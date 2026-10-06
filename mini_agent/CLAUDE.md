# mini_agent/

## Purpose
The team's main agent: mini-swe-agent (pinned PyPI `2.4.6`) wired into Harbor as an external agent for Terminal-Bench 2.0. It replaced `../starter/agent/` as the baseline; all new agent work happens here.

## Contents
- `badger_mini/harbor_agent.py` — `BadgerMiniAgent` (Harbor `BaseAgent`), `HarborEnvironment` (mini-swe-agent environment over `environment.exec()`), `HarborSyncedAgent` (`DefaultAgent` that mirrors token usage into Harbor's `AgentContext`), `BadgerLitellmModel` (no retries on 400s).
- `badger_mini/config/terminal_bench.yaml` — prompts, `step_limit`, command `timeout`, observation and format-error templates. Selected by `BADGER_CONFIG` (default this file).
- `scripts/` — `run_sample.sh`, `run_subset.sh <list>`, `run_full.sh`, `check_endpoint.sh`, `score.sh <job-dir>`; all `cd` into `mini_agent/` and write to `mini_agent/jobs/`.
- `eval/experiment_subset.txt` — the 30 tasks behind `../docs/research/mini-30-vs-baseline.md`.
- `.env.example`, `.env.op.example` — committed templates; real `.env` / `.env.op` are gitignored.

## How it fits in
`scripts/*.sh` → `harbor run --agent badger_mini.harbor_agent:BadgerMiniAgent` (resolvable only via `uv pip install -e mini_agent/`) → `BadgerMiniAgent.run()` starts mini-swe-agent in a daemon thread → each command is scheduled back onto Harbor's event loop and runs in the task container → the model is called on the host through litellm (`openai/<LLM_MODEL>` at `LLM_BASE_URL`).

## Gotchas
- Endpoint settings come only from env vars (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_MAX_TOKENS`, `LLM_TEMPERATURE`, `LLM_TOP_P`, `AGENT_MAX_TURNS`, `AGENT_COMMAND_TIMEOUT_SEC`); never hardcode them. `.env` loads with `override=False`, unlike the starter's `llm.py`.
- Harbor reads `AgentContext` after `run()` returns *or is cancelled*: `HarborSyncedAgent.add_messages()` must keep token counts current every message, including `FormatError` responses.
- Returning normally after a crash is deliberate (so the verifier still grades); `_is_config_error()` is the exception, so misconfigured runs fail loudly instead of "finishing" every task with no work.
- The command wrapper uses `timeout -k 5 <t> bash -c` inside the container so partial output survives; Harbor's own timeout is `t + 30` as an outer bound.
- Output offloading (#13, `docs/plans/tool-output-offloading.md`): the wrapper also saves each command's output to `/tmp/agent_out/cmd_<n>.log` in the container and prints `SAVED_MARKER` first, which `execute()` strips. Outputs over `AGENT_OUTPUT_LIMIT` (or `AGENT_OUTPUT_VIEW_LIMIT` for plain file views, see `is_file_view()`) render as `output_head`/`output_tail`/`total_chars`/`full_output_path`; trimming (#14) parses these two shapes, so renaming the fields breaks it.
- `harbor_agent.py` depends on mini-swe-agent internals (`DefaultAgent.add_messages/query`, `LitellmModel.abort_exceptions`, the `finish_reason` variable in `format_error_template`). Bumping the `mini-swe-agent` pin needs a rerun.
- No task-specific logic anywhere (competition rule): one config, one loop.
