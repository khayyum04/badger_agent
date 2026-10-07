"""Harbor external agent that runs mini-swe-agent against a Terminal-Bench task container.

    harbor run -d terminal-bench@2.0 --agent-import-path badger_mini.harbor_agent:BadgerMiniAgent -i fix-git

The LLM client (litellm, via mini-swe-agent) runs on the host, so the API key never enters the
task container; only bash commands go in, through Harbor's ``environment.exec()``.

mini-swe-agent's loop is synchronous, Harbor's is async: the agent runs in a worker thread and
each command is scheduled back onto Harbor's event loop.

Settings (env vars; secrets come from ``op run --env-file=mini_agent/.env.op``, tuning from ``mini_agent/.env``):
  LLM_BASE_URL, LLM_API_KEY, LLM_MODEL   endpoint (LLM_MODEL wins over harbor's -m)
  LLM_LITELLM_PROVIDER                   litellm provider prefix for LLM_MODEL (default: openai)
  LLM_MAX_TOKENS, LLM_TEMPERATURE, LLM_TOP_P
  AGENT_MAX_TURNS, AGENT_COMMAND_TIMEOUT_SEC
  AGENT_STRIP_REASONING                  on = don't re-send the model's earlier thinking (default: off)
  AGENT_COMPACTION                       on = self-compaction, see compaction.py (default: off)
  AGENT_THINKING_CAP                     max_tokens per reply; a reply after an overrun gets LLM_MAX_TOKENS (default: off)
  BADGER_CONFIG                          agent yaml (default: config/terminal_bench.yaml)
"""

import asyncio
import contextlib
import os
import shlex
import threading
import time
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

os.environ.setdefault("MSWEA_SILENT_STARTUP", "1")
os.environ.setdefault("MSWEA_COST_TRACKING", "ignore_errors")

from harbor.agents.base import BaseAgent  # noqa: E402
from harbor.environments.base import BaseEnvironment  # noqa: E402
from harbor.models.agent.context import AgentContext  # noqa: E402
from minisweagent.agents.default import DefaultAgent  # noqa: E402
from minisweagent.exceptions import Submitted  # noqa: E402
import litellm  # noqa: E402
from minisweagent.models import get_model  # noqa: E402
from minisweagent.models.litellm_model import LitellmModel  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from badger_mini.compaction import Compactor  # noqa: E402

PACKAGE_DIR = Path(__file__).resolve().parent
# override=False: values injected by `op run` must win over anything in mini_agent/.env
load_dotenv(PACKAGE_DIR.parent / ".env", override=False)

SUBMIT_MARKER = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"


class HarborEnvironmentConfig(BaseModel):
    timeout: int = 180
    """Per-command timeout (s). Enforced in the container so partial output survives a timeout."""
    cwd: str = ""
    """Working directory; empty = the task image's WORKDIR."""
    env: dict[str, str] = {}


class HarborEnvironment:
    """mini-swe-agent Environment that executes commands in Harbor's task container."""

    def __init__(self, environment: BaseEnvironment, loop: asyncio.AbstractEventLoop, stop: threading.Event, **kwargs):
        self.config = HarborEnvironmentConfig(**kwargs)
        self._environment = environment
        self._loop = loop
        self._stop = stop

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        if self._stop.is_set():
            raise RuntimeError("Harbor stopped the agent (task timeout)")
        timeout = timeout or self.config.timeout
        # `timeout` kills the command inside the container but keeps what it printed so far;
        # Harbor's own timeout (the outer bound) would discard all output.
        inner = shlex.quote(action.get("command", ""))
        command = (
            f"if command -v timeout >/dev/null 2>&1; then timeout -k 5 {timeout} bash -c {inner}; "
            f"else bash -c {inner}; fi"
        )
        start = time.monotonic()
        future = asyncio.run_coroutine_threadsafe(
            self._environment.exec(
                command=command,
                cwd=cwd or self.config.cwd or None,
                env=self.config.env or None,
                timeout_sec=timeout + 30,
            ),
            self._loop,
        )
        try:
            result = future.result()
            output = {
                "output": (result.stdout or "") + (result.stderr or ""),
                "returncode": result.return_code,
                "exception_info": "",
            }
            if result.return_code in (124, 137) and time.monotonic() - start >= timeout:
                output["exception_info"] = (
                    f"The command was killed after the {timeout}s timeout; output so far is shown. "
                    "For long builds/training, run in the background with a log file "
                    "(nohup cmd > /tmp/job.log 2>&1 &) and check the log in later commands."
                )
        except Exception as e:
            output = {
                "output": "",
                "returncode": -1,
                "exception_info": f"An error occurred while executing the command: {e}",
                "extra": {"exception_type": type(e).__name__, "exception": str(e)},
            }
        self._check_finished(output)
        return output

    def _check_finished(self, output: dict):
        lines = output.get("output", "").lstrip().splitlines(keepends=True)
        if lines and lines[0].strip() == SUBMIT_MARKER and output["returncode"] == 0:
            submission = "".join(lines[1:])
            raise Submitted(
                {"role": "exit", "content": submission, "extra": {"exit_status": "Submitted", "submission": submission}}
            )

    def get_template_vars(self, **kwargs) -> dict[str, Any]:
        return self.config.model_dump() | kwargs

    def serialize(self) -> dict:
        return {
            "info": {
                "config": {
                    "environment": self.config.model_dump(mode="json"),
                    "environment_type": f"{self.__class__.__module__}.{self.__class__.__name__}",
                }
            }
        }


class BadgerLitellmModel(LitellmModel):
    """LitellmModel that doesn't retry 400s: a wrong model id or bad param never fixes itself.

    The two context-saving switches are set by BadgerMiniAgent.run() after construction
    (get_model() deep-copies its config, so the shared Compactor can't be passed through it).
    """

    abort_exceptions = [*LitellmModel.abort_exceptions, litellm.exceptions.BadRequestError]
    strip_reasoning = False
    compactor: Compactor | None = None
    # Thinking cap: most replies get `thinking_cap` tokens (thinking included). A reply that hit its limit
    # (finish_reason=length, usually a FormatError with no tool call) makes the next call use the full
    # max_tokens, until a reply finishes normally. Long thinking turns are what run tasks out of time.
    thinking_cap: int = 0
    _boost_next = False
    n_boosted_calls = 0

    def _prepare_messages_for_api(self, messages: list[dict]) -> list[dict]:
        if self.strip_reasoning:
            # Stored replies carry their thinking (twice: reasoning_content and provider_specific_fields),
            # and the gateway bills it as input on every later turn. The model thinks afresh each turn.
            messages = [
                {k: m[k] for k in ("role", "content", "tool_calls") if k in m} if m.get("role") == "assistant" else m
                for m in messages
            ]
        return super()._prepare_messages_for_api(messages)

    def _query(self, messages: list[dict[str, str]], **kwargs):
        boosted = self._boost_next
        if self.thinking_cap and not boosted:
            kwargs = {**kwargs, "max_tokens": min(self.thinking_cap, self.config.model_kwargs.get("max_tokens") or self.thinking_cap)}
        if boosted:
            self.n_boosted_calls += 1
        if not self.compactor:
            response = super()._query(messages, **kwargs)
        else:
            # The parent hardcodes tools=[BASH_TOOL], so its call is repeated here with the compactor's tools.
            response = litellm.completion(
                model=self.config.model_name,
                messages=messages,
                tools=self.compactor.tools(),
                **(self.config.model_kwargs | kwargs | self.compactor.request_kwargs()),
            )
        if self.thinking_cap:
            self._boost_next = response.choices[0].finish_reason == "length"
        return response

    def _parse_actions(self, response) -> list[dict]:
        if self.compactor:
            actions = self.compactor.parse(response.choices[0].message.tool_calls or [])
            if actions is not None:
                return actions
        return super()._parse_actions(response)


# Endpoint misconfiguration: fail the trial loudly instead of letting every task "finish" with no work.
CONFIG_ERRORS = (
    litellm.exceptions.AuthenticationError,
    litellm.exceptions.NotFoundError,
    litellm.exceptions.PermissionDeniedError,
)


def _is_config_error(e: Exception) -> bool:
    if isinstance(e, litellm.exceptions.ContextWindowExceededError):
        return False
    return isinstance(e, CONFIG_ERRORS) or isinstance(e, litellm.exceptions.BadRequestError)


class HarborSyncedAgent(DefaultAgent):
    """DefaultAgent that mirrors token usage into Harbor's AgentContext after every message.

    Harbor reads the context after run() returns *or is cancelled on timeout*, so it must be
    current at all times. Usage is taken from every stored response, including ones that ended
    in a FormatError (e.g. a reasoning overrun with no tool call) - those tokens are billed too.
    """

    def __init__(
        self,
        *args,
        harbor_context: AgentContext,
        stop: threading.Event,
        compactor: Compactor | None = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.harbor_context = harbor_context
        self._stop = stop
        self.compactor = compactor
        self.n_input_tokens = 0
        self.n_output_tokens = 0
        self.n_cache_tokens = 0

    def query(self) -> dict:
        if self._stop.is_set():
            raise RuntimeError("Harbor stopped the agent (task timeout)")
        if self.compactor and (stage_message := self.compactor.stage_message(self.messages)):
            self.add_messages(stage_message)
        return super().query()

    def execute_actions(self, message: dict) -> list[dict]:
        actions = message.get("extra", {}).get("actions", [])
        if self.compactor and actions and actions[0].get("tool") == "self_compact":
            self.messages = self.compactor.apply(self.messages, actions[0])
            self._sync_context()
            return []
        return super().execute_actions(message)

    def add_messages(self, *messages: dict) -> list[dict]:
        for message in messages:
            response = (message.get("extra") or {}).get("response")
            usage = (response.get("usage") if isinstance(response, dict) else None) or {}
            self.n_input_tokens += usage.get("prompt_tokens") or 0
            self.n_output_tokens += usage.get("completion_tokens") or 0
            self.n_cache_tokens += (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        added = super().add_messages(*messages)
        self._sync_context()
        return added

    def _sync_context(self):
        ctx = self.harbor_context
        ctx.n_input_tokens = self.n_input_tokens
        ctx.n_output_tokens = self.n_output_tokens
        ctx.n_cache_tokens = self.n_cache_tokens
        ctx.metadata = {
            "n_model_calls": self.n_calls,
            "n_messages": len(self.messages),
            "exit_status": (self.messages[-1].get("extra") or {}).get("exit_status", "") if self.messages else "",
            "trajectory_path": str(self.config.output_path),
            "strip_reasoning": getattr(self.model, "strip_reasoning", False),
            "thinking_cap": getattr(self.model, "thinking_cap", 0),
            "n_boosted_calls": getattr(self.model, "n_boosted_calls", 0),
        }
        if self.compactor:
            ctx.metadata["compactions"] = self.compactor.log


def _load_config() -> dict:
    path = Path(os.environ.get("BADGER_CONFIG") or PACKAGE_DIR / "config" / "terminal_bench.yaml")
    if not path.is_absolute() and not path.exists():
        path = PACKAGE_DIR / "config" / path
    return yaml.safe_load(path.read_text())


def _model_config(config: dict, harbor_model_name: str | None) -> dict:
    """Build the litellm model config from env vars; endpoint changes never need code changes."""
    model_id = os.environ.get("LLM_MODEL")
    if model_id:
        model_name = f"{os.environ.get('LLM_LITELLM_PROVIDER', 'openai')}/{model_id}"
    elif harbor_model_name:
        model_name = harbor_model_name
    else:
        raise ValueError("No model configured. Set LLM_MODEL (mini_agent/.env.op) or pass -m to harbor run.")
    model_kwargs = dict(config.get("model_kwargs") or {})
    for env_key, kwarg, cast in [
        ("LLM_BASE_URL", "api_base", str),
        ("LLM_API_KEY", "api_key", str),
        ("LLM_MAX_TOKENS", "max_tokens", int),
        ("LLM_TEMPERATURE", "temperature", float),
        ("LLM_TOP_P", "top_p", float),
    ]:
        if os.environ.get(env_key):
            model_kwargs[kwarg] = cast(os.environ[env_key])
    return {**config, "model_name": model_name, "model_kwargs": model_kwargs}


async def _run_in_daemon_thread(fn, *args):
    """Like asyncio.to_thread, but in a daemon thread: asyncio.to_thread's executor is joined at
    interpreter exit, so Ctrl+C or a Harbor timeout would hang until a blocked model call or a
    retry backoff (up to 60 s per attempt) finished."""
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def resolve(result, error):
        if not future.done():
            future.set_exception(error) if error else future.set_result(result)

    def target():
        try:
            outcome = (fn(*args), None)
        except BaseException as e:
            outcome = (None, e)
        with contextlib.suppress(RuntimeError):  # loop already closed: nobody is waiting
            loop.call_soon_threadsafe(resolve, *outcome)

    threading.Thread(target=target, daemon=True, name="mini-swe-agent").start()
    return await future


class BadgerMiniAgent(BaseAgent):
    @staticmethod
    def name() -> str:
        return "badger-mini-swe-agent"

    def version(self) -> str | None:
        return "0.1.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        pass

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        config = _load_config()
        agent_config = dict(config.get("agent") or {})
        if os.environ.get("AGENT_MAX_TURNS"):
            agent_config["step_limit"] = int(os.environ["AGENT_MAX_TURNS"])
        env_config = dict(config.get("environment") or {})
        if os.environ.get("AGENT_COMMAND_TIMEOUT_SEC"):
            env_config["timeout"] = int(os.environ["AGENT_COMMAND_TIMEOUT_SEC"])

        stop = threading.Event()
        strip_reasoning = os.environ.get("AGENT_STRIP_REASONING", "off").lower() == "on"
        compactor = Compactor.from_env(archive_dir=self.logs_dir, reasoning_sent=not strip_reasoning)
        model = get_model(config=_model_config(config.get("model") or {}, self.model_name))
        model.strip_reasoning = strip_reasoning
        model.compactor = compactor
        model.thinking_cap = int(os.environ.get("AGENT_THINKING_CAP") or 0)
        env = HarborEnvironment(environment, asyncio.get_running_loop(), stop, **env_config)
        agent = HarborSyncedAgent(
            model,
            env,
            harbor_context=context,
            stop=stop,
            compactor=compactor,
            output_path=self.logs_dir / "mini-swe-agent.trajectory.json",
            **agent_config,
        )
        try:
            result = await _run_in_daemon_thread(agent.run, instruction)
        except asyncio.CancelledError:
            stop.set()  # the worker thread exits at its next model call or command
            raise
        except Exception as e:
            if _is_config_error(e):
                raise
            # If run() raises, Harbor skips the verifier; return so the container's state still gets graded.
            self.logger.warning("mini-swe-agent crashed (%s: %s); returning so the task is still graded", type(e).__name__, e)
            return
        self.logger.info("mini-swe-agent finished: %s", result.get("exit_status"))
