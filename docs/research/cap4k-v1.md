# Thinking cap 4096 on the slow tasks (`cap4k-v1`)

`eval/slow_subset.txt` (34 tasks), Victus, Nov 5-6 2026, branch `feat/overrun-recovery`, all defaults
except `AGENT_THINKING_CAP=4096`. The A side is the same 34 tasks in `full-all-v1` and `full-all-v2` (cap 8192).

## Result: no gain

| | A: v1 | A: v2 | B: cap 4096 |
|---|---:|---:|---:|
| Passed | 14 | 14 | **14** |
| Timeouts | 12 | 11 | 9 |
| Wrong submissions | 7 | 8 | 6 |
| Ended on 5 format errors | 0 | 0 | 2 |
| Step limit | 1 | 1 | 3 |

- **Same pass count, different mix.** Three tasks that failed in both A runs passed: `chess-best-move`,
  `code-from-image`, `dna-assembly`. Two that passed in both failed: `feal-linear-cryptanalysis` (timeout)
  and `protein-assembly` (step limit). With 24 of 89 tasks flipping between identical runs, that's noise.
- **More cut-offs:** 10% of replies were cut, against 4% in `full-all-v1`.

## New failure: long commands get cut

A command is part of the reply, so the cap limits the command too.

- **`make-doom-for-mips`:** five replies in a row stopped at exactly 4096 tokens inside the tool call
  (`finish_reason=tool_calls`). These were large files written with a heredoc. A cut tool call is a broken
  tool call, so it counts as a format error. It isn't a `length` overrun, so overrun recovery doesn't step in,
  and five in a row ended the task.
- **`winning-avg-corewars`:** after boosted retries, two replies finished with `stop` and no tool call
  (9-15K tokens). Those also count as format errors without recovery.

## Decision

Keep 8192. A lower cap can't tell thinking from a long command. `AGENT_REASONING_EFFORT` shortens thinking
without cutting replies, so it's the next test (`effort-medium-v1`, same 34 tasks).
