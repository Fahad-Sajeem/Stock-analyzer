"""Offline test of the Screener.in top-ratios parser."""

from analyzer.fundamentals.fetch_screener import parse_top_ratios, _to_number

_HTML = """
<html><body>
<ul id="top-ratios">
  <li class="flex flex-space-between">
    <span class="name">Market Cap</span>
    <span class="nowrap value">₹ <span class="number">16,50,000</span> Cr.</span>
  </li>
  <li class="flex flex-space-between">
    <span class="name">Stock P/E</span>
    <span class="nowrap value"><span class="number">28.4</span></span>
  </li>
  <li class="flex flex-space-between">
    <span class="name">ROCE</span>
    <span class="nowrap value"><span class="number">22.1</span> %</span>
  </li>
  <li class="flex flex-space-between">
    <span class="name">ROE</span>
    <span class="nowrap value"><span class="number">19.8</span> %</span>
  </li>
</ul>
</body></html>
"""


def test_to_number_handles_indian_formatting():
    assert _to_number("₹ 16,50,000 Cr.") == 1650000.0
    assert _to_number("28.4") == 28.4
    assert _to_number("22.1 %") == 22.1
    assert _to_number("--") is None


def test_parse_top_ratios():
    ratios = parse_top_ratios(_HTML)
    assert ratios["Market Cap"] == 1650000.0
    assert ratios["Stock P/E"] == 28.4
    assert ratios["ROCE"] == 22.1
    assert ratios["ROE"] == 19.8
