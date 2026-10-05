# Context compaction and stripping: what five runs showed

We tried two ways to keep the model's context small, to avoid **context rot**: the model getting worse
as a long session's history grows.

- **Stripping** (`AGENT_STRIP_REASONING=on`): stop re-sending the model's earlier thinking.
- **Compaction** (`AGENT_COMPACTION=on`): when the history gets long, the model replaces older turns
  with a summary it writes itself (`self_compact` tool; notice → warning → hard stage).

Code: `mini_agent/badger_mini/compaction.py`. Plan: [self-compaction-mvp.md](../plans/self-compaction-mvp.md).
All runs use `qwen3.8-27b` (not approved for submission), single attempt per task. Jobs are local
(`mini_agent/jobs/`, gitignored).

## The runs

| Run | Job | Settings |
|---|---|---|
| Baseline | `2026-09-27__12-44-55` | nothing on, 30 tasks |
| Strip only | `strip-only-n2` | stripping on, 30 tasks |
| Compaction 25K | `compact-only-10-20-30-n2` | compaction at 25K / 50K / 75K tokens, 30 tasks |
| Strip + compaction | `full-strip-compact-10-15-25` | both on, 25K / 37.5K / 62.5K, all 89, 3 tasks at a time |
| Compaction 50K | `full-compact-50-100-150-n2` | compaction at 50K / 100K / 150K, all 89, with the forced-mode fixes below |

All but "strip + compaction" ran 2 tasks at a time. The table below compares the same 30 tasks
(`mini_agent/eval/experiment_subset.txt`) in every run.

## Results on the same 30 tasks

| | Baseline | Strip only | Compaction 25K | Strip + compaction | Compaction 50K |
|---|---:|---:|---:|---:|---:|
| Passed | **15** | **15** | 13 | 11 | 13 |
| Ran out of time | 3 | 8 | 8 | 12 | 10 |
| Thinking per turn (tokens) | 1,023 | 1,650 | 1,426 | 1,524 | 1,311 |
| Typical context per call | 46K | 20K | 26K | 16K | 37K |
| Total tokens | 77.2M | 31.3M | 41.2M | 19.6M | 56.3M |
| Tokens vs baseline | — | −59% | −47% | −75% | −27% |

On all 89 tasks, compaction 50K passed **47 of 89**, the best full run so far (strip + compaction:
41 of 89).

**Noise warning:** 15 of the 30 tasks changed result at least once between runs. A difference of
two passes is within luck.

## What we learned

1. **No setting beat the baseline on passes.** Smaller context did not make the model solve more
   tasks.
2. **Stripping makes the model think about 60% longer per turn.** Without its earlier reasoning it
   works things out again. Turns get slower and more tasks run out of time (3 → 8). Not worth it.
3. **Compaction works mechanically.** The model writes good summaries (exact paths, errors, test
   results) and does not redo work. At 50K it mostly compacts by itself at the notice (16 of 25
   compactions). A compaction takes the history from about 67K to about 19K tokens.
4. **Context rot shows up above about 100K tokens.** In the compaction 50K run, calls with more than
   100K tokens of context thought about 3× longer and wasted about 10 turns in 100 (the model
   thinks until its limit and produces nothing), against about 1 in 100 below 100K. The baseline
   shows the same jump in thinking. Below 100K we saw no degradation. Caveat: those calls come from
   the hardest tasks, so part of the jump may be the task, not the context.
5. **Two long tasks passed for the first time ever with compaction 50K:** `path-tracing-reverse`
   (4 compactions) and `schemelike-metacircular-eval` (1 compaction). One run each, so not proof.

## Forced compaction: the problem and the fix

When the model ignores the notice and warning, the hard stage takes `bash` away until it calls
`self_compact`. At 25K this failed 8 times in 12 forced episodes: 4 times the model called `bash`
anyway, 4 times it thought about the task and never wrote the call. Once a task ended locked out.

Three fixes, all in the compaction 50K run:

- **One last command** after the hard message, so the model can finish its step.
- **Thinking off on the locked turn** (`COMPACT_FORCED_THINKING=on` turns it back on). Writing the
  summary is the reasoning step.
- **Give `bash` back after two failed attempts**, so a task never ends locked out.

Result: both forced episodes compacted on the first locked turn, with zero thinking. Only two
episodes, so this needs more runs to confirm.

## How many tokens compaction saved

- **Measured, same 30 tasks:** compaction 50K used 56.3M tokens against the baseline's 77.2M,
  **−21M (−27%)**. Compaction 25K used 41.2M, **−36M (−47%)**.
- **Estimated, compaction 50K on all 89:** compaction saved about **33M tokens**, roughly **20%** of
  the ~162M the run would have used without it. Estimate = each compaction's drop in context size,
  counted on every later call in that task, minus the cost of the compaction call itself. It assumes
  the model would have behaved the same without compacting.

Saving tokens is a side effect; the goal is avoiding context rot.

## Recommendation

- **Keep stripping off.**
- **Keep compaction, with the hard cutoff at 100K** (for example notice 50K, warning 75K, hard
  100K), so the context never reaches the zone where the model degrades.
- **Repeat the run** before trusting any pass difference; single runs are too noisy.
