"""`BreezyStrikeLadder` -- a weather-conditioned, MULTI-INSTRUMENT strategy.

Written as an acceptance exercise for the backtest harness. Unlike
``breezy.strategy.harness_probe`` -- one instrument, one MARKET BUY, no
decision -- this strategy holds positions on SEVERAL strikes of the same city
at once, and every one of those positions is chosen from an observed
temperature rather than from the book.

The trade
---------

The captured Polymarket.us universe is a ladder of mutually exclusive
temperature buckets on one city and one day: ``...-gte70lt71f``,
``...-gte72lt73f``, ``...-gte74f``, ``...-lt66f``. Exactly one settles at 1.

Given an observed high ``tmax_f`` for the configured station:

* the bucket **containing** ``tmax_f`` is bought at the full clip -- that is
  the position the weather implies. Buckets are CLOSED intervals: the venue
  titles ``...-gte72lt73f`` "72 to 73", so 73 is inside it. Reading ``lt`` as
  strict is wrong for 455 of the 680 captured markets and orphans every odd
  degree -- see ``breezy.adapters.polymarket_us.symbology``;
* every bucket **within** :attr:`~BreezyStrikeLadderConfig.tolerance_f` of
  ``tmax_f`` is bought at the reduced clip, because the observation this
  strategy trades on may still be revised. A CLI product is corrected often
  enough that a one-degree neighbourhood is a modelled hedge and not a
  decoration -- see ``breezy.domain.nws_climate_day`` on revisions.

So a run holds at least two positions, on purpose, and at settlement at most
one of them is a winner. That asymmetry is the point: it is what makes a
multi-instrument settlement check able to fail.

Three constraints inherited from the venue spec, restated because each one is
silent when broken
------------------------------------------------------------------------------

**Weather is subscribed by ``client_id``, never by ``instrument_id``.** This
matters far more here than in the single-instrument probe, because the
tempting thing to write when a strategy holds N instruments is N
instrument-scoped weather subscriptions. ``Actor.subscribe_data(instrument_id=
...)`` builds the pattern ``data.NwsClimateDay.<venue>.<symbol>`` while
``DataType(NwsClimateDay).topic`` is ``NwsClimateDay*``; ``is_matching_py``
returns False for that pair. All N subscriptions would receive ZERO records,
with no error and no log. One climate day settles the whole ladder, so ONE
client-scoped subscription is also the semantically correct shape.

**Every order is a MARKET BUY.** MARKET so the fill is unambiguously TAKER:
``PolymarketUSFeeModel`` prices a maker fill at the taker coefficient, which
is wrong in SIGN. BUY because ``docs/specs/BACKTEST_VENUE_CONFIG.md`` §2 shows
a naked SELL passing every ``RiskEngine`` check on a CASH account and RAISING
free cash -- and a ladder strategy is exactly where "sell the buckets that
cannot win" is the obvious next idea.

**The decision fires once, on the first qualifying record.** ``on_data`` is
re-entered for every revision, and a ladder that re-bought on each one would
compound silently.

Null hypothesis: ``nautilus_trader.trading.strategy.Strategy`` is the native
extension point, and is subclassed directly. No Breezy base class, no
lifecycle wrapper, no per-instrument sub-actor -- one ``Strategy`` holding a
mapping is what the framework already supports.
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
    from nautilus_trader.model.data import InstrumentClose, OrderBookDepth10, QuoteTick
    from nautilus_trader.model.events import OrderFilled
    from nautilus_trader.model.identifiers import ClientOrderId, InstrumentId
    from nautilus_trader.model.objects import Quantity

__all__ = ["BreezyStrikeLadder", "BreezyStrikeLadderConfig"]

#: Sentinel for an open-ended bucket bound (``...-gte74f`` has no upper edge,
#: ``...-lt66f`` no lower one). A large finite integer rather than
#: ``float('inf')`` so the config stays msgspec-encodable as plain ints.
OPEN_BOUND_F: int = 10_000


class BreezyStrikeLadderConfig(StrategyConfig, frozen=True):
    """Configuration for :class:`BreezyStrikeLadder`.

    Parameters
    ----------
    station : str
        The NWS station id whose ``NwsClimateDay`` records drive the decision
        (e.g. ``"NYC"``). Records for any other station are ignored: the
        weather subscription is client-scoped, so a run covering two cities
        delivers BOTH cities' records to BOTH ladders.
    buckets : tuple[tuple[InstrumentId, int, int], ...]
        One entry per strike: ``(instrument_id, lower_f, upper_f)``. The
        interval is **CLOSED at BOTH ends** -- ``lower_f <= tmax_f <=
        upper_f`` -- because that is what the venue's own prose says, and the
        venue's prose is the source of truth for the comparator, not the slug.
        ``breezy.adapters.polymarket_us.symbology`` records the evidence: a
        slug segment ``gte72lt73f`` is titled "72 to 73", so 73 is INSIDE the
        bucket, and across the 114 captured city/day ladders only the closed
        reading tiles the degree line without a gap (114 of 114, versus 0 of
        114 for the naive half-open reading of ``lt``). A half-open bucket
        here orphans every odd degree: the ladder simply fails to buy the
        winning strike, buys its hedges instead, and loses money with no
        error anywhere. Use :data:`OPEN_BOUND_F` / ``-OPEN_BOUND_F`` for an
        open edge.
    trade_quantity : Decimal
        Clip for the bucket that CONTAINS the observation, in contracts.
    hedge_quantity : Decimal
        Clip for each bucket within ``tolerance_f`` of the observation.
    tolerance_f : int
        Degrees F of revision risk hedged either side of the observation.
        ``0`` disables the hedge legs entirely.
    require_final : bool
        When True (default) only ``is_final`` climate days trade. A
        preliminary can be superseded; see ``breezy.domain.nws_climate_day``.

    """

    station: str
    buckets: tuple[tuple[InstrumentId, int, int], ...]
    trade_quantity: Decimal
    hedge_quantity: Decimal
    tolerance_f: int = 1
    require_final: bool = True


class BreezyStrikeLadder(Strategy):
    """Buys several temperature buckets at once, from one observation."""

    def __init__(self, config: BreezyStrikeLadderConfig) -> None:
        super().__init__(config)
        #: Per-instrument arrival counts. Keyed by `InstrumentId` rather than
        #: summed, because the failure this strategy exists to expose is ONE
        #: instrument going quiet while the others look healthy -- a scalar
        #: counter cannot show that.
        self.quotes: dict[InstrumentId, int] = {}
        self.depths: dict[InstrumentId, int] = {}
        self.closes: dict[InstrumentId, int] = {}
        self.own_fills: dict[InstrumentId, int] = {}
        self.submitted: dict[InstrumentId, Quantity] = {}
        self.weather: int = 0
        self.weather_stations: tuple[str, ...] = ()
        self.maker_fills: int = 0
        #: Ordered, engine-timestamped decision log. No wall clock, no uuid.
        self.decisions: list[str] = []
        #: The observation the ladder actually traded on, once it has.
        self.traded_tmax_f: int | None = None
        self._own_order_ids: set[ClientOrderId] = set()
        self._quantities: dict[InstrumentId, tuple[Quantity, Quantity]] = {}
        self._fired: bool = False

    # -- lifecycle ---------------------------------------------------------

    def on_start(self) -> None:
        """Resolve every bucket's instrument, then subscribe all streams.

        A missing instrument STOPS the strategy rather than skipping the leg:
        a ladder silently trading three of its four buckets is precisely the
        quiet wrong answer this module is meant not to produce.
        """
        for instrument_id, _lower, _upper in self.config.buckets:
            instrument = self.cache.instrument(instrument_id)
            if instrument is None:
                self.log.error(
                    f"no instrument {instrument_id} in the cache; stopping the whole ladder. "
                    f"Add it with `BacktestEngine.add_instrument` before the data.",
                )
                self.stop()
                return
            self._quantities[instrument_id] = (
                instrument.make_qty(self.config.trade_quantity),
                instrument.make_qty(self.config.hedge_quantity),
            )
            self.quotes[instrument_id] = 0
            self.depths[instrument_id] = 0
            self.closes[instrument_id] = 0
            self.own_fills[instrument_id] = 0
            self.subscribe_quote_ticks(instrument_id)
            self.subscribe_order_book_depth(instrument_id)
            self.subscribe_instrument_close(instrument_id)

        # ONCE, by `client_id`. Never per instrument -- see module docstring.
        self.subscribe_data(nws_climate_day_data_type(), client_id=NWS_BACKTEST_CLIENT_ID)
        self._record(0, "started", f"{len(self.config.buckets)} buckets")

    # -- data --------------------------------------------------------------

    def on_data(self, data: Data) -> None:
        """Trade the ladder from the first qualifying observation.

        The type guard is type-EXACT: ``is_matching_py`` treats
        ``NwsClimateDayExtra*`` as matching ``NwsClimateDay*``, so a class
        whose name merely starts with this one's would leak in.
        """
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

        if self._fired or data.station != self.config.station:
            return
        if self.config.require_final and not data.is_final:
            return
        if data.tmax_f is None:
            self._record(data.ts_event, "skip", "no tmax_f")
            return

        self._fired = True
        self.traded_tmax_f = data.tmax_f
        self._trade_ladder(observed_f=data.tmax_f, ts_event=data.ts_event)

    def on_quote_tick(self, tick: QuoteTick) -> None:
        self.quotes[tick.instrument_id] = self.quotes.get(tick.instrument_id, 0) + 1

    def on_order_book_depth(self, depth: OrderBookDepth10) -> None:
        self.depths[depth.instrument_id] = self.depths.get(depth.instrument_id, 0) + 1

    def on_instrument_close(self, update: InstrumentClose) -> None:
        self.closes[update.instrument_id] = self.closes.get(update.instrument_id, 0) + 1
        self._record(
            update.ts_event,
            "close",
            f"{update.instrument_id}:{update.close_type}@{update.close_price}",
        )

    # -- events ------------------------------------------------------------

    def on_order_filled(self, event: OrderFilled) -> None:
        """Count the ladder's OWN fills, per instrument.

        The engine's settlement leg is a ``reduce_only`` MARKET order it
        issues itself against each position (``backtest/engine.pyx:5947``);
        it routes back here and must not be counted as a decision.
        """
        if event.liquidity_side == LiquiditySide.MAKER:
            self.maker_fills += 1
        if event.client_order_id in self._own_order_ids:
            self.own_fills[event.instrument_id] = self.own_fills.get(event.instrument_id, 0) + 1
        self._record(
            event.ts_event,
            "filled",
            f"{event.instrument_id}:{event.venue_order_id}:{event.order_side}"
            f":{event.last_qty}@{event.last_px}:{event.liquidity_side}:{event.commission}",
        )

    # -- internals ---------------------------------------------------------

    def _trade_ladder(self, *, observed_f: int, ts_event: int) -> None:
        """One MARKET BUY per qualifying bucket, largest clip first."""
        for instrument_id, lower, upper in self.config.buckets:
            full, hedge = self._quantities[instrument_id]
            # CLOSED interval on BOTH sides -- see `BreezyStrikeLadderConfig`.
            if lower <= observed_f <= upper:
                quantity, reason = full, "contains"
            elif self._within_tolerance(observed_f, lower, upper):
                quantity, reason = hedge, "hedge"
            else:
                self._record(ts_event, "no-trade", f"{instrument_id}:[{lower},{upper})")
                continue
            if quantity == 0:
                self._record(ts_event, "no-trade", f"{instrument_id}:zero-clip")
                continue
            order = self.order_factory.market(
                instrument_id=instrument_id,
                # BUY only. Spec §2: a naked SELL on a CASH account passes
                # every RiskEngine check and raises free cash.
                order_side=OrderSide.BUY,
                quantity=quantity,
            )
            self._own_order_ids.add(order.client_order_id)
            self.submitted[instrument_id] = quantity
            self._record(ts_event, "submit", f"{instrument_id}:{reason}:BUY:{quantity}")
            self.submit_order(order)

    def _within_tolerance(self, observed_f: int, lower: int, upper: int) -> bool:
        """Is this bucket reachable if the observation is revised?

        Distance from the observation to the CLOSED bucket interval, not to
        either edge: a bucket the observation already sits in is handled
        above, and one that merely touches must be measured from its near
        edge.
        """
        tolerance = self.config.tolerance_f
        if tolerance <= 0:
            return False
        if observed_f < lower:
            return bool(lower - observed_f <= tolerance)
        return bool(observed_f - upper <= tolerance)

    def _record(self, ts_event: int, kind: str, detail: str) -> None:
        self.decisions.append(f"{ts_event}|{kind}|{detail}")
