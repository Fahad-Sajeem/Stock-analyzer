"""Price structure: fractal swings, support/resistance, base detection, 52w levels.

Pure functions over OHLC (PLAN 7.1 "Structure"). These feed the setup scanners in
Phase 4 (breakout bases, S/R for stops/targets, mean-reversion ranges).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def fractal_pivots(high: pd.Series, low: pd.Series, k: int = 2) -> tuple[pd.Series, pd.Series]:
    """Bill Williams style fractals: a pivot high has ``k`` lower highs on BOTH
    sides; a pivot low has ``k`` higher lows on both sides.

    Returns (is_pivot_high, is_pivot_low) boolean Series. Pivots are only
    confirmable ``k`` bars later (no look-ahead when used causally).
    """
    n = len(high)
    ph = np.zeros(n, dtype=bool)
    pl = np.zeros(n, dtype=bool)
    h = high.to_numpy()
    lo = low.to_numpy()
    for i in range(k, n - k):
        window_h = h[i - k : i + k + 1]
        window_l = lo[i - k : i + k + 1]
        if h[i] == window_h.max() and (window_h.argmax() == k):
            ph[i] = True
        if lo[i] == window_l.min() and (window_l.argmin() == k):
            pl[i] = True
    return pd.Series(ph, index=high.index), pd.Series(pl, index=low.index)


def recent_swing_low(low: pd.Series, is_pivot_low: pd.Series, lookback: int = 20) -> float | None:
    """Most recent confirmed pivot low within ``lookback`` bars (for stop placement)."""
    recent = low[is_pivot_low].tail(50)
    if recent.empty:
        return None
    window = low.tail(lookback)
    lows = recent[recent.index.isin(window.index)]
    return float(lows.iloc[-1]) if not lows.empty else float(recent.iloc[-1])


def cluster_levels(prices: list[float], tolerance_pct: float = 1.5) -> list[dict]:
    """Cluster nearby pivot prices into S/R levels. Returns [{level, strength}]
    sorted by strength (number of touches) descending."""
    if not prices:
        return []
    ordered = sorted(prices)
    clusters: list[list[float]] = [[ordered[0]]]
    for p in ordered[1:]:
        anchor = clusters[-1][0]
        if abs(p - anchor) / anchor * 100.0 <= tolerance_pct:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    levels = [{"level": float(np.mean(c)), "strength": len(c)} for c in clusters]
    return sorted(levels, key=lambda x: x["strength"], reverse=True)


def support_resistance(
    high: pd.Series, low: pd.Series, k: int = 2, tolerance_pct: float = 1.5, lookback: int = 250
) -> tuple[list[dict], list[dict]]:
    """Return (resistances, supports) as clustered level dicts over the lookback."""
    ph, pl = fractal_pivots(high.tail(lookback), low.tail(lookback), k)
    res = cluster_levels(list(high.tail(lookback)[ph]), tolerance_pct)
    sup = cluster_levels(list(low.tail(lookback)[pl]), tolerance_pct)
    return res, sup


def rolling_high(high: pd.Series, n: int) -> pd.Series:
    return high.rolling(n, min_periods=1).max()


def rolling_low(low: pd.Series, n: int) -> pd.Series:
    return low.rolling(n, min_periods=1).min()


def dist_to_52w_high(close: pd.Series, high: pd.Series, window: int = 252) -> pd.Series:
    """Percent distance from the trailing 52-week high (0 = at highs, negative below)."""
    hi = high.rolling(window, min_periods=1).max()
    return (close - hi) / hi * 100.0


def detect_base(
    high: pd.Series, low: pd.Series, close: pd.Series, min_days: int = 15, max_range_pct: float = 12.0
) -> tuple[pd.Series, pd.Series]:
    """Consolidation/base detection (breakout precondition, PLAN 7.3 Setup A).

    A bar is "in a base" if, looking back ``min_days``, the high-low range is
    tighter than ``max_range_pct`` of price. ``base_days`` counts how many
    consecutive prior bars satisfied the tightness (length of the current base).
    Returns (in_base bool Series, base_days int Series).
    """
    hi = high.rolling(min_days, min_periods=min_days).max()
    lo = low.rolling(min_days, min_periods=min_days).min()
    rng_pct = (hi - lo) / close * 100.0
    in_base = rng_pct <= max_range_pct

    # base_days: consecutive True run length ending at each bar.
    base_days = np.zeros(len(in_base), dtype=int)
    vals = in_base.fillna(False).to_numpy()
    run = 0
    for i, v in enumerate(vals):
        run = run + 1 if v else 0
        base_days[i] = (run + min_days - 1) if v else 0
    return in_base, pd.Series(base_days, index=in_base.index)
