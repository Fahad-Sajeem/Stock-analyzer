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
    """Compact digest from the daily report: title, regime, position actions
    (the CG Power-style 'EXIT' lines must reach the phone), and signal rows."""
    lines = report_md.splitlines()
    keep: list[str] = []
    in_actions = False
    for ln in lines:
        if ln.startswith("# ") or ln.startswith("**Regime"):
            keep.append(ln.replace("# ", ""))
        elif ln.startswith("## Open-position actions"):
            in_actions = True
            keep.append("Position actions:")
        elif in_actions:
            if ln.startswith("## "):
                in_actions = False
            elif ln.startswith("- "):
                keep.append(ln)
            elif ln.startswith("_None"):
                keep.append("(no actions)")
                in_actions = False
        elif ln.startswith("| ") and len(keep) < 30:
            keep.append(ln)
        elif ln.startswith("_No new signals"):
            keep.append(ln.strip("_"))
    return "\n".join(keep[:45])
