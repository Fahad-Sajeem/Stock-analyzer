"""Historical backfill via yfinance (PLAN 4.1 pt.4, 4.2 pt.4).

Used to seed 10 years of daily history quickly. yfinance is convenient but
rate-limited and occasionally wrong on Indian corporate actions, so it is a
BACKFILL / cross-validation source — never the primary daily feed (that is the
NSE bhavcopy). Delivery data is unavailable here (left NULL).
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from analyzer.config import get_config
from analyzer.logging_setup import get_logger

log = get_logger(__name__)


def _yf():
    import yfinance as yf  # imported lazily so the dep is optional at import time

    return yf


def backfill_symbol(symbol: str, start: date, end: date | None = None) -> pd.DataFrame:
    """Fetch raw (unadjusted) daily OHLCV for one NSE symbol into prices_raw shape."""
    cfg = get_config()
    yf = _yf()
    ticker = f"{symbol}{cfg.ingestion.yfinance_suffix_nse}"
    end = end or date.today()
    try:
        hist = yf.download(
            ticker,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=False,   # keep raw OHLC; we adjust ourselves via corporate_actions
            progress=False,
            threads=False,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("yf_download_failed", symbol=symbol, error=str(exc))
        return pd.DataFrame()

    if hist is None or hist.empty:
        return pd.DataFrame()

    # yfinance may return a MultiIndex on columns for a single ticker.
    if isinstance(hist.columns, pd.MultiIndex):
        hist.columns = hist.columns.get_level_values(0)

    hist = hist.reset_index()
    out = pd.DataFrame(
        {
            "symbol": symbol,
            "date": pd.to_datetime(hist["Date"]).dt.date,
            "open": pd.to_numeric(hist["Open"], errors="coerce"),
            "high": pd.to_numeric(hist["High"], errors="coerce"),
            "low": pd.to_numeric(hist["Low"], errors="coerce"),
            "close": pd.to_numeric(hist["Close"], errors="coerce"),
            "volume": pd.to_numeric(hist["Volume"], errors="coerce").fillna(0).astype("int64"),
        }
    )
    out = out.dropna(subset=["close"])
    out = out[out["close"] > 0].reset_index(drop=True)
    return out


def backfill_symbols(repo, symbols: list[str], years: int | None = None) -> int:
    """Backfill many symbols into ``prices_raw``. Returns rows written."""
    cfg = get_config()
    years = years or cfg.ingestion.backfill_years
    start = date.today() - timedelta(days=int(years * 365.25))
    written = 0
    for i, sym in enumerate(symbols, 1):
        df = backfill_symbol(sym, start)
        if not df.empty:
            written += repo.upsert_df("prices_raw", df)
        if i % 50 == 0:
            log.info("backfill_progress", done=i, total=len(symbols), rows=written)
    log.info("backfill_complete", symbols=len(symbols), rows=written)
    return written


def backfill_symbols_bulk(
    repo, symbols: list[str], years: int | None = None, chunk_size: int = 40
) -> int:
    """Bulk backfill via multi-ticker yf.download (much faster than one-by-one).

    Downloads ``chunk_size`` tickers per request with threads; symbols Yahoo
    doesn't know (renamed/suspended) are skipped silently. Upserts per symbol so
    a crash mid-run loses nothing already written.
    """
    import time as _time

    cfg = get_config()
    yf = _yf()
    years = years or cfg.ingestion.backfill_years
    start = date.today() - timedelta(days=int(years * 365.25))
    end = date.today() + timedelta(days=1)
    suffix = cfg.ingestion.yfinance_suffix_nse

    written = 0
    ok_symbols = 0
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i : i + chunk_size]
        tickers = [f"{s}{suffix}" for s in chunk]
        try:
            data = yf.download(
                tickers, start=start.isoformat(), end=end.isoformat(), interval="1d",
                auto_adjust=False, progress=False, threads=True, group_by="ticker",
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("bulk_chunk_failed", at=i, error=str(exc))
            _time.sleep(2)
            continue
        if data is None or data.empty:
            continue

        multi = isinstance(data.columns, pd.MultiIndex)
        for sym, tk in zip(chunk, tickers):
            try:
                sub = data[tk] if multi else data
            except KeyError:
                continue
            if sub is None or sub.empty or "Close" not in sub.columns:
                continue
            sub = sub.dropna(subset=["Close"]).reset_index()
            if sub.empty:
                continue
            out = pd.DataFrame(
                {
                    "symbol": sym,
                    "date": pd.to_datetime(sub["Date"]).dt.date,
                    "open": pd.to_numeric(sub["Open"], errors="coerce"),
                    "high": pd.to_numeric(sub["High"], errors="coerce"),
                    "low": pd.to_numeric(sub["Low"], errors="coerce"),
                    "close": pd.to_numeric(sub["Close"], errors="coerce"),
                    "volume": pd.to_numeric(sub["Volume"], errors="coerce")
                    .fillna(0).astype("int64"),
                }
            ).dropna(subset=["close"])
            out = out[out["close"] > 0]
            if out.empty:
                continue
            written += repo.upsert_df("prices_raw", out)
            ok_symbols += 1

        log.info("bulk_progress", done=min(i + chunk_size, len(symbols)),
                 total=len(symbols), ok=ok_symbols, rows=written)
        _time.sleep(1)  # be polite between chunks

    log.info("bulk_backfill_complete", symbols=len(symbols), ok=ok_symbols, rows=written)
    return written
