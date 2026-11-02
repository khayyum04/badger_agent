# Fixing time-limit failures: thinking cap and time awareness

Most of `full-mini-v1`'s failures were tasks that ran out of time, not wrong answers. This page
measures two fixes on the same slow-task list, one at a time:

- **Thinking cap** (`AGENT_THINKING_CAP=8192`, [plan](../plans/thinking-cap.md)): replies get 8,192
  tokens by default and the full `LLM_MAX_TOKENS` only right after a reply runs out.
- **Time awareness** (`AGENT_TIME_AWARENESS=on`, [plan](../plans/time-awareness.md)): each command
  result ends with the minutes used, prompt rule 4 asks for a working output file by about 5-8 minutes,
  and one nudge comes at 10 minutes. Issue #18.

Sources: `jobs/full-mini-v1` (all 89 tasks, Oct 1), `jobs/thinkcap-8k-v1` (cap only) and
`jobs/timeaware-v1` (cap + time awareness, Nov 2). All three were run on the Victus with model
`qwen3.8-27b`. `jobs/` is gitignored, so the data is local to Mukhriz's machines.

## Task list

`mini_agent/eval/slow_subset.txt` has 34 tasks:

- 28 slow tasks that timed out or quit after 5 overruns in `full-mini-v1`;
- 6 control tasks that passed in `full-mini-v1` and thought the most. These check that nothing broke.

In `timeaware-v1`, `gpt2-codegolf` and `write-compressor` were cancelled 35 seconds into the run
(`CancelledError`, before any real work). Both timed out in the other two runs. The tables below leave
them out, so the slow group has 26 tasks.

## Results

| | `full-mini-v1` | Cap only | Cap + time awareness |
|---|---:|---:|---:|
| Slow tasks passed (of 26) | 2 | 7 | **8** |
| Slow tasks timed out | 23 | 13 | **9** |
| Control tasks passed (of 6) | 6 | 6 | 6 |
| Timed-out tasks that never wrote the output file | — | 7 | **3** |
| Tokens, 32 tasks | 64.3M | 64.8M | **50.1M** |
| Server output speed | — | 82 tok/s | 77 tok/s |

"Never wrote the output file" is measured by `my-notes/first_write.py`. It reads the command text and
looks for writes to a path named in the task, so it can miss files written through a variable.
Server speed is output tokens divided by agent wall time. It is rough, but good enough to show that
the second run was not helped by a faster server.

### Thinking cap

On the slow tasks, passes went from 2 to 7 and timeouts from 23 to 13. All 6 control tasks still
passed. Part of this gain is luck and server speed on the day, so our estimate is about +1-2 tasks on
the full benchmark.

### Time awareness (on top of the cap)

Overall, passes rose by one, from 13 to 14 out of 32. Run-to-run noise on a list this size is about ±3,
so the pass count alone proves little. The changes underneath it show what time awareness did:

- **5 gains, all former timeouts:** cancel-async-tasks, chess-best-move, cobol-modernization,
  model-extraction-relu-logits, protein-assembly. For example, chess-best-move never touched
  `/app/move.txt` in 45 commands with the cap only. With time awareness it wrote the answer at
  9.8 minutes and passed.
- **4 losses, none caused by time pressure:**
  - circuit-fibsqrt and schemelike-metacircular-eval quit after 5 overruns in a row, before the
    10-minute nudge.
  - code-from-image gave a wrong hash.
  - gcode-to-text guessed the wrong letter at the time limit.

  The cap-only run passed all 4.
- Timed-out tasks that never wrote anything fell from 7 to 3: caffe-cifar-10, path-tracing-reverse
  and polyglot-rust-c.
- The weak spot we were worried about, "submits sooner and gets it wrong", showed up a little. Slow
  tasks that submitted a wrong answer went from 4 to 6. Two of them, raman-fitting and
  torch-pipeline-parallelism, timed out before and now finish with a wrong answer. Quitting after
  5 overruns in a row also rose, from 2 to 4.
- large-scale-text-editing (a control task) took 20 minutes instead of 3 and passed after a timeout.
  It's worth watching in the full run.

## Bottom line

Use both settings for the next full run. Time awareness hits the failure it was built for: fewer timed-out
tasks with no output file, and every gain was a former timeout. It also cost fewer tokens. Its effect on
passes is small and not proven by one run, so the full 89-task run is the real test.

Next problem: overrun streaks. In this run they ended 2 tasks before the 10-minute mark, even with the cap
giving the full budget after each overrun.
