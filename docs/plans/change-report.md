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
  - For each git repo, the commits reachable from local branches, tags and HEAD. Not `--all`: `git filter-branch`
    keeps the old history under `refs/original`, and remote refs keep it too, so lost commits would never show.
    A repo with more than 5,000 commits is left out (a cut-off list can't be compared).
- At the first submit (the submit check's hold), take the snapshot again and append a short factual list to
  the checklist:
  - **Created / Changed / Deleted** files, 25 per section at most. Files in a directory that didn't exist at the
    start (a build dir, `__pycache__`) are one line, `dir/ (N files, size)`, so they can't push `cmain` off the list;
    the same for a directory that was deleted whole.
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
  snapshotted whole; nothing under `/proc`, `/sys`, `/dev` or `/run` is snapshotted. A URL in the task is not a path.
- One big directory (more than 20,000 files in all) turns the whole report off, `/app` included.
- An edit that keeps the size, within the same second as the start snapshot, isn't seen (mtime is in seconds).

## Detailed Implementation

- `badger_mini/changes.py`: `candidate_dirs`, `snapshot_command` / `parse_snapshot`, `git_command` /
  `parse_git`, `counts`, `report`.
- `harbor_agent.py`:
  - `HarborSyncedAgent.run()` takes the start snapshot; `_take_snapshot()`, `change_notes()`.
  - `HarborEnvironment.submit_notes` is appended to `SUBMIT_CHECK_MESSAGE`.
  - The switch is `AGENT_CHANGE_REPORT`.

## Status (2026-11-09)

- Done: code; unit tests (`mini_agent/tests/test_change_report.py`, 25 tests; 90 in all pass); a shell check of the
  real commands on macOS with a GNU `stat -c` shim (spaces and `|` in paths, a missing dir, `node_modules` pruned, a
  new build dir as one line, a `filter-branch` rewrite seen as 2 lost commits); docs (`.env.example`,
  `mini_agent/CLAUDE.md`, Langfuse export of `change_report`/`change_counts`).
- Not checked: busybox `stat`/`find` (no Docker on the Mac). The smoke test covers it if the task image is Alpine;
  otherwise it's untested.
- **TODO:**
  1. A one-task smoke test on the Victus (`polyglot-c-py`, with `AGENT_CHANGE_REPORT=on`): check the report lists
     `cmain` (trajectory: the submit check's output) and that `change_counts` is in `result.json`.
  2. Then a full run, `full-change-v1`.

## Measure

- A full run against `full-all-v1`/`v2` (56 each). Caveat: three experiments in a row scored 49-51 (see
  `docs/research/full-timelimit-v1.md`), so a result near 50 is ambiguous without a fresh baseline run.
- Per task: do `polyglot-c-py`, `polyglot-rust-c`, `sanitize-git-repo` and `configure-git-webserver` pass more
  often? Does any build task lose a needed file?
