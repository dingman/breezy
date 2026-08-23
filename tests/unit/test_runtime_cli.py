"""Unit tests for `breezy.runtime.cli` and the `breezy` console entrypoint.

No real `TradingNode` is constructed and no event loop is started: the node
is injected as a factory, so `build()`/`run()`/`dispose()` ordering and the
teardown guarantees are assertable without any I/O.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest
from nautilus_trader.config import TradingNodeConfig

import breezy
from breezy.ingest.shared_state import SharedIngestState
from breezy.persistence.catalog import FilesystemLocality, FilesystemProbe
from breezy.runtime import cli

SITES: tuple[tuple[str, str], ...] = (("polymarket_us", "NYC"),)


class FakeNode:
    """Records the node lifecycle without touching an event loop."""

    instances: ClassVar[list[FakeNode]] = []

    def __init__(self, config: TradingNodeConfig, *, run_error: BaseException | None = None):
        self.config = config
        self.calls: list[str] = []
        self._run_error = run_error
        FakeNode.instances.append(self)

    def build(self) -> None:
        self.calls.append("build")

    def run(self) -> None:
        self.calls.append("run")
        if self._run_error is not None:
            raise self._run_error

    def dispose(self) -> None:
        self.calls.append("dispose")


@pytest.fixture(autouse=True)
def _reset_nodes() -> Iterator[None]:
    FakeNode.instances = []
    yield
    FakeNode.instances = []


def local_probe(path: Path) -> FilesystemProbe:
    return FilesystemProbe(
        path=str(path),
        mount_point="/",
        fs_type="ext4",
        locality=FilesystemLocality.LOCAL,
        detail="fake probe",
    )


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    return {
        "BREEZY_TRADER_ID": "BREEZY-001",
        "BREEZY_SITES": "polymarket_us:NYC",
        "BREEZY_CATALOG_BASE": str(tmp_path / "nws"),
        "BREEZY_STATE_DB": str(tmp_path / "state" / "breezy-state.sqlite3"),
        "BREEZY_ALLOW_PROXY_ENV": "1",
    }


class TestRun:
    def test_happy_path_builds_runs_and_disposes_the_node(
        self, env: dict[str, str]
    ) -> None:
        stderr = io.StringIO()

        code = cli.run(env=env, node_factory=FakeNode, probe=local_probe, stderr=stderr)

        assert code == cli.EXIT_OK
        assert FakeNode.instances[-1].calls == ["build", "run", "dispose"]
        assert stderr.getvalue() == ""

    def test_the_node_receives_the_composed_config(self, env: dict[str, str]) -> None:
        cli.run(env=env, node_factory=FakeNode, probe=local_probe, stderr=io.StringIO())

        config = FakeNode.instances[-1].config
        assert isinstance(config, TradingNodeConfig)
        assert config.catalogs == []
        assert len(config.actors) == len(SITES)

    def test_shared_ingest_state_is_disposed_after_the_run(
        self, env: dict[str, str]
    ) -> None:
        captured: list[SharedIngestState] = []

        def factory(config: TradingNodeConfig) -> FakeNode:
            return FakeNode(config)

        cli.run(
            env=env,
            node_factory=factory,
            probe=local_probe,
            stderr=io.StringIO(),
            on_runtime=captured.append,
        )

        assert len(captured) == 1
        # Disposal released the process slot: a second run must succeed.
        assert (
            cli.run(env=env, node_factory=FakeNode, probe=local_probe, stderr=io.StringIO())
            == cli.EXIT_OK
        )

    def test_node_is_disposed_even_when_run_raises(self, env: dict[str, str]) -> None:
        def exploding(config: TradingNodeConfig) -> FakeNode:
            return FakeNode(config, run_error=RuntimeError("kaboom"))

        stderr = io.StringIO()
        code = cli.run(env=env, node_factory=exploding, probe=local_probe, stderr=stderr)

        assert code == cli.EXIT_RUNTIME_ERROR
        assert FakeNode.instances[-1].calls == ["build", "run", "dispose"]
        assert "kaboom" in stderr.getvalue()

    def test_installs_no_signal_handlers_of_its_own(self) -> None:
        # NULL HYPOTHESIS CONFIRMED against nautilus-trader 1.231.0:
        # `NautilusKernel._setup_loop` (`system/kernel.py:558-572`) registers
        # SIGTERM/SIGINT/SIGABRT on the loop for every non-BACKTEST environment,
        # dispatching to `TradingNode._loop_sig_handler` -> `node.stop()`.
        # Re-installing handlers here would REPLACE that native shutdown path.
        import inspect

        source = inspect.getsource(cli)
        assert "signal.signal" not in source
        assert "add_signal_handler" not in source


class TestErrorReporting:
    def test_missing_required_setting_exits_non_zero_with_a_clear_message(self) -> None:
        stderr = io.StringIO()

        code = cli.run(env={}, node_factory=FakeNode, probe=local_probe, stderr=stderr)

        assert code == cli.EXIT_CONFIG_ERROR
        message = stderr.getvalue()
        assert "BREEZY_SITES" in message
        assert "Traceback" not in message
        assert FakeNode.instances == []

    def test_malformed_setting_exits_non_zero_with_a_clear_message(
        self, env: dict[str, str]
    ) -> None:
        stderr = io.StringIO()

        code = cli.run(
            env={**env, "BREEZY_POLL_INTERVAL_SECONDS": "-5"},
            node_factory=FakeNode,
            probe=local_probe,
            stderr=stderr,
        )

        assert code == cli.EXIT_CONFIG_ERROR
        assert "BREEZY_POLL_INTERVAL_SECONDS" in stderr.getvalue()
        assert "Traceback" not in stderr.getvalue()

    def test_malformed_trader_id_is_refused_before_nautilus_aborts(
        self, env: dict[str, str]
    ) -> None:
        # Guards against the measured SIGABRT in `TraderId` -- see
        # test_runtime_node_config.TestValidatedTraderId.
        stderr = io.StringIO()

        code = cli.run(
            env={**env, "BREEZY_TRADER_ID": "nohyphen"},
            node_factory=FakeNode,
            probe=local_probe,
            stderr=stderr,
        )

        assert code == cli.EXIT_CONFIG_ERROR
        assert "trader_id" in stderr.getvalue()
        assert FakeNode.instances == []

    def test_unknown_site_exits_non_zero_with_a_clear_message(
        self, env: dict[str, str]
    ) -> None:
        stderr = io.StringIO()

        code = cli.run(
            env={**env, "BREEZY_SITES": "polymarket_us:PHL"},
            node_factory=FakeNode,
            probe=local_probe,
            stderr=stderr,
        )

        assert code == cli.EXIT_CONFIG_ERROR
        assert "PHL" in stderr.getvalue()
        assert "Traceback" not in stderr.getvalue()

    def test_network_station_root_exits_non_zero_with_a_clear_message(
        self, env: dict[str, str]
    ) -> None:
        def network_probe(path: Path) -> FilesystemProbe:
            return FilesystemProbe(
                path=str(path),
                mount_point="/mnt/share",
                fs_type="nfs4",
                locality=FilesystemLocality.NETWORK,
                detail="fake probe",
            )

        stderr = io.StringIO()
        code = cli.run(
            env=env, node_factory=FakeNode, probe=network_probe, stderr=stderr
        )

        assert code == cli.EXIT_CONFIG_ERROR
        assert "nfs4" in stderr.getvalue()
        assert FakeNode.instances == []

    def test_an_unexpected_error_is_reported_not_dumped(self, env: dict[str, str]) -> None:
        def broken(config: TradingNodeConfig) -> FakeNode:
            raise ZeroDivisionError("something nobody anticipated")

        stderr = io.StringIO()
        code = cli.run(env=env, node_factory=broken, probe=local_probe, stderr=stderr)

        assert code == cli.EXIT_RUNTIME_ERROR
        assert "something nobody anticipated" in stderr.getvalue()
        assert "Traceback" not in stderr.getvalue()


class TestEntrypoint:
    def test_breezy_main_delegates_to_the_cli(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: list[object] = []

        def fake_run(**kwargs: object) -> int:
            seen.append(kwargs)
            return 7

        monkeypatch.setattr(cli, "run", fake_run)

        assert breezy.main() == 7
        assert len(seen) == 1

    def test_breezy_main_no_longer_prints_the_hello_stub(self) -> None:
        import inspect

        assert "Hello from breezy" not in inspect.getsource(breezy)

    def test_cli_main_delegates_to_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli, "run", lambda **kwargs: 3)

        assert cli.main() == 3


class TestUnexpectedCompositionFailure:
    def test_a_failure_outside_the_node_is_reported_not_dumped(
        self, env: dict[str, str]
    ) -> None:
        # Raised inside the composed runtime but OUTSIDE `_run_node`, so it
        # exercises the outer catch-all rather than the node's own handler.
        def explode(_shared: SharedIngestState) -> None:
            raise ZeroDivisionError("composition-time surprise")

        stderr = io.StringIO()
        code = cli.run(
            env=env,
            node_factory=FakeNode,
            probe=local_probe,
            stderr=stderr,
            on_runtime=explode,
        )

        assert code == cli.EXIT_RUNTIME_ERROR
        assert "composition-time surprise" in stderr.getvalue()
        assert "Traceback" not in stderr.getvalue()
        assert FakeNode.instances == []

    def test_that_failure_still_releases_the_process_slot(
        self, env: dict[str, str]
    ) -> None:
        def explode(_shared: SharedIngestState) -> None:
            raise ZeroDivisionError("composition-time surprise")

        cli.run(
            env=env,
            node_factory=FakeNode,
            probe=local_probe,
            stderr=io.StringIO(),
            on_runtime=explode,
        )

        assert (
            cli.run(env=env, node_factory=FakeNode, probe=local_probe, stderr=io.StringIO())
            == cli.EXIT_OK
        )
