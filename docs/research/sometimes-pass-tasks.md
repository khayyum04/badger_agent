# How the sometimes-pass tasks fail (5 full runs)

Runs: `full-mini-v1`, `full-capta-v1`, `full-all-v1`, `full-all-v2`, `full-effort-medium-v1`. 31 tasks passed in
all five runs, 17 in none, and **41 passed sometimes**. Those 41 are the room left with this model: about 72
tasks have passed at least once, against 56 per run now.

## Failures of the 41 sometimes-pass tasks

| | Failures |
|---|---:|
| Timeout | 45 |
| Wrong answer submitted | 44 |
| Step limit (100) | 6 |
| Five broken replies in a row | 3 |
| Context window full | 1 |

## Wrong answers repeat the same hidden test

When these tasks fail with a wrong answer, they mostly fail the **same test every time**: a consistent
misreading, not chance.

| Task | Failed test (times) | What the test caught |
|---|---|---|
| polyglot-c-py | test_fibonacci_polyglot (4) | compiled test binary `cmain` left next to the deliverable |
| sanitize-git-repo | test_no_other_files_changed (3) | git history rewritten; an original commit is gone |
| configure-git-webserver | hello.html test (3) | final state broken: the agent reset the repo / web root after its own tests |
| cancel-async-tasks | test_tasks_cancel_above_max_concurrent (3) | tasks cancelled before starting never run their cleanup |
| query-optimize | runtime vs golden (3) | slower than 1.05× the reference query |
| video-processing | jump analyzer (3-4) | wrong frame detection |
| dna-insert | test_primers (3) | primer doesn't overlap the vector as required |
| mteb-leaderboard | test_data_matches (3) | wrong model picked from the leaderboard |

Two generic patterns:

1. **The agent's own testing spoils the final state.** It leaves build or test files behind (`polyglot-c-py`),
   rewrites history (`sanitize-git-repo`), or resets things after testing (`configure-git-webserver`). The
   submit checklist targets this, but works only when the agent notices.
2. **A requirement in the task text is missed** (cleanup on cancel, speed relative to the reference, overlap
   rules). The agent checks against its own reading.

Both are what the fresh-context reviewer (`AGENT_SUBMIT_REVIEW`, `full-review-v1`) checks: the final state,
against the task text. No new task-independent fix stands out beyond it. The remaining wrong answers are
domain mistakes (`dna-insert`, `mteb-leaderboard`, `video-processing`).

**Timeouts** (45) are spread across many tasks. Shortening the thinking didn't help (`cap4k-v1`,
`full-effort-medium-v1`), so a known time limit (`AGENT_KNOWN_TIME_LIMIT`) or a faster model are the
remaining levers.
