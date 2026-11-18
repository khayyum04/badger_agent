# Change report on all 89 tasks (`full-change-v1`)

Victus, Nov 9 2026, branch `feat/change-report` at `62bc0aa`, all defaults plus `AGENT_CHANGE_REPORT=on`
(`docs/plans/change-report.md`). The A side is `full-all-v1` / `full-all-v2` (56 each, Nov 4).

## Result: no gain, about 54 corrected

| | A: v1 | A: v2 | B: change report |
|---|---:|---:|---:|
| Passed | 56 | 56 | **52** |
| Leaderboard score (capped penalty) | 0.62907 | 0.62907 | 0.58411 |
| Timeouts (AgentTimeoutError) | 17 | 16 | 17 |
| Wrong submissions | 14 | 17 | 18 |
| Tokens | 126.9M | 131.5M | 141.3M |

- **Grading broke on 2 more tasks** (504 downloading Python in the test script): llm-inference-batching-scheduler
  and merge-diff-arc-agi-task, besides the two qemu tasks. Both pass in both A runs, so the corrected estimate
  is **about 54**.
- **Lost** (passed in both A runs): circuit-fibsqrt (step limit), mailman (step limit), feal-linear-cryptanalysis
  (timeout), db-wal-recovery, extract-elf, protein-assembly (wrong answers), and the two grading failures.
- **Gained** (failed in both A runs): none.
- Like the last three experiments (49-51), more wrong submissions than A. See the baseline caveat in
  `full-timelimit-v1.md`.

## Did the report work?

- **It ran everywhere it could:** `change_report` is true on all 89, and 68 tasks reached the first submit and
  got a report. One task reached it without one: custom-memory-heap-crash names `/usr/local/gcc-custom-debug/`,
  which is likely over the 20,000-file cap, so the whole report was off (the task passed anyway).
- **The agent acts on it:** in about 25 tasks the next command deleted leftovers (`__pycache__`, `build/`,
  `.egg-info`, compiled binaries, `.pytest_cache`, editor or tool output). Nearly all of those tasks passed.
- **No loss traces back to it:** none of the three lost wrong answers deleted anything after the report. The
  failures are wrong output (extract-elf found 0% of the values; protein-assembly's gblock) and db-wal-recovery,
  where `main.db` / `main.db-wal` had already been changed before the report (the report listed both as Changed).
- **No lost commits in any task** (`commits_gone` 0 everywhere).

### The four target tasks

| Task | A v1 | A v2 | B | What happened |
|---|---:|---:|---:|---|
| polyglot-c-py | 1 | 0 | **1** | Deleted `cmain` and `__pycache__` after the report. |
| sanitize-git-repo | 1 | 0 | **1** | Deleted `__pycache__`; history intact. |
| polyglot-rust-c | 0 | 0 | 0 | **Deleted `main` and `cmain`, then rebuilt both to verify, and submitted with them** (its own `ls` showed them). Test: "Expected only main.rs, found: main.rs, cmain, main". |
| configure-git-webserver | 1 | 0 | 0 | Report said nothing was created: the agent's work was in `/git` and the web root, which weren't snapshotted (known weak spot). |

## Findings

1. **Clean up, then rebuild, then submit.** The report fires once, at the first submit. After it, the agent
   cleans up but often re-verifies by rebuilding (smoke-change-v3 rebuilt and deleted again; polyglot-rust-c
   rebuilt and stopped). The second submit goes through without another look.
2. **Directories the agent creates are invisible** (configure-git-webserver), as expected.
3. **One big directory named in the task turns the report off for everything** (custom-memory-heap-crash).

## Next

- Not a clear win at 52 (about 54); one sample, inside the run-to-run spread. Leave it default off.
- Idea for (1), not built: at the second submit, compare against the first-submit snapshot, and if files were
  created again, hold once more with only that list. Costs one more snapshot and at most one turn.
- The baseline question from `full-timelimit-v1.md` is now four experiments deep: a plain-defaults
  `full-all-v3` would say whether 52-54 is "no change" or "a small gain on a drifted baseline".
