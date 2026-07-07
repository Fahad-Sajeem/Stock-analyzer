"""Market regime module (PLAN 7.5) — gates all setups.

BULL:    Nifty 50 > 50DMA > 200DMA AND breadth (% of universe > 200DMA) > 55%
BEAR:    Nifty 50 < 200DMA OR breadth < 35%
NEUTRAL: everything else
India VIX > threshold is carried through for downstream position-size halving.

Writes one row per trading day to ``regime_daily``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analyzer.config import Config, get_config
from analyzer.logging_setup import get_logger
from analyzer.technicals.indicators import sma

log = get_logger(__name__)


def classify_regime(
    nifty_close: float, dma50: float, dma200: float, breadth: float, cfg: Config
) -> str:
    r = cfg.regime
    if any(np.isnan(x) for x in (nifty_close, dma200)):
        return "NEUTRAL"
    bull_breadth = r.get("breadth_bull_pct", 55.0)
    bear_breadth = r.get("breadth_bear_pct", 35.0)
    has_breadth = not np.isnan(breadth)

    if nifty_close < dma200 or (has_breadth and breadth < bear_breadth):
        return "BEAR"
    # BULL needs a clean price stack; breadth CONFIRMS when available but its
    # absence (e.g. thin universe / historical backfill) must not block a bull.
    price_stack = (not np.isnan(dma50)) and (nifty_close > dma50 > dma200)
    breadth_ok = (not has_breadth) or (breadth > bull_breadth)
    if price_stack and breadth_ok:
        return "BULL"
    return "NEUTRAL"


def compute_breadth(repo) -> pd.DataFrame:
    """% of stocks trading above their own 200DMA, per date (market breadth)."""
    return repo.query_df(
        """
        SELECT a.date AS date,
               AVG(CASE WHEN a.close > i.sma200 THEN 1.0 ELSE 0.0 END) * 100.0 AS breadth
        FROM prices_adj a
        JOIN indicators_daily i ON i.symbol = a.symbol AND i.date = a.date
        WHERE i.sma200 IS NOT NULL
        GROUP BY a.date
        ORDER BY a.date
        """
    )


def run_compute_regime(repo, cfg: Config | None = None) -> int:
    cfg = cfg or get_config()
    with repo.job_run("compute_regime") as jr:
        nifty = repo.query_df(
            "SELECT date, close FROM index_prices WHERE index_name='NIFTY50' ORDER BY date"
        )
        if nifty.empty:
            log.warning("regime_no_nifty")
            return 0
        nifty["date"] = pd.to_datetime(nifty["date"])
        nifty = nifty.set_index("date")
        nifty["dma50"] = sma(nifty["close"], 50)
        nifty["dma200"] = sma(nifty["close"], 200)

        breadth = compute_breadth(repo)
        breadth_map = {}
        if not breadth.empty:
            breadth["date"] = pd.to_datetime(breadth["date"])
            breadth_map = dict(zip(breadth["date"], breadth["breadth"]))

        vix = repo.query_df(
            "SELECT date, close FROM index_prices WHERE index_name='INDIAVIX' ORDER BY date"
        )
        vix_map = {}
        if not vix.empty:
            vix["date"] = pd.to_datetime(vix["date"])
            vix_map = dict(zip(vix["date"], vix["close"]))

        rows = []
        for dt, row in nifty.iterrows():
            b = breadth_map.get(dt, np.nan)
            regime = classify_regime(row["close"], row["dma50"], row["dma200"], b, cfg)
            rows.append(
                {
                    "date": dt.date(),
                    "regime": regime,
                    "nifty_close": float(row["close"]),
                    "breadth_above_200dma": None if np.isnan(b) else float(b),
                    "india_vix": vix_map.get(dt),
                }
            )
        df = pd.DataFrame(rows)
        n = repo.upsert_df("regime_daily", df)
        jr.add_rows(n)
    log.info("regime_computed", rows=n)
    return n
