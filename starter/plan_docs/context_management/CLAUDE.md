# starter/plan_docs/context_management/

## Purpose
Planning docs for the **Context Management and History Compaction** feature: stop resending the
agent's full transcript every turn by separating an append-only raw history from a bounded,
deliberately built active context. Docs only — no source lives here. Each phase runs in its own
fresh session, so everything a session needs must come from the files below plus the code.

## Loaded into every session (imports)
The four files below are pulled in automatically whenever this file loads.

@roadmap.md
@decisions.md
@handoff.md
@../../agent/CLAUDE.md

Deliberately **not** imported: `design.md` (~12K tokens), the phase specs, and the agent source.
Read those on demand as the protocol below says.

## Contents
- `roadmap.md` — phase list, dependencies, gates, and status (`proposed | discussing | ready | implementing | completed`). **The only place phase status is tracked.**
- `decisions.md` — append-only log of accepted decisions (`DEC-NNN`). Check it before re-opening a settled question.
- `handoff.md` — ledger of what exists in the code, what later phases must reuse, and notes passed forward. Read its interface ledger before writing any helper.
- `design.md` — the full target architecture, invariants, and definition of done (§ numbered). **Not an implementation request.**
- `phases/00-…05-*.md` — one spec per phase (Phase 5 is a conditional stub).

## Starting a session
This file loads when a file in this directory is read, not at launch. Begin every session with:
"Work on Phase N (issue #M). Start by reading `starter/plan_docs/context_management/phases/0N-*.md`."
Then, before writing anything:
1. State the phase and its roadmap status. Predecessors must be `completed` (gates passed for Phase 5); if not, stop and say so.
2. Decide the session type from the status. `proposed` / `discussing` → **refine the spec, no code** (use `design-discussion` / `write-spec`). `ready` / `implementing` → **implement**. `completed` → stop.
3. Read the phase spec and only the `design.md` sections it cites.
4. Read the agent source: every file in `starter/agent/` and every file the handoff *Code map* lists. The source is the truth about what earlier phases built.
5. Before any code, report which existing symbols you will reuse (from the ledger and the source) and what, if anything, is genuinely new.

## Working rules
- Implement **only** a phase whose status is `ready`. Never implement a later phase early, and never treat `design.md` as one big task. Phase 5 is conditional on gate G2, and retrieval is a backlog item behind G3 (both in `roadmap.md`): leave them as stubs and do not spend discussion time on them until the gate passes.
- **Reuse before create.** Before adding a function, class or constant, check the handoff ledger and grep `starter/agent/`. If something fits, use or extend it. Never build a parallel version (a second builder, classifier, state type, or shell runner). Organise code by responsibility, not by phase. Changing an existing symbol's signature means updating its callers and its ledger row in the same change. If you find a defect in an earlier phase's code, fix it in place, note it under *Deviations* in `handoff.md`, and do not work around it in new code.
- I will use the grill me skills for further discussions and clarifications and I would like for you to ask me one question at a time and not list all questions at once. 
- Behavior-changing pieces (canonicalization, nudges, completion guard) must be individually switchable and measured on/off; a change that lowers completion rate is not done, whatever it does to tokens. **One recorded exception so far:** Phase 1's Gate G1 found a completion-rate regression on long-running tasks, root-caused to the recent-window gap the roadmap already scoped Phase 4/5 to fix, and the owner explicitly chose to accept and document it rather than block on a fix here (DEC-033). Treat this rule as still binding by default — DEC-033 is a one-time, owner-approved exception with a specific rationale (the real fix doesn't exist until a later phase), not a precedent for waving off regressions generally.
- The phase spec says **what to build**; `decisions.md` says **why, and what was rejected**. A spec references `DEC-NNN` instead of restating it.
- The repo's no-code-during-design rule applies to refine sessions.

## Finishing a session
A phase is not done until the next session can pick up without you. In the same change:
1. Tests pass, and for behavior-affecting phases the measurement protocol has been re-run with the numbers posted in the phase's issue.
2. `handoff.md`: flip ledger rows to `implemented` with their location, add any new shared helper as a row, fill the phase's *Code map* entry, and write *Notes for the next phase* and any *Deviations*. Verify every name with `grep`.
3. Update `starter/agent/CLAUDE.md` wherever it is now false (it is imported into every session, so a stale claim misleads the next one). Update `starter/scripts/CLAUDE.md` if scripts changed.
4. Record any real choice as the next `DEC-NNN` in `decisions.md` and reference it from the spec.
5. Update the phase's status in `roadmap.md` and comment on its GitHub issue.

## How it fits in
Code changes land in `starter/agent/` (`agent.py` loop, `tools.py`, `prompts.py`, `llm.py`); see `starter/agent/CLAUDE.md`. Measurement uses `starter/scripts/` and Harbor's `jobs/`. Each phase has a GitHub issue under the milestone **Context Management and History Compaction**; issues link here, not the other way round.

## Gotchas
- Competition rules bind every phase: no task-specific hardcoding, approved open-weight models only (this includes any model used for compaction), endpoint config only via `.env`/`.env.op`, and the agent never touches the host filesystem. That is all you need from the competition docs; the root `CLAUDE.md` has the rest.
- Scoring is `TB_score − 0.01 × (total_tokens / 1M)`, and compaction calls count as tokens. Success is completion rate first, tokens second (`design.md` §3).
- `context.metadata` must stay updated every turn (see `starter/agent/CLAUDE.md`); raw history must remain the thing that gets written there.
- Phase numbers here (0–5) do **not** match the "Phase 1–7" rollout list in `design.md` §31; `roadmap.md` has the mapping. Phases are ordered by dependence on an LLM call (DEC-004): 0–4 are deterministic and built in order; 5 and the retrieval backlog item are gated bets. A phase boundary is a point where we measure and can stop (DEC-007).
- `design.md` pseudocode names are illustrative and differ from the code in places (e.g. `Literal["shell","complete","invalid"]` vs. the code's `"shell"|"done"|"none"`). The ledger in `handoff.md` wins over the design's names.
- The first time imports are used in a project, Claude Code may ask you to approve them. If they are declined, the four files above do not load.
