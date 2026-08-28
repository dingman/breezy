"""Tests for breezy.normalize.units.

Settlement values are published integer degrees Fahrenheit and are NEVER
converted on the settlement path. Conversions exist for enrichment use
only and are structurally distinct (a separate function, never mixed into
the settlement dataclass).
"""

from __future__ import annotations

import pytest

from breezy.normalize.units import TemperatureReadingF, fahrenheit_to_celsius


def test_temperature_reading_with_value_has_none_sentinel() -> None:
    reading = TemperatureReadingF(value_f=79, sentinel="NONE")
    assert reading.value_f == 79
    assert reading.sentinel == "NONE"


@pytest.mark.parametrize("sentinel", ["M", "T", "MS", "MB"])
def test_temperature_reading_with_sentinel_has_no_value(sentinel: str) -> None:
    reading = TemperatureReadingF(value_f=None, sentinel=sentinel)  # type: ignore[arg-type]
    assert reading.value_f is None
    assert reading.sentinel == sentinel


def test_temperature_reading_rejects_value_without_none_sentinel_mismatch() -> None:
    with pytest.raises(ValueError):
        TemperatureReadingF(value_f=None, sentinel="NONE")


def test_temperature_reading_rejects_value_present_with_sentinel_present() -> None:
    with pytest.raises(ValueError):
        TemperatureReadingF(value_f=79, sentinel="M")


def test_fahrenheit_to_celsius_is_enrichment_only_conversion() -> None:
    assert fahrenheit_to_celsius(32) == pytest.approx(0.0)
    assert fahrenheit_to_celsius(212) == pytest.approx(100.0)
    assert fahrenheit_to_celsius(79) == pytest.approx(26.1111, rel=1e-3)
