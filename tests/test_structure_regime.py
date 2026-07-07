"""Tests for structure detection and regime classification."""

import numpy as np
import pandas as pd

from analyzer.config import get_config
from analyzer.technicals import structure as struct
from analyzer.technicals.regime import classify_regime

CFG = get_config()


def test_fractal_pivots_finds_peak():
    # A clear peak at index 3.
    high = pd.Series([1, 2, 3, 5, 3, 2, 1], dtype="float64")
    low = pd.Series([1, 2, 3, 5, 3, 2, 1], dtype="float64")
    ph, pl = struct.fractal_pivots(high, low, k=2)
    assert bool(ph.iloc[3]) is True
    assert not ph.iloc[0]


def test_fractal_pivots_finds_trough():
    low = pd.Series([5, 4, 3, 1, 3, 4, 5], dtype="float64")
    high = low.copy()
    _ph, pl = struct.fractal_pivots(high, low, k=2)
    assert bool(pl.iloc[3]) is True


def test_cluster_levels_merges_close_prices():
    levels = struct.cluster_levels([100.0, 100.5, 101.0, 150.0], tolerance_pct=1.5)
    # 100/100.5/101 cluster (strongest), 150 separate.
    assert levels[0]["strength"] == 3
    assert abs(levels[0]["level"] - 100.5) < 0.6


def test_detect_base_flags_tight_range():
    # 40 bars oscillating in a tight 2% band -> in a base.
    rng = np.random.default_rng(0)
    close = pd.Series(100 + rng.uniform(-1, 1, 40))
    high = close + 0.2
    low = close - 0.2
    in_base, base_days = struct.detect_base(high, low, close, min_days=15, max_range_pct=12.0)
    assert bool(in_base.iloc[-1]) is True
    assert base_days.iloc[-1] >= 15


def test_detect_base_rejects_trending():
    close = pd.Series(np.arange(1, 60, dtype="float64") * 2)  # strong trend, wide range
    high = close + 0.5
    low = close - 0.5
    in_base, _ = struct.detect_base(high, low, close, min_days=15, max_range_pct=12.0)
    assert bool(in_base.iloc[-1]) is False


def test_dist_to_52w_high():
    close = pd.Series([100, 110, 120, 90], dtype="float64")
    high = pd.Series([100, 110, 120, 95], dtype="float64")
    out = struct.dist_to_52w_high(close, high, window=252)
    assert out.iloc[2] == 0.0                 # at the high
    assert out.iloc[3] == (90 - 120) / 120 * 100  # 25% below


def test_regime_bull():
    r = classify_regime(nifty_close=100, dma50=95, dma200=90, breadth=60, cfg=CFG)
    assert r == "BULL"


def test_regime_bear_below_200dma():
    r = classify_regime(nifty_close=85, dma50=95, dma200=90, breadth=60, cfg=CFG)
    assert r == "BEAR"


def test_regime_bear_on_breadth():
    r = classify_regime(nifty_close=100, dma50=95, dma200=90, breadth=30, cfg=CFG)
    assert r == "BEAR"


def test_regime_neutral():
    # Above 200DMA but not a clean stack / middling breadth.
    r = classify_regime(nifty_close=100, dma50=102, dma200=90, breadth=45, cfg=CFG)
    assert r == "NEUTRAL"


def test_regime_bull_when_breadth_missing():
    # Clean price stack but no breadth data (thin universe / backfill) -> still BULL.
    r = classify_regime(nifty_close=100, dma50=95, dma200=90, breadth=float("nan"), cfg=CFG)
    assert r == "BULL"


def test_regime_bear_when_breadth_missing_and_below_200():
    r = classify_regime(nifty_close=85, dma50=95, dma200=90, breadth=float("nan"), cfg=CFG)
    assert r == "BEAR"
