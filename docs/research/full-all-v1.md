# Full run with every setting on (`full-all-v1`)

All 89 Terminal-Bench 2.0 tasks, model `qwen3.8-27b`, Victus, Nov 4 2026, branch `feat/overrun-recovery`
(commit 43fc6dc):
`AGENT_THINKING_CAP=8192 AGENT_TIME_AWARENESS=on AGENT_SUBMIT_CHECK=on AGENT_NO_BENCHMARK_LOOKUP=on AGENT_OVERRUN_RECOVERY=on`.
Scores use the current rule: `TB - min(0.01, 0.01 × tokens_per_task / 100M)`.

## Result: best run so far

| | `full-mini-v1` | `full-capta-v1` | `full-all-v1` |
|---|---:|---:|---:|
| Passed | 52 (51 honest) | 48 | **56** |
| Leaderboard score | 0.58411 | 0.53919 | **0.62907** |
| Failed by timeout | 23 | 21 | 17 |
| Failed with a submitted (wrong) answer | 6 | 15 | 14 |
| Ended after 5 cut-off replies (`RepeatedFormatError`) | 3 | 3 | **0** |
| Output thrown away in cut-off replies | 26% | 31% | 25% |
| Tokens per task | 1.61M | 1.33M | 1.43M |

13 tasks gained and 5 lost against `full-capta-v1`. Between the two earlier full runs 16 tasks flipped by
chance, so +8 is about two standard deviations: probably real, but not all of it can be credited to one setting.

## What each new setting did

**Overrun recovery.**
- 108 retry notes carried the cut-off thinking forward.
- 20 replies were sent with thinking off: all 20 made a tool call, none had any thinking, and the endpoint
  never rejected the switch.
- No task ended on five cut-offs (3 in each earlier run).
- On the 6 sometimes-pass targets: 4 passed (`feal-linear-cryptanalysis`, `feal-differential-cryptanalysis`,
  `circuit-fibsqrt`, `regex-log`), against about 3.3 expected from their earlier rates.
- The 7 never-pass targets still fail, now mostly on time instead of cut-offs. The 4 controls passed.

**Submit check.**
- 69 tasks got the checklist.
- `polyglot-c-py` passed again (failed 5 of 5 before; 2 of 2 with the check), and `sanitize-git-repo` passed
  for the first time.
- The two lost build tasks were not caused by the check:
  - `build-pmars` unpacked its source in `/tmp`, but the task wanted it in `/app`.
  - `build-pov-ray` was missing an original source file (`file_id.diz`) the test looks for.

**No-benchmark-lookup line.** No command fetched the benchmark's repo or solutions. The keyword hits were task
files that contain the canary string or a `TBENCH` salt.

## Gained / lost vs `full-capta-v1`

- **Gained:** configure-git-webserver, crack-7z-hash, dna-insert, extract-elf (honest this time),
  feal-linear-cryptanalysis, gcode-to-text, largest-eigenval (0 of 4 before), polyglot-c-py, protein-assembly,
  query-optimize, regex-log, sanitize-git-repo, train-fasttext.
- **Lost:** build-pmars, build-pov-ray, nginx-request-logging, password-recovery (timeout),
  schemelike-metacircular-eval (100-step limit).

## Next

- Use this configuration as the new baseline for submissions.
- To attribute the gain: rerun the 26 sometimes-pass tasks once with and once without overrun recovery.
- The remaining failures are mostly timeouts on hard tasks (17), where the model is too slow, not stuck.
