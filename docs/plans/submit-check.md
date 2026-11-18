# Submit check (cut skipped-requirement failures)

Agreed 2026-11-03 (Mukhriz, with Claude) after the `full-capta-v1` analysis
(`docs/research/full-capta-v1.md`). Branch: `feat/submit-checklist`, from `feat/time-awareness`.

## Problem

In `full-capta-v1`, 15 tasks failed with a submitted answer. Almost all of them verified before submitting
("ALL SUITES PASS", "FINAL OUTPUT IDENTICAL"), but only against the agent's own reading of the task. The
hidden tests failed them on requirements the agent skipped. Some of these repeat in every run:

- `polyglot-c-py`: correct program, but the compiled test binary `cmain` was left in `/app/polyglot`; the
  test wants only `main.py.c` there. 5 of 5 runs, starter agent included.
- `polyglot-rust-c`: the same, `cmain` and `main` next to `main.rs`.
- `sanitize-git-repo`: rewrote git history, so an original commit the test looks up is gone. 2 of 2 runs.
- `financial-document-processor`: left the original documents in place once (`full-mini-v1`).

Prompt rule 6 already says "build and experiment in /tmp, not in the output directory". The model reads it
at the start and acts on it 10+ minutes later; in these runs it didn't hold.

Separately, the agent searched GitHub for Terminal-Bench's own repo in two full runs (`extract-elf` in
`full-mini-v1` copied the official solution; `count-dataset-tokens` in `full-capta-v1` found nothing). The
top 5 submissions are code-reviewed.

## Technical Plan

Two settings, both off by default.

1. **`AGENT_SUBMIT_CHECK=on`:** the first successful submit command is held back. Its output is replaced by a
   checklist: re-read the task's explicit requirements (paths, names, format, signatures, stated limits);
   `ls -la` the directories the task names and delete files created there only to build or test, keeping what
   the task needs; change nothing the task didn't ask for (history, data, settings). The next submit goes
   through. The reminder lands at the moment of the decision, once per task.
2. **`AGENT_NO_BENCHMARK_LOOKUP=on`:** one system-prompt line: solve the task yourself; don't search online
   for this benchmark or published solutions; packages, data and docs the task needs are fine.

Both are generic (no task names, no task-specific text), so they fit the competition's one-prompt rule.

## Alternatives

- **A stronger prompt rule only.** Rule 6 already covers leftover files and didn't work.
- **Clean output directories automatically.** The agent can't know which files the tests need; deleting a
  build output would turn passes into fails.
- **A second model call as a reviewer.** More tokens and code for the same reminder; try only if the
  checklist doesn't move the target tasks.

## Weak spots

- The "delete files you created" step could delete a build output the tests need. The controls include
  build tasks (`build-pmars`, `sqlite-with-gcov`, `pytorch-model-cli`, `kv-store-grpc`) to catch that.
- "Don't rewrite history" could stop a task that genuinely needs history changes. `fix-git` and
  `git-multibranch` are in the controls.
- One extra turn per task: the full history is re-sent once more (about 1-2% more tokens) and a task near its
  time limit loses a turn. The tests still grade whatever state is left.
- The model may answer the checklist by resubmitting at once without checking.
- It can't fix misreadings the agent is sure of (e.g. `extract-elf` picking the wrong memory layout).

## Detailed Implementation

- `harbor_agent.py`: `SUBMIT_CHECK_MESSAGE` constant; `HarborEnvironment.submit_check` /
  `submit_checked_at`; `_check_finished()` replaces the first submit's output with the message and returns
  instead of raising `Submitted`. A submit command with a non-zero return code doesn't use up the check.
- `terminal_bench.yaml`: `{% if no_benchmark_lookup %}` line in `system_template`.
- `BadgerMiniAgent.run()`: reads both settings. `_sync_context()`: `submit_check`, `submit_checked_at_sec`,
  `no_benchmark_lookup` in the result metadata.
- Tests: `mini_agent/tests/test_submit_check.py` (no endpoint or Docker).

## Measure

- List: `mini_agent/eval/submit_check_subset.txt` (4 targets + 7 controls), with the same settings as
  `full-capta-v1` plus both new ones:
  `AGENT_THINKING_CAP=8192 AGENT_TIME_AWARENESS=on AGENT_SUBMIT_CHECK=on AGENT_NO_BENCHMARK_LOOKUP=on`.
- Compare against `full-capta-v1` on the same tasks. **Targets:** how many pass, and whether the leftover
  files / history rewrite are gone (read the verifier output, not just the reward). **Controls:** all 7 must
  still pass. Also check that the agent acted on the checklist (commands between the held-back submit and the
  real one).
- The targets fail the same way every run, so one run is enough to see whether the check fixes them; it is not
  enough to measure the effect on the full benchmark (16 of 89 tasks flipped between the two full runs).
