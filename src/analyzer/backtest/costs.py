"""Round-trip cost model for Indian delivery equity (PLAN 10.2).

Any strategy that dies under realistic costs is dead — better to know now. Models
STT, exchange/GST/stamp charges, and slippage per side. Discount-broker brokerage
is ~0 and ignored. Slippage scales up for illiquid names.

Total modeled round-trip is ~0.5-0.6% for liquid stocks — the single biggest
reason marginal setups fail.
"""

from __future__ import annotations


def round_trip_cost_pct(cfg_backtest: dict, liquidity_factor: float = 1.0) -> float:
    """Total round-trip cost as a percent of trade value.

    ``liquidity_factor`` >= 1 inflates slippage for thinner names (1.0 = liquid
    large-cap; e.g. 2.0 doubles the slippage component).
    """
    stt = cfg_backtest["stt_pct_per_side"] * 2          # buy + sell
    other = cfg_backtest["other_costs_pct_per_side"] * 2
    slippage = cfg_backtest["slippage_pct_per_side"] * 2 * max(1.0, liquidity_factor)
    return stt + other + slippage


def apply_costs_to_r(gross_r: float, entry: float, risk_per_share: float,
                     cfg_backtest: dict, liquidity_factor: float = 1.0) -> float:
    """Convert a gross return (in R multiples) to net-of-costs R.

    Costs are a percent of notional on both legs; expressed in R by dividing the
    cost rupees-per-share by the risk-per-share.
    """
    if risk_per_share <= 0:
        return gross_r
    cost_pct = round_trip_cost_pct(cfg_backtest, liquidity_factor)
    cost_per_share = cost_pct / 100.0 * entry
    cost_r = cost_per_share / risk_per_share
    return gross_r - cost_r
