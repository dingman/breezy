"""Unit tests for strategy-facing weather-bucket facts."""

from __future__ import annotations

import datetime as dt

import pytest

from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
    WEATHER_FACTS_STATUS_UNKNOWN,
    Measure,
    WeatherBucketFacts,
    WeatherFactsUnavailableError,
    is_weather_market,
    read_weather_bucket_facts,
)
from tests.unit.conftest import iter_captured_market_payloads


def known_info(**overrides: object) -> dict[str, object]:
    info: dict[str, object] = {
        WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
        SETTLEMENT_STATION_KEY: "NYC",
        CLIMATE_DAY_KEY: "2026-04-23",
        MEASURE_KEY: "high",
        STRIKE_LOWER_F_KEY: 72,
        STRIKE_UPPER_F_KEY: 73,
    }
    info.update(overrides)
    return info


def test_reader_returns_typed_closed_bucket_facts() -> None:
    facts = read_weather_bucket_facts(known_info())

    assert facts == WeatherBucketFacts(
        settlement_station="NYC",
        climate_day=dt.date(2026, 4, 23),
        measure=Measure.HIGH,
        lower_f=72,
        upper_f=73,
    )
    assert facts.contains(72)
    assert facts.contains(73)
    assert not facts.contains(71)
    assert not facts.contains(74)
    assert facts.distance_f(73) == 0
    assert facts.distance_f(74) == 1
    assert facts.applies_to("NYC", dt.date(2026, 4, 23))
    assert not facts.applies_to("LAX", dt.date(2026, 4, 23))
    assert not facts.applies_to("NYC", dt.date(2026, 4, 24))


@pytest.mark.parametrize(
    ("overrides", "offending_key"),
    [
        ({WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_UNKNOWN}, WEATHER_FACTS_STATUS_KEY),
        ({CLIMATE_DAY_KEY: None}, CLIMATE_DAY_KEY),
        ({CLIMATE_DAY_KEY: "not-a-date"}, CLIMATE_DAY_KEY),
        ({MEASURE_KEY: "median"}, MEASURE_KEY),
        ({STRIKE_LOWER_F_KEY: "72"}, STRIKE_LOWER_F_KEY),
        ({STRIKE_LOWER_F_KEY: 74}, STRIKE_LOWER_F_KEY),
        ({STRIKE_LOWER_F_KEY: None, STRIKE_UPPER_F_KEY: None}, STRIKE_LOWER_F_KEY),
    ],
)
def test_reader_fails_closed_for_unusable_facts(
    overrides: dict[str, object],
    offending_key: str,
) -> None:
    with pytest.raises(WeatherFactsUnavailableError, match=offending_key):
        read_weather_bucket_facts(known_info(**overrides))


@pytest.mark.parametrize(
    ("info", "offending_key"),
    [
        (object(), WEATHER_FACTS_STATUS_KEY),
        ({}, WEATHER_FACTS_STATUS_KEY),
        (
            {
                SETTLEMENT_STATION_KEY: "NYC",
                CLIMATE_DAY_KEY: "2026-04-23",
                MEASURE_KEY: "high",
                STRIKE_LOWER_F_KEY: 72,
                STRIKE_UPPER_F_KEY: 73,
            },
            WEATHER_FACTS_STATUS_KEY,
        ),
    ],
)
def test_reader_refuses_absent_or_non_mapping_status(
    info: object,
    offending_key: str,
) -> None:
    with pytest.raises(WeatherFactsUnavailableError, match=offending_key):
        read_weather_bucket_facts(info)


def test_reader_names_missing_required_key() -> None:
    info = known_info()
    del info[SETTLEMENT_STATION_KEY]

    with pytest.raises(WeatherFactsUnavailableError, match=SETTLEMENT_STATION_KEY):
        read_weather_bucket_facts(info)


def test_explicit_unknown_is_not_weather_but_absent_status_refuses() -> None:
    assert is_weather_market({WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_UNKNOWN}) is False
    assert is_weather_market(known_info()) is True

    with pytest.raises(WeatherFactsUnavailableError, match=WEATHER_FACTS_STATUS_KEY):
        is_weather_market({})


def test_open_sided_distance_is_unsigned_and_zero_on_contained_side() -> None:
    lower_open = read_weather_bucket_facts(known_info(**{STRIKE_LOWER_F_KEY: None}))
    upper_open = read_weather_bucket_facts(known_info(**{STRIKE_UPPER_F_KEY: None}))

    assert lower_open.contains(-10)
    assert lower_open.distance_f(-10) == 0
    assert lower_open.distance_f(74) == 1
    assert upper_open.contains(100)
    assert upper_open.distance_f(100) == 0
    assert upper_open.distance_f(71) == 1


@pytest.mark.parametrize("bad", [True, False, "73", 73.0, None])
def test_interval_methods_reject_bool_and_non_int_readings(bad: object) -> None:
    facts = read_weather_bucket_facts(known_info())

    with pytest.raises(TypeError, match="reading_f"):
        facts.contains(bad)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="reading_f"):
        facts.distance_f(bad)  # type: ignore[arg-type]


def test_real_between_bucket_facts_come_from_parsed_instrument_info() -> None:
    payload = next(
        payload
        for payload in iter_captured_market_payloads()
        if payload["market"]["slug"].endswith("gte72lt73f")
    )

    facts = read_weather_bucket_facts(
        parse_binary_option(payload, venue=POLYMARKET_US_VENUE, ts_init=0).info
    )

    assert facts.lower_f == 72
    assert facts.upper_f == 73
    assert facts.contains(72)
    assert facts.contains(73)
    assert not facts.contains(71)
    assert not facts.contains(74)
    assert facts.distance_f(74) == 1
    assert facts.distance_f(73) == 0
