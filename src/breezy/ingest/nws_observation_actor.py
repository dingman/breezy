"""The per-station NWS observation Actor -- BL-24 Seam B, section 3.

One instance per 5-minute ASOS station (KLAX, KMDW, KMIA, KSFO; KNYC is
hourly-only and refused at config time -- amendment A14, converged item 8).
It polls ``/stations/{icao}/observations`` on a NATIVE Nautilus timer and
publishes every accepted `StationObservation` on the ONE shared
``DataType`` topic. **Raw records only: this Actor holds no accumulator.**
The strategy owns its `RunningExtremeAccumulator` and pushes on ``on_data``
(brief section 3: the `lint-imports` layer contract places `strategy` above
`ingest`, and the accumulator is pure and belongs with its consumer).

Native, therefore used rather than rebuilt (verified in the installed
``nautilus-trader==1.231.0``):

* timer scheduling with a phase shift -- ``Clock.set_timer(name, interval,
  start_time=..., callback=...)`` (``common/component.pyx:419``);
* publication -- ``Actor.publish_data(DataType, Data)``
  (``common/actor.pyx:2813``);
* lifecycle -- ``Actor._start -> on_start`` (``actor.pyx:1208``) and
  registration through ``Trader.add_actor`` (``trading/trader.py:312``).

Authored here, with the measurement that forced it (``nws_actor.py``'s
docstring and ``tests/contract/test_live_timer_thread_affinity.py``): the
timer callback runs on a Rust ``_DummyThread`` with no running loop, and a
``LiveClock`` SWALLOWS anything raised there (L-16). So ``on_poll_timer``
does exactly two things -- submit and return -- through
``asyncio.run_coroutine_threadsafe``; supervision is the returned handle's
done-callback, which marshals any exception back onto the loop.

One clock (amendment A7): the transport is built in ``on_start`` from
``self.clock.timestamp_ns``, so the receipt stamps that become ``ts_init``
and every politeness decision read the Actor's own Nautilus clock. There is
no ``time.time_ns()`` and no float time math in this module.

Politeness (S2): one request per poll, 300 s cadence per station
(NWS ``cache-control: max-age=92``), per-station stagger through the native
``start_time``, and never two requests within one second -- a timer fire
that lands too soon is SKIPPED and counted, never slept through (a sleep
would be a second clock). A ``RateLimitedError`` or any ``TransportError``
NEVER triggers an immediate re-poll: the next attempt is the next timer fire.

Restart rebuild (amendment A8): the first poll after ``on_start`` is ONE
bounded fetch covering the current climate day from local-standard
midnight. It is trusted only if it reaches midnight and has no gap over the
staleness bound (`nws_observation_rebuild.rebuild_is_trusted`). Untrusted:
NOTHING is published for the station -- not even partial rows -- and a
``CRITICAL`` is logged, so the strategy refuses ``observation_unavailable``.
A partial rebuild would yield a LOWER `R` -- a wrong signal, not a
suppressed one -- which is why it is withheld (L-17). If the response did
not even reach midnight, the next attempt asks for the API ceiling (500).
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime as dt
import json
import logging
import threading
from collections import Counter
from datetime import timedelta
from typing import Any, Final

from nautilus_trader.common.actor import Actor

from breezy.domain.station_observation import StationObservation
from breezy.ingest.http import FetchResult, RateLimitedError, TransportError
from breezy.ingest.nws_observation_config import (
    DEFAULT_OBSERVATION_POLL_INTERVAL_SECONDS,
    DEFAULT_STALENESS_BOUND_SECONDS,
    EXCLUDED_ICAOS,
    MIN_REQUEST_SPACING_NS,
    NwsObservationActorConfig,
    ObservationFetcher,
    TransportFactory,
    build_observation_transport,
)
from breezy.ingest.nws_observation_rebuild import (
    MAX_OBSERVATION_LIMIT,
    local_standard_midnight_ns,
    observation_fetch_limit,
    rebuild_is_trusted,
)
from breezy.ingest.nws_observations import (
    nws_observation_rows_to_station_observations,
    station_observation_data_type,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_OBSERVATION_POLL_INTERVAL_SECONDS",
    "DEFAULT_STALENESS_BOUND_SECONDS",
    "EXCLUDED_ICAOS",
    "MIN_REQUEST_SPACING_NS",
    "NwsObservationActor",
    "NwsObservationActorConfig",
    "ObservationFetcher",
    "TransportFactory",
    "build_observation_transport",
]

_NS_PER_SECOND: Final[int] = 1_000_000_000


class NwsObservationActor(Actor):
    """Polls one station's observations and publishes raw records. See the module docstring."""

    def __init__(
        self,
        config: NwsObservationActorConfig,
        *,
        std_utc_offset_hours: float,
        transport_factory: TransportFactory = build_observation_transport,
    ) -> None:
        super().__init__(config)
        self._config = config
        self._icao = config.station_icao
        self._std_utc_offset_hours = float(std_utc_offset_hours)
        self._staleness_bound_ns = int(config.staleness_bound_seconds) * _NS_PER_SECOND
        self._transport_factory = transport_factory
        self._transport: ObservationFetcher | None = None

        self._loop: asyncio.AbstractEventLoop | None = None
        self._timer_armed = False
        self._poll_in_flight = False
        self._rebuild_trusted = False
        self._escalate_to_ceiling = False
        self._last_request_ns: int | None = None
        self._last_success_ns: int | None = None
        #: `observed_at_ns -> temp_c_tenths` published for the current climate day.
        self._published: dict[int, int] = {}
        self._published_midnight_ns: int | None = None

        self._inflight = 0
        self._inflight_lock = threading.Lock()
        #: Drop reasons from the parser plus this Actor's own event counts.
        self.counters: Counter[str] = Counter()
        self.published_count = 0

    # -- observability ------------------------------------------------------

    @property
    def station_icao(self) -> str:
        return self._icao

    @property
    def rebuild_trusted(self) -> bool:
        return self._rebuild_trusted

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
        """Capture the loop, build the transport on THIS clock, rebuild, arm the timer.

        With no running loop (a backtest) nothing is armed and no transport
        is built: no network I/O by construction.
        """
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
            logger.info("no running event loop for %s: no observation polling armed", self._icao)
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
            interval=timedelta(seconds=int(self._config.poll_interval_seconds)),
            start_time=self._stagger_start_time(),
            callback=self.on_poll_timer,
        )
        self._timer_armed = True

    def _stagger_start_time(self) -> dt.datetime | None:
        """Phase shift via the NATIVE `start_time=` -- `nws_actor.py:671-700`'s pattern."""
        offset = int(self._config.stagger_offset_seconds)
        if offset <= 0:
            return None
        now: dt.datetime = self.clock.utc_now()
        return now + timedelta(seconds=offset)

    @property
    def _timer_name(self) -> str:
        return f"nws-obs-poll-{self._icao}"

    # -- the cross-thread bridge (L-16) ---------------------------------------

    def on_poll_timer(self, event: object) -> None:
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
            logger.critical("poll task for %s died after loop close: %r", self._icao, exc)
            self._settle()
            return
        loop.call_soon_threadsafe(self._record_task_death, exc)

    def _record_task_death(self, exc: BaseException) -> None:
        logger.critical(
            "observation poll task for %s died: %r", self._icao, exc, exc_info=exc
        )
        self.counters["task_death"] += 1
        # Fail closed: whatever state the poll left behind, the next attempt
        # re-proves coverage from midnight before anything is published.
        self._rebuild_trusted = False
        self._settle()

    # -- one poll -------------------------------------------------------------

    async def poll_once(self) -> None:
        """One attempt: a rebuild until trusted, a bounded steady poll thereafter."""
        transport = self._transport
        if transport is None:
            return
        now_ns = self.clock.timestamp_ns()
        if self._poll_in_flight:
            self.counters["poll_overlapped"] += 1
            return
        last = self._last_request_ns
        if last is not None and now_ns - last < MIN_REQUEST_SPACING_NS:
            self.counters["poll_skipped_too_soon"] += 1
            return
        self._poll_in_flight = True
        try:
            await self._poll(transport, now_ns)
        finally:
            self._poll_in_flight = False

    def _needs_rebuild(self, now_ns: int) -> bool:
        if not self._rebuild_trusted:
            return True
        last_success = self._last_success_ns
        return last_success is None or now_ns - last_success > self._staleness_bound_ns

    def _fetch_limit(self, now_ns: int, midnight_ns: int, rebuilding: bool) -> int:
        if rebuilding:
            if self._escalate_to_ceiling:
                return MAX_OBSERVATION_LIMIT
            return observation_fetch_limit((now_ns - midnight_ns) // _NS_PER_SECOND)
        last_success = self._last_success_ns
        assert last_success is not None  # `_needs_rebuild` is False only with a success
        return observation_fetch_limit((now_ns - last_success) // _NS_PER_SECOND)

    async def _poll(self, transport: ObservationFetcher, now_ns: int) -> None:
        midnight_ns = local_standard_midnight_ns(now_ns, self._std_utc_offset_hours)
        self._roll_day(midnight_ns)
        rebuilding = self._needs_rebuild(now_ns)
        limit = self._fetch_limit(now_ns, midnight_ns, rebuilding)
        self._last_request_ns = now_ns
        try:
            result = await transport.fetch_station_observations(self._icao, limit=limit)
        except RateLimitedError as exc:
            self.counters["rate_limited"] += 1
            logger.warning(
                "%s: rate limited (%s); next attempt is the next timer fire", self._icao, exc
            )
            return
        except TransportError as exc:
            self.counters["transport_error"] += 1
            logger.warning(
                "%s: transport error (%s); next attempt is the next timer fire", self._icao, exc
            )
            return

        rows = self._parse(result)
        if rebuilding and not self._accept_rebuild(rows, limit, midnight_ns):
            return
        self._last_success_ns = result.retrieved_at_ns
        self._publish_new(rows, midnight_ns)
        self.counters["poll_ok"] += 1

    def _parse(self, result: FetchResult) -> list[StationObservation]:
        if result.text is None:  # pragma: no cover - `allow_not_modified=False` forbids a 304
            raise ValueError("observation fetch returned no body")
        observations, drops = nws_observation_rows_to_station_observations(
            station=self._icao,
            payload=json.loads(result.text),
            source_channel=self._config.source_channel,
            assumed_publication_lag_ns=int(self._config.assumed_publication_lag_ns),
            received_at_ns=result.retrieved_at_ns,
        )
        self.counters.update(drops)
        return sorted(observations, key=lambda record: record.observed_at_ns)

    def _accept_rebuild(
        self, rows: list[StationObservation], limit: int, midnight_ns: int
    ) -> bool:
        trusted = rebuild_is_trusted(
            sorted_observed_ns=[record.observed_at_ns for record in rows],
            midnight_ns=midnight_ns,
            staleness_bound_ns=self._staleness_bound_ns,
        )
        if trusted:
            self._rebuild_trusted = True
            self._escalate_to_ceiling = False
            return True
        self.counters["rebuild_untrusted"] += 1
        reached_midnight = bool(rows) and rows[0].observed_at_ns <= midnight_ns
        if not reached_midnight and limit < MAX_OBSERVATION_LIMIT:
            self._escalate_to_ceiling = True
        logger.critical(
            "%s: rebuild untrusted (limit=%d, rows=%d, reached_midnight=%s); nothing "
            "published, the station stays observation_unavailable until a trusted rebuild",
            self._icao,
            limit,
            len(rows),
            reached_midnight,
        )
        return False

    def _roll_day(self, midnight_ns: int) -> None:
        if self._published_midnight_ns != midnight_ns:
            self._published = {}
            self._published_midnight_ns = midnight_ns

    def _publish_new(self, rows: list[StationObservation], midnight_ns: int) -> None:
        """Publish, ascending, every current-climate-day row not already published.

        Ascending order matters: the strategy-side accumulator resets on a
        day change, so the first in-day row must arrive before any later
        one. Rows before midnight belong to a day the accumulator will never
        hold and are used only as coverage evidence. A changed reading at an
        already-published instant IS re-published -- a correction, which the
        accumulator applies by replacement.
        """
        data_type = station_observation_data_type()
        for record in rows:
            if record.observed_at_ns < midnight_ns:
                continue
            if self._published.get(record.observed_at_ns) == record.temp_c_tenths:
                continue
            self.publish_data(data_type, record)
            self._published[record.observed_at_ns] = record.temp_c_tenths
            self.published_count += 1
