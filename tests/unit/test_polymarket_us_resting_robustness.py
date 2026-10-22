"""S4 WP4 (ARM maker-sharp B5 review G2-G5, G8, G10-G12, G14, G15 and the REJECTED event):
robustness of the resting ledger, the rehydration, the cancel loop and the terminal settle.

A poisoned durable binding row (or any exception inside one id's cancel attempt) must
never fail ``_connect``, the evidence write or the other ids' cancels: the failure LATCHES
``resting_cancel_unconfirmed`` and the loop goes on. Terminal reads must echo the id and
slug that were asked about; logs and alert details name an order by a redacted prefix and
never echo an id or slug that fails validation.

Every sender and private read is a local double: no network, no venue contact.
No ``exec`` import here (barrier X1): everything goes through ``ambig_latch_rig``.
"""

from __future__ import annotations

import asyncio
import dataclasses
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
from tests.unit.polymarket_us_exec_shapes import build_no_leg_instrument
from tests.unit.test_polymarket_us_resting_cancel import (
    CancelSender,
    _auto_cancel,
    _cancel_all_cmd,
    _cancel_cmd,
    _fill_payload,
    _names,
    _payload,
    _rig,
    _set_state,
)
from tests.unit.test_polymarket_us_resting_submit import _id_n, _rest_command, _submit_rest
from tests.unit.test_polymarket_us_resting_sweep import _open_row, _second_process
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_unverified,  # noqa: F401 -- used via usefixtures
)

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


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_filled_read_clears_the_cancel_latch_and_alert_for_that_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G3: a terminal read of any kind (here a fill, which the fill path owns) ends the
    cancel problem for that id: it must not leave the latch or the alert behind."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    await _submit_rest(rig, 0)
    client._latch_resting_cancel_unconfirmed(_id_n(0), "earlier_refusals")
    client._resting_cancel_alert_details = {_id_n(0): {"severity": "CRITICAL"}}
    client._resting_cancel_alert_ns = {_id_n(0): 1}
    _fill_payload(rig, 0)
    unresolved = await asyncio.wait_for(client._cancel_resting_order([_id_n(0)]), 2.0)
    assert unresolved == frozenset()
    assert _LATCH not in [r.reason for r in client._trading_refusals]
    assert client.resting_cancel_alerts == ()
    assert client._unconfirmed_cancel_ids == frozenset()
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_an_unreadable_ledger_mid_loop_latches_instead_of_dropping_the_id_as_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G5: ``None`` from the ledger means UNREADABLE, which is not "retired"."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    await _submit_rest(rig, 0)
    real = client._read_fill_index

    def unreadable(key: str) -> list[str] | None:
        if key == client_module.RESTING_INDEX_KEY:
            return None
        return real(key)  # type: ignore[no-any-return]

    monkeypatch.setattr(client, "_read_fill_index", unreadable)
    unresolved = await asyncio.wait_for(client._cancel_resting_order([_id_n(0)]), 2.0)
    assert unresolved == frozenset()
    assert rig.sender.cancels == [], "nothing to post against an unreadable ledger"
    assert _LATCH in [r.reason for r in client._trading_refusals]
    assert client.log_lines("error", "resting_cancel_unconfirmed")
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_live_partial_fill_keeps_the_cancel_loop_retrying_until_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G4 at the client: PARTIALLY_FILLED (the rest still rests) is not a done cancel; once
    the venue shows the order terminal WITH a fill the cancel path cannot book (here a partial
    of ten), the id stays pending (B6 review S2) and the cancel path settles nothing itself."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    await _submit_rest(rig, 0)
    intent_id = client._resting_bookings[_id_n(0)][0]
    _payload(rig, 0)["quantity"] = 10  # the rig's rest is for one contract; widen it
    _set_state(rig, 0, "ORDER_STATE_PARTIALLY_FILLED", cum=1)
    task = asyncio.ensure_future(client._cancel_resting_order([_id_n(0)]))
    await asyncio.sleep(0.1)
    assert not task.done(), "a live partial is retried, not dropped as filled"
    assert len(rig.sender.cancels) >= 2
    _set_state(rig, 0, "ORDER_STATE_CANCELED", cum=1)
    await asyncio.sleep(0.1)
    assert not task.done(), "an unbookable terminal fill keeps the id pending (B6 review S2)"
    assert "OrderCanceled" not in _names(rig), "a fill is never settled by the cancel path"
    assert client._ledger.has_open_exposure(intent_id)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize("field", ["id", "marketSlug"])
async def test_a_terminal_read_that_echoes_another_order_never_settles_ours(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    """G15 at the client: a CANCELED body for a different id or market is not our proof."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    await _submit_rest(rig, 0)
    _payload(rig, 0).update({"state": "ORDER_STATE_CANCELED", field: "tc-temp-other-x"})
    task = asyncio.ensure_future(client._cancel_resting_order([_id_n(0)]))
    await asyncio.sleep(0.1)
    assert not task.done(), "an echo mismatch keeps the cancel pending"
    assert "OrderCanceled" not in _names(rig)
    assert json.loads(client._store_get(client_module.RESTING_INDEX_KEY)) == [_id_n(0)]
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await client._disconnect()


def hand_bind(client: Any, command: Any, n: int) -> str:
    """Bind ``command``'s cached order as ledger id ``_id_n(n)`` by writing the durable
    index and binding row directly (no submit, so no canonical string is needed); returns
    the slug. The test then has a real cancellable ledger target."""
    body = submit_chain.build_resting_order_body(command.order, build_no_leg_instrument())
    venue_id = _id_n(n)
    indexed = json.loads(client._store_get(client_module.RESTING_INDEX_KEY) or b"[]")
    client._store_set(
        f"{_ROW_PREFIX}{venue_id}",
        submit_chain.resting_binding_bytes(
            intent_id=f"intent-{n}",
            slug=body["marketSlug"],
            client_order_id=command.order.client_order_id.value,
            expire_time_ns=int(command.order.expire_time_ns),
        ),
    )
    client._store_set(
        client_module.RESTING_INDEX_KEY, submit_chain.resting_index_bytes([*indexed, venue_id])
    )
    slug: str = body["marketSlug"]
    return slug


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_cancel_all_without_a_sender_rejects_every_target_and_never_looks_like_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G12: a cancel-all the client cannot send must tell the strategy -- one
    ``OrderCancelRejected`` per ledger target -- and shout in the log, never return quietly."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    await _submit_rest(rig, 0)
    await _submit_rest(rig, 1)
    client._order_sender = None
    await client._cancel_all_orders(_cancel_all_cmd(rig, build_no_leg_instrument().id))
    assert _names(rig).count("OrderCancelRejected") == 2
    assert rig.sender.cancels == []
    assert client.log_lines("error", "Refusing cancel-all")
    assert json.loads(client._store_get(client_module.RESTING_INDEX_KEY)) == [_id_n(0), _id_n(1)]
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env", "write_canonical_unverified")
async def test_cancel_all_with_the_canonical_string_unverified_rejects_every_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same, for an unverified canonical string. The ledger is bound by hand because a
    submit cannot run while the canonical string is unverified."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    hand_bind(client, _rest_command(client), 0)
    await client._cancel_all_orders(_cancel_all_cmd(rig, build_no_leg_instrument().id))
    assert _names(rig).count("OrderCancelRejected") == 1
    assert rig.sender.cancels == []
    assert client.log_lines("error", "canonical string is unverified")
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_cancel_all_that_cannot_send_with_no_target_still_logs_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    client._order_sender = None
    await client._cancel_all_orders(_cancel_all_cmd(rig, build_no_leg_instrument().id))
    assert "OrderCancelRejected" not in _names(rig)
    assert client.log_lines("error", "Refusing cancel-all")
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_the_cancel_alert_log_and_detail_carry_a_redacted_id_and_a_validated_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """G14: the ERROR line and the alert detail (which leaves the process) name the order by
    a short prefix, never the full venue id."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    await _submit_rest(rig, 0)
    target = client._resting_target_of(_id_n(0))
    assert target is not None
    now_ns = (submit_chain.RETRY_ALERT_AGE_S + 1) * 1_000_000_000
    client._note_cancel_refused(target, 0, now_ns)
    (detail,) = client.resting_cancel_alerts
    assert detail["venue_order_id"] == _id_n(0)[:4] + "…"
    assert _id_n(0) not in json.dumps(dict(detail))
    assert detail["slug"] == target.slug
    lines = client.log_lines("error", "resting_cancel_alert")
    assert lines and all(_id_n(0) not in line for line in lines)
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_poisoned_slug_is_never_logged_or_alerted_verbatim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    await _submit_rest(rig, 0)
    target = client._resting_target_of(_id_n(0))
    assert target is not None
    evil = dataclasses.replace(target, slug="tc-x\nCRITICAL forged line")
    now_ns = (submit_chain.RETRY_ALERT_AGE_S + 1) * 1_000_000_000
    client._note_cancel_refused(evil, 0, now_ns)
    (detail,) = client.resting_cancel_alerts
    assert "forged" not in json.dumps(dict(detail))
    assert all("forged" not in m and "\n" not in m for _lv, m in client.log_records)
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize(
    "bad_id",
    ["evil\nCRITICAL forged line", "x" * 500, "café", "\x1b[31mred", ""],
    ids=["newline", "overlong", "unicode", "escape", "empty"],
)
async def test_the_latch_log_never_echoes_an_invalid_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_id: str
) -> None:
    """G14 log-injection: an id that fails the allowlist is replaced, not logged."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    client._latch_resting_cancel_unconfirmed(bad_id, "id_or_slug_unusable")
    lines = client.log_lines("error", "venue order")
    assert lines
    for line in lines:
        assert "forged" not in line and "\x1b" not in line and "x" * 100 not in line
        assert "<invalid-id>" in line
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_the_latch_log_redacts_a_valid_id_and_keeps_synthetic_ids_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    client._latch_resting_cancel_unconfirmed(_id_n(0), "cancel_not_confirmed")
    client._latch_resting_cancel_unconfirmed("boot-sweep", "boot_sweep_reread_failed:X")
    lines = client.log_lines("error", "venue order")
    assert any(_id_n(0)[:4] + "…" in line for line in lines)
    assert all(_id_n(0) not in line for line in lines)
    assert any("boot-sweep" in line for line in lines)
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_venue_rejected_zero_fill_rest_emits_order_rejected_and_settles_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """r4 section 6 (verdicts = the native ``OrderStatus``): the venue's REJECTED maps to the
    native REJECTED status, so the retirement emits ``OrderRejected`` -- never a
    ``OrderCanceled`` the venue did not report. Nautilus accepts ACCEPTED -> REJECTED."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    command = await _submit_rest(rig, 0)
    intent_id = client._resting_bookings[_id_n(0)][0]
    rig.sender.on_cancel = lambda oid: _set_state(rig, 0, "ORDER_STATE_REJECTED")
    await asyncio.wait_for(client._cancel_order(_cancel_cmd(rig, command)), 2.0)
    assert _names(rig).count("OrderRejected") == 1
    assert "OrderCanceled" not in _names(rig)
    assert not client._ledger.has_open_exposure(intent_id)
    assert json.loads(client._store_get(client_module.RESTING_INDEX_KEY)) == []
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_rejected_read_with_a_fill_still_belongs_to_the_fill_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    command = await _submit_rest(rig, 0)
    intent_id = client._resting_bookings[_id_n(0)][0]
    rig.sender.on_cancel = lambda oid: _set_state(rig, 0, "ORDER_STATE_REJECTED", cum=1)
    # B6 review S2: the unbookable REJECTED-with-a-fill read keeps the id pending in the cancel
    # loop (it never settles or emits a terminal itself); the loop is still running here
    task = asyncio.ensure_future(client._cancel_order(_cancel_cmd(rig, command)))
    await asyncio.sleep(0.1)
    assert not task.done()
    assert "OrderRejected" not in _names(rig) and "OrderCanceled" not in _names(rig)
    assert client._ledger.has_open_exposure(intent_id)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await client._disconnect()
