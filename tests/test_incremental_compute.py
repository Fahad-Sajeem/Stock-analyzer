"""Incremental indicator recompute must match the full recompute (equivalence test).

This is the guard that lets the nightly cloud pipeline use incremental mode: if
windowed computation diverged from full-history computation, signals would
silently differ between environments.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from analyzer.db.repository import Repository
from analyzer.technicals.compute import run_compute_indicators

_CHECK_COLS = [
    "ema20", "ema50", "sma200", "adx", "rsi", "macd", "macd_sig", "atr",
    "atr_pct", "bb_width_pctile", "vol_ratio", "obv_slope", "roc20", "roc60",
    "roc120", "dist_52wh", "supertrend", "in_base", "base_days",
    "wk_gate_trend", "wk_gate_mr",
]


def _seed_prices(repo: Repository, symbol: str, n: int = 520, seed: int = 0):
    rng = np.random.default_rng(seed)
    closes = 100 * np.cumprod(1 + rng.normal(0.0004, 0.015, n))
    start = date(2024, 1, 1)
    dates, d = [], start
    while len(dates) < n:  # weekdays only, realistic calendar
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    df = pd.DataFrame({
        "symbol": symbol, "date": dates,
        "open": closes * (1 + rng.normal(0, 0.002, n)),
        "high": closes * (1 + abs(rng.normal(0, 0.008, n))),
        "low": closes * (1 - abs(rng.normal(0, 0.008, n))),
        "close": closes,
        "volume": rng.integers(100_000, 5_000_000, n),
    })
    repo.upsert_df("prices_adj", df.assign(adj_factor=1.0))
    repo.upsert_df("prices_raw", df.assign(traded_value=df.close * df.volume,
                                           delivery_pct=50.0))


def test_incremental_matches_full():
    repo = Repository.open(":memory:")
    for i, sym in enumerate(["AAA", "BBB", "CCC"]):
        _seed_prices(repo, sym, seed=i)

    # Full run = ground truth.
    run_compute_indicators(repo, incremental=False)
    full = repo.query_df(
        "SELECT * FROM indicators_daily ORDER BY symbol, date"
    )
    last_dates = sorted(full["date"].unique())[-4:]  # the tail we'll recompute

    # Wipe the tail, then recompute incrementally (windowed load).
    repo.execute("DELETE FROM indicators_daily WHERE date >= ?", [last_dates[0]])
    n = run_compute_indicators(repo, incremental=True)
    assert n > 0

    incr = repo.query_df("SELECT * FROM indicators_daily ORDER BY symbol, date")
    f_tail = full[full["date"].isin(last_dates)].reset_index(drop=True)
    i_tail = incr[incr["date"].isin(last_dates)].reset_index(drop=True)
    assert len(f_tail) == len(i_tail) > 0

    for col in _CHECK_COLS:
        fv, iv = f_tail[col], i_tail[col]
        if fv.dtype == bool or col in ("in_base", "wk_gate_trend", "wk_gate_mr"):
            assert (fv.fillna(False) == iv.fillna(False)).all(), f"mismatch in {col}"
        elif col == "base_days":
            assert (fv.fillna(0) == iv.fillna(0)).all(), "mismatch in base_days"
        else:
            assert np.allclose(fv.astype(float), iv.astype(float),
                               rtol=1e-5, atol=1e-6, equal_nan=True), f"mismatch in {col}"
    repo.close()


def test_incremental_overlap_rewrite_is_idempotent():
    repo = Repository.open(":memory:")
    _seed_prices(repo, "AAA")
    run_compute_indicators(repo, incremental=False)
    before = repo.query_df("SELECT * FROM indicators_daily ORDER BY date")
    # Re-running with no new prices only re-upserts the small safety overlap
    # (~5 calendar days) and must not change any values or add rows.
    n = run_compute_indicators(repo, incremental=True)
    assert 0 < n <= 5
    after = repo.query_df("SELECT * FROM indicators_daily ORDER BY date")
    assert len(after) == len(before)
    assert np.allclose(before["ema20"].astype(float), after["ema20"].astype(float),
                       equal_nan=True)
    repo.close()


def test_incremental_falls_back_to_full_when_empty():
    repo = Repository.open(":memory:")
    _seed_prices(repo, "AAA")
    # indicators_daily empty -> incremental request must do a full run.
    n = run_compute_indicators(repo, incremental=True)
    assert n > 400
    repo.close()
