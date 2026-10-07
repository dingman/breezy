"""F13-C1 S4: the US-source collector -- one oneshot invocation per source x cycle.

Sources: ``lamp`` (hourly HH30 ``lavtxt`` + ``lavtxt_ext`` from NOMADS), ``pfm`` (AFOS, the
latest forecast per closed WFO) and ``nbp`` (availability only; C1 never writes NBP rows).

Per cycle the driver, under the source's unit lock:

1. refuses a firing that STARTS inside [16:30Z, 17:10Z) (the 17:10Z firing reruns it, rows
   flagged ``late``), then the disk guard and the clock-offset bound;
2. polls, never starting an attempt whose worst case could meet the launch window;
3. on the first poll that sees a payload digest, records the availability interval in the
   append-only poll ledger BEFORE any raw write (so a kill cannot lose the first-seen stamp),
   then persists the raw payload through the revision store (``<base>-r<N>``) and the
   normalised rows through ``<base>-norm-r<N>``;
4. alerts once per repeat window when a source has gone stale.

Every step is idempotent: a rerun adds no raw entry, no manifest entry and no second ``seen``
event for a digest already recorded, and it repairs a normalised file a kill left behind.

This script imports NOTHING from ``breezy.runtime`` (M6 enforces it): ``alerts.env`` is read as
a file by ``us_source_guards``. ``--clearenv`` strips the environment, so the User-Agent is
always passed explicitly.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import enum
import fcntl
import functools
import hashlib
import os
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

_COLLECT_DIR = Path(__file__).resolve().parent
for _directory in (_COLLECT_DIR, _COLLECT_DIR.parent / "venue"):  # pragma: no cover - bootstrap
    if str(_directory) not in sys.path:
        sys.path.insert(0, str(_directory))

import us_source_alert as alert_mod
import us_source_guards as guards
import us_source_lag_legs as legs
import us_source_ledger as ledger_mod
import us_source_norm as norm
import us_source_obs_transport as obs_transport
from iem_mos_probe_transport import (  # type: ignore[import-not-found]
    IEM_AFOS_LAV_MIN_INTERVAL_NS,
    IEM_AFOS_PFM_MAX_BODY_BYTES,
    IemMosProbeTransport,
    IemPacer,
    PacedIemTransport,
)

from breezy.ingest.http import TransportError
from breezy.ingest.lamp_parse import LampBlock, parse_lamp_blocks
from breezy.ingest.mdl_lamp_transport import (
    LAMP_DEFAULT_USER_AGENT,
    LampNotPublishedError,
    MdlLampTransport,
)
from breezy.ingest.nbm_quantile_transport import (
    DEFAULT_NBM_QUANTILE_STATIONS,
    NOMADS_QUANTILE_HOST,
    S3_QUANTILE_HOST,
    BothHostsFailedError,
    NbmQuantileTransport,
)
from breezy.ingest.pfm_parse import PfmParseError, PfmPoint, parse_pfm_product
from breezy.ingest.probe_transport import RequestBudget
from breezy.ingest.us_source_availability import (
    LagPrereg,
    LagSample,
    Observation,
    available_at,
)
from breezy.persistence.us_source_request import (
    LAMP_ALL_STATION,
    LAMP_EXT_STATION,
    PFM_POINTS,
    US_LAMP_LIVE_SOURCE,
    US_PFM_AFOS_SOURCE,
    US_SOURCE_PRODUCTS,
    revision_request,
)
from breezy.persistence.us_source_revision_store import (
    AppendOutcome,
    RevisionStoreBusyError,
    RevisionStoreError,
    UsSourceRevisionStore,
)

__all__ = [
    "COLLECTOR_USER_AGENT",
    "NBP_STATIONS",
    "SOURCE_KEYS",
    "CycleContext",
    "CycleReport",
    "CycleStatus",
    "FetchedPayload",
    "NotPublishedError",
    "default_lamp_fetcher",
    "default_lav_fetcher",
    "default_mos_fetcher",
    "default_nbp_fetcher",
    "default_obs_fetcher",
    "default_pfm_fetcher",
    "lag_samples",
    "main",
    "run_cycle",
]

_NS: Final[int] = 1_000_000_000
_MINUTE_NS: Final[int] = 60 * _NS
_HOUR_NS: Final[int] = 3600 * _NS
_GIB: Final[int] = 2**30

#: A project alias, never an operator mailbox (LOW).
COLLECTOR_USER_AGENT: Final[str] = LAMP_DEFAULT_USER_AGENT

#: CLI source name -> archive source key (the directory under the archive root).
NBP_SOURCE_KEY: Final[str] = "us-nbp-avail"
SOURCE_KEYS: Final[dict[str, str]] = {
    "lamp": US_LAMP_LIVE_SOURCE,
    "pfm": US_PFM_AFOS_SOURCE,
    "nbp": NBP_SOURCE_KEY,
    "lav": legs.IEM_LEGS["lav"].source_key,
    "mos": legs.IEM_LEGS["mos"].source_key,
    "obs": legs.OBS_SOURCE_KEY,
}
NBP_AVAILABILITY_SOURCE: Final[str] = "NBM_NBP"
#: R29: the stations argument is KNYC-inclusive; the transport's module default is untouched.
NBP_STATIONS: Final[frozenset[str]] = frozenset({*DEFAULT_NBM_QUANTILE_STATIONS, "KNYC"})
NBP_CYCLE_HOURS: Final[tuple[int, ...]] = (1, 7, 13, 19)

LAMP_ALL: Final[str] = LAMP_ALL_STATION
LAMP_EXT: Final[str] = LAMP_EXT_STATION
_AVAILABILITY_VERSION: Final[str] = "v1"

#: A poll after this long past the run is ``late`` (right-censored; excluded from lag freeze).
LATE_AFTER_NS: Final[dict[str, int]] = {
    "lamp": 20 * _MINUTE_NS,
    "pfm": 3 * _HOUR_NS,
    "nbp": 3 * _HOUR_NS,
    "lav": legs.IEM_LEGS["lav"].late_after_ns,
    "mos": legs.IEM_LEGS["mos"].late_after_ns,
    "obs": legs.OBS_LATE_AFTER_NS,
}
#: A displaced rerun still polls for this long (it starts past the nominal window).
_LATE_MAX_POLL_NS: Final[int] = 10 * _MINUTE_NS
_STALE_ALERT_REPEAT_NS: Final[int] = 6 * _HOUR_NS
_LAMP_RUN_MINUTE_NS: Final[int] = 30 * _MINUTE_NS
_PFM_REQUEST_BUDGET: Final[int] = 20
_DEFAULT_NTP_BOUND_MS: Final[int] = 1000  # provisional; frozen in the prereg after B0/A0
_DEFAULT_MIN_FREE_GIB: Final[int] = 10
_EXIT_REFUSED: Final[int] = 2
_EXIT_ERROR: Final[int] = 1

#: Sanity floors, never lag estimates (R29). The collector always observes, so the
#: ``nominal_plus_conservative_lag`` fallback is never taken; the table only satisfies
#: ``LagPrereg``'s own consistency checks.
COLLECTOR_PREREG: Final[LagPrereg] = LagPrereg(
    sanity_floors_ns={US_LAMP_LIVE_SOURCE: 5 * _MINUTE_NS, US_PFM_AFOS_SOURCE: 0},
    conservative_lags_ns={
        US_LAMP_LIVE_SOURCE: 60 * _MINUTE_NS,
        US_PFM_AFOS_SOURCE: 0,
        NBP_AVAILABILITY_SOURCE: 2 * _HOUR_NS,
    },
)


NotPublishedError = legs.NotPublishedError
FetchedPayload = legs.FetchedPayload


class CycleStatus(enum.StrEnum):
    COLLECTED = "collected"
    UNCHANGED = "unchanged"
    NOT_PUBLISHED = "not_published"
    REFUSED = "refused"
    DEADLINE = "deadline"
    SKIPPED_WINDOW = "skipped_window"
    SKIPPED_LOCKED = "skipped_locked"
    REFUSED_GUARD = "refused_guard"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class CycleReport:
    source: str
    status: CycleStatus
    refused: int = 0
    notes: tuple[str, ...] = ()

    @property
    def exit_code(self) -> int:
        if self.status is CycleStatus.REFUSED_GUARD:
            return _EXIT_REFUSED
        if self.status in {CycleStatus.ERROR, CycleStatus.REFUSED}:
            return _EXIT_ERROR
        return 0


def _unused_fetcher(*_args: object) -> FetchedPayload:
    raise RuntimeError("this fetcher is not used by the selected source")


@dataclass(frozen=True)
class CycleContext:
    root: Path
    clock: Callable[[], int]
    sleep: Callable[[float], None]
    fetch_lamp: Callable[[int, bool], FetchedPayload]
    fetch_pfm: Callable[[str], FetchedPayload]
    fetch_nbp: Callable[[dt.date, int], FetchedPayload]
    measure_ntp_offset: Callable[[], int | None]
    free_bytes: Callable[[Path], int]
    alert: Callable[[str, str, str], bool]
    poll_interval_s: float = 60.0
    nbp_poll_interval_s: float = 300.0
    ntp_bound_ns: int = _DEFAULT_NTP_BOUND_MS * 1_000_000
    min_free_bytes: int = _DEFAULT_MIN_FREE_GIB * _GIB
    fetch_lav: Callable[[str, int], FetchedPayload] = _unused_fetcher
    fetch_mos: Callable[[str, int], FetchedPayload] = _unused_fetcher
    fetch_obs: Callable[[str], FetchedPayload] = _unused_fetcher


class _StoreClock:
    """The ``timestamp_ns()`` protocol the archive classes want, over the injected clock."""

    def __init__(self, clock: Callable[[], int]) -> None:
        self._clock = clock

    def timestamp_ns(self) -> int:
        return self._clock()


@dataclass(frozen=True, slots=True)
class _Job:
    """One unit of polled work: a LAMP product (``ALL`` / ``ALLEXT``)."""

    station: str
    extended: bool


@dataclass(slots=True)
class _Result:
    status: CycleStatus
    refused: int = 0


# -- payload checks (everything runs BEFORE any write) ------------------------------------


def _decode(body: bytes) -> str:
    if not body.strip():
        raise ValueError("empty payload")
    return body.decode("utf-8")


@functools.lru_cache(maxsize=4)
def _parse_lamp(body: bytes) -> tuple[LampBlock, ...]:
    """All-or-nothing; the closed-station blocks of one HH30 run."""
    blocks = parse_lamp_blocks(_decode(body).splitlines())
    if not blocks:
        raise ValueError("no closed-set station block in the bulletin")
    return blocks


def _parse_pfm(body: bytes, station: str, now_ns: int) -> PfmPoint:
    reference = dt.datetime.fromtimestamp(now_ns / _NS, tz=dt.UTC)
    return parse_pfm_product(
        _decode(body).encode("utf-8"), station=station, reference_time=reference
    )


# -- locking ------------------------------------------------------------------------------


@contextlib.contextmanager
def _cycle_lock(store: UsSourceRevisionStore, root: Path, source_key: str) -> Iterator[None]:
    """The source's unit lock; an availability-only source gets the same flock shape."""
    if source_key in US_SOURCE_PRODUCTS:
        with store.unit_lock(source_key):
            yield
        return
    path = store.lock_path(source_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RevisionStoreBusyError(f"another run holds {path}") from exc
        yield
    finally:
        os.close(fd)


# -- ingest of one fetched payload ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Target:
    """Where one payload lives: its source, key shape and parsed form."""

    cli_source: str
    source_key: str
    station: str
    run_ts_ns: int
    model: str | None
    wmo_header_ns: int | None = None
    availability_source: str | None = None


class _Collector:
    def __init__(self, ctx: CycleContext, cli_source: str) -> None:
        self.ctx = ctx
        self.cli_source = cli_source
        self.source_key = SOURCE_KEYS[cli_source]
        clock = _StoreClock(ctx.clock)
        self.store = UsSourceRevisionStore(ctx.root, clock)
        self.writer = norm.NormWriter(ctx.root, clock)
        self.ledger = ledger_mod.PollLedger(ctx.root)
        self.ntp_offset: int | None = None

    # -- availability and the ledger --------------------------------------------------

    def seen_event(self, target: _Target, payload: FetchedPayload, sha: str) -> dict[str, Any]:
        earlier = [
            e
            for e in self.ledger.seen_events(self.source_key)
            if e.get("station") == target.station and e.get("run_ts_ns") == target.run_ts_ns
        ]
        last_miss = (
            None
            if earlier
            else self.ledger.last_miss_ns(self.source_key, target.station, target.run_ts_ns)
        )
        result = available_at(
            target.availability_source or target.source_key,
            _AVAILABILITY_VERSION,
            target.run_ts_ns,
            Observation(
                first_seen_ns=payload.fetched_at_ns,
                last_miss_ns=last_miss,
                last_modified=payload.last_modified,
                wmo_header_ns=target.wmo_header_ns,
                host_tag=payload.host_tag,
            ),
            prereg=COLLECTOR_PREREG,
        )
        ts, basis, miss_ts, clamped = result
        return {
            "kind": "seen",
            "station": target.station,
            "run_ts_ns": target.run_ts_ns,
            "sha256": sha,
            "fetched_at_ns": payload.fetched_at_ns,
            "first_seen_ns": payload.fetched_at_ns,
            "last_modified": payload.last_modified,
            "host_tag": payload.host_tag,
            "wmo_header_ns": target.wmo_header_ns,
            "available_ts_ns": ts,
            "basis": basis,
            "miss_ts_ns": miss_ts,
            "clamped_to_miss": clamped,
            "late": payload.fetched_at_ns > target.run_ts_ns + LATE_AFTER_NS[target.cli_source],
            "ntp_offset_ns": self.ntp_offset,
        }

    def record_miss(self, station: str, run_ts_ns: int, now_ns: int) -> None:
        self.ledger.record(
            self.source_key,
            {
                "kind": "miss",
                "station": station,
                "run_ts_ns": run_ts_ns,
                "fetched_at_ns": now_ns,
                "ntp_offset_ns": self.ntp_offset,
            },
        )

    def record_refused(self, station: str, run_ts_ns: int | None, sha: str, why: str) -> None:
        self.ledger.record(
            self.source_key,
            {
                "kind": "refused",
                "station": station,
                "run_ts_ns": run_ts_ns,
                "sha256": sha,
                "reason": why,
                "fetched_at_ns": self.ctx.clock(),
            },
        )

    # -- persistence ------------------------------------------------------------------

    def ingest(
        self,
        target: _Target,
        payload: FetchedPayload,
        build_rows: Callable[[dict[str, Any]], bytes] | None,
    ) -> _Result:
        """Ledger the first-seen interval, then the raw revision, then the normalised rows."""
        sha = hashlib.sha256(payload.body).hexdigest()
        seen = self.ledger.find_seen(self.source_key, target.station, target.run_ts_ns, sha)
        if seen is None:
            seen = self.seen_event(target, payload, sha)
            self.ledger.record(self.source_key, seen)
        try:
            outcome = self.store.append_if_new(
                source=target.source_key,
                station=target.station,
                run_ts_ns=target.run_ts_ns,
                model=target.model,
                payload=payload.body,
            )
        except RevisionStoreBusyError:
            raise
        except (RevisionStoreError, OSError) as exc:
            return self._store_refused(target, sha, type(exc).__name__)
        if outcome.outcome is AppendOutcome.QUARANTINED:
            return self._store_refused(target, sha, "quarantined")
        base = US_SOURCE_PRODUCTS[target.source_key]
        stored = dict(
            self.store.revisions(target.source_key, target.station, target.run_ts_ns, base)
        )
        number = next((n for n, digest in stored.items() if digest == sha), None)
        if number is None:
            return self._store_refused(target, sha, "digest_missing_after_append")
        if build_rows is not None:
            raw = revision_request(
                target.source_key, target.station, target.run_ts_ns, number, model=target.model
            )
            norm.write_normalised(self.writer, raw, build_rows(seen))
        appended = outcome.outcome is AppendOutcome.APPENDED
        return _Result(CycleStatus.COLLECTED if appended else CycleStatus.UNCHANGED)

    def _store_refused(self, target: _Target, sha: str, reason: str) -> _Result:
        """The store said no AFTER the seen row: record it, alert, and fail the cycle."""
        self.record_refused(target.station, target.run_ts_ns, sha, reason)
        self.ctx.alert("payload_refused", self.source_key, f"{target.station}: store {reason}")
        return _Result(CycleStatus.ERROR, refused=1)

    def repair_normalised(
        self,
        station: str,
        run_ts_ns: int,
        model: str | None,
        builder: Callable[[bytes, dict[str, Any]], bytes],
    ) -> None:
        """A kill between the raw write and the normalised write leaves the latter missing."""
        base = US_SOURCE_PRODUCTS[self.source_key]
        for number, sha in self.store.revisions(self.source_key, station, run_ts_ns, base):
            raw = revision_request(self.source_key, station, run_ts_ns, number, model=model)
            seen = self.ledger.find_seen(self.source_key, station, run_ts_ns, sha)
            if seen is None or not self.writer.missing(raw):
                continue
            try:
                rows = builder(self.writer.read_raw(raw), seen)
            except (ValueError, PfmParseError):
                continue  # a payload kept raw-only (lenient product) has no normalised form
            norm.write_normalised(self.writer, raw, rows)

    # -- alerts ----------------------------------------------------------------------

    def refuse_payload(
        self, station: str, run_ts_ns: int | None, body: bytes, exc: Exception
    ) -> None:
        sha = hashlib.sha256(body).hexdigest()
        reason = getattr(exc, "reason", type(exc).__name__)
        self.record_refused(station, run_ts_ns, sha, str(reason))
        self.ctx.alert("payload_refused", self.source_key, f"{station}: {reason}")

    def check_stale(self, now_ns: int) -> None:
        last = self.ledger.last_seen_ns(self.source_key)
        if last is None or now_ns - last <= guards.STALE_AFTER_NS[self.cli_source]:
            return
        prior = self.ledger.last_alert_ns(self.source_key)
        if prior is not None and now_ns - prior < _STALE_ALERT_REPEAT_NS:
            return
        age_h = (now_ns - last) / _HOUR_NS
        delivered = self.ctx.alert(
            "stale_source", self.source_key, f"newest observed run is {age_h:.1f} h old"
        )
        if delivered:  # an undelivered alert is retried next cycle, never deduped away
            self.ledger.record(self.source_key, {"kind": "stale_alert", "fetched_at_ns": now_ns})


# -- the polling loop -----------------------------------------------------------------------


def _poll(
    ctx: CycleContext,
    cli_source: str,
    pending: list[_Job],
    *,
    deadline_ns: int,
    interval_s: float,
    step: Callable[[_Job], bool | None],
) -> tuple[list[_Job], CycleStatus | None]:
    """Run ``step`` over ``pending`` until each is done, the window ends or the deadline hits.

    ``step`` returns True when the job is finished, False when it must be polled again, and
    None after a transport error (polled again, remembered for the status).
    """
    start = ctx.clock()
    errored = False
    while pending:
        now = ctx.clock()
        over_budget = (
            guards.worked_seconds_outside_window(start, now) > guards.MAX_WORK_SECONDS[cli_source]
        )
        if over_budget or not guards.attempt_allowed(now):
            return pending, CycleStatus.DEADLINE
        if now > deadline_ns:
            return pending, CycleStatus.ERROR if errored else CycleStatus.NOT_PUBLISHED
        outcomes = [(job, step(job)) for job in pending]
        errored = errored or any(done is None for _, done in outcomes)
        pending = [job for job, done in outcomes if not done]
        if pending:
            ctx.sleep(interval_s)
    return [], None


def _merge(results: Sequence[CycleStatus]) -> CycleStatus:
    for status in (
        CycleStatus.ERROR,
        CycleStatus.COLLECTED,
        CycleStatus.DEADLINE,
        CycleStatus.NOT_PUBLISHED,
    ):
        if status in results:
            return status
    return CycleStatus.UNCHANGED


def _final_status(results: Sequence[CycleStatus], refused: int) -> CycleStatus:
    """Merged status; a cycle whose every outcome was a refusal is REFUSED, never UNCHANGED."""
    if refused and not results:
        return CycleStatus.REFUSED
    return _merge(results)


def _log(message: str) -> None:
    print(f"us-source-collector: {message}", file=sys.stderr)


# -- LAMP -----------------------------------------------------------------------------------


def lamp_target_run_ns(now_ns: int) -> int:
    """The latest HH:30 run that is at least a minute old at ``now_ns``."""
    probe = now_ns - _MINUTE_NS
    return (probe - _LAMP_RUN_MINUTE_NS) // _HOUR_NS * _HOUR_NS + _LAMP_RUN_MINUTE_NS


def _lamp_rows_builder(body: bytes, seen: dict[str, Any]) -> bytes:
    return norm.lamp_csv(_parse_lamp(body), seen)


def _lamp_cycle(col: _Collector, now_ns: int) -> CycleReport:
    ctx = col.ctx
    run_ts = lamp_target_run_ns(now_ns)
    base = US_SOURCE_PRODUCTS[col.source_key]
    results: list[CycleStatus] = []
    refused = 0
    pending: list[_Job] = []
    for job in (_Job(LAMP_ALL, False), _Job(LAMP_EXT, True)):
        if col.store.revisions(col.source_key, job.station, run_ts, base):
            if not job.extended:
                col.repair_normalised(job.station, run_ts, None, _lamp_rows_builder)
            results.append(CycleStatus.UNCHANGED)
        else:
            pending.append(job)

    def step(job: _Job) -> bool | None:
        nonlocal refused
        now = ctx.clock()
        try:
            payload = ctx.fetch_lamp(run_ts, job.extended)
        except NotPublishedError:
            col.record_miss(job.station, run_ts, now)
            return False
        except (TransportError, OSError) as exc:
            _log(f"{job.station} fetch failed: {type(exc).__name__}")
            return None
        target = _Target("lamp", col.source_key, job.station, run_ts, None)
        if not job.extended:  # the main bulletin is strict; the ext layout is unverified
            try:
                _parse_lamp(payload.body)
            except (ValueError, UnicodeDecodeError) as exc:
                col.refuse_payload(job.station, run_ts, payload.body, exc)
                refused += 1
                return True
            builder: Callable[[dict[str, Any]], bytes] | None = functools.partial(
                _lamp_rows_builder, payload.body
            )
        else:
            try:
                _decode(payload.body)
            except (ValueError, UnicodeDecodeError) as exc:
                col.refuse_payload(job.station, run_ts, payload.body, exc)
                refused += 1
                return True
            builder = _optional_lamp_rows(payload.body)
        outcome = col.ingest(target, payload, builder)
        results.append(outcome.status)
        refused += outcome.refused
        return True

    deadline = max(run_ts + LATE_AFTER_NS["lamp"], now_ns + _LATE_MAX_POLL_NS)
    unfinished, status = _poll(
        ctx,
        "lamp",
        pending,
        deadline_ns=deadline,
        interval_s=ctx.poll_interval_s,
        step=step,
    )
    if unfinished and status is not None:
        results.append(status)
    return CycleReport(col.source_key, _final_status(results, refused), refused)


def _optional_lamp_rows(body: bytes) -> Callable[[dict[str, Any]], bytes] | None:
    """Normalised rows for the ext bulletin only if it parses like the main one."""
    try:
        blocks = _parse_lamp(body)
    except (ValueError, UnicodeDecodeError):
        return None
    return functools.partial(norm.lamp_csv, blocks)


# -- PFM ------------------------------------------------------------------------------------


def _pfm_cycle(col: _Collector, _now_ns: int) -> CycleReport:
    ctx = col.ctx
    results: list[CycleStatus] = []
    refused = 0
    for station, point in PFM_POINTS.items():
        attempt = ctx.clock()
        if not guards.attempt_allowed(attempt):
            results.append(CycleStatus.DEADLINE)
            break
        try:
            payload = ctx.fetch_pfm(point.wfo)
        except NotPublishedError:
            results.append(CycleStatus.NOT_PUBLISHED)
            continue
        except (TransportError, OSError) as exc:
            _log(f"{point.wfo} fetch failed: {type(exc).__name__}")
            results.append(CycleStatus.ERROR)
            continue
        try:
            parsed = _parse_pfm(payload.body, station, payload.fetched_at_ns)
        except (PfmParseError, ValueError, UnicodeDecodeError) as exc:
            col.refuse_payload(station, None, payload.body, exc)
            refused += 1
            continue
        issued_ns = int(parsed.issued_at.timestamp()) * _NS
        target = _Target(
            "pfm", col.source_key, station, issued_ns, point.wfo, wmo_header_ns=issued_ns
        )
        outcome = col.ingest(target, payload, functools.partial(norm.pfm_csv, parsed))
        results.append(outcome.status)
        refused += outcome.refused
    return CycleReport(col.source_key, _final_status(results, refused), refused)


# -- NBP (availability only) ----------------------------------------------------------------


def nbp_target_cycle(now_ns: int) -> tuple[int, dt.date, int]:
    """The latest NBP cycle (01/07/13/19Z) at or before ``now_ns``: (ts, date, hour)."""
    day = dt.datetime.fromtimestamp(now_ns / _NS, tz=dt.UTC).date()
    candidates = [
        (
            int(dt.datetime(d.year, d.month, d.day, hour, tzinfo=dt.UTC).timestamp()) * _NS,
            d,
            hour,
        )
        for d in (day - dt.timedelta(days=1), day)
        for hour in NBP_CYCLE_HOURS
    ]
    return max(c for c in candidates if c[0] <= now_ns)


def _nbp_cycle(col: _Collector, now_ns: int) -> CycleReport:
    ctx = col.ctx
    run_ts, cycle_date, cycle_hour = nbp_target_cycle(now_ns)
    if col.ledger.find_seen(col.source_key, LAMP_ALL, run_ts) is not None:
        return CycleReport(col.source_key, CycleStatus.UNCHANGED)
    target = _Target(
        "nbp", col.source_key, LAMP_ALL, run_ts, None, availability_source=NBP_AVAILABILITY_SOURCE
    )

    def step(_job: _Job) -> bool | None:
        now = ctx.clock()
        try:
            payload = ctx.fetch_nbp(cycle_date, cycle_hour)
        except NotPublishedError:
            col.record_miss(LAMP_ALL, run_ts, now)
            return False
        except (TransportError, OSError) as exc:
            _log(f"nbp fetch failed: {type(exc).__name__}")
            return None
        sha = hashlib.sha256(payload.body).hexdigest()
        col.ledger.record(col.source_key, col.seen_event(target, payload, sha))
        return True  # polling stops for this cycle after its first success

    deadline = max(run_ts + LATE_AFTER_NS["nbp"], now_ns + _LATE_MAX_POLL_NS)
    unfinished, status = _poll(
        ctx,
        "nbp",
        [_Job(LAMP_ALL, False)],
        deadline_ns=deadline,
        interval_s=ctx.nbp_poll_interval_s,
        step=step,
    )
    if unfinished:
        return CycleReport(col.source_key, status or CycleStatus.NOT_PUBLISHED)
    return CycleReport(col.source_key, CycleStatus.COLLECTED)


# -- lav / mos / obs (availability only, C1-R1) ------------------------------------------------


def _leg_report(col: _Collector, out: legs.LegOutcome) -> CycleReport:
    if out.errors:
        status = CycleStatus.ERROR
    elif out.collected:
        status = CycleStatus.COLLECTED
    elif out.deadline:
        status = CycleStatus.DEADLINE
    elif out.misses:
        status = CycleStatus.NOT_PUBLISHED
    elif out.refused:
        status = CycleStatus.REFUSED
    else:
        status = CycleStatus.UNCHANGED
    return CycleReport(col.source_key, status, out.refused)


def _lav_cycle(col: _Collector, _now_ns: int) -> CycleReport:
    return _leg_report(col, legs.iem_cycle(col, legs.IEM_LEGS["lav"], col.ctx.fetch_lav))


def _mos_cycle(col: _Collector, _now_ns: int) -> CycleReport:
    return _leg_report(col, legs.iem_cycle(col, legs.IEM_LEGS["mos"], col.ctx.fetch_mos))


def _obs_cycle(col: _Collector, _now_ns: int) -> CycleReport:
    return _leg_report(col, legs.obs_cycle(col, col.ctx.fetch_obs))


# -- the driver -----------------------------------------------------------------------------


_CYCLES: Final[dict[str, Callable[[_Collector, int], CycleReport]]] = {
    "lamp": _lamp_cycle,
    "pfm": _pfm_cycle,
    "nbp": _nbp_cycle,
    "lav": _lav_cycle,
    "mos": _mos_cycle,
    "obs": _obs_cycle,
}


def run_cycle(source: str, ctx: CycleContext) -> CycleReport:
    """One collection cycle for ``source`` (``lamp`` / ``pfm`` / ``nbp``)."""
    if source not in SOURCE_KEYS:
        raise ValueError(f"unknown source {source!r}; choose from {sorted(SOURCE_KEYS)}")
    key = SOURCE_KEYS[source]
    now = ctx.clock()
    if guards.firing_decision(now) is guards.FiringDecision.SKIP_WINDOW:
        _log("firing inside the launch window; the 17:10Z firing reruns it (rows flagged late)")
        return CycleReport(key, CycleStatus.SKIPPED_WINDOW)
    try:
        guards.check_disk(ctx.root, min_free_bytes=ctx.min_free_bytes, free_bytes=ctx.free_bytes)
    except guards.DiskGuardRefusedError as exc:
        ctx.alert("disk_guard_refused", key, str(exc))
        return CycleReport(key, CycleStatus.REFUSED_GUARD, notes=(str(exc),))
    offset = ctx.measure_ntp_offset()
    try:
        guards.check_ntp_offset(offset, bound_ns=ctx.ntp_bound_ns)
    except guards.NtpOffsetExceededError as exc:
        ctx.alert("ntp_offset_excess", key, str(exc))
        return CycleReport(key, CycleStatus.REFUSED_GUARD, notes=(str(exc),))
    collector = _Collector(ctx, source)
    collector.ntp_offset = offset
    try:
        with _cycle_lock(collector.store, ctx.root, key):
            collector.check_stale(now)
            return _CYCLES[source](collector, now)
    except RevisionStoreBusyError:
        _log(f"{key} is locked by another run; skipping this cycle")
        return CycleReport(key, CycleStatus.SKIPPED_LOCKED)


def lag_samples(ledger: ledger_mod.PollLedger, source_key: str) -> list[LagSample]:
    """Observed lags (``available_ts - run_ts``) of every ``seen`` event, ``late`` flagged."""
    return [
        LagSample(source_key, int(e["available_ts_ns"]) - int(e["run_ts_ns"]), bool(e.get("late")))
        for e in ledger.seen_events(source_key)
        if e.get("station") != LAMP_EXT
    ]


# -- default transports (production wiring) ---------------------------------------------------


def default_lamp_fetcher(
    clock: Callable[[], int], *, check_proxy_env: bool = True
) -> Callable[[int, bool], FetchedPayload]:
    transport = MdlLampTransport(
        clock=clock, user_agent=COLLECTOR_USER_AGENT, check_proxy_env=check_proxy_env
    )

    def fetch(run_ts_ns: int, extended: bool) -> FetchedPayload:
        when = dt.datetime.fromtimestamp(run_ts_ns / _NS, tz=dt.UTC)
        try:
            result = asyncio.run(
                transport.fetch_lamp_bulletin(when.date(), when.hour, extended=extended)
            )
        except LampNotPublishedError as exc:
            raise NotPublishedError(str(exc)) from exc
        return FetchedPayload(
            result.body.encode("utf-8"), result.retrieved_at_ns, result.last_modified, "nomads"
        )

    return fetch


def default_pfm_fetcher(
    clock: Callable[[], int], *, check_proxy_env: bool = True
) -> Callable[[str], FetchedPayload]:
    transport = PacedIemTransport(
        budget=RequestBudget(limit=_PFM_REQUEST_BUDGET),
        pacer=IemPacer(clock=clock),
        user_agent=COLLECTOR_USER_AGENT,
        clock=clock,
        max_body_bytes=IEM_AFOS_PFM_MAX_BODY_BYTES,
        accept="text/plain",
        check_proxy_env=check_proxy_env,
    )

    def fetch(wfo: str) -> FetchedPayload:
        result = asyncio.run(transport.fetch_afos_pfm(wfo, limit=1))
        body = (result.text or "").encode("utf-8")
        if not body.strip():
            raise NotPublishedError(f"empty AFOS response for PFM{wfo}")
        return FetchedPayload(
            body, result.retrieved_at_ns, result.headers.get("last-modified"), "iem"
        )

    return fetch


def _both_hosts_404(exc: BothHostsFailedError) -> bool:
    return all("status 404" in str(err) for err in (exc.primary_error, exc.fallback_error))


def default_nbp_fetcher(
    clock: Callable[[], int], *, check_proxy_env: bool = True
) -> Callable[[dt.date, int], FetchedPayload]:
    transport = NbmQuantileTransport(
        clock=clock,
        stations=NBP_STATIONS,
        user_agent=COLLECTOR_USER_AGENT,
        check_proxy_env=check_proxy_env,
    )
    tags = {S3_QUANTILE_HOST: "s3", NOMADS_QUANTILE_HOST: "nomads"}

    def fetch(cycle_date: dt.date, cycle_hour: int) -> FetchedPayload:
        try:
            result = asyncio.run(
                transport.fetch_nbp_bulletin(cycle_date=cycle_date, cycle_hour=cycle_hour)
            )
        except BothHostsFailedError as exc:
            if _both_hosts_404(exc):
                raise NotPublishedError(str(exc)) from exc
            raise
        return FetchedPayload(
            result.text.encode("utf-8"),
            result.fetched_at_ns,
            result.last_modified,
            tags[result.source_host],
        )

    return fetch


_LAV_REQUEST_BUDGET: Final[int] = 60
_MOS_REQUEST_BUDGET: Final[int] = 30
_IEM_CSV_MAX_BODY_BYTES: Final[int] = 2 * 1024 * 1024


def _iem_window(run_ts_ns: int) -> tuple[str, str]:
    """``sts``/``ets`` (YYYY-MM-DDTHH:MMZ) bracketing one runtime; rows are filtered after."""
    start = dt.datetime.fromtimestamp(run_ts_ns / _NS, tz=dt.UTC)
    end = start + dt.timedelta(minutes=1)
    return start.strftime("%Y-%m-%dT%H:%MZ"), end.strftime("%Y-%m-%dT%H:%MZ")


def _iem_csv_fetcher(
    clock: Callable[[], int], *, model: str, budget: int, check_proxy_env: bool
) -> Callable[[str, int], FetchedPayload]:
    transport = IemMosProbeTransport(
        budget=RequestBudget(limit=budget),
        pacer=IemPacer(clock=clock, min_interval_ns=IEM_AFOS_LAV_MIN_INTERVAL_NS),
        user_agent=COLLECTOR_USER_AGENT,
        clock=clock,
        max_body_bytes=_IEM_CSV_MAX_BODY_BYTES,
        check_proxy_env=check_proxy_env,
    )

    def fetch(station: str, run_ts_ns: int) -> FetchedPayload:
        sts, ets = _iem_window(run_ts_ns)
        if model == "LAV":
            result = asyncio.run(transport.fetch_lav(station, sts, ets))
        else:
            result = asyncio.run(transport.fetch_mos_csv(station, model, sts, ets))
        text = result.text or ""
        if not legs.iem_csv_has_run(text, station, run_ts_ns):
            raise NotPublishedError(f"no {model} row for {station} at {sts}")
        return FetchedPayload(text.encode("utf-8"), result.retrieved_at_ns, None, "iem")

    return fetch


def default_lav_fetcher(
    clock: Callable[[], int], *, check_proxy_env: bool = True
) -> Callable[[str, int], FetchedPayload]:
    return _iem_csv_fetcher(
        clock, model="LAV", budget=_LAV_REQUEST_BUDGET, check_proxy_env=check_proxy_env
    )


def default_mos_fetcher(
    clock: Callable[[], int], *, check_proxy_env: bool = True
) -> Callable[[str, int], FetchedPayload]:
    return _iem_csv_fetcher(
        clock, model="GFS", budget=_MOS_REQUEST_BUDGET, check_proxy_env=check_proxy_env
    )


def default_obs_fetcher(
    clock: Callable[[], int], *, check_proxy_env: bool = True
) -> Callable[[str], FetchedPayload]:
    """The live observation request (parity with ``NwsObservationTransport`` is pinned by test)."""
    transport = obs_transport.ObsTransport(
        clock=clock, user_agent=COLLECTOR_USER_AGENT, check_proxy_env=check_proxy_env
    )

    def fetch(station: str) -> FetchedPayload:
        result = asyncio.run(
            transport.fetch_station_observations(station, limit=legs.OBS_FETCH_LIMIT)
        )
        return FetchedPayload(
            (result.text or "").encode("utf-8"), result.retrieved_at_ns, None, "nws"
        )

    return fetch


def _make_alert(webhook_url: str | None) -> Callable[[str, str, str], bool]:
    def alert(event: str, source: str, detail: str) -> bool:
        print(f"ALERT {event} {source}: {detail}", file=sys.stderr)  # the journal line
        if not webhook_url:
            return False
        return bool(alert_mod.post_alert(webhook_url, event, source, detail))

    return alert


def build_default_context(args: argparse.Namespace) -> CycleContext:
    clock = time.time_ns
    fetchers: dict[str, Callable[..., FetchedPayload]] = {
        "lamp": _unused_fetcher,
        "pfm": _unused_fetcher,
        "nbp": _unused_fetcher,
        "lav": _unused_fetcher,
        "mos": _unused_fetcher,
        "obs": _unused_fetcher,
    }
    factories: dict[str, Callable[[Callable[[], int]], Callable[..., FetchedPayload]]] = {
        "lamp": default_lamp_fetcher,
        "pfm": default_pfm_fetcher,
        "nbp": default_nbp_fetcher,
        "lav": default_lav_fetcher,
        "mos": default_mos_fetcher,
        "obs": default_obs_fetcher,
    }
    fetchers[args.source] = factories[args.source](clock)
    return CycleContext(
        root=args.archive_root,
        clock=clock,
        sleep=time.sleep,
        fetch_lamp=fetchers["lamp"],
        fetch_pfm=fetchers["pfm"],
        fetch_nbp=fetchers["nbp"],
        fetch_lav=fetchers["lav"],
        fetch_mos=fetchers["mos"],
        fetch_obs=fetchers["obs"],
        measure_ntp_offset=guards.measure_ntp_offset_ns,
        free_bytes=guards.disk_free_bytes,
        alert=_make_alert(guards.resolve_webhook_url(args.alerts_env)),
        poll_interval_s=args.poll_interval_s,
        ntp_bound_ns=args.ntp_bound_ms * 1_000_000,
        min_free_bytes=args.min_free_gib * _GIB,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="us_source_collector",
        description="One F13-C1 collection cycle for one US source (oneshot, idempotent).",
    )
    parser.add_argument("--source", required=True, choices=sorted(SOURCE_KEYS))
    parser.add_argument("--archive-root", required=True, type=Path, help="the sole writable dir")
    parser.add_argument(
        "--alerts-env",
        type=Path,
        default=Path.home() / ".config" / "breezy" / "alerts.env",
        help="alerts.env, read as a file (the alert sink); values are never printed",
    )
    parser.add_argument("--poll-interval-s", type=float, default=60.0)
    parser.add_argument("--ntp-bound-ms", type=int, default=_DEFAULT_NTP_BOUND_MS)
    parser.add_argument("--min-free-gib", type=int, default=_DEFAULT_MIN_FREE_GIB)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.archive_root.is_dir():
        print(f"error: archive root {args.archive_root} is not a directory", file=sys.stderr)
        return _EXIT_REFUSED
    report = run_cycle(args.source, build_default_context(args))
    print(f"source={report.source} status={report.status} refused={report.refused}")
    return report.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
