"""WI-9 -- restart/resume proven across a real build/start/stop/build cycle.

`tests/integration/test_runtime_lifecycle_smoke.py` proves the composition
root releases its OWN resources (the process slot and the sqlite handle)
across a restart, and its docstring names this module as the follow-on that
proves DOMAIN state survives one. That is what these tests do.

What "survives" means here is deliberately narrow and deliberately harsh:
**a value is durable only if a SECOND, INDEPENDENT handle on the backing
medium can read it back after the writer is gone.** Every assertion below
therefore reads `runtime.store` -- and after a restart, a *different*
`SqliteStateStore` instance opened by a *different* `ingest_runtime` over
the same file -- never the Actor's in-process attribute. An in-memory-only
write cannot satisfy that, which is exactly the point: against the code
these tests were written for, the resume cursor and the conditional-GET
validators lived in the NautilusTrader `Cache`, which this deployment
configures with `database=None` (`runtime/node_config.py:150` ->
`system/kernel.py:310-311` -> `cache/cache.pyx:298`), i.e. a plain dict that
dies with the process.

Falsifiability, stated as a contract rather than a hope
------------------------------------------------------
A durability test that only ever observes `None` proves nothing. Each test
here carries a POSITIVE CONTROL: it asserts the store key is absent before
the poll and present after it, so the assertion cannot pass vacuously. If
`_save_cursor` were deleted outright, `test_resume_cursor_survives_a_full_
teardown_and_rebuild` fails on the `is not None` line, and
`test_cursor_is_durable_at_the_moment_of_a_kill_between_persist_and_publish`
fails on its pre-kill capture -- neither degrades into a silent pass.

Thread confinement is part of the claim, not a detail
----------------------------------------------------
Moving the cursor off `Cache` puts it behind `SqliteStateStore`, which is
THREAD-CONFINED (`runtime/sqlite_store.py:71-79`). `poll_once` and
`warm_start` both hand real work to a `ThreadPoolExecutor`, so a cursor or
validator touch that drifted inside one of those callables would raise in
a real process and never in a store-stubbing unit test.
`test_no_cursor_or_validator_touch_ever_leaves_the_loop_thread` pins that,
and carries a negative control so a green run is evidence of correct call
placement rather than of a blind detector.

Zero network I/O
----------------
`respx` intercepts `httpx` at the transport layer (the house pattern from
`tests/unit/test_ingest_nws_actor.py`), and `tests/conftest.py` blocks real
sockets outright as a second, independent mechanism. No wall-clock date is
read: the nanosecond clock is `FakeClock`, whose origin is derived from the
NYC fixture's own `meta.json` instant, never `time.time_ns()` and never
`date.today()`.

Seams reused rather than reinvented (task constraint): `RecordingNode` /
`local_probe` from the lifecycle smoke test, and `FakeClock` /
`mock_discovery` / `mock_product` / the fixture constants from the unit
suite -- the same re-export route `tests/contract/conftest.py` already uses.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.nws_raw_product import NwsRawProduct
from breezy.ingest.gate import GateReason
from breezy.ingest.nws_actor import (
    CURSOR_KEY_PREFIX,
    VALIDATORS_KEY_PREFIX,
    Cursor,
    NwsIngestActor,
)
from breezy.persistence.catalog import (
    open_station_catalog,
    read_climate_days,
    read_raw_products,
)
from breezy.runtime.composition import BreezyIngestRuntime, build_ingest_node, ingest_runtime
from breezy.runtime.settings import BreezyRuntimeSettings
from breezy.runtime.sqlite_store import SqliteStateStore
from tests.integration.test_runtime_lifecycle_smoke import RecordingNode, local_probe
from tests.unit.test_ingest_nws_actor import (
    CITY,
    DISCOVERY_URL,
    NYC_FINAL,
    NYC_PRELIM,
    SECOND,
    VENUE,
    FakeClock,
    load_meta,
    mock_discovery,
    mock_product,
)

CURSOR_KEY = f"{CURSOR_KEY_PREFIX}{VENUE}:{CITY}"
VALIDATORS_KEY = f"{VALIDATORS_KEY_PREFIX}{VENUE}:{CITY}"


# ---------------------------------------------------------------------------
# One process lifetime
# ---------------------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: Path) -> BreezyRuntimeSettings:
    return BreezyRuntimeSettings(
        trader_id="BREEZY-001",
        sites=((VENUE, CITY),),
        catalog_base=tmp_path / "nws",
        state_db_path=tmp_path / "state" / "breezy-state.sqlite3",
        poll_interval_seconds=300,
        parse_timeout_ms=5000,
        log_level="INFO",
        check_proxy_env=False,
        registry_path=None,
    )


def _register(actor: NwsIngestActor) -> NwsIngestActor:
    """Complete the Nautilus system wiring `Trader.add_actor` would do.

    The cache here is a REAL `nautilus_trader` `Cache`, configured exactly as
    the deployment configures it (`database=None`, i.e. a plain dict). That is
    deliberate and it stays: it is the standing proof that nothing on the
    resume path has quietly drifted back onto `Cache`. Substituting a fake
    that happens to persist would assume the conclusion; a `Cache` that really
    is memory-only means every assertion below can only be satisfied by
    `runtime.store`.
    """
    from nautilus_trader.common.component import TestClock
    from nautilus_trader.test_kit.stubs.component import TestComponentStubs

    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=TestClock(),
    )
    published: list[tuple[Any, Any]] = []
    actor.publish_data = lambda data_type, data: published.append(
        (data_type, data)
    )
    actor.published = published
    return actor


@contextmanager
def process_cycle(
    settings: BreezyRuntimeSettings,
    clock: FakeClock,
    *,
    store_factory: Callable[[Path], Any] = SqliteStateStore,
) -> Iterator[tuple[BreezyIngestRuntime, NwsIngestActor]]:
    """Model ONE process lifetime over `settings`'s paths.

    Entering opens a fresh `SqliteStateStore` on the same file and claims the
    process-wide slot; leaving runs `ExitStack` teardown -- `shared.dispose()`
    then `store.close()` (`composition.py`) -- releasing both. A second entry
    therefore reads through a genuinely different sqlite connection, which is
    what makes "the value survived" a statement about the file rather than
    about a Python object.
    """
    with ingest_runtime(
        settings, clock=clock, probe=local_probe, store_factory=store_factory
    ) as runtime:
        node = build_ingest_node(runtime, node_factory=RecordingNode)
        (actor,) = node.trader.added_actors
        assert isinstance(actor, NwsIngestActor)
        _register(actor)
        try:
            yield runtime, actor
        finally:
            actor.on_stop()
            actor.shutdown_executor()


async def start_and_settle(actor: NwsIngestActor) -> None:
    """`on_start()` and then wait for the warm start it submits to finish.

    `on_start` fires `self._submit(self.warm_start())` -- scheduled onto the
    loop, not awaited -- and `warm_start` itself awaits catalog reads on the
    worker pool. Sleeping a fixed interval would be a race; wrapping the
    coroutine in an `Event` is exact, and touches no private attribute.
    """
    done = asyncio.Event()
    original = actor.warm_start

    async def wrapped() -> None:
        try:
            await original()
        finally:
            done.set()

    actor.warm_start = wrapped  # type: ignore[method-assign]
    try:
        actor.on_start()
        await asyncio.wait_for(done.wait(), timeout=10)
    finally:
        actor.warm_start = original  # type: ignore[method-assign]


def decode_cursor(raw: bytes | None) -> Cursor | None:
    if not raw:
        return None
    payload = json.loads(raw.decode("utf-8"))
    return (int(payload[0]), str(payload[1]), str(payload[2]))


def catalog_state(settings: BreezyRuntimeSettings) -> tuple[set[str], int]:
    """Every persisted product uuid, and the total record count."""
    catalog = open_station_catalog(settings.catalog_base, VENUE, CITY)
    raws = read_raw_products(catalog)
    days = read_climate_days(catalog)
    return {r.product_uuid for r in raws}, len(raws) + len(days)


def fixture_uuid(dirname: str) -> str:
    return str(load_meta(dirname)["product_id"])


class _Killed(Exception):
    """Sentinel raised by the injected write seam to abort a poll after the
    durable catalog write and before any publication."""


# ---------------------------------------------------------------------------
# A1/A2/A3 -- the cursor itself
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resume_cursor_survives_a_full_teardown_and_rebuild(
    settings: BreezyRuntimeSettings,
) -> None:
    """The headline claim: after a clean stop and a fresh process over the
    same paths, the resume cursor reads back as the SAME tuple.

    Three assertions, in order of strength:

    * **A1** -- `store.get(CURSOR_KEY)` is non-`None` after the poll, having
      been `None` before it (the positive control that makes this test
      falsifiable).
    * **A2** -- a fresh runtime's Actor loads that identical cursor through a
      brand-new sqlite connection.
    * **A3** -- warm start on the fresh Actor republishes NOTHING, because the
      cursor is already at the head. Without a durable cursor this republishes
      the entire retained station catalog on every restart.
    """
    clock = FakeClock()

    with process_cycle(settings, clock) as (runtime, actor):
        # Positive control: the key genuinely starts absent, so a later
        # `is not None` cannot pass vacuously.
        assert runtime.store.get(CURSOR_KEY) is None

        await start_and_settle(actor)
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            mock_product(mock, NYC_FINAL)
            await actor.poll_once()

        assert actor.published, "the poll must publish, or there is no cursor to test"
        in_process = actor.resume_cursor
        assert in_process is not None

        # A1 -- the durable medium, not the Actor attribute.
        durable = runtime.store.get(CURSOR_KEY)
        assert durable is not None
        assert decode_cursor(durable) == in_process

    # A second `ingest_runtime` over the same paths: new process slot, new
    # sqlite connection, new Actor, no shared Python object with the above.
    with process_cycle(settings, clock) as (runtime2, actor2):
        # A2 -- read back through the fresh handle, before anything else runs.
        assert decode_cursor(runtime2.store.get(CURSOR_KEY)) == in_process
        assert actor2.resume_cursor == in_process

        # A3 -- nothing to replay.
        await start_and_settle(actor2)
        assert actor2.published == []


# ---------------------------------------------------------------------------
# Kill between persist and publish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cursor_is_durable_at_the_moment_of_a_kill_between_persist_and_publish(
    settings: BreezyRuntimeSettings,
) -> None:
    """Assert durability AT THE KILL, and fail if the write never happened.

    Sequence:

    1. A clean poll ingests the NYC FINAL and advances the cursor. The
       durable cursor is captured **before** the kill -- this capture is the
       falsifiability condition: remove `_save_cursor` and this line fails.
    2. A second poll ingests the PRELIMINARY with `write_records` (the
       Actor's documented injectable seam) substituted for a wrapper that
       performs the REAL write and then raises. The poll therefore dies
       strictly between a durable catalog write and any publication.
    3. Nothing from poll 2 was published, its records ARE on disk, and the
       durable cursor still holds poll 1's value -- unmoved, not lost.
    4. After a full restart, warm start republishes EXACTLY the
       persisted-but-unpublished records and nothing else.

    Note on fidelity: raising out of the write seam is routed by
    `route_catalog_error` and hard-blocks the site, which a real SIGKILL
    would not do. That is strictly HARSHER than the scenario, and none of
    the assertions below read the gate -- they read the store and the
    catalog.
    """
    clock = FakeClock()
    prelim_uuid = fixture_uuid(NYC_PRELIM)

    with process_cycle(settings, clock) as (runtime, actor):
        await start_and_settle(actor)
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            mock_product(mock, NYC_FINAL)
            await actor.poll_once()

        published_before_kill = list(actor.published)
        assert published_before_kill
        cursor_at_kill = runtime.store.get(CURSOR_KEY)
        assert cursor_at_kill is not None, (
            "the cursor must be durable BEFORE the kill; if it is absent here "
            "the kill scenario below proves nothing"
        )

        real_write = actor.write_records

        def write_then_die(catalog: Any, records: Any) -> Any:
            real_write(catalog, records)
            raise _Killed("process killed after the durable write, before publish")

        actor.write_records = write_then_die
        clock.advance(300 * SECOND)
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_PRELIM)
            mock_product(mock, NYC_PRELIM)
            await actor.poll_once()

        # The write really happened...
        uuids, _ = catalog_state(settings)
        assert prelim_uuid in uuids
        # ...and nothing from it reached a subscriber.
        assert list(actor.published) == published_before_kill
        # ...and the cursor is exactly where poll 1 left it: durable, unmoved.
        assert runtime.store.get(CURSOR_KEY) == cursor_at_kill

    with process_cycle(settings, clock) as (runtime2, actor2):
        assert runtime2.store.get(CURSOR_KEY) == cursor_at_kill
        await start_and_settle(actor2)

        replayed = [payload for _, payload in actor2.published]
        # Exactly the two records the killed poll persisted, and nothing that
        # poll 1 already published. `NwsClimateDay` carries no `product_uuid`
        # -- the two types are joined by `raw_sha256` (`nws_raw_product.py:51`)
        # -- so identify the raw product by uuid and the climate day by the
        # digest it shares with it.
        assert len(replayed) == 2, "one NwsRawProduct and one NwsClimateDay"
        (raw,) = [r for r in replayed if isinstance(r, NwsRawProduct)]
        (day,) = [r for r in replayed if isinstance(r, NwsClimateDay)]
        assert raw.product_uuid == prelim_uuid, (
            "warm start must republish exactly the persisted-but-unpublished records"
        )
        assert day.raw_sha256 == raw.raw_sha256


# ---------------------------------------------------------------------------
# A4/A6 -- re-polling after a restart
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_repolling_the_same_products_after_a_restart_is_a_clean_no_op(
    settings: BreezyRuntimeSettings,
) -> None:
    """Restart, then offer the discovery list again unchanged.

    No duplicate record, no `WRITE_INTEGRITY_VIOLATION`, no product re-fetch
    (the durable product index still dedupes), and no republication (the
    durable cursor still guards the publish path).
    """
    clock = FakeClock()

    with process_cycle(settings, clock) as (_runtime, actor):
        await start_and_settle(actor)
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            mock_product(mock, NYC_FINAL)
            await actor.poll_once()
    before = catalog_state(settings)

    with process_cycle(settings, clock) as (runtime2, actor2):
        await start_and_settle(actor2)
        # The restart itself republished nothing: without a durable cursor the
        # warm start would replay the whole retained catalog here. Asserted
        # BEFORE the clear, so the clear cannot hide it.
        assert actor2.published == [], (
            "warm start after a restart must not replay already-published records"
        )
        actor2.published.clear()
        clock.advance(300 * SECOND)
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            product_route = mock_product(mock, NYC_FINAL)
            await actor2.poll_once()

        assert product_route.call_count == 0, "the durable product index must still dedupe"
        assert catalog_state(settings) == before
        assert (
            GateReason.WRITE_INTEGRITY_VIOLATION
            not in runtime2.shared.gate.blocking_causes(VENUE, CITY)
        )
        assert actor2.published == []


# ---------------------------------------------------------------------------
# The conditional-GET validators
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_conditional_get_validators_survive_a_restart(
    settings: BreezyRuntimeSettings,
) -> None:
    """A restart must not silently downgrade the next poll to an
    unconditional GET.

    Extra load under ONE User-Agent is the documented path into the
    api.weather.gov abuse trap, and a restart loop is precisely when it is
    repeated. Positive control included: the validators key is absent before
    the first poll.
    """
    clock = FakeClock()
    etag = '"abc123"'
    last_modified = "Sat, 22 Aug 2026 06:30:00 GMT"

    with process_cycle(settings, clock) as (runtime, actor):
        assert runtime.store.get(VALIDATORS_KEY) is None
        await start_and_settle(actor)
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(
                mock,
                NYC_FINAL,
                headers={"ETag": etag, "Last-Modified": last_modified},
            )
            mock_product(mock, NYC_FINAL)
            await actor.poll_once()
        assert runtime.store.get(VALIDATORS_KEY) is not None

    with process_cycle(settings, clock) as (_runtime2, actor2):
        await start_and_settle(actor2)
        clock.advance(300 * SECOND)
        with respx.mock(assert_all_called=False) as mock:
            route = mock.get(DISCOVERY_URL).mock(return_value=httpx.Response(304))
            await actor2.poll_once()

        sent = route.calls[0].request
        assert sent.headers["if-none-match"] == etag
        assert sent.headers["if-modified-since"] == last_modified


@pytest.mark.asyncio
async def test_a_304_that_omits_its_etag_does_not_erase_the_durable_one(
    settings: BreezyRuntimeSettings,
) -> None:
    """`_store_validators`' preservation rule, asserted on the DURABLE value.

    A 304 that omits the `ETag` it was validated against must not blank the
    stored one, or the poll after it silently becomes unconditional. Pinned
    here against the store so the move off `Cache` cannot drop the rule.
    """
    clock = FakeClock()
    etag = '"abc123"'

    with process_cycle(settings, clock) as (runtime, actor):
        await start_and_settle(actor)
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL, headers={"ETag": etag})
            mock_product(mock, NYC_FINAL)
            await actor.poll_once()
        after_first = runtime.store.get(VALIDATORS_KEY)
        assert after_first is not None
        assert json.loads(after_first.decode("utf-8"))["etag"] == etag

        clock.advance(300 * SECOND)
        with respx.mock(assert_all_called=False) as mock:
            mock.get(DISCOVERY_URL).mock(
                return_value=httpx.Response(
                    304, headers={"Last-Modified": "Sat, 22 Aug 2026 07:00:00 GMT"}
                )
            )
            await actor.poll_once()

        preserved = runtime.store.get(VALIDATORS_KEY)
        assert preserved is not None
        assert json.loads(preserved.decode("utf-8"))["etag"] == etag


@pytest.mark.asyncio
async def test_reset_cursor_survives_a_restart_as_absent(
    settings: BreezyRuntimeSettings,
) -> None:
    """Replay repair is an operational tool, and it must stick.

    `reset_cursor` writes a `b""` sentinel; `_load_cursor` treats falsy bytes
    as absent. Rewinding in memory only would silently un-rewind on the next
    process -- the operator would run the repair, restart, and get no replay.
    """
    clock = FakeClock()

    with process_cycle(settings, clock) as (runtime, actor):
        await start_and_settle(actor)
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            mock_product(mock, NYC_FINAL)
            await actor.poll_once()
        assert actor.resume_cursor is not None
        actor.reset_cursor()
        assert runtime.store.get(CURSOR_KEY) == b""

    with process_cycle(settings, clock) as (_runtime2, actor2):
        assert actor2.resume_cursor is None
        await start_and_settle(actor2)
        # The rewind really took effect: everything on disk replays.
        assert len(actor2.published) == 2


# ---------------------------------------------------------------------------
# Thread confinement -- the failure that only shows up in a real process
# ---------------------------------------------------------------------------


class ThreadRecordingStore:
    """A real `SqliteStateStore` that records the thread of every access.

    The recording happens BEFORE delegating, so an off-thread touch is
    captured even though the inner store then raises. That is the whole
    point: without it a confinement breach surfaces as an opaque
    `RuntimeError` from somewhere inside a `run_in_executor` callable, and
    only in a real deployment -- a naive unit test that stubs the store, or
    that constructs it on the same thread it polls from, never sees it.
    """

    def __init__(self, path: Path, touches: list[tuple[str, str, int]]) -> None:
        self._inner = SqliteStateStore(path)
        self.touches = touches

    def get(self, key: str) -> bytes | None:
        self.touches.append(("get", key, threading.get_ident()))
        return self._inner.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.touches.append(("set", key, threading.get_ident()))
        self._inner.set(key, value)

    def close(self) -> None:
        self._inner.close()


@pytest.mark.asyncio
async def test_no_cursor_or_validator_touch_ever_leaves_the_loop_thread(
    settings: BreezyRuntimeSettings,
) -> None:
    """SS4.1: moving the cursor onto `SqliteStateStore` puts it behind a
    THREAD-CONFINED resource, and this poll runs real executor work.

    `poll_once` hands catalog I/O to a `ThreadPoolExecutor` via
    `_run_off_loop`, and `warm_start` reads the whole station catalog the
    same way. A `_save_cursor` or `_store_validators` call that drifted
    inside one of those callables -- or a `resume_cursor` read used as a
    sort key there -- would raise `RuntimeError` in production and never in
    a test that stubs the store.

    Three assertions, and the third is what makes the first two mean
    something:

    * every recorded touch is on the loop thread;
    * the cursor and validator keys really were touched (positive control --
      otherwise "no off-thread touch" is satisfied by touching nothing);
    * the detector is DEMONSTRABLY capable of catching a breach, shown by
      driving one deliberately through the same executor seam.
    """
    clock = FakeClock()
    touches: list[tuple[str, str, int]] = []

    def factory(path: Path) -> ThreadRecordingStore:
        return ThreadRecordingStore(path, touches)

    loop_thread = threading.get_ident()

    with process_cycle(settings, clock, store_factory=factory) as (runtime, actor):
        await start_and_settle(actor)
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL, headers={"ETag": '"abc123"'})
            mock_product(mock, NYC_FINAL)
            await actor.poll_once()

        assert actor.published, "no publish means no cursor write to police"
        touched_keys = {key for _, key, _ in touches}
        assert CURSOR_KEY in touched_keys
        assert VALIDATORS_KEY in touched_keys

        off_thread = [t for t in touches if t[2] != loop_thread]
        assert off_thread == [], (
            f"the durable store was touched off the loop thread: {off_thread}"
        )

        # Negative control. The same store, reached through the same
        # `_run_off_loop` seam the poll uses, is both RECORDED off-thread and
        # REJECTED by the store itself -- so a green run above is evidence of
        # correct call placement, not of a blind detector.
        mark = len(touches)
        with pytest.raises(RuntimeError, match="different thread"):
            await actor._run_off_loop(lambda: runtime.store.get(CURSOR_KEY))
        assert [t[2] for t in touches[mark:]] == [
            t[2] for t in touches[mark:] if t[2] != loop_thread
        ]
        assert touches[mark:], "the negative control recorded nothing"
