"""The TestClock-driven harness for `NwsObservationActor` (BL-24 Seam B, converged item 7).

Not a test module: a helper, in the shape of ``operator_control_env.py``.

The Actor is driven with a clock the test controls: a NATIVE `TestClock`
(``nautilus_trader/common/component.pyx:705`` ``set_timer_ns``, ``:790``
``advance_time``) registered through the native ``Actor.register_base``
(``common/actor.pyx:691``) with the message bus, portfolio and cache from
Nautilus' own test kit (``nautilus_trader/test_kit/stubs/component.py:51-67``,
``TestComponentStubs.msgbus/portfolio/cache``). Timers are armed by the
Actor's real ``on_start`` and fired ORGANICALLY: ``TestClock.advance_time``
returns the due ``TimeEventHandler``s and each one's ``handle()``
(``component.pyx:1166``) invokes the Actor's timer callback. Publications
are captured by subscribing the real bus to the shared data type's topic,
never by monkeypatching ``publish_data``.

The fixture is the recorded ``GET /stations/KMDW/observations?limit=500``
response at ``tests/fixtures/nws/kmdw_observations_2026-09-04.json``:
fetched **2026-09-04T02:34:57Z** (``1788489297658387295`` ns), 500 rows,
newest ``2026-09-04T02:20:00Z``, oldest ``2026-09-02T12:00:00Z`` -- so it
reaches the current climate day's local-standard midnight
(``2026-09-03T06:00:00Z``, CST) with ~24 h to spare.

No network I/O: the transport seam is a recording fake constructed by the
Actor's own ``transport_factory`` on the Actor's own clock (A7, one clock).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.domain.station_observation import StationObservation
from breezy.ingest.http import FetchResult
from breezy.ingest.nws_observation_actor import NwsObservationActor, NwsObservationActorConfig
from breezy.ingest.nws_observation_rebuild import local_standard_midnight_ns
from breezy.ingest.nws_observations import (
    NWS_OBSERVATION_SOURCE_CHANNEL,
    nws_observation_rows_to_station_observations,
    station_observation_data_type,
)

FIXTURE_FILE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "nws" / "kmdw_observations_2026-09-04.json"
)
FIXTURE_TEXT = FIXTURE_FILE.read_text(encoding="utf-8")
FIXTURE_ROWS: list[dict[str, Any]] = json.loads(FIXTURE_TEXT)["features"]

NS = 1_000_000_000
FETCH_INSTANT_NS = 1_788_489_297_658_387_295
MDW_STD_OFFSET_HOURS = -6.0
MIDNIGHT_NS = local_standard_midnight_ns(FETCH_INSTANT_NS, MDW_STD_OFFSET_HOURS)
LAG_NS = 1_260 * NS  # 21 min measured 2026-09-04 (provenance only, A6)
INTERVAL_S = 300
BOUND_S = 2_700  # Grok rev 2 section 5: stale_observation_hours = 0.75
BOUND_NS = BOUND_S * NS
TOPIC = f"data.{station_observation_data_type().topic}"


def row_ns(row: dict[str, Any]) -> int:
    instant = dt.datetime.fromisoformat(row["properties"]["timestamp"]).astimezone(dt.UTC)
    return int(instant.timestamp()) * NS


def payload_text(rows: Sequence[dict[str, Any]]) -> str:
    return json.dumps({"type": "FeatureCollection", "features": list(rows)})


def rows_observed_at_or_before(now_ns: int) -> list[dict[str, Any]]:
    return [row for row in FIXTURE_ROWS if row_ns(row) <= now_ns]


def expected_rebuild_rows(now_ns: int = FETCH_INSTANT_NS) -> list[tuple[int, int]]:
    """`(observed_at_ns, temp_c_tenths)` of every in-day fixture row, ascending."""
    observations, _ = nws_observation_rows_to_station_observations(
        station="KMDW",
        payload=json.loads(FIXTURE_TEXT),
        source_channel=NWS_OBSERVATION_SOURCE_CHANNEL,
        assumed_publication_lag_ns=LAG_NS,
        received_at_ns=now_ns,
    )
    in_day = [o for o in observations if o.observed_at_ns >= MIDNIGHT_NS]
    return sorted((o.observed_at_ns, o.temp_c_tenths) for o in in_day)


class RecordingFetcher:
    """The transport seam: records every request and answers from a script."""

    def __init__(
        self,
        clock: Callable[[], int],
        *,
        texts: Sequence[str] | Callable[[int], str],
        raises: BaseException | None,
    ) -> None:
        self.clock = clock
        self._texts = texts
        self._raises = raises
        self.calls: list[tuple[str, int, int]] = []

    async def fetch_station_observations(self, icao: str, *, limit: int) -> FetchResult:
        now_ns = self.clock()
        self.calls.append((icao, limit, now_ns))
        if self._raises is not None:
            raise self._raises
        if callable(self._texts):
            text = self._texts(now_ns)
        else:
            text = self._texts[min(len(self.calls) - 1, len(self._texts) - 1)]
        return FetchResult(
            text=text,
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
            status_code=200,
            headers=httpx.Headers(),
            url=f"https://api.weather.gov/stations/{icao}/observations?limit={limit}",
            retrieved_at_ns=now_ns,
        )


@dataclass
class Harness:
    actor: NwsObservationActor
    clock: TestClock
    fetchers: list[RecordingFetcher]
    published: list[StationObservation] = field(default_factory=list)

    @property
    def fetcher(self) -> RecordingFetcher:
        (fetcher,) = self.fetchers
        return fetcher

    @property
    def calls(self) -> list[tuple[str, int, int]]:
        return self.fetcher.calls

    async def drain(self) -> None:
        """Let every submitted coroutine finish; the bridge is real, not stubbed."""
        for _ in range(5_000):
            if self.actor.inflight == 0:
                return
            await asyncio.sleep(0)
        raise AssertionError("actor still has work in flight")

    async def fire_due_timers(self, to_ns: int) -> int:
        """Advance the TestClock; run every due handler ORGANICALLY; drain."""
        handlers = self.clock.advance_time(to_ns)
        for handler in handlers:
            handler.handle()
        await self.drain()
        return len(handlers)


def build(
    *,
    texts: Sequence[str] | Callable[[int], str] = (FIXTURE_TEXT,),
    raises: BaseException | None = None,
    now_ns: int = FETCH_INSTANT_NS,
    **config_overrides: Any,
) -> Harness:
    clock = TestClock()
    clock.set_time(now_ns)
    fetchers: list[RecordingFetcher] = []

    def factory(clock_fn: Callable[[], int]) -> RecordingFetcher:
        fetcher = RecordingFetcher(clock_fn, texts=texts, raises=raises)
        fetchers.append(fetcher)
        return fetcher

    kwargs: dict[str, Any] = {
        "station_icao": "KMDW",
        "assumed_publication_lag_ns": LAG_NS,
        "poll_interval_seconds": INTERVAL_S,
        "staleness_bound_seconds": BOUND_S,
    }
    kwargs.update(config_overrides)
    actor = NwsObservationActor(
        NwsObservationActorConfig(**kwargs),
        std_utc_offset_hours=MDW_STD_OFFSET_HOURS,
        transport_factory=factory,
    )
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
