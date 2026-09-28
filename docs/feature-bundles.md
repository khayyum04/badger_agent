# Feature bundles A and B

Status: **agreed in planning sessions on 2026-09-25 and 2026-09-28**. Items marked *(proposed)* were
recommended but not yet explicitly confirmed.

Evidence for everything below: [`starter/docs/research/full-sweep-analysis.md`](../starter/docs/research/full-sweep-analysis.md)
(the full 89-task sweep `full-89-0924`). Read its §2 first. It explains the root cause both
bundles are working around.

## Who owns what

| Bundle | Owner | Owns these files | Must not edit |
|---|---|---|---|
| **A — History & output** | khayyum04 | `starter/agent/agent.py`, `starter/agent/llm.py`, new `starter/agent/history.py` (or similar) | `prompts.py` sections owned by B |
| **B — Behavior** | MukhHz | `starter/agent/prompts.py`, new `starter/agent/behavior.py`; also runs all evaluations on the Victus | `agent.py` / `llm.py` until A has merged |

A starts from a blank slate. The earlier Phase 1 / context-management attempt (PR #9, the closed
issues #1–6) is **not** a starting point.

## Merge order

1. Both branch from current `main`: A on `feature/history-cleanup`, B on `feature/behavior`.
2. **B, part 1** (prompt-only) can merge whenever it passes the dev-subset rule. Khayyum reviews
   and merges it.
3. **A** merges when it passes the dev-subset rule. Mukhriz reviews and merges it.
4. **B, part 2** (the `agent.py` changes) starts **only after A is on `main`**: `git pull origin
   main` into `feature/behavior`, then build on A's loop. Khayyum reviews and merges it.
5. After both are in, rerun all 89 tasks for the new baseline.

## Dev subset and the merge rule

**List:** [`starter/eval/dev_subset.txt`](../starter/eval/dev_subset.txt): 30 tasks, stratified by
the baseline's failure modes. It holds all 6 context overflows, all 10 wrong finishes, 6 of the 31
timeouts, and 8 passes for catching regressions (4 short, 4 long). Both of us use this same list.

**Run it** (from `starter/`, on the hosted endpoint):

```bash
op run --env-file=.env.op -- env SUBSET_FILE=eval/dev_subset.txt ./scripts/run_subset.sh \
  --environment-build-timeout-multiplier 6 --job-name <name>
```

`N_CONCURRENT` defaults to 2 (`-n 2`, two tasks at once). Keep it there: 3 crashed the Victus, and
the endpoint is shared.

**Cost:** about 42.9M tokens and about 4.2h wall-clock per run, most of it (25.9M) the 6 overflow
tasks. Khayyum may iterate on smaller slices on his own machine, but **every merge decision uses
the full 30.**

**Baseline:** run #1 is the combined 89-task baseline's result for each of these 30 tasks. Run #2
is one fresh run of unmodified `main` (MukhHz, on the Victus). A task that flips between #1 and #2
is noise, and its flips don't count for or against a branch.

**Merge rule:** on the dev subset, the leaderboard score (pass rate − 0.01 × tokens/1M) must not
drop, **and** the bundle's own targets below must be met.

---

## Bundle A — History & output (khayyum04)

### Problem, in numbers

- 86% of all transcript text is the model's own replies, and every one is re-sent every turn.
  Input tokens: 87.5M; output: 5.7M. Token penalty: **−0.93**, larger than the whole TB score.
- 19% of replies (457 / 2,420) are >20k chars. The model hit `LLM_MAX_TOKENS` mid-thought,
  `content` came back empty, and `llm.py:148` saved the truncated `reasoning_content` as the
  reply.
- 6 tasks hit the 250k context window (turns 40–56).
- 238 turns (10%) were wasted on the "no action" nudge. 205 of them were prose-only replies,
  usually truncated thoughts.

### Where it lives

- `agent.py` loop: `messages.append({"role": "assistant", "content": text})` stores the full
  reply, and `llm.chat(messages)` sends the whole list every turn.
- `llm.py:137–148`: the empty-`content` → `reasoning_content` fallback.

### What to build

1. **Keep a slim history, not the full replies.** Separate "what we log" (full transcript in
   `context.metadata`, for the dashboard) from "what we send" (what the model sees). Past turns
   are sent as the command that was run plus its output. Old reasoning text is dropped or cut to
   a short line.
2. **Handle cut-off replies.** When `content` is empty and only `reasoning_content` exists:
   - pull out a bash block if the thought contains one, and store only that;
   - if there's none, don't store the thought. Re-ask once with a short "reply with the next
     command only" message, and don't keep that exchange in the sent history either.
3. **Cap the total size of what's sent**, with a safety margin under the 250k window, so a task
   can never hit the context-overflow error again.
4. **Experiment, configured in `.env`:** try cutting the thinking itself, e.g. a lower or higher
   `LLM_MAX_TOKENS`, or a server-side thinking switch if the endpoint supports one. Any such knob
   must be an env var, not a code constant (portability rule in the root `CLAUDE.md`).

### Success metric (dev subset)

- Total tokens down **≥ 40%** vs baseline *(proposed threshold)*.
- **0** context overflows on `video-processing` / `regex-chess`.
- Nudge rate clearly down.
- Pass count not lower than baseline, **especially on the long regression tasks** (`reshard-c4-data`,
  `mcmc-sampling-stan`).

### What could go wrong

- **Dropping old reasoning loses what the model figured out early on.** A long task can then
  re-explore instead of making progress. That is exactly the kind of regression a shorter history
  causes, and short tasks won't show it. Watch the long tasks and the turn counts, not just the
  pass count.
- **Commands alone may be too thin.** Some reasoning, like "the bug is in X because Y", may be
  worth keeping as one line per turn. Decide based on transcripts, not a guess.
- **The dashboard reads `context.metadata["messages"]`.** Keep the full transcript there, or
  `build_dashboard.py` breaks. It also mirrors `NUDGE_MESSAGE`/`CODE_BLOCK_RE`, see
  `starter/scripts/CLAUDE.md`.
- **Re-asking after a cut-off reply costs another model call.** Cap it at one retry per turn.

---

## Bundle B — Behavior (MukhHz)

### Problem, in numbers

- **27 tasks hit their time limit** (26 failed + `regex-log`, which had actually solved it but
  never said TASK_COMPLETE). Limits vary per task: 750–3600s, most 900s. Median turn takes 24s
  (p90 50s), so most tasks get only ~17–30 turns.
- **6 tasks said TASK_COMPLETE and failed the tests:** `build-pov-ray`, `configure-git-webserver`,
  `filter-js-from-html`, `llm-inference-batching-scheduler`, `qemu-alpine-ssh`, `query-optimize`.
- 2 tasks hit the 100-turn cap: `compile-compcert`, `install-windows-3.11`.
- 33 nudges came from ```` ```python ```` (or other non-bash) code blocks.

**Important:** `SYSTEM_PROMPT` *already* says "VERIFY before finishing … run any available tests"
(strategy step 5) and "prefer fast, targeted commands" (rule 5). Those 6 wrong finishes and 27
timeouts happened *with* that text in the prompt. So more of the same wording probably won't
fix it on its own. Part 2's loop-level changes are where the real effect is likely to come from.

### Part 1 — prompt-only (`prompts.py`), start now

1. **Split `SYSTEM_PROMPT` into named sections** (e.g. `TIME_SECTION`, `VERIFY_SECTION`) joined in
   one place, so later edits touch separate lines.
2. **Time discipline:** tell the model it has a hard wall-clock limit. Long builds/installs should
   run in the background with output going to a log it checks later. Don't re-run slow commands to
   look at their output again. Once the task looks done, finish.
3. **Concrete verification:** replace the generic line with specific steps. Re-read the
   instruction and list each requirement, check each one with a command (exact file paths, output
   format, running the program or its tests), and only then finish.
4. **Code-block rule:** "the only accepted block is ```` ```bash ````; to run Python, use
   `python3 - <<'EOF'` inside it." Also update `NUDGE_MESSAGE` to say this when it fires. (Keep
   `build_dashboard.py`'s copy of `NUDGE_MESSAGE` in sync.)

Measure Part 1 alone on the dev subset. It's cheap, and it tells us how much prompting can do
before any code changes.

### Part 2 — loop changes (`behavior.py` + a few call lines in `agent.py`), after A merges

1. **Time budget in every turn:** append "N min elapsed" to each observation.
   - **Checked:** Harbor does **not** pass the task's time limit to the agent. `run()` gets only
     the instruction, the environment and the context; the limit lives in the task's `task.toml`.
     Limits seen: 750–3600s, most often 900s.
   - **Decided:** show elapsed time, plus a soft warning at a threshold set in `.env` (default
     ~12 min): "if your solution already works, finish now". Never a hard "stop", because a
     3600s task must not quit early. Don't read Harbor's internal cache files for the real limit.
2. **Completion gate:** the first time the model says TASK_COMPLETE, don't end the task right
   away. Reply once with "list each requirement from the instruction and show the command that
   proves it". Accept the second TASK_COMPLETE. Skip the gate when little time is left.
3. **Stuck detection (feature #5, if time allows):** if the same command (or the same error) repeats
   3 times, inject "this isn't working, try a different approach".
4. **`python` blocks (feature #6):** alternatively, accept ```` ```python ```` blocks in
   `tools.parse_action()` and run them via `python3 - <<'EOF'`. This is a `tools.py` change, so
   coordinate with A.

### Success metric (dev subset), agreed

- Wrong finishes: **≥ 3 of the 10** now pass.
- Timeouts: **≥ 2 of the 6** finish in time, and `regex-log` actually says TASK_COMPLETE.
- The 8 regression passes: none lost (except tasks that flipped between baseline runs #1 and #2).
- Tokens: **≤ +10%**. The completion gate adds turns, so keep it lean.

### What could go wrong

- **The completion gate can make things worse:** extra turns on tasks that were already right,
  and a task that finishes right at its time limit could be pushed past it. That's why it's
  skipped when time is short and fires only once.
- **Time messages cost tokens every turn.** Keep them to one short line.
- **Without the real per-task time limit, the time budget is a guess.** A 3600s task told "900s"
  will rush and give up too early. Solve the open question in Part 2, step 1 before building on it.
- **Prompt-only changes may not move the numbers** (see the "Important" note above). If Part 1
  shows no effect, don't keep polishing wording. Move to Part 2.

---

## Not in either bundle (yet)

- **Infra:** rerun the 21 never-started tasks (MukhHz, on the Victus, after freeing disk). This is
  not agent work.
- **Model approval:** the endpoint reports `qwen3.8-27b`, but the approved list names Qwen3.6-27B.
  Confirm with the organizers before any submission run.
- **Dev-subset script:** done. `run_subset.sh` takes `SUBSET_FILE=...` (see above).
