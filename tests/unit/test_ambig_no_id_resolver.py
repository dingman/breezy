"""AMBIG-LATCH-RESUME Phase B: the automated no-id resolver (T26-T40, T49-T51).

Authority: ``docs/plans/backlog/BACKLOG_PLANS_2026-10-03/
AMBIG-LATCH-RESUME_plan_r6.md`` section 2.8 and 3.2.

A no-id AMBIGUOUS (an exception from ``post_order``, or a classified response
with no venue id) used to need the operator. These tests drive the REAL
resolver coroutine and the REAL ``_submit_order`` through
``tests/unit/ambig_latch_rig.py`` (no ``exec`` import here: barrier X1).

Two rig modes, deliberately:

* the REAL flow (``_no_id_take``): ``_submit_order`` writes the pre-POST
  context itself; the clock is moved with ``TimedClient.advance``;
* HAND-BUILT intents (``arm_context``): exact ``created_ns``/baseline control,
  for the tests whose point is a boundary or a cross-process shape.

The clock is real plus an offset, so no assertion sits within a few
milliseconds of a boundary; the exact boundaries are pinned on the constants.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import pytest
from nautilus_trader.model.events import OrderDenied, OrderFilled, OrderRejected, OrderSubmitted
from nautilus_trader.model.identifiers import ClientOrderId

from breezy.adapters.polymarket_us.safety import live_trading_budget_remaining
from breezy.runtime.component_health_watch import install_component_degraded_alert
from breezy.runtime.health import AlertPayload
from tests.unit.ambig_latch_rig import (
    IOC,
    OPEN_ORDERS_PATH,
    PORTFOLIO_ACTIVITIES_PATH,
    PORTFOLIO_POSITIONS_PATH,
    RESOLVER_CONTEXT_KEY_PREFIX,
    SEC_NS,
    AmbiguousResolverContext,
    PolymarketUSExecutionClient,
    RaisingSender,
    SubmitIntentState,
    TimedClient,
    arm_context,
    boot_second_process,
    build_client,
    client_module,
    gate_env,  # noqa: F401 -- fixture
    make_command,
    prior_process,
    read_context,
    read_paths,
    response_sender,
    rig_slug,
    run_passes,
    submit_chain,
    trade_row,
    wire_payloads,
    write_canonical_verified,  # noqa: F401 -- fixture
    write_evidence,
)
from tests.unit.polymarket_us_exec_shapes import build_instrument, build_no_leg_instrument
from tests.unit.test_current_rung_hold_ambiguous_resolver import (
    _ambiguous_create_body,
    _order_get_body,
    _run_exactly_one_pass,
)

SLUG = rig_slug()
ORDER_X = "ord-found-X"
AMBIGUOUS = submit_chain.AMBIGUOUS_REASON
CONTRADICTION_EVENT = "resolver_evidence_contradiction"
HOLDING_NEXT = "no_id_recheck_60s_manual_reconcile_then_launch_after_market_resolution"


class _Sink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


# ---------------------------------------------------------------------------
# Rig helpers
# ---------------------------------------------------------------------------


def _negative(
    client: Any,
    *,
    positions: dict[str, Any] | None = None,
    activities: list[Any] | None = None,
    open_orders: list[Any] | None = None,
) -> None:
    payloads = wire_payloads(client)
    payloads[PORTFOLIO_POSITIONS_PATH] = {"positions": positions or {}, "eof": True}
    payloads[PORTFOLIO_ACTIVITIES_PATH] = {"activities": activities or [], "eof": True}
    payloads[OPEN_ORDERS_PATH] = {"orders": open_orders or []}


async def _no_id_take(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: str = "exception",
    admitted: bool | None = True,
    before_take: Any = None,
) -> tuple[TimedClient, Any, Any, Any, list[Any]]:
    """One REAL no-id AMBIGUOUS take. Returns (client, current_intent, cmd,
    sender, order_events)."""
    sender: Any
    if mode == "exception":
        sender = RaisingSender()
    elif mode == "empty200":
        sender = response_sender(200, b"{}")
    elif mode == "html502":
        sender = response_sender(502, b"<html>bad gateway</html>")
    else:
        sender = response_sender(200, b"not json at all")
    client, events, _permit, _cm = await build_client(
        tmp_path, monkeypatch, sender=sender, admitted=admitted, start=True
    )
    _negative(client)
    if before_take is not None:
        before_take(client)
    command = make_command(client)
    await client._submit_order(command)
    current = client._latch.current_open()
    assert current is not None, "a no-id AMBIGUOUS leaves the intent OPEN"
    return client, current, command, sender, events


def _contradiction(client: Any, intent_id: str) -> dict[str, str]:
    return dict(client._resolver_contradiction_details[intent_id])


def _assert_no_operator_wording(client: Any) -> None:
    surfaces = [
        *client._resolver_contradiction_details.values(),
        *client._resolver_stale_alert_details.values(),
    ]
    for entry in surfaces:
        assert "operator" not in " ".join(entry.values()).lower(), entry
        if entry.get("event") in {CONTRADICTION_EVENT, "resolver_no_id_retire_blocked"}:
            assert entry.get("next"), entry


def _retirement(client: Any) -> str | None:
    current = client._latch.current()
    if current is None or current.state is not SubmitIntentState.RETIRED:
        return None
    assert current.retirement_reason is not None
    return str(current.retirement_reason.value)


def _echo_leg(ts_ns: int, order_id: str = ORDER_X, **kw: Any) -> dict[str, Any]:
    return trade_row(ts_ns=ts_ns, order_id=order_id, slug=SLUG, **kw)


def _open_ioc_order(created_ns: int, order_id: str = "open-1") -> dict[str, Any]:
    from tests.unit.ambig_latch_rig import ns_to_rfc3339

    return {
        "id": order_id,
        "marketSlug": SLUG,
        "state": "ORDER_STATE_NEW",
        "side": "ORDER_SIDE_BUY",
        "quantity": 1,
        "cumQuantity": 0,
        "tif": IOC,
        "createTime": ns_to_rfc3339(created_ns),
        "price": {"value": "0.40", "currency": "USD"},
    }


# ---------------------------------------------------------------------------
# T26-T30: the pre-POST context and the booking registrations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_post_context_is_durable_before_the_post_is_awaited(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    seen: dict[str, Any] = {}

    class _ProbeSender:
        client: Any = None
        calls: ClassVar[list[Any]] = []

        async def post_order(self, base_url: str, *, headers: Any, body: bytes) -> Any:
            current = self.client._latch.current_open()
            raw = self.client._store_get(f"{RESOLVER_CONTEXT_KEY_PREFIX}{current.intent_id}")
            seen["raw"] = raw
            seen["body"] = json.loads(body)
            seen["intent"] = current
            seen["bookings"] = dict(self.client._ambiguous_bookings)
            self.calls.append(body)
            return type(response_sender(200, b"{}").response)(status=200, headers={}, body=b"{}")

    sender = _ProbeSender()
    client, _ev, _permit, _cm = await build_client(tmp_path, monkeypatch, sender=sender)
    sender.client = client
    command = make_command(client)

    await client._submit_order(command)

    context = AmbiguousResolverContext.from_bytes(seen["raw"])
    body = seen["body"]
    assert context.venue_order_id == submit_chain.NO_VENUE_ORDER_ID == ""
    assert context.wire_market_slug == body["marketSlug"]
    assert context.wire_price == body["price"]["value"]
    assert context.wire_outcome_side == body["outcomeSide"]
    assert context.wire_action == body["action"]
    assert context.created_ns == seen["intent"].created_ns
    assert context.client_order_id == command.order.client_order_id.value
    assert context.intent_id not in seen["bookings"], "no booking is registered before the POST"
    await client._disconnect()


@pytest.mark.asyncio
async def test_a_pre_post_context_write_failure_denies_without_posting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    sender = RaisingSender()
    client, events, _permit, _cm = await build_client(tmp_path, monkeypatch, sender=sender)
    real_set = PolymarketUSExecutionClient._store_set

    def _failing_set(self: Any, key: str, value: bytes) -> None:
        if key.startswith(RESOLVER_CONTEXT_KEY_PREFIX):
            raise OSError("resolver-prefix write failed (rig)")
        real_set(self, key, value)

    monkeypatch.setattr(PolymarketUSExecutionClient, "_store_set", _failing_set)
    spent_before = client._ledger.spent_today_usd(now_ns=client._clock.timestamp_ns())

    await client._submit_order(make_command(client))

    assert sender.calls == [], "a context-write failure never POSTs"
    denied = [e for e in events if isinstance(e, OrderDenied)]
    assert [d.reason for d in denied] == [submit_chain.STORE_RAISED_REASON]
    assert client._ledger.spent_today_usd(now_ns=client._clock.timestamp_ns()) == spent_before
    assert client.trading_refusals == ()
    current = client._latch.current_open()
    assert current is not None, "the intent stays OPEN without a context"
    monkeypatch.undo()
    assert read_context(client, current.intent_id) is None
    await client._disconnect()


@pytest.mark.asyncio
async def test_exception_path_keeps_the_no_id_context_and_registers_the_booking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    # (a) a transport error
    client, current, _cmd, _sender, _ev = await _no_id_take(tmp_path / "a", monkeypatch)
    context = read_context(client, current.intent_id)
    assert context is not None and context.venue_order_id == ""
    assert AMBIGUOUS in client.trading_refusals
    assert client._ambiguous_bookings[current.intent_id] is not None
    assert client._post_in_flight_intent_id is None
    await client._disconnect()

    # (b) a CancelledError is re-raised, and the context + flag are consistent
    (tmp_path / "b").mkdir()
    client, _events, _permit, _cm = await build_client(
        tmp_path / "b",
        monkeypatch,
        sender=RaisingSender(asyncio.CancelledError()),
        start=True,
    )
    with pytest.raises(asyncio.CancelledError):
        await client._submit_order(make_command(client))
    current = client._latch.current_open()
    assert current is not None
    assert read_context(client, current.intent_id) is not None
    assert client._post_in_flight_intent_id is None
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["empty200", "html502", "nonjson200"])
async def test_classified_no_id_path_registers_the_booking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
    mode: str,
) -> None:
    client, current, _cmd, sender, _ev = await _no_id_take(tmp_path, monkeypatch, mode=mode)
    context = read_context(client, current.intent_id)
    assert context is not None and context.venue_order_id == ""
    assert AMBIGUOUS in client.trading_refusals
    assert client._ambiguous_bookings[current.intent_id] is not None
    assert client._post_in_flight_intent_id is None
    outcome = submit_chain.classify_create_order_outcome(
        sender.response,
        instrument=build_instrument(),
        account_id=client._issued_account_id,
        ts_init=0,
    )
    assert outcome.kind == submit_chain.KIND_AMBIGUOUS
    assert outcome.venue_order_id is None
    await client._disconnect()


@pytest.mark.asyncio
async def test_with_id_ambiguous_overwrites_the_pre_post_context_and_keeps_the_echo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    sender = response_sender(200, _ambiguous_create_body("ord-amb-9"))
    client, _ev, _permit, _cm = await build_client(tmp_path, monkeypatch, sender=sender)
    await client._submit_order(make_command(client))
    current = client._latch.current_open()
    assert current is not None
    context = read_context(client, current.intent_id)
    assert context is not None
    assert context.venue_order_id == "ord-amb-9"
    assert context.wire_market_slug == SLUG
    assert context.wire_price == "0.40"
    assert context.wire_outcome_side == "OUTCOME_SIDE_YES"
    assert context.wire_action == "ORDER_ACTION_BUY"
    assert client._ambiguous_bookings[current.intent_id] is not None
    await client._disconnect()


def test_an_old_context_blob_decodes_with_none_wire_fields() -> None:
    old = json.dumps(
        {
            "intentId": "i",
            "venueOrderId": "v",
            "instrumentId": "x",
            "clientOrderId": "c",
            "strategyId": "s",
            "notionalUsd": "1.00",
            "bookingId": 1,
            "createdNs": 5,
        },
        sort_keys=True,
    ).encode()
    context = AmbiguousResolverContext.from_bytes(old)
    assert context.wire_market_slug is None
    assert context.wire_price is None
    assert context.wire_outcome_side is None
    assert context.wire_action is None
    assert context.baseline_venue_net is None
    assert context.baseline_durable_net is None
    assert context.baseline_ts_ns is None


def test_a_context_with_an_empty_venue_id_round_trips() -> None:
    context = AmbiguousResolverContext(
        intent_id="i",
        venue_order_id="",
        instrument_id="x",
        client_order_id="c",
        strategy_id="s",
        notional_usd=Decimal("0.40"),
        booking_id=1,
        created_ns=5,
        wire_market_slug=SLUG,
        wire_price="0.40",
        wire_outcome_side="OUTCOME_SIDE_YES",
        wire_action="ORDER_ACTION_BUY",
        baseline_venue_net="2",
        baseline_durable_net="0",
        baseline_ts_ns=7,
    )
    again = AmbiguousResolverContext.from_bytes(context.to_bytes())
    assert again == context
    assert again.venue_order_id == ""


# ---------------------------------------------------------------------------
# T31-T32: in-flight guard, min age, constants, re-check cadence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_no_id_branch_skips_an_intent_whose_post_is_in_flight(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    gate = asyncio.Event()
    entered = asyncio.Event()

    class _GatedSender:
        calls: ClassVar[list[Any]] = []

        async def post_order(self, base_url: str, *, headers: Any, body: bytes) -> Any:
            entered.set()
            await gate.wait()
            raise OSError("transport died after the stall (rig)")

    client, _ev, _permit, _cm = await build_client(
        tmp_path, monkeypatch, sender=_GatedSender(), admitted=True, start=True
    )
    _negative(client)
    task = asyncio.get_event_loop().create_task(client._submit_order(make_command(client)))
    await asyncio.wait_for(entered.wait(), timeout=5)
    current = client._latch.current_open()
    assert current is not None
    assert client._post_in_flight_intent_id == current.intent_id
    client.advance(400)
    paths_before = read_paths(client)

    await run_passes(client, 1)

    new_paths = read_paths(client)[len(paths_before) :]
    assert PORTFOLIO_ACTIVITIES_PATH not in new_paths
    assert client._latch.current_open() is not None
    gate.set()
    await task
    assert client._post_in_flight_intent_id is None
    await client._disconnect()


def test_no_id_constants_are_pinned() -> None:
    cm = client_module
    assert cm._RESOLVER_NO_ID_MIN_AGE_NS >= cm._RESOLVER_ZERO_FILL_MIN_AGE_NS
    assert cm._RESOLVER_NO_ID_MIN_AGE_NS >= 300 * SEC_NS
    assert cm._NO_ID_WINDOW_BACKSKEW_NS >= 4 * 30 * SEC_NS
    assert cm._NO_ID_FATE_FIXED_NS == 65 * SEC_NS
    # the skew is a CHOICE (symmetric with the back-skew), not a derivation
    assert cm._NO_ID_WINDOW_FORWARD_SKEW_NS == 55 * SEC_NS
    assert cm._NO_ID_WINDOW_FORWARD_NS == cm._NO_ID_FATE_FIXED_NS + cm._NO_ID_WINDOW_FORWARD_SKEW_NS
    assert cm._NO_ID_WINDOW_FORWARD_NS == 120 * SEC_NS == cm._NO_ID_WINDOW_BACKSKEW_NS
    assert cm._RESOLVER_NO_ID_MIN_AGE_NS - cm._NO_ID_WINDOW_FORWARD_NS >= 180 * SEC_NS
    assert cm._NO_ID_MANUAL_STRADDLE_NS == 30 * SEC_NS
    assert cm._NO_ID_RECHECK_INTERVAL_NS == 60 * SEC_NS
    assert cm._NO_ID_BASELINE_QUIET_NS == 300 * SEC_NS


@pytest.mark.asyncio
async def test_no_id_branch_makes_no_read_below_the_min_age_and_reads_above_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, current, _cmd, _sender, _ev = await _no_id_take(tmp_path, monkeypatch)
    client.advance(290)
    before = read_paths(client)
    await run_passes(client, 1)
    assert PORTFOLIO_ACTIVITIES_PATH not in read_paths(client)[len(before) :]
    assert client._latch.current_open() is not None
    client.advance(20)
    await run_passes(client, 1)
    assert PORTFOLIO_ACTIVITIES_PATH in read_paths(client)
    del current
    await client._disconnect()


@pytest.mark.asyncio
async def test_after_a_contradiction_the_branch_waits_for_the_recheck_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, current, _cmd, _sender, _ev = await _no_id_take(tmp_path, monkeypatch)
    _negative(client, positions={SLUG: {"netPosition": "1"}})
    client.advance(305)
    await run_passes(client, 1)
    assert current.intent_id in client._resolver_contradiction_details

    def _activity_reads() -> int:
        return read_paths(client).count(PORTFOLIO_ACTIVITIES_PATH)

    reads = _activity_reads()
    client.advance(50)
    await run_passes(client, 1)
    assert _activity_reads() == reads, "59.99 s rule: no read before the interval"
    client.advance(12)
    await run_passes(client, 1)
    assert _activity_reads() > reads, "re-read once the interval has passed"
    await client._disconnect()


# ---------------------------------------------------------------------------
# T33-T35: retire, adopt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_process_no_id_no_fill_retires_clears_restores_and_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    sink = _Sink()

    def _watch(c: Any) -> None:
        install_component_degraded_alert(
            c._msgbus,
            component_id=str(c.id),
            reasons=lambda: c.trading_refusals,
            sink=sink,
            ambiguous_reason=AMBIGUOUS,
            ambiguous_clears=lambda: c.ambiguous_refusal_clears,
        )

    client, current, _cmd, _sender, events = await _no_id_take(
        tmp_path, monkeypatch, before_take=_watch
    )
    client._refuse(AMBIGUOUS)  # already present; a no-op that keeps the rig honest
    client.advance(305)
    evidence_before = client.read_startup_position_evidence()

    await run_passes(client, 2)

    assert _retirement(client) == "RESOLVER_NO_ID_NO_FILL"
    assert client.log_lines("info", f"retired intent {current.intent_id} (RESOLVER_NO_ID_NO_FILL)")
    assert client._ledger.spent_today_usd(now_ns=client._clock.timestamp_ns()) == 0
    assert client._budget_was_restored(f"noid:{current.intent_id}")
    _notional, count = live_trading_budget_remaining(client._permit)
    assert count == 2, "restored exactly once; the second pass is a no-op"
    assert len([e for e in events if isinstance(e, OrderRejected)]) == 1
    evidence_after = client.read_startup_position_evidence()
    assert evidence_after is not None
    assert evidence_before is None or evidence_after.ts_ns >= evidence_before.ts_ns
    assert AMBIGUOUS not in client.trading_refusals
    assert client.ambiguous_refusal_clears == 1
    assert client.resume_if_refusals_cleared() is True
    assert len(sink.payloads) == 1, "one component_degraded CRITICAL for the episode"
    await client._disconnect()


@pytest.mark.asyncio
async def test_same_process_no_id_found_fill_is_adopted_and_books_through_accept_fill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, current, command, _sender, events = await _no_id_take(
        tmp_path, monkeypatch, mode="empty200"
    )
    created = current.created_ns
    _negative(client, activities=[_echo_leg(created + SEC_NS, ORDER_X)])
    client.advance(305)

    await _run_exactly_one_pass(client)

    context = read_context(client, current.intent_id)
    assert context is not None and context.venue_order_id == ORDER_X
    assert len([e for e in events if isinstance(e, OrderSubmitted)]) == 1
    assert not [e for e in events if isinstance(e, OrderFilled)]
    assert client._latch.current_open() is not None

    payloads = wire_payloads(client)
    payloads[f"/v1/order/{ORDER_X}"] = _order_get_body(
        ORDER_X, slug=SLUG, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.40"
    )
    payloads[PORTFOLIO_POSITIONS_PATH] = {"positions": {SLUG: {"netPosition": "1"}}, "eof": True}
    await _run_exactly_one_pass(client)

    assert _retirement(client) == "STATUS_REPORT_ACCEPT_FILL_TERMINAL"
    records = client.fill_records_for(build_instrument().id)
    assert [r.venue_order_id for r in records] == [ORDER_X]
    assert len([e for e in events if isinstance(e, OrderFilled)]) == 1
    assert AMBIGUOUS not in client.trading_refusals
    # (the rig has no execution engine, so the cache order's status is not
    # advanced by the published events; the event stream is the evidence)
    cached = client._cache.order(ClientOrderId(command.order.client_order_id.value))
    assert cached is not None
    await client._disconnect()


@pytest.mark.asyncio
async def test_cross_process_sigterm_mid_post_untracked_fill_is_adopted_and_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    # MED-2: a prior process died mid-POST; an untracked fill exists.
    first, cm, intent_id, created = await prior_process(
        tmp_path / "fill", monkeypatch, with_context="no_id", age_s=305
    )
    second, _cm2 = await boot_second_process(
        tmp_path / "fill", monkeypatch, first, cm, admitted=True
    )
    _negative(second, activities=[_echo_leg(created + SEC_NS, ORDER_X)])
    events: list[Any] = []
    second._msgbus.subscribe(topic="*", handler=events.append)
    payloads = wire_payloads(second)
    payloads[f"/v1/order/{ORDER_X}"] = _order_get_body(
        ORDER_X, slug=SLUG, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.40"
    )
    payloads[PORTFOLIO_POSITIONS_PATH] = {"positions": {SLUG: {"netPosition": "1"}}, "eof": True}

    await second._connect()  # the immediate pass adopts the venue id
    context = read_context(second, intent_id)
    assert context is not None and context.venue_order_id == ORDER_X
    assert not [e for e in events if isinstance(e, OrderSubmitted)], "order not in the cache"
    await _run_exactly_one_pass(second)  # then the with-id path

    assert _retirement(second) == "STATUS_REPORT_ACCEPT_FILL_TERMINAL"
    assert [r.venue_order_id for r in second.fill_records_for(build_instrument().id)] == [ORDER_X]
    assert not [e for e in events if isinstance(e, OrderFilled)], "cross-session: nothing booked"
    assert client_module._RESOLVER_FILL_UNBUDGETED in second.trading_refusals, "AC6b"
    await second._disconnect()

    # variant: negative evidence retires with NO restore and NO native event
    first, cm, intent_id, created = await prior_process(
        tmp_path / "nofill", monkeypatch, with_context="no_id", age_s=305
    )
    second, _cm2 = await boot_second_process(
        tmp_path / "nofill", monkeypatch, first, cm, admitted=True
    )
    _negative(second)
    events = []
    second._msgbus.subscribe(topic="*", handler=events.append)
    permit_before = live_trading_budget_remaining(second._permit)
    await second._connect()  # the immediate pass retires it
    assert _retirement(second) == "RESOLVER_NO_ID_NO_FILL"
    assert live_trading_budget_remaining(second._permit) == permit_before, "no restore"
    assert not [e for e in events if isinstance(e, OrderRejected)], "no native event"
    assert not second._budget_was_restored(f"noid:{intent_id}")
    await second._disconnect()


# ---------------------------------------------------------------------------
# T36-T37: contradictions and incomplete reads stay AMBIGUOUS
# ---------------------------------------------------------------------------


async def _contradiction_world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, token: str
) -> tuple[TimedClient, Any]:
    """A real no-id take plus the evidence that yields ``token``."""
    before = None
    if token == "unexplained_holding":
        # no valid baseline: the evidence the take would snapshot is REFUSED
        def before(c: Any) -> None:
            write_evidence(c, "0", refused=True)

    client, current, _cmd, _sender, _ev = await _no_id_take(
        tmp_path, monkeypatch, before_take=before
    )
    created = current.created_ns
    if token == "multiple_candidates":
        _negative(
            client,
            activities=[
                _echo_leg(created + 2 * SEC_NS, "cand-b"),
                _echo_leg(created + 1 * SEC_NS, "cand-a"),
            ],
        )
    elif token == "unattributed_automated_trade_in_window":
        _negative(client, activities=[_echo_leg(created + SEC_NS, "other-1", price="0.55")])
    elif token == "in_window_open_order":
        _negative(client, open_orders=[_open_ioc_order(created + SEC_NS)])
    elif token == "unexplained_holding":
        _negative(client, positions={SLUG: {"netPosition": "1"}})
    elif token == "leg_after_attribution_window":
        _negative(client, activities=[_echo_leg(created + 120 * SEC_NS + 1, "late-1")])
    else:  # pragma: no cover
        raise AssertionError(token)
    return client, current


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "token",
    [
        "multiple_candidates",
        "unattributed_automated_trade_in_window",
        "in_window_open_order",
        "unexplained_holding",
        "leg_after_attribution_window",
    ],
)
async def test_no_id_contradictions_stay_ambiguous_and_page_critical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
    token: str,
) -> None:
    client, current = await _contradiction_world(tmp_path, monkeypatch, token)
    client.advance(305)

    await run_passes(client, 1)

    details = _contradiction(client, current.intent_id)
    assert details["event"] == CONTRADICTION_EVENT
    assert details["no_id"] == "true"
    assert details["reason"] == token
    expected_next = HOLDING_NEXT if token.startswith("unexplained_holding") else "no_id_recheck_60s"
    assert details["next"] == expected_next
    assert client._latch.current_open() is not None
    assert AMBIGUOUS in client.trading_refusals
    assert len(client.log_lines("error", "no-id intent")) == 1
    _assert_no_operator_wording(client)
    await client._disconnect()


@pytest.mark.asyncio
async def test_a_valid_baseline_moved_by_an_unexplained_leg_is_the_delta_contradiction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, intent_id, _snapshot, _created = await _route_d_world(
        tmp_path, monkeypatch, baseline_net="0", now_net="1"
    )
    await run_passes(client, 1)
    details = _contradiction(client, intent_id)
    assert details["reason"] == "unexplained_holding_delta"
    assert details["next"] == HOLDING_NEXT
    assert len(client.log_lines("error", "no-id intent")) == 1
    await client._disconnect()


@pytest.mark.asyncio
async def test_a_holding_contradiction_on_an_exit_context_uses_the_exit_direction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    """Exit (SELL) absolute rule: ``v < d`` is the contradiction."""
    client, _ev, _permit, _cm = await build_client(
        tmp_path, monkeypatch, sender=response_sender(200, b"{}"), admitted=True
    )
    instrument = build_instrument()
    record = client_module.DurableFillRecord(
        venue_order_id="prior-fill-1",
        client_order_id="O-PRIOR",
        instrument_id=str(instrument.id),
        order_side="BUY",
        cumulative_qty=Decimal(1),
        cumulative_cost=Decimal("0.40"),
        cumulative_fee=Decimal(0),
        fee_reconciled=False,
        ts_event=client._clock.timestamp_ns() - 10_000 * SEC_NS,
        venue_fee_raw=None,
        trade_id="GET-prior-fill-1",
        order_qty=Decimal(1),
    )
    client.record_fill(record)
    intent_id, _created = arm_context(client, age_s=305, wire_action="ORDER_ACTION_SELL")
    _negative(client, positions={})  # v = 0 < d = 1
    await run_passes(client, 1)
    details = _contradiction(client, intent_id)
    assert details["reason"] == "unexplained_holding"
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "page_cap",
        "empty_cursor",
        "out_of_order_one_page",
        "out_of_order_across_pages",
        "uninterpretable_in_window_row",
        "unparseable_trade_time",
        "activities_read_raises",
        "open_orders_read_raises",
        "positions_read_raises",
        "durable_net_none",
    ],
)
async def test_no_id_incomplete_reads_stay_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
    case: str,
) -> None:
    client, current, _cmd, _sender, _ev = await _no_id_take(tmp_path, monkeypatch)
    created = current.created_ns
    payloads = wire_payloads(client)
    older = created - 500 * SEC_NS
    bad_manual = trade_row(ts_ns=created + SEC_NS, order_id="other", slug=SLUG, price="0.55")
    del bad_manual["trade"]["aggressor"]["manualOrderIndicator"]
    pages: dict[str | None, dict[str, Any]] | None = None
    if case == "page_cap":
        payloads[PORTFOLIO_ACTIVITIES_PATH] = {
            "activities": [],
            "eof": False,
            "nextCursor": "c",
        }
    elif case == "empty_cursor":
        payloads[PORTFOLIO_ACTIVITIES_PATH] = {"activities": [], "eof": False}
    elif case == "out_of_order_one_page":
        payloads[PORTFOLIO_ACTIVITIES_PATH] = {
            "activities": [
                trade_row(ts_ns=older, order_id="a", slug=SLUG, manual=True),
                trade_row(ts_ns=older + SEC_NS, order_id="b", slug=SLUG, manual=True),
            ],
            "eof": True,
        }
    elif case == "out_of_order_across_pages":
        pages = {
            None: {
                "activities": [
                    trade_row(ts_ns=created + 100 * SEC_NS, order_id="a", slug=SLUG, manual=True)
                ],
                "eof": False,
                "nextCursor": "p2",
            },
            "p2": {
                "activities": [
                    trade_row(ts_ns=created + 110 * SEC_NS, order_id="b", slug=SLUG, manual=True)
                ],
                "eof": True,
            },
        }
    elif case == "uninterpretable_in_window_row":
        payloads[PORTFOLIO_ACTIVITIES_PATH] = {"activities": [bad_manual], "eof": True}
    elif case == "unparseable_trade_time":
        row = trade_row(ts_ns=older, order_id="a", slug=SLUG, manual=True)
        row["trade"]["createTime"] = "not-a-time"
        payloads[PORTFOLIO_ACTIVITIES_PATH] = {"activities": [row], "eof": True}
    elif case == "activities_read_raises":
        del payloads[PORTFOLIO_ACTIVITIES_PATH]
    elif case == "open_orders_read_raises":
        del payloads[OPEN_ORDERS_PATH]
    elif case == "positions_read_raises":
        del payloads[PORTFOLIO_POSITIONS_PATH]
    elif case == "durable_net_none":
        monkeypatch.setattr(PolymarketUSExecutionClient, "_durable_net_qty", lambda *_a: None)
    if pages is not None:
        stub = client._private_read

        async def _paged(path: str, query: Any = None) -> Any:
            if path == PORTFOLIO_ACTIVITIES_PATH:
                cursor = (query or {}).get("cursor")
                return pages[cursor]
            return await stub(path, query)

        client._private_read = _paged
    client.advance(305)

    await run_passes(client, 1)

    assert client._latch.current_open() is not None
    assert current.intent_id not in client._resolver_contradiction_details
    assert AMBIGUOUS in client.trading_refusals
    assert client.log_lines("warning"), "an incomplete read logs a WARNING"
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("attributed", [True, False], ids=["attributed", "window_only"])
async def test_a_persistently_incomplete_no_id_intent_pages_the_stale_critical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
    attributed: bool,
) -> None:
    client, _ev, _permit, _cm = await build_client(
        tmp_path, monkeypatch, sender=response_sender(200, b"{}"), admitted=True
    )
    intent_id, _created = arm_context(client, age_s=16 * 60, with_context=attributed)
    _negative(client)
    del wire_payloads(client)[PORTFOLIO_ACTIVITIES_PATH]  # activities never readable
    await run_passes(client, 1)
    assert client._latch.current_open() is not None
    entry = (
        dict(client._resolver_stale_alert_details[intent_id])
        if intent_id in client._resolver_stale_alert_details
        else None
    )
    assert entry is not None and entry["event"] == "open_intent_stale"
    if not attributed:
        assert entry["no_context"] == "true"
        assert entry["next"] == "no_id_resolver_window_only"
    _assert_no_operator_wording(client)
    await client._disconnect()


# ---------------------------------------------------------------------------
# T38-T40: ignoring non-Breezy rows, window-only mode, H2
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_breezy_rows_are_ignored_and_no_fill_retires(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, _ev, _permit, _cm = await build_client(
        tmp_path, monkeypatch, sender=response_sender(200, b"{}"), admitted=True
    )
    intent_id, created = arm_context(client, age_s=305)
    client.record_venue_order_id(
        submit_chain.venue_order_id("known-1"), ClientOrderId("O-OTHER-TAKE")
    )
    rows = [
        _echo_leg(created + 4 * SEC_NS, "known-1"),  # (i) maps to another take
        _echo_leg(created + 3 * SEC_NS, "manual-1", manual=True),  # (ii)
        _echo_leg(created + 2 * SEC_NS, "hit-manual-passive", price="0.55", passive_manual=True),
        _echo_leg(created - 300 * SEC_NS, "before-window", price="0.55"),  # (iv)
    ]
    _negative(client, activities=rows)

    await run_passes(client, 1)

    assert _retirement(client) == "RESOLVER_NO_ID_NO_FILL"
    _assert_no_operator_wording(client)
    del intent_id
    await client._disconnect()


@pytest.mark.asyncio
async def test_window_only_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    # (i) the store-fail intent: OPEN, no context -- retires after 300 s
    (tmp_path / "i").mkdir()
    client, _events, _permit, _cm = await build_client(
        tmp_path / "i", monkeypatch, sender=RaisingSender(), admitted=True
    )
    real_set = PolymarketUSExecutionClient._store_set

    def _failing_set(self: Any, key: str, value: bytes) -> None:
        if key.startswith(RESOLVER_CONTEXT_KEY_PREFIX):
            raise OSError("resolver-prefix write failed (rig)")
        real_set(self, key, value)

    monkeypatch.setattr(PolymarketUSExecutionClient, "_store_set", _failing_set)
    await client._submit_order(make_command(client))
    monkeypatch.setattr(PolymarketUSExecutionClient, "_store_set", real_set)
    assert client._latch.current_open() is not None
    _negative(client)
    client.advance(305)
    await run_passes(client, 1)
    assert _retirement(client) == "RESOLVER_NO_ID_NO_FILL"
    await client._disconnect()

    # (ii) ANY unknown AUTOMATIC in-window aggressor is a contradiction
    (tmp_path / "ii").mkdir()
    client, _ev, _permit, _cm = await build_client(
        tmp_path / "ii", monkeypatch, sender=response_sender(200, b"{}"), admitted=True
    )
    intent_id, created = arm_context(client, age_s=305, with_context=False)
    _negative(client, activities=[_echo_leg(created + SEC_NS, "would-match-an-echo")])
    await run_passes(client, 1)
    assert _contradiction(client, intent_id)["reason"] == "unattributed_automated_trade_in_window"
    await client._disconnect()

    # (iii) a same-day instrument with v != d
    (tmp_path / "iii").mkdir()
    client, _ev, _permit, _cm = await build_client(
        tmp_path / "iii", monkeypatch, sender=response_sender(200, b"{}"), admitted=True
    )
    intent_id, _created = arm_context(client, age_s=305, with_context=False)
    _negative(client, positions={SLUG: {"netPosition": "1"}})
    await run_passes(client, 1)
    assert _contradiction(client, intent_id)["reason"] == "unexplained_holding"
    await client._disconnect()

    # (iv) an old-blob context (wire fields None) uses the window-only rules
    (tmp_path / "iv").mkdir()
    client, _ev, _permit, _cm = await build_client(
        tmp_path / "iv", monkeypatch, sender=response_sender(200, b"{}"), admitted=True
    )
    intent_id, created = arm_context(
        client,
        age_s=305,
        wire_slug=None,
        wire_price=None,
        wire_outcome_side=None,
        wire_action=None,
    )
    _negative(client, activities=[_echo_leg(created + SEC_NS, "would-match-an-echo")])
    await run_passes(client, 1)
    assert _contradiction(client, intent_id)["reason"] == "unattributed_automated_trade_in_window"
    await client._disconnect()


@pytest.mark.asyncio
async def test_resolve_no_order_refuses_without_a_this_run_negative_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, _ev, _permit, _cm = await build_client(
        tmp_path, monkeypatch, sender=response_sender(200, b"{}"), admitted=True
    )
    intent_id, _created = arm_context(client, age_s=305)
    context = read_context(client, intent_id)
    assert context is not None

    client._resolve_no_order(intent_id, context, client._clock.timestamp_ns(), {})

    assert client._latch.current_open() is not None, "no retire without the H2 stamp"
    assert client.log_lines("error", "SAFETY H2")


@pytest.mark.asyncio
async def test_resolve_no_order_is_idempotent_against_an_already_retired_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, _ev, _permit, _cm = await build_client(
        tmp_path, monkeypatch, sender=response_sender(200, b"{}"), admitted=True
    )
    intent_id, _created = arm_context(client, age_s=305)
    context = read_context(client, intent_id)
    assert context is not None
    now = client._clock.timestamp_ns()
    client._resolved_no_id_ts_ns[intent_id] = now
    client._retire(intent_id, "RESOLVER_NO_ID_NO_FILL", now)

    client._resolve_no_order(intent_id, context, now, {})  # must not raise

    assert _retirement(client) == "RESOLVER_NO_ID_NO_FILL"
    assert not client.log_lines("info", f"retired intent {intent_id} (RESOLVER_NO_ID_NO_FILL)")


# ---------------------------------------------------------------------------
# T49-T50: the holding baseline, the exits, the supervisor marker guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pre_existing_manual_holding_does_not_block_no_fill_retirement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, _ev, _permit, _cm = await build_client(
        tmp_path, monkeypatch, sender=RaisingSender(), admitted=True, start=True
    )
    evidence_ts = write_evidence(client, "2")
    sender = client._order_sender

    await client._submit_order(make_command(client))

    assert len(sender.calls) == 1
    current = client._latch.current_open()
    assert current is not None
    context = read_context(client, current.intent_id)
    assert context is not None
    assert context.baseline_venue_net == "2"
    assert context.baseline_durable_net == "0"
    assert context.baseline_ts_ns == evidence_ts
    _negative(client, positions={SLUG: {"netPosition": "2"}})
    client.advance(305)

    await run_passes(client, 1)

    assert _retirement(client) == "RESOLVER_NO_ID_NO_FILL"
    await client._disconnect()


@pytest.mark.asyncio
async def test_baseline_variants_a_b_c(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    def now_of(c: Any) -> int:
        return int(c._clock.timestamp_ns())

    instrument = build_instrument()

    # (a) a durable fill within 300 s of the snapshot -> no baseline -> absolute rule
    (tmp_path / "a").mkdir()
    client, _ev, _permit, _cm = await build_client(
        tmp_path / "a", monkeypatch, sender=RaisingSender(), admitted=True, start=True
    )
    stamp = now_of(client)
    client.record_fill(
        client_module.DurableFillRecord(
            venue_order_id="recent-1",
            client_order_id="O-RECENT",
            instrument_id=str(instrument.id),
            order_side="BUY",
            cumulative_qty=Decimal(1),
            cumulative_cost=Decimal("0.40"),
            cumulative_fee=Decimal(0),
            fee_reconciled=False,
            ts_event=stamp - 100 * SEC_NS,
            venue_fee_raw=None,
            trade_id="GET-recent-1",
            order_qty=Decimal(1),
        )
    )
    write_evidence(client, "1", ts_ns=stamp)
    assert client._holding_baseline(instrument.id, SLUG, stamp) is None
    await client._disconnect()

    # (b) refused or non-eof evidence -> no baseline
    (tmp_path / "b").mkdir()
    client, _ev, _permit, _cm = await build_client(
        tmp_path / "b", monkeypatch, sender=RaisingSender(), admitted=True, start=True
    )
    stamp = now_of(client)
    write_evidence(client, "1", ts_ns=stamp, refused=True)
    assert client._holding_baseline(instrument.id, SLUG, stamp) is None
    write_evidence(client, "1", ts_ns=stamp, eof=False)
    assert client._holding_baseline(instrument.id, SLUG, stamp) is None

    # (b-2) the age bound: 120 s + 1 ns -> none; exactly 120 s -> a baseline
    write_evidence(client, "1", ts_ns=stamp)
    assert client._holding_baseline(instrument.id, SLUG, stamp + 120 * SEC_NS + 1) is None
    baseline = client._holding_baseline(instrument.id, SLUG, stamp + 120 * SEC_NS)
    assert baseline is not None
    assert (baseline.venue_net, baseline.durable_net, baseline.ts_ns) == ("1", "0", stamp)
    await client._disconnect()

    # (c) a raising _holding_baseline leaves the take POSTed once, no baseline
    (tmp_path / "c").mkdir()
    sender = RaisingSender()
    client, _ev, _permit, _cm = await build_client(
        tmp_path / "c", monkeypatch, sender=sender, admitted=True, start=True
    )

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("baseline exploded (rig)")

    monkeypatch.setattr(PolymarketUSExecutionClient, "_holding_baseline", _boom)
    await client._submit_order(make_command(client))
    assert len(sender.calls) == 1
    current = client._latch.current_open()
    assert current is not None
    context = read_context(client, current.intent_id)
    assert context is not None and context.baseline_ts_ns is None
    await client._disconnect()


@pytest.mark.asyncio
async def test_a_holding_contradiction_exits_automatically_once_the_market_is_past_day(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    # (d) unexplained_holding on a listed instrument, then a reboot on a
    # provider WITHOUT it (past-day): the positions leg is skipped -> retires.
    first, cm, intent_id, _created = await prior_process(
        tmp_path / "d", monkeypatch, with_context="no_id", age_s=305
    )
    _negative(first, positions={SLUG: {"netPosition": "2"}})
    await run_passes(first, 1)
    assert _contradiction(first, intent_id)["reason"] == "unexplained_holding"
    second, _cm2 = await boot_second_process(
        tmp_path / "d", monkeypatch, first, cm, admitted=True, in_provider=False
    )
    _negative(second, positions={})
    await second._connect()
    await run_passes(second, 1)
    assert _retirement(second) == "RESOLVER_NO_ID_NO_FILL"
    await second._disconnect()


@pytest.mark.asyncio
async def test_the_first_relaunch_does_not_exit_a_listed_market_and_the_second_does(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    # (e) exactly two reboots, matching the restated "two daily cycles" bound.
    first, cm, intent_id, _created = await prior_process(
        tmp_path / "e",
        monkeypatch,
        with_context="no_id",
        age_s=305,
        baseline_venue_net="0",
        baseline_durable_net="0",
        baseline_ts_ns=None,
    )
    # a valid delta baseline moved by an unexplained +1
    context = read_context(first, intent_id)
    assert context is not None
    stamped = AmbiguousResolverContext(
        **{
            **{f: getattr(context, f) for f in context.__slots__},
            "baseline_ts_ns": context.created_ns - 5 * SEC_NS,
        }
    )
    first._store_set(f"{RESOLVER_CONTEXT_KEY_PREFIX}{intent_id}", stamped.to_bytes())

    # reboot 1: the market is still listed (the 16:50Z launch on the take day)
    second, cm2 = await boot_second_process(
        tmp_path / "e", monkeypatch, first, cm, admitted=True, in_provider=True
    )
    _negative(second, positions={SLUG: {"netPosition": "1"}})
    await second._connect()
    await run_passes(second, 1)
    details = _contradiction(second, intent_id)
    assert details["reason"] == "unexplained_holding_delta"
    assert details["next"] == HOLDING_NEXT
    assert second._latch.current_open() is not None

    # reboot 2: the market resolved -> past-day -> the exit
    third, _cm3 = await boot_second_process(
        tmp_path / "e", monkeypatch, second, cm2, admitted=True, in_provider=False
    )
    _negative(third, positions={})
    await third._connect()
    await run_passes(third, 1)
    assert _retirement(third) == "RESOLVER_NO_ID_NO_FILL"
    await third._disconnect()


@pytest.mark.asyncio
async def test_no_id_retire_is_blocked_without_the_supervisor_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    # the DEFAULT (flag not passed): False
    client, current, _cmd, _sender, _ev = await _no_id_take(tmp_path, monkeypatch, admitted=None)
    client.advance(305)

    await run_passes(client, 1)

    assert client._latch.current_open() is not None
    entry = _contradiction(client, current.intent_id)
    assert entry["event"] == "resolver_no_id_retire_blocked"
    assert entry["reason"] == "supervisor_decode_marker_absent"
    assert entry["next"] == "next_node_boot_rereads_supervisor_marker"
    assert AMBIGUOUS in client.trading_refusals
    _assert_no_operator_wording(client)
    await client._disconnect()


@pytest.mark.asyncio
async def test_adopt_is_not_gated_by_the_supervisor_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, current, _cmd, _sender, _ev = await _no_id_take(
        tmp_path, monkeypatch, mode="empty200", admitted=False
    )
    _negative(client, activities=[_echo_leg(current.created_ns + SEC_NS, ORDER_X)])
    client.advance(305)
    await _run_exactly_one_pass(client)
    context = read_context(client, current.intent_id)
    assert context is not None and context.venue_order_id == ORDER_X
    await client._disconnect()


# ---------------------------------------------------------------------------
# T51: route (d), manual-leg reconciliation
# ---------------------------------------------------------------------------


def _manual_leg(
    ts_ns: int,
    *,
    action: str = "ORDER_ACTION_BUY",
    outcome: str = "OUTCOME_SIDE_YES",
    intent: str = "ORDER_INTENT_BUY_LONG",
    qty: str = "2.0000",
    order_id: str = "manual-1",
    passive_manual: bool = False,
    slug: str = SLUG,
    manual: bool = True,
) -> dict[str, Any]:
    return trade_row(
        ts_ns=ts_ns,
        order_id=order_id,
        slug=slug,
        outcome_side=outcome,
        action=action,
        intent=intent,
        qty_decimal=qty,
        manual=manual,
        passive_manual=passive_manual,
        price="0.55",
        quantity=9,
        tif="TIME_IN_FORCE_DAY",
    )


async def _route_d_world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    baseline_net: str,
    now_net: str,
    legs_at: list[tuple[int, dict[str, Any]]] | None = None,
    no_leg: bool = False,
) -> tuple[TimedClient, str, int, int]:
    """A hand-built attributed intent with a valid baseline taken 5 s before
    the arm. ``legs_at`` is ``[(offset_s_from_snapshot, row_kwargs)]``."""
    client, _ev, _permit, _cm = await build_client(
        tmp_path, monkeypatch, sender=response_sender(200, b"{}"), admitted=True
    )
    instrument = build_instrument()
    kwargs: dict[str, Any] = {}
    if no_leg:
        instrument = build_no_leg_instrument()
        client._cache.add_instrument(instrument)
        client._instrument_provider.add(instrument)
        kwargs = {"wire_outcome_side": "OUTCOME_SIDE_NO"}
    snapshot_ns = client._clock.timestamp_ns() - 305 * SEC_NS - 5 * SEC_NS
    intent_id, created = arm_context(
        client,
        age_s=305,
        instrument=instrument,
        baseline_venue_net=baseline_net,
        baseline_durable_net="0",
        baseline_ts_ns=snapshot_ns,
        **kwargs,
    )
    rows = [
        _manual_leg(snapshot_ns + off * SEC_NS, **row_kwargs)
        for off, row_kwargs in sorted(legs_at or [], key=lambda item: -item[0])
    ]
    _negative(client, positions={SLUG: {"netPosition": now_net}}, activities=rows)
    return client, intent_id, snapshot_ns, created


@pytest.mark.asyncio
async def test_manual_trade_after_the_snapshot_is_reconciled_within_the_recheck(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    # (i) BUY_LONG 2: the leg is placed just under 120 s before the first pass
    # (the plan's "10 s after the snapshot" cannot be < 120 s old at a pass
    # that is >= 300 s old, so the leg is late; the code path is the same).
    (tmp_path / "i").mkdir()
    client, intent_id, _snapshot, _created = await _route_d_world(
        tmp_path / "i", monkeypatch, baseline_net="0", now_net="2"
    )
    leg_ts = client._clock.timestamp_ns() - 60 * SEC_NS
    _negative(
        client,
        positions={SLUG: {"netPosition": "2"}},
        activities=[_manual_leg(leg_ts)],
    )
    await run_passes(client, 1)
    assert intent_id not in client._resolver_contradiction_details
    assert client._latch.current_open() is not None
    assert client.log_lines("warning", "manual_leg_unsettled")
    client.advance(70)
    await run_passes(client, 1)
    assert _retirement(client) == "RESOLVER_NO_ID_NO_FILL"
    assert client.log_lines("info", "reconciled by 1 manual leg(s)")
    await client._disconnect()

    # (ii) SELL_LONG 2 against a pre-existing manual long of 3 -> net 1
    (tmp_path / "ii").mkdir()
    client, _intent_id, _snapshot, _created = await _route_d_world(
        tmp_path / "ii",
        monkeypatch,
        baseline_net="3",
        now_net="1",
        legs_at=[
            (60, {"action": "ORDER_ACTION_SELL", "intent": "ORDER_INTENT_SELL_LONG"}),
        ],
    )
    await run_passes(client, 1)
    assert _retirement(client) == "RESOLVER_NO_ID_NO_FILL"
    await client._disconnect()

    # (iii) NO-leg echo with (NO, BUY, BUY_SHORT) 1: the venue net moved -1
    (tmp_path / "iii").mkdir()
    client, _intent_id, _snapshot, _created = await _route_d_world(
        tmp_path / "iii",
        monkeypatch,
        baseline_net="3",
        now_net="2",
        no_leg=True,
        legs_at=[
            (
                60,
                {
                    "outcome": "OUTCOME_SIDE_NO",
                    "intent": "ORDER_INTENT_BUY_SHORT",
                    "qty": "1.0000",
                },
            ),
        ],
    )
    await run_passes(client, 1)
    assert _retirement(client) == "RESOLVER_NO_ID_NO_FILL"
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("case", "baseline", "now_net", "legs", "reason"),
    [
        ("iv_untracked_fill_on_top", "0", "3", [(60, {})], None),
        (
            "v_masked_untracked_buy",
            "1",
            "1",
            [
                (
                    60,
                    {
                        "action": "ORDER_ACTION_SELL",
                        "intent": "ORDER_INTENT_SELL_LONG",
                        "qty": "1.0000",
                    },
                )
            ],
            None,
        ),
        ("vi_straddles", "0", "2", [(20, {})], "straddles_snapshot"),
        (
            "vii_sell_short",
            "0",
            "2",
            [
                (
                    60,
                    {
                        "outcome": "OUTCOME_SIDE_NO",
                        "action": "ORDER_ACTION_SELL",
                        "intent": "ORDER_INTENT_SELL_SHORT",
                    },
                )
            ],
            "unknown_shape",
        ),
        (
            "viii_manual_passive",
            "0",
            "0",
            [(60, {"manual": False, "passive_manual": True})],
            "manual_passive_leg",
        ),
    ],
)
async def test_route_d_failures_stay_ambiguous_and_page_with_the_r6_next(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
    case: str,
    baseline: str,
    now_net: str,
    legs: list[tuple[int, dict[str, Any]]],
    reason: str | None,
) -> None:
    client, intent_id, _snapshot, _created = await _route_d_world(
        tmp_path, monkeypatch, baseline_net=baseline, now_net=now_net, legs_at=legs
    )
    await run_passes(client, 1)
    details = _contradiction(client, intent_id)
    assert details["reason"] == "unexplained_holding_delta", case
    assert details["next"] == HOLDING_NEXT
    if reason is not None:
        assert details["manual_reconcile"] == reason
    assert client._latch.current_open() is not None
    _assert_no_operator_wording(client)
    await client._disconnect()


@pytest.mark.asyncio
async def test_with_no_manual_legs_route_d_equals_the_r5_behaviour(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gate_env: None,  # noqa: F811
) -> None:
    client, intent_id, _snapshot, _created = await _route_d_world(
        tmp_path, monkeypatch, baseline_net="2", now_net="2"
    )
    await run_passes(client, 1)
    assert _retirement(client) == "RESOLVER_NO_ID_NO_FILL"
    assert not client.log_lines("info", "manual leg(s)")
    del intent_id
    await client._disconnect()
