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
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import pytest
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.enums import OrderSide, OrderType, TimeInForce
from nautilus_trader.model.events import OrderInitialized
from nautilus_trader.model.identifiers import (
    ClientOrderId,
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
from breezy.adapters.polymarket_us.safety import MAX_ORDER_NOTIONAL_USD_ENV_VAR
from breezy.runtime import trade_cli
from breezy.runtime.backtest_order_guard import NakedShortRefusedError
from breezy.runtime.settings import TRADE_TRADER_ID_VAR
from breezy.runtime.trade_cli import (
    EXIT_CONFIG_ERROR,
    EXIT_OK,
    EXIT_RUNTIME_ERROR,
    run,
)

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
    """Enough of ``CacheFacade`` for R-6a's guard to actually evaluate an event."""

    def orders_open(self, *, instrument_id: InstrumentId | None = None) -> tuple[Any, ...]:
        del instrument_id
        return ()


class _FakeKernel:
    """Stands in for the slice of ``NautilusKernel`` R-6a's guard reads."""

    def __init__(self) -> None:
        self.portfolio = _FakeGuardPortfolio()
        self.cache = _FakeGuardCache()
        self.msgbus = _FakeMsgBus()


class RecordingNode:
    """Stands in for ``TradingNode``; records the wiring calls made on it."""

    instances: ClassVar[list[RecordingNode]] = []

    def __init__(self, config: Any) -> None:
        self.config = config
        self.data_client_factories: list[tuple[str, type]] = []
        self.exec_client_factories: list[tuple[str, type]] = []
        self.calls: list[str] = []
        self.kernel = _FakeKernel()
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


def test_the_entrypoint_source_registers_no_strategy_or_exec_algorithm_or_raw_submit() -> None:
    """Structural, not behavioural -- and deliberately so.

    The behavioural test above proves this run registered an exec CLIENT. It
    cannot prove a *conditional* registration of a strategy or exec algorithm
    on a branch the test does not take. Reading the source closes that gap:
    the increment's promise is that the process is still INCAPABLE of
    reaching an order path, and a call that is not written cannot be reached.
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
    assert "add_strategy" not in called
    assert "add_exec_algorithm" not in called


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
    """A host with no per-order ceiling starts NOTHING, and is told why.

    `build_trade_node_config` configures the native per-order notional cap
    from `BREEZY_MAX_ORDER_NOTIONAL_USD` and refuses when that operator
    control is absent -- the process must never come up uncapped. Absence is
    an operator provisioning fault: exit 2 and one readable line naming the
    control, not a traceback reported as an engineering crash.

    This routes correctly with no change to `_CONFIG_ERRORS`:
    `LiveTradingPermissionError` subclasses `PermissionError`, which
    subclasses `OSError`, which that tuple already names. Asserted rather than
    assumed -- narrowing `OSError` there later would silently turn this
    refusal into an exit-1 crash report.
    """
    monkeypatch.delenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, raising=False)
    err = io.StringIO()

    code = run(env=TRADE_ENV, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_CONFIG_ERROR
    assert MAX_ORDER_NOTIONAL_USD_ENV_VAR in err.getvalue()
    assert RecordingNode.instances == [], "no node is built without a ceiling"


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
