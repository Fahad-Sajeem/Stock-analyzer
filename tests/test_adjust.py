"""Golden tests for corporate-action adjustment (PLAN Phase 1 DoD, 16 pt.3)."""

import pandas as pd

from analyzer.data.adjust import adjust_prices, price_multiplier


def test_price_multiplier_bonus_1_1():
    # 1:1 bonus -> price halves -> multiplier 0.5
    assert price_multiplier("BONUS", "1:1", None) == 0.5


def test_price_multiplier_bonus_1_2():
    # 1 new for every 2 held -> 2/(1+2) = 0.6667
    assert abs(price_multiplier("BONUS", "1:2", None) - (2 / 3)) < 1e-9


def test_price_multiplier_split_10_to_1():
    # face value 10 -> 1 : share count ×10 -> price ×(1/10)
    assert abs(price_multiplier("SPLIT", "10:1", None) - 0.1) < 1e-9


def test_price_multiplier_dividend_noop():
    assert price_multiplier("DIVIDEND", None, 5.0) == 1.0


def test_adjust_prices_known_bonus():
    # Stock at 100 for 3 days, then a 1:1 bonus on day 4 halves the price to 50.
    prices = pd.DataFrame(
        {
            "symbol": ["X"] * 5,
            "date": pd.to_datetime(
                ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
            ),
            "open": [100, 100, 100, 50, 50],
            "high": [100, 100, 100, 50, 50],
            "low": [100, 100, 100, 50, 50],
            "close": [100, 100, 100, 50, 50],
            "volume": [1000, 1000, 1000, 2000, 2000],
        }
    )
    actions = pd.DataFrame(
        {"ex_date": [pd.Timestamp("2024-01-04")], "action_type": ["BONUS"], "ratio": ["1:1"],
         "value": [None]}
    )
    adj = adjust_prices(prices, actions)
    # Pre-ex-date closes should be halved to match the post-bonus series (no false crash).
    assert list(adj["close"]) == [50, 50, 50, 50, 50]
    # Volume on pre-ex days should be doubled (inverse of price factor).
    assert list(adj["volume"])[:3] == [2000, 2000, 2000]
    # adj_factor is 0.5 before the event, 1.0 on/after.
    assert list(adj["adj_factor"]) == [0.5, 0.5, 0.5, 1.0, 1.0]


def test_adjust_prices_no_actions_is_identity():
    prices = pd.DataFrame(
        {
            "symbol": ["Y"] * 3,
            "date": pd.to_datetime(["2024-02-01", "2024-02-02", "2024-02-03"]),
            "open": [10, 11, 12],
            "high": [10, 11, 12],
            "low": [10, 11, 12],
            "close": [10, 11, 12],
            "volume": [5, 6, 7],
        }
    )
    adj = adjust_prices(prices, pd.DataFrame())
    assert list(adj["close"]) == [10, 11, 12]
    assert list(adj["adj_factor"]) == [1.0, 1.0, 1.0]
