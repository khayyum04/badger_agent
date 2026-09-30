# Shared by the run_*.sh scripts. Runs from mini_agent/ so results land in mini_agent/jobs/.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
AGENT="badger_mini.harbor_agent:BadgerMiniAgent"
command -v harbor >/dev/null || { echo "harbor not found: source .venv/bin/activate (repo root)" >&2; exit 1; }
[ -n "${LLM_API_KEY:-}" ] || echo "warning: LLM_API_KEY not set — launch via: op run --env-file=mini_agent/.env.op -- $0 ..." >&2
