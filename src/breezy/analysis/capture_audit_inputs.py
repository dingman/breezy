"""AUT-1 WP5 stage 2b, W3: input gathering.

``gather_inputs`` is the ONE place the audit reads the world: single-read ``O_NOFOLLOW`` files under
the data root, the exec store through the E-8 snapshot (``take_flock=False``, advisory), the node
logs (ONE ``scan_node_log`` pass per log per run with the W2 sinks, S2-R6), the journals through
``capture_audit_host`` and the recorder catalog (``capture_audit_tape``, loaded eagerly: an I/O
failure there is ``tape_unreadable``). An unreadable or untrusted input raises ``AuditInputError``
with a cause of the closed set.

Per-log cache (S2-R6). A log that ended (its ``TradingNode`` DISPOSED line was seen) is immutable,
so its reducer outputs are cached under ``AUDIT_CACHE_DIR``, keyed by
``(name, size, mtime_ns, head-sha)`` plus the codec version. The cache is an optimisation, never
evidence: an unreadable or undecodable entry is a miss and the log is scanned again. A log that is
still being written is never cached (and its key moves with every byte, so it cannot hit). The
cache lives in ``capture_audit_cache``, whose ``write_scan_cache`` is the audit's only write.

Deadline (S2-R6). ``DEADLINE`` holds the monotonic instant after which no more work may start. A
sink counts events and checks the clock every 65,536 events, so a scan stops mid-log, and
``ScanDeadline`` then tells the caller the day is not reached (it is deferred, never written
partial). ``MONOTONIC`` is the one clock both the run and the sink read.

Layout below the data root: ``logs/`` (node logs), ``derived/capture_stream/polymarket_us/``
(capture streams), ``catalog/quote_tape/polymarket_us`` (the recorder catalog) and
``catalog/quote_tape/decisions`` (funnel and settlement files).
"""

import datetime as dt
import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

from breezy.analysis.capture_audit_cache import (
    LogResult,
    encode_result,
    log_key,
    read_scan_cache,
    write_scan_cache,
)
from breezy.analysis.capture_audit_exec_view import KNOWN_EXEC_SUBPREFIXES, read_exec_view
from breezy.analysis.capture_audit_host import (
    EMPTY_OUTPUT_DETAIL,
    INGEST_JOURNAL_ARGV,
    RECORDER_JOURNAL_ARGV,
    SUPERVISOR_JOURNAL_ARGV,
    journal_slot,
    parse_recorder_journal,
    read_ingest_exit_ns,
    read_recorder_props,
    run_journal,
)
from breezy.analysis.capture_audit_input_types import (
    AuditInputs,
    BootEvidence,
    FunnelCount,
    FunnelRow,
    HeartbeatSummary,
    IngestLine,
    LogMarkers,
    NotifierProof,
    ReplayResult,
    StallRecord,
    StreamSummary,
)
from breezy.analysis.capture_audit_log_markers import MarkerParser
from breezy.analysis.capture_audit_model import AuditInputError
from breezy.analysis.capture_audit_replay import BootReplay
from breezy.analysis.capture_audit_tape import RecorderCatalogTape, catalog_instruments
from breezy.analysis.capture_node_log import iter_node_log, scan_node_log
from breezy.analysis.capture_node_log_decisions import InstanceIdLine
from breezy.analysis.capture_node_log_io import NodeLogUnreadable
from breezy.analysis.capture_node_log_sinks import LogSink, NodeLogSinkFailed
from breezy.analysis.capture_node_log_spawns import (
    list_node_logs,
    match_spawns_to_logs,
    parse_supervisor_lines,
)
from breezy.analysis.capture_settlement import (
    SettlementFileCorrupt,
    SettlementRecord,
    read_settlement_day,
)
from breezy.domain.exec_intent import utc_day_for_ns
from breezy.persistence.autonomy.capture_epoch import EpochRecord, EpochUnreadable, read_epoch
from breezy.persistence.autonomy.capture_reader import (
    C1View,
    CaptureProjectionError,
    CaptureStream,
    project_c1,
    read_capture_stream,
)
from breezy.persistence.autonomy.capture_records import SOURCES
from breezy.persistence.autonomy.capture_stream import capture_root
from breezy.persistence.autonomy.single_read import (
    ReadPolicy,
    SingleReadReason,
    SingleReadRefused,
    open_root,
    read_once_at,
    walk_dirs,
)
from breezy.registry.sites import default_registry
from breezy.runtime.capture_recorder_hook_cli import STALL_RELATIVE, STALL_SUFFIX

__all__ = [
    "DEADLINE",
    "KNOWN_EXEC_SUBPREFIXES",
    "MONOTONIC",
    "NBP_CYCLE_HOURS_UTC",
    "RecorderCatalogTape",
    "ScanDeadline",
    "boot_census",
    "gather_inputs",
    "list_names",
    "read_exec_view",
    "write_scan_cache",
]

_LOGGER: Final[logging.Logger] = logging.getLogger(__name__)
VENUE: Final[str] = "polymarket_us"
LOGS_DIR: Final[str] = "logs"
TAPE_REL: Final[tuple[str, ...]] = ("catalog", "quote_tape", VENUE)
DECISIONS_REL: Final[tuple[str, ...]] = ("catalog", "quote_tape", "decisions")
NOTIFY_REL: Final[tuple[str, ...]] = ("evidence", "alerts", "notify")
_NS: Final[int] = 1_000_000_000
_DAY_NS: Final[int] = 86_400 * _NS
_HEAD_EVENTS: Final[int] = 5_000
_MAX_FILE_BYTES: Final[int] = 64 * 1024 * 1024
_DEADLINE_CHECK_EVERY: Final[int] = 65_536
_ROTATION_HOUR_UTC: Final[int] = 9
#: The NBP model cycle hours (``ingest.nbm_quantile_actor.DEFAULT_NBM_QUANTILE_CYCLE_HOURS``),
#: restated because that module pulls an HTTP client into a wrapped unit; a test pins them equal.
NBP_CYCLE_HOURS_UTC: Final[tuple[int, ...]] = (1, 13, 19)
_NBP_LAG_S: Final[int] = 3 * 3600
_SETTLEMENT_DAYS_BACK: Final[int] = 2
_SETTLEMENT_DAYS_FORWARD: Final[int] = 2
_LOG_NAME_RE: Final[re.Pattern[str]] = re.compile(r"\Abreezy-trade-(\d{8}T\d{6}Z)\.log\Z")
_NOTIFY_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"\A(?P<unit>.+)__(?P<inv>[0-9a-f]{32})\.delivered\.json\Z"
)
_STALL_NAME_RE: Final[re.Pattern[str]] = re.compile(
    r"\A(?P<ns>\d+)_(?P<inv>[0-9a-f]{32})" + re.escape(STALL_SUFFIX) + r"\Z"
)


class ScanDeadline(Exception):
    """The work budget ran out: the day is not reached (deferred), never written partial."""


#: The monotonic instant after which no work may start; ``None`` is unlimited. Set by ``run_audit``.
DEADLINE: ContextVar[float | None] = ContextVar("capture_audit_deadline", default=None)
MONOTONIC: Callable[[], float] = time.monotonic


def _check_deadline() -> None:
    deadline = DEADLINE.get()
    if deadline is not None and MONOTONIC() >= deadline:
        raise ScanDeadline


class _DeadlineSink:
    """A sink that only watches the clock: it keeps one counter and never reads the event."""

    def __init__(self) -> None:
        self._events = 0

    def feed(self, event: object) -> None:
        self._events += 1
        if self._events % _DEADLINE_CHECK_EVERY == 0:
            _check_deadline()


# -- single-read helpers -------------------------------------------------------------------------


def _read_file(
    root: Path, rel: Sequence[str], name: str, policy: ReadPolicy = ReadPolicy.STRICT
) -> bytes | None:
    """``name`` below ``root/rel`` through the ``O_NOFOLLOW`` walk, or ``None`` when absent. Any
    other refusal (a symlink, a foreign owner, an oversize file) is raised."""
    rootfd = open_root(root)
    try:
        try:
            dirfd = walk_dirs(rootfd, rel)
        except SingleReadRefused as exc:
            if exc.reason is SingleReadReason.NOT_FOUND:
                return None
            raise
    finally:
        os.close(rootfd)
    try:
        return read_once_at(dirfd, name, max_bytes=_MAX_FILE_BYTES, policy=policy)
    except SingleReadRefused as exc:
        if exc.reason is SingleReadReason.NOT_FOUND:
            return None
        raise
    finally:
        os.close(dirfd)


def list_names(root: Path, rel: Sequence[str]) -> list[str]:
    """The entry names of ``root/rel`` (empty when it is absent), through the nofollow walk."""
    rootfd = open_root(root)
    try:
        try:
            dirfd = walk_dirs(rootfd, rel)
        except SingleReadRefused as exc:
            if exc.reason is SingleReadReason.NOT_FOUND:
                return []
            raise
    finally:
        os.close(rootfd)
    try:
        return sorted(os.listdir(dirfd))
    finally:
        os.close(dirfd)


def _day_bounds_ns(day: dt.date) -> tuple[int, int]:
    start = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp()) * _NS
    return start, start + _DAY_NS


# -- logs, spawns and the boot census ------------------------------------------------------------


def _log_stamp_ns(path: Path) -> int:
    match = _LOG_NAME_RE.fullmatch(path.name)
    if match is None:
        raise ValueError("not a node log name")
    moment = dt.datetime.strptime(match[1], "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.UTC)
    return int(moment.timestamp()) * _NS


def _listed_logs(data_root: Path) -> tuple[Path, ...]:
    try:
        return list_node_logs(data_root / LOGS_DIR).paths
    except NodeLogUnreadable as exc:
        raise AuditInputError("node_log_unreadable", exc.cause) from None


def _overlaps_day(path: Path, day: dt.date) -> bool:
    lo, hi = _day_bounds_ns(day)
    try:
        return _log_stamp_ns(path) < hi and path.stat().st_mtime_ns >= lo
    except OSError as exc:
        raise AuditInputError("node_log_unreadable", type(exc).__name__) from None


def _head_ids(path: Path) -> tuple[str, ...]:
    """The instance ids in a log's first lines (a node writes its ``TradingNode: instance_id:``
    line at start-up), without reading the rest of a gigabyte file."""
    found: dict[str, None] = {}
    try:
        for seen, event in enumerate(iter_node_log(path)):
            if isinstance(event, InstanceIdLine):
                found.setdefault(event.instance_id)
            if found or seen >= _HEAD_EVENTS:
                break
    except NodeLogUnreadable as exc:
        raise AuditInputError("node_log_unreadable", exc.cause) from None
    return tuple(found)


def _live_ids(data_root: Path, day: dt.date) -> dict[str, str]:
    """``instance_id -> source`` of every capture stream directory that overlaps ``day``: its files
    were last written on or after the day's start and first written before its end."""
    root = capture_root(data_root, VENUE)
    lo, hi = _day_bounds_ns(day)
    found: dict[str, str] = {}
    for source in SOURCES:
        try:
            names = sorted(p for p in (root / source).iterdir() if p.is_dir())
            for directory in names:
                stamps = [f.stat().st_mtime_ns for f in directory.iterdir()]
                if stamps and max(stamps) >= lo and min(stamps) < hi:
                    found.setdefault(directory.name, source)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise AuditInputError("stream_unreadable", type(exc).__name__) from None
    return found


def _spawn_ids(
    supervisor_journal: str,
    logs: Sequence[Path],
    heads: Mapping[Path, tuple[str, ...]],
    day: dt.date,
) -> set[str]:
    scan = parse_supervisor_lines(supervisor_journal.splitlines())
    if scan.unparseable_total:
        raise AuditInputError("node_log_unparseable", "supervisor_spawn_line")
    lo, hi = _day_bounds_ns(day)
    census = match_spawns_to_logs(scan.spawns, logs)
    ids: set[str] = set()
    for match in census.matches:
        if not lo <= int(match.event.ts.timestamp()) * _NS < hi:
            continue
        if match.log_path is None:
            raise AuditInputError("node_log_missing", "spawn_without_log")
        if not heads.get(match.log_path):
            raise AuditInputError("node_log_missing", "spawned_log_without_instance_id")
        ids.update(heads[match.log_path])
    return ids


def boot_census(data_root: Path, day: dt.date, *, supervisor_journal: str) -> tuple[str, ...]:
    """The instance ids of every boot overlapping ``day``: log ids, capture ``live/<instance_id>/``
    directories and supervisor spawns, counted by ``instance_id`` (a boot seen three ways is one).
    A boot with no readable log, or a spawn with no log, is ``node_log_missing``."""
    logs = _listed_logs(data_root)
    heads = {path: _head_ids(path) for path in logs}
    log_ids = {i for path in logs if _overlaps_day(path, day) for i in heads[path]}
    known = {i for ids in heads.values() for i in ids}
    live = _live_ids(data_root, day)
    if set(live) - known:
        raise AuditInputError("node_log_missing", "capture_stream_without_log")
    spawned = _spawn_ids(supervisor_journal, logs, heads, day)
    return tuple(sorted(log_ids | set(live) | spawned))


# -- scanning one log ----------------------------------------------------------------------------


def _new_sinks() -> tuple[BootReplay, MarkerParser, LogSink]:
    return BootReplay(), MarkerParser(), _DeadlineSink()


def _scan_one(path: Path) -> LogResult:
    replay, markers, watch = _new_sinks()
    try:
        scan = scan_node_log(path, sinks=(replay, markers, watch))
    except NodeLogUnreadable as exc:
        raise AuditInputError("node_log_unreadable", exc.cause) from None
    except NodeLogSinkFailed as exc:
        if isinstance(exc.__cause__, ScanDeadline):
            raise ScanDeadline from None
        raise AuditInputError("node_log_sink_failed", str(exc)) from None
    bad = [u for u in scan.unparseable if u.marker != "line"]
    if bad:
        raise AuditInputError("node_log_unparseable", f"{bad[0].marker}:{bad[0].cause}")
    return LogResult(scan, dict(replay.results()), dict(markers.markers()))


def _scan_log(data_root: Path, path: Path) -> LogResult:
    """One log's result: the cache entry, else ONE scan (cached if the log ended)."""
    try:
        key = log_key(path)
    except OSError as exc:
        raise AuditInputError("node_log_unreadable", type(exc).__name__) from None
    cached = read_scan_cache(data_root, key)
    if cached is not None:
        return cached
    _check_deadline()
    result = _scan_one(path)
    if result.scan.node_disposed:
        try:
            write_scan_cache(data_root, key, encode_result(result))
        except (OSError, SingleReadRefused, TypeError, ValueError) as exc:
            _LOGGER.warning("capture audit: scan cache write failed (%s)", type(exc).__name__)
    return result


# -- streams, epoch, funnel and the small inputs --------------------------------------------------


#: The catalog table names (Nautilus ``class_to_filename``); pinned to the reader by a test, because
#: ``breezy.analysis`` never imports Nautilus directly.
def _row_counts(stream: CaptureStream) -> dict[str, int]:
    counts = {
        "custom_decision_record": len(stream.decisions),
        "custom_frame_copy": len(stream.frame_copies),
        "custom_order_event_record": len(stream.order_events),
        "custom_detector_event": len(stream.detector_events),
        "custom_capture_heartbeat": len(stream.heartbeats),
        "custom_forecast_point": len(stream.forecast_points),
        "order_initialized": len(stream.order_initialized),
        "order_filled": len(stream.order_filled),
    }
    for table, _row in stream.position_events:
        counts[table] = counts.get(table, 0) + 1
    return counts


def _summary_of(stream: CaptureStream) -> StreamSummary:
    return StreamSummary(
        row_counts=_row_counts(stream),
        heartbeats=tuple(
            HeartbeatSummary(int(h.ts_event), int(h.seq), bool(h.final), dict(h.written_by_type))
            for h in stream.heartbeats
        ),
        torn_tail_count=len(stream.torn_tails),
        unrecognised_file_count=len(stream.unrecognised_files),
        forecast_cycles=frozenset(
            (p.station, int(p.cycle_runtime_ns)) for p in stream.forecast_points
        ),
    )


def _read_stream(data_root: Path, source: str, instance_id: str) -> CaptureStream | None:
    directory = capture_root(data_root, VENUE) / source / instance_id
    if not directory.is_dir():
        return None
    try:
        return read_capture_stream(directory)
    except (SingleReadRefused, CaptureProjectionError, OSError) as exc:
        raise AuditInputError("stream_unreadable", type(exc).__name__) from None


def _project(stream: CaptureStream, family_id: str) -> C1View:
    try:
        return project_c1(stream, family_id=family_id)
    except CaptureProjectionError as exc:
        raise AuditInputError("capture_projection_failed", str(exc)[:80]) from None


def _first_record_ns(stream: CaptureStream) -> int | None:
    stamps = [int(h.ts_event) for h in stream.heartbeats]
    stamps += [int(d.wall_ns) for d in stream.decisions if d.wall_ns]
    return min(stamps) if stamps else None


def _read_epoch_record(data_root: Path, family_id: str) -> EpochRecord | None:
    try:
        return read_epoch(data_root, family_id)
    except (EpochUnreadable, SingleReadRefused, OSError):
        raise AuditInputError("epoch_unreadable", "epoch_file") from None


def _funnel_rows(data_root: Path, boot_days: Iterable[dt.date]) -> tuple[FunnelRow, ...]:
    rows: list[FunnelRow] = []
    for boot_day in sorted(set(boot_days)):
        try:
            raw = _read_file(data_root, DECISIONS_REL, f"fq_funnel_{boot_day.isoformat()}.jsonl")
        except SingleReadRefused as exc:
            raise AuditInputError("funnel_missing", exc.reason.value) from None
        if raw is None:
            continue
        for line in raw.decode("utf-8", "replace").splitlines():
            if line.strip():
                rows.append(_funnel_row(line, boot_day))
    return tuple(rows)


def _funnel_row(line: str, boot_day: dt.date) -> FunnelRow:
    try:
        body = json.loads(line)
        counts = tuple(
            FunnelCount(
                str(c["station"]), str(c["side"]), str(c["kind"]), str(c["reason"]), int(c["count"])
            )
            for c in body["counts"]
        )
        return FunnelRow(
            int(body["ts_ns"]), str(body.get("boot_day", boot_day.isoformat())), counts
        )
    except (ValueError, KeyError, TypeError):
        raise AuditInputError("funnel_missing", "unparseable_row") from None


def _settlements(data_root: Path, day: dt.date) -> tuple[SettlementRecord, ...]:
    found: list[SettlementRecord] = []
    decisions = data_root.joinpath(*DECISIONS_REL)
    for offset in range(-_SETTLEMENT_DAYS_BACK, _SETTLEMENT_DAYS_FORWARD + 1):
        try:
            found.extend(read_settlement_day(decisions, day + dt.timedelta(days=offset)))
        except FileNotFoundError:
            continue
        except (SettlementFileCorrupt, SingleReadRefused) as exc:
            # No closed cause names an unreadable settlement file; the stage-2c review adds one.
            raise AuditInputError(
                "capture_projection_failed", f"settlement:{type(exc).__name__}"
            ) from None
    return tuple(found)


def _std_offsets() -> Mapping[str, float]:
    """Station -> fixed standard-time UTC offset, under the city code (``LAX``, which the decision
    lines and settlement files use) and its ICAO form (``KLAX``, which the forecast lines use)."""
    registry = default_registry()
    offsets: dict[str, float] = {}
    for venue, city in registry.pairs():
        if venue == VENUE:
            hours = registry.climate_day_window(venue, city).std_utc_offset_hours
            offsets[city] = hours
            offsets[f"K{city}"] = hours
    return offsets


def _nbp_cycles_ns(day: dt.date) -> tuple[int, ...]:
    lo, hi = _day_bounds_ns(day)
    cycles: list[int] = []
    for back in (1, 0):
        base, _ = _day_bounds_ns(day - dt.timedelta(days=back))
        for hour in NBP_CYCLE_HOURS_UTC:
            cycle = base + hour * 3600 * _NS
            if lo <= cycle + _NBP_LAG_S * _NS < hi:
                cycles.append(cycle)
    return tuple(sorted(cycles))


def _stall_records(data_root: Path, day: dt.date) -> tuple[StallRecord, ...]:
    found: list[StallRecord] = []
    for offset in (0, 1):
        stamp = (day + dt.timedelta(days=offset)).isoformat()
        rel = (*STALL_RELATIVE.parts, stamp)
        for name in list_names(data_root, rel):
            match = _STALL_NAME_RE.fullmatch(name)
            if match is None:
                continue
            try:
                raw = _read_file(data_root, rel, name)
                body = json.loads(raw or b"")
                found.append(
                    StallRecord(str(body["invocation_id"]), int(body["detected_ns"]), stamp)
                )
            except (SingleReadRefused, ValueError, KeyError, TypeError):
                raise AuditInputError("capture_projection_failed", "stall_record") from None
    return tuple(sorted(found, key=lambda s: (s.ts_ns, s.invocation_id)))


def _notifier_proofs(data_root: Path, day: dt.date) -> tuple[NotifierProof, ...]:
    found: list[NotifierProof] = []
    for offset in (0, 1):
        stamp = (day + dt.timedelta(days=offset)).isoformat()
        rel = (*NOTIFY_REL, stamp)
        for name in list_names(data_root, rel):
            match = _NOTIFY_NAME_RE.fullmatch(name)
            if match is None:
                continue
            delivered = False
            try:
                body = json.loads(_read_file(data_root, rel, name, ReadPolicy.REPO) or b"")
                delivered = isinstance(body, dict) and body.get("delivered") is True
            except (SingleReadRefused, ValueError):
                delivered = False  # an unreadable marker proves no delivery
            found.append(NotifierProof(match["unit"], match["inv"], delivered, stamp))
    return tuple(sorted(found, key=lambda p: (p.date, p.unit, p.invocation_id)))


# -- the journals --------------------------------------------------------------------------------


def _slot(day: dt.date, offset_days: int) -> str:
    start, _ = _day_bounds_ns(day + dt.timedelta(days=offset_days))
    return journal_slot(start // _NS)


def _tolerating_empty(template: Sequence[str], since: str, until: str, *, tolerate: bool) -> str:
    try:
        return run_journal(template, since, until)
    except AuditInputError as exc:
        if tolerate and exc.cause == "journal_failed" and exc.detail == EMPTY_OUTPUT_DETAIL:
            return ""
        raise


def _ingest_lines(day: dt.date, exited_after_rotation: bool) -> tuple[IngestLine, ...]:
    text = _tolerating_empty(
        INGEST_JOURNAL_ARGV, _slot(day, 1), _slot(day, 2), tolerate=not exited_after_rotation
    )
    return tuple(IngestLine(line) for line in text.splitlines() if line.strip())


# -- the boots -----------------------------------------------------------------------------------


def _boot_for(row: "_BootRow", day: dt.date) -> BootEvidence:
    live = row.source == "live"
    scan = row.result.scan if live else None
    iid = row.instance_id
    return BootEvidence(
        instance_id=iid,
        source=row.source,
        stream=row.reader,
        summary=row.summary,
        c1=row.c1,
        log_name=row.log_path.name,
        scan=scan,
        markers=row.result.markers.get((iid, day), LogMarkers()) if live else LogMarkers(),
        replay=row.result.replay.get((iid, day), ReplayResult()) if live else ReplayResult(),
        started_ns=_log_stamp_ns(row.log_path),
        last_line_ts_ns=None if scan is None else scan.last_line_ts_ns,
        ended=False,
        disposed=bool(scan and scan.node_disposed),
        overlap_s=0,
        subscribed=frozenset(),
    )


def _settle_boots(
    boots: Sequence[BootEvidence], day: dt.date, now_ns: int, tape: RecorderCatalogTape
) -> tuple[BootEvidence, ...]:
    """Fill in what needs the whole set: ended (a later boot or a DISPOSED line), the overlap with
    the day, and the instruments the tape shows active in it."""
    lo, hi = _day_bounds_ns(day)
    live_starts = sorted(b.started_ns for b in boots if b.source == "live")
    out: list[BootEvidence] = []
    for boot in boots:
        last = boot.last_line_ts_ns if boot.last_line_ts_ns is not None else boot.started_ns
        ended = boot.disposed or any(s > last for s in live_starts)
        end = last if ended else now_ns
        start_in, end_in = max(boot.started_ns, lo), min(end, hi)
        overlap = max(0, end_in - start_in) // _NS
        subscribed = tape.active_instruments(start_in, end_in) if end_in > start_in else frozenset()
        out.append(replace(boot, ended=ended, overlap_s=overlap, subscribed=subscribed))
    return tuple(sorted(out, key=lambda b: (b.started_ns, b.instance_id, b.source)))


def _check_epoch(
    epoch: EpochRecord | None, boots: Sequence[BootEvidence], firsts: Sequence[int], day: dt.date
) -> None:
    streams = bool(boots) and any(b.summary.row_counts.get("capture_heartbeat") for b in boots)
    if epoch is None:
        if streams or firsts:
            raise AuditInputError("epoch_missing", "capture_files_without_epoch")
        return
    if firsts and epoch.epoch_start_ns > min(firsts):
        raise AuditInputError("epoch_rewritten", "epoch_after_first_record")
    if utc_day_for_ns(epoch.epoch_start_ns) == day:
        owner = [b for b in boots if b.instance_id == epoch.node_boot_id and b.source == "live"]
        if owner and not any(b.markers.capture_epoch_start for b in owner):
            raise AuditInputError("epoch_unlogged", "no_epoch_start_line")


@dataclass(frozen=True, slots=True)
class _BootRow:
    """One boot-source: its stream REDUCED (summary and C1 view; the stream itself is dropped) and a
    reader that re-reads it on demand (leg B)."""

    instance_id: str
    source: str
    summary: StreamSummary
    c1: C1View
    reader: Callable[[], CaptureStream]
    result: LogResult
    log_path: Path


def _check_stream_owner(stream: CaptureStream, census: Sequence[str]) -> None:
    owners = {d.node_boot_id for d in stream.decisions if d.node_boot_id}
    owners |= {h.node_boot_id for h in stream.heartbeats if h.node_boot_id}
    if owners - set(census):
        raise AuditInputError("node_log_missing", "capture_node_boot_id_without_log")


def _log_of_ids(data_root: Path) -> dict[str, Path]:
    path_of: dict[str, Path] = {}
    for path in _listed_logs(data_root):
        for iid in _head_ids(path):
            path_of.setdefault(iid, path)
    return path_of


def _stream_reader(data_root: Path, source: str, iid: str) -> Callable[[], CaptureStream]:
    def read() -> CaptureStream:
        stream = _read_stream(data_root, source, iid)
        return stream if stream is not None else CaptureStream(instance_id=iid, source=source)

    return read


def _gather_boots(
    data_root: Path, family_id: str, census: Sequence[str]
) -> tuple[list[_BootRow], list[int]]:
    """Every census boot's streams (live, and canary when it exists) with its log's one scan, and
    the first record time of each live stream (the epoch check's input)."""
    path_of = _log_of_ids(data_root)
    results: dict[Path, LogResult] = {}
    rows: list[_BootRow] = []
    firsts: list[int] = []
    for iid in census:
        path = path_of.get(iid)
        if path is None:
            raise AuditInputError("node_log_missing", "boot_without_log")
        _check_deadline()
        if path not in results:
            results[path] = _scan_log(data_root, path)
        for source in SOURCES:
            stream = _read_stream(data_root, source, iid)
            if stream is None and source != "live":
                continue
            held = stream if stream is not None else CaptureStream(instance_id=iid, source=source)
            _check_stream_owner(held, census)
            first = _first_record_ns(held) if source == "live" else None
            firsts.extend([] if first is None else [first])
            reader = _stream_reader(data_root, source, iid)
            rows.append(
                _BootRow(
                    iid,
                    source,
                    _summary_of(held),
                    _project(held, family_id),
                    reader,
                    results[path],
                    path,
                )
            )
    return rows, firsts


def _supervisor_text(day: dt.date, have_logs: bool) -> str:
    return _tolerating_empty(
        SUPERVISOR_JOURNAL_ARGV, _slot(day, -1), _slot(day, 1), tolerate=not have_logs
    )


def _load_tape(data_root: Path, day: dt.date) -> RecorderCatalogTape:
    root = data_root.joinpath(*TAPE_REL)
    return RecorderCatalogTape(root, day, catalog_instruments(root, day))


def _journals(
    data_root: Path, day: dt.date, now_ns: int
) -> tuple[tuple[IngestLine, ...], bool, tuple[Any, ...]]:
    """The ingest lines, whether the ingest unit exited after D's rotation, and the recorder's
    ``UNIT_RESULT`` entries."""
    exit_ns = read_ingest_exit_ns(data_root, now_ns=now_ns)
    rotation_ns = _day_bounds_ns(day + dt.timedelta(days=1))[0] + _ROTATION_HOUR_UTC * 3600 * _NS
    exited = exit_ns is not None and exit_ns > rotation_ns
    recorder = parse_recorder_journal(
        _tolerating_empty(RECORDER_JOURNAL_ARGV, _slot(day, 0), _slot(day, 1), tolerate=True)
    )
    return _ingest_lines(day, exited), exited, recorder


def gather_inputs(data_root: Path, family_id: str, day: dt.date, *, now_ns: int) -> AuditInputs:
    """Everything one day's legs read, or ``AuditInputError``."""
    props = read_recorder_props(data_root, now_ns=now_ns)
    epoch = _read_epoch_record(data_root, family_id)
    exec_view = read_exec_view(data_root)
    have_logs = any(_overlaps_day(p, day) for p in _listed_logs(data_root))
    census = boot_census(data_root, day, supervisor_journal=_supervisor_text(day, have_logs))
    ingest, exited, recorder = _journals(data_root, day, now_ns)
    rows, firsts = _gather_boots(data_root, family_id, census)
    tape = _load_tape(data_root, day)
    boots = _settle_boots([_boot_for(r, day) for r in rows], day, now_ns, tape)
    _check_epoch(epoch, boots, firsts, day)
    boot_days = [utc_day_for_ns(b.started_ns) for b in boots if b.source == "live" and b.started_ns]
    offsets = _std_offsets()
    return AuditInputs(
        day=day,
        family_id=family_id,
        epoch=epoch,
        boots=boots,
        exec=exec_view,
        settlements=_settlements(data_root, day),
        std_offsets=offsets,
        tape=tape,
        ingest_lines=ingest,
        ingest_exited_after_rotation=exited,
        recorder_journal=recorder,
        recorder_props=props,
        stall_records=_stall_records(data_root, day),
        notifier_proofs=_notifier_proofs(data_root, day),
        now_ns=now_ns,
        funnel=_funnel_rows(data_root, boot_days),
        resolver_live=any(
            utc_day_for_ns(r.created_ns) == day for r in exec_view.resolvers if r.created_ns > 0
        ),
        nbp_stations=tuple(sorted(c for c in offsets if c.startswith("K"))),
        nbp_cycles_ns=_nbp_cycles_ns(day),
    )
