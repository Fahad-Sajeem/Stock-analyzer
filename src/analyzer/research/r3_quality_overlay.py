"""EXP-003 (R3) — quality overlay experiments. DEV window only.

(a) Momentum portfolio restricted to point-in-time quality-gated names,
    vs the EXP-001 momentum-plain baseline (same benchmark).
(b) Setups A/B/D with a quality gate applied at signal date, vs ungated.

Config/hypotheses are registered in RESEARCH_LOG.md EXP-003 before running.

Run:  .venv/Scripts/python.exe -m analyzer.research.r3_quality_overlay
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from analyzer.backtest.metrics import compute_metrics
from analyzer.backtest.runner import run_backtest
from analyzer.config import get_config
from analyzer.logging_setup import configure_logging, get_logger
from analyzer.research.momentum import (
    MomentumConfig,
    load_panels,
    month_end_positions,
    run_momentum,
)
from analyzer.research.quality_panel import build_quality_panel
from analyzer.setups.base import SETUP_A, SETUP_B, SETUP_D

log = get_logger(__name__)


def _quality_sets_for_dates(repo, dates: list[pd.Timestamp]) -> dict:
    panel = build_quality_panel(repo, [d.date() for d in dates])
    out: dict = {}
    for d, grp in panel.groupby("date"):
        out[d] = set(grp[grp["quality_ok"]]["symbol"])
    return out


def run_exp_003a(repo) -> dict:
    """Momentum with quality gate vs plain (both costs-on, same benchmark)."""
    cfg = MomentumConfig()
    close, tv, nifty, nifty_dma = load_panels(repo)
    dates = close.index
    me_pos = [
        i for i in month_end_positions(dates)
        if i >= cfg.lookback_12m and cfg.dev_start <= dates[i].date() <= cfg.dev_end
    ]
    rebalance_dates = [dates[i] for i in me_pos]
    quality_sets = _quality_sets_for_dates(repo, rebalance_dates)
    avg_pass = sum(len(s) for s in quality_sets.values()) / max(len(quality_sets), 1)
    log.info("quality_sets_ready", dates=len(quality_sets), avg_passing=int(avg_pass))

    plain = run_momentum(close, tv, nifty, nifty_dma, cfg)
    gated = run_momentum(close, tv, nifty, nifty_dma, cfg, quality_sets=quality_sets)
    return {
        "avg_quality_passing": int(avg_pass),
        "momentum_plain": plain["stats"]["momentum_plain"],
        "momentum_quality": gated["stats"]["momentum_plain"],  # same variant key, gated universe
        "benchmark_ew": plain["stats"]["benchmark_ew_universe"],
    }


def run_exp_003b(repo) -> dict:
    """Setups A/B/D with vs without the quality gate at signal date (DEV)."""
    cfg = get_config()
    bt = cfg.backtest
    dev_start = datetime.strptime(bt["in_sample"][0], "%Y-%m-%d").date()
    dev_end = date(2023, 12, 31)

    # Monthly as-of quality sets; a signal uses the latest month-end <= its date.
    month_ends = pd.date_range(date(2017, 1, 1), dev_end, freq="ME")
    quality_sets = _quality_sets_for_dates(repo, list(month_ends))
    sorted_keys = sorted(quality_sets.keys())

    def signal_filter(symbol: str, sig_date) -> bool:
        ts = pd.Timestamp(sig_date)
        # latest month-end snapshot at or before the signal date
        idx = pd.Index(sorted_keys).searchsorted(ts, side="right") - 1
        if idx < 0:
            return False
        return symbol in quality_sets[sorted_keys[idx]]

    setups = [SETUP_A, SETUP_B, SETUP_D]
    out: dict = {}
    frames_cache: dict = {}
    for label, filt in [("ungated", None), ("quality_gated", signal_filter)]:
        trades = run_backtest(
            repo, cfg, setups=setups, start=dev_start, end=dev_end,
            signal_filter=filt, frames_cache=frames_cache,
        )
        out[label] = {
            s: compute_metrics(t, dev_start, dev_end) if not t.empty else {"n_trades": 0}
            for s, t in trades.items()
        }
    return out


def main() -> None:
    from analyzer.jobs.ingest import open_repo

    configure_logging()
    repo = open_repo()
    try:
        print("=== EXP-003a: momentum + quality gate (DEV) ===")
        a = run_exp_003a(repo)
        print(f"avg names passing quality gate/rebalance: {a['avg_quality_passing']}")
        for k in ("momentum_plain", "momentum_quality", "benchmark_ew"):
            print(f"{k:20s} {a[k]}")

        print("\n=== EXP-003b: setups with quality gate at signal date (DEV) ===")
        b = run_exp_003b(repo)
        for setup in b["ungated"]:
            u, g = b["ungated"][setup], b["quality_gated"][setup]
            print(f"{setup:24s} ungated: n={u.get('n_trades',0):4} pf={u.get('profit_factor')} "
                  f"exp={u.get('expectancy_r')}  |  gated: n={g.get('n_trades',0):4} "
                  f"pf={g.get('profit_factor')} exp={g.get('expectancy_r')}")
    finally:
        repo.close()


if __name__ == "__main__":
    main()
