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
from breezy.ingest.nws_actor import NwsIngestActor
from breezy.ingest.shared_state import SharedIngestState
from breezy.persistence.catalog import FilesystemLocality, FilesystemProbe
from breezy.runtime import cli
from breezy.runtime.sqlite_store import SqliteStateStore

SITES: tuple[tuple[str, str], ...] = (("polymarket_us", "NYC"),)


class FakeTrader:
    """Records `Trader.add_actor` calls without a real Trader."""

    def __init__(self) -> None:
        self.added_actors: list[object] = []

    def add_actor(self, actor: object) -> None:
        self.added_actors.append(actor)


class FakeNode:
    """Records the node lifecycle without touching an event loop."""

    instances: ClassVar[list[FakeNode]] = []

    def __init__(
        self,
        config: TradingNodeConfig,
        *,
        run_error: BaseException | None = None,
        order: list[str] | None = None,
    ):
        self.config = config
        self.calls: list[str] = []
        self._run_error = run_error
        # Optional shared sequence recorder -- see `TestTeardownOrder`. `None`
        # by default so every other `FakeNode` caller is unaffected.
        self._order = order
        self.trader = FakeTrader()
        FakeNode.instances.append(self)

    def build(self) -> None:
        self.calls.append("build")

    def run(self) -> None:
        self.calls.append("run")
        if self._run_error is not None:
            raise self._run_error

    def dispose(self) -> None:
        self.calls.append("dispose")
        if self._order is not None:
            self._order.append("node.dispose")


@pytest.fixture(autouse=True)
def _reset_nodes() -> Iterator[None]:
    FakeNode.instances = []
    yield
    FakeNode.instances = []


@pytest.fixture(autouse=True)
def _set_user_agent_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BREEZY_USER_AGENT", "breezy-test/1.0 (+mailto:ops@example.com)")


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
        "BREEZY_USER_AGENT": "breezy-test/1.0 (+mailto:ops@example.com)",
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
        # Zero declared actors, not one-per-site. `NwsIngestActor` requires a
        # live `SharedIngestState` and `ActorFactory.create` ends in
        # `actor_cls(config)` (`common/config.py:614`), so the
        # `ImportableActorConfig` route cannot construct it. Actors are built
        # and registered by `composition.build_ingest_node` through the native
        # `Trader.add_actor` -- see
        # `test_ingest_actors_are_registered_on_the_node_via_trader_add_actor`.
        assert config.actors == []

    def test_ingest_actors_are_registered_on_the_node_via_trader_add_actor(
        self, env: dict[str, str]
    ) -> None:
        """Regression: the node `cli.run` runs must carry the ingest Actors.

        A node with zero registered Actors builds and runs cleanly forever
        while ingesting nothing -- silently. Asserting `config.actors == []`
        (as `test_the_node_receives_the_composed_config` does) is correct but
        insufficient: it would still pass with zero Actors registered. This
        test asserts the Actors are actually present on `node.trader`, wired
        through the native `Trader.add_actor`.
        """
        stderr = io.StringIO()

        code = cli.run(env=env, node_factory=FakeNode, probe=local_probe, stderr=stderr)

        assert code == cli.EXIT_OK
        node = FakeNode.instances[-1]
        assert len(node.trader.added_actors) == len(SITES)
        assert all(isinstance(actor, NwsIngestActor) for actor in node.trader.added_actors)

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


class TestTeardownOrder:
    """WI-7: the full THREE-step teardown order, as ONE recorded sequence.

    `cli._run_node` disposes the node INSIDE the `with ingest_runtime(...)`
    block (`cli.py:161-164`), so the true production order is
    `node.dispose()` -> `shared.dispose()` -> `store.close()`: the node
    first (`_run_node`'s own `finally`, `cli.py:129-134`), then the two
    steps `ingest_runtime` owns on the way out (`composition.py:130,
    :158`; `ExitStack` unwinds LIFO). `test_runtime_composition.py`'s
    `TestTeardownOrder` pins the latter two steps in isolation; this class
    pins all three together, exactly as production runs them.
    """

    def test_clean_exit_order_is_node_then_shared_then_store(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        order: list[str] = []

        original_shared_dispose = SharedIngestState.dispose

        def recording_shared_dispose(self_: SharedIngestState) -> None:
            order.append("shared.dispose")
            original_shared_dispose(self_)

        monkeypatch.setattr(SharedIngestState, "dispose", recording_shared_dispose)

        original_store_close = SqliteStateStore.close

        def recording_store_close(self_: SqliteStateStore) -> None:
            order.append("store.close")
            original_store_close(self_)

        monkeypatch.setattr(SqliteStateStore, "close", recording_store_close)

        def factory(config: TradingNodeConfig) -> FakeNode:
            return FakeNode(config, order=order)

        def discard_construction_noise(_shared: SharedIngestState) -> None:
            # Discard anything recorded during construction -- e.g. the
            # durability probe's own second store handle, opened and closed
            # entirely inside `SharedIngestState.__init__`, before the node
            # is even built. Only the TEARDOWN-phase calls are under test.
            order.clear()

        stderr = io.StringIO()
        code = cli.run(
            env=env,
            node_factory=factory,
            probe=local_probe,
            stderr=stderr,
            on_runtime=discard_construction_noise,
        )

        assert code == cli.EXIT_OK
        assert order == ["node.dispose", "shared.dispose", "store.close"]

    def test_run_raising_still_tears_down_all_three_in_order(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        order: list[str] = []

        original_shared_dispose = SharedIngestState.dispose

        def recording_shared_dispose(self_: SharedIngestState) -> None:
            order.append("shared.dispose")
            original_shared_dispose(self_)

        monkeypatch.setattr(SharedIngestState, "dispose", recording_shared_dispose)

        original_store_close = SqliteStateStore.close

        def recording_store_close(self_: SqliteStateStore) -> None:
            order.append("store.close")
            original_store_close(self_)

        monkeypatch.setattr(SqliteStateStore, "close", recording_store_close)

        def factory(config: TradingNodeConfig) -> FakeNode:
            return FakeNode(config, order=order, run_error=RuntimeError("kaboom"))

        def discard_construction_noise(_shared: SharedIngestState) -> None:
            order.clear()

        stderr = io.StringIO()
        code = cli.run(
            env=env,
            node_factory=factory,
            probe=local_probe,
            stderr=stderr,
            on_runtime=discard_construction_noise,
        )

        # `_run_node` catches the node's own failure and turns it into an
        # exit code (`cli.py:126-128`) -- unlike `ingest_runtime`'s body, it
        # never re-raises the original exception -- but disposal must still
        # run to completion, in the documented order.
        assert code == cli.EXIT_RUNTIME_ERROR
        assert "kaboom" in stderr.getvalue()
        assert order == ["node.dispose", "shared.dispose", "store.close"]


class TestErrorReporting:
    def test_missing_required_setting_exits_non_zero_with_a_clear_message(self) -> None:
        """G-19 B4 moved ``BREEZY_SITES`` off this list.

        The city universe is a venue FACT and is now derived from the site
        registry when unset. ``BREEZY_CATALOG_BASE`` is a deploy path -- an
        operator enablement ceiling -- and stays required, so it is the
        variable an empty environment must now name.
        """
        stderr = io.StringIO()

        code = cli.run(env={}, node_factory=FakeNode, probe=local_probe, stderr=stderr)

        assert code == cli.EXIT_CONFIG_ERROR
        message = stderr.getvalue()
        assert "BREEZY_CATALOG_BASE" in message
        assert "Traceback" not in message
        assert FakeNode.instances == []

    def test_an_unset_site_list_starts_on_the_derived_registry_default(
        self, env: dict[str, str]
    ) -> None:
        """The G-19 deliverable at the process boundary: no recited venue fact."""
        stderr = io.StringIO()

        code = cli.run(
            env={key: value for key, value in env.items() if key != "BREEZY_SITES"},
            node_factory=FakeNode,
            probe=local_probe,
            stderr=stderr,
        )

        assert code == cli.EXIT_OK
        assert stderr.getvalue() == ""

    def test_missing_user_agent_exits_as_configuration_error(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stderr = io.StringIO()
        monkeypatch.delenv("BREEZY_USER_AGENT", raising=False)

        code = cli.run(
            env={key: value for key, value in env.items() if key != "BREEZY_USER_AGENT"},
            node_factory=FakeNode,
            probe=local_probe,
            stderr=stderr,
        )

        assert code == cli.EXIT_CONFIG_ERROR
        assert "BREEZY_USER_AGENT" in stderr.getvalue()
        assert "Traceback" not in stderr.getvalue()
        assert FakeNode.instances == []

    def test_injected_user_agent_env_is_used_without_process_environment(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stderr = io.StringIO()
        monkeypatch.delenv("BREEZY_USER_AGENT", raising=False)

        code = cli.run(env=env, node_factory=FakeNode, probe=local_probe, stderr=stderr)

        assert code == cli.EXIT_OK
        assert stderr.getvalue() == ""
        assert FakeNode.instances[-1].calls == ["build", "run", "dispose"]

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
