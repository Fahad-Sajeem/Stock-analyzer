"""Data-quality validation layer (PLAN 4.2 pt.6).

Catches the silent data bugs that poison technical signals: OHLC integrity
violations, zero-volume days, implausible price jumps, and missing trading days
vs. the NSE calendar. Returns a structured report; never mutates the data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from analyzer.config import get_config
from analyzer.data.calendar import TradingCalendar
from analyzer.logging_setup import get_logger

log = get_logger(__name__)


@dataclass
class ValidationReport:
    checked_symbols: int = 0
    checked_rows: int = 0
    ohlc_violations: pd.DataFrame = field(default_factory=pd.DataFrame)
    zero_volume: pd.DataFrame = field(default_factory=pd.DataFrame)
    big_moves: pd.DataFrame = field(default_factory=pd.DataFrame)
    missing_days: dict[str, list[date]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.ohlc_violations.empty and self.checked_rows > 0

    def summary(self) -> dict:
        return {
            "checked_symbols": self.checked_symbols,
            "checked_rows": self.checked_rows,
            "ohlc_violations": len(self.ohlc_violations),
            "zero_volume": len(self.zero_volume),
            "big_moves": len(self.big_moves),
            "symbols_with_gaps": len(self.missing_days),
        }


def check_ohlc_integrity(df: pd.DataFrame) -> pd.DataFrame:
    """Rows where high < max(open, close) or low > min(open, close), or non-positive."""
    hi_ok = df["high"] >= df[["open", "close", "low"]].max(axis=1) - 1e-6
    lo_ok = df["low"] <= df[["open", "close", "high"]].min(axis=1) + 1e-6
    positive = (df[["open", "high", "low", "close"]] > 0).all(axis=1)
    bad = ~(hi_ok & lo_ok & positive)
    return df.loc[bad, ["symbol", "date", "open", "high", "low", "close"]]


def check_big_moves(df: pd.DataFrame, max_move_pct: float) -> pd.DataFrame:
    """Day-over-day close moves exceeding the threshold (candidate CA/data errors)."""
    out = []
    for sym, grp in df.sort_values("date").groupby("symbol"):
        pct = grp["close"].pct_change().abs() * 100
        flagged = grp.loc[pct > max_move_pct, ["symbol", "date", "close"]].copy()
        if not flagged.empty:
            flagged["move_pct"] = pct[pct > max_move_pct].values
            out.append(flagged)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def validate_prices(
    df: pd.DataFrame,
    calendar: TradingCalendar | None = None,
    check_gaps: bool = False,
) -> ValidationReport:
    """Run all data-quality checks over a ``prices_raw``-shaped frame."""
    cfg = get_config()
    rep = ValidationReport()
    if df.empty:
        return rep
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date

    rep.checked_symbols = df["symbol"].nunique()
    rep.checked_rows = len(df)
    rep.ohlc_violations = check_ohlc_integrity(df)
    rep.zero_volume = df.loc[df["volume"] <= cfg.validation.min_volume, ["symbol", "date"]]
    rep.big_moves = check_big_moves(df, cfg.validation.max_daily_move_pct)

    if check_gaps and calendar is not None:
        for sym, grp in df.groupby("symbol"):
            dates = set(grp["date"])
            if not dates:
                continue
            expected = calendar.trading_days(min(dates), max(dates))
            missing = [d for d in expected if d not in dates]
            if missing:
                rep.missing_days[sym] = missing

    log.info("validation_done", **rep.summary())
    return rep
