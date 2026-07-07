"""Tests for the backtest cost model, trade engine, and metrics."""

from datetime import date, timedelta

import pandas as pd

from analyzer.backtest.costs import apply_costs_to_r, round_trip_cost_pct
from analyzer.backtest.engine import simulate_trade
from analyzer.backtest.metrics import check_gates, compute_metrics
from analyzer.config import get_config

CFG = get_config()
SIG = CFG.signals
BT = CFG.backtest


def _bars(prices):
    """Build OHLC bars from a list of (o,h,l,c) tuples with sequential dates."""
    start = date(2024, 1, 2)
    rows = []
    for i, (o, h, l, c) in enumerate(prices):
        rows.append({"date": start + timedelta(days=i), "open": o, "high": h, "low": l, "close": c})
    return pd.DataFrame(rows)


def _signal(entry=100.0, stop=96.0, t1=106.0, t2=112.0):
    return {"symbol": "X", "setup": "A_momentum_breakout", "date": date(2024, 1, 1),
            "entry_aggressive": entry, "stop_loss": stop, "t1": t1, "t2": t2}


# --- cost model -----------------------------------------------------------
def test_round_trip_cost_reasonable():
    c = round_trip_cost_pct(BT, 1.0)
    assert 0.4 <= c <= 0.7   # ~0.5-0.6% for liquid names


def test_slippage_scales_with_illiquidity():
    liquid = round_trip_cost_pct(BT, 1.0)
    illiquid = round_trip_cost_pct(BT, 2.0)
    assert illiquid > liquid


def test_apply_costs_reduces_r():
    net = apply_costs_to_r(2.0, entry=100, risk_per_share=4.0, cfg_backtest=BT)
    assert net < 2.0


# --- trade engine ---------------------------------------------------------
def test_entry_expires_if_never_triggered():
    # Price never reaches entry_ref (100) within the validity window.
    bars = _bars([(95, 96, 94, 95)] * 6)
    tr = simulate_trade(_signal(), bars, SIG, BT)
    assert not tr.entered
    assert tr.outcome == "EXPIRED"


def test_stop_hit_loses_about_one_r():
    # Enter day 1 (touches 100), then collapse through the stop (96).
    bars = _bars([(100, 101, 99, 100), (98, 99, 90, 91)])
    tr = simulate_trade(_signal(), bars, SIG, BT)
    assert tr.entered
    assert tr.outcome == "SL_HIT"
    assert -1.3 < tr.net_r < -0.9   # ~ -1R plus costs


def test_t2_hit_full_winner():
    # Enter at 100, then rally through T1 (106) and T2 (112).
    bars = _bars([(100, 101, 99, 100), (105, 107, 104, 106), (110, 113, 109, 112)])
    tr = simulate_trade(_signal(), bars, SIG, BT)
    assert tr.entered
    assert tr.outcome == "T2_HIT"
    assert tr.t1_booked
    # 0.5*1.5R + 0.5*3R = 2.25R gross, minus costs.
    assert 1.9 < tr.net_r < 2.3


def test_t1_then_breakeven_stop():
    # Hit T1 (book half, stop->breakeven), then fall back to entry.
    bars = _bars([(100, 101, 99, 100), (105, 107, 104, 106), (103, 104, 99, 99)])
    tr = simulate_trade(_signal(), bars, SIG, BT)
    assert tr.t1_booked
    assert tr.outcome == "T1_TRAIL"
    # 0.5*1.5R + 0.5*0R = 0.75R gross, minus costs.
    assert 0.5 < tr.net_r < 0.8


def test_no_chase_beyond_2pct():
    # Gaps open to 103 (>+2% above entry 100) every day -> never a valid fill.
    bars = _bars([(103, 105, 102, 104)] * 6)
    tr = simulate_trade(_signal(), bars, SIG, BT)
    assert not tr.entered


def test_time_stop_exits():
    # Enters, then drifts sideways below targets -> exits on the time stop.
    # Use enough bars to exceed the configured time-stop regardless of its value.
    n = SIG["time_stop_sessions"] + 5
    flat = [(100, 101, 99, 100)] + [(100, 101, 99.5, 100)] * n
    tr = simulate_trade(_signal(), _bars(flat), SIG, BT)
    assert tr.entered
    assert tr.outcome == "TIME_STOP"


# --- metrics --------------------------------------------------------------
def _trades_df(rs):
    return pd.DataFrame([
        {"entered": True, "net_r": r, "signal_date": date(2020 + i % 4, 1, 1),
         "entry_date": date(2020 + i % 4, 1, 2), "days_held": 5, "regime": "BULL"}
        for i, r in enumerate(rs)
    ])


def test_metrics_profit_factor_and_winrate():
    m = compute_metrics(_trades_df([2, 2, -1, -1, 2]), date(2020, 1, 1), date(2023, 12, 31))
    assert m["n_trades"] == 5
    assert m["win_rate"] == 60.0
    assert m["profit_factor"] == 3.0   # wins 6 / losses 2


def test_gates_fail_on_low_trades():
    m = compute_metrics(_trades_df([2, -1, 2]), date(2020, 1, 1), date(2023, 12, 31))
    passed, reasons = check_gates(m, BT)
    assert not passed
    assert any("n_trades" in r for r in reasons)
