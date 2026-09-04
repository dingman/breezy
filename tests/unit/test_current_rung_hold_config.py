"""Tests for ``CurrentRungHoldConfig``
(src/breezy/strategy/current_rung_hold/config.py).

Covers the construction-time validations the blueprint's build order step 4
requires: NYC (hourly-only, A14) is refused, ``order_quantity`` must be
exactly 1, ``allow_short`` must stay False, and ``archive_table_pin`` must
match the frozen corpus sha the module actually ships
(``archive_table.CORPUS_SHA256``) -- never a second hard-coded copy of it.

Operator-reserved caps (maximum daily trading budget; maximum notional per
position) are NOT fields on this config -- they come from ``operator_controls``
at runtime (see ``docs/plans/CURRENT_RUNG_HOLD_BLUEPRINT_2026-09-04.md`` §2).
A test below asserts no field name on this config even mentions budget,
daily, or a position cap.
"""

from __future__ import annotations

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

#: Substrings that would identify an operator-reserved control if they
#: appeared in a field name on this config. Case-insensitive.
_FORBIDDEN_FIELD_SUBSTRINGS: tuple[str, ...] = ("budget", "daily", "position_cap", "poscap")


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
    field_names = CurrentRungHoldConfig.__struct_fields__
    for name in field_names:
        lowered = name.lower()
        for forbidden in _FORBIDDEN_FIELD_SUBSTRINGS:
            assert forbidden not in lowered, (
                f"field {name!r} looks like an operator-reserved control; "
                "those come from operator_controls at runtime, never a "
                "config field"
            )
