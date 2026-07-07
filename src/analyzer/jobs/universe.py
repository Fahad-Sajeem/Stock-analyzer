"""Weekly universe job (PLAN 2.4 / Section 6.4).

Funnels the full symbol list through Layer 0 (tradability) then Layer 1
(hard filters + quality score) and writes the approve/reject decision, score, and
reasons to the ``universe`` table. This "approved universe" is what the daily
technical scanner is allowed to trade.

The fundamental ``inputs_provider`` is injectable so the job can be unit-tested
with synthetic data instead of hitting the network.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Callable

import pandas as pd

from analyzer.config import Config, get_config
from analyzer.fundamentals.fetch_yfinance import build_inputs_from_yfinance, snapshot_row
from analyzer.fundamentals.hard_filters import hard_filter_reasons
from analyzer.fundamentals.models import FundamentalInputs
from analyzer.fundamentals.quality_score import compute_quality_score
from analyzer.fundamentals.tradability import compute_tradability
from analyzer.logging_setup import get_logger

log = get_logger(__name__)

InputsProvider = Callable[[str], FundamentalInputs]


def evaluate_symbol(
    symbol: str, fi: FundamentalInputs, cfg: Config
) -> dict:
    """Apply hard filters + quality score to one symbol's fundamentals.

    Returns a dict with approved(bool), quality_score, reject_reasons, breakdown.
    (Tradability is decided separately in the job and merged in.)
    """
    hf = cfg.fundamentals["hard_filters"]
    reasons = hard_filter_reasons(fi, hf)
    result = compute_quality_score(fi, cfg.fundamentals)

    min_score = cfg.fundamentals["approve_min_score"]
    below = result.score < min_score
    if below:
        reasons.append(f"quality score {result.score:.0f} < {min_score}")

    approved = len(reasons) == 0
    return {
        "symbol": symbol,
        "approved": approved,
        "quality_score": result.score,
        "reject_reasons": reasons,
        "breakdown": result.breakdown,
        "notes": result.notes,
        "data_completeness": result.data_completeness,
    }


def run_universe(
    repo,
    cfg: Config | None = None,
    as_of: date | None = None,
    inputs_provider: InputsProvider | None = None,
    limit: int | None = None,
    store_fundamentals: bool = True,
) -> pd.DataFrame:
    """Build the approved universe and persist to the ``universe`` table.

    ``limit`` caps how many tradeable symbols are fundamentally evaluated (useful
    for a quick spot-check run without fetching thousands of names).
    """
    cfg = cfg or get_config()
    as_of = as_of or date.today()
    inputs_provider = inputs_provider or build_inputs_from_yfinance

    with repo.job_run(f"universe:{as_of}") as jr:
        trad = compute_tradability(repo, cfg, as_of)
        if trad.empty:
            log.warning("universe_no_prices")
            return trad

        tradeable = trad[trad["tradeable"]].copy()
        if limit is not None:
            tradeable = tradeable.head(limit)
        log.info("universe_evaluating", tradeable=len(tradeable))

        rows = []
        snapshots = []
        for _, tr in tradeable.iterrows():
            symbol = tr["symbol"]
            try:
                fi = inputs_provider(symbol)
            except Exception as exc:  # noqa: BLE001
                log.warning("inputs_provider_failed", symbol=symbol, error=str(exc))
                fi = FundamentalInputs(symbol=symbol)
            ev = evaluate_symbol(symbol, fi, cfg)
            rows.append(ev)
            if store_fundamentals:
                snapshots.append(snapshot_row(fi))

        # Non-tradeable symbols are recorded as rejected (Layer 0 reasons).
        for _, tr in trad[~trad["tradeable"]].iterrows():
            rows.append(
                {
                    "symbol": tr["symbol"],
                    "approved": False,
                    "quality_score": 0.0,
                    "reject_reasons": list(tr["reasons"]),
                    "breakdown": {},
                    "notes": ["failed tradability (Layer 0)"],
                    "data_completeness": 0.0,
                }
            )

        universe_df = pd.DataFrame(
            [
                {
                    "symbol": r["symbol"],
                    "as_of": as_of,
                    "approved": r["approved"],
                    "quality_score": r["quality_score"],
                    "reject_reasons": r["reject_reasons"],
                    "score_breakdown": json.dumps(
                        {"breakdown": r["breakdown"], "notes": r["notes"],
                         "data_completeness": r["data_completeness"]}
                    ),
                }
                for r in rows
            ]
        )
        n = repo.upsert_df("universe", universe_df)
        jr.add_rows(n)

        if store_fundamentals and snapshots:
            repo.upsert_df("fundamentals", pd.DataFrame(snapshots))

    approved_n = int(universe_df["approved"].sum())
    log.info("universe_done", total=len(universe_df), approved=approved_n)
    return universe_df
