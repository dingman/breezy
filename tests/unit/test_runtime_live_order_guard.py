"""R-6a: the live long-only order guard.

``install_live_order_guard`` wires the SAME ``BacktestOrderGuard`` used in
backtests onto a live node's ``MessageBus`` (``trade_cli`` does this after
``node.build()``). Despite the class name, nothing here is backtest-specific
-- see the module docstring in ``backtest_order_guard.py``.

The coverage gap this file closes, verified before writing anything:

* ``test_runtime_backtest_order_guard.py:307`` asserts only that the SOURCE
  STRING ``"install_order_guard(engine)"`` appears in a file -- it proves
  nothing about behaviour, and proves nothing at all about the LIVE
  installer, which has no test of any kind. ``test_the_live_installer_...``
  below installs onto a fake but live-shaped ``MessageBus`` and then drives
  an event through the handler it actually captured, so a broken installer
  (wrong topic, wrong handler, wrong bus method) fails this test even though
  it would satisfy the old source-string assertion.
* ``_refuse_naked_short`` is named only in a docstring
  (``test_backtest_harness_refusal_precedence.py:294``) -- never exercised
  under that name with an assertion on the refusal message.

R-6a Revision 2 (``docs/plans/R6A_GUARD_SEMANTICS_2026-09-02.md``) deletes the
tag/prefix exemption this file used to pin: it was keyed on attacker-settable
fields (any strategy can set ``tags=["RECONCILIATION"]`` or a
``SETTLEMENT-``-prefixed ``ClientOrderId``), so it was not an exemption, it
was a documented bypass. The RED-1..RED-3 tests below pin that the same
shapes are now REFUSED. The surviving exemption keys on ``event.reconciliation``
instead, which only Nautilus itself can set (RED-4, RED-5, RED-7).

**MEASURED, and load-bearing for RED-4/RED-5's ``xfail``:**
``OrderInitialized.reconciliation`` (nautilus_trader==1.231.0,
``model/events/order.pyx:481``) is a hardcoded ``return False  # Internal
system event`` -- it ignores ``self._reconciliation`` entirely, no matter
what the constructor was given. Verified directly against the installed
package: constructing ``OrderInitialized(..., reconciliation=True)`` and
reading the property back returns ``False``, both via keyword and via
positional argument. This is the SAME construction Nautilus itself uses at
``live/execution_engine.py:3608``, so even in a hypothetical future Nautilus
version that publishes this event during reconciliation (it does not today --
see RED-6), the property would still read ``False``. The `event.reconciliation`
check this module now carries is therefore doubly dead in 1.231.0: dead
because nothing publishes the event (M1), AND dead because the flag the
guard would read never surfaces even if something did. This is a Nautilus
defect, not a Breezy one, and Nautilus is immutable here -- it cannot be
patched. RED-4 and RED-5 are written at FULL strength (no exception must be
raised) and marked ``xfail(strict=True)`` rather than weakened, so an XPASS
(meaning Nautilus fixed the property) fails the suite and forces a re-read.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
from nautilus_trader.model.events import OrderInitialized
from nautilus_trader.model.identifiers import (
    ClientOrderId,
    InstrumentId,
    StrategyId,
    Symbol,
    TraderId,
    Venue,
)
from nautilus_trader.model.objects import Quantity

from breezy.runtime.backtest_order_guard import (
    ORDER_EVENT_TOPIC,
    BacktestOrderGuard,
    NakedShortRefusedError,
    install_live_order_guard,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Callable, Sequence

INSTRUMENT = InstrumentId(Symbol("synthetic-live-guard-market"), Venue("POLYMARKET_US"))

#: The exact strings the deleted tag/prefix exemption used to key on. Spelled
#: out locally now that the module exports no such constants -- RED-1..RED-3
#: pin that these are attacker-settable and therefore no longer exempt.
_OLD_RECONCILIATION_TAG = "RECONCILIATION"
_OLD_VENUE_TAG = "VENUE"
_OLD_SETTLEMENT_PREFIX = "SETTLEMENT-"


class _FakePortfolio:
    def __init__(self, net: Decimal) -> None:
        self._net = net

    def net_position(self, instrument_id: InstrumentId) -> Decimal:
        del instrument_id
        return self._net


class _FakeCache:
    """`orders`, not `orders_open` -- the guard reads `cache.orders(...)` since
    `docs/plans/ORDER_LIST_BYPASS_2026-09-02.md` Increment 1 (§2); every test
    in this module screens against a net of 0 with no working orders either
    way, so an always-empty return is unaffected by which method is called.

    `order` is Increment 2's addition (§6): the guard's shim consults
    `cache.order(coid)` for every entry it holds. Every SELL in this module
    is refused (net is always 0), so the guard never records a shim entry
    here in the first place -- `order` returning `None` unconditionally is
    correct, not merely unexercised.
    """

    def orders(self, *, instrument_id: InstrumentId | None = None) -> Sequence[Any]:
        del instrument_id
        return ()

    def order(self, client_order_id: ClientOrderId) -> None:
        del client_order_id


class _FakeLiveMessageBus:
    """Mimics the ONE surface the installer may use: ``subscribe(topic=, handler=)``.

    Recording rather than dispatching by glob keeps this fake honest about
    what it is standing in for -- it does not reimplement Nautilus's topic
    matching -- while still letting a test PROVE the captured handler drives
    the guard's real logic by calling it directly.
    """

    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, Callable[[object], None]]] = []

    def subscribe(self, *, topic: str, handler: Callable[[object], None]) -> None:
        self.subscriptions.append((topic, handler))


def _initialized(
    *,
    side: OrderSide = OrderSide.SELL,
    quantity: int = 500,
    post_only: bool = False,
    reduce_only: bool = False,
    tags: list[str] | None = None,
    client_order_id: ClientOrderId | None = None,
    reconciliation: bool = False,
) -> OrderInitialized:
    return OrderInitialized(
        trader_id=TraderId("BREEZYTRADE-001"),
        strategy_id=StrategyId("EXTERNAL"),
        instrument_id=INSTRUMENT,
        client_order_id=client_order_id or ClientOrderId("O-1"),
        order_side=side,
        order_type=OrderType.MARKET,
        quantity=Quantity(quantity, 0),
        time_in_force=TimeInForce.GTC,
        post_only=post_only,
        reduce_only=reduce_only,
        quote_quantity=False,
        options={},
        emulation_trigger=0,
        trigger_instrument_id=None,
        contingency_type=0,
        order_list_id=None,
        linked_order_ids=None,
        parent_order_id=None,
        exec_algorithm_id=None,
        exec_algorithm_params=None,
        exec_spawn_id=None,
        tags=tags,
        event_id=UUID4(),
        ts_init=0,
        reconciliation=reconciliation,
    )


# ---------------------------------------------------------------------------
# 1. The live installer wires a working, REPORTING guard -- behavioural.
# ---------------------------------------------------------------------------


def test_the_live_installer_subscribes_the_wrapped_handler_to_the_order_topic() -> None:
    """RED-9. Replaces the pre-§4 identity assertion (``handler ==
    guard.on_order_event``), which becomes false once the reporting wrapper
    lands. The behavioural drive-an-event half is kept: a broken installer
    (wrong bus method, wrong topic, a handler that discards the event) fails
    here even though it might satisfy a source-string check.
    """
    msgbus = _FakeLiveMessageBus()
    portfolio = _FakePortfolio(Decimal(0))
    cache = _FakeCache()

    guard = install_live_order_guard(portfolio, cache, msgbus, on_refusal=lambda exc: None)

    assert isinstance(guard, BacktestOrderGuard)
    assert len(msgbus.subscriptions) == 1
    topic, handler = msgbus.subscriptions[0]
    assert topic == ORDER_EVENT_TOPIC
    # A WRAPPER, not the guard's bare bound method -- §4 requires the
    # subscribed handler to catch, report, and re-raise a refusal.
    assert handler is not guard.on_order_event

    naked_short = _initialized(side=OrderSide.SELL, quantity=500, tags=None)
    with pytest.raises(NakedShortRefusedError):
        handler(naked_short)


def test_a_live_refusal_is_reported_before_it_is_raised() -> None:
    """RED-11. Both halves of §4: the reporter is called, AND the
    original exception still propagates -- reporting must never replace
    enforcement."""
    msgbus = _FakeLiveMessageBus()
    portfolio = _FakePortfolio(Decimal(0))
    cache = _FakeCache()
    reported: list[ValueError] = []

    install_live_order_guard(portfolio, cache, msgbus, on_refusal=reported.append)
    _, handler = msgbus.subscriptions[0]
    naked_short = _initialized(side=OrderSide.SELL, quantity=500, tags=None)

    with pytest.raises(NakedShortRefusedError) as excinfo:
        handler(naked_short)

    assert len(reported) == 1
    assert reported[0] is excinfo.value


def test_a_raising_refusal_reporter_does_not_replace_the_cause() -> None:
    """RED-12. Pins §4's objection to the ``try/finally`` spelling: a
    bare ``raise`` inside a ``finally`` would re-raise the REPORTER's
    exception here, not the refusal. Would pass silently under that wrong
    spelling only if the reporter never raised -- this test makes it raise.
    """
    msgbus = _FakeLiveMessageBus()
    portfolio = _FakePortfolio(Decimal(0))
    cache = _FakeCache()

    def _broken_reporter(exc: ValueError) -> None:
        del exc
        raise RuntimeError("reporter is broken")

    install_live_order_guard(portfolio, cache, msgbus, on_refusal=_broken_reporter)
    _, handler = msgbus.subscriptions[0]
    naked_short = _initialized(side=OrderSide.SELL, quantity=500, tags=None)

    with pytest.raises(NakedShortRefusedError):
        handler(naked_short)


# ---------------------------------------------------------------------------
# 2. `_refuse_naked_short`, behaviourally, by name.
# ---------------------------------------------------------------------------


def test_refuse_naked_short_refuses_and_names_the_instrument() -> None:
    guard = BacktestOrderGuard(_FakePortfolio(Decimal(0)), _FakeCache())
    event = _initialized(side=OrderSide.SELL, quantity=250, tags=None)

    with pytest.raises(NakedShortRefusedError) as excinfo:
        guard._refuse_naked_short(event)

    assert str(INSTRUMENT) in str(excinfo.value)


# ---------------------------------------------------------------------------
# 3. RED-1..RED-3: the deleted tag/prefix exemption is now a REFUSAL.
# ---------------------------------------------------------------------------


def test_a_reconciliation_tagged_naked_sell_is_refused() -> None:
    """RED-1. ``tags`` is an ordinary, attacker-settable ``OrderFactory``
    kwarg (measured: ``common/factories.pyx:236-248``); ``reconciliation``
    defaults ``False`` on every path a strategy can reach. Finding (A)
    closed."""
    guard = BacktestOrderGuard(_FakePortfolio(Decimal(0)), _FakeCache())
    event = _initialized(
        side=OrderSide.SELL,
        quantity=500,
        tags=[_OLD_RECONCILIATION_TAG],
        client_order_id=ClientOrderId("O-2"),
    )

    with pytest.raises(NakedShortRefusedError):
        guard.on_order_event(event)


def test_a_venue_tagged_naked_sell_is_refused() -> None:
    """RED-2. Same reasoning as RED-1, for the other deleted tag."""
    guard = BacktestOrderGuard(_FakePortfolio(Decimal(0)), _FakeCache())
    event = _initialized(
        side=OrderSide.SELL,
        quantity=500,
        tags=[_OLD_VENUE_TAG],
        client_order_id=ClientOrderId("O-4"),
    )

    with pytest.raises(NakedShortRefusedError):
        guard.on_order_event(event)


def test_a_settlement_prefixed_naked_sell_is_refused() -> None:
    """RED-3. The forgeable branch: any strategy can set its own
    ``ClientOrderId`` to any string, including this exact prefix."""
    guard = BacktestOrderGuard(_FakePortfolio(Decimal(0)), _FakeCache())
    event = _initialized(
        side=OrderSide.SELL,
        quantity=500,
        tags=None,
        client_order_id=ClientOrderId(f"{_OLD_SETTLEMENT_PREFIX}NYC-2026-09-02"),
    )

    with pytest.raises(NakedShortRefusedError):
        guard.on_order_event(event)


# ---------------------------------------------------------------------------
# 4. RED-4/RED-5: the surviving, UNFORGEABLE exemption -- xfail, see module
#    docstring for the measured Nautilus property defect.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "MEASURED against nautilus_trader==1.231.0: `OrderInitialized."
        "reconciliation` (`model/events/order.pyx:481`) is a hardcoded "
        "`return False`, regardless of the constructor argument. Verified "
        "directly: constructing `OrderInitialized(..., reconciliation=True)` "
        "and reading `.reconciliation` back returns `False`. The guard's "
        "`event.reconciliation` check (R-6a §2) is therefore inert for "
        "this event type even in a unit test that constructs the event "
        "directly -- not only 'dead because Nautilus never publishes it' "
        "(M1), but dead because the flag cannot be read back at all. Nautilus "
        "is immutable here; this is not a Breezy defect to fix. `strict=True` "
        "means an XPASS (Nautilus corrected the property) fails the suite "
        "and forces a re-read, which is the intended signal."
    ),
)
def test_a_nautilus_reconciliation_event_is_out_of_jurisdiction() -> None:
    """RED-4. A naked SELL with ``reconciliation=True`` must pass untouched."""
    guard = BacktestOrderGuard(_FakePortfolio(Decimal(0)), _FakeCache())
    event = _initialized(side=OrderSide.SELL, quantity=500, tags=None, reconciliation=True)

    guard.on_order_event(event)  # must not raise


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Same measured defect as `test_a_nautilus_reconciliation_event_is_"
        "out_of_jurisdiction` -- see that test and the module docstring. "
        "This is §2's OWN motivating case (a resting post-only order "
        "found at the venue on restart): it fails for the identical reason, "
        "since `event.reconciliation` reads `False` regardless."
    ),
)
def test_a_reconciled_post_only_order_is_also_out_of_jurisdiction() -> None:
    """RED-5. Fails if the check is placed inside ``_refuse_naked_short``
    instead of ``on_order_event`` -- this order is a BUY, so the naked-short
    rule would never even see it; only the post-only rule can refuse it."""
    guard = BacktestOrderGuard(_FakePortfolio(Decimal(0)), _FakeCache())
    event = _initialized(
        side=OrderSide.BUY,
        quantity=500,
        post_only=True,
        tags=None,
        reconciliation=True,
    )

    guard.on_order_event(event)  # must not raise


# ---------------------------------------------------------------------------
# 5. An untagged, unclaimed sell is still refused -- no blanket exemption.
# ---------------------------------------------------------------------------


def test_an_untagged_unclaimed_market_sell_is_still_refused() -> None:
    guard = BacktestOrderGuard(_FakePortfolio(Decimal(0)), _FakeCache())
    event = _initialized(
        side=OrderSide.SELL,
        quantity=500,
        tags=None,
        client_order_id=ClientOrderId("O-3"),
    )

    with pytest.raises(NakedShortRefusedError):
        guard.on_order_event(event)


# ---------------------------------------------------------------------------
# 6. The exemption tag set stays EXACT -- an unrecognised tag is still refused.
# ---------------------------------------------------------------------------


def test_a_tagged_naked_sell_is_still_refused() -> None:
    """Renamed from ``test_an_unrecognised_tag_on_a_naked_sell_is_still_
    refused``: with the tag/prefix exemption gone entirely, EVERY tag is
    unrecognised -- this is no longer a special case, but is kept as an
    explicit pin that tagging an order is not, on its own, ever a way out."""
    guard = BacktestOrderGuard(_FakePortfolio(Decimal(0)), _FakeCache())
    event = _initialized(
        side=OrderSide.SELL,
        quantity=500,
        tags=["SOMETHING-ELSE"],
        client_order_id=ClientOrderId("O-5"),
    )

    with pytest.raises(NakedShortRefusedError):
        guard.on_order_event(event)


# ---------------------------------------------------------------------------
# 7. RED-7: why the surviving exemption is unforgeable.
# ---------------------------------------------------------------------------


def test_the_order_factory_cannot_set_the_reconciliation_flag() -> None:
    """RED-7. Unlike ``tags`` and ``reduce_only`` (ordinary, public
    ``OrderFactory`` kwargs -- measured: ``common/factories.pyx:236-248``),
    ``reconciliation`` is not exposed to a strategy at all. Only Nautilus's
    own internal reconciliation code constructs ``OrderInitialized`` with it
    directly (``live/execution_engine.py:3608``)."""
    factory = OrderFactory(
        trader_id=TraderId("BREEZYTRADE-001"),
        strategy_id=StrategyId("EXTERNAL"),
        clock=TestClock(),
    )

    with pytest.raises(TypeError):
        factory.market(
            instrument_id=INSTRUMENT,
            order_side=OrderSide.SELL,
            quantity=Quantity(500, 0),
            reconciliation=True,
        )
