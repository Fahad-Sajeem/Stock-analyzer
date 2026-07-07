"""EXP-004 (R4) — results-announcement calendar from the NSE board-meetings archive.

Pages the archive in quarterly windows, keeps meetings whose purpose mentions
financial results, and stores (symbol, announce_date) in ``results_calendar``.
Note: board-meeting date is when results are approved & announced (often after
market close) — consumers should treat announce_date AND the next session as
the potential reaction window.

Run:  .venv/Scripts/python.exe -m analyzer.research.results_calendar [--from-year 2016]
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from analyzer.data.nse_client import NseClient
from analyzer.logging_setup import configure_logging, get_logger

log = get_logger(__name__)


def _quarter_windows(from_year: int, until: date) -> list[tuple[date, date]]:
    out = []
    for year in range(from_year, until.year + 1):
        for q_start_month in (1, 4, 7, 10):
            start = date(year, q_start_month, 1)
            end_month = q_start_month + 2
            end = date(year, end_month, [31, 30, 30, 31][(q_start_month - 1) // 3])
            if start > until:
                break
            out.append((start, min(end, until)))
    return out


def fetch_board_meetings(client: NseClient, start: date, end: date) -> pd.DataFrame:
    url = (
        f"{client.base_url}/api/corporate-board-meetings?index=equities"
        f"&from_date={start.strftime('%d-%m-%Y')}&to_date={end.strftime('%d-%m-%Y')}"
    )
    referer = f"{client.base_url}/companies-listing/corporate-filings-board-meetings"
    try:
        data = client.get_json(url, referer=referer)
    except Exception as exc:  # noqa: BLE001
        log.warning("bm_fetch_failed", start=str(start), error=str(exc))
        return pd.DataFrame()
    recs = data if isinstance(data, list) else data.get("data", [])
    if not recs:
        return pd.DataFrame()
    df = pd.DataFrame(recs)
    if "bm_symbol" not in df.columns or "bm_date" not in df.columns:
        log.warning("bm_unexpected_format", cols=list(df.columns)[:8])
        return pd.DataFrame()

    purpose = df.get("bm_purpose", pd.Series("", index=df.index)).astype(str)
    results_mask = purpose.str.lower().str.contains("result", na=False)
    df = df[results_mask]
    out = pd.DataFrame(
        {
            "symbol": df["bm_symbol"].astype(str).str.strip(),
            "announce_date": pd.to_datetime(df["bm_date"], format="%d-%b-%Y", errors="coerce").dt.date,
            "purpose": purpose[results_mask].str.slice(0, 120),
            "source": "nse_bm",
        }
    ).dropna(subset=["announce_date"])
    return out.drop_duplicates(subset=["symbol", "announce_date"]).reset_index(drop=True)


def run_ingest(repo, from_year: int = 2016) -> dict:
    client = NseClient()
    windows = _quarter_windows(from_year, date.today())
    total = 0
    with repo.job_run("results_calendar_ingest") as jr:
        for start, end in windows:
            df = fetch_board_meetings(client, start, end)
            if not df.empty:
                total += repo.upsert_df("results_calendar", df)
            log.info("bm_window_done", window=f"{start}..{end}", rows=len(df))
        jr.add_rows(total)
    summary = {
        "windows": len(windows),
        "rows": total,
        "symbols": repo.scalar("SELECT COUNT(DISTINCT symbol) FROM results_calendar"),
        "min_date": str(repo.scalar("SELECT MIN(announce_date) FROM results_calendar")),
        "max_date": str(repo.scalar("SELECT MAX(announce_date) FROM results_calendar")),
    }
    log.info("results_calendar_done", **summary)
    return summary


def main() -> None:
    import argparse

    from analyzer.jobs.ingest import open_repo

    configure_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-year", type=int, default=2016)
    args = ap.parse_args()
    repo = open_repo()
    try:
        print(run_ingest(repo, from_year=args.from_year))
    finally:
        repo.close()


if __name__ == "__main__":
    main()
