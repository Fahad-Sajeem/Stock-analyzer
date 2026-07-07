"""Corporate-action price adjustment (PLAN 4.2 pt.3, 16 pt.3).

Technical indicators must run on *adjusted* prices, else every bonus/split
(common in India) fires a false crash signal. This module turns ``prices_raw`` +
``corporate_actions`` into ``prices_adj``.

Adjustment model
----------------
Each split/bonus has a price multiplier ``m`` = post-event price / pre-event
price (e.g. a 1:1 bonus doubles the share count, so ``m = 0.5``). The cumulative
adjustment factor at date ``t`` is the product of ``m`` over all actions whose
ex-date is strictly after ``t``. Adjusted price = raw price × factor; adjusted
volume = raw volume ÷ factor. Prices on/after the latest action have factor 1.0.
"""

from __future__ import annotations

import pandas as pd

from analyzer.logging_setup import get_logger

log = get_logger(__name__)


def price_multiplier(action_type: str, ratio: str | None, value: float | None) -> float:
    """Return the price multiplier ``m`` for one corporate action.

    ratio format 'a:b':
      * BONUS  'a:b'  -> a new shares for every b held -> m = b / (a + b)
      * SPLIT  'a:b'  -> face value a -> b (b < a) i.e. one share becomes a/b
                         shares -> m = b / a
    Dividends do not adjust OHLC in this simple model (return 1.0).
    """
    at = (action_type or "").upper()
    if at == "DIVIDEND":
        return 1.0
    if value and value > 0 and not ratio:
        return float(value)
    if not ratio or ":" not in ratio:
        return 1.0
    a_str, b_str = ratio.split(":", 1)
    try:
        a, b = float(a_str), float(b_str)
    except ValueError:
        return 1.0
    if a <= 0 or b <= 0:
        return 1.0
    if at == "BONUS":
        return b / (a + b)
    if at == "SPLIT":
        # 'a:b' as old:new face value -> share count scales by a/b -> price × b/a
        return b / a
    return 1.0


def adjust_prices(prices: pd.DataFrame, actions: pd.DataFrame) -> pd.DataFrame:
    """Pure function: adjust one symbol's OHLCV for its corporate actions.

    ``prices``  columns: date, open, high, low, close, volume  (one symbol)
    ``actions`` columns: ex_date, action_type, ratio, value
    Returns a frame with adjusted OHLCV + ``adj_factor``.
    """
    p = prices.sort_values("date").reset_index(drop=True).copy()
    p["date"] = pd.to_datetime(p["date"])
    factor = pd.Series(1.0, index=p.index)

    if actions is not None and not actions.empty:
        acts = actions.copy()
        acts["ex_date"] = pd.to_datetime(acts["ex_date"])
        for _, act in acts.iterrows():
            m = price_multiplier(act.get("action_type"), act.get("ratio"), act.get("value"))
            if m == 1.0:
                continue
            # Apply to all bars strictly before the ex-date.
            mask = p["date"] < act["ex_date"]
            factor.loc[mask] *= m

    out = pd.DataFrame(
        {
            "symbol": p["symbol"] if "symbol" in p.columns else None,
            "date": p["date"].dt.date,
            "open": p["open"] * factor,
            "high": p["high"] * factor,
            "low": p["low"] * factor,
            "close": p["close"] * factor,
            "volume": (p["volume"] / factor).round().astype("int64"),
            "adj_factor": factor,
        }
    )
    return out


def rebuild_adjusted(repo, symbols: list[str] | None = None) -> int:
    """Populate ``prices_adj`` from ``prices_raw`` + ``corporate_actions``.

    Fast path: symbols with NO corporate actions (the vast majority on any given
    day) are copied with adj_factor=1.0 in a single set-based SQL statement. Only
    symbols that actually have actions go through the per-symbol Python adjuster.
    """
    where = ""
    params: list = []
    if symbols:
        placeholders = ",".join(["?"] * len(symbols))
        where = f"WHERE symbol IN ({placeholders})"
        params = list(symbols)

    # Which of the requested symbols actually have corporate actions?
    act_where = f"WHERE symbol IN ({','.join(['?'] * len(symbols))})" if symbols else ""
    acted = repo.query_df(
        f"SELECT DISTINCT symbol FROM corporate_actions {act_where}", params if symbols else []
    )
    acted_symbols = set(acted["symbol"]) if not acted.empty else set()

    written = 0

    # --- fast bulk path: no-action symbols copied straight through -----------
    exclude = ""
    bulk_params = list(params)
    if acted_symbols:
        exclude = f"{'AND' if where else 'WHERE'} symbol NOT IN " \
                  f"({','.join(['?'] * len(acted_symbols))})"
        bulk_params = list(params) + list(acted_symbols)
    repo.execute(
        f"INSERT OR REPLACE INTO prices_adj "
        f"(symbol, date, open, high, low, close, volume, adj_factor) "
        f"SELECT symbol, date, open, high, low, close, volume, 1.0 "
        f"FROM prices_raw {where} {exclude}",
        bulk_params,
    )
    written += int(
        repo.scalar(
            f"SELECT COUNT(*) FROM prices_raw {where} {exclude}", bulk_params
        ) or 0
    )

    # --- slow per-symbol path: only symbols with actions ---------------------
    if acted_symbols:
        ph = ",".join(["?"] * len(acted_symbols))
        raw = repo.query_df(
            f"SELECT symbol, date, open, high, low, close, volume FROM prices_raw "
            f"WHERE symbol IN ({ph})",
            list(acted_symbols),
        )
        actions = repo.query_df(
            f"SELECT symbol, ex_date, action_type, ratio, value FROM corporate_actions "
            f"WHERE symbol IN ({ph})",
            list(acted_symbols),
        )
        for sym, grp in raw.groupby("symbol"):
            sym_actions = actions[actions["symbol"] == sym]
            adj = adjust_prices(grp, sym_actions)
            written += repo.upsert_df("prices_adj", adj)

    log.info("adjusted_rebuilt", rows=written, acted_symbols=len(acted_symbols))
    return written
