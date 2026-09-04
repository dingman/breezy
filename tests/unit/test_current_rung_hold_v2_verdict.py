"""RED-first: `breezy.settlement.current_rung_hold_v2.look_verdict` truth table.

`docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md` rev b Sec 3,
`docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md` Interfaces.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from breezy.settlement.current_rung_hold_v2 import ScoreState, look_verdict


def _state(s: float) -> ScoreState:
    return ScoreState(s=s, information=10.0, n=10)


def test_survive_requires_all_four_conditions() -> None:
    verdict = look_verdict(
        _state(2.0),
        b_eff=1.96,
        b_fut=-1.96,
        total_pnl=Decimal(5),
        cell_dead=False,
        structural_fired=False,
    )
    assert verdict == "SURVIVE"


@pytest.mark.parametrize(
    ("total_pnl", "cell_dead", "structural_fired"),
    [
        (Decimal(-1), False, False),  # PnL not positive
        (Decimal(5), True, False),  # a stratum is dead
        (Decimal(5), False, True),  # structural-dead fired
    ],
)
def test_survive_is_refused_if_any_other_condition_fails_even_with_s_above_b_eff(
    total_pnl: Decimal, cell_dead: bool, structural_fired: bool
) -> None:
    verdict = look_verdict(
        _state(2.0),
        b_eff=1.96,
        b_fut=-1.96,
        total_pnl=total_pnl,
        cell_dead=cell_dead,
        structural_fired=structural_fired,
    )
    assert verdict != "SURVIVE"


def test_kill_on_s_at_or_below_b_fut() -> None:
    verdict = look_verdict(
        _state(-2.0),
        b_eff=1.96,
        b_fut=-1.96,
        total_pnl=Decimal(5),
        cell_dead=False,
        structural_fired=False,
    )
    assert verdict == "KILL"


def test_kill_on_cell_dead_alone_even_with_a_strong_positive_score() -> None:
    verdict = look_verdict(
        _state(5.0),
        b_eff=1.96,
        b_fut=-1.96,
        total_pnl=Decimal(5),
        cell_dead=True,
        structural_fired=False,
    )
    assert verdict == "KILL"


def test_kill_on_structural_fired_alone_even_with_a_strong_positive_score() -> None:
    verdict = look_verdict(
        _state(5.0),
        b_eff=1.96,
        b_fut=-1.96,
        total_pnl=Decimal(5),
        cell_dead=False,
        structural_fired=True,
    )
    assert verdict == "KILL"


def test_continue_in_the_interior_band() -> None:
    verdict = look_verdict(
        _state(0.0),
        b_eff=1.96,
        b_fut=-1.96,
        total_pnl=Decimal(5),
        cell_dead=False,
        structural_fired=False,
    )
    assert verdict == "CONTINUE"


def test_plus_minus_inf_boundaries_are_valid_inputs_and_force_continue() -> None:
    """A degenerate tied-information look (Sec 7 tie guard) emits
    `b_eff=+inf`, `b_fut=-inf`: no finite `S` can cross either, so the look
    is CONTINUE-forced absent an independent cell_dead/structural KILL."""
    verdict = look_verdict(
        _state(1_000.0),
        b_eff=float("inf"),
        b_fut=float("-inf"),
        total_pnl=Decimal(5),
        cell_dead=False,
        structural_fired=False,
    )
    assert verdict == "CONTINUE"


def test_plus_minus_inf_boundaries_do_not_suppress_an_independent_kill() -> None:
    verdict = look_verdict(
        _state(1_000.0),
        b_eff=float("inf"),
        b_fut=float("-inf"),
        total_pnl=Decimal(5),
        cell_dead=True,
        structural_fired=False,
    )
    assert verdict == "KILL"
