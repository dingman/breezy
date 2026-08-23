"""WI-7b -- minimal build/start/stop/build-again lifecycle smoke test.

Proves that `ingest_runtime` + `build_ingest_node`, taken through a full
build -> start -> stop -> teardown cycle, release BOTH the process-wide
`SharedIngestState` slot AND the SQLite state-db handle -- so a supervisor
that restarts this process after a clean stop gets a working process back,
not `DuplicateSharedIngestStateError` and not a locked database file.

Zero network I/O: the trading node is a recording fake (`build()`/`run()`/
`dispose()` only, no event loop, no socket), and the filesystem probe is a
fixed-verdict fake. No hard-coded wall-clock date -- the clock is an
injected monotonic counter, exactly the seam
`breezy.runtime.composition.ingest_runtime` documents.

Makes NO assertions about domain-record content (published products, gap
ledgers, settlement state) -- proving those survive a restart is WI-9's job
(`tests/integration/test_runtime_restart_resume.py`, not yet written). This
test proves only that the composition root's OWN resources -- the process
slot and the sqlite handle -- are genuinely released, which is the
precondition WI-9 depends on.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from nautilus_trader.config import TradingNodeConfig

from breezy.ingest.shared_state import DuplicateSharedIngestStateError
from breezy.persistence.catalog import FilesystemLocality, FilesystemProbe
from breezy.runtime.composition import BreezyIngestRuntime, build_ingest_node, ingest_runtime
from breezy.runtime.settings import BreezyRuntimeSettings

SITES: tuple[tuple[str, str], ...] = (("polymarket_us", "NYC"), ("polymarket_us", "LAX"))


def local_probe(path: Path) -> FilesystemProbe:
    return FilesystemProbe(
        path=str(path),
        mount_point="/",
        fs_type="ext4",
        locality=FilesystemLocality.LOCAL,
        detail="fake probe",
    )


class RecordingTrader:
    """Records `Trader.add_actor` calls without a real Trader."""

    def __init__(self) -> None:
        self.added_actors: list[object] = []

    def add_actor(self, actor: object) -> None:
        self.added_actors.append(actor)


class RecordingNode:
    """A `TradingNode` stand-in: `build`/`run`/`dispose` recorded, no loop.

    `run()` returns immediately rather than blocking -- exactly the state a
    real `TradingNode.run()` is in once `TradingNode.stop()` has already
    been signalled, i.e. a clean, already-completed stop.
    """

    def __init__(self, config: TradingNodeConfig) -> None:
        self.config = config
        self.calls: list[str] = []
        self.trader = RecordingTrader()

    def build(self) -> None:
        self.calls.append("build")

    def run(self) -> None:
        self.calls.append("run")

    def dispose(self) -> None:
        self.calls.append("dispose")


@pytest.fixture
def settings(tmp_path: Path) -> BreezyRuntimeSettings:
    return BreezyRuntimeSettings(
        trader_id="BREEZY-001",
        sites=SITES,
        catalog_base=tmp_path / "nws",
        state_db_path=tmp_path / "state" / "breezy-state.sqlite3",
        poll_interval_seconds=300,
        parse_timeout_ms=250,
        log_level="INFO",
        check_proxy_env=False,
        registry_path=None,
    )


def make_clock() -> Callable[[], int]:
    """A monotonically increasing fake nanosecond clock -- never wall time.

    A fresh counter per call, starting from an arbitrary fixed origin: this
    suite has already been bitten once by a hard-coded wall-clock date, so
    every clock here is synthetic and relative, never `time.time_ns`.
    """
    counter = {"n": 1_000_000_000}

    def clock() -> int:
        counter["n"] += 1
        return counter["n"]

    return clock


def run_one_lifecycle(settings: BreezyRuntimeSettings) -> RecordingNode:
    """Build -> start -> stop -> tear down, over `settings`'s paths."""
    with ingest_runtime(settings, clock=make_clock(), probe=local_probe) as runtime:
        assert isinstance(runtime, BreezyIngestRuntime)
        node = build_ingest_node(runtime, node_factory=RecordingNode)
        node.build()
        node.run()
        node.dispose()
    return node


class TestLifecycleSmoke:
    def test_build_start_stop_teardown_then_build_again_is_clean(
        self, settings: BreezyRuntimeSettings
    ) -> None:
        first = run_one_lifecycle(settings)
        assert first.calls == ["build", "run", "dispose"]
        assert len(first.trader.added_actors) == len(SITES)

        # Same `state_db_path`, same `catalog_base`: this second cycle
        # proves the process-wide slot AND the sqlite handle from the FIRST
        # cycle were genuinely released, not merely marked closed -- a
        # supervisor restart depends on exactly this.
        second = run_one_lifecycle(settings)
        assert second.calls == ["build", "run", "dispose"]
        assert len(second.trader.added_actors) == len(SITES)
        assert second is not first

    def test_a_second_runtime_entered_while_the_first_is_still_open_fails_loudly(
        self, settings: BreezyRuntimeSettings
    ) -> None:
        """The single-process guard, proven at the FULL lifecycle level.

        A built and running node still holds the process slot, so a second,
        overlapping `ingest_runtime` must be refused loudly -- never
        silently produce two live runtimes against the same state db and
        catalog.
        """
        with ingest_runtime(settings, clock=make_clock(), probe=local_probe) as runtime:
            node = build_ingest_node(runtime, node_factory=RecordingNode)
            node.build()
            node.run()

            with (
                pytest.raises(DuplicateSharedIngestStateError),
                ingest_runtime(settings, clock=make_clock(), probe=local_probe),
            ):
                pytest.fail("a second concurrent runtime must never be constructed")

            node.dispose()

        # The guard did not wedge the process: after the FIRST runtime's own
        # (single) teardown, a fresh entry over the same paths still works.
        third = run_one_lifecycle(settings)
        assert third.calls == ["build", "run", "dispose"]
