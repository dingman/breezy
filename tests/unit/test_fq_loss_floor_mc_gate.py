"""Floor-MC gate: G1 margin, G3 floor, α ladder, freeze table, reach cutoff."""

from __future__ import annotations

import math

import pytest

from breezy.analysis.fq_loss_stop_core import ALPHA_FLOOR_GRID, G3_FLOOR_MULTIPLIER
from scripts.analysis.fq_loss_floor_mc_gate import (
    DEFAULT_FREEZE,
    HORIZON,
    AlphaEval,
    choose_t_min,
    epoch_grid,
    epoch_holds,
    fully_lost_fraction,
    g1_holds,
    g3_floor,
    inclusive_days,
    keep_probability,
    margin_limit,
    rate_cal,
    rate_gate,
    reach_cutoff,
    repeated_crossing,
    select_alpha,
    t_low_count,
)
from scripts.analysis.fq_loss_floor_mc_rows import all_lose_z, make_leg, make_station_day
from scripts.analysis.fq_mc_eprocess import POWER_TARGET


def _eval(
    alpha: float,
    *,
    g1: bool,
    margin: bool,
    g3: float,
    s6_rate: float = 0.05,
    s6_se: float = 0.02,
    c: float = 1.5,
    epochs: dict[str, bool] | None = None,
) -> AlphaEval:
    return AlphaEval(
        alpha=alpha,
        g1_pass=g1,
        g1_margin=margin,
        g3_at_m016=g3,
        s6_rate=s6_rate,
        s6_se=s6_se,
        c=c,
        c_se=0.04,
        t_min=1,
        measured_power={"-0.16": g3, "-0.08": g3 / 2, "-0.04": g3 / 4},
        epoch_ok=epochs
        if epochs is not None
        else {"2026-10-08": g1 and g3 >= g3_floor(alpha), "2026-11-01": False},
    )


def test_g1_margin_rule_and_all_lose_crossing() -> None:
    assert margin_limit(10) == 8
    assert margin_limit(27) == math.floor(0.8 * 27)
    assert g1_holds(8, 10, margin=True)
    assert not g1_holds(9, 10, margin=True)
    assert g1_holds(10, 10, margin=False)
    assert not g1_holds(None, 10, margin=False)
    day = make_station_day("K", (make_leg("T70", "yes", 0.5),))
    z = all_lose_z(day)
    assert z is not None
    assert z == pytest.approx(-1.0)
    assert repeated_crossing(z, c=1.0, t_min=1, t_low=10) == 2
    assert g1_holds(2, 10, margin=True)


def test_g3_floor_tracks_the_multiplier() -> None:
    assert G3_FLOOR_MULTIPLIER == pytest.approx(2.5)
    assert g3_floor(0.10) == pytest.approx(0.25)
    assert g3_floor(0.20) == pytest.approx(0.50)
    assert g3_floor(0.30) == pytest.approx(0.75)
    assert POWER_TARGET == pytest.approx(0.8)


def test_rates_and_keep_probability() -> None:
    assert rate_cal(0.40, 0.25) == pytest.approx(0.40)
    assert rate_gate(0.40, 0.25) == pytest.approx(0.25)
    assert rate_cal(0.10, 0.25) == pytest.approx(0.25)
    assert rate_gate(0.10, 0.25) == pytest.approx(0.10)
    assert keep_probability(0.25, r_sd=1.0, lambda_sd=0.5) == pytest.approx(0.5)
    assert keep_probability(2.0, r_sd=1.0, lambda_sd=0.5) == pytest.approx(1.0)
    assert t_low_count(10, 0.5, 1.0) == 5


def test_t_min_maximises_g3_and_breaks_ties_toward_the_smallest() -> None:
    scores = {1: 0.2, 2: 0.5, 3: 0.5, 5: 0.4}
    assert choose_t_min(scores, {1, 2, 3, 5}) == 2
    assert choose_t_min(scores, {1, 5}) == 5
    with pytest.raises(ValueError, match="t_min"):
        choose_t_min(scores, set())


def test_epoch_grid_and_horizon() -> None:
    assert [day.isoformat() for day in epoch_grid(DEFAULT_FREEZE)] == [
        "2026-10-08",
        "2026-11-01",
        "2026-11-15",
        "2026-12-01",
    ]
    assert inclusive_days(DEFAULT_FREEZE, HORIZON) == (HORIZON - DEFAULT_FREEZE).days + 1
    assert fully_lost_fraction(-1.0, c=2.0, t_low=16) == pytest.approx(min(1.0, 2.0 / 4.0))


@pytest.mark.parametrize(
    ("evals", "mode", "power_class", "alpha", "c_is_none"),
    [
        (
            (
                _eval(0.10, g1=True, margin=False, g3=0.85),
                _eval(0.20, g1=True, margin=True, g3=0.99),
            ),
            "sqrt_boundary",
            "edge_capable",
            0.10,
            False,
        ),
        (
            (
                _eval(0.10, g1=False, margin=False, g3=0.10),
                _eval(0.20, g1=True, margin=True, g3=0.60),
            ),
            "sqrt_boundary",
            "gross_loss_tripwire",
            0.20,
            False,
        ),
        (
            (
                _eval(0.10, g1=False, margin=False, g3=0.0),
                _eval(0.20, g1=True, margin=False, g3=0.9),
                _eval(0.30, g1=True, margin=True, g3=0.90),
            ),
            "sqrt_boundary",
            "edge_capable",
            0.30,
            False,
        ),
        (
            (
                _eval(0.10, g1=False, margin=False, g3=0.0),
                _eval(0.20, g1=False, margin=False, g3=0.0),
            ),
            "unreachable_veto",
            "none",
            None,
            True,
        ),
        (
            (
                _eval(0.10, g1=True, margin=True, g3=0.10),
                _eval(0.20, g1=True, margin=True, g3=0.95),
            ),
            "unreachable_veto",
            "none",
            0.10,
            True,
        ),
        (
            (
                _eval(0.10, g1=False, margin=False, g3=0.0),
                _eval(0.20, g1=True, margin=True, g3=0.10),
                _eval(0.30, g1=True, margin=True, g3=0.95),
            ),
            "unreachable_veto",
            "none",
            0.20,
            True,
        ),
        (
            (_eval(0.10, g1=True, margin=True, g3=0.90, s6_rate=0.50, s6_se=0.01),),
            None,
            "none",
            0.10,
            True,
        ),
        (
            (_eval(0.10, g1=True, margin=True, g3=0.80),),
            "sqrt_boundary",
            "edge_capable",
            0.10,
            False,
        ),
        (
            (_eval(0.10, g1=True, margin=True, g3=0.25),),
            "sqrt_boundary",
            "gross_loss_tripwire",
            0.10,
            False,
        ),
        (
            (_eval(0.10, g1=True, margin=True, g3=0.799),),
            "sqrt_boundary",
            "gross_loss_tripwire",
            0.10,
            False,
        ),
    ],
)
def test_freeze_table_and_ladder_never_escalates_on_g3(
    evals: tuple[AlphaEval, ...],
    mode: str | None,
    power_class: str,
    alpha: float | None,
    c_is_none: bool,
) -> None:
    outcome = select_alpha(evals)
    assert outcome.escalated_on_g3 is False
    assert outcome.floor_mode == mode
    assert outcome.power_class == power_class
    if mode is None:
        assert outcome.freeze_blocked is not None
        assert outcome.freeze_blocked["reason"] == "s6_failed"
    else:
        assert outcome.freeze_blocked is None
    if alpha is None:
        assert outcome.alpha_star is None
    else:
        assert outcome.alpha_star == pytest.approx(alpha)
    assert (outcome.c is None) is c_is_none
    assert set(ALPHA_FLOOR_GRID) >= {item.alpha for item in evals}


def test_reach_cutoff_is_the_latest_epoch_that_holds() -> None:
    assert epoch_holds(g1_pass=True, g1_margin=False, g3=0.30, alpha=0.10)
    assert not epoch_holds(g1_pass=True, g1_margin=False, g3=0.30, alpha=0.20)
    assert not epoch_holds(g1_pass=True, g1_margin=True, g3=0.10, alpha=0.10)
    flags = {"2026-10-08": True, "2026-11-01": False, "2026-12-01": True}
    assert reach_cutoff(flags) == "2026-12-01"
    assert reach_cutoff({"2026-10-08": False}) is None
