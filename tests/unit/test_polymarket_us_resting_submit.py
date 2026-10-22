"""S4 WP3 (ARM maker-sharp B4): the resting submit path, confirm, bind and ADOPT.

Plan: ``docs/plans/backlog/MAKER_2026-10-12/S4_exec_resting_order_path_plan_r4_delta.md``
section 2 WP3 and section 9; r3 WP3; ARM plan r2 delta D2.

The suite reaches every ``exec`` symbol through ``tests/unit/ambig_latch_rig.py``
(barrier X1 pins by set equality each test module that imports the ``exec``
package; this file adds no importer). No sender here can reach a network: every
sender and private read is a local double.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pytest
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import SubmitOrder
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.objects import Quantity

from tests.unit.ambig_latch_rig import (
    AmbiguousResolverContext,
    RaisingSender,
    RetirementReason,
    build_client,
    caps,
    client_module,
    gate_env,  # noqa: F401 -- used via usefixtures
    read_context,
    response_sender,
    run_passes,
    submit_chain,
    wire_payloads,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.polymarket_us_exec_shapes import build_no_leg_instrument
from tests.unit.test_current_rung_hold_pre_arm_race import (
    STRATEGY_ID,
    TRADER_ID,
)
from tests.unit.test_polymarket_us_permit_issuance import enable_operator_gate


def _context(**overrides: object) -> AmbiguousResolverContext:
    fields: dict[str, object] = {
        "intent_id": "I-1",
        "venue_order_id": "ABCDEF123456",
        "instrument_id": "TC-TEMP-X.POLYMARKET_US",
        "client_order_id": "O-1",
        "strategy_id": "WEATHER-001",
        "notional_usd": Decimal("0.40"),
        "booking_id": 1,
        "created_ns": 1_000,
        "wire_market_slug": "tc-temp-x",
        "wire_price": "0.60",
        "wire_outcome_side": "OUTCOME_SIDE_NO",
        "wire_action": "ORDER_ACTION_BUY",
        "wire_quantity": "1",
    }
    fields.update(overrides)
    return AmbiguousResolverContext(**fields)  # type: ignore[arg-type]


def test_resting_context_round_trips_the_flag_and_the_expiry() -> None:
    context = _context(resting=True, resting_expire_ns=1_787_620_813_123_456_789)
    decoded = AmbiguousResolverContext.from_bytes(context.to_bytes())
    assert decoded.resting is True
    assert decoded.resting_expire_ns == 1_787_620_813_123_456_789
    assert decoded == context


def test_ioc_resolver_context_bytes_are_unchanged() -> None:
    """The new keys are serialised ONLY for a resting context (IOC bytes frozen)."""
    payload = json.loads(_context().to_bytes())
    assert "resting" not in payload
    assert "restingExpireNs" not in payload


def test_absent_resting_key_decodes_false() -> None:
    """[CHAR] An old blob (no key) decodes ``resting=False``, ``resting_expire_ns=None``."""
    decoded = AmbiguousResolverContext.from_bytes(_context().to_bytes())
    assert decoded.resting is False
    assert decoded.resting_expire_ns is None


def test_resting_wire_echo_is_the_nine_key_body_view() -> None:
    context = _context(resting=True, resting_expire_ns=1_787_620_813_123_456_789)
    echo = context.resting_wire_echo
    assert echo is not None
    assert echo["marketSlug"] == "tc-temp-x"
    assert echo["price"]["value"] == "0.60"
    assert echo["tif"] == "TIME_IN_FORCE_GOOD_TILL_DATE"
    assert echo["goodTillTime"] == "2026-08-25T01:20:13Z"
    assert _context().resting_wire_echo is None


# ---------------------------------------------------------------------------
# The submit path
# ---------------------------------------------------------------------------

VENUE_ID: Final[str] = "ABCDEF123456"
NS_PER_S: Final[int] = 1_000_000_000
_RESTING_KEY_PREFIX: Final[str] = client_module.RESTING_KEY_PREFIX
_RESTING_INDEX_KEY: Final[str] = client_module.RESTING_INDEX_KEY


def _create_body(order_id: str = VENUE_ID) -> bytes:
    """The async create ack: 200 + id, nothing else (the venue confirms by GET)."""
    return json.dumps({"id": order_id, "executions": []}).encode("utf-8")


def _expire_ns(client: Any, *, seconds: int = 1_800) -> int:
    now = int(client._clock.timestamp_ns())
    day_end = (now // (86_400 * NS_PER_S) + 1) * 86_400 * NS_PER_S
    return min(now + seconds * NS_PER_S, day_end - 1)


#: ONE factory for the module: its counter de-dupes client order ids when a test
#: submits several orders.
_FACTORY: Final[OrderFactory] = OrderFactory(
    trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=LiveClock()
)


def _rest_command(client: Any, *, price: str = "0.40", tif: TimeInForce = TimeInForce.GTD) -> Any:
    """A BUY 1 GTD on the NO leg of the shared (daily-HIGH) market, cached the
    way the engine does before the client runs."""
    no = build_no_leg_instrument()
    factory = _FACTORY
    expire = (
        pd.Timestamp(_expire_ns(client), unit="ns", tz="UTC") if tif is TimeInForce.GTD else None
    )
    order = factory.limit(
        instrument_id=no.id,
        order_side=OrderSide.BUY,
        quantity=Quantity(1, no.size_precision),
        price=no.make_price(price),
        time_in_force=tif,
        expire_time=expire,
        post_only=False,
    )
    client._cache.add_order(order, position_id=None)
    return SubmitOrder(
        trader_id=TRADER_ID,
        strategy_id=STRATEGY_ID,
        order=order,
        command_id=UUID4(),
        ts_init=client._clock.timestamp_ns(),
    )


def _venue_order(command: Any, **overrides: Any) -> dict[str, Any]:
    """What ``GET /v1/order/{id}`` returns for the rest ``command`` posted."""
    no = build_no_leg_instrument()
    posted = submit_chain.build_resting_order_body(command.order, no)
    order: dict[str, Any] = {
        "id": VENUE_ID,
        "marketSlug": posted["marketSlug"],
        "side": "ORDER_SIDE_SELL",
        "intent": "ORDER_INTENT_BUY_SHORT",
        "type": posted["type"],
        "tif": posted["tif"],
        "state": "ORDER_STATE_NEW",
        "price": posted["price"],
        "quantity": posted["quantity"],
        "cumQuantity": 0,
        "leavesQuantity": posted["quantity"],
        "createTime": "2026-08-25T00:00:14.120237895Z",
        "goodTillTime": posted["goodTillTime"],
        "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
    }
    order.update(overrides)
    return {"order": order}


class _Rig:
    """A built client, its sender and a way to script ``GET /v1/order/{id}``."""

    def __init__(self, client: Any, sender: Any, events: list[Any]) -> None:
        self.client = client
        self.sender = sender
        self.events = events

    def set_get(self, payload: dict[str, Any]) -> None:
        wire_payloads(self.client)[submit_chain.order_by_id_path(VENUE_ID)] = payload

    def event_names(self) -> list[str]:
        return [type(e).__name__ for e in self.events]

    def intent(self) -> Any:
        return self.client._latch.current()


async def _rig(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    create_body: bytes | None = None,
    admitted: bool = True,
    gtd_verified: bool = True,
    fast_confirm: bool = True,
) -> _Rig:
    monkeypatch.setattr(submit_chain, "GTD_EXPIRY_VERIFIED", gtd_verified)
    if fast_confirm:
        # A 20 ms deadline and a 1 ms poll keep the not-NEW cases fast.
        monkeypatch.setattr(submit_chain, "RESTING_CONFIRM_DEADLINE_NS", 20_000_000)
        monkeypatch.setattr(submit_chain, "RESTING_CONFIRM_POLL_S", 0.001)
    sender = response_sender(200, _create_body() if create_body is None else create_body)
    client, events, _permit, _latch_cm = await build_client(tmp_path, monkeypatch, sender=sender)
    client._resting_accept_admitted = admitted
    no = build_no_leg_instrument()
    client._cache.add_instrument(no)
    client._instrument_provider.add(no)
    return _Rig(client, sender, events)


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_resting_submit_refused_until_supervisor_admits_accepted_resting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WP2 deferred: without the supervisor's ACCEPTED_RESTING admission a rest is
    denied before any venue contact, the latch never arms, nothing is spent."""
    rig = await _rig(tmp_path, monkeypatch, admitted=False)
    command = _rest_command(rig.client)
    await rig.client._submit_order(command)
    assert rig.sender.calls == []
    assert "OrderDenied" in rig.event_names()
    assert rig.intent() is None
    assert rig.client._resting_accept_admitted is False
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_resting_submit_refused_while_gtd_expiry_is_unverified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch, gtd_verified=False)
    await rig.client._submit_order(_rest_command(rig.client))
    assert rig.sender.calls == []
    assert "OrderDenied" in rig.event_names()
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_confirm_new_binds_and_retires_accepted_resting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    command = _rest_command(rig.client)
    rig.set_get(_venue_order(command))
    await rig.client._submit_order(command)
    client = rig.client
    assert len(rig.sender.calls) == 1
    body = json.loads(rig.sender.calls[0]["body"])
    assert set(body) == set(submit_chain.RESTING_ORDER_BODY_KEYS)
    assert body["tif"] == "TIME_IN_FORCE_GOOD_TILL_DATE"
    assert rig.event_names()[-2:] == ["OrderSubmitted", "OrderAccepted"]
    # K=1 released: the slot is retired ACCEPTED_RESTING, nothing left open.
    assert client._latch.open_slot_count() == 0
    assert client._trading_refusals == []
    # The binding row and the index entry are durable; the booking is held.
    assert json.loads(client._store_get(_RESTING_INDEX_KEY)) == [VENUE_ID]
    row = json.loads(client._store_get(f"{_RESTING_KEY_PREFIX}{VENUE_ID}"))
    assert row["slug"] == body["marketSlug"]
    assert row["clientOrderId"] == command.order.client_order_id.value
    assert VENUE_ID in client._resting_bookings
    assert VENUE_ID in client._this_process_resting_ids
    assert client._post_in_flight_intent_ids == frozenset()
    assert client._ledger.has_open_exposure(row["intentId"])
    assert client._resolver_error_count == 0
    assert RetirementReason.ACCEPTED_RESTING.value == "ACCEPTED_RESTING"
    await client._disconnect()


def _fail(*_args: Any, **_kwargs: Any) -> Any:
    raise AssertionError("must not be called")


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_async_create_200_with_id_does_not_accept_until_get_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[CHAR] A 200+id (even one echoing a NEW-looking body) never accepts by itself:
    with the GET still PENDING at the deadline the order is HELD, not accepted."""
    body = json.dumps({"id": VENUE_ID, "state": "ORDER_STATE_NEW", "executions": []}).encode()
    rig = await _rig(tmp_path, monkeypatch, create_body=body)
    command = _rest_command(rig.client)
    rig.set_get(_venue_order(command, state="ORDER_STATE_PENDING_RISK"))
    await rig.client._submit_order(command)
    assert "OrderAccepted" not in rig.event_names()
    assert rig.client._latch.open_slot_count() == 1
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_confirm_pending_at_deadline_holds_and_keeps_slot_and_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    command = _rest_command(rig.client)
    rig.set_get(_venue_order(command, state="ORDER_STATE_PENDING_RISK"))
    await rig.client._submit_order(command)
    client = rig.client
    intent = rig.intent()
    assert intent is not None and intent.state.name == "OPEN"
    assert client._latch.open_slot_count() == 1
    assert client._ledger.has_open_exposure(intent.intent_id)
    assert intent.intent_id in client._ambiguous_bookings
    assert [r.reason for r in client._trading_refusals] == [submit_chain.AMBIGUOUS_REASON]
    assert client._store_get(_RESTING_INDEX_KEY) is None
    assert client._post_in_flight_intent_ids == frozenset()
    await client._disconnect()


@pytest.mark.parametrize(
    "overrides",
    [
        {"state": "ORDER_STATE_FILLED", "cumQuantity": 1, "leavesQuantity": 0},
        {"state": "ORDER_STATE_PARTIALLY_FILLED", "cumQuantity": 0.5, "leavesQuantity": 0.5},
        {"state": "ORDER_STATE_CANCELED", "leavesQuantity": 0},
        {"state": "ORDER_STATE_REJECTED", "leavesQuantity": 0},
    ],
    ids=["filled", "partial", "canceled", "rejected"],
)
@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_confirm_non_new_state_holds_and_books_nothing_inline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any]
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    command = _rest_command(rig.client)
    rig.set_get(_venue_order(command, **overrides))
    await rig.client._submit_order(command)
    client = rig.client
    names = rig.event_names()
    assert "OrderAccepted" not in names and "OrderFilled" not in names
    assert client._latch.open_slot_count() == 1
    assert client._store_get(_RESTING_INDEX_KEY) is None
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_confirm_unreadable_get_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    command = _rest_command(rig.client)
    # No payload registered for the GET path: the stub raises KeyError every poll.
    await rig.client._submit_order(command)
    assert "OrderAccepted" not in rig.event_names()
    assert rig.client._latch.open_slot_count() == 1
    await rig.client._disconnect()


@pytest.mark.parametrize(
    "overrides",
    [
        {"price": {"value": "0.61", "currency": "USD"}},
        {"tif": "TIME_IN_FORCE_GOOD_TILL_CANCEL"},
        {"quantity": 2, "leavesQuantity": 2},
        {"goodTillTime": "2031-01-01T00:00:00Z"},
    ],
    ids=["price", "tif", "quantity", "good-till-time"],
)
@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_confirm_echo_mismatch_or_non_gtd_tif_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overrides: dict[str, Any]
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    command = _rest_command(rig.client)
    rig.set_get(_venue_order(command, **overrides))
    await rig.client._submit_order(command)
    assert "OrderAccepted" not in rig.event_names()
    assert rig.client._latch.open_slot_count() == 1
    await rig.client._disconnect()


@pytest.mark.parametrize("indicator", ["MANUAL_ORDER_INDICATOR_MANUAL", None])
@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_confirm_never_binds_a_manual_or_unmarked_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, indicator: str | None
) -> None:
    """B4 review F2 (inline bind path): an order the venue marks MANUAL, or does not
    mark at all, is HELD for the resolver, never bound as the bot's own rest."""
    rig = await _rig(tmp_path, monkeypatch)
    command = _rest_command(rig.client)
    payload = _venue_order(command)
    if indicator is None:
        del payload["order"]["manualOrderIndicator"]
    else:
        payload["order"]["manualOrderIndicator"] = indicator
    rig.set_get(payload)
    await rig.client._submit_order(command)
    client = rig.client
    assert "OrderAccepted" not in rig.event_names()
    assert client._store_get(_RESTING_INDEX_KEY) is None
    assert client._latch.open_slot_count() == 1
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_resolver_never_binds_a_manual_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B4 review F2 (resolver bind path)."""
    rig, command, _intent_id = await _held_rest(tmp_path, monkeypatch)
    client = rig.client
    payload = _venue_order(command)
    payload["order"]["manualOrderIndicator"] = "MANUAL_ORDER_INDICATOR_MANUAL"
    rig.set_get(payload)
    await run_passes(client, 2)
    assert "OrderAccepted" not in rig.event_names()
    assert client._store_get(_RESTING_INDEX_KEY) is None
    assert client._latch.open_slot_count() == 1
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_bind_refuses_id_outside_allowlist_and_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An id outside ``[A-Z0-9]{12}`` is never GET-confirmed and never bound."""
    rig = await _rig(tmp_path, monkeypatch, create_body=_create_body("bad id\n"))
    command = _rest_command(rig.client)
    await rig.client._submit_order(command)
    client = rig.client
    assert not any(p.startswith("/v1/order/") for p in client._private_read.paths)
    assert "OrderAccepted" not in rig.event_names()
    assert client._store_get(_RESTING_INDEX_KEY) is None
    assert client._latch.open_slot_count() == 1
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_with_id_resting_context_written_before_confirm_awaits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    command = _rest_command(rig.client)
    client = rig.client
    seen: list[Any] = []
    real_read = client._private_read

    async def spying_read(path: str, query: Any = None) -> Any:
        if path.startswith("/v1/order/"):
            intent = client._latch.current()
            seen.append(read_context(client, intent.intent_id))
            seen.append(client._post_in_flight_intent_ids)
        return await real_read(path, query)

    rig.set_get(_venue_order(command))
    spying_read._payloads = real_read._payloads  # type: ignore[attr-defined]
    spying_read.paths = real_read.paths  # type: ignore[attr-defined]
    client._private_read = spying_read
    await client._submit_order(command)
    context, in_flight = seen[0], seen[1]
    assert context.venue_order_id == VENUE_ID
    assert context.resting is True
    assert context.resting_expire_ns == command.order.expire_time_ns
    assert context.intent_id in in_flight
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_pre_post_context_carries_resting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash between POST and the with-id write is adopted by the no-id path and
    then bound by the with-id resolver: the PRE-POST context must say resting.
    (A POST that raises leaves exactly the pre-POST context; no alias of the
    sender's ``post_order`` is taken here -- the B9 one-caller scan follows aliases.)"""
    rig = await _rig(tmp_path, monkeypatch)
    rig.client._order_sender = RaisingSender()
    command = _rest_command(rig.client)
    await rig.client._submit_order(command)
    intent = rig.intent()
    assert intent is not None
    context = read_context(rig.client, intent.intent_id)
    assert context.venue_order_id == submit_chain.NO_VENUE_ORDER_ID
    assert context.resting is True
    assert context.resting_expire_ns == command.order.expire_time_ns
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_hold_context_rewrite_keeps_resting_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    command = _rest_command(rig.client)
    rig.set_get(_venue_order(command, state="ORDER_STATE_PENDING_RISK"))
    await rig.client._submit_order(command)
    context = read_context(rig.client, rig.intent().intent_id)
    assert context.venue_order_id == VENUE_ID
    assert context.resting is True
    assert context.resting_expire_ns == command.order.expire_time_ns
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_stop_during_confirm_leaves_context_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    command = _rest_command(rig.client)
    client = rig.client

    async def cancelled_read(path: str, query: Any = None) -> Any:
        del query
        if path.startswith("/v1/order/"):
            raise asyncio.CancelledError
        return {}

    cancelled_read._payloads = {}  # type: ignore[attr-defined]
    cancelled_read.paths = []  # type: ignore[attr-defined]
    client._private_read = cancelled_read
    with pytest.raises(asyncio.CancelledError):
        await client._submit_order(command)
    intent = client._latch.current()
    assert intent is not None and intent.state.name == "OPEN"
    context = read_context(client, intent.intent_id)
    assert context is not None and context.resting is True
    assert context.venue_order_id == VENUE_ID
    assert client._post_in_flight_intent_ids == frozenset()
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_hung_confirm_get_is_bounded_by_the_deadline_and_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B4 review F3: a GET that never answers must not hold the coroutine past the
    confirm deadline. HOLD semantics: slot and budget kept, nothing bound."""
    rig = await _rig(tmp_path, monkeypatch)
    command = _rest_command(rig.client)
    client = rig.client
    hang = asyncio.Event()

    async def hung_read(path: str, query: Any = None) -> Any:
        del query
        if path.startswith("/v1/order/"):
            await hang.wait()
        return {}

    hung_read._payloads = {}  # type: ignore[attr-defined]
    hung_read.paths = []  # type: ignore[attr-defined]
    client._private_read = hung_read
    await asyncio.wait_for(client._submit_order(command), timeout=2.0)
    intent = rig.intent()
    assert intent is not None and intent.state.name == "OPEN"
    assert client._latch.open_slot_count() == 1
    assert client._ledger.has_open_exposure(intent.intent_id)
    assert intent.intent_id in client._ambiguous_bookings
    assert "OrderAccepted" not in rig.event_names()
    assert client._store_get(_RESTING_INDEX_KEY) is None
    assert client._post_in_flight_intent_ids == frozenset()
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_binder_failure_holds_and_logs_the_exception_type_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B4 review F4: the binder runs outside the POST/confirm ``try``; an exception
    from it (a failing store write) must HOLD, not escape ``_submit_order``, and the
    log carries the exception TYPE only, never its message."""
    rig = await _rig(tmp_path, monkeypatch)
    command = _rest_command(rig.client)
    client = rig.client
    real_store_set = client._store_set

    def faulty_store_set(key: str, value: bytes) -> None:
        if key.startswith(_RESTING_KEY_PREFIX):
            raise RuntimeError("SECRET-STORE-DETAIL")
        real_store_set(key, value)

    monkeypatch.setattr(client, "_store_set", faulty_store_set)
    rig.set_get(_venue_order(command))
    await client._submit_order(command)
    intent = rig.intent()
    assert intent is not None and intent.state.name == "OPEN"
    assert client._latch.open_slot_count() == 1
    assert client._ledger.has_open_exposure(intent.intent_id)
    assert intent.intent_id in client._ambiguous_bookings
    assert "OrderAccepted" not in rig.event_names()
    assert client._store_get(_RESTING_INDEX_KEY) is None
    assert client._post_in_flight_intent_ids == frozenset()
    lines = [m for _lv, m in client.log_records]
    assert any("RuntimeError" in m for m in lines)
    assert not any("SECRET-STORE-DETAIL" in m for m in lines)
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_binder_retires_and_releases_the_slot_when_the_order_is_not_in_the_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B4 review F7 [CHAR]: a context whose order is absent from this run's cache
    (a restart) still binds, retires ACCEPTED_RESTING and releases K=1, emitting
    no event."""
    import dataclasses

    rig, _command, intent_id = await _held_rest(tmp_path, monkeypatch)
    client = rig.client
    context = read_context(client, intent_id)
    assert context is not None
    missing = dataclasses.replace(context, client_order_id="O-NOT-IN-CACHE")
    events_before = rig.event_names()
    assert client._bind_resting_order(missing, VENUE_ID, client._clock.timestamp_ns()) is True
    assert rig.event_names() == events_before
    assert client._latch.open_slot_count() == 0
    assert json.loads(client._store_get(_RESTING_INDEX_KEY)) == [VENUE_ID]
    assert VENUE_ID in client._resting_bookings
    assert client.log_lines("warning", "not in this run's cache")
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_binder_allowlist_refusal_logs_the_redacted_client_order_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B4 review F7: the allowlist-fail line names the client order id (redacted
    like every other id) and never the offending venue id."""
    import dataclasses

    rig, _command, intent_id = await _held_rest(tmp_path, monkeypatch)
    client = rig.client
    context = read_context(client, intent_id)
    assert context is not None
    unique = dataclasses.replace(context, client_order_id="O-ABCDEFGHIJKLMNOP")
    assert client._bind_resting_order(unique, "bad id\n", client._clock.timestamp_ns()) is False
    (line,) = client.log_lines("error", "resting bind: refused")
    assert client_module._redact_order_id("O-ABCDEFGHIJKLMNOP") in line
    assert "O-ABCDEFGHIJKLMNOP" not in line
    assert "bad id" not in line
    await client._disconnect()


def test_hold_writes_follow_the_finally_without_an_await() -> None:
    """N-8: every ``await`` in ``_submit_order`` sits inside the one POST/confirm
    ``try`` -- so nothing suspends between its ``finally`` and the HOLD writes."""
    import ast
    import inspect
    import textwrap

    source = textwrap.dedent(
        inspect.getsource(client_module.PolymarketUSExecutionClient._submit_order)
    )
    fn = ast.parse(source).body[0]
    tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try) and n.finalbody]
    post_tries = [t for t in tries if "post_order" in ast.unparse(t)]
    assert len(post_tries) == 1
    inside = {id(n) for n in ast.walk(post_tries[0])}
    awaits = [n for n in ast.walk(fn) if isinstance(n, ast.Await)]
    assert awaits, "the scan must see the POST and confirm awaits (non-vacuity)"
    assert all(id(a) in inside for a in awaits)
    assert any("_confirm_resting_order" in ast.unparse(a) for a in awaits)


# ---------------------------------------------------------------------------
# The with-id resolver and the binder's other callers
# ---------------------------------------------------------------------------


async def _held_rest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[_Rig, Any, str]:
    """A rest whose confirm HELD (GET still PENDING at the deadline): OPEN
    intent, with-id resting context, AMBIGUOUS refusal latched, booking held."""
    rig = await _rig(tmp_path, monkeypatch)
    command = _rest_command(rig.client)
    rig.set_get(_venue_order(command, state="ORDER_STATE_PENDING_RISK"))
    await rig.client._submit_order(command)
    intent = rig.intent()
    assert intent is not None
    return rig, command, intent.intent_id


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_crash_between_post_and_confirm_resolves_via_with_id_resolver_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, command, intent_id = await _held_rest(tmp_path, monkeypatch)
    client = rig.client
    rig.set_get(_venue_order(command))  # the venue now shows the clean NEW
    await run_passes(client, 1)
    assert client._latch.open_slot_count() == 0
    assert rig.event_names().count("OrderAccepted") == 1
    assert json.loads(client._store_get(_RESTING_INDEX_KEY)) == [VENUE_ID]
    assert VENUE_ID in client._resting_bookings
    assert client._resting_bookings[VENUE_ID][0] == intent_id
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_resolver_binds_accepted_resting_context_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, command, _intent_id = await _held_rest(tmp_path, monkeypatch)
    client = rig.client
    rig.set_get(_venue_order(command))
    await run_passes(client, 3)
    assert rig.event_names().count("OrderAccepted") == 1
    assert json.loads(client._store_get(_RESTING_INDEX_KEY)) == [VENUE_ID]
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_resolver_bind_clears_ambiguous_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, command, _intent_id = await _held_rest(tmp_path, monkeypatch)
    client = rig.client
    assert [r.reason for r in client._trading_refusals] == [submit_chain.AMBIGUOUS_REASON]
    rig.set_get(_venue_order(command))
    await run_passes(client, 1)
    assert client._trading_refusals == []
    assert client._ambiguous_refusal_clears == 1
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_resolver_bind_does_not_clear_refusal_while_another_intent_ambiguous(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E3: the binder clears the GLOBAL refusal only when it was the sole open
    AMBIGUOUS intent (the A3 predicate). Another open slot keeps it."""
    rig, command, _intent_id = await _held_rest(tmp_path, monkeypatch)
    client = rig.client
    monkeypatch.setattr(client._latch, "open_slot_count", lambda: 1)
    rig.set_get(_venue_order(command))
    await run_passes(client, 1)
    assert "OrderAccepted" in rig.event_names()
    assert [r.reason for r in client._trading_refusals] == [submit_chain.AMBIGUOUS_REASON]
    assert client._ambiguous_refusal_clears == 0
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_with_id_resolver_skips_in_flight_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, command, intent_id = await _held_rest(tmp_path, monkeypatch)
    client = rig.client
    rig.set_get(_venue_order(command))
    before = [p for p in client._private_read.paths if p.startswith("/v1/order/")]
    client._post_in_flight_intent_ids = frozenset({intent_id})
    await run_passes(client, 2)
    after = [p for p in client._private_read.paths if p.startswith("/v1/order/")]
    assert after == before
    assert "OrderAccepted" not in rig.event_names()
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_resolver_does_not_bind_while_cancel_in_flight(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, command, _intent_id = await _held_rest(tmp_path, monkeypatch)
    client = rig.client
    rig.set_get(_venue_order(command))
    client._cancel_in_flight = frozenset({VENUE_ID})
    await run_passes(client, 2)
    assert "OrderAccepted" not in rig.event_names()
    assert client._latch.open_slot_count() == 1
    client._cancel_in_flight = frozenset()
    await run_passes(client, 1)
    assert "OrderAccepted" in rig.event_names()
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_resting_index_three_way_read_unreadable_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable index binds nothing (it would otherwise be overwritten by a
    single entry, silently deleting every id it still held): the order is HELD."""
    rig = await _rig(tmp_path, monkeypatch)
    command = _rest_command(rig.client)
    rig.client._store_set(_RESTING_INDEX_KEY, b"{not json")
    rig.set_get(_venue_order(command))
    await rig.client._submit_order(command)
    client = rig.client
    assert "OrderAccepted" not in rig.event_names()
    assert client._store_get(f"{_RESTING_KEY_PREFIX}{VENUE_ID}") is None
    assert client._store_get(_RESTING_INDEX_KEY) == b"{not json"
    assert client._latch.open_slot_count() == 1
    assert VENUE_ID not in client._resting_bookings
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_accept_resting_does_not_count_as_registry_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    command = _rest_command(rig.client)
    rig.set_get(_venue_order(command))
    await rig.client._submit_order(command)
    assert rig.client._resolver_error_count == 0
    assert not rig.client.log_lines("error", "still registered")
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_other_retire_with_open_entry_still_counts_as_leak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, _command, intent_id = await _held_rest(tmp_path, monkeypatch)
    client = rig.client
    assert client._ledger.has_open_exposure(intent_id)
    client._retire(intent_id, submit_chain.RETIRE_ZERO_FILL, client._clock.timestamp_ns())
    assert client._resolver_error_count == 1
    assert client.log_lines("error", "still registered")
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_ioc_submit_path_still_posts_the_ten_key_ioc_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[CHAR] An IOC order never takes the resting branch, with or without the
    admission flag."""
    from tests.unit.ambig_latch_rig import make_command

    for admitted in (False, True):
        rig = await _rig(tmp_path / f"a{admitted}", monkeypatch, admitted=admitted)
        (tmp_path / f"a{admitted}").mkdir(exist_ok=True)
        await rig.client._submit_order(make_command(rig.client))
        assert len(rig.sender.calls) == 1
        body = json.loads(rig.sender.calls[0]["body"])
        assert set(body) == set(submit_chain.ORDER_BODY_KEYS)
        assert body["tif"] == "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL"
        await rig.client._disconnect()


# ---------------------------------------------------------------------------
# Many orders under K=1, headroom, taker-on-create
# ---------------------------------------------------------------------------


def _id_n(n: int) -> str:
    return f"ABCDEF12345{n}"


async def _submit_rest(rig: _Rig, n: int) -> Any:
    """Submit one more rest with venue id ``_id_n(n)`` (the K=1 latch is free)."""
    rig.sender.response = response_sender(200, _create_body(_id_n(n))).response
    command = _rest_command(rig.client)
    rig.client._private_read._payloads[submit_chain.order_by_id_path(_id_n(n))] = _venue_order(
        command, id=_id_n(n)
    )
    await rig.client._submit_order(command)
    return command


@pytest.mark.asyncio
@pytest.mark.usefixtures("write_canonical_verified")
async def test_eight_resting_orders_coexist_with_k1_and_a_ninth_is_refused_by_the_permit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Eight binds in a row, each releasing the single slot; the ninth is refused by
    the permit's order count (fixture caps only), NOT by the latch, and never POSTs."""
    enable_operator_gate(monkeypatch, order_count="8")
    with caps():
        rig = await _rig(tmp_path, monkeypatch)
        for n in range(8):
            await _submit_rest(rig, n)
            assert rig.client._latch.open_slot_count() == 0, n
        client = rig.client
        assert json.loads(client._store_get(_RESTING_INDEX_KEY)) == [_id_n(n) for n in range(8)]
        assert sorted(client._resting_bookings) == [_id_n(n) for n in range(8)]
        assert all(
            client._ledger.has_open_exposure(intent_id)
            for intent_id, _booking in client._resting_bookings.values()
        )
        assert len(rig.sender.calls) == 8
        assert rig.event_names().count("OrderAccepted") == 8
        await _submit_rest(rig, 8)
        assert len(rig.sender.calls) == 8, "the ninth never reaches the venue"
        assert rig.event_names().count("OrderAccepted") == 8
        assert "OrderDenied" in rig.event_names()
        assert client._latch.open_slot_count() == 0, "denied, so the latch was never armed"
        await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_resting_accept_does_not_double_register_exposure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The arm-time registration is the ONLY one: binding registers nothing more
    (a second `register_open_exposure` for the same intent would raise)."""
    rig = await _rig(tmp_path, monkeypatch)
    calls: list[str] = []
    ledger_type = type(rig.client._ledger)
    real = ledger_type.register_open_exposure

    def counting(self: Any, intent_id: str, *args: Any, **kwargs: Any) -> Any:
        calls.append(intent_id)
        return real(self, intent_id, *args, **kwargs)

    monkeypatch.setattr(ledger_type, "register_open_exposure", counting)
    command = _rest_command(rig.client)
    rig.set_get(_venue_order(command))
    await rig.client._submit_order(command)
    assert len(calls) == 1
    assert rig.client._resolver_error_count == 0
    await rig.client._disconnect()


def _crossed_create_body(command: Any) -> bytes:
    """A create response that already carries the fill (the rest crossed)."""
    import time

    from tests.unit.polymarket_us_exec_shapes import build_execution, build_order
    from tests.unit.test_polymarket_us_submit_order_chain import _rfc3339_nanos_utc

    posted = submit_chain.build_resting_order_body(command.order, build_no_leg_instrument())
    order = build_order(posted["marketSlug"])
    order.update(
        {
            "id": VENUE_ID,
            "side": "ORDER_SIDE_SELL",
            "intent": "ORDER_INTENT_BUY_SHORT",
            "tif": "TIME_IN_FORCE_GOOD_TILL_DATE",
            "quantity": 1,
            "cumQuantity": 1,
            "leavesQuantity": 0,
            "state": "ORDER_STATE_FILLED",
            "price": posted["price"],
            "avgPx": posted["price"],
        }
    )
    execution = build_execution(order)
    execution["lastShares"] = "1"
    execution["lastPx"] = posted["price"]
    execution["commissionNotionalCollected"] = {"value": "0.03", "currency": "USD"}
    execution["transactTime"] = _rfc3339_nanos_utc(time.time_ns())
    return json.dumps({"id": VENUE_ID, "executions": [execution]}).encode("utf-8")


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_create_fill_on_resting_shape_is_taker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rest that crossed at create time is booked as today, as a TAKER fill (spec
    section 3: counted separately), with a WARN naming `resting_order_crossed`; it is
    never bound and never retired ACCEPTED_RESTING."""
    rig = await _rig(tmp_path, monkeypatch)
    command = _rest_command(rig.client)
    rig.sender.response = response_sender(200, _crossed_create_body(command)).response
    await rig.client._submit_order(command)
    fills = [e for e in rig.events if type(e).__name__ == "OrderFilled"]
    assert len(fills) == 1
    assert fills[0].liquidity_side.name == "TAKER"
    assert rig.client.log_lines("warning", "resting_order_crossed")
    assert "OrderAccepted" not in rig.event_names()
    assert rig.client._store_get(_RESTING_INDEX_KEY) is None
    assert rig.client._latch.open_slot_count() == 0
    await rig.client._disconnect()
