#!/usr/bin/env python
"""IEM 1-minute ASOS backfill into the durable archive cache (FC-0a-2 / WP-3).

WHAT THIS IS
------------
The operator-run job that populates the Stage-0b fit corpus: 1-minute ASOS
observations for KLAX/KMDW/KMIA/KSFO from 2021 to the last COMPLETE year,
one request per station-year, into `ArchiveCache`.

WHAT IT IS NOT
--------------
It is not a cache. `breezy.persistence.archive_cache.ArchiveCache` already
owns cache keys, content-addressed payloads, sha256 digests, the
`coverage.json` manifest, atomic writes, the non-blocking writer lock and the
root-disjointness assertion. This module ORCHESTRATES that cache and adds
nothing of its own to it: no digesting, no manifest handling, no locking.

L-46. The IEM transport stays under `scripts/`. This module names no host: the
paced, budgeted, IEM-only transport (`IemPacer`, `PacedIemTransport`) is
imported from its sibling `scripts/venue/iem_mos_probe_transport.py`, whose
docstring already reserves those names for "the 1-min ASOS product".

L-13. An extremum statistic is not comparable across sampling cadences. The
cadence is therefore never implicit here: it is a closed set, each cadence maps
to its OWN cache product (so two cadences can never share a cache slot, a
payload file, or a manifest entry), the requested cadence is the `sample` the
URL carries, and a run that would mix cadences is REFUSED
(:class:`CadenceMixError`) rather than silently averaged. Downsampling the
dense source, where a comparison needs it, is the consumer's explicit step --
this job never performs it implicitly.

MEMORY. A station-year of 1-minute ASOS is tens of megabytes. The loop is
process-then-discard: exactly one station-year payload is alive at a time, and
what survives the iteration is statistics (rows, bytes, sha256), never bytes.

PARTIAL WRITES. Nothing half-written may ever look like coverage. The payload
is VALIDATED before the cache is allowed to commit it, so an empty body, an
HTML error page or a truncated response is a FAILURE rather than a permanent
zero-row "covered" entry; and because the cache writes the payload atomically
and only then the manifest, a crash anywhere in between leaves a manifest that
claims nothing it does not have -- the next run re-fetches that station-year.

URL GRAMMAR. The `asos1min.py` query grammar below is UNVERIFIED against the
live service: no request has been issued from this module. The first real run
is the verification, which is why `--dry-run` exists and why a real run needs
both `BREEZY_LIVE=1` and `--apply`.

Usage
-----
    scripts/archive/iem_asos1min_backfill.py --dry-run
    BREEZY_LIVE=1 BREEZY_USER_AGENT='breezy/1.0 (+mailto:you@example.com)' \
        scripts/archive/iem_asos1min_backfill.py --apply

Exit codes: 0 complete, 1 one or more station-years failed, 2 refusal
(unlock/argument/root policy), 3 aborted (request budget or another writer).
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Callable, Coroutine, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final
from urllib.parse import urlencode

from breezy.ingest.probe_transport import (
    RequestBudget,
    RequestBudgetExceededError,
)
from breezy.persistence.archive_cache import (
    ArchiveCache,
    ArchiveCacheConcurrentWriterError,
    ArchiveCachePathError,
    ArchiveRequest,
    assert_cache_root_disjoint_from_backup,
    count_rows,
)
from breezy.persistence.archive_request import IEM_ASOS_1MIN_SOURCE, iem_asos_1min_request

_VENUE_SCRIPTS = Path(__file__).resolve().parents[1] / "venue"
if str(_VENUE_SCRIPTS) not in sys.path:  # pragma: no cover - bootstrap
    sys.path.insert(0, str(_VENUE_SCRIPTS))

# Imported after the sys.path bootstrap above; the shared, paced IEM transport
# lives under scripts/ and stays there (L-46).
from iem_mos_probe_transport import (
    IEM_ALLOWED_HOSTS,
    IEM_BASE_URL,
    IEM_MIN_INTERVAL_NS,
    IemPacer,
    PacedIemTransport,
)

__all__ = [
    "ASOS1MIN_MIN_INTERVAL_NS",
    "CADENCE_PRODUCTS",
    "DEFAULT_CADENCE",
    "DURABLE_ROOT_TAIL",
    "FIRST_YEAR",
    "IEM_ASOS1MIN_PATH",
    "STATIONS",
    "Asos1MinTransport",
    "BackfillReport",
    "CacheRootPolicyError",
    "CadenceMixError",
    "DryRunFetchAttemptedError",
    "EmptyPayloadError",
    "StationYear",
    "StationYearOutcome",
    "assert_durable_cache_root",
    "build_pacer",
    "build_plan",
    "default_cache_root",
    "last_complete_year",
    "main",
    "prepare_cache_root",
    "refuse_cadence_mix",
    "render_summary",
    "request_for",
    "run_backfill",
    "validate_payload",
]

#: The four stations the 0b fit needs. A closed set: an unlisted station is
#: refused, never sanitised into a request.
STATIONS: Final[tuple[str, ...]] = ("KLAX", "KMDW", "KMIA", "KSFO")
FIRST_YEAR: Final[int] = 2021

#: L-13. One product per cadence, so a cache key, a payload file and a manifest
#: entry can only ever hold ONE cadence. `asos-1min` is the product string the
#: shared `iem_asos_1min_request` factory already uses; adding a cadence here
#: adds a disjoint cache slot, never a second meaning for an existing one.
CADENCE_PRODUCTS: Final[MappingProxyType[str, str]] = MappingProxyType(
    {
        "1min": "asos-1min",
        "5min": "asos-5min",
    }
)
DEFAULT_CADENCE: Final[str] = "1min"

#: Politeness to a public, NOAA-adjacent service: at most one request a second,
#: charged by a named pacer inside the transport's `_fetch`, never by a bare
#: `sleep` sprinkled through a loop.
ASOS1MIN_MIN_INTERVAL_NS: Final[int] = IEM_MIN_INTERVAL_NS

IEM_ASOS1MIN_PATH: Final[str] = "/cgi-bin/request/asos1min.py"
ASOS1MIN_ACCEPT: Final[str] = "text/csv"
#: A station-year of 1-minute ASOS is ~0.5M rows. 256 MiB is a ceiling that
#: refuses a runaway body while leaving a real year comfortable.
ASOS1MIN_MAX_BODY_BYTES: Final[int] = 256 * 1024 * 1024
#: The service generates a year of 1-minute rows on demand; the default 10-20s
#: read timeout is far too short for that.
ASOS1MIN_READ_TIMEOUT_SECONDS: Final[float] = 900.0
ASOS1MIN_VARS: Final[tuple[str, ...]] = ("tmpf", "dwpf")

LIVE_ENV_VAR: Final[str] = "BREEZY_LIVE"
USER_AGENT_ENV_VAR: Final[str] = "BREEZY_USER_AGENT"

#: The durable layout, as a path TAIL rather than a prefix blocklist: it pins
#: the documented location (`~/.local/share/breezy/archive/iem-asos-1min`) and
#: in doing so refuses `/tmp`, `/var/tmp` and `/dev/shm` by construction.
DURABLE_ROOT_TAIL: Final[tuple[str, ...]] = (
    ".local",
    "share",
    "breezy",
    "archive",
    IEM_ASOS_1MIN_SOURCE,
)

_NANOSECONDS_PER_SECOND: Final[int] = 1_000_000_000
_STATION_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A[A-Z]{4}\Z")
_STS_ETS_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}Z\Z")

STATUS_FETCHED: Final[str] = "FETCHED"
STATUS_SKIPPED: Final[str] = "SKIPPED"
STATUS_WOULD_FETCH: Final[str] = "WOULD_FETCH"
STATUS_FAILED: Final[str] = "FAILED"


class CacheRootPolicyError(ArchiveCachePathError):
    """Raised when a cache root is not the durable archive location."""


class CadenceMixError(ValueError):
    """Raised when one run would mix sampling cadences (L-13)."""


class EmptyPayloadError(ValueError):
    """Raised when a response carries no usable observation rows.

    A zero-row body is NOT coverage. Raising here, inside the fetch the cache
    calls, is what keeps the cache from committing a permanent "covered"
    manifest entry for a station-year that in fact returned nothing.
    """


class DryRunFetchAttemptedError(RuntimeError):
    """Raised if a dry run ever reaches a fetch. A dry run makes no request."""


@dataclass(frozen=True, slots=True)
class StationYear:
    """One unit of work, and one unit of coverage."""

    station: str
    year: int
    cadence: str = DEFAULT_CADENCE

    @property
    def label(self) -> str:
        return f"{self.station} {self.year}"


@dataclass(frozen=True, slots=True)
class StationYearOutcome:
    """What a station-year did. Statistics only -- never a payload."""

    station: str
    year: int
    cadence: str
    status: str
    rows: int
    bytes: int
    sha256: str
    detail: str

    @property
    def label(self) -> str:
        return f"{self.station} {self.year}"


@dataclass(frozen=True, slots=True)
class BackfillReport:
    """The whole run, in the shape the operator has to act on."""

    outcomes: tuple[StationYearOutcome, ...]
    fetched: int
    skipped: int
    would_fetch: int
    failed: tuple[StationYearOutcome, ...]
    cadence: str
    dry_run: bool
    cache_root: Path | None = None
    requests_spent: int | None = None

    @property
    def rows(self) -> int:
        return sum(outcome.rows for outcome in self.outcomes)


# ---------------------------------------------------------------------------
# Root policy. Both checks run BEFORE any mkdir.
# ---------------------------------------------------------------------------


def default_cache_root() -> Path:
    """The durable cache root, resolved from `$HOME` at CALL time.

    Equal to `breezy.persistence.archive_layout.DEFAULT_IEM_CACHE_DIR`; it is
    rebuilt here rather than imported so a test can relocate `$HOME` without
    the value having been frozen at import.
    """
    return Path.home().joinpath(*DURABLE_ROOT_TAIL)


def assert_durable_cache_root(root: Path) -> None:
    """Refuse any root that is not the durable archive location.

    The corpus this job writes is expensive to re-fetch and gates every later
    edge claim, so a volatile root (`/tmp`, `/var/tmp`, `/dev/shm`) is refused
    -- not warned about.
    """
    if not root.is_absolute():
        raise CacheRootPolicyError(f"the cache root must be an absolute path, was {root}")
    if root.parts[-len(DURABLE_ROOT_TAIL) :] != DURABLE_ROOT_TAIL:
        raise CacheRootPolicyError(
            f"{root} is not a durable archive root: it must end with "
            f"{Path(*DURABLE_ROOT_TAIL)} (a volatile root such as /tmp is refused)"
        )


def prepare_cache_root(root: Path) -> Path:
    """Validate the root, then create it. Never the other way round."""
    assert_durable_cache_root(root)
    assert_cache_root_disjoint_from_backup(root)
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# Plan, cadence and requests.
# ---------------------------------------------------------------------------


def last_complete_year(clock: Callable[[], int]) -> int:
    """The last year that has fully elapsed.

    The current year is EXCLUDED by default because a station-year cache entry
    claims a whole calendar year: caching a year that has not finished would
    make a partial payload look permanently covered to every later run.
    """
    now = dt.datetime.fromtimestamp(clock() / _NANOSECONDS_PER_SECOND, tz=dt.UTC)
    return now.year - 1


def refuse_cadence_mix(cadences: Iterable[str]) -> str:
    """Return the single cadence in play, or refuse (L-13).

    Two cadences in one corpus are only comparable after the dense one is
    explicitly DOWNSAMPLED to the sparse one's resolution. This job never does
    that implicitly, so it refuses the mix instead of averaging across it.
    """
    distinct = sorted(set(cadences))
    if not distinct:
        raise CadenceMixError("no cadence: an empty plan has no sampling resolution to record")
    if len(distinct) > 1:
        raise CadenceMixError(
            f"refusing to mix sampling cadences {distinct} in one run: an extremum "
            "statistic is not comparable across cadences (L-13). Downsample the dense "
            "source explicitly, in its own run, against its own cache product."
        )
    return distinct[0]


def request_for(item: StationYear) -> ArchiveRequest:
    """Build the archive request for a station-year, cadence included in the key."""
    product = CADENCE_PRODUCTS.get(item.cadence)
    if product is None:
        raise ValueError(
            f"unknown cadence {item.cadence!r}; the closed set is "
            f"{sorted(CADENCE_PRODUCTS)} -- refused rather than sanitised"
        )
    request = iem_asos_1min_request(item.station, item.year)
    if product == request.product:
        return request
    return dataclasses.replace(request, product=product)


def build_plan(
    *,
    stations: Sequence[str] = STATIONS,
    first_year: int = FIRST_YEAR,
    through_year: int,
    cadence: str = DEFAULT_CADENCE,
) -> tuple[StationYear, ...]:
    """Station-major, year-ascending work plan. One item is one request."""
    if cadence not in CADENCE_PRODUCTS:
        raise ValueError(
            f"unknown cadence {cadence!r}; the closed set is {sorted(CADENCE_PRODUCTS)}"
        )
    unknown = [station for station in stations if station not in STATIONS]
    if unknown:
        raise ValueError(f"station(s) {unknown} are not in the closed set {list(STATIONS)}")
    if through_year < first_year:
        raise ValueError(f"through_year {through_year} precedes first_year {first_year}")
    return tuple(
        StationYear(station, year, cadence)
        for station in stations
        for year in range(first_year, through_year + 1)
    )


# ---------------------------------------------------------------------------
# Payload validation: what may become coverage.
# ---------------------------------------------------------------------------


def validate_payload(body: bytes, *, station: str, cadence: str) -> int:
    """Return the data-row count, or refuse the body as non-coverage."""
    if cadence not in CADENCE_PRODUCTS:
        raise ValueError(f"unknown cadence {cadence!r}")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EmptyPayloadError(
            f"{station} {cadence}: body is not UTF-8 CSV ({exc}); refusing to cache it"
        ) from exc
    stripped = text.lstrip()
    if not stripped:
        raise EmptyPayloadError(f"{station} {cadence}: empty body; refusing to cache it")
    if stripped.startswith("<"):
        raise EmptyPayloadError(
            f"{station} {cadence}: body is markup, not CSV (an error page); refusing to cache it"
        )
    if stripped.upper().startswith("ERROR"):
        raise EmptyPayloadError(
            f"{station} {cadence}: body is an upstream error message; refusing to cache it"
        )
    rows = count_rows(body)
    if rows == 0:
        raise EmptyPayloadError(
            f"{station} {cadence}: zero observation rows. A zero-row response is a "
            "FAILED station-year, never a covered one -- it would poison the 0b fit "
            "invisibly and would never be re-fetched."
        )
    return rows


# ---------------------------------------------------------------------------
# Transport. No host literal here: the origin comes from the shared module.
# ---------------------------------------------------------------------------


def build_pacer(
    *,
    clock: Callable[[], int],
    sleeper: Callable[[float], Coroutine[Any, Any, None]] | None = None,
) -> IemPacer:
    """The named pacer: >= 1 second between requests, testable on a fake clock."""
    return IemPacer(clock=clock, sleeper=sleeper, min_interval_ns=ASOS1MIN_MIN_INTERVAL_NS)


class Asos1MinTransport(PacedIemTransport):
    """IEM 1-minute ASOS CSV fetch on the paced, budgeted IEM transport.

    The caller supplies a station, a cadence and a window -- never a URL.
    """

    def __init__(
        self,
        *,
        budget: RequestBudget,
        pacer: IemPacer,
        user_agent: str,
        clock: Callable[[], int],
        allowed_hosts: frozenset[str] = IEM_ALLOWED_HOSTS,
        base_url: str = IEM_BASE_URL,
        max_body_bytes: int = ASOS1MIN_MAX_BODY_BYTES,
        accept: str = ASOS1MIN_ACCEPT,
        check_proxy_env: bool = True,
        connect_timeout: float = 5.0,
        read_timeout: float = ASOS1MIN_READ_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(
            budget=budget,
            pacer=pacer,
            user_agent=user_agent,
            clock=clock,
            max_body_bytes=max_body_bytes,
            accept=accept,
            allowed_hosts=allowed_hosts,
            base_url=base_url,
            check_proxy_env=check_proxy_env,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        )

    async def fetch_asos1min_csv(self, station: str, cadence: str, sts: str, ets: str) -> Any:
        return await self._fetch(
            self._asos1min_url(station, cadence, sts, ets),
            if_none_match=None,
            if_modified_since=None,
            allow_not_modified=False,
        )

    def _asos1min_url(self, station: str, cadence: str, sts: str, ets: str) -> str:
        if _STATION_PATTERN.match(station) is None or station not in STATIONS:
            raise ValueError(
                f"`station` {station!r} is not in the closed backfill station set "
                f"{list(STATIONS)}; refused rather than sanitised."
            )
        if cadence not in CADENCE_PRODUCTS:
            raise ValueError(
                f"`cadence` {cadence!r} is not in the closed set {sorted(CADENCE_PRODUCTS)}; "
                "the URL's `sample` and the cache product are the SAME value (L-13)."
            )
        for name, value in (("sts", sts), ("ets", ets)):
            if _STS_ETS_PATTERN.match(value) is None:
                raise ValueError(f"`{name}` must be YYYY-MM-DDTHH:MMZ; {value!r} is refused.")
        pairs: list[tuple[str, str]] = [("station", station)]
        pairs.extend(("vars", variable) for variable in ASOS1MIN_VARS)
        pairs.extend(
            [
                ("sample", cadence),
                ("sts", sts),
                ("ets", ets),
                ("tz", "UTC"),
                ("format", "comma"),
                ("what", "download"),
            ]
        )
        return f"{self._base_url}{IEM_ASOS1MIN_PATH}?{urlencode(pairs)}"


def window_bounds(item: StationYear) -> tuple[str, str]:
    """The `sts`/`ets` the URL carries, derived from the cache request itself."""
    request = request_for(item)
    start = dt.datetime.fromtimestamp(request.window_start / _NANOSECONDS_PER_SECOND, tz=dt.UTC)
    end = dt.datetime.fromtimestamp(request.window_end / _NANOSECONDS_PER_SECOND, tz=dt.UTC)
    fmt = "%Y-%m-%dT%H:%MZ"
    return start.strftime(fmt), end.strftime(fmt)


# ---------------------------------------------------------------------------
# The run.
# ---------------------------------------------------------------------------


def run_backfill(
    *,
    cache: ArchiveCache,
    plan: Sequence[StationYear],
    progress: Callable[[str], None],
    dry_run: bool = False,
) -> BackfillReport:
    """Walk the plan station-year by station-year, process-then-discard.

    Exactly one payload is alive at a time: the body is reduced to statistics
    and released before the next station-year begins. A failure is recorded and
    named, never swallowed, and never aborts the remaining station-years -- with
    one exception: another writer holding the coverage lock means a second
    backfill is running, which is a terminal condition for THIS run.
    """
    cadence = refuse_cadence_mix(item.cadence for item in plan)
    total = len(plan)
    outcomes: list[StationYearOutcome] = []
    failed: list[StationYearOutcome] = []
    fetched = 0
    skipped = 0
    would_fetch = 0

    for index, item in enumerate(plan, start=1):
        request = request_for(item)
        prefix = f"[{index}/{total}] {item.label} {item.cadence}"

        if not cache.missing(request):
            outcome = StationYearOutcome(
                station=item.station,
                year=item.year,
                cadence=item.cadence,
                status=STATUS_SKIPPED,
                rows=0,
                bytes=0,
                sha256="",
                detail="already in coverage.json",
            )
            outcomes.append(outcome)
            skipped += 1
            progress(f"{prefix} {STATUS_SKIPPED} (already covered)")
            continue

        if dry_run:
            outcomes.append(
                StationYearOutcome(
                    station=item.station,
                    year=item.year,
                    cadence=item.cadence,
                    status=STATUS_WOULD_FETCH,
                    rows=0,
                    bytes=0,
                    sha256="",
                    detail=f"cache_key={request.cache_key()}",
                )
            )
            would_fetch += 1
            progress(f"{prefix} {STATUS_WOULD_FETCH}")
            continue

        try:
            body = cache.get_or_fetch(request)
        except ArchiveCacheConcurrentWriterError:
            raise
        except Exception as exc:  # noqa: BLE001 - every failure mode is reported, not raised
            outcome = StationYearOutcome(
                station=item.station,
                year=item.year,
                cadence=item.cadence,
                status=STATUS_FAILED,
                rows=0,
                bytes=0,
                sha256="",
                detail=f"{type(exc).__name__}: {exc}",
            )
            outcomes.append(outcome)
            failed.append(outcome)
            progress(f"{prefix} {STATUS_FAILED} {outcome.detail}")
            continue

        rows = count_rows(body)
        size = len(body)
        digest = hashlib.sha256(body).hexdigest()
        del body  # process-then-discard: one station-year in memory, never two

        outcomes.append(
            StationYearOutcome(
                station=item.station,
                year=item.year,
                cadence=item.cadence,
                status=STATUS_FETCHED,
                rows=rows,
                bytes=size,
                sha256=digest,
                detail=f"cache_key={request.cache_key()}",
            )
        )
        fetched += 1
        progress(f"{prefix} {STATUS_FETCHED} rows={rows} bytes={size} sha256={digest[:12]}")

    return BackfillReport(
        outcomes=tuple(outcomes),
        fetched=fetched,
        skipped=skipped,
        would_fetch=would_fetch,
        failed=tuple(failed),
        cadence=cadence,
        dry_run=dry_run,
    )


def render_summary(report: BackfillReport) -> str:
    """The end-of-run summary. A failed station-year is NAMED, never a count."""
    mode = "DRY RUN" if report.dry_run else "RUN"
    lines = [
        f"{mode} cadence={report.cadence} product={CADENCE_PRODUCTS[report.cadence]}",
        (
            f"  station-years: {len(report.outcomes)} planned, "
            f"{report.would_fetch} to fetch, {report.fetched} fetched, "
            f"{report.skipped} already covered, {len(report.failed)} failed"
        ),
        f"  rows fetched this run: {report.rows}",
    ]
    if report.cache_root is not None:
        lines.append(f"  cache root: {report.cache_root}")
    if report.requests_spent is not None:
        lines.append(f"  requests spent: {report.requests_spent}")
    if report.would_fetch:
        lines.append("  WOULD FETCH:")
        lines.extend(
            f"    {outcome.label} ({outcome.cadence})"
            for outcome in report.outcomes
            if outcome.status == STATUS_WOULD_FETCH
        )
    if report.failed:
        lines.append("  FAILED station-years (NOT covered; re-run to retry):")
        lines.extend(
            f"    {STATUS_FAILED} {outcome.label} ({outcome.cadence}): {outcome.detail}"
            for outcome in report.failed
        )
    else:
        lines.append("  no failed station-years")
    return "\n".join(lines) + "\n"


def _outcome_to_json(outcome: StationYearOutcome) -> dict[str, Any]:
    """The `--report-json` schema for one station-year, field by named field.

    Written out explicitly rather than via `dataclasses.asdict`: that helper
    deep-copies field values and bypasses hand-written `__repr__`/`__reduce__`
    hooks, so every call site is a closed, reviewed set in this repo
    (`tests/unit/test_polymarket_us_credential_serialization.py`). Naming the
    fields also makes this report's schema something chosen and stable rather
    than whatever the dataclass happens to carry.
    """
    return {
        "station": outcome.station,
        "year": outcome.year,
        "cadence": outcome.cadence,
        "status": outcome.status,
        "rows": outcome.rows,
        "bytes": outcome.bytes,
        "sha256": outcome.sha256,
        "detail": outcome.detail,
    }


def report_to_json(report: BackfillReport) -> str:
    payload = {
        "cadence": report.cadence,
        "product": CADENCE_PRODUCTS[report.cadence],
        "dry_run": report.dry_run,
        "cache_root": str(report.cache_root) if report.cache_root else None,
        "requests_spent": report.requests_spent,
        "fetched": report.fetched,
        "skipped": report.skipped,
        "would_fetch": report.would_fetch,
        "failed": [outcome.label for outcome in report.failed],
        "outcomes": [_outcome_to_json(outcome) for outcome in report.outcomes],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument("--cache-root", default=None)
    parser.add_argument("--stations", nargs="+", default=list(STATIONS))
    parser.add_argument("--first-year", type=int, default=FIRST_YEAR)
    parser.add_argument("--through-year", type=int, default=None)
    parser.add_argument("--cadence", choices=sorted(CADENCE_PRODUCTS), default=DEFAULT_CADENCE)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--request-budget", type=int, default=None)
    parser.add_argument("--report-json", default=None)
    return parser.parse_args(list(argv))


def _stderr(line: str) -> None:
    sys.stderr.write(f"{line}\n")


def _refuse(message: str) -> int:
    _stderr(f"REFUSED: {message}")
    return 2


def _dry_run_fetch(request: ArchiveRequest) -> bytes:
    raise DryRunFetchAttemptedError(
        f"a dry run reached a fetch for {request.cache_key()}; a dry run makes no request"
    )


def _make_fetch(
    transport: Asos1MinTransport,
    runner: asyncio.Runner,
    plan_by_key: dict[str, StationYear],
) -> Callable[[ArchiveRequest], bytes]:
    def fetch(request: ArchiveRequest) -> bytes:
        item = plan_by_key[request.cache_key()]
        sts, ets = window_bounds(item)
        result = runner.run(
            transport.fetch_asos1min_csv(item.station, item.cadence, sts, ets)
        )
        if result.status_code != 200 or result.text is None:
            raise EmptyPayloadError(
                f"{item.label}: upstream answered HTTP {result.status_code}; not coverage"
            )
        body: bytes = result.text.encode("utf-8")
        validate_payload(body, station=item.station, cadence=item.cadence)
        return body

    return fetch


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. A real run needs both the live unlock and `--apply`."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    root = Path(args.cache_root) if args.cache_root else default_cache_root()
    try:
        assert_durable_cache_root(root)
    except CacheRootPolicyError as exc:
        return _refuse(str(exc))

    clock = time.time_ns
    through_year = args.through_year if args.through_year is not None else last_complete_year(clock)
    try:
        plan = build_plan(
            stations=tuple(args.stations),
            first_year=args.first_year,
            through_year=through_year,
            cadence=args.cadence,
        )
    except ValueError as exc:
        return _refuse(str(exc))

    if not args.dry_run:
        if os.environ.get(LIVE_ENV_VAR) != "1":
            return _refuse(
                f"{LIVE_ENV_VAR}=1 is required before this job may dispatch any request. "
                f"Planned station-years: {len(plan)} (one request each). "
                "Run with --dry-run first."
            )
        if not args.apply:
            return _refuse(
                f"--apply is required for a real run. Planned station-years: {len(plan)}."
            )
        if not os.environ.get(USER_AGENT_ENV_VAR):
            return _refuse(f"{USER_AGENT_ENV_VAR} must name a monitored contact.")

    try:
        prepare_cache_root(root)
    except ArchiveCachePathError as exc:
        return _refuse(str(exc))

    _stderr(
        f"IEM 1-min ASOS backfill: {len(plan)} station-years planned "
        f"({', '.join(args.stations)} {args.first_year}..{through_year}, "
        f"cadence={args.cadence}) into {root}"
    )

    if args.dry_run:
        cache = ArchiveCache(root=root, fetch=_dry_run_fetch, clock=_WallClock())
        report = run_backfill(cache=cache, plan=plan, progress=_stderr, dry_run=True)
        report = dataclasses.replace(report, cache_root=root)
        sys.stderr.write(render_summary(report))
        _write_report_json(args.report_json, report)
        return 0

    budget = RequestBudget(limit=args.request_budget or len(plan))
    plan_by_key = {request_for(item).cache_key(): item for item in plan}
    exit_code = 0
    with asyncio.Runner() as runner:
        transport = Asos1MinTransport(
            budget=budget,
            pacer=build_pacer(clock=clock),
            user_agent=os.environ[USER_AGENT_ENV_VAR],
            clock=clock,
        )
        try:
            report = run_backfill(
                cache=ArchiveCache(
                    root=root,
                    fetch=_make_fetch(transport, runner, plan_by_key),
                    clock=_WallClock(),
                ),
                plan=plan,
                progress=_stderr,
            )
        except (ArchiveCacheConcurrentWriterError, RequestBudgetExceededError) as exc:
            _stderr(f"ABORTED: {type(exc).__name__}: {exc}")
            return 3

    report = dataclasses.replace(report, cache_root=root, requests_spent=budget.spent)
    sys.stderr.write(render_summary(report))
    _write_report_json(args.report_json, report)
    if report.failed:
        exit_code = 1
    return exit_code


def _write_report_json(path: str | None, report: BackfillReport) -> None:
    if path is None:
        return
    Path(path).write_text(report_to_json(report), encoding="utf-8")


class _WallClock:
    """The nanosecond clock `ArchiveCache` stamps `fetched_at_ns` from."""

    def timestamp_ns(self) -> int:
        return time.time_ns()


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
