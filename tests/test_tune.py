"""Tests for the tuning harness override/grid mechanics (no DB needed)."""

from analyzer.config import get_config
from analyzer.jobs.tune import GRIDS, _apply_overrides, _combos, _score_combo
from analyzer.setups.base import SETUP_A, SETUP_B


def test_apply_overrides_sets_nested_value():
    cfg = get_config()
    orig_vol = cfg.setups["breakout"]["vol_mult_min"]
    orig_ts = cfg.signals["time_stop_sessions"]
    new = _apply_overrides(cfg, {"setups.breakout.vol_mult_min": 99.0,
                                 "signals.time_stop_sessions": 7})
    assert new.setups["breakout"]["vol_mult_min"] == 99.0
    assert new.signals["time_stop_sessions"] == 7
    # Original untouched (deep copy) — whatever its current configured values are.
    assert cfg.setups["breakout"]["vol_mult_min"] == orig_vol
    assert cfg.signals["time_stop_sessions"] == orig_ts


def test_apply_overrides_none_removes_key():
    cfg = get_config()
    with_regimes = _apply_overrides(cfg, {"setups.pullback.allowed_regimes": ["NEUTRAL"]})
    assert with_regimes.setups["pullback"]["allowed_regimes"] == ["NEUTRAL"]
    removed = _apply_overrides(with_regimes, {"setups.pullback.allowed_regimes": None})
    assert "allowed_regimes" not in removed.setups["pullback"]


def test_combos_cartesian_product():
    combos = _combos({"a": [1, 2], "b": ["x", "y", "z"]})
    assert len(combos) == 6
    assert {"a": 1, "b": "x"} in combos


def test_grids_are_coarse():
    # Anti-overfitting guard: no grid axis should have more than 4 values,
    # and total combos per setup stay small.
    for setup, grid in GRIDS.items():
        for key, values in grid.items():
            assert len(values) <= 4, f"{setup}:{key} grid too fine"
        assert len(_combos(grid)) <= 32, f"{setup} grid too large"


def test_score_combo_requires_min_trades():
    assert _score_combo({"n_trades": 10, "expectancy_r": 5.0}) == float("-inf")
    good = _score_combo({"n_trades": 100, "expectancy_r": 0.2})
    better_n = _score_combo({"n_trades": 400, "expectancy_r": 0.2})
    assert better_n > good  # same expectancy, more evidence -> ranks higher


def test_setup_grid_coverage():
    assert SETUP_A in GRIDS and SETUP_B in GRIDS
