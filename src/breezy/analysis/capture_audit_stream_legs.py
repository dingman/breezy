"""AUT-1 WP5 stage 2b, W2: the stream, watchdog, tape and NBP legs (plan r12 section 3.11.3).

Pure functions over one ``AuditInputs`` value; no I/O. ``leg_w`` only COMPUTES the watchdog
evidence gaps (the daily re-send is stage 3, S2-R14). ``positive_control`` is the D13 node-log and
funnel check: ``node_log_blind`` / ``funnel_missing`` are ``ERROR`` causes, so it reports them as
``ERROR`` findings of leg PC. Signatures are pinned by ``tests/unit/test_capture_audit_stubs.py``.

Conventions this module fixes where the plan leaves them open (each pinned by a test):

* **R7** counts the leading gap (boot start to the first heartbeat) and, for a boot with no final
  heartbeat, the trailing gap (last heartbeat to the boot's last log line) as well as the gaps
  between consecutive heartbeats; only a gap that overlaps the audited UTC day counts.
* **R5** reads ``write_drops`` from the boot's own heartbeats through the lazy stream handle (the
  reduced ``HeartbeatSummary`` does not carry it).
* **leg N** reads DELIVERY evidence, never the log alone (stage 2a known limit: a wired offer logs
  nothing). A missed cycle's delivery proof is a ``NotifierProof`` with ``unit ==
  NBP_MISSED_PROOF_UNIT`` and ``invocation_id == str(cycle_ns)``, pending AUT-6's final format
  (design S2-R11).
"""

import datetime as dt
import re
from collections.abc import Iterable
from itertools import pairwise
from typing import Final

from breezy.analysis.capture_audit_input_types import AuditInputs, BootEvidence, HeartbeatSummary
from breezy.analysis.capture_audit_model import (
    PC_MIN_OVERLAP_S,
    STREAM_GAP_FAIL_S,
    AuditInputError,
    Finding,
    Leg,
    LegOutcome,
    LegResult,
    MetricValue,
    WatchdogGap,
)
from breezy.analysis.capture_audit_replay import _decision_loss, _only, _rollup
from breezy.analysis.capture_node_log import (
    FqVectorCompleteLine,
    NbpCycleMissedLine,
    NbpPublishedLine,
)

__all__ = [
    "HEARTBEAT_TABLE",
    "NBP_DEADLINE_S",
    "NBP_MISSED_PROOF_UNIT",
    "RECORDER_UNIT",
    "leg_n",
    "leg_r4",
    "leg_r5",
    "leg_r7",
    "leg_t",
    "leg_w",
    "positive_control",
]

_NS: Final[int] = 1_000_000_000
_NS_PER_DAY: Final[int] = 86_400 * _NS
RECORDER_UNIT: Final[str] = "breezy-quote-tape.service"
#: ``NBP_CYCLE_MISSED`` is offered once the cycle's publication deadline (cycle + 3 h) has passed.
NBP_DEADLINE_S: Final[int] = 3 * 3600
NBP_MISSED_PROOF_UNIT: Final[str] = "NBP_CYCLE_MISSED"
#: ``class_to_filename(CaptureHeartbeat)``: the table the writer counts and the reader keys by.
#: The analysis layer may not import Nautilus, so the tests pin this literal to that function.
HEARTBEAT_TABLE: Final[str] = "custom_capture_heartbeat"
_WATCHDOG_RESULT: Final[str] = "watchdog"
_EXTEND_PREFIX: Final[str] = "extend_dedupe:"
_EXTEND_RE: Final[re.Pattern[str]] = re.compile(
    r"^extend_dedupe: chunks=(?P<chunks>\d+) filtered=\d+ unfiltered=\d+ "
    r"by_type=(?P<by_type>\S*) flat_root=(?P<flat_root>\S+)$"
)
_TRUNCATION_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|,)custom_depth_truncation:(?P<filtered>\d+)/(?P<unfiltered>\d+)(?:,|$)"
)
_FLAT_ROOT_NONE: Final[str] = "none"


def _day_of(ns: int) -> dt.date:
    return dt.datetime.fromtimestamp(ns // _NS, dt.UTC).date()


def _day_bounds(day: dt.date) -> tuple[int, int]:
    start = int(dt.datetime(day.year, day.month, day.day, tzinfo=dt.UTC).timestamp()) * _NS
    return start, start + _NS_PER_DAY


def _boot_end_ns(boot: BootEvidence, now_ns: int) -> int:
    """When the boot stopped running: its last log line, else now for a boot still up."""
    if boot.last_line_ts_ns is not None:
        return boot.last_line_ts_ns
    return boot.started_ns if boot.ended else now_ns


# -- R4 -------------------------------------------------------------------------------------------


def leg_r4(inp: AuditInputs) -> LegResult:
    """Writer-failure markers in the node log."""
    findings: list[Finding] = []
    torn = 0
    for boot in inp.boots:
        scan = boot.scan
        if scan is not None and scan.writer_failure_total:
            complete = len(scan.writer_failures) == scan.writer_failure_total
            on_day = [
                failure
                for failure in scan.writer_failures
                if failure.log_ts_ns is None or _day_of(failure.log_ts_ns) == inp.day
            ]
            seen = on_day if complete else scan.writer_failures
            if seen or not complete:
                names = ",".join(sorted({failure.marker for failure in seen}))
                findings.append(
                    Finding(
                        Leg.R4,
                        LegOutcome.FAIL,
                        "writer_failure_marker",
                        boot.instance_id,
                        f"markers={names} total={scan.writer_failure_total}",
                    )
                )
        if boot.ended and boot.summary.torn_tail_count:
            torn += boot.summary.torn_tail_count
            findings.append(
                Finding(
                    Leg.R4,
                    LegOutcome.INFO,
                    "stream_torn_tail_counted",
                    boot.instance_id,
                    f"files={boot.summary.torn_tail_count}",
                )
            )
    metrics: dict[str, MetricValue] = {"stream_torn_tails": torn}
    return _rollup(Leg.R4, findings, metrics)


# -- R5 -------------------------------------------------------------------------------------------


def _last_heartbeat(boot: BootEvidence) -> HeartbeatSummary | None:
    beats = boot.summary.heartbeats
    return max(beats, key=lambda beat: (beat.ts_ns, beat.seq)) if beats else None


def _r5_tables(boot: BootEvidence, last: HeartbeatSummary) -> list[Finding]:
    """Rows present against the last heartbeat's snapshot, per table. The snapshot is taken BEFORE
    the heartbeat's own write, so the heartbeat table holds one more row than it counts (GL1)."""
    findings: list[Finding] = []
    counted = dict(last.written_by_type)
    counted.setdefault(HEARTBEAT_TABLE, 0)
    for table in sorted(set(counted) | set(boot.summary.row_counts)):
        expected = counted.get(table, 0) + (1 if table == HEARTBEAT_TABLE else 0)
        present = boot.summary.row_counts.get(table, 0)
        detail = f"{table} present={present} expected={expected}"
        if present < expected:
            findings.append(
                Finding(Leg.R5, LegOutcome.FAIL, "stream_record_lost", boot.instance_id, detail)
            )
        elif present > expected and last.final:
            findings.append(
                Finding(Leg.R5, LegOutcome.FAIL, "stream_record_excess", boot.instance_id, detail)
            )
    return findings


def _write_drops(boot: BootEvidence) -> int:
    """``write_drops`` of the boot's newest heartbeat, read through the lazy stream handle."""
    try:
        beats = boot.stream().heartbeats
    except Exception as exc:
        raise AuditInputError("stream_unreadable", type(exc).__name__) from exc
    return int(max(beats, key=lambda beat: (beat.ts_event, beat.seq)).write_drops) if beats else 0


def leg_r5(inp: AuditInputs) -> LegResult:
    """Counted stream loss per boot and table."""
    findings: list[Finding] = []
    lost = 0
    for boot in inp.boots:
        last = _last_heartbeat(boot)
        if last is None:
            continue
        findings.extend(_r5_tables(boot, last))
        drops = _write_drops(boot)
        if drops:
            findings.append(
                Finding(
                    Leg.R5,
                    LegOutcome.FAIL,
                    "stream_write_dropped",
                    boot.instance_id,
                    f"write_drops={drops}",
                )
            )
        if boot.scan is not None:
            lost += _decision_loss(boot, inp.day)
    metrics: dict[str, MetricValue] = {"records_lost_in_flush_window": lost}
    return _rollup(Leg.R5, findings, metrics)


# -- R7 -------------------------------------------------------------------------------------------


def _beat_gaps(boot: BootEvidence, now_ns: int) -> list[tuple[int, int]]:
    """``(start_ns, end_ns)`` of every stretch the boot ran with no heartbeat: before the first,
    between consecutive ones and, without a final heartbeat, after the last."""
    stamps = sorted(beat.ts_ns for beat in boot.summary.heartbeats)
    final = any(beat.final for beat in boot.summary.heartbeats)
    end = _boot_end_ns(boot, now_ns)
    points = [boot.started_ns, *stamps, *([] if final else [end])]
    return [(a, b) for a, b in pairwise(points) if b - a > 0]


def leg_r7(inp: AuditInputs) -> LegResult:
    """Stream continuity: no heartbeat gap above ``STREAM_GAP_FAIL_S``."""
    day_start, day_end = _day_bounds(inp.day)
    findings: list[Finding] = []
    longest = 0
    for boot in inp.boots:
        for start, end in _beat_gaps(boot, inp.now_ns):
            if end < day_start or start >= day_end:
                continue
            gap_s = (end - start) // _NS
            longest = max(longest, gap_s)
            if end - start > STREAM_GAP_FAIL_S * _NS:
                findings.append(
                    Finding(
                        Leg.R7,
                        LegOutcome.FAIL,
                        "stream_gap",
                        boot.instance_id,
                        f"gap_s={gap_s} start_ns={start}",
                    )
                )
    metrics: dict[str, MetricValue] = {"longest_heartbeat_gap_s": longest}
    return _rollup(Leg.R7, findings, metrics)


# -- W --------------------------------------------------------------------------------------------


def leg_w(inp: AuditInputs) -> tuple[LegResult, tuple[WatchdogGap, ...]]:
    """Watchdog evidence: every recorder watchdog kill has a stall record and a delivered page."""
    stalled = {record.invocation_id for record in inp.stall_records}
    delivered = {
        proof.invocation_id
        for proof in inp.notifier_proofs
        if proof.unit == RECORDER_UNIT and proof.delivered
    }
    gaps: list[WatchdogGap] = []
    seen: set[str] = set()
    for entry in sorted(inp.recorder_journal, key=lambda e: (e.ts_ns, e.invocation_id)):
        if entry.unit_result != _WATCHDOG_RESULT or _day_of(entry.ts_ns) != inp.day:
            continue
        if entry.invocation_id in seen:
            continue
        seen.add(entry.invocation_id)
        for present, cause in (
            (entry.invocation_id in stalled, "stall_record_missing"),
            (entry.invocation_id in delivered, "notifier_marker_missing"),
        ):
            if not present:
                gaps.append(WatchdogGap(RECORDER_UNIT, entry.invocation_id, entry.ts_ns, cause))
    findings = [
        Finding(Leg.W, LegOutcome.FAIL, "watchdog_evidence_gap", gap.invocation_id, gap.cause)
        for gap in gaps
    ]
    metrics: dict[str, MetricValue] = {
        "watchdog_kills_unproven": len({gap.invocation_id for gap in gaps}),
    }
    return _rollup(Leg.W, findings, metrics), tuple(gaps)


# -- T --------------------------------------------------------------------------------------------


def _has_rows(rows: Iterable[object]) -> bool:
    return next(iter(rows), None) is not None


def _probed_instruments(inp: AuditInputs) -> frozenset[str]:
    """The instruments the audit can name without enumerating the catalog: every boot's
    subscriptions and every exec fill."""
    subscribed = {iid for boot in inp.boots for iid in boot.subscribed}
    return frozenset(subscribed | {fill.instrument_id for fill in inp.exec.fills})


def _ingest_line_findings(lines: list[str], severity: LegOutcome) -> tuple[list[Finding], bool]:
    """The strict-grammar findings of the ``extend_dedupe:`` lines, and whether any proves work
    (``chunks > 0``; a ``chunks=0`` line is valid but proves nothing alone)."""
    findings: list[Finding] = []
    proven = False
    for text in lines:
        match = _EXTEND_RE.match(text)
        if match is None:
            findings.append(Finding(Leg.T, severity, "tape_line_unparseable", "", text[:120]))
            continue
        proven = proven or int(match["chunks"]) > 0
        if match["flat_root"] != _FLAT_ROOT_NONE:
            findings.append(Finding(Leg.T, severity, "tape_flat_root", "", match["flat_root"]))
        truncation = _TRUNCATION_RE.search(match["by_type"])
        if truncation is not None and int(truncation["unfiltered"]) > 0:
            findings.append(Finding(Leg.T, severity, "tape_unfiltered", "", match["by_type"][:120]))
    return findings, proven


def _catalog_findings(inp: AuditInputs, severity: LegOutcome) -> tuple[list[Finding], bool]:
    """Positive control against the catalog: an instrument with quote rows and no Depth10 rows is
    ``tape_ingest_missing``, and so is a day with no catalog rows at all."""
    start, end = _day_bounds(inp.day)
    instruments = sorted(_probed_instruments(inp))
    findings: list[Finding] = []
    any_rows = any_depth = False
    for instrument in instruments:
        quotes = _has_rows(inp.tape.quote_rows(instrument, start, end))
        depth = _has_rows(inp.tape.depth_rows(instrument, start, end))
        any_rows = any_rows or quotes or depth
        any_depth = any_depth or depth
        if quotes and not depth:
            findings.append(
                Finding(Leg.T, severity, "tape_ingest_missing", instrument, "quotes without depth")
            )
    if instruments and not any_rows:
        findings.append(
            Finding(Leg.T, severity, "tape_ingest_missing", "", "no catalog rows for the day")
        )
    return findings, any_depth


def leg_t(inp: AuditInputs) -> LegResult:
    """r8's tape-ingest leg."""
    epoch = inp.epoch
    info_mode = epoch is None or inp.day < _day_of(epoch.epoch_start_ns)
    severity = LegOutcome.INFO if info_mode else LegOutcome.FAIL
    lines = [line.text for line in inp.ingest_lines if line.text.startswith(_EXTEND_PREFIX)]
    findings, proven_by_line = _ingest_line_findings(lines, severity)
    catalog, proven_by_catalog = _catalog_findings(inp, severity)
    findings.extend(catalog)
    ran = inp.ingest_exited_after_rotation and any(_EXTEND_RE.match(text) for text in lines)
    if not ran:
        findings.append(
            Finding(Leg.T, severity, "tape_ingest_missing", "", "no ingest summary after rotation")
        )
    elif not (proven_by_line or proven_by_catalog):
        findings.append(
            Finding(Leg.T, severity, "tape_ingest_missing", "", "chunks=0 lines prove nothing")
        )
    return _rollup(Leg.T, findings, {})


# -- N --------------------------------------------------------------------------------------------


def _up_intervals(inp: AuditInputs) -> list[tuple[int, int]]:
    return [(boot.started_ns, _boot_end_ns(boot, inp.now_ns)) for boot in inp.boots]


def leg_n(inp: AuditInputs) -> LegResult:
    """r8's NBP census plus a delivery record for each ``NBP_CYCLE_MISSED`` offer."""
    published = {
        line.cycle_ns
        for boot in inp.boots
        for line in _only(boot.markers.nbp_published, NbpPublishedLine)
    }
    vectors = {
        (line.station, line.cycle_ns)
        for boot in inp.boots
        for line in _only(boot.markers.fq_vector_complete, FqVectorCompleteLine)
    }
    logged_missed = {
        line.cycle_ns
        for boot in inp.boots
        for line in _only(boot.markers.nbp_cycle_missed, NbpCycleMissedLine)
    }
    delivered = {
        proof.invocation_id
        for proof in inp.notifier_proofs
        if proof.unit == NBP_MISSED_PROOF_UNIT and proof.delivered
    }
    findings: list[Finding] = []
    up = _up_intervals(inp)
    needs_delivery = set(logged_missed)
    for cycle in sorted(inp.nbp_cycles_ns):
        deadline = cycle + NBP_DEADLINE_S * _NS
        if not any(start <= deadline <= end for start, end in up):
            continue  # the node was down at the deadline: nothing was expected of it
        if cycle not in published:
            findings.append(Finding(Leg.N, LegOutcome.FAIL, "nbp_cycle_missing", str(cycle)))
            needs_delivery.add(cycle)
        findings.extend(
            Finding(Leg.N, LegOutcome.FAIL, "nbp_vector_missing", str(cycle), station)
            for station in sorted(inp.nbp_stations)
            if (station, cycle) not in vectors
        )
    findings.extend(
        Finding(Leg.N, LegOutcome.FAIL, "nbp_missed_alert_undelivered", str(cycle))
        for cycle in sorted(needs_delivery)
        if str(cycle) not in delivered
    )
    return _rollup(Leg.N, findings, {})


# -- positive control (D13) -----------------------------------------------------------------------


def _overlap_window(boot: BootEvidence, day: dt.date, now_ns: int) -> tuple[int, int]:
    day_start, day_end = _day_bounds(day)
    return max(boot.started_ns, day_start), min(_boot_end_ns(boot, now_ns), day_end)


def _boot_sees_tape(inp: AuditInputs, boot: BootEvidence, start: int, end: int) -> bool:
    """The node-independent trigger: the catalog holds Depth10 rows for an instrument the boot
    subscribed during its overlap."""
    return any(
        _has_rows(inp.tape.depth_rows(instrument, start, end))
        for instrument in sorted(boot.subscribed)
    )


def positive_control(inp: AuditInputs) -> LegResult:
    """D13: boots overlapping the day by ``PC_MIN_OVERLAP_S`` hold decisions and funnel rows."""
    findings: list[Finding] = []
    for boot in inp.boots:
        if boot.overlap_s < PC_MIN_OVERLAP_S:
            continue
        start, end = _overlap_window(boot, inp.day, inp.now_ns)
        if not _boot_sees_tape(inp, boot, start, end):
            continue
        if boot.replay.evaluations < 1:
            findings.append(Finding(Leg.PC, LegOutcome.ERROR, "node_log_blind", boot.instance_id))
        if not any(boot.started_ns <= row.ts_ns <= end for row in inp.funnel):
            findings.append(Finding(Leg.PC, LegOutcome.ERROR, "funnel_missing", boot.instance_id))
    return _rollup(Leg.PC, findings, {})
