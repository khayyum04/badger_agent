# Phase 1: Separate raw history from active context; canonicalize actions

Spec: draft, incomplete. Phase status lives only in [`../roadmap.md`](../roadmap.md).
Depends on: Phase 0
Design: [`../design.md`](../design.md) §5, §6, §7, §13, §23, §24 (partial), §29 (per-turn part); invariants 1, 2, 15
Roadmap: [`../roadmap.md`](../roadmap.md)
Issue: —
Decisions: DEC-003, DEC-005

## Goal

Introduce an append-only raw event history and build each model request from it through a context
manager, so the model no longer receives the whole transcript. Assistant turns enter active context
in canonical form only. The result — system prompt + original task + a bounded recent window of
canonical action–observation pairs — **is** design §30 variant B, the rolling-window baseline that
all later phases must beat. No task state yet.

## Scope (draft)

- Event records for actions and observations (raw response, command, exit code, output, char counts, turn, timestamp).
- A context manager that builds `active_messages` from raw events + budgets.
- Deterministic `canonicalize_action` (no LLM); raw response kept in the event; parse failures recorded as explicit events (§7).
- Canonicalization behind its own config flag so it can be measured on/off independently of the window (DEC-005).
- Token counting before each request; per-turn telemetry by component.
- A structured shell result: `tools.run_shell` returns exit code, stdout, stderr, sizes, and a did-not-complete flag; string formatting moves into one renderer. (Today it returns a formatted string, which events cannot be built from.)
- Test scaffolding: the repo has no tests. Add pytest as a dev dependency, a `starter/tests/` directory, and reusable fakes (environment, LLM client, event builders).
- Recent window: fixed pair count first, token-bounded later (§13). Never split an action from its observation.
- The original task is never dropped.

## Out of scope

- Output offloading (Phase 3), loop controls (Phase 2), any summarization or task state.

## Open questions

- Event representation: dataclasses per design §6, or plain dicts? Where does the code live (new module in `starter/agent/` vs. inside `agent.py`)?
- `context.metadata["messages"]` is read by `build_dashboard.py`. Does it become the raw transcript, the events, or both? (Must stay updated every turn.)
- What happens to `NUDGE_MESSAGE` turns (no valid action) — are they events, and are they in the recent window?
- Window size default, and is it in turns or tokens for this phase?
- Does dropping old turns hurt tasks that need early context (e.g. an early discovery)? What is the cheap mitigation before Phase 4 exists?
- How is token count obtained (see Phase 0)?
- `CODE_BLOCK_RE` accepts untagged fences; the canonical form is always ` ```bash `. Confirm this cannot change what executes.
- Reasoning-model fallback: `reasoning_content` is parsed as an action today. Does canonicalization make that visible or hide it?
- Multiple code blocks in one response: does the canonical form record only the executed one?
- `build_dashboard.py` mirrors the regex and nudge text; what must change there?
- The endpoint's `usage` gives total prompt tokens only *after* a call; per-component and pre-request counts need local counting. Which tokenizer for an approved open-weight model?

## Interfaces and handoff

- **Provides** (ledger rows owned by Phase 1): events, raw history, structured shell result, `canonicalize_action`, `count_tokens`, `select_recent_events`, `build_active_context`, per-turn telemetry writer, context config and flags, test scaffolding.
- **Reuses:** `tools.Action` and `tools.parse_action` (extend `Action`; no second action type), `prompts.observation_message` as the single observation renderer, `LLMClient.chat` and its `usage`.
- **Changes existing code:** `tools.run_shell` returns a structured result instead of a formatted string; `agent.run` builds messages through the context manager instead of appending to one list.
- **Handoff:** decide and record the module layout (by responsibility, not by phase); fill the *Code map*, the ledger rows, and *Notes for the next phase* (2, 3, 4).

## Exit criteria (draft)

- Raw history remains complete and is what gets written to run metadata.
- The model no longer receives the entire raw transcript; active context contains canonical actions only.
- Token usage can be measured by context component.
- Tests run with one documented command, and the fakes are reusable by later phases.
- **Gate G1:** variant B compared with Phase 0 on the agreed protocol, with canonicalization on and off. No unexplained completion-rate regression.
- `handoff.md` updated per `CLAUDE.md` › Finishing a session.

## Tests (draft)

Canonicalization of narrated / bare / untagged / multi-block / invalid / `TASK_COMPLETE` responses; recent-window selection; action–observation pairing; original task always present; raw history not mutated by context building; token accounting.

## Notes

Absorbs the former standalone canonicalization phase, which was too small to justify its own
contract (DEC-005). If canonicalization measures as harmful, the flag ships off and the rest stands.
