"""Ingestion jobs (Phase 1). Daily EOD bhavcopy + historical backfill.

Later phases append indicator/regime/signal steps to the daily orchestrator; this
module owns the data-ingestion half only.
"""

from __future__ import annotations

from datetime import date

from analyzer.config import Config, get_config
from analyzer.data.adjust import rebuild_adjusted
from analyzer.data.bhavcopy import fetch_bhavcopy
from analyzer.data.calendar import TradingCalendar, seed_holidays
from analyzer.data.nse_client import NseClient
from analyzer.data.symbols import sync_symbols
from analyzer.data.validation import validate_prices
from analyzer.db.repository import Repository
from analyzer.logging_setup import get_logger

log = get_logger(__name__)


def open_repo(cfg: Config | None = None) -> Repository:
    """Open the DB (creating/applying schema) and ensure the holiday seed is loaded."""
    cfg = cfg or get_config()
    repo = Repository.open(cfg.db_path)
    if repo.count("holidays_nse") == 0:
        seed_holidays(repo)
    return repo


def run_daily_ingest(
    repo: Repository,
    target_date: date | None = None,
    client: NseClient | None = None,
    cfg: Config | None = None,
) -> dict:
    """Ingest one trading day's bhavcopy into prices_raw and refresh prices_adj.

    Idempotent: re-running the same date upserts the same rows. Skips non-trading
    days. Returns a small summary dict.
    """
    cfg = cfg or get_config()
    client = client or NseClient(cfg)
    target_date = target_date or date.today()

    calendar = TradingCalendar.from_repo(repo)
    if not calendar.is_trading_day(target_date):
        log.info("skip_non_trading_day", date=str(target_date))
        return {"date": str(target_date), "skipped": "non_trading_day", "rows": 0}

    with repo.job_run(f"daily_ingest:{target_date}") as jr:
        df = fetch_bhavcopy(client, target_date)
        if df.empty:
            log.warning("no_bhavcopy_data", date=str(target_date))
            return {"date": str(target_date), "rows": 0, "note": "no data (holiday/not published)"}

        report = validate_prices(df)
        if not report.ohlc_violations.empty:
            log.warning("ohlc_violations", n=len(report.ohlc_violations), date=str(target_date))

        rows = repo.upsert_df("prices_raw", df)
        jr.add_rows(rows)

        # Refresh adjusted prices for the symbols we just touched.
        rebuild_adjusted(repo, symbols=df["symbol"].unique().tolist())

    return {"date": str(target_date), "rows": rows, "validation": report.summary()}


def run_symbol_sync(repo: Repository, cfg: Config | None = None) -> int:
    cfg = cfg or get_config()
    with repo.job_run("symbol_sync") as jr:
        n = sync_symbols(repo, NseClient(cfg))
        jr.add_rows(n)
    return n


def run_backfill(
    repo: Repository, symbols: list[str] | None = None, years: int | None = None,
    cfg: Config | None = None, bulk: bool = False,
) -> int:
    """Backfill historical prices via yfinance for the given symbols (or all in
    the symbol master), then rebuild adjusted prices."""
    from analyzer.data.yfinance_backfill import backfill_symbols, backfill_symbols_bulk

    cfg = cfg or get_config()
    if symbols is None:
        rows = repo.query_df("SELECT symbol FROM symbols WHERE is_active ORDER BY symbol")
        symbols = rows["symbol"].tolist()
    with repo.job_run("backfill") as jr:
        if bulk:
            n = backfill_symbols_bulk(repo, symbols, years=years)
        else:
            n = backfill_symbols(repo, symbols, years=years)
        jr.add_rows(n)
        rebuild_adjusted(repo, symbols=symbols)
    return n
