"""Pre-trade taker cost, in PROBABILITY units, as two separately-named terms.

WHY THIS EXISTS -- NAUTILUS NULL HYPOTHESIS (L-1), CHECKED FIRST
----------------------------------------------------------------
Nautilus's cost surface is :class:`nautilus_trader.backtest.models.FeeModel`,
whose entire API is one method
(``.venv/lib/python3.13/site-packages/nautilus_trader/backtest/models/fee.pyx:38``)::

    cpdef Money get_commission(self, Order order, Quantity fill_qty,
                               Price fill_px, Instrument instrument)

It prices a **fill that has already happened**: it requires an ``Order``
object, a filled quantity and a filled price, and returns ``Money``. There is
no API anywhere in the installed package that answers "what would this cost if
I paid ``a``?" for a *contemplated* price, and none that answers in
probability units. The three concrete models -- ``MakerTakerFeeModel``
(``fee.pyx:67``), ``FixedFeeModel`` (``:115``) and ``PerContractFeeModel``
(``:168``) -- are flat-rate-on-notional or flat-per-contract, so none of them
can express a ``p * (1 - p)`` term at all. **The gap is real**; this module is
the smallest pure helper that closes it.

``nautilus_trader/adapters/polymarket/fee_model.py::PolymarketFeeModel``
implements the right formula and is nonetheless **forbidden and unsafe**: it
lives in the Polymarket **.com** adapter, which the import-linter contract
"Breezy never imports the Nautilus Polymarket .com adapter" blocks; it reads
the flat ``instrument.taker_fee`` field and returns ``Money(0)`` when it is
``<= 0`` -- fail-OPEN to a free venue, the exact posture
``breezy.adapters.polymarket_us.fees`` refuses; and it credits maker rebates
(``infer_maker_rebate_rate``, ``fee_model.py:132-176``), which
``MakerRebateUnmodelledError`` says Breezy must not model until a real maker
fill has been observed.

This helper does **not** replace
:class:`breezy.adapters.polymarket_us.fees.PolymarketUSFeeModel`, which stays
the settlement-time authority. It is the gate-time estimate of the same
formula, and the two are pinned to each other by an agreement test
(``tests/unit/test_weather_common_costs.py``) so they cannot drift.

WHY TWO TERMS AND NOT ONE SCALAR
--------------------------------
The venue fee and the execution term behave OPPOSITELY as ``p -> 1``: at
ask 0.99 with ``theta = 0.06`` the fee is 0.000594 and vanishing, while
slippage does not vanish at all. A single "total cost" scalar cannot express
that, and it is precisely the field in which the unsafe configuration gets
written -- ``transaction_cost_prob = 0.0006`` with a 0.005 edge floor trades
at ask 0.99, which BL-19 s8.2 computes as **-0.003698** after one tick of
slippage. Keeping the terms separate, named, and pure means the total cost is
never writable, only derivable.

``slippage_prob`` is UNMEASURED. See
``docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md`` s2 and s8.2, and
the instrumentation obligation in s8.5 that is expected to replace the 0.01
placeholder with a figure derived from realised fills. Callers put
``fee_coefficient``, ``fee_prob`` and ``slippage_prob`` on the emitted
decision's metadata precisely so that replacement is possible offline, without
re-running a capture.

VENUE NEUTRALITY
----------------
Nothing here imports an adapter or names a venue. ``theta`` arrives by
injection through :class:`FeeCoefficientSource`, mirroring the pattern
``weather_common.forecast_source`` already established: a plain non-Nautilus
``Protocol``, a REQUIRED constructor argument at the consuming strategy, and a
named error rather than a default. That keeps the eventual move from
Polymarket.us to Kalshi.com a wiring change, not a strategy rewrite.
"""

from __future__ import annotations

import math
from typing import Protocol, runtime_checkable

__all__ = [
    "FeeCoefficientSource",
    "UnknownFeeScheduleError",
    "trade_cost_prob",
    "venue_fee_prob",
]


class UnknownFeeScheduleError(ValueError):
    """A cost computation was reached with no fee coefficient for the market.

    Raised by a :class:`FeeCoefficientSource` implementation rather than
    returning a default. An unresolved fee schedule is a NO-TRADE, never a
    free trade: ``breezy.adapters.polymarket_us.fees`` is explicit that "a
    market whose coefficient we could not parse raises rather than trading
    free", and a strategy-side default would reintroduce exactly the fallback
    the adapter refuses.
    """


@runtime_checkable
class FeeCoefficientSource(Protocol):
    """Resolves one market's venue fee coefficient (``theta``).

    A PULL seam, not a push: called once per instrument at ``on_start``,
    because a fee schedule is a static property of the market and cannot
    appear mid-session. Implementations MUST raise
    :class:`UnknownFeeScheduleError` rather than return a default -- mirroring
    ``breezy.adapters.polymarket_us.fees._fee_coefficient``, which raises
    rather than trading free.
    """

    def fee_coefficient_for(self, instrument_id: str) -> float:
        """Return ``theta`` for ``instrument_id``, or raise.

        Raises
        ------
        UnknownFeeScheduleError
            When the market carries no usable coefficient. Never returns a
            fallback value.
        """
        ...


def venue_fee_prob(*, executable_price: float, fee_coefficient: float) -> float:
    """``theta * p * (1 - p)``, in probability units, per contract.

    Pure. Non-negative on ``[0, 1]``; symmetric about 0.5; maximal at 0.5;
    monotone decreasing on ``[0.5, 1]``.

    Raises
    ------
    ValueError
        If ``executable_price`` is outside ``[0, 1]`` -- outside that range the
        ``p * (1 - p)`` term goes NEGATIVE and would pay a rebate
        (``fees.py:178-184`` refuses for the same reason) -- or if
        ``fee_coefficient`` is non-finite or outside ``[0, 1]``, the same range
        ``fees.py:249-253`` validates. ``theta = 0`` is a legitimate OBSERVED
        value and is allowed; an UNRESOLVED schedule is refused at resolution
        time by :class:`FeeCoefficientSource`, not here.
    """
    if not math.isfinite(executable_price) or executable_price < 0.0 or executable_price > 1.0:
        raise ValueError(
            f"Executable price {executable_price!r} is outside the binary-option range "
            "[0, 1]; refusing to compute a venue fee that would turn negative and pay "
            "a rebate on a bad tick",
        )
    if not math.isfinite(fee_coefficient) or fee_coefficient < 0.0 or fee_coefficient > 1.0:
        raise ValueError(
            f"Fee coefficient {fee_coefficient!r} is outside [0, 1] or non-finite; "
            "refusing to price a trade against an unusable coefficient",
        )
    return fee_coefficient * executable_price * (1.0 - executable_price)


def trade_cost_prob(
    *,
    executable_price: float,
    fee_coefficient: float,
    slippage_prob: float,
) -> float:
    """``venue_fee_prob(...) + slippage_prob``.

    The two terms are kept SEPARATE and separately named because they behave
    oppositely as ``p -> 1``: the fee vanishes (0.000594 at 0.99), the
    execution term does not. ``slippage_prob`` is UNMEASURED -- see
    ``docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md`` s2 and s8.2,
    and the instrumentation in s8.5 that is expected to replace the 0.01
    placeholder with a figure derived from realised fills.

    Raises
    ------
    ValueError
        On any input :func:`venue_fee_prob` refuses, or a negative or
        non-finite ``slippage_prob``. A negative execution term is a rebate on
        execution; there is no such thing.
    """
    if not math.isfinite(slippage_prob) or slippage_prob < 0.0:
        raise ValueError(
            f"Slippage {slippage_prob!r} is negative or non-finite; a negative "
            "execution term is a rebate on execution and there is no such thing",
        )
    return venue_fee_prob(
        executable_price=executable_price,
        fee_coefficient=fee_coefficient,
    ) + slippage_prob
