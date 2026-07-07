"""Backtest metrics & acceptance gates (PLAN 10.3).

All metrics are computed on NET-of-cost R multiples. The equity curve sequences
trades by entry date and compounds a fixed fractional risk per trade, so the
drawdown reflects risk-normalized position sizing.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _max_drawdown(equity: np.ndarray) -> float:
    """Max peak-to-trough decline of an equity curve, as a positive percent."""
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    return float(-dd.min() * 100.0)


def compute_metrics(
    trades: pd.DataFrame, period_start, period_end, risk_frac: float = 0.01
) -> dict:
    """Compute the full report-card metric set for a set of entered trades."""
    entered = trades[trades["entered"]].copy() if "entered" in trades else trades.copy()
    n = len(entered)
    if n == 0:
        return {"n_trades": 0}

    entered = entered.sort_values("entry_date")
    r = entered["net_r"].to_numpy()
    wins = r[r > 0]
    losses = r[r < 0]

    gross_win = wins.sum()
    gross_loss = abs(losses.sum())
    profit_factor = float(gross_win / gross_loss) if gross_loss > 0 else float("inf")

    equity = np.cumprod(1.0 + r * risk_frac)
    max_dd = _max_drawdown(equity)
    years = max((pd.Timestamp(period_end) - pd.Timestamp(period_start)).days / 365.25, 1e-9)
    cagr = float((equity[-1] ** (1.0 / years) - 1.0) * 100.0) if equity[-1] > 0 else -100.0

    entered["year"] = pd.to_datetime(entered["entry_date"]).dt.year
    by_year = {}
    for y, g in entered.groupby("year"):
        by_year[int(y)] = {
            "n": int(len(g)),
            "win_rate": round(float((g["net_r"] > 0).mean() * 100), 1),
            "sum_r": round(float(g["net_r"].sum()), 2),
            "avg_r": round(float(g["net_r"].mean()), 3),
        }
    positive_years = [y for y, s in by_year.items() if s["sum_r"] > 0]
    pct_positive_years = round(len(positive_years) / len(by_year) * 100, 1) if by_year else 0.0

    by_regime = {}
    if "regime" in entered:
        for rg, g in entered.groupby("regime"):
            by_regime[str(rg)] = {
                "n": int(len(g)),
                "win_rate": round(float((g["net_r"] > 0).mean() * 100), 1),
                "avg_r": round(float(g["net_r"].mean()), 3),
            }

    return {
        "n_trades": n,
        "win_rate": round(float((r > 0).mean() * 100), 1),
        "avg_r": round(float(r.mean()), 3),
        "median_r": round(float(np.median(r)), 3),
        "profit_factor": round(profit_factor, 2) if np.isfinite(profit_factor) else 999.0,
        "expectancy_r": round(float(r.mean()), 3),
        "max_dd_pct": round(max_dd, 1),
        "cagr_pct": round(cagr, 1),
        "avg_days_held": round(float(entered["days_held"].mean()), 1),
        "trades_per_year": round(n / years, 1),
        "pct_positive_years": pct_positive_years,
        "final_equity_mult": round(float(equity[-1]), 3),
        "by_year": by_year,
        "by_regime": by_regime,
    }


def check_gates(metrics: dict, cfg_backtest: dict) -> tuple[bool, list[str]]:
    """Evaluate acceptance gates (PLAN 10.3.4). Returns (passed, failure_reasons)."""
    reasons = []
    if metrics.get("n_trades", 0) < cfg_backtest["min_trades_significance"]:
        reasons.append(
            f"n_trades {metrics.get('n_trades', 0)} < {cfg_backtest['min_trades_significance']}"
        )
    if metrics.get("profit_factor", 0) < cfg_backtest["gate_profit_factor"]:
        reasons.append(
            f"profit_factor {metrics.get('profit_factor', 0)} < {cfg_backtest['gate_profit_factor']}"
        )
    if metrics.get("max_dd_pct", 100) >= cfg_backtest["gate_max_dd_pct"]:
        reasons.append(
            f"max_dd {metrics.get('max_dd_pct', 100)}% >= {cfg_backtest['gate_max_dd_pct']}%"
        )
    if metrics.get("pct_positive_years", 0) < cfg_backtest["gate_positive_years_pct"]:
        reasons.append(
            f"positive_years {metrics.get('pct_positive_years', 0)}% "
            f"< {cfg_backtest['gate_positive_years_pct']}%"
        )
    return (len(reasons) == 0, reasons)
