"""Native Nautilus fee model for Polymarket.us binary options.

NULL HYPOTHESIS, checked before this module was written. Nautilus DOES ship a
fee model with this exact formula: ``nautilus_pyo3.ProbabilityPriceFeeModel``
("Applies ``qty * fee_rate * p * (1 - p)`` using the instrument's maker or
taker fee rate", for ``BinaryOption`` instruments quoted on ``[0, 1]``). It is
unusable here for one structural reason: it lives on the **PyO3** surface,
while Breezy runs on the **Cython** surface, and ``BacktestEngine.add_venue``
type-checks its ``fee_model`` argument against the Cython ``FeeModel``
(``backtest/engine.pyx:651`` -> ``Condition.type``). Passing the PyO3 object
raises ``TypeError``. That rejection is pinned by a contract test
(``tests/unit/test_polymarket_us_fee_model.py``), so if a future Nautilus
unifies the surfaces the test fails RED and this module should be DELETED
rather than maintained beside the framework's own.

What remains genuinely ours is therefore a thin subclass of the native
``FeeModel`` extension point -- no parallel abstraction, no reimplementation.

**This model must be WIRED, or it does nothing.** ``BacktestEngine.add_venue``
defaults ``fee_model`` to ``MakerTakerFeeModel()``
(``backtest/engine.pyx:643-644``), and the ``BacktestNode`` path reaches the
same default through ``BacktestVenueConfig(fee_model=None)`` ->
``get_fee_model`` -> ``node.py:401``. An accurate model that no venue is given
is an accurate model that never runs, while the generic one silently reads
``instrument.taker_fee`` as a flat notional rate. Barrier F2 in
``tests/unit/test_polymarket_us_fee_guard.py`` fails the suite for any module
under ``src/`` or ``scripts/`` that constructs a venue without passing
``fee_model=PolymarketUSFeeModel()``.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation

from nautilus_trader.backtest.models import FeeModel
from nautilus_trader.model.enums import LiquiditySide
from nautilus_trader.model.instruments import Instrument
from nautilus_trader.model.objects import Currency, Money, Price, Quantity
from nautilus_trader.model.orders import Order

from breezy.adapters.polymarket_us.errors import (
    FeeScheduleUnknownError,
    MakerRebateUnmodelledError,
)
from breezy.adapters.polymarket_us.parsing import (
    FEE_COEFFICIENT_KEY,
    assert_fee_schedule_known,
)

__all__ = ["PolymarketUSFeeModel", "polymarket_us_fee"]

_ZERO = Decimal(0)
_ONE = Decimal(1)

#: Emitted once per call site when a maker fill is priced at the taker
#: coefficient. Deliberately carries no instrument identifier, so Python's
#: default warning filter collapses it to one line per location rather than
#: one per market.
_MAKER_SIGN_WARNING = (
    "Pricing a Polymarket.us MAKER fill at the taker coefficient (+theta). "
    "The venue's documented maker coefficient is a REBATE (-0.0125), i.e. "
    "income, so this figure is wrong in SIGN, not merely in magnitude. Any "
    "result that depends on maker economics is unevaluable; treat it as a "
    "taker-side number only."
)


# `backtest/models/fee` is a compiled Cython extension and ships no `.pyi`, so
# mypy resolves `FeeModel` to `Any` and rejects the subclass under `strict`.
# Nautilus is IMMUTABLE, so the stub cannot be added upstream and the ignore is
# scoped to this single line. Because the ignore makes the base `Any`, mypy
# also cannot verify that `get_commission`'s signature still matches
# `backtest/models/fee.pxd`; that is pinned instead by
# `test_the_get_commission_signature_matches_the_immutable_cython_base` and by
# `test_the_model_is_callable_exactly_the_way_the_engine_calls_it`, because
# Nautilus invokes this method BY KEYWORD at both of its call sites
# (`backtest/engine.pyx:7672` and `:7886`), making parameter NAMES load-bearing.
class PolymarketUSFeeModel(FeeModel):  # type: ignore[misc]
    """Compute Polymarket.us fees from the market's OWN ``feeCoefficient``.

    The venue publishes one per-market coefficient, ``theta``, and charges
    ``theta * C * p * (1 - p)``, where ``C`` is the contract count and ``p``
    the fill price in ``[0, 1]``. The function is concave with a maximum at
    ``p = 0.50``, giving the venue's own worked figure of $1.50 per 100
    contracts at ``theta = 0.06``. Note that it is also SYMMETRIC about
    ``p = 0.50``: a YES at 0.90 and a NO at 0.10 cost the same $0.54.

    ``theta`` is read per market from ``instrument.info[FEE_COEFFICIENT_KEY]``.
    There is deliberately NO module-level default and no fallback: a market
    whose coefficient we could not parse raises rather than trading free.

    Maker treatment, and the exact scope of its conservatism
    --------------------------------------------------------
    The payload carries a single coefficient with no maker/taker split, so
    charging both sides at it is an INFERENCE, not a venue fact. The venue
    documentation snapshot describes a maker coefficient of **-0.0125 -- a
    REBATE, i.e. income** -- plus volume-tiered taker discounts. Neither is
    applied here, because applying an unobserved discount would understate
    cost.

    That inference is safe **for a taker gate and only for a taker gate.** At
    ``C = 100``, ``p = 0.50`` the venue would pay $0.3125 while this model
    charges $1.50: wrong by $1.8125 and wrong in SIGN. Every maker or posting
    strategy backtested against it is therefore negative BY CONSTRUCTION and
    unevaluable -- not merely pessimistic. Accordingly:

    * a **post-only** order (explicit maker-only intent) is REFUSED with
      :class:`~breezy.adapters.polymarket_us.errors.MakerRebateUnmodelledError`
      rather than priced with an inverted sign;
    * any other **maker** fill is priced, but emits a loud ``UserWarning``, so
      a number built on it cannot be mistaken for a clean one.

    Because one coefficient is written to both flat fields,
    ``MakerTakerFeeModel``'s own ``LiquiditySide`` branch is DEAD on these
    instruments -- it returns the same figure either way. Do not read that
    branch as evidence that Breezy models a maker/taker split. It does not.

    Rounding, and why it is TWO-SIDED rather than conservative
    ---------------------------------------------------------
    The venue's documented rule is banker's rounding to $0.01
    (``polymarket-us-integration`` skill, "Fee Formula"), applied to the
    **cumulative** fee for a trade. This model is stateless per fill, so it
    computes ``sum(bankers(exact_per_fill))`` where the venue computes
    ``bankers(sum(exact))``. Those differ in **both directions**:

    * *Understating.* Two clips whose exact fee is $0.004 each: this model
      charges ``0.00 + 0.00 = $0.00``; the venue charges
      ``bankers(0.008) = $0.01``.
    * *Overstating.* Many small clips each rounding up accumulate phantom
      cents against a much smaller cumulative cap.

    So **no blanket "never understates" claim holds for this model**, and none
    is made. Implementing the cumulative rule needs per-trade state that the
    ``FeeModel`` extension point does not carry; until that is designed, the
    approximation is documented rather than hidden. Rounding is applied
    explicitly BEFORE ``Money`` is constructed, so the rounding MODE is ours
    and is testable; ``Money`` would otherwise impose its own on the
    half-cent cases.

    The flat instrument fields are NOT a fallback for this model
    -----------------------------------------------------------
    ``parse_binary_option`` writes ``theta`` into ``maker_fee``/``taker_fee``.
    Read as a flat notional rate those give ``theta * C * p`` against the
    venue's ``theta * C * p * (1 - p)``: absolute error ``theta * C * p^2``,
    **relative error ``1/(1 - p)``, unbounded as ``p -> 1``**, and the venue
    fee's symmetry destroyed. That is a directional tilt toward the cheap side
    of every book, not a conservative haircut, and it is worst exactly where a
    weather bot's confident forecasts sit. The fields hold ``theta`` rather
    than ``Decimal(0)`` only so that a circumvention errs upward instead of
    reading as a free venue; their real defence is barrier F2, which keeps a
    default fee model off every backtest venue.
    """

    def get_commission(
        self,
        order: Order,
        fill_qty: Quantity,
        fill_px: Price,
        instrument: Instrument,
    ) -> Money:
        """Return ``theta * C * p * (1 - p)`` in the instrument's quote currency."""
        side = order.liquidity_side
        if side not in (LiquiditySide.MAKER, LiquiditySide.TAKER):
            raise ValueError(
                "Refusing to price a Polymarket.us fill with no maker/taker "
                f"liquidity side (was {side!r}); a sideless fill is an upstream "
                "bug, never a free trade"
            )

        if side == LiquiditySide.MAKER:
            self._refuse_or_warn_on_maker(order, instrument)

        return polymarket_us_fee(instrument, fill_qty, fill_px)

    @staticmethod
    def _refuse_or_warn_on_maker(order: Order, instrument: Instrument) -> None:
        """Fail closed on maker-only intent; warn loudly on an incidental maker fill.

        See the class docstring: the modelled maker fee has the WRONG SIGN
        relative to the venue's documented rebate, so a strategy that exists
        to post liquidity cannot be evaluated against it at all. A limit order
        that merely happened to rest is a different case -- refusing it would
        break ordinary backtests -- so it is priced, but never silently.
        """
        if order.is_post_only:
            raise MakerRebateUnmodelledError(
                f"Refusing to price a post-only (maker-only) Polymarket.us order for "
                f"{instrument.id}: the venue's documented maker coefficient is a "
                "REBATE (-0.0125) and this model charges the taker coefficient "
                "(+theta), so the fee would be wrong in SIGN. A posting strategy "
                "backtested on it is negative by construction and unevaluable. "
                "Observe a real maker fill and record the venue's actual maker "
                "treatment before enabling this path."
            )
        warnings.warn(_MAKER_SIGN_WARNING, UserWarning, stacklevel=3)


def polymarket_us_fee(instrument: Instrument, quantity: Quantity, price: Price) -> Money:
    """Return ``theta * C * p * (1 - p)`` for ``instrument``, banker's-rounded.

    The venue's fee arithmetic, with no liquidity-side opinion of its own --
    that judgement belongs to the caller, because the two callers make it
    differently and for different reasons:

    * :meth:`PolymarketUSFeeModel.get_commission` has an ``Order`` and can
      distinguish post-only (maker-only) INTENT from an incidental maker fill;
    * ``PolymarketUSExecutionClient.calculate_commission``
      (``execution/client.pyx:165``, the native reconciliation extension point)
      has only a ``LiquiditySide`` and refuses MAKER outright, because Breezy
      is taker-only and R-3 already refuses maker fills at the mapper.

    Extracted so those two share ONE implementation of the fee. A second copy
    in the execution client is how the reconciled fee and the modelled fee
    drift apart, and the whole reason ``assert_fee_schedule_known`` exists is
    that a fee nobody can point at becomes an implied zero.

    Raises
    ------
    FeeScheduleUnknownError
        If this market's ``theta`` is absent or unusable. Never defaulted --
        an unknown schedule refuses; it does not trade free.
    ValueError
        If ``price`` is outside ``[0, 1]``.
    """
    theta = _fee_coefficient(instrument)

    fill_price = price.as_decimal()
    if fill_price < _ZERO or fill_price > _ONE:
        # Outside [0, 1] the p*(1-p) term turns NEGATIVE and would pay us
        # a rebate. Refuse rather than manufacture income from a bad tick.
        raise ValueError(
            f"Fill price {fill_price} is outside the binary-option range [0, 1]; "
            f"refusing to compute a Polymarket.us fee for {instrument.id}"
        )

    exact = theta * quantity.as_decimal() * fill_price * (_ONE - fill_price)
    return Money(_round_bankers(exact, instrument.quote_currency), instrument.quote_currency)


def _fee_coefficient(instrument: Instrument) -> Decimal:
    """Read and re-validate this market's ``theta``.

    The status marker is checked first (barrier F1's guard), but passing it is
    NOT sufficient: the marker lives in a loosely-typed ``info`` dict that a
    hand-built or round-tripped instrument can carry without a usable value.
    The coefficient is therefore re-validated here, so the marker can never on
    its own license a computation.
    """
    assert_fee_schedule_known(instrument)

    info = getattr(instrument, "info", None)
    raw = info.get(FEE_COEFFICIENT_KEY) if isinstance(info, Mapping) else None
    if raw is None:
        raise FeeScheduleUnknownError(
            f"Refusing to compute Polymarket.us fees for {instrument.id}: "
            f"{FEE_COEFFICIENT_KEY!r} is absent despite a KNOWN fee schedule"
        )
    if isinstance(raw, bool):
        # `bool` is a subclass of `int`, so a boolean is a plausible
        # round-trip accident here. It is a PRESENT value, so the "is absent"
        # message above would be actively misleading. `Decimal(str(True))`
        # would also raise `InvalidOperation` and land in the "not a valid
        # decimal" branch below, which is true but says nothing useful about
        # a `True`; this branch exists purely to name what actually happened.
        raise FeeScheduleUnknownError(
            f"Refusing to compute Polymarket.us fees for {instrument.id}: "
            f"{FEE_COEFFICIENT_KEY!r} is a bool ({raw!r}), not a decimal "
            "coefficient; a boolean here is a round-trip or serialisation bug"
        )
    try:
        theta = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        raise FeeScheduleUnknownError(
            f"Refusing to compute Polymarket.us fees for {instrument.id}: "
            f"{FEE_COEFFICIENT_KEY!r} is not a valid decimal"
        ) from None
    if not theta.is_finite() or theta < _ZERO or theta > _ONE:
        raise FeeScheduleUnknownError(
            f"Refusing to compute Polymarket.us fees for {instrument.id}: "
            f"{FEE_COEFFICIENT_KEY!r} {theta!s} is outside [0, 1]"
        )
    return theta


def _round_bankers(value: Decimal, currency: Currency) -> Decimal:
    """Quantise to the currency's precision using the venue's rounding rule.

    Applied per fill, which is an APPROXIMATION of the venue's cumulative cap
    with error in both directions -- see the class docstring. Done here rather
    than left to ``Money`` so the rounding MODE is ours and is testable.
    """
    quantum = Decimal(1).scaleb(-currency.precision)
    return value.quantize(quantum, rounding=ROUND_HALF_EVEN)
