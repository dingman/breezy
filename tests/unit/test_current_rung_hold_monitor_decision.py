"""RED-first tests for the intra-day position monitor's pure thesis
classifier (INC-3, ``docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md`` §3,
Rev 2.1 addendum P6).
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from breezy.strategy.current_rung_hold.monitor_decision import (
    MonitorDecision,
    MonitorHistory,
    ThesisState,
    Verdict,
    evaluate_monitor,
    should_emit,
)
from breezy.strategy.current_rung_hold.monitor_evidence import MonitorEvidence

_MINUTE_NS = 60_000_000_000
_STALE_BOUND_NS = 50 * _MINUTE_NS


def _evidence(**overrides: object) -> MonitorEvidence:
    base: dict[str, object] = {
        "ts_ns": 0,
        "instrument_id": "sfo-86-87.POLYMARKET_US",
        "station": "SFO",
        "climate_day": "2026-09-01",
        "leg": "YES",
        "cell_key": ("SFO", "DJF", 14, 0, 0),
        "p_hold_at_entry": Decimal("0.70"),
        "p_hold_at_t": Decimal("0.70"),
        "fill_px": Decimal("0.40"),
        "held_qty": 1,
        "mark_vwap": Decimal("0.40"),
        "mark_source": "depth_walk",
        "spread": Decimal("0.02"),
        "depth_sufficient": True,
        "staleness_ns": 0,
        "book_staleness_ns": 0,
        "running_max_lower": 85,
        "running_max_upper": 85,
        "rung_low": 84,
        "rung_high": 87,
        "exit_fee_at_mark": Decimal("0.01"),
        "unrealized_pnl": Decimal("0.00"),
        "recoverable_value": Decimal("0.39"),
        "hour_lst": 14,
        "entry_context": "live",
    }
    base.update(overrides)
    return MonitorEvidence(**base)  # type: ignore[arg-type]


def _evaluate(
    evidence: MonitorEvidence, history: MonitorHistory,
) -> tuple[MonitorDecision, MonitorHistory]:
    return evaluate_monitor(evidence, history, stale_observation_bound_ns=_STALE_BOUND_NS)


# --------------------------------------------------------------------------
# Stale observation vs p_hold_undefined -- distinct reason codes
# --------------------------------------------------------------------------


def test_stale_observation_yields_unknown_state_and_verdict() -> None:
    evidence = _evidence(staleness_ns=_STALE_BOUND_NS + 1)

    decision, _ = _evaluate(evidence, MonitorHistory.EMPTY)

    assert decision.state is ThesisState.UNKNOWN
    assert decision.verdict is Verdict.UNKNOWN
    assert decision.reason_codes == ("stale_observation",)


def test_missing_staleness_reading_is_also_unknown() -> None:
    evidence = _evidence(staleness_ns=None)

    decision, _ = _evaluate(evidence, MonitorHistory.EMPTY)

    assert decision.state is ThesisState.UNKNOWN
    assert decision.reason_codes == ("stale_observation",)


def test_p_hold_undefined_is_a_distinct_reason_from_stale_observation() -> None:
    evidence = _evidence(staleness_ns=0, p_hold_at_t=None)

    decision, _ = _evaluate(evidence, MonitorHistory.EMPTY)

    assert decision.reason_codes == ("p_hold_undefined",)
    assert decision.state is ThesisState.ALIVE
    assert decision.verdict is Verdict.HOLD


# --------------------------------------------------------------------------
# DEAD classifier -- 2 distinct-time confirmation gate (P6: >= 5 min span)
# --------------------------------------------------------------------------


def test_single_noisy_dead_reading_is_a_candidate_not_a_confirmation() -> None:
    evidence = _evidence(ts_ns=0, running_max_lower=90, rung_high=87)

    decision, history = _evaluate(evidence, MonitorHistory.EMPTY)

    assert decision.state is ThesisState.ALIVE  # previous state, unchanged
    assert decision.reason_codes == ("dead_candidate",)
    assert history.dead_confirm_observed_ns == (0,)


def test_two_distinct_times_spanning_the_guard_confirms_dead() -> None:
    first = _evidence(ts_ns=0, running_max_lower=90, rung_high=87)
    _, history = _evaluate(first, MonitorHistory.EMPTY)

    second = _evidence(ts_ns=5 * _MINUTE_NS, running_max_lower=90, rung_high=87)
    decision, history = _evaluate(second, history)

    assert decision.state is ThesisState.DEAD_BY_OBSERVATION
    assert decision.reason_codes == ("dead_confirmed",)
    assert decision.verdict is Verdict.EXIT_RECOMMENDED  # depth_sufficient, fresh book


def test_two_qualifying_reads_under_the_span_guard_never_confirm() -> None:
    first = _evidence(ts_ns=0, running_max_lower=90, rung_high=87)
    _, history = _evaluate(first, MonitorHistory.EMPTY)

    second = _evidence(ts_ns=_MINUTE_NS, running_max_lower=90, rung_high=87)
    decision, _ = _evaluate(second, history)

    assert decision.state is not ThesisState.DEAD_BY_OBSERVATION
    assert decision.reason_codes == ("dead_candidate",)


def test_a_same_instant_repush_never_counts_twice_toward_dead() -> None:
    first = _evidence(ts_ns=0, running_max_lower=90, rung_high=87)
    _, history = _evaluate(first, MonitorHistory.EMPTY)

    repushed = _evidence(ts_ns=0, running_max_lower=91, rung_high=87)
    decision, history = _evaluate(repushed, history)

    assert decision.state is not ThesisState.DEAD_BY_OBSERVATION
    assert history.dead_confirm_observed_ns == (0,)


def test_confirmed_dead_with_a_stale_book_is_missing_stop_never_exit() -> None:
    first = _evidence(ts_ns=0, running_max_lower=90, rung_high=87, book_staleness_ns=0)
    _, history = _evaluate(first, MonitorHistory.EMPTY)

    second = _evidence(
        ts_ns=5 * _MINUTE_NS, running_max_lower=90, rung_high=87,
        book_staleness_ns=181 * 1_000_000_000,
    )
    decision, _ = _evaluate(second, history)

    assert decision.state is ThesisState.DEAD_BY_OBSERVATION
    assert decision.verdict is Verdict.MISSING_STOP


def test_confirmed_dead_with_one_sided_depth_is_missing_stop() -> None:
    first = _evidence(ts_ns=0, running_max_lower=90, rung_high=87)
    _, history = _evaluate(first, MonitorHistory.EMPTY)

    second = _evidence(
        ts_ns=5 * _MINUTE_NS, running_max_lower=90, rung_high=87,
        mark_source="missing", depth_sufficient=False, mark_vwap=None,
    )
    decision, _ = _evaluate(second, history)

    assert decision.verdict is Verdict.MISSING_STOP


# --------------------------------------------------------------------------
# LOCKED_BY_OBSERVATION -- mechanistic
# --------------------------------------------------------------------------


def test_locked_when_the_interval_sits_fully_inside_the_rung_after_18_lst() -> None:
    evidence = _evidence(
        running_max_lower=85, running_max_upper=86, rung_low=84, rung_high=87, hour_lst=18,
    )

    decision, _ = _evaluate(evidence, MonitorHistory.EMPTY)

    assert decision.state is ThesisState.LOCKED_BY_OBSERVATION
    assert decision.verdict is Verdict.HOLD


def test_not_locked_before_the_locked_hour_even_if_interval_is_inside() -> None:
    evidence = _evidence(
        running_max_lower=85, running_max_upper=86, rung_low=84, rung_high=87, hour_lst=17,
    )

    decision, _ = _evaluate(evidence, MonitorHistory.EMPTY)

    assert decision.state is not ThesisState.LOCKED_BY_OBSERVATION


# --------------------------------------------------------------------------
# THREATENED hysteresis -- confirmations + span, both directions
# --------------------------------------------------------------------------


def _candidate_evidence(ts_ns: int) -> MonitorEvidence:
    # p_hold_at_entry (0.70) - p_hold_at_t (0.55) == 0.15 >= the 0.10 margin.
    return _evidence(ts_ns=ts_ns, p_hold_at_entry=Decimal("0.70"), p_hold_at_t=Decimal("0.55"))


def test_a_single_candidate_reading_is_a_no_op() -> None:
    decision, history = _evaluate(_candidate_evidence(0), MonitorHistory.EMPTY)

    assert decision.state is ThesisState.ALIVE
    assert decision.reason_codes == ("p_hold_drop_candidate",)
    assert history.candidate_count == 1


def test_three_confirmations_spanning_ten_minutes_flips_to_threatened() -> None:
    history = MonitorHistory.EMPTY
    for ts_ns in (0, 4 * _MINUTE_NS, 10 * _MINUTE_NS):
        decision, history = _evaluate(_candidate_evidence(ts_ns), history)

    assert decision.state is ThesisState.THREATENED
    assert decision.verdict is Verdict.REDUCE_RECOMMENDED


def test_three_confirmations_under_the_span_guard_never_flip() -> None:
    history = MonitorHistory.EMPTY
    for ts_ns in (0, 1 * _MINUTE_NS, 2 * _MINUTE_NS):
        decision, history = _evaluate(_candidate_evidence(ts_ns), history)

    assert decision.state is ThesisState.ALIVE


def test_a_non_candidate_reading_resets_an_in_progress_threatened_run() -> None:
    history = MonitorHistory.EMPTY
    _, history = _evaluate(_candidate_evidence(0), history)
    _, history = _evaluate(_candidate_evidence(4 * _MINUTE_NS), history)
    # A recovering reading interrupts the run.
    _, history = _evaluate(_evidence(ts_ns=5 * _MINUTE_NS), history)
    decision, history = _evaluate(_candidate_evidence(6 * _MINUTE_NS), history)

    assert decision.state is ThesisState.ALIVE
    assert history.candidate_count == 1


def test_recovery_to_alive_is_symmetric_with_entering_threatened() -> None:
    threatened_history = dataclasses.replace(
        MonitorHistory.EMPTY,
        last_state=ThesisState.THREATENED,
        last_verdict=Verdict.REDUCE_RECOMMENDED,
    )
    history = threatened_history
    for ts_ns in (0, 4 * _MINUTE_NS, 10 * _MINUTE_NS):
        decision, history = _evaluate(_evidence(ts_ns=ts_ns), history)

    assert decision.state is ThesisState.ALIVE
    assert decision.verdict is Verdict.HOLD


def test_recovery_reads_under_the_span_guard_stay_threatened() -> None:
    threatened_history = dataclasses.replace(
        MonitorHistory.EMPTY,
        last_state=ThesisState.THREATENED,
        last_verdict=Verdict.REDUCE_RECOMMENDED,
    )
    history = threatened_history
    for ts_ns in (0, 1 * _MINUTE_NS):
        decision, history = _evaluate(_evidence(ts_ns=ts_ns), history)

    assert decision.state is ThesisState.THREATENED


# --------------------------------------------------------------------------
# should_emit
# --------------------------------------------------------------------------


def test_should_emit_true_on_the_very_first_evaluation() -> None:
    decision = MonitorDecision(
        state=ThesisState.ALIVE, verdict=Verdict.HOLD, reason_codes=(), confirmations=0, ts_ns=0,
    )

    assert should_emit(decision, MonitorHistory.EMPTY, now_ns=0) is True


def test_should_emit_true_on_a_state_change() -> None:
    history = dataclasses.replace(
        MonitorHistory.EMPTY,
        last_state=ThesisState.ALIVE, last_verdict=Verdict.HOLD, last_emitted_ts_ns=0,
    )
    decision = MonitorDecision(
        state=ThesisState.THREATENED, verdict=Verdict.REDUCE_RECOMMENDED,
        reason_codes=(), confirmations=0, ts_ns=1,
    )

    assert should_emit(decision, history, now_ns=1) is True


def test_should_emit_false_within_the_heartbeat_window_with_no_change() -> None:
    history = dataclasses.replace(
        MonitorHistory.EMPTY,
        last_state=ThesisState.ALIVE, last_verdict=Verdict.HOLD, last_emitted_ts_ns=0,
    )
    decision = MonitorDecision(
        state=ThesisState.ALIVE, verdict=Verdict.HOLD, reason_codes=(), confirmations=0, ts_ns=1,
    )

    assert should_emit(decision, history, now_ns=30_000_000_000) is False


def test_should_emit_true_after_the_heartbeat_elapses_with_no_change() -> None:
    history = dataclasses.replace(
        MonitorHistory.EMPTY,
        last_state=ThesisState.ALIVE, last_verdict=Verdict.HOLD, last_emitted_ts_ns=0,
    )
    decision = MonitorDecision(
        state=ThesisState.ALIVE, verdict=Verdict.HOLD, reason_codes=(), confirmations=0, ts_ns=1,
    )

    assert should_emit(decision, history, now_ns=_MINUTE_NS) is True


# --------------------------------------------------------------------------
# History immutability
# --------------------------------------------------------------------------


def test_evaluate_monitor_never_mutates_the_input_history() -> None:
    history = MonitorHistory.EMPTY
    snapshot = dataclasses.astuple(history)

    _, new_history = _evaluate(_candidate_evidence(0), history)

    assert dataclasses.astuple(history) == snapshot
    assert new_history is not history


# --------------------------------------------------------------------------
# Property: UNKNOWN and unconfirmed-DEAD never produce EXIT_RECOMMENDED
# --------------------------------------------------------------------------


_reading = st.fixed_dictionaries(
    {
        "stale": st.booleans(),
        "dead_qualifies": st.booleans(),
        "p_hold_drop": st.booleans(),
    }
)


# --------------------------------------------------------------------------
# NO leg -- the thesis classifier's semantics invert (2026-09-15 fix)
# --------------------------------------------------------------------------


def _no_evidence(**overrides: object) -> MonitorEvidence:
    overrides.setdefault("leg", "NO")
    return _evidence(**overrides)


def test_no_leg_single_win_lock_reading_is_a_candidate_not_locked() -> None:
    evidence = _no_evidence(ts_ns=0, running_max_lower=90, rung_high=87)

    decision, history = _evaluate(evidence, MonitorHistory.EMPTY)

    assert decision.state is not ThesisState.LOCKED_BY_OBSERVATION
    assert decision.reason_codes == ("dead_candidate",)
    assert history.dead_confirm_observed_ns == (0,)


def test_no_leg_two_confirmed_win_lock_readings_are_locked_and_hold() -> None:
    first = _no_evidence(ts_ns=0, running_max_lower=90, rung_high=87)
    _, history = _evaluate(first, MonitorHistory.EMPTY)

    second = _no_evidence(ts_ns=5 * _MINUTE_NS, running_max_lower=90, rung_high=87)
    decision, _ = _evaluate(second, history)

    assert decision.state is ThesisState.LOCKED_BY_OBSERVATION
    assert decision.verdict is Verdict.HOLD
    assert decision.reason_codes == ("no_leg_win_locked",)


def test_no_leg_single_inside_rung_after_peak_reading_is_a_candidate_not_dead() -> None:
    evidence = _no_evidence(
        running_max_lower=85, running_max_upper=86, rung_low=84, rung_high=87, hour_lst=18,
    )

    decision, history = _evaluate(evidence, MonitorHistory.EMPTY)

    assert decision.state is not ThesisState.DEAD_BY_OBSERVATION
    assert decision.reason_codes == ("dead_candidate",)
    assert history.locked_confirm_observed_ns == (0,)


def test_no_leg_inside_rung_after_peak_confirmed_is_dead_and_exit_recommended() -> None:
    first = _no_evidence(
        ts_ns=0, running_max_lower=85, running_max_upper=86,
        rung_low=84, rung_high=87, hour_lst=18,
    )
    _, history = _evaluate(first, MonitorHistory.EMPTY)

    second = _no_evidence(
        ts_ns=5 * _MINUTE_NS, running_max_lower=85, running_max_upper=86,
        rung_low=84, rung_high=87, hour_lst=18,
    )
    decision, _ = _evaluate(second, history)

    assert decision.state is ThesisState.DEAD_BY_OBSERVATION
    assert decision.verdict is Verdict.EXIT_RECOMMENDED
    assert decision.reason_codes == ("no_leg_inside_rung_after_peak",)


def test_no_leg_inside_rung_after_peak_confirmed_with_stale_book_is_missing_stop() -> None:
    first = _no_evidence(
        ts_ns=0, running_max_lower=85, running_max_upper=86,
        rung_low=84, rung_high=87, hour_lst=18, book_staleness_ns=0,
    )
    _, history = _evaluate(first, MonitorHistory.EMPTY)

    second = _no_evidence(
        ts_ns=5 * _MINUTE_NS, running_max_lower=85, running_max_upper=86,
        rung_low=84, rung_high=87, hour_lst=18, book_staleness_ns=181 * 1_000_000_000,
    )
    decision, _ = _evaluate(second, history)

    assert decision.state is ThesisState.DEAD_BY_OBSERVATION
    assert decision.verdict is Verdict.MISSING_STOP


def test_no_leg_inside_rung_before_peak_flips_to_threatened_after_confirmations() -> None:
    history = MonitorHistory.EMPTY
    decision = None
    for ts_ns in (0, 4 * _MINUTE_NS, 10 * _MINUTE_NS):
        evidence = _no_evidence(
            ts_ns=ts_ns, running_max_lower=85, running_max_upper=86,
            rung_low=84, rung_high=87, hour_lst=14,
        )
        decision, history = _evaluate(evidence, history)

    assert decision is not None
    assert decision.state is ThesisState.THREATENED
    assert decision.verdict is Verdict.REDUCE_RECOMMENDED
    assert decision.reason_codes == ()


def test_no_leg_inside_rung_before_peak_building_candidate_reason_is_no_inside_rung() -> None:
    evidence = _no_evidence(
        ts_ns=0, running_max_lower=85, running_max_upper=86,
        rung_low=84, rung_high=87, hour_lst=14,
    )

    decision, _ = _evaluate(evidence, MonitorHistory.EMPTY)

    assert decision.state is ThesisState.ALIVE
    assert decision.reason_codes == ("no_inside_rung",)


def test_no_leg_inside_rung_before_peak_never_confirms_to_dead() -> None:
    history = MonitorHistory.EMPTY
    for minute in range(12):
        evidence = _no_evidence(
            ts_ns=minute * _MINUTE_NS, running_max_lower=85, running_max_upper=86,
            rung_low=84, rung_high=87, hour_lst=14,
        )
        decision, history = _evaluate(evidence, history)
        assert decision.state is not ThesisState.DEAD_BY_OBSERVATION
        assert decision.state is not ThesisState.LOCKED_BY_OBSERVATION


def test_no_leg_below_the_rung_is_alive() -> None:
    evidence = _no_evidence(
        running_max_lower=80, running_max_upper=81, rung_low=84, rung_high=87,
    )

    decision, _ = _evaluate(evidence, MonitorHistory.EMPTY)

    assert decision.state is ThesisState.ALIVE
    assert decision.verdict is Verdict.HOLD


def test_no_leg_history_does_not_disturb_yes_leg_regression() -> None:
    """Sanity: the YES fixture default still exercises the unchanged path."""
    evidence = _evidence(running_max_lower=90, rung_high=87)

    decision, _ = _evaluate(evidence, MonitorHistory.EMPTY)

    assert decision.reason_codes == ("dead_candidate",)


_no_position = st.sampled_from(["above", "inside", "below"])


@given(st.lists(_no_position, min_size=1, max_size=12))
@settings(max_examples=100)
def test_no_leg_never_reports_locked_while_the_interval_is_inside_the_rung(
    positions: list[str],
) -> None:
    history = MonitorHistory.EMPTY
    ts_ns = 0
    for position in positions:
        ts_ns += 6 * _MINUTE_NS
        if position == "above":
            running_max_lower, running_max_upper = 90, 91
        elif position == "inside":
            running_max_lower, running_max_upper = 85, 86
        else:
            running_max_lower, running_max_upper = 80, 81
        evidence = _no_evidence(
            ts_ns=ts_ns, running_max_lower=running_max_lower,
            running_max_upper=running_max_upper, rung_low=84, rung_high=87, hour_lst=14,
        )
        decision, history = _evaluate(evidence, history)

        if decision.state is ThesisState.LOCKED_BY_OBSERVATION:
            assert running_max_lower > 87


@given(st.lists(_reading, min_size=1, max_size=12))
@settings(max_examples=100)
def test_unknown_and_unconfirmed_dead_never_yield_exit_recommended(
    readings: list[dict[str, bool]],
) -> None:
    history = MonitorHistory.EMPTY
    ts_ns = 0
    for reading in readings:
        ts_ns += 6 * _MINUTE_NS
        evidence = _evidence(
            ts_ns=ts_ns,
            staleness_ns=(_STALE_BOUND_NS + 1) if reading["stale"] else 0,
            running_max_lower=90 if reading["dead_qualifies"] else 80,
            rung_high=87,
            p_hold_at_t=Decimal("0.55") if reading["p_hold_drop"] else Decimal("0.70"),
        )
        decision, history = _evaluate(evidence, history)

        if decision.verdict is Verdict.EXIT_RECOMMENDED:
            assert decision.state is ThesisState.DEAD_BY_OBSERVATION
            assert decision.reason_codes == ("dead_confirmed",)
        if decision.state is ThesisState.UNKNOWN:
            assert decision.verdict is not Verdict.EXIT_RECOMMENDED
        if decision.reason_codes == ("dead_candidate",):
            assert decision.verdict is not Verdict.EXIT_RECOMMENDED
