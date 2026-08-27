"""Unit tests for the submit-time order screen.

The integration proof -- that these refusals actually fire inside a running
``BacktestEngine`` -- lives in
``tests/integration/test_backtest_run_refusals.py``. THIS module pins the rule
boundaries directly against the handler, where a live engine cannot easily
produce the cases: a sell exactly equal to the net long, a sell against
already-working sells, the ``reduce_only`` exemption, and the fact that the
screen ignores every order event except ``OrderInitialized``.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
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

from breezy.runtime.backtest_harness import HARNESS_SOURCE_PATH
from breezy.runtime.backtest_order_guard import (
    ORDER_EVENT_TOPIC,
    BacktestOrderGuard,
    NakedShortRefusedError,
    PostOnlyRefusedError,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Sequence

INSTRUMENT = InstrumentId(Symbol("synthetic-guard-market"), Venue("POLYMARKET_US"))


class _FakePortfolio:
    def __init__(self, net: Decimal) -> None:
        self._net = net

    def net_position(self, instrument_id: InstrumentId) -> Decimal:
        del instrument_id
        return self._net


class _FakeOrder:
    def __init__(self, *, side: OrderSide, leaves: Decimal, reduce_only: bool = False) -> None:
        self.side = side
        self.leaves_qty = Quantity(leaves, 0)
        self.is_reduce_only = reduce_only


class _FakeCache:
    def __init__(self, open_orders: Sequence[_FakeOrder] = ()) -> None:
        self._open = list(open_orders)

    def orders_open(self, *, instrument_id: InstrumentId | None = None) -> list[_FakeOrder]:
        del instrument_id
        return self._open


def _guard(
    *,
    net: Decimal = Decimal(0),
    open_orders: Sequence[_FakeOrder] = (),
) -> BacktestOrderGuard:
    return BacktestOrderGuard(_FakePortfolio(net), _FakeCache(open_orders))  # type: ignore[arg-type]


def _initialized(
    *,
    side: OrderSide = OrderSide.SELL,
    quantity: int = 1,
    post_only: bool = False,
    reduce_only: bool = False,
) -> OrderInitialized:
    return OrderInitialized(
        trader_id=TraderId("BREEZY-BACKTEST-001"),
        strategy_id=StrategyId("S-1"),
        instrument_id=INSTRUMENT,
        client_order_id=ClientOrderId("O-1"),
        order_side=side,
        order_type=OrderType.LIMIT,
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
        tags=None,
        event_id=UUID4(),
        ts_init=0,
    )


# ---------------------------------------------------------------------------
# post_only
# ---------------------------------------------------------------------------


def test_a_post_only_buy_is_refused() -> None:
    with pytest.raises(PostOnlyRefusedError) as excinfo:
        _guard().on_order_event(_initialized(side=OrderSide.BUY, post_only=True))

    assert "post_only=True" in str(excinfo.value)


def test_a_marketable_buy_is_accepted() -> None:
    _guard().on_order_event(_initialized(side=OrderSide.BUY, post_only=False))


# ---------------------------------------------------------------------------
# naked shorts -- the boundary is `>`, not `>=`
# ---------------------------------------------------------------------------


def test_a_sell_exactly_equal_to_the_net_long_is_accepted() -> None:
    """Flattening a position is not a naked short, and must stay writable."""
    _guard(net=Decimal(10)).on_order_event(_initialized(quantity=10))


def test_a_sell_one_unit_beyond_the_net_long_is_refused() -> None:
    with pytest.raises(NakedShortRefusedError):
        _guard(net=Decimal(10)).on_order_event(_initialized(quantity=11))


def test_a_sell_with_no_position_at_all_is_refused() -> None:
    with pytest.raises(NakedShortRefusedError) as excinfo:
        _guard(net=Decimal(0)).on_order_event(_initialized(quantity=1))

    assert str(INSTRUMENT) in str(excinfo.value)


def test_two_sells_that_are_each_within_the_net_long_are_JOINTLY_refused() -> None:
    """The case a position-only check cannot see.

    Each sell alone is fully covered; together they are naked. The working
    quantity is read from the cache, so cancels and partial fills need no
    bookkeeping in the guard.
    """
    working = [_FakeOrder(side=OrderSide.SELL, leaves=Decimal(10))]

    with pytest.raises(NakedShortRefusedError) as excinfo:
        _guard(net=Decimal(10), open_orders=working).on_order_event(_initialized(quantity=10))

    assert "already working" in str(excinfo.value)


def test_a_working_BUY_does_not_count_against_the_sell_budget() -> None:
    working = [_FakeOrder(side=OrderSide.BUY, leaves=Decimal(10))]

    _guard(net=Decimal(10), open_orders=working).on_order_event(_initialized(quantity=10))


def test_a_working_reduce_only_sell_does_not_count_against_the_budget() -> None:
    """The engine's own settlement leg is `reduce_only`; it cannot make a
    strategy's legitimate exit look naked.
    """
    working = [_FakeOrder(side=OrderSide.SELL, leaves=Decimal(10), reduce_only=True)]

    _guard(net=Decimal(10), open_orders=working).on_order_event(_initialized(quantity=10))


def test_a_reduce_only_sell_is_exempt() -> None:
    _guard(net=Decimal(0)).on_order_event(_initialized(quantity=500, reduce_only=True))


def test_a_buy_is_never_a_naked_short() -> None:
    _guard(net=Decimal(0)).on_order_event(_initialized(side=OrderSide.BUY, quantity=500))


# ---------------------------------------------------------------------------
# Scope: only `OrderInitialized`, and only via the documented topic
# ---------------------------------------------------------------------------


def test_a_non_initialized_order_event_is_ignored() -> None:
    """The topic carries the whole lifecycle, including the settlement leg's
    own accepted/filled events. Screening those would be a false positive.
    """

    class _NotAnInitialization:
        post_only = True
        side = OrderSide.SELL
        quantity = Quantity(500, 0)
        reduce_only = False
        instrument_id = INSTRUMENT
        client_order_id = ClientOrderId("O-2")

    _guard().on_order_event(_NotAnInitialization())  # type: ignore[arg-type]


def test_the_topic_is_the_one_strategies_publish_on() -> None:
    """`trading/strategy.pyx:322` subscribes to `events.order.<strategy_id>`;
    the guard's glob must cover every strategy in the run.
    """
    assert ORDER_EVENT_TOPIC == "events.order.*"


def test_the_harness_installs_the_guard() -> None:
    """A screen nobody wires up is a comment."""
    source = Path(HARNESS_SOURCE_PATH).read_text(encoding="utf-8")

    assert "install_order_guard(engine)" in source
