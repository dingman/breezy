"""ARM maker-sharp B6 review P2: a restart does not silently clear the commission latches.

The commission latches live in the in-memory refusal list, so a node restart used to clear
``resting_commission_out_of_envelope`` and ``commission_unreadable`` without review. At boot the
client re-derives them from the CURRENT UTC day's ``POLL-`` durable records (their
``venue_fee_raw``): an unreadable commission, or one above the envelope, latches again.

Every sender and private read is a local double: no network, no venue contact.
No ``exec`` import here (barrier X1): everything goes through ``ambig_latch_rig``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final

import pytest

from tests.unit.ambig_latch_rig import (
    gate_env,  # noqa: F401 -- used via usefixtures
    resting_morning_clock,
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.test_polymarket_us_resting_cancel import CancelSender, _payload
from tests.unit.test_polymarket_us_resting_query import _fill, _query, _rested
from tests.unit.test_polymarket_us_resting_sweep import _second_process

ENVELOPE: Final[str] = submit_chain.RESTING_COMMISSION_OUT_OF_ENVELOPE_REASON
UNREADABLE: Final[str] = submit_chain.RESTING_COMMISSION_UNREADABLE_REASON
DAY_S: Final[int] = 86_400


async def _booked_then_rebooted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, commission: str | None
) -> Any:
    """Process one books a poll fill (``commission`` None = absent), process two boots over its
    store; returns the NOT yet connected second client."""
    rig, (command,) = await _rested(tmp_path, monkeypatch, clock=resting_morning_clock())
    _fill(rig, 0, commission="0.01" if commission is None else commission)
    if commission is None:
        del _payload(rig, 0)["commissionNotionalTotalCollected"]
    await rig.client._query_order(_query(rig, command))
    first = rig.client
    return await _second_process(
        tmp_path,
        monkeypatch,
        first,
        first.latch_cm,
        sender=CancelSender(),
        clock=resting_morning_clock(),
    )


def _reasons_of(client: Any) -> list[str]:
    return [r.reason for r in client._trading_refusals]


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_restart_relatches_an_out_of_envelope_commission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    second = await _booked_then_rebooted(tmp_path, monkeypatch, commission="0.50")
    assert ENVELOPE not in _reasons_of(second), "a fresh process starts with no latch"
    await second._connect()
    assert ENVELOPE in _reasons_of(second)
    assert [a["event"] for a in second.resting_commission_alerts] == [
        "resting_commission_out_of_envelope"
    ]
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_restart_relatches_an_unreadable_commission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    second = await _booked_then_rebooted(tmp_path, monkeypatch, commission=None)
    await second._connect()
    assert UNREADABLE in _reasons_of(second)
    assert [a["event"] for a in second.resting_commission_alerts] == ["commission_unreadable"]
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_restart_over_an_ordinary_fill_latches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    second = await _booked_then_rebooted(tmp_path, monkeypatch, commission="0.01")
    await second._connect()
    assert ENVELOPE not in _reasons_of(second) and UNREADABLE not in _reasons_of(second)
    assert not second.resting_commission_alerts
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_record_from_a_past_utc_day_is_not_re_derived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    second = await _booked_then_rebooted(tmp_path, monkeypatch, commission="0.50")
    second.advance(2 * DAY_S)
    await second._connect()
    assert ENVELOPE not in _reasons_of(second)
    await second._disconnect()
