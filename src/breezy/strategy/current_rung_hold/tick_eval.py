"""Shared eligible-snapshot → ``Decision`` evaluation for rung-hold families.

Extracted from ``CurrentRungHoldStrategy.on_quote_tick`` so v2 and v3 share
the same evaluate path. ``observation_ambiguous`` return-before-consume stays
in the v2 strategy (ARCH condition (a)): hoisting it here would change v2's
consume-site ordering.

This module is PURE: no Nautilus, no I/O, no clock. ``evaluate_decision`` is
the frozen take test (``decision.py``) -- never reimplemented here.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from breezy.domain.season import season_for
from breezy.domain.weather_bucket_facts import WeatherBucketFacts
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.decision import (
    Decision,
    DecisionInputs,
    Refuse,
    RungBounds,
    evaluate_decision,
)
from breezy.strategy.weather_common.running_extreme import RunningMax

__all__ = [
    "WIDTH_INTERIOR",
    "WIDTH_OPEN_LOWER",
    "WIDTH_OPEN_UPPER",
    "build_eligible_inputs",
    "evaluate_eligible_snapshot",
    "instrument_rung_is_current",
    "width_and_m",
]

WIDTH_INTERIOR: int = 0
WIDTH_OPEN_UPPER: int = 1
WIDTH_OPEN_LOWER: int = 2


def width_and_m(facts: WeatherBucketFacts, running_max: RunningMax) -> tuple[int, int]:
    """Legal-cell ``(width_code, m_code)`` for this instrument vs ``running_max``."""
    if facts.upper_f is None:
        return WIDTH_OPEN_UPPER, 0
    if facts.lower_f is None:
        return WIDTH_OPEN_LOWER, 0
    return WIDTH_INTERIOR, running_max.lower_f - facts.lower_f


def instrument_rung_is_current(facts: WeatherBucketFacts, running_max: RunningMax) -> bool:
    """True when the observation interval TOUCHES this instrument's rung."""
    return facts.contains(running_max.lower_f) or facts.contains(running_max.upper_f)


def build_eligible_inputs(
    *,
    station: str,
    climate_day: date,
    now_ns: int,
    ladder: Sequence[RungBounds],
    fee_coefficient: Decimal | None,
    ask: Decimal,
    size: int,
    running_max: RunningMax,
    staleness_ns: int | None,
    config: CurrentRungHoldConfig,
    hour_lst: int,
    width_code: int,
    m_code: int,
) -> DecisionInputs | Refuse:
    """Build ``DecisionInputs`` for an already-eligible snapshot, or F1 Refuse."""
    if fee_coefficient is None:
        return Refuse("fee_schedule_mismatch")
    return DecisionInputs(
        station=station,
        climate_day=climate_day,
        now_ns=now_ns,
        ladder=ladder,
        fee_coefficient=fee_coefficient,
        ask=ask,
        size=size,
        running_max=running_max,
        staleness_ns=staleness_ns,
        config=config,
        season=season_for(climate_day),
        hour_lst=hour_lst,
        width_code=width_code,
        m_code=m_code,
        latch_consumed=False,
    )


def evaluate_eligible_snapshot(
    *,
    station: str,
    climate_day: date,
    now_ns: int,
    ladder: Sequence[RungBounds],
    fee_coefficient: Decimal | None,
    ask: Decimal,
    size: int,
    running_max: RunningMax,
    staleness_ns: int | None,
    config: CurrentRungHoldConfig,
    hour_lst: int,
    width_code: int,
    m_code: int,
) -> Decision:
    """Evaluate one already-eligible snapshot (WAIT gates already passed).

    ``fee_coefficient is None`` is Barrier F1: same counted refusal
    ``evaluate_decision`` emits for a known-but-mismatched coefficient.
    """
    built = build_eligible_inputs(
        station=station,
        climate_day=climate_day,
        now_ns=now_ns,
        ladder=ladder,
        fee_coefficient=fee_coefficient,
        ask=ask,
        size=size,
        running_max=running_max,
        staleness_ns=staleness_ns,
        config=config,
        hour_lst=hour_lst,
        width_code=width_code,
        m_code=m_code,
    )
    if isinstance(built, Refuse):
        return built
    return evaluate_decision(built)
