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
(``risk/engine.pyx:949``) can never fire; and 1.231.0 routes only
position-reducing sells AROUND that check, on a CONDITION a naked sell fails:
``is_position_reducing_sell = order.is_reduce_only or pending_sell_qty <=
available_long_qty`` (``risk/engine.pyx:979-982``), where ``available_long_qty``
is the net open LONG minus already-submitted sells (``:701-739``). A naked sell
is neither reduce-only nor within a long it does not have, so it is NOT
exempted -- it falls THROUGH to the balance check above, which on a cash
account cannot deny it. Either way the sell arrives unopposed; the exemption
merely decides which unfireable gate it reaches. The spec used to prescribe "a strategy-side
invariant", which asks every strategy author to re-derive the rule from prose
they may never read -- and one author, writing a perfectly reasonable ladder,
did not. Verified live: a LIMIT SELL for 500 contracts against a ZERO position
and $1,000 of cash was accepted and filled 50, with no rejection and no
warning. The guard therefore lives here, where it cannot be forgotten.

That Nautilus exemption is quoted here to explain the mechanism it bypasses,
not as a model for this guard's own rule below: ``reduce_only`` is an
ordinary, attacker-settable ``OrderFactory`` kwarg, Nautilus only validates it
when ``command.position_id is not None`` (never true on the default
``submit_order`` path), and even when it does run the check is
jointly-naked-blind -- N reduce-only sells each within the net long all pass.
``_refuse_naked_short`` below therefore grants the flag no exemption at all;
see ``docs/plans/REDUCE_ONLY_BYPASS_2026-09-02.md``.

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

import logging
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.events import OrderInitialized

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable

    from nautilus_trader.backtest.engine import BacktestEngine
    from nautilus_trader.cache.base import CacheFacade
    from nautilus_trader.common.component import MessageBus
    from nautilus_trader.core.message import Event
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.portfolio import Portfolio

logger = logging.getLogger(__name__)

__all__ = [
    "ORDER_EVENT_TOPIC",
    "BacktestOrderGuard",
    "NakedShortRefusedError",
    "PostOnlyRefusedError",
    "install_live_order_guard",
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

    On Polymarket.us, NO is an outcome side on the *same* instrument/book --
    not a separate ``InstrumentId`` with its own book -- so the live order
    expression is ``outcomeSide=NO`` with price inversion, as recorded in
    ``docs/evidence/no_side_instrument_probe_2026-08-31.md``.
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
        if event.reconciliation:
            # !! THIS BRANCH CANNOT FIRE ON nautilus_trader==1.231.0. !!
            # It is forward-compatible insurance, NOT present protection --
            # do not read it as "reconciliation orders are exempt". They are
            # exempt only because the event never arrives at all. Two
            # INDEPENDENT measured reasons, either alone sufficient:
            #   1. Nothing publishes a reconciliation `OrderInitialized`.
            #      Exactly three sites publish an init event -- strategy.pyx
            #      :858, :950, algorithm.pyx:1209 -- all strategy/exec-algo
            #      submission. `_generate_order` builds the event and returns
            #      it WITHOUT publishing (`live/execution_engine.py:3611`).
            #   2. `OrderInitialized.reconciliation` is a hardcoded
            #      `return False  # Internal system event`
            #      (`model/events/order.pyx:481`) -- it ignores the value the
            #      constructor stored. Measured: building the event with
            #      `reconciliation=True` and reading the property back yields
            #      `False`, via the SAME call shape Nautilus itself uses at
            #      `live/execution_engine.py:3608`. A Nautilus defect, and
            #      Nautilus is immutable here, so it cannot be patched.
            # `test_runtime_live_order_guard.py` pins both at full strength
            # under `xfail(strict=True)`, so an XPASS -- Nautilus fixing the
            # property -- fails the suite and forces a re-read of this block.
            #
            # WHY KEEP IT ANYWAY: if either reason above ever changes, this is
            # out of jurisdiction for BOTH rules below, not just naked-short.
            # Reconciliation copies `post_only=report.post_only` straight off
            # the venue report (`live/execution_engine.py:3592`), so a resting
            # post-only order found at the venue on restart would be refused by
            # `_refuse_post_only` -- crash-looping while holding a real venue
            # position. And unlike a tag or a ClientOrderId prefix, the flag is
            # unforgeable: `OrderFactory` cannot set it (see
            # `test_the_order_factory_cannot_set_the_reconciliation_flag`).
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
        """Refuse a SELL that exceeds the net long, INCLUDING a ``reduce_only`` one.

        ``reduce_only`` confers no exemption here: it is an ordinary,
        attacker-settable ``OrderFactory`` kwarg (F1,
        `docs/plans/REDUCE_ONLY_BYPASS_2026-09-02.md`), and Nautilus's own
        validation of it is skipped on the default ``submit_order`` path and
        jointly-naked-blind even when it runs (F2/F3). A GENUINELY reducing
        sell satisfies ``pending + quantity <= net`` by the definition of
        reducing, so running the identical test for every SELL cannot refuse
        a legitimate exit -- it can only refuse the sells that are naked
        regardless of the flag.
        """
        if event.side != OrderSide.SELL:
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
                f"is `outcomeSide=NO` with price inversion. No "
                f"Nautilus check can catch this: `CashAccount.balance_impact` returns "
                f"+notional for a SELL, so the RiskEngine's `(free + impact) < 0` gate "
                f"can never fire, position-reducing sells are exempted outright, and "
                f"after the fill the account shows MORE free cash than before. "
                f"Terminal PnL arithmetic stays correct, so the backtest looks fine. "
                f"Size every SELL from `self.portfolio.net_position(...)` MINUS any "
                f"already-working SELL quantity -- the same "
                f"subtraction `_working_sell_quantity` performs -- never from "
                f"`net_position(...)` alone, or a working exit sized to part of the "
                f"position plus a settlement leg sized to the whole of it will "
                f"double-count and refuse a real close. `reduce_only` is not a "
                f"licence to skip this check: it is an ordinary, attacker-settable "
                f"flag (any strategy can set it), so it is screened exactly like "
                f"every other SELL -- a genuinely reducing sell still passes, "
                f"because it satisfies this same inequality by construction.",
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

        EVERY open SELL counts, `reduce_only` included -- the same divergence
        from Nautilus's own `submitted_sell_qty` (F5,
        `docs/plans/REDUCE_ONLY_BYPASS_2026-09-02.md`) that closes the
        jointly-naked pair of `reduce_only` sells: excluding them would make
        the FIRST one invisible to the budget the second is screened against.

        `Cache.orders_open` guarantees no ordering (`cache.pyx:4719`); this is
        a SUM, so the result does not depend on one.
        """
        return sum(
            (
                order.leaves_qty.as_decimal()
                for order in self._cache.orders_open(instrument_id=instrument_id)
                if order.side == OrderSide.SELL
            ),
            Decimal(0),
        )

    def _net_long(self, instrument_id: InstrumentId) -> Decimal:
        """Net position, floored at zero.

        Floored because a net SHORT is not a budget to sell more against; if
        one ever exists it is itself the failure this guard describes.
        """
        net = self._portfolio.net_position(instrument_id)
        if net is None:  # defensive floor only: `Portfolio.net_position` always
            return Decimal(0)  # returns `Decimal`, never `None`, in this Nautilus.
        return max(Decimal(str(net)), Decimal(0))


def install_order_guard(engine: BacktestEngine) -> BacktestOrderGuard:
    """Subscribe a :class:`BacktestOrderGuard` to ``engine``'s order events.

    Returns the guard so a caller (and a test) can hold it; the engine holds
    only the bound handler.
    """
    guard = BacktestOrderGuard(engine.portfolio, engine.cache)
    engine.kernel.msgbus.subscribe(topic=ORDER_EVENT_TOPIC, handler=guard.on_order_event)
    return guard


def install_live_order_guard(
    portfolio: Portfolio,
    cache: CacheFacade,
    msgbus: MessageBus,
    on_refusal: Callable[[ValueError], None],
) -> BacktestOrderGuard:
    """Subscribe a :class:`BacktestOrderGuard` to a LIVE node's message bus.

    ``BacktestOrderGuard`` is venue- and mode-agnostic despite its name: every
    rule it enforces (unmodelled post-only economics, a naked short) is a
    property of the ORDER, not of the engine that raised it, and this
    function is the proof -- the same class, unmodified, is wired onto a
    live ``MessageBus`` here exactly as it is onto a backtest one by
    :func:`install_order_guard`. Renaming the class to say so is out of
    scope for this increment: it is used by name in backtest tests, and
    renaming it here would touch files this increment has no other reason to
    change.

    Mirrors :func:`install_order_guard`'s shape (``engine.kernel.msgbus`` ->
    ``msgbus`` directly, since a live ``TradingNode`` has no engine object of
    its own): a plain ``msgbus.subscribe(topic=..., handler=...)``, never
    ``msgbus.request(...)`` -- ``request`` is one of the write verbs barrier
    B4 bans syntactically, on any object, inside a venue-touching module,
    and this module IS venue-touching (its docstrings and f-strings name the
    venue). ``subscribe`` is not in that banned set.

    ``on_refusal`` is REQUIRED, not defaulted, so a refusal on a live node can
    never be silently swallowed by omission: a bare ``msgbus.subscribe(...,
    handler=guard.on_order_event)`` (:func:`install_order_guard`'s shape, kept
    for backtest) would let the refusal propagate but report nothing at the
    instant it happens -- on the engine-queue path ``os._exit(1)`` beats the
    CLI's own ``FATAL`` print, and on a ``LiveClock`` timer callback the
    exception is discarded outright and the process exits 0. The subscribed
    handler is therefore a WRAPPER around ``guard.on_order_event``, not the
    bare bound method itself: it reports at the moment of refusal, THEN
    re-raises, so the refusal still aborts exactly as it did before -- only
    reporting is added.

    Returns the guard so a caller (and a test) can hold it; the node holds
    only the bound handler.
    """
    guard = BacktestOrderGuard(portfolio, cache)

    def _report_then_reraise(event: Event) -> None:
        try:
            guard.on_order_event(event)
        except (PostOnlyRefusedError, NakedShortRefusedError) as exc:
            try:
                on_refusal(exc)
            except Exception:  # a broken reporter must not replace the cause
                logger.exception("order-guard refusal reporter failed")
            # Deliberately OUTSIDE the inner `try/except`, and NOT a
            # `finally`: a bare `raise` inside a `finally` re-raises
            # `sys.exc_info()`, which -- if `on_refusal` itself raised -- is
            # the REPORTER's exception, not this refusal (D4's objection).
            raise

    msgbus.subscribe(topic=ORDER_EVENT_TOPIC, handler=_report_then_reraise)
    return guard
