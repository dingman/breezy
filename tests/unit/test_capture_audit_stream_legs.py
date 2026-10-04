"""AUT-1 WP5 stage 2b, W2: the stream, watchdog, tape and NBP legs and the D13 positive control.

Covers ``capture_audit_stream_legs`` (R4, R5, R7, W, T, N, ``positive_control``). Names follow
plan r12 section 4 WP5 and r8 WP5 verbatim. The replay, R1-R3 and the marker sink are in
``test_capture_audit_recon_legs.py`` (split for the 800-line rule, the WP0-R10 precedent).
"""

from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.persistence.funcs import class_to_filename

from breezy.analysis.capture_audit_input_types import (
    FunnelRow,
    HeartbeatSummary,
    IngestLine,
    LogMarkers,
    NotifierProof,
    RecorderJournalEntry,
    ReplayResult,
    StallRecord,
)
from breezy.analysis.capture_audit_model import (
    PC_MIN_OVERLAP_S,
    STREAM_GAP_FAIL_S,
    AuditInputError,
    LegOutcome,
)
from breezy.analysis.capture_audit_stream_legs import (
    HEARTBEAT_TABLE as MODULE_HEARTBEAT_TABLE,
)
from breezy.analysis.capture_audit_stream_legs import (
    NBP_DEADLINE_S,
    NBP_MISSED_PROOF_UNIT,
    RECORDER_UNIT,
    leg_n,
    leg_r4,
    leg_r5,
    leg_r7,
    leg_t,
    leg_w,
    positive_control,
)
from breezy.analysis.capture_node_log import (
    FqVectorCompleteLine,
    NbpCycleMissedLine,
    NbpPublishedLine,
)
from breezy.persistence.autonomy.capture_epoch import EpochRecord
from breezy.persistence.autonomy.capture_reader import CaptureStream
from breezy.persistence.autonomy.capture_records import (
    CaptureHeartbeat,
    DecisionRecord,
    make_record,
)
from tests.support.capture_audit_fixtures import (
    DAY,
    INSTANCE_ID,
    INSTRUMENT_ID,
    NS,
    EmptyTape,
    make_boot,
    make_inputs,
    make_stream_summary,
)
from tests.support.capture_audit_recon_fixtures import (
    DAY_START_NS,
    T,
    analyse,
    boot_for,
    causes,
    failing,
    funnel_row,
    inputs_for,
    instance_line,
    log_ts,
    refuse_line,
    refuse_view,
)

HB_TABLE = class_to_filename(CaptureHeartbeat)
DECISION_TABLE = class_to_filename(DecisionRecord)


def test_the_heartbeat_table_literal_is_the_writers_table_name() -> None:
    assert MODULE_HEARTBEAT_TABLE == HB_TABLE


# ================================================================================================
# R4
# ================================================================================================


def writer_failure_boot(tmp_path: Path, text: str, offset: int = 0) -> Any:
    line = f"{log_ts(T + offset)} [ERROR] BREEZY-L001.W: {text}"
    return boot_for(analyse(tmp_path, [instance_line(T - NS), line]))


def test_marker_write_failure_still_fails_day(tmp_path: Path) -> None:
    boot = writer_failure_boot(tmp_path, "CAPTURE_PUBLISH_FAILED family=f type=DecisionRecord")
    assert failing(leg_r4(inputs_for(boot))) == ["writer_failure_marker"]


def test_failed_to_serialize_log_line_fails_r4(tmp_path: Path) -> None:
    boot = writer_failure_boot(tmp_path, "Failed to serialize cls=<c>")
    result = leg_r4(inputs_for(boot))
    assert failing(result) == ["writer_failure_marker"]
    assert "failed_to_serialize" in result.findings[0].detail


def test_cant_find_writer_marker_fails_r4(tmp_path: Path) -> None:
    boot = writer_failure_boot(tmp_path, "Can't find writer for cls <c>")
    assert failing(leg_r4(inputs_for(boot))) == ["writer_failure_marker"]


def test_a_failure_on_another_day_does_not_fail_this_day(tmp_path: Path) -> None:
    boot = writer_failure_boot(tmp_path, "Failed to serialize cls=<c>", offset=-2 * 86_400 * NS)
    assert leg_r4(inputs_for(boot)).outcome == LegOutcome.PASS


def test_no_failure_marker_passes(tmp_path: Path) -> None:
    boot = boot_for(analyse(tmp_path, [instance_line(T - NS), refuse_line(0)]))
    assert leg_r4(inputs_for(boot)).outcome == LegOutcome.PASS


def test_stream_torn_tail_after_boot_end_is_counted() -> None:
    boot = make_boot(summary=make_stream_summary(torn_tail_count=1), ended=True)
    result = leg_r4(make_inputs(boots=(boot,)))
    assert result.outcome == LegOutcome.INFO
    assert causes(result) == ["stream_torn_tail_counted"]
    assert result.metrics["stream_torn_tails"] == 1
    running = make_boot(summary=make_stream_summary(torn_tail_count=1), ended=False)
    assert leg_r4(make_inputs(boots=(running,))).outcome == LegOutcome.PASS


# ================================================================================================
# R5
# ================================================================================================


def beat(ts_s: int, seq: int, written: dict[str, int], *, final: bool = False) -> HeartbeatSummary:
    return HeartbeatSummary(T + ts_s * NS, seq, final, written)


def r5_boot(rows: dict[str, int], beats: tuple[HeartbeatSummary, ...], **over: Any) -> Any:
    summary = make_stream_summary(row_counts=rows, heartbeats=beats)
    return make_boot(summary=summary, **over)


def test_records_short_of_last_heartbeat_count_fail_stream_record_lost() -> None:
    boot = r5_boot(
        {DECISION_TABLE: 9, HB_TABLE: 3}, (beat(0, 3, {DECISION_TABLE: 10, HB_TABLE: 2}),)
    )
    assert failing(leg_r5(make_inputs(boots=(boot,)))) == ["stream_record_lost"]


def test_native_table_short_of_heartbeat_count_fails() -> None:
    written = {"order_initialized": 3, HB_TABLE: 2}
    boot = r5_boot({"order_initialized": 2, HB_TABLE: 3}, (beat(0, 3, written),))
    result = leg_r5(make_inputs(boots=(boot,)))
    assert failing(result) == ["stream_record_lost"]
    assert "order_initialized" in result.findings[0].detail


def test_final_heartbeat_requires_exact_equality_per_table() -> None:
    """Mutation: R5 equality off (a surplus passes). Equal passes; short and surplus both fail."""
    final = beat(0, 3, {DECISION_TABLE: 10, HB_TABLE: 2}, final=True)
    equal = r5_boot({DECISION_TABLE: 10, HB_TABLE: 3}, (final,))
    assert leg_r5(make_inputs(boots=(equal,))).outcome == LegOutcome.PASS
    surplus = r5_boot({DECISION_TABLE: 11, HB_TABLE: 3}, (final,))
    assert failing(leg_r5(make_inputs(boots=(surplus,)))) == ["stream_record_excess"]
    short = r5_boot({DECISION_TABLE: 9, HB_TABLE: 3}, (final,))
    assert failing(leg_r5(make_inputs(boots=(short,)))) == ["stream_record_lost"]


def test_a_crashed_boot_may_hold_more_rows_than_its_last_heartbeat_counted() -> None:
    crashed = r5_boot(
        {DECISION_TABLE: 14, HB_TABLE: 3}, (beat(0, 3, {DECISION_TABLE: 10, HB_TABLE: 2}),)
    )
    assert leg_r5(make_inputs(boots=(crashed,))).outcome == LegOutcome.PASS


def test_heartbeat_table_rows_equal_count_plus_one() -> None:
    """GL1: the snapshot is taken BEFORE the heartbeat's own write, so the heartbeat table holds
    its count plus the heartbeat that carries it."""
    final = beat(0, 5, {HB_TABLE: 4}, final=True)
    assert leg_r5(make_inputs(boots=(r5_boot({HB_TABLE: 5}, (final,)),))).outcome == (
        LegOutcome.PASS
    )
    assert failing(leg_r5(make_inputs(boots=(r5_boot({HB_TABLE: 4}, (final,)),)))) == [
        "stream_record_lost"
    ]


def test_the_first_heartbeat_alone_balances() -> None:
    first = beat(0, 1, {}, final=True)
    assert leg_r5(make_inputs(boots=(r5_boot({HB_TABLE: 1}, (first,)),))).outcome == (
        LegOutcome.PASS
    )


def test_tail_after_last_heartbeat_of_crashed_boot_is_lost_in_flush_window_counted(
    tmp_path: Path,
) -> None:
    lines = [
        instance_line(T - NS),
        refuse_line(0, "a"),
        refuse_line(10 * NS, "b"),
        refuse_line(20 * NS, "c"),
    ]
    analysis = analyse(tmp_path, lines)
    summary = make_stream_summary(
        row_counts={DECISION_TABLE: 1, HB_TABLE: 2},
        heartbeats=(beat(0, 2, {DECISION_TABLE: 1, HB_TABLE: 1}),),
    )
    boot = boot_for(analysis, [refuse_view(0, "a")], summary=summary)
    result = leg_r5(inputs_for(boot))
    assert result.outcome == LegOutcome.PASS
    assert result.metrics["records_lost_in_flush_window"] == 2


def test_nonzero_write_drops_fails_stream_write_dropped() -> None:
    """GM2: ``write_drops`` is in the boot's own heartbeat rows (the reduced summary omits it)."""
    row = make_record(
        CaptureHeartbeat, ts_event=T, ts_init=T, seq=3, final=True, write_drops=2, write_failures=0
    )
    stream = CaptureStream(INSTANCE_ID, "live", heartbeats=(row,))
    boot = r5_boot({HB_TABLE: 3}, (beat(0, 3, {HB_TABLE: 2}, final=True),), stream=lambda: stream)
    assert failing(leg_r5(make_inputs(boots=(boot,)))) == ["stream_write_dropped"]


def test_an_unreadable_stream_raises_stream_unreadable() -> None:
    def broken() -> CaptureStream:
        raise OSError("gone")

    boot = r5_boot({HB_TABLE: 3}, (beat(0, 3, {HB_TABLE: 2}, final=True),), stream=broken)
    with pytest.raises(AuditInputError) as error:
        leg_r5(make_inputs(boots=(boot,)))
    assert error.value.cause == "stream_unreadable"


# ================================================================================================
# R7
# ================================================================================================


def r7_boot(beats: list[int], *, final: bool = True, **over: Any) -> Any:
    hbs = tuple(
        beat(s, n + 1, {}, final=final and n == len(beats) - 1) for n, s in enumerate(beats)
    )
    fields: dict[str, Any] = {
        "started_ns": T + beats[0] * NS,
        "last_line_ts_ns": T + beats[-1] * NS,
    }
    fields.update(over)
    return make_boot(summary=make_stream_summary(heartbeats=hbs), **fields)


def test_heartbeat_gap_over_180s_fails_stream_gap() -> None:
    """Mutation: the threshold 181 instead of 180 passes a 181 s gap."""
    over = r7_boot([0, 60, 60 + STREAM_GAP_FAIL_S + 1])
    assert failing(leg_r7(make_inputs(boots=(over,)))) == ["stream_gap"]
    exact = r7_boot([0, 60, 60 + STREAM_GAP_FAIL_S])
    assert leg_r7(make_inputs(boots=(exact,))).outcome == LegOutcome.PASS


def test_a_boot_with_no_heartbeat_after_start_fails_the_leading_gap() -> None:
    boot = r7_boot([300], started_ns=T, final=True)
    assert failing(leg_r7(make_inputs(boots=(boot,)))) == ["stream_gap"]


def test_a_boot_without_a_final_heartbeat_fails_the_trailing_gap() -> None:
    crashed = r7_boot([0, 60], final=False, last_line_ts_ns=T + 400 * NS)
    assert failing(leg_r7(make_inputs(boots=(crashed,)))) == ["stream_gap"]
    clean = r7_boot([0, 60], final=True, last_line_ts_ns=T + 400 * NS)
    assert leg_r7(make_inputs(boots=(clean,))).outcome == LegOutcome.PASS


def test_a_gap_outside_the_audited_day_is_not_this_days_failure() -> None:
    early = [-3 * 86_400, -3 * 86_400 + 600]
    boot = r7_boot(early, started_ns=T + early[0] * NS)
    assert leg_r7(make_inputs(boots=(boot,))).outcome == LegOutcome.PASS


# ================================================================================================
# W
# ================================================================================================


def kill(invocation: str = "inv-9", ts_offset_s: int = 3600) -> RecorderJournalEntry:
    return RecorderJournalEntry(DAY_START_NS + ts_offset_s * NS, invocation, "watchdog", "killed")


def proof(invocation: str = "inv-9", *, delivered: bool = True) -> NotifierProof:
    return NotifierProof(RECORDER_UNIT, invocation, delivered, DAY.isoformat())


def stall(invocation: str = "inv-9") -> StallRecord:
    return StallRecord(invocation, DAY_START_NS + 3600 * NS, DAY.isoformat())


def w_inputs(**over: Any) -> Any:
    fields: dict[str, Any] = {
        "recorder_journal": (kill(),),
        "stall_records": (stall(),),
        "notifier_proofs": (proof(),),
    }
    fields.update(over)
    return make_inputs(**fields)


def test_a_fully_evidenced_watchdog_kill_passes_leg_w() -> None:
    result, gaps = leg_w(w_inputs())
    assert result.outcome == LegOutcome.PASS and gaps == ()


def test_watchdog_journal_entry_without_stall_record_fails_leg_w() -> None:
    result, gaps = leg_w(w_inputs(stall_records=()))
    assert failing(result) == ["watchdog_evidence_gap"]
    assert [(g.invocation_id, g.cause) for g in gaps] == [("inv-9", "stall_record_missing")]
    assert result.metrics["watchdog_kills_unproven"] == 1


def test_watchdog_journal_entry_without_delivered_notifier_marker_fails_leg_w() -> None:
    for proofs in ((), (proof(delivered=False),)):
        result, gaps = leg_w(w_inputs(notifier_proofs=proofs))
        assert failing(result) == ["watchdog_evidence_gap"]
        assert [g.cause for g in gaps] == ["notifier_marker_missing"]


def test_fallback_page_delivery_satisfies_leg_w() -> None:
    """The delivered record of the fallback page for the same ``(unit, InvocationID)`` is the same
    key as the notifier marker, so it satisfies the leg."""
    result, gaps = leg_w(w_inputs(notifier_proofs=(proof(delivered=False), proof())))
    assert result.outcome == LegOutcome.PASS and gaps == ()


def test_leg_w_reads_aut6_notifier_marker_by_invocation_id() -> None:
    other = NotifierProof(RECORDER_UNIT, "inv-other", True, DAY.isoformat())
    wrong_unit = NotifierProof("breezy-trade.service", "inv-9", True, DAY.isoformat())
    result, gaps = leg_w(w_inputs(notifier_proofs=(other, wrong_unit)))
    assert [g.cause for g in gaps] == ["notifier_marker_missing"]
    assert result.outcome == LegOutcome.FAIL


def test_a_kill_on_another_day_or_a_non_watchdog_result_is_not_judged() -> None:
    elsewhere = kill(ts_offset_s=-3600)
    ordinary = RecorderJournalEntry(DAY_START_NS + 7200 * NS, "inv-x", "success", "stopped")
    result, gaps = leg_w(w_inputs(recorder_journal=(elsewhere, ordinary), stall_records=()))
    assert result.outcome == LegOutcome.PASS and gaps == ()


def test_each_unproven_part_is_a_gap_and_a_repeated_entry_counts_once() -> None:
    result, gaps = leg_w(
        w_inputs(recorder_journal=(kill(), kill()), stall_records=(), notifier_proofs=())
    )
    assert sorted(g.cause for g in gaps) == ["notifier_marker_missing", "stall_record_missing"]
    assert result.metrics["watchdog_kills_unproven"] == 1


# ================================================================================================
# T
# ================================================================================================


class RowsTape(EmptyTape):
    """A tape with quote and depth rows for named instruments."""

    def __init__(self, quotes: Iterable[str] = (), depth: Iterable[str] = ()) -> None:
        self._quotes, self._depth = set(quotes), set(depth)

    def quote_rows(self, instrument_id: str, start_ns: int, end_ns: int) -> Iterable[Any]:
        return [{"ts_event": start_ns}] if instrument_id in self._quotes else []

    def depth_rows(self, instrument_id: str, start_ns: int, end_ns: int) -> Iterable[Any]:
        return [{"ts_event": start_ns}] if instrument_id in self._depth else []


GOOD_INGEST = (
    "extend_dedupe: chunks=3 filtered=3 unfiltered=0 "
    "by_type=custom_depth_truncation:3/0,quote_tick:3/0 flat_root=none"
)


def t_inputs(*lines: str, tape: Any = None, **over: Any) -> Any:
    fields: dict[str, Any] = {
        "ingest_lines": tuple(IngestLine(text) for text in (lines or (GOOD_INGEST,))),
        "ingest_exited_after_rotation": True,
        "tape": tape or RowsTape(quotes=[INSTRUMENT_ID], depth=[INSTRUMENT_ID]),
    }
    fields.update(over)
    return make_inputs(**fields)


def test_a_healthy_ingest_passes_leg_t() -> None:
    assert leg_t(t_inputs()).outcome == LegOutcome.PASS


def test_extend_dedupe_flat_root_fails_tape() -> None:
    line = GOOD_INGEST.replace("flat_root=none", "flat_root=custom_depth_truncation")
    assert failing(leg_t(t_inputs(line))) == ["tape_flat_root"]


def test_extend_dedupe_unfiltered_depth_truncation_fails_tape() -> None:
    line = GOOD_INGEST.replace("custom_depth_truncation:3/0", "custom_depth_truncation:2/1")
    assert failing(leg_t(t_inputs(line))) == ["tape_unfiltered"]


def test_filtered_depth_truncation_count_is_healthy() -> None:
    line = GOOD_INGEST.replace("custom_depth_truncation:3/0", "custom_depth_truncation:9/0")
    assert leg_t(t_inputs(line)).outcome == LegOutcome.PASS


def test_extend_dedupe_unparseable_line_fails_tape() -> None:
    assert failing(leg_t(t_inputs("extend_dedupe: chunks=x", GOOD_INGEST))) == [
        "tape_line_unparseable"
    ]


def test_extend_dedupe_legacy_line_without_flat_root_is_unparseable() -> None:
    legacy = "extend_dedupe: chunks=3 filtered=3 unfiltered=0 by_type=quote_tick:3/0"
    assert failing(leg_t(t_inputs(legacy, GOOD_INGEST))) == ["tape_line_unparseable"]


def test_chunks_zero_lines_alone_do_not_prove_ingest() -> None:
    zero = "extend_dedupe: chunks=0 filtered=0 unfiltered=0 by_type= flat_root=none"
    result = leg_t(t_inputs(zero, tape=RowsTape()))
    assert "tape_ingest_missing" in failing(result)
    assert leg_t(t_inputs(zero, tape=RowsTape(depth=[INSTRUMENT_ID]))).outcome == LegOutcome.PASS


def test_no_catalog_rows_for_day_is_tape_ingest_missing() -> None:
    assert "tape_ingest_missing" in failing(leg_t(t_inputs(tape=RowsTape())))


def test_no_ingest_line_after_rotation_is_tape_ingest_missing() -> None:
    assert "tape_ingest_missing" in failing(leg_t(t_inputs("unrelated journal line")))
    assert "tape_ingest_missing" in failing(leg_t(t_inputs(ingest_exited_after_rotation=False)))


def test_instrument_with_tape_quotes_and_no_depth_rows_is_tape_ingest_missing() -> None:
    tape = RowsTape(quotes=[INSTRUMENT_ID, "other.POLYMARKET_US"], depth=[INSTRUMENT_ID])
    boot = make_boot(subscribed=frozenset({INSTRUMENT_ID, "other.POLYMARKET_US"}))
    result = leg_t(t_inputs(tape=tape, boots=(boot,)))
    (finding,) = [f for f in result.findings if f.cause == "tape_ingest_missing"]
    assert finding.subject == "other.POLYMARKET_US"


def test_leg_t_audits_only_days_at_or_after_epoch_day() -> None:
    late_epoch = EpochRecord(
        "pm_us_crh_fq_v1", DAY_START_NS + 2 * 86_400 * NS, INSTANCE_ID, "0" * 40
    )
    line = GOOD_INGEST.replace("flat_root=none", "flat_root=x")
    before = leg_t(t_inputs(line, epoch=late_epoch))
    assert before.outcome == LegOutcome.INFO and failing(before) == []
    assert failing(leg_t(t_inputs(line))) == ["tape_flat_root"]


def test_leg_t_pre_epoch_legacy_line_is_info() -> None:
    legacy = "extend_dedupe: chunks=3 filtered=3 unfiltered=0 by_type=quote_tick:3/0"
    result = leg_t(t_inputs(legacy, GOOD_INGEST, epoch=None))
    assert result.outcome == LegOutcome.INFO
    assert causes(result, LegOutcome.INFO) == ["tape_line_unparseable"]


# ================================================================================================
# N
# ================================================================================================

CYCLE = DAY_START_NS + 8 * 3600 * NS
DEADLINE = CYCLE + NBP_DEADLINE_S * NS


def nbp_markers(*, published: bool = True, stations: Iterable[str] = ("KLAX",)) -> LogMarkers:
    return LogMarkers(
        nbp_published=(NbpPublishedLine(1, DEADLINE, CYCLE, 4, 28, "5.0"),) if published else (),
        fq_vector_complete=tuple(
            FqVectorCompleteLine(2, DEADLINE, station, CYCLE, DAY, "v5.0") for station in stations
        ),
    )


def n_inputs(markers: LogMarkers, *, started: int = DEADLINE - 3600 * NS, **over: Any) -> Any:
    boot = make_boot(started_ns=started, last_line_ts_ns=DEADLINE + 3600 * NS, markers=markers)
    fields: dict[str, Any] = {
        "boots": (boot,),
        "nbp_cycles_ns": (CYCLE,),
        "nbp_stations": ("KLAX",),
        "notifier_proofs": (),
    }
    fields.update(over)
    return make_inputs(**fields)


def missed_proof(cycle: int = CYCLE, *, delivered: bool = True) -> NotifierProof:
    return NotifierProof(NBP_MISSED_PROOF_UNIT, str(cycle), delivered, DAY.isoformat())


def test_a_published_cycle_with_every_station_vector_passes_leg_n() -> None:
    assert leg_n(n_inputs(nbp_markers())).outcome == LegOutcome.PASS


def test_nbp_cycle_census_missing_cycle_fails() -> None:
    result = leg_n(n_inputs(nbp_markers(published=False), notifier_proofs=(missed_proof(),)))
    assert failing(result) == ["nbp_cycle_missing"]


def test_nbp_cycle_with_missing_station_vector_fails() -> None:
    result = leg_n(n_inputs(nbp_markers(stations=())))
    assert failing(result) == ["nbp_vector_missing"]


def test_nbp_cycle_with_deadline_in_node_down_interval_not_expected() -> None:
    """The node came up after the cycle's deadline: nothing was expected of it."""
    after = DEADLINE + 4 * 3600 * NS
    boot = make_boot(started_ns=after, last_line_ts_ns=after + 3600 * NS)
    inp = make_inputs(boots=(boot,), nbp_cycles_ns=(CYCLE,), nbp_stations=("KLAX",))
    assert leg_n(inp).outcome == LegOutcome.PASS


def test_a_missed_cycle_without_a_delivery_record_fails_even_with_nothing_logged() -> None:
    """Stage 2a known limit: with an ``alert_offer`` wired the node logs nothing on a missed cycle,
    so the leg must read delivery evidence, not the log."""
    result = leg_n(n_inputs(nbp_markers(published=False)))
    assert failing(result) == ["nbp_cycle_missing", "nbp_missed_alert_undelivered"]
    undelivered = leg_n(
        n_inputs(nbp_markers(published=False), notifier_proofs=(missed_proof(delivered=False),))
    )
    assert "nbp_missed_alert_undelivered" in failing(undelivered)


def test_each_nbp_cycle_missed_log_line_needs_a_delivery_record() -> None:
    complete = nbp_markers()
    missed = NbpCycleMissedLine(3, DEADLINE, CYCLE, DEADLINE, "NBM_NBP", True)
    markers = LogMarkers(
        nbp_published=complete.nbp_published,
        fq_vector_complete=complete.fq_vector_complete,
        nbp_cycle_missed=(missed,),
    )
    assert failing(leg_n(n_inputs(markers))) == ["nbp_missed_alert_undelivered"]
    assert leg_n(n_inputs(markers, notifier_proofs=(missed_proof(),))).outcome == LegOutcome.PASS


# ================================================================================================
# D13 positive control
# ================================================================================================


def funnel_in_boot() -> tuple[FunnelRow, ...]:
    return (funnel_row(T + 900 * NS, 0, 0),)


def pc_inputs(boot: Any, **over: Any) -> Any:
    fields: dict[str, Any] = {
        "boots": (boot,),
        "tape": RowsTape(depth=[INSTRUMENT_ID]),
        "funnel": funnel_in_boot(),
    }
    fields.update(over)
    return make_inputs(**fields)


def pc_boot(**over: Any) -> Any:
    fields: dict[str, Any] = {
        "started_ns": T,
        "last_line_ts_ns": T + 4 * 3600 * NS,
        "overlap_s": 4 * 3600,
        "replay": make_boot().replay,
    }
    fields.update(over)
    return make_boot(**fields)


def test_a_boot_with_decisions_and_funnel_rows_passes_the_positive_control() -> None:
    assert positive_control(pc_inputs(pc_boot())).outcome == LegOutcome.PASS


def test_boot_with_tape_frames_and_no_shadow_decision_is_error_node_log_blind() -> None:
    blind = pc_boot(replay=ReplayResult())
    result = positive_control(pc_inputs(blind))
    assert result.outcome == LegOutcome.ERROR and causes(result) == ["node_log_blind"]


def test_boot_with_tape_frames_and_missing_funnel_file_is_error_funnel_missing() -> None:
    result = positive_control(pc_inputs(pc_boot(), funnel=()))
    assert result.outcome == LegOutcome.ERROR and causes(result) == ["funnel_missing"]
    outside = (funnel_row(T - 3600 * NS, 0, 0),)  # a row, but not inside the boot's interval
    assert causes(positive_control(pc_inputs(pc_boot(), funnel=outside))) == ["funnel_missing"]


def test_short_boot_exempt_from_positive_control() -> None:
    short = pc_boot(overlap_s=PC_MIN_OVERLAP_S - 1, replay=ReplayResult())
    assert positive_control(pc_inputs(short, funnel=())).outcome == LegOutcome.PASS
    exact = pc_boot(overlap_s=PC_MIN_OVERLAP_S, replay=ReplayResult())
    assert positive_control(pc_inputs(exact, funnel=())).outcome == LegOutcome.ERROR


def test_boot_without_tape_frames_exempt_from_positive_control() -> None:
    blind = pc_boot(replay=ReplayResult())
    result = positive_control(pc_inputs(blind, funnel=(), tape=RowsTape(quotes=[INSTRUMENT_ID])))
    assert result.outcome == LegOutcome.PASS
    unsubscribed = pc_boot(replay=ReplayResult(), subscribed=frozenset())
    assert positive_control(pc_inputs(unsubscribed, funnel=())).outcome == LegOutcome.PASS
