"""Signal-outcome tracker (PLAN 6.2 / 7.4) — the observational-run engine.

Every published signal is replayed daily against actual subsequent prices using
the SAME simulator as the backtester (no live/backtest divergence). Terminal
outcomes (EXPIRED / SL_HIT / T1_TRAIL / T2_HIT / TIME_STOP) are written to
``signal_outcomes``; signals still in flight stay outcome='OPEN' and are
re-evaluated next run.

This forward-collected dataset is the one validation source that cannot be
overfit — the whole point of the observational run (RESEARCH_LOG decision gate).
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pandas as pd

from analyzer.backtest.engine import simulate_trade
from analyzer.config import Config, get_config
from analyzer.logging_setup import get_logger

log = get_logger(__name__)

TERMINAL = {"EXPIRED", "SL_HIT", "T1_TRAIL", "T2_HIT", "TIME_STOP"}


def _future_bars(repo, symbol: str, after: date) -> pd.DataFrame:
    return repo.query_df(
        "SELECT date, open, high, low, close FROM prices_adj "
        "WHERE symbol = ? AND date > ? ORDER BY date",
        [symbol, after],
    )


def update_signal_outcomes(repo, cfg: Config | None = None, lookback_days: int = 90) -> dict:
    """Re-evaluate all non-terminal signals from the last ``lookback_days``."""
    cfg = cfg or get_config()
    sig_cfg = cfg.signals

    signals = repo.query_df(
        """
        SELECT s.signal_id, s.date, s.symbol, s.setup, s.entry_aggressive,
               s.stop_loss, s.t1, s.t2, o.outcome AS prev_outcome
        FROM signals s
        LEFT JOIN signal_outcomes o ON o.signal_id = s.signal_id
        WHERE s.date >= CURRENT_DATE - INTERVAL (?) DAY
          AND (o.outcome IS NULL OR o.outcome = 'OPEN')
        ORDER BY s.date
        """,
        [lookback_days],
    )
    if signals.empty:
        log.info("tracker_nothing_to_update")
        return {"checked": 0, "terminal": 0, "open": 0}

    rows = []
    n_terminal = 0
    for _, s in signals.iterrows():
        sig_date = pd.Timestamp(s["date"]).date()
        bars = _future_bars(repo, s["symbol"], sig_date)
        if bars.empty:
            continue
        signal = {
            "symbol": s["symbol"], "setup": s["setup"], "date": sig_date,
            "entry_aggressive": s["entry_aggressive"], "stop_loss": s["stop_loss"],
            "t1": s["t1"], "t2": s["t2"],
        }
        tr = simulate_trade(signal, bars, sig_cfg, cfg.backtest)

        # Distinguish genuinely-terminal from "not enough future data yet".
        outcome = tr.outcome
        if outcome == "EXPIRED" and len(bars) < sig_cfg["entry_valid_sessions"]:
            outcome = "OPEN"          # entry window still running
        elif outcome == "END":
            outcome = "OPEN"          # entered, still in flight
        if outcome in TERMINAL:
            n_terminal += 1

        rows.append(
            {
                "signal_id": s["signal_id"],
                "triggered": bool(tr.entered),
                "trigger_date": tr.entry_date,
                "outcome": outcome,
                "exit_date": tr.exit_date if outcome in TERMINAL else None,
                "realized_r": tr.net_r if outcome in TERMINAL else None,
                "mfe_r": tr.mfe_r,
                "mae_r": tr.mae_r,
            }
        )

    if rows:
        repo.upsert_df("signal_outcomes", pd.DataFrame(rows))
    summary = {"checked": len(signals), "terminal": n_terminal,
               "open": len(rows) - n_terminal}
    log.info("tracker_updated", **summary)
    return summary


def outcome_stats(repo, since: date | None = None) -> pd.DataFrame:
    """Live per-setup performance from tracked outcomes (terminal only)."""
    where = "WHERE o.outcome NOT IN ('OPEN')" if since is None else \
            "WHERE o.outcome NOT IN ('OPEN') AND s.date >= ?"
    params = [] if since is None else [since]
    return repo.query_df(
        f"""
        SELECT s.setup,
               COUNT(*)                                        AS n,
               SUM(CASE WHEN o.triggered THEN 1 ELSE 0 END)    AS triggered,
               ROUND(AVG(CASE WHEN o.realized_r > 0 THEN 100.0 ELSE 0 END), 1) AS win_pct,
               ROUND(SUM(COALESCE(o.realized_r, 0)), 2)        AS sum_r,
               ROUND(AVG(o.realized_r), 3)                     AS avg_r
        FROM signal_outcomes o
        JOIN signals s ON s.signal_id = o.signal_id
        {where}
        GROUP BY s.setup ORDER BY s.setup
        """,
        params,
    )


def open_position_actions(repo, cfg: Config | None = None) -> list[str]:
    """Daily 'actions required' for manually tracked positions (positions table)."""
    cfg = cfg or get_config()
    pos = repo.query_df(
        "SELECT position_id, symbol, qty, entry_price, current_sl, status, booked_pct "
        "FROM positions WHERE status IN ('OPEN', 'PARTIAL')"
    )
    if pos.empty:
        return []
    actions: list[str] = []
    for _, p in pos.iterrows():
        last = repo.query_df(
            "SELECT date, close, low FROM prices_adj WHERE symbol = ? ORDER BY date DESC LIMIT 1",
            [p["symbol"]],
        )
        if last.empty:
            continue
        close = float(last.iloc[0]["close"])
        sig = repo.query_df(
            "SELECT t1, t2 FROM signals WHERE signal_id = "
            "(SELECT signal_id FROM positions WHERE position_id = ?)",
            [p["position_id"]],
        )
        if close <= p["current_sl"]:
            actions.append(f"{p['symbol']}: CLOSE {close:.1f} <= stop {p['current_sl']:.1f} — EXIT")
        elif not sig.empty and p["status"] == "OPEN" and close >= float(sig.iloc[0]["t1"]):
            actions.append(
                f"{p['symbol']}: T1 hit — book 50%, move stop to breakeven "
                f"({p['entry_price']:.1f})"
            )
    return actions
