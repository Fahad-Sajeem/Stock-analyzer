"""The daily EOD pipeline (PLAN Section 15, 19:00 IST on trading days).

ingest bhavcopy -> indices/indicators/regime -> (weekly) universe refresh ->
publish signals -> update signal outcomes -> render charts -> daily report ->
Telegram digest.

Designed to be idempotent and safely re-runnable; schedule via Windows Task
Scheduler or cron calling ``analyzer daily``.
"""

from __future__ import annotations

from datetime import date

from analyzer.charts.plotly_chart import render_charts_for_date
from analyzer.config import Config, get_config
from analyzer.data.calendar import TradingCalendar
from analyzer.jobs.ingest import run_daily_ingest
from analyzer.jobs.signals import run_signals
from analyzer.jobs.technicals import run_technicals
from analyzer.jobs.universe import run_universe
from analyzer.logging_setup import get_logger
from analyzer.notify.report import write_daily_report
from analyzer.notify.telegram import send_telegram, telegram_digest
from analyzer.risk.tracker import update_signal_outcomes

log = get_logger(__name__)

_UNIVERSE_MAX_AGE_DAYS = 7


def run_daily(repo, cfg: Config | None = None, target_date: date | None = None) -> dict:
    cfg = cfg or get_config()
    target_date = target_date or date.today()
    summary: dict = {"date": str(target_date)}

    calendar = TradingCalendar.from_repo(repo)
    if not calendar.is_trading_day(target_date):
        # Still update outcomes/report on holidays? Keep it simple: skip fully.
        log.info("daily_skip_non_trading", date=str(target_date))
        summary["skipped"] = "non-trading day"
        return summary

    # 1. EOD prices.
    summary["ingest"] = run_daily_ingest(repo, target_date=target_date, cfg=cfg)

    # 2. Indices + indicators + regime (incremental: only new dates recomputed —
    #    keeps peak RAM ~10x lower so the pipeline fits small cloud instances).
    summary["technicals"] = run_technicals(repo, cfg, refresh_indices=True,
                                           incremental=True)

    # 3. Weekly universe refresh (slow: fundamentals fetch) when stale.
    latest_universe = repo.scalar("SELECT MAX(as_of) FROM universe")
    stale = (
        latest_universe is None
        or (target_date - latest_universe.date()
            if hasattr(latest_universe, "date") else target_date - latest_universe).days
        > _UNIVERSE_MAX_AGE_DAYS
    )
    if stale:
        log.info("universe_refresh_start", note="stale/missing; this takes a while")
        df = run_universe(repo, cfg)
        summary["universe"] = {"evaluated": len(df), "approved": int(df["approved"].sum())}
    else:
        summary["universe"] = "fresh"

    # 4. Signals (observational feed).
    sigs = run_signals(repo, cfg, as_of=target_date)
    summary["signals"] = 0 if sigs is None or sigs.empty else len(sigs)

    # 5. Track outcomes of all recent signals (the observational dataset).
    summary["tracker"] = update_signal_outcomes(repo, cfg)

    # 6. Charts for today's signals.
    summary["charts"] = render_charts_for_date(repo, target_date, cfg)

    # 7. Report + Telegram digest.
    report_path = write_daily_report(repo, target_date, cfg)
    summary["report"] = report_path
    content = open(report_path, encoding="utf-8").read()
    summary["telegram"] = send_telegram(telegram_digest(content), cfg)

    log.info("daily_done", **{k: str(v)[:80] for k, v in summary.items()})
    return summary
