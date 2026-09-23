# Harbor job failure analysis (all jobs, as of 2026-09-23)

Primary sources only: `jobs/*/*/result.json` (`verifier_result`, `agent_result.n_input_tokens`/
`n_output_tokens`, `agent_result.metadata.{turns,finished,messages}`, `exception_info`),
`jobs/*/*/trial.log`, `jobs/*/*/verifier/{reward.txt,test-stdout.txt}`, and
`starter/agent/{agent,prompts,tools,llm}.py`. No summaries, dashboards, or `plan.md` claims were
taken on faith — every number below was recomputed from `result.json` in this pass. Scratch
scripts used to tabulate: none committed (ad hoc `jq`/Python over `jobs/`); the raw per-trial table
is reproduced in full in §1 so the analysis doesn't depend on a script that isn't checked in.

## 0. Scope and what's *not* covered

- 4 job directories exist under `./jobs/`: `2026-09-12__21-32-36`, `2026-09-21__20-31-31`,
  `2026-09-21__20-32-09`, `2026-09-22__20-46-23` — each a full run of the 10-task
  `terminal-bench-sample@2.0` set (`starter/scripts/run_baseline.sh`'s target), 40 trials total.
  No other `result.json` files exist anywhere in the repo (`find . -name result.json` outside
  `.venv`). This is the entire evidence base — **40 trials, 10 distinct tasks, each run 4 times**.
- No trial in this dataset shows any exception type other than `AgentTimeoutError` or none. There
  is no evidence here of model-API errors, Docker/infra failures, OOM, or crashes in agent code —
  that's a real absence in the data, not a claim that such failures can't happen elsewhere.
- The exact `LLM_MODEL` / `LLM_BASE_URL` used for these 4 runs is **not recorded** in any
  `result.json` (`agent_info.model_info` is `null`, `config.agent.model_name` is `null` — see
  §6). `starter/CLAUDE.md`, `starter/docs/uw_madison_endpoint.md`, and `plan.md` all point at the
  hosted `Qwen3.6-27B-FP8` reasoning-model endpoint as the intended target, and the transcripts'
  style (long chain-of-thought, self-narrated "I'm going in circles" text — §3.3) is consistent
  with a reasoning model, but this is **inference**, not a value read from the artifacts. Flagged
  wherever it matters.
- `starter/.env` / `starter/.env.op` were not read (they're gitignored and may hold credentials —
  out of scope for a read-only research pass; also blocked by the session's own credential-read
  guard). `LLM_MAX_TOKENS`, `LLM_TEMPERATURE`, etc. for these specific runs are therefore unknown
  exactly; only inferred from behavior.
- `starter/plan_docs/context_management/` (the existing context-management design/roadmap) is
  **deleted in the working tree** but present in git history on this branch at `HEAD` (commit
  `1c258e3`) and further developed on branch `harness/context` (commits `f0cba5b`, `1b6325b`,
  `10d1d0c`, not present on the current `harness/compaction` branch). `starter/agent/*.py` on the
  current branch is still the **unmodified baseline** — nothing from that plan is implemented here
  yet. §7 cross-references it explicitly.

## 1. Full per-trial table (all 40 trials)

Recomputed with `jq` per field: `.verifier_result.rewards.reward`, `.agent_result.n_input_tokens`,
`.agent_result.n_output_tokens`, `.agent_result.metadata.turns`, `.agent_result.metadata.finished`,
`.exception_info.exception_type`, plus a Python pass counting nudge messages (exact string match on
`"Your last response contained no action"` from `starter/agent/prompts.py`'s `NUDGE_MESSAGE`) and
`"characters omitted"` (from `starter/agent/tools.py`'s `_truncate`) inside
`agent_result.metadata.messages`.

| task | job | reward | turns | finished | exception | nudges | truncations | n_in | n_out | out/turn |
|---|---|---|---|---|---|---|---|---|---|---|
| build-cython-ext | 2026-09-12 | 1.0 | 87 | true | — | 0 | 4 | 2,142,744 | 25,327 | 291 |
| build-cython-ext | 2026-09-21a | 1.0 | 56 | true | — | 0 | 1 | 863,047 | 26,918 | 481 |
| build-cython-ext | 2026-09-21b | 1.0 | 73 | true | — | 4 | 4 | 1,844,402 | 46,941 | 643 |
| build-cython-ext | 2026-09-22 | 1.0 | 66 | true | — | 1 | 4 | 1,664,666 | 28,812 | 437 |
| chess-best-move | 2026-09-12 | 0.0 | 16 | — | AgentTimeoutError | 1 | 2 | 110,211 | 25,474 | 1,592 |
| chess-best-move | 2026-09-21a | 0.0 | 23 | — | AgentTimeoutError | 1 | 3 | 444,736 | 74,584 | 3,243 |
| chess-best-move | 2026-09-21b | 0.0 | 22 | — | AgentTimeoutError | 1 | 6 | 411,491 | 65,990 | 3,000 |
| chess-best-move | 2026-09-22 | 0.0 | 27 | — | AgentTimeoutError | 0 | 1 | 892,088 | 91,877 | 3,403 |
| configure-git-webserver | 2026-09-12 | 0.0 | 13 | true | — | 0 | 0 | 36,095 | 7,412 | 570 |
| configure-git-webserver | 2026-09-21a | 0.0 | 12 | true | — | 0 | 0 | 40,336 | 6,914 | 576 |
| configure-git-webserver | 2026-09-21b | 0.0 | 14 | true | — | 0 | 0 | 45,856 | 6,115 | 437 |
| configure-git-webserver | 2026-09-22 | 0.0 | 25 | true | — | 0 | 0 | 101,884 | 9,166 | 367 |
| fix-code-vulnerability | 2026-09-12 | 1.0 | 25 | true | — | 0 | 0 | 203,331 | 15,506 | 620 |
| fix-code-vulnerability | 2026-09-21a | 1.0 | 25 | true | — | 4 | 0 | 141,130 | 4,245 | 170 |
| fix-code-vulnerability | 2026-09-21b | 1.0 | 33 | true | — | 0 | 0 | 327,687 | 26,982 | 818 |
| fix-code-vulnerability | 2026-09-22 | 1.0 | 19 | true | — | 0 | 0 | 123,565 | 3,538 | 186 |
| log-summary-date-ranges | 2026-09-12 | 1.0 | 9 | true | — | 0 | 0 | 38,235 | 3,502 | 389 |
| log-summary-date-ranges | 2026-09-21a | 1.0 | 12 | true | — | 2 | 0 | 45,275 | 3,720 | 310 |
| log-summary-date-ranges | 2026-09-21b | 1.0 | 10 | true | — | 2 | 0 | 31,197 | 3,648 | 365 |
| log-summary-date-ranges | 2026-09-22 | 1.0 | 11 | true | — | 0 | 0 | 31,733 | 4,112 | 374 |
| polyglot-c-py | 2026-09-12 | 0.0 | 17 | — | AgentTimeoutError | 1 | 0 | 201,690 | 30,216 | 1,777 |
| polyglot-c-py | 2026-09-21a | 0.0 | 13 | — | AgentTimeoutError | 0 | 0 | 493,404 | 77,607 | 5,970 |
| polyglot-c-py | 2026-09-21b | 0.0 | 17 | — | AgentTimeoutError | 2 | 0 | 446,752 | 65,838 | 3,873 |
| polyglot-c-py | 2026-09-22 | 0.0 | 17 | **true** | — | 5 | 0 | 272,573 | 36,646 | 2,156 |
| qemu-alpine-ssh | 2026-09-12 | 0.0 | 22 | — | AgentTimeoutError | 0 | 1 | 232,056 | 26,748 | 1,216 |
| qemu-alpine-ssh | 2026-09-21a | 0.0 | 48 | — | AgentTimeoutError | 1 | 1 | 997,063 | 69,118 | 1,440 |
| qemu-alpine-ssh | 2026-09-21b | 0.0 | 23 | — | AgentTimeoutError | 2 | 2 | 414,180 | 81,640 | 3,550 |
| qemu-alpine-ssh | 2026-09-22 | 0.0 | 24 | — | AgentTimeoutError | 0 | 0 | 427,702 | 86,995 | 3,625 |
| qemu-startup | 2026-09-12 | 0.0 | 23 | — | AgentTimeoutError | 0 | 1 | 137,927 | 31,859 | 1,385 |
| qemu-startup | 2026-09-21a | 0.0 | 19 | — | AgentTimeoutError | 1 | 0 | 306,908 | 70,572 | 3,714 |
| qemu-startup | 2026-09-21b | 0.0 | 42 | — | AgentTimeoutError | 4 | 2 | 556,463 | 65,200 | 1,552 |
| qemu-startup | 2026-09-22 | 0.0 | 13 | — | AgentTimeoutError | 5 | 2 | 127,128 | 92,900 | 7,146 |
| regex-log | 2026-09-12 | 0.0 | 7 | — | AgentTimeoutError | 0 | 0 | 118,704 | 27,389 | 3,913 |
| regex-log | 2026-09-21a | 0.0 | 16 | — | AgentTimeoutError | 1 | 0 | 492,581 | 68,782 | 4,299 |
| regex-log | 2026-09-21b | 0.0 | 9 | — | AgentTimeoutError | 6 | 0 | 261,117 | 64,585 | 7,176 |
| regex-log | 2026-09-22 | 0.0 | 8 | — | AgentTimeoutError | 6 | 0 | 208,407 | 87,947 | 10,993 |
| sqlite-with-gcov | 2026-09-12 | 1.0 | 30 | true | — | 0 | 1 | 206,971 | 9,127 | 304 |
| sqlite-with-gcov | 2026-09-21a | 1.0 | 26 | true | — | 2 | 0 | 101,665 | 3,592 | 138 |
| sqlite-with-gcov | 2026-09-21b | 1.0 | 24 | true | — | 0 | 0 | 79,395 | 3,836 | 160 |
| sqlite-with-gcov | 2026-09-22 | 1.0 | 19 | true | — | 0 | 0 | 48,548 | 1,935 | 102 |

(`2026-09-21a` = `2026-09-21__20-31-31`, `2026-09-21b` = `2026-09-21__20-32-09`, job dirs
abbreviated for table width.)

## 2. Aggregate numbers

- **Mean reward is exactly 0.4 in all 4 job runs** (4/10 tasks pass, every time):
  `build-cython-ext`, `fix-code-vulnerability`, `log-summary-date-ranges`, `sqlite-with-gcov`. This
  isn't noise — it's the same 4 tasks in all 4 runs (`jobs/*/*/result.json` →
  `verifier_result.rewards.reward`).
- **19/40 trials (48%) end in `AgentTimeoutError`** — a Harbor-level `asyncio.wait_for` timeout on
  the whole `agent.run()` call, fixed at **900.0 seconds** (`exception_info.exception_message`:
  `"Agent execution timed out after 900.0 seconds"` in every one of the 19; the traceback's last
  frame before Harbor's is always `agent.py:145` / `llm.py:131`, i.e. the exception always lands
  *inside an in-flight `llm.chat()` call* — see §3). `900.0` matches Harbor's own template default
  (`.venv/lib/python3.12/site-packages/harbor/cli/template-task/task.toml:6,9` — `timeout_sec =
  900.0`); `config.agent.override_timeout_sec` is `null` in every trial's `config.json`, i.e. no
  per-run override was set.
- **5/40 trials (12.5%) finish (`TASK_COMPLETE` emitted) but score 0** — every
  `configure-git-webserver` trial (4/4), plus one `polyglot-c-py` trial. Root causes differ per
  task but share a shape: the agent verified *something*, then took a further action that
  invalidated the verified state, and declared done without re-verifying (§3.2–3.3).
- **16/40 trials (40%) finish and score 1** — the 4 always-passing tasks, all 4 runs each.
- **0/40 trials hit `AGENT_MAX_TURNS` (100)** — the highest turn count in the whole dataset is 87
  (`build-cython-ext`, 2026-09-12, a *passing* trial). Every failing trial times out well under
  100 turns (7–48). **The 100-turn ceiling in `starter/agent/agent.py` (`MAX_TURNS =
  int(os.environ.get("AGENT_MAX_TURNS", "100"))`) is never the binding constraint in this
  dataset; the 900s wall clock always is.**
- **0/40 trials show an empty assistant response** (`message.content` coming back `""` and
  triggering `llm.py`'s `reasoning_content` fallback — checked directly against
  `agent_result.metadata.messages`, counting assistant messages with empty/whitespace-only
  content). This is the exact failure mode `starter/docs/troubleshooting.md` and
  `starter/docs/uw_madison_endpoint.md` document ("every assistant response is empty ... output
  token count will be exactly `turns × LLM_MAX_TOKENS`") — **it is not what's happening in this
  dataset.** Whatever `LLM_MAX_TOKENS` these 4 runs used, it was high enough that `content` always
  came back non-empty. A *different*, currently undocumented failure mode dominates instead — see
  §3.3.
- Token totals: 15.67M input + 1.48M output = ~17.15M tokens across all 40 trials. Per-job totals
  (input+output), with the resulting `leaderboard_score = TB_score − 0.01×(total_tokens/1M)` at
  `mean_reward` as a crude per-job proxy (10-task sample, not the real 89-task leaderboard number):

  | job | mean reward | total tokens | proxy score |
  |---|---|---|---|
  | 2026-09-12__21-32-36 | 0.40 | 3,630,524 | 0.3637 |
  | 2026-09-21__20-31-31 | 0.40 | 4,332,197 | 0.3567 |
  | 2026-09-21__20-32-09 | 0.40 | 4,849,315 | 0.3515 |
  | 2026-09-22__20-46-23 | 0.40 | 4,342,222 | 0.3566 |

  Reward is flat at 0.4 across all 4 runs while total tokens drift upward (3.63M → 4.33M → 4.85M →
  4.34M) — **more tokens spent for identical pass/fail outcomes.** Under the scoring formula this
  is a pure (small: ~0.001–0.012 per run here) efficiency loss, not a capability loss. See §3.3 for
  the likely driver (rising output-tokens-per-turn on the timeout-prone tasks).

## 3. Failure-mode analysis, with trajectory reconstruction and code cross-reference

### 3.1 Failure-mode frequency table

| Failure mode | Trials | % of 40 | Tasks affected |
|---|---|---|---|
| `AgentTimeoutError` (900s wall clock, mid-`llm.chat()`) | 19 | 48% | chess-best-move (4/4), qemu-alpine-ssh (4/4), qemu-startup (4/4), regex-log (4/4), polyglot-c-py (3/4) |
| Declares `TASK_COMPLETE`, but a post-verification action invalidated the verified state (verify-then-mutate-without-reverify) | 5 | 12.5% | configure-git-webserver (4/4), polyglot-c-py (1/4) |
| Declares `TASK_COMPLETE` correctly, verified | 16 | 40% | build-cython-ext, fix-code-vulnerability, log-summary-date-ranges, sqlite-with-gcov (4/4 each) |
| `AGENT_MAX_TURNS` reached | 0 | 0% | none |
| Empty/reasoning-only response → nudge loop → timeout (the documented `troubleshooting.md` mode) | 0 confirmed | 0% | none — ruled out by direct message inspection |
| Other exceptions (infra, model API, OOM, etc.) | 0 | 0% | none observed |

Two failure modes account for the entire non-passing 60% of the dataset (24/40 trials), and both
are reconstructible in detail from the transcripts.

### 3.2 "Declares done, but a later action undoes the verification" (5 trials)

**`configure-git-webserver` — 4/4 trials, reward 0.0, `finished: true`, reproduced identically
across every run.**

Trajectory (from `jobs/2026-09-12__21-32-36/configure-git-webserver__WVo9Br3/result.json`
`agent_result.metadata.messages`, corroborated by the `trial.log` command list): the agent installs
`git`/`openssh-server`/`nginx`, creates a bare repo at `/git/server` with a `post-receive` hook
that checks out to `/var/www/html`, points nginx at port 8080, **and then actually verifies the
literal end-to-end flow**: generates a throwaway SSH keypair, clones, pushes a real
`hello.html`, and confirms `curl http://localhost:8080/hello.html` returns `hello world`. That is
genuine, non-trivial self-verification — better than the "declared done with no check" failure
mode this kind of analysis usually looks for.

Then, in the assistant turn quoted verbatim below (same message that goes on to say
`TASK_COMPLETE`), it cleans up its own test fixtures:

```
# Reset bare repo to empty so the user's flow starts clean
rm -rf /git/server
git init --bare /git/server >/dev/null 2>&1
...
# Remove test web content
rm -f /var/www/html/hello.html
```

`/var/www/html/hello.html` is **exactly** the file the task's verifier checks for. The agent never
re-ran its own end-to-end test after this cleanup step; it went straight to `TASK_COMPLETE`. The
real grader's `test-stdout.txt` confirms the resulting break directly:
`jobs/2026-09-12__21-32-36/configure-git-webserver__WVo9Br3/verifier/test-stdout.txt`:
`"❌ TEST FAILED: Web server returned HTTP 404"`. All 4 trials across all 4 job runs show the
identical `rm -f .../hello.html` cleanup step and the identical `HTTP 404` verifier failure
(`jobs/2026-09-21__20-31-31/configure-git-webserver__RvM3xEg/verifier/test-stdout.txt`,
`jobs/2026-09-21__20-32-09/configure-git-webserver__zG7Nnyd/verifier/test-stdout.txt`,
`jobs/2026-09-22__20-46-23/configure-git-webserver__Td7gFSf/verifier/test-stdout.txt` — all "1
failed", same assertion). This is fully deterministic given the prompt/model/temperature in these
runs, not a fluke.

**`polyglot-c-py`, 2026-09-22 run (`polyglot-c-py__QgLX6Ju`), reward 0.0, `finished: true`.** The
task asks for a single polyglot file at `/app/polyglot/main.py.c`. The agent's own last two
commands were `gcc /app/polyglot/main.py.c -o /app/polyglot/cmain && ...` (compiling to verify the
C path) followed by `ls -la /app/polyglot/; ... wc -l /app/polyglot/main.py.c` — and that final
`ls` output, **shown to the model in its own last observation**, lists both `main.py.c` and
`cmain`. The agent's closing message says "Single file check" but only checked `wc -l` of
`main.py.c`, not that `cmain` was absent, then emitted `TASK_COMPLETE`. The verifier
(`jobs/2026-09-22__20-46-23/polyglot-c-py__QgLX6Ju/verifier/test-stdout.txt`) fails on exactly
that: `AssertionError: Expected only main.py.c, found: ['main.py.c', 'cmain']`. The compiled
binary produced by the agent's own verification step was never cleaned up, and the model did not
notice the contradiction present in text it had just read.

**Code cross-reference:** nothing in `starter/agent/prompts.py`'s `SYSTEM_PROMPT` step 5
("VERIFY before finishing... If verification fails, fix it") requires the verification to be
*re-run after the last state-changing command*, and nothing checks that "clean up test artifacts"
doesn't remove artifacts the grader itself depends on. The loop in `agent.py` has no concept of
"has anything changed since the last successful verification" — it trusts whatever the model says
in the turn where it emits `TASK_COMPLETE`, with no independent check
(`agent.py`: `if action.kind == "done": finished = True; ... break`, no gate beyond the presence of
the `TASK_COMPLETE` string per `tools.py`'s `parse_action`).

### 3.3 `AgentTimeoutError` — wall-clock exhaustion, not turn-count exhaustion (19 trials)

All 19 timeouts raise inside `await llm.chat(messages)` (traceback frame `agent.py:145`, then
`llm.py:131`'s `self._client.chat.completions.create(...)` — see e.g.
`jobs/2026-09-12__21-32-36/chess-best-move__J5GJUXU/result.json`'s `exception_info` in full). The
agent was always mid-request for the *next* turn's response when the 900s ceiling hit — never
between turns, never inside `environment.exec()`.

Two distinguishable sub-patterns, both traceable to the same underlying driver
(per-turn output verbosity), found by comparing tokens-out-per-turn (`n_output_tokens / turns`,
computed per trial in §1) against the always-passing tasks:

- **Always-passing tasks** (`build-cython-ext`, `fix-code-vulnerability`, `log-summary-date-ranges`,
  `sqlite-with-gcov`) average **102–818 output tokens/turn** across all 16 trials.
- **Always/mostly-timing-out tasks** (`chess-best-move`, `qemu-alpine-ssh`, `qemu-startup`,
  `regex-log`, `polyglot-c-py`) average **1,216–10,993 output tokens/turn** — roughly 5–70× more
  verbose per turn, on tasks that are also, independently, harder (custom low-level parsing/engine
  work — below). **Higher verbosity does not correlate with more turns completed; it correlates
  with fewer** (`regex-log` timed out at 7–16 turns; `qemu-startup` at 13–42), because wall-clock
  time is spent on tokens generated, not turns executed.

**Sub-pattern A — genuinely hard tasks solved the slow way, and running out of time before
finishing.** `chess-best-move` (0/4, 100% timeout): with no `python-chess` installed and no
network (confirmed: `pip list` in-transcript shows only `pillow`/`pip`/`setuptools`/`wheel`;
`ModuleNotFoundError: No module named 'chess'` —
`jobs/2026-09-12__21-32-36/chess-best-move__J5GJUXU/result.json` messages), the agent manually
reverse-engineers the chess piece glyphs from a PNG via pixel sampling, then writes its own
minimax/move-generation engine from scratch inside the container. In the 2026-09-12 trial it gets
as far as a working engine producing scored candidate moves (`Top moves: c3d5: -1130, ...` — the
literal final tool-output message in the transcript) but the timeout fires before the model can
pick and submit a final answer. `qemu-startup`/`qemu-alpine-ssh` (both 4/4 timeout) show the same
shape against a different obstacle: no `mount`, `isoinfo`, `7z`, `bsdtar`, or `xorriso` available in
the container (`jobs/2026-09-21__20-31-31/qemu-startup__ejhPAAa/trial.log`: `which ... isoinfo 7z
bsdtar xorriso mount` returns nothing usable), so the agent hand-writes an ISO9660 volume-descriptor
parser in Python from raw `struct` reads, redoing near-identical byte-offset analysis across turns
14–18 of that trial before the run times out. This is a real task-difficulty/tooling problem, not
purely a prompting bug — see §4 for a generic (non-task-specific) mitigation.

**Sub-pattern B — a no-action nudge loop that consumes almost the entire time budget without ever
taking an action.** The clearest single piece of evidence in the whole dataset:
`jobs/2026-09-22__20-46-23/regex-log__3QLTNzm/result.json`. Full per-message trace (role, char
length, tag):

```
2  assistant 46096            Let me think carefully about this task. ...
3  user        266  [OBS]     exit code: 2 ... bash: -c: line 1: syntax error ...
4  assistant   131            The previous command failed because I pasted the raw regex...
5  user        153  [NUDGE]   Your last response contained no action. ...
6  assistant    87            ```bash ls -la /app/ && ...```
7  user        159  [OBS]     total 8 ...
8  assistant   133            The /app directory is empty. Let me create the regex file...
9  user        153  [NUDGE]
10 assistant 50079            Let me carefully think through the regex design. ...
11 user        153  [NUDGE]
12 assistant 30543            I need to stop overthinking and just write the file. ...
13 user        153  [NUDGE]
14 assistant 48906            I keep going in circles with my thinking and not actually pr[oducing action] ...
15 user        153  [NUDGE]
16 assistant 48861            I've been stuck in a loop of thinking without taking action. ...
17 user        153  [NUDGE]
```

Turns 10, 12, 14, and 16 are each 30,000–50,000-character single responses (order of ~8,000–13,000
tokens each, consistent with `n_output_tokens = 87,947` for this trial over only 8 assistant
turns), the model **explicitly narrates that it is stuck in a loop** ("I keep going in circles with
my thinking and not actually producing [action]"; "I've been stuck in a loop of thinking without
taking action"), and still fails to close a parseable ` ```bash ` fence, so `tools.parse_action()`
returns `Action(kind="none")` every time and `agent.py` appends the same generic `NUDGE_MESSAGE`
again. Five of this trial's eight turns are nudges; the model's self-diagnosis of the loop does not
help it exit the loop, because the nudge message it receives back is identical every time and gives
it no new constraint (e.g. "keep this response under N tokens" or "emit the code block first, then
explain"). The 900s budget is exhausted almost entirely on this unproductive exchange — real
progress (an actual regex written) never resumes after turn 3's failed attempt. `regex-log`'s other
3 trials show the same shape at smaller scale (1, 6, and 6 nudges out of 7–16 turns respectively;
`qemu-startup`'s 2026-09-22 trial: 5 nudges in only 13 turns). Across the 19 timeout trials, 13
(68%) have at least one nudge; the always-passing 16 trials average 0.95 nudges each versus 1.68 in
the timeouts — nudges are more than incidental to the timeout cluster.

**Rising verbosity across job runs, same task set, same reward.** Averaging output-tokens/turn for
the 5 timeout-prone tasks by job date: 2026-09-12 → ~1,977; 2026-09-21 (run a) → ~3,477; 2026-09-21
(run b) → ~4,050; 2026-09-22 → ~5,265 (computed from §1's `out/turn` column, task subset:
chess-best-move, qemu-alpine-ssh, qemu-startup, regex-log, polyglot-c-py). Reward on these 5 tasks
stayed at 0/4, 0/4, 0/4, 0/4 (except the one 2026-09-22 `finished:true` `polyglot-c-py`
already covered in §3.2) across all four dates — **more verbose, not more capable**, and the
per-job total-token totals in §2 drift upward in the same window. **This is an inference, not a
directly-observed cause**: the exact `LLM_MAX_TOKENS`/model/endpoint config for each of the 4 dated
runs isn't recorded in `result.json` (§0), so it can't be confirmed from these artifacts alone
whether this drift is a config change (e.g. `LLM_MAX_TOKENS` raised per
`starter/docs/uw_madison_endpoint.md`'s `8192` recommendation, between 2026-09-12 and 2026-09-21),
a model/endpoint change, or model-server-side nondeterminism. What *is* directly observed: whatever
changed, it made the wall-clock-timeout cluster more likely to burn its whole budget on fewer,
larger turns, not fewer, so if the intent was fixing the empty-response bug (§2, confirmed absent
in all 40 trials), it may have traded one `AgentTimeoutError` cause for another that isn't yet
written down in `starter/docs/troubleshooting.md`.

**Code cross-reference:**
- `starter/agent/llm.py`'s `chat()` sets `max_tokens=self.max_tokens` per call but has no
  awareness of remaining wall-clock budget for the *task* — every turn gets the same generation
  budget whether 2 minutes or 2 seconds are left before the 900s ceiling.
- `starter/agent/agent.py`'s loop bound is `AGENT_MAX_TURNS` (never binding here, §2) with no
  parallel wall-clock check; it has no way to detect "approaching the 900s ceiling" and react (e.g.
  by forcing a short, decisive final turn) because it never sees that ceiling — it's enforced
  entirely by Harbor's `asyncio.wait_for` outside the agent's own code
  (`.venv/lib/python3.12/site-packages/harbor/trial/trial.py:545`).
- `starter/agent/prompts.py`'s `NUDGE_MESSAGE` is a single fixed string with no escalation — after
  1 nudge or 5 consecutive nudges, the model receives the exact same 153-character text
  (`"Your last response contained no action. Respond with exactly one bash code block..."`),
  which the regex-log transcript shows is not sufficient to break a verbose-but-actionless loop
  once the model is already in it.
- `starter/agent/tools.py`'s `CODE_BLOCK_RE` requires a *closed* fence
  (`` ```(?:bash|sh|shell)?\s*\n(.*?)``` ``, non-greedy but still requires the closing `` ``` ``).
  A response that runs out of budget mid-code-block, or that discusses a command without ever
  opening a fence, produces `Action(kind="none")` with no partial credit and no distinction from "the
  model didn't try" — both look identical to `agent.py`.
- `starter/agent/tools.py`'s `MAX_OBSERVATION_CHARS` truncation is **not** a meaningful contributor
  to the timeout cluster: truncation counts are low-to-zero for the 5 timeout-prone tasks (§1,
  "truncations" column: 0–6, mostly 0–1) — the growth driver there is assistant-side generation
  verbosity, not tool-output volume. Truncation *is* a real, recurring cost on the largest
  always-passing task (`build-cython-ext`: 1–4 truncations every run, and by far the largest
  `n_input_tokens` in the dataset at up to 2.14M) — it just isn't what's causing the timeouts.

## 4. Cross-reference summary: which code behaviors contributed to which failures

| Code location | Behavior | Failure(s) it contributes to |
|---|---|---|
| `agent.py`: `if action.kind == "done": finished = True; ... break` | No independent re-verification gate before accepting `TASK_COMPLETE` | §3.2 (configure-git-webserver ×4, polyglot-c-py ×1) |
| `prompts.py`: `SYSTEM_PROMPT` step 5 | Tells the model to verify, but not to re-verify after subsequent state-changing actions, and not to check for extraneous artifacts | §3.2 |
| `prompts.py`: `NUDGE_MESSAGE` | Single fixed string, no escalation, no verbosity/format constraint | §3.3 sub-pattern B (regex-log, qemu-startup) |
| `tools.py`: `CODE_BLOCK_RE` / `parse_action` | Requires a fully closed fence; a truncated-mid-block or fence-less response is indistinguishable from "no attempt" | §3.3 sub-pattern B |
| `llm.py`: `chat()` `max_tokens` | Fixed per-turn budget, no awareness of remaining task wall-clock time | §3.3 (both sub-patterns) |
| `agent.py`: `MAX_TURNS` loop bound only | No wall-clock-aware stopping/escalation logic; the actual binding constraint (Harbor's 900s) is invisible to the agent | §3.3 (all 19 timeouts) |
| `tools.py`: `MAX_OBSERVATION_CHARS` truncation | Blunt but not implicated in any of the 24 non-passing trials' root cause; a token-cost factor on the largest passing task only | Not a failure driver here; a token-cost note only |
| `agent.py` / Harbor's `AgentTimeoutError` | 900s trial-level ceiling, `config.agent.override_timeout_sec: null` in every trial (not overridden) | §3.3 (all 19 timeouts) |

## 5. What the successful trajectories look like, for contrast

All 16 passing trials (4 tasks × 4 runs) show a real verify-then-declare pattern, e.g.
`jobs/2026-09-12__21-32-36/log-summary-date-ranges__dVUtf6r/result.json`'s last two assistant
turns: a `cat /app/summary.csv` to re-read the exact output file, followed only then by
`TASK_COMPLETE` with a note that "all counts were verified through independent cross-checks." These
tasks also have short, targeted outputs per turn (§1, `out/turn` 102–818) and few-to-no nudges.
This is direct evidence that the "verify by re-reading the actual output, right before declaring
done" pattern the `SYSTEM_PROMPT` already asks for **does work when the model follows it and stays
terse** — the failures in §3 are not evidence the instruction is wrong, they're evidence it isn't
being followed reliably (verify-then-mutate) or isn't achievable in the time budget (verbose
reasoning eating the clock before a first real verification is possible).

## 6. Evidence gaps (explicit)

- **Model identity per run is unrecorded.** `agent_info.model_info` and `config.agent.model_name`
  are `null` in every `result.json` sampled. The verbosity/reasoning-style evidence in §3.3 is
  consistent with a reasoning model but is inference from behavior, not a logged fact. Recommend
  writing the resolved model id into `context.metadata` each run (cheap, `llm.py` already has
  `self.model` at hand) so this stops being a gap.
- **No per-turn timestamps.** `result.json` has `started_at`/`finished_at` for the whole trial but
  nothing per-turn, so exact latency-per-turn (as opposed to tokens-per-turn, used as the proxy
  throughout §3.3) can't be reconstructed. This means the causal link "more output tokens → more
  wall-clock time → timeout" is a strong, consistent correlation across 19/19 timeout trials and
  matches the mechanism visible in the code (`llm.chat()` is a blocking generation call whose
  latency scales with tokens generated), but it is not a directly measured latency number.
  `agent.py` could log a timestamp per turn into `context.metadata` cheaply to close this gap.
- **Only 4 job runs, 10 tasks each.** This is the entire `./jobs/` history in this repo — good for
  "these 10 tasks, reproducibly" claims (the per-task pass/fail pattern is identical in all 4 runs,
  which is unusually clean signal), but it says nothing about the other 79 tasks in the full
  Terminal-Bench 2.0 set, and `starter/eval/public_subset.txt` is still 3 placeholder task names
  per `starter/CLAUDE.md` — there is no evidence here about the official public-subset or
  full-89-task score.
- **`starter/.env`/`.env.op` not read** (credential file, out of scope) — exact `LLM_MAX_TOKENS`,
  `LLM_TEMPERATURE`, `AGENT_COMMAND_TIMEOUT_SEC` values in effect for these 4 runs are unconfirmed;
  defaults from `starter/agent/llm.py`/`agent.py` are cited only as fallback-if-unset, not as what
  necessarily ran.
- **No non-timeout, non-verify exceptions observed.** Can't say anything from these artifacts about
  robustness to model-API errors, network blips, or Docker failures — none occurred in this
  sample.

## 7. Prioritized harness improvements, tied to observed failures

Ordered by (evidence strength × frequency addressed) ÷ (implementation + token cost). Each ties
back to a §3 finding. All recommendations are generic behavior changes to the loop/prompts/parsing
— none is task-specific (per the competition's no-hardcoding rule); none proposes reading task
names or branching on them.

1. **Completion guard: require a fresh, literal re-check of the acceptance-relevant state
   immediately before `TASK_COMPLETE`, and flag if any state-changing command ran since the last
   verification.** Directly fixes §3.2's entire failure class (5/40 trials, 100% reproducible
   across job runs on `configure-git-webserver`, plus the `polyglot-c-py` case). This is
   low-token-cost if implemented as a deterministic check ("was there a
   state-changing command after the last command whose output the closing message cites as
   verification?") rather than an extra LLM call — a code-level or prompt-level gate, not a second
   model round-trip. This is exactly `starter/plan_docs/context_management/design.md` §27
   ("Completion guard" — "Verification must have occurred after the latest relevant code,
   dependency, build, or environment change") and Phase 4's "completion guard v1" in that plan's
   roadmap (`starter/plan_docs/context_management/roadmap.md`, Phase 4, currently `proposed`, not
   implemented on this branch). **This finding is direct, concrete confirming evidence for that
   already-designed phase** — the analysis in this document independently arrived at the same gap
   from live trial data before knowing the plan called it out.

2. **Wall-clock-aware turn budget, not just a turn-count ceiling.** Directly addresses §3.3 (19/40
   trials, 48% of all trials, the single largest failure mode). `AGENT_MAX_TURNS` is proven inert
   in this dataset (§2) — the real constraint is Harbor's 900s wall clock, which the agent cannot
   currently see. Concretely: track elapsed time since `run()` started (`time.monotonic()`, trivial
   to add to `agent.py`), and once a configurable fraction of the ~900s budget is used, inject a
   `design.md` §25-style message ("You are approaching the time budget. Stop exploratory work,
   identify the shortest safe path to the acceptance criteria, and verify+submit."). Token cost:
   near zero (one short injected message near the end of a run that would otherwise time out
   anyway with zero reward) against a potential fix for up to 48% of trials — the best cost/benefit
   ratio of anything in this list. This directly extends `design.md` §25 ("Turn and progress
   feedback"), which as currently drafted budgets by *turn count*; the evidence here (§3.3, out/turn
   varying 5–70× across tasks) says turn count is a poor proxy for what's actually being exhausted
   and the design should budget by **time or cumulative output tokens**, not turns, in this loop.

3. **A generic per-turn output-length ceiling (or a "answer first, explain after" structural
   nudge) to stop the no-action verbose-reasoning loop.** Directly addresses §3.3 sub-pattern B —
   the `regex-log` transcript where the model narrates its own stuck loop for 4 consecutive
   30–50K-character turns without ever closing a bash fence. A generic (non-task-specific) fix:
   lower `LLM_MAX_TOKENS` for the *nudge retry* specifically (forces a short, action-first
   response instead of another full reasoning pass), or change `NUDGE_MESSAGE` to require the code
   block as the literal first line of the reply. This is squarely
   `starter/plan_docs/context_management/design.md` §26 ("No-progress detection" — "target[ed]
   message describing the specific pattern" instead of a generic nudge) and Phase 2
   (`02-loop-controls.md`, currently `proposed`) — but note Phase 2's drafted scope (repeated
   commands, consecutive read-only actions) **does not currently list "consecutive no-action
   nudges" as one of its detected patterns**; this analysis's evidence (68% of timeout trials have
   ≥1 nudge, vs 95% nudge rate difference between timeout and passing trials) argues it should be
   added to that phase's scope before it's speced further. Token cost: this one is closer to net
   *token-saving* than token-costing — a run stuck in this loop is already spending the most tokens
   in the whole dataset (regex-log: 87,947 output tokens in just 8 turns) for zero reward; cutting
   it off earlier both raises pass probability and lowers cost.

4. **Context/history management (summarization, raw/active separation) for the small number of
   very-long, already-passing tasks.** `build-cython-ext` is the only task in this dataset where
   `MAX_OBSERVATION_CHARS` truncation is a repeat, multi-trial pattern (§3.3's last row) and where
   `n_input_tokens` reaches into the millions (up to 2.14M in one trial) purely from resending
   growing history every turn. This is real but **lower priority than items 1–3**: it doesn't
   explain any of the 24 non-passing trials in this dataset (build-cython-ext passes 4/4 despite
   the cost), so by this evidence it's a token-cost lever, not a capability lever — consistent with
   the competition scoring formula weighting capability far above the `0.01×tokens/1M` token term,
   and with `starter/plan_docs/context_management/roadmap.md`'s own Gate G2 logic ("measure...
   proceed only if runs still fail or lose meaningful score because of context growth... *and* the
   token pricing shows the remaining cost is worth it"). This document's evidence doesn't clear
   that gate on its own — the failures here are dominated by items 1–3, not context overflow. This
   is exactly the kind of finding Gate G2 was designed to require before committing to Phase 5
   (`starter/plan_docs/context_management/decisions.md`, DEC-004/DEC-007): on this evidence, Tier A
   deterministic work (Phases 1–4, especially the completion guard and loop controls above) looks
   like it would resolve most of what's currently failing, and Phase 5 (semantic
   compaction/retrieval, an extra LLM call) is not yet justified by this dataset.

5. **Generic environment-capability bootstrap in `setup()`, sized to the task's evident needs, not
   named per-task.** §3.3 sub-pattern A (chess-best-move, qemu-alpine-ssh, qemu-startup) shows the
   agent hand-rolling low-level parsers/engines because common tools aren't present (no
   `python-chess`, no `mount`/`isoinfo`/`xorriso`/`7z`, no network). `BaselineAgent.setup()`
   currently does nothing (`starter/agent/agent.py`: `async def setup(...): pass`). A generic,
   best-effort `apt-get install`/`pip install` of a broad, task-agnostic toolset (archive/ISO
   tools, common Python libraries) in `setup()` — never conditioned on task name or instruction
   text — could shortcut some of this manual reverse-engineering without violating the
   no-task-specific-hardcoding rule. Lower confidence than items 1–3: it's not certain these tools
   would be installable in the finale environment (`starter/docs/safety.md`/`agent.py`'s own
   docstring warns finale tasks may have no network), so this is offered as worth investigating,
   not as a confirmed fix — and even with tools available, chess-best-move's core difficulty
   (deriving the position from an image, then finding a decisive move) may not shrink much. Token
   cost: a few setup-time exec calls per task, likely small relative to the 48% timeout rate it
   might partly address.

### Not recommended based on this evidence

- **Do not prioritize LLM_MAX_TOKENS reduction as a blanket fix.** It would suppress §3.3's
  verbosity problem but at the cost of risking the *other* documented failure mode
  (`troubleshooting.md`'s empty-response/`reasoning_content` fallback loop), which is currently at
  0/40 in this dataset — trading a 48%-frequency problem for reintroducing a 0%-frequency one is
  not obviously an improvement without re-measuring. Item 3 (per-turn ceiling scoped to the nudge
  retry only) gets a similar benefit with less of that risk.
- **Do not treat `AGENT_MAX_TURNS` as a lever at all** until wall-clock is addressed — this
  dataset's evidence (§2) is that it is never the binding constraint, so raising or lowering it
  would have no measurable effect on any of these 40 trials.

## 8. Overlap with `starter/plan_docs/context_management/`

That plan (present at `HEAD` on this branch, commit `1c258e3`; deleted in the current working tree
per this session's `git status`; further developed on a different branch, `harness/context`, not
yet merged here) already scopes most of the highest-value items above:

- Its Phase 4 ("deterministic task state and completion guard v1",
  `starter/plan_docs/context_management/phases/04-deterministic-state.md` per its roadmap entry)
  and `design.md` §27 already design item 1 above (the completion guard). This document adds
  concrete trial evidence (§3.2) motivating it, beyond the plan's own rationale.
- Its Phase 2 ("state-free loop controls",
  `starter/plan_docs/context_management/phases/02-loop-controls.md`) already designs most of item 3
  above (targeted, pattern-specific messages instead of the generic `NUDGE_MESSAGE`), but its
  drafted scope list (repeated commands, consecutive read-only actions) doesn't yet name
  "consecutive no-action/nudge" as a detected pattern — this document's evidence (§3.3) says it
  should.
- `design.md` §25 ("Turn and progress feedback") already designs a version of item 2, but budgets
  by **turn count** ("Turn: 18/30"); this document's evidence (§3.3: output-tokens-per-turn varies
  5–70× across tasks, and `AGENT_MAX_TURNS` is never hit while wall-clock is hit 48% of the time)
  argues that budget should be **time- or token-based**, not turn-based, for this specific loop.
- Item 4 (context/history compaction, the plan's main subject) is explicitly gated behind
  Gate G2 in the plan's own `roadmap.md`, and this document's evidence is consistent with that gate
  not yet being cleared — the observed failures are dominated by completion-guard and loop-control
  gaps (items 1–3), not by context overflow or forgotten details, in this 40-trial sample.
- No file in this analysis was modified, and no plan file was restored — the working-tree deletion
  of `starter/plan_docs/context_management/` is left exactly as found; this document reads the
  git-historical version only for cross-reference.
