"""AUT-1 WP5 stage 2a: the audit's input value types (plan r12 section 3.11.1; design S2-R3).

``AuditInputs`` is the ONE value every leg reads: all I/O happens in ``capture_audit_inputs`` /
``capture_audit_host`` (stage 2b W3), so each leg is a pure function over this value. Every type is
frozen. ``BootEvidence`` holds REDUCED summaries and a lazy stream handle, never a boot's whole
tables; a leg that needs the full ``CaptureStream`` (leg B's frame copies and forecast references)
calls ``boot.stream()``, which reads one boot on demand.

Venue order ids appear only as sha256 (``venue_order_id_sha256``); no field holds a path.
Non-writer, no ``breezy.adapters`` import.
"""

import datetime as dt
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Protocol, runtime_checkable

from breezy.analysis.capture_aut6_contract import NotifierProof
from breezy.analysis.capture_node_log import LogSink, MarkerEvent, NodeLogScan
from breezy.analysis.capture_settlement import SettlementRecord
from breezy.persistence.autonomy.capture_epoch import EpochRecord
from breezy.persistence.autonomy.capture_reader import C1View, CaptureStream

__all__ = [
    "AuditInputs",
    "BootEvidence",
    "ExecFill",
    "ExecOrder",
    "ExecView",
    "FunnelCount",
    "FunnelRow",
    "HeartbeatSummary",
    "IngestLine",
    "LogMarkers",
    "LogSink",
    "MarkerLine",
    "NotifierProof",
    "RecorderJournalEntry",
    "RecorderProps",
    "ReplayResult",
    "ResolverContext",
    "StallRecord",
    "StreamSummary",
    "TapeIndex",
]

#: A parsed node-log marker line (``capture_node_log_markers``).
MarkerLine = MarkerEvent


def _empty_map() -> Mapping[str, int]:
    return MappingProxyType({})


def _empty_str_map() -> Mapping[str, str]:
    return MappingProxyType({})


def _empty_days() -> Mapping[str, tuple[str, ...]]:
    return MappingProxyType({})


@dataclass(frozen=True, slots=True)
class LogMarkers:
    """The marker lines of one boot on one UTC day, in log order. The collector is the W2
    ``MarkerParser`` sink; each list is bounded by what the node logs per day."""

    capture_refused: tuple[MarkerLine, ...] = ()
    order_submitted: tuple[MarkerLine, ...] = ()
    order_denied: tuple[MarkerLine, ...] = ()
    nbp_published: tuple[MarkerLine, ...] = ()
    fq_vector_complete: tuple[MarkerLine, ...] = ()
    nbp_cycle_missed: tuple[MarkerLine, ...] = ()
    #: ``CAPTURE_EPOCH_START`` lines (leg ``epoch_unlogged``); not in the design's list.
    capture_epoch_start: tuple[MarkerLine, ...] = ()


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """One boot-day's R2 replay (W2 ``BootReplay``): the node's real ``OnChangeFilter`` and
    ``EvalSeqCounter`` run over its ``SHADOW_DECISION`` lines WITHOUT dedupe (S2-R4)."""

    admitted_total: int = 0
    #: Admitted lines by decision kind (``Take``, ``TrySubmit``, ``Refuse``, ...).
    admitted_by_kind: Mapping[str, int] = field(default_factory=_empty_map)
    #: Evaluation lines seen (decision-class lines, TrySubmit excluded): ``EvalSeqCounter.next``
    #: runs once per evaluation, quote and depth twins included.
    evaluations: int = 0
    #: The counter value after the last evaluation of the boot-day.
    eval_seq_final: int = 0
    #: Lines excluded from both sides because they are guard ``EntryVeto``s (S2-R5).
    guard_vetoes_excluded: int = 0
    #: Byte-identical repeat lines: an INFO count only.
    duplicate_lines: int = 0
    #: Replayed admissions that differ from the stream's on-change records, and short samples.
    mismatches: int = 0
    mismatch_samples: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HeartbeatSummary:
    """One ``CaptureHeartbeat``: ``written_by_type`` is the snapshot taken just BEFORE its write."""

    ts_ns: int
    seq: int
    final: bool
    written_by_type: Mapping[str, int]
    #: The heartbeat's counted write drops (GM2). Required: R5 reads it from here, so a summary
    #: built without it must fail loudly rather than read as zero drops (S3-R20).
    write_drops: int


@dataclass(frozen=True, slots=True)
class StreamSummary:
    """A boot's stream reduced to what R5, R7 and the positive control need."""

    #: Rows present per table, over every file of the boot.
    row_counts: Mapping[str, int] = field(default_factory=_empty_map)
    heartbeats: tuple[HeartbeatSummary, ...] = ()
    torn_tail_count: int = 0
    unrecognised_file_count: int = 0
    #: ``(station, cycle_runtime_ns)`` of every streamed ``ForecastPoint`` (R-B existence check).
    forecast_cycles: frozenset[tuple[str, int]] = frozenset()


@dataclass(frozen=True, slots=True)
class BootEvidence:
    """One boot overlapping the audited day, matched by ``instance_id`` (WP0-R5)."""

    instance_id: str
    source: str
    #: Lazy handle: reads this boot's whole ``CaptureStream`` on demand (leg B only).
    stream: Callable[[], CaptureStream]
    summary: StreamSummary
    c1: C1View
    #: The node-log basename (never a path); ``None`` when the boot has no readable log.
    log_name: str | None
    #: The boot's ONE node-log pass summary (``scan_node_log``); ``None`` with no log.
    scan: NodeLogScan | None
    markers: LogMarkers
    replay: ReplayResult
    started_ns: int
    last_line_ts_ns: int | None
    #: The boot ended (a ``DISPOSED`` ``TradingNode`` line, or a later boot / spawn superseded it).
    ended: bool
    disposed: bool
    #: Seconds the boot overlapped the audited day.
    overlap_s: int
    #: Instruments the boot subscribed during the overlap (D13's node-independent trigger).
    subscribed: frozenset[str]


@dataclass(frozen=True, slots=True)
class ExecFill:
    """A durable fill record of the exec store (``fill/<venue_order_id>``), venue id hashed."""

    client_order_id: str
    venue_order_id_sha256: str
    trade_id: str | None
    instrument_id: str
    order_side: str
    cumulative_qty: str
    cumulative_cost: str
    ts_event: int
    fee_reconciled: bool


@dataclass(frozen=True, slots=True)
class ExecOrder:
    """A ``venue_id/`` row: a venue order id (hashed) and its client order id."""

    client_order_id: str
    venue_order_id_sha256: str


@dataclass(frozen=True, slots=True)
class ResolverContext:
    """A ``resolver/<intent_id>`` context."""

    intent_id: str
    client_order_id: str
    instrument_id: str
    created_ns: int


@dataclass(frozen=True, slots=True)
class ExecView:
    """The exec store as read by the E-8 snapshot with ``take_flock=False``: ADVISORY (it may lag
    the live store), so it never counts toward the join verdict on its own."""

    fills: tuple[ExecFill, ...] = ()
    #: ``fill_by_day/<day>`` -> the venue order ids (hashed) indexed under that UTC day.
    fill_by_day: Mapping[str, tuple[str, ...]] = field(default_factory=_empty_days)
    #: ``fill_by_fingerprint/<day>:<fp>`` -> the venue order id (hashed).
    fill_by_fingerprint: Mapping[str, str] = field(default_factory=_empty_str_map)
    orders: tuple[ExecOrder, ...] = ()
    resolvers: tuple[ResolverContext, ...] = ()
    advisory: bool = True


@dataclass(frozen=True, slots=True)
class FunnelCount:
    station: str
    side: str
    kind: str
    reason: str
    count: int


@dataclass(frozen=True, slots=True)
class FunnelRow:
    """One ``fq_funnel_<boot day>.jsonl`` summary row (a 15-minute flush)."""

    ts_ns: int
    boot_day: str
    counts: tuple[FunnelCount, ...]


@runtime_checkable
class TapeIndex(Protocol):
    """The recorder catalog as the audit reads it. The audit loads it eagerly in ``gather_inputs``;
    an I/O failure there is ``AuditInputError("tape_unreadable")`` (S2-R7)."""

    def lookup(
        self, frame_kind: str, instrument_id: str, ts_event: int
    ) -> Mapping[str, Any] | None:
        """The catalog row a frame reference names (``depth10`` or ``quote``), or None."""
        ...

    def quote_rows(
        self, instrument_id: str, start_ns: int, end_ns: int
    ) -> Iterable[Mapping[str, Any]]: ...

    def depth_rows(
        self, instrument_id: str, start_ns: int, end_ns: int
    ) -> Iterable[Mapping[str, Any]]: ...

    def best_ask_at(self, instrument_id: str, ts_ns: int) -> float | None: ...


@dataclass(frozen=True, slots=True)
class IngestLine:
    """One line of the ingest unit's journal (``-o cat``), timestamp-free text."""

    text: str


@dataclass(frozen=True, slots=True)
class RecorderJournalEntry:
    """One entry of the recorder unit's journal (``-o json``), reduced to what leg W reads."""

    ts_ns: int
    invocation_id: str
    unit_result: str
    message: str = ""


@dataclass(frozen=True, slots=True)
class RecorderProps:
    """``systemctl --user show -p WatchdogUSec -p NotifyAccess -p Type`` of the recorder, read
    through seam B's bus snapshot. Armed means ``watchdog_usec > 0``, ``type == "notify"`` and
    ``notify_access == "all"`` (r10, X-1, X-2)."""

    watchdog_usec: int
    notify_access: str
    type: str


@dataclass(frozen=True, slots=True)
class StallRecord:
    """An ``evidence/capture/stall/`` record of the recorder stop hook."""

    invocation_id: str
    ts_ns: int
    day: str
    heal_sha256: str = ""


@dataclass(frozen=True, slots=True)
class AuditInputs:
    """Everything one audited day reads. Fields after ``now_ns`` extend the design's list (each with
    a default): the funnel rows (D13), the resolver-live flag (S2-R13), and the configured NBP
    stations and cycles of leg N."""

    day: dt.date
    family_id: str
    epoch: EpochRecord | None
    boots: tuple[BootEvidence, ...]
    exec: ExecView
    settlements: tuple[SettlementRecord, ...]
    #: Station -> fixed standard-time UTC offset in hours (``climate_day_window``).
    std_offsets: Mapping[str, float]
    tape: TapeIndex
    ingest_lines: tuple[IngestLine, ...]
    #: ``breezy-quote-tape-ingest.service`` has ``ExecMainExitTimestamp`` later than D's rotation.
    ingest_exited_after_rotation: bool
    recorder_journal: tuple[RecorderJournalEntry, ...]
    recorder_props: RecorderProps
    stall_records: tuple[StallRecord, ...]
    notifier_proofs: tuple[NotifierProof, ...]
    now_ns: int
    funnel: tuple[FunnelRow, ...] = ()
    #: A resolver context was live on D: ``registry_seq == 0`` after it fails the day (S2-R13).
    resolver_live: bool = False
    nbp_stations: tuple[str, ...] = ()
    #: The configured NBP cycle runtimes (epoch ns) whose publication deadline fell on D.
    nbp_cycles_ns: tuple[int, ...] = ()
