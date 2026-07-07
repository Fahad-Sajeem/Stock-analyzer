"""Tests for the position ledger, intraday watch mechanics, and digest fix."""

from datetime import date, datetime

import pandas as pd
import pytest

from analyzer.data.calendar import TradingCalendar
from analyzer.db.repository import Repository
from analyzer.notify.telegram import telegram_digest
from analyzer.risk.intraday_watch import in_market_hours
from analyzer.risk.positions import (
    add_position,
    close_position,
    list_positions,
    sell_position,
    set_stop,
)


def _repo():
    return Repository.open(":memory:")


def test_add_and_list_position():
    repo = _repo()
    add_position(repo, "cgpower", 100, 900.0, 880.0)
    df = list_positions(repo)
    assert len(df) == 1
    row = df.iloc[0]
    assert row["symbol"] == "CGPOWER"       # normalized to upper
    assert row["qty"] == 100
    assert row["current_sl"] == 880.0
    repo.close()


def test_add_rejects_stop_above_entry():
    repo = _repo()
    with pytest.raises(ValueError, match="BELOW entry"):
        add_position(repo, "X", 10, 100.0, 105.0)
    repo.close()


def test_set_stop_tighten_only():
    repo = _repo()
    add_position(repo, "X", 10, 100.0, 90.0)
    set_stop(repo, "X", 95.0)               # tighten OK
    assert list_positions(repo).iloc[0]["current_sl"] == 95.0
    with pytest.raises(ValueError, match="WIDEN"):
        set_stop(repo, "X", 85.0)           # widen refused
    repo.close()


def test_close_position():
    repo = _repo()
    add_position(repo, "X", 10, 100.0, 90.0)
    n = close_position(repo, "X", price=97.0)
    assert n == 1
    assert list_positions(repo).empty
    assert len(list_positions(repo, include_closed=True)) == 1
    repo.close()


def _seed_signal(repo, symbol="CGPOWER", days_valid=5):
    from datetime import timedelta
    today = date.today()
    repo.upsert_df("signals", pd.DataFrame([{
        "signal_id": f"{today}-{symbol}-A", "date": today, "symbol": symbol,
        "setup": "A_momentum_breakout", "direction": "LONG", "grade": "A",
        "composite_score": 85.0, "entry_aggressive": 905.0, "entry_conservative": 900.0,
        "entry_valid_till": today + timedelta(days=days_valid), "stop_loss": 878.0,
        "t1": 945.0, "t2": 985.0, "rr": 3.0, "suggested_risk_pct": 1.0,
    }]))


def test_add_position_from_signal_inherits_stop():
    repo = _repo()
    _seed_signal(repo)
    add_position(repo, "CGPOWER", 100, 902.0)      # no --sl: pull from signal
    row = list_positions(repo).iloc[0]
    assert row["current_sl"] == 878.0               # signal's structural stop
    pos = repo.query_df("SELECT signal_id, notes FROM positions").iloc[0]
    assert pos["signal_id"] is not None             # linked -> T1 actions work
    # Slippage recorded vs the signal's entry reference (905 -> 902 = -33 bps).
    fill = repo.query_df("SELECT * FROM fills").iloc[0]
    assert abs(fill["slippage_bps"] - (902 - 905) / 905 * 1e4) < 0.2
    repo.close()


def test_add_position_without_signal_requires_sl():
    repo = _repo()
    with pytest.raises(ValueError, match="no system signal"):
        add_position(repo, "NOSIGNAL", 10, 100.0)   # discretionary, no --sl
    repo.close()


def test_add_position_expired_signal_rejected():
    repo = _repo()
    _seed_signal(repo, days_valid=-2)               # signal window already over
    with pytest.raises(ValueError, match="expired"):
        add_position(repo, "CGPOWER", 100, 902.0)
    repo.close()


def test_partial_sell_reduces_qty_keeps_open():
    repo = _repo()
    add_position(repo, "CGPOWER", 100, 900.0, 880.0)
    res = sell_position(repo, "CGPOWER", qty=40, price=950.0)
    assert res == {"closed": False, "sold": 40, "remaining": 60}
    df = list_positions(repo)                       # still tracked
    assert len(df) == 1
    row = df.iloc[0]
    assert row["qty"] == 60
    assert row["status"] == "PARTIAL"
    # A sell fill was recorded for the 40 booked.
    fills = repo.query_df("SELECT * FROM fills WHERE side = 'SELL'")
    assert len(fills) == 1 and fills.iloc[0]["actual_price"] == 950.0
    repo.close()


def test_partial_then_full_sell():
    repo = _repo()
    add_position(repo, "CGPOWER", 100, 900.0, 880.0)
    sell_position(repo, "CGPOWER", qty=40, price=950.0)
    res = sell_position(repo, "CGPOWER", price=970.0)   # sell the remaining 60
    assert res["closed"] and res["sold"] == 60
    assert list_positions(repo).empty
    repo.close()


def test_sell_full_when_qty_exceeds_holding():
    repo = _repo()
    add_position(repo, "X", 50, 100.0, 95.0)
    res = sell_position(repo, "X", qty=80, price=110.0)  # asked more than held
    assert res["closed"] and res["sold"] == 50
    repo.close()


def test_close_position_still_full_exit():
    repo = _repo()
    add_position(repo, "X", 50, 100.0, 95.0)
    assert close_position(repo, "X", price=110.0) == 1
    assert list_positions(repo).empty
    repo.close()


def test_holdings_section_summarizes_open_positions():
    from analyzer.notify.report import _holdings_section

    repo = _repo()
    # Seed a price so last_close / P&L / cushion compute.
    repo.upsert_df("prices_adj", pd.DataFrame([{
        "symbol": "CGPOWER", "date": date(2026, 7, 6), "open": 890.0, "high": 895.0,
        "low": 888.0, "close": 892.0, "volume": 1000, "adj_factor": 1.0,
    }]))
    add_position(repo, "CGPOWER", 100, 900.0, 880.0)
    section = _holdings_section(repo)
    assert "CGPOWER" in section
    assert "892" in section              # last close shown
    assert "Total open P&L" in section
    repo.close()


def test_holdings_section_empty():
    from analyzer.notify.report import _holdings_section

    repo = _repo()
    assert "No open holdings" in _holdings_section(repo)
    repo.close()


def test_market_hours_logic():
    cal = TradingCalendar(holidays={date(2026, 7, 6)})  # pretend Monday is a holiday
    # Tuesday 10:00 -> in hours.
    assert in_market_hours(datetime(2026, 7, 7, 10, 0), cal)
    # Tuesday 08:00 (pre-open) and 16:30 (post-close) -> out.
    assert not in_market_hours(datetime(2026, 7, 7, 8, 0), cal)
    assert not in_market_hours(datetime(2026, 7, 7, 16, 30), cal)
    # Saturday -> out; holiday Monday -> out.
    assert not in_market_hours(datetime(2026, 7, 11, 10, 0), cal)
    assert not in_market_hours(datetime(2026, 7, 6, 10, 0), cal)


def test_digest_includes_holdings_and_actions():
    report = "\n".join([
        "# Daily Report — 2026-07-06",
        "",
        "**Regime: BEAR** | Nifty 24,000",
        "",
        "## Your holdings (end of day)",
        "| Symbol | Qty | Entry | Last | P&L | P&L% | Stop | Cushion |",
        "|--------|-----|-------|------|-----|------|------|---------|",
        "| CGPOWER | 100 | 900.0 | 892.6 | -740 | -0.8% | 880.0 | +1.4% |",
        "",
        "**Total open P&L: -740 (-0.8%)**",
        "",
        "## Open-position actions",
        "- TATAPOWER: T1 hit — book 50%",
        "",
        "## New signals (observational — do not trade)",
        "_No new signals today._",
        "",
        "## Live observational performance (tracked outcomes)",
        "_No terminal outcomes tracked yet._",
    ])
    digest = telegram_digest(report)
    # Holdings row + total P&L reach the phone.
    assert "CGPOWER" in digest and "892.6" in digest
    assert "Total open P&L: -740" in digest
    # Actions still carried.
    assert "TATAPOWER" in digest
    assert "Regime: BEAR" in digest
    # The performance table (not a chosen section) must NOT leak in.
    assert "terminal outcomes" not in digest


def test_digest_no_holdings():
    report = "\n".join([
        "# Daily Report — 2026-07-06",
        "**Regime: BULL** | Nifty 25,000",
        "## Your holdings (end of day)",
        "_No open holdings. Log buys with the bot._",
        "## Open-position actions",
        "_None._",
        "## New signals (observational — do not trade)",
        "_No new signals today._",
    ])
    digest = telegram_digest(report)
    assert "no open holdings" in digest.lower()
    assert "no actions today" in digest.lower()
