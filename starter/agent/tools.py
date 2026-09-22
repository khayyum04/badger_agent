"""Action parsing and command execution.

This file is the bridge between the LLM's text output and the Docker
container. It handles two things:

1. **Parsing** — Extracting a structured ``Action`` from the LLM's
   free-text response. The baseline protocol is intentionally simple so
   that even small local models (~7B) can follow it reliably:
   - A fenced ``bash`` code block → run that command in the container.
   - The literal string ``TASK_COMPLETE`` → stop the loop.
   - Anything else → the LLM didn't follow the protocol; agent.py will
     send a nudge message asking it to try again.

2. **Execution** — Running the parsed command inside the task's Docker
   container via Harbor's ``environment.exec()`` and returning a structured
   ``ShellResult``. Rendering that into text for the model is
   ``prompts.observation_message``'s job, not this module's — ``tools.py``
   stays a pure execution layer.

Output truncation
=================
Commands can produce megabytes of output (e.g., ``find /``). Feeding all of
that into the conversation would blow the model's context window. So
``run_shell()`` truncates long output to ``MAX_OBSERVATION_CHARS``, keeping
the first and last halves with a "[N characters omitted]" marker in between.
This is a blunt strategy — smarter truncation (e.g., keeping error lines,
tail-only, or summarizing) is a good improvement target.

Improvement ideas
=================
- Add richer action types (read_file, write_file, search) so the LLM
  doesn't have to compose raw bash for common operations.
- Parse multiple code blocks and execute them sequentially.
- Detect and break out of repeated-command loops.
- Smarter truncation: prioritize stderr, keep the last N lines, etc.
"""

import re
from dataclasses import dataclass

from harbor.environments.base import BaseEnvironment

CODE_BLOCK_RE = re.compile(r"```(?:bash|sh|shell)?\s*\n(.*?)```", re.DOTALL)
"""Matches a Markdown fenced code block tagged as bash/sh/shell (or untagged).
The captured group (1) is everything between the opening and closing fences."""

DONE_MARKER = "TASK_COMPLETE"
"""The literal string the LLM must emit (outside a code block) to signal
that it believes the task is finished."""

MAX_OBSERVATION_CHARS = 6000
"""Maximum characters to keep from a command's combined output. Longer
output is truncated to the first and last halves with an omission notice."""


@dataclass
class Action:
    """A single action parsed from the LLM's response.

    Attributes
    ----------
    kind : str
        One of ``"shell"`` (run a command), ``"done"`` (task complete),
        or ``"none"`` (no valid action found — LLM didn't follow protocol).
    command : str
        The bash command to execute. Only meaningful when ``kind == "shell"``.
    """

    kind: str
    command: str = ""


@dataclass
class ShellResult:
    """The structured result of executing one shell command.

    ``events.ObservationEvent`` is built straight from this (see
    ``context.record_observation``); rendering it into text for the model is
    ``prompts.observation_message``'s job.

    Attributes
    ----------
    command : str
        The command that was run, carried through unchanged from ``run_shell``'s
        own ``command`` argument.
    exit_code : int | None
        The process's exit code, or ``None`` if it never produced one
        (``did_not_complete`` is true).
    stdout, stderr : str
        Already truncated to ``MAX_OBSERVATION_CHARS`` each, same as today.
        Empty strings when ``did_not_complete`` is true.
    original_stdout_chars, original_stderr_chars : int
        The pre-truncation lengths, so a later reader can tell how much was
        cut. ``0`` when ``did_not_complete`` is true.
    truncated : bool
        Whether either stream was cut. ``False`` when ``did_not_complete`` is
        true — there was nothing to truncate.
    did_not_complete : bool
        True if ``environment.exec`` raised before producing a result.
    error : str | None
        The exception message when ``did_not_complete`` is true, else ``None``.
    """

    command: str
    exit_code: int | None
    stdout: str
    stderr: str
    original_stdout_chars: int
    original_stderr_chars: int
    truncated: bool
    did_not_complete: bool
    error: str | None


def parse_action(text: str) -> Action:
    """Extract a single action from the LLM's response text.

    Precedence: a code block wins over a ``TASK_COMPLETE`` mention, so the
    model can discuss finishing without accidentally terminating.

    Parameters
    ----------
    text : str
        The raw text content of the LLM's response.

    Returns
    -------
    Action
        The parsed action. ``kind`` is ``"shell"`` if a bash block was found,
        ``"done"`` if TASK_COMPLETE was found (and no code block), or
        ``"none"`` if neither was present.
    """
    match = CODE_BLOCK_RE.search(text)
    if match:
        command = match.group(1).strip()
        if command:
            return Action("shell", command)
    if DONE_MARKER in text:
        return Action("done")
    return Action("none")


def _truncate(text: str) -> tuple[str, bool]:
    """Truncate long text, keeping the first and last halves.

    Returns the (possibly truncated) text and whether truncation happened.
    The original length is cheap to get separately via ``len(text)`` before
    calling this, so it isn't returned here too.
    """
    if len(text) <= MAX_OBSERVATION_CHARS:
        return text, False
    half = MAX_OBSERVATION_CHARS // 2
    omitted = len(text) - MAX_OBSERVATION_CHARS
    return f"{text[:half]}\n... [{omitted} characters omitted] ...\n{text[-half:]}", True


async def run_shell(
    environment: BaseEnvironment, command: str, timeout_sec: int
) -> ShellResult:
    """Execute a bash command in the task's Docker container.

    Parameters
    ----------
    environment : BaseEnvironment
        Harbor's container interface. The key method is
        ``environment.exec(command=..., timeout_sec=...)``, which returns
        an ``ExecResult`` with ``.stdout``, ``.stderr``, and ``.return_code``.
    command : str
        The bash command string to run (can be multi-line).
    timeout_sec : int
        Maximum seconds to wait before killing the command.

    Returns
    -------
    ShellResult
        The structured result — ``exit_code`` is ``None`` and ``stdout``/
        ``stderr`` are empty when ``did_not_complete`` is true (the command
        never produced a result to read them from).
    """
    try:
        result = await environment.exec(command=command, timeout_sec=timeout_sec)
    except Exception as exc:
        return ShellResult(
            command=command,
            exit_code=None,
            stdout="",
            stderr="",
            original_stdout_chars=0,
            original_stderr_chars=0,
            truncated=False,
            did_not_complete=True,
            error=str(exc),
        )

    raw_stdout = result.stdout or ""
    raw_stderr = result.stderr or ""
    stdout, stdout_truncated = _truncate(raw_stdout)
    stderr, stderr_truncated = _truncate(raw_stderr)

    return ShellResult(
        command=command,
        exit_code=result.return_code,
        stdout=stdout,
        stderr=stderr,
        original_stdout_chars=len(raw_stdout),
        original_stderr_chars=len(raw_stderr),
        truncated=stdout_truncated or stderr_truncated,
        did_not_complete=False,
        error=None,
    )
