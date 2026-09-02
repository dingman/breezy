"""HALT trading the moment an order is formed with no account in the cache.

EXEC SPINE R-7-PRE (``docs/plans/EXEC_SPINE_R5_R6_2026-09-02.md``), and a hard
precondition of R-7.

The hazard this closes
----------------------
``RiskEngine._check_orders_risk_for_account`` (``$NT/risk/engine.pyx``) reads::

    cdef Account account = self._cache.account_for_venue(instrument.id.venue, account_id)

    if account is None:
        self._log.debug(...)
        return True  # TODO: Temporary early return until handling routing/multiple venues

``True`` means **order allowed**, and the framework's own comment calls it a
"Temporary early return". Every notional and free-balance cap Nautilus offers
lives BELOW that line, so while the account lookup is ``None`` a configured
``max_notional_per_order`` is inert and the order is forwarded to execution
unopposed. ``tests/contract/test_risk_engine_ordering_enforcement.py`` pins
that behaviour deliberately, so an upstream fix cannot pass unnoticed.

Today the execution client refuses every order unconditionally, so the
fail-open cannot be reached in a way that matters. R-7 removes that net. From
that point on, an account-registration race -- a slow balances read, a
reconnect, a cache flush -- would silently allow an order through an immutable
framework path. Nautilus is immutable here: the early return cannot be
patched, so the denial has to come from somewhere the early return does not
govern.

Null hypothesis, checked before any of this was written
-------------------------------------------------------
**Nautilus already provides the denial.** ``RiskEngine`` carries a
``TradingState`` and denies every ``SubmitOrder`` while it is ``HALTED``
(``$NT/risk/engine.pyx``, ``_execution_gateway``, ``reason=f"TradingState.HALTED"``),
and ``RiskEngine.set_trading_state`` is the public, documented way in. Nothing
here re-implements a risk check, subclasses a Nautilus class, or wraps one.
What is added is exactly one thing Nautilus does not have: the CONDITION under
which that native state is entered. No Nautilus component sets the trading
state on its own -- ``set_trading_state`` has no caller anywhere in the
installed framework -- because "what counts as unsafe" is a deployment's
question, not the framework's.

Where the denial lands, stated precisely
----------------------------------------
For a ``SubmitOrder``, Nautilus checks ``HALTED`` in ``_execution_gateway``,
which ``_handle_submit_order`` reaches AFTER ``_check_orders_risk``. So this
is not upstream of the fail-open in call ORDER. It is dominant over it in
EFFECT, which is the property that matters: the fail-open can only answer
"no cap opinion" (``True``), and that answer no longer reaches execution.
An order formed while the account is missing is denied with reason
``TradingState.HALTED`` -- never forwarded, never handed to an execution
client, whatever body that client's ``_submit_order`` may later acquire.

Why ``OrderInitialized``
------------------------
``Strategy.submit_order`` publishes the order's ``OrderInitialized`` to
``events.order.<strategy_id>`` as its FIRST action -- before the duplicate-id
check, before ``cache.add_order``, and before the ``SubmitOrder`` command
reaches the ``RiskEngine`` (``$NT/trading/strategy.pyx``). That is the
earliest observation point the framework offers, it is a native extension
point rather than a hook, and it is the SAME seam
:func:`breezy.runtime.backtest_order_guard.install_live_order_guard` already
uses -- one wiring idiom in this process, not two. Screening there means the
state is already ``HALTED`` by the time the command arrives.

Design notes
------------
* **The venue is read off the order, never configured.** ``account_for_venue``
  is keyed on ``instrument_id.venue``, so screening on that same key asks
  exactly the question the framework is about to ask. It also makes this
  module PORTABLE with no edit: a second venue's orders are screened against
  a second venue's account by construction.
* **The halt never self-clears.** An account that appears after the halt says
  the race resolved; it does not say the orders formed during the race were
  sound. Returning to ``ACTIVE`` is an operator action through
  ``RiskEngine.set_trading_state``, and this module deliberately provides no
  way to do it -- the same never-self-clearing rule the execution client's
  refusal latch already follows.
* **Type-EXACT event screening.** ``events.order.*`` carries the whole order
  lifecycle. A guard that matched by ``isinstance`` or by attribute would halt
  on its own resulting ``OrderDenied``.
* **This module is not an order path.** It sends no command, constructs no
  order, and touches no transport. Its only write is a state change on the
  risk engine, in the safe direction.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from nautilus_trader.model.enums import TradingState
from nautilus_trader.model.events import OrderInitialized

from breezy.runtime.backtest_order_guard import ORDER_EVENT_TOPIC

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable

    from nautilus_trader.cache.base import CacheFacade
    from nautilus_trader.common.component import MessageBus
    from nautilus_trader.core.message import Event
    from nautilus_trader.risk.engine import RiskEngine

logger = logging.getLogger(__name__)

__all__ = [
    "ORDER_EVENT_TOPIC",
    "AccountPresenceHalt",
    "install_account_presence_halt",
]

#: What an operator is told, and what the log records. Written once here so the
#: message an operator reads and the message a test asserts on cannot drift.
HALT_REASON_TEMPLATE: Final[str] = (
    "no account is cached for venue {venue}, so every Nautilus risk cap is "
    "inert for it (`_check_orders_risk_for_account` returns True on a missing "
    "account -- an order allowed). Order {client_order_id} on {instrument_id} "
    "was formed in that state. Trading is now HALTED for the whole node and "
    "will not resume without an operator: the caps this process appears to "
    "have configured were not protecting it."
)


class AccountPresenceHalt:
    """Halts the risk engine when an order is formed with no account cached.

    Holds the ``Cache`` and the ``RiskEngine`` rather than a snapshot of
    either: account presence is read at the instant the order is formed, which
    is the only instant at which the question has an answer that matters.
    """

    def __init__(self, cache: CacheFacade, risk_engine: RiskEngine) -> None:
        self._cache = cache
        self._risk_engine = risk_engine
        self._halted = False

    @property
    def halted(self) -> bool:
        """Whether THIS guard has halted the engine. Never resets."""
        return self._halted

    def on_order_event(self, event: Event) -> str | None:
        """Screen ``OrderInitialized``; ignore every other order event.

        Returns the halt reason when it halts, otherwise ``None``, so the
        installer can report without re-deriving the message.

        Type-EXACT rather than ``isinstance``: this topic carries the whole
        order lifecycle, including the ``OrderDenied`` this guard's own halt
        produces.
        """
        if type(event) is not OrderInitialized:
            return None
        if self._halted:
            # The engine is already HALTED; re-entering the same state logs a
            # framework warning and changes nothing.
            return None
        venue = event.instrument_id.venue
        if self._cache.account_for_venue(venue) is not None:
            return None

        reason = HALT_REASON_TEMPLATE.format(
            venue=venue,
            client_order_id=event.client_order_id,
            instrument_id=event.instrument_id,
        )
        # State FIRST, reporting second: the denial must not depend on
        # anything a reporter does or fails to do.
        self._risk_engine.set_trading_state(TradingState.HALTED)
        self._halted = True
        logger.error("account-presence halt: %s", reason)
        return reason


def install_account_presence_halt(
    msgbus: MessageBus,
    cache: CacheFacade,
    risk_engine: RiskEngine,
    *,
    on_halt: Callable[[str], None],
) -> AccountPresenceHalt:
    """Subscribe an :class:`AccountPresenceHalt` to a node's message bus.

    A plain ``msgbus.subscribe(topic=..., handler=...)`` -- the same shape
    :func:`breezy.runtime.backtest_order_guard.install_live_order_guard` uses,
    so ``actors=[]`` in ``build_trade_node_config`` stays an untouched empty
    literal and no new component type is introduced.

    ``on_halt`` is REQUIRED, not defaulted. A node that halts itself and tells
    nobody is a trading process that stops for reasons the operator has to
    reverse-engineer from a log. It is invoked AFTER the state change, and a
    reporter that raises is logged and contained: unlike the order guard --
    whose refusal IS the exception -- there is nothing here to re-raise, and
    letting a broken reporter propagate out of a bus handler would replace a
    clean halt with an unrelated failure.

    Returns the guard so a caller (and a test) can hold it; the node holds only
    the bound handler.
    """
    guard = AccountPresenceHalt(cache, risk_engine)

    def _halt_then_report(event: Event) -> None:
        reason = guard.on_order_event(event)
        if reason is None:
            return
        try:
            on_halt(reason)
        except Exception:  # a broken reporter must not undo or mask the halt
            logger.exception("account-presence halt reporter failed")

    msgbus.subscribe(topic=ORDER_EVENT_TOPIC, handler=_halt_then_report)
    return guard
