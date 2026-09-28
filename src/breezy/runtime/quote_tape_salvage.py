"""Salvage the recoverable prefix of a truncated quote-tape feather file.

Split out of :mod:`breezy.runtime.quote_tape_ingest_cli` (which still owns
quarantine/refusal and calls into this module) purely to keep that file under
the 800-line ceiling; the behaviour and its guarantees are unchanged.

Quarantine is untouched by anything here: nothing in this module writes the
``.converted-<type>`` marker, so a truncated instance still refuses full
conversion via the ordinary path on every run. Salvage only ever ADDS rows
that were otherwise silently lost.

Two safety properties, both load-bearing:

* **The truncated source is never touched.** ``salvage_feather_file`` only
  reads (``feather_preflight.py:301-306``: ``pa.OSFile`` opened read-only),
  so the file the operator may need for forensics is preserved byte-for-byte.
* **A salvage failure is isolated to its own file.** A `_handle_table_nautilus`
  or `write_data` failure on one truncated file must never abort the
  remaining files, types, or instances -- exactly the isolation
  ``ingest_instance`` already gives an ordinary ``ValueError`` from
  ``convert_stream_to_data``. Two kinds of isolation, in two branches:
  a RETRYABLE one -- ``ValueError`` (deserialisation or non-disjoint-interval
  refusal), ``pyarrow.ArrowInvalid`` (a salvaged table that still fails a
  later Arrow operation), ``OSError`` (the file vanishing or becoming
  unreadable between preflight and salvage), and a plain ``NotImplementedError``
  from anywhere other than deserialisation -- left unmarked so a later run
  may retry; and a TERMINAL one -- a ``NotImplementedError`` raised
  specifically by the deserialise call-site
  (``ArrowSerializer._deserialize_rust`` when the type's Rust wrangler is
  ``None`` -- measured for ``MarkPriceUpdate``, also ``InstrumentClose`` /
  ``IndexPriceUpdate``), narrowed via the private :class:`_UnsupportedSalvageType`
  sentinel so no other ``NotImplementedError`` is misclassified -- deterministic
  and permanent for the installed Nautilus version, so it earns its own marker
  (:data:`SALVAGE_UNSUPPORTED_PREFIX`) instead of being retried forever
  (FU-7 item 4). A ``MemoryError``/``RecursionError`` is deliberately NOT
  caught here, for the same reason ``_read_streamed`` does not catch it: it
  says nothing about this file and everything about the process.

De-duplication before writing salvaged rows
--------------------------------------------
``write_data(..., skip_disjoint_check=True)`` bypasses the ONLY native guard
against writing the same rows twice, so salvage must not rely on it being
run-once. The idempotency marker (`SALVAGE_MARKER_PREFIX`) stops the SAME
truncated file from being salvaged twice, but says nothing about a DIFFERENT
instance's rows landing at an overlapping ``(instrument_id, ts_init)`` --
capture-timed types are monotonic within one recorder run but nothing stops
two rotations, or a hand-seeded catalog, from sharing a moment. Before
writing, this module queries the write target for existing rows of the same
type filtered to the instrument ids present in the salvaged batch (cheap:
proportional to one instrument's existing data, not the whole type) and drops
every row whose ``(instrument_id, ts_init)`` is already landed -- the exact
precedent :func:`breezy.runtime.quote_tape_ingest_cli.convert_instrument_definitions`
sets for instrument definitions, generalised to any data class.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import nautilus_trader
import pyarrow as pa
import pyarrow.parquet as pq
from nautilus_trader.model.data import CustomData, OrderBookDepth10, QuoteTick, TradeTick
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.persistence.funcs import class_to_filename

from breezy.adapters.polymarket_us.tape_records import DepthTruncation
from breezy.persistence.feather_preflight import FeatherFileReport, salvage_feather_file

logger = logging.getLogger(__name__)

#: Prefix for the per-truncated-file salvage marker. Deliberately keyed to
#: the FILE, not the (instance, data type) pair the ingest CLI's own
#: `MARKER_PREFIX` uses: a truncated instance never earns `.converted-<type>`
#: (full conversion stays refused), so idempotency for the salvaged prefix
#: needs its own marker. Safe without content-level de-duplication of THIS
#: file's own rows only because a quarantined instance's bytes never change
#: again -- nothing re-truncates it further.
SALVAGE_MARKER_PREFIX = ".salvaged-"

#: Prefix for the TERMINAL per-truncated-file marker written when the type's
#: Arrow wrangler is ``None`` (``NotImplementedError``, FU-7 item 4). Unlike
#: ``SALVAGE_MARKER_PREFIX``, this never claims rows were landed -- reusing
#: ``_mark_salvaged`` here would mislead forensics and flip the ``:1144``
#: pin in ``test_quote_tape_ingest_cli.py`` (the "no Arrow wrangler"
#: isolation test). The failure is deterministic for the installed Nautilus
#: version (verified against ``serializer.py:328-347``), so there is no
#: retry -- delete the marker to retry after a Nautilus upgrade that might
#: add the missing wrangler.
SALVAGE_UNSUPPORTED_PREFIX = ".salvage-unsupported-"

#: Exceptions isolated to the ONE truncated file that raised them. Mirrors
#: ``ingest_instance``'s own ``except ValueError`` isolation, widened to the
#: failure modes salvage can hit that a plain conversion cannot: a salvaged
#: table that still fails a later Arrow operation, or the file vanishing
#: between preflight and salvage. ``NotImplementedError`` (a type whose
#: Arrow wrangler is ``None``) is handled separately, in its own terminal
#: branch below -- see :data:`SALVAGE_UNSUPPORTED_PREFIX`.
_ISOLATED_ERRORS: tuple[type[BaseException], ...] = (
    ValueError,
    pa.ArrowInvalid,
    OSError,
    NotImplementedError,
)


class _UnsupportedSalvageType(Exception):
    """Sentinel: the deserialise call-site raised ``NotImplementedError``.

    Raised ONLY around ``catalog._handle_table_nautilus`` in
    :func:`_salvage_one_file` -- the sole reachable ``NotImplementedError``
    site is ``ArrowSerializer._deserialize_rust`` (deterministic per
    installed Nautilus version). Caught immediately by
    :func:`salvage_truncated_instance` to write the terminal marker; never
    escapes this module. A ``NotImplementedError`` raised anywhere else (the
    write path, a future query-side call) is NOT wrapped here, so it falls
    through to :data:`_ISOLATED_ERRORS` above and is treated as an ordinary
    retryable failure instead of being wrongly marked terminal.
    """

    def __init__(self, original: NotImplementedError) -> None:
        super().__init__(str(original))
        self.original = original


def _salvage_marker_path(instance_dir: Path, file_path: Path) -> Path:
    return instance_dir / f"{SALVAGE_MARKER_PREFIX}{file_path.name}"


def _salvage_unsupported_marker_path(instance_dir: Path, file_path: Path) -> Path:
    return instance_dir / f"{SALVAGE_UNSUPPORTED_PREFIX}{file_path.name}"


def _is_salvage_marked(instance_dir: Path, file_path: Path) -> bool:
    return (
        _salvage_marker_path(instance_dir, file_path).is_file()
        or _salvage_unsupported_marker_path(instance_dir, file_path).is_file()
    )


def _mark_salvaged(instance_dir: Path, file_path: Path) -> None:
    _salvage_marker_path(instance_dir, file_path).touch()


def _mark_salvage_unsupported(instance_dir: Path, file_path: Path) -> None:
    """Terminal marker: this file's type has no Arrow wrangler to salvage it.

    Written empty (``touch``), like every sibling marker in this module and
    in ``quote_tape_ingest_cli`` (``SALVAGE_MARKER_PREFIX``,
    ``FILE_MARKER_PREFIX``, ``MARKER_PREFIX``): the marker's own filename
    ends in ``.feather``, so a non-empty, non-Arrow body would make the
    preflight scanner's own byte-level walk (``iter_feather_files`` globs
    ``*.feather``) misclassify the MARKER ITSELF as a truncated Arrow
    stream, poisoning ``needs_salvage_work`` in
    ``quote_tape_ingest_cli._ingest_instance_per_file`` with a phantom
    truncated file (measured: a text body flips this marker to
    ``FeatherStatus.TRUNCATED``, defeating AC4). An empty file classifies as
    ``EMPTY_FILE`` instead, exactly like the existing markers. The installed
    Nautilus version is recorded in the ERROR log line instead (AC3), and
    that log line names this marker's path for the delete-to-retry
    instruction.
    """
    _salvage_unsupported_marker_path(instance_dir, file_path).touch()


def _file_belongs_to_data_cls(instance_dir: Path, file_path: Path, data_cls: type) -> bool:
    """True if ``file_path`` is one of ``data_cls``'s feather files.

    Mirrors the two layouts ``StreamingFeatherWriter`` uses
    (``persistence/writer.py:422`` per-instrument, ``:466`` flat): either the
    file's immediate parent under the instance directory is the type's
    directory name, or its filename is prefixed with it.
    """
    cls_name = class_to_filename(data_cls)
    try:
        rel_parts = file_path.resolve().relative_to(instance_dir.resolve()).parts
    except ValueError:
        return False
    if not rel_parts:
        return False
    if rel_parts[0] == cls_name:
        return True
    return rel_parts[-1].startswith(f"{cls_name}_")


def _object_key(obj: Any) -> tuple[str | None, int]:
    instrument_id = getattr(obj, "instrument_id", None)
    return (instrument_id.value if instrument_id is not None else None, obj.ts_init)


def _catalog_row(item: Any) -> Any:
    return item.data if isinstance(item, CustomData) else item


def _drop_already_landed(
    write_target: ParquetDataCatalog, data_cls: type, objects: list[Any]
) -> list[Any]:
    """Filter out every object whose ``(instrument_id, ts_init)`` is already landed."""
    identifiers = sorted({key[0] for obj in objects if (key := _object_key(obj))[0] is not None})
    existing = (
        write_target.query(data_cls=data_cls, identifiers=identifiers)
        if identifiers
        else write_target.query(data_cls=data_cls)
    )
    known = {_object_key(_catalog_row(landed)) for landed in existing}
    return [obj for obj in objects if _object_key(obj) not in known]


#: The identifier-keyed types (ING-2-RSS, widened ING-2-AMEND2). For these,
#: and ONLY these, a guarded identifier-filtered query is attempted first --
#: every other type (InstrumentStatus, definitions such as ``BinaryOption``)
#: keeps the unconditional unfiltered query unchanged, so T4 and the tie-run
#: spy tests (``bounded_read.py:582-612``, ``:784-797``), which use
#: ``InstrumentStatus``, keep passing without edits. ``DepthTruncation``
#: joined the metadata-keyed Rust types (``QuoteTick``, ``TradeTick``,
#: ``OrderBookDepth10``) because it is a per-instrument-directory pyarrow-path
#: custom type with the SAME layout (ING-2-AMEND2: 839 per-instrument
#: subdirectories, 0 depth-1 files, 100% unfiltered EXTEND dispatch before
#: this fix).
_ID_FILTERABLE_TYPES = frozenset({QuoteTick, TradeTick, OrderBookDepth10, DepthTruncation})


class _ExtendDedupeCounters:
    """Per-process counts of the EXTEND dedupe dispatch (ING-2-RSS, L-30/L-52).

    Counts only -- never an instrument id or a value. Reset once per ingest
    run by :mod:`breezy.runtime.quote_tape_ingest_cli`'s ``run()`` so the
    summary line reflects exactly one run, even when several runs happen in
    one process (e.g. under pytest).
    """

    def __init__(self) -> None:
        self.chunks = 0
        self.filtered = 0
        self.unfiltered = 0
        #: ``class_to_filename`` name -> [filtered_count, unfiltered_count].
        self.by_type: dict[str, list[int]] = {}

    def record(self, data_cls: type, *, filtered: bool) -> None:
        self.chunks += 1
        if filtered:
            self.filtered += 1
        else:
            self.unfiltered += 1
        counts = self.by_type.setdefault(class_to_filename(data_cls), [0, 0])
        counts[0 if filtered else 1] += 1

    def reset(self) -> None:
        self.chunks = 0
        self.filtered = 0
        self.unfiltered = 0
        self.by_type.clear()

    def summary_line(self) -> str:
        by_type = ",".join(f"{name}:{f}/{u}" for name, (f, u) in sorted(self.by_type.items()))
        return (
            f"extend_dedupe: chunks={self.chunks} filtered={self.filtered} "
            f"unfiltered={self.unfiltered} by_type={by_type}"
        )


#: Module-level singleton (ING-2-RSS observability). Mutable by design: one
#: counters object per process, shared across every EXTEND chunk in a run.
extend_dedupe_counters = _ExtendDedupeCounters()


def _type_root_has_flat_files(write_target: ParquetDataCatalog, data_cls: type) -> bool:
    """True when ``data_cls``'s type root already holds a depth-1 (FLAT) file.

    The type-dir name comes from ``ParquetDataCatalog._make_path`` (native's
    own ``class_to_filename``-derived mapping, e.g. ``order_book_depths`` for
    ``OrderBookDepth10`` -- never hard-coded). A non-empty result means a
    ``convert_stream_to_data`` FLAT write landed here (``TestTheMixedCatalogLayoutIsPinned``),
    which an identifier-filtered query would silently omit.
    """
    type_root = write_target._make_path(data_cls=data_cls, identifier=None)
    return bool(_parquet_set(write_target, type_root))


def _drop_already_landed_unfiltered(
    write_target: ParquetDataCatalog, data_cls: type, objects: list[Any]
) -> list[Any]:
    """Drop landed rows already in the catalog, filtered when it is safe to.

    Identifier-filtered ``query`` silently omits FLAT ``convert_stream_to_data``
    files (``parquet.py:2249``; ``TestTheMixedCatalogLayoutIsPinned``). The
    ING-1 partial slice is exactly that layout, so EXTEND must see it.

    ING-2-RSS: for the identifier-keyed types (:data:`_ID_FILTERABLE_TYPES`),
    an unfiltered query deserialises every OTHER instrument's landed rows in
    the chunk's time window too, which is what drove EXTEND's memory and
    wall time up (root cause). When this data class's type root holds no
    FLAT file, an identifier-filtered query is exactly equivalent (nothing
    is omitted) and reads only this chunk's own instruments. When a FLAT
    file IS present -- or for every other type -- the query stays
    unfiltered, byte-identical to before. A read error (``ArrowInvalid``,
    ``FileNotFoundError``, etc.) is never caught here: turning it into an
    empty existing-set would mean silent duplicates.
    """
    if not objects:
        return []
    lo = min(obj.ts_init for obj in objects)
    hi = max(obj.ts_init for obj in objects)
    identifiers = sorted({key[0] for obj in objects if (key := _object_key(obj))[0] is not None})
    use_filtered = (
        data_cls in _ID_FILTERABLE_TYPES
        and bool(identifiers)
        and not _type_root_has_flat_files(write_target, data_cls)
    )
    if use_filtered:
        existing = write_target.query(data_cls=data_cls, identifiers=identifiers, start=lo, end=hi)
    else:
        existing = write_target.query(data_cls=data_cls, start=lo, end=hi)
    extend_dedupe_counters.record(data_cls, filtered=use_filtered)
    known = {_object_key(_catalog_row(landed)) for landed in existing}
    return [obj for obj in objects if _object_key(obj) not in known]


class ExtendWriteMismatch(ValueError):
    """An EXTEND write's row count on disk did not match what was fresh (A8).

    ``write_data``'s ``_write_chunk`` silently skips a write when its target
    filename already exists (a bare ``print``, ``parquet.py:378-380``) --
    indistinguishable on its own from a successful write. This detector
    turns that silent skip into a loud, reason-coded failure for the EXTEND
    path (ING-2 S3a, Arch §7 r3), where ``write_data``'s per-instrument
    filename usually differs from native's flat one, so a collision is a
    real, actionable anomaly rather than routine idempotent overlap. It
    covers EXTEND only: a same-directory, same-filename collision on the
    native fast/per-file path is RS-4, a named residual, and is not raised
    here. The message never contains "non-disjoint", so it is never
    misrouted into the non-disjoint-refusal handling in
    ``quote_tape_ingest_cli``, and it never names an instrument id or a
    value -- only counts.
    """


def _write_data_group(obj: Any) -> tuple[type, str | None]:
    """Mirror ``ParquetDataCatalog.write_data``'s grouping rule (``parquet.py:320-339``).

    Returns the ``(class, identifier)`` pair ``write_data`` will use to pick
    ``obj``'s directory: unwraps ``CustomData``, then applies native's
    four-branch rule -- an ``Instrument``'s ``id.value``, an object with
    ``bar_type``'s ``str(bar_type)``, an object with ``instrument_id``'s
    ``instrument_id.value``, or ``None`` otherwise. The identifier returned
    here is the RAW form; ``_make_path`` applies ``urisafe_identifier``
    itself, so it must never be pre-encoded.
    """
    if isinstance(obj, CustomData):
        obj = obj.data
    cls = type(obj)
    if isinstance(obj, Instrument):
        return cls, obj.id.value
    if hasattr(obj, "bar_type"):
        return cls, str(obj.bar_type)
    if hasattr(obj, "instrument_id"):
        return cls, obj.instrument_id.value
    return cls, None


def _parquet_set(write_target: ParquetDataCatalog, directory: str) -> set[str]:
    """The depth-1 ``*.parquet`` files directly under ``directory``.

    Depth-1 only, via ``fs.ls`` rather than ``fs.glob`` (r3.1: avoids
    glob-metacharacter interpretation in an instrument id or bar_type
    string). For a flat type root (identifier ``None``) this correctly
    excludes identifier subdirectories; for a per-instrument directory it is
    exactly the directory ``_write_chunk`` writes into
    (``parquet.py:370-380``).
    """
    if not write_target.fs.exists(directory):
        return set()
    return {
        entry for entry in write_target.fs.ls(directory, detail=False) if entry.endswith(".parquet")
    }


def _write_data_with_mismatch_detection(
    write_target: ParquetDataCatalog,
    data_cls: type,
    fresh: list[Any],
) -> None:
    """``write_data(fresh, skip_disjoint_check=True)``, guarded by A8.

    Scoped to the exact directories ``write_data`` will touch for ``fresh``
    (Arch §7 r3). Diffs each directory's depth-1 parquet set before and
    after the write, and sums the row counts of the new files from their
    footers (cheap: footer-only reads, never a full table read). If the sum
    does not equal ``len(fresh)``, raises :class:`ExtendWriteMismatch` --
    the file stays unmarked by the caller, and the run is retried.
    """
    dirs = {
        write_target._make_path(data_cls=cls, identifier=ident)
        for cls, ident in {_write_data_group(obj) for obj in fresh}
    }
    before: set[str] = set()
    for directory in dirs:
        before |= _parquet_set(write_target, directory)

    write_target.write_data(fresh, skip_disjoint_check=True)

    after: set[str] = set()
    for directory in dirs:
        after |= _parquet_set(write_target, directory)

    new_files = after - before
    written = sum(
        pq.read_metadata(new_file, filesystem=write_target.fs).num_rows for new_file in new_files
    )
    if written != len(fresh):
        raise ExtendWriteMismatch(
            f"extend write mismatch for {class_to_filename(data_cls)}: "
            f"expected {len(fresh)} row(s), landed {written} across {len(dirs)} dir(s)"
        )


def write_fresh_capture_rows(
    write_target: ParquetDataCatalog,
    data_cls: type,
    objects: list[Any],
) -> int:
    """Write capture-timed rows that are not already in the catalog.

    EXTEND for ING-1: new parquet records only, never a rewrite or a
    ``delete_data_range``. ``skip_disjoint_check=True`` is earned by the
    de-dupe, same contract as :func:`salvage_truncated_instance` and
    ``convert_instrument_definitions``. The write is guarded by the A8
    write-mismatch detector (:func:`_write_data_with_mismatch_detection`),
    which raises :class:`ExtendWriteMismatch` instead of silently losing
    rows to ``write_data``'s exists-skip.
    """
    fresh = _drop_already_landed_unfiltered(write_target, data_cls, objects)
    dropped = len(objects) - len(fresh)
    if dropped:
        logger.warning(
            "%d of %d capture-timed %s row(s) already landed (same "
            "instrument_id, ts_init); dropped to avoid a duplicate",
            dropped,
            len(objects),
            class_to_filename(data_cls),
        )
    if not fresh:
        return 0
    _write_data_with_mismatch_detection(write_target, data_cls, fresh)
    return len(fresh)


def salvage_truncated_instance(
    catalog: ParquetDataCatalog,
    instance_dir: Path,
    instance_id: str,
    data_types: Sequence[type],
    truncated_files: Sequence[FeatherFileReport],
    *,
    target: ParquetDataCatalog | None = None,
) -> None:
    """Land the recoverable prefix of every not-yet-salvaged truncated file.

    Deserialisation reuses ``ParquetDataCatalog._handle_table_nautilus``, the
    same private helper the native ``query`` (``parquet.py:2166``) and stream
    read paths (``:2591``) already use to turn a `pyarrow.Table` into typed
    objects -- there is no public wrapper for "table I already have in hand",
    so this is the smallest correct reuse of existing native machinery rather
    than a hand-rolled Arrow deserialiser.

    A failure salvaging one file is logged and skipped -- it never aborts a
    sibling file, data type, or instance. See the module docstring for
    exactly which exceptions that covers and why.
    """
    write_target = catalog if target is None else target
    for data_cls in data_types:
        cls_name = class_to_filename(data_cls)
        for report in truncated_files:
            if not _file_belongs_to_data_cls(instance_dir, report.path, data_cls):
                continue
            if _is_salvage_marked(instance_dir, report.path):
                continue

            try:
                _salvage_one_file(
                    catalog, write_target, instance_dir, instance_id, cls_name, data_cls, report
                )
            except _UnsupportedSalvageType as exc:
                original = exc.original
                marker_path = _salvage_unsupported_marker_path(instance_dir, report.path)
                logger.error(
                    "instance %s: salvage of %s truncated file %s skipped %s "
                    "[reason=unsupported_type] no Arrow wrangler in nautilus %s: %s; "
                    "rows NOT landed; marked terminal; delete %s to retry",
                    instance_id,
                    cls_name,
                    report.path,
                    type(original).__name__,
                    nautilus_trader.__version__,
                    original,
                    marker_path,
                )
                _mark_salvage_unsupported(instance_dir, report.path)
                continue
            except _ISOLATED_ERRORS as exc:
                logger.error(
                    "instance %s: salvage of %s truncated file %s failed -- %s: %s -- "
                    "skipped, no marker written so a later run may retry",
                    instance_id,
                    cls_name,
                    report.path,
                    type(exc).__name__,
                    exc,
                )
                continue


def _salvage_one_file(
    catalog: ParquetDataCatalog,
    write_target: ParquetDataCatalog,
    instance_dir: Path,
    instance_id: str,
    cls_name: str,
    data_cls: type,
    report: FeatherFileReport,
) -> None:
    result = salvage_feather_file(report.path)
    if result.table is None or result.rows_recovered == 0:
        logger.warning(
            "instance %s: %s truncated file %s recovered no rows -- %s",
            instance_id,
            cls_name,
            report.path,
            result.describe(),
        )
        _mark_salvaged(instance_dir, report.path)
        return

    try:
        objects = list(catalog._handle_table_nautilus(table=result.table, data_cls=data_cls))
    except NotImplementedError as exc:
        raise _UnsupportedSalvageType(exc) from exc
    fresh = _drop_already_landed(write_target, data_cls, objects)
    duplicates = len(objects) - len(fresh)
    if duplicates:
        logger.warning(
            "instance %s: %d of %d salvaged %s row(s) from %s already landed "
            "(same instrument_id, ts_init); skipped to avoid a duplicate",
            instance_id,
            duplicates,
            len(objects),
            cls_name,
            report.path,
        )

    if fresh:
        write_target.write_data(fresh, skip_disjoint_check=True)

    logger.error(
        "instance %s: salvaged %d row(s) of %s from truncated file %s "
        "(%d already landed and skipped; bytes_lost=%d of %d total; rows "
        "lost is UNKNOWN -- the incomplete trailing Arrow message's row "
        "count is not on disk); the truncated file is preserved untouched "
        "for forensics",
        instance_id,
        len(fresh),
        cls_name,
        report.path,
        duplicates,
        result.bytes_lost,
        report.size_bytes,
    )
    _mark_salvaged(instance_dir, report.path)
