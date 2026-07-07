"""Tests for the schema-migration mechanism.

The key guarantee: opening an OLD-shape database (created by earlier code, missing
a column) upgrades it in place — adding the column — WITHOUT losing existing rows.
This is what makes 'edit code, redeploy' safe on the live observational DB.
"""

import duckdb

from analyzer.db.repository import _split_statements, apply_migrations, connect


def test_split_statements_ignores_comments_and_blanks():
    sql = """
    -- a comment
    ALTER TABLE t ADD COLUMN IF NOT EXISTS a INT;

    -- another
    ALTER TABLE t ADD COLUMN IF NOT EXISTS b INT;
    """
    stmts = _split_statements(sql)
    assert len(stmts) == 2
    assert all("ALTER" in s for s in stmts)
    assert not any(s.strip().startswith("--") for s in stmts)


def test_apply_migrations_is_idempotent(tmp_path):
    # Two opens of the same DB must not error (every statement runs each time).
    db = tmp_path / "a.duckdb"
    con1 = connect(db)
    con1.close()
    con2 = connect(db)   # migrations run again — must be a no-op, not a failure
    con2.close()


def test_old_db_gains_missing_column_without_data_loss(tmp_path, monkeypatch):
    from analyzer.db import repository as repo_mod

    db = tmp_path / "old.duckdb"

    # 1. Simulate an OLD database: a table WITHOUT the future column, with data.
    raw = duckdb.connect(str(db))
    raw.execute("CREATE TABLE positions (position_id TEXT, symbol TEXT, qty INTEGER)")
    raw.execute("INSERT INTO positions VALUES ('p1', 'CGPOWER', 100)")
    raw.close()

    # 2. New code ships a migration adding a 'strategy_tag' column to positions.
    mig = tmp_path / "migrations.sql"
    mig.write_text(
        "ALTER TABLE positions ADD COLUMN IF NOT EXISTS strategy_tag TEXT;\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(repo_mod, "_MIGRATIONS_PATH", mig)
    # Skip the real schema.sql for this focused test (avoid unrelated CREATEs).
    empty_schema = tmp_path / "schema.sql"
    empty_schema.write_text("-- none\n", encoding="utf-8")
    monkeypatch.setattr(repo_mod, "_SCHEMA_PATH", empty_schema)

    # 3. Open with the new code -> migration runs.
    con = connect(db)
    cols = [r[1] for r in con.execute("PRAGMA table_info(positions)").fetchall()]
    assert "strategy_tag" in cols                     # column added
    row = con.execute("SELECT symbol, qty FROM positions WHERE position_id='p1'").fetchone()
    assert row == ("CGPOWER", 100)                    # existing data preserved
    con.close()


def test_bad_migration_does_not_block_open(tmp_path, monkeypatch):
    from analyzer.db import repository as repo_mod

    db = tmp_path / "b.duckdb"
    mig = tmp_path / "migrations.sql"
    # A statement referencing a non-existent table must be logged & skipped,
    # not crash the connection (data-safety over strictness).
    mig.write_text(
        "ALTER TABLE does_not_exist ADD COLUMN IF NOT EXISTS x INT;\n"
        "CREATE TABLE IF NOT EXISTS marker (id INT);\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(repo_mod, "_MIGRATIONS_PATH", mig)
    empty_schema = tmp_path / "schema.sql"
    empty_schema.write_text("-- none\n", encoding="utf-8")
    monkeypatch.setattr(repo_mod, "_SCHEMA_PATH", empty_schema)

    con = connect(db)   # must not raise despite the bad first statement
    tables = {r[0] for r in con.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    assert "marker" in tables   # the good statement after the bad one still ran
    con.close()


def test_real_migrations_apply_to_real_schema(tmp_path):
    # The shipped migrations.sql must apply cleanly on top of the real schema.
    db = tmp_path / "real.duckdb"
    con = connect(db)
    n = apply_migrations(con)   # run again explicitly
    assert n >= 1               # at least the placeholder ran without error
    con.close()
