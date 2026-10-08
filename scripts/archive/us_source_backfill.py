"""F13 B0 backfill: PFM history (IEM AFOS) and GFS MOS history (incl. KNYC). Coordinator-run.

Read-only network use against ``mesonet.agron.iastate.edu`` only; the one local write path is
the ``us-pfm-afos`` revision store (PFM) and the existing MOS archive writer (GFS).

* PFM: ``PacedIemTransport.fetch_afos_pfm`` pages ascending history (``sdate`` = the last issuance
  INSTANT, ``order=asc``, at most 20 products per request, halved on an oversize body down to
  one) at the A0-R1 pace
  (>= 4 s between AFOS requests). Each
  product is split out, its WMO issuance time resolved, parsed (a refused product is counted
  and never written) and appended RAW through ``UsSourceRevisionStore`` under the collector's
  key shape. The stored bytes are the product exactly as the AFOS response framed it (SOH ..
  ETX, nothing stripped), which is what the live collector stores for a ``limit=1`` response,
  so a live-collected issuance is UNCHANGED under a re-run, never a second revision.
  Normalised CSVs and the poll ledger are not written: a backfilled row's availability is
  its exact WMO header time and the live collector owns first-seen stamps.
* GFS: delegated to the existing ``iem_mos_backfill`` CLI (model ``GFS``, KNYC included via
  the R33 ``IEM_MOS_STATIONS`` widening), so the MOS archive keeps ONE writer.

Statuses: ``complete``; ``oversize_product`` (a single product exceeds the body cap: that station
stops, the next runs); ``error`` (an unexpected exception inside a leg is recorded, never raised);
``unplaceable_header`` (NO product on a page could be placed: that station stops, the next
runs; a single unplaceable product is only refused and counted, never mis-placed); ``degraded``
(a revision-store error other than an expected payload refusal); ``throttled`` / ``forbidden``
(an IEM 403 abuse block) /
``paused_launch_window`` (stop ALL remaining stations and the GFS leg);
``budget_exhausted``, ``store_busy``, ``coverage_incomplete`` (a coverage flush
dropped a key or left a journal stranded). Any status but ``complete`` exits 1.

Safety: ``--dry-run`` plans only (no network, no write); ``--apply`` needs ``BREEZY_LIVE=1`` and
a request budget. A request never starts inside, or close enough to meet, the 16:30-17:10Z
launch window (``launch_window_guard``): the PFM leg pauses and names the resume date. A throttle
body ("Too many requests ...") is never data: the leg backs off, then stops and alerts.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime as dt
import json
import logging
import math
import os
import re
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any, Final, cast

import httpx

_ARCHIVE_DIR = Path(__file__).resolve().parent
for _directory in (_ARCHIVE_DIR, _ARCHIVE_DIR.parent / "venue"):  # pragma: no cover - bootstrap
    if str(_directory) not in sys.path:
        sys.path.insert(0, str(_directory))

from iem_mos_probe_transport import (  # type: ignore[import-not-found]
    IEM_AFOS_LAV_MIN_INTERVAL_NS,
    IEM_AFOS_PFM_MAX_BODY_BYTES,
    IemPacer,
    PacedIemTransport,
)
from us_source_pfm_support import (  # type: ignore[import-not-found]
    BODY_WMO_TOLERANCE,
    BodyTimeError,
    RefusalQuarantine,
    body_issuance_utc,
    wmo_instant_near,
)

from breezy.ingest.http import (
    ContentEncodingError,
    DecodeError,
    DisallowedHostError,
    ForbiddenError,
    OversizeBodyError,
    RateLimitedError,
    RedirectError,
    ServerError,
    TransportError,
    TransportTimeoutError,
)
from breezy.ingest.pfm_parse import PfmParseError, parse_pfm_product
from breezy.ingest.probe_transport import (
    RequestBudget,
    RequestBudgetExceededError,
)
from breezy.persistence.autonomy.capture_schedule import LAUNCH_WINDOW_UTC, launch_window_guard
from breezy.persistence.us_source_request import (
    PFM_POINTS,
    US_PFM_AFOS_SOURCE,
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
    "BodyTimeError",
    "LegReport",
    "RefusalQuarantine",
    "UnplaceableHeaderError",
    "main",
    "make_pfm_fetch",
    "make_window_guard",
    "resolve_issuance_sequence",
    "run_pfm_leg",
    "split_products",
    "split_raw_products",
    "wmo_header_fields",
]

_NS: Final[int] = 1_000_000_000
LIVE_ENV_VAR: Final[str] = "BREEZY_LIVE"
USER_AGENT_ENV_VAR: Final[str] = "BREEZY_USER_AGENT"
#: 20 PFM products (~40-60 KB each) stay under the 2 MiB body cap; 50 did not.
DEFAULT_PAGE_LIMIT: Final[int] = 20
DEFAULT_USER_AGENT: Final[str] = "breezy-us-source-backfill (contact: jon@gopoint.com; F13 B0)"
FIRST_YEAR: Final[int] = 2021
#: A request is paced (>= 4 s), may read for up to 20 s, plus slack.
REQUEST_WORST_CASE_S: Final[int] = 30
THROTTLE_BACKOFF_S: Final[tuple[float, ...]] = (30.0, 120.0, 300.0)
#: Transient transport faults (timeout, 5xx): up to three retries per page, 30/60/120 s apart.
TRANSIENT_BACKOFF_S: Final[tuple[float, ...]] = (30.0, 60.0, 120.0)
BUSY_WAIT_S: Final[float] = 10.0
BUSY_RETRIES: Final[int] = 3
#: Planning constant for the dry run only (LOT issues ~28/day, the others fewer).
PLANNING_ISSUANCES_PER_DAY: Final[int] = 24
MAX_GAP_DAYS: Final[int] = 45
#: A month rollover is only credible for a short forward gap; a longer "rollover" is an
#: out-of-order header and is refused rather than placed a month ahead.
MAX_ROLLOVER_GAP_DAYS: Final[int] = 7
#: Statuses after which nothing else may run (the venue asked us to stop, or the window opened).
STOP_ALL_STATUSES: Final[frozenset[str]] = frozenset(
    {"throttled", "forbidden", "paused_launch_window"}
)
#: Mirrors ``scripts/analysis/market_calibration_scan.LIVE_DATA_ROOT``.
LIVE_DATA_ROOT: Final[Path] = Path.home() / ".local" / "share" / "breezy"
#: The one directory under the live data root this script may write (the collector's archive).
US_SOURCE_ARCHIVE_DIR: Final[str] = "us_source_archive"
_MAX_MONTH_BUMPS: Final[int] = 3
DEFAULT_MAX_RUNTIME_S: Final[int] = 3 * 3600
_REFUSE_REASON_FALLBACK: Final[str] = "unparsed"
_EXIT_REFUSED: Final[int] = 2
_EXIT_INCOMPLETE: Final[int] = 1
_SOH: Final[str] = "\x01"
_ETX: Final[str] = "\x03"
_HEADER_SCAN_LINES: Final[int] = 10
_WMO_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Z]{4}\d{2} ([A-Z]{4}) (\d{2})(\d{2})(\d{2})$")

#: ``(wfo, sdate, limit)``; ``sdate`` is a UTC instant (a ``datetime``, which is a ``date``).
PfmFetch = Callable[[str, dt.date, int], str]


# ------------------------------------------------------------------ pure helpers


def split_products(text: str) -> tuple[str, ...]:
    """Split one AFOS text response into its products (each keeps its leading SOH)."""
    if not text.strip():
        return ()
    parts = text.split(_SOH)
    if len(parts) == 1:
        body = text.replace(_ETX, "").rstrip()
        return (body,) if body else ()
    out: list[str] = []
    for part in parts[1:]:
        body = part.replace(_ETX, "").rstrip()
        if body.strip():
            out.append(_SOH + body)
    return tuple(out)


def split_raw_products(text: str) -> tuple[str, ...]:
    """Split an AFOS response into products, each EXACTLY as framed (SOH .. up to the next SOH).

    A single-product response is returned whole, byte for byte, which is what the live collector
    stores for ``limit=1``; nothing (ETX, trailing newline) is stripped.
    """
    if not text.strip():
        return ()
    starts = [i for i, ch in enumerate(text) if ch == _SOH]
    if len(starts) <= 1:
        return (text,)
    bounds = [*starts, len(text)]
    return tuple(text[a:b] for a, b in pairwise(bounds))


def wmo_header_fields(product: str) -> tuple[str, int, int, int] | None:
    """``(CCCC, day, hour, minute)`` of the WMO abbreviated heading, or None."""
    for line in product.splitlines()[:_HEADER_SCAN_LINES]:
        match = _WMO_RE.match(line.strip())
        if match is not None:
            cccc, day, hour, minute = match.groups()
            return cccc, int(day), int(hour), int(minute)
    return None


def _next_month(year: int, month: int) -> tuple[int, int]:
    return (year + 1, 1) if month == 12 else (year, month + 1)


def resolve_issuance_sequence(
    headers: Sequence[tuple[int, int, int]], start: dt.date
) -> list[dt.datetime]:
    """Resolve ``(day, hour, minute)`` headers, ascending from ``start``, to UTC instants.

    A WMO header carries no month or year. Ascending order lets the month advance whenever the
    day-of-month steps backwards (or the day does not exist in the current month).
    """
    year, month = start.year, start.month
    previous = dt.datetime(start.year, start.month, start.day, tzinfo=dt.UTC)
    resolved: list[dt.datetime] = []
    for day, hour, minute in headers:
        found: dt.datetime | None = None
        for _ in range(_MAX_MONTH_BUMPS):
            try:
                candidate: dt.datetime | None = dt.datetime(
                    year, month, day, hour, minute, tzinfo=dt.UTC
                )
            except ValueError:
                candidate = None
            if candidate is not None and candidate >= previous:
                found = candidate
                break
            year, month = _next_month(year, month)
        if found is None:
            raise ValueError(
                f"cannot place header {day:02d}{hour:02d}{minute:02d} after {previous}"
            )
        if found - previous > dt.timedelta(days=MAX_GAP_DAYS):
            raise ValueError(f"issuance gap over {MAX_GAP_DAYS} days before {found.isoformat()}")
        resolved.append(found)
        previous = found
    return resolved


class UnplaceableHeaderError(ValueError):
    """A product cannot be placed unambiguously; ``reason`` is the refusal it is counted under."""

    def __init__(self, message: str, reason: str = "unplaceable_header") -> None:
        super().__init__(message)
        self.reason = reason


def make_window_guard(worst_case_s: int = REQUEST_WORST_CASE_S) -> Callable[[int], bool]:
    """``window_ok(now_ns)``: True when a request starting now cannot meet 16:30-17:10Z."""

    def window_ok(now_ns: int) -> bool:
        return launch_window_guard(now_ns, 0, worst_case_s)

    return window_ok


# ---------------------------------------------------------------------- PFM leg


@dataclass(slots=True)
class LegReport:
    station: str
    wfo: str
    status: str = "complete"
    requests: int = 0
    products_seen: int = 0
    appended: int = 0
    unchanged: int = 0
    quarantined: int = 0
    refused: dict[str, int] = field(default_factory=dict)
    store_errors: dict[str, int] = field(default_factory=dict)
    truncated_days: tuple[dt.date, ...] = ()
    resume_sdate: dt.date | None = None
    error: str | None = None
    coverage_flushed: int = 0
    coverage_dropped: int = 0
    coverage_stranded_sources: tuple[str, ...] = ()
    coverage_torn_journal_lines: int = 0

    @property
    def refused_total(self) -> int:
        return sum(self.refused.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "station": self.station,
            "wfo": self.wfo,
            "status": self.status,
            "requests": self.requests,
            "products_seen": self.products_seen,
            "appended": self.appended,
            "unchanged": self.unchanged,
            "quarantined": self.quarantined,
            "refused": dict(sorted(self.refused.items())),
            "store_errors": dict(sorted(self.store_errors.items())),
            "truncated_days": [d.isoformat() for d in self.truncated_days],
            "resume_sdate": self.resume_sdate.isoformat() if self.resume_sdate else None,
            "error": self.error,
            "coverage_flushed": self.coverage_flushed,
            "coverage_dropped": self.coverage_dropped,
            "coverage_stranded_sources": list(self.coverage_stranded_sources),
            "coverage_torn_journal_lines": self.coverage_torn_journal_lines,
        }


class _StoreClock:
    def __init__(self, clock_ns: Callable[[], int]) -> None:
        self._clock_ns = clock_ns

    def timestamp_ns(self) -> int:
        return self._clock_ns()


def _stamp(cursor: dt.datetime) -> str:
    return cursor.strftime("%Y-%m-%dT%H:%MZ")


def _alert(message: str) -> None:
    sys.stderr.write(f"ALERT us-source-backfill: {message}\n")


_CONNECTION_CAUSES: Final = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ReadError,
    ConnectionResetError,
)
_NEVER_RETRIED: Final = (
    ForbiddenError,
    RateLimitedError,
    OversizeBodyError,
    DecodeError,
    DisallowedHostError,
    RedirectError,
    ContentEncodingError,
)


def _is_transient(exc: TransportError) -> bool:
    """A timeout, a gateway 5xx, or a plain TransportError caused by a connection-level failure."""
    if isinstance(exc, _NEVER_RETRIED):
        return False
    if isinstance(exc, TransportTimeoutError):
        return True
    if isinstance(exc, ServerError):
        return exc.status_code >= 500
    return type(exc) is TransportError and isinstance(exc.__cause__, _CONNECTION_CAUSES)


def _fetch_page(
    fetch: PfmFetch,
    wfo: str,
    cursor: dt.datetime,
    limit: int,
    report: LegReport,
    sleep: Callable[[float], None],
    window_ok: Callable[[int], bool],
    clock_ns: Callable[[], int],
) -> tuple[str | None, int]:
    """One page as ``(text, limit used)``; ``text`` None means the leg must stop (status set).

    A throttle, timeout or 5xx is retried with backoff (a 403 never is). An oversize body
    retries the same ``cursor`` with the
    limit halved (each retry is a paced, budgeted request); a single-product page that is still
    oversize marks the station ``oversize_product``.
    """
    attempt = 0
    transient = 0
    while True:
        if not window_ok(clock_ns()):
            report.status = "paused_launch_window"
            return None, limit
        try:
            text = fetch(wfo, cursor, limit)
        except RequestBudgetExceededError:
            report.status = "budget_exhausted"
            return None, limit
        except OversizeBodyError as exc:
            report.requests += 1
            if limit <= 1:
                report.status = "oversize_product"
                report.error = f"{type(exc).__name__}: {exc}"
                _alert(
                    f"PFM{wfo} sdate={_stamp(cursor)}: one product exceeds the body cap; "
                    "station stops"
                )
                return None, limit
            limit //= 2
            continue
        except (TransportTimeoutError, ServerError) as exc:
            if not _is_transient(exc):
                raise
            # Each failed attempt spent budget and pacing; the retry re-enters this loop, so it
            # is paced, budgeted and window-guarded again. Exhausted: the station boundary
            # records ``error`` with the resume date.
            report.requests += 1
            if transient == len(TRANSIENT_BACKOFF_S):
                raise
            sleep(TRANSIENT_BACKOFF_S[transient])
            transient += 1
            continue
        except ForbiddenError:
            report.requests += 1
            report.status = "forbidden"
            _alert(
                f"IEM 403 (abuse block) for PFM{wfo} at sdate={_stamp(cursor)}; stopping every leg"
            )
            return None, limit
        except RateLimitedError:
            report.requests += 1
            if attempt == len(THROTTLE_BACKOFF_S):
                report.status = "throttled"
                _alert(
                    f"IEM throttle persisted for PFM{wfo} at sdate={_stamp(cursor)}; "
                    "stopping the leg"
                )
                return None, limit
            sleep(THROTTLE_BACKOFF_S[attempt])
            attempt += 1
            continue
        except TransportError as exc:
            # Only a connection-level cause (e.g. "Server disconnected") is transient; every other
            # TransportError subclass reaching here (decode, redirect, host, encoding) is not.
            if not _is_transient(exc):
                raise
            report.requests += 1
            if transient == len(TRANSIENT_BACKOFF_S):
                raise
            sleep(TRANSIENT_BACKOFF_S[transient])
            transient += 1
            continue
        report.requests += 1
        return text, limit


def _append(
    store: UsSourceRevisionStore,
    report: LegReport,
    sleep: Callable[[float], None],
    *,
    station: str,
    run_ts_ns: int,
    wfo: str,
    payload: bytes,
    on_refused: Callable[[str], None] | None = None,
) -> bool:
    """Append one raw revision; False when the unit lock stayed busy past the retries."""
    for attempt in range(BUSY_RETRIES + 1):
        try:
            result = store.append_if_new(
                source=US_PFM_AFOS_SOURCE,
                station=station,
                run_ts_ns=run_ts_ns,
                model=wfo,
                payload=payload,
            )
        except RevisionStoreBusyError:
            if attempt == BUSY_RETRIES:
                return False
            sleep(BUSY_WAIT_S)
            continue
        except RevisionPayloadRefusedError as exc:  # an expected refusal of this payload
            _count(report, type(exc).__name__)
            if on_refused is not None:
                on_refused(type(exc).__name__)
            return True
        except RevisionStoreError as exc:  # integrity or other store trouble: not a refusal
            name = type(exc).__name__
            report.store_errors[name] = report.store_errors.get(name, 0) + 1
            return True
        if result.outcome is AppendOutcome.APPENDED:
            report.appended += 1
        elif result.outcome is AppendOutcome.UNCHANGED:
            report.unchanged += 1
        else:
            report.quarantined += 1
        return True
    return False  # pragma: no cover


def _count(report: LegReport, reason: str) -> None:
    report.refused[reason] = report.refused.get(reason, 0) + 1


def _place_by_body(
    header: tuple[str, int, int, int],
    body: dt.datetime,
    previous: dt.datetime,
    floor: dt.datetime,
) -> dt.datetime:
    """The WMO instant nearest the body's full local date, if the two agree and are plausible."""
    _cccc, day, hour, minute = header
    issued: dt.datetime | None = wmo_instant_near(day, hour, minute, body)
    if issued is None or abs(issued - body) > BODY_WMO_TOLERANCE:
        raise UnplaceableHeaderError(
            f"WMO {day:02d}{hour:02d}{minute:02d} disagrees with the body time {body.isoformat()}",
            "header_body_mismatch",
        )
    if issued < floor or issued - previous > dt.timedelta(days=MAX_GAP_DAYS):
        raise UnplaceableHeaderError(
            f"body time {issued.isoformat()} is outside the window around {previous.isoformat()}"
        )
    return issued


def _place_by_cursor(header: tuple[str, int, int, int], previous: dt.datetime) -> dt.datetime:
    """Cursor-relative placement for a product with no usable body time (day, hour, minute only)."""
    try:
        (issued,) = resolve_issuance_sequence([(header[1], header[2], header[3])], previous.date())
    except ValueError as exc:
        raise UnplaceableHeaderError(str(exc)) from exc
    rolled = (issued.year, issued.month) != (previous.year, previous.month)
    if rolled and issued - previous > dt.timedelta(days=MAX_ROLLOVER_GAP_DAYS):
        raise UnplaceableHeaderError(
            f"header {issued.isoformat()} is a {(issued - previous).days} day month "
            f"rollover after {previous.isoformat()}; refusing to place it"
        )
    return issued


def _place(
    products: Sequence[str],
    cursor: dt.date,
    report: LegReport,
    on_refused: Callable[[str, str], None] | None = None,
) -> list[tuple[str, dt.datetime | None]]:
    """Pair each product with its resolved issuance time; an unplaceable one is refused alone.

    The body's full local date ("615 PM CST Thu Dec 31 2020"), cross-checked against the WMO
    ``DDHHMM``, places a product when present. Otherwise the WMO header is placed relative to the
    latest instant placed so far (the cursor's midnight at first): same month unless the day went
    backwards, and a month "rollover" over ``MAX_ROLLOVER_GAP_DAYS`` is refused rather than
    placed a month ahead. A refused product is counted (and passed to ``on_refused(reason,
    product)``); the others on the page are still placed.
    """
    floor = dt.datetime(cursor.year, cursor.month, cursor.day, tzinfo=dt.UTC) - dt.timedelta(days=1)
    previous = floor + dt.timedelta(days=1)
    paired: list[tuple[str, dt.datetime | None]] = []
    for product in products:
        header = wmo_header_fields(product)
        if header is None:
            _refuse_product(report, on_refused, "no_wmo_header", product)
            paired.append((product, None))
            continue
        try:
            body = body_issuance_utc(product)
            issued = (
                _place_by_cursor(header, previous)
                if body is None
                else _place_by_body(header, body, previous, floor)
            )
        except (UnplaceableHeaderError, BodyTimeError) as exc:
            _refuse_product(report, on_refused, exc.reason, product)
            paired.append((product, None))
            continue
        previous = max(previous, issued)
        paired.append((product, issued))
    return paired


def _refuse_product(
    report: LegReport,
    on_refused: Callable[[str, str], None] | None,
    reason: str,
    product: str,
) -> None:
    _count(report, reason)
    if on_refused is not None:
        on_refused(reason, product)


def _ingest_page(
    paired: Sequence[tuple[str, dt.datetime | None]],
    *,
    station: str,
    wfo: str,
    end: dt.date,
    store: UsSourceRevisionStore,
    report: LegReport,
    sleep: Callable[[float], None],
    quarantine: RefusalQuarantine | None = None,
    sdate: dt.datetime | None = None,
) -> tuple[dt.datetime | None, bool, bool]:
    """Store a page; returns ``(last issuance seen, past_end, busy)``."""
    last: dt.datetime | None = None

    for product, issued in paired:
        if issued is None:
            continue
        if issued.date() > end:
            return last, True, False
        last = issued
        report.products_seen += 1
        raw = product.encode("utf-8")

        def keep(reason: str, *, _raw: bytes = raw, _issued: dt.datetime = issued) -> None:
            if quarantine is not None and sdate is not None:
                quarantine.record(
                    reason=reason, station=station, wfo=wfo, sdate=sdate, issued=_issued, raw=_raw
                )

        try:
            parse_pfm_product(raw, station=station, reference_time=issued + dt.timedelta(seconds=1))
        except PfmParseError as exc:
            reason = exc.reason or _REFUSE_REASON_FALLBACK
            _count(report, reason)
            keep(reason)
            continue
        run_ts_ns = int(issued.timestamp()) * _NS
        if not _append(
            store,
            report,
            sleep,
            station=station,
            run_ts_ns=run_ts_ns,
            wfo=wfo,
            payload=raw,
            on_refused=keep,
        ):
            return last, False, True
    return last, False, False


_coverage_batch_unavailable_warned = False


def _warn_coverage_batch_unavailable() -> None:
    """One warning per process. Test doubles that only implement append stay usable."""
    global _coverage_batch_unavailable_warned
    if _coverage_batch_unavailable_warned:
        return
    _coverage_batch_unavailable_warned = True
    logging.getLogger("us_source_backfill").warning(
        "coverage batching unavailable; falling back to per-append manifest writes"
    )


def _coverage_batch(store: object) -> contextlib.AbstractContextManager[Any]:
    batch = getattr(store, "coverage_batch", None)
    if not callable(batch):
        _warn_coverage_batch_unavailable()
        return contextlib.nullcontext(None)
    return cast("contextlib.AbstractContextManager[Any]", batch())


def _record_coverage(report: LegReport, outcome: Any) -> None:
    if outcome is None:
        return
    report.coverage_flushed = int(outcome.flushed)
    report.coverage_dropped = len(outcome.dropped)
    report.coverage_stranded_sources = tuple(outcome.stranded)
    report.coverage_torn_journal_lines = int(outcome.torn_journal_lines)
    uncovered = report.coverage_dropped or report.coverage_stranded_sources
    if report.status == "complete" and uncovered:
        report.status = "coverage_incomplete"


def run_pfm_leg(
    *,
    station: str,
    start: dt.date,
    end: dt.date,
    fetch: PfmFetch,
    store: UsSourceRevisionStore,
    clock_ns: Callable[[], int],
    window_ok: Callable[[int], bool],
    sleep: Callable[[float], None],
    page_limit: int = DEFAULT_PAGE_LIMIT,
    quarantine: RefusalQuarantine | None = None,
) -> LegReport:
    """Backfill one station's WFO from ``start`` to ``end`` inclusive, ascending by issuance.

    Never raises for a leg-local fault: an unexpected exception becomes status ``error``.
    """
    wfo = PFM_POINTS[station].wfo
    report = LegReport(station=station, wfo=wfo)
    truncated: list[dt.date] = []
    cursor = [dt.datetime(start.year, start.month, start.day, tzinfo=dt.UTC)]  # mutable: error path
    outcome: Any = None
    try:
        # One manifest rewrite for the leg (and every COVERAGE_FLUSH_EVERY products),
        # including when the leg raises. The journal, not a signal handler, is what
        # makes SIGTERM safe. Doubles that only implement append_if_new stay on the
        # per-append path and log once that batching is unavailable.
        with _coverage_batch(store) as outcome:
            _page_loop(
                report, truncated, cursor, wfo, station, end, fetch, store, clock_ns, window_ok,
                sleep, page_limit, quarantine,
            )  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - the station boundary: record, never crash the run
        report.status = "error"
        report.error = f"{type(exc).__name__}: {exc}"
        report.resume_sdate = cursor[0].date()
        _alert(f"{wfo} sdate={_stamp(cursor[0])}: unexpected {report.error}; this station stops")
    report.truncated_days = tuple(truncated)
    if report.store_errors and report.status == "complete":
        report.status = "degraded"
    _record_coverage(report, outcome)
    return report


_PLACEMENT_REASONS: Final[tuple[str, ...]] = ("unplaceable_header", "header_body_mismatch")


def _placement_refusals(report: LegReport) -> int:
    return sum(report.refused.get(reason, 0) for reason in _PLACEMENT_REASONS)


def _page_loop(
    report: LegReport,
    truncated: list[dt.date],
    cursor_box: list[dt.datetime],
    wfo: str,
    station: str,
    end: dt.date,
    fetch: PfmFetch,
    store: UsSourceRevisionStore,
    clock_ns: Callable[[], int],
    window_ok: Callable[[int], bool],
    sleep: Callable[[float], None],
    page_limit: int,
    quarantine: RefusalQuarantine | None = None,
) -> None:
    while cursor_box[0].date() <= end:
        cursor = cursor_box[0]
        text, page_limit = _fetch_page(
            fetch, wfo, cursor, page_limit, report, sleep, window_ok, clock_ns
        )
        if text is None:
            report.resume_sdate = cursor.date()
            return
        products = split_raw_products(text)
        if not products:
            return
        refused_before = _placement_refusals(report)

        def on_refused(reason: str, product: str, *, _cursor: dt.datetime = cursor) -> None:
            if quarantine is not None:
                quarantine.record(
                    reason=reason,
                    station=station,
                    wfo=wfo,
                    sdate=_cursor,
                    issued=None,
                    raw=product.encode("utf-8"),
                )

        paired = _place(products, cursor.date(), report, on_refused)
        if _placement_refusals(report) > refused_before and all(i is None for _p, i in paired):
            _alert(
                f"{wfo} sdate={_stamp(cursor)}: no product on the page could be placed; "
                f"this station stops, resume at {_stamp(cursor)}"
            )
            report.status, report.resume_sdate = "unplaceable_header", cursor.date()
            return
        last, past_end, busy = _ingest_page(
            paired,
            station=station,
            wfo=wfo,
            end=end,
            store=store,
            report=report,
            sleep=sleep,
            quarantine=quarantine,
            sdate=cursor,
        )
        if busy:
            report.status, report.resume_sdate = "store_busy", cursor.date()
            return
        if past_end or len(products) < page_limit or last is None:
            return
        # Continue from the last issuance INSTANT (inclusive, so the overlap dedupes in the store):
        # a full page inside one day then loses nothing. Only a page that cannot advance at all (a
        # whole page in one minute) skips that minute, and says so.
        following = last
        if following <= cursor:
            truncated.append(cursor.date())
            following = cursor + dt.timedelta(minutes=1)
        cursor_box[0] = following


# -------------------------------------------------------------------- transport


def make_pfm_fetch(
    *,
    request_budget: int,
    user_agent: str,
    clock_ns: Callable[[], int],
    sleeper: Callable[[float], Any] | None = None,
    check_proxy_env: bool = True,
) -> PfmFetch:
    """The AFOS fetch: paced IEM transport, A0-R1 spacing, a hard shared request budget."""
    transport = PacedIemTransport(
        budget=RequestBudget(limit=request_budget),
        pacer=IemPacer(
            clock=clock_ns, sleeper=sleeper, min_interval_ns=IEM_AFOS_LAV_MIN_INTERVAL_NS
        ),
        user_agent=user_agent,
        clock=clock_ns,
        max_body_bytes=IEM_AFOS_PFM_MAX_BODY_BYTES,
        accept="text/plain",
        check_proxy_env=check_proxy_env,
    )

    def fetch(wfo: str, sdate: dt.date, limit: int) -> str:
        result = asyncio.run(transport.fetch_afos_pfm(wfo, sdate=sdate, limit=limit))
        return result.text or ""

    return fetch


# ------------------------------------------------------------------------ plans


def _last_complete_year(end: dt.date) -> int:
    return end.year if (end.month, end.day) == (12, 31) else end.year - 1


def _gfs_years(start: dt.date, end: dt.date) -> list[int]:
    return list(range(max(FIRST_YEAR, start.year), _last_complete_year(end) + 1))


def _gfs_argv(
    stations: Sequence[str], years: Sequence[int], budget: int, cache_root: Path | None
) -> list[str]:
    argv = [
        "--stations", *stations,
        "--first-year", str(years[0]),
        "--through-year", str(years[-1]),
        "--model", "GFS",
        "--apply",
        "--request-budget", str(budget),
    ]  # fmt: skip
    if cache_root is not None:
        argv += ["--cache-root", str(cache_root)]
    return argv


def _pfm_plan(
    stations: Sequence[str], start: dt.date, end: dt.date, budget: int | None
) -> dict[str, Any]:
    days = (end - start).days + 1
    # each page re-reads the previous page's last product (the instant cursor is inclusive)
    per_wfo = math.ceil(days * PLANNING_ISSUANCES_PER_DAY / (DEFAULT_PAGE_LIMIT - 1))
    wfos = {
        PFM_POINTS[s].wfo: {
            "station": s,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "days": days,
            "estimated_requests": per_wfo,
        }
        for s in stations
    }
    total = per_wfo * len(wfos)
    pacing_s = IEM_AFOS_LAV_MIN_INTERVAL_NS / _NS
    return {
        "wfos": wfos,
        "pacing_s": pacing_s,
        "page_limit": DEFAULT_PAGE_LIMIT,
        "planning_issuances_per_day": PLANNING_ISSUANCES_PER_DAY,
        "estimated_requests": total,
        "estimated_seconds": total * pacing_s,
        "request_budget": budget,
        "fits_budget": None if budget is None else total <= budget,
    }


def _gfs_plan(stations: Sequence[str], years: Sequence[int]) -> dict[str, Any]:
    return {
        "model": "GFS",
        "stations": list(stations),
        "years": list(years),
        "estimated_requests": len(stations) * len(years),
        "delegates_to": "scripts/archive/iem_mos_backfill.py",
    }


# ------------------------------------------------------------------------- main


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, default=None)
    parser.add_argument("--legs", nargs="+", choices=("pfm", "gfs"), default=["pfm", "gfs"])
    parser.add_argument("--stations", nargs="+", default=list(US_SOURCE_STATIONS))
    parser.add_argument(
        "--start-date", type=dt.date.fromisoformat, default=dt.date(FIRST_YEAR, 1, 1)
    )
    parser.add_argument("--end-date", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--request-budget", type=int, default=None)
    parser.add_argument("--gfs-request-budget", type=int, default=None)
    parser.add_argument("--max-runtime-s", type=int, default=DEFAULT_MAX_RUNTIME_S)
    parser.add_argument("--mos-cache-root", type=Path, default=None)
    parser.add_argument("--report-json", type=Path, default=None)
    parser.add_argument(
        "--quarantine-dir",
        type=Path,
        default=None,
        help="write every refused raw PFM product plus a refusals.jsonl line here (default off)",
    )
    parser.add_argument(
        "--reingest-quarantine",
        type=Path,
        default=None,
        help="OFFLINE: replay a --quarantine-dir through the current parser into --archive-root "
        "(--dry-run counts only; --apply appends; idempotent by the store's sha dedupe)",
    )
    parser.add_argument(
        "--reingest-reasons",
        nargs="+",
        default=None,
        help="with --reingest-quarantine: only replay lines refused for these reasons",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args(list(argv))


def _refuse(message: str) -> int:
    sys.stderr.write(f"REFUSED: {message}\n")
    return _EXIT_REFUSED


def _archive_root_problem(root: Path) -> str | None:
    """Refuse a holdout directory, and the live data root except its sanctioned archive dir."""
    resolved = root.resolve()
    if any("holdout" in part.lower() for part in resolved.parts):
        return f"--archive-root {resolved} sits in a holdout directory (sealed)"
    live = LIVE_DATA_ROOT.resolve()
    if resolved != live and live not in resolved.parents:
        return None
    sanctioned = live / US_SOURCE_ARCHIVE_DIR
    if resolved == sanctioned or sanctioned in resolved.parents:
        return None
    return (
        f"--archive-root {resolved} is under the live data root {live}; only "
        f"{sanctioned} (the collector archive) may be written from here"
    )


def _quarantine_dir_problem(root: Path, archive_root: Path | None) -> str | None:
    """Refuse a quarantine dir in a holdout, the live data root, or the archive being written."""
    resolved = root.resolve()
    if any("holdout" in part.lower() for part in resolved.parts):
        return f"--quarantine-dir {resolved} sits in a holdout directory (sealed)"
    live = LIVE_DATA_ROOT.resolve()
    if resolved == live or live in resolved.parents:
        return f"--quarantine-dir {resolved} is under the live data root {live}"
    if archive_root is not None:
        archive = archive_root.resolve()
        if resolved == archive or archive in resolved.parents:
            return f"--quarantine-dir {resolved} is inside --archive-root {archive}"
    return None


def _validate(args: argparse.Namespace) -> str | None:
    """A refusal message, or None when the invocation is coherent."""
    if args.dry_run == args.apply:
        return "exactly one of --dry-run and --apply is required"
    if args.start_date < dt.date(FIRST_YEAR, 1, 1):
        return f"--start-date may not precede {FIRST_YEAR}-01-01 (PFM format break, NBM versions)"
    unknown = [s for s in args.stations if s not in US_SOURCE_STATIONS]
    if unknown:
        return f"station(s) {unknown} are outside the closed set {list(US_SOURCE_STATIONS)}"
    if "pfm" in args.legs and args.archive_root is None:
        return "--archive-root is required for the pfm leg"
    if args.archive_root is not None:
        problem = _archive_root_problem(args.archive_root)
        if problem is not None:
            return problem
    if args.quarantine_dir is not None:
        problem = _quarantine_dir_problem(args.quarantine_dir, args.archive_root)
        if problem is not None:
            return problem
    if args.apply and os.environ.get(LIVE_ENV_VAR) != "1":
        return f"{LIVE_ENV_VAR}=1 is required before any request may be dispatched"
    if args.apply and "pfm" in args.legs and not args.request_budget:
        return "--request-budget is required for a real pfm run"
    if args.request_budget is not None and args.request_budget < 1:
        return "--request-budget must be a positive request count"
    return None


def _write_report(path: Path | None, report: dict[str, Any]) -> None:
    text = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    sys.stdout.write(text)


def _default_gfs_runner(argv: Sequence[str]) -> int:  # pragma: no cover - live delegation
    from iem_mos_backfill import main as mos_main  # type: ignore[import-not-found]

    return int(mos_main(list(argv)))


def _reingest(
    args: argparse.Namespace, clock: Callable[[], int], sleep: Callable[[float], None]
) -> int:
    """The offline ``--reingest-quarantine`` mode: no network, no request budget, no live env."""
    from us_source_pfm_reingest import reingest_quarantine  # type: ignore[import-not-found]

    if args.dry_run == args.apply:
        return _refuse("exactly one of --dry-run and --apply is required")
    if args.archive_root is None:
        return _refuse("--archive-root is required with --reingest-quarantine")
    problem = _archive_root_problem(args.archive_root)
    if problem is not None:
        return _refuse(problem)
    if any("holdout" in part.lower() for part in args.reingest_quarantine.resolve().parts):
        return _refuse("--reingest-quarantine sits in a holdout directory (sealed)")
    store = UsSourceRevisionStore(args.archive_root, _StoreClock(clock)) if args.apply else None
    reasons = frozenset(args.reingest_reasons) if args.reingest_reasons else None
    try:
        report = reingest_quarantine(
            args.reingest_quarantine, store, only_reasons=reasons, sleep=sleep
        )
    except FileNotFoundError as exc:
        return _refuse(str(exc))
    _write_report(args.report_json, report)
    return (
        0
        if report["complete"] and not any(leg["store_errors"] for leg in report["legs"])
        else _EXIT_INCOMPLETE
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    clock: Callable[[], int] = time.time_ns,
    sleep: Callable[[float], None] = time.sleep,
    pfm_fetch_factory: Callable[..., PfmFetch] = make_pfm_fetch,
    gfs_runner: Callable[[Sequence[str]], int] = _default_gfs_runner,
) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    if args.reingest_quarantine is not None:
        return _reingest(args, clock, sleep)
    problem = _validate(args)
    if problem is not None:
        return _refuse(problem)
    end = args.end_date or dt.datetime.fromtimestamp(clock() / _NS, tz=dt.UTC).date()
    stations: list[str] = list(args.stations)
    years = _gfs_years(args.start_date, end)
    report: dict[str, Any] = {
        "mode": "dry_run" if args.dry_run else "apply",
        "inputs": {
            "start": args.start_date.isoformat(),
            "end": end.isoformat(),
            "stations": stations,
            "legs": list(args.legs),
        },
        "launch_window_utc": "16:30-17:10",
    }
    if "pfm" in args.legs:
        report["pfm"] = _pfm_plan(stations, args.start_date, end, args.request_budget)
    if "gfs" in args.legs:
        report["gfs"] = _gfs_plan(stations, years)
    if args.dry_run:
        _write_report(args.report_json, report)
        return 0
    code = _EXIT_INCOMPLETE
    try:
        code = _apply(
            args, report, stations, years, end, clock, sleep, pfm_fetch_factory, gfs_runner
        )
    except Exception as exc:  # noqa: BLE001 - the report is the run's evidence; never lose it
        report["error"] = f"{type(exc).__name__}: {exc}"
        _alert(f"run aborted by unexpected {report['error']}")
    finally:
        _write_report(args.report_json, report)
    return code


def _seconds_to_window(now_ns: int) -> int:
    """Whole seconds from ``now_ns`` to the next 16:30Z window start (0 inside the window)."""
    (start_h, start_m), (end_h, end_m) = LAUNCH_WINDOW_UTC
    second = now_ns // _NS
    of_day = second % 86_400
    start_s, end_s = start_h * 3600 + start_m * 60, end_h * 3600 + end_m * 60
    if start_s <= of_day < end_s:
        return 0
    return (start_s - of_day) % 86_400


def _run_gfs(
    args: argparse.Namespace,
    report: dict[str, Any],
    stations: Sequence[str],
    years: Sequence[int],
    clock: Callable[[], int],
    gfs_runner: Callable[[Sequence[str]], int],
    stopped: dict[str, Any] | None,
) -> bool:
    """Run (or refuse) the delegated GFS leg; True when it leaves the run incomplete.

    ``iem_mos_backfill`` has no deadline hook, so the leg is bounded by its request budget and by
    a start-time check: it only starts when ``--max-runtime-s`` still fits before the next
    16:30Z window, evaluated NOW (after any PFM leg) and recorded in the report.
    """
    gfs = report["gfs"]
    if stopped is not None:
        gfs["status"] = "skipped_after_stop"
        return True
    if not years:
        gfs["status"] = "nothing_to_do"
        return False
    now = clock()
    gfs.update(max_runtime_s=args.max_runtime_s, seconds_to_window=_seconds_to_window(now))
    if not launch_window_guard(now, 0, args.max_runtime_s):
        gfs["status"] = "refused_launch_window"
        _alert(f"GFS leg not started: {args.max_runtime_s} s would meet the launch window")
        return True
    budget = args.gfs_request_budget or len(stations) * len(years)
    try:
        code = gfs_runner(_gfs_argv(stations, years, budget, args.mos_cache_root))
    except Exception as exc:  # noqa: BLE001 - recorded, so the PFM results still reach the report
        gfs.update(status="error", error=f"{type(exc).__name__}: {exc}")
        _alert(f"GFS leg raised {gfs['error']}")
        return True
    gfs.update(status="complete" if code == 0 else "failed", exit_code=code)
    return code != 0


def _apply(
    args: argparse.Namespace,
    report: dict[str, Any],
    stations: Sequence[str],
    years: Sequence[int],
    end: dt.date,
    clock: Callable[[], int],
    sleep: Callable[[float], None],
    pfm_fetch_factory: Callable[..., PfmFetch],
    gfs_runner: Callable[[Sequence[str]], int],
) -> int:
    if "gfs" in args.legs and years and not launch_window_guard(clock(), 0, args.max_runtime_s):
        return _refuse(
            f"a {args.max_runtime_s} s run starting now could meet the 16:30-17:10Z launch window"
        )
    incomplete = False
    stopped: dict[str, Any] | None = None
    if "pfm" in args.legs:
        user_agent = os.environ.get(USER_AGENT_ENV_VAR, DEFAULT_USER_AGENT)
        fetch = pfm_fetch_factory(
            request_budget=args.request_budget, user_agent=user_agent, clock_ns=clock
        )
        store = UsSourceRevisionStore(args.archive_root, _StoreClock(clock))
        quarantine = (
            RefusalQuarantine(args.quarantine_dir) if args.quarantine_dir is not None else None
        )
        legs: list[LegReport] = []
        for index, station in enumerate(stations):
            leg = run_pfm_leg(
                station=station,
                start=args.start_date,
                end=end,
                fetch=fetch,
                store=store,
                clock_ns=clock,
                window_ok=make_window_guard(),
                sleep=sleep,
                quarantine=quarantine,
            )
            legs.append(leg)
            if leg.status in STOP_ALL_STATUSES:
                stopped = {"reason": leg.status, "skipped_stations": list(stations[index + 1 :])}
                break
        report["pfm"]["legs"] = [leg.to_dict() for leg in legs]
        if stopped is not None:
            report["pfm"]["stopped"] = stopped
        incomplete = stopped is not None or any(leg.status != "complete" for leg in legs)
    if "gfs" in args.legs:
        incomplete = (
            _run_gfs(args, report, stations, years, clock, gfs_runner, stopped) or incomplete
        )
    return _EXIT_INCOMPLETE if incomplete else 0


if __name__ == "__main__":  # pragma: no cover - script entry
    raise SystemExit(main())
