"""AUT-1 streaming node-log parser (plan r12 section 3.11, r8 WP5; build rulings WP0-R7, WP5-R4).

A READ-ONLY, memory-bounded reader of the trade node's ``breezy-trade-<stamp>.log`` files and the
supervisor's log. It holds only lines that matter, never the whole file, so a 1 GB log scans in
memory proportional to the number of matches. This module is the facade; the parts are

* ``capture_node_log_io``: the bounded line reader, timestamps and report types;
* ``capture_node_log_decisions``: line classification, Take/TrySubmit pairing, duplicate digests;
* ``capture_node_log_spawns``: the supervisor spawn events and the boot census.

What it extracts:

* **Decision lines**, classified by ``kind``. Each evaluation emits exactly one decision-class line;
  a Take adds one ``TrySubmit`` line when ``shadow_only=False``. So ``evaluation_count`` is total
  minus TrySubmit (R3), ``pair_take_trysubmit`` pairs each TrySubmit with its Take (R1) and
  ``drop_try_submits`` removes TrySubmit before an on-change/``eval_seq`` replay (R2).
  ``scan_node_log(keep_kinds=...)`` retains the requested kinds in one pass.
* **Byte-identical repeats** (older builds): ``duplicate_decision_count`` and
  ``evaluation_count_deduped``; whether a repeat fails a day is the audit's ruling.
* **Boot end and writer failures**: ``<component>: DISPOSED`` (the ``TradingNode`` line ends a boot)
  and the three writer-failure texts.
* **Spawn events and the boot census**: see ``capture_node_log_spawns``.

Failure handling: a marker line that does not parse, an unterminated last line and every overlong
line are REPORTED (``UnparseableLine``), never skipped; no hostile line raises. Counts are exact
even when a stored list is capped at ``MAX_STORED_REPORTS``. An unreadable file raises
``NodeLogUnreadable`` (the audit maps it to ERROR).

Non-writer: stdlib only, no ``breezy.adapters`` import.
"""

from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from breezy.analysis.capture_node_log_decisions import (
    DISPOSED_TEXT,
    EVALUATION_KINDS,
    KIND_TAKE,
    KIND_TRY_SUBMIT,
    MARKER_CAPTURE_PUBLISH_FAILED,
    MARKER_FAILED_TO_SERIALIZE,
    MARKER_MISSING_WRITER,
    DecisionLine,
    DisposedLine,
    DuplicateTracker,
    EntryPairing,
    InstanceIdLine,
    NodeLogEvent,
    OrderFilledLine,
    TakeInputs,
    WriterFailureLine,
    classify_line,
    dedupe_decisions,
    drop_try_submits,
    is_try_submit,
    marker_name,
    pair_take_trysubmit,
)
from breezy.analysis.capture_node_log_io import (
    CAUSE_BAD_FIELDS,
    CAUSE_INVALID_LOG_NAME,
    CAUSE_LINE_TOO_LONG,
    CAUSE_NO_MATCH,
    CAUSE_NODE_LOG_MISSING,
    CAUSE_TORN_TAIL,
    CAUSE_UNDECODABLE,
    CAUSE_UNKNOWN_KIND,
    CAUSE_UNMATCHED_LOG_IN_WINDOW,
    FAILURE_RE,
    MAX_LINE_BYTES,
    MAX_STORED_REPORTS,
    LogFinding,
    NodeLogUnreadable,
    RawLine,
    UnparseableLine,
    read_lines,
    ts_matches,
    ts_ns,
    unparseable,
)
from breezy.analysis.capture_node_log_markers import (
    MARKER_CAPTURE_EPOCH_START,
    MARKER_CAPTURE_REFUSED,
    MARKER_FQ_VECTOR_COMPLETE,
    MARKER_NBP_CYCLE_MISSED,
    MARKER_NBP_PUBLISHED,
    MARKER_ORDER_DENIED,
    MARKER_ORDER_SUBMITTED,
    MAX_MARKER_TEXT_CHARS,
    CaptureEpochStartLine,
    CaptureRefusedLine,
    FqVectorCompleteLine,
    MarkerEvent,
    NbpCycleMissedLine,
    NbpPublishedLine,
    OrderDeniedLine,
    OrderSubmittedLine,
)
from breezy.analysis.capture_node_log_sinks import LogSink, NodeLogSinkFailed
from breezy.analysis.capture_node_log_spawns import (
    LOG_STAMP_MAX_LAG_S,
    NO_SPAWN_EVENTS,
    POST_SPAWN_EARLY_S,
    POST_SPAWN_LATE_S,
    PRE_SPAWN_EARLY_S,
    PRE_SPAWN_EVENTS,
    SPAWN_EVENTS,
    NodeLogListing,
    SpawnCensus,
    SpawnEvent,
    SpawnMatch,
    SupervisorScan,
    list_node_logs,
    match_spawns_to_logs,
    parse_supervisor_lines,
    scan_supervisor_log,
)

__all__ = [
    "CAUSE_BAD_FIELDS",
    "CAUSE_INVALID_LOG_NAME",
    "CAUSE_LINE_TOO_LONG",
    "CAUSE_NODE_LOG_MISSING",
    "CAUSE_NO_MATCH",
    "CAUSE_TORN_TAIL",
    "CAUSE_UNDECODABLE",
    "CAUSE_UNKNOWN_KIND",
    "CAUSE_UNMATCHED_LOG_IN_WINDOW",
    "DEFAULT_KEEP_KINDS",
    "DISPOSED_TEXT",
    "EVALUATION_KINDS",
    "KIND_TAKE",
    "KIND_TRY_SUBMIT",
    "LOG_STAMP_MAX_LAG_S",
    "MARKER_CAPTURE_EPOCH_START",
    "MARKER_CAPTURE_PUBLISH_FAILED",
    "MARKER_CAPTURE_REFUSED",
    "MARKER_FAILED_TO_SERIALIZE",
    "MARKER_FQ_VECTOR_COMPLETE",
    "MARKER_MISSING_WRITER",
    "MARKER_NBP_CYCLE_MISSED",
    "MARKER_NBP_PUBLISHED",
    "MARKER_ORDER_DENIED",
    "MARKER_ORDER_SUBMITTED",
    "MAX_LINE_BYTES",
    "MAX_MARKER_TEXT_CHARS",
    "MAX_STORED_REPORTS",
    "NO_SPAWN_EVENTS",
    "POST_SPAWN_EARLY_S",
    "POST_SPAWN_LATE_S",
    "PRE_SPAWN_EARLY_S",
    "PRE_SPAWN_EVENTS",
    "SPAWN_EVENTS",
    "CaptureEpochStartLine",
    "CaptureRefusedLine",
    "DecisionLine",
    "DisposedLine",
    "DuplicateTracker",
    "EntryPairing",
    "FqVectorCompleteLine",
    "InstanceIdLine",
    "LogFinding",
    "LogSink",
    "MarkerEvent",
    "NbpCycleMissedLine",
    "NbpPublishedLine",
    "NodeLogEvent",
    "NodeLogListing",
    "NodeLogScan",
    "NodeLogSinkFailed",
    "NodeLogUnreadable",
    "OrderDeniedLine",
    "OrderFilledLine",
    "OrderSubmittedLine",
    "SpawnCensus",
    "SpawnEvent",
    "SpawnMatch",
    "SupervisorScan",
    "TakeInputs",
    "UnparseableLine",
    "WriterFailureLine",
    "classify_line",
    "dedupe_decisions",
    "distinct_boot_ids",
    "drop_try_submits",
    "is_try_submit",
    "iter_node_log",
    "list_node_logs",
    "match_spawns_to_logs",
    "pair_take_trysubmit",
    "parse_supervisor_lines",
    "scan_node_log",
    "scan_supervisor_log",
]

#: The decision kinds ``scan_node_log`` keeps by default: the entry lines R1 pairs.
DEFAULT_KEEP_KINDS: Final[frozenset[str]] = frozenset({KIND_TAKE, KIND_TRY_SUBMIT})
_KNOWN_KINDS: Final[frozenset[str]] = EVALUATION_KINDS | {KIND_TRY_SUBMIT}
_HEAD_BYTES: Final[int] = 96


def _events_for(rl: RawLine) -> list[NodeLogEvent]:
    """The events one raw line yields (an overlong line may yield two)."""
    if rl.truncated:
        events: list[NodeLogEvent] = [unparseable(rl.line_no, "line", CAUSE_LINE_TOO_LONG, rl.raw)]
        hit = FAILURE_RE.search(rl.raw)
        found = hit.group(0) if hit else rl.tail_failure
        if found is not None:
            events.append(WriterFailureLine(rl.line_no, ts_ns(rl.raw), marker_name(found)))
        return events
    if not rl.terminated and rl.raw.strip():
        return [unparseable(rl.line_no, "line", CAUSE_TORN_TAIL, rl.raw)]
    event = classify_line(rl.raw, rl.line_no)
    return [] if event is None else [event]


def iter_node_log(path: Path) -> Iterator[NodeLogEvent]:
    """Stream the classified events of one node log, in file order, holding one line at a time.

    Raises ``NodeLogUnreadable`` if the file cannot be opened or read."""
    for rl in read_lines(path):
        yield from _events_for(rl)


@dataclass(frozen=True, slots=True)
class NodeLogScan:
    """The summary of one node log. Stored lists are capped at ``MAX_STORED_REPORTS``; every
    ``*_total`` and count is exact."""

    line_count: int
    decision_line_count: int
    kind_counts: Mapping[str, int]
    #: Decision lines of the kept kinds, in log order (default: Take and TrySubmit).
    entry_lines: tuple[DecisionLine, ...]
    entry_total: int
    instance_ids: tuple[str, ...]
    instance_id_total: int
    disposed_count: int
    node_disposed: bool
    fills: tuple[OrderFilledLine, ...]
    fill_total: int
    writer_failures: tuple[WriterFailureLine, ...]
    writer_failure_total: int
    unparseable: tuple[UnparseableLine, ...]
    unparseable_total: int
    #: Marker lines seen, by marker name (``capture_node_log_markers``); exact, never capped.
    marker_counts: Mapping[str, int]
    #: Byte-identical repeats within a tick (all kinds; evaluation kinds only).
    duplicate_decision_count: int
    duplicate_evaluation_count: int
    #: Timestamp of the last TIMESTAMPED line (a traceback tail has none).
    last_line_ts_ns: int | None

    @property
    def evaluation_count(self) -> int:
        """R3: total decision-class lines minus TrySubmit lines."""
        return self.decision_line_count - self.kind_counts.get(KIND_TRY_SUBMIT, 0)

    @property
    def evaluation_count_deduped(self) -> int:
        """``evaluation_count`` less the byte-identical repeats."""
        return self.evaluation_count - self.duplicate_evaluation_count

    @property
    def has_writer_failure(self) -> bool:
        return self.writer_failure_total > 0

    @property
    def takes(self) -> tuple[DecisionLine, ...]:
        return tuple(ln for ln in self.entry_lines if ln.kind == KIND_TAKE)

    @property
    def try_submits(self) -> tuple[DecisionLine, ...]:
        return tuple(ln for ln in self.entry_lines if ln.kind == KIND_TRY_SUBMIT)


@dataclass(slots=True)
class _Counts:
    line_count: int = 0
    entry_total: int = 0
    instance_id_total: int = 0
    disposed: int = 0
    fill_total: int = 0
    failures: int = 0
    bad: int = 0
    duplicates: int = 0
    duplicate_evaluations: int = 0
    node_disposed: bool = False


@dataclass(slots=True)
class _Stored:
    entries: list[DecisionLine]
    instance_ids: dict[str, None]
    fills: list[OrderFilledLine]
    failures: list[WriterFailureLine]
    bad: list[UnparseableLine]


_MARKER_NAMES: Final[Mapping[type, str]] = {
    CaptureRefusedLine: MARKER_CAPTURE_REFUSED,
    OrderSubmittedLine: MARKER_ORDER_SUBMITTED,
    OrderDeniedLine: MARKER_ORDER_DENIED,
    NbpPublishedLine: MARKER_NBP_PUBLISHED,
    FqVectorCompleteLine: MARKER_FQ_VECTOR_COMPLETE,
    NbpCycleMissedLine: MARKER_NBP_CYCLE_MISSED,
    CaptureEpochStartLine: MARKER_CAPTURE_EPOCH_START,
}


def _feed(sinks: Sequence[LogSink], event: NodeLogEvent) -> None:
    for sink in sinks:
        try:
            sink.feed(event)
        except Exception as exc:
            raise NodeLogSinkFailed(type(exc).__name__) from exc


def _absorb(
    event: NodeLogEvent,
    keep: frozenset[str],
    counts: _Counts,
    stored: _Stored,
    kinds: Counter[str],
    tracker: DuplicateTracker,
    markers: Counter[str],
) -> None:
    cap = MAX_STORED_REPORTS
    if isinstance(event, MarkerEvent):
        markers[_MARKER_NAMES[type(event)]] += 1
    elif isinstance(event, DecisionLine):
        kinds[event.kind] += 1
        if tracker.is_duplicate(event):
            counts.duplicates += 1
            counts.duplicate_evaluations += event.kind != KIND_TRY_SUBMIT
        if event.kind in keep:
            counts.entry_total += 1
            if len(stored.entries) < cap:
                stored.entries.append(event)
    elif isinstance(event, InstanceIdLine):
        counts.instance_id_total += 1
        if len(stored.instance_ids) < cap:
            stored.instance_ids.setdefault(event.instance_id)
    elif isinstance(event, DisposedLine):
        counts.disposed += 1
        counts.node_disposed = counts.node_disposed or event.is_trading_node
    elif isinstance(event, OrderFilledLine):
        counts.fill_total += 1
        if len(stored.fills) < cap:
            stored.fills.append(event)
    elif isinstance(event, WriterFailureLine):
        counts.failures += 1
        if len(stored.failures) < cap:
            stored.failures.append(event)
    else:
        counts.bad += 1
        if len(stored.bad) < cap:
            stored.bad.append(event)


def scan_node_log(
    path: Path,
    *,
    keep_kinds: frozenset[str] = DEFAULT_KEEP_KINDS,
    sinks: Sequence[LogSink] = (),
) -> NodeLogScan:
    """One streaming pass over a node log. Raises ``NodeLogUnreadable``.

    ``keep_kinds`` names the decision kinds retained in ``entry_lines`` (every kind is always
    counted); ``ValueError`` for an unknown kind.

    ``sinks`` (S2-R1) are online consumers: each is fed EVERY event, in file order and uncapped,
    before the scan's own accounting, so the audit's replay and marker reducers run in this one pass
    (``entry_lines`` is capped). A sink that raises aborts the scan with
    ``NodeLogSinkFailed``; no later event is fed to any sink."""
    unknown = keep_kinds - _KNOWN_KINDS
    if unknown:
        raise ValueError(f"unknown decision kinds: {sorted(unknown)}")
    kinds: Counter[str] = Counter()
    counts = _Counts()
    stored = _Stored([], {}, [], [], [])
    tracker = DuplicateTracker()
    markers: Counter[str] = Counter()
    last_head = b""
    for rl in read_lines(path):
        counts.line_count = rl.line_no
        if ts_matches(rl.raw[:_HEAD_BYTES]):
            last_head = rl.raw[:_HEAD_BYTES]
        for event in _events_for(rl):
            _feed(sinks, event)
            _absorb(event, keep_kinds, counts, stored, kinds, tracker, markers)
    return NodeLogScan(
        line_count=counts.line_count,
        decision_line_count=sum(kinds.values()),
        kind_counts=MappingProxyType(dict(kinds)),
        entry_lines=tuple(stored.entries),
        entry_total=counts.entry_total,
        instance_ids=tuple(stored.instance_ids),
        instance_id_total=counts.instance_id_total,
        disposed_count=counts.disposed,
        node_disposed=counts.node_disposed,
        fills=tuple(stored.fills),
        fill_total=counts.fill_total,
        writer_failures=tuple(stored.failures),
        writer_failure_total=counts.failures,
        unparseable=tuple(stored.bad),
        unparseable_total=counts.bad,
        marker_counts=MappingProxyType(dict(markers)),
        duplicate_decision_count=counts.duplicates,
        duplicate_evaluation_count=counts.duplicate_evaluations,
        last_line_ts_ns=ts_ns(last_head) if last_head else None,
    )


def distinct_boot_ids(scans: Iterable[NodeLogScan]) -> tuple[str, ...]:
    """Boots are counted by ``TradingNode: instance_id:``, never by a time window (WP0-R5)."""
    seen: dict[str, None] = {}
    for scan in scans:
        for instance_id in scan.instance_ids:
            seen.setdefault(instance_id)
    return tuple(seen)
