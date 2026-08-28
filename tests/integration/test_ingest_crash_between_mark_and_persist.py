"""The durable "seen" mark must be contingent on a CONFIRMED catalog persist.

The window under test
--------------------
``poll_once`` runs the SS3.4 Job 2 integrity tripwire (step 8) and then the
catalog write (steps 9-11). The tripwire's recorder,
``ProductIntegrityIndex.observe``, writes the ``product_uuid`` **durably** --
manifest key first, entry key second (``ingest/product_index.py``). The
discovery-time dedupe of SS3.4 Job 1 (``_undeduped``) then answers "have I
already ingested this?" from that same durable index.

So a process that dies -- or a catalog write that fails -- *after* the mark and
*before* the write leaves a state that is silently, permanently wrong: the uuid
reads as already-seen forever, the product is never re-fetched, and it is absent
from the catalog. No gate reason fires on the next poll, because from the
Actor's point of view nothing is outstanding. That is the exploitable shape of a
lost NWS **correction**: a corrected final marked seen an instant before the
crash settles a position on the superseded temperature, with no alert.

The safe failure direction
--------------------------
The two orderings fail in opposite directions, and they are not symmetric:

* mark-then-write (the defect) loses the product **permanently and silently**;
* write-then-mark loses only the mark, so the next poll re-fetches and
  re-persists a product that may already be on disk.

The second is recoverable and the first is not, so the second is the correct
bias. It is worth being precise about what "recoverable" means here, because it
is NOT catalog-level idempotency: ``persistence/catalog.py`` is append-only and
does not dedupe by ``product_uuid`` (``write_records``, ``catalog.py:422``;
``NwsClimateDay`` carries no uuid at all). ``ProductIntegrityIndex.observe`` IS
idempotent -- first-write-wins, a second observation of an identical digest is a
read-only MATCH (``product_index.py``, ``observe``). What makes the re-persist
safe is that ``_persist_batch`` nudges a colliding ``retrieved_at_ns`` strictly
past the catalog's current maximum ``ts_init`` (WI-11), so the re-write appends
a later revision of identical content rather than tripping the exact-range
rewrite that ``write_records`` reports as ``skipped`` (CRIT, hard-block).
Supersession resolves by ``(is_final, ts_init, revision_seq)``, so that later
revision carries the same readings and settlement is unchanged.

Falsifiability
--------------
Both tests carry controls that make a vacuous pass impossible:

* the headline test asserts the crashed poll really did fetch the product and
  really did leave the catalog empty, before it asserts anything about the
  restart;
* :func:`test_a_clean_poll_still_dedupes_across_a_restart` is the negative
  control for the fix itself. "Never mark the uuid" would satisfy the headline
  test and re-fetch every product forever; that test fails on it, and it asserts
  the durable index key directly rather than inferring it from behaviour.

Zero network I/O: ``respx`` intercepts ``httpx`` at the transport layer, and
``tests/conftest.py`` blocks real sockets as an independent second mechanism.
The nanosecond clock is ``FakeClock``.

Seams are reused, not reinvented: ``process_cycle`` / ``start_and_settle`` /
``catalog_state`` / ``fixture_uuid`` come from
``tests/integration/test_runtime_restart_resume.py``, and the fixture constants
and ``respx`` helpers from ``tests/unit/test_ingest_nws_actor.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest
import respx

from breezy.ingest.gate import GateReason
from breezy.ingest.product_index import PRODUCT_INDEX_KEY_PREFIX
from breezy.runtime.settings import BreezyRuntimeSettings
from tests.integration.test_runtime_restart_resume import (
    catalog_state,
    fixture_uuid,
    process_cycle,
    settings,  # noqa: F401 -- re-exported pytest fixture
    start_and_settle,
)
from tests.unit.test_ingest_nws_actor import (
    CITY,
    NYC_FINAL,
    SECOND,
    VENUE,
    FakeClock,
    mock_discovery,
    mock_product,
)

POLL_INTERVAL_NS = 300 * SECOND


class _DiedBeforeTheWrite(Exception):
    """Injected at the ``write_records`` seam to abort a poll at the persist
    step with **nothing** durable in the catalog.

    This models the crash window truthfully in the direction that matters: the
    tripwire has already run, and the catalog never received the batch. It is
    strictly harsher than a real SIGKILL in one respect -- the exception is
    routed by ``route_catalog_error`` and hard-blocks the site -- and that is
    deliberately irrelevant to the claim: a write-integrity block does not stop
    the next poll, because ``network_allowed`` gates only on the global UA-trap
    latch and the in-process backoff window (``nws_actor.py``,
    ``network_allowed``), neither of which survives the restart.
    """


def _die_before_writing(_catalog: Any, _records: Sequence[Any]) -> Any:
    raise _DiedBeforeTheWrite("process died at the persist step, before any durable write")


def _index_key(product_uuid: str) -> str:
    return f"{PRODUCT_INDEX_KEY_PREFIX}{product_uuid}"


@pytest.mark.asyncio
async def test_a_crash_at_the_persist_step_leaves_the_product_refetchable(
    settings: BreezyRuntimeSettings,  # noqa: F811 -- the imported fixture
) -> None:
    """The headline claim: a product marked "seen" but never persisted must be
    re-fetched and must land in the catalog after a restart.

    Sequence:

    1. A poll fetches the NYC FINAL and dies at the persist step. Controls: the
       product WAS fetched, and the catalog is empty afterwards -- so the
       scenario really is "seen, not persisted" and not something weaker.
    2. A full restart over the same paths: new sqlite connection, new Actor, no
       shared Python object.
    3. The same discovery list is offered again. The product must be re-fetched
       and must be durable in the catalog.

    Against mark-then-write this fails at step 3 with ``call_count == 0``: the
    durable index dedupes the uuid away in ``_undeduped`` before the product
    fetch is ever attempted, and the product is lost permanently.
    """
    clock = FakeClock()
    final_uuid = fixture_uuid(NYC_FINAL)

    with process_cycle(settings, clock) as (_runtime, actor):
        await start_and_settle(actor)
        actor.write_records = _die_before_writing
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            crashed_route = mock_product(mock, NYC_FINAL)
            await actor.poll_once()

        # Control A: the poll really got as far as the product fetch, so the
        # tripwire really did run on this uuid.
        assert crashed_route.call_count == 1, (
            "the crashed poll must have fetched the product, or the scenario "
            "never reached the integrity mark and proves nothing"
        )
        # Control B: nothing reached the catalog. The product exists nowhere
        # durable at this instant.
        uuids, record_count = catalog_state(settings)
        assert final_uuid not in uuids
        assert record_count == 0, "the crash must leave the catalog untouched"
        assert actor.published == []

    with process_cycle(settings, clock) as (_runtime2, actor2):
        await start_and_settle(actor2)
        clock.advance(POLL_INTERVAL_NS)
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            retry_route = mock_product(mock, NYC_FINAL)
            await actor2.poll_once()

        assert retry_route.call_count == 1, (
            "a product that was marked seen but never persisted must be "
            "re-fetched after a restart -- the durable mark may only be set "
            "once the catalog write is confirmed"
        )
        uuids2, record_count2 = catalog_state(settings)
        assert final_uuid in uuids2, (
            "the re-fetched product must be durable in the catalog; if it is "
            "absent here the data is lost permanently and silently"
        )
        assert record_count2 == 2, "one NwsRawProduct and one NwsClimateDay"
        assert actor2.published, "the recovered product must also be published"


@pytest.mark.asyncio
async def test_a_clean_poll_still_dedupes_across_a_restart(
    settings: BreezyRuntimeSettings,  # noqa: F811 -- the imported fixture
) -> None:
    """NEGATIVE CONTROL. Steady state must stay a clean no-op.

    A successful poll must still leave the uuid durably marked, so a restart
    followed by the same discovery list re-fetches nothing, writes nothing, and
    publishes nothing. "Stop marking uuids" would satisfy the headline test
    while turning every poll into a re-fetch-and-duplicate-write storm; this
    test refuses that, and it asserts the durable ``productidx:<uuid>`` key
    directly rather than inferring the mark from behaviour alone.
    """
    clock = FakeClock()
    final_uuid = fixture_uuid(NYC_FINAL)

    with process_cycle(settings, clock) as (runtime, actor):
        # Positive control: the key genuinely starts absent, so the assertion
        # after the poll cannot pass vacuously.
        assert runtime.store.get(_index_key(final_uuid)) is None
        await start_and_settle(actor)
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            mock_product(mock, NYC_FINAL)
            await actor.poll_once()

        assert actor.published, "the poll must succeed, or the no-op claim is empty"
        assert runtime.store.get(_index_key(final_uuid)) is not None, (
            "a CONFIRMED persist must durably mark the uuid as seen"
        )
    before = catalog_state(settings)
    assert final_uuid in before[0]

    with process_cycle(settings, clock) as (runtime2, actor2):
        await start_and_settle(actor2)
        assert actor2.published == []
        clock.advance(POLL_INTERVAL_NS)
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            product_route = mock_product(mock, NYC_FINAL)
            await actor2.poll_once()

        assert product_route.call_count == 0, "the durable product index must still dedupe"
        assert catalog_state(settings) == before, "no duplicate catalog write"
        assert (
            GateReason.WRITE_INTEGRITY_VIOLATION
            not in runtime2.shared.gate.blocking_causes(VENUE, CITY)
        )
        assert actor2.published == []


@pytest.mark.asyncio
async def test_a_mismatched_digest_still_blocks_before_anything_is_persisted(
    settings: BreezyRuntimeSettings,  # noqa: F811 -- the imported fixture
) -> None:
    """The tripwire must keep firing BEFORE the write, not after it.

    Moving the durable mark past the persist must not move the *check* past it
    too: a uuid whose bytes changed under a stable id has to hard-block with
    nothing written, exactly as it did before. Seeded with a foreign digest and
    forced past the discovery-time dedupe, as
    ``test_integrity_index_mismatch_hard_blocks`` does in the unit suite.
    """
    clock = FakeClock()
    final_uuid = fixture_uuid(NYC_FINAL)

    with process_cycle(settings, clock) as (runtime, actor):
        await start_and_settle(actor)
        runtime.shared.product_index.observe(final_uuid, "f" * 64)
        actor.refetch_known_products = True
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            mock_product(mock, NYC_FINAL)
            await actor.poll_once()

        assert GateReason.TRANSPORT_INTEGRITY_ALARM in runtime.shared.gate.blocking_causes(
            VENUE, CITY
        )
        assert catalog_state(settings) == (set(), 0), (
            "a digest mismatch must be caught before the catalog write, never after it"
        )
        assert actor.published == []


@pytest.mark.asyncio
async def test_unreadable_persisted_evidence_still_blocks_before_the_write(
    settings: BreezyRuntimeSettings,  # noqa: F811 -- the imported fixture
) -> None:
    """Corruption must stay an integrity alarm, not become a clean slate.

    ``observe`` folded an undecodable persisted entry into its MISMATCH
    verdict; the read-only ``known_digest`` reports the same condition by
    RAISING :class:`CorruptProductIndexEntryError`, because ``None`` is
    reserved for "never observed" and overloading it would turn corruption
    into a free pass. Splitting the check off the recorder must not lose that,
    so this pins the raising half to the identical outcome: CRIT hard-block,
    nothing written, nothing published.

    Reached via ``refetch_known_products`` because ``_undeduped`` consults
    ``known_digest`` first and would otherwise raise before step 8 -- itself
    fail-closed, but through task supervision rather than through this branch.
    """
    clock = FakeClock()
    final_uuid = fixture_uuid(NYC_FINAL)

    with process_cycle(settings, clock) as (runtime, actor):
        await start_and_settle(actor)
        runtime.store.set(_index_key(final_uuid), b"{not json at all")
        actor.refetch_known_products = True
        with respx.mock(assert_all_called=False) as mock:
            mock_discovery(mock, NYC_FINAL)
            mock_product(mock, NYC_FINAL)
            await actor.poll_once()

        assert GateReason.TRANSPORT_INTEGRITY_ALARM in runtime.shared.gate.blocking_causes(
            VENUE, CITY
        )
        assert catalog_state(settings) == (set(), 0)
        assert actor.published == []
