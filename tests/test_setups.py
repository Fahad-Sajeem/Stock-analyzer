"""Tests for candlestick detectors, regime setup selection, and Setup A detection."""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from analyzer.config import get_config
from analyzer.setups import get_active_setups
from analyzer.setups.base import SETUP_A, SETUP_C
from analyzer.setups.breakout import scan_breakout
from analyzer.setups.candlesticks import (
    is_bullish_engulfing,
    is_hammer,
    is_shooting_star,
)

CFG = get_config()


def test_active_setups_by_regime():
    assert set(get_active_setups("BULL")) == set(get_active_setups("NEUTRAL"))
    assert get_active_setups("BEAR") == [SETUP_C]
    assert get_active_setups("RISK_OFF") == []


def test_bullish_engulfing():
    df = pd.DataFrame(
        {"open": [10, 8.5], "high": [10.2, 11], "low": [8, 8.3], "close": [8.6, 10.8]}
    )
    assert is_bullish_engulfing(df)


def test_hammer():
    df = pd.DataFrame({"open": [10.0], "high": [10.2], "low": [8.5], "close": [10.1]})
    assert is_hammer(df)


def test_shooting_star():
    # Long upper wick, small body near the low, negligible lower wick.
    df = pd.DataFrame({"open": [10.0], "high": [11.5], "low": [10.0], "close": [10.3]})
    assert is_shooting_star(df)


def _synthetic_breakout_frame() -> pd.DataFrame:
    """A clean uptrend, a tight base, then a high-volume breakout on the last bar."""
    n_trend, n_base = 220, 20
    dates = [date(2025, 1, 1) + timedelta(days=i) for i in range(n_trend + n_base + 1)]
    # Rising trend from 50 -> 100 to stack EMAs above the 200DMA.
    trend = np.linspace(50, 100, n_trend)
    base = np.full(n_base, 100.0)  # flat tight base -> 60d high ~100.5
    breakout = np.array([103.0])   # breakout close within 4% of the base high
    close = np.concatenate([trend, base, breakout])
    high = close + 0.5
    high[-1] = 103.5
    low = close - 0.5
    openp = close - 0.1
    vol = np.concatenate([np.full(n_trend + n_base, 1_000_000.0), [3_000_000.0]])

    df = pd.DataFrame(
        {"symbol": "TEST", "date": dates, "open": openp, "high": high, "low": low,
         "close": close, "volume": vol}
    )
    # Minimal indicator columns the scanner reads.
    df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["sma200"] = df["close"].rolling(200, min_periods=1).mean()
    df["atr"] = 1.0
    df["rs_pctile"] = 85.0
    df["vol_ratio"] = df["volume"] / 1_000_000.0
    df["delivery_pct"] = 60.0
    # base_days: 0 through the trend, climbing across the base.
    bd = [0] * n_trend + list(range(1, n_base + 1)) + [n_base + 1]
    df["base_days"] = [max(0, x + 14) if x > 0 else 0 for x in bd]
    return df


def test_scan_breakout_fires_on_clean_setup():
    df = _synthetic_breakout_frame()
    raw = scan_breakout(df, CFG.setups)
    assert raw is not None
    assert raw.setup == SETUP_A
    assert raw.entry_ref == 103.0
    assert raw.trigger_level < 103.0     # broke above the prior 60d high
    assert len(raw.reasons) >= 2


def test_scan_breakout_rejects_low_volume():
    df = _synthetic_breakout_frame()
    df.loc[df.index[-1], "vol_ratio"] = 1.0  # no volume expansion
    assert scan_breakout(df, CFG.setups) is None


def test_scan_breakout_rejects_extended():
    df = _synthetic_breakout_frame()
    # Push close far above the breakout level (>4% extended).
    df.loc[df.index[-1], "close"] = 130.0
    assert scan_breakout(df, CFG.setups) is None
