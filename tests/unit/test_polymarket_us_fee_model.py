"""The Polymarket.us fee model computes ``theta * C * p * (1 - p)`` per market.

Why this file exists. The venue fee is a coefficient on a CONCAVE function of
fill price, not a flat rate on notional. Nautilus's ``BinaryOption`` exposes
only flat ``maker_fee``/``taker_fee`` rates
(``model/instruments/binary_option.pyx:148-149``), and generic machinery such
as ``MakerTakerFeeModel.get_commission`` (``backtest/models/fee.pyx``)
multiplies notional by those and by nothing else. No constant can represent
``theta * p * (1 - p)`` exactly, so the fee is carried by a native
``FeeModel`` subclass instead -- the extension point Nautilus provides for
precisely this.

NULL HYPOTHESIS, tested rather than asserted. Nautilus DOES ship a fee model
with our exact formula: ``nautilus_pyo3.ProbabilityPriceFeeModel``
(``qty * rate * p * (1 - p)``). It lives on the PyO3 surface, which Breezy
does not use, and ``BacktestEngine.add_venue`` type-checks its ``fee_model``
against the *Cython* ``FeeModel`` (``backtest/engine.pyx:651``). The rejection
is pinned below so that a version bump which unifies the two surfaces fails
RED and tells us to delete Breezy's model rather than carry it forever.
"""

from __future__ import annotations

import copy
import json
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.backtest.models import FeeModel, MakerTakerFeeModel
from nautilus_trader.core.correctness import PyCondition
from nautilus_trader.model.enums import LiquiditySide
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.model.orders import Order
from nautilus_trader.test_kit.stubs.events import TestEventStubs
from nautilus_trader.test_kit.stubs.execution import TestExecStubs

from breezy.adapters.polymarket_us.errors import (
    FeeScheduleUnknownError,
    MakerRebateUnmodelledError,
    PolymarketUSError,
)
from breezy.adapters.polymarket_us.fees import PolymarketUSFeeModel
from breezy.adapters.polymarket_us.parsing import (
    FEE_COEFFICIENT_KEY,
    FEE_SCHEDULE_STATUS_KEY,
    FEE_SCHEDULE_STATUS_KNOWN,
    FEE_SCHEDULE_STATUS_UNKNOWN,
    parse_binary_option,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from tests.unit.conftest import (
    MIN_CAPTURED_MARKETS,
    iter_captured_market_payloads,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"
TS_INIT = 1_787_617_213_000_000_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def load_open_market() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads(
        (RAW / "market_open_510636_by_slug.json").read_text(encoding="utf-8")
    )
    return payload


def build(payload: dict[str, Any]) -> BinaryOption:
    return parse_binary_option(payload, venue=POLYMARKET_US_VENUE, ts_init=TS_INIT)


def with_theta(theta: object) -> BinaryOption:
    payload = load_open_market()
    payload["market"]["feeCoefficient"] = theta
    return build(payload)


def rebuild_with_info(instrument: BinaryOption, info: dict[str, Any]) -> BinaryOption:
    """Clone ``instrument`` with a replaced ``info`` (``info`` is read-only)."""
    return BinaryOption(
        instrument_id=instrument.id,
        raw_symbol=instrument.raw_symbol,
        outcome=instrument.outcome,
        description=instrument.description,
        asset_class=instrument.asset_class,
        currency=instrument.quote_currency,
        price_precision=instrument.price_precision,
        price_increment=instrument.price_increment,
        size_precision=instrument.size_precision,
        size_increment=instrument.size_increment,
        activation_ns=instrument.activation_ns,
        expiration_ns=instrument.expiration_ns,
        min_quantity=instrument.min_quantity,
        ts_event=instrument.ts_event,
        ts_init=instrument.ts_init,
        info=info,
    )


def order_with_liquidity(instrument: BinaryOption, side: LiquiditySide) -> Order:
    """A REAL Nautilus order carrying a real ``liquidity_side``.

    Built through ``test_kit`` stubs rather than a hand-rolled fake, so the
    object the fee model receives is the object the matching engine passes.
    """
    order = TestExecStubs.make_submitted_order(
        instrument=instrument,
        quantity=Quantity.from_int(100),
    )
    order.apply(TestEventStubs.order_accepted(order))
    order.apply(
        TestEventStubs.order_filled(
            order,
            instrument,
            liquidity_side=side,
            last_px=Price.from_str("0.50"),
        )
    )
    return order


def post_only_order(instrument: BinaryOption, side: LiquiditySide) -> Order:
    """A REAL post-only (maker-only) Nautilus order that has filled."""
    order = TestExecStubs.make_submitted_order(
        instrument=instrument,
        quantity=Quantity.from_int(100),
        post_only=True,
    )
    order.apply(TestEventStubs.order_accepted(order))
    order.apply(
        TestEventStubs.order_filled(
            order,
            instrument,
            liquidity_side=side,
            last_px=Price.from_str("0.50"),
        )
    )
    return order


# ---------------------------------------------------------------------------
# The formula
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("side", [LiquiditySide.MAKER, LiquiditySide.TAKER])
def test_fee_model_pins_theta_times_contracts_times_price_times_one_minus_price(
    side: LiquiditySide,
) -> None:
    """Hand-computed, both symmetric and asymmetric prices."""
    instrument = build(load_open_market())
    model = PolymarketUSFeeModel()
    order = order_with_liquidity(instrument, side)
    usd = instrument.quote_currency

    # Hand calculation: 0.06 * 100 * 0.50 * 0.50 = 1.50.
    # This is the venue's own documented worst case: $1.50 per 100 at p=0.50.
    assert model.get_commission(
        order, Quantity.from_int(100), Price.from_str("0.50"), instrument
    ) == Money(Decimal("1.50"), usd)

    # Hand calculation: 0.06 * 100 * 0.90 * 0.10 = 0.54.
    assert model.get_commission(
        order, Quantity.from_int(100), Price.from_str("0.90"), instrument
    ) == Money(Decimal("0.54"), usd)

    # Hand calculation: 0.06 * 100 * 0.10 * 0.90 = 0.54. p(1-p) is symmetric
    # about 0.50, so the mirrored price costs the same.
    assert model.get_commission(
        order, Quantity.from_int(100), Price.from_str("0.10"), instrument
    ) == Money(Decimal("0.54"), usd)

    # Hand calculation: 0.06 * 100 * 0.99 * 0.01 = 0.0594 -> $0.06.
    assert model.get_commission(
        order, Quantity.from_int(100), Price.from_str("0.99"), instrument
    ) == Money(Decimal("0.06"), usd)


def test_a_certain_outcome_is_free_because_p_times_one_minus_p_is_zero() -> None:
    instrument = build(load_open_market())
    model = PolymarketUSFeeModel()
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)
    usd = instrument.quote_currency

    for price in ("0.00", "1.00"):
        assert model.get_commission(
            order, Quantity.from_int(100), Price.from_str(price), instrument
        ) == Money(Decimal(0), usd)


def test_maker_is_charged_at_the_taker_coefficient_which_is_an_inference() -> None:
    """The payload carries ONE coefficient and no maker/taker split.

    Charging makers at the taker coefficient is a deliberate CONSERVATIVE
    inference, not a venue fact: if makers are in truth free or rebated we
    have overstated our own cost, which is the safe direction for a gate.
    The venue docs snapshot describes a maker rebate; we do not apply it,
    because applying an unobserved rebate would UNDERSTATE cost.
    """
    instrument = build(load_open_market())
    model = PolymarketUSFeeModel()
    args = (Quantity.from_int(100), Price.from_str("0.50"), instrument)

    maker = model.get_commission(order_with_liquidity(instrument, LiquiditySide.MAKER), *args)
    taker = model.get_commission(order_with_liquidity(instrument, LiquiditySide.TAKER), *args)

    assert maker == taker
    assert maker.as_decimal() > Decimal(0)


def test_fee_model_reads_theta_from_the_market_payload_not_a_constant() -> None:
    """A different payload coefficient MUST produce a different fee."""
    model = PolymarketUSFeeModel()
    six = build(load_open_market())
    three = with_theta("0.03")
    order = order_with_liquidity(six, LiquiditySide.TAKER)
    args = (Quantity.from_int(100), Price.from_str("0.50"))

    commission_006 = model.get_commission(order, *args, six)
    commission_003 = model.get_commission(order, *args, three)

    assert commission_006 == Money(Decimal("1.50"), six.quote_currency)
    assert commission_003 == Money(Decimal("0.75"), three.quote_currency)
    assert commission_003 != commission_006


def test_fee_scales_linearly_in_contract_count() -> None:
    instrument = build(load_open_market())
    model = PolymarketUSFeeModel()
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)
    px = Price.from_str("0.50")

    # 0.06 * 200 * 0.25 = 3.00, exactly twice 0.06 * 100 * 0.25 = 1.50.
    assert model.get_commission(order, Quantity.from_int(200), px, instrument) == Money(
        Decimal("3.00"), instrument.quote_currency
    )


# ---------------------------------------------------------------------------
# Rounding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("theta", "expected"),
    [
        # exact 0.025 -> banker's rounding goes DOWN to the even cent 0.02.
        # (round-half-up or round-ceiling would give 0.03, so this discriminates.)
        ("0.10", "0.02"),
        # exact 0.035 -> banker's rounding goes UP to the even cent 0.04.
        ("0.14", "0.04"),
        # exact 0.015 -> banker's rounding goes UP to the even cent 0.02.
        ("0.06", "0.02"),
    ],
)
def test_rounding_is_the_venue_documented_bankers_rounding_to_the_cent(
    theta: str, expected: str
) -> None:
    """Venue rule: banker's rounding to $0.01 (polymarket-us-integration skill).

    Each case is an EXACT half-cent, which is the only place rounding modes
    disagree. One contract at p=0.50 makes the arithmetic trivial to check:
    fee = theta * 1 * 0.5 * 0.5 = theta / 4.
    """
    instrument = with_theta(theta)
    model = PolymarketUSFeeModel()
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)

    assert model.get_commission(
        order, Quantity.from_int(1), Price.from_str("0.50"), instrument
    ) == Money(Decimal(expected), instrument.quote_currency)


# ---------------------------------------------------------------------------
# Fail-closed
# ---------------------------------------------------------------------------


def test_fee_model_refuses_when_the_fee_schedule_is_unknown() -> None:
    instrument = build(load_open_market())
    info = dict(instrument.info)
    info[FEE_SCHEDULE_STATUS_KEY] = FEE_SCHEDULE_STATUS_UNKNOWN
    unknown = rebuild_with_info(instrument, info)

    model = PolymarketUSFeeModel()
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)

    with pytest.raises(FeeScheduleUnknownError):
        model.get_commission(order, Quantity.from_int(100), Price.from_str("0.50"), unknown)


@pytest.mark.parametrize("bad", [None, "not-a-number", "1.5", "-0.01", "NaN"])
def test_fee_model_refuses_a_known_marker_carrying_an_unusable_coefficient(bad: object) -> None:
    """Defence in depth: the status marker alone never licenses a computation.

    ``parse_binary_option`` cannot produce this state, but a hand-built or
    round-tripped instrument can, and the model must still fail closed rather
    than compute from a garbage coefficient.
    """
    instrument = build(load_open_market())
    info = dict(instrument.info)
    info[FEE_SCHEDULE_STATUS_KEY] = FEE_SCHEDULE_STATUS_KNOWN
    info[FEE_COEFFICIENT_KEY] = bad
    tampered = rebuild_with_info(instrument, info)

    model = PolymarketUSFeeModel()
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)

    with pytest.raises(FeeScheduleUnknownError):
        model.get_commission(order, Quantity.from_int(100), Price.from_str("0.50"), tampered)


@pytest.mark.parametrize("price", ["-0.01", "1.01"])
def test_fee_model_refuses_a_fill_price_outside_the_binary_range(price: str) -> None:
    """Outside [0, 1], p(1-p) turns negative and would REBATE us. Refuse."""
    instrument = build(load_open_market())
    model = PolymarketUSFeeModel()
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)

    with pytest.raises(ValueError, match="0, 1"):
        model.get_commission(order, Quantity.from_int(100), Price.from_str(price), instrument)


def test_fee_model_refuses_an_order_with_no_liquidity_side() -> None:
    """A fill with no side is a bug upstream, never a free trade."""
    instrument = build(load_open_market())
    model = PolymarketUSFeeModel()
    order = TestExecStubs.make_submitted_order(
        instrument=instrument, quantity=Quantity.from_int(100)
    )
    assert order.liquidity_side == LiquiditySide.NO_LIQUIDITY_SIDE

    with pytest.raises(ValueError, match="liquidity"):
        model.get_commission(order, Quantity.from_int(100), Price.from_str("0.50"), instrument)


# ---------------------------------------------------------------------------
# Contract tests against the immutable foundation
# ---------------------------------------------------------------------------


def test_the_model_is_a_native_cython_fee_model_the_backtest_engine_accepts() -> None:
    """``BacktestEngine.add_venue`` runs ``Condition.type(fee_model, FeeModel)``.

    (``backtest/engine.pyx:651``.) Subclassing the Cython base is the whole
    reason this extension is legitimate rather than a parallel abstraction.
    """
    model = PolymarketUSFeeModel()
    assert isinstance(model, FeeModel)
    PyCondition.type(model, FeeModel, "fee_model")


def test_the_native_pyo3_probability_fee_model_is_still_unusable_from_cython() -> None:
    """NULL-HYPOTHESIS PIN, and a deliberate tripwire on version bumps.

    ``nautilus_pyo3.ProbabilityPriceFeeModel`` implements our exact formula.
    It is rejected by the Cython engine's type check today. If a future
    Nautilus makes this pass, Breezy's model is redundant and MUST be deleted
    rather than maintained alongside the framework's own.
    """
    from nautilus_trader.core import nautilus_pyo3

    # Fetched via `getattr` because `core/nautilus_pyo3.pyi` is INCOMPLETE:
    # `ProbabilityPriceFeeModel` exists at runtime but is absent from the stub,
    # so a direct attribute access fails `mypy --strict` while working fine.
    # Grepping the stub to prove a symbol's absence yields false negatives.
    factory = getattr(nautilus_pyo3, "ProbabilityPriceFeeModel", None)
    assert factory is not None, "the PyO3 fee model vanished; re-check the null hypothesis"

    native = factory()
    assert not isinstance(native, FeeModel)
    with pytest.raises(TypeError):
        PyCondition.type(native, FeeModel, "fee_model")


# ---------------------------------------------------------------------------
# The real captured corpus
# ---------------------------------------------------------------------------


def test_every_captured_market_observation_resolves_to_a_usable_coefficient() -> None:
    """BEHAVIOURAL property: the parser resolves a usable theta for every market.

    Deliberately says nothing about the VALUE of theta. The whole design
    reads the coefficient per market, so a future capture legitimately
    carrying 0.045 (a documented volume-tier taker rate) must not break the
    parser's contract. The value itself is pinned separately, and named as
    evidence, by ``test_evidence_pin_*`` below -- so a change there reads
    "the evidence changed", not "the parser broke".
    """
    payloads = iter_captured_market_payloads()
    assert len(payloads) >= MIN_CAPTURED_MARKETS, (
        f"corpus shrank to {len(payloads)}; evidence lost?"
    )

    statuses = set()
    coefficients = set()
    for payload in payloads:
        instrument = build(payload)
        statuses.add(instrument.info[FEE_SCHEDULE_STATUS_KEY])
        coefficients.add(Decimal(instrument.info[FEE_COEFFICIENT_KEY]))

    assert statuses == {FEE_SCHEDULE_STATUS_KNOWN}
    assert all(Decimal(0) <= theta <= Decimal(1) for theta in coefficients), coefficients
    assert all(theta.is_finite() for theta in coefficients), coefficients


def test_evidence_pin_the_captured_venue_charges_six_percent_everywhere() -> None:
    """EVIDENCE PIN, not a behavioural contract.

    Recorded fact, as of the 2026-08-26 capture: every one of the captured
    market observations carries ``feeCoefficient == 0.06``, across both open
    and resolved markets. This test exists so that a venue change or a new
    capture carrying a different coefficient is NOTICED -- it is not a claim
    that 0.06 is a constant, and the parser must keep working if it changes.

    A failure here means "the evidence changed; re-verify the fee schedule
    and update this pin", never "the parser is broken".
    """
    payloads = iter_captured_market_payloads()
    assert len(payloads) >= MIN_CAPTURED_MARKETS

    assert {payload["market"]["feeCoefficient"] for payload in payloads} == {0.06}
    assert {build(payload).info[FEE_COEFFICIENT_KEY] for payload in payloads} == {"0.06"}

    # Both lifecycle stages are represented, so the coefficient is not an
    # artefact of a single market state.
    statuses = {payload["market"].get("status") for payload in payloads}
    assert "MARKET_STATUS_OPEN" in statuses
    assert "MARKET_STATUS_RESOLVED" in statuses


def test_the_fee_on_a_real_captured_market_matches_the_venue_worked_example() -> None:
    """$1.50 per 100 contracts at p=0.50, straight off a captured payload."""
    payload = json.loads(
        (RAW / "market_closed_15806_by_slug.json").read_text(encoding="utf-8")
    )
    instrument = build(payload)
    model = PolymarketUSFeeModel()
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)

    assert model.get_commission(
        order, Quantity.from_int(100), Price.from_str("0.50"), instrument
    ) == Money(Decimal("1.50"), instrument.quote_currency)


def test_a_deep_copied_payload_does_not_leak_theta_between_instruments() -> None:
    """Guards against a module-level cache masquerading as a per-market read."""
    base = load_open_market()
    other = copy.deepcopy(base)
    other["market"]["feeCoefficient"] = 0.01

    first = build(base)
    second = build(other)

    assert first.info[FEE_COEFFICIENT_KEY] == "0.06"
    assert second.info[FEE_COEFFICIENT_KEY] == "0.01"


# ---------------------------------------------------------------------------
# The model must be REACHABLE (the defect two reviews blocked on)
# ---------------------------------------------------------------------------


def test_the_fee_model_is_exported_from_the_adapter_package() -> None:
    """An accurate model nobody can import is an accurate model nobody uses.

    ``PolymarketUSFeeModel`` had ZERO callers and was not exported, while
    ``BacktestEngine.add_venue`` defaults to ``MakerTakerFeeModel``
    (``backtest/engine.pyx:643-644``). Exporting it is half the fix; barrier
    F2 in ``test_polymarket_us_fee_guard.py`` is the other half.
    """
    import breezy.adapters.polymarket_us as pkg

    assert "PolymarketUSFeeModel" in pkg.__all__
    assert pkg.PolymarketUSFeeModel is PolymarketUSFeeModel


# ---------------------------------------------------------------------------
# What the flat fields actually do to a GENERIC model (finding F2)
# ---------------------------------------------------------------------------
#
# The test this replaces computed both sides from the same `theta` inside the
# test body and asserted `theta*C*p - theta*C*p*(1-p) == theta*C*p*p`. That is
# an algebraic identity: it holds for theta = 0, 0.06 and 1 alike, constrains
# nothing about the implementation, and survives deleting `maker_fee=` and
# `taker_fee=` from `parse_binary_option` outright.
#
# What follows compares the two REAL models on the REAL instrument.


def test_the_generic_model_and_the_venue_model_disagree_by_a_known_amount() -> None:
    """Hardcoded expected pair: $3.00 generic vs $1.50 venue at p=0.50, C=100.

    Both numbers come from executing a real Nautilus fee model against a real
    parsed instrument, not from re-deriving the formula in the test body.
    """
    instrument = build(load_open_market())
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)
    args = (Quantity.from_int(100), Price.from_str("0.50"), instrument)
    usd = instrument.quote_currency

    generic = MakerTakerFeeModel().get_commission(order, *args)
    venue = PolymarketUSFeeModel().get_commission(order, *args)

    assert generic == Money(Decimal("3.00"), usd)
    assert venue == Money(Decimal("1.50"), usd)


@pytest.mark.parametrize(
    ("price", "generic", "venue"),
    [
        # p=0.10 -- the generic read is barely wrong.
        ("0.10", "0.60", "0.54"),
        ("0.50", "3.00", "1.50"),
        # p=0.90 -- the SAME venue fee as p=0.10, but 10x the generic charge.
        ("0.90", "5.40", "0.54"),
        ("0.99", "5.94", "0.06"),
    ],
)
def test_the_generic_read_destroys_the_symmetry_of_the_venue_fee(
    price: str, generic: str, venue: str
) -> None:
    """The distortion is DIRECTIONAL, not a uniform conservative haircut.

    The venue fee ``theta*C*p*(1-p)`` is SYMMETRIC about p=0.50: a YES at
    p=0.90 and a NO at p=0.10 cost the venue's customer exactly the same
    $0.54. The flat read ``theta*C*p`` is MONOTONE in p, so it charges the
    p=0.90 side $5.40 and the p=0.10 side $0.60 -- a 9x tilt toward the cheap
    side of every book.

    Relative overstatement is ``1/(1-p)``, which is UNBOUNDED as p -> 1. A
    weather bot's confident forecasts live exactly in that region. This is why
    the flat fields are defensible only because barrier F2 makes them
    unreachable, and not because they are "conservative".
    """
    instrument = build(load_open_market())
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)
    args = (Quantity.from_int(100), Price.from_str(price), instrument)
    usd = instrument.quote_currency

    assert MakerTakerFeeModel().get_commission(order, *args) == Money(Decimal(generic), usd)
    assert PolymarketUSFeeModel().get_commission(order, *args) == Money(Decimal(venue), usd)


def test_the_venue_fee_is_symmetric_where_the_generic_read_is_not() -> None:
    """Stated as the property itself, on both real models."""
    instrument = build(load_open_market())
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)
    generic = MakerTakerFeeModel()
    venue = PolymarketUSFeeModel()
    qty = Quantity.from_int(100)

    low = Price.from_str("0.10")
    high = Price.from_str("0.90")

    assert venue.get_commission(order, qty, low, instrument) == venue.get_commission(
        order, qty, high, instrument
    )
    assert generic.get_commission(order, qty, low, instrument) != generic.get_commission(
        order, qty, high, instrument
    )


def test_the_relative_overstatement_grows_without_bound_towards_certainty() -> None:
    """``generic / venue == 1/(1-p)``, measured on the real models."""
    instrument = build(load_open_market())
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)
    generic = MakerTakerFeeModel()
    venue = PolymarketUSFeeModel()
    qty = Quantity.from_int(10_000)  # large C so cent-rounding does not blur the ratio

    ratios = []
    for price in ("0.50", "0.90", "0.99"):
        px = Price.from_str(price)
        g = generic.get_commission(order, qty, px, instrument).as_decimal()
        v = venue.get_commission(order, qty, px, instrument).as_decimal()
        ratios.append(g / v)

    assert [round(r) for r in ratios] == [2, 10, 100]
    assert ratios[0] < ratios[1] < ratios[2]


# ---------------------------------------------------------------------------
# Maker side: the sign is inverted and the scope of that is bounded (F3)
# ---------------------------------------------------------------------------


def test_a_post_only_order_is_refused_rather_than_priced_with_an_inverted_sign() -> None:
    """The documented maker rate is a REBATE (-0.0125); we charge +theta.

    At C=100, p=0.50 the venue would pay us $0.3125 and this model charges
    $1.50 -- wrong by $1.8125 and, critically, wrong in SIGN. Not applying an
    unobserved rebate is the right call for a taker gate, but it makes every
    maker/posting strategy negative BY CONSTRUCTION and therefore
    unevaluable. A post-only order is an explicit maker-only intent, so it is
    refused loudly rather than silently returning a wrong-signed number.
    """
    instrument = build(load_open_market())
    model = PolymarketUSFeeModel()
    order = post_only_order(instrument, LiquiditySide.MAKER)
    assert order.is_post_only

    with pytest.raises(MakerRebateUnmodelledError, match="post-only"):
        model.get_commission(order, Quantity.from_int(100), Price.from_str("0.50"), instrument)


def test_the_post_only_refusal_is_catchable_as_the_adapter_base_error() -> None:
    instrument = build(load_open_market())
    order = post_only_order(instrument, LiquiditySide.MAKER)

    with pytest.raises(PolymarketUSError):
        PolymarketUSFeeModel().get_commission(
            order, Quantity.from_int(100), Price.from_str("0.50"), instrument
        )


def test_a_non_post_only_maker_fill_warns_loudly_instead_of_passing_silently() -> None:
    """A maker fill can still happen without post-only intent.

    Refusing every maker fill would break ordinary limit-order backtests, so
    that case is priced -- but never silently. The warning names the sign
    inversion so a result built on it cannot be read as a clean number.
    """
    instrument = build(load_open_market())
    order = order_with_liquidity(instrument, LiquiditySide.MAKER)
    assert not order.is_post_only

    with pytest.warns(UserWarning, match="REBATE"):
        commission = PolymarketUSFeeModel().get_commission(
            order, Quantity.from_int(100), Price.from_str("0.50"), instrument
        )

    assert commission == Money(Decimal("1.50"), instrument.quote_currency)


def test_a_taker_fill_neither_warns_nor_refuses() -> None:
    """Non-vacuity: the maker alarm is not an unconditional warning."""
    import warnings

    instrument = build(load_open_market())
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        commission = PolymarketUSFeeModel().get_commission(
            order, Quantity.from_int(100), Price.from_str("0.50"), instrument
        )

    assert commission == Money(Decimal("1.50"), instrument.quote_currency)


def test_the_two_flat_fields_are_equal_which_makes_the_generic_side_branch_dead() -> None:
    """``MakerTakerFeeModel`` branches on ``LiquiditySide`` and gets the same number.

    Recorded so nobody reads the generic model's maker/taker split as evidence
    that Breezy models a maker/taker split. It does not: one coefficient is
    written to both fields.
    """
    instrument = build(load_open_market())
    generic = MakerTakerFeeModel()
    args = (Quantity.from_int(100), Price.from_str("0.50"), instrument)

    maker = generic.get_commission(order_with_liquidity(instrument, LiquiditySide.MAKER), *args)
    taker = generic.get_commission(order_with_liquidity(instrument, LiquiditySide.TAKER), *args)

    assert maker == taker


# ---------------------------------------------------------------------------
# Per-fill rounding is TWO-SIDED, not conservative (F4)
# ---------------------------------------------------------------------------


def test_summing_per_fill_rounding_can_understate_the_venues_cumulative_cap() -> None:
    """The documented venue rule caps total commission at ``bankers(sum(exact))``.

    This model is stateless per fill, so it computes ``sum(bankers(exact))``.
    Those differ in BOTH directions, which is why no "never understates"
    claim may be attached to it.

    Understating counterexample: two clips whose exact fee is $0.004 each.
    Breezy charges 0.00 + 0.00 = $0.00; the venue charges
    ``bankers(0.008) = $0.01``.
    """
    instrument = build(load_open_market())
    model = PolymarketUSFeeModel()
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)

    # theta=0.06, C=1, p=0.933... is awkward; pick exact arithmetic instead:
    # 0.06 * qty * p * (1-p) = 0.004  =>  with p=0.02, 1-p=0.98:
    # 0.06 * qty * 0.0196 = 0.004  =>  qty = 3.401...  Use theta instead.
    per_clip = with_theta("0.016")  # 0.016 * 1 * 0.5 * 0.5 = 0.004 exactly
    clip_order = order_with_liquidity(per_clip, LiquiditySide.TAKER)
    args = (Quantity.from_int(1), Price.from_str("0.50"), per_clip)

    charged = model.get_commission(clip_order, *args).as_decimal()
    assert charged == Decimal("0.00"), "each clip rounds to zero on its own"

    breezy_total = charged * 2
    exact_total = Decimal("0.004") * 2
    venue_total = exact_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    assert breezy_total == Decimal("0.00")
    assert venue_total == Decimal("0.01")
    assert breezy_total < venue_total, "per-fill rounding UNDERSTATES here"

    # `order` and `instrument` are exercised so the fixture pair is not dead.
    assert model.get_commission(order, Quantity.from_int(100), Price.from_str("0.50"), instrument)


def test_summing_per_fill_rounding_can_also_overstate_by_phantom_cents() -> None:
    """The mirror image: many tiny fills each rounding UP.

    100 clips of exact fee $0.00500 each round to $0.01 apiece under banker's
    rounding away from an even cent, so Breezy charges ~$0.50 against a venue
    cap of ``bankers(0.5) = $0.50``... which happens to agree. Push the exact
    per-clip fee slightly above the half-cent and the divergence is visible.
    """
    exact_per_clip = Decimal("0.006")
    clips = 100
    breezy_total = exact_per_clip.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN) * clips
    venue_total = (exact_per_clip * clips).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    assert breezy_total == Decimal("1.00")
    assert venue_total == Decimal("0.60")
    assert breezy_total > venue_total, "per-fill rounding OVERSTATES here"


def test_the_model_documents_the_two_sided_rounding_error_and_claims_no_safe_direction() -> None:
    """Prose contract: no "never understates" claim may survive on this model.

    A reader who takes a blanket conservatism claim at face value will size
    against a number that is not conservative. Asserted on the docstring so
    the claim cannot quietly reappear.
    """
    doc = PolymarketUSFeeModel.__doc__ or ""
    lowered = doc.lower()

    # The exact claim that was there before and is now known to be false.
    assert "understates it nowhere" not in lowered
    # The venue's actual rule, and the fact that this model approximates it.
    assert "cumulative" in lowered, "the venue's cumulative cap must be named"
    assert "both directions" in lowered, "the error is two-sided and must say so"
    # An explicit disclaimer, so silence cannot be read as endorsement.
    assert "no blanket" in lowered, "blanket conservatism must be disclaimed outright"


# ---------------------------------------------------------------------------
# Signature drift against the immutable base (F9)
# ---------------------------------------------------------------------------


def test_the_get_commission_signature_matches_the_immutable_cython_base() -> None:
    """``# type: ignore[misc]`` makes the base ``Any``, so mypy checks nothing.

    ``backtest/models/fee.pxd`` declares
    ``cpdef Money get_commission(self, Order, Quantity, Price, Instrument)``.
    A Nautilus bump that reorders or adds a parameter would produce zero
    static errors and zero test failures here, then a ``TypeError`` at the
    first fill. Pinned so the bump fails RED instead.
    """
    import inspect

    ours = inspect.signature(PolymarketUSFeeModel.get_commission)
    base = inspect.signature(FeeModel.get_commission)

    assert list(ours.parameters) == list(base.parameters)
    assert list(base.parameters) == ["self", "order", "fill_qty", "fill_px", "instrument"]


def test_the_model_is_callable_exactly_the_way_the_engine_calls_it() -> None:
    """Nautilus invokes the fee model by KEYWORD, at both of its call sites.

    ``engine.pyx:7886`` (the ordinary fill path) and ``:7672`` (the spread-leg
    path) both call::

        self._fee_model.get_commission(
            order=..., fill_qty=..., fill_px=..., instrument=...,
        )

    against a ``cdef FeeModel _fee_model`` (``engine.pxd:368``). Parameter
    NAMES are therefore load-bearing, not merely positional order: a bump
    that renamed ``fill_px`` would keep every positional test in this file
    green and fail at the first real fill. Pinned by calling the model the
    same way the engine does.
    """
    instrument = build(load_open_market())
    model = PolymarketUSFeeModel()
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)

    by_keyword = model.get_commission(
        order=order,
        fill_qty=Quantity.from_int(100),
        fill_px=Price.from_str("0.50"),
        instrument=instrument,
    )

    assert by_keyword == Money(Decimal("1.50"), instrument.quote_currency)


def test_the_python_override_wins_over_the_bases_not_implemented_body() -> None:
    """The base's own body raises ``NotImplementedError`` (``fee.pyx:64``).

    Reaching a real number through normal attribute dispatch proves the
    subclass override is what Nautilus's ``cpdef`` machinery resolves. (The
    UNBOUND form ``FeeModel.get_commission(model, ...)`` deliberately calls
    the base implementation instead and is NOT the engine's path -- asserted
    here so nobody mistakes it for a stronger check and writes a false one.)
    """
    instrument = build(load_open_market())
    model = PolymarketUSFeeModel()
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)
    args = (Quantity.from_int(100), Price.from_str("0.50"), instrument)

    assert model.get_commission(order, *args) == Money(Decimal("1.50"), instrument.quote_currency)

    with pytest.raises(NotImplementedError):
        FeeModel.get_commission(model, order, *args)


# ---------------------------------------------------------------------------
# Coefficient typing: booleans are refused with an ACCURATE message (F6)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [True, False])
def test_a_boolean_coefficient_is_refused_and_not_reported_as_absent(raw: bool) -> None:
    """``True``/``False`` are present values, so "is absent" was a wrong message.

    ``bool`` is a subclass of ``int``, so a boolean slipping into the info
    dict is a plausible round-trip accident, and ``Decimal(str(True))``
    raises ``InvalidOperation`` -- meaning the old ``isinstance(raw, bool)``
    guard only changed which (inaccurate) message the operator saw.
    """
    instrument = build(load_open_market())
    info = dict(instrument.info)
    info[FEE_SCHEDULE_STATUS_KEY] = FEE_SCHEDULE_STATUS_KNOWN
    info[FEE_COEFFICIENT_KEY] = raw
    tampered = rebuild_with_info(instrument, info)

    order = order_with_liquidity(instrument, LiquiditySide.TAKER)

    with pytest.raises(FeeScheduleUnknownError) as excinfo:
        PolymarketUSFeeModel().get_commission(
            order, Quantity.from_int(100), Price.from_str("0.50"), tampered
        )

    message = str(excinfo.value)
    assert "absent" not in message, "a present boolean must not be reported as absent"
    assert "bool" in message


def test_a_genuinely_absent_coefficient_still_says_absent() -> None:
    """Non-vacuity for the message split above."""
    instrument = build(load_open_market())
    info = dict(instrument.info)
    info[FEE_SCHEDULE_STATUS_KEY] = FEE_SCHEDULE_STATUS_KNOWN
    info[FEE_COEFFICIENT_KEY] = None
    tampered = rebuild_with_info(instrument, info)

    order = order_with_liquidity(instrument, LiquiditySide.TAKER)

    with pytest.raises(FeeScheduleUnknownError, match="absent"):
        PolymarketUSFeeModel().get_commission(
            order, Quantity.from_int(100), Price.from_str("0.50"), tampered
        )


# ---------------------------------------------------------------------------
# R-8-PRE-1 -- venue has NO minimum taker fee; 1-contract bounds
# ---------------------------------------------------------------------------
#
# See docs/evidence/venue/polymarket_us/OQ8_MINIMUM_FEE_2026-09-04.md: the
# venue's fee docs state "Can fees ever be zero? Yes." with no floor, and that
# fees are banker's-rounded to the cent. These two tests pin the 1-contract
# bounds that R-8's precondition relies on: min = $0.00, and the per-fill
# taker charge at C=1 is bounded above by bankers(theta * p * (1-p)), which is
# $0.02 at the maximum p=0.50 for the docs' published theta=0.06. Both are
# expected to pass immediately -- they pin EXISTING model behaviour, not new
# code.


def test_one_contract_at_one_cent_is_charged_zero_fee_documented_no_minimum() -> None:
    """No minimum taker fee (OQ-8): 1 contract at p=0.01 rounds down to $0.00.

    theta * 1 * 0.01 * 0.99 = 0.000594 -> bankers-rounds to $0.00. Confirms
    the venue's own FAQ claim ("fees can round down to $0.00") against this
    model at the documented theta=0.06, per
    docs/evidence/venue/polymarket_us/OQ8_MINIMUM_FEE_2026-09-04.md.
    """
    instrument = with_theta("0.06")
    model = PolymarketUSFeeModel()
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)

    assert model.get_commission(
        order, Quantity.from_int(1), Price.from_str("0.01"), instrument
    ) == Money(Decimal("0.00"), instrument.quote_currency)


@pytest.mark.parametrize("price", ["0.12", "0.25", "0.50", "0.75", "0.99"])
def test_one_contract_taker_fee_is_bounded_by_two_cents_at_the_p_half_maximum(
    price: str,
) -> None:
    """1-contract taker fee bound (R-8-PRE-1 precondition, OQ-8).

    ``theta * p * (1-p)`` is concave and maximised at ``p = 0.50``, so the
    per-fill charge at ``C = 1`` and the docs' published ``theta = 0.06`` is
    bounded above by ``bankers(0.06 * 0.5 * 0.5) = $0.02`` for every price in
    ``[0, 1]``. Each case is asserted equal to the model's own banker's
    rounding of the exact figure, not just the bound, so this also pins the
    exact 1-contract fee at each price. See
    docs/evidence/venue/polymarket_us/OQ8_MINIMUM_FEE_2026-09-04.md.
    """
    theta = Decimal("0.06")
    instrument = with_theta("0.06")
    model = PolymarketUSFeeModel()
    order = order_with_liquidity(instrument, LiquiditySide.TAKER)

    p = Decimal(price)
    exact = theta * p * (Decimal(1) - p)
    expected = exact.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)

    charged = model.get_commission(
        order, Quantity.from_int(1), Price.from_str(price), instrument
    )

    assert charged == Money(expected, instrument.quote_currency)
    assert charged.as_decimal() <= Decimal("0.02")
