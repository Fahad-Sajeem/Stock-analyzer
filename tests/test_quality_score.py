"""Tests for the 0-100 quality score (PLAN 6.2)."""

from analyzer.config import get_config
from analyzer.fundamentals.models import FundamentalInputs
from analyzer.fundamentals.quality_score import compute_quality_score

FUND = get_config().fundamentals


def _excellent() -> FundamentalInputs:
    return FundamentalInputs(
        symbol="EXCEL",
        is_financial=False,
        roe=24.0, roce=26.0, roe_3yr=23.0, roce_3yr=25.0,
        sales_cagr_3yr=20.0, eps_growth_ttm_yoy=22.0, sales_growth_recent_q=25.0,
        cfo_ebitda_3yr=0.9, fcf_positive_years=3,
        debt_equity=0.2, debt_trend_declining=True,
        promoter_pct=60.0, pledge_pct=0.0, fii_dii_rising=True,
        pe=25.0, ev_ebitda=18.0, sector_median_pe=22.0,
    )


def _weak() -> FundamentalInputs:
    return FundamentalInputs(
        symbol="WEAK",
        is_financial=False,
        roe=6.0, roce=8.0, roe_3yr=6.0, roce_3yr=8.0,
        sales_cagr_3yr=1.0, eps_growth_ttm_yoy=0.0,
        cfo_ebitda_3yr=0.2, fcf_positive_years=0,
        debt_equity=1.8, debt_trend_declining=False,
        promoter_pct=32.0, pledge_pct=20.0, fii_dii_rising=False,
        pe=120.0, ev_ebitda=55.0, sector_median_pe=20.0,
    )


def test_excellent_scores_high():
    r = compute_quality_score(_excellent(), FUND)
    assert r.score >= 85
    assert r.data_completeness == 1.0


def test_weak_scores_low():
    r = compute_quality_score(_weak(), FUND)
    assert r.score <= 30


def test_valuation_penalty_applied():
    r = compute_quality_score(_weak(), FUND)
    # weak stock has PE 120 (>3x sector 20) and EV/EBITDA 55 (>40) -> 0 valuation pts
    assert r.breakdown["valuation_sanity"] == 0.0


def test_score_bounded_0_100():
    for fi in (_excellent(), _weak()):
        r = compute_quality_score(fi, FUND)
        assert 0.0 <= r.score <= 100.0


def test_breakdown_sums_to_score():
    r = compute_quality_score(_excellent(), FUND)
    assert abs(sum(r.breakdown.values()) - r.score) < 1e-9


def test_missing_data_lowers_completeness_and_score():
    fi = FundamentalInputs(symbol="EMPTY")  # nothing known
    r = compute_quality_score(fi, FUND)
    assert r.data_completeness < 0.5
    assert r.score < 20  # unverifiable -> won't clear the gate


def test_bank_uses_roa_branch():
    bank = FundamentalInputs(
        symbol="BANK", is_financial=True,
        roa=1.4, roe=17.0, roe_3yr=16.0,
        sales_cagr_3yr=18.0, eps_growth_ttm_yoy=20.0,
        cfo_ebitda_3yr=0.8, fcf_positive_years=2,
        promoter_pct=55.0, pledge_pct=0.0,
        pe=18.0, ev_ebitda=None, sector_median_pe=16.0,
    )
    r = compute_quality_score(bank, FUND)
    # profitability should score well off ROA/ROE, not choke on missing ROCE.
    assert r.breakdown["profitability"] > 18
    # balance sheet is the neutral financial treatment, not zero.
    assert r.breakdown["balance_sheet"] > 0
