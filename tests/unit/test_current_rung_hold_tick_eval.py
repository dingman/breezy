"""Direct unit tests for ``tick_eval.py``'s pure functions.

``tick_eval.py`` is the shared v2/v3 eligible-snapshot evaluate path
(module docstring); prior coverage was only indirect, through the two
strategies' ``on_quote_tick`` integration tests. These exercise
``build_eligible_inputs``, ``instrument_rung_is_current``, and
``width_and_m`` directly, with no Nautilus wiring.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from breezy.domain.season import season_for
from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.decision import DecisionInputs, Refuse
from breezy.strategy.current_rung_hold.tick_eval import (
    WIDTH_INTERIOR,
    WIDTH_OPEN_LOWER,
    WIDTH_OPEN_UPPER,
    build_eligible_inputs,
    instrument_rung_is_current,
    width_and_m,
)
from breezy.strategy.weather_common.running_extreme import RunningMax

_STATION = "LAX"
_CLIMATE_DAY = date(2026, 9, 11)


def _facts(*, lower_f: int | None, upper_f: int | None) -> WeatherBucketFacts:
    return WeatherBucketFacts(
        settlement_station=_STATION,
        climate_day=_CLIMATE_DAY,
        measure=Measure.HIGH,
        lower_f=lower_f,
        upper_f=upper_f,
    )


def _running_max(lower_f: int, upper_f: int) -> RunningMax:
    return RunningMax(
        lower_f=lower_f,
        upper_f=upper_f,
        exact_f=lower_f if lower_f == upper_f else None,
        source_observed_at_ns=1,
        source_received_at_ns=1,
    )


# --- width_and_m -------------------------------------------------------


def test_width_and_m_open_upper_tail_is_width_open_upper_m_zero() -> None:
    facts = _facts(lower_f=80, upper_f=None)
    running_max = _running_max(80, 80)
    assert width_and_m(facts, running_max) == (WIDTH_OPEN_UPPER, 0)


def test_width_and_m_open_lower_tail_is_width_open_lower_m_zero() -> None:
    facts = _facts(lower_f=None, upper_f=79)
    running_max = _running_max(79, 79)
    assert width_and_m(facts, running_max) == (WIDTH_OPEN_LOWER, 0)


def test_width_and_m_interior_m_code_is_the_margin_from_running_max() -> None:
    facts = _facts(lower_f=80, upper_f=81)
    on_rung = _running_max(80, 80)
    assert width_and_m(facts, on_rung) == (WIDTH_INTERIOR, 0)

    one_off = _running_max(81, 81)
    assert width_and_m(facts, one_off) == (WIDTH_INTERIOR, 1)


# --- instrument_rung_is_current -----------------------------------------


def test_instrument_rung_is_current_true_when_lower_f_touches() -> None:
    facts = _facts(lower_f=80, upper_f=81)
    running_max = _running_max(79, 80)
    assert instrument_rung_is_current(facts, running_max) is True


def test_instrument_rung_is_current_true_when_upper_f_touches() -> None:
    facts = _facts(lower_f=80, upper_f=81)
    running_max = _running_max(81, 82)
    assert instrument_rung_is_current(facts, running_max) is True


def test_instrument_rung_is_current_false_for_a_non_current_rung() -> None:
    """The observation interval falls wholly outside this instrument's
    bucket -- neither endpoint touches it, so this is not (yet) the
    current rung."""
    facts = _facts(lower_f=80, upper_f=81)
    running_max = _running_max(90, 91)
    assert instrument_rung_is_current(facts, running_max) is False


# --- build_eligible_inputs -----------------------------------------------


def test_build_eligible_inputs_f1_refusal_when_fee_coefficient_is_none() -> None:
    """Barrier F1: an unresolved fee coefficient folds into a `Refuse`
    here, never reaching `DecisionInputs` construction."""
    result = build_eligible_inputs(
        station=_STATION,
        climate_day=_CLIMATE_DAY,
        now_ns=1,
        ladder=((80, 81),),
        fee_coefficient=None,
        ask=Decimal("0.40"),
        size=10,
        running_max=_running_max(80, 80),
        staleness_ns=0,
        config=CurrentRungHoldConfig(),
        hour_lst=12,
        width_code=WIDTH_INTERIOR,
        m_code=0,
    )
    assert result == Refuse("fee_schedule_mismatch")


def test_build_eligible_inputs_builds_decision_inputs_when_fee_coefficient_is_known() -> None:
    config = CurrentRungHoldConfig()
    result = build_eligible_inputs(
        station=_STATION,
        climate_day=_CLIMATE_DAY,
        now_ns=1_000,
        ladder=((80, 81),),
        fee_coefficient=Decimal("0.06"),
        ask=Decimal("0.40"),
        size=10,
        running_max=_running_max(80, 80),
        staleness_ns=0,
        config=config,
        hour_lst=12,
        width_code=WIDTH_INTERIOR,
        m_code=0,
    )
    assert isinstance(result, DecisionInputs)
    assert result.station == _STATION
    assert result.climate_day == _CLIMATE_DAY
    assert result.fee_coefficient == Decimal("0.06")
    assert result.ask == Decimal("0.40")
    assert result.config is config
    assert result.season == season_for(_CLIMATE_DAY)
    assert result.width_code == WIDTH_INTERIOR
    assert result.m_code == 0
    # Always False here: the caller (v2/v3's on_quote_tick) is the ONLY
    # place that ever knows the latch state; this builder never does.
    assert result.latch_consumed is False
