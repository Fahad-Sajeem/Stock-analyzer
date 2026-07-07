"""Symbol master ingestion — maps SYMBOL <-> ISIN and listing metadata.

Source: NSE's official equity list
    https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv
Columns: SYMBOL, NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE,
         MARKET LOT, ISIN NUMBER, FACE VALUE

ISIN is the stable identity key (symbols get renamed; ISINs don't), so it is the
primary key of the ``symbols`` table.
"""

from __future__ import annotations

import pandas as pd

from analyzer.data.nse_client import NseClient
from analyzer.db.repository import Repository
from analyzer.logging_setup import get_logger

log = get_logger(__name__)


def fetch_equity_list(client: NseClient, use_cache: bool = False) -> pd.DataFrame:
    url = f"{client.archives_url}/content/equities/EQUITY_L.csv"
    # This file changes as companies list/delist -> don't cache by default.
    path = client.download(url, "EQUITY_L.csv", referer=f"{client.base_url}/", use_cache=use_cache)
    raw = pd.read_csv(path, skipinitialspace=True)
    raw.columns = [c.strip().upper() for c in raw.columns]

    out = pd.DataFrame(
        {
            "isin": raw["ISIN NUMBER"].astype(str).str.strip(),
            "symbol": raw["SYMBOL"].astype(str).str.strip(),
            "name": raw["NAME OF COMPANY"].astype(str).str.strip(),
            "exchange": "NSE",
            "listing_date": pd.to_datetime(
                raw["DATE OF LISTING"], format="%d-%b-%Y", errors="coerce"
            ).dt.date,
            "is_active": True,
        }
    )
    out = out[out["isin"].str.startswith("IN", na=False)].reset_index(drop=True)
    log.info("equity_list_fetched", rows=len(out))
    return out


def sync_symbols(repo: Repository, client: NseClient | None = None) -> int:
    """Refresh the ``symbols`` master table from NSE. Returns rows written."""
    client = client or NseClient(repo_cfg(repo))
    df = fetch_equity_list(client)
    return repo.upsert_df("symbols", df)


def repo_cfg(_repo: Repository):  # small helper so callers can omit a client
    from analyzer.config import get_config

    return get_config()
