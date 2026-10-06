"""AUT-2 r7 WP5 / section 3.9 (Z19): the open intent after STOP."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from breezy.analysis.labeling.prelaunch_intents import (
    IntentObservation,
    observe_open_intent_post_stop,
    reconstruct_open_intent_at,
    z19_alerts,
    z19_counts,
    z19_line,
    z19_observation_for_day,
)
from breezy.runtime.submit_intent import RetirementReason, SubmitIntent, SubmitIntentState

T = 1_790_000_000_000_000_000
_H = 3_600_000_000_000


def _intent(
    *,
    created: int = T,
    state: SubmitIntentState = SubmitIntentState.OPEN,
    retired: int | None = None,
    intent_id: str = "intent-1",
) -> SubmitIntent:
    retired_state = state is SubmitIntentState.RETIRED
    return SubmitIntent(
        intent_id=intent_id,
        fingerprint="f" * 64,
        created_ns=created,
        state=state,
        retired_ns=retired if retired_state else None,
        retirement_reason=RetirementReason.OPERATOR_CLEARED if retired_state else None,
    )


def _retired(created: int, retired: int, intent_id: str = "intent-1") -> SubmitIntent:
    return _intent(
        created=created, state=SubmitIntentState.RETIRED, retired=retired, intent_id=intent_id
    )


def _observe(current: SubmitIntent | None, **kw: Any) -> IntentObservation:
    return observe_open_intent_post_stop(
        stop_signal_present=kw.pop("stop", True),
        node_pid=kw.pop("pid", lambda: None),
        read_current=lambda: current,
        **kw,
    )


def test_post_stop_observation_records_open_intent_at_poststop() -> None:
    assert _observe(None) is IntentObservation.NONE
    assert _observe(_retired(T, T + _H)) is IntentObservation.NONE
    assert _observe(_intent()) is IntentObservation.OPEN
    assert _observe(_intent(), is_ambiguous=lambda i: True) is IntentObservation.AMBIGUOUS


def test_missing_post_stop_run_reports_unknown() -> None:
    assert _observe(_intent(), stop=False) is IntentObservation.UNKNOWN
    assert _observe(None, pid=lambda: 4242) is IntentObservation.UNKNOWN  # a live node
    observed = {"2026-10-01": IntentObservation.OPEN}
    assert z19_observation_for_day("2026-10-01", observed) is IntentObservation.OPEN
    assert z19_observation_for_day("2026-10-02", observed) is IntentObservation.UNKNOWN

    def _raises() -> SubmitIntent | None:
        raise OSError("unreadable")

    assert (
        observe_open_intent_post_stop(
            stop_signal_present=True, node_pid=lambda: None, read_current=_raises
        )
        is IntentObservation.UNKNOWN
    )


def test_rewritten_created_ns_reports_unknown() -> None:
    clean = [_retired(T, T + 2 * _H)]
    rewritten = [replace(_retired(T, T + 2 * _H), created_ns=T + 3 * _H)]
    disagreeing = [_retired(T, T + _H), _retired(T + _H, T + 2 * _H)]

    assert reconstruct_open_intent_at(clean, T + _H) is IntentObservation.OPEN
    assert reconstruct_open_intent_at(clean, T + 3 * _H) is IntentObservation.NONE
    assert reconstruct_open_intent_at(clean, T - _H) is IntentObservation.NONE
    assert reconstruct_open_intent_at(rewritten, T + _H) is IntentObservation.UNKNOWN
    assert reconstruct_open_intent_at(disagreeing, T) is IntentObservation.UNKNOWN


def test_z19_unknown_is_metric_not_alert() -> None:
    counts = z19_counts(
        [
            IntentObservation.NONE,
            IntentObservation.OPEN,
            IntentObservation.AMBIGUOUS,
            IntentObservation.UNKNOWN,
            IntentObservation.UNKNOWN,
        ]
    )

    assert (counts.days_open, counts.n, counts.ambiguous, counts.unknown) == (2, 5, 1, 2)
    assert z19_line(counts) == "Z19 open_intent_at_poststop days=2/5 ambiguous=1 unknown=2"
    assert z19_alerts(counts) == ()
