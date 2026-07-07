"""Composite score & grade (PLAN 8.6).

composite = 0.40*setup_strength + 0.25*momentum_rs + 0.25*quality
          + 0.10*volume_delivery   (+ small candlestick confirmation, ± news)
Grades: A >= 80, B 65-79, C 50-64 (C = watch-only).
"""

from __future__ import annotations

from dataclasses import dataclass

from analyzer.setups.base import RawSignal


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


@dataclass
class Score:
    composite: float
    grade: str
    breakdown: dict[str, float]


def volume_delivery_score(rs: RawSignal) -> float:
    """0-100 from breakout-day volume expansion and delivery strength."""
    vr = rs.extra.get("vol_ratio", 1.0)
    vol_component = _clamp((vr - 1.0) / 1.5) * 100.0 if vr else 0.0
    return _clamp(vol_component)


def compute_score(
    rs: RawSignal,
    quality_score: float,
    cfg_signals: dict,
    candle_bonus: float = 0.0,
    news_adjust: float = 0.0,
) -> Score:
    w = cfg_signals["composite_weights"]
    momentum_rs = rs.extra.get("rs_pctile", 50.0)
    setup_component = _clamp(rs.setup_strength * 100.0)
    vol_component = volume_delivery_score(rs)

    composite = (
        w["setup_strength"] * setup_component
        + w["momentum_rs"] * _clamp(momentum_rs)
        + w["quality"] * _clamp(quality_score)
        + w["volume_delivery"] * vol_component
    )
    # Candlestick confirmation and news are bounded modifiers, not drivers.
    news_cap = cfg_signals.get("news_max_adjust_points", 5)
    composite += _clamp(candle_bonus, -5, 5)
    composite += max(-news_cap, min(news_cap, news_adjust))
    composite = _clamp(composite)

    if composite >= cfg_signals["grade_a_min"]:
        grade = "A"
    elif composite >= cfg_signals["grade_b_min"]:
        grade = "B"
    elif composite >= cfg_signals["grade_c_min"]:
        grade = "C"
    else:
        grade = "D"

    return Score(
        composite=round(composite, 1),
        grade=grade,
        breakdown={
            "setup_strength": round(setup_component, 1),
            "momentum_rs": round(_clamp(momentum_rs), 1),
            "quality": round(_clamp(quality_score), 1),
            "volume_delivery": round(vol_component, 1),
            "candle_bonus": round(_clamp(candle_bonus, -5, 5), 1),
        },
    )
