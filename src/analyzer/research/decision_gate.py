"""DECISION GATE — the three registered HOLDOUT evaluations (2024-01-01..2026-06-30).

Pre-registered in RESEARCH_LOG.md before execution. This spends the ENTIRE
holdout budget (contract R-1). Do not re-run with modified parameters; the
window is burned after this.

Run:  .venv/Scripts/python.exe -m analyzer.research.decision_gate
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from analyzer.backtest.metrics import compute_metrics
from analyzer.backtest.runner import _load_symbol_frame, run_backtest
from analyzer.config import get_config
from analyzer.logging_setup import configure_logging, get_logger
from analyzer.research.momentum import MomentumConfig, load_panels, month_end_positions, run_momentum
from analyzer.research.quality_panel import load_history
from analyzer.research.r3_quality_overlay import _quality_sets_for_dates
from analyzer.research.r4_pead import inject_results_flag
from analyzer.setups.base import SETUP_A, SETUP_E

log = get_logger(__name__)

HOLDOUT_START = date(2024, 1, 1)
HOLDOUT_END = date(2026, 6, 30)


def _quality_filter_factory(quality_sets: dict):
    keys = sorted(quality_sets.keys())
    idx = pd.Index(keys)

    def quality_filter(symbol: str, d) -> bool:
        i = idx.searchsorted(pd.Timestamp(d), side="right") - 1
        return i >= 0 and symbol in quality_sets[keys[i]]

    return quality_filter


def holdout_1_momentum(repo) -> dict:
    """Quality-gated momentum portfolio over the holdout window."""
    cfg = MomentumConfig(dev_start=HOLDOUT_START, dev_end=HOLDOUT_END)
    close, tv, nifty, nifty_dma = load_panels(repo)
    dates = close.index
    me_pos = [
        i for i in month_end_positions(dates)
        if i >= cfg.lookback_12m and HOLDOUT_START <= dates[i].date() <= HOLDOUT_END
    ]
    rebalance_dates = [dates[i] for i in me_pos]
    quality_sets = _quality_sets_for_dates(repo, rebalance_dates)

    gated = run_momentum(close, tv, nifty, nifty_dma, cfg, quality_sets=quality_sets)
    return {
        "strategy": gated["stats"]["momentum_plain"],
        "benchmark_ew": gated["stats"]["benchmark_ew_universe"],
        "nifty50": gated["stats"]["nifty50"],
    }


def holdout_2_breakout(repo, quality_filter, frames_cache: dict) -> dict:
    cfg = get_config()
    trades = run_backtest(
        repo, cfg, setups=[SETUP_A], start=HOLDOUT_START, end=HOLDOUT_END,
        signal_filter=quality_filter, frames_cache=frames_cache,
    )[SETUP_A]
    return compute_metrics(trades, HOLDOUT_START, HOLDOUT_END) if not trades.empty else {"n_trades": 0}


def holdout_3_pead(repo, quality_filter, frames: dict) -> dict:
    cfg = get_config()
    plain = run_backtest(
        repo, cfg, setups=[SETUP_E], start=HOLDOUT_START, end=HOLDOUT_END,
        symbols=list(frames.keys()), frames_cache=frames,
    )[SETUP_E]
    gated = run_backtest(
        repo, cfg, setups=[SETUP_E], start=HOLDOUT_START, end=HOLDOUT_END,
        symbols=list(frames.keys()), frames_cache=frames, signal_filter=quality_filter,
    )[SETUP_E]
    return {
        "pead_plain_PRIMARY": compute_metrics(plain, HOLDOUT_START, HOLDOUT_END)
        if not plain.empty else {"n_trades": 0},
        "pead_quality_descriptive": compute_metrics(gated, HOLDOUT_START, HOLDOUT_END)
        if not gated.empty else {"n_trades": 0},
    }


def main() -> None:
    from analyzer.jobs.ingest import open_repo

    configure_logging()
    repo = open_repo()
    try:
        # Shared prep: quality sets (monthly) + PEAD frames with results flag.
        month_ends = pd.date_range(date(2023, 6, 30), HOLDOUT_END, freq="ME")
        quality_sets = _quality_sets_for_dates(repo, list(month_ends))
        quality_filter = _quality_filter_factory(quality_sets)

        cal = repo.query_df("SELECT symbol, announce_date FROM results_calendar")
        cal["announce_date"] = pd.to_datetime(cal["announce_date"]).dt.date
        ann_by_symbol = {s: set(g["announce_date"]) for s, g in cal.groupby("symbol")}
        symbols = repo.query_df(
            "SELECT DISTINCT symbol FROM indicators_daily"
        )["symbol"].tolist()
        frames: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            ann = ann_by_symbol.get(sym)
            if not ann:
                continue
            f = _load_symbol_frame(repo, sym)
            if len(f) >= 260:
                frames[sym] = inject_results_flag(f, ann)
        log.info("gate_prep_done", frames=len(frames), quality_dates=len(quality_sets))

        print(f"\n=========== DECISION GATE (HOLDOUT {HOLDOUT_START}..{HOLDOUT_END}) ===========")

        print("\n--- HOLDOUT-1: quality-gated momentum portfolio ---")
        h1 = holdout_1_momentum(repo)
        for k, v in h1.items():
            print(f"  {k:14s} {v}")

        print("\n--- HOLDOUT-2: quality-gated Setup-A breakout ---")
        h2 = holdout_2_breakout(repo, quality_filter, frames)
        print(f"  {h2}")

        print("\n--- HOLDOUT-3: PEAD (plain = PRIMARY) ---")
        h3 = holdout_3_pead(repo, quality_filter, frames)
        for k, v in h3.items():
            print(f"  {k:26s} {v}")

        # Provisional pass/fail per the registered definitions.
        print("\n=========== VERDICTS (per pre-registered definitions) ===========")
        s, b = h1["strategy"], h1["benchmark_ew"]
        v1 = (s.get("cagr_pct", -99) > b.get("cagr_pct", 0)
              and s.get("sharpe", 0) > b.get("sharpe", 0)
              and s.get("max_dd_pct", 100) < 25)
        print(f"  HOLDOUT-1 momentum+quality : {'PROVISIONAL PASS' if v1 else 'FAIL'}")

        v2 = (h2.get("profit_factor", 0) >= 1.5 and h2.get("expectancy_r", 0) > 0.10
              and h2.get("max_dd_pct", 100) < 25)
        print(f"  HOLDOUT-2 breakout+quality : {'PROVISIONAL PASS' if v2 else 'FAIL'} "
              f"(n={h2.get('n_trades', 0)})")

        p = h3["pead_plain_PRIMARY"]
        v3 = (p.get("profit_factor", 0) >= 1.5 and p.get("expectancy_r", 0) > 0.10
              and p.get("max_dd_pct", 100) < 25)
        print(f"  HOLDOUT-3 PEAD             : {'PROVISIONAL PASS' if v3 else 'FAIL'} "
              f"(n={p.get('n_trades', 0)})")
    finally:
        repo.close()


if __name__ == "__main__":
    main()
