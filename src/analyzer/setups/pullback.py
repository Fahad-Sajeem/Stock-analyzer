"""Setup B — Pullback to Trend (PLAN 7.3). Buy-the-dip within an uptrend."""

from __future__ import annotations

import pandas as pd

from analyzer.setups.base import SETUP_B, RawSignal


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def scan_pullback(df: pd.DataFrame, cfg_setups: dict) -> RawSignal | None:
    s = cfg_setups["pullback"]
    if len(df) < 210:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # 1. Long-term uptrend: above rising 200DMA + relative strength.
    sma200_now = last["sma200"]
    sma200_past = df["sma200"].iloc[-21] if len(df) > 21 else None
    if pd.isna(sma200_now) or last["close"] <= sma200_now:
        return None
    if sma200_past is None or pd.isna(sma200_past) or sma200_now <= sma200_past:
        return None
    rs = last.get("rs_pctile")
    if pd.isna(rs) or rs < s["rs_pctile_min"]:
        return None

    # 2. Pullback into the EMA20-EMA50 zone (recent low touched the zone).
    recent_low = df["low"].tail(3).min()
    in_zone = recent_low <= last["ema20"] * 1.015 and last["close"] >= last["ema50"] * 0.985
    if not in_zone:
        return None

    # 3. Selling exhausting: pullback volume below average.
    vol_ratio = last.get("vol_ratio")
    if vol_ratio is not None and not pd.isna(vol_ratio) and vol_ratio >= 1.2:
        return None

    # 4. Trigger: close above prior day's high with RSI turning up from 40-55.
    rsi_lo, rsi_hi = s["rsi_zone"]
    rsi_now, rsi_prev = last["rsi"], prev["rsi"]
    trigger = (
        last["close"] > prev["high"]
        and (rsi_lo <= rsi_now <= rsi_hi + 5)
        and rsi_now > rsi_prev
    )
    if not trigger:
        return None

    # 5. There is a trend to pull back within.
    if pd.isna(last["adx"]) or last["adx"] < s["adx_min"]:
        return None

    swing_low = df["low"].tail(5).min()
    strength = _clamp(
        0.5 * _clamp(rs / 100.0)
        + 0.3 * _clamp(last["adx"] / 40.0)
        + 0.2 * _clamp((55 - abs(rsi_now - 50)) / 55)
    )
    reasons = [
        f"Pullback to EMA20/50 zone in an uptrend (RS {rs:.0f})",
        f"Reversal trigger: close>{prev['high']:.1f}, RSI {rsi_now:.0f} turning up",
        f"ADX {last['adx']:.0f} — trend intact",
    ]
    return RawSignal(
        symbol=last["symbol"],
        date=last["date"],
        setup=SETUP_B,
        entry_ref=float(prev["high"]),
        trigger_level=float(prev["high"]),
        swing_low=float(swing_low),
        base_low=float(last["ema50"]),
        atr=float(last["atr"]),
        setup_strength=strength,
        reasons=reasons,
        extra={"rs_pctile": float(rs), "adx": float(last["adx"])},
    )
