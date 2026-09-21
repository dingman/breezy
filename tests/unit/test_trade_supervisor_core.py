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

import inspect

from breezy.runtime.trade_supervisor_core import (
    DaySchedulerState,
    SelfCheckEscalationState,
    SelfCheckResult,
    decode_self_check_escalation_state,
    encode_self_check_escalation_state,
    escalated_self_check_severity,
    record_self_check_result,
)

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
