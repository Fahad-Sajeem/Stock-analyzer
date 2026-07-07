"""The fundamental-analysis data contract.

``FundamentalInputs`` is the source-agnostic, normalized set of fields the hard
filters and quality score consume. Fetchers (yfinance / Screener) map their raw
data INTO this model; the scoring logic never touches a data source directly.

Every field is Optional: real-world fundamental data is patchy. The scoring
functions treat missing inputs conservatively (a component with no data scores
low and is noted), so a stock we cannot verify simply won't clear the gate —
the safe default for a system that risks money.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class FundamentalInputs:
    symbol: str
    # Branch flag: banks/NBFCs skip D/E & interest-coverage rules and use ROA.
    is_financial: bool = False

    # --- profitability -------------------------------------------------------
    roe: float | None = None            # latest %, or 3yr avg if that's all we have
    roce: float | None = None
    roa: float | None = None            # banks
    roe_3yr: float | None = None
    roce_3yr: float | None = None

    # --- growth --------------------------------------------------------------
    sales_cagr_3yr: float | None = None       # %
    eps_growth_ttm_yoy: float | None = None    # %
    sales_growth_recent_q: float | None = None # % YoY, latest quarter

    # --- earnings quality ----------------------------------------------------
    cfo_ebitda_3yr: float | None = None        # ratio
    fcf_positive_years: int | None = None      # count in last 3 FY

    # --- balance sheet -------------------------------------------------------
    debt_equity: float | None = None
    interest_coverage: float | None = None
    debt_trend_declining: bool | None = None

    # --- ownership -----------------------------------------------------------
    promoter_pct: float | None = None
    promoter_pct_change_2q: float | None = None  # pp change over last 2 quarters
    pledge_pct: float | None = None
    fii_dii_rising: bool | None = None

    # --- valuation -----------------------------------------------------------
    pe: float | None = None
    ev_ebitda: float | None = None
    sector_median_pe: float | None = None

    # --- hard-filter-only fields --------------------------------------------
    net_profit_history: list[float] = field(default_factory=list)  # last 3 FY
    last_2q_profitable: bool | None = None
    auditor_red_flag: bool = False
    contingent_liab_to_networth: float | None = None

    source: str = "unknown"


@dataclass
class QualityResult:
    symbol: str
    score: float                      # 0-100
    breakdown: dict[str, float]       # component -> points
    notes: list[str] = field(default_factory=list)
    data_completeness: float = 1.0    # fraction of components with data

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "score": round(self.score, 1),
            "breakdown": {k: round(v, 1) for k, v in self.breakdown.items()},
            "notes": self.notes,
            "data_completeness": round(self.data_completeness, 2),
        }
