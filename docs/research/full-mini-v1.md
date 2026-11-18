# mini_agent on all 89 tasks (full-mini-v1)

The first full 89-task run of `mini_agent/` (mini-swe-agent as a Harbor external agent), compared with
the starter agent's full run. This is the new baseline for all 89 tasks.

- **Sources:** `jobs/full-mini-v1/` (mini_agent) and the combined starter run (`jobs/full-89-0924` plus
  the graded results of `rerun-21-0926` and `rerun-13-0927`; see
  [full-89-0924-failure-analysis.md](full-89-0924-failure-analysis.md)). `jobs/` is gitignored, so both
  are local to Mukhriz's machine.

## Run facts

| | mini_agent | Starter agent |
|---|---|---|
| Job | `full-mini-v1` | `full-89-0924` + reruns |
| Commit | `036bf6a` | `21d5c09` |
| Model | `qwen3.8-27b` (**not approved**, dev run) | `qwen3.8-27b` |
| Flags | `-n 2 --n-attempts 1 --environment-build-timeout-multiplier 6` | `-n 3`, then reruns |
| Wall clock | 12 h 8 min (Oct 1, 07:11 to 19:19 UTC) | ~7 h plus reruns |

## Summary

| All 89 tasks | mini_agent | Starter agent |
|---|---:|---:|
| Passed | **52 / 89** (TB 0.584) | 40 / 89 (0.449) |
| Hit the time limit | 25 | 32 |
| Never graded | 0 | 8 |
| Total tokens | 143.2M (138.4M in, 4.8M out) | 110.9M |
| Median tokens per task | 0.74M | |
| **Leaderboard score** | **−0.848** | −0.660 |

- **12 more passes, but a worse leaderboard score.** The pass gain is worth +0.135; the extra 32.3M
  tokens cost −0.323.
- **97% of tokens are input**, the history re-sent every turn. This is what #13 (offloading) and #14
  (trimming) target.
- **Failures cost twice what passes do:** failed tasks used 95.3M tokens, passes 47.9M.
- **Time limits are the most expensive failures:** the 25 timed-out tasks used 56.4M tokens (39% of
  the total) and only 2 of them passed.

Passes gained over the starter (17): `break-filter-js-from-html`, `build-pmars`, `build-pov-ray`,
`compile-compcert`, `configure-git-webserver`, `custom-memory-heap-crash`, `dna-insert`, `fix-ocaml-gc`,
`llm-inference-batching-scheduler`, `model-extraction-relu-logits`, `mteb-leaderboard`, `overfull-hbox`,
`password-recovery`, `prove-plus-comm`, `query-optimize`, `rstan-to-pystan`, `train-fasttext`.

Passes lost (5): `cancel-async-tasks`, `cobol-modernization`, `code-from-image`,
`financial-document-processor`, `largest-eigenval`.

## Most expensive tasks

| Task | Tokens | Result |
|---|---:|---|
| `make-mips-interpreter` | 8.6M | fail |
| `build-pov-ray` | 7.2M | pass |
| `path-tracing-reverse` | 7.2M | time limit |
| `winning-avg-corewars` | 7.2M | time limit |
| `circuit-fibsqrt` | 7.1M | time limit |
| `path-tracing` | 6.0M | fail |
| `tune-mjcf` | 5.3M | fail |
| `fix-ocaml-gc` | 5.1M | pass |
| `protein-assembly` | 5.0M | time limit |
| `sam-cell-seg` | 4.8M | fail |

## The 30-task experiment subset in this run

On the 30 tasks of `mini_agent/eval/experiment_subset.txt`, this run passed **12 / 30 on 74.0M tokens**.
The earlier subset-only run ([mini-30-vs-baseline.md](mini-30-vs-baseline.md)) passed 15 / 30 on 77.2M
with essentially the same code. So a single run varies by about ±3 tasks on the subset. A change
measured on one subset run has to beat that noise before it counts.

## Reproduce

```bash
./mini_agent/scripts/score.sh jobs/full-mini-v1
# tasks=89 tb_score=0.5843 total_tokens=143204830 leaderboard_score=-0.8478
```
