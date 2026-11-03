# Full run with thinking cap + time awareness (`full-capta-v1`)

All 89 Terminal-Bench 2.0 tasks, `AGENT_THINKING_CAP=8192 AGENT_TIME_AWARENESS=on`, model `qwen3.8-27b`,
`-n 2`, Nov 2-3 2026. Compared with `full-mini-v1` (neither setting, Oct 1). Both jobs are local
(`jobs/` is gitignored). Scores use the current rule: `TB - min(0.01, 0.01 × tokens_per_task / 100M)`.

## Result

| | `full-mini-v1` | `full-capta-v1` |
|---|---:|---:|
| Passed | 52 (51 honest, see below) | 48 |
| Leaderboard score | 0.58411 | 0.53919 |
| Failed by timeout | 23 | 21 |
| Failed with a submitted (wrong) answer | 6 | 15 |
| Overruns (`finish_reason=length`) | 79 | 141 |
| Server speed (output tok / agent s) | 69 | 74 |
| Tokens per task | 1.61M | 1.33M |

6 tasks gained, 10 lost. The slow-subset gains (`docs/research/slow-subset-timeouts.md`: timeouts 23 → 9 on
26 tasks) did not carry over: timeouts fell only 23 → 21 on the full benchmark.

## The drop is within run-to-run noise

16 of 89 tasks changed pass/fail between the two full runs (sampling temperature 0.6). With that many flips,
a net −4 is about one standard deviation of chance. This run neither shows that time awareness hurts nor that
it helps. A single full run cannot detect a ±3-task effect.

## Wrong submissions: the agent verified, against its own reading

The wrong submissions went from 6 to 15, but:

- About half of those tasks fail in every run they appear in (`filter-js-from-html`, `mteb-retrieve`,
  `polyglot-c-py`, `qemu-alpine-ssh`, `sam-cell-seg`, `sanitize-git-repo`, `video-processing`). Time
  awareness turned their timeouts into wrong answers, which costs nothing.
- Almost all 15 ran checks before submitting ("ALL SUITES PASS", "FINAL OUTPUT IDENTICAL", "cross-checked
  3990 values, mismatches: 0"). The hidden tests failed them on things the agent didn't read into the task:
  an output format (`sam-cell-seg`), a speed target relative to a reference (`query-optimize`), an edge case
  (`cancel-async-tasks`), the wrong one of two plausible interpretations (`extract-elf`).
- So "verify before submitting" is not missing; the verification is self-referential.

## Failures that repeat every run

| Task | Runs failed | Cause, every time |
|---|---|---|
| `polyglot-c-py` | 5 of 5 (starter + mini) | compiled test binary `cmain` left next to `main.py.c`; the test wants only `main.py.c` |
| `polyglot-rust-c` | `full-mini-v1` | `cmain` and `main` left next to `main.rs` |
| `sanitize-git-repo` | 2 of 2 mini runs | rewrote git history; the test looks up an original commit |

These are fixable with a generic check at submit time: `docs/plans/submit-check.md`.

## Benchmark lookup

`count-dataset-tokens` searched GitHub for `harbor-framework/terminal-bench-2` and listed its files, looking
for this task. It found nothing and computed the answer itself (an honest pass). In `full-mini-v1` the same
move let `extract-elf` copy the official solution, which is why that run's honest score is 51/89. Next runs
should use `AGENT_NO_BENCHMARK_LOOKUP=on`.

## Next

1. Submit check + no-lookup line on `mini_agent/eval/submit_check_subset.txt` (4 targets, 7 controls).
2. Decide time awareness on repeated evidence, not one full run: e.g. the 16 flipped tasks, 2-3 runs per setting.
