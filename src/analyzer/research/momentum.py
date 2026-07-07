"""EXP-001 (R1) — cross-sectional momentum portfolio backtest.

Config, hypothesis, and kill criteria are REGISTERED in RESEARCH_LOG.md — do not
change parameters here without a new log entry. DEV window only.

Run:  .venv/Scripts/python.exe -m analyzer.research.momentum
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from analyzer.logging_setup import configure_logging, get_logger

log = get_logger(__name__)


@dataclass
class MomentumConfig:
    # Declared in RESEARCH_LOG.md EXP-001; keep in sync with the log entry.
    top_n: int = 20
    skip_days: int = 21
    lookback_6m: int = 126
    lookback_12m: int = 252
    min_price: float = 20.0
    min_median_tv: float = 3e7        # ₹3 crore/day
    liq_window: int = 20
    cost_per_side: float = 0.003      # 0.30%
    kill_switch: bool = True
    dev_start: date = date(2016, 7, 1)
    dev_end: date = date(2023, 12, 31)


# --------------------------------------------------------------------------
# data loading
# --------------------------------------------------------------------------

def load_panels(repo) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """Return (close_wide, traded_value_wide, nifty_close, nifty_200dma).

    Wide frames: index = trading dates (ascending), columns = symbols.
    Traded value = close x volume on ADJUSTED data (adjustment-invariant).
    """
    df = repo.query_df("SELECT symbol, date, close, volume FROM prices_adj ORDER BY date")
    df["date"] = pd.to_datetime(df["date"])
    close = df.pivot_table(index="date", columns="symbol", values="close", aggfunc="last")
    vol = df.pivot_table(index="date", columns="symbol", values="volume", aggfunc="last")
    tv = close * vol

    idx = repo.query_df(
        "SELECT date, close FROM index_prices WHERE index_name='NIFTY50' ORDER BY date"
    )
    nifty = pd.Series(idx["close"].values, index=pd.to_datetime(idx["date"]))
    nifty_dma = nifty.rolling(200, min_periods=100).mean()
    return close, tv, nifty, nifty_dma


def month_end_positions(dates: pd.DatetimeIndex) -> list[int]:
    """Row positions of the last trading day in each calendar month."""
    keys = dates.to_period("M")
    pos = []
    for i in range(len(dates) - 1):
        if keys[i] != keys[i + 1]:
            pos.append(i)
    pos.append(len(dates) - 1)
    return pos


# --------------------------------------------------------------------------
# core mechanics (pure, unit-testable)
# --------------------------------------------------------------------------

def eligible_mask(
    close: pd.DataFrame, tv: pd.DataFrame, i: int, cfg: MomentumConfig
) -> pd.Series:
    """Eligibility at row position ``i`` (uses only data <= i; no look-ahead)."""
    c_now = close.iloc[i]
    c_old = close.iloc[i - cfg.lookback_12m]
    med_tv = tv.iloc[max(0, i - cfg.liq_window + 1) : i + 1].median()
    return (
        c_now.notna()
        & (c_now >= cfg.min_price)
        & c_old.notna()
        & med_tv.notna()
        & (med_tv >= cfg.min_median_tv)
    )


def momentum_scores(close: pd.DataFrame, i: int, cfg: MomentumConfig) -> pd.Series:
    """Blended 6m/12m momentum with a skip-month, computed at row position i."""
    p_skip = close.iloc[i - cfg.skip_days]
    r6 = p_skip / close.iloc[i - cfg.lookback_6m] - 1.0
    r12 = p_skip / close.iloc[i - cfg.lookback_12m] - 1.0
    return 0.5 * r6 + 0.5 * r12


def turnover_cost(prev: set, curr: set, top_n: int, cost_per_side: float) -> float:
    """Cost as a fraction of the book: entries buy one side, exits sell one side."""
    if not prev and not curr:
        return 0.0
    entries = len(curr - prev)
    exits = len(prev - curr)
    return (entries + exits) / max(top_n, 1) * cost_per_side


def max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    return float((-(equity - peak) / peak).max() * 100.0)


def perf_stats(monthly_returns: pd.Series) -> dict:
    r = monthly_returns.dropna()
    if len(r) == 0:
        return {}
    equity = (1 + r).cumprod()
    n_months = len(r)
    cagr = float(equity.iloc[-1] ** (12 / n_months) - 1) * 100
    yearly = (1 + r).groupby(r.index.year).prod() - 1
    return {
        "months": n_months,
        "cagr_pct": round(cagr, 1),
        "max_dd_pct": round(max_drawdown(equity.to_numpy()), 1),
        "ann_vol_pct": round(float(r.std() * np.sqrt(12)) * 100, 1),
        "sharpe": round(float(r.mean() / r.std() * np.sqrt(12)), 2) if r.std() > 0 else 0.0,
        "positive_years_pct": round(float((yearly > 0).mean() * 100), 0),
        "final_equity": round(float(equity.iloc[-1]), 2),
    }


# --------------------------------------------------------------------------
# backtest loop
# --------------------------------------------------------------------------

def run_momentum(
    close: pd.DataFrame, tv: pd.DataFrame, nifty: pd.Series, nifty_dma: pd.Series,
    cfg: MomentumConfig,
    quality_sets: dict | None = None,
) -> dict:
    """Run the EXP-001 variants over the DEV window. Returns stats + curves.

    ``quality_sets``: optional {rebalance_date -> set(symbols passing the
    point-in-time quality gate)} (EXP-003a). Applied to STRATEGY eligibility
    only — benchmarks stay unfiltered so comparisons share one baseline.
    """
    dates = close.index
    me_pos = [
        i for i in month_end_positions(dates)
        if i >= cfg.lookback_12m
        and cfg.dev_start <= dates[i].date() <= cfg.dev_end
    ]
    if len(me_pos) < 24:
        raise RuntimeError(f"too few rebalance points: {len(me_pos)}")

    cff = close.ffill()  # exit pricing for names that stop trading mid-month
    nifty_on = nifty.reindex(dates, method="ffill")
    dma_on = nifty_dma.reindex(dates, method="ffill")

    rows = []
    hold_ks: set = set()     # holdings, kill-switch variant
    hold_nk: set = set()     # holdings, no-kill-switch variant
    for a, b in zip(me_pos[:-1], me_pos[1:]):
        d_a, d_b = dates[a], dates[b]
        elig = eligible_mask(close, tv, a, cfg)
        strat_elig = elig.copy()
        if quality_sets is not None:
            allowed = quality_sets.get(d_a, set())
            strat_elig &= strat_elig.index.isin(allowed)
        scores = momentum_scores(close, a, cfg)[strat_elig]
        top = set(scores.nlargest(cfg.top_n).index) if len(scores) else set()

        period_ret = cff.iloc[b] / cff.iloc[a] - 1.0

        # -- no-kill-switch variant
        new_nk = top
        ret_nk = float(period_ret[list(new_nk)].mean()) if new_nk else 0.0
        ret_nk -= turnover_cost(hold_nk, new_nk, cfg.top_n, cfg.cost_per_side)
        hold_nk = new_nk

        # -- kill-switch variant
        risk_off = bool(nifty_on[d_a] < dma_on[d_a]) if not pd.isna(dma_on[d_a]) else False
        new_ks = set() if risk_off else top
        ret_ks = float(period_ret[list(new_ks)].mean()) if new_ks else 0.0
        ret_ks -= turnover_cost(hold_ks, new_ks, cfg.top_n, cfg.cost_per_side)
        hold_ks = new_ks

        # -- benchmarks (no costs: conservative against the strategy)
        elig_names = list(elig[elig].index)
        ret_ew = float(period_ret[elig_names].mean()) if elig_names else 0.0
        ret_nifty = float(nifty_on[d_b] / nifty_on[d_a] - 1.0)

        rows.append(
            {"date": d_b, "ks": ret_ks, "nk": ret_nk, "ew_universe": ret_ew,
             "nifty": ret_nifty, "n_eligible": len(elig_names), "risk_off": risk_off}
        )

    out = pd.DataFrame(rows).set_index("date")
    return {
        "monthly": out,
        "stats": {
            "momentum_killswitch": perf_stats(out["ks"]),
            "momentum_plain": perf_stats(out["nk"]),
            "benchmark_ew_universe": perf_stats(out["ew_universe"]),
            "nifty50": perf_stats(out["nifty"]),
        },
        "avg_eligible": int(out["n_eligible"].mean()),
        "risk_off_months": int(out["risk_off"].sum()),
    }


def main() -> None:
    from analyzer.jobs.ingest import open_repo

    configure_logging()
    cfg = MomentumConfig()
    repo = open_repo()
    try:
        log.info("loading_panels")
        close, tv, nifty, nifty_dma = load_panels(repo)
        log.info("panels_loaded", dates=len(close), symbols=close.shape[1])
        result = run_momentum(close, tv, nifty, nifty_dma, cfg)
    finally:
        repo.close()

    print(f"\nEXP-001 momentum backtest (DEV {cfg.dev_start}..{cfg.dev_end})")
    print(f"avg eligible universe: {result['avg_eligible']} names | "
          f"risk-off months: {result['risk_off_months']}\n")
    for name, s in result["stats"].items():
        print(f"{name:24s} {s}")

    ks, ew = result["stats"]["momentum_killswitch"], result["stats"]["benchmark_ew_universe"]
    edge = ks["cagr_pct"] - ew["cagr_pct"]
    dd_ok = ks["max_dd_pct"] <= 1.1 * ew["max_dd_pct"]
    print(f"\nCAGR edge vs EW universe: {edge:+.1f}pp (need >= +3.0)")
    print(f"DD condition (<= 1.1x benchmark): {'OK' if dd_ok else 'VIOLATED'} "
          f"({ks['max_dd_pct']}% vs {ew['max_dd_pct']}%)")
    print(f"\nEXP-001 verdict: {'PASS' if edge >= 3.0 and dd_ok else 'FAIL'}")


if __name__ == "__main__":
    main()
