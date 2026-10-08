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
import re
from dataclasses import fields, replace
from typing import Any

import pytest

from breezy.runtime.trade_supervisor_core import (
    LIVENESS_MAX_AGE_NS,
    LIVENESS_MAX_FUTURE_SKEW_NS,
    LIVENESS_SCAN_MAX_OCCURRENCES,
    MIDDAY_MAX_RELAUNCH_ATTEMPTS,
    NODE_LOG_NAME_RE,
    PERMIT_ALERT_HEARTBEAT,
    PERMIT_DEFERRED_MAX,
    READY_ADOPTION_ALERT_EVENT,
    AlertDetail,
    DaySchedulerState,
    PermitAlertAction,
    PermitCapability,
    ReadyAdoptionVerdict,
    SelfCheckEscalationState,
    SelfCheckResult,
    decide_permit_alert,
    decide_ready_adoption,
    decide_ready_adoption_alert,
    decode_self_check_escalation_state,
    encode_self_check_escalation_state,
    escalated_self_check_severity,
    initial_scheduler_state,
    is_deferral,
    latch_log_facts,
    latest_liveness_line_ns,
    midday_budget_live,
    node_log_spawned_at,
    permit_capability_valid,
    permit_watch_window,
    record_child_adopted,
    record_liveness_line_seen,
    record_permit_alert_sent,
    record_ready_adoption,
    record_ready_adoption_alert_sent,
    record_ready_adoption_deferral,
    record_self_check_result,
    record_strategy_subscribed_seen,
    reset_ready_adoption_deferral,
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


class _UnmappedCapability:
    """[silent-failure-hunter/python-reviewer review] A stand-in for a
    future ``PermitCapability`` member that reaches ``decide_permit_alert``
    with no ``_PERMIT_ALERT_DETAIL`` entry and no explicit branch (not
    ``NOT_REQUIRED``/``DEFERRED``/``VALID``, and its ``.value`` is not in
    ``_BAD_CAPABILITY_VALUES``). A real enum member can't exercise this --
    every current one is mapped -- so this mimics one structurally instead."""

    value = "totally_unmapped_capability"


class TestDecidePermitAlert:
    def test_decide_permit_alert_raises_on_an_unmapped_capability(self):
        """The fallback must fail loudly, never silently resolve to NONE --
        D8's own containment (``_do_permit_watch``) is what turns this into
        a CRITICAL ``WATCH_FAILED`` page, never this function itself."""
        with pytest.raises(AssertionError):
            decide_permit_alert(
                capability=_UnmappedCapability(),
                now=_utc(20, 0),
                last_sent_at=None,
                last_capability=None,
                not_required_warned=False,
            )

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
        """[FU-1, 2026-09-25] Before this change, `_do_midday_watch`'s own
        inline sequence never latched `orders_not_requested_seen`, so this
        test could only assert parity on the OTHER four fields --
        `latch_log_facts` strictly EXCEEDED `_do_midday_watch` on that one.
        `_do_midday_watch` now latches it too (same discipline as its other
        four inline latches), so this asserts the now-EQUAL coverage: every
        field `latch_log_facts` sets from this text, `_do_midday_watch`'s
        own inline sequence sets identically, field for field."""
        from breezy.runtime.trade_supervisor_core import PERMIT_NOT_REQUESTED_MARKER

        log_text = (
            "trading node failed\n"
            f"live-trading permit issued issued_at_ns=1 expires_at_ns={_FAR_FUTURE_NS} "
            "ttl_s=1\n"
            "CurrentRungHoldStrategy subscribed X\n"
        ) + PERMIT_NOT_REQUESTED_MARKER + "\n"
        state = initial_scheduler_state(_DAY)

        drained = latch_log_facts(state, _utc(20, 0), log_text)

        # Mirrors _do_midday_watch's own inline sequence exactly (post FU-1).
        from breezy.runtime.trade_supervisor_core import (
            RelaunchCause,
            classify_exit1_cause,
            parse_permit_expiry_ns,
            record_first_boot_permit_seen,
            record_midday_cause_seen,
            record_orders_not_requested_seen,
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
        if PERMIT_NOT_REQUESTED_MARKER in log_text:
            inline = record_orders_not_requested_seen(inline, _utc(20, 0))

        assert drained.strategy_subscribed_seen == inline.strategy_subscribed_seen
        assert (
            drained.permit_issued_seen_expires_at_ns == inline.permit_issued_seen_expires_at_ns
        )
        assert (
            drained.first_boot_permit_expires_at_ns == inline.first_boot_permit_expires_at_ns
        )
        assert drained.midday_cause_seen == inline.midday_cause_seen
        # The now-equal field -- previously exceeded, never asserted here.
        assert drained.orders_not_requested_seen == inline.orders_not_requested_seen
        assert drained == inline

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


# ===========================================================================
# [SUP-RESTART-ANYTIME] ready-adoption: pure core (T1-T7e)
# ===========================================================================

_NS = 1_000_000_000
_V = ReadyAdoptionVerdict
_NOW = _utc(20, 0)
_NOW_NS = int(_NOW.timestamp()) * _NS
_STAMP_LINE_TAIL = " [INFO] BREEZY-L001.FORECAST-QUANTILE-LADDER: SHADOW_DECISION {'k': 1}\n"


def _nautilus_prefix(at_ns: int, *, ansi: bool = True) -> str:
    seconds, nanos = divmod(at_ns, _NS)
    moment = dt.datetime.fromtimestamp(seconds, dt.UTC)
    stamp = f"{moment:%Y-%m-%dT%H:%M:%S}.{nanos:09d}Z"
    return f"\x1b[1m{stamp}\x1b[0m" if ansi else stamp


def _shadow_line(at_ns: int, *, ansi: bool = True) -> str:
    return _nautilus_prefix(at_ns, ansi=ansi) + _STAMP_LINE_TAIL


def _proven_state(**overrides: Any) -> DaySchedulerState:
    """Every proof true: ``decide_ready_adoption`` returns MARK."""
    base = replace(
        initial_scheduler_state(_DAY),
        permit_issued_seen_expires_at_ns=_NOW_NS + 3 * 3600 * _NS,
        first_boot_permit_expires_at_ns=_NOW_NS + 3 * 3600 * _NS,
        strategy_subscribed_seen=True,
        liveness_line_last_ns=_NOW_NS - 30 * _NS,
    )
    return replace(base, **overrides)


def _decide(state: DaySchedulerState | None = None, **overrides: Any) -> ReadyAdoptionVerdict:
    kwargs: dict[str, Any] = {
        "now": _NOW,
        "now_ns": _NOW_NS,
        "child_alive": True,
        "holder_is_tracked": True,
        "log_spawned_at": _utc(16, 50),
    }
    kwargs.update(overrides)
    return decide_ready_adoption(state=state if state is not None else _proven_state(), **kwargs)


class TestDecideReadyAdoption:
    def test_decide_ready_adoption_marks_only_when_every_proof_holds(self) -> None:
        """T1: flip each input from the all-true baseline; assert the verdict."""
        assert _decide() is _V.MARK
        cases: list[tuple[ReadyAdoptionVerdict, DaySchedulerState | None, dict[str, Any]]] = [
            (_V.ALREADY_READY, _proven_state(readiness_observed=True), {}),
            (_V.NO_CHILD, None, {"child_alive": False}),
            (_V.HOLDER_UNPROVEN, None, {"holder_is_tracked": False}),
            (_V.PERMIT_ABSENT, _proven_state(permit_issued_seen_expires_at_ns=None), {}),
            (
                _V.NOT_REQUIRED,
                _proven_state(
                    permit_issued_seen_expires_at_ns=None, orders_not_requested_seen=True
                ),
                {},
            ),
            (
                _V.PERMIT_EXPIRED,
                _proven_state(permit_issued_seen_expires_at_ns=_NOW_NS),
                {},
            ),
            (_V.NOT_SUBSCRIBED, _proven_state(strategy_subscribed_seen=False), {}),
            (_V.ANCHOR_UNKNOWN, _proven_state(first_boot_permit_expires_at_ns=None), {}),
            (_V.LOG_UNKNOWN, None, {"log_spawned_at": None}),
            (_V.LOG_NOT_CURRENT_DAY, None, {"log_spawned_at": _utc(16, 39, 59)}),
            (_V.NO_FRESH_ACTIVITY, _proven_state(liveness_line_last_ns=None), {}),
            (
                _V.NO_FRESH_ACTIVITY,
                _proven_state(liveness_line_last_ns=_NOW_NS - LIVENESS_MAX_AGE_NS - 1),
                {},
            ),
            (_V.NOT_IN_WINDOW, None, {"now": _utc(17, 9, 59)}),
        ]
        for expected, state, overrides in cases:
            assert _decide(state, **overrides) is expected, expected

    def test_permit_expiry_boundary_uses_this_polls_now_ns(self) -> None:
        state = _proven_state(permit_issued_seen_expires_at_ns=_NOW_NS)
        assert _decide(state) is _V.PERMIT_EXPIRED
        state = _proven_state(permit_issued_seen_expires_at_ns=_NOW_NS + 1)
        assert _decide(state) is _V.MARK
        assert _decide(state, now_ns=_NOW_NS + 1) is _V.PERMIT_EXPIRED

    def test_latched_permit_wins_over_orders_not_requested(self) -> None:
        state = _proven_state(orders_not_requested_seen=True)
        assert _decide(state) is _V.MARK

    def test_liveness_age_boundary_is_inclusive_at_600s(self) -> None:
        at_limit = _proven_state(liveness_line_last_ns=_NOW_NS - LIVENESS_MAX_AGE_NS)
        assert _decide(at_limit) is _V.MARK
        past = _proven_state(liveness_line_last_ns=_NOW_NS - LIVENESS_MAX_AGE_NS - 1)
        assert _decide(past) is _V.NO_FRESH_ACTIVITY

    def test_liveness_line_older_than_log_spawn_stamp_is_not_fresh(self) -> None:
        state = _proven_state(liveness_line_last_ns=_NOW_NS - 30 * _NS)
        assert _decide(state, log_spawned_at=_utc(19, 59, 45)) is _V.NO_FRESH_ACTIVITY

    def test_is_deferral_is_exactly_the_eight_counted_members(self) -> None:
        counted = {
            _V.HOLDER_UNPROVEN,
            _V.PERMIT_ABSENT,
            _V.NOT_SUBSCRIBED,
            _V.ANCHOR_UNKNOWN,
            _V.LOG_UNKNOWN,
            _V.LOG_NOT_CURRENT_DAY,
            _V.NO_FRESH_ACTIVITY,
            _V.IO_ERROR,
        }
        assert {v for v in _V if is_deferral(v)} == counted
        assert not is_deferral(_V.NOT_REQUIRED)
        assert not is_deferral(_V.MARK)

    def test_decide_ready_adoption_window_boundaries(self) -> None:
        """T2"""
        for outside in (_utc(16, 45), _utc(17, 5), _utc(17, 9, 59)):
            assert _decide(now=outside) is _V.NOT_IN_WINDOW
        assert _decide(now=_utc(17, 10), now_ns=int(_utc(17, 10).timestamp()) * _NS) is not (
            _V.NOT_IN_WINDOW
        )
        last = _utc(0, 59, 59, day=_DAY + dt.timedelta(days=1))
        assert _decide(now=last) is not _V.NOT_IN_WINDOW
        close = _utc(1, 0, day=_DAY + dt.timedelta(days=1))
        assert _decide(now=close) is _V.NOT_IN_WINDOW

    def test_ready_adoption_keys_on_readiness_not_launch_done(self) -> None:
        """T3"""
        assert _decide(_proven_state(launch_done=True, readiness_observed=False)) is _V.MARK
        assert _decide(_proven_state(launch_done=True, readiness_observed=True)) is _V.ALREADY_READY

    def test_permit_unexpired_alone_does_not_prove_current_day(self) -> None:
        """T7"""
        state = _proven_state(permit_issued_seen_expires_at_ns=_NOW_NS + 3600 * _NS)
        now = _utc(17, 30)
        verdict = _decide(
            state, now=now, now_ns=int(now.timestamp()) * _NS, log_spawned_at=_utc(10, 0)
        )
        assert verdict is _V.LOG_NOT_CURRENT_DAY

    def test_log_not_current_day_is_a_counted_deferral(self) -> None:
        """T7e: a D-1 node after a restart pages (WARN at 5, CRITICAL at 12)."""
        state = _proven_state()
        d_minus_1 = _utc(16, 50, day=_DAY - dt.timedelta(days=1))
        alerts = {}
        for poll in range(1, 13):
            now = _utc(20, 0) + dt.timedelta(seconds=60 * poll)
            verdict = _decide(
                state, now=now, now_ns=int(now.timestamp()) * _NS, log_spawned_at=d_minus_1
            )
            assert verdict is _V.LOG_NOT_CURRENT_DAY
            assert is_deferral(verdict)
            state = record_ready_adoption_deferral(state, now)
            spec = decide_ready_adoption_alert(state)
            if spec is not None:
                alerts[poll] = spec.severity
                state = record_ready_adoption_alert_sent(
                    state, now, critical=spec.severity == "CRITICAL"
                )
        assert alerts == {5: "WARN", 12: "CRITICAL"}


class TestRecordReadyAdoption:
    def test_record_ready_adoption_sets_both_latches_and_nothing_else(self) -> None:
        """T4"""
        state = _proven_state(
            relaunch_attempts=1,
            self_check_done=True,
            ready_adoption_deferral_polls=7,
            ready_adoption_critical_last_poll=6,
            ready_adoption_warn_sent=True,
            permit_alert_last_capability="absent",
            midday_alert_sent=True,
        )
        marked = record_ready_adoption(state, _NOW)
        assert marked.launch_done is True
        assert marked.readiness_observed is True
        assert marked.ready_adoption_deferral_polls == 0
        assert marked.ready_adoption_critical_last_poll is None
        assert marked == replace(
            state,
            launch_done=True,
            readiness_observed=True,
            ready_adoption_deferral_polls=0,
            ready_adoption_critical_last_poll=None,
        )
        assert marked.ready_adoption_warn_sent is True
        assert record_ready_adoption(marked, _NOW) == marked  # idempotent

    def test_record_ready_adoption_is_trading_day_scoped(self) -> None:
        later = _utc(20, 0, day=_DAY + dt.timedelta(days=1))
        rolled = record_ready_adoption(_proven_state(), later)
        assert rolled.day == _DAY + dt.timedelta(days=1)
        assert rolled.liveness_line_last_ns is None

    def test_record_child_adopted_clears_ready_adoption_fields(self) -> None:
        """T5: the five per-child fields clear; rollover resets them too."""
        dirty = _proven_state(
            ready_adoption_deferral_polls=9,
            ready_adoption_warn_sent=True,
            ready_adoption_critical_last_poll=8,
            ready_adoption_terminal_logged=True,
        )
        adopted = record_child_adopted(dirty, _NOW)
        assert adopted.liveness_line_last_ns is None
        assert adopted.ready_adoption_deferral_polls == 0
        assert adopted.ready_adoption_warn_sent is False
        assert adopted.ready_adoption_critical_last_poll is None
        assert adopted.ready_adoption_terminal_logged is False
        names = {f.name for f in fields(DaySchedulerState)}
        assert {
            "liveness_line_last_ns",
            "ready_adoption_deferral_polls",
            "ready_adoption_warn_sent",
            "ready_adoption_critical_last_poll",
            "ready_adoption_terminal_logged",
        } <= names
        next_day = _utc(20, 0, day=_DAY + dt.timedelta(days=1))
        rolled = reset_ready_adoption_deferral(dirty, next_day)
        assert rolled == initial_scheduler_state(_DAY + dt.timedelta(days=1))


class TestNodeLogName:
    def test_node_log_spawned_at_parses_node_stamp_only(self) -> None:
        """T6"""
        assert node_log_spawned_at("breezy-trade-20260925T165012Z.log") == dt.datetime(
            2026, 9, 25, 16, 50, 12, tzinfo=dt.UTC
        )
        for other in (
            "breezy-trade-supervisor.log",
            "breezy-trade-supervisor-stdout-20260925T165012Z.log",
            "breezy-trade-supervisor.launch-20260925T165012Z.log",
            "breezy-trade-20261340T165012Z.log",  # impossible date
            "",
        ):
            assert node_log_spawned_at(other) is None, other

    def test_node_log_name_re_matches_identically_to_frozen_r1_literal(self) -> None:
        """T6b"""
        frozen = re.compile(r"^breezy-trade-\d{8}T\d{6}Z\.log$")
        corpus = [
            "breezy-trade-20260925T165012Z.log",
            "breezy-trade-20260101T000000Z.log",
            "breezy-trade-20261231T235959Z.log",
            "breezy-trade-20261001T151202Z.log",
            "breezy-trade-supervisor.log",
            "breezy-trade-supervisor-20260925T165012Z.log",
            "breezy-trade-supervisor-stdout-20260925T165012Z.log",
            "breezy-trade-supervisor.launch-20260925T165012Z.log",
            "breezy-trade-20260925T165012Z.log\n",
            "breezy-trade-20260925T165012Z.log.1",
            "breezy-trade-2026092T165012Z.log",
            "breezy-trade-202609255T165012Z.log",
            "breezy-trade-20260925T16501Z.log",
            "breezy-trade-20260925T1650123Z.log",
            "breezy-trade-20260925T165012.log",
            "xbreezy-trade-20260925T165012Z.log",
            "breezy-trade-.log",
            "breezy-trade.log",
            "",
            "breezy-trade-20260925T165012Z.LOG",
        ]
        for name in corpus:
            assert bool(NODE_LOG_NAME_RE.match(name)) == bool(frozen.match(name)), name
        assert NODE_LOG_NAME_RE.pattern == r"^breezy-trade-(\d{8}T\d{6}Z)\.log$"
        match = NODE_LOG_NAME_RE.match("breezy-trade-20260925T165012Z.log")
        assert match is not None
        assert match.group(1) == "20260925T165012Z"


class TestLatestLivenessLine:
    def test_latest_liveness_line_ns(self) -> None:
        """T7b"""
        at = _NOW_NS - 10 * _NS
        verbatim = (
            "\x1b[1m2026-10-03T16:39:02.215766648Z\x1b[0m [INFO] "
            "BREEZY-L001.FORECAST-QUANTILE-LADDER: SHADOW_DECISION {'x': 1}\n"
        )
        verbatim_ns = int(dt.datetime(2026, 10, 3, 16, 39, 2, tzinfo=dt.UTC).timestamp()) * _NS
        assert (
            latest_liveness_line_ns(verbatim, now_ns=verbatim_ns + 5 * _NS)
            == verbatim_ns + 215766648
        )
        two = _shadow_line(at - 5 * _NS) + _shadow_line(at)
        assert latest_liveness_line_ns(two, now_ns=_NOW_NS) == at
        assert latest_liveness_line_ns(_shadow_line(at, ansi=False), now_ns=_NOW_NS) == at
        reconnect = "2026-09-25T20:00:00.000000000Z [WARN] websocket: reconnecting\n"
        assert latest_liveness_line_ns(reconnect + "ERROR boom\n", now_ns=_NOW_NS) is None
        truncation = _nautilus_prefix(at) + " [WARN] data: 3 book level(s) discarded so far\n"
        assert latest_liveness_line_ns(truncation, now_ns=_NOW_NS) is None
        assert latest_liveness_line_ns("", now_ns=_NOW_NS) is None

    def test_liveness_scan_skips_headless_last_occurrence(self) -> None:
        """SL1 (i)-(iv)"""
        good = _shadow_line(_NOW_NS - 20 * _NS)
        headless = "ISION {'k': 1} tail SHADOW_DECISION {'cut': 1}\n"
        # (i) text starts mid-line; the LAST occurrence is headless
        headless_last = good + "  garbage SHADOW_DECISION {'cut': 1}\n"
        assert latest_liveness_line_ns(headless_last, now_ns=_NOW_NS) == _NOW_NS - 20 * _NS
        # the first line of a delta is headless, the earlier-parseable rule still holds
        assert latest_liveness_line_ns(headless + good, now_ns=_NOW_NS) == _NOW_NS - 20 * _NS
        # (ii) every occurrence headless
        assert latest_liveness_line_ns(headless * 3, now_ns=_NOW_NS) is None
        cut = "cut-prefix SHADOW_DECISION {'a': 1}\n"
        # (iii) 64 headless after one parseable -> parseable is the 65th: None
        n = LIVENESS_SCAN_MAX_OCCURRENCES
        assert latest_liveness_line_ns(good + cut * n, now_ns=_NOW_NS) is None
        # (iv) 63 headless after one parseable -> the 64th from the end: found
        assert latest_liveness_line_ns(good + cut * (n - 1), now_ns=_NOW_NS) == _NOW_NS - 20 * _NS

    def test_future_stamped_lines_are_unparseable(self) -> None:
        """T7b (v)-(vii): future-skew rejection at latch time."""
        old = _NOW_NS - 30 * _NS
        future = _NOW_NS + 3600 * _NS
        # (v)
        text = _shadow_line(old) + _shadow_line(future)
        assert latest_liveness_line_ns(text, now_ns=_NOW_NS) == old
        # (vi) boundary inclusive at +60 s, rejected one ns later
        edge = _NOW_NS + LIVENESS_MAX_FUTURE_SKEW_NS
        assert latest_liveness_line_ns(_shadow_line(edge), now_ns=_NOW_NS) == edge
        assert latest_liveness_line_ns(_shadow_line(edge + 1), now_ns=_NOW_NS) is None
        # (vii)
        assert latest_liveness_line_ns(_shadow_line(future) * 2, now_ns=_NOW_NS) is None

    def test_latch_log_facts_records_liveness_max_wins(self) -> None:
        """T7c"""
        state = initial_scheduler_state(_DAY)
        newer = _NOW_NS - 5 * _NS
        state = latch_log_facts(state, _NOW, _shadow_line(newer))
        assert state.liveness_line_last_ns == newer
        state = latch_log_facts(state, _NOW, _shadow_line(newer - 60 * _NS))
        assert state.liveness_line_last_ns == newer
        assert record_liveness_line_seen(state, _NOW, newer - 1).liveness_line_last_ns == newer
        plain = latch_log_facts(initial_scheduler_state(_DAY), _NOW, "nothing to see\n")
        assert plain == initial_scheduler_state(_DAY)


class TestReadyAdoptionAlert:
    def test_decide_ready_adoption_alert_thresholds_dedupe_and_refire(self) -> None:
        """T7d: 4 none; 5 WARN; 12 CRITICAL; 72, 132 re-fire; reset; new child."""

        def run(
            state: DaySchedulerState, polls: int, *, send: bool = True
        ) -> tuple[DaySchedulerState, dict[int, tuple[str, AlertDetail]]]:
            fired: dict[int, tuple[str, AlertDetail]] = {}
            for poll in range(1, polls + 1):
                state = record_ready_adoption_deferral(state, _NOW)
                spec = decide_ready_adoption_alert(state)
                if spec is not None:
                    assert spec.event == READY_ADOPTION_ALERT_EVENT
                    fired[poll] = (spec.severity, spec.detail)
                    if send:
                        state = record_ready_adoption_alert_sent(
                            state, _NOW, critical=spec.severity == "CRITICAL"
                        )
            return state, fired

        state, fired = run(initial_scheduler_state(_DAY), 140)
        assert fired == {
            5: ("WARN", AlertDetail.READY_ADOPTION_DEFERRED),
            12: ("CRITICAL", AlertDetail.READY_ADOPTION_UNPROVEN),
            72: ("CRITICAL", AlertDetail.READY_ADOPTION_UNPROVEN),
            132: ("CRITICAL", AlertDetail.READY_ADOPTION_UNPROVEN),
        }
        # terminal interlude: counter and re-fire anchor reset, WARN stays latched
        state = reset_ready_adoption_deferral(state, _NOW)
        assert state.ready_adoption_deferral_polls == 0
        assert state.ready_adoption_critical_last_poll is None
        assert state.ready_adoption_warn_sent is True
        _, fired = run(state, 12)
        assert fired == {12: ("CRITICAL", AlertDetail.READY_ADOPTION_UNPROVEN)}
        # a new child gets a fresh budget: WARN again at 5
        _, fired = run(record_child_adopted(state, _NOW), 5)
        assert fired == {5: ("WARN", AlertDetail.READY_ADOPTION_DEFERRED)}

    def test_unlatched_critical_is_due_again_on_the_next_poll(self) -> None:
        state = initial_scheduler_state(_DAY)
        for _ in range(12):
            state = record_ready_adoption_deferral(state, _NOW)
        first = decide_ready_adoption_alert(state)
        assert first is not None and first.severity == "CRITICAL"
        # the send failed: nothing latched, so it is due again after one more poll
        state = record_ready_adoption_deferral(state, _NOW)
        again = decide_ready_adoption_alert(state)
        assert again is not None and again.severity == "CRITICAL"

    def test_flapping_worst_case_arithmetic_is_visible(self) -> None:
        """T7d note: a terminal verdict every 13th poll over a 470-minute
        window is the bound the code comment cites (36 CRITICALs)."""
        assert 470 // 13 == 36
        doc = inspect.getdoc(decide_ready_adoption_alert) or ""
        assert "36" in doc and "470" in doc
