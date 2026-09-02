"""``_flatten`` must cancel a working order the SETTLED position cannot see.

T-2 (``docs/plans/`` — follow-on to T-1's in-flight blindness work).

THE DEFECT
----------
``_flatten`` is byte-identical in ``forecast_mispricing``,
``calibration_mean_reversion`` and ``forecast_revision``, and every copy opened
with::

    qty = float(self.portfolio.net_position(nt_id))
    if abs(qty) < 1e-9:
        return

``Portfolio.net_position`` is SETTLED-ONLY: a ``Position`` exists only once a
fill has been applied. So a strategy holding nothing settled but carrying a
working order returned at that guard and cancelled NOTHING.

The reachable hazard is the one ``flatten_on_observation`` exists to prevent.
Tick N: settled 0, the strategy submits BUY 200 (SUBMITTED, unfilled). Tick
N+1: the final ``NwsClimateDay`` arrives -> ``on_data`` -> ``_flatten(iid,
"observation_received")`` -> ``net_position`` is still 0 -> return. The BUY is
never cancelled and fills AFTER the settlement-determining observation is
public, leaving the strategy long a contract whose outcome is already known.
No ``FLATTEN`` line is logged, so it is silent. ``settlement_halt`` takes the
identical path.

WHY THE EXISTING FLATTEN TESTS DID NOT CATCH IT
-----------------------------------------------
``test_flatten_cancels_a_submitted_sell_before_closing`` and
``test_flatten_still_closes_when_there_is_nothing_to_cancel`` (in
``test_forecast_mispricing_inflight_orders.py`` and
``test_weather_strategy_inflight_orders.py``) both construct their rig with
``settled_qty=100.0``. They enter ``_flatten`` past the guard by construction
and therefore measure only what happens after it. This module states the
zero-settled cases they cannot reach; those tests are left intact as the
non-zero-settled half of the same contract.

WHAT IS *NOT* CLOSED
--------------------
Native ``Strategy.cancel_all_orders``
(``nautilus_trader/trading/strategy.pyx:1297``) explicitly ``continue``s on
``OrderStatus.INITIALIZED``, and INITIALIZED appears in none of
``orders_open`` / ``orders_inflight`` / ``orders_emulated``. An INITIALIZED
order is therefore still uncancellable by anyone, and this module does not
pretend otherwise: it pins the SUBMITTED window, which is the reachable one.

FIDELITY
--------
Real ``Cache``, real ``MessageBus``, real ``OrderFactory``, real Nautilus
order-status transitions, with the emitted commands captured off the
``RiskEngine.execute`` / ``ExecEngine.execute`` endpoints — the same rig shape
as ``test_weather_strategy_inflight_orders.py``. Two doubles only, both
narrow: ``PortfolioFacade`` so a settled position can be STATED (that is the
variable under test), and a recording proxy over the strategy's ``log`` that
forwards to the real ``Logger`` — Nautilus's logging subsystem is a
process-global initialized once by whichever backtest runs first, so
capturing it at the file descriptor would make these assertions
order-dependent.
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
from nautilus_trader.model.enums import OmsType, OrderSide, OrderStatus
from nautilus_trader.model.identifiers import PositionId, TraderId
from nautilus_trader.model.position import Position
from nautilus_trader.portfolio.base import PortfolioFacade
from nautilus_trader.test_kit.stubs.events import TestEventStubs

from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.domain.weather_bucket_facts import Measure, WeatherBucketFacts
from breezy.strategy.calibration_mean_reversion.config import CalibrationMeanReversionConfig
from breezy.strategy.calibration_mean_reversion.strategy import CalibrationMeanReversionStrategy
from breezy.strategy.forecast_mispricing.config import ForecastMispricingConfig
from breezy.strategy.forecast_mispricing.strategy import ForecastMispricingStrategy
from breezy.strategy.forecast_revision.config import ForecastRevisionConfig
from breezy.strategy.forecast_revision.strategy import ForecastRevisionStrategy
from breezy.strategy.weather_common.bucket_contract import MispricingContract
from breezy.strategy.weather_common.models import ForecastSnapshot
from tests.unit.conftest import iter_captured_market_payloads

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.model.instruments import BinaryOption
    from nautilus_trader.model.orders.base import Order
    from nautilus_trader.trading.strategy import Strategy

TRADER_ID = TraderId("BREEZY-FLATTEN-004")
NOW = dt.datetime(2026, 4, 22, 12, 0, tzinfo=dt.UTC)
CLIMATE_DAY = dt.date(2026, 4, 23)

#: The hazard's own numbers: one BUY 200 left working across the observation.
ORDER_QTY = 200.0

#: The settled size used by the RED-D control, where the pre-T-2 guard was
#: already passed and behaviour must not change.
SETTLED_QTY = 100.0

#: The real `on_data` reason string, so the log assertion pins the line an
#: operator would actually search for after a settlement print.
OBSERVATION_REASON = "observation_received"


def _instrument() -> BinaryOption:
    payloads = iter_captured_market_payloads()
    assert payloads, "no captured Polymarket.us market payloads on disk"
    return parse_binary_option(payloads[0], ts_init=0)


class _StubForecastSource:
    """Never consulted: every test here calls ``_flatten`` directly."""

    def snapshot(
        self,
        *,
        station: str,
        climate_day: dt.date,
        now: dt.datetime,
    ) -> ForecastSnapshot | None:
        del station, climate_day, now
        return None


class _SettledPositionPortfolio(PortfolioFacade):  # type: ignore[misc]  # compiled Cython base erases to Any
    """States the SETTLED position only — the view ``_flatten`` used to trust alone."""

    def __init__(self, net: float) -> None:
        self._net = Decimal(str(net))

    def net_position(self, instrument_id: Any, account_id: Any = None) -> Decimal:
        del instrument_id, account_id
        return self._net

    def account(self, venue: Any) -> None:
        del venue


class _RecordingLog:
    """Records every message and forwards it to the real ``Logger``.

    The native logger still runs, so nothing about the strategy's logging
    behaviour is stubbed away — only observed.
    """

    def __init__(self, real: Any, messages: list[str]) -> None:
        self._real = real
        self._messages = messages

    def info(self, message: str, **kwargs: Any) -> None:
        self._messages.append(message)
        self._real.info(message, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class _Rig:
    """One real strategy on a real cache; subclasses supply construction only."""

    name: str = "base"

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, settled_qty: float = 0.0) -> None:
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
        # test has, and `_flatten` reads only `_nt_ids`.
        self.strategy._contracts = {self.local_id: self.contract}
        self.strategy._nt_ids = {self.local_id: self.instrument_id}

        # `Actor.log` is a read-only Cython attribute, so the recorder is
        # installed as a class attribute on the (pure-Python) strategy
        # subclass, where it shadows the base descriptor for the Python-level
        # `self.log` lookup inside `_flatten`. Nautilus's own Cython code
        # reads the C-level `_log` slot and is unaffected. `monkeypatch`
        # removes it at teardown.
        self.log_messages: list[str] = []
        real_log = self.strategy.log
        monkeypatch.setattr(
            type(self.strategy),
            "log",
            property(lambda _self: _RecordingLog(real_log, self.log_messages)),
            raising=False,
        )

    # -- per-strategy seam -----------------------------------------------

    def _build_strategy(self) -> Strategy:
        raise NotImplementedError

    # -- action ----------------------------------------------------------

    def flatten(self, reason: str = OBSERVATION_REASON) -> None:
        self.strategy._flatten(self.local_id, reason)

    # -- order / position seeding ----------------------------------------

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

    def seed_open_position(self, *, quantity: float = SETTLED_QTY) -> Position:
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

    def flatten_log_lines(self) -> list[str]:
        return [m for m in self.log_messages if m.startswith("FLATTEN ")]

    def spy_on_exits(self) -> tuple[list[Any], list[Any]]:
        """Record calls to both native exit calls WITHOUT displacing them.

        The real bound methods still run, so a native no-op path is genuinely
        exercised rather than stubbed out.
        """
        cancels: list[Any] = []
        closes: list[Any] = []
        native_cancel = self.strategy.cancel_all_orders
        native_close = self.strategy.close_all_positions

        def recording_cancel(*args: Any, **kwargs: Any) -> None:
            cancels.append(args)
            native_cancel(*args, **kwargs)

        def recording_close(*args: Any, **kwargs: Any) -> None:
            closes.append(args)
            native_close(*args, **kwargs)

        self.strategy.cancel_all_orders = recording_cancel
        self.strategy.close_all_positions = recording_close
        return cancels, closes


class _ForecastMispricingRig(_Rig):
    name = "forecast_mispricing"

    def _build_strategy(self) -> Strategy:
        config = ForecastMispricingConfig(instrument_ids=(self.instrument_id,))
        return ForecastMispricingStrategy(config, _StubForecastSource())


class _CalibrationMeanReversionRig(_Rig):
    name = "calibration_mean_reversion"

    def _build_strategy(self) -> Strategy:
        config = CalibrationMeanReversionConfig(instrument_ids=(self.instrument_id,))
        return CalibrationMeanReversionStrategy(config, _StubForecastSource())


class _ForecastRevisionRig(_Rig):
    name = "forecast_revision"

    def _build_strategy(self) -> Strategy:
        config = ForecastRevisionConfig(instrument_ids=(self.instrument_id,))
        return ForecastRevisionStrategy(config, _StubForecastSource())


#: The three strategies that carry a byte-identical `_flatten`.
FLATTEN_RIGS = (
    _ForecastMispricingRig,
    _CalibrationMeanReversionRig,
    _ForecastRevisionRig,
)
FLATTEN_RIG_IDS = [rig.name for rig in FLATTEN_RIGS]


# ----------------------------------------------------------------------
# RED-A / RED-B -- zero settled, one working order
# ----------------------------------------------------------------------


@pytest.mark.parametrize("rig_cls", FLATTEN_RIGS, ids=FLATTEN_RIG_IDS)
def test_flatten_cancels_a_working_buy_when_nothing_is_settled(
    rig_cls: type[_Rig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-A. The observation is public; the unfilled BUY must not survive it."""
    rig = rig_cls(monkeypatch, settled_qty=0.0)
    order = rig.seed_submitted(side=OrderSide.BUY, quantity=ORDER_QTY)
    assert order.status == OrderStatus.SUBMITTED
    assert rig.cache.positions_open(instrument_id=rig.instrument_id) == []

    rig.flatten(OBSERVATION_REASON)

    assert len(rig.cancel_all_commands()) == 1, (
        f"{rig_cls.name}: a SUBMITTED BUY survived _flatten because the settled "
        "position was zero — it will fill after the settlement-determining "
        "observation is already public"
    )


@pytest.mark.parametrize("rig_cls", FLATTEN_RIGS, ids=FLATTEN_RIG_IDS)
def test_flatten_of_a_working_order_is_not_silent(
    rig_cls: type[_Rig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-B. A cancel an operator cannot see in the log did not happen, for them."""
    rig = rig_cls(monkeypatch, settled_qty=0.0)
    rig.seed_submitted(side=OrderSide.BUY, quantity=ORDER_QTY)

    rig.flatten(OBSERVATION_REASON)

    lines = rig.flatten_log_lines()
    assert len(lines) == 1, f"{rig_cls.name}: no FLATTEN line logged: {rig.log_messages}"
    line = lines[0]
    assert "qty=0.0" in line, line
    assert "working=1" in line, line
    assert f"reason={OBSERVATION_REASON}" in line, line


# ----------------------------------------------------------------------
# RED-C -- genuinely nothing to do
# ----------------------------------------------------------------------


@pytest.mark.parametrize("rig_cls", FLATTEN_RIGS, ids=FLATTEN_RIG_IDS)
def test_flatten_returns_early_when_there_is_nothing_settled_and_nothing_working(
    rig_cls: type[_Rig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-C. The early return must survive: this fix is not "cancel on every tick"."""
    rig = rig_cls(monkeypatch, settled_qty=0.0)
    cancels, closes = rig.spy_on_exits()

    rig.flatten(OBSERVATION_REASON)

    assert cancels == [], f"{rig_cls.name}: cancel_all_orders called with nothing to cancel"
    assert closes == [], f"{rig_cls.name}: close_all_positions called with nothing to close"
    assert rig.cancel_all_commands() == []
    assert rig.submit_commands() == []
    assert rig.flatten_log_lines() == []


# ----------------------------------------------------------------------
# RED-D -- the pre-T-2 behaviour, unchanged
# ----------------------------------------------------------------------


@pytest.mark.parametrize("rig_cls", FLATTEN_RIGS, ids=FLATTEN_RIG_IDS)
def test_flatten_with_a_settled_position_still_cancels_closes_and_logs(
    rig_cls: type[_Rig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED-D. Control: the path that already worked keeps working, log included."""
    rig = rig_cls(monkeypatch, settled_qty=SETTLED_QTY)
    rig.seed_open_position(quantity=SETTLED_QTY)
    order = rig.seed_submitted(side=OrderSide.SELL, quantity=50)
    assert order.status == OrderStatus.SUBMITTED

    rig.flatten(OBSERVATION_REASON)

    assert len(rig.cancel_all_commands()) == 1
    assert len(rig.submit_commands()) == 1  # the position close
    lines = rig.flatten_log_lines()
    assert len(lines) == 1, rig.log_messages
    assert f"qty={SETTLED_QTY:.1f}" in lines[0], lines[0]
