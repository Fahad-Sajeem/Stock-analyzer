"""Signal publisher (PLAN 8.5-8.6) — the orchestration capstone.

For a given as-of date: pick active setups by regime, scan the approved universe,
apply the weekly gate, compute levels + composite score, rank with per-day and
per-sector caps, and write the JSON-contract rows to the ``signals`` table.
"""

from __future__ import annotations

import json
from datetime import date

import pandas as pd

from analyzer.config import Config, get_config
from analyzer.data.calendar import TradingCalendar
from analyzer.logging_setup import get_logger
from analyzer.setups import SCANNERS, get_active_setups
from analyzer.setups.base import SETUP_C, TREND_SETUPS
from analyzer.setups.candlesticks import bullish_confirmation
from analyzer.signals.levels import compute_levels
from analyzer.signals.scoring import compute_score

log = get_logger(__name__)

_SETUP_LETTER = {
    "A_momentum_breakout": "A", "B_pullback_trend": "B", "C_mean_reversion": "C",
    "D_squeeze_breakout": "D", "E_earnings_momentum": "E",
}

_SETUP_CFG_KEY = {
    "A_momentum_breakout": "breakout", "B_pullback_trend": "pullback",
    "C_mean_reversion": "mean_reversion", "D_squeeze_breakout": "squeeze",
    "E_earnings_momentum": "earnings_momentum",
}


def _load_scan_data(repo, as_of: date) -> pd.DataFrame:
    """Prices (adjusted) + delivery + indicators for all symbols up to as_of."""
    return repo.query_df(
        """
        SELECT a.symbol, a.date, a.open, a.high, a.low, a.close, a.volume,
               r.delivery_pct,
               i.ema20, i.ema50, i.sma200, i.adx, i.rsi, i.macd, i.macd_hist,
               i.atr, i.atr_pct, i.bb_width_pctile, i.vol_ratio, i.rs_pctile,
               i.roc20, i.roc60, i.dist_52wh, i.supertrend, i.in_base, i.base_days,
               i.wk_gate_trend, i.wk_gate_mr
        FROM prices_adj a
        JOIN indicators_daily i ON i.symbol = a.symbol AND i.date = a.date
        LEFT JOIN prices_raw r ON r.symbol = a.symbol AND r.date = a.date
        WHERE a.date <= ?
        ORDER BY a.symbol, a.date
        """,
        [as_of],
    )


def _recent_announcements(repo, as_of: date, window_days: int = 7) -> dict[str, set]:
    """symbol -> set(announce_dates) in the recent window (for live Setup E)."""
    try:
        cal = repo.query_df(
            "SELECT symbol, announce_date FROM results_calendar "
            "WHERE announce_date BETWEEN ? - INTERVAL (?) DAY AND ?",
            [as_of, window_days, as_of],
        )
    except Exception:  # noqa: BLE001 - table may not exist on old DBs
        return {}
    if cal.empty:
        return {}
    cal["announce_date"] = pd.to_datetime(cal["announce_date"]).dt.date
    return {s: set(g["announce_date"]) for s, g in cal.groupby("symbol")}


def _research_quality_set(repo, as_of: date) -> set | None:
    """Symbols passing the frozen research quality gate as of today (tag only)."""
    try:
        from analyzer.research.quality_panel import build_snapshot, load_history, quality_gate

        hist = load_history(repo)
        if hist.empty:
            return None
        snap = build_snapshot(hist, as_of)
        gate = quality_gate(snap)
        return set(gate[gate].index)
    except Exception as exc:  # noqa: BLE001
        log.warning("research_quality_tag_unavailable", error=str(exc))
        return None


def _approved_universe(repo, as_of: date) -> pd.DataFrame:
    latest = repo.scalar("SELECT MAX(as_of) FROM universe WHERE as_of <= ?", [as_of])
    if latest is None:
        return pd.DataFrame()
    return repo.query_df(
        "SELECT symbol, quality_score FROM universe WHERE as_of = ? AND approved", [latest]
    )


def run_publish_signals(
    repo, cfg: Config | None = None, as_of: date | None = None
) -> pd.DataFrame:
    cfg = cfg or get_config()
    sig_cfg = cfg.signals
    risk_cfg = cfg.risk

    if as_of is None:
        as_of = repo.scalar("SELECT MAX(date) FROM indicators_daily")
        if as_of is None:
            log.warning("no_indicators")
            return pd.DataFrame()

    regime_row = repo.query_df(
        "SELECT regime, india_vix FROM regime_daily WHERE date <= ? ORDER BY date DESC LIMIT 1",
        [as_of],
    )
    regime = regime_row.iloc[0]["regime"] if not regime_row.empty else "NEUTRAL"
    vix = regime_row.iloc[0]["india_vix"] if not regime_row.empty else None
    active = get_active_setups(regime)
    if not active:
        log.info("no_active_setups", regime=regime, date=str(as_of))
        return pd.DataFrame()

    universe = _approved_universe(repo, as_of)
    if universe.empty:
        log.warning("empty_universe", date=str(as_of))
        return pd.DataFrame()
    quality_map = dict(zip(universe["symbol"], universe["quality_score"]))

    data = _load_scan_data(repo, as_of)
    if data.empty:
        return pd.DataFrame()

    calendar = TradingCalendar.from_repo(repo)
    valid_till = calendar.add_sessions(as_of, sig_cfg["entry_valid_sessions"])
    high_vix = vix is not None and not pd.isna(vix) and vix > cfg.regime.get("vix_high", 22)

    announcements = _recent_announcements(repo, as_of)       # live Setup E flag
    research_quality = _research_quality_set(repo, as_of)    # observational tag

    candidates = []
    for symbol, grp in data.groupby("symbol"):
        if symbol not in quality_map:
            continue
        grp = grp.reset_index(drop=True)
        if grp.iloc[-1]["date"] != as_of:
            continue  # symbol didn't trade on as_of
        qscore = float(quality_map[symbol])

        # Inject results_recent (announce day or next session) for Setup E.
        ann = announcements.get(symbol)
        if ann:
            dts = pd.to_datetime(grp["date"]).dt.date
            on_day = dts.isin(ann)
            grp["results_recent"] = (on_day | on_day.shift(1, fill_value=False)).to_numpy()

        for setup_id in active:
            # Per-setup regime restriction (tunable, e.g. pullback NEUTRAL-only).
            allowed = cfg.setups.get(_SETUP_CFG_KEY.get(setup_id, ""), {}).get("allowed_regimes")
            if allowed and regime not in allowed:
                continue
            raw = SCANNERS[setup_id](grp, cfg.setups)
            if raw is None:
                continue

            # Setup-specific quality gates (PLAN 7.3 / 7.5).
            if setup_id == SETUP_C:
                if qscore < cfg.setups["mean_reversion"]["quality_min"]:
                    continue
                if regime == "BEAR" and qscore < 80:
                    continue
                if not bool(grp.iloc[-1].get("wk_gate_mr", False)):
                    continue

            levels = compute_levels(raw, sig_cfg)
            if levels is None:
                continue

            is_bull, pattern = bullish_confirmation(grp)
            candle_bonus = 5.0 if is_bull else 0.0
            if pattern:
                raw.reasons.append(f"Candlestick confirmation: {pattern}")

            score = compute_score(raw, qscore, sig_cfg, candle_bonus=candle_bonus)

            # Weekly multi-timeframe gate: trend setups failing it -> watch-only.
            demoted = False
            if setup_id in TREND_SETUPS and not bool(grp.iloc[-1].get("wk_gate_trend", False)):
                if score.grade in ("A", "B"):
                    score.grade = "C"
                    demoted = True
                    raw.warnings.append("Below weekly trend gate — demoted to watch-only")

            if score.grade == "D":
                continue

            risk_pct = (
                risk_cfg["risk_per_trade_pct"]
                if score.grade == "A"
                else risk_cfg["risk_per_trade_pct_grade_b"]
            )
            if regime == "BEAR" or high_vix:
                risk_pct /= 2.0

            warnings = list(raw.warnings)
            if high_vix:
                warnings.append(f"India VIX {vix:.0f} elevated — size halved")
            # Honesty gate: mark signals from setups that haven't passed backtest
            # acceptance gates (PLAN 10.3.4 / config.signals.validated_setups).
            if setup_id not in sig_cfg.get("validated_setups", []):
                raw.warnings.append("UNVALIDATED setup - failed/pending backtest gates")
                warnings.append("UNVALIDATED setup - failed/pending backtest gates")

            # Observational tag: frozen research quality gate (EXP-003) — used to
            # slice live outcomes (e.g. PEAD+quality hypothesis), never to gate.
            if research_quality is not None:
                tag = ("research-quality-gate: PASS" if symbol in research_quality
                       else "research-quality-gate: fail")
                raw.reasons.append(tag)

            candidates.append(
                {
                    "raw": raw, "levels": levels, "score": score,
                    "quality": qscore, "risk_pct": risk_pct, "demoted": demoted,
                    "sector": None,
                }
            )

    if not candidates:
        log.info("no_signals", date=str(as_of), regime=regime)
        return pd.DataFrame()

    # Rank by composite; apply per-sector then per-day caps (PLAN 8.6).
    candidates.sort(key=lambda c: c["score"].composite, reverse=True)
    per_sector: dict = {}
    selected = []
    for c in candidates:
        sec = c["sector"] or "UNKNOWN"
        if per_sector.get(sec, 0) >= sig_cfg["max_signals_per_sector"] and sec != "UNKNOWN":
            continue
        selected.append(c)
        per_sector[sec] = per_sector.get(sec, 0) + 1
        if len(selected) >= sig_cfg["max_signals_per_day"]:
            break

    rows = [
        _build_signal_row(c, as_of, valid_till, regime, sig_cfg) for c in selected
    ]
    df = pd.DataFrame(rows)
    with repo.job_run(f"publish_signals:{as_of}") as jr:
        n = repo.upsert_df("signals", df)
        jr.add_rows(n)
    log.info("signals_published", date=str(as_of), regime=regime, n=len(df))
    return df


def _build_signal_row(c: dict, as_of: date, valid_till: date, regime: str, sig_cfg: dict) -> dict:
    raw, levels, score = c["raw"], c["levels"], c["score"]
    letter = _SETUP_LETTER.get(raw.setup, "X")
    signal_id = f"{as_of}-{raw.symbol}-{letter}"
    payload = {
        "signal_id": signal_id,
        "date": str(as_of),
        "symbol": raw.symbol,
        "setup": raw.setup,
        "direction": raw.direction,
        "grade": score.grade,
        "composite_score": score.composite,
        "score_breakdown": score.breakdown,
        "entry_aggressive": levels.entry_aggressive,
        "entry_conservative": levels.entry_conservative,
        "entry_valid_till": str(valid_till),
        "stop_loss": levels.stop_loss,
        "stop_basis": levels.stop_basis,
        "t1": levels.t1,
        "t2": levels.t2,
        "rr_to_t2": levels.rr_to_t2,
        "risk_pct": levels.risk_pct,
        "time_stop_sessions": sig_cfg["time_stop_sessions"],
        "quality_score": round(c["quality"], 1),
        "regime": regime,
        "suggested_risk_pct": c["risk_pct"],
        "reasons": raw.reasons,
        "warnings": raw.warnings,
    }
    return {
        "signal_id": signal_id,
        "date": as_of,
        "symbol": raw.symbol,
        "setup": raw.setup,
        "direction": raw.direction,
        "grade": score.grade,
        "composite_score": score.composite,
        "entry_aggressive": levels.entry_aggressive,
        "entry_conservative": levels.entry_conservative,
        "entry_valid_till": valid_till,
        "stop_loss": levels.stop_loss,
        "t1": levels.t1,
        "t2": levels.t2,
        "rr": levels.rr_to_t2,
        "suggested_risk_pct": c["risk_pct"],
        "reasons": raw.reasons,
        "warnings": raw.warnings,
        "payload": json.dumps(payload),
        "chart_path": None,
    }
