"""Tests for the backup job: snapshot creation, verification, retention."""

from pathlib import Path

import duckdb
import pandas as pd
import pytest

from analyzer.jobs.backup import export_critical, run_backup


def _make_db(path: Path, n_positions: int = 3) -> None:
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE positions (position_id TEXT, symbol TEXT, qty INTEGER)")
    con.execute("CREATE TABLE signal_outcomes (signal_id TEXT, outcome TEXT)")
    con.execute("CREATE TABLE fills (position_id TEXT, side TEXT)")
    con.execute("CREATE TABLE signals (signal_id TEXT)")
    con.execute("CREATE TABLE prices_raw (symbol TEXT, date DATE)")
    con.execute("CREATE TABLE indicators_daily (symbol TEXT, date DATE)")
    con.executemany("INSERT INTO positions VALUES (?, ?, ?)",
                    [(f"p{i}", "X", 10) for i in range(n_positions)])
    con.close()


def test_backup_creates_verified_snapshot(tmp_path):
    db = tmp_path / "analyzer.duckdb"
    _make_db(db, n_positions=5)
    dest = tmp_path / "backups"

    manifest = run_backup(repo_db_path=db, dest_dir=dest, keep=4)

    snap = Path(manifest["snapshot"])
    assert (snap / "analyzer.duckdb").exists()
    # Verification actually counted rows from the COPY, not the original.
    assert manifest["verified_counts"]["positions"] == 5
    assert manifest["db_size_mb"] >= 0


def test_backup_copies_extra_files(tmp_path, monkeypatch):
    db = tmp_path / "analyzer.duckdb"
    _make_db(db)
    # Fake a repo root with a config.yaml to copy.
    (tmp_path / "config.yaml").write_text("dummy: 1", encoding="utf-8")
    from analyzer.config import get_config
    cfg = get_config()
    monkeypatch.setattr(cfg, "root", tmp_path)

    manifest = run_backup(repo_db_path=db, cfg=cfg, dest_dir=tmp_path / "bk", keep=4)
    assert (Path(manifest["snapshot"]) / "config.yaml").exists()


def test_backup_retention_prunes_old(tmp_path):
    db = tmp_path / "analyzer.duckdb"
    _make_db(db)
    dest = tmp_path / "backups"
    # Create 6 snapshots keeping 4 -> 2 pruned across the run of runs.
    import time
    for _ in range(6):
        run_backup(repo_db_path=db, dest_dir=dest, keep=4)
        time.sleep(1.05)  # distinct second-resolution timestamps
    remaining = [p for p in dest.iterdir() if p.is_dir()]
    assert len(remaining) == 4


def test_backup_missing_db_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        run_backup(repo_db_path=tmp_path / "nope.duckdb", dest_dir=tmp_path / "b")


def test_critical_export_is_small_and_restorable(tmp_path):
    db = tmp_path / "analyzer.duckdb"
    _make_db(db, n_positions=7)
    # Add bulk "regenerable" data that must NOT bloat the critical export.
    con = duckdb.connect(str(db))
    con.executemany("INSERT INTO prices_raw VALUES (?, ?)",
                    [("X", f"2020-01-{(i % 28) + 1:02d}") for i in range(50_000)])
    con.close()

    out = tmp_path / "critical.duckdb"
    counts = export_critical(db, out)
    assert counts["positions"] == 7
    assert "prices_raw" not in counts          # bulk data excluded by design

    # The export opens read-only and the positions survive the round-trip.
    rc = duckdb.connect(str(out), read_only=True)
    assert rc.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 7
    assert "prices_raw" not in {
        r[0] for r in rc.execute(
            "SELECT table_name FROM information_schema.tables").fetchall()}
    rc.close()

    # And it's tiny vs the full DB (the whole point).
    assert out.stat().st_size < db.stat().st_size


def test_run_backup_includes_critical(tmp_path):
    db = tmp_path / "analyzer.duckdb"
    _make_db(db, n_positions=3)
    manifest = run_backup(repo_db_path=db, dest_dir=tmp_path / "bk", keep=4)
    assert Path(manifest["critical_path"]).exists()
    assert manifest["critical_counts"]["positions"] == 3
    assert manifest["critical_kb"] >= 0
