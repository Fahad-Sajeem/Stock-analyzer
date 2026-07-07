"""Backtest report-card generation (PLAN 10.3). Markdown per setup + DB rows."""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from analyzer.backtest.metrics import check_gates
from analyzer.db.repository import new_id


def _fmt_metrics(m: dict) -> str:
    if m.get("n_trades", 0) == 0:
        return "  (no trades)\n"
    lines = [
        f"  - trades: {m['n_trades']}  (per year: {m['trades_per_year']})",
        f"  - win rate: {m['win_rate']}%   avg R: {m['avg_r']}   median R: {m['median_r']}",
        f"  - profit factor: {m['profit_factor']}   expectancy: {m['expectancy_r']} R",
        f"  - max drawdown: {m['max_dd_pct']}%   CAGR: {m['cagr_pct']}%   equity x{m['final_equity_mult']}",
        f"  - avg hold: {m['avg_days_held']}d   positive years: {m['pct_positive_years']}%",
    ]
    if m.get("by_regime"):
        reg = "; ".join(
            f"{k}: n={v['n']} wr={v['win_rate']}% avgR={v['avg_r']}"
            for k, v in m["by_regime"].items()
        )
        lines.append(f"  - by regime: {reg}")
    return "\n".join(lines) + "\n"


def build_report(
    setup: str, is_metrics: dict, oos_metrics: dict, cfg_backtest: dict
) -> tuple[str, bool]:
    """Return (markdown, passed_gates) for one setup."""
    passed, reasons = check_gates(oos_metrics, cfg_backtest)
    verdict = "✅ PASS" if passed else "❌ FAIL"
    md = [
        f"### Setup `{setup}` — {verdict}",
        "",
        "**In-sample:**",
        _fmt_metrics(is_metrics),
        "**Out-of-sample (acceptance decided here):**",
        _fmt_metrics(oos_metrics),
    ]
    if not passed:
        md.append(f"**Gate failures:** {'; '.join(reasons)}")
    if oos_metrics.get("by_year"):
        md.append("\n**OOS by year:**")
        md.append("| year | n | win% | sum R |")
        md.append("|---|---|---|---|")
        for y, v in sorted(oos_metrics["by_year"].items()):
            md.append(f"| {y} | {v['n']} | {v['win_rate']} | {v['sum_r']} |")
    md.append("\n---\n")
    return "\n".join(md), passed


def write_report_file(reports_dir, content: str) -> str:
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = reports_dir / f"backtest_{stamp}.md"
    path.write_text(content, encoding="utf-8")
    return str(path)


def store_result_row(repo, setup: str, sample: str, metrics: dict, period, report_path: str):
    if metrics.get("n_trades", 0) == 0:
        return
    row = {
        "run_id": new_id("bt_"),
        "run_at": datetime.now(),
        "setup": setup,
        "config_hash": "",
        "period_start": period[0],
        "period_end": period[1],
        "sample": sample,
        "n_trades": metrics["n_trades"],
        "win_rate": metrics["win_rate"],
        "avg_r": metrics["avg_r"],
        "profit_factor": metrics["profit_factor"],
        "max_dd": metrics["max_dd_pct"],
        "cagr": metrics["cagr_pct"],
        "exposure": metrics.get("avg_days_held"),
        "report_path": report_path,
    }
    repo.upsert_df("backtest_results", pd.DataFrame([row]))
