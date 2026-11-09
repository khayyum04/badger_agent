# Change report at submit (`AGENT_CHANGE_REPORT`)

Agreed 2026-11-09 (Mukhriz, with Claude). Branch `feat/change-report`, from `feat/review-and-time-limit`.
Default off until a full run shows it helps.

## Problem

The repeated wrong answers (`docs/research/sometimes-pass-tasks.md`) are often the agent spoiling its own result:

- a compiled test binary left next to the deliverable (`polyglot-c-py` 4 times, `polyglot-rust-c`);
- git history rewritten (`sanitize-git-repo`);
- setup reset after testing (`configure-git-webserver`).

The submit checklist asks the agent to look, and the fresh reviewer looked too (`full-review-v1`). Both read a
long listing and missed it: the reviewer's own `ls` showed `cmain`, and it still wrote "single file".

## Technical Plan

- At the start of a task, take a snapshot of the task's directories: `/app` plus the directories of absolute
  paths named in the task.
  - Every file's path, size and mtime (`find ... -exec stat -c`). `.git` internals and `node_modules` are skipped.
  - For each git repo, the commit hashes (`git rev-list --all`).
- At the first submit (the submit check's hold), take the snapshot again and append a short factual list to
  the checklist:
  - **Created / Changed / Deleted** files, 25 per section at most.
  - **Commits** that existed at the start and are gone.
  - Then: "does the task ask for it? If not, delete or restore it."
- **Failures:** if anything fails (no directories, more than 20,000 files, a command error), there's no
  report and the plain checklist stays as it is.
- **Metadata:** `change_report`, and `change_counts` (created/changed/deleted/commits_gone).

## Weak spots

- The agent may delete a file the tests need (a build output). The checklist has carried the same risk since
  `full-all-v1` and didn't break the build tasks.
- Directories the agent creates (e.g. `/git` in `configure-git-webserver`) aren't in the start snapshot. Their
  files show up only if a snapshotted directory contains them.
- The two snapshots cost a few seconds per task (two `find` + `git` runs).
- Paths read from the task text are a heuristic. System roots (`/`, `/usr`, `/etc`, `/var`, ...) are never
  snapshotted whole.

## Detailed Implementation

- `badger_mini/changes.py`: `candidate_dirs`, `snapshot_command` / `parse_snapshot`, `git_command` /
  `parse_git`, `counts`, `report`.
- `harbor_agent.py`:
  - `HarborSyncedAgent.run()` takes the start snapshot; `_take_snapshot()`, `change_notes()`.
  - `HarborEnvironment.submit_notes` is appended to `SUBMIT_CHECK_MESSAGE`.
  - The switch is `AGENT_CHANGE_REPORT`.

## Status (2026-11-09)

- Code written; the existing 65 tests pass.
- **TODO:**
  1. Unit tests for `changes.py`: created/changed/deleted, lost commits, the too-many-files cap, the path
     heuristic.
  2. A shell check of `snapshot_command` / `git_command`. macOS `stat` has no `-c`, so use a shim or Docker.
  3. Docs: `.env.example`, `mini_agent/CLAUDE.md`, and the Langfuse export field `change_counts`.
  4. A one-task smoke test on the Victus (`polyglot-c-py`, with `AGENT_CHANGE_REPORT=on`): check the report lists
     `cmain`.
  5. Then a full run, `full-change-v1`.

## Measure

- A full run against `full-all-v1`/`v2` (56 each). Caveat: three experiments in a row scored 49-51 (see
  `docs/research/full-timelimit-v1.md`), so a result near 50 is ambiguous without a fresh baseline run.
- Per task: do `polyglot-c-py`, `polyglot-rust-c`, `sanitize-git-repo` and `configure-git-webserver` pass more
  often? Does any build task lose a needed file?
