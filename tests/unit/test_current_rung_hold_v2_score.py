"""RED-first: `breezy.settlement.current_rung_hold_v2.score`/`information_fraction`.

`docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md` rev b Sec 3,
`docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md` Sec "Tests".
"""

from __future__ import annotations

import math
from decimal import Decimal

import pytest

from breezy.settlement.current_rung_hold_v2 import (
    ScoreState,
    StratumRow,
    break_even_row,
    information_fraction,
    score,
)

FEE_THETA = Decimal("0.06")


def _row(
    entry_ask: str, held: bool, *, fee_theta: Decimal = FEE_THETA, station: str = "MIA"
) -> StratumRow:
    ask = Decimal(entry_ask)
    fee = fee_theta * ask * (1 - ask)
    return StratumRow(entry_ask=ask, fee=fee, held=held, station=station)


def test_break_even_row_is_ask_plus_fee() -> None:
    ask = Decimal("0.20")
    fee = Decimal("0.01")
    assert break_even_row(ask, fee) == Decimal("0.21")


def test_score_matches_a_hand_computed_three_row_fixture_to_1e_12() -> None:
    # asks 0.10 / 0.50 / 0.90 at theta = 0.06 (docs/specs rev b Sec 5 example).
    rows = (
        _row("0.10", held=True),
        _row("0.50", held=False),
        _row("0.90", held=True),
    )
    bes = [float(break_even_row(r.entry_ask, r.fee)) for r in rows]
    expected_information = sum(be * (1.0 - be) for be in bes)
    expected_s = sum(
        (1.0 if r.held else 0.0) - be for r, be in zip(rows, bes, strict=True)
    ) / math.sqrt(expected_information)

    state = score(rows)

    assert state.n == 3
    assert math.isclose(state.information, expected_information, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(state.s, expected_s, rel_tol=0, abs_tol=1e-12)


def test_information_is_strictly_less_than_n_times_pi_bar_one_minus_pi_bar() -> None:
    """The concavity the ruling turned on: `n*pi_bar(1-pi_bar) >= Sum BE_i(1-BE_i)`,
    strict whenever the per-row `BE_i` actually vary."""
    rows = (
        _row("0.10", held=True),
        _row("0.50", held=False),
        _row("0.90", held=True),
        _row("0.30", held=True),
    )
    bes = [float(break_even_row(r.entry_ask, r.fee)) for r in rows]
    n = len(rows)
    pi_bar = sum(bes) / n
    plug_in_variance = n * pi_bar * (1.0 - pi_bar)

    state = score(rows)

    assert state.information < plug_in_variance


def test_score_raises_value_error_when_information_is_zero() -> None:
    with pytest.raises(ValueError):
        score(())


def test_score_raises_value_error_when_every_be_is_degenerate() -> None:
    # BE_i in {0.0, 1.0} makes each be*(1-be) term zero -> I == 0.
    rows = (StratumRow(entry_ask=Decimal(0), fee=Decimal(0), held=True, station="MIA"),)
    with pytest.raises(ValueError):
        score(rows)


def test_mixed_theta_fixture_uses_per_row_be_not_a_single_theta_break_even() -> None:
    """Rows with fees from theta=0.06 and theta=0.07 in one stratum: the
    per-row BE_i differ even at the same ask, and `score()` must use each
    row's own BE_i, never re-derive a single-theta break_even(mean_ask)."""
    ask = Decimal("0.30")
    row_a = StratumRow(
        entry_ask=ask, fee=Decimal("0.06") * ask * (1 - ask), held=True, station="MIA"
    )
    row_b = StratumRow(
        entry_ask=ask, fee=Decimal("0.07") * ask * (1 - ask), held=False, station="LAX"
    )

    assert row_a.fee != row_b.fee

    state = score((row_a, row_b))

    be_a = float(break_even_row(row_a.entry_ask, row_a.fee))
    be_b = float(break_even_row(row_b.entry_ask, row_b.fee))
    expected_information = be_a * (1 - be_a) + be_b * (1 - be_b)
    expected_s = ((1.0 - be_a) + (0.0 - be_b)) / math.sqrt(expected_information)

    assert math.isclose(state.information, expected_information, abs_tol=1e-12)
    assert math.isclose(state.s, expected_s, abs_tol=1e-12)


def test_information_fraction_is_the_min_of_one_and_the_ratio() -> None:
    assert information_fraction(10.0, i_max=40.0) == pytest.approx(0.25)
    assert information_fraction(40.0, i_max=40.0) == pytest.approx(1.0)
    assert information_fraction(80.0, i_max=40.0) == 1.0


def test_information_fraction_never_exceeds_one_even_when_information_overshoots() -> None:
    assert information_fraction(1_000_000.0, i_max=40.0) == 1.0


def test_score_state_is_a_frozen_dataclass_with_s_information_n() -> None:
    state = ScoreState(s=1.0, information=2.0, n=3)
    assert (state.s, state.information, state.n) == (1.0, 2.0, 3)
    with pytest.raises(Exception):  # noqa: B017 -- frozen dataclass raises FrozenInstanceError
        state.s = 5.0  # type: ignore[misc]
