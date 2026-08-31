"""Two order intents the backtest venue cannot model, refused where they are FORMED.

Both rules below already existed in this repository. Neither was reachable from
the seat of the person who breaks them.

**post_only.** ``PolymarketUSFeeModel.get_commission`` raises
``MakerRebateUnmodelledError`` when it is asked to PRICE a post-only fill --
the venue documents a maker *rebate* (``-0.0125``) and the model has only the
taker coefficient, so the number would be wrong in SIGN, not merely in
magnitude. The refusal is correct policy. The PHASE was wrong: the fee model
only runs on a FILL, so a post-only order that rests and never fills produces
no signal at all, and one that does fill aborts ``engine.run()`` halfway
through with an error about fees rather than about the order. This module moves
the same refusal to the instant the order is submitted.

**Naked shorts.** ``docs/specs/BACKTEST_VENUE_CONFIG.md`` §2: a SELL with no
position passes every ``RiskEngine`` check on a CASH account, because
``CashAccount.balance_impact`` (``accounting/accounts/cash.pyx:489-493``)
returns **+notional** for a SELL, so the check ``(free + balance_impact) < 0``
(``risk/engine.pyx:949``) can never fire; and 1.231.0 exempts
position-reducing sells outright (``:975-987``), so the only sells that reach
that gate are the naked ones. The spec used to prescribe "a strategy-side
invariant", which asks every strategy author to re-derive the rule from prose
they may never read -- and one author, writing a perfectly reasonable ladder,
did not. Verified live: a LIMIT SELL for 500 contracts against a ZERO position
and $1,000 of cash was accepted and filled 50, with no rejection and no
warning. The guard therefore lives here, where it cannot be forgotten.

Why the message bus, and why ``OrderInitialized``
-------------------------------------------------

``Strategy.submit_order`` publishes the order's ``OrderInitialized`` event to
``events.order.<strategy_id>`` as its FIRST action -- before the duplicate-id
check, before ``cache.add_order``, and before the ``SubmitOrder`` command
reaches the ``RiskEngine`` (``trading/strategy.pyx:855-859``). Subscribing to
that topic is therefore the earliest observation point in the framework, and it
is a native extension point rather than a hook: nothing here subclasses,
patches, or wraps any Nautilus class.

The engine's own settlement leg does NOT pass through here, by construction:
``check_instrument_expiration`` builds its ``EXPIRATION-LEG-<uuid4>``
``MarketOrder`` and calls ``cache.add_order`` plus ``_generate_order_accepted``
directly (``backtest/engine.pyx:5952-5966``), publishing no
``OrderInitialized`` at all. That matters because the settlement leg is a SELL
sized to the whole position, and a guard that saw it would have to special-case
it.

Raising from a bus handler propagates out of ``engine.run()`` -- the same route
``MakerRebateUnmodelledError`` already takes, and the reason the author learns
about the problem at all.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Final

from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.events import OrderInitialized

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.cache.base import CacheFacade
    from nautilus_trader.core.message import Event
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.portfolio import Portfolio

__all__ = [
    "ORDER_EVENT_TOPIC",
    "BacktestOrderGuard",
    "NakedShortRefusedError",
    "PostOnlyRefusedError",
    "install_order_guard",
]

#: Every strategy publishes its order events under ``events.order.<strategy_id>``
#: (``trading/strategy.pyx:322`` subscribes to exactly this shape). The trailing
#: ``*`` is a ``MessageBus`` glob, so ONE subscription covers every strategy in
#: the run, including strategies added after this one is installed.
ORDER_EVENT_TOPIC: Final[str] = "events.order.*"


class PostOnlyRefusedError(ValueError):
    """A post-only order was submitted. The venue's maker economics are unmodelled.

    Raised at SUBMIT time. The policy itself is unchanged from
    ``PolymarketUSFeeModel``: any result depending on maker economics is
    unevaluable, because the modelled coefficient has the wrong sign.
    """


class NakedShortRefusedError(ValueError):
    """A SELL exceeded the net long quantity the account actually holds.

    Raised at SUBMIT time, because no later observation point can catch it: the
    fill is accepted, the account's free balance RISES, and terminal PnL
    arithmetic stays correct. The only symptom is a position that could never
    have been funded.
    """


class BacktestOrderGuard:
    """Refuses two unmodellable order intents at the moment they are submitted.

    Holds the ``Portfolio`` rather than a snapshot of it: the net position is
    read at submit time, which is the only instant at which "naked" is a
    well-defined question.
    """

    def __init__(self, portfolio: Portfolio, cache: CacheFacade) -> None:
        self._portfolio = portfolio
        self._cache = cache

    def on_order_event(self, event: Event) -> None:
        """Screen ``OrderInitialized``; ignore every other order event.

        Type-EXACT rather than ``isinstance``: this topic carries the whole
        order lifecycle (accepted, filled, canceled, rejected), and the
        settlement leg's own events arrive here too.
        """
        if type(event) is not OrderInitialized:
            return
        self._refuse_post_only(event)
        self._refuse_naked_short(event)

    # -- rules -------------------------------------------------------------

    def _refuse_post_only(self, event: OrderInitialized) -> None:
        if not event.post_only:
            return
        raise PostOnlyRefusedError(
            f"{event.client_order_id} on {event.instrument_id} was submitted with "
            f"post_only=True, which this venue configuration cannot model. "
            f"`PolymarketUSFeeModel` has only the TAKER coefficient; the venue "
            f"documents a maker REBATE (-0.0125), so a modelled maker fill is wrong "
            f"in SIGN and any result that depends on it is unevaluable rather than "
            f"merely pessimistic. Refused here, at SUBMIT, because the fee model can "
            f"only refuse at FILL -- by which point a post-only order that never "
            f"filled has told you nothing and one that did has aborted the run. "
            f"Submit a marketable order (post_only=False) and accept the taker fee.",
        )

    def _refuse_naked_short(self, event: OrderInitialized) -> None:
        if event.side != OrderSide.SELL or event.reduce_only:
            return
        instrument_id = event.instrument_id
        net = self._net_long(instrument_id)
        pending = self._working_sell_quantity(instrument_id)
        quantity = event.quantity.as_decimal()
        if pending + quantity > net:
            raise NakedShortRefusedError(
                f"{event.client_order_id} would SELL {quantity} of {instrument_id} "
                f"against a net long of {net} (with {pending} already working) -- a "
                f"naked short of {pending + quantity - net}. On a Polymarket CLOB you "
                f"cannot sell tokens you do not hold. On Polymarket.us, NO is an "
                f"outcome side on the same instrument/book: the live order expression "
                f"is `outcomeSide=NO` with price inversion, as recorded in "
                f"`docs/evidence/no_side_instrument_probe_2026-08-31.md`. No "
                f"Nautilus check can catch this: `CashAccount.balance_impact` returns "
                f"+notional for a SELL, so the RiskEngine's `(free + impact) < 0` gate "
                f"can never fire, position-reducing sells are exempted outright, and "
                f"after the fill the account shows MORE free cash than before. "
                f"Terminal PnL arithmetic stays correct, so the backtest looks fine. "
                f"Size every SELL from `self.cache`/`self.portfolio.net_position(...)`.",
            )

    # -- internals ---------------------------------------------------------

    def _working_sell_quantity(self, instrument_id: InstrumentId) -> Decimal:
        """Unfilled quantity on SELL orders already working for this instrument.

        Counted because two sells that are each within the net long are
        JOINTLY naked, and a rule that looked only at the position would pass
        both. Read from the cache rather than tracked here so cancels,
        rejections and partial fills need no bookkeeping of our own -- the
        order being submitted is not in the cache yet, since
        `Strategy.submit_order` publishes `OrderInitialized` BEFORE it calls
        `cache.add_order` (`trading/strategy.pyx:855-871`).

        `Cache.orders_open` guarantees no ordering (`cache.pyx:4719`); this is
        a SUM, so the result does not depend on one.
        """
        return sum(
            (
                order.leaves_qty.as_decimal()
                for order in self._cache.orders_open(instrument_id=instrument_id)
                if order.side == OrderSide.SELL and not order.is_reduce_only
            ),
            Decimal(0),
        )

    def _net_long(self, instrument_id: InstrumentId) -> Decimal:
        """Net position, floored at zero.

        Floored because a net SHORT is not a budget to sell more against; if
        one ever exists it is itself the failure this guard describes.
        """
        net = self._portfolio.net_position(instrument_id)
        if net is None:
            return Decimal(0)
        return max(Decimal(str(net)), Decimal(0))


def install_order_guard(engine: BacktestEngine) -> BacktestOrderGuard:
    """Subscribe a :class:`BacktestOrderGuard` to ``engine``'s order events.

    Returns the guard so a caller (and a test) can hold it; the engine holds
    only the bound handler.
    """
    guard = BacktestOrderGuard(engine.portfolio, engine.cache)
    engine.kernel.msgbus.subscribe(topic=ORDER_EVENT_TOPIC, handler=guard.on_order_event)
    return guard
