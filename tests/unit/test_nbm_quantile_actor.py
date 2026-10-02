"""SL-11: the live NBM NBP quantile ingest Actor.

Mirrors `tests/unit/test_nbm_forecast_actor.py`'s own harness shape (a NATIVE
`TestClock` registered through `Actor.register_base`, timers fired
ORGANICALLY through `TestClock.advance_time`, publications captured by
subscribing the REAL bus to the shared `ForecastPoint` `DataType`'s topic,
and a recording fake transport built by the Actor's own injectable
factory) -- adapted to NBP's three cycles (13Z/19Z/01Z) and its
publication-lag floor (60 min, `MINIMUM_PUBLICATION_LAG_NS["NBM_NBP"]`).

Uses the REAL fixtures (`tests/fixtures/nbm/nbptx_t13z_excerpt.txt` etc.,
byte-identical captures, L-17/L-36) rather than a synthetic bulletin: this
Actor's own contract is what it does with a real parsed cycle, not the
parser's drift handling (already RED-tested in `test_nbm_quantile_parse.py`).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.domain.forecast_point import MINIMUM_PUBLICATION_LAG_NS, ForecastPoint
from breezy.ingest.http import TransportError
from breezy.ingest.nbm_forecast_data_type import nbm_forecast_point_data_type
from breezy.ingest.nbm_quantile_actor import (
    BULLETIN_DRIFT_ALERT_MARKER,
    DEFAULT_NBM_QUANTILE_CYCLE_HOURS,
    DEFAULT_NBM_QUANTILE_STALE_DEADLINE_SECONDS,
    STALE_CYCLE_ALERT_MARKER,
    NbmQuantileActor,
    NbmQuantileActorConfig,
    build_nbm_quantile_transport,
)
from breezy.ingest.nbm_quantile_parse import NBM_NBP_MODEL, TXN_VARIABLE_BY_ROW_LABEL
from breezy.ingest.nbm_quantile_transport import NbmQuantileFetchResult

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "nbm"
NS = 1_000_000_000
FLOOR_NS = MINIMUM_PUBLICATION_LAG_NS[NBM_NBP_MODEL]
STATIONS = ("KLAX", "KMDW", "KMIA", "KSFO")

CYCLE_NS = int(dt.datetime(2026, 9, 28, 13, tzinfo=dt.UTC).timestamp()) * NS
LAG_NS = 65 * 60 * NS  # 65 min: above the 60 min floor
NOW_NS = CYCLE_NS + LAG_NS + 60 * NS
LAST_MODIFIED = "Mon, 28 Sep 2026 14:05:00 GMT"  # CYCLE_NS + LAG_NS
TOPIC = f"data.{nbm_forecast_point_data_type().topic}"

FIXTURE_13Z = (FIXTURE_DIR / "nbptx_t13z_excerpt.txt").read_text(encoding="utf-8")


def _rfc2822(instant_ns: int) -> str:
    instant = dt.datetime.fromtimestamp(instant_ns / NS, tz=dt.UTC)
    return instant.strftime("%a, %d %b %Y %H:%M:%S GMT")


class RecordingFetcher:
    """The transport seam: records every request, answers from a script."""

    def __init__(
        self,
        clock: Callable[[], int],
        *,
        texts: Sequence[str],
        last_modifieds: Sequence[str | None],
        raises: BaseException | None,
    ) -> None:
        self.clock = clock
        self._texts = texts
        self._last_modifieds = last_modifieds
        self._raises = raises
        self.calls: list[tuple[dt.date, int, int]] = []

    async def fetch_nbp_bulletin(
        self, *, cycle_date: dt.date, cycle_hour: int
    ) -> NbmQuantileFetchResult:
        now_ns = self.clock()
        self.calls.append((cycle_date, cycle_hour, now_ns))
        if self._raises is not None:
            raise self._raises
        index = min(len(self.calls) - 1, len(self._texts) - 1)
        text = self._texts[index]
        last_modified = self._last_modifieds[min(index, len(self._last_modifieds) - 1)]
        return NbmQuantileFetchResult(
            text=text,
            source_host="noaa-nbm-grib2-pds.s3.amazonaws.com",
            last_modified=last_modified,
            fetched_at_ns=now_ns,
            raw_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            raw_bytes=len(text.encode("utf-8")),
        )


@dataclass
class Harness:
    actor: NbmQuantileActor
    clock: TestClock
    fetchers: list[RecordingFetcher]
    published: list[ForecastPoint] = field(default_factory=list)

    @property
    def fetcher(self) -> RecordingFetcher:
        (fetcher,) = self.fetchers
        return fetcher

    async def drain(self) -> None:
        import asyncio

        for _ in range(5_000):
            if self.actor.inflight == 0:
                return
            await asyncio.sleep(0)
        raise AssertionError("actor still has work in flight")

    async def fire_due_timers(self, to_ns: int) -> int:
        handlers = self.clock.advance_time(to_ns)
        for handler in handlers:
            handler.handle()
        await self.drain()
        return len(handlers)


def build(
    *,
    texts: Sequence[str] = (FIXTURE_13Z,),
    last_modifieds: Sequence[str | None] = (LAST_MODIFIED,),
    raises: BaseException | None = None,
    now_ns: int = NOW_NS,
    **overrides: Any,
) -> Harness:
    clock = TestClock()
    clock.set_time(now_ns)
    fetchers: list[RecordingFetcher] = []

    def factory(clock_fn: Callable[[], int]) -> RecordingFetcher:
        fetcher = RecordingFetcher(
            clock_fn, texts=texts, last_modifieds=last_modifieds, raises=raises
        )
        fetchers.append(fetcher)
        return fetcher

    kwargs: dict[str, Any] = {"station_icaos": STATIONS}
    kwargs.update(overrides)
    actor = NbmQuantileActor(NbmQuantileActorConfig(**kwargs), transport_factory=factory)
    msgbus = TestComponentStubs.msgbus()
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=msgbus,
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    harness = Harness(actor=actor, clock=clock, fetchers=fetchers)
    msgbus.subscribe(topic=TOPIC, handler=harness.published.append)
    return harness


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("icao", ["klax", "KLA", "KLAXX", ""])
def test_a_malformed_station_is_refused_at_config_time(icao: str) -> None:
    with pytest.raises(ValueError):
        NbmQuantileActorConfig(station_icaos=(icao,))


def test_at_least_one_station_is_required() -> None:
    with pytest.raises(ValueError):
        NbmQuantileActorConfig(station_icaos=())


def test_the_default_cycle_hours_are_13z_19z_01z() -> None:
    assert DEFAULT_NBM_QUANTILE_CYCLE_HOURS == (1, 13, 19)
    assert (
        NbmQuantileActorConfig(station_icaos=STATIONS).cycle_hours
        == DEFAULT_NBM_QUANTILE_CYCLE_HOURS
    )


def test_a_stale_deadline_at_or_below_the_publication_floor_is_refused() -> None:
    floor_seconds = FLOOR_NS // NS
    with pytest.raises(ValueError):
        NbmQuantileActorConfig(station_icaos=STATIONS, stale_deadline_seconds=floor_seconds)


# ---------------------------------------------------------------------------
# Scheduling: the first attempt is due at cycle + the publication floor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_start_arms_a_native_timer_and_polls_the_newest_eligible_cycle() -> None:
    harness = build()
    harness.actor.start()
    await harness.drain()

    assert harness.actor.poll_timer_armed is True
    assert harness.fetcher.calls == [(dt.date(2026, 9, 28), 13, NOW_NS)]


# ---------------------------------------------------------------------------
# Publication: 7 TXN variables x 4 stations, the D+1 (nearest MAX) window only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_cycle_publishes_seven_variables_times_four_stations() -> None:
    harness = build()
    harness.actor.start()
    await harness.drain()

    assert len(harness.published) == 28
    assert {type(point) for point in harness.published} == {ForecastPoint}
    assert {point.station for point in harness.published} == set(STATIONS)
    assert {point.variable for point in harness.published} == set(
        TXN_VARIABLE_BY_ROW_LABEL.values()
    )
    for station in STATIONS:
        for variable in TXN_VARIABLE_BY_ROW_LABEL.values():
            matches = [
                point
                for point in harness.published
                if point.station == station and point.variable == variable
            ]
            assert len(matches) == 1, f"{station}/{variable}: expected exactly one D+1 row"


@pytest.mark.asyncio
async def test_each_published_point_carries_the_nearest_window_only() -> None:
    """The parser returns every offered lead; the actor keeps only D+1 (R2-16)."""
    from breezy.ingest.nbm_quantile_parse import parse_nbp_bulletin

    all_points, _ = parse_nbp_bulletin(FIXTURE_13Z, stations=frozenset(STATIONS))
    nearest_by_key: dict[tuple[str, str], Any] = {}
    for point in all_points:
        key = (point.station, point.variable)
        current = nearest_by_key.get(key)
        if current is None or point.valid_start_ns < current.valid_start_ns:
            nearest_by_key[key] = point

    harness = build()
    harness.actor.start()
    await harness.drain()

    published_valid_ns = {
        (point.station, point.variable): point.valid_start_ns for point in harness.published
    }
    expected_valid_ns = {key: point.valid_start_ns for key, point in nearest_by_key.items()}
    assert published_valid_ns == expected_valid_ns


@pytest.mark.asyncio
async def test_ts_event_is_the_cycle_runtime_and_ts_init_is_the_measured_vintage() -> None:
    harness = build()
    harness.actor.start()
    await harness.drain()

    point = harness.published[0]
    assert point.ts_event == CYCLE_NS
    assert point.cycle_runtime_ns == CYCLE_NS
    assert point.measured_publication_lag_ns == LAG_NS
    assert point.available_at_ns == CYCLE_NS + LAG_NS
    assert point.ts_init == point.available_at_ns
    assert point.ingested_at_ns == NOW_NS
    # Never earlier than cycle + the 60-minute publication floor.
    assert point.available_at_ns - point.cycle_runtime_ns >= FLOOR_NS


# ---------------------------------------------------------------------------
# A duplicate cycle is not re-published
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_timer_fires_organically_and_never_refetches_a_known_cycle() -> None:
    harness = build()
    harness.actor.start()
    await harness.drain()
    first_published_count = len(harness.published)

    fired = await harness.fire_due_timers(NOW_NS + 2 * 900 * NS)

    assert fired >= 2
    assert len(harness.fetcher.calls) == 1, "the same cycle must not be refetched"
    assert harness.actor.counters["cycle_already_fetched"] >= 2
    assert len(harness.published) == first_published_count


# ---------------------------------------------------------------------------
# L-16: a timer callback never raises, even when the transport throws
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_poll_that_dies_is_recorded_and_never_swallowed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = build(raises=RuntimeError("upstream shape changed"))
    with caplog.at_level(logging.CRITICAL):
        harness.actor.start()
        await harness.drain()

    assert harness.actor.counters["task_death"] == 1
    assert any("died" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_a_transport_error_is_counted_and_waits_for_the_next_timer_fire() -> None:
    harness = build(raises=TransportError("connection reset"))
    harness.actor.start()
    await harness.drain()

    assert harness.actor.counters["transport_error"] == 1
    assert harness.actor.counters["task_death"] == 0
    assert harness.published == []


@pytest.mark.asyncio
async def test_on_cycle_timer_itself_never_raises_synchronously() -> None:
    """The bare callback (`L-16`'s own hazard): submit-and-return, always."""
    harness = build(raises=RuntimeError("boom"))
    harness.actor.start()
    await harness.drain()

    harness.actor.on_cycle_timer(event=object())  # must not raise
    await harness.drain()


# ---------------------------------------------------------------------------
# Stale-cycle alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stale_cycle_alerts_at_error_with_the_stable_marker(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stale_now_ns = CYCLE_NS + DEFAULT_NBM_QUANTILE_STALE_DEADLINE_SECONDS * NS + 60 * NS
    harness = build(raises=TransportError("connection reset"), now_ns=stale_now_ns)
    with caplog.at_level(logging.ERROR):
        harness.actor.start()
        await harness.drain()

    assert harness.actor.counters["stale_cycle_alert"] >= 1
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any(STALE_CYCLE_ALERT_MARKER in record.message for record in error_records)


@pytest.mark.asyncio
async def test_no_stale_alert_before_the_deadline(
    caplog: pytest.LogCaptureFixture,
) -> None:
    early_now_ns = CYCLE_NS + FLOOR_NS + 60 * NS
    harness = build(raises=TransportError("connection reset"), now_ns=early_now_ns)
    with caplog.at_level(logging.ERROR):
        harness.actor.start()
        await harness.drain()

    assert harness.actor.counters["stale_cycle_alert"] == 0
    assert not any(
        STALE_CYCLE_ALERT_MARKER in record.message for record in caplog.records
    )


# ---------------------------------------------------------------------------
# L-55: the production-default factory must construct, not only the fake
# ---------------------------------------------------------------------------


def test_the_production_transport_factory_constructs() -> None:
    import inspect

    from breezy.ingest.nbm_quantile_transport import NBM_QUANTILE_ALLOWED_HOSTS

    default = inspect.signature(NbmQuantileActor.__init__).parameters["transport_factory"].default
    assert default is build_nbm_quantile_transport

    transport = build_nbm_quantile_transport(lambda: NOW_NS, check_proxy_env=False)
    assert transport._allowed_hosts == NBM_QUANTILE_ALLOWED_HOSTS


# ---------------------------------------------------------------------------
# `_measured_lag_ns` refusal branches (SL-11 review, HIGH): a vintage that
# cannot be measured, or is measured below the floor, must publish nothing
# and be LOUD (L-17) -- mirrors test_nbm_forecast_actor.py's own
# `test_a_missing_last_modified_publishes_nothing_and_is_loud` /
# `test_a_publication_lag_below_the_model_floor_publishes_nothing`.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_missing_last_modified_publishes_nothing_and_is_loud(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = build(last_modifieds=(None,))
    with caplog.at_level(logging.CRITICAL):
        harness.actor.start()
        await harness.drain()

    assert harness.published == []
    assert harness.actor.counters["missing_last_modified"] == 1
    assert any("Last-Modified" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_an_unparsable_last_modified_publishes_nothing_and_is_loud(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = build(last_modifieds=("not-a-valid-http-date",))
    with caplog.at_level(logging.CRITICAL):
        harness.actor.start()
        await harness.drain()

    assert harness.published == []
    assert harness.actor.counters["unparsable_last_modified"] == 1
    assert any("did not parse" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_a_publication_lag_below_the_model_floor_publishes_nothing() -> None:
    """A zero or implausible lag grants look-ahead; it is refused, never clamped."""
    early = _rfc2822(CYCLE_NS + 60 * NS)  # 60 s, below the 60 min NBM_NBP floor
    harness = build(last_modifieds=(early,))
    harness.actor.start()
    await harness.drain()

    assert harness.published == []
    assert harness.actor.counters["publication_lag_below_floor"] == 1
    assert FLOOR_NS == 60 * 60 * NS


# ---------------------------------------------------------------------------
# No running event loop (SL-11 review, HIGH): a backtest has no loop, so
# nothing is armed and no network I/O is possible by construction -- mirrors
# test_nbm_forecast_actor.py::test_with_no_running_loop_nothing_is_armed_and_no_transport_is_built.
# ---------------------------------------------------------------------------


def test_with_no_running_loop_nothing_is_armed_and_no_transport_is_built() -> None:
    harness = build()
    harness.actor.start()

    assert harness.actor.poll_timer_armed is False
    assert harness.fetchers == []


# ---------------------------------------------------------------------------
# Execution-egress firewall (SL-11 review, HIGH): this ingest Actor must
# never become an execution-egress surface -- mirrors
# the WP-12 egress guard (re-homed here when the NBS actor was removed).
# ---------------------------------------------------------------------------

SL11_MODULES = ("src/breezy/ingest/nbm_quantile_actor.py",)


def test_no_sl11_module_is_an_execution_egress_surface() -> None:
    from tests.unit.test_execution_egress_firewall_guard import find_execution_egress_modules

    offenders = [v for v in find_execution_egress_modules() if v.path in SL11_MODULES]

    assert offenders == [], "\n".join(str(v) for v in offenders)


#: Re-homed from the removed `test_nbm_forecast_actor.py` (WP12_MODULES): the
#: surviving forecast-ingest and subscriber modules stay outside the
#: execution-egress surface. Literal paths, so a rename cannot silently empty
#: the scan.
WP12_MODULES = (
    "src/breezy/ingest/nbm_quantile_actor.py",
    "src/breezy/ingest/nbm_quantile_parse.py",
    "src/breezy/ingest/nbm_quantile_transport.py",
    "src/breezy/ingest/nbm_forecast_data_type.py",
    "src/breezy/strategy/ladder_ev/forecast_subscriber.py",
)


def test_every_wp12_module_path_exists() -> None:
    """Non-vacuity: the scan below is only meaningful if each path is real."""
    from tests.unit.test_execution_egress_firewall_guard import REPO_ROOT as _ROOT

    missing = [path for path in WP12_MODULES if not (_ROOT / path).is_file()]

    assert missing == []


def test_no_wp12_module_is_an_execution_egress_surface() -> None:
    from tests.unit.test_execution_egress_firewall_guard import find_execution_egress_modules

    offenders = [v for v in find_execution_egress_modules() if v.path in WP12_MODULES]

    assert offenders == [], "\n".join(str(v) for v in offenders)


def test_the_egress_detector_would_still_fire_on_an_sl11_path() -> None:
    """Non-vacuity: the scan above passes because the module is clean."""
    from tests.unit.test_execution_egress_firewall_guard import _scan_source

    planted = "class ForecastExecutionClient:\n    pass\n"
    assert _scan_source("src/breezy/ingest/nbm_quantile_actor.py", planted) != []


# ---------------------------------------------------------------------------
# Bulletin drift is latched but never silent (SL-11 review, MEDIUM):
# `_fetched_cycles.add(cycle_ns)` runs before `_publish`, so a malformed
# bulletin is never retried in a loop -- but that latch must not lose the
# failure quietly. `NBM_NBP_BULLETIN_DRIFT` is the stable marker.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_bulletin_drift_is_latched_but_never_silent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    malformed = "not an NBP bulletin at all\n"
    harness = build(texts=(malformed,))
    with caplog.at_level(logging.ERROR):
        harness.actor.start()
        await harness.drain()

    assert harness.actor.counters["bulletin_drift"] == 1
    assert harness.published == []
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert any(BULLETIN_DRIFT_ALERT_MARKER in record.message for record in error_records)

    # Latched: a subsequent timer fire must not re-fetch the same cycle.
    fired = await harness.fire_due_timers(NOW_NS + 2 * 900 * NS)
    assert fired >= 2
    assert len(harness.fetcher.calls) == 1
