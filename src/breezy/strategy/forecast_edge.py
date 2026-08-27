"""A simple weather-observation edge buyer for Breezy backtests.

``ForecastHighEdgeBuyer`` is intentionally small but not a probe: it expresses
the ordinary first strategy a weather-market author might write. It watches the
current YES ask, consumes station-filtered ``NwsClimateDay`` records, maps the
reported high temperature to a configured model probability, and buys a fixed
clip only when ``model_probability - ask`` clears the configured threshold.

The strategy uses Nautilus Trader's native ``Strategy``/``StrategyConfig``
extension points directly. It does not import the venue adapter; the harness
provides the instrument and venue configuration.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, cast

from nautilus_trader.model.enums import LiquiditySide, OrderSide
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.ingest.nws_actor import nws_climate_day_data_type
from breezy.runtime.backtest_feed import NWS_BACKTEST_CLIENT_ID

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.core.data import Data
    from nautilus_trader.model.data import BookOrder, OrderBookDepth10, QuoteTick
    from nautilus_trader.model.events import OrderFilled
    from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
    from nautilus_trader.model.objects import Price, Quantity

__all__ = ["ForecastHighEdgeBuyer", "ForecastHighEdgeBuyerConfig"]

_ZERO = Decimal(0)
_ONE = Decimal(1)


class ForecastHighEdgeBuyerConfig(StrategyConfig, frozen=True):
    """Configuration for :class:`ForecastHighEdgeBuyer`.

    Parameters
    ----------
    instrument_id : InstrumentId
        YES market to buy when the model edge is positive enough.
    station : str
        NWS station whose climate-day records may drive the decision.
    yes_if_tmax_at_least_f : int
        Temperature threshold represented by the YES side. If the record's
        ``tmax_f`` is at least this value, the strategy uses
        ``probability_when_yes``; otherwise it uses ``probability_when_no``.
    trade_quantity : Decimal
        Fixed clip size, coerced through the instrument's own precision.
    edge_threshold : Decimal
        Minimum ``model_probability - current_ask`` required before buying.
    probability_when_yes, probability_when_no : Decimal
        Model probabilities assigned to observations above/below the threshold.
    require_final : bool
        When True, ignore preliminary climate-day records.

    """

    instrument_id: InstrumentId
    station: str
    yes_if_tmax_at_least_f: int
    trade_quantity: Decimal
    edge_threshold: Decimal
    probability_when_yes: Decimal = Decimal("0.70")
    probability_when_no: Decimal = Decimal("0.20")
    require_final: bool = True


class ForecastHighEdgeBuyer(Strategy):
    """Buy one fixed YES clip when weather implies enough ask-side edge."""

    def __init__(self, config: ForecastHighEdgeBuyerConfig) -> None:
        super().__init__(config)
        self.quotes: int = 0
        self.depths: int = 0
        self.weather: int = 0
        self.weather_stations: tuple[str, ...] = ()
        self.orders_submitted: int = 0
        self.own_fills: int = 0
        self.maker_fills: int = 0
        self.traded_tmax_f: int | None = None
        self.last_model_probability: Decimal | None = None
        self.last_edge: Decimal | None = None
        self.decisions: list[str] = []

        self._quantity: Quantity | None = None
        self._last_ask: Price | None = None
        self._own_order_ids: set[ClientOrderId] = set()
        self._validate_config()

    # -- lifecycle ---------------------------------------------------------

    def on_start(self) -> None:
        instrument = self.cache.instrument(self.config.instrument_id)
        if instrument is None:
            self.log.error(
                f"no instrument {self.config.instrument_id} in the cache; stopping",
            )
            self.stop()
            return

        self._quantity = instrument.make_qty(self.config.trade_quantity)
        self.subscribe_quote_ticks(instrument.id)
        self.subscribe_order_book_depth(instrument.id)
        self.subscribe_instrument_close(instrument.id)
        self.subscribe_data(nws_climate_day_data_type(), client_id=NWS_BACKTEST_CLIENT_ID)
        self._record(0, "started", str(instrument.id))

    # -- data --------------------------------------------------------------

    def on_quote_tick(self, tick: QuoteTick) -> None:
        self.quotes += 1
        self._last_ask = tick.ask_price
        self._record(tick.ts_event, "quote", f"ask={tick.ask_price}")

    def on_order_book_depth(self, depth: OrderBookDepth10) -> None:
        self.depths += 1
        best_ask = self._best_ask(depth.asks)
        if best_ask is not None:
            self._last_ask = best_ask
        self._record(depth.ts_event, "depth", f"seq={depth.sequence}:ask={self._last_ask}")

    def on_data(self, data: Data) -> None:
        if type(data) is not NwsClimateDay:
            return

        self.weather += 1
        self.weather_stations = (*self.weather_stations, data.station)
        self._record(
            data.ts_event,
            "weather",
            f"{data.station}:{data.climate_day.isoformat()}:tmax={data.tmax_f}"
            f":final={data.is_final}",
        )

        if self.orders_submitted:
            return
        if data.station != self.config.station:
            self._record(data.ts_event, "skip", f"foreign:{data.station}")
            return
        if self.config.require_final and not data.is_final:
            self._record(data.ts_event, "skip", "preliminary")
            return
        if data.tmax_f is None:
            self._record(data.ts_event, "skip", "missing-tmax")
            return
        if self._quantity is None or self._last_ask is None:
            self._record(data.ts_event, "skip", "no-ask")
            return

        probability = self._probability(data.tmax_f)
        edge = probability - self._last_ask.as_decimal()
        self.last_model_probability = probability
        self.last_edge = edge
        self._record(
            data.ts_event,
            "edge",
            f"p={probability}:ask={self._last_ask}:edge={edge}",
        )
        if edge < self.config.edge_threshold:
            return

        order = self.order_factory.market(
            instrument_id=self.config.instrument_id,
            order_side=OrderSide.BUY,
            quantity=self._quantity,
        )
        self.orders_submitted += 1
        self.traded_tmax_f = data.tmax_f
        self._own_order_ids.add(order.client_order_id)
        self._record(data.ts_event, "submit", f"BUY:{order.quantity}")
        self.submit_order(order)

    # -- events ------------------------------------------------------------

    def on_order_filled(self, event: OrderFilled) -> None:
        if event.liquidity_side == LiquiditySide.MAKER:
            self.maker_fills += 1
        if event.client_order_id in self._own_order_ids:
            self.own_fills += 1
        self._record(
            event.ts_event,
            "filled",
            f"{event.venue_order_id}:{event.order_side}:{event.last_qty}"
            f"@{event.last_px}:{event.liquidity_side}:{event.commission}",
        )

    # -- internals ---------------------------------------------------------

    def _probability(self, tmax_f: int) -> Decimal:
        if tmax_f >= self.config.yes_if_tmax_at_least_f:
            return cast("Decimal", self.config.probability_when_yes)
        return cast("Decimal", self.config.probability_when_no)

    def _best_ask(self, asks: list[BookOrder]) -> Price | None:
        if not asks:
            return None
        best: Price = asks[0].price
        return best

    def _record(self, ts_event: int, kind: str, detail: str) -> None:
        self.decisions.append(f"{ts_event}|{kind}|{detail}")

    def _validate_config(self) -> None:
        for name in ("probability_when_yes", "probability_when_no"):
            value = getattr(self.config, name)
            if value < _ZERO or value > _ONE:
                raise ValueError(f"{name} must be between 0 and 1 inclusive, got {value}")
        if self.config.edge_threshold < _ZERO:
            raise ValueError(
                f"edge_threshold must be non-negative, got {self.config.edge_threshold}",
            )
        if self.config.trade_quantity <= _ZERO:
            raise ValueError(
                f"trade_quantity must be positive, got {self.config.trade_quantity}",
            )
