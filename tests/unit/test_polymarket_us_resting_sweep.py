"""S4 WP4 (ARM maker-sharp B5): restart rehydration, the boot sweep and the own-order rule.

Plan: S4 r4 delta sections 2 WP4 (4b, 4e), 5 (the cancel-all guard, certification) and
9; ARM plan r2 delta D2; B4 security review items 1 and 3.

Every sender and private read is a local double: no network, no venue contact.
No ``exec`` import here (barrier X1): everything goes through ``ambig_latch_rig``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.domain.exec_slots import Admit, SlotRecord, SlotTableView, Wait, admit
from breezy.strategy.current_rung_hold.trial_day_latch import (
    startup_evidence_permits_arm,
    startup_evidence_refusal_reason,
)
from tests.unit.ambig_latch_rig import (
    OPEN_ORDERS_PATH,
    client_module,
    gate_env,  # noqa: F401 -- used via usefixtures
    reboot_client,
    submit_chain,
    wire_payloads,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)
from tests.unit.polymarket_us_exec_shapes import build_instrument, build_no_leg_instrument
from tests.unit.test_polymarket_us_resting_adopt import _no_id_rest
from tests.unit.test_polymarket_us_resting_cancel import CancelSender, _rig
from tests.unit.test_polymarket_us_resting_submit import (
    _id_n,
    _rest_command,
    _submit_rest,
    _venue_order,
)

_INDEX_KEY: Final[str] = client_module.RESTING_INDEX_KEY
_EVIDENCE_KEY: Final[str] = client_module.STARTUP_EVIDENCE_KEY


async def _second_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    first: Any,
    first_cm: Any,
    *,
    sender: CancelSender | None,
    payloads: dict[str, Any] | None = None,
) -> Any:
    """Reboot over the first process's store with ``sender`` injected; both leg
    instruments are loaded. NOT yet connected."""
    client, latch_cm = await reboot_client(
        tmp_path, monkeypatch, first_latch_cm=first_cm, first_client=first, admitted=True
    )
    for inst in (build_instrument(), build_no_leg_instrument()):
        client._cache.add_instrument(inst)
        client._instrument_provider.add(inst)
    client.latch_cm = latch_cm  # keeps the flock held (dropping it GCs the generator)
    client._order_sender = sender
    client._resting_accept_admitted = True
    wired = wire_payloads(client)  # also makes sure the open-orders path answers
    wired.update(payloads or {})
    return client


def _open_row(command: Any, n: int, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = _venue_order(command, id=_id_n(n))["order"]
    row.update(overrides)
    return row


def _cancel_posts(sender: CancelSender) -> list[str]:
    return [c["order_id"] for c in sender.cancels]


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_restart_with_bound_rest_blocks_admission_until_swept_or_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B4 review item 1: after a restart a live bound rest has a registered exposure
    (unknown notional, so admission is REFUSED) and the unresolved-sweep latch keeps
    NEW rests refused; a terminal read releases both."""
    rig = await _rig(tmp_path, monkeypatch)
    command = await _submit_rest(rig, 0)
    intent_id = rig.client._resting_bookings[_id_n(0)][0]
    payloads = {
        submit_chain.order_by_id_path(_id_n(0)): rig.client._private_read._payloads[
            submit_chain.order_by_id_path(_id_n(0))
        ]
    }
    sender = CancelSender()  # a cancel POST does NOT change the order: it stays NEW
    second = await _second_process(
        tmp_path, monkeypatch, rig.client, rig.client.latch_cm, sender=sender, payloads=payloads
    )
    await second._connect()
    # the rehydrated rest is a registered, unknown-notional exposure ...
    assert second._ledger.has_open_exposure(intent_id)
    now = second._clock.timestamp_ns()
    refusal = second._ledger.exposure_admission_refusal(Decimal("0.40"), Decimal(1), now)
    assert refusal is not None and "unknown notional" in refusal
    # ... the sweep made exactly one attempt (bounded: _connect cannot hang) and latched
    assert _cancel_posts(sender) == [_id_n(0)]
    assert [r.reason for r in second._trading_refusals] == [
        submit_chain.RESTING_CANCEL_UNCONFIRMED_REASON
    ]
    assert json.loads(second._store_get(_INDEX_KEY)) == [_id_n(0)], "no row deleted unread"
    assert _id_n(0) not in second._this_process_resting_ids
    assert second._resting_bookings[_id_n(0)] == (intent_id, None)
    # a NEW rest is denied with zero POSTs while it is unresolved
    new_command = _rest_command(second)
    await second._submit_order(new_command)
    assert sender.calls == []
    # a terminal read (the venue cancelled it) releases the exposure and the latch
    _set_state_on(second, 0, "ORDER_STATE_CANCELED")
    assert await second._cancel_resting_order([_id_n(0)], max_passes=1) == frozenset()
    assert not second._ledger.has_open_exposure(intent_id)
    assert (
        second._ledger.exposure_admission_refusal(
            Decimal("0.40"), Decimal(1), second._clock.timestamp_ns()
        )
        is None
    )
    assert second._trading_refusals == []
    assert json.loads(second._store_get(_INDEX_KEY)) == []
    assert not second._budget_was_restored(_id_n(0)), "never restored to this process's permit"
    del command
    await second._disconnect()


def _set_state_on(client: Any, n: int, state: str, cum: int = 0) -> None:
    payloads: dict[str, Any] = client._private_read._payloads
    payloads[submit_chain.order_by_id_path(_id_n(n))]["order"].update(
        {"state": state, "cumQuantity": cum}
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_restart_with_an_unreadable_index_issues_zero_posts_and_keeps_the_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    await _submit_rest(rig, 0)
    rig.client._store_set(_INDEX_KEY, b"{not json")
    sender = CancelSender()
    second = await _second_process(
        tmp_path, monkeypatch, rig.client, rig.client.latch_cm, sender=sender
    )
    await second._connect()
    assert sender.cancels == [] and sender.cancel_alls == []
    assert second._trading_refusals, "the unreadable-index refusal is kept (fail closed)"
    assert second._resting_bookings == {}
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_boot_sweep_cancels_every_ledger_id_and_confirms_by_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    await _submit_rest(rig, 0)
    await _submit_rest(rig, 1)
    src_payloads: dict[str, Any] = rig.client._private_read._payloads
    payloads = {
        submit_chain.order_by_id_path(_id_n(n)): src_payloads[
            submit_chain.order_by_id_path(_id_n(n))
        ]
        for n in (0, 1)
    }
    sender = CancelSender()
    second = await _second_process(
        tmp_path, monkeypatch, rig.client, rig.client.latch_cm, sender=sender, payloads=payloads
    )
    sender.on_cancel = lambda oid: _set_state_on(second, int(oid[-1]), "ORDER_STATE_CANCELED")
    await second._connect()
    assert sorted(_cancel_posts(sender)) == [_id_n(0), _id_n(1)]
    assert sender.cancel_alls == [], "per-order only while the slug pin is False"
    assert json.loads(second._store_get(_INDEX_KEY)) == []
    assert second._trading_refusals == []
    assert second._resting_bookings == {}
    assert second._cancel_in_flight == frozenset()
    reads = [p for p in second._private_read.paths if p == OPEN_ORDERS_PATH]
    assert len(reads) >= 2, "the sweep's certifying re-read plus the startup evidence read"
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_empty_ledger_sweep_issues_zero_posts_and_reads_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    sender = CancelSender()
    second = await _second_process(
        tmp_path, monkeypatch, rig.client, rig.client.latch_cm, sender=sender
    )
    await second._connect()
    before = list(second._private_read.paths)
    await second._sweep_resting_orders_at_boot()
    assert sender.cancels == [] and sender.cancel_alls == []
    assert list(second._private_read.paths) == before, "an empty ledger reads nothing"
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_boot_sweep_does_not_run_without_a_sender(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    await _submit_rest(rig, 0)
    second = await _second_process(
        tmp_path, monkeypatch, rig.client, rig.client.latch_cm, sender=None
    )
    await second._connect()
    assert json.loads(second._store_get(_INDEX_KEY)) == [_id_n(0)], "no row deleted"
    assert second._swept_resting_intent_ids == frozenset()
    assert second.log_lines("error", "sweep does not run")
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_boot_sweep_reread_failure_latches_and_marks_no_intent_swept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    await _submit_rest(rig, 0)
    src: dict[str, Any] = rig.client._private_read._payloads
    sender = CancelSender()
    # an open-orders reply carrying an UNKNOWN envelope key cannot be certified empty
    second = await _second_process(
        tmp_path,
        monkeypatch,
        rig.client,
        rig.client.latch_cm,
        sender=sender,
        payloads={
            submit_chain.order_by_id_path(_id_n(0)): src[submit_chain.order_by_id_path(_id_n(0))],
            OPEN_ORDERS_PATH: {"orders": [], "nextCursor": "abc"},
        },
    )
    sender.on_cancel = lambda oid: _set_state_on(second, 0, "ORDER_STATE_CANCELED")
    await second._connect()
    assert [r.reason for r in second._trading_refusals] == [
        submit_chain.RESTING_CANCEL_UNCONFIRMED_REASON
    ]
    assert second._swept_resting_intent_ids == frozenset()
    assert second.log_lines("error", "boot-sweep")
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
@pytest.mark.parametrize("slug_busy", [False, True])
async def test_boot_sweep_marks_a_no_id_resting_intent_swept_only_on_a_confirmed_empty_slug(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, slug_busy: bool
) -> None:
    client, current, command = await _no_id_rest(tmp_path, monkeypatch)
    sender = CancelSender()
    open_rows = [_open_row(command, 0)] if slug_busy else []
    second = await _second_process(
        tmp_path,
        monkeypatch,
        client,
        client.latch_cm,
        sender=sender,
        payloads={OPEN_ORDERS_PATH: {"orders": open_rows}},
    )
    await second._connect()
    if slug_busy:
        assert second._swept_resting_intent_ids == frozenset()
        assert [r.reason for r in second._trading_refusals][:1] == [
            submit_chain.RESTING_CANCEL_UNCONFIRMED_REASON
        ]
        assert sender.cancels == [], "an unbound/no-id order is never cancelled per id"
    else:
        assert second._swept_resting_intent_ids == frozenset({current.intent_id})
        assert second._trading_refusals == [] or all(
            r.reason == submit_chain.AMBIGUOUS_REASON for r in second._trading_refusals
        )
    assert sender.cancel_alls == [], "the slug pin is False: no venue cancel-all"
    await second._disconnect()


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_unbound_open_order_is_never_cancelled_by_the_sweep_and_still_refuses_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    command = await _submit_rest(rig, 0)
    src: dict[str, Any] = rig.client._private_read._payloads
    sender = CancelSender()
    foreign = _open_row(command, 7)  # same slug, NOT in the ledger
    second = await _second_process(
        tmp_path,
        monkeypatch,
        rig.client,
        rig.client.latch_cm,
        sender=sender,
        payloads={
            submit_chain.order_by_id_path(_id_n(0)): src[submit_chain.order_by_id_path(_id_n(0))],
            OPEN_ORDERS_PATH: {"orders": [foreign]},
        },
    )
    sender.on_cancel = lambda oid: _set_state_on(second, 0, "ORDER_STATE_CANCELED")
    await second._connect()
    assert _cancel_posts(sender) == [_id_n(0)], "only the ledger id; never the unbound one"
    assert second.log_lines("error", "unbound")
    evidence = json.loads(second._store_get(_EVIDENCE_KEY))
    assert [o["own_resting"] for o in evidence["open_orders"]] == [False]
    assert not startup_evidence_permits_arm(evidence)
    await second._disconnect()


# -- the own-order rule (4b) -----------------------------------------------------


async def _evidence_with_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, bound_slug_matches: bool = True
) -> dict[str, Any]:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    command = await _submit_rest(rig, 0)
    row = _open_row(command, 0)
    if not bound_slug_matches:
        row["marketSlug"] = "tc-temp-nyc-other"
    client._private_read._payloads[OPEN_ORDERS_PATH] = {"orders": [row]}
    await client._refresh_startup_position_evidence()
    evidence: dict[str, Any] = json.loads(client._store_get(_EVIDENCE_KEY))
    await client._disconnect()
    return evidence


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_map_bound_resting_orders_do_not_refuse_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = await _evidence_with_open(tmp_path, monkeypatch)
    assert [o["own_resting"] for o in evidence["open_orders"]] == [True]
    assert startup_evidence_refusal_reason(evidence) is None
    assert startup_evidence_permits_arm(evidence)


@pytest.mark.asyncio
@pytest.mark.usefixtures("gate_env")
async def test_a_bound_id_on_a_different_slug_is_not_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evidence = await _evidence_with_open(tmp_path, monkeypatch, bound_slug_matches=False)
    assert [o["own_resting"] for o in evidence["open_orders"]] == [False]
    assert not startup_evidence_permits_arm(evidence)


def _legacy_evidence(open_orders: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "v": 1,
        "ts_ns": 1,
        "eof_complete": True,
        "position_read_refused": False,
        "fill_walk_complete": True,
        "positions": [],
        "open_orders_read_refused": False,
        "open_orders": open_orders,
    }


def test_unbound_open_order_still_refuses_arm_and_a_mixed_book_refuses() -> None:
    own = {"venue_order_id": "A", "market_slug": "s", "state": "N", "own_resting": True}
    foreign = {"venue_order_id": "B", "market_slug": "s", "state": "N", "own_resting": False}
    assert startup_evidence_permits_arm(_legacy_evidence([own]))
    assert startup_evidence_permits_arm(_legacy_evidence([]))
    assert not startup_evidence_permits_arm(_legacy_evidence([foreign]))
    assert not startup_evidence_permits_arm(_legacy_evidence([own, foreign]))
    # anything but the boolean True is not "own" (a string, 1, None, a missing key)
    for value in ("true", 1, None):
        assert not startup_evidence_permits_arm(_legacy_evidence([{**own, "own_resting": value}]))


def test_pre_s4_evidence_bytes_decode_own_resting_false() -> None:
    """[CHAR] A record written before the key existed decodes ``own_resting=False``
    (so a pre-S4 open order can never be mistaken for ours)."""
    payload = _legacy_evidence([{"venue_order_id": "A", "market_slug": "s", "state": "N"}])
    decoded = client_module.StartupPositionEvidence.from_bytes(json.dumps(payload).encode())
    assert [o.own_resting for o in decoded.open_orders] == [False]
    assert not startup_evidence_permits_arm(payload)
    again = json.loads(decoded.to_bytes())
    assert again["open_orders"][0]["own_resting"] is False


# -- B4 review item 3: one open intent per slug ----------------------------------


def test_admission_forbids_two_open_intents_on_one_slug_at_k_greater_than_one() -> None:
    """[CHAR] ``admit`` refuses ``slug_open`` while any OPEN slot holds the slug, and at
    K == 1 refuses any second slot at all: two unresolved intents on one slug cannot
    coexist, so a slug-scoped AMBIGUOUS clear can never release another intent's refusal."""
    open_one = SlotTableView(
        open_slots=(SlotRecord("i-1", "tc-temp-a", False),), unreadable_slots=0, cooloff=()
    )
    assert admit(open_one, "tc-temp-a", False, 4, False, 0) == Wait("slug_open")
    assert admit(open_one, "tc-temp-b", False, 4, False, 0) == Admit()
    assert admit(open_one, "tc-temp-b", False, 1, False, 0) == Wait("slot_open")
