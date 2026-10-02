"""The `breezy-quote-tape-ingest` console entrypoint.

Closes the gap ``breezy.runtime.quote_tape_cli`` deliberately left open: the
recorder streams Arrow IPC feather under ``<catalog>/live/<instance>/``, and
turning that into the parquet layout every analysis script queries is a
single native call (``ParquetDataCatalog.convert_stream_to_data``, or since
ING-2 S3a a Breezy mirror of it -- :func:`_convert_stream_natively` -- that
reads with a bounded, coalesced read and still calls native
``_convert_feather_table_to_parquet`` per file) that nothing has ever
automated. It had been run by hand twice, ever -- 199,079 depth rows for
2026-09-01 afternoon were invisible on disk until a manual conversion.

A SEPARATE process from the recorder and from the preflight checker, for the
same reason those two are separate from each other: different failure
consequences. This one holds no venue credential, opens no socket, and never
signals the recorder -- it only reads feather bytes and writes parquet plus
its own marker files.

Null hypothesis, checked before writing any of this:

* **Conversion is native.** ``ParquetDataCatalog.convert_stream_to_data``
  (``persistence/catalog/parquet.py:2604``) does the feather -> parquet work.
  Since ING-2 S3a the fast path calls a Breezy mirror,
  :func:`_convert_stream_natively`, which reads each feather file through
  :func:`breezy.persistence.feather_read.read_feather_coalesced` instead of
  ``_read_feather_file``'s ``reader.read_all()`` (bounded memory on a
  one-row-per-message stream), then still calls native
  ``_convert_feather_table_to_parquet`` per file, unchanged. This module
  otherwise supplies only instance enumeration, live-write avoidance,
  truncation refusal, and idempotency bookkeeping around that call.
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
``convert_stream_to_data`` (or its Breezy mirror, :func:`_convert_stream_natively`)
converts feather files ONE AT A TIME, deriving
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

Definitions-first across the WHOLE run (ING-2 S1)
---------------------------------------------------
The guarantee above is per-instance only: :func:`ingest_instance` and
:func:`_ingest_instance_per_file` each convert one instance's own
definitions before that SAME instance's tick types, but say nothing about
instance B's tick types relative to instance A's definitions. A run killed
(SIGKILL/OOM/``os._exit``) partway through instance A's tick conversion used
to leave the catalog with NO instrument definitions landed at all if A
happened to be enumerated first -- the 2026-09-25 16:50Z forensics: only a
``.converted-quote_tick`` marker existed on disk, and the node resolved zero
instruments. :func:`run_ingest_definitions_first` closes that gap: it takes
ONE :class:`LivenessSnapshot` (:func:`take_liveness_snapshot`) up front,
runs a first pass converting ONLY instrument-definition types for every
instance :func:`_needs_definition_pass` selects, then runs the ordinary
:func:`run_ingest` as a second pass over every instance and every requested
type (already-landed definitions are skipped by their existing per-type
marker). A kill during the second pass therefore can never erase what the
first pass already committed -- every instance definitions pass 1 reached is
resolvable in the catalog regardless of what happens next. ``run()`` calls
this wrapper, not :func:`run_ingest` directly.

A ``None`` table from the feather reader (``read_feather_coalesced``, the
ING-2 S3a coalesced mirror of native ``_read_feather_file`` -- same
ArrowInvalid/OSError scope, already-truncated bytes that slipped past
preflight, or a post-transform table that comes back empty despite a
nonzero preflight row count) is a HARD per-file failure here -- logged at
``ERROR``, never marked, counted under ``failed`` -- unlike
``convert_stream_to_data``'s own native caller, which treats the same
``None`` as "nothing to do" and silently marks the whole type converted. An
instance with any such failure reports outcome ``"failed"``.

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
Deferral-stall alert             4  pending work deferred >= 4 consecutive
(EDGE-6 6f)                        runs AND >= 60 minutes (see
                                   :mod:`breezy.runtime.ingest_deferral_streak`)
===========================  ====  ==========================================

Exit-code precedence when more than one condition applies on the SAME run
(EDGE-6 6f, C-5): usage (2) beats a conversion failure (3), which beats a
deferral-stall alert (4), which beats a clean run (0). A conversion
failure with pending work also stalled still exits 3 -- but the
``DEFERRAL_STALLED`` line still prints in that invocation's journal, so
``OnFailure=`` fires exactly once and the reason is visible either way (see
:func:`run`).
"""

from __future__ import annotations

import os

# Implementation lives in the sibling module. Every moved name is
# re-exported: timers, the console script, and importers keep this path.
# The sibling does not import this module.
from breezy.runtime.quote_tape_ingest_core import (
    _OUTCOME_LADDER,
    _SALVAGE_ATTEMPT_NAME,
    _STREAM_SUBDIRECTORIES,
    ATTEMPT_PREFIX,
    CATALOG_ENV_VAR,
    CONVERTED,
    CONVERTED_NOTHING_NEW,
    DEFAULT_DATA_TYPES,
    DEFAULT_DEADLINE_SECONDS,
    DEFAULT_LIVE_GRACE_MINUTES,
    DEFAULT_SERVICE_UNIT,
    DEFAULT_SUBDIRECTORY,
    DEFERRAL_STREAK_STATE_FILENAME,
    DEFERRED_DEADLINE,
    EXIT_CONVERSION_FAILED,
    EXIT_DEFERRAL_STALLED,
    EXIT_OK,
    EXIT_USAGE,
    EXTEND_CHUNK_ROWS,
    FILE_MARKER_PREFIX,
    MARKER_PREFIX,
    PROGRAM,
    QUOTE_TAPE_INCLUDE_TYPES,
    UTC,
    Any,
    Callable,
    ConvertFn,
    ExtendWriteMismatch,
    FeatherStatus,
    InstanceIngestResult,
    Instrument,
    LivenessSnapshot,
    Mapping,
    ParquetDataCatalog,
    Path,
    PreflightError,
    PreflightReport,
    RunDeadline,
    Sequence,
    ServiceActiveProbe,
    TextIO,
    TypeConversionResult,
    _attempt_path,
    _build_parser,
    _clear_attempt,
    _clear_salvage_attempt,
    _cls_open_and_closed_files,
    _convert_one_definition_type,
    _convert_one_tick_type_per_file,
    _convert_stream_natively,
    _count_pending_deferral_units,
    _data_cls_for_feather,
    _definitions_first,
    _dry_run_preview,
    _extend_overlapping_stream,
    _extend_table_chunked,
    _file_belongs_to_data_cls,
    _file_marker_path,
    _ingest_instance_per_file,
    _instance_dir,
    _instance_has_pending_work,
    _instance_is_fully_converted,
    _instance_is_poisoned,
    _instance_write_window,
    _is_file_marked_converted,
    _is_instrument_definition,
    _is_marked_converted,
    _is_non_disjoint_refusal,
    _is_salvage_marked,
    _ladder_rank,
    _load_deferral_streak_state,
    _mark_converted,
    _mark_file_converted,
    _marker_path,
    _merge_pass_results,
    _needs_definition_pass,
    _newest_started_instance_id,
    _open_files_for_instance,
    _outcome_has_failure,
    _poison_first_order,
    _read_streamed,
    _resolve_catalog,
    _salvage_attempt_path,
    _same_definition,
    _save_deferral_streak_state,
    _step_deferral_streak,
    _validate_deadline_seconds,
    _write_attempt,
    _write_salvage_attempt,
    argparse,
    class_to_filename,
    convert_instrument_definitions,
    count_deferred,
    dataclass,
    datetime,
    default_convert,
    default_service_active_probe,
    extend_dedupe_counters,
    field,
    ingest_instance,
    iter_feather_files,
    list_instance_ids,
    logger,
    logging,
    math,
    read_feather_coalesced,
    replace,
    resource,
    run,
    run_ingest,
    run_ingest_definitions_first,
    salvage_truncated_instance,
    scan_instance_memoized,
    subprocess,
    sys,
    take_liveness_snapshot,
    time,
    write_fresh_capture_rows,
)

__all__ = [
    "ATTEMPT_PREFIX",
    "CATALOG_ENV_VAR",
    "CONVERTED",
    "CONVERTED_NOTHING_NEW",
    "DEFAULT_DATA_TYPES",
    "DEFAULT_DEADLINE_SECONDS",
    "DEFAULT_LIVE_GRACE_MINUTES",
    "DEFAULT_SERVICE_UNIT",
    "DEFAULT_SUBDIRECTORY",
    "DEFERRAL_STREAK_STATE_FILENAME",
    "DEFERRED_DEADLINE",
    "EXIT_CONVERSION_FAILED",
    "EXIT_DEFERRAL_STALLED",
    "EXIT_OK",
    "EXIT_USAGE",
    "EXTEND_CHUNK_ROWS",
    "FILE_MARKER_PREFIX",
    "MARKER_PREFIX",
    "PROGRAM",
    "QUOTE_TAPE_INCLUDE_TYPES",
    "UTC",
    "_OUTCOME_LADDER",
    "_SALVAGE_ATTEMPT_NAME",
    "_STREAM_SUBDIRECTORIES",
    "Any",
    "Callable",
    "ConvertFn",
    "ExtendWriteMismatch",
    "FeatherStatus",
    "InstanceIngestResult",
    "Instrument",
    "LiveDetection",
    "LivenessSnapshot",
    "Mapping",
    "ParquetDataCatalog",
    "Path",
    "PreflightError",
    "PreflightReport",
    "RunDeadline",
    "Sequence",
    "ServiceActiveProbe",
    "TextIO",
    "TypeConversionResult",
    "_attempt_path",
    "_build_parser",
    "_clear_attempt",
    "_clear_salvage_attempt",
    "_cls_open_and_closed_files",
    "_convert_one_definition_type",
    "_convert_one_tick_type_per_file",
    "_convert_stream_natively",
    "_count_pending_deferral_units",
    "_data_cls_for_feather",
    "_definitions_first",
    "_dry_run_preview",
    "_extend_overlapping_stream",
    "_extend_table_chunked",
    "_file_belongs_to_data_cls",
    "_file_marker_path",
    "_ingest_instance_per_file",
    "_instance_dir",
    "_instance_has_pending_work",
    "_instance_is_fully_converted",
    "_instance_is_poisoned",
    "_instance_write_window",
    "_is_file_marked_converted",
    "_is_instrument_definition",
    "_is_marked_converted",
    "_is_non_disjoint_refusal",
    "_is_salvage_marked",
    "_ladder_rank",
    "_load_deferral_streak_state",
    "_mark_converted",
    "_mark_file_converted",
    "_marker_path",
    "_merge_pass_results",
    "_needs_definition_pass",
    "_newest_started_instance_id",
    "_open_files_for_instance",
    "_outcome_has_failure",
    "_poison_first_order",
    "_read_streamed",
    "_resolve_catalog",
    "_salvage_attempt_path",
    "_same_definition",
    "_save_deferral_streak_state",
    "_step_deferral_streak",
    "_validate_deadline_seconds",
    "_write_attempt",
    "_write_salvage_attempt",
    "argparse",
    "class_to_filename",
    "classify_liveness",
    "convert_instrument_definitions",
    "count_deferred",
    "dataclass",
    "datetime",
    "default_convert",
    "default_service_active_probe",
    "extend_dedupe_counters",
    "field",
    "ingest_instance",
    "iter_feather_files",
    "list_instance_ids",
    "logger",
    "logging",
    "main",
    "math",
    "os",
    "read_feather_coalesced",
    "replace",
    "resource",
    "run",
    "run_ingest",
    "run_ingest_definitions_first",
    "salvage_truncated_instance",
    "scan_instance_memoized",
    "subprocess",
    "sys",
    "take_liveness_snapshot",
    "time",
    "write_fresh_capture_rows",
]

@dataclass(frozen=True)
class LiveDetection:
    """The liveness verdict for one instance, with the reason stated."""

    is_live: bool
    reason: str


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
        instance_id: _instance_write_window(_instance_dir(catalog_root, instance_id, subdirectory))
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


def main() -> int:
    """Console-script entrypoint. Returns the process exit code."""
    return run(sys.argv[1:], env=os.environ)


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess in tests
    raise SystemExit(main())
