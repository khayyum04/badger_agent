# Phase 1: Separate raw history from active context; canonicalize actions

Spec: ready. Phase status lives only in [`../roadmap.md`](../roadmap.md).
Depends on: Phase 0
Design: [`../design.md`](../design.md) §5, §6, §7, §13, §23, §24 (partial), §29 (per-turn part); invariants 1, 2, 15
Roadmap: [`../roadmap.md`](../roadmap.md)
Issue: —
Decisions: DEC-003, DEC-005, DEC-011, DEC-012, DEC-013, DEC-014, DEC-015, DEC-016, DEC-017, DEC-018, DEC-019, DEC-020, DEC-021, DEC-022, DEC-023, DEC-024, DEC-025, DEC-026, DEC-027, DEC-028

## Goal

Introduce an append-only raw event history and build each model request from it through a context
manager, so the model no longer receives the whole transcript. Assistant turns enter active context
in canonical form only. The result — system prompt + original task + a bounded recent window of
canonical action–observation pairs — **is** design §30 variant B, the rolling-window baseline that
all later phases must beat. No task state yet.

## Scope

- **Module layout (DEC-011):** `starter/agent/events.py` — new module holding `Event`,
  `AssistantActionEvent`, `ObservationEvent` dataclasses (design §6, names as the code decides, not
  design's pseudocode literals — see canonical vocabulary below; **field sets are trimmed per
  DEC-022**, not copied verbatim from design §6). `starter/agent/context.py` — new module holding
  `canonicalize_action`, `select_recent_events`, `build_active_context`, the per-turn telemetry
  writer, context config/flags (**scope trimmed per DEC-023**), and a `record_observation(shell_result,
  turn)` helper (signature unchanged — `command` comes from `shell_result.command`, DEC-025) that
  builds an `ObservationEvent` from `tools.run_shell`'s result. Neither module is a
  stateful class; `context.py`'s functions take a plain `raw_events` list as a parameter and return
  new values — no hidden state.
- **`tools.run_shell`** changes to return a plain `ShellResult` dataclass instead of a formatted
  string: `command: str` (**DEC-025** — carried through unchanged from `run_shell`'s own `command`
  argument, so `record_observation` has a source for `ObservationEvent.command` without a third
  parameter), `exit_code`, `stdout`, `stderr` (**already truncated to `MAX_OBSERVATION_CHARS`, same as
  today — `tools._truncate` is unchanged this phase, per DEC-021**), `original_stdout_chars`,
  `original_stderr_chars` (pre-truncation lengths), `truncated: bool`, `did_not_complete: bool`,
  `error: str | None` (the exception message when `did_not_complete` is true, replacing today's
  `except Exception` → formatted-string path). String formatting for the model-facing observation
  message moves into `prompts.observation_message`, which becomes the single renderer of a
  `ShellResult`/`ObservationEvent` into text. `tools.py` does not import `events.py`.
- **`ObservationEvent` fields (DEC-022):** `command`, `exit_code`, `stdout`, `stderr`,
  `original_stdout_chars`, `original_stderr_chars`, `truncated`, `did_not_complete`, `error` — carried
  straight through from `ShellResult` by `record_observation`. Design §6's `started_at`,
  `duration_seconds`, and `full_output_path` are **not** included this phase (no timing capture; Phase
  3 owns `full_output_path`). `Event`'s base fields are `id`, `turn`, `event_type`, `timestamp` —
  design §6's `token_count` and `tags` are **not** included this phase (killed by DEC-015; introduced
  by Phase 2).
- **`agent.py`'s `run()` loop** owns a plain `raw_events: list` (parallel in spirit to today's
  `messages` list) and threads it into `context.py`'s functions each turn instead of appending
  directly to a growing `messages` list. It also owns `next_event_id` (**DEC-027**), a single `int`
  counter starting at 0, shared across both `AssistantActionEvent` and `ObservationEvent` and
  incremented by one after every event append — not derived from `len(raw_events)`, so ids stay
  stable identities if a future phase adds editing/deletion of raw events. The counter value is
  passed explicitly into the event constructor / `record_observation` at creation time.
- **Canonical vocabulary (DEC-017):** `AssistantActionEvent.action_kind` is `"shell"` / `"done"` /
  `"none"` — exactly `tools.Action.kind`'s values, not design.md's `"complete"`/`"invalid"`.
- **`canonicalize_action(action: Action) -> str`** (deterministic, no LLM): for `kind == "shell"`,
  returns ` ```bash\n{command}\n``` `; for `kind == "done"`, returns `"TASK_COMPLETE"`; for
  `kind == "none"`, returns `""` (**DEC-028**, matching design §7's own fallback) — this value is
  stored in `canonical_content` for shape-consistency but is never read for a `"none"` event (the
  nudge display always uses `raw_response`; see nudge handling below). The raw response is
  always kept in the event; canonicalization only ever operates on the already-parsed `Action`, so
  it cannot affect what actually ran (DEC-016).
- **Canonicalization flag (DEC-005, DEC-018):** `AGENT_CANONICALIZE`, defaulting to **on**. When
  off, active context uses raw responses instead of canonical form, isolating the canonicalization
  effect from the windowing effect for Gate G1.
- **Nudge / no-action turns (DEC-013, DEC-026):** when `Action.kind == "none"`, record
  `AssistantActionEvent(action_kind="none", raw_response=text)` in raw history. Do **not** create a
  paired `ObservationEvent` — there was no command and no environment interaction.
  `select_recent_events` has no awareness of `"none"` events at all (see Recent window below); they
  never appear in its output, paired or not. Instead, `build_active_context` always checks whether
  the *last* raw event is a `"none"`-kind action: if so, it unconditionally appends that event's
  `raw_response` followed by `prompts.NUDGE_MESSAGE` (unchanged this phase — Phase 2 supersedes it
  with targeted messages) to the active messages, after the recent window and outside the
  `recent_window_pairs` budget — the model's equivalent of today's "append `NUDGE_MESSAGE`, retry
  next turn." A `"none"` event that is not the most recent raw event is invisible to the model (it
  remains in raw history for audit only); if the model fails validation multiple turns in a row,
  only the latest attempt plus the nudge is shown.
- **Recent window (DEC-014):** fixed pair count, default **6**, configurable via
  `AGENT_RECENT_WINDOW_PAIRS`. Selection is `select_recent_events(events, max_pairs) ->
  list[Event]`, walking raw history backward and taking complete action–observation pairs only,
  until `max_pairs` is reached or history is exhausted. Never split an action from its observation.
  `"none"`-kind events are not pairs and are never selected by this function (DEC-026) — nudge
  handling is entirely `build_active_context`'s responsibility, not this function's. No mitigation
  for early-context loss and no telemetry counter for dropped events this phase — an accepted gap
  (see Notes).
- **Active context (`build_active_context`):** assembles, in order: system prompt → original task
  → recent window (canonical form if `AGENT_CANONICALIZE` is on, else raw response) → observation
  renderings → trailing nudge, if the last raw event is a `"none"`-kind action (DEC-026). No task
  state, no retrieval — those are later phases. The original task is never dropped, regardless of
  window size.
- **Token accounting (DEC-015):** no local tokenizer. Recent-window selection is by pair count, not
  token budget (token-bounded windows are deferred per design §13). Per-turn telemetry's input-token
  figure is the exact value already returned by the endpoint (`usage.prompt_tokens`, same source as
  `context.n_input_tokens`) — no per-component (system/task/window) breakdown this phase.
- **Per-turn telemetry storage (DEC-024):** written to a new `context.metadata["telemetry"]` list,
  one record per turn, appended every turn alongside the existing `turns`/`finished`/`messages`
  keys: `{"turn": int, "sent_input_tokens": int}`. Later phases add fields to each record rather than
  creating a second telemetry location.
- **Context config scope (DEC-023):** the config object in `context.py` holds exactly the two flags
  this phase defines — `canonicalize: bool` (`AGENT_CANONICALIZE`) and `recent_window_pairs: int`
  (`AGENT_RECENT_WINDOW_PAIRS`). Design §34's other example fields (token budgets, turn-warning
  threshold, output directory, etc.) are **not** pre-populated; each later phase adds its own field
  to this same object when it needs one.
- **`context.metadata["messages"]` (DEC-012):** becomes the serialized raw event history (every
  `AssistantActionEvent`/`ObservationEvent`, including nudge turns), not the OpenAI-style
  role/content list. Written every turn, same as today.
- **`scripts/build_dashboard.py` (DEC-019):** minimal patch to read the new
  `context.metadata["messages"]` shape and keep rendering a transcript. No new event-aware views
  (raw-vs-canonical diffing, per-kind rendering) this phase.
- **No test scaffolding this phase (DEC-020):** no pytest, no `starter/tests/`, no fakes. See Notes.

## Out of scope

- Output offloading (Phase 3), loop controls (Phase 2), any summarization or task state.
- Token-bounded window selection (deferred per design §13; this phase is pair-count only).
- Per-component token telemetry (DEC-015).
- Test scaffolding of any kind (DEC-020).
- Mitigating early-context loss, or telemetry for it (DEC-014).
- Reasoning-model fallback visibility, tightening `CODE_BLOCK_RE`, or flagging discarded
  multi-block responses (all confirmed no-ops per DEC-016).
- Rewriting `build_dashboard.py`'s rendering beyond reading the new metadata shape (DEC-019).
- Full untruncated output in raw history; event timing fields (`started_at`/`duration_seconds`);
  offload metadata (`full_output_path`); per-event token counts or tags; and any design-§34 config
  field beyond the two this phase defines — all deferred to the phase that populates them
  (DEC-021, DEC-022, DEC-023).

## Interfaces and handoff

- **Provides** (ledger rows owned by Phase 1, superseding the `planned` rows in `handoff.md` once
  implemented): `Event`, `AssistantActionEvent`, `ObservationEvent` (`events.py`); raw event history
  (plain list, owned by `agent.py`); `ShellResult` (`tools.py`, replaces the formatted-string return
  of `run_shell`); `canonicalize_action`, `select_recent_events`, `build_active_context`,
  `record_observation`, per-turn telemetry writer, context config/flags (all `context.py`).
- **Reuses:** `tools.Action` and `tools.parse_action` (extended, not duplicated — `action_kind`
  mirrors `Action.kind` exactly per DEC-017), `prompts.observation_message` as the single
  observation renderer (now takes a `ShellResult`/`ObservationEvent` instead of a preformatted
  string), `LLMClient.chat` and its `usage` unchanged.
- **Changes existing code:** `tools.run_shell` returns `ShellResult` instead of a formatted string;
  `agent.run` builds messages through `context.py`'s functions instead of appending to one list;
  `scripts/build_dashboard.py` reads the new `context.metadata["messages"]` shape.
- **Handoff:** fill the *Code map*, flip the relevant ledger rows to `implemented` with locations,
  and write *Notes for the next phase* (2, 3, 4) per `CLAUDE.md` › Finishing a session. No test
  scaffolding row to fill in (DEC-020) — note its absence explicitly so Phase 2 doesn't assume it
  exists.

## Exit criteria

- Raw history remains complete (given today's truncation limit — see DEC-021) and is what gets
  written to run metadata (`context.metadata["messages"]`, DEC-012).
- The model no longer receives the entire raw transcript; active context contains canonical actions
  only when `AGENT_CANONICALIZE` is on, bounded to the recent window either way.
- Per-turn telemetry records the exact endpoint input-token total (no per-component split this
  phase, per DEC-015).
- **Gate G1:** variant B compared with Phase 0 on the agreed protocol (`handoff.md`'s Measurement
  protocol), with `AGENT_CANONICALIZE` on and off. No unexplained completion-rate regression (per
  the noise rule in `handoff.md` §5).
- `scripts/build_dashboard.py` renders transcripts from the new metadata shape without erroring.
- `handoff.md` updated per `CLAUDE.md` › Finishing a session.

## Tests

None this phase (DEC-020). Verification is Gate G1's harbor-run measurement protocol only —
completion rate and token totals from `jobs/`, per `handoff.md`. There is no automated coverage of
`canonicalize_action`'s edge cases (narrated / bare / untagged / multi-block / invalid /
`TASK_COMPLETE` responses), `select_recent_events`'s pairing invariant, or token accounting; a
subtle bug in any of these may not surface as a distinguishable Gate G1 result.

## Notes

Absorbs the former standalone canonicalization phase, which was too small to justify its own
contract (DEC-005). If canonicalization measures as harmful, the flag ships off and the rest
stands.

Early-context loss (the recent window dropping turns that may matter later, e.g. an early file-path
discovery) is a known, accepted gap of design §30 variant B, with no mitigation or telemetry in this
phase (DEC-014). If Gate G1 shows an unexplained completion-rate regression, this is a plausible but
unconfirmed cause — diagnosing it means reading the raw event history by hand, since there's no
counter pointing at it.

Test scaffolding (pytest, fakes) was scoped out of this phase (DEC-020), reversing the original
draft's plan to add it here. The interface ledger's "Test scaffolding" row has no Phase 1
implementation; if a later phase wants unit tests, it starts from scratch.

## Resolved open questions (goldfish test, 2026-09-22)

A zero-context read of this spec surfaced four gaps an implementer could not have resolved from the
text as written: `ObservationEvent.command`'s source (DEC-025), the nudge-turn injection mechanism
(DEC-026), `Event.id` allocation (DEC-027), and `canonical_content` for `"none"`-kind events
(DEC-028). All four are now resolved and folded into the Scope section above; see those decisions
for the reasoning and rejected alternatives. This section is kept as a record that the goldfish test
found real gaps, not to re-litigate them.
