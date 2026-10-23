"""ARM C2: the live NBP feed (``ForecastPoint`` -> pinned ``PNoStore`` rows) and its skew guard."""

from __future__ import annotations

import datetime as dt
import logging

import pytest

from breezy.domain.forecast_point import MINIMUM_PUBLICATION_LAG_NS, ForecastPoint
from breezy.strategy.ladder_ev.forecast_state import NBP_QUANTILE_VARIABLES
from breezy.strategy.ladder_ev.quantile_density import Rung
from breezy.strategy.no_ladder_maker.live_feed import LATE_ARRIVAL_EVENT, LiveNbpFeed
from tests.strategy.no_ladder_maker.maker_strategy_support import (
    DAY,
    HOUR_NS,
    NS,
    Harness,
    identity_calibration,
    want,
)

LAG = MINIMUM_PUBLICATION_LAG_NS["NBM_NBP"]
#: 13Z of D-1 (a pinned cycle for D)
CYCLE_NS = int(dt.datetime(2026, 9, 17, 13, 0, tzinfo=dt.UTC).timestamp()) * NS
VALID_START = int(dt.datetime(2026, 9, 18, 7, 0, tzinfo=dt.UTC).timestamp()) * NS
VALID_END = VALID_START + 12 * HOUR_NS


def point(
    variable: str = "TXN_Q50",
    *,
    cycle_ns: int = CYCLE_NS,
    lag_ns: int = LAG,
    station: str = "KSFO",
    model: str = "NBM_NBP",
    version: str = "4.2",
    value: float | None = 70.0,
    valid_start: int = VALID_START,
) -> ForecastPoint:
    return ForecastPoint(
        station=station,
        model=model,
        model_version=version,
        variable=variable,
        cycle_runtime_ns=cycle_ns,
        valid_start_ns=valid_start,
        valid_end_ns=valid_start + 12 * HOUR_NS,
        value_f=value,
        issuance_seq=0,
        measured_publication_lag_ns=lag_ns,
        available_at_ns=cycle_ns + lag_ns,
        ingested_at_ns=cycle_ns + lag_ns,
        absence_reason=None if value is not None else "not_published",
    )


def feed(late: list[tuple[str, int, int]] | None = None) -> LiveNbpFeed:
    return LiveNbpFeed(
        calibration=identity_calibration(),
        icao_by_station={"SFO": "KSFO", "LAX": "KLAX"},
        on_late_arrival=(lambda s, c, n: late.append((s, c, n))) if late is not None else None,
    )


def test_a_record_for_another_model_variable_or_station_is_counted_and_dropped() -> None:
    f = feed()
    assert f.push(point(model="NBM_NBS"), arrival_ns=CYCLE_NS + LAG).reason == "foreign_model"
    assert f.push(point("TXN"), arrival_ns=CYCLE_NS + LAG).reason == "foreign_variable"
    assert f.push(point(station="KJFK"), arrival_ns=CYCLE_NS + LAG).reason == "unknown_station"
    assert f.push(point(value=None), arrival_ns=CYCLE_NS + LAG).reason == "absent"
    assert f.pinned_rows("SFO", DAY) == []


def test_an_on_time_row_keeps_its_publication_instant_and_the_v_prefixed_era() -> None:
    late: list[tuple[str, int, int]] = []
    f = feed(late)
    outcome = f.push(point(), arrival_ns=CYCLE_NS + LAG)  # arrival == publication
    assert outcome.accepted and outcome.late_ns == 0 and late == []
    (row,) = f.pinned_rows("SFO", DAY)
    assert row.available_at_ns == CYCLE_NS + LAG
    assert row.nbm_version_era == "v4.2"


def test_a_late_arrival_keeps_its_publication_age_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    late: list[tuple[str, int, int]] = []
    f = feed(late)
    arrival = CYCLE_NS + LAG + 90 * NS
    with caplog.at_level(logging.WARNING):
        outcome = f.push(point(), arrival_ns=arrival)
    assert outcome.late_ns == 90 * NS
    (row,) = f.pinned_rows("SFO", DAY)
    assert row.available_at_ns == CYCLE_NS + LAG, "the staleness gate must see the true age"
    assert late == [("SFO", CYCLE_NS, 90 * NS)]
    assert f.counters[LATE_ARRIVAL_EVENT] == 1
    assert LATE_ARRIVAL_EVENT in caplog.text and "station=SFO" in caplog.text


def test_a_vector_is_invisible_until_it_arrives_whatever_its_publication_time() -> None:
    """Visibility is arrival-bound by construction: no push, no row in any store."""
    f = feed()
    f.set_ladder("SFO", DAY, [Rung("a", None, 65), Rung("b", 66, None)])
    before = f.store("SFO", DAY)
    assert before is not None and f.pinned_rows("SFO", DAY) == []
    f.push(point(), arrival_ns=CYCLE_NS + LAG + 3_600 * NS)  # published an hour before it arrived
    assert len(f.pinned_rows("SFO", DAY)) == 1
    assert f.store("SFO", DAY) is not before


def test_only_the_three_pinned_cycles_feed_a_climate_day() -> None:
    f = feed()
    other = int(dt.datetime(2026, 9, 17, 7, 0, tzinfo=dt.UTC).timestamp()) * NS  # 07Z: not pinned
    f.push(point(cycle_ns=other), arrival_ns=other + LAG)
    f.push(point(), arrival_ns=CYCLE_NS + LAG)
    assert {r.cycle_runtime_ns for r in f.pinned_rows("SFO", DAY)} == {CYCLE_NS}


def test_the_first_max_column_wins_and_a_later_window_never_displaces_it() -> None:
    f = feed()
    f.push(point(value=70.0, valid_start=VALID_START), arrival_ns=CYCLE_NS + LAG)
    dup = f.push(
        point(value=99.0, valid_start=VALID_START + 24 * HOUR_NS), arrival_ns=CYCLE_NS + LAG
    )
    assert dup.accepted is False and dup.reason == "duplicate"
    f.push(point(value=65.0, valid_start=VALID_START - 24 * HOUR_NS), arrival_ns=CYCLE_NS + LAG)
    (row,) = f.pinned_rows("SFO", DAY)
    assert row.value_f == 65.0 and row.valid_start_ns == VALID_START - 24 * HOUR_NS


def test_a_store_needs_a_ladder_and_is_rebuilt_when_a_row_or_the_ladder_changes() -> None:
    f = feed()
    assert f.store("SFO", DAY) is None
    f.set_ladder("SFO", DAY, [Rung("a", None, 65), Rung("b", 66, None)])
    first = f.store("SFO", DAY)
    assert first is not None and f.store("SFO", DAY) is first
    f.push(point(), arrival_ns=CYCLE_NS + LAG)
    rebuilt = f.store("SFO", DAY)
    assert rebuilt is not first
    f.set_ladder("SFO", DAY, [Rung("a", None, 65), Rung("b", 66, None)])  # unchanged
    assert f.store("SFO", DAY) is rebuilt
    f.set_ladder("SFO", DAY, [Rung("a", None, 65), Rung("b", 66, 70), Rung("c", 71, None)])
    assert f.store("SFO", DAY) is not rebuilt


def test_nbp_rows_survive_a_ladder_change_and_feed_the_rebuilt_store() -> None:
    """V6: a new rung (a ladder change) drops the cached store, never the received rows."""
    f = feed()
    for variable in NBP_QUANTILE_VARIABLES:
        f.push(point(variable), arrival_ns=CYCLE_NS + LAG)
    f.set_ladder("SFO", DAY, [Rung("a", None, 65), Rung("b", 66, None)])
    before = f.store("SFO", DAY)
    rows_before = f.pinned_rows("SFO", DAY)
    assert before is not None and len(rows_before) == len(NBP_QUANTILE_VARIABLES)
    f.set_ladder("SFO", DAY, [Rung("a", None, 65), Rung("b", 66, 70), Rung("c", 71, None)])
    after = f.store("SFO", DAY)
    assert after is not None and after is not before, "the store is rebuilt for the new ladder"
    assert f.pinned_rows("SFO", DAY) == rows_before, "no received vector was lost"
    assert f.complete_cycle_count("SFO", DAY) == 1


def test_a_complete_vector_needs_all_seven_variables() -> None:
    f = feed()
    for variable in NBP_QUANTILE_VARIABLES[:-1]:
        f.push(point(variable), arrival_ns=CYCLE_NS + LAG)
    assert f.complete_cycle_count("SFO", DAY) == 0
    f.push(point(NBP_QUANTILE_VARIABLES[-1]), arrival_ns=CYCLE_NS + LAG)
    assert f.complete_cycle_count("SFO", DAY) == 1


# --- the strategy side: the NBP release alert -----------------------------------------------------


def test_an_accepted_forecast_point_redecides_one_ns_later_not_at_the_arrival_instant() -> None:
    h = Harness()
    calls = h.install(lambda ctx: want())
    h.drain()
    now = h.clock.timestamp_ns()
    h.strategy.on_data(point(cycle_ns=now - LAG - NS, lag_ns=LAG))
    assert calls == [], (
        "the decision waits for the 1 ns alert: classify_p_no needs it STRICTLY after"
    )
    h.advance_to(now + 1)
    assert [c.now_ns for c in calls] == [now + 1]


def test_arrivals_of_one_station_coalesce_into_one_pending_alert() -> None:
    h = Harness()
    calls = h.install(lambda ctx: want())
    now = h.clock.timestamp_ns()
    for variable in NBP_QUANTILE_VARIABLES:
        h.strategy.on_data(point(variable, cycle_ns=now - LAG - NS))
    h.advance_to(now + 1)
    assert len(calls) == 1


def test_a_foreign_record_schedules_nothing() -> None:
    h = Harness()
    calls = h.install(lambda ctx: want())
    now = h.clock.timestamp_ns()
    h.strategy.on_data(point(model="NBM_NBS", cycle_ns=now - LAG - NS))
    h.advance_to(now + 1)
    assert calls == []
