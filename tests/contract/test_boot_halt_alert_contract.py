"""AUD-13d: a real kernel's startup early-return is a CRITICAL boot-halt alert.

The lifecycle contract beside this file is the positive control: the same
``build_trade_node_config`` wiring reaches ``trader.is_running``. Each test
here perturbs that wiring by exactly one fact (a client that never connects,
a reconciliation that returns false, a portfolio that never initialises) and
asserts the boot-halt ``detail`` the post-``run()`` ladder resolves.

Nothing in ``nautilus_trader`` is monkeypatched. Levers are a
``TradingNodeConfig`` timeout or a Breezy-owned client subclass registered
through the documented factory seam. No venue socket is opened. The alert
sink is an in-process recorder; ``resolve_alert_sink`` is never the webhook.
"""

from __future__ import annotations

import asyncio
import io
import threading
import time
from enum import Enum
from typing import Any

import pytest
from msgspec.structs import replace as msgspec_replace
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.config import LiveDataClientConfig
from nautilus_trader.live.data_client import LiveMarketDataClient
from nautilus_trader.live.execution_client import LiveExecutionClient
from nautilus_trader.live.factories import LiveDataClientFactory, LiveExecClientFactory
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.enums import AccountType, OmsType, OrderSide
from nautilus_trader.model.identifiers import ClientId, PositionId, StrategyId
from nautilus_trader.model.objects import Currency
from nautilus_trader.model.position import Position
from nautilus_trader.test_kit.providers import TestInstrumentProvider
from nautilus_trader.test_kit.stubs.events import TestEventStubs

from breezy.adapters.polymarket_us.safety import MAX_ORDER_NOTIONAL_USD_ENV_VAR
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.runtime import trade_cli
from breezy.runtime.health import AlertPayload
from breezy.runtime.trade_cli import EXIT_OK, run
from tests.unit.test_trade_cli import TRADE_ENV

pytestmark = pytest.mark.contract

_STARTUP_TIMEOUT_S = 0.5
_HALT_SETTLE_S = 2.0
_DRIVE_DEADLINE_S = 20.0

OPERATOR_ORDER_CEILING_USD = "25"

_BOOT_HALT_EVENT = "BOOT_HALT"
_DETAIL_ENGINES = "BOOT_HALT_ENGINES_NOT_CONNECTED"
_DETAIL_RECONCILIATION = "BOOT_HALT_RECONCILIATION_FAILED"
_DETAIL_PORTFOLIO = "BOOT_HALT_PORTFOLIO_NOT_INITIALISED"


class _Mode(Enum):
    REACHES_RUNNING = "reaches_running"
    ENGINES_NEVER_CONNECT = "engines"
    RECONCILIATION_FAILS = "reconciliation"
    PORTFOLIO_NEVER_INITIALISES = "portfolio"


class _RecordingAlertSink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


@pytest.fixture(autouse=True)
def _operator_order_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, OPERATOR_ORDER_CEILING_USD)


@pytest.fixture
def alert_sink(monkeypatch: pytest.MonkeyPatch) -> _RecordingAlertSink:
    sink = _RecordingAlertSink()
    monkeypatch.setattr(trade_cli, "resolve_alert_sink", lambda: sink, raising=False)
    return sink


class _SilentDataClient(LiveMarketDataClient):
    async def _connect(self) -> None:
        return None

    async def _disconnect(self) -> None:
        return None


class _SilentDataClientFactory(LiveDataClientFactory):
    @staticmethod
    def create(  # type: ignore[override]
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: LiveDataClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> _SilentDataClient:
        del config
        return _SilentDataClient(
            loop=loop,
            client_id=ClientId(name),
            venue=POLYMARKET_US_VENUE,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=InstrumentProvider(),
        )


class _NeverConnectingDataClient(LiveMarketDataClient):
    """``_connect`` waits on an event nobody sets, so the client never connects."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._never = asyncio.Event()

    async def _connect(self) -> None:
        await self._never.wait()

    async def _disconnect(self) -> None:
        return None


class _NeverConnectingDataClientFactory(LiveDataClientFactory):
    @staticmethod
    def create(  # type: ignore[override]
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: LiveDataClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> _NeverConnectingDataClient:
        del config
        return _NeverConnectingDataClient(
            loop=loop,
            client_id=ClientId(name),
            venue=POLYMARKET_US_VENUE,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=InstrumentProvider(),
        )


class _MassStatusNoneExecClient(LiveExecutionClient):
    """Connects, then returns no mass status so reconciliation fails closed."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        client_id: ClientId,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> None:
        super().__init__(
            loop=loop,
            client_id=client_id,
            venue=POLYMARKET_US_VENUE,
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            base_currency=Currency.from_str("USD"),
            instrument_provider=InstrumentProvider(),
            msgbus=msgbus,
            cache=cache,
            clock=clock,
        )

    async def _connect(self) -> None:
        return None

    async def _disconnect(self) -> None:
        return None

    async def generate_mass_status(self, lookback_mins: int | None = None) -> None:
        del lookback_mins


class _MassStatusNoneExecClientFactory(LiveExecClientFactory):
    @staticmethod
    def create(  # type: ignore[override]
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: object,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> _MassStatusNoneExecClient:
        del config
        return _MassStatusNoneExecClient(
            loop=loop,
            client_id=ClientId(name),
            msgbus=msgbus,
            cache=cache,
            clock=clock,
        )


class _HarnessNode(TradingNode):
    """Ignores the production factories ``trade_cli`` registers.

    The production factories open the venue. These tests keep the real kernel
    and substitute one Breezy-owned client through the same seam.
    """

    def __init__(
        self,
        config: Any,
        mode: _Mode,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        # Pass the loop in. Under pytest, TradingNode's fallback
        # ``get_event_loop()`` refuses to create one (the lifecycle contract
        # constructs its node the same way).
        super().__init__(config, loop=loop)
        self._boot_halt_mode = mode

    def add_data_client_factory(self, name: str, factory: type) -> None:
        del factory
        if self._boot_halt_mode is _Mode.ENGINES_NEVER_CONNECT:
            super().add_data_client_factory(name, _NeverConnectingDataClientFactory)
            return
        super().add_data_client_factory(name, _SilentDataClientFactory)

    def add_exec_client_factory(self, name: str, factory: type) -> None:
        del factory
        if self._boot_halt_mode is _Mode.RECONCILIATION_FAILS:
            super().add_exec_client_factory(name, _MassStatusNoneExecClientFactory)


def _request_stop(node: TradingNode) -> None:
    loop = node.kernel.loop

    def _schedule() -> None:
        loop.create_task(node.stop_async())

    loop.call_soon_threadsafe(_schedule)


def _plant_portfolio_that_cannot_initialise(node: TradingNode) -> None:
    """Leave ``portfolio.initialized`` false after ``_initialize_portfolio``.

    ``initialize_orders`` sets the flag false when an open order's instrument
    is missing, then ``initialize_positions`` (called next, kernel
    ``_initialize_portfolio``) assigns the flag again and sets it true when
    no position is open. An open position whose instrument was never added
    to the cache is what makes the second assignment stick at false. The
    instrument object exists only so ``Position`` can be constructed; it is
    not cached.
    """
    instrument = TestInstrumentProvider.default_fx_ccy("EUR/USD")
    orders = OrderFactory(
        trader_id=node.trader.id,
        strategy_id=StrategyId("BOOT-HALT-PROBE"),
        clock=node.kernel.clock,
    )
    order = orders.market(
        instrument_id=instrument.id,
        order_side=OrderSide.BUY,
        quantity=instrument.make_qty(1),
    )
    order.apply(TestEventStubs.order_submitted(order))
    order.apply(TestEventStubs.order_accepted(order))
    node.kernel.cache.add_order(order)
    node.kernel.cache.update_order(order)

    fill = TestEventStubs.order_filled(
        order,
        instrument,
        position_id=PositionId("P-BOOT-HALT"),
    )
    node.kernel.cache.add_position(Position(instrument, fill), OmsType.NETTING)


def _drive(
    mode: _Mode,
    *,
    until_running: bool,
    after_build: Any = None,
) -> tuple[int, str, bool | None]:
    observed: dict[str, Any] = {}
    holder: list[TradingNode] = []
    err = io.StringIO()

    def factory(config: Any) -> TradingNode:
        tuned = msgspec_replace(
            config,
            timeout_connection=_STARTUP_TIMEOUT_S,
            timeout_portfolio=_STARTUP_TIMEOUT_S,
        )
        loop = asyncio.new_event_loop()
        node = _HarnessNode(tuned, mode, loop)
        holder.append(node)
        return node

    def stopper() -> None:
        deadline = time.monotonic() + _DRIVE_DEADLINE_S
        while not holder and time.monotonic() < deadline:
            time.sleep(0.01)
        if not holder:
            return
        node = holder[0]
        while time.monotonic() < deadline:
            loop = getattr(getattr(node, "kernel", None), "loop", None)
            if loop is not None and loop.is_running():
                break
            time.sleep(0.01)
        else:
            return
        if until_running:
            while time.monotonic() < deadline and not node.trader.is_running:
                time.sleep(0.01)
        else:
            time.sleep(_HALT_SETTLE_S)
        try:
            observed["trader_running"] = bool(node.trader.is_running)
        except Exception as exc:  # noqa: BLE001 - recorded, asserted by the caller
            observed["trader_running_error"] = type(exc).__name__
        _request_stop(node)

    thread = threading.Thread(target=stopper, name="boot-halt-stopper", daemon=True)
    thread.start()
    code = run(env=TRADE_ENV, node_factory=factory, stderr=err, after_build=after_build)
    thread.join(timeout=5)
    return code, err.getvalue(), observed.get("trader_running")


def _boot_halt_details(sink: _RecordingAlertSink) -> list[str]:
    return [payload.detail for payload in sink.payloads if payload.event == _BOOT_HALT_EVENT]


def test_a_real_node_that_reaches_running_emits_no_boot_halt_alert(
    alert_sink: _RecordingAlertSink,
) -> None:
    """Positive control for the false-positive guard, on a real node.

    Same client wiring as ``test_the_trade_node_reaches_running_and_stops_cleanly``:
    a connecting data client and zero execution clients. The trader reaches
    RUNNING, so the post-run check must stay silent.
    """
    code, stderr, trader_running = _drive(_Mode.REACHES_RUNNING, until_running=True)

    assert code == EXIT_OK, stderr
    assert trader_running is True
    assert _boot_halt_details(alert_sink) == []


def test_engines_that_never_connect_halt_the_boot_with_the_engines_not_connected_detail(
    alert_sink: _RecordingAlertSink,
) -> None:
    code, stderr, trader_running = _drive(_Mode.ENGINES_NEVER_CONNECT, until_running=False)

    assert code == EXIT_OK, stderr
    # The halt is the kernel's: the trader never started. The alert does not
    # change that, and it does not change the process exit code.
    assert trader_running is False
    details = _boot_halt_details(alert_sink)
    assert details == [_DETAIL_ENGINES]
    assert alert_sink.payloads[0].severity == "CRITICAL"


def test_a_false_reconciliation_halts_the_boot_and_emits_a_critical_alert(
    alert_sink: _RecordingAlertSink,
) -> None:
    code, stderr, trader_running = _drive(_Mode.RECONCILIATION_FAILS, until_running=False)

    assert code == EXIT_OK, stderr
    assert trader_running is False
    details = _boot_halt_details(alert_sink)
    assert details == [_DETAIL_RECONCILIATION]
    assert alert_sink.payloads[0].severity == "CRITICAL"
    assert alert_sink.payloads[0].site == "global"
    assert len(alert_sink.payloads) == 1


def test_a_portfolio_that_never_initialises_halts_the_boot_with_the_portfolio_detail(
    alert_sink: _RecordingAlertSink,
) -> None:
    code, stderr, trader_running = _drive(
        _Mode.PORTFOLIO_NEVER_INITIALISES,
        until_running=False,
        after_build=_plant_portfolio_that_cannot_initialise,
    )

    assert code == EXIT_OK, stderr
    assert trader_running is False
    details = _boot_halt_details(alert_sink)
    assert details == [_DETAIL_PORTFOLIO]
    assert _DETAIL_RECONCILIATION not in details
