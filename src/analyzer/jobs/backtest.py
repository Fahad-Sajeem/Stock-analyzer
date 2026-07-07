"""Backtest job (Phase 5): run each setup in-sample + out-of-sample, evaluate
acceptance gates, write report cards, and print a config recommendation.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd

from analyzer.backtest.metrics import compute_metrics
from analyzer.backtest.reports import build_report, store_result_row, write_report_file
from analyzer.backtest.runner import run_backtest
from analyzer.config import Config, get_config
from analyzer.logging_setup import get_logger

log = get_logger(__name__)


def _parse(d) -> date:
    return datetime.strptime(d, "%Y-%m-%d").date() if isinstance(d, str) else d


def run_full_backtest(
    repo, cfg: Config | None = None, apply_weekly_gate: bool = False
) -> dict:
    cfg = cfg or get_config()
    bt = cfg.backtest
    is_start, is_end = _parse(bt["in_sample"][0]), _parse(bt["in_sample"][1])
    oos_start, oos_end = _parse(bt["out_sample"][0]), _parse(bt["out_sample"][1])

    with repo.job_run("backtest") as jr:
        # Generate + simulate once over the whole span, then split by signal date.
        all_trades = run_backtest(
            repo, cfg, start=is_start, end=oos_end, apply_weekly_gate=apply_weekly_gate
        )

        sections = [
            f"# Backtest Report — {datetime.now():%Y-%m-%d %H:%M}",
            f"\nWeekly gate: {'ON' if apply_weekly_gate else 'OFF'}  |  "
            f"IS {is_start}..{is_end}  OOS {oos_start}..{oos_end}\n",
            "> Costs modeled per PLAN 10.2 (STT + charges + slippage). Metrics are "
            "net-of-cost R multiples.\n",
        ]
        summary = {}
        for setup, trades in all_trades.items():
            if trades.empty:
                sections.append(f"### Setup `{setup}` — no signals\n---\n")
                summary[setup] = {"passed": False, "n_oos": 0}
                continue
            trades["sig_date"] = pd.to_datetime(trades["signal_date"])
            is_tr = trades[(trades["sig_date"] >= pd.Timestamp(is_start))
                           & (trades["sig_date"] <= pd.Timestamp(is_end))]
            oos_tr = trades[(trades["sig_date"] >= pd.Timestamp(oos_start))
                            & (trades["sig_date"] <= pd.Timestamp(oos_end))]
            is_m = compute_metrics(is_tr, is_start, is_end)
            oos_m = compute_metrics(oos_tr, oos_start, oos_end)
            md, passed = build_report(setup, is_m, oos_m, bt)
            sections.append(md)
            summary[setup] = {
                "passed": passed,
                "n_oos": oos_m.get("n_trades", 0),
                "oos_pf": oos_m.get("profit_factor"),
                "oos_dd": oos_m.get("max_dd_pct"),
            }
            store_result_row(repo, setup, "IS", is_m, (is_start, is_end), "")
            store_result_row(repo, setup, "OOS", oos_m, (oos_start, oos_end), "")

        content = "\n".join(sections)
        path = write_report_file(cfg.reports_path / "backtest", content)
        jr.add_rows(sum(len(t) for t in all_trades.values()))

    log.info("backtest_complete", report=path, summary=summary)
    return {"report_path": path, "summary": summary}
