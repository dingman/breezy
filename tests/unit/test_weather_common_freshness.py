"""Unit tests for `breezy.strategy.weather_common.freshness`.

`SignalFreshness` is the tagged age value `RiskManager.evaluate_order` takes
in place of the old bare `forecast_age_hours: float` -- see the module
docstring for why forecast and observation share ONE screening step (a
`SignalKind` tag on one scalar) rather than a second bare parameter.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from breezy.strategy.weather_common.freshness import SignalFreshness, SignalKind


def test_forecast_constructor_tags_the_forecast_kind() -> None:
    freshness = SignalFreshness.forecast(3.5)

    assert freshness.kind is SignalKind.FORECAST
    assert freshness.age_hours == 3.5


def test_observation_constructor_tags_the_observation_kind() -> None:
    freshness = SignalFreshness.observation(1.25)

    assert freshness.kind is SignalKind.OBSERVATION
    assert freshness.age_hours == 1.25


def test_signal_freshness_is_frozen() -> None:
    freshness = SignalFreshness.forecast(0.0)

    with pytest.raises(FrozenInstanceError):
        freshness.age_hours = 1.0  # type: ignore[misc]


def test_signal_kind_has_exactly_forecast_and_observation() -> None:
    """Closed set -- a third kind is a deliberate, reviewed addition, not a typo."""
    assert {member.value for member in SignalKind} == {"forecast", "observation"}
