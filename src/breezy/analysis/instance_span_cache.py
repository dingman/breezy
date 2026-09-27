"""On-disk cache of per-CLEAN-instance replay-window spans (AUD-09b amendment
Rev 2.1, Stage A, C6; REPLAY-INCR v2).

Why on disk and not an in-process memo: the census (``replay_sufficiency_census.py``)
is a fresh process every night, so an in-process memo removes nothing --
the cost of converting a live capture into a work catalog and re-deriving its
per-station-day :class:`~breezy.analysis.replay_sufficiency.InstanceSpan`
values is paid again on every run regardless. This module persists that
result keyed by ``(instance_id, fingerprint, algo_version)`` so a re-run over
an UNCHANGED instance reuses it.

**Only CLEAN instances are cached** (:func:`write_instance_span_cache`
refuses otherwise). ``LIVE`` instances may still be appending -- caching a
span for one would freeze a stale, possibly-incomplete view; ``CORRUPT`` and
``EMPTY`` instances carry no real span to cache at all. All three are
recomputed every run.

**Fingerprint**: sha256 over the sorted per-file snapshot
``(relpath, size, mtime_ns, st_ino, st_dev, head_digest, tail_digest)`` values.
The classifier version is a separate cache-key component, so a future preflight
classifier change invalidates every entry even when the files are unchanged.

**Residual**: a same-size/same-mtime edit in the middle of a file that leaves
the head/tail probes and inode/dev unchanged is detected by the staggered full
rescan, not by the cheap hit path.

**Never `dataclasses.asdict`**: like `replay_sufficiency.py`, every field is
serialised explicitly. The credential-serialisation guard
(`tests/unit/test_polymarket_us_credential_serialization.py`) bans every
`asdict(...)` call site under `src/`/`scripts/` outside a closed allowlist
this module is not in.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from breezy.analysis.replay_sufficiency import InstanceSpan

__all__ = [
    "DEFAULT_INSTANCE_SPANS_PATH",
    "INSTANCE_SPANS_SCHEMA_VERSION",
    "LEGACY_INSTANCE_SPANS_PATH",
    "SPAN_ALGO_VERSION",
    "CacheKey",
    "CachedInstanceSpans",
    "InstanceFileFingerprint",
    "InstanceSpanCacheCorruptError",
    "StationDaySpans",
    "UnknownInstanceSpanCacheSchemaError",
    "append_instance_span_cache_entry",
    "fingerprint_instance_files",
    "lookup",
    "read_instance_span_cache",
    "read_instance_span_cache_with_stats",
    "read_legacy_instance_span_cache",
    "staggered_last_full_scan",
    "write_instance_span_cache",
]

#: Hand-off: every writer/reader of `instance_spans.v2.jsonl` agrees on this.
INSTANCE_SPANS_SCHEMA_VERSION: Final[int] = 2

#: A bump invalidates every cached entry, regardless of fingerprint -- for a
#: change to how a span is COMPUTED (e.g. the window definition), never for a
#: change to the instance's own files (the fingerprint already covers that).
SPAN_ALGO_VERSION: Final[int] = 1

LEGACY_INSTANCE_SPANS_PATH: Final[Path] = (
    Path.home() / ".local" / "share" / "breezy" / "derived" / "replay" / "instance_spans.jsonl"
)
DEFAULT_INSTANCE_SPANS_PATH: Final[Path] = LEGACY_INSTANCE_SPANS_PATH.with_name(
    "instance_spans.v2.jsonl"
)

#: `(instance_id, fingerprint, algo_version, preflight_classifier_version)`.
CacheKey = tuple[str, str, int, int]
#: `(station, climate_day_iso)` -> the instance's span for that station-day.
StationDaySpans = Mapping[tuple[str, str], InstanceSpan]


class UnknownInstanceSpanCacheSchemaError(Exception):
    """A cache line names a ``schema_version`` this reader does not know."""


class InstanceSpanCacheCorruptError(Exception):
    """A cache line is malformed, or a non-CLEAN span was asked to be cached."""


@dataclass(frozen=True, slots=True, kw_only=True)
class InstanceFileFingerprint:
    """One per-file snapshot feeding a v2 fingerprint."""

    relpath: str
    size: int
    mtime_ns: int
    st_ino: int = 0
    st_dev: int = 0
    head_digest: str = ""
    tail_digest: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class CachedInstanceSpans:
    """One cache entry's spans plus the invalidation metadata v2 needs."""

    spans: dict[tuple[str, str], InstanceSpan]
    station_offsets: dict[str, float]
    last_full_scan: str
    files: tuple[InstanceFileFingerprint, ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class InstanceSpanCacheReadResult:
    entries: dict[CacheKey, CachedInstanceSpans]
    torn_lines: int = 0


def fingerprint_instance_files(files: Iterable[InstanceFileFingerprint]) -> str:
    """sha256 over the sorted per-file fingerprint rows.

    Sorted so file-discovery order never changes the fingerprint -- the same
    determinism `write_replay_sufficiency` already requires of the census
    output applies here at the cache-key level.
    """
    ordered = sorted(files, key=lambda entry: entry.relpath)
    canonical = "\n".join(
        (
            f"{f.relpath}\t{f.size}\t{f.mtime_ns}\t{f.st_ino}\t{f.st_dev}\t"
            f"{f.head_digest}\t{f.tail_digest}"
        )
        for f in ordered
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def legacy_fingerprint_instance_files(files: Iterable[InstanceFileFingerprint]) -> str:
    """v1 stat-only fingerprint, used only for v1->v2 migration."""
    ordered = sorted(files, key=lambda entry: entry.relpath)
    canonical = "\n".join(f"{f.relpath}\t{f.size}\t{f.mtime_ns}" for f in ordered)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def staggered_last_full_scan(instance_id: str, today: str) -> str:
    """Spread new/migrated entries across the seven-day rescan window."""
    current = dt.date.fromisoformat(today)
    digest = hashlib.sha256(instance_id.encode("utf-8")).digest()
    age_days = int.from_bytes(digest[:2], "big") % 7
    return (current - dt.timedelta(days=age_days)).isoformat()


def _span_to_row(station: str, climate_day: str, span: InstanceSpan) -> dict[str, object]:
    return {
        "station": station,
        "climate_day": climate_day,
        "depth_window_minutes": span.depth_window_minutes,
        "quote_window_minutes": span.quote_window_minutes,
        "distinct_instruments": span.distinct_instruments,
        "first_in_window_ns": span.first_in_window_ns,
        "last_in_window_ns": span.last_in_window_ns,
    }


def _row_to_span(
    row: Mapping[str, object],
    *,
    instance_id: str,
) -> tuple[tuple[str, str], InstanceSpan]:
    station = row.get("station")
    climate_day = row.get("climate_day")
    depth_window_minutes = row.get("depth_window_minutes")
    quote_window_minutes = row.get("quote_window_minutes")
    distinct_instruments = row.get("distinct_instruments")
    first_in_window_ns = row.get("first_in_window_ns")
    last_in_window_ns = row.get("last_in_window_ns")
    if (
        not isinstance(station, str)
        or not isinstance(climate_day, str)
        or not isinstance(depth_window_minutes, float)
        or not isinstance(quote_window_minutes, float)
        or not isinstance(distinct_instruments, int)
        or not (first_in_window_ns is None or isinstance(first_in_window_ns, int))
        or not (last_in_window_ns is None or isinstance(last_in_window_ns, int))
    ):
        raise InstanceSpanCacheCorruptError(
            f"instance {instance_id!r}: malformed cached span row {row!r}"
        )
    span = InstanceSpan(
        instance_id=instance_id,
        verdict="CLEAN",
        depth_window_minutes=depth_window_minutes,
        quote_window_minutes=quote_window_minutes,
        distinct_instruments=distinct_instruments,
        first_in_window_ns=first_in_window_ns,
        last_in_window_ns=last_in_window_ns,
    )
    return (station, climate_day), span


def _validate_clean_entry(instance_id: str, entry: CachedInstanceSpans) -> None:
    for span in entry.spans.values():
        if span.verdict != "CLEAN":
            raise InstanceSpanCacheCorruptError(
                f"instance {instance_id!r}: refusing to cache a {span.verdict} span -- "
                "only CLEAN instances are cached (AUD-09b amendment C6)"
            )


def _file_to_row(file: InstanceFileFingerprint) -> dict[str, object]:
    return {
        "relpath": file.relpath,
        "size": file.size,
        "mtime_ns": file.mtime_ns,
        "st_ino": file.st_ino,
        "st_dev": file.st_dev,
        "head_digest": file.head_digest,
        "tail_digest": file.tail_digest,
    }


def _file_from_row(
    row: Mapping[str, object], *, path: Path, line_number: int
) -> InstanceFileFingerprint:
    try:
        relpath = row["relpath"]
        size = row["size"]
        mtime_ns = row["mtime_ns"]
        st_ino = row["st_ino"]
        st_dev = row["st_dev"]
        head_digest = row["head_digest"]
        tail_digest = row["tail_digest"]
    except KeyError as exc:
        raise InstanceSpanCacheCorruptError(
            f"{path}:{line_number}: cached file row missing key {exc.args[0]!r}"
        ) from exc
    if (
        not isinstance(relpath, str)
        or not isinstance(size, int)
        or isinstance(size, bool)
        or not isinstance(mtime_ns, int)
        or isinstance(mtime_ns, bool)
        or not isinstance(st_ino, int)
        or isinstance(st_ino, bool)
        or not isinstance(st_dev, int)
        or isinstance(st_dev, bool)
        or not isinstance(head_digest, str)
        or not isinstance(tail_digest, str)
    ):
        raise InstanceSpanCacheCorruptError(
            f"{path}:{line_number}: malformed cached file fingerprint row {row!r}"
        )
    return InstanceFileFingerprint(
        relpath=relpath,
        size=size,
        mtime_ns=mtime_ns,
        st_ino=st_ino,
        st_dev=st_dev,
        head_digest=head_digest,
        tail_digest=tail_digest,
    )


def _payload_for_entry(key: CacheKey, entry: CachedInstanceSpans) -> dict[str, object]:
    instance_id, fingerprint, algo_version, classifier_version = key
    _validate_clean_entry(instance_id, entry)
    return {
        "schema_version": INSTANCE_SPANS_SCHEMA_VERSION,
        "instance_id": instance_id,
        "fingerprint": fingerprint,
        "algo_version": algo_version,
        "preflight_classifier_version": classifier_version,
        "station_offsets": dict(sorted(entry.station_offsets.items())),
        "last_full_scan": entry.last_full_scan,
        "files": [
            _file_to_row(file) for file in sorted(entry.files, key=lambda item: item.relpath)
        ],
        "spans": [
            _span_to_row(station, climate_day, span)
            for (station, climate_day), span in sorted(entry.spans.items())
        ],
    }


def append_instance_span_cache_entry(path: Path, key: CacheKey, entry: CachedInstanceSpans) -> None:
    """Append one checkpoint line and fsync it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _payload_for_entry(key, entry)
    encoded = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    with path.open("ab+") as handle:
        handle.seek(0, os.SEEK_END)
        size = handle.tell()
        if size:
            handle.seek(size - 1)
            if handle.read(1) != b"\n":
                handle.seek(0)
                previous_newline = handle.read().rfind(b"\n")
                truncate_at = previous_newline + 1 if previous_newline >= 0 else 0
                os.ftruncate(handle.fileno(), truncate_at)
                handle.seek(0, os.SEEK_END)
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def write_instance_span_cache(path: Path, entries: Mapping[CacheKey, CachedInstanceSpans]) -> None:
    """Atomic final compaction: one line per cache entry, sorted by key."""

    ordered = sorted(entries.items(), key=lambda item: item[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for key, entry in ordered:
                payload = _payload_for_entry(key, entry)
                handle.write(json.dumps(payload, sort_keys=True))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _require_top_level_key(
    payload: Mapping[str, object],
    key: str,
    expected_type: type,
    *,
    path: Path,
    line_number: int,
) -> object:
    """One top-level key, validated and typed -- raises
    :class:`InstanceSpanCacheCorruptError` naming the bad key, never a bare
    `KeyError`/`TypeError` (code review MEDIUM: `_row_to_span` already
    validates its own nested rows this way; the top-level keys did not)."""
    if key not in payload:
        raise InstanceSpanCacheCorruptError(
            f"{path}:{line_number}: instance_spans cache line missing key {key!r}"
        )
    value = payload[key]
    is_bool_value = isinstance(value, bool)
    if expected_type is int and (not isinstance(value, int) or is_bool_value):
        raise InstanceSpanCacheCorruptError(
            f"{path}:{line_number}: {key!r} must be an int, got {type(value).__name__}"
        )
    if expected_type is str and not isinstance(value, str):
        raise InstanceSpanCacheCorruptError(
            f"{path}:{line_number}: {key!r} must be a str, got {type(value).__name__}"
        )
    return value


def _read_payloads(path: Path) -> tuple[list[tuple[int, Mapping[str, object]]], int]:
    payloads: list[tuple[int, Mapping[str, object]]] = []
    if not path.exists():
        return payloads, 0
    torn_lines = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                # Append checkpoints can be torn by SIGKILL. Only tolerate a
                # torn final line; a malformed middle line means the cache is
                # not trustworthy.
                if raw_line.endswith("\n"):
                    raise InstanceSpanCacheCorruptError(
                        f"{path}:{line_number}: malformed instance_spans cache JSON"
                    ) from None
                torn_lines += 1
                continue
            if not isinstance(payload, Mapping):
                raise InstanceSpanCacheCorruptError(
                    f"{path}:{line_number}: instance_spans cache line is not a JSON "
                    f"object, got {type(payload).__name__}"
                )
            payloads.append((line_number, payload))
    return payloads, torn_lines


def read_instance_span_cache_with_stats(path: Path) -> InstanceSpanCacheReadResult:
    """Absent file = empty cache. Refuses an unrecognised ``schema_version``,
    a non-object line, a missing top-level key, or a top-level key of the
    wrong type -- always :class:`InstanceSpanCacheCorruptError` naming the
    bad key, never a bare `KeyError`/`TypeError`/`AttributeError`."""
    typed: dict[CacheKey, CachedInstanceSpans] = {}
    payloads, torn_lines = _read_payloads(path)
    for line_number, payload in payloads:
        version = payload.get("schema_version")
        if version != INSTANCE_SPANS_SCHEMA_VERSION:
            raise UnknownInstanceSpanCacheSchemaError(
                f"{path}:{line_number}: unknown instance_span_cache schema_version "
                f"{version!r} (expected {INSTANCE_SPANS_SCHEMA_VERSION})"
            )
        instance_id = _require_top_level_key(
            payload,
            "instance_id",
            str,
            path=path,
            line_number=line_number,
        )
        fingerprint = _require_top_level_key(
            payload,
            "fingerprint",
            str,
            path=path,
            line_number=line_number,
        )
        algo_version = _require_top_level_key(
            payload,
            "algo_version",
            int,
            path=path,
            line_number=line_number,
        )
        classifier_version = _require_top_level_key(
            payload,
            "preflight_classifier_version",
            int,
            path=path,
            line_number=line_number,
        )
        last_full_scan = _require_top_level_key(
            payload,
            "last_full_scan",
            str,
            path=path,
            line_number=line_number,
        )
        station_offsets_payload = payload.get("station_offsets")
        if not isinstance(station_offsets_payload, Mapping):
            raise InstanceSpanCacheCorruptError(
                f"{path}:{line_number}: 'station_offsets' must be an object"
            )
        station_offsets: dict[str, float] = {}
        for station, offset in station_offsets_payload.items():
            if not isinstance(station, str) or not isinstance(offset, int | float):
                raise InstanceSpanCacheCorruptError(
                    f"{path}:{line_number}: malformed station_offsets entry"
                )
            station_offsets[station] = float(offset)
        files_payload = payload.get("files", [])
        if not isinstance(files_payload, list):
            raise InstanceSpanCacheCorruptError(f"{path}:{line_number}: 'files' must be a list")
        files = tuple(
            _file_from_row(file, path=path, line_number=line_number)  # type: ignore[arg-type]
            for file in files_payload
        )
        if "spans" not in payload:
            raise InstanceSpanCacheCorruptError(
                f"{path}:{line_number}: instance_spans cache line missing key 'spans'"
            )
        spans_payload = payload["spans"]
        if not isinstance(spans_payload, list):
            raise InstanceSpanCacheCorruptError(
                f"{path}:{line_number}: 'spans' must be a list, got {type(spans_payload).__name__}"
            )
        spans: dict[tuple[str, str], InstanceSpan] = {}
        for row in spans_payload:
            key, span = _row_to_span(row, instance_id=instance_id)  # type: ignore[arg-type]
            spans[key] = span
        cache_key = (
            instance_id,  # type: ignore[arg-type]
            fingerprint,  # type: ignore[arg-type]
            algo_version,  # type: ignore[arg-type]
            classifier_version,  # type: ignore[arg-type]
        )
        typed[cache_key] = CachedInstanceSpans(
            spans=spans,
            station_offsets=station_offsets,
            last_full_scan=last_full_scan,  # type: ignore[arg-type]
            files=files,
        )
    return InstanceSpanCacheReadResult(entries=typed, torn_lines=torn_lines)


def read_instance_span_cache(path: Path) -> dict[CacheKey, CachedInstanceSpans]:
    return read_instance_span_cache_with_stats(path).entries


def read_legacy_instance_span_cache(
    path: Path,
) -> dict[tuple[str, str, int], dict[tuple[str, str], InstanceSpan]]:
    """Read schema-v1 entries for one-time migration."""
    legacy: dict[tuple[str, str, int], dict[tuple[str, str], InstanceSpan]] = {}
    payloads, _torn_lines = _read_payloads(path)
    for line_number, payload in payloads:
        version = payload.get("schema_version")
        if version != 1:
            raise UnknownInstanceSpanCacheSchemaError(
                f"{path}:{line_number}: unknown legacy instance_span_cache schema_version "
                f"{version!r} (expected 1)"
            )
        instance_id = _require_top_level_key(
            payload,
            "instance_id",
            str,
            path=path,
            line_number=line_number,
        )
        fingerprint = _require_top_level_key(
            payload,
            "fingerprint",
            str,
            path=path,
            line_number=line_number,
        )
        algo_version = _require_top_level_key(
            payload,
            "algo_version",
            int,
            path=path,
            line_number=line_number,
        )
        spans_payload = payload.get("spans")
        if not isinstance(spans_payload, list):
            raise InstanceSpanCacheCorruptError(f"{path}:{line_number}: 'spans' must be a list")
        spans: dict[tuple[str, str], InstanceSpan] = {}
        for row in spans_payload:
            key, span = _row_to_span(row, instance_id=instance_id)  # type: ignore[arg-type]
            spans[key] = span
        legacy[(instance_id, fingerprint, algo_version)] = spans  # type: ignore[index]
    return legacy


def lookup(
    cache: Mapping[CacheKey, CachedInstanceSpans],
    *,
    instance_id: str,
    fingerprint: str,
    preflight_classifier_version: int,
    station_offsets: Mapping[str, float] | None = None,
    algo_version: int = SPAN_ALGO_VERSION,
) -> StationDaySpans | None:
    """``None`` on a miss: absent entry, fingerprint/version mismatch, or offset drift."""
    entry = cache.get((instance_id, fingerprint, algo_version, preflight_classifier_version))
    if entry is None:
        return None
    if (
        station_offsets is not None
        and {station: float(offset) for station, offset in station_offsets.items()}
        != entry.station_offsets
    ):
        return None
    return entry.spans
