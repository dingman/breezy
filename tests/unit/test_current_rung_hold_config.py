"""Tests for ``CurrentRungHoldConfig``
(src/breezy/strategy/current_rung_hold/config.py).

Covers the construction-time validations the blueprint's build order step 4
requires: NYC (hourly-only, A14) is refused, ``order_quantity`` must be
exactly 1, ``allow_short`` must stay False, and ``archive_table_pin`` must
match the frozen corpus sha the module actually ships
(``archive_table.CORPUS_SHA256``) -- never a second hard-coded copy of it.

Operator-reserved caps (maximum daily trading budget; maximum notional per
position) are NOT fields on this config -- they come from the operator's
own reserved control surface at runtime (see
``docs/plans/CURRENT_RUNG_HOLD_BLUEPRINT_2026-09-04.md`` §2). A test below
asserts no field name on this config LITERALLY matches a field name on
``breezy.strategy.weather_common.risk.RiskLimits`` -- the repo's one
canonical risk-cap dataclass, and every reserved-cap-shaped field name
(``max_position_contracts``, ``max_event_notional``, etc.) already lives
there. Comparing against its real field names (rather than an ad-hoc
substring list) is precise where a substring list is guesswork: it catches
any literal collision without maintaining a second, drifting vocabulary of
"looks like a cap" strings.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest

from breezy.strategy.current_rung_hold.archive_table import CORPUS_SHA256
from breezy.strategy.current_rung_hold.config import (
    AllowShortNotPermittedError,
    ArchiveTablePinMismatchError,
    CurrentRungHoldConfig,
    InvalidOrderQuantityError,
    UnsupportedStationError,
)
from breezy.strategy.weather_common.risk import RiskLimits


def test_default_construction_succeeds() -> None:
    config = CurrentRungHoldConfig()
    assert config.stations == ("LAX", "MDW", "MIA", "SFO")
    assert config.stale_observation_hours == 0.75
    assert config.required_fee_coefficient == Decimal("0.06")
    assert config.executable_ask_lower == Decimal("0.05")
    assert config.executable_ask_upper == Decimal("0.95")
    assert config.minimum_displayed_size == 1
    assert config.order_quantity == 1
    assert config.allow_short is False
    assert config.entry_only_halt is True


def test_archive_table_pin_defaults_to_the_frozen_corpus_sha() -> None:
    config = CurrentRungHoldConfig()
    assert config.archive_table_pin == CORPUS_SHA256


def test_nyc_station_is_refused_at_construction() -> None:
    with pytest.raises(UnsupportedStationError):
        CurrentRungHoldConfig(stations=("LAX", "NYC"))


def test_knyc_station_is_refused_at_construction() -> None:
    with pytest.raises(UnsupportedStationError):
        CurrentRungHoldConfig(stations=("KNYC",))


def test_order_quantity_other_than_one_is_refused() -> None:
    with pytest.raises(InvalidOrderQuantityError):
        CurrentRungHoldConfig(order_quantity=2)


def test_order_quantity_zero_is_refused() -> None:
    with pytest.raises(InvalidOrderQuantityError):
        CurrentRungHoldConfig(order_quantity=0)


def test_allow_short_true_is_refused() -> None:
    with pytest.raises(AllowShortNotPermittedError):
        CurrentRungHoldConfig(allow_short=True)


def test_archive_table_pin_mismatch_is_refused() -> None:
    with pytest.raises(ArchiveTablePinMismatchError):
        CurrentRungHoldConfig(archive_table_pin="not-the-real-sha")


def test_config_is_frozen() -> None:
    config = CurrentRungHoldConfig()
    with pytest.raises(AttributeError):
        config.order_quantity = 2  # type: ignore[misc]


def test_config_has_no_operator_reserved_field_name() -> None:
    field_names = frozenset(CurrentRungHoldConfig.__struct_fields__)
    # `RiskLimits` carries several fields (`allow_short`,
    # `stale_observation_hours`, ...) that every sibling weather-strategy
    # config LEGITIMATELY shares by name -- those are not reserved caps.
    # The reserved-CAP-shaped fields are exactly the `max_*` ceilings
    # (`max_position_contracts`, `max_event_notional`,
    # `max_location_notional`, `max_simultaneous_positions`,
    # `max_equity_fraction`): the ones a `budget`/`position_cap` substring
    # scan was trying to approximate. Comparing against these literal names
    # (rather than an ad-hoc substring list) is precise where a substring
    # list is guesswork.
    reserved_cap_field_names = frozenset(
        field.name
        for field in dataclasses.fields(RiskLimits)
        if field.name.startswith("max_")
    )
    collisions = field_names & reserved_cap_field_names
    assert not collisions, (
        f"field(s) {sorted(collisions)!r} literally match a RiskLimits "
        "reserved-cap field name; reserved-cap-shaped fields come from the "
        "operator's own reserved control surface at runtime, never a "
        "config field"
    )
