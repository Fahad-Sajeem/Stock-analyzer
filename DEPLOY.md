# Deploying to Oracle Cloud Free Tier (Ampere A1)

Hosting the observational run on an always-free Oracle VM so it doesn't depend
on your PC being on. Footprint: ~1.8 GB disk, peak RAM well under 1 GB with the
incremental nightly pipeline (the default in `analyzer daily`).

## 1. Provision the instance

- Shape: **VM.Standard.A1.Flex (Ampere ARM)** — always free up to 4 OCPU / 24 GB.
  **1 OCPU / 6 GB is plenty.** Do NOT use the 1 GB AMD micro shape.
- Image: **Ubuntu 24.04 (aarch64)**.
- Boot volume: default 50 GB (free tier allows 200 GB total) — ample.
- Networking: leave only SSH (22) open. The dashboard is best reached via an
  SSH tunnel (`ssh -L 8000:localhost:8000 ubuntu@<ip>`) rather than opening
  port 8000 to the internet — the app has no authentication.

## 2. System setup

```bash
sudo timedatectl set-timezone Asia/Kolkata     # all schedules below assume IST
sudo apt update && sudo apt install -y python3.12-venv python3-pip git
```

## 3. Install the app

```bash
sudo mkdir -p /opt/stock-analyzer && sudo chown $USER /opt/stock-analyzer
# copy the repo (from your PC):
#   scp -r D:\GitHub\PersonalGitHub\Claude\Stock-analyzer ubuntu@<ip>:/opt/stock-analyzer
cd /opt/stock-analyzer
python3 -m venv .venv
.venv/bin/pip install -e .
chmod +x scripts/run_daily.sh scripts/run_watch.sh
```

## 4. Bring the data

Two options:

- **Copy the existing DB (recommended — keeps all history + your positions):**
  `scp data/analyzer.duckdb ubuntu@<ip>:/opt/stock-analyzer/data/` (~1.2 GB).
  Also copy `data/cache/screener/` if you want free fundamentals refreshes.
- **Rebuild from scratch on the server:**
  `analyzer initdb && analyzer sync-symbols && analyzer backfill --bulk &&
  analyzer technicals && analyzer universe` (~1–2 hours; also re-run the
  research ingests if you need the results calendar:
  `python -m analyzer.research.results_calendar`).

Then verify: `.venv/bin/analyzer status` and `.venv/bin/analyzer daily`.

## 5. Schedule (cron)

```bash
crontab -e
```
```cron
# Stock analyzer — system TZ is Asia/Kolkata
0 19 * * 1-5   /opt/stock-analyzer/scripts/run_daily.sh
*/15 9-15 * * 1-5  /opt/stock-analyzer/scripts/run_watch.sh
```
The watch command exits instantly outside 09:15–15:35 and on NSE holidays, so
the coarse cron window is fine.

## 6. Telegram credentials

Cron doesn't read your shell profile. Put the credentials where the wrappers
inherit them — simplest is `/etc/environment`:

```
ANALYZER_TG_BOT_TOKEN="123456:ABC..."
ANALYZER_TG_CHAT_ID="123456789"
```
(then reboot or re-login), and set `notify.telegram_enabled: true` in
`config.yaml`.

## 7. Dashboard (optional, via systemd)

```ini
# /etc/systemd/system/stock-analyzer-dash.service
[Unit]
Description=Stock Analyzer dashboard
After=network.target

[Service]
WorkingDirectory=/opt/stock-analyzer
ExecStart=/opt/stock-analyzer/.venv/bin/analyzer serve --host 127.0.0.1 --port 8000
Restart=on-failure
User=ubuntu

[Install]
WantedBy=multi-user.target
```
`sudo systemctl enable --now stock-analyzer-dash`, then access through the SSH
tunnel. Note: DuckDB is single-writer — a dashboard request during the nightly
job may briefly return 503; harmless.

## 7b. Two-way Telegram bot (optional, log trades by chat)

```ini
# /etc/systemd/system/stock-analyzer-bot.service
[Unit]
Description=Stock Analyzer Telegram bot
After=network.target

[Service]
WorkingDirectory=/opt/stock-analyzer
EnvironmentFile=/etc/environment
ExecStart=/opt/stock-analyzer/.venv/bin/analyzer bot
Restart=on-failure
User=ubuntu

[Install]
WantedBy=multi-user.target
```
`sudo systemctl enable --now stock-analyzer-bot`. Run only ONE bot instance
across all machines (Telegram getUpdates is single-consumer). If you keep
ingestion on your PC and only host the bot/dashboard here, that's fine — but
don't run the bot on both at once.

## 7c. Backups → Oracle Object Storage (do this — the data is un-regenerable)

Your positions, live signal outcomes, fills, tuned config, and research log
cannot be rebuilt if the instance dies. Prices can; those ride along in the DB
copy for free. Two tiers:

- **Tier 1 (local, automatic):** `analyzer backup` writes a verified snapshot to
  `backups/` (keeps 4 full copies). Verified = the copy is reopened read-only and
  row-counted.
- **Tier 2 (offsite, survives the instance):** the wrapper pushes only
  `critical.duckdb` — the un-regenerable tables (positions, fills, signal
  outcomes, signals, config-scale data), **~1.3 MB**, NOT the 1.4 GB full DB.
  Prices/indicators are re-backfillable in ~2 hours, so they don't belong
  offsite. At ~1.3 MB/week with 26-week retention (~34 MB total), the free
  10 GB bucket **never fills** — you'd need ~150 years to reach the limit.
  Restore = re-provision, restore critical.duckdb, then `analyzer backfill --bulk`
  to rebuild the price history.

Optional belt-and-suspenders: set a **bucket lifecycle rule** in the console
(auto-delete objects older than 180 days) so retention is enforced server-side
even if a cron run is missed.

One-time Object Storage setup:
```bash
# 1. Create a bucket in the console (Storage -> Buckets), e.g. stock-analyzer-backups
# 2. Configure the OCI CLI on the instance:
sudo apt install -y python3-oci-cli        # or: bash -c "$(curl -L https://raw.githubusercontent.com/oracle/oci-cli/master/scripts/install/install.sh)"
oci setup config                            # follow prompts; upload the generated public key in the console
# 3. Tell the wrapper which bucket (in /etc/environment so cron sees it):
#    ANALYZER_OS_BUCKET="stock-analyzer-backups"
```

Cron (system TZ = Asia/Kolkata) — Sunday 10:00, when nothing else writes:
```cron
0 10 * * 0   /opt/stock-analyzer/scripts/run_backup.sh
```
The wrapper does the local snapshot, then (if `oci` is configured and
`ANALYZER_OS_BUCKET` is set) uploads the DB as `analyzer_YYYYMMDD.duckdb`. If the
upload fails, the local snapshot is still good and the log says so.

**Restore drill (do it once so you know it works):**
```bash
oci os object get --bucket-name "$ANALYZER_OS_BUCKET" --name critical_YYYYMMDD.duckdb \
  --file /tmp/restore.duckdb
.venv/bin/python -c "import duckdb; c=duckdb.connect('/tmp/restore.duckdb', read_only=True); \
  print('positions:', c.execute('SELECT COUNT(*) FROM positions').fetchone()[0])"
```
A backup you have never restored is a hope, not a backup.

## 8. Known risks on a datacenter IP

- **NSE and Yahoo throttle cloud IPs more than home connections.** The clients
  already retry with backoff, but expect occasional failed evenings — the
  pipeline is idempotent, and the next day's run (or a manual
  `analyzer daily --date YYYY-MM-DD`) backfills a missed day.
- Validate before trusting: after deploying, watch `logs/daily_*.log` for a few
  days and check `analyzer status` (job_runs should show OK rows).
- If NSE blocks persistently, the fallback order is: run ingestion on your PC
  (Task Scheduler as today) and `scp`/sync the DuckDB file to the server, or
  switch primary EOD ingestion to yfinance bulk (already built:
  `analyzer backfill --bulk --years 1` daily is a serviceable, if cruder, feed).

## 9. Ongoing upkeep

- The DB grows ~1 MB/day (~0.4 GB/yr) — irrelevant vs 200 GB.
- `data/cache/` and `logs/` self-prune (wrappers) or stay static.
- To update code: `git pull` (or re-scp) + `.venv/bin/pip install -e .` — the
  DB schema applies additively on next open.
