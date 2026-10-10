"""EXEC-PAR WP7 (r5 5.WP7): deterministic replay.

Two runs of the same scripted K = 3 session -- an accept-fill, a with-id AMBIGUOUS
take, a no-id AMBIGUOUS take (transport failure), a clock jump and a resolver
drain -- under a FIXED clock and the same venue script must leave byte-identical
persisted state and send byte-identical order sequences.

The only entropy in that state is process-local by design: the latch's random
intent id (``uuid4``), the ledger's process-monotonic booking id, and the
durability probe's nonce (a documented, harmless marker key). The replay restarts
the first two counters per run and skips the third key; nothing else is touched.
Any OTHER difference between the runs (a stray wall-clock read, set ordering, a
dict-order dependency) is what this test exists to catch.
"""

from __future__ import annotations

import itertools
import sqlite3
import types
import uuid
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from breezy.adapters.polymarket_us import operator_controls
from breezy.ingest.gate import DURABILITY_PROBE_KEY
from breezy.runtime import submit_intent
from tests.unit.exec_par_rig import (
    BASE_NS,
    SEC_NS,
    ScriptedSender,
    accept_fill_body,
    ambiguous_body,
    backdate,
    build_par_rig,
    caps,
    decimal_spent,
    ok,
    run_passes,
    wire_order,
    wire_positions,
)
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)


@dataclass(frozen=True)
class Replay:
    """Everything a run leaves behind that a replay must reproduce exactly."""

    store_rows: tuple[tuple[str, bytes], ...]
    posted_bodies: tuple[bytes, ...]
    posted_headers: tuple[tuple[tuple[str, str], ...], ...]
    event_names: tuple[str, ...]
    denied: tuple[str, ...]
    spent: str


def _pin_process_counters(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restart the two process-local sources a fresh process would restart anyway.

    The latch's ``uuid4`` intent id, and the ledger's process-monotonic booking id
    (``operator_controls._BOOKING_IDS``, persisted in the resolver context): a
    second run in the SAME process would otherwise continue the first run's count.
    """
    monkeypatch.setattr(operator_controls, "_BOOKING_IDS", itertools.count(1))
    counter = iter(range(1, 1_000_000))
    monkeypatch.setattr(
        submit_intent,
        "uuid",
        types.SimpleNamespace(uuid4=lambda: uuid.UUID(int=next(counter))),
    )


def _store_rows(path: Path) -> tuple[tuple[str, bytes], ...]:
    connection = sqlite3.connect(path)
    try:
        rows = connection.execute("SELECT key, value FROM state ORDER BY key").fetchall()
    finally:
        connection.close()
    # The durability probe's nonce is random BY DESIGN ("the last probe's nonce, which
    # is harmless", ingest/gate.py) and carries no order, slot or ledger state.
    return tuple(
        (str(key), bytes(value)) for key, value in rows if str(key) != DURABILITY_PROBE_KEY
    )


async def _session(directory: Path, monkeypatch: pytest.MonkeyPatch) -> Replay:
    directory.mkdir(parents=True)
    _pin_process_counters(monkeypatch)
    sender = ScriptedSender(
        ok(b""),  # placeholder: the accept-fill needs the rig's slug
        ok(ambiguous_body("ord-b")),
        ConnectionResetError("transport down (replay)"),
    )
    rig = await build_par_rig(directory, monkeypatch, sender=sender, max_slots=3)
    sender.responses[0] = ok(accept_fill_body(rig.slug(0), order_id="ord-a"))
    await rig.client._submit_order(rig.buy(rig.instruments[0]))
    await rig.client._submit_order(rig.buy(rig.instruments[1]))
    await rig.client._submit_order(rig.buy(rig.instruments[2]))
    open_ids = sorted(rig.open_intent_ids())
    assert len(open_ids) == 2, "the accept-fill retired; both AMBIGUOUS takes hold a slot"

    # A clock jump, a fresh heartbeat, then a drain through the real resolver.
    rig.client.set_now(BASE_NS + 90 * SEC_NS)
    now_ns = rig.clock.timestamp_ns()
    rig.latch.write_breaker_heartbeat(hb_ns=now_ns, resolver_pass_ns=now_ns)
    wire_order(rig, "ord-b", 1, state="ORDER_STATE_CANCELED", cum_quantity=0)
    wire_positions(rig, {})
    for intent_id in open_ids:
        backdate(rig.client, intent_id)
    await run_passes(rig.client, count=8)

    result = Replay(
        store_rows=(),
        posted_bodies=tuple(call["body"] for call in sender.calls),
        posted_headers=tuple(tuple(sorted(call["headers"].items())) for call in sender.calls),
        event_names=tuple(type(event).__name__ for event in rig.order_events),
        denied=tuple(rig.denied_reasons()),
        spent=str(decimal_spent(rig)),
    )
    path = rig.store_path
    await rig.close()
    return replace(result, store_rows=_store_rows(path))


@pytest.mark.asyncio
async def test_replay_bit_for_bit_fixed_clock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        first = await _session(tmp_path / "run_a", monkeypatch)
        second = await _session(tmp_path / "run_b", monkeypatch)

    assert first.posted_bodies, "the session sent orders"
    assert first.store_rows, "the session persisted state"
    assert second.posted_bodies == first.posted_bodies, "byte-identical order sequence"
    assert second.posted_headers == first.posted_headers
    assert second.store_rows == first.store_rows, "byte-identical persisted state"
    assert second.event_names == first.event_names
    assert second.denied == first.denied
    assert second.spent == first.spent
