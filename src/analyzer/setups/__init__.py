"""Setup scanners (PLAN 7.3). Each detects one tradeable pattern on the last bar
of a per-symbol price+indicator frame and returns a RawSignal (or None).

Setups are pure functions so they are testable with synthetic data and reusable
by the backtester (Phase 5) unchanged.
"""

from analyzer.setups.base import (
    ALL_SETUPS,
    SETUP_A,
    SETUP_B,
    SETUP_C,
    SETUP_D,
    SETUP_E,
    RawSignal,
    get_active_setups,
)
from analyzer.setups.breakout import scan_breakout
from analyzer.setups.earnings_momentum import scan_earnings_momentum
from analyzer.setups.mean_reversion import scan_mean_reversion
from analyzer.setups.pullback import scan_pullback
from analyzer.setups.squeeze import scan_squeeze

# Dispatch map: setup id -> scanner function (df, cfg_setups) -> RawSignal | None
SCANNERS = {
    SETUP_A: scan_breakout,
    SETUP_B: scan_pullback,
    SETUP_C: scan_mean_reversion,
    SETUP_D: scan_squeeze,
    SETUP_E: scan_earnings_momentum,
}

__all__ = ["RawSignal", "ALL_SETUPS", "get_active_setups", "SCANNERS"]

