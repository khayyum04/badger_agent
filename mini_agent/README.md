# mini_agent — the team's main agent

This is our Terminal-Bench 2.0 agent for the Efficient Coder challenge. It runs
[mini-swe-agent](https://github.com/SWE-agent/mini-swe-agent) (MIT, pinned `2.4.6` from PyPI) as a
Harbor **external agent**: the model client runs on your machine, and only bash commands go into the
task container.

It replaced the starter ReAct agent in [`../starter/`](../starter/) as our baseline. On the same 30
tasks it passed 15 against the starter agent's 10, with no ungraded crashes. The comparison is in
[`../starter/docs/research/mini-30-vs-baseline.md`](../starter/docs/research/mini-30-vs-baseline.md).

## Layout

| Path | What it is |
|---|---|
| `badger_mini/harbor_agent.py` | `BadgerMiniAgent`, the Harbor agent: runs mini-swe-agent's `DefaultAgent` in a worker thread, with a `HarborEnvironment` that sends each command through `environment.exec()` |
| `badger_mini/config/terminal_bench.yaml` | Prompts, step limit, command timeout, observation and format-error templates |
| `.env.op.example` / `.env.example` | 1Password references for the endpoint / non-secret tuning. Copy to `.env.op` / `.env` (gitignored) |
| `scripts/` | `run_sample.sh`, `run_subset.sh`, `run_full.sh`, `check_endpoint.sh`, `score.sh` |
| `eval/experiment_subset.txt` | The 30-task list behind the comparison doc |

## What it fixes compared with the starter agent

| Starter weakness ([analysis](../starter/docs/research/full-89-0924-failure-analysis.md)) | Here |
|---|---|
| W1/W5: cut-off thinking run as a command and kept in history | Native tool calls. A reply with no tool call is dropped from history and replaced by a short "take one small step" note |
| W5: `TASK_COMPLETE` matched anywhere | The task ends only when a command's output starts with `COMPLETE_TASK_AND_SUBMIT_FINAL_OUTPUT` |
| W4: 60 s limit throws away output | 180 s, enforced inside the container, so partial output survives |
| W6: a crash skips grading | Crashes return normally so the verifier still runs. Endpoint config errors fail on the first request |
| W7: stalls and copy-paste loops | Mostly gone (no-command replies 67 → 3 on the subset) |
| W2: full history re-sent every turn | **Not fixed** — the next lever |

## Setup (from the repo root)

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e mini_agent/                    # pulls harbor + mini-swe-agent 2.4.6
cp mini_agent/.env.example mini_agent/.env
cp mini_agent/.env.op.example mini_agent/.env.op # set your 1Password item name
```

You also need Docker running, the `op` CLI connected to the 1Password app, and the campus VPN.

## Run (from the repo root, venv active)

```bash
op run --env-file=mini_agent/.env.op -- ./mini_agent/scripts/check_endpoint.sh      # no Docker needed
op run --env-file=mini_agent/.env.op -- ./mini_agent/scripts/run_sample.sh fix-git   # one task
op run --env-file=mini_agent/.env.op -- ./mini_agent/scripts/run_sample.sh           # 10 sample tasks
op run --env-file=mini_agent/.env.op -- ./mini_agent/scripts/run_subset.sh eval/experiment_subset.txt
op run --env-file=mini_agent/.env.op -- ./mini_agent/scripts/run_full.sh --job-name full-mini-v1
./mini_agent/scripts/score.sh mini_agent/jobs/<job-name>
```

Subset paths are relative to `mini_agent/` (the scripts `cd` there). Any list works, for example
`../starter/eval/<file>.txt`. Set `N_CONCURRENT=<n>` before `op run` to change parallelism (default 1
for the sample, 2 for subsets, 3 for the full run).

Directly with Harbor:

```bash
cd mini_agent && op run --env-file=.env.op -- harbor run -d terminal-bench@2.0 \
  --agent badger_mini.harbor_agent:BadgerMiniAgent -n 2
```

Results land in `mini_agent/jobs/<job>/<task>__<id>/`: `result.json` (reward, tokens) and
`agent/mini-swe-agent.trajectory.json` (full transcript, including every model response's
`finish_reason` and token usage).

## Gotchas

- **Model:** the UW gateway serves only `qwen3.8-27b`, which is **not approved** for the submitted
  run. Swap `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` in `.env.op` once an approved endpoint is
  available. `check_endpoint.sh` lists the served model ids.
- **Credentials:** `.env.op` holds only `op://` references. `.env` is loaded with `override=False`,
  so `op run` values always win; still keep connection values out of `.env`.
- **Don't edit the config mid-run:** the agent re-reads `terminal_bench.yaml` at the start of every
  task, so an edit changes the rest of a running job.
- **Disk:** every task leaves a 0.5–3 GB Docker image. Run `docker image prune -a -f` between big runs.
- **Upgrading mini-swe-agent:** `harbor_agent.py` subclasses its internals, so bump the pin
  deliberately and rerun the smoke check and a subset.
