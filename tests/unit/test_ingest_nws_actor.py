"""Unit tests for `breezy.ingest.nws_actor.NwsIngestActor`.

Governing spec: `docs/plans/archive/PHASE1_ACTOR_BRIEF.md`. Every test below pins one
ruling from that document; the section reference is named in the docstring so a
future edit that "simplifies" a branch fails against the ruling rather than
against a stylistic preference.

No test here performs real network I/O. `respx` intercepts `httpx` at the
transport layer, so the REAL `HttpTransport` -- allowlist, TLS floor, size cap,
digest-before-decode, receipt stamp -- is exercised end to end while no socket
is opened. `tests/conftest.py` blocks sockets outright as a second mechanism.

The four hazards that shape most of these tests:

1. **The settlement gate is a USE-time gate, not a poll gate** (SS6 step 1).
   Gating polls on `require_open` deadlocks on first boot, because the only
   way a site opens is a successful poll. `test_every_blocked_state_still_polls`
   is the regression test for that, and the brief calls it the single most
   important test in this phase.
2. **The timer callback runs on a Rust `_DummyThread`** (SS4.1). There is no
   running loop on it, so the bridge is
   `asyncio.run_coroutine_threadsafe(coro, loop)` with the loop captured in
   `on_start`, and supervision is `fut.exception()` in a done-callback --
   never an exception escaping the callback, which Rust swallows.
3. **`SqliteStateStore` is thread-confined** (`runtime/sqlite_store.py:72-79`).
   Every gate/index call must therefore happen on the loop thread, including
   the ones reached from a done-callback that measurably runs on the
   completing thread.
4. **`WriteOutcome.skipped` is an integrity violation, not a partial success**
   (SS3.4 / SS5). It must never be confused with "already ingested", which
   discovery-time dedupe is supposed to prevent from reaching the write at all.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import inspect
import json
import threading
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from nautilus_trader.cache.base import CacheFacade

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.nws_raw_product import NwsRawProduct
from breezy.ingest import nws_actor as nws_actor_module
from breezy.ingest.config import NwsIngestActorConfig
from breezy.ingest.gate import (
    GateReason,
    GateState,
    InMemoryStateStore,
)
from breezy.ingest.nws_actor import (
    NwsIngestActor,
    nws_climate_day_data_type,
    nws_raw_product_data_type,
)
from breezy.ingest.shared_state import SharedIngestState
from breezy.persistence.catalog import (
    FilesystemLocality,
    FilesystemProbe,
    WriteOutcome,
    open_station_catalog,
    read_climate_days,
    read_raw_products,
)
from breezy.registry.sites import SiteRegistry, default_registry

VENUE = "polymarket_us"
CITY = "NYC"
SITE = (VENUE, CITY)
ALL_SITES = (SITE, (VENUE, "SFO"), (VENUE, "MIA"), (VENUE, "MDW"), (VENUE, "LAX"))

SECOND = 1_000_000_000
BASE_URL = "https://api.weather.gov"
DISCOVERY_URL = f"{BASE_URL}/products/types/CLI/locations/NYC"

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "nws"

NYC_FINAL = "nyc_final_2026-08-21"
NYC_PRELIM = "nyc_preliminary_2026-08-21"
MIA_FINAL = "mia_final_2026-08-21"

# The NYC final for climate day 2026-08-21 was issued 2026-08-22T06:26Z and
# retrieved five minutes later. Both instants are read from the fixture's own
# meta.json rather than restated, so a fixture refresh cannot silently desync.
_NOW_NS = int(dt.datetime(2026, 8, 22, 6, 31, tzinfo=dt.UTC).timestamp()) * SECOND


# ---------------------------------------------------------------------------
# Fixtures and doubles
# ---------------------------------------------------------------------------


def load_product_text(dirname: str) -> str:
    return (FIXTURES_DIR / dirname / "product.txt").read_text()


def load_meta(dirname: str) -> dict[str, Any]:
    meta: dict[str, Any] = json.loads((FIXTURES_DIR / dirname / "meta.json").read_text())
    return meta


class FakeClock:
    """Injectable nanosecond clock -- the `Callable[[], int]` seam every
    Breezy component takes, so a stamped instant is assertable exactly."""

    def __init__(self, now: int = _NOW_NS) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now

    def advance(self, ns: int) -> None:
        self.now += ns


class RecordingStateStore(InMemoryStateStore):
    """`InMemoryStateStore` that records every write, in order.

    The resume cursor and the conditional-GET validators live HERE, in
    Breezy's own `StateStore`, not in the Nautilus `Cache`: `Cache.add`
    forwards to a database only `if self._database is not None`
    (`cache/cache.pyx:1704-1708`) and Breezy configures
    `CacheConfig(database=None)` (`runtime/node_config.py:150`), so a cursor
    kept there is a plain dict that dies with the process. Recording the
    write ORDER is what lets a test assert the cursor was durable AT THE
    MOMENT OF THE KILL rather than merely observing over-publication
    afterwards -- the latter passes whether or not the write happened.
    """

    def __init__(self, data: dict[str, bytes], writes: list[tuple[str, bytes]]) -> None:
        super().__init__(data)
        self.writes = writes

    def set(self, key: str, value: bytes) -> None:
        super().set(key, value)
        self.writes.append((key, value))


def durable_store_pair() -> tuple[RecordingStateStore, Callable[[], RecordingStateStore]]:
    """A store plus an opener over the SAME backing dict.

    `SharedIngestState` now proves durability by round-trip through an
    independent handle on the store's backing medium, replacing the three
    fake Nautilus config objects this module used to build (that guard
    required `CacheConfig.database is not None`, which no Redis-free node
    config can satisfy, and it described the Cache -- which is not what backs
    `StateStore`).
    """
    backing: dict[str, bytes] = {}
    writes: list[tuple[str, bytes]] = []
    return (
        RecordingStateStore(backing, writes),
        lambda: RecordingStateStore(backing, writes),
    )


def _local_probe(path: Path) -> FilesystemProbe:
    return FilesystemProbe(
        path=str(path),
        mount_point="/",
        fs_type="ext4",
        locality=FilesystemLocality.LOCAL,
        detail="fake probe",
    )


class FakeCache(CacheFacade):  # type: ignore[misc]
    """A `CacheFacade` stand-in for `register_base`'s `cache` slot.

    `register_base` hard type-checks its four arguments, so this must be a
    real `CacheFacade` subclass rather than a duck type. Nothing in Breezy
    stores state through it: the resume cursor and the conditional-GET
    validators live in `RecordingStateStore` above. Writes are still recorded
    so a test can assert this cache stays EMPTY -- a regression back onto
    `Cache` would be silent otherwise, and silently non-durable.
    """

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}
        self.writes: list[tuple[str, bytes]] = []

    def add(self, key: str, value: bytes) -> None:
        self.store[key] = value
        self.writes.append((key, value))

    def get(self, key: str) -> bytes | None:
        return self.store.get(key)


@pytest.fixture
def registry() -> SiteRegistry:
    return default_registry()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store_pair() -> tuple[RecordingStateStore, Callable[[], RecordingStateStore]]:
    return durable_store_pair()


@pytest.fixture
def store(
    store_pair: tuple[RecordingStateStore, Callable[[], RecordingStateStore]],
) -> RecordingStateStore:
    return store_pair[0]


@pytest.fixture
def shared(
    registry: SiteRegistry,
    clock: FakeClock,
    store_pair: tuple[RecordingStateStore, Callable[[], RecordingStateStore]],
    tmp_path: Path,
) -> Iterator[SharedIngestState]:
    store, store_opener = store_pair
    state = SharedIngestState(
        registry=registry,
        sites=ALL_SITES,
        catalog_base=tmp_path / "nws",
        store=store,
        clock=clock,
        store_opener=store_opener,
        probe=_local_probe,
        check_proxy_env=False,
    )
    try:
        yield state
    finally:
        state.dispose()


@pytest.fixture
def actor(shared: SharedIngestState, clock: FakeClock) -> Iterator[NwsIngestActor]:
    """A registered Actor with test doubles in the four `register_base` slots.

    `TestComponentStubs` supplies a real `Cache`/`MessageBus` elsewhere in this
    suite; here the cache is a recording double so a test can assert Breezy
    writes NOTHING through it.
    """
    instance = build_actor(shared)
    try:
        yield instance
    finally:
        instance.shutdown_executor()


def build_actor(shared: SharedIngestState, **config_overrides: Any) -> NwsIngestActor:
    """Construct and register one Actor, capturing its publications.

    `register_base` is Nautilus's own system wiring (`common/actor.pyx:691`)
    and hard type-checks its four arguments, which is why `FakeCache`
    subclasses `CacheFacade` rather than duck-typing it.
    """
    from nautilus_trader.common.component import TestClock
    from nautilus_trader.test_kit.stubs.component import TestComponentStubs

    kwargs: dict[str, Any] = {"venue": VENUE, "city": CITY, "poll_interval_seconds": 300}
    kwargs.update(config_overrides)
    instance = NwsIngestActor(config=NwsIngestActorConfig(**kwargs), shared=shared)
    instance.sleep_between_product_fetches = _no_product_fetch_sleep
    instance.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=FakeCache(),
        clock=TestClock(),
    )
    published: list[tuple[Any, Any]] = []
    instance.publish_data = lambda data_type, data: published.append(
        (data_type, data)
    )
    instance.published = published
    return instance


async def _no_product_fetch_sleep(_delay_seconds: float) -> None:
    """Unit tests opt out of production pacing unless they assert it directly."""


def discovery_payload(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"@graph": list(entries)}


def discovery_entry(dirname: str) -> dict[str, Any]:
    meta = load_meta(dirname)
    return {
        "id": meta["product_id"],
        "productCode": "CLI",
        "issuingOffice": meta["issuing_office"],
        "wmoCollectiveId": meta["wmo_collective_id"],
        "issuanceTime": meta["issuance_time"],
    }


def product_payload(dirname: str) -> dict[str, Any]:
    entry = discovery_entry(dirname)
    entry["productText"] = load_product_text(dirname)
    return entry


def product_url(dirname: str) -> str:
    return f"{BASE_URL}/products/{load_meta(dirname)['product_id']}"


def mock_discovery(mock: respx.MockRouter, *dirnames: str, **kwargs: Any) -> Any:
    payload = discovery_payload(*(discovery_entry(d) for d in dirnames))
    return mock.get(DISCOVERY_URL).mock(
        return_value=httpx.Response(200, json=payload, **kwargs)
    )


def mock_product(mock: respx.MockRouter, dirname: str) -> Any:
    return mock.get(product_url(dirname)).mock(
        return_value=httpx.Response(200, json=product_payload(dirname))
    )


def _called_attribute_names(module: Any) -> set[str]:
    """Every attribute/function NAME this module actually calls.

    An AST walk, not a substring scan: `request_data` and `register_catalog`
    are named in the module docstring precisely to explain why they are NOT
    used, and a text search cannot tell documentation from a call site.
    """
    import ast

    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            names.add(func.attr)
        elif isinstance(func, ast.Name):
            names.add(func.id)
    return names


# ---------------------------------------------------------------------------
# SS3.6 / SS6 step 0 -- startup invariants
# ---------------------------------------------------------------------------


def test_actor_registers_itself_with_the_shared_container(
    shared: SharedIngestState, actor: NwsIngestActor
) -> None:
    """SS3.6: "all five Actors hold the same gate object" is an ASSERTED
    startup invariant, not a convention. Registration proves the Actor holds
    the container's own gate and index."""
    assert shared.registered_sites() == (SITE,)


def test_actor_uses_the_containers_gate_and_index_objects(
    shared: SharedIngestState, actor: NwsIngestActor
) -> None:
    """A private gate would make the UA-trap latch per-Actor, which is the
    entire failure SS3.6 exists to prevent."""
    assert actor.gate is shared.gate
    assert actor.product_index is shared.product_index


def test_actor_does_not_construct_its_own_gate_or_index(
    shared: SharedIngestState, registry: SiteRegistry, clock: FakeClock
) -> None:
    """A second Actor for an already-claimed station is a deployment defect --
    the catalog's writer lock treats a second writer as one."""
    from breezy.ingest.shared_state import DuplicateSiteRegistrationError

    cfg = NwsIngestActorConfig(venue=VENUE, city=CITY)
    with pytest.raises(DuplicateSiteRegistrationError):
        NwsIngestActor(config=cfg, shared=shared)
        NwsIngestActor(config=cfg, shared=shared)


def test_module_registers_zero_catalogs_and_defines_no_historical_handler() -> None:
    """F1 + F3: register ZERO catalogs with the `DataEngine` and never call
    `request_data`. F3 is the dangerous one -- `_query_catalog` stops at the
    first registered catalog that returns rows, so with one catalog root per
    station, stations 2..N would silently warm-start from station 1's records.
    That is confidently wrong data, not a missing feature. Consequence:
    `on_historical_data` is never called, so it must not exist as dead code."""
    called = _called_attribute_names(nws_actor_module)
    assert "register_catalog" not in called
    assert "request_data" not in called
    assert "on_historical_data" not in NwsIngestActor.__dict__
    assert not hasattr(NwsIngestActor, "_query_catalog")


def test_module_never_uses_actor_run_in_executor() -> None:
    """F2: `Actor.run_in_executor` returns a `TaskId` only. In no-executor mode
    the callable's return value is DISCARDED, and there is no result channel
    reachable through the `Actor` public API -- so it cannot host work whose
    result the Actor needs. Catalog I/O goes through the stdlib
    `loop.run_in_executor`, which is unaffected by F2."""
    called = _called_attribute_names(nws_actor_module)
    assert "run_in_executor" in called, "the stdlib loop.run_in_executor IS used"
    source = inspect.getsource(nws_actor_module)
    assert "self.run_in_executor" not in source
    assert "loop.run_in_executor(" in source


# ---------------------------------------------------------------------------
# SS4.1 -- the timer callback runs on a Rust thread
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_start_captures_the_running_loop(actor: NwsIngestActor) -> None:
    """SS4.1: base `Actor` exposes NO loop attribute, and the only non-private
    route to one is `asyncio.get_running_loop()` inside `on_start`, which a
    live kernel awaits on the loop thread."""
    actor.on_start()
    assert actor.loop is asyncio.get_running_loop()


@pytest.mark.asyncio
async def test_on_start_warm_start_failure_reaches_the_gate(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """HIGH defect: `on_start` used to fire `warm_start()` via a bare
    `create_task`, so a corrupt catalog / permission error / disk-full
    exception during warm start vanished into "Task exception was never
    retrieved" -- no `GateReason` recorded, the site left un-blocked.

    This goes through the REAL `on_start` wiring (unlike every other
    warm-start test, which calls `actor.warm_start()` directly and bypasses
    the scheduling entirely) and lets the event loop actually run the
    scheduled task to completion. It must be supervised exactly like the poll
    path: the exception has to reach `GateReason.TASK_DEATH` and BLOCK the
    site, not merely get logged.
    """

    async def _boom() -> None:
        raise ValueError("warm start exploded")

    actor.warm_start = _boom  # type: ignore[method-assign]
    actor.on_start()
    for _ in range(200):
        await asyncio.sleep(0.01)
        if GateReason.TASK_DEATH in shared.gate.blocking_causes(VENUE, CITY):
            break
    assert GateReason.TASK_DEATH in shared.gate.blocking_causes(VENUE, CITY)
    assert shared.gate.status(VENUE, CITY).state is GateState.BLOCKED


def test_on_start_without_a_running_loop_schedules_no_poll_timer(
    actor: NwsIngestActor,
) -> None:
    """SS4.1: in a backtest `get_running_loop()` raises, which is the correct
    signal that the bridge is not needed. Exit criterion: a backtest performs
    NO network I/O -- so no poll timer is armed at all."""
    actor.on_start()
    assert actor.loop is None
    assert actor.poll_timer_armed is False


@pytest.mark.asyncio
async def test_timer_callback_submits_from_a_foreign_thread(
    actor: NwsIngestActor,
) -> None:
    """SS4.1 measured: `asyncio.create_task` raises `RuntimeError: no running
    event loop` on the timer thread. `run_coroutine_threadsafe` is the only
    primitive that works AND returns a handle -- and the handle IS the
    supervision seam that drives the gate to BLOCKED."""
    actor.on_start()
    calls: list[str] = []

    async def _fake_poll() -> None:
        calls.append(threading.current_thread().name)

    actor.poll_once = _fake_poll  # type: ignore[method-assign]

    done = threading.Event()

    def _fire() -> None:
        actor.on_poll_timer(object())
        done.set()

    threading.Thread(target=_fire, name="Dummy-probe").start()
    for _ in range(200):
        if done.is_set() and calls:
            break
        await asyncio.sleep(0.01)
    assert calls, "the coroutine submitted from the foreign thread never ran"


def test_timer_callback_returns_quietly_when_the_loop_is_absent(
    actor: NwsIngestActor,
) -> None:
    """SS4.1 hazard 4: `run_coroutine_threadsafe` raises if the loop is closed.
    Guard it. Rust swallows exceptions raised in the callback anyway, so
    letting it raise buys nothing and loses the shutdown race quietly."""
    actor.on_start()  # no running loop -> actor.loop is None
    actor.on_poll_timer(object())  # must not raise


@pytest.mark.asyncio
async def test_poll_done_callback_routes_an_exception_to_task_death(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """SS4.1 hazard 1: Rust swallows exceptions raised in the callback, so
    supervision cannot rely on one escaping. It must be explicit, via
    `fut.exception()` in the done-callback -> `record_task_death` -> BLOCKED."""
    actor.on_start()

    async def _boom() -> None:
        raise ValueError("poll exploded")

    actor.poll_once = _boom  # type: ignore[method-assign]
    actor.on_poll_timer(object())
    for _ in range(200):
        await asyncio.sleep(0.01)
        if GateReason.TASK_DEATH in shared.gate.blocking_causes(VENUE, CITY):
            break
    assert GateReason.TASK_DEATH in shared.gate.blocking_causes(VENUE, CITY)
    assert shared.gate.status(VENUE, CITY).state is GateState.BLOCKED


@pytest.mark.asyncio
async def test_poll_done_callback_touches_no_store_off_the_loop_thread(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """SS4.1 hazard 3 + the thread-confined `SqliteStateStore`: the
    done-callback runs on the COMPLETING thread. Every gate call must be
    marshalled back onto the loop, or a real deployment raises
    `RuntimeError: SqliteStateStore was constructed on a different thread`."""
    actor.on_start()
    loop = asyncio.get_running_loop()
    seen: list[int] = []
    original = shared.gate.record_task_death

    def _spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(threading.get_ident())
        return original(*args, **kwargs)

    shared.gate.record_task_death = _spy  # type: ignore[method-assign]

    async def _boom() -> None:
        raise ValueError("boom")

    actor.poll_once = _boom  # type: ignore[method-assign]
    actor.on_poll_timer(object())
    for _ in range(200):
        await asyncio.sleep(0.01)
        if seen:
            break
    assert seen == [threading.get_ident()]
    assert loop is actor.loop


# ---------------------------------------------------------------------------
# SS6 step 1 -- the poll gate is NOT `require_open`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "block",
    [
        "record_parser_failure",
        "record_sanity_violation",
        "record_task_death",
        "record_write_integrity_violation",
        "record_transport_integrity_alarm",
        "record_redirect_integrity_alarm",
        "record_client_error_defect",
        "record_ambiguous_headline",
        "record_oversize_or_parse_timeout",
    ],
)
async def test_every_blocked_state_still_polls_and_a_clean_poll_reopens(
    actor: NwsIngestActor, shared: SharedIngestState, block: str
) -> None:
    """THE most important test in this phase (SS7 exit criteria).

    The settlement gate defaults to BLOCKED and `record_successful_poll` is
    reachable only FROM a poll. Gating polls on `require_open` therefore
    deadlocks on first boot and never recovers, and turns any transient
    hiccup into a permanent outage needing a database edit."""
    getattr(shared.gate, block)(VENUE, CITY, detail="induced for test")
    assert shared.gate.status(VENUE, CITY).state is GateState.BLOCKED

    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    assert shared.gate.status(VENUE, CITY).state is GateState.OPEN


@pytest.mark.asyncio
async def test_never_polled_site_polls_on_first_boot(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """The first-boot deadlock in its purest form: NEVER_POLLED is a BLOCKED
    state, and it can only ever be cleared by a poll."""
    assert GateReason.NEVER_POLLED in shared.gate.blocking_causes(VENUE, CITY)
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()
    assert shared.gate.status(VENUE, CITY).state is GateState.OPEN


@pytest.mark.asyncio
async def test_ua_trap_latch_suppresses_network_io(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """SS6 step 1: the narrow predicate. The GLOBAL `ua_trap_blocked` latch is
    one of exactly two things that genuinely forbid network I/O -- polling on
    into a UA trap is what costs us API access entirely."""
    # A cold-start 403 with no site ever having succeeded is classified by the
    # gate itself as a UA trap.
    shared.gate.record_forbidden_403(VENUE, CITY, detail="cold start")
    assert GateReason.UA_TRAP_403 in shared.gate.blocking_causes(VENUE, CITY)

    with respx.mock(assert_all_called=False) as mock:
        route = mock_discovery(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()
    assert route.call_count == 0


@pytest.mark.asyncio
async def test_active_backoff_window_suppresses_network_io(
    actor: NwsIngestActor, shared: SharedIngestState, clock: FakeClock
) -> None:
    """SS6 step 1: the second genuine prohibition. A 429 carrying `Retry-After`
    must be honoured -- the gate records the transient, the Actor owns the
    window (the same division of labour as `final_window_elapsed`)."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(DISCOVERY_URL).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "120"})
        )
        actor.on_start()
        await actor.poll_once()

    with respx.mock(assert_all_called=False) as mock:
        route = mock_discovery(mock, NYC_FINAL)
        await actor.poll_once()
    assert route.call_count == 0

    clock.advance(121 * SECOND)
    with respx.mock(assert_all_called=False) as mock:
        route = mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        await actor.poll_once()
    assert route.call_count == 1


# ---------------------------------------------------------------------------
# SS6 Stage A -- discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_304_is_a_terminal_no_op_success(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """SS6 step 2: a 304 is a TERMINAL branch, not step 9. Freshness is
    satisfied, so `record_successful_poll` is called directly -- but no record
    is written, no digest recorded, no cursor touched, nothing published.
    A 304 produces no `WriteOutcome`, so it must not pass through any step
    gated on `is_complete`."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(304))
        actor.on_start()
        await actor.poll_once()

    assert shared.gate.status(VENUE, CITY).state is GateState.OPEN
    assert actor.published == []
    assert actor.resume_cursor is None


@pytest.mark.asyncio
async def test_conditional_validators_are_stored_and_replayed(
    actor: NwsIngestActor,
) -> None:
    """SS6 step 2: conditional GET of the DISCOVERY list, sending the stored
    ETag/Last-Modified. Correct here -- and never on `/products/{id}`, whose
    bodies are immutable by id and where a 304 would satisfy the freshness
    watchdog while a corrected final sat unfetched."""
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(
            mock,
            NYC_FINAL,
            headers={"ETag": '"abc123"', "Last-Modified": "Sat, 22 Aug 2026 06:30:00 GMT"},
        )
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(304))
        await actor.poll_once()

    sent = route.calls[0].request
    assert sent.headers["if-none-match"] == '"abc123"'
    assert sent.headers["if-modified-since"] == "Sat, 22 Aug 2026 06:30:00 GMT"


@pytest.mark.asyncio
async def test_discovery_validators_are_not_persisted_after_sanity_hard_block(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """A discovery validator is safe to replay only after the batch succeeds.

    If a product body hard-blocks after the discovery list has been fetched, the
    body was NOT persisted. Replaying that list's ETag on the next poll can turn
    an unchanged 304 into `record_successful_poll`, clearing the CRIT sanity
    block while the missing product is still absent from the catalog.
    """
    payload = product_payload(NYC_FINAL)
    payload["productText"] = load_product_text(NYC_FINAL).replace(
        "MAXIMUM         79", "MAXIMUM        250"
    )

    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL, headers={"ETag": '"bad-batch"'})
        mock.get(product_url(NYC_FINAL)).mock(return_value=httpx.Response(200, json=payload))
        actor.on_start()
        await actor.poll_once()

    assert GateReason.SANITY_VIOLATION in shared.gate.blocking_causes(VENUE, CITY)

    with respx.mock(assert_all_called=False) as mock:
        route = mock_discovery(mock, NYC_FINAL)
        mock.get(product_url(NYC_FINAL)).mock(return_value=httpx.Response(200, json=payload))
        await actor.poll_once()

    assert "if-none-match" not in route.calls[0].request.headers
    assert GateReason.SANITY_VIOLATION in shared.gate.blocking_causes(VENUE, CITY)


@pytest.mark.asyncio
async def test_product_fetch_sends_no_conditional_validators(
    actor: NwsIngestActor,
) -> None:
    """A `/products/{id}` body is immutable by id. Revalidating it buys nothing
    and costs correctness: a 304 routes as a successful poll, satisfying the
    freshness watchdog while writing no record and recording no digest."""
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL, headers={"ETag": '"abc123"'})
        route = mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    sent = route.calls[0].request
    assert "if-none-match" not in sent.headers
    assert "if-modified-since" not in sent.headers


@pytest.mark.asyncio
async def test_already_ingested_uuid_is_never_refetched(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """SS3.4 Job 1 -- ordinary dedupe, and it is MANDATORY. Without it the
    discovery list returns the same id every poll, each re-fetch gets a fresh
    `retrieved_at_ns` and therefore a fresh `ts_init`, and the write SUCCEEDS
    -- appending a duplicate `NwsRawProduct`, verbatim `raw_text` and all,
    every cycle."""
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        route = mock_product(mock, NYC_FINAL)
        await actor.poll_once()

    assert route.call_count == 0
    assert shared.gate.status(VENUE, CITY).state is GateState.OPEN


@pytest.mark.asyncio
async def test_repolling_an_ingested_product_writes_no_duplicate_and_no_violation(
    actor: NwsIngestActor, shared: SharedIngestState, clock: FakeClock, tmp_path: Path
) -> None:
    """SS7 exit criterion, and the branch SS3.4 calls "worse": an exact
    `ts_init`-range collision makes `write_records` report `skipped`, which SS5
    routes to `record_write_integrity_violation` -- CRIT, hard-block. So an
    ungraceful crash right after a successful write would hard-block the site
    on the next poll. Discovery-time dedupe is what stops that."""
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    clock.advance(300 * SECOND)
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        await actor.poll_once()

    catalog = open_station_catalog(tmp_path / "nws", VENUE, CITY)
    assert len(read_raw_products(catalog)) == 1
    assert len(read_climate_days(catalog)) == 1
    assert (
        GateReason.WRITE_INTEGRITY_VIOLATION
        not in shared.gate.blocking_causes(VENUE, CITY)
    )


@pytest.mark.asyncio
async def test_empty_discovery_list_records_a_successful_poll(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """An empty `@graph` is a VALID, empty result -- nothing published yet --
    not a structural error. Freshness is satisfied."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(DISCOVERY_URL).mock(
            return_value=httpx.Response(200, json={"@graph": []})
        )
        actor.on_start()
        await actor.poll_once()
    assert shared.gate.status(VENUE, CITY).state is GateState.OPEN


@pytest.mark.asyncio
async def test_batch_of_unfetched_ids_is_written_in_non_decreasing_ts_init_order(
    actor: NwsIngestActor, tmp_path: Path
) -> None:
    """SS6 step 4: the list may yield SEVERAL unfetched ids -- after downtime, or
    a preliminary and a final since the last poll. `write_records` requires
    non-decreasing `ts_init` within a batch."""
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL, NYC_PRELIM)
        mock_product(mock, NYC_FINAL)
        mock_product(mock, NYC_PRELIM)
        actor.on_start()
        await actor.poll_once()

    catalog = open_station_catalog(tmp_path / "nws", VENUE, CITY)
    days = read_climate_days(catalog)
    assert len(days) == 2
    assert [d.ts_init for d in days] == sorted(d.ts_init for d in days)


@pytest.mark.asyncio
async def test_product_fetches_are_paced_after_the_first_and_keep_issuance_order(
    actor: NwsIngestActor,
) -> None:
    """Cold-start backlog fetches must not form a back-to-back burst.

    The first body fetch is immediate, then each subsequent product is delayed
    through an injected sleep seam. The loop still sorts by `issuance_time_ns`
    before pacing, so `ts_init` order remains issuance order rather than the
    discovery-list order.
    """
    events: list[str] = []

    async def _record_sleep(delay_seconds: float) -> None:
        events.append(f"sleep:{delay_seconds}")

    def _product_response(dirname: str) -> httpx.Response:
        events.append(f"fetch:{dirname}")
        return httpx.Response(200, json=product_payload(dirname))

    actor.sleep_between_product_fetches = _record_sleep

    with respx.mock(assert_all_called=False) as mock:
        # Deliberately newest-first in discovery; fetch order must still be
        # oldest issuance first.
        mock_discovery(mock, NYC_FINAL, NYC_PRELIM)
        mock.get(product_url(NYC_PRELIM)).mock(
            side_effect=lambda _request: _product_response(NYC_PRELIM)
        )
        mock.get(product_url(NYC_FINAL)).mock(
            side_effect=lambda _request: _product_response(NYC_FINAL)
        )
        actor.on_start()
        await actor.poll_once()

    assert events == [f"fetch:{NYC_PRELIM}", "sleep:0.5", f"fetch:{NYC_FINAL}"]


# ---------------------------------------------------------------------------
# SS6 Stage B -- per product
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_persists_publishes_and_opens_the_gate(
    actor: NwsIngestActor, shared: SharedIngestState, tmp_path: Path
) -> None:
    """SS6 steps 5-12 end to end, in order."""
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    catalog = open_station_catalog(tmp_path / "nws", VENUE, CITY)
    days = read_climate_days(catalog)
    raws = read_raw_products(catalog)
    assert len(days) == 1
    assert len(raws) == 1
    assert days[0].station == "NYC"
    assert days[0].is_final is True
    assert days[0].climate_day == dt.date(2026, 8, 21)
    assert raws[0].verify_digest() is True
    assert shared.gate.status(VENUE, CITY).state is GateState.OPEN


@pytest.mark.asyncio
async def test_publish_uses_the_raw_record_and_the_shared_data_type_factory(
    actor: NwsIngestActor,
) -> None:
    """SS6 note: `Actor.publish_data` enforces
    `Condition.type(data, data_type.type, ...)`, and a `CustomData` wrapper is
    not an `NwsClimateDay` -- passing one raises `TypeError`. The wrapping rule
    governs data submitted to the `DataEngine`, not data an Actor publishes.

    Trap 20: metadata KEY ORDER changes the topic string while `DataType.__eq__`
    ignores it, so equality-based tests pass while production delivers nothing.
    One shared factory per type is the only defence."""
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    published = actor.published
    types = {dt_.type for dt_, _ in published}
    assert types == {NwsClimateDay, NwsRawProduct}
    for data_type, payload in published:
        assert isinstance(payload, data_type.type)
        assert not type(payload).__name__.startswith("CustomData")
    assert nws_climate_day_data_type() is nws_climate_day_data_type()
    assert nws_raw_product_data_type() is nws_raw_product_data_type()


@pytest.mark.asyncio
async def test_sibling_station_product_is_routine_and_never_blocks(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """SS6 step 6 / SS5: a not-our-product rejection (sibling-station PIL, CLM
    monthly) is ROUTINE -- skip that product and continue. NEVER a block, and
    never `record_successful_poll` either, which would keep this site "fresh"
    forever on sibling products alone while the staleness watchdog and
    FINAL_CLI_OVERDUE both stayed silent."""
    with respx.mock(assert_all_called=False) as mock:
        # The MIA final arriving on the NYC poll: same shape, wrong station.
        payload = discovery_payload(discovery_entry(MIA_FINAL))
        mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=payload))
        mock_product(mock, MIA_FINAL)
        actor.on_start()
        await actor.poll_once()

    causes = shared.gate.blocking_causes(VENUE, CITY)
    assert GateReason.PARSER_FAILURE not in causes
    assert GateReason.OVERSIZE_OR_PARSE_TIMEOUT not in causes
    assert actor.published == []


@pytest.mark.asyncio
async def test_sibling_only_poll_stores_validators_without_recording_success(
    actor: NwsIngestActor, shared: SharedIngestState, clock: FakeClock
) -> None:
    """A sibling-only discovery response is safe to revalidate but not fresh.

    Every pending entry has already proven it is not this site's CLI product,
    so replaying the discovery validator cannot hide an unpersisted NYC body.
    It still must not call `record_successful_poll` on the 200 branch, because
    sibling traffic alone would otherwise keep the site fresh forever.
    """
    with respx.mock(assert_all_called=False) as mock:
        payload = discovery_payload(discovery_entry(MIA_FINAL))
        mock.get(DISCOVERY_URL).mock(
            return_value=httpx.Response(200, json=payload, headers={"ETag": '"siblings"'})
        )
        mock_product(mock, MIA_FINAL)
        actor.on_start()
        await actor.poll_once()

    assert shared.gate.status(VENUE, CITY).last_successful_poll_ns is None

    clock.advance(SECOND)
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(304))
        await actor.poll_once()

    sent = route.calls[0].request
    assert sent.headers["if-none-match"] == '"siblings"'
    assert shared.gate.status(VENUE, CITY).last_successful_poll_ns == clock.now


@pytest.mark.asyncio
async def test_sanity_violation_blocks_the_site(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """SS5: a physically impossible value is its OWN CRIT reason code --
    the text parsed correctly, so recording PARSER_FAILURE would name the
    wrong cause in the audit trail an operator reads at 07:30."""
    text = load_product_text(NYC_FINAL).replace("MAXIMUM         79", "MAXIMUM        250")
    payload = product_payload(NYC_FINAL)
    payload["productText"] = text

    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock.get(product_url(NYC_FINAL)).mock(
            return_value=httpx.Response(200, json=payload)
        )
        actor.on_start()
        await actor.poll_once()

    assert GateReason.SANITY_VIOLATION in shared.gate.blocking_causes(VENUE, CITY)


@pytest.mark.asyncio
async def test_ambiguous_headline_records_its_own_reason(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """SS5: `ClassificationError` -> `record_ambiguous_headline` -- CRIT.
    Classification is the highest-consequence parsing rule in the system: a
    preliminary mistaken for a final settles trades on a value NWS has not
    finalised."""
    payload = product_payload(NYC_FINAL)

    def _raise(_text: str) -> Any:
        from breezy.normalize.classify import ClassificationError

        raise ClassificationError("induced")

    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock.get(product_url(NYC_FINAL)).mock(
            return_value=httpx.Response(200, json=payload)
        )
        actor.on_start()
        actor.classify_issuance = _raise
        await actor.poll_once()

    assert GateReason.AMBIGUOUS_HEADLINE in shared.gate.blocking_causes(VENUE, CITY)


@pytest.mark.asyncio
async def test_integrity_index_mismatch_hard_blocks(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """SS3.4 Job 2 -- the integrity tripwire. It should NEVER fire in steady
    state: NWS assigns a fresh uuid to every re-issue and `/products/{id}`
    bodies are immutable by id. That is the point. It is a cheap invariant
    guard on an assumption we do not control, and its value is precisely that
    it costs nothing until the assumption breaks. Do not delete it as dead
    code, and do not infer from "it should never fire" that it can be skipped.
    """
    meta = load_meta(NYC_FINAL)
    # Seed the index with a DIFFERENT digest for this uuid, then force a
    # deliberate re-fetch by bypassing the discovery-time dedupe.
    shared.product_index.observe(meta["product_id"], "f" * 64)

    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        actor.refetch_known_products = True
        await actor.poll_once()

    assert shared.gate.status(VENUE, CITY).state is GateState.BLOCKED
    assert GateReason.TRANSPORT_INTEGRITY_ALARM in shared.gate.blocking_causes(
        VENUE, CITY
    )


@pytest.mark.asyncio
async def test_incomplete_write_blocks_and_never_records_a_successful_poll(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """SS6 step 10-11: `record_successful_poll` is gated behind
    `WriteOutcome.is_complete`. A non-empty `skipped` -- INCLUDING the partial
    case -- is an integrity violation, not a partial success: the catalog
    silently skips a same-range rewrite (`parquet.py:378-380`, a bare `print`
    to stdout, no exception, no logger)."""

    def _skip_everything(_catalog: Any, records: Sequence[Any]) -> WriteOutcome:
        return WriteOutcome(written=(), skipped=tuple(records), path="/fake")

    actor.write_records = _skip_everything

    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    assert shared.gate.status(VENUE, CITY).state is GateState.BLOCKED
    assert GateReason.WRITE_INTEGRITY_VIOLATION in shared.gate.blocking_causes(
        VENUE, CITY
    )
    assert actor.published == []


@pytest.mark.asyncio
async def test_catalog_write_error_routes_to_write_integrity_violation(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """SS5b: the catalog write path RAISES six types, not three. All route to
    `record_write_integrity_violation`, CRIT, hard-block."""
    from breezy.persistence.catalog import ConcurrentWriterError

    def _raise(_catalog: Any, _records: Sequence[Any]) -> WriteOutcome:
        raise ConcurrentWriterError("another writer holds the lock")

    actor.write_records = _raise

    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    assert GateReason.WRITE_INTEGRITY_VIOLATION in shared.gate.blocking_causes(
        VENUE, CITY
    )


@pytest.mark.asyncio
async def test_catalog_write_cancellation_propagates_without_durable_block(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """A graceful shutdown cancellation is not catalog corruption.

    `asyncio.CancelledError` inherits from `BaseException`, so catching
    `BaseException` around the off-loop write swallows SIGTERM cancellation and
    routes it as `UNROUTED_CATALOG_ERROR`, durably blocking the site on restart.
    """

    def _cancel(_catalog: Any, _records: Sequence[Any]) -> WriteOutcome:
        raise asyncio.CancelledError("shutdown")

    actor.write_records = _cancel

    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        with pytest.raises(asyncio.CancelledError):
            await actor.poll_once()

    assert (
        GateReason.WRITE_INTEGRITY_VIOLATION
        not in shared.gate.blocking_causes(VENUE, CITY)
    )


@pytest.mark.asyncio
async def test_parse_timeout_records_its_own_reason(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """SS6: the 250 ms fuzz ceiling is a CI-time PROPERTY test, not a production
    circuit-breaker -- nothing measures real elapsed time. Wrap the call, route
    `TimeoutError` to `record_oversize_or_parse_timeout`, and stop the runtime
    guarantee depending on regex authors never regressing."""
    import time as _time

    def _slow(*_args: Any, **_kwargs: Any) -> Any:
        _time.sleep(0.5)
        raise AssertionError("unreachable")

    actor.parse_cli_product = _slow

    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    assert GateReason.OVERSIZE_OR_PARSE_TIMEOUT in shared.gate.blocking_causes(
        VENUE, CITY
    )


# ---------------------------------------------------------------------------
# SS5 -- error routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_403_passes_the_cross_site_burst_signal(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """SS5b: `record_forbidden_403` no longer takes `is_ua_trap`. The gate
    classifies it itself, but the Actor must supply the cross-site burst
    SIGNAL, following the `final_window_elapsed` precedent where the gate owns
    the decision and the caller owns the clock."""
    observed: list[tuple[str, str]] = []
    original = shared.observe_forbidden_403

    def _spy(venue: str, city: str, **kwargs: Any) -> bool:
        observed.append((venue, city))
        return original(venue, city, **kwargs)

    shared.observe_forbidden_403 = _spy  # type: ignore[method-assign]

    with respx.mock(assert_all_called=False) as mock:
        mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(403))
        actor.on_start()
        await actor.poll_once()

    assert observed == [SITE]
    assert shared.gate.status(VENUE, CITY).state is GateState.BLOCKED


@pytest.mark.asyncio
async def test_404_is_a_binding_error_not_a_transient(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """F4 + SS5: `http.py` raises only for 3xx (except 304), 403, 429 and 5xx.
    A 404 returns a NORMAL `FetchResult` -- assuming "no exception means
    success" is a live defect. A 404 on a configured CLI location is a BINDING
    error; no amount of retrying makes a mistyped location exist."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(404))
        actor.on_start()
        await actor.poll_once()

    causes = shared.gate.blocking_causes(VENUE, CITY)
    assert GateReason.CLIENT_ERROR_DEFECT in causes
    assert GateReason.TRANSIENT_FAILURE not in causes


@pytest.mark.asyncio
async def test_redirect_is_an_integrity_alarm(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """SS5: redirects are never followed. A 3xx on a settlement endpoint is an
    integrity alarm -- CRIT, hard-block."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(DISCOVERY_URL).mock(
            return_value=httpx.Response(301, headers={"Location": "https://evil.test/x"})
        )
        actor.on_start()
        await actor.poll_once()

    assert GateReason.REDIRECT_INTEGRITY_ALARM in shared.gate.blocking_causes(
        VENUE, CITY
    )


@pytest.mark.asyncio
async def test_server_error_is_transient_and_degrades_after_three(
    actor: NwsIngestActor, shared: SharedIngestState, clock: FakeClock
) -> None:
    """SS5: 5xx joins the transient counter -- it is NOT an integrity alarm and
    must not share a route with one."""
    for _ in range(3):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(503))
            actor.on_start()
            await actor.poll_once()
        clock.advance(3600 * SECOND)

    causes = shared.gate.blocking_causes(VENUE, CITY)
    assert GateReason.TRANSIENT_FAILURE in causes or (
        GateReason.TRANSIENT_WINDOW_ELAPSED in causes
    )


@pytest.mark.asyncio
async def test_unroutable_body_shape_blocks_the_site(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """SS5: a malformed/hostile body shape is a data-quality failure -- block
    the site. Fail closed; "I do not recognise this" is not evidence it is
    benign."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(DISCOVERY_URL).mock(
            return_value=httpx.Response(200, content=b"not json at all")
        )
        actor.on_start()
        await actor.poll_once()

    assert shared.gate.status(VENUE, CITY).state is GateState.BLOCKED


# ---------------------------------------------------------------------------
# SS3.3 -- crash recovery and the resume cursor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_cursor_is_durable_at_the_moment_of_each_publish(
    actor: NwsIngestActor, store: RecordingStateStore
) -> None:
    """SS3.3 + SS7: the exit test must assert DURABILITY AT THE MOMENT OF THE
    KILL, and fail if the cursor was never written. A test that kills and then
    observes over-publication passes whether or not the cursor was durable --
    which is passing for the wrong reason.

    Two homes are ruled out here, and this test is what pins the second:

    * `on_save` -- `save_state`/`load_state` are `NautilusKernelConfig` fields
      and `Trader.save()` runs only from `kernel.stop()`, so on SIGKILL, OOM or
      host loss it never runs.
    * the Nautilus `Cache` -- write-through only when `CacheConfig.database` is
      set, and Breezy sets `database=None` (`runtime/node_config.py:150` ->
      `system/kernel.py:310-311` -> `cache/cache.pyx:298`). The final assertion
      below is the regression guard: Breezy must write NOTHING through it.
    """
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    cursor_writes = [k for k, _ in store.writes if "cursor" in k]
    published = actor.published
    assert len(cursor_writes) == len(published), (
        "every publish must be followed by a durable cursor write"
    )
    assert actor.resume_cursor is not None
    assert actor.cache.writes == [], (
        "nothing may be persisted through the memory-only Nautilus Cache"
    )


@pytest.mark.asyncio
async def test_cursor_comparison_is_strict_on_the_full_tuple(
    actor: NwsIngestActor,
) -> None:
    """SS3.3: the cursor is NOT a bare `ts_init`. `NwsClimateDay` and
    `NwsRawProduct` from one fetch share `retrieved_at_ns`. With a strict `>`
    on `ts_init` alone, a crash after publishing the first and before the
    second loses the second PERMANENTLY. With `>=`, every warm start
    re-publishes the last record. The cursor is therefore a TUPLE, compared
    strictly, and the equal-`ts_init` interleaving is pinned here."""
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    published = actor.published
    ts_inits = {payload.ts_init for _, payload in published}
    assert len(published) == 2
    assert len(ts_inits) == 1, "the two records share one retrieved_at_ns by design"
    assert actor.resume_cursor == actor.record_cursor(published[-1][1])


@pytest.mark.asyncio
async def test_warm_start_republishes_only_records_past_the_cursor(
    actor: NwsIngestActor, tmp_path: Path
) -> None:
    """SS3.2: each Actor warm-starts by reading its OWN catalog directly, then
    republishes through the SAME shared `DataType` factory the live path uses.
    Register zero catalogs, never call `request_data` -- F1 and F3 both break
    it, and F3 breaks it silently."""
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    live_published = list(actor.published)
    actor.published.clear()

    # Cursor already at the head: nothing to replay.
    await actor.warm_start()
    assert actor.published == []

    # Rewind the cursor: everything replays, in the same order.
    actor.reset_cursor()
    await actor.warm_start()
    replayed = actor.published
    assert [type(p).__name__ for _, p in replayed] == [
        type(p).__name__ for _, p in live_published
    ]


@pytest.mark.asyncio
async def test_warm_start_is_a_no_op_on_an_empty_catalog(
    actor: NwsIngestActor,
) -> None:
    """A cold station root has no records; warm start must not fabricate one."""
    actor.on_start()
    await actor.warm_start()
    assert actor.published == []
    assert actor.resume_cursor is None


# ---------------------------------------------------------------------------
# SS6 / SS5b -- the data-completeness clock and the staleness watchdog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_final_deadline_fires_on_a_schedule_not_on_failed_fetches(
    actor: NwsIngestActor, shared: SharedIngestState, clock: FakeClock
) -> None:
    """SS6: the ONLY orthogonal defence against a perpetual-304 staleness
    attack. A 304 counts as a successful poll and resets
    `last_successful_poll_ns`, satisfying the liveness watchdog indefinitely
    while writing no record. Contract: the deadline fires on a SCHEDULE, not
    "after N failed fetches"."""
    actor.on_start()
    # Well past 08:00 ET on 2026-08-22, with no final for 2026-08-21 ingested.
    clock.advance(12 * 3600 * SECOND)
    await actor.check_final_deadline()

    assert GateReason.FINAL_CLI_OVERDUE in shared.gate.blocking_causes(VENUE, CITY)


@pytest.mark.asyncio
async def test_successful_poll_does_not_clear_an_overdue_final(
    actor: NwsIngestActor, shared: SharedIngestState, clock: FakeClock
) -> None:
    """SS5b: `record_final_overdue` is a DATA-COMPLETENESS clock keyed by
    climate day. A successful poll deliberately does NOT clear it -- only
    `record_final_received` for that EXACT climate day does. A final for
    yesterday must not clear today's block."""
    actor.on_start()
    clock.advance(12 * 3600 * SECOND)
    await actor.check_final_deadline()
    assert GateReason.FINAL_CLI_OVERDUE in shared.gate.blocking_causes(VENUE, CITY)

    with respx.mock(assert_all_called=False) as mock:
        mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(304))
        await actor.poll_once()

    assert GateReason.FINAL_CLI_OVERDUE in shared.gate.blocking_causes(VENUE, CITY)


@pytest.mark.asyncio
async def test_ingesting_the_final_clears_the_overdue_block(
    actor: NwsIngestActor, shared: SharedIngestState, clock: FakeClock
) -> None:
    """SS6 step 12 + SS5b: the only clearing path is `record_final_received`
    for that specific climate day."""
    actor.on_start()
    clock.advance(12 * 3600 * SECOND)
    await actor.check_final_deadline()
    assert GateReason.FINAL_CLI_OVERDUE in shared.gate.blocking_causes(VENUE, CITY)

    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        await actor.poll_once()

    assert GateReason.FINAL_CLI_OVERDUE not in shared.gate.blocking_causes(VENUE, CITY)


@pytest.mark.asyncio
async def test_deadline_check_is_a_no_op_before_the_deadline(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """06:31 UTC on 2026-08-22 is 02:31 ET -- comfortably before the 08:00 ET
    settlement deadline for climate day 2026-08-21."""
    actor.on_start()
    await actor.check_final_deadline()
    assert GateReason.FINAL_CLI_OVERDUE not in shared.gate.blocking_causes(VENUE, CITY)


@pytest.mark.asyncio
async def test_staleness_watchdog_escalates_without_a_successful_poll(
    actor: NwsIngestActor, shared: SharedIngestState, clock: FakeClock
) -> None:
    """The data-staleness alarm on the subscribed channel. `check_freshness`
    has deliberately NO recovery branch: freshness is DEFINED by a recent
    successful poll, and `record_successful_poll` is the only legitimate way
    staleness clears."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(304))
        actor.on_start()
        await actor.poll_once()
    assert shared.gate.status(VENUE, CITY).state is GateState.OPEN

    clock.advance(actor.staleness_blocked_after_ns + SECOND)
    actor.check_staleness()

    assert GateReason.STALE_BLOCKED in shared.gate.blocking_causes(VENUE, CITY)


# ---------------------------------------------------------------------------
# Provenance / settlement-grade discipline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_persisted_records_carry_verifiable_provenance(
    actor: NwsIngestActor, tmp_path: Path, clock: FakeClock
) -> None:
    """Settlement-grade discipline: preserve exact station, product id,
    timestamps, units and source identifiers on every persisted record, and
    verify `sha256(raw_text)` before any later settlement use."""
    meta = load_meta(NYC_FINAL)
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    catalog = open_station_catalog(tmp_path / "nws", VENUE, CITY)
    raw = read_raw_products(catalog)[0]
    day = read_climate_days(catalog)[0]

    assert raw.product_uuid == meta["product_id"]
    assert raw.issuing_office == meta["issuing_office"]
    assert raw.wmo_collective_id == meta["wmo_collective_id"]
    assert raw.awips_pil == "CLINYC"
    assert raw.station == "NYC"
    assert raw.raw_sha256 == hashlib.sha256(raw.raw_text.encode()).hexdigest()
    assert raw.verify_digest() is True
    assert raw.ts_init == clock.now
    # `raw_sha256` is the join between the two records.
    assert day.raw_sha256 == raw.raw_sha256
    assert day.revision_seq >= 1


@pytest.mark.asyncio
async def test_revision_seq_increments_for_a_second_record_of_one_climate_day(
    actor: NwsIngestActor, tmp_path: Path, clock: FakeClock
) -> None:
    """Monotonic `revision_seq` per `(station, climate_day)`, starting at 1.
    A silent `1` on a correction would mask a missing increment -- and the
    settlement resolver re-checks the LATEST revision, not the first ingested.
    """
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_PRELIM)
        mock_product(mock, NYC_PRELIM)
        actor.on_start()
        await actor.poll_once()

    clock.advance(3600 * SECOND)
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_PRELIM, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        await actor.poll_once()

    catalog = open_station_catalog(tmp_path / "nws", VENUE, CITY)
    days = sorted(read_climate_days(catalog), key=lambda d: d.ts_init)
    assert [d.climate_day for d in days] == [dt.date(2026, 8, 21)] * 2
    assert [d.revision_seq for d in days] == [1, 2]


def test_no_hardcoded_credentials_hosts_or_personal_identifiers() -> None:
    """SS8 standing constraints: the User-Agent comes from `http.py`'s existing
    `BREEZY_USER_AGENT` mechanism; TLS is never disabled; no venue host is
    reachable from this module."""
    source = inspect.getsource(nws_actor_module)
    for forbidden in (
        "verify=False",
        "_create_unverified_context",
        "polymarket",
        "BREEZY_USER_AGENT",
        "@gmail.com",
        "https://",
        "http://",
    ):
        assert forbidden not in source, f"{forbidden!r} must not appear in nws_actor.py"


def test_station_identifiers_come_only_from_the_registry() -> None:
    """SS8: path components derive only from the registry object and a typed
    date, never from parsed product text. An identifier extracted from product
    text and interpolated into a catalog path is a path-traversal write
    primitive."""
    source = inspect.getsource(nws_actor_module)
    for hardcoded in ('"KNYC"', '"CLINYC"', '"KOKX"', '"NYC"', '"KMDW"'):
        assert hardcoded not in source


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_stop_cancels_timers_and_shuts_the_executor_down(
    actor: NwsIngestActor,
) -> None:
    """No orphaned worker thread and no timer firing into a stopped Actor."""
    actor.on_start()
    assert actor.poll_timer_armed is True
    actor.on_stop()
    assert actor.poll_timer_armed is False


@pytest.mark.asyncio
async def test_catalog_io_runs_off_the_event_loop(actor: NwsIngestActor) -> None:
    """SS3.1 ruling: catalog I/O runs OFF the loop. The parse has a ceiling
    test; the thing that will actually stall the loop -- `fcntl.flock`, two
    pyarrow read-backs inside `write_records`, and an unbounded warm-start read
    that grows monotonically with retention -- does not."""
    loop_ident = threading.get_ident()
    idents: list[int] = []
    original = actor.write_records

    def _spy(catalog: Any, records: Sequence[Any]) -> WriteOutcome:
        idents.append(threading.get_ident())
        return original(catalog, records)

    actor.write_records = _spy

    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    assert idents, "write_records was never called"
    assert loop_ident not in idents


# ---------------------------------------------------------------------------
# Remaining branches: every failure route reachable in Phase 1
# ---------------------------------------------------------------------------


def test_data_type_factory_refuses_an_unregistered_record_type() -> None:
    """Trap 5: a `DataType(X)` subscriber uses the glob `data.X*` and WILL
    receive `XSomething` objects. Publishing an unknown type through a shared
    factory would be the mirror of that bug, so it is a hard error rather than
    a best-effort `DataType(type(record))`."""
    with pytest.raises(TypeError, match="no shared DataType factory"):
        nws_actor_module._data_type_for(object())


@pytest.mark.asyncio
async def test_on_stop_is_idempotent_and_dispose_releases_the_pool(
    actor: NwsIngestActor,
) -> None:
    """A timer must not fire into a stopped Actor, and a disposed Actor must
    not leave a worker thread behind."""
    actor.on_stop()  # never started: must be a quiet no-op
    assert actor.poll_timer_armed is False
    actor.on_start()
    actor.on_stop()
    actor.on_stop()
    actor.on_dispose()
    assert actor.poll_timer_armed is False


@pytest.mark.asyncio
async def test_deadline_timer_bridges_onto_the_loop(
    actor: NwsIngestActor, shared: SharedIngestState, clock: FakeClock
) -> None:
    """The data-completeness timer uses the SAME Rust-thread bridge as the poll
    timer -- it is a `Clock` timer too, so it lands on a `_DummyThread` with no
    running loop."""
    actor.on_start()
    clock.advance(12 * 3600 * SECOND)
    actor.on_deadline_timer(object())
    for _ in range(200):
        await asyncio.sleep(0.01)
        if GateReason.FINAL_CLI_OVERDUE in shared.gate.blocking_causes(VENUE, CITY):
            break
    assert GateReason.FINAL_CLI_OVERDUE in shared.gate.blocking_causes(VENUE, CITY)


@pytest.mark.asyncio
async def test_supervision_is_silent_on_success_and_on_cancellation(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """A completed or cancelled poll is not a task death. Recording one would
    hard-block a healthy site on every ordinary shutdown."""
    import concurrent.futures as cf

    actor.on_start()
    cancelled: cf.Future[None] = cf.Future()
    cancelled.cancel()
    actor._on_poll_done(cancelled)

    ok: cf.Future[None] = cf.Future()
    ok.set_result(None)
    actor._on_poll_done(ok)

    assert GateReason.TASK_DEATH not in shared.gate.blocking_causes(VENUE, CITY)


@pytest.mark.asyncio
async def test_oversize_discovery_list_is_refused_before_json_parsing(
    shared: SharedIngestState,
) -> None:
    """The body cap is checked on the raw text, BEFORE `json.loads` walks it.
    Rejecting a pathological payload in bounded work is the whole point; doing
    it after parsing would have already paid the cost."""
    instance = build_actor(shared, discovery_max_bytes=32)
    try:
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            instance.on_start()
            await instance.poll_once()
        assert GateReason.PARSER_FAILURE in shared.gate.blocking_causes(VENUE, CITY)
    finally:
        instance.shutdown_executor()


@pytest.mark.asyncio
async def test_discovery_list_that_is_not_a_json_object_blocks(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """A JSON array where an object belongs is a structural claim about the
    payload, not a field error -- and it must not reach `parse_discovery_list`
    as a mapping it never was."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(200, json=[1, 2, 3]))
        actor.on_start()
        await actor.poll_once()
    assert GateReason.PARSER_FAILURE in shared.gate.blocking_causes(VENUE, CITY)


@pytest.mark.asyncio
async def test_product_envelope_that_is_not_a_json_object_blocks(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock.get(product_url(NYC_FINAL)).mock(
            return_value=httpx.Response(200, json=["not", "an", "object"])
        )
        actor.on_start()
        await actor.poll_once()
    assert GateReason.PARSER_FAILURE in shared.gate.blocking_causes(VENUE, CITY)


@pytest.mark.asyncio
async def test_transport_failure_on_the_product_fetch_aborts_the_batch(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """Stage B failures abort the batch, and nothing has been observed into the
    integrity index yet -- so the product is still re-fetchable next poll."""
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock.get(product_url(NYC_FINAL)).mock(return_value=httpx.Response(503))
        actor.on_start()
        await actor.poll_once()

    assert actor.product_index.known_digest(load_meta(NYC_FINAL)["product_id"]) is None
    # One failure does not reach the 3-strike DEGRADED rung, so the transition
    # EVENT is the evidence here -- `blocking_causes` answers a different
    # question ("why is it not OPEN right now") and is deliberately silent
    # about a single transient tick.
    assert shared.gate.status(VENUE, CITY).reason is GateReason.TRANSIENT_FAILURE


@pytest.mark.asyncio
async def test_client_error_on_the_product_fetch_aborts_the_batch(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """F4 again, on the product endpoint: a 404 returns a normal `FetchResult`.
    "No exception" is not "success"."""
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock.get(product_url(NYC_FINAL)).mock(return_value=httpx.Response(404))
        actor.on_start()
        await actor.poll_once()
    assert GateReason.CLIENT_ERROR_DEFECT in shared.gate.blocking_causes(VENUE, CITY)


@pytest.mark.asyncio
async def test_structurally_impossible_body_is_rejected_before_any_regex(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """SS6 step 6: the structural allowlist runs ALONE and ahead of the parser,
    so a malformed or adversarial product is rejected in bounded, near-constant
    work regardless of what the later regexes could be made to do with it.
    A structural rejection is loud -- distinct from a routine sibling product.
    """
    payload = product_payload(NYC_FINAL)
    payload["productText"] = "X\n" * 5000

    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock.get(product_url(NYC_FINAL)).mock(
            return_value=httpx.Response(200, json=payload)
        )
        actor.on_start()
        await actor.poll_once()

    assert GateReason.OVERSIZE_OR_PARSE_TIMEOUT in shared.gate.blocking_causes(
        VENUE, CITY
    )


@pytest.mark.asyncio
async def test_structural_allowlist_also_has_a_wall_clock_ceiling(
    shared: SharedIngestState,
) -> None:
    """Both bounded stages are bounded. A zero-millisecond ceiling proves the
    allowlist call is genuinely wrapped rather than only the parse."""
    instance = build_actor(shared, parse_timeout_ms=0)
    try:
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            mock_product(mock, NYC_FINAL)
            instance.on_start()
            await instance.poll_once()
        assert GateReason.OVERSIZE_OR_PARSE_TIMEOUT in shared.gate.blocking_causes(
            VENUE, CITY
        )
    finally:
        instance.shutdown_executor()


@pytest.mark.asyncio
async def test_content_error_from_the_parser_is_a_crit_parse_failure(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """SS5: structure passed, content unreadable -- our OWN product arrived
    unusable. That is CRIT, and it must never be collapsed into
    `CliNotOurProductError`'s "ignore it and carry on"."""
    from breezy.normalize.cli_parse import CliContentError

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise CliContentError("induced content error")

    actor.parse_cli_product = _raise

    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    assert GateReason.PARSER_FAILURE in shared.gate.blocking_causes(VENUE, CITY)


@pytest.mark.asyncio
async def test_record_builder_inconsistency_is_a_parser_failure(
    actor: NwsIngestActor, shared: SharedIngestState, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The builders' cross-object checks are MISCLASSIFICATION DETECTORS, not
    tolerances -- a final whose `ts_event` post-dates its `ts_init` means the
    climate day had not ended when the bytes arrived, so it is not a final."""

    def _raise(**_kwargs: Any) -> Any:
        raise ValueError("induced builder inconsistency")

    monkeypatch.setattr(nws_actor_module, "build_climate_day", _raise)

    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    assert GateReason.PARSER_FAILURE in shared.gate.blocking_causes(VENUE, CITY)


@pytest.mark.asyncio
async def test_revision_seq_ignores_another_stations_records(
    actor: NwsIngestActor, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """One WFO issues several cities' CLIs, so the station must never be
    inferred across records -- including when counting revisions. A sibling's
    row must not push our first revision to 2."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        nws_actor_module,
        "read_climate_days",
        lambda _catalog: [
            SimpleNamespace(station="JFK", climate_day=dt.date(2026, 8, 21))
        ],
    )

    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    monkeypatch.undo()
    catalog = open_station_catalog(tmp_path / "nws", VENUE, CITY)
    assert [d.revision_seq for d in read_climate_days(catalog)] == [1]


@pytest.mark.asyncio
async def test_publishing_the_same_records_twice_is_idempotent(
    actor: NwsIngestActor, tmp_path: Path
) -> None:
    """The cursor guards the publish path itself, not just warm start."""
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    published_once = len(actor.published)
    catalog = open_station_catalog(tmp_path / "nws", VENUE, CITY)
    actor._publish_records([*read_climate_days(catalog), *read_raw_products(catalog)])
    assert len(actor.published) == published_once


@pytest.mark.asyncio
async def test_corrupt_cursor_replays_rather_than_skipping(
    actor: NwsIngestActor,
) -> None:
    """Fail closed by REPLAYING. An unreadable cursor must never be read as
    "everything was already published": over-publication is idempotent for
    subscribers, silent loss of a settlement record is not."""
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    actor._state_store.set(actor._cursor_key, b"{not json")
    actor._cursor_loaded = False
    assert actor.resume_cursor is None

    actor.published.clear()
    await actor.warm_start()
    assert len(actor.published) == 2


@pytest.mark.asyncio
async def test_corrupt_validators_fall_back_to_an_unconditional_get(
    actor: NwsIngestActor,
) -> None:
    """A corrupt stored validator degrades to an unconditional GET -- the
    conservative direction. Echoing an unreadable value back into an outbound
    request header is what `InvalidCacheValidatorError` exists to stop."""
    actor._state_store.set(actor._validators_key, b"[]")
    with respx.mock(assert_all_called=False) as mock:
        route = mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()
    assert "if-none-match" not in route.calls[0].request.headers


@pytest.mark.asyncio
async def test_deadline_is_not_recorded_once_the_final_is_on_disk(
    actor: NwsIngestActor, shared: SharedIngestState, clock: FakeClock
) -> None:
    """The completeness answer is read DURABLY off the catalog, not off process
    memory: an in-memory "we saw the final" set would reset on restart and
    re-block a site that is actually complete. The SETTLEMENT accessor is used,
    which answers "what should the venue have settled on" rather than "what do
    we believe now"."""
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    clock.advance(12 * 3600 * SECOND)
    await actor.check_final_deadline()
    assert GateReason.FINAL_CLI_OVERDUE not in shared.gate.blocking_causes(VENUE, CITY)


@pytest.mark.asyncio
async def test_unparseable_retry_after_falls_back_to_exponential_backoff(
    actor: NwsIngestActor, clock: FakeClock
) -> None:
    """`Retry-After` may be an HTTP-date. Guessing at a date format on a
    rate-limit response is how a client turns a temporary throttle into a ban,
    so an unparseable value falls through to the exponential schedule rather
    than being parsed loosely."""
    with respx.mock(assert_all_called=False) as mock:
        mock.get(DISCOVERY_URL).mock(
            return_value=httpx.Response(
                429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}
            )
        )
        actor.on_start()
        await actor.poll_once()

    # One poll interval (300 s), not zero and not the header's value.
    assert actor._backoff_until_ns == clock.now + 300 * SECOND


@pytest.mark.asyncio
async def test_a_long_transient_streak_signals_the_final_window_elapsed(
    actor: NwsIngestActor, shared: SharedIngestState, clock: FakeClock
) -> None:
    """SS5b: the retry window belongs to the caller, exactly as the conflict
    window does. The gate only records its outcome, and
    `final_window_elapsed=True` is what escalates DEGRADED to BLOCKED."""
    signals: list[bool] = []
    original = shared.gate.record_transient_failure

    def _spy(venue: str, city: str, **kwargs: Any) -> Any:
        signals.append(bool(kwargs.get("final_window_elapsed")))
        return original(venue, city, **kwargs)

    shared.gate.record_transient_failure = _spy  # type: ignore[method-assign]

    actor.on_start()
    for _ in range(2):
        with respx.mock(assert_all_called=False) as mock:
            mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(503))
            await actor.poll_once()
        clock.advance(2 * 3600 * SECOND)

    assert signals == [False, True]
    assert GateReason.TRANSIENT_WINDOW_ELAPSED in shared.gate.blocking_causes(
        VENUE, CITY
    )


@pytest.mark.asyncio
async def test_parser_may_also_report_a_sibling_station(
    actor: NwsIngestActor, shared: SharedIngestState
) -> None:
    """`parse_cli_product` re-runs the structural allowlist itself (defence in
    depth, and it must stay ahead of every regex), so `CliNotOurProductError`
    can surface from the parse step as well as the allowlist step. Both must
    route as ROUTINE -- a sibling product reaching the second check is still
    not a failure of ours."""
    from breezy.normalize.cli_parse import CliNotOurProductError

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise CliNotOurProductError("sibling station at the parse step")

    actor.parse_cli_product = _raise

    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    causes = shared.gate.blocking_causes(VENUE, CITY)
    assert GateReason.PARSER_FAILURE not in causes
    assert GateReason.OVERSIZE_OR_PARSE_TIMEOUT not in causes
    assert actor.published == []


@pytest.mark.asyncio
async def test_reset_cursor_is_durable_and_reads_back_as_absent(
    actor: NwsIngestActor,
) -> None:
    """Replay repair must survive a restart: rewinding in memory only would
    silently un-rewind on the next process, so the reset is written through."""
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    actor.reset_cursor()
    actor._cursor_loaded = False  # simulate a fresh process reading it back
    assert actor.resume_cursor is None


def test_final_window_is_not_elapsed_before_any_transient_failure(
    actor: NwsIngestActor,
) -> None:
    """`final_window_elapsed` must be False with no streak in flight. The
    default matters: `True` would escalate a site to BLOCKED on its very first
    network hiccup, converting a blip into an outage."""
    assert actor._final_window_elapsed() is False


@pytest.mark.asyncio
async def test_a_persisted_cursor_round_trips_across_a_restart(
    actor: NwsIngestActor,
) -> None:
    """The restart path itself: the cursor written after the last publish must
    read back as the SAME tuple, or warm start republishes records subscribers
    already saw (harmless) or -- if it read back wrong -- skips ones they did
    not (a silently lost settlement record).
    """
    with respx.mock(assert_all_called=False) as mock:
        mock_discovery(mock, NYC_FINAL)
        mock_product(mock, NYC_FINAL)
        actor.on_start()
        await actor.poll_once()

    in_memory = actor.resume_cursor
    assert in_memory is not None

    actor._cursor_loaded = False  # simulate a fresh process reading it back
    assert actor.resume_cursor == in_memory

    actor.published.clear()
    await actor.warm_start()
    assert actor.published == []


# ---------------------------------------------------------------------------
# The climate-day derivation exists exactly ONCE
# ---------------------------------------------------------------------------


def test_the_actor_no_longer_carries_a_private_climate_day_derivation() -> None:
    """`gaps.most_recent_completed_climate_day` was extracted byte-for-byte
    from this Actor's own `_most_recent_completed_climate_day`, so the
    fixed-standard-offset-vs-DST arithmetic existed TWICE.

    Two copies of exactly this calculation is the divergence that silently
    fabricates or hides gaps -- the ledger and the settlement deadline would
    disagree about which day is complete. The private copy is therefore gone,
    not merely kept in agreement.
    """
    assert not hasattr(NwsIngestActor, "_most_recent_completed_climate_day")


@pytest.mark.parametrize(
    "instant",
    [
        # Exactly local-standard midnight, and one second either side of it --
        # the boundary a float-division rewrite would move by a whole day.
        dt.datetime(2026, 8, 22, 5, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2026, 8, 22, 4, 59, 59, tzinfo=dt.UTC),
        dt.datetime(2026, 8, 22, 5, 0, 1, tzinfo=dt.UTC),
        # Inside EDT: the DST-following clock says 20:00 on the 21st while
        # local STANDARD time says 19:00 on the 21st. Both agree here, which
        # is the point -- the standard offset is applied, never the DST one.
        dt.datetime(2026, 8, 22, 0, 0, 0, tzinfo=dt.UTC),
        # The spring-forward and fall-back instants themselves.
        dt.datetime(2026, 3, 8, 7, 0, 0, tzinfo=dt.UTC),
        dt.datetime(2026, 11, 1, 6, 0, 0, tzinfo=dt.UTC),
        # A UTC date that is NOT the local date.
        dt.datetime(2026, 8, 22, 3, 30, 0, tzinfo=dt.UTC),
    ],
)
def test_the_extracted_climate_day_matches_the_removed_arithmetic_exactly(
    shared: SharedIngestState, instant: dt.datetime
) -> None:
    """Behaviour-identical, proven against the arithmetic as it was WRITTEN in
    `nws_actor.py` before the extraction (restated verbatim here, which is the
    only way this assertion can falsify a drift in the extraction).

    Floor division on whole seconds, not float division: `fromtimestamp` on a
    float would round-trip through binary floating point and can land on the
    wrong side of a midnight boundary.
    """
    from breezy.ingest import gaps
    from breezy.normalize.climate_day import standard_time_zone

    actor = build_actor(shared)
    window = shared.registry.climate_day_window(VENUE, CITY)
    now_ns = int(instant.timestamp()) * SECOND

    # The removed implementation, verbatim.
    local = dt.datetime.fromtimestamp(
        now_ns // SECOND, tz=standard_time_zone(window.std_utc_offset_hours)
    )
    expected = local.date() - dt.timedelta(days=1)

    assert gaps.most_recent_completed_climate_day(now_ns, window.std_utc_offset_hours) == expected
    actor.shutdown_executor()
