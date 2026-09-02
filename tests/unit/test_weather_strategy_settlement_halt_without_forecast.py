"""The settlement halt is a TIME decision and must not need a forecast to fire.

T-5 (``docs/core/findings/BLIND_RISK_VIEWS_2026-09-02.md``).

THE DEFECT
----------
``forecast_mispricing/strategy.py``, mirrored byte-for-byte in
``calibration_mean_reversion`` and ``forecast_revision``::

    forecast = self._forecast_source.snapshot(...)
    if forecast is None:
        return
    if forecast.horizon_hours <= self._config.halt_hours_before_settlement:
        self._flatten(instrument_id, "settlement_halt")
        return

The halt is reached ONLY through a forecast object. Drop the station/day at
the provider -- a routine outage -- and every tick returns at ``forecast is
None``, so the halt never fires: 200 contracts held at T-minus-70 minutes ride
into settlement with no exit ever attempted, silently (the ``FLATTEN`` line is
downstream of the return).

WHAT IS *NOT* THE DEFECT, AND MUST SURVIVE THE FIX
---------------------------------------------------
"Never flatten-for-lack-of-forecast" is a DELIBERATE trade, stated in
``breezy.strategy.weather_common.forecast_source``: a missing forecast means
"skip evaluation", never "panic out of the book". This module pins BOTH
halves -- the halt must fire on the clock (RED-1), and a missing forecast
OUTSIDE the halt window must still flatten nothing (RED-2). A fix that
inverted the trade would pass RED-1 and fail RED-2.

THE SHAPE OF THE FIX THIS PINS
-------------------------------
``running_extreme_lock`` already does this correctly and is not exposed: it
records ``instrument.expiration_ns`` -- the NATIVE Nautilus settlement
deadline -- into ``_deadlines`` at subscribe time, and evaluates the halt from
``hours_until(deadline, self.clock.utc_now())``. RED-0 pins the wiring
(``on_start`` must record the deadline) and RED-1/3 pin the behaviour.

FIDELITY
--------
Real ``Cache``, real ``MessageBus``, real ``TestClock``, real ``OrderFactory``,
real Nautilus order/position state, with the emitted commands captured off the
``RiskEngine.execute`` / ``ExecEngine.execute`` endpoints -- the rig shape of
``test_weather_strategy_flatten_working_orders.py``, from which this module is
modelled. Two doubles only, both narrow: ``PortfolioFacade`` so a settled
position can be STATED, and a recording proxy over ``log`` that forwards to
the real ``Logger`` (Nautilus's logging subsystem is a process-global
initialised by whichever backtest runs first, so capturing at the file
descriptor would make these assertions order-dependent).

The instrument is the REAL captured Polymarket.us market, so
``expiration_ns`` is a real venue settlement instant and the clock is set
relative to it -- not to an invented deadline.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import MessageBus, TestClock
from nautilus_trader.config import CacheConfig
from nautilus_trader.execution.messages import CancelAllOrders, SubmitOrder
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.enums import OmsType, OrderSide
from nautilus_trader.model.identifiers import PositionId, TraderId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.model.position import Position
from nautilus_trader.portfolio.base import PortfolioFacade
from nautilus_trader.portfolio.portfolio import Portfolio
from nautilus_trader.test_kit.stubs.component import TestComponentStubs
from nautilus_trader.test_kit.stubs.events import TestEventStubs

from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.domain.weather_bucket_facts import read_weather_bucket_facts
from breezy.strategy.calibration_mean_reversion.config import CalibrationMeanReversionConfig
from breezy.strategy.calibration_mean_reversion.strategy import CalibrationMeanReversionStrategy
from breezy.strategy.forecast_mispricing.config import ForecastMispricingConfig
from breezy.strategy.forecast_mispricing.strategy import ForecastMispricingStrategy
from breezy.strategy.forecast_revision.config import ForecastRevisionConfig
from breezy.strategy.forecast_revision.strategy import ForecastRevisionStrategy
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.models import ForecastSnapshot, hours_until
from tests.unit.conftest import iter_captured_market_payloads

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.model.instruments import BinaryOption
    from nautilus_trader.model.orders.base import Order
    from nautilus_trader.trading.strategy import Strategy

TRADER_ID = TraderId("BREEZY-HALT-005")

#: Stated, not defaulted: the finding's scenario is T-minus-70 minutes, which
#: is 1.167h and would sit OUTSIDE the 1.0h default. Two hours puts it inside,
#: so the window under test is the configured one and not an inherited number.
HALT_HOURS = 2.0

#: The finding's own numbers.
HELD_QTY = 200.0
MINUTES_BEFORE_SETTLEMENT_INSIDE = 70.0
HOURS_BEFORE_SETTLEMENT_OUTSIDE = 6.0

#: The reason string an operator greps for after a position rides in.
HALT_REASON = "settlement_halt"

_NS_PER_SECOND = 1_000_000_000


def _instrument() -> BinaryOption:
    payloads = iter_captured_market_payloads()
    assert payloads, "no captured Polymarket.us market payloads on disk"
    return parse_binary_option(payloads[0], ts_init=0)


def _deadline_of(instrument: BinaryOption) -> dt.datetime:
    return dt.datetime.fromtimestamp(instrument.expiration_ns / _NS_PER_SECOND, tz=dt.UTC)


class _NoForecastSource:
    """The outage under test: the provider has dropped this station/day."""

    def snapshot(
        self,
        *,
        station: str,
        climate_day: dt.date,
        now: dt.datetime,
    ) -> ForecastSnapshot | None:
        del station, climate_day, now
        return None


class _LiveForecastSource:
    """A CONFORMING source: ``horizon_hours`` is live against the real deadline.

    This is the control for RED-3. It obeys the
    ``breezy.strategy.weather_common.forecast_source`` contract exactly --
    ``horizon_hours`` recomputed from the ``now`` it was called with -- so the
    halt it triggers today and the clock-derived halt agree by construction.
    """

    def __init__(self, deadline: dt.datetime) -> None:
        self._deadline = deadline

    def snapshot(
        self,
        *,
        station: str,
        climate_day: dt.date,
        now: dt.datetime,
    ) -> ForecastSnapshot | None:
        return ForecastSnapshot(
            location_id=station,
            target_date=climate_day,
            published_at=now - dt.timedelta(hours=3),
            expected_high_f=66.5,
            horizon_hours=hours_until(self._deadline, now),
        )


class _SettledPositionPortfolio(PortfolioFacade):  # type: ignore[misc]  # compiled Cython base erases to Any
    """States the SETTLED position only -- what ``_flatten`` reads."""

    def __init__(self, net: float) -> None:
        self._net = Decimal(str(net))

    def net_position(self, instrument_id: Any, account_id: Any = None) -> Decimal:
        del instrument_id, account_id
        return self._net

    def account(self, venue: Any) -> None:
        del venue


class _RecordingLog:
    """Records every message and forwards it to the real ``Logger``."""

    def __init__(self, real: Any, messages: list[str]) -> None:
        self._real = real
        self._messages = messages

    def info(self, message: str, **kwargs: Any) -> None:
        self._messages.append(message)
        self._real.info(message, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class _Rig:
    """One real strategy on a real cache, with the clock set near settlement."""

    name: str = "base"

    def __init__(
        self,
        monkeypatch: pytest.MonkeyPatch,
        *,
        forecast_source: Any,
        hours_to_settlement: float,
        settled_qty: float = 0.0,
    ) -> None:
        self.instrument = _instrument()
        self.instrument_id = self.instrument.id
        self.local_id = str(self.instrument.id)
        self.deadline = _deadline_of(self.instrument)

        self.clock = TestClock()
        self.now_ns = self.instrument.expiration_ns - int(
            hours_to_settlement * 3600 * _NS_PER_SECOND,
        )
        self.clock.set_time(self.now_ns)

        msgbus = MessageBus(trader_id=TRADER_ID, clock=self.clock)
        self.cache = Cache(
            database=None,
            config=CacheConfig(database=None, flush_on_start=False),
        )
        self.cache.add_instrument(self.instrument)

        self.commands: list[Any] = []
        msgbus.register("RiskEngine.execute", self.commands.append)
        msgbus.register("ExecEngine.execute", self.commands.append)

        self.strategy = self.build_strategy(self.instrument_id, forecast_source)
        self.strategy.register(
            TRADER_ID,
            _SettledPositionPortfolio(settled_qty),
            msgbus,
            self.cache,
            self.clock,
        )

        self.contract = MispricingContract(
            instrument_id=self.local_id,
            facts=read_weather_bucket_facts(self.instrument.info),
            tick_size=float(self.instrument.price_increment),
        )
        # `on_start` is bypassed: it subscribes to live data feeds no unit test
        # has. Everything the evaluation path reads is stated explicitly --
        # including `_deadlines`, whose POPULATION is pinned separately by
        # `test_on_start_records_the_native_expiration_as_the_deadline`.
        self.strategy._contracts = {self.local_id: self.contract}
        self.strategy._nt_ids = {self.local_id: self.instrument_id}
        self.strategy._deadlines = {self.local_id: self.deadline}

        # `Actor.log` is a read-only Cython attribute, so the recorder is
        # installed as a class attribute on the (pure-Python) strategy
        # subclass, where it shadows the base descriptor for the Python-level
        # `self.log` lookup. `monkeypatch` removes it at teardown.
        self.log_messages: list[str] = []
        real_log = self.strategy.log
        monkeypatch.setattr(
            type(self.strategy),
            "log",
            property(lambda _self: _RecordingLog(real_log, self.log_messages)),
            raising=False,
        )

    # -- per-strategy seam -----------------------------------------------

    #: Set by each concrete rig; also used by RED-0, which needs the same
    #: strategy built WITHOUT the rig (it calls the real `on_start`).
    strategy_cls: type[Strategy]
    config_cls: Any

    @classmethod
    def build_strategy(cls, instrument_id: Any, forecast_source: Any) -> Strategy:
        return cls.strategy_cls(
            cls.config_cls(
                instrument_ids=(instrument_id,),
                halt_hours_before_settlement=HALT_HOURS,
            ),
            forecast_source,
        )

    # -- action ----------------------------------------------------------

    def tick(self) -> None:
        """Deliver one real quote -- the only thing that drives evaluation."""
        self.strategy.on_quote_tick(
            QuoteTick(
                instrument_id=self.instrument_id,
                bid_price=Price.from_str("0.40"),
                ask_price=Price.from_str("0.42"),
                bid_size=Quantity.from_int(100),
                ask_size=Quantity.from_int(100),
                ts_event=self.now_ns,
                ts_init=self.now_ns,
            ),
        )

    # -- seeding ---------------------------------------------------------

    def seed_open_position(self, *, quantity: float = HELD_QTY) -> Position:
        position_id = PositionId("P-HALT")
        order = self.strategy.order_factory.market(
            instrument_id=self.instrument_id,
            order_side=OrderSide.BUY,
            quantity=self.instrument.make_qty(quantity),
        )
        self.cache.add_order(order, position_id=position_id)
        order.apply(TestEventStubs.order_submitted(order))
        order.apply(TestEventStubs.order_accepted(order))
        fill = TestEventStubs.order_filled(
            order,
            self.instrument,
            position_id=position_id,
            last_px=self.instrument.make_price(0.4),
        )
        order.apply(fill)
        self.cache.update_order(order)
        position = Position(self.instrument, fill)
        self.cache.add_position(position, OmsType.NETTING)
        return position

    def seed_submitted(
        self,
        *,
        side: OrderSide = OrderSide.BUY,
        quantity: float = HELD_QTY,
    ) -> Order:
        order = self.strategy.order_factory.market(
            instrument_id=self.instrument_id,
            order_side=side,
            quantity=self.instrument.make_qty(quantity),
        )
        self.cache.add_order(order)
        order.apply(TestEventStubs.order_submitted(order))
        self.cache.update_order(order)
        return order

    # -- observation -----------------------------------------------------

    def cancel_all_commands(self) -> list[CancelAllOrders]:
        return [c for c in self.commands if isinstance(c, CancelAllOrders)]

    def submit_commands(self) -> list[SubmitOrder]:
        """The position-close order `close_all_positions` submits.

        Native `cancel_all_orders` logs-and-returns when nothing is
        open/inflight/emulated, so a held-but-quiet position produces NO
        `CancelAllOrders` -- the close order is the exit evidence there. Both
        are asserted below so neither half can silently stop happening.
        """
        return [c for c in self.commands if isinstance(c, SubmitOrder)]

    def flatten_log_lines(self) -> list[str]:
        return [m for m in self.log_messages if m.startswith("FLATTEN ")]


class _ForecastMispricingRig(_Rig):
    name = "forecast_mispricing"
    strategy_cls = ForecastMispricingStrategy
    config_cls = ForecastMispricingConfig


class _CalibrationMeanReversionRig(_Rig):
    name = "calibration_mean_reversion"
    strategy_cls = CalibrationMeanReversionStrategy
    config_cls = CalibrationMeanReversionConfig


class _ForecastRevisionRig(_Rig):
    name = "forecast_revision"
    strategy_cls = ForecastRevisionStrategy
    config_cls = ForecastRevisionConfig


#: The three strategies whose halt is reachable only through a forecast.
HALT_RIGS = (
    _ForecastMispricingRig,
    _CalibrationMeanReversionRig,
    _ForecastRevisionRig,
)
HALT_RIG_IDS = [rig.name for rig in HALT_RIGS]


# ----------------------------------------------------------------------
# RED-0 -- the wiring: `on_start` must record the NATIVE deadline
# ----------------------------------------------------------------------


@pytest.mark.parametrize("rig_cls", HALT_RIGS, ids=HALT_RIG_IDS)
def test_on_start_records_the_native_expiration_as_the_deadline(
    rig_cls: type[_Rig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-0. A clock-derived halt needs a deadline; it comes from Nautilus.

    ``instrument.expiration_ns`` is the native settlement instant Nautilus
    already carries on ``BinaryOption``. Nothing here recomputes a settlement
    wall clock -- see ``test_weather_strategy_settlement_clock.py``.
    """
    del monkeypatch
    instrument = _instrument()
    clock = TestClock()
    msgbus = TestComponentStubs.msgbus()
    cache = TestComponentStubs.cache()
    cache.add_instrument(instrument)
    portfolio = Portfolio(msgbus=msgbus, cache=cache, clock=clock)
    # Without a data endpoint a `SubscribeQuoteTicks` reaches no handler, which
    # Nautilus reports as an error rather than raising.
    msgbus.register(endpoint="DataEngine.execute", handler=lambda command: None)

    strategy = rig_cls.build_strategy(instrument.id, _NoForecastSource())
    strategy.register(
        trader_id=TRADER_ID,
        portfolio=portfolio,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
    )
    strategy.start()  # -> RUNNING, then `on_start`

    deadlines = getattr(strategy, "_deadlines", None)
    assert deadlines is not None, (
        f"{rig_cls.name}: no `_deadlines` map -- the settlement halt can only "
        "be reached through a forecast object, so a provider outage disables it"
    )
    assert deadlines[str(instrument.id)] == _deadline_of(instrument), (
        f"{rig_cls.name}: the recorded deadline is not the instrument's own "
        "`expiration_ns`"
    )


# ----------------------------------------------------------------------
# RED-1 -- the defect: the halt must not need a forecast
# ----------------------------------------------------------------------


@pytest.mark.parametrize("rig_cls", HALT_RIGS, ids=HALT_RIG_IDS)
def test_settlement_halt_fires_when_the_forecast_source_dropped_the_station(
    rig_cls: type[_Rig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-1. 200 held, T-minus-70min, provider outage -- an exit must be tried."""
    rig = rig_cls(
        monkeypatch,
        forecast_source=_NoForecastSource(),
        hours_to_settlement=MINUTES_BEFORE_SETTLEMENT_INSIDE / 60.0,
        settled_qty=HELD_QTY,
    )
    rig.seed_open_position()
    rig.seed_submitted(side=OrderSide.SELL, quantity=50)

    rig.tick()

    assert len(rig.cancel_all_commands()) == 1, (
        f"{rig_cls.name}: no exit was attempted at T-minus-"
        f"{MINUTES_BEFORE_SETTLEMENT_INSIDE:.0f}min with {HELD_QTY:.0f} contracts "
        "held -- the missing forecast returned before the settlement halt, so "
        "the position rides into settlement"
    )
    assert len(rig.submit_commands()) == 1, (
        f"{rig_cls.name}: the held position was never closed"
    )
    lines = rig.flatten_log_lines()
    assert len(lines) == 1, f"{rig_cls.name}: silent halt: {rig.log_messages}"
    assert f"reason={HALT_REASON}" in lines[0], lines[0]


# ----------------------------------------------------------------------
# RED-2 -- the trade that must survive: no panic-flatten on a missing forecast
# ----------------------------------------------------------------------


@pytest.mark.parametrize("rig_cls", HALT_RIGS, ids=HALT_RIG_IDS)
def test_a_missing_forecast_outside_the_halt_window_flattens_nothing(
    rig_cls: type[_Rig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-2. "Never flatten-for-lack-of-forecast" is deliberate; pin it.

    A fix that became "flatten whenever the forecast is missing" would pass
    RED-1 and invert the stated trade in
    ``breezy.strategy.weather_common.forecast_source``. This is the pin that
    catches it.
    """
    rig = rig_cls(
        monkeypatch,
        forecast_source=_NoForecastSource(),
        hours_to_settlement=HOURS_BEFORE_SETTLEMENT_OUTSIDE,
        settled_qty=HELD_QTY,
    )
    rig.seed_open_position()
    rig.seed_submitted(side=OrderSide.SELL, quantity=50)
    commands_before = len(rig.commands)

    rig.tick()

    assert len(rig.commands) == commands_before, (
        f"{rig_cls.name}: a missing forecast at T-minus-"
        f"{HOURS_BEFORE_SETTLEMENT_OUTSIDE:.0f}h caused an exit -- the fix "
        "inverted the deliberate never-flatten-for-lack-of-forecast trade"
    )
    assert rig.flatten_log_lines() == [], rig.log_messages


# ----------------------------------------------------------------------
# RED-3 -- regression pin: the forecast-present halt still fires
# ----------------------------------------------------------------------


@pytest.mark.parametrize("rig_cls", HALT_RIGS, ids=HALT_RIG_IDS)
def test_settlement_halt_still_fires_with_a_conforming_forecast_present(
    rig_cls: type[_Rig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-3. Passes on the pre-fix tree; states the behaviour that must not move."""
    instrument = _instrument()
    rig = rig_cls(
        monkeypatch,
        forecast_source=_LiveForecastSource(_deadline_of(instrument)),
        hours_to_settlement=MINUTES_BEFORE_SETTLEMENT_INSIDE / 60.0,
        settled_qty=HELD_QTY,
    )
    rig.seed_open_position()
    rig.seed_submitted(side=OrderSide.SELL, quantity=50)

    rig.tick()

    assert len(rig.cancel_all_commands()) == 1, (
        f"{rig_cls.name}: the settlement halt stopped firing when a forecast IS "
        "present -- a regression, not the T-5 defect"
    )
    assert len(rig.submit_commands()) == 1, (
        f"{rig_cls.name}: the held position was never closed"
    )
    lines = rig.flatten_log_lines()
    assert len(lines) == 1, f"{rig_cls.name}: silent halt: {rig.log_messages}"
    assert f"reason={HALT_REASON}" in lines[0], lines[0]


# ----------------------------------------------------------------------
# RED-4 -- nothing to exit: the halt must stay silent and must not raise
# ----------------------------------------------------------------------


@pytest.mark.parametrize("rig_cls", HALT_RIGS, ids=HALT_RIG_IDS)
def test_a_halt_with_nothing_to_exit_is_silent_and_raises_nothing(
    rig_cls: type[_Rig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-4. Guards the interaction with T-2's ``_flatten`` early return.

    Zero settled AND no working order is the one case ``_flatten`` returns on.
    Reaching it every tick for the whole halt window must stay free of both
    exceptions and spurious commands.
    """
    rig = rig_cls(
        monkeypatch,
        forecast_source=_NoForecastSource(),
        hours_to_settlement=MINUTES_BEFORE_SETTLEMENT_INSIDE / 60.0,
        settled_qty=0.0,
    )
    assert rig.cache.positions_open(instrument_id=rig.instrument_id) == []

    rig.tick()
    rig.tick()

    assert rig.commands == [], f"{rig_cls.name}: spurious commands {rig.commands}"
    assert rig.flatten_log_lines() == [], rig.log_messages


@pytest.mark.parametrize("rig_cls", HALT_RIGS, ids=HALT_RIG_IDS)
def test_a_halt_cancels_a_working_order_even_with_nothing_settled(
    rig_cls: type[_Rig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-4b. The T-2 hazard under the T-5 trigger: SUBMITTED, zero settled.

    The BUY submitted on the previous tick would otherwise fill inside the
    halt window. ``net_position`` cannot see it; ``working_orders`` can.
    """
    rig = rig_cls(
        monkeypatch,
        forecast_source=_NoForecastSource(),
        hours_to_settlement=MINUTES_BEFORE_SETTLEMENT_INSIDE / 60.0,
        settled_qty=0.0,
    )
    rig.seed_submitted()

    rig.tick()

    assert len(rig.cancel_all_commands()) == 1, (
        f"{rig_cls.name}: a SUBMITTED BUY survived the settlement halt"
    )
