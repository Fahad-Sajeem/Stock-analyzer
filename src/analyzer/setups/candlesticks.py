"""Candlestick pattern detection (PLAN 7.4) — confirmation only, never a trigger.

Pure boolean detectors evaluated on the last bar. Patterns add/subtract a few
confirmation points in scoring; they never generate a signal on their own.
"""

from __future__ import annotations

import pandas as pd


def _body(o: float, c: float) -> float:
    return abs(c - o)


def is_bullish_engulfing(df: pd.DataFrame) -> bool:
    if len(df) < 2:
        return False
    p, c = df.iloc[-2], df.iloc[-1]
    prev_down = p["close"] < p["open"]
    curr_up = c["close"] > c["open"]
    engulfs = c["close"] >= p["open"] and c["open"] <= p["close"]
    return bool(prev_down and curr_up and engulfs)


def is_bearish_engulfing(df: pd.DataFrame) -> bool:
    if len(df) < 2:
        return False
    p, c = df.iloc[-2], df.iloc[-1]
    prev_up = p["close"] > p["open"]
    curr_down = c["close"] < c["open"]
    engulfs = c["open"] >= p["close"] and c["close"] <= p["open"]
    return bool(prev_up and curr_down and engulfs)


def is_hammer(df: pd.DataFrame) -> bool:
    c = df.iloc[-1]
    rng = c["high"] - c["low"]
    if rng <= 0:
        return False
    body = _body(c["open"], c["close"])
    lower_wick = min(c["open"], c["close"]) - c["low"]
    upper_wick = c["high"] - max(c["open"], c["close"])
    return bool(lower_wick >= 2 * body and upper_wick <= body and body > 0)


def is_shooting_star(df: pd.DataFrame) -> bool:
    c = df.iloc[-1]
    rng = c["high"] - c["low"]
    if rng <= 0:
        return False
    body = _body(c["open"], c["close"])
    upper_wick = c["high"] - max(c["open"], c["close"])
    lower_wick = min(c["open"], c["close"]) - c["low"]
    return bool(upper_wick >= 2 * body and lower_wick <= body and body > 0)


def is_doji(df: pd.DataFrame, tol: float = 0.1) -> bool:
    c = df.iloc[-1]
    rng = c["high"] - c["low"]
    if rng <= 0:
        return False
    return bool(_body(c["open"], c["close"]) <= tol * rng)


def bullish_confirmation(df: pd.DataFrame) -> tuple[bool, str | None]:
    """Return (is_bullish_pattern, name) for the last bar."""
    if is_bullish_engulfing(df):
        return True, "bullish engulfing"
    if is_hammer(df):
        return True, "hammer"
    return False, None


def bearish_confirmation(df: pd.DataFrame) -> tuple[bool, str | None]:
    if is_bearish_engulfing(df):
        return True, "bearish engulfing"
    if is_shooting_star(df):
        return True, "shooting star"
    return False, None
