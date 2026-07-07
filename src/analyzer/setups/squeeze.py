"""Setup D — Volatility Squeeze Breakout (PLAN 7.3).

A Bollinger-band squeeze (bottom-15% width) resolving upward on volume. Catches
moves Setup A's fixed base rule misses.
"""

from __future__ import annotations

import pandas as pd

from analyzer.setups.base import SETUP_D, RawSignal
from analyzer.technicals.indicators import bollinger


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def scan_squeeze(df: pd.DataFrame, cfg_setups: dict) -> RawSignal | None:
    s = cfg_setups["squeeze"]
    if len(df) < 260:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # 1. Prior bar was in a squeeze (BB width in its bottom percentile).
    if pd.isna(prev.get("bb_width_pctile")) or prev["bb_width_pctile"] > s["bb_width_pctile_max"]:
        return None

    # 2. Trigger: close breaks out above the upper Bollinger band on volume.
    _mid, upper, _lower, _w = bollinger(df["close"], 20, 2.0)
    if pd.isna(upper.iloc[-1]) or last["close"] <= upper.iloc[-1]:
        return None
    vol_ratio = last.get("vol_ratio")
    if pd.isna(vol_ratio) or vol_ratio < s["vol_mult_min"]:
        return None

    # 3. Long-only direction filter.
    if pd.isna(last["sma200"]) or last["close"] <= last["sma200"]:
        return None

    swing_low = df["low"].tail(10).min()
    base_low = df["low"].tail(20).min()
    strength = _clamp(
        0.5 * _clamp((s["bb_width_pctile_max"] - prev["bb_width_pctile"]) / s["bb_width_pctile_max"])
        + 0.5 * _clamp((vol_ratio - 1.0) / 1.5)
    )
    reasons = [
        f"Volatility squeeze (BB width pctile {prev['bb_width_pctile']:.0f}) resolving up",
        f"Close above upper band on {vol_ratio:.1f}x volume",
        "Above 200DMA (long-only filter)",
    ]
    return RawSignal(
        symbol=last["symbol"],
        date=last["date"],
        setup=SETUP_D,
        entry_ref=float(last["close"]),
        trigger_level=float(upper.iloc[-1]),
        swing_low=float(swing_low),
        base_low=float(base_low),
        atr=float(last["atr"]),
        setup_strength=strength,
        reasons=reasons,
        extra={"vol_ratio": float(vol_ratio)},
    )
