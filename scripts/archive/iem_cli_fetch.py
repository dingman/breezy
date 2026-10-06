#!/usr/bin/env python
"""IEM AFOS CLI truth fetch and offline truth dataset (FQ loss response F2).

WHAT THIS IS
------------
The ONE writer of the AFOS CLI cache revisions (through the sibling store module
``iem_cli_revisions``), and the offline reader that turns them into a truth dataset.
``fetch`` pulls the NWS CLI (AFOS ``CLI<loc>``) text products for every venue station
from IEM through D-1; ``dataset`` reads the latest promoted valid revision per
station, never touches the network, and writes the finals plus an explicit
``coverage_gap`` field and any ``skipped_revisions``.

EGRESS
------
A public HTTPS GET to a host in ``IEM_ALLOWED_HOSTS`` and nothing else. The
transport is a subclass of ``PacedIemTransport`` (the ``iem_mos_probe_transport``
pattern, imported, never copied), so the allowlist, the redirect alarm, the body
cap, the budget and the 1 s pacer are inherited. No venue credential and no
``operator.env`` is read; this module reads no environment variable at all (the
unit loads ``alerts.env`` only so the failure notifier can deliver).

CACHE (append-only)
-------------------
Each fetch commits a NEW revision ``<LOC>/<fetch_date>.<seq>.json`` (the commit
marker) naming its body ``<fetch_date>.<seq>.<sha12>.txt``. A committed body or
marker is NEVER unlinked or overwritten, including on a same-day rerun. A body is
written under an exclusive non-blocking ``flock``: temp file, ``fsync``, atomic
``os.replace``, directory ``fsync``; body first and marker last. A body that does
not parse to CLI products, or whose climate-day coverage is smaller than the latest
promoted revision's, is rejected and logged to ``rejected.jsonl``; it never becomes
a revision. The reader returns the newest PROMOTED revision whose marker parses and
whose body still matches its recorded sha256; every skipped corrupt marker is
logged with its reason and returned by ``latest_valid_report``.

VALUE CHANGES ARE NOT PROMOTED
------------------------------
If a new body changes ``tmax_f`` or the correction flag on a day the previous
promoted revision already covers, it is committed (evidence) but marked
``promoted=false`` with ``value_change_unconfirmed`` (day, old, new) in its marker
and in ``changes.jsonl``; ``latest_valid`` keeps serving the previous value and the
fetch exits 4 so ``OnFailure`` alerts. TODO(F2-follow-up, deliberately NOT built):
promotion of an unconfirmed revision is a later explicit, human-reviewed path only.

SINGLE WRITER
-------------
``settlement_alignment_study.fetch_text_cached``/``fetch_bytes_cached`` are
cache-read-only for AFOS CLI URLs (a miss raises ``AfosCliCacheMissError``).

LAUNCH WINDOW
-------------
Both subcommands refuse (exit 6) if started 16:30 <= UTC < 17:10; the timers carry
no ``Persistent=true`` so a missed run is never replayed into that window.

EXIT CODES
----------
0 complete
1 one or more stations failed (HTTP/transport error, bad body, coverage reduced)
2 refusal (``dataset`` cache miss, bad cache dir, or cache/output OSError)
3 aborted (request budget exhausted, or another writer holds the lock)
4 value change on a covered day committed but NOT promoted (takes priority over 1)
5 catalog disagreement on a committed station (all else complete)
6 refused: started inside the 16:30-17:10 UTC launch window
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as dt
import io
import json
import sys
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit

_SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
for _sibling in ("analysis", "venue", "archive"):  # pragma: no cover - bootstrap
    _sibling_path = str(_SCRIPTS_ROOT / _sibling)
    if _sibling_path not in sys.path:
        sys.path.insert(0, _sibling_path)

# Imported after the sys.path bootstrap above (L-46: IEM retrieval stays under scripts/).
from iem_cli_revisions import (  # type: ignore[import-not-found]
    AFOS_CACHE_SUBDIR,
    CacheLockedError,
    Revision,
    RevisionStore,
    SkippedRevision,
    atomic_write,
    sha256_hex,
)
from iem_mos_probe_transport import (  # type: ignore[import-not-found]
    IEM_ALLOWED_HOSTS,
    IEM_MIN_INTERVAL_NS,
    IemPacer,
    PacedIemTransport,
)
from settlement_alignment_cache import (  # type: ignore[import-not-found]
    DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR,
    require_settlement_alignment_cache_dir,
)
from settlement_alignment_study import (  # type: ignore[import-not-found]
    AFOS_CLI_PATH,
    CliLabel,
    SiteSpec,
    afos_url,
    is_afos_cli_url,
    load_sites,
    parse_cli_labels,
    read_catalog_finals,
)

from breezy.ingest.http import (
    RateLimitedError,
    ServerError,
    TransportError,
    TransportTimeoutError,
)
from breezy.ingest.probe_transport import (
    RequestBudget,
    RequestBudgetExceededError,
)

__all__ = [
    "AFOS_CACHE_SUBDIR",
    "TRUTH_WINDOW_START",
    "CacheLockedError",
    "DatasetReport",
    "FetchedText",
    "IemCliTransport",
    "NonIemUrlError",
    "Revision",
    "RevisionStore",
    "SkippedRevision",
    "StationOutcome",
    "TruthCacheMissError",
    "afos_cli_text_url",
    "build_dataset",
    "catalog_cross_check",
    "fetch_all",
    "main",
    "require_afos_cli_url",
]

DATASET_SCHEMA: Final[str] = "fq_truth_cli/v1"
DATASET_CSV_NAME: Final[str] = "truth_cli_finals.csv"
DATASET_COVERAGE_NAME: Final[str] = "coverage.json"
DEFAULT_OUTPUT_DIR: Final[Path] = Path.home() / ".local/share/breezy/derived/fq-truth"
DEFAULT_CATALOG_DIR: Final[Path] = Path.home() / ".local/share/breezy/catalog"

#: First climate day the truth window covers (matches the SL-5 extension window).
TRUTH_WINDOW_START: Final[dt.date] = dt.date(2026, 1, 1)
AFOS_LIMIT: Final[int] = 10_000
USER_AGENT: Final[str] = "breezy-truth-fetch/1.0 (read-only AFOS CLI cache; contact: operator)"
ACCEPT: Final[str] = "text/plain"
MAX_BODY_BYTES: Final[int] = 32 * 1024 * 1024
MAX_ATTEMPTS: Final[int] = 3
RETRY_BACKOFF_S: Final[float] = 30.0
_NS_PER_S: Final[int] = 1_000_000_000

EXIT_OK: Final[int] = 0
EXIT_FAILED: Final[int] = 1
EXIT_REFUSED: Final[int] = 2
EXIT_ABORTED: Final[int] = 3
EXIT_VALUE_CHANGE: Final[int] = 4
EXIT_DISAGREEMENT: Final[int] = 5
EXIT_LAUNCH_WINDOW: Final[int] = 6

#: Both subcommands refuse inside [16:30, 17:10) UTC (the launch window).
LAUNCH_WINDOW_START: Final[dt.time] = dt.time(16, 30)
LAUNCH_WINDOW_END: Final[dt.time] = dt.time(17, 10)

STATUS_COMMITTED: Final[str] = "committed"
STATUS_BAD_BODY: Final[str] = "rejected_bad_body"
STATUS_COVERAGE_REDUCED: Final[str] = "rejected_coverage_reduced"
STATUS_VALUE_CHANGE: Final[str] = "value_change_unconfirmed"
STATUS_HTTP_ERROR: Final[str] = "http_error"
STATUS_FETCH_ERROR: Final[str] = "fetch_error"

_RETRYABLE: Final[tuple[type[TransportError], ...]] = (
    RateLimitedError,
    ServerError,
    TransportTimeoutError,
)


class NonIemUrlError(ValueError):
    """The URL is not an https AFOS CLI retrieval on an IEM-allowed host."""


class TruthCacheMissError(RuntimeError):
    """The dataset refuses: a station has no valid cached revision. Never fetches."""


# ---------------------------------------------------------------------------
# URL and transport
# ---------------------------------------------------------------------------


def afos_cli_text_url(cli_location: str, start: dt.date, end: dt.date) -> str:
    """The shared ``afos_url`` grammar with the ``text`` format (the transport is text-only)."""
    parts = urlsplit(afos_url(cli_location, start, end, limit=AFOS_LIMIT))
    query = [(key, "text" if key == "fmt" else value) for key, value in parse_qsl(parts.query)]
    return f"{parts.scheme}://{parts.netloc}{parts.path}?{urlencode(query)}"


def require_afos_cli_url(url: str) -> None:
    """Refuse anything but an https AFOS ``CLI<loc>`` retrieval on an IEM-allowed host."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or host not in IEM_ALLOWED_HOSTS or parts.port not in (None, 443):
        raise NonIemUrlError("refused: not an https URL on an IEM-allowed host")
    if parts.path != AFOS_CLI_PATH or not is_afos_cli_url(url):
        raise NonIemUrlError("refused: not an AFOS CLI retrieval")


@dataclass(frozen=True, slots=True)
class FetchedText:
    status_code: int
    text: str


class CliTextFetcher(Protocol):
    async def fetch_cli_text(self, url: str) -> FetchedText: ...


class IemCliTransport(PacedIemTransport):  # type: ignore[misc]
    """Budgeted, paced, IEM-only GET of AFOS CLI text. Caller names a URL, never a host."""

    def __init__(
        self,
        *,
        budget: RequestBudget,
        pacer: IemPacer,
        user_agent: str,
        clock: Callable[[], int],
        check_proxy_env: bool = True,
    ) -> None:
        super().__init__(
            budget=budget,
            pacer=pacer,
            user_agent=user_agent,
            clock=clock,
            max_body_bytes=MAX_BODY_BYTES,
            accept=ACCEPT,
            check_proxy_env=check_proxy_env,
        )

    async def fetch_cli_text(self, url: str) -> FetchedText:
        require_afos_cli_url(url)
        result = await self._fetch(
            url, if_none_match=None, if_modified_since=None, allow_not_modified=False
        )
        return FetchedText(status_code=result.status_code, text=result.text or "")


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StationOutcome:
    """``detail`` carries ``message``, ``disagreement`` and ``compared_days`` (and changes)."""

    station: str
    status: str
    detail: Mapping[str, Any]
    body_sha256: str | None = None
    label_day_count: int = 0

    @property
    def ok(self) -> bool:
        return self.status == STATUS_COMMITTED

    @property
    def disagreement(self) -> bool:
        return bool(self.detail.get("disagreement", False))


def _detail(
    message: str, check: Mapping[str, Any] | None = None, changes: Sequence[Any] = ()
) -> dict[str, Any]:
    check = check or {}
    return {
        "message": message,
        "disagreement": bool(check.get("disagreement", False)),
        "compared_days": int(check.get("compared_days", 0)),
        "value_changes": list(changes),
    }


def _parse_labels(
    spec: SiteSpec, text: str, url: str, start: dt.date, end: dt.date
) -> tuple[dict[dt.date, CliLabel], int]:
    labels, _drops, errors = parse_cli_labels(
        city=spec.city, site=spec.site, raw_text=text, source_url=url, start=start, end=end
    )
    return labels, len(errors)


def catalog_cross_check(
    city: str,
    labels: Mapping[dt.date, CliLabel],
    catalog_tmax: Mapping[tuple[str, dt.date], int | None] | None,
) -> dict[str, Any]:
    """Compare IEM finals with the catalog CLI finals; a mismatch is flagged, never hidden."""
    if catalog_tmax is None:
        return {
            "status": "unavailable",
            "compared_days": 0,
            "disagreement": False,
            "disagreements": [],
        }
    disagreements: list[dict[str, Any]] = []
    compared = 0
    for day, label in sorted(labels.items()):
        if (city, day) not in catalog_tmax:
            continue
        compared += 1
        if catalog_tmax[(city, day)] != label.tmax_f:
            disagreements.append(
                {
                    "climate_day": day.isoformat(),
                    "cli_tmax_f": label.tmax_f,
                    "catalog_tmax_f": catalog_tmax[(city, day)],
                }
            )
    return {
        "status": "compared",
        "compared_days": compared,
        "disagreement": bool(disagreements),
        "disagreements": disagreements,
    }


async def _fetch_with_retry(
    fetcher: CliTextFetcher, url: str, sleep: Callable[[float], Awaitable[None]]
) -> FetchedText:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await fetcher.fetch_cli_text(url)
        except _RETRYABLE:
            if attempt == MAX_ATTEMPTS:
                raise
            await sleep(RETRY_BACKOFF_S * attempt)
    raise AssertionError("unreachable")  # pragma: no cover


async def _get_text(
    fetcher: CliTextFetcher,
    url: str,
    sleep: Callable[[float], Awaitable[None]],
    station: str,
) -> FetchedText | StationOutcome:
    try:
        fetched = await _fetch_with_retry(fetcher, url, sleep)
    except RequestBudgetExceededError:
        raise
    except TransportError as exc:
        return StationOutcome(station, STATUS_FETCH_ERROR, _detail(f"{type(exc).__name__}: {exc}"))
    if not 200 <= fetched.status_code < 300:
        return StationOutcome(station, STATUS_HTTP_ERROR, _detail(f"HTTP {fetched.status_code}"))
    return fetched


def _check_coverage_not_reduced(
    previous: Revision | None, labels: Mapping[dt.date, CliLabel], window_start: dt.date
) -> str | None:
    """A rejection detail if the new body lost climate days the previous revision covered."""
    if previous is None:
        return None
    lost = sorted(day for day in previous.label_days if day >= window_start and day not in labels)
    if not lost:
        return None
    return f"{len(lost)} previously covered climate days missing, first {lost[0]}"


def _value_changes(
    previous: Revision | None,
    spec: SiteSpec,
    labels: Mapping[dt.date, CliLabel],
    window: tuple[dt.date, dt.date],
) -> list[dict[str, Any]]:
    """Covered days whose tmax or correction flag differ from the previous promoted revision."""
    if previous is None:
        return []
    text = previous.body_path.read_text(encoding="utf-8")
    old_labels, _errors = _parse_labels(spec, text, previous.url, *window)
    return [
        {
            "climate_day": day.isoformat(),
            "old_tmax_f": old_labels[day].tmax_f,
            "new_tmax_f": labels[day].tmax_f,
            "old_correction_flag": old_labels[day].correction_flag,
            "new_correction_flag": labels[day].correction_flag,
        }
        for day in sorted(labels)
        if day in old_labels
        and (old_labels[day].tmax_f, old_labels[day].correction_flag)
        != (labels[day].tmax_f, labels[day].correction_flag)
    ]


def _reject(
    store: RevisionStore, station: str, fetch_date: dt.date, reason: str, body: bytes, detail: str
) -> StationOutcome:
    store.log_rejection(
        station=station, fetch_date=fetch_date, reason=reason, body=body, detail=detail
    )
    return StationOutcome(station, reason, _detail(detail), sha256_hex(body))


async def _fetch_station(
    *,
    spec: SiteSpec,
    fetcher: CliTextFetcher,
    store: RevisionStore,
    fetch_date: dt.date,
    window_start: dt.date,
    catalog_tmax: Mapping[tuple[str, dt.date], int | None] | None,
    sleep: Callable[[float], Awaitable[None]],
) -> StationOutcome:
    station = spec.site.cli_location
    window = (window_start, fetch_date - dt.timedelta(days=1))
    url = afos_cli_text_url(station, *window)
    fetched = await _get_text(fetcher, url, sleep, station)
    if isinstance(fetched, StationOutcome):
        return fetched
    body = fetched.text.encode("utf-8")
    labels, error_count = _parse_labels(spec, fetched.text, url, *window)
    if not labels:
        message = f"no parseable CLI final in window ({error_count} product parse errors)"
        return _reject(store, station, fetch_date, STATUS_BAD_BODY, body, message)
    previous = store.latest_valid(station)
    reduced = _check_coverage_not_reduced(previous, labels, window_start)
    if reduced is not None:
        return _reject(store, station, fetch_date, STATUS_COVERAGE_REDUCED, body, reduced)
    changes = _value_changes(previous, spec, labels, window)
    check = catalog_cross_check(spec.city, labels, catalog_tmax)
    digest = store.commit(
        station=station,
        fetch_date=fetch_date,
        url=url,
        body=body,
        label_days=tuple(labels),
        catalog_check=check,
        value_changes=changes,
    )
    status = STATUS_VALUE_CHANGE if changes else STATUS_COMMITTED
    message = f"{len(changes)} covered day(s) changed, NOT promoted" if changes else "ok"
    return StationOutcome(station, status, _detail(message, check, changes), digest, len(labels))


async def fetch_all(
    *,
    store: RevisionStore,
    sites: Sequence[SiteSpec],
    fetcher: CliTextFetcher,
    fetch_date: dt.date,
    catalog_tmax: Mapping[tuple[str, dt.date], int | None] | None = None,
    window_start: dt.date = TRUTH_WINDOW_START,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> tuple[StationOutcome, ...]:
    """One exclusive-lock pass over every site. Raises ``CacheLockedError`` if contended."""
    outcomes: list[StationOutcome] = []
    with store.locked():
        for spec in sites:
            outcomes.append(
                await _fetch_station(
                    spec=spec,
                    fetcher=fetcher,
                    store=store,
                    fetch_date=fetch_date,
                    window_start=window_start,
                    catalog_tmax=catalog_tmax,
                    sleep=sleep,
                )
            )
    return tuple(outcomes)


# ---------------------------------------------------------------------------
# Offline dataset (never fetches)
# ---------------------------------------------------------------------------

_CSV_FIELDS: Final[tuple[str, ...]] = (
    "station",
    "city",
    "climate_day",
    "tmax_f",
    "tmax_flag",
    "correction_flag",
    "issued_at_utc",
    "product_sha256",
    "revision_fetch_date",
    "revision_sha256",
)


@dataclass(frozen=True, slots=True)
class DatasetReport:
    csv_path: Path
    coverage_path: Path
    coverage: Mapping[str, Any]


def _latest_per_station(
    store: RevisionStore, sites: Sequence[SiteSpec]
) -> tuple[dict[str, Revision], list[SkippedRevision]]:
    found: dict[str, Revision] = {}
    skipped: list[SkippedRevision] = []
    for spec in sites:
        station = spec.site.cli_location
        revision, station_skipped = store.latest_valid_report(station)
        skipped.extend(station_skipped)
        if revision is not None:
            found[station] = revision
    missing = sorted(
        spec.site.cli_location for spec in sites if spec.site.cli_location not in found
    )
    if missing:
        raise TruthCacheMissError(
            f"no valid AFOS CLI revision cached for {missing}; the dataset never fetches"
            f" ({len(skipped)} corrupt revision(s) skipped)"
        )
    return found, skipped


def _station_rows(
    spec: SiteSpec, revision: Revision, labels: Mapping[dt.date, CliLabel]
) -> list[dict[str, Any]]:
    return [
        {
            "station": spec.site.cli_location,
            "city": spec.city,
            "climate_day": day.isoformat(),
            "tmax_f": labels[day].tmax_f,
            "tmax_flag": labels[day].tmax_flag or "",
            "correction_flag": labels[day].correction_flag,
            "issued_at_utc": labels[day].issued_at_utc.isoformat()
            if labels[day].issued_at_utc
            else "",
            "product_sha256": labels[day].raw_sha256,
            "revision_fetch_date": revision.fetch_date.isoformat(),
            "revision_sha256": revision.body_sha256,
        }
        for day in sorted(labels)
    ]


def _station_coverage(
    spec: SiteSpec,
    revision: Revision,
    labels: Mapping[dt.date, CliLabel],
    gap: Sequence[dt.date],
) -> dict[str, Any]:
    return {
        "city": spec.city,
        "revision_fetch_date": revision.fetch_date.isoformat(),
        "revision_sha256": revision.body_sha256,
        "final_days": len(labels),
        "coverage_gap_days": len(gap),
        "coverage_gap": [day.isoformat() for day in gap],
        "last_final_day": max(labels).isoformat() if labels else None,
        "catalog_disagreement": bool(revision.catalog_check.get("disagreement", False)),
        "catalog_disagreements": list(revision.catalog_check.get("disagreements", [])),
        "catalog_check_status": revision.catalog_check.get("status"),
    }


def build_dataset(
    *,
    store: RevisionStore,
    sites: Sequence[SiteSpec],
    as_of: dt.date,
    output_dir: Path,
    window_start: dt.date = TRUTH_WINDOW_START,
) -> DatasetReport:
    """Read the latest promoted revision per station. A cache miss is a refusal, not a fetch."""
    revisions, skipped = _latest_per_station(store, sites)
    window_end = as_of - dt.timedelta(days=1)
    expected = [
        window_start + dt.timedelta(days=offset)
        for offset in range((window_end - window_start).days + 1)
    ]
    rows: list[dict[str, Any]] = []
    stations: dict[str, Any] = {}
    for spec in sites:
        revision = revisions[spec.site.cli_location]
        text = revision.body_path.read_text(encoding="utf-8")
        labels, _errors = _parse_labels(spec, text, revision.url, window_start, window_end)
        rows.extend(_station_rows(spec, revision, labels))
        gap = [day for day in expected if day not in labels]
        stations[spec.site.cli_location] = _station_coverage(spec, revision, labels, gap)
    coverage: dict[str, Any] = {
        "schema": DATASET_SCHEMA,
        "as_of": as_of.isoformat(),
        "window_start": window_start.isoformat(),
        "through_d_minus_1": window_end.isoformat(),
        "expected_days_per_station": len(expected),
        "coverage_gap_days": sum(s["coverage_gap_days"] for s in stations.values()),
        "catalog_disagreement": any(s["catalog_disagreement"] for s in stations.values()),
        "skipped_revisions": [
            {"station": s.station, "marker": s.marker, "reason": s.reason} for s in skipped
        ],
        "stations": stations,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / DATASET_CSV_NAME
    coverage_path = output_dir / DATASET_COVERAGE_NAME
    atomic_write(csv_path, _render_csv(rows))
    atomic_write(coverage_path, (json.dumps(coverage, indent=2, sort_keys=True) + "\n").encode())
    return DatasetReport(csv_path=csv_path, coverage_path=coverage_path, coverage=coverage)


def _render_csv(rows: Sequence[Mapping[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("fetch", "GET AFOS CLI text from IEM into the revision cache (the only writer)"),
        ("dataset", "offline: build the truth dataset from the cache (never fetches)"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--cache-dir", default=str(DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR))
        command.add_argument("--window-start", default=TRUTH_WINDOW_START.isoformat())
        if name == "fetch":
            command.add_argument("--catalog-base", default=str(DEFAULT_CATALOG_DIR))
        else:
            command.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    return parser.parse_args(argv)


def _now(clock: Callable[[], int]) -> dt.datetime:
    return dt.datetime.fromtimestamp(clock() / _NS_PER_S, tz=dt.UTC)


def _today(clock: Callable[[], int]) -> dt.date:
    return _now(clock).date()


def _in_launch_window(clock: Callable[[], int]) -> bool:
    return LAUNCH_WINDOW_START <= _now(clock).time() < LAUNCH_WINDOW_END


def _fetch_exit_code(outcomes: Sequence[StationOutcome]) -> int:
    if any(outcome.status == STATUS_VALUE_CHANGE for outcome in outcomes):
        return EXIT_VALUE_CHANGE
    if not all(outcome.ok for outcome in outcomes):
        return EXIT_FAILED
    return EXIT_DISAGREEMENT if any(outcome.disagreement for outcome in outcomes) else EXIT_OK


def _run_fetch(
    args: argparse.Namespace,
    *,
    clock: Callable[[], int],
    fetcher: CliTextFetcher | None,
) -> int:
    cache_dir = require_settlement_alignment_cache_dir(args.cache_dir)
    sites = load_sites()
    catalog_finals, _details = read_catalog_finals(
        catalog_base=Path(args.catalog_base) if args.catalog_base else None, sites=sites
    )
    catalog_tmax: dict[tuple[str, dt.date], int | None] | None = (
        {key: record.tmax_f for key, record in catalog_finals.items()} if catalog_finals else None
    )
    resolved = fetcher or IemCliTransport(
        budget=RequestBudget(limit=len(sites) * MAX_ATTEMPTS),
        pacer=IemPacer(clock=clock, min_interval_ns=IEM_MIN_INTERVAL_NS),
        user_agent=USER_AGENT,
        clock=clock,
    )
    try:
        outcomes = asyncio.run(
            fetch_all(
                store=RevisionStore(cache_dir),
                sites=sites,
                fetcher=resolved,
                fetch_date=_today(clock),
                catalog_tmax=catalog_tmax,
                window_start=dt.date.fromisoformat(args.window_start),
            )
        )
    except (CacheLockedError, RequestBudgetExceededError) as exc:
        print(f"aborted: {exc}", file=sys.stderr)
        return EXIT_ABORTED
    for outcome in outcomes:
        print(
            f"{outcome.station} {outcome.status} {outcome.detail['message']}"
            f" disagreement={outcome.disagreement}"
            f" compared_days={outcome.detail['compared_days']}"
        )
    return _fetch_exit_code(outcomes)


def _run_dataset(args: argparse.Namespace, *, clock: Callable[[], int]) -> int:
    cache_dir = require_settlement_alignment_cache_dir(args.cache_dir)
    try:
        report = build_dataset(
            store=RevisionStore(cache_dir),
            sites=load_sites(),
            as_of=_today(clock),
            output_dir=Path(args.output_dir),
            window_start=dt.date.fromisoformat(args.window_start),
        )
    except (TruthCacheMissError, OSError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    print(f"coverage_gap_days={report.coverage['coverage_gap_days']} csv={report.csv_path}")
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None,
    *,
    clock: Callable[[], int] | None = None,
    fetcher: CliTextFetcher | None = None,
) -> int:
    """`clock` and `fetcher` are test seams, never CLI flags."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    resolved_clock = clock if clock is not None else time.time_ns
    if _in_launch_window(resolved_clock):
        print("refused: inside the 16:30-17:10 UTC launch window", file=sys.stderr)
        return EXIT_LAUNCH_WINDOW
    if args.command == "fetch":
        return _run_fetch(args, clock=resolved_clock, fetcher=fetcher)
    return _run_dataset(args, clock=resolved_clock)


if __name__ == "__main__":
    raise SystemExit(main())
