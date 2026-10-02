"""Point-in-time guard: a record available only after the decision is refused.

Equality is available, not look-ahead (AUD-11 §6 item 1). A missing or
non-integer ``ts_init`` fails closed and is reported with the other offenders.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from breezy.runtime.point_in_time_guard import (
    LookAheadRecordError,
    assert_available_before_decision,
)

_DECISION_NS = 1_700_000_000_000_000_000


def _record(ts_init: object) -> SimpleNamespace:
    return SimpleNamespace(ts_init=ts_init)


def test_a_record_after_the_decision_instant_is_refused() -> None:
    late = _record(_DECISION_NS + 1)
    with pytest.raises(LookAheadRecordError) as caught:
        assert_available_before_decision(
            [late],
            decision_ts_init_ns=_DECISION_NS,
            context="unit",
        )
    assert caught.value.offending_records == (late,)
    assert str(_DECISION_NS) in str(caught.value)
    assert str(late.ts_init) in str(caught.value)


def test_a_record_at_the_decision_instant_is_available() -> None:
    """Equal ``ts_init`` is the decision instant itself, not look-ahead."""
    at_decision = _record(_DECISION_NS)
    assert_available_before_decision(
        [at_decision],
        decision_ts_init_ns=_DECISION_NS,
        context="unit-equality",
    )


def test_one_exception_carries_every_offender_in_input_order() -> None:
    early = _record(_DECISION_NS - 5)
    late_a = _record(_DECISION_NS + 2)
    at_decision = _record(_DECISION_NS)
    late_b = _record(_DECISION_NS + 9)
    with pytest.raises(LookAheadRecordError) as caught:
        assert_available_before_decision(
            [early, late_a, at_decision, late_b],
            decision_ts_init_ns=_DECISION_NS,
            context="unit-aggregate",
        )
    assert caught.value.offending_records == (late_a, late_b)
    assert len(caught.value.offending_records) == 2


def test_a_record_without_an_integer_ts_init_fails_closed() -> None:
    missing = SimpleNamespace()
    bogus = _record("not-a-timestamp")
    ok = _record(_DECISION_NS)
    with pytest.raises(LookAheadRecordError) as caught:
        assert_available_before_decision(
            [ok, missing, bogus],
            decision_ts_init_ns=_DECISION_NS,
            context="unit-fail-closed",
        )
    assert caught.value.offending_records == (missing, bogus)


def test_known_tape_retrieval_after_the_last_decision_instant_is_refused() -> None:
    """The 2026-08-30 tape: last decision ~16:11:54Z, retrieval hours later.

    This is the documenting assertion's known gap, not a live catalog read.
    """
    last_market_data_ns = int(
        dt.datetime(2026, 8, 30, 16, 11, 53, tzinfo=dt.UTC).timestamp() * 1_000_000_000
    )
    decision_ns = last_market_data_ns + 1_000_000_000
    retrieved_ns = int(
        dt.datetime(2026, 8, 30, 20, 40, tzinfo=dt.UTC).timestamp() * 1_000_000_000
    )
    late = _record(retrieved_ns)
    with pytest.raises(LookAheadRecordError) as caught:
        assert_available_before_decision(
            [late],
            decision_ts_init_ns=decision_ns,
            context="paper_replay.main default branch",
        )
    assert caught.value.offending_records == (late,)
    assert len(caught.value.offending_records) == 1
