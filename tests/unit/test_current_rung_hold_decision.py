"""Tests for the ``current_rung_hold`` PURE decision function
(src/breezy/strategy/current_rung_hold/decision.py, build order step 5).

Covers every refusal reason in :data:`REFUSAL_REASONS`, the worked ``Take``
example from the dispatch brief (ask ``0.40``, fee ``0.06*0.40*0.60 ==
0.0144`` -> ``$0.01``, break-even ``0.41``), and a table-driven test proving
the refusal precedence order the module docstring pins.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal

import pytest

from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.decision import (
    REFUSAL_REASONS,
    DecisionInputs,
    Refuse,
    Take,
    evaluate_decision,
)
from breezy.strategy.weather_common.running_extreme import RunningMax

#: A three-rung ladder: an open-lower tail, one 2F interior rung (`[70, 71]`),
#: and an open-upper tail -- closed-closed, matching `WeatherBucketFacts`.
_LADDER: tuple[tuple[int | None, int | None], ...] = ((None, 69), (70, 71), (72, None))

#: `(LAX, DJF, 12, interior_2F, m=0)` -> `Decimal("0.6585")` in the frozen
#: table (`archive_table.py`).
_STATION = "LAX"
_SEASON = "DJF"
_HOUR_LST = 12
_INTERIOR_WIDTH_CODE = 0
_M_ZERO = 0

_STALE_BOUND_NS = int(0.75 * 3_600_000_000_000)


def _exact_running_max(reading_f: int, *, source_observed_at_ns: int = 0) -> RunningMax:
    return RunningMax(
        lower_f=reading_f,
        upper_f=reading_f,
        exact_f=reading_f,
        source_observed_at_ns=source_observed_at_ns,
        source_received_at_ns=source_observed_at_ns,
    )


def _take_case_inputs(**overrides: object) -> DecisionInputs:
    """Every field set so the decision is a clean ``Take`` (worked example).

    ``ask=0.40`` against ``theta=0.06`` gives fee ``0.06*0.40*0.60 ==
    0.0144`` -> banker's-rounded ``$0.01`` -> break-even ``0.41``, and
    ``p_hold_lower == 0.6585`` (the frozen table's ``(LAX, DJF, 12, 0, 0)``
    cell) clears it.
    """
    base = DecisionInputs(
        station=_STATION,
        climate_day=dt.date(2026, 1, 15),
        now_ns=1_000_000_000,
        ladder=_LADDER,
        fee_coefficient=Decimal("0.06"),
        ask=Decimal("0.40"),
        size=5,
        running_max=_exact_running_max(70),
        staleness_ns=0,
        config=CurrentRungHoldConfig(),
        season=_SEASON,
        hour_lst=_HOUR_LST,
        width_code=_INTERIOR_WIDTH_CODE,
        m_code=_M_ZERO,
        latch_consumed=False,
    )
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


def test_refusal_reasons_is_the_closed_set_from_the_brief() -> None:
    assert REFUSAL_REASONS == frozenset(
        {
            "observation_unavailable",
            "observation_ambiguous",
            "fee_schedule_mismatch",
            "trial_day_consumed",
            "illegal_cell",
            "not_executable",
            "p_hold_undefined",
            "edge_below_break_even",
            # Strategy-layer reason (`strategy.py`, build order step 6):
            # widened here (never emitted by `evaluate_decision` itself) so
            # the trial-day latch's closed reason set covers it too -- see
            # `decision.py`'s `REFUSAL_REASONS` comment.
            "outside_decision_window",
            # Strategy-layer reason (`strategy.py`'s `on_start`): a
            # configured instrument id absent from the cache at start-up
            # (L-23) is a counted, skipped refusal, never fatal to its
            # sibling instruments -- widened here for the same reason
            # `outside_decision_window` was.
            "instrument_unresolved",
        }
    )


def test_the_worked_take_example_matches_the_brief() -> None:
    decision = evaluate_decision(_take_case_inputs())
    assert decision == Take(
        quantity=1,
        limit_price=Decimal("0.40"),
        p_hold_lower=Decimal("0.6585"),
        break_even=Decimal("0.41"),
        rung=(70, 71),
    )


def test_a_consumed_trial_day_is_refused() -> None:
    decision = evaluate_decision(_take_case_inputs(latch_consumed=True))
    assert decision == Refuse("trial_day_consumed")


def test_a_fee_coefficient_mismatch_is_refused() -> None:
    decision = evaluate_decision(_take_case_inputs(fee_coefficient=Decimal("0.05")))
    assert decision == Refuse("fee_schedule_mismatch")


def test_a_missing_running_max_is_refused_observation_unavailable() -> None:
    decision = evaluate_decision(
        _take_case_inputs(running_max=None, staleness_ns=None)
    )
    assert decision == Refuse("observation_unavailable")


def test_a_stale_running_max_is_refused_observation_unavailable() -> None:
    decision = evaluate_decision(_take_case_inputs(staleness_ns=_STALE_BOUND_NS + 1))
    assert decision == Refuse("observation_unavailable")


def test_a_running_max_exactly_at_the_stale_bound_is_not_refused() -> None:
    decision = evaluate_decision(_take_case_inputs(staleness_ns=_STALE_BOUND_NS))
    assert isinstance(decision, Take)


def test_a_running_max_spanning_two_rungs_is_refused_observation_ambiguous() -> None:
    spanning = RunningMax(
        lower_f=69,
        upper_f=70,
        exact_f=None,
        source_observed_at_ns=0,
        source_received_at_ns=0,
    )
    decision = evaluate_decision(_take_case_inputs(running_max=spanning))
    assert decision == Refuse("observation_ambiguous")


def test_an_exact_metar_reading_can_never_be_ambiguous() -> None:
    decision = evaluate_decision(_take_case_inputs(running_max=_exact_running_max(70)))
    assert isinstance(decision, Take)


def test_an_ask_at_or_below_the_executable_lower_bound_is_not_executable() -> None:
    decision = evaluate_decision(_take_case_inputs(ask=Decimal("0.05")))
    assert decision == Refuse("not_executable")


def test_an_ask_at_or_above_the_executable_upper_bound_is_not_executable() -> None:
    decision = evaluate_decision(_take_case_inputs(ask=Decimal("0.95")))
    assert decision == Refuse("not_executable")


def test_a_size_below_the_minimum_displayed_size_is_not_executable() -> None:
    decision = evaluate_decision(_take_case_inputs(size=0))
    assert decision == Refuse("not_executable")


def test_a_table_defined_cell_with_illegal_interior_margin_is_refused_illegal_cell() -> None:
    """`(LAX, DJF, 12, interior_2F, m=1)` IS defined in the frozen table
    (`Decimal("0.5197")`), and clears break-even against the default ask --
    proving this is a REAL escape route the legal-cell rule must close, not
    a hypothetical one. Legal ⟺ `(width_code == 0 AND m_code == 0)` OR
    `width_code == 1` (blueprint step 6; `archive_table.py`'s header). A
    cell existing in the table is never sufficient on its own -- the caller
    passing an out-of-policy key must still be refused, unforgeable by the
    caller (L-22).
    """
    decision = evaluate_decision(
        _take_case_inputs(width_code=_INTERIOR_WIDTH_CODE, m_code=1)
    )
    assert decision == Refuse("illegal_cell")


def test_open_lower_width_code_is_never_legal() -> None:
    """`width_code == 2` (`open_lower`) is never legal, regardless of
    `m_code`, and regardless of whether a cell happens to exist -- see
    `archive_table.py`'s header ("`width_code`: 0 = interior_2F, 1 =
    open_upper, 2 = open_lower") and the blueprint's binding LEGAL CELL rule.
    """
    decision = evaluate_decision(_take_case_inputs(width_code=2, m_code=0))
    assert decision == Refuse("illegal_cell")


def test_an_undefined_table_cell_is_refused_p_hold_undefined() -> None:
    # `(LAX, DJF, 12, open_upper, m=1)` has no cell in the frozen table --
    # `m_code` is fixed at 0 on the open tails, so `(1, 1)` was never
    # populated for this station/season/hour.
    decision = evaluate_decision(_take_case_inputs(width_code=1, m_code=1))
    assert decision == Refuse("p_hold_undefined")


def test_edge_below_break_even_is_refused_when_p_hold_lower_does_not_clear_it() -> None:
    # Same cell (`p_hold_lower == 0.6585`), a higher ask pushes break-even
    # above it: fee(0.80) = 0.06*0.80*0.20 = 0.0096 -> $0.01, BE = 0.81.
    decision = evaluate_decision(_take_case_inputs(ask=Decimal("0.80")))
    assert decision == Refuse("edge_below_break_even")


def test_first_executable_ask_is_the_only_candidate_even_if_a_later_ask_is_cheaper() -> None:
    """Not enforced here -- this module is stateless and pure; the ONE-TRIAL
    rule is the caller's latch (module docstring). This test pins that a
    single call only ever evaluates the snapshot it is given, never a
    history of asks -- so a cheaper later ask cannot retroactively change an
    already-returned decision.
    """
    first = evaluate_decision(_take_case_inputs(ask=Decimal("0.40")))
    cheaper_later = evaluate_decision(_take_case_inputs(ask=Decimal("0.30")))
    assert isinstance(first, Take)
    assert isinstance(cheaper_later, Take)
    assert first.limit_price != cheaper_later.limit_price


@pytest.mark.parametrize(
    ("overrides", "expected_reason"),
    [
        pytest.param(
            {
                "latch_consumed": True,
                "fee_coefficient": Decimal("0.05"),
                "running_max": None,
                "staleness_ns": None,
            },
            "trial_day_consumed",
            id="latch-beats-everything",
        ),
        pytest.param(
            {
                "fee_coefficient": Decimal("0.05"),
                "running_max": None,
                "staleness_ns": None,
            },
            "fee_schedule_mismatch",
            id="fee-mismatch-beats-missing-observation",
        ),
        pytest.param(
            {
                "running_max": None,
                "staleness_ns": None,
                "ask": Decimal("0.99"),
            },
            "observation_unavailable",
            id="missing-observation-beats-not-executable",
        ),
        pytest.param(
            {
                "running_max": RunningMax(
                    lower_f=69,
                    upper_f=70,
                    exact_f=None,
                    source_observed_at_ns=0,
                    source_received_at_ns=0,
                ),
                "ask": Decimal("0.99"),
            },
            "observation_ambiguous",
            id="ambiguous-observation-beats-not-executable",
        ),
        pytest.param(
            {
                "ask": Decimal("0.99"),
                "width_code": _INTERIOR_WIDTH_CODE,
                "m_code": 1,
            },
            "illegal_cell",
            id="illegal-cell-beats-not-executable",
        ),
        pytest.param(
            {
                "ask": Decimal("0.99"),
                "width_code": 1,
                "m_code": 1,
            },
            "not_executable",
            id="not-executable-beats-undefined-table-cell",
        ),
        pytest.param(
            {"width_code": 1, "m_code": 1},
            "p_hold_undefined",
            id="undefined-table-cell-beats-edge-below-break-even",
        ),
        pytest.param(
            {"width_code": _INTERIOR_WIDTH_CODE, "m_code": 1},
            "illegal_cell",
            id="illegal-cell-beats-edge-below-break-even-even-when-the-cell-is-defined",
        ),
        pytest.param(
            {"ask": Decimal("0.80")},
            "edge_below_break_even",
            id="edge-below-break-even-is-last",
        ),
    ],
)
def test_refusal_precedence_order(
    overrides: dict[str, object], expected_reason: str
) -> None:
    decision = evaluate_decision(_take_case_inputs(**overrides))
    assert decision == Refuse(expected_reason)


def test_a_refuse_reason_outside_the_closed_set_is_rejected() -> None:
    with pytest.raises(ValueError):
        Refuse("not_a_real_reason")
