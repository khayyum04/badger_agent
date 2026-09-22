"""Build the model's active context from the raw event history.

Phase 1 (context management) separates two things that used to be one growing
``messages`` list: an append-only raw event history (owned by ``agent.py``,
made of ``events.py`` dataclasses) and the bounded active context sent to the
model each turn, built fresh from it here. Nothing in this module is a
stateful class — every function takes a plain ``raw_events`` list (or a
single event/result) and returns a new value.

Functions
=========
- ``canonicalize_action`` — deterministic, minimal text form of one action.
- ``select_recent_events`` — the last N complete action–observation pairs.
- ``build_active_context`` — assembles one turn's model-facing message list.
- ``record_observation`` — turns a ``tools.ShellResult`` into an
  ``events.ObservationEvent``.
- ``record_turn_telemetry`` — one turn's telemetry record.
- ``load_context_config`` — reads this phase's two ``AGENT_*`` flags.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from agent.events import AssistantActionEvent, Event, ObservationEvent, now_iso
from agent.prompts import NUDGE_MESSAGE, observation_message
from agent.tools import Action, ShellResult

_FALSY_ENV_VALUES = {"0", "false", "no", "off"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in _FALSY_ENV_VALUES


@dataclass
class ContextConfig:
    """The two context-shaping flags Phase 1 defines (DEC-023).

    Later phases add their own field here rather than creating a second
    config object.
    """

    canonicalize: bool
    recent_window_pairs: int


def load_context_config() -> ContextConfig:
    """Read ``AGENT_CANONICALIZE`` and ``AGENT_RECENT_WINDOW_PAIRS`` from the environment."""
    return ContextConfig(
        canonicalize=_env_bool("AGENT_CANONICALIZE", default=True),
        recent_window_pairs=int(os.environ.get("AGENT_RECENT_WINDOW_PAIRS", "6")),
    )


def canonicalize_action(action: Action) -> str:
    """The standard, minimal text form of one already-parsed action.

    Operates only on the parsed ``Action`` — it cannot affect what actually
    ran (DEC-016). Matches design.md §7's own fallback: ``""`` for a
    ``"none"``-kind action (DEC-028).
    """
    if action.kind == "shell":
        return f"```bash\n{action.command}\n```"
    if action.kind == "done":
        return "TASK_COMPLETE"
    return ""


def record_observation(shell_result: ShellResult, turn: int, event_id: int) -> ObservationEvent:
    """Build an ``ObservationEvent`` from a shell command's structured result.

    Positional arguments, in order: ``shell_result``, then ``turn`` (which turn
    this happened on), then ``event_id`` (this event's id in ``agent.py``'s
    ``next_event_id`` sequence, DEC-027). ``turn`` and ``event_id`` are both
    plain ``int``s, so swapping them at a call site fails silently rather than
    raising a type error — DEC-030.
    """
    return ObservationEvent(
        id=event_id,
        turn=turn,
        timestamp=now_iso(),
        command=shell_result.command,
        exit_code=shell_result.exit_code,
        stdout=shell_result.stdout,
        stderr=shell_result.stderr,
        original_stdout_chars=shell_result.original_stdout_chars,
        original_stderr_chars=shell_result.original_stderr_chars,
        truncated=shell_result.truncated,
        did_not_complete=shell_result.did_not_complete,
        error=shell_result.error,
    )


def record_turn_telemetry(turn: int, sent_input_tokens: int) -> dict:
    """Build one turn's record for ``context.metadata["telemetry"]`` (DEC-024)."""
    return {"turn": turn, "sent_input_tokens": sent_input_tokens}


def select_recent_events(events: list[Event], max_pairs: int) -> list[Event]:
    """The last ``max_pairs`` complete action–observation pairs, oldest first.

    Walks raw history backward. A pair is a ``"shell"``-kind
    ``AssistantActionEvent`` immediately followed by its ``ObservationEvent``
    (always adjacent, since ``agent.py`` appends the observation right after
    its action). Anything else — a ``"none"``-kind action (no paired
    observation, DEC-013) or the final ``"done"`` action — is skipped and
    never appears in the result, paired or not (DEC-026). Never splits an
    action from its observation.
    """
    pairs: list[list[Event]] = []
    i = len(events) - 1
    while i >= 0 and len(pairs) < max_pairs:
        event = events[i]
        if isinstance(event, ObservationEvent) and i > 0:
            prev = events[i - 1]
            if isinstance(prev, AssistantActionEvent) and prev.action_kind == "shell":
                pairs.append([prev, event])
                i -= 2
                continue
        i -= 1
    pairs.reverse()
    return [event for pair in pairs for event in pair]


def build_active_context(
    system_prompt: str,
    instruction: str,
    raw_events: list[Event],
    config: ContextConfig,
) -> list[dict]:
    """Assemble one turn's model-facing message list from the raw history.

    Order: system prompt → original task → recent window (canonical form if
    ``config.canonicalize``, else raw response) → observation renderings →
    trailing nudge, if the last raw event is a ``"none"``-kind action
    (DEC-026). No task state, no retrieval — later phases. The original task
    is never dropped, regardless of window size.
    """
    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": instruction},
    ]

    for event in select_recent_events(raw_events, config.recent_window_pairs):
        if isinstance(event, AssistantActionEvent):
            content = event.canonical_content if config.canonicalize else event.raw_response
            messages.append({"role": "assistant", "content": content})
        elif isinstance(event, ObservationEvent):
            messages.append({"role": "user", "content": observation_message(event)})

    if raw_events:
        last = raw_events[-1]
        if isinstance(last, AssistantActionEvent) and last.action_kind == "none":
            messages.append({"role": "assistant", "content": last.raw_response})
            messages.append({"role": "user", "content": NUDGE_MESSAGE})

    return messages
