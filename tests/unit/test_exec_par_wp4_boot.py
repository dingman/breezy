"""EXEC-PAR WP4 (r5 3.5 H6, 3.9, r5.1 E6/E7): boot registration and the K guard.

Every intent OPEN at boot is registered as uncharged, AMBIGUOUS open exposure in
the no-await span between the spend seed and ``_spend_seeded = True``; the
seeded partial is derived from the durable record under the seed's own day
filter; a cost/budget bucket above the frozen label (or a derivation failure)
forces K to 1; a K forced to 1 over a v2 table still resolves every slot.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.adapters.polymarket_us.exec_fault import clear_fatal_exec_fault, fatal_exec_fault
from breezy.adapters.polymarket_us.safety import LiveTradingPermissionError
from tests.unit.exec_par_rig import (
    BASE_NS,
    SEC_NS,
    ParRig,
    ScriptedSender,
    ambiguous_body,
    arm_open_intent,
    build_par_rig,
    caps,
    client_module,
    decimal_spent,
    durable_record,
    ok,
    par_rig,
    reboot,
    run_passes,
    wire_order,
    wire_positions,
    zero_fill_body,
)
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)

UNBUDGETED = client_module._RESOLVER_FILL_UNBUDGETED
DAY_NS = 86_400 * SEC_NS


@pytest.fixture(autouse=True)
def _clean_exec_fault_latch() -> Any:
    clear_fatal_exec_fault()
    yield
    clear_fatal_exec_fault()


# ---------------------------------------------------------------------------
# H6 registration
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_boot_registers_uncharged_with_zero_fills(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=ScriptedSender(), connect=False) as rig:
            intent_id = arm_open_intent(rig, 0, venue_order_id="ord-b1", notional="0.40")
            assert not rig.ledger.has_open_exposure(intent_id)

            await rig.client._connect()

            assert rig.ledger.has_open_exposure(intent_id)
            assert rig.ledger.uncharged_open_total() == Decimal("0.40")
            assert rig.ledger.ambiguous_open_total() == Decimal("0.40")
            assert decimal_spent(rig) == Decimal(0), "registration charges nothing"


@pytest.mark.asyncio
async def test_second_connect_in_one_process_does_not_register_twice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=ScriptedSender(), connect=False) as rig:
            intent_id = arm_open_intent(rig, 0, venue_order_id="ord-b1", notional="0.40")

            await rig.client._connect()
            await rig.client._connect()  # a duplicate registration would fail the connect

            assert rig.ledger.has_open_exposure(intent_id)
            assert rig.ledger.uncharged_open_total() == Decimal("0.40"), "counted once"


@pytest.mark.asyncio
async def test_boot_context_less_unknown_key_denies_entries_no_crash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(zero_fill_body()))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2, connect=False) as rig:
            intent_id = arm_open_intent(rig, 0, with_context=False)

            await rig.client._connect()

            assert rig.ledger.has_open_exposure(intent_id)
            assert rig.ledger.unknown_key_count() == 1
            await rig.client._submit_order(rig.buy(rig.instruments[1]))
            assert len(rig.denied_reasons()) == 1
            assert sender.calls == []


@pytest.mark.asyncio
async def test_boot_over_budget_resolver_still_retires_and_denial_is_logged_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(zero_fill_body()))
    with caps(daily="0.60"):
        async with par_rig(
            tmp_path,
            monkeypatch,
            sender=sender,
            max_slots=2,
            connect=False,
            frozen_bucket=">0.50",
        ) as rig:
            intent_id = arm_open_intent(rig, 0, venue_order_id="ord-b1", notional="0.40")
            await rig.client._connect()

            await rig.client._submit_order(rig.buy(rig.instruments[1]))
            assert len(rig.denied_reasons()) == 1, "0.40 uncharged + 0.37 passes the 0.60 budget"
            assert sender.calls == []
            assert rig.day_stop_marker() is None

            wire_order(rig, "ord-b1", 0, state="ORDER_STATE_CANCELED", cum_quantity=0)
            wire_positions(rig, {})
            await run_passes(rig.client, count=2)

            assert not rig.latch.is_open_intent(intent_id), "the resolver retired it"
            assert not rig.ledger.has_open_exposure(intent_id)
            await rig.client._submit_order(rig.buy(rig.instruments[1]))
            assert len(sender.calls) == 1, "headroom is back once the slot settled"


@pytest.mark.asyncio
async def test_boot_permit_untouched_by_open_intent_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=ScriptedSender(), connect=False) as rig:
            arm_open_intent(rig, 0, venue_order_id="ord-b1")
            before = rig.remaining_permit()
            await rig.client._connect()
            assert rig.remaining_permit() == before


@pytest.mark.asyncio
async def test_boot_zero_fill_retire_no_permit_restore_d3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=ScriptedSender(), connect=False) as rig:
            intent_id = arm_open_intent(rig, 0, venue_order_id="ord-b1")
            await rig.client._connect()
            before = rig.remaining_permit()
            wire_order(rig, "ord-b1", 0, state="ORDER_STATE_CANCELED", cum_quantity=0)
            wire_positions(rig, {})

            await run_passes(rig.client, count=2)

            assert not rig.latch.is_open_intent(intent_id)
            assert not rig.ledger.has_open_exposure(intent_id)
            assert rig.remaining_permit() == before, "no booking in this process: no restore (D3)"


@pytest.mark.asyncio
async def test_boot_fill_not_flagged_fill_unbudgeted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=ScriptedSender(), connect=False) as rig:
            intent_id = arm_open_intent(rig, 0, venue_order_id="ord-b1", notional="0.40")
            await rig.client._connect()
            wire_order(rig, "ord-b1", 0, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.40")
            wire_positions(rig, {rig.slug(0): {"netPosition": "1"}})

            await run_passes(rig.client, count=2)

            assert not rig.latch.is_open_intent(intent_id)
            assert UNBUDGETED not in rig.client.trading_refusals
            assert decimal_spent(rig) == Decimal("0.40"), "the fill's cost counts once"


@pytest.mark.asyncio
async def test_boot_interleave_retire_before_and_after_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=ScriptedSender(), connect=False) as rig:
            intent_id = arm_open_intent(rig, 0, venue_order_id="ord-b1", notional="0.40")
            # The immediate resolver pass inside ``_connect`` runs BEFORE the seed
            # and the registration, so it retires the intent unregistered.
            wire_order(rig, "ord-b1", 0, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.40")
            wire_positions(rig, {rig.slug(0): {"netPosition": "1"}})

            await rig.client._connect()

            assert not rig.latch.is_open_intent(intent_id)
            assert not rig.ledger.has_open_exposure(intent_id), "retired before registration"
            assert UNBUDGETED not in rig.client.trading_refusals, "the seed counts it (D8)"
            assert decimal_spent(rig) == Decimal("0.40")


@pytest.mark.asyncio
async def test_boot_registration_failure_fails_connect_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    from tests.unit.exec_par_rig import SpyLedger

    class _Failing(SpyLedger):
        def register_open_exposure(self, *args: Any, **kwargs: Any) -> None:
            raise LiveTradingPermissionError("registry bug (test double)")

    with caps():
        async with par_rig(
            tmp_path, monkeypatch, sender=ScriptedSender(), ledger=_Failing(), connect=False
        ) as rig:
            arm_open_intent(rig, 0, venue_order_id="ord-b1")

            with pytest.raises(LiveTradingPermissionError):
                await rig.client._connect()

            assert fatal_exec_fault() is not None, "the connect fault was recorded"
            assert rig.client._spend_seeded is False


# ---------------------------------------------------------------------------
# seeded_partial (H6)
# ---------------------------------------------------------------------------


async def _restart_with_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    record_ts_ns: int | None,
    record_cost: str = "0.10",
    venue_order_id: str = "ord-p1",
    no_id: bool = False,
) -> ParRig:
    """Process 1 leaves an OPEN intent (and optionally a partial fill record);
    process 2 boots over the same store. Returns the second, connected rig."""
    first = await build_par_rig(tmp_path, monkeypatch, sender=ScriptedSender())
    arm_open_intent(
        first,
        0,
        venue_order_id="" if no_id else venue_order_id,
        notional="0.40",
        registered=False,
    )
    if record_ts_ns is not None:
        first.client.record_fill(
            durable_record(
                first, venue_order_id=venue_order_id, ts_event=record_ts_ns, cost=record_cost
            )
        )
    return await reboot(first, monkeypatch, sender=ScriptedSender())


@pytest.mark.asyncio
async def test_seeded_partial_zero_for_prior_day_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        rig = await _restart_with_record(tmp_path, monkeypatch, record_ts_ns=BASE_NS - 2 * DAY_NS)
        try:
            assert rig.ledger.uncharged_open_total() == Decimal("0.40"), "P = 0: the full notional"
        finally:
            await rig.close()


@pytest.mark.asyncio
async def test_seeded_partial_zero_for_no_id_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        rig = await _restart_with_record(tmp_path, monkeypatch, record_ts_ns=BASE_NS, no_id=True)
        try:
            assert rig.ledger.uncharged_open_total() == Decimal("0.40"), "no-id: no lookup, P = 0"
        finally:
            await rig.close()


@pytest.mark.asyncio
async def test_prior_day_partial_then_today_final_fill_counts_full_realized(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        rig = await _restart_with_record(tmp_path, monkeypatch, record_ts_ns=BASE_NS - 2 * DAY_NS)
        try:
            assert decimal_spent(rig) == Decimal(0), "the prior-day record is not today's seed"
            wire_order(rig, "ord-p1", 0, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.40")
            wire_positions(rig, {rig.slug(0): {"netPosition": "1"}})
            await run_passes(rig.client, count=2)
            assert decimal_spent(rig) == Decimal("0.40")
        finally:
            await rig.close()


@pytest.mark.asyncio
async def test_today_partial_then_final_counts_realized_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        rig = await _restart_with_record(tmp_path, monkeypatch, record_ts_ns=BASE_NS)
        try:
            assert decimal_spent(rig) == Decimal("0.10"), "the seed counted the partial"
            assert rig.ledger.uncharged_open_total() == Decimal("0.30"), "notional - P"
            wire_order(rig, "ord-p1", 0, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.40")
            wire_positions(rig, {rig.slug(0): {"netPosition": "1"}})
            await run_passes(rig.client, count=2)
            assert decimal_spent(rig) == Decimal("0.40"), "0.10 + (0.40 - 0.10), counted once"
            assert UNBUDGETED not in rig.client.trading_refusals
        finally:
            await rig.close()


# ---------------------------------------------------------------------------
# 3.9 / E6 bucket guard
# ---------------------------------------------------------------------------


async def _connect_k2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    frozen: str | None,
    daily: str,
    position: str,
    use_caps: bool = True,
) -> ParRig:
    rig = await build_par_rig(
        tmp_path,
        monkeypatch,
        sender=ScriptedSender(),
        max_slots=2,
        connect=False,
        client_kwargs={"frozen_cost_budget_bucket": frozen},
    )
    try:
        if use_caps:
            with caps(daily=daily, position=position):
                await rig.client._connect()
        else:
            await rig.client._connect()
    except BaseException:
        await rig.close()
        raise
    return rig


@pytest.mark.asyncio
async def test_bucket_outside_frozen_label_forces_k1_and_alerts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    rig = await _connect_k2(tmp_path, monkeypatch, frozen="0.10", daily="100.00", position="25.00")
    try:
        assert rig.latch.max_slots() == 1
        assert rig.client.k_forced_to_1_reason is not None
        assert rig.client.log_lines("ERROR", "forced to K=1")
    finally:
        await rig.close()


@pytest.mark.asyncio
async def test_bucket_derivation_raise_forces_k1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    rig = await _connect_k2(
        tmp_path, monkeypatch, frozen="0.25", daily="", position="", use_caps=False
    )
    try:
        assert rig.latch.max_slots() == 1
        assert rig.client.k_forced_to_1_reason is not None
    finally:
        await rig.close()


@pytest.mark.asyncio
async def test_bucket_label_above_0_50_is_sentinel_forcing_k1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    rig = await _connect_k2(tmp_path, monkeypatch, frozen="0.50", daily="10.00", position="10.00")
    try:
        assert rig.latch.max_slots() == 1, "ratio 1.0 -> '>0.50', above every bucket"
    finally:
        await rig.close()


@pytest.mark.asyncio
async def test_frozen_label_and_guard_share_cap_over_budget_units(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    held = await _connect_k2(
        tmp_path / "held", monkeypatch, frozen="0.05", daily="100.00", position="5.00"
    )
    try:
        assert held.latch.max_slots() == 2, "cap/budget = 0.05 is within the frozen 0.05"
        assert held.client.k_forced_to_1_reason is None
    finally:
        await held.close()
    forced = await _connect_k2(
        tmp_path / "forced", monkeypatch, frozen="≤0.02", daily="100.00", position="5.00"
    )
    try:
        assert forced.latch.max_slots() == 1
    finally:
        await forced.close()


@pytest.mark.asyncio
async def test_k_forced_1_when_frozen_label_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    rig = await _connect_k2(tmp_path, monkeypatch, frozen=None, daily="1000.00", position="10.00")
    try:
        assert rig.latch.max_slots() == 1
    finally:
        await rig.close()


@pytest.mark.asyncio
async def test_restart_with_k_forced_1_over_open_v2_table_resolves_all_slots_and_downgrades(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        first = await build_par_rig(tmp_path, monkeypatch, sender=ScriptedSender(), max_slots=2)
        ids = [
            arm_open_intent(first, 0, venue_order_id="ord-a", registered=True),
            arm_open_intent(first, 1, venue_order_id="ord-b", registered=True),
        ]
        assert json.loads(first.latch._store.get("exec/polymarket_us/intent/current"))["v"] == 2
    second = await reboot(
        first,
        monkeypatch,
        sender=ScriptedSender(ok(zero_fill_body())),
        max_slots=2,
        connect=False,
        client_kwargs={"frozen_cost_budget_bucket": "0.05"},
    )
    try:
        with caps(daily="10.00", position="10.00"):  # ratio 1.0 -> forced to K=1
            await second.client._connect()
            assert second.latch.max_slots() == 1
            assert all(second.latch.is_open_intent(i) for i in ids)
            await second.client._submit_order(second.buy(second.instruments[2]))
            assert second.denied_reasons(), "admission denies while any slot is open"

            for index, name in enumerate(("ord-a", "ord-b")):
                wire_order(second, name, index, state="ORDER_STATE_CANCELED", cum_quantity=0)
            wire_positions(second, {})
            for intent_id in ids:
                _age(second, intent_id)
            await run_passes(second.client, count=4)

            assert not any(second.latch.is_open_intent(i) for i in ids)
            table = json.loads(second.latch._store.get("exec/polymarket_us/intent/current"))
            assert table["v"] == 1 and table["state"] == "RETIRED", "downgraded on drain"
    finally:
        await second.close()


def _age(rig: ParRig, intent_id: str) -> None:
    from tests.unit.exec_par_rig import backdate

    backdate(rig.client, intent_id)


# ---------------------------------------------------------------------------
# D6 wire quantity, and the watcher-facing properties
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wire_quantity_written_at_both_call_sites_and_old_blob_decodes_none(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(ambiguous_body("ord-a")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, record_writes=True) as rig:
            await rig.client._submit_order(rig.buy())
            contexts = [
                json.loads(value)
                for key, value in rig.writes
                if key.startswith(client_module.RESOLVER_CONTEXT_KEY_PREFIX)
                and json.loads(value)["wireMarketSlug"] is not None
            ]
            assert len(contexts) >= 2, "the pre-POST write and the with-id overwrite"
            assert [c["wireQuantity"] for c in contexts[:2]] == ["1", "1"]
            assert contexts[0]["venueOrderId"] == "" and contexts[1]["venueOrderId"] == "ord-a"

            legacy = {k: v for k, v in contexts[1].items() if k != "wireQuantity"}
            decoded = client_module.AmbiguousResolverContext.from_bytes(json.dumps(legacy).encode())
            assert decoded.wire_quantity is None


@pytest.mark.asyncio
async def test_client_exposes_the_watcher_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(ambiguous_body("ord-a")))
    with caps(daily="1.00"):
        async with par_rig(
            tmp_path,
            monkeypatch,
            sender=sender,
            max_slots=2,
            ledger_kwargs={"f_adm": Decimal("0.50"), "f_breaker": Decimal("0.25")},
            frozen_bucket=">0.50",
        ) as rig:
            assert rig.client.ambiguous_notional_breaker_tripped is False
            assert rig.client.contradiction_events_total == 0
            assert rig.client.k_forced_to_1_reason is None
            assert rig.client.unreadable_slot_keys == ()

            await rig.client._submit_order(rig.buy())

            assert rig.client.ambiguous_notional_breaker_tripped is True, "0.37 > 0.25 x 1.00"
            rig.client.advance(90)
            ((intent_id, slug, age_ns),) = rig.client.open_intent_ages
            assert slug == rig.slug() and intent_id in rig.open_intent_ids()
            assert age_ns == 90 * SEC_NS
            wire_positions(rig, {rig.slug(): {"netPosition": "1"}})
            await run_passes(rig.client, count=1)
            assert rig.client.resolver_last_pass_ns == rig.clock.timestamp_ns()
