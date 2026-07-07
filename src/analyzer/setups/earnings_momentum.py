"""Setup E — Earnings Momentum / Post-Earnings Drift (PLAN 7.3).

Detects the results-day reaction signature (gap-up / strong close on huge volume,
gains held). Requires a ``results_recent`` flag on the frame — until the results-
calendar ingestion (task 2.2) lands, this stays dormant unless the caller injects
the flag, which prevents it from firing on non-earnings volume spikes.
"""

from __future__ import annotations

import pandas as pd

from analyzer.setups.base import SETUP_E, RawSignal


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def scan_earnings_momentum(df: pd.DataFrame, cfg_setups: dict) -> RawSignal | None:
    s = cfg_setups["earnings_momentum"]
    if len(df) < 210:
        return None
    last = df.iloc[-1]
    prev = df.iloc[-2]

    # Gate: only around a scheduled result (dormant without a results calendar).
    if s.get("require_results_flag", True) and not bool(last.get("results_recent", False)):
        return None

    # Results-day reaction: gap-up OR strong close, on heavy volume, gains held.
    gap_pct = (last["open"] - prev["close"]) / prev["close"] * 100.0
    close_pct = (last["close"] - prev["close"]) / prev["close"] * 100.0
    reaction = gap_pct >= s["gap_min_pct"] or close_pct >= s["close_min_pct"]
    if not reaction:
        return None
    vol_ratio = last.get("vol_ratio")
    if pd.isna(vol_ratio) or vol_ratio < s["vol_mult_min"]:
        return None
    day_range = last["high"] - last["low"]
    if day_range <= 0:
        return None
    close_in_top = (last["close"] - last["low"]) / day_range >= 0.70  # top 30% of range
    if not close_in_top:
        return None

    # Skip if the results-day range is too wide (stop would be too loose).
    range_pct = day_range / last["close"] * 100.0
    if range_pct > s["max_results_day_range_pct"]:
        return None

    # Long-only trend filter.
    if pd.isna(last["sma200"]) or last["close"] <= last["sma200"]:
        return None
    rs = last.get("rs_pctile")
    if rs is not None and not pd.isna(rs) and rs < s["rs_pctile_min"]:
        return None

    strength = _clamp(0.5 * _clamp(close_pct / 8.0) + 0.5 * _clamp((vol_ratio - 1) / 3.0))
    reasons = [
        f"Post-earnings drift: {close_pct:+.1f}% on {vol_ratio:.1f}x volume, gains held",
        f"Gap {gap_pct:+.1f}%, close in top 30% of range",
        "Above 200DMA",
    ]
    return RawSignal(
        symbol=last["symbol"],
        date=last["date"],
        setup=SETUP_E,
        entry_ref=float(last["high"]),
        trigger_level=float(last["high"]),
        swing_low=float(last["low"]),
        base_low=float(last["low"]),
        atr=float(last["atr"]),
        setup_strength=strength,
        reasons=reasons,
        extra={"vol_ratio": float(vol_ratio), "close_pct": float(close_pct)},
    )
