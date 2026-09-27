#!/usr/bin/env python3
"""AUD-09a: the replay-sufficiency census.

Disk-only, per `(station, climate_day)`, machine-readable, versioned census
of which station-days can be replayed at all -- see
`docs/plans/backlog/AUDIT_2026-09-21/AUD-09-scheduled-per-station-replay.md`
§6a and the Rev 2.1 amendment
(`docs/plans/backlog/AUDIT_2026-09-21/AUD-09b-AMENDMENT-2026-09-25.md`). Cheap:
it never runs an engine, never fetches over the network, and never touches
the live path.

This module is the impure I/O wrapper around the pure core in
`breezy.analysis.replay_sufficiency`. It reuses, without modification:

- `breezy.persistence.feather_preflight.list_instance_ids` / `scan_instance` /
  `iter_feather_files`;
- `cli_basis_offer_gate_scan.classify_instance`, `_load_stream` and
  `station_days_only_on_corrupt_tape`;
- `current_rung_hold_paper_replay._convert_live_capture` and
  `whole_tape_paper_replay._corrupt_instance_station_days` for the same
  feather-to-work-catalog conversion and corrupt-tape identity read the
  whole-tape driver already performs, so this script derives no new reading
  of the raw capture format;
- `run_weather_strategy_backtests._capture_instruments_by_id` for the same
  single id-discovery-and-filter seam every capture-scoped driver uses.

**REPLAY-BIGINST**: `_discover_clean_spans` no longer reads every book-backed
instrument's full `OrderBookDepth10`/`QuoteTick` object list via
`_select_capture_instruments` -- that scales with the size of the largest
captured instance. It instead column-scans the SAME converted parquet via
`breezy.persistence.catalog_column_scan`, object-free, so census peak memory
no longer scales with instance size
(`docs/plans/backlog/EDGE_2026-09-27/REPLAY-BIGINST_plan_r1_2026-09-27.md`).

**Window definition (AUD-09b amendment C1, B21)**: the decision window is
computed via `breezy.analysis.replay_sufficiency.decision_window_ns`, which
scopes by BOTH date and local-standard-time hour -- unlike the pre-amendment
`_in_decision_window` this module used to define locally (hour only), which
let a market listed the day before draw depth from the WRONG day's
afternoon (F3). The census and the KILL clock (`structural_dead_stop.py`)
therefore share the WINDOW DEFINITION ONLY: the KILL clock counts every depth
instant across rungs of the merged tape catalog and subtracts resolved
`QuoteTapeGap`s, while this census counts PER INSTANCE, executable asks only.
They can still disagree about "covered" -- the shared piece is the window.

**Overlap winner rule (AUD-09b amendment Stage B, §3)**: the winner rule and
FRAGMENT/`excluded_fragments` reporting live entirely in
`breezy.analysis.replay_sufficiency.classify_station_day`; this script
supplies only the real, ns-precision `InstanceSpan` values the pure core
classifies. Stage 0's `--dump-instance-extents` diagnostic (D1) was
Stage-0-only and is deleted now that Stage B has landed.

**H1 (AUD-08b -> AUD-09a)** is read via AUD-08b's own
`breezy.persistence.station_candidates.read_station_candidates` (merged).
`_read_station_candidates` below is a thin wrapper: it prints the plan's
mandated WARN when the register file is absent (§6a: "a missing register is
a WARN and an empty candidate set, never a census failure"), then delegates
to the real reader, which itself returns `()` for a missing file and raises
`UnknownStationCandidateSchemaError`/`StationCandidateRegisterCorruptError`
on a corrupt or unversioned register -- never swallowed here.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import os
import shutil
import signal
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli_basis_offer_gate_scan import (
    _load_stream,
    classify_instance,
    station_days_only_on_corrupt_tape,
)
from current_rung_hold_paper_replay import (  # type: ignore[attr-defined]
    _convert_live_capture,
)
from nautilus_trader.model.data import OrderBookDepth10, QuoteTick
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.persistence.funcs import urisafe_identifier
from run_weather_strategy_backtests import WEATHER_VENUE, _capture_instruments_by_id
from weather_strategy_backtest_lib import select_book_backed_instrument_ids
from whole_tape_paper_replay import _corrupt_instance_station_days

from breezy.analysis.instance_span_cache import (
    DEFAULT_INSTANCE_SPANS_PATH,
    LEGACY_INSTANCE_SPANS_PATH,
    SPAN_ALGO_VERSION,
    CachedInstanceSpans,
    CacheKey,
    InstanceFileFingerprint,
    append_instance_span_cache_entry,
    fingerprint_instance_files,
    legacy_fingerprint_instance_files,
    read_instance_span_cache_with_stats,
    read_legacy_instance_span_cache,
    staggered_last_full_scan,
    write_instance_span_cache,
)
from breezy.analysis.replay_sufficiency import (
    CANDIDATE_UNSUPPORTED_STATION,
    REPLAY_SUFFICIENCY_SCHEMA_VERSION,
    InstanceSpan,
    ReplaySufficiency,
    WindowExtentFold,
    classify_station_day,
    count_live_instances_in_window,
    decision_window_ns,
    write_replay_sufficiency,
)
from breezy.domain.weather_bucket_facts import (
    WeatherFactsUnavailableError,
    read_weather_bucket_facts,
)
from breezy.persistence.catalog_column_scan import (
    count_depth_rows,
    group_files_by_identifier,
    scan_depth_window,
    scan_quote_window,
)
from breezy.persistence.feather_preflight import (
    DEFAULT_SUBDIRECTORY,
    PREFLIGHT_CLASSIFIER_VERSION,
    PreflightError,
    iter_feather_files,
    list_instance_ids,
    scan_instance,
)
from breezy.persistence.station_candidates import StationCandidate, read_station_candidates
from breezy.registry import SiteNotFoundError, default_registry

__all__ = [
    "CensusCompletenessError",
    "_assert_census_is_complete",
    "_candidate_rows_to_replay_sufficiency",
    "_live_instance_registrations",
    "_read_station_candidates",
    "build_census",
    "main",
    "run_census",
]

DEFAULT_QUOTE_TAPE_CATALOG: Final[Path] = (
    Path.home() / ".local/share/breezy/catalog/quote_tape/polymarket_us"
)
DEFAULT_OUTPUT_PATH: Final[Path] = (
    Path.home() / ".local/share/breezy/derived/replay/replay_sufficiency.jsonl"
)
DEFAULT_STATION_CANDIDATES_PATH: Final[Path] = (
    Path.home() / ".local/share/breezy/derived/station_candidates/station_candidates.jsonl"
)
DEFAULT_WORK_PARENT: Final[Path] = Path.home() / ".cache/breezy/replay-census-work"
_DIGEST_BYTES: Final[int] = 4096
_FULL_RESCAN_DAYS: Final[int] = 7
_STALE_WORKDIR_SECONDS: Final[int] = 300

_TERMINATE_REQUESTED = False


@dataclass(slots=True)
class _CacheStats:
    hit: int = 0
    probe_fail: int = 0
    offset_miss: int = 0
    rescanned: int = 0
    cold: int = 0

    def total(self) -> int:
        return self.hit + self.probe_fail + self.offset_miss + self.rescanned + self.cold


@dataclass(slots=True)
class _LoadedCache:
    entries: dict[CacheKey, CachedInstanceSpans]
    migrated: bool = False
    torn_lines: int = 0


def _request_termination(_signum: int, _frame: object) -> None:
    global _TERMINATE_REQUESTED
    _TERMINATE_REQUESTED = True


def _raise_if_terminating() -> None:
    if _TERMINATE_REQUESTED:
        raise SystemExit(143)


def _read_station_candidates(path: Path) -> tuple[StationCandidate, ...]:
    """H1: a missing register WARNs and yields an empty candidate set.

    Never a census failure. The WARN is printed here (the plan's own H1
    text); the actual read -- including the missing-file empty return and
    the unknown-schema / corrupt-register refusals -- is AUD-08b's real
    `breezy.persistence.station_candidates.read_station_candidates`, never
    swallowed.
    """
    if not path.is_file():
        print(
            f"replay-sufficiency-census: WARN -- no station candidate register at {path}; "
            "treating as an empty candidate set (AUD-08b not yet merged or not yet run)",
            file=sys.stderr,
        )
    return read_station_candidates(path)


@contextlib.contextmanager
def _locked_cache(path: Path):
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                f"instance span cache lock is already held: {lock_path}; "
                "refusing to run with a stale or concurrently-written census cache"
            ) from exc
        yield


def _try_lock_workdir(directory: Path):
    lock_path = directory / ".lock"
    try:
        handle = lock_path.open("a+")
    except OSError:
        return None
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def _sweep_work_parent(parent: Path) -> None:
    parent.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.UTC).timestamp()
    for directory in parent.glob("replay-sufficiency-census-*"):
        if not directory.is_dir():
            continue
        lock_path = directory / ".lock"
        if not lock_path.exists():
            continue
        with contextlib.suppress(OSError):
            if now - directory.stat().st_mtime < _STALE_WORKDIR_SECONDS:
                continue
        handle = _try_lock_workdir(directory)
        if handle is None:
            continue
        try:
            shutil.rmtree(directory)
        finally:
            handle.close()


def _sweep_legacy_tmp_workdirs() -> None:
    tmp_parent = Path(tempfile.gettempdir())
    now = dt.datetime.now(dt.UTC).timestamp()
    for directory in tmp_parent.glob("replay-sufficiency-census-*"):
        if not directory.is_dir():
            continue
        lock_path = directory / ".lock"
        if not lock_path.exists():
            continue
        with contextlib.suppress(OSError):
            if now - directory.stat().st_mtime < _STALE_WORKDIR_SECONDS:
                continue
        handle = _try_lock_workdir(directory)
        if handle is None:
            continue
        try:
            shutil.rmtree(directory)
        finally:
            handle.close()


@contextlib.contextmanager
def _locked_work_dir(parent: Path):
    _sweep_work_parent(parent)
    _sweep_legacy_tmp_workdirs()
    work_dir = Path(tempfile.mkdtemp(prefix="replay-sufficiency-census-", dir=parent))
    lock_handle = (work_dir / ".lock").open("a+")
    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
    try:
        yield work_dir
    finally:
        try:
            shutil.rmtree(work_dir)
        finally:
            lock_handle.close()


def _candidate_rows_to_replay_sufficiency(
    candidates: Sequence[StationCandidate],
    *,
    computed_day: str,
    exclude_keys: frozenset[tuple[str, str]] = frozenset(),
) -> tuple[ReplaySufficiency, ...]:
    """H1: one row per candidate NOT already discovered on the tape,
    `CANDIDATE_UNSUPPORTED_STATION`, never queued.

    `exclude_keys` (AUD-09b dup fix, 2026-09-25) is the set of resolved
    `(station, climate_day)` keys the tape-derived census already classified
    via `classify_station_day` in this same run. A candidate register is
    folded on its own schedule and can still list a station (typically a
    `REGISTRY_SEED` row) for the SAME still-open UTC day a live instance is
    already capturing real quotes under -- that collision produced a real
    duplicate `(station, climate_day)` key in production
    (`('NYC', '2026-09-25')`, both `CANDIDATE_UNSUPPORTED_STATION` and a
    real tape-derived row) that `read_replay_sufficiency` correctly refused
    to silently accept. A key the tape already has a real, data-backed
    verdict for is skipped here rather than duplicated with this placeholder
    -- the reader's duplicate-key refusal stays a safety check, not a
    routine trip.

    `winner_instance_id` is always `None` on every emitted row: no station
    outside `SUPPORTED_STATIONS` can ever be selected for replay (plan §6a).
    """
    registry = default_registry()
    rows: list[ReplaySufficiency] = []
    for candidate in candidates:
        try:
            station = registry.site_for_venue_city_token(candidate.venue, candidate.city_token).city
        except SiteNotFoundError:
            station = candidate.city_token.upper()
            print(
                f"replay-sufficiency-census: WARN -- ({candidate.venue}, "
                f"{candidate.city_token}) is not yet in the registry; using the raw "
                "token as a best-effort station label",
                file=sys.stderr,
            )
        if (station, candidate.last_seen_day) in exclude_keys:
            continue
        rows.append(
            ReplaySufficiency(
                schema_version=REPLAY_SUFFICIENCY_SCHEMA_VERSION,
                station=station,
                climate_day=candidate.last_seen_day,
                verdict="INSUFFICIENT",
                reason=CANDIDATE_UNSUPPORTED_STATION,
                winner_instance_id=None,
                depth_window_minutes=0.0,
                quote_window_minutes=0.0,
                distinct_instruments=0,
                computed_day=computed_day,
                # No registry offset exists for an unsupported station -- there
                # is no decision window to report, so every window/live-count
                # field below is the degenerate sentinel (AUD-09b amendment C2a).
                window_start_ns=0,
                window_end_ns=0,
                winner_first_in_window_ns=None,
                winner_last_in_window_ns=None,
                window_complete=False,
                live_instance_count=0,
                coverage_kind="WHOLE",
                excluded_fragments=(),
            )
        )
    return tuple(rows)


def build_census(
    *,
    station_day_spans: Mapping[tuple[str, str], Sequence[InstanceSpan]],
    candidate_rows: Sequence[ReplaySufficiency] = (),
    computed_day: str,
    window_bounds: Mapping[tuple[str, str], tuple[int, int]] | None = None,
    live_instance_counts: Mapping[tuple[str, str], int] | None = None,
) -> tuple[ReplaySufficiency, ...]:
    """Pure aggregation: one `classify_station_day` call per tape-derived key,
    plus every H1 candidate row, sorted for determinism.

    `window_bounds`/`live_instance_counts` (AUD-09b amendment C2a/C3) default
    to empty, so a caller that does not yet compute them (e.g. an older test)
    gets the pre-amendment degenerate `(0, 0)`/`0` values `classify_station_day`
    itself defaults to -- never a `KeyError`.
    """
    resolved_window_bounds = window_bounds or {}
    resolved_live_counts = live_instance_counts or {}
    rows = [
        classify_station_day(
            station=station,
            climate_day=climate_day,
            instances=instances,
            computed_day=computed_day,
            window_start_ns=resolved_window_bounds.get((station, climate_day), (0, 0))[0],
            window_end_ns=resolved_window_bounds.get((station, climate_day), (0, 0))[1],
            live_instance_count=resolved_live_counts.get((station, climate_day), 0),
        )
        for (station, climate_day), instances in station_day_spans.items()
    ]
    rows.extend(candidate_rows)
    return tuple(sorted(rows, key=lambda row: (row.station, row.climate_day)))


class CensusCompletenessError(Exception):
    """The written tape rows do not cover every station-day discovered in the
    raw instance metadata.

    B1 requires a row for every `(station, climate_day)` the tape contains;
    a silently-missing row is worse than a wrong reason, so a mismatch here
    is a loud failure, never a partial write.
    """


def _assert_census_is_complete(
    *,
    discovered: set[tuple[str, str]],
    written: set[tuple[str, str]],
) -> None:
    missing = discovered - written
    extra = written - discovered
    if missing or extra:
        raise CensusCompletenessError(
            f"census completeness check failed: {len(missing)} station-day(s) discovered in "
            f"raw instance metadata but not written ({sorted(missing)}); {len(extra)} written "
            f"but not discovered ({sorted(extra)})"
        )


def _registry_offset_table_fingerprint(registry: object) -> str:
    """sha256 over every `(station, std_utc_offset_hours)` pair the registry
    knows for this venue (AUD-09b amendment Rev 2.1 #5).

    Folded into every instance's cache fingerprint: a registry offset edit
    must invalidate cached spans even though the instance's OWN files never
    changed. Whole-table rather than per-instance-station, because the cache
    lookup happens BEFORE the instance's own stations are known (that is
    discovered only by the conversion the cache is trying to skip).
    """
    pairs = sorted(
        (city, registry.climate_day_window(WEATHER_VENUE, city).std_utc_offset_hours)  # type: ignore[attr-defined]
        for venue, city in registry.pairs()  # type: ignore[attr-defined]
        if venue == WEATHER_VENUE
    )
    canonical = "|".join(f"{city}:{offset}" for city, offset in pairs)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _digest_prefix_and_suffix(path: Path, *, size: int) -> tuple[str, str]:
    with path.open("rb") as handle:
        head = handle.read(_DIGEST_BYTES)
        if size > _DIGEST_BYTES:
            handle.seek(max(size - _DIGEST_BYTES, 0), os.SEEK_SET)
        else:
            handle.seek(0)
        tail = handle.read(_DIGEST_BYTES)
    return (
        hashlib.sha256(head).hexdigest(),
        hashlib.sha256(tail).hexdigest(),
    )


def _instance_file_fingerprints(instance_dir: Path) -> tuple[InstanceFileFingerprint, ...]:
    files: list[InstanceFileFingerprint] = []
    for path in iter_feather_files(instance_dir):
        stat = path.stat()
        head_digest, tail_digest = _digest_prefix_and_suffix(path, size=stat.st_size)
        files.append(
            InstanceFileFingerprint(
                relpath=path.relative_to(instance_dir).as_posix(),
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
                st_ino=stat.st_ino,
                st_dev=stat.st_dev,
                head_digest=head_digest,
                tail_digest=tail_digest,
            )
        )
    return tuple(sorted(files, key=lambda entry: entry.relpath))


def _instance_fingerprint(files: Sequence[InstanceFileFingerprint]) -> str:
    return fingerprint_instance_files(files)


def _legacy_instance_fingerprint(instance_dir: Path, *, offset_table_fingerprint: str) -> str:
    file_fingerprint = legacy_fingerprint_instance_files(
        InstanceFileFingerprint(
            relpath=path.relative_to(instance_dir).as_posix(),
            size=path.stat().st_size,
            mtime_ns=path.stat().st_mtime_ns,
        )
        for path in iter_feather_files(instance_dir)
    )
    return hashlib.sha256(f"{file_fingerprint}:{offset_table_fingerprint}".encode()).hexdigest()


def _station_offsets_for(
    stations: set[str],
    *,
    registry: object,
) -> dict[str, float]:
    return {
        station: float(
            registry.climate_day_window(  # type: ignore[attr-defined]
                WEATHER_VENUE,
                station,
            ).std_utc_offset_hours
        )
        for station in sorted(stations)
    }


def _entry_offsets_still_match(entry: CachedInstanceSpans, *, registry: object) -> bool:
    return entry.station_offsets == _station_offsets_for(
        set(entry.station_offsets),
        registry=registry,
    )


def _entry_due_for_rescan(entry: CachedInstanceSpans, *, today: str) -> bool:
    last_full_scan = dt.date.fromisoformat(entry.last_full_scan)
    return (dt.date.fromisoformat(today) - last_full_scan).days >= _FULL_RESCAN_DAYS


def _merge_cached_spans(
    *,
    entry: CachedInstanceSpans,
    spans: dict[tuple[str, str], list[InstanceSpan]],
    clean_station_days: set[tuple[str, str]],
    window_bounds: MutableMapping[tuple[str, str], tuple[int, int]],
    registry: object,
) -> None:
    for (station, day), span in entry.spans.items():
        spans[(station, day)].append(span)
        clean_station_days.add((station, day))
        _window_bounds_for(station, day, registry=registry, window_bounds=window_bounds)


def _load_span_cache(
    *,
    cache_path: Path,
    catalog_root: Path,
    subdirectory: str,
    today: str,
    registry: object,
) -> _LoadedCache:
    if cache_path.exists():
        loaded = read_instance_span_cache_with_stats(cache_path)
        return _LoadedCache(entries=dict(loaded.entries), torn_lines=loaded.torn_lines)

    legacy_path = LEGACY_INSTANCE_SPANS_PATH
    if cache_path != DEFAULT_INSTANCE_SPANS_PATH:
        legacy_path = cache_path.with_name("instance_spans.jsonl")
    if not legacy_path.exists():
        return _LoadedCache(entries={})

    migrated: dict[CacheKey, CachedInstanceSpans] = {}
    offset_table_fingerprint = _registry_offset_table_fingerprint(registry)
    for (instance_id, legacy_fingerprint, algo_version), spans in read_legacy_instance_span_cache(
        legacy_path
    ).items():
        instance_dir = catalog_root / subdirectory / instance_id
        if not instance_dir.is_dir():
            continue
        current_legacy = _legacy_instance_fingerprint(
            instance_dir,
            offset_table_fingerprint=offset_table_fingerprint,
        )
        if current_legacy != legacy_fingerprint:
            continue
        files = _instance_file_fingerprints(instance_dir)
        fingerprint = _instance_fingerprint(files)
        stations = {station for station, _day in spans}
        migrated[(instance_id, fingerprint, algo_version, PREFLIGHT_CLASSIFIER_VERSION)] = (
            CachedInstanceSpans(
                spans=dict(spans),
                station_offsets=_station_offsets_for(stations, registry=registry),
                last_full_scan=staggered_last_full_scan(instance_id, today),
                files=files,
            )
        )
    write_instance_span_cache(cache_path, migrated)
    return _LoadedCache(entries=migrated, migrated=True)


def _window_bounds_for(
    station: str,
    day: str,
    *,
    registry: object,
    window_bounds: MutableMapping[tuple[str, str], tuple[int, int]],
) -> tuple[int, int]:
    """Memoised `decision_window_ns` lookup, shared by `_discover_clean_spans`
    and `run_census` (code review MEDIUM: previously duplicated as an
    identical local closure in each)."""
    bounds = window_bounds.get((station, day))
    if bounds is not None:
        return bounds
    std_offset = registry.climate_day_window(  # type: ignore[attr-defined]
        WEATHER_VENUE,
        station,
    ).std_utc_offset_hours
    bounds = decision_window_ns(
        climate_day=dt.date.fromisoformat(day),
        std_utc_offset_hours=std_offset,
    )
    window_bounds[(station, day)] = bounds
    return bounds


def _scan_instrument_into_station_fold(
    *,
    instrument_id: str,
    facts: object,
    day: str,
    depth_files_by_id: Mapping[str, list[str]],
    quote_files_by_id: Mapping[str, list[str]],
    registry: object,
    window_bounds: MutableMapping[tuple[str, str], tuple[int, int]],
    by_station: MutableMapping[str, tuple[WindowExtentFold, WindowExtentFold, int]],
    should_stop: Callable[[], None],
) -> None:
    """One already-type-checked, book-backed instrument's depth+quote scan,
    folded into its station's running `WindowExtentFold`s (extracted from
    `_discover_clean_spans`, review finding 4: this was the innermost body of
    a 4-level-deep loop nest).

    `facts` is `WeatherBucketFacts` (kept as `object` here to avoid importing
    it just for the annotation -- the caller already read it via
    `read_weather_bucket_facts`).
    """
    station = facts.settlement_station  # type: ignore[attr-defined]
    start_ns, end_ns = _window_bounds_for(
        station,
        day,
        registry=registry,
        window_bounds=window_bounds,
    )
    _depth_row_count, depth_lo, depth_hi = scan_depth_window(
        depth_files_by_id.get(urisafe_identifier(instrument_id), []),
        start_ns=start_ns,
        end_ns=end_ns,
        should_stop=should_stop,
    )
    _quote_row_count, quote_lo, quote_hi = scan_quote_window(
        quote_files_by_id.get(urisafe_identifier(instrument_id), []),
        start_ns=start_ns,
        end_ns=end_ns,
        should_stop=should_stop,
    )
    depth_fold, quote_fold, count = by_station.get(
        station, (WindowExtentFold(), WindowExtentFold(), 0)
    )
    depth_fold = depth_fold.combine(
        (v for v in (depth_lo, depth_hi) if v is not None),
        start_ns=start_ns,
        end_ns=end_ns,
    )
    quote_fold = quote_fold.combine(
        (v for v in (quote_lo, quote_hi) if v is not None),
        start_ns=start_ns,
        end_ns=end_ns,
    )
    by_station[station] = (depth_fold, quote_fold, count + 1)


def _discover_spans_for_climate_day(
    *,
    catalog: object,
    climate_day: dt.date,
    instance_id: str,
    depth_files_by_id: Mapping[str, list[str]],
    quote_files_by_id: Mapping[str, list[str]],
    registry: object,
    window_bounds: MutableMapping[tuple[str, str], tuple[int, int]],
    should_stop: Callable[[], None],
    spans: MutableMapping[tuple[str, str], list[InstanceSpan]],
    clean_station_days: set[tuple[str, str]],
) -> None:
    """One instance's one climate day: dedup + book-backed filter, the
    R3-3 type check over ALL of them before any scan, the per-instrument
    scans (`_scan_instrument_into_station_fold`), and the resulting
    per-station `InstanceSpan`s (review finding 4, split out of
    `_discover_clean_spans`)."""
    day = climate_day.isoformat()
    # Dedup + this-day filter only -- the SAME single id-discovery-and-filter
    # seam the old path used
    # (`run_weather_strategy_backtests._capture_instruments_by_id`), never
    # `catalog.instruments()` again here.
    by_id = _capture_instruments_by_id(catalog, climate_day=climate_day)
    facts_by_id = {
        instrument_id: read_weather_bucket_facts(instrument.info)
        for instrument_id, instrument in by_id.items()
    }
    # D-1: all-time, unwindowed, footer-only depth row counts -- computed for
    # EVERY id, book-backed or not, exactly matching the oracle's own
    # book-backed test.
    depth_counts = {
        instrument_id: count_depth_rows(
            depth_files_by_id.get(urisafe_identifier(instrument_id), [])
        )
        for instrument_id in by_id
    }
    book_backed_ids = select_book_backed_instrument_ids(depth_counts)

    # R3-3: the BinaryOption type check runs over EVERY book-backed id, in
    # `book_backed_ids`' own sorted order, BEFORE any scan touches a file --
    # never interleaved with the scan loop below. Otherwise a corrupt file on
    # an earlier id could raise `CatalogColumnScanError` before a later id's
    # `TypeError` is ever checked (review finding 3).
    for instrument_id in book_backed_ids:
        instrument = by_id[instrument_id]
        if not isinstance(instrument, BinaryOption):
            raise TypeError(
                f"{instrument_id} is a {type(instrument).__name__}, not a BinaryOption",
            )

    # Per-station accumulator for THIS climate day only -- `day` is fixed for
    # the whole loop below, so grouping only needs the station half of the
    # old `(station, day)` key.
    by_station: dict[str, tuple[WindowExtentFold, WindowExtentFold, int]] = {}

    for instrument_id in book_backed_ids:
        _scan_instrument_into_station_fold(
            instrument_id=instrument_id,
            facts=facts_by_id[instrument_id],
            day=day,
            depth_files_by_id=depth_files_by_id,
            quote_files_by_id=quote_files_by_id,
            registry=registry,
            window_bounds=window_bounds,
            by_station=by_station,
            should_stop=should_stop,
        )

    for station, (depth_fold, quote_fold, count) in by_station.items():
        depth_extent = depth_fold.extent()
        quote_extent = quote_fold.extent()
        span = InstanceSpan(
            instance_id=instance_id,
            verdict="CLEAN",
            depth_window_minutes=depth_extent.span_ns / 1_000_000_000 / 60,
            quote_window_minutes=quote_extent.span_ns / 1_000_000_000 / 60,
            distinct_instruments=count,
            first_in_window_ns=depth_extent.first_ns,
            last_in_window_ns=depth_extent.last_ns,
        )
        spans[(station, day)].append(span)
        clean_station_days.add((station, day))


def _cleanup_work_catalog(work_catalog: Path) -> None:
    """Best-effort removal of one instance's work catalog -- tolerant of a
    directory that was never created (conversion failed before creating it),
    but a genuine removal failure is now a WARN, never silently swallowed
    (review finding 5)."""
    if not work_catalog.exists():
        return

    def _on_error(function: object, path: str, exc: BaseException) -> None:
        print(
            f"replay-sufficiency-census: WARN -- failed to remove work catalog "
            f"{work_catalog} ({getattr(function, '__name__', function)} on {path}): {exc}",
            file=sys.stderr,
        )

    shutil.rmtree(work_catalog, onexc=_on_error)


def _discover_clean_spans(
    *,
    catalog_root: Path,
    subdirectory: str,
    clean_ids: Sequence[str],
    work_root: Path,
    should_stop: Callable[[], None] = _raise_if_terminating,
) -> tuple[
    dict[tuple[str, str], list[InstanceSpan]],
    set[tuple[str, str]],
    dict[tuple[str, str], tuple[int, int]],
]:
    """Real catalog conversion + per-station-day depth/quote span computation.

    REPLAY-BIGINST: object-free. Conversion (`_convert_live_capture`) and the
    climate-day discovery loop are unchanged from before. What used to run
    AFTER that -- `_select_capture_instruments` pulling every book-backed
    instrument's full Depth10/QuoteTick object lists -- is replaced with
    column-projected scans (`breezy.persistence.catalog_column_scan`) over
    the SAME converted parquet, folded with `WindowExtentFold`. Not directly
    unit-tested at the full run_census level (see the test module's
    docstring): the column-scan equivalence to the old, object-based path is
    covered by `tests/unit/test_census_column_scan.py`'s E-B* tests against
    the oracle helper frozen there.

    `should_stop` defaults to the module's own `_raise_if_terminating`; tests
    inject a stub. It is called after every scanned batch and is expected to
    RAISE (never return) to signal a stop request (D-4/R3-4): this function
    never returns a partial `InstanceSpan` for an instance whose scan was
    interrupted, because a raised exception aborts the whole call instead.
    ``should_stop`` stays typed ``Callable[[], None]`` rather than
    ``Callable[[], NoReturn]`` -- the injected `_raise_if_terminating` only
    raises conditionally and otherwise returns normally, so it genuinely is
    not a `NoReturn` callable (mypy rejects binding it as one; confirmed
    locally).

    Cache lookup/checkpointing is deliberately outside this helper: `run_census`
    computes the cheap fingerprint before scan and only calls this conversion
    helper for instances that actually need reconversion, and only writes a
    cache entry / checkpoint line after this function RETURNS (never after a
    raise) -- so a stop request or a `TypeError` (below, re-homed into
    `_discover_spans_for_climate_day`) leaves no partial cache entry and no
    checkpoint line for the instance that raised (E-SIG, E-B7b -- see the
    `run_census`-level E-SIG-int/E-B7b-int integration tests).

    Per-instance work is split into `_discover_spans_for_climate_day` and
    `_scan_instrument_into_station_fold` (review finding 4): this function
    now owns only conversion, climate-day discovery, and cleanup.
    """
    registry = default_registry()
    spans: dict[tuple[str, str], list[InstanceSpan]] = defaultdict(list)
    clean_station_days: set[tuple[str, str]] = set()
    window_bounds: dict[tuple[str, str], tuple[int, int]] = {}

    for instance_id in clean_ids:
        work_catalog = work_root / f"{instance_id}"
        try:
            catalog = _convert_live_capture(
                quote_catalog=catalog_root,
                instance_id=instance_id,
                subdirectory=subdirectory,
                work_catalog=work_catalog,
            )

            climate_days: dict[dt.date, None] = {}
            for instrument in catalog.instruments():
                try:
                    facts = read_weather_bucket_facts(instrument.info)
                except WeatherFactsUnavailableError:
                    continue
                climate_days.setdefault(facts.climate_day, None)

            # Globbed ONCE per instance, per type (r2 "smaller items"), then
            # grouped by `urisafe_identifier(id)` (R3-1) -- never once per id.
            depth_files_by_id = group_files_by_identifier(catalog, OrderBookDepth10)
            quote_files_by_id = group_files_by_identifier(catalog, QuoteTick)

            for climate_day in climate_days:
                _discover_spans_for_climate_day(
                    catalog=catalog,
                    climate_day=climate_day,
                    instance_id=instance_id,
                    depth_files_by_id=depth_files_by_id,
                    quote_files_by_id=quote_files_by_id,
                    registry=registry,
                    window_bounds=window_bounds,
                    should_stop=should_stop,
                    spans=spans,
                    clean_station_days=clean_station_days,
                )
        finally:
            # Finding 5: cleanup now runs even when `_convert_live_capture`
            # itself fails partway (the `try` now starts BEFORE the
            # conversion call, not after it), and a genuine removal failure
            # is WARNed, never silently swallowed.
            _cleanup_work_catalog(work_catalog)

    return dict(spans), clean_station_days, window_bounds


def _live_instance_registrations(
    *,
    quote_catalog: Path,
    subdirectory: str,
    live_ids: Sequence[str],
) -> dict[str, tuple[set[tuple[str, dt.date]], int | None]]:
    """AUD-09b amendment C3 / Rev 2.1 #2: per-LIVE-instance identity read.

    Returns, per LIVE instance, the ``(station, climate_day)`` set its own
    ``binary_option`` registrations named, plus its CAPTURE START (the
    minimum ``ts_init`` over those same rows), or ``None`` when the instance
    yields no usable registration at all.

    Census-local -- deliberately NOT an extension of the shared
    `_corrupt_instance_station_days` (Rev 2.1 #2): that helper merges every
    instance into ONE set and is shared with the whole-tape driver and the
    CORRUPT path, so extending it to also return a minimum would attribute
    ONE global minimum across every instance, not each instance's own start.
    Reading one instance directory at a time here keeps the attribution
    correct. Registration `ts_init` may be listing time rather than true
    capture time; that errs toward OVER-counting a LIVE instance (fail
    closed), and the amendment's Stage 0 journal correlation is the guard.
    """
    result: dict[str, tuple[set[tuple[str, dt.date]], int | None]] = {}
    for instance_id in live_ids:
        instance_dir = quote_catalog / subdirectory / instance_id
        station_days: set[tuple[str, dt.date]] = set()
        min_ts_init: int | None = None
        for instrument in _load_stream([instance_dir], "binary_option", BinaryOption):
            try:
                facts = read_weather_bucket_facts(instrument.info)
            except WeatherFactsUnavailableError:
                continue
            station_days.add((facts.settlement_station, facts.climate_day))
            ts_init = int(instrument.ts_init)
            if min_ts_init is None or ts_init < min_ts_init:
                min_ts_init = ts_init
        result[instance_id] = (station_days, min_ts_init)
    return result


def run_census(
    *,
    catalog_root: Path,
    subdirectory: str,
    work_root: Path,
    station_candidates_path: Path,
    computed_day: str,
    now_ns: int,
    instance_spans_cache_path: Path | None = None,
) -> tuple[ReplaySufficiency, ...]:
    """The real, end-to-end census over one feather capture root.

    `instance_spans_cache_path` (AUD-09b amendment C6) is `None` by default:
    caching is opt-in, so a test (or any caller) that omits it never reads or
    writes the shared on-disk cache. Only `main` passes the real default
    path.
    """
    listing_succeeded = True
    try:
        instance_ids = list_instance_ids(catalog_root, subdirectory)
    except PreflightError:
        instance_ids = ()
        listing_succeeded = False

    corrupt_ids: list[str] = []
    live_or_empty_ids: list[str] = []
    registry = default_registry()
    span_cache: dict[CacheKey, CachedInstanceSpans] | None = None
    kept_cache_keys: set[CacheKey] = set()
    cache_stats = _CacheStats()
    torn_cache_lines = 0
    cache_enabled = instance_spans_cache_path is not None
    if instance_spans_cache_path is not None:
        loaded_cache = _load_span_cache(
            cache_path=instance_spans_cache_path,
            catalog_root=catalog_root,
            subdirectory=subdirectory,
            today=computed_day,
            registry=registry,
        )
        span_cache = loaded_cache.entries
        torn_cache_lines = loaded_cache.torn_lines

    spans: dict[tuple[str, str], list[InstanceSpan]] = defaultdict(list)
    clean_station_days: set[tuple[str, str]] = set()
    window_bounds: dict[tuple[str, str], tuple[int, int]] = {}

    for instance_id in instance_ids:
        _raise_if_terminating()
        instance_dir = catalog_root / subdirectory / instance_id
        files = _instance_file_fingerprints(instance_dir)
        fingerprint = _instance_fingerprint(files)
        cache_key: CacheKey = (
            instance_id,
            fingerprint,
            SPAN_ALGO_VERSION,
            PREFLIGHT_CLASSIFIER_VERSION,
        )
        cached_entry = span_cache.get(cache_key) if span_cache is not None else None
        has_entry_for_instance = span_cache is not None and any(
            key[0] == instance_id for key in span_cache
        )
        if cached_entry is not None and _entry_offsets_still_match(cached_entry, registry=registry):
            if _entry_due_for_rescan(cached_entry, today=computed_day):
                cache_stats.rescanned += 1
                report = scan_instance(catalog_root, instance_id, subdirectory)
                verdict = classify_instance(report, now_ns=now_ns)
                if verdict == "CLEAN":
                    updated_entry = CachedInstanceSpans(
                        spans=dict(cached_entry.spans),
                        station_offsets=dict(cached_entry.station_offsets),
                        last_full_scan=computed_day,
                        files=files,
                    )
                    span_cache[cache_key] = updated_entry
                    kept_cache_keys.add(cache_key)
                    if instance_spans_cache_path is not None:
                        append_instance_span_cache_entry(
                            instance_spans_cache_path, cache_key, updated_entry
                        )
                    _merge_cached_spans(
                        entry=updated_entry,
                        spans=spans,
                        clean_station_days=clean_station_days,
                        window_bounds=window_bounds,
                        registry=registry,
                    )
                    continue
                if verdict == "CORRUPT":
                    corrupt_ids.append(instance_id)
                else:
                    live_or_empty_ids.append(instance_id)
                continue

            cache_stats.hit += 1
            kept_cache_keys.add(cache_key)
            _merge_cached_spans(
                entry=cached_entry,
                spans=spans,
                clean_station_days=clean_station_days,
                window_bounds=window_bounds,
                registry=registry,
            )
            continue

        if span_cache is None:
            cache_stats.cold += 1
        elif cached_entry is not None:
            cache_stats.offset_miss += 1
        elif has_entry_for_instance:
            cache_stats.probe_fail += 1
        else:
            cache_stats.cold += 1

        report = scan_instance(catalog_root, instance_id, subdirectory)
        verdict = classify_instance(report, now_ns=now_ns)
        if verdict == "CLEAN":
            converted, converted_days, converted_bounds = _discover_clean_spans(
                catalog_root=catalog_root,
                subdirectory=subdirectory,
                clean_ids=[instance_id],
                work_root=work_root,
            )
            instance_spans: dict[tuple[str, str], InstanceSpan] = {}
            for key, value in converted.items():
                spans[key].extend(value)
                for span in value:
                    if span.instance_id == instance_id:
                        instance_spans[key] = span
            clean_station_days |= converted_days
            window_bounds.update(converted_bounds)
            if span_cache is not None:
                stations = {station for station, _day in instance_spans}
                entry = CachedInstanceSpans(
                    spans=instance_spans,
                    station_offsets=_station_offsets_for(stations, registry=registry),
                    last_full_scan=staggered_last_full_scan(instance_id, computed_day),
                    files=files,
                )
                span_cache[cache_key] = entry
                kept_cache_keys.add(cache_key)
                if instance_spans_cache_path is not None:
                    append_instance_span_cache_entry(instance_spans_cache_path, cache_key, entry)
        elif verdict == "CORRUPT":
            corrupt_ids.append(instance_id)
        else:
            # LIVE (writer may still be appending) or EMPTY (zero rows
            # anywhere). Neither is ever a winner, but B1 requires a row for
            # every (station, climate_day) the tape contains -- silently
            # dropping a LIVE-only day's identity was the completeness bug.
            live_or_empty_ids.append(instance_id)

    if cache_stats.total() != len(instance_ids):
        raise AssertionError(
            "cache provenance counters are not exhaustive: "
            f"instances={len(instance_ids)} accounted={cache_stats.total()}"
        )

    if (
        instance_spans_cache_path is not None
        and span_cache is not None
        and listing_succeeded
        and instance_ids
    ):
        compacted = {key: span_cache[key] for key in sorted(kept_cache_keys)}
        write_instance_span_cache(instance_spans_cache_path, compacted)

    corrupt_station_days_native = _corrupt_instance_station_days(
        quote_catalog=catalog_root,
        subdirectory=subdirectory,
        corrupt_ids=corrupt_ids,
    )
    clean_station_days_native = {
        (station, dt.date.fromisoformat(day)) for station, day in clean_station_days
    }
    corrupt_only = station_days_only_on_corrupt_tape(
        corrupt_station_days=corrupt_station_days_native,
        clean_station_days=clean_station_days_native,
    )
    for station, corrupt_day in corrupt_only:
        day = corrupt_day.isoformat()
        _window_bounds_for(station, day, registry=registry, window_bounds=window_bounds)
        spans.setdefault((station, day), []).append(
            InstanceSpan(
                instance_id="<corrupt-only>",
                verdict="CORRUPT",
                depth_window_minutes=0.0,
                quote_window_minutes=0.0,
                distinct_instruments=0,
            )
        )

    # C3/Rev 2.1 #2: census-local, per-LIVE-instance identity read -- never
    # an extension of the shared `_corrupt_instance_station_days` (that
    # helper merges every instance into one set; C3 needs each instance's
    # OWN capture start attributed to only the days IT registered).
    # EMPTY instances structurally contribute nothing here (`captured_nothing`
    # means zero rows in every file, so they can never yield a registration);
    # every entry below is therefore from a genuinely LIVE instance.
    live_registrations = _live_instance_registrations(
        quote_catalog=catalog_root,
        subdirectory=subdirectory,
        live_ids=live_or_empty_ids,
    )
    live_or_empty_station_days_native: set[tuple[str, dt.date]] = set()
    live_capture_starts_by_station_day: dict[tuple[str, str], list[int]] = defaultdict(list)
    for station_days, capture_start in live_registrations.values():
        live_or_empty_station_days_native |= station_days
        if capture_start is not None:
            for station, native_day in station_days:
                live_capture_starts_by_station_day[(station, native_day.isoformat())].append(
                    capture_start
                )

    for station, live_day in live_or_empty_station_days_native:
        day = live_day.isoformat()
        _window_bounds_for(station, day, registry=registry, window_bounds=window_bounds)
        spans.setdefault((station, day), []).append(
            InstanceSpan(
                instance_id="<live-or-empty>",
                verdict="LIVE",
                depth_window_minutes=0.0,
                quote_window_minutes=0.0,
                distinct_instruments=0,
            )
        )

    live_instance_counts = {
        key: count_live_instances_in_window(
            capture_starts,
            window_end_ns=_window_bounds_for(
                *key,
                registry=registry,
                window_bounds=window_bounds,
            )[1],
        )
        for key, capture_starts in live_capture_starts_by_station_day.items()
    }

    discovered_station_days = (
        {(station, day.isoformat()) for station, day in corrupt_station_days_native}
        | clean_station_days
        | {(station, day.isoformat()) for station, day in live_or_empty_station_days_native}
    )
    tape_rows = build_census(
        station_day_spans=spans,
        computed_day=computed_day,
        window_bounds=window_bounds,
        live_instance_counts=live_instance_counts,
    )
    _assert_census_is_complete(
        discovered=discovered_station_days,
        written={(row.station, row.climate_day) for row in tape_rows},
    )

    candidates = _read_station_candidates(station_candidates_path)
    candidate_rows = _candidate_rows_to_replay_sufficiency(
        candidates,
        computed_day=computed_day,
        exclude_keys=frozenset(discovered_station_days),
    )

    rows = build_census(
        station_day_spans=spans,
        candidate_rows=candidate_rows,
        computed_day=computed_day,
        window_bounds=window_bounds,
        live_instance_counts=live_instance_counts,
    )
    print(
        "census_provenance: "
        f"run={computed_day} instances={len(instance_ids)} "
        f"cache={'on' if cache_enabled else 'off'} "
        f"hit={cache_stats.hit} probe_fail={cache_stats.probe_fail} "
        f"offset_miss={cache_stats.offset_miss} rescanned={cache_stats.rescanned} "
        f"cold={cache_stats.cold} rescan_due={cache_stats.rescanned} torn={torn_cache_lines}"
    )
    return rows


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog-root", default=str(DEFAULT_QUOTE_TAPE_CATALOG))
    parser.add_argument("--subdirectory", default=DEFAULT_SUBDIRECTORY)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--station-candidates", default=str(DEFAULT_STATION_CANDIDATES_PATH))
    parser.add_argument(
        "--instance-spans-cache",
        default=str(DEFAULT_INSTANCE_SPANS_PATH),
        help="AUD-09b amendment C6: on-disk per-instance span cache path.",
    )
    parser.add_argument(
        "--no-instance-spans-cache",
        action="store_true",
        help="Disable the C6 on-disk span cache for this run.",
    )
    parser.add_argument(
        "--work-parent",
        default=str(DEFAULT_WORK_PARENT),
        help="Parent directory for per-run replay census work catalogs.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    global _TERMINATE_REQUESTED
    _TERMINATE_REQUESTED = False
    previous_sigterm = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _request_termination)
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    now = dt.datetime.now(dt.UTC)
    now_ns = int(now.timestamp() * 1_000_000_000)
    computed_day = now.date().isoformat()

    instance_spans_cache_path = (
        None if args.no_instance_spans_cache else Path(args.instance_spans_cache).expanduser()
    )

    try:
        with contextlib.ExitStack() as stack:
            if instance_spans_cache_path is not None:
                stack.enter_context(_locked_cache(instance_spans_cache_path))
            work_root = stack.enter_context(_locked_work_dir(Path(args.work_parent).expanduser()))
            rows = run_census(
                catalog_root=Path(args.catalog_root).expanduser(),
                subdirectory=args.subdirectory,
                work_root=work_root,
                station_candidates_path=Path(args.station_candidates).expanduser(),
                computed_day=computed_day,
                now_ns=now_ns,
                instance_spans_cache_path=instance_spans_cache_path,
            )
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm)

    write_replay_sufficiency(Path(args.output).expanduser(), rows)

    by_reason = Counter(row.reason or "SUFFICIENT" for row in rows)
    print(
        f"replay-sufficiency-census: {len(rows)} station-day(s) classified: "
        f"{dict(sorted(by_reason.items()))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
