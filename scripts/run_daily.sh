#!/usr/bin/env bash
# Daily EOD pipeline wrapper for Linux/cron (mirror of run_daily.ps1).
# Cron (with system TZ = Asia/Kolkata):  0 19 * * 1-5  /opt/stock-analyzer/scripts/run_daily.sh
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
LOG="logs/daily_$(date +%Y%m%d_%H%M%S).log"
export PYTHONUTF8=1

echo "=== analyzer daily START $(date -Iseconds) ===" >> "$LOG"
"$ROOT/.venv/bin/analyzer" daily >> "$LOG" 2>&1
CODE=$?
echo "=== analyzer daily END exit=$CODE $(date -Iseconds) ===" >> "$LOG"

find "$ROOT/logs" -name 'daily_*.log' -mtime +120 -delete 2>/dev/null
exit $CODE
