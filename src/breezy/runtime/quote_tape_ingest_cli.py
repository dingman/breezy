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
Before converting, every instance not classified live is run through the
BL-23 preflight (:func:`breezy.persistence.feather_preflight.scan_instance`).
Any truncated or unreadable file anywhere under the instance refuses the
WHOLE instance, logged with a reason -- never a silent partial conversion of
whatever else happened to be intact.

Idempotency
-----------
A per-(instance, data type) marker file,
``<catalog>/live/<instance>/.converted-<data_type>``, is written only after
that type's conversion succeeds. A second run against an unchanged tape
therefore calls ``convert_stream_to_data`` zero additional times and adds
zero rows.

Exit contract
--------------
===========================  ====  ==========================================
Outcome                      Code  Example
===========================  ====  ==========================================
Ran (even if every instance     0  nothing to do is not a failure
was skipped)
Usage / configuration error     2  no catalog root, path is not a directory
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
    PreflightError,
    iter_feather_files,
    list_instance_ids,
    scan_instance,
)
from breezy.runtime.node_config import QUOTE_TAPE_INCLUDE_TYPES
from breezy.runtime.quote_tape_preflight_cli import CATALOG_ENV_VAR

logger = logging.getLogger(__name__)

PROGRAM = "breezy-quote-tape-ingest"

EXIT_OK = 0
EXIT_USAGE = 2

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


def _mark_converted(instance_dir: Path, data_cls: type) -> None:
    _marker_path(instance_dir, data_cls).touch()


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
    is one ``convert_stream_to_data``, unchanged. ``target`` defaults to
    ``None``, which is byte-for-byte the pre-existing behaviour (every
    existing caller, including :func:`ingest_instance`, omits it); passing it
    writes the converted rows into a SEPARATE catalog instead of ``catalog``
    itself -- the shape ``_convert_live_capture`` needs to convert a
    read-only capture into a disposable work catalog without duplicating this
    function's dispatch logic.
    """
    if _is_instrument_definition(data_cls):
        return convert_instrument_definitions(
            catalog, instance_id, data_cls, subdirectory, target=target
        )
    catalog.convert_stream_to_data(
        instance_id, data_cls, other_catalog=target, subdirectory=subdirectory
    )
    return CONVERTED


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
    started = {
        instance_id: start for instance_id, (start, _end) in windows.items() if start > 0
    }
    newest_id = max(started, key=lambda instance_id: started[instance_id], default=None)

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
    outcome: str  # "converted" | "skipped-live" | "skipped-truncated" | "dry-run"
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
        prefix = "would ingest" if self.outcome == "dry-run" else "ingested"
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
    aborts other instances.
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
    return InstanceIngestResult(
        instance_id=instance_id, outcome="converted", type_results=tuple(type_results)
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
    liveness = classify_liveness(
        catalog_root,
        instance_ids,
        subdirectory,
        now_ns=now,
        grace_ns=grace_ns,
        service_active=service_active_probe(),
    )

    catalog = ParquetDataCatalog(str(catalog_root))
    results: list[InstanceIngestResult] = []
    for instance_id in instance_ids:
        detection = liveness[instance_id]
        if detection.is_live:
            results.append(
                InstanceIngestResult(instance_id, "skipped-live", detection.reason)
            )
            continue

        try:
            preflight_report = scan_instance(catalog_root, instance_id, subdirectory)
        except PreflightError as exc:
            results.append(InstanceIngestResult(instance_id, "skipped-truncated", str(exc)))
            continue

        if preflight_report.has_truncation:
            reason = (
                f"{len(preflight_report.truncated)} truncated, "
                f"{len(preflight_report.unreadable)} unreadable file(s); "
                f"run breezy-quote-tape-preflight for detail"
            )
            logger.error("instance %s: refusing to convert -- %s", instance_id, reason)
            results.append(InstanceIngestResult(instance_id, "skipped-truncated", reason))
            continue

        if dry_run:
            results.append(
                _dry_run_preview(catalog_root, instance_id, subdirectory, data_types)
            )
            continue

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
    return EXIT_OK


def main() -> int:
    """Console-script entrypoint. Returns the process exit code."""
    return run(sys.argv[1:], env=os.environ)


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess in tests
    raise SystemExit(main())
