# Full 89-task sweep — failure analysis (`full-89-0924`)

## Update 2026-09-28: all 89 tasks now attempted

The 21 never-started tasks were rerun on the **same unmodified agent** (commit `1b30b32`,
`qwen3.8-27b`, `LLM_MAX_TOKENS=8192`). Each rerun directory has a `RUN_INFO.txt` with commit,
flags and model id. That fills the gap §0/§4 flagged, for the reruns only.

- `jobs/rerun-21-0926`: all 21, `-n 2`, WSL memory raised from 7.4 GB to 10 GB + 8 GB swap.
  **Zero `RuntimeError`s, which confirms §1's diagnosis: memory pressure, an infra failure, not
  the agent.** 13 tasks then hit `EnvironmentStartTimeoutError`. All 107 GB of Docker images had
  been pruned to free disk, and rebuilding from a cold cache blew Harbor's 600s start budget. Only
  8 trials here are real data (5 passed, 3 `AgentTimeoutError`). The other 13 are superseded.
- `jobs/rerun-13-0927`: those 13, `-n 2 --environment-build-timeout-multiplier 6`
  (600s → 3600s). All 13 scored, 7 passed.

**How to combine: take each task's result from the latest job that actually ran it.** Don't read
any of the three directories on its own. Each alone gives a wrong number.

| Source | Tasks | Passes |
|---|---|---|
| `full-89-0924` (the 68 attempted) | 68 | 28 |
| `rerun-21-0926` (the 8 attempted) | 8 | 5 |
| `rerun-13-0927` | 13 | 7 |
| **Total** | **89** | **40** |

**The headline changes from 0.3146 to 0.4494.** The old figure counted 21 never-attempted tasks as
failures, as §4's caveat anticipated. **28 → 40 is not an improvement:** same agent, same code,
same prompts. The extra 12 passes are measurements recovered from tasks that never ran, not
capability gains. Don't compare any later number against 0.3146.

The rerun's 17.69M tokens are **not wasted or double-counted spend**. The never-started tasks
burned zero tokens originally, so 110.94M is the real single-pass cost of the baseline over 89
tasks.

| | Original sweep (68 attempted) | **Combined, all 89** |
|---|---|---|
| Passed | 28 | **40 / 89 = 0.449** |
| Timed out | 26 (+ `regex-log`, passed) | **31** |
| Said done, tests failed | 6 | **10** |
| Context overflow | 6 | 6 |
| 100-turn cap | 2 | 2 |
| Total tokens | 93.25M | **110.94M → penalty 1.11** |
| Leaderboard score | — | **0.449 − 1.109 = −0.66** |

**§3's ranking still holds, and #1 (tokens) is now more urgent, not less.** The penalty (1.11) is
larger than the score (0.45). **Even 89/89 would score 1.0 − 1.11 = −0.11** at this token rate.

What the 21 reruns added:

- 12/21 passed (57% vs 41% on the first 68). That's plausibly because these tasks are easier, not
  because anything changed. The agent is identical.
- **4 more wrong finishes, all the same pattern: the agent "verified" that a file existed, not
  that it was right.**
  - `build-pmars`: 2/4 tests failed. It missed an explicit instruction ("source must be extracted
    to `/app`").
  - `sam-cell-seg`: 8/9 tests passed. It got one output-format detail wrong (coords as flat
    lists).
  - `mteb-retrieve`: its final check was `cat /app/result.txt`, and the value was wrong.
  - `mteb-leaderboard`: it wrote "I'll write my best answer" and submitted a **guess**, then
    "verified" with `cat` + `wc -c`.
  
  This is direct evidence for Bundle B's requirement-by-requirement check.
- **5 more timeouts** (`dna-assembly`, `dna-insert`, `rstan-to-pystan`,
  `model-extraction-relu-logits`, `sanitize-git-repo`). Two of them were buried in nudges:
  `dna-assembly` got 26, `model-extraction-relu-logits` got 14 in 15 turns.
- **Environment build time is an infra risk for every future run,** especially after a Docker
  prune. Use `--environment-build-timeout-multiplier 6` for all runs from now on.

**Nudges, reclassified across all 3 jobs (310 total):** 159 prose with no command, 112 cut-off
reasoning (>20k chars), **26 ```` ```bash ```` blocks never closed**, 10 other-language blocks,
3 where the model wrote native XML tool-call syntax (`</parameter></invoke>`) instead of closing
the block. The 29 unclosed/XML ones are a cheap parser fix: accept a `bash` block that runs to the
end of the reply or to a `</parameter>` tag.

Source: `jobs/full-89-0924/` (gitignored — raw transcripts, never commit). Every number below was
recomputed from the per-trial `result.json` files and `job.log`. Run on the HP Victus (WSL2),
`-n 3`, unmodified baseline agent, `terminal-bench@2.0`, 2026-09-24 05:50–12:39 UTC. Model id as
the endpoint reported it in `job.log`: `qwen3.8-27b`, 250,000-token context window. No
`RUN_INFO.txt` or `sweep.log` came with the folder, so the exact commit and `.env` values aren't
recorded.

## Headline numbers (original sweep only; **superseded by the update above**)

| | |
|---|---|
| Passed | **28 / 89** (Harbor mean 0.3146) |
| Actually attempted by the agent | 68 (21 never started — see §1) |
| Pass rate on attempted tasks | 28 / 68 = 41% |
| Total tokens | **93.25M** (87.51M input, 5.74M output) |
| Token penalty | 0.01 × 93.25 = **0.93** |
| Leaderboard score | 0.315 − 0.933 = **−0.62** |

**The token penalty is bigger than the entire TB score.** At this token rate, a perfect score
would still come out barely positive. Getting tokens down is priority 1, not an afterthought.

## Outcome breakdown (89 trials)

| Outcome | Count | Agent's fault? |
|---|---|---|
| Passed | 28 | — (1 of these, `regex-log`, passed even though the agent hit the time limit) |
| Agent hit the task's time limit (`AgentTimeoutError`) | 26 | yes |
| Ran past the 250k context window (`BadRequestError` 400) | 6 | yes |
| Declared `TASK_COMPLETE` but the tests failed | 6 | yes |
| Hit `AGENT_MAX_TURNS` = 100 | 2 | yes |
| Docker crashed, task never started (`RuntimeError`, compose exit −11) | 18 | **no — infra** |
| Environment start took >600s (`EnvironmentStartTimeoutError`) | 3 | **no — infra** |

## §1. Infra failures (21) — rerun these, not a feature

> **Confirmed (2026-09-28):** the cause was memory pressure. Raising WSL memory to 10 GB + 8 GB swap
> and using `-n 2` eliminated every `RuntimeError` in the rerun. The disk-space theory was a side
> effect, not the cause.

- **18 tasks failed at the exact same second (12:39 UTC).** `docker compose up` exited with −11
  (segfault) and no output. Docker Desktop or the WSL VM crashed partway through the run. Every
  task still queued at that moment failed instantly. These tasks were **never attempted**, so they
  say nothing about the agent: `build-cython-ext build-pmars constraints-scheduling dna-assembly
  dna-insert git-leak-recovery large-scale-text-editing model-extraction-relu-logits
  nginx-request-logging openssl-selfsigned-cert pytorch-model-recovery rstan-to-pystan sam-cell-seg
  sanitize-git-repo sparql-university sqlite-db-truncate sqlite-with-gcov vulnerable-secret`.
- **3 tasks whose image didn't download within 600s:** `hf-model-inference mteb-leaderboard
  mteb-retrieve` (big ML images). Pre-pulling them or rerunning on a faster connection should fix
  it.

Until these 21 are rerun, the ranking below is based on 68 attempted tasks.

## §2. Root cause behind most agent failures: reasoning bloat in the history

This is the single biggest finding, and it drives the token cost, the context overflows, and much
of the slowness.

- **86% of all transcript text (14.7M of 17.1M chars) is the model's own replies.** Command output
  is 2.3M chars (13%). The system prompt is negligible.
- **457 of 2,420 replies (19%) are over 20,000 characters.** They are cut off mid-sentence. The
  model used up its whole `LLM_MAX_TOKENS` budget thinking, and `llm.py`'s fallback
  (`llm.py:148`) saved the raw `reasoning_content` as the reply.
- **The agent re-sends the full conversation every turn, including every one of those replies.**
  So input tokens grow roughly with the square of the turn count: 87.5M input vs 5.7M output. A
  ~50-turn task reaches 250k tokens of context and the endpoint rejects it (the 6 overflows, all
  at turns 40–56 with 3.7–5.5M tokens).
- **Truncated thoughts often contain no command.** 238 replies (10% of all turns) triggered the
  "no action" nudge: 205 were prose only, and 33 had a code block not tagged `bash`/`sh` (mostly
  ```` ```python ````). Each wasted turn costs a full model call plus a full re-send of the history.
- **Turns are slow:** median 24s per turn, p90 50s. With task time limits of 750–3600s (most are
  900s), the agent gets only about 17–30 turns on most tasks before it's cut off.

## §3. Ranked features to work on

Ranked by (tasks affected × how directly the fix addresses them), with the token penalty
counted as a first-class failure.

| # | Feature | Addresses | Evidence |
|---|---|---|---|
| 1 | **Context management: stop keeping old reasoning in history.** Keep each past turn as its command + a short output summary; drop or compress the reply text. | Token penalty (−0.93), all 6 context overflows, part of the 26 timeouts (less prefill per turn) | §2: 86% of history is replies; 87.5M input tokens |
| 2 | **Handle reasoning truncation / enforce output discipline.** When `content` is empty and the fallback kicks in, don't store the 26k-char thought. Re-ask briefly for "the command only", tune `LLM_MAX_TOKENS`, and prompt for short reasoning. | 238 nudges (10% of turns), per-turn latency, feeds #1 | 457 replies >20k chars, cut mid-sentence |
| 3 | **Time awareness.** The agent doesn't know its time limit (750–3600s, varies by task). Tell it elapsed/remaining time, prefer fast commands, run long builds in the background and poll, and wrap up before the deadline. | 26 timeouts + `regex-log` (solved but never declared done) | 27 `AgentTimeoutError`s; median 24s/turn |
| 4 | **Verify before `TASK_COMPLETE`.** Require running whatever tests or checks the task implies, and comparing against the instruction's exact requirements, before finishing. | 6 finished-but-wrong | `build-pov-ray configure-git-webserver filter-js-from-html llm-inference-batching-scheduler qemu-alpine-ssh query-optimize` — needs a per-transcript read to confirm each one's cause |
| 5 | **Loop / stuck detection (error recovery).** Notice repeated failing commands or 100-turn grinds and force a different approach. | 2 max-turn failures, some timeouts | `compile-compcert`, `install-windows-3.11` hit 100 turns |
| 6 | **Parser robustness.** Decide how to handle ```` ```python ```` blocks: run them via `python3 - <<EOF`, or reject them with a clearer nudge. | 33 nudges | §2 |
| — | **Infra (not a feature):** rerun the 21 never-started tasks; pre-pull big images; keep Docker Desktop memory headroom (maybe `-n 2`). | 21 tasks | §1 |

**Overlap warning for splitting the work:** #1 and #2 both change how a model reply is stored in
the history, the same few lines of `agent.py`. They should either be one person's issue, or the
hooks refactor has to give them separate seams: "clean up a reply before storing it" (#2) vs
"choose which history to send" (#1).

## §4. Caveats

- One run of each task. Task-level pass/fail is noisy. Treat any single task as weak evidence and
  the category counts as the signal.
- The #4 list uses the `finished=True, reward=0` trials; *why* each one was wrong hasn't been read
  per transcript yet.
- The endpoint reports the model as `qwen3.8-27b`. The approved-model table in the root
  `README.md` lists Qwen3.6-27B. Confirm with the organizers that the hosted model counts as
  approved before any submission run.
- `harbor`'s mean counts never-started tasks as 0. The 0.3146 figure will change once §1's 21 tasks
  are rerun.

## Per-trial list

**Passed (28):** bn-fit-modify cancel-async-tasks cobol-modernization code-from-image
count-dataset-tokens crack-7z-hash db-wal-recovery distribution-search extract-elf
feal-linear-cryptanalysis financial-document-processor fix-code-vulnerability fix-git
git-multibranch headless-terminal kv-store-grpc largest-eigenval log-summary-date-ranges
mcmc-sampling-stan merge-diff-arc-agi-task modernize-scientific-stack multi-source-data-merger
portfolio-optimization pypi-server pytorch-model-cli regex-log reshard-c4-data
torch-tensor-parallelism

**Time limit (26):** adaptive-rejection-sampler break-filter-js-from-html caffe-cifar-10
chess-best-move custom-memory-heap-crash extract-moves-from-video feal-differential-cryptanalysis
gcode-to-text gpt2-codegolf mailman make-doom-for-mips make-mips-interpreter overfull-hbox
password-recovery path-tracing path-tracing-reverse polyglot-c-py polyglot-rust-c
protein-assembly prove-plus-comm qemu-startup raman-fitting torch-pipeline-parallelism
train-fasttext tune-mjcf write-compressor

**Context overflow (6):** circuit-fibsqrt fix-ocaml-gc regex-chess schemelike-metacircular-eval
video-processing winning-avg-corewars

**Finished but wrong (6):** build-pov-ray configure-git-webserver filter-js-from-html
llm-inference-batching-scheduler qemu-alpine-ssh query-optimize

**Max turns (2):** compile-compcert install-windows-3.11

**Infra, never started (21):** see §1.
