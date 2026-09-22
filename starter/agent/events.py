"""Structured event model for the agent's raw history.

Phase 1 (context management) introduces an append-only raw event history that sits
underneath the bounded, deliberately-built active context the model actually sees
(see ``context.py``). This module holds the event dataclasses that history is made
of; ``agent.py`` owns the ``raw_events`` list itself, and ``context.py`` is what
reads and assembles from it.

Two event kinds this phase:

- ``AssistantActionEvent`` — one per model turn. Keeps both the raw response and
  its canonical form (see ``context.canonicalize_action``); ``action_kind`` mirrors
  ``tools.Action.kind`` exactly (``"shell"`` / ``"done"`` / ``"none"``).
- ``ObservationEvent`` — one per executed shell command. Built from
  ``tools.ShellResult`` by ``context.record_observation``. A ``"none"``-kind
  action has no paired observation (there was no command to run).

Field sets are trimmed to only what this phase populates (no ``token_count``,
``tags``, timing, or offload fields yet) — see ``decisions.md`` DEC-022.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


def now_iso() -> str:
    """Current UTC time as an ISO-8601 string, used to stamp new events."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(kw_only=True)
class Event:
    """Base fields shared by every event kind."""

    id: int
    turn: int
    event_type: str
    timestamp: str


@dataclass(kw_only=True)
class AssistantActionEvent(Event):
    """One model turn: what it said, and the single action parsed from it.

    ``command`` is the shell command for ``action_kind == "shell"`` and ``None``
    otherwise. ``canonical_content`` is ``context.canonicalize_action``'s output
    for this action, stored for shape-consistency even for ``"none"`` events,
    where it is always ``""`` and never read (DEC-028).
    """

    event_type: str = "assistant_action"
    raw_response: str
    action_kind: str
    command: str | None
    canonical_content: str


@dataclass(kw_only=True)
class ObservationEvent(Event):
    """The result of executing one shell command, mirroring ``tools.ShellResult``.

    ``exit_code`` is ``None`` and ``stdout``/``stderr`` are empty when
    ``did_not_complete`` is true — the command never produced a result to read
    them from (DEC-029).
    """

    event_type: str = "observation"
    command: str
    exit_code: int | None
    stdout: str
    stderr: str
    original_stdout_chars: int
    original_stderr_chars: int
    truncated: bool
    did_not_complete: bool
    error: str | None
