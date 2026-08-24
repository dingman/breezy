"""Tests for the NWS ingest Actor (`breezy.ingest.nws_actor`).

Governing rulings: `docs/plans/PHASE1_ACTOR_BRIEF.md` SS3.6, SS4.1, SS5, SS6, SS7 and
`docs/plans/WEATHER_INGESTION_PROPOSAL.md` SS2.3, SS5, SS10.

Four properties here are load-bearing and each is tested as a property, not as
an incidental consequence of some larger flow:

1. **A BLOCKED site still polls, and a clean poll reopens it.** The gate is a
   *use-time* gate, not a poll gate. Gating the poll on `require_open` would
   deadlock on first boot (a site starts BLOCKED and only a successful poll can
   open it) and would turn one transient hiccup into a permanent outage. The
   brief calls this the single most important test in the phase.
2. **An integrity alarm propagates out of `RetryManager` uncaught.**
   `live/retry.py:172` is `except self.exc_types as e:` -- ordinary,
   *isinstance-based* `except`. Listing the base `TransportError` would make the
   manager swallow and silently RETRY a `RedirectError` on a settlement
   endpoint. Only sibling LEAF types may be listed.
3. **The final-overdue deadline is a wall clock, not a poll counter.** A
   perpetual-304 attack satisfies the liveness watchdog forever while writing no
   record; the deadline is the orthogonal defence, so it must fire on a schedule.
4. **The resume cursor is durable at the instant of publish.** A crash between
   persist and publish must republish, and an equal-`ts_init` pair must not lose
   its second member.

No test here touches the network: the transport's two coroutines are replaced
per-test with local doubles.
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import datetime as dt
import hashlib
import inspect
import json
import logging
import threading
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import msgspec
import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.common.config import ImportableActorConfig, msgspec_encoding_hook
from nautilus_trader.model.identifiers import ComponentId
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.domain.data_types import climate_day_type, raw_product_type
from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.nws_raw_product import NwsRawProduct
from breezy.ingest import nws_actor as nws_actor_module
from breezy.ingest.gate import (
    GateReason,
    GateState,
    InMemoryStateStore,
    SettlementGate,
)
from breezy.ingest.http import (
    ContentEncodingError,
    FetchResult,
    ForbiddenError,
    RateLimitedError,
    RedirectError,
    ServerError,
    TransportTimeoutError,
)
from breezy.ingest.nws_actor import (
    MAX_INFLIGHT_TASKS,
    ExecutorDisposedError,
    NwsIngestActor,
    NwsIngestActorConfig,
    build_actor_config,
    final_overdue_timer_name,
    parse_discovery_list,
    parse_product_envelope,
    poll_timer_name,
)
from breezy.ingest.shared_state import SharedIngestState
from breezy.persistence.catalog import (
    FilesystemLocality,
    FilesystemProbe,
    open_station_catalog,
    read_climate_days,
)
from breezy.persistence.state_store import FileStateStore
from breezy.registry.sites import SiteRegistry, default_registry

VENUE = "polymarket_us"
CITY = "NYC"
ALL_SITES = ((VENUE, "NYC"), (VENUE, "SFO"), (VENUE, "MIA"), (VENUE, "MDW"), (VENUE, "LAX"))

SECOND_NS = 1_000_000_000
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "nws"

#: 2026-08-22T19:14:00Z -- the NYC final fixture's own `retrieved_at`.
NOW = dt.datetime(2026, 8, 22, 19, 14, tzinfo=dt.UTC)
NOW_NS = int(NOW.timestamp()) * SECOND_NS

NYC_FINAL_UUID = "40bb657c-e166-44d4-a038-dd18701cf2c8"
NYC_PRELIM_UUID = "1a2b3c4d-5e6f-4a8b-9c0d-1e2f3a4b5c6d"


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class FakeClock:
    """The injected `Callable[[], int]` of UNIX nanoseconds."""

    def __init__(self, now: int = NOW_NS) -> None:
        self.now = now

    def __call__(self) -> int:
        return self.now

    def advance_ns(self, ns: int) -> None:
        self.now += ns


class LocalProbe:
    """A `probe_filesystem` stand-in with a fixed LOCAL verdict."""

    def __call__(self, path: Path) -> FilesystemProbe:
        return FilesystemProbe(
            path=str(path),
            mount_point="/",
            fs_type="ext4",
            locality=FilesystemLocality.LOCAL,
            detail="test probe",
        )


class FakeKernelConfig:
    save_state = True
    load_state = True


class FakeCacheConfig:
    database = object()
    flush_on_start = False


class FakeExecEngineConfig:
    load_cache = True


def _fixture_text(name: str) -> str:
    return (FIXTURES / name / "product.txt").read_text(encoding="utf-8")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _discovery_body(*entries: tuple[str, str]) -> str:
    """Build a `/products/types/CLI/locations/{loc}` ld+json body."""
    return json.dumps(
        {
            "@context": {"@vocab": "https://api.weather.gov/ontology#"},
            "@graph": [
                {
                    "id": product_uuid,
                    "wmoCollectiveId": "CDUS41",
                    "issuingOffice": "KOKX",
                    "issuanceTime": issuance_time,
                    "productCode": "CLI",
                    "productName": "Climate Report",
                }
                for product_uuid, issuance_time in entries
            ],
        }
    )


def _product_body(
    product_uuid: str,
    product_text: str,
    *,
    issuance_time: str = "2026-08-22T06:26:00+00:00",
    issuing_office: str = "KOKX",
) -> str:
    return json.dumps(
        {
            "@context": {"@vocab": "https://api.weather.gov/ontology#"},
            "@id": f"https://api.weather.gov/products/{product_uuid}",
            "id": product_uuid,
            "wmoCollectiveId": "CDUS41",
            "issuingOffice": issuing_office,
            "issuanceTime": issuance_time,
            "productCode": "CLI",
            "productName": "Climate Report",
            "productText": product_text,
        }
    )


def _fetch(
    body: str,
    *,
    status: int = 200,
    at_ns: int = NOW_NS,
    url: str = "https://api.weather.gov/products/types/CLI/locations/NYC",
    retry_after: str | None = None,
    etag: str | None = None,
) -> FetchResult:
    import httpx

    headers = httpx.Headers({"etag": etag} if etag else {})
    if status == 304:
        return FetchResult(
            text=None,
            sha256=None,
            status_code=304,
            headers=headers,
            url=url,
            retrieved_at_ns=at_ns,
            retry_after=retry_after,
        )
    return FetchResult(
        text=body,
        sha256=_sha(body),
        status_code=status,
        headers=headers,
        url=url,
        retrieved_at_ns=at_ns,
        retry_after=retry_after,
    )


class TransportDouble:
    """Records calls and replays scripted results/exceptions.

    Installed over the real `HttpTransport`'s two coroutines with
    `monkeypatch.setattr`, so the Actor still holds the container's one
    transport object and the shared-instance invariant is untouched.
    """

    def __init__(self) -> None:
        self.discovery_calls: list[tuple[str, str | None, str | None]] = []
        self.product_calls: list[str] = []
        self.discovery_results: list[Any] = []
        self.product_results: dict[str, list[Any]] = {}
        self.default_product: Any = None

    async def fetch_discovery_list(
        self,
        cli_location: str,
        *,
        if_none_match: str | None = None,
        if_modified_since: str | None = None,
    ) -> FetchResult:
        self.discovery_calls.append((cli_location, if_none_match, if_modified_since))
        return self._take(self.discovery_results)

    async def fetch_product(self, product_id: str) -> FetchResult:
        self.product_calls.append(product_id)
        scripted = self.product_results.get(product_id)
        if scripted:
            return self._take(scripted)
        return self._take([self.default_product])

    @staticmethod
    def _take(queue: list[Any]) -> FetchResult:
        item = queue[0] if len(queue) == 1 else queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        assert isinstance(item, FetchResult)
        return item


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
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
def container(
    registry: SiteRegistry,
    clock: FakeClock,
    store: InMemoryStateStore,
    tmp_path: Path,
) -> Iterator[SharedIngestState]:
    """One real `SharedIngestState`, disposed afterwards.

    Constructed through a signature filter deliberately: this module must not
    fail to collect because a concurrently-evolving `SharedIngestState`
    constructor gained or lost a deployment-precondition parameter. Every
    keyword the current constructor *does* accept is still supplied.
    """
    candidates: dict[str, object] = {
        "registry": registry,
        "sites": ALL_SITES,
        "catalog_base": tmp_path / "nws",
        "store": store,
        "clock": clock,
        "kernel_config": FakeKernelConfig(),
        "cache_config": FakeCacheConfig(),
        "exec_engine_config": FakeExecEngineConfig(),
        "require_durable_store": False,
        "probe": LocalProbe(),
    }
    accepted = inspect.signature(SharedIngestState.__init__).parameters
    state = SharedIngestState(  # type: ignore[arg-type]
        **{key: value for key, value in candidates.items() if key in accepted}
    )
    try:
        yield state
    finally:
        state.dispose()


@pytest.fixture
def transport(container: SharedIngestState, monkeypatch: pytest.MonkeyPatch) -> TransportDouble:
    double = TransportDouble()
    monkeypatch.setattr(container.transport, "fetch_discovery_list", double.fetch_discovery_list)
    monkeypatch.setattr(container.transport, "fetch_product", double.fetch_product)
    return double


@pytest.fixture
def config() -> NwsIngestActorConfig:
    return NwsIngestActorConfig(
        # A real `ComponentId`, not a `str`. `msgspec.Struct.__init__` neither
        # validates nor converts, so a `str` here would never become the declared
        # type and the round-trip comparison below would raise rather than fail.
        # Pinned in `tests/contract/test_actor_timer_and_retry_contract.py`.
        component_id=ComponentId(f"NWS-{CITY}"),
        venue=VENUE,
        city=CITY,
        poll_interval_seconds=300,
        stagger_index=0,
        stagger_seconds=30,
        max_retries=2,
        retry_delay_initial_ms=1,
        retry_delay_max_ms=2,
    )


@pytest.fixture
def actor(
    config: NwsIngestActorConfig,
    container: SharedIngestState,
    clock: FakeClock,
) -> Iterator[NwsIngestActor]:
    """One Actor whose TWO clocks are pinned to the SAME simulated instant.

    The Actor reads two different clocks by design: `self.clock` (the Nautilus
    `Clock`, which owns timers and enforces `allow_past=False`) and the injected
    `Callable[[], int]` (which the gate, the index and the transport share, and
    from which the settlement deadline is derived).

    `TestComponentStubs.clock()` returns a **`LiveClock`**, so with the injected
    clock simulating 2026-08-22 the final-overdue deadline would be validated
    against the MACHINE's real date -- making every deadline test pass or fail
    depending on what time of day CI runs. Pinning both to `NOW_NS` removes that
    dependency entirely.
    """
    nautilus_clock = TestClock()
    nautilus_clock.set_time(clock())
    instance = NwsIngestActor(config, container=container)
    instance.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=nautilus_clock,
    )
    yield instance
    if not instance.is_disposed:
        instance.dispose_resources()


@pytest.fixture
def gate(container: SharedIngestState) -> SettlementGate:
    return container.gate


def _script_healthy_final_poll(transport: TransportDouble) -> str:
    """Script one discovery + one NYC final product fetch. Returns the text."""
    text = _fixture_text("nyc_final_2026-08-21")
    transport.discovery_results = [
        _fetch(_discovery_body((NYC_FINAL_UUID, "2026-08-22T06:26:00+00:00")))
    ]
    transport.product_results = {
        NYC_FINAL_UUID: [
            _fetch(
                _product_body(NYC_FINAL_UUID, text),
                url=f"https://api.weather.gov/products/{NYC_FINAL_UUID}",
            )
        ]
    }
    return text


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_config_survives_the_importable_actor_config_round_trip(
    config: NwsIngestActorConfig,
) -> None:
    """`ActorFactory.create` re-encodes `ImportableActorConfig.config` to JSON and
    decodes it through the config class (`common/config.py:609-614`). A field
    holding a live object, a `Path` or a `re.Pattern` breaks that silently at
    deployment time rather than here.
    """
    importable = ImportableActorConfig(
        actor_path=f"{NwsIngestActor.__module__}:{NwsIngestActor.__qualname__}",
        config_path=NwsIngestActorConfig.fully_qualified_name(),
        config=config.dict(),
    )
    # `msgspec_encoding_hook` is not optional garnish: `ActorFactory.create`
    # passes it (`common/config.py:612`), and without it a `ComponentId` in the
    # config dict raises `TypeError: Encoding objects of type ... is unsupported`.
    encoded = msgspec.json.encode(importable.config, enc_hook=msgspec_encoding_hook)
    restored = NwsIngestActorConfig.parse(encoded)

    assert restored == config


def test_msgspec_validates_on_decode_not_on_init() -> None:
    """The trap: a directly-constructed `msgspec.Struct` accepts a wrong type in
    silence, so `NwsIngestActorConfig(city=7)` is not the guard it looks like.
    `build_actor_config` routes through `msgspec.convert(..., strict=True)`,
    which is where validation actually happens.
    """
    smuggled = NwsIngestActorConfig(venue=VENUE, city=7)  # type: ignore[arg-type]
    assert smuggled.city == 7  # no error -- this is the trap being pinned

    with pytest.raises(msgspec.ValidationError):
        build_actor_config({"venue": VENUE, "city": 7})


def test_build_actor_config_rejects_unknown_fields() -> None:
    with pytest.raises(msgspec.ValidationError):
        build_actor_config({"venue": VENUE, "city": CITY, "typo_field": 1})


def test_build_actor_config_accepts_a_well_formed_mapping() -> None:
    built = build_actor_config({"venue": VENUE, "city": CITY, "poll_interval_seconds": 120})

    assert (built.venue, built.city, built.poll_interval_seconds) == (VENUE, CITY, 120)


# ---------------------------------------------------------------------------
# Lifecycle and timers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_start_arms_one_poll_timer_named_for_the_site(actor: NwsIngestActor) -> None:
    actor.start()

    assert poll_timer_name(VENUE, CITY) in actor.clock.timer_names


@pytest.mark.asyncio
async def test_stagger_is_a_start_time_offset_not_a_throttler(
    container: SharedIngestState,
) -> None:
    """SS2.3 / brief decision 2: the five-city stagger is a `start_time`
    argument on ONE `set_timer` call per Actor. `Throttler` is declined.
    """
    # One shared `TestClock` deliberately. In production `Trader.add_actor` gives
    # every Actor its OWN clock (`trading/trader.py:342`), so five `utc_now()`
    # readings differ by milliseconds -- which is why timer names cannot collide,
    # and also why measuring the stagger against five moving bases would measure
    # scheduling jitter rather than the stagger. Pinning it against one base is
    # what makes the `start_time` arithmetic itself assertable.
    shared_clock = TestClock()
    shared_clock.set_time(NOW_NS)
    started: list[NwsIngestActor] = []
    first_fires: list[int] = []
    for index, city in enumerate(("NYC", "SFO", "MIA")):
        instance = NwsIngestActor(
            NwsIngestActorConfig(
                component_id=ComponentId(f"NWS-{city}"),
                venue=VENUE,
                city=city,
                stagger_index=index,
                stagger_seconds=30,
            ),
            container=container,
        )
        instance.register_base(
            portfolio=TestComponentStubs.portfolio(),
            msgbus=TestComponentStubs.msgbus(),
            cache=TestComponentStubs.cache(),
            clock=shared_clock,
        )
        instance.start()
        started.append(instance)
        first_fires.append(instance.clock.next_time_ns(poll_timer_name(VENUE, city)))

    try:
        assert first_fires[1] - first_fires[0] == 30 * SECOND_NS
        assert first_fires[2] - first_fires[1] == 30 * SECOND_NS
    finally:
        for instance in started:
            instance.dispose_resources()


@pytest.mark.asyncio
async def test_on_start_arms_the_final_overdue_alert_for_the_pending_climate_day(
    actor: NwsIngestActor,
) -> None:
    actor.start()
    pending_day, deadline_ns = actor.pending_final_deadline()

    name = final_overdue_timer_name(CITY, pending_day)
    assert actor.clock.next_time_ns(name) == deadline_ns
    assert deadline_ns > NOW_NS


@pytest.mark.asyncio
async def test_on_stop_cancels_every_armed_timer(actor: NwsIngestActor) -> None:
    actor.start()
    assert actor.clock.timer_names

    actor.stop()

    assert actor.clock.timer_names == []


@pytest.mark.asyncio
async def test_on_stop_is_safe_when_no_timer_is_armed(actor: NwsIngestActor) -> None:
    """`LiveClock.cancel_timer` runs `Condition.is_in(name, self.timer_names)` and
    raises `KeyError` for an unknown name (`common/component.pyx:991-995`,
    verified). A blind `cancel_timer` in `on_stop` would therefore raise.
    """
    actor.start()
    actor.clock.cancel_timers()

    actor.stop()  # must not raise

    assert actor.is_stopped


@pytest.mark.asyncio
async def test_on_start_registers_with_the_shared_container(
    actor: NwsIngestActor,
    container: SharedIngestState,
) -> None:
    """Brief SS3.6: "all five Actors hold the same gate object" is an ASSERTED
    startup invariant, not a convention.
    """
    actor.start()

    assert (VENUE, CITY) in container.registered_sites()


@pytest.mark.asyncio
async def test_on_reset_clears_the_in_memory_cursor_but_not_the_durable_one(
    actor: NwsIngestActor,
    container: SharedIngestState,
) -> None:
    actor.start()
    actor.advance_cursor(ts_init=NOW_NS, dedupe_key="a" * 64)
    actor.stop()

    actor.reset()

    assert actor.resume_cursor is not None
    assert actor.resume_cursor.ts_init == NOW_NS


# ---------------------------------------------------------------------------
# SS4.1 -- the Rust-timer-thread bridge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timer_callback_submits_the_poll_to_the_captured_loop(
    actor: NwsIngestActor,
    transport: TransportDouble,
) -> None:
    """The callback runs on the Rust/tokio thread with no running loop, so the
    only working primitive is `asyncio.run_coroutine_threadsafe(coro, loop)`
    against a loop captured in `on_start`. Pinned in
    `tests/contract/test_live_timer_thread_affinity.py`.
    """
    _script_healthy_final_poll(transport)
    actor.start()
    done = threading.Event()

    def fire() -> None:
        actor.fire_poll_timer_for_test()
        done.set()

    worker = threading.Thread(target=fire)
    worker.start()
    for _ in range(500):
        await asyncio.sleep(0.005)
        if done.is_set() and transport.product_calls:
            break
    worker.join(timeout=5)
    await actor.drain_for_test()

    assert transport.discovery_calls
    assert transport.product_calls == [NYC_FINAL_UUID]


def test_a_backtest_performs_no_network_io(
    config: NwsIngestActorConfig,
    container: SharedIngestState,
    transport: TransportDouble,
) -> None:
    """`asyncio.get_running_loop()` raises in a backtest, which is the correct
    signal that the live bridge is not available. The timer callback must then
    perform NO network I/O rather than reaching for a fallback.
    """
    instance = NwsIngestActor(config, container=container)
    instance.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=TestComponentStubs.clock(),
    )
    try:
        instance.start()  # no running loop -- this is a backtest
        assert instance.event_loop is None

        instance.fire_poll_timer_for_test()

        assert transport.discovery_calls == []
        assert transport.product_calls == []
    finally:
        instance.dispose_resources()


@pytest.mark.asyncio
async def test_a_failed_poll_reaches_the_gate_through_the_done_callback(
    actor: NwsIngestActor,
    gate: SettlementGate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rust SWALLOWS exceptions raised in a timer callback, so supervision cannot
    rely on one escaping. `fut.exception()` in the done-callback is the only seam
    that carries a failure to `record_task_death`.
    """

    async def explode() -> None:
        raise RuntimeError("poll blew up")

    monkeypatch.setattr(actor, "poll_once", explode)
    actor.start()

    actor.fire_poll_timer_for_test()
    await actor.drain_for_test()

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.TASK_DEATH


# ---------------------------------------------------------------------------
# SS6 step 1 -- the poll gate is NOT `require_open`
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "block",
    [
        pytest.param(lambda g: g.record_parser_failure(VENUE, CITY), id="parser_failure"),
        pytest.param(lambda g: g.record_sanity_violation(VENUE, CITY), id="sanity_violation"),
        pytest.param(lambda g: g.record_task_death(VENUE, CITY), id="task_dead"),
        pytest.param(
            lambda g: g.record_write_integrity_violation(VENUE, CITY),
            id="write_integrity_violation",
        ),
        pytest.param(
            lambda g: g.record_transport_integrity_alarm(VENUE, CITY),
            id="transport_integrity_alarm",
        ),
        pytest.param(
            lambda g: g.record_redirect_integrity_alarm(VENUE, CITY), id="redirect_alarm"
        ),
        pytest.param(lambda g: g.record_client_error_defect(VENUE, CITY), id="client_defect"),
        pytest.param(
            lambda g: g.record_oversize_or_parse_timeout(VENUE, CITY), id="oversize_or_timeout"
        ),
        pytest.param(lambda g: g.record_ambiguous_headline(VENUE, CITY), id="ambiguous_headline"),
        pytest.param(
            lambda g: g.record_transient_failure(VENUE, CITY, final_window_elapsed=True),
            id="transient_blocked",
        ),
        pytest.param(lambda g: None, id="never_polled_default"),
    ],
)
@pytest.mark.asyncio
async def test_a_blocked_site_still_polls_and_a_clean_poll_reopens_it(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
    block: Callable[[SettlementGate], object],
) -> None:
    """**The single most important test in the phase** (brief SS7).

    The settlement gate is a USE-time gate consumed by the settlement resolver.
    It is not a poll gate. It defaults to BLOCKED until a successful poll, and
    `record_successful_poll` is only reachable FROM a poll -- so "a blocked site
    does not poll" deadlocks on first boot and never recovers.
    """
    block(gate)
    assert gate.status(VENUE, CITY).state is GateState.BLOCKED
    _script_healthy_final_poll(transport)
    actor.start()

    await actor.poll_once()

    assert transport.discovery_calls, "a BLOCKED site must still perform its poll"
    assert gate.status(VENUE, CITY).state is GateState.OPEN


@pytest.mark.asyncio
async def test_the_global_ua_trap_latch_forbids_network_io(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
) -> None:
    """The one block that genuinely forbids I/O: continuing to poll into a UA
    trap is what costs API access outright.
    """
    _script_healthy_final_poll(transport)
    actor.start()
    for venue, city in ALL_SITES:
        gate.record_forbidden_403(venue, city, cross_site_burst_detected=True)
    assert GateReason.UA_TRAP_403 in gate.blocking_causes(VENUE, CITY)

    await actor.poll_once()

    assert transport.discovery_calls == []


@pytest.mark.asyncio
async def test_an_active_backoff_window_forbids_network_io_until_it_expires(
    actor: NwsIngestActor,
    clock: FakeClock,
    transport: TransportDouble,
) -> None:
    _script_healthy_final_poll(transport)
    actor.start()
    actor.arm_backoff(seconds=120.0, reason="test")

    await actor.poll_once()
    assert transport.discovery_calls == []

    clock.advance_ns(121 * SECOND_NS)
    await actor.poll_once()
    assert len(transport.discovery_calls) == 1


@pytest.mark.asyncio
async def test_retry_after_drives_the_inter_poll_backoff_window(
    actor: NwsIngestActor,
    transport: TransportDouble,
    clock: FakeClock,
) -> None:
    """`RetryManager` cannot honour `Retry-After` -- its delay derives solely from
    attempt count (`live/retry.py:186-194`) and `exc.retry_after` is never read.
    The honouring window is therefore ours, and it lives BETWEEN polls.
    """
    transport.discovery_results = [RateLimitedError("429", retry_after="120")]
    actor.start()

    await actor.poll_once()

    assert actor.backoff_until_ns == clock() + 120 * SECOND_NS


@pytest.mark.asyncio
async def test_the_backoff_window_is_durable_across_a_restart(
    actor: NwsIngestActor,
    container: SharedIngestState,
    config: NwsIngestActorConfig,
    transport: TransportDouble,
) -> None:
    """`RetryManagerPool.acquire()` calls `clear()` (`retry.py:335` -> `:206-210`),
    so the manager holds no per-site state at all. Ours is persisted.
    """
    transport.discovery_results = [RateLimitedError("429", retry_after="300")]
    actor.start()
    await actor.poll_once()
    armed_until = actor.backoff_until_ns

    successor = NwsIngestActor(config, container=container)
    successor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=TestComponentStubs.clock(),
    )
    try:
        assert successor.backoff_until_ns == armed_until
    finally:
        successor.dispose_resources()


# ---------------------------------------------------------------------------
# RetryManager -- exc_types must list SIBLING LEAF types only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_integrity_alarm_propagates_out_of_the_retry_manager_uncaught(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
) -> None:
    """**The highest-value test in this file.** A regression here is silent and
    settlement-critical.

    `live/retry.py:172` is `except self.exc_types as e:` -- ordinary,
    isinstance-based `except`. Every integrity error in `ingest/http.py`
    subclasses `TransportError`, so listing the BASE would make `RetryManager`
    swallow and silently RETRY a `RedirectError` on `/products/{id}` -- a
    possibly hijacked settlement endpoint, exactly what
    `record_redirect_integrity_alarm` exists to hard-block.

    `retry_check` is not an escape hatch either: `retry.py:174-183` returns
    `None` with `result=False` rather than re-raising, which converts an
    integrity alarm into a silent no-op -- worse than retrying it.
    """
    transport.discovery_results = [
        RedirectError("redirected", status_code=302, location="https://evil.example/x")
    ]
    actor.start()

    await actor.poll_once()

    assert len(transport.discovery_calls) == 1, "an integrity alarm must NOT be retried"
    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.REDIRECT_INTEGRITY_ALARM


@pytest.mark.asyncio
async def test_a_content_encoding_alarm_is_also_never_retried(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
) -> None:
    transport.discovery_results = [ContentEncodingError("gzip on an identity request")]
    actor.start()

    await actor.poll_once()

    assert len(transport.discovery_calls) == 1
    assert gate.status(VENUE, CITY).reason is GateReason.TRANSPORT_INTEGRITY_ALARM


@pytest.mark.asyncio
async def test_a_server_error_is_retried_and_collapses_into_one_transient_strike(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
) -> None:
    """One retry sequence is ONE `record_transient_failure` call: three TCP
    attempts inside one poll are not three failed polls. Stated here rather than
    absorbed silently, because it changes what `_TRANSIENT_DEGRADE_THRESHOLD`
    counts.
    """
    transport.discovery_results = [
        ServerError("503", status_code=503),
        ServerError("503", status_code=503),
        _fetch(_discovery_body()),
    ]
    actor.start()

    await actor.poll_once()

    assert len(transport.discovery_calls) == 3, "ServerError is a retryable sibling leaf type"
    assert gate.status(VENUE, CITY).state is GateState.OPEN


@pytest.mark.asyncio
async def test_retry_exhaustion_is_a_failed_poll_not_a_no_op(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
) -> None:
    """`RetryManager.run` returns a bare `None` on exhaustion and logs through the
    Nautilus `Logger`, which DISCARDS records when logging is uninitialized
    (`component.pyx:1450-1451`). Assert on `.result`/`.last_exception`, never on
    log output -- and never let the `None` fall through as success.
    """
    transport.discovery_results = [TransportTimeoutError("timed out")]
    actor.start()

    await actor.poll_once()

    assert len(transport.discovery_calls) == 3  # 1 attempt + max_retries=2
    status = gate.status(VENUE, CITY)
    assert status.reason is GateReason.TRANSIENT_FAILURE
    assert status.state is not GateState.OPEN


@pytest.mark.asyncio
async def test_a_429_is_not_retried_inside_the_poll(
    actor: NwsIngestActor,
    transport: TransportDouble,
) -> None:
    """`RateLimitedError` is deliberately NOT in `exc_types`: retrying in ~0.5-2s
    against a server-stated wait risks escalating into an NWS abuse block, and
    the gate's UA-trap block is permanent until a manual
    `acknowledge_ua_trap_resolved()`. Wire it in only once the `Retry-After`
    honouring window exists -- which is the inter-poll window, not this loop.
    """
    transport.discovery_results = [RateLimitedError("429", retry_after="30")]
    actor.start()

    await actor.poll_once()

    assert len(transport.discovery_calls) == 1


@pytest.mark.asyncio
async def test_a_403_passes_the_cross_site_burst_signal_to_the_gate(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
) -> None:
    transport.discovery_results = [ForbiddenError("403")]
    actor.start()

    await actor.poll_once()

    assert gate.status(VENUE, CITY).state is GateState.BLOCKED
    assert gate.status(VENUE, CITY).reason in {
        GateReason.ABUSE_BLOCK_403,
        GateReason.UA_TRAP_403,
    }


# ---------------------------------------------------------------------------
# SS6 -- the two-stage poll sequence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_304_is_a_terminal_success_that_writes_no_record(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
    container: SharedIngestState,
) -> None:
    transport.discovery_results = [_fetch("", status=304)]
    actor.start()

    await actor.poll_once()

    assert transport.product_calls == []
    assert gate.status(VENUE, CITY).state is GateState.OPEN
    catalog = open_station_catalog(container.catalog_base, VENUE, CITY)
    assert read_climate_days(catalog) == []


@pytest.mark.asyncio
async def test_stored_validators_are_replayed_on_the_next_conditional_get(
    actor: NwsIngestActor,
    transport: TransportDouble,
) -> None:
    transport.discovery_results = [
        _fetch(_discovery_body(), etag='W/"abc123"'),
        _fetch("", status=304),
    ]
    actor.start()

    await actor.poll_once()
    await actor.poll_once()

    assert transport.discovery_calls[0][1] is None
    assert transport.discovery_calls[1][1] == 'W/"abc123"'


@pytest.mark.asyncio
async def test_an_already_ingested_product_is_never_refetched(
    actor: NwsIngestActor,
    container: SharedIngestState,
    transport: TransportDouble,
    gate: SettlementGate,
) -> None:
    """Brief SS3.4 job 1. Without discovery-time dedupe the same id is re-fetched
    every poll, each re-fetch gets a fresh `ts_init`, and the write appends a
    duplicate `NwsRawProduct` every cycle -- or collides and reports `skipped`,
    which routes to a CRIT hard block.
    """
    text = _script_healthy_final_poll(transport)
    container.product_index.observe(NYC_FINAL_UUID, _sha(text))
    actor.start()

    await actor.poll_once()

    assert transport.product_calls == []
    assert gate.status(VENUE, CITY).state is GateState.OPEN


@pytest.mark.asyncio
async def test_repolling_the_same_product_produces_no_duplicate_and_no_alarm(
    actor: NwsIngestActor,
    container: SharedIngestState,
    transport: TransportDouble,
    gate: SettlementGate,
) -> None:
    _script_healthy_final_poll(transport)
    actor.start()

    await actor.poll_once()
    await actor.poll_once()

    catalog = open_station_catalog(container.catalog_base, VENUE, CITY)
    assert len(read_climate_days(catalog)) == 1
    assert gate.status(VENUE, CITY).state is GateState.OPEN


@pytest.mark.asyncio
async def test_a_404_on_the_discovery_list_is_a_binding_error_not_a_transient(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
) -> None:
    """F4: `http.py` raises only for 3xx (except 304), 403, 429 and 5xx. A 404
    arrives as an ordinary `FetchResult`, and no amount of retrying makes a
    mistyped location exist.
    """
    transport.discovery_results = [_fetch("{}", status=404)]
    actor.start()

    await actor.poll_once()

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.CLIENT_ERROR_DEFECT


@pytest.mark.asyncio
async def test_a_sibling_station_product_is_skipped_with_no_gate_action(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
    container: SharedIngestState,
) -> None:
    """One WFO issues several cities' CLIs, so a `CLIJFK` arriving on the NYC poll
    is expected on a healthy system. Routine: skip the product, keep going.
    Recording anything here manufactures an outage out of normal operation.
    """
    sibling = _fixture_text("nyc_final_2026-08-21").replace("CLINYC", "CLIJFK", 1)
    ours = _fixture_text("nyc_final_2026-08-21")
    transport.discovery_results = [
        _fetch(
            _discovery_body(
                (NYC_PRELIM_UUID, "2026-08-22T06:20:00+00:00"),
                (NYC_FINAL_UUID, "2026-08-22T06:26:00+00:00"),
            )
        )
    ]
    transport.product_results = {
        NYC_PRELIM_UUID: [_fetch(_product_body(NYC_PRELIM_UUID, sibling))],
        NYC_FINAL_UUID: [_fetch(_product_body(NYC_FINAL_UUID, ours))],
    }
    actor.start()

    await actor.poll_once()

    assert transport.product_calls == [NYC_PRELIM_UUID, NYC_FINAL_UUID]
    assert gate.status(VENUE, CITY).state is GateState.OPEN
    catalog = open_station_catalog(container.catalog_base, VENUE, CITY)
    days = read_climate_days(catalog)
    assert [record.station for record in days] == ["NYC"]


@pytest.mark.asyncio
async def test_a_full_poll_persists_publishes_and_opens_the_gate(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
    container: SharedIngestState,
) -> None:
    text = _script_healthy_final_poll(transport)
    published: list[tuple[str, Any]] = []
    actor.start()
    actor.msgbus.subscribe(
        topic=f"data.{climate_day_type(venue=VENUE, city=CITY).topic}",
        handler=lambda msg: published.append(("day", msg)),
    )
    actor.msgbus.subscribe(
        topic=f"data.{raw_product_type(venue=VENUE, city=CITY).topic}",
        handler=lambda msg: published.append(("raw", msg)),
    )

    await actor.poll_once()

    catalog = open_station_catalog(container.catalog_base, VENUE, CITY)
    days = read_climate_days(catalog)
    assert len(days) == 1
    assert (days[0].station, days[0].tmax_f, days[0].tmin_f) == ("NYC", 79, 63)
    assert days[0].is_final is True
    assert days[0].raw_sha256 == _sha(text)
    assert gate.status(VENUE, CITY).state is GateState.OPEN
    assert {kind for kind, _ in published} == {"day", "raw"}
    assert all(
        isinstance(msg, NwsClimateDay if kind == "day" else NwsRawProduct)
        for kind, msg in published
    )


@pytest.mark.asyncio
async def test_publication_carries_the_raw_record_not_a_custom_data_wrapper(
    actor: NwsIngestActor,
    transport: TransportDouble,
) -> None:
    """`Actor.publish_data` runs `Condition.type(data, data_type.type, ...)`
    (`actor.pyx:2827`), which raises `TypeError` for a `CustomData` wrapper. The
    wrapper belongs to the catalog read path and `BacktestEngine.add_data`.
    """
    _script_healthy_final_poll(transport)
    seen: list[Any] = []
    actor.start()
    actor.msgbus.subscribe(
        topic=f"data.{climate_day_type(venue=VENUE, city=CITY).topic}",
        handler=seen.append,
    )

    await actor.poll_once()

    assert [type(item) for item in seen] == [NwsClimateDay]


@pytest.mark.asyncio
async def test_a_sanity_violation_blocks_with_its_own_reason(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
) -> None:
    """A malformed remote product must fail loudly, never settle quietly -- and it
    must name SANITY_VIOLATION, not PARSER_FAILURE: the text parsed correctly.
    """
    text = _fixture_text("nyc_final_2026-08-21").replace(
        "MAXIMUM         79", "MAXIMUM        250", 1
    )
    transport.discovery_results = [
        _fetch(_discovery_body((NYC_FINAL_UUID, "2026-08-22T06:26:00+00:00")))
    ]
    transport.product_results = {NYC_FINAL_UUID: [_fetch(_product_body(NYC_FINAL_UUID, text))]}
    actor.start()

    await actor.poll_once()

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.SANITY_VIOLATION


@pytest.mark.asyncio
async def test_a_parse_that_exceeds_the_wall_clock_ceiling_is_routed_as_a_timeout(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The 250 ms fuzz ceiling is a CI-time property test, not a production
    circuit-breaker. Nothing else measures real elapsed time, so a future regex
    edit could freeze the loop with no guard. The ceiling is enforced here.
    """
    import time

    _script_healthy_final_poll(transport)

    def slow_parse(*args: object, **kwargs: object) -> Any:
        time.sleep(0.5)
        raise AssertionError("should have been cancelled")

    monkeypatch.setattr("breezy.ingest.nws_actor.parse_cli_product", slow_parse)
    monkeypatch.setattr(actor, "parse_ceiling_seconds", 0.05)
    actor.start()

    await actor.poll_once()

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.OVERSIZE_OR_PARSE_TIMEOUT


@pytest.mark.asyncio
async def test_a_silently_skipped_write_is_an_integrity_violation(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The catalog skips a same-`ts_init`-range rewrite with a bare `print` and no
    exception (`parquet.py:378-380`). A successful return does not mean data was
    written.
    """
    from breezy.persistence.catalog import WriteOutcome

    _script_healthy_final_poll(transport)

    def skipping_write(catalog: Any, records: Sequence[Any]) -> WriteOutcome:
        return WriteOutcome(written=(), skipped=tuple(records), path="/tmp/x")

    monkeypatch.setattr("breezy.ingest.nws_actor.write_records", skipping_write)
    actor.start()

    await actor.poll_once()

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.WRITE_INTEGRITY_VIOLATION


@pytest.mark.asyncio
async def test_a_product_index_mismatch_is_a_crit_integrity_alarm(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
    container: SharedIngestState,
) -> None:
    """The tripwire of brief SS3.4 job 2: a uuid we have already seen coming back
    with DIFFERENT bytes. It should never fire in steady state -- that is the
    point, and why it must not be deleted as dead code.
    """
    _script_healthy_final_poll(transport)
    container.product_index.observe(NYC_FINAL_UUID, "b" * 64)
    actor.start()

    await actor.force_ingest_for_test(NYC_FINAL_UUID)

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.TRANSPORT_INTEGRITY_ALARM


# ---------------------------------------------------------------------------
# The final-overdue deadline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_final_overdue_deadline_fires_on_a_schedule_not_after_failed_fetches(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
) -> None:
    """The only orthogonal defence against a perpetual-304 staleness attack: a 304
    counts as a successful poll and resets `last_successful_poll_ns`, satisfying
    the liveness watchdog indefinitely while writing no record.
    """
    transport.discovery_results = [_fetch("", status=304)]
    actor.start()
    for _ in range(5):
        await actor.poll_once()
    assert gate.status(VENUE, CITY).state is GateState.OPEN

    pending_day, _ = actor.pending_final_deadline()
    await actor.fire_final_overdue_for_test(pending_day)

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.FINAL_CLI_OVERDUE


@pytest.mark.asyncio
async def test_a_final_for_the_exact_climate_day_clears_the_deadline(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
) -> None:
    _script_healthy_final_poll(transport)
    actor.start()
    gate.record_final_overdue(VENUE, CITY, "2026-08-21", NOW_NS)
    assert gate.status(VENUE, CITY).state is GateState.BLOCKED
    # Arm the alert for the EXACT day the fixture's final covers. Without this
    # the assertion below would hold vacuously: at NOW the pending day is
    # 2026-08-22, so no 2026-08-21 alert exists to cancel and the test would pass
    # whether or not `_clear_final_overdue` cancels anything at all.
    armed = final_overdue_timer_name(CITY, dt.date(2026, 8, 21))
    actor.clock.set_time_alert(
        armed,
        NOW + dt.timedelta(hours=1),
        callback=lambda event: None,
        override=True,
        allow_past=False,
    )
    assert actor.clock.next_time_ns(armed) > 0

    await actor.poll_once()

    assert gate.status(VENUE, CITY).state is GateState.OPEN
    assert actor.clock.next_time_ns(armed) == 0


@pytest.mark.asyncio
async def test_a_final_for_yesterday_does_not_clear_todays_deadline(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
) -> None:
    _script_healthy_final_poll(transport)
    actor.start()
    gate.record_final_overdue(VENUE, CITY, "2026-08-22", NOW_NS)

    await actor.poll_once()  # ingests the final for 2026-08-21

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert GateReason.FINAL_CLI_OVERDUE in gate.blocking_causes(VENUE, CITY)


@pytest.mark.asyncio
async def test_the_deadline_alert_is_rearmed_with_override_rather_than_duplicated(
    actor: NwsIngestActor,
) -> None:
    """`set_time_alert` with a duplicate name and NO `override=True` raises
    `KeyError` (`common/component.pyx:316`, verified).
    """
    actor.start()

    actor.arm_final_overdue()
    actor.arm_final_overdue()  # must not raise

    pending_day, _ = actor.pending_final_deadline()
    assert actor.clock.timer_names.count(final_overdue_timer_name(CITY, pending_day)) == 1


# ---------------------------------------------------------------------------
# Revision / supersession
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revision_seq_increments_per_station_and_climate_day(
    actor: NwsIngestActor,
    transport: TransportDouble,
    container: SharedIngestState,
    clock: FakeClock,
) -> None:
    """The supersession write path is ours: `ParquetDataCatalog` gives
    serialization, not supersession semantics. A correction landing after the
    first ingest is a NEW record with a later `ts_init` and `revision_seq` 2 --
    never a rewrite of the same range, which the catalog silently discards.
    """
    original = _fixture_text("nyc_final_2026-08-21")
    corrected = _fixture_text("nyc_correction_synthetic_2026-08-21")
    correction_uuid = "9f8e7d6c-5b4a-4392-8817-2635a4b5c6d7"
    transport.discovery_results = [
        _fetch(_discovery_body((NYC_FINAL_UUID, "2026-08-22T06:26:00+00:00"))),
        _fetch(_discovery_body((correction_uuid, "2026-08-22T12:00:00+00:00"))),
    ]
    transport.product_results = {
        NYC_FINAL_UUID: [_fetch(_product_body(NYC_FINAL_UUID, original))],
        correction_uuid: [
            _fetch(
                _product_body(correction_uuid, corrected),
                at_ns=NOW_NS + 3600 * SECOND_NS,
            )
        ],
    }
    actor.start()

    await actor.poll_once()
    clock.advance_ns(3600 * SECOND_NS)
    await actor.poll_once()

    catalog = open_station_catalog(container.catalog_base, VENUE, CITY)
    days = sorted(read_climate_days(catalog), key=lambda record: record.ts_init)
    assert [record.revision_seq for record in days] == [1, 2]
    assert all(record.is_superseded is False for record in days)


def test_a_mismatched_digest_cannot_even_be_constructed(
    container: SharedIngestState,
) -> None:
    """The first line of defence, and the reason the warm-start test below has to
    reach past it: `NwsRawProduct.__init__` recomputes `sha256(raw_text)` and
    refuses a record whose declared digest disagrees. A tampered record therefore
    cannot enter the process through construction at all -- only through mutation
    at rest, which is what `verify_digest` is for.
    """
    with pytest.raises(ValueError, match="raw_sha256"):
        NwsRawProduct(
            station="NYC",
            product_uuid=NYC_FINAL_UUID,
            product_code="CLI",
            issuing_office="KOKX",
            wmo_collective_id="CDUS41",
            awips_pil="CLINYC",
            wmo_bbb_token=None,
            issuance_time_ns=NOW_NS - 60 * SECOND_NS,
            retrieved_at_ns=NOW_NS,
            climate_day=dt.date(2026, 8, 21),
            raw_text="tampered",
            raw_sha256="c" * 64,
            response_sha256="d" * 64,
            response_etag=None,
            response_last_modified=None,
            source_channel="https://api.weather.gov/products/x",
            registry_version=container.registry.registry_version,
        )


@pytest.mark.asyncio
async def test_a_record_whose_digest_no_longer_verifies_is_not_republished(
    actor: NwsIngestActor,
    container: SharedIngestState,
    transport: TransportDouble,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`sha256(raw_text)` is computed at ingestion and MUST be verified before any
    later settlement use -- a stored digest alone is circular, and only
    recomputation detects mutation at rest.

    Mutation at rest is simulated by forcing `verify_digest` to fail, because the
    constructor (test above) makes a genuinely mismatched record unbuildable.
    """
    _script_healthy_final_poll(transport)
    actor.start()
    await actor.poll_once()
    actor.reset_cursor_for_test()

    class MutatedAtRest:
        """Stands in for a catalog row whose bytes changed under us.

        A stand-in rather than a patched `NwsRawProduct`, because patching
        `verify_digest` on the class also breaks the constructor's own check and
        makes the catalog read fail for the wrong reason.
        """

        ts_init = NOW_NS
        raw_sha256 = "e" * 64
        product_uuid = NYC_FINAL_UUID
        climate_day = dt.date(2026, 8, 21)

        @staticmethod
        def verify_digest() -> bool:
            return False

    monkeypatch.setattr(
        "breezy.ingest.nws_actor.read_raw_products", lambda catalog: [MutatedAtRest()]
    )
    seen: list[Any] = []
    actor.msgbus.subscribe(
        topic=f"data.{raw_product_type(venue=VENUE, city=CITY).topic}",
        handler=seen.append,
    )

    with caplog.at_level(logging.CRITICAL, logger="breezy.ingest.nws_actor"):
        await actor.warm_start()

    assert seen == [], "a record whose digest no longer verifies must not be republished"
    assert any("digest" in record.message.lower() for record in caplog.records)


# ---------------------------------------------------------------------------
# The resume cursor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_cursor_is_durable_at_the_instant_of_publish(
    actor: NwsIngestActor,
    transport: TransportDouble,
    store: InMemoryStateStore,
) -> None:
    """Brief SS3.3: the exit test must assert durability AT the moment of the kill.
    A test that kills and then observes over-publication passes whether or not
    the cursor was durable -- passing for the wrong reason.
    """
    _script_healthy_final_poll(transport)
    actor.start()
    snapshots: list[bytes | None] = []
    key = actor.cursor_store_key

    original = actor.publish_record

    def spy(record: Any, data_type: Any) -> None:
        original(record, data_type)
        snapshots.append(store.get(key))

    actor.publish_record = spy  # type: ignore[method-assign]

    await actor.poll_once()

    assert snapshots, "nothing was published"
    assert all(snapshot is not None for snapshot in snapshots), (
        "the cursor must be durable at every publish instant, not at graceful stop"
    )


@pytest.mark.asyncio
async def test_warm_start_republishes_only_records_after_the_cursor(
    actor: NwsIngestActor,
    container: SharedIngestState,
    transport: TransportDouble,
) -> None:
    _script_healthy_final_poll(transport)
    actor.start()
    await actor.poll_once()
    seen: list[Any] = []
    actor.msgbus.subscribe(
        topic=f"data.{climate_day_type(venue=VENUE, city=CITY).topic}",
        handler=seen.append,
    )

    await actor.warm_start()

    assert seen == [], "everything published already sits at or before the cursor"


@pytest.mark.asyncio
async def test_the_first_poll_waits_for_warm_start_to_finish(
    actor: NwsIngestActor,
    transport: TransportDouble,
) -> None:
    """Regression: warm start and the poll share ONE single-worker executor, so
    without an explicit gate the first poll can persist, publish and advance the
    cursor while warm start is still queued behind it -- and warm start, having
    already decided its `pending` set against the OLDER cursor, then republishes
    that same record. A duplicate publication of a settlement record is not
    cosmetic.

    Asserted as the ORDERING INVARIANT rather than by trying to lose a race:
    "no fetch happens while warm start is outstanding" is deterministic, whereas
    an interleaving test passes or fails on executor scheduling and would be
    green for the wrong reason.
    """
    _script_healthy_final_poll(transport)
    released = threading.Event()
    real_read = actor._read_catalog

    def blocking_read() -> Any:
        released.wait(timeout=5)
        return real_read()

    actor._read_catalog = blocking_read  # type: ignore[method-assign]
    actor.start()

    poll = asyncio.ensure_future(actor.poll_once())
    for _ in range(20):
        await asyncio.sleep(0.005)
    assert transport.discovery_calls == [], (
        "the poll fetched while warm start was still outstanding"
    )

    released.set()
    await poll
    await actor.drain_for_test()

    assert len(transport.discovery_calls) == 1


@pytest.mark.asyncio
async def test_warm_start_republishes_a_record_the_crash_window_swallowed(
    actor: NwsIngestActor,
    container: SharedIngestState,
    transport: TransportDouble,
) -> None:
    """Steps 9->12 are the crash window: a durably-written record no subscriber
    ever saw.
    """
    _script_healthy_final_poll(transport)
    actor.start()
    await actor.poll_once()
    actor.reset_cursor_for_test()
    seen: list[Any] = []
    actor.msgbus.subscribe(
        topic=f"data.{climate_day_type(venue=VENUE, city=CITY).topic}",
        handler=seen.append,
    )

    await actor.warm_start()

    assert [type(item) for item in seen] == [NwsClimateDay]


def test_equal_ts_init_records_are_not_lost_by_the_cursor(actor: NwsIngestActor) -> None:
    """`NwsClimateDay` and `NwsRawProduct` from one fetch share `retrieved_at_ns`,
    and a poll after downtime may stamp a preliminary and a final identically.
    A strict `>` on a bare `ts_init` loses the second one PERMANENTLY; `>=` on a
    bare `ts_init` re-publishes the last record on every warm start. The cursor
    is therefore `(ts_init, dedupe_key)`, compared with strict `>`.
    """
    actor.advance_cursor(ts_init=NOW_NS, dedupe_key="a" * 64)

    assert actor.is_after_cursor(ts_init=NOW_NS, dedupe_key="b" * 64) is True
    assert actor.is_after_cursor(ts_init=NOW_NS, dedupe_key="a" * 64) is False
    assert actor.is_after_cursor(ts_init=NOW_NS - 1, dedupe_key="z" * 64) is False
    assert actor.is_after_cursor(ts_init=NOW_NS + 1, dedupe_key="a" * 64) is True


# ---------------------------------------------------------------------------
# Component state is an OUTPUT of the gate, never gate truth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_gate_block_mirrors_to_component_degrade(
    actor: NwsIngestActor,
    transport: TransportDouble,
) -> None:
    """Adopted as an OUTPUT so operators get `ComponentStateChanged` on
    `events.system.{id}` -- never read back as gate truth.
    """
    transport.discovery_results = [_fetch("{}", status=404)]
    actor.start()

    await actor.poll_once()

    assert actor.is_degraded


@pytest.mark.asyncio
async def test_a_clean_poll_resumes_the_degraded_component(
    actor: NwsIngestActor,
    transport: TransportDouble,
) -> None:
    transport.discovery_results = [
        _fetch("{}", status=404),
        _fetch(_discovery_body()),
    ]
    actor.start()

    await actor.poll_once()
    assert actor.is_degraded

    await actor.poll_once()

    assert actor.is_running


def test_the_actor_never_calls_fault() -> None:
    """`fault()` is terminal and irreversible -- the FSM has no exit from FAULTED
    (`component.pyx:2129`, `:1649-1654`) -- while our BLOCKED must be clearable
    by a clean poll. Conflating them bricks the Actor.
    """
    import breezy.ingest.nws_actor as module

    source = Path(module.__file__).read_text(encoding="utf-8")

    assert "self.fault()" not in source
    assert ".fault()" not in source


# ---------------------------------------------------------------------------
# The staleness watchdog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_staleness_watchdog_escalates_a_silent_channel(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
    clock: FakeClock,
) -> None:
    """Nautilus ships no HTTP staleness watchdog -- `idle_timeout_ms` is
    WebSocket-only. This mirrors the bundled adapter's idle-timeout pattern onto
    the poll channel.
    """
    _script_healthy_final_poll(transport)
    actor.start()
    await actor.poll_once()
    assert gate.status(VENUE, CITY).state is GateState.OPEN

    clock.advance_ns((actor.staleness_blocked_after_seconds + 1) * SECOND_NS)
    actor.check_staleness()

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.STALE_BLOCKED


# ---------------------------------------------------------------------------
# Envelope parsing -- size and depth caps
# ---------------------------------------------------------------------------


def test_parse_discovery_list_extracts_ids_in_issuance_order() -> None:
    body = _discovery_body(
        (NYC_FINAL_UUID, "2026-08-22T06:26:00+00:00"),
        (NYC_PRELIM_UUID, "2026-08-21T20:44:00+00:00"),
    )

    entries = parse_discovery_list(body, cli_location="NYC")

    assert [entry.product_uuid for entry in entries] == [NYC_PRELIM_UUID, NYC_FINAL_UUID]


def test_parse_discovery_list_rejects_a_non_cli_product_code() -> None:
    body = json.dumps({"@graph": [{"id": NYC_FINAL_UUID, "productCode": "CLM"}]})

    entries = parse_discovery_list(body, cli_location="NYC")

    assert entries == ()


def test_parse_discovery_list_rejects_an_over_deep_document() -> None:
    nested: Any = {"@graph": []}
    cursor = nested
    for _ in range(80):
        cursor["nested"] = {}
        cursor = cursor["nested"]

    with pytest.raises(ValueError, match="depth"):
        parse_discovery_list(json.dumps(nested), cli_location="NYC")


def test_parse_discovery_list_rejects_a_malformed_body() -> None:
    with pytest.raises(ValueError):
        parse_discovery_list("not json at all", cli_location="NYC")


def test_parse_product_envelope_extracts_the_provenance_fields() -> None:
    text = _fixture_text("nyc_final_2026-08-21")

    envelope = parse_product_envelope(_product_body(NYC_FINAL_UUID, text))

    assert envelope.product_uuid == NYC_FINAL_UUID
    assert envelope.product_code == "CLI"
    assert envelope.issuing_office == "KOKX"
    assert envelope.wmo_collective_id == "CDUS41"
    assert envelope.product_text == text
    assert envelope.issuance_time_ns > 0


def test_parse_product_envelope_rejects_a_missing_product_text() -> None:
    body = json.dumps({"id": NYC_FINAL_UUID, "productCode": "CLI"})

    with pytest.raises(ValueError):
        parse_product_envelope(body)


# ---------------------------------------------------------------------------
# Durable state: restart, and the fail-direction of every corrupt-state branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_resume_cursor_is_restored_by_a_successor_process(
    actor: NwsIngestActor,
    container: SharedIngestState,
    config: NwsIngestActorConfig,
    transport: TransportDouble,
) -> None:
    """The whole point of the cursor being durable: a successor must not
    re-publish what its predecessor already published.
    """
    _script_healthy_final_poll(transport)
    actor.start()
    await actor.poll_once()
    original = actor.resume_cursor
    assert original is not None

    successor = NwsIngestActor(config, container=container)
    try:
        assert successor.resume_cursor == original
        assert successor.is_after_cursor(
            ts_init=original.ts_init, dedupe_key=original.dedupe_key
        ) is False
    finally:
        successor.dispose_resources()


def test_an_unreadable_cursor_fails_towards_republishing_not_towards_loss(
    config: NwsIngestActorConfig,
    container: SharedIngestState,
    store: InMemoryStateStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Deliberate fail direction. A corrupt cursor resolves to "publish
    everything again", because a duplicate publication is recoverable and a lost
    settlement record is not. This is the opposite direction from the corrupt
    BACKOFF state below, and the asymmetry is intentional.
    """
    instance = NwsIngestActor(config, container=container)
    key = instance.cursor_store_key
    instance.dispose_resources()
    store.set(key, b"{not json")

    with caplog.at_level(logging.CRITICAL, logger="breezy.ingest.nws_actor"):
        reloaded = NwsIngestActor(config, container=container)

    try:
        assert reloaded.resume_cursor is None
        assert reloaded.is_after_cursor(ts_init=1, dedupe_key="a") is True
        assert any("cursor" in record.message.lower() for record in caplog.records)
    finally:
        reloaded.dispose_resources()


@pytest.mark.asyncio
async def test_corrupt_backoff_state_fails_closed_and_holds_the_site_off_the_network(
    actor: NwsIngestActor,
    store: InMemoryStateStore,
    transport: TransportDouble,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The opposite fail direction from the cursor, and correct: an unreadable
    backoff window must never resolve to "no wait", which would let a corrupted
    record hammer an origin that had just asked us to stop.
    """
    _script_healthy_final_poll(transport)
    actor.start()
    store.set(actor.backoff_store_key, b"\xff\xfe not json")

    with caplog.at_level(logging.CRITICAL, logger="breezy.ingest.nws_actor"):
        await actor.poll_once()

    assert transport.discovery_calls == []
    assert any("backoff" in record.message.lower() for record in caplog.records)


@pytest.mark.asyncio
async def test_unreadable_cache_validators_fall_back_to_an_unconditional_fetch(
    actor: NwsIngestActor,
    store: InMemoryStateStore,
    transport: TransportDouble,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Dropping a malformed validator is the safe direction HERE, unlike a
    malformed validator arriving from the wire (which `http.py` rejects as a
    possible header-injection attempt). The cost is one uncached fetch; the
    alternative is a site that can never poll again.
    """
    _script_healthy_final_poll(transport)
    actor.start()
    store.set(actor.validator_store_key, b"{not json")

    with caplog.at_level(logging.WARNING, logger="breezy.ingest.nws_actor"):
        await actor.poll_once()

    assert transport.discovery_calls == [("NYC", None, None)]


# ---------------------------------------------------------------------------
# Remaining error routes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_catalog_write_path_exception_is_a_write_integrity_violation(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`write_records` reports a silent skip by RETURNING and these by RAISING.
    Both ends of that split must be covered, or a durable-write failure reaches
    an OPEN gate on discipline alone.
    """
    from breezy.persistence.catalog import NonMonotonicWriteError

    _script_healthy_final_poll(transport)

    def exploding_write(catalog: Any, records: Sequence[Any]) -> Any:
        raise NonMonotonicWriteError("ts_init went backwards")

    monkeypatch.setattr("breezy.ingest.nws_actor.write_records", exploding_write)
    actor.start()

    await actor.poll_once()

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.WRITE_INTEGRITY_VIOLATION


@pytest.mark.asyncio
async def test_a_transport_failure_on_the_product_fetch_stops_the_poll(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
) -> None:
    """Stage B has its own transport-error route. A discovery-only test would
    leave it unexercised, and an integrity alarm there is the more serious of the
    two: `/products/{id}` is the settlement document itself.
    """
    _script_healthy_final_poll(transport)
    transport.product_results = {
        NYC_FINAL_UUID: [
            RedirectError("moved", status_code=302, location="https://evil.example/x")
        ]
    }
    actor.start()

    await actor.poll_once()

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.REDIRECT_INTEGRITY_ALARM


@pytest.mark.asyncio
async def test_a_malformed_discovery_body_is_a_parse_failure_not_a_transient(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
) -> None:
    transport.discovery_results = [_fetch("{}")]  # no '@graph'
    actor.start()

    await actor.poll_once()

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.PARSER_FAILURE


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(json.dumps([1, 2, 3]), id="not_an_object"),
        pytest.param(json.dumps({"@graph": {"id": "x"}}), id="graph_not_a_list"),
        pytest.param(json.dumps({"@graph": ["not-an-object"]}), id="entry_not_an_object"),
        pytest.param(
            json.dumps({"@graph": [{"productCode": "CLI", "issuanceTime": "2026-01-01T00:00Z"}]}),
            id="entry_without_id",
        ),
        pytest.param(
            json.dumps({"@graph": [{"id": "x", "productCode": "CLI"}]}),
            id="missing_issuance_time",
        ),
        pytest.param(
            json.dumps({"@graph": [{"id": "x", "productCode": "CLI", "issuanceTime": "nope"}]}),
            id="unparseable_issuance_time",
        ),
        pytest.param(
            json.dumps(
                {"@graph": [{"id": "x", "productCode": "CLI", "issuanceTime": "2026-01-01T00:00"}]}
            ),
            id="naive_issuance_time",
        ),
        pytest.param(
            json.dumps({"@graph": [{"id": f"u{i}", "productCode": "CLI"} for i in range(200)]}),
            id="over_the_entry_cap",
        ),
    ],
)
def test_parse_discovery_list_rejects_a_structurally_wrong_document(body: str) -> None:
    with pytest.raises(ValueError):
        parse_discovery_list(body, cli_location="NYC")


def test_parse_product_envelope_rejects_a_non_object_document() -> None:
    with pytest.raises(ValueError):
        parse_product_envelope(json.dumps(["not", "an", "object"]))


def test_parse_product_envelope_rejects_a_naive_issuance_time() -> None:
    body = json.dumps(
        {
            "id": NYC_FINAL_UUID,
            "productCode": "CLI",
            "issuingOffice": "KOKX",
            "wmoCollectiveId": "CDUS41",
            "issuanceTime": "2026-08-22T06:26:00",
            "productText": "x",
        }
    )

    with pytest.raises(ValueError, match="timezone"):
        parse_product_envelope(body)


def test_a_retry_after_http_date_is_ignored_rather_than_guessed(
    actor: NwsIngestActor,
) -> None:
    """Delta-seconds only. An HTTP-date `Retry-After` depends on agreement with
    the origin's clock, and a skewed one yields either no wait at all or an
    unbounded one -- so it is not parsed, and the ordinary backoff applies.
    """
    assert actor.pending_final_deadline()[1] > 0  # actor is usable
    assert NwsIngestActor._retry_after_seconds("Wed, 21 Oct 2026 07:28:00 GMT") is None
    assert NwsIngestActor._retry_after_seconds("-5") is None
    assert NwsIngestActor._retry_after_seconds(None) is None
    assert NwsIngestActor._retry_after_seconds(" 30 ") == 30.0


# ---------------------------------------------------------------------------
# The cross-thread bridge: every branch that decides whether a failure is seen
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_submission_after_the_loop_closed_is_dropped_not_raised(
    actor: NwsIngestActor,
    transport: TransportDouble,
    gate: SettlementGate,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Shutdown race. The timer callback runs on the Rust/tokio thread, which
    SWALLOWS exceptions -- so a raise here is invisible, not loud. It is dropped
    at INFO and deliberately does NOT strike the gate: a CRIT on every clean
    shutdown trains operators to ignore the one that matters.
    """
    _script_healthy_final_poll(transport)
    actor.start()
    dead = asyncio.new_event_loop()
    dead.close()
    actor._loop = dead

    with caplog.at_level(logging.INFO, logger="breezy.ingest.nws_actor"):
        actor.fire_poll_timer_for_test()

    assert transport.discovery_calls == []
    assert gate.status(VENUE, CITY).reason is not GateReason.TASK_DEATH
    assert any("loop closed" in record.message for record in caplog.records) or any(
        "loop closed" in str(record.getMessage()) for record in caplog.records
    )


@pytest.mark.asyncio
async def test_a_submission_while_the_loop_is_closing_is_dropped_not_raised(
    actor: NwsIngestActor,
    transport: TransportDouble,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`run_coroutine_threadsafe` raises `RuntimeError` on a loop that has begun
    closing but is not yet closed -- a state `loop.is_closed()` still reports as
    False, so the guard above does not cover this and both are needed.
    """
    _script_healthy_final_poll(transport)
    actor.start()

    def refuse(coro: Any, loop: Any) -> Any:
        raise RuntimeError("Event loop is closed")

    monkeypatch.setattr(asyncio, "run_coroutine_threadsafe", refuse)

    with caplog.at_level(logging.INFO, logger="breezy.ingest.nws_actor"):
        actor.fire_poll_timer_for_test()

    assert transport.discovery_calls == []
    assert any("loop closing" in record.getMessage() for record in caplog.records)


def test_a_task_death_with_no_loop_left_is_logged_critical_not_swallowed(
    actor: NwsIngestActor,
    gate: SettlementGate,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The last-ditch branch of the ONLY supervision seam there is. The routing
    hop needs the loop; if the loop is gone the gate cannot be driven to BLOCKED,
    and the one remaining obligation is to say so at CRITICAL rather than return
    quietly and leave an OPEN gate over a dead poller.
    """
    import concurrent.futures

    future: concurrent.futures.Future[None] = concurrent.futures.Future()
    future.set_running_or_notify_cancel()
    future.set_exception(RuntimeError("poll blew up"))
    actor._loop = None

    with caplog.at_level(logging.CRITICAL, logger="breezy.ingest.nws_actor"):
        actor._on_task_done(future)

    assert any("the loop is gone" in record.getMessage() for record in caplog.records)
    assert any(record.levelno == logging.CRITICAL for record in caplog.records)


@pytest.mark.asyncio
async def test_the_final_overdue_timer_callback_records_through_the_loop(
    actor: NwsIngestActor,
    gate: SettlementGate,
) -> None:
    """The deadline callback is the settlement watchdog's only trigger. It fires
    on the Rust thread like the poll timer, so it must SUBMIT rather than touch
    the gate inline -- brief SS4.1 hazard 2 puts all state mutation on the loop.
    """
    actor.start()

    actor._on_final_overdue_timer(None)
    await actor.drain_for_test()

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.FINAL_CLI_OVERDUE


def test_on_dispose_releases_the_executor(actor: NwsIngestActor) -> None:
    """Nautilus calls `on_dispose` from `Component.dispose()`; the executor is
    ours, so nothing else will reclaim the thread.
    """
    actor.start()
    assert actor._io_executor is not None
    assert actor._parse_executor is not None

    actor.on_dispose()

    assert actor._io_executor is None
    assert actor._parse_executor is None
    actor.on_dispose()  # idempotent


# ---------------------------------------------------------------------------
# Remaining routed outcomes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_404_on_the_product_fetch_stops_the_poll_at_stage_b(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
    container: SharedIngestState,
) -> None:
    """Stage B routes fetch results through the same table as stage A but on its
    own branch, so a discovery-only test leaves it unproven. The product URL is
    the settlement document: a 404 there must not be silently skipped.
    """
    _script_healthy_final_poll(transport)
    transport.product_results = {NYC_FINAL_UUID: [_fetch("{}", status=404)]}
    actor.start()

    await actor.poll_once()

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.CLIENT_ERROR_DEFECT
    catalog = open_station_catalog(container.catalog_base, VENUE, CITY)
    assert read_climate_days(catalog) == []


@pytest.mark.asyncio
async def test_an_unclassifiable_issuance_blocks_the_site_as_an_ambiguous_headline(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deliberately driven by a patched classifier, and the reason matters.

    `classify_issuance` today raises only on empty text, which the structural
    allowlist rejects FIRST -- so no real product can reach this branch. It is
    defence for the classifier `classify.py` will become: preliminary-vs-final is
    the two-issuance trap, and a wrong answer settles a market on a preliminary.
    Pinning the wiring now means the day ambiguity becomes representable, the
    route to `record_ambiguous_headline` is already proven rather than written
    under pressure.

    Flagged for the routing seam's owner: `routing.GateAction` carries no member
    for this outcome, so the Actor records it directly (module docstring,
    deviation 3).
    """
    from breezy.normalize.classify import ClassificationError

    _script_healthy_final_poll(transport)

    def ambiguous(product_text: str) -> Any:
        raise ClassificationError("two VALID TODAY lines; cannot classify")

    monkeypatch.setattr("breezy.ingest.nws_actor.classify_issuance", ambiguous)
    actor.start()

    await actor.poll_once()

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.AMBIGUOUS_HEADLINE


# ---------------------------------------------------------------------------
# The retry seam's own invariants
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_retry_manager_that_reports_neither_result_nor_exception_still_fails(
    actor: NwsIngestActor,
    gate: SettlementGate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`RetryManager.run` returns `None` on failure and records the cause on
    `last_exception`. If a future version ever reports failure WITHOUT a cause,
    the one outcome that must not happen is `None` flowing on as a successful
    poll -- an OPEN gate over a fetch that never happened. Fail closed instead.
    """

    class _Blank:
        result = False
        last_exception = None
        message = "vanished"

        async def run(self, *args: Any, **kwargs: Any) -> None:
            return None

    monkeypatch.setattr(
        "breezy.ingest.nws_actor.RetryManager", lambda *a, **k: _Blank()
    )
    actor.start()

    await actor.poll_once()

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED


def test_a_fetched_result_cannot_open_the_gate_before_the_record_is_persisted(
    actor: NwsIngestActor,
    gate: SettlementGate,
) -> None:
    """The deferral guard, asserted at its own seam.

    `record_successful_poll` on a FETCHED would declare the site healthy over a
    body that has not been parsed, sanity-checked, digested or written. Today
    every call site happens to respect that; this pins the guard itself, so a
    refactor that adds a call site -- or drops the `action_is_deferred` check --
    fails RED here instead of quietly opening the gate over unpersisted data.
    """
    from breezy.ingest.routing import PollOutcome, route_fetch_result

    decision = route_fetch_result(
        _fetch(_discovery_body((NYC_FINAL_UUID, "2026-08-22T06:26:00+00:00")))
    )
    assert decision.outcome is PollOutcome.FETCHED
    assert decision.action_is_deferred is True

    actor._execute(decision)
    assert gate.status(VENUE, CITY).state is GateState.BLOCKED, (
        "a FETCHED must not open the gate before the write is confirmed"
    )

    actor._execute(decision, redeem_deferred=True)
    assert gate.status(VENUE, CITY).state is GateState.OPEN


# ---------------------------------------------------------------------------
# Warm start: the timeout, and the skip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_stuck_warm_start_degrades_to_polling_rather_than_wedging(
    container: SharedIngestState,
    transport: TransportDouble,
    clock: FakeClock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Deliberate fail direction, and the opposite of the ordering test above.

    Waiting for warm start is what stops a duplicate publication -- but waiting
    FOREVER stops ingestion outright, and a site that never polls misses the
    settlement window. A duplicate is recoverable; a missed final is not. So the
    wait is bounded, the breach is CRITICAL, and the poll proceeds.
    """
    _script_healthy_final_poll(transport)
    instance = NwsIngestActor(
        NwsIngestActorConfig(
            component_id=ComponentId(f"NWS-{CITY}"),
            venue=VENUE,
            city=CITY,
            warm_start_timeout_seconds=0.05,
        ),
        container=container,
    )
    nautilus_clock = TestClock()
    nautilus_clock.set_time(clock())
    instance.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=nautilus_clock,
    )
    released = threading.Event()
    real_read = instance._read_catalog

    def blocking_read() -> Any:
        released.wait(timeout=5)
        return real_read()

    instance._read_catalog = blocking_read  # type: ignore[method-assign]
    instance.start()

    try:
        with caplog.at_level(logging.CRITICAL, logger="breezy.ingest.nws_actor"):
            await instance.poll_once()

        assert len(transport.discovery_calls) == 1, "a stuck warm start must not wedge polling"
        assert any("warm start did not finish" in r.getMessage() for r in caplog.records)
    finally:
        released.set()
        await instance.drain_for_test()
        instance.dispose_resources()


@pytest.mark.asyncio
async def test_warm_start_does_not_republish_the_archive_record_at_the_cursor(
    actor: NwsIngestActor,
    transport: TransportDouble,
) -> None:
    """The raw archive has its own topic and its own arm of the cursor filter.
    Asserting only the climate-day topic would leave the archive arm unproven,
    and a duplicate raw record breaks the `(productCode, location, summary_date,
    hash)` dedupe contract just as a duplicate settlement record does.
    """
    _script_healthy_final_poll(transport)
    actor.start()
    await actor.poll_once()
    seen: list[Any] = []
    actor.msgbus.subscribe(
        topic=f"data.{raw_product_type(venue=VENUE, city=CITY).topic}",
        handler=seen.append,
    )

    await actor.warm_start()

    assert seen == [], "the archived raw sits AT the cursor and must not be republished"


def test_a_publish_set_with_no_climate_day_leaves_the_deadline_armed() -> None:
    """`_clear_final_overdue` keys off the climate day in the published set. An
    archive-only set (raw stored, no day derived) must resolve to "no day", so
    the settlement watchdog stays armed rather than being cancelled by a write
    that settled nothing.
    """
    from breezy.ingest.nws_actor import _climate_day_of

    assert _climate_day_of(()) is None


@pytest.mark.asyncio
async def test_the_cursor_lands_on_the_maximum_of_what_was_just_published(
    actor: NwsIngestActor,
    transport: TransportDouble,
) -> None:
    """The invariant the resume cursor rests on, asserted directly.

    `advance_cursor` overwrites unconditionally, so the cursor after a poll is
    whatever was published LAST -- not necessarily the greatest key published.
    Warm start filters with a strict `>` over `(ts_init, dedupe_key)`, so if
    publication order disagrees with that order, everything published after the
    maximum is re-published on EVERY warm start, forever. The two records from
    one fetch share `ts_init`, so the tiebreaker alone decides it.

    Regression: publication ran in build order (raw, then day) while
    `"NwsClimateDay" < "NwsRawProduct"`, leaving the cursor on the day and the
    archive record permanently above it.
    """
    from breezy.ingest.nws_actor import _cursor_key

    _script_healthy_final_poll(transport)
    published: list[Any] = []
    for data_type in (
        raw_product_type(venue=VENUE, city=CITY),
        climate_day_type(venue=VENUE, city=CITY),
    ):
        actor.msgbus.subscribe(topic=f"data.{data_type.topic}", handler=published.append)
    actor.start()

    await actor.poll_once()

    assert sorted(type(item).__name__ for item in published) == [
        "NwsClimateDay",
        "NwsRawProduct",
    ]
    cursor = actor.resume_cursor
    assert cursor is not None
    assert (cursor.ts_init, cursor.dedupe_key) == max(_cursor_key(item) for item in published), (
        "the cursor must land on the greatest key published, not merely the last one"
    )


# ---------------------------------------------------------------------------
# The two-issuance trap, and the deadline's day boundary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_preliminary_is_ingested_but_does_not_satisfy_the_final_deadline(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
    container: SharedIngestState,
) -> None:
    """The two-issuance trap, from the ingestion side.

    NYC issues a PRELIMINARY CLI at 4:44 PM local and a FINAL the next morning,
    both for climate day 2026-08-21, both headed `CLIMATE SUMMARY` -- so wording
    is not the discriminator; the `VALID TODAY AS OF 0400 PM LOCAL TIME.` line
    is. The preliminary is archived and published (it is real data), but it must
    NOT clear the final-overdue deadline: treating it as settlement-grade is
    exactly how a market settles on a value the 4 AM final revises.
    """
    text = _fixture_text("nyc_preliminary_2026-08-21")
    assert "VALID TODAY AS OF" in text, "fixture must carry the discriminator line"
    transport.discovery_results = [
        _fetch(_discovery_body((NYC_PRELIM_UUID, "2026-08-21T20:44:00+00:00")))
    ]
    transport.product_results = {
        NYC_PRELIM_UUID: [
            _fetch(
                _product_body(
                    NYC_PRELIM_UUID, text, issuance_time="2026-08-21T20:44:00+00:00"
                ),
                url=f"https://api.weather.gov/products/{NYC_PRELIM_UUID}",
            )
        ]
    }
    actor.start()
    armed = final_overdue_timer_name(CITY, dt.date(2026, 8, 21))
    actor.clock.set_time_alert(
        armed,
        NOW + dt.timedelta(hours=1),
        callback=lambda event: None,
        override=True,
        allow_past=False,
    )

    await actor.poll_once()

    assert gate.status(VENUE, CITY).state is GateState.OPEN, "a preliminary is a healthy poll"
    catalog = open_station_catalog(container.catalog_base, VENUE, CITY)
    assert [record.climate_day for record in read_climate_days(catalog)] == [
        dt.date(2026, 8, 21)
    ], "the preliminary is archived like any other product"
    assert actor.clock.next_time_ns(armed) > 0, (
        "a PRELIMINARY must never clear the final-overdue deadline"
    )


def test_the_watchdog_guards_yesterday_until_yesterdays_deadline_actually_passes(
    actor: NwsIngestActor,
    clock: FakeClock,
) -> None:
    """The day boundary the settlement watchdog turns on, pinned on both sides.

    Two clocks, deliberately: the candidate climate day comes from the FIXED
    standard-time offset (-5 for NYC, never DST-aware, because the climate day is
    defined in local standard time), while the deadline comes from the venue's
    DST-following clock (08:00 America/New_York = 12:00 UTC in August). Reading
    either one from the other's accessor moves the boundary by an hour and, at
    the wrong hour, by a whole day.
    """
    before = int(dt.datetime(2026, 8, 22, 10, 0, tzinfo=dt.UTC).timestamp()) * SECOND_NS
    clock.now = before
    day, deadline_ns = actor.pending_final_deadline()
    assert day == dt.date(2026, 8, 21)
    assert deadline_ns == int(
        dt.datetime(2026, 8, 22, 12, 0, tzinfo=dt.UTC).timestamp()
    ) * SECOND_NS
    assert deadline_ns > before

    clock.now = int(dt.datetime(2026, 8, 22, 12, 0, tzinfo=dt.UTC).timestamp()) * SECOND_NS
    rolled_day, rolled_deadline = actor.pending_final_deadline()
    assert rolled_day == dt.date(2026, 8, 22), "at the deadline instant it rolls, not after"
    assert rolled_deadline == int(
        dt.datetime(2026, 8, 23, 12, 0, tzinfo=dt.UTC).timestamp()
    ) * SECOND_NS


@pytest.mark.asyncio
async def test_an_unparseable_retry_after_arms_no_backoff_window(
    actor: NwsIngestActor,
    transport: TransportDouble,
) -> None:
    """`Retry-After` as an HTTP-date is ignored rather than guessed (a skewed
    origin clock yields either no wait or an unbounded one). Ignored must mean
    the ordinary path applies -- not a window of `None` seconds, and not a poll
    that can never run again.
    """
    transport.discovery_results = [
        _fetch("{}", status=404, retry_after="Wed, 21 Oct 2026 07:28:00 GMT")
    ]
    actor.start()

    await actor.poll_once()

    assert actor.may_poll() is True, "an unparseable Retry-After must not lock the site out"


# ---------------------------------------------------------------------------
# Executor isolation: the event loop, the parse worker and catalog I/O
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_as_of_catalog_read_runs_off_the_event_loop(
    actor: NwsIngestActor,
    transport: TransportDouble,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`read_climate_day_including_corrections` is documented "Unbounded on
    purpose" (`catalog.py:620-659`): a full pyarrow scan of the station's whole
    history, growing monotonically with retention. All five site Actors share one
    event loop, so running it inline freezes all five -- the identical hazard
    `_write_off_loop`'s own docstring invokes to justify offloading the write one
    line later. It must go through the same I/O executor the write does.
    """
    loop_thread = threading.current_thread()
    seen: list[threading.Thread] = []
    real = nws_actor_module.read_climate_day_including_corrections

    def spy(*args: Any, **kwargs: Any) -> Any:
        seen.append(threading.current_thread())
        return real(*args, **kwargs)

    monkeypatch.setattr(
        "breezy.ingest.nws_actor.read_climate_day_including_corrections", spy
    )
    _script_healthy_final_poll(transport)
    actor.start()

    await actor.poll_once()

    assert seen, "the as-of read never ran"
    assert all(thread is not loop_thread for thread in seen), (
        "the unbounded catalog read ran on the event-loop thread"
    )
    assert all(thread.name.startswith("breezy-nws-io-") for thread in seen), (
        f"the read must run on the catalog I/O executor, ran on {[t.name for t in seen]}"
    )


@pytest.mark.asyncio
async def test_a_wedged_parse_does_not_starve_catalog_io(
    actor: NwsIngestActor,
    transport: TransportDouble,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The single-worker starvation defect, as a property.

    `asyncio.wait_for` cancels only the awaiting coroutine.
    `concurrent.futures.Future.cancel()` is a no-op once a call has STARTED, and
    Python cannot interrupt a running thread -- so a stalled parse keeps its
    worker forever. With one shared `max_workers=1` executor behind the parse,
    the write and the warm-start catalog read, every later catalog operation
    queues behind that stall and never returns: the site can then never complete
    a successful poll, which is the only mechanism that clears any block.

    Raising `max_workers` only delays this. The parse must have its OWN worker so
    catalog I/O is structurally unreachable from a parse stall.
    """
    release = threading.Event()

    def wedged_parse(*args: object, **kwargs: object) -> Any:
        # Never returns until the test releases it: exactly the uninterruptible
        # case, not a slow-but-finite one.
        release.wait(timeout=30)
        raise AssertionError("parse should have been abandoned, not awaited")

    monkeypatch.setattr("breezy.ingest.nws_actor.parse_cli_product", wedged_parse)
    monkeypatch.setattr(actor, "parse_ceiling_seconds", 0.05)
    _script_healthy_final_poll(transport)
    actor.start()

    try:
        await actor.poll_once()  # parse ceiling fires; the worker stays wedged

        assert actor._parse_executor is not actor._io_executor, (
            "the parse and catalog I/O must not share a worker"
        )
        # The load-bearing assertion: catalog I/O still completes PROMPTLY while
        # the parse worker is permanently occupied.
        await asyncio.wait_for(actor.warm_start(), timeout=5.0)
    finally:
        release.set()


@pytest.mark.asyncio
async def test_inflight_submissions_are_bounded_rather_than_leaked(
    actor: NwsIngestActor,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`_inflight` must not grow without bound.

    `may_poll()` deliberately checks only the UA-trap latch and the backoff
    window, never general BLOCKED state, so the poll timer keeps firing through
    any block. If every fired poll's future is retained unconditionally, a site
    that cannot complete a poll leaks one future per cadence tick forever.
    """
    actor.start()

    async def _never() -> None:
        await asyncio.sleep(30)

    submitted: list[Any] = []
    try:
        with caplog.at_level(logging.CRITICAL, logger="breezy.ingest.nws_actor"):
            for _ in range(MAX_INFLIGHT_TASKS + 8):
                actor._submit(_never(), what="poll")
        assert len(actor._inflight) <= MAX_INFLIGHT_TASKS
        assert any("in-flight" in record.message.lower() for record in caplog.records)
    finally:
        for future in list(actor._inflight):
            future.cancel()
        submitted.clear()


class _InterleavedInflightLock:
    """A `threading.Lock` facade that PINS one interleaving of two `_submit`s.

    The cap in `_submit` is a check-then-act pair. Whether it holds depends
    entirely on whether ONE hold of the lock spans BOTH halves, and that
    question is invisible to any single-threaded test: run `_submit` in a loop
    on one thread and a check-only lock passes, because there is no second
    thread to slip between the check and the insert.

    So the interleaving is not raced for -- it is imposed, with events only, no
    sleeps and no timing assumptions. `A` is the thread that gets the lock
    first; `B` is the one that arrives second.

    1. A enters `_submit` and takes the lock. `a_holds_lock` is set, which is
       B's cue to call `_submit` at all -- so "A first" is a precondition of
       the script rather than something the scheduler decides.
    2. At A's FIRST release, and while A still HOLDS the lock, A waits for
       `b_reached_lock`. That flag is set BEFORE B's blocking `acquire`, so B
       is provably queued behind A rather than merely "probably slower".
    3. A performs the real release, then waits for `b_holds_lock` before
       running any further, so A cannot race ahead of B's check.

    Under a lock spanning only the check, step 2 fires after A's check and
    BEFORE A's insert, so B reads a set A has not yet grown and both
    submissions are admitted. Under a lock spanning check-through-insert, step
    2 fires after A's insert, so B reads the set A already grew and B is the
    one that trips the cap. Same script, opposite outcome, no timing.
    """

    def __init__(self, *, timeout: float = 10.0) -> None:
        self._lock = threading.Lock()
        self._timeout = timeout
        self.a_ident: int | None = None
        self.b_ident: int | None = None
        self._a_release_seen = False
        self.a_holds_lock = threading.Event()
        self.b_reached_lock = threading.Event()
        self.b_holds_lock = threading.Event()

    def __enter__(self) -> bool:
        me = threading.get_ident()
        if me == self.b_ident:
            # Announced BEFORE blocking, so A can prove B is queued.
            self.b_reached_lock.set()
        self._lock.acquire()
        if me == self.a_ident:
            self.a_holds_lock.set()
        if me == self.b_ident:
            self.b_holds_lock.set()
        return True

    def __exit__(self, *exc_info: object) -> None:
        if threading.get_ident() == self.a_ident and not self._a_release_seen:
            self._a_release_seen = True
            reached = self.b_reached_lock.wait(timeout=self._timeout)
            self._lock.release()
            if not reached:
                raise AssertionError("thread B never reached the in-flight lock")
            if not self.b_holds_lock.wait(timeout=self._timeout):
                raise AssertionError("thread B never acquired the in-flight lock")
            return
        self._lock.release()


@pytest.mark.asyncio
async def test_the_inflight_cap_is_atomic_across_check_and_insert(
    actor: NwsIngestActor,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Two concurrent `_submit`s at the cap boundary admit exactly ONE.

    `_submit` runs on the Rust/tokio timer thread, and this Actor arms TWO
    timers (the poll cadence and the final-overdue alert), so two callbacks can
    be inside `_submit` at once. With the set at `MAX_INFLIGHT_TASKS - 1`, a
    lock held across the check ALONE lets both read `over_cap = False`, both
    insert, and the set land at `MAX_INFLIGHT_TASKS + 1` -- over the cap, with
    NO CRITICAL logged. The breach is silent, which defeats the entire point of
    the cap: the log line IS the alarm it exists to raise.

    The assertion is deliberately on both halves. `len(...) <= cap` alone would
    pass on an implementation that dropped BOTH submissions; the CRITICAL alone
    would pass on one that logged and then inserted anyway.
    """
    actor.start()
    # `on_start` submits warm start; this test owns the set, so reclaim it.
    for future in list(actor._inflight):
        future.cancel()
    actor._inflight.clear()

    async def _never() -> None:
        await asyncio.sleep(30)

    filler = [concurrent.futures.Future[None]() for _ in range(MAX_INFLIGHT_TASKS - 1)]
    actor._inflight.update(filler)
    assert len(actor._inflight) == MAX_INFLIGHT_TASKS - 1

    facade = _InterleavedInflightLock()
    actor._inflight_lock = facade  # type: ignore[assignment]
    a_ready = threading.Event()
    b_ready = threading.Event()
    go = threading.Event()
    failures: list[AssertionError] = []
    completed: set[str] = set()

    def _thread_a() -> None:
        facade.a_ident = threading.get_ident()
        a_ready.set()
        go.wait(timeout=10)
        # Only `AssertionError` is caught, and only to carry the lock facade's
        # own timeout diagnostics back to the main thread. Any other failure is
        # caught by `completed`, which stays unset when `_submit` does not return.
        try:
            actor._submit(_never(), what="poll")
        except AssertionError as exc:  # pragma: no cover - surfaced by the assert below
            failures.append(exc)
        else:
            completed.add("a")

    def _thread_b() -> None:
        facade.b_ident = threading.get_ident()
        b_ready.set()
        go.wait(timeout=10)
        # A must own the lock before B even enters `_submit`, so which thread
        # is "first" is fixed by the script and not by the scheduler.
        if not facade.a_holds_lock.wait(timeout=10):  # pragma: no cover
            failures.append(AssertionError("thread A never took the in-flight lock"))
            return
        try:
            actor._submit(_never(), what="final-overdue")
        except AssertionError as exc:  # pragma: no cover - surfaced by the assert below
            failures.append(exc)
        else:
            completed.add("b")

    thread_a = threading.Thread(target=_thread_a, name="submit-a")
    thread_b = threading.Thread(target=_thread_b, name="submit-b")
    thread_a.start()
    thread_b.start()

    try:
        with caplog.at_level(logging.CRITICAL, logger="breezy.ingest.nws_actor"):
            assert a_ready.wait(timeout=10) and b_ready.wait(timeout=10)
            go.set()
            thread_a.join(timeout=20)
            thread_b.join(timeout=20)
        assert not thread_a.is_alive() and not thread_b.is_alive(), "a submit thread wedged"
        assert failures == []
        assert completed == {"a", "b"}, f"a `_submit` call did not return cleanly: {completed}"

        assert len(actor._inflight) == MAX_INFLIGHT_TASKS, (
            "the check and the insert must happen under ONE hold of the lock; the set "
            f"holds {len(actor._inflight)} against a cap of {MAX_INFLIGHT_TASKS}"
        )
        assert [record.message for record in caplog.records if "DROPPED" in record.message], (
            "the submission that lost the race must be dropped with a CRITICAL, not "
            "admitted over the cap in silence"
        )
    finally:
        go.set()
        for future in list(actor._inflight):
            future.cancel()
        actor._inflight.clear()


class _DefaultExecutorSpy(concurrent.futures.ThreadPoolExecutor):
    """Stands in for the loop's process-wide default executor and records use.

    `BaseEventLoop.run_in_executor` resolves `executor is None` to
    `self._default_executor`, and CONSTRUCTS a fresh multi-worker
    `ThreadPoolExecutor` when that is `None` too
    (`asyncio/base_events.py:888-896`, CPython 3.13.13 as installed). Installing
    a spy as the default via the PUBLIC `loop.set_default_executor` turns "did
    this call silently reroute?" into a recorded fact rather than an inference
    off a private attribute.
    """

    def __init__(self) -> None:
        super().__init__(max_workers=2, thread_name_prefix="default-executor-spy")
        self.submissions: list[str] = []

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Any:  # type: ignore[override]
        self.submissions.append(getattr(fn, "__name__", repr(fn)))
        return super().submit(fn, *args, **kwargs)


@pytest.mark.asyncio
async def test_executor_work_submitted_after_disposal_fails_loudly(
    actor: NwsIngestActor,
) -> None:
    """A coroutine resuming after `dispose_resources` must NOT keep working.

    `dispose_resources` sets both executor attributes to `None`. A coroutine
    suspended mid-poll when disposal runs resumes and reads the attribute
    fresh, so passing it straight to `run_in_executor` hands over `None` --
    which resolves to the loop's default executor and, failing that, to a
    newly constructed process-wide MULTI-WORKER one.

    That escapes the single-worker serialisation the catalog path depends on:
    `write_records` takes an `flock` on the station root and requires
    non-decreasing `ts_init` within a batch, and both `on_start` executors are
    `max_workers=1` for exactly that reason. Two catalog operations for one
    station running concurrently is the failure this Actor is built to prevent
    -- and it would happen silently, at precisely the point the design needs it
    to fail loudly.

    All four seams that read an executor attribute are covered, because the
    defect is per-call-site: one unguarded read is enough to reopen it.
    """
    actor.start()
    loop = asyncio.get_running_loop()
    spy = _DefaultExecutorSpy()
    loop.set_default_executor(spy)
    try:
        actor.dispose_resources()

        with pytest.raises(ExecutorDisposedError):
            await actor._read_existing_off_loop(dt.date(2026, 8, 21))
        with pytest.raises(ExecutorDisposedError):
            await actor._parse_with_ceiling(_fixture_text("nyc_final_2026-08-21"))
        with pytest.raises(ExecutorDisposedError):
            await actor._write_off_loop([])
        with pytest.raises(ExecutorDisposedError):
            await actor.warm_start()

        assert spy.submissions == [], (
            "post-disposal work reached the process-wide default executor; the "
            f"single-worker serialisation is gone -- {spy.submissions}"
        )
    finally:
        loop.set_default_executor(concurrent.futures.ThreadPoolExecutor(max_workers=1))
        spy.shutdown(wait=False)


@pytest.mark.asyncio
async def test_disposal_is_idempotent_and_never_passes_none_to_run_in_executor(
    actor: NwsIngestActor,
) -> None:
    """The guard is the ONLY reader of the two executor attributes.

    Pinned structurally as well as behaviourally: a future call site that reads
    `self._io_executor` or `self._parse_executor` directly and hands it to
    `run_in_executor` would reopen the defect without failing any behavioural
    test, because the attributes are non-`None` for the whole of a healthy run.
    """
    source = inspect.getsource(nws_actor_module.NwsIngestActor)
    for line in source.splitlines():
        stripped = line.strip()
        if "run_in_executor(" not in stripped:
            continue
        assert "self._io_executor" not in stripped and "self._parse_executor" not in stripped, (
            "an executor attribute is passed to `run_in_executor` without the "
            f"disposal guard: {stripped!r}"
        )

    actor.start()
    actor.dispose_resources()
    actor.dispose_resources()  # idempotent
    assert actor._io_executor is None
    assert actor._parse_executor is None


@pytest.mark.asyncio
async def test_on_stop_requests_cancellation_of_in_flight_submissions(
    actor: NwsIngestActor,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`on_stop` shrinks the window `ExecutorDisposedError` is the backstop for.

    A true DRAIN is not available here and never was: `on_stop` is a synchronous
    Cython handler running ON the loop thread, so it cannot `await`, and
    blocking there would deadlock against the very coroutines it is waiting for
    -- they need that same thread to make progress. `drain_for_test` is `async`
    for exactly this reason and cannot be called from the real lifecycle.

    The available non-blocking move is to REQUEST cancellation.
    `run_coroutine_threadsafe`'s `concurrent.futures.Future` stays PENDING until
    the task finishes, so `.cancel()` succeeds and `_chain_future`'s
    `_call_check_cancel` hops `task.cancel()` onto the loop
    (`asyncio/futures.py:393-397`). The coroutine then raises `CancelledError`
    at its next await and `_on_task_done` returns quietly on it -- so a clean
    shutdown does not manufacture a gate strike out of a poll that was simply
    told to stop.

    It cannot hang on a wedged parse worker, which is the constraint that chose
    `shutdown(wait=False)`: cancelling the awaiting coroutine never touches the
    worker thread, and the worker is abandoned either way.

    This does NOT retire `ExecutorDisposedError`. `dispose_resources()` is
    reachable without `stop()` (this module's own fixture does exactly that),
    and a coroutine already past its last await point cannot be cancelled.
    """
    actor.start()
    for future in list(actor._inflight):
        future.cancel()
    actor._inflight.clear()

    entered = asyncio.Event()

    async def _long_poll() -> None:
        entered.set()
        await asyncio.sleep(30)

    actor._submit(_long_poll(), what="poll")
    await asyncio.wait_for(entered.wait(), timeout=5)
    tracked = list(actor._inflight)
    assert len(tracked) == 1

    with caplog.at_level(logging.CRITICAL, logger="breezy.ingest.nws_actor"):
        actor.stop()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 5.0
        while actor._inflight and loop.time() < deadline:
            await asyncio.sleep(0.01)

    assert actor._inflight == set(), "in-flight submissions outlived `on_stop`"
    assert tracked[0].cancelled(), "`on_stop` must request cancellation, not merely forget"
    assert [record for record in caplog.records if record.levelno >= logging.CRITICAL] == [], (
        "a cancelled poll is a clean shutdown, not an alarm"
    )


# ---------------------------------------------------------------------------
# Fail directions proved against the REAL durable store
#
# Every fail-direction test above uses `InMemoryStateStore`, which has no CRC32
# and structurally CANNOT raise `StateStoreCorruptError`. Those tests prove the
# design (a decode failure resolves in the documented direction); they cannot
# prove the deployment. In production the store is `FileStateStore`, whose
# `get()` raises `StateStoreCorruptError` on a per-key CRC32 failure -- and the
# chain is `StateStoreCorruptError` -> `StateStoreError` -> `RuntimeError`
# (`state_store.py:149,153`), which `except (ValueError, KeyError, TypeError,
# UnicodeDecodeError)` does not catch. These pin the real deployment behaviour.
# ---------------------------------------------------------------------------


def _flip_one_byte_of_value(path: Path, key: str) -> None:
    """Corrupt exactly one key's stored payload so it fails its CRC32 check,
    while keeping the JSON container itself well-formed -- so the effect is
    attributable only to the store's per-value CRC discipline and never to a
    broken JSON parse. Deliberately duplicated rather than imported: test
    modules in this project do not cross-import.
    """
    parsed = json.loads(path.read_text())
    raw = bytearray(base64.b64decode(parsed[key]["data"]))
    raw[0] ^= 0xFF
    parsed[key]["data"] = base64.b64encode(bytes(raw)).decode("ascii")
    path.write_text(json.dumps(parsed))


def _durable_container(
    *,
    registry: SiteRegistry,
    clock: FakeClock,
    store: FileStateStore,
    catalog_base: Path,
) -> SharedIngestState:
    """A real `SharedIngestState` over a real `FileStateStore`.

    Built here rather than through the module's `container` fixture because
    these tests need to close the store, corrupt one key on disk and reopen --
    and because `SharedIngestState` permits exactly one live instance per
    process, so a fixture-supplied container would already hold the slot.
    """
    candidates: dict[str, object] = {
        "registry": registry,
        "sites": ALL_SITES,
        "catalog_base": catalog_base,
        "store": store,
        "clock": clock,
        "kernel_config": FakeKernelConfig(),
        "cache_config": FakeCacheConfig(),
        "exec_engine_config": FakeExecEngineConfig(),
        "require_durable_store": False,
        "probe": LocalProbe(),
    }
    accepted = inspect.signature(SharedIngestState.__init__).parameters
    return SharedIngestState(  # type: ignore[arg-type]
        **{key: value for key, value in candidates.items() if key in accepted}
    )


def test_a_crc_corrupt_cursor_does_not_crash_actor_construction(
    tmp_path: Path,
    registry: SiteRegistry,
    clock: FakeClock,
    config: NwsIngestActorConfig,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`_load_cursor` runs from `__init__` (`:601`). A `StateStoreCorruptError`
    escaping it takes the Actor's CONSTRUCTION down -- the site never exists, so
    it can never poll, and the documented fail direction ("re-publish rather than
    risk losing a record") never gets a chance to apply.
    """
    path = tmp_path / "durable" / "state.json"
    store = FileStateStore(path)
    container = _durable_container(
        registry=registry, clock=clock, store=store, catalog_base=tmp_path / "nws"
    )
    try:
        seed = NwsIngestActor(config, container=container)
        cursor_key = seed.cursor_store_key
        seed.advance_cursor(ts_init=NOW_NS, dedupe_key="NwsClimateDay:deadbeef")
        seed.dispose_resources()
    finally:
        container.dispose()
        store.close()

    _flip_one_byte_of_value(path, cursor_key)

    reopened = FileStateStore(path)
    successor_container = _durable_container(
        registry=registry, clock=clock, store=reopened, catalog_base=tmp_path / "nws"
    )
    try:
        with caplog.at_level(logging.CRITICAL, logger="breezy.ingest.nws_actor"):
            successor = NwsIngestActor(config, container=successor_container)

        assert successor.resume_cursor is None, "must fail TOWARDS re-publishing"
        assert successor.is_after_cursor(ts_init=1, dedupe_key="a") is True
        assert any("cursor" in record.message.lower() for record in caplog.records)
        successor.dispose_resources()
    finally:
        successor_container.dispose()
        reopened.close()


@pytest.mark.asyncio
async def test_a_crc_corrupt_backoff_key_fails_closed_gracefully_and_recoverably(
    tmp_path: Path,
    registry: SiteRegistry,
    clock: FakeClock,
    config: NwsIngestActorConfig,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`backoff_until_ns` is read on every `may_poll()`, so a
    `StateStoreCorruptError` here raises out of `may_poll()` -> `poll_once()`
    into generic task-death every cycle. That fails closed only by accident: the
    site is held off the network by an unhandled exception rather than by the
    documented graceful window, and the CRIT diagnostic that names the cause
    never fires.
    """
    path = tmp_path / "durable" / "state.json"
    store = FileStateStore(path)
    container = _durable_container(
        registry=registry, clock=clock, store=store, catalog_base=tmp_path / "nws"
    )
    try:
        seed = NwsIngestActor(config, container=container)
        backoff_key = seed.backoff_store_key
        seed.arm_backoff(seconds=1.0, reason="seed")
        seed.dispose_resources()
    finally:
        container.dispose()
        store.close()

    _flip_one_byte_of_value(path, backoff_key)

    reopened = FileStateStore(path)
    successor_container = _durable_container(
        registry=registry, clock=clock, store=reopened, catalog_base=tmp_path / "nws"
    )
    double = TransportDouble()
    monkeypatch.setattr(
        successor_container.transport, "fetch_discovery_list", double.fetch_discovery_list
    )
    monkeypatch.setattr(successor_container.transport, "fetch_product", double.fetch_product)
    try:
        successor = NwsIngestActor(config, container=successor_container)
        nautilus_clock = TestClock()
        nautilus_clock.set_time(clock())
        successor.register_base(
            portfolio=TestComponentStubs.portfolio(),
            msgbus=TestComponentStubs.msgbus(),
            cache=TestComponentStubs.cache(),
            clock=nautilus_clock,
        )
        successor.start()

        with caplog.at_level(logging.CRITICAL, logger="breezy.ingest.nws_actor"):
            assert successor.backoff_until_ns > clock(), "graceful closed window, not a raise"
            assert successor.may_poll() is False
            await successor.poll_once()

        assert double.discovery_calls == [], "a corrupt backoff key must hold the site off"
        assert any("backoff" in record.message.lower() for record in caplog.records)

        # RECOVERABLE: one clean write clears the corrupt marker for that key.
        successor.arm_backoff(seconds=0.0, reason="operator cleared")
        assert successor.may_poll() is True
        successor.dispose_resources()
    finally:
        successor_container.dispose()
        reopened.close()


@pytest.mark.asyncio
async def test_a_crc_corrupt_validator_key_drops_to_an_unconditional_fetch(
    tmp_path: Path,
    registry: SiteRegistry,
    clock: FakeClock,
    config: NwsIngestActorConfig,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`_load_validators` runs at `:934`, BEFORE any fetch. A
    `StateStoreCorruptError` escaping it blocks the site outright rather than
    dropping to the documented one uncached fetch.
    """
    path = tmp_path / "durable" / "state.json"
    store = FileStateStore(path)
    container = _durable_container(
        registry=registry, clock=clock, store=store, catalog_base=tmp_path / "nws"
    )
    try:
        seed = NwsIngestActor(config, container=container)
        validator_key = seed.validator_store_key
        seed._store_validators(_fetch("{}", etag='W/"seed-etag"'))
        seed.dispose_resources()
    finally:
        container.dispose()
        store.close()

    _flip_one_byte_of_value(path, validator_key)

    reopened = FileStateStore(path)
    successor_container = _durable_container(
        registry=registry, clock=clock, store=reopened, catalog_base=tmp_path / "nws"
    )
    double = TransportDouble()
    monkeypatch.setattr(
        successor_container.transport, "fetch_discovery_list", double.fetch_discovery_list
    )
    monkeypatch.setattr(successor_container.transport, "fetch_product", double.fetch_product)
    try:
        successor = NwsIngestActor(config, container=successor_container)
        nautilus_clock = TestClock()
        nautilus_clock.set_time(clock())
        successor.register_base(
            portfolio=TestComponentStubs.portfolio(),
            msgbus=TestComponentStubs.msgbus(),
            cache=TestComponentStubs.cache(),
            clock=nautilus_clock,
        )
        _script_healthy_final_poll(double)
        successor.start()

        with caplog.at_level(logging.WARNING, logger="breezy.ingest.nws_actor"):
            await successor.poll_once()

        assert double.discovery_calls == [("NYC", None, None)], (
            "a corrupt validator must drop to ONE unconditional fetch, not block the site"
        )
        successor.dispose_resources()
    finally:
        successor_container.dispose()
        reopened.close()


# ---------------------------------------------------------------------------
# The remaining concurrency defects
# ---------------------------------------------------------------------------


class ClosingLoop:
    """A loop that reports itself OPEN and then refuses the hop.

    The TOCTOU window `_on_task_done` leaves: it checks
    `loop is None or loop.is_closed()` and then calls `call_soon_threadsafe`
    unguarded. Between those two statements the loop can finish closing.
    """

    def __init__(self) -> None:
        self.calls = 0

    @staticmethod
    def is_closed() -> bool:
        return False

    def call_soon_threadsafe(self, *args: Any, **kwargs: Any) -> Any:
        self.calls += 1
        raise RuntimeError("Event loop is closed")


def test_a_loop_that_closes_inside_the_toctou_window_is_reported_not_raised(
    actor: NwsIngestActor,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`_on_task_done` is a `concurrent.futures` done-callback. A `RuntimeError`
    raised inside one is logged by CPython through its OWN internal logger and
    goes no further, so the failed poll never reaches
    `route_unhandled_exception` and is never recorded as a gate strike. The
    docstring's claim that all three branches are handled must actually hold.
    """
    future: concurrent.futures.Future[None] = concurrent.futures.Future()
    future.set_running_or_notify_cancel()
    future.set_exception(RuntimeError("poll blew up"))
    closing = ClosingLoop()
    actor._loop = closing  # type: ignore[assignment]

    with caplog.at_level(logging.CRITICAL, logger="breezy.ingest.nws_actor"):
        actor._on_task_done(future)  # must not raise

    assert closing.calls == 1, "the hop must actually have been attempted"
    assert any(record.levelno == logging.CRITICAL for record in caplog.records)
    assert any("gate could not" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_an_overlapping_poll_is_skipped_not_run_concurrently(
    actor: NwsIngestActor,
    transport: TransportDouble,
    container: SharedIngestState,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`_submit` schedules on every timer fire regardless of whether the previous
    poll is still in flight. Two overlapping polls can both pass the
    `known_digest(...) is None` check before either calls `_index.observe(...)`,
    so both compute `revision_seq = 1` for the same `(station, climate_day)` --
    violating the documented monotonic invariant -- and the duplicate write then
    trips a false-positive `WRITE_INTEGRITY_VIOLATION` CRIT out of a purely
    benign scheduling duplicate.

    The overlapping fire is SKIPPED, not queued: see `poll_once`'s docstring.
    """
    text = _fixture_text("nyc_final_2026-08-21")
    gate_open = asyncio.Event()

    async def slow_discovery(
        cli_location: str,
        *,
        if_none_match: str | None = None,
        if_modified_since: str | None = None,
    ) -> FetchResult:
        transport.discovery_calls.append((cli_location, if_none_match, if_modified_since))
        await gate_open.wait()
        return _fetch(_discovery_body((NYC_FINAL_UUID, "2026-08-22T06:26:00+00:00")))

    transport.product_results = {NYC_FINAL_UUID: [_fetch(_product_body(NYC_FINAL_UUID, text))]}
    monkeypatch.setattr(container.transport, "fetch_discovery_list", slow_discovery)
    actor.start()

    first = asyncio.create_task(actor.poll_once())
    await asyncio.sleep(0)  # let `first` reach the awaiting fetch
    overlapped_concurrently = False
    try:
        with caplog.at_level(logging.WARNING, logger="breezy.ingest.nws_actor"):
            # Bounded so an UNGUARDED overlapping poll -- which blocks on the same
            # fetch as `first` -- fails the test instead of hanging the suite.
            await asyncio.wait_for(actor.poll_once(), timeout=2.0)
    except TimeoutError:
        overlapped_concurrently = True
    finally:
        gate_open.set()
        await first

    assert not overlapped_concurrently, (
        "the overlapping poll blocked on the in-flight fetch instead of returning"
    )
    assert transport.discovery_calls == [("NYC", None, None)], (
        "the overlapping poll must not have started a second discovery fetch"
    )

    catalog = open_station_catalog(container.catalog_base, VENUE, CITY)
    days = read_climate_days(catalog)
    assert [record.revision_seq for record in days] == [1]


# ---------------------------------------------------------------------------
# Supersession: a non-correction must never outrank a correction
# ---------------------------------------------------------------------------


def _as_rra_retransmission(product_text: str) -> str:
    """Re-stamp a product's WMO heading with an `RRA` BBB indicator.

    `RRx` is a routine DELAYED/RETRANSMITTED report, NOT a correction -- see
    `CliStructuralHeader.wmo_bbb`, which spells out that `wmo_bbb is not None`
    is the obvious-looking correction test and is wrong. So no correction
    evidence exists anywhere in this text and no integrity alarm fires on the
    BBB token itself.
    """
    lines = product_text.split("\n")
    assert lines[2].strip().startswith("CDUS41 KOKX 220626"), lines[2]
    lines[2] = "CDUS41 KOKX 220626 RRA"
    return "\n".join(lines)


@pytest.mark.asyncio
async def test_an_rra_retransmission_may_not_supersede_a_correction(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
    container: SharedIngestState,
    clock: FakeClock,
) -> None:
    """NYC, climate day 2026-08-21, in arrival order.

    1. FINAL says TMAX 79            -> revision 1
    2. a genuine `CCA` correction says 80 -> revision 2
    3. a delayed `RRA` retransmission of the UNCORRECTED text arrives last

    `revision_seq` is assigned purely on ingestion order, so (3) would take
    revision 3 and outrank the correction -- and because `RRA` is a routine
    retransmission and not a correction, nothing else raises an alarm. A
    corrected temperature silently reverts to 79.

    `header.is_correction_bbb` is computed on every ingest and appears exactly
    once in the module, inside a LOG MESSAGE. This pins it as a decision: a
    non-correction issuance whose content DIFFERS from an existing correction
    for the same `(station, climate_day)` is an anomaly, and the write path fails
    closed on it rather than persisting a superseding revision.

    Fixing `revision_seq` alone would not close this, because the downstream
    selector orders by arrival time ahead of `revision_seq`. That selector is out
    of scope here; refusing the WRITE is what closes it at this seam.
    """
    original = _fixture_text("nyc_final_2026-08-21")
    corrected = _fixture_text("nyc_correction_synthetic_2026-08-21")
    retransmitted = _as_rra_retransmission(original)
    correction_uuid = "9f8e7d6c-5b4a-4392-8817-2635a4b5c6d7"
    rra_uuid = "3c2b1a09-8f7e-4d6c-b5a4-93827160fedc"

    transport.discovery_results = [
        _fetch(_discovery_body((NYC_FINAL_UUID, "2026-08-22T06:26:00+00:00"))),
        _fetch(_discovery_body((correction_uuid, "2026-08-22T12:00:00+00:00"))),
        _fetch(_discovery_body((rra_uuid, "2026-08-22T15:00:00+00:00"))),
    ]
    transport.product_results = {
        NYC_FINAL_UUID: [_fetch(_product_body(NYC_FINAL_UUID, original))],
        correction_uuid: [
            _fetch(_product_body(correction_uuid, corrected), at_ns=NOW_NS + 3600 * SECOND_NS)
        ],
        rra_uuid: [
            _fetch(_product_body(rra_uuid, retransmitted), at_ns=NOW_NS + 7200 * SECOND_NS)
        ],
    }
    actor.start()

    await actor.poll_once()
    clock.advance_ns(3600 * SECOND_NS)
    await actor.poll_once()
    clock.advance_ns(3600 * SECOND_NS)
    await actor.poll_once()

    catalog = open_station_catalog(container.catalog_base, VENUE, CITY)
    days = sorted(read_climate_days(catalog), key=lambda record: record.ts_init)

    assert [record.revision_seq for record in days] == [1, 2], (
        "the RRA retransmission must not have been written as a superseding revision"
    )
    assert [record.tmax_f for record in days] == [79, 80]
    assert days[-1].correction_flag is True, "the correction is still the latest record"

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.WRITE_INTEGRITY_VIOLATION


@pytest.mark.asyncio
async def test_an_identical_retransmission_of_a_correction_is_not_an_anomaly(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
    container: SharedIngestState,
    clock: FakeClock,
) -> None:
    """The guard keys on DIFFERING content, not on the BBB token alone.

    A delayed retransmission carrying the SAME settlement values as the stored
    correction reverts nothing, so it must stay an ordinary revision. Blocking
    the site on it would manufacture an outage out of routine NWS behaviour --
    the same reasoning that keeps a sibling station's product from being a gate
    strike.
    """
    corrected = _fixture_text("nyc_correction_synthetic_2026-08-21")
    retransmitted = _as_rra_retransmission(corrected).replace(
        "CLIMATE REPORT...CORRECTED", "CLIMATE REPORT"
    )
    correction_uuid = "9f8e7d6c-5b4a-4392-8817-2635a4b5c6d7"
    rra_uuid = "3c2b1a09-8f7e-4d6c-b5a4-93827160fedc"

    transport.discovery_results = [
        _fetch(_discovery_body((correction_uuid, "2026-08-22T12:00:00+00:00"))),
        _fetch(_discovery_body((rra_uuid, "2026-08-22T15:00:00+00:00"))),
    ]
    transport.product_results = {
        correction_uuid: [_fetch(_product_body(correction_uuid, corrected))],
        rra_uuid: [
            _fetch(_product_body(rra_uuid, retransmitted), at_ns=NOW_NS + 3600 * SECOND_NS)
        ],
    }
    actor.start()

    await actor.poll_once()
    clock.advance_ns(3600 * SECOND_NS)
    await actor.poll_once()

    catalog = open_station_catalog(container.catalog_base, VENUE, CITY)
    days = sorted(read_climate_days(catalog), key=lambda record: record.ts_init)

    assert [record.revision_seq for record in days] == [1, 2]
    assert {record.tmax_f for record in days} == {80}
    assert gate.status(VENUE, CITY).reason is not GateReason.WRITE_INTEGRITY_VIOLATION


def _with_incidental_correction_wording(product_text: str) -> str:
    """Add a remark mentioning a correction to a DIFFERENT day.

    `classify._CORRECTION_RE` scans the WHOLE product body, so any incidental
    "CORRECTED"/"CORRECTION" wording anywhere in the text sets `correction_flag`
    -- including a remark about some other date entirely. That is deliberate and
    correct for an ADVISORY audit-trail flag; it is catastrophic as a
    supersession verdict.
    """
    marker = "T  INDICATES TRACE AMOUNT."
    assert marker in product_text
    return product_text.replace(
        marker,
        marker + "\nTHE PRECIPITATION TOTAL FOR AUGUST 19 WAS CORRECTED IN A LATER PRODUCT.",
    )


@pytest.mark.asyncio
async def test_incidental_correction_wording_may_not_supersede_a_correction(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
    container: SharedIngestState,
    clock: FakeClock,
) -> None:
    """The incoming-side correction test must use the POSITIONAL verdict alone.

    Same arrival order as the `RRA` test -- FINAL 79, genuine `CCA` 80, then a
    delayed `RRA` retransmission of the UNCORRECTED text -- except the
    retransmission also carries a remark about a correction to AUGUST 19. That
    one word flips `correction_flag` to `True` while `is_correction_bbb` stays
    `False`, because the BBB token is still `RRA`.

    Testing the incoming side on `is_correction_bbb OR correction_flag` makes
    that product claim to BE a correction, so the guard returns without raising
    and the stale TMAX 79 is written as revision 3 -- outranking the stored
    correction, with no `record_write_integrity_violation` and no alarm
    anywhere. This is the branch neither existing guard test reached: the `RRA`
    fixture there has `correction_flag=False`, so only the `is_correction_bbb`
    disjunct was ever exercised.

    The asymmetry with condition 1 is deliberate and is documented at the
    condition itself. A broad signal on the STORED side makes the guard engage
    MORE often; the same broad signal on the INCOMING side makes it engage LESS
    often. Same widening, opposite consequence.
    """
    original = _fixture_text("nyc_final_2026-08-21")
    corrected = _fixture_text("nyc_correction_synthetic_2026-08-21")
    adversarial = _with_incidental_correction_wording(_as_rra_retransmission(original))
    correction_uuid = "9f8e7d6c-5b4a-4392-8817-2635a4b5c6d7"
    rra_uuid = "3c2b1a09-8f7e-4d6c-b5a4-93827160fedc"

    transport.discovery_results = [
        _fetch(_discovery_body((NYC_FINAL_UUID, "2026-08-22T06:26:00+00:00"))),
        _fetch(_discovery_body((correction_uuid, "2026-08-22T12:00:00+00:00"))),
        _fetch(_discovery_body((rra_uuid, "2026-08-22T15:00:00+00:00"))),
    ]
    transport.product_results = {
        NYC_FINAL_UUID: [_fetch(_product_body(NYC_FINAL_UUID, original))],
        correction_uuid: [
            _fetch(_product_body(correction_uuid, corrected), at_ns=NOW_NS + 3600 * SECOND_NS)
        ],
        rra_uuid: [
            _fetch(_product_body(rra_uuid, adversarial), at_ns=NOW_NS + 7200 * SECOND_NS)
        ],
    }
    actor.start()

    await actor.poll_once()
    clock.advance_ns(3600 * SECOND_NS)
    await actor.poll_once()
    clock.advance_ns(3600 * SECOND_NS)
    await actor.poll_once()

    catalog = open_station_catalog(container.catalog_base, VENUE, CITY)
    days = sorted(read_climate_days(catalog), key=lambda record: record.ts_init)

    assert [record.revision_seq for record in days] == [1, 2], (
        "a non-correction carrying incidental correction WORDING must not have been "
        "written as a superseding revision"
    )
    assert [record.tmax_f for record in days] == [79, 80]
    assert days[-1].correction_flag is True, "the correction is still the latest record"

    status = gate.status(VENUE, CITY)
    assert status.state is GateState.BLOCKED
    assert status.reason is GateReason.WRITE_INTEGRITY_VIOLATION


def _as_second_correction(product_text: str) -> str:
    """Re-stamp a `CCA` correction as a genuine `CCB` with a further-revised max."""
    assert "CDUS41 KOKX 220626 CCA" in product_text
    assert "  MAXIMUM         80    301 PM" in product_text
    return product_text.replace("CDUS41 KOKX 220626 CCA", "CDUS41 KOKX 220626 CCB").replace(
        "  MAXIMUM         80    301 PM", "  MAXIMUM         81    301 PM"
    )


@pytest.mark.asyncio
async def test_a_genuine_second_correction_supersedes_the_first_cleanly(
    actor: NwsIngestActor,
    gate: SettlementGate,
    transport: TransportDouble,
    container: SharedIngestState,
    clock: FakeClock,
) -> None:
    """`CCB` following `CCA` is a correction and must NOT trip the guard.

    `cli_parse._CORRECTION_BBB_RE` is `^CC[A-Z]$`, so `CCB` is positionally a
    correction. Corrections run CCA, CCB, CCC..., and a SECOND correction to one
    climate day carrying a further-revised value is precisely the case most
    likely to land after settlement -- blocking the site on it would be an
    outage manufactured out of NWS working correctly.

    This is the guard rail on the fix: narrowing the incoming-side test to
    `is_correction_bbb` must not narrow it to "first correction only".
    """
    corrected = _fixture_text("nyc_correction_synthetic_2026-08-21")
    recorrected = _as_second_correction(corrected)
    cca_uuid = "9f8e7d6c-5b4a-4392-8817-2635a4b5c6d7"
    ccb_uuid = "3c2b1a09-8f7e-4d6c-b5a4-93827160fedc"

    transport.discovery_results = [
        _fetch(_discovery_body((cca_uuid, "2026-08-22T12:00:00+00:00"))),
        _fetch(_discovery_body((ccb_uuid, "2026-08-22T15:00:00+00:00"))),
    ]
    transport.product_results = {
        cca_uuid: [_fetch(_product_body(cca_uuid, corrected))],
        ccb_uuid: [
            _fetch(_product_body(ccb_uuid, recorrected), at_ns=NOW_NS + 3600 * SECOND_NS)
        ],
    }
    actor.start()

    await actor.poll_once()
    clock.advance_ns(3600 * SECOND_NS)
    await actor.poll_once()

    catalog = open_station_catalog(container.catalog_base, VENUE, CITY)
    days = sorted(read_climate_days(catalog), key=lambda record: record.ts_init)

    assert [record.revision_seq for record in days] == [1, 2]
    assert [record.tmax_f for record in days] == [80, 81]
    assert gate.status(VENUE, CITY).reason is not GateReason.WRITE_INTEGRITY_VIOLATION


# ---------------------------------------------------------------------------
# DST boundaries -- both clocks, pinned on the transition days themselves
# ---------------------------------------------------------------------------


def _ns(moment: dt.datetime) -> int:
    return int(moment.timestamp()) * SECOND_NS


def test_the_settlement_deadline_follows_dst_across_spring_forward_2026_03_08(
    actor: NwsIngestActor,
    clock: FakeClock,
) -> None:
    """2026-03-08, when America/New_York jumps 02:00 EST -> 03:00 EDT.

    The 08:00 ET settlement deadline is a CIVIL wall-clock time, so it moves an
    hour earlier in UTC across this boundary: 13:00Z on 2026-03-07, 12:00Z from
    2026-03-08 onwards. `_deadline_ns` gets that from `ZoneInfo`; a fixed -5
    offset -- the value the CLIMATE-DAY window legitimately uses -- would not.

    The instant is chosen so the two answers diverge in the DAY as well as the
    hour, rather than being merely an hour apart: at 12:30Z the DST-aware
    deadline for 2026-03-07 has already passed (12:00Z) and the pending day rolls
    forward, while a fixed-offset deadline (13:00Z) would still be in the future
    and the pending day would not roll.
    """
    # The day BEFORE the transition: still EST, so 08:00 ET is 13:00Z.
    clock.now = _ns(dt.datetime(2026, 3, 7, 12, 30, tzinfo=dt.UTC))
    assert actor.pending_final_deadline() == (
        dt.date(2026, 3, 6),
        _ns(dt.datetime(2026, 3, 7, 13, 0, tzinfo=dt.UTC)),
    )

    # The transition day itself: EDT, so 08:00 ET is 12:00Z.
    clock.now = _ns(dt.datetime(2026, 3, 8, 12, 30, tzinfo=dt.UTC))
    assert actor.pending_final_deadline() == (
        dt.date(2026, 3, 8),
        _ns(dt.datetime(2026, 3, 9, 12, 0, tzinfo=dt.UTC)),
    ), "a fixed -5 deadline would answer (2026-03-07, 2026-03-08T13:00Z) here"


def test_the_settlement_deadline_follows_dst_across_fall_back_2026_11_01(
    actor: NwsIngestActor,
    clock: FakeClock,
) -> None:
    """2026-11-01, when America/New_York falls back 02:00 EDT -> 01:00 EST.

    The mirror image: 08:00 ET is 12:00Z on 2026-10-31 and 13:00Z from
    2026-11-01. At 12:30Z on the transition day the DST-aware deadline
    (13:00Z) has NOT passed, so the pending day stays 2026-10-31 -- whereas a
    deadline frozen at the previous day's -4 offset would have passed at 12:00Z
    and rolled the pending day forward a day early, retiring the settlement
    watchdog for 2026-10-31 while its final was still outstanding.
    """
    # The day BEFORE the transition: still EDT, so 08:00 ET is 12:00Z.
    clock.now = _ns(dt.datetime(2026, 10, 31, 11, 30, tzinfo=dt.UTC))
    assert actor.pending_final_deadline() == (
        dt.date(2026, 10, 30),
        _ns(dt.datetime(2026, 10, 31, 12, 0, tzinfo=dt.UTC)),
    )

    # The transition day itself: EST, so 08:00 ET is 13:00Z.
    clock.now = _ns(dt.datetime(2026, 11, 1, 12, 30, tzinfo=dt.UTC))
    assert actor.pending_final_deadline() == (
        dt.date(2026, 10, 31),
        _ns(dt.datetime(2026, 11, 1, 13, 0, tzinfo=dt.UTC)),
    ), "a fixed -4 deadline would have rolled the pending day forward a day early"


@pytest.mark.parametrize(
    ("now", "expected_day"),
    [
        # Spring forward. The climate day is local-STANDARD midnight to midnight
        # (-5 for NYC) all year, so the pending day is derived from -5 on BOTH
        # sides of the transition -- never from the -4 civil clock in force.
        (dt.datetime(2026, 3, 8, 12, 30, tzinfo=dt.UTC), dt.date(2026, 3, 8)),
        (dt.datetime(2026, 3, 9, 12, 30, tzinfo=dt.UTC), dt.date(2026, 3, 9)),
        # Fall back.
        (dt.datetime(2026, 10, 31, 11, 30, tzinfo=dt.UTC), dt.date(2026, 10, 30)),
        (dt.datetime(2026, 11, 1, 12, 30, tzinfo=dt.UTC), dt.date(2026, 10, 31)),
    ],
)
def test_the_climate_day_window_stays_on_standard_time_across_both_transitions(
    actor: NwsIngestActor,
    clock: FakeClock,
    registry: SiteRegistry,
    now: dt.datetime,
    expected_day: dt.date,
) -> None:
    """The OTHER half of the two-clock split, pinned on the transition days.

    `pending_final_deadline` derives the climate day from
    `ClimateDayWindow.std_utc_offset_hours` -- a FIXED offset, never DST-aware --
    and only the deadline instant from `ZoneInfo`.

    **Honest scope, measured rather than assumed.** Substituting the DST-aware
    civil offset for the fixed one changes NOTHING about what this method
    returns, at any instant of 2026 (checked at 10-minute resolution). The reason
    is the one-step advance below the derivation: whenever the two offsets put
    the station on different dates -- only the 04:00-05:00Z hour, and only under
    EDT -- the candidate whose deadline has already passed rolls forward onto the
    same answer. So the method self-corrects, and this half CANNOT be pinned
    discriminatingly here.

    It is pinned as a regression value instead, plus two assertions that do
    discriminate: the registry offset itself does not move at either transition,
    and the derived day equals the fixed-offset arithmetic exactly. The place the
    fixed offset genuinely bites is a record's `ts_event`
    (`records._climate_day_end_ns`), covered by
    `test_a_final_stamps_ts_event_from_the_fixed_standard_offset` below.
    """
    window = registry.climate_day_window(VENUE, CITY)
    assert window.std_utc_offset_hours == -5.0, "the climate-day offset is never DST-aware"

    clock.now = _ns(now)
    day, deadline_ns = actor.pending_final_deadline()
    assert day == expected_day
    assert deadline_ns > clock(), "the pending deadline is always in the future"

    station_now = now + dt.timedelta(hours=window.std_utc_offset_hours)
    expected_from_fixed_offset = station_now.date() - dt.timedelta(days=1)
    assert day in (expected_from_fixed_offset, expected_from_fixed_offset + dt.timedelta(days=1))


@pytest.mark.asyncio
async def test_a_final_stamps_ts_event_from_the_fixed_standard_offset(
    actor: NwsIngestActor,
    transport: TransportDouble,
    container: SharedIngestState,
) -> None:
    """Where the fixed standard offset actually bites, and discriminates.

    A final's `ts_event` is the climate day's END in local STANDARD time. The
    NYC final fixture covers 2026-08-21 -- a date under EDT -- so a DST-aware
    derivation would stamp 2026-08-22T04:00Z while the correct standard-time
    answer is 05:00Z. One hour, on the field that orders settlement joins.
    """
    _script_healthy_final_poll(transport)
    actor.start()

    await actor.poll_once()

    catalog = open_station_catalog(container.catalog_base, VENUE, CITY)
    (day,) = read_climate_days(catalog)
    assert day.climate_day == dt.date(2026, 8, 21)
    assert day.ts_event == _ns(dt.datetime(2026, 8, 22, 5, 0, tzinfo=dt.UTC)), (
        "climate-day end is local STANDARD midnight (-5), not the -4 EDT clock in force"
    )


@pytest.mark.parametrize("venue,city", ALL_SITES)
def test_every_settlement_time_sits_outside_the_dst_ambiguous_window(
    registry: SiteRegistry,
    venue: str,
    city: str,
) -> None:
    """`_deadline_ns` builds the instant with a bare
    `datetime.combine(..., tzinfo=ZoneInfo(...))` and never sets `fold`.

    That is correct ONLY while the configured local time sits outside the
    01:00-03:00 transition window. Inside it, `combine` silently produces either
    a NON-EXISTENT local time (spring forward: 2026-03-08 02:30 America/New_York
    resolves to 07:30Z, an instant at which the local clock reads 03:30, not
    02:30) or an AMBIGUOUS one (fall back: 2026-11-01 01:30 resolves to 05:30Z
    with the default `fold=0` and 06:30Z with `fold=1` -- an hour of settlement
    deadline decided by a keyword nobody passed).

    Today's values are 08:00 and 11:00 ET, comfortably outside. Nothing asserted
    that, so a registry edit could move a deadline into the fold and the failure
    would surface once a year, on a settlement morning. This is the assertion.
    """
    zone = ZoneInfo("America/New_York")
    # Demonstrate the hazard on the real transition dates, so this test fails if
    # the platform's own tz behaviour ever stops matching the premise.
    assert dt.datetime(2026, 3, 8, 2, 30, tzinfo=zone).astimezone(dt.UTC) == dt.datetime(
        2026, 3, 8, 7, 30, tzinfo=dt.UTC
    )
    assert dt.datetime(2026, 11, 1, 1, 30, tzinfo=zone).astimezone(dt.UTC) != dt.datetime(
        2026, 11, 1, 1, 30, fold=1, tzinfo=zone
    ).astimezone(dt.UTC)

    deadline = registry.settlement_deadline(venue, city)
    for label, value in (
        ("settlement_time_local", deadline.settlement_time_local),
        ("settlement_delay_time_local", deadline.settlement_delay_time_local),
    ):
        local = dt.time.fromisoformat(value)
        assert not (dt.time(1, 0) <= local < dt.time(3, 0)), (
            f"{venue}/{city} {label}={value} sits inside the 01:00-03:00 DST "
            "transition window, where `datetime.combine` is ambiguous on fall-back "
            "and non-existent on spring-forward"
        )
