"""Daily markdown report (PLAN Section 14).

Sections: regime banner, new signals (with UNVALIDATED status), open-position
actions, live observational performance (signal_outcomes), momentum+quality
watchlist. Written to reports/daily/YYYY-MM-DD.md; the same text feeds Telegram.
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from analyzer.config import Config, get_config
from analyzer.logging_setup import get_logger
from analyzer.risk.tracker import open_position_actions, outcome_stats

log = get_logger(__name__)

_DISCLAIMER = (
    "> Educational analytics, not investment advice. Securities markets are "
    "subject to market risks. All setups are UNVALIDATED per the research log — "
    "this feed exists to collect observational outcomes, not to be traded."
)


def _regime_banner(repo, as_of: date) -> str:
    r = repo.query_df(
        "SELECT date, regime, nifty_close, breadth_above_200dma, india_vix "
        "FROM regime_daily WHERE date <= ? ORDER BY date DESC LIMIT 1",
        [as_of],
    )
    if r.empty:
        return "**Regime:** unknown"
    row = r.iloc[0]
    breadth = f"{row['breadth_above_200dma']:.0f}%" if pd.notna(row["breadth_above_200dma"]) else "n/a"
    vix = f"{row['india_vix']:.1f}" if pd.notna(row["india_vix"]) else "n/a"
    return (
        f"**Regime: {row['regime']}** | Nifty {row['nifty_close']:,.0f} | "
        f"breadth {breadth} above 200DMA | India VIX {vix}"
    )


def _signals_section(repo, as_of: date) -> str:
    sigs = repo.query_df(
        "SELECT symbol, setup, grade, composite_score, entry_aggressive, "
        "entry_conservative, stop_loss, t1, t2, rr, suggested_risk_pct, reasons, chart_path "
        "FROM signals WHERE date = ? ORDER BY composite_score DESC",
        [as_of],
    )
    if sigs.empty:
        return "_No new signals today._"
    lines = [
        "| # | Symbol | Setup | Gr | Score | Entry | Stop | T1 | T2 | R:R | Risk% |",
        "|---|--------|-------|----|-------|-------|------|----|----|-----|-------|",
    ]
    for i, s in sigs.iterrows():
        lines.append(
            f"| {i+1} | **{s['symbol']}** | {s['setup'].split('_')[0]} | {s['grade']} "
            f"| {s['composite_score']:.0f} | {s['entry_aggressive']:.1f} "
            f"| {s['stop_loss']:.1f} | {s['t1']:.1f} | {s['t2']:.1f} "
            f"| {s['rr']:.1f} | {s['suggested_risk_pct']:.1f} |"
        )
    lines.append("")
    for _, s in sigs.iterrows():
        reasons = s["reasons"] if isinstance(s["reasons"], list) else []
        if len(reasons):
            lines.append(f"- **{s['symbol']}**: " + "; ".join(str(r) for r in reasons[:3]))
    return "\n".join(lines)


def _performance_section(repo) -> str:
    stats = outcome_stats(repo)
    if stats.empty:
        return "_No terminal outcomes tracked yet._"
    lines = [
        "| Setup | Signals | Triggered | Win% | Sum R | Avg R |",
        "|-------|---------|-----------|------|-------|-------|",
    ]
    for _, r in stats.iterrows():
        lines.append(
            f"| {r['setup']} | {r['n']} | {r['triggered']} | {r['win_pct']} "
            f"| {r['sum_r']} | {r['avg_r']} |"
        )
    return "\n".join(lines)


def _momentum_watchlist(repo, cfg: Config) -> str:
    """Current top-20 quality-gated momentum names (observational watchlist)."""
    try:
        from analyzer.research.momentum import (
            MomentumConfig, eligible_mask, load_panels, momentum_scores,
        )
        from analyzer.research.quality_panel import build_snapshot, load_history, quality_gate

        mcfg = MomentumConfig()
        close, tv, _n, _d = load_panels(repo)
        if len(close) < mcfg.lookback_12m + 1:
            return "_Insufficient history for momentum watchlist._"
        i = len(close) - 1
        elig = eligible_mask(close, tv, i, mcfg)
        hist = load_history(repo)
        if not hist.empty:
            snap = build_snapshot(hist, close.index[i])
            passing = set(quality_gate(snap)[lambda s: s].index)
            elig &= elig.index.isin(passing)
        scores = momentum_scores(close, i, mcfg)[elig].nlargest(mcfg.top_n)
        if scores.empty:
            return "_No names pass the momentum+quality screen today._"
        names = ", ".join(f"{s} ({v*100:.0f}%)" for s, v in scores.items())
        return f"Top {len(scores)} by 6/12m momentum (quality-gated): {names}"
    except Exception as exc:  # noqa: BLE001
        log.warning("momentum_watchlist_failed", error=str(exc))
        return "_Momentum watchlist unavailable._"


def build_daily_report(repo, as_of: date, cfg: Config | None = None) -> str:
    cfg = cfg or get_config()
    actions = open_position_actions(repo, cfg)
    actions_md = "\n".join(f"- {a}" for a in actions) if actions else "_None._"

    parts = [
        f"# Daily Report — {as_of}",
        "",
        _regime_banner(repo, as_of),
        "",
        "## New signals (observational — do not trade)",
        _signals_section(repo, as_of),
        "",
        "## Open-position actions",
        actions_md,
        "",
        "## Live observational performance (tracked outcomes)",
        _performance_section(repo),
        "",
        "## Momentum + quality watchlist (monthly-style, informational)",
        _momentum_watchlist(repo, cfg),
        "",
        "---",
        _DISCLAIMER,
    ]
    return "\n".join(parts)


def write_daily_report(repo, as_of: date, cfg: Config | None = None) -> str:
    cfg = cfg or get_config()
    content = build_daily_report(repo, as_of, cfg)
    out_dir = cfg.reports_path / "daily"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{as_of}.md"
    path.write_text(content, encoding="utf-8")
    log.info("report_written", path=str(path))
    return str(path)
