"""Self-compaction: the agent replaces its older history with a summary it writes itself.

mini-swe-agent re-sends the whole history on every model call, so input tokens dominate the cost.
With compaction on, the model gets a second tool, ``self_compact(summary, note_to_self)``. As the
history grows the harness asks for it in three stages: a notice, a warning, and a hard stage where,
after one last command, ``bash`` is withheld until the model compacts (or has failed to twice). The history then becomes: system prompt, task, the
summary and note, and the most recent turns. The replaced history is saved next to the trajectory.

This is the experiment version; see docs/plans/self-compaction-mvp.md for what it leaves out.

Settings (env vars):
  AGENT_COMPACTION                       on/off (default: off)
  LLM_CONTEXT_WINDOW                     the model's context window in tokens (default: 250000)
  COMPACT_NOTICE_AT, COMPACT_WARNING_AT,
  COMPACT_HARD_AT                        stage thresholds in tokens (default: 10% / 20% / 30% of the window)
  COMPACT_FORCED_THINKING                on/off: let the model think on turns where only self_compact is
                                         offered (default: off; its thinking there caused failed attempts)
"""

import json
import os
from pathlib import Path

from minisweagent.exceptions import FormatError
from minisweagent.models.utils.actions_toolcall import BASH_TOOL

STAGES = ("notice", "warning", "hard")
DEFAULT_THRESHOLDS = (0.10, 0.20, 0.30)  # fractions of the context window, one per stage

SELF_COMPACT_TOOL = {
    "type": "function",
    "function": {
        "name": "self_compact",
        "description": (
            "Replace your older history with a summary to keep your context small. Call this alone, not "
            "together with bash. The original task stays visible word for word, so don't restate it. "
            "Be specific and brief."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": (
                        "Replaces everything before your most recent turns, including any earlier summary, so "
                        "carry forward what still matters from it. In this order: (1) done: files you created "
                        "or changed, with exact paths, and commands that worked; (2) verified: what you tested "
                        "and the result; (3) decisions made and why; (4) in progress: the current error or "
                        "blocker with its exact message."
                    ),
                },
                "note_to_self": {
                    "type": "string",
                    "description": "What you were doing, ending with your next concrete action.",
                },
            },
            "required": ["summary", "note_to_self"],
        },
    },
}

STAGE_MESSAGES = {
    "notice": (
        "[Context note: your history is about {size}K tokens. At a natural stopping point, e.g. right after "
        "a step succeeds, call the self_compact tool instead of bash. You can keep working until then.]"
    ),
    "warning": (
        "[Context warning: your history is about {size}K tokens. Call the self_compact tool instead of bash "
        "within your next one or two turns. At {hard}K tokens bash becomes unavailable until you do.]"
    ),
    "hard": (
        "[Context limit reached: your history is about {size}K tokens. You may run one more bash command to "
        "finish your current step. After that, bash is unavailable until you call the self_compact tool with "
        "a summary of your work and a note to yourself.]"
    ),
    "locked": (
        "[bash is now unavailable. Call the self_compact tool now with a summary of your work and a note to "
        "yourself.]"
    ),
    "released": (
        "[Compaction failed {failures} times, so bash is available again. Continue the task, and call the "
        "self_compact tool when you reach a stopping point.]"
    ),
}

MAX_FORCED_FAILURES = 2
"""Failed self_compact attempts while bash is withheld before it is given back for the rest of the cycle."""

COMPACTED_MESSAGE = """\
[Context compacted. Your earlier turns were replaced by your own summary below. The task above is \
unchanged. Your most recent turns follow this message.]

Summary of earlier work:
{summary}

Note to self:
{note_to_self}"""

CALL_ERROR = (
    "Tool call error: call self_compact once, on its own (not together with bash), with a non-empty "
    "summary and note_to_self."
)
FORCED_ERROR = (
    "Your context limit was reached, so bash is unavailable. Reply with exactly one self_compact tool "
    "call: a short summary of your work so far and a note to yourself."
)


def estimate_tokens(message: dict, reasoning_sent: bool = False) -> int:
    """Rough size of a message as sent: about 3 characters per token on this model."""
    chars = len(str(message.get("content") or "")) + len(json.dumps(message.get("tool_calls") or []))
    if reasoning_sent:
        chars += len(str(message.get("reasoning_content") or ""))
    return chars // 3


def recent_turns(messages: list[dict], budget: int, reasoning_sent: bool = False) -> list[dict]:
    """The newest whole turns that fit in `budget` tokens; always at least one.

    A turn is an assistant message plus its tool results, so a call is never separated from its
    result. User messages (stage messages, format-error notes, an earlier summary) are dropped:
    they describe a situation the compaction ends.
    """
    turns: list[list[dict]] = []
    for message in messages:
        if message["role"] == "assistant":
            turns.append([message])
        elif message["role"] == "tool" and turns:
            turns[-1].append(message)
    kept: list[dict] = []
    used = 0
    for turn in reversed(turns):
        size = sum(estimate_tokens(m, reasoning_sent) for m in turn)
        if kept and used + size > budget:
            break
        kept = turn + kept
        used += size
    return kept


class Compactor:
    """Stage tracking and history rebuilding for one task; shared by the agent and the model."""

    def __init__(
        self,
        thresholds: tuple[int, int, int],
        archive_dir: Path,
        reasoning_sent: bool = False,
        forced_thinking: bool = False,
    ):
        self.thresholds = thresholds
        # A third of the notice threshold leaves room to work before the next notice (8K by default).
        self.recent_budget = thresholds[0] // 3
        # Without AGENT_STRIP_REASONING the kept turns are re-sent with their thinking, so it counts toward the budget.
        self.reasoning_sent = reasoning_sent
        self.forced_thinking = forced_thinking
        self.archive_dir = archive_dir
        self.stage = 0  # stages announced since the last compaction: 0 = none, 3 = hard
        # The hard stage, in order: one last bash command, then bash withheld, then given back if the model can't compact.
        self.last_command = False
        self.forced_failures = 0
        self.released = False
        self.fresh_from = 0  # history index; responses before it were to requests from before the last compaction
        self.log: list[dict] = []  # one record per compaction, mirrored into Harbor's metadata

    @classmethod
    def from_env(cls, archive_dir: Path, reasoning_sent: bool = False) -> "Compactor | None":
        if os.environ.get("AGENT_COMPACTION", "off").lower() != "on":
            return None
        window = int(os.environ.get("LLM_CONTEXT_WINDOW") or 250_000)
        thresholds = tuple(
            int(os.environ.get(f"COMPACT_{stage.upper()}_AT") or window * fraction)
            for stage, fraction in zip(STAGES, DEFAULT_THRESHOLDS)
        )
        forced_thinking = os.environ.get("COMPACT_FORCED_THINKING", "off").lower() == "on"
        return cls(thresholds, archive_dir, reasoning_sent, forced_thinking)

    @property
    def forced(self) -> bool:
        """Past the hard stage and its last command: only self_compact is available until the model compacts."""
        return self.stage == len(STAGES) and not self.last_command and not self.released

    def tools(self) -> list[dict]:
        # self_compact is offered from the first turn: the tool list is at the start of the prompt,
        # so adding it later would invalidate the gateway's prefix cache.
        return [SELF_COMPACT_TOOL] if self.forced else [BASH_TOOL, SELF_COMPACT_TOOL]

    def request_kwargs(self) -> dict:
        """Extra request parameters. On forced turns thinking is off: writing the summary is the reasoning step,
        and long thinking there made the model run out of budget or drift back to the task."""
        if self.forced and not self.forced_thinking:
            return {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}
        return {}

    def size(self, messages: list[dict]) -> int:
        """History size in tokens: the gateway's prompt count for the latest request since the last compaction."""
        for message in reversed(messages[self.fresh_from :]):
            response = (message.get("extra") or {}).get("response")
            usage = (response.get("usage") if isinstance(response, dict) else None) or {}
            if usage.get("prompt_tokens"):
                return usage["prompt_tokens"]
        return 0

    def stage_message(self, messages: list[dict]) -> dict | None:
        """The message for a newly reached stage, if any. Each stage is announced once per cycle."""
        size = self.size(messages)
        reached = sum(size >= threshold for threshold in self.thresholds)
        if reached > self.stage:
            self.stage = reached
            name = STAGES[reached - 1]
            self.last_command = name == "hard"
        elif self.last_command:  # the model call after the hard message has been made
            self.last_command = False
            name = "locked"
        elif self.forced and self.forced_failures >= MAX_FORCED_FAILURES:
            # Forcing must never end a task that would otherwise keep working; the cost is a history that keeps growing.
            self.released = True
            name = "released"
        else:
            return None
        content = STAGE_MESSAGES[name].format(
            size=round(size / 1000), hard=round(self.thresholds[-1] / 1000), failures=self.forced_failures
        )
        return {"role": "user", "content": content, "extra": {"compaction_stage": name}}

    def parse(self, tool_calls: list) -> list[dict] | None:
        """The action for a self_compact call. None if the reply has nothing to do with compaction."""
        names = [call.function.name for call in tool_calls]
        if not self.forced and "self_compact" not in names:
            return None
        if names == ["self_compact"]:
            try:
                args = json.loads(tool_calls[0].function.arguments)
                summary, note = args["summary"].strip(), args["note_to_self"].strip()
            except (ValueError, KeyError, TypeError, AttributeError):  # cut-off JSON, missing or non-string fields
                summary = note = ""
            if summary and note:
                return [
                    {
                        "tool": "self_compact",
                        "summary": summary,
                        "note_to_self": note,
                        "tool_call_id": tool_calls[0].id,
                    }
                ]
        self.forced_failures += self.forced
        error = FORCED_ERROR if self.forced else CALL_ERROR
        raise FormatError({"role": "user", "content": error, "extra": {"interrupt_type": "FormatError"}})

    def apply(self, messages: list[dict], action: dict) -> list[dict]:
        """Carry out a self_compact call (the last message). Returns the history to continue with."""
        size = self.size(messages)
        if size < self.thresholds[0]:
            reply = f"Not compacted: your history is only about {round(size / 1000)}K tokens. Continue working."
            return [*messages, {"role": "tool", "tool_call_id": action["tool_call_id"], "content": reply}]

        n = len(self.log) + 1
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        (self.archive_dir / f"compaction-{n}.json").write_text(json.dumps(messages, indent=2))

        system, task = messages[:2]
        kept = recent_turns(messages[2:-1], self.recent_budget, self.reasoning_sent)
        summary = {
            "role": "user",
            "content": COMPACTED_MESSAGE.format(summary=action["summary"], note_to_self=action["note_to_self"]),
            "extra": {"compaction": n},
        }
        history = [system, task, summary, *kept]
        self.log.append(
            {
                "stage": STAGES[self.stage - 1] if self.stage else "none",
                "size_before": size,
                "forced_failures": self.forced_failures,
                "messages_before": len(messages),
                "messages_after": len(history),
            }
        )
        self.stage = 0
        self.last_command, self.forced_failures, self.released = False, 0, False
        self.fresh_from = len(history)
        return history
