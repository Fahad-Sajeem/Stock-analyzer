"""Setup C — Range / Mean-Reversion (PLAN 7.3). NEUTRAL regime only.

Publisher additionally enforces quality >= 65 (junk that falls keeps falling).
"""

from __future__ import annotations

import pandas as pd

from analyzer.setups.base import SETUP_C, RawSignal
from analyzer.setups.candlesticks import bullish_confirmation
from analyzer.technicals.indicators import bollinger


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def scan_mean_reversion(df: pd.DataFrame, cfg_setups: dict) -> RawSignal | None:
    s = cfg_setups["mean_reversion"]
    range_days = s["range_min_days"]
    if len(df) < range_days + 5:
        return None
    last = df.iloc[-1]

    # 1. Defined range (not trending): flat-ish 200DMA / low ADX.
    if not pd.isna(last["adx"]) and last["adx"] >= 20:
        return None

    # 2. Near range support, oversold, at/through the lower Bollinger band.
    support = df["low"].tail(range_days).min()
    near_support = last["close"] <= support * 1.02
    if not near_support:
        return None
    if pd.isna(last["rsi"]) or last["rsi"] >= s["rsi_max"]:
        return None
    _mid, _up, lower, _w = bollinger(df["close"], 20, 2.0)
    if pd.isna(lower.iloc[-1]) or last["close"] > lower.iloc[-1]:
        return None

    # 3. Trigger: a bullish reversal candle closing back above support.
    is_bull, pattern = bullish_confirmation(df)
    if not is_bull or last["close"] < support:
        return None

    swing_low = df["low"].tail(range_days).min()
    strength = _clamp(
        0.5 * _clamp((s["rsi_max"] - last["rsi"]) / s["rsi_max"])
        + 0.5  # reversal candle at defined support
    )
    reasons = [
        f"At range support {support:.1f}, RSI {last['rsi']:.0f} (oversold)",
        f"Lower Bollinger reversal: {pattern}",
        "Mean-reversion in a defined range (low ADX)",
    ]
    return RawSignal(
        symbol=last["symbol"],
        date=last["date"],
        setup=SETUP_C,
        entry_ref=float(last["close"]),
        trigger_level=float(last["close"]),
        swing_low=float(swing_low),
        base_low=float(support),
        atr=float(last["atr"]),
        next_resistance=float(df["high"].tail(range_days).max()),
        setup_strength=strength,
        reasons=reasons,
        extra={"rsi": float(last["rsi"])},
    )
