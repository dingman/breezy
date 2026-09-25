"""AUD-14b -- pure-core unit tests for the self-check repeat-failure
escalation mechanism: no I/O, no clock, no store, no ``DaySchedulerState``.

Covers plan steps 2 and 2a (``docs/plans/backlog/AUDIT_2026-09-21/
AUD-14-hands-off-operation-restart-motive-and-selfcheck-escalation.md``):
``SelfCheckEscalationState``, ``record_self_check_result``,
``escalated_self_check_severity``, and the escalation codec
(``encode_self_check_escalation_state``/``decode_self_check_escalation_state``).

The I/O shell tests (persistence, fault paths, restart/rollover replay) live
in ``tests/unit/test_trade_supervisor.py``.
"""

from __future__ import annotations

import datetime as dt
import inspect
from dataclasses import replace

from breezy.runtime.trade_supervisor_core import (
    MIDDAY_MAX_RELAUNCH_ATTEMPTS,
    PERMIT_ALERT_HEARTBEAT,
    PERMIT_DEFERRED_MAX,
    DaySchedulerState,
    PermitAlertAction,
    PermitCapability,
    SelfCheckEscalationState,
    SelfCheckResult,
    decide_permit_alert,
    decode_self_check_escalation_state,
    encode_self_check_escalation_state,
    escalated_self_check_severity,
    initial_scheduler_state,
    latch_log_facts,
    midday_budget_live,
    permit_capability_valid,
    permit_watch_window,
    record_child_adopted,
    record_permit_alert_sent,
    record_self_check_result,
    record_strategy_subscribed_seen,
)

_DAY = dt.date(2026, 9, 25)


def _utc(hour: int, minute: int, second: int = 0, *, day: dt.date = _DAY) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=dt.UTC)


_FAR_FUTURE_NS = 4102444800000000000  # 2100-01-01T00:00:00Z

# ---------------------------------------------------------------------------
# Step 2 -- the pure reducer.
# ---------------------------------------------------------------------------


class TestRecordSelfCheckResult:
    def test_a_second_consecutive_self_check_failure_increments_the_counter(self):
        state = SelfCheckEscalationState()
        state = record_self_check_result(
            state, SelfCheckResult.FAIL_NODE_NOT_READY.value, now_utc="2026-09-12T17:05:01Z"
        )
        assert state.consecutive_failures == 1
        state = record_self_check_result(
            state, SelfCheckResult.FAIL_NODE_NOT_READY.value, now_utc="2026-09-13T17:05:11Z"
        )
        assert state.consecutive_failures == 2

    def test_a_pass_resets_the_consecutive_failure_counter(self):
        state = SelfCheckEscalationState(
            consecutive_failures=5, last_self_check_utc="2026-09-17T17:05:05Z"
        )
        state = record_self_check_result(
            state, SelfCheckResult.PASS.value, now_utc="2026-09-19T17:05:33Z"
        )
        assert state.consecutive_failures == 0

        state = SelfCheckEscalationState(consecutive_failures=3)
        state = record_self_check_result(
            state, SelfCheckResult.PASS_ADOPTED_LOG_UNKNOWN.value, now_utc="2026-09-19T17:05:33Z"
        )
        assert state.consecutive_failures == 0

    def test_the_reducer_records_the_self_check_utc_on_every_result(self):
        state = SelfCheckEscalationState()
        fail_state = record_self_check_result(
            state, SelfCheckResult.FAIL_CHILD_EXITED.value, now_utc="2026-09-18T17:05:05Z"
        )
        assert fail_state.last_self_check_utc == "2026-09-18T17:05:05Z"

        pass_state = record_self_check_result(
            fail_state, SelfCheckResult.PASS.value, now_utc="2026-09-19T17:05:33Z"
        )
        assert pass_state.last_self_check_utc == "2026-09-19T17:05:33Z"

    def test_the_escalation_reducer_takes_no_date_and_never_touches_day_scheduler_state(self):
        """Structural pin -- the deliberate deviation from the ``record_*``
        family: no ``day``/``dt.date`` parameter, no ``DaySchedulerState``
        operand or return, matching §6's decision that this counter is not
        per-trading-day state."""
        signature = inspect.signature(record_self_check_result)
        param_names = set(signature.parameters)
        assert param_names == {"state", "result", "now_utc"}
        for name, param in signature.parameters.items():
            annotation = param.annotation
            assert "date" not in str(annotation).lower(), name
            assert "DaySchedulerState" not in str(annotation), name
        assert "DaySchedulerState" not in str(signature.return_annotation)

        result = record_self_check_result(
            SelfCheckEscalationState(), SelfCheckResult.PASS.value, now_utc="2026-09-19T17:05:33Z"
        )
        assert isinstance(result, SelfCheckEscalationState)
        assert not isinstance(result, DaySchedulerState)


# ---------------------------------------------------------------------------
# Step 2a -- the severity decision (pure, fail-toward-alerting rule).
# ---------------------------------------------------------------------------


class TestEscalatedSelfCheckSeverity:
    def test_a_pass_result_resolves_to_no_severity_at_all(self):
        assert (
            escalated_self_check_severity(
                result_is_fail=False, consecutive_failures=0, count_known=True
            )
            is None
        )
        assert (
            escalated_self_check_severity(
                result_is_fail=False, consecutive_failures=5, count_known=False
            )
            is None
        )

    def test_a_first_failure_with_a_known_count_resolves_to_warn(self):
        assert (
            escalated_self_check_severity(
                result_is_fail=True, consecutive_failures=1, count_known=True
            )
            == "WARN"
        )

    def test_a_second_consecutive_failure_with_a_known_count_resolves_to_critical(self):
        assert (
            escalated_self_check_severity(
                result_is_fail=True, consecutive_failures=2, count_known=True
            )
            == "CRITICAL"
        )
        assert (
            escalated_self_check_severity(
                result_is_fail=True, consecutive_failures=7, count_known=True
            )
            == "CRITICAL"
        )

    def test_an_unknown_count_resolves_a_failure_to_critical_even_at_a_count_of_one(self):
        assert (
            escalated_self_check_severity(
                result_is_fail=True, consecutive_failures=1, count_known=False
            )
            == "CRITICAL"
        )
        assert (
            escalated_self_check_severity(
                result_is_fail=True, consecutive_failures=0, count_known=False
            )
            == "CRITICAL"
        )


# ---------------------------------------------------------------------------
# Step 2a -- the escalation codec (total decode; every rejection is CORRUPT,
# never coerced to a default).
# ---------------------------------------------------------------------------


class TestSelfCheckEscalationCodec:
    def test_the_escalation_codec_round_trips_both_fields_by_name(self):
        state = SelfCheckEscalationState(
            consecutive_failures=3, last_self_check_utc="2026-09-14T17:05:07Z"
        )
        raw = encode_self_check_escalation_state(state)
        assert isinstance(raw, bytes)
        decoded = decode_self_check_escalation_state(raw)
        assert decoded == state

    def test_the_codec_rejects_a_missing_key_an_extra_key_and_a_wrong_scalar_type(self):
        import json

        missing_key = json.dumps({"consecutive_failures": 1}).encode("utf-8")
        assert decode_self_check_escalation_state(missing_key) is None

        extra_key = json.dumps(
            {
                "consecutive_failures": 1,
                "last_self_check_utc": "2026-09-14T17:05:07Z",
                "extra": "field",
            }
        ).encode("utf-8")
        assert decode_self_check_escalation_state(extra_key) is None

        wrong_scalar_type = json.dumps(
            {"consecutive_failures": "not-an-int", "last_self_check_utc": "2026-09-14T17:05:07Z"}
        ).encode("utf-8")
        assert decode_self_check_escalation_state(wrong_scalar_type) is None

        not_json = b"not json at all"
        assert decode_self_check_escalation_state(not_json) is None

        not_an_object = json.dumps([1, 2, 3]).encode("utf-8")
        assert decode_self_check_escalation_state(not_an_object) is None


# ---------------------------------------------------------------------------
# B1 -- the supervisor-side permit-lapse detector's pure decision core.
# ---------------------------------------------------------------------------


def _valid_state(**overrides) -> DaySchedulerState:
    return replace(initial_scheduler_state(_DAY), **overrides)


class TestPermitWatchWindow:
    def test_permit_watch_window_is_1710z_to_0100z_next_day(self):
        opens, closes = permit_watch_window(_DAY)
        assert opens == _utc(17, 10)
        assert closes == _utc(1, 0, day=_DAY + dt.timedelta(days=1))


class TestMiddayBudgetLive:
    def test_midday_budget_not_live_when_ceiling_unknown_alert_sent(self):
        assert (
            midday_budget_live(
                launch_done=True,
                readiness_observed=True,
                midday_watch_window_open=True,
                midday_alert_sent=False,
                midday_ceiling_unknown_alert_sent=True,
                midday_relaunch_attempts=0,
            )
            is False
        )
        # Every other condition satisfied -- confirms the ceiling-unknown
        # latch alone is sufficient to close the budget.
        assert (
            midday_budget_live(
                launch_done=True,
                readiness_observed=True,
                midday_watch_window_open=True,
                midday_alert_sent=False,
                midday_ceiling_unknown_alert_sent=False,
                midday_relaunch_attempts=0,
            )
            is True
        )


class TestPermitCapabilityValid:
    def test_permit_capability_is_valid_before_latched_expiry(self):
        state = _valid_state(permit_issued_seen_expires_at_ns=_FAR_FUTURE_NS)
        capability = permit_capability_valid(
            state, 1_000, child_alive=True, log_available=True, midday_budget_live=False
        )
        assert capability is PermitCapability.VALID

    def test_permit_capability_lapsed_at_or_after_expiry(self):
        state = _valid_state(permit_issued_seen_expires_at_ns=1_000)
        capability = permit_capability_valid(
            state, 1_000, child_alive=True, log_available=True, midday_budget_live=False
        )
        assert capability is PermitCapability.LAPSED
        capability_after = permit_capability_valid(
            state, 1_001, child_alive=True, log_available=True, midday_budget_live=False
        )
        assert capability_after is PermitCapability.LAPSED

    def test_expired_at_ceiling_only_after_a_relaunch(self):
        # Same expiry as the ceiling anchor, but no relaunch happened yet --
        # this IS the first boot's own permit, a genuine LAPSED, not the
        # clamp.
        state = _valid_state(
            permit_issued_seen_expires_at_ns=1_000,
            first_boot_permit_expires_at_ns=1_000,
        )
        assert (
            permit_capability_valid(
                state, 1_000, child_alive=True, log_available=True, midday_budget_live=False
            )
            is PermitCapability.LAPSED
        )

        relaunched = _valid_state(
            permit_issued_seen_expires_at_ns=1_000,
            first_boot_permit_expires_at_ns=1_000,
            relaunch_attempts=1,
        )
        assert (
            permit_capability_valid(
                relaunched, 1_000, child_alive=True, log_available=True, midday_budget_live=False
            )
            is PermitCapability.EXPIRED_AT_CEILING
        )

        midday_relaunched = _valid_state(
            permit_issued_seen_expires_at_ns=1_000,
            first_boot_permit_expires_at_ns=1_000,
            midday_relaunch_attempts=1,
        )
        assert (
            permit_capability_valid(
                midday_relaunched,
                1_000,
                child_alive=True,
                log_available=True,
                midday_budget_live=False,
            )
            is PermitCapability.EXPIRED_AT_CEILING
        )

    def test_permit_capability_unknown_only_when_log_unavailable(self):
        state = _valid_state()
        assert (
            permit_capability_valid(
                state, 1_000, child_alive=True, log_available=False, midday_budget_live=False
            )
            is PermitCapability.UNKNOWN
        )
        # Log unavailable but the child is dead -- never UNKNOWN, since row 1
        # requires the child to be alive.
        assert (
            permit_capability_valid(
                state, 1_000, child_alive=False, log_available=False, midday_budget_live=False
            )
            is not PermitCapability.UNKNOWN
        )

    def test_permit_capability_not_required_when_marker_latched(self):
        state = _valid_state(orders_not_requested_seen=True)
        assert (
            permit_capability_valid(
                state, 1_000, child_alive=True, log_available=True, midday_budget_live=False
            )
            is PermitCapability.NOT_REQUIRED
        )
        # Even with the child dead and no budget -- the marker still wins.
        assert (
            permit_capability_valid(
                state, 1_000, child_alive=False, log_available=True, midday_budget_live=False
            )
            is PermitCapability.NOT_REQUIRED
        )

    def test_absent_takes_precedence_over_unknown_when_log_readable(self):
        # AC14: alive, log readable, no latch, no marker, no midday relaunch
        # at all (so the boot grace never applies) -> ABSENT, never UNKNOWN.
        state = _valid_state()
        capability = permit_capability_valid(
            state, 1_000, child_alive=True, log_available=True, midday_budget_live=False
        )
        assert capability is PermitCapability.ABSENT
        assert capability is not PermitCapability.UNKNOWN

    def test_boot_grace_defers_a_fresh_midday_child_without_permit_line(self):
        relaunch_at = _utc(20, 0)
        state = _valid_state(last_midday_relaunch_attempt_at=relaunch_at)
        within_grace_ns = int((relaunch_at + dt.timedelta(minutes=1)).timestamp() * 1e9)
        assert (
            permit_capability_valid(
                state,
                within_grace_ns,
                child_alive=True,
                log_available=True,
                midday_budget_live=False,
            )
            is PermitCapability.DEFERRED
        )
        past_grace_ns = int((relaunch_at + dt.timedelta(minutes=3)).timestamp() * 1e9)
        assert (
            permit_capability_valid(
                state, past_grace_ns, child_alive=True, log_available=True, midday_budget_live=False
            )
            is PermitCapability.ABSENT
        )

    def test_a_never_relaunched_first_boot_child_gets_no_boot_grace(self):
        """[silent-failure-review A1] A never-relaunched (16:50Z) child with
        no permit line past launch+2min is ABSENT immediately -- the boot
        grace is reserved for a midday-relaunched child only."""
        state = _valid_state()  # last_midday_relaunch_attempt_at is None
        soon_ns = int(_utc(16, 52).timestamp() * 1e9)
        assert (
            permit_capability_valid(
                state, soon_ns, child_alive=True, log_available=True, midday_budget_live=False
            )
            is PermitCapability.ABSENT
        )

    def test_deferred_becomes_no_node_after_twenty_minutes(self):
        deferred_since = _utc(20, 0)
        state = _valid_state(permit_deferred_since=deferred_since)
        just_under_ns = int(
            (deferred_since + PERMIT_DEFERRED_MAX - dt.timedelta(seconds=1)).timestamp() * 1e9
        )
        assert (
            permit_capability_valid(
                state, just_under_ns, child_alive=False, log_available=True, midday_budget_live=True
            )
            is PermitCapability.DEFERRED
        )
        past_bound_ns = int(
            (deferred_since + PERMIT_DEFERRED_MAX + dt.timedelta(seconds=1)).timestamp() * 1e9
        )
        assert (
            permit_capability_valid(
                state, past_bound_ns, child_alive=False, log_available=True, midday_budget_live=True
            )
            is PermitCapability.NO_NODE
        )


class TestPermitDeferredSinceMonotonic:
    def test_deferred_unknown_deferred_flicker_still_promotes_at_twenty_minutes(self):
        """[silent-failure-review A1] permit_deferred_since must NOT reset on
        an interstitial UNKNOWN observation -- the 20-minute bound is
        measured from the FIRST DEFERRED observation, even after a flicker
        to UNKNOWN and back to DEFERRED."""
        from breezy.runtime.trade_supervisor_core import record_permit_deferred_since

        state = _valid_state()
        t0 = _utc(20, 0)

        # First observation: DEFERRED (child dead, midday budget live).
        cap0 = permit_capability_valid(
            state,
            int(t0.timestamp() * 1e9),
            child_alive=False,
            log_available=True,
            midday_budget_live=True,
        )
        assert cap0 is PermitCapability.DEFERRED
        state = record_permit_deferred_since(state, t0, capability=cap0)
        assert state.permit_deferred_since == t0

        # Interstitial poll: child alive but log unreadable -> UNKNOWN. Must
        # NOT clear permit_deferred_since.
        t1 = t0 + dt.timedelta(minutes=5)
        cap1 = permit_capability_valid(
            state,
            int(t1.timestamp() * 1e9),
            child_alive=True,
            log_available=False,
            midday_budget_live=True,
        )
        assert cap1 is PermitCapability.UNKNOWN
        state = record_permit_deferred_since(state, t1, capability=cap1)
        assert state.permit_deferred_since == t0  # unchanged

        # Back to DEFERRED at t0+21min -- must promote to NO_NODE because the
        # bound is measured from t0, not from this later re-entry.
        t2 = t0 + dt.timedelta(minutes=21)
        cap2 = permit_capability_valid(
            state,
            int(t2.timestamp() * 1e9),
            child_alive=False,
            log_available=True,
            midday_budget_live=True,
        )
        assert cap2 is PermitCapability.NO_NODE


class TestDecidePermitAlert:
    def test_decide_permit_alert_heartbeat_repeats_after_sixty_minutes(self):
        first = decide_permit_alert(
            capability=PermitCapability.ABSENT,
            now=_utc(20, 0),
            last_sent_at=None,
            last_capability=None,
            not_required_warned=False,
        )
        assert first.action is PermitAlertAction.ALERT

        too_soon = decide_permit_alert(
            capability=PermitCapability.ABSENT,
            now=_utc(20, 30),
            last_sent_at=_utc(20, 0),
            last_capability=PermitCapability.ABSENT.value,
            not_required_warned=False,
        )
        assert too_soon.action is PermitAlertAction.NONE

        heartbeat_due = decide_permit_alert(
            capability=PermitCapability.ABSENT,
            now=_utc(20, 0) + PERMIT_ALERT_HEARTBEAT,
            last_sent_at=_utc(20, 0),
            last_capability=PermitCapability.ABSENT.value,
            not_required_warned=False,
        )
        assert heartbeat_due.action is PermitAlertAction.ALERT

    def test_decide_permit_alert_capability_change_emits_immediately(self):
        decision = decide_permit_alert(
            capability=PermitCapability.NO_NODE,
            now=_utc(20, 1),
            last_sent_at=_utc(20, 0),
            last_capability=PermitCapability.ABSENT.value,
            not_required_warned=False,
        )
        assert decision.action is PermitAlertAction.ALERT
        assert decision.detail is not None

    def test_deferred_and_not_required_never_alert_via_heartbeat_alone(self):
        assert (
            decide_permit_alert(
                capability=PermitCapability.DEFERRED,
                now=_utc(20, 0),
                last_sent_at=None,
                last_capability=None,
                not_required_warned=False,
            ).action
            is PermitAlertAction.NONE
        )

    def test_not_required_warns_once_then_never_again_today(self):
        first = decide_permit_alert(
            capability=PermitCapability.NOT_REQUIRED,
            now=_utc(17, 15),
            last_sent_at=None,
            last_capability=None,
            not_required_warned=False,
        )
        assert first.action is PermitAlertAction.ALERT
        assert first.severity == "WARN"

        second = decide_permit_alert(
            capability=PermitCapability.NOT_REQUIRED,
            now=_utc(22, 15),
            last_sent_at=None,
            last_capability=None,
            not_required_warned=True,
        )
        assert second.action is PermitAlertAction.NONE


class TestPermitAlertLatchLifecycle:
    def test_permit_alert_latches_survive_record_child_adopted(self):
        state = _valid_state(
            permit_alert_last_sent_at=_utc(20, 0),
            permit_alert_last_capability=PermitCapability.ABSENT.value,
            permit_deferred_since=_utc(19, 0),
            permit_gap_info_logged=True,
            permit_not_required_warned=True,
        )
        adopted = record_child_adopted(state, _utc(20, 5))
        assert adopted.permit_alert_last_sent_at == _utc(20, 0)
        assert adopted.permit_alert_last_capability == PermitCapability.ABSENT.value
        assert adopted.permit_deferred_since == _utc(19, 0)
        assert adopted.permit_gap_info_logged is True
        assert adopted.permit_not_required_warned is True
        # The per-child marker latch IS cleared by adoption.
        seeded = _valid_state(orders_not_requested_seen=True)
        assert record_child_adopted(seeded, _utc(20, 5)).orders_not_requested_seen is False

    def test_permit_alert_latches_reset_at_trading_day_rollover(self):
        state = record_permit_alert_sent(
            _valid_state(), _utc(20, 0), capability=PermitCapability.ABSENT
        )
        next_day = _DAY + dt.timedelta(days=1)
        rolled = record_permit_alert_sent(
            state, _utc(20, 0, day=next_day), capability=PermitCapability.VALID
        )
        # A genuinely NEW day's state -- not just this one field changed.
        assert rolled.day == next_day
        assert rolled.permit_alert_last_capability == PermitCapability.VALID.value
        # And a plain read (no alert) after rollover starts fresh.
        from breezy.runtime.trade_supervisor_core import _for_day

        fresh = _for_day(state, next_day)
        assert fresh.permit_alert_last_sent_at is None
        assert fresh.permit_alert_last_capability is None


class TestLatchLogFactsParity:
    def test_latch_log_facts_parity_with_midday_watch_inline_latching(self):
        log_text = (
            "trading node failed\n"
            f"live-trading permit issued issued_at_ns=1 expires_at_ns={_FAR_FUTURE_NS} "
            "ttl_s=1\n"
            "CurrentRungHoldStrategy subscribed X\n"
        )
        state = initial_scheduler_state(_DAY)

        drained = latch_log_facts(state, _utc(20, 0), log_text)

        # Mirrors _do_midday_watch's own inline sequence exactly.
        from breezy.runtime.trade_supervisor_core import (
            RelaunchCause,
            classify_exit1_cause,
            parse_permit_expiry_ns,
            record_first_boot_permit_seen,
            record_midday_cause_seen,
            record_permit_issued_seen,
            strategy_subscribed_in,
        )

        inline = state
        if strategy_subscribed_in(log_text):
            inline = record_strategy_subscribed_seen(inline, _utc(20, 0))
        permit_expiry_ns = parse_permit_expiry_ns(log_text)
        if permit_expiry_ns is not None:
            inline = record_permit_issued_seen(inline, _utc(20, 0), permit_expiry_ns)
            inline = record_first_boot_permit_seen(inline, _utc(20, 0), permit_expiry_ns)
        cause = classify_exit1_cause(log_text)
        if cause is not RelaunchCause.UNKNOWN:
            inline = record_midday_cause_seen(inline, _utc(20, 0), cause)

        assert drained.strategy_subscribed_seen == inline.strategy_subscribed_seen
        assert (
            drained.permit_issued_seen_expires_at_ns == inline.permit_issued_seen_expires_at_ns
        )
        assert (
            drained.first_boot_permit_expires_at_ns == inline.first_boot_permit_expires_at_ns
        )
        assert drained.midday_cause_seen == inline.midday_cause_seen

    def test_latch_log_facts_also_latches_the_not_requested_marker(self):
        from breezy.runtime.trade_supervisor_core import PERMIT_NOT_REQUESTED_MARKER

        state = initial_scheduler_state(_DAY)
        drained = latch_log_facts(state, _utc(20, 0), PERMIT_NOT_REQUESTED_MARKER + "\n")
        assert drained.orders_not_requested_seen is True


class TestCloseEvaluationInstant:
    def test_close_evaluation_uses_window_close_instant(self):
        """A permit that lapses exactly AT the window close must be seen as
        LAPSED when evaluated with ``now_ns := close_ns`` (D2's close-
        evaluation contract), not treated as still-open."""
        from breezy.runtime.trade_supervisor_core import midday_watch_window_end

        close = midday_watch_window_end(_DAY)
        close_ns = int(close.timestamp() * 1e9)
        state = _valid_state(permit_issued_seen_expires_at_ns=close_ns)
        assert (
            permit_capability_valid(
                state, close_ns, child_alive=True, log_available=True, midday_budget_live=False
            )
            is PermitCapability.LAPSED
        )


# Sanity: the constant used throughout the tests above matches the plan.
def test_midday_max_relaunch_attempts_constant_is_three():
    assert MIDDAY_MAX_RELAUNCH_ATTEMPTS == 3
