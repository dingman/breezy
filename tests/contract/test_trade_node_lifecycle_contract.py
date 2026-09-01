"""EXEC SPINE R-2: a REAL ``TradingNode`` on the trade config starts and stops.

The rest of the R-2 suite asserts properties of a config object and of an
entrypoint driving an injected double. Neither can answer the only question an
operator actually has: *does this process come up?* This file runs the genuine
``TradingNode`` that ``build_trade_node_config`` produces, on a real asyncio
loop, through ``build() -> run_async() -> RUNNING -> stop_async() -> STOPPED
-> dispose()``.

No live network. The one thing that cannot be exercised in-process is a real
socket, so the Polymarket.us data-client factory is replaced by a stub whose
``_connect``/``_disconnect`` are no-ops. Everything else -- the kernel, the
data engine, the risk engine, the LIVE execution engine, the message bus,
startup reconciliation, and shutdown -- is the shipped code path.

Two assertions here are made against the LIVE ENGINE rather than the config,
because a config value that the engine ignores is not a property of the
running system:

* ``LiveExecutionEngine.inflight_check_interval_ms == 0``;
* no ``continuous_reconciliation`` task exists on the loop
  (``live/execution_engine.py:383-386`` schedules it only when at least one of
  the three intervals is truthy). Polymarket.us has no client-order-id, so an
  engine that re-queries or self-resolves orders by id has nothing sound to
  act on.

And one asserts the increment's boundary: the running node has **zero
registered execution clients**. R-2 cannot submit an order.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.config import LiveDataClientConfig
from nautilus_trader.live.data_client import LiveMarketDataClient
from nautilus_trader.live.factories import LiveDataClientFactory
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import ClientId

from breezy.adapters.polymarket_us.factories import POLYMARKET_US_CLIENT_NAME
from breezy.adapters.polymarket_us.safety import MAX_ORDER_NOTIONAL_USD_ENV_VAR
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.runtime.node_config import build_trade_node_config
from tests.unit.test_runtime_trade_node_config import (
    make_data_client_config,
    make_trade_settings,
)

pytestmark = pytest.mark.contract

_WAIT_TIMEOUT_S = 30.0
_POLL_S = 0.01


#: Test-local stand-in for the operator's per-order USD ceiling
#: (`BREEZY_MAX_ORDER_NOTIONAL_USD`). `build_trade_node_config` configures the
#: NATIVE per-order notional cap from that control and FAILS CLOSED when it is
#: absent, so every builder call in this module needs it present. The number is
#: arbitrary and test-local: it is not a production risk setting, and it is not
#: either operator-reserved control (max daily budget, max per position),
#: neither of which is read, defaulted or inferred anywhere on this path. The
#: refusal itself is covered by
#: `tests/contract/test_native_order_cap_wiring.py`, which is where it belongs.
OPERATOR_ORDER_CEILING_USD = "25"


@pytest.fixture(autouse=True)
def _operator_order_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, OPERATOR_ORDER_CEILING_USD)


class _SilentDataClient(LiveMarketDataClient):
    """A real ``LiveMarketDataClient`` that opens nothing.

    Substituted for the venue client so this test exercises the node lifecycle
    rather than the venue transport. It implements only the two lifecycle
    coroutines the kernel drives; every subscription coroutine is left
    unimplemented, because nothing in this test subscribes.
    """

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
        return _SilentDataClient(
            loop=loop,
            client_id=ClientId(name),
            venue=POLYMARKET_US_VENUE,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=InstrumentProvider(),
        )


async def _wait_until(predicate: Any, timeout: float = _WAIT_TIMEOUT_S) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError("timed out waiting for the node lifecycle to advance")
        await asyncio.sleep(_POLL_S)


@pytest.fixture(name="node")
def _node() -> Iterator[TradingNode]:
    config = build_trade_node_config(make_trade_settings(), make_data_client_config())
    loop = asyncio.new_event_loop()
    node = TradingNode(config, loop=loop)
    try:
        yield node
    finally:
        loop.close()


def test_the_trade_node_reaches_running_and_stops_cleanly() -> None:
    """The whole increment, in one run: START -> RUNNING -> STOPPED -> DISPOSED.

    Observations are RECORDED during the run and asserted afterwards, rather
    than asserted inline. An ``AssertionError`` raised inside the driving
    coroutine would abandon a running node on a live loop, and the resulting
    teardown noise buries the real cause -- which is precisely the failure
    shape this repo has been burned by before.
    """
    config = build_trade_node_config(make_trade_settings(), make_data_client_config())
    loop = asyncio.new_event_loop()
    node = TradingNode(config, loop=loop)
    node.add_data_client_factory(POLYMARKET_US_CLIENT_NAME, _SilentDataClientFactory)
    node.build()

    seen: dict[str, Any] = {}

    async def _drive() -> None:
        task = asyncio.create_task(node.run_async())
        try:
            await _wait_until(lambda: node.trader.is_running)
            seen["running"] = node.trader.is_running

            # The increment's boundary, observed on the RUNNING system: there
            # is no execution client, so there is no order path.
            seen["exec_clients"] = list(node.kernel.exec_engine.registered_clients)

            # Observed on the live ENGINE, not on the config object: a config
            # value the engine ignores is not a property of the running system.
            seen["inflight_ms"] = node.kernel.exec_engine.inflight_check_interval_ms
            seen["task_names"] = {t.get_name() for t in asyncio.all_tasks()}

            await node.stop_async()
            await _wait_until(lambda: node.trader.is_stopped)
            seen["stopped"] = node.trader.is_stopped

            # `run_async` must return on its own once the stop cancels the
            # engine queue tasks it gathers. A run task that outlives
            # `stop_async` is a process systemd cannot stop.
            await asyncio.wait_for(task, timeout=_WAIT_TIMEOUT_S)
        finally:
            if not task.done():  # pragma: no cover - only on a failed stop
                task.cancel()

    try:
        loop.run_until_complete(_drive())
    finally:
        # AFTER the loop work: `dispose` stops the loop, so anything awaited
        # past this point never completes.
        node.dispose()
        if not loop.is_closed():
            loop.close()

    assert seen["running"] is True
    assert seen["stopped"] is True
    assert seen["exec_clients"] == []
    assert seen["inflight_ms"] == 0
    # `live/execution_engine.py:383-386` names this task and creates it only
    # when one of the three reconciliation intervals is truthy.
    assert "continuous_reconciliation" not in seen["task_names"]


def test_the_built_node_registers_one_data_client_and_zero_exec_clients(
    node: TradingNode,
) -> None:
    """``build()`` alone, no loop run: the wiring is what is under test here."""
    node.add_data_client_factory(POLYMARKET_US_CLIENT_NAME, _SilentDataClientFactory)
    node.build()

    # `registered_clients` yields `ClientId`s, not client objects.
    assert [str(c) for c in node.kernel.data_engine.registered_clients] == [
        POLYMARKET_US_CLIENT_NAME
    ]
    assert node.kernel.exec_engine.registered_clients == []

    node.dispose()
