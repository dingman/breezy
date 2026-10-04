"""AUT-1 WP5 stage 2b, W2: the online R2 replay and legs R1, R2 and R3 (design S2-R4, S2-R5).

``BootReplay`` is a ``LogSink`` fed by the one ``scan_node_log`` pass. It replays every
``SHADOW_DECISION`` line through the REAL ``OnChangeFilter`` and ``EvalSeqCounter`` (never a
reimplementation), one fresh pair per ``TradingNode: instance_id:`` line, so a boot's state never
leaks into the next. State carries across UTC midnight; the outputs are partitioned by the UTC day
of each line, keyed ``(instance_id, day)``.

Replay rules (S2-R4, S2-R5), all pinned by ``tests/unit/test_capture_audit_recon_legs.py``:

* NO dedupe. ``EvalSeqCounter.next`` runs once per evaluation line, quote and depth twins included;
  byte-identical repeats are only COUNTED (an INFO finding, never a FAIL).
* A ``TrySubmit`` line never advances the counter. It enters the filter as the node's
  ``FqCaptureAdapter.follow_up`` does: as ``TrySubmit``, or as ``EntryVeto`` when its reason is a
  ``VetoReason``, under the paired Take's ``eval_ns``. ``drop_try_submits`` is never used here.
* A capture-guard ``EntryVeto`` (``is_guard_entry_veto``) is excluded on BOTH sides: the replay and
  the stream comparison.

State is bounded: the filter and the Take memory evict by climate day, the counter keeps four
``ts_event`` values per instrument, and the comparison with the stream is a hash chain over the
admitted sequence with checkpoints only for the last ``FLUSH_WINDOW_S`` seconds of the boot, so the
sequence itself is never stored. ``BootDayReplay`` extends ``ReplayResult`` with that chain.

Signatures of the stub set are pinned by ``tests/unit/test_capture_audit_stubs.py``.
"""

import datetime as dt
import hashlib
from collections import Counter, deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final

from breezy.analysis.capture_audit_input_types import (
    AuditInputs,
    BootEvidence,
    FunnelRow,
    LogSink,
    ReplayResult,
)
from breezy.analysis.capture_audit_model import (
    FLUSH_WINDOW_S,
    Finding,
    Leg,
    LegOutcome,
    LegResult,
    MetricValue,
    is_guard_entry_veto,
)
from breezy.analysis.capture_node_log import (
    EVALUATION_KINDS,
    KIND_TAKE,
    KIND_TRY_SUBMIT,
    CaptureRefusedLine,
    DecisionLine,
    DuplicateTracker,
    InstanceIdLine,
    NodeLogEvent,
    NodeLogScan,
)
from breezy.persistence.autonomy.capture_ids import EvalSeqCounter
from breezy.persistence.autonomy.capture_on_change import OnChangeFilter
from breezy.persistence.autonomy.veto import VetoReason

__all__ = ["BootDayReplay", "BootReplay", "leg_r1", "leg_r2", "leg_r3"]

_NS: Final[int] = 1_000_000_000
_NS_PER_DAY: Final[int] = 86_400 * _NS
_REASON_TAKE: Final[str] = "take"
_REASON_SUBMITTED: Final[str] = "submitted"
_KIND_ENTRY_VETO: Final[str] = "EntryVeto"
_VETO_REASONS: Final[frozenset[str]] = frozenset(reason.value for reason in VetoReason)
#: The kinds a boot's ``DecisionRecord`` stream holds that ``SHADOW_DECISION`` lines also describe.
#: ``Exit`` records have no decision line, so they are not part of the replay.
_REPLAYED_KINDS: Final[frozenset[str]] = EVALUATION_KINDS | {KIND_TRY_SUBMIT, _KIND_ENTRY_VETO}
_ENTRY_RECORD_KINDS: Final[frozenset[str]] = frozenset(
    {KIND_TAKE, KIND_TRY_SUBMIT, _KIND_ENTRY_VETO}
)
_BOOT_NONE: Final[str] = ""
_FUNNEL_RACE_S: Final[int] = 2
_FUNNEL_KINDS: Final[frozenset[str]] = frozenset({KIND_TAKE, KIND_TRY_SUBMIT})
_MAX_SAMPLES: Final[int] = 5
_CHAIN_DIGEST_BYTES: Final[int] = 16

#: ``(station, climate_day ISO, rung_id, side)``: the on-change key.
_Key = tuple[str, str, str, str]
#: ``(station, climate_day, rung_id, side, kind, reason, eval_ns, eval_seq)``.
_Entry = tuple[str, str, str, str, str, str, int, int]

CAUSE_CAPTURE_MISSING: Final[str] = "capture_missing"
CAUSE_CAPTURE_UNEXPLAINED: Final[str] = "capture_unexplained"
CAUSE_VETO_UNANCHORED: Final[str] = "veto_line_unanchored"
CAUSE_ENTRY_LINES_CAPPED: Final[str] = "entry_lines_capped"
CAUSE_GUARD_VETO_UNMATCHED: Final[str] = "guard_veto_without_capture_refused"
CAUSE_CAPTURE_REFUSED_UNMATCHED: Final[str] = "capture_refused_without_veto_record"
CAUSE_R2_MISMATCH: Final[str] = "r2_sequence_mismatch"
CAUSE_R2_UNEXPLAINED: Final[str] = "r2_unexplained_records"
CAUSE_STREAM_RECORD_LOST: Final[str] = "stream_record_lost"
CAUSE_REPLAY_UNANCHORED: Final[str] = "replay_unanchored_follow_up"
CAUSE_DUPLICATES: Final[str] = "duplicate_decision_lines"
CAUSE_LOST_IN_FLUSH_WINDOW: Final[str] = "lost_in_flush_window"
CAUSE_FUNNEL_MISMATCH: Final[str] = "funnel_count_mismatch"


def _day_of(ns: int) -> dt.date:
    """The UTC day of an epoch-ns instant (total: no instant raises)."""
    return dt.datetime.fromtimestamp(ns // _NS, dt.UTC).date()


def _day_bounds(day: dt.date) -> tuple[int, int]:
    start = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp()) * _NS
    return start, start + _NS_PER_DAY


def _follow_up_kind(reason: str) -> str:
    """The record kind a logged ``TrySubmit`` line stands for (``FqCaptureAdapter.follow_up``): an
    ``EntryVeto`` when the reason is a ``VetoReason``, else the ``TrySubmit`` it says it is."""
    return _KIND_ENTRY_VETO if reason in _VETO_REASONS else KIND_TRY_SUBMIT


def _cutoff_day(now_ns: int) -> str:
    """The eviction cutoff the node's filter uses: the UTC day of ``now_ns`` minus one."""
    return (_day_of(now_ns) - dt.timedelta(days=1)).isoformat()


def _chain(previous: bytes, entry: _Entry) -> bytes:
    return hashlib.blake2b(
        previous + repr(entry).encode("utf-8"), digest_size=_CHAIN_DIGEST_BYTES
    ).digest()


def _only[T](lines: Iterable[object], kind: type[T]) -> list[T]:
    """The lines of one marker type (``LogMarkers`` fields are typed as the whole marker union)."""
    return [line for line in lines if isinstance(line, kind)]


def _rollup(leg: Leg, findings: Iterable[Finding], metrics: Mapping[str, MetricValue]) -> LegResult:
    """The leg outcome from its findings: ERROR over FAIL over INFO over PASS."""
    found = tuple(findings)
    outcomes = {finding.outcome for finding in found}
    if LegOutcome.ERROR in outcomes:
        outcome = LegOutcome.ERROR
    elif LegOutcome.FAIL in outcomes:
        outcome = LegOutcome.FAIL
    elif LegOutcome.INFO in outcomes:
        outcome = LegOutcome.INFO
    else:
        outcome = LegOutcome.PASS
    return LegResult(leg, outcome, found, MappingProxyType(dict(metrics)))


# -- the replay result ----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BootDayReplay(ReplayResult):
    """A ``ReplayResult`` that also carries the hash chain of the boot-day's admitted sequence.

    ``chain_digest`` covers every admitted entry of the boot-day (``admitted_total`` of them) in log
    order. ``base_count`` and ``base_digest`` are the chain just before the entries within
    ``FLUSH_WINDOW_S`` of the boot's last log line; ``tail`` holds one ``(count, digest)`` per such
    entry. A stream that stops at any tail count is a legitimate flush-window loss; anywhere else
    it is a mismatch."""

    chain_digest: str = ""
    base_count: int = 0
    base_digest: str = ""
    tail: tuple[tuple[int, str], ...] = ()


@dataclass(slots=True)
class _DayAcc:
    admitted: Counter[str] = field(default_factory=Counter)
    evaluations: int = 0
    eval_seq_final: int = 0
    guard_excluded: int = 0
    duplicates: int = 0
    mismatches: int = 0
    samples: list[str] = field(default_factory=list)
    count: int = 0
    digest: bytes = b""
    base_count: int = 0
    base_digest: bytes = b""
    #: ``(count after, digest after, log ts)`` of the entries inside the flush window.
    tail: deque[tuple[int, bytes, int]] = field(default_factory=deque)


@dataclass(slots=True)
class _BootState:
    on_change: OnChangeFilter = field(default_factory=OnChangeFilter)
    counter: EvalSeqCounter = field(default_factory=EvalSeqCounter)
    tracker: DuplicateTracker = field(default_factory=DuplicateTracker)
    #: The last Take per key: ``(eval_ns, eval_seq)``, the clock and ordinal a follow-up inherits.
    takes: dict[_Key, tuple[int, int]] = field(default_factory=dict)
    last_ts_ns: int = 0
    days: dict[dt.date, _DayAcc] = field(default_factory=dict)


def _feed_decision(state: _BootState, line: DecisionLine) -> None:
    state.last_ts_ns = max(state.last_ts_ns, line.log_ts_ns)
    acc = state.days.setdefault(_day_of(line.log_ts_ns), _DayAcc())
    if state.tracker.is_duplicate(line):
        acc.duplicates += 1  # counted, never dropped: the node evaluated twice (S2-R4)
    key: _Key = (line.station, line.climate_day.isoformat(), line.rung_id, line.side)
    if line.kind == KIND_TRY_SUBMIT:
        _feed_follow_up(state, acc, line, key)
        return
    eval_seq = state.counter.next(line.instrument_id, line.now_ns)
    acc.evaluations += 1
    acc.eval_seq_final = eval_seq
    reason = _REASON_TAKE if line.kind == KIND_TAKE else (line.reason or "")
    if line.kind == KIND_TAKE:
        if key not in state.takes:
            _evict_takes(state, line.now_ns)
        state.takes[key] = (line.now_ns, eval_seq)
    if state.on_change.admit(key, line.kind, reason, line.now_ns):
        _admit(state, acc, line, (*key, line.kind, reason, line.now_ns, eval_seq))


def _feed_follow_up(state: _BootState, acc: _DayAcc, line: DecisionLine, key: _Key) -> None:
    reason = line.reason or ""
    kind = _follow_up_kind(reason)
    if is_guard_entry_veto(kind, reason):
        acc.guard_excluded += 1
        return
    take = state.takes.get(key)
    if take is None:
        acc.mismatches += 1
        if len(acc.samples) < _MAX_SAMPLES:
            acc.samples.append(f"{CAUSE_REPLAY_UNANCHORED} line={line.line_no}")
        return
    eval_ns, eval_seq = take
    if state.on_change.admit(key, kind, reason, eval_ns):
        _admit(state, acc, line, (*key, kind, reason, eval_ns, eval_seq))


def _evict_takes(state: _BootState, now_ns: int) -> None:
    cutoff = _cutoff_day(now_ns)
    for stale in [key for key in state.takes if key[1] < cutoff]:
        del state.takes[stale]


def _admit(state: _BootState, acc: _DayAcc, line: DecisionLine, entry: _Entry) -> None:
    acc.admitted[entry[4]] += 1
    acc.count += 1
    acc.digest = _chain(acc.digest, entry)
    acc.tail.append((acc.count, acc.digest, line.log_ts_ns))
    floor = state.last_ts_ns - FLUSH_WINDOW_S * _NS
    while acc.tail and acc.tail[0][2] < floor:
        acc.base_count, acc.base_digest, _ = acc.tail.popleft()


def _day_result(state: _BootState, acc: _DayAcc) -> BootDayReplay:
    floor = state.last_ts_ns - FLUSH_WINDOW_S * _NS
    base_count, base_digest = acc.base_count, acc.base_digest
    tail = list(acc.tail)
    while tail and tail[0][2] < floor:
        base_count, base_digest, _ = tail.pop(0)
    return BootDayReplay(
        admitted_total=acc.count,
        admitted_by_kind=MappingProxyType(dict(acc.admitted)),
        evaluations=acc.evaluations,
        eval_seq_final=acc.eval_seq_final,
        guard_vetoes_excluded=acc.guard_excluded,
        duplicate_lines=acc.duplicates,
        mismatches=acc.mismatches,
        mismatch_samples=tuple(acc.samples),
        chain_digest=acc.digest.hex(),
        base_count=base_count,
        base_digest=base_digest.hex(),
        tail=tuple((count, digest.hex()) for count, digest, _ in tail),
    )


class BootReplay(LogSink):
    """The online R2 reducer (a ``LogSink`` with bounded state)."""

    def __init__(self) -> None:
        self._boots: dict[str, _BootState] = {}
        self._instance_id = _BOOT_NONE

    def feed(self, event: NodeLogEvent) -> None:
        if isinstance(event, InstanceIdLine):
            self._instance_id = event.instance_id
        elif isinstance(event, DecisionLine):
            _feed_decision(self._boots.setdefault(self._instance_id, _BootState()), event)

    def results(self) -> Mapping[tuple[str, dt.date], ReplayResult]:
        """The replay result of each ``(instance_id, UTC day)`` seen."""
        found: dict[tuple[str, dt.date], ReplayResult] = {}
        for instance_id, state in self._boots.items():
            for day, acc in state.days.items():
                found[(instance_id, day)] = _day_result(state, acc)
        return MappingProxyType(found)


# -- the stream side of R2 ------------------------------------------------------------------------


def _stream_entries(boot: BootEvidence, day: dt.date) -> list[_Entry]:
    """The boot's on-change ``DecisionRecord`` sequence for ``day``, in file order, guard
    ``EntryVeto`` records excluded (the other half of S2-R5)."""
    entries: list[_Entry] = []
    for record in boot.c1.decisions:
        if record.kind not in _REPLAYED_KINDS or is_guard_entry_veto(record.kind, record.reason):
            continue
        if _day_of(record.wall_ns) != day:
            continue
        entries.append(
            (
                record.station,
                record.climate_day,
                record.rung_id,
                record.side,
                record.kind,
                record.reason,
                record.eval_ns,
                record.eval_seq,
            )
        )
    return entries


@dataclass(frozen=True, slots=True)
class _Reconciliation:
    """``verdict``: ``ok``, ``mismatch``, ``lost`` (short beyond the flush window) or ``extra``."""

    verdict: str
    lost_in_window: int = 0
    detail: str = ""


def _prefix_digests(entries: list[_Entry], wanted: set[int]) -> dict[int, str]:
    digests = {0: ""}
    previous = b""
    for count, entry in enumerate(entries, start=1):
        previous = _chain(previous, entry)
        if count in wanted:
            digests[count] = previous.hex()
    return digests


def _reconcile_counts(replay: ReplayResult, entries: list[_Entry]) -> _Reconciliation:
    """Fallback for a plain ``ReplayResult`` (no chain): the counts must agree."""
    present = len(entries)
    if present == replay.admitted_total:
        return _Reconciliation("ok")
    verdict = "lost" if present < replay.admitted_total else "extra"
    return _Reconciliation(verdict, detail=f"replay={replay.admitted_total} stream={present}")


def _reconcile(boot: BootEvidence, day: dt.date) -> _Reconciliation:
    replay = boot.replay
    entries = _stream_entries(boot, day)
    if not isinstance(replay, BootDayReplay):
        return _reconcile_counts(replay, entries)
    total, present = replay.admitted_total, len(entries)
    known = {replay.base_count: replay.base_digest, **dict(replay.tail)}
    digests = _prefix_digests(entries, {total, present, *known})
    detail = f"replay={total} stream={present}"
    if present >= total:
        if digests[total] != replay.chain_digest:
            return _Reconciliation("mismatch", detail=detail)
        return _Reconciliation("ok" if present == total else "extra", detail=detail)
    if present < replay.base_count or known.get(present) != digests[present]:
        return _Reconciliation("lost", detail=detail)  # short, and not by the flush-window tail
    return _Reconciliation("ok", lost_in_window=total - present, detail=detail)


def _decision_loss(boot: BootEvidence, day: dt.date) -> int:
    """How many admitted decisions the stream lacks inside the boot's flush window (0 if none)."""
    return _reconcile(boot, day).lost_in_window


# -- leg R2 ---------------------------------------------------------------------------------------


def _scanned(inp: AuditInputs) -> list[tuple[BootEvidence, NodeLogScan]]:
    """The boots that have a node-log summary (a boot without one is the gatherer's ERROR)."""
    return [(boot, boot.scan) for boot in inp.boots if boot.scan is not None]


def leg_r2(inp: AuditInputs) -> LegResult:
    """The replay equals the boot's on-change ``DecisionRecord`` sequence."""
    findings: list[Finding] = []
    duplicates = lost = 0
    for boot, _scan in _scanned(inp):
        replay = boot.replay
        duplicates += replay.duplicate_lines
        if replay.duplicate_lines:
            findings.append(
                Finding(
                    Leg.R2,
                    LegOutcome.INFO,
                    CAUSE_DUPLICATES,
                    boot.instance_id,
                    f"lines={replay.duplicate_lines}",
                )
            )
        if replay.mismatches:
            findings.append(
                Finding(
                    Leg.R2,
                    LegOutcome.FAIL,
                    CAUSE_REPLAY_UNANCHORED,
                    boot.instance_id,
                    "; ".join(replay.mismatch_samples),
                )
            )
        result = _reconcile(boot, inp.day)
        lost += result.lost_in_window
        findings.extend(_r2_findings(boot.instance_id, result))
    metrics: dict[str, MetricValue] = {
        "duplicate_decision_lines": duplicates,
        "records_lost_in_flush_window": lost,
    }
    return _rollup(Leg.R2, findings, metrics)


def _r2_findings(instance_id: str, result: _Reconciliation) -> list[Finding]:
    causes = {
        "mismatch": CAUSE_R2_MISMATCH,
        "lost": CAUSE_STREAM_RECORD_LOST,
        "extra": CAUSE_R2_UNEXPLAINED,
    }
    if result.verdict in causes:
        return [
            Finding(Leg.R2, LegOutcome.FAIL, causes[result.verdict], instance_id, result.detail)
        ]
    if result.lost_in_window:
        return [
            Finding(
                Leg.R2,
                LegOutcome.INFO,
                CAUSE_LOST_IN_FLUSH_WINDOW,
                instance_id,
                f"records={result.lost_in_window}",
            )
        ]
    return []


# -- leg R1 ---------------------------------------------------------------------------------------

#: ``(station, rung_id, side, kind, reason, t)``: R1's bijection key (r8 section 3.10).
_R1Key = tuple[str, str, str, str, str, int]


def _expected_lines(
    boot: BootEvidence, scan: NodeLogScan, day: dt.date
) -> tuple[dict[_R1Key, list[int]], list[Finding]]:
    """The lines of ``day`` that need a record, by key, with each line's log time. Veto lines pass
    through the on-change filter (an unchanged repeat needs no record) and a veto line with no
    earlier Take of its key is ``veto_line_unanchored``."""
    on_change = OnChangeFilter()
    takes: dict[_Key, int] = {}
    expected: dict[_R1Key, list[int]] = {}
    findings: list[Finding] = []
    for line in scan.entry_lines:
        key: _Key = (line.station, line.climate_day.isoformat(), line.rung_id, line.side)
        if line.kind == KIND_TAKE:
            kind, reason, eval_ns = KIND_TAKE, _REASON_TAKE, line.now_ns
            takes[key] = line.now_ns
        else:
            reason = line.reason or ""
            kind = _follow_up_kind(reason)
            if is_guard_entry_veto(kind, reason):
                continue
            anchor = takes.get(key)
            if anchor is None and kind == _KIND_ENTRY_VETO and _day_of(line.now_ns) == day:
                findings.append(
                    Finding(
                        Leg.R1, LegOutcome.FAIL, CAUSE_VETO_UNANCHORED, boot.instance_id, reason
                    )
                )
            eval_ns = line.now_ns if anchor is None else anchor
        admitted = on_change.admit(key, kind, reason, eval_ns)
        if admitted and _day_of(line.now_ns) == day:
            r1_key = (line.station, line.rung_id, line.side, kind, reason, line.now_ns)
            expected.setdefault(r1_key, []).append(line.log_ts_ns)
    return expected, findings


def _record_time(kind: str, eval_ns: int, wall_ns: int) -> int:
    """``t`` on a record: ``eval_ns`` for a Take, ``wall_ns`` for a TrySubmit or EntryVeto (U9)."""
    return eval_ns if kind == KIND_TAKE else wall_ns


def _actual_records(boot: BootEvidence, day: dt.date) -> dict[_R1Key, int]:
    actual: Counter[_R1Key] = Counter()
    for record in boot.c1.decisions:
        if record.kind not in _ENTRY_RECORD_KINDS or is_guard_entry_veto(
            record.kind, record.reason
        ):
            continue
        when = _record_time(record.kind, record.eval_ns, record.wall_ns)
        if _day_of(when) == day:
            actual[
                (record.station, record.rung_id, record.side, record.kind, record.reason, when)
            ] += 1
    return dict(actual)


def _r1_boot(boot: BootEvidence, scan: NodeLogScan, day: dt.date) -> tuple[list[Finding], int]:
    if scan.entry_total > len(scan.entry_lines):
        return [Finding(Leg.R1, LegOutcome.ERROR, CAUSE_ENTRY_LINES_CAPPED, boot.instance_id)], 0
    expected, findings = _expected_lines(boot, scan, day)
    actual = _actual_records(boot, day)
    last_ts = boot.last_line_ts_ns if boot.last_line_ts_ns is not None else scan.last_line_ts_ns
    window_floor = None if last_ts is None else last_ts - FLUSH_WINDOW_S * _NS
    lost_in_window = 0
    for key, stamps in expected.items():
        short = len(stamps) - actual.get(key, 0)
        for stamp in sorted(stamps)[len(stamps) - max(short, 0) :]:
            if window_floor is not None and stamp >= window_floor:
                lost_in_window += 1
            else:
                findings.append(
                    Finding(
                        Leg.R1,
                        LegOutcome.FAIL,
                        CAUSE_CAPTURE_MISSING,
                        boot.instance_id,
                        _label(key),
                    )
                )
    for key, count in actual.items():
        extra = count - len(expected.get(key, ()))
        findings.extend(
            Finding(
                Leg.R1, LegOutcome.FAIL, CAUSE_CAPTURE_UNEXPLAINED, boot.instance_id, _label(key)
            )
            for _ in range(max(extra, 0))
        )
    findings.extend(_guard_findings(boot))
    return findings, lost_in_window


def _label(key: _R1Key) -> str:
    station, rung_id, side, kind, reason, when = key
    return f"{station}/{rung_id}/{side} {kind}:{reason}@{when}"


def _guard_findings(boot: BootEvidence) -> list[Finding]:
    """Guard ``EntryVeto`` records are matched one-to-one with ``CAPTURE_REFUSED`` lines (by
    reason). A record without a line always fails; a line without a record is tolerated only up to
    the boot's detector events (a refusal with no known Take writes a detector instead)."""
    records: Counter[str] = Counter(
        record.reason
        for record in boot.c1.decisions
        if is_guard_entry_veto(record.kind, record.reason)
    )
    lines: Counter[str] = Counter(
        refused.reason for refused in _only(boot.markers.capture_refused, CaptureRefusedLine)
    )
    findings = [
        Finding(Leg.R1, LegOutcome.FAIL, CAUSE_GUARD_VETO_UNMATCHED, boot.instance_id, reason)
        for reason, count in sorted(records.items())
        for _ in range(max(count - lines.get(reason, 0), 0))
    ]
    surplus = sum(max(lines[reason] - records.get(reason, 0), 0) for reason in lines)
    findings.extend(
        Finding(Leg.R1, LegOutcome.FAIL, CAUSE_CAPTURE_REFUSED_UNMATCHED, boot.instance_id, "")
        for _ in range(max(surplus - len(boot.c1.detector_events), 0))
    )
    return findings


def leg_r1(inp: AuditInputs) -> LegResult:
    """A bijection between Take/TrySubmit lines and records; guard vetoes matched to refusals."""
    findings: list[Finding] = []
    lost = 0
    for boot, scan in _scanned(inp):
        boot_findings, boot_lost = _r1_boot(boot, scan, inp.day)
        findings.extend(boot_findings)
        lost += boot_lost
    metrics: dict[str, MetricValue] = {"records_lost_in_flush_window": lost}
    if lost:
        findings.append(
            Finding(Leg.R1, LegOutcome.INFO, CAUSE_LOST_IN_FLUSH_WINDOW, "", f"lines={lost}")
        )
    return _rollup(Leg.R1, findings, metrics)


# -- leg R3 ---------------------------------------------------------------------------------------

#: ``(station, side, kind, reason)`` as the funnel counts them (a Take's reason is empty).
_FunnelKey = tuple[str, str, str, str]


def _funnel_rows(inp: AuditInputs, boot: BootEvidence, end_ns: int) -> list[FunnelRow]:
    rows = [row for row in inp.funnel if boot.started_ns <= row.ts_ns <= end_ns]
    return sorted(rows, key=lambda row: row.ts_ns)


def _funnel_counts(row: FunnelRow) -> Counter[_FunnelKey]:
    counts: Counter[_FunnelKey] = Counter()
    for item in row.counts:
        if item.kind in _FUNNEL_KINDS:
            counts[(item.station, item.side, item.kind, item.reason)] += item.count
    return counts


def _r3_boot(inp: AuditInputs, boot: BootEvidence, scan: NodeLogScan) -> list[Finding]:
    last_ts = boot.last_line_ts_ns if boot.last_line_ts_ns is not None else scan.last_line_ts_ns
    if last_ts is None:
        return []
    if scan.entry_total > len(scan.entry_lines):
        return [Finding(Leg.R3, LegOutcome.ERROR, CAUSE_ENTRY_LINES_CAPPED, boot.instance_id)]
    race_ns = _FUNNEL_RACE_S * _NS
    stamps = [line.log_ts_ns for line in scan.entry_lines]
    eligible = [
        row
        for row in _funnel_rows(inp, boot, last_ts + race_ns)
        if all(abs(stamp - row.ts_ns) > race_ns for stamp in stamps)
    ]
    if not eligible:
        return []
    flush = eligible[-1]
    log_counts: Counter[_FunnelKey] = Counter()
    for line in scan.entry_lines:
        if line.log_ts_ns <= flush.ts_ns:
            reason = "" if line.kind == KIND_TAKE else (line.reason or "")
            log_counts[(line.station, line.side, line.kind, reason)] += 1
    funnel = _funnel_counts(flush)
    return [
        Finding(
            Leg.R3,
            LegOutcome.FAIL,
            CAUSE_FUNNEL_MISMATCH,
            boot.instance_id,
            f"{'/'.join(key)} funnel={funnel.get(key, 0)} log={log_counts.get(key, 0)}",
        )
        for key in sorted(set(funnel) | set(log_counts))
        if funnel.get(key, 0) != log_counts.get(key, 0)
    ]


def leg_r3(inp: AuditInputs) -> LegResult:
    """Funnel counts against the log (Take and TrySubmit only)."""
    findings: list[Finding] = []
    for boot, scan in _scanned(inp):
        findings.extend(_r3_boot(inp, boot, scan))
    return _rollup(Leg.R3, findings, {})
