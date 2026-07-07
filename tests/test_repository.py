"""Tests for the DuckDB repository: schema apply, idempotent upsert, job logging."""

import pandas as pd

from analyzer.db.repository import Repository


def test_schema_applies_in_memory():
    repo = Repository.open(":memory:")
    tables = repo.query_df(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
    )
    names = set(tables["table_name"])
    for expected in ["symbols", "prices_raw", "prices_adj", "signals", "job_runs", "universe"]:
        assert expected in names
    repo.close()


def test_upsert_is_idempotent():
    repo = Repository.open(":memory:")
    df = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB"],
            "date": [pd.Timestamp("2024-01-01").date(), pd.Timestamp("2024-01-01").date()],
            "open": [10.0, 20.0],
            "high": [11.0, 21.0],
            "low": [9.0, 19.0],
            "close": [10.5, 20.5],
            "volume": [100, 200],
        }
    )
    repo.upsert_df("prices_raw", df)
    repo.upsert_df("prices_raw", df)  # second time must not duplicate
    assert repo.count("prices_raw") == 2

    # Changing a value and re-upserting updates in place (INSERT OR REPLACE).
    df2 = df.copy()
    df2.loc[0, "close"] = 99.0
    repo.upsert_df("prices_raw", df2)
    assert repo.count("prices_raw") == 2
    val = repo.scalar("SELECT close FROM prices_raw WHERE symbol='AAA'")
    assert val == 99.0
    repo.close()


def test_upsert_ignores_unknown_columns():
    repo = Repository.open(":memory:")
    df = pd.DataFrame({"symbol": ["X"], "date": [pd.Timestamp("2024-01-01").date()],
                       "close": [5.0], "bogus_col": ["ignored"]})
    n = repo.upsert_df("prices_raw", df)
    assert n == 1
    repo.close()


def test_job_run_logs_ok_and_error():
    repo = Repository.open(":memory:")
    with repo.job_run("t_ok") as jr:
        jr.add_rows(5)
    row = repo.query_df("SELECT status, rows_written FROM job_runs WHERE job='t_ok'")
    assert row.iloc[0]["status"] == "OK"
    assert row.iloc[0]["rows_written"] == 5

    try:
        with repo.job_run("t_err"):
            raise ValueError("boom")
    except ValueError:
        pass
    row = repo.query_df("SELECT status, error FROM job_runs WHERE job='t_err'")
    assert row.iloc[0]["status"] == "ERROR"
    assert "boom" in row.iloc[0]["error"]
    repo.close()
