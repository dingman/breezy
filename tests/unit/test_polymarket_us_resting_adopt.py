"""S4 WP3 (ARM maker-sharp B4, r2 D2): the in-process no-id RESTING ADOPT, end to end.

A resting POST whose response carried no venue order id leaves a pre-POST
context (``resting=True``) and nothing to GET. In the SAME process the no-id
resolver ADOPTs a single echo-matching GTD open order (the with-id resolver then
binds it), or retires the intent ``RESOLVER_NO_ID_NO_FILL`` after two negative
passes (the GTD expired). The three RED tests r2 D2 requires:

(a) ``test_no_id_rest_expires_then_two_negative_passes_retire_no_fill``;
(b) ``test_no_id_maker_fill_before_adopt_stays_ambiguous_with_the_operator_clearing_path``:
    a maker fill before ADOPT is the passive side of a trade row, so it can never
    be adopted. It stays AMBIGUOUS (fail closed, exposure bounded: qty 1, held to
    settlement). The named clearing path is the operator runbook:
    stop the node, ``breezy-clear-submit-intent --list`` to find the slot,
    reconcile the held NO leg against the venue positions + activities, then clear
    that intent with ``--intent-id <id> --resolution ... --evidence ...`` and the
    ``BREEZY_CLEAR_SUBMIT_INTENT_ACK`` ack (``src/breezy/runtime/clear_submit_intent_cli.py``);
(c) ``test_contradiction_is_re_evaluated_per_tick_not_latched``.

No ``exec`` import here (barrier X1): everything goes through ``ambig_latch_rig``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import pytest

from tests.unit.ambig_latch_rig import (
    OPEN_ORDERS_PATH,
    SEC_NS,
    TimedClient,
    build_client,
    client_module,
    gate_env,  # noqa: F401 -- used via usefixtures
    ns_to_rfc3339,
    read_context,
    response_sender,
    rig_slug,
    run_passes,
    submit_chain,
    trade_row,
    wire_payloads,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.polymarket_us_exec_shapes import build_no_leg_instrument
from tests.unit.test_ambig_no_id_resolver import _negative, _retirement
from tests.unit.test_polymarket_us_resting_submit import (
    VENUE_ID,
    _rest_command,
    _venue_order,
)

SLUG: Final[str] = rig_slug()
NO_ID_ACK: Final[bytes] = json.dumps({"executions": []}).encode("utf-8")


async def _no_id_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[TimedClient, Any, Any]:
    """One REAL resting take whose 200 carries no id (a no-id AMBIGUOUS)."""
    monkeypatch.setattr(submit_chain, "GTD_EXPIRY_VERIFIED", True)
    client, _events, _permit, _cm = await build_client(
        tmp_path,
        monkeypatch,
        sender=response_sender(200, b"{}"),
        admitted=True,
        start=True,
    )
    client._resting_accept_admitted = True
    no = build_no_leg_instrument()
    client._cache.add_instrument(no)
    client._instrument_provider.add(no)
    _negative(client)
    command = _rest_command(client)
    await client._submit_order(command)
    current = client._latch.current_open()
    assert current is not None, "a no-id AMBIGUOUS leaves the intent OPEN"
    context = read_context(client, current.intent_id)
    assert context is not None and context.resting is True
    assert context.venue_order_id == submit_chain.NO_VENUE_ORDER_ID
    return client, current, command


def _open_rest_row(context_created_ns: int, command: Any, *, order_id: str = VENUE_ID) -> Any:
    row = _venue_order(command)["order"]
    row["id"] = order_id
    row["createTime"] = ns_to_rfc3339(context_created_ns + 5 * SEC_NS)
    return row


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_no_id_rest_expires_then_two_negative_passes_retire_no_fill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(a) The GTD expired and nothing is visible: ONE negative pass is not enough
    for a rest; the second, >= 60 s later, retires RESOLVER_NO_ID_NO_FILL."""
    client, current, _command = await _no_id_rest(tmp_path, monkeypatch)
    client.advance(305)
    await run_passes(client, 1)
    assert client._latch.current_open() is not None, "first negative pass retires nothing"
    assert _retirement(client) is None
    client.advance(30)
    await run_passes(client, 1)
    assert _retirement(client) is None, "30 s is inside the recheck interval"
    client.advance(40)
    await run_passes(client, 1)
    assert _retirement(client) == "RESOLVER_NO_ID_NO_FILL"
    assert current.intent_id not in client._no_id_resting_first_nofill_ns
    assert client._latch.open_slot_count() == 0
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_late_landing_post_after_first_read_is_caught_by_second_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, current, command = await _no_id_rest(tmp_path, monkeypatch)
    context = read_context(client, current.intent_id)
    client.advance(305)
    await run_passes(client, 1)  # first negative pass
    # the POST lands late: the rest is now visible on the open-orders read
    _negative(client, open_orders=[_open_rest_row(context.created_ns, command)])
    client.advance(65)
    await run_passes(client, 1)
    assert _retirement(client) is None, "never NO_FILL once the rest is visible"
    adopted = read_context(client, current.intent_id)
    assert adopted.venue_order_id == VENUE_ID
    assert client._no_id_resting_first_nofill_ns.get(current.intent_id, 0) == 0
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_resting_single_echo_match_open_order_is_adopted_then_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, current, command = await _no_id_rest(tmp_path, monkeypatch)
    context = read_context(client, current.intent_id)
    _negative(client, open_orders=[_open_rest_row(context.created_ns, command)])
    wire_payloads(client)[submit_chain.order_by_id_path(VENUE_ID)] = _venue_order(command)
    client.advance(305)
    # One driven run is several passes: the no-id pass ADOPTs the open order, the
    # next (with-id) pass GETs it NEW and binds it through the shared binder.
    await run_passes(client, 1)
    assert read_context(client, current.intent_id).venue_order_id == VENUE_ID
    assert client._latch.open_slot_count() == 0
    index = client._store_get(client_module.RESTING_INDEX_KEY)
    assert index is not None
    assert json.loads(index) == [VENUE_ID]
    assert VENUE_ID in client._resting_bookings
    assert client._trading_refusals == []
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_no_id_maker_fill_before_adopt_stays_ambiguous_with_the_operator_clearing_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(b) The rest filled as MAKER before it could be adopted: the venue shows the
    trade with some OTHER order as aggressor, so the join is a contradiction. The
    intent stays OPEN/AMBIGUOUS and the surfaced `next` NAMES the operator path
    (see the module docstring for the runbook); no automated route retires it."""
    client, current, _command = await _no_id_rest(tmp_path, monkeypatch)
    context = read_context(client, current.intent_id)
    aggressor = trade_row(
        ts_ns=context.created_ns + 10 * SEC_NS,
        order_id="AGGRESSOR-1",
        slug=SLUG,
        price="0.60",
        tif="TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
    )
    _negative(client, activities=[aggressor], positions={SLUG: {"netPosition": "-1"}})
    client.advance(305)
    await run_passes(client, 1)
    detail = client._resolver_contradiction_details[current.intent_id]
    assert detail["event"] == "resolver_evidence_contradiction"
    assert detail["next"] == client_module._RESTING_NO_ID_OPERATOR_CLEAR_NEXT
    assert "breezy_clear_submit_intent" in detail["next"]
    assert client._latch.current_open() is not None
    assert _retirement(client) is None
    client.advance(65)
    await run_passes(client, 3)
    assert _retirement(client) is None, "no automated route retires a filled rest"
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_contradiction_is_re_evaluated_per_tick_not_latched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(c) Two echo-matching GTD orders contradict; one tick later only one is
    left and the SAME intent ADOPTs it. A contradiction is a verdict about one
    tick's evidence, never a latch."""
    client, current, command = await _no_id_rest(tmp_path, monkeypatch)
    context = read_context(client, current.intent_id)
    both = [
        _open_rest_row(context.created_ns, command, order_id="ABCDEF123456"),
        _open_rest_row(context.created_ns, command, order_id="ZZZZZZ999999"),
    ]
    _negative(client, open_orders=both)
    client.advance(305)
    await run_passes(client, 1)
    assert current.intent_id in client._resolver_contradiction_details
    assert read_context(client, current.intent_id).venue_order_id == submit_chain.NO_VENUE_ORDER_ID
    _negative(client, open_orders=both[:1])
    client.advance(65)
    await run_passes(client, 1)
    assert read_context(client, current.intent_id).venue_order_id == VENUE_ID
    await client._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize("indicator", ["MANUAL_ORDER_INDICATOR_MANUAL", None])
async def test_a_manual_or_unmarked_open_order_is_never_adopted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, indicator: str | None
) -> None:
    """B4 review F2 (adopt path): an operator's own order that happens to echo-match
    the rest is a CONTRADICTION, never the bot's order."""
    client, current, command = await _no_id_rest(tmp_path, monkeypatch)
    context = read_context(client, current.intent_id)
    row = _open_rest_row(context.created_ns, command)
    if indicator is None:
        del row["manualOrderIndicator"]
    else:
        row["manualOrderIndicator"] = indicator
    _negative(client, open_orders=[row])
    client.advance(305)
    await run_passes(client, 2)
    detail = client._resolver_contradiction_details[current.intent_id]
    assert detail["reason"] == "in_window_open_order"
    assert read_context(client, current.intent_id).venue_order_id == submit_chain.NO_VENUE_ORDER_ID
    assert client._store_get(client_module.RESTING_INDEX_KEY) is None
    assert client._latch.current_open() is not None
    await client._disconnect()


def test_open_orders_path_constant_is_the_stubbed_one() -> None:
    """Non-vacuity of the stub wiring used above."""
    assert OPEN_ORDERS_PATH.startswith("/v1/")
