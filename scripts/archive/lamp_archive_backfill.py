"""F13 A1 backfill: LAMP archives (MDL yearly tars, MDL monthly gz) and the IEM LAV gap-fill.

Coordinator-run. Read-only network use against ``lamp.mdl.nws.noaa.gov`` (the exact host the
existing ``MdlLampTransport`` allows, under its one path prefix) and, for the gap-fill leg only,
``mesonet.agron.iastate.edu``. The one local write path is the existing revision store
(``UsSourceRevisionStore``) under the existing product keys, plus an append-only availability
manifest beside it (``availability_manifest.jsonl``).

Legs:

* ``mdl-yearly``  ``lmp_lavtxt.YYYY.tar`` for 2021-2025, streamed member by member by the H2 tar
  handler. Members that are not a selected cycle are skipped without being parsed.
* ``mdl-monthly`` ``lmp_lavtxt.YYYYMM.HHMMz.gz`` (2026-01..2026-09 by default), a concatenated-text
  gzip read through the streamed gzip line reader, with the same byte caps.
* ``iem-lav``     IEM LAV CSV, per station and month, stored under ``us-lav-iem``. A gap-fill and
  cross-check only: its basis is flagged (``iem_lav_gap_fill_run_label_inferred``: IEM labels the
  run HH:00 while the real run is probably HH:30) and it never writes to ``us-lamp-mdl``.

Cycles: the 24 hourly HH30 runs of ``lavtxt`` (hours 1-25 ahead), which is what the daily max is
derived from. The MDL archive has no ``lavtxt_ext`` file (``lmp_lavtxt`` only; A0-R4); the
hours 26-38 extension exists only in the live feed (``us-lamp-live``, station ``ALLEXT``). The
quarter-hour runs are out of scope (A0-R3).

Stored: ONE raw revision per run under ``us-lamp-mdl``, station ``ALL``, ``run_ts`` = the header's
issuance, holding only the five closed-set station blocks (KNYC KLAX KMDW KMIA KSFO). It is NOT
the whole bulletin the live collector stores, so it never collides with a live revision. A day or
run absent from an archive is MISSING: counted in the report, never imputed.

Availability: ``archive`` basis, ``run + 60 min`` (the plan's conservative LAMP lag, above the
A0-measured 6-10 min). It is written to the manifest, with the holdout tag: a run dated on or
after 2026-07-01 is STORED (kept for the forward feed) but tagged ``holdout_sealed``; no fit or
score code lives here and none may read a sealed row.

Statuses per unit: ``complete``; ``not_published`` (404: the file is missing); ``oversize`` (a
byte, member or line cap); ``degraded`` (the unit ran to the end but a run was refused by the
store's payload checks, hit a store error, or dropped any block outside
``EXPECTED_SKIP_DROPS``; that run's day is reported missing); ``error``;
and the STOP-ALL statuses ``throttled`` / ``forbidden`` /
``paused_launch_window`` / ``budget_exhausted`` / ``store_busy``. A non-``complete`` unit exits 1.

Files: the revision store, the manifest and the report are written 0o644 (world-readable): the
data is public NWS/IEM text and this matches the live collector's files. Deliberately not 0o600.

Tar completeness: a yearly unit reports the expected year x cycle members that were absent
(``members_missing``) and whether the tar stream was fully validated (``tar_stream_complete``,
``tar_sha256``). Members that are skipped are never gunzipped, so any skip leaves the stream
unvalidated; the members that WERE ingested were each validated by their own parse.

Safety: ``--dry-run`` plans only (no network, no write, no archive directory created);
``--apply`` needs ``BREEZY_LIVE=1`` and a hard request budget. No request starts that could meet
the 16:30-17:10Z launch window for the worst case of its stream (a tar may run 2 h). The run is
address-space capped (``--memory-cap-gib``).
"""

from __future__ import annotations

import argparse
import asyncio
import calendar
import datetime as dt
import functools
import json
import os
import re
import sys
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

_ARCHIVE_DIR = Path(__file__).resolve().parent
for _directory in (_ARCHIVE_DIR, _ARCHIVE_DIR.parent / "venue"):  # pragma: no cover - bootstrap
    if str(_directory) not in sys.path:
        sys.path.insert(0, str(_directory))

from iem_mos_probe_transport import (  # type: ignore[import-not-found]
    IEM_AFOS_LAV_MIN_INTERVAL_NS,
    IEM_LAV_MAX_BODY_BYTES,
    IemPacer,
    PacedIemTransport,
)
from lamp_archive_runs import (  # type: ignore[import-not-found]
    ARCHIVE_PREREG,
    HOLDOUT_START,
    MANIFEST_NAME,
    LampRun,
    LavPayloadError,
    Manifest,
    availability_row,
    iter_lamp_runs,
    missing_stations,
    split_lav_runs,
)
from us_source_backfill import (  # type: ignore[import-not-found]
    BUSY_RETRIES,
    BUSY_WAIT_S,
    DEFAULT_USER_AGENT,
    LIVE_ENV_VAR,
    REQUEST_WORST_CASE_S,
    THROTTLE_BACKOFF_S,
    USER_AGENT_ENV_VAR,
)
from us_source_backfill import (
    _archive_root_problem as archive_root_problem,
)

from breezy.analysis.memory_cap import apply_address_space_cap
from breezy.ingest.http import (
    ForbiddenError,
    OversizeBodyError,
    RateLimitedError,
    TransportError,
)
from breezy.ingest.lamp_parse import LampParseError, parse_lamp_blocks
from breezy.ingest.mdl_lamp_transport import (
    DEFAULT_LAMP_MONTH_LIMITS,
    DEFAULT_LAMP_YEAR_LIMITS,
    LampNotPublishedError,
    MdlLampTransport,
    build_mdl_lamp_transport,
)
from breezy.ingest.probe_transport import RequestBudget, RequestBudgetExceededError
from breezy.persistence.autonomy.capture_schedule import LAUNCH_WINDOW_UTC, launch_window_guard
from breezy.persistence.us_source_request import (
    LAV_MODEL,
    US_LAMP_MDL_SOURCE,
    US_LAV_IEM_SOURCE,
    US_SOURCE_STATIONS,
)
from breezy.persistence.us_source_revision_store import (
    AppendOutcome,
    RevisionPayloadRefusedError,
    RevisionStoreBusyError,
    RevisionStoreError,
    UsSourceRevisionStore,
)

__all__ = [
    "ARCHIVE_PREREG",
    "HOLDOUT_START",
    "MANIFEST_NAME",
    "REQUEST_WORST_CASE_S",
    "RETRY_AFTER_WORST_CASE_S",
    "THROTTLE_BACKOFF_S",
    "Manifest",
    "RequestBudget",
    "RequestBudgetExceededError",
    "apply_address_space_cap",
    "iter_lamp_runs",
    "main",
    "make_lav_fetch",
    "missing_stations",
]

_NS: Final[int] = 1_000_000_000
LEGS: Final[tuple[str, ...]] = ("mdl-yearly", "mdl-monthly", "iem-lav")
FIRST_YEAR: Final[int] = 2021
LAST_TAR_YEAR: Final[int] = 2025
DEFAULT_START_MONTH: Final[str] = "2026-01"
DEFAULT_END_MONTH: Final[str] = "2026-09"
DEFAULT_CYCLES: Final[tuple[str, ...]] = tuple(f"{hour:02d}30" for hour in range(24))
#: MDL documents no rate; one request per stream, spaced generously.
MDL_MIN_INTERVAL_S: Final[float] = 5.0
DEFAULT_MEMORY_CAP_GIB: Final[float] = 4.0
#: Worst-case span of one stream: its wall-clock cap plus the connect/slack allowance.
_SLACK_S: Final[int] = REQUEST_WORST_CASE_S
#: The transport honours up to 2 ``Retry-After`` waits of at most 120 s each before a stream
#: opens (``mdl_lamp_transport``: ``max_429_retries=2``, ``_MAX_RETRY_AFTER_SECONDS=120``); a test
#: pins this equal to those. Each retry is also charged to the request budget (``_charge_retries``).
RETRY_AFTER_WORST_CASE_S: Final[int] = 2 * 120
YEAR_WORST_CASE_S: Final[int] = (
    int(DEFAULT_LAMP_YEAR_LIMITS.max_wall_seconds) + _SLACK_S + RETRY_AFTER_WORST_CASE_S
)
MONTH_WORST_CASE_S: Final[int] = (
    int(DEFAULT_LAMP_MONTH_LIMITS.max_wall_seconds) + _SLACK_S + RETRY_AFTER_WORST_CASE_S
)
STOP_ALL_STATUSES: Final[frozenset[str]] = frozenset(
    {"throttled", "forbidden", "paused_launch_window", "budget_exhausted", "store_busy"}
)
_EXIT_REFUSED: Final[int] = 2
_EXIT_INCOMPLETE: Final[int] = 1
_MEMBER_RE: Final[re.Pattern[str]] = re.compile(
    r"\Almp_lavtxt\.(?P<ym>\d{6})\.(?P<hhmm>\d{4})z\.gz\Z"
)
_MONTH_RE: Final[re.Pattern[str]] = re.compile(r"\A(\d{4})-(\d{2})\Z")
_CYCLE_RE: Final[re.Pattern[str]] = re.compile(r"\A([01]\d|2[0-3])30\Z")

LavFetch = Callable[[str, str, str], str]


class PausedLaunchWindowError(Exception):
    """A request here could meet the 16:30-17:10Z launch window."""


class StoreBusyError(Exception):
    """The unit lock stayed busy past the retries."""


# ------------------------------------------------------------------------ report


@dataclass(slots=True)
class UnitReport:
    unit: str
    leg: str
    status: str = "complete"
    requests: int = 0
    runs_seen: int = 0
    appended: int = 0
    unchanged: int = 0
    quarantined: int = 0
    members_ingested: int = 0
    members_skipped: dict[str, int] = field(default_factory=dict)
    dropped: dict[str, int] = field(default_factory=dict)
    refused: dict[str, int] = field(default_factory=dict)
    store_errors: dict[str, int] = field(default_factory=dict)
    station_blocks_missing: dict[str, int] = field(default_factory=dict)
    members_missing: list[str] = field(default_factory=list)
    tar_stream_complete: bool | None = None
    tar_sha256: str | None = None
    missing_runs: dict[str, list[str]] = field(default_factory=dict)
    missing_run_count: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit": self.unit,
            "leg": self.leg,
            "status": self.status,
            "requests": self.requests,
            "runs_seen": self.runs_seen,
            "appended": self.appended,
            "unchanged": self.unchanged,
            "quarantined": self.quarantined,
            "members_ingested": self.members_ingested,
            "members_skipped": dict(sorted(self.members_skipped.items())),
            "dropped": dict(sorted(self.dropped.items())),
            "refused": dict(sorted(self.refused.items())),
            "store_errors": dict(sorted(self.store_errors.items())),
            "station_blocks_missing": dict(sorted(self.station_blocks_missing.items())),
            "members_missing": sorted(self.members_missing),
            "members_missing_count": len(self.members_missing),
            "tar_stream_complete": self.tar_stream_complete,
            "tar_sha256": self.tar_sha256,
            "missing_runs": dict(sorted(self.missing_runs.items())),
            "missing_run_count": self.missing_run_count,
            "error": self.error,
        }


def _bump(tally: dict[str, int], key: str) -> None:
    tally[key] = tally.get(key, 0) + 1


def _alert(message: str) -> None:
    sys.stderr.write(f"ALERT lamp-archive-backfill: {message}\n")


# ------------------------------------------------------------------- request gate


class RequestGate:
    """Hard budget, fixed pacing and the launch-window guard for the MDL requests."""

    def __init__(
        self,
        *,
        budget: RequestBudget,
        clock: Callable[[], int],
        sleep: Callable[[float], None],
        min_interval_s: float,
    ) -> None:
        self._budget = budget
        self._clock = clock
        self._sleep = sleep
        self._interval_ns = int(min_interval_s * _NS)
        self._last_ns: int | None = None

    def check_window(self, worst_case_s: int) -> None:
        if not launch_window_guard(self._clock(), 0, worst_case_s):
            raise PausedLaunchWindowError

    def before(self, worst_case_s: int) -> None:
        if self._budget.remaining < 1:
            raise RequestBudgetExceededError("the request budget is exhausted")
        now = self._clock()
        slot = now if self._last_ns is None else max(now, self._last_ns + self._interval_ns)
        self._last_ns = slot
        if slot > now:
            self._sleep((slot - now) / _NS)
        self.check_window(worst_case_s)
        self._budget.consume()


def make_lav_fetch(
    *,
    budget: RequestBudget,
    user_agent: str,
    clock_ns: Callable[[], int],
    sleeper: Callable[[float], Any] | None = None,
    check_proxy_env: bool = True,
) -> LavFetch:
    """The IEM LAV fetch: the paced, budgeted IEM transport at the A0-R1 spacing."""
    transport = PacedIemTransport(
        budget=budget,
        pacer=IemPacer(
            clock=clock_ns, sleeper=sleeper, min_interval_ns=IEM_AFOS_LAV_MIN_INTERVAL_NS
        ),
        user_agent=user_agent,
        clock=clock_ns,
        max_body_bytes=IEM_LAV_MAX_BODY_BYTES,
        accept="text/csv",
        check_proxy_env=check_proxy_env,
    )

    def fetch(station: str, sts: str, ets: str) -> str:
        return asyncio.run(transport.fetch_lav(station, sts, ets)).text or ""

    return fetch


# ----------------------------------------------------------------- run context


class _StoreClock:
    def __init__(self, clock_ns: Callable[[], int]) -> None:
        self._clock_ns = clock_ns

    def timestamp_ns(self) -> int:
        return self._clock_ns()


def _validate_lamp(payload: bytes) -> None:
    if not parse_lamp_blocks(payload.decode("utf-8").splitlines()):
        raise LampParseError("no_closed_station_block")


def _validate_lav(payload: bytes) -> None:
    first = payload.decode("utf-8").split("\n", 1)[0].lower().split(",")
    if "runtime" not in [cell.strip() for cell in first]:
        raise LavPayloadError("LAV payload has no runtime column")


@dataclass(slots=True)
class _Ctx:
    stations: tuple[str, ...]
    cycles: tuple[str, ...]
    clock: Callable[[], int]
    sleep: Callable[[float], None]
    gate: RequestGate
    stores: dict[str, UsSourceRevisionStore]
    manifests: dict[str, Manifest]
    mdl: MdlLampTransport | None = None
    lav_fetch: LavFetch | None = None

    @property
    def station_set(self) -> frozenset[str]:
        return frozenset(self.stations)


def _append(
    ctx: _Ctx,
    rep: UnitReport,
    *,
    source: str,
    station: str,
    model: str | None,
    run_at: dt.datetime,
    payload: bytes,
) -> bool:
    """Append one raw revision and its manifest row; a busy unit lock is retried then raised.

    True when the run is held in the store (appended, unchanged or quarantined); False when it
    was refused or hit a store error (it is then NOT seen: its day is reported missing).
    """
    store, manifest = ctx.stores[source], ctx.manifests[source]
    run_ns = int(run_at.timestamp()) * _NS
    for attempt in range(BUSY_RETRIES + 1):
        try:
            with store.unit_lock(source):
                result = store.append_if_new(
                    source=source, station=station, run_ts_ns=run_ns, model=model, payload=payload
                )
                if result.outcome is not AppendOutcome.QUARANTINED:
                    manifest.record(
                        availability_row(
                            source=source,
                            station=station,
                            run_at=run_at,
                            sha256=result.sha256,
                            revision=result.revision,
                            leg=rep.leg,
                            origin=rep.unit,
                        )
                    )
        except RevisionStoreBusyError:
            if attempt == BUSY_RETRIES:
                raise StoreBusyError from None
            ctx.sleep(BUSY_WAIT_S)
            continue
        except RevisionPayloadRefusedError as exc:  # an expected refusal of this payload
            _bump(rep.refused, str(getattr(exc.__cause__, "reason", type(exc).__name__)))
            return False
        except RevisionStoreError as exc:  # integrity or other store trouble: not a refusal
            _bump(rep.store_errors, type(exc).__name__)
            return False
        if result.outcome is AppendOutcome.APPENDED:
            rep.appended += 1
        elif result.outcome is AppendOutcome.UNCHANGED:
            rep.unchanged += 1
        else:
            rep.quarantined += 1
        return True
    raise AssertionError("unreachable: the retry loop returns or raises")  # pragma: no cover


# ------------------------------------------------------------------ unit runners


def _ingest_lamp_lines(
    ctx: _Ctx, rep: UnitReport, lines: Iterable[str], *, ym: str, hhmm: str
) -> None:
    year, month = int(ym[:4]), int(ym[4:])
    seen_days: set[int] = set()
    for run in iter_lamp_runs(
        lines,
        expect_year_month=(year, month),
        expect_hhmm=hhmm,
        tally=rep.dropped,
        stations=ctx.station_set,
    ):
        rep.runs_seen += 1
        _note_missing_stations(rep, run, ctx.stations)
        held = _append(
            ctx,
            rep,
            source=US_LAMP_MDL_SOURCE,
            station="ALL",
            model=None,
            run_at=run.run_at,
            payload=run.payload(),
        )
        if held:  # a refused or errored run never counts as seen
            seen_days.add(run.run_at.day)
    absent = [d for d in range(1, calendar.monthrange(year, month)[1] + 1) if d not in seen_days]
    if absent:
        rep.missing_runs[f"{ym}.{hhmm}"] = [f"{year:04d}-{month:02d}-{d:02d}" for d in absent]
        rep.missing_run_count += len(absent)


def _note_missing_stations(rep: UnitReport, run: LampRun, stations: Sequence[str]) -> None:
    for station in missing_stations(run, stations):
        _bump(rep.station_blocks_missing, station)


def _run_year(ctx: _Ctx, rep: UnitReport, year: int) -> None:
    assert ctx.mdl is not None
    ctx.gate.before(YEAR_WORST_CASE_S)
    rep.requests += 1
    seen_members: set[str] = set()
    with ctx.mdl.fetch_lamp_archive_year(year) as stream:
        for member in stream.members():
            match = _MEMBER_RE.fullmatch(member.name)
            if match is None:
                _bump(rep.members_skipped, "unrecognised_name")
            elif int(match["ym"][:4]) != year:
                _bump(rep.members_skipped, "wrong_year")
            elif match["hhmm"] not in ctx.cycles:
                _bump(rep.members_skipped, "not_selected_cycle")
            else:
                seen_members.add(f"{match['ym']}.{match['hhmm']}")
                rep.members_ingested += 1
                _ingest_lamp_lines(
                    ctx, rep, member.lines(ctx.station_set), ym=match["ym"], hhmm=match["hhmm"]
                )
        _note_tar_outcome(ctx, rep, year, seen_members, stream)


def _note_tar_outcome(
    ctx: _Ctx, rep: UnitReport, year: int, seen_members: set[str], stream: Any
) -> None:
    """Report members absent from the tar and whether its stream was fully validated.

    A skipped (unselected or unrecognised) member is never gunzipped, so the stream is not
    fully validated whenever any member was skipped: ``tar_stream_complete`` is then False and no
    sha256 is released. That is reported, never papered over.
    """
    expected = {f"{year:04d}{m:02d}.{hhmm}" for m in range(1, 13) for hhmm in ctx.cycles}
    rep.members_missing = sorted(expected - seen_members)
    try:
        rep.tar_sha256 = stream.sha256
        rep.tar_stream_complete = True
    except RuntimeError:
        rep.tar_stream_complete = False


def _run_month(ctx: _Ctx, rep: UnitReport, ym: str, hhmm: str) -> None:
    assert ctx.mdl is not None
    ctx.gate.before(MONTH_WORST_CASE_S)
    rep.requests += 1
    with ctx.mdl.fetch_lamp_archive_month(ym, hhmm) as stream:
        rep.members_ingested += 1
        _ingest_lamp_lines(ctx, rep, stream.lines(ctx.station_set), ym=ym, hhmm=hhmm)


def _charge_retries(transport: MdlLampTransport, budget: RequestBudget) -> None:
    """Charge each transport 429 retry to the request budget before it is made.

    The transport re-issues a stream request after a ``Retry-After`` wait through its sleep
    hook and nowhere else; wrapping that hook (the transport module is not edited) spends one
    budget request per retry, so a retry can never exceed the hard ceiling.
    """
    wait = transport._sleep

    def charged(seconds: float) -> None:
        budget.consume()
        wait(seconds)

    transport._sleep = charged


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def _run_lav(ctx: _Ctx, rep: UnitReport, station: str, year: int, month: int) -> None:
    assert ctx.lav_fetch is not None
    ctx.gate.check_window(REQUEST_WORST_CASE_S)
    after_year, after_month = _next_month(year, month)
    sts = f"{year:04d}-{month:02d}-01T00:00Z"
    ets = f"{after_year:04d}-{after_month:02d}-01T00:00Z"
    try:
        text = ctx.lav_fetch(station, sts, ets)
    except RequestBudgetExceededError:
        raise
    except BaseException:
        rep.requests += 1
        raise
    rep.requests += 1
    for run_at, payload in split_lav_runs(text, station, rep.dropped).items():
        rep.runs_seen += 1
        _append(
            ctx,
            rep,
            source=US_LAV_IEM_SOURCE,
            station=station,
            model=LAV_MODEL,
            run_at=run_at,
            payload=payload,
        )


@dataclass(frozen=True, slots=True)
class _Unit:
    name: str
    leg: str
    run: Callable[[_Ctx, UnitReport], None]


def _months(start: tuple[int, int], end: tuple[int, int]) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    year, month = start
    while (year, month) <= end:
        out.append((year, month))
        year, month = _next_month(year, month)
    return out


def _units(args: argparse.Namespace, leg: str) -> list[_Unit]:
    months = _months(args.start_month, args.end_month)
    if leg == "mdl-yearly":
        return [
            _Unit(str(y), leg, functools.partial(_run_year, year=y))
            for y in range(args.first_year, args.last_year + 1)
        ]
    if leg == "mdl-monthly":
        return [
            _Unit(
                f"{y:04d}{m:02d}.{hhmm}",
                leg,
                functools.partial(_run_month, ym=f"{y:04d}{m:02d}", hhmm=hhmm),
            )
            for (y, m) in months
            for hhmm in args.cycles
        ]
    return [
        _Unit(f"{s}.{y:04d}{m:02d}", leg, functools.partial(_run_lav, station=s, year=y, month=m))
        for s in args.stations
        for (y, m) in months
    ]


def _execute(ctx: _Ctx, unit: _Unit) -> UnitReport:
    """Run one unit; every fault becomes a status. Never raises for a unit-local fault."""
    rep = UnitReport(unit=unit.name, leg=unit.leg)
    attempt = 0
    while True:
        try:
            unit.run(ctx, rep)
            return _settled(rep)
        except PausedLaunchWindowError:
            rep.status = "paused_launch_window"
            _alert(f"{unit.name}: a request could meet the 16:30-17:10Z launch window; stopping")
        except RequestBudgetExceededError:
            rep.status = "budget_exhausted"
            _alert(f"{unit.name}: the request budget is exhausted; stopping")
        except StoreBusyError:
            rep.status = "store_busy"
            _alert(f"{unit.name}: the revision store stayed busy; stopping")
        except LampNotPublishedError:
            rep.status = "not_published"
        except ForbiddenError:
            rep.status = "forbidden"
            _alert(f"{unit.name}: 403 (abuse block); stopping every leg")
        except RateLimitedError:
            if attempt < len(THROTTLE_BACKOFF_S):
                ctx.sleep(THROTTLE_BACKOFF_S[attempt])
                attempt += 1
                continue
            rep.status = "throttled"
            _alert(f"{unit.name}: the throttle persisted; stopping every leg")
        except OversizeBodyError as exc:
            rep.status, rep.error = "oversize", f"{type(exc).__name__}: {exc}"
        except (TransportError, LavPayloadError, OSError, ValueError) as exc:
            rep.status, rep.error = "error", f"{type(exc).__name__}: {exc}"
        except Exception as exc:  # noqa: BLE001 - the unit boundary: record, never crash the run
            rep.status, rep.error = "error", f"{type(exc).__name__}: {exc}"
            _alert(f"{unit.name}: unexpected {rep.error}")
        return rep


#: Drop reasons that are the expected, benign skips of a source that carries more than the
#: closed set: an IEM LAV row for a station outside it. Every other drop (a bad or mismatched
#: header, an oversize or duplicate block, a reappearing run, a malformed LAV row) means data
#: the file carried was NOT stored, so it must surface as ``degraded`` and never as ``complete``.
EXPECTED_SKIP_DROPS: Final = frozenset({"wrong_station"})


def _settled(rep: UnitReport) -> UnitReport:
    """A unit that lost data (refused run, store error, unexpected drop) is not complete."""
    unexpected_drop = any(k not in EXPECTED_SKIP_DROPS for k in rep.dropped)
    if rep.status == "complete" and (rep.refused or rep.store_errors or unexpected_drop):
        rep.status = "degraded"
    return rep


# ---------------------------------------------------------------------- plan


def _plan(args: argparse.Namespace) -> dict[str, Any]:
    months = _months(args.start_month, args.end_month)
    years = list(range(args.first_year, args.last_year + 1))
    per_leg = {
        "mdl-yearly": {
            "years": years,
            "estimated_requests": len(years),
            "worst_case_s_per_request": YEAR_WORST_CASE_S,
        },
        "mdl-monthly": {
            "months": [f"{y:04d}-{m:02d}" for y, m in months],
            "estimated_requests": len(months) * len(args.cycles),
            "worst_case_s_per_request": MONTH_WORST_CASE_S,
        },
        "iem-lav": {
            "months": [f"{y:04d}-{m:02d}" for y, m in months],
            "estimated_requests": len(months) * len(args.stations),
            "worst_case_s_per_request": REQUEST_WORST_CASE_S,
        },
    }
    chosen = {leg: per_leg[leg] for leg in LEGS if leg in args.legs}
    total = sum(int(leg["estimated_requests"]) for leg in chosen.values())
    return {
        **chosen,
        "cycles": list(args.cycles),
        "stations": list(args.stations),
        "mdl_min_interval_s": MDL_MIN_INTERVAL_S,
        "iem_min_interval_s": IEM_AFOS_LAV_MIN_INTERVAL_NS / _NS,
        "estimated_requests": total,
        "request_budget": args.request_budget,
        "fits_budget": None if args.request_budget is None else total <= args.request_budget,
        "holdout_start": HOLDOUT_START.isoformat(),
        "memory_cap_gib": args.memory_cap_gib,
    }


# ----------------------------------------------------------------------- main


def _month_arg(text: str) -> tuple[int, int]:
    match = _MONTH_RE.match(text)
    if match is None or not 1 <= int(match[2]) <= 12:
        raise argparse.ArgumentTypeError(f"{text!r} is not YYYY-MM")
    return int(match[1]), int(match[2])


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--legs", nargs="+", choices=LEGS, default=list(LEGS))
    parser.add_argument("--stations", nargs="+", default=list(US_SOURCE_STATIONS))
    parser.add_argument("--cycles", nargs="+", default=list(DEFAULT_CYCLES))
    parser.add_argument("--first-year", type=int, default=FIRST_YEAR)
    parser.add_argument("--last-year", type=int, default=LAST_TAR_YEAR)
    parser.add_argument("--start-month", type=_month_arg, default=_month_arg(DEFAULT_START_MONTH))
    parser.add_argument("--end-month", type=_month_arg, default=_month_arg(DEFAULT_END_MONTH))
    parser.add_argument("--request-budget", type=int, default=None)
    parser.add_argument("--memory-cap-gib", type=float, default=DEFAULT_MEMORY_CAP_GIB)
    parser.add_argument("--report-json", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(list(argv))


def _validate(args: argparse.Namespace) -> str | None:
    """A refusal message, or None when the invocation is coherent."""
    if args.dry_run == args.apply:
        return "exactly one of --dry-run and --apply is required"
    unknown = [s for s in args.stations if s not in US_SOURCE_STATIONS]
    if unknown:
        return f"station(s) {unknown} are outside the closed set {list(US_SOURCE_STATIONS)}"
    bad = [c for c in args.cycles if _CYCLE_RE.match(c) is None]
    if bad:
        return f"cycle(s) {bad} are not HH30 runs (only the hourly :30 runs are in scope)"
    if not FIRST_YEAR <= args.first_year <= args.last_year <= LAST_TAR_YEAR:
        return (
            f"--first-year/--last-year must satisfy "
            f"{FIRST_YEAR} <= first <= last <= {LAST_TAR_YEAR}"
        )
    if not (FIRST_YEAR, 1) <= args.start_month <= args.end_month:
        return f"--start-month/--end-month must satisfy {FIRST_YEAR}-01 <= start <= end"
    if not args.memory_cap_gib > 0:
        return "--memory-cap-gib must be positive"
    problem: str | None = archive_root_problem(args.archive_root)
    if problem is not None:
        return str(problem)
    if args.request_budget is not None and args.request_budget < 1:
        return "--request-budget must be a positive request count"
    if args.apply and os.environ.get(LIVE_ENV_VAR) != "1":
        return f"{LIVE_ENV_VAR}=1 is required before any request may be dispatched"
    if args.apply and not args.request_budget:
        return "--request-budget is required for a real run"
    return None


def _write_report(path: Path | None, report: dict[str, Any]) -> None:
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    sys.stdout.write(text)


def main(
    argv: Sequence[str] | None = None,
    *,
    clock: Callable[[], int] = time.time_ns,
    sleep: Callable[[float], None] = time.sleep,
    mdl_factory: Callable[[Callable[[], int]], MdlLampTransport] = build_mdl_lamp_transport,
    iem_fetch_factory: Callable[..., LavFetch] = make_lav_fetch,
    memory_cap: Callable[[float], Any] = apply_address_space_cap,
) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    problem = _validate(args)
    if problem is not None:
        sys.stderr.write(f"REFUSED: {problem}\n")
        return _EXIT_REFUSED
    report: dict[str, Any] = {
        "mode": "dry_run" if args.dry_run else "apply",
        "inputs": {
            "legs": list(args.legs),
            "stations": list(args.stations),
            "cycles": list(args.cycles),
            "first_year": args.first_year,
            "last_year": args.last_year,
            "start_month": "{:04d}-{:02d}".format(*args.start_month),
            "end_month": "{:04d}-{:02d}".format(*args.end_month),
        },
        "launch_window_utc": "{:02d}:{:02d}-{:02d}:{:02d}".format(
            *LAUNCH_WINDOW_UTC[0], *LAUNCH_WINDOW_UTC[1]
        ),
        "plan": _plan(args),
    }
    if args.dry_run:
        _write_report(args.report_json, report)
        return 0
    code = _EXIT_INCOMPLETE
    try:
        code = _apply(args, report, clock, sleep, mdl_factory, iem_fetch_factory, memory_cap)
    except Exception as exc:  # noqa: BLE001 - the report is the run's evidence; never lose it
        report["error"] = f"{type(exc).__name__}: {exc}"
        _alert(f"run aborted by unexpected {report['error']}")
    finally:
        _write_report(args.report_json, report)
    return code


def _apply(
    args: argparse.Namespace,
    report: dict[str, Any],
    clock: Callable[[], int],
    sleep: Callable[[float], None],
    mdl_factory: Callable[[Callable[[], int]], MdlLampTransport],
    iem_fetch_factory: Callable[..., LavFetch],
    memory_cap: Callable[[float], Any],
) -> int:
    memory_cap(args.memory_cap_gib)
    budget = RequestBudget(limit=args.request_budget)
    root: Path = args.archive_root
    store_clock = _StoreClock(clock)
    ctx = _Ctx(
        stations=tuple(args.stations),
        cycles=tuple(args.cycles),
        clock=clock,
        sleep=sleep,
        gate=RequestGate(
            budget=budget, clock=clock, sleep=sleep, min_interval_s=MDL_MIN_INTERVAL_S
        ),
        stores={
            US_LAMP_MDL_SOURCE: UsSourceRevisionStore(root, store_clock, validator=_validate_lamp),
            US_LAV_IEM_SOURCE: UsSourceRevisionStore(root, store_clock, validator=_validate_lav),
        },
        manifests={s: Manifest(root, s) for s in (US_LAMP_MDL_SOURCE, US_LAV_IEM_SOURCE)},
    )
    if any(leg in args.legs for leg in ("mdl-yearly", "mdl-monthly")):
        ctx.mdl = mdl_factory(clock)
        _charge_retries(ctx.mdl, budget)
    if "iem-lav" in args.legs:
        ctx.lav_fetch = iem_fetch_factory(
            budget=budget,
            user_agent=os.environ.get(USER_AGENT_ENV_VAR, DEFAULT_USER_AGENT),
            clock_ns=clock,
        )
    legs_report: dict[str, Any] = report.setdefault("legs", {})
    report["manifest_torn_lines"] = 0
    pending = [(leg, unit) for leg in LEGS if leg in args.legs for unit in _units(args, leg)]
    incomplete = False
    for index, (leg, unit) in enumerate(pending):
        rep = _execute(ctx, unit)
        legs_report.setdefault(leg, {"units": []})["units"].append(rep.to_dict())
        incomplete = incomplete or rep.status != "complete"
        if rep.status in STOP_ALL_STATUSES:
            report["stopped"] = {
                "reason": rep.status,
                "skipped_units": [u.name for _, u in pending[index + 1 :]],
            }
            break
    report["manifest_torn_lines"] = sum(m.torn_lines for m in ctx.manifests.values())
    return _EXIT_INCOMPLETE if incomplete or "stopped" in report else 0


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(main())
