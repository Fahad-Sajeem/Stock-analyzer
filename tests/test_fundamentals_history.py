"""Offline tests for the Screener fundamentals-history parser (EXP-002)."""

from datetime import date

import pandas as pd

from analyzer.research.fundamentals_history import (
    _parse_period,
    _to_num,
    parse_company_html,
)

_HTML = """
<html><body>
<section id="profit-loss">
<table class="data-table">
<thead><tr><th></th><th>Mar 2023</th><th>Mar 2024</th><th>TTM</th></tr></thead>
<tbody>
<tr><td>Sales&nbsp;+</td><td>1,000</td><td>1,200</td><td>1,300</td></tr>
<tr><td>OPM %</td><td>15%</td><td>17%</td><td>18%</td></tr>
<tr><td>Net Profit&nbsp;+</td><td>100</td><td>140</td><td>150</td></tr>
<tr><td>EPS in Rs</td><td>10.5</td><td>14.2</td><td>15.0</td></tr>
</tbody></table>
</section>
<section id="balance-sheet">
<table class="data-table">
<thead><tr><th></th><th>Mar 2023</th><th>Mar 2024</th></tr></thead>
<tbody>
<tr><td>Borrowings&nbsp;+</td><td>500</td><td>450</td></tr>
<tr><td>Reserves&nbsp;+</td><td>800</td><td>900</td></tr>
</tbody></table>
</section>
<section id="quarters">
<table class="data-table">
<thead><tr><th></th><th>Dec 2024</th><th>Mar 2025</th></tr></thead>
<tbody>
<tr><td>Sales&nbsp;+</td><td>310</td><td>330</td></tr>
<tr><td>Net Profit&nbsp;+</td><td>36</td><td>40</td></tr>
</tbody></table>
</section>
<section id="shareholding">
<table class="data-table">
<thead><tr><th></th><th>Mar 2025</th></tr></thead>
<tbody>
<tr><td>Promoters&nbsp;+</td><td>52.30%</td></tr>
<tr><td>FIIs&nbsp;+</td><td>18.10%</td></tr>
</tbody></table>
</section>
</body></html>
"""


def test_parse_period():
    assert _parse_period("Mar 2024") == date(2024, 3, 31)
    assert _parse_period("Dec 2024") == date(2024, 12, 31)
    assert _parse_period("TTM") is None


def test_to_num():
    assert _to_num("1,234") == 1234.0
    assert _to_num("15%") == 15.0
    assert _to_num("-42.5") == -42.5
    assert _to_num("") is None


def test_parse_company_html_full():
    rows = parse_company_html(_HTML, "TESTCO", "screener-consolidated")
    df = pd.DataFrame(rows)

    # Annual: sales FY2024 = 1200; TTM column skipped.
    ann_sales = df[(df.freq == "A") & (df.metric == "sales")]
    assert set(ann_sales.period) == {"FY2023", "FY2024"}
    assert float(ann_sales[ann_sales.period == "FY2024"].value.iloc[0]) == 1200.0

    # Availability lag: FY Mar 2024 -> +185 days (~Oct 2024).
    af = ann_sales[ann_sales.period == "FY2024"].available_from.iloc[0]
    assert af == date(2024, 3, 31) + pd.Timedelta(days=185)

    # Quarterly rows exist with 60-day lag.
    q = df[(df.freq == "Q") & (df.metric == "net_profit") & (df.period == "Q2025-03")]
    assert len(q) == 1
    assert q.available_from.iloc[0] == date(2025, 3, 31) + pd.Timedelta(days=60)

    # Shareholding parsed with 45-day lag.
    sh = df[(df.freq == "SH") & (df.metric == "promoter_pct")]
    assert float(sh.value.iloc[0]) == 52.30
    assert sh.available_from.iloc[0] == date(2025, 3, 31) + pd.Timedelta(days=45)

    # Balance sheet metrics present.
    assert (df.metric == "borrowings").any()
    # OPM percent captured as number.
    opm = df[(df.metric == "opm_pct") & (df.period == "FY2024")]
    assert float(opm.value.iloc[0]) == 17.0
