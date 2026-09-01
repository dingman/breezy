"""Unit tests for `breezy.strategy.weather_common.costs`.

The cost seam BL-19 s8.6 specifies and
`docs/plans/print_lock_adverse_selection_and_cost_2026-09-01.md` s2 designs:
two SEPARATELY NAMED pure terms, never one scalar. The point of the split is
that they behave OPPOSITELY as `p -> 1` -- the venue fee vanishes (0.000594 at
0.99) while the execution term does not -- so a single "total cost" field is
the field in which the unsafe configuration gets written.

The agreement test at the bottom is the one that makes the duplication safe:
this module is the GATE-TIME estimate of the fee, `PolymarketUSFeeModel` is
the SETTLEMENT-TIME authority, and they must not drift.
"""

from __future__ import annotations

import math
from decimal import Decimal

import pytest
from nautilus_trader.model.enums import LiquiditySide
from nautilus_trader.model.objects import Price, Quantity

from breezy.adapters.polymarket_us.fees import PolymarketUSFeeModel
from breezy.strategy.weather_common.costs import (
    FeeCoefficientSource,
    UnknownFeeScheduleError,
    trade_cost_prob,
    venue_fee_prob,
)
from tests.unit.test_polymarket_us_fee_model import (
    build,
    load_open_market,
    order_with_liquidity,
)

#: [MEASURED] 20/20 captured weather markets carry `feeCoefficient: 0.06`
#: (`docs/evidence/venue/polymarket_us/raw/markets_tagIds_weather.json`,
#: pinned by `test_evidence_pin_the_captured_venue_charges_six_percent_everywhere`).
THETA = 0.06


# ---------------------------------------------------------------------------
# `venue_fee_prob` -- the venue's own `theta * p * (1 - p)`, in prob units
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (0.99, 0.000594),
        (0.98, 0.001176),
        (0.97, 0.001746),
        (0.95, 0.002850),
        (0.90, 0.005400),
        (0.80, 0.009600),
        (0.65, 0.013650),
        (0.50, 0.015000),
        (0.21, 0.009954),
        (0.02, 0.001176),
    ],
)
def test_venue_fee_prob_pins_the_derived_table(price: float, expected: float) -> None:
    """Every fee figure in the plan's s1.3 / s1.5 tables, recomputed here."""
    assert venue_fee_prob(executable_price=price, fee_coefficient=THETA) == pytest.approx(
        expected, abs=1e-9,
    )


def test_venue_fee_prob_is_non_negative_across_the_whole_unit_interval() -> None:
    for i in range(101):
        p = i / 100.0
        assert venue_fee_prob(executable_price=p, fee_coefficient=THETA) >= 0.0


def test_venue_fee_prob_is_symmetric_about_one_half() -> None:
    """A YES at 0.90 and a NO at 0.10 cost the same -- the venue's own shape."""
    for i in range(51):
        p = i / 100.0
        assert venue_fee_prob(executable_price=p, fee_coefficient=THETA) == pytest.approx(
            venue_fee_prob(executable_price=1.0 - p, fee_coefficient=THETA), abs=1e-12,
        )


def test_venue_fee_prob_is_maximal_at_one_half() -> None:
    peak = venue_fee_prob(executable_price=0.5, fee_coefficient=THETA)
    for i in range(101):
        p = i / 100.0
        assert venue_fee_prob(executable_price=p, fee_coefficient=THETA) <= peak + 1e-12


def test_venue_fee_prob_is_monotone_decreasing_on_the_upper_half() -> None:
    """The reason the split matters: the fee VANISHES where this strategy trades."""
    previous = math.inf
    for i in range(50, 101):
        p = i / 100.0
        current = venue_fee_prob(executable_price=p, fee_coefficient=THETA)
        assert current <= previous + 1e-12
        previous = current


def test_venue_fee_prob_scales_linearly_in_theta() -> None:
    base = venue_fee_prob(executable_price=0.98, fee_coefficient=0.06)
    half = venue_fee_prob(executable_price=0.98, fee_coefficient=0.03)

    assert base == pytest.approx(2.0 * half, abs=1e-12)


def test_a_zero_coefficient_is_a_free_venue_and_is_allowed_because_it_was_OBSERVED() -> None:
    """`theta = 0` is a legitimate parsed value, distinct from UNRESOLVED.

    `adapters.polymarket_us.fees._fee_coefficient` accepts 0 (it validates the
    range `[0, 1]`); what it refuses is an ABSENT or unparseable coefficient.
    The refusal posture lives at resolution time, not here.
    """
    assert venue_fee_prob(executable_price=0.98, fee_coefficient=0.0) == 0.0


@pytest.mark.parametrize("price", [-0.01, 1.01, 2.0, -1.0])
def test_venue_fee_prob_refuses_a_price_outside_the_binary_range(price: float) -> None:
    """Outside [0, 1] the `p * (1 - p)` term goes NEGATIVE and pays a rebate.

    `fees.py:178-184` refuses for exactly this reason; the gate-time estimate
    must not be the one place a bad tick manufactures income.
    """
    with pytest.raises(ValueError, match="outside"):
        venue_fee_prob(executable_price=price, fee_coefficient=THETA)


@pytest.mark.parametrize("theta", [-0.01, 1.01, float("nan"), float("inf")])
def test_venue_fee_prob_refuses_an_unusable_coefficient(theta: float) -> None:
    with pytest.raises(ValueError):
        venue_fee_prob(executable_price=0.98, fee_coefficient=theta)


# ---------------------------------------------------------------------------
# `trade_cost_prob` -- fee PLUS slippage, kept separate and separately named
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        (0.99, 0.010594),
        (0.98, 0.011176),
        (0.97, 0.011746),
        (0.95, 0.012850),
        (0.90, 0.015400),
        (0.80, 0.019600),
        (0.65, 0.023650),
        (0.50, 0.025000),
        (0.21, 0.019954),
        (0.02, 0.011176),
    ],
)
def test_trade_cost_prob_pins_the_derived_cost_column(price: float, expected: float) -> None:
    assert trade_cost_prob(
        executable_price=price, fee_coefficient=THETA, slippage_prob=0.01,
    ) == pytest.approx(expected, abs=1e-9)


def test_trade_cost_prob_is_exactly_fee_plus_slippage() -> None:
    for i in range(101):
        p = i / 100.0
        assert trade_cost_prob(
            executable_price=p, fee_coefficient=THETA, slippage_prob=0.01,
        ) == pytest.approx(
            venue_fee_prob(executable_price=p, fee_coefficient=THETA) + 0.01, abs=1e-12,
        )


def test_the_two_terms_diverge_towards_certainty_which_is_why_they_are_split() -> None:
    """At 0.99 the fee is 5.6% of the cost and slippage is 94.4% of it.

    A single scalar cannot express that, and the one-scalar spelling is what
    lets `transaction_cost_prob = 0.0006` be written and trade at 0.99.
    """
    fee = venue_fee_prob(executable_price=0.99, fee_coefficient=THETA)
    total = trade_cost_prob(executable_price=0.99, fee_coefficient=THETA, slippage_prob=0.01)

    assert fee == pytest.approx(0.000594, abs=1e-9)
    assert total - fee == pytest.approx(0.01, abs=1e-12)
    assert fee / total < 0.06


@pytest.mark.parametrize("slippage", [-0.001, float("nan"), float("inf")])
def test_trade_cost_prob_refuses_a_negative_or_non_finite_slippage(slippage: float) -> None:
    """A negative execution term is a rebate on execution. There is no such thing."""
    with pytest.raises(ValueError):
        trade_cost_prob(executable_price=0.98, fee_coefficient=THETA, slippage_prob=slippage)


# ---------------------------------------------------------------------------
# The injection seam
# ---------------------------------------------------------------------------


def test_unknown_fee_schedule_error_is_a_value_error() -> None:
    """Catchable by the strategy layer without importing an adapter type."""
    assert issubclass(UnknownFeeScheduleError, ValueError)


def test_fee_coefficient_source_is_a_runtime_checkable_pull_seam() -> None:
    class _Source:
        def fee_coefficient_for(self, instrument_id: str) -> float:
            return THETA

    source: FeeCoefficientSource = _Source()

    assert source.fee_coefficient_for("KNYC-80-84.SIM") == THETA


# ---------------------------------------------------------------------------
# AGREEMENT: the gate-time estimate must not drift from the settlement-time
# authority. This is the test that makes the duplication safe.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("price", ["0.98", "0.90", "0.65", "0.50", "0.21", "0.02"])
@pytest.mark.parametrize("contracts", [25, 100, 150])
def test_venue_fee_prob_times_contracts_agrees_with_the_settlement_fee_model(
    price: str, contracts: int,
) -> None:
    """`venue_fee_prob(p, theta) * C` == `PolymarketUSFeeModel.get_commission(...)`.

    Up to the venue's banker's-rounding quantum ($0.01), which the settlement
    model applies and the gate-time estimate deliberately does not -- the gate
    reasons in probability units and must stay continuous.
    """
    instrument = build(load_open_market())
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)
    theta = float(Decimal(str(instrument.info["fee_coefficient"])))

    estimate = venue_fee_prob(executable_price=float(price), fee_coefficient=theta) * contracts
    authority = PolymarketUSFeeModel().get_commission(
        order,
        Quantity.from_int(contracts),
        Price.from_str(price),
        instrument,
    )

    # HALF the $0.01 quantum is the exact worst case of banker's rounding; the
    # `1e-9` is float slack for the half-cent boundary (0.135 -> 0.14), not a
    # loosening of the agreement.
    assert abs(estimate - float(authority.as_double())) <= 0.005 + 1e-9
