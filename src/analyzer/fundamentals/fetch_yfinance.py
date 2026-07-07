"""Fundamentals fetcher via yfinance (PLAN 2.1 fallback source).

Maps yfinance's raw data into the ``FundamentalInputs`` contract. yfinance's
Indian fundamental coverage is patchy and some fields are proxies (e.g.
heldPercentInsiders as a promoter-holding stand-in), so this is the FALLBACK
source; Screener.in consolidated data is preferred where available (fetch_screener).

All access is wrapped defensively — any missing field becomes None and the
scoring layer degrades gracefully.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from analyzer.fundamentals.models import FundamentalInputs
from analyzer.fundamentals.ratios import cagr, count_positive, is_declining, safe_ratio, yoy_growth
from analyzer.logging_setup import get_logger

log = get_logger(__name__)

_FINANCIAL_SECTORS = {"financial services", "financial", "banks"}


def _ticker(symbol: str):
    import yfinance as yf

    from analyzer.config import get_config

    return yf.Ticker(f"{symbol}{get_config().ingestion.yfinance_suffix_nse}")


def _row(df: pd.DataFrame | None, *names: str) -> pd.Series | None:
    """Fetch a statement line by trying several possible row labels (yfinance
    label drift). Returns the row as a Series (newest-first columns) or None."""
    if df is None or df.empty:
        return None
    idx = {str(i).lower(): i for i in df.index}
    for name in names:
        key = name.lower()
        if key in idx:
            return df.loc[idx[key]]
    return None


def _oldest_first(series: pd.Series | None) -> list[float | None]:
    """yfinance statement columns are newest-first; return values oldest-first."""
    if series is None:
        return []
    vals = list(series.values)[::-1]
    out: list[float | None] = []
    for v in vals:
        try:
            out.append(None if pd.isna(v) else float(v))
        except (TypeError, ValueError):
            out.append(None)
    return out


def build_inputs_from_yfinance(symbol: str) -> FundamentalInputs:
    fi = FundamentalInputs(symbol=symbol, source="yfinance")
    try:
        tk = _ticker(symbol)
    except Exception as exc:  # noqa: BLE001
        log.warning("yf_ticker_failed", symbol=symbol, error=str(exc))
        return fi

    info: dict = {}
    try:
        info = tk.info or {}
    except Exception as exc:  # noqa: BLE001
        log.warning("yf_info_failed", symbol=symbol, error=str(exc))

    sector = str(info.get("sector", "")).lower()
    industry = str(info.get("industry", "")).lower()
    fi.is_financial = sector in _FINANCIAL_SECTORS or "bank" in industry

    def pct(key: str) -> float | None:
        v = info.get(key)
        return float(v) * 100.0 if isinstance(v, (int, float)) else None

    fi.roe = pct("returnOnEquity")
    fi.roa = pct("returnOnAssets")
    de = info.get("debtToEquity")
    fi.debt_equity = float(de) / 100.0 if isinstance(de, (int, float)) else None
    fi.pe = info.get("trailingPE") if isinstance(info.get("trailingPE"), (int, float)) else None
    ev = info.get("enterpriseToEbitda")
    fi.ev_ebitda = float(ev) if isinstance(ev, (int, float)) else None
    fi.promoter_pct = pct("heldPercentInsiders")  # proxy; real value needs SHP data

    # --- annual statements: growth, earnings quality, coverage ---------------
    try:
        income = tk.income_stmt
    except Exception:  # noqa: BLE001
        income = None
    try:
        cashflow = tk.cashflow
    except Exception:  # noqa: BLE001
        cashflow = None

    revenue = _oldest_first(_row(income, "Total Revenue", "TotalRevenue", "Operating Revenue"))
    net_income = _oldest_first(_row(income, "Net Income", "NetIncome"))
    ebitda = _oldest_first(_row(income, "EBITDA", "Normalized EBITDA"))
    ebit = _oldest_first(_row(income, "EBIT", "Operating Income"))
    interest = _oldest_first(_row(income, "Interest Expense", "Interest Expense Non Operating"))
    cfo = _oldest_first(_row(cashflow, "Operating Cash Flow", "Total Cash From Operating Activities"))
    fcf = _oldest_first(_row(cashflow, "Free Cash Flow"))

    fi.net_profit_history = [v for v in net_income if v is not None][-3:]

    if len(revenue) >= 2:
        yrs = len(revenue) - 1
        fi.sales_cagr_3yr = cagr(revenue[0], revenue[-1], yrs)
    if len(net_income) >= 2:
        fi.eps_growth_ttm_yoy = yoy_growth(net_income[-2], net_income[-1])

    if ebitda and cfo:
        ratios = [safe_ratio(c, e) for c, e in zip(cfo[-3:], ebitda[-3:]) if e]
        ratios = [r for r in ratios if r is not None]
        if ratios:
            fi.cfo_ebitda_3yr = sum(ratios) / len(ratios)
    if fcf:
        fi.fcf_positive_years = count_positive(fcf[-3:])

    if ebit and interest:
        latest_ebit, latest_int = ebit[-1], interest[-1]
        if latest_ebit is not None and latest_int:
            fi.interest_coverage = abs(latest_ebit) / abs(latest_int)

    # Debt trend from balance sheet (declining is a bonus).
    try:
        bs = tk.balance_sheet
        debt = _oldest_first(_row(bs, "Total Debt", "Long Term Debt"))
        fi.debt_trend_declining = is_declining(debt)
    except Exception:  # noqa: BLE001
        pass

    log.debug("yf_inputs_built", symbol=symbol, financial=fi.is_financial)
    return fi


def snapshot_row(fi: FundamentalInputs) -> dict:
    """Flatten inputs into a ``fundamentals`` table row (period = 'TTM')."""
    return {
        "symbol": fi.symbol,
        "period": "TTM",
        "net_profit": fi.net_profit_history[-1] if fi.net_profit_history else None,
        "debt": None,
        "equity": None,
        "roe": fi.roe,
        "roce": fi.roce,
        "interest_coverage": fi.interest_coverage,
        "promoter_pct": fi.promoter_pct,
        "pledge_pct": fi.pledge_pct,
        "fii_pct": None,
        "dii_pct": None,
        "pe": fi.pe,
        "ev_ebitda": fi.ev_ebitda,
        "source": fi.source,
        "fetched_at": datetime.now(),
    }
