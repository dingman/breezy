"""ARM maker-sharp B6 security review: S1 (swept retirement vs open orders), S2 (a failed booking
in the cancel loop), S3 (a crash replay of ``record_fill``).

Every sender and private read is a local double: no network, no venue contact.
No ``exec`` import here (barrier X1): everything goes through ``ambig_latch_rig``.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from tests.unit.ambig_latch_rig import (
    OPEN_ORDERS_PATH,
    gate_env,  # noqa: F401 -- used via usefixtures
    run_passes,
    submit_chain,
    wire_payloads,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.test_ambig_no_id_resolver import _negative, _retirement
from tests.unit.test_polymarket_us_resting_cancel import CancelSender
from tests.unit.test_polymarket_us_resting_query import (
    _fill,
    _filled_events,
    _query,
    _records,
    _rested,
)
from tests.unit.test_polymarket_us_resting_restart import SWEEP, _prior_process
from tests.unit.test_polymarket_us_resting_submit import _id_n, _rest_command
from tests.unit.test_polymarket_us_resting_sweep import _open_row, _second_process

NO_PX: Final[Decimal] = Decimal("0.40")

CANCEL_LATCH: Final[str] = submit_chain.RESTING_CANCEL_UNCONFIRMED_REASON


def _refusal_reasons(client: Any) -> list[str]:
    return [r.reason for r in client._trading_refusals]


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_s2_a_failed_booking_in_the_cancel_loop_keeps_the_latch_and_the_pending_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    client = rig.client
    venue_id = _id_n(0)
    client._latch_resting_cancel_unconfirmed(venue_id, "test")
    _fill(rig, 0)

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(client, "record_fill", boom)
    still_pending = await client._cancel_resting_order((venue_id,), max_passes=1)
    assert venue_id in still_pending, "the fill is not booked: the id stays pending"
    assert CANCEL_LATCH in _refusal_reasons(client), "and the cancel latch is kept"
    assert venue_id in client._unconfirmed_cancel_ids
    assert _records(rig) == () and _filled_events(rig) == []
    # the write recovers: the next read books it and only then is the latch cleared
    monkeypatch.delattr(client, "record_fill")
    await client._query_order(_query(rig, command))
    assert len(_records(rig)) == 1
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_s2_a_booked_fill_in_the_cancel_loop_still_clears_the_latch_and_the_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (_command,) = await _rested(tmp_path, monkeypatch)
    client = rig.client
    venue_id = _id_n(0)
    client._latch_resting_cancel_unconfirmed(venue_id, "test")
    _fill(rig, 0)
    still_pending = await client._cancel_resting_order((venue_id,), max_passes=1)
    assert still_pending == frozenset()
    assert CANCEL_LATCH not in _refusal_reasons(client)
    assert len(_records(rig)) == 1
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_s3_a_crash_replay_of_record_fill_does_not_double_the_settle_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Process one wrote the durable ``POLL-`` record, then died before retiring the row. The next
    boot's spend seed already counted that record; re-booking the same fill must not add its
    cost a second time."""
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    first = rig.client
    _fill(rig, 0, commission="0.01")
    path = submit_chain.order_by_id_path(_id_n(0))
    payloads = {path: first._private_read._payloads[path]}

    def crash(_venue_id: str) -> bool:
        raise OSError("killed between record_fill and retire")

    monkeypatch.setattr(first, "_retire_resting_row", crash)
    await first._query_order(_query(rig, command))
    assert len(_records(rig)) == 1, "the record was written before the crash"
    monkeypatch.delattr(first, "_retire_resting_row")
    second = await _second_process(
        tmp_path, monkeypatch, first, first.latch_cm, sender=CancelSender(), payloads=payloads
    )
    await second._connect()
    spent = second._ledger.spent_today_usd(now_ns=second._clock.timestamp_ns())
    assert spent == NO_PX, "the cost is counted once (by the seed), not again by the replay"
    assert second._trading_refusals == []
    await second._disconnect()


# -- S1: the swept NO_FILL retirement consults the open-orders read ------------------------


async def _swept_two_passes(second: Any) -> None:
    second.advance(305)
    await run_passes(second, 1)
    second.advance(70)
    await run_passes(second, 2)


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_s1_an_open_order_on_the_swept_slug_blocks_the_no_fill_retirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    second, intent_id, _context = await _prior_process(tmp_path, monkeypatch, sender=CancelSender())
    row = _open_row(_rest_command(second), 7)
    _negative(second, open_orders=[row])
    await _swept_two_passes(second)
    assert _retirement(second) is None, "an order still open on the slug may yet fill"
    assert second._latch.current_open() is not None
    # it clears the moment the venue shows the slug clear: the retirement then proceeds
    _negative(second)
    second.advance(70)
    await run_passes(second, 1)
    second.advance(70)
    await run_passes(second, 1)
    assert _retirement(second) == SWEEP
    del intent_id
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_s1_an_unreadable_open_orders_read_blocks_the_no_fill_retirement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    second, _intent_id, _context = await _prior_process(
        tmp_path, monkeypatch, sender=CancelSender()
    )
    _negative(second)
    del wire_payloads(second)[OPEN_ORDERS_PATH]
    await _swept_two_passes(second)
    assert _retirement(second) is None, "an unread open-orders book is not a clear slug"
    await second._disconnect()


# -- S6: emit before retire; a failing retire never strands the booking ---------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_s6_a_failing_retire_after_the_record_still_emits_the_fill_and_settles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The native ``OrderFilled`` is emitted BEFORE the row is retired and the retire is guarded:
    a retire that raises (after the index write, or before) must not leave the Nautilus order
    open with the durable record already written, nor skip the settle."""
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    client = rig.client
    intent_id = client._resting_bookings[_id_n(0)][0]
    _fill(rig, 0, commission="0.01")

    def boom(_venue_id: str) -> bool:
        raise OSError("tombstone write failed")

    monkeypatch.setattr(client, "_retire_resting_row", boom)
    await client._query_order(_query(rig, command))
    assert len(_records(rig)) == 1
    assert len(_filled_events(rig)) == 1, "the order is not left open in the cache"
    assert not client._ledger.has_open_exposure(intent_id), "the exposure is settled"
    assert client.log_lines("error", "retiring the booked rest failed")
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_s6_the_fill_event_is_emitted_while_the_row_is_still_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    client = rig.client
    _fill(rig, 0)
    seen: list[bool] = []
    real = client._emit_resting_fill_event

    def spy(*args: Any, **kwargs: Any) -> None:
        seen.append(client._rest_still_bound(_id_n(0)))
        real(*args, **kwargs)

    monkeypatch.setattr(client, "_emit_resting_fill_event", spy)
    await client._query_order(_query(rig, command))
    assert seen == [True]
    assert not client._rest_still_bound(_id_n(0)), "and retired right after"
    await client._disconnect()
