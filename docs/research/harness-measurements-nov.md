# Harness ideas measured on existing runs (Nov 10–18 2026)

After the change report (`full-change-v1.md`) we took the untried ideas from LangChain's Terminal-Bench 2.0
harness write-up (langchain.com/blog/improving-deep-agents-with-harness-engineering) and measured each one
against the trajectories we already had before building anything. This note records what each measurement
found, so nobody re-tests these dead ends.

Data: `full-all-v1`, `full-all-v2` (repo-root `jobs/`) and `full-all-v3` (`mini_agent/jobs/`), all plain defaults,
267 trials. One new full run: `full-offafter1-v1` (`mini_agent/jobs/`).

## Bottom line

| Idea | How it was tested | Verdict |
|---|---|---|
| Reasoning sandwich (more effort to plan/verify, less in the middle) | Thinking per phase + effort probe | **Dropped**: the bookends are near no-ops, and unset effort already thinks least |
| Thinking off after the first overrun | Retry probe + full run | **No gain** (50/89); keep the default of 2 |
| Edit tool (avoid whole-file rewrites) | Command parsing | **Not worth building**: the agent already edits in place |
| Loop detection | Command parsing + test output | **Not worth building**: the agent doesn't loop |
| "Graded by tests, exact paths" prompt line | Read the prompt | **Already there** (`terminal_bench.yaml` lines 20–21) |
| Environment onboarding | Phase measurement | **Redundant**: the first 1–3 calls are already a cheap `ls` |

Baseline: 56 / 56 / 57 passes. Most wrong answers are tasks the model gets wrong every time, not process
mistakes (see "Loops and wrong answers" below). The harness ideas from that write-up are now used up for us.

| Run | Passed | Timed out (failed) | Wrong | Tokens |
|---|---:|---:|---:|---:|
| full-all-v1 | 56 | 17 | 16 | 126.9M |
| full-all-v2 | 56 | 14 | 19 | 131.5M |
| full-all-v3 | 57 | 13 | 19 | 145.4M |
| full-offafter1-v1 | 50 | 12 | 27 | 159.0M |

"Passed" counts `reward == 1`, including trials that timed out but still passed (about 2 per run). The other two
columns are failures only.

## 1. Where thinking goes (sandwich measurement)

Each trial was split into phases: the first 3 calls, the middle, and everything after the submit check.

- The middle holds 86–97% of visible thinking. The first 3 calls are tiny (median 15–85 thinking tokens,
  usually `ls`). After the submit check it's about 3%, and **0 of 46 timed-out trials ever reached the check**.
- **Overruns are the real cost.** An overrun is a reply that hits the 8192 thinking cap with no tool call. It is
  dropped from the trajectory but still billed: 25–34% of all output tokens, and 140 overruns across 34 of the
  46 timeouts (about 5 minutes of a 15-minute limit).

So a sandwich would only change the middle, and the question became "should the middle think less?"

## 2. Effort probe

24 real mid-task requests were replayed with `reasoning_effort` unset, xhigh, high and medium (96 calls).
Thinking length relative to unset (geometric mean): **xhigh ×1.92** (95% CI 1.16–3.34), **high ×1.55**
(0.91–2.70), **medium ×0.96**. Medium also hit the cap more often (3 of 24 vs 1).

- **Unset is not xhigh.** The old code comment saying so was wrong and has been fixed.
- "Middle at high" would think *more*, not less, so the sandwich was dropped. Medium everywhere had already
  scored 49 (`full-effort-medium-v1.md`).
- Caveat: one sample per request, and the noise between requests is large.

## 3. Thinking off after an overrun (`AGENT_OVERRUN_THINKING_OFF_AFTER`)

**Probe:** 30 real post-overrun requests replayed three ways (stopped at 32 of 90 when the VPN dropped).
`reasoning_effort=low` at the 8192 cap overran on 6 of 12, so it's ruled out. Thinking off always produced a
command in 2–26 s, and in the 8 comparable cases it matched what the agent eventually did.

**Full run** (`full-offafter1-v1`, branch `feat/overrun-thinking-off` at `2b8157d`, setting 1): **50/89**.
Plan and judging criteria are in `docs/plans/overrun-thinking-off.md`.

- The mechanism worked: double overruns (two in a row) went from 21 per run to 0.
- But re-overruns within 2 replies rose from 25–30 to 48. Total overruns didn't change (120 vs 110–115), so no
  time was saved. The model just did its thinking one call later.
- Of the 11 tasks lost, 5 had no overruns at all, so part of the drop is run-to-run noise. There were still 8
  more wrong answers than the worst baseline.
- Verdict: no gain. The setting stays in the code with default 2 (unchanged behaviour).

## 4. Whole-file rewrites (edit tool)

All 9711 commands were parsed for heredoc writes (`cat`/`tee`), `sed -i`, and Python `open(..., 'w')` edits.

- 1505 heredoc writes, of which 170 rewrote an existing file. Only **17** rewrote a file of 30+ lines while
  changing ≤20% of it, about 0.01M tokens in total, and none of them were in timeouts.
- The agent already edits in place: 335 `sed -i` and 300 Python replace edits.
- Median write is about 870 characters. Only 22 of 9001 commands are over about 3K tokens.
- Conclusion: overruns come from thinking, not from writing big files. Caveat: we can't see dropped overrun
  replies.

## 5. Loops and wrong answers

Script: `docs/research/scripts/loops.py` (`python3 -I docs/research/scripts/loops.py <job dirs>`).

| | passed (169) | wrong (54) | timed out (44) |
|---|---|---|---|
| Commands (median) | 21 | 36 | 54 |
| Same command repeated (median) | 0 | 0 | 0 |
| Same command run 4+ times | 0% | 0% | 0% |
| Longest run of failing commands (median) | 1 | 1 | 2 |
| One file written 5+ times | 11% | 19% | 23% |
| Got the submit checklist | 96% | 87% | 0% |
| Submitted with no command after the checklist | 3% | 13% | – |

- **No loops.** In the 24 tasks that passed in one run and failed in another, the failing run wrote a single
  file *fewer* times than the passing run in 11 tasks, and more times in only 3.
- **Skipping the check** after the checklist is somewhat more common in wrong answers, but it's about 6 trials
  across three runs.
- **7 wrong trials hit the 100-step limit** without submitting: install-windows-3.11 ×3,
  schemelike-metacircular-eval ×2, compile-compcert, path-tracing-reverse.

**Why answers are wrong:** 33 of the 54 wrong answers are tasks that fail in 2 or 3 of the 3 runs. Test output
for the tasks wrong in all 3 runs:

| Task | What the test says |
|---|---|
| mteb-retrieve | The same wrong answer every time ("HumanEval…" instead of "MTEB…") |
| raman-fitting | Fitted peak far off (expected x0 = 1580; got 3745, 10441, 1573 with gamma 282) |
| filter-js-from-html | 1–6 of hundreds of XSS cases get through |
| torch-pipeline-parallelism | Calls the installed `transformers` the wrong way (`inputs_embeds` vs `input_embeds`), or crashes unpacking `None` |
| sam-cell-seg | v1: IoU 0.11. v2 and v3: **format errors**, a folder instead of a CSV, and a tuple instead of a list |
| dna-assembly, install-windows-3.11 | Wrong in all 3 runs (not analysed) |

These are mostly hard tasks the model can't solve, not process mistakes that a nudge would fix. The 21 one-off
wrong answers look like run-to-run noise, which fits the 56/56/57 spread. Caveats: we only see the final test
output, and only these 6 tasks were spot-checked.

## What's left

- **Step limit 100 → 150:** the only concrete lead (the 7 trials above). Expect +0–2: install-windows probably
  can't pass anyway, and more steps can turn some of these into timeouts.
- Bigger gains probably need a stronger model or more time per task, not more prompt tweaks
  (`model-options-96gb.md`).

## Scripts

Only `scripts/loops.py` survived. The phase, effort-probe, retry-probe and rewrite scripts lived in a session
scratchpad that was wiped. The numbers above come from those runs.
