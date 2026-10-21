"""S4 WP4 (ARM maker-sharp B5): the per-order cancel path, instrument-filtered
cancel-all, the cancel latches and the in-flight guard.

Plan: ``docs/plans/backlog/MAKER_2026-10-12/S4_exec_resting_order_path_plan_r4_delta.md``
sections 2 WP4, 5, 6 and 9; ARM plan r2 delta D2 (instrument filter, in-flight set).

Every sender and private read is a local double: no network, no venue contact.
No ``exec`` import here (barrier X1): everything goes through ``ambig_latch_rig``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Final

import pytest
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import CancelAllOrders, CancelOrder
from nautilus_trader.model.enums import OrderSide

from breezy.adapters.polymarket_us.safety import live_trading_budget_remaining
from breezy.adapters.polymarket_us.transport import VenueResponse
from tests.unit.ambig_latch_rig import (
    build_client,
    caps,
    client_module,
    gate_env,  # noqa: F401 -- used via usefixtures
    run_passes,
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.polymarket_us_exec_shapes import build_instrument, build_no_leg_instrument
from tests.unit.test_current_rung_hold_pre_arm_race import (
    STRATEGY_ID,
    TRADER_ID,
    _SlowSender,
)
from tests.unit.test_polymarket_us_permit_issuance import enable_operator_gate
from tests.unit.test_polymarket_us_resting_submit import (
    _id_n,
    _rest_command,
    _Rig,
    _submit_rest,
    _venue_order,
)
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_unverified,  # noqa: F401 -- used via usefixtures
)

_INDEX_KEY: Final[str] = client_module.RESTING_INDEX_KEY
_ROW_PREFIX: Final[str] = client_module.RESTING_KEY_PREFIX
NS: Final[int] = 1_000_000_000


class CancelSender(_SlowSender):
    """``post_order`` (the create) plus the two cancel verbs, all recorded."""

    def __init__(self) -> None:
        super().__init__()
        self.cancels: list[dict[str, Any]] = []
        self.cancel_alls: list[list[str]] = []
        self.on_cancel: Any = None
        self.cancel_raises: BaseException | None = None
        self.gate: asyncio.Event | None = None

    async def post_cancel_order(
        self, api_base_url: str, *, headers: Any, order_id: str, market_slug: str
    ) -> Any:
        await asyncio.sleep(0)
        if self.gate is not None:
            await self.gate.wait()
        self.cancels.append({"order_id": order_id, "market_slug": market_slug})
        if self.cancel_raises is not None:
            raise self.cancel_raises
        if self.on_cancel is not None:
            self.on_cancel(order_id)
        return VenueResponse(status=200, headers={}, body=b"{}")

    async def post_cancel_all(self, api_base_url: str, *, headers: Any, slugs: list[str]) -> Any:
        await asyncio.sleep(0)
        self.cancel_alls.append(list(slugs))
        return VenueResponse(status=200, headers={}, body=b"{}")


async def _rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, pin: bool = False) -> _Rig:
    monkeypatch.setattr(submit_chain, "GTD_EXPIRY_VERIFIED", True)
    monkeypatch.setattr(submit_chain, "SLUG_SCOPED_CANCEL_ALL_VERIFIED", pin)
    monkeypatch.setattr(submit_chain, "RESTING_CONFIRM_DEADLINE_NS", 20_000_000)
    monkeypatch.setattr(submit_chain, "RESTING_CONFIRM_POLL_S", 0.001)
    monkeypatch.setattr(submit_chain, "CANCEL_RETRY_BACKOFF_S", (0.001,))
    sender = CancelSender()
    client, events, _permit, _cm = await build_client(tmp_path, monkeypatch, sender=sender)
    client._resting_accept_admitted = True
    no = build_no_leg_instrument()
    client._cache.add_instrument(no)
    client._instrument_provider.add(no)
    return _Rig(client, sender, events)


def _payload(rig: _Rig, n: int) -> dict[str, Any]:
    payloads: dict[str, Any] = rig.client._private_read._payloads
    return payloads[submit_chain.order_by_id_path(_id_n(n))]["order"]  # type: ignore[no-any-return]


def _set_state(rig: _Rig, n: int, state: str, cum: int = 0) -> None:
    _payload(rig, n).update({"state": state, "cumQuantity": cum})


def _cancel_cmd(rig: _Rig, command: Any) -> CancelOrder:
    return CancelOrder(
        trader_id=TRADER_ID,
        strategy_id=STRATEGY_ID,
        instrument_id=command.order.instrument_id,
        client_order_id=command.order.client_order_id,
        venue_order_id=None,
        command_id=UUID4(),
        ts_init=rig.client._clock.timestamp_ns(),
    )


def _cancel_all_cmd(rig: _Rig, instrument_id: Any) -> CancelAllOrders:
    return CancelAllOrders(
        trader_id=TRADER_ID,
        strategy_id=STRATEGY_ID,
        instrument_id=instrument_id,
        order_side=OrderSide.NO_ORDER_SIDE,
        command_id=UUID4(),
        ts_init=rig.client._clock.timestamp_ns(),
    )


def _auto_cancel(rig: _Rig) -> None:
    """The venue honours every cancel POST: the order reads CANCELED afterwards."""
    rig.sender.on_cancel = lambda order_id: _set_state(
        rig, int(order_id[-1]), "ORDER_STATE_CANCELED"
    )


def _names(rig: _Rig) -> list[str]:
    return rig.event_names()


def _remaining(rig: _Rig) -> tuple[Any, int]:
    return live_trading_budget_remaining(rig.client._permit)


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_zero_fill_cancel_settles_exactly_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    command = await _submit_rest(rig, 0)
    intent_id = client._resting_bookings[_id_n(0)][0]
    settles: list[str] = []
    ledger_type = type(client._ledger)
    real = ledger_type.settle

    def spy(self: Any, key: str, **kwargs: Any) -> Any:
        settles.append(key)
        return real(self, key, **kwargs)

    monkeypatch.setattr(ledger_type, "settle", spy)
    released: list[Any] = []
    monkeypatch.setattr(ledger_type, "release_booking", lambda *a, **k: released.append(1))
    _auto_cancel(rig)
    await client._cancel_order(_cancel_cmd(rig, command))
    assert _names(rig).count("OrderCanceled") == 1
    assert settles == [intent_id], "settled exactly once, via settle (never release_booking)"
    assert released == []
    assert not client._ledger.has_open_exposure(intent_id)
    assert json.loads(client._store_get(_INDEX_KEY)) == []
    assert not client._store_get(f"{_ROW_PREFIX}{_id_n(0)}")
    assert _id_n(0) not in client._resting_bookings
    assert client._cancel_in_flight == frozenset()
    assert client._latch.open_slot_count() == 0
    # a second cancel of the same (now unknown) order is rejected, never re-settled
    await client._cancel_order(_cancel_cmd(rig, command))
    assert settles == [intent_id]
    assert _names(rig).count("OrderCanceled") == 1
    assert "OrderCancelRejected" in _names(rig)
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_cancel_body_is_the_bound_rows_market_slug_and_the_signature_covers_the_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    command = await _submit_rest(rig, 0)
    signed: list[tuple[str, str]] = []
    real = client._write_signer.sign_headers

    def spy(method: str, path: str, **kwargs: Any) -> Any:
        signed.append((method, path))
        return real(method, path, **kwargs)

    monkeypatch.setattr(client._write_signer, "sign_headers", spy, raising=False)
    _auto_cancel(rig)
    await client._cancel_order(_cancel_cmd(rig, command))
    row_slug = json.loads(client._store_get(f"{_ROW_PREFIX}{_id_n(0)}") or b"{}").get("slug")
    assert rig.sender.cancels == [
        {
            "order_id": _id_n(0),
            "market_slug": submit_chain.build_resting_order_body(
                command.order, build_no_leg_instrument()
            )["marketSlug"],
        }
    ]
    assert signed[-1] == ("POST", f"/v1/order/{_id_n(0)}/cancel")
    assert row_slug in (None, rig.sender.cancels[0]["market_slug"])
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_bare_200_does_not_emit_order_canceled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 200 on the cancel POST proves nothing: with the GET still NEW the loop keeps
    going (RETRY-WHEN-OPEN), emits nothing, settles nothing, restores nothing."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    command = await _submit_rest(rig, 0)
    before = _remaining(rig)
    intent_id = client._resting_bookings[_id_n(0)][0]
    task = asyncio.ensure_future(client._cancel_order(_cancel_cmd(rig, command)))
    await asyncio.sleep(0.1)
    assert not task.done(), "the loop retries while the order stays open"
    assert len(rig.sender.cancels) >= 2, "re-POSTs after the backoff"
    assert _id_n(0) in client._cancel_in_flight, "populated for the loop's lifetime (B4 review)"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert client._cancel_in_flight == frozenset(), "cleared in a finally"
    assert "OrderCanceled" not in _names(rig)
    assert client._ledger.has_open_exposure(intent_id)
    assert _remaining(rig) == before
    assert json.loads(client._store_get(_INDEX_KEY)) == [_id_n(0)]
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_cancel_post_200_but_get_filled_routes_to_fill_and_does_not_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    command = await _submit_rest(rig, 0)
    before = _remaining(rig)
    intent_id = client._resting_bookings[_id_n(0)][0]
    rig.sender.on_cancel = lambda _id: _set_state(rig, 0, "ORDER_STATE_FILLED", cum=1)
    await client._cancel_order(_cancel_cmd(rig, command))
    assert "OrderCanceled" not in _names(rig)
    assert client._ledger.has_open_exposure(intent_id), "the fill path (poll) settles it"
    assert json.loads(client._store_get(_INDEX_KEY)) == [_id_n(0)], "row kept for the poll"
    assert _remaining(rig) == before, "no restore on a fill"
    assert client._cancel_in_flight == frozenset()
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_restore_only_for_this_process_ids_and_idempotent_per_venue_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    command = await _submit_rest(rig, 0)
    after_submit = _remaining(rig)
    _auto_cancel(rig)
    await client._cancel_order(_cancel_cmd(rig, command))
    restored = _remaining(rig)
    assert restored[1] == after_submit[1] + 1, "the order-count slot came back"
    assert restored[0] > after_submit[0], "the notional came back"
    assert client._budget_was_restored(_id_n(0))
    # a second terminal for the SAME id (venue-initiated duplicate) restores nothing
    target = client_module.RestingTarget(
        venue_order_id=_id_n(0),
        slug="x",
        client_order_id="O-1",
        intent_id="I-x",
        instrument_id=None,
        strategy_id=None,
        expire_time_ns=0,
        bound=True,
    )
    assert client._settle_resting_terminal(target, submit_chain.CANCEL_READ_EXPIRED) is False
    assert _remaining(rig) == restored
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_rehydrated_id_is_cancelled_without_a_permit_restore(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An id this process did not arm (not in ``_this_process_resting_ids``) is
    settled but never restored to this process's permit."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    command = await _submit_rest(rig, 0)
    client._this_process_resting_ids = frozenset()
    before = _remaining(rig)
    _auto_cancel(rig)
    await client._cancel_order(_cancel_cmd(rig, command))
    assert _names(rig).count("OrderCanceled") == 1
    assert _remaining(rig) == before
    assert not client._budget_was_restored(_id_n(0))
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_venue_initiated_expiry_settles_once_with_an_expired_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    command = await _submit_rest(rig, 0)
    target = client._resting_cancel_target(_cancel_cmd(rig, command))[0]
    assert client._settle_resting_terminal(target, submit_chain.CANCEL_READ_EXPIRED) is True
    assert client._settle_resting_terminal(target, submit_chain.CANCEL_READ_EXPIRED) is False
    assert _names(rig).count("OrderExpired") == 1
    assert "OrderCanceled" not in _names(rig)
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_cancel_allowed_with_an_expired_permit_and_never_asserts_the_permit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    command = await _submit_rest(rig, 0)

    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a cancel must never assert the permit or arm an intent")

    monkeypatch.setattr(client_module, "assert_live_order_submission_permitted", boom)
    monkeypatch.setattr(client._latch, "arm_slot", boom)

    def expired(*_a: Any, **_k: Any) -> Any:
        raise client_module.LiveTradingPermissionError("permit expired")

    monkeypatch.setattr(client_module, "restore_live_trading_budget", expired)
    _auto_cancel(rig)
    await client._cancel_order(_cancel_cmd(rig, command))
    assert _names(rig).count("OrderCanceled") == 1, (
        "the cancel completes; only the restore is skipped"
    )
    assert client._latch.open_slot_count() == 0
    await client._disconnect()


def test_the_client_never_emits_pending_cancel() -> None:
    """[CHAR] The native strategy applies ``OrderPendingCancel``; the client must not."""
    source = Path(client_module.__file__).read_text(encoding="utf-8")
    assert "generate_order_pending_cancel" not in source


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_cancel_of_an_unknown_order_is_rejected_and_nothing_is_posted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    command = _rest_command(client)  # created and cached, never submitted
    await client._cancel_order(_cancel_cmd(rig, command))
    assert rig.sender.cancels == []
    assert _names(rig).count("OrderCancelRejected") == 1
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_cancel_is_rejected_while_the_sender_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    command = await _submit_rest(rig, 0)
    client._order_sender = None
    await client._cancel_order(_cancel_cmd(rig, command))
    assert rig.sender.cancels == []
    assert "OrderCancelRejected" in _names(rig)
    assert json.loads(client._store_get(_INDEX_KEY)) == [_id_n(0)], "nothing retired"
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("write_canonical_unverified")
async def test_cancel_is_rejected_while_the_canonical_string_is_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The submit-chain module's own fixture pins the flag False (it is the one place
    allowed to set it); a cancel is then rejected before any POST."""
    enable_operator_gate(monkeypatch, order_count="2")
    with caps():
        rig = await _rig(tmp_path, monkeypatch)
        command = _rest_command(rig.client)
        await rig.client._cancel_order(_cancel_cmd(rig, command))
        assert rig.sender.cancels == []
        assert _names(rig).count("OrderCancelRejected") == 1
        assert rig.client.log_lines("error", "canonical string is unverified")
        await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_allowlist_failure_in_loop_latches_without_raise_or_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sec E2a: an id that fails ``valid_venue_order_id`` inside the loop is
    terminal-unconfirmable: CRITICAL + latch at once, no POST, no retry, no raise."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    unresolved = await asyncio.wait_for(client._cancel_resting_order(("bad/../id",)), 1.0)
    assert rig.sender.cancels == []
    assert unresolved == frozenset()
    assert [r.reason for r in client._trading_refusals] == [
        submit_chain.RESTING_CANCEL_UNCONFIRMED_REASON
    ]
    assert client.log_lines("error", "resting_cancel_unconfirmed")
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_slug_helper_returns_unscoped_unverified_while_pin_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch, pin=False)
    client = rig.client
    command = await _submit_rest(rig, 0)
    slug = submit_chain.build_resting_order_body(command.order, build_no_leg_instrument())[
        "marketSlug"
    ]
    assert await client._cancel_slug_orders(slug) == submit_chain.UNSCOPED_UNVERIFIED
    assert rig.sender.cancel_alls == []
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_slug_helper_refuses_empty_and_off_ledger_slug_and_posts_the_ledger_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch, pin=True)
    client = rig.client
    # an EMPTY ledger issues zero POSTs whatever the slug
    assert await client._cancel_slug_orders("tc-temp-nyc-x") == "REFUSED_OFF_LEDGER"
    command = await _submit_rest(rig, 0)
    slug = submit_chain.build_resting_order_body(command.order, build_no_leg_instrument())[
        "marketSlug"
    ]
    for bad in ("", "tc-temp-other", slug + "\n", None):
        assert await client._cancel_slug_orders(bad) == "REFUSED_OFF_LEDGER"
    assert rig.sender.cancel_alls == []
    assert await client._cancel_slug_orders(slug) == "POSTED"
    assert rig.sender.cancel_alls == [[slug]]
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_cancel_all_is_filtered_by_instrument_and_touches_only_ledger_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    await _submit_rest(rig, 0)
    await _submit_rest(rig, 1)
    # an UNBOUND open order on the account: never named by the strategy path
    client._private_read._payloads[client_module.OPEN_ORDERS_PATH] = {
        "orders": [{"id": "ZZZZZZZZZZZZ", "marketSlug": "tc-temp-x", "state": "ORDER_STATE_NEW"}]
    }
    _auto_cancel(rig)
    yes_id = build_instrument().id
    await client._cancel_all_orders(_cancel_all_cmd(rig, yes_id))
    assert rig.sender.cancels == [], "the YES instrument has no bound rest"
    no_id = build_no_leg_instrument().id
    await client._cancel_all_orders(_cancel_all_cmd(rig, no_id))
    assert sorted(c["order_id"] for c in rig.sender.cancels) == [_id_n(0), _id_n(1)]
    assert "ZZZZZZZZZZZZ" not in {c["order_id"] for c in rig.sender.cancels}
    assert rig.sender.cancel_alls == [], "no venue cancel-all from the strategy path"
    assert _names(rig).count("OrderCanceled") == 2
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_cancel_all_attempts_every_id_before_backoff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N-6: one POST+confirm attempt per pending id per pass, so a stuck head id
    cannot starve the rest."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    await _submit_rest(rig, 0)
    await _submit_rest(rig, 1)
    rig.sender.on_cancel = lambda oid: (
        _set_state(rig, 1, "ORDER_STATE_CANCELED") if oid == _id_n(1) else None
    )
    task = asyncio.ensure_future(
        client._cancel_all_orders(_cancel_all_cmd(rig, build_no_leg_instrument().id))
    )
    await asyncio.sleep(0.1)
    order = [c["order_id"] for c in rig.sender.cancels]
    assert order[:2] == [_id_n(0), _id_n(1)], order
    assert set(order[2:]) == {_id_n(0)}, "the terminal id left the pending set"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_two_concurrent_cancels_never_post_the_same_id_and_do_not_clear_each_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ARM D2 (arch H2): the second loop sees the id in ``_cancel_in_flight``, owns
    nothing, and its exit leaves the first loop's guard intact."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    command = await _submit_rest(rig, 0)
    first = asyncio.ensure_future(client._cancel_order(_cancel_cmd(rig, command)))
    await asyncio.sleep(0.02)
    posts_before = len(rig.sender.cancels)
    await asyncio.wait_for(
        client._cancel_all_orders(_cancel_all_cmd(rig, build_no_leg_instrument().id)), 1.0
    )
    assert _id_n(0) in client._cancel_in_flight, "not cleared by the other loop"
    # the second loop issued no POST of its own for the same id
    assert len(rig.sender.cancels) - posts_before <= 2
    _auto_cancel(rig)
    await asyncio.wait_for(first, 2.0)
    assert _names(rig).count("OrderCanceled") == 1
    assert client._cancel_in_flight == frozenset()
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_refused_cancel_alerts_before_the_latch_then_escalates_and_latches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch, pin=True)
    client = rig.client
    command = await _submit_rest(rig, 0)
    rig.sender.on_cancel = lambda _id: client.advance(400)  # the order stays open
    task = asyncio.ensure_future(client._cancel_order(_cancel_cmd(rig, command)))
    for _ in range(100):
        await asyncio.sleep(0.01)
        if client._trading_refusals:
            break
    assert [r.reason for r in client._trading_refusals] == [
        submit_chain.RESTING_CANCEL_UNCONFIRMED_REASON
    ]
    lines = [m for lv, m in client.log_records if lv == "error"]
    alert = next(i for i, m in enumerate(lines) if "resting_cancel_alert" in m)
    latch = next(i for i, m in enumerate(lines) if "resting_cancel_unconfirmed" in m)
    assert alert < latch, "the non-latching alert precedes the latch (property: r4 section 9)"
    assert rig.sender.cancel_alls, (
        "the unconfirmed cancel escalated to the slug cancel-all (pin True)"
    )
    assert client.resting_cancel_alerts, "the health surface carries the alert"
    # the cancels continue while latched, and a later terminal read clears the latch
    _auto_cancel(rig)
    rig.sender.on_cancel = lambda oid: _set_state(rig, 0, "ORDER_STATE_CANCELED")
    await asyncio.wait_for(task, 2.0)
    assert _names(rig).count("OrderCanceled") == 1
    assert client._trading_refusals == []
    assert client.resting_cancel_alerts == ()
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_no_latch_before_the_computed_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch, pin=True)
    client = rig.client
    command = await _submit_rest(rig, 0)
    task = asyncio.ensure_future(client._cancel_order(_cancel_cmd(rig, command)))
    await asyncio.sleep(0.1)
    assert client._trading_refusals == []
    assert rig.sender.cancel_alls == []
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_cancel_during_hold_by_with_id_context_never_retires_and_the_resolver_skips_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Item 2 of the B4 review: while a cancel loop owns a venue id the with-id
    resolver cannot bind it (or retire it); a context-target cancel never retires."""
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    command = _rest_command(client)
    rig.sender.response = VenueResponse(
        status=200, headers={}, body=json.dumps({"id": _id_n(0), "executions": []}).encode()
    )
    client._private_read._payloads[submit_chain.order_by_id_path(_id_n(0))] = _venue_order(
        command, id=_id_n(0), state="ORDER_STATE_PENDING_RISK"
    )
    await client._submit_order(command)  # HOLD: PENDING at the deadline
    held = client._latch.current_open()
    assert held is not None and "OrderAccepted" not in _names(rig)
    rig.sender.gate = asyncio.Event()
    task = asyncio.ensure_future(client._cancel_order(_cancel_cmd(rig, command)))
    await asyncio.sleep(0.02)
    assert _id_n(0) in client._cancel_in_flight
    # the order now reads a clean NEW: a resolver pass would BIND it, but must skip
    _payload(rig, 0).update({"state": "ORDER_STATE_NEW"})
    client._private_read.paths.clear()
    await run_passes(client, 1)
    assert submit_chain.order_by_id_path(_id_n(0)) not in client._private_read.paths
    assert "OrderAccepted" not in _names(rig)
    # release the cancel POST; the venue cancels; the loop must NOT retire the context
    _auto_cancel(rig)
    rig.sender.gate.set()
    await asyncio.wait_for(task, 2.0)
    assert client._cancel_in_flight == frozenset()
    assert client._latch.current_open() is not None, "the resolver owns context retirement"
    assert "OrderCanceled" not in _names(rig)
    await client._disconnect()


def test_retire_resting_row_is_synchronous_check_and_rewrite() -> None:
    """N-2(d): no ``await`` between the index read and its rewrite (one winner)."""
    import ast
    import inspect
    import textwrap

    source = textwrap.dedent(
        inspect.getsource(client_module.PolymarketUSExecutionClient._retire_resting_row)
    )
    tree = ast.parse(source)
    assert isinstance(tree.body[0], ast.FunctionDef), "a plain def, so it cannot await"
    assert not any(isinstance(n, ast.Await) for n in ast.walk(tree))


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_retire_resting_row_has_exactly_one_winner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    await _submit_rest(rig, 0)
    await _submit_rest(rig, 1)
    assert client._retire_resting_row(_id_n(0)) is True
    assert client._retire_resting_row(_id_n(0)) is False
    assert json.loads(client._store_get(_INDEX_KEY)) == [_id_n(1)]
    assert not client._store_get(f"{_ROW_PREFIX}{_id_n(0)}"), "tombstoned"
    assert client._retire_resting_row("ZZZZZZZZZZZZ") is False
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_unreadable_index_issues_zero_posts_and_keeps_the_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch, pin=True)
    client = rig.client
    command = await _submit_rest(rig, 0)
    client._store_set(_INDEX_KEY, b"{not json")
    await client._cancel_order(_cancel_cmd(rig, command))
    await client._cancel_all_orders(_cancel_all_cmd(rig, build_no_leg_instrument().id))
    assert await client._cancel_slug_orders("tc-temp-x") == "REFUSED_OFF_LEDGER"
    assert rig.sender.cancels == [] and rig.sender.cancel_alls == []
    assert client._trading_refusals, "the unreadable index refusal is kept (fail closed)"
    await client._disconnect()
