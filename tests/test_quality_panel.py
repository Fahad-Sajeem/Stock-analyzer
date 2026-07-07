"""Tests for the point-in-time quality panel (R3 building block)."""

from datetime import date, timedelta

import pandas as pd

from analyzer.research.quality_panel import build_snapshot, quality_gate


def _hist_rows():
    """Synthetic fundamentals_history: GOOD (quality) and JUNK symbols."""
    rows = []

    def add(symbol, metric, freq, year, value, month=3):
        pe = date(year, month, 31 if month == 3 else 30)
        lag = {"A": 185, "Q": 60, "SH": 45}[freq]
        rows.append(
            {"symbol": symbol, "period": f"FY{year}", "period_end": pd.Timestamp(pe),
             "freq": freq, "metric": metric, "value": value,
             "available_from": pd.Timestamp(pe + timedelta(days=lag))}
        )

    for y, sales in [(2020, 100), (2021, 120), (2022, 150), (2023, 200)]:
        add("GOOD", "sales", "A", y, sales)
        add("JUNK", "sales", "A", y, 100)          # zero growth
    for y, e in [(2022, 10.0), (2023, 14.0)]:
        add("GOOD", "eps", "A", y, e)
        add("JUNK", "eps", "A", y, -2.0)
    add("GOOD", "roce_pct", "A", 2023, 22.0)
    add("JUNK", "roce_pct", "A", 2023, 4.0)
    add("GOOD", "cfo", "A", 2023, 50.0)
    add("JUNK", "cfo", "A", 2023, -10.0)
    add("GOOD", "equity_capital", "A", 2023, 10.0)
    add("GOOD", "reserves", "A", 2023, 200.0)
    add("GOOD", "borrowings", "A", 2023, 40.0)     # D/E ~0.19
    add("JUNK", "equity_capital", "A", 2023, 10.0)
    add("JUNK", "reserves", "A", 2023, 20.0)
    add("JUNK", "borrowings", "A", 2023, 200.0)    # D/E ~6.7
    add("GOOD", "promoter_pct", "SH", 2023, 55.0)
    return pd.DataFrame(rows)


def test_snapshot_point_in_time_excludes_unavailable():
    hist = _hist_rows()
    # As of June 2023, FY2023 (avail ~Oct 2023) must NOT be visible; FY2022 is.
    snap = build_snapshot(hist, date(2023, 6, 30))
    assert "roce_pct" in snap.columns
    # GOOD's ROCE was only reported for FY2023 -> not yet available.
    assert pd.isna(snap.loc["GOOD", "roce_pct"])

    # As of Dec 2023, FY2023 is available.
    snap2 = build_snapshot(hist, date(2023, 12, 31))
    assert snap2.loc["GOOD", "roce_pct"] == 22.0


def test_quality_gate_separates_good_from_junk():
    hist = _hist_rows()
    snap = build_snapshot(hist, date(2024, 6, 30))
    gate = quality_gate(snap)
    assert bool(gate["GOOD"])
    assert not bool(gate["JUNK"])


def test_growth_computation():
    hist = _hist_rows()
    snap = build_snapshot(hist, date(2024, 6, 30))
    # 100 -> 200 over 3 years = ~26% CAGR
    assert 24 < snap.loc["GOOD", "sales_growth"] < 28
    assert abs(snap.loc["JUNK", "sales_growth"]) < 1e-9
