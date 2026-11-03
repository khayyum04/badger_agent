# Shared by the run_*.sh scripts. Runs from mini_agent/ so results land in mini_agent/jobs/.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
AGENT="badger_mini.harbor_agent:BadgerMiniAgent"
command -v harbor >/dev/null || { echo "harbor not found: source .venv/bin/activate (repo root)" >&2; exit 1; }
[ -n "${LLM_API_KEY:-}" ] || echo "warning: LLM_API_KEY not set — launch via: op run --env-file=mini_agent/.env.op -- $0 ..." >&2

# `harbor run`, then (only when LANGFUSE_ENABLED=1) upload the job summary to Langfuse. Off by default;
# an export failure never changes the run's exit status. Job dir: --job-name if given, else the newest.
run_harbor() {
  local status=0 job="" prev=""
  harbor run "$@" || status=$?
  if [ "${LANGFUSE_ENABLED:-0}" = "1" ]; then
    for arg in "$@"; do [ "$prev" = "--job-name" ] && job="jobs/$arg"; prev="$arg"; done
    [ -n "$job" ] || job="$(ls -td jobs/*/ 2>/dev/null | head -1)"
    if [ -n "$job" ]; then
      python -m badger_mini.langfuse_export "$job" \
        || echo "warning: Langfuse export failed; retry: python -m badger_mini.langfuse_export mini_agent/$job" >&2
    fi
  fi
  return $status
}
