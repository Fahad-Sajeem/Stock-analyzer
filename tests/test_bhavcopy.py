"""Offline test of the bhavcopy parser using a small fixture in NSE's format."""

from datetime import date

from analyzer.data.bhavcopy import parse_sec_bhavdata

# NSE writes headers/values with a leading space after each comma.
_FIXTURE = (
    "SYMBOL, SERIES, DATE1, PREV_CLOSE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, "
    "LAST_PRICE, CLOSE_PRICE, AVG_PRICE, TTL_TRD_QNTY, TURNOVER_LACS, NO_OF_TRADES, "
    "DELIV_QTY, DELIV_PER\n"
    "RELIANCE, EQ, 30-Jun-2026, 3000.00, 3010.00, 3050.00, 2995.00, 3040.00, "
    "3042.50, 3041.00, 5000000, 152125.00, 120000, 3000000, 60.00\n"
    "TCS, EQ, 30-Jun-2026, 3800.00, 3810.00, 3830.00, 3790.00, 3820.00, "
    "3821.00, 3815.00, 1000000, 38210.00, 45000, 700000, 70.00\n"
    "SOMESME, SM, 30-Jun-2026, 50.00, 51.00, 52.00, 49.00, 50.50, 50.40, 50.30, "
    "1000, 0.50, 30, 500, 50.00\n"
    "TRUSTEE, BE, 30-Jun-2026, 10.00, 10.10, 10.50, 10.00, 10.40, 10.30, 10.25, "
    "2000, 0.21, 40, 1000, 50.00\n"
)


def test_parse_sec_bhavdata(tmp_path):
    f = tmp_path / "sec.csv"
    f.write_text(_FIXTURE, encoding="utf-8")
    df = parse_sec_bhavdata(f, date(2026, 6, 30))

    # Keeps EQ and BE, drops the SM (SME) series row.
    assert set(df["symbol"]) == {"RELIANCE", "TCS", "TRUSTEE"}

    r = df[df["symbol"] == "RELIANCE"].iloc[0]
    assert r["open"] == 3010.0
    assert r["high"] == 3050.0
    # CLOSE_PRICE column is 3042.50 (LAST_PRICE 3040 is a different column).
    assert r["close"] == 3042.5
    assert r["volume"] == 5_000_000
    assert r["delivery_pct"] == 60.0
    # TURNOVER_LACS 152125 lakhs -> rupees = 1.52125e10
    assert abs(r["traded_value"] - 152125.0 * 1e5) < 1.0
    assert r["date"] == date(2026, 6, 30)
