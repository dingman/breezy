"""WP-12 Seam B: the per-cycle NBM forecast Actor.

Native, therefore used rather than rebuilt (verified in the installed
``nautilus-trader==1.231.0``): ``Clock.set_timer`` (``common/component.pyx:419``),
``Actor.publish_data`` (``common/actor.pyx:2813``), ``Actor._start -> on_start``.

The Actor is driven by a NATIVE ``TestClock`` registered through
``Actor.register_base``, timers fire ORGANICALLY through
``TestClock.advance_time``, and publications are captured by subscribing the
REAL bus to the shared ``DataType``'s topic -- the shape
``tests/unit/nws_observation_harness.py`` established. The transport seam is a
recording fake built by the Actor's own factory on the Actor's own clock: no
network I/O by construction.
"""

from __future__ import annotations

import ast
import asyncio
import datetime as dt
import hashlib
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.domain.forecast_point import MINIMUM_PUBLICATION_LAG_NS, ForecastPoint
from breezy.ingest.http import FetchResult, TransportError
from breezy.ingest.nbm_forecast_actor import (
    DEFAULT_NBM_CYCLE_HOURS,
    NbmForecastActor,
    NbmForecastActorConfig,
)
from breezy.ingest.nbm_forecast_data_type import nbm_forecast_point_data_type
from tests.unit.test_nbm_forecast_parse import REAL_BLOCK

REPO_ROOT = Path(__file__).resolve().parents[2]
NS = 1_000_000_000
FLOOR_NS = MINIMUM_PUBLICATION_LAG_NS["NBM_NBS"]
CYCLE_NS = int(dt.datetime(2026, 9, 19, 12, tzinfo=dt.UTC).timestamp()) * NS
LAG_NS = 30 * 60 * NS
NOW_NS = CYCLE_NS + LAG_NS + 60 * NS
LAST_MODIFIED = "Sat, 19 Sep 2026 12:30:00 GMT"
TOPIC = f"data.{nbm_forecast_point_data_type().topic}"


class RecordingFetcher:
    """The transport seam: records every request, answers from a script."""

    def __init__(
        self,
        clock: Callable[[], int],
        *,
        texts: Sequence[str],
        headers: Sequence[dict[str, str]],
        raises: BaseException | None,
    ) -> None:
        self.clock = clock
        self._texts = texts
        self._headers = headers
        self._raises = raises
        self.calls: list[tuple[dt.date, int, int]] = []

    async def fetch_nbs_bulletin(self, *, cycle_date: dt.date, cycle_hour: int) -> FetchResult:
        now_ns = self.clock()
        self.calls.append((cycle_date, cycle_hour, now_ns))
        if self._raises is not None:
            raise self._raises
        index = min(len(self.calls) - 1, len(self._texts) - 1)
        text = self._texts[index]
        header = self._headers[min(index, len(self._headers) - 1)]
        return FetchResult(
            text=text,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            status_code=200,
            headers=httpx.Headers(header),
            url=(
                "https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/"
                f"blend.{cycle_date:%Y%m%d}/{cycle_hour:02d}/text/blend_nbstx.t{cycle_hour:02d}z"
            ),
            retrieved_at_ns=now_ns,
        )


@dataclass
class Harness:
    actor: NbmForecastActor
    clock: TestClock
    fetchers: list[RecordingFetcher]
    published: list[ForecastPoint] = field(default_factory=list)

    @property
    def fetcher(self) -> RecordingFetcher:
        (fetcher,) = self.fetchers
        return fetcher

    async def drain(self) -> None:
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
    texts: Sequence[str] = (REAL_BLOCK,),
    headers: Sequence[dict[str, str]] = ({"last-modified": LAST_MODIFIED},),
    raises: BaseException | None = None,
    now_ns: int = NOW_NS,
    **overrides: Any,
) -> Harness:
    clock = TestClock()
    clock.set_time(now_ns)
    fetchers: list[RecordingFetcher] = []

    def factory(clock_fn: Callable[[], int]) -> RecordingFetcher:
        fetcher = RecordingFetcher(clock_fn, texts=texts, headers=headers, raises=raises)
        fetchers.append(fetcher)
        return fetcher

    kwargs: dict[str, Any] = {"station_icaos": ("KMIA",)}
    kwargs.update(overrides)
    actor = NbmForecastActor(NbmForecastActorConfig(**kwargs), transport_factory=factory)
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


@pytest.mark.parametrize("icao", ["kmia", "KMI", "KMIAX", ""])
def test_a_malformed_station_is_refused_at_config_time(icao: str) -> None:
    with pytest.raises(ValueError):
        NbmForecastActorConfig(station_icaos=(icao,))


def test_at_least_one_station_is_required() -> None:
    with pytest.raises(ValueError):
        NbmForecastActorConfig(station_icaos=())


def test_the_measured_cycle_hours_are_the_default() -> None:
    assert DEFAULT_NBM_CYCLE_HOURS == (0, 6, 12, 18)
    assert NbmForecastActorConfig(station_icaos=("KMIA",)).cycle_hours == DEFAULT_NBM_CYCLE_HOURS


# ---------------------------------------------------------------------------
# A per-cycle TIMER, never a polling loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_start_arms_a_native_timer_and_polls_once() -> None:
    harness = build()
    harness.actor.start()
    await harness.drain()

    assert harness.actor.poll_timer_armed is True
    assert harness.fetcher.calls == [(dt.date(2026, 9, 19), 12, NOW_NS)]


@pytest.mark.asyncio
async def test_the_timer_fires_organically_and_never_refetches_a_known_cycle() -> None:
    harness = build()
    harness.actor.start()
    await harness.drain()

    fired = await harness.fire_due_timers(NOW_NS + 2 * 900 * NS)

    assert fired >= 2
    assert len(harness.fetcher.calls) == 1, "the same cycle must not be refetched"
    assert harness.actor.counters["cycle_already_fetched"] >= 2


def test_the_actor_module_contains_no_polling_loop() -> None:
    """A `while True` in an ingest actor is network I/O in tests. There is none."""
    source = (REPO_ROOT / "src/breezy/ingest/nbm_forecast_actor.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert [n for n in ast.walk(tree) if isinstance(n, ast.While)] == []
    # AST, not a substring: the module DOCUMENTS that it holds no sleep, and a
    # substring check would fire on its own prose.
    sleeps = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "sleep"
    ]
    assert sleeps == []


def test_with_no_running_loop_nothing_is_armed_and_no_transport_is_built() -> None:
    """A backtest has no loop: no timer, no transport, therefore no network I/O."""
    harness = build()
    harness.actor.start()

    assert harness.actor.poll_timer_armed is False
    assert harness.fetchers == []


# ---------------------------------------------------------------------------
# L-16: a timer callback that raises must not silently vanish
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


# ---------------------------------------------------------------------------
# Publication on the ONE shared topic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_parsed_point_is_published_on_the_shared_data_type() -> None:
    harness = build()
    harness.actor.start()
    await harness.drain()

    assert len(harness.published) == 6
    assert {type(point) for point in harness.published} == {ForecastPoint}
    assert [point.value_f for point in harness.published] == [84.0, 76.0, 84.0, 75.0, 84.0, 75.0]
    assert {point.available_at_ns for point in harness.published} == {CYCLE_NS + LAG_NS}


@pytest.mark.asyncio
async def test_the_vintage_uses_the_measured_last_modified_lag_never_a_clock_read() -> None:
    harness = build()
    harness.actor.start()
    await harness.drain()

    point = harness.published[0]
    assert point.measured_publication_lag_ns == LAG_NS
    assert point.available_at_ns == point.cycle_runtime_ns + LAG_NS
    assert point.ingested_at_ns == NOW_NS


@pytest.mark.asyncio
async def test_a_missing_last_modified_publishes_nothing_and_is_loud(
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness = build(headers=({},))
    with caplog.at_level(logging.CRITICAL):
        harness.actor.start()
        await harness.drain()

    assert harness.published == []
    assert harness.actor.counters["missing_last_modified"] == 1


@pytest.mark.asyncio
async def test_a_publication_lag_below_the_model_floor_publishes_nothing() -> None:
    """A zero or implausible lag grants look-ahead; it is refused, never clamped."""
    early = "Sat, 19 Sep 2026 12:01:00 GMT"  # 60 s, below the 20 min NBM_NBS floor
    harness = build(headers=({"last-modified": early},))
    harness.actor.start()
    await harness.drain()

    assert harness.published == []
    assert harness.actor.counters["publication_lag_below_floor"] == 1
    assert FLOOR_NS == 20 * 60 * NS


# ---------------------------------------------------------------------------
# NBM direct is the live PRIMARY
# ---------------------------------------------------------------------------


def test_the_production_transport_factory_is_the_nbm_host() -> None:
    from breezy.ingest.nbm_forecast_actor import build_nbm_forecast_transport
    from breezy.ingest.nbm_forecast_transport import NBM_ALLOWED_HOSTS

    transport = build_nbm_forecast_transport(lambda: NOW_NS, check_proxy_env=False)

    assert transport._allowed_hosts == NBM_ALLOWED_HOSTS
    assert transport._base_url.startswith("https://nomads.ncep.noaa.gov")


# ---------------------------------------------------------------------------
# The new modules are OUTSIDE the execution-egress surface
# ---------------------------------------------------------------------------

WP12_MODULES = (
    "src/breezy/ingest/nbm_forecast_actor.py",
    "src/breezy/ingest/nbm_forecast_transport.py",
    "src/breezy/ingest/nbm_forecast_parse.py",
    "src/breezy/ingest/nbm_forecast_data_type.py",
    "src/breezy/ingest/iem_mos_fallback_transport.py",
    "src/breezy/strategy/ladder_ev/forecast_subscriber.py",
)


def test_no_wp12_module_is_an_execution_egress_surface() -> None:
    from tests.unit.test_execution_egress_firewall_guard import find_execution_egress_modules

    offenders = [v for v in find_execution_egress_modules() if v.path in WP12_MODULES]

    assert offenders == [], "\n".join(str(v) for v in offenders)


def test_the_egress_detector_would_still_fire_on_a_wp12_path() -> None:
    """Non-vacuity: the scan above passes because the modules are clean."""
    from tests.unit.test_execution_egress_firewall_guard import _scan_source

    planted = "class ForecastExecutionClient:\n    pass\n"
    assert _scan_source("src/breezy/ingest/nbm_forecast_actor.py", planted) != []
