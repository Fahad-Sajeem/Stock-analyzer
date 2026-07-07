"""Fundamentals fetcher via Screener.in (PLAN 2.1 preferred source).

Screener has no public API. This adapter fetches the company page and parses the
stable ``#top-ratios`` block (Market Cap, P/E, ROCE, ROE, Debt, etc.). Deep
financial history requires a logged-in export and is left for a later iteration;
until then yfinance (fetch_yfinance) fills the gaps.

Everything Screener-specific is isolated here so that when the site's HTML changes
(it will), this is the only file to fix. Prefer the CONSOLIDATED page.
"""

from __future__ import annotations

import re

import requests

from analyzer.config import get_config
from analyzer.fundamentals.models import FundamentalInputs
from analyzer.logging_setup import get_logger

log = get_logger(__name__)

_BASE = "https://www.screener.in"


def company_url(symbol: str, consolidated: bool = True) -> str:
    suffix = "consolidated/" if consolidated else ""
    return f"{_BASE}/company/{symbol}/{suffix}"


def _to_number(text: str) -> float | None:
    """'₹ 1,650 Cr.' / '18.5 %' / '1.23' -> float; None if not numeric."""
    if not text:
        return None
    cleaned = re.sub(r"[^0-9.\-]", "", text.replace(",", ""))
    if cleaned in ("", "-", ".", "-."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_top_ratios(html: str) -> dict[str, float | None]:
    """Parse the ``#top-ratios`` list into {ratio_name: value}.

    Depends only on the ``<li><span class="name">…</span> … <span class="number">
    …</span>`` structure, which is the most stable part of the page.
    """
    ratios: dict[str, float | None] = {}
    block = re.search(r'id="top-ratios".*?</ul>', html, re.DOTALL)
    scope = block.group(0) if block else html
    for li in re.findall(r"<li\b.*?</li>", scope, re.DOTALL):
        name_m = re.search(r'class="name"[^>]*>(.*?)</span>', li, re.DOTALL)
        if not name_m:
            continue
        name = re.sub(r"<[^>]+>", "", name_m.group(1)).strip()
        nums = re.findall(r'class="number"[^>]*>(.*?)</span>', li, re.DOTALL)
        value = _to_number(nums[0]) if nums else None
        ratios[name] = value
    return ratios


def fetch_top_ratios(symbol: str, consolidated: bool = True, session=None) -> dict[str, float | None]:
    cfg = get_config()
    session = session or requests.Session()
    session.headers.setdefault("User-Agent", cfg.ingestion.user_agent)
    url = company_url(symbol, consolidated)
    try:
        resp = session.get(url, timeout=cfg.ingestion.request_timeout_sec)
        if resp.status_code != 200 and consolidated:
            # Fall back to standalone if consolidated page is absent.
            resp = session.get(company_url(symbol, False), timeout=cfg.ingestion.request_timeout_sec)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("screener_fetch_failed", symbol=symbol, error=str(exc))
        return {}
    return parse_top_ratios(resp.text)


def merge_top_ratios(fi: FundamentalInputs, ratios: dict[str, float | None]) -> FundamentalInputs:
    """Overlay Screener top-ratios onto an existing inputs object (Screener wins
    where present — it's the preferred source for Indian names)."""
    def g(*names: str) -> float | None:
        for n in names:
            if n in ratios and ratios[n] is not None:
                return ratios[n]
        return None

    fi.roce = g("ROCE", "ROCE %") or fi.roce
    fi.roe = g("ROE", "ROE %") or fi.roe
    fi.pe = g("Stock P/E", "P/E") or fi.pe
    # Screener 'Debt to equity' if exposed in top-ratios of some pages.
    de = g("Debt to equity")
    if de is not None:
        fi.debt_equity = de
    if fi.source == "yfinance":
        fi.source = "screener+yfinance"
    else:
        fi.source = "screener"
    return fi
