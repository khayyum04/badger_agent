# Handoff ledger — Context Management

Every phase runs in a fresh session, so this file is how one phase tells the next what exists and
what to reuse. It is imported into every session. **The source code is the ground truth**; this
file is the map plus the intent. If they disagree, fix one of them in the same change.

## Rules for editing

- The session that **finishes** a phase updates this file before closing. Verify every symbol with `grep` first; never write it from memory.
- Update rows, don't delete them. A removed symbol is marked `removed` with the reason.
- This is a map, not a narrative: signature, location, one-line purpose. Rationale belongs in `decisions.md`, scope in the phase spec.
- Names in `planned` rows are draft names taken from `design.md` pseudocode. The implementing phase may rename, but must update the row so later phases don't guess.
- Module layout is by **responsibility, never by phase** (no `phase3_utils.py`). Phase 1 decides the layout and records it under *Code map*.

## Existing symbols to extend, not duplicate (baseline, before Phase 1)

| Symbol (in `starter/agent/`) | Touched by | Instruction |
|---|---|---|
| `tools.Action` — `kind` is `"shell"`, `"done"` or `"none"`; `command` | 1, 2, 4 | Extend it. Do not add a second action type. `design.md` §6's `complete` / `invalid` mean `done` / `none`. |
| `tools.parse_action(text) -> Action` | 1 | Reuse as-is. Canonicalization builds on its result. |
| `tools.run_shell(environment, command, timeout_sec) -> str` | 1, 3 | Returns a **formatted string** today, which events cannot be built from. Phase 1 changes it to return a structured result and moves string formatting into one renderer. Phase 3 then extends **this function**. Do not add `run_shell_with_output_capture` beside it. |
| `tools._truncate`, `MAX_OBSERVATION_CHARS` (per-stream, 6000) | 3 | Phase 3 replaces this with preview/offload logic. Don't keep both paths. |
| `prompts.observation_message(observation: str)` | 1 | The single point that renders an observation for the model. Keep it single. |
| `prompts.NUDGE_MESSAGE` (generic) | 2 | Phase 2's targeted messages supersede the generic one. Mirrored in `scripts/build_dashboard.py`; change together. |
| `agent.BaselineAgent.run` loop, `messages` list | 1 | Replaced by the context manager. `context.metadata` keys `turns`, `finished`, `messages` are read by `scripts/build_dashboard.py`. |
| `llm.LLMClient.chat(messages) -> (text, usage)` | 1, 5 | `usage` gives total prompt/completion tokens only *after* a call. Phase 5's compaction call reuses this client; no second client. |

## Interface ledger (planned → implemented)

`Status`: `planned` → `implemented` (fill `Location`) → `removed`. "Reused by" lists phases that must
call it instead of writing their own.

| Symbol (draft name) | Owner | Reused by | Status | Location | Purpose |
|---|---|---|---|---|---|
| Measurement command + baseline numbers | 0 | every phase | planned | — | The protocol each phase re-runs; where baseline results live (see *Measurement protocol*). |
| `Event`, `AssistantActionEvent`, `ObservationEvent` (§6) | 1 | 2, 3, 4, 5 | planned | — | Structured raw events; built on `Action` and the structured shell result. |
| Append-only raw history (design: `raw_events`) | 1 | 2, 3, 4, 5 | planned | — | The audit record; also what is written to `context.metadata`. |
| Structured shell result (return type of `tools.run_shell`) | 1 | 3, 4 | planned | — | exit code, stdout, stderr, sizes, did-not-complete flag. Replaces the formatted string. |
| `canonicalize_action(action) -> str` (§7) | 1 | 5 | planned | — | Canonical form of one action, behind its own flag. |
| `count_tokens(...)` (name TBD) | 1 | 2, 4, 5 | planned | — | Pre-request token estimate; per-component counts. |
| `select_recent_events(events, token_budget, count_tokens)` (§13) | 1 | 5 | planned | — | Recent exact window; never splits an action from its observation. |
| `build_active_context(...)` (§23) | 1 | 2, 4, 5 | planned | — | The only place `active_messages` are built. Later phases add **slots** to it (loop feedback, task state, retrieved evidence), never a second builder. |
| Per-turn telemetry writer (§29) | 1 | 2, 3, 4, 5 | planned | — | Fields go into `context.metadata` every turn. Later phases add fields, not writers. |
| Context config + `AGENT_*` flags (§34) | 1 | 2, 3, 4, 5 | planned | — | One config object; each behavior-changing feature has its own flag. |
| Test scaffolding: fake `environment`, fake LLM client, event builders | 1 | 2, 3, 4, 5 | planned | — | The repo has no tests today; Phase 1 creates the harness everything else reuses. |
| `action_may_modify_state(command) -> bool` (§19 calls it `action_may_modify_repository_or_environment`) | 2 | 4, 5 | planned | — | Generic, conservative "might change repo/env" classifier. One classifier, one name. |
| Repeat / consecutive-read-only detectors | 2 | 5 | planned | — | Signals computed from events alone. |
| Loop-feedback message builders | 2 | 4 | planned | — | Injected through Phase 1's context-manager slot; Phase 4's guard rejections reuse the same path. |
| Extended `tools.run_shell` (output capture + offload) | 3 | 4, 5 | planned | — | Same function as today, not a new one. |
| Failure-preview extractor (name TBD) | 3 | 4 | planned | — | Finds "the error" in output generically; Phase 4's current-failure record reuses it. |
| Offload metadata on `ObservationEvent` (`full_output_path`, sizes) | 3 | 4, 5 | planned | — | Pointers to full output kept in the container. |
| `TaskState` + deterministic-subset records (§10) | 4 | 5 | planned | — | Phase 5 **extends** this; it does not introduce a second state type. |
| `deterministically_update_state(...)` | 4 | 5 | planned | — | Updates state from an action/observation pair. |
| `verification_may_be_stale` + invalidation v1 (§19) | 4 | 5 | planned | — | Uses Phase 2's classifier. |
| `validate_completion(task_state)` guard v1 (§27) | 4 | 5 | planned | — | Phase 5's per-criterion guard upgrades this. |
| State renderer for active context | 4 | 5 | planned | — | Fills the task-state slot in `build_active_context`. |
| `should_compact`, `split_compactable_events`, `update_compact_state`, `validate_compact_state` (§14–§18) | 5 | — | planned | — | Conditional on Gate G2. |

## Implemented code map

Filled in by the session that completes each phase: new/changed files, public functions with
signatures, config flags and env vars, telemetry fields, tests and fixtures added, and how to run
the tests. Format per phase:

```
### Phase N — <title> (issue #M, completed YYYY-MM-DD)
- Files: ...
- Public symbols: `name(sig)` — purpose
- Flags / env: ...
- Telemetry fields added: ...
- Tests: where, how to run, fixtures other phases can reuse
```

*Nothing implemented yet.*

## Measurement protocol

Written by Phase 0: the exact command, task set, repeats, token-counting method, and where baseline
numbers live. Every later phase re-runs it and posts the comparison in its issue.

*Not yet defined.*

## Notes for the next phase

Written when a phase completes: what the next phase must know that is not obvious from the code
(surprises, half-finished edges, constraints discovered). One heading per phase; delete a note once
it has been acted on and, if it still matters, move it to `decisions.md`.

*None yet.*

## Deviations from the plan

Where what was built differs from the spec, and why. Link the `DEC-NNN` if a decision was made.

*None yet.*
