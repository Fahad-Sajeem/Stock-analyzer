"""Index / VIX ingestion (PLAN 3.3, 7.5).

Fetches Nifty 50, Nifty 500 and India VIX daily history via yfinance into the
``index_prices`` table. These benchmarks drive the market-regime module and the
relative-strength ranking.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from analyzer.config import get_config
from analyzer.logging_setup import get_logger

log = get_logger(__name__)


def _fetch_yf_index(tickers: list[str], start: date, end: date) -> pd.DataFrame:
    import yfinance as yf

    for tk in tickers:
        try:
            hist = yf.download(
                tk, start=start.isoformat(), end=(end + timedelta(days=1)).isoformat(),
                interval="1d", auto_adjust=False, progress=False, threads=False,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("index_download_failed", ticker=tk, error=str(exc))
            continue
        if hist is not None and not hist.empty:
            if isinstance(hist.columns, pd.MultiIndex):
                hist.columns = hist.columns.get_level_values(0)
            return hist.reset_index()
    return pd.DataFrame()


def ingest_indices(repo, years: int | None = None) -> int:
    cfg = get_config()
    years = years or cfg.ingestion.backfill_years
    start = date.today() - timedelta(days=int(years * 365.25))
    end = date.today()
    tickers_map = cfg.regime.get("index_tickers", {})

    written = 0
    with repo.job_run("ingest_indices") as jr:
        for index_name, tickers in tickers_map.items():
            hist = _fetch_yf_index(list(tickers), start, end)
            if hist.empty:
                log.warning("index_no_data", index=index_name)
                continue
            df = pd.DataFrame(
                {
                    "index_name": index_name,
                    "date": pd.to_datetime(hist["Date"]).dt.date,
                    "open": pd.to_numeric(hist.get("Open"), errors="coerce"),
                    "high": pd.to_numeric(hist.get("High"), errors="coerce"),
                    "low": pd.to_numeric(hist.get("Low"), errors="coerce"),
                    "close": pd.to_numeric(hist["Close"], errors="coerce"),
                }
            ).dropna(subset=["close"])
            written += repo.upsert_df("index_prices", df)
        jr.add_rows(written)
    log.info("indices_ingested", rows=written)
    return written


def load_index_close(repo, index_name: str) -> pd.Series:
    df = repo.query_df(
        "SELECT date, close FROM index_prices WHERE index_name = ? ORDER BY date", [index_name]
    )
    if df.empty:
        return pd.Series(dtype="float64")
    return pd.Series(df["close"].values, index=pd.to_datetime(df["date"]))
