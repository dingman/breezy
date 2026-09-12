"""RED/GREEN coverage for `decide_node_liveness`/`NodeLivenessState`
(SP-6 A11 pure core, part of the process_probe/node_expected_alive
increment)."""

from __future__ import annotations

import datetime as dt

from breezy.runtime.trade_supervisor_core import NodeLivenessState, decide_node_liveness

_ALIVE_EXPECTED_INSTANT = dt.datetime(2026, 9, 12, 2, 0, tzinfo=dt.UTC)
_NOT_ALIVE_EXPECTED_INSTANT = dt.datetime(2026, 9, 12, 16, 45, tzinfo=dt.UTC)


def test_node_present_rearms_and_never_alerts() -> None:
    state = NodeLivenessState(consecutive_absent=5, alerted=True)

    new_state, should_alert = decide_node_liveness(
        now_utc=_ALIVE_EXPECTED_INSTANT, node_present=True, state=state
    )

    assert new_state == NodeLivenessState()
    assert should_alert is False


def test_absence_inside_the_expected_stop_window_never_alerts() -> None:
    new_state, should_alert = decide_node_liveness(
        now_utc=_NOT_ALIVE_EXPECTED_INSTANT,
        node_present=False,
        state=NodeLivenessState(),
    )

    assert new_state == NodeLivenessState()
    assert should_alert is False


def test_absence_confirmed_by_two_consecutive_passes_alerts_once() -> None:
    state = NodeLivenessState()

    state, first_alert = decide_node_liveness(
        now_utc=_ALIVE_EXPECTED_INSTANT, node_present=False, state=state
    )
    assert first_alert is False
    assert state.consecutive_absent == 1

    state, second_alert = decide_node_liveness(
        now_utc=_ALIVE_EXPECTED_INSTANT, node_present=False, state=state
    )
    assert second_alert is True
    assert state.consecutive_absent == 2
    assert state.alerted is True


def test_a_standing_absence_alerts_once_not_every_pass() -> None:
    state = NodeLivenessState()
    alerts = []
    for _ in range(5):
        state, fired = decide_node_liveness(
            now_utc=_ALIVE_EXPECTED_INSTANT, node_present=False, state=state
        )
        alerts.append(fired)

    assert alerts == [False, True, False, False, False]


def test_confirm_after_is_configurable() -> None:
    state = NodeLivenessState()
    state, fired_at_one = decide_node_liveness(
        now_utc=_ALIVE_EXPECTED_INSTANT,
        node_present=False,
        state=state,
        confirm_after=1,
    )

    assert fired_at_one is True
