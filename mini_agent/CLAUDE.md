# mini_agent/

## Purpose
The team's main agent: mini-swe-agent (pinned PyPI `2.4.6`) wired into Harbor as an external agent for Terminal-Bench 2.0. It replaced `../starter/agent/` as the baseline; all new agent work happens here.

## Contents
- `badger_mini/harbor_agent.py` — `BadgerMiniAgent` (Harbor `BaseAgent`), `HarborEnvironment` (mini-swe-agent environment over `environment.exec()`), `HarborSyncedAgent` (`DefaultAgent` that mirrors token usage into Harbor's `AgentContext`), `BadgerLitellmModel` (no retries on 400s).
- `badger_mini/compaction.py` — `Compactor`: self-compaction (`AGENT_COMPACTION=on`, default off). Owns the `self_compact` tool, the stage messages, parsing of `self_compact` calls and the history rebuild; all its model-facing text lives there, not in the YAML. One instance per task, shared by `HarborSyncedAgent` (stage check before each query, rebuild on a `self_compact` action) and `BadgerLitellmModel` (tool list, parsing). Experiment version: `../docs/plans/self-compaction-mvp.md`.
- `badger_mini/langfuse_export.py` — `python -m badger_mini.langfuse_export <job-dir>...`: uploads per-task summaries of finished Harbor jobs to Langfuse as dataset experiment runs (one run per job, `reward`/`total_tokens`/`outcome` scores). Post-hoc, reads only `result.json` and the trajectory; `harbor_agent.py` must never import it (`langfuse` is the optional `[tracing]` extra). `scripts/_common.sh`'s `run_harbor` calls it after a run only when `LANGFUSE_ENABLED=1`.
- `tests/test_compaction.py`, `tests/test_thinking_cap.py`, `tests/test_time_awareness.py`, `tests/test_submit_check.py`, `tests/test_langfuse_export.py` — offline tests with a scripted model / patched litellm (`uv pip install -e "mini_agent/[dev]"`, `pytest mini_agent/tests`).
- `badger_mini/config/terminal_bench.yaml` — prompts, `step_limit`, command `timeout`, observation and format-error templates. Selected by `BADGER_CONFIG` (default this file).
- `scripts/` — `run_sample.sh`, `run_subset.sh <list>`, `run_full.sh`, `check_endpoint.sh`, `score.sh <job-dir>`; all `cd` into `mini_agent/` and write to `mini_agent/jobs/`.
- `eval/experiment_subset.txt` — the 30 tasks behind `../docs/research/mini-30-vs-baseline.md`.
- `eval/submit_check_subset.txt` — 4 tasks that failed a skipped requirement in every run + 7 controls (`../docs/plans/submit-check.md`).
- `eval/slow_subset.txt` — the 28 tasks that timed out or quit on overruns in `full-mini-v1`, plus 6 thinking-heavy passes as a regression check (`../docs/plans/thinking-cap.md`).
- `.env.example`, `.env.op.example` — committed templates; real `.env` / `.env.op` are gitignored.

## How it fits in
`scripts/*.sh` → `harbor run --agent badger_mini.harbor_agent:BadgerMiniAgent` (resolvable only via `uv pip install -e mini_agent/`) → `BadgerMiniAgent.run()` starts mini-swe-agent in a daemon thread → each command is scheduled back onto Harbor's event loop and runs in the task container → the model is called on the host through litellm (`openai/<LLM_MODEL>` at `LLM_BASE_URL`).

## Gotchas
- Endpoint settings come only from env vars (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_MAX_TOKENS`, `LLM_TEMPERATURE`, `LLM_TOP_P`, `AGENT_MAX_TURNS`, `AGENT_COMMAND_TIMEOUT_SEC`, `AGENT_THINKING_CAP`, `AGENT_TIME_AWARENESS`); never hardcode them. `.env` loads with `override=False`, unlike the starter's `llm.py`.
- Harbor reads `AgentContext` after `run()` returns *or is cancelled*: `HarborSyncedAgent.add_messages()` must keep token counts current every message, including `FormatError` responses.
- Returning normally after a crash is deliberate (so the verifier still grades); `_is_config_error()` is the exception, so misconfigured runs fail loudly instead of "finishing" every task with no work.
- The command wrapper uses `timeout -k 5 <t> bash -c` inside the container so partial output survives; Harbor's own timeout is `t + 30` as an outer bound.
- `harbor_agent.py` depends on mini-swe-agent internals (`DefaultAgent.add_messages/query`, `LitellmModel.abort_exceptions`, the `finish_reason` variable in `format_error_template`). Bumping the `mini-swe-agent` pin needs a rerun.
- With compaction on, `self.messages` is **replaced** at each compaction, so the trajectory file holds only the current history; what was replaced is in `agent/compaction-<n>.json`. Token counts are unaffected (they accumulate in `add_messages()`).
- `AGENT_STRIP_REASONING=on` drops earlier thinking from what is *sent* (`_prepare_messages_for_api`); stored messages keep it.
- `AGENT_THINKING_CAP` (default off) sets `max_tokens` per reply in `BadgerLitellmModel._query`; after a reply with `finish_reason=length` the next call gets the full `LLM_MAX_TOKENS` until one finishes normally. `n_boosted_calls` goes into the result metadata.
- `AGENT_TIME_AWARENESS=on` (default off) appends the time used to each command result in `HarborSyncedAgent.execute_actions()` (plus one nudge at 10 min, `nudged_at_sec` in metadata) and switches prompt rule 4 via the `time_awareness` template variable. Plan: `../docs/plans/time-awareness.md`.
- `AGENT_SUBMIT_CHECK=on` (default off): `HarborEnvironment._check_finished()` holds back the first successful `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` and returns `SUBMIT_CHECK_MESSAGE` (re-read requirements, delete build/test leftovers in the task's directories, no unrequested changes) as that command's output; the next submit goes through. Costs one turn. `submit_checked_at_sec` in metadata. Plan: `../docs/plans/submit-check.md`.
- `AGENT_NO_BENCHMARK_LOOKUP=on` (default off) adds one system-prompt line (template variable `no_benchmark_lookup`): don't search online for the benchmark or published solutions. Added after the agent fetched Terminal-Bench's repo in two full runs (`extract-elf` in full-mini-v1 copied the solution).
- No task-specific logic anywhere (competition rule): one config, one loop.
