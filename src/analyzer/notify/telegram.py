"""Telegram push (PLAN 6.4). Plain HTTPS via requests — no extra dependency.

Enable in config (notify.telegram_enabled: true) and provide credentials via
environment variables ANALYZER_TG_BOT_TOKEN and ANALYZER_TG_CHAT_ID.
No-ops (with a log line) when disabled or unconfigured — the pipeline must
never fail because notifications aren't set up.
"""

from __future__ import annotations

import os

import requests

from analyzer.config import Config, get_config
from analyzer.logging_setup import get_logger

log = get_logger(__name__)

_MAX_LEN = 4000  # Telegram hard limit is 4096


def send_telegram(text: str, cfg: Config | None = None) -> bool:
    cfg = cfg or get_config()
    if not cfg.notify.get("telegram_enabled", False):
        log.debug("telegram_disabled")
        return False
    token = os.environ.get("ANALYZER_TG_BOT_TOKEN")
    chat_id = os.environ.get("ANALYZER_TG_CHAT_ID")
    if not token or not chat_id:
        log.warning("telegram_unconfigured",
                    hint="set ANALYZER_TG_BOT_TOKEN and ANALYZER_TG_CHAT_ID")
        return False
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:_MAX_LEN],
                  "parse_mode": "Markdown", "disable_web_page_preview": True},
            timeout=20,
        )
        ok = resp.status_code == 200
        if not ok:
            log.warning("telegram_send_failed", status=resp.status_code, body=resp.text[:200])
        return ok
    except requests.RequestException as exc:
        log.warning("telegram_error", error=str(exc))
        return False


def telegram_digest(report_md: str) -> str:
    """Compact digest from the daily report. Section-aware so it reliably carries
    the parts that matter to the phone: title, regime, YOUR holdings + total P&L,
    open-position actions (the CG Power-style 'EXIT' lines), and new-signal rows."""
    lines = report_md.splitlines()
    keep: list[str] = []
    section = None  # 'holdings' | 'actions' | 'signals' | None
    for ln in lines:
        if ln.startswith("# ") or ln.startswith("**Regime"):
            keep.append(ln.replace("# ", ""))
            continue
        if ln.startswith("## Your holdings"):
            section = "holdings"
            keep.append("*Holdings:*")
            continue
        if ln.startswith("## Open-position actions"):
            section = "actions"
            keep.append("*Actions:*")
            continue
        if ln.startswith("## New signals"):
            section = "signals"
            continue
        if ln.startswith("## "):  # any other section ends capture
            section = None
            continue

        if section == "holdings":
            if ln.startswith("| ") and "Symbol" not in ln and "---" not in ln:
                keep.append(ln)              # a holding row
            elif ln.startswith("**Total"):
                keep.append(ln)              # the total P&L line
            elif ln.startswith("_No open holdings"):
                keep.append("(no open holdings)")
        elif section == "actions":
            if ln.startswith("- "):
                keep.append(ln)
            elif ln.startswith("_None"):
                keep.append("(no actions today)")
        elif section == "signals":
            if ln.startswith("- ") or (ln.startswith("| ") and "Symbol" not in ln
                                       and "---" not in ln):
                keep.append(ln)
            elif ln.startswith("_No new signals"):
                keep.append("(no new signals)")
    return "\n".join(keep[:50])
