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
    gate_env,  # noqa: F401 -- used via usefixtures
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.test_polymarket_us_resting_cancel import CancelSender
from tests.unit.test_polymarket_us_resting_query import (
    _fill,
    _filled_events,
    _query,
    _records,
    _rested,
)
from tests.unit.test_polymarket_us_resting_submit import _id_n
from tests.unit.test_polymarket_us_resting_sweep import _second_process

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
