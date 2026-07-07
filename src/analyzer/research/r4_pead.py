"""EXP-004 (R4) — PEAD backtest with real NSE announcement dates. DEV only.

Variants (registered in RESEARCH_LOG.md EXP-004):
  004a  Setup E on price/volume reaction alone
  004b  004a + EXP-003 frozen quality gate at signal date
  004c  004a + quarterly fundamental confirmation (net-profit YoY >= 25% or
        sales YoY >= 10% for the just-reported quarter)

Run:  .venv/Scripts/python.exe -m analyzer.research.r4_pead
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pandas as pd

from analyzer.backtest.metrics import compute_metrics
from analyzer.backtest.runner import _load_symbol_frame, run_backtest
from analyzer.config import get_config
from analyzer.logging_setup import configure_logging, get_logger
from analyzer.setups.base import SETUP_E

log = get_logger(__name__)

DEV_END = date(2023, 12, 31)


# --------------------------------------------------------------------------
# pure helpers (unit-testable)
# --------------------------------------------------------------------------

def inject_results_flag(df: pd.DataFrame, announce_dates: set[date]) -> pd.DataFrame:
    """Mark announce day AND the following session as results-reaction candidates
    (results often land after market close -> reaction is the next session)."""
    out = df.copy()
    dts = pd.to_datetime(out["date"]).dt.date
    on_day = dts.isin(announce_dates)
    next_day = on_day.shift(1, fill_value=False)
    out["results_recent"] = (on_day | next_day).to_numpy()
    return out


def build_yoy_confirm(hist: pd.DataFrame):
    """Return confirm(symbol, sig_date) -> bool from quarterly fundamentals.

    Confirms if the just-reported quarter (latest Q period_end within 75 days
    before the signal) shows net-profit YoY >= 25% or sales YoY >= 10%.
    """
    q = hist[(hist.freq == "Q") & (hist.metric.isin(["net_profit", "sales"]))]
    per_symbol: dict[str, pd.DataFrame] = {
        sym: g.pivot_table(index="period_end", columns="metric", values="value")
        for sym, g in q.groupby("symbol")
    }

    def confirm(symbol: str, sig_date) -> bool:
        tbl = per_symbol.get(symbol)
        if tbl is None or tbl.empty:
            return False
        ts = pd.Timestamp(sig_date)
        recent = tbl[(tbl.index <= ts) & (tbl.index >= ts - pd.Timedelta(days=75))]
        if recent.empty:
            return False
        pe = recent.index[-1]
        prior_win = tbl[(tbl.index >= pe - pd.Timedelta(days=380))
                        & (tbl.index <= pe - pd.Timedelta(days=350))]
        if prior_win.empty:
            return False
        cur, prev = recent.iloc[-1], prior_win.iloc[-1]
        np_ok = (
            pd.notna(cur.get("net_profit")) and pd.notna(prev.get("net_profit"))
            and prev["net_profit"] != 0
            and (cur["net_profit"] - prev["net_profit"]) / abs(prev["net_profit"]) >= 0.25
        )
        sales_ok = (
            pd.notna(cur.get("sales")) and pd.notna(prev.get("sales"))
            and prev["sales"] > 0
            and (cur["sales"] - prev["sales"]) / prev["sales"] >= 0.10
        )
        return bool(np_ok or sales_ok)

    return confirm


# --------------------------------------------------------------------------
# experiment
# --------------------------------------------------------------------------

def main() -> None:
    from analyzer.jobs.ingest import open_repo
    from analyzer.research.quality_panel import load_history
    from analyzer.research.r3_quality_overlay import _quality_sets_for_dates

    configure_logging()
    cfg = get_config()
    dev_start = datetime.strptime(cfg.backtest["in_sample"][0], "%Y-%m-%d").date()

    repo = open_repo()
    try:
        cal = repo.query_df("SELECT symbol, announce_date FROM results_calendar")
        if cal.empty:
            raise RuntimeError("results_calendar empty — run results_calendar ingest first")
        cal["announce_date"] = pd.to_datetime(cal["announce_date"]).dt.date
        ann_by_symbol = {s: set(g["announce_date"]) for s, g in cal.groupby("symbol")}
        print(f"calendar: {len(cal):,} announcements, {len(ann_by_symbol)} symbols")

        # Pre-build frames with the results_recent flag injected (only symbols
        # that have announcements AND indicators).
        symbols = repo.query_df(
            "SELECT DISTINCT symbol FROM indicators_daily ORDER BY symbol"
        )["symbol"].tolist()
        frames: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            ann = ann_by_symbol.get(sym)
            if not ann:
                continue
            f = _load_symbol_frame(repo, sym)
            if len(f) < 260:
                continue
            frames[sym] = inject_results_flag(f, ann)
        print(f"frames with results flag: {len(frames)}")

        # Quality gate sets (EXP-003 frozen definition) for 004b.
        month_ends = pd.date_range(date(2017, 1, 1), DEV_END, freq="ME")
        quality_sets = _quality_sets_for_dates(repo, list(month_ends))
        keys = sorted(quality_sets.keys())

        def quality_filter(symbol: str, d) -> bool:
            ts = pd.Timestamp(d)
            i = pd.Index(keys).searchsorted(ts, side="right") - 1
            return i >= 0 and symbol in quality_sets[keys[i]]

        # YoY confirmation for 004c.
        confirm = build_yoy_confirm(load_history(repo))

        variants = [
            ("004a_plain", None),
            ("004b_quality", quality_filter),
            ("004c_yoy_confirm", lambda s, d: confirm(s, d)),
        ]
        print(f"\nEXP-004 PEAD (DEV {dev_start}..{DEV_END}):")
        for label, filt in variants:
            trades = run_backtest(
                repo, cfg, setups=[SETUP_E], start=dev_start, end=DEV_END,
                symbols=list(frames.keys()), frames_cache=frames, signal_filter=filt,
            )[SETUP_E]
            m = compute_metrics(trades, dev_start, DEV_END) if not trades.empty else {"n_trades": 0}
            print(f"  {label:18s} n={m.get('n_trades',0):5} win%={m.get('win_rate')} "
                  f"pf={m.get('profit_factor')} exp={m.get('expectancy_r')}R "
                  f"dd={m.get('max_dd_pct')}%")
    finally:
        repo.close()


if __name__ == "__main__":
    main()
