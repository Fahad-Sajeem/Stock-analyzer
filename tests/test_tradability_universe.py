"""Tests for Layer 0 tradability + the universe job (with a fake inputs provider)."""

from datetime import date, timedelta

import pandas as pd

from analyzer.config import get_config
from analyzer.fundamentals.models import FundamentalInputs
from analyzer.fundamentals.tradability import compute_tradability, tradability_reasons
from analyzer.db.repository import Repository
from analyzer.jobs.universe import evaluate_symbol, run_universe

CFG = get_config()


def test_tradability_reasons_price_and_liquidity():
    row = pd.Series({"close": 10.0, "mcap_cr": 1000.0, "band_pct": None, "surveillance": None})
    reasons = tradability_reasons(row, CFG, n_history=500, median_traded_value_cr=0.5)
    assert any("price" in r for r in reasons)      # 10 < 20
    assert any("liquidity" in r for r in reasons)  # 0.5cr < 3cr


def test_tradability_surveillance_and_band():
    row = pd.Series({"close": 100.0, "mcap_cr": 1000.0, "band_pct": 5, "surveillance": "GSM"})
    reasons = tradability_reasons(row, CFG, n_history=500, median_traded_value_cr=10.0)
    assert any("circuit band" in r for r in reasons)
    assert any("surveillance" in r for r in reasons)


def test_tradability_clean_passes():
    row = pd.Series({"close": 500.0, "mcap_cr": 5000.0, "band_pct": None, "surveillance": None})
    reasons = tradability_reasons(row, CFG, n_history=500, median_traded_value_cr=20.0)
    assert reasons == []


def _seed_prices(repo: Repository, symbol: str, close: float, tv_rupees: float, n: int):
    start = date(2024, 1, 1)
    rows = [
        {
            "symbol": symbol,
            "date": start + timedelta(days=i),
            "open": close, "high": close, "low": close, "close": close,
            "volume": 100000, "traded_value": tv_rupees,
        }
        for i in range(n)
    ]
    repo.upsert_df("prices_raw", pd.DataFrame(rows))


def test_compute_tradability_from_db():
    repo = Repository.open(":memory:")
    # Liquid large-cap: 300 sessions, 5cr/day traded value.
    _seed_prices(repo, "BIG", close=500.0, tv_rupees=5e7, n=300)
    # Illiquid penny: 300 sessions but tiny traded value + low price.
    _seed_prices(repo, "TINY", close=8.0, tv_rupees=1e5, n=300)
    repo.upsert_df("symbols", pd.DataFrame([
        {"isin": "IN1", "symbol": "BIG", "mcap_cr": 5000.0},
        {"isin": "IN2", "symbol": "TINY", "mcap_cr": 50.0},
    ]))

    trad = compute_tradability(repo, CFG)
    big = trad[trad["symbol"] == "BIG"].iloc[0]
    tiny = trad[trad["symbol"] == "TINY"].iloc[0]
    assert big["tradeable"]
    assert not tiny["tradeable"]
    repo.close()


def test_evaluate_symbol_approves_quality_name():
    fi = FundamentalInputs(
        symbol="Q", roe=22, roce=24, roe_3yr=21, roce_3yr=23,
        sales_cagr_3yr=18, eps_growth_ttm_yoy=20, cfo_ebitda_3yr=0.9,
        fcf_positive_years=3, debt_equity=0.3, promoter_pct=60, pledge_pct=0,
        pe=25, ev_ebitda=18, sector_median_pe=22, net_profit_history=[10, 12, 15],
        interest_coverage=9,
    )
    ev = evaluate_symbol("Q", fi, CFG)
    assert ev["approved"]
    assert ev["quality_score"] >= 50


def test_run_universe_end_to_end_with_fake_provider():
    repo = Repository.open(":memory:")
    _seed_prices(repo, "BIG", close=500.0, tv_rupees=5e7, n=300)
    _seed_prices(repo, "TINY", close=8.0, tv_rupees=1e5, n=300)
    repo.upsert_df("symbols", pd.DataFrame([
        {"isin": "IN1", "symbol": "BIG", "mcap_cr": 5000.0},
        {"isin": "IN2", "symbol": "TINY", "mcap_cr": 50.0},
    ]))

    def fake_provider(symbol: str) -> FundamentalInputs:
        # BIG is a quality business; TINY never gets here (fails Layer 0).
        return FundamentalInputs(
            symbol=symbol, roe=22, roce=24, roe_3yr=21, roce_3yr=23,
            sales_cagr_3yr=18, eps_growth_ttm_yoy=20, cfo_ebitda_3yr=0.9,
            fcf_positive_years=3, debt_equity=0.3, promoter_pct=60, pledge_pct=0,
            pe=25, ev_ebitda=18, sector_median_pe=22, net_profit_history=[10, 12, 15],
            interest_coverage=9,
        )

    df = run_universe(repo, inputs_provider=fake_provider, store_fundamentals=False)
    big = df[df["symbol"] == "BIG"].iloc[0]
    tiny = df[df["symbol"] == "TINY"].iloc[0]
    assert big["approved"]
    assert not tiny["approved"]
    assert any("liquidity" in r or "price" in r or "mcap" in r for r in tiny["reject_reasons"])
    repo.close()
