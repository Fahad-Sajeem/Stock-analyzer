"""Backup job — protect the un-regenerable data (positions, live signal outcomes,
fills, the tuned config, and the research record).

Local backup is tier 1 (fast restore); the wrapper (scripts/run_backup.sh) pushes
the same file to Oracle Object Storage as tier 2 (survives the whole instance).

Safety: DuckDB is single-writer. This runs when no pipeline writes (Sunday
morning). It best-effort CHECKPOINTs to fold the WAL into the main file, then
copies, then VERIFIES the copy by opening it read-only and counting rows — an
unverified backup is a hope, not a backup.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from analyzer.config import Config, get_config
from analyzer.logging_setup import get_logger

log = get_logger(__name__)

# Files copied alongside the DB (the irreplaceable, non-price artifacts).
_EXTRA_FILES = ["config.yaml", "PLAN.md", "RESEARCH_PLAN.md", "RESEARCH_LOG.md",
                "README.md", "DEPLOY.md"]
# Tables whose row counts are logged as a sanity check on the copy.
_VERIFY_TABLES = ["positions", "signal_outcomes", "fills", "signals",
                  "prices_raw", "indicators_daily"]

# The un-regenerable tables. Everything else (prices, indicators, fundamentals,
# calendar, regime, indices) is re-backfillable from public data in ~2 hours, so
# it does NOT belong in the tiny offsite export. These stay a few KB-MB for years.
_CRITICAL_TABLES = ["positions", "fills", "signal_outcomes", "signals",
                    "alerts_log", "backtest_results", "job_runs"]


def _checkpoint(db_path: Path) -> None:
    """Best-effort WAL flush. If something holds the write lock, skip and rely on
    copying the .wal alongside the main file (still a consistent pair)."""
    try:
        import duckdb

        con = duckdb.connect(str(db_path))
        con.execute("CHECKPOINT")
        con.close()
        log.debug("backup_checkpoint_ok")
    except Exception as exc:  # noqa: BLE001
        log.warning("backup_checkpoint_skipped", error=str(exc))


def export_critical(db_path: Path, out_path: Path) -> dict:
    """Write a small DuckDB holding ONLY the un-regenerable tables + a copy of the
    config/research files' text. This is what goes offsite — a few KB-MB, so the
    free 10 GB Object Storage bucket never fills. Returns {table: rows}."""
    import duckdb

    src = duckdb.connect(str(db_path), read_only=True)
    dst = duckdb.connect(str(out_path))
    counts = {}
    try:
        existing = {r[0] for r in src.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
        ).fetchall()}
        for t in _CRITICAL_TABLES:
            if t not in existing:
                continue
            df = src.execute(f"SELECT * FROM {t}").df()  # small tables only
            dst.register("_t", df)
            dst.execute(f'CREATE TABLE "{t}" AS SELECT * FROM _t')
            dst.unregister("_t")
            counts[t] = len(df)
        dst.execute("CHECKPOINT")
    finally:
        dst.close()
        src.close()
    return counts


def _verify(copy_path: Path) -> dict:
    """Open the COPY read-only and count rows — proves it's a usable database."""
    import duckdb

    con = duckdb.connect(str(copy_path), read_only=True)
    try:
        counts = {}
        for t in _VERIFY_TABLES:
            try:
                counts[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except Exception:  # noqa: BLE001 - table may not exist on older DBs
                counts[t] = None
        return counts
    finally:
        con.close()


def run_backup(repo_db_path: Path | None = None, cfg: Config | None = None,
               dest_dir: str | Path | None = None, keep: int = 4) -> dict:
    """Create a verified local backup. Returns a manifest dict (paths + counts)."""
    cfg = cfg or get_config()
    db_path = Path(repo_db_path) if repo_db_path else cfg.db_path
    if not db_path.exists():
        raise FileNotFoundError(f"database not found: {db_path}")

    dest = Path(dest_dir) if dest_dir else cfg.path("backups")
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    snap_dir = dest / stamp
    snap_dir.mkdir()

    _checkpoint(db_path)

    # Copy the DB (+ WAL if a checkpoint couldn't flush it) and the extra files.
    db_copy = snap_dir / db_path.name
    shutil.copy2(db_path, db_copy)
    wal = db_path.with_suffix(db_path.suffix + ".wal")
    if wal.exists():
        shutil.copy2(wal, snap_dir / wal.name)
    for name in _EXTRA_FILES:
        src = cfg.root / name
        if src.exists():
            shutil.copy2(src, snap_dir / name)

    counts = _verify(db_copy)
    size_mb = round(db_copy.stat().st_size / 1e6, 1)

    # Small offsite-friendly export (the un-regenerable tables only).
    crit_path = snap_dir / "critical.duckdb"
    crit_counts = export_critical(db_copy, crit_path)
    crit_kb = round(crit_path.stat().st_size / 1e3, 1)

    # Retention: keep the newest ``keep`` snapshot dirs.
    snaps = sorted([p for p in dest.iterdir() if p.is_dir()], reverse=True)
    removed = 0
    for old in snaps[keep:]:
        shutil.rmtree(old, ignore_errors=True)
        removed += 1

    manifest = {
        "snapshot": str(snap_dir), "db_size_mb": size_mb,
        "critical_path": str(crit_path), "critical_kb": crit_kb,
        "critical_counts": crit_counts,
        "verified_counts": counts, "pruned_old": removed,
    }
    log.info("backup_done", snapshot=stamp, db_size_mb=size_mb, critical_kb=crit_kb,
             positions=counts.get("positions"), outcomes=counts.get("signal_outcomes"),
             pruned=removed)
    return manifest
