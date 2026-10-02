"""R3.2 -- table-driven unit tests for the supervisor decisions lifted into
``trade_supervisor_core``: pure values in, values out; no clock, no I/O."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from pathlib import Path

import pytest

from breezy.runtime.trade_supervisor_core import (
    MIDDAY_BUDGET_EXHAUSTED_REASON,
    MIDDAY_MAX_RELAUNCH_ATTEMPTS,
    MIDDAY_READINESS_RECHECK_TIMEOUT,
    PERMIT_NOT_REQUESTED_MARKER,
    STRATEGY_SUBSCRIBED_MARKERS,
    AlertDetail,
    ContinuousFamilyCheck,
    DaySchedulerState,
    EscalationLoadOutcome,
    MiddayDeadAction,
    MiddayRecheckAction,
    Phase,
    RelaunchCause,
    SelfCheckResult,
    decide_midday_dead_child,
    decide_midday_recheck,
    derive_self_check_facts,
    initial_scheduler_state,
    latch_midday_log_facts,
    midday_boot_retry_dispatch_due,
    midday_handler_reads_log,
    midday_recheck_pending,
    midday_watch_idle,
    phase_exception_marks_fired,
    phase_poll_interval_s,
    self_check_load_alert,
    self_check_log_fields,
    self_check_result_alert,
)

_DAY = dt.date(2026, 9, 25)
_NOW = dt.datetime(2026, 9, 25, 17, 5, tzinfo=dt.UTC)
_NOW_NS = int(_NOW.timestamp() * 1e9)
_LOG = Path("/nonexistent/node.log")
_SUBSCRIBED = STRATEGY_SUBSCRIBED_MARKERS[0]


def _state(**kw: object) -> DaySchedulerState:
    return replace(initial_scheduler_state(_DAY), **kw)  # type: ignore[arg-type]


def _permit_line(expires_ns: int) -> str:
    return f"live-trading permit issued issued_at_ns=1 expires_at_ns={expires_ns} ttl_s=60\n"


@pytest.mark.parametrize(
    ("phase", "interval"),
    [
        (Phase.RELAUNCH_CHECK, 15.0),
        (Phase.LAUNCH, 60.0),
        (Phase.SELF_CHECK, 60.0),
        (Phase.MIDDAY_WATCH, 60.0),
        (Phase.STOP_PRIOR, 60.0),
    ],
)
def test_phase_poll_interval(phase: Phase, interval: float) -> None:
    assert phase_poll_interval_s(phase) == interval


@pytest.mark.parametrize("phase", list(Phase))
def test_phase_exception_marks_fired_except_relaunch_check(phase: Phase) -> None:
    assert phase_exception_marks_fired(phase) is (phase is not Phase.RELAUNCH_CHECK)


@pytest.mark.parametrize(
    ("alert_sent", "pid", "log", "expected"),
    [
        (False, 7, _LOG, True),
        (True, 7, _LOG, False),
        (False, None, _LOG, False),
        (False, 7, None, False),
    ],
)
def test_midday_handler_reads_log(
    alert_sent: bool, pid: int | None, log: Path | None, expected: bool
) -> None:
    state = _state(midday_alert_sent=alert_sent)
    assert midday_handler_reads_log(state=state, tracked_pid=pid, node_log=log) is expected


def test_facts_without_state_are_log_only() -> None:
    log = _SUBSCRIBED + "\n" + _permit_line(_NOW_NS + 10**9)
    facts = derive_self_check_facts(state=None, log_text=log, now=_NOW)
    assert facts.state is None
    assert (facts.strategy_subscribed, facts.permit_issued, facts.permit_expiry_valid) == (
        True,
        True,
        True,
    )
    assert facts.permit_expiry_at_daily_ceiling is False


def test_facts_without_state_expired_permit_is_invalid() -> None:
    facts = derive_self_check_facts(state=None, log_text=_permit_line(_NOW_NS - 1), now=_NOW)
    assert (facts.permit_issued, facts.permit_expiry_valid) == (True, False)


def test_facts_with_state_latch_live_evidence() -> None:
    log = _SUBSCRIBED + "\n" + _permit_line(_NOW_NS + 5) + PERMIT_NOT_REQUESTED_MARKER
    facts = derive_self_check_facts(state=_state(), log_text=log, now=_NOW)
    assert facts.state is not None
    assert facts.state.strategy_subscribed_seen is True
    assert facts.state.permit_issued_seen_expires_at_ns == _NOW_NS + 5
    assert facts.state.first_boot_permit_expires_at_ns == _NOW_NS + 5
    assert facts.state.orders_not_requested_seen is True


def test_facts_with_state_use_latch_when_log_delta_is_empty() -> None:
    state = _state(strategy_subscribed_seen=True, permit_issued_seen_expires_at_ns=_NOW_NS + 9)
    facts = derive_self_check_facts(state=state, log_text="", now=_NOW)
    assert (facts.strategy_subscribed, facts.permit_issued, facts.permit_expiry_valid) == (
        True,
        True,
        True,
    )


def test_facts_latched_expired_permit_is_invalid_despite_fresh_live_line() -> None:
    state = _state(permit_issued_seen_expires_at_ns=_NOW_NS - 1)
    facts = derive_self_check_facts(state=state, log_text=_permit_line(_NOW_NS + 10**9), now=_NOW)
    assert facts.permit_expiry_valid is False


@pytest.mark.parametrize(
    ("relaunch_attempts", "anchor_offset", "expected"),
    [
        (1, 0, True),
        (0, 0, False),  # never relaunched: the match is trivial, not a clamp
        (1, 1, False),  # expiry differs from the anchor
    ],
)
def test_facts_permit_expiry_at_daily_ceiling(
    relaunch_attempts: int, anchor_offset: int, expected: bool
) -> None:
    expiry = _NOW_NS + 100
    state = _state(
        relaunch_attempts=relaunch_attempts,
        first_boot_permit_expires_at_ns=expiry + anchor_offset,
        permit_issued_seen_expires_at_ns=expiry,
    )
    facts = derive_self_check_facts(state=state, log_text="", now=_NOW)
    assert facts.permit_expiry_at_daily_ceiling is expected


def test_facts_zero_instruments_refusal_latches_once() -> None:
    log = "current_rung_hold: resolved 0 instruments for X; refusing to start"
    facts = derive_self_check_facts(state=_state(), log_text=log, now=_NOW)
    assert facts.state is not None and facts.state.boot_zero_instruments_seen is True


def test_log_fields_plain_pass() -> None:
    fields = self_check_log_fields(
        result=SelfCheckResult.PASS,
        continuous_check=None,
        continuous_family_halt_source=None,
        load_outcome=EscalationLoadOutcome.PRESENT,
        gap_hours=1.0,
    )
    assert fields == {"result": SelfCheckResult.PASS.value}


def test_log_fields_absent_gap_and_continuous() -> None:
    fields = self_check_log_fields(
        result=SelfCheckResult.PASS,
        continuous_check=ContinuousFamilyCheck(True, False, True),
        continuous_family_halt_source=None,
        load_outcome=EscalationLoadOutcome.ABSENT,
        gap_hours=49.9,
    )
    assert fields == {
        "result": SelfCheckResult.PASS.value,
        "continuous_phase0_clean": True,
        "continuous_startup_evidence_valid": False,
        "continuous_family_not_halted": True,
        "continuous_family_halt_source": "unknown",
        "escalation_state": "absent",
        "self_check_gap_hours": 49,
    }


@pytest.mark.parametrize(
    ("outcome", "event", "detail"),
    [
        (
            EscalationLoadOutcome.CORRUPT,
            "TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STATE_CORRUPT",
            AlertDetail.SELF_CHECK_ESCALATION_STATE_CORRUPT,
        ),
        (
            EscalationLoadOutcome.UNAVAILABLE,
            "TRADE_SUPERVISOR_SELF_CHECK_ESCALATION_STORE_UNAVAILABLE",
            AlertDetail.SELF_CHECK_ESCALATION_STORE_UNAVAILABLE,
        ),
    ],
)
def test_load_alert_warns_for_bad_record(
    outcome: EscalationLoadOutcome, event: str, detail: AlertDetail
) -> None:
    spec = self_check_load_alert(outcome)
    assert spec is not None
    assert (spec.event, spec.severity, spec.detail) == (event, "WARN", detail)


@pytest.mark.parametrize("outcome", [EscalationLoadOutcome.ABSENT, EscalationLoadOutcome.PRESENT])
def test_load_alert_silent_otherwise(outcome: EscalationLoadOutcome) -> None:
    assert self_check_load_alert(outcome) is None


_FAIL = SelfCheckResult.FAIL_CHILD_EXITED


@pytest.mark.parametrize(
    ("result", "outcome", "failures", "expected"),
    [
        (SelfCheckResult.PASS, EscalationLoadOutcome.PRESENT, 0, None),
        (SelfCheckResult.PASS_ADOPTED_LOG_UNKNOWN, EscalationLoadOutcome.CORRUPT, 1, None),
        (_FAIL, EscalationLoadOutcome.PRESENT, 1, ("TRADE_SUPERVISOR_SELF_CHECK_FAIL", "WARN")),
        (_FAIL, EscalationLoadOutcome.ABSENT, 1, ("TRADE_SUPERVISOR_SELF_CHECK_FAIL", "WARN")),
        (
            _FAIL,
            EscalationLoadOutcome.PRESENT,
            2,
            ("TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED", "CRITICAL"),
        ),
        (
            _FAIL,
            EscalationLoadOutcome.CORRUPT,
            1,
            ("TRADE_SUPERVISOR_SELF_CHECK_FAIL_REPEATED", "CRITICAL"),
        ),
    ],
)
def test_result_alert_table(
    result: SelfCheckResult,
    outcome: EscalationLoadOutcome,
    failures: int,
    expected: tuple[str, str] | None,
) -> None:
    spec = self_check_result_alert(
        result=result, load_outcome=outcome, consecutive_failures=failures
    )
    if expected is None:
        assert spec is None
    else:
        assert spec is not None
        assert (spec.event, spec.severity) == expected


def test_result_alert_detail_follows_count_knowledge() -> None:
    known = self_check_result_alert(
        result=_FAIL, load_outcome=EscalationLoadOutcome.PRESENT, consecutive_failures=2
    )
    corrupt = self_check_result_alert(
        result=_FAIL, load_outcome=EscalationLoadOutcome.CORRUPT, consecutive_failures=1
    )
    unavailable = self_check_result_alert(
        result=_FAIL, load_outcome=EscalationLoadOutcome.UNAVAILABLE, consecutive_failures=1
    )
    assert known is not None and corrupt is not None and unavailable is not None
    assert corrupt.detail is AlertDetail.SELF_CHECK_ESCALATION_STATE_CORRUPT
    assert unavailable.detail is AlertDetail.SELF_CHECK_ESCALATION_STORE_UNAVAILABLE
    assert known.detail not in (corrupt.detail, unavailable.detail)


def _retry_state(**kw: object) -> DaySchedulerState:
    return _state(boot_zero_instruments_seen=True, **kw)


@pytest.mark.parametrize(
    ("state", "pid", "log", "owned", "expected"),
    [
        (_retry_state(), None, None, False, True),
        (_retry_state(), 5, _LOG, True, True),
        (_retry_state(), 5, None, True, False),
        (_retry_state(), 5, _LOG, False, False),
        (_state(), None, None, False, False),
        (_retry_state(readiness_observed=True), None, None, False, False),
        (_retry_state(first_boot_permit_expires_at_ns=1), None, None, False, False),
        (_retry_state(boot_retry_nontransient_alert_sent=True), None, None, False, False),
        (_retry_state(boot_retry_exhausted_alert_sent=True), None, None, False, False),
    ],
)
def test_midday_boot_retry_dispatch_due(
    state: DaySchedulerState, pid: int | None, log: Path | None, owned: bool, expected: bool
) -> None:
    got = midday_boot_retry_dispatch_due(
        state=state, tracked_pid=pid, node_log=log, is_owned=lambda _p: owned
    )
    assert got is expected


def test_boot_retry_dispatch_never_consults_ownership_without_a_pid_or_when_gated() -> None:
    calls: list[int] = []

    def probe(pid: int) -> bool:
        calls.append(pid)
        return True

    midday_boot_retry_dispatch_due(
        state=_retry_state(), tracked_pid=None, node_log=None, is_owned=probe
    )
    midday_boot_retry_dispatch_due(state=_state(), tracked_pid=5, node_log=_LOG, is_owned=probe)
    assert calls == []


@pytest.mark.parametrize(
    ("kw", "pid", "log", "expected"),
    [
        ({}, 5, _LOG, False),
        ({"boot_retry_nontransient_alert_sent": True}, 5, _LOG, True),
        ({"boot_retry_exhausted_alert_sent": True}, 5, _LOG, True),
        ({"midday_alert_sent": True}, 5, _LOG, True),
        ({}, None, _LOG, True),
        ({}, 5, None, True),
    ],
)
def test_midday_watch_idle(
    kw: dict[str, object], pid: int | None, log: Path | None, expected: bool
) -> None:
    assert midday_watch_idle(state=_state(**kw), tracked_pid=pid, node_log=log) is expected


def test_latch_midday_log_facts_all_markers() -> None:
    log = _SUBSCRIBED + "\n" + _permit_line(_NOW_NS + 3) + PERMIT_NOT_REQUESTED_MARKER
    state, cause = latch_midday_log_facts(state=_state(), now=_NOW, log_text=log)
    assert state.strategy_subscribed_seen is True
    assert state.permit_issued_seen_expires_at_ns == _NOW_NS + 3
    assert state.first_boot_permit_expires_at_ns == _NOW_NS + 3
    assert state.orders_not_requested_seen is True
    assert cause is RelaunchCause.UNKNOWN
    assert state.midday_cause_seen is None


def test_latch_midday_log_facts_empty_delta_changes_nothing() -> None:
    before = _state()
    state, cause = latch_midday_log_facts(state=before, now=_NOW, log_text="")
    assert state == before
    assert cause is RelaunchCause.UNKNOWN


def test_midday_recheck_pending() -> None:
    assert midday_recheck_pending(_state()) is False
    assert midday_recheck_pending(_state(last_midday_relaunch_attempt_at=_NOW)) is True
    assert (
        midday_recheck_pending(
            _state(last_midday_relaunch_attempt_at=_NOW, midday_readiness_recheck_done=True)
        )
        is False
    )


@pytest.mark.parametrize(
    ("holds", "subscribed", "permit", "elapsed", "expected"),
    [
        (True, True, 1, dt.timedelta(0), MiddayRecheckAction.READY),
        (True, True, 1, MIDDAY_READINESS_RECHECK_TIMEOUT * 5, MiddayRecheckAction.READY),
        (False, True, 1, dt.timedelta(0), MiddayRecheckAction.WAIT),
        (False, True, 1, MIDDAY_READINESS_RECHECK_TIMEOUT, MiddayRecheckAction.WAIT),
        (
            False,
            True,
            1,
            MIDDAY_READINESS_RECHECK_TIMEOUT + dt.timedelta(seconds=1),
            MiddayRecheckAction.NOT_READY_TIMEOUT,
        ),
        (True, False, 1, dt.timedelta(0), MiddayRecheckAction.WAIT),
        (True, True, None, dt.timedelta(0), MiddayRecheckAction.WAIT),
    ],
)
def test_decide_midday_recheck(
    holds: bool,
    subscribed: bool,
    permit: int | None,
    elapsed: dt.timedelta,
    expected: MiddayRecheckAction,
) -> None:
    state = _state(
        last_midday_relaunch_attempt_at=_NOW - elapsed,
        strategy_subscribed_seen=subscribed,
        permit_issued_seen_expires_at_ns=permit,
    )
    assert decide_midday_recheck(state=state, now=_NOW, holds_intent_lock=holds) is expected


_MIDDAY_NOW = dt.datetime(2026, 9, 25, 18, 0, tzinfo=dt.UTC)


@pytest.mark.parametrize(
    ("kw", "cause", "action", "reason"),
    [
        ({}, RelaunchCause.TRANSIENT, MiddayDeadAction.CEILING_UNKNOWN_FIRST, None),
        (
            {"midday_ceiling_unknown_alert_sent": True},
            RelaunchCause.TRANSIENT,
            MiddayDeadAction.CEILING_UNKNOWN_REPEAT,
            None,
        ),
        (
            {"first_boot_permit_expires_at_ns": 1},
            RelaunchCause.TRANSIENT,
            MiddayDeadAction.RELAUNCH,
            None,
        ),
        (
            {"first_boot_permit_expires_at_ns": 1},
            RelaunchCause.UNKNOWN,
            MiddayDeadAction.DECLINED,
            "exit cause is not transient",
        ),
        (
            {"first_boot_permit_expires_at_ns": 1, "midday_cause_seen": RelaunchCause.TRANSIENT},
            RelaunchCause.UNKNOWN,
            MiddayDeadAction.RELAUNCH,
            None,
        ),
        (
            {
                "first_boot_permit_expires_at_ns": 1,
                "midday_relaunch_attempts": MIDDAY_MAX_RELAUNCH_ATTEMPTS,
            },
            RelaunchCause.TRANSIENT,
            MiddayDeadAction.EXHAUSTED,
            MIDDAY_BUDGET_EXHAUSTED_REASON,
        ),
        (
            {
                "first_boot_permit_expires_at_ns": 1,
                "midday_relaunch_attempts": 1,
                "last_midday_relaunch_attempt_at": _MIDDAY_NOW - dt.timedelta(seconds=30),
            },
            RelaunchCause.TRANSIENT,
            MiddayDeadAction.DECLINED,
            "minimum inter-attempt gap not elapsed",
        ),
    ],
)
def test_decide_midday_dead_child(
    kw: dict[str, object], cause: RelaunchCause, action: MiddayDeadAction, reason: str | None
) -> None:
    decision = decide_midday_dead_child(state=_state(**kw), now=_MIDDAY_NOW, live_cause=cause)
    assert decision.action is action
    assert decision.reason == reason


def test_ceiling_gate_precedes_a_would_be_exhausted_budget() -> None:
    state = _state(midday_relaunch_attempts=MIDDAY_MAX_RELAUNCH_ATTEMPTS)
    decision = decide_midday_dead_child(
        state=state, now=_MIDDAY_NOW, live_cause=RelaunchCause.TRANSIENT
    )
    assert decision.action is MiddayDeadAction.CEILING_UNKNOWN_FIRST
