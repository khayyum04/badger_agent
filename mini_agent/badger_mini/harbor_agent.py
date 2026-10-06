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
  AGENT_OUTPUT_LIMIT, AGENT_OUTPUT_HEAD, AGENT_OUTPUT_TAIL   output offloading (limit 0 = off)
  AGENT_OUTPUT_VIEW_LIMIT                offloading limit for file views (cat/nl/head/tail/sed -n)
  BADGER_CONFIG                          agent yaml (default: config/terminal_bench.yaml)
"""

import asyncio
import contextlib
import os
import re
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

PACKAGE_DIR = Path(__file__).resolve().parent
# override=False: values injected by `op run` must win over anything in mini_agent/.env
load_dotenv(PACKAGE_DIR.parent / ".env", override=False)

SUBMIT_MARKER = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"
# First line of a command's output when the wrapper saved it to a file in the container; stripped in execute().
SAVED_MARKER = "BADGER_OUTPUT_SAVED_7f3a"
# A command that only displays files: cat/nl/head/tail/sed -n (each optionally piped into a filter), possibly
# chained with `&&`/`;` to `cd` or `echo` separators, and no heredoc. The model asked to read the file, so
# cutting it makes the model re-read it in small pieces; such outputs get the higher output_view_limit.
FILE_VIEW_RE = re.compile(r"^(?:cat|nl|head|tail|sed\s+-n)\b")
_VIEW_FILLER_RE = re.compile(r"^(?:cd|echo|printf)\b")


def is_file_view(command: str) -> bool:
    if "<<" in command or "||" in command:
        return False
    parts = [p.strip() for p in re.split(r"&&|;|\n", command) if p.strip()]
    views = [p for p in parts if FILE_VIEW_RE.match(p)]
    return bool(views) and all(FILE_VIEW_RE.match(p) or _VIEW_FILLER_RE.match(p) for p in parts)


class HarborEnvironmentConfig(BaseModel):
    timeout: int = 180
    """Per-command timeout (s). Enforced in the container so partial output survives a timeout."""
    cwd: str = ""
    """Working directory; empty = the task image's WORKDIR."""
    env: dict[str, str] = {}
    output_limit: int = 2000
    """Outputs longer than this (chars) are shown as a head/tail preview plus a file path; 0 = off."""
    output_view_limit: int = 10000
    """Limit for commands that display a file (FILE_VIEW_RE); those are shown in full up to this size."""
    output_head: int = 300
    output_tail: int = 1000
    output_dir: str = "/tmp/agent_out"
    """Where every command's full output is saved, inside the container."""


class HarborEnvironment:
    """mini-swe-agent Environment that executes commands in Harbor's task container."""

    def __init__(self, environment: BaseEnvironment, loop: asyncio.AbstractEventLoop, stop: threading.Event, **kwargs):
        self.config = HarborEnvironmentConfig(**kwargs)
        self._environment = environment
        self._loop = loop
        self._stop = stop
        self._n_commands = 0

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        if self._stop.is_set():
            raise RuntimeError("Harbor stopped the agent (task timeout)")
        timeout = timeout or self.config.timeout
        self._n_commands += 1
        path = f"{self.config.output_dir}/cmd_{self._n_commands}.log"
        command = self._wrap(action.get("command", ""), timeout, path)
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
            text = (result.stdout or "") + (result.stderr or "")
            saved = text.startswith(SAVED_MARKER + "\n")
            if saved:
                text = text[len(SAVED_MARKER) + 1 :]
            output = {"output": text, "returncode": result.return_code, "exception_info": ""}
            limit = self.config.output_limit
            if is_file_view(action.get("command", "")):
                limit = max(limit, self.config.output_view_limit)
            if saved and len(text) > limit:
                output |= {
                    "output_head": text[: self.config.output_head],
                    "output_tail": text[-self.config.output_tail :] if self.config.output_tail else "",
                    "total_chars": len(text),
                    "full_output_path": path,
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

    def _wrap(self, command: str, timeout: int, path: str) -> str:
        # `timeout` kills the command inside the container but keeps what it printed so far;
        # Harbor's own timeout (the outer bound) would discard all output.
        inner = shlex.quote(command)
        run = (
            f"if command -v timeout >/dev/null 2>&1; then timeout -k 5 {timeout} bash -c {inner}; "
            f"else bash -c {inner}; fi"
        )
        if self.config.output_limit <= 0:
            return run
        # Save the full output in the container so the model can grep it later; if the file can't be
        # created, run the command as before (no marker, so execute() won't offload).
        d, p = shlex.quote(self.config.output_dir), shlex.quote(path)
        return (
            f"if mkdir -p {d} 2>/dev/null && : > {p} 2>/dev/null; then "
            f"{{ {run} ; }} > {p} 2>&1; rc=$?; echo {SAVED_MARKER}; cat {p}; exit $rc; "
            f"else {run}; fi"
        )

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
    """LitellmModel that doesn't retry 400s: a wrong model id or bad param never fixes itself."""

    abort_exceptions = [*LitellmModel.abort_exceptions, litellm.exceptions.BadRequestError]


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

    def __init__(self, *args, harbor_context: AgentContext, stop: threading.Event, **kwargs):
        super().__init__(*args, **kwargs)
        self.harbor_context = harbor_context
        self._stop = stop
        self.n_input_tokens = 0
        self.n_output_tokens = 0
        self.n_cache_tokens = 0

    def query(self) -> dict:
        if self._stop.is_set():
            raise RuntimeError("Harbor stopped the agent (task timeout)")
        return super().query()

    def add_messages(self, *messages: dict) -> list[dict]:
        for message in messages:
            response = (message.get("extra") or {}).get("response")
            usage = (response.get("usage") if isinstance(response, dict) else None) or {}
            self.n_input_tokens += usage.get("prompt_tokens") or 0
            self.n_output_tokens += usage.get("completion_tokens") or 0
            self.n_cache_tokens += (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
        added = super().add_messages(*messages)
        ctx = self.harbor_context
        ctx.n_input_tokens = self.n_input_tokens
        ctx.n_output_tokens = self.n_output_tokens
        ctx.n_cache_tokens = self.n_cache_tokens
        ctx.metadata = {
            "n_model_calls": self.n_calls,
            "n_messages": len(self.messages),
            "exit_status": (self.messages[-1].get("extra") or {}).get("exit_status", "") if self.messages else "",
            "trajectory_path": str(self.config.output_path),
        }
        return added


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
        for env_key, key in (
            ("AGENT_OUTPUT_LIMIT", "output_limit"),
            ("AGENT_OUTPUT_VIEW_LIMIT", "output_view_limit"),
            ("AGENT_OUTPUT_HEAD", "output_head"),
            ("AGENT_OUTPUT_TAIL", "output_tail"),
        ):
            if os.environ.get(env_key):
                env_config[key] = int(os.environ[env_key])

        stop = threading.Event()
        model = get_model(config=_model_config(config.get("model") or {}, self.model_name))
        env = HarborEnvironment(environment, asyncio.get_running_loop(), stop, **env_config)
        agent = HarborSyncedAgent(
            model,
            env,
            harbor_context=context,
            stop=stop,
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
