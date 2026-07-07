"""Unit tests for EXP-001 momentum portfolio mechanics (pure functions)."""

import numpy as np
import pandas as pd

from analyzer.research.momentum import (
    MomentumConfig,
    eligible_mask,
    max_drawdown,
    momentum_scores,
    month_end_positions,
    turnover_cost,
)

CFG = MomentumConfig(lookback_12m=252, lookback_6m=126, skip_days=21)


def _panel(n_days=300, symbols=("WIN", "LOSE", "ILLIQ")):
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    close = pd.DataFrame(index=dates)
    close["WIN"] = np.linspace(100, 200, n_days)     # strong uptrend
    close["LOSE"] = np.linspace(100, 60, n_days)     # downtrend
    close["ILLIQ"] = 100.0                            # flat, illiquid
    vol = pd.DataFrame(1_000_000.0, index=dates, columns=list(symbols))
    vol["ILLIQ"] = 10.0                               # tiny volume
    return close, close * vol


def test_month_end_positions_last_day_of_month():
    dates = pd.bdate_range("2024-01-01", "2024-03-31")
    pos = month_end_positions(pd.DatetimeIndex(dates))
    labels = [dates[i].strftime("%Y-%m-%d") for i in pos]
    assert labels[0] == "2024-01-31"
    assert labels[1] == "2024-02-29"


def test_momentum_scores_rank_winner_first():
    close, _tv = _panel()
    s = momentum_scores(close, len(close) - 1, CFG)
    assert s["WIN"] > s["ILLIQ"] > s["LOSE"]


def test_eligibility_excludes_illiquid():
    close, tv = _panel()
    m = eligible_mask(close, tv, len(close) - 1, CFG)
    assert bool(m["WIN"]) and bool(m["LOSE"])
    assert not bool(m["ILLIQ"])  # fails ₹3cr median traded value


def test_eligibility_requires_history():
    close, tv = _panel()
    short = close.copy()
    short.iloc[: len(short) - 100, short.columns.get_loc("WIN")] = np.nan  # listed recently
    m = eligible_mask(short, tv, len(short) - 1, CFG)
    assert not bool(m["WIN"])


def test_turnover_cost_full_and_partial():
    # Full replacement of a 20-name book: each slot pays sell 0.3% + buy 0.3%
    # = 0.6% of the book -> (20 exits + 20 entries)/20 x 0.003 = 0.006.
    assert abs(turnover_cost(set("ABCDEFGHIJKLMNOPQRST"), set("abcdefghijklmnopqrst"), 20, 0.003)
               - 0.006) < 1e-12
    # No change -> no cost
    h = {"X", "Y"}
    assert turnover_cost(h, h, 20, 0.003) == 0.0
    # From cash into a full book: 20 entries only
    assert abs(turnover_cost(set(), set("ABCDEFGHIJKLMNOPQRST"), 20, 0.003) - 0.003) < 1e-12


def test_max_drawdown():
    eq = np.array([1.0, 1.2, 0.9, 1.1, 1.3])
    assert abs(max_drawdown(eq) - 25.0) < 1e-9  # 1.2 -> 0.9
