"""Shared harness for the ARM C2 strategy tests (NOT a test module: no ``test_`` prefix).

A real Nautilus ``Strategy`` registered on a ``TestClock`` / cache / message bus, with the two
engine endpoints replaced by command recorders, so what the strategy sends (``SubmitOrder``,
``CancelOrder``, ``CancelAllOrders``, ``QueryOrder``) is observable and what the venue answers is
scripted by the test (``deliver``). No venue, no socket, no execution client.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Final

from nautilus_trader.common.component import TestClock
from nautilus_trader.core.fsm import InvalidStateTrigger
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import (
    CancelAllOrders,
    CancelOrder,
    QueryOrder,
    SubmitOrder,
)
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import BookOrder, OrderBookDepth10
from nautilus_trader.model.enums import AssetClass, LiquiditySide, OrderSide, OrderStatus
from nautilus_trader.model.events import OrderCancelRejected, OrderDenied
from nautilus_trader.model.identifiers import AccountId, InstrumentId, TraderId, VenueOrderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs
from nautilus_trader.test_kit.stubs.events import TestEventStubs

from breezy.adapters.polymarket_us.symbology import (
    base_slug_of,
    no_leg_instrument_id,
    sibling_instrument_id,
    slug_to_instrument_id,
)
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.domain.weather_bucket_facts import (
    CLIMATE_DAY_KEY,
    MEASURE_KEY,
    SETTLEMENT_STATION_KEY,
    STRIKE_LOWER_F_KEY,
    STRIKE_UPPER_F_KEY,
    WEATHER_FACTS_STATUS_KEY,
    WEATHER_FACTS_STATUS_KNOWN,
)
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import LiveCalibration
from breezy.strategy.ladder_ev.location_correction import CorrectionForm
from breezy.strategy.ladder_ev.quantile_density import CdfMethod, EmosParams
from breezy.strategy.no_ladder_maker.config import STALE_BOOK_S, NoLadderMakerConfig
from breezy.strategy.no_ladder_maker.ladder_state import Ladder
from breezy.strategy.no_ladder_maker.params import SHARP_V1, MakerRuleParams
from breezy.strategy.no_ladder_maker.records import CENTS, Decision, DecisionContext, Desired
from breezy.strategy.no_ladder_maker.strategy import NoLadderMakerStrategy

NS: Final[int] = 10**9
HOUR_NS: Final[int] = 3_600 * NS
TRADER: Final[TraderId] = TraderId("BACKTEST-001")
ACCOUNT: Final[AccountId] = AccountId("POLYMARKET_US-001")
#: 2026-09-17T17:00:00Z = 09:00 PST on D-1 for D = 2026-09-18 (a LAX/SFO ladder day).
NOW_NS: Final[int] = int(dt.datetime(2026, 9, 17, 17, 0, tzinfo=dt.UTC).timestamp()) * NS
DAY: Final[dt.date] = dt.date(2026, 9, 18)
#: A ladder of six HIGH rungs; the slug grammar is the venue's (``tc-temp-<city>high-...``).
BANDS: Final[tuple[str, ...]] = (
    "lt66f",
    "gte66lt67f",
    "gte68lt69f",
    "gte70lt71f",
    "gte72lt73f",
    "gte74f",
)


def slug(station: str, band: str, day: dt.date = DAY) -> str:
    return f"tc-temp-{station.lower()}high-{day.isoformat()}-{band}"


def yes_id(station: str, band: str, day: dt.date = DAY) -> InstrumentId:
    return slug_to_instrument_id(slug(station, band, day))


def no_id(station: str, band: str, day: dt.date = DAY) -> InstrumentId:
    return no_leg_instrument_id(slug(station, band, day))


def _facts_info(instrument_id: InstrumentId) -> dict[str, object]:
    """What the adapter writes into a weather instrument's ``info`` (from the same slug grammar)."""
    facts = bucket_facts_from_instrument_id(str(instrument_id))
    assert facts is not None, f"{instrument_id} is not a weather rung"
    return {
        WEATHER_FACTS_STATUS_KEY: WEATHER_FACTS_STATUS_KNOWN,
        SETTLEMENT_STATION_KEY: facts.settlement_station,
        CLIMATE_DAY_KEY: facts.climate_day.isoformat(),
        MEASURE_KEY: facts.measure.value,
        STRIKE_LOWER_F_KEY: facts.lower_f,
        STRIKE_UPPER_F_KEY: facts.upper_f,
    }


def _instrument(instrument_id: InstrumentId, outcome: str) -> BinaryOption:
    increment = Price.from_str("0.01")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=instrument_id,
        raw_symbol=instrument_id.symbol,
        outcome=outcome,
        description="test weather market",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=increment.precision,
        price_increment=increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=4_000_000_000_000_000_000,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal("0.0695"),
        taker_fee=Decimal("0.0695"),
        ts_event=0,
        ts_init=0,
        info=_facts_info(slug_to_instrument_id(base_slug_of(instrument_id))),
    )


def identity_calibration() -> LiveCalibration:
    identity = EmosParams(a=0.0, gamma=0.0, delta=1.0)
    return LiveCalibration(
        sha256="a" * 64,
        cdf_method=CdfMethod.NORMAL,
        correction_form=CorrectionForm.NONE,
        linear_coefficients=None,
        month_offsets={},
        point_by_version={"": identity},
        draws_by_version={"": (identity,)},
    )


@dataclass(frozen=True, slots=True)
class FakePermit:
    expires_at_ns: int


def depth(
    instrument_id: InstrumentId,
    *,
    ts_ns: int,
    bids: Sequence[tuple[str, int]] = (),
    asks: Sequence[tuple[str, int]] = (),
    levels: int = 10,
) -> OrderBookDepth10:
    def side(order_side: OrderSide, book: Sequence[tuple[str, int]]) -> list[BookOrder]:
        pad = BookOrder(order_side, Price(0, 2), Quantity(0, 0), 0)
        orders = [BookOrder(order_side, Price.from_str(p), Quantity(s, 0), 0) for p, s in book]
        return [*orders, *([pad] * (levels - len(orders)))]

    bid_orders, ask_orders = side(OrderSide.BUY, bids), side(OrderSide.SELL, asks)
    return OrderBookDepth10(
        instrument_id=instrument_id,
        bids=bid_orders,
        asks=ask_orders,
        bid_counts=[1 if o.size.as_double() > 0 else 0 for o in bid_orders],
        ask_counts=[1 if o.size.as_double() > 0 else 0 for o in ask_orders],
        flags=0,
        sequence=0,
        ts_event=ts_ns,
        ts_init=ts_ns,
    )


def scripted_selector(
    calls: list[DecisionContext], script: Callable[[DecisionContext], Decision]
) -> Callable[[DecisionContext], Decision]:
    def selector(ctx: DecisionContext, /) -> Decision:
        calls.append(ctx)
        return script(ctx)

    return selector


def want(*pairs: tuple[str, int]) -> Decision:
    """A valid forecast with these (rung_id, bid_cents) wanted, in rank order."""
    return Decision(desired=tuple(Desired(r, c) for r, c in pairs), forecast_valid=True)


class Harness:
    """One registered strategy plus its recorded commands."""

    def __init__(
        self,
        *,
        stations: Sequence[str] = ("SFO",),
        shadow_only: bool = False,
        permit_expires_at_ns: int | None = NOW_NS + 10 * HOUR_NS,
        veto: Callable[[], str | None] | None = None,
        fee_verified: Callable[[int], bool] | None = None,
        params: MakerRuleParams = SHARP_V1,
        bands: Sequence[str] = BANDS,
        max_depth_subscriptions: int = 40,
        with_no_legs: bool = True,
        day: dt.date = DAY,
        start: bool = True,
        now_ns: int = NOW_NS,
        instrument_ids: Sequence[InstrumentId] | None = None,
        calibration: LiveCalibration | None = None,
        theta: float = 0.0695,
        stale_book_s: int = STALE_BOOK_S,
    ) -> None:
        self.clock = TestClock()
        self.clock.set_time(now_ns)
        self.msgbus = TestComponentStubs.msgbus()
        self.cache = TestComponentStubs.cache()
        self.inbox: list[Any] = []
        self.msgbus.register(endpoint="RiskEngine.execute", handler=self.inbox.append)
        self.msgbus.register(endpoint="ExecEngine.execute", handler=self.inbox.append)
        self.after_handler: Callable[[], None] | None = None
        self.day = day
        yes_ids = (
            list(instrument_ids)
            if instrument_ids is not None
            else [yes_id(station, band, day) for station in stations for band in bands]
        )
        for yes in yes_ids:
            self.cache.add_instrument(_instrument(yes, "Yes"))
            if with_no_legs:
                self.cache.add_instrument(_instrument(sibling_instrument_id(yes), "No"))
        self.permit = None if permit_expires_at_ns is None else FakePermit(permit_expires_at_ns)
        self.strategy = NoLadderMakerStrategy(
            NoLadderMakerConfig(
                stations=tuple(stations),
                shadow_only=shadow_only,
                order_id_tag="T",
                strategy_id="NoLadderMaker-T",
            ),
            calibration=calibration if calibration is not None else identity_calibration(),
            theta=theta,
            params=params,
            order_submission_permit=self.permit,
            submit_veto=veto,
            fee_verified=fee_verified,
            max_depth_subscriptions=max_depth_subscriptions,
            stale_book_s=stale_book_s,
        )
        portfolio = Portfolio(msgbus=self.msgbus, cache=self.cache, clock=self.clock)
        self.strategy.register(
            trader_id=TRADER,
            portfolio=portfolio,
            msgbus=self.msgbus,
            cache=self.cache,
            clock=self.clock,
        )
        #: every ``cancel_all_orders`` call the strategy makes (Nautilus sends the command only
        #: for an instrument whose cache shows an open or in-flight order)
        self.cancel_all_calls: list[InstrumentId] = []
        real_cancel_all = self.strategy.cancel_all_orders

        def spy(instrument_id: InstrumentId, *args: Any, **kwargs: Any) -> None:
            self.cancel_all_calls.append(instrument_id)
            real_cancel_all(instrument_id, *args, **kwargs)

        self.strategy.cancel_all_orders = spy
        if start:
            self.strategy.start()

    # -- time ---------------------------------------------------------------------------------

    def advance_to(self, ts_ns: int) -> None:
        """Move the clock to ``ts_ns``, running each due timer AT its own instant.

        ``TestClock.advance_time`` would run every due handler with the clock already at the
        target; stepping the clock to each handler's scheduled instant keeps "now" truthful inside
        a callback (a GTD expiry at midnight must re-decide at midnight, not at the next event).
        ``after_handler`` lets a venue double answer between handlers.
        """
        if ts_ns <= self.clock.timestamp_ns():
            return  # the clock only moves forward; an event at "now" needs no advance
        for handler in self.clock.advance_time(ts_ns, set_time=False):
            due = handler.event.ts_event
            if due > self.clock.timestamp_ns():
                self.clock.set_time(due)
            handler.handle()
            if self.after_handler is not None:
                self.after_handler()
        self.clock.set_time(ts_ns)

    def advance(self, seconds: float) -> None:
        self.advance_to(self.clock.timestamp_ns() + int(seconds * NS))

    # -- state --------------------------------------------------------------------------------

    @property
    def ladder(self) -> Ladder:
        (ladder,) = [lad for lad in self.strategy.ladders.values()]
        return ladder

    def rung(self, band: str, station: str = "SFO") -> str:
        return str(yes_id(station, band, self.day))

    def install(self, script: Callable[[DecisionContext], Decision]) -> list[DecisionContext]:
        """Replace the ported selector with a scripted one (the mechanics are under test here)."""
        calls: list[DecisionContext] = []
        scripted = scripted_selector(calls, script)
        self.strategy._selector_for = lambda ladder: scripted  # type: ignore[method-assign]
        return calls

    def book(
        self,
        band: str,
        *,
        ts_ns: int | None = None,
        station: str = "SFO",
        bids: Sequence[tuple[str, int]] = (("0.05", 10),),
        asks: Sequence[tuple[str, int]] = (("0.40", 10),),
    ) -> None:
        """A YES-book frame for ``band`` (YES asks at a cents are NO bids at 100 - a)."""
        ts = self.clock.timestamp_ns() if ts_ns is None else ts_ns
        self.strategy.on_order_book_depth(
            depth(yes_id(station, band, self.day), ts_ns=ts, bids=bids, asks=asks)
        )

    # -- commands -----------------------------------------------------------------------------

    def drain(self) -> list[Any]:
        out, self.inbox[:] = list(self.inbox), []
        return out

    def submits(self, commands: Sequence[Any]) -> list[SubmitOrder]:
        return [c for c in commands if isinstance(c, SubmitOrder)]

    def cancels(self, commands: Sequence[Any]) -> list[CancelOrder]:
        return [c for c in commands if isinstance(c, CancelOrder)]

    def cancel_alls(self, commands: Sequence[Any]) -> list[CancelAllOrders]:
        return [c for c in commands if isinstance(c, CancelAllOrders)]

    def queries(self, commands: Sequence[Any]) -> list[QueryOrder]:
        return [c for c in commands if isinstance(c, QueryOrder)]

    # -- venue answers ------------------------------------------------------------------------

    def deliver(self, event: Any, *, engine_tolerant: bool = False) -> None:
        """Apply ``event`` to the cached order and publish it to the strategy.

        ``engine_tolerant`` mirrors ``ExecutionEngine._apply_event_to_order``: an event the order
        FSM refuses (``InvalidStateTrigger``) is logged, NOT applied, and still published.
        """
        order = self.cache.order(event.client_order_id)
        if order is not None:
            try:
                order.apply(event)
            except InvalidStateTrigger:
                if not engine_tolerant:
                    raise
            self.cache.update_order(order)  # keeps the open / in-flight indices true
        self.msgbus.publish(topic=f"events.order.{self.strategy.id}", msg=event)

    def mark_submitted(self, command: SubmitOrder) -> None:
        """The engine's ``OrderSubmitted``: the order is now IN FLIGHT (no venue id yet)."""
        order = self.cache.order(command.order.client_order_id)
        assert order is not None
        if order.status is OrderStatus.INITIALIZED:
            self.deliver(TestEventStubs.order_submitted(order, ts_event=self.clock.timestamp_ns()))

    def accept(self, command: SubmitOrder) -> None:
        self.mark_submitted(command)
        self.deliver(
            TestEventStubs.order_accepted(
                command.order,
                venue_order_id=VenueOrderId(f"V-{command.order.client_order_id}"),
                ts_event=self.clock.timestamp_ns(),
            )
        )

    def cancel_ack(self, order: Any) -> None:
        self.deliver(TestEventStubs.order_canceled(order, ts_event=self.clock.timestamp_ns()))

    def cancel_reject(self, order: Any, reason: str = "venue refused the cancel") -> None:
        """``OrderCancelRejected``: the order returns to its pre-cancel status (Nautilus FSM)."""
        self.deliver(
            OrderCancelRejected(
                trader_id=TRADER,
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                venue_order_id=order.venue_order_id,
                account_id=ACCOUNT,
                reason=reason,
                event_id=UUID4(),
                ts_event=self.clock.timestamp_ns(),
                ts_init=self.clock.timestamp_ns(),
            ),
            engine_tolerant=True,  # PENDING_CANCEL -> SUBMITTED is not a legal FSM edge (1.231)
        )

    def expire(self, order: Any) -> None:
        self.deliver(TestEventStubs.order_expired(order, ts_event=self.clock.timestamp_ns()))

    def reject(self, order: Any) -> None:
        self.deliver(TestEventStubs.order_rejected(order, ts_event=self.clock.timestamp_ns()))

    def deny(self, order: Any) -> None:
        self.deliver(
            OrderDenied(
                trader_id=TRADER,
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                reason="test denial",
                event_id=UUID4(),
                ts_init=self.clock.timestamp_ns(),
            )
        )

    def fill(self, order: Any) -> None:
        instrument = self.cache.instrument(order.instrument_id)
        self.deliver(
            TestEventStubs.order_filled(
                order,
                instrument,
                account_id=ACCOUNT,
                liquidity_side=LiquiditySide.MAKER,
                ts_event=self.clock.timestamp_ns(),
            )
        )

    def post_and_accept(self) -> list[SubmitOrder]:
        """Drain the inbox, accept every submitted order, return the submits."""
        submits = self.submits(self.drain())
        for command in submits:
            self.accept(command)
        return submits


def cents_of(command: SubmitOrder) -> int:
    return round(float(command.order.price) * CENTS)


def empty_mapping() -> Mapping[str, object]:
    return MappingProxyType({})


class FakeVenue:
    """The venue as the execution client presents it to the strategy, in a few lines.

    Open orders by venue id; a ``CancelAllOrders`` cancels every open order of that instrument's
    slug; a ``CancelOrder`` of an order past its ``expire_time`` answers ``OrderExpired`` (the
    managed GTD timer's cancel), otherwise ``OrderCanceled``; ``unfiltered_open_orders`` is the
    slug list of everything resting (the unfiltered ``GET /v1/orders/open``). ``posts`` records
    every submit.
    """

    def __init__(self, harness: Harness) -> None:
        self.h = harness
        harness.after_handler = self.pump  # answer between timer callbacks, as a live venue does
        self.open: dict[str, tuple[str, Any]] = {}
        self.cancel_all_seen: list[str] = []
        self.posts: list[tuple[int, str, int, int]] = []  # (t0, NO instrument, cents, expire_ns)

    def pump(self) -> None:
        while self.h.inbox:
            self._apply(self.h.drain())

    def _apply(self, commands: Sequence[Any]) -> None:
        now = self.h.clock.timestamp_ns()
        for command in commands:
            if isinstance(command, SubmitOrder):
                order = command.order
                self.open[f"V-{order.client_order_id}"] = (base_slug_of(order.instrument_id), order)
                self.posts.append(
                    (now, str(order.instrument_id), cents_of(command), order.expire_time_ns)
                )
                self.h.accept(command)
            elif isinstance(command, CancelAllOrders):
                self.cancel_all_seen.append(str(command.instrument_id))
                slug = base_slug_of(command.instrument_id)
                for venue_id, (open_slug, order) in list(self.open.items()):
                    if open_slug == slug:
                        del self.open[venue_id]
                        self.h.cancel_ack(order)
            elif isinstance(command, CancelOrder):
                for venue_id, (_slug, order) in list(self.open.items()):
                    if order.client_order_id == command.client_order_id:
                        del self.open[venue_id]
                        if 0 < order.expire_time_ns <= now:
                            self.h.expire(order)
                        else:
                            self.h.cancel_ack(order)

    def fill_open(self, no_instrument: InstrumentId) -> bool:
        """The venue fills the resting order on ``no_instrument`` (if any)."""
        for venue_id, (_slug, order) in list(self.open.items()):
            if order.instrument_id == no_instrument:
                del self.open[venue_id]
                self.h.fill(order)
                return True
        return False

    def unfiltered_open_orders(self) -> list[str]:
        return sorted(slug for slug, _ in self.open.values())
