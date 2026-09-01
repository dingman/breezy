"""`BreezyRestingLadder` -- a LIMIT-order, resting-liquidity strategy.

Written as an acceptance exercise for the backtest harness: unlike
``breezy.strategy.harness_probe`` (one MARKET BUY, no lifecycle), this
strategy submits several LIMIT orders, modifies one, cancels another, is
driven by ``on_order_book_depth`` rather than by weather, and uses three
Nautilus facilities the probe does not touch -- ``self.clock`` time alerts,
``self.cache``, and ``self.portfolio``.

Shape of the run
----------------

On the FIRST depth snapshot:

* **TAKE** -- one marketable ``LIMIT BUY`` priced AT the best ask. Marketable
  rather than post-only, because ``PolymarketUSFeeModel`` refuses
  ``post_only=True`` outright (``MakerRebateUnmodelledError``) and prices any
  incidental maker fill at the taker coefficient, which is wrong in SIGN.
* **REST** -- one ``LIMIT BUY`` priced ``rest_offset_ticks`` BELOW the best
  bid, which should not be marketable and should sit in the book.

Two time alerts are then armed off the ENGINE clock (never wall clock):

* ``reprice`` -- modifies the resting bid up by one tick and grows its size,
  proving the modify round-trip.
* ``sweep`` -- cancels whatever is still open, proving the cancel round-trip.

On the first fill the strategy also posts an **exit** ``LIMIT SELL`` above the
book, sized from ``self.cache.position(...)`` and cross-checked against
``self.portfolio.net_position(...)``. That size is capped at the cached net
long quantity: ``docs/specs/BACKTEST_VENUE_CONFIG.md`` §2 records that on a
CASH account a naked SELL passes every ``RiskEngine`` check and *raises* free
cash, so the guard has to live in the strategy. The sell is deliberately
priced where it will not fill on a flat tape; what it exercises is that the
engine's expiration latch cancels it (``engine.pyx:5936-5947``).

Nothing here imports ``breezy.adapters.polymarket_us``: that would make this
module venue-touching under the read-only guard's classifier C4, and the
instrument is resolved from the native cache anyway. Strategies that need
weather-bucket station/day/bounds should read the cached instrument's
corroborated facts with
``breezy.domain.weather_bucket_facts.read_weather_bucket_facts`` rather than
importing a venue adapter or hand-typing bucket bounds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nautilus_trader.model.enums import LiquiditySide, OrderSide, TimeInForce
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from breezy.strategy.depth10 import best_order

if TYPE_CHECKING:  # pragma: no cover - typing only
    from decimal import Decimal

    from nautilus_trader.common.component import TimeEvent
    from nautilus_trader.model.data import BookOrder, OrderBookDepth10
    from nautilus_trader.model.events import (
        OrderCanceled,
        OrderFilled,
        OrderRejected,
        OrderUpdated,
    )
    from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
    from nautilus_trader.model.instruments import Instrument
    from nautilus_trader.model.objects import Price
    from nautilus_trader.model.orders import Order

__all__ = ["BreezyRestingLadder", "BreezyRestingLadderConfig"]

#: Timer names. Unique per clock; ``set_time_alert_ns`` raises on a repeat.
_REPRICE_ALERT = "resting-ladder-reprice"
_SWEEP_ALERT = "resting-ladder-sweep"


class BreezyRestingLadderConfig(StrategyConfig, frozen=True):
    """Configuration for :class:`BreezyRestingLadder`.

    Parameters
    ----------
    instrument_id : InstrumentId
        The market to trade. Supplied, not discovered, so the strategy stays
        venue-agnostic and portable to Kalshi.
    clip : Decimal
        Base order size in contracts. Coerced through ``Instrument.make_qty``
        because the captured universe carries both ``size_precision=0`` and
        ``=2``.
    rest_offset_ticks : int
        How many ``price_increment`` steps BELOW the best bid the resting buy
        sits. Must be >= 1 or the order would join the touch.
    exit_offset_ticks : int
        How many ticks ABOVE the best ask the exit sell is posted.
    reprice_after_ns : int
        Nanoseconds after the first depth snapshot at which the resting buy is
        modified.
    sweep_after_ns : int
        Nanoseconds after the first depth snapshot at which every still-open
        order is cancelled. Must exceed ``reprice_after_ns``.

    """

    instrument_id: InstrumentId
    clip: Decimal
    rest_offset_ticks: int = 1
    exit_offset_ticks: int = 10
    reprice_after_ns: int = 2_000_000_000
    sweep_after_ns: int = 4_000_000_000


class BreezyRestingLadder(Strategy):
    """Take once, rest once, modify, cancel, and try to exit.

    Every counter is a plain attribute so a test reads exactly the integer a
    callback incremented.
    """

    def __init__(self, config: BreezyRestingLadderConfig) -> None:
        super().__init__(config)
        # -- what arrived
        self.depths: int = 0
        self.quotes: int = 0
        # -- what we did
        self.orders_submitted: int = 0
        self.modifies_requested: int = 0
        self.cancels_requested: int = 0
        # -- what came back
        self.fills: int = 0
        self.own_fills: int = 0
        self.maker_fills: int = 0
        self.updates: int = 0
        self.cancel_events: int = 0
        self.rejections: int = 0
        self.timer_events: int = 0
        self.own_fill_sides: tuple[OrderSide, ...] = ()
        #: Ordered decision log; engine timestamps only, never wall clock.
        self.decisions: list[str] = []
        #: Portfolio/cache readings taken at the sweep alert, so a test can
        #: prove those surfaces were reachable from inside a running strategy.
        self.net_position_at_sweep: Decimal | None = None
        self.open_orders_at_sweep: int | None = None

        self._instrument: Instrument | None = None
        self._own_order_ids: set[ClientOrderId] = set()
        self._resting_id: ClientOrderId | None = None
        self._exit_submitted: bool = False

    # -- lifecycle ---------------------------------------------------------

    def on_start(self) -> None:
        instrument = self.cache.instrument(self.config.instrument_id)
        if instrument is None:
            self.log.error(
                f"no instrument {self.config.instrument_id} in the cache; stopping",
            )
            self.stop()
            return
        self._instrument = instrument
        self.subscribe_order_book_depth(instrument.id)
        self.subscribe_quote_ticks(instrument.id)
        self._record(0, "started", str(instrument.id))

    # -- data --------------------------------------------------------------

    def on_quote_tick(self, tick: object) -> None:
        del tick
        self.quotes += 1

    def on_order_book_depth(self, depth: OrderBookDepth10) -> None:
        """Act on the FIRST snapshot only; count the rest."""
        self.depths += 1
        instrument = self._instrument
        if instrument is None:
            return

        best_bid = self._best(depth.bids)
        best_ask = self._best(depth.asks)
        self._record(
            depth.ts_event,
            "depth",
            f"seq={depth.sequence}:{best_bid}/{best_ask}",
        )
        if self.orders_submitted or best_bid is None or best_ask is None:
            return

        quantity = instrument.make_qty(self.config.clip)
        tick_size = instrument.price_increment.as_decimal()

        # (1) Marketable LIMIT BUY at the touch -- expected TAKER fill.
        take = self.order_factory.limit(
            instrument_id=instrument.id,
            order_side=OrderSide.BUY,
            quantity=quantity,
            price=best_ask,
            time_in_force=TimeInForce.GTC,
            post_only=False,
        )
        self._submit(take, depth.ts_event, f"take BUY {quantity}@{best_ask}")

        # (2) Resting LIMIT BUY below the touch -- expected to sit unfilled.
        rest_px = instrument.make_price(
            best_bid.as_decimal() - tick_size * self.config.rest_offset_ticks,
        )
        rest = self.order_factory.limit(
            instrument_id=instrument.id,
            order_side=OrderSide.BUY,
            quantity=quantity,
            price=rest_px,
            time_in_force=TimeInForce.GTC,
            post_only=False,
        )
        self._resting_id = rest.client_order_id
        self._submit(rest, depth.ts_event, f"rest BUY {quantity}@{rest_px}")

        # Alerts are armed off the ENGINE clock, from the timestamp of the
        # snapshot that triggered them.
        now_ns = self.clock.timestamp_ns()
        self.clock.set_time_alert_ns(
            name=_REPRICE_ALERT,
            alert_time_ns=now_ns + self.config.reprice_after_ns,
            callback=self._on_alert,
        )
        self.clock.set_time_alert_ns(
            name=_SWEEP_ALERT,
            alert_time_ns=now_ns + self.config.sweep_after_ns,
            callback=self._on_alert,
        )

    # -- timers ------------------------------------------------------------

    def _on_alert(self, event: TimeEvent) -> None:
        self.timer_events += 1
        if event.name == _REPRICE_ALERT:
            self._reprice(event.ts_event)
        elif event.name == _SWEEP_ALERT:
            self._sweep(event.ts_event)

    def _reprice(self, ts_event: int) -> None:
        """Modify the resting bid: one tick up, and 50% larger."""
        instrument = self._instrument
        order = self._resting_order()
        if instrument is None or order is None:
            self._record(ts_event, "reprice-skipped", "resting order not open")
            return
        new_px = instrument.make_price(
            order.price.as_decimal() + instrument.price_increment.as_decimal(),
        )
        new_qty = instrument.make_qty(order.quantity.as_decimal() + self.config.clip)
        self.modifies_requested += 1
        self._record(ts_event, "modify", f"{order.client_order_id}->{new_qty}@{new_px}")
        self.modify_order(order, quantity=new_qty, price=new_px)

    def _sweep(self, ts_event: int) -> None:
        """Read cache/portfolio state, then cancel whatever is still open."""
        instrument_id = self.config.instrument_id
        # `Cache.orders_open` guarantees NO ordering of its result list, so it
        # is sorted before anything is recorded or cancelled -- otherwise the
        # decision log (and the cancel sequence) is non-deterministic.
        open_orders = sorted(
            self.cache.orders_open(instrument_id=instrument_id),
            key=lambda o: o.client_order_id.value,
        )
        self.open_orders_at_sweep = len(open_orders)
        self.net_position_at_sweep = self.portfolio.net_position(instrument_id)
        open_positions = self.cache.positions_open(instrument_id=instrument_id)
        position = self.cache.position(open_positions[0].id) if open_positions else None
        self._record(
            ts_event,
            "sweep",
            f"open={len(open_orders)}:net={self.net_position_at_sweep}:"
            f"pos={'yes' if position is not None else 'no'}",
        )
        for order in open_orders:
            self.cancels_requested += 1
            self._record(ts_event, "cancel", str(order.client_order_id))
            self.cancel_order(order)

    # -- events ------------------------------------------------------------

    def on_order_filled(self, event: OrderFilled) -> None:
        self.fills += 1
        if event.liquidity_side == LiquiditySide.MAKER:
            self.maker_fills += 1
        if event.client_order_id in self._own_order_ids:
            self.own_fills += 1
            self.own_fill_sides = (*self.own_fill_sides, event.order_side)
        # NOT `event.client_order_id` unconditionally: the engine's own
        # settlement leg is stamped `EXPIRATION-LEG-<uuid4>`
        # (`engine.pyx:5947-5958`), which is FRESH ON EVERY RUN even with
        # `use_random_ids=False`. Logging it makes an otherwise deterministic
        # decision log differ between two identical runs.
        who = (
            str(event.client_order_id)
            if event.client_order_id in self._own_order_ids
            else f"engine-leg:{event.venue_order_id}"
        )
        self._record(
            event.ts_event,
            "filled",
            f"{who}:{event.order_side}:{event.last_qty}"
            f"@{event.last_px}:{event.liquidity_side}:{event.commission}",
        )
        self._maybe_post_exit(event.ts_event)

    def on_order_updated(self, event: OrderUpdated) -> None:
        self.updates += 1
        self._record(event.ts_event, "updated", f"{event.client_order_id}:{event.quantity}")

    def on_order_canceled(self, event: OrderCanceled) -> None:
        self.cancel_events += 1
        self._record(event.ts_event, "canceled", str(event.client_order_id))

    def on_order_rejected(self, event: OrderRejected) -> None:
        self.rejections += 1
        self._record(event.ts_event, "rejected", f"{event.client_order_id}:{event.reason}")

    # -- internals ---------------------------------------------------------

    def _maybe_post_exit(self, ts_event: int) -> None:
        """Post a take-profit SELL sized from the CACHED net long only.

        Spec §2: a naked SELL on a CASH account passes every ``RiskEngine``
        check and raises free cash. The size therefore comes from the cache,
        and a non-positive net position posts nothing at all.
        """
        instrument = self._instrument
        if instrument is None or self._exit_submitted:
            return
        net = self.portfolio.net_position(instrument.id)
        if net is None or net <= 0:
            return
        quantity = instrument.make_qty(min(net, self.config.clip))
        last_ask = self._last_ask()
        if last_ask is None:
            return
        exit_px = instrument.make_price(
            last_ask.as_decimal()
            + instrument.price_increment.as_decimal() * self.config.exit_offset_ticks,
        )
        order = self.order_factory.limit(
            instrument_id=instrument.id,
            order_side=OrderSide.SELL,
            quantity=quantity,
            price=exit_px,
            time_in_force=TimeInForce.GTC,
            post_only=False,
        )
        self._exit_submitted = True
        self._submit(order, ts_event, f"exit SELL {quantity}@{exit_px}")

    def _last_ask(self) -> Price | None:
        book = self.cache.order_book(self.config.instrument_id)
        if book is None:
            return None
        asks = book.asks()
        if not asks:
            return None
        best: Price = asks[0].price
        return best

    def _resting_order(self) -> Order | None:
        if self._resting_id is None:
            return None
        order: Order | None = self.cache.order(self._resting_id)
        if order is None or order.is_closed:
            return None
        return order

    def _submit(self, order: Order, ts_event: int, detail: str) -> None:
        self.orders_submitted += 1
        self._own_order_ids.add(order.client_order_id)
        self._record(ts_event, "submit", detail)
        self.submit_order(order)

    @staticmethod
    def _best(side: list[BookOrder]) -> Price | None:
        """Best level of a Depth10 ladder, skipping the null padding.

        ``OrderBookDepth10`` pads short ladders to ten with zero-size orders
        (``model/data.pyx:3499-3504``); a naive ``side[0]`` on an EMPTY side
        would therefore read a synthetic 0.00 level as a real quote.
        """
        level = best_order(side)
        if level is None:
            return None
        price: Price = level.price
        return price

    def _record(self, ts_event: int, kind: str, detail: str) -> None:
        self.decisions.append(f"{ts_event}|{kind}|{detail}")
