"""Contract: what Nautilus books when the venue reports a settled position FLAT.

Pinned against **``nautilus-trader==1.231.0``** (asserted below). Every
assertion drives REAL Nautilus objects -- a real ``Cache``, ``MessageBus``,
``Portfolio``, ``LiveExecutionEngine``, and a real ``BinaryOption`` parsed
from a captured Polymarket.us payload. Nothing is mocked. In particular
``calculate_reconciliation_price`` is never stubbed: it IS the behaviour
under test.

The hazard
----------
``LiveExecEngineConfig.generate_missing_orders`` defaults to **True**
(``live/config.py:183``). So the moment EXEC_SPINE **R-4** lands a live
execution client, ``LiveExecutionEngine._reconcile_position_report_netting``
(``live/execution_engine.py:2466``) will, on its own and with nobody choosing
it, synthesise a closing order whenever the venue reports FLAT for an
instrument Breezy holds -- which is exactly what a settled weather binary
looks like.

The price it books is the hazard. A settled binary is worth exactly ``1.00``
or ``0.00``. This file measures what Nautilus actually books instead, and
pins it, so that R-4 cannot ship a plausible, silent, wrong number.

**MEASURED CORRECTION to EXEC_SPINE R-9 / the R-4 LANDMINE note.** The plan
states that ``calculate_reconciliation_price`` (``live/reconciliation.py:549``)
"has no target ``avg_px_open`` for a flat target, so ``:2866-2880`` falls back
to the last cached quote's **bid**, and failing that to ``current_avg_px``",
and concludes that "a single cached quote tick prevents it". **Both halves are
wrong, and the truth is worse.** Measured here
(`test_calculate_reconciliation_price_returns_the_open_price_for_a_flat_target`):

    calculate_reconciliation_price(
        current_position_qty=Decimal(10),
        current_position_avg_px=Decimal("0.30"),
        target_position_qty=Decimal(0),
        target_position_avg_px=None,
    ) -> Decimal("0.30")     # NOT None

Because the return is not ``None``, the ``if reconciliation_price is None``
branch at ``live/execution_engine.py:2863`` is **never entered**, so the
quote-tick fallback (``:2871`` read, ``:2877`` SELL-side bid) and the
``current_avg_px`` fallback (``:2880-2881``) are both **unreachable** for a
long-to-flat target. The close
is booked at ``avg_px_open`` by the pricing function itself.

Consequences that change the plan:

* A cached quote tick is **not** a mitigation. There is nothing to mitigate
  with; the quote is never consulted. Pinned by
  `test_the_cached_quote_bid_is_never_consulted_for_a_flat_target`.
* The hazard is **unconditional** for any Breezy-opened position, because such
  a position always has an ``avg_px_open`` derived from its own fills. There is
  no configuration, no market data state, and no ordering that avoids it.

**This file asserts the hazardous behaviour on purpose. It does NOT endorse
it.** If a Nautilus upgrade changes any of it, these tests go RED and that is
GOOD NEWS needing a re-read -- never a reason to relax an assertion, and
never a reason to patch, monkeypatch or vendor Nautilus, which is immutable
here.

Scope guards
------------
No test here opens a socket, starts a node, or touches a venue. The engine,
cache and message bus are built in-process; the instrument comes from the
committed raw-capture corpus on disk. Runs under
``scripts/ci/run_tests_no_egress.sh``.

Values below (``0.30`` open, ``0.72`` bid, 10 contracts) are TEST-LOCAL
numbers chosen only so the three candidate prices are mutually distinct. This
file assigns no value to either operator-reserved control, and every order it
builds is a long-only BUY open (``allow_short=False``).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

import nautilus_trader
import pytest
from nautilus_trader.accounting.factory import AccountFactory
from nautilus_trader.cache.cache import Cache
from nautilus_trader.cache.config import CacheConfig
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.core import nautilus_pyo3
from nautilus_trader.core.message import Event
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.reports import PositionStatusReport
from nautilus_trader.live.config import LiveExecEngineConfig
from nautilus_trader.live.execution_engine import LiveExecutionEngine
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import (
    AccountType,
    LiquiditySide,
    OmsType,
    OrderSide,
    PositionSide,
)
from nautilus_trader.model.events import (
    AccountState,
    OrderFilled,
    OrderInitialized,
    OrderSubmitted,
    PositionClosed,
    PositionEvent,
)
from nautilus_trader.model.identifiers import (
    AccountId,
    PositionId,
    StrategyId,
    TradeId,
    TraderId,
    VenueOrderId,
)
from nautilus_trader.model.objects import AccountBalance, Money, Price, Quantity
from nautilus_trader.model.position import Position
from nautilus_trader.portfolio.portfolio import Portfolio
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.runtime.backtest_order_guard import ORDER_EVENT_TOPIC, BacktestOrderGuard
from tests.unit.conftest import iter_captured_market_payloads

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterator

    from nautilus_trader.model.instruments import BinaryOption
    from nautilus_trader.model.orders import Order

pytestmark = pytest.mark.contract

PINNED_NAUTILUS_VERSION = "1.231.0"

TRADER_ID = TraderId("BREEZY-RECON-HAZARD-001")
#: `StrategyId` is `f"{strategy_id}-{order_id_tag}"` (`trading/strategy.pyx:148-149`).
STRATEGY_NAME = "SETTLE"
ORDER_ID_TAG = "001"
STRATEGY_ID = StrategyId(f"{STRATEGY_NAME}-{ORDER_ID_TAG}")

#: The price Breezy opened at. Distinct from the bid and from both legal
#: settlement prices, so the booked number identifies its own source.
OPEN_PRICE = 0.30

#: A STALE cached top-of-book bid. Deliberately far from `OPEN_PRICE` so that
#: "booked the bid" and "booked the open" cannot be confused.
STALE_BID = 0.72
STALE_ASK = 0.74

OPEN_QUANTITY = 10

#: The only two prices a settled binary can be worth.
LEGAL_SETTLEMENT_PRICES = (Decimal("0.00"), Decimal("1.00"))

ACCOUNT_BALANCE = 1_000_000


def test_pinned_nautilus_version() -> None:
    """Every `path:line` in this module's docstring was read at this version."""
    assert nautilus_trader.__version__ == PINNED_NAUTILUS_VERSION, (
        f"These pins were verified against nautilus-trader "
        f"{PINNED_NAUTILUS_VERSION}, running against "
        f"{nautilus_trader.__version__}. Re-read "
        f"`live/execution_engine.py::_create_position_reconciliation_report` "
        f"before updating this constant."
    )


def _instrument() -> BinaryOption:
    """A real captured Polymarket.us market, never a fabricated instrument."""
    payloads = iter_captured_market_payloads()
    assert payloads, "no captured Polymarket.us market payloads on disk"
    return parse_binary_option(payloads[0], ts_init=0)


@dataclass(kw_only=True)
class _Rig:
    """An in-process live execution engine holding one open Breezy position."""

    engine: LiveExecutionEngine
    cache: Cache
    portfolio: Portfolio
    instrument: BinaryOption
    account_id: AccountId
    position_id: PositionId
    position_events: list[PositionEvent] = field(default_factory=list)

    def flat_venue_report(self) -> PositionStatusReport:
        """What the venue sends once the market has resolved: FLAT, no avg px."""
        return PositionStatusReport(
            account_id=self.account_id,
            instrument_id=self.instrument.id,
            position_side=PositionSide.FLAT,
            quantity=Quantity(0, self.instrument.size_precision),
            report_id=UUID4(),
            ts_last=1,
            ts_init=1,
        )

    def reconciliation_orders(self) -> list[Order]:
        """Orders the ENGINE synthesised (i.e. not the one Breezy submitted)."""
        return [order for order in self.cache.orders() if order.side == OrderSide.SELL]


def _build_rig(
    loop: asyncio.AbstractEventLoop,
    *,
    with_cached_quote: bool,
    claim_instrument: bool,
) -> _Rig:
    """Build the engine in-process. No node, no clients, no sockets."""
    clock = LiveClock()
    msgbus = MessageBus(trader_id=TRADER_ID, clock=clock)
    cache = Cache(database=None, config=CacheConfig(database=None, flush_on_start=False))

    instrument = _instrument()
    cache.add_instrument(instrument)
    currency = instrument.quote_currency
    account_id = AccountId(f"{instrument.id.venue}-001")

    account_state = AccountState(
        account_id=account_id,
        account_type=AccountType.CASH,
        base_currency=currency,
        reported=True,
        balances=[
            AccountBalance(
                Money(ACCOUNT_BALANCE, currency),
                Money(0, currency),
                Money(ACCOUNT_BALANCE, currency),
            ),
        ],
        margins=[],
        info={},
        event_id=UUID4(),
        ts_event=0,
        ts_init=0,
    )
    cache.add_account(AccountFactory.create(account_state))

    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    portfolio.update_account(account_state)

    engine = LiveExecutionEngine(
        loop=loop,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        # R-2's pins: in-flight and open/position checks disabled. They are
        # irrelevant here and would otherwise arm background timers.
        config=LiveExecEngineConfig(
            inflight_check_interval_ms=0,
            open_check_interval_secs=None,
            position_check_interval_secs=None,
        ),
    )

    if claim_instrument:
        # R-9's attribution fix. `_generate_order` reads the claim at
        # `live/execution_engine.py:3551`; with no claim it assigns
        # `StrategyId("EXTERNAL")` (`:3556`) and the reconciliation fill forms
        # a SEPARATE position that never closes the Breezy one.
        engine.register_external_order_claims(
            Strategy(
                config=StrategyConfig(
                    strategy_id=STRATEGY_NAME,
                    order_id_tag=ORDER_ID_TAG,
                    external_order_claims=[instrument.id],
                ),
            ),
        )

    # ---- the open Breezy position, built from a real OrderFilled ----
    # The position id follows the NETTING convention
    # (`f"{instrument_id}-{strategy_id}"`), otherwise the reconciliation fill
    # nets against nothing and the test measures an artefact.
    position_id = PositionId(f"{instrument.id}-{STRATEGY_ID}")
    orders = OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=clock)
    quantity = Quantity(OPEN_QUANTITY, instrument.size_precision)
    open_price = Price(OPEN_PRICE, instrument.price_precision)

    order = orders.market(
        instrument_id=instrument.id,
        order_side=OrderSide.BUY,  # Breezy never shorts (`allow_short=False`)
        quantity=quantity,
    )
    cache.add_order(order, position_id=position_id)
    order.apply(
        OrderSubmitted(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            instrument_id=instrument.id,
            client_order_id=order.client_order_id,
            account_id=account_id,
            event_id=UUID4(),
            ts_event=0,
            ts_init=0,
        ),
    )
    fill = OrderFilled(
        trader_id=TRADER_ID,
        strategy_id=STRATEGY_ID,
        instrument_id=instrument.id,
        client_order_id=order.client_order_id,
        venue_order_id=VenueOrderId("V-OPEN-1"),
        account_id=account_id,
        trade_id=TradeId("T-OPEN-1"),
        position_id=position_id,
        order_side=OrderSide.BUY,
        order_type=order.order_type,
        last_qty=quantity,
        last_px=open_price,
        currency=currency,
        commission=Money(0, currency),
        liquidity_side=LiquiditySide.TAKER,
        event_id=UUID4(),
        ts_event=0,
        ts_init=0,
    )
    order.apply(fill)
    cache.update_order(order)
    cache.add_position(Position(instrument=instrument, fill=fill), OmsType.NETTING)

    if with_cached_quote:
        cache.add_quote_tick(
            QuoteTick(
                instrument_id=instrument.id,
                bid_price=Price(STALE_BID, instrument.price_precision),
                ask_price=Price(STALE_ASK, instrument.price_precision),
                bid_size=Quantity(1, instrument.size_precision),
                ask_size=Quantity(1, instrument.size_precision),
                ts_event=0,
                ts_init=0,
            ),
        )

    rig = _Rig(
        engine=engine,
        cache=cache,
        portfolio=portfolio,
        instrument=instrument,
        account_id=account_id,
        position_id=position_id,
    )
    msgbus.subscribe(topic="events.position.*", handler=rig.position_events.append)
    return rig


@pytest.fixture
def rig(event_loop_for_rig: asyncio.AbstractEventLoop) -> _Rig:
    return _build_rig(event_loop_for_rig, with_cached_quote=True, claim_instrument=True)


@pytest.fixture
def event_loop_for_rig() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


# --------------------------------------------------------------------------
# The default configuration that arms the hazard
# --------------------------------------------------------------------------


def test_generate_missing_orders_defaults_to_true() -> None:
    """`live/config.py:183` -- nobody has to choose this for it to fire."""
    assert LiveExecEngineConfig().generate_missing_orders is True


# --------------------------------------------------------------------------
# Non-vacuity: the unguarded native path, measured end to end
# --------------------------------------------------------------------------


def test_calculate_reconciliation_price_returns_the_open_price_for_a_flat_target() -> None:
    """The pricing function itself, at the pure-function level.

    A long-to-flat target with NO target `avg_px_open` returns the CURRENT
    average price, not `None`. That single fact is why every downstream
    fallback in `_create_position_reconciliation_report` is dead code on this
    path -- and why the plan's "a cached quote tick prevents it" is false.
    """
    priced = nautilus_pyo3.calculate_reconciliation_price(
        Decimal(OPEN_QUANTITY),
        Decimal(str(OPEN_PRICE)),
        Decimal(0),
        None,  # the venue's FLAT report carries no `avg_px_open`
    )
    assert priced is not None, (
        "`calculate_reconciliation_price` now returns None for a flat target. "
        "The bid / `current_avg_px` fallbacks at "
        "`live/execution_engine.py:2871-2881` have become REACHABLE. Re-read "
        "this whole module before changing anything."
    )
    assert Decimal(str(priced)) == Decimal(str(OPEN_PRICE))


def test_the_unguarded_reconciliation_books_the_open_price(rig: _Rig) -> None:
    """End to end: the synthesised closing order is priced at `avg_px_open`.

    This is the non-vacuity half of the pin below -- it proves the dangerous
    path is actually exercised by this rig, so the pin's assertions have teeth
    rather than passing because nothing happened.
    """
    assert rig.engine._reconcile_position_report_netting(rig.flat_venue_report()) is True

    synthesised = rig.reconciliation_orders()
    assert len(synthesised) == 1, synthesised
    assert Decimal(str(synthesised[0].avg_px)) == Decimal(str(OPEN_PRICE))
    assert synthesised[0].side == OrderSide.SELL
    # R-9 test 7's premise, measured. A CLAIMED instrument's reconciliation
    # order carries `tags=None` (`live/execution_engine.py:3567`); only the
    # UNCLAIMED branch sets `["RECONCILIATION"]` (`:3563`). R-6a's guard no
    # longer keys on a tag at all -- its exemption keys on
    # `event.reconciliation` instead (`backtest_order_guard.py`), which is
    # unforgeable through any public construction path. See RED-6 below:
    # this event is never even published to the guard's topic, so the
    # exemption's reach on THIS path is moot in 1.231.0 either way.
    assert synthesised[0].tags is None


def test_reconciliation_publishes_no_order_initialized_to_the_guard(rig: _Rig) -> None:
    """R-6a RED-6 (D2/§2, M1). The guard's handler must never see an
    `OrderInitialized` synthesised by reconciliation -- proven here
    BEHAVIOURALLY, on the exact rig `test_the_unguarded_reconciliation_
    books_the_open_price` drives, rather than assumed from a
    publisher-shape grep that a future `publish(topic=..., msg=...)` call
    could silently stop matching. A REAL `BacktestOrderGuard` is subscribed
    to the SAME message bus the engine was built with; if it ever raised
    (it would, since the synthesised leg is a full-size SELL) this test
    would fail as loudly as a naked short in production.
    """
    guard = BacktestOrderGuard(rig.portfolio, rig.cache)
    received: list[Event] = []

    def _handler(event: Event) -> None:
        received.append(event)
        guard.on_order_event(event)  # must never raise -- see the assertion below

    rig.engine._msgbus.subscribe(topic=ORDER_EVENT_TOPIC, handler=_handler)

    assert rig.engine._reconcile_position_report_netting(rig.flat_venue_report()) is True

    assert not any(type(event) is OrderInitialized for event in received)


def test_the_cached_quote_bid_is_never_consulted_for_a_flat_target(
    event_loop_for_rig: asyncio.AbstractEventLoop,
) -> None:
    """With a quote and without one, the SAME price is booked.

    Refutes "a single cached quote tick prevents it": the quote is not a
    mitigation, it is simply never read on this path.
    """
    booked: dict[bool, Decimal] = {}
    for with_quote in (True, False):
        local = _build_rig(
            event_loop_for_rig,
            with_cached_quote=with_quote,
            claim_instrument=True,
        )
        assert (local.cache.quote_tick(local.instrument.id) is not None) is with_quote
        assert local.engine._reconcile_position_report_netting(
            local.flat_venue_report(),
        ) is True
        synthesised = local.reconciliation_orders()
        assert len(synthesised) == 1, synthesised
        booked[with_quote] = Decimal(str(synthesised[0].avg_px))

    assert booked[True] == booked[False] == Decimal(str(OPEN_PRICE)), booked
    assert booked[True] != Decimal(str(STALE_BID))


def test_without_an_external_order_claim_the_position_is_never_closed(
    event_loop_for_rig: asyncio.AbstractEventLoop,
) -> None:
    """The DEFAULT R-4 shape is worse still: no close happens at all.

    Without `external_order_claims`, `_generate_order` assigns
    `StrategyId("EXTERNAL")` (`live/execution_engine.py:3553-3556`) and the
    synthesised SELL forms a SEPARATE `<instrument>-EXTERNAL` position. The
    Breezy position stays OPEN forever, no `PositionClosed` is ever emitted,
    and no realized-PnL row exists -- which is precisely the goal-state clause
    R-9 exists to produce.
    """
    local = _build_rig(
        event_loop_for_rig,
        with_cached_quote=True,
        claim_instrument=False,
    )
    assert local.engine._reconcile_position_report_netting(
        local.flat_venue_report(),
    ) is True

    breezy_position = local.cache.position(local.position_id)
    assert breezy_position.is_open, "unexpected close -- re-read the attribution trap"
    assert breezy_position.realized_pnl == Money(0, local.instrument.quote_currency)

    phantom = [
        position
        for position in local.cache.positions()
        if position.id != local.position_id
    ]
    assert len(phantom) == 1, phantom
    assert phantom[0].strategy_id == StrategyId("EXTERNAL")
    assert phantom[0].side == PositionSide.SHORT


def test_the_unguarded_reconciliation_realizes_exactly_zero(rig: _Rig) -> None:
    """The position closes and `realized_pnl` is 0 -- a settled trade that made
    nothing, on a contract that is worth 1.00 or 0.00."""
    assert rig.engine._reconcile_position_report_netting(rig.flat_venue_report()) is True

    position = rig.cache.position(rig.position_id)
    assert position.is_closed, "the venue-flat report did not close the position"
    assert Decimal(str(position.avg_px_close)) == Decimal(str(position.avg_px_open))
    assert position.realized_pnl == Money(0, rig.instrument.quote_currency)

    closed = [event for event in rig.position_events if isinstance(event, PositionClosed)]
    assert len(closed) == 1, rig.position_events
    assert closed[0].realized_pnl == Money(0, rig.instrument.quote_currency)


# --------------------------------------------------------------------------
# The pin
# --------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "RED for EXEC_SPINE R-9, STILL. R-4 landed "
        "`src/breezy/adapters/polymarket_us/exec/client.py`, so the module is "
        "no longer empty and the `_send_order_status_report` seam IS "
        "reachable -- it is the native `_query_order` path, CALLED (not "
        "absent) at `live/execution_client.py:516-532`, closed only because "
        "this client's own `generate_order_status_report` always returns "
        "`None` (pinned by "
        "`tests/unit/test_polymarket_us_exec_client.py::"
        "test_native_query_order_never_reaches_the_send_seam`). What is still "
        "genuinely missing is R-9's OWN guard: nothing yet supplies an "
        "NWS-keyed settlement price to that seam, and no `SettlementExitActor` "
        "exists to drive it. The assertions below are at FULL strength and "
        "are NOT to be weakened. `strict=True` means this file goes RED the "
        "moment R-9's guard lands: an XPASS fails the suite, forcing the "
        "marker off. That is the intended signal, not a regression."
    ),
)
def test_reconciliation_fallback_price_is_never_booked(rig: _Rig) -> None:
    """A settled binary closes at 1.00 or 0.00 -- never a fallback price."""
    assert rig.engine._reconcile_position_report_netting(rig.flat_venue_report()) is True

    synthesised = rig.reconciliation_orders()
    assert len(synthesised) == 1, synthesised
    booked = Decimal(str(synthesised[0].avg_px))

    assert booked != Decimal(str(STALE_BID)), "booked the stale cached bid"
    assert booked != Decimal(str(OPEN_PRICE)), "booked the OPEN price: realized_pnl is 0"
    assert booked in LEGAL_SETTLEMENT_PRICES, (
        f"booked {booked}, which is not a legal binary settlement price"
    )
