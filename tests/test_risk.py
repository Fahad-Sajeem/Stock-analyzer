"""Tests for position sizing, portfolio caps, correlation cap, gap stress."""

import numpy as np
import pandas as pd

from analyzer.config import get_config
from analyzer.risk.position_sizing import (
    correlation_ok,
    gap_stress,
    portfolio_room,
    suggest_position,
)

RISK = get_config().risk


def test_suggest_position_risk_math_uncapped():
    # Wide stop so the position stays under the capital cap:
    # 1% of 10L = 10,000 risk; entry 100, stop 90 -> risk/share 10 -> 1000 shares
    # = 1L notional = 10% of capital < 15% cap -> no cap applied.
    r = suggest_position(1_000_000, 1.0, 100.0, 90.0, adv_traded_value=1e9, cfg_risk=RISK)
    assert r is not None
    assert r.qty == 1000
    assert r.caps_applied == []


def test_suggest_position_capital_cap_binds():
    # Tight stop: 10,000 / 4 = 2500 sh = 2.5L = 25% of capital -> capped to 15%.
    r = suggest_position(1_000_000, 1.0, 100.0, 96.0, adv_traded_value=1e9, cfg_risk=RISK)
    assert r is not None
    assert r.qty == 1500
    assert r.capital_frac_pct <= RISK["max_position_pct"] + 0.01
    assert any("capital" in c for c in r.caps_applied)


def test_suggest_position_liquidity_cap():
    # Tiny ADV forces the liquidity cap to bind.
    r = suggest_position(1_000_000, 1.0, 100.0, 96.0, adv_traded_value=2e5, cfg_risk=RISK)
    assert r is not None
    assert r.notional <= 2e5 * RISK["max_adv_participation_pct"] / 100 + 100
    assert any("ADV" in c for c in r.caps_applied)


def test_suggest_position_rejects_bad_stop():
    assert suggest_position(1_000_000, 1.0, 100.0, 105.0, None, RISK) is None


def test_portfolio_room_max_positions():
    pos = pd.DataFrame(
        {"symbol": [f"S{i}" for i in range(RISK["max_open_positions"])],
         "qty": [10] * RISK["max_open_positions"],
         "entry_price": [100.0] * RISK["max_open_positions"],
         "current_sl": [95.0] * RISK["max_open_positions"]}
    )
    ok, reasons = portfolio_room(pos, {}, None, 1_000_000, RISK)
    assert not ok
    assert any("max open positions" in r for r in reasons)


def test_portfolio_room_sector_cap():
    pos = pd.DataFrame(
        {"symbol": ["A", "B", "C"], "qty": [1, 1, 1],
         "entry_price": [100.0] * 3, "current_sl": [99.0] * 3}
    )
    sector_of = {"A": "IT", "B": "IT", "C": "IT"}
    ok, reasons = portfolio_room(pos, sector_of, "IT", 1_000_000, RISK)
    assert not ok
    assert any("sector" in r for r in reasons)


def test_correlation_cap():
    rng = np.random.default_rng(3)
    base = pd.Series(rng.normal(0, 1, 60))
    # Two open positions highly correlated with the candidate.
    open_returns = {"X": base + rng.normal(0, 0.1, 60), "Y": base + rng.normal(0, 0.1, 60)}
    ok, reasons = correlation_ok(base, open_returns, RISK)
    assert not ok
    # One correlated position is allowed.
    ok2, _ = correlation_ok(base, {"X": open_returns["X"]}, RISK)
    assert ok2


def test_gap_stress_blocks_when_concentrated():
    # 10L capital, 9L notional held -> -5% gap = 4.5% of capital > 4% -> blocked.
    pos = pd.DataFrame({"symbol": ["A"], "qty": [900], "entry_price": [1000.0],
                        "current_sl": [950.0]})
    out = gap_stress(pos, 1_000_000, RISK)
    assert out["scenarios"]["-5%"] > 4.0
    assert out["blocked"]


def test_gap_stress_ok_when_small():
    pos = pd.DataFrame({"symbol": ["A"], "qty": [100], "entry_price": [100.0],
                        "current_sl": [95.0]})
    out = gap_stress(pos, 1_000_000, RISK)
    assert not out["blocked"]
