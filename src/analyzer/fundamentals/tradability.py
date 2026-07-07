"""Layer 0 — tradability filter (PLAN Section 3.2).

Hard gates computed from our OWN price DB + symbol master (no network): liquidity,
price floor, listing age, market-cap floor, circuit band, surveillance status.
This runs BEFORE fundamentals to shrink ~5,000 stocks to the liquid ~1,200.
"""

from __future__ import annotations

import pandas as pd

from analyzer.config import Config
from analyzer.logging_setup import get_logger

log = get_logger(__name__)


def tradability_reasons(
    row: pd.Series, cfg: Config, n_history: int, median_traded_value_cr: float | None
) -> list[str]:
    """Return reject reasons for one symbol (empty list = tradeable).

    ``row`` carries symbol-master fields (mcap_cr, band_pct, surveillance) plus the
    latest close. ``n_history`` = number of price rows (listing-age proxy).
    """
    t = cfg.tradability
    reasons: list[str] = []

    close = row.get("close")
    if close is not None and not pd.isna(close) and close < t.min_price:
        reasons.append(f"price {close:.1f} < {t.min_price:.0f}")

    if median_traded_value_cr is not None and median_traded_value_cr < t.min_median_traded_value_cr:
        reasons.append(
            f"liquidity {median_traded_value_cr:.2f}cr/day < {t.min_median_traded_value_cr:.0f}cr"
        )

    if n_history < t.min_listing_days:
        reasons.append(f"only {n_history} sessions of history < {t.min_listing_days}")

    mcap = row.get("mcap_cr")
    if mcap is not None and not pd.isna(mcap) and mcap < t.min_mcap_cr:
        reasons.append(f"mcap {mcap:.0f}cr < {t.min_mcap_cr:.0f}cr")

    band = row.get("band_pct")
    if band is not None and not pd.isna(band) and int(band) in set(t.excluded_bands_pct):
        reasons.append(f"circuit band {int(band)}%")

    surv = row.get("surveillance")
    if surv and not pd.isna(surv):
        surv_str = str(surv).upper()
        for flag in t.exclude_surveillance:
            if flag in surv_str:
                reasons.append(f"surveillance {surv_str}")
                break
        # ASM stage parsing: 'ASM2', 'ASM Stage 2', etc.
        if "ASM" in surv_str:
            stage = "".join(ch for ch in surv_str if ch.isdigit())
            if stage and int(stage) > t.asm_max_stage:
                reasons.append(f"ASM stage {stage} > {t.asm_max_stage}")

    return reasons


def compute_tradability(repo, cfg: Config, as_of=None) -> pd.DataFrame:
    """Evaluate every symbol with price history against Layer 0 gates.

    Returns a DataFrame: symbol, tradeable(bool), reasons(list), close,
    median_traded_value_cr, n_history.
    """
    vol_period = cfg.technicals.get("vol_avg_period", 20)
    # Per-symbol: latest close, history count, and median traded value over last N rows.
    stats = repo.query_df(
        """
        WITH ranked AS (
            SELECT symbol, date, close, traded_value,
                   ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) AS rn,
                   COUNT(*) OVER (PARTITION BY symbol) AS n_history
            FROM prices_raw
        )
        SELECT symbol,
               ANY_VALUE(n_history)                                   AS n_history,
               MAX(CASE WHEN rn = 1 THEN close END)                   AS close,
               MEDIAN(CASE WHEN rn <= ? THEN traded_value END) / 1e7  AS median_traded_value_cr
        FROM ranked
        GROUP BY symbol
        """,
        [vol_period],
    )
    if stats.empty:
        return pd.DataFrame(columns=["symbol", "tradeable", "reasons"])

    syms = repo.query_df(
        "SELECT symbol, mcap_cr, band_pct, surveillance FROM symbols"
    )
    df = stats.merge(syms, on="symbol", how="left")

    out_rows = []
    for _, row in df.iterrows():
        reasons = tradability_reasons(
            row, cfg, int(row["n_history"]), row.get("median_traded_value_cr")
        )
        out_rows.append(
            {
                "symbol": row["symbol"],
                "tradeable": len(reasons) == 0,
                "reasons": reasons,
                "close": row.get("close"),
                "median_traded_value_cr": row.get("median_traded_value_cr"),
                "n_history": int(row["n_history"]),
            }
        )
    result = pd.DataFrame(out_rows)
    log.info(
        "tradability_computed",
        total=len(result),
        tradeable=int(result["tradeable"].sum()),
    )
    return result
