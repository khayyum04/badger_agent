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
  AGENT_THINKING_CAP                     max_tokens per reply; a reply after an overrun gets LLM_MAX_TOKENS (default: 8192; 0 = off)
  AGENT_TIME_AWARENESS                   on = show time used in each command result, nudge at 10 min (default: on)
  AGENT_SUBMIT_CHECK                     on = the first submit is held back and answered with SUBMIT_CHECK_MESSAGE (default: on)
  AGENT_NO_BENCHMARK_LOOKUP              on = prompt line: don't look up this benchmark or its solutions (default: on)
  AGENT_OVERRUN_RECOVERY                 on = keep the thinking of cut-off replies as notes; thinking off after 2 in a row (default: on)
  AGENT_SUBMIT_REVIEW                    on = the first submit is answered by a fresh-context reviewer instead of the checklist (default: off)
  AGENT_KNOWN_TIME_LIMIT                 on = read the task's time limit from Harbor and show it (default: off)
  AGENT_REASONING_EFFORT                 low | medium | high | xhigh, sent as reasoning_effort (default: unset = model's own, xhigh)
  BADGER_CONFIG                          agent yaml (default: config/terminal_bench.yaml)

The five settings defaulting to on are the full-all-v1 configuration (56/89, docs/research/full-all-v1.md).
"""

import asyncio
import contextlib
import inspect
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
from minisweagent.exceptions import FormatError, Submitted  # noqa: E402
import litellm  # noqa: E402
from minisweagent.models import get_model  # noqa: E402
from minisweagent.models.litellm_model import LitellmModel  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from badger_mini.compaction import Compactor  # noqa: E402
from badger_mini.review import run_review  # noqa: E402

PACKAGE_DIR = Path(__file__).resolve().parent
# override=False: values injected by `op run` must win over anything in mini_agent/.env
load_dotenv(PACKAGE_DIR.parent / ".env", override=False)

SUBMIT_MARKER = "COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"

# Time awareness (AGENT_TIME_AWARENESS): the agent can't see the task's time limit, so each command
# result shows the time used, and one nudge asks for a working answer at NUDGE_AFTER_SEC.
CLOCK_TEMPLATE = "\n[time used: {minutes} min; the limit is unknown and may be as short as 15 min]"
NUDGE_AFTER_SEC = 600
NUDGE_MESSAGE = (
    "\n10 minutes used. If the required output isn't written yet, write your best version now, "
    "then keep improving it."
)
# Known time limit (AGENT_KNOWN_TIME_LIMIT): Harbor knows each task's limit but passes it only to its oracle
# agent, so it's read from the running Trial (_harbor_agent_timeout_sec). Then the clock shows the real limit
# and the nudge comes at NUDGE_AT_FRACTION of it instead of at NUDGE_AFTER_SEC.
CLOCK_KNOWN_TEMPLATE = "\n[time used: {minutes} of {limit} min]"
NUDGE_AT_FRACTION = 0.6
NUDGE_KNOWN_MESSAGE = (
    "\n{minutes} of {limit} minutes used. If the required output isn't written yet, write your best version "
    "now, then keep improving it."
)


def _harbor_agent_timeout_sec() -> float | None:
    """The running Harbor Trial's agent timeout (task limit x multiplier), found up the call stack."""
    frame = inspect.currentframe()
    try:
        while frame is not None:
            candidate = frame.f_locals.get("self")
            value = getattr(candidate, "_agent_timeout_sec", None) if candidate is not None else None
            if isinstance(value, (int, float)) and value > 0:
                return float(value)
            frame = frame.f_back
    finally:
        del frame
    return None

# Submit check (AGENT_SUBMIT_CHECK): the agent verifies against its own reading of the task, and the hidden
# tests fail it on requirements it skipped (leftover build files in the output directory, changes the task
# didn't ask for). A prompt rule read at the start didn't stop that, so the reminder comes at the moment of
# the decision: the first submit is answered with this checklist; the next submit goes through.
SUBMIT_CHECK_MESSAGE = """Not submitted yet: one final check first (this happens only once).
1. Re-read the task. Check every explicit requirement: exact paths and file names, output format,
   function signatures, and any stated limits (speed, size, what must stay unchanged).
2. List the directories the task names (ls -la). Delete files you created there only to build or test
   (scratch scripts, compiled test binaries, logs) unless the task asks for them. Keep what the task needs.
3. Make sure you changed only what the task asked for: don't rewrite history, delete data, or change
   settings the task didn't mention.
Fix anything that fails. Then submit again with: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"""


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
        self.submit_check = False
        self.submit_checked_at: float | None = None
        """time.time() of the held-back first submit; None until then."""

    submit_reviewer: Any = None  # callable returning the message for a held-back submit (AGENT_SUBMIT_REVIEW)

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None, check: bool = True) -> dict[str, Any]:
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
        if check:
            self._check_finished(output)
        return output

    def _check_finished(self, output: dict):
        lines = output.get("output", "").lstrip().splitlines(keepends=True)
        if lines and lines[0].strip() == SUBMIT_MARKER and output["returncode"] == 0:
            if self.submit_check and self.submit_checked_at is None:
                self.submit_checked_at = time.time()
                output["output"] = self.submit_reviewer() if self.submit_reviewer else SUBMIT_CHECK_MESSAGE
                return
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
    overrun_recovery = False
    _overruns_in_row = 0
    n_overrun_notes = 0
    n_thinking_off_calls = 0
    thinking_off_rejected = False
    reasoning_effort: str | None = None

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
        if self.reasoning_effort:
            extra_body = {**(self.config.model_kwargs.get("extra_body") or {}), **(kwargs.get("extra_body") or {})}
            kwargs = {**kwargs, "extra_body": {**extra_body, "reasoning_effort": self.reasoning_effort}}
        thinking_off = (
            self.overrun_recovery
            and not self.thinking_off_rejected
            and self._overruns_in_row >= OVERRUN_THINKING_OFF_AFTER
        )
        if not thinking_off:
            response = self._complete(messages, kwargs)
        else:
            extra_body = {**(self.config.model_kwargs.get("extra_body") or {}), **(kwargs.get("extra_body") or {})}
            try:
                response = self._complete(messages, {**kwargs, "extra_body": {**extra_body, **THINKING_OFF_KWARGS}})
                self.n_thinking_off_calls += 1
            except litellm.exceptions.BadRequestError:
                # The endpoint doesn't take the switch: stop sending it for this task, retry as a normal call.
                self.thinking_off_rejected = True
                response = self._complete(messages, kwargs)
        overrun = response.choices[0].finish_reason == "length"
        if self.thinking_cap:
            self._boost_next = overrun
        self._overruns_in_row = self._overruns_in_row + 1 if overrun else 0
        return response

    def _complete(self, messages: list[dict[str, str]], kwargs: dict):
        if not self.compactor:
            return super()._query(messages, **kwargs)
        # The parent hardcodes tools=[BASH_TOOL], so its call is repeated here with the compactor's tools.
        return litellm.completion(
            model=self.config.model_name,
            messages=messages,
            tools=self.compactor.tools(),
            **(self.config.model_kwargs | kwargs | self.compactor.request_kwargs()),
        )

    def _parse_actions(self, response) -> list[dict]:
        try:
            if self.compactor:
                actions = self.compactor.parse(response.choices[0].message.tool_calls or [])
                if actions is not None:
                    return actions
            return super()._parse_actions(response)
        except FormatError as e:
            if self.overrun_recovery and response.choices[0].finish_reason == "length":
                if notes := _overrun_notes(response.choices[0].message):
                    e.messages[0]["content"] += OVERRUN_NOTES_TEMPLATE.format(notes=notes)
                    self.n_overrun_notes += 1
            raise


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
        self.time_awareness = False
        self.nudged_at_sec: int | None = None
        self.extra_template_vars["time_awareness"] = False  # the prompt templates render with StrictUndefined
        self.extra_template_vars["no_benchmark_lookup"] = False
        self.time_limit_sec: float | None = None
        self.extra_template_vars["time_limit_min"] = None
        self.review: dict | None = None

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
        if not self.time_awareness:
            return super().execute_actions(message)
        # Same as DefaultAgent.execute_actions(), with the clock added before the results are stored.
        outputs = [self.env.execute(action) for action in message.get("extra", {}).get("actions", [])]
        observations = self.model.format_observation_messages(message, outputs, self.get_template_vars())
        if observations and isinstance(observations[-1].get("content"), str):
            observations[-1]["content"] += self._clock_text()
        return self.add_messages(*observations)

    def _clock_text(self) -> str:
        elapsed = int(time.time() - self._start_time)
        if self.time_limit_sec:
            limit = round(self.time_limit_sec / 60)
            text = CLOCK_KNOWN_TEMPLATE.format(minutes=elapsed // 60, limit=limit)
            if self.nudged_at_sec is None and elapsed >= NUDGE_AT_FRACTION * self.time_limit_sec:
                self.nudged_at_sec = elapsed
                text += NUDGE_KNOWN_MESSAGE.format(minutes=elapsed // 60, limit=limit)
            return text
        text = CLOCK_TEMPLATE.format(minutes=elapsed // 60)
        if self.nudged_at_sec is None and elapsed >= NUDGE_AFTER_SEC:
            self.nudged_at_sec = elapsed
            text += NUDGE_MESSAGE
        return text

    def submit_review(self) -> str:
        """Runs the fresh-context reviewer (review.py); its tokens count like the agent's."""

        def add_usage(n_in: int, n_out: int):
            self.n_input_tokens += n_in
            self.n_output_tokens += n_out
            self._sync_context()

        self.review = run_review(
            task=self.extra_template_vars.get("task", ""),
            model_name=self.model.config.model_name,
            model_kwargs=dict(self.model.config.model_kwargs),
            run_command=lambda command, timeout: self.env.execute({"command": command}, timeout=timeout, check=False),
            add_usage=add_usage,
            should_stop=self._stop.is_set,
        )
        self._sync_context()
        return self.review["message"]

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
            "overrun_recovery": getattr(self.model, "overrun_recovery", False),
            "n_overrun_notes": getattr(self.model, "n_overrun_notes", 0),
            "n_thinking_off_calls": getattr(self.model, "n_thinking_off_calls", 0),
            "thinking_off_rejected": getattr(self.model, "thinking_off_rejected", False),
            "time_awareness": self.time_awareness,
            "nudged_at_sec": self.nudged_at_sec,
            "submit_check": getattr(self.env, "submit_check", False),
            "submit_checked_at_sec": (
                int(self.env.submit_checked_at - self._start_time)
                if getattr(self.env, "submit_checked_at", None) is not None
                else None
            ),
            "no_benchmark_lookup": self.extra_template_vars.get("no_benchmark_lookup", False),
            "submit_review": getattr(self.env, "submit_reviewer", None) is not None,
            "review_verdict": (self.review or {}).get("verdict", "")[:1000] or None,
            "review_commands": (self.review or {}).get("n_commands"),
            "review_sec": (self.review or {}).get("seconds"),
            "time_limit_sec": self.time_limit_sec,
            "reasoning_effort": getattr(self.model, "reasoning_effort", None),
        }
        if self.compactor:
            ctx.metadata["compactions"] = self.compactor.log

# Overrun recovery (AGENT_OVERRUN_RECOVERY): a reply cut off at its token limit before calling the tool is
# discarded, so the model restarts its thinking from zero each time (31% of all output in full-capta-v1).
# The retry note carries the start and end of that thinking, and after a few overruns in a row the next calls
# go out with thinking off until a reply finishes normally. docs/plans/overrun-recovery.md
OVERRUN_NOTES_HEAD = 1500
OVERRUN_NOTES_TAIL = 4500
OVERRUN_THINKING_OFF_AFTER = 2
OVERRUN_NOTES_TEMPLATE = """

Your notes from the cut-off reply (its thinking: the start, then the end). Continue from them; don't start
over. They are notes, not checked results. Reply with one bash tool call now, e.g. save the plan and key
findings to /tmp/notes.md, or run a short script that tests the next idea.
<notes>
{notes}
</notes>"""
THINKING_OFF_KWARGS = {"chat_template_kwargs": {"enable_thinking": False}}  # Qwen's switch, sent as extra_body

# Reasoning effort (AGENT_REASONING_EFFORT): Qwen3.8 thinks at "xhigh" unless told otherwise. On a hard maths
# question, "low" used about a quarter of the tokens with the same answer (endpoint probe, 2026-11-05).
# Sent as a top-level request field (extra_body), the form that cut the most in that probe.
REASONING_EFFORTS = ("low", "medium", "high", "xhigh")


def _reasoning_effort() -> str | None:
    value = (os.environ.get("AGENT_REASONING_EFFORT") or "").strip().lower()
    if not value:
        return None
    if value not in REASONING_EFFORTS:
        raise ValueError(f"AGENT_REASONING_EFFORT={value!r}: use one of {', '.join(REASONING_EFFORTS)}, or leave it unset")
    return value


def _overrun_notes(message) -> str:
    """The cut-off reply's thinking (reasoning_content, else content), trimmed to its head and tail."""
    text = (getattr(message, "reasoning_content", None) or getattr(message, "content", None) or "").strip()
    text = text.removeprefix("<think>").strip()
    if len(text) > OVERRUN_NOTES_HEAD + OVERRUN_NOTES_TAIL:
        omitted = len(text) - OVERRUN_NOTES_HEAD - OVERRUN_NOTES_TAIL
        text = f"{text[:OVERRUN_NOTES_HEAD]}\n[... {omitted} characters omitted ...]\n{text[-OVERRUN_NOTES_TAIL:]}"
    return text

# Defaults: the full-all-v1 configuration. Set a switch to off (or AGENT_THINKING_CAP=0) to turn it off.
DEFAULT_THINKING_CAP = 8192


def _switch(name: str, default: str = "on") -> bool:
    return (os.environ.get(name) or default).strip().lower() == "on"


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
        model.thinking_cap = int(os.environ.get("AGENT_THINKING_CAP") or DEFAULT_THINKING_CAP)
        model.overrun_recovery = _switch("AGENT_OVERRUN_RECOVERY")
        model.reasoning_effort = _reasoning_effort()
        env = HarborEnvironment(environment, asyncio.get_running_loop(), stop, **env_config)
        env.submit_check = _switch("AGENT_SUBMIT_CHECK")
        agent = HarborSyncedAgent(
            model,
            env,
            harbor_context=context,
            stop=stop,
            compactor=compactor,
            output_path=self.logs_dir / "mini-swe-agent.trajectory.json",
            **agent_config,
        )
        agent.time_awareness = _switch("AGENT_TIME_AWARENESS")
        agent.extra_template_vars["time_awareness"] = agent.time_awareness
        agent.extra_template_vars["no_benchmark_lookup"] = _switch("AGENT_NO_BENCHMARK_LOOKUP")
        if _switch("AGENT_SUBMIT_REVIEW", default="off"):
            env.submit_check = True  # the review uses the submit check's hold on the first submit
            env.submit_reviewer = agent.submit_review
        if agent.time_awareness and _switch("AGENT_KNOWN_TIME_LIMIT", default="off"):
            agent.time_limit_sec = _harbor_agent_timeout_sec()
            if agent.time_limit_sec:
                agent.extra_template_vars["time_limit_min"] = round(agent.time_limit_sec / 60)
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
