"""`BreezyHarnessProbe` -- the reference strategy the backtest harness is proved with.

This strategy is deliberately, aggressively trivial. Its entire purpose is
attribution: when
``tests/contract/test_backtest_harness_stop_gate.py`` fails, the failure must
be the HARNESS's. So the probe counts what arrives, records an ordered
decision log, submits exactly one order, and does nothing else. It asserts
nothing and raises nothing -- pinned from source by
``tests/unit/test_strategy_harness_probe.py``.

Three choices here are load-bearing rather than incidental:

**Weather is subscribed by ``client_id``, never by ``instrument_id``.**
``Actor.subscribe_data(instrument_id=...)`` builds the message-bus pattern
``data.NwsClimateDay.<venue>.<symbol>`` while
``DataType(NwsClimateDay).topic`` is ``NwsClimateDay*``. ``is_matching_py``
returns False for that pair, so an instrument-scoped weather subscription
receives ZERO records -- no error, no log, no failing assertion anywhere else.
That is also semantically right: one climate day settles many markets, so
weather is not per-instrument data.

**The single order is a MARKET BUY.** MARKET so the fill is unambiguously
TAKER: ``PolymarketUSFeeModel`` prices a maker fill at the taker coefficient,
which is wrong in SIGN (the venue documents a *rebate*), making any
maker-dependent result unevaluable rather than merely pessimistic. BUY so the
probe never depends on the naked-short hazard of
``docs/specs/BACKTEST_VENUE_CONFIG.md`` §2 -- on a CASH account a naked SELL
passes every ``RiskEngine`` check and *raises* free cash.

**Nothing from ``breezy.adapters.polymarket_us`` is imported.** That import
would make this module venue-touching under classifier C4 of the read-only
guard (``tests/unit/test_polymarket_us_readonly_guard.py``), inheriting a
write-egress cage it has no reason to carry. The instrument comes from config
and is resolved through the native cache, which is also what will let this
probe run unchanged against Kalshi.

Null hypothesis: ``nautilus_trader.trading.strategy.Strategy`` is the native
extension point for exactly this, and is subclassed directly. No Breezy
strategy base class, no lifecycle wrapper, no event router.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nautilus_trader.model.enums import LiquiditySide, OrderSide
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.ingest.nws_actor import nws_climate_day_data_type
from breezy.runtime.backtest_feed import NWS_BACKTEST_CLIENT_ID

if TYPE_CHECKING:  # pragma: no cover - typing only
    from decimal import Decimal

    from nautilus_trader.core.data import Data
    from nautilus_trader.core.message import Event
    from nautilus_trader.model.data import InstrumentClose, OrderBookDepth10, QuoteTick
    from nautilus_trader.model.events import OrderFilled
    from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
    from nautilus_trader.model.objects import Quantity

__all__ = ["BreezyHarnessProbe", "BreezyHarnessProbeConfig"]


class BreezyHarnessProbeConfig(StrategyConfig, frozen=True):
    """Configuration for :class:`BreezyHarnessProbe`.

    Parameters
    ----------
    instrument_id : InstrumentId
        The market to subscribe to and trade. Supplied rather than discovered,
        so the probe stays venue-agnostic.
    trade_quantity : Decimal
        Size of the single MARKET BUY, in contracts. Coerced to the
        instrument's own ``size_precision`` via ``Instrument.make_qty`` --
        never to a literal precision, because the captured universe carries
        both ``size_precision=0`` and ``=2``.

    """

    instrument_id: InstrumentId
    trade_quantity: Decimal


class BreezyHarnessProbe(Strategy):
    """Counts what arrives, buys once, and never fails on its own.

    Every counter is a plain attribute rather than a property over some
    internal collection: a test that reads ``probe.weather`` should be reading
    the same integer the callback incremented, with nothing in between.
    """

    def __init__(self, config: BreezyHarnessProbeConfig) -> None:
        super().__init__(config)
        self.quotes: int = 0
        self.depths: int = 0
        self.weather: int = 0
        self.closes: int = 0
        self.events: int = 0
        self.fills: int = 0
        self.maker_fills: int = 0
        self.own_fills: int = 0
        self.orders_submitted: int = 0
        #: Fill sides for orders the PROBE submitted, in arrival order. The
        #: engine's settlement leg is excluded, so this stays ``(BUY,)`` even
        #: though the closing leg is a SELL.
        self.own_fill_sides: tuple[OrderSide, ...] = ()
        #: The ordered decision log. Deterministic by construction: it carries
        #: engine timestamps and venue order ids, never wall-clock time and
        #: never the ``uuid4`` the engine stamps into its settlement leg's
        #: ``ClientOrderId``.
        self.decisions: list[str] = []
        #: Client order ids the probe itself submitted. The discriminator for
        #: :attr:`own_fills`: ``OrderFilled`` carries no ``tags`` field
        #: (checked on 1.231.0), so the engine's settlement leg cannot be
        #: recognised by its ``EXPIRATION_<venue>_CLOSE`` tag from the event
        #: alone. Identity of the submitting order is exact and needs no
        #: string matching.
        self._own_order_ids: set[ClientOrderId] = set()
        self._quantity: Quantity | None = None

    # -- lifecycle ---------------------------------------------------------

    def on_start(self) -> None:
        """Resolve the instrument, then subscribe to all four streams."""
        instrument = self.cache.instrument(self.config.instrument_id)
        if instrument is None:
            self.log.error(
                f"no instrument {self.config.instrument_id} in the cache; stopping. "
                f"Add it with `BacktestEngine.add_instrument` before the data.",
            )
            self.stop()
            return

        self._quantity = instrument.make_qty(self.config.trade_quantity)
        self.subscribe_quote_ticks(instrument.id)
        self.subscribe_order_book_depth(instrument.id)
        self.subscribe_instrument_close(instrument.id)
        # `client_id`, NOT `instrument_id`. See the module docstring.
        self.subscribe_data(nws_climate_day_data_type(), client_id=NWS_BACKTEST_CLIENT_ID)
        self._record(0, "started", str(instrument.id))

    # -- data --------------------------------------------------------------

    def on_data(self, data: Data) -> None:
        """Count weather, and on the FIRST record submit one MARKET BUY.

        The type guard comes first and is type-EXACT. ``is_matching_py`` treats
        ``NwsClimateDayExtra*`` as matching ``NwsClimateDay*``, so a record
        class whose name merely STARTS WITH this one's leaks into this
        subscription; counting before checking would score the leak as a
        success.
        """
        if type(data) is not NwsClimateDay:
            return

        self.weather += 1
        self._record(data.ts_event, "weather", f"{data.station}:{data.climate_day.isoformat()}")

        if self.orders_submitted or self._quantity is None:
            return
        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=self._quantity,
        )
        self.orders_submitted += 1
        self._own_order_ids.add(order.client_order_id)
        self._record(data.ts_event, "submit", f"BUY:{order.quantity}")
        self.submit_order(order)

    def on_quote_tick(self, tick: QuoteTick) -> None:
        self.quotes += 1
        self._record(tick.ts_event, "quote", f"{tick.bid_price}/{tick.ask_price}")

    def on_order_book_depth(self, depth: OrderBookDepth10) -> None:
        self.depths += 1
        self._record(depth.ts_event, "depth", f"seq={depth.sequence}")

    def on_instrument_close(self, update: InstrumentClose) -> None:
        self.closes += 1
        self._record(update.ts_event, "close", f"{update.close_type}@{update.close_price}")

    # -- events ------------------------------------------------------------

    def on_event(self, event: Event) -> None:
        self.events += 1

    def on_order_filled(self, event: OrderFilled) -> None:
        """Count every fill; separate the probe's own from the engine's.

        Two fills are CORRECT on a settled run: the probe's entry, and the
        engine's own ``reduce_only`` close leg, which is issued against the
        probe's position and therefore routes back to this handler
        (``backtest/engine.pyx:5947-5958``).
        """
        self.fills += 1
        if event.liquidity_side == LiquiditySide.MAKER:
            self.maker_fills += 1
        if event.client_order_id in self._own_order_ids:
            self.own_fills += 1
            self.own_fill_sides = (*self.own_fill_sides, event.order_side)
        self._record(
            event.ts_event,
            "filled",
            f"{event.venue_order_id}:{event.order_side}:{event.last_qty}"
            f"@{event.last_px}:{event.liquidity_side}:{event.commission}",
        )

    # -- internals ---------------------------------------------------------

    def _record(self, ts_event: int, kind: str, detail: str) -> None:
        self.decisions.append(f"{ts_event}|{kind}|{detail}")
