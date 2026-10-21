"""S4 WP5 (ARM maker-sharp B6): the poll fill booking (`_query_order`), the recognised
maker commission, the commission latches and the single-winner fill booking.

Plan: ``docs/plans/backlog/MAKER_2026-10-12/S4_exec_resting_order_path_plan_r4_delta.md``
sections 2 WP5, 4 (commission design), 6 and 9 (WP5 list); ARM plan r2 delta D2.

Every sender and private read is a local double: no network, no venue contact. No ``exec``
import here (barrier X1): everything goes through ``ambig_latch_rig``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import QueryOrder
from nautilus_trader.model.enums import LiquiditySide

from tests.unit.ambig_latch_rig import (
    client_module,
    gate_env,  # noqa: F401 -- used via usefixtures
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.polymarket_us_exec_shapes import build_no_leg_instrument
from tests.unit.test_current_rung_hold_pre_arm_race import STRATEGY_ID, TRADER_ID
from tests.unit.test_polymarket_us_resting_cancel import (
    _auto_cancel,
    _cancel_cmd,
    _names,
    _payload,
    _remaining,
    _rig,
    _set_state,
)
from tests.unit.test_polymarket_us_resting_submit import (
    _id_n,
    _rest_command,
    _Rig,
    _submit_rest,
)

_INDEX_KEY: Final[str] = client_module.RESTING_INDEX_KEY
NS: Final[int] = 1_000_000_000
#: Wire price of the NO-leg rest the shared fixture posts (NO 0.40 == wire 0.60).
WIRE_PX: Final[str] = "0.60"
NO_PX: Final[Decimal] = Decimal("0.40")


def _amount(value: str) -> dict[str, str]:
    return {"value": value, "currency": "USD"}


def _inert_bps(rig: _Rig, n: int) -> None:
    """The venue's observed bps fields (WP0 (f)): the string ``"0"``."""
    _payload(rig, n).update({"commissionsBasisPoints": "0", "makerCommissionsBasisPoints": "0"})


def _fill(rig: _Rig, n: int, commission: str = "0.01", **extra: Any) -> None:
    """The venue shows rest ``n`` FILLED (qty 1) at its limit, with ``commission``."""
    _inert_bps(rig, n)
    _payload(rig, n).update(
        {
            "state": "ORDER_STATE_FILLED",
            "cumQuantity": 1,
            "leavesQuantity": 0,
            "avgPx": _amount(WIRE_PX),
            "commissionNotionalTotalCollected": _amount(commission),
            **extra,
        }
    )


def _query(rig: _Rig, command: Any) -> QueryOrder:
    return QueryOrder(
        trader_id=TRADER_ID,
        strategy_id=STRATEGY_ID,
        instrument_id=command.order.instrument_id,
        client_order_id=command.order.client_order_id,
        venue_order_id=None,
        command_id=UUID4(),
        ts_init=rig.client._clock.timestamp_ns(),
    )


def _records(rig: _Rig) -> tuple[Any, ...]:
    return tuple(rig.client.fill_records_for(build_no_leg_instrument().id))


def _filled_events(rig: _Rig) -> list[Any]:
    return [e for e in rig.events if type(e).__name__ == "OrderFilled"]


def _reasons(rig: _Rig) -> list[str]:
    return [r.reason for r in rig.client._trading_refusals]


async def _rested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, n: int = 1
) -> tuple[_Rig, list[Any]]:
    rig = await _rig(tmp_path, monkeypatch)
    commands = [await _submit_rest(rig, i) for i in range(n)]
    for i in range(n):
        _inert_bps(rig, i)
    return rig, commands


# ---------------------------------------------------------------------------
# The poll books a fill
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_query_detects_fill_with_venue_signed_commission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    client = rig.client
    intent_id = client._resting_bookings[_id_n(0)][0]
    _fill(rig, 0, commission="0.01")
    await client._query_order(_query(rig, command))
    (event,) = _filled_events(rig)
    assert event.liquidity_side == LiquiditySide.MAKER
    assert event.last_qty.as_decimal() == Decimal(1)
    assert event.last_px.as_decimal() == NO_PX, "the NO leg price, inverted from the wire"
    assert event.commission.as_decimal() == Decimal("0.01")
    (record,) = _records(rig)
    assert record.venue_order_id == _id_n(0)
    assert record.cumulative_qty == Decimal(1)
    assert record.cumulative_cost == NO_PX
    assert not client._ledger.has_open_exposure(intent_id), "settled once"
    assert json.loads(client._store_get(_INDEX_KEY)) == []
    assert _id_n(0) not in client._resting_bookings
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_query_fill_writes_durable_record_before_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    client = rig.client
    order: list[str] = []
    real_record = client.record_fill
    real_filled = type(client).generate_order_filled

    def record_spy(*args: Any, **kwargs: Any) -> Any:
        order.append("record")
        return real_record(*args, **kwargs)

    def filled_spy(self: Any, **kwargs: Any) -> Any:
        order.append("event")
        assert len(_records(rig)) == 1, "the durable record is on disk when the event goes out"
        return real_filled(self, **kwargs)

    monkeypatch.setattr(client, "record_fill", record_spy)
    monkeypatch.setattr(type(client), "generate_order_filled", filled_spy)
    settles: list[str] = []
    ledger_type = type(client._ledger)
    real_settle = ledger_type.settle

    def settle_spy(self: Any, key: str, **kwargs: Any) -> Any:
        order.append("settle")
        return real_settle(self, key, **kwargs)

    monkeypatch.setattr(ledger_type, "settle", settle_spy)
    _fill(rig, 0)
    await client._query_order(_query(rig, command))
    assert order == ["record", "event", "settle"], settles
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_poll_fill_after_accepted_resting_is_maker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    seen: list[dict[str, Any]] = []
    real = type(rig.client).generate_order_filled

    def spy(self: Any, **kwargs: Any) -> Any:
        seen.append(kwargs)
        return real(self, **kwargs)

    monkeypatch.setattr(type(rig.client), "generate_order_filled", spy)
    _fill(rig, 0)
    await rig.client._query_order(_query(rig, command))
    assert [k["liquidity_side"] for k in seen] == [LiquiditySide.MAKER]
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_query_never_reaches_send_order_status_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    reached: list[Any] = []
    rig.client._send_order_status_report = reached.append
    _fill(rig, 0)
    await rig.client._query_order(_query(rig, command))
    _set_state(rig, 0, "ORDER_STATE_NEW")
    await rig.client._query_order(_query(rig, command))
    assert reached == []
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_query_order_poll_never_sends(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The poll is GET-only: filled, terminal, open and unreadable reads post NOTHING."""
    rig, commands = await _rested(tmp_path, monkeypatch, n=4)
    client = rig.client
    posts_before = len(rig.sender.calls)
    _fill(rig, 0)
    _set_state(rig, 1, "ORDER_STATE_CANCELED")
    # n=2 stays NEW; n=3 becomes unreadable
    del client._private_read._payloads[submit_chain.order_by_id_path(_id_n(3))]
    for command in commands:
        await client._query_order(_query(rig, command))
    assert len(rig.sender.calls) == posts_before
    assert rig.sender.cancels == []
    assert rig.sender.cancel_alls == []
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_query_order_for_an_unbound_order_is_a_quiet_no_op(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An order the ledger does not bind (here: the index emptied) is never read."""
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    client = rig.client
    reads: list[str] = []
    real = client._private_read

    async def counting(path: str, *args: Any, **kwargs: Any) -> Any:
        reads.append(path)
        return await real(path, *args, **kwargs)

    counting._payloads = real._payloads  # type: ignore[attr-defined]
    client._private_read = counting
    client._store_set(_INDEX_KEY, b"[]")
    await client._query_order(_query(rig, command))
    assert reads == []
    assert _filled_events(rig) == []
    await client._disconnect()


# ---------------------------------------------------------------------------
# Poll health: three failed GETs latch resting_query_unreadable
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_three_failed_polls_latch_resting_query_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    client = rig.client
    path = submit_chain.order_by_id_path(_id_n(0))
    good = client._private_read._payloads.pop(path)
    for _ in range(2):
        await client._query_order(_query(rig, command))
    assert submit_chain.RESTING_QUERY_UNREADABLE_REASON not in _reasons(rig)
    await client._query_order(_query(rig, command))
    assert submit_chain.RESTING_QUERY_UNREADABLE_REASON in _reasons(rig)
    client._private_read._payloads[path] = good
    await client._query_order(_query(rig, command))
    assert submit_chain.RESTING_QUERY_UNREADABLE_REASON not in _reasons(rig), "a read clears it"
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_read_that_echoes_another_order_counts_as_a_failed_poll(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    client = rig.client
    _fill(rig, 0)
    _payload(rig, 0)["id"] = "SOMEONEELSE"
    for _ in range(3):
        await client._query_order(_query(rig, command))
    assert submit_chain.RESTING_QUERY_UNREADABLE_REASON in _reasons(rig)
    assert _filled_events(rig) == [], "a read that answers for another order books nothing"
    assert json.loads(client._store_get(_INDEX_KEY)) == [_id_n(0)]
    await client._disconnect()


# ---------------------------------------------------------------------------
# Terminal polls: as the cancel path (4c)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize(
    ("state", "event"),
    [
        ("ORDER_STATE_CANCELED", "OrderCanceled"),
        ("ORDER_STATE_EXPIRED", "OrderExpired"),
        ("ORDER_STATE_REJECTED", "OrderRejected"),
    ],
)
async def test_a_venue_terminal_zero_fill_poll_retires_once_like_a_cancel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str, event: str
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    client = rig.client
    intent_id = client._resting_bookings[_id_n(0)][0]
    _set_state(rig, 0, state)
    await client._query_order(_query(rig, command))
    await client._query_order(_query(rig, command))
    assert _names(rig).count(event) == 1
    assert not client._ledger.has_open_exposure(intent_id)
    assert json.loads(client._store_get(_INDEX_KEY)) == []
    assert _filled_events(rig) == []
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_still_open_poll_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    client = rig.client
    before = (_remaining(rig), list(rig.events))
    await client._query_order(_query(rig, command))
    assert (_remaining(rig), list(rig.events)) == before
    assert json.loads(client._store_get(_INDEX_KEY)) == [_id_n(0)]
    await client._disconnect()


# ---------------------------------------------------------------------------
# Commission: one recognition point
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_poll_fill_books_recognised_commission_to_cumulative_fee_and_native_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0, commission="0.01")
    await rig.client._query_order(_query(rig, command))
    (record,) = _records(rig)
    (event,) = _filled_events(rig)
    assert record.cumulative_fee == Decimal("0.01")
    assert event.commission.as_decimal() == record.cumulative_fee
    assert record.venue_fee_raw == "0.01"
    assert record.fee_reconciled is True
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_raw_negative_commission_persisted_only_in_venue_fee_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert submit_chain.MAKER_COMMISSION_SIGN_VERIFIED is False
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0, commission="-0.01")
    await rig.client._query_order(_query(rig, command))
    (record,) = _records(rig)
    (event,) = _filled_events(rig)
    assert record.venue_fee_raw == "-0.01"
    assert record.cumulative_fee == Decimal(0), "an unverified rebate is never booked"
    assert event.commission.as_decimal() == Decimal(0)
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize(
    ("raw", "reconciled"), [("0.01", True), ("0", True), ("0.00", True), ("-0.01", False)]
)
async def test_fee_reconciled_is_recognised_equals_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str, reconciled: bool
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0, commission=raw)
    await rig.client._query_order(_query(rig, command))
    (record,) = _records(rig)
    assert record.fee_reconciled is reconciled
    expected_source = (
        client_module.FEE_SOURCE_RECORDED
        if reconciled
        else client_module.FEE_SOURCE_MODELLED_AT_FILL_TIME
    )
    assert record.fee_source == expected_source
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_flipping_the_sign_pin_books_the_raw_rebate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one switch: with the sign VERIFIED the recognised value is the raw one and the
    fill reconciles. (The flip itself is a reviewed WP6 commit, never this test.)"""
    monkeypatch.setattr(submit_chain, "MAKER_COMMISSION_SIGN_VERIFIED", True)
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0, commission="-0.01")
    await rig.client._query_order(_query(rig, command))
    (record,) = _records(rig)
    assert record.cumulative_fee == Decimal("-0.01")
    assert record.fee_reconciled is True
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_filled_any_with_negative_commission_is_booked_not_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L-48: a real fill is never stranded by a refusal on its commission sign."""
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0, commission="-0.01")
    await rig.client._query_order(_query(rig, command))
    assert len(_filled_events(rig)) == 1 and len(_records(rig)) == 1
    assert rig.client._trading_refusals == []
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_clamped_negative_is_unreconciled_and_excluded_from_prereg_population(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A clamped negative is UNRECONCILED, so every reader that gates on
    ``fee_reconciled`` (prereg admission, the settled-P&L floor) excludes it."""
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0, commission="-0.01")
    await rig.client._query_order(_query(rig, command))
    (record,) = _records(rig)
    assert record.fee_reconciled is False
    assert record.fee_source == client_module.FEE_SOURCE_MODELLED_AT_FILL_TIME
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_position_realized_pnl_cannot_rise_on_unverified_rebate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Native ``Position.realized_pnl`` nets ``OrderFilled.commission``: a negative event
    commission would RAISE it. Whatever the raw sign, the event never carries one."""
    values: list[Decimal] = []
    for n, raw in enumerate(["-0.05", "-0.01", "0", "0.01"]):
        rig, (command,) = await _rested(tmp_path / f"r{n}", monkeypatch)
        _fill(rig, 0, commission=raw)
        await rig.client._query_order(_query(rig, command))
        values.append(_filled_events(rig)[0].commission.as_decimal())
        await rig.client._disconnect()
    assert all(v >= 0 for v in values), values
    assert values == [Decimal(0), Decimal(0), Decimal(0), Decimal("0.01")]


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_positive_commission_always_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0, commission="0.02")
    await rig.client._query_order(_query(rig, command))
    (record,) = _records(rig)
    assert record.cumulative_fee == Decimal("0.02")
    await rig.client._disconnect()


# ---------------------------------------------------------------------------
# Latches: envelope and bps drift (NEW rests only; the fill is still booked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize("raw", ["0.50", "-0.50"])
async def test_commission_outside_envelope_books_and_latches_new_rests_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, raw: str
) -> None:
    rig, (command, second) = await _rested(tmp_path, monkeypatch, n=2)
    client = rig.client
    _fill(rig, 0, commission=raw)
    await client._query_order(_query(rig, command))
    assert len(_filled_events(rig)) == 1 and len(_records(rig)) == 1, "still booked"
    assert submit_chain.RESTING_COMMISSION_OUT_OF_ENVELOPE_REASON in _reasons(rig)
    # NEW rests are refused (denied before any POST) ...
    posts = len(rig.sender.calls)
    await client._submit_order(_rest_command(client))
    assert len(rig.sender.calls) == posts
    # ... cancels and polls continue
    _auto_cancel(rig)
    await client._cancel_order(_cancel_cmd(rig, second))
    assert _names(rig).count("OrderCanceled") == 1
    await client._query_order(_query(rig, second))
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_commission_inside_the_envelope_latches_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0, commission="0.01")
    await rig.client._query_order(_query(rig, command))
    assert submit_chain.RESTING_COMMISSION_OUT_OF_ENVELOPE_REASON not in _reasons(rig)
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_bps_drift_latches_new_rests_keeps_cancels_and_booking(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, (first, second) = await _rested(tmp_path, monkeypatch, n=2)
    client = rig.client
    _fill(rig, 0, commission="0.01", makerCommissionsBasisPoints="125")
    await client._query_order(_query(rig, first))
    assert len(_filled_events(rig)) == 1, "the fill is still booked"
    assert submit_chain.COMMISSION_BPS_DRIFT_REASON in _reasons(rig)
    (record,) = _records(rig)
    assert record.cumulative_fee == Decimal("0.01"), "the bps value is a watch, never a rate"
    # cancels continue under the latch
    _auto_cancel(rig)
    await client._cancel_order(_cancel_cmd(rig, second))
    assert _names(rig).count("OrderCanceled") == 1
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_every_poll_get_runs_the_bps_inertness_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An open rest's poll (no fill at all) still trips the drift latch."""
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _payload(rig, 0)["commissionsBasisPoints"] = "5"
    await rig.client._query_order(_query(rig, command))
    assert submit_chain.COMMISSION_BPS_DRIFT_REASON in _reasons(rig)
    await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_poll_never_reads_bps_or_fee_coefficient(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[CHAR] The bps and ``feeCoefficient`` fields are watched, never priced from: the
    booked fee is the same whatever they say."""
    results: list[Decimal] = []
    for n, bps in enumerate(["0", "9999"]):
        rig, (command,) = await _rested(tmp_path / f"c{n}", monkeypatch)
        _fill(
            rig,
            0,
            commission="0.01",
            commissionsBasisPoints=bps,
            makerCommissionsBasisPoints=bps,
        )
        await rig.client._query_order(_query(rig, command))
        results.append(_records(rig)[0].cumulative_fee)
        await rig.client._disconnect()
    assert results == [Decimal("0.01"), Decimal("0.01")]


# ---------------------------------------------------------------------------
# Log hygiene (sec L2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_venue_fee_raw_never_logged_beyond_sign_class_or_alerted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "0.0137"
    for n, raw in enumerate([secret, f"-{secret}", "0.9173"]):
        rig, (command,) = await _rested(tmp_path / f"l{n}", monkeypatch)
        marker = raw.lstrip("-")
        _fill(rig, 0, commission=raw)
        await rig.client._query_order(_query(rig, command))
        text = "\n".join(message for _level, message in rig.client.log_records)
        alerts = json.dumps(
            [dict(a) for a in rig.client.resting_cancel_alerts]
            + [dict(a) for a in rig.client.resting_commission_alerts]
        )
        assert marker not in text, "the raw figure is never logged"
        assert marker not in alerts, "the raw figure is never in an alert"
        assert any("commission sign" in m for _lv, m in rig.client.log_records)
        await rig.client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_durable_fill_record_key_set_unchanged_no_commission_sign(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[CHAR] K1: the poll booking adds no key to ``DurableFillRecord`` (the sign is the
    first character of ``venueFeeRaw``)."""
    rig, (command,) = await _rested(tmp_path, monkeypatch)
    _fill(rig, 0, commission="-0.01")
    await rig.client._query_order(_query(rig, command))
    raw = rig.client._store_get(f"{client_module.FILL_KEY_PREFIX}{_id_n(0)}")
    assert raw is not None
    assert set(json.loads(raw)) == {
        "venueOrderId",
        "clientOrderId",
        "instrumentId",
        "orderSide",
        "cumulativeQty",
        "cumulativeCost",
        "cumulativeFee",
        "feeReconciled",
        "tsEvent",
        "venueFeeRaw",
        "tradeId",
        "orderQty",
        "feeCoefficientAtFill",
        "feeSource",
    }
    await rig.client._disconnect()
