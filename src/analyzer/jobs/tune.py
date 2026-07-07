"""Parameter tuning harness (PLAN 10.3 pt.1: tune on IN-SAMPLE ONLY).

Evaluates small, coarse per-setup grids over the in-sample window and ranks them.
Deliberately anti-overfitting:
  * grids are small and use round thresholds (no RSI-43.7 nonsense),
  * ranking prefers robust expectancy with a minimum trade count,
  * the OOS window is NEVER touched here — one final OOS validation happens
    separately (jobs/backtest.py) after a config is frozen.

Usage:
    analyzer tune --setup B_pullback_trend
    analyzer tune --setup A_momentum_breakout --limit-symbols 400
"""

from __future__ import annotations

import copy
import itertools
from datetime import datetime

from analyzer.backtest.metrics import compute_metrics
from analyzer.backtest.runner import run_backtest
from analyzer.config import Config, get_config
from analyzer.logging_setup import get_logger
from analyzer.setups.base import SETUP_A, SETUP_B, SETUP_C, SETUP_D

log = get_logger(__name__)

# --- per-setup grids: dotted config path -> candidate values -----------------
# Scan-parameter grids (signal generation). Kept coarse & small on purpose.
GRIDS: dict[str, dict[str, list]] = {
    SETUP_A: {
        "setups.breakout.vol_mult_min": [1.5, 2.0],
        "setups.breakout.rs_pctile_min": [70, 80],
        "setups.breakout.high_lookback": [60, 100],
        "setups.breakout.allowed_regimes": [None, ["BULL"]],
    },
    SETUP_B: {
        "setups.pullback.rs_pctile_min": [60, 70],
        "setups.pullback.adx_min": [20, 25],
        "setups.pullback.allowed_regimes": [None, ["NEUTRAL"], ["BULL", "NEUTRAL"]],
    },
    SETUP_C: {
        "setups.mean_reversion.rsi_max": [30, 35],
        "setups.mean_reversion.allowed_regimes": [None, ["NEUTRAL"]],
    },
    SETUP_D: {
        "setups.squeeze.vol_mult_min": [1.5, 2.0],
        "setups.squeeze.bb_width_pctile_max": [10, 15],
        "setups.squeeze.allowed_regimes": [None, ["BULL"]],
    },
}

# Exit-parameter grid (applied to the best scan combo in a second stage).
EXIT_GRID: dict[str, list] = {
    "signals.t1_r_mult": [1.0, 1.5],
    "signals.t2_r_mult": [2.5, 3.0],
    "signals.time_stop_sessions": [10, 15, 25],
    "signals.atr_stop_mult": [2.0, 2.5],
}

_MIN_IS_TRADES = 80  # combos with fewer in-sample trades are noise -> skipped


def _apply_overrides(cfg: Config, overrides: dict) -> Config:
    """Deep-copy the config and set dotted-path overrides (dict sections only)."""
    new = cfg.model_copy(deep=True)
    for path, value in overrides.items():
        parts = path.split(".")
        node = getattr(new, parts[0])
        for key in parts[1:-1]:
            node = node[key]
        if value is None:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = copy.deepcopy(value)
    return new


def _combos(grid: dict[str, list]) -> list[dict]:
    keys = list(grid.keys())
    return [dict(zip(keys, vals)) for vals in itertools.product(*(grid[k] for k in keys))]


def _score_combo(m: dict) -> float:
    """Ranking score: expectancy weighted by sqrt(n) (robustness over luck)."""
    n = m.get("n_trades", 0)
    if n < _MIN_IS_TRADES:
        return float("-inf")
    return m.get("expectancy_r", -9) * (n ** 0.5)


def run_tuning(
    repo,
    setup: str,
    cfg: Config | None = None,
    limit_symbols: int | None = None,
    include_exit_grid: bool = True,
    apply_weekly_gate: bool = False,
) -> dict:
    """Grid-search one setup over the in-sample window. Returns ranked results."""
    cfg = cfg or get_config()
    bt = cfg.backtest
    is_start = datetime.strptime(bt["in_sample"][0], "%Y-%m-%d").date()
    is_end = datetime.strptime(bt["in_sample"][1], "%Y-%m-%d").date()

    symbols = None
    if limit_symbols:
        # Most-liquid subset (median traded value over available history).
        rows = repo.query_df(
            """
            SELECT symbol, MEDIAN(volume * close) AS mtv
            FROM prices_adj GROUP BY symbol ORDER BY mtv DESC LIMIT ?
            """,
            [limit_symbols],
        )
        symbols = rows["symbol"].tolist()

    frames_cache: dict = {}  # shared across combos — load each symbol frame once

    def evaluate(overrides: dict) -> dict:
        c = _apply_overrides(cfg, overrides)
        trades = run_backtest(
            repo, c, setups=[setup], start=is_start, end=is_end,
            apply_weekly_gate=apply_weekly_gate, symbols=symbols,
            frames_cache=frames_cache,
        )[setup]
        m = compute_metrics(trades, is_start, is_end) if not trades.empty else {"n_trades": 0}
        return {"overrides": overrides, "metrics": m, "rank_score": _score_combo(m)}

    # --- stage 1: scan-parameter grid ----------------------------------------
    results = []
    combos = _combos(GRIDS[setup])
    log.info("tuning_stage1", setup=setup, combos=len(combos), symbols=len(symbols or []))
    for i, ov in enumerate(combos, 1):
        r = evaluate(ov)
        results.append(r)
        m = r["metrics"]
        log.info(
            "combo_done", i=i, of=len(combos), n=m.get("n_trades", 0),
            pf=m.get("profit_factor"), exp=m.get("expectancy_r"), ov=str(ov),
        )
    results.sort(key=lambda r: r["rank_score"], reverse=True)
    best_scan = results[0]

    # --- stage 2: exit grid on the best scan combo ---------------------------
    exit_results = []
    if include_exit_grid and best_scan["rank_score"] > float("-inf"):
        exit_combos = _combos(EXIT_GRID)
        log.info("tuning_stage2", setup=setup, combos=len(exit_combos))
        for i, ex in enumerate(exit_combos, 1):
            ov = {**best_scan["overrides"], **ex}
            r = evaluate(ov)
            exit_results.append(r)
            m = r["metrics"]
            log.info(
                "exit_combo_done", i=i, of=len(exit_combos), n=m.get("n_trades", 0),
                pf=m.get("profit_factor"), exp=m.get("expectancy_r"), ov=str(ex),
            )
        exit_results.sort(key=lambda r: r["rank_score"], reverse=True)

    best = exit_results[0] if exit_results and exit_results[0]["rank_score"] >= best_scan[
        "rank_score"
    ] else best_scan
    return {
        "setup": setup,
        "best": best,
        "stage1": results[:5],
        "stage2": exit_results[:5],
    }
