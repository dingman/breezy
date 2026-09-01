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
from pathlib import Path
from typing import Any, ClassVar

import pytest

from breezy.adapters.polymarket_us import feed_fault
from breezy.adapters.polymarket_us.factories import (
    POLYMARKET_US_CLIENT_NAME,
    PolymarketUSLiveDataClientFactory,
)
from breezy.adapters.polymarket_us.safety import MAX_ORDER_NOTIONAL_USD_ENV_VAR
from breezy.runtime import trade_cli
from breezy.runtime.settings import TRADE_TRADER_ID_VAR
from breezy.runtime.trade_cli import (
    EXIT_CONFIG_ERROR,
    EXIT_OK,
    EXIT_RUNTIME_ERROR,
    run,
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


class RecordingNode:
    """Stands in for ``TradingNode``; records the wiring calls made on it."""

    instances: ClassVar[list[RecordingNode]] = []

    def __init__(self, config: Any) -> None:
        self.config = config
        self.data_client_factories: list[tuple[str, type]] = []
        self.exec_client_factories: list[tuple[str, type]] = []
        self.calls: list[str] = []
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
    yield
    RecordingNode.instances.clear()
    feed_fault.clear_fatal_feed_fault()


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


def test_no_execution_client_factory_is_ever_registered() -> None:
    """R-2 has no order path at all. A later increment adds one; not this one."""
    run(env=TRADE_ENV, node_factory=RecordingNode, stderr=io.StringIO())
    node = RecordingNode.instances[0]

    assert node.exec_client_factories == []
    assert node.config.exec_clients == {}
    assert node.config.strategies == []
    assert node.config.exec_algorithms == []


def test_the_entrypoint_source_registers_no_execution_surface() -> None:
    """Structural, not behavioural -- and deliberately so.

    The behavioural test above proves this run registered nothing. It cannot
    prove a *conditional* registration on a branch the test does not take.
    Reading the source closes that gap: the increment's promise is that the
    process is INCAPABLE of reaching an order path, and a call that is not
    written cannot be reached.
    """
    source = Path(trade_cli.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert "add_exec_client_factory" not in called
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
# Misconfiguration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        TRADE_TRADER_ID_VAR,
        "POLYMARKET_US_USER_AGENT",
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
