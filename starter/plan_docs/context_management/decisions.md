# Decisions — Context Management and History Compaction

Append-only. New decisions get the next `DEC-NNN`. To change a decision, add a new entry that
supersedes it and set the old one's status to `Superseded by DEC-NNN`; do not rewrite history.

Entry format: Status (`Proposed | Accepted | Superseded`), Phase, Date, then Decision / Rationale /
Alternatives Considered / Why Rejected / Consequences.

---

## DEC-001: Plan docs live in `starter/plan_docs/context_management/` with a CLAUDE.md entry point

Status: Accepted  
Phase: All  
Date: 2026-09-21

### Decision

Keep the feature's design, roadmap, decisions, and per-phase specs under
`starter/plan_docs/context_management/`. The entry point is a `CLAUDE.md` (not a `README.md`) so
Claude Code loads it automatically when working in that directory.

### Rationale

`starter/plan_docs/` already held the planning docs, and the repo's other directories use the
nested-`CLAUDE.md` convention for auto-loaded context.

### Alternatives Considered

1. `docs/context-management/` at the repo root, with a `README.md`.
2. `starter/docs/` (existing human-facing guides).

### Why Rejected

1. There is no root `docs/`; it would split planning docs across two places. A `README.md` is not auto-loaded.
2. `starter/docs/` holds finished how-to guides, not in-flight plans.

### Consequences

A subdirectory `CLAUDE.md` loads when files in that directory are read, not at session start. To
load it every session, reference it from `starter/CLAUDE.md`.

---

## DEC-002: Eight phases (0–7) instead of the seven in `design.md` §31

Status: Superseded by DEC-004 and DEC-007 (only the baseline-phase idea stands; the slicing and the count changed to six phases, 0–5)  
Phase: All  
Date: 2026-09-21

### Decision

Track the work as Phases 0–7, one GitHub issue each, mapped to `design.md` §31 in `roadmap.md`.

### Rationale

A baseline-measurement phase is needed before any change can be judged (`design.md` §30), and
finer phases give smaller, independently reviewable contracts.

### Alternatives Considered

1. Use §31's seven phases as written.

### Why Rejected

§31 has no baseline phase, and its Phase 1 bundles history separation with canonicalization.

### Consequences

Numbers in issues and specs refer to the roadmap, not §31. Both are cross-referenced in `roadmap.md`.

---

## DEC-003: Maintain separate raw and active histories

Status: Accepted  
Phase: 1  
Date: 2026-09-21

### Decision

Keep a complete append-only raw event history and construct active model messages separately.

### Rationale

Compaction must reduce model input without destroying audit and evaluation data (`design.md` §5,
invariants 1 and 15).

### Alternatives Considered

1. Mutate the existing `messages` list in place.
2. Keep the full history and add a summary on top.

### Why Rejected

Mutating the only history destroys evidence. Sending the full history with a summary does not
reduce context usage.

### Consequences

Later features must build active context through the context manager rather than appending
directly to raw history. Anything that reads `context.metadata["messages"]` (e.g.
`starter/scripts/build_dashboard.py`) must be revisited in Phase 1.

---

## DEC-004: Slice phases by LLM dependence; make LLM compaction a gated bet

Status: Accepted (the Phase 5–7 layout it describes was changed by DEC-007; the tiering and gates stand)  
Phase: All (esp. 4–7)  
Date: 2026-09-21

### Decision

Order phases by what they depend on. Tier A (Phases 0–4) needs no extra model call and is built in
order. Tier B (Phases 5–6, semantic state and compaction) and Tier C (Phase 7, retrieval) are
conditional on measurement gates G2 and G3 in `roadmap.md`. Phase 4 holds only the deterministic
state and completion guard v1; the former standalone "structured state" phase is merged into
Phase 5. Phase 0 also prices baseline tokens in score terms.

### Rationale

The first draft made structured state (old Phase 4) a standalone phase, but deterministic code
cannot extract objectives or acceptance criteria from free text, so it would have little content
until an LLM populates it. More generally, compaction only pays off if context growth is actually
costing completion rate or meaningful score, and the scoring formula makes token savings small
next to capability. Evidence should decide whether the expensive phases happen.

### Alternatives Considered

1. Keep eight topic-ordered phases, all committed (the DEC-002 slicing).
2. Build LLM compaction unconditionally and evaluate it afterwards.

### Why Rejected

1 commits weeks of work to Phases 4–7 on assumption and leaves a standalone state phase with
almost no content. 2 is the same commitment with the evidence arriving too late to change course.

### Consequences

Specs for Phases 5–7 stay stubs until their gate passes. Gate G2 needs Phase 0's token pricing and
Phase 4's measurements. The design document is unchanged; only the order and commitment differ.

---

## DEC-005: Fold canonicalization into Phase 1, behind its own flag

Status: Accepted  
Phase: 1  
Date: 2026-09-21

### Decision

Canonicalization ships in Phase 1 with the raw/active split. It has its own config flag so it can
be measured on and off independently of the window.

### Rationale

Canonicalization is a small deterministic function of an action event and was too small to justify
its own contract. But dropping the model's narration may change its behavior (models imitate their
own prior turns), and that effect would be confounded with the window change unless separately
switchable.

### Alternatives Considered

1. Keep canonicalization as a standalone phase (previous Phase 2).
2. Fold it into Phase 1 with no flag.

### Why Rejected

1 is process overhead for a few dozen lines. 2 makes it impossible to tell which change hurt if
completion drops.

### Consequences

Phase 1 is somewhat larger. Its Gate G1 measures variant B with canonicalization on and off. If it
measures as harmful, it ships off.

---

## DEC-006: Move state-free loop controls to Phase 2

Status: Accepted  
Phase: 2  
Date: 2026-09-21

### Decision

Turn/context feedback (§25) and the §26 signals computable from raw events alone (repeated
command, consecutive read-only actions) become Phase 2, directly after Phase 1. Signals that need
task state — completed/remaining work, "no new finding", returning to a rejected approach — stay
with the state phases (5–6).

### Rationale

These controls do not depend on compaction and are likely cheaper and lower risk than it. Bundling
them with retrieval delayed them behind the most speculative work. The split is honest: only the
state-free subset can move early.

### Alternatives Considered

1. Leave them in the last phase with retrieval (original grouping).
2. Move all of §25/§26 early.

### Why Rejected

1 delays cheap wins behind gated work. 2 is impossible: some signals need state that does not exist
until Phase 4–5.

### Consequences

Phase 2 introduces a generic `action_may_modify_state` classifier that Phase 4 reuses for the stale
flag. Because nudges change behavior, they are individually switchable and measured; if they are
neutral, only the telemetry ships.

---

## DEC-007: Collapse the conditional back end to one Phase 5; demote retrieval to a backlog item

Status: Accepted  
Phase: 5 and backlog  
Date: 2026-09-21

### Decision

Reduce the roadmap from eight phases (0–7) to six (0–5). Phase 5 absorbs semantic task state,
compaction, and criteria-aware verification (the former Phases 5 and 6). Metadata retrieval (the
former Phase 7) is no longer a phase: it is a backlog section in `roadmap.md` with no spec or
issue until Gate G3 passes. Phases 0–4 are unchanged. In DEC-004 and DEC-006, "Phase 6" now means
Phase 5, and "Phase 7" means the retrieval backlog item.

### Rationale

A phase boundary is a point where we measure and can stop. Phases 0–4 each are. The former
Phases 5–7 sit behind gates G2/G3, do not exist yet, and their boundaries were guesses: criteria-aware
verification only makes sense once Phase 5 has produced criteria, and retrieval may never ship.
Separate specs and issues for work we cannot yet scope are overhead.

### Alternatives Considered

1. Keep eight phases with Phases 5–7 as conditional stubs (DEC-004 layout).
2. Also merge front-end phases (0 into 1, or 2/3 into 4).

### Why Rejected

1 keeps trackers for work that may never be built. 2 puts independent changes in one measurement, so
a completion-rate drop cannot be attributed, and it delays cheap wins behind riskier work; Phase 0
is also easy to skip if it is not its own deliverable.

### Consequences

The merged Phase 5 is large and is expected to be split again once G2 passes and there is real data
to split on. Criteria-aware verification (guard v2) must carry its own flag and on/off measurement,
since it no longer has its own phase boundary. Six GitHub issues instead of eight; retrieval gets
one only if G3 passes.

---

## DEC-008: Run each phase in a fresh session, fed by imports plus a handoff ledger

Status: Accepted  
Phase: All  
Date: 2026-09-21

### Decision

Each phase (refine or implement) runs in its own fresh session. What a session knows comes from:
(1) imports in this directory's `CLAUDE.md`: `roadmap.md`, `decisions.md`, `handoff.md`, and
`starter/agent/CLAUDE.md`; (2) reads the protocol requires: the phase spec, only the `design.md`
sections it cites, and the agent source. `handoff.md` is the single ledger of interfaces
(planned → implemented), code map, notes for the next phase, and deviations, and every phase must
update it before it counts as done. Phases follow a reuse-before-create rule. `roadmap.md` is the
only place phase status is tracked.

### Rationale

A fresh session has no memory of earlier phases, and the failure mode is a phase inventing its own
helper because it cannot see what earlier phases built. The source plus a ledger of intended
interfaces prevents parallel versions. Reviewing the real code showed the design's pseudocode
invites exactly that: a separate `run_shell_with_output_capture` next to `run_shell`, action kinds
(`complete`/`invalid`) that differ from the code's (`done`/`none`), and two names for the same
classifier. The ledger fixes the names and the extension points up front.

### Alternatives Considered

1. Import `design.md` as well, so every session has the full design.
2. Keep implementation notes inside each phase spec and have each session read all earlier specs.
3. Rely on git history and the code alone, with no ledger.
4. Import the plan from the root `CLAUDE.md` so it loads at launch in every session.

### Why Rejected

1 costs ~12K tokens per session, almost all of it sections the phase does not touch; the phase
spec already cites the sections it needs. 2 spreads "what exists" across N files, duplicates
content, and gives no single view. 3 shows what changed but not what later phases are meant to
reuse. 4 taxes every session in the repo, including unrelated ones, with the plan's context.

### Consequences

- A nested `CLAUDE.md` loads when a file in its directory is read, not at launch, so each session
  starts by reading a file here (the kickoff prompt in `CLAUDE.md`).
- The ledger is only as good as the discipline of updating it; "handoff updated" is an exit
  criterion of every phase.
- About 8K tokens are loaded at each session start (this `CLAUDE.md` plus its four imports). `decisions.md` grows over time; if it passes
  ~500 lines, split it into an index plus entries.
- `starter/agent/CLAUDE.md` is imported, so a stale claim in it misleads every later session. Each
  phase updates it where it becomes false.
- Claude Code may ask for one-time approval of the imports.

---

## DEC-009: The baseline of record is 3 runs of the 10-task sample (2026-09-12 plus two 2026-09-21 repeats)

Status: Accepted  
Phase: 0 (binds every gate)  
Date: 2026-09-21 (revised 2026-09-21 after the two repeat runs completed)

### Decision

The baseline is three runs of the unmodified `BaselineAgent` on `terminal-bench-sample@2.0`
(10 tasks), model `qwen3.8-27b`, `LLM_MAX_TOKENS=8192` and defaults for every other setting:
`jobs/2026-09-12__21-32-36` (original, concurrency inferred at 4), `jobs/2026-09-21__20-31-31` and
`jobs/2026-09-21__20-32-09` (repeats, run to settle the noise rule — see Deviation below). Every
later measurement uses the same 10 tasks, the same model and settings, and `-n 4` set explicitly
(`N_CONCURRENT=4`; Harbor's default is 4, the script's is 1). The public subset
(`eval/public_subset.txt`) is not used at any gate.

### Rationale

The original run already existed, and the agent's `.py` files are identical to commit `754f792` for
all three runs, so all three are runs of the unmodified agent. The 10-task sample is available now
and stable, while the public subset is 3 placeholders until kickoff, so a baseline on it would be
discarded.

### Alternatives Considered

1. Re-run the baseline at `-n 1` for a known concurrency.
2. Keep the original run as the only sample, with no repeats.
3. The public subset, or the sample plus the subset.

### Why Rejected

1 costs about two hours and still would not match the original run. 2 was the initial plan but left
the noise rule unsettled; the owner ran two repeats instead. 3 measures placeholders that will be
replaced.

### Deviation: the two repeats ran concurrently with each other, not sequentially

The Phase 0 spec's re-run command (§2) and my own guidance both called for one run at a time, so
each measurement sees `-n 4` and nothing else competing for the shared endpoint. `jobs/2026-09-21__20-31-31`
started at 20:31:32 and `jobs/2026-09-21__20-32-09` started 38 seconds later; both ran until about
21:02. They overlapped almost completely, so the actual load was 8 concurrent trials, not the
intended 4, for nearly the whole duration of both.

**What this does and doesn't affect:** the pass/fail pattern was identical across all three
runs — same 4 tasks always pass, same 6 always fail — including at double the intended load, so the
completion-rate finding below is not undermined; if anything it is a harder test. Token totals
(3.63M / 4.33M / 4.85M) are not independent samples under matched conditions, though, and the
doubled load likely inflated turns and tokens versus a true sequential `-n 4` repeat (e.g. more
retry/exploration under contention). Treat the token spread as an upper bound on noise, not a clean
estimate of it, and do not average these three totals into a single "typical" token figure without
that caveat. A true sequential repeat has not been run.

### Consequences

- **Completion rate looks stable on this sample:** 4/10 in all three runs, with the identical 4 tasks passing and the identical 6 failing every time, including under double concurrency. No flaky task observed yet.
- **Token totals vary about ±29% around a mean of ~4.27M** (stdev ≈ 612K on 3.63M/4.33M/4.85M), but this spread is confounded by the concurrency deviation above and should not be read as measured under matched conditions.
- The model and settings are the owner's recollection and a reconstruction for the 2026-09-12 run (`.env` was edited after it); the two 2026-09-21 runs used the same settings, deliberately unchanged.
- All three baselines live only in local, gitignored `jobs/`.
- `qwen3.8-27b` is a dev model, not the approved submission checkpoint; token pricing is indicative until re-priced on the submission model.
- A genuinely sequential `-n 4` repeat is still outstanding if a clean noise estimate for tokens is needed later.

---

## DEC-010: Phase 0 measures with `jq` over `jobs/`: no agent edit, no committed numbers, endpoint usage as the token source

Status: Accepted  
Phase: 0 (binds every gate)  
Date: 2026-09-21

### Decision

- Token counts are the endpoint's `usage` as accumulated in `n_input_tokens` and `n_output_tokens`, the same quantity the leaderboard charges. No local tokenizer.
- `agent.py` is not changed in Phase 0; there is no per-turn usage telemetry. Per-turn and peak context are an offline estimate from the stored `messages`, scaled to the exact `n_input_tokens`, and always labelled an estimate.
- Baseline numbers stay in `jobs/`. `handoff.md` holds the protocol, the derivation commands and the failure labels, not the numbers. No summary file is committed and no script is added; derivations are documented `jq` snippets.
- The baseline's failed runs are labelled by hand from a fixed cause list.

### Rationale

Gates G1 and G2 are decided on completion rate and total tokens, and both come exactly from
`n_input_tokens` and `n_output_tokens`. A per-turn curve is diagnostic only, and a context overflow
would already show up as an exception because `llm.chat()` has no retry. Editing `agent.py` would
alter the "unmodified" baseline and pre-empt Phase 1's per-turn telemetry writer (ledger row owned by
Phase 1).

### Alternatives Considered

1. Save per-turn `usage.prompt_tokens` into `context.metadata` in `agent.py`.
2. Add a local tokenizer.
3. Commit a `baseline.md` numbers file next to the protocol in `handoff.md`.

### Why Rejected

1 gives exactness for something the score does not charge, edits the baseline agent, and moves
ownership of telemetry out of Phase 1. 2: approved models may not share a tokenizer with any
available library, and the endpoint's count is the scored one. 3 was declined by the owner in favor
of simplicity, accepting that the baseline exists only on this machine.

### Consequences

- The peak-context figure is roughly ±20%, and Phase 1's exact per-turn counts are not directly comparable with it; say so when comparing.
- Deleting `jobs/2026-09-12__21-32-36` deletes the baseline (and the only copy of its transcripts). Back it up outside the repo.
- Token totals and the score penalty are re-derived from `jobs/` at each gate.
- Phase 1 still owns the per-turn telemetry writer; the handoff ledger is unchanged.

---

## DEC-011: Phase 1 module layout — `events.py` and `context.py`, plain-list history, `ShellResult` layering

Status: Accepted
Phase: 1
Date: 2026-09-21

### Decision

Event dataclasses (`Event`, `AssistantActionEvent`, `ObservationEvent`) live in a new
`starter/agent/events.py`. Everything that assembles or reads them — `canonicalize_action`, the
recent-window selector, `build_active_context`, telemetry, and a `record_observation(shell_result,
turn)`-style helper that turns `tools.run_shell`'s plain result into an `ObservationEvent` — lives
in a new `starter/agent/context.py`. `tools.run_shell` is changed to return a plain `ShellResult`
dataclass (exit code, stdout, stderr, sizes, did-not-complete flag) instead of a formatted string;
it does not import `events.py`. Raw history is a plain list owned by `agent.py`'s `run()` loop,
appended to as events are created and passed as a parameter into `context.py`'s functions;
`context.py` exposes no stateful class.

### Rationale

Keeps `tools.py` a pure execution layer with no dependency on the event/context machinery,
matching its existing separation from `agent.py`'s conversation-shaped code. Passing `raw_events`
as a plain list into pure functions (rather than a stateful `ContextManager`) matches design.md's
own pseudocode style and keeps `context.py` trivially testable — pass a list of events in, get
`active_messages` out, no hidden state.

### Alternatives Considered

1. `tools.run_shell` returns the `ObservationEvent` directly.
2. `context.py` exposes a stateful `ContextManager` class owning the raw-events list and telemetry internally.
3. `canonicalize_action` lives in `tools.py`, next to `Action` and `parse_action`.

### Why Rejected

1 would make `tools.py` depend on `events.py`, coupling execution to the conversation/event model
for no benefit — the caller already has the turn number and timestamp needed to build the event.
2 adds a stateful object every test has to fake instead of a plain list, and design.md's own
pseudocode is function-based. 3 was considered since `canonicalize_action` only depends on
`Action`, but was decided against in favor of grouping it with its main caller
(`build_active_context`) in `context.py`.

### Consequences

`agent.py`'s `run()` loop now owns and threads through a `raw_events` list the same way it already
owns `messages` today. Any later phase adding a new event-producing step (Phase 3's offload, Phase
4's state updates) extends `context.py`, not `tools.py` or `agent.py` directly.

---

## DEC-012: `context.metadata["messages"]` becomes the raw event history

Status: Accepted
Phase: 1
Date: 2026-09-21

### Decision

`context.metadata["messages"]` (read today by `scripts/build_dashboard.py`) is repointed to hold
the serialized raw event list — every `AssistantActionEvent` and `ObservationEvent`, including
narrated/nudge turns — rather than the OpenAI-style role/content list or the bounded
`active_messages` actually sent to the model.

### Rationale

This is the complete audit record design.md §5 and DEC-003 require; active context is deliberately
partial by construction, so a viewer built on anything less than the full raw history cannot
reconstruct what actually happened, only what the model was shown on its last turn.

### Alternatives Considered

1. Store both raw events (under a new key) and a snapshot of the last `active_messages`.
2. Keep `"messages"` as active-context-only, matching what the model actually saw.

### Why Rejected

1 doubles what must be kept in sync every turn for a use case (seeing exactly the last turn's
prompt) that isn't needed yet and can be reconstructed from raw events plus the context manager's
own logic if it ever is. 2 conflicts with DEC-003 and invariants 1/15: it would mean the only thing
written to run metadata is not the complete record.

### Consequences

`scripts/build_dashboard.py` must be updated to read the new shape (see DEC-019). Anything else
that reads `context.metadata["messages"]` must be treated as reading raw history, not a literal
conversation transcript.

---

## DEC-013: Nudge/no-action turns are recorded as an event, excluded from the recent window, with no paired observation

Status: Accepted
Phase: 1
Date: 2026-09-21

### Decision

When a model response has no valid action (`Action.kind == "none"`), it is recorded as an
`AssistantActionEvent(action_kind="none", raw_response=text)` in raw history. No `ObservationEvent`
is created for it — there was no command and no environment interaction. It is excluded from the
recent-window pair budget.

### Rationale

Recording it preserves visibility into how often the model drifts off-protocol, which Phase 2's
loop-control heuristics want. Not pairing it with a synthetic `ObservationEvent` avoids inventing
sentinel values (null `exit_code`, null `stdout_preview`, ...) for a type whose fields describe a
container execution that never happened — every consumer of `ObservationEvent` (rendering, pairing
logic, Phase 3's offload, Phase 4's failure extractor) would otherwise need to special-case it.

### Alternatives Considered

1. Also emit an `ObservationEvent` with sentinel/null fields, so every assistant turn has exactly one paired observation-shaped record.
2. Do not record nudge turns as events at all.

### Why Rejected

1 was tried first and reverted: it adds a null-check burden to every later reader of
`ObservationEvent` for no offsetting benefit, since nothing about a nudge needs the
`ObservationEvent` shape. 2 loses the off-protocol-drift signal Phase 2 wants and makes raw history
incomplete for a turn that did happen.

### Consequences

Code that assumes "every `AssistantActionEvent` has exactly one paired `ObservationEvent`" is wrong
for `action_kind="none"` turns; `select_recent_events` and any window-pairing logic must handle a
lone action event. `NUDGE_MESSAGE`'s literal text is not stored per-occurrence (it's a fixed
constant); only the model's raw response is.

---

## DEC-014: Recent window ships as a fixed pair count (default 6, config-driven); no mitigation or telemetry for dropped early context

Status: Accepted
Phase: 1
Date: 2026-09-21

### Decision

The recent window (design.md §13) selects a fixed number of recent action–observation pairs,
default 6, configurable via `AGENT_RECENT_WINDOW_PAIRS`. Phase 1 ships no mitigation for
early-context loss (e.g. no pinned first turn) and no telemetry signal for events dropped from the
window each turn.

### Rationale

Design.md §13's own example uses six turns, and there is no data yet to tune the number — Gate G1
is where it gets tuned empirically. The window's early-context loss is exactly design §30 variant
B's known, accepted gap; Phase 4 (task state) and Phase 5/backlog (retrieval) exist to address it,
and adding a mitigation or dedicated telemetry counter now would be scope creep ahead of evidence
that it's actually costing completion rate on the 10-task sample.

### Alternatives Considered

1. Default window of 10 or 3 pairs.
2. Always pin turn 1's action–observation pair in addition to the recent window.
3. Add a per-turn `events_dropped_this_turn` telemetry counter.

### Why Rejected

1 has no more evidence behind it than 6; 6 was chosen only as design.md's own starting point. 2
adds a special case to `select_recent_events` before there's evidence it's needed. 3 was considered
so Gate G1's failure-labeling could correlate regressions with dropped context, but was declined as
unnecessary scope for a first measurement — revisit if G1 shows an unexplained regression.

### Consequences

The window size is a config default, not a hardcoded constant, so Gate G1 can retune it without a
code change. If Gate G1 shows a completion-rate regression with no other explanation, dropped early
context is a plausible cause with no direct telemetry to confirm it — that would have to be
diagnosed from the raw event history by hand.

---

## DEC-015: No local tokenizer; per-turn telemetry reports the exact endpoint total with no per-component split

Status: Accepted
Phase: 1
Date: 2026-09-21

### Decision

Phase 1 adds no local tokenizer and no token-bounded window (deferred per design.md §13).
Recent-window selection is by turn/pair count only. Per-turn telemetry's total input-token figure
is the exact value already returned by the endpoint (`usage.prompt_tokens`, the same source
DEC-010 uses for the scored total) carried into the per-turn record; design.md §29's per-component
fields (`system_prompt_tokens`, `task_tokens`, `recent_history_tokens`, etc.) are not populated
this phase.

### Rationale

The endpoint gives one exact number for the whole prompt and never a breakdown by component, so any
per-component figure would necessarily be an estimate (e.g. character-proportion, as DEC-010
already does for the unrelated peak-context estimate) layered onto an otherwise-exact number. Given
the phase doesn't need per-component budgets to select the window (turn-count based), that estimate
would exist for telemetry only, and was judged not worth adding this phase.

### Alternatives Considered

1. Char-proportion estimate for each component, scaled to the exact per-turn total (matching DEC-010's method).
2. Leave even the total input-token telemetry field unpopulated until real per-component counting exists.

### Why Rejected

1 was the initial recommendation but declined: it introduces an estimation method into the phase's
telemetry before there's a need it serves (no Phase 1 decision depends on the split). 2 throws away
a number that's already exact and free (the endpoint's own usage figure) for no reason.

### Consequences

Phase 1's telemetry can show sent-token totals per turn exactly, but cannot show which component
(system prompt vs. task vs. recent window) drove a given total — that granularity waits for a phase
that actually needs per-component budgets enforced (a token-bounded window, per §13's "preferred
mature implementation").

---

## DEC-016: Confirmed canonicalization edge cases require no design or code change

Status: Accepted
Phase: 1
Date: 2026-09-21

### Decision

Three canonicalization edge cases raised as open questions in the phase spec are confirmed to need
no change:

1. **Multi-block responses:** `canonicalize_action` only ever sees the already-parsed `Action`
   (from `tools.parse_action`, which uses `CODE_BLOCK_RE.search` — first match only), so the
   canonical form always reflects only the executed block; discarded blocks remain visible solely
   in `raw_response`.
2. **Untagged/```sh/```shell fences:** `parse_action`'s regex (accepting `bash`, `sh`, `shell`, or
   untagged fences) is unchanged. Canonicalization renders `Action.command` into the standard
   ` ```bash ` form for display only, after parsing has already decided what executed — it cannot
   change what ran.
3. **Reasoning-model fallback** (`llm.py` falling back to `reasoning_content` when `content` is
   empty): out of scope for Phase 1. Canonicalization and the event model treat fallback text
   exactly like normal content, with no visibility flag.

### Rationale

All three are consequences of canonicalization operating strictly after parsing, on the `Action`
already produced by `tools.parse_action` — there is no path by which canonicalizing a response
could change what was executed or add missing information about what fences are accepted.

### Alternatives Considered

1. Tag discarded extra code blocks on the event (e.g. `extra_blocks_discarded: true`).
2. Tighten `CODE_BLOCK_RE` to require an explicit ` ```bash ` tag, rejecting sh/shell/untagged blocks.
3. Add a `used_reasoning_fallback` flag to `AssistantActionEvent`.

### Why Rejected

1 adds a telemetry field for a case with no evidence it matters yet. 2 changes real execution
behavior (not just canonicalization/display), affecting the baseline's parsing contract — a larger
change than this phase implies, needing its own measurement. 3 was considered low-cost but judged
out of scope for Phase 1's event model; the known fix (raising `LLM_MAX_TOKENS`) remains a
config-level mitigation.

### Consequences

None of these open questions block Phase 1 becoming `ready`; no code changes to `tools.py`'s
parsing behavior are needed for any of them.

---

## DEC-017: Parse-failure/no-action events reuse `Action.kind`'s `"none"` as `action_kind`

Status: Accepted
Phase: 1
Date: 2026-09-21

### Decision

`AssistantActionEvent.action_kind` uses the same vocabulary as `tools.Action.kind` (`"shell"` /
`"done"` / `"none"`), not design.md §6's `Literal["shell", "complete", "invalid"]`. A parse failure
(`Action.kind == "none"`) is recorded with `action_kind="none"` verbatim.

### Rationale

The handoff ledger's rule is that the code's names win over design.md's pseudocode names (already
true for `"done"`/`"none"` vs. design's `"complete"`/`"invalid"`). Introducing a second vocabulary
for the same concept (translating `"none"` to `"invalid"` at the event boundary) would need to be
kept in sync for no benefit.

### Alternatives Considered

1. Use design.md's literal terms (`"complete"`/`"invalid"`) for `action_kind`, translating from `Action.kind` at the point the event is built.

### Why Rejected

Two names for the same three-way distinction is exactly the kind of drift DEC-008 identified
design.md's pseudocode as inviting (citing this exact `complete`/`invalid` vs. `done`/`none`
mismatch as a motivating example).

### Consequences

Any later phase reading `action_kind` should expect `"shell"`/`"done"`/`"none"`, matching
`Action.kind` exactly.

---

## DEC-018: Canonicalization (DEC-005) ships with a default of on

Status: Accepted
Phase: 1
Date: 2026-09-21

### Decision

The canonicalization flag introduced by DEC-005 is named `AGENT_CANONICALIZE` and defaults to on
(canonicalization is applied unless explicitly disabled).

### Rationale

Owner's choice, made explicit against the alternative of defaulting off.

### Alternatives Considered

1. Default off, keeping a plain `harbor run` closest to the already-measured Phase 0 baseline (which never canonicalized), with Gate G1 turning it on for comparison.

### Why Rejected

The owner chose to treat canonicalization as the intended steady state once Phase 1 ships, with off
retained only as the explicit comparison arm for Gate G1, rather than the other way around.
(Recorded here rather than re-argued: DEC-005's own consequence already commits to shipping the
flag off if it measures as harmful, regardless of its default.)

### Consequences

A plain `harbor run` of the Phase-1 agent with no extra flags canonicalizes by default. Gate G1's
comparison run must explicitly set `AGENT_CANONICALIZE=off` to reproduce the Phase-0-equivalent
behavior.

---

## DEC-019: `scripts/build_dashboard.py` gets a minimal patch, not a full event-aware rewrite

Status: Accepted
Phase: 1
Date: 2026-09-21

### Decision

`build_dashboard.py` is updated only enough to read `context.metadata["messages"]` as the new
raw-event list (per DEC-012) and continue rendering a transcript; it does not gain new views (e.g.
raw-vs-canonical diffing, per-event-kind rendering).

### Rationale

`build_dashboard.py` is the only consumer of `context.metadata["messages"]` outside the agent, so
leaving it unpatched would silently break the local job-viewer for every run from Phase 1 on — that
much is a Phase 1 dependency. Richer event-aware views are dashboard feature work with no phase
currently depending on them.

### Alternatives Considered

1. A full rewrite building proper event-aware rendering now, since this is the first phase to introduce the event model.

### Why Rejected

Building views nothing yet needs, ahead of a phase that actually requires them for debugging, is
scope creep beyond what Phase 1 owes.

### Consequences

`build_dashboard.py`'s `CODE_BLOCK_RE`/`NUDGE_MESSAGE` mirrors (`starter/agent/CLAUDE.md`'s noted
duplication) must still be kept in sync with `tools.py`/`prompts.py`; richer event views remain a
future, undated improvement.

---

## DEC-020: Test scaffolding cut from Phase 1's scope

Status: Accepted
Phase: 1
Date: 2026-09-21

### Decision

Phase 1 does not add pytest, `starter/tests/`, or reusable fakes (environment, LLM client, event
builders), reversing the scope line in `phases/01-history-separation.md` and the corresponding
exit criterion. Verification for Phase 1 relies solely on Gate G1's harbor-run measurement protocol
(`handoff.md`'s Measurement protocol).

### Rationale

Owner's choice, made after considering the case for it (Phase 1 introduces the codebase's first
pure, edge-case-heavy logic — `canonicalize_action`, `select_recent_events`, the
action/observation pairing invariant — which is cheap to unit-test and expensive to catch via a
~30-minute harbor run).

### Alternatives Considered

1. Keep a minimal version of the scaffolding, sized to just the phase spec's own listed test cases (canonicalization variants, window selection, pairing invariant, token accounting).

### Why Rejected

The owner judged it unnecessary for this phase, choosing to rely on the existing measurement
protocol instead.

### Consequences

The interface ledger's "Test scaffolding" row (owner Phase 1, reused by 2–5) has no implementation
to hand off; a later phase that wants unit tests must add this scaffolding itself, from scratch,
since Phase 1 no longer provides it. Phase 1's exit criteria and the phase spec's Scope section are
edited to remove the test-scaffolding bullet accordingly. This also means `canonicalize_action`,
`select_recent_events`, and the pairing invariant ship with no automated test coverage — Gate G1's
harbor-run pass/fail and token totals are the only signal if something in this logic is wrong, and a
subtle bug (e.g. a mis-paired action/observation) may not surface as a distinguishable failure.

---

## DEC-021: `ShellResult`/`ObservationEvent` carry already-truncated text; truncation ownership stays in `tools.py` this phase

Status: Accepted
Phase: 1
Date: 2026-09-21

### Decision

`tools.run_shell`'s change to return `ShellResult` does not move or remove the existing
`tools._truncate`/`MAX_OBSERVATION_CHARS` behavior. `ShellResult.stdout`/`.stderr` hold the same
first/last-half-truncated text the current formatted string already contains, at the same 6000-char
limit. `ShellResult` additionally carries `original_stdout_chars`, `original_stderr_chars` (the
pre-truncation lengths, cheap to record — `len()` before truncating) and a `truncated: bool`.
`ObservationEvent` carries these same fields through unchanged. A command that raises inside
`environment.exec` (the current `except Exception` path) is represented as `did_not_complete: bool`
plus an `error: str | None` holding the exception message, rather than raising out of `run_shell`.

### Rationale

The handoff ledger already scopes `tools._truncate`/`MAX_OBSERVATION_CHARS` as "touched by 3," i.e.
Phase 1 leaves this behavior alone; Phase 3 replaces it with real preview/offload logic (per the
ledger's "Extended `tools.run_shell` (output capture + offload)" row). Recording the pre-truncation
counts now is nearly free and lets Phase 3 detect "this observation was truncated and by how much"
without re-deriving it or changing `ObservationEvent`'s shape.

### Alternatives Considered

1. `ShellResult` holds full untruncated stdout/stderr; truncation moves entirely into
   `prompts.observation_message` at render time.
2. `ShellResult` holds truncated text only, with no size/truncated-flag fields (matching the
   original phase spec's silence on this).

### Why Rejected

1 makes `context.metadata["messages"]` (and therefore every run's stored JSON) hold full untruncated
command output for every turn, which the baseline never did and which was not requested; it also
duplicates the offload work Phase 3 is scoped to do, ahead of Phase 3 existing. 2 leaves the
"complete raw history" claim in DEC-003/DEC-012 silently only-partially-true (raw history reflects
only what survived truncation) with no way for a reader to tell truncation happened at all.

### Consequences

Phase 1's raw history is a complete record of *what the agent saw*, not of the full real command
output beyond the truncation limit — that gap is explicit (via `truncated`/`original_*_chars`) and
closed by Phase 3, not Phase 1. `DEC-003`/`DEC-012`'s "complete audit record" language should be
read as "complete given today's truncation limit" until Phase 3 ships.

---

## DEC-022: `Event`/`ObservationEvent` field sets are trimmed to only what Phase 1 populates

Status: Accepted
Phase: 1
Date: 2026-09-21

### Decision

Phase 1's `events.py` dataclasses drop fields from design §6's pseudocode that nothing in this phase
populates, rather than carrying them as unused/`None` placeholders:

- `Event` (base): drops `token_count` (killed for this phase by DEC-015) and `tags` (introduced by
  Phase 2's classifier work). Keeps `id`, `turn`, `event_type`, `timestamp`.
- `ObservationEvent`: drops `started_at`, `duration_seconds` (no timing capture this phase — nothing
  in `tools.run_shell`'s current scope measures it) and `full_output_path` (explicitly owned by
  Phase 3 per the handoff ledger's "Offload metadata on `ObservationEvent`" row). Keeps `command`,
  `exit_code`, `stdout`, `stderr`, `original_stdout_chars`, `original_stderr_chars`, `truncated`,
  `did_not_complete`, `error` (per DEC-021).
- `AssistantActionEvent` is unchanged from the original phase spec (`raw_response`, `action_kind`,
  `command`, `canonical_content`).

A later phase that needs a dropped field adds it to the dataclass when it actually populates it,
rather than Phase 1 guessing its shape now.

### Rationale

Design.md's pseudocode is illustrative of the eventual mature shape across all five phases, not a
literal Phase-1 contract — the project's own established rule (DEC-016/DEC-017: code's names win
over design's literal pseudocode) already treats design.md as a source of intent, not a schema to
copy verbatim. Carrying unused fields (always `None`/`0`) adds a null-check burden to every future
reader for no benefit this phase provides, exactly the pattern DEC-013 already rejected once for
`ObservationEvent`'s sentinel-field question.

### Alternatives Considered

1. Include all of design §6's fields now, populated with `None`/defaults, so later phases don't
   need to touch the dataclass shape.
2. Include `tags` now (empty dict) since Phase 2 is immediately next, even though Phase 1 doesn't
   populate it.

### Why Rejected

1 is scope creep into fields with no Phase 1 consumer and duplicates the risk DEC-013 already flagged
for `ObservationEvent`'s null-sentinel question. 2 was considered as a "one phase early" compromise
but rejected for consistency: Phase 1 populates nothing into `tags`, so an empty dict is indistinguishable
from the field not existing yet, and Phase 2 adding the field when it starts populating it is no more
work than Phase 2 finding it already there and empty.

### Consequences

Phase 2 adds `tags` to `Event` when it introduces its classifier; Phase 3 adds `full_output_path` to
`ObservationEvent` when it ships offload; no phase needs per-event token counting until (if ever) a
phase reintroduces it. `handoff.md`'s "Provides" row for `Event`/`AssistantActionEvent`/
`ObservationEvent` should record the trimmed field lists, not design §6's fields, when Phase 1 fills
in the *Implemented code map*.

---

## DEC-023: Phase 1's context config holds only the two flags it defines

Status: Accepted
Phase: 1
Date: 2026-09-21

### Decision

The "context config/flags" object introduced by Phase 1 in `context.py` (handoff ledger's "Context
config + `AGENT_*` flags (§34)" row) holds exactly two fields this phase: `canonicalize: bool`
(`AGENT_CANONICALIZE`) and `recent_window_pairs: int` (`AGENT_RECENT_WINDOW_PAIRS`). It does not
pre-populate the other fields from design §34's example config (`soft_limit_ratio`,
`hard_limit_ratio`, per-component token budgets, `safety_margin_tokens`, `turn_budget_warning`,
`output_directory`, etc.) as stubs or defaults.

### Rationale

Design §34 sketches the config's eventual mature shape across all five-plus phases; almost every
field in it belongs to a phase that doesn't exist yet (token-bounded budgets are deferred per DEC-015,
turn-budget warnings are Phase 2, `output_directory` is Phase 3's offload). A single config object
that later phases add fields to (per the ledger's own instruction: "each behavior-changing feature
has its own flag") only requires that the object exists and is extensible, not that it anticipates
every future field now.

### Alternatives Considered

1. Pre-populate all of design §34's fields now with placeholder/default values, so the "one config
   object" is complete from the start.

### Why Rejected

1 adds ~11 fields with no Phase 1 (or even clearly-defined Phase 2/3) consumer yet, several of which
(the token budgets) are explicitly deferred by DEC-015 and may never take this exact shape once a
phase actually needs them — guessing the shape now risks a rename/restructure later for no benefit
gained by guessing early.

### Consequences

Phase 2 adds its own field(s) (e.g. a turn-budget-warning threshold) to the same config object rather
than creating a second one; same for Phase 3 onward. The config object's growth is one field per
phase that actually uses it, tracked in `handoff.md`'s ledger row as it happens.

---

## DEC-024: Per-turn telemetry is stored as `context.metadata["telemetry"]`, a list appended every turn

Status: Accepted
Phase: 1
Date: 2026-09-21

### Decision

Phase 1's per-turn telemetry writer appends one record per turn to a new `context.metadata["telemetry"]`
list, alongside the existing `turns`/`finished`/`messages` keys (written every turn per the existing
"update `context` every turn" invariant). Each Phase 1 record is `{"turn": int, "sent_input_tokens":
int}`, where `sent_input_tokens` is that turn's exact `usage.prompt_tokens` from the endpoint
(DEC-015's total, no per-component split).

### Rationale

The phase spec named a "per-turn telemetry writer" as a Phase 1 deliverable reused by Phases 2–5 but
never said where its output lives or what shape a record has; without this, a later phase adding its
own telemetry field has nothing to extend. A list under its own metadata key (rather than folding
into `"messages"`, which DEC-012 already dedicates to raw events) keeps telemetry additive and
readable independently of the event history.

### Alternatives Considered

1. Fold per-turn token totals into each `AssistantActionEvent` as a field instead of a separate list.
2. Only store the final cumulative total (already available via `context.n_input_tokens`), with no
   per-turn breakdown.

### Why Rejected

1 conflicts with DEC-022's trimming of `Event`'s `token_count` field for this phase, and ties
telemetry's shape to the event model's shape for no benefit. 2 already exists today via
`context.n_input_tokens`/`n_output_tokens` and provides no per-turn signal, which is the entire point
of design §29's telemetry requirement this phase is scoped to partially satisfy.

### Consequences

Phases 2–5 add fields to each record in `context.metadata["telemetry"]` (e.g. Phase 2's loop-control
signals, Phase 3's offload stats) rather than inventing a second telemetry location.
`scripts/build_dashboard.py` is not required to render this key in Phase 1 (DEC-019 scopes its patch
to reading `"messages"` only); a future dashboard improvement may add a telemetry view.

---

## DEC-025: `ShellResult` carries `command`, so `record_observation` can populate `ObservationEvent.command`

Status: Accepted
Phase: 1
Date: 2026-09-22

### Decision

`tools.run_shell`'s `ShellResult` return type gains a `command: str` field, carried through
unchanged from `run_shell`'s own `command` argument (which it already receives and uses to call
`environment.exec`). `record_observation(shell_result, turn)`'s signature is unchanged — it reads
`shell_result.command` to populate the required `ObservationEvent.command` field (DEC-022) rather
than taking a third parameter.

### Rationale

A goldfish test of this phase spec (2026-09-22) found that `ObservationEvent` requires `command`
(DEC-022), but neither the originally-specified `ShellResult` field list nor
`record_observation(shell_result, turn)`'s two-argument signature had anywhere to read it from —
the dataclass could not be constructed as specified. `run_shell` already has `command` in scope at
the point it builds the result, so attaching it there is the smallest fix and keeps
`record_observation`'s signature untouched.

### Alternatives Considered

1. Leave `ShellResult` as originally specified (execution-result fields only) and add `command` as
   a third parameter to `record_observation`, with `agent.py` passing `action.command` in
   explicitly.

### Why Rejected

Both were equally small to build; this just decides whether "the command that was run" is treated
as part of the shell result or as context the caller re-supplies. Attaching it to `ShellResult`
keeps `record_observation`'s signature as originally drafted and matches the intuition that a
result of running a command should say what command produced it.

### Consequences

`tools.run_shell`'s docstring/return type must document the new `command` field. No other Phase 1
symbol changes.

---

## DEC-026: Nudge is a trailing-only special case in `build_active_context`, not a windowed event

Status: Accepted
Phase: 1
Date: 2026-09-22

### Decision

`select_recent_events` never sees `action_kind="none"` events at all — it walks raw history
backward taking complete action–observation pairs only, exactly as originally specified, with no
awareness that `"none"` events exist. Separately, `build_active_context` always checks whether the
*last* raw event is a `"none"`-kind `AssistantActionEvent`; if so, it appends that event's
`raw_response` (verbatim, regardless of `AGENT_CANONICALIZE` — see DEC-028) followed by
`prompts.NUDGE_MESSAGE` to the active messages, unconditionally and outside the pair-count budget.
A `"none"` event that is not the most recent raw event is not shown in active context at all (it
remains in raw history for audit).

### Rationale

A goldfish test of this phase spec (2026-09-22) found no described mechanism for the model to ever
see a retry nudge, since DEC-013 already excludes `"none"` events from having a paired
`ObservationEvent`, and `select_recent_events` was described as taking "complete
action–observation pairs only" — silently dropping today's nudge-retry behavior (a functional
regression, not a cosmetic gap).

Only the trailing `"none"` event is live: `NUDGE_MESSAGE` is a present-tense instruction ("produce
a valid action now"), and resurfacing it for a `"none"` event the model already recovered from
several turns ago is confusing, out-of-place mid-transcript, and burns tokens for zero
decision-relevant value — directly working against this phase's purpose. Keeping
`select_recent_events` fully unaware of `"none"` events (rather than including them unpaired inside
the walked window) also keeps that function's "never split an action from its observation"
invariant trivially true with no special-casing inside the walk itself; all nudge-specific logic
lives in exactly one place.

### Alternatives Considered

1. Include `"none"` events inside the window returned by `select_recent_events` (not counted toward
   the pair budget), with `NUDGE_MESSAGE` rendered inline wherever such an event lands in the
   selected window.

### Why Rejected

1 resurfaces a stale, present-tense instruction for turns the model already moved past, purely
because that turn happened to fall within the last N pairs' span — wasting tokens on content with
no bearing on the model's next decision, and requiring `select_recent_events`'s walk to special-case
`"none"` events for no benefit `build_active_context`'s single trailing check doesn't already give.
`observation_message`'s documented contract ("the single renderer of a `ShellResult`/
`ObservationEvent`") also has no natural home for a `"none"` event either way, since one never has
an `ObservationEvent` — so 1 does not actually save a special case, it only relocates the same one
to fire on every occurrence instead of just the trailing one.

### Consequences

Two or more consecutive `"none"` events at the tail (the model repeatedly failing to follow
protocol) show only the most recent one plus `NUDGE_MESSAGE`; earlier ones in that run are invisible
to the model (still in raw history). `select_recent_events` needs no `"none"`-awareness at all,
keeping it a pure pairs-only walk.

---

## DEC-027: `Event.id` is a monotonic counter owned by `agent.py`'s `run()`, not derived from list length

Status: Accepted
Phase: 1
Date: 2026-09-22

### Decision

`run()` keeps a single `int` counter (`next_event_id`, starting at 0, matching design §28's own
pseudocode), shared across both `AssistantActionEvent` and `ObservationEvent` — incremented by one
after *every* event append, regardless of type. The counter value is passed explicitly into the
event constructor / `record_observation` at creation time; no `context.py` function derives `id`
from `len(raw_events)` or any other property of the list.

### Rationale

A goldfish test of this phase spec (2026-09-22) found `Event.id` unassigned: `context.py`'s
functions are specified as stateless, and `record_observation(shell_result, turn)`'s signature has
no `id` parameter. `len(raw_events)` was considered (and briefly preferred) as requiring no extra
state, but it is only collision-free as long as `raw_events` never shrinks or reorders. A
`len`-derived id is recomputed fresh at each append from current list length; if any future phase
adds editing or deletion of raw events (explicitly raised as a motivating case: human-in-the-loop
review/redaction of turns), a new event created after a deletion could be assigned an id already
held by an existing, still-present event, since the list's length no longer reflects the total
count of events ever created. A counter, once assigned, is never recomputed and stays a stable
identity independent of later list mutations — the same reason a database uses an auto-increment
primary key instead of a row's current position.

### Alternatives Considered

1. Derive `id` from `len(raw_events)` at append time, requiring `record_observation` to also accept
   `raw_events` so it can compute this.

### Why Rejected

1 is only safe under an append-only-forever assumption. It is not needed for Phase 1 itself (raw
history is append-only this phase per DEC-003), but it silently creates an id-collision hazard for
whichever future phase first adds any form of raw-event editing or removal — exactly the scenario
that prompted this decision. The counter costs one extra local variable and has no such hazard
under any future list mutation.

### Consequences

`agent.py`'s `run()` gains a `next_event_id` local, mirroring `messages`/`raw_events` as loop-owned
state. `record_observation`'s signature is unchanged in shape (still receives what it needs to
build the event) but now also receives the pre-incremented `id` value from the caller, same as the
action-event constructor does.

---

## DEC-028: `canonical_content` is `""` for `action_kind="none"` events, and is never read for them

Status: Accepted
Phase: 1
Date: 2026-09-22

### Decision

`canonicalize_action` returns `""` for `kind == "none"`, matching design §7's own fallback branch.
Per DEC-026, `build_active_context`'s trailing-nudge display always shows `raw_response` for a
`"none"` event (never `canonical_content`, regardless of `AGENT_CANONICALIZE`), so the field is
populated for shape-consistency with the dataclass but is dead — never read — for this event kind
in Phase 1.

### Rationale

A goldfish test of this phase spec (2026-09-22) found no stated value for `canonical_content` on a
`"none"`-kind event, despite DEC-022 keeping it as a required field on every `AssistantActionEvent`.
Once DEC-026 settled that the trailing nudge display always uses `raw_response`, the field's value
for this event kind stopped being observable behavior and became a pure implementation detail —
`""` was chosen only because it already exists as design's own fallback, avoiding inventing a new
convention.

### Alternatives Considered

1. Store `raw_response` in `canonical_content` too for `"none"` events, so the field is never empty.

### Why Rejected

1 was rejected only for consistency, not correctness — nothing in Phase 1 reads
`canonical_content` for a `"none"` event either way, so duplicating `raw_response` into it would be
harmless but pointless.

### Consequences

None beyond documentation — this closes an otherwise-unspecified field value with no behavioral
effect this phase.

---

## DEC-029: `ShellResult`/`ObservationEvent` field values when `did_not_complete=True`

Status: Accepted
Phase: 1
Date: 2026-09-22

### Decision

`ShellResult.exit_code` is typed `int | None` and is `None` when `did_not_complete` is `True`. In
that same branch: `stdout = ""`, `stderr = ""`, `original_stdout_chars = 0`,
`original_stderr_chars = 0`, `truncated = False`. `ObservationEvent` carries these same values
through unchanged, per DEC-021's "carried straight through."

### Rationale

A goldfish test of this phase spec (2026-09-22) found six of `ShellResult`'s nine fields
unspecified for the `did_not_complete=True` branch (`environment.exec` raised before producing a
result) — DEC-021 only pins down `did_not_complete` and `error`. `exit_code`'s type wasn't stated
either. `None` is the only representation of "no exit code exists" that can't be silently misread
as a real (failing) exit code by code that omits the `did_not_complete` check first — a sentinel
int (e.g. `-1`) is indistinguishable from a genuine exit code to any such comparison, and this
field matters downstream: the handoff ledger names Phase 4's failure extractor as a reader of it.
The other fields' values follow directly from "no output was ever captured": empty strings, zero
counts, no truncation.

### Alternatives Considered

1. `exit_code: int = -1` (or another sentinel value), keeping the field non-`Optional`.

### Why Rejected

1 keeps a simpler type but reintroduces the silent-misread risk above: a consumer that forgets to
check `did_not_complete` first reads `-1` as an ordinary failing exit code rather than "no command
ever ran." `None` forces that case to be visible — an unchecked `None` where an `int` was expected
is either a type-checker error or a runtime error, whereas a wrong sentinel read as real data fails
silently.

### Consequences

`ObservationEvent.exit_code` is `int | None`; any later phase reading it (Phase 4's failure
extractor, per the handoff ledger) must handle `None` explicitly rather than assuming an `int` is
always present. `tools.run_shell`'s docstring documents the `None` case alongside
`did_not_complete`.

---

## DEC-030: `record_observation` takes `event_id` as an explicit third parameter

Status: Accepted
Phase: 1
Date: 2026-09-22

### Decision

`record_observation`'s signature is `record_observation(shell_result, turn, event_id) ->
ObservationEvent`. `agent.py`'s `run()` loop passes the current value of its `next_event_id`
counter (DEC-027) into this third parameter at the call site, then increments the counter — the
same treatment `next_event_id` already gets for `AssistantActionEvent`'s constructor.

### Rationale

A third goldfish test of this phase spec (2026-09-22) found DEC-025 and DEC-027 in direct conflict
over this same function: DEC-025 pinned `record_observation(shell_result, turn)` at two parameters
("signature unchanged ... rather than taking a third parameter"), while DEC-027, accepted
immediately afterward, requires that "the counter value is passed explicitly into the event
constructor / `record_observation` at creation time" — which needs a parameter DEC-025's signature
has no room for. DEC-025 was correct when written; it predates DEC-027, which introduced the
id-passing requirement and was never checked against DEC-025's literal signature afterward.
`ObservationEvent.id` is a required base field (DEC-022) with exactly one constructor
(`record_observation`), so the id has to arrive as an argument to it — there is no other place to
set it, and dataclasses are not specified as mutable-after-construction anywhere in this plan.

### Alternatives Considered

1. Keep `record_observation(shell_result, turn)` at two parameters; have the caller take the
   `ObservationEvent` `record_observation` returns and set `.id` on it afterward, or give
   `context.py` a second, internal counter so no id needs to cross the function boundary at all.

### Why Rejected

Setting `.id` after construction needs `ObservationEvent` to be mutable for a single field nothing
else needs mutated, and produces an object that is briefly invalid (no id) between construction and
the fixup — a state worth avoiding for no gain over just passing the id in. A second,
`context.py`-internal counter duplicates id ownership across two places instead of the single owner
DEC-027 already decided on (`agent.py`'s `next_event_id`, shared across both event types
specifically to keep ids assigned from one sequence) — reintroducing exactly the dual-counter
collision risk DEC-027 was written to avoid.

### Consequences

The `context.py` module-layout bullet in `phases/01-history-separation.md`'s Scope section is
corrected to `record_observation(shell_result, turn, event_id)`, citing both DEC-025 (for
`command`) and DEC-030 (for `event_id`). No other Phase 1 symbol changes. `record_observation`'s
docstring should say which positional argument is which, since `turn` and `event_id` are both
plain `int`s and swapping them at a call site would fail silently (no type error) rather than
loudly.

---

## DEC-031: `context.metadata` is rebuilt after every raw-history mutation, not once per turn

Status: Accepted
Phase: 1
Date: 2026-09-22

### Decision

`agent.py`'s `run()` loop calls a local `sync_metadata()` closure (which rebuilds the whole
`context.metadata` dict, including a fresh `[dataclasses.asdict(e) for e in raw_events]`) after
*every* mutation of `raw_events`, `finished`, or the telemetry list within a turn — up to four
times per turn (after the LLM call, after the action event is appended, after `finished` is set on
a `"done"` action, and after the observation event is appended) — rather than once per turn as the
pre-Phase-1 baseline did.

### Rationale

The baseline wrote `context.metadata["messages"] = messages` once per turn and relied on `messages`
being a shared mutable reference: later `messages.append(...)` calls that same turn were reflected
automatically, with no second assignment, which is why one write per turn was already safe there
(recorded in the pre-Phase-1 `agent/CLAUDE.md`: "`messages` is stored by reference, so later appends
show up automatically"). Phase 1's `context.metadata["messages"]` is instead built by serializing
`raw_events` into fresh dicts (`dataclasses.asdict`) — a value, not a reference to `raw_events`
itself — so a single early-in-turn write would go stale the moment `raw_events` gets another event
appended later that same turn. `run_shell` (awaiting `environment.exec`) is exactly the kind of
long, hang-prone step most likely to be mid-execution when Harbor's overall per-task timeout fires,
so leaving its resulting `ObservationEvent` unrecorded in `context.metadata` until a write that never
comes would reintroduce the exact partial-progress-loss failure mode the "update every turn"
invariant exists to prevent.

### Alternatives Considered

1. Keep a single `context.metadata` write per turn, placed after the last event of the turn is
   appended (i.e., after the observation, or after the action event for `"none"`/`"done"` turns).
2. Make `raw_events` itself the value stored at `context.metadata["messages"]` (skip serialization),
   restoring the by-reference trick.

### Why Rejected

1 reintroduces a real gap: if the process is killed while `run_shell` is still awaiting
`environment.exec` (the single most timeout-prone line in the loop), `context.metadata` would still
only reflect the state as of the *start* of that turn, discarding this turn's assistant action too
— not just wiping the pending observation. 2 was rejected because DEC-012 requires
`context.metadata["messages"]` to hold serialized (JSON-safe) event data, not live dataclass
instances Harbor doesn't know how to write to `result.json`.

### Consequences

`sync_metadata()` re-serializes the entire `raw_events` list on every call, which is O(n) in the
number of events so far and is called a small constant number of extra times per turn; this is
cheap (dict/list construction, no I/O) at the event counts a 100-turn task produces and was not
judged worth optimizing this phase. A later phase that makes serialization non-trivial (e.g. a much
larger per-event payload) should revisit this rather than assume the extra calls stay free.

---

## DEC-032: `context.metadata` gains `system_prompt`/`instruction` keys, outside `"messages"`

Status: Accepted
Phase: 1
Date: 2026-09-22

### Decision

`agent.py` writes `context.metadata["system_prompt"]` (the constant `prompts.SYSTEM_PROMPT`) and
`context.metadata["instruction"]` (the task instruction string `run()` receives) every turn,
alongside `"turns"`/`"finished"`/`"messages"`/`"telemetry"`. Per DEC-012, `"messages"` itself stays
exactly the serialized raw event history — only `AssistantActionEvent`/`ObservationEvent` entries,
nothing else.

### Rationale

DEC-012 scopes `"messages"` to raw history, and raw history has no event for the system prompt or
task instruction — `build_active_context` reassembles them fresh from `run()`'s own arguments every
turn rather than storing them as events (they're static for the whole run, not something that
happens at a turn). Before Phase 1, `scripts/build_dashboard.py` got both for free because they were
`messages[0]`/`messages[1]` in the OpenAI-format list; under DEC-012's raw-event-only `"messages"`,
that information would disappear from every future `result.json` with no replacement, degrading the
dashboard (and any other future reader of `context.metadata`) from "shows the whole audit trail" to
"shows the whole audit trail except what the task was" — a real loss of debugging capability for a
feature whose stated purpose is a complete audit record (DEC-003), not a redefinition of what
"complete" means. Checking `result.json`'s other top-level fields (`config.task`, etc.) confirmed
the literal instruction text isn't recorded anywhere else Harbor writes.

### Alternatives Considered

1. Accept the loss: `build_dashboard.py` (and any other consumer) simply cannot show the task
   instruction or system prompt for Phase-1-and-later runs.
2. Have `build_dashboard.py` hardcode/mirror the current `SYSTEM_PROMPT` text as a constant (as it
   already does for `NUDGE_MESSAGE`), and drop instruction display entirely.

### Why Rejected

1 was rejected as an unforced, unrequested regression — nothing in the phase spec or its decisions
says the task instruction should stop being visible, and DEC-019's own goal for the dashboard patch
is to "keep rendering a transcript," which a transcript with no visible task instruction only
nominally satisfies. 2 could work for `SYSTEM_PROMPT` (a fixed constant, like `NUDGE_MESSAGE`) but
not for `instruction`, which is per-task data with no fixed value to mirror.

### Consequences

`context.metadata` has two more static (per-run, not per-turn-varying) keys beyond what DEC-012 and
DEC-024 specify. This is additive only — it does not change the definition or contents of
`"messages"`, so DEC-012's audit-record guarantee for raw history is unaffected. Any later phase
adding its own static, whole-run metadata should follow the same pattern (a new top-level key) rather
than folding it into `"messages"`.

---

## DEC-033: Gate G1's regression on long-running tasks is accepted, not fixed, this phase

Status: Accepted
Phase: 1 (binds Phase 4/5 follow-up)
Date: 2026-09-22

### Decision

Gate G1 (two harbor runs, `jobs/phase1-canon-on` and `jobs/phase1-canon-off`, same settings as the
Phase 0 baseline) found that `build-cython-ext` and `fix-code-vulnerability` — 3/3-stable in the
baseline, finishing in 25–87 turns — regress to `finished=False` in both `AGENT_CANONICALIZE`
variants, running to the 100-turn or 900s cap without completing. Full numbers and root-cause
investigation are recorded in `handoff.md`'s *Gate G1 results*. Phase 1 ships with this regression
as a known, documented limitation. `AGENT_RECENT_WINDOW_PAIRS` is left at its default (6) — not
tuned — and no further confirmation re-run was done this phase. `roadmap.md` keeps Phase 1 at
`implementing`, not `completed`, pending this being resolved or explicitly accepted as shippable at
submission time.

### Rationale

Root-cause investigation (turn counts, wall-clock time, and transcript tails compared directly
against the same two tasks' baseline runs) points at DEC-014's own predicted, accepted gap: the
fixed 6-pair recent window drops early discoveries on tasks needing many turns, and the agent
re-explores/re-verifies instead of converging, rather than any implementation defect specific to
this phase's code. Per-turn wall-clock latency did not get worse (if anything, slightly better,
consistent with sending less context per request) — the trials simply needed far more turns to reach
the same conclusion. This is precisely the failure mode Phase 4 (deterministic task state) and Phase
5/the retrieval backlog (semantic state, compaction, retrieval of older evidence) exist to fix per
the roadmap's own structure (`roadmap.md`'s Gate G2 already asks "do runs still fail... because of
context growth or forgotten details"). Spending Phase 1's own measurement budget re-tuning a window
size or re-running for confirmation would be treating a gap the plan already named and scoped a later
phase to fix as if it were an open question, when the real content of the fix (giving the model a way
to retain or retrieve early findings without keeping the whole transcript) doesn't exist until then.

### Alternatives Considered

1. Increase `AGENT_RECENT_WINDOW_PAIRS` (e.g. to 12–15) and re-run both variants (~60 more minutes)
   to see if a larger window closes the gap.
2. Re-run `canon-on` and `canon-off` once more, unchanged, purely to satisfy the noise rule's
   "re-run once to rule out a one-off" before concluding anything.
3. Treat this as blocking: hold Phase 1 in `implementing` and refuse to let Phase 2/3 start until
   the regression is actually fixed (not just documented).

### Why Rejected

1 is a band-aid that doesn't fix the underlying problem (any fixed window eventually loses
information on a long-enough task) and costs real measurement time for a result whose interpretation
would still be provisional — a task that passes with a window of 15 doesn't prove the mechanism is
sound, only that this particular 10-task sample didn't need more than that. 2 was judged unnecessary
given the corroboration already in hand: the same two tasks failed identically (never finishing, same
exploratory-not-looping failure shape) across two independent variants against a 3/3-stable baseline
— a third run of an unchanged config was judged unlikely to change the conclusion enough to justify
another ~60 minutes. 3 conflicts with `roadmap.md`'s own phase-ordering rationale (DEC-004, DEC-006):
Phases 2 and 3 are independent of the state/retrieval work that would actually fix this, and blocking
them on a fix that belongs in Phase 4/5 anyway delays independent, lower-risk work behind a gap the
plan already scoped elsewhere.

### Consequences

- `roadmap.md`'s Phase 1 row stays `implementing`, not `completed`, with this decision linked.
- Phase 4 and Phase 5/backlog work should treat `build-cython-ext` and `fix-code-vulnerability` as a
  concrete regression test (re-run under the same settings, check `finished=True` in a turn count
  comparable to the 25–87-turn baseline), not just re-run the aggregate 10-task protocol and check
  the overall pass rate — this phase's own numbers show the aggregate rate can look unchanged while
  individual tasks silently regress.
- `AGENT_RECENT_WINDOW_PAIRS` remains an untried lever (still just the design.md-suggested default)
  if a future phase wants a cheap interim mitigation before task state/retrieval are ready.
- Before final submission, the owner needs to explicitly decide whether this regression is acceptable
  to ship if Phase 4/5 aren't finished in time — this decision defers that call, it doesn't make it.

---

## DEC-034: `AGENT_CANONICALIZE` default-on (DEC-018) is confirmed by Gate G1, not reopened

Status: Accepted
Phase: 1
Date: 2026-09-22

### Decision

Gate G1's data confirms DEC-018's default: `canon-on` beat `canon-off` on both axes measured —
completion rate (4/10 vs. 2/10, though `canon-on`'s 4/10 has its own churn, see DEC-033) and total
tokens (1,807,782 vs. 2,879,681, `canon-on` using ~37% fewer). `AGENT_CANONICALIZE` stays default-on;
no code or default change.

### Rationale

DEC-005's own consequence commits to shipping canonicalization off only if it measures as harmful.
It didn't — it measured as strictly better on the two axes Gate G1 tracks. The two tasks that
flipped to pass only under `canon-on` (`configure-git-webserver`, `regex-log`) are a secondary,
weaker signal in the same direction (not required to reach this decision, since the primary
completion-rate/token comparison already favors `canon-on` on its own).

### Alternatives Considered

1. Reopen DEC-018 given `canon-on`'s own regressions (`build-cython-ext`, `fix-code-vulnerability`).

### Why Rejected

Those two regressions occurred identically under `canon-off` too (see DEC-033), so they are not
evidence against canonicalization specifically — they're evidence against the window size, which
both variants share. Weighing canonicalization on its own two isolated axes (the entire point of
DEC-005's flag existing) shows no case for turning it off.

### Consequences

None beyond confirmation — this closes the "should Gate G1 change `AGENT_CANONICALIZE`'s default"
question without a code change. The regression DEC-033 tracks is unaffected by this decision, since
it is not canonicalization-specific.
