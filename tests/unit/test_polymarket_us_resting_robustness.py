"""S4 WP4 (ARM maker-sharp B5 review G2-G8, G10, G11): robustness of the resting ledger,
the rehydration, the cancel loop and the terminal settle.

A poisoned durable binding row (or any exception inside one id's cancel attempt) must
never fail ``_connect``, the evidence write or the other ids' cancels: the failure LATCHES
``resting_cancel_unconfirmed`` and the loop goes on.

Every sender and private read is a local double: no network, no venue contact.
No ``exec`` import here (barrier X1): everything goes through ``ambig_latch_rig``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Final

import pytest

from tests.unit.ambig_latch_rig import (
    OPEN_ORDERS_PATH,
    client_module,
    gate_env,  # noqa: F401 -- used via usefixtures
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.test_polymarket_us_resting_cancel import (
    CancelSender,
    _auto_cancel,
    _names,
    _rig,
    _set_state,
)
from tests.unit.test_polymarket_us_resting_submit import _id_n, _submit_rest
from tests.unit.test_polymarket_us_resting_sweep import _open_row, _second_process

_ROW_PREFIX: Final[str] = client_module.RESTING_KEY_PREFIX
_EVIDENCE_KEY: Final[str] = client_module.STARTUP_EVIDENCE_KEY
_LATCH: Final[str] = submit_chain.RESTING_CANCEL_UNCONFIRMED_REASON

#: Binding-row mutations a corrupt (or hostile) durable row could carry.
_POISONS: Final[dict[str, dict[str, Any]]] = {
    "expire_not_a_number": {"expireTimeNs": "abc"},
    "expire_a_list": {"expireTimeNs": [1]},
    "expire_a_bool": {"expireTimeNs": True},
    "slug_null": {"slug": None},
    "slug_number": {"slug": 7},
    "intent_number": {"intentId": 5},
    "intent_null": {"intentId": None},
    "client_order_id_list": {"clientOrderId": ["x"]},
    "client_order_id_nul": {"clientOrderId": "a\x00b"},
}


def _poison(client: Any, **changes: Any) -> None:
    key = f"{_ROW_PREFIX}{_id_n(0)}"
    row = json.loads(client._store_get(key))
    row.update(changes)
    client._store_set(key, json.dumps(row).encode())


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize("name", sorted(_POISONS))
async def test_a_poisoned_binding_row_is_an_unusable_target_never_a_raise(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    await _submit_rest(rig, 0)
    _poison(rig.client, **_POISONS[name])
    target = rig.client._bound_target_of(_id_n(0))
    assert target.venue_order_id == _id_n(0) and target.bound is True
    assert target.slug == "", "an unusable row has no slug (terminal-unconfirmable in the loop)"
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize("raw", [b"\xff\xfe", b"[1, 2]", b"null", b"123", b'"x"', b"{"])
async def test_an_undecodable_binding_row_is_an_unusable_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: bytes
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    await _submit_rest(rig, 0)
    rig.client._store_set(f"{_ROW_PREFIX}{_id_n(0)}", raw)
    target = rig.client._bound_target_of(_id_n(0))
    assert target.slug == "" and target.intent_id == ""
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize("name", sorted(_POISONS))
async def test_a_poisoned_binding_row_does_not_fail_connect_and_latches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    await _submit_rest(rig, 0)
    _poison(rig.client, **_POISONS[name])
    sender = CancelSender()
    second = await _second_process(
        tmp_path, monkeypatch, rig.client, rig.client.latch_cm, sender=sender
    )
    await second._connect()  # must not raise
    assert second._store_get(_EVIDENCE_KEY), "the evidence write completed"
    assert _LATCH in [r.reason for r in second._trading_refusals]
    assert json.loads(second._store_get(client_module.RESTING_INDEX_KEY)) == [_id_n(0)]
    assert sender.cancels == [], "an unusable row posts nothing (no slug to cancel against)"
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_resting_ledger_never_raises_and_latches_when_the_store_read_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    await _submit_rest(rig, 0)
    real = client._store_get

    def boom(key: str) -> bytes | None:
        if key == client_module.RESTING_INDEX_KEY:
            raise RuntimeError("store exploded")
        return real(key)  # type: ignore[no-any-return]

    monkeypatch.setattr(client, "_store_get", boom)
    assert client._resting_ledger() is None
    assert _LATCH in [r.reason for r in client._trading_refusals]
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_the_evidence_write_survives_a_failing_ledger_and_marks_nothing_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    await _submit_rest(rig, 0)

    def boom() -> Any:
        raise RuntimeError("ledger exploded")

    monkeypatch.setattr(client, "_resting_ledger", boom)
    await client._refresh_startup_position_evidence()
    evidence = json.loads(client._store_get(_EVIDENCE_KEY))
    assert [o["own_resting"] for o in evidence["open_orders"]] == [False] * len(
        evidence["open_orders"]
    )
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_rehydration_failure_for_one_row_latches_and_the_rest_still_rehydrate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    await _submit_rest(rig, 0)
    await _submit_rest(rig, 1)
    payloads: dict[str, Any] = rig.client._private_read._payloads
    sender = CancelSender()
    second = await _second_process(
        tmp_path,
        monkeypatch,
        rig.client,
        rig.client.latch_cm,
        sender=sender,
        payloads={
            submit_chain.order_by_id_path(_id_n(n)): payloads[
                submit_chain.order_by_id_path(_id_n(n))
            ]
            for n in (0, 1)
        },
    )
    ledger_type = type(second._ledger)
    real = ledger_type.register_open_exposure
    calls: list[str] = []

    def flaky(self: Any, intent_id: str, *args: Any, **kwargs: Any) -> Any:
        calls.append(intent_id)
        if len(calls) == 1:
            raise RuntimeError("register exploded")
        return real(self, intent_id, *args, **kwargs)

    monkeypatch.setattr(ledger_type, "register_open_exposure", flaky)
    await second._connect()  # must not raise
    assert len(calls) == 2, "the loop went on after the first row failed"
    assert _LATCH in [r.reason for r in second._trading_refusals]
    assert len(second._resting_bookings) == 1, "exactly the row that did not fail is tracked"
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_mid_batch_exception_latches_that_id_and_still_cancels_the_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    await _submit_rest(rig, 0)
    await _submit_rest(rig, 1)
    real = client._settle_resting_terminal

    def flaky(target: Any, verdict: str) -> bool:
        if target.venue_order_id == _id_n(0):
            raise RuntimeError("settle exploded")
        return real(target, verdict)  # type: ignore[no-any-return]

    monkeypatch.setattr(client, "_settle_resting_terminal", flaky)
    _auto_cancel(rig)
    unresolved = await asyncio.wait_for(
        client._cancel_resting_order([_id_n(0), _id_n(1)], max_passes=1), 2.0
    )
    assert _id_n(1) not in unresolved
    assert _names(rig).count("OrderCanceled") == 1, "the second id was still cancelled"
    assert json.loads(client._store_get(client_module.RESTING_INDEX_KEY)) == [_id_n(0)]
    assert _LATCH in [r.reason for r in client._trading_refusals]
    assert client._cancel_in_flight == frozenset()
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_settle_runs_before_the_native_event_and_a_raising_emit_is_contained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G8: the exposure is settled and the row retired BEFORE the event is emitted, and
    an exception out of the emit neither escapes nor undoes the settle."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    command = await _submit_rest(rig, 0)
    intent_id = client._resting_bookings[_id_n(0)][0]
    seen: list[bool] = []

    def boom(**kwargs: Any) -> None:
        seen.append(client._ledger.has_open_exposure(intent_id))
        raise RuntimeError("emit exploded")

    monkeypatch.setattr(client, "generate_order_canceled", boom)
    _set_state(rig, 0, "ORDER_STATE_CANCELED")
    target = client._resting_target_of(_id_n(0))
    assert target is not None
    assert client._settle_resting_terminal(target, submit_chain.CANCEL_READ_CANCELED) is True
    assert seen == [False], "settled before the emit"
    assert json.loads(client._store_get(client_module.RESTING_INDEX_KEY)) == []
    assert client.log_lines("error", "RuntimeError") or client.log_lines("warning", "RuntimeError")
    del command
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_raising_expired_emit_is_contained_too(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    await _submit_rest(rig, 0)

    def boom(**kwargs: Any) -> None:
        raise RuntimeError("emit exploded")

    monkeypatch.setattr(client, "generate_order_expired", boom)
    target = client._resting_target_of(_id_n(0))
    assert target is not None
    assert client._settle_resting_terminal(target, submit_chain.CANCEL_READ_EXPIRED) is True
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_poisoned_row_is_not_an_open_order_passthrough_in_a_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The poisoned id is still listed open by the venue: it must stay foreign to the gate."""
    rig = await _rig(tmp_path, monkeypatch)
    command = await _submit_rest(rig, 0)
    _poison(rig.client, slug=None)
    sender = CancelSender()
    second = await _second_process(
        tmp_path,
        monkeypatch,
        rig.client,
        rig.client.latch_cm,
        sender=sender,
        payloads={OPEN_ORDERS_PATH: {"orders": [_open_row(command, 0)]}},
    )
    await second._connect()
    evidence = json.loads(second._store_get(_EVIDENCE_KEY))
    assert [o["own_resting"] for o in evidence["open_orders"]] == [False]
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_an_id_that_leaves_pending_is_released_from_in_flight_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G2: the in-flight guard drops an id the moment it is terminal, not when the whole
    loop (which may retry another id for hours) finally exits."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    await _submit_rest(rig, 0)
    await _submit_rest(rig, 1)
    rig.sender.on_cancel = lambda oid: (
        _set_state(rig, 0, "ORDER_STATE_CANCELED") if oid == _id_n(0) else None
    )
    task = asyncio.ensure_future(client._cancel_resting_order([_id_n(0), _id_n(1)]))
    await asyncio.sleep(0.1)
    assert not task.done(), "id 1 stays open, so the loop keeps retrying"
    assert _id_n(0) not in client._cancel_in_flight, "terminal id released immediately"
    assert _id_n(1) in client._cancel_in_flight
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client._cancel_in_flight == frozenset()
    await client._disconnect()
