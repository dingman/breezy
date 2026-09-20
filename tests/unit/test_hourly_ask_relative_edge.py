"""RED-first tests for the hourly ask-relative edge measurement.

Four guards carry the whole value of this work package and each has its own
test here: the strict as-of leakage assertion, the complete-partition refusal,
the ONE pre-declared instant per (station, day, hour) rule, and the fee
arithmetic at the venue's current coefficient.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import pytest

_ANALYSIS = Path(__file__).resolve().parents[2] / "scripts" / "analysis"
if str(_ANALYSIS) not in sys.path:
    sys.path.insert(0, str(_ANALYSIS))

from h4_preliminary_economic_read import DepthObservation, Rung
from hourly_ask_relative_edge import (
    TAKER_FEE_COEFFICIENT,
    AsOfViolation,
    LadderNotAPartitionError,
    assert_as_of,
    assert_complete_partition,
    claimed_edge,
    first_liftable_quote,
    holm_adjusted,
    hour_window_bounds,
    realised_pnl_per_contract,
    take_fee,
)


def _rung(lower: int | None, upper: int | None) -> Rung:
    if lower is None:
        band = f"lt{(upper or 0) + 1}f"
    elif upper is None:
        band = f"gte{lower}f"
    else:
        band = f"gte{lower}lt{upper}f"
    return Rung(
        instrument_id=f"tc-temp-sfohigh-2026-09-01-{band}",
        city="SFO",
        climate_day=dt.date(2026, 9, 1),
        lower_f=lower,
        upper_f=upper,
    )


def _obs(minute: int, ask: float | None, size: float, bid: float | None = None) -> DepthObservation:
    return DepthObservation(
        instrument_id="tc-temp-sfohigh-2026-09-01-gte70lt71f",
        ts_event=dt.datetime(2026, 9, 1, 19, minute, tzinfo=dt.UTC),
        best_ask=ask,
        ask_ladder=None if ask is None else ((ask, size),),
        best_bid=bid,
    )


# -- 1. the leakage guard ---------------------------------------------------


def test_assert_as_of_raises_when_the_reference_postdates_the_decision() -> None:
    with pytest.raises(AsOfViolation, match="as-of"):
        assert_as_of(reference_ts_ns=1_000_000_001, decision_ts_ns=1_000_000_000, context="SFO")


def test_assert_as_of_accepts_a_reference_at_the_decision_instant() -> None:
    assert assert_as_of(reference_ts_ns=7, decision_ts_ns=7, context="SFO") is None


def test_the_hour_window_is_scoped_by_date_and_hour_never_hour_alone() -> None:
    start, end = hour_window_bounds(
        climate_day=dt.date(2026, 9, 1), hour_lst=14, std_utc_offset_hours=-8.0
    )
    assert start == dt.datetime(2026, 9, 1, 22, tzinfo=dt.UTC)
    assert end == dt.datetime(2026, 9, 1, 23, tzinfo=dt.UTC)
    # The same LST hour on the NEXT date is a disjoint window -- the WP-7 C2
    # artefact came from a filter that was hour-of-day over a D-1..D+1 tape.
    next_start, _ = hour_window_bounds(
        climate_day=dt.date(2026, 9, 2), hour_lst=14, std_utc_offset_hours=-8.0
    )
    assert next_start == end + dt.timedelta(hours=23)


# -- 2. the complete-partition refusal --------------------------------------


def test_assert_complete_partition_accepts_a_contiguous_ladder() -> None:
    assert_complete_partition(
        (_rung(None, 69), _rung(70, 71), _rung(72, 73), _rung(74, None))
    )


def test_assert_complete_partition_refuses_a_gap_in_the_interiors() -> None:
    with pytest.raises(LadderNotAPartitionError, match="gap"):
        assert_complete_partition((_rung(None, 69), _rung(70, 71), _rung(74, None)))


def test_assert_complete_partition_refuses_a_ladder_with_no_open_lower_tail() -> None:
    with pytest.raises(LadderNotAPartitionError, match="open lower"):
        assert_complete_partition((_rung(70, 71), _rung(72, 73), _rung(74, None)))


# -- 3. ONE pre-declared instant, never an argmax ---------------------------


def test_first_liftable_quote_returns_the_first_never_the_cheapest() -> None:
    rows = (
        _obs(5, 0.60, 12.0),
        _obs(10, 0.10, 99.0),
        _obs(20, 0.08, 99.0),
    )
    chosen = first_liftable_quote(
        rows,
        start=dt.datetime(2026, 9, 1, 19, 0, tzinfo=dt.UTC),
        end=dt.datetime(2026, 9, 1, 20, 0, tzinfo=dt.UTC),
    )
    assert chosen is not None
    assert chosen.best_ask == 0.60


def test_first_liftable_quote_skips_unliftable_rows_then_takes_the_first_liftable() -> None:
    rows = (
        _obs(1, None, 0.0),
        _obs(2, 0.60, 0.0),
        _obs(3, 0.99, 50.0),
        _obs(4, 0.42, 3.0),
        _obs(5, 0.11, 90.0),
    )
    chosen = first_liftable_quote(
        rows,
        start=dt.datetime(2026, 9, 1, 19, 0, tzinfo=dt.UTC),
        end=dt.datetime(2026, 9, 1, 20, 0, tzinfo=dt.UTC),
    )
    assert chosen is not None
    assert chosen.best_ask == 0.42


def test_first_liftable_quote_ignores_rows_outside_the_window() -> None:
    rows = (_obs(5, 0.40, 10.0),)
    assert (
        first_liftable_quote(
            rows,
            start=dt.datetime(2026, 9, 1, 20, 0, tzinfo=dt.UTC),
            end=dt.datetime(2026, 9, 1, 21, 0, tzinfo=dt.UTC),
        )
        is None
    )


# -- 4. the fee arithmetic --------------------------------------------------


def test_the_fee_coefficient_is_the_venues_current_theta() -> None:
    assert TAKER_FEE_COEFFICIENT == 0.0695


@pytest.mark.parametrize(
    ("ask", "expected"),
    [(0.05, 0.00), (0.10, 0.01), (0.30, 0.01), (0.50, 0.02), (0.62, 0.02), (0.90, 0.01)],
)
def test_take_fee_is_banker_rounded_to_the_cent_at_theta_0_0695(
    ask: float, expected: float
) -> None:
    assert take_fee(ask) == pytest.approx(expected)


def test_claimed_edge_is_p_bound_minus_ask_plus_fee() -> None:
    assert claimed_edge(p_bound=0.70, ask=0.50) == pytest.approx(0.70 - 0.50 - 0.02)


def test_realised_pnl_pays_one_on_a_hold_and_zero_otherwise() -> None:
    assert realised_pnl_per_contract(ask=0.50, held=True) == pytest.approx(1.0 - 0.50 - 0.02)
    assert realised_pnl_per_contract(ask=0.50, held=False) == pytest.approx(-0.52)


# -- 5. multiplicity --------------------------------------------------------


def test_holm_adjusts_in_rank_order_and_is_monotone() -> None:
    adjusted = holm_adjusted((0.01, 0.04, 0.03))
    assert adjusted[0] == pytest.approx(0.03)
    assert adjusted[1] == pytest.approx(0.06)
    assert adjusted[2] == pytest.approx(0.06)
    assert all(value <= 1.0 for value in adjusted)


# -- 6. an hour with too few clusters is UNDERPOWERED, never significant ----


def test_the_minimum_cluster_floor_is_the_programmes_existing_fifteen() -> None:
    from hourly_ask_relative_edge import MIN_CLUSTERS_TO_SCORE

    assert MIN_CLUSTERS_TO_SCORE == 15


def test_partition_powered_excludes_hours_below_the_cluster_floor() -> None:
    from hourly_ask_relative_edge import partition_powered

    by_hour = {
        9: ["row"] * 15,
        18: ["row"] * 1,
        23: ["row"] * 14,
    }
    powered, underpowered = partition_powered(by_hour)
    assert sorted(powered) == [9]
    assert sorted(underpowered) == [18, 23]


def test_a_single_cluster_hour_can_never_enter_the_holm_family() -> None:
    """A percentile bootstrap over ONE cluster returns that cluster's own mean
    on every draw, so its interval has zero width and its p-value pins at the
    1/B floor. Reported unguarded, hours 17..23 of the first run each showed a
    'Holm-significant' result off n=1. That is an artefact of the resampler,
    not a measurement."""
    from hourly_ask_relative_edge import partition_powered

    powered, underpowered = partition_powered({18: ["row"]})
    assert powered == {}
    assert 18 in underpowered


# -- 7. open-lower refusals are NOT 'below N_MIN' --------------------------


def test_the_open_lower_tail_has_its_own_refusal_reason() -> None:
    from hourly_ask_relative_edge import (
        REASON_OPEN_LOWER_NOT_TABULATED,
        REASON_P_BOUND_UNDEFINED,
        REFUSAL_REASONS,
    )

    assert REASON_OPEN_LOWER_NOT_TABULATED in REFUSAL_REASONS
    assert REASON_OPEN_LOWER_NOT_TABULATED != REASON_P_BOUND_UNDEFINED
