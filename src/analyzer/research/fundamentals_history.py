"""EXP-002 (R2) — point-in-time fundamentals history from Screener.in.

Scrapes company pages (consolidated, standalone fallback) for the top-N liquid
symbols and stores a LONG-format panel in ``fundamentals_history`` with
conservative ``available_from`` lags (see RESEARCH_LOG.md EXP-002 — do not
change lags without a new log entry).

Run:  .venv/Scripts/python.exe -m analyzer.research.fundamentals_history [--limit 800]
"""

from __future__ import annotations

import io
import re
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

from analyzer.config import get_config
from analyzer.logging_setup import configure_logging, get_logger

log = get_logger(__name__)

_BASE = "https://www.screener.in"

# Availability lags (days past period_end) — registered in EXP-002.
_LAG_ANNUAL = 185
_LAG_QUARTER = 60
_LAG_SHAREHOLDING = 45

# Row-label (lowercased, cleaned) -> canonical metric name, per section.
_PL_METRICS = {
    "sales": "sales", "revenue": "sales",
    "operating profit": "operating_profit", "financing profit": "operating_profit",
    "opm": "opm_pct", "financing margin": "opm_pct",
    "interest": "interest", "depreciation": "depreciation",
    "profit before tax": "pbt", "net profit": "net_profit",
    "eps in rs": "eps",
}
_BS_METRICS = {
    "equity capital": "equity_capital", "reserves": "reserves",
    "borrowings": "borrowings", "total assets": "total_assets",
}
_CF_METRICS = {"cash from operating activity": "cfo"}
_RATIO_METRICS = {"roce": "roce_pct"}
_SH_METRICS = {"promoters": "promoter_pct", "fiis": "fii_pct", "diis": "dii_pct"}


# --------------------------------------------------------------------------
# parsing (pure — unit-testable on HTML fixtures)
# --------------------------------------------------------------------------

def _clean_label(s: str) -> str:
    s = re.sub(r"[+%\xa0]", " ", str(s))
    return re.sub(r"\s+", " ", s).strip().lower()


def _to_num(v) -> float | None:
    s = re.sub(r"[^0-9.\-]", "", str(v).replace(",", ""))
    if s in ("", "-", ".", "-."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_period(col: str) -> date | None:
    """'Mar 2024' -> date(2024,3,31)-ish (last day of month)."""
    m = re.match(r"([A-Za-z]{3})\s+(\d{4})", str(col).strip())
    if not m:
        return None
    try:
        d = datetime.strptime(f"{m.group(1)} {m.group(2)}", "%b %Y")
    except ValueError:
        return None
    nxt = date(d.year + (d.month == 12), (d.month % 12) + 1, 1)
    return nxt - timedelta(days=1)


def _section_table(html: str, section_id: str) -> pd.DataFrame | None:
    """Extract the first data table inside <section id=...> ... </section>."""
    m = re.search(rf'<section[^>]+id="{section_id}".*?</section>', html, re.DOTALL)
    if not m:
        return None
    try:
        tables = pd.read_html(io.StringIO(m.group(0)))
    except ValueError:
        return None
    return tables[0] if tables else None


def _rows_from_table(
    table: pd.DataFrame, metric_map: dict[str, str], freq: str, symbol: str, source: str
) -> list[dict]:
    """Melt a Screener section table into long-format metric rows."""
    if table is None or table.empty:
        return []
    out: list[dict] = []
    label_col = table.columns[0]
    lag = {"A": _LAG_ANNUAL, "Q": _LAG_QUARTER, "SH": _LAG_SHAREHOLDING}[freq]
    prefix = {"A": "FY", "Q": "Q", "SH": "SH"}[freq]

    for _, row in table.iterrows():
        label = _clean_label(row[label_col])
        metric = None
        for key, name in metric_map.items():
            if label == key or label.startswith(key + " ") or label.startswith(key):
                metric = name
                break
        if metric is None:
            continue
        for col in table.columns[1:]:
            pe = _parse_period(str(col))
            if pe is None:      # skips 'TTM' and junk columns
                continue
            val = _to_num(row[col])
            if val is None:
                continue
            period = f"FY{pe.year}" if freq == "A" else f"{prefix}{pe.year}-{pe.month:02d}"
            out.append(
                {
                    "symbol": symbol, "period": period, "period_end": pe, "freq": freq,
                    "metric": metric, "value": val,
                    "available_from": pe + timedelta(days=lag),
                    "source": source, "fetched_at": datetime.now(),
                }
            )
    return out


def parse_company_html(html: str, symbol: str, source: str) -> list[dict]:
    """Parse one Screener company page into fundamentals_history rows."""
    rows: list[dict] = []
    rows += _rows_from_table(_section_table(html, "profit-loss"), _PL_METRICS, "A", symbol, source)
    rows += _rows_from_table(_section_table(html, "balance-sheet"), _BS_METRICS, "A", symbol, source)
    rows += _rows_from_table(_section_table(html, "cash-flow"), _CF_METRICS, "A", symbol, source)
    rows += _rows_from_table(_section_table(html, "ratios"), _RATIO_METRICS, "A", symbol, source)
    rows += _rows_from_table(_section_table(html, "quarters"), _PL_METRICS, "Q", symbol, source)
    rows += _rows_from_table(_section_table(html, "shareholding"), _SH_METRICS, "SH", symbol, source)
    return rows


# --------------------------------------------------------------------------
# fetching (cached, rate-limited)
# --------------------------------------------------------------------------

def _cache_dir() -> Path:
    d = get_config().cache_path / "screener"
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch_company_html(symbol: str, session: requests.Session, use_cache: bool = True) -> tuple[str, str] | None:
    """Return (html, source) for a symbol; consolidated preferred. Cached on disk."""
    cfg = get_config()
    for variant, url in [
        ("screener-consolidated", f"{_BASE}/company/{symbol}/consolidated/"),
        ("screener-standalone", f"{_BASE}/company/{symbol}/"),
    ]:
        cache = _cache_dir() / f"{symbol}.{variant}.html"
        if use_cache and cache.exists() and cache.stat().st_size > 5000:
            html = cache.read_text(encoding="utf-8", errors="ignore")
        else:
            try:
                resp = session.get(url, timeout=cfg.ingestion.request_timeout_sec)
            except requests.RequestException as exc:
                log.warning("screener_request_error", symbol=symbol, error=str(exc))
                return None
            if resp.status_code == 429:
                log.warning("screener_rate_limited", symbol=symbol)
                time.sleep(30)
                return None
            if resp.status_code != 200:
                continue
            html = resp.text
            cache.write_text(html, encoding="utf-8")
            time.sleep(2.0)  # registered rate limit
        # Consolidated pages of standalone-only companies are stubs — check for data.
        if 'id="profit-loss"' in html and _section_table(html, "profit-loss") is not None:
            return html, variant
    return None


def top_liquid_symbols(repo, limit: int) -> list[str]:
    rows = repo.query_df(
        """
        SELECT symbol, MEDIAN(volume * close) AS mtv
        FROM prices_adj
        WHERE date >= (SELECT MAX(date) FROM prices_adj) - INTERVAL 365 DAY
        GROUP BY symbol HAVING COUNT(*) >= 200
        ORDER BY mtv DESC LIMIT ?
        """,
        [limit],
    )
    return rows["symbol"].tolist()


def run_scrape(repo, limit: int = 800) -> dict:
    cfg = get_config()
    session = requests.Session()
    session.headers.update({"User-Agent": cfg.ingestion.user_agent,
                            "Accept-Language": "en-US,en;q=0.9"})
    symbols = top_liquid_symbols(repo, limit)

    ok, failed, total_rows = 0, [], 0
    with repo.job_run("fundamentals_history_scrape") as jr:
        for i, sym in enumerate(symbols, 1):
            res = fetch_company_html(sym, session)
            if res is None:
                failed.append(sym)
                continue
            html, source = res
            rows = parse_company_html(html, sym, source)
            if not rows:
                failed.append(sym)
                continue
            total_rows += repo.upsert_df("fundamentals_history", pd.DataFrame(rows))
            ok += 1
            if i % 25 == 0:
                log.info("scrape_progress", done=i, total=len(symbols), ok=ok,
                         failed=len(failed), rows=total_rows)
        jr.add_rows(total_rows)

    summary = {"requested": len(symbols), "ok": ok, "failed": len(failed),
               "rows": total_rows, "failed_symbols": failed[:20]}
    log.info("scrape_complete", **{k: v for k, v in summary.items() if k != "failed_symbols"})
    return summary


def main() -> None:
    import argparse

    from analyzer.jobs.ingest import open_repo

    configure_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=800)
    args = ap.parse_args()

    repo = open_repo()
    try:
        summary = run_scrape(repo, limit=args.limit)
    finally:
        repo.close()
    print(f"\nEXP-002 scrape: {summary['ok']}/{summary['requested']} symbols OK, "
          f"{summary['rows']:,} rows. Failed sample: {summary['failed_symbols']}")


if __name__ == "__main__":
    main()
