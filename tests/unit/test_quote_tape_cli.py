"""The quote-tape recorder's process entrypoint.

A node config that nothing constructs is the repo's standing failure mode:
green suite, dead deployment. These tests drive the actual entrypoint the
console script calls, with the ``TradingNode`` injected so nothing opens a
socket, and assert the properties an operator depends on:

* a misconfigured host exits 2 with the offending variable named on stderr;
* a correctly configured host builds, runs and ALWAYS disposes the node;
* exactly one data-client factory is registered, under the name the node
  config keys its ``data_clients`` mapping by (a mismatch there routes
  nothing and logs nothing);
* **zero** exec-client factories are registered, ever.
"""

from __future__ import annotations

import io
import logging
import os
import stat
from pathlib import Path
from typing import Any, ClassVar

import pytest

from breezy.adapters.polymarket_us.factories import (
    POLYMARKET_US_CLIENT_NAME,
    PolymarketUSLiveDataClientFactory,
)
from breezy.runtime.node_config import QUOTE_TAPE_ROOT_MODE
from breezy.runtime.quote_tape_cli import (
    EXIT_CONFIG_ERROR,
    EXIT_OK,
    EXIT_RUNTIME_ERROR,
    run,
)
from breezy.runtime.quote_tape_disk_monitor import DiskUsage

SLUG = "tc-temp-nychigh-2026-08-25-lt79f"

#: Venue values are `.invalid` hosts and the catalog root is a per-test tmp
#: directory: `run` now really creates that root (0700, symlink-checked), so a
#: fixed absolute path here would write outside the test sandbox.
BASE_ENV: dict[str, str] = {
    "BREEZY_POLYMARKET_US_QUOTE_TAPE_MIN_FREE_BYTES_WARNING": str(20 * 1024**3),
    "BREEZY_POLYMARKET_US_QUOTE_TAPE_MIN_FREE_BYTES_ERROR": str(10 * 1024**3),
    "BREEZY_POLYMARKET_US_QUOTE_TAPE_MAX_FILE_BYTES_WARNING": str(400 * 1024**3),
    "BREEZY_POLYMARKET_US_QUOTE_TAPE_MAX_FILE_BYTES_ERROR": str(500 * 1024**3),
    # Security finding M2: these test-double origins sit off the venue domain,
    # so the recorder's environment must declare that deliberately -- exactly
    # as a real staging run would have to.
    "POLYMARKET_US_ALLOW_FOREIGN_ORIGIN": "1",
    "POLYMARKET_US_API_BASE": "https://api.example.invalid",
    "POLYMARKET_US_GATEWAY_BASE": "https://gateway.example.invalid",
    "POLYMARKET_US_WS_URL": "wss://ws.example.invalid",
    "POLYMARKET_US_DISCOVERY_RELOAD_INTERVAL_MINS": "5",
    "POLYMARKET_US_USER_AGENT": "breezy-test/1.0 (+mailto:ops@example.invalid)",
}


@pytest.fixture(name="complete_env")
def _complete_env(tmp_path: Path) -> dict[str, str]:
    return {
        **BASE_ENV,
        "BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG": str(tmp_path / "venue" / "polymarket_us"),
    }


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


@pytest.fixture(autouse=True)
def _clear_instances() -> None:
    RecordingNode.instances.clear()


def test_a_complete_environment_builds_runs_and_disposes_the_node(
    complete_env: dict[str, str],
) -> None:
    err = io.StringIO()

    code = run(env=complete_env, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_OK
    assert err.getvalue() == ""
    assert RecordingNode.instances[0].calls == ["build", "run", "dispose"]


def test_exactly_one_data_client_factory_is_registered_under_the_routing_name(
    complete_env: dict[str, str],
) -> None:
    """The registration name and the ``data_clients`` key must be the same string.

    ``live/node_builder.py:163,177`` resolves the client by that name; a
    mismatch produces no client and no error worth noticing.
    """
    run(env=complete_env, node_factory=RecordingNode, stderr=io.StringIO())
    node = RecordingNode.instances[0]

    assert node.data_client_factories == [
        (POLYMARKET_US_CLIENT_NAME, PolymarketUSLiveDataClientFactory)
    ]
    assert set(node.config.data_clients) == {POLYMARKET_US_CLIENT_NAME}


def test_no_execution_client_factory_is_ever_registered(
    complete_env: dict[str, str],
) -> None:
    """Zero order path. This recorder can only read."""
    run(env=complete_env, node_factory=RecordingNode, stderr=io.StringIO())
    node = RecordingNode.instances[0]

    assert node.exec_client_factories == []
    assert node.config.exec_clients == {}


def test_the_node_is_configured_to_stream_to_the_configured_catalog_root(
    complete_env: dict[str, str],
) -> None:
    run(env=complete_env, node_factory=RecordingNode, stderr=io.StringIO())
    node = RecordingNode.instances[0]

    assert node.config.streaming is not None
    assert node.config.streaming.catalog_path == complete_env[
        "BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG"
    ]


@pytest.mark.parametrize(
    "name",
    [
        "BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG",
        "POLYMARKET_US_USER_AGENT",
    ],
)
def test_every_missing_variable_exits_two_and_names_itself(
    name: str, complete_env: dict[str, str]
) -> None:
    """Strict on its OWN terms -- the point of the separate role.

    The weather collector is unaffected by any of these; the recorder refuses
    to start half-configured rather than recording an incomplete tape nobody
    notices is incomplete.

    G-19 B1/B2 removed the four Polymarket.us venue-FACT variables from this
    list. They are no longer required inputs -- the endpoint triple is pinned
    from captured venue evidence and the reload cadence is derived from the
    discovered market set -- so their absence must NOT stop the recorder. The
    complement is asserted by
    ``test_recorder_starts_with_no_venue_fact_variable_set``.

    G-19 B10 removed the four disk thresholds for the same reason: how much
    headroom a volume needs is derivable from the volume, so their absence
    must not stop the recorder either. Both survivors are genuine operator
    ceilings -- a deploy path and a contact string -- and neither can be
    self-derived.
    """
    env = dict(complete_env)
    del env[name]
    err = io.StringIO()

    code = run(env=env, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_CONFIG_ERROR
    assert name in err.getvalue()
    assert RecordingNode.instances == [], "no node is built from a bad environment"


@pytest.mark.parametrize(
    "name",
    [
        "POLYMARKET_US_API_BASE",
        "POLYMARKET_US_GATEWAY_BASE",
        "POLYMARKET_US_WS_URL",
        "POLYMARKET_US_DISCOVERY_RELOAD_INTERVAL_MINS",
    ],
)
def test_recorder_starts_with_no_venue_fact_variable_set(
    name: str, complete_env: dict[str, str]
) -> None:
    """G-19: no venue FACT may block the recorder from starting.

    Removing any one of the four (B) variables must NOT produce a
    configuration error -- the bot already knows or derives that value.
    """
    env = dict(complete_env)
    del env[name]
    err = io.StringIO()

    code = run(env=env, node_factory=RecordingNode, stderr=err)

    assert code != EXIT_CONFIG_ERROR, err.getvalue()
    assert name not in err.getvalue()


def test_ctrl_c_is_a_clean_shutdown_not_a_runtime_failure(
    complete_env: dict[str, str],
) -> None:
    """A deliberate stop must exit 0.

    `TradingNode.run` catches only `RuntimeError` (`live/node.py:293-300`).
    The kernel installs SIGINT/SIGTERM handlers for a LIVE environment
    (`system/kernel.py:558-572`), but a signal arriving before the loop is
    running -- during `build()`, or between `build()` and `run()` -- surfaces as
    `KeyboardInterrupt` and would otherwise be reported as a failed run. Under
    systemd that is the difference between "stopped" and "failed", and it is
    the difference an operator watching a months-long recorder acts on.
    """
    err = io.StringIO()

    code = run(env=complete_env, node_factory=InterruptedNode, stderr=err)

    assert code == EXIT_OK
    assert RecordingNode.instances[0].calls == ["build", "run", "dispose"]
    assert "failed" not in err.getvalue().lower()


def test_the_tape_root_is_prepared_before_the_node_is_built(
    tmp_path: Path, complete_env: dict[str, str]
) -> None:
    """Nautilus would otherwise create it via fsspec under the process umask."""
    root = tmp_path / "venue" / "polymarket_us"
    env = dict(complete_env)

    code = run(env=env, node_factory=RecordingNode, stderr=io.StringIO())

    assert code == EXIT_OK
    assert root.is_dir()
    assert stat.S_IMODE(os.lstat(root).st_mode) == QUOTE_TAPE_ROOT_MODE


def test_an_unsafe_tape_root_is_a_configuration_error_not_a_crash(
    tmp_path: Path, complete_env: dict[str, str]
) -> None:
    real = tmp_path / "elsewhere"
    real.mkdir()
    root = tmp_path / "linked"
    root.symlink_to(real, target_is_directory=True)
    env = dict(complete_env)
    env["BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG"] = str(root)
    err = io.StringIO()

    code = run(env=env, node_factory=RecordingNode, stderr=err)

    assert code == EXIT_CONFIG_ERROR
    assert "symlink" in err.getvalue()
    assert RecordingNode.instances == []


def test_a_runtime_failure_exits_one_and_still_disposes_the_node(
    complete_env: dict[str, str],
) -> None:
    err = io.StringIO()

    code = run(env=complete_env, node_factory=RaisingNode, stderr=err)

    assert code == EXIT_RUNTIME_ERROR
    assert "the socket exploded" in err.getvalue()
    assert RecordingNode.instances[0].calls == ["build", "run", "dispose"]


def test_disk_error_logs_but_does_not_halt_the_recorder(
    complete_env: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    err = io.StringIO()

    with caplog.at_level(logging.ERROR, logger="breezy.runtime.quote_tape_disk_monitor"):
        code = run(
            env=complete_env,
            node_factory=RecordingNode,
            stderr=err,
            disk_usage_probe=lambda path: DiskUsage(total=10_000, used=9_900, free=100),
        )

    assert code == EXIT_OK
    assert err.getvalue() == ""
    assert RecordingNode.instances[0].calls == ["build", "run", "dispose"]
    assert any("free_space_error" in record.getMessage() for record in caplog.records)
