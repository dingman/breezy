"""The `breezy-quote-tape-ingest` console entrypoint.

Closes the gap ``breezy.runtime.quote_tape_cli`` deliberately left open: the
recorder streams Arrow IPC feather under ``<catalog>/live/<instance>/``, and
turning that into the parquet layout every analysis script queries is a
single native call (``ParquetDataCatalog.convert_stream_to_data``) that
nothing has ever automated. It had been run by hand twice, ever -- 199,079
depth rows for 2026-09-01 afternoon were invisible on disk until a manual
conversion.

A SEPARATE process from the recorder and from the preflight checker, for the
same reason those two are separate from each other: different failure
consequences. This one holds no venue credential, opens no socket, and never
signals the recorder -- it only reads feather bytes and writes parquet plus
its own marker files.

Null hypothesis, checked before writing any of this:

* **Conversion is native.** ``ParquetDataCatalog.convert_stream_to_data``
  (``persistence/catalog/parquet.py:2604``) does the feather -> parquet work.
  This module supplies only instance enumeration, live-write avoidance,
  truncation refusal, and idempotency bookkeeping around that one call.
* **Per-file idempotency is ALREADY native but insufficient alone.**
  ``_convert_feather_table_to_parquet`` skips a parquet file that already
  exists at the same name (a bare ``print``, ``parquet.py`` ~:2680) and
  raises ``ValueError`` on a non-disjoint-but-different interval. That makes
  a byte-identical re-run safe, but says nothing about SKIPPING the re-scan
  of an instance already known to be fully converted, and nothing about
  isolating one data type's ``ValueError`` from the rest -- both handled here.
* **Row-wise writing is native too.** ``ParquetDataCatalog.write_data`` takes
  ``skip_disjoint_check=True`` (``parquet.py:255-310``, documented as the
  escape "when consolidating or re-writing chunks where you manage intervals
  explicitly") and ``read_live_run``/``read_backtest`` (``:2519``, ``:2541``)
  read a stream back as deserialised objects. No native path converts a
  stream WITH the check skipped -- ``convert_stream_to_data`` exposes no such
  parameter -- so the instrument-definition path below is the smallest
  composition of those two public calls, not new persistence machinery.

Instrument definitions convert row-wise (the re-emission defect)
----------------------------------------------------------------
``convert_stream_to_data`` converts feather files ONE AT A TIME, deriving
each file's interval from ``[min ts_init, max ts_init]``, and raises
``ValueError`` when that interval overlaps one already in the type's data
directory. For capture-timed types (quotes, depth, trades) intervals are
monotonic and never overlap. Instrument definitions are different in kind:
the recorder re-emits a definition with its ORIGINAL ``ts_init``, so a later
one-row file's POINT interval lands strictly inside the interval of the
initial multi-row file. That overlap is permanent -- it refused
``BinaryOption`` on every timer run for three days, and the first refusal
also aborted the remaining feather files of that type.

So for types whose ``ts_init`` is a definition stamp rather than a capture
stamp (:func:`_is_instrument_definition`), this module reads the streamed
objects, drops every ``(instrument_id, ts_init)`` already present in the
catalog, and writes only what is genuinely new with
``skip_disjoint_check=True``. De-duplication is what makes skipping the check
safe: the check exists to stop the same rows being written twice, and that
property is enforced here directly instead. Every other type keeps the single
native call unchanged.

Live-write avoidance (the hard safety property)
------------------------------------------------
A feather stream with no end-of-stream marker must never be converted
mid-write: the tail of a live writer's buffer is byte-identical to a
genuinely truncated one, and ``convert_stream_to_data`` would either read a
partial trailing message as if it were complete or silently deliver zero rows
for it (see :mod:`breezy.persistence.feather_preflight`). An instance is
classified LIVE -- and skipped entirely -- if EITHER:

(a) any file under it was written within the configurable grace window
    (default 30 minutes), OR
(b) it is the most-recently-STARTED instance (the one whose earliest file
    mtime is the latest among all instances) AND the recorder's systemd unit
    is currently reported active.

Neither rule alone is robust. (a) alone misses a live-but-quiet instance: the
writer only flushes when it has something to flush
(``QUOTE_TAPE_FLUSH_INTERVAL_MS``), so a dead-quiet market for longer than the
grace window leaves a genuinely live instance looking idle. (b) alone would
pin the newest directory as permanently live even after the recorder has
exited, since a new instance directory is created on every process start
regardless of whether the previous one saw any writes. Combined, an instance
is only ever treated as non-live when there is no recent write AND it is
either not the current instance or the recorder has exited -- exactly when a
missing end-of-stream marker means "abandoned", never "mid-write". The
service-active probe issues ``systemctl --user is-active``, which QUERIES
state and sends no signal to the running process -- this module never
signals or restarts the recorder.

Truncation refusal
------------------
Before converting, every instance not already fully converted is run
through the BL-23 preflight (:func:`breezy.persistence.feather_preflight.
scan_instance`). Fully converted means every requested ``data_types`` entry
AND every feather physically present under the instance has a
``.converted-<type>`` marker (present types are derived from the recorder's
``<class_to_filename>_<n>.feather`` names). A narrower ``data_types``
argument therefore cannot hide an unmarked sibling file. Converted bytes are
frozen and truncated instances never receive those markers, so skipping the
scan does not change liveness or truncation semantics -- it avoids
re-streaming gigabytes of already-landed feather on every timer tick.

Per-file conversion (GL-14/BL-24)
----------------------------------
Whenever an instance has at least one still-open file (:func:`_open_files_
for_instance`, scoped to the single newest file of one data type -- rotation
always closes the previous file before opening the next) OR at least one
truncated/unreadable file anywhere, the whole-instance fast path above is
bypassed for :func:`_ingest_instance_per_file`: every OTHER file -- complete,
in a different type, or simply older in the same type's rotation -- is
still converted or salvaged, regardless of that one file's state. Only the
open file itself is left untouched, retried on the next run. This closes two
defects the old whole-instance refusal caused: (1) an actively-recording
instance's already-rotated, already-closed files waited for the WHOLE
instance to go quiet (up to a day) before landing; (2) a single crashed
(SIGKILL/OOM/reboot) file permanently blocked every sibling file, of every
type, in that instance, even years later.

An end-of-stream-marked file is always trusted as closed. An INTACT-but-
unmarked file (a clean read that stops exactly on a message boundary but
never wrote the terminator) is byte-identical to a live writer paused
mid-stream -- there is no way to distinguish the two from the bytes alone
-- so the EOS marker is trusted as the sole proof of closure ONLY while a
writer for that file COULD still exist. Whether one could is exactly the
instance-wide liveness predicate rule (b) already uses for the
whole-instance path: ``instance_is_dead = NOT (this is the most-recently-
started instance AND the recorder unit is active)``. :func:`run_ingest`
computes it once per instance and threads it into both
:func:`_ingest_instance_per_file` and
:func:`_convert_one_tick_type_per_file`.

* ``instance_is_dead`` is ``False`` (the instance might still be live): a
  no-EOS file is left unmarked (``skipped-unclosed``) and retried next run
  -- the PERMANENT per-file marker is never risked over a file that may yet
  receive more rows.
* ``instance_is_dead`` is ``True``: a no-EOS file converts and is marked
  exactly like an EOS-closed one. This closes a real production stranding:
  a reboot-killed instance can have MOST of its rotated files lacking an
  EOS marker (the writer only appends it on an orderly ``close()``, never
  on a SIGKILL/OOM/reboot) while ALSO carrying an unrelated truncated file
  for a different type -- so it never reaches the whole-instance dead path
  (that path refuses outright on ANY truncation, anywhere) and, before
  this fix, never satisfied the per-file path's EOS bar either. Between
  the two paths, every no-EOS file in an already-dead instance was
  stranded forever. A crashed-and-abandoned instance (SIGKILL/OOM/reboot
  followed by the recorder restarting into a NEW instance UUID) is
  precisely this case: the writer process for the OLD UUID is provably
  gone the moment a newer instance exists, so its last, unmarked file is
  exactly as safe to trust as one the whole-instance path has always
  accepted, truncation elsewhere or not.

Independent of ``instance_is_dead``: :func:`_open_files_for_instance`'s
own two rules (recent mtime, OR newest-instance-and-active) still exclude a
group's single newest file from BOTH paths entirely, dead instance or not
-- that check protects the one file a writer could still be appending to
right now, which an instance-wide dead/live label cannot see file-by-file.

Ordering guarantee: instrument-definition types (:func:`_is_instrument_
definition`) are always converted before every other ("tick") type within
one call to :func:`_ingest_instance_per_file`, and a tick type is deferred
whole (``skipped-definitions-pending``) for the run if ANY definition type
still has an open file -- never partially, never ahead of its definition.
A tick row can therefore never land in the catalog before the instrument
definition it references.

A ``None`` table from the native feather reader (ArrowInvalid/OSError,
already-truncated bytes that slipped past preflight, or a post-transform
table that comes back empty despite a nonzero preflight row count) is a
HARD per-file failure here -- logged at ``ERROR``, never marked, counted
under ``failed`` -- unlike ``convert_stream_to_data``'s own native caller,
which treats the same ``None`` as "nothing to do" and silently marks the
whole type converted. An instance with any such failure reports outcome
``"failed"``.

Idempotency
-----------
A per-(instance, data type) marker file,
``<catalog>/live/<instance>/.converted-<data_type>``, is written only after
NATIVE, whole-type conversion succeeds (the original, unchanged fast path).
The per-file conversion path above writes a separate per-FILE marker instead
(``.converted-file-<relative-path>``, see :data:`FILE_MARKER_PREFIX`):
writing the blanket per-type marker is only ever safe once a type's group is
known dead (no open file), because a still-active instance can always
receive one more rotated file for a type already touched this run. Either
marker makes a second run against an unchanged tape call the native
conversion (or ``_convert_feather_table_to_parquet``) zero additional times
and add zero rows.

Exit contract
--------------
===========================  ====  ==========================================
Outcome                      Code  Example
===========================  ====  ==========================================
Ran, nothing failed             0  every instance skipped-live/-truncated,
(skips are not a failure)       every instance already converted, or fine
Usage / configuration error     2  no catalog root, path is not a directory
At least one hard per-file      3  a ``None`` table or empty-after-transform
conversion failure                read (see "Per-file conversion" above)
===========================  ====  ==========================================
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TextIO

from nautilus_trader.model.instruments import Instrument
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.persistence.funcs import class_to_filename

from breezy.persistence.feather_preflight import (
    DEFAULT_SUBDIRECTORY,
    FeatherStatus,
    PreflightError,
    PreflightReport,
    iter_feather_files,
    list_instance_ids,
    scan_instance,
)
from breezy.runtime.node_config import QUOTE_TAPE_INCLUDE_TYPES
from breezy.runtime.quote_tape_preflight_cli import CATALOG_ENV_VAR
from breezy.runtime.quote_tape_salvage import (
    _file_belongs_to_data_cls,
    salvage_truncated_instance,
    write_fresh_capture_rows,
)

logger = logging.getLogger(__name__)

PROGRAM = "breezy-quote-tape-ingest"

EXIT_OK = 0
EXIT_USAGE = 2
#: At least one instance's outcome was "failed" (a hard per-file conversion
#: failure -- see the module docstring's "Per-file conversion" section).
#: Distinct from EXIT_OK's "ran, even if every instance was skipped": a skip
#: is an ordinary, expected outcome, never a failure.
EXIT_CONVERSION_FAILED = 3

#: A file touched more recently than this may be mid-write. Configurable via
#: ``--live-grace-minutes`` because the right value depends on how bursty a
#: given deployment's markets are, not on anything this module can infer.
DEFAULT_LIVE_GRACE_MINUTES = 30

#: The unit whose activity gates rule (b) above. Read-only queried, never
#: signalled.
DEFAULT_SERVICE_UNIT = "breezy-quote-tape.service"

#: Prefix for the per-(instance, data type) idempotency marker. Dotfile, so it
#: never collides with a ``*.feather`` glob and is invisible to `ls`.
MARKER_PREFIX = ".converted-"

#: Prefix for the per-FILE idempotency marker (GL-14: per-file ingest).
#: The blanket ``.converted-<type>`` marker above is safe ONLY when it is
#: written after every physically-present file for that type is known to be
#: intact and dead (the instance will never receive another file for that
#: type) -- exactly the pre-existing "whole instance is not live" guarantee.
#: Once conversion also runs against a STILL-ACTIVE instance (BL-24: convert
#: rotated-out files without waiting for the whole instance to die), that
#: guarantee no longer holds: a type can still receive a brand-new file after
#: an earlier one was converted. A per-file marker never has that hazard --
#: ``StreamingFeatherWriter`` rotation flushes and closes a file before ever
#: creating the next one, so a marked file's bytes are frozen forever the
#: moment it is marked.
FILE_MARKER_PREFIX = ".converted-file-"

#: The exact set the recorder persists (`breezy.runtime.node_config`), reused
#: rather than re-declared: a duplicate list here would silently drift from
#: what is actually on disk the next time that constant changes.
DEFAULT_DATA_TYPES: tuple[type, ...] = tuple(QUOTE_TAPE_INCLUDE_TYPES)

#: Rows landed in the catalog for this type.
CONVERTED = "converted"

#: The type converted successfully and every streamed row was already in the
#: catalog. Distinct from ``CONVERTED`` so a re-emission-only interval is
#: legible in the log without printing any instrument id or value.
CONVERTED_NOTHING_NEW = "converted-nothing-new"

#: The stream subdirectories Nautilus itself supports, each with its own
#: public reader. ``_read_feather(kind=...)`` is private; these two are not.
_STREAM_SUBDIRECTORIES = ("live", "backtest")

#: A convert function returns the outcome string it achieved, or ``None`` to
#: mean the plain :data:`CONVERTED` outcome.
ConvertFn = Callable[[ParquetDataCatalog, str, type, str], str | None]
ServiceActiveProbe = Callable[[], bool]


def _instance_dir(catalog_root: Path, instance_id: str, subdirectory: str) -> Path:
    return catalog_root / subdirectory / instance_id


def _marker_path(instance_dir: Path, data_cls: type) -> Path:
    return instance_dir / f"{MARKER_PREFIX}{class_to_filename(data_cls)}"


def _is_marked_converted(instance_dir: Path, data_cls: type) -> bool:
    return _marker_path(instance_dir, data_cls).is_file()


def _data_cls_for_feather(
    instance_dir: Path, path: Path, known_types: Sequence[type]
) -> type | None:
    """Map a recorder feather path to its data class via ``class_to_filename``.

    The recorder writes either a flat ``<class_to_filename>_<n>.feather``
    or a per-instrument ``<class_to_filename>/...`` tree -- the same two
    layouts ``StreamingFeatherWriter`` uses. ``None`` means the name is
    unknown and the caller must scan.
    """
    try:
        rel_parts = path.resolve().relative_to(instance_dir.resolve()).parts
    except ValueError:
        return None
    if not rel_parts:
        return None
    for data_cls in known_types:
        name = class_to_filename(data_cls)
        if rel_parts[0] == name or rel_parts[-1].startswith(f"{name}_"):
            return data_cls
    return None


def _instance_is_fully_converted(instance_dir: Path, data_types: Sequence[type]) -> bool:
    """True when every requested type AND every on-disk feather type is marked.

    A narrower ``data_types`` argument must not hide an unmarked sibling
    file: any feather whose type is unmarked, or whose name maps to no
    known type, is scanned as before.
    """
    if not all(_is_marked_converted(instance_dir, data_cls) for data_cls in data_types):
        return False
    known_types = tuple(dict.fromkeys((*data_types, *DEFAULT_DATA_TYPES)))
    for path in iter_feather_files(instance_dir):
        matched = _data_cls_for_feather(instance_dir, path, known_types)
        if matched is None or not _is_marked_converted(instance_dir, matched):
            return False
    return True


def _mark_converted(instance_dir: Path, data_cls: type) -> None:
    _marker_path(instance_dir, data_cls).touch()


def _file_marker_path(instance_dir: Path, path: Path) -> Path:
    """A dotfile keyed to the file's path relative to the instance directory.

    The full relative path (not the bare filename) is encoded so that two
    different types' per-instrument subdirectories can never collide on a
    shared filename.
    """
    rel = path.resolve().relative_to(instance_dir.resolve())
    safe = str(rel).replace("/", "__")
    return instance_dir / f"{FILE_MARKER_PREFIX}{safe}"


def _is_file_marked_converted(instance_dir: Path, path: Path) -> bool:
    return _file_marker_path(instance_dir, path).is_file()


def _mark_file_converted(instance_dir: Path, path: Path) -> None:
    _file_marker_path(instance_dir, path).touch()


def _is_instrument_definition(data_cls: type) -> bool:
    """True when ``ts_init`` stamps a DEFINITION rather than a capture moment.

    ``Instrument`` is the whole predicate, and it is exact rather than
    convenient: an instrument definition is the only thing the recorder
    re-publishes verbatim -- carrying the ``ts_init`` of its first
    publication -- so it is the only thing whose feather intervals can go
    backwards. Everything else on the tape is stamped when it was captured
    and is therefore monotonic by construction.
    """
    return issubclass(data_cls, Instrument)


def _read_streamed(
    catalog: ParquetDataCatalog, instance_id: str, data_cls: type, subdirectory: str
) -> list[Any]:
    """Deserialise one type's streamed feather files, via the public reader."""
    if subdirectory not in _STREAM_SUBDIRECTORIES:
        raise ValueError(
            f"cannot read streamed {class_to_filename(data_cls)} from "
            f"subdirectory {subdirectory!r}: expected one of "
            f"{', '.join(_STREAM_SUBDIRECTORIES)}"
        )
    reader = catalog.read_live_run if subdirectory == "live" else catalog.read_backtest
    try:
        # `raise_on_failed_deserialize=True` is deliberate: the native default
        # PRINTS the failure and DROPS the rows, and dropping rows before
        # writing the success marker is precisely the invisible-data defect
        # this module exists to end. It turns a schema drift into a loud
        # per-type failure instead of a marker over missing rows.
        streamed = reader(instance_id, data_cls=data_cls, raise_on_failed_deserialize=True)
    except (MemoryError, RecursionError):
        # Interpreter-level exhaustion says nothing about this data type and
        # everything about the process. Never dressed up as a type failure
        # that the next timer run would cheerfully retry.
        raise
    except Exception as exc:  # re-raised as THIS type's failure only
        raise ValueError(f"could not read streamed {class_to_filename(data_cls)}: {exc}") from exc
    if not isinstance(streamed, list):
        # `return_as_dict` is left at its default, so this is unreachable
        # today; asserting it keeps a future native default-flip from
        # silently iterating a dict's KEYS as if they were definitions.
        # ValueError, not TypeError, ON PURPOSE: `ingest_instance` isolates a
        # ValueError as THIS type's failure, and any other exception aborts
        # the whole instance. A wrong return type is one type's problem.
        raise ValueError(  # noqa: TRY004
            f"reader for {class_to_filename(data_cls)} returned "
            f"{type(streamed).__name__}, expected list"
        )
    return sorted(streamed, key=lambda obj: obj.ts_init)


def _same_definition(landed: Any, streamed: Any) -> bool:
    """Compare two definitions by CONTENT.

    ``Instrument.__eq__`` compares ``id`` alone (``instruments/base.pyx``
    :299-302), so ``==`` cannot tell a re-emission that changed a field from
    one that changed nothing -- it answers "same instrument", which is
    already true by construction here. ``to_dict`` is the public,
    round-trip-stable field view every ``Instrument`` subclass implements.
    """
    return bool(type(landed).to_dict(landed) == type(streamed).to_dict(streamed))


def convert_instrument_definitions(
    catalog: ParquetDataCatalog,
    instance_id: str,
    data_cls: type,
    subdirectory: str,
    *,
    target: ParquetDataCatalog | None = None,
) -> str:
    """Land the definitions this instance streamed that are not in the catalog.

    Row-wise rather than file-wise because a re-emitted definition keeps its
    original ``ts_init`` (see the module docstring): the native per-file
    conversion refuses the resulting overlap permanently. De-duplicating on
    ``(instrument_id, ts_init)`` -- against the WRITE TARGET catalog AND
    within the stream -- is what earns ``skip_disjoint_check=True``, which is
    otherwise the one guard against writing the same rows twice.

    ``target`` is the catalog the de-duplicated rows are queried against and
    written to; it defaults to ``catalog`` itself, which reproduces every
    caller's behaviour before this parameter existed byte for byte. Passing a
    different ``target`` (e.g. a separate work catalog built from a read-only
    capture -- see ``_convert_live_capture``) reads the streamed feather from
    ``catalog`` but de-duplicates and writes against ``target`` instead,
    exactly mirroring how ``convert_stream_to_data``'s own ``other_catalog``
    parameter works for every other type.

    Idempotency marker semantics do NOT change here: this function has never
    written the ``.converted-<type>`` marker itself -- that is
    :func:`ingest_instance`'s job, gated on the OUTCOME this function
    returns, and it always marks against the streamed instance's OWN
    directory under ``catalog`` regardless of where the rows landed. No
    caller passes a foreign ``target`` through :func:`ingest_instance` today
    (only :func:`default_convert`'s direct callers can), so there is nothing
    to reconcile in practice; this note exists so a future caller that DOES
    combine them makes that call deliberately rather than by accident.

    Reading every existing definition back is affordable precisely because
    definitions are few: one row per market per re-emission, against millions
    of quote rows that never come near this path.

    Two consequences on disk, stated because both are load-bearing and
    neither is reversible by this module.

    **The catalog layout is mixed, and only an UNFILTERED query spans it.**
    The streamed feather carries no ``instrument_id`` schema metadata, so the
    native converter derived no identifier and wrote FLAT to
    ``data/<type>/``, while ``write_data`` files rows under
    ``data/<type>/<instrument_id>/``. ``get_file_list_from_data_cls`` globs
    ``data/<type>/**/*.parquet`` and matches both, so an unfiltered
    :meth:`ParquetDataCatalog.query` returns the union -- which is what the
    de-duplication above relies on. An IDENTIFIER-FILTERED query does NOT:
    ``filter_files`` derives a file's identifier from
    ``file_path.split("/")[-2]`` (``parquet.py:2249``), which for a flat file
    is the data-type directory, so ``query(<type>, identifiers=[...])`` and
    ``catalog.instruments(instrument_ids=[...])`` silently omit every flat
    row. **Never filter by identifier for this type**; query it unfiltered and
    filter in Python. Pinned by
    ``TestTheMixedCatalogLayoutIsPinned`` in the test module.

    **``data/<type>/<instrument_id>/`` is now permanently non-disjoint.**
    That is the whole point of ``skip_disjoint_check=True``, but it makes
    every native operation that ASSUMES disjoint intervals unsound for this
    type: ``consolidate_data`` (aborts on overlap), ``query_last_timestamp``
    and ``extend_file_name`` (filename-interval reasoning), and any future
    ``write_data`` for this type WITHOUT the flag (it would raise, exactly as
    ``convert_stream_to_data`` does). Separately, per-instrument
    subdirectories turn ``delete_data_range(<type>, identifier=None)`` into a
    real RECURSIVE delete (``parquet.py:1421-1440``: the ``/data/<type>/``
    substring now matches, where a flat layout made it a no-op) -- the exact
    hazard :mod:`breezy.persistence.catalog` calls settlement-critical and
    designs around. No caller does any of these today; this note is here so
    that stays a decision rather than an accident.
    """
    write_target = catalog if target is None else target
    streamed = _read_streamed(catalog, instance_id, data_cls, subdirectory)
    known: dict[tuple[str, int], Any] = {
        (definition.id.value, definition.ts_init): definition
        for definition in write_target.query(data_cls=data_cls)
    }

    fresh: list[Any] = []
    divergent = 0
    for definition in streamed:
        key = (definition.id.value, definition.ts_init)
        landed = known.get(key)
        if landed is not None:
            if not _same_definition(landed, definition):
                divergent += 1
            continue
        known[key] = definition
        fresh.append(definition)

    if divergent:
        # A COUNT, never an id: `TypeConversionResult` and this module's log
        # lines are value-free by contract. The landed row wins -- deciding
        # which revision of a definition is authoritative is the trading
        # path's call, not the ingest timer's -- but it is never silent.
        logger.warning(
            "instance %s: %d streamed %s row(s) share an already-landed "
            "(instrument_id, ts_init) but differ in content; skipped, the "
            "landed row stands",
            instance_id,
            divergent,
            class_to_filename(data_cls),
        )

    if not fresh:
        return CONVERTED_NOTHING_NEW

    write_target.write_data(fresh, skip_disjoint_check=True)
    return CONVERTED


def default_convert(
    catalog: ParquetDataCatalog,
    instance_id: str,
    data_cls: type,
    subdirectory: str,
    *,
    target: ParquetDataCatalog | None = None,
) -> str:
    """The one native call this module exists to schedule and guard.

    Instrument definitions take the row-wise path instead; every other type
    is one ``convert_stream_to_data``, unchanged, except the ING-1
    non-disjoint fallback (:func:`_extend_overlapping_stream`). ``target``
    defaults to ``None``, which is byte-for-byte the pre-existing behaviour
    (every existing caller, including :func:`ingest_instance`, omits it);
    passing it writes the converted rows into a SEPARATE catalog instead of
    ``catalog`` itself -- the shape ``_convert_live_capture`` needs to convert
    a read-only capture into a disposable work catalog without duplicating
    this function's dispatch logic.
    """
    if _is_instrument_definition(data_cls):
        return convert_instrument_definitions(
            catalog, instance_id, data_cls, subdirectory, target=target
        )
    try:
        catalog.convert_stream_to_data(
            instance_id, data_cls, other_catalog=target, subdirectory=subdirectory
        )
    except ValueError as exc:
        if not _is_non_disjoint_refusal(exc):
            raise
        return _extend_overlapping_stream(
            catalog, instance_id, data_cls, subdirectory, target=target
        )
    return CONVERTED


def _is_non_disjoint_refusal(exc: BaseException) -> bool:
    """True when Nautilus refused a write as a non-disjoint interval."""
    return "non-disjoint" in str(exc)


def _extend_overlapping_stream(
    catalog: ParquetDataCatalog,
    instance_id: str,
    data_cls: type,
    subdirectory: str,
    *,
    target: ParquetDataCatalog | None = None,
) -> str:
    """ING-1 EXTEND: land only rows the partial slice did not already write.

    Reached when ``convert_stream_to_data`` raises the native non-disjoint
    refusal. Walks the same feather files the native converter would, one
    file at a time -- a whole-stream deserialise of a multi-gigabyte live
    instance would not fit the ingest unit's memory ceiling. Does not
    delete, does not rewrite an existing filename, and does not restamp
    ``ts_init``. Empty stream re-raises so a monkeypatched native failure
    with nothing to extend stays ``failed``.
    """
    write_target = catalog if target is None else target
    streamed_any = False
    written = 0
    for feather_file in catalog._list_feather_data_files(
        kind=subdirectory,
        instance_id=instance_id,
        data_cls=data_cls,
    ):
        table = catalog._read_feather_file(feather_file.path)
        if table is None or len(table) == 0:
            continue
        objects = list(catalog._handle_table_nautilus(table=table, data_cls=data_cls))
        if not objects:
            continue
        streamed_any = True
        written += write_fresh_capture_rows(write_target, data_cls, objects)
    if written:
        return CONVERTED
    if streamed_any:
        return CONVERTED_NOTHING_NEW
    raise ValueError(
        f"conversion of {data_cls.__name__} failed: would create non-disjoint "
        "intervals and the stream had no rows to extend"
    )


def default_service_active_probe(unit: str = DEFAULT_SERVICE_UNIT) -> bool:
    """True if systemd reports ``unit`` active.

    ``systemctl --user is-active`` QUERIES state; it sends no signal to the
    running process and never restarts it. On any failure to ask at all (no
    user session, ``systemctl`` missing) this fails CLOSED toward "live": an
    ambiguous host must never convert a tape it cannot confirm is unattended.
    """
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", unit],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return True
    return result.stdout.strip() == "active"


@dataclass(frozen=True)
class LiveDetection:
    """The liveness verdict for one instance, with the reason stated."""

    is_live: bool
    reason: str


def _instance_write_window(instance_dir: Path) -> tuple[int, int]:
    """``(earliest mtime_ns, latest mtime_ns)`` across every ``*.feather`` file.

    Deliberately ``iter_feather_files`` (the recorder's own output), never a
    bare ``rglob("*")``: this module writes ``.converted-*`` marker files
    into the SAME directory, and counting a marker's own touch-time as
    write activity would make every just-converted instance look freshly
    live forever, permanently blocking the second run this module exists to
    make a no-op.
    """
    mtimes = [path.stat().st_mtime_ns for path in iter_feather_files(instance_dir)]
    if not mtimes:
        return (0, 0)
    return (min(mtimes), max(mtimes))


def _newest_started_instance_id(
    catalog_root: Path, instance_ids: Sequence[str], subdirectory: str
) -> str | None:
    """The instance whose earliest file mtime is the latest, or ``None``.

    Shared by :func:`classify_liveness` (whole-instance verdict) and
    :func:`_open_files_for_instance` (per-file verdict) -- both apply the
    SAME rule (b): "the most recently started instance, while the recorder
    is active", just scoped differently.
    """
    windows = {
        instance_id: _instance_write_window(
            _instance_dir(catalog_root, instance_id, subdirectory)
        )
        for instance_id in instance_ids
    }
    started = {
        instance_id: start for instance_id, (start, _end) in windows.items() if start > 0
    }
    return max(started, key=lambda instance_id: started[instance_id], default=None)


def classify_liveness(
    catalog_root: Path,
    instance_ids: Sequence[str],
    subdirectory: str,
    *,
    now_ns: int,
    grace_ns: int,
    service_active: bool,
) -> dict[str, LiveDetection]:
    """Classify every instance as live or not. See the module docstring for the rule."""
    windows = {
        instance_id: _instance_write_window(
            _instance_dir(catalog_root, instance_id, subdirectory)
        )
        for instance_id in instance_ids
    }
    newest_id = _newest_started_instance_id(catalog_root, instance_ids, subdirectory)

    verdicts: dict[str, LiveDetection] = {}
    for instance_id in instance_ids:
        _start, end = windows[instance_id]
        recently_written = end > 0 and (now_ns - end) < grace_ns
        is_current_and_active = instance_id == newest_id and service_active
        if recently_written:
            verdicts[instance_id] = LiveDetection(
                True, "a file was written within the live-grace window"
            )
        elif is_current_and_active:
            verdicts[instance_id] = LiveDetection(
                True, "the most recently started instance and the recorder service is active"
            )
        else:
            verdicts[instance_id] = LiveDetection(
                False, "no recent write and not the active current instance"
            )
    return verdicts


def _open_files_for_instance(
    catalog_root: Path,
    instance_id: str,
    subdirectory: str,
    data_types: Sequence[type],
    *,
    now_ns: int,
    grace_ns: int,
    newest_instance_id: str | None,
    service_active: bool,
) -> frozenset[Path]:
    """The one feather file per data type that may still be mid-write.

    Scoped to one (instance, data type) GROUP rather than the whole
    instance -- see the module docstring's BL-24 note. ``StreamingFeatherWriter``
    rotation (``persistence/writer.py``) always flushes and closes the
    PREVIOUS file before opening a new one for the same table, so within one
    group only the newest-mtime file can ever be genuinely open or crashed
    mid-write; every older file in the same group is closed by construction
    and safe to convert regardless of the instance's own liveness.

    Applies the SAME two rules :func:`classify_liveness` applies to a whole
    instance, scoped to the file: (a) the group's newest file was written
    within the live-grace window, or (b) this is the most-recently-started
    instance and the recorder service is currently active.
    """
    instance_dir = _instance_dir(catalog_root, instance_id, subdirectory)
    known_types = tuple(dict.fromkeys((*data_types, *DEFAULT_DATA_TYPES)))
    groups: dict[type, list[Path]] = {}
    for path in iter_feather_files(instance_dir):
        matched = _data_cls_for_feather(instance_dir, path, known_types)
        if matched is not None:
            groups.setdefault(matched, []).append(path)

    is_current_and_active = instance_id == newest_instance_id and service_active
    open_files: set[Path] = set()
    for paths in groups.values():
        newest_path = max(paths, key=lambda p: p.stat().st_mtime_ns)
        recently_written = (now_ns - newest_path.stat().st_mtime_ns) < grace_ns
        if recently_written or is_current_and_active:
            open_files.add(newest_path)
    return frozenset(open_files)


@dataclass(frozen=True)
class TypeConversionResult:
    """The outcome for one data type within one instance."""

    data_cls: type
    #: "converted" | "converted-nothing-new" | "skipped-already-converted"
    #: | "would-convert" | "failed". Value-free by contract: never an
    #: instrument id, never a price.
    outcome: str
    detail: str = ""


@dataclass(frozen=True)
class InstanceIngestResult:
    """The outcome for one run instance."""

    instance_id: str
    outcome: str  # "converted" | "skipped-live" | "skipped-truncated" | "dry-run" | "failed"
    reason: str = ""
    type_results: tuple[TypeConversionResult, ...] = field(default_factory=tuple)

    def summary_line(self) -> str:
        """One line: rows-relevant outcome per type, or the skip reason."""
        if self.outcome in ("skipped-live", "skipped-truncated"):
            return f"instance {self.instance_id}: skipped ({self.reason})"
        parts = [
            f"{class_to_filename(result.data_cls)}={result.outcome}"
            for result in self.type_results
        ]
        if self.outcome == "dry-run":
            prefix = "would ingest"
        elif self.outcome == "failed":
            prefix = "attempted"
        else:
            prefix = "ingested"
        return f"instance {self.instance_id}: {prefix} " + " ".join(parts)


def ingest_instance(
    catalog: ParquetDataCatalog,
    catalog_root: Path,
    instance_id: str,
    subdirectory: str,
    data_types: Sequence[type],
    *,
    convert_fn: ConvertFn = default_convert,
) -> InstanceIngestResult:
    """Convert every not-yet-converted data type for one instance.

    A ``ValueError`` from one type (the native non-disjoint-interval refusal,
    e.g. a republished-but-different range) is logged and recorded as THAT
    type's failure only -- it never aborts the remaining types, and never
    aborts other instances. The INSTANCE-level outcome is ``"failed"`` if
    any type failed, matching :func:`_ingest_instance_per_file`'s existing
    precedent (SP-1/I3).
    """
    instance_dir = _instance_dir(catalog_root, instance_id, subdirectory)
    type_results: list[TypeConversionResult] = []
    for data_cls in data_types:
        if _is_marked_converted(instance_dir, data_cls):
            type_results.append(
                TypeConversionResult(data_cls, "skipped-already-converted")
            )
            continue
        try:
            outcome = convert_fn(catalog, instance_id, data_cls, subdirectory)
        except ValueError as exc:
            logger.error(
                "instance %s: conversion of %s failed: %s",
                instance_id,
                data_cls.__name__,
                exc,
            )
            type_results.append(TypeConversionResult(data_cls, "failed", str(exc)))
            continue
        _mark_converted(instance_dir, data_cls)
        type_results.append(TypeConversionResult(data_cls, outcome or CONVERTED))
    any_failure = any(_outcome_has_failure(result.outcome) for result in type_results)
    return InstanceIngestResult(
        instance_id=instance_id,
        outcome="failed" if any_failure else "converted",
        reason="at least one type failed conversion; see type_results for detail"
        if any_failure
        else "",
        type_results=tuple(type_results),
    )


def _dry_run_preview(
    catalog_root: Path, instance_id: str, subdirectory: str, data_types: Sequence[type]
) -> InstanceIngestResult:
    instance_dir = _instance_dir(catalog_root, instance_id, subdirectory)
    type_results = tuple(
        TypeConversionResult(
            data_cls,
            "skipped-already-converted"
            if _is_marked_converted(instance_dir, data_cls)
            else "would-convert",
        )
        for data_cls in data_types
    )
    return InstanceIngestResult(
        instance_id=instance_id, outcome="dry-run", type_results=type_results
    )


def _outcome_has_failure(outcome: str) -> bool:
    """True if a :class:`TypeConversionResult` outcome string records a
    failure -- either the bare ``"failed"`` a definition type's ``ValueError``
    produces, or a ``failed=<n>`` token within a tick type's space-joined
    per-file count summary.
    """
    tokens = outcome.split()
    return "failed" in tokens or any(token.startswith("failed=") for token in tokens)


def _cls_open_and_closed_files(
    instance_dir: Path, data_cls: type, open_files: frozenset[Path]
) -> tuple[list[Path], list[Path]]:
    cls_files = [
        path
        for path in iter_feather_files(instance_dir)
        if _file_belongs_to_data_cls(instance_dir, path, data_cls)
    ]
    cls_open = [path for path in cls_files if path in open_files]
    cls_closed = [path for path in cls_files if path not in open_files]
    return cls_open, cls_closed


def _convert_one_definition_type(
    catalog: ParquetDataCatalog,
    instance_dir: Path,
    instance_id: str,
    subdirectory: str,
    data_cls: type,
    open_files: frozenset[Path],
    *,
    convert_fn: ConvertFn,
    dry_run: bool,
) -> tuple[TypeConversionResult, bool, bool]:
    """Convert one instrument-definition type. Returns ``(result, converted, open)``."""
    cls_open, cls_closed = _cls_open_and_closed_files(instance_dir, data_cls, open_files)
    if cls_open:
        return TypeConversionResult(data_cls, "skipped-open"), False, True
    if not cls_closed:
        return TypeConversionResult(data_cls, "skipped-already-converted"), False, False
    if dry_run:
        return TypeConversionResult(data_cls, "would-convert"), False, False
    try:
        outcome = convert_fn(catalog, instance_id, data_cls, subdirectory)
    except ValueError as exc:
        logger.error(
            "instance %s: conversion of %s failed: %s", instance_id, data_cls.__name__, exc
        )
        return TypeConversionResult(data_cls, "failed", str(exc)), False, False
    _mark_converted(instance_dir, data_cls)
    return TypeConversionResult(data_cls, outcome or CONVERTED), True, False


def _convert_one_tick_type_per_file(
    catalog: ParquetDataCatalog,
    instance_dir: Path,
    instance_id: str,
    data_cls: type,
    open_files: frozenset[Path],
    reports_by_path: dict[Path, Any],
    *,
    instance_is_dead: bool,
    dry_run: bool,
) -> tuple[TypeConversionResult, bool, bool]:
    """Convert one non-definition type's not-yet-marked files, per file.

    Returns ``(result, converted_something_new, saw_an_open_file)``. A file
    carrying the Arrow end-of-stream marker is always trusted as closed. A
    file that reads cleanly to a message boundary WITHOUT one is only
    trusted when ``instance_is_dead`` -- the EOS caution exists purely to
    guard against a writer that could still append to THIS file; once no
    such writer can exist (see the module docstring's "Per-file conversion"
    section), the missing marker says nothing more than "the writer never
    got to call ``close()``", exactly like the pre-existing whole-instance
    dead-instance path has always accepted. In a LIVE instance a no-EOS file
    is left unmarked (``skipped-unclosed``) and retried next run instead.
    """
    cls_open, cls_closed = _cls_open_and_closed_files(instance_dir, data_cls, open_files)
    counts: dict[str, int] = {}
    any_new_conversion = False

    for path in cls_closed:
        if _is_file_marked_converted(instance_dir, path):
            counts["skipped-already-converted"] = counts.get("skipped-already-converted", 0) + 1
            continue
        report = reports_by_path.get(path)
        if report is None:
            logger.warning(
                "instance %s: %s file %s has no preflight report -- skipped "
                "this run, retried next",
                instance_id,
                data_cls.__name__,
                path,
            )
            counts["unreported"] = counts.get("unreported", 0) + 1
            continue
        if report.status is FeatherStatus.UNREADABLE:
            counts["unreadable"] = counts.get("unreadable", 0) + 1
            continue
        if report.is_truncated:
            key = "would-salvage" if dry_run else "salvaged"
            counts[key] = counts.get(key, 0) + 1
            continue
        if report.is_empty:
            if not dry_run:
                _mark_file_converted(instance_dir, path)
                any_new_conversion = True
            counts["converted-nothing-new"] = counts.get("converted-nothing-new", 0) + 1
            continue
        if not report.end_of_stream_marker and not instance_is_dead:
            # INTACT but unclosed, and the instance MIGHT still be live: a
            # clean EOF at a message boundary is byte-identical to a live
            # writer paused mid-stream. Left unmarked, retried next run --
            # `instance_is_dead` below is what proves no such writer can
            # exist and lets the same file convert.
            counts["skipped-unclosed"] = counts.get("skipped-unclosed", 0) + 1
            continue
        if dry_run:
            counts["would-convert"] = counts.get("would-convert", 0) + 1
            continue
        table = catalog._read_feather_file(str(path))
        if table is None:
            logger.error(
                "instance %s: conversion of %s file %s failed -- feather "
                "read returned no table (ArrowInvalid/OSError); left "
                "unmarked for a later retry",
                instance_id,
                data_cls.__name__,
                path,
            )
            counts["failed"] = counts.get("failed", 0) + 1
            continue
        transformed = catalog._apply_stream_conversion_transforms(
            table, convert_bar_type_to_external=True
        )
        if len(transformed) == 0 and report.rows > 0:
            logger.error(
                "instance %s: conversion of %s file %s failed -- preflight "
                "saw %d row(s) but the post-transform table is empty; "
                "refusing a silent zero-row write",
                instance_id,
                data_cls.__name__,
                path,
                report.rows,
            )
            counts["failed"] = counts.get("failed", 0) + 1
            continue
        try:
            catalog._convert_feather_table_to_parquet(
                feather_table=table,
                feather_path=str(path),
                data_cls=data_cls,
                used_catalog=catalog,
            )
            _mark_file_converted(instance_dir, path)
            counts["converted"] = counts.get("converted", 0) + 1
            any_new_conversion = True
        except ValueError as exc:
            if not _is_non_disjoint_refusal(exc):
                logger.error(
                    "instance %s: conversion of %s file %s failed: %s",
                    instance_id,
                    data_cls.__name__,
                    path,
                    exc,
                )
                counts["failed"] = counts.get("failed", 0) + 1
                continue
            objects = list(catalog._handle_table_nautilus(table=table, data_cls=data_cls))
            written = write_fresh_capture_rows(catalog, data_cls, objects)
            if written or objects:
                _mark_file_converted(instance_dir, path)
                key = "converted" if written else "converted-nothing-new"
                counts[key] = counts.get(key, 0) + 1
                any_new_conversion = any_new_conversion or bool(written)
            else:
                logger.error(
                    "instance %s: conversion of %s file %s failed: %s",
                    instance_id,
                    data_cls.__name__,
                    path,
                    exc,
                )
                counts["failed"] = counts.get("failed", 0) + 1

    any_open_seen = bool(cls_open)
    if cls_open:
        counts["skipped-open"] = len(cls_open)

    summary = " ".join(f"{key}={value}" for key, value in counts.items() if value)
    return (
        TypeConversionResult(data_cls, summary or "skipped-already-converted"),
        any_new_conversion,
        any_open_seen,
    )


def _ingest_instance_per_file(
    catalog: ParquetDataCatalog,
    catalog_root: Path,
    instance_id: str,
    subdirectory: str,
    data_types: Sequence[type],
    open_files: frozenset[Path],
    preflight_report: PreflightReport,
    *,
    instance_is_dead: bool,
    convert_fn: ConvertFn,
    dry_run: bool,
) -> InstanceIngestResult:
    """Convert every complete, non-open feather file, per file (GL-14/BL-24).

    Reached only when :func:`run_ingest` cannot take the whole-instance fast
    path: at least one file is currently open (the instance is still being
    written to) or at least one file elsewhere in the instance is truncated
    or unreadable. Neither condition may block a SIBLING file that is
    genuinely complete: an open file is retried next run untouched; a
    truncated file is salvaged (unchanged, file-level, already idempotent)
    without blocking anything else; an intact, END-OF-STREAM-CLOSED file is
    converted and marked with a per-file marker, never the blanket per-type
    marker (see :data:`FILE_MARKER_PREFIX`). An INTACT file lacking the EOS
    marker is convertible too, but ONLY when ``instance_is_dead`` (see
    :func:`_convert_one_tick_type_per_file`) -- otherwise it is left
    unmarked and retried.

    Ordering guarantee: instrument-definition types are always attempted
    FIRST, entirely before any non-definition ("tick") type, and every tick
    type is deferred (``skipped-definitions-pending``) for the whole run if
    ANY definition type still has an open file. This prevents a tick row
    from landing in the catalog before the instrument definition it
    references -- both the write order within this function and, therefore,
    the resulting parquet file mtimes.
    """
    instance_dir = _instance_dir(catalog_root, instance_id, subdirectory)
    reports_by_path = {report.path: report for report in preflight_report.files}
    truncated_to_salvage = tuple(
        report for report in preflight_report.truncated if report.path not in open_files
    )
    unresolved_unreadable = tuple(
        report for report in preflight_report.unreadable if report.path not in open_files
    )
    if not dry_run and truncated_to_salvage:
        salvage_truncated_instance(
            catalog, instance_dir, instance_id, data_types, truncated_to_salvage
        )
    has_unresolved_truncation = bool(truncated_to_salvage) or bool(unresolved_unreadable)

    results_by_cls: dict[type, TypeConversionResult] = {}
    any_new_conversion = False
    any_open_seen = False
    definitions_have_open_file = False

    definition_types = [c for c in data_types if _is_instrument_definition(c)]
    tick_types = [c for c in data_types if not _is_instrument_definition(c)]

    for data_cls in definition_types:
        if _is_marked_converted(instance_dir, data_cls):
            results_by_cls[data_cls] = TypeConversionResult(data_cls, "skipped-already-converted")
            continue
        result, converted, is_open = _convert_one_definition_type(
            catalog,
            instance_dir,
            instance_id,
            subdirectory,
            data_cls,
            open_files,
            convert_fn=convert_fn,
            dry_run=dry_run,
        )
        results_by_cls[data_cls] = result
        any_new_conversion = any_new_conversion or converted
        if is_open:
            any_open_seen = True
            definitions_have_open_file = True

    for data_cls in tick_types:
        if _is_marked_converted(instance_dir, data_cls):
            results_by_cls[data_cls] = TypeConversionResult(data_cls, "skipped-already-converted")
            continue
        if definitions_have_open_file:
            results_by_cls[data_cls] = TypeConversionResult(
                data_cls, "skipped-definitions-pending"
            )
            any_open_seen = True
            continue
        result, converted, is_open = _convert_one_tick_type_per_file(
            catalog, instance_dir, instance_id, data_cls, open_files, reports_by_path,
            instance_is_dead=instance_is_dead, dry_run=dry_run,
        )
        results_by_cls[data_cls] = result
        any_new_conversion = any_new_conversion or converted
        any_open_seen = any_open_seen or is_open

    type_results = tuple(results_by_cls[data_cls] for data_cls in data_types)
    any_failure = any(_outcome_has_failure(result.outcome) for result in type_results)

    if has_unresolved_truncation:
        outcome = "skipped-truncated"
        reason = (
            f"{len(truncated_to_salvage)} truncated, {len(unresolved_unreadable)} "
            f"unreadable file(s); run breezy-quote-tape-preflight for detail"
        )
    elif dry_run:
        outcome = "dry-run"
        reason = ""
    elif any_failure:
        outcome = "failed"
        reason = "at least one file failed conversion; see type_results for detail"
    elif any_new_conversion:
        outcome = "converted"
        reason = ""
    elif any_open_seen:
        outcome = "skipped-live"
        reason = (
            "a file was written within the live-grace window or is the "
            "active instance's current file"
        )
    else:
        outcome = "converted"
        reason = ""

    return InstanceIngestResult(
        instance_id=instance_id,
        outcome=outcome,
        reason=reason,
        type_results=type_results,
    )


def run_ingest(
    catalog_root: Path,
    *,
    subdirectory: str = DEFAULT_SUBDIRECTORY,
    data_types: Sequence[type] = DEFAULT_DATA_TYPES,
    now_ns: int | None = None,
    grace_minutes: float = DEFAULT_LIVE_GRACE_MINUTES,
    service_active_probe: ServiceActiveProbe = default_service_active_probe,
    convert_fn: ConvertFn = default_convert,
    dry_run: bool = False,
) -> tuple[InstanceIngestResult, ...]:
    """Enumerate instances and convert every one that is safe to convert."""
    now = time.time_ns() if now_ns is None else now_ns
    grace_ns = int(grace_minutes * 60 * 1_000_000_000)

    instance_ids = list_instance_ids(catalog_root, subdirectory)
    newest_instance_id = _newest_started_instance_id(catalog_root, instance_ids, subdirectory)
    service_active = service_active_probe()

    catalog = ParquetDataCatalog(str(catalog_root))
    results: list[InstanceIngestResult] = []
    for instance_id in instance_ids:
        instance_dir = _instance_dir(catalog_root, instance_id, subdirectory)
        # The instance-wide liveness predicate rule (b) alone applies (see
        # the module docstring): the newest-started instance while the
        # recorder is active is the only instance a writer can still exist
        # for. Independent of `open_files` below, which ALSO honors rule
        # (a) (per-file recency) to protect a genuinely fresh file even in
        # an otherwise-dead instance.
        instance_is_dead = not (instance_id == newest_instance_id and service_active)
        open_files = _open_files_for_instance(
            catalog_root,
            instance_id,
            subdirectory,
            data_types,
            now_ns=now,
            grace_ns=grace_ns,
            newest_instance_id=newest_instance_id,
            service_active=service_active,
        )

        if not open_files and _instance_is_fully_converted(instance_dir, data_types):
            # Converted bytes are frozen; truncated instances never earn these
            # markers. Skip the BL-23 rescan so periodic ingest does not
            # re-stream every already-converted feather file. Requires a
            # marker for every requested type AND every type physically
            # present under the instance.
            if dry_run:
                results.append(
                    _dry_run_preview(catalog_root, instance_id, subdirectory, data_types)
                )
            else:
                results.append(
                    ingest_instance(
                        catalog,
                        catalog_root,
                        instance_id,
                        subdirectory,
                        data_types,
                        convert_fn=convert_fn,
                    )
                )
            continue

        try:
            preflight_report = scan_instance(catalog_root, instance_id, subdirectory)
        except PreflightError as exc:
            results.append(InstanceIngestResult(instance_id, "skipped-truncated", str(exc)))
            continue

        if not open_files and not preflight_report.has_truncation:
            # The ordinary, unchanged path: a dead instance with nothing
            # truncated anywhere converts via the single native call, per
            # type, exactly as before this change.
            if dry_run:
                results.append(
                    _dry_run_preview(catalog_root, instance_id, subdirectory, data_types)
                )
            else:
                results.append(
                    ingest_instance(
                        catalog,
                        catalog_root,
                        instance_id,
                        subdirectory,
                        data_types,
                        convert_fn=convert_fn,
                    )
                )
            continue

        # GL-14/BL-24: at least one file is still open, or truncation exists
        # somewhere in the instance. Neither may block a sibling file that is
        # genuinely complete -- convert per file instead of refusing the
        # whole instance.
        results.append(
            _ingest_instance_per_file(
                catalog,
                catalog_root,
                instance_id,
                subdirectory,
                data_types,
                open_files,
                preflight_report,
                instance_is_dead=instance_is_dead,
                convert_fn=convert_fn,
                dry_run=dry_run,
            )
        )
    return tuple(results)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description=(
            "Convert every not-yet-converted, non-live run instance's streamed "
            "feather tape into the parquet catalog every analysis script queries."
        ),
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help=f"Catalog root. Defaults to ${CATALOG_ENV_VAR}.",
    )
    parser.add_argument(
        "--subdirectory",
        default=DEFAULT_SUBDIRECTORY,
        help=f"Staging subdirectory (default: {DEFAULT_SUBDIRECTORY}).",
    )
    parser.add_argument(
        "--live-grace-minutes",
        type=float,
        default=DEFAULT_LIVE_GRACE_MINUTES,
        help=(
            "A file written more recently than this many minutes ago marks its "
            f"instance live (default: {DEFAULT_LIVE_GRACE_MINUTES})."
        ),
    )
    parser.add_argument(
        "--service-unit",
        default=DEFAULT_SERVICE_UNIT,
        help=f"Recorder unit queried read-only for liveness (default: {DEFAULT_SERVICE_UNIT}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would be converted without converting or writing markers.",
    )
    return parser


def _resolve_catalog(namespace: argparse.Namespace, env: Mapping[str, str]) -> Path:
    if namespace.catalog is not None:
        root = Path(namespace.catalog)
    else:
        raw = env.get(CATALOG_ENV_VAR, "").strip()
        if not raw:
            raise PreflightError(
                f"no catalog root: pass --catalog or set {CATALOG_ENV_VAR}"
            )
        root = Path(raw)
    if not root.is_dir():
        raise PreflightError(f"catalog root {root} is not a directory")
    return root


def run(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
    now_ns: int | None = None,
) -> int:
    """Ingest, report, and return the process exit code. Never raises."""
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    active_env: Mapping[str, str] = env if env is not None else {}
    parser = _build_parser()

    try:
        namespace = parser.parse_args(list(argv) if argv is not None else [])
    except SystemExit:
        return EXIT_USAGE

    try:
        root = _resolve_catalog(namespace, active_env)
        results = run_ingest(
            root,
            subdirectory=namespace.subdirectory,
            grace_minutes=namespace.live_grace_minutes,
            service_active_probe=lambda: default_service_active_probe(namespace.service_unit),
            dry_run=namespace.dry_run,
            now_ns=now_ns,
        )
    except PreflightError as exc:
        print(f"{PROGRAM}: {exc}", file=err)
        return EXIT_USAGE

    mode = " (dry-run)" if namespace.dry_run else ""
    print(f"{PROGRAM}: catalog={root} subdirectory={namespace.subdirectory}{mode}", file=out)
    for result in results:
        print(result.summary_line(), file=out)
    if any(result.outcome == "failed" for result in results):
        return EXIT_CONVERSION_FAILED
    return EXIT_OK


def main() -> int:
    """Console-script entrypoint. Returns the process exit code."""
    return run(sys.argv[1:], env=os.environ)


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess in tests
    raise SystemExit(main())
