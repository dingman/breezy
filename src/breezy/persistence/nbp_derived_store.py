"""SL-4: the durable, on-disk derived store for backfilled NBM NBP quantile rows.

WHAT THIS IS. The schema, dedupe rule and file-level persistence primitives
for `scripts/analysis/nbp_backfill.py`'s output: one row per (station,
cycle_runtime, variable, valid window), written as Arrow/Parquet, partitioned
by the cycle's UTC year/month. This module owns the on-disk SHAPE and the
DEDUPE RULE; it does not fetch or parse a bulletin (`breezy.ingest.
nbm_quantile_transport`/`nbm_quantile_parse`, both a layer above this one)
and it does not orchestrate a run (the script does).

WHAT IT IS NOT. Not `breezy.persistence.archive_cache.ArchiveCache`: that
cache owns RAW, content-addressed request/response payloads for the
settlement-adjacent archive corpora and is on the forbidden-import list for
`breezy.settlement`/`breezy.strategy` (pyproject.toml, "Settlement and
strategy code never reaches archived backfill records"). This module is a
DERIVED store -- already-parsed quantile rows, never a raw payload -- and it
is added to that SAME forbidden list under its own name (L-12, R2-13/R3-08):
live strategy code must reach NBP calibration only through the sha-pinned
manifest artefact S2 produces (plan §3.2 item 9), never by importing a
backfill script's own store directly.

DEDUPE (R2-13 / R3-08, branch (b) -- BBB absent). `docs/evidence/
NBP_TXN_WINDOW_AND_BBB_NOTE_2026-09-29.md` part (b) pins the WMO BBB
correction/retransmission indicator ABSENT on every real NBP station-header
line examined (16/16, both v5.0 and v4.2-era captures): the `blend_nbptx`
files are served flat from AWS S3/NOMADS, never routed through the NWS
telecommunications gateway that stamps that token. Branch (a) ("BBB verified
present") is therefore out of scope for this slice -- the plan's own
branching rule (§7 row 4) degrades explicitly to branch (b):
`max(LastModified, raw_sha256)` per (station, cycle_runtime, variable, valid
window), never BBB rank. `dedupe_rows` implements ONLY this branch; a run
that ever discovers a BBB token on a real capture must revisit SL-2's note
and this module's ordering before trusting it.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Sequence
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Final

import pyarrow as pa
import pyarrow.parquet as pq

from breezy.domain.forecast_point import MINIMUM_PUBLICATION_LAG_NS

__all__ = [
    "NBP_DERIVED_SCHEMA",
    "NBP_DERIVED_SCHEMA_VERSION",
    "PUBLICATION_LAG_FLOOR_NS",
    "DedupeLog",
    "DerivedNbpRow",
    "FailureEntry",
    "ManifestEntry",
    "available_at_ns",
    "dedupe_rows",
    "derived_row_key",
    "failure_ledger_path",
    "load_failure_ledger",
    "load_manifest",
    "manifest_key",
    "manifest_path",
    "partition_path",
    "read_partition",
    "record_failure",
    "record_success",
    "rows_to_table",
    "table_to_rows",
    "write_partition",
]

NBP_DERIVED_SCHEMA_VERSION: Final[int] = 1

#: The SL-1b NBP publication-lag floor -- the ONE copy (`forecast_point.py`),
#: reused rather than re-declared, so this store can never drift from the
#: floor `ForecastPoint` itself enforces.
PUBLICATION_LAG_FLOOR_NS: Final[int] = MINIMUM_PUBLICATION_LAG_NS["NBM_NBP"]

NBP_DERIVED_SCHEMA: Final[pa.Schema] = pa.schema(
    [
        pa.field("station", pa.string(), nullable=False),
        pa.field("variable", pa.string(), nullable=False),
        pa.field("cycle_runtime_ns", pa.int64(), nullable=False),
        pa.field("valid_start_ns", pa.int64(), nullable=False),
        pa.field("valid_end_ns", pa.int64(), nullable=False),
        pa.field("value_f", pa.float64(), nullable=True),
        pa.field("absence_reason", pa.string(), nullable=True),
        pa.field("header_model_version", pa.string(), nullable=False),
        pa.field("nbm_version_era", pa.string(), nullable=False),
        pa.field("version_break_mismatch", pa.bool_(), nullable=False),
        pa.field("available_at_ns", pa.int64(), nullable=False),
        pa.field("last_modified", pa.string(), nullable=True),
        pa.field("source_host", pa.string(), nullable=False),
        pa.field("raw_sha256", pa.string(), nullable=False),
        pa.field("fetched_at_ns", pa.int64(), nullable=False),
        pa.field("schema_version", pa.int32(), nullable=False),
    ]
)


@dataclass(frozen=True, slots=True)
class DerivedNbpRow:
    """One station's one TXN quantile/summary-stat field for one NBP cycle.

    Mirrors `nbm_quantile_parse.NbpQuantilePoint` plus the provenance and
    version-tagging fields SL-4 adds: `header_model_version` /
    `nbm_version_era` / `version_break_mismatch` (item 5), `available_at_ns`
    (item 1, `max(LastModified, cycle+floor)`), and `source_host` /
    `raw_sha256` / `last_modified` / `fetched_at_ns` (fetch provenance).
    """

    station: str
    variable: str
    cycle_runtime_ns: int
    valid_start_ns: int
    valid_end_ns: int
    value_f: float | None
    absence_reason: str | None
    header_model_version: str
    nbm_version_era: str
    version_break_mismatch: bool
    available_at_ns: int
    last_modified: str | None
    source_host: str
    raw_sha256: str
    fetched_at_ns: int
    schema_version: int = NBP_DERIVED_SCHEMA_VERSION


DerivedRowKey = tuple[str, int, str, int, int]


def derived_row_key(row: DerivedNbpRow) -> DerivedRowKey:
    """The dedupe/join identity: (station, cycle_runtime, variable, valid window)."""
    return (row.station, row.cycle_runtime_ns, row.variable, row.valid_start_ns, row.valid_end_ns)


def available_at_ns(*, cycle_runtime_ns: int, last_modified_ns: int | None) -> int:
    """`max(LastModified, cycle + floor)` -- plan §3.2 item 1, the SL-1b floor.

    `last_modified_ns` is `None` when the fetch carried no `Last-Modified`
    header (or it could not be parsed): the floor alone then governs, which
    is always AT LEAST as conservative as a present-but-unusable header would
    have been.
    """
    floor_ns = cycle_runtime_ns + PUBLICATION_LAG_FLOOR_NS
    if last_modified_ns is None:
        return floor_ns
    return max(last_modified_ns, floor_ns)


def parse_http_last_modified(value: str | None) -> dt.datetime | None:
    """Parse an HTTP `Last-Modified` header (RFC 2822/1123) to an aware UTC datetime.

    Returns `None` for a missing or unparseable header -- never raises: a
    malformed upstream header must degrade the dedupe ranking, not crash the
    backfill.
    """
    if value is None:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.astimezone(dt.UTC)


@dataclass(frozen=True, slots=True)
class DedupeLog:
    """Counts from one `dedupe_rows` call -- reported, never silent."""

    kept: int
    collapsed_identical_sha: int
    retransmissions_resolved: int
    ties_resolved_by_sha: int


#: The floor used when a row's `last_modified` cannot be parsed -- always
#: ranks below any real timestamp, so an unparseable header never wins a
#: dedupe race it has no legitimate claim to.
_UNRANKED_LAST_MODIFIED: Final[dt.datetime] = dt.datetime.min.replace(tzinfo=dt.UTC)


def _rank(row: DerivedNbpRow) -> tuple[dt.datetime, str]:
    """No-BBB dedupe ordering (branch (b)): `max(LastModified, raw_sha256)`."""
    parsed = parse_http_last_modified(row.last_modified)
    return (parsed if parsed is not None else _UNRANKED_LAST_MODIFIED, row.raw_sha256)


def dedupe_rows(rows: Sequence[DerivedNbpRow]) -> tuple[tuple[DerivedNbpRow, ...], DedupeLog]:
    """Deterministic no-BBB dedupe: per key, keep `max(LastModified, raw_sha256)`.

    Byte-identical `raw_sha256` duplicates for the same key collapse WITHOUT
    being counted as a retransmission (they are the same fetch, refetched --
    never evidence of a correction). A genuine `LastModified` disagreement
    (a real retransmission) keeps the newer one. A `LastModified` TIE
    (including two rows that both carry no usable header) resolves
    deterministically on `raw_sha256` -- the sort is total, so the result
    never depends on input order.
    """
    by_key: dict[DerivedRowKey, list[DerivedNbpRow]] = {}
    for row in rows:
        by_key.setdefault(derived_row_key(row), []).append(row)

    kept: list[DerivedNbpRow] = []
    collapsed = 0
    retransmissions = 0
    ties = 0
    for group in by_key.values():
        distinct_by_sha: dict[str, DerivedNbpRow] = {}
        for row in group:
            distinct_by_sha.setdefault(row.raw_sha256, row)
        collapsed += len(group) - len(distinct_by_sha)

        candidates = list(distinct_by_sha.values())
        if len(candidates) == 1:
            kept.append(candidates[0])
            continue

        ranked = sorted(candidates, key=_rank, reverse=True)
        winner = ranked[0]
        winner_lm = parse_http_last_modified(winner.last_modified) or _UNRANKED_LAST_MODIFIED
        tied_on_last_modified = [
            c
            for c in candidates
            if (parse_http_last_modified(c.last_modified) or _UNRANKED_LAST_MODIFIED) == winner_lm
        ]
        if len(tied_on_last_modified) > 1:
            ties += 1
        else:
            retransmissions += 1
        kept.append(winner)

    return tuple(kept), DedupeLog(
        kept=len(kept),
        collapsed_identical_sha=collapsed,
        retransmissions_resolved=retransmissions,
        ties_resolved_by_sha=ties,
    )


# ---------------------------------------------------------------------------
# Arrow / Parquet round-trip.
# ---------------------------------------------------------------------------

_FIELD_NAMES: Final[tuple[str, ...]] = tuple(field.name for field in NBP_DERIVED_SCHEMA)


def rows_to_table(rows: Sequence[DerivedNbpRow]) -> pa.Table:
    columns: dict[str, list[Any]] = {name: [] for name in _FIELD_NAMES}
    for row in rows:
        columns["station"].append(row.station)
        columns["variable"].append(row.variable)
        columns["cycle_runtime_ns"].append(row.cycle_runtime_ns)
        columns["valid_start_ns"].append(row.valid_start_ns)
        columns["valid_end_ns"].append(row.valid_end_ns)
        columns["value_f"].append(row.value_f)
        columns["absence_reason"].append(row.absence_reason)
        columns["header_model_version"].append(row.header_model_version)
        columns["nbm_version_era"].append(row.nbm_version_era)
        columns["version_break_mismatch"].append(row.version_break_mismatch)
        columns["available_at_ns"].append(row.available_at_ns)
        columns["last_modified"].append(row.last_modified)
        columns["source_host"].append(row.source_host)
        columns["raw_sha256"].append(row.raw_sha256)
        columns["fetched_at_ns"].append(row.fetched_at_ns)
        columns["schema_version"].append(row.schema_version)
    return pa.Table.from_pydict(columns, schema=NBP_DERIVED_SCHEMA)


def table_to_rows(table: pa.Table) -> tuple[DerivedNbpRow, ...]:
    return tuple(DerivedNbpRow(**record) for record in table.to_pylist())


def partition_path(output_dir: Path, cycle_date: dt.date, cycle_hour: int) -> Path:
    """One file per (date, cycle) -- the per-file checkpoint unit itself."""
    return (
        output_dir
        / f"{cycle_date.year:04d}"
        / f"{cycle_date.month:02d}"
        / f"nbp_{cycle_date:%Y%m%d}_{cycle_hour:02d}z.parquet"
    )


def write_partition(rows: Sequence[DerivedNbpRow], path: Path) -> DedupeLog:
    """Deduped, atomic write: temp file in the same directory, then rename."""
    deduped, log = dedupe_rows(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = rows_to_table(deduped)
    tmp = path.with_name(path.name + ".tmp")
    pq.write_table(table, tmp)
    tmp.replace(path)
    return log


def read_partition(path: Path) -> tuple[DerivedNbpRow, ...]:
    return table_to_rows(pq.read_table(path, schema=NBP_DERIVED_SCHEMA))


# ---------------------------------------------------------------------------
# Manifest (resumable per-file checkpoint) + failure ledger.
# ---------------------------------------------------------------------------

_MANIFEST_FILENAME: Final[str] = "_manifest.json"
_FAILURE_LEDGER_FILENAME: Final[str] = "_failures.json"


def manifest_key(cycle_date: dt.date, cycle_hour: int) -> str:
    return f"{cycle_date.isoformat()}:{cycle_hour:02d}"


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One completed (date, cycle) checkpoint. Never means "this cycle had
    every requested station" -- a station absent from the bulletin is a
    parser-level drop, reported by the caller, not a manifest field."""

    cycle_date: str
    cycle_hour: int
    source_host: str
    raw_sha256: str
    rows: int
    parquet_path: str
    completed_at_ns: int


@dataclass(frozen=True, slots=True)
class FailureEntry:
    """One (date, cycle) that failed on BOTH hosts. No row is ever written
    for a key on this ledger -- see `scripts/analysis/nbp_backfill.py`."""

    cycle_date: str
    cycle_hour: int
    primary_error: str
    fallback_error: str
    failed_at_ns: int


def manifest_path(output_dir: Path) -> Path:
    return output_dir / _MANIFEST_FILENAME


def failure_ledger_path(output_dir: Path) -> Path:
    return output_dir / _FAILURE_LEDGER_FILENAME


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def load_manifest(output_dir: Path) -> dict[str, ManifestEntry]:
    path = manifest_path(output_dir)
    if not path.exists():
        return {}
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    return {
        item["key"]: ManifestEntry(
            cycle_date=item["cycle_date"],
            cycle_hour=item["cycle_hour"],
            source_host=item["source_host"],
            raw_sha256=item["raw_sha256"],
            rows=item["rows"],
            parquet_path=item["parquet_path"],
            completed_at_ns=item["completed_at_ns"],
        )
        for item in payload
    }


def record_success(output_dir: Path, key: str, entry: ManifestEntry) -> None:
    manifest = load_manifest(output_dir)
    manifest[key] = entry
    payload = [
        {
            "key": k,
            "cycle_date": e.cycle_date,
            "cycle_hour": e.cycle_hour,
            "source_host": e.source_host,
            "raw_sha256": e.raw_sha256,
            "rows": e.rows,
            "parquet_path": e.parquet_path,
            "completed_at_ns": e.completed_at_ns,
        }
        for k, e in sorted(manifest.items())
    ]
    _atomic_write_json(manifest_path(output_dir), payload)


def load_failure_ledger(output_dir: Path) -> dict[str, FailureEntry]:
    path = failure_ledger_path(output_dir)
    if not path.exists():
        return {}
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    return {
        item["key"]: FailureEntry(
            cycle_date=item["cycle_date"],
            cycle_hour=item["cycle_hour"],
            primary_error=item["primary_error"],
            fallback_error=item["fallback_error"],
            failed_at_ns=item["failed_at_ns"],
        )
        for item in payload
    }


def record_failure(output_dir: Path, key: str, entry: FailureEntry) -> None:
    ledger = load_failure_ledger(output_dir)
    ledger[key] = entry
    payload = [
        {
            "key": k,
            "cycle_date": e.cycle_date,
            "cycle_hour": e.cycle_hour,
            "primary_error": e.primary_error,
            "fallback_error": e.fallback_error,
            "failed_at_ns": e.failed_at_ns,
        }
        for k, e in sorted(ledger.items())
    ]
    _atomic_write_json(failure_ledger_path(output_dir), payload)
