#!/usr/bin/env bash
# Submission-card numbers for a job dir:  ./mini_agent/scripts/score.sh mini_agent/jobs/<job-name>
# Scoring (Kaggle evaluation page): penalty = min(0.01, 0.01 * tokens_per_task / 100M), tokens_per_task = total_tokens / 89.
# On a subset we divide by the tasks actually run, so the score is a proxy; only a full 89-task run gives the real number.
set -euo pipefail
JOB="${1:?usage: score.sh <job-dir>}"
files=$(find "$JOB" -mindepth 2 -name result.json)
tb=$(echo "$files" | xargs jq -s '[.[] | .verifier_result.rewards.reward // 0] | add / length')
tok=$(echo "$files" | xargs jq -s '[.[] | (.agent_result.n_input_tokens // 0) + (.agent_result.n_output_tokens // 0)] | add')
n=$(echo "$files" | wc -l | xargs)
awk -v tb="$tb" -v tok="$tok" -v n="$n" 'BEGIN {
  tpt = tok / n; pen = 0.01 * tpt / 100000000; if (pen > 0.01) pen = 0.01
  printf "tasks=%d tb_score=%.5f total_tokens=%.0f tokens_per_task=%.0f token_penalty=%.5f leaderboard_score=%.5f\n", n, tb, tok, tpt, pen, tb - pen
}'
