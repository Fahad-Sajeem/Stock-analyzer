"""NSE trading calendar.

Seeds the ``holidays_nse`` table from the packaged CSV and provides trading-day
helpers used by every scheduler/pipeline (jobs must be holiday-aware, PLAN 15).

The CSV is a starting seed; PLAN Section 15 schedules a monthly refresh job that
can pull the official NSE holiday list and upsert new rows.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from analyzer.db.repository import Repository
from analyzer.logging_setup import get_logger

log = get_logger(__name__)

_CSV_PATH = Path(__file__).with_name("holidays_nse.csv")


def seed_holidays(repo: Repository, csv_path: Path | None = None) -> int:
    """Load the packaged holiday CSV into ``holidays_nse`` (idempotent upsert)."""
    df = pd.read_csv(csv_path or _CSV_PATH, parse_dates=["holiday_date"])
    df["holiday_date"] = df["holiday_date"].dt.date
    n = repo.upsert_df("holidays_nse", df)
    log.info("holidays_seeded", rows=n)
    return n


class TradingCalendar:
    """In-memory trading calendar backed by the holiday set from the DB."""

    def __init__(self, holidays: set[date]) -> None:
        self.holidays = holidays

    @classmethod
    def from_repo(cls, repo: Repository) -> "TradingCalendar":
        rows = repo.query_df("SELECT holiday_date FROM holidays_nse")
        hols = set(pd.to_datetime(rows["holiday_date"]).dt.date) if not rows.empty else set()
        return cls(hols)

    def is_trading_day(self, d: date) -> bool:
        # Monday=0 .. Sunday=6; NSE trades Mon-Fri excluding holidays.
        return d.weekday() < 5 and d not in self.holidays

    def previous_trading_day(self, d: date) -> date:
        cur = d - timedelta(days=1)
        while not self.is_trading_day(cur):
            cur -= timedelta(days=1)
        return cur

    def next_trading_day(self, d: date) -> date:
        cur = d + timedelta(days=1)
        while not self.is_trading_day(cur):
            cur += timedelta(days=1)
        return cur

    def trading_days(self, start: date, end: date) -> list[date]:
        out: list[date] = []
        cur = start
        while cur <= end:
            if self.is_trading_day(cur):
                out.append(cur)
            cur += timedelta(days=1)
        return out

    def add_sessions(self, d: date, n: int) -> date:
        """Return the date ``n`` trading sessions after ``d`` (n may be negative)."""
        step = 1 if n >= 0 else -1
        remaining = abs(n)
        cur = d
        while remaining > 0:
            cur += timedelta(days=step)
            if self.is_trading_day(cur):
                remaining -= 1
        return cur
