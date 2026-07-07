"""Golden tests for technical indicators (PLAN 3.1 DoD).

Indicator bugs are silent money-losers, so these pin behavior against
hand-verifiable cases and known mathematical properties.
"""

import numpy as np
import pandas as pd

from analyzer.technicals import indicators as ind


def test_sma_basic():
    s = pd.Series([1, 2, 3, 4, 5], dtype="float64")
    out = ind.sma(s, 3)
    assert np.isnan(out.iloc[1])
    assert out.iloc[2] == 2.0  # mean(1,2,3)
    assert out.iloc[4] == 4.0  # mean(3,4,5)


def test_ema_first_value_and_recursion():
    s = pd.Series([10, 11, 12, 13], dtype="float64")
    out = ind.ema(s, 2)  # span=2 -> alpha = 2/3
    # adjust=False: first defined value equals the first price.
    assert out.iloc[0] == 10.0
    alpha = 2 / 3
    expected1 = alpha * 11 + (1 - alpha) * 10
    assert abs(out.iloc[1] - expected1) < 1e-9


def test_rsi_all_gains_is_100():
    s = pd.Series(np.arange(1, 30, dtype="float64"))  # strictly increasing
    out = ind.rsi(s, 14)
    assert abs(out.iloc[-1] - 100.0) < 1e-9


def test_rsi_all_losses_is_0():
    s = pd.Series(np.arange(30, 1, -1, dtype="float64"))  # strictly decreasing
    out = ind.rsi(s, 14)
    assert abs(out.iloc[-1] - 0.0) < 1e-9


def test_rsi_bounded():
    rng = np.random.default_rng(42)
    s = pd.Series(100 + np.cumsum(rng.normal(0, 1, 200)))
    out = ind.rsi(s, 14).dropna()
    assert (out >= 0).all() and (out <= 100).all()


def test_atr_constant_range():
    # Every bar has high-low = 2 and no gaps -> true range 2 -> ATR converges to 2.
    n = 60
    high = pd.Series([102.0] * n)
    low = pd.Series([100.0] * n)
    close = pd.Series([101.0] * n)
    out = ind.atr(high, low, close, 14)
    assert abs(out.iloc[-1] - 2.0) < 1e-6


def test_macd_zero_for_constant_series():
    s = pd.Series([50.0] * 60)
    line, sig, hist = ind.macd(s)
    assert abs(line.iloc[-1]) < 1e-9
    assert abs(hist.iloc[-1]) < 1e-9


def test_roc():
    s = pd.Series([100.0, 110.0, 121.0])
    out = ind.roc(s, 1)
    assert abs(out.iloc[1] - 10.0) < 1e-9   # +10%
    assert abs(out.iloc[2] - 10.0) < 1e-9


def test_obv_direction():
    close = pd.Series([10, 11, 10, 12], dtype="float64")
    vol = pd.Series([100, 200, 300, 400], dtype="float64")
    out = ind.obv(close, vol)
    # +200 (up), -300 (down), +400 (up) -> cumulative 0,200,-100,300
    assert list(out) == [0.0, 200.0, -100.0, 300.0]


def test_bollinger_width_positive():
    rng = np.random.default_rng(1)
    s = pd.Series(100 + np.cumsum(rng.normal(0, 1, 100)))
    _mid, up, lo, width = ind.bollinger(s, 20, 2)
    w = width.dropna()
    assert (w >= 0).all()
    assert (up.dropna() >= lo.dropna()).all()


def test_adx_trending_is_high():
    # Strong clean uptrend should register a high ADX.
    s = pd.Series(np.arange(1, 80, dtype="float64"))
    high, low, close = s + 0.5, s - 0.5, s
    adx_s, pdi, mdi = ind.adx(high, low, close, 14)
    assert adx_s.iloc[-1] > 40
    assert pdi.iloc[-1] > mdi.iloc[-1]  # +DI dominates in an uptrend


def test_rolling_percentile_matches_naive():
    rng = np.random.default_rng(7)
    s = pd.Series(rng.normal(0, 1, 300))
    window = 60
    fast = ind.rolling_percentile(s, window)
    # Naive reference on full windows.
    for i in (100, 200, 299):
        w = s.iloc[i - window + 1 : i + 1].to_numpy()
        expected = (w <= w[-1]).mean() * 100.0
        assert abs(fast.iloc[i] - expected) < 1e-9


def test_rolling_percentile_last_is_max_gives_100():
    s = pd.Series([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 100.0])
    out = ind.rolling_percentile(s, 5)
    assert abs(out.iloc[-1] - 100.0) < 1e-9  # current value is the window max


def test_supertrend_follows_below_in_uptrend():
    s = pd.Series(np.arange(1, 80, dtype="float64"))
    high, low, close = s + 1, s - 1, s
    st = ind.supertrend(high, low, close, 10, 3).dropna()
    # In a persistent uptrend the supertrend line sits below price.
    assert st.iloc[-1] < close.iloc[-1]
