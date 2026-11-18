# Submit review on all 89 tasks (`full-review-v1`)

Victus, Nov 7-8 2026, branch `feat/review-and-time-limit`, all defaults plus `AGENT_SUBMIT_REVIEW=on`. The A side
is `full-all-v1` / `full-all-v2` (56 each).

## Result: no gain, drop the reviewer

**50/89 as graded.**

- **Grading broke on 7 more tasks than usual:** downloads from GitHub timed out or got HTTP 504 inside the test
  scripts, so no tests ran and the tasks scored 0. Those tasks were db-wal-recovery, feal-linear-cryptanalysis,
  modernize-scientific-stack, password-recovery, path-tracing, path-tracing-reverse and
  torch-tensor-parallelism. Each A run had none of these. Going by those tasks' A pass rates, about 5 of the 7
  would have passed, so **the corrected estimate is about 55**, against 56. That's no gain at best.

How the reviewer behaved:

- It ran on 71 tasks, with no errors. It ran 5.3 commands and took 50 s on average (max 212 s; 2 hit the
  3-minute budget).
- 47 verdicts were something other than a plain "ALL MET".
- On the 25 tasks that failed with a wrong answer in A, 10 passed, against 7.5 per A run.
- **It missed the cases it was built for:**
  - `polyglot-c-py`: the reviewer's own `ls` showed the leftover `cmain`, yet it wrote "main.py.c exists as a
    single file". The task failed again.
  - `cancel-async-tasks`: "All checks pass", but it failed the same cleanup-on-cancel test as before.
  - `pytorch-model-recovery`: "All success criteria verified", but `forward()` has the wrong signature.
- **It's the same model with the same blind spots.** A fresh context doesn't fix a misreading the model makes
  every time.
- No sign it broke anything itself: it worked in `/tmp` as told.

## Decision

Keep `AGENT_SUBMIT_REVIEW` off. The submit checklist stays: it's cheaper and did as well.

## Grading breaks on two tasks in every run

In every full run, the graders of `qemu-startup` and `qemu-alpine-ssh` fail before any test runs. The test
script's `apt-get install curl` gets HTTP 404 from deb.debian.org (a stale package list in the image), so
`curl` and `uvx` are missing. Those two tasks can't pass on any run as things stand. It's a benchmark-side
problem, not ours. TB 2.1 reportedly fixes 28 tasks; this may be one of them.
