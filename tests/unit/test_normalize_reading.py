"""Tests for breezy.normalize.reading.

ClimateDayReading is a plain frozen dataclass -- not a NautilusTrader
type. source_grade is set only via the from_nws(...) classmethod, but
this is visibility for review, not an unforgeable settlement token: the
class remains directly constructible.
"""

from __future__ import annotations

import dataclasses
from datetime import date
from typing import TypedDict

import pytest

from breezy.normalize.reading import ClimateDayReading
from breezy.normalize.units import TemperatureReadingF


class _ReadingKwargs(TypedDict):
    station: str
    climate_day: date
    tmax: TemperatureReadingF
    tmin: TemperatureReadingF
    tavg: TemperatureReadingF
    is_final: bool
    has_correction_evidence: bool


def _reading_kwargs() -> _ReadingKwargs:
    return {
        "station": "NYC",
        "climate_day": date(2026, 8, 21),
        "tmax": TemperatureReadingF(value_f=79, sentinel="NONE"),
        "tmin": TemperatureReadingF(value_f=63, sentinel="NONE"),
        "tavg": TemperatureReadingF(value_f=71, sentinel="NONE"),
        "is_final": True,
        "has_correction_evidence": False,
    }


def test_from_nws_sets_source_grade_settlement() -> None:
    reading = ClimateDayReading.from_nws(**_reading_kwargs())
    assert reading.source_grade == "SETTLEMENT"
    assert reading.station == "NYC"
    assert reading.climate_day == date(2026, 8, 21)
    assert reading.is_final is True
    assert reading.has_correction_evidence is False


def test_reading_is_a_plain_frozen_dataclass_not_nautilus_type() -> None:
    reading = ClimateDayReading.from_nws(**_reading_kwargs())
    assert dataclasses.is_dataclass(reading)
    with pytest.raises(dataclasses.FrozenInstanceError):
        reading.station = "SFO"  # type: ignore[misc]

    # No Nautilus Data/Actor/Clock coupling anywhere in the module (the
    # docstring may legitimately mention "nautilus_trader" in prose, so
    # check for an actual import statement, not a bare substring).
    import breezy.normalize.reading as reading_module

    source = reading_module.__file__
    assert source is not None
    with open(source) as handle:
        text = handle.read()
    assert "import nautilus_trader" not in text
    assert "from nautilus_trader" not in text


def test_reading_directly_constructible_without_from_nws() -> None:
    """Honest per its own docstring: source_grade is visibility, not an
    unforgeable token. Direct construction with any source_grade remains
    possible -- this test pins that documented limitation rather than
    hiding it.
    """
    reading = ClimateDayReading(
        source_grade="SETTLEMENT",
        **_reading_kwargs(),
    )
    assert reading.source_grade == "SETTLEMENT"


def test_preliminary_reading_carries_is_final_false() -> None:
    kwargs = _reading_kwargs()
    kwargs["is_final"] = False
    reading = ClimateDayReading.from_nws(**kwargs)
    assert reading.is_final is False
