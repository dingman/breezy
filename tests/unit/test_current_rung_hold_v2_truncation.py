"""RED-first: `breezy.settlement.current_rung_hold_v2.terminal_look`/`TruncationReason`.

`docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md` rev b Sec 4,
`docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md` Sec "Tests" (truncation).
CONTINUE is illegal at a terminal look; the return type admits only
SURVIVE/KILL by construction, so no test asserts `!= "CONTINUE"` -- the
type system already forecloses it. These tests instead pin the KILL/SURVIVE
truth table across the three `TruncationReason`s.
"""

from __future__ import annotations

from decimal import Decimal
from typing import get_args

import pytest

from breezy.settlement.current_rung_hold_v2 import (
    ScoreState,
    TruncationReason,
    terminal_look,
)


def _state(s: float) -> ScoreState:
    return ScoreState(s=s, information=40.0, n=160)


def test_terminal_look_return_type_admits_only_survive_and_kill() -> None:
    import typing

    hints = typing.get_type_hints(terminal_look)
    literal_args = get_args(hints["return"])
    assert set(literal_args) == {"SURVIVE", "KILL"}


def test_loss_stop_is_kill_unconditionally_even_with_s_far_above_b_eff() -> None:
    verdict = terminal_look(
        _state(100.0),
        reason=TruncationReason.LOSS_STOP,
        b_eff=1.96,
        b_fut=-1.96,
        total_pnl=Decimal(100),  # even a (contradictory) positive PnL input
        cell_dead=False,
    )
    assert verdict == "KILL"


def test_loss_stop_is_kill_with_a_realistic_negative_pnl_too() -> None:
    verdict = terminal_look(
        _state(0.5),
        reason=TruncationReason.LOSS_STOP,
        b_eff=1.96,
        b_fut=-1.96,
        total_pnl=Decimal(-60),
        cell_dead=False,
    )
    assert verdict == "KILL"


@pytest.mark.parametrize("reason", [TruncationReason.D0_165, TruncationReason.I_MAX])
def test_interior_band_is_fail_closed_to_kill(reason: TruncationReason) -> None:
    verdict = terminal_look(
        _state(0.0),  # b_fut=-1.96 < 0.0 < b_eff=1.96
        reason=reason,
        b_eff=1.96,
        b_fut=-1.96,
        total_pnl=Decimal(5),
        cell_dead=False,
    )
    assert verdict == "KILL"


@pytest.mark.parametrize("reason", [TruncationReason.D0_165, TruncationReason.I_MAX])
def test_survive_requires_s_at_or_above_b_eff_and_positive_pnl_and_no_cell_dead(
    reason: TruncationReason,
) -> None:
    verdict = terminal_look(
        _state(2.0),
        reason=reason,
        b_eff=1.96,
        b_fut=-1.96,
        total_pnl=Decimal(5),
        cell_dead=False,
    )
    assert verdict == "SURVIVE"


@pytest.mark.parametrize(
    ("total_pnl", "cell_dead"),
    [
        (Decimal(-1), False),
        (Decimal(5), True),
    ],
)
@pytest.mark.parametrize("reason", [TruncationReason.D0_165, TruncationReason.I_MAX])
def test_survive_is_refused_at_s_above_b_eff_if_pnl_or_cell_dead_fail(
    reason: TruncationReason, total_pnl: Decimal, cell_dead: bool
) -> None:
    verdict = terminal_look(
        _state(2.0),
        reason=reason,
        b_eff=1.96,
        b_fut=-1.96,
        total_pnl=total_pnl,
        cell_dead=cell_dead,
    )
    assert verdict == "KILL"


@pytest.mark.parametrize("reason", [TruncationReason.D0_165, TruncationReason.I_MAX])
def test_kill_when_s_at_or_below_b_fut(reason: TruncationReason) -> None:
    verdict = terminal_look(
        _state(-2.0),
        reason=reason,
        b_eff=1.96,
        b_fut=-1.96,
        total_pnl=Decimal(5),
        cell_dead=False,
    )
    assert verdict == "KILL"


def test_truncation_reason_members() -> None:
    assert {member.value for member in TruncationReason} == {
        "D0_165",
        "LOSS_STOP",
        "I_MAX",
    }


def test_truncation_reason_is_a_str_enum() -> None:
    assert TruncationReason.D0_165 == "D0_165"
    assert isinstance(TruncationReason.D0_165, str)
