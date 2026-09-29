"""ForecastQuantileState — SL-12: scalar TXN -> quantile vector per (station, cycle).

Mirrors ``test_forecast_state.py``'s own visibility-gate shape, widened to a
7-variable vector (TXN_Q10..Q90, TXN_MEAN, TXN_SD). A vector becomes visible
only once ALL 7 variables for that cycle have arrived AND ``now_ns`` is at or
after the vector's own vintage (the max of the 7 variables' own
``available_at_ns``) — never a partial vector, never interpolated, never a
future vintage.

``ForecastState`` itself (the scalar TXN path) is untouched by this slice;
``test_forecast_state.py`` stays green unchanged.
"""

from __future__ import annotations

from breezy.strategy.ladder_ev.forecast_state import (
    NBP_QUANTILE_VARIABLES,
    ForecastQuantileState,
)

_Q10, _Q25, _Q50, _Q75, _Q90, _MEAN, _SD = NBP_QUANTILE_VARIABLES


def _push_all(
    state: ForecastQuantileState,
    *,
    cycle_runtime_ns: int,
    available_at_ns: int,
    base: float = 80.0,
) -> None:
    values = {
        _Q10: base - 4.0,
        _Q25: base - 2.0,
        _Q50: base,
        _Q75: base + 2.0,
        _Q90: base + 4.0,
        _MEAN: base,
        _SD: 2.5,
    }
    for variable, value_f in values.items():
        state.push(
            variable=variable,
            value_f=value_f,
            available_at_ns=available_at_ns,
            cycle_runtime_ns=cycle_runtime_ns,
        )


def test_the_closed_quantile_alphabet_has_exactly_seven_members() -> None:
    assert NBP_QUANTILE_VARIABLES == (
        "TXN_Q10",
        "TXN_Q25",
        "TXN_Q50",
        "TXN_Q75",
        "TXN_Q90",
        "TXN_MEAN",
        "TXN_SD",
    )


def test_value_at_is_none_before_any_push() -> None:
    state = ForecastQuantileState()
    assert state.value_at(1_000) is None


def test_a_partial_vector_is_never_visible_even_after_its_vintage() -> None:
    """Six of seven variables arrive; the vector must stay invisible."""
    state = ForecastQuantileState()
    for variable in NBP_QUANTILE_VARIABLES[:-1]:
        state.push(variable=variable, value_f=80.0, available_at_ns=100, cycle_runtime_ns=50)

    assert state.value_at(10_000) is None


def test_the_vector_becomes_visible_once_all_seven_arrive_and_now_covers_the_vintage() -> None:
    state = ForecastQuantileState()
    _push_all(state, cycle_runtime_ns=50, available_at_ns=100)

    assert state.value_at(99) is None
    vector = state.value_at(100)
    assert vector is not None
    assert vector.q10 == 76.0
    assert vector.q25 == 78.0
    assert vector.q50 == 80.0
    assert vector.q75 == 82.0
    assert vector.q90 == 84.0
    assert vector.mean == 80.0
    assert vector.sd == 2.5
    assert vector.cycle_runtime_ns == 50


def test_the_vectors_vintage_is_the_max_of_its_sevens_own_available_at_ns() -> None:
    """One late-arriving variable in the set delays the WHOLE vector's visibility."""
    state = ForecastQuantileState()
    early = NBP_QUANTILE_VARIABLES[:-1]
    for variable in early:
        state.push(variable=variable, value_f=80.0, available_at_ns=100, cycle_runtime_ns=50)
    late_variable = NBP_QUANTILE_VARIABLES[-1]
    state.push(variable=late_variable, value_f=2.5, available_at_ns=250, cycle_runtime_ns=50)

    assert state.value_at(200) is None
    vector = state.value_at(250)
    assert vector is not None
    assert vector.available_at_ns == 250


def test_a_later_complete_cycle_supersedes_an_earlier_complete_one() -> None:
    state = ForecastQuantileState()
    _push_all(state, cycle_runtime_ns=50, available_at_ns=100, base=80.0)
    _push_all(state, cycle_runtime_ns=150, available_at_ns=200, base=90.0)

    vector = state.value_at(200)
    assert vector is not None
    assert vector.cycle_runtime_ns == 150
    assert vector.q50 == 90.0


def test_pushing_an_unknown_variable_is_refused() -> None:
    import pytest

    state = ForecastQuantileState()
    with pytest.raises(ValueError, match="TMP"):
        state.push(variable="TMP", value_f=1.0, available_at_ns=1, cycle_runtime_ns=1)


def test_pushing_a_none_value_is_a_no_op_not_a_stored_absence() -> None:
    state = ForecastQuantileState()
    for variable in NBP_QUANTILE_VARIABLES:
        state.push(variable=variable, value_f=None, available_at_ns=100, cycle_runtime_ns=50)

    assert state.value_at(10_000) is None
