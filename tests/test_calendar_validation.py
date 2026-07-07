"""Tests for the trading calendar and the data-validation layer."""

from datetime import date

import pandas as pd

from analyzer.data.calendar import TradingCalendar, seed_holidays
from analyzer.data.validation import check_ohlc_integrity, validate_prices
from analyzer.db.repository import Repository


def _calendar_with_holiday():
    # 2025-08-15 (Independence Day) is a Friday holiday.
    return TradingCalendar(holidays={date(2025, 8, 15)})


def test_weekend_is_not_trading_day():
    cal = _calendar_with_holiday()
    assert not cal.is_trading_day(date(2025, 8, 16))  # Saturday
    assert not cal.is_trading_day(date(2025, 8, 17))  # Sunday


def test_holiday_is_not_trading_day():
    cal = _calendar_with_holiday()
    assert not cal.is_trading_day(date(2025, 8, 15))
    assert cal.is_trading_day(date(2025, 8, 14))  # Thursday


def test_previous_and_next_trading_day_skip_holiday_and_weekend():
    cal = _calendar_with_holiday()
    # Day after Thursday 14th is Friday 15th (holiday) then weekend -> Monday 18th.
    assert cal.next_trading_day(date(2025, 8, 14)) == date(2025, 8, 18)
    assert cal.previous_trading_day(date(2025, 8, 18)) == date(2025, 8, 14)


def test_add_sessions():
    cal = _calendar_with_holiday()
    # 3 sessions after Wed 13th: Thu 14 (1), Fri 15 holiday skip, Mon 18 (2), Tue 19 (3)
    assert cal.add_sessions(date(2025, 8, 13), 3) == date(2025, 8, 19)


def test_seed_holidays_populates_table():
    repo = Repository.open(":memory:")
    n = seed_holidays(repo)
    assert n > 0
    cal = TradingCalendar.from_repo(repo)
    assert not cal.is_trading_day(date(2025, 12, 25))  # Christmas seeded
    repo.close()


def test_ohlc_integrity_flags_bad_row():
    df = pd.DataFrame(
        {
            "symbol": ["A", "B"],
            "date": [date(2025, 1, 1), date(2025, 1, 1)],
            "open": [10.0, 10.0],
            "high": [9.0, 12.0],   # A: high < open -> violation
            "low": [8.0, 9.0],
            "close": [8.5, 11.0],
        }
    )
    bad = check_ohlc_integrity(df)
    assert len(bad) == 1
    assert bad.iloc[0]["symbol"] == "A"


def test_validate_prices_detects_big_move():
    df = pd.DataFrame(
        {
            "symbol": ["A", "A"],
            "date": [date(2025, 1, 1), date(2025, 1, 2)],
            "open": [100.0, 200.0],
            "high": [100.0, 200.0],
            "low": [100.0, 200.0],
            "close": [100.0, 200.0],  # +100% move
            "volume": [10, 10],
        }
    )
    rep = validate_prices(df)
    assert len(rep.big_moves) == 1
    assert rep.checked_rows == 2
