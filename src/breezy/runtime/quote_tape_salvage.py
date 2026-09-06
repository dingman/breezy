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
  ``convert_stream_to_data``. Caught narrowly: ``ValueError`` (deserialisation
  or non-disjoint-interval refusal), ``pyarrow.ArrowInvalid`` (a salvaged
  table that still fails a later Arrow operation), ``OSError`` (the
  file vanishing or becoming unreadable between preflight and salvage), and
  ``NotImplementedError`` (``ArrowSerializer._deserialize_rust`` when the
  type's Rust wrangler is ``None`` -- measured for ``MarkPriceUpdate``,
  also ``InstrumentClose`` / ``IndexPriceUpdate``). A
  ``MemoryError``/``RecursionError`` is deliberately NOT caught here, for the
  same reason ``_read_streamed`` does not catch it: it says nothing about
  this file and everything about the process.

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

import pyarrow as pa
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.persistence.funcs import class_to_filename

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

#: Exceptions isolated to the ONE truncated file that raised them. Mirrors
#: ``ingest_instance``'s own ``except ValueError`` isolation, widened to the
#: failure modes salvage can hit that a plain conversion cannot: a salvaged
#: table that still fails a later Arrow operation, the file vanishing
#: between preflight and salvage, or a type whose Arrow wrangler is ``None``
#: (``ArrowSerializer._deserialize_rust`` raises ``NotImplementedError``).
_ISOLATED_ERRORS: tuple[type[BaseException], ...] = (
    ValueError,
    pa.ArrowInvalid,
    OSError,
    NotImplementedError,
)


def _salvage_marker_path(instance_dir: Path, file_path: Path) -> Path:
    return instance_dir / f"{SALVAGE_MARKER_PREFIX}{file_path.name}"


def _is_salvage_marked(instance_dir: Path, file_path: Path) -> bool:
    return _salvage_marker_path(instance_dir, file_path).is_file()


def _mark_salvaged(instance_dir: Path, file_path: Path) -> None:
    _salvage_marker_path(instance_dir, file_path).touch()


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


def _drop_already_landed(
    write_target: ParquetDataCatalog, data_cls: type, objects: list[Any]
) -> list[Any]:
    """Filter out every object whose ``(instrument_id, ts_init)`` is already landed."""
    identifiers = sorted(
        {key[0] for obj in objects if (key := _object_key(obj))[0] is not None}
    )
    existing = (
        write_target.query(data_cls=data_cls, identifiers=identifiers)
        if identifiers
        else write_target.query(data_cls=data_cls)
    )
    known = {_object_key(landed) for landed in existing}
    return [obj for obj in objects if _object_key(obj) not in known]


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

    objects = list(catalog._handle_table_nautilus(table=result.table, data_cls=data_cls))
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
