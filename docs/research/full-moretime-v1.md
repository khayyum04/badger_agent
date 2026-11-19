# Twice the time on all 89 tasks (`full-moretime-v1`)

Victus, Nov 18-19 2026, branch `feat/output-cap` at `bfa747f`: all defaults plus `AGENT_MAX_TURNS=200` and
`--agent-timeout-multiplier 2` (the organizers confirmed on Nov 18 that the multiplier is allowed). Known time
limit off. Compared with the three plain-defaults runs `full-all-v1`/`v2`/`v3`.

## Result: 61/89, the best so far

| | v1 | v2 | v3 | **2x time** |
|---|---:|---:|---:|---:|
| Passed | 56 | 56 | 57 | **61** |
| Leaderboard score (capped penalty) | 0.62907 | 0.62907 | 0.64029 | **0.68513** |
| Timeouts (AgentTimeoutError) | 17 | 16 | 13 | **8** |
| Failed without timing out | 16 | 19 | 19 | 21 |
| Tokens | 126.9M | 131.5M | 145.4M | 237.5M (237536120) |

- **Outside the baseline spread.** The three baselines are within one task of each other (56-57); this is 4-5 above.
  It is one run, so a second one would confirm it.
- **Timeouts halved** (8 vs 13-17). Some of the tasks that no longer time out now submit a wrong answer (21 vs
  16-19), which is expected: they get to the end instead of being cut off.
- **Passes that needed the extra time:** 4 ran past the task's normal limit (taken from timed-out baseline trials):
  largest-eigenval (24 min, limit 14), regex-chess (63, 59), train-fasttext (119, 59; timed out at 2x but its
  output passed), tune-mjcf (27, 14). That accounts for most of the gain; the rest is the usual task-to-task luck.
- **Gained** (failed in all three baselines): dna-assembly.
- **Lost** (passed in all three): circuit-fibsqrt, financial-document-processor, sqlite-db-truncate, all real
  wrong answers. The last two finished in 33 and 24 model calls, far inside the old limit, so the extra time
  did not cause them.
- **No task hit 200 steps.**
- **Grading:** only qemu-startup and qemu-alpine-ssh (apt 404 for curl, as in every run). No download failures.
- **Tokens:** 1.6x the baseline, from working longer. The penalty is 0.00027, far below one task (0.0112).

## The 24-task probe before it (`probe-moretime-v1`)

Same settings on `eval/timeout_subset.txt` (24 tasks that timed out and failed at least once in v1-v3): 9 passed,
against 6/5/7 for the baselines on the same tasks. The bar set beforehand was "10+ is a real gain, 6-8 is luck",
so the probe alone was only a weak positive; the full run is what shows the gain.

## Output cap (same branch)

In the probe, qemu-alpine-ssh printed a raw ISO (about 1 GB). The model only saw the first and last 5,000
characters, but mini-swe-agent stored the whole output in memory and in the trajectory (`extra.raw_output`),
re-saved every step: a 1.2 GB trajectory. An earlier run had a 1.3 GB cobol-modernization trajectory, likely the same.
`HarborEnvironment.execute()` now keeps the first and last 500K characters of any output over 1,000,000
(`OUTPUT_CAP_CHARS`, `n_capped_outputs` in metadata). In this run it triggered once (sam-cell-seg) and the whole job
archive was 9.4 MB.

## Defaults changed

`step_limit` 200 in `terminal_bench.yaml`, `AGENT_MAX_TURNS=200` in `.env.example`, and the run scripts pass
`--agent-timeout-multiplier ${AGENT_TIMEOUT_MULTIPLIER:-2}`. A local `.env` with `AGENT_MAX_TURNS=100` still
overrides the YAML: update it.

Job: `mini_agent/jobs/full-moretime-v1` (gitignored).
