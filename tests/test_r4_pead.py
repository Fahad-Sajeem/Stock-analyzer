"""Unit tests for R4 PEAD helpers."""

from datetime import date

import pandas as pd

from analyzer.research.r4_pead import build_yoy_confirm, inject_results_flag
from analyzer.research.results_calendar import _quarter_windows


def test_inject_results_flag_marks_day_and_next_session():
    df = pd.DataFrame({"date": [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3),
                                date(2024, 1, 4)]})
    out = inject_results_flag(df, {date(2024, 1, 2)})
    assert list(out["results_recent"]) == [False, True, True, False]


def test_quarter_windows_cover_range():
    wins = _quarter_windows(2016, date(2016, 12, 31))
    assert wins[0][0] == date(2016, 1, 1)
    assert len(wins) == 4


def test_yoy_confirm():
    hist = pd.DataFrame(
        [
            # current quarter: strong profit growth (+40%)
            {"symbol": "X", "freq": "Q", "metric": "net_profit",
             "period_end": pd.Timestamp("2023-09-30"), "value": 140.0},
            {"symbol": "X", "freq": "Q", "metric": "net_profit",
             "period_end": pd.Timestamp("2022-09-30"), "value": 100.0},
            {"symbol": "X", "freq": "Q", "metric": "sales",
             "period_end": pd.Timestamp("2023-09-30"), "value": 105.0},
            {"symbol": "X", "freq": "Q", "metric": "sales",
             "period_end": pd.Timestamp("2022-09-30"), "value": 100.0},
            # symbol with weak growth
            {"symbol": "Y", "freq": "Q", "metric": "net_profit",
             "period_end": pd.Timestamp("2023-09-30"), "value": 101.0},
            {"symbol": "Y", "freq": "Q", "metric": "net_profit",
             "period_end": pd.Timestamp("2022-09-30"), "value": 100.0},
        ]
    )
    confirm = build_yoy_confirm(hist)
    # Signal shortly after the Sep-2023 quarter: X confirms (+40% profit), Y doesn't.
    assert confirm("X", date(2023, 11, 1))
    assert not confirm("Y", date(2023, 11, 1))
    # Signal too long after period end (>75d) -> no confirmation.
    assert not confirm("X", date(2024, 3, 1))
    # Unknown symbol -> False.
    assert not confirm("Z", date(2023, 11, 1))
