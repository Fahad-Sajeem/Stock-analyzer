"""Quality score 0-100 (PLAN Section 6.2).

NOT a value screen — it certifies a business is strong & clean enough to swing
trade. Six weighted components; banks/NBFCs use an ROA-based profitability branch
and a neutral balance-sheet treatment (leverage is their business model).

Each component returns points in [0, weight]. Components with no data score 0 and
add a note (conservative: unverifiable stocks won't clear the gate). The final
score also feeds the composite signal score (PLAN 8.6).
"""

from __future__ import annotations

from analyzer.fundamentals.models import FundamentalInputs, QualityResult
from analyzer.fundamentals.ratios import average


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _linear(x: float | None, floor: float, full: float) -> float | None:
    """Map x in [floor, full] -> [0, 1], clamped. None if x is None."""
    if x is None:
        return None
    if full == floor:
        return 1.0 if x >= full else 0.0
    return _clamp((x - floor) / (full - floor))


def _score_profitability(fi: FundamentalInputs, t: dict, weight: float) -> tuple[float, str | None]:
    if fi.is_financial:
        roa = fi.roa
        roe = fi.roe_3yr if fi.roe_3yr is not None else fi.roe
        sub_roa = _linear(roa, t["roa_floor"], t["roa_full"])
        sub_roe = _linear(roe, t["bank_roe_floor"], t["bank_roe_full"])
        subs = [s for s in (sub_roa, sub_roe) if s is not None]
        if not subs:
            return 0.0, "profitability: no bank ROA/ROE data"
        return weight * (sum(subs) / len(subs)), None
    roce = fi.roce_3yr if fi.roce_3yr is not None else fi.roce
    roe = fi.roe_3yr if fi.roe_3yr is not None else fi.roe
    sub_roce = _linear(roce, t["roce_floor"], t["roce_full"])
    sub_roe = _linear(roe, t["roe_floor"], t["roe_full"])
    subs = [s for s in (sub_roce, sub_roe) if s is not None]
    if not subs:
        return 0.0, "profitability: no ROE/ROCE data"
    return weight * (sum(subs) / len(subs)), None


def _score_growth(fi: FundamentalInputs, t: dict, weight: float) -> tuple[float, str | None]:
    full = t["growth_full_pct"]
    sub_sales = _linear(fi.sales_cagr_3yr, 0.0, full)
    sub_eps = _linear(fi.eps_growth_ttm_yoy, 0.0, full)
    subs = [s for s in (sub_sales, sub_eps) if s is not None]
    if not subs:
        return 0.0, "growth: no sales/EPS growth data"
    base = sum(subs) / len(subs)
    # Recent-quarter acceleration bonus.
    if (
        fi.sales_growth_recent_q is not None
        and fi.sales_cagr_3yr is not None
        and fi.sales_growth_recent_q > fi.sales_cagr_3yr
    ):
        base = _clamp(base + t["accel_bonus_frac"])
    return weight * base, None


def _score_earnings_quality(
    fi: FundamentalInputs, t: dict, weight: float
) -> tuple[float, str | None]:
    sub_cfo = _linear(fi.cfo_ebitda_3yr, 0.0, t["cfo_ebitda_full"])
    sub_fcf = (
        _clamp(fi.fcf_positive_years / t["fcf_years_full"])
        if fi.fcf_positive_years is not None
        else None
    )
    subs = [s for s in (sub_cfo, sub_fcf) if s is not None]
    if not subs:
        return 0.0, "earnings quality: no CFO/FCF data"
    return weight * (sum(subs) / len(subs)), None


def _score_balance_sheet(fi: FundamentalInputs, t: dict, weight: float) -> tuple[float, str | None]:
    if fi.is_financial:
        # Leverage ratios aren't meaningful for banks; give a neutral score.
        return weight * 0.6, "balance sheet: neutral (financial)"
    de = fi.debt_equity
    if de is None:
        return 0.0, "balance sheet: no debt/equity data"
    if de <= t["de_full"]:
        sub = 1.0
    else:
        sub = _clamp((t["de_floor"] - de) / (t["de_floor"] - t["de_full"]))
    if fi.debt_trend_declining:
        sub = _clamp(sub + t["debt_decline_bonus_frac"])
    return weight * sub, None


def _score_ownership(fi: FundamentalInputs, t: dict, weight: float) -> tuple[float, str | None]:
    sub = _linear(fi.promoter_pct, t["promoter_floor"], t["promoter_full"])
    if sub is None:
        return 0.0, "ownership: no promoter-holding data"
    # Pledge (even below the 25% hard-reject) costs proportional points.
    if fi.pledge_pct:
        sub *= _clamp(1.0 - fi.pledge_pct / 25.0)
    if fi.fii_dii_rising:
        sub = _clamp(sub + t["fii_dii_bonus_frac"])
    return weight * sub, None


def _score_valuation_sanity(
    fi: FundamentalInputs, t: dict, weight: float
) -> tuple[float, str | None]:
    # Start at full marks; only penalize genuine insanity (extremes reverse hard).
    sub = 1.0
    noted = False
    if fi.pe is not None and fi.sector_median_pe and fi.sector_median_pe > 0:
        if fi.pe > t["pe_sector_mult_max"] * fi.sector_median_pe:
            sub -= 0.5
            noted = True
    if fi.ev_ebitda is not None and fi.ev_ebitda > t["ev_ebitda_max"]:
        sub -= 0.5
        noted = True
    sub = _clamp(sub)
    note = "valuation: extreme multiple penalized" if noted else None
    return weight * sub, note


def compute_quality_score(fi: FundamentalInputs, cfg_fundamentals: dict) -> QualityResult:
    weights = cfg_fundamentals["quality_weights"]
    t = cfg_fundamentals["quality_thresholds"]

    components = {
        "profitability": _score_profitability(fi, t, weights["profitability"]),
        "growth": _score_growth(fi, t, weights["growth"]),
        "earnings_quality": _score_earnings_quality(fi, t, weights["earnings_quality"]),
        "balance_sheet": _score_balance_sheet(fi, t, weights["balance_sheet"]),
        "ownership": _score_ownership(fi, t, weights["ownership"]),
        "valuation_sanity": _score_valuation_sanity(fi, t, weights["valuation_sanity"]),
    }

    breakdown = {name: pts for name, (pts, _note) in components.items()}
    notes = [note for (_pts, note) in components.values() if note]
    # Data completeness = fraction of components that had usable data (no "no data" note).
    missing = sum(1 for (_p, n) in components.values() if n and "no " in n)
    completeness = 1.0 - missing / len(components)

    score = sum(breakdown.values())
    return QualityResult(
        symbol=fi.symbol,
        score=score,
        breakdown=breakdown,
        notes=notes,
        data_completeness=completeness,
    )
