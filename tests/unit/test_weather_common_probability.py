"""Unit tests for `breezy.strategy.weather_common.probability`.

Focus: the venue-facts routing added by this task
(`WeatherProbabilityEngine.bucket_probability`), and the measure guard. The
underlying Gaussian/Student-t math is the operator's unmodified bundle code
and is exercised indirectly (monotonicity checks) rather than re-derived by
hand here.
"""

from __future__ import annotations

import datetime as dt

import pytest

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.strategy.weather_common.probability import (
    UnsupportedMeasureError,
    WeatherProbabilityEngine,
)

STATION = "NYC"
CLIMATE_DAY = dt.date(2026, 8, 28)


def _facts(
    *, lower_f: int | None, upper_f: int | None, measure: Measure = Measure.HIGH,
) -> WeatherBucketFacts:
    return WeatherBucketFacts(
        settlement_station=STATION,
        climate_day=CLIMATE_DAY,
        measure=measure,
        lower_f=lower_f,
        upper_f=upper_f,
    )


def test_bucket_probability_rises_with_expected_high_for_an_above_bucket() -> None:
    engine = WeatherProbabilityEngine()
    facts = _facts(lower_f=80, upper_f=None)

    cold = engine.bucket_probability(facts, expected_high_f=60.0, horizon_hours=6.0)
    hot = engine.bucket_probability(facts, expected_high_f=100.0, horizon_hours=6.0)

    assert cold < hot
    assert cold == pytest.approx(engine.error_model.p_floor, abs=1e-6)
    assert hot == pytest.approx(1.0 - engine.error_model.p_floor, abs=1e-6)


def test_bucket_probability_falls_with_expected_high_for_a_below_bucket() -> None:
    engine = WeatherProbabilityEngine()
    facts = _facts(lower_f=None, upper_f=70)

    cold = engine.bucket_probability(facts, expected_high_f=50.0, horizon_hours=6.0)
    hot = engine.bucket_probability(facts, expected_high_f=95.0, horizon_hours=6.0)

    assert cold > hot


def test_bucket_probability_peaks_inside_a_closed_range() -> None:
    engine = WeatherProbabilityEngine()
    facts = _facts(lower_f=72, upper_f=73)

    inside = engine.bucket_probability(facts, expected_high_f=72.5, horizon_hours=6.0)
    far_outside = engine.bucket_probability(facts, expected_high_f=40.0, horizon_hours=6.0)

    assert inside > far_outside
    assert inside > 0.2


def test_a_low_measure_bucket_refuses_rather_than_silently_misapplying_the_high_model() -> None:
    engine = WeatherProbabilityEngine()
    facts = _facts(lower_f=30, upper_f=None, measure=Measure.LOW)

    with pytest.raises(UnsupportedMeasureError):
        engine.bucket_probability(facts, expected_high_f=95.0, horizon_hours=6.0)


def test_wider_horizon_widens_sigma_and_therefore_pulls_probability_toward_uncertainty() -> None:
    engine = WeatherProbabilityEngine()
    facts = _facts(lower_f=80, upper_f=None)

    # Just above threshold: a wider horizon (bigger sigma) should pull the
    # probability of clearing the bar DOWN from near-certainty, since more
    # uncertainty means less confidence in a narrow margin.
    near_term = engine.bucket_probability(facts, expected_high_f=82.0, horizon_hours=3.0)
    far_term = engine.bucket_probability(facts, expected_high_f=82.0, horizon_hours=200.0)

    assert far_term < near_term
