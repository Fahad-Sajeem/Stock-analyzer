"""Compute the full indicator set for the universe into ``indicators_daily``.

Per-symbol indicators are vectorized column ops; the relative-strength percentile
is cross-sectional (ranked across all symbols per date). Reads ADJUSTED prices;
delivery% is joined from the raw table.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analyzer.config import Config, get_config
from analyzer.logging_setup import get_logger
from analyzer.technicals import indicators as ind
from analyzer.technicals import structure as struct

log = get_logger(__name__)


def _weekly_gate(df: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Weekly multi-timeframe gate flags mapped back to daily rows (PLAN 7.6)."""
    t = cfg.technicals
    wk_ema_n = t.get("weekly_ema", 10)
    wk_sma_n = t.get("weekly_sma", 40)

    # ``df`` is already sorted ascending by date (caller guarantees it).
    dates = pd.to_datetime(df["date"])
    s = pd.Series(df["close"].values, index=dates)
    weekly = s.resample("W-FRI").last().dropna()
    if len(weekly) < 5:
        return pd.DataFrame(
            {"wk_gate_trend": [False] * len(df), "wk_gate_mr": [False] * len(df)}
        )
    wk_ema = weekly.ewm(span=wk_ema_n, adjust=False).mean()
    wk_sma = weekly.rolling(wk_sma_n, min_periods=1).mean()
    gate_trend = (weekly > wk_ema) & (wk_ema >= wk_ema.shift(4))
    gate_mr = weekly > wk_sma

    wk = pd.DataFrame(
        {"week": weekly.index, "wk_gate_trend": gate_trend.values, "wk_gate_mr": gate_mr.values}
    )
    # Map each daily bar to the most recent COMPLETED week's flags (no look-ahead).
    daily = pd.DataFrame({"date": dates.values})
    merged = pd.merge_asof(
        daily, wk.sort_values("week"),
        left_on="date", right_on="week", direction="backward",
    )
    return pd.DataFrame(
        {
            "wk_gate_trend": merged["wk_gate_trend"].fillna(False).astype(bool).values,
            "wk_gate_mr": merged["wk_gate_mr"].fillna(False).astype(bool).values,
        }
    )


def compute_symbol_indicators(df: pd.DataFrame, cfg: Config | None = None) -> pd.DataFrame:
    """Compute all per-symbol indicators for one symbol's OHLCV frame.

    ``df`` columns: symbol, date, open, high, low, close, volume, delivery_pct.
    Returns an ``indicators_daily``-shaped frame (minus rs_pctile, set later).
    """
    cfg = cfg or get_config()
    t = cfg.technicals
    df = df.sort_values("date").reset_index(drop=True)
    close, high, low = df["close"], df["high"], df["low"]
    vol = df["volume"].astype("float64")

    macd_line, macd_sig, macd_hist = ind.macd(close, *t.get("macd", [12, 26, 9]))
    adx_s, _pdi, _mdi = ind.adx(high, low, close, t.get("adx_period", 14))
    atr_s = ind.atr(high, low, close, t.get("atr_period", 14))
    _mid, _up, _lo, bb_width = ind.bollinger(close, *_bb(t))
    in_base, base_days = struct.detect_base(
        high, low, close, t.get("base_min_days", 15), t.get("base_max_range_pct", 12.0)
    )
    vol_avg = vol.rolling(t.get("vol_avg_period", 20), min_periods=5).mean()

    out = pd.DataFrame({"symbol": df["symbol"], "date": df["date"]})
    out["ema20"] = ind.ema(close, t.get("ema_fast", 20))
    out["ema50"] = ind.ema(close, t.get("ema_mid", 50))
    out["sma200"] = ind.sma(close, t.get("sma_slow", 200))
    out["adx"] = adx_s
    out["rsi"] = ind.rsi(close, t.get("rsi_period", 14))
    out["macd"] = macd_line
    out["macd_sig"] = macd_sig
    out["macd_hist"] = macd_hist
    out["atr"] = atr_s
    out["atr_pct"] = atr_s / close * 100.0
    out["bb_width_pctile"] = ind.rolling_percentile(bb_width, 252)
    out["vol_ratio"] = vol / vol_avg
    out["obv_slope"] = ind.slope(ind.obv(close, vol), 20)
    roc_p = t.get("roc_periods", [20, 60, 120])
    out["roc20"] = ind.roc(close, roc_p[0])
    out["roc60"] = ind.roc(close, roc_p[1])
    out["roc120"] = ind.roc(close, roc_p[2])
    out["dist_52wh"] = struct.dist_to_52w_high(close, high)
    out["supertrend"] = ind.supertrend(high, low, close, *t.get("supertrend", [10, 3]))
    out["in_base"] = in_base.fillna(False).astype(bool)
    out["base_days"] = base_days.astype(int)
    # rs_return is the raw n-day return used cross-sectionally later.
    out["_rs_return"] = ind.roc(close, t.get("rs_lookback_days", 63))

    gate = _weekly_gate(df, cfg)
    out["wk_gate_trend"] = gate["wk_gate_trend"].values
    out["wk_gate_mr"] = gate["wk_gate_mr"].values
    return out


def _bb(t: dict) -> tuple[int, float]:
    bb = t.get("bb", [20, 2])
    return int(bb[0]), float(bb[1])


def compute_relative_strength(
    all_ind: pd.DataFrame, index_rs_return: pd.Series
) -> pd.Series:
    """Cross-sectional RS percentile (0-100) per date.

    RS = stock n-day return − index n-day return; percentile-ranked across all
    symbols on each date. ``index_rs_return`` is indexed by date.
    """
    df = all_ind[["symbol", "date", "_rs_return"]].copy()
    df["date_ts"] = pd.to_datetime(df["date"])
    idx = index_rs_return.copy()
    idx.index = pd.to_datetime(idx.index)
    df["idx_ret"] = df["date_ts"].map(idx)
    df["rs_raw"] = df["_rs_return"] - df["idx_ret"].fillna(0.0)
    df["rs_pctile"] = df.groupby("date")["rs_raw"].rank(pct=True) * 100.0
    return df["rs_pctile"]


# Trailing bars loaded per symbol in incremental mode. Chosen so every indicator
# is exact or numerically converged within the window: SMA200/52wk-high/roc120/
# bb_width_pctile(252) are exact; EMA/RMA initial-condition decay after 420 bars
# is < 1e-7; the weekly 40-SMA gate needs ~200 bars. Only base_days (run length)
# can be truncated for bases longer than the window — practically irrelevant.
_INCR_WINDOW_BARS = 420
_INCR_OVERLAP_DAYS = 5


def run_compute_indicators(
    repo, cfg: Config | None = None, incremental: bool = False
) -> int:
    """Compute indicators -> indicators_daily.

    ``incremental=True`` (nightly mode): loads only the trailing window per
    symbol and upserts just the dates newer than the last computed date (minus
    a small overlap). Cuts peak RAM ~10x and runtime to seconds; falls back to
    a full run automatically when the table is empty.
    """
    cfg = cfg or get_config()

    cutoff = None
    if incremental:
        last_ind = repo.scalar("SELECT MAX(date) FROM indicators_daily")
        if last_ind is None:
            incremental = False  # nothing computed yet -> full run
        else:
            last_d = last_ind.date() if hasattr(last_ind, "date") else last_ind
            cutoff = last_d - pd.Timedelta(days=_INCR_OVERLAP_DAYS).to_pytimedelta()

    with repo.job_run("compute_indicators" + (":incr" if incremental else "")) as jr:
        window_clause = (
            f"QUALIFY ROW_NUMBER() OVER (PARTITION BY a.symbol ORDER BY a.date DESC) "
            f"<= {_INCR_WINDOW_BARS}" if incremental else ""
        )
        prices = repo.query_df(
            f"""
            SELECT a.symbol, a.date, a.open, a.high, a.low, a.close, a.volume,
                   r.delivery_pct
            FROM prices_adj a
            LEFT JOIN prices_raw r ON r.symbol = a.symbol AND r.date = a.date
            {window_clause}
            ORDER BY a.symbol, a.date
            """
        )
        if prices.empty:
            log.warning("no_adjusted_prices")
            return 0

        frames = []
        for _sym, grp in prices.groupby("symbol"):
            if len(grp) < 30:  # too short to compute anything meaningful
                continue
            frames.append(compute_symbol_indicators(grp, cfg))
        if not frames:
            return 0
        all_ind = pd.concat(frames, ignore_index=True)

        if incremental and cutoff is not None:
            all_ind = all_ind[pd.to_datetime(all_ind["date"]).dt.date > cutoff]
            if all_ind.empty:
                log.info("indicators_incremental_nothing_new", cutoff=str(cutoff))
                return 0

        # Cross-sectional relative strength vs Nifty 500.
        idx = repo.query_df(
            "SELECT date, close FROM index_prices WHERE index_name = 'NIFTY500' ORDER BY date"
        )
        if idx.empty:
            idx = repo.query_df(
                "SELECT date, close FROM index_prices WHERE index_name = 'NIFTY50' ORDER BY date"
            )
        if not idx.empty:
            iser = pd.Series(idx["close"].values, index=pd.to_datetime(idx["date"]))
            index_rs_return = (iser / iser.shift(cfg.technicals.get("rs_lookback_days", 63)) - 1) * 100
            all_ind["rs_pctile"] = compute_relative_strength(all_ind, index_rs_return).values
        else:
            all_ind["rs_pctile"] = np.nan

        all_ind = all_ind.drop(columns=["_rs_return"])
        n = repo.upsert_df("indicators_daily", all_ind)
        jr.add_rows(n)
    log.info("indicators_computed", rows=n, symbols=all_ind["symbol"].nunique())
    return n
