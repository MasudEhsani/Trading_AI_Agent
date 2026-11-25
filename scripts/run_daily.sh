#!/usr/bin/env bash
# run_daily.sh - unattended daily review (Linux/macOS). Schedule it with cron, e.g.:
#   0 18 * * 1-5  ~/Trading_AI_Agent/scripts/run_daily.sh
# cron doesn't load your shell profile: put `export ANTHROPIC_API_KEY=...` in
# ~/.trading_agent_env (chmod 600) and it is read below.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f "$HOME/.trading_agent_env" ] && source "$HOME/.trading_agent_env"
mkdir -p data/live/reports
.venv/bin/python -m trading_agent --daily >> data/live/reports/log.txt 2>&1
