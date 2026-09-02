"""In-flight order visibility at the four REMAINING weather-strategy boundaries.

T-1 stage 2 (``docs/plans/T1_STRATEGY_INFLIGHT_BLINDNESS_2026-09-02.md``).
``tests/unit/test_forecast_mispricing_inflight_orders.py`` pins the same three
uses of ``cache.orders_open(...)`` for ``forecast_mispricing``, the template
strategy landed in stage 1. The gate is FIVE COPIES of one mistake, and a test
on one copy proves nothing about the other four, so the remaining four are
pinned here against REAL strategies registered onto a real ``Cache`` /
``MessageBus`` / ``OrderFactory``, with the commands they emit captured off
the engine endpoints:

* **class A** -- the re-submission gate in ``_maybe_submit``. ``is_open_c``
  (``model/orders/base.pyx``) excludes ``INITIALIZED``/``SUBMITTED``, so inside
  the submit -> ACCEPTED window the gate saw nothing working and let a
  duplicate order through. Present in all four.
* **class B** -- the ``if orders_open: cancel_all_orders(...)`` pre-filter in
  ``_flatten``. Present in ``calibration_mean_reversion`` and
  ``forecast_revision`` only; ``running_extreme_lock`` and
  ``cli_settlement_print_lock`` have no ``_flatten`` (neither has an exit
  signal beyond the settlement halt).
* **class C** -- the ``pending_qty`` feed into ``PortfolioSnapshot``, and with
  it ``net_qty`` and the operator-reserved ``max_position_contracts`` -- the
  only cumulative position cap in the system, Nautilus's ``RiskEngine``
  carrying none.

Everything is parametrized over the strategies rather than copied per file,
because the DEFECT is a copy: a test written once and run against each real
``_maybe_submit`` / ``_flatten`` / ``_portfolio_snapshot`` body is the shape
that would have caught it. What differs per strategy -- constructor
dependencies, ``_maybe_submit`` arity, whether a settlement deadline or a
cost-basis anchor is consulted -- lives in a small rig subclass and nowhere
else.

The portfolio is a ``PortfolioFacade`` double so a settled position can be
stated directly; everything else -- orders, cache indexes, order status
transitions, the emitted commands -- is real Nautilus.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import MessageBus, TestClock
from nautilus_trader.config import CacheConfig
from nautilus_trader.execution.messages import CancelAllOrders, SubmitOrder
from nautilus_trader.model.enums import OmsType, OrderSide, OrderStatus
from nautilus_trader.model.identifiers import PositionId, TraderId
from nautilus_trader.model.position import Position
from nautilus_trader.portfolio.base import PortfolioFacade
from nautilus_trader.test_kit.stubs.events import TestEventStubs

from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.strategy.calibration_mean_reversion.config import CalibrationMeanReversionConfig
from breezy.strategy.calibration_mean_reversion.strategy import CalibrationMeanReversionStrategy
from breezy.strategy.cli_settlement_print_lock.config import CliSettlementPrintLockConfig
from breezy.strategy.cli_settlement_print_lock.decision import CliPrintObservation
from breezy.strategy.cli_settlement_print_lock.strategy import CliSettlementPrintLockStrategy
from breezy.strategy.forecast_revision.config import ForecastRevisionConfig
from breezy.strategy.forecast_revision.strategy import ForecastRevisionStrategy
from breezy.strategy.running_extreme_lock.config import RunningExtremeLockConfig
from breezy.strategy.running_extreme_lock.decision import RunningExtremeObservation
from breezy.strategy.running_extreme_lock.strategy import RunningExtremeLockStrategy
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.freshness import SignalFreshness
from breezy.strategy.weather_common.models import (
    ForecastSnapshot,
    MarketQuote,
    SideIntent,
    SignalDecision,
)
from breezy.strategy.weather_common.risk import PortfolioSnapshot, RiskLimits, RiskManager
from tests.unit.conftest import iter_captured_market_payloads

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.model.instruments import BinaryOption
    from nautilus_trader.model.orders.base import Order
    from nautilus_trader.trading.strategy import Strategy

TRADER_ID = TraderId("BREEZY-INFLIGHT-003")
NOW = dt.datetime(2026, 4, 22, 12, 0, tzinfo=dt.UTC)
CLIMATE_DAY = dt.date(2026, 4, 23)
#: Comfortably outside `min_hours_to_settlement` / `halt_hours_before_settlement`
#: for the two strategies whose risk call reads a deadline.
DEADLINE = NOW + dt.timedelta(hours=24)

#: Test-local stand-in for the operator's cumulative position ceiling. Stated
#: here as a FIXTURE ARGUMENT -- no default anywhere in the shipped configs or
#: `RiskLimits` is changed by this module.
MAX_POSITION_CONTRACTS = 250.0

#: Test-local observation-freshness bound. The two observation-kind strategies
#: refuse EVERY order when this is unset (`observation_limit_unset`), which
#: would make the class A control test pass for the wrong reason.
STALE_OBSERVATION_HOURS = 12.0

#: The sizing sequence from the plan's §0: two cycles of +200 against a 250
#: cap, the second one fired while the first is still in flight.
ORDER_QTY = 200.0

#: Large enough that `cli_settlement_print_lock`'s cost-basis clip is not the
#: binding constraint on `ORDER_QTY` -- this module measures the in-flight
#: gate, not the anchor (which has its own tests).
COST_BASIS_ANCHOR = 1_000.0
FEE_PROB = 0.0126


def _instrument() -> BinaryOption:
    payloads = iter_captured_market_payloads()
    assert payloads, "no captured Polymarket.us market payloads on disk"
    return parse_binary_option(payloads[0], ts_init=0)


class _StubForecastSource:
    """Never consulted: every test here calls the decision-side methods directly."""

    def snapshot(
        self,
        *,
        station: str,
        climate_day: dt.date,
        now: dt.datetime,
    ) -> ForecastSnapshot | None:
        del station, climate_day, now
        return None


class _StubFeeCoefficients:
    """`cli_settlement_print_lock` refuses to construct without one."""

    def fee_coefficient_for(self, instrument_id: str) -> float:
        del instrument_id
        return 0.06


#: A STATED account balance for the stub venue account below.
#:
#: This portfolio double used to return ``account -> None`` so ``_equity()``
#: would fall back to ``config.starting_equity`` -- a fabricated constant
#: that T-4 deleted, because an unobserved balance now refuses a new BUY
#: (``equity_unobserved``) instead of inventing a denominator. These tests
#: measure the IN-FLIGHT gate, so they state an observation rather than lean
#: on the absence of one. At ``max_equity_fraction=0.08`` this authorises 800
#: contracts against an ``ORDER_QTY`` of 200: the equity clip stays exactly as
#: far out of the way as it was before, so what these tests measure is
#: unchanged.
OBSERVED_EQUITY = 10_000.0


class _StubBalance:
    """`Account.balance_total` returns `Money | None`; only `as_double` is read."""

    def __init__(self, amount: float) -> None:
        self._amount = amount

    def as_double(self) -> float:
        return self._amount


class _StubAccount:
    def __init__(self, balance: float) -> None:
        self._balance = balance

    def balance_total(self, currency: Any) -> _StubBalance:
        del currency
        return _StubBalance(self._balance)


class _SettledPositionPortfolio(PortfolioFacade):  # type: ignore[misc]  # compiled Cython base erases to Any
    """States the SETTLED position only -- the quantity in-flight orders are missing from.

    ``account`` reports :data:`OBSERVED_EQUITY`, which keeps the
    equity-fraction clip out of the way of what these tests measure without
    relying on an equity nobody observed.
    """

    def __init__(self, net: float) -> None:
        self._net = Decimal(str(net))

    def net_position(self, instrument_id: Any, account_id: Any = None) -> Decimal:
        del instrument_id, account_id
        return self._net

    def account(self, venue: Any) -> _StubAccount:
        del venue
        return _StubAccount(OBSERVED_EQUITY)


class _Rig:
    """One real strategy, one real cache, one real order factory.

    Subclasses supply only what differs: how the strategy is constructed, how
    its ``_maybe_submit`` is called, and whether it consults a settlement
    deadline.
    """

    name: str = "base"
    #: `running_extreme_lock` / `cli_settlement_print_lock` read
    #: `self._deadlines[...]` inside `_maybe_submit`; the forecast strategies
    #: take `hours_to_settlement` from the forecast horizon instead.
    needs_deadlines: bool = False
    #: Only `calibration_mean_reversion` and `forecast_revision` define
    #: `_flatten`, and therefore only they carry a class B site.
    has_flatten: bool = False

    def __init__(self, *, settled_qty: float = 0.0) -> None:
        self.instrument = _instrument()
        self.instrument_id = self.instrument.id
        self.local_id = str(self.instrument.id)
        clock = TestClock()
        msgbus = MessageBus(trader_id=TRADER_ID, clock=clock)
        self.cache = Cache(
            database=None,
            config=CacheConfig(database=None, flush_on_start=False),
        )
        self.cache.add_instrument(self.instrument)

        self.commands: list[Any] = []
        msgbus.register("RiskEngine.execute", self.commands.append)
        msgbus.register("ExecEngine.execute", self.commands.append)

        self.strategy = self._build_strategy()
        self.strategy.register(
            TRADER_ID,
            _SettledPositionPortfolio(settled_qty),
            msgbus,
            self.cache,
            clock,
        )

        self.contract = MispricingContract(
            instrument_id=self.local_id,
            facts=WeatherBucketFacts(
                settlement_station="NYC",
                climate_day=CLIMATE_DAY,
                measure=Measure.HIGH,
                lower_f=66,
                upper_f=67,
            ),
            tick_size=float(self.instrument.price_increment),
        )
        # `on_start` is bypassed: it subscribes to live data feeds no unit
        # test has, and everything it builds that matters here is stated
        # explicitly below.
        self.strategy._contracts = {self.local_id: self.contract}
        self.strategy._nt_ids = {self.local_id: self.instrument_id}
        if self.needs_deadlines:
            self.strategy._deadlines = {self.local_id: DEADLINE}
        self.limits = RiskLimits(
            max_position_contracts=MAX_POSITION_CONTRACTS,
            stale_observation_hours=STALE_OBSERVATION_HOURS,
        )
        self.risk = RiskManager(
            self.limits,
            {self.local_id: self.contract},
            native_instrument_ids=self.strategy._nt_ids,
        )
        self.strategy._risk = self.risk

    # -- per-strategy seams ----------------------------------------------

    def _build_strategy(self) -> Strategy:
        raise NotImplementedError

    def maybe_submit(self, *, current_qty: float = 0.0) -> None:
        raise NotImplementedError

    def flatten(self, reason: str = "test_flatten") -> None:
        self.strategy._flatten(self.local_id, reason)

    # -- order seeding ---------------------------------------------------

    def _new_order(
        self,
        *,
        side: OrderSide,
        quantity: float,
        position_id: PositionId | None = None,
    ) -> Order:
        order = self.strategy.order_factory.market(
            instrument_id=self.instrument_id,
            order_side=side,
            quantity=self.instrument.make_qty(quantity),
        )
        self.cache.add_order(order, position_id=position_id)
        return order

    def seed_initialized(
        self,
        *,
        side: OrderSide = OrderSide.BUY,
        quantity: float = ORDER_QTY,
    ) -> Order:
        """Cached, no lifecycle event yet -- invisible to `orders_open` AND `orders_inflight`."""
        return self._new_order(side=side, quantity=quantity)

    def seed_submitted(
        self,
        *,
        side: OrderSide = OrderSide.BUY,
        quantity: float = ORDER_QTY,
    ) -> Order:
        order = self._new_order(side=side, quantity=quantity)
        order.apply(TestEventStubs.order_submitted(order))
        self.cache.update_order(order)
        return order

    def seed_open_position(self, *, quantity: float = 100) -> Position:
        position_id = PositionId("P-FLATTEN")
        order = self._new_order(
            side=OrderSide.BUY,
            quantity=quantity,
            position_id=position_id,
        )
        order.apply(TestEventStubs.order_submitted(order))
        order.apply(TestEventStubs.order_accepted(order))
        fill = TestEventStubs.order_filled(
            order,
            self.instrument,
            position_id=position_id,
            last_px=self.instrument.make_price(0.5),
        )
        order.apply(fill)
        self.cache.update_order(order)
        position = Position(self.instrument, fill)
        self.cache.add_position(position, OmsType.NETTING)
        return position

    # -- observation -----------------------------------------------------

    def submit_commands(self) -> list[SubmitOrder]:
        return [c for c in self.commands if isinstance(c, SubmitOrder)]

    def cancel_all_commands(self) -> list[CancelAllOrders]:
        return [c for c in self.commands if isinstance(c, CancelAllOrders)]

    def spy_on_cancel_all_orders(self) -> list[Any]:
        """Record every `cancel_all_orders` call WITHOUT displacing the native one.

        The real bound method still runs, so the native "nothing to cancel"
        no-op path is genuinely exercised (and its absence of a command
        genuinely observed) rather than stubbed out.
        """
        calls: list[Any] = []
        native = self.strategy.cancel_all_orders

        def recording(*args: Any, **kwargs: Any) -> None:
            calls.append(args)
            native(*args, **kwargs)

        self.strategy.cancel_all_orders = recording
        return calls

    def snapshot(self) -> PortfolioSnapshot:
        # `Strategy` is a compiled Cython class, so the subclass method erases
        # to `Any` here -- the cast keeps the rig's own signature honest.
        return cast("PortfolioSnapshot", self.strategy._portfolio_snapshot())


class _CalibrationMeanReversionRig(_Rig):
    name = "calibration_mean_reversion"
    has_flatten = True

    def _build_strategy(self) -> Strategy:
        config = CalibrationMeanReversionConfig(instrument_ids=(self.instrument_id,))
        return CalibrationMeanReversionStrategy(config, _StubForecastSource())

    def maybe_submit(self, *, current_qty: float = 0.0) -> None:
        self.strategy._maybe_submit(
            self.contract,
            _quote(self.local_id),
            _decision(self.local_id),
            _forecast(),
            NOW,
            current_qty,
        )


class _ForecastRevisionRig(_Rig):
    name = "forecast_revision"
    has_flatten = True

    def _build_strategy(self) -> Strategy:
        config = ForecastRevisionConfig(instrument_ids=(self.instrument_id,))
        return ForecastRevisionStrategy(config, _StubForecastSource())

    def maybe_submit(self, *, current_qty: float = 0.0) -> None:
        self.strategy._maybe_submit(
            self.contract,
            _quote(self.local_id),
            _decision(self.local_id),
            _forecast(),
            NOW,
            current_qty,
        )


class _RunningExtremeLockRig(_Rig):
    name = "running_extreme_lock"
    needs_deadlines = True

    def _build_strategy(self) -> Strategy:
        config = RunningExtremeLockConfig(
            instrument_ids=(self.instrument_id,),
            stale_observation_hours=STALE_OBSERVATION_HOURS,
        )
        return RunningExtremeLockStrategy(config)

    def maybe_submit(self, *, current_qty: float = 0.0) -> None:
        self.strategy._maybe_submit(
            self.contract,
            _quote(self.local_id),
            _decision(self.local_id),
            _running_extreme_observation(),
            NOW,
            current_qty,
        )


class _CliSettlementPrintLockRig(_Rig):
    name = "cli_settlement_print_lock"
    needs_deadlines = True

    def _build_strategy(self) -> Strategy:
        config = CliSettlementPrintLockConfig(
            instrument_ids=(self.instrument_id,),
            stale_observation_hours=STALE_OBSERVATION_HOURS,
            slippage_prob=0.01,
        )
        return CliSettlementPrintLockStrategy(config, _StubFeeCoefficients())

    def maybe_submit(self, *, current_qty: float = 0.0) -> None:
        self.strategy._maybe_submit(
            self.contract,
            _quote(self.local_id),
            _decision(
                self.local_id,
                metadata={"cost_basis_anchor": COST_BASIS_ANCHOR, "fee_prob": FEE_PROB},
            ),
            _cli_print_observation(),
            NOW,
            current_qty,
            15.0,
        )


#: Every strategy T-1 stage 2 covers. `forecast_mispricing` is deliberately
#: absent: it is stage 1's template and has its own module.
ALL_RIGS = (
    _CalibrationMeanReversionRig,
    _ForecastRevisionRig,
    _RunningExtremeLockRig,
    _CliSettlementPrintLockRig,
)
ALL_RIG_IDS = [rig.name for rig in ALL_RIGS]

FLATTEN_RIGS = tuple(rig for rig in ALL_RIGS if rig.has_flatten)
FLATTEN_RIG_IDS = [rig.name for rig in FLATTEN_RIGS]


def _quote(instrument_id: str) -> MarketQuote:
    return MarketQuote(
        instrument_id=instrument_id,
        bid=0.28,
        ask=0.30,
        bid_size=1_000.0,
        ask_size=1_000.0,
        ts_event=NOW,
    )


def _forecast() -> ForecastSnapshot:
    return ForecastSnapshot(
        location_id="NYC",
        target_date=CLIMATE_DAY,
        published_at=NOW - dt.timedelta(hours=1),
        expected_high_f=95.0,
        horizon_hours=24.0,
    )


def _running_extreme_observation() -> RunningExtremeObservation:
    return RunningExtremeObservation(
        station="NYC",
        climate_day=CLIMATE_DAY,
        tmax_f=68,
        tmin_f=50,
        correction_flag=False,
        is_superseded=False,
        published_at=NOW - dt.timedelta(hours=1),
    )


def _cli_print_observation() -> CliPrintObservation:
    return CliPrintObservation(
        station="NYC",
        climate_day=CLIMATE_DAY,
        tmax_f=66,
        tmin_f=50,
        is_final=True,
        correction_flag=False,
        is_superseded=False,
        published_at=NOW - dt.timedelta(hours=1),
    )


def _decision(
    instrument_id: str,
    metadata: dict[str, float] | None = None,
) -> SignalDecision:
    return SignalDecision(
        instrument_id=instrument_id,
        intent=SideIntent.LONG_YES,
        model_probability=0.95,
        market_probability=0.30,
        edge=0.20,
        conviction=1.0,
        quantity=ORDER_QTY,
        reason="test_long_yes",
        metadata={} if metadata is None else metadata,
    )


# ----------------------------------------------------------------------
# class C -- `pending_qty` / `net_qty`
# ----------------------------------------------------------------------


@pytest.mark.parametrize("rig_cls", ALL_RIGS, ids=ALL_RIG_IDS)
def test_pending_qty_counts_a_submitted_order_the_position_does_not_yet_hold(
    rig_cls: type[_Rig],
) -> None:
    """Settled 0 plus one SUBMITTED BUY 200 is 200 of committed exposure."""
    rig = rig_cls(settled_qty=0.0)
    order = rig.seed_submitted(quantity=ORDER_QTY)
    assert order.status == OrderStatus.SUBMITTED
    assert rig.cache.orders_open(instrument_id=rig.instrument_id) == []

    snapshot = rig.snapshot()

    assert snapshot.position_qty[rig.local_id] == pytest.approx(0.0)
    assert snapshot.pending_qty[rig.local_id] == pytest.approx(ORDER_QTY)
    assert snapshot.net_qty(rig.local_id) == pytest.approx(ORDER_QTY)


@pytest.mark.parametrize("rig_cls", ALL_RIGS, ids=ALL_RIG_IDS)
def test_a_second_order_inside_the_submit_window_cannot_breach_the_position_cap(
    rig_cls: type[_Rig],
) -> None:
    """The operator-reserved `max_position_contracts` breach, per strategy.

    Settled 0, one SUBMITTED BUY 200, cap 250. A second +200 must either be
    refused outright or clipped to the 50 contracts of remaining room -- what
    it must NOT do is pass unclipped to a net 400 against a 250 cap.
    """
    rig = rig_cls(settled_qty=0.0)
    rig.seed_submitted(quantity=ORDER_QTY)

    decision = rig.risk.evaluate_order(
        contract=rig.contract,
        signed_qty_delta=ORDER_QTY,
        hours_to_settlement=24.0,
        signal_age=SignalFreshness.forecast(1.0),
        edge=0.20,
        portfolio=rig.snapshot(),
        quote=_quote(rig.local_id),
        quote_age_minutes=0.0,
    )

    room = MAX_POSITION_CONTRACTS - ORDER_QTY
    if decision.allowed:
        assert decision.clipped_quantity == pytest.approx(room), (
            f"{rig.name}: a second in-flight-window order was allowed at "
            f"{decision.clipped_quantity} contracts, taking the position to "
            f"{ORDER_QTY + decision.clipped_quantity} against a cap of "
            f"{MAX_POSITION_CONTRACTS}"
        )
    else:
        assert decision.reason == "max_position"


# ----------------------------------------------------------------------
# class A -- the re-submission gate
# ----------------------------------------------------------------------


@pytest.mark.parametrize("rig_cls", ALL_RIGS, ids=ALL_RIG_IDS)
def test_maybe_submit_does_submit_when_nothing_is_working(rig_cls: type[_Rig]) -> None:
    """Control: each rig CAN reach `submit_order`, so a silent-no-op cannot pass below."""
    rig = rig_cls(settled_qty=0.0)

    rig.maybe_submit(current_qty=0.0)

    assert len(rig.submit_commands()) == 1


@pytest.mark.parametrize("rig_cls", ALL_RIGS, ids=ALL_RIG_IDS)
def test_maybe_submit_does_not_duplicate_an_order_that_is_only_submitted(
    rig_cls: type[_Rig],
) -> None:
    """The submit -> ACCEPTED window is not an empty book."""
    rig = rig_cls(settled_qty=0.0)
    order = rig.seed_submitted(quantity=ORDER_QTY)
    assert order.status == OrderStatus.SUBMITTED

    rig.maybe_submit(current_qty=0.0)

    assert rig.submit_commands() == []


@pytest.mark.parametrize("rig_cls", ALL_RIGS, ids=ALL_RIG_IDS)
def test_maybe_submit_does_not_duplicate_an_order_that_is_only_initialized(
    rig_cls: type[_Rig],
) -> None:
    """INITIALIZED is invisible to `orders_open` AND to `orders_inflight`.

    This is the case that rules out the ``orders_open() + orders_inflight()``
    shortcut: ``is_inflight_c`` (``model/orders/base.pyx``) is
    SUBMITTED/PENDING_CANCEL/PENDING_UPDATE only, so an INITIALIZED order
    would stay invisible under it.
    """
    rig = rig_cls(settled_qty=0.0)
    order = rig.seed_initialized(quantity=ORDER_QTY)
    assert order.status == OrderStatus.INITIALIZED
    assert rig.cache.orders_open(instrument_id=rig.instrument_id) == []
    assert rig.cache.orders_inflight(instrument_id=rig.instrument_id) == []

    rig.maybe_submit(current_qty=0.0)

    assert rig.submit_commands() == []


# ----------------------------------------------------------------------
# class B -- the cancel pre-filter in `_flatten`
# ----------------------------------------------------------------------


@pytest.mark.parametrize("rig_cls", FLATTEN_RIGS, ids=FLATTEN_RIG_IDS)
def test_flatten_cancels_a_submitted_sell_before_closing(rig_cls: type[_Rig]) -> None:
    """A SUBMITTED SELL is not `orders_open`, but IS `orders_inflight`.

    Nautilus's `cancel_all_orders` reaches it; the Breezy pre-filter, reading
    the narrower query, suppressed the cancel entirely.
    """
    rig = rig_cls(settled_qty=100.0)
    rig.seed_open_position(quantity=100)
    order = rig.seed_submitted(side=OrderSide.SELL, quantity=50)
    assert order.status == OrderStatus.SUBMITTED
    assert rig.cache.orders_open(instrument_id=rig.instrument_id) == []

    rig.flatten()

    assert len(rig.cancel_all_commands()) == 1
    assert len(rig.submit_commands()) == 1  # the position close


@pytest.mark.parametrize("rig_cls", FLATTEN_RIGS, ids=FLATTEN_RIG_IDS)
def test_flatten_still_closes_when_there_is_nothing_to_cancel(rig_cls: type[_Rig]) -> None:
    """The unconditional cancel must be a clean native no-op.

    `cancel_all_orders` is called every time now, so the path where all three
    of Nautilus's queries (`orders_open`, `orders_emulated`, `orders_inflight`)
    come back empty is pinned: it logs, returns, emits no command, and the
    close still happens.
    """
    rig = rig_cls(settled_qty=100.0)
    rig.seed_open_position(quantity=100)
    calls = rig.spy_on_cancel_all_orders()

    rig.flatten()

    assert len(calls) == 1, "cancel_all_orders must be called unconditionally"
    assert rig.cancel_all_commands() == []  # native no-op: nothing to cancel
    assert len(rig.submit_commands()) == 1  # the position close still happens
