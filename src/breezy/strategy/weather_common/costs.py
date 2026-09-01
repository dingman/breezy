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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from breezy.strategy.weather_common.ladder import walk_ask_ladder

__all__ = [
    "INSTRUMENT_INFO_FEE_COEFFICIENT_KEY",
    "DepthAwareTradeCost",
    "FeeCoefficientSource",
    "NoExecutableDepthError",
    "UnknownFeeScheduleError",
    "depth_aware_trade_cost_prob",
    "fee_coefficient_from_info",
    "trade_cost_prob",
    "venue_fee_prob",
]

#: The ``Instrument.info`` key under which a venue adapter publishes that
#: market's OWN fee coefficient.
#:
#: RE-DECLARED HERE RATHER THAN IMPORTED, deliberately. This module names no
#: venue (see the module docstring), and importing
#: ``breezy.adapters.polymarket_us.parsing.FEE_COEFFICIENT_KEY`` would weld
#: every strategy that reads a cost to one exchange -- against the
#: Polymarket.us -> Kalshi.com portability priority. The two spellings are
#: pinned equal by
#: ``test_the_venue_neutral_info_key_is_the_one_the_adapter_writes``, which is
#: the anti-drift guarantee the import would otherwise have provided. A future
#: venue's wiring publishes the SAME key.
INSTRUMENT_INFO_FEE_COEFFICIENT_KEY: Final[str] = "fee_coefficient"


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


class NoExecutableDepthError(ValueError):
    """A cost was requested against a book that offers no real depth.

    Raised by :func:`depth_aware_trade_cost_prob` rather than falling back to
    the level-0 tick or to a zero price. Same posture as
    :class:`UnknownFeeScheduleError`: an unanswerable input is a NO-TRADE,
    never a free or optimistically-priced one. Note that Nautilus's own
    ``OrderBook.get_avg_px_for_quantity`` takes the opposite posture and
    returns ``0.0`` when it cannot compute an average (``book.pyx:578-580``),
    which is precisely why Breezy does not route through it -- see
    :mod:`breezy.strategy.weather_common.ladder`.
    """


@dataclass(frozen=True, slots=True)
class DepthAwareTradeCost:
    """Taker cost for one intended size, priced off the ladder it consumes.

    Every price field is in PROBABILITY units (raw venue prices already
    multiplied by ``price_scale``). The two cost terms stay separately named
    for the reason the module docstring gives: they behave oppositely as
    ``p -> 1``, and a single writable "total cost" scalar is the field in
    which the unsafe configuration gets written.
    """

    #: VWAP of the ladder actually consumed -- the price the order would pay.
    executable_price: float
    #: Level-0 ask, kept so the concession is legible and the old figure is
    #: still on the record rather than silently replaced.
    top_of_book_price: float
    #: Worst rung the fill would touch, in PROBABILITY units. The execution
    #: layer prices its marketable limit off this, never off the VWAP: a limit
    #: at the average price stops halfway up the ladder it was priced for.
    worst_price: float
    #: ``theta * p * (1 - p)`` at ``executable_price``, never at level 0.
    fee_prob: float
    #: ``max(slippage_floor_prob, executable_price - top_of_book_price)``.
    slippage_prob: float
    #: ``fee_prob + slippage_prob``. Derived, never writable.
    total_prob: float
    #: What the recorded ladder could actually supply -- the largest size a
    #: caller may honestly claim.
    fillable_quantity: float
    requested_quantity: float
    #: The ladder ran out before the request was absorbed.
    depth_exhausted: bool


def depth_aware_trade_cost_prob(
    *,
    ask_levels: Sequence[tuple[float, float]],
    quantity: float,
    price_scale: float,
    fee_coefficient: float,
    slippage_floor_prob: float,
) -> DepthAwareTradeCost:
    """:func:`trade_cost_prob`, but priced at the VWAP of the size being taken.

    WHY THE FLAT TERM IS THE WRONG SHAPE, NOT MERELY THE WRONG VALUE (BL-25 D1)
    --------------------------------------------------------------------------
    :func:`trade_cost_prob` adds a CONSTANT ``slippage_prob`` to a fee priced
    at the level-0 ask. Measured over the captured ladder at
    ``~/.local/share/breezy/catalog/quote_tape/polymarket_us`` (``data/`` AND
    ``live/``): a $24.53 order exceeds level-0 ask size in **57.4%** of
    snapshots and exhausts all ten recorded levels in **6.5%**; realised
    walk-the-book slippage (VWAP - level-0 ask) is 0.0026 at the median but
    **0.137 at p90** and **0.661 at p99**, and **36.0%** of snapshots exceed
    the flat 0.01 floor from the recorded book ALONE -- before any market
    impact or adverse selection. Cost therefore depends on SIZE, which no
    additive constant can express.

    ``ask_levels`` is ``(price, size)`` best-first in RAW venue units (see
    :mod:`breezy.strategy.weather_common.ladder`); ``price_scale`` converts to
    probability units, exactly as ``MarketQuote.implied_ask`` does.

    THE FLOOR IS A MAX, NEVER A REPLACEMENT. ``slippage_floor_prob`` is the
    shipped execution term (one tick on this venue's 0.01 grid, and still
    UNMEASURED as an impact/adverse-selection estimate -- BL-19 s8.2/s8.5).
    The book-derived concession can only RAISE it: a deep flat book computes
    zero concession, and a floor of zero there would restore the exact unsafe
    configuration the structured cost term exists to forbid.

    Raises
    ------
    ValueError
        On anything :func:`venue_fee_prob` refuses -- an unusable
        ``fee_coefficient`` is refused here exactly as it is there, and there
        is deliberately NO default for it, so an unresolved schedule cannot be
        priced through this function either. Also on a negative or non-finite
        ``slippage_floor_prob`` or a non-positive/non-finite ``price_scale``.
    NoExecutableDepthError
        When ``ask_levels`` offers no real depth, or ``quantity`` is
        non-positive.
    """
    if not math.isfinite(slippage_floor_prob) or slippage_floor_prob < 0.0:
        raise ValueError(
            f"Slippage floor {slippage_floor_prob!r} is negative or non-finite; a "
            "negative execution term is a rebate on execution and there is no such thing",
        )
    if not math.isfinite(price_scale) or price_scale <= 0.0:
        raise ValueError(
            f"Price scale {price_scale!r} is non-positive or non-finite; refusing to "
            "convert a raw venue ladder into probability units through it",
        )
    walk = walk_ask_ladder(ask_levels, quantity)
    if walk is None:
        raise NoExecutableDepthError(
            f"No executable ask depth for a request of {quantity!r} contracts; refusing "
            "to price a fill against a book that cannot supply one. An empty book is a "
            "no-trade, never a zero-cost trade",
        )
    executable_price = walk.vwap_price * price_scale
    top_of_book_price = walk.top_of_book_price * price_scale
    worst_price = walk.worst_price * price_scale
    slippage_prob = max(slippage_floor_prob, walk.price_concession * price_scale)
    fee_prob = venue_fee_prob(
        executable_price=executable_price,
        fee_coefficient=fee_coefficient,
    )
    return DepthAwareTradeCost(
        executable_price=executable_price,
        top_of_book_price=top_of_book_price,
        worst_price=worst_price,
        fee_prob=fee_prob,
        slippage_prob=slippage_prob,
        total_prob=fee_prob + slippage_prob,
        fillable_quantity=walk.filled_quantity,
        requested_quantity=walk.requested_quantity,
        depth_exhausted=walk.exhausted,
    )


def fee_coefficient_from_info(info: object) -> float | None:
    """The coefficient the INSTRUMENT ITSELF carries, or ``None`` if it carries none.

    The venue's own value is the AUTHORITY on that market's fee schedule. A
    :class:`FeeCoefficientSource` is an injected PULL seam that takes an opaque
    ``instrument_id`` string and has no structural obligation to answer about
    the market it was asked for -- so a caller holding both should compare
    them. This is the read that makes that comparison possible without naming
    a venue.

    Three outcomes, and the difference between the last two matters:

    * key ABSENT -> ``None``. There is no authority to check against. A REAL
      venue instrument always carries the key (the Polymarket.us parser writes
      it unconditionally, ``None`` included); an instrument without it is
      hand-built or comes from wiring that publishes none.
    * key PRESENT but unusable (``None``, a ``bool`` round-trip, undecodable
      text, non-finite, or outside ``[0, 1]``) -> raises. That is the venue
      saying "unknown", which is a NO-TRADE, never "any value will do" -- the
      same posture ``breezy.adapters.polymarket_us.fees`` takes when it
      refuses rather than trading free.
    * key present and usable -> the ``float``.

    Raises
    ------
    UnknownFeeScheduleError
        When the key is present but carries no usable coefficient.
    """
    if not isinstance(info, Mapping):
        return None
    if INSTRUMENT_INFO_FEE_COEFFICIENT_KEY not in info:
        return None
    raw = info[INSTRUMENT_INFO_FEE_COEFFICIENT_KEY]
    value: float | None = None
    # `bool` is a subclass of `int`, so a boolean is a plausible round-trip
    # accident and must never be read as 0.0/1.0.
    if isinstance(raw, bool):
        value = None
    elif isinstance(raw, int | float):
        value = float(raw)
    elif isinstance(raw, str):
        try:
            value = float(raw)
        except ValueError:
            value = None
    if value is None or not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise UnknownFeeScheduleError(
            f"{INSTRUMENT_INFO_FEE_COEFFICIENT_KEY!r} is present on this instrument but "
            f"carries no usable coefficient ({raw!r}). A present-but-unusable value is "
            "the venue saying the fee schedule is UNKNOWN, which is a no-trade, never "
            "a licence to price the market off an injected number instead.",
        )
    return value
