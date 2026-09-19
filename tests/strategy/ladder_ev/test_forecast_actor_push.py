"""WP-12 Seam D (R1-11): the decider sees forecasts by ACTOR PUSH, never a catalog read.

``ForecastState`` is fed from the message bus by
:class:`breezy.strategy.ladder_ev.forecast_subscriber.ForecastStateActor`,
which subscribes to the ONE shared ``DataType``
(``nbm_forecast_data_type.nbm_forecast_point_data_type``) and pushes each
``ForecastPoint`` into the per-station in-memory store. Three properties are
load-bearing and each is asserted here:

* a publication reaches ``ForecastState.value_at``;
* with the producing actor ABSENT the state says ``forecast_unavailable`` --
  loudly, by name -- and no take is permitted. Never a silent zero, never a
  carried-over value;
* a stale forecast is DISTINGUISHABLE from a fresh one.

The bus is the real ``MessageBus``; nothing is monkeypatched.
"""

from __future__ import annotations

import datetime as dt

import pytest
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.domain.forecast_point import MINIMUM_PUBLICATION_LAG_NS, ForecastPoint
from breezy.ingest.nbm_forecast_data_type import nbm_forecast_point_data_type
from breezy.strategy.ladder_ev.forecast_state import (
    FORECAST_OK,
    FORECAST_STALE,
    FORECAST_UNAVAILABLE,
    ForecastState,
    forecast_take_permitted,
)
from breezy.strategy.ladder_ev.forecast_subscriber import ForecastStateActor

NS = 1_000_000_000
LAG_NS = MINIMUM_PUBLICATION_LAG_NS["NBM_NBS"] + 600 * NS
CYCLE_NS = int(dt.datetime(2026, 9, 19, 12, tzinfo=dt.UTC).timestamp()) * NS
AVAILABLE_NS = CYCLE_NS + LAG_NS
NOW_NS = AVAILABLE_NS + 60 * NS
MAX_STALENESS_NS = 6 * 3600 * NS


def make_point(
    *,
    station: str = "KMIA",
    value_f: float | None = 84.0,
    absence_reason: str | None = None,
    cycle_runtime_ns: int = CYCLE_NS,
    variable: str = "TXN",
) -> ForecastPoint:
    return ForecastPoint(
        station=station,
        model="NBM_NBS",
        model_version="5.0",
        variable=variable,
        cycle_runtime_ns=cycle_runtime_ns,
        valid_start_ns=cycle_runtime_ns + 12 * 3600 * NS,
        valid_end_ns=cycle_runtime_ns + 12 * 3600 * NS,
        value_f=value_f,
        issuance_seq=0,
        measured_publication_lag_ns=LAG_NS,
        available_at_ns=cycle_runtime_ns + LAG_NS,
        ingested_at_ns=cycle_runtime_ns + LAG_NS,
        absence_reason=absence_reason,
    )


class Publisher(Actor):  # type: ignore[misc]
    """Stands in for the ingest Actor: publishes through the NATIVE `publish_data`.

    Using the real publication path rather than a hand-built topic string is
    the whole point -- a topic the producer does not actually use would make
    this suite pass while production delivered nothing (the metadata-ordering
    hazard barrier W1 exists for).
    """

    def publish(self, point: ForecastPoint) -> None:
        self.publish_data(nbm_forecast_point_data_type(), point)


def build(*, stations: tuple[str, ...] = ("KMIA",)) -> tuple[ForecastStateActor, Publisher]:
    clock = TestClock()
    clock.set_time(NOW_NS)
    subscriber = ForecastStateActor(stations=stations)
    publisher = Publisher()
    msgbus = TestComponentStubs.msgbus()
    for actor in (subscriber, publisher):
        actor.register_base(
            portfolio=TestComponentStubs.portfolio(),
            msgbus=msgbus,
            cache=TestComponentStubs.cache(),
            clock=clock,
        )
        actor.start()
    return subscriber, publisher


def publish(publisher: Publisher, point: ForecastPoint) -> None:
    publisher.publish(point)


# ---------------------------------------------------------------------------
# (a) a publication reaches ForecastState.value_at
# ---------------------------------------------------------------------------


def test_publishing_a_forecast_point_updates_the_state() -> None:
    actor, publisher = build()

    publish(publisher, make_point())

    snapshot = actor.state_for("KMIA").value_at(NOW_NS)
    assert snapshot is not None
    assert snapshot.value_f == 84.0
    assert snapshot.available_at_ns == AVAILABLE_NS


def test_a_point_is_invisible_before_its_own_vintage() -> None:
    actor, publisher = build()

    publish(publisher, make_point())

    assert actor.state_for("KMIA").value_at(AVAILABLE_NS - 1) is None


def test_a_later_cycle_supersedes_an_earlier_one() -> None:
    actor, publisher = build()

    publish(publisher, make_point(value_f=84.0))
    publish(publisher, make_point(value_f=79.0, cycle_runtime_ns=CYCLE_NS + 6 * 3600 * NS))

    later_now = CYCLE_NS + 6 * 3600 * NS + LAG_NS + NS
    snapshot = actor.state_for("KMIA").value_at(later_now)
    assert snapshot is not None
    assert snapshot.value_f == 79.0


def test_a_station_the_actor_does_not_serve_is_counted_not_stored() -> None:
    actor, publisher = build(stations=("KMIA",))

    publish(publisher, make_point(station="KSFO"))

    assert actor.counters["unknown_station"] == 1


def test_an_absence_is_counted_by_its_reason_and_never_stored_as_a_value() -> None:
    actor, publisher = build()

    publish(publisher, make_point(value_f=None, absence_reason="not_published"))

    assert actor.state_for("KMIA").value_at(NOW_NS) is None
    assert actor.counters["absent_not_published"] == 1


def test_a_foreign_variable_is_ignored() -> None:
    actor, publisher = build()

    publish(publisher, make_point(variable="TMP"))

    assert actor.state_for("KMIA").value_at(NOW_NS) is None


# ---------------------------------------------------------------------------
# (b) with the actor absent: forecast_unavailable, loud, and no take
# ---------------------------------------------------------------------------


def test_with_no_actor_the_state_reports_forecast_unavailable_and_permits_no_take() -> None:
    state = ForecastState()

    visibility = state.visibility_at(NOW_NS, max_staleness_ns=MAX_STALENESS_NS)

    assert visibility.snapshot is None
    assert visibility.reason == FORECAST_UNAVAILABLE
    assert visibility.staleness_ns is None
    assert forecast_take_permitted(visibility) is False


def test_the_unavailable_reason_is_a_named_string_never_a_silent_zero() -> None:
    state = ForecastState()

    visibility = state.visibility_at(NOW_NS, max_staleness_ns=MAX_STALENESS_NS)

    assert visibility.reason == "forecast_unavailable"
    assert visibility.snapshot is None


def test_a_state_fed_by_the_actor_does_permit_a_take() -> None:
    """Non-vacuity for the refusal above."""
    actor, publisher = build()
    publish(publisher, make_point())

    visibility = actor.state_for("KMIA").visibility_at(
        NOW_NS, max_staleness_ns=MAX_STALENESS_NS
    )

    assert visibility.reason == FORECAST_OK
    assert forecast_take_permitted(visibility) is True


# ---------------------------------------------------------------------------
# (c) stale is distinguishable from fresh
# ---------------------------------------------------------------------------


def test_a_stale_forecast_is_named_stale_and_permits_no_take() -> None:
    actor, publisher = build()
    publish(publisher, make_point())

    much_later = AVAILABLE_NS + MAX_STALENESS_NS + NS
    visibility = actor.state_for("KMIA").visibility_at(
        much_later, max_staleness_ns=MAX_STALENESS_NS
    )

    assert visibility.reason == FORECAST_STALE
    assert visibility.snapshot is not None, "the value is still reported, and labelled stale"
    assert visibility.staleness_ns == MAX_STALENESS_NS + NS
    assert forecast_take_permitted(visibility) is False


def test_staleness_is_measured_from_the_vintage() -> None:
    state = ForecastState()
    state.push(value_f=84.0, available_at_ns=AVAILABLE_NS, cycle_runtime_ns=CYCLE_NS)

    assert state.staleness_ns(AVAILABLE_NS + 42 * NS) == 42 * NS
    assert state.staleness_ns(AVAILABLE_NS - 1) is None


def test_a_not_yet_visible_point_never_makes_staleness_negative() -> None:
    state = ForecastState()
    state.push(
        value_f=84.0, available_at_ns=AVAILABLE_NS + 10 * NS, cycle_runtime_ns=CYCLE_NS
    )

    assert state.staleness_ns(AVAILABLE_NS) is None


def test_the_staleness_bound_must_be_positive() -> None:
    with pytest.raises(ValueError):
        ForecastState().visibility_at(NOW_NS, max_staleness_ns=0)


# ---------------------------------------------------------------------------
# Never a catalog read in the hot path
# ---------------------------------------------------------------------------


def test_the_subscriber_never_touches_the_catalog() -> None:
    """R1-11: actor push, never a store read in the hot path.

    Asserted over the AST rather than the raw text: the module DOCUMENTS why
    the catalog-replay path matters, and a substring check would fire on its
    own prose while telling us nothing about what it calls.
    """
    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[3]
        / "src/breezy/strategy/ladder_ev/forecast_subscriber.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)

    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert called.isdisjoint({"query", "custom_data", "write_data", "read_text", "open"})

    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any("persistence" in module or "catalog" in module for module in imported)
