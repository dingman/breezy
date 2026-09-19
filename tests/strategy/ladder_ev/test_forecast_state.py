"""ForecastState.value_at — in-memory PIT visibility (WP-10; actor-push comes in WP-12)."""

from __future__ import annotations


def test_value_at_is_none_before_any_push() -> None:
    from breezy.strategy.ladder_ev.forecast_state import ForecastState

    state = ForecastState()
    assert state.value_at(1_000) is None


def test_value_at_returns_the_latest_visible_txn() -> None:
    from breezy.strategy.ladder_ev.forecast_state import ForecastState

    state = ForecastState()
    state.push(value_f=91.0, available_at_ns=100, cycle_runtime_ns=50)
    state.push(value_f=93.0, available_at_ns=200, cycle_runtime_ns=150)
    assert state.value_at(150) is not None
    assert state.value_at(150).value_f == 91.0
    assert state.value_at(200) is not None
    assert state.value_at(200).value_f == 93.0
    assert state.value_at(199) is not None
    assert state.value_at(199).value_f == 91.0


def test_value_at_never_uses_a_not_yet_available_point() -> None:
    from breezy.strategy.ladder_ev.forecast_state import ForecastState

    state = ForecastState()
    state.push(value_f=88.0, available_at_ns=500, cycle_runtime_ns=400)
    assert state.value_at(499) is None
