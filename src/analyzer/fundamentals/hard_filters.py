"""Hard rejection rules (PLAN Section 6.1).

Any one triggered -> the stock is excluded from the tradeable universe regardless
of its quality score. These are the India-specific governance/solvency landmines
(pledge invocation, leverage blowups, insider exits, auditor red flags).

``hard_filter_reasons`` returns a list of human-readable reject reasons (empty =
passes). Banks/NBFCs (``is_financial``) skip the leverage rules that don't apply
to their business model.
"""

from __future__ import annotations

from analyzer.fundamentals.models import FundamentalInputs
from analyzer.fundamentals.ratios import count_negative


def hard_filter_reasons(fi: FundamentalInputs, hf: dict) -> list[str]:
    reasons: list[str] = []

    # 1. Promoter pledge -----------------------------------------------------
    max_pledge = hf.get("max_pledge_pct", 25.0)
    if fi.pledge_pct is not None and fi.pledge_pct > max_pledge:
        reasons.append(f"promoter pledge {fi.pledge_pct:.1f}% > {max_pledge:.0f}%")

    # 2 & 3. Leverage / solvency (non-financials only) -----------------------
    if not fi.is_financial:
        max_de = hf.get("max_debt_equity", 2.0)
        if fi.debt_equity is not None and fi.debt_equity > max_de:
            reasons.append(f"debt/equity {fi.debt_equity:.2f} > {max_de:.1f}")
        min_ic = hf.get("min_interest_coverage", 2.0)
        if fi.interest_coverage is not None and fi.interest_coverage < min_ic:
            reasons.append(f"interest coverage {fi.interest_coverage:.2f} < {min_ic:.1f}")

    # 4. Consecutive loss years (turnaround override) ------------------------
    max_loss = hf.get("max_loss_years_in_3", 1)
    loss_years = count_negative(fi.net_profit_history[-3:])
    if loss_years > max_loss:
        if fi.last_2q_profitable:
            pass  # turnaround override: last 2 quarters profitable
        else:
            reasons.append(f"net loss in {loss_years} of last 3 FYs")

    # 5. Auditor red flag ----------------------------------------------------
    if fi.auditor_red_flag:
        reasons.append("auditor resignation / qualified opinion in last 12 months")

    # 6. Promoter holding falling --------------------------------------------
    max_drop = hf.get("max_promoter_drop_pp", 5.0)
    if fi.promoter_pct_change_2q is not None and fi.promoter_pct_change_2q < -max_drop:
        reasons.append(
            f"promoter holding fell {abs(fi.promoter_pct_change_2q):.1f}pp in 2 quarters"
        )

    # 7. Contingent liabilities ----------------------------------------------
    max_cl = hf.get("max_contingent_liab_to_networth", 0.5)
    if fi.contingent_liab_to_networth is not None and fi.contingent_liab_to_networth > max_cl:
        reasons.append(
            f"contingent liabilities {fi.contingent_liab_to_networth:.0%} of net worth "
            f"> {max_cl:.0%}"
        )

    return reasons


def passes_hard_filters(fi: FundamentalInputs, hf: dict) -> bool:
    return len(hard_filter_reasons(fi, hf)) == 0
