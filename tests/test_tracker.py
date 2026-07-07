"""Tests for the signal-outcome tracker (in-memory repo, synthetic prices)."""

from datetime import date, timedelta

import pandas as pd

from analyzer.db.repository import Repository
from analyzer.risk.tracker import update_signal_outcomes


def _seed(repo: Repository, symbol: str, sig_date: date, prices: list[tuple], t1=106.0):
    """Insert one signal + subsequent daily bars (o,h,l,c)."""
    repo.upsert_df("signals", pd.DataFrame([{
        "signal_id": f"{sig_date}-{symbol}-A", "date": sig_date, "symbol": symbol,
        "setup": "A_momentum_breakout", "direction": "LONG", "grade": "A",
        "composite_score": 80.0, "entry_aggressive": 100.0, "entry_conservative": 99.0,
        "entry_valid_till": sig_date + timedelta(days=7), "stop_loss": 96.0,
        "t1": t1, "t2": 112.0, "rr": 3.0, "suggested_risk_pct": 1.0,
    }]))
    rows = []
    for i, (o, h, l, c) in enumerate(prices, 1):
        rows.append({"symbol": symbol, "date": sig_date + timedelta(days=i),
                     "open": o, "high": h, "low": l, "close": c,
                     "volume": 1000, "adj_factor": 1.0})
    repo.upsert_df("prices_adj", pd.DataFrame(rows))


def test_tracker_marks_t2_hit():
    repo = Repository.open(":memory:")
    sig_date = date.today() - timedelta(days=10)
    _seed(repo, "WINNER", sig_date, [
        (100, 101, 99, 100),      # entry triggers
        (105, 107, 104, 106),     # T1
        (110, 113, 109, 112),     # T2
    ])
    summary = update_signal_outcomes(repo)
    assert summary["terminal"] == 1
    out = repo.query_df("SELECT * FROM signal_outcomes").iloc[0]
    assert out["outcome"] == "T2_HIT"
    assert bool(out["triggered"])
    assert out["realized_r"] > 1.5
    repo.close()


def test_tracker_open_when_in_flight():
    repo = Repository.open(":memory:")
    sig_date = date.today() - timedelta(days=5)
    _seed(repo, "FLIGHT", sig_date, [
        (100, 101, 99, 100),      # entered
        (101, 102, 100, 101),     # drifting, nothing hit
    ])
    summary = update_signal_outcomes(repo)
    assert summary["terminal"] == 0
    out = repo.query_df("SELECT * FROM signal_outcomes").iloc[0]
    assert out["outcome"] == "OPEN"
    assert bool(out["triggered"])
    repo.close()


def test_tracker_pending_entry_stays_open():
    repo = Repository.open(":memory:")
    sig_date = date.today() - timedelta(days=3)
    # Only 2 bars, never reached entry -> window still running -> OPEN not EXPIRED.
    _seed(repo, "PEND", sig_date, [(95, 96, 94, 95), (95, 96, 94, 95)])
    update_signal_outcomes(repo)
    out = repo.query_df("SELECT * FROM signal_outcomes").iloc[0]
    assert out["outcome"] == "OPEN"
    assert not bool(out["triggered"])
    repo.close()


def test_tracker_expired_after_window():
    repo = Repository.open(":memory:")
    sig_date = date.today() - timedelta(days=20)
    # 6 bars (>= entry_valid_sessions), never triggered -> EXPIRED terminal.
    _seed(repo, "EXP", sig_date, [(95, 96, 94, 95)] * 6)
    summary = update_signal_outcomes(repo)
    assert summary["terminal"] == 1
    out = repo.query_df("SELECT * FROM signal_outcomes").iloc[0]
    assert out["outcome"] == "EXPIRED"
    repo.close()
