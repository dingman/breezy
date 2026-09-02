"""Unit pins for the shared in-flight order view (`weather_common.inflight`).

The defect this module guards (T-1,
``docs/plans/T1_STRATEGY_INFLIGHT_BLINDNESS_2026-09-02.md``): every weather
strategy asked ``cache.orders_open(...)`` both to gate re-submission and to
size committed exposure, and ``Order.is_open_c`` (``model/orders/base.pyx``)
excludes ``INITIALIZED`` and ``SUBMITTED``. Inside the submit -> ACCEPTED
window the strategy therefore saw nothing working and re-submitted.

Everything here runs against REAL ``nautilus_trader`` order objects driven
through real lifecycle events -- a hand-rolled double could not prove the
``leaves_qty`` property that makes widening onto ``PARTIALLY_FILLED`` safe.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import TestClock
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.config import CacheConfig
from nautilus_trader.model.enums import OrderSide, OrderStatus
from nautilus_trader.model.identifiers import StrategyId, TraderId
from nautilus_trader.test_kit.stubs.events import TestEventStubs

from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.strategy.weather_common.inflight import signed_working_qty, working_orders
from tests.unit.conftest import iter_captured_market_payloads

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.model.instruments import BinaryOption
    from nautilus_trader.model.orders.base import Order

TRADER_ID = TraderId("BREEZY-INFLIGHT-001")
STRATEGY_ID = StrategyId("S-INFLIGHT")


def _instrument() -> BinaryOption:
    payloads = iter_captured_market_payloads()
    assert payloads, "no captured Polymarket.us market payloads on disk"
    return parse_binary_option(payloads[0], ts_init=0)


class _Rig:
    """A real ``Cache`` plus a real ``OrderFactory`` -- no strategy needed."""

    def __init__(self) -> None:
        self.clock = TestClock()
        self.instrument = _instrument()
        self.cache = Cache(
            database=None,
            config=CacheConfig(database=None, flush_on_start=False),
        )
        self.cache.add_instrument(self.instrument)
        self.orders = OrderFactory(
            trader_id=TRADER_ID,
            strategy_id=STRATEGY_ID,
            clock=self.clock,
        )

    def _new(self, *, side: OrderSide, quantity: int) -> Order:
        order = self.orders.market(
            instrument_id=self.instrument.id,
            order_side=side,
            quantity=self.instrument.make_qty(quantity),
        )
        self.cache.add_order(order)
        return order

    def initialized(self, *, side: OrderSide = OrderSide.BUY, quantity: int = 100) -> Order:
        """Created and cached, no lifecycle event applied yet."""
        return self._new(side=side, quantity=quantity)

    def submitted(self, *, side: OrderSide = OrderSide.BUY, quantity: int = 100) -> Order:
        order = self._new(side=side, quantity=quantity)
        order.apply(TestEventStubs.order_submitted(order))
        self.cache.update_order(order)
        return order

    def accepted(self, *, side: OrderSide = OrderSide.BUY, quantity: int = 100) -> Order:
        order = self.submitted(side=side, quantity=quantity)
        order.apply(TestEventStubs.order_accepted(order))
        self.cache.update_order(order)
        return order

    def partially_filled(
        self,
        *,
        side: OrderSide = OrderSide.BUY,
        quantity: int = 100,
        filled: int = 60,
    ) -> Order:
        order = self.accepted(side=side, quantity=quantity)
        order.apply(
            TestEventStubs.order_filled(
                order,
                self.instrument,
                last_qty=self.instrument.make_qty(filled),
                last_px=self.instrument.make_price(0.5),
            ),
        )
        self.cache.update_order(order)
        return order

    def filled(self, *, side: OrderSide = OrderSide.BUY, quantity: int = 100) -> Order:
        order = self.accepted(side=side, quantity=quantity)
        order.apply(
            TestEventStubs.order_filled(
                order,
                self.instrument,
                last_px=self.instrument.make_price(0.5),
            ),
        )
        self.cache.update_order(order)
        return order

    def canceled(self, *, side: OrderSide = OrderSide.BUY, quantity: int = 100) -> Order:
        order = self.accepted(side=side, quantity=quantity)
        order.apply(TestEventStubs.order_canceled(order))
        self.cache.update_order(order)
        return order

    def working(self) -> list[Order]:
        return working_orders(self.cache, self.instrument.id)


@pytest.fixture
def rig() -> _Rig:
    return _Rig()


def test_working_orders_sees_an_initialized_order_that_orders_open_misses(
    rig: _Rig,
) -> None:
    order = rig.initialized()

    assert order.status == OrderStatus.INITIALIZED
    assert rig.cache.orders_open(instrument_id=rig.instrument.id) == []
    assert rig.working() == [order]


def test_working_orders_sees_a_submitted_order_that_orders_open_misses(
    rig: _Rig,
) -> None:
    order = rig.submitted()

    assert order.status == OrderStatus.SUBMITTED
    assert rig.cache.orders_open(instrument_id=rig.instrument.id) == []
    assert rig.working() == [order]


def test_working_orders_still_sees_an_accepted_order(rig: _Rig) -> None:
    order = rig.accepted()

    assert rig.cache.orders_open(instrument_id=rig.instrument.id) == [order]
    assert rig.working() == [order]


def test_working_orders_excludes_filled_and_canceled_orders(rig: _Rig) -> None:
    rig.filled()
    rig.canceled()

    assert rig.working() == []


def test_working_orders_is_empty_when_nothing_was_ever_submitted(rig: _Rig) -> None:
    assert rig.working() == []


def test_signed_working_qty_is_zero_for_no_orders() -> None:
    assert signed_working_qty([]) == 0.0


def test_signed_working_qty_signs_buys_positive_and_sells_negative(rig: _Rig) -> None:
    rig.submitted(side=OrderSide.BUY, quantity=200)
    rig.submitted(side=OrderSide.SELL, quantity=50)

    assert signed_working_qty(rig.working()) == pytest.approx(150.0)


def test_signed_working_qty_counts_leaves_not_original_quantity(rig: _Rig) -> None:
    """The property that makes widening onto ``PARTIALLY_FILLED`` safe.

    ``Order.signed_decimal_qty()`` (``model/orders/base.pyx``) is built from
    ``leaves_qty``, so the 60 already filled -- which the portfolio's settled
    position now carries -- is NOT counted a second time here.
    """
    order = rig.partially_filled(quantity=100, filled=60)

    assert order.status == OrderStatus.PARTIALLY_FILLED
    assert signed_working_qty(rig.working()) == pytest.approx(40.0)
