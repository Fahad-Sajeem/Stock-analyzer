"""Two-way Telegram bot — log trades by texting the bot (PLAN §14 wishlist).

Long-polls getUpdates (no public webhook needed — works behind SSH-only cloud
firewalls) and dispatches chat commands to the position ledger. SECURITY: only
messages from ANALYZER_TG_CHAT_ID are honored; everything else is ignored, so
a stranger who finds the bot cannot touch your positions.

Commands (case-insensitive, '@'/','/'at' tolerated):
    buy  CGPOWER 100 902           log a buy (stop from signal if one exists)
    buy  CGPOWER 100 902 sl 880    log a buy with an explicit stop
    sell CGPOWER                   close a position (optionally: sell CGPOWER 950)
    sl   CGPOWER 910               tighten a stop
    list                           show holdings with live P&L
    help

Run:  analyzer bot        (one instance only; runs until Ctrl-C / service stop)
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import requests

from analyzer.config import Config, get_config
from analyzer.logging_setup import get_logger
from analyzer.risk.positions import add_position, list_positions, sell_position, set_stop

log = get_logger(__name__)

# Registered with Telegram's native "/" command menu (set_bot_commands) so they
# show up in the client's autocomplete + menu button — the discoverable path,
# not just "you have to already know to type help". Telegram command names must
# be lowercase \w{1,32}; keep in sync with parse_command's verb handling below.
_COMMAND_MENU = [
    ("help", "Show all commands and how to use them"),
    ("list", "Show your holdings with live P&L"),
    ("buy", "Log a buy — e.g. /buy CGPOWER 100 902"),
    ("sell", "Sell all or part — e.g. /sell CGPOWER 40 950"),
    ("sl", "Tighten a stop — e.g. /sl CGPOWER 910"),
]

_HELP = (
    "*Stock Analyzer bot — commands*\n\n"
    "*/buy* SYMBOL QTY PRICE [sl STOP]\n"
    "  Log a buy. If a system signal exists for the symbol, the stop is taken "
    "from it automatically — leave [sl STOP] out.\n"
    "  e.g. `/buy CGPOWER 100 902`\n"
    "  Discretionary buy (no signal) — stop is required:\n"
    "  e.g. `/buy CGPOWER 100 900 sl 880`\n\n"
    "*/sell* SYMBOL [PRICE]  — sell the WHOLE position\n"
    "  e.g. `/sell CGPOWER 950`  or just `/sell CGPOWER` (market)\n"
    "*/sell* SYMBOL QTY PRICE  — sell PART, rest stays tracked\n"
    "  e.g. `/sell CGPOWER 40 950`  (books 40, keeps watching the remainder)\n\n"
    "*/sl* SYMBOL PRICE  — tighten a stop (never widens)\n"
    "  e.g. `/sl CGPOWER 910`\n\n"
    "*/list*  — holdings with live entry/stop/P&L\n\n"
    "*/help*  — this message\n\n"
    "Only messages from your registered chat are ever acted on."
)


# --- pure command parser (unit-testable, no I/O) --------------------------

def parse_command(text: str) -> dict:
    if not text or not text.strip():
        return {"action": "none"}
    parts = text.strip().lower().replace(",", " ").replace("@", " ").split()
    parts = [p for p in parts if p != "at"]
    verb = parts[0].lstrip("/")

    try:
        if verb in ("help", "?", "start"):
            return {"action": "help"}
        if verb in ("list", "positions", "ls", "holdings", "status"):
            return {"action": "list"}
        if verb in ("buy", "bought", "b", "took"):
            args = parts[1:]
            sl = None
            if "sl" in args:
                i = args.index("sl")
                if i + 1 < len(args):
                    sl = float(args[i + 1])
                args = args[:i] + args[i + 2:]
            if len(args) < 3:
                return {"action": "error", "msg": "buy needs: SYMBOL QTY PRICE [sl STOP]"}
            return {"action": "buy", "symbol": args[0].upper(),
                    "qty": int(args[1]), "price": float(args[2]), "sl": sl}
        if verb in ("sell", "sold", "close", "exit"):
            args = parts[1:]
            if not args:
                return {"action": "error",
                        "msg": "sell needs: SYMBOL [PRICE]  (partial: SYMBOL QTY PRICE)"}
            symbol = args[0].upper()
            nums = args[1:]
            # Two numbers -> QTY then PRICE (partial). One -> PRICE (full). None -> market.
            if len(nums) >= 2:
                return {"action": "sell", "symbol": symbol,
                        "qty": int(nums[0]), "price": float(nums[1])}
            if len(nums) == 1:
                return {"action": "sell", "symbol": symbol, "qty": None,
                        "price": float(nums[0])}
            return {"action": "sell", "symbol": symbol, "qty": None, "price": None}
        if verb in ("sl", "stop"):
            args = parts[1:]
            if len(args) < 2:
                return {"action": "error", "msg": "sl needs: SYMBOL PRICE"}
            return {"action": "set_sl", "symbol": args[0].upper(), "sl": float(args[1])}
    except ValueError:
        return {"action": "error", "msg": "couldn't read the numbers — check the format"}
    return {"action": "unknown"}


# --- dispatch to the ledger (repo I/O, no network) ------------------------

def handle_command(repo, text: str) -> str:
    cmd = parse_command(text)
    action = cmd["action"]
    if action == "none":
        return ""
    if action == "help":
        return _HELP
    if action in ("error", "unknown"):
        return cmd.get("msg", "didn't understand that.\n\n" + _HELP)

    try:
        if action == "buy":
            add_position(repo, cmd["symbol"], cmd["qty"], cmd["price"], cmd["sl"])
            pos = repo.query_df(
                "SELECT current_sl, signal_id, notes FROM positions "
                "WHERE symbol = ? AND status IN ('OPEN','PARTIAL') ORDER BY entry_date DESC LIMIT 1",
                [cmd["symbol"]],
            ).iloc[0]
            linked = " (from signal)" if pos["signal_id"] else ""
            warn = " ⚠ CHASED >2%" if "CHASED" in str(pos["notes"]) else ""
            return (f"✅ Logged BUY {cmd['symbol']} {cmd['qty']} @ {cmd['price']:.2f}, "
                    f"stop {pos['current_sl']:.2f}{linked}{warn}. Watcher is on it.")
        if action == "sell":
            res = sell_position(repo, cmd["symbol"], qty=cmd.get("qty"),
                                price=cmd.get("price"))
            if res["closed"]:
                return f"✅ Closed {cmd['symbol']} fully ({res['sold']} shares)."
            stop = repo.scalar(
                "SELECT current_sl FROM positions WHERE symbol = ? "
                "AND status IN ('OPEN','PARTIAL') ORDER BY entry_date LIMIT 1", [cmd["symbol"]],
            )
            return (f"✅ Sold {res['sold']} {cmd['symbol']}; {res['remaining']} still held "
                    f"(stop {stop:.1f}) — watcher still on it.")
        if action == "set_sl":
            set_stop(repo, cmd["symbol"], cmd["sl"])
            return f"✅ Stop on {cmd['symbol']} moved to {cmd['sl']:.2f}."
        if action == "list":
            df = list_positions(repo)
            if df.empty:
                return "No open positions."
            lines = ["*Holdings:*"]
            for _, r in df.iterrows():
                pnl = r.get("pnl")
                pnl_s = f"{pnl:+.0f} ({r.get('pnl_pct'):+.1f}%)" if pnl is not None else ""
                lines.append(f"• {r['symbol']} {r['qty']} @ {r['entry_price']:.1f} "
                             f"| stop {r['current_sl']:.1f} | {pnl_s}")
            return "\n".join(lines)
    except ValueError as exc:
        return f"⚠ {exc}"
    except Exception as exc:  # noqa: BLE001 - never crash the poll loop on one msg
        log.warning("bot_command_failed", text=text, error=str(exc))
        return f"error: {exc}"
    return ""


def set_bot_commands(token: str) -> bool:
    """Register the "/" command menu with Telegram (setMyCommands) so commands
    are discoverable in the client UI, not just something you have to know to
    type. Safe to call every time the bot starts — Telegram just overwrites."""
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/setMyCommands",
            json={"commands": [{"command": c, "description": d} for c, d in _COMMAND_MENU]},
            timeout=20,
        )
        ok = resp.status_code == 200
        if not ok:
            log.warning("bot_setmycommands_failed", status=resp.status_code, body=resp.text[:200])
        return ok
    except requests.RequestException as exc:
        log.warning("bot_setmycommands_error", error=str(exc))
        return False


# --- polling loop ---------------------------------------------------------

def _offset_path(cfg: Config) -> Path:
    return cfg.path("data") / ".tg_offset"


def run_bot(repo, cfg: Config | None = None, poll_timeout: int = 30,
            once: bool = False) -> None:
    cfg = cfg or get_config()
    token = os.environ.get("ANALYZER_TG_BOT_TOKEN")
    chat_id = os.environ.get("ANALYZER_TG_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError(
            "set ANALYZER_TG_BOT_TOKEN and ANALYZER_TG_CHAT_ID to run the bot"
        )
    base = f"https://api.telegram.org/bot{token}"
    off_file = _offset_path(cfg)
    offset = int(off_file.read_text()) if off_file.exists() else 0
    set_bot_commands(token)  # register the "/" menu; harmless if it fails

    def reply(text: str) -> None:
        if not text:
            return
        try:
            requests.post(f"{base}/sendMessage",
                          json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
                          timeout=20)
        except requests.RequestException as exc:
            log.warning("bot_reply_failed", error=str(exc))

    log.info("bot_started", chat_id=chat_id)
    while True:
        try:
            resp = requests.get(f"{base}/getUpdates",
                                params={"offset": offset, "timeout": poll_timeout},
                                timeout=poll_timeout + 10)
            updates = resp.json().get("result", []) if resp.status_code == 200 else []
        except requests.RequestException as exc:
            log.warning("bot_poll_error", error=str(exc))
            time.sleep(5)
            if once:
                return
            continue

        for u in updates:
            offset = u["update_id"] + 1
            msg = u.get("message") or u.get("edited_message") or {}
            sender = str(msg.get("chat", {}).get("id", ""))
            if sender != str(chat_id):
                log.warning("bot_ignored_foreign_chat", sender=sender)  # SECURITY gate
                continue
            text = msg.get("text", "")
            out = handle_command(repo, text)
            log.info("bot_command", text=text[:60], replied=bool(out))
            reply(out)

        off_file.write_text(str(offset))
        if once:
            return
