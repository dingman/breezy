"""EXEC SPINE R-2: the ``breezy-trade`` process entrypoint.

A node config nothing constructs is this repo's standing failure mode: green
suite, dead deployment. These tests drive the actual entrypoint the console
script calls, with ``TradingNode`` injected so nothing opens a socket.

The load-bearing assertions are the ones about ABSENCE. R-2 is config and
process only: the trading process must be **structurally incapable of
submitting an order**. So this file asserts, on the real entrypoint:

* zero execution-client factories are registered, ever;
* the built config carries no exec client, no strategy and no exec algorithm;
* the entrypoint's own source contains no execution-registration call at all,
  so the property cannot be quietly undone by a later edit that the
  behavioural tests happen not to reach.

The exit contract mirrors ``breezy.runtime.quote_tape_cli``: 0 clean, 1
runtime failure (including a LATCHED market-data fault behind an otherwise
clean stop), 2 misconfiguration.
"""

from __future__ import annotations

import ast
import io
import os
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.common.enums import ComponentState
from nautilus_trader.common.messages import ComponentStateChanged
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce, TradingState
from nautilus_trader.model.events import OrderInitialized
from nautilus_trader.model.identifiers import (
    ClientId,
    ClientOrderId,
    ComponentId,
    InstrumentId,
    StrategyId,
    Symbol,
    TraderId,
    Venue,
)
from nautilus_trader.model.objects import Quantity

from breezy.adapters.polymarket_us import exec_fault, feed_fault
from breezy.adapters.polymarket_us.factories import (
    POLYMARKET_US_CLIENT_NAME,
    PolymarketUSLiveDataClientFactory,
    PolymarketUSLiveExecClientFactory,
)
from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
)
from breezy.adapters.polymarket_us.safety import MAX_ORDER_NOTIONAL_USD_ENV_VAR
from breezy.runtime import trade_cli
from breezy.runtime.backtest_order_guard import ORDER_EVENT_TOPIC, NakedShortRefusedError
from breezy.runtime.component_health_watch import (
    COMPONENT_STATE_TOPIC,
    REFUSAL_REPOLL_INTERVAL,
    REFUSAL_REPOLL_TIMER_NAME,
)
from breezy.runtime.health import AlertPayload
from breezy.runtime.settings import LIVE_OBSERVATIONS_VAR, TRADE_TRADER_ID_VAR
from breezy.runtime.stop_intent_marker import stop_intent_marker_path, write_stop_intent_marker
from breezy.runtime.trade_cli import (
    EXIT_CONFIG_ERROR,
    EXIT_OK,
    EXIT_RUNTIME_ERROR,
    run,
)
from tests.unit.operator_control_env import operator_control_env, operator_control_unset

#: A synthetic instrument for RED-13's directly-constructed refusable event.
_GUARD_TEST_INSTRUMENT = InstrumentId(
    Symbol("synthetic-trade-cli-guard-market"), Venue("POLYMARKET_US")
)

#: What a provisioned trading host carries. Venue values are `.invalid` hosts;
#: nothing in this file performs network I/O.
TRADE_ENV: dict[str, str] = {
    TRADE_TRADER_ID_VAR: "BREEZYTRADE-001",
    # Security finding M2: these test-double origins sit off the venue domain,
    # so the environment must declare that deliberately, as a real run would.
    "POLYMARKET_US_ALLOW_FOREIGN_ORIGIN": "1",
    "POLYMARKET_US_API_BASE": "https://api.example.invalid",
    "POLYMARKET_US_GATEWAY_BASE": "https://gateway.example.invalid",
    "POLYMARKET_US_WS_URL": "wss://ws.example.invalid",
    "POLYMARKET_US_USER_AGENT": "breezy-test/1.0 (+mailto:ops@example.invalid)",
    # EXEC SPINE W: `exec_config_from_env`'s two REQUIRED, venue-specific
    # variables (OQ-I; see `factories.py`'s own doc comments on both).
    "POLYMARKET_US_ACCOUNT_NUMBER": "001",
    "POLYMARKET_US_EXEC_STATE_DB": "/tmp/breezy-trade-cli-test-exec-state.db",
}


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


class _FakeMsgBus:
    """Stands in for the ONE surface R-6a's installer uses: ``subscribe``."""

    def __init__(self) -> None:
        self.subscriptions: list[tuple[str, Any]] = []

    def subscribe(self, *, topic: str, handler: Any) -> None:
        self.subscriptions.append((topic, handler))


class _FakeGuardPortfolio:
    """Enough of ``Portfolio`` for R-6a's guard to actually evaluate an event."""

    def net_position(self, instrument_id: InstrumentId) -> Decimal:
        del instrument_id
        return Decimal(0)


class _FakeGuardCache:
    """Enough of ``CacheFacade`` for R-6a's guard to actually evaluate an event.

    ``orders``, not ``orders_open`` -- the guard reads ``cache.orders(...)``
    since ``docs/plans/ORDER_LIST_BYPASS_2026-09-02.md`` Increment 1 (§2).

    ``order`` is Increment 2's addition (§6): the naked short driven through
    here is always against a net of 0, so it is refused and the guard never
    records a shim entry -- ``None`` unconditionally is correct.
    """

    #: A stand-in for a cached ``Account``. Only its NULLITY is ever read.
    account: ClassVar[object] = object()

    def orders(self, *, instrument_id: InstrumentId | None = None) -> tuple[Any, ...]:
        del instrument_id
        return ()

    def order(self, client_order_id: ClientOrderId) -> None:
        del client_order_id

    def account_for_venue(self, venue: Venue) -> object | None:
        """R-7-PRE's addition: the guard asks whether an account is cached.

        Returns a NON-``None`` sentinel by default -- "the account is there" --
        so every test above keeps measuring what it measured before R-7-PRE
        existed. ``_FakeAccountlessKernel`` below is the variant that answers
        ``None``, and it is the only place the halt can fire.
        """
        del venue
        return self.account


class _FakeAccountlessGuardCache(_FakeGuardCache):
    """The cache mid-race: instruments known, no ``AccountState`` yet."""

    def account_for_venue(self, venue: Venue) -> object | None:
        del venue
        return None


class _FakeRiskEngine:
    """Stands in for the ONE surface R-7-PRE's guard uses: ``set_trading_state``."""

    def __init__(self) -> None:
        self.states: list[TradingState] = []

    def set_trading_state(self, state: TradingState) -> None:
        self.states.append(state)


class _SilentExecEngine:
    """Enough of the exec engine for the stale-intent reader to find no client."""

    def __init__(self) -> None:
        self._clients: dict[object, object] = {}


class _InlineLoop:
    """FU-8b: fakes the loop-hop surface `_run_node` reads off `node.kernel.loop`
    -- `is_closed()` and `call_soon_threadsafe`. Calls the callback INLINE,
    on the same thread, since every fake `TestClock` in this module fires
    inline too (`TestClock.advance_time`); the genuine cross-thread hop is
    proven separately under a real `LiveClock` and a real asyncio loop in
    `tests/contract/test_refusal_repoll_live_clock_contract.py`.
    """

    def __init__(self) -> None:
        self.closed = False

    def is_closed(self) -> bool:
        return self.closed

    def call_soon_threadsafe(self, callback: Any, *args: Any) -> None:
        callback(*args)


class _FakeKernel:
    """Stands in for the slice of ``NautilusKernel`` R-6a's/R-7-PRE's guards read."""

    cache_type: ClassVar[type[_FakeGuardCache]] = _FakeGuardCache

    def __init__(self) -> None:
        self.portfolio = _FakeGuardPortfolio()
        self.cache = self.cache_type()
        self.msgbus = _FakeMsgBus()
        self.risk_engine = _FakeRiskEngine()
        self.exec_engine = _SilentExecEngine()
        # WP-B2 widens the slice the guards read by one attribute: the
        # kernel's own clock, which `_run_node` hands the order guard so a
        # lapsed `OrderSubmissionPermit` is refused at submit. A REAL
        # Nautilus `TestClock`, not a stub -- `NautilusKernel.clock` returns
        # a `Clock` (`system/kernel.py`), and the point of this fake is to
        # stand in for that slice faithfully.
        self.clock = TestClock()
        # FU-8b: `_run_node` now also reads `node.kernel.loop` to arm the
        # refusal re-poll timer's loop-thread hop. Without this, every test
        # in this module would take the `NOT armed` path once that read
        # lands (`AttributeError` on a bare fake).
        self.loop = _InlineLoop()


class _FakeAccountlessKernel(_FakeKernel):
    """A kernel whose cache has no account -- R-7-PRE's hazard, reproduced."""

    cache_type: ClassVar[type[_FakeGuardCache]] = _FakeAccountlessGuardCache


class _RecordingTrader:
    """Stands in for ``Trader``; records the Actors registered natively on it."""

    def __init__(self, calls: list[str], trader_id: TraderId) -> None:
        self.id = trader_id
        self.actors: list[Any] = []
        self.strategies: list[Any] = []
        self._calls = calls

    def add_actor(self, actor: Any) -> None:
        self.actors.append(actor)
        self._calls.append("add_actor")

    def add_strategy(self, strategy: Any) -> None:
        self.strategies.append(strategy)
        self._calls.append("add_strategy")


class RecordingNode:
    """Stands in for ``TradingNode``; records the wiring calls made on it."""

    instances: ClassVar[list[RecordingNode]] = []

    def __init__(self, config: Any) -> None:
        self.config = config
        self.data_client_factories: list[tuple[str, type]] = []
        self.exec_client_factories: list[tuple[str, type]] = []
        self.calls: list[str] = []
        self.kernel = _FakeKernel()
        self.trader = _RecordingTrader(self.calls, config.trader_id)
        RecordingNode.instances.append(self)

    def add_data_client_factory(self, name: str, factory: type) -> None:
        self.data_client_factories.append((name, factory))

    def add_exec_client_factory(self, name: str, factory: type) -> None:  # pragma: no cover
        self.exec_client_factories.append((name, factory))

    def build(self) -> None:
        self.calls.append("build")

    def run(self) -> None:
        self.calls.append("run")

    def dispose(self) -> None:
        self.calls.append("dispose")


class RaisingNode(RecordingNode):
    def run(self) -> None:
        self.calls.append("run")
        raise RuntimeError("the socket exploded")


class InterruptedNode(RecordingNode):
    def run(self) -> None:
        self.calls.append("run")
        raise KeyboardInterrupt


class FeedLostNode(RecordingNode):
    """A run that ended because the data client gave up on the feed.

    From the CLI's side this is indistinguishable from a SIGTERM: the kernel
    handled ``ShutdownSystem``, stopped cleanly, and ``run()`` returned. Only
    the process-scoped latch carries the reason.
    """

    def run(self) -> None:
        self.calls.append("run")
        feed_fault.record_fatal_feed_fault(
            "POLYMARKET_US", "markets feed lost and not recoverable"
        )


class _RecordingAlertSink:
    """Captures alert payloads. Never opens a socket."""

    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


@pytest.fixture(autouse=True)
def _no_send_alert_sink(monkeypatch: pytest.MonkeyPatch) -> Iterator[_RecordingAlertSink]:
    """Every ``run()`` in this module resolves the alert sink through here.

    A boot that never publishes trader ``RUNNING`` emits after the feature
    lands. The real ``resolve_alert_sink`` would build a webhook client when
    ``BREEZY_ALERT_WEBHOOK_URL`` is set. This module must not do that.
    """
    sink = _RecordingAlertSink()
    monkeypatch.setattr(trade_cli, "resolve_alert_sink", lambda: sink, raising=False)
    yield sink


@pytest.fixture(autouse=True)
def _clean_process_state() -> Iterator[None]:
    RecordingNode.instances.clear()
    feed_fault.clear_fatal_feed_fault()
    exec_fault.clear_fatal_exec_fault()
    yield
    RecordingNode.instances.clear()
    feed_fault.clear_fatal_feed_fault()
    exec_fault.clear_fatal_exec_fault()


# ---------------------------------------------------------------------------
# Starting and stopping
# ---------------------------------------------------------------------------


def test_a_complete_environment_builds_runs_and_disposes_the_node() -> None:
    err = io.StringIO()

    code = run(env=TRADE_ENV, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_OK
    assert err.getvalue() == ""
    assert RecordingNode.instances[0].calls == ["build", "run", "dispose"]


def test_exactly_one_data_client_factory_is_registered_under_the_routing_name() -> None:
    """The registration name and the ``data_clients`` key must be one string.

    ``live/node_builder.py:163,177`` resolves the client by that name; a
    mismatch registers nothing, raises nothing, and trades on no data.
    """
    run(env=TRADE_ENV, node_factory=RecordingNode, stderr=io.StringIO())
    node = RecordingNode.instances[0]

    assert node.data_client_factories == [
        (POLYMARKET_US_CLIENT_NAME, PolymarketUSLiveDataClientFactory)
    ]
    assert set(node.config.data_clients) == {POLYMARKET_US_CLIENT_NAME}


def test_exactly_one_execution_client_factory_is_registered_under_the_routing_name() -> None:
    """EXEC SPINE W. R-4's client had ZERO construction sites before this;
    the trading process now registers it, under the SAME routing name the
    data client uses -- and still declares no strategy and no exec algorithm,
    so nothing on this path can originate an order."""
    run(env=TRADE_ENV, node_factory=RecordingNode, stderr=io.StringIO())
    node = RecordingNode.instances[0]

    assert node.exec_client_factories == [
        (POLYMARKET_US_CLIENT_NAME, PolymarketUSLiveExecClientFactory)
    ]
    assert set(node.config.exec_clients) == {POLYMARKET_US_CLIENT_NAME}
    assert node.config.strategies == []
    assert node.config.exec_algorithms == []


def test_the_stale_intent_watch_is_installed_beside_the_degraded_alert() -> None:
    """2026-09-11 incident addendum, item 3: `install_stale_intent_alert`
    rides the SAME `COMPONENT_STATE_TOPIC` heartbeat
    `install_component_degraded_alert` already subscribes -- one wiring
    idiom, not a second timer. The boot-halt check is not a third
    subscriber and not a timer: it reads the trader once after ``run()``.
    Nothing else in `_run_node` uses this topic (the order guard and the
    account presence halt both subscribe `ORDER_EVENT_TOPIC` instead).

    AUD-13b adds the third: `install_reconciliation_refusal_alert`, the SAME
    idiom again -- the kernel publishes the OrderEmulator/trader RUNNING
    transitions after the startup reconciliation returns, so the first poll
    after the pass sees its latched refusals. Still no timer.

    EDGE-2 slice D (silent-failure review, 75b9008) adds the fourth:
    `install_resolver_contradiction_alert`, the SAME idiom again, delivering
    `resolver_evidence_contradictions` -- a detector with no subscriber is
    not a control."""
    run(env=TRADE_ENV, node_factory=RecordingNode, stderr=io.StringIO())
    node = RecordingNode.instances[0]

    component_state_subscribers = [
        handler
        for topic, handler in node.kernel.msgbus.subscriptions
        if topic == COMPONENT_STATE_TOPIC
    ]
    assert len(component_state_subscribers) == 4, node.kernel.msgbus.subscriptions


def test_the_reconciliation_refusal_reader_reads_the_exec_client_surface() -> None:
    """AUD-13b: the reader resolves the exec client at POLL time and reads its
    read-only `reconciliation_refusals`; a missing client or a client without
    the attribute yields `()`, never a raise inside a bus handler."""
    refusal = {"event": "reconciliation_refusal", "detail": "POSITIONS_READ_FAILED",
               "latch": "positions_read_failed", "subject": ""}
    client = SimpleNamespace(reconciliation_refusals=(refusal,))
    clients: dict[object, object] = {}
    node = SimpleNamespace(kernel=SimpleNamespace(exec_engine=SimpleNamespace(_clients=clients)))
    read = trade_cli._exec_client_reconciliation_refusal_reader(node)

    assert read() == ()
    clients[ClientId(POLYMARKET_US_CLIENT_NAME)] = SimpleNamespace()
    assert read() == ()
    clients[ClientId(POLYMARKET_US_CLIENT_NAME)] = client
    assert read() == (refusal,)


def test_the_resolver_contradiction_reader_reads_the_exec_client_surface() -> None:
    """EDGE-2 slice D (silent-failure review, 75b9008): the reader resolves
    the exec client at POLL time and reads its read-only
    `resolver_evidence_contradictions`; a missing client or a client without
    the attribute yields `()`, never a raise inside a bus handler -- same
    shape as `_exec_client_reconciliation_refusal_reader` immediately
    above."""
    contradiction = {
        "severity": "CRITICAL", "event": "resolver_evidence_contradiction", "site": "global",
        "intent_id": "intent-1", "venue_order_id": "vo-1", "trade_count": "1",
        "create_fill_evidence": "none",
    }
    client = SimpleNamespace(resolver_evidence_contradictions=(contradiction,))
    clients: dict[object, object] = {}
    node = SimpleNamespace(kernel=SimpleNamespace(exec_engine=SimpleNamespace(_clients=clients)))
    read = trade_cli._exec_client_resolver_contradiction_reader(node)

    assert read() == ()
    clients[ClientId(POLYMARKET_US_CLIENT_NAME)] = SimpleNamespace()
    assert read() == ()
    clients[ClientId(POLYMARKET_US_CLIENT_NAME)] = client
    assert read() == (contradiction,)


def test_the_entrypoint_source_registers_no_strategy_or_exec_algorithm_or_raw_submit() -> None:
    """Structural, not behavioural -- and deliberately so.

    The behavioural test above proves this run registered an exec CLIENT. It
    cannot prove a *conditional* registration of a strategy or exec algorithm
    on a branch the test does not take. Reading the source closes that gap:
    ``submit_order`` and ``add_exec_algorithm`` stay unwritten. ``add_strategy``
    is the native registration of already-constructed shadow-mode strategies
    (``orders_enabled`` stays False) and is not an order path.
    ``add_exec_client_factory`` is deliberately NOT asserted absent here --
    EXEC SPINE W adds it, on purpose, in the behavioural test above.
    """
    source = Path(trade_cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "submit_order" not in called
    assert "add_exec_algorithm" not in called
    # Native registration of already-constructed shadow-mode strategies
    # (``orders_enabled`` stays False). Not an order path.
    assert "add_strategy" in called


def test_ctrl_c_is_a_clean_shutdown_not_a_runtime_failure() -> None:
    """A deliberate stop must exit 0.

    ``TradingNode.run`` catches only ``RuntimeError`` (``live/node.py:293-300``)
    and the kernel installs SIGINT/SIGTERM handlers for a LIVE environment
    (``system/kernel.py:558-572``) -- but a signal arriving during ``build()``,
    or between ``build()`` and ``run()``, surfaces here as
    ``KeyboardInterrupt``. Under systemd that is the difference between
    "stopped" and "failed".
    """
    err = io.StringIO()

    code = run(env=TRADE_ENV, node_factory=InterruptedNode, stderr=err)

    assert code == EXIT_OK
    assert RecordingNode.instances[0].calls == ["build", "run", "dispose"]
    assert "failed" not in err.getvalue().lower()


def test_a_runtime_failure_exits_one_and_still_disposes_the_node() -> None:
    err = io.StringIO()

    code = run(env=TRADE_ENV, node_factory=RaisingNode, stderr=err)

    assert code == EXIT_RUNTIME_ERROR
    assert "the socket exploded" in err.getvalue()
    assert RecordingNode.instances[0].calls == ["build", "run", "dispose"]


# ---------------------------------------------------------------------------
# The latched fault
# ---------------------------------------------------------------------------


def test_a_latched_fault_exits_non_zero_behind_an_otherwise_clean_stop() -> None:
    err = io.StringIO()

    code = run(env=TRADE_ENV, node_factory=FeedLostNode, stderr=err)

    assert code == EXIT_RUNTIME_ERROR
    assert code != EXIT_OK
    assert "feed" in err.getvalue().lower()


def test_a_latched_fault_still_disposes_the_node() -> None:
    run(env=TRADE_ENV, node_factory=FeedLostNode, stderr=io.StringIO())

    assert RecordingNode.instances[0].calls == ["build", "run", "dispose"]


def test_a_clean_stop_with_no_fault_exits_zero() -> None:
    err = io.StringIO()

    code = run(env=TRADE_ENV, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_OK
    assert err.getvalue() == ""


def test_a_stale_fault_from_an_earlier_run_cannot_fail_a_healthy_one() -> None:
    """The latch is process-scoped and cleared at entry: it reports THIS run."""
    feed_fault.record_fatal_feed_fault("POLYMARKET_US", "a fault from before this run")
    err = io.StringIO()

    code = run(env=TRADE_ENV, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_OK


def test_a_ctrl_c_after_a_latched_fault_is_still_a_failed_run() -> None:
    """Reporting the interrupt would hide the cause."""

    class FaultThenInterruptNode(RecordingNode):
        def run(self) -> None:
            self.calls.append("run")
            feed_fault.record_fatal_feed_fault("POLYMARKET_US", "feed lost")
            raise KeyboardInterrupt

    err = io.StringIO()

    code = run(env=TRADE_ENV, node_factory=FaultThenInterruptNode, stderr=err)

    assert code == EXIT_RUNTIME_ERROR


# ---------------------------------------------------------------------------
# EXEC SPINE W, risk 2 -- the latched EXECUTION fault, done-predicate clause 7
# ---------------------------------------------------------------------------


class ExecFaultNode(RecordingNode):
    """A run whose execution client failed to connect -- exactly what a
    real ``_connect`` failure leaves behind: an otherwise clean stop, with
    the ONLY evidence in the process-scoped exec-fault latch (see
    ``exec/client.py``'s wrapped ``_connect`` and
    ``tests/unit/test_polymarket_us_exec_client.py::test_a_failed_connect_is_observable_and_does_not_exit_zero``
    for the client-side half of this exact chain).
    """

    def run(self) -> None:
        self.calls.append("run")
        exec_fault.record_fatal_exec_fault("POLYMARKET_US", "_connect failed: PermissionError")


def test_a_latched_execution_fault_is_reported_as_a_runtime_failure() -> None:
    """Without this check the process would exit `EXIT_OK` having never
    reconciled and never traded -- see `_exit_code_for_completed_run`'s own
    docstring for the full native chain that makes this silent otherwise."""
    err = io.StringIO()

    code = run(env=TRADE_ENV, node_factory=ExecFaultNode, stderr=err)

    assert code == EXIT_RUNTIME_ERROR
    assert code != EXIT_OK
    assert "execution-client" in err.getvalue().lower()


def test_a_latched_execution_fault_still_disposes_the_node() -> None:
    run(env=TRADE_ENV, node_factory=ExecFaultNode, stderr=io.StringIO())

    assert RecordingNode.instances[0].calls == ["build", "run", "dispose"]


def test_a_stale_execution_fault_from_an_earlier_run_cannot_fail_a_healthy_one() -> None:
    """The latch is process-scoped and cleared at entry: it reports THIS run."""
    exec_fault.record_fatal_exec_fault("POLYMARKET_US", "a fault from before this run")
    err = io.StringIO()

    code = run(env=TRADE_ENV, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_OK


def test_an_execution_fault_is_checked_before_a_feed_fault() -> None:
    """Both latched is an edge case, not a real scenario -- but the exec
    fault is the more actionable of the two (nothing reconciled at all), so
    it is reported first when both happen to be set."""

    class BothFaultsNode(RecordingNode):
        def run(self) -> None:
            self.calls.append("run")
            feed_fault.record_fatal_feed_fault("POLYMARKET_US", "feed lost")
            exec_fault.record_fatal_exec_fault("POLYMARKET_US", "_connect failed")

    err = io.StringIO()

    code = run(env=TRADE_ENV, node_factory=BothFaultsNode, stderr=err)

    assert code == EXIT_RUNTIME_ERROR
    assert "execution-client" in err.getvalue().lower()


# ---------------------------------------------------------------------------
# R-6a §4: a live order-guard refusal is reported to the operator, end to end
# ---------------------------------------------------------------------------


def test_trade_cli_writes_the_refusal_to_stderr_and_latches_it() -> None:
    """RED-13. Drives a naked short through the handler R-6a's installer
    actually subscribed onto ``_FakeMsgBus``, then asserts the operator
    signal end to end: the stderr line is written AT REFUSAL TIME (not only
    via the latch), ``fatal_exec_fault()`` is populated, and
    ``_exit_code_for_completed_run`` reports ``EXIT_RUNTIME_ERROR``.
    """
    err = io.StringIO()
    code = run(env=TRADE_ENV, node_factory=RecordingNode, stderr=err)
    assert code == EXIT_OK  # the fake node's own `run()` published nothing

    node = RecordingNode.instances[0]
    _, handler = node.kernel.msgbus.subscriptions[0]
    naked_short = OrderInitialized(
        trader_id=TraderId("BREEZYTRADE-001"),
        strategy_id=StrategyId("EXTERNAL"),
        instrument_id=_GUARD_TEST_INSTRUMENT,
        client_order_id=ClientOrderId("O-1"),
        order_side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Quantity(500, 0),
        time_in_force=TimeInForce.GTC,
        post_only=False,
        reduce_only=False,
        quote_quantity=False,
        options={},
        emulation_trigger=0,
        trigger_instrument_id=None,
        contingency_type=0,
        order_list_id=None,
        linked_order_ids=None,
        parent_order_id=None,
        exec_algorithm_id=None,
        exec_algorithm_params=None,
        exec_spawn_id=None,
        tags=None,
        event_id=UUID4(),
        ts_init=0,
    )

    with pytest.raises(NakedShortRefusedError):
        handler(naked_short)

    assert "breezy-trade: FATAL order-guard refusal" in err.getvalue()
    fault = exec_fault.fatal_exec_fault()
    assert fault is not None
    assert trade_cli._exit_code_for_completed_run(err) == EXIT_RUNTIME_ERROR


# ---------------------------------------------------------------------------
# R-7-PRE: a node whose account never arrived halts itself, end to end
# ---------------------------------------------------------------------------


class AccountlessNode(RecordingNode):
    """A node mid-race: built and wired, but no ``AccountState`` cached yet."""

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self.kernel = _FakeAccountlessKernel()


def test_trade_cli_halts_the_risk_engine_when_no_account_is_cached() -> None:
    """R-7-PRE, driven through the handler the CLI itself subscribed.

    Nautilus's ``_check_orders_risk_for_account`` returns ``True`` -- order
    ALLOWED -- while ``cache.account_for_venue(...)`` is ``None``, and Nautilus
    is immutable, so the denial has to be the native ``TradingState.HALTED``.
    This asserts the CLI wires the thing that enters that state: a BUY (so
    R-6a's naked-short rule is not what fires) with no account cached leaves
    the risk engine HALTED, the operator told, and the run unable to report
    success.
    """
    err = io.StringIO()
    code = run(env=TRADE_ENV, node_factory=AccountlessNode, stderr=err)
    assert code == EXIT_OK  # the fake node's own `run()` published nothing

    node = RecordingNode.instances[0]
    order_handlers = [
        handler for topic, handler in node.kernel.msgbus.subscriptions if topic == ORDER_EVENT_TOPIC
    ]
    assert len(order_handlers) == 2, "R-6a's guard and R-7-PRE's halt, both wired"

    initialized = OrderInitialized(
        trader_id=TraderId("BREEZYTRADE-001"),
        strategy_id=StrategyId("EXTERNAL"),
        instrument_id=_GUARD_TEST_INSTRUMENT,
        client_order_id=ClientOrderId("O-ACCOUNTLESS-1"),
        order_side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Quantity(1, 0),
        time_in_force=TimeInForce.GTC,
        post_only=False,
        reduce_only=False,
        quote_quantity=False,
        options={},
        emulation_trigger=0,
        trigger_instrument_id=None,
        contingency_type=0,
        order_list_id=None,
        linked_order_ids=None,
        parent_order_id=None,
        exec_algorithm_id=None,
        exec_algorithm_params=None,
        exec_spawn_id=None,
        tags=None,
        event_id=UUID4(),
        ts_init=0,
    )
    for handler in order_handlers:
        handler(initialized)

    assert node.kernel.risk_engine.states == [TradingState.HALTED]
    assert "breezy-trade: FATAL account-presence halt" in err.getvalue()
    fault = exec_fault.fatal_exec_fault()
    assert fault is not None
    assert trade_cli._exit_code_for_completed_run(err) == EXIT_RUNTIME_ERROR


def test_a_cached_account_leaves_the_risk_engine_active() -> None:
    """The mitigation is account-CONDITIONAL, not a second blanket refusal.

    Identical event, identical wiring, an account in the cache: the trading
    state is untouched and the operator is told nothing.
    """
    err = io.StringIO()
    run(env=TRADE_ENV, node_factory=RecordingNode, stderr=err)

    node = RecordingNode.instances[0]
    order_handlers = [
        handler for topic, handler in node.kernel.msgbus.subscriptions if topic == ORDER_EVENT_TOPIC
    ]
    initialized = OrderInitialized(
        trader_id=TraderId("BREEZYTRADE-001"),
        strategy_id=StrategyId("EXTERNAL"),
        instrument_id=_GUARD_TEST_INSTRUMENT,
        client_order_id=ClientOrderId("O-ACCOUNTED-1"),
        order_side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        quantity=Quantity(1, 0),
        time_in_force=TimeInForce.GTC,
        post_only=False,
        reduce_only=False,
        quote_quantity=False,
        options={},
        emulation_trigger=0,
        trigger_instrument_id=None,
        contingency_type=0,
        order_list_id=None,
        linked_order_ids=None,
        parent_order_id=None,
        exec_algorithm_id=None,
        exec_algorithm_params=None,
        exec_spawn_id=None,
        tags=None,
        event_id=UUID4(),
        ts_init=0,
    )
    for handler in order_handlers:
        handler(initialized)

    assert node.kernel.risk_engine.states == []
    assert "account-presence halt" not in err.getvalue()
    assert exec_fault.fatal_exec_fault() is None


# ---------------------------------------------------------------------------
# Misconfiguration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        TRADE_TRADER_ID_VAR,
        "POLYMARKET_US_USER_AGENT",
        # EXEC SPINE W, OQ-I: no default, no fallback, no derivation.
        "POLYMARKET_US_ACCOUNT_NUMBER",
        "POLYMARKET_US_EXEC_STATE_DB",
    ],
)
def test_every_missing_required_variable_exits_two_and_names_itself(name: str) -> None:
    env = dict(TRADE_ENV)
    del env[name]
    err = io.StringIO()

    code = run(env=env, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_CONFIG_ERROR
    assert name in err.getvalue()
    assert RecordingNode.instances == [], "no node is built from a bad environment"


def test_a_host_provisioned_only_for_weather_ingest_cannot_start_the_trader() -> None:
    """Role separation, in the fail-closed direction.

    ``BREEZY_TRADER_ID`` is the COLLECTOR's variable and carries a default.
    If it satisfied the trading role, a weather host would start a trading
    process under the collector's identity.
    """
    err = io.StringIO()

    code = run(
        env={"BREEZY_TRADER_ID": "BREEZY-001", "BREEZY_SITES": "KNYC:nyc"},
        node_factory=RecordingNode,
        stderr=err,
    )

    assert code == EXIT_CONFIG_ERROR
    assert TRADE_TRADER_ID_VAR in err.getvalue()
    assert RecordingNode.instances == []


def test_a_missing_operator_order_ceiling_is_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operator ruling 2026-09-10: a missing per-order session ceiling
    derives from the per-position cap. When that cap is also absent the
    process still starts NOTHING -- never uncapped -- and the refusal
    names the missing cap, not a traceback.

    This routes correctly with no change to `_CONFIG_ERRORS`:
    `LiveTradingPermissionError` subclasses `PermissionError`, which
    subclasses `OSError`, which that tuple already names. Asserted rather than
    assumed -- narrowing `OSError` there later would silently turn this
    refusal into an exit-1 crash report.
    """
    monkeypatch.delenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, raising=False)
    err = io.StringIO()

    with (
        operator_control_unset(MAX_DAILY_BUDGET_USD_ENV_VAR),
        operator_control_unset(MAX_POSITION_COST_USD_ENV_VAR),
    ):
        code = run(env=TRADE_ENV, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_CONFIG_ERROR
    assert MAX_POSITION_COST_USD_ENV_VAR in err.getvalue()
    assert RecordingNode.instances == [], "no node is built without a ceiling"


def test_a_missing_per_order_ceiling_derives_from_the_position_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Operator ruling 2026-09-10: with the two caps present, absence of
    the per-order session var is not a configuration error -- the native
    cap is derived and the node is built.
    """
    monkeypatch.delenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, raising=False)
    err = io.StringIO()

    with (
        operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "100.00"),
        operator_control_env(MAX_POSITION_COST_USD_ENV_VAR, "25.00"),
    ):
        code = run(env=TRADE_ENV, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_OK
    assert RecordingNode.instances, "node is built from the derived ceiling"


def test_a_malformed_trader_id_is_a_configuration_error_not_a_crash() -> None:
    env = {**TRADE_ENV, TRADE_TRADER_ID_VAR: "nope"}
    err = io.StringIO()

    code = run(env=env, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_CONFIG_ERROR
    assert RecordingNode.instances == []


def test_no_operator_reserved_control_appears_anywhere_in_the_entrypoint() -> None:
    """Neither reserved value may acquire a number on this path.

    Max DAILY budget and max PER POSITION are the operator's two values. R-6
    adds the mechanism; nothing -- least of all a process entrypoint -- ever
    assigns one, and absence must fail closed rather than default.
    """
    source = Path(trade_cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float)
    }

    # The only numeric constants in this module are the three exit codes.
    assert literals <= {0, 1, 2}, literals


# ---------------------------------------------------------------------------
# BL-24 Seam B section 6: live observation Actors, flag OFF by default
# ---------------------------------------------------------------------------


def test_the_observation_actor_is_absent_unless_the_flag_is_set() -> None:
    from breezy.ingest.nws_observation_actor import NwsObservationActor

    run(env=TRADE_ENV, node_factory=RecordingNode, stderr=io.StringIO())
    assert RecordingNode.instances[0].trader.actors == []
    assert "add_actor" not in RecordingNode.instances[0].calls

    RecordingNode.instances.clear()
    run(
        env={**TRADE_ENV, LIVE_OBSERVATIONS_VAR: "1"},
        node_factory=RecordingNode,
        stderr=io.StringIO(),
    )
    node = RecordingNode.instances[0]
    actors = node.trader.actors
    assert actors, "the flag registered no Actor"
    assert all(isinstance(actor, NwsObservationActor) for actor in actors)
    # Registered natively, BEFORE build (composition.py:462-484's shape).
    assert node.calls.index("add_actor") < node.calls.index("build")
    stations = {actor.station_icao for actor in actors}
    assert stations == {"KLAX", "KMDW", "KMIA", "KSFO"}  # KNYC excluded (A14, item 8)
    assert len({str(actor.id) for actor in actors}) == len(actors)


def test_a_flag_value_other_than_one_registers_nothing() -> None:
    run(
        env={**TRADE_ENV, LIVE_OBSERVATIONS_VAR: "true"},
        node_factory=RecordingNode,
        stderr=io.StringIO(),
    )
    assert RecordingNode.instances[0].trader.actors == []


def test_the_trade_node_config_still_declares_no_actors() -> None:
    """`build_trade_node_config` keeps `actors=[]` (node_config.py:696) even with the flag."""
    run(
        env={**TRADE_ENV, LIVE_OBSERVATIONS_VAR: "1"},
        node_factory=RecordingNode,
        stderr=io.StringIO(),
    )
    node = RecordingNode.instances[0]
    assert node.config.actors == []
    assert node.config.strategies == []
    assert node.config.exec_algorithms == []


def test_the_tape_recorder_and_the_ingest_node_are_untouched() -> None:
    """Only the trading entrypoint gains the observation Actors; the other two roles do not."""
    from breezy.runtime import composition, quote_tape_cli, quote_tape_ingest_cli

    for module in (composition, quote_tape_cli, quote_tape_ingest_cli):
        source = Path(str(module.__file__)).read_text(encoding="utf-8")
        assert "NwsObservationActor" not in source, module.__name__
        assert "live_observations" not in source, module.__name__
        assert "observation_composition" not in source, module.__name__


# ---------------------------------------------------------------------------
# AUD-13d: a trader that never reaches RUNNING is a CRITICAL boot-halt.
# The node lifecycle (build / run / dispose, exit code) stays the one the
# kernel already decided. This block only observes it.
# ---------------------------------------------------------------------------

_BOOT_HALT_EVENT = "BOOT_HALT"
#: The only detail a post-run read can state honestly. Engine connectivity
#: does not survive stop, and ``portfolio.initialized`` is false for every
#: early return, not only a portfolio-init failure.
_BOOT_HALT_DETAILS = frozenset(
    {"BOOT_HALT_TRADER_NEVER_STARTED", "BOOT_HALT_NODE_ASSEMBLY_FAILED"}
)
_DROPPED_BOOT_HALT_DETAILS = frozenset(
    {
        "BOOT_HALT_ENGINES_NOT_CONNECTED",
        "BOOT_HALT_RECONCILIATION_FAILED",
        "BOOT_HALT_PORTFOLIO_NOT_INITIALISED",
    }
)


def _boot_halt_payloads(sink: _RecordingAlertSink) -> list[AlertPayload]:
    return [payload for payload in sink.payloads if payload.event == _BOOT_HALT_EVENT]


def _publish_component_state(
    node: RecordingNode,
    *,
    component_id: Any,
    component_type: str,
    state: ComponentState,
) -> None:
    event = ComponentStateChanged(
        trader_id=node.trader.id,
        component_id=component_id,
        component_type=component_type,
        state=state,
        config={},
        event_id=UUID4(),
        ts_event=0,
        ts_init=0,
    )
    for topic, handler in node.kernel.msgbus.subscriptions:
        if topic == COMPONENT_STATE_TOPIC:
            handler(event)


class _AlwaysConnectedEngine:
    def __init__(self) -> None:
        self._clients: dict[object, object] = {}

    def check_connected(self) -> bool:
        return True


class _TraderReachedRunningNode(RecordingNode):
    """A clean stop leaves the public ``Trader.is_stopped`` flag set.

    That is the one-shot signal read after ``run()``. Publishing a component
    state is not that signal: the check does not subscribe to the bus.
    """

    def run(self) -> None:
        self.calls.append("run")
        self.trader.is_stopped = True


class _UnattributedBootHaltNode(RecordingNode):
    """Connected engines, portfolio not initialised, trader never started.

    A bus sample of that shape used to be labelled a failed reconciliation
    (engines connected, order emulator never seen). Those probes do not
    survive as a cause after ``run()`` returns, so the alert stays generic.
    The published event gives a subscriber the same chance to mislabel it.
    """

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self.kernel.data_engine = _AlwaysConnectedEngine()
        self.kernel.exec_engine = _AlwaysConnectedEngine()
        self.kernel.portfolio.initialized = False

    def run(self) -> None:
        self.calls.append("run")
        _publish_component_state(
            self,
            component_id=ComponentId("DataEngine"),
            component_type="DataEngine",
            state=ComponentState.RUNNING,
        )


def test_a_run_that_ends_without_the_trader_ever_running_alerts_at_critical(
    _no_send_alert_sink: _RecordingAlertSink,
) -> None:
    err = io.StringIO()

    code = run(env=TRADE_ENV, node_factory=RecordingNode, stderr=err)

    # The boot/halt decision is unchanged: the fake run still completes and
    # still exits 0. Only the alert is new.
    assert code == EXIT_OK
    assert err.getvalue() == ""
    assert RecordingNode.instances[0].calls == ["build", "run", "dispose"]
    payloads = _boot_halt_payloads(_no_send_alert_sink)
    assert len(payloads) == 1
    assert payloads[0].severity == "CRITICAL"
    assert payloads[0].site == "global"
    assert payloads[0].event == _BOOT_HALT_EVENT


def test_a_normal_run_that_reaches_trader_running_emits_no_boot_halt_alert(
    _no_send_alert_sink: _RecordingAlertSink,
) -> None:
    err = io.StringIO()

    code = run(env=TRADE_ENV, node_factory=_TraderReachedRunningNode, stderr=err)

    assert code == EXIT_OK
    assert err.getvalue() == ""
    assert RecordingNode.instances[0].calls == ["build", "run", "dispose"]
    node = RecordingNode.instances[0]
    # The one-shot signal, not a bus subscription. A node that never sets
    # it alerts (the test above); this one did, so silence is the branch.
    assert node.trader.is_stopped is True
    assert _boot_halt_payloads(_no_send_alert_sink) == []


def test_the_boot_halt_alert_detail_is_a_fixed_enum_and_carries_no_value(
    _no_send_alert_sink: _RecordingAlertSink,
) -> None:
    code = run(env=TRADE_ENV, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    payloads = _boot_halt_payloads(_no_send_alert_sink)
    assert len(payloads) == 1
    detail = payloads[0].detail
    assert detail in _BOOT_HALT_DETAILS
    assert detail == "BOOT_HALT_TRADER_NEVER_STARTED"
    assert not any(character.isdigit() for character in detail)
    assert " " not in detail
    assert "/" not in detail
    assert set(payloads[0].to_dict()) == {"severity", "event", "site", "detail"}


def test_a_failing_alert_sink_does_not_change_the_process_exit_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RaisingSink:
        def __init__(self) -> None:
            self.calls = 0

        def emit(self, payload: AlertPayload) -> None:
            del payload
            self.calls += 1
            raise RuntimeError("sink down")

    sink = _RaisingSink()
    monkeypatch.setattr(trade_cli, "resolve_alert_sink", lambda: sink, raising=False)
    err = io.StringIO()

    code = run(env=TRADE_ENV, node_factory=RecordingNode, stderr=err)

    assert sink.calls == 1
    assert code == EXIT_OK
    assert err.getvalue() == ""
    assert RecordingNode.instances[0].calls == ["build", "run", "dispose"]


def test_a_boot_halt_with_no_attributable_cause_alerts_with_the_generic_detail(
    _no_send_alert_sink: _RecordingAlertSink,
) -> None:
    code = run(env=TRADE_ENV, node_factory=_UnattributedBootHaltNode, stderr=io.StringIO())

    assert code == EXIT_OK
    assert RecordingNode.instances[0].calls == ["build", "run", "dispose"]
    payloads = _boot_halt_payloads(_no_send_alert_sink)
    assert len(payloads) == 1
    assert payloads[0].severity == "CRITICAL"
    detail = payloads[0].detail
    assert detail == "BOOT_HALT_TRADER_NEVER_STARTED"
    assert detail not in _DROPPED_BOOT_HALT_DETAILS


class _DoubleClaimNode(RecordingNode):
    """``Trader.add_strategy`` raising, as Nautilus's double external-order
    claim does (``execution/engine.pyx:552-557``)."""

    def __init__(self, config: Any) -> None:
        super().__init__(config)

        def _raise(strategy: Any) -> None:
            del strategy
            self.calls.append("add_strategy")
            raise ValueError("External order claim for X already exists for Y")

        self.trader.add_strategy = _raise  # type: ignore[method-assign]


class _BuildRaisingNode(RecordingNode):
    def build(self) -> None:
        self.calls.append("build")
        raise RuntimeError("the builder refused")


@pytest.mark.parametrize("node_factory", [_DoubleClaimNode, _BuildRaisingNode])
def test_a_node_assembly_failure_pages_one_critical_boot_halt(
    node_factory: type[RecordingNode],
    _no_send_alert_sink: _RecordingAlertSink,
) -> None:
    """AUD-13c review HIGH: an exception while the node is ASSEMBLED
    (``add_actor``/``add_strategy``/``build``) reaches the same CRITICAL
    sink as a boot that never starts. Exit code and stderr report unchanged."""
    err = io.StringIO()

    code = run(env=TRADE_ENV, node_factory=node_factory, stderr=err, strategies=(object(),))

    assert code == EXIT_RUNTIME_ERROR
    assert "trading node failed" in err.getvalue()
    assert "run" not in RecordingNode.instances[0].calls
    payloads = _boot_halt_payloads(_no_send_alert_sink)
    assert len(payloads) == 1
    assert payloads[0].severity == "CRITICAL"
    assert payloads[0].site == "global"
    assert payloads[0].detail == "BOOT_HALT_NODE_ASSEMBLY_FAILED"
    assert payloads[0].detail in _BOOT_HALT_DETAILS


def test_a_raising_sink_never_masks_a_node_assembly_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _RaisingSink:
        calls = 0

        def emit(self, payload: AlertPayload) -> None:
            del payload
            _RaisingSink.calls += 1
            raise RuntimeError("sink down")

    monkeypatch.setattr(trade_cli, "resolve_alert_sink", _RaisingSink, raising=False)
    err = io.StringIO()

    code = run(env=TRADE_ENV, node_factory=_BuildRaisingNode, stderr=err)

    assert _RaisingSink.calls == 1
    assert code == EXIT_RUNTIME_ERROR
    assert "the builder refused" in err.getvalue()


def test_a_failure_after_assembly_is_not_labelled_an_assembly_failure(
    _no_send_alert_sink: _RecordingAlertSink,
) -> None:
    code = run(env=TRADE_ENV, node_factory=RaisingNode, stderr=io.StringIO())

    assert code == EXIT_RUNTIME_ERROR
    details = [payload.detail for payload in _boot_halt_payloads(_no_send_alert_sink)]
    assert "BOOT_HALT_NODE_ASSEMBLY_FAILED" not in details


# ---------------------------------------------------------------------------
# AUD-13d HIGH-1: an intentional supervisor stop must never page CRITICAL.
# The marker lives beside `POLYMARKET_US_EXEC_STATE_DB`
# (`TRADE_ENV[EXEC_STATE_DB_ENV_VAR]`) -- the SAME store path
# `breezy.runtime.trade_supervisor`'s `stop_prior` phase resolves from the
# identical env var, since `spawn_node` forwards `env=os.environ` as-is.
# ---------------------------------------------------------------------------

_STOP_INTENT_STORE_PATH = Path(TRADE_ENV["POLYMARKET_US_EXEC_STATE_DB"])


@pytest.fixture(autouse=True)
def _clean_stop_intent_marker() -> Iterator[None]:
    marker_path = stop_intent_marker_path(_STOP_INTENT_STORE_PATH)
    marker_path.unlink(missing_ok=True)
    yield
    marker_path.unlink(missing_ok=True)


def test_a_stop_intent_marker_naming_this_process_suppresses_the_boot_halt_alert(
    _no_send_alert_sink: _RecordingAlertSink,
) -> None:
    write_stop_intent_marker(_STOP_INTENT_STORE_PATH, os.getpid())

    code = run(env=TRADE_ENV, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    assert RecordingNode.instances[0].calls == ["build", "run", "dispose"]
    assert _boot_halt_payloads(_no_send_alert_sink) == []


def test_the_stop_intent_marker_is_single_use(
    _no_send_alert_sink: _RecordingAlertSink,
) -> None:
    """A marker consumed by one boot-halt check must not silence the next."""
    write_stop_intent_marker(_STOP_INTENT_STORE_PATH, os.getpid())

    first_code = run(env=TRADE_ENV, node_factory=RecordingNode, stderr=io.StringIO())
    assert first_code == EXIT_OK
    assert _boot_halt_payloads(_no_send_alert_sink) == []

    second_code = run(env=TRADE_ENV, node_factory=RecordingNode, stderr=io.StringIO())
    assert second_code == EXIT_OK
    payloads = _boot_halt_payloads(_no_send_alert_sink)
    assert len(payloads) == 1
    assert payloads[0].detail == "BOOT_HALT_TRADER_NEVER_STARTED"


def test_a_stop_intent_marker_for_a_different_pid_does_not_suppress_the_alert(
    _no_send_alert_sink: _RecordingAlertSink,
) -> None:
    write_stop_intent_marker(_STOP_INTENT_STORE_PATH, os.getpid() + 1)

    code = run(env=TRADE_ENV, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    payloads = _boot_halt_payloads(_no_send_alert_sink)
    assert len(payloads) == 1
    assert payloads[0].detail == "BOOT_HALT_TRADER_NEVER_STARTED"


def test_no_stop_intent_marker_still_alerts_as_before(
    _no_send_alert_sink: _RecordingAlertSink,
) -> None:
    """Regression guard: the default (no marker) path is unchanged."""
    code = run(env=TRADE_ENV, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    payloads = _boot_halt_payloads(_no_send_alert_sink)
    assert len(payloads) == 1
    assert payloads[0].severity == "CRITICAL"


def test_a_stop_intent_marker_does_not_suppress_a_run_that_reaches_running(
    _no_send_alert_sink: _RecordingAlertSink,
) -> None:
    """The marker is read only when the trader never reached RUNNING -- a
    healthy run that happens to race a stale marker still stays silent for
    the SAME reason it always did (``_trader_reached_running`` is True),
    and the marker must still be consumed so it cannot outlive this boot."""
    write_stop_intent_marker(_STOP_INTENT_STORE_PATH, os.getpid())

    code = run(env=TRADE_ENV, node_factory=_TraderReachedRunningNode, stderr=io.StringIO())

    assert code == EXIT_OK
    assert _boot_halt_payloads(_no_send_alert_sink) == []


# ---------------------------------------------------------------------------
# FU-8b: a native LiveClock timer re-polls the reconciliation-refusal and
# stale-intent surfaces so a runtime latch is alerted within one interval
# with no ComponentStateChanged in between.
# ---------------------------------------------------------------------------

_REPOLL_INTERVAL_NS = int(REFUSAL_REPOLL_INTERVAL.total_seconds() * 1_000_000_000)


def _fire_repoll(node: RecordingNode) -> None:
    """Advance the fake kernel's real `TestClock` by exactly one repoll
    interval and hand every returned `TimeEventHandler` to `.handle()` --
    `TestClock` fires inline, on the caller's thread, and `_InlineLoop`
    (`node.kernel.loop`) forwards that call inline too, so the whole chain
    -- `_on_timer` -> `call_soon_threadsafe` -> `_poll` -> both alert
    handlers -- runs synchronously inside this call.
    """
    clock = node.kernel.clock
    handlers = clock.advance_time(clock.timestamp_ns() + _REPOLL_INTERVAL_NS)
    for handler in handlers:
        handler.handle()


class TimerObservingNode(RecordingNode):
    """Snapshots the kernel clock's armed timer names at the instant `run()`
    is called -- BEFORE any fire -- so test 13 observes arming alone."""

    def __init__(self, config: Any) -> None:
        super().__init__(config)
        self.timer_names_at_run: tuple[str, ...] = ()

    def run(self) -> None:
        self.calls.append("run")
        self.timer_names_at_run = tuple(self.kernel.clock.timer_names)


def test_run_node_arms_the_repoll_timer_on_the_kernel_clock_during_run() -> None:
    run(env=TRADE_ENV, node_factory=TimerObservingNode, stderr=io.StringIO())

    node = RecordingNode.instances[0]
    assert REFUSAL_REPOLL_TIMER_NAME in node.timer_names_at_run  # type: ignore[attr-defined]


class RepollTickNode(RecordingNode):
    """Registers one reconciliation refusal and one stale intent on the
    exec-client surfaces the readers poll, then fires exactly one repoll
    tick from inside `run()`."""

    def run(self) -> None:
        self.calls.append("run")
        client = SimpleNamespace(
            reconciliation_refusals=(
                {
                    "latch": "resolver_fill_not_booked",
                    "subject": "",
                    "detail": "RESOLVER_FILL_NOT_BOOKED",
                },
            ),
            stale_ambiguous_intent_alerts=(
                {
                    "intent_id": "intent-1",
                    "venue_order_id": "vo-1",
                    "age_minutes": "16",
                    "last_failure_kind": "TIMEOUT",
                },
            ),
        )
        self.kernel.exec_engine._clients[ClientId(POLYMARKET_US_CLIENT_NAME)] = client
        _fire_repoll(self)


def test_run_node_repoll_polls_reconciliation_and_stale_surfaces_on_a_tick(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The two watches resolve their OWN default alert sink -- a real
    `LoggingAlertSink` -- at install time, independent of this module's
    `_no_send_alert_sink` fixture (which only patches `trade_cli`'s own
    reference, used for boot-halt/assembly alerts). So the signal a repoll
    tick produced is read from the log stream, exactly as an operator would.
    """
    with caplog.at_level("INFO"):
        code = run(env=TRADE_ENV, node_factory=RepollTickNode, stderr=io.StringIO())

    assert code == EXIT_OK
    messages = [record.message for record in caplog.records]
    assert any("event=reconciliation_refusal" in message for message in messages)
    assert any("event=open_intent_stale" in message for message in messages)


class _DisposeSnapshotMixin:
    """Snapshots the kernel clock's armed timer names at the instant
    `dispose()` runs, before delegating to the real fake's own bookkeeping."""

    def dispose(self) -> None:
        self.timer_names_at_dispose: tuple[str, ...] = tuple(
            self.kernel.clock.timer_names  # type: ignore[attr-defined]
        )
        super().dispose()  # type: ignore[misc]


class CancelObservingNormalNode(_DisposeSnapshotMixin, RecordingNode):
    pass


class CancelObservingRaisingNode(_DisposeSnapshotMixin, RaisingNode):
    pass


class CancelObservingInterruptedNode(_DisposeSnapshotMixin, InterruptedNode):
    pass


@pytest.mark.parametrize(
    "node_factory",
    [CancelObservingNormalNode, CancelObservingRaisingNode, CancelObservingInterruptedNode],
)
def test_run_node_cancels_the_timer_on_every_exit(
    node_factory: type[RecordingNode],
) -> None:
    run(env=TRADE_ENV, node_factory=node_factory, stderr=io.StringIO())

    node = RecordingNode.instances[0]
    assert node.timer_names_at_dispose == ()  # type: ignore[attr-defined]


class RunSwallowsErrorNode(RecordingNode):
    """Models `TradingNode.run` catching a `RuntimeError` and returning with
    the kernel never stopped (`live/node.py:293-300`): from `_run_node`'s own
    vantage this `run()` simply returns, exactly like a normal stop, and
    nothing here calls the kernel's own `_cancel_timers`."""

    def run(self) -> None:
        self.calls.append("run")


class CancelObservingSwallowedNode(_DisposeSnapshotMixin, RunSwallowsErrorNode):
    pass


def test_run_node_cancels_the_timer_when_run_swallows_an_error_and_the_kernel_never_stops() -> (
    None
):
    run(env=TRADE_ENV, node_factory=CancelObservingSwallowedNode, stderr=io.StringIO())

    node = RecordingNode.instances[0]
    assert node.timer_names_at_dispose == ()  # type: ignore[attr-defined]


def test_run_node_arms_nothing_and_writes_no_not_armed_line_when_build_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Reuses `_BuildRaisingNode` (defined above for the assembly-failure
    tests): the arm is pinned AFTER `build()`, so a build that raises never
    reaches the arm call at all -- no armed INFO line, no `NOT armed` line,
    and no timer left on the clock."""
    err = io.StringIO()

    with caplog.at_level("INFO"):
        code = run(env=TRADE_ENV, node_factory=_BuildRaisingNode, stderr=err)

    assert code == EXIT_RUNTIME_ERROR
    assert "NOT armed" not in err.getvalue()
    # The positive arm signal must be ABSENT too: a timer armed and then
    # cleaned up in `finally` would satisfy the final-state check below by
    # accident even if the arm ran too early (before `build()`).
    assert not any("refusal re-poll timer armed" in record.message for record in caplog.records)
    node = RecordingNode.instances[0]
    assert tuple(node.kernel.clock.timer_names) == ()


def test_run_node_boots_when_arming_fails(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def _raise_on_arm(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("arming exploded")

    monkeypatch.setattr(trade_cli, "install_refusal_repoll_timer", _raise_on_arm)
    err = io.StringIO()

    with caplog.at_level("ERROR"):
        code = run(env=TRADE_ENV, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_OK
    assert err.getvalue().count("NOT armed") == 1
    not_armed_errors = [
        record
        for record in caplog.records
        if record.levelname == "ERROR" and "NOT armed" in record.message
    ]
    assert len(not_armed_errors) == 1
    assert RecordingNode.instances[0].calls == ["build", "run", "dispose"]
