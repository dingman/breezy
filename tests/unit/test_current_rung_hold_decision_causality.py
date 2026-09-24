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

The sole probability input is ``P_HOLD_LOWER.get(key)`` (YES) /
``1 - P_HOLD_UPPER.get(key)`` (NO); to hold EVERY other ``DecisionInputs``
field constant while sweeping it, these tests monkeypatch
``decision.P_HOLD_LOWER`` / ``decision.P_HOLD_UPPER`` (the module globals the
function actually reads) -- never the frozen ``archive_table`` corpus itself.

What this file does NOT prove (scope, explicit)
-----------------------------------------------

The claim proved here is about the PURE CORE ``evaluate_decision`` and the
IMPORT/CALL-SITE binding from the live family to it. It is NOT an end-to-end
sending proof. Specifically, none of the following is proved anywhere below:

* that a live venue tick actually REACHES ``_hunt_tick``'s
  ``evaluate_both_sides`` call -- the instrument/subscription, climate-day,
  de-dupe, trial-day latch, observation-availability and depth/quote
  plumbing gates upstream of it are untested here (only the LST-window gate
  is characterized, and only by predicate + source order);
* that a ``Take`` is ever SUBMITTED. ``_maybe_submit``, the arming state,
  the boot-time execution permit, the NO-SEND egress firewall and the
  operator-reserved caps are all downstream of this file's last assertion;
  a ``Take`` here is a decision object, never an order;
* the NO leg's live WIRING (``continuous_strategy.py:1937``). The NO-leg
  sweep below exercises the pure core's NO branch (``decision.py:431-433``,
  probability ``1 - P_HOLD_UPPER``) only -- it does not prove the strategy
  feeds it the venue's real bid, nor that a NO ``Take`` is submitted;
* the exit/sell path (``exit_wiring.py:302``) in any form -- this file is
  entry-decision-only and says nothing about closing a position.
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
from breezy.strategy.current_rung_hold.archive_table import P_HOLD_LOWER as FROZEN_P_HOLD_LOWER
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

#: Derived from the production config, never hardcoded: if
#: ``stale_observation_minutes`` moves, the staleness test below moves with
#: it (and fails loudly if production's bound stops being
#: ``minutes * 60s``), rather than silently drifting away from the real bound.
_STALE_BOUND_NS = CurrentRungHoldConfig().stale_observation_minutes * 60 * 1_000_000_000
_CENT = Decimal("0.01")
_TENTH_CENT = Decimal("0.0001")


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

    SCOPE (see the module docstring's "What this file does NOT prove"):
    this proves only that the live family's decision call RESOLVES to this
    function. It does NOT prove that a live tick reaches ``_hunt_tick`` past
    its upstream gates, that ``evaluate_both_sides`` is reached on a real
    quote, or that the resulting ``Take`` is ever submitted -- ``_maybe_submit``,
    arming, the execution permit and the egress firewall are all untested
    here, and the NO leg's live wiring (``continuous_strategy.py:1937``) and
    the exit path (``exit_wiring.py:302``) are outside this file entirely.
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


# --------------------------------------------------------------------------
# 6. The fee's ROUNDING MODE is banker's, pinned against the alternatives.
# --------------------------------------------------------------------------


def _fee_is_a_half_cent_tie(price: Decimal, theta: Decimal) -> bool:
    exact = theta * price * (Decimal(1) - price)
    return (exact / _CENT) % 1 == Decimal("0.5")


@pytest.mark.parametrize(
    ("theta", "price", "expected_fee", "half_up_fee"),
    [
        # exact fee 0.015 -> banker's rounds UP to the even cent 0.02.
        # Rules this case KILLS: ROUND_DOWN / ROUND_FLOOR / ROUND_HALF_DOWN
        # (all 0.01).
        (Decimal("0.06"), Decimal("0.50"), Decimal("0.02"), Decimal("0.02")),
        # exact fee 0.025 -> banker's rounds DOWN to the even cent 0.02.
        # Rules this case KILLS: ROUND_HALF_UP / ROUND_UP / ROUND_CEILING
        # (all 0.03).
        (Decimal("0.10"), Decimal("0.50"), Decimal("0.02"), Decimal("0.03")),
    ],
)
def test_a_true_half_cent_tie_is_rounded_bankers_not_half_up(
    monkeypatch: pytest.MonkeyPatch,
    theta: Decimal,
    price: Decimal,
    expected_fee: Decimal,
    half_up_fee: Decimal,
) -> None:
    """The break-even on an EXACT half-cent tie is banker's-rounded.

    Gap 1 (domain review): every other case in this file lands the fee well
    away from a .005 boundary (0.0144, 0.0126, 0.0500), so ROUND_DOWN or
    ROUND_HALF_UP in production would pass them unchanged. These two cases
    are true ties -- one that banker's rounds UP and one it rounds DOWN --
    so between them they pin ROUND_HALF_EVEN uniquely against every other
    standard mode. The 0.025 case FAILS if production switches to
    ROUND_HALF_UP (break-even would be 0.53, not 0.52).
    """
    assert _fee_is_a_half_cent_tie(price, theta), "case is not a true half-cent tie"
    expected_break_even = price + expected_fee
    assert _expected_break_even(price, theta) == expected_break_even

    config = CurrentRungHoldConfig(required_fee_coefficient=theta)

    def _decide(p_bound: Decimal) -> object:
        _pin_probability(monkeypatch, p_bound)
        return evaluate_decision(
            _causal_inputs(ask=price, fee_coefficient=theta, config=config)
        )

    # (a) the reported break-even is the banker's one, on BOTH outcome paths.
    below = _decide(expected_break_even)
    assert below == Refuse(
        "edge_below_break_even", p_bound=expected_break_even, break_even=expected_break_even
    )
    above = _decide(expected_break_even + _CENT)
    assert isinstance(above, Take)
    assert above.break_even == expected_break_even

    # (b) a DECISION that differs under ROUND_HALF_UP, whenever the two modes
    # disagree: p sits above the banker's break-even and at-or-below the
    # half-up one, so half-up would refuse where banker's takes.
    if half_up_fee != expected_fee:
        half_up_break_even = price + half_up_fee
        probe = expected_break_even + (half_up_break_even - expected_break_even) / 2
        assert expected_break_even < probe <= half_up_break_even
        outcome = _decide(probe)
        assert isinstance(outcome, Take), (
            f"p={probe} must TAKE under banker's rounding (break-even "
            f"{expected_break_even}); a Refuse here means production rounds "
            f"HALF_UP (break-even {half_up_break_even})"
        )
        assert outcome.break_even == expected_break_even


# --------------------------------------------------------------------------
# 7. CHARACTERIZATION: the boundary tracks the AS-CHARGED (rounded) fee.
# --------------------------------------------------------------------------


def test_the_break_even_boundary_tracks_the_as_charged_fee_not_the_exact_fee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate's break-even uses the fee the VENUE ACTUALLY CHARGES.

    Gap 2 (domain review), corrected against the venue's own published
    schedule (``docs/evidence/venue/polymarket_us/docs_snapshots/
    fees_2026-08-25.md:152,208``): "All fees and rebates are rounded to the
    nearest $0.01 using banker's rounding (round half to even)" and "Fees
    are rounded to the nearest cent ... the fee can round down to $0.00".
    The cent-quantized fee is therefore NOT an approximation the gate gets
    away with -- it is the charge. ``decision._fee`` models the same rule
    ``fees._round_bankers`` (:467-475) applies to the authoritative
    per-fill commission, and at ``config.order_quantity == 1`` there is
    exactly ONE fill, so that snapshot's multi-fill cumulative cap (:153,
    which "can only reduce a fill's charge, never increase it") is
    inapplicable and the rounded per-fill fee is exactly what is paid.

    The sub-cent sweep is kept because the boundary is what it pins: the
    probability arrives at 1e-4 granularity while the charge is a whole
    cent, so a probability strictly between the as-charged break-even and
    the EXACT-fee break-even is taken -- correctly, at POSITIVE realised
    edge, because the exact fee is never billed. At ask 0.70 / theta 0.06
    the exact fee is 0.0126 but 0.01 is charged, so the rounding is a
    0.0026/contract DISCOUNT in the trader's favour. The signed gap's full
    distribution is characterized in the corpus test below.
    """
    price = Decimal("0.70")
    theta = Decimal("0.06")
    exact_fee = theta * price * (Decimal(1) - price)
    as_charged_fee = exact_fee.quantize(_CENT, rounding=ROUND_HALF_EVEN)
    assert (exact_fee, as_charged_fee) == (Decimal("0.012600"), Decimal("0.01"))

    as_charged_break_even = _expected_break_even(price, theta)
    exact_fee_break_even = price + exact_fee
    assert as_charged_break_even == Decimal("0.71")
    # Signed gap, trader's perspective: charged MINUS exact. Negative = discount.
    rounding_gap = as_charged_fee - exact_fee
    assert rounding_gap == Decimal("-0.002600")

    # Sweep at 1e-4 -- the frozen table's OWN granularity, i.e. values the
    # production lookup really can return.
    taken_below_the_exact_fee_break_even: list[Decimal] = []
    step = as_charged_break_even
    while step <= exact_fee_break_even:
        _pin_probability(monkeypatch, step)
        outcome = evaluate_decision(_causal_inputs(ask=price, fee_coefficient=theta))
        if step == as_charged_break_even:
            assert isinstance(outcome, Refuse)  # equality refuses (strict `>`)
        else:
            assert isinstance(outcome, Take), f"expected Take at p={step}"
            assert outcome.break_even == as_charged_break_even
            # Realised edge against the AS-CHARGED fee -- the money actually
            # paid -- is strictly POSITIVE on every one of these.
            assert step - (price + as_charged_fee) > 0
            assert step <= exact_fee_break_even  # and below the exact-fee line
            taken_below_the_exact_fee_break_even.append(step)
        step += _TENTH_CENT

    assert len(taken_below_the_exact_fee_break_even) == 26  # 0.7101 .. 0.7126
    assert min(taken_below_the_exact_fee_break_even) == Decimal("0.7101")
    assert max(taken_below_the_exact_fee_break_even) == exact_fee_break_even
    # The whole band is inside the rounding discount: no take here is thinner
    # than one 1e-4 tick of realised edge.
    thinnest = min(p - (price + as_charged_fee) for p in taken_below_the_exact_fee_break_even)
    assert thinnest == _TENTH_CENT


def test_the_as_charged_rounding_gap_is_a_discount_more_often_than_a_penalty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The SIGNED gap ``as_charged_fee - exact_fee`` over the frozen corpus.

    Measured over all 240 defined ``P_HOLD_LOWER`` cells (every one at 1e-4
    granularity; 239 finer than a cent) crossed with the whole admissible 1c
    ask grid in ``(0.05, 0.95)`` -- 89 asks:

    * theta = 0.06: the rounding favours the trader (charged < exact) at 64
      of 89 asks and penalises (charged > exact) at 25; max discount
      0.004994/contract at ask 0.49, max penalty 0.0050 at ask 0.50. Of the
      21,360 (cell, ask) pairs, 51 are TAKEN under the as-charged rule that
      an exact-fee rule would refuse (each at positive realised edge), and
      10 are REFUSED that an exact-fee rule would take (the conservative
      direction) -- no pair trades at negative realised edge.
    * theta = 0.0695 (the 2026-09-17 drift): discount at 32 asks, penalty at
      57; max discount 0.00486605 at ask 0.31, max penalty 0.00488480 at ask
      0.92; 42 pairs taken-only-under-as-charged, 24 refused-only.

    Because the take rule is ``p > price + as_charged_fee`` and the venue
    charges exactly that fee, NO admissible (cell, ask) pair yields a take
    with negative realised edge -- asserted exhaustively below.
    """
    defined = {key: value for key, value in FROZEN_P_HOLD_LOWER.items() if value is not None}
    assert len(defined) == 240
    assert all(value.as_tuple().exponent == -4 for value in defined.values())
    assert sum(1 for v in defined.values() if v != v.quantize(_CENT)) == 239

    grid = [Decimal(cents) / 100 for cents in range(6, 95)]
    assert len(grid) == 89

    for theta, favour, penalise, max_discount, max_penalty, taken_only, refused_only in (
        (Decimal("0.06"), 64, 25, Decimal("-0.004994"), Decimal("0.0050"), 51, 10),
        (Decimal("0.0695"), 32, 57, Decimal("-0.00486605"), Decimal("0.00488480"), 42, 24),
    ):
        gaps = {
            ask: _expected_break_even(ask, theta) - (ask + theta * ask * (Decimal(1) - ask))
            for ask in grid
        }
        assert sum(1 for gap in gaps.values() if gap < 0) == favour
        assert sum(1 for gap in gaps.values() if gap > 0) == penalise
        assert min(gaps.values()) == max_discount
        assert max(gaps.values()) == max_penalty

        taken_only_count = 0
        refused_only_count = 0
        for value in defined.values():
            for ask in grid:
                as_charged = _expected_break_even(ask, theta)
                exact = ask + theta * ask * (Decimal(1) - ask)
                if as_charged < value <= exact:
                    taken_only_count += 1
                elif exact < value <= as_charged:
                    refused_only_count += 1
        assert (taken_only_count, refused_only_count) == (taken_only, refused_only)

    theta = Decimal("0.06")
    # A real corpus cell, driven through production at the as-charged fee.
    key = ("LAX", "DJF", 14, 0, 0)
    value = FROZEN_P_HOLD_LOWER[key]
    assert value == Decimal("0.7213")
    ask = Decimal("0.71")
    _pin_probability(monkeypatch, value)
    outcome = evaluate_decision(_causal_inputs(ask=ask, fee_coefficient=theta))
    assert isinstance(outcome, Take)
    assert outcome.break_even == Decimal("0.72")  # 0.71 + charged 0.01
    assert value - outcome.break_even == Decimal("0.0013")  # POSITIVE realised edge
    # An exact-fee rule would have refused this one; the venue never bills it.
    assert value <= ask + theta * ask * (Decimal(1) - ask)


# --------------------------------------------------------------------------
# 8. The NO leg: the same causal sweep on `1 - P_HOLD_UPPER`.
# --------------------------------------------------------------------------


def _pin_no_probability(
    monkeypatch: pytest.MonkeyPatch,
    p_hold_upper: Decimal | None,
    *,
    key: tuple[str, str, int, int, int] = _KEY,
) -> None:
    """Pin the NO leg's ONLY probability source (``decision.P_HOLD_UPPER``)."""
    monkeypatch.setattr(decision_module, "P_HOLD_UPPER", {key: p_hold_upper})


def _no_inputs(bid: Decimal, **overrides: object) -> DecisionInputs:
    """NO snapshot on the ARMED calibration path.

    These tests pin the break-even boundary of ``P_HOLD_UPPER``, which is
    reachable only once ``no_side_calibration_gate_cleared`` is explicit.
    The shipped default (closed) is pinned in the NO-side decision module.
    """
    config = overrides.pop("config", CurrentRungHoldConfig(no_side_calibration_gate_cleared=True))
    return _causal_inputs(
        side="no",
        bid=bid,
        bid_size=Decimal(5),
        config=config,
        **overrides,
    )


def test_the_no_leg_flips_refuse_to_take_exactly_at_its_own_break_even(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sweeping ONLY ``P_HOLD_UPPER`` flips the NO decision at ``1 - p_u > NO_ask + fee``.

    The NO price is ``1 - bid`` and the NO estimand is ``1 - P_HOLD_UPPER``
    (``decision.py:431-433``): a HIGHER ``p_hold_upper`` is a WORSE NO edge,
    so the sweep's direction is inverted relative to the YES leg. The
    break-even oracle is the same recomputed one, applied to the inverted
    price -- never imported from production.
    """
    bid = Decimal("0.60")
    theta = Decimal("0.06")
    no_ask = Decimal(1) - bid
    expected_break_even = _expected_break_even(no_ask, theta)
    assert (no_ask, expected_break_even) == (Decimal("0.40"), Decimal("0.41"))

    taken: list[Decimal] = []
    refused: list[Decimal] = []
    for step in range(31):  # p_hold_upper 0.40 .. 0.70 => p_miss 0.60 .. 0.30
        p_hold_upper = Decimal("0.40") + Decimal(step) * _CENT
        p_miss_lower = Decimal(1) - p_hold_upper
        _pin_no_probability(monkeypatch, p_hold_upper)
        outcome = evaluate_decision(_no_inputs(bid))
        if p_miss_lower > expected_break_even:
            assert isinstance(outcome, Take), f"expected Take at p_u={p_hold_upper}"
            assert outcome.side == "no"
            assert outcome.p_bound == p_miss_lower
            assert outcome.limit_price == no_ask
            assert outcome.break_even == expected_break_even
            assert outcome.quantity == 1  # never a short: allow_short stays False
            taken.append(p_miss_lower)
        else:
            assert outcome == Refuse(
                "edge_below_break_even",
                p_bound=p_miss_lower,
                break_even=expected_break_even,
            ), f"expected Refuse at p_u={p_hold_upper}"
            refused.append(p_miss_lower)

    assert refused and taken
    assert max(refused) < min(taken)
    assert max(refused) == expected_break_even  # equality refuses (strict `>`)
    assert min(taken) == expected_break_even + _CENT


def test_the_no_leg_refuses_when_its_own_table_cell_is_undefined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ``P_HOLD_UPPER`` => no NO take, even with a wide-open YES cell."""
    _pin_probability(monkeypatch, Decimal("0.99"))
    monkeypatch.setattr(decision_module, "P_HOLD_UPPER", {})
    assert evaluate_decision(_no_inputs(Decimal("0.60"))) == Refuse("p_hold_undefined")
    _pin_no_probability(monkeypatch, None)
    assert evaluate_decision(_no_inputs(Decimal("0.60"))) == Refuse("p_hold_undefined")


def test_raising_the_bid_flips_a_no_take_into_a_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A higher bid is a DEARER NO leg (``NO_ask = 1 - bid``) => the edge dies."""
    _pin_no_probability(monkeypatch, Decimal("0.40"))  # p_miss_lower = 0.60
    theta = Decimal("0.06")
    cheap_bid = Decimal("0.60")  # NO_ask 0.40, break-even 0.41
    dear_bid = Decimal("0.30")  # NO_ask 0.70, break-even 0.71

    cheap = evaluate_decision(_no_inputs(cheap_bid))
    dear = evaluate_decision(_no_inputs(dear_bid))

    assert isinstance(cheap, Take)
    assert cheap.limit_price == Decimal("0.40")
    assert dear == Refuse(
        "edge_below_break_even",
        p_bound=Decimal("0.60"),
        break_even=_expected_break_even(Decimal("0.70"), theta),
    )
