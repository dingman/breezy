"""RED-first: `breezy.settlement.current_rung_hold_v2.score`/`information_fraction`.

`docs/specs/PREREG_v2_current_rung_hold_DRAFT_2026-09-04.md` rev b Sec 3,
`docs/plans/FAMILY_TALLY_V2_BLUEPRINT_2026-09-04.md` Sec "Tests".
"""

from __future__ import annotations

import itertools
import math
from decimal import Decimal

import pytest

from breezy.settlement.current_rung_hold_v2 import (
    CombinedDraw,
    ScoreState,
    StationDayAdmissionRefusal,
    StratumRow,
    break_even_row,
    combine_station_day,
    information_fraction,
    score,
    score_combined,
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


# ---------------------------------------------------------------------------
# S4a (plan MULTI_POSITION_PER_STATION_2026-09-14, R3-2/R3-3): the
# station-day combined draw under the exact mutual-exclusivity variance.
# ---------------------------------------------------------------------------
def test_a_single_fill_station_day_is_byte_identical_to_today() -> None:
    """Regression floor (R3-2 merge gate): k=1, qty=1 -- `combine_station_day`
    plus `score_combined` over one draw per station-day must match `score()`
    over the raw rows exactly."""
    rows = (
        _row("0.10", held=True),
        _row("0.50", held=False),
        _row("0.90", held=True),
    )
    direct = score(rows)
    combined = tuple(combine_station_day((row,)) for row in rows)
    via_combined = score_combined(combined)

    assert via_combined.n == direct.n
    assert math.isclose(via_combined.information, direct.information, abs_tol=1e-12)
    assert math.isclose(via_combined.s, direct.s, abs_tol=1e-12)


def test_two_rung_fills_on_one_station_day_are_one_draw() -> None:
    """Numerically pinned example (R3-3): BE 0.30 and 0.20, held (1, 0) ->
    X=0.5, Var = 0.21 + 0.16 - 2*0.06 = 0.25."""
    row_a = StratumRow(entry_ask=Decimal("0.30"), fee=Decimal(0), held=True, station="MIA")
    row_b = StratumRow(entry_ask=Decimal("0.20"), fee=Decimal(0), held=False, station="MIA")

    draw = combine_station_day((row_a, row_b))

    assert draw.n_constituents == 2
    assert math.isclose(draw.x, 0.5, abs_tol=1e-12)
    assert math.isclose(draw.variance, 0.25, abs_tol=1e-12)

    state = score_combined((draw,))
    assert state.n == 1


def test_the_combined_draw_variance_uses_the_mutual_exclusivity_covariance() -> None:
    """Three mutually exclusive rungs: Var = Sum BE_i(1-BE_i) - 2*Sum_{i<j} BE_i*BE_j."""
    bes = (Decimal("0.10"), Decimal("0.20"), Decimal("0.15"))
    held = (True, False, False)
    rows = tuple(
        StratumRow(entry_ask=be, fee=Decimal(0), held=h, station="MIA")
        for be, h in zip(bes, held, strict=True)
    )

    draw = combine_station_day(rows)

    bes_f = [float(b) for b in bes]
    expected_variance = sum(b * (1 - b) for b in bes_f)
    for i in range(3):
        for j in range(i + 1, 3):
            expected_variance -= 2 * bes_f[i] * bes_f[j]
    expected_x = sum(
        (1.0 if h else 0.0) - b for h, b in zip(held, bes_f, strict=True)
    )

    assert math.isclose(draw.variance, expected_variance, abs_tol=1e-12)
    assert math.isclose(draw.x, expected_x, abs_tol=1e-12)


def test_the_draw_is_a_function_of_a_qty_parameter_fixed_at_one() -> None:
    """R3-2: qty is a wired PARAMETER (default 1), never a literal average --
    proven by varying it, even though Increment A never passes qty != 1 in
    a real caller."""
    row_a = StratumRow(entry_ask=Decimal("0.30"), fee=Decimal(0), held=True, station="MIA")
    row_b = StratumRow(entry_ask=Decimal("0.20"), fee=Decimal(0), held=False, station="MIA")
    baseline = combine_station_day((row_a, row_b))

    row_a_qty2 = StratumRow(
        entry_ask=Decimal("0.30"), fee=Decimal(0), held=True, station="MIA", qty=Decimal(2),
    )
    weighted = combine_station_day((row_a_qty2, row_b))

    be_a, be_b = 0.30, 0.20
    expected_x = 2 * (1.0 - be_a) + 1 * (0.0 - be_b)
    expected_variance = (
        (2**2) * be_a * (1 - be_a) + (1**2) * be_b * (1 - be_b) - 2 * 2 * 1 * be_a * be_b
    )

    assert math.isclose(weighted.x, expected_x, abs_tol=1e-12)
    assert math.isclose(weighted.variance, expected_variance, abs_tol=1e-12)
    assert weighted.x != baseline.x
    assert weighted.variance != baseline.variance


def test_a_station_day_whose_bes_sum_above_one_is_refused_as_malformed_input() -> None:
    row_a = StratumRow(entry_ask=Decimal("0.60"), fee=Decimal(0), held=True, station="MIA")
    row_b = StratumRow(entry_ask=Decimal("0.55"), fee=Decimal(0), held=False, station="MIA")

    with pytest.raises(StationDayAdmissionRefusal):
        combine_station_day((row_a, row_b))


def test_combine_station_day_raises_value_error_on_empty_rows() -> None:
    with pytest.raises(ValueError):
        combine_station_day(())


def test_score_combined_raises_value_error_when_information_is_zero() -> None:
    with pytest.raises(ValueError):
        score_combined(())


def test_combined_draw_is_a_frozen_dataclass() -> None:
    draw = CombinedDraw(x=1.0, variance=2.0, n_constituents=1)
    assert (draw.x, draw.variance, draw.n_constituents) == (1.0, 2.0, 1)
    with pytest.raises(Exception):  # noqa: B017 -- frozen dataclass raises FrozenInstanceError
        draw.x = 5.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Increment A validation slice (plan MULTI_POSITION_PER_STATION_2026-09-14,
# Rev 3 disposition R3-3): closed-form reductions and the non-negativity
# property, missing from S4a's own test set above.
# ---------------------------------------------------------------------------
def test_the_combined_variance_reduces_to_bernoulli_at_k_equals_one() -> None:
    """k=1, qty=1: `combine_station_day`'s variance/x collapse exactly to
    `BE*(1-BE)`/`held-BE` -- the single-row Bernoulli terms `score()` itself
    uses (regression floor, restated in isolation from the full
    `test_a_single_fill_station_day_is_byte_identical_to_today` fixture)."""
    row = StratumRow(entry_ask=Decimal("0.35"), fee=Decimal("0.02"), held=True, station="MIA")
    draw = combine_station_day((row,))
    be = float(break_even_row(row.entry_ask, row.fee))

    assert draw.n_constituents == 1
    assert math.isclose(draw.variance, be * (1.0 - be), abs_tol=1e-12)
    assert math.isclose(draw.x, 1.0 - be, abs_tol=1e-12)


def test_the_combined_variance_scales_with_qty_squared() -> None:
    """k=1, qty=3: variance scales as `qty^2 * BE*(1-BE)` -- the dollar-
    variance scaling PnL itself needs (R3-3), qty=1's reduction above being
    the qty=1 special case of this same formula."""
    row = StratumRow(
        entry_ask=Decimal("0.35"),
        fee=Decimal("0.02"),
        held=True,
        station="MIA",
        qty=Decimal(3),
    )
    draw = combine_station_day((row,))
    be = float(break_even_row(row.entry_ask, row.fee))

    assert math.isclose(draw.variance, 9.0 * be * (1.0 - be), abs_tol=1e-12)
    assert math.isclose(draw.x, 3.0 * (1.0 - be), abs_tol=1e-12)


def test_variance_is_non_negative_for_every_admissible_station_day() -> None:
    """Property (R3-3 admission gate, qty=1): for every admissible
    station-day (`Sum BE_i <= 1`, `k <= 4`), the covariance-subtracted
    `Var_H0(X_sd)` must be `>= 0`. Algebraically `Var = S - S**2` where
    `S = Sum BE_i` (the cross terms collapse `Sum BE_i**2 + 2*Sum_{i<j}
    BE_i*BE_j` into `S**2` exactly), so this is a property of a perfect
    square and can never go negative for `S` in `[0, 1]` -- a grid search
    over BE tuples up to k=4 (step 0.1) is the check; ANY negative Var here
    is a BLOCKER, reported and never papered over."""
    be_values = [i / 10 for i in range(11)]
    checked = 0
    for k in range(1, 5):
        for combo in itertools.product(be_values, repeat=k):
            if sum(combo) > 1.0 + 1e-9:
                continue
            rows = tuple(
                StratumRow(entry_ask=Decimal(str(be)), fee=Decimal(0), held=False, station="MIA")
                for be in combo
            )
            draw = combine_station_day(rows)
            assert draw.variance >= -1e-9, (
                f"BLOCKER: negative Var_H0 at BE tuple {combo!r}: {draw.variance!r}"
            )
            checked += 1
    assert checked > 0
