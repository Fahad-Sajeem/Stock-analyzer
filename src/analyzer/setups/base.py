"""Setup interface, RawSignal, and the regime-aware active-setup selector."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class RawSignal:
    """A detected setup on one symbol/date, BEFORE levels & scoring are applied.

    Carries everything the levels engine (§8.2-8.3) and scorer (§8.6) need:
    the trigger price, structural stop references, ATR, a 0-1 setup_strength,
    and human-readable reasons.
    """

    symbol: str
    date: date
    setup: str                      # e.g. 'A_momentum_breakout'
    direction: str = "LONG"
    entry_ref: float = 0.0          # aggressive-entry reference (trigger price)
    trigger_level: float | None = None   # breakout level / prior-day high
    swing_low: float | None = None       # recent pivot low (stop reference)
    base_low: float | None = None         # base/consolidation low (stop reference)
    atr: float = 0.0
    next_resistance: float | None = None   # for T2 refinement
    setup_strength: float = 0.0     # 0..1
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


# Setup identifiers.
SETUP_A = "A_momentum_breakout"
SETUP_B = "B_pullback_trend"
SETUP_C = "C_mean_reversion"
SETUP_D = "D_squeeze_breakout"
SETUP_E = "E_earnings_momentum"

ALL_SETUPS = [SETUP_A, SETUP_B, SETUP_C, SETUP_D, SETUP_E]

# Trend setups gated by the weekly trend gate (§7.6); C uses the MR gate.
TREND_SETUPS = {SETUP_A, SETUP_B, SETUP_D, SETUP_E}


def get_active_setups(regime: str) -> list[str]:
    """Which setups may fire in the given market regime (PLAN 7.5).

    BULL: all. NEUTRAL: A/B/D/E + C. BEAR: only C (capital-preservation mode;
    publisher additionally requires quality>=80 & half size for C in BEAR).
    """
    regime = (regime or "NEUTRAL").upper()
    if regime == "BEAR":
        return [SETUP_C]
    if regime == "RISK_OFF":
        return []  # news-driven risk-off: no new entries (PLAN 17.4)
    # BULL and NEUTRAL allow the full long-side set.
    return list(ALL_SETUPS)
