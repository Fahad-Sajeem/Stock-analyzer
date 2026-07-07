"""Intraday position watcher — the CG Power safety net.

Runs every ~15 minutes during market hours (scheduled task), checks live quotes
for every OPEN position, and sends a Telegram alert on:
  * STOP_BREACH — price at/below your stop, and
  * SHARP_DROP  — price down more than ``notify.watch_drop_pct`` (default 3%)
    vs the previous close (news-shock detector: catches the CG Power case even
    when the stop hasn't been hit yet).

Each (position, alert-type) fires at most once per day (alerts_log dedupe).

Honesty note: quotes come from yfinance and may be delayed ~15 minutes, and the
task interval adds up to 15 more — total alert latency is minutes-to-half-hour.
That converts "found out after close" into "knew within ~20 minutes", which is
what's realistically achievable without a paid real-time feed.

CLI:  analyzer watch [--force]
"""

from __future__ import annotations

from datetime import date, datetime, time

import pandas as pd

from analyzer.config import Config, get_config
from analyzer.data.calendar import TradingCalendar
from analyzer.logging_setup import get_logger
from analyzer.notify.telegram import send_telegram

log = get_logger(__name__)

_MARKET_OPEN = time(9, 15)
_MARKET_CLOSE = time(15, 35)   # small buffer past 15:30


def in_market_hours(now: datetime, calendar: TradingCalendar) -> bool:
    if not calendar.is_trading_day(now.date()):
        return False
    return _MARKET_OPEN <= now.time() <= _MARKET_CLOSE


def _live_quote(symbol: str, suffix: str) -> float | None:
    """Latest traded price via yfinance (may be ~15 min delayed for NSE)."""
    try:
        import yfinance as yf

        info = yf.Ticker(f"{symbol}{suffix}").fast_info
        price = info.get("last_price") or info.get("lastPrice")
        return float(price) if price else None
    except Exception as exc:  # noqa: BLE001
        log.warning("quote_failed", symbol=symbol, error=str(exc))
        return None


def _already_alerted(repo, d: date, symbol: str, alert_type: str) -> bool:
    return bool(repo.scalar(
        "SELECT COUNT(*) FROM alerts_log WHERE alert_date = ? AND symbol = ? AND alert_type = ?",
        [d, symbol, alert_type],
    ))


def _record_alert(repo, d: date, symbol: str, alert_type: str, detail: str) -> None:
    repo.upsert_df("alerts_log", pd.DataFrame([{
        "alert_date": d, "symbol": symbol, "alert_type": alert_type,
        "detail": detail[:300], "sent_at": datetime.now(),
    }]))


def run_watch(repo, cfg: Config | None = None, force: bool = False,
              now: datetime | None = None) -> dict:
    """One watch pass. Designed to be scheduled every 15 min and exit instantly
    outside market hours (``force=True`` overrides for manual testing)."""
    cfg = cfg or get_config()
    now = now or datetime.now()
    calendar = TradingCalendar.from_repo(repo)

    if not force and not in_market_hours(now, calendar):
        return {"skipped": "outside market hours", "alerts": 0}

    positions = repo.query_df(
        "SELECT symbol, qty, entry_price, current_sl FROM positions "
        "WHERE status IN ('OPEN','PARTIAL')"
    )
    if positions.empty:
        return {"skipped": "no open positions", "alerts": 0}

    drop_pct = float(cfg.notify.get("watch_drop_pct", 3.0))
    suffix = cfg.ingestion.yfinance_suffix_nse
    today = now.date()
    alerts: list[str] = []

    for _, p in positions.iterrows():
        symbol = p["symbol"]
        price = _live_quote(symbol, suffix)
        if price is None:
            continue
        prev_close = repo.scalar(
            "SELECT close FROM prices_raw WHERE symbol = ? AND date < ? "
            "ORDER BY date DESC LIMIT 1", [symbol, today],
        )

        # STOP_BREACH — price at/below your stop.
        if price <= float(p["current_sl"]) and not _already_alerted(
            repo, today, symbol, "STOP_BREACH"
        ):
            msg = (f"🔴 {symbol}: {price:.1f} at/below your stop {p['current_sl']:.1f} "
                   f"(entry {p['entry_price']:.1f}) — plan says EXIT")
            alerts.append(msg)
            _record_alert(repo, today, symbol, "STOP_BREACH", msg)

        # SHARP_DROP — news-shock detector, even before the stop.
        if prev_close and prev_close > 0:
            chg = (price / float(prev_close) - 1) * 100
            if chg <= -drop_pct and not _already_alerted(
                repo, today, symbol, "SHARP_DROP"
            ):
                msg = (f"⚠️ {symbol}: {chg:+.1f}% today ({price:.1f} vs close "
                       f"{float(prev_close):.1f}) — check for news; your stop is "
                       f"{p['current_sl']:.1f}")
                alerts.append(msg)
                _record_alert(repo, today, symbol, "SHARP_DROP", msg)

    if alerts:
        text = f"*Intraday alert {now:%H:%M}*\n" + "\n".join(alerts)
        sent = send_telegram(text, cfg)
        for a in alerts:
            log.info("intraday_alert", alert=a, telegram=sent)
    return {"checked": len(positions), "alerts": len(alerts),
            "messages": alerts}
