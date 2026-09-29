"""forecast_margin -- ruling A-6 (RULING_forecast_nbp_reopen_2026-09-29.md §12).

margin(h) = m0 + (m24 - m0) * clamp((h - h0) / (24 - h0), 0, 1), using the
existing, committed LadderEvConfig defaults (m0=0.02, m24=0.06, h0=6h). No
n_cell/archive-cell gate -- dropped for this family (A-6).
"""

from __future__ import annotations

import pytest

from breezy.strategy.ladder_ev.config import LadderEvConfig


def test_at_h0_margin_equals_m0() -> None:
    from breezy.strategy.forecast_quantile_ladder.margin import forecast_margin

    cfg = LadderEvConfig()
    assert forecast_margin(6.0, cfg) == pytest.approx(0.02, abs=1e-12)


def test_at_h_3_margin_is_hand_computed_0_02() -> None:
    """h=3 < h0=6 -> clamp(...) = 0 -> margin = m0 = 0.02."""
    from breezy.strategy.forecast_quantile_ladder.margin import forecast_margin

    cfg = LadderEvConfig()
    assert forecast_margin(3.0, cfg) == pytest.approx(0.02, abs=1e-12)


def test_at_h_15_margin_is_hand_computed_0_04() -> None:
    """h=15: t = (15-6)/(24-6) = 0.5 -> margin = 0.02 + (0.06-0.02)*0.5 = 0.04."""
    from breezy.strategy.forecast_quantile_ladder.margin import forecast_margin

    cfg = LadderEvConfig()
    assert forecast_margin(15.0, cfg) == pytest.approx(0.04, abs=1e-12)


def test_at_h_30_margin_is_hand_computed_0_06() -> None:
    """h=30 > 24 -> clamp(...) = 1 -> margin = m24 = 0.06."""
    from breezy.strategy.forecast_quantile_ladder.margin import forecast_margin

    cfg = LadderEvConfig()
    assert forecast_margin(30.0, cfg) == pytest.approx(0.06, abs=1e-12)


def test_uses_the_cfg_supplied_constants_not_hardcoded_ones() -> None:
    from breezy.strategy.forecast_quantile_ladder.margin import forecast_margin

    cfg = LadderEvConfig(margin_m0=0.10, margin_m24=0.20, margin_h0_hours=0)
    assert forecast_margin(0.0, cfg) == pytest.approx(0.10, abs=1e-12)
    assert forecast_margin(24.0, cfg) == pytest.approx(0.20, abs=1e-12)


def test_takes_no_n_cell_parameter() -> None:
    """A-6: the archive-cell gate is dropped for this family."""
    import inspect

    from breezy.strategy.forecast_quantile_ladder.margin import forecast_margin

    params = inspect.signature(forecast_margin).parameters
    assert "n_cell" not in params
    assert "n_min_cell" not in params
