#!/usr/bin/env bash
# All 89 Terminal-Bench 2.0 tasks, single attempt — the leaderboard-style run (~hours).
#   op run --env-file=mini_agent/.env.op -- ./mini_agent/scripts/run_full.sh --job-name full-mini-v1
# The endpoint is shared: keep N_CONCURRENT at 2-4 and announce full sweeps in Kaggle Discussion.
source "$(dirname "$0")/_common.sh"
run_harbor -d terminal-bench@2.0 --agent "$AGENT" -n "${N_CONCURRENT:-3}" --jobs-dir jobs "$@"
