#!/usr/bin/env python
"""IEM AFOS CLI truth fetch and offline truth dataset (FQ loss response F2).

WHAT THIS IS
------------
The ONE writer of the AFOS CLI cache revisions, and the offline reader that turns
them into a truth dataset. ``fetch`` pulls the NWS CLI (AFOS ``CLI<loc>``) text
products for every venue station from IEM through D-1; ``dataset`` reads the
latest valid revision per station, never touches the network, and writes the
finals plus an explicit ``coverage_gap`` field.

EGRESS
------
A public HTTPS GET to a host in ``IEM_ALLOWED_HOSTS`` and nothing else. The
transport is a subclass of ``PacedIemTransport`` (the ``iem_mos_probe_transport``
pattern, imported, never copied), so the allowlist, the redirect alarm, the body
cap, the budget and the 1 s pacer are inherited. No venue credential and no
``operator.env`` is read; this module reads no environment variable at all (the
unit loads ``alerts.env`` only so the failure notifier can deliver).

CACHE
-----
``<cache>/afos-cli/<LOC>/<fetch_date>.json`` is the revision's commit marker and
names its body ``<fetch_date>.<sha12>.txt``. Each run asks for a day-bounded
window ``[window_start, fetch_date - 1]`` (the URL's ``edate`` moves with the fetch
date, so every day has its own URL). A body is written under an exclusive
non-blocking ``flock``: temp file, ``fsync``, atomic ``os.replace``, body first and
marker last. A body that does not parse to CLI products, or whose climate-day
coverage is smaller than the latest valid revision's, is rejected and logged to
``rejected.jsonl``; it never becomes a revision. The reader returns the newest
revision whose marker parses and whose body still matches its recorded sha256.

SINGLE WRITER
-------------
``settlement_alignment_study.fetch_text_cached``/``fetch_bytes_cached`` are
cache-read-only for AFOS CLI URLs (a miss raises ``AfosCliCacheMissError``).

Exit codes: 0 complete, 1 one or more stations failed, 2 refusal (cache miss in
``dataset`` or bad cache dir), 3 aborted (budget exhausted or another writer).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
import sys
import time
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit

_SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
for _sibling in ("analysis", "venue"):  # pragma: no cover - bootstrap
    _sibling_path = str(_SCRIPTS_ROOT / _sibling)
    if _sibling_path not in sys.path:
        sys.path.insert(0, _sibling_path)

# Imported after the sys.path bootstrap above (L-46: IEM retrieval stays under scripts/).
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
    "RevisionStore",
    "StationOutcome",
    "TruthCacheMissError",
    "afos_cli_text_url",
    "build_dataset",
    "fetch_all",
    "main",
    "require_afos_cli_url",
]

AFOS_CACHE_SUBDIR: Final[str] = "afos-cli"
LOCK_NAME: Final[str] = ".lock"
REJECTED_LOG_NAME: Final[str] = "rejected.jsonl"
REVISION_SCHEMA: Final[str] = "afos_cli_revision/v1"
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
_BODY_SHA_PREFIX_LEN: Final[int] = 12
_NS_PER_S: Final[int] = 1_000_000_000

EXIT_OK: Final[int] = 0
EXIT_FAILED: Final[int] = 1
EXIT_REFUSED: Final[int] = 2
EXIT_ABORTED: Final[int] = 3

STATUS_COMMITTED: Final[str] = "committed"
STATUS_BAD_BODY: Final[str] = "rejected_bad_body"
STATUS_COVERAGE_REDUCED: Final[str] = "rejected_coverage_reduced"
STATUS_HTTP_ERROR: Final[str] = "http_error"
STATUS_FETCH_ERROR: Final[str] = "fetch_error"

_RETRYABLE: Final[tuple[type[TransportError], ...]] = (
    RateLimitedError,
    ServerError,
    TransportTimeoutError,
)


class NonIemUrlError(ValueError):
    """The URL is not an https AFOS CLI retrieval on an IEM-allowed host."""


class CacheLockedError(RuntimeError):
    """Another writer holds the cache lock."""


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
# Revision store (the only writer of the AFOS CLI cache)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Revision:
    station: str
    fetch_date: dt.date
    url: str
    body_path: Path
    body_sha256: str
    label_days: tuple[dt.date, ...]
    catalog_check: Mapping[str, Any]


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class RevisionStore:
    def __init__(self, cache_dir: Path) -> None:
        self._root = cache_dir / AFOS_CACHE_SUBDIR

    @property
    def root(self) -> Path:
        return self._root

    def station_dir(self, station: str) -> Path:
        return self._root / station

    @contextlib.contextmanager
    def locked(self) -> Iterator[None]:
        self._root.mkdir(parents=True, exist_ok=True)
        with (self._root / LOCK_NAME).open("a") as handle:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CacheLockedError("another AFOS CLI cache writer holds the lock") from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def latest_valid(self, station: str) -> Revision | None:
        """The newest revision whose marker parses and whose body matches its sha256."""
        directory = self.station_dir(station)
        if not directory.is_dir():
            return None
        for marker in sorted(directory.glob("*.json"), reverse=True):
            revision = self._load(station, directory, marker)
            if revision is not None:
                return revision
        return None

    def _load(self, station: str, directory: Path, marker: Path) -> Revision | None:
        try:
            meta = json.loads(marker.read_text(encoding="utf-8"))
            if meta["schema"] != REVISION_SCHEMA or meta["station"] != station:
                return None
            body_path = directory / str(meta["body_file"])
            body = body_path.read_bytes()
            if _sha256(body) != meta["body_sha256"]:
                return None
            return Revision(
                station=station,
                fetch_date=dt.date.fromisoformat(meta["fetch_date"]),
                url=str(meta["url"]),
                body_path=body_path,
                body_sha256=str(meta["body_sha256"]),
                label_days=tuple(dt.date.fromisoformat(day) for day in meta["label_days"]),
                catalog_check=dict(meta["catalog_check"]),
            )
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def commit(
        self,
        *,
        station: str,
        fetch_date: dt.date,
        url: str,
        body: bytes,
        label_days: Sequence[dt.date],
        catalog_check: Mapping[str, Any],
    ) -> str:
        """Write body then marker. Caller must hold ``locked()``. Returns the body sha256."""
        directory = self.station_dir(station)
        directory.mkdir(parents=True, exist_ok=True)
        digest = _sha256(body)
        body_name = f"{fetch_date.isoformat()}.{digest[:_BODY_SHA_PREFIX_LEN]}.txt"
        _atomic_write(directory / body_name, body)
        meta = {
            "schema": REVISION_SCHEMA,
            "station": station,
            "fetch_date": fetch_date.isoformat(),
            "url": url,
            "body_file": body_name,
            "body_sha256": digest,
            "body_bytes": len(body),
            "label_days": [day.isoformat() for day in sorted(label_days)],
            "catalog_check": dict(catalog_check),
        }
        marker = directory / f"{fetch_date.isoformat()}.json"
        previous_body = self._body_named_by(marker)
        _atomic_write(marker, (json.dumps(meta, sort_keys=True) + "\n").encode("utf-8"))
        if previous_body is not None and previous_body != body_name:
            (directory / previous_body).unlink(missing_ok=True)
        return digest

    @staticmethod
    def _body_named_by(marker: Path) -> str | None:
        try:
            return str(json.loads(marker.read_text(encoding="utf-8"))["body_file"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def log_rejection(
        self, *, station: str, fetch_date: dt.date, reason: str, body: bytes, detail: str
    ) -> None:
        directory = self.station_dir(station)
        directory.mkdir(parents=True, exist_ok=True)
        record = {
            "fetch_date": fetch_date.isoformat(),
            "reason": reason,
            "body_sha256": _sha256(body),
            "body_bytes": len(body),
            "detail": detail,
        }
        with (directory / REJECTED_LOG_NAME).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StationOutcome:
    station: str
    status: str
    detail: str
    body_sha256: str | None = None
    label_day_count: int = 0

    @property
    def ok(self) -> bool:
        return self.status == STATUS_COMMITTED


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
    window_end = fetch_date - dt.timedelta(days=1)
    url = afos_cli_text_url(station, window_start, window_end)
    try:
        fetched = await _fetch_with_retry(fetcher, url, sleep)
    except RequestBudgetExceededError:
        raise
    except TransportError as exc:
        return StationOutcome(station, STATUS_FETCH_ERROR, f"{type(exc).__name__}: {exc}")
    if not 200 <= fetched.status_code < 300:
        return StationOutcome(station, STATUS_HTTP_ERROR, f"HTTP {fetched.status_code}")

    body = fetched.text.encode("utf-8")
    labels, error_count = _parse_labels(spec, fetched.text, url, window_start, window_end)
    if not labels:
        detail = f"no parseable CLI final in window ({error_count} product parse errors)"
        store.log_rejection(
            station=station, fetch_date=fetch_date, reason=STATUS_BAD_BODY, body=body, detail=detail
        )
        return StationOutcome(station, STATUS_BAD_BODY, detail, _sha256(body))

    previous = store.latest_valid(station)
    if previous is not None:
        lost = sorted(
            day for day in previous.label_days if day >= window_start and day not in labels
        )
        if lost:
            detail = f"{len(lost)} previously covered climate days missing, first {lost[0]}"
            store.log_rejection(
                station=station,
                fetch_date=fetch_date,
                reason=STATUS_COVERAGE_REDUCED,
                body=body,
                detail=detail,
            )
            return StationOutcome(station, STATUS_COVERAGE_REDUCED, detail, _sha256(body))

    digest = store.commit(
        station=station,
        fetch_date=fetch_date,
        url=url,
        body=body,
        label_days=tuple(labels),
        catalog_check=catalog_cross_check(spec.city, labels, catalog_tmax),
    )
    return StationOutcome(station, STATUS_COMMITTED, "ok", digest, len(labels))


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


def build_dataset(
    *,
    store: RevisionStore,
    sites: Sequence[SiteSpec],
    as_of: dt.date,
    output_dir: Path,
    window_start: dt.date = TRUTH_WINDOW_START,
) -> DatasetReport:
    """Read the latest valid revision per station. A cache miss is a refusal, not a fetch."""
    revisions = {
        spec.site.cli_location: store.latest_valid(spec.site.cli_location) for spec in sites
    }
    missing = sorted(station for station, revision in revisions.items() if revision is None)
    if missing:
        raise TruthCacheMissError(
            f"no valid AFOS CLI revision cached for {missing}; the dataset never fetches"
        )
    window_end = as_of - dt.timedelta(days=1)
    expected = [
        window_start + dt.timedelta(days=offset)
        for offset in range((window_end - window_start).days + 1)
    ]
    rows: list[dict[str, Any]] = []
    stations: dict[str, Any] = {}
    gap_total = 0
    for spec in sites:
        station = spec.site.cli_location
        revision = revisions[station]
        assert revision is not None  # narrowed by the refusal above
        text = revision.body_path.read_text(encoding="utf-8")
        labels, _errors = _parse_labels(spec, text, revision.url, window_start, window_end)
        gap = [day for day in expected if day not in labels]
        gap_total += len(gap)
        for day in sorted(labels):
            label = labels[day]
            rows.append(
                {
                    "station": station,
                    "city": spec.city,
                    "climate_day": day.isoformat(),
                    "tmax_f": label.tmax_f,
                    "tmax_flag": label.tmax_flag or "",
                    "correction_flag": label.correction_flag,
                    "issued_at_utc": label.issued_at_utc.isoformat() if label.issued_at_utc else "",
                    "product_sha256": label.raw_sha256,
                    "revision_fetch_date": revision.fetch_date.isoformat(),
                    "revision_sha256": revision.body_sha256,
                }
            )
        stations[station] = {
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
    coverage: dict[str, Any] = {
        "schema": DATASET_SCHEMA,
        "as_of": as_of.isoformat(),
        "window_start": window_start.isoformat(),
        "through_d_minus_1": window_end.isoformat(),
        "expected_days_per_station": len(expected),
        "coverage_gap_days": gap_total,
        "catalog_disagreement": any(s["catalog_disagreement"] for s in stations.values()),
        "stations": stations,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / DATASET_CSV_NAME
    coverage_path = output_dir / DATASET_COVERAGE_NAME
    _atomic_write(csv_path, _render_csv(rows))
    _atomic_write(coverage_path, (json.dumps(coverage, indent=2, sort_keys=True) + "\n").encode())
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


def _today(clock: Callable[[], int]) -> dt.date:
    return dt.datetime.fromtimestamp(clock() / _NS_PER_S, tz=dt.UTC).date()


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
        print(f"{outcome.station} {outcome.status} {outcome.detail}")
    return EXIT_OK if all(outcome.ok for outcome in outcomes) else EXIT_FAILED


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
    except TruthCacheMissError as exc:
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
    if args.command == "fetch":
        return _run_fetch(args, clock=resolved_clock, fetcher=fetcher)
    return _run_dataset(args, clock=resolved_clock)


if __name__ == "__main__":
    raise SystemExit(main())
