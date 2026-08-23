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

from breezy.ingest.gate import CachePersistenceMisconfiguredError
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
    DurableStateAttestation,
    durable_state_attestation,
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
# Durable-state attestation (see composition.py for the full rationale)
# ---------------------------------------------------------------------------


class TestDurableStateAttestation:
    def test_names_the_sqlite_file_that_actually_holds_durable_state(
        self, settings: BreezyRuntimeSettings
    ) -> None:
        attestation = durable_state_attestation(settings)

        assert isinstance(attestation, DurableStateAttestation)
        assert attestation.database == str(settings.state_db_path)

    def test_satisfies_the_shared_state_startup_precondition(
        self, settings: BreezyRuntimeSettings
    ) -> None:
        from breezy.ingest.gate import (
            assert_cache_persistence_configured,
            cache_persistence_config_from,
        )

        attestation = durable_state_attestation(settings)
        assert_cache_persistence_configured(
            cache_persistence_config_from(attestation, attestation, attestation)
        )

    def test_the_real_nautilus_node_config_cannot_satisfy_it(
        self, settings: BreezyRuntimeSettings
    ) -> None:
        # UPSTREAM DEFECT, asserted so it fails RED when fixed:
        # `SharedIngestState` asserts Nautilus-Cache persistence, but Breezy's
        # `StateStore` is `SqliteStateStore` (see that module's docstring: the
        # Cache-backed store was rejected on measured evidence). The assertion
        # demands `CacheConfig.database is not None`, and `kernel.py:311-329`
        # accepts only 'redis' there -- so no real, Redis-free node config can
        # ever pass. See `durable_state_attestation` for how this seam responds.
        from breezy.ingest.gate import (
            assert_cache_persistence_configured,
            cache_persistence_config_from,
        )
        from breezy.runtime.node_config import build_node_config

        node_config = build_node_config(settings)

        with pytest.raises(CachePersistenceMisconfiguredError):
            assert_cache_persistence_configured(
                cache_persistence_config_from(
                    node_config, node_config.cache, node_config.exec_engine
                )
            )


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
            assert len(runtime.node_config.actors) == len(SITES)

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
