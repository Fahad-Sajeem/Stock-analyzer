"""Setup A — Momentum Breakout (PLAN 7.3). Primary setup; best in BULL regime."""

from __future__ import annotations

import pandas as pd

from analyzer.setups.base import SETUP_A, RawSignal


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def scan_breakout(df: pd.DataFrame, cfg_setups: dict) -> RawSignal | None:
    """Detect a momentum breakout on the last bar of ``df`` (ascending by date)."""
    s = cfg_setups["breakout"]
    if len(df) < s["high_lookback"] + 5:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # 1. Close crosses above the prior N-day high (breakout level).
    lookback = s["high_lookback"]
    breakout_level = df["high"].shift(1).rolling(lookback).max().iloc[-1]
    if pd.isna(breakout_level) or last["close"] <= breakout_level:
        return None

    # 2. Breakout-day volume >= 1.5x 20d average.
    vol_ratio = last.get("vol_ratio")
    if pd.isna(vol_ratio) or vol_ratio < s["vol_mult_min"]:
        return None

    # 3. Prior consolidation: a 15+ day base was in place before the breakout.
    if pd.isna(prev.get("base_days")) or prev["base_days"] < 15:
        return None

    # 4. Stacked trend alignment: close > EMA20 > EMA50 > SMA200.
    if not (
        last["close"] > last["ema20"] > last["ema50"] > last["sma200"]
    ):
        return None

    # 5. Relative strength leadership.
    rs = last.get("rs_pctile")
    if pd.isna(rs) or rs < s["rs_pctile_min"]:
        return None

    # 6. Genuine buying: delivery% today >= its 20-day average.
    deliv = last.get("delivery_pct")
    deliv_avg = df["delivery_pct"].rolling(20).mean().iloc[-1]
    if deliv is not None and deliv_avg is not None and not pd.isna(deliv) and not pd.isna(deliv_avg):
        if deliv < deliv_avg:
            return None

    # 7. Not extended: within max_extension% above the breakout level.
    extension = (last["close"] - breakout_level) / breakout_level * 100.0
    if extension > s["max_extension_pct"]:
        return None

    # --- strength & references ----------------------------------------------
    base_low = df["low"].tail(int(prev["base_days"]) if prev["base_days"] > 0 else 20).min()
    swing_low = df["low"].tail(10).min()
    strength = _clamp(
        0.4 * _clamp((vol_ratio - 1.0) / (s["vol_mult_strong"] - 1.0))
        + 0.3 * _clamp(rs / 100.0)
        + 0.3 * _clamp(prev["base_days"] / 40.0)
    )

    reasons = [
        f"Breakout above {lookback}d high {breakout_level:.1f} on {vol_ratio:.1f}x volume",
        f"{int(prev['base_days'])}-session base; RS percentile {rs:.0f}",
    ]
    if deliv is not None and not pd.isna(deliv):
        reasons.append(f"Delivery {deliv:.0f}% vs {deliv_avg:.0f}% avg")

    return RawSignal(
        symbol=last["symbol"],
        date=last["date"],
        setup=SETUP_A,
        entry_ref=float(last["close"]),
        trigger_level=float(breakout_level),
        swing_low=float(swing_low),
        base_low=float(base_low),
        atr=float(last["atr"]),
        setup_strength=strength,
        reasons=reasons,
        extra={"vol_ratio": float(vol_ratio), "rs_pctile": float(rs)},
    )
