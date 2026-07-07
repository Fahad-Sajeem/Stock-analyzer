"""Point-in-time quality panel from ``fundamentals_history`` (R3 building block).

Produces, for any as-of date, a per-symbol quality snapshot using ONLY rows with
``available_from <= as_of`` (contract R-5). Metrics mirror the production quality
score's spirit but are computed from the scraped panel:

  roce_pct        latest annual ROCE
  sales_growth    3yr sales CAGR (annual)
  eps_growth      latest-annual EPS YoY
  cfo_positive    CFO > 0 in latest annual
  de_proxy        borrowings / (equity_capital + reserves)
  promoter_pct    latest shareholding promoter %
  quality_flag    simple boolean gate (see ``quality_gate``)

The panel is built once for a grid of dates (e.g. month-ends) and joined as-of by
research backtests.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from analyzer.logging_setup import get_logger

log = get_logger(__name__)


def load_history(repo) -> pd.DataFrame:
    df = repo.query_df(
        "SELECT symbol, period, period_end, freq, metric, value, available_from "
        "FROM fundamentals_history"
    )
    if df.empty:
        return df
    df["period_end"] = pd.to_datetime(df["period_end"])
    df["available_from"] = pd.to_datetime(df["available_from"])
    return df


def _latest(df: pd.DataFrame, metric: str, asof: pd.Timestamp, freq: str = "A") -> pd.Series:
    """Latest available value per symbol for one metric as of ``asof``."""
    sub = df[(df.metric == metric) & (df.freq == freq) & (df.available_from <= asof)]
    if sub.empty:
        return pd.Series(dtype="float64")
    sub = sub.sort_values("period_end").groupby("symbol").tail(1)
    return pd.Series(sub.value.values, index=sub.symbol.values)


def _annual_series(df: pd.DataFrame, metric: str, asof: pd.Timestamp) -> pd.DataFrame:
    """All available annual values per symbol (for growth calcs)."""
    sub = df[(df.metric == metric) & (df.freq == "A") & (df.available_from <= asof)]
    return sub.sort_values("period_end")


def build_snapshot(hist: pd.DataFrame, asof: date | pd.Timestamp) -> pd.DataFrame:
    """Quality snapshot for one as-of date. Returns df indexed by symbol."""
    asof = pd.Timestamp(asof)

    roce = _latest(hist, "roce_pct", asof)
    promoter = _latest(hist, "promoter_pct", asof, freq="SH")
    cfo = _latest(hist, "cfo", asof)
    eq = _latest(hist, "equity_capital", asof)
    res = _latest(hist, "reserves", asof)
    borrow = _latest(hist, "borrowings", asof)

    # 3yr sales CAGR + latest EPS YoY from annual series.
    sales = _annual_series(hist, "sales", asof)
    growth = {}
    for sym, g in sales.groupby("symbol"):
        v = g.value.to_numpy()
        if len(v) >= 4 and v[-4] > 0 and v[-1] > 0:
            growth[sym] = ((v[-1] / v[-4]) ** (1 / 3) - 1) * 100
    sales_growth = pd.Series(growth)

    eps = _annual_series(hist, "eps", asof)
    eps_g = {}
    for sym, g in eps.groupby("symbol"):
        v = g.value.to_numpy()
        if len(v) >= 2 and v[-2] != 0:
            eps_g[sym] = (v[-1] - v[-2]) / abs(v[-2]) * 100
    eps_growth = pd.Series(eps_g)

    symbols = sorted(
        set(roce.index) | set(sales_growth.index) | set(promoter.index) | set(cfo.index)
    )
    snap = pd.DataFrame(index=symbols)
    snap["roce_pct"] = roce
    snap["sales_growth"] = sales_growth
    snap["eps_growth"] = eps_growth
    snap["cfo_positive"] = (cfo > 0).reindex(symbols)
    networth = (eq.reindex(symbols).fillna(0) + res.reindex(symbols).fillna(0))
    snap["de_proxy"] = borrow.reindex(symbols) / networth.replace(0, np.nan)
    snap["promoter_pct"] = promoter
    return snap


def quality_gate(snap: pd.DataFrame) -> pd.Series:
    """Boolean quality gate per symbol (registered thresholds — see EXP-003 when
    it is created; do not tweak without a new log entry).

    Gate: ROCE >= 15 AND CFO positive AND (D/E proxy < 1.0 or is a financial
    where borrowings are business-model — proxied here by ROCE presence with
    high D/E being allowed if ROCE >= 12) AND 3yr sales CAGR > 5.
    Symbols missing ALL inputs fail (unverifiable = not allowed).
    """
    roce_ok = snap["roce_pct"] >= 15
    cfo_ok = snap["cfo_positive"].fillna(False)
    de = snap["de_proxy"]
    de_ok = (de < 1.0) | (de.isna()) | ((de >= 1.0) & (snap["roce_pct"] >= 12))
    growth_ok = snap["sales_growth"] > 5
    return (roce_ok & cfo_ok & de_ok & growth_ok).fillna(False)


def build_quality_panel(repo, dates: list[date]) -> pd.DataFrame:
    """Quality gate per (date, symbol) for a list of as-of dates (long format)."""
    hist = load_history(repo)
    if hist.empty:
        raise RuntimeError("fundamentals_history is empty — run the EXP-002 scrape first")
    frames = []
    for d in dates:
        snap = build_snapshot(hist, d)
        frames.append(
            pd.DataFrame(
                {"date": pd.Timestamp(d), "symbol": snap.index,
                 "quality_ok": quality_gate(snap).values,
                 "roce_pct": snap["roce_pct"].values}
            )
        )
    panel = pd.concat(frames, ignore_index=True)
    log.info("quality_panel_built", dates=len(dates),
             avg_pass=round(float(panel.groupby('date')['quality_ok'].mean().mean()) * 100, 1))
    return panel
