"""Submit review (AGENT_SUBMIT_REVIEW): a fresh-context reviewer before the first submit.

The agent verifies against its own reading of the task, so misreadings survive its checks. At the first
submit, a reviewer that has seen only the task text inspects the container with a few read-only commands
and lists the explicit requirements that aren't met. Its verdict replaces the agent's submit output; the
agent's next submit goes through. Same model and endpoint as the agent. docs/plans/review-and-time-limit.md
"""

import json
import time
from collections.abc import Callable
from typing import Any

import litellm
from minisweagent.models.utils.actions_toolcall import BASH_TOOL

REVIEW_MAX_COMMANDS = 6
REVIEW_COMMAND_TIMEOUT = 60
REVIEW_MAX_TOKENS = 8192
REVIEW_OUTPUT_CHARS = 4000
# Wall-clock budget: once it's used, the next call must give the verdict, with a short reply budget.
# Keeps the worst case near REVIEW_TIME_BUDGET_SEC + one short call instead of ~7 full-length calls.
REVIEW_TIME_BUDGET_SEC = 180
REVIEW_VERDICT_MAX_TOKENS = 2048

REVIEW_SYSTEM = """You review someone else's finished work on a task inside a Linux container. You did not do
the work and you have no notes from whoever did. Judge only by the task text and what you can see now.

Use the bash tool to inspect the result: list the directories and files the task names, read outputs, run
the deliverable on a small input if that's quick. Do NOT modify, create or delete anything. You may run at
most {max_commands} commands, one per reply.

Then reply WITHOUT a tool call, in this format:
UNMET:
- <each explicit requirement of the task that the current state does not meet, with the evidence>
or, if you found none:
ALL MET
Only list requirements the task text actually states (paths, names, formats, signatures, limits, things that
must stay unchanged, files that must or must not be present). No style advice, no guesses about hidden tests."""

REVIEW_TASK = "<task>\n{task}\n</task>\n\nInspect the current state and give your verdict."
REVIEW_STOP = "Stop inspecting. Give your verdict now, without a tool call."

REVIEW_RESULT = """Not submitted yet: an independent reviewer (fresh context, read only the task) checked the
current state. This happens only once.

<review>
{verdict}
</review>

Fix every unmet requirement it found that you agree is real; ignore any that are wrong, and say why. Then
submit again with: echo COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT"""


def _usage(response) -> tuple[int, int]:
    usage = getattr(response, "usage", None)
    return (getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0)


def run_review(
    *,
    task: str,
    model_name: str,
    model_kwargs: dict[str, Any],
    run_command: Callable[[str, int], dict],
    add_usage: Callable[[int, int], None],
    should_stop: Callable[[], bool] = lambda: False,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Runs the reviewer. Returns {"message": text for the agent, "verdict", "n_commands", "seconds"}.

    Never raises: any error yields a short note, so the agent's submit flow keeps working.
    """
    start = clock()
    messages: list[dict] = [
        {"role": "system", "content": REVIEW_SYSTEM.format(max_commands=REVIEW_MAX_COMMANDS)},
        {"role": "user", "content": REVIEW_TASK.format(task=task)},
    ]
    kwargs = {**model_kwargs, "max_tokens": min(REVIEW_MAX_TOKENS, model_kwargs.get("max_tokens") or REVIEW_MAX_TOKENS)}
    n_commands = 0
    verdict = ""
    try:
        for _ in range(REVIEW_MAX_COMMANDS + 2):
            if should_stop():
                break
            out_of_time = clock() - start >= REVIEW_TIME_BUDGET_SEC
            final = n_commands >= REVIEW_MAX_COMMANDS or out_of_time
            if final:
                messages.append({"role": "user", "content": REVIEW_STOP})
            call_kwargs = {**kwargs, "max_tokens": min(kwargs["max_tokens"], REVIEW_VERDICT_MAX_TOKENS)} if final else kwargs
            response = litellm.completion(
                model=model_name,
                messages=messages,
                **({} if final else {"tools": [BASH_TOOL]}),
                **call_kwargs,
            )
            add_usage(*_usage(response))
            message = response.choices[0].message
            tool_calls = (message.tool_calls or []) if not final else []
            if not tool_calls:
                verdict = (message.content or "").strip()
                if verdict or final:
                    break
                messages.append({"role": "user", "content": REVIEW_STOP})  # thinking only, no answer
                n_commands = REVIEW_MAX_COMMANDS
                continue
            call = tool_calls[0]
            messages.append({"role": "assistant", "content": message.content or "", "tool_calls": [call.model_dump()]})
            try:
                command = json.loads(call.function.arguments).get("command", "")
            except Exception:
                command = ""
            remaining = REVIEW_TIME_BUDGET_SEC - (clock() - start)
            timeout = int(max(10, min(REVIEW_COMMAND_TIMEOUT, remaining)))
            result = run_command(command, timeout) if command else {"output": "no command", "returncode": -1}
            n_commands += 1
            output = (result.get("output") or "")[-REVIEW_OUTPUT_CHARS:]
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": f"returncode={result.get('returncode')}\n{output}"}
            )
    except Exception as e:  # endpoint error, bad reply: don't break the agent's submit
        verdict = verdict or f"(review failed: {type(e).__name__}: {str(e)[:200]})"
    verdict = verdict or "(no verdict)"
    return {
        "message": REVIEW_RESULT.format(verdict=verdict),
        "verdict": verdict,
        "n_commands": n_commands,
        "seconds": int(clock() - start),
    }
