#!/usr/bin/env bash
# Weekly backup wrapper for Linux/cron (Oracle Cloud).
# Tier 1: verified local snapshot (analyzer backup).
# Tier 2: push the newest snapshot's DB to Oracle Object Storage (survives the
#         instance/block-volume dying) IF the OCI CLI is configured and
#         ANALYZER_OS_BUCKET is set.
# Cron (system TZ = Asia/Kolkata):  0 10 * * 0  /opt/stock-analyzer/scripts/run_backup.sh
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs
LOG="logs/backup_$(date +%Y%m%d).log"
export PYTHONUTF8=1

echo "=== backup START $(date -Iseconds) ===" >> "$LOG"

# --- tier 1: local verified snapshot ---
"$ROOT/.venv/bin/analyzer" backup --keep 4 >> "$LOG" 2>&1
CODE=$?

# --- tier 2: offsite to Oracle Object Storage (optional) ---
# Uploads only the SMALL critical.duckdb (positions/outcomes/fills/config-scale
# data, a few KB) — NOT the 1.4 GB full DB. Prices etc. are re-backfillable, so
# the 10 GB bucket never fills even with years of weekly backups.
# Setup once:  oci setup config ;  set ANALYZER_OS_BUCKET in /etc/environment
if [ $CODE -eq 0 ] && command -v oci >/dev/null 2>&1 && [ -n "${ANALYZER_OS_BUCKET:-}" ]; then
  NEWEST="$(ls -1dt "$ROOT"/backups/*/ 2>/dev/null | head -1)"
  CRIT="${NEWEST}critical.duckdb"
  if [ -f "$CRIT" ]; then
    OBJ="critical_$(date +%Y%m%d).duckdb"
    echo "uploading $CRIT -> os://$ANALYZER_OS_BUCKET/$OBJ" >> "$LOG"
    oci os object put --bucket-name "$ANALYZER_OS_BUCKET" --name "$OBJ" \
      --file "$CRIT" --force >> "$LOG" 2>&1 \
      && echo "object storage upload OK" >> "$LOG" \
      || echo "object storage upload FAILED (local backup still good)" >> "$LOG"

    # Retention: keep the newest 26 weekly critical objects (~6 months); delete older.
    oci os object list --bucket-name "$ANALYZER_OS_BUCKET" --prefix "critical_" \
      --query 'sort_by(data,&name)[*].name' --raw-output 2>>"$LOG" \
      | sed 's/[][", ]//g' | grep -E 'critical_[0-9]+\.duckdb' \
      | head -n -26 \
      | while read -r old; do
          oci os object delete --bucket-name "$ANALYZER_OS_BUCKET" --name "$old" \
            --force >> "$LOG" 2>&1 && echo "pruned old offsite $old" >> "$LOG"
        done
  fi
else
  echo "object storage push skipped (oci not configured / ANALYZER_OS_BUCKET unset)" >> "$LOG"
fi

echo "=== backup END exit=$CODE $(date -Iseconds) ===" >> "$LOG"
find "$ROOT/logs" -name 'backup_*.log' -mtime +180 -delete 2>/dev/null
exit $CODE
