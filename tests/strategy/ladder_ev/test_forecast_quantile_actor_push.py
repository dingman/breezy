"""SL-12: ``ForecastQuantileStateActor`` pushes NBM_NBP quantile points into
:class:`breezy.strategy.ladder_ev.forecast_state.ForecastQuantileState`.

Mirrors ``test_forecast_actor_push.py``'s shape for the scalar TXN actor,
widened to the 7-variable NBP quantile set. ``ForecastStateActor`` itself is
untouched; that suite stays green unchanged.
"""

from __future__ import annotations

import datetime as dt

from nautilus_trader.common.actor import Actor
from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.domain.forecast_point import ForecastPoint
from breezy.ingest.nbm_forecast_data_type import nbm_forecast_point_data_type
from breezy.strategy.ladder_ev.forecast_state import NBP_QUANTILE_VARIABLES
from breezy.strategy.ladder_ev.forecast_subscriber import ForecastQuantileStateActor

NS = 1_000_000_000
_NBP_FLOOR_NS = 60 * 60 * NS
LAG_NS = _NBP_FLOOR_NS + 600 * NS
CYCLE_NS = int(dt.datetime(2026, 9, 19, 13, tzinfo=dt.UTC).timestamp()) * NS
AVAILABLE_NS = CYCLE_NS + LAG_NS
NOW_NS = AVAILABLE_NS + 60 * NS


def make_point(
    *,
    station: str = "KMIA",
    variable: str,
    value_f: float | None = 80.0,
    absence_reason: str | None = None,
    model: str = "NBM_NBP",
    cycle_runtime_ns: int = CYCLE_NS,
) -> ForecastPoint:
    return ForecastPoint(
        station=station,
        model=model,
        model_version="5.0",
        variable=variable,
        cycle_runtime_ns=cycle_runtime_ns,
        valid_start_ns=cycle_runtime_ns + 24 * 3600 * NS,
        valid_end_ns=cycle_runtime_ns + 24 * 3600 * NS,
        value_f=value_f,
        issuance_seq=0,
        measured_publication_lag_ns=LAG_NS,
        available_at_ns=cycle_runtime_ns + LAG_NS,
        ingested_at_ns=cycle_runtime_ns + LAG_NS,
        absence_reason=absence_reason,
    )


class Publisher(Actor):  # type: ignore[misc]
    """Stands in for the ingest actor: publishes through the NATIVE ``publish_data``."""

    def publish(self, point: ForecastPoint) -> None:
        self.publish_data(nbm_forecast_point_data_type(), point)


def build(
    *, stations: tuple[str, ...] = ("KMIA",)
) -> tuple[ForecastQuantileStateActor, Publisher]:
    clock = TestClock()
    clock.set_time(NOW_NS)
    subscriber = ForecastQuantileStateActor(stations=stations)
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


def _publish_all_seven(publisher: Publisher, *, base: float = 80.0) -> None:
    deltas = {
        "TXN_Q10": -4.0,
        "TXN_Q25": -2.0,
        "TXN_Q50": 0.0,
        "TXN_Q75": 2.0,
        "TXN_Q90": 4.0,
        "TXN_MEAN": 0.0,
        "TXN_SD": -77.5,  # forces sd=2.5 given base=80.0
    }
    for variable in NBP_QUANTILE_VARIABLES:
        publisher.publish(make_point(variable=variable, value_f=base + deltas[variable]))


def test_publishing_all_seven_variables_completes_the_vector() -> None:
    actor, publisher = build()

    _publish_all_seven(publisher)

    vector = actor.state_for("KMIA").value_at(NOW_NS)
    assert vector is not None
    assert vector.q50 == 80.0
    assert vector.sd == 2.5


def test_a_partial_publication_never_completes_the_vector() -> None:
    actor, publisher = build()

    for variable in NBP_QUANTILE_VARIABLES[:-1]:
        publisher.publish(make_point(variable=variable, value_f=80.0))

    assert actor.state_for("KMIA").value_at(NOW_NS) is None


def test_a_foreign_model_is_counted_not_stored() -> None:
    actor, publisher = build()

    publisher.publish(make_point(variable="TXN_Q50", model="NBM_NBS", value_f=80.0))

    assert actor.counters["foreign_model"] == 1
    assert actor.state_for("KMIA").value_at(NOW_NS) is None


def test_a_foreign_variable_is_counted_not_stored() -> None:
    actor, publisher = build()

    publisher.publish(make_point(variable="TXN", value_f=80.0))

    assert actor.counters["foreign_variable"] == 1


def test_a_station_the_actor_does_not_serve_is_counted_not_stored() -> None:
    actor, publisher = build(stations=("KMIA",))

    publisher.publish(make_point(station="KSFO", variable="TXN_Q50", value_f=80.0))

    assert actor.counters["unknown_station"] == 1


def test_an_absence_is_counted_by_its_reason_and_never_stored_as_a_value() -> None:
    actor, publisher = build()

    publisher.publish(
        make_point(variable="TXN_Q50", value_f=None, absence_reason="not_published"),
    )

    assert actor.counters["absent_not_published"] == 1
    assert actor.state_for("KMIA").value_at(NOW_NS) is None


def test_an_unserved_station_lookup_raises() -> None:
    import pytest

    actor, _ = build(stations=("KMIA",))
    with pytest.raises(KeyError):
        actor.state_for("KSFO")


def test_constructing_with_no_stations_is_refused() -> None:
    import pytest

    with pytest.raises(ValueError, match="stations"):
        ForecastQuantileStateActor(stations=())
