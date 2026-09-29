"""SL-11: the live NBM NBP quantile ingest Actor.

Mirrors `nbm_forecast_actor.py` (WP-12 Seam B, the NBS deterministic sibling)
in every structural choice -- a NATIVE Nautilus timer, per-cycle latching, a
measured (never assumed) vintage, an injectable `transport_factory`, and
publication on the ONE shared `ForecastPoint` `DataType` topic -- adapted to
the NBP probabilistic percentile product (`docs/plans/
FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md` §3.2 item 1, §7 SL-11).

Native, therefore used rather than rebuilt (verified in the installed
``nautilus-trader==1.231.0``), identically to the NBS sibling:

* timer scheduling -- ``Clock.set_timer(name, interval, start_time=...,
  callback=...)`` (``common/component.pyx:419``);
* publication -- ``Actor.publish_data(DataType, Data)``
  (``common/actor.pyx:2813``);
* lifecycle -- ``Actor._start -> on_start`` and registration through
  ``Trader.add_actor``.

A TIMER, not a polling loop, per-CYCLE not per-tick, for the same reasons the
NBS actor's own module docstring gives.

**Three cycles, not four.** NBP is issued at 13Z, 19Z and 01Z (never NBS's
00/06/12/18Z set): ``DEFAULT_NBM_QUANTILE_CYCLE_HOURS``.

**The publication-lag floor is 60 minutes**
(``MINIMUM_PUBLICATION_LAG_NS["NBM_NBP"]``, the SL-3 lag census minimum
rounded down to 5 min -- ``forecast_point.py``). The first fetch attempt for
a cycle is therefore due at ``cycle + 60 min``; the NATIVE timer's own
periodic re-fire is what supplies the retry -- a cycle that is not yet
`_fetched_cycles` is attempted again on the next tick, exactly as the NBS
actor already does. The vintage itself is always the MEASURED
``Last-Modified`` lag, never the floor (L-17): a lag below the floor
publishes nothing rather than clamping a vintage, identically to the NBS
actor's own ``_measured_lag_ns``.

**D+1 only.** ``parse_nbp_bulletin`` returns every MAX-column lead a cycle
offers (nine, for a 13Z capture) -- this family trades D+1 exclusively (plan
§2.4, R2-16: "lead axis unnecessary ... SL-10 DROPPED"), and NBP's own grid
already sorts the columns lead-ascending, so the NEAREST valid window per
(station, variable) *is* D+1 in each station's own LST (verified by
``test_nbm_quantile_parse.py::test_first_max_column_targets_dplus1_in_lst_every_cycle``).
This Actor keeps raw ingest lean and the shared topic free of a lead fan-out
no consumer reads: exactly ``len(TXN_VARIABLE_BY_ROW_LABEL) *
len(station_icaos)`` `ForecastPoint` rows per cycle, never nine times that.

**A stale-cycle alert.** Unlike the NBS sibling (whose own timer cadence
against 6-hourly cycles makes "still trying" the only failure mode worth
counting), NBP feeds a live family with a decisive permit window (plan §3.3),
so a cycle that never arrives needs to be LOUD, not merely counted. When an
expected cycle is not ingested by ``cycle + stale_deadline_seconds``, every
subsequent poll logs a single ``ERROR`` line carrying the stable
``STALE_CYCLE_ALERT_MARKER`` -- a plain, greppable constant the deployed
alert pipeline (``deploy/systemd``) can match on, deliberately not routed
through ``breezy.runtime.health`` (this module is ``ingest`` and must never
import ``strategy``/``runtime``; ``nws_actor.py``'s own use of that module is
an explicitly waived, inspected exception -- ``pyproject.toml``'s
``breezy.ingest.nws_actor -> breezy.runtime.health`` row -- not a precedent
to extend). ``DEFAULT_NBM_QUANTILE_STALE_DEADLINE_SECONDS`` is a conservative
margin over the floor, not a measured census value: no arrival-variance
census exists yet for NBP specifically (the SL-15 nightly freshness
heartbeat is the future home for a measured one).

L-16: the timer callback runs on a Rust ``_DummyThread`` where a
``LiveClock`` SWALLOWS anything raised, so ``on_cycle_timer`` does exactly
two things -- submit and return -- and supervision is the returned handle's
done-callback, identically to the NBS actor.
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

from breezy.domain.forecast_point import MINIMUM_PUBLICATION_LAG_NS, ForecastPoint
from breezy.ingest.http import RateLimitedError, TransportError
from breezy.ingest.nbm_forecast_data_type import nbm_forecast_point_data_type
from breezy.ingest.nbm_quantile_parse import (
    NBM_NBP_MODEL,
    NbpBulletinDriftError,
    NbpQuantilePoint,
    parse_nbp_bulletin,
)
from breezy.ingest.nbm_quantile_transport import (
    NbmQuantileFetchResult,
    build_nbm_quantile_transport,
)

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_NBM_QUANTILE_CYCLE_HOURS",
    "DEFAULT_NBM_QUANTILE_STALE_DEADLINE_SECONDS",
    "DEFAULT_NBM_QUANTILE_TIMER_INTERVAL_SECONDS",
    "STALE_CYCLE_ALERT_MARKER",
    "BulletinFetcher",
    "NbmQuantileActor",
    "NbmQuantileActorConfig",
    "TransportFactory",
    "build_nbm_quantile_transport",
]

_NS_PER_SECOND: Final[int] = 1_000_000_000
_SECONDS_PER_HOUR: Final[int] = 3_600
_ICAO_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A[A-Z]{4}\Z")

#: NBP's own issuance schedule (v5.0 text-card): 13Z, 19Z, 01Z. Sorted
#: ascending, matching the NBS actor's own `tuple(sorted(...))` convention.
DEFAULT_NBM_QUANTILE_CYCLE_HOURS: Final[tuple[int, ...]] = (1, 13, 19)

#: Same cadence as the NBS sibling: often enough that a cycle is picked up
#: within a quarter hour of its publication window closing.
DEFAULT_NBM_QUANTILE_TIMER_INTERVAL_SECONDS: Final[int] = 900

#: The 60-minute publication floor, restated in seconds for the deadline
#: bound-check below (module docstring: not a knob, a sanity floor).
_NBP_FLOOR_SECONDS: Final[int] = MINIMUM_PUBLICATION_LAG_NS[NBM_NBP_MODEL] // _NS_PER_SECOND

#: Conservative placeholder margin, NOT a measured census value (module
#: docstring). Three hours past the cycle -- two past the floor -- comfortably
#: precedes the next cycle's own floor (the shortest inter-cycle gap is 6 h,
#: 13Z->19Z / 19Z->01Z), so a stale 13Z cycle alerts well before it could be
#: confused with 19Z's own fresh attempt.
DEFAULT_NBM_QUANTILE_STALE_DEADLINE_SECONDS: Final[int] = 3 * _SECONDS_PER_HOUR

#: Stable, greppable marker for the deployed alert pipeline. Never
#: interpolated with per-cycle detail INSIDE the marker itself -- the marker
#: is what a matcher greps for; the detail is the rest of the log line.
STALE_CYCLE_ALERT_MARKER: Final[str] = "NBM_NBP_STALE_CYCLE"


class BulletinFetcher(Protocol):
    """The one transport method the Actor calls."""

    async def fetch_nbp_bulletin(
        self, *, cycle_date: dt.date, cycle_hour: int
    ) -> NbmQuantileFetchResult: ...


#: Builds the transport ON THE ACTOR'S CLOCK -- called from `on_start` with
#: `self.clock.timestamp_ns`, so a transport on any other clock cannot be
#: wired in by construction (one clock). Mirrors the NBS actor's own
#: `TransportFactory` shape exactly, which is why `NbmQuantileTransport`'s own
#: `build_nbm_quantile_transport` (SL-3) already satisfies it unmodified --
#: reused directly below rather than wrapped a second time (DRY).
TransportFactory = Callable[[Callable[[], int]], BulletinFetcher]


class NbmQuantileActorConfig(ActorConfig, frozen=True):
    """Configuration for one quantile Actor serving a set of stations.

    Scalar, msgspec-serialisable fields only -- see `NbmForecastActorConfig`.
    """

    station_icaos: tuple[str, ...]
    cycle_hours: tuple[int, ...] = DEFAULT_NBM_QUANTILE_CYCLE_HOURS
    timer_interval_seconds: int = DEFAULT_NBM_QUANTILE_TIMER_INTERVAL_SECONDS
    stagger_offset_seconds: int = 0
    stale_deadline_seconds: int = DEFAULT_NBM_QUANTILE_STALE_DEADLINE_SECONDS

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
        if self.stale_deadline_seconds <= _NBP_FLOOR_SECONDS:
            raise ValueError(
                f"`stale_deadline_seconds` ({self.stale_deadline_seconds}) must exceed "
                f"the {NBM_NBP_MODEL} publication floor of {_NBP_FLOOR_SECONDS} s; "
                f"otherwise every cycle would alert before it could possibly have "
                f"arrived"
            )


def _nearest_per_station_variable(
    points: tuple[NbpQuantilePoint, ...],
) -> list[NbpQuantilePoint]:
    """Keep only the nearest (D+1) window per (station, variable). See module docstring."""
    nearest: dict[tuple[str, str], NbpQuantilePoint] = {}
    for point in points:
        key = (point.station, point.variable)
        current = nearest.get(key)
        if current is None or point.valid_start_ns < current.valid_start_ns:
            nearest[key] = point
    return list(nearest.values())


def _to_forecast_point(
    point: NbpQuantilePoint, *, lag_ns: int, ingested_at_ns: int
) -> ForecastPoint:
    return ForecastPoint(
        station=point.station,
        model=NBM_NBP_MODEL,
        model_version=point.model_version,
        variable=point.variable,
        cycle_runtime_ns=point.cycle_runtime_ns,
        valid_start_ns=point.valid_start_ns,
        valid_end_ns=point.valid_end_ns,
        value_f=point.value_f,
        issuance_seq=0,
        measured_publication_lag_ns=lag_ns,
        available_at_ns=point.cycle_runtime_ns + lag_ns,
        ingested_at_ns=ingested_at_ns,
        absence_reason=point.absence_reason,
    )


class NbmQuantileActor(Actor):
    """Fetches one NBP cycle per cycle and publishes D+1 raw records. See module docstring."""

    def __init__(
        self,
        config: NbmQuantileActorConfig,
        *,
        transport_factory: TransportFactory = build_nbm_quantile_transport,
    ) -> None:
        super().__init__(config)
        self._config = config
        self._stations = frozenset(config.station_icaos)
        self._cycle_hours = tuple(sorted(set(config.cycle_hours)))
        self._transport_factory = transport_factory
        self._transport: BulletinFetcher | None = None
        self._floor_ns = MINIMUM_PUBLICATION_LAG_NS[NBM_NBP_MODEL]
        self._stale_deadline_ns = int(config.stale_deadline_seconds) * _NS_PER_SECOND

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
            logger.info("no running event loop: no NBM quantile polling armed")
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
        return "nbm-quantile-cycle"

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
            logger.critical("NBM quantile task died after loop close: %r", exc)
            self._settle()
            return
        loop.call_soon_threadsafe(self._record_task_death, exc)

    def _record_task_death(self, exc: BaseException) -> None:
        logger.critical("NBM quantile cycle task died: %r", exc, exc_info=exc)
        self.counters["task_death"] += 1
        self._settle()

    # -- one cycle ----------------------------------------------------------

    def latest_available_cycle_ns(self, now_ns: int) -> int | None:
        """The newest configured cycle whose minimum publication window has closed.

        Uses the model's `MINIMUM_PUBLICATION_LAG_NS` floor only as a
        SCHEDULING bound -- "do not ask before it could possibly exist". The
        lag that reaches a record is always the MEASURED one. Identical
        algorithm to the NBS sibling's own method, generic over cycle hours.
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
        now_ns = self.clock.timestamp_ns()
        cycle_ns = self.latest_available_cycle_ns(now_ns)
        if cycle_ns is None:  # pragma: no cover - defensive
            self.counters["no_cycle_available"] += 1
            return
        self._check_stale_cycle(cycle_ns, now_ns)
        if cycle_ns in self._fetched_cycles:
            self.counters["cycle_already_fetched"] += 1
            return
        self._poll_in_flight = True
        try:
            await self._fetch_cycle(transport, cycle_ns)
        finally:
            self._poll_in_flight = False

    def _check_stale_cycle(self, cycle_ns: int, now_ns: int) -> None:
        """Loud, stable-marker `ERROR` once a cycle outlives its deadline.

        Fires on EVERY poll past the deadline while the cycle stays
        un-ingested (never a single-shot latch): a monitor that samples logs
        on its own cadence must not be able to land in the one gap between a
        single alert and the eventual fetch.
        """
        if cycle_ns in self._fetched_cycles:
            return
        deadline_ns = cycle_ns + self._stale_deadline_ns
        if now_ns < deadline_ns:
            return
        self.counters["stale_cycle_alert"] += 1
        instant = dt.datetime.fromtimestamp(cycle_ns / _NS_PER_SECOND, tz=dt.UTC)
        logger.error(
            "%s: %s cycle %s %02dZ not ingested by its %d s deadline "
            "(now=%d ns); still retrying on the next timer fire",
            STALE_CYCLE_ALERT_MARKER,
            NBM_NBP_MODEL,
            instant.date().isoformat(),
            instant.hour,
            self._config.stale_deadline_seconds,
            now_ns,
        )

    async def _fetch_cycle(self, transport: BulletinFetcher, cycle_ns: int) -> None:
        instant = dt.datetime.fromtimestamp(cycle_ns / _NS_PER_SECOND, tz=dt.UTC)
        try:
            result = await transport.fetch_nbp_bulletin(
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

    def _measured_lag_ns(self, result: NbmQuantileFetchResult, cycle_ns: int) -> int | None:
        """The MEASURED publication lag, or `None` when it cannot be trusted.

        Both refusals are loud and publish nothing: a vintage that is assumed
        or clamped up to the floor would be look-ahead stored as evidence.
        """
        raw = result.last_modified
        if not raw:
            self.counters["missing_last_modified"] += 1
            logger.critical(
                "NBP bulletin carried no Last-Modified header; the publication lag "
                "cannot be measured, so nothing is published for this cycle"
            )
            return None
        try:
            published = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            self.counters["unparsable_last_modified"] += 1
            logger.critical("NBP bulletin Last-Modified %r did not parse", raw)
            return None
        lag_ns = int(published.timestamp()) * _NS_PER_SECOND - cycle_ns
        if lag_ns < self._floor_ns:
            self.counters["publication_lag_below_floor"] += 1
            logger.critical(
                "measured publication lag %d ns is below the %s floor of %d ns; "
                "nothing is published for this cycle rather than clamping a vintage",
                lag_ns,
                NBM_NBP_MODEL,
                self._floor_ns,
            )
            return None
        return lag_ns

    def _publish(self, result: NbmQuantileFetchResult, lag_ns: int) -> None:
        try:
            points, drops = parse_nbp_bulletin(result.text, stations=self._stations)
        except NbpBulletinDriftError:
            # Counted here AND re-raised: the count keeps the failure visible
            # on the Actor, and the raise reaches the supervisor so a layout
            # change cannot be a quiet no-op poll.
            self.counters["bulletin_drift"] += 1
            raise
        self.counters.update(drops)
        data_type = nbm_forecast_point_data_type()
        for point in _nearest_per_station_variable(points):
            forecast_point = _to_forecast_point(
                point, lag_ns=lag_ns, ingested_at_ns=result.fetched_at_ns
            )
            self.publish_data(data_type, forecast_point)
            self.published_count += 1
