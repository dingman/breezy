"""Core implementation for :mod:`breezy.runtime.quote_tape_ingest_cli`.

The public entrypoint and historical monkeypatch surface stay in
``quote_tape_ingest_cli``.  Functions moved here deliberately resolve patched
helpers through that original module where tests and lazy callers already target
those names.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import math
import resource
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TextIO, cast

from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.persistence.feather_preflight import (
    DEFAULT_SUBDIRECTORY,
    FeatherStatus,
    PreflightError,
    PreflightReport,
)
from breezy.runtime.ingest_deadline import (
    DEFAULT_DEADLINE_SECONDS,
    DEFERRED_DEADLINE,
    RunDeadline,
)
from breezy.runtime.ingest_deferral_streak import (
    STATE_FILENAME as DEFERRAL_STREAK_STATE_FILENAME,
)
from breezy.runtime.ingest_deferral_streak import (
    load_state as _load_deferral_streak_state,
)
from breezy.runtime.ingest_deferral_streak import (
    save_state as _save_deferral_streak_state,
)
from breezy.runtime.ingest_deferral_streak import (
    step as _step_deferral_streak,
)
from breezy.runtime.quote_tape_exit_codes import (
    EXIT_CONVERSION_FAILED,
    EXIT_DEFERRAL_STALLED,
    EXIT_USAGE,
    PROGRAM,
)
from breezy.runtime.quote_tape_preflight_cli import CATALOG_ENV_VAR
from breezy.runtime.quote_tape_salvage import ExtendWriteMismatch, extend_dedupe_counters


def _cli_module() -> Any:
    main_module = sys.modules.get("__main__")
    main_spec = getattr(main_module, "__spec__", None)
    if getattr(main_spec, "name", None) == "breezy.runtime.quote_tape_ingest_cli":
        return main_module
    module = sys.modules.get("breezy.runtime.quote_tape_ingest_cli")
    if module is None:
        module = importlib.import_module("breezy.runtime.quote_tape_ingest_cli")
    return module


_cli: Any = _cli_module()
logger: logging.Logger = _cli.logger

CONVERTED: str = _cli.CONVERTED
DEFAULT_DATA_TYPES: tuple[type, ...] = _cli.DEFAULT_DATA_TYPES
DEFAULT_LIVE_GRACE_MINUTES: float = _cli.DEFAULT_LIVE_GRACE_MINUTES
DEFAULT_SERVICE_UNIT: str = _cli.DEFAULT_SERVICE_UNIT
EXIT_OK: int = _cli.EXIT_OK

if TYPE_CHECKING:
    from breezy.runtime.quote_tape_ingest_cli import (
        ConvertFn,
        InstanceIngestResult,
        LivenessSnapshot,
        ServiceActiveProbe,
        TypeConversionResult,
    )
else:
    ConvertFn = _cli.ConvertFn
    InstanceIngestResult = _cli.InstanceIngestResult
    LivenessSnapshot = _cli.LivenessSnapshot
    ServiceActiveProbe = _cli.ServiceActiveProbe
    TypeConversionResult = _cli.TypeConversionResult

_cls_open_and_closed_files = _cli._cls_open_and_closed_files
_clear_attempt = _cli._clear_attempt
_clear_salvage_attempt = _cli._clear_salvage_attempt
_convert_one_definition_type = _cli._convert_one_definition_type
_dry_run_preview = _cli._dry_run_preview
_instance_dir = _cli._instance_dir
_instance_is_fully_converted = _cli._instance_is_fully_converted
_is_file_marked_converted = _cli._is_file_marked_converted
_is_instrument_definition = _cli._is_instrument_definition
_is_marked_converted = _cli._is_marked_converted
_is_non_disjoint_refusal = _cli._is_non_disjoint_refusal
_is_salvage_marked = _cli._is_salvage_marked
_mark_converted = _cli._mark_converted
_mark_file_converted = _cli._mark_file_converted
_needs_definition_pass = _cli._needs_definition_pass
_open_files_for_instance = _cli._open_files_for_instance
_outcome_has_failure = _cli._outcome_has_failure
_write_attempt = _cli._write_attempt
_write_salvage_attempt = _cli._write_salvage_attempt
class_to_filename = _cli.class_to_filename
ingest_instance = _cli.ingest_instance
salvage_truncated_instance = _cli.salvage_truncated_instance


def _extend_table_chunked(*args: Any, **kwargs: Any) -> tuple[int, bool]:
    return cast(tuple[int, bool], _cli._extend_table_chunked(*args, **kwargs))


def default_convert(*args: Any, **kwargs: Any) -> str | None:
    return cast(str | None, _cli.default_convert(*args, **kwargs))


def default_service_active_probe(unit: str = DEFAULT_SERVICE_UNIT) -> bool:
    return cast(bool, _cli.default_service_active_probe(unit))


def read_feather_coalesced(*args: Any, **kwargs: Any) -> Any:
    return _cli.read_feather_coalesced(*args, **kwargs)


def run_ingest_definitions_first(*args: Any, **kwargs: Any) -> tuple[InstanceIngestResult, ...]:
    return cast(tuple[InstanceIngestResult, ...], _cli.run_ingest_definitions_first(*args, **kwargs))


def scan_instance_memoized(*args: Any, **kwargs: Any) -> PreflightReport:
    return cast(PreflightReport, _cli.scan_instance_memoized(*args, **kwargs))


def take_liveness_snapshot(*args: Any, **kwargs: Any) -> LivenessSnapshot:
    return cast(LivenessSnapshot, _cli.take_liveness_snapshot(*args, **kwargs))


def write_fresh_capture_rows(*args: Any, **kwargs: Any) -> int:
    return cast(int, _cli.write_fresh_capture_rows(*args, **kwargs))


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
    deadline: RunDeadline | None = None,
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

    ``deadline`` (ING-2 S2) gates this WHOLE TYPE as one unit, LAZILY: the
    check happens only once, at the first file that clears every no-op
    filter below (marked/unreported/unreadable/truncated/empty/unclosed) --
    a type with nothing convertible never calls ``admit()`` at all (N2). A
    denied gate stops this type's loop entirely (the remaining files are
    retried next run) and the type reports ``DEFERRED_DEADLINE``.
    """
    cls_open, cls_closed = _cls_open_and_closed_files(instance_dir, data_cls, open_files)
    counts: dict[str, int] = {}
    any_new_conversion = False
    admitted_this_type = False
    deferred_this_type = False

    for path in cls_closed:
        if _is_file_marked_converted(instance_dir, path):
            counts["skipped-already-converted"] = counts.get("skipped-already-converted", 0) + 1
            continue
        report = reports_by_path.get(path)
        if report is None:
            logger.warning(
                "instance %s: %s file %s has no preflight report -- skipped this run, retried next",
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
        if deadline is not None and not admitted_this_type:
            if not deadline.admit():
                deferred_this_type = True
                break
            admitted_this_type = True
            _write_attempt(instance_dir, data_cls)
        table = read_feather_coalesced(catalog.fs, str(path))
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
            try:
                written, streamed_any = _extend_table_chunked(catalog, catalog, data_cls, table)
            except ExtendWriteMismatch as mismatch:
                logger.error(
                    "instance %s: conversion of %s file %s failed "
                    "[reason=extend_write_mismatch]: %s; left unmarked for triage",
                    instance_id,
                    data_cls.__name__,
                    path,
                    mismatch,
                )
                counts["failed"] = counts.get("failed", 0) + 1
                continue
            if written or streamed_any:
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

    if deferred_this_type:
        return TypeConversionResult(data_cls, DEFERRED_DEADLINE), any_new_conversion, any_open_seen

    if cls_closed and all(_is_file_marked_converted(instance_dir, path) for path in cls_closed):
        # N6: every physically-present closed file is already marked -- a
        # stale breadcrumb from an earlier gated-but-then-killed run can
        # never be earned back by this type again.
        _clear_attempt(instance_dir, data_cls)

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
    deadline: RunDeadline | None = None,
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
    salvage_deferred = False
    if not dry_run and truncated_to_salvage:
        # r3.1 S1: the salvage gate applies only when real work remains --
        # an instance whose truncated files are ALL already salvage-marked
        # must never poison itself or burn the deadline for a no-op re-scan
        # (T-n4-noop).
        needs_salvage_work = any(
            not _is_salvage_marked(instance_dir, report.path) for report in truncated_to_salvage
        )
        if deadline is not None and needs_salvage_work:
            if not deadline.admit():
                salvage_deferred = True
            else:
                _write_salvage_attempt(instance_dir)
                salvage_truncated_instance(
                    catalog, instance_dir, instance_id, data_types, truncated_to_salvage
                )
                _clear_salvage_attempt(instance_dir)
        else:
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
            _clear_attempt(instance_dir, data_cls)
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
            deadline=deadline,
        )
        results_by_cls[data_cls] = result
        any_new_conversion = any_new_conversion or converted
        if is_open:
            any_open_seen = True
            definitions_have_open_file = True

    for data_cls in tick_types:
        if _is_marked_converted(instance_dir, data_cls):
            results_by_cls[data_cls] = TypeConversionResult(data_cls, "skipped-already-converted")
            _clear_attempt(instance_dir, data_cls)
            continue
        if definitions_have_open_file:
            results_by_cls[data_cls] = TypeConversionResult(data_cls, "skipped-definitions-pending")
            any_open_seen = True
            continue
        result, converted, is_open = _convert_one_tick_type_per_file(
            catalog,
            instance_dir,
            instance_id,
            data_cls,
            open_files,
            reports_by_path,
            instance_is_dead=instance_is_dead,
            dry_run=dry_run,
            deadline=deadline,
        )
        results_by_cls[data_cls] = result
        any_new_conversion = any_new_conversion or converted
        any_open_seen = any_open_seen or is_open

    type_results = tuple(results_by_cls[data_cls] for data_cls in data_types)
    any_failure = any(_outcome_has_failure(result.outcome) for result in type_results)
    any_deferred = any(result.outcome == DEFERRED_DEADLINE for result in type_results)

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
    elif any_deferred:
        outcome = DEFERRED_DEADLINE
        reason = ""
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
        salvage_deferred=salvage_deferred,
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
    snapshot: LivenessSnapshot | None = None,
    deadline: RunDeadline | None = None,
) -> tuple[InstanceIngestResult, ...]:
    """Enumerate instances and convert every one that is safe to convert.

    ``snapshot``, when given, OVERRIDES the liveness/inventory read
    entirely: ``now_ns``/``grace_minutes``/``service_active_probe`` are
    never consulted and the read is not repeated -- this call's instance
    list, newest-instance id, and service-active state are exactly the
    snapshot's. Passing both ``snapshot`` and ``now_ns`` is a caller error
    (:func:`take_liveness_snapshot` already folds ``now_ns`` into the
    snapshot) and raises ``ValueError``.

    ``deadline`` (ING-2 S2), when given, is peeked at the top of the loop
    (``can_admit()``) before ANYTHING happens for that instance -- a denied
    peek defers the WHOLE instance (``DEFERRED_DEADLINE``, reason
    ``"not evaluated"``, no scan) -- and is threaded into every conversion
    call below. ``deadline=None`` is byte-identical to before this
    parameter existed (AC-D10): no gate, no reorder, no breadcrumb.
    """
    if snapshot is not None and now_ns is not None:
        raise ValueError("snapshot and now_ns are mutually exclusive")
    snap = (
        take_liveness_snapshot(
            catalog_root,
            subdirectory,
            now_ns=now_ns,
            grace_minutes=grace_minutes,
            service_active_probe=service_active_probe,
        )
        if snapshot is None
        else snapshot
    )

    now = snap.now_ns
    grace_ns = snap.grace_ns
    instance_ids = snap.instance_ids
    newest_instance_id = snap.newest_instance_id
    service_active = snap.service_active

    catalog = ParquetDataCatalog(str(catalog_root))
    results: list[InstanceIngestResult] = []
    for instance_id in instance_ids:
        if deadline is not None and not deadline.can_admit():
            results.append(InstanceIngestResult(instance_id, DEFERRED_DEADLINE, "not evaluated"))
            continue
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
                        deadline=deadline,
                    )
                )
            continue

        if deadline is not None:
            deadline.note_scan()
        try:
            preflight_report = scan_instance_memoized(
                catalog_root,
                instance_id,
                subdirectory,
                open_files=frozenset(open_files),
            )
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
                        deadline=deadline,
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
                deadline=deadline,
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
    parser.add_argument(
        "--deadline-seconds",
        type=float,
        default=DEFAULT_DEADLINE_SECONDS,
        help=(
            "Wall-clock budget for this run (ING-2 S2): once elapsed, no NEW "
            "conversion unit starts -- deferred units retry next run. Must be "
            f"a finite number > 0 (default: {DEFAULT_DEADLINE_SECONDS})."
        ),
    )
    return parser


def _validate_deadline_seconds(value: float) -> str | None:
    """``None`` if valid, else the usage-error message to print (AC-D8)."""
    if not math.isfinite(value) or value <= 0:
        return (
            f"{PROGRAM}: --deadline-seconds must be a finite number greater than 0 (got {value!r})"
        )
    return None


def _resolve_catalog(namespace: argparse.Namespace, env: Mapping[str, str]) -> Path:
    if namespace.catalog is not None:
        root = Path(namespace.catalog)
    else:
        raw = env.get(CATALOG_ENV_VAR, "").strip()
        if not raw:
            raise PreflightError(f"no catalog root: pass --catalog or set {CATALOG_ENV_VAR}")
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
    clock_ns: Callable[[], int] | None = None,
) -> int:
    """Ingest, report, and return the process exit code. Never raises.

    ``clock_ns`` (ING-2 S2), when given, is the MONOTONIC clock
    :class:`~breezy.runtime.ingest_deadline.RunDeadline` uses -- independent
    of ``now_ns`` (the WALL clock the liveness/inventory read uses). A
    dry run never builds a deadline at all (AC-D6).
    """
    out = sys.stdout if stdout is None else stdout
    err = sys.stderr if stderr is None else stderr
    active_env: Mapping[str, str] = env if env is not None else {}
    parser = _build_parser()

    try:
        namespace = parser.parse_args(list(argv) if argv is not None else [])
    except SystemExit:
        return EXIT_USAGE

    deadline_seconds: float = namespace.deadline_seconds
    error = _validate_deadline_seconds(deadline_seconds)
    if error is not None:
        # AC-D8: an argparse-level configuration error -- no budget was ever
        # built, so no deadline line is printed for this path.
        print(error, file=err)
        return EXIT_USAGE

    # The deadline is built BEFORE the snapshot/catalog resolution, per the
    # module design: a PreflightError below still reports a (zero-progress)
    # deadline line, since the budget already existed at that point (AC-D7).
    deadline: RunDeadline | None = (
        None
        if namespace.dry_run
        else RunDeadline(
            budget_ns=int(deadline_seconds * 1_000_000_000),
            clock_ns=clock_ns if clock_ns is not None else time.monotonic_ns,
        )
    )

    def _deadline_line(instance_count: int) -> str:
        assert deadline is not None
        elapsed_seconds = deadline.elapsed_ns / 1_000_000_000
        rss_peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
        return (
            f"{PROGRAM}: deadline budget={deadline_seconds:g}s "
            f"elapsed={elapsed_seconds:.0f}s deferred_units={deadline.deferred_units} "
            f"deferred_instances={deadline.deferred_instances} instances={instance_count} "
            f"rss_peak_mb={rss_peak_mb}"
        )

    extend_dedupe_counters.reset()
    try:
        root = _resolve_catalog(namespace, active_env)
        results = run_ingest_definitions_first(
            root,
            subdirectory=namespace.subdirectory,
            grace_minutes=namespace.live_grace_minutes,
            service_active_probe=lambda: default_service_active_probe(namespace.service_unit),
            dry_run=namespace.dry_run,
            now_ns=now_ns,
            deadline=deadline,
        )
    except PreflightError as exc:
        # Review finding 2 (ING-2-RSS): no `extend_dedupe:` summary line here
        # -- nothing ran (no instance was ever reached), and `PreflightError`
        # already logs its own diagnostic above.
        print(f"{PROGRAM}: {exc}", file=err)
        if deadline is not None:
            print(_deadline_line(0), file=out)
        return EXIT_USAGE

    mode = " (dry-run)" if namespace.dry_run else ""
    print(f"{PROGRAM}: catalog={root} subdirectory={namespace.subdirectory}{mode}", file=out)
    for result in results:
        print(result.summary_line(), file=out)
    if deadline is not None:
        print(_deadline_line(len(results)), file=out)
    # ING-2-RSS observability (L-30/L-52): counts only, one line every run,
    # including a run with zero EXTEND chunks -- that makes "EXTEND never
    # ran" distinguishable from "EXTEND ran and every chunk took the
    # unfiltered path". Printed to `out` (like every sibling summary line
    # above) rather than logged: production configures no INFO handler for
    # this logger, so a `logger.info` call here is silently never delivered
    # (detector without delivery, L-52) -- confirmed by the 2026-09-27
    # 11:30Z production run, which executed this code yet left no
    # `extend_dedupe:` line in the journal at all.
    print(extend_dedupe_counters.summary_line(), file=out)

    # EDGE-6 6f: the deferral-stall streak. Independent of `deadline` (a
    # dry run never builds a deadline either, but pending-ness is still
    # meaningful in principle) -- gated on `dry_run` alone (AC: a dry run
    # never touches the streak file, since it never converts or marks
    # anything real).
    alert_due = False
    if not namespace.dry_run:
        pending_units = _cli._count_pending_deferral_units(
            results,
            root,
            namespace.subdirectory,
            DEFAULT_DATA_TYPES,
            now_ns=now_ns,
            grace_minutes=namespace.live_grace_minutes,
            service_active_probe=lambda: default_service_active_probe(namespace.service_unit),
        )
        streak_path = root / DEFERRAL_STREAK_STATE_FILENAME
        streak_state = _load_deferral_streak_state(streak_path)
        now_utc = datetime.fromtimestamp(
            (now_ns if now_ns is not None else time.time_ns()) / 1_000_000_000,
            tz=UTC,
        )
        new_streak_state, alert_due = _step_deferral_streak(
            streak_state, pending=pending_units > 0, now=now_utc
        )
        _save_deferral_streak_state(streak_path, new_streak_state)
        if alert_due:
            assert new_streak_state.first_deferred_utc is not None
            first_deferred = datetime.fromisoformat(new_streak_state.first_deferred_utc)
            age_s = int((now_utc - first_deferred).total_seconds())
            print(
                f"{PROGRAM}: DEFERRAL_STALLED runs={new_streak_state.consecutive_runs} "
                f"age_s={age_s} pending_units={pending_units}",
                file=out,
            )

    # Exit-code precedence (C-5): usage (2, already returned above) beats a
    # conversion failure (3), which beats a deferral-stall alert (4), which
    # beats a clean run (0). A failure with a stall also due still exits 3
    # -- the DEFERRAL_STALLED line above already printed either way, so
    # `OnFailure=` fires exactly once and the reason is visible regardless
    # of which code wins.
    if any(result.outcome == "failed" for result in results):
        return EXIT_CONVERSION_FAILED
    if alert_due:
        return EXIT_DEFERRAL_STALLED
    return EXIT_OK
