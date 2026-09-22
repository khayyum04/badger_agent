# Handoff ledger — Context Management

Every phase runs in a fresh session, so this file is how one phase tells the next what exists and
what to reuse. It is imported into every session. **The source code is the ground truth**; this
file is the map plus the intent. If they disagree, fix one of them in the same change.

## Rules for editing

- The session that **finishes** a phase updates this file before closing. Verify every symbol with `grep` first; never write it from memory.
- Update rows, don't delete them. A removed symbol is marked `removed` with the reason.
- This is a map, not a narrative: signature, location, one-line purpose. Rationale belongs in `decisions.md`, scope in the phase spec.
- Names in `planned` rows are draft names taken from `design.md` pseudocode. The implementing phase may rename, but must update the row so later phases don't guess.
- Module layout is by **responsibility, never by phase** (no `phase3_utils.py`). Phase 1 decides the layout and records it under *Code map*.

## Existing symbols to extend, not duplicate (baseline, before Phase 1)

| Symbol (in `starter/agent/`) | Touched by | Instruction |
|---|---|---|
| `tools.Action` — `kind` is `"shell"`, `"done"` or `"none"`; `command` | 1, 2, 4 | Extend it. Do not add a second action type. `design.md` §6's `complete` / `invalid` mean `done` / `none`. |
| `tools.parse_action(text) -> Action` | 1 | Reuse as-is. Canonicalization builds on its result. |
| `tools.run_shell(environment, command, timeout_sec) -> ShellResult` | 1, 3 | **Implemented by Phase 1** (`starter/agent/tools.py`): now returns a structured `ShellResult` instead of a formatted string; string formatting moved to `prompts.observation_message`. Phase 3 extends **this function** (output capture + offload) — do not add `run_shell_with_output_capture` beside it. |
| `tools._truncate(text) -> tuple[str, bool]` | 1, 3 | **Signature changed by Phase 1** (`starter/agent/tools.py`): now returns `(text, was_truncated)` instead of `str`, so `run_shell` can populate `ShellResult.truncated`; the truncation algorithm itself (first/last half, 6000-char limit) is unchanged (DEC-021). Phase 3 replaces this with preview/offload logic. Don't keep both paths. |
| `MAX_OBSERVATION_CHARS` (per-stream, 6000) | 3 | Unchanged by Phase 1 (DEC-021). Phase 3 replaces this with preview/offload logic. |
| `prompts.observation_message(observation)` | 1 | **Signature changed by Phase 1** (`starter/agent/prompts.py`): now takes a `tools.ShellResult` or `events.ObservationEvent` (duck-typed on matching field names) instead of a preformatted string, and does the exit-code/stdout/stderr formatting itself. Still the single renderer of an observation for the model — keep it single. |
| `prompts.NUDGE_MESSAGE` (generic) | 2 | Phase 2's targeted messages supersede the generic one. Mirrored in `scripts/build_dashboard.py`; change together. |
| `agent.BaselineAgent.run` loop, `messages` list | 1 | **Implemented by Phase 1** (`starter/agent/agent.py`): the plain `messages` list is replaced by a `raw_events` list (owned by `run()`, built through `context.py`'s functions) plus a `next_event_id` counter and a `telemetry` list. `context.metadata` keys `turns`, `finished`, `messages` (now the serialized raw event history, DEC-012), `telemetry` (DEC-024), `system_prompt`/`instruction` (DEC-032) are read by `scripts/build_dashboard.py`. |
| `llm.LLMClient.chat(messages) -> (text, usage)` | 1, 5 | `usage` gives total prompt/completion tokens only *after* a call. Phase 5's compaction call reuses this client; no second client. |

## Interface ledger (planned → implemented)

`Status`: `planned` → `implemented` (fill `Location`) → `removed`. "Reused by" lists phases that must
call it instead of writing their own.

| Symbol (draft name) | Owner | Reused by | Status | Location | Purpose |
|---|---|---|---|---|---|
| Measurement command + baseline numbers | 0 | every phase | implemented | `handoff.md` → Measurement protocol; baseline jobs `jobs/2026-09-12__21-32-36`, `jobs/2026-09-21__20-31-31`, `jobs/2026-09-21__20-32-09` (local) | The protocol each phase re-runs; where baseline results live (see *Measurement protocol*). |
| `events.Event`, `events.AssistantActionEvent`, `events.ObservationEvent` (§6) | 1 | 2, 3, 4, 5 | implemented | `starter/agent/events.py` | Structured raw events; built on `Action` and `tools.ShellResult`. Field sets trimmed to only what Phase 1 populates (DEC-022) — no `token_count`/`tags` on `Event`, no timing/`full_output_path` on `ObservationEvent`. `event_type` (`"assistant_action"`/`"observation"`) is the JSON discriminator, defaulted on each subclass. |
| Append-only raw history (design: `raw_events`) | 1 | 2, 3, 4, 5 | implemented | `starter/agent/agent.py::BaselineAgent.run` (local `raw_events: list[Event]`) | The audit record; serialized via `dataclasses.asdict` into `context.metadata["messages"]` every time it changes (DEC-012, DEC-031). |
| `tools.ShellResult` | 1 | 3, 4 | implemented | `starter/agent/tools.py` | exit code (`int \| None`), stdout, stderr, `original_stdout_chars`/`original_stderr_chars`, `truncated`, `did_not_complete`, `error`, `command`. Replaces the formatted-string return of `run_shell` (DEC-025, DEC-029). |
| `context.canonicalize_action(action) -> str` (§7) | 1 | 5 | implemented | `starter/agent/context.py` | Canonical form of one action, behind `AGENT_CANONICALIZE` (default on, DEC-018). `""` for `"none"`-kind actions (DEC-028). |
| `context.record_observation(shell_result, turn, event_id) -> ObservationEvent` | 1 | 3, 4 | implemented | `starter/agent/context.py` | Not in the original planned-rows list — added by DEC-025 (needs `shell_result.command`) and DEC-030 (needs an explicit `event_id`, since `Event.id` is a caller-supplied counter, not derived from list length — DEC-027). |
| `count_tokens(...)` (name TBD) | 1 | 2, 4, 5 | **not built this phase (DEC-015)** | — | No local tokenizer. Per-turn telemetry uses the endpoint's exact `usage.prompt_tokens` instead of any per-component estimate. Unowned until a phase actually needs enforced per-component budgets. |
| `context.select_recent_events(events, max_pairs) -> list[Event]` (§13) | 1 | 5 | implemented | `starter/agent/context.py` | Signature is pair-count-based, not `(events, token_budget, count_tokens)` — token-bounded selection is deferred (DEC-015). Walks backward; a pair is a `"shell"`-kind action immediately followed by its observation; `"none"`-kind actions are invisible to it (DEC-026). Default `max_pairs` is 6, via `AGENT_RECENT_WINDOW_PAIRS` (DEC-014). |
| `context.build_active_context(system_prompt, instruction, raw_events, config) -> list[dict]` (§23) | 1 | 2, 4, 5 | implemented | `starter/agent/context.py` | Signature differs from design §23's pseudocode (no `task_state`/`retrieval_query`/`budgets` — out of scope this phase, DEC-023). The only place the model-facing message list is built. Appends a trailing nudge (raw response + `NUDGE_MESSAGE`) when the last raw event is a `"none"`-kind action (DEC-026), outside the window budget. Later phases add **slots** to it (loop feedback, task state, retrieved evidence), never a second builder. |
| `context.record_turn_telemetry(turn, sent_input_tokens) -> dict` (§29) | 1 | 2, 3, 4, 5 | implemented | `starter/agent/context.py` | Returns `{"turn": int, "sent_input_tokens": int}` (DEC-024); `agent.py` appends each turn's record to a `telemetry` list written to `context.metadata["telemetry"]`. Later phases add fields to each record, not writers. |
| `context.ContextConfig` / `context.load_context_config()` (§34) | 1 | 2, 3, 4, 5 | implemented | `starter/agent/context.py` | Two fields only this phase (DEC-023): `canonicalize: bool` (`AGENT_CANONICALIZE`), `recent_window_pairs: int` (`AGENT_RECENT_WINDOW_PAIRS`). Each later phase adds its own field to this same object. |
| Test scaffolding: fake `environment`, fake LLM client, event builders | 1 | 2, 3, 4, 5 | **cut from scope (DEC-020)** | — | No pytest, no `starter/tests/`, no fakes shipped. Verification was ad hoc (scratchpad-only scripts, not committed) plus Gate G1's harbor-run protocol. A later phase that wants unit tests starts from scratch. |
| `action_may_modify_state(command) -> bool` (§19 calls it `action_may_modify_repository_or_environment`) | 2 | 4, 5 | planned | — | Generic, conservative "might change repo/env" classifier. One classifier, one name. |
| Repeat / consecutive-read-only detectors | 2 | 5 | planned | — | Signals computed from events alone. |
| Loop-feedback message builders | 2 | 4 | planned | — | Injected through Phase 1's context-manager slot; Phase 4's guard rejections reuse the same path. |
| Extended `tools.run_shell` (output capture + offload) | 3 | 4, 5 | planned | — | Same function as today, not a new one. |
| Failure-preview extractor (name TBD) | 3 | 4 | planned | — | Finds "the error" in output generically; Phase 4's current-failure record reuses it. |
| Offload metadata on `ObservationEvent` (`full_output_path`, sizes) | 3 | 4, 5 | planned | — | Pointers to full output kept in the container. |
| `TaskState` + deterministic-subset records (§10) | 4 | 5 | planned | — | Phase 5 **extends** this; it does not introduce a second state type. |
| `deterministically_update_state(...)` | 4 | 5 | planned | — | Updates state from an action/observation pair. |
| `verification_may_be_stale` + invalidation v1 (§19) | 4 | 5 | planned | — | Uses Phase 2's classifier. |
| `validate_completion(task_state)` guard v1 (§27) | 4 | 5 | planned | — | Phase 5's per-criterion guard upgrades this. |
| State renderer for active context | 4 | 5 | planned | — | Fills the task-state slot in `build_active_context`. |
| `should_compact`, `split_compactable_events`, `update_compact_state`, `validate_compact_state` (§14–§18) | 5 | — | planned | — | Conditional on Gate G2. |

## Implemented code map

Filled in by the session that completes each phase: new/changed files, public functions with
signatures, config flags and env vars, telemetry fields, tests and fixtures added, and how to run
the tests. Format per phase:

```
### Phase N — <title> (issue #M, completed YYYY-MM-DD)
- Files: ...
- Public symbols: `name(sig)` — purpose
- Flags / env: ...
- Telemetry fields added: ...
- Tests: where, how to run, fixtures other phases can reuse
```

### Phase 1 — Separate raw history from active context; canonicalize actions (issue #2, implemented 2026-09-22; Gate G1 run 2026-09-22 — **known regression accepted, not fixed this phase**, see *Gate G1 results* below and *Notes for the next phase*)

- Files: `starter/agent/events.py` (new), `starter/agent/context.py` (new), `starter/agent/tools.py`
  (changed: `ShellResult`, `run_shell`, `_truncate`), `starter/agent/prompts.py` (changed:
  `observation_message`), `starter/agent/agent.py` (changed: `run()` loop), `starter/scripts/build_dashboard.py`
  (changed: new `classify_events`/`build_trial_record` read the raw-event shape; `classify_messages`/
  `parse_observation` are **kept**, not removed — `build_trial_record` detects which shape a job has
  (`"event_type"` present on the first message or not) and dispatches to the matching one, so
  pre-Phase-1 job directories, including the baseline-of-record jobs, still render), `starter/.env.example`
  (documented the two new flags).
- Public symbols: see the interface ledger above for full signatures — `events.Event`/
  `AssistantActionEvent`/`ObservationEvent`; `tools.ShellResult`; `context.canonicalize_action`,
  `context.select_recent_events`, `context.build_active_context`, `context.record_observation`,
  `context.record_turn_telemetry`, `context.ContextConfig`/`load_context_config`.
- Flags / env: `AGENT_CANONICALIZE` (bool-ish: `0`/`false`/`no`/`off` are falsy, anything else
  including unset is truthy; default on), `AGENT_RECENT_WINDOW_PAIRS` (int, default `6`).
- Telemetry fields added: `context.metadata["telemetry"]` — list of `{"turn": int,
  "sent_input_tokens": int}`, one per turn (DEC-024).
- Other `context.metadata` changes: `"messages"` is now the serialized raw event history (list of
  `dataclasses.asdict(event)`, DEC-012) instead of an OpenAI-format message list; two new keys,
  `"system_prompt"` and `"instruction"`, hold the static per-run strings so `build_dashboard.py`
  doesn't lose task visibility (DEC-032, a deviation from DEC-012's literal scope — see *Deviations*
  below).
- Tests: none (DEC-020 cut test scaffolding from this phase's scope). Verification was ad hoc:
  scratchpad-only smoke scripts (not committed) exercising `canonicalize_action`,
  `select_recent_events`'s pairing/windowing invariant, `build_active_context`'s canonicalize
  on/off and trailing-nudge behavior, `record_observation`'s `did_not_complete` branch, a full
  mocked `BaselineAgent.run()` loop (fake environment/LLM, no Docker), `build_dashboard.py` against
  a synthetic Phase-1-shaped `result.json`, and — added after a mean-review pass caught the
  backward-compat regression noted below — `build_dashboard.py` re-run against all three real
  baseline-of-record job directories to confirm zero messages fall through to the `"other"`
  fallback. None of this is reusable by a later phase — it was throwaway, per DEC-020's note that a
  later phase wanting tests starts from scratch.

#### Gate G1 results (run 2026-09-22)

Two harbor runs of the Phase 1 agent on `terminal-bench-sample@2.0`, same settings as the Phase 0
baseline (`qwen3.8-27b`, `LLM_MAX_TOKENS=8192`, `N_CONCURRENT=4`, `AGENT_RECENT_WINDOW_PAIRS=6`
default): `jobs/phase1-canon-on` (`AGENT_CANONICALIZE` default/on) and `jobs/phase1-canon-off`
(`AGENT_CANONICALIZE=off`).

**Tokens: a clean, large win.** `canon-on`: 1,807,782 total tokens (≈58% below the baseline's
~4.27M mean). `canon-off`: 2,879,681 (≈33% below). Both clear the noise rule's ~30% threshold by a
wide margin — this is a real reduction, not noise, and is exactly Phase 1's intended effect.

**Completion rate: does not clear Gate G1's "no unexplained regression" bar.**

| task | baseline (3/3) | canon-on | canon-off |
|---|---|---|---|
| `build-cython-ext` | PASS | **FAIL** | **FAIL** |
| `fix-code-vulnerability` | PASS | **FAIL** | **FAIL** |
| `configure-git-webserver` | FAIL | PASS | FAIL |
| `regex-log` | FAIL | PASS | FAIL |
| `log-summary-date-ranges`, `sqlite-with-gcov` | PASS | PASS | PASS |
| `chess-best-move`, `polyglot-c-py`, `qemu-alpine-ssh`, `qemu-startup` | FAIL | FAIL | FAIL |

`canon-on`'s aggregate pass rate (4/10) matches the baseline by coincidence — it is 2 regressions
offset by 2 unrelated improvements, not "no change." `canon-off` is a clear net regression (2/10 vs.
the baseline's 4/10).

**Root cause, investigated (not just asserted):** `build-cython-ext` and `fix-code-vulnerability`
regressed in *both* variants, which rules out canonicalization as the cause — it is the windowing
itself. Both were the most reliable baseline tasks (`finished=True` every time, in 56–87 and 25–33
turns respectively). In all four Phase 1 failing trials, `finished=False` and the trial ran to
either the 100-turn cap or the 900s wall-clock cap without ever reaching `TASK_COMPLETE`. Per-turn
wall-clock latency did **not** get worse (`build-cython-ext`: ~10.1s/turn baseline vs. ~9.3s/turn
canon-on; `fix-code-vulnerability`: ~4.8–13.6s/turn baseline vs. ~5.9–6.5s/turn Phase 1, actually
faster) — the trials simply needed far more turns to reach the same conclusion, and for
`fix-code-vulnerability` specifically hit the 100-turn cap with 250–300+ seconds of wall-clock
budget still unused. Reading the transcript tails (`build_dashboard.py`) shows no obvious infinite
loop — both trials are still doing plausible exploratory/verification work at the cutoff (re-reading
diffs, re-checking imports, re-running tests), consistent with re-discovering things a longer-running
task would have found earlier and then lost once they aged out of the 6-pair recent window. This
matches **DEC-014's own predicted, accepted gap** (early-context loss, no mitigation this phase) —
Gate G1 has now turned that from a theoretical risk into a measured one.

**Disposition (owner's decision 2026-09-22): accept and document, do not tune `AGENT_RECENT_WINDOW_PAIRS`
or re-run further this phase.** Phase 1 ships with this regression as a known, root-caused
limitation rather than spending more measurement budget on it now — see DEC-033. `roadmap.md` keeps
Phase 1 at `implementing`, not `completed`, until this is resolved (by Phase 4's task state or
Phase 5, per the roadmap's own structure) or explicitly accepted as shippable by the owner at
submission time.

**Noise-rule note:** the formal protocol (`handoff.md` §5) calls for a same-config re-run to rule out
a one-off before concluding a flipped task is a real regression. That confirmation re-run was not
done — the decision to accept without further measurement was made on the strength of the same two
tasks failing identically (never finishing, same failure shape) across *two independent Phase 1
variants*, against a 3/3-stable baseline, which was judged sufficient corroboration without a third
run of the same config.

## Measurement protocol

Written by Phase 0: the exact command, task set, repeats, token-counting method, and where baseline
numbers live. Every later phase re-runs it and posts the comparison in its issue.

### 1. Baseline of record

Three runs of the unmodified `BaselineAgent` on `terminal-bench-sample@2.0`:

| Job directory | Role | Concurrency | Pass rate | Total tokens |
|---|---|---|---|---|
| `jobs/2026-09-12__21-32-36` | original | inferred 4 | 4/10 | 3,630,524 |
| `jobs/2026-09-21__20-31-31` | repeat A | **actual 8** (see Deviation) | 4/10 | 4,332,197 |
| `jobs/2026-09-21__20-32-09` | repeat B | **actual 8** (see Deviation) | 4/10 | 4,849,315 |

**Deviation — repeats A and B ran concurrently with each other, not sequentially.** Both were
intended as independent `-n 4` runs, one after another. Instead, repeat A started 2026-09-21
20:31:32 and repeat B started 20:32:09 (38 s later); both ran until about 21:02. They overlapped
almost completely, so the real load was 8 concurrent trials for nearly the whole duration, not the
4 the protocol calls for (DEC-009). Consequence: the identical-pass/fail finding below is not
weakened by this (if anything it is a harder test, since it held under double load), but the three
token totals are not independent samples under matched conditions and should not be averaged into
a single "typical" figure without that caveat.

| Fact | Value | Status |
|---|---|---|
| Job directories | see table above (repo-root `jobs/`; gitignored; hold raw transcripts, so never commit or upload them: `starter/docs/safety.md`) | verified |
| Dataset and tasks | `terminal-bench-sample@2.0`: `build-cython-ext`, `chess-best-move`, `configure-git-webserver`, `fix-code-vulnerability`, `log-summary-date-ranges`, `polyglot-c-py`, `qemu-alpine-ssh`, `qemu-startup`, `regex-log`, `sqlite-with-gcov` | verified (10 trials in each job) |
| Agent | unmodified `BaselineAgent`. `starter/agent/*.py` are identical to commit `754f792` (2026-07-15) for all three runs | verified 2026-09-21 |
| Per-task agent timeout | 900 s, set by Harbor per task | verified (`AgentTimeoutError` message) |
| Model | `qwen3.8-27b` on the hosted gateway | owner's recollection for the original run; matches `LLM_MODEL` in `.env.op.example`; deliberately unchanged for the two repeats |
| Agent settings | `LLM_MAX_TOKENS=8192`, `LLM_TEMPERATURE` unset (0.2), `AGENT_MAX_TURNS` unset (100), `AGENT_COMMAND_TIMEOUT_SEC` unset (60) | **reconstructed** for the original run; unchanged and intentional for the two repeats |
| Concurrency, original run | unrecorded; treated as 4 | **inferred** |
| Concurrency, repeats A and B | `N_CONCURRENT=4` each, but overlapped (see Deviation above) | **measured** |

**Task-level finding across all three runs:** the same 4 tasks pass and the same 6 fail every
time — `build-cython-ext`, `fix-code-vulnerability`, `log-summary-date-ranges`, `sqlite-with-gcov`
always pass; `chess-best-move`, `configure-git-webserver`, `polyglot-c-py`, `qemu-alpine-ssh`,
`qemu-startup`, `regex-log` always fail. No flaky task observed in 3 runs, including one pair run
under double the intended concurrency.

### 2. Re-run command

From the repo root, venv activated, Docker running:

```bash
grep '^LLM_MODEL' starter/.env.op                                   # expect qwen3.8-27b
grep -c -E '^(LLM_BASE_URL|LLM_MODEL|LLM_API_KEY)=' starter/.env     # expect 0 (prints a count, not values)
grep '^LLM_MAX_TOKENS' starter/.env                                  # expect 8192

N_CONCURRENT=4 caffeinate -i op run --env-file=starter/.env.op -- \
  ./starter/scripts/run_baseline.sh "" --job-name <label> -o "$PWD/jobs"
```

- `N_CONCURRENT=4` must be explicit: the script defaults to 1, Harbor to 4, and the baseline was (probably) Harbor's default.
- The empty `""` is required: the script treats its first argument as a task name, so a flag there would become `-i --job-name`.
- `-o "$PWD/jobs"` must be absolute: the script `cd`s to `starter/`, so a relative path would land in `starter/jobs/`, away from the baseline.
- `caffeinate -i` (macOS) stops sleep from ending a run; drop it elsewhere.
- Expect about 30 minutes. Do not change `LLM_TEMPERATURE`, `AGENT_*`, the model, or `-n` between the baseline and a gate run.
- The script passes the deprecated `--agent-import-path`; Harbor 0.22 still accepts it and only warns. The baseline used `--agent agent.agent:BaselineAgent`. They are expected to load the same agent; this has not been run-verified.
- **Run one job at a time.** Two of the three baseline runs overlapped for their full ~30 minutes (see Deviation above). Don't repeat that: start one `harbor run`, wait for it to finish, then start the next.

### 3. Derived numbers

`JOB` is a job directory. Each snippet is run once per job directory and gives 10 rows.

Per-task table (task, reward, turns, input tokens, output tokens, exception):

```bash
for f in "$JOB"/*/result.json; do
  jq -r '[.task_name, (.verifier_result.rewards.reward // "n/a"), .agent_result.metadata.turns,
          .agent_result.n_input_tokens, .agent_result.n_output_tokens,
          (.exception_info.exception_type // "none")] | @tsv' "$f"
done | column -t
```

Totals, pass rate and score penalty (`penalty_89_tasks` is an order-of-magnitude estimate only —
always read it next to the "without heaviest" figure):

```bash
jq -s '
  [.[] | (.agent_result.n_input_tokens // 0) + (.agent_result.n_output_tokens // 0)] as $t
  | ($t | sort) as $s
  | { n_trials: length,
      pass_rate: (([.[] | .verifier_result.rewards.reward // 0] | add) / length),
      total_tokens: ($t | add),
      penalty_this_run: (($t | add) / 1e6 * 0.01),
      penalty_89_tasks: (($t | add) / length * 89 / 1e6 * 0.01),
      penalty_89_tasks_without_heaviest: (($s[:-1] | add) / (length - 1) * 89 / 1e6 * 0.01) }
' "$JOB"/*/result.json
```

Scale for reading the penalty: one task is worth 1/89 = 0.0112 points and 1M tokens costs 0.01, so
1M tokens is about 0.9 of a task. This is the number Gate G2 uses.

Estimated peak context per trial (an estimate: assumes tokens per character is constant within a
trial, so treat it as roughly ±20%):

```bash
for f in "$JOB"/*/result.json; do
  jq -r '
    .agent_result.metadata.messages as $m
    | [range(0; $m|length) | select($m[.].role=="assistant")] as $idx
    | [ $idx[] as $i | ([$m[0:$i][] | (.content|length)] | add) ] as $chars
    | ($chars|add) as $sum
    | [.task_name, ($chars|length), .agent_result.n_input_tokens, (($chars|last)|tostring),
       ((.agent_result.n_input_tokens / $sum * 1000 | round)/1000),
       ((($chars|last) * .agent_result.n_input_tokens / $sum) | round)] | @tsv' "$f"
done | sort -k6 -n -r | column -t
```

### 4. Failure-cause labels

Procedure, for each trial with reward 0:

1. `AgentTimeoutError` in `exception_info` means a timeout candidate. Otherwise, if `metadata.finished` is true, it is a wrong final answer: read `<trial>/verifier/test-stdout.txt` for the failing assertion.
2. Read the transcript tail: `python starter/scripts/build_dashboard.py <job_dir> --open` (local only).
3. Assign one label from the fixed set: `slow-generation timeout`, `wrong final answer / verification gap`, `forgotten or lost detail`, `repeated loop`, `other`. A short modifier is allowed (e.g. `over-exploration`).
4. Record one line: task, label, one piece of evidence.

Labels for the baseline (first pass, 2026-09-21, from transcript tails and verifier output, not full
reads):

| Task | Label | Evidence |
|---|---|---|
| `chess-best-move` | slow-generation timeout | ~1.6K output tokens per turn; writing its own chess engine in the last turns |
| `polyglot-c-py` | slow-generation timeout, polishing | ~1.8K per turn; Python side worked, chasing a harmless C warning, then a bash quoting error |
| `qemu-alpine-ssh` | timeout, over-exploration | read the ISO `init` script in 200-line chunks; a crude check found no QEMU launch |
| `qemu-startup` | timeout, over-preparation | extracting the ISO, checking CPU, memory and `nc`; a crude check found no QEMU launch |
| `regex-log` | slow-generation timeout | ~3.9K output tokens per turn, ~130 s per turn; 7 turns used the 900 s |
| `configure-git-webserver` | wrong final answer / verification gap | declared complete after its own test; verifier: "TEST FAILED: Web serve…" |

Reading: none of the six failures is a forgotten detail or a clear repeat loop, and none is a context
overflow. On this sample, context growth explains no failure.

### 5. Noise rule (approved)

**Observed:** across the three baseline runs (§1), completion rate was 4/10 every time, with the
identical 4 tasks passing and the identical 6 failing — including the pair run at double the
intended concurrency (§1 Deviation). No flakiness was observed. Token totals varied by about ±29%
around a mean of ~4.27M (stdev ≈ 612K on 3.63M / 4.33M / 4.85M), but that spread is confounded by
the concurrency deviation and is an upper bound on noise, not a clean estimate — no genuinely
sequential repeat has been run.

**Rule:**
- **Completion rate:** treat a change to a task's pass/fail outcome as real, not noise, on the first
  observation — the baseline showed zero flips across 3 runs, including one under 2x load. If a gate
  run flips a task that was stable in the baseline (3/3), re-run once to rule out a one-off (a flaky
  container pull, a grading timing issue — see `starter/docs/walkthrough.md`'s note on flakes)
  before concluding it's a regression or improvement.
- **Tokens:** don't gate a decision on a token delta smaller than roughly 30% until a sequential
  (non-overlapping) repeat produces a clean noise estimate to replace this placeholder.
- **Symmetry:** any re-run applies equally to results that look like a regression and results that
  look like an improvement — re-running only bad results biases toward keeping changes.
- Each run costs about 30 minutes; re-runs must not overlap with each other or with the run being
  checked (see §2's added bullet).

This rule is weaker than originally planned: the 3-run baseline gives good evidence for
task-level stability but, because of the concurrency deviation, no trustworthy token-noise number.
A sequential repeat remains valuable before Gate G2, where the token comparison matters most, and
is still outstanding — no phase currently owns running it.

## Notes for the next phase

Written when a phase completes: what the next phase must know that is not obvious from the code
(surprises, half-finished edges, constraints discovered). One heading per phase; delete a note once
it has been acted on and, if it still matters, move it to `decisions.md`.

### Phase 1

- **Gate G1 ran 2026-09-22 and found a real, root-caused completion-rate regression that was
  accepted, not fixed — see *Gate G1 results* in the code map above and DEC-033.** Tokens dropped
  ~33–58% (a clean win), but `build-cython-ext` and `fix-code-vulnerability` — previously 3/3-stable,
  finishing in 25–87 turns — now run to the 100-turn or 900s cap without finishing, in both
  `AGENT_CANONICALIZE` on and off. Root cause: the 6-pair recent window (DEC-014's own predicted,
  accepted gap) drops early discoveries on tasks needing many turns, and the agent re-explores/
  re-verifies instead of converging. **This is exactly the kind of failure Phase 4 (task state) and
  Phase 5/backlog (retrieval) exist to fix** — a next phase working on either should treat these two
  tasks as a concrete regression test: re-run them under the same settings and check whether
  `finished` flips back to `True` in a similar turn count to the baseline (25–87 turns), not just
  whether the aggregate pass rate looks acceptable. Gate G2 (after Phase 4) should re-check this
  specifically, not just re-run the aggregate protocol. `AGENT_RECENT_WINDOW_PAIRS` was deliberately
  left at its default (6) rather than tuned — that remains an open, untried lever if a future phase
  wants a cheaper interim mitigation before task state/retrieval ship.
- **`raw_events` is a plain `list[Event]`, owned by `agent.py`'s `run()`, not `context.py`.** Any new
  event-producing step (Phase 3's offload, Phase 4's state updates) should extend `context.py`'s
  functions and have `agent.py` append the result to `raw_events`, the same pattern
  `record_observation` already follows — don't give `context.py` its own copy of the list.
- **`select_recent_events` has zero awareness of `"none"`-kind events** (DEC-026) — they're
  invisible to it entirely, not filtered out after the fact. If a later phase's signal (e.g. Phase
  2's repeated/no-progress detectors) needs to see *all* raw events including `"none"` ones, read
  `raw_events` directly rather than going through `select_recent_events`.
- **`ObservationEvent.exit_code` is `int | None`.** Phase 4's failure extractor (named in the ledger
  as a reader of it) must check `did_not_complete`/`exit_code is None` before treating it as a real
  exit code (DEC-029).
- **`context.metadata["messages"]` no longer includes the system prompt or task instruction** — see
  DEC-032. They're separate `context.metadata["system_prompt"]`/`["instruction"]` keys instead. Any
  new consumer of `context.metadata` (not just `build_dashboard.py`) needs to know this if it wants
  to reconstruct what the model was told.
- **`context.metadata` is now rebuilt multiple times per turn** (DEC-031), not once — a closure in
  `agent.py::run()` (`sync_metadata`) called after every `raw_events`/`finished`/`telemetry`
  mutation. If a later phase's telemetry additions make serializing `raw_events` non-trivial (it's
  currently a cheap `dataclasses.asdict` per event), revisit whether every call site still needs a
  full rebuild.
- **`prompts.observation_message` is now duck-typed**, not tied to a specific class — it reads
  `.exit_code`/`.stdout`/`.stderr`/`.did_not_complete`/`.error` off whatever it's given
  (`tools.ShellResult` or `events.ObservationEvent`, both have matching field names). A later phase
  adding a third observation-shaped type should keep those field names rather than adding a branch.

## Deviations from the plan

Where what was built differs from the spec, and why. Link the `DEC-NNN` if a decision was made.

### Phase 1

- **`context.metadata` gains `"system_prompt"`/`"instruction"` keys not named in the phase spec or
  DEC-012.** DEC-012 scopes `"messages"` to only `AssistantActionEvent`/`ObservationEvent` entries,
  which would have silently dropped `build_dashboard.py`'s ability to show what a task even asked
  for (previously `messages[0]`/`[1]` in the OpenAI-format list). See DEC-032.
- **`context.metadata` is synced after every raw-history mutation within a turn, not once per
  turn.** The pre-Phase-1 baseline's single per-turn write was safe only because `messages` was
  mutated in place by reference; Phase 1's serialized `"messages"` is a fresh value each time, so a
  single early write would go stale if the process were killed mid-`run_shell`. See DEC-031.
- **`build_active_context`'s signature is `(system_prompt, instruction, raw_events, config)`**, not
  design.md §23's `(system_prompt, instruction, task_state, raw_events, retrieval_query, budgets)` —
  expected, given DEC-023 scopes `config` to two fields and this phase has no task state or
  retrieval, but noted here since a reader skimming design.md's pseudocode after DEC-023 might not
  otherwise connect the two.
- **`select_recent_events`'s signature is `(events, max_pairs)`**, not design.md §13's `(events,
  token_budget, count_tokens)` — already anticipated by the phase spec itself and DEC-015 (no local
  tokenizer this phase), not a new decision; recorded here only so the signature change is visible
  next to the others.
- **`build_dashboard.py` keeps the pre-Phase-1 `classify_messages`/`parse_observation` code path**,
  beyond DEC-019's "minimal patch" framing — a mean-review pass caught that the initial
  implementation replaced them outright, which silently broke rendering for every pre-Phase-1 job
  directory (verified against the real baseline-of-record jobs: every message fell into a raw-JSON
  `"other"` fallback and the system/task turns disappeared, since old metadata has neither
  `event_type` nor `system_prompt`/`instruction` keys). `build_trial_record` now detects the shape
  per job and dispatches to the matching classifier. Not a new decision so much as a correction: the
  original patch didn't actually satisfy DEC-019's own "keep rendering a transcript" goal for data
  the Measurement protocol depends on.
