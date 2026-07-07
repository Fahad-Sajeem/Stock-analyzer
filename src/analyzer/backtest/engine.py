"""Event-loop trade simulator (PLAN 8.1-8.3 execution, 16 pt.1 no look-ahead).

Simulates one trade from a signal against the symbol's FUTURE bars only (a signal
computed at close of day T can act no earlier than T+1). Models the published
execution rules: stop-limit entry with a +2% no-chase cap, 5-session entry expiry,
50% booked at T1 with stop→breakeven, remainder to T2 / trailing / time-stop, and
gap-through-stop fills at the open.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from analyzer.backtest.costs import apply_costs_to_r, round_trip_cost_pct


@dataclass
class TradeResult:
    symbol: str
    setup: str
    signal_date: date
    entered: bool
    outcome: str                 # EXPIRED | SL_HIT | T2_HIT | TIME_STOP | END | T1_TRAIL
    t1_booked: bool = False
    entry_date: date | None = None
    entry_price: float = 0.0
    exit_date: date | None = None
    exit_price: float = 0.0
    gross_r: float = 0.0
    net_r: float = 0.0
    return_pct: float = 0.0      # net-of-cost % on notional deployed
    mfe_r: float = 0.0           # max favorable excursion (R)
    mae_r: float = 0.0           # max adverse excursion (R)
    days_held: int = 0


def simulate_trade(
    signal: dict, future_bars: pd.DataFrame, cfg_signals: dict, cfg_backtest: dict,
    liquidity_factor: float = 1.0,
) -> TradeResult:
    """Simulate a single LONG signal. ``future_bars`` = bars strictly AFTER the
    signal date, ascending, with columns date/open/high/low/close (row 0 = T+1)."""
    entry_ref = signal["entry_aggressive"]
    stop0 = signal["stop_loss"]
    t1, t2 = signal["t1"], signal["t2"]
    valid = cfg_signals["entry_valid_sessions"]
    time_stop = cfg_signals["time_stop_sessions"]

    res = TradeResult(
        symbol=signal.get("symbol", "?"), setup=signal.get("setup", "?"),
        signal_date=signal.get("date"), entered=False, outcome="EXPIRED",
    )
    if future_bars.empty or entry_ref <= 0:
        return res
    bars = future_bars.reset_index(drop=True)

    # --- Phase 1: entry within the validity window --------------------------
    entry_idx = None
    entry_price = 0.0
    for i in range(min(valid, len(bars))):
        b = bars.iloc[i]
        if b["high"] >= entry_ref:                     # trigger touched
            if b["open"] > entry_ref * 1.02:           # gapped past the no-chase cap
                continue
            entry_price = max(float(b["open"]), entry_ref)
            entry_idx = i
            break
    if entry_idx is None:
        return res  # never triggered -> EXPIRED

    risk = entry_price - stop0
    if risk <= 0:
        return res
    res.entered = True
    res.entry_date = bars.iloc[entry_idx]["date"]
    res.entry_price = round(entry_price, 2)

    # --- Phase 2: manage the position ---------------------------------------
    current_stop = stop0
    t1_booked = False
    legs: list[tuple[float, float]] = []   # (fraction, exit_price)
    hi_mark, lo_mark = entry_price, entry_price
    outcome = "END"
    exit_date = bars.iloc[-1]["date"]

    for j in range(entry_idx + 1, len(bars)):
        b = bars.iloc[j]
        days_held = j - entry_idx
        hi_mark = max(hi_mark, float(b["high"]))
        lo_mark = min(lo_mark, float(b["low"]))

        # Stop first (conservative). Gap-through -> fill at the open.
        if b["open"] <= current_stop:
            legs.append((1.0 - _booked(legs), float(b["open"])))
            outcome = "SL_HIT" if not t1_booked else "T1_TRAIL"
            exit_date = b["date"]
            break
        if b["low"] <= current_stop:
            legs.append((1.0 - _booked(legs), current_stop))
            outcome = "SL_HIT" if not t1_booked else "T1_TRAIL"
            exit_date = b["date"]
            break

        # Book 50% at T1, move stop to breakeven.
        if not t1_booked and b["high"] >= t1:
            legs.append((0.5, t1))
            t1_booked = True
            current_stop = entry_price

        # Remainder exits at T2.
        if t1_booked and b["high"] >= t2:
            legs.append((1.0 - _booked(legs), t2))
            outcome = "T2_HIT"
            exit_date = b["date"]
            break

        # Time stop.
        if days_held >= time_stop:
            legs.append((1.0 - _booked(legs), float(b["close"])))
            outcome = "TIME_STOP"
            exit_date = b["date"]
            break
    else:
        # Ran out of data -> exit remainder at last close.
        legs.append((1.0 - _booked(legs), float(bars.iloc[-1]["close"])))
        outcome = "END"

    gross_r = sum(frac * (px - entry_price) / risk for frac, px in legs)
    net_r = apply_costs_to_r(gross_r, entry_price, risk, cfg_backtest, liquidity_factor)
    pnl_pct = sum(frac * (px - entry_price) / entry_price for frac, px in legs) * 100.0
    pnl_pct -= round_trip_cost_pct(cfg_backtest, liquidity_factor)

    res.outcome = outcome
    res.t1_booked = t1_booked
    res.exit_date = exit_date
    res.exit_price = round(legs[-1][1], 2) if legs else 0.0
    res.gross_r = round(gross_r, 3)
    res.net_r = round(net_r, 3)
    res.return_pct = round(pnl_pct, 3)
    res.mfe_r = round((hi_mark - entry_price) / risk, 3)
    res.mae_r = round((lo_mark - entry_price) / risk, 3)
    res.days_held = (exit_date - res.entry_date).days if res.entry_date else 0
    return res


def _booked(legs: list[tuple[float, float]]) -> float:
    return sum(f for f, _ in legs)
