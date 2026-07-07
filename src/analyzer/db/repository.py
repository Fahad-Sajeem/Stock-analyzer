"""DuckDB repository — the ONLY place raw SQL lives.

Design rules (PLAN Section 5):
  * Idempotent writes: ``upsert_df`` uses INSERT OR REPLACE on primary keys so
    re-running a day's job never duplicates rows.
  * Observability: every pipeline wraps work in ``job_run(...)`` which writes a
    row to ``job_runs`` (started/finished/status/rows/error).
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Sequence

import duckdb
import pandas as pd

from analyzer.logging_setup import get_logger

log = get_logger(__name__)

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: str | Path, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    """Open (creating parent dirs) a DuckDB connection and apply the schema."""
    db_path = Path(db_path)
    if str(db_path) != ":memory:":
        db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path), read_only=read_only)
    if not read_only:
        con.execute(_SCHEMA_PATH.read_text(encoding="utf-8"))
    return con


class JobRun:
    """Handle returned by ``Repository.job_run`` so the body can report row counts."""

    def __init__(self) -> None:
        self.rows_written = 0

    def add_rows(self, n: int) -> None:
        self.rows_written += int(n)


class Repository:
    """Thin typed wrapper over a DuckDB connection."""

    def __init__(self, con: duckdb.DuckDBPyConnection) -> None:
        self.con = con

    @classmethod
    def open(cls, db_path: str | Path, read_only: bool = False) -> "Repository":
        return cls(connect(db_path, read_only=read_only))

    def close(self) -> None:
        self.con.close()

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # --- schema introspection -------------------------------------------------
    def table_columns(self, table: str) -> list[str]:
        rows = self.con.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = ? ORDER BY ordinal_position",
            [table],
        ).fetchall()
        return [r[0] for r in rows]

    # --- generic query helpers ------------------------------------------------
    def query_df(self, sql: str, params: Sequence[Any] | None = None) -> pd.DataFrame:
        return self.con.execute(sql, params or []).df()

    def execute(self, sql: str, params: Sequence[Any] | None = None) -> None:
        self.con.execute(sql, params or [])

    def scalar(self, sql: str, params: Sequence[Any] | None = None) -> Any:
        row = self.con.execute(sql, params or []).fetchone()
        return row[0] if row else None

    def count(self, table: str) -> int:
        return int(self.scalar(f"SELECT COUNT(*) FROM {table}") or 0)

    # --- idempotent bulk upsert ----------------------------------------------
    def upsert_df(self, table: str, df: pd.DataFrame) -> int:
        """INSERT OR REPLACE a DataFrame into ``table`` (idempotent on PK).

        Only columns that exist in BOTH the DataFrame and the table are written;
        the rest fall back to table defaults / NULL. Returns rows written.
        """
        if df is None or df.empty:
            return 0
        table_cols = set(self.table_columns(table))
        cols = [c for c in df.columns if c in table_cols]
        if not cols:
            raise ValueError(
                f"upsert_df: DataFrame has no columns matching table '{table}'. "
                f"df cols={list(df.columns)}"
            )
        payload = df[cols]
        col_list = ", ".join(f'"{c}"' for c in cols)
        # Register the frame as a temporary view for a set-based upsert.
        self.con.register("_upsert_src", payload)
        try:
            self.con.execute(
                f'INSERT OR REPLACE INTO "{table}" ({col_list}) '
                f"SELECT {col_list} FROM _upsert_src"
            )
        finally:
            self.con.unregister("_upsert_src")
        return len(payload)

    def insert_df(self, table: str, df: pd.DataFrame) -> int:
        """Plain INSERT (append-only tables without a primary key, e.g. fills)."""
        if df is None or df.empty:
            return 0
        table_cols = set(self.table_columns(table))
        cols = [c for c in df.columns if c in table_cols]
        if not cols:
            raise ValueError(f"insert_df: no columns match table '{table}'")
        col_list = ", ".join(f'"{c}"' for c in cols)
        self.con.register("_insert_src", df[cols])
        try:
            self.con.execute(
                f'INSERT INTO "{table}" ({col_list}) SELECT {col_list} FROM _insert_src'
            )
        finally:
            self.con.unregister("_insert_src")
        return len(df)

    # --- job-run observability ------------------------------------------------
    @contextmanager
    def job_run(self, job: str) -> Iterator[JobRun]:
        started = datetime.now()
        handle = JobRun()
        self.con.execute(
            "INSERT INTO job_runs (job, started, status, rows_written) VALUES (?, ?, 'RUNNING', 0)",
            [job, started],
        )
        t0 = time.perf_counter()
        try:
            yield handle
        except Exception as exc:  # noqa: BLE001 - we re-raise after logging
            self._finish_job(job, started, "ERROR", handle.rows_written, str(exc))
            log.error("job_failed", job=job, error=str(exc))
            raise
        else:
            self._finish_job(job, started, "OK", handle.rows_written, None)
            log.info(
                "job_done",
                job=job,
                rows=handle.rows_written,
                secs=round(time.perf_counter() - t0, 2),
            )

    def _finish_job(
        self, job: str, started: datetime, status: str, rows: int, error: str | None
    ) -> None:
        # Update the specific RUNNING row we created (match on job+started).
        self.con.execute(
            "UPDATE job_runs SET finished = ?, status = ?, rows_written = ?, error = ? "
            "WHERE job = ? AND started = ? AND status = 'RUNNING'",
            [datetime.now(), status, rows, error, job, started],
        )


def new_id(prefix: str = "") -> str:
    """Short unique id helper for ad-hoc rows (backtest runs, etc.)."""
    return f"{prefix}{uuid.uuid4().hex[:12]}"
