"""On-disk cache of per-CLEAN-instance replay-window spans (AUD-09b amendment
Rev 2.1, Stage A, C6).

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

**Fingerprint**: sha256 over the sorted ``(relpath, size, mtime_ns)`` triples
of an instance's own files (:func:`fingerprint_instance_files`), folded with
the station's own standard-UTC-offset table (Rev 2.1 #5) by the CALLER before
it is used as a cache key -- a registry offset change must invalidate cached
spans even though the instance's own files never moved.

**Residual (pinned by ``tests/unit/test_instance_span_cache.py::test_a7_*``)**:
an edit that preserves both size and mtime is not detected. This is an
accepted, explicit gap (AUD-09b amendment §9), not an oversight.

**Never `dataclasses.asdict`**: like `replay_sufficiency.py`, every field is
serialised explicitly. The credential-serialisation guard
(`tests/unit/test_polymarket_us_credential_serialization.py`) bans every
`asdict(...)` call site under `src/`/`scripts/` outside a closed allowlist
this module is not in.
"""

from __future__ import annotations

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
    "SPAN_ALGO_VERSION",
    "CacheKey",
    "InstanceFileFingerprint",
    "InstanceSpanCacheCorruptError",
    "StationDaySpans",
    "UnknownInstanceSpanCacheSchemaError",
    "fingerprint_instance_files",
    "lookup",
    "read_instance_span_cache",
    "write_instance_span_cache",
]

#: Hand-off: every writer/reader of `instance_spans.jsonl` agrees on this.
INSTANCE_SPANS_SCHEMA_VERSION: Final[int] = 1

#: A bump invalidates every cached entry, regardless of fingerprint -- for a
#: change to how a span is COMPUTED (e.g. the window definition), never for a
#: change to the instance's own files (the fingerprint already covers that).
SPAN_ALGO_VERSION: Final[int] = 1

DEFAULT_INSTANCE_SPANS_PATH: Final[Path] = (
    Path.home() / ".local" / "share" / "breezy" / "derived" / "replay" / "instance_spans.jsonl"
)

#: `(instance_id, fingerprint, algo_version)`.
CacheKey = tuple[str, str, int]
#: `(station, climate_day_iso)` -> the instance's span for that station-day.
StationDaySpans = Mapping[tuple[str, str], InstanceSpan]


class UnknownInstanceSpanCacheSchemaError(Exception):
    """A cache line names a ``schema_version`` this reader does not know."""


class InstanceSpanCacheCorruptError(Exception):
    """A cache line is malformed, or a non-CLEAN span was asked to be cached."""


@dataclass(frozen=True, slots=True, kw_only=True)
class InstanceFileFingerprint:
    """One ``(relpath, size, mtime_ns)`` triple feeding a fingerprint."""

    relpath: str
    size: int
    mtime_ns: int


def fingerprint_instance_files(files: Iterable[InstanceFileFingerprint]) -> str:
    """sha256 over the SORTED ``(relpath, size, mtime_ns)`` triples.

    Sorted so file-discovery order never changes the fingerprint -- the same
    determinism `write_replay_sufficiency` already requires of the census
    output applies here at the cache-key level.
    """
    ordered = sorted(files, key=lambda entry: entry.relpath)
    canonical = "\n".join(f"{f.relpath}\t{f.size}\t{f.mtime_ns}" for f in ordered)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


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
    row: Mapping[str, object], *, instance_id: str,
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


def write_instance_span_cache(path: Path, entries: Mapping[CacheKey, StationDaySpans]) -> None:
    """Atomic whole-file rewrite: one line per cache entry, sorted by key.

    Refuses (never silently drops) an entry carrying a non-``CLEAN`` span --
    ``LIVE``/``CORRUPT``/``EMPTY`` instances are never cached (C6).
    """
    for (instance_id, _fingerprint, _algo_version), spans in entries.items():
        for span in spans.values():
            if span.verdict != "CLEAN":
                raise InstanceSpanCacheCorruptError(
                    f"instance {instance_id!r}: refusing to cache a {span.verdict} span -- "
                    "only CLEAN instances are cached (AUD-09b amendment C6)"
                )

    ordered = sorted(entries.items(), key=lambda item: item[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            for (instance_id, fingerprint, algo_version), spans in ordered:
                payload = {
                    "schema_version": INSTANCE_SPANS_SCHEMA_VERSION,
                    "instance_id": instance_id,
                    "fingerprint": fingerprint,
                    "algo_version": algo_version,
                    "spans": [
                        _span_to_row(station, climate_day, span)
                        for (station, climate_day), span in sorted(spans.items())
                    ],
                }
                handle.write(json.dumps(payload, sort_keys=True))
                handle.write("\n")
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


def read_instance_span_cache(path: Path) -> dict[CacheKey, dict[tuple[str, str], InstanceSpan]]:
    """Absent file = empty cache. Refuses an unrecognised ``schema_version``,
    a non-object line, a missing top-level key, or a top-level key of the
    wrong type -- always :class:`InstanceSpanCacheCorruptError` naming the
    bad key, never a bare `KeyError`/`TypeError`/`AttributeError`."""
    if not path.exists():
        return {}
    cache: dict[CacheKey, dict[tuple[str, str], InstanceSpan]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, Mapping):
                raise InstanceSpanCacheCorruptError(
                    f"{path}:{line_number}: instance_spans cache line is not a JSON "
                    f"object, got {type(payload).__name__}"
                )
            version = payload.get("schema_version")
            if version != INSTANCE_SPANS_SCHEMA_VERSION:
                raise UnknownInstanceSpanCacheSchemaError(
                    f"{path}:{line_number}: unknown instance_span_cache schema_version "
                    f"{version!r} (expected {INSTANCE_SPANS_SCHEMA_VERSION})"
                )
            instance_id = _require_top_level_key(
                payload, "instance_id", str, path=path, line_number=line_number,
            )
            fingerprint = _require_top_level_key(
                payload, "fingerprint", str, path=path, line_number=line_number,
            )
            algo_version = _require_top_level_key(
                payload, "algo_version", int, path=path, line_number=line_number,
            )
            if "spans" not in payload:
                raise InstanceSpanCacheCorruptError(
                    f"{path}:{line_number}: instance_spans cache line missing key 'spans'"
                )
            spans_payload = payload["spans"]
            if not isinstance(spans_payload, list):
                raise InstanceSpanCacheCorruptError(
                    f"{path}:{line_number}: 'spans' must be a list, "
                    f"got {type(spans_payload).__name__}"
                )
            spans: dict[tuple[str, str], InstanceSpan] = {}
            for row in spans_payload:
                key, span = _row_to_span(row, instance_id=instance_id)  # type: ignore[arg-type]
                spans[key] = span
            cache[(instance_id, fingerprint, algo_version)] = spans  # type: ignore[index]
    return cache


def lookup(
    cache: Mapping[CacheKey, StationDaySpans],
    *,
    instance_id: str,
    fingerprint: str,
    algo_version: int = SPAN_ALGO_VERSION,
) -> StationDaySpans | None:
    """``None`` on a miss: absent entry, fingerprint mismatch, or algo-version bump."""
    return cache.get((instance_id, fingerprint, algo_version))
