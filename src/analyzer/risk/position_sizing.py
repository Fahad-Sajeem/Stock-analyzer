"""Position sizing + portfolio caps (PLAN Section 9). Pure functions.

size = (capital x risk%) / (entry - stop), then capped by:
  * max 15% of capital in one stock,
  * max 5% participation of the stock's 20d average daily traded value,
  * portfolio: max 8 open positions, max 3/sector, max 5% total open risk,
  * correlation cap: reject if corr > 0.7 with >= 2 open positions,
  * gap-risk stress: block new entries if a -5% gap scenario loses > 4% of capital.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class SizingResult:
    qty: int
    notional: float
    risk_amount: float
    capital_frac_pct: float
    caps_applied: list[str] = field(default_factory=list)


def suggest_position(
    capital: float, risk_pct: float, entry: float, stop: float,
    adv_traded_value: float | None, cfg_risk: dict,
) -> SizingResult | None:
    """Suggested quantity for one signal. None if the trade can't be sized."""
    risk_per_share = entry - stop
    if risk_per_share <= 0 or entry <= 0 or capital <= 0:
        return None
    caps: list[str] = []
    risk_amount = capital * risk_pct / 100.0
    qty = int(risk_amount / risk_per_share)

    # Cap: max % of capital in one name.
    max_notional = capital * cfg_risk["max_position_pct"] / 100.0
    if qty * entry > max_notional:
        qty = int(max_notional / entry)
        caps.append(f"capped at {cfg_risk['max_position_pct']:.0f}% of capital")

    # Cap: liquidity participation.
    if adv_traded_value and adv_traded_value > 0:
        max_liq_notional = adv_traded_value * cfg_risk["max_adv_participation_pct"] / 100.0
        if qty * entry > max_liq_notional:
            qty = int(max_liq_notional / entry)
            caps.append(f"capped at {cfg_risk['max_adv_participation_pct']:.0f}% of ADV")

    if qty <= 0:
        return None
    return SizingResult(
        qty=qty,
        notional=round(qty * entry, 2),
        risk_amount=round(qty * risk_per_share, 2),
        capital_frac_pct=round(qty * entry / capital * 100, 2),
        caps_applied=caps,
    )


def portfolio_room(open_positions: pd.DataFrame, sector_of: dict, candidate_sector: str | None,
                   capital: float, cfg_risk: dict) -> tuple[bool, list[str]]:
    """Check portfolio-level caps for adding one more position.

    ``open_positions`` columns: symbol, qty, entry_price, current_sl.
    """
    reasons: list[str] = []
    if len(open_positions) >= cfg_risk["max_open_positions"]:
        reasons.append(f"max open positions ({cfg_risk['max_open_positions']}) reached")

    if candidate_sector and not open_positions.empty:
        sectors = [sector_of.get(s) for s in open_positions["symbol"]]
        n_same = sum(1 for s in sectors if s and s == candidate_sector)
        if n_same >= cfg_risk["max_positions_per_sector"]:
            reasons.append(f"max positions in sector {candidate_sector} reached")

    if not open_positions.empty:
        open_risk = (
            (open_positions["entry_price"] - open_positions["current_sl"]).clip(lower=0)
            * open_positions["qty"]
        ).sum()
        if open_risk / capital * 100 >= cfg_risk["max_total_open_risk_pct"]:
            reasons.append(
                f"total open risk {open_risk / capital * 100:.1f}% >= "
                f"{cfg_risk['max_total_open_risk_pct']:.0f}%"
            )
    return (len(reasons) == 0, reasons)


def correlation_ok(
    candidate_returns: pd.Series, open_returns: dict[str, pd.Series], cfg_risk: dict
) -> tuple[bool, list[str]]:
    """Correlation cap (PLAN §9): reject if 60d daily-return correlation > 0.7
    with >= 2 open positions."""
    threshold = cfg_risk.get("correlation_threshold", 0.7)
    if candidate_returns is None or candidate_returns.dropna().empty or not open_returns:
        return True, []
    high = []
    for sym, r in open_returns.items():
        joined = pd.concat([candidate_returns, r], axis=1, join="inner").dropna()
        if len(joined) < 20:
            continue
        c = joined.iloc[:, 0].corr(joined.iloc[:, 1])
        if not np.isnan(c) and c > threshold:
            high.append(f"{sym} (corr {c:.2f})")
    if len(high) >= 2:
        return False, [f"correlated > {threshold} with: {', '.join(high)}"]
    return True, []


def gap_stress(open_positions: pd.DataFrame, capital: float, cfg_risk: dict) -> dict:
    """Portfolio P&L if every open position gaps down 5% / 10% overnight."""
    out = {"scenarios": {}, "blocked": False}
    if open_positions.empty or capital <= 0:
        return out
    notional = (open_positions["entry_price"] * open_positions["qty"]).sum()
    for pct in cfg_risk.get("gap_stress_pct", [5, 10]):
        loss = notional * pct / 100.0
        out["scenarios"][f"-{pct}%"] = round(loss / capital * 100, 2)
    worst_allowed = cfg_risk.get("gap_stress_max_loss_pct", 4.0)
    first = cfg_risk.get("gap_stress_pct", [5])[0]
    if out["scenarios"].get(f"-{first}%", 0) > worst_allowed:
        out["blocked"] = True
    return out
