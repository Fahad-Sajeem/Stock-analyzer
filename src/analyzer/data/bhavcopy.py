"""NSE bhavcopy ingestion — the daily EOD ground truth (PLAN 4.2).

Primary source: the *security-wise delivery* bhavcopy
    https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv
which carries OHLC, volume, turnover AND delivery quantity/percentage in one
file — one download per day instead of ~2,000 per-symbol requests.

Delivery % is an India-specific edge (genuine accumulation vs. churn), so this
file is preferred over the plain UDiFF bhavcopy which lacks delivery data.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from analyzer.data.nse_client import NseClient
from analyzer.logging_setup import get_logger

log = get_logger(__name__)

# Series we treat as tradeable cash equity. EQ = normal rolling; BE = trade-to-trade.
_KEEP_SERIES = {"EQ", "BE"}


def _sec_bhavdata_url(client: NseClient, d: date) -> str:
    ddmmyyyy = d.strftime("%d%m%Y")
    return f"{client.archives_url}/products/content/sec_bhavdata_full_{ddmmyyyy}.csv"


def fetch_bhavcopy(client: NseClient, d: date, use_cache: bool = True) -> pd.DataFrame:
    """Download & normalize one day's bhavcopy into the ``prices_raw`` shape.

    Returns an empty DataFrame if the file is absent (e.g. a holiday slipped
    through, or data not yet published).
    """
    url = _sec_bhavdata_url(client, d)
    fname = f"sec_bhavdata_full_{d.strftime('%d%m%Y')}.csv"
    try:
        path = client.download(url, fname, referer=f"{client.base_url}/", use_cache=use_cache)
    except RuntimeError as exc:
        log.warning("bhavcopy_unavailable", date=str(d), error=str(exc))
        return pd.DataFrame()
    return parse_sec_bhavdata(path, d)


def parse_sec_bhavdata(path, d: date) -> pd.DataFrame:
    """Pure parser for a sec_bhavdata_full CSV file -> ``prices_raw`` shape.

    Separated from the network fetch so it can be unit-tested with a fixture.
    """
    # NSE writes column names/values with leading spaces -> skipinitialspace.
    raw = pd.read_csv(path, skipinitialspace=True)
    raw.columns = [c.strip().upper() for c in raw.columns]
    if "SERIES" not in raw.columns or "SYMBOL" not in raw.columns:
        log.warning("bhavcopy_bad_format", date=str(d), cols=list(raw.columns))
        return pd.DataFrame()

    raw["SERIES"] = raw["SERIES"].astype(str).str.strip()
    df = raw[raw["SERIES"].isin(_KEEP_SERIES)].copy()
    if df.empty:
        return pd.DataFrame()

    def num(col: str) -> pd.Series:
        return pd.to_numeric(df[col], errors="coerce")

    out = pd.DataFrame(
        {
            "symbol": df["SYMBOL"].astype(str).str.strip(),
            "date": d,
            "open": num("OPEN_PRICE"),
            "high": num("HIGH_PRICE"),
            "low": num("LOW_PRICE"),
            "close": num("CLOSE_PRICE"),
            "volume": num("TTL_TRD_QNTY").fillna(0).astype("int64"),
            # TURNOVER_LACS is in lakhs of rupees -> convert to rupees.
            "traded_value": num("TURNOVER_LACS") * 1e5,
            "delivery_qty": num("DELIV_QTY").fillna(0).astype("int64"),
            "delivery_pct": num("DELIV_PER"),
        }
    )
    # Drop rows with no usable close (suspended/again bad lines).
    out = out.dropna(subset=["close"])
    out = out[out["close"] > 0]
    log.info("bhavcopy_parsed", date=str(d), rows=len(out))
    return out.reset_index(drop=True)
