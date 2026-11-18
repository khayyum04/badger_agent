# Submit review and known time limit

Agreed 2026-11-05 (Mukhriz, with Claude) after `full-all-v1`/`v2` (56/89 each). Branch:
`feat/review-and-time-limit`, from `feat/overrun-recovery`. Both settings default to off, because neither
is cleared with the organizers yet (see Rules).

## Problem

Per run, the failures are about 14-17 timeouts and 14-17 wrong submissions.

- **Wrong submissions:** the agent checks its answer against its own reading of the task, so misreadings
  survive. The submit checklist (`AGENT_SUBMIT_CHECK`) helps only when the agent itself notices the problem.
  In `full-all-v2` it listed the leftover `cmain` file and kept it.
- **Timeouts:** the agent can't see the task's limit (12-60 min). Time awareness says "unknown, maybe 15
  min" and nudges at 10 min on every task. So 30- and 60-minute tasks get rushed, and 15-minute ones get no
  plan for their real budget.

## Technical Plan

1. **`AGENT_SUBMIT_REVIEW=on`.** At the first submit (the submit check's hold), a reviewer runs (`review.py`).
   - It's the same model and endpoint, with a fresh context: it gets only the task text.
   - It may run up to 6 inspection commands (60 s each), without changing anything, then answers
     `UNMET: ...` or `ALL MET`. After 3 minutes (`REVIEW_TIME_BUDGET_SEC`) the next call must give the
     verdict, with at most 2,048 tokens, so the worst case stays near 3-4 minutes.
   - Its verdict replaces the checklist as that submit's output, and the agent's next submit goes through.
   - Its tokens count toward the task's total.
   - Any reviewer error gives a short note instead, so the agent can still submit.
2. **`AGENT_KNOWN_TIME_LIMIT=on`** (only with time awareness on).
   - `BadgerMiniAgent.run()` reads the running Trial's `_agent_timeout_sec` from the call stack. Harbor
     computes it (task limit × multiplier) but passes it only to its oracle agent.
   - The clock then shows `time used: X of Y min`, the nudge comes at 60% of the limit, and prompt rule 4
     says "You have Y minutes in total; a working version within the first third".
   - If the limit can't be found, everything stays as today.

## Rules

Ask the organizers before submitting with either:
1. Is a second, same-model reviewer call before submitting "one system prompt, one agent loop"?
2. May the agent read its time limit from the harness?

Testing them in dev runs is fine.

## Weak spots

- **The review costs time:** typically 2-4 minutes, capped near 3-4 by the time budget, at the moment a task
  is closest to done. Tasks near their
  limit can tip into a timeout.
- **The reviewer can be wrong.** The message tells the agent to ignore findings it disagrees with, and to
  say why.
- **The reviewer could modify files** despite the instruction; nothing enforces read-only. It's told to copy
  anything it runs or compiles to /tmp, since a leftover binary or log in a task directory can fail the task.
- **The time-limit lookup relies on Harbor internals** (the Trial's attribute name and the call stack).
  Pinned at harbor 0.23.0; tested with `asyncio.wait_for` as Harbor uses it. If it breaks, the feature turns
  itself off.
- **A known 60-minute limit may make the agent slower**, not better, on tasks it can't solve anyway.

## Detailed Implementation

- `review.py`: `run_review()` and its prompt constants.
- `harbor_agent.py`:
  - `HarborEnvironment.submit_reviewer`, and `execute(check=False)` for reviewer commands.
  - `HarborSyncedAgent.submit_review()`.
  - `_harbor_agent_timeout_sec()`, `CLOCK_KNOWN_TEMPLATE`, `NUDGE_AT_FRACTION`, `NUDGE_KNOWN_MESSAGE`, and the
    template variable `time_limit_min`.
  - Metadata: `submit_review`, `review_verdict`, `review_commands`, `review_sec`, `time_limit_sec`.
- `terminal_bench.yaml`: the rule 4 variant.
- Tests: `mini_agent/tests/test_review_and_time_limit.py`.

## Measure (A/B, one change per run)

- **A side:** the same tasks in `full-all-v1` and `full-all-v2` (defaults, neither setting). The pass
  counts are in the list files.
- **Review (B):** `mini_agent/eval/review_subset.txt`, the 25 tasks that failed with a wrong answer in
  either run (A: 15 of 50 passes, 30%), with `AGENT_SUBMIT_REVIEW=on`. Read the verdicts too: true findings,
  false alarms, timeouts caused.
- **Time limit (B):** `mini_agent/eval/time_limit_subset.txt`, the 23 tasks that timed out in either run
  (A: 11 of 46, 24%), with `AGENT_KNOWN_TIME_LIMIT=on`.
- **Noise:** 24 of 89 tasks flipped between the two A runs, so only a large gap counts (about +5 tasks of
  25). Anything smaller needs a second B run or a full run.
