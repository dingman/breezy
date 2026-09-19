"""Executable CAUSAL proof that the take/refuse decision is driven by its
probability input, not by hard-coding, stale state, or an accidental path.

Characterizes EXISTING behaviour of the pure core
(``src/breezy/strategy/current_rung_hold/decision.py``) and its binding to
the live sending family (``ContinuousRungHoldStrategy`` ->
``tick_eval.evaluate_both_sides`` -> ``evaluate_decision``).

The break-even oracle here is RECOMPUTED from price and fee coefficient
(:func:`_expected_break_even`) rather than imported from production, so a
production drift in ``decision._fee``'s formula or rounding fails these
tests instead of silently agreeing with them.

The sole probability input is ``P_HOLD_LOWER.get(key)``; to hold EVERY other
``DecisionInputs`` field constant while sweeping it, these tests monkeypatch
``decision.P_HOLD_LOWER`` (the module global the function actually reads) --
never the frozen ``archive_table`` corpus itself.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import inspect
from decimal import ROUND_HALF_EVEN, Decimal

import pytest

from breezy.strategy.current_rung_hold import continuous_strategy as continuous_strategy_module
from breezy.strategy.current_rung_hold import decision as decision_module
from breezy.strategy.current_rung_hold import tick_eval as tick_eval_module
from breezy.strategy.current_rung_hold.config import CurrentRungHoldConfig
from breezy.strategy.current_rung_hold.continuous_strategy import ContinuousRungHoldStrategy
from breezy.strategy.current_rung_hold.decision import (
    DecisionInputs,
    Refuse,
    Take,
    evaluate_decision,
)
from breezy.strategy.current_rung_hold.strategy import (
    _WINDOW_END_HOUR_LST,
    _WINDOW_START_HOUR_LST,
)
from breezy.strategy.weather_common.running_extreme import RunningMax

_LADDER: tuple[tuple[int | None, int | None], ...] = ((None, 69), (70, 71), (72, None))

_STATION = "LAX"
_SEASON = "DJF"
_HOUR_LST = 12
_INTERIOR_WIDTH_CODE = 0
_M_ZERO = 0
_CLIMATE_DAY = dt.date(2026, 1, 15)

#: The frozen table's lookup key for every input built below.
_KEY: tuple[str, str, int, int, int] = (
    _STATION,
    _SEASON,
    _HOUR_LST,
    _INTERIOR_WIDTH_CODE,
    _M_ZERO,
)

_STALE_BOUND_NS = 50 * 60 * 1_000_000_000
_CENT = Decimal("0.01")


def _expected_break_even(price: Decimal, fee_coefficient: Decimal) -> Decimal:
    """``price + round_half_even(theta * price * (1 - price), cent)``.

    Recomputed here from the documented formula -- deliberately NOT
    ``decision._fee`` -- so this is a real oracle for the production rule.
    """
    fee = (fee_coefficient * price * (Decimal(1) - price)).quantize(
        _CENT, rounding=ROUND_HALF_EVEN
    )
    return price + fee


def _exact_running_max(reading_f: int) -> RunningMax:
    return RunningMax(
        lower_f=reading_f,
        upper_f=reading_f,
        exact_f=reading_f,
        source_observed_at_ns=0,
        source_received_at_ns=0,
    )


def _causal_inputs(**overrides: object) -> DecisionInputs:
    """A clean, executable YES snapshot with every non-probability field fixed."""
    base = DecisionInputs(
        station=_STATION,
        climate_day=_CLIMATE_DAY,
        now_ns=1_000_000_000,
        ladder=_LADDER,
        fee_coefficient=Decimal("0.06"),
        ask=Decimal("0.40"),
        size=5,
        running_max=_exact_running_max(70),
        staleness_ns=0,
        config=CurrentRungHoldConfig(),
        season=_SEASON,
        hour_lst=_HOUR_LST,
        width_code=_INTERIOR_WIDTH_CODE,
        m_code=_M_ZERO,
        latch_consumed=False,
    )
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


def _pin_probability(
    monkeypatch: pytest.MonkeyPatch,
    p_hold_lower: Decimal | None,
    *,
    key: tuple[str, str, int, int, int] = _KEY,
) -> None:
    """Make ``p_hold_lower`` the ONLY probability ``evaluate_decision`` can see."""
    monkeypatch.setattr(decision_module, "P_HOLD_LOWER", {key: p_hold_lower})


# --------------------------------------------------------------------------
# 1. Monotone causal sweep across the break-even boundary.
# --------------------------------------------------------------------------


def test_the_decision_flips_refuse_to_take_exactly_at_the_recomputed_break_even(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sweeping ONLY the probability flips REFUSE->TAKE at ``p > price + fee``."""
    ask = Decimal("0.40")
    theta = Decimal("0.06")
    expected_break_even = _expected_break_even(ask, theta)
    assert expected_break_even == Decimal("0.41")  # 0.06*0.40*0.60 = 0.0144 -> $0.01

    taken: list[Decimal] = []
    refused: list[Decimal] = []
    for step in range(31):  # 0.30 .. 0.60 inclusive, spanning the boundary
        p_hold_lower = Decimal("0.30") + Decimal(step) * _CENT
        _pin_probability(monkeypatch, p_hold_lower)
        outcome = evaluate_decision(_causal_inputs(ask=ask, fee_coefficient=theta))
        # The oracle: take IFF p strictly exceeds the INDEPENDENTLY recomputed
        # break-even -- never a table constant, never a production import.
        if p_hold_lower > expected_break_even:
            assert isinstance(outcome, Take), f"expected Take at p={p_hold_lower}"
            assert outcome.p_hold_lower == p_hold_lower
            assert outcome.break_even == expected_break_even
            taken.append(p_hold_lower)
        else:
            assert outcome == Refuse(
                "edge_below_break_even",
                p_bound=p_hold_lower,
                break_even=expected_break_even,
            ), f"expected Refuse at p={p_hold_lower}"
            refused.append(p_hold_lower)

    # Monotone single flip: every refusal is below every take.
    assert refused and taken
    assert max(refused) < min(taken)
    assert max(refused) == expected_break_even  # equality refuses (strict `>`)
    assert min(taken) == expected_break_even + _CENT


def test_a_probability_strictly_below_the_boundary_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_probability(monkeypatch, Decimal("0.40"))
    outcome = evaluate_decision(_causal_inputs())
    assert outcome == Refuse(
        "edge_below_break_even", p_bound=Decimal("0.40"), break_even=Decimal("0.41")
    )


def test_a_probability_strictly_above_the_boundary_takes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pin_probability(monkeypatch, Decimal("0.42"))
    outcome = evaluate_decision(_causal_inputs())
    assert outcome == Take(
        quantity=1,
        limit_price=Decimal("0.40"),
        p_hold_lower=Decimal("0.42"),
        break_even=_expected_break_even(Decimal("0.40"), Decimal("0.06")),
        rung=(70, 71),
    )


def test_an_undefined_table_cell_refuses_rather_than_defaulting_to_a_take(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No probability => no take: the decision is never made without the input."""
    monkeypatch.setattr(decision_module, "P_HOLD_LOWER", {})
    assert evaluate_decision(_causal_inputs()) == Refuse("p_hold_undefined")
    _pin_probability(monkeypatch, None)
    assert evaluate_decision(_causal_inputs()) == Refuse("p_hold_undefined")


# --------------------------------------------------------------------------
# 2. Price and fee causality, probability held constant.
# --------------------------------------------------------------------------


def test_raising_the_ask_flips_a_take_into_a_refusal_at_a_fixed_probability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Higher price, same probability => the edge disappears (correct direction)."""
    p_hold_lower = Decimal("0.60")
    _pin_probability(monkeypatch, p_hold_lower)

    cheap_ask = Decimal("0.40")
    dear_ask = Decimal("0.70")
    assert p_hold_lower > _expected_break_even(cheap_ask, Decimal("0.06"))
    assert p_hold_lower <= _expected_break_even(dear_ask, Decimal("0.06"))

    cheap = evaluate_decision(_causal_inputs(ask=cheap_ask))
    dear = evaluate_decision(_causal_inputs(ask=dear_ask))

    assert isinstance(cheap, Take)
    assert cheap.limit_price == cheap_ask
    assert dear == Refuse(
        "edge_below_break_even",
        p_bound=p_hold_lower,
        break_even=_expected_break_even(dear_ask, Decimal("0.06")),
    )


def test_raising_the_fee_coefficient_flips_a_take_into_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Higher fee, same probability and price => the edge disappears.

    ``fee_coefficient`` must equal ``config.required_fee_coefficient`` or the
    earlier ``fee_schedule_mismatch`` gate fires, so both move together here
    -- this varies the FEE, never that gate.
    """
    p_hold_lower = Decimal("0.53")
    _pin_probability(monkeypatch, p_hold_lower)
    ask = Decimal("0.50")

    low_theta = Decimal("0.06")
    high_theta = Decimal("0.20")
    assert p_hold_lower > _expected_break_even(ask, low_theta)
    assert p_hold_lower <= _expected_break_even(ask, high_theta)

    def _inputs(theta: Decimal) -> DecisionInputs:
        return _causal_inputs(
            ask=ask,
            fee_coefficient=theta,
            config=CurrentRungHoldConfig(required_fee_coefficient=theta),
        )

    cheap_fee = evaluate_decision(_inputs(low_theta))
    dear_fee = evaluate_decision(_inputs(high_theta))

    assert isinstance(cheap_fee, Take)
    assert cheap_fee.break_even == _expected_break_even(ask, low_theta)
    assert dear_fee == Refuse(
        "edge_below_break_even",
        p_bound=p_hold_lower,
        break_even=_expected_break_even(ask, high_theta),
    )


# --------------------------------------------------------------------------
# 3. Production-path identity.
# --------------------------------------------------------------------------


def test_the_live_family_decision_path_resolves_to_this_same_evaluate_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The function swept above IS the one the live sending family calls.

    A full ``ContinuousRungHoldStrategy`` instantiation (trial-day latch,
    instrument cache, Nautilus node wiring) is too heavy for a pure unit
    test, so the binding is proved in three parts, as the brief permits:
    (a) IMPORT IDENTITY along the whole chain
    ``ContinuousRungHoldStrategy`` -> ``tick_eval.evaluate_both_sides`` ->
    ``decision.evaluate_decision``; (b) a CALL-SITE assertion that
    ``_hunt_tick``'s body really calls ``evaluate_both_sides``; and (c) a
    SPY driven through ``evaluate_both_sides`` proving the YES leg reaches
    ``evaluate_decision`` with ``DecisionInputs`` built from the tick.
    """
    # (a) import identity -- one object, no shadowing copy.
    assert tick_eval_module.evaluate_decision is decision_module.evaluate_decision
    assert tick_eval_module.evaluate_decision is evaluate_decision
    assert (
        continuous_strategy_module.evaluate_both_sides is tick_eval_module.evaluate_both_sides
    )

    # (b) call-site: `_hunt_tick` is the decision body and it calls it.
    hunt_source = inspect.getsource(ContinuousRungHoldStrategy._hunt_tick)
    assert "evaluate_both_sides(" in hunt_source
    assert "both_sides.yes" in hunt_source

    # (c) spy: drive the production entry point, capture the inputs.
    captured: list[DecisionInputs] = []
    real = decision_module.evaluate_decision

    def _spy(inputs: DecisionInputs) -> object:
        captured.append(inputs)
        return real(inputs)

    monkeypatch.setattr(tick_eval_module, "evaluate_decision", _spy)
    _pin_probability(monkeypatch, Decimal("0.42"))

    both = tick_eval_module.evaluate_both_sides(
        station=_STATION,
        climate_day=_CLIMATE_DAY,
        now_ns=1_000_000_000,
        ladder=_LADDER,
        fee_coefficient=Decimal("0.06"),
        ask=Decimal("0.40"),
        ask_size=5,
        bid=None,
        bid_size=None,
        running_max=_exact_running_max(70),
        staleness_ns=0,
        config=CurrentRungHoldConfig(),
        hour_lst=_HOUR_LST,
        width_code=_INTERIOR_WIDTH_CODE,
        m_code=_M_ZERO,
    )

    yes_inputs = [inputs for inputs in captured if inputs.side == "yes"]
    assert len(yes_inputs) == 1
    assert yes_inputs[0].ask == Decimal("0.40")
    assert yes_inputs[0].size == 5
    assert yes_inputs[0].station == _STATION
    assert yes_inputs[0].hour_lst == _HOUR_LST
    # Same function, same answer as the swept core.
    assert both.yes == evaluate_decision(yes_inputs[0])
    assert isinstance(both.yes, Take)
    assert both.yes.p_hold_lower == Decimal("0.42")


# --------------------------------------------------------------------------
# 4. Abstention rules dominate the edge signal.
# --------------------------------------------------------------------------


def test_a_stale_observation_refuses_however_favourable_the_probability_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Staleness beyond the bound wins over a near-certain edge."""
    _pin_probability(monkeypatch, Decimal("0.99"))
    assert isinstance(evaluate_decision(_causal_inputs(staleness_ns=_STALE_BOUND_NS)), Take)
    for stale_ns in (_STALE_BOUND_NS + 1, _STALE_BOUND_NS * 10):
        assert evaluate_decision(_causal_inputs(staleness_ns=stale_ns)) == Refuse(
            "observation_unavailable"
        )
    assert evaluate_decision(
        _causal_inputs(running_max=None, staleness_ns=None)
    ) == Refuse("observation_unavailable")


def test_the_decision_window_gate_refuses_every_out_of_window_hour_before_evaluating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The LST window gate is a STRATEGY gate that runs BEFORE any edge test.

    The pure core carries no clock gate at all (asserted first: a favourable
    probability at an out-of-window hour would take), so the abstention must
    dominate upstream. `_hunt_tick`'s guard is verified by (a) evaluating
    the exact predicate at every hour of the day and (b) proving in source
    order that the guard and its `return` precede the
    ``evaluate_both_sides`` call.
    """
    out_of_window_hour = 9
    out_of_window_key = (
        _STATION,
        _SEASON,
        out_of_window_hour,
        _INTERIOR_WIDTH_CODE,
        _M_ZERO,
    )
    _pin_probability(monkeypatch, Decimal("0.99"), key=out_of_window_key)
    assert isinstance(
        evaluate_decision(_causal_inputs(hour_lst=out_of_window_hour)), Take
    ), "the pure core has no clock gate; the window must dominate upstream"

    # (a) the exact predicate at `continuous_strategy._hunt_tick`.
    in_window = {
        hour
        for hour in range(24)
        if _WINDOW_START_HOUR_LST <= hour < _WINDOW_END_HOUR_LST
    }
    assert in_window == {12, 13, 14, 15, 16}
    assert out_of_window_hour not in in_window
    for hour in set(range(24)) - in_window:
        assert not (_WINDOW_START_HOUR_LST <= hour < _WINDOW_END_HOUR_LST)

    # (b) source order: guard, refusal record, `return`, THEN the evaluation.
    hunt_source = inspect.getsource(ContinuousRungHoldStrategy._hunt_tick)
    guard = "if not (_WINDOW_START_HOUR_LST <= hour_lst < _WINDOW_END_HOUR_LST):"
    assert guard in hunt_source
    guard_at = hunt_source.index(guard)
    evaluate_at = hunt_source.index("evaluate_both_sides(")
    assert guard_at < evaluate_at
    guard_block = hunt_source[guard_at:evaluate_at]
    assert "_OUTSIDE_DECISION_WINDOW" in guard_block
    assert "return" in guard_block


# --------------------------------------------------------------------------
# 5. Size and side are NOT probability-driven.
# --------------------------------------------------------------------------


def test_quantity_and_side_are_invariant_to_the_probability_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probability controls ONLY take-vs-refuse, never size or side.

    Size is ``config.order_quantity`` (pinned at 1) and the side is YES --
    a long buy, never a short (``allow_short`` stays ``False``).
    """
    config = CurrentRungHoldConfig()
    assert config.order_quantity == 1
    assert config.allow_short is False

    quantities: set[int] = set()
    sides: set[str] = set()
    limit_prices: set[Decimal] = set()
    for step in range(20):  # every p in the take region: 0.42 .. 0.61
        p_hold_lower = Decimal("0.42") + Decimal(step) * _CENT
        _pin_probability(monkeypatch, p_hold_lower)
        outcome = evaluate_decision(_causal_inputs(config=config))
        assert isinstance(outcome, Take)
        quantities.add(outcome.quantity)
        sides.add(outcome.side)
        limit_prices.add(outcome.limit_price)

    assert quantities == {config.order_quantity} == {1}
    assert sides == {"yes"}
    assert limit_prices == {Decimal("0.40")}  # the ask, never a function of p
