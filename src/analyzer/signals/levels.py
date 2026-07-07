"""Levels engine — entry / stop-loss / targets / R:R (PLAN 8.1-8.4).

Deterministic and backtestable. Given a RawSignal (trigger price + structural
stop references + ATR), produce the tradeable levels or reject the setup when the
stop is too wide or the reward:risk is insufficient.
"""

from __future__ import annotations

from dataclasses import dataclass

from analyzer.setups.base import RawSignal


@dataclass
class Levels:
    entry_aggressive: float
    entry_conservative: float
    stop_loss: float
    stop_basis: str
    t1: float
    t2: float
    rr_to_t2: float
    risk_pct: float          # stop distance as % of entry


def compute_levels(rs: RawSignal, cfg_signals: dict) -> Levels | None:
    """Compute levels for a raw signal. Returns None if the signal is rejected
    (stop too wide, or reward:risk below the gate)."""
    entry = rs.entry_ref
    if entry <= 0 or rs.atr <= 0:
        return None
    atr = rs.atr

    # --- stop-loss: structure-aware, ATR-buffered (§8.2) ---------------------
    structure_refs = [x for x in (rs.swing_low, rs.base_low) if x is not None and x < entry]
    technical_stop = min(structure_refs) if structure_refs else entry - 2 * atr
    volatility_stop = entry - cfg_signals["atr_stop_mult"] * atr
    # The tighter sensible stop = the higher of the two candidates.
    stop = max(technical_stop - cfg_signals["stop_swing_buffer_atr"] * atr, volatility_stop)

    stop_pct = (entry - stop) / entry * 100.0

    # Hard cap: too-wide stops are rejected outright (§8.2).
    if stop_pct > cfg_signals["max_stop_pct"]:
        return None
    # Min floor: avoid noise stop-outs by widening very tight stops.
    if stop_pct < cfg_signals["min_stop_pct"]:
        stop = entry * (1 - cfg_signals["min_stop_pct"] / 100.0)
        stop_pct = cfg_signals["min_stop_pct"]

    risk = entry - stop
    if risk <= 0:
        return None

    # --- targets (§8.3) ------------------------------------------------------
    t1 = entry + cfg_signals["t1_r_mult"] * risk
    t2_by_r = entry + cfg_signals["t2_r_mult"] * risk
    # T2 = 3R or the next major resistance, whichever is NEARER (but above T1).
    if rs.next_resistance and rs.next_resistance > t1:
        t2 = min(t2_by_r, rs.next_resistance)
    else:
        t2 = t2_by_r

    rr_to_t2 = (t2 - entry) / risk
    if rr_to_t2 < cfg_signals["min_rr_to_t2"]:
        return None

    stop_basis = (
        f"{'swing/base' if structure_refs else 'ATR'} stop {stop:.1f}; "
        f"{stop_pct:.1f}% risk"
    )
    return Levels(
        entry_aggressive=round(entry, 2),
        entry_conservative=round(rs.trigger_level if rs.trigger_level else entry, 2),
        stop_loss=round(stop, 2),
        stop_basis=stop_basis,
        t1=round(t1, 2),
        t2=round(t2, 2),
        rr_to_t2=round(rr_to_t2, 2),
        risk_pct=round(stop_pct, 2),
    )
