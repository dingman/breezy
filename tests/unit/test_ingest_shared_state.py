"""Tests for the process-wide shared-state owner (`breezy.ingest.shared_state`).

Governing ruling: `docs/plans/PHASE1_ACTOR_BRIEF.md` SS3.6 and SS6 step 0.

Three invariants are load-bearing here and each is tested as an invariant, not
as a convention:

1. **One instance per process.** A second independent construction must fail
   loudly, because a silent second container hands four of the five Actors a
   gate that cannot see the UA-trap latch the fifth just set.
2. **The cross-site 403 window fires on distinct SITES, in-window, per cause.**
   Never on one site's retry loop, never across unrelated 403 classes.
3. **The two deployment preconditions run at startup, once, never at import.**
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

import pytest

from breezy.ingest.gate import (
    GateState,
    InMemoryStateStore,
    SettlementGate,
    StateStore,
)
from breezy.ingest.product_index import ProductIntegrityIndex
from breezy.ingest.shared_state import (
    DEFAULT_BURST_POLICY,
    FORBIDDEN_403_CAUSE,
    CrossSite403Window,
    CrossSiteBurstPolicy,
    DuplicateSharedIngestStateError,
    DuplicateSiteRegistrationError,
    ForeignComponentError,
    SharedIngestState,
    SiteSetError,
    UnknownSiteError,
)
from breezy.persistence.catalog import (
    FilesystemLocality,
    FilesystemProbe,
    WriterLockFilesystemError,
    station_catalog_path,
)
from breezy.persistence.state_store import (
    FileStateStore,
    StateStoreError,
)
from breezy.registry.sites import SiteRegistry, default_registry

VENUE = "polymarket_us"
NYC = (VENUE, "NYC")
SFO = (VENUE, "SFO")
MIA = (VENUE, "MIA")
MDW = (VENUE, "MDW")
LAX = (VENUE, "LAX")
ALL_SITES = (NYC, SFO, MIA, MDW, LAX)

SECOND = 1_000_000_000
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64


# ---------------------------------------------------------------------------
# Fixtures / doubles
# ---------------------------------------------------------------------------


class FakeClock:
    """Injectable nanosecond clock, mirroring the `Callable[[], int]` seam."""

    def __init__(self, now: int = 1_700_000_000 * SECOND) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now

    def advance(self, ns: int) -> None:
        self.now += ns


class RecordingProbe:
    """A `probe_filesystem` stand-in whose verdict is fixed and whose calls are
    recorded, so per-station-root probing is assertable without a real mount.
    """

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


@pytest.fixture(autouse=True)
def _default_breezy_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test in this module a contact env var, by default.

    `HttpTransport` (built internally by `SharedIngestState`) now fails fast
    at construction when no contact is configured -- see
    `breezy.ingest.http.MissingContactError` and the RED/GREEN pair in
    `tests/unit/test_http_transport.py` that pins that behaviour. None of the
    tests in this module are testing UA behaviour, so rather than pass
    `user_agent=` through every `make_state()` call site, this autouse
    fixture supplies a default `BREEZY_USER_AGENT` for the whole module.
    """
    monkeypatch.setenv("BREEZY_USER_AGENT", "breezy-test/1.0 (+mailto:breezy@jonathan.vc)")


@pytest.fixture
def registry() -> SiteRegistry:
    return default_registry()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store() -> InMemoryStateStore:
    return InMemoryStateStore()


@pytest.fixture
def probe() -> RecordingProbe:
    return RecordingProbe()


@pytest.fixture
def make_state(
    registry: SiteRegistry,
    clock: FakeClock,
    store: InMemoryStateStore,
    probe: RecordingProbe,
    tmp_path: Path,
) -> Iterator[Callable[..., SharedIngestState]]:
    """Build a `SharedIngestState` with sane defaults, disposing every instance
    it created afterwards so the process-wide slot never leaks between tests.
    """
    created: list[SharedIngestState] = []

    def _make(**overrides: object) -> SharedIngestState:
        kwargs: dict[str, object] = {
            "registry": registry,
            "sites": ALL_SITES,
            "catalog_base": tmp_path / "nws",
            "store": store,
            "clock": clock,
            # The `store` fixture is an `InMemoryStateStore` -- not durable --
            # so every test that does not care about the durability
            # precondition opts out of it explicitly here. Tests that DO care
            # (below) override this back to `True` against a real
            # `FileStateStore`.
            "require_durable_store": False,
            "probe": probe,
        }
        kwargs.update(overrides)
        state = SharedIngestState(**kwargs)  # type: ignore[arg-type]
        created.append(state)
        return state

    yield _make

    for state in created:
        state.dispose()


# ---------------------------------------------------------------------------
# Invariant 1 -- exactly one instance per process
# ---------------------------------------------------------------------------


def test_a_second_independent_construction_fails_loudly(
    make_state: Callable[..., SharedIngestState],
) -> None:
    make_state()

    with pytest.raises(DuplicateSharedIngestStateError) as excinfo:
        make_state()

    assert "already" in str(excinfo.value).lower()


def test_dispose_releases_the_process_slot(
    make_state: Callable[..., SharedIngestState],
) -> None:
    first = make_state()
    first.dispose()

    second = make_state()

    assert second is not first


def test_dispose_is_idempotent(make_state: Callable[..., SharedIngestState]) -> None:
    state = make_state()

    state.dispose()
    state.dispose()

    assert make_state() is not state


def test_a_disposed_instance_cannot_release_its_successors_slot(
    make_state: Callable[..., SharedIngestState],
) -> None:
    """The exact hazard a naive `_INSTANCE = None` in `dispose` creates: a stale
    handle silently unlocking the slot the live container is holding.
    """
    first = make_state()
    first.dispose()
    second = make_state()

    first.dispose()

    with pytest.raises(DuplicateSharedIngestStateError):
        make_state()
    assert second.gate is not None


def test_a_failed_startup_precondition_does_not_wedge_the_process(
    make_state: Callable[..., SharedIngestState],
) -> None:
    """A misconfigured deployment must fail LOUDLY and then be fixable in place;
    leaving the process slot claimed by a half-built container would turn one
    config error into an unrecoverable one.
    """
    with pytest.raises(StateStoreError):
        # The `store` fixture is an `InMemoryStateStore`; `require_durable_store`
        # (opted out of by every other test's `make_state` defaults) proves it
        # is not durable and refuses to start.
        make_state(require_durable_store=True)

    state = make_state()

    assert state.sites == ALL_SITES


# ---------------------------------------------------------------------------
# Invariant 3 -- startup preconditions, once, never at import
# ---------------------------------------------------------------------------


def test_a_non_durable_store_is_rejected_at_construction(
    make_state: Callable[..., SharedIngestState],
) -> None:
    """The replacement for the declined Cache-backed precondition:
    `SharedIngestState` must refuse to start unless `store` is a genuinely
    durable `FileStateStore` with its startup lock held -- an in-memory (or
    otherwise non-durable) stand-in would let the `ua_trap_blocked` halt
    latch be silently lost on every restart, which is exactly the failure
    mode `assert_state_store_durable` exists to catch.
    """
    with pytest.raises(StateStoreError):
        make_state(require_durable_store=True)


def test_a_genuinely_durable_store_satisfies_the_precondition(
    make_state: Callable[..., SharedIngestState],
    tmp_path: Path,
) -> None:
    store = FileStateStore(tmp_path / "durable-state" / "state.json")
    try:
        state = make_state(store=store, require_durable_store=True)
        assert state.store is store
    finally:
        store.close()


def test_require_durable_store_false_opts_out_for_a_non_durable_double(
    make_state: Callable[..., SharedIngestState],
    store: InMemoryStateStore,
) -> None:
    """The explicit opt-out every other test in this module relies on via
    `make_state`'s defaults, pinned directly: `require_durable_store=False`
    must let a non-durable double through construction.
    """
    state = make_state(require_durable_store=False)

    assert state.store is store


def test_writer_lock_filesystem_is_probed_once_per_station_root(
    make_state: Callable[..., SharedIngestState],
    probe: RecordingProbe,
    tmp_path: Path,
) -> None:
    make_state()

    expected = [station_catalog_path(tmp_path / "nws", venue, city) for venue, city in ALL_SITES]
    assert probe.paths == expected


def test_a_network_filesystem_station_root_fails_closed(
    make_state: Callable[..., SharedIngestState],
    registry: SiteRegistry,
) -> None:
    with pytest.raises(WriterLockFilesystemError):
        make_state(probe=RecordingProbe(FilesystemLocality.NETWORK))


def test_an_undetermined_filesystem_station_root_fails_closed(
    make_state: Callable[..., SharedIngestState],
) -> None:
    with pytest.raises(WriterLockFilesystemError):
        make_state(probe=RecordingProbe(FilesystemLocality.UNDETERMINED))


def test_neither_precondition_is_an_import_time_side_effect() -> None:
    """Structural, not behavioural: the brief forbids import-time execution, and
    a behavioural test cannot distinguish "not called at import" from "called at
    import in a previous test that already imported the module".
    """
    from breezy.ingest import shared_state

    guarded = {
        "assert_state_store_durable",
        "assert_writer_lock_filesystem_supported",
        "probe_filesystem",
        "station_catalog_path",
        "default_registry",
        "load_registry",
    }
    tree = ast.parse(inspect.getsource(shared_state))

    called_at_module_scope: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                func = inner.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                called_at_module_scope.add(name)

    assert not (called_at_module_scope & guarded)


# ---------------------------------------------------------------------------
# Shared components -- identity, registration, one store, one clock
# ---------------------------------------------------------------------------


def test_the_shared_components_are_stable_singletons(
    make_state: Callable[..., SharedIngestState],
) -> None:
    state = make_state()

    assert state.gate is state.gate
    assert state.product_index is state.product_index
    assert state.transport is state.transport
    assert isinstance(state.gate, SettlementGate)
    assert isinstance(state.product_index, ProductIntegrityIndex)


def test_all_five_actors_register_against_one_state(
    make_state: Callable[..., SharedIngestState],
) -> None:
    state = make_state()

    for venue, city in ALL_SITES:
        state.register_site_actor(
            venue,
            city,
            component_id=f"NWS-{city}",
            gate=state.gate,
            product_index=state.product_index,
        )

    assert state.registered_sites() == ALL_SITES


def test_registering_a_foreign_gate_fails_loudly(
    make_state: Callable[..., SharedIngestState],
    store: InMemoryStateStore,
    clock: FakeClock,
) -> None:
    state = make_state()
    impostor = SettlementGate(store=store, clock=clock, sites=frozenset(ALL_SITES))

    with pytest.raises(ForeignComponentError) as excinfo:
        state.register_site_actor(
            *NYC, component_id="NWS-NYC", gate=impostor, product_index=state.product_index
        )

    assert "gate" in str(excinfo.value)


def test_registering_a_foreign_product_index_fails_loudly(
    make_state: Callable[..., SharedIngestState],
    store: InMemoryStateStore,
    clock: FakeClock,
) -> None:
    state = make_state()
    impostor = ProductIntegrityIndex(store=store, clock=clock)

    with pytest.raises(ForeignComponentError) as excinfo:
        state.register_site_actor(
            *NYC, component_id="NWS-NYC", gate=state.gate, product_index=impostor
        )

    assert "product_index" in str(excinfo.value)


def test_a_second_actor_for_one_station_fails_loudly(
    make_state: Callable[..., SharedIngestState],
) -> None:
    state = make_state()
    state.register_site_actor(
        *NYC, component_id="NWS-NYC", gate=state.gate, product_index=state.product_index
    )

    with pytest.raises(DuplicateSiteRegistrationError):
        state.register_site_actor(
            *NYC, component_id="NWS-NYC-2", gate=state.gate, product_index=state.product_index
        )


def test_registering_an_unconfigured_site_fails_loudly(
    make_state: Callable[..., SharedIngestState],
) -> None:
    state = make_state(sites=(NYC,))

    with pytest.raises(UnknownSiteError):
        state.register_site_actor(
            *SFO, component_id="NWS-SFO", gate=state.gate, product_index=state.product_index
        )


def test_gate_and_index_share_one_store_without_key_collision(
    make_state: Callable[..., SharedIngestState],
    store: InMemoryStateStore,
) -> None:
    state = make_state()

    state.gate.record_successful_poll(*NYC, detail="ok")
    state.product_index.observe("11111111-1111-4111-8111-111111111111", DIGEST_A)

    keys = set(store._data)
    gate_keys = {k for k in keys if k.startswith("gate:")}
    index_keys = {k for k in keys if k.startswith("productidx:")}

    assert gate_keys
    assert index_keys
    assert not (gate_keys & index_keys)
    assert gate_keys | index_keys == keys


def test_a_second_gate_over_the_same_store_sees_the_shared_state(
    make_state: Callable[..., SharedIngestState],
    store: InMemoryStateStore,
    clock: FakeClock,
) -> None:
    """The store is genuinely shared -- proof that the container's store, not a
    private copy, is what the gate writes through.
    """
    state = make_state()
    state.gate.record_successful_poll(*NYC, detail="ok")

    observer = SettlementGate(store=store, clock=clock, sites=frozenset(ALL_SITES))

    assert observer.status(*NYC).state is GateState.OPEN


def test_one_clock_drives_the_gate_the_index_and_the_transport(
    make_state: Callable[..., SharedIngestState],
    clock: FakeClock,
) -> None:
    state = make_state()
    clock.advance(7 * SECOND)

    gate_status = state.gate.record_successful_poll(*NYC, detail="ok")
    index_result = state.product_index.observe("22222222-2222-4222-8222-222222222222", DIGEST_A)

    assert gate_status.at_ns == clock.now
    assert index_result.observed_at_ns == clock.now
    assert state.clock is clock
    # `HttpTransport` exposes no public clock accessor and this identity is
    # load-bearing (the receipt stamp that becomes `ts_init` must come from the
    # same clock the freshness watchdog reads), so it is asserted directly.
    assert state.transport._clock is clock


def test_station_root_matches_the_catalog_helper(
    make_state: Callable[..., SharedIngestState],
    tmp_path: Path,
) -> None:
    state = make_state()

    assert state.station_root(*MDW) == station_catalog_path(tmp_path / "nws", *MDW)


def test_station_root_rejects_an_unconfigured_site(
    make_state: Callable[..., SharedIngestState],
) -> None:
    state = make_state(sites=(NYC,))

    with pytest.raises(UnknownSiteError):
        state.station_root(*LAX)


# ---------------------------------------------------------------------------
# Site-set validation
# ---------------------------------------------------------------------------


def test_an_empty_site_set_is_rejected(make_state: Callable[..., SharedIngestState]) -> None:
    with pytest.raises(SiteSetError):
        make_state(sites=())


def test_a_duplicated_site_is_rejected(make_state: Callable[..., SharedIngestState]) -> None:
    with pytest.raises(SiteSetError):
        make_state(sites=(NYC, NYC))


def test_a_site_absent_from_the_registry_is_rejected(
    make_state: Callable[..., SharedIngestState],
) -> None:
    with pytest.raises(SiteSetError):
        make_state(sites=(NYC, (VENUE, "PHL")))


# ---------------------------------------------------------------------------
# Invariant 2 -- the cross-site 403 burst window
# ---------------------------------------------------------------------------


def make_window(clock: FakeClock, **policy: int) -> CrossSite403Window:
    kwargs = {"window_ns": 120 * SECOND, "site_threshold": 2}
    kwargs.update(policy)
    return CrossSite403Window(clock=clock, policy=CrossSiteBurstPolicy(**kwargs))


def test_a_single_site_403_is_not_a_burst(clock: FakeClock) -> None:
    window = make_window(clock)

    assert window.observe(*NYC, cause=FORBIDDEN_403_CAUSE) is False


def test_one_sites_retry_loop_can_never_manufacture_a_burst(clock: FakeClock) -> None:
    """The load-bearing asymmetry: repeated 403s from ONE city are exactly the
    per-site abuse block the gate already degrades on. Counting events rather
    than distinct sites would let a single city's retry loop halt all five.
    """
    window = make_window(clock)

    results = []
    for _ in range(20):
        results.append(window.observe(*NYC, cause=FORBIDDEN_403_CAUSE))
        clock.advance(SECOND)

    assert not any(results)


def test_the_burst_fires_at_the_site_threshold(clock: FakeClock) -> None:
    window = make_window(clock)

    assert window.observe(*NYC, cause=FORBIDDEN_403_CAUSE) is False
    clock.advance(30 * SECOND)
    assert window.observe(*SFO, cause=FORBIDDEN_403_CAUSE) is True


def test_the_burst_does_not_fire_below_a_raised_threshold(clock: FakeClock) -> None:
    window = make_window(clock, site_threshold=3)

    assert window.observe(*NYC, cause=FORBIDDEN_403_CAUSE) is False
    assert window.observe(*SFO, cause=FORBIDDEN_403_CAUSE) is False
    assert window.observe(*MIA, cause=FORBIDDEN_403_CAUSE) is True


def test_the_burst_fires_on_the_last_nanosecond_inside_the_window(clock: FakeClock) -> None:
    window = make_window(clock)
    window.observe(*NYC, cause=FORBIDDEN_403_CAUSE)

    clock.advance(120 * SECOND - 1)

    assert window.observe(*SFO, cause=FORBIDDEN_403_CAUSE) is True


def test_the_burst_does_not_fire_exactly_at_the_window_edge(clock: FakeClock) -> None:
    window = make_window(clock)
    window.observe(*NYC, cause=FORBIDDEN_403_CAUSE)

    clock.advance(120 * SECOND)

    assert window.observe(*SFO, cause=FORBIDDEN_403_CAUSE) is False


def test_the_window_is_per_cause_and_unrelated_403s_cannot_trip_it(clock: FakeClock) -> None:
    window = make_window(clock)

    assert window.observe(*NYC, cause=FORBIDDEN_403_CAUSE) is False
    assert window.observe(*SFO, cause="product_forbidden") is False
    assert window.observe(*MIA, cause="product_forbidden") is True


def test_a_second_cause_does_not_disturb_a_live_window(clock: FakeClock) -> None:
    window = make_window(clock)
    window.observe(*NYC, cause=FORBIDDEN_403_CAUSE)
    window.observe(*SFO, cause="product_forbidden")

    assert window.observe(*MIA, cause=FORBIDDEN_403_CAUSE) is True


def test_a_future_dated_observation_stays_in_window(clock: FakeClock) -> None:
    """A backward clock jump must not silently evict evidence. Keeping a
    future-dated observation biases toward halting, which is the cheap error.
    """
    window = make_window(clock)
    window.observe(*NYC, cause=FORBIDDEN_403_CAUSE)

    clock.now -= 10 * SECOND

    assert window.observe(*SFO, cause=FORBIDDEN_403_CAUSE) is True


def test_active_sites_reports_only_in_window_observations(clock: FakeClock) -> None:
    window = make_window(clock)
    window.observe(*NYC, cause=FORBIDDEN_403_CAUSE)
    clock.advance(60 * SECOND)
    window.observe(*SFO, cause=FORBIDDEN_403_CAUSE)

    assert window.active_sites(cause=FORBIDDEN_403_CAUSE) == (NYC, SFO)

    clock.advance(61 * SECOND)

    assert window.active_sites(cause=FORBIDDEN_403_CAUSE) == (SFO,)
    assert window.active_sites(cause="never_seen") == ()


def test_a_blank_cause_is_rejected(clock: FakeClock) -> None:
    window = make_window(clock)

    with pytest.raises(ValueError, match="cause"):
        window.observe(*NYC, cause="  ")


@pytest.mark.parametrize(
    ("window_ns", "site_threshold"),
    [(0, 2), (-1, 2), (SECOND, 1), (SECOND, 0)],
)
def test_an_indefensible_burst_policy_is_rejected(window_ns: int, site_threshold: int) -> None:
    with pytest.raises(ValueError):
        CrossSiteBurstPolicy(window_ns=window_ns, site_threshold=site_threshold)


def test_the_default_policy_is_two_sites_in_two_minutes() -> None:
    assert DEFAULT_BURST_POLICY.site_threshold == 2
    assert DEFAULT_BURST_POLICY.window_ns == 120 * SECOND


# ---------------------------------------------------------------------------
# The window wired to the shared gate
# ---------------------------------------------------------------------------


def test_observe_forbidden_403_rejects_an_unconfigured_site(
    make_state: Callable[..., SharedIngestState],
) -> None:
    state = make_state(sites=(NYC,))

    with pytest.raises(UnknownSiteError):
        state.observe_forbidden_403(*SFO)


def test_a_cross_site_burst_halts_every_site_through_the_shared_gate(
    make_state: Callable[..., SharedIngestState],
    clock: FakeClock,
) -> None:
    """The whole point of the module: one Actor sees one city, but two cities
    403-ing the same way inside the window blocks all five.
    """
    state = make_state()
    # Every site has succeeded before, so the gate's cold-start UA-trap arm is
    # latched off and ONLY the burst signal can classify this as a trap.
    for venue, city in ALL_SITES:
        state.gate.record_successful_poll(venue, city, detail="warmup")

    first = state.observe_forbidden_403(*NYC)
    state.gate.record_forbidden_403(*NYC, detail="403", cross_site_burst_detected=first)
    assert state.gate.status(*LAX).state is GateState.OPEN

    clock.advance(20 * SECOND)
    second = state.observe_forbidden_403(*SFO)
    state.gate.record_forbidden_403(*SFO, detail="403", cross_site_burst_detected=second)

    assert first is False
    assert second is True
    assert state.gate.status(*LAX).state is GateState.BLOCKED
    assert state.gate.status(*MDW).state is GateState.BLOCKED


def test_the_shared_gate_is_wired_with_the_containers_configured_sites(
    make_state: Callable[..., SharedIngestState],
    clock: FakeClock,
) -> None:
    """Wiring test for the composition root: SharedIngestState must construct
    its ONE gate with the container's own (already-validated) site set, not
    an empty/omitted default -- an empty site set would silently disable the
    gate's persisted cross-site-burst derivation with no error and no log,
    the exact footgun shape that caused the original defect. This
    deliberately never calls `observe_forbidden_403` (the legacy in-memory
    window), so ONLY the gate's own persisted-state derivation can be what
    fires -- if the composition root failed to pass a non-empty site set,
    this would silently stay OPEN instead.
    """
    state = make_state(sites=(NYC, SFO))
    state.gate.record_successful_poll(*NYC, detail="warmup")
    state.gate.record_successful_poll(*SFO, detail="warmup")

    state.gate.record_forbidden_403(*NYC, detail="403")  # no cross_site_burst_detected passed
    assert state.gate.status(*SFO).state is GateState.OPEN  # one site alone is not a burst

    clock.advance(20 * SECOND)
    state.gate.record_forbidden_403(*SFO, detail="403")  # no cross_site_burst_detected passed

    assert state.gate.status(*NYC).state is GateState.BLOCKED
    assert state.gate.status(*SFO).state is GateState.BLOCKED


def test_active_forbidden_403_sites_is_readable_for_operators(
    make_state: Callable[..., SharedIngestState],
) -> None:
    state = make_state()
    state.observe_forbidden_403(*MIA)

    assert state.active_forbidden_403_sites() == (MIA,)


def test_burst_policy_is_exposed_for_logging(
    make_state: Callable[..., SharedIngestState],
) -> None:
    policy = CrossSiteBurstPolicy(window_ns=45 * SECOND, site_threshold=4)
    state = make_state(burst_policy=policy)

    assert state.burst_policy is policy


# ---------------------------------------------------------------------------
# Composition-root smoke: exactly what the Actor dispatch will do
# ---------------------------------------------------------------------------


def test_the_container_composes_a_usable_ingest_stack(
    make_state: Callable[..., SharedIngestState],
    store: StateStore,
) -> None:
    state = make_state()
    for venue, city in ALL_SITES:
        state.register_site_actor(
            venue,
            city,
            component_id=f"NWS-{city}",
            gate=state.gate,
            product_index=state.product_index,
        )

    uuid = "33333333-3333-4333-8333-333333333333"
    assert state.product_index.known_digest(uuid) is None
    assert state.product_index.observe(uuid, DIGEST_B).outcome.value == "first_seen"
    assert state.product_index.known_digest(uuid) == DIGEST_B
    assert state.store is store
    assert state.catalog_base.name == "nws"


def test_sites_are_reported_in_configuration_order(
    make_state: Callable[..., SharedIngestState],
) -> None:
    state = make_state(sites=(LAX, NYC))

    assert state.sites == (LAX, NYC)


def test_registered_sites_is_empty_before_any_actor_starts(
    make_state: Callable[..., SharedIngestState],
) -> None:
    state = make_state()

    assert state.registered_sites() == ()


def test_transport_is_built_against_the_weather_gov_host_allowlist(
    make_state: Callable[..., SharedIngestState],
) -> None:
    state = make_state()

    assert state.transport._allowed_hosts == frozenset({"api.weather.gov"})


def test_dispose_clears_site_registrations(
    make_state: Callable[..., SharedIngestState],
) -> None:
    state = make_state()
    state.register_site_actor(
        *NYC, component_id="NWS-NYC", gate=state.gate, product_index=state.product_index
    )

    state.dispose()

    assert state.registered_sites() == ()


def test_sites_accepts_any_sequence(
    make_state: Callable[..., SharedIngestState],
) -> None:
    sites: Sequence[tuple[str, str]] = [NYC, SFO]
    state = make_state(sites=sites)

    assert state.sites == (NYC, SFO)


def test_the_window_exposes_its_own_policy(clock: FakeClock) -> None:
    policy = CrossSiteBurstPolicy(window_ns=SECOND, site_threshold=2)
    window = CrossSite403Window(clock=clock, policy=policy)

    assert window.policy is policy


def test_the_container_shares_one_registry(
    make_state: Callable[..., SharedIngestState],
    registry: SiteRegistry,
) -> None:
    """The registry is the single source of truth for station identity, so every
    Actor must read the same loaded object rather than re-loading `sites.toml`.
    """
    state = make_state()

    assert state.registry is registry
