"""Tests for the two-way Telegram bot: command parsing + dispatch (no network)."""

from datetime import date, timedelta

import pandas as pd
import pytest

from analyzer.db.repository import Repository
from analyzer.notify.telegram_bot import handle_command, parse_command
from analyzer.risk.positions import list_positions


# --- parser ---------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("buy CGPOWER 100 902", {"action": "buy", "symbol": "CGPOWER", "qty": 100,
                             "price": 902.0, "sl": None}),
    ("bought cgpower 100 @ 902", {"action": "buy", "symbol": "CGPOWER", "qty": 100,
                                  "price": 902.0, "sl": None}),
    ("buy CGPOWER 100 902 sl 880", {"action": "buy", "symbol": "CGPOWER", "qty": 100,
                                    "price": 902.0, "sl": 880.0}),
    ("took RELIANCE 50 at 2980", {"action": "buy", "symbol": "RELIANCE", "qty": 50,
                                  "price": 2980.0, "sl": None}),
    ("sell CGPOWER", {"action": "sell", "symbol": "CGPOWER", "qty": None, "price": None}),
    ("sold cgpower 950", {"action": "sell", "symbol": "CGPOWER", "qty": None, "price": 950.0}),
    ("sell cgpower 40 950", {"action": "sell", "symbol": "CGPOWER", "qty": 40,
                             "price": 950.0}),
    ("sl CGPOWER 910", {"action": "set_sl", "symbol": "CGPOWER", "sl": 910.0}),
    ("list", {"action": "list"}),
    ("/help", {"action": "help"}),
])
def test_parse_command(text, expected):
    assert parse_command(text) == expected


def test_parse_errors():
    assert parse_command("buy CGPOWER")["action"] == "error"
    assert parse_command("sell")["action"] == "error"
    assert parse_command("buy X two 902")["action"] == "error"   # bad number
    assert parse_command("")["action"] == "none"
    assert parse_command("what's up")["action"] == "unknown"


# --- dispatch -------------------------------------------------------------

def _repo_with_signal(symbol="CGPOWER"):
    repo = Repository.open(":memory:")
    today = date.today()
    repo.upsert_df("signals", pd.DataFrame([{
        "signal_id": f"{today}-{symbol}-A", "date": today, "symbol": symbol,
        "setup": "A_momentum_breakout", "direction": "LONG", "grade": "A",
        "composite_score": 85.0, "entry_aggressive": 905.0, "entry_conservative": 900.0,
        "entry_valid_till": today + timedelta(days=5), "stop_loss": 878.0,
        "t1": 945.0, "t2": 985.0, "rr": 3.0, "suggested_risk_pct": 1.0,
    }]))
    return repo


def test_handle_buy_from_signal():
    repo = _repo_with_signal()
    reply = handle_command(repo, "buy CGPOWER 100 902")
    assert "Logged BUY" in reply and "from signal" in reply
    assert "878" in reply                       # inherited stop echoed back
    assert len(list_positions(repo)) == 1
    repo.close()


def test_handle_buy_discretionary_needs_stop():
    repo = Repository.open(":memory:")
    reply = handle_command(repo, "buy NOSIG 10 100")
    assert "no system signal" in reply.lower()  # friendly error, not a crash
    assert list_positions(repo).empty
    repo.close()


def test_handle_buy_discretionary_with_stop():
    repo = Repository.open(":memory:")
    reply = handle_command(repo, "buy NOSIG 10 100 sl 95")
    assert "Logged BUY" in reply
    repo.close()


def test_handle_sell_and_list():
    repo = _repo_with_signal()
    handle_command(repo, "buy CGPOWER 100 902")
    assert "CGPOWER" in handle_command(repo, "list")
    reply = handle_command(repo, "sell CGPOWER 950")
    assert "Closed" in reply
    assert handle_command(repo, "list") == "No open positions."
    repo.close()


def test_handle_partial_sell_from_chat():
    repo = _repo_with_signal()
    handle_command(repo, "buy CGPOWER 100 902")
    reply = handle_command(repo, "sell CGPOWER 40 950")   # partial
    assert "Sold 40" in reply and "60 still held" in reply
    assert "still on it" in reply.lower()
    # Remaining 60 must still show in holdings.
    assert "60" in handle_command(repo, "list")
    repo.close()


def test_handle_set_sl_refuses_widen():
    repo = _repo_with_signal()
    handle_command(repo, "buy CGPOWER 100 902")   # stop 878 from signal
    ok = handle_command(repo, "sl CGPOWER 890")
    assert "moved to 890" in ok
    widen = handle_command(repo, "sl CGPOWER 800")
    assert "WIDEN" in widen or "widen" in widen   # refused, surfaced to chat
    repo.close()
