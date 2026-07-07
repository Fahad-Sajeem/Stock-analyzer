#!/usr/bin/env bash
# Intraday watch wrapper for Linux/cron (mirror of run_watch.ps1).
# Cron (system TZ = Asia/Kolkata):  */15 9-15 * * 1-5  /opt/stock-analyzer/scripts/run_watch.sh
# The command itself exits instantly outside 09:15-15:35 / holidays.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
LOG="logs/watch_$(date +%Y%m%d).log"
export PYTHONUTF8=1

echo "--- watch $(date +%H:%M:%S) ---" >> "$LOG"
"$ROOT/.venv/bin/analyzer" watch >> "$LOG" 2>&1

find "$ROOT/logs" -name 'watch_*.log' -mtime +60 -delete 2>/dev/null
