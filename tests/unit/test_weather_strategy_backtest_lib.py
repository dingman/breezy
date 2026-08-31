"""Unit tests for the pure helper logic in
``scripts/analysis/weather_strategy_backtest_lib.py``.

Covers exactly the three pure-logic areas the runner depends on:
instrument selection (which tape instruments actually carry book+quote
data), settlement-price mapping (bucket containment -> 0.0/1.0), and
scenario construction (the REAL-vs-ASSUMED settlement sweep). Also covers
the ``hours_until`` helper the synthetic forecast source uses to compute a
LIVE horizon.

Loaded via ``importlib`` from its file path, matching the existing pattern in
``tests/unit/test_price_conditional_settlement_analysis.py``: ``scripts/``
carries no package ``__init__.py``.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts


def _load_lib_module() -> ModuleType:
    path = Path("scripts/analysis/weather_strategy_backtest_lib.py")
    sys.path.insert(0, path.parent.as_posix())
    spec = importlib.util.spec_from_file_location("weather_strategy_backtest_lib", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


lib = _load_lib_module()


def _facts(station: str, lower_f: int | None, upper_f: int | None) -> WeatherBucketFacts:
    return WeatherBucketFacts(
        settlement_station=station,
        climate_day=dt.date(2026, 8, 30),
        measure=Measure.HIGH,
        lower_f=lower_f,
        upper_f=upper_f,
    )


# ---------------------------------------------------------------------------
# select_tradable_instrument_ids
# ---------------------------------------------------------------------------


def test_select_tradable_instrument_ids_requires_both_depth_and_quotes() -> None:
    depth_counts = {"has-both": 10, "depth-only": 5, "zero-depth": 0}
    quote_counts = {"has-both": 8, "quote-only": 4, "zero-depth": 3}

    result = lib.select_tradable_instrument_ids(depth_counts, quote_counts)

    assert result == ["has-both"]


def test_select_tradable_instrument_ids_returns_sorted_list() -> None:
    depth_counts = {"zzz": 1, "aaa": 1, "mmm": 1}
    quote_counts = {"zzz": 1, "aaa": 1, "mmm": 1}

    result = lib.select_tradable_instrument_ids(depth_counts, quote_counts)

    assert result == ["aaa", "mmm", "zzz"]


def test_select_tradable_instrument_ids_empty_inputs_returns_empty() -> None:
    assert lib.select_tradable_instrument_ids({}, {}) == []


def test_select_tradable_instrument_ids_excludes_instrument_missing_from_quotes() -> None:
    depth_counts = {"only-in-depth": 3}
    quote_counts: dict[str, int] = {}

    assert lib.select_tradable_instrument_ids(depth_counts, quote_counts) == []


# ---------------------------------------------------------------------------
# settlement_prices_for_scenario
# ---------------------------------------------------------------------------


def test_settlement_prices_for_scenario_maps_containing_bucket_to_one() -> None:
    facts_by_id = {
        "nyc-lt82f": _facts("NYC", None, 81),
        "nyc-82-83": _facts("NYC", 82, 83),
        "nyc-84-85": _facts("NYC", 84, 85),
    }

    prices = lib.settlement_prices_for_scenario(facts_by_id, {"NYC": 78})

    assert prices == {"nyc-lt82f": 1.0, "nyc-82-83": 0.0, "nyc-84-85": 0.0}


def test_settlement_prices_for_scenario_handles_multiple_stations_independently() -> None:
    facts_by_id = {
        "nyc-lt82f": _facts("NYC", None, 81),
        "mia-91-92": _facts("MIA", 91, 92),
    }

    prices = lib.settlement_prices_for_scenario(facts_by_id, {"NYC": 78, "MIA": 91})

    assert prices == {"nyc-lt82f": 1.0, "mia-91-92": 1.0}


def test_settlement_prices_for_scenario_endpoint_inclusive_upper_bound() -> None:
    facts_by_id = {"mia-91-92": _facts("MIA", 91, 92)}

    prices = lib.settlement_prices_for_scenario(facts_by_id, {"MIA": 92})

    assert prices == {"mia-91-92": 1.0}


def test_settlement_prices_for_scenario_no_bucket_wins_settles_all_zero() -> None:
    facts_by_id = {
        "nyc-lt82f": _facts("NYC", None, 81),
        "nyc-82-83": _facts("NYC", 82, 83),
    }

    prices = lib.settlement_prices_for_scenario(facts_by_id, {"NYC": 90})

    assert prices == {"nyc-lt82f": 0.0, "nyc-82-83": 0.0}


def test_settlement_prices_for_scenario_raises_on_missing_station_reading() -> None:
    facts_by_id = {"nyc-lt82f": _facts("NYC", None, 81)}

    with pytest.raises(KeyError):
        lib.settlement_prices_for_scenario(facts_by_id, {"MIA": 91})


def test_settlement_prices_for_scenario_empty_mapping_returns_empty() -> None:
    assert lib.settlement_prices_for_scenario({}, {"NYC": 78}) == {}


# ---------------------------------------------------------------------------
# build_settlement_scenarios
# ---------------------------------------------------------------------------


def test_build_settlement_scenarios_first_entry_is_primary_real() -> None:
    scenarios = lib.build_settlement_scenarios(
        real_observed_by_station={"NYC": 78, "MIA": 91},
        sweep_by_station={},
    )

    assert len(scenarios) == 1
    primary = scenarios[0]
    assert primary.name == "primary_real_preliminary"
    assert primary.observed_by_station == {"NYC": 78, "MIA": 91}
    assert primary.provenance_by_station == {"NYC": "REAL", "MIA": "REAL"}


def test_build_settlement_scenarios_sweep_varies_one_station_holds_rest_real() -> None:
    scenarios = lib.build_settlement_scenarios(
        real_observed_by_station={"NYC": 78, "MIA": 91},
        sweep_by_station={"NYC": [82, 84]},
    )

    assert len(scenarios) == 3  # primary + 2 NYC sweep candidates
    sweep_82 = next(s for s in scenarios if s.observed_by_station["NYC"] == 82)
    assert sweep_82.observed_by_station == {"NYC": 82, "MIA": 91}
    assert sweep_82.provenance_by_station == {"NYC": "ASSUMED", "MIA": "REAL"}

    sweep_84 = next(s for s in scenarios if s.observed_by_station["NYC"] == 84)
    assert sweep_84.observed_by_station == {"NYC": 84, "MIA": 91}
    assert sweep_84.provenance_by_station == {"NYC": "ASSUMED", "MIA": "REAL"}


def test_build_settlement_scenarios_multiple_stations_swept_independently() -> None:
    scenarios = lib.build_settlement_scenarios(
        real_observed_by_station={"NYC": 78, "MIA": 91},
        sweep_by_station={"NYC": [82], "MIA": [89]},
    )

    names = {s.name for s in scenarios}
    assert names == {"primary_real_preliminary", "sweep_nyc_82f", "sweep_mia_89f"}

    mia_sweep = next(s for s in scenarios if s.name == "sweep_mia_89f")
    assert mia_sweep.observed_by_station == {"NYC": 78, "MIA": 89}
    assert mia_sweep.provenance_by_station == {"NYC": "REAL", "MIA": "ASSUMED"}


def test_build_settlement_scenarios_rejects_sweep_station_with_no_real_reading() -> None:
    with pytest.raises(ValueError, match="ORD"):
        lib.build_settlement_scenarios(
            real_observed_by_station={"NYC": 78},
            sweep_by_station={"ORD": [70]},
        )


def test_build_settlement_scenarios_no_sweep_candidates_for_station_adds_nothing() -> None:
    scenarios = lib.build_settlement_scenarios(
        real_observed_by_station={"NYC": 78},
        sweep_by_station={"NYC": []},
    )

    assert len(scenarios) == 1
    assert scenarios[0].name == "primary_real_preliminary"


# ---------------------------------------------------------------------------
# hours_until
# ---------------------------------------------------------------------------


def test_hours_until_positive_when_deadline_is_in_the_future() -> None:
    now = dt.datetime(2026, 8, 30, 16, 5, tzinfo=dt.UTC)
    deadline = dt.datetime(2026, 8, 31, 5, 0, tzinfo=dt.UTC)

    result = lib.hours_until(now, deadline)

    assert result == pytest.approx(12 + 55 / 60)


def test_hours_until_zero_when_now_equals_deadline() -> None:
    moment = dt.datetime(2026, 8, 30, 16, 5, tzinfo=dt.UTC)

    assert lib.hours_until(moment, moment) == 0.0


def test_hours_until_negative_when_now_is_past_the_deadline() -> None:
    now = dt.datetime(2026, 8, 31, 6, 0, tzinfo=dt.UTC)
    deadline = dt.datetime(2026, 8, 31, 5, 0, tzinfo=dt.UTC)

    result = lib.hours_until(now, deadline)

    assert result == pytest.approx(-1.0)


def test_hours_until_rejects_naive_now() -> None:
    now = dt.datetime(2026, 8, 30, 16, 5)  # noqa: DTZ001 - deliberately naive
    deadline = dt.datetime(2026, 8, 31, 5, 0, tzinfo=dt.UTC)

    with pytest.raises(ValueError, match="timezone-aware"):
        lib.hours_until(now, deadline)


def test_hours_until_rejects_naive_deadline() -> None:
    now = dt.datetime(2026, 8, 30, 16, 5, tzinfo=dt.UTC)
    deadline = dt.datetime(2026, 8, 31, 5, 0)  # noqa: DTZ001 - deliberately naive

    with pytest.raises(ValueError, match="timezone-aware"):
        lib.hours_until(now, deadline)


# ---------------------------------------------------------------------------
# latest_publication_at_or_before
# ---------------------------------------------------------------------------


def test_latest_publication_at_or_before_returns_none_for_empty_sequence() -> None:
    now = dt.datetime(2026, 8, 30, 16, 5, tzinfo=dt.UTC)

    assert lib.latest_publication_at_or_before([], now) is None


def test_latest_publication_at_or_before_returns_none_when_now_precedes_every_publication() -> None:
    now = dt.datetime(2026, 8, 30, 10, 0, tzinfo=dt.UTC)
    publications = [(dt.datetime(2026, 8, 30, 16, 5, tzinfo=dt.UTC), 83.0)]

    assert lib.latest_publication_at_or_before(publications, now) is None


def test_latest_publication_at_or_before_returns_exact_match() -> None:
    published_at = dt.datetime(2026, 8, 30, 16, 5, tzinfo=dt.UTC)
    publications = [(published_at, 83.0)]

    result = lib.latest_publication_at_or_before(publications, published_at)

    assert result == (published_at, 83.0)


def test_latest_publication_at_or_before_returns_the_latest_not_exceeding_now() -> None:
    pub0 = (dt.datetime(2026, 8, 30, 10, 0, tzinfo=dt.UTC), 80.0)
    pub1 = (dt.datetime(2026, 8, 30, 16, 6, tzinfo=dt.UTC), 83.0)
    pub2 = (dt.datetime(2026, 8, 30, 16, 8, tzinfo=dt.UTC), 86.0)
    now = dt.datetime(2026, 8, 30, 16, 7, tzinfo=dt.UTC)  # between pub1 and pub2

    result = lib.latest_publication_at_or_before([pub0, pub1, pub2], now)

    assert result == pub1


def test_latest_publication_at_or_before_returns_the_last_once_now_passes_all_of_them() -> None:
    pub0 = (dt.datetime(2026, 8, 30, 10, 0, tzinfo=dt.UTC), 80.0)
    pub1 = (dt.datetime(2026, 8, 30, 16, 6, tzinfo=dt.UTC), 83.0)
    now = dt.datetime(2026, 8, 30, 18, 0, tzinfo=dt.UTC)

    result = lib.latest_publication_at_or_before([pub0, pub1], now)

    assert result == pub1


def test_latest_publication_at_or_before_is_order_independent_in_the_input_sequence() -> None:
    pub0 = (dt.datetime(2026, 8, 30, 10, 0, tzinfo=dt.UTC), 80.0)
    pub1 = (dt.datetime(2026, 8, 30, 16, 6, tzinfo=dt.UTC), 83.0)
    now = dt.datetime(2026, 8, 30, 18, 0, tzinfo=dt.UTC)

    # Deliberately out of chronological order.
    result = lib.latest_publication_at_or_before([pub1, pub0], now)

    assert result == pub1


# ---------------------------------------------------------------------------
# derive_completion_status
# ---------------------------------------------------------------------------


def test_derive_completion_status_no_orders_no_refusals_is_completed() -> None:
    # An efficient market: the strategy saw no opportunity, not a gag.
    status = lib.derive_completion_status(orders_submitted=0, refusal_counts={})

    assert status == lib.STATUS_COMPLETED


def test_derive_completion_status_orders_submitted_is_completed_even_with_refusals() -> None:
    # Some signals traded, some were refused -- not the ENTIRE signal set.
    status = lib.derive_completion_status(
        orders_submitted=3, refusal_counts={"shorts_disabled": 2},
    )

    assert status == lib.STATUS_COMPLETED


def test_derive_completion_status_zero_orders_with_refusals_is_completed_all_refused() -> None:
    # Zero orders AND a nonzero refusal count: the whole signal set was gagged,
    # not merely a strategy that found no edge.
    status = lib.derive_completion_status(
        orders_submitted=0, refusal_counts={"shorts_disabled": 12},
    )

    assert status == lib.STATUS_COMPLETED_ALL_REFUSED


def test_derive_completion_status_sums_multiple_refusal_reasons() -> None:
    status = lib.derive_completion_status(
        orders_submitted=0,
        refusal_counts={"shorts_disabled": 5, "some_other_reason": 1},
    )

    assert status == lib.STATUS_COMPLETED_ALL_REFUSED


def test_derive_completion_status_zero_orders_and_all_zero_refusal_values_is_completed() -> None:
    # A reason key present with count 0 is not evidence of a refusal.
    status = lib.derive_completion_status(
        orders_submitted=0, refusal_counts={"shorts_disabled": 0},
    )

    assert status == lib.STATUS_COMPLETED
