"""AUT-1 WP5 stage 2b, W2: the reconciliation legs, the online R2 replay and the marker sink.

Covers ``capture_audit_replay`` (``BootReplay``, legs R1, R2, R3), ``capture_audit_log_markers``
(``MarkerParser``) and ``capture_audit_stream_legs`` (R4, R5, R7, W, T, N and the D13 positive
control). Test names follow plan r12 section 4 WP5 and r8 WP5 verbatim; a name the design retires is
listed in the stage-2b W2 return. Each test that kills a mutation says which in its docstring.

The ORACLE test drives the real ``FqCaptureAdapter`` (real ``OnChangeFilter``) and the real
``EvalSeqCounter`` on generated sequences and requires ``BootReplay`` to reproduce the adapter's
admitted records and their ``eval_seq`` exactly (design S2-R4).
"""

import datetime as dt
from collections.abc import Iterable, Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from nautilus_trader.persistence.funcs import class_to_filename

from breezy.analysis import capture_audit_log_markers as markers_module
from breezy.analysis.capture_audit_input_types import ReplayResult
from breezy.analysis.capture_audit_log_markers import MarkerParser
from breezy.analysis.capture_audit_model import (
    FLUSH_WINDOW_S,
    LegOutcome,
)
from breezy.analysis.capture_audit_replay import BootDayReplay, BootReplay, leg_r1, leg_r2, leg_r3
from breezy.analysis.capture_node_log import (
    CaptureEpochStartLine,
    NodeLogSinkFailed,
    iter_node_log,
    scan_node_log,
)
from breezy.persistence.autonomy.capture_ids import EVAL_SEQ_REORDER_BASE, EvalSeqCounter
from breezy.persistence.autonomy.capture_records import (
    CaptureHeartbeat,
    DecisionRecord,
)
from breezy.strategy.forecast_quantile_ladder.capture_adapter import REASON_TAKE
from breezy.strategy.forecast_quantile_ladder.decision import NotDPlus1, NotExecutable, Refuse
from tests.support.capture_audit_fixtures import (
    DAY,
    INSTANCE_ID,
    NS,
)
from tests.support.capture_audit_recon_fixtures import (
    DAY_END_NS,
    INSTANCE_B,
    MS,
    T,
    analyse,
    boot_for,
    causes,
    decision_text,
    dv,
    failing,
    funnel_row,
    inputs_for,
    instance_line,
    log_ts,
    refuse_line,
    refuse_view,
    refused_text,
    run_scenario,
    take_for,
    try_submit_text,
    views_of,
)
from tests.support.capture_node_log_fixtures import (
    CONSTRUCTED_EPOCH_START,
    PINNED_NBP_CYCLE_MISSED,
    REAL_FQ_VECTOR_COMPLETE,
    REAL_NBP_PUBLISHED,
    REAL_ORDER_DENIED,
    REAL_ORDER_SUBMITTED,
    write_log,
)

HB_TABLE = class_to_filename(CaptureHeartbeat)
DECISION_TABLE = class_to_filename(DecisionRecord)


# ================================================================================================
# BootReplay: the online R2 reducer (S2-R4, S2-R5)
# ================================================================================================


def replay_of(tmp_path: Path, *lines: str) -> Mapping[tuple[str, dt.date], Any]:
    return analyse(tmp_path, [instance_line(T - NS), *lines]).replay


def test_r2_replay_keeps_quote_and_depth_twins_and_matches_node_counter(tmp_path: Path) -> None:
    """Mutation: dedupe enabled. Two byte-identical Take lines (a quote and a depth evaluation of
    one frame) are two evaluations: both admitted, eval_seq 0 then 1, as the node's counter."""
    twin = decision_text(T + 5 * MS, take_for(), now_ns=T)
    result = replay_of(tmp_path, twin, twin)[(INSTANCE_ID, DAY)]
    node = EvalSeqCounter()
    expected = [node.next(take_for().instrument_id, T), node.next(take_for().instrument_id, T)]
    assert expected == [0, 1]
    assert (result.evaluations, result.admitted_total) == (2, 2)
    assert result.eval_seq_final == expected[-1]
    assert result.duplicate_lines == 1  # counted, never dropped


@pytest.mark.parametrize("seed", range(12))
def test_oracle_replay_equals_the_real_fq_capture_adapter(tmp_path: Path, seed: int) -> None:
    """The ORACLE (S2-R4). The real adapter and counter run on a generated sequence (quote and
    depth twins, Takes followed by TrySubmit, EntryVeto and guard refusals); the log lines the node
    would have written are replayed. Admitted set and ``eval_seq`` must be identical (R2 compares a
    hash chain over ``(key, kind, reason, eval_ns, eval_seq)``). Kills: dedupe, TrySubmit
    advancing the counter, the guard exclusion removed, no per-boot reset, a changed follow-up
    mapping."""
    scenario = run_scenario(seed)
    analysis = analyse(tmp_path, scenario.lines)
    replay = analysis.replay[(INSTANCE_ID, DAY)]
    published = [r for r in scenario.records if r.kind in {"Take", "Refuse", "NotExecutable"}]
    assert published, "the scenario must publish decision records"
    assert replay.evaluations == len(scenario.expected_seqs)
    assert max(scenario.expected_seqs) >= 1  # twins were generated
    assert replay.duplicate_lines > 0
    boot = boot_for(analysis, views_of(scenario.records))
    result = leg_r2(inputs_for(boot))
    assert failing(result) == [], result.findings
    assert leg_r1(inputs_for(boot)).outcome in {LegOutcome.PASS, LegOutcome.INFO}


def test_oracle_exercises_guard_refusals_and_suppressed_repeats() -> None:
    kinds = {r.kind for seed in range(12) for r in run_scenario(seed).records}
    reasons = {r.reason for seed in range(12) for r in run_scenario(seed).records}
    assert {"Take", "TrySubmit", "EntryVeto", "Refuse"} <= kinds
    assert "capture_gap" in reasons


def test_trysubmit_never_advances_the_counter(tmp_path: Path) -> None:
    """Mutation: TrySubmit advancing the counter, under the Take's ``ts_event`` (the twin would be
    seq 2) or under its own clock (a later frame would look non-monotone). Take (seq 0), its
    TrySubmit, the twin of the same frame (seq 1), then a frame between the Take and the clock."""
    lines = (
        decision_text(T + 5 * MS, take_for(), now_ns=T),
        try_submit_text(T + 9 * MS, "submitted"),
        refuse_line(0, "already_latched"),
    )
    twin = replay_of(tmp_path, *lines)[(INSTANCE_ID, DAY)]
    assert twin.evaluations == 2
    assert twin.eval_seq_final == 1
    between = replay_of(tmp_path, *lines, refuse_line(5 * MS, "below_margin"))
    assert between[(INSTANCE_ID, DAY)].eval_seq_final == 0  # a fresh ts_event, not a reorder


def test_trysubmit_and_veto_lines_enter_the_filter_under_the_takes_eval_ns(tmp_path: Path) -> None:
    lines = (
        decision_text(T + 5 * MS, take_for(), now_ns=T),
        try_submit_text(T + 9 * MS, "submitted"),
        try_submit_text(T + 12 * MS, "feed_stale"),
        try_submit_text(T + 15 * MS, "feed_stale"),  # the same veto again: suppressed
    )
    result = replay_of(tmp_path, *lines)[(INSTANCE_ID, DAY)]
    assert dict(result.admitted_by_kind) == {"Take": 1, "TrySubmit": 1, "EntryVeto": 1}
    assert result.evaluations == 1


def test_a_guard_entry_veto_is_excluded_and_never_touches_the_filter(tmp_path: Path) -> None:
    """Mutation: the guard exclusion removed. A ``capture_gap`` follow-up is the guard's own
    refusal: counted as excluded, not admitted, and a later ordinary veto still changes state."""
    lines = (
        decision_text(T + 5 * MS, take_for(), now_ns=T),
        try_submit_text(T + 9 * MS, "capture_gap"),
        try_submit_text(T + 12 * MS, "feed_stale"),
    )
    result = replay_of(tmp_path, *lines)[(INSTANCE_ID, DAY)]
    assert result.guard_vetoes_excluded == 1
    assert dict(result.admitted_by_kind) == {"Take": 1, "EntryVeto": 1}


def test_each_boot_gets_a_fresh_filter_and_counter(tmp_path: Path) -> None:
    """Mutation: no per-boot reset. The same refusal in two boots is admitted in BOTH, and each
    boot-day reports only its own evaluations."""
    lines = [
        instance_line(T - NS, INSTANCE_ID),
        refuse_line(0),
        instance_line(T + 60 * NS, INSTANCE_B),
        refuse_line(61 * NS),
    ]
    results = analyse(tmp_path, lines).replay
    for instance_id in (INSTANCE_ID, INSTANCE_B):
        result = results[(instance_id, DAY)]
        assert (result.evaluations, result.admitted_total, result.eval_seq_final) == (1, 1, 0)


def test_r2_replay_spans_utc_rollover_within_boot(tmp_path: Path) -> None:
    """State carries across midnight (a refusal repeated after it stays suppressed) while the
    results are partitioned by the UTC day of each line."""
    before = DAY_END_NS - 2 * NS
    after = DAY_END_NS + 2 * NS
    lines = [
        instance_line(before - NS),
        decision_text(before, Refuse(reason="below_margin"), now_ns=before),
        decision_text(after, Refuse(reason="below_margin"), now_ns=after),
    ]
    results = analyse(tmp_path, lines).replay
    next_day = DAY + dt.timedelta(days=1)
    assert results[(INSTANCE_ID, DAY)].admitted_total == 1
    assert results[(INSTANCE_ID, next_day)].admitted_total == 0
    assert results[(INSTANCE_ID, next_day)].evaluations == 1


def test_r2_recomputes_eval_seq_per_key_and_now_ns(tmp_path: Path) -> None:
    """Refuse a, then a twin at the same ``now_ns`` (b, seq 1), then b again a second later
    (suppressed, seq 0 for the new ts): the stream holds seqs 0 and 1 and R2 passes; a stream that
    carries 0 for the twin fails."""
    lines = [instance_line(T - NS), refuse_line(0, "a"), refuse_line(0, "b"), refuse_line(NS, "b")]
    analysis = analyse(tmp_path, lines)
    good = [refuse_view(0, "a", 0), refuse_view(0, "b", 1)]
    bad = [refuse_view(0, "a", 0), refuse_view(0, "b", 0)]
    assert failing(leg_r2(inputs_for(boot_for(analysis, good)))) == []
    assert failing(leg_r2(inputs_for(boot_for(analysis, bad)))) == ["r2_sequence_mismatch"]


def test_r2_replays_reorder_ordinal_range_and_four_entry_window_identically(
    tmp_path: Path,
) -> None:
    """Five distinct ``ts_event`` (the fifth evicts the oldest) and then a late frame older than
    every retained entry: the node counter and R2 give identical ordinals, one of them in the
    disjoint reorder range."""
    iid = take_for().instrument_id
    stamps = [0, 1, 2, 3, 4, 5, 1]  # seconds after T; the last is the late frame
    node = EvalSeqCounter()
    seqs = [node.next(iid, T + s * NS) for s in stamps]
    assert seqs[-1] >= EVAL_SEQ_REORDER_BASE
    lines = [instance_line(T - NS)]
    views = []
    for n, (stamp, seq) in enumerate(zip(stamps, seqs, strict=True)):
        lines.append(refuse_line(stamp * NS, f"r{n}", instrument_id=iid))
        views.append(refuse_view(stamp * NS, f"r{n}", seq))
    analysis = analyse(tmp_path, lines)
    assert analysis.replay[(INSTANCE_ID, DAY)].eval_seq_final == seqs[-1]
    assert failing(leg_r2(inputs_for(boot_for(analysis, views)))) == []


def test_replay_state_is_bounded_by_climate_day(tmp_path: Path) -> None:
    """The Take memory and the on-change filter evict old climate days: a long boot holds a few
    keys, not one per key ever seen."""
    replay = BootReplay()
    lines = [instance_line(T - NS)]
    for n in range(10):
        stamp = T + n * 86_400 * NS
        day = dt.datetime.fromtimestamp(stamp // NS, dt.UTC).date() + dt.timedelta(days=1)
        lines.append(decision_text(stamp, take_for(climate_day=day), now_ns=stamp, climate_day=day))
    for event in iter_node_log(write_log(tmp_path / "n.log", *lines)):
        replay.feed(event)
    state = replay._boots[INSTANCE_ID]
    assert len(state.takes) <= 3 and len(state.on_change) <= 3


def test_a_follow_up_with_no_preceding_take_is_a_counted_inconsistency(tmp_path: Path) -> None:
    result = replay_of(tmp_path, try_submit_text(T, "feed_stale"))[(INSTANCE_ID, DAY)]
    assert result.mismatches == 1 and "replay_unanchored_follow_up" in result.mismatch_samples[0]
    boot = boot_for(analyse(tmp_path, [instance_line(T - NS), try_submit_text(T, "feed_stale")]))
    assert failing(leg_r2(inputs_for(boot))) == ["replay_unanchored_follow_up"]


def test_the_take_reason_constant_matches_the_adapter() -> None:
    from breezy.analysis import capture_audit_replay as module

    assert module._REASON_TAKE == REASON_TAKE


def test_notexecutable_and_notdplus1_lines_are_replayed_as_evaluations(tmp_path: Path) -> None:
    lines = (
        decision_text(T, NotExecutable(), now_ns=T),
        decision_text(T + 2 * NS, NotDPlus1(), now_ns=T + 2 * NS),
    )
    result = replay_of(tmp_path, *lines)[(INSTANCE_ID, DAY)]
    assert (result.evaluations, result.admitted_total) == (2, 2)


# ================================================================================================
# leg R2 against the stream
# ================================================================================================


def test_r2_replay_sequence_equals_capture_sequence(tmp_path: Path) -> None:
    scenario = run_scenario(3)
    boot = boot_for(analyse(tmp_path, scenario.lines), views_of(scenario.records))
    result = leg_r2(inputs_for(boot))
    assert failing(result) == []
    assert causes(result) == ["duplicate_decision_lines"]  # INFO only


def test_duplicate_decision_lines_counted_info_not_fail(tmp_path: Path) -> None:
    twin = refuse_line(0)
    analysis = analyse(tmp_path, [instance_line(T - NS), twin, twin])
    result = leg_r2(inputs_for(boot_for(analysis, [refuse_view(0)])))
    assert result.outcome == LegOutcome.INFO
    assert causes(result, LegOutcome.INFO) == ["duplicate_decision_lines"]
    assert result.metrics["duplicate_decision_lines"] == 1


def test_r2_deleted_refusal_record_fails(tmp_path: Path) -> None:
    scenario = run_scenario(5)
    views = views_of(scenario.records)
    victim = next(i for i, v in enumerate(views[:-4]) if v.kind == "Refuse")
    del views[victim]
    boot = boot_for(analyse(tmp_path, scenario.lines), views)
    assert failing(leg_r2(inputs_for(boot))) != []


def test_r2_reordered_refusal_records_fail(tmp_path: Path) -> None:
    lines = [instance_line(T - NS), refuse_line(0, "a"), refuse_line(NS, "b")]
    analysis = analyse(tmp_path, lines)
    swapped = [refuse_view(NS, "b"), refuse_view(0, "a")]
    assert failing(leg_r2(inputs_for(boot_for(analysis, swapped)))) == ["r2_sequence_mismatch"]


def test_an_extra_record_the_replay_does_not_explain_fails(tmp_path: Path) -> None:
    lines = [instance_line(T - NS), refuse_line(0, "a")]
    views = [refuse_view(0, "a"), refuse_view(NS, "b")]
    result = leg_r2(inputs_for(boot_for(analyse(tmp_path, lines), views)))
    assert failing(result) == ["r2_unexplained_records"]


def test_missing_record_older_than_61s_before_last_log_line_is_stream_record_lost(
    tmp_path: Path,
) -> None:
    """EL1: the record of a line older than the flush window is lost, never tolerated."""
    old = (FLUSH_WINDOW_S + 60) * NS
    lines = [instance_line(T - NS), refuse_line(0, "a"), refuse_line(old, "b")]
    analysis = analyse(tmp_path, lines)
    result = leg_r2(inputs_for(boot_for(analysis, [])))
    assert failing(result) == ["stream_record_lost"]


def test_tail_inside_the_flush_window_is_counted_not_failed(tmp_path: Path) -> None:
    old = (FLUSH_WINDOW_S + 60) * NS
    lines = [
        instance_line(T - NS),
        refuse_line(0, "a"),
        refuse_line(old, "b"),
        refuse_line(old + 10 * NS, "c"),
    ]
    analysis = analyse(tmp_path, lines)
    present = [refuse_view(0, "a"), refuse_view(old, "b")]  # "c" never flushed
    result = leg_r2(inputs_for(boot_for(analysis, present)))
    assert failing(result) == []
    assert result.metrics["records_lost_in_flush_window"] == 1
    assert "lost_in_flush_window" in causes(result, LegOutcome.INFO)


def test_a_plain_replay_result_falls_back_to_a_count_comparison(tmp_path: Path) -> None:
    analysis = analyse(tmp_path, [instance_line(T - NS), refuse_line(0)])
    plain = ReplayResult(admitted_total=1)
    boot = boot_for(analysis, [refuse_view(0)], replay=plain)
    assert failing(leg_r2(inputs_for(boot))) == []
    short = boot_for(analysis, [], replay=plain)
    assert failing(leg_r2(inputs_for(short))) == ["stream_record_lost"]


def test_the_replay_carries_a_chain_and_a_bounded_tail(tmp_path: Path) -> None:
    lines = [instance_line(T - NS)]
    lines += [refuse_line(n * 10 * NS, f"r{n}") for n in range(30)]
    result = analyse(tmp_path, lines).replay[(INSTANCE_ID, DAY)]
    assert isinstance(result, BootDayReplay)
    assert result.admitted_total == 30
    assert result.base_count > 0 and len(result.tail) == 30 - result.base_count
    assert len(result.tail) <= FLUSH_WINDOW_S // 10 + 2


# ================================================================================================
# leg R1
# ================================================================================================


def take_pair(offset_ns: int = 0) -> tuple[list[str], list[Any]]:
    """A Take and its submitted TrySubmit: lines and the records the node would write."""
    take_ns, sub_ns = T + offset_ns, T + offset_ns + 9 * MS
    lines = [
        decision_text(take_ns + 5 * MS, take_for(), now_ns=take_ns),
        try_submit_text(sub_ns, "submitted"),
    ]
    views = [
        dv("Take", "take", eval_ns=take_ns, wall_ns=take_ns + 5 * MS),
        dv("TrySubmit", "submitted", eval_ns=take_ns, wall_ns=sub_ns),
    ]
    return lines, views


def r1_inputs(tmp_path: Path, lines: Iterable[str], views: Iterable[Any], **over: Any) -> Any:
    tail = refuse_line(300 * NS, "later")  # a later line: nothing is inside the flush window
    analysis = analyse(tmp_path, [instance_line(T - NS), *lines, tail])
    return inputs_for(boot_for(analysis, views, **over))


def test_r1_bijection_passes_on_a_take_and_its_trysubmit(tmp_path: Path) -> None:
    lines, views = take_pair()
    assert leg_r1(r1_inputs(tmp_path, lines, views)).outcome == LegOutcome.PASS


def test_node_log_take_line_without_capture_record_fails(tmp_path: Path) -> None:
    lines, views = take_pair()
    result = leg_r1(r1_inputs(tmp_path, lines, views[1:]))
    assert failing(result) == ["capture_missing"]


def test_capture_record_without_node_log_line_fails(tmp_path: Path) -> None:
    lines, views = take_pair()
    result = leg_r1(r1_inputs(tmp_path, lines[1:], views))
    assert failing(result) == ["capture_unexplained"]


def test_eval_ns_is_handler_ts_event_and_trysubmit_wall_ns_matches_line_now_ns(
    tmp_path: Path,
) -> None:
    """A Take line's ``now_ns`` is the handler's ``ts_event`` (the record's ``eval_ns``); a
    TrySubmit line's ``now_ns`` is the clock (the record's ``wall_ns``). Swapped times fail."""
    lines, views = take_pair()
    swapped = [
        dv("Take", "take", eval_ns=views[0].wall_ns, wall_ns=views[0].eval_ns),
        views[1],
    ]
    assert failing(leg_r1(r1_inputs(tmp_path, lines, swapped))) != []


def test_r1_matches_trysubmit_on_wall_ns_and_take_on_eval_ns(tmp_path: Path) -> None:
    lines, views = take_pair()
    shifted = [views[0], dv("TrySubmit", "submitted", eval_ns=T, wall_ns=T + 99 * MS)]
    result = leg_r1(r1_inputs(tmp_path, lines, shifted))
    assert sorted(failing(result)) == ["capture_missing", "capture_unexplained"]


def test_r1_maps_veto_trysubmit_lines_to_entryveto_records_through_on_change_filter(
    tmp_path: Path,
) -> None:
    lines = [
        decision_text(T + 5 * MS, take_for(), now_ns=T),
        try_submit_text(T + 9 * MS, "feed_stale"),
    ]
    views = [
        dv("Take", "take", eval_ns=T, wall_ns=T + 5 * MS),
        dv("EntryVeto", "feed_stale", eval_ns=T, wall_ns=T + 9 * MS),
    ]
    assert leg_r1(r1_inputs(tmp_path, lines, views)).outcome == LegOutcome.PASS


def test_r1_suppressed_repeat_veto_line_is_not_capture_missing(tmp_path: Path) -> None:
    lines = [
        decision_text(T + 5 * MS, take_for(), now_ns=T),
        try_submit_text(T + 9 * MS, "feed_stale"),
        try_submit_text(T + 12 * MS, "feed_stale"),  # same (kind, reason) again: not on-change
    ]
    views = [
        dv("Take", "take", eval_ns=T, wall_ns=T + 5 * MS),
        dv("EntryVeto", "feed_stale", eval_ns=T, wall_ns=T + 9 * MS),
    ]
    assert failing(leg_r1(r1_inputs(tmp_path, lines, views))) == []


def test_r1_veto_line_without_preceding_take_fails(tmp_path: Path) -> None:
    lines = [try_submit_text(T + 9 * MS, "feed_stale")]
    views = [dv("EntryVeto", "feed_stale", eval_ns=T, wall_ns=T + 9 * MS)]
    assert "veto_line_unanchored" in failing(leg_r1(r1_inputs(tmp_path, lines, views)))


def test_r1_guard_entryveto_matched_to_capture_refused_line(tmp_path: Path) -> None:
    lines, views = take_pair()
    guard = dv("EntryVeto", "capture_gap", eval_ns=T, wall_ns=T + 20 * MS)
    marker = refused_text(T + 20 * MS, "capture_gap")
    assert leg_r1(r1_inputs(tmp_path, [*lines, marker], [*views, guard])).outcome == (
        LegOutcome.PASS
    )
    unmatched = leg_r1(r1_inputs(tmp_path, lines, [*views, guard]))
    assert failing(unmatched) == ["guard_veto_without_capture_refused"]
    only_line = leg_r1(r1_inputs(tmp_path, [*lines, marker], views))
    assert failing(only_line) == ["capture_refused_without_veto_record"]


def test_r1_lines_inside_the_flush_window_are_counted_not_failed(tmp_path: Path) -> None:
    lines, views = take_pair()
    analysis = analyse(tmp_path, [instance_line(T - NS), *lines])
    result = leg_r1(inputs_for(boot_for(analysis, views[:1])))  # the TrySubmit record never landed
    assert failing(result) == []
    assert result.metrics["records_lost_in_flush_window"] == 1


def test_r1_only_judges_the_audited_day(tmp_path: Path) -> None:
    lines, _views = take_pair(offset_ns=-2 * 86_400 * NS)
    result = leg_r1(r1_inputs(tmp_path, lines, []))
    assert failing(result) == []


def test_r1_reports_a_capped_entry_list_as_an_error_not_a_pass(tmp_path: Path) -> None:
    lines, views = take_pair()
    analysis = analyse(tmp_path, [instance_line(T - NS), *lines])
    capped = type(analysis.scan)(**{**_fields(analysis.scan), "entry_total": 10_000})
    result = leg_r1(inputs_for(boot_for(analysis, views, scan=capped)))
    assert result.outcome == LegOutcome.ERROR


def _fields(scan: Any) -> dict[str, Any]:
    import dataclasses

    return {f.name: getattr(scan, f.name) for f in dataclasses.fields(scan)}


# ================================================================================================
# leg R3
# ================================================================================================


def test_funnel_matches_the_log_counts(tmp_path: Path) -> None:
    lines, views = take_pair()
    analysis = analyse(tmp_path, [instance_line(T - NS), *lines, refuse_line(1800 * NS)])
    inp = inputs_for(boot_for(analysis, views), funnel=(funnel_row(T + 900 * NS, 1, 1),))
    assert leg_r3(inp).outcome == LegOutcome.PASS


def test_funnel_vs_capture_count_mismatch_fails(tmp_path: Path) -> None:
    lines, views = take_pair()
    analysis = analyse(tmp_path, [instance_line(T - NS), *lines, refuse_line(1800 * NS)])
    inp = inputs_for(boot_for(analysis, views), funnel=(funnel_row(T + 900 * NS, 2, 1),))
    assert failing(leg_r3(inp)) == ["funnel_count_mismatch"]


def test_funnel_flush_next_to_a_take_is_skipped_for_the_earlier_one(tmp_path: Path) -> None:
    """The last flush within 2 s of an entry line is racy; the previous flush is the comparison."""
    lines, views = take_pair()
    analysis = analyse(tmp_path, [instance_line(T - NS), *lines, refuse_line(1800 * NS)])
    rows = (funnel_row(T + 900 * NS, 1, 1), funnel_row(T + 1, 0, 0))  # the second races the Take
    assert leg_r3(inputs_for(boot_for(analysis, views), funnel=rows)).outcome == LegOutcome.PASS


def test_funnel_rows_segmented_by_boot(tmp_path: Path) -> None:
    """Boot B logged no entry lines. The funnel row of boot A (one Take) must not be compared with
    it, and B's own row (all zero) passes."""
    lines, views = take_pair()
    a = analyse(tmp_path, [instance_line(T - NS), *lines, refuse_line(1800 * NS)], name="a.log")
    b_start = T + 7200 * NS
    b_lines = [
        instance_line(b_start, INSTANCE_B),
        decision_text(b_start + 60 * NS, Refuse(reason="x"), now_ns=b_start + 60 * NS),
    ]
    b = analyse(tmp_path, b_lines, name="b.log")
    boot_a = boot_for(a, views, started_ns=T - NS)
    boot_b = boot_for(b, [], instance_id=INSTANCE_B, started_ns=b_start)
    funnel = (funnel_row(T + 900 * NS, 1, 1), funnel_row(b_start + 900 * NS, 0, 0))
    assert leg_r3(inputs_for(boot_a, boot_b, funnel=funnel)).outcome == LegOutcome.PASS


# ================================================================================================
# MarkerParser and the marker grammar
# ================================================================================================


def test_marker_parser_collects_every_marker_kind_per_boot_and_day(tmp_path: Path) -> None:
    lines = [
        instance_line(T - NS),
        REAL_ORDER_SUBMITTED,
        REAL_ORDER_DENIED,
        REAL_NBP_PUBLISHED,
        REAL_FQ_VECTOR_COMPLETE,
        PINNED_NBP_CYCLE_MISSED,
        CONSTRUCTED_EPOCH_START,
        refused_text(T),
    ]
    found = analyse(tmp_path, lines).markers
    ((key, markers),) = found.items()
    assert key == (INSTANCE_ID, DAY)
    assert len(markers.order_submitted) == 1 and len(markers.order_denied) == 1
    assert len(markers.nbp_published) == 1 and len(markers.fq_vector_complete) == 1
    assert len(markers.nbp_cycle_missed) == 1 and len(markers.capture_epoch_start) == 1
    assert len(markers.capture_refused) == 1


def test_marker_parser_partitions_by_boot_and_utc_day(tmp_path: Path) -> None:
    lines = [
        instance_line(T - NS, INSTANCE_ID),
        refused_text(T),
        refused_text(DAY_END_NS + 5 * NS),
        instance_line(DAY_END_NS + 10 * NS, INSTANCE_B),
        refused_text(DAY_END_NS + 20 * NS),
    ]
    found = analyse(tmp_path, lines).markers
    next_day = DAY + dt.timedelta(days=1)
    assert {key: len(m.capture_refused) for key, m in found.items()} == {
        (INSTANCE_ID, DAY): 1,
        (INSTANCE_ID, next_day): 1,
        (INSTANCE_B, next_day): 1,
    }


def test_marker_parser_state_is_capped_and_overflow_fails_the_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(markers_module, "MAX_MARKERS_PER_KIND", 2)
    path = write_log(tmp_path / "n.log", *[refused_text(T + n) for n in range(3)])
    with pytest.raises(NodeLogSinkFailed):
        scan_node_log(path, sinks=(MarkerParser(),))


def test_capture_epoch_start_format_round_trips_through_the_parser(tmp_path: Path) -> None:
    """S2-R10: the line WP8 will emit, ``CAPTURE_EPOCH_START family=<id> epoch_ns=<n>``, is read
    back into ``LogMarkers.capture_epoch_start`` with both fields intact."""
    epoch_ns = T - 3600 * NS
    message = f"CAPTURE_EPOCH_START family=pm_us_crh_fq_v1 epoch_ns={epoch_ns}"
    line = f"{log_ts(T)} [INFO] BREEZY-L001.CaptureActor: {message}"
    ((_, markers),) = analyse(tmp_path, [line]).markers.items()
    (event,) = markers.capture_epoch_start
    assert isinstance(event, CaptureEpochStartLine)
    assert (event.family_id, event.epoch_ns) == ("pm_us_crh_fq_v1", epoch_ns)


def test_unparseable_marker_line_is_error_node_log_unparseable(tmp_path: Path) -> None:
    """A marker line that does not match its grammar is reported, never dropped (the gatherer
    turns ``scan.unparseable`` into ERROR); the sink sees nothing of it."""
    bad = f"{log_ts(T)} [INFO] X: CAPTURE_EPOCH_START family=f"
    analysis = analyse(tmp_path, [bad])
    assert analysis.scan.unparseable_total == 1 and not analysis.markers


# ================================================================================================
# Stage 2c review: S2-R40 (guard day cut), S2-R41 (flush window), S2-R46 (day clock)
# ================================================================================================

_MIDNIGHT = DAY_END_NS


def _straddling_boot(
    tmp_path: Path, *, detector_day_offset_ns: int | None = None
) -> tuple[Any, Any]:
    """A boot across midnight with one capture-guard refusal on each side: the log lines, and a
    guard ``EntryVeto`` record for each."""
    lines = [
        instance_line(_MIDNIGHT - 60 * NS),
        refused_text(_MIDNIGHT - 5 * NS, "capture_gap"),
        refused_text(_MIDNIGHT + 5 * NS, "capture_gap"),
    ]
    records = [
        dv("EntryVeto", "capture_gap", eval_ns=_MIDNIGHT - 5 * NS, wall_ns=_MIDNIGHT - 5 * NS),
        dv("EntryVeto", "capture_gap", eval_ns=_MIDNIGHT + 5 * NS, wall_ns=_MIDNIGHT + 5 * NS),
    ]
    return analyse(tmp_path, lines), records


@pytest.mark.parametrize("day", [DAY, DAY + dt.timedelta(days=1)], ids=["day_d", "day_d_plus_1"])
def test_a_boot_across_midnight_has_no_false_guard_fail_on_either_day(
    tmp_path: Path, day: dt.date
) -> None:
    """S2-R40. MUTATION: ``_guard_findings`` counts every record of the boot instead of the day's.
    Each day's refusal line is matched by that day's record only."""
    analysis, records = _straddling_boot(tmp_path)
    boot = boot_for(analysis, records, day=day)
    assert failing(leg_r1(inputs_for(boot, day=day))) == []


def test_a_guard_record_on_the_other_day_does_not_hide_a_missing_refusal_line(
    tmp_path: Path,
) -> None:
    """S2-R40: day D's record has no line of D, so it fails even though D+1 holds a line."""
    lines = [instance_line(_MIDNIGHT - 60 * NS), refused_text(_MIDNIGHT + 5 * NS, "capture_gap")]
    records = [
        dv("EntryVeto", "capture_gap", eval_ns=_MIDNIGHT - 5 * NS, wall_ns=_MIDNIGHT - 5 * NS)
    ]
    analysis = analyse(tmp_path, lines)
    boot = boot_for(analysis, records, day=DAY)
    assert failing(leg_r1(inputs_for(boot, day=DAY))) == ["guard_veto_without_capture_refused"]


def test_a_detector_event_of_the_next_day_does_not_excuse_a_refusal_line_of_this_day(
    tmp_path: Path,
) -> None:
    """S2-R40: a refusal with no known Take writes a detector event instead of a record; only the
    day's own events count against the day's surplus lines."""
    analysis = analyse(
        tmp_path,
        [instance_line(_MIDNIGHT - 60 * NS), refused_text(_MIDNIGHT - 5 * NS, "capture_gap")],
    )
    other_day = SimpleNamespace(ts_event=_MIDNIGHT + 5 * NS)
    same_day = SimpleNamespace(ts_event=_MIDNIGHT - 4 * NS)
    wrong = boot_for(analysis, [], day=DAY, detector_events=(other_day,))
    assert failing(leg_r1(inputs_for(wrong, day=DAY))) == ["capture_refused_without_veto_record"]
    right = boot_for(analysis, [], day=DAY, detector_events=(same_day,))
    assert failing(leg_r1(inputs_for(right, day=DAY))) == []


def test_a_record_lost_just_before_the_last_decision_of_a_boot_that_kept_logging_is_a_fail(
    tmp_path: Path,
) -> None:
    """S2-R41. MUTATION: the tail floor anchored at the last DECISION line. The boot logged for
    three more hours, so the flush window is long over: the missing record is FAIL, not INFO."""
    lines = [
        instance_line(T - NS),
        refuse_line(0, "a"),
        refuse_line(10 * NS, "b"),
        refuse_line(20 * NS, "c"),
        refused_text(T + 3 * 3600 * NS, "capture_gap"),  # the boot's last log line
    ]
    analysis = analyse(tmp_path, lines)
    assert analysis.scan.last_line_ts_ns == T + 3 * 3600 * NS
    present = [refuse_view(0, "a"), refuse_view(10 * NS, "b")]  # "c" lost
    result = leg_r2(inputs_for(boot_for(analysis, present)))
    assert failing(result) == ["stream_record_lost"]
    assert result.metrics["records_lost_in_flush_window"] == 0


def test_the_same_loss_is_flush_window_info_when_the_boot_stopped_with_that_decision(
    tmp_path: Path,
) -> None:
    lines = [
        instance_line(T - NS),
        refuse_line(0, "a"),
        refuse_line(10 * NS, "b"),
        refuse_line(20 * NS, "c"),
    ]
    analysis = analyse(tmp_path, lines)
    present = [refuse_view(0, "a"), refuse_view(10 * NS, "b")]
    result = leg_r2(inputs_for(boot_for(analysis, present)))
    assert failing(result) == []
    assert result.metrics["records_lost_in_flush_window"] == 1


def test_a_decision_a_millisecond_from_midnight_is_bucketed_the_same_on_both_sides(
    tmp_path: Path,
) -> None:
    """S2-R46. MUTATION: cut the stream on ``wall_ns`` while the replay cuts on the line clock. The
    record's ``wall_ns`` is 2 ms after its frame clock, which crosses midnight."""
    line_ns = _MIDNIGHT - MS
    lines = [
        instance_line(line_ns - 60 * NS),
        decision_text(line_ns, Refuse(reason="below_margin"), now_ns=line_ns),
    ]
    record = dv("Refuse", "below_margin", eval_ns=line_ns, wall_ns=line_ns + 2 * MS)
    analysis = analyse(tmp_path, lines)
    assert (INSTANCE_ID, DAY) in analysis.replay
    assert failing(leg_r2(inputs_for(boot_for(analysis, [record])))) == []
    next_day = DAY + dt.timedelta(days=1)
    assert (
        failing(leg_r2(inputs_for(boot_for(analysis, [record], day=next_day), day=next_day))) == []
    )


def test_a_follow_up_a_millisecond_after_midnight_lands_on_the_next_day_on_both_sides(
    tmp_path: Path,
) -> None:
    """S2-R46: a TrySubmit line's ``now_ns`` is the record's ``wall_ns`` (U9), so a follow-up logged
    just after midnight belongs to D+1 although its Take (and its ``eval_ns``) is on D."""
    take_ns, sub_ns = _MIDNIGHT - 5 * MS, _MIDNIGHT + MS
    lines = [
        instance_line(take_ns - 60 * NS),
        decision_text(take_ns, take_for(), now_ns=take_ns),
        try_submit_text(sub_ns, "submitted"),
    ]
    analysis = analyse(tmp_path, lines)
    next_day = DAY + dt.timedelta(days=1)
    views = [
        dv("Take", "take", eval_ns=take_ns, wall_ns=take_ns),
        dv("TrySubmit", "submitted", eval_ns=take_ns, wall_ns=sub_ns),
    ]
    for day, mine in ((DAY, views[:1]), (next_day, views[1:])):
        boot = boot_for(analysis, mine, day=day)
        assert failing(leg_r2(inputs_for(boot, day=day))) == [], day
