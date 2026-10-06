# Tool output offloading (issue #13)

Agreed 2026-10-05 (Mukhriz, with Claude). Branch: `feat/13-output-offloading`. Related: #14 (history
trimming, Khayyum), which reads the output format defined here.

## v2 changes (2026-10-06)

The v1 30-task run (`jobs/offload-30-v2`, 14/30, 82.2M tokens) saved no tokens against the baseline
(12/30, 74.0M in `full-mini-v1`; 15/30, 77.2M in Khayyum's run). From its transcripts:

- **55% of the 295 offloaded outputs were the model deliberately viewing a file** (`cat`, `sed -n`,
  `nl`, `head`); build/test logs were only 7%. Cut off, the model re-read the same file in pieces
  222 times in 16 tasks (back-to-back `sed -n` range reads: 3.1 per 100 commands before, 8.2 after),
  roughly 15M tokens of extra calls.
- The previews (about 2.3K chars each) still made up 37M re-sent characters.
- The model opened the saved files only 9 times.
- Confound: the model server was about 19% faster (94 against 79 output tok/s), so time-limit stops fell
  from 10 to 1 and tasks ran to the 100-turn cap instead (1,457 calls against 1,232).

v2, measured alone (Khayyum's compaction from `main` deliberately not merged yet):

1. **File views get a higher limit.** `is_file_view()` is true when every `&&`/`;`/newline-separated part
   of the command is `cat`/`nl`/`head`/`tail`/`sed -n` (pipes allowed) or a `cd`/`echo`/`printf`
   filler, with at least one view and no heredoc (`<<`) or `||`. Such outputs are shown in full up to
   `AGENT_OUTPUT_VIEW_LIMIT` (default 10,000) and offloaded above that. On the v1 run this would have
   shown 150 of the 295 offloaded outputs in full.
2. **Smaller previews:** `AGENT_OUTPUT_HEAD` 500 → 300, `AGENT_OUTPUT_TAIL` 1,500 → 1,000.

Known misses: a file printed by a script (`python3 -c "print(open(f).read())"`) isn't a view;
`cat f | python3 parse.py` counts as one (its output is then capped at 10,000, not 2,000).
Measure: one 30-task run against `offload-30-v2`, comparing paging rate, re-sent preview text and
tokens per call, and noting server speed (no same-day "off" run is possible).

The sections below describe v1; v2 changes only the limit choice in `execute()` and the defaults.

## Problem

About 97% of `mini_agent`'s tokens are input: the whole history is re-sent to the model every turn, so
a long command output is paid for again on every later turn. Today an output is only cut down above
10,000 characters (`observation_template` in `mini_agent/badger_mini/config/terminal_bench.yaml`).

Replaying the transcripts of `jobs/full-mini-v1` (52/89, 143.2M tokens, see
`docs/research/full-mini-v1.md`) with outputs cut at 2,000 characters saves an estimated 15–35M of
the 138.4M input tokens (+0.15 to +0.35 leaderboard). Of 3,362 outputs, the median is 389 characters
and 548 are over 2,000. The estimate assumes the model never re-reads the full output; in practice it
sometimes will, which gives part of the saving back.

## Technical Plan

1. **Save every command's output inside the task container** as it runs, at
   `/tmp/agent_out/cmd_<n>.log` (`n` = 1, 2, 3, … per task). This happens in the command wrapper in
   `HarborEnvironment.execute()`, in the same `exec` call as the command. If the directory or file
   can't be created, the command runs exactly as it does today (no file).
2. **Short outputs (≤ 2,000 characters) are shown to the model unchanged:**
   `{"returncode": 0, "output": "..."}`.
3. **Long outputs (> 2,000 characters, and the file was saved) are shown as a preview:**

   ```json
   {
     "returncode": 1,
     "output_head": "<first 500 characters>",
     "output_tail": "<last 1,500 characters>",
     "total_chars": 24000,
     "full_output_path": "/tmp/agent_out/cmd_12.log",
     "note": "Output truncated. Full output saved at full_output_path; search it with grep, or view parts with head/tail/sed -n."
   }
   ```

   `exception_info` is appended when present, as today. The tail is longer than the head because
   errors and final status usually come at the end.
4. **Settings** come from env vars (`mini_agent/.env`), like the other `AGENT_*` settings:

   | Var | Default | Meaning |
   |---|---|---|
   | `AGENT_OUTPUT_LIMIT` | `2000` | Offload outputs longer than this many characters. `0` turns offloading off (today's behaviour, for A/B runs). |
   | `AGENT_OUTPUT_HEAD` | `500` | Characters kept from the start. |
   | `AGENT_OUTPUT_TAIL` | `1500` | Characters kept from the end. |

5. **Contract with #14 (trimming):** an output message has exactly one of two shapes: `output`
   (short or not offloaded) or `output_head` + `output_tail` + `total_chars` + `full_output_path`
   (offloaded). The existing over-10,000 shape (`output_head`, `output_tail`, `elided_chars`, `warning`)
   still appears only when offloading is off or the file couldn't be saved. Old outputs stay searchable
   at `full_output_path` after trimming shortens their turn.

## Alternatives

- **Write the file afterwards, only for long outputs** (a second `exec` that pipes the text back into
  the container). Lost: needs two calls per long output, and one command can only carry so much text,
  so large outputs (build logs of hundreds of KB) would need chunking.
- **Head and tail split evenly (1,000 + 1,000).** Lost: shows less of the end, where errors are.
- **Limit 1,000 or 4,000.** 1,000 saves more (21–49M) but the model has to open the file more often;
  4,000 is safer but saves about half as much (9–20M). 2,000 is the middle, and it's adjustable via env.
- **New field names.** Lost: reusing `output_head`/`output_tail` from the existing long-output shape
  keeps the number of shapes #14 must parse at two.
- **Leave offloading to #14** (its original "Fix 2" notes included writing full outputs to a file).
  Lost: split on 2026-09-30 so #13 owns offloading and #14 owns trimming, in different functions.

## Detailed Implementation

### `mini_agent/badger_mini/harbor_agent.py`

**`HarborEnvironmentConfig`** gains:

```python
output_limit: int = 2000   # 0 = offloading off
output_head: int = 500
output_tail: int = 1500
output_dir: str = "/tmp/agent_out"   # inside the container; a field so tests can point it elsewhere
```

**`HarborEnvironment.__init__`** sets a counter `self._n_commands = 0`.

**`HarborEnvironment.execute()`**:

1. Increment the counter first (also when the command later fails), and let
   `path = f"{output_dir}/cmd_{n}.log"`.
2. Keep the current inner command unchanged as `run`:
   `if command -v timeout ...; then timeout -k 5 {timeout} bash -c {inner}; else bash -c {inner}; fi`.
3. When `output_limit > 0`, wrap it (paths shell-quoted):

   ```bash
   if mkdir -p DIR 2>/dev/null && : > PATH 2>/dev/null; then
     { RUN ; } > PATH 2>&1; rc=$?; echo SAVED_MARKER; cat PATH; exit $rc
   else
     RUN
   fi
   ```

   `SAVED_MARKER` is a new module constant, e.g. `BADGER_OUTPUT_SAVED_7f3a`. stdout and stderr both
   land in the file, so the output comes back interleaved in the order printed (today it's stdout then
   stderr). The return code is the command's, so the `124/137` timeout check is unaffected.
   When `output_limit == 0`, send `RUN` exactly as today.
4. After `exec`: `text = stdout + stderr`. If `text` starts with `SAVED_MARKER + "\n"`, strip that line
   and set `saved = True`. `output["output"]` is always the full, marker-free text, so
   `_check_finished()` (the submit marker check) and anything else reading it is unchanged.
5. If `saved` and `len(text) > output_limit`, add to the output dict: `output_head = text[:output_head]`,
   `output_tail = text[-output_tail:]`, `total_chars = len(text)`, `full_output_path = path`.
6. The exception path (`returncode: -1`) is unchanged and never adds these keys.

**`BadgerMiniAgent.run()`**: read `AGENT_OUTPUT_LIMIT`, `AGENT_OUTPUT_HEAD`, `AGENT_OUTPUT_TAIL` into
`env_config` the same way `AGENT_COMMAND_TIMEOUT_SEC` is read. Add them to the module docstring's
settings list.

### `mini_agent/badger_mini/config/terminal_bench.yaml`

`observation_template` gets a new first branch:

```jinja
{%- if output.full_output_path is defined -%}
{
  "returncode": {{ output.returncode }},
  "output_head": {{ output.output_head | tojson }},
  "output_tail": {{ output.output_tail | tojson }},
  "total_chars": {{ output.total_chars }},
  "full_output_path": {{ output.full_output_path | tojson }},
  "note": "Output truncated. Full output saved at full_output_path; search it with grep, or view parts with head/tail/sed -n."
  {%- if output.exception_info %}, "exception_info": {{ output.exception_info | tojson }}{% endif %}
}
{%- elif output.output | length < 10000 -%}
... (existing short branch, unchanged)
{%- else -%}
... (existing over-10,000 branch, unchanged)
{%- endif -%}
```

### Docs and settings

- `mini_agent/.env.example`: add the three vars with their defaults and one-line comments.
- `mini_agent/CLAUDE.md`, Gotchas: the wrapper now saves output to `/tmp/agent_out/cmd_<n>.log` and
  prefixes a marker line that `execute()` strips; the two output shapes are a contract with #14.

### Tests: `mini_agent/tests/test_offloading.py` (offline, no Docker, no model)

Add `pytest` as a dev dependency in `mini_agent/pyproject.toml` if it isn't one.

1. **Python logic with a fake environment** whose `exec` returns a canned result (no command runs):
   - short output with marker → `output` only, marker stripped, no offload keys;
   - long output with marker → head/tail/total/path set, head 500 and tail 1,500 characters, path
     `…/cmd_<n>.log` with `n` counting up across calls;
   - long output **without** marker (file couldn't be saved) → no offload keys;
   - `output_limit = 0` → the command sent is exactly today's wrapper, no offload keys;
   - output whose first line after the marker is `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` with
     return code 0 → raises `Submitted`.
2. **Template rendering**: render `observation_template` with each output shape and check the result is
   valid JSON with the expected keys.
3. **Wrapper shell behaviour**: run the generated wrapper with local `bash` against
   `output_dir = tmp_path` using harmless commands only (`echo`, `printf`, `exit 3`), checking the file
   content, the marker line, and that the return code is preserved. Skip the timeout case when
   `timeout` isn't installed (macOS). These run only throwaway commands in pytest's temp dir; the agent
   itself still only executes inside the container.

### Verification after the tests

1. One sample task with `./mini_agent/scripts/run_sample.sh <task>` (VPN + `op run`): check that
   `/tmp/agent_out/` fills up in the container and that the trajectory shows previews for long outputs.
2. 30-task run on the Victus from this branch:
   `./mini_agent/scripts/run_subset.sh eval/experiment_subset.txt` with `-n 2` and
   `--environment-build-timeout-multiplier 6`. Compare against the mini_agent baseline **15/30, 77.2M
   tokens** (`docs/research/mini-30-vs-baseline.md`). Success: tokens clearly down, passes not lower
   (single runs vary by about ±3 tasks; the same 30 scored 12/30 inside `full-mini-v1`).
   Also count how often the model reads a `full_output_path` file, which shows how much of the
   saving is given back.

### Known limits

- The trajectory still keeps every full output: mini-swe-agent stores it in each tool message's
  `extra.raw_output`, and `extra` is stripped before messages are sent to the model.
- Harbor's outer timeout (`timeout + 30`) still loses all output, as today.
