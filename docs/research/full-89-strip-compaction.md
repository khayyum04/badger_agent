# Stripping old thinking + self-compaction on all 89 tasks

The first full run of `mini_agent` with both context-saving switches on: old thinking is no longer
re-sent (`AGENT_STRIP_REASONING=on`) and the agent can compact its own history
(`AGENT_COMPACTION=on`, [plan](../plans/self-compaction-mvp.md)). It asks two questions: how much
do they save, and what do they cost in passes?

- **Sources:** `mini_agent/jobs/full-strip-compact-10-15-25/` (this run) and
  `mini_agent/jobs/2026-09-27__12-44-55/` (the 30-task mini_agent baseline,
  [write-up](mini-30-vs-baseline.md)). `jobs/` is gitignored, so both are local to Khayyum's machine.
- **Comparisons:** the same 30 tasks against the mini_agent baseline, and all 89 against the starter
  agent's run ([full-89-0924](full-89-0924-failure-analysis.md)). There is **no 89-task mini_agent
  run without the switches** and **no strip-only run**, which limits what can be concluded; see
  [Caveats](#caveats).

## Contents

- [Run facts](#run-facts)
- [Summary](#summary)
- [Tokens: where the reduction came from](#tokens-where-the-reduction-came-from)
- [How compaction behaved](#how-compaction-behaved)
- [Passes: time is now the limit](#passes-time-is-now-the-limit)
- [Did compaction cost passes?](#did-compaction-cost-passes)
- [Bottom line and next steps](#bottom-line-and-next-steps)
- [Caveats](#caveats)
- [Method](#method)

## Run facts

| | This run | mini_agent baseline (30 tasks) |
|---|---|---|
| Job | `full-strip-compact-10-15-25` | `2026-09-27__12-44-55` |
| Tasks | all 89 | the 30-task [experiment subset](full-89-0924-fix-priorities.md#experiment-subset) |
| Code | `866798a` plus uncommitted changes (`badger_mini/compaction.py`, hooks in `harbor_agent.py`) | fork commit `08367552` |
| Model | `qwen3.8-27b` (UW gateway; **not approved**) | same |
| Old thinking re-sent | **no** | yes |
| Compaction | **on**: notice 25,000 / warning 37,500 / hard 62,500 tokens (10% / 15% / 25% of the 250K window) | off |
| `max_tokens`, sampling, turn cap, command timeout | 16,384; 0.6 / 0.95; 100; 180 s | same |
| Concurrency | **3** | 2 |
| Wall clock | 8 h 29 min (22:00 → 06:29) | 4 h 28 min |

The run is valid: all 89 trials finished, 88 were graded (`filter-js-from-html` hit a verifier
timeout), every trial made model calls from start to finish (no VPN drop), and every trial's
metadata records `strip_reasoning: true`.

## Summary

| | This run, 89 tasks | Starter agent, 89 tasks |
|---|---:|---:|
| Passed | **41 / 89** (TB 0.461) | 28 / 89 (0.315) |
| Total tokens | **47.3M** (42.3M in, 5.0M out) | 93.2M |
| Leaderboard score | **−0.013** | −0.617 |
| Hit the time limit | 33 | 27 |

| Same 30 tasks | This run | mini_agent baseline |
|---|---:|---:|
| Passed | 11 / 30 (0.367) | **15 / 30** (0.500) |
| Total tokens | **19.6M** | 77.2M |
| Leaderboard score on these 30 | **+0.170** | −0.272 |
| Hit the time limit | 12 | 3 |
| Model calls | 975 | 1,263 |
| Input tokens per call | 17.5K | 59.4K |
| Overruns | 62 | 37 |
| Total agent time | 10.6 h | 7.3 h |

- **Tokens fell by 75% on the same 30 tasks** (77.2M → 19.6M). That is worth 0.58 leaderboard
  points; the 4 lost passes cost 0.13. The leaderboard score on these 30 turned positive.
- **Passes fell 15 → 11, and the cause is time, not wrong answers.** Timeouts went 3 → 12. The model
  now thinks longer per turn and overruns more often, and the endpoint was about 40% slower.
- **Compaction worked as designed.** It fired 18 times in 13 tasks, mostly when the model was asked
  at the warning stage, and saved an estimated 11.4M tokens (19% of what the run would have used).
- **This run cannot say whether compaction itself costs passes.** Three things changed at once
  (strip, compaction, concurrency). Of the 6 passes lost, 2 never compacted, 1 compacted only after
  the baseline had already finished, and 3 are unclear.

Passes gained on the 30 (2): `fix-ocaml-gc` (the baseline's run was cancelled during grading),
`financial-document-processor`.

Passes lost (6): `break-filter-js-from-html`, `feal-differential-cryptanalysis`, `mailman`,
`path-tracing`, `video-processing`, `winning-avg-corewars`.

On the other 59 tasks the agent passed 30 (0.508) with 27.7M tokens and 21 timeouts. There is no
mini_agent baseline for those.

## Tokens: where the reduction came from

On the same 30 tasks, input per model call fell from 59.4K to 17.5K tokens. Three things add up to
the 77.2M → 19.6M drop:

| Source | Rough size | How it is known |
|---|---|---|
| Old thinking no longer re-sent | the largest part | The [replay](../plans/self-compaction.md#expected-effect-static-replay-an-upper-bound) predicted 77.2M → 43–44M from this alone |
| Fewer calls | large | 975 calls instead of 1,263: tasks were cut short by the time limit (`schemelike-metacircular-eval` 100 → 27 calls, `custom-memory-heap-crash` 98 → 45) |
| Compaction | about 7.6M on these 30 | Static estimate from this run (below): without it these 30 would have used about 27M |

The second row is not a real saving: a task that times out uses fewer tokens because it did less
work.

Across all 89 tasks, the 13 tasks that compacted used 21.2M of the 47.3M tokens. The six largest
tasks are now 1.75M–2.44M each (`winning-avg-corewars` 2.44M, `make-doom-for-mips` 2.34M,
`compile-compcert` 2.05M); in the baseline the largest were 6M–11M. The median passed task used
128K tokens and the median failed task 375K.

## How compaction behaved

| | Count |
|---|---:|
| Tasks whose history reached the notice size (25K) | 29 |
| … the warning size (37.5K) | 19 |
| … the hard cutoff (62.5K) | 2 |
| Stage messages sent: notice / warning / hard | 36 / 22 / 2 |
| Compactions | **18**, in 13 tasks |
| … made after a notice / a warning / when forced | 5 / 12 / 1 |

- **The model compacts when told to do it soon.** Twelve of 22 warnings ("within your next one or
  two turns") led to a compaction; only 5 of 36 notices did. This differs from the two smoke runs,
  where it ignored every notice and warning. With these thresholds the hard cutoff is almost never
  reached.
- **Each compaction cut the prompt by about three quarters.** Typical: 38K → 10K tokens (range after
  compacting: 5.6K–17.2K).
- **The summaries are detailed.** The summary-and-note message was 2.0K–6.9K characters. They carry
  exact paths, constants, commands that worked and test scores (for example `path-tracing` listed 20
  constants read from the binary and each recovered function's logic).
- **The model did not redo work verbatim.** Of 363 commands run after a compaction, 8 were exact
  repeats of an earlier command.
- **Writing the summary costs a turn of thinking.** A `self_compact` call produced a median of 2,439
  output tokens; the largest was 11,329.
- **Forced mode failed once.** `path-tracing-reverse` reached the hard cutoff, the model overran on
  both forced attempts, and the task hit its time limit still locked out of `bash`. This is the
  failure the full design's "release after two failed attempts" rule exists for; the experiment
  version does not have it.
- One early `self_compact` call got the "Not compacted" reply. No call had invalid arguments.

### Estimated savings

Treating each compaction's drop in prompt size as saved on every later call of that task, and
subtracting the cost of the `self_compact` call itself, compaction saved **about 11.4M tokens**:
the run would otherwise have used about 58.7M. That is 0.11 leaderboard points, the value of 10
passes out of 89. The estimate assumes the model would have behaved the same without compacting.

| Task | Result | Compactions (at call, of total calls) | Est. saved |
|---|---|---|---:|
| `path-tracing` | timeout | 16 and 30, of 46 | 1.65M |
| `make-doom-for-mips` | timeout | 16, of 67 | 1.52M |
| `video-processing` | wrong answer | 12 and 31, of 54 | 1.36M |
| `path-tracing-reverse` | timeout | 13 and 27, of 49 | 1.28M |
| `make-mips-interpreter` | timeout | 41, of 68 | 1.05M |
| `build-pov-ray` | **pass** | 43, of 79 | 1.00M |
| `mailman` | timeout | 42, of 73 | 0.88M |
| `fix-ocaml-gc` | **pass** | 31 and 72, of 73 | 0.70M |
| `winning-avg-corewars` | turn cap | 73, of 100 | 0.68M |
| `sam-cell-seg` | wrong answer | 43 and 67, of 68 | 0.61M |
| `gcode-to-text` | timeout | 33, of 50 | 0.51M |
| `compile-compcert` | turn cap | 95, of 100 | 0.10M |
| `custom-memory-heap-crash` | **pass** | 43, of 45 | 0.02M |

Three of the 13 passed. These are the longest and hardest tasks, so a low pass rate among them is
expected with or without compaction.

## Passes: time is now the limit

**33 of 89 tasks hit their time limit** (3 of them passed anyway). In 25 of the 33, at least 80% of
the limit was spent waiting on the model, not running commands. Fifteen were cut off in the middle
of a model call.

Three things made turns slower than in the baseline. On the same 30 tasks:

| | Baseline | This run |
|---|---:|---:|
| Mean time of a normal turn's model call | 11.3 s | 20.8 s |
| Output tokens per successful call (mean) | 1,259 | 1,798 |
| Overruns | 37 (in 12 tasks) | 62 (in 19 tasks) |
| Time in turns that contained an overrun | 0.7 h (9% of agent time) | 2.8 h (26%) |
| Endpoint speed (output tokens per second) | 94 | 57 |

1. **The model thinks more per turn after the first few turns.** Mean output per call, by position
   in the task:

   | Calls | Baseline | This run |
   |---|---:|---:|
   | 1 | 1,938 | 2,286 |
   | 2–5 | 3,867 | 4,174 |
   | 6–15 | 1,722 | 2,867 |
   | 16–40 | 1,505 | 2,473 |
   | 41+ | 1,295 | 2,221 |

   The first five calls are about the same; from call 6 the mean is 64–72% higher. The medians are
   similar in both runs, so the difference is more very long thinking turns, not longer typical
   ones. The likely cause is stripping: the model no longer sees its earlier reasoning, so it works
   things out again. This is a pattern, not proof (see Caveats).
2. **Overruns nearly doubled** (37 → 62). An overrun burns the whole 16,384-token budget and
   produces nothing; at this endpoint speed that is 3 to 5 minutes each. Turns containing an overrun
   took a quarter of all agent time on these 30 tasks.
3. **The endpoint was slower and uneven.** Speed by hour ranged from 38 to 93 output tokens per
   second (the baseline run: 83–115). The run used 3 concurrent tasks instead of 2, and the endpoint
   is shared, so the two causes cannot be separated.

The other failures are the familiar ones: 10 wrong submissions, 4 `RepeatedFormatError` (five
overruns in a row: `circuit-fibsqrt`, `dna-assembly`, `feal-linear-cryptanalysis`, `regex-chess`)
and 3 at the 100-turn cap.

## Did compaction cost passes?

The six passes lost on the 30 tasks, one by one:

| Task | Compacted? | What happened | Verdict |
|---|---|---|---|
| `break-filter-js-from-html` | no | Timeout at 1,200 s after 17 calls and 3 overruns. The baseline needed 400 s. Output tokens 24K → 83K | Not compaction |
| `feal-differential-cryptanalysis` | no | Timeout at 1,800 s after 21 calls and 5 overruns. Output tokens 74K → 161K | Not compaction |
| `winning-avg-corewars` | at call 73 | Hit the 100-turn cap without ever writing `/app/my_warrior.red`. The baseline had submitted by call 63, before this run's compaction | Not compaction |
| `mailman` | at call 42 | Timeout after 73 calls; 1 of 3 tests passed. The baseline did 99 calls in 688 s with 36K output tokens; this run produced 145K output tokens in 1,800 s | Unclear, mostly time |
| `path-tracing` | at calls 16 and 30 | Timeout after 46 calls without ever writing `/app/image.c`. It found the original generator binary and tried to rebuild its exact source from the disassembly; the baseline approximated the image and wrote the file at action 47 | Unclear: a different, slower approach |
| `video-processing` | at calls 12 and 31 | Submitted; 4 of 5 tests passed (a frame number was off by 10 on the test video) | Unclear |

So no lost pass can be pinned on compaction, and three cannot be cleared. In the two unclear
timeouts the model was already slow before it compacted.

Two patterns from the baseline analysis show up again, unrelated to compaction:
`winning-avg-corewars` and `path-tracing` never wrote their output file, although the prompt says to
write it as soon as there is a plausible answer
([W3](mini-30-vs-baseline.md#w3-no-sense-of-time-and-the-answer-file-isnt-written-early--no-visible-change)).

## Bottom line and next steps

The two switches together cut tokens by about three quarters and moved the leaderboard score on all
89 tasks from deeply negative to about zero (−0.013). Token cost is no longer what holds the score
down. **Time is**: a third of the tasks run out of it, mostly while waiting for the model to think.

Next, in order:

1. **Run strip-only on the 30 tasks at concurrency 2.** It is the missing comparison. It tells
   whether stripping is what makes the model think longer, and it isolates compaction's effect on
   passes (this run against that one).
2. **Cut the time lost to overruns.** They took 18% of all agent time in this run. Options already
   listed in the fix plan: a smaller thinking budget on normal turns with more room only on the
   retry ([C4](full-89-0924-fix-priorities.md#cause-track-fewer-overruns-at-the-source)), or
   thinking turned off on the retry.
3. **Keep compaction on with these thresholds.** It fires at the warning, the summaries hold up, and
   it is worth about 0.11 points. Add the "release after two failed forced attempts" rule from the
   [full design](../plans/self-compaction.md) before the next long run; `path-tracing-reverse` hit
   that case.
4. **Use concurrency 2 for comparable runs**, or accept slower turns at 3.

## Caveats

- **Three changes at once.** Stripping, compaction and concurrency 3 all differ from the baseline.
  The run measures their sum.
- **Not the approved model.** Both runs used `qwen3.8-27b`.
- **One sample per task.** A difference of one or two passes is noise. The timeout count (3 → 12 on
  the same tasks) and the token totals are large enough to trust; the per-task verdicts are not.
- **The "thinks more after stripping" finding is an inference.** It rests on the by-position table.
  The tasks took different paths in the two runs, and a slower endpoint does not change how many
  tokens the model writes, but nothing here rules out other causes.
- **Endpoint load varies.** The endpoint is shared, so speed, and with it the timeouts, differ
  between runs.
- **The compaction savings are a static estimate.** They assume unchanged behavior without
  compaction.
- **The subset is overrun-heavy by design** (20 of the 30 were picked for having the most overruns),
  so its timeout rate is worse than the other 59 tasks'.

## Method

Computed from each trial's `result.json` and its transcript.

- **Transcript:** with compaction on, `agent/mini-swe-agent.trajectory.json` holds only the history
  after the last compaction; each replaced history is in `agent/compaction-<n>.json`. The full
  sequence of messages is rebuilt from all of them, counting each message once.
- **Tokens, passes, timeouts:** `n_input_tokens + n_output_tokens`, `verifier_result.rewards.reward`
  and `exception_info.exception_type` from `result.json`. For timed-out trials the transcript can
  hold one more model call than `result.json` (the call in flight when Harbor read the counts), so
  call-level figures come from the transcript and totals from `result.json`.
- **Overrun:** a format-error note whose stored response has `finish_reason == "length"`.
- **Turn time:** the gap between a model reply's timestamp and the previous timestamped message.
  **Endpoint speed:** output tokens divided by that gap, summed over successful calls.
  **Command time:** the gap between a tool result and the reply before it.
- **Compaction stage:** the `stage` recorded in `agent_result.metadata.compactions`.
- **Estimated savings:** for each compaction, (prompt of the `self_compact` call − prompt of the next
  call), accumulated over a task's compactions and multiplied by the number of later calls, minus the
  `self_compact` call's own input and output tokens.
- **Exact repeats:** commands after a task's first compaction that are character-for-character equal
  to an earlier command in that task.
