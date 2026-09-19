"""The per-cycle NBM forecast Actor -- WP-12 Seam B.

One instance serves a set of stations from ONE collective NBS bulletin, on a
NATIVE Nautilus timer, and publishes every parsed `ForecastPoint` on the ONE
shared ``DataType`` topic. **Raw records only: this Actor holds no state the
decider reads.** The decider owns its `ForecastState` and is fed by actor
PUSH on the message bus (plan R1-11) -- never by a catalog query in the hot
path, and never by an import from ``ingest`` into ``strategy``, which the
``lint-imports`` layer contract forbids in that direction.

Native, therefore used rather than rebuilt (verified in the installed
``nautilus-trader==1.231.0``):

* timer scheduling -- ``Clock.set_timer(name, interval, start_time=...,
  callback=...)`` (``common/component.pyx:419``);
* publication -- ``Actor.publish_data(DataType, Data)``
  (``common/actor.pyx:2813``);
* lifecycle -- ``Actor._start -> on_start`` and registration through
  ``Trader.add_actor``.

A TIMER, not a polling loop. There is no ``while`` and no ``asyncio.sleep``
in this module: a loop would be network I/O the moment a test constructed the
Actor, and it would be a second scheduler beside the Nautilus clock. As in
``nws_observation_actor.py``, the timer callback runs on a Rust
``_DummyThread`` where a ``LiveClock`` SWALLOWS anything raised (L-16), so
``on_cycle_timer`` does exactly two things -- submit and return -- and
supervision is the returned handle's done-callback, which marshals any
exception back onto the loop and COUNTS it.

Per CYCLE, not per tick: each fire resolves the newest cycle whose
publication window has closed and fetches it at most ONCE. A cycle already
fetched is counted and skipped, so a 15-minute timer against 6-hourly cycles
costs one request per cycle, not one per fire.

The VINTAGE is measured, never assumed. ``available_at_ns`` comes from the
response's ``Last-Modified`` minus nothing: the lag is
``last_modified - cycle_runtime``, and `ForecastPoint` derives the vintage
from it. If the header is absent, or the measured lag falls below the model's
`MINIMUM_PUBLICATION_LAG_NS` floor, NOTHING is published for that cycle and a
``CRITICAL`` is logged -- an assumed or clamped lag would grant look-ahead
across the publication repricing window, which is the one error this seam
exists to prevent (L-17: withhold, never publish a confidently wrong value).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime as dt
import logging
import re
import threading
from collections import Counter
from collections.abc import Callable
from datetime import timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Final, Protocol

from nautilus_trader.common.actor import Actor
from nautilus_trader.common.config import ActorConfig

from breezy.domain.forecast_point import MINIMUM_PUBLICATION_LAG_NS
from breezy.ingest.http import FetchResult, RateLimitedError, TransportError
from breezy.ingest.nbm_forecast_data_type import nbm_forecast_point_data_type
from breezy.ingest.nbm_forecast_parse import (
    NBM_NBS_MODEL,
    NbsBulletinDriftError,
    parse_nbs_bulletin,
)
from breezy.ingest.nbm_forecast_transport import NbmForecastTransport

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_NBM_CYCLE_HOURS",
    "DEFAULT_NBM_TIMER_INTERVAL_SECONDS",
    "BulletinFetcher",
    "NbmForecastActor",
    "NbmForecastActorConfig",
    "TransportFactory",
    "build_nbm_forecast_transport",
]

_NS_PER_SECOND: Final[int] = 1_000_000_000
_SECONDS_PER_HOUR: Final[int] = 3_600
_ICAO_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A[A-Z]{4}\Z")

#: The NBS cycle hours the FC-0a census observed as `runtime` values
#: (``docs/evidence/FC_0a_TXN_OCCUPANCY_2026-09-19.md``). Whether this origin
#: also serves hourly cycles is UNVERIFIED, so the measured four are the
#: default rather than an assumed 24.
DEFAULT_NBM_CYCLE_HOURS: Final[tuple[int, ...]] = (0, 6, 12, 18)

#: Fires often enough that a cycle is picked up within a quarter hour of its
#: publication window closing; the per-cycle latch keeps the request count at
#: one per cycle regardless.
DEFAULT_NBM_TIMER_INTERVAL_SECONDS: Final[int] = 900


class BulletinFetcher(Protocol):
    """The one transport method the Actor calls."""

    async def fetch_nbs_bulletin(
        self, *, cycle_date: dt.date, cycle_hour: int
    ) -> FetchResult: ...


#: Builds the transport ON THE ACTOR'S CLOCK -- called from `on_start` with
#: `self.clock.timestamp_ns`, so a transport on any other clock cannot be
#: wired in by construction (one clock).
TransportFactory = Callable[[Callable[[], int]], BulletinFetcher]


def build_nbm_forecast_transport(
    clock: Callable[[], int], *, check_proxy_env: bool = True
) -> NbmForecastTransport:
    """The production `TransportFactory`. NBM direct is the live PRIMARY."""
    return NbmForecastTransport(clock=clock, check_proxy_env=check_proxy_env)


class NbmForecastActorConfig(ActorConfig, frozen=True):
    """Configuration for one forecast Actor serving a set of stations.

    Scalar, msgspec-serialisable fields only -- see `NwsIngestActorConfig`.
    """

    station_icaos: tuple[str, ...]
    cycle_hours: tuple[int, ...] = DEFAULT_NBM_CYCLE_HOURS
    timer_interval_seconds: int = DEFAULT_NBM_TIMER_INTERVAL_SECONDS
    stagger_offset_seconds: int = 0

    def __post_init__(self) -> None:
        if not self.station_icaos:
            raise ValueError("`station_icaos` must name at least one station")
        for icao in self.station_icaos:
            if _ICAO_PATTERN.match(icao) is None:
                raise ValueError(
                    f"`station_icaos` entries must be four-letter upper-case ICAO "
                    f"ids, found {icao!r}"
                )
        if not self.cycle_hours:
            raise ValueError("`cycle_hours` must name at least one cycle hour")
        for hour in self.cycle_hours:
            if not 0 <= hour <= 23:
                raise ValueError(f"`cycle_hours` entries must be in 0..23, found {hour}")
        if self.timer_interval_seconds <= 0:
            raise ValueError("`timer_interval_seconds` must be positive")
        if self.stagger_offset_seconds < 0:
            raise ValueError("`stagger_offset_seconds` must be non-negative")


class NbmForecastActor(Actor):
    """Fetches one NBS cycle per cycle and publishes raw records. See the module docstring."""

    def __init__(
        self,
        config: NbmForecastActorConfig,
        *,
        transport_factory: TransportFactory = build_nbm_forecast_transport,
    ) -> None:
        super().__init__(config)
        self._config = config
        self._stations = frozenset(config.station_icaos)
        self._cycle_hours = tuple(sorted(set(config.cycle_hours)))
        self._transport_factory = transport_factory
        self._transport: BulletinFetcher | None = None
        self._floor_ns = MINIMUM_PUBLICATION_LAG_NS[NBM_NBS_MODEL]

        self._loop: asyncio.AbstractEventLoop | None = None
        self._timer_armed = False
        self._poll_in_flight = False
        #: Cycle runtimes already fetched, so a cycle costs exactly one request.
        self._fetched_cycles: set[int] = set()

        self._inflight = 0
        self._inflight_lock = threading.Lock()
        self.counters: Counter[str] = Counter()
        self.published_count = 0

    # -- observability ------------------------------------------------------

    @property
    def inflight(self) -> int:
        """Submitted coroutines not yet fully supervised (tests drain on this)."""
        with self._inflight_lock:
            return self._inflight

    @property
    def poll_timer_armed(self) -> bool:
        return self._timer_armed

    # -- lifecycle ----------------------------------------------------------

    def on_start(self) -> None:
        """Capture the loop, build the transport on THIS clock, fetch, arm the timer.

        With no running loop (a backtest) nothing is armed and no transport is
        built: no network I/O by construction.
        """
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
            logger.info("no running event loop: no NBM forecast polling armed")
            return
        self._transport = self._transport_factory(self.clock.timestamp_ns)
        self._submit(self.poll_once())
        self._arm_timer()

    def on_stop(self) -> None:
        if not self._timer_armed:
            return
        try:
            self.clock.cancel_timer(self._timer_name)
        except (KeyError, ValueError):  # pragma: no cover - defensive
            logger.debug("timer %s was already cancelled", self._timer_name)
        self._timer_armed = False

    def _arm_timer(self) -> None:
        if self._timer_armed:
            return
        self.clock.set_timer(
            name=self._timer_name,
            interval=timedelta(seconds=int(self._config.timer_interval_seconds)),
            start_time=self._stagger_start_time(),
            callback=self.on_cycle_timer,
        )
        self._timer_armed = True

    def _stagger_start_time(self) -> dt.datetime | None:
        """Phase shift via the NATIVE `start_time=`."""
        offset = int(self._config.stagger_offset_seconds)
        if offset <= 0:
            return None
        now: dt.datetime = self.clock.utc_now()
        return now + timedelta(seconds=offset)

    @property
    def _timer_name(self) -> str:
        return "nbm-forecast-cycle"

    # -- the cross-thread bridge (L-16) -------------------------------------

    def on_cycle_timer(self, event: object) -> None:
        """Timer callback: submit and return. Never raises (a `LiveClock` would swallow it)."""
        self._submit(self.poll_once())

    def _submit(self, coro: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            coro.close()
            return
        with self._inflight_lock:
            self._inflight += 1
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:  # pragma: no cover - shutdown race
            coro.close()
            self._settle()
            return
        future.add_done_callback(self._on_poll_done)

    def _settle(self) -> None:
        with self._inflight_lock:
            self._inflight -= 1

    def _on_poll_done(self, future: concurrent.futures.Future[None]) -> None:
        """Supervision, on the COMPLETING thread: marshal any death back onto the loop."""
        if future.cancelled():
            self._settle()
            return
        exc = future.exception()
        if exc is None:
            self._settle()
            return
        loop = self._loop
        if loop is None or loop.is_closed():  # pragma: no cover - shutdown race
            logger.critical("NBM forecast task died after loop close: %r", exc)
            self._settle()
            return
        loop.call_soon_threadsafe(self._record_task_death, exc)

    def _record_task_death(self, exc: BaseException) -> None:
        logger.critical("NBM forecast cycle task died: %r", exc, exc_info=exc)
        self.counters["task_death"] += 1
        self._settle()

    # -- one cycle ----------------------------------------------------------

    def latest_available_cycle_ns(self, now_ns: int) -> int | None:
        """The newest configured cycle whose minimum publication window has closed.

        Uses the model's `MINIMUM_PUBLICATION_LAG_NS` floor only as a
        SCHEDULING bound -- "do not ask before it could possibly exist". The
        lag that reaches a record is always the MEASURED one.
        """
        deadline_ns = now_ns - self._floor_ns
        day_ns = 24 * _SECONDS_PER_HOUR * _NS_PER_SECOND
        hour_ns = _SECONDS_PER_HOUR * _NS_PER_SECOND
        day_start_ns = deadline_ns - deadline_ns % day_ns
        candidates = [
            day_start_ns + offset - shift
            for shift in (0, day_ns)
            for offset in (hour * hour_ns for hour in self._cycle_hours)
        ]
        eligible = [candidate for candidate in candidates if candidate <= deadline_ns]
        return max(eligible) if eligible else None

    async def poll_once(self) -> None:
        """One attempt at the newest un-fetched cycle."""
        transport = self._transport
        if transport is None:
            return
        if self._poll_in_flight:
            self.counters["poll_overlapped"] += 1
            return
        cycle_ns = self.latest_available_cycle_ns(self.clock.timestamp_ns())
        if cycle_ns is None:  # pragma: no cover - defensive
            self.counters["no_cycle_available"] += 1
            return
        if cycle_ns in self._fetched_cycles:
            self.counters["cycle_already_fetched"] += 1
            return
        self._poll_in_flight = True
        try:
            await self._fetch_cycle(transport, cycle_ns)
        finally:
            self._poll_in_flight = False

    async def _fetch_cycle(self, transport: BulletinFetcher, cycle_ns: int) -> None:
        instant = dt.datetime.fromtimestamp(cycle_ns / _NS_PER_SECOND, tz=dt.UTC)
        try:
            result = await transport.fetch_nbs_bulletin(
                cycle_date=instant.date(), cycle_hour=instant.hour
            )
        except RateLimitedError as exc:
            self.counters["rate_limited"] += 1
            logger.warning("rate limited (%s); next attempt is the next timer fire", exc)
            return
        except TransportError as exc:
            self.counters["transport_error"] += 1
            logger.warning("transport error (%s); next attempt is the next timer fire", exc)
            return

        lag_ns = self._measured_lag_ns(result, cycle_ns)
        if lag_ns is None:
            return
        self._fetched_cycles.add(cycle_ns)
        self._publish(result, lag_ns)

    def _measured_lag_ns(self, result: FetchResult, cycle_ns: int) -> int | None:
        """The MEASURED publication lag, or `None` when it cannot be trusted.

        Both refusals are loud and publish nothing: a vintage that is assumed
        or clamped up to the floor would be look-ahead stored as evidence.
        """
        raw = result.headers.get("last-modified")
        if not raw:
            self.counters["missing_last_modified"] += 1
            logger.critical(
                "NBS bulletin carried no Last-Modified header; the publication lag "
                "cannot be measured, so nothing is published for this cycle"
            )
            return None
        try:
            published = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            self.counters["unparsable_last_modified"] += 1
            logger.critical("NBS bulletin Last-Modified %r did not parse", raw)
            return None
        lag_ns = int(published.timestamp()) * _NS_PER_SECOND - cycle_ns
        if lag_ns < self._floor_ns:
            self.counters["publication_lag_below_floor"] += 1
            logger.critical(
                "measured publication lag %d ns is below the %s floor of %d ns; "
                "nothing is published for this cycle rather than clamping a vintage",
                lag_ns,
                NBM_NBS_MODEL,
                self._floor_ns,
            )
            return None
        return lag_ns

    def _publish(self, result: FetchResult, lag_ns: int) -> None:
        if result.text is None:  # pragma: no cover - `allow_not_modified=False` forbids a 304
            raise ValueError("NBS bulletin fetch returned no body")
        try:
            points, drops = parse_nbs_bulletin(
                result.text,
                stations=self._stations,
                measured_publication_lag_ns=lag_ns,
                ingested_at_ns=result.retrieved_at_ns,
            )
        except NbsBulletinDriftError:
            # Counted here AND re-raised: the count keeps the failure visible
            # on the Actor, and the raise reaches the supervisor so a layout
            # change cannot be a quiet no-op poll.
            self.counters["bulletin_drift"] += 1
            raise
        self.counters.update(drops)
        data_type = nbm_forecast_point_data_type()
        for point in points:
            self.publish_data(data_type, point)
            self.published_count += 1
