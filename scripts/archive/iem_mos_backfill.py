#!/usr/bin/env python
"""IEM MOS (NBS/GFS) forecast backfill into the durable archive cache (FC-0a-3).

WHAT THIS IS
------------
The forecast half of the Stage-0b fit corpus. The observation half landed as
`scripts/archive/iem_asos1min_backfill.py`; the 0b fit joins FORECAST x CLI
truth x R(t), so without this job there is no forecast to condition on. This
job fetches one MOS model's station-years for KLAX/KMDW/KMIA/KSFO, one request
per station-year, into `ArchiveCache`.

WHAT IT IS NOT
--------------
It is not a cache. `breezy.persistence.archive_cache.ArchiveCache` already owns
cache keys, content-addressed payloads, sha256 digests, the `coverage.json`
manifest, atomic writes, the non-blocking writer lock and the root-disjointness
assertion. This module ORCHESTRATES that cache and adds nothing of its own.

It is also not a transport. L-46: IEM retrieval stays under `scripts/`. The
paced, budgeted, IEM-only transport and the MOS URL builder already live in
`scripts/venue/iem_mos_probe_transport.py`; this module subclasses that
transport for the longer read a station-year needs and names no host.

URL GRAMMAR -- VERIFIED LIVE 2026-09-19. Exercised against the live service in
this work package, over SHORT ranges, before any station-year was fetched:

    https://mesonet.agron.iastate.edu/cgi-bin/request/mos.py
        ?station=KMIA&model=NBS&format=csv
        &sts=2021-06-15T00%3A00Z&ets=2021-06-15T23%3A59Z

    -> HTTP 200, Content-Type: text/plain; charset=UTF-8, 13,961 bytes, 92
       data rows, header `runtime,ftime,model,tmp,dpt,...,station,...`.

That body is checked in byte-for-byte as
`tests/fixtures/iem/mos_NBS_KMIA_2021-06-15_1day.csv` and the URL shape is
pinned against it by `tests/unit/test_iem_mos_backfill.py`.

STATION IDENTIFIER -- ICAO, and the failure mode is SILENT. `asos1min.py` keys
on the three-letter IEM/FAA id and answers `HTTP 422` for an ICAO call sign.
`mos.py` is the OPPOSITE and worse: it keys on the FOUR-letter ICAO
(`station=KMIA`), and a three-letter id is not rejected -- it answers
`HTTP 200` with a HEADER-ONLY body (324 bytes, zero data rows), verified live
and checked in as `mos_NBS_MIA_2021-06-15_zero_rows.csv`. A 200 is therefore
never evidence of coverage here: every payload is VALIDATED (non-empty, CSV,
correct model column, correct station column, at least one data row) BEFORE the
cache is allowed to commit it, so a silent empty can never become a permanent
zero-row "covered" entry.

L-13. An extremum statistic is not comparable across models or cycles, so model
identity is never implicit: the closed model set maps to its OWN cache product
(`mos-nbs`, `mos-gfs`) AND is carried in the request's `model` field, so NBS and
GFS cannot share a cache key, a payload file or a manifest entry; the model the
URL asks for is the model the payload is checked to carry; and a run that would
mix models is REFUSED (:class:`ModelMixError`) rather than blended.

WINDOWS. A station-year is `[Jan 1 00:00Z, Dec 31 23:59Z]` -- the bounds the
URL carries and the bounds the manifest records, identical by construction.
MOS runtimes fall on the hour, so consecutive years are disjoint and no runtime
falls in the one-minute gap at the boundary.

MEMORY. The loop is process-then-discard: exactly one station-year payload is
alive at a time, and what survives an iteration is statistics, never bytes.

Usage
-----
    scripts/archive/iem_mos_backfill.py --model NBS --dry-run
    BREEZY_LIVE=1 BREEZY_USER_AGENT='breezy-ingest/1.0 (+mailto:you@example.com)' \
        scripts/archive/iem_mos_backfill.py --model NBS --apply

Exit codes: 0 complete, 1 one or more station-years failed, 2 refusal
(unlock/argument/root policy), 3 aborted (request budget or another writer).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import dataclasses
import datetime as dt
import hashlib
import io
import json
import os
import sys
import time
from collections.abc import Callable, Coroutine, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

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
from breezy.persistence.archive_request import (
    IEM_MOS_MODEL_PRODUCTS,
    IEM_MOS_SOURCE,
    iem_mos_request,
)

_VENUE_SCRIPTS = Path(__file__).resolve().parents[1] / "venue"
if str(_VENUE_SCRIPTS) not in sys.path:  # pragma: no cover - bootstrap
    sys.path.insert(0, str(_VENUE_SCRIPTS))

# Imported after the sys.path bootstrap above; the IEM transport and the
# VERIFIED MOS URL builder live under scripts/ and stay there (L-46).
from iem_mos_probe_transport import (
    IEM_MIN_INTERVAL_NS,
    IEM_MOS_MODEL_ORDER,
    IEM_MOS_STATION_ORDER,
    IemMosProbeTransport,
    IemPacer,
)

__all__ = [
    "DEFAULT_MODEL",
    "DURABLE_ROOT_TAIL",
    "FIRST_YEAR",
    "MODELS",
    "MOS_MIN_INTERVAL_NS",
    "STATIONS",
    "BackfillReport",
    "CacheRootPolicyError",
    "DryRunFetchAttemptedError",
    "EmptyPayloadError",
    "IemMosBackfillTransport",
    "IemPacer",
    "ModelMismatchError",
    "ModelMixError",
    "StationMismatchError",
    "StationYear",
    "StationYearOutcome",
    "assert_durable_cache_root",
    "build_pacer",
    "build_plan",
    "default_cache_root",
    "last_complete_year",
    "main",
    "prepare_cache_root",
    "refuse_model_mix",
    "render_summary",
    "report_to_json",
    "request_for",
    "run_backfill",
    "validate_payload",
    "window_bounds",
]

#: The four stations the 0b fit needs, reused from the closed MOS set the
#: reachability probe already proved listed. Unlisted -> refused, never
#: sanitised into a request.
STATIONS: Final[tuple[str, ...]] = IEM_MOS_STATION_ORDER
#: The closed model set (L-13). Each maps to its own disjoint cache product.
MODELS: Final[tuple[str, ...]] = IEM_MOS_MODEL_ORDER
DEFAULT_MODEL: Final[str] = "NBS"
FIRST_YEAR: Final[int] = 2021

#: Politeness to a public, NOAA-adjacent service: at most one request a second,
#: charged by a named pacer inside the transport's `_fetch`.
MOS_MIN_INTERVAL_NS: Final[int] = IEM_MIN_INTERVAL_NS

#: A station-year of NBS is ~5 MB (measured by the FC-0a-1 probe: max 5,067,326
#: bytes). 64 MiB refuses a runaway body with a wide margin over a real year.
MOS_MAX_BODY_BYTES: Final[int] = 64 * 1024 * 1024
#: The service generates a year of MOS rows on demand; a 20 s read timeout is
#: too short to depend on.
MOS_READ_TIMEOUT_SECONDS: Final[float] = 900.0

LIVE_ENV_VAR: Final[str] = "BREEZY_LIVE"
USER_AGENT_ENV_VAR: Final[str] = "BREEZY_USER_AGENT"

#: The durable layout, as a path TAIL rather than a prefix blocklist: it pins
#: `~/.local/share/breezy/archive/iem-mos` and in doing so refuses `/tmp`,
#: `/var/tmp` and `/dev/shm` by construction. A DIFFERENT tail from the 1-minute
#: observation backfill, so the two corpora never share a manifest or a lock.
DURABLE_ROOT_TAIL: Final[tuple[str, ...]] = (
    ".local",
    "share",
    "breezy",
    "archive",
    IEM_MOS_SOURCE,
)

#: The CSV columns the validator keys on. Verified against the live header.
_RUNTIME_COLUMN: Final[str] = "runtime"
_MODEL_COLUMN: Final[str] = "model"
_STATION_COLUMN: Final[str] = "station"

_NANOSECONDS_PER_SECOND: Final[int] = 1_000_000_000

STATUS_FETCHED: Final[str] = "FETCHED"
STATUS_SKIPPED: Final[str] = "SKIPPED"
STATUS_WOULD_FETCH: Final[str] = "WOULD_FETCH"
STATUS_FAILED: Final[str] = "FAILED"


class CacheRootPolicyError(ArchiveCachePathError):
    """Raised when a cache root is not the durable archive location."""


class ModelMixError(ValueError):
    """Raised when one run would mix forecast models (L-13)."""


class EmptyPayloadError(ValueError):
    """Raised when a body carries no observations and may not become coverage."""


class ModelMismatchError(EmptyPayloadError):
    """Raised when a payload's model column is not the model that was asked for."""


class StationMismatchError(EmptyPayloadError):
    """Raised when a payload's station column is not the station that was asked for."""


class DryRunFetchAttemptedError(RuntimeError):
    """Raised when a dry run reaches a fetch. A dry run makes no request."""


@dataclass(frozen=True, slots=True)
class StationYear:
    """One unit of work: one station, one year, one model. One request."""

    station: str
    year: int
    model: str

    @property
    def label(self) -> str:
        return f"{self.station} {self.year} {self.model}"


@dataclass(frozen=True, slots=True)
class StationYearOutcome:
    """What a station-year did. Statistics only -- never a payload."""

    station: str
    year: int
    model: str
    status: str
    rows: int
    bytes: int
    sha256: str
    detail: str

    @property
    def label(self) -> str:
        return f"{self.station} {self.year} {self.model}"


@dataclass(frozen=True, slots=True)
class BackfillReport:
    """The whole run, in the shape the operator has to act on."""

    outcomes: tuple[StationYearOutcome, ...]
    fetched: int
    skipped: int
    would_fetch: int
    failed: tuple[StationYearOutcome, ...]
    model: str
    dry_run: bool
    cache_root: Path | None = None
    requests_spent: int | None = None

    @property
    def rows(self) -> int:
        return sum(outcome.rows for outcome in self.outcomes)


# ---------------------------------------------------------------------------
# Cache root policy.
# ---------------------------------------------------------------------------


def default_cache_root() -> Path:
    return Path.home().joinpath(*DURABLE_ROOT_TAIL)


def assert_durable_cache_root(root: Path) -> None:
    """Refuse any root that is not the durable archive location."""
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
# Plan, model and requests.
# ---------------------------------------------------------------------------


def last_complete_year(clock: Callable[[], int]) -> int:
    """The last year that has fully elapsed.

    A station-year entry claims a whole calendar year, so caching a year that
    has not finished would make a partial payload look permanently covered.
    """
    now = dt.datetime.fromtimestamp(clock() / _NANOSECONDS_PER_SECOND, tz=dt.UTC)
    return now.year - 1


def refuse_model_mix(models: Iterable[str]) -> str:
    """Return the single model in play, or refuse (L-13)."""
    distinct = sorted(set(models))
    if not distinct:
        raise ModelMixError("no model: an empty plan has no forecast identity to record")
    if len(distinct) > 1:
        raise ModelMixError(
            f"refusing to mix forecast models {distinct} in one run: model identity is "
            "part of the datum (L-13). Run each model in its own run, against its own "
            "cache product."
        )
    return distinct[0]


def request_for(item: StationYear) -> ArchiveRequest:
    """Build the archive request for a station-year; the model is in the key."""
    return iem_mos_request(item.station, item.year, item.model)


def build_plan(
    *,
    stations: Sequence[str] = STATIONS,
    first_year: int = FIRST_YEAR,
    through_year: int,
    model: str = DEFAULT_MODEL,
) -> tuple[StationYear, ...]:
    """Station-major, year-ascending work plan. One item is one request."""
    if model not in MODELS:
        raise ValueError(f"unknown model {model!r}; the closed set is {sorted(MODELS)}")
    unknown = [station for station in stations if station not in STATIONS]
    if unknown:
        raise ValueError(f"station(s) {unknown} are not in the closed set {list(STATIONS)}")
    if through_year < first_year:
        raise ValueError(f"through_year {through_year} precedes first_year {first_year}")
    return tuple(
        StationYear(station, year, model)
        for station in stations
        for year in range(first_year, through_year + 1)
    )


def window_bounds(item: StationYear) -> tuple[str, str]:
    """The `sts`/`ets` the URL carries, derived from the cache request itself."""
    request = request_for(item)
    start = dt.datetime.fromtimestamp(request.window_start / _NANOSECONDS_PER_SECOND, tz=dt.UTC)
    end = dt.datetime.fromtimestamp(request.window_end / _NANOSECONDS_PER_SECOND, tz=dt.UTC)
    fmt = "%Y-%m-%dT%H:%MZ"
    return start.strftime(fmt), end.strftime(fmt)


# ---------------------------------------------------------------------------
# Payload validation: what may become coverage.
# ---------------------------------------------------------------------------


def validate_payload(body: bytes, *, station: str, model: str) -> int:
    """Return the data-row count, or refuse the body as non-coverage.

    HTTP 200 is not evidence here: a three-letter station id returns 200 with a
    header and nothing else. The model and station columns are checked too, so
    a GFS body can never be committed into an NBS slot (L-13).
    """
    if model not in MODELS:
        raise ValueError(f"unknown model {model!r}; the closed set is {sorted(MODELS)}")
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EmptyPayloadError(
            f"{station} {model}: body is not UTF-8 CSV ({exc}); refusing to cache it"
        ) from exc
    stripped = text.lstrip()
    if not stripped:
        raise EmptyPayloadError(f"{station} {model}: empty body; refusing to cache it")
    if stripped.startswith("<"):
        raise EmptyPayloadError(
            f"{station} {model}: body is markup, not CSV (an error page); refusing to cache it"
        )
    if stripped.upper().startswith("ERROR"):
        raise EmptyPayloadError(
            f"{station} {model}: body is an upstream error message; refusing to cache it"
        )

    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows or rows[0][0].strip() != _RUNTIME_COLUMN:
        raise EmptyPayloadError(
            f"{station} {model}: body does not carry the verified MOS CSV header "
            f"(first column {_RUNTIME_COLUMN!r}); refusing to cache it"
        )
    header = [cell.strip() for cell in rows[0]]
    data = rows[1:]
    if not data:
        raise EmptyPayloadError(
            f"{station} {model}: HTTP 200 with a header and ZERO forecast rows. That is "
            "what a wrong station identifier returns -- a FAILED station-year, never a "
            "covered one: it would poison the 0b fit invisibly and never be re-fetched."
        )
    for column, expected, error in (
        (_MODEL_COLUMN, model, ModelMismatchError),
        (_STATION_COLUMN, station, StationMismatchError),
    ):
        if column not in header:
            raise EmptyPayloadError(
                f"{station} {model}: the CSV header carries no {column!r} column; "
                "the payload's identity cannot be checked, so it is refused"
            )
        index = header.index(column)
        seen = {row[index].strip() for row in data if len(row) > index}
        if seen != {expected}:
            raise error(
                f"{station} {model}: the payload's {column!r} column carries "
                f"{sorted(seen)}, not exactly [{expected!r}]; refusing to cache it under "
                "an identity it does not have (L-13)"
            )
    return len(data)


# ---------------------------------------------------------------------------
# Transport. No host literal here: the origin and the VERIFIED URL builder
# both come from the shared scripts/venue module (L-46).
# ---------------------------------------------------------------------------


def build_pacer(
    *,
    clock: Callable[[], int],
    sleeper: Callable[[float], Coroutine[Any, Any, None]] | None = None,
) -> IemPacer:
    """The named pacer: >= 1 second between requests, testable on a fake clock."""
    return IemPacer(clock=clock, sleeper=sleeper, min_interval_ns=MOS_MIN_INTERVAL_NS)


class IemMosBackfillTransport(IemMosProbeTransport):
    """The probe's MOS transport, sized for a station-year rather than a probe.

    The URL grammar is INHERITED, not restated: `_mos_url` is the shape that was
    verified live, and there is exactly one copy of it in the repo.
    """

    def __init__(
        self,
        *,
        budget: RequestBudget,
        pacer: IemPacer,
        user_agent: str,
        clock: Callable[[], int],
        max_body_bytes: int = MOS_MAX_BODY_BYTES,
        check_proxy_env: bool = True,
        connect_timeout: float = 5.0,
        read_timeout: float = MOS_READ_TIMEOUT_SECONDS,
    ) -> None:
        super().__init__(
            budget=budget,
            pacer=pacer,
            user_agent=user_agent,
            clock=clock,
            max_body_bytes=max_body_bytes,
            check_proxy_env=check_proxy_env,
            connect_timeout=connect_timeout,
            read_timeout=read_timeout,
        )


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

    A failure is recorded and named, never swallowed, and never aborts the
    remaining station-years -- with one exception: another writer holding the
    coverage lock means a second backfill is running, which is terminal.
    """
    model = refuse_model_mix(item.model for item in plan)
    total = len(plan)
    outcomes: list[StationYearOutcome] = []
    failed: list[StationYearOutcome] = []
    fetched = 0
    skipped = 0
    would_fetch = 0

    for index, item in enumerate(plan, start=1):
        request = request_for(item)
        prefix = f"[{index}/{total}] {item.label}"

        if not cache.missing(request):
            outcome = StationYearOutcome(
                station=item.station,
                year=item.year,
                model=item.model,
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
                    model=item.model,
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
                model=item.model,
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
                model=item.model,
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
        model=model,
        dry_run=dry_run,
    )


def render_summary(report: BackfillReport) -> str:
    """The end-of-run summary. A failed station-year is NAMED, never a count."""
    mode = "DRY RUN" if report.dry_run else "RUN"
    lines = [
        f"{mode} model={report.model} product={IEM_MOS_MODEL_PRODUCTS[report.model]}",
        (
            f"  station-years: {len(report.outcomes)} planned, "
            f"{report.would_fetch} to fetch, {report.fetched} fetched, "
            f"{report.skipped} already covered, {len(report.failed)} failed"
        ),
        f"  forecast rows fetched this run: {report.rows}",
    ]
    if report.cache_root is not None:
        lines.append(f"  cache root: {report.cache_root}")
    if report.requests_spent is not None:
        lines.append(f"  requests spent: {report.requests_spent}")
    if report.would_fetch:
        lines.append("  WOULD FETCH:")
        lines.extend(
            f"    {outcome.label}"
            for outcome in report.outcomes
            if outcome.status == STATUS_WOULD_FETCH
        )
    if report.failed:
        lines.append("  FAILED station-years (NOT covered; re-run to retry):")
        lines.extend(
            f"    {STATUS_FAILED} {outcome.label}: {outcome.detail}" for outcome in report.failed
        )
    else:
        lines.append("  no failed station-years")
    return "\n".join(lines) + "\n"


def _outcome_to_json(outcome: StationYearOutcome) -> dict[str, Any]:
    """The `--report-json` schema for one station-year, field by named field.

    Written out explicitly rather than via `dataclasses.asdict`: that helper
    deep-copies field values and bypasses hand-written `__repr__`/`__reduce__`
    hooks, so every call site is a closed, reviewed set in this repo
    (`tests/unit/test_polymarket_us_credential_serialization.py`).
    """
    return {
        "station": outcome.station,
        "year": outcome.year,
        "model": outcome.model,
        "status": outcome.status,
        "rows": outcome.rows,
        "bytes": outcome.bytes,
        "sha256": outcome.sha256,
        "detail": outcome.detail,
    }


def report_to_json(report: BackfillReport) -> str:
    payload = {
        "model": report.model,
        "product": IEM_MOS_MODEL_PRODUCTS[report.model],
        "source": IEM_MOS_SOURCE,
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
    parser.add_argument("--model", choices=sorted(MODELS), default=DEFAULT_MODEL)
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


class _WallClock:
    def timestamp_ns(self) -> int:
        return time.time_ns()


def _make_fetch(
    transport: IemMosBackfillTransport,
    runner: asyncio.Runner,
    plan_by_key: dict[str, StationYear],
) -> Callable[[ArchiveRequest], bytes]:
    def fetch(request: ArchiveRequest) -> bytes:
        item = plan_by_key[request.cache_key()]
        sts, ets = window_bounds(item)
        result = runner.run(transport.fetch_mos_csv(item.station, item.model, sts, ets))
        if result.status_code != 200 or result.text is None:
            raise EmptyPayloadError(
                f"{item.label}: upstream answered HTTP {result.status_code}; not coverage"
            )
        body: bytes = result.text.encode("utf-8")
        validate_payload(body, station=item.station, model=item.model)
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
            model=args.model,
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
        f"IEM MOS backfill: {len(plan)} station-years planned "
        f"({', '.join(args.stations)} {args.first_year}..{through_year}, "
        f"model={args.model}) into {root}"
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
        transport = IemMosBackfillTransport(
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
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(report_to_json(report), encoding="utf-8")
    _stderr(f"report written to {target}")


if __name__ == "__main__":  # pragma: no cover - operator entry point
    raise SystemExit(main())
