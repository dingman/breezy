"""Unit tests for `breezy.runtime.composition`.

Nothing here starts a `TradingNode`, opens a socket, or reaches the network.
Every test drives the composition root against a `tmp_path` catalog base and
an injected filesystem probe, exactly as `tests/unit/test_ingest_shared_state.py`
does, so the process-wide `SharedIngestState` slot is always released.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

import pytest

from breezy.ingest.shared_state import (
    DuplicateSharedIngestStateError,
    SharedIngestState,
    SharedIngestStateError,
)
from breezy.persistence.catalog import (
    FilesystemLocality,
    FilesystemProbe,
    WriterLockFilesystemError,
    station_catalog_path,
)
from breezy.registry.sites import SiteRegistry
from breezy.runtime.composition import (
    BreezyIngestRuntime,
    ingest_runtime,
    load_site_registry,
)
from breezy.runtime.settings import BreezyRuntimeSettings
from breezy.runtime.sqlite_store import SqliteStateStore

SITES: tuple[tuple[str, str], ...] = (("polymarket_us", "NYC"), ("polymarket_us", "LAX"))


class RecordingProbe:
    """A `probe_filesystem` stand-in with a fixed verdict and recorded calls."""

    def __init__(self, locality: FilesystemLocality = FilesystemLocality.LOCAL) -> None:
        self.locality = locality
        self.paths: list[Path] = []

    def __call__(self, path: Path) -> FilesystemProbe:
        self.paths.append(Path(path))
        return FilesystemProbe(
            path=str(path),
            mount_point="/",
            fs_type="ext4" if self.locality is FilesystemLocality.LOCAL else "nfs4",
            locality=self.locality,
            detail="fake probe",
        )


class RecordingStore(SqliteStateStore):
    """A real `SqliteStateStore` that records whether `close()` was called."""

    instances: ClassVar[list[RecordingStore]] = []

    def __init__(self, path: Path | str) -> None:
        super().__init__(path)
        self.close_calls = 0
        RecordingStore.instances.append(self)

    def close(self) -> None:
        self.close_calls += 1
        super().close()


@pytest.fixture(autouse=True)
def _reset_recording_stores() -> Iterator[None]:
    RecordingStore.instances = []
    yield
    RecordingStore.instances = []


@pytest.fixture
def probe() -> RecordingProbe:
    return RecordingProbe()


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


# ---------------------------------------------------------------------------
# Registry selection
# ---------------------------------------------------------------------------


class TestLoadSiteRegistry:
    def test_defaults_to_the_packaged_registry(
        self, settings: BreezyRuntimeSettings
    ) -> None:
        registry = load_site_registry(settings)

        assert isinstance(registry, SiteRegistry)
        assert ("polymarket_us", "NYC") in registry.pairs()

    def test_honours_an_explicit_registry_path(
        self, settings: BreezyRuntimeSettings, tmp_path: Path
    ) -> None:
        from breezy.registry.sites import DEFAULT_REGISTRY_PATH

        copied = tmp_path / "sites-copy.toml"
        copied.write_bytes(DEFAULT_REGISTRY_PATH.read_bytes())

        registry = load_site_registry(
            BreezyRuntimeSettings(**{**vars_of(settings), "registry_path": copied})
        )

        assert ("polymarket_us", "NYC") in registry.pairs()

    def test_a_missing_registry_path_fails_loudly(
        self, settings: BreezyRuntimeSettings, tmp_path: Path
    ) -> None:
        missing = tmp_path / "does-not-exist.toml"

        with pytest.raises(FileNotFoundError):
            load_site_registry(
                BreezyRuntimeSettings(**{**vars_of(settings), "registry_path": missing})
            )


def vars_of(settings: BreezyRuntimeSettings) -> dict[str, object]:
    return {
        "trader_id": settings.trader_id,
        "sites": settings.sites,
        "catalog_base": settings.catalog_base,
        "state_db_path": settings.state_db_path,
        "poll_interval_seconds": settings.poll_interval_seconds,
        "parse_timeout_ms": settings.parse_timeout_ms,
        "log_level": settings.log_level,
        "check_proxy_env": settings.check_proxy_env,
        "registry_path": settings.registry_path,
    }


# ---------------------------------------------------------------------------
# Durable state
#
# REPLACES `TestDurableStateAttestation`. That class covered a duck-typed
# `DurableStateAttestation` object the composition root fed to
# `SharedIngestState` so a Cache-persistence assertion would pass -- an object
# that reported a SQLite path as if it were `CacheConfig.database`. It existed
# only because the assertion was unsatisfiable (`CacheConfig.database is not
# None`, while the kernel accepts only 'redis' there and this deployment has no
# Redis) and described the wrong mechanism.
#
# Both the assertion and the workaround are gone. The composition root now
# hands `SharedIngestState` an opener over the REAL store, and durability is
# established by round-trip.
# ---------------------------------------------------------------------------


class TestDurableState:
    def test_the_attestation_workaround_is_gone(self) -> None:
        """A fiction in the startup path of a settlement-critical system must
        not reappear.
        """
        from breezy.runtime import composition

        assert not hasattr(composition, "DurableStateAttestation")
        assert not hasattr(composition, "durable_state_attestation")

    def test_the_composed_runtime_uses_a_genuinely_durable_store(
        self, settings: BreezyRuntimeSettings
    ) -> None:
        """Not a declared flag: the value is written through the live store and
        read back by a NEW store object over the same file, after the runtime
        (and therefore the original connection) has been torn down.
        """
        with ingest_runtime(settings, probe=RecordingProbe()) as runtime:
            runtime.store.set("gate:probe-canary", b"latched")
            assert isinstance(runtime.store, SqliteStateStore)

        with SqliteStateStore(settings.state_db_path) as reopened:
            assert reopened.get("gate:probe-canary") == b"latched"

    def test_a_non_durable_store_factory_fails_startup_closed(
        self, settings: BreezyRuntimeSettings
    ) -> None:
        """The whole point of the replacement guard: a store that accepts every
        write and persists nothing must stop the process, not start it.
        """
        from breezy.ingest.gate import InMemoryStateStore, StateStoreNotDurableError

        def volatile_factory(_path: Path) -> InMemoryStateStore:
            return InMemoryStateStore()

        with (
            pytest.raises(StateStoreNotDurableError),
            ingest_runtime(settings, probe=RecordingProbe(), store_factory=volatile_factory),
        ):
            pass

    def test_a_failed_durability_check_leaks_neither_slot_nor_handle(
        self, settings: BreezyRuntimeSettings
    ) -> None:
        """A misconfigured deployment must stay fixable in place: the
        process-wide `SharedIngestState` slot must be released, so the next
        attempt reports the real cause rather than a duplicate-construction
        error.
        """
        from breezy.ingest.gate import InMemoryStateStore, StateStoreNotDurableError

        def volatile_factory(_path: Path) -> InMemoryStateStore:
            return InMemoryStateStore()

        with (
            pytest.raises(StateStoreNotDurableError),
            ingest_runtime(settings, probe=RecordingProbe(), store_factory=volatile_factory),
        ):
            pass

        with ingest_runtime(settings, probe=RecordingProbe()) as runtime:
            assert runtime.shared.sites == SITES


# ---------------------------------------------------------------------------
# The runtime context manager
# ---------------------------------------------------------------------------


class TestIngestRuntime:
    def test_yields_every_wired_component(
        self, settings: BreezyRuntimeSettings, probe: RecordingProbe
    ) -> None:
        with ingest_runtime(settings, probe=probe) as runtime:
            assert isinstance(runtime, BreezyIngestRuntime)
            assert runtime.settings is settings
            assert isinstance(runtime.registry, SiteRegistry)
            assert isinstance(runtime.store, SqliteStateStore)
            assert isinstance(runtime.shared, SharedIngestState)
            # Zero, not one-per-site: the ingest Actors need a live
            # `SharedIngestState` and are built by `build_ingest_actors` and
            # registered through the native `Trader.add_actor` instead.
            assert runtime.node_config.actors == []

    def test_shared_state_is_backed_by_the_sqlite_store_and_configured_sites(
        self, settings: BreezyRuntimeSettings, probe: RecordingProbe
    ) -> None:
        with ingest_runtime(settings, probe=probe) as runtime:
            assert runtime.shared.store is runtime.store
            assert runtime.shared.sites == SITES
            assert runtime.shared.catalog_base == settings.catalog_base
            assert runtime.shared.registry is runtime.registry

    def test_sqlite_file_lives_at_the_configured_state_db_path(
        self, settings: BreezyRuntimeSettings, probe: RecordingProbe
    ) -> None:
        with ingest_runtime(settings, probe=probe) as runtime:
            runtime.store.set("k", b"v")

        assert settings.state_db_path.exists()

    def test_every_station_root_is_probed(
        self, settings: BreezyRuntimeSettings, probe: RecordingProbe
    ) -> None:
        with ingest_runtime(settings, probe=probe):
            pass

        expected = [
            station_catalog_path(settings.catalog_base, venue, city) for venue, city in SITES
        ]
        assert probe.paths == expected

    def test_normal_exit_disposes_shared_state_and_closes_the_store(
        self, settings: BreezyRuntimeSettings, probe: RecordingProbe
    ) -> None:
        with ingest_runtime(settings, probe=probe, store_factory=RecordingStore) as runtime:
            store = runtime.store
        assert isinstance(store, RecordingStore)
        assert store.close_calls == 1

        # Slot released: a second construction would otherwise raise.
        with ingest_runtime(settings, probe=probe, store_factory=RecordingStore):
            pass

    def test_an_exception_in_the_body_still_disposes_and_closes(
        self, settings: BreezyRuntimeSettings, probe: RecordingProbe
    ) -> None:
        class Boom(Exception):
            pass

        with (
            pytest.raises(Boom),
            ingest_runtime(settings, probe=probe, store_factory=RecordingStore),
        ):
            raise Boom

        assert RecordingStore.instances[-1].close_calls == 1
        with ingest_runtime(settings, probe=probe):
            pass  # slot was released

    def test_a_construction_failure_does_not_leak_the_open_sqlite_handle(
        self, settings: BreezyRuntimeSettings, probe: RecordingProbe
    ) -> None:
        # A network station root is refused by
        # `assert_writer_lock_filesystem_supported`, which runs INSIDE
        # `SharedIngestState.__init__` -- i.e. after the store is already open.
        network_probe = RecordingProbe(FilesystemLocality.NETWORK)

        with (
            pytest.raises(WriterLockFilesystemError),
            ingest_runtime(settings, probe=network_probe, store_factory=RecordingStore),
        ):
            pytest.fail("body must never run")

        assert RecordingStore.instances[-1].close_calls == 1

        # Extend: prove the handle is genuinely RELEASED, not merely that
        # `close()` was invoked once. A real SECOND `ingest_runtime` entry
        # over the SAME `state_db_path`, through the SAME store factory,
        # must succeed and yield a runtime that actually reads and writes
        # through a fresh handle -- not just "does not raise".
        with ingest_runtime(settings, probe=probe, store_factory=RecordingStore) as runtime:
            assert isinstance(runtime.store, RecordingStore)
            runtime.store.set("post-recovery-canary", b"ok")
            assert runtime.store.get("post-recovery-canary") == b"ok"
        assert RecordingStore.instances[-1].close_calls == 1

    def test_a_construction_failure_does_not_leak_the_process_slot(
        self, settings: BreezyRuntimeSettings, probe: RecordingProbe
    ) -> None:
        network_probe = RecordingProbe(FilesystemLocality.NETWORK)

        with (
            pytest.raises(WriterLockFilesystemError),
            ingest_runtime(settings, probe=network_probe),
        ):
            pytest.fail("body must never run")

        # If the slot had leaked, this would raise DuplicateSharedIngestStateError.
        with ingest_runtime(settings, probe=probe) as runtime:
            assert isinstance(runtime.shared, SharedIngestState)

    def test_a_site_absent_from_the_registry_is_refused(
        self, settings: BreezyRuntimeSettings, probe: RecordingProbe
    ) -> None:
        bad = BreezyRuntimeSettings(
            **{**vars_of(settings), "sites": (("polymarket_us", "PHL"),)}
        )

        with (
            pytest.raises(SharedIngestStateError) as excinfo,
            ingest_runtime(bad, probe=probe, store_factory=RecordingStore),
        ):
            pytest.fail("body must never run")

        assert "PHL" in str(excinfo.value)
        assert RecordingStore.instances[-1].close_calls == 1

    def test_two_concurrent_runtimes_are_refused(
        self, settings: BreezyRuntimeSettings, probe: RecordingProbe
    ) -> None:

        # these into one `with` would still enter them left to right, but it would
        # hide the thing under test: that the second construction is refused while
        # the first still holds the process slot.
        with ingest_runtime(settings, probe=probe):  # noqa: SIM117
            with (
                pytest.raises(DuplicateSharedIngestStateError),
                ingest_runtime(settings, probe=probe),
            ):
                pytest.fail("body must never run")

    def test_an_explicit_clock_is_used_verbatim(
        self, settings: BreezyRuntimeSettings, probe: RecordingProbe
    ) -> None:
        # The ONE nanosecond clock reaches the gate, the product index, the
        # transport and the burst window. A per-Actor Nautilus `Clock` cannot
        # serve that role, so this seam must pass exactly what it is given.
        def fixed_clock() -> int:
            return 1_700_000_000_000_000_000

        with ingest_runtime(settings, clock=fixed_clock, probe=probe) as runtime:
            assert runtime.shared.clock is fixed_clock


# ---------------------------------------------------------------------------
# Teardown order, pinned as ONE recorded sequence
#
# `ingest_runtime` owns exactly two teardown steps -- `shared.dispose()` then
# `store.close()` (`composition.py:130`, `:158`; `ExitStack` unwinds LIFO,
# and `store.close` is registered BEFORE `shared.dispose`). Every existing
# test above asserts each step happened in isolation (`close_calls == 1`,
# slot released); none records the two as a single ordered sequence, so a
# regression that silently reordered the two `stack.callback(...)` calls
# would pass the whole suite. The node's OWN `dispose()` is a THIRD step,
# owned by `cli._run_node`'s `finally`, which runs INSIDE this
# contextmanager's `with` block (`cli.py:161-164`) -- see
# `test_runtime_cli.TestTeardownOrder` for the full three-step
# `node.dispose -> shared.dispose -> store.close` sequence pinned together.
# ---------------------------------------------------------------------------


class OrderRecordingStore(SqliteStateStore):
    """A real `SqliteStateStore` that appends `"store.close"` to a shared,
    injected `order` list at the moment `close()` actually runs.
    """

    def __init__(self, path: Path | str, *, order: list[str]) -> None:
        super().__init__(path)
        self._order = order

    def close(self) -> None:
        self._order.append("store.close")
        super().close()


class TestTeardownOrder:
    def test_clean_exit_order_is_shared_dispose_then_store_close(
        self,
        settings: BreezyRuntimeSettings,
        probe: RecordingProbe,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        order: list[str] = []
        original_dispose = SharedIngestState.dispose

        def recording_dispose(self_: SharedIngestState) -> None:
            order.append("shared.dispose")
            original_dispose(self_)

        monkeypatch.setattr(SharedIngestState, "dispose", recording_dispose)

        def factory(path: Path) -> OrderRecordingStore:
            return OrderRecordingStore(path, order=order)

        with ingest_runtime(settings, probe=probe, store_factory=factory) as runtime:
            # Discard whatever the durability probe's SECOND, independent
            # handle recorded during construction -- it is opened and closed
            # entirely inside `SharedIngestState.__init__`
            # (`assert_state_store_durable`), before this body ever runs.
            # Only the TEARDOWN-phase calls are under test here.
            order.clear()
            assert isinstance(runtime.store, OrderRecordingStore)

        assert order == ["shared.dispose", "store.close"]

    def test_body_exception_still_tears_down_in_order_and_the_original_exception_propagates(
        self,
        settings: BreezyRuntimeSettings,
        probe: RecordingProbe,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        order: list[str] = []
        original_dispose = SharedIngestState.dispose

        def recording_dispose(self_: SharedIngestState) -> None:
            order.append("shared.dispose")
            original_dispose(self_)

        monkeypatch.setattr(SharedIngestState, "dispose", recording_dispose)

        def factory(path: Path) -> OrderRecordingStore:
            return OrderRecordingStore(path, order=order)

        class Boom(Exception):
            pass

        raised = Boom("body failed mid-poll")

        with (
            pytest.raises(Boom) as excinfo,
            ingest_runtime(settings, probe=probe, store_factory=factory),
        ):
            order.clear()
            raise raised

        # The ORIGINAL exception object propagates -- not a new one raised
        # during teardown, and not merely "some Boom".
        assert excinfo.value is raised
        assert str(excinfo.value) == "body failed mid-poll"
        assert order == ["shared.dispose", "store.close"]

        # Both the slot and the handle were released even though the body
        # raised: a fresh entry over the same paths succeeds.
        with ingest_runtime(settings, probe=probe) as runtime:
            assert isinstance(runtime.shared, SharedIngestState)


# ---------------------------------------------------------------------------
# Out-of-band bootstrap witness, exercised through the composition root
# itself -- the empirical end-to-end probe: latch the UA trap through a real
# `ingest_runtime`, delete the WHOLE state-DB file, reopen, and confirm the
# gate stays BLOCKED (never re-opens on the next successful poll). See
# `breezy.runtime.bootstrap_witness` for the mechanism.
# ---------------------------------------------------------------------------


class TestBootstrapWitnessThroughTheCompositionRoot:
    def test_first_boot_stamps_the_out_of_band_witness_file(
        self, settings: BreezyRuntimeSettings, probe: RecordingProbe
    ) -> None:
        from breezy.runtime.bootstrap_witness import witness_file_path

        with ingest_runtime(settings, probe=probe):
            pass

        assert witness_file_path(settings.catalog_base).exists()

    def test_whole_file_deletion_of_the_state_db_leaves_the_gate_blocked(
        self, settings: BreezyRuntimeSettings, probe: RecordingProbe
    ) -> None:
        from breezy.ingest.gate import GateReason, GateState

        venue, city = SITES[0]

        with ingest_runtime(settings, probe=probe) as runtime:
            runtime.shared.gate.record_forbidden_403(venue, city, detail="cross-site 403 burst")
            assert runtime.shared.gate.status(venue, city).state is GateState.BLOCKED

        # A botched restore / accidental `rm` of the whole DB, including its
        # WAL-mode siblings. The out-of-band witness file (elsewhere under
        # `catalog_base`) is untouched.
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{settings.state_db_path}{suffix}")
            candidate.unlink(missing_ok=True)
        assert not settings.state_db_path.exists()

        with ingest_runtime(settings, probe=probe) as runtime:
            before_poll = runtime.shared.gate.status(venue, city)
            assert before_poll.state is GateState.BLOCKED
            assert before_poll.reason is GateReason.STATE_STORE_TAMPERED

            after_poll = runtime.shared.gate.record_successful_poll(
                venue, city, detail="ordinary poll after the botched restore"
            )
            assert after_poll.state is GateState.BLOCKED
            assert after_poll.reason is GateReason.STATE_STORE_TAMPERED
            assert after_poll.reason is not GateReason.SUCCESSFUL_POLL

    def test_genuine_first_deployment_still_reaches_open_after_a_poll(
        self, settings: BreezyRuntimeSettings, probe: RecordingProbe
    ) -> None:
        from breezy.ingest.gate import GateState
        from breezy.runtime.bootstrap_witness import witness_file_path

        venue, city = SITES[0]
        assert not settings.state_db_path.exists()
        assert not witness_file_path(settings.catalog_base).exists()

        with ingest_runtime(settings, probe=probe) as runtime:
            status = runtime.shared.gate.record_successful_poll(venue, city, detail="first poll")
            assert status.state is GateState.OPEN
