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
        self, settings: BreezyRuntimeSettings
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
