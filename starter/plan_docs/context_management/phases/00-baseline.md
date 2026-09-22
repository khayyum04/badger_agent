# Phase 0: Establish context-management baseline

Spec: draft for review, not yet approved. Phase status lives only in [`../roadmap.md`](../roadmap.md).
Depends on: —
Design: [`../design.md`](../design.md) §2, §29, §30 (variant A)
Roadmap: [`../roadmap.md`](../roadmap.md)
Issue: #1
Decisions: DEC-009 (baseline of record), DEC-010 (measure with `jq`, no agent edit)

## Problem

Phases 1–5 change how the agent builds its prompt. To tell a real improvement from noise, or a
token saving from a lost task, every later phase needs one fixed reference: how the unmodified
`BaselineAgent` performs on a fixed task set, what its tokens cost in leaderboard-score terms, and
whether context growth ever causes a failure. Without it, gates G1 and G2 have nothing to compare
against, and G2 (whether to build LLM compaction at all) cannot be judged.

## Technical Plan

Phase 0 changes **no source code**. The baseline already exists: a run of the unmodified agent on
the 10-task sample. Phase 0 (a) pins that run down as the baseline of record with the caveats it
carries, (b) writes the protocol every later phase re-runs, (c) defines how the numbers are derived
from `jobs/` with `jq`, and (d) labels why the baseline's failed runs failed.

- **Baseline of record:** the existing 2026-09-12 run, one sample (DEC-009).
- **Task set:** the 10-task `terminal-bench-sample@2.0`, at every gate. The public subset
  (`eval/public_subset.txt`, 3 placeholders) is not used (DEC-009).
- **Concurrency:** `-n 4`, set explicitly, for the baseline and every later run (DEC-009).
- **Token source:** the endpoint's `usage`, i.e. `n_input_tokens` + `n_output_tokens` in
  `result.json`. No tokenizer, no `agent.py` edit (DEC-010).
- **Results location:** `jobs/` only. `handoff.md` holds the protocol, derivation commands and
  failure labels, not the numbers (DEC-010).
- **Per-turn / peak context:** an offline estimate from the stored `messages`, calibrated to the
  exact `n_input_tokens`; always labelled an estimate (DEC-010).

## Resolved questions

| Original open question | Answer |
|---|---|
| Which task set? | The 10-task sample only. |
| The model's real context limit? | Docs state 250k for the provided Qwen3.6 endpoint (`starter/docs/uw_madison_endpoint.md:70`); not verified for `qwen3.8-27b`. The baseline finished an 87-turn trial with an estimated ~46k peak, so the window is at least ~40k. Budgets in `design.md` §24/§34 may use 250k as the working figure and must say it is unverified. |
| Token counting? | Trust the endpoint's `usage` (DEC-010). |
| Repeats per task? | None now: the baseline is one sample. See §5 for the proposed noise rule. |
| Where do results live? | `jobs/` only (DEC-010). |
| Can `build_dashboard.py` give the per-turn context curve? | No: it shows trial totals only. The offline estimate in §3 replaces it. |

## Alternatives

Rationale and rejected options live in the decisions; in one line each:

- Re-run the baseline at `-n 1` — dropped: about two hours, and it would still not match the old run's concurrency (DEC-009).
- Fresh repeats now — declined for cost; replaced by the proposed noise rule in §5 (DEC-009).
- Public subset, or sample plus subset — the subset is placeholders until kickoff (DEC-009).
- Add per-turn `usage` telemetry to `agent.py` — not needed for anything the score charges, and it would edit the "unmodified" baseline and pre-empt Phase 1's telemetry writer (DEC-010).
- Local tokenizer — approved models may not share one with any library (DEC-010).
- Commit a `baseline.md` numbers file — declined; accepted risk that the baseline lives only in local `jobs/` (DEC-010).

## Detailed Implementation

Nothing is built. The deliverable is text in `handoff.md` → *Measurement protocol* (§6), made of
the pieces below.

### 1. Baseline of record

The baseline is **three runs** of the same task set and agent (DEC-009):

| Job directory | Role | Concurrency | Pass rate | Total tokens |
|---|---|---|---|---|
| `jobs/2026-09-12__21-32-36` | original | inferred 4 | 4/10 | 3,630,524 |
| `jobs/2026-09-21__20-31-31` | repeat A | **actual 8** (see Deviation) | 4/10 | 4,332,197 |
| `jobs/2026-09-21__20-32-09` | repeat B | **actual 8** (see Deviation) | 4/10 | 4,849,315 |

**Deviation — repeats A and B ran concurrently with each other, not sequentially.** Both were
intended as independent `-n 4` runs, one after another. Instead, repeat A started 2026-09-21
20:31:32 and repeat B started 20:32:09 (38 s later); both ran until about 21:02. They overlapped
almost completely, so the real load was 8 concurrent trials for nearly the whole duration, not the
4 the protocol calls for. Full reasoning in DEC-009. Consequence: the identical-pass/fail finding
below is not weakened by this (if anything it is a harder test, since it held under double load),
but the three token totals are not independent samples under matched conditions and should not be
averaged into a single "typical" figure without that caveat.

| Fact | Value | Status |
|---|---|---|
| Job directories | see table above (repo-root `jobs/`; gitignored; hold raw transcripts, so never commit or upload them: `starter/docs/safety.md`) | verified |
| Dataset and tasks | `terminal-bench-sample@2.0`: `build-cython-ext`, `chess-best-move`, `configure-git-webserver`, `fix-code-vulnerability`, `log-summary-date-ranges`, `polyglot-c-py`, `qemu-alpine-ssh`, `qemu-startup`, `regex-log`, `sqlite-with-gcov` | verified (10 trials in each job) |
| Agent | unmodified `BaselineAgent`. `starter/agent/*.py` are identical to commit `754f792` (2026-07-15) for all three runs: `git diff 754f792 HEAD -- 'starter/agent/*.py'` is empty | verified 2026-09-21 |
| Per-task agent timeout | 900 s, set by Harbor per task | verified (`AgentTimeoutError` message) |
| Model | `qwen3.8-27b` on the hosted gateway | owner's recollection for the original run; matches `LLM_MODEL` in `.env.op.example`; deliberately unchanged for the two repeats |
| Agent settings | `LLM_MAX_TOKENS=8192`, `LLM_TEMPERATURE` unset (0.2), `AGENT_MAX_TURNS` unset (100), `AGENT_COMMAND_TIMEOUT_SEC` unset (60) | **reconstructed** for the original run (`.env` was last edited 2026-09-16, after it ran); supporting evidence: some trials averaged more than 2048 output tokens per turn, above the code default. Unchanged and intentional for the two repeats |
| Concurrency, original run | unrecorded; treated as 4 | **inferred**: per-trial agent time sums to ~109 min inside ~30 min of wall-clock, and the job config names the agent via `--agent` (not the script's `--agent-import-path`), so Harbor's default `-n 4` applied |
| Concurrency, repeats A and B | `N_CONCURRENT=4` each, but overlapped (see Deviation above) | **measured**: `started_at`/`finished_at` in each `result.json` |

**Task-level finding across all three runs:** the same 4 tasks pass and the same 6 fail every
time — `build-cython-ext`, `fix-code-vulnerability`, `log-summary-date-ranges`, `sqlite-with-gcov`
always pass; `chess-best-move`, `configure-git-webserver`, `polyglot-c-py`, `qemu-alpine-ssh`,
`qemu-startup`, `regex-log` always fail. No flaky task observed in 3 runs, including one pair run
under double the intended concurrency.

### 2. Re-run command (protocol)

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
- The script passes the deprecated `--agent-import-path`; Harbor 0.22 still accepts it (`cli/jobs.py`, `cli/trials.py`) and only warns. The baseline used `--agent agent.agent:BaselineAgent`. They are expected to load the same agent; this has not been run-verified.
- **Run one job at a time.** Two of the three baseline runs (`2026-09-21__20-31-31`, `2026-09-21__20-32-09`) were launched 38 s apart and overlapped for their full ~30 minutes, so the real load was 8 concurrent trials instead of 4 (see §1 Deviation, DEC-009). Don't repeat that: start one `harbor run`, wait for it to finish, then start the next.

### 3. Derived numbers (protocol)

`JOB` is a job directory. Each snippet is run once per job directory (repeat for each of the three
baseline jobs in §1, or point it at a gate's job to compare) and gives 10 rows.

Per-task table (task, reward, turns, input tokens, output tokens, exception):

```bash
for f in "$JOB"/*/result.json; do
  jq -r '[.task_name, (.verifier_result.rewards.reward // "n/a"), .agent_result.metadata.turns,
          .agent_result.n_input_tokens, .agent_result.n_output_tokens,
          (.exception_info.exception_type // "none")] | @tsv' "$f"
done | column -t
```

Totals, pass rate and score penalty. `penalty_89_tasks` is the mean tokens per task times 89: an
order of magnitude only, since one heavy task can dominate. Always read it next to the "without
heaviest" figure.

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

Estimated peak context per trial (an estimate: it assumes tokens per character is constant within a
trial, so treat it as roughly ±20%). Columns: task, turns, `n_input_tokens`, chars in the last
prompt, calibrated tokens per char, estimated peak tokens:

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

### 4. Failure-cause labels (protocol)

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

### 5. Noise rule (PROPOSED, informed by the 3-run baseline; not yet agreed)

**Observed:** across the three baseline runs (§1), completion rate was 4/10 every time, with the
identical 4 tasks passing and the identical 6 failing — including the pair run at double the
intended concurrency (§1 Deviation). No flakiness was observed. Token totals varied by about ±29%
around a mean of ~4.27M (stdev ≈ 612K on 3.63M / 4.33M / 4.85M), but that spread is confounded by
the concurrency deviation and is an upper bound on noise, not a clean estimate — no genuinely
sequential repeat has been run.

**Proposed rule**, given that evidence:
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
A sequential repeat remains valuable before Gate G2, where the token comparison matters most.

### 6. Where it is written

At implementation (Phase 0 becomes `implemented`), copy §1–§5 into `handoff.md` → *Measurement
protocol* as commands and facts, not narrative: the three-run baseline table and Deviation note in
§1, the command in §2, the snippets in §3, the procedure and labels in §4, and the noise rule in §5
if approved. Flip the ledger row "Measurement command + baseline numbers" to `implemented` with
location "`handoff.md` → Measurement protocol; baseline jobs `jobs/2026-09-12__21-32-36`,
`jobs/2026-09-21__20-31-31`, `jobs/2026-09-21__20-32-09` (local)". `handoff.md` is not edited while
this spec is a draft.

## Interfaces and handoff

- **Provides:** the measurement command, the derivation snippets, the failure-labeling procedure, the six baseline labels, and the task-level stability finding (ledger row "Measurement command + baseline numbers"). Every later phase re-runs the command and compares with the baseline jobs.
- **Reuses:** `starter/scripts/run_baseline.sh` and `build_dashboard.py` unchanged; `jq`; Harbor's `result.json` fields `verifier_result.rewards.reward`, `agent_result.n_input_tokens`, `n_output_tokens`, `metadata.turns`, `metadata.finished`, `metadata.messages`, `exception_info`, `started_at`/`finished_at`. Nothing new is created in `starter/agent/` or `starter/scripts/`.
- **Handoff:** fill `handoff.md` → *Measurement protocol* per §6.

## Exit criteria

- `handoff.md` → *Measurement protocol* contains §1–§5 (with §5 only if approved), and a reader with no memory of this discussion could re-run the command and reproduce the derivations.
- Each §3 snippet runs unedited against each of the three baseline jobs and returns 10 trials.
- The baseline's caveats (reconstructed config for the original run, inferred concurrency, the concurrency deviation between the two repeats, dev model) are stated in the protocol, not only here.
- The answer to "does context growth cause failures or only cost?" is written down: none of the six failures in any of the three runs was caused by context growth, and the baseline token cost is expressed as a score penalty (via the §3 derivation).
- The agent code the baseline ran is identified by commit (`754f792`), so later phases can say what changed.
- `handoff.md` ledger row updated; no change to `starter/agent/CLAUDE.md` is expected (no code changed). Optionally add the script gotchas from §2 (first argument is a task name; script default `N_CONCURRENT=1`; don't launch two jobs close together) to `starter/scripts/CLAUDE.md`.
- Roadmap status and GitHub issue #1 are updated by the user's decision, not automatically.

## Tests

None (measurement only). The check is that the snippets run on each baseline job as written.

## Known limits

- **Token noise is not cleanly measured.** The two repeat runs overlapped (§1 Deviation), so the observed ±29% token spread is an upper bound, not a clean noise estimate; a sequential repeat is still outstanding.
- **Completion-rate stability is better evidenced than expected, but still only 3 runs**, and 5 of the 6 recurring failures are timeouts that depend on endpoint load, which varies by time of day; the concurrent-repeat pair is one data point that stability survives 2x load, not proof it always will.
- **Config for the original run is reconstructed, and its concurrency is inferred** (§1); a discovery that either differed needs a new DEC, not a silent edit.
- **Dev model.** `qwen3.8-27b` is not the approved submission checkpoint (Qwen3.6-27B-FP8). Verbosity, tokenizer and context window may differ, so the token pricing is indicative until re-priced on the submission model.
- **Heavy-tailed tokens.** `build-cython-ext` is the largest single contributor to input tokens in all three runs, and `starter/docs/walkthrough.md` flags its *oracle* as broken; the baseline agent nevertheless scored 1.0 in all three, so it is passable, but its token cost varies a lot run to run (863K–2.14M input tokens across the three).
- **Estimates.** The peak-context figure is roughly ±20%. The failure labels come from tails, not full reads, and cannot separate model slowness from endpoint queueing.
- **The baseline lives only in local `jobs/`.** Back it up outside the repo; deleting it deletes the baseline.
- **Script versus direct `harbor run`.** Not run-verified as equivalent (§2).
- For context, the 10-task baseline runs each used more tokens on their own than the README's "1–3M typical" for a full 89-task run, which is why the pricing derivation matters for G2.
