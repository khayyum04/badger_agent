# Reasoning effort "medium" on all 89 tasks (`full-effort-medium-v1`)

Victus, Nov 6 2026, branch `feat/review-and-time-limit`, all defaults plus `AGENT_REASONING_EFFORT=medium`
(cap 8192). The A side is `full-all-v1` and `full-all-v2`: the same settings with the model's default effort,
`xhigh`.

## Result: worse, keep the default

| | A: v1 | A: v2 | B: medium |
|---|---:|---:|---:|
| Passed | 56 | 56 | **49** |
| Leaderboard score | 0.62907 | 0.62907 | 0.55045 |
| Wrong submissions | 14 | 17 | 23 |
| Timeouts | 17 | 14 | 13 |
| Total tokens | 126.9M | 131.5M | 102.5M |
| Output tokens | 4.17M | 4.23M | 2.90M |

- **Slow tasks (`eval/slow_subset.txt`, 34):** 15 passes, against 14.0 per A run. About the same.
- **The other 55 tasks:** 34 passes, against 42.0 per A run. This is where the loss is.
- **Lost:** 7 tasks that passed in both A runs: break-filter-js-from-html, compile-compcert, crack-7z-hash,
  extract-elf, mcmc-sampling-stan, protein-assembly, sqlite-db-truncate.
- **Gained:** 3 tasks that failed in both: adaptive-rejection-sampler, chess-best-move, write-compressor.

**Less thinking means more wrong answers** (23 against about 15.5) and barely fewer timeouts. A run on the
slow subset alone would have shown +1 and hidden the loss on the other 55 tasks.

## Decision

Keep the model's default effort (`AGENT_REASONING_EFFORT` unset) and the 8192 cap. Both ways of thinking less,
this one and `cap4k-v1`, failed to add passes. An adaptive version (high effort for planning and when stuck)
is a weak bet after this; shelved.
