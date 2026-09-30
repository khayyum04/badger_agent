# starter/

## Purpose
The original starter kit: an installable Python package (`pyproject.toml`) containing the starter ReAct agent, the scripts that launch and inspect its runs, and the eval task lists. **The team's main agent is now `../mini_agent/`** (mini-swe-agent); this agent is kept as a reference implementation, and `eval/` here is shared by both. The guides that used to live in `starter/docs/` are now in the repo-root `../docs/`. Repo-level setup, competition rules, and commands live in the root `CLAUDE.md`.

## Contents
- `agent/` — the product: `BaselineAgent` loop, prompts, action parsing/execution, OpenAI-compatible LLM client. See `agent/CLAUDE.md`.
- `scripts/` — `run_baseline.sh` (10-task sample) and `run_subset.sh` (official subset) launchers, `build_dashboard.py` job viewer, and two VRAM-eligibility utilities. See `scripts/CLAUDE.md`.
- `eval/public_subset.txt` — task names consumed by `run_subset.sh`. Currently 3 placeholders until the official list is announced at kickoff.
- `.env.example`, `.env.op.example` — committed templates for local Ollama settings and 1Password references for the hosted endpoint. Real `.env`/`.env.op` are gitignored.
- `pyproject.toml`, `README.md`, `.gitignore` — packaging, starter overview, ignores (`.env`, `.venv/`, `jobs/`).

## How it fits in
`scripts/*.sh` → `harbor run` → imports `agent.agent:BaselineAgent` (resolvable only via the editable install of this directory) → the agent talks to the model endpoint configured by `.env` / `op run` and acts only through the task container. Results land in `jobs/`, which `scripts/build_dashboard.py` renders. Agent changes are made in `agent/` and measured with `scripts/`.

## Gotchas
- Credentials: hosted-endpoint keys come from 1Password via `op run --env-file=starter/.env.op -- <cmd>`. Never put `op://` refs or active `LLM_*` lines in `.env`; `agent/llm.py` loads `.env` with `override=True` and would clobber the injected values.
- The `.sh` scripts `cd` here themselves; `harbor` must be on PATH (activated venv) and Docker must be running.
- `eval/public_subset.txt` scores are not real leaderboard numbers until the list is replaced.
- Duplication to keep in sync: `scripts/build_dashboard.py` mirrors `agent/tools.py::CODE_BLOCK_RE` and `agent/prompts.py::NUDGE_MESSAGE`.
- Competition rules constrain edits: no task-specific hardcoding, approved open-weight models only for the submitted run, endpoint changes only via env files, never code.
