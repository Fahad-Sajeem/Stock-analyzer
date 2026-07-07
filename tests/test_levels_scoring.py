"""Tests for the levels engine and composite scoring (PLAN 8.2-8.6)."""

from datetime import date

from analyzer.config import get_config
from analyzer.setups.base import RawSignal
from analyzer.signals.levels import compute_levels
from analyzer.signals.scoring import compute_score

SIG = get_config().signals


def _raw(**kw) -> RawSignal:
    base = dict(
        symbol="X", date=date(2026, 6, 30), setup="A_momentum_breakout",
        entry_ref=100.0, trigger_level=99.0, swing_low=96.0, base_low=95.0, atr=2.0,
        setup_strength=0.8, extra={"vol_ratio": 2.0, "rs_pctile": 85},
    )
    base.update(kw)
    return RawSignal(**base)


def test_levels_basic_structure_stop():
    lv = compute_levels(_raw(), SIG)
    assert lv is not None
    # structure stop = min(swing_low, base_low) - 0.25*ATR = 95 - 0.5 = 94.5
    # volatility stop = 100 - 2*2 = 96 ; max(94.5, 96) = 96
    assert lv.stop_loss == 96.0
    risk = 100 - 96
    assert lv.t1 == 100 + 1.5 * risk   # 106
    assert lv.t2 == 100 + 3.0 * risk   # 112
    assert lv.rr_to_t2 == 3.0


def test_levels_reject_when_stop_too_wide():
    # Huge ATR pushes the stop beyond the 8% cap -> reject.
    lv = compute_levels(_raw(atr=12.0, swing_low=80.0, base_low=78.0), SIG)
    assert lv is None


def test_levels_min_floor_widens_tight_stop():
    # Very tight structure -> stop floored to min_stop_pct (1.5%).
    lv = compute_levels(_raw(atr=0.2, swing_low=99.9, base_low=99.8), SIG)
    assert lv is not None
    assert abs(lv.risk_pct - SIG["min_stop_pct"]) < 1e-6


def test_levels_reject_low_rr():
    # Resistance between T1 (106) and 3R (112) caps T2 so R:R falls below 2.0.
    # entry 100, stop 96, risk 4 -> resistance 107 gives RR (107-100)/4 = 1.75 < 2.
    lv = compute_levels(_raw(next_resistance=107.0), SIG)
    assert lv is None


def test_levels_t2_uses_nearer_resistance():
    lv = compute_levels(_raw(next_resistance=110.0), SIG)
    assert lv is not None
    # 3R target = 112, resistance 110 is nearer -> T2 = 110.
    assert lv.t2 == 110.0


def test_score_grades_strong_signal_high():
    s = compute_score(_raw(setup_strength=0.9, extra={"vol_ratio": 2.5, "rs_pctile": 95}),
                      quality_score=85, cfg_signals=SIG)
    assert s.composite >= 80
    assert s.grade == "A"


def test_score_weak_signal_low_grade():
    s = compute_score(_raw(setup_strength=0.3, extra={"vol_ratio": 1.1, "rs_pctile": 40}),
                      quality_score=40, cfg_signals=SIG)
    assert s.grade in ("C", "D")


def test_news_and_candle_bounded():
    # News adjustment is capped at +/-5 points.
    s_hi = compute_score(_raw(), quality_score=70, cfg_signals=SIG, news_adjust=100)
    s_lo = compute_score(_raw(), quality_score=70, cfg_signals=SIG, news_adjust=-100)
    assert (s_hi.composite - s_lo.composite) <= 10.001
