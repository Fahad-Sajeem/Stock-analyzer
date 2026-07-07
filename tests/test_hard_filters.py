"""Tests for the fundamental hard rejection rules (PLAN 6.1)."""

from analyzer.config import get_config
from analyzer.fundamentals.hard_filters import hard_filter_reasons, passes_hard_filters
from analyzer.fundamentals.models import FundamentalInputs

HF = get_config().fundamentals["hard_filters"]


def _clean_stock() -> FundamentalInputs:
    return FundamentalInputs(
        symbol="GOOD",
        is_financial=False,
        pledge_pct=0.0,
        debt_equity=0.4,
        interest_coverage=8.0,
        net_profit_history=[100, 120, 150],
        promoter_pct_change_2q=0.0,
        contingent_liab_to_networth=0.1,
    )


def test_clean_stock_passes():
    assert passes_hard_filters(_clean_stock(), HF)


def test_high_pledge_rejected():
    fi = _clean_stock()
    fi.pledge_pct = 40.0
    reasons = hard_filter_reasons(fi, HF)
    assert any("pledge" in r for r in reasons)


def test_high_debt_rejected_for_nonfinancial():
    fi = _clean_stock()
    fi.debt_equity = 3.0
    assert any("debt/equity" in r for r in hard_filter_reasons(fi, HF))


def test_debt_rule_skipped_for_financial():
    fi = _clean_stock()
    fi.is_financial = True
    fi.debt_equity = 5.0  # normal for a bank
    fi.interest_coverage = 0.5
    # Neither leverage nor coverage should reject a financial.
    assert passes_hard_filters(fi, HF)


def test_low_interest_coverage_rejected():
    fi = _clean_stock()
    fi.interest_coverage = 1.0
    assert any("interest coverage" in r for r in hard_filter_reasons(fi, HF))


def test_consecutive_losses_rejected():
    fi = _clean_stock()
    fi.net_profit_history = [-10, -20, 5]  # loss in 2 of 3
    assert any("net loss" in r for r in hard_filter_reasons(fi, HF))


def test_turnaround_override():
    fi = _clean_stock()
    fi.net_profit_history = [-10, -20, 5]
    fi.last_2q_profitable = True  # turnaround override
    assert passes_hard_filters(fi, HF)


def test_promoter_exit_rejected():
    fi = _clean_stock()
    fi.promoter_pct_change_2q = -8.0
    assert any("promoter holding fell" in r for r in hard_filter_reasons(fi, HF))


def test_auditor_flag_rejected():
    fi = _clean_stock()
    fi.auditor_red_flag = True
    assert any("auditor" in r for r in hard_filter_reasons(fi, HF))


def test_contingent_liability_rejected():
    fi = _clean_stock()
    fi.contingent_liab_to_networth = 0.9
    assert any("contingent" in r for r in hard_filter_reasons(fi, HF))
