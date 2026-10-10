"""EXEC-PAR WP4 (r5 5.WP4 + r5.1 E1/E2/E9/E10'/E13): the resolver side.

Selection across slots (H5), by-id guards and scoped clears (H7/H8), settle at
every post-booking site BEFORE ``_retire`` (E1), the integrity-error paths
(E2/E9), the create-path convergence (E10'/E13), the fresh clock and shared
stamp (3.5), and the duplicate detector (3.6).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.adapters.polymarket_us.safety import LiveTradingPermissionError
from tests.unit.exec_par_rig import (
    NEXT_MIDNIGHT_NS,
    SEC_NS,
    AmbiguousResolverContext,
    DurableFillRecord,
    NoRegisterLedger,
    ParRig,
    ScriptedSender,
    SpyLedger,
    accept_fill_body,
    ambiguous_body,
    arm_open_intent,
    backdate,
    caps,
    client_module,
    decimal_spent,
    ok,
    par_rig,
    run_one_pass,
    run_passes,
    run_passes_recording_sleeps,
    spy_retire,
    wire_order,
    wire_positions,
)
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)

AMBIGUOUS = client_module.submit_chain.AMBIGUOUS_REASON
UNBUDGETED = client_module._RESOLVER_FILL_UNBUDGETED


class _RaisingSender(ScriptedSender):
    """A sender whose POST raises: a no-id AMBIGUOUS."""

    def __init__(self) -> None:
        super().__init__(RuntimeError("transport down (test)"))


async def _submit_ambiguous(rig: ParRig, count: int = 2) -> dict[str, str]:
    """Submit ``count`` with-id AMBIGUOUS takes (one per instrument); returns
    ``{slug: intent_id}`` with every context aged past the resolver floors."""
    for index in range(count):
        await rig.client._submit_order(rig.buy(rig.instruments[index]))
    by_slug = {i.slug: i.intent_id for i in rig.latch.open_submit_intents()}
    for intent_id in by_slug.values():
        backdate(rig.client, intent_id)
    return by_slug


def _empty_chain_evidence(rig: ParRig) -> None:
    wire_positions(rig, {})


def _terminal_zero(rig: ParRig, order_id: str, index: int) -> None:
    wire_order(rig, order_id, index, state="ORDER_STATE_CANCELED", cum_quantity=0)


# ---------------------------------------------------------------------------
# H5 selection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slot_b_resolves_while_a_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(ambiguous_body("ord-a")), ok(ambiguous_body("ord-b")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            ids = await _submit_ambiguous(rig)
            wire_order(rig, "ord-a", 0, state="ORDER_STATE_NEW", cum_quantity=0)
            _terminal_zero(rig, "ord-b", 1)
            _empty_chain_evidence(rig)

            await run_passes(rig.client, count=3)

            assert rig.latch.is_open_intent(ids[rig.slug(0)]) is True
            assert rig.latch.is_open_intent(ids[rig.slug(1)]) is False
            assert len(rig.events_named("OrderCanceled")) == 1
            assert rig.client.resolver_error_count == 0


@pytest.mark.asyncio
async def test_resolver_round_robin_skipping_backoff_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(ambiguous_body("ord-a")), ok(ambiguous_body("ord-b")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            await _submit_ambiguous(rig)
            wire_order(rig, "ord-a", 0, state="ORDER_STATE_NEW", cum_quantity=0)
            wire_order(rig, "ord-b", 1, state="ORDER_STATE_NEW", cum_quantity=0)
            _empty_chain_evidence(rig)

            await run_passes(rig.client, count=2)

            order_reads = [p for p in rig.client._private_read.paths if p.startswith("/v1/order/")]
            assert len(order_reads) >= 4
            first_four = order_reads[:4]
            assert first_four[0] != first_four[1], "the second pass serves the OTHER slot"
            assert first_four[0:2] == first_four[2:4], "and then they alternate"


@pytest.mark.asyncio
async def test_one_503_slot_does_not_starve_others(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(ambiguous_body("ord-a")), ok(ambiguous_body("ord-b")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            ids = await _submit_ambiguous(rig)
            # No payload wired for ord-a: its GET raises on every pass.
            _terminal_zero(rig, "ord-b", 1)
            _empty_chain_evidence(rig)

            await run_passes(rig.client, count=4)

            assert rig.latch.is_open_intent(ids[rig.slug(1)]) is False, "B resolved"
            assert rig.latch.is_open_intent(ids[rig.slug(0)]) is True
            failures = rig.client._resolver_intent_failures
            assert failures[ids[rig.slug(0)]] >= 1
            assert ids[rig.slug(1)] not in failures or failures[ids[rig.slug(1)]] == 0


@pytest.mark.asyncio
async def test_global_backoff_still_drives_sleep(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(ambiguous_body("ord-a")), ok(ambiguous_body("ord-b")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            await _submit_ambiguous(rig)
            # The periodic task `_connect` started would share the patched sleep.
            await rig.client._cancel_resolver_task()
            # Neither order has a wired GET: every pass fails.
            sleeps = await run_passes_recording_sleeps(
                rig.client, passes=4, monkeypatch=monkeypatch
            )
            assert sleeps[:4] == [5.0, 5.0, 10.0, 20.0]


@pytest.mark.asyncio
async def test_resolver_corrupt_slot_skipped_others_resolve(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    import json

    sender = ScriptedSender(ok(ambiguous_body("ord-a")), ok(ambiguous_body("ord-b")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            ids = await _submit_ambiguous(rig)
            key = "exec/polymarket_us/intent/current"
            table = json.loads(rig.latch._store.get(key))
            table["slots"][ids[rig.slug(0)]] = 5  # not a record: unreadable
            rig.latch._store.set(key, json.dumps(table, sort_keys=True).encode())
            _terminal_zero(rig, "ord-b", 1)
            _empty_chain_evidence(rig)

            await run_passes(rig.client, count=3)

            assert rig.latch.unreadable_slot_keys() == (ids[rig.slug(0)],)
            assert rig.latch.is_open_intent(ids[rig.slug(1)]) is False, "the healthy slot resolved"
            assert rig.client.resolver_error_count == 0


# ---------------------------------------------------------------------------
# H8 scoped clears
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolving_one_slot_clears_only_its_scoped_ambiguous_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(ambiguous_body("ord-a")), ok(ambiguous_body("ord-b")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            await _submit_ambiguous(rig)
            assert sorted(rig.client.trading_refusal_scopes) == sorted([rig.slug(0), rig.slug(1)])
            wire_order(rig, "ord-a", 0, state="ORDER_STATE_NEW", cum_quantity=0)
            _terminal_zero(rig, "ord-b", 1)
            _empty_chain_evidence(rig)

            await run_passes(rig.client, count=3)

            assert rig.client.trading_refusal_scopes == (rig.slug(0),), "B cleared, A's survives"


@pytest.mark.asyncio
async def test_scoped_ambiguous_refusal_survives_a_successful_reconcile_of_its_slug(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(ambiguous_body("ord-a")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            await rig.client._submit_order(rig.buy(rig.instruments[0]))
            refusals = tuple(rig.client._trading_refusals)
            assert refusals[0].instrument == rig.slug(0)
            assert refusals[0].classification is client_module.RefusalClass.DURABLE
            kept = client_module.refusals_after_successful_reconcile(
                refusals, instrument=rig.slug(0)
            )
            assert kept == refusals, "a successful map of A never clears A's AMBIGUOUS"


@pytest.mark.asyncio
async def test_unscoped_ambiguous_refusal_clears_only_when_no_slot_is_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=ScriptedSender(), max_slots=2) as rig:
            ids = [
                arm_open_intent(rig, 0, venue_order_id="ord-a", registered=True),
                arm_open_intent(rig, 1, venue_order_id="ord-b", registered=True),
            ]
            rig.client._refuse(AMBIGUOUS)  # unscoped, as K=1 writes it
            _terminal_zero(rig, "ord-a", 0)
            _terminal_zero(rig, "ord-b", 1)
            _empty_chain_evidence(rig)

            await run_one_pass(rig.client)
            assert sum(1 for i in ids if rig.latch.is_open_intent(i)) == 1
            assert AMBIGUOUS in rig.client.trading_refusals, "one slot is still open"

            await run_passes(rig.client, count=2)
            assert not any(rig.latch.is_open_intent(i) for i in ids)
            assert AMBIGUOUS not in rig.client.trading_refusals


@pytest.mark.asyncio
async def test_slug_from_record_used_in_no_id_window_only_clear(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        async with par_rig(
            tmp_path,
            monkeypatch,
            sender=ScriptedSender(),
            max_slots=2,
            client_kwargs={"no_id_retire_admitted": True},
        ) as rig:
            # Slot A has NO context (window-only): only its SubmitIntent record
            # can name the slug whose scoped refusal the retirement must clear.
            id_a = arm_open_intent(rig, 0, with_context=False, age_s=400)
            id_b = arm_open_intent(rig, 1, venue_order_id="ord-b", age_s=400)
            rig.client._refuse(AMBIGUOUS, instrument=rig.slug(0))
            rig.client._refuse(AMBIGUOUS, instrument=rig.slug(1))
            wire_positions(rig, {})
            payloads = rig.client._private_read._payloads
            payloads[client_module.OPEN_ORDERS_PATH] = {"orders": []}
            payloads[client_module.PORTFOLIO_ACTIVITIES_PATH] = {"activities": [], "eof": True}

            await run_passes(rig.client, count=3)

            assert not rig.latch.is_open_intent(id_a), "window-only no-id slot retired"
            assert rig.latch.is_open_intent(id_b)
            assert rig.client.trading_refusal_scopes == (rig.slug(1),)


# ---------------------------------------------------------------------------
# E1 / E9: settle before _retire at the zero-fill and no-id sites
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_fill_and_no_id_settle_before_retire_then_cancel_restore_clear_no_raise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    for path, sender, kwargs in (
        ("zero", ScriptedSender(ok(ambiguous_body("ord-z"))), {}),
        ("noid", _RaisingSender(), {"no_id_retire_admitted": True}),
    ):
        ledger = SpyLedger()
        with caps():
            async with par_rig(
                tmp_path / path,
                monkeypatch,
                sender=sender,
                ledger=ledger,
                client_kwargs=kwargs,
            ) as rig:
                spy_retire(rig, ledger)
                await rig.client._submit_order(rig.buy())
                (intent_id,) = rig.open_intent_ids()
                _, count_after_submit = rig.remaining_permit()
                if path == "zero":
                    backdate(rig.client, intent_id)
                    _terminal_zero(rig, "ord-z", 0)
                else:
                    rig.client.advance(400)
                    payloads = rig.client._private_read._payloads
                    payloads[client_module.OPEN_ORDERS_PATH] = {"orders": []}
                    payloads[client_module.PORTFOLIO_ACTIVITIES_PATH] = {
                        "activities": [],
                        "eof": True,
                    }
                _empty_chain_evidence(rig)

                await run_passes(rig.client, count=2)

                names = [c[0] for c in ledger.calls if c[1] == intent_id]
                assert names == ["settle", "retire"], (path, ledger.calls)
                assert rig.client.resolver_error_count == 0
                assert rig.latch.open_slot_count() == 0
                assert AMBIGUOUS not in rig.client.trading_refusals, "the clear ran"
                assert rig.remaining_permit()[1] == count_after_submit + 1, "permit restored"
                assert not rig.ledger.has_open_exposure(intent_id)
                assert decimal_spent(rig) == Decimal(0), "zero-fill releases the headroom"
                assert rig.events_named("OrderCanceled" if path == "zero" else "OrderRejected")


@pytest.mark.asyncio
async def test_zero_fill_releases_headroom(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(ambiguous_body("ord-a")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            ids = await _submit_ambiguous(rig, count=1)
            assert rig.ledger.ambiguous_open_total() == Decimal("0.37")
            _terminal_zero(rig, "ord-a", 0)
            _empty_chain_evidence(rig)

            await run_passes(rig.client, count=2)

            assert rig.ledger.ambiguous_open_total() == Decimal(0)
            assert rig.ledger.uncharged_open_total() == Decimal(0)
            assert decimal_spent(rig) == Decimal(0)
            assert not rig.ledger.has_open_exposure(ids[rig.slug(0)])


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["zero", "noid"])
async def test_zero_fill_and_no_id_settle_raise_abandons_and_retires(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    path: str,
) -> None:
    ledger = SpyLedger()
    sender = ScriptedSender(ok(ambiguous_body("ord-z"))) if path == "zero" else _RaisingSender()
    kwargs = {} if path == "zero" else {"no_id_retire_admitted": True}
    with caps():
        async with par_rig(
            tmp_path, monkeypatch, sender=sender, ledger=ledger, client_kwargs=kwargs
        ) as rig:
            spy_retire(rig, ledger)
            await rig.client._submit_order(rig.buy())
            (intent_id,) = rig.open_intent_ids()
            _, count_after_submit = rig.remaining_permit()
            if path == "zero":
                backdate(rig.client, intent_id)
                _terminal_zero(rig, "ord-z", 0)
            else:
                rig.client.advance(400)
                payloads = rig.client._private_read._payloads
                payloads[client_module.OPEN_ORDERS_PATH] = {"orders": []}
                payloads[client_module.PORTFOLIO_ACTIVITIES_PATH] = {"activities": [], "eof": True}
            _empty_chain_evidence(rig)
            ledger.settle_raises = 1

            await run_passes(rig.client, count=2)

            assert [c[0] for c in ledger.calls if c[1] == intent_id] == [
                "settle",
                "abandon",
                "retire",
            ]
            assert rig.client.resolver_error_count == 1
            assert intent_id not in rig.client._ambiguous_bookings, "booking popped"
            assert rig.latch.open_slot_count() == 0, "retired, never stuck"
            assert rig.remaining_permit()[1] == count_after_submit + 1, "restore still ran"
            assert rig.events_named("OrderCanceled" if path == "zero" else "OrderRejected")
            assert AMBIGUOUS in rig.client.trading_refusals, "the clear is skipped (conservative)"


# ---------------------------------------------------------------------------
# E2: accept-fill integrity error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settle_over_cost_retry_does_not_self_heal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    ledger = SpyLedger()
    sender = ScriptedSender(ok(ambiguous_body("ord-a")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, ledger=ledger) as rig:
            spy_retire(rig, ledger)
            await rig.client._submit_order(rig.buy())  # booked at 0.37
            (intent_id,) = rig.open_intent_ids()
            backdate(rig.client, intent_id)
            wire_order(rig, "ord-a", 0, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.90")
            wire_positions(rig, {rig.slug(0): {"netPosition": "1"}})

            await run_passes(rig.client, count=1)

            settle_calls = [c for c in ledger.calls if c[0] == "settle"]
            assert len(settle_calls) == 1
            assert settle_calls[0][6] is True, "the booking was still reachable at settle time"
            assert ("abandon", intent_id) in ledger.calls
            assert rig.client.resolver_error_count == 1
            assert UNBUDGETED in rig.client.trading_refusals
            assert rig.latch.open_slot_count() == 0, "retired in the same pass"
            assert len(rig.events_named("OrderFilled")) == 1
            assert any(m for m in rig.client.log_lines("ERROR") if "settle" in m.lower())
            before = decimal_spent(rig)
            assert before == Decimal("0.37"), "the authorized cost stays; realized is NOT added"

            await run_passes(rig.client, count=3)
            assert decimal_spent(rig) == before, "no later pass self-heals the spend"
            assert rig.client.resolver_error_count == 1


# ---------------------------------------------------------------------------
# E10' / E13: the create path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_path_settle_raise_converges_to_resolver_latch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    ledger = SpyLedger()
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=ScriptedSender(), ledger=ledger) as rig:
            rig.sender.responses = [ok(accept_fill_body(rig.slug(0), order_id="ord-f1"))]
            ledger.client = rig.client
            ledger.settle_raises = 1

            with pytest.raises(LiveTradingPermissionError):
                await rig.client._submit_order(rig.buy())

            (intent_id,) = rig.open_intent_ids()
            assert ("abandon", intent_id) in ledger.calls
            assert intent_id not in rig.client._ambiguous_bookings
            assert len(rig.events_named("OrderSubmitted")) == 1, "emitted before the re-raise"
            assert rig.events_named("OrderFilled") == []
            raw = rig.client._store_get(f"{client_module.RESOLVER_CONTEXT_KEY_PREFIX}{intent_id}")
            context = AmbiguousResolverContext.from_bytes(raw)
            assert context.venue_order_id == "ord-f1", "upgraded to the with-id route"
            assert not rig.ledger.has_open_exposure(intent_id)
            spent = decimal_spent(rig)

            backdate(rig.client, intent_id)
            wire_order(rig, "ord-f1", 0, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.37")
            wire_positions(rig, {rig.slug(0): {"netPosition": "1"}})
            await run_one_pass(rig.client)

            assert rig.latch.open_slot_count() == 0, "converged within one poll"
            assert UNBUDGETED in rig.client.trading_refusals
            assert len(rig.events_named("OrderFilled")) == 1
            assert len(rig.events_named("OrderSubmitted")) == 1
            assert decimal_spent(rig) == spent, "no spend self-heals"
            record = DurableFillRecord.from_bytes(
                rig.client._store_get("exec/polymarket_us/fill/ord-f1")
            )
            assert record.fee_reconciled is False, "the documented degradation"


# ---------------------------------------------------------------------------
# 3.5 fresh clock and shared stamp
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_ledger_calls_use_fresh_clock_at_k_gt_1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(ambiguous_body("ord-a")), ok(ambiguous_body("ord-b")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            ids = await _submit_ambiguous(rig)
            wire_order(rig, "ord-a", 0, state="ORDER_STATE_NEW", cum_quantity=0)
            _terminal_zero(rig, "ord-b", 1)
            _empty_chain_evidence(rig)
            original = rig.client._order_trade_activity

            async def with_concurrent_authorize(venue_order_id: str, created_ns: int) -> Any:
                join = await original(venue_order_id, created_ns)
                rig.client.advance(20)
                rig.ledger.authorize_order_cost(
                    price_usd=Decimal("0.10"),
                    quantity=Decimal(1),
                    now_ns=rig.clock.timestamp_ns(),
                )
                return join

            rig.client._order_trade_activity = with_concurrent_authorize

            await run_passes(rig.client, count=3)

            assert rig.latch.is_open_intent(ids[rig.slug(1)]) is False, "B retired despite the race"
            assert rig.client.resolver_error_count == 0


@pytest.mark.asyncio
async def test_resolver_fill_ts_event_and_settle_share_one_clock_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    ledger = SpyLedger()
    sender = ScriptedSender(ok(ambiguous_body("ord-a")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, ledger=ledger) as rig:
            ledger.client = rig.client
            await rig.client._submit_order(rig.buy())
            (intent_id,) = rig.open_intent_ids()
            backdate(rig.client, intent_id)
            wire_order(rig, "ord-a", 0, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.37")
            wire_positions(rig, {rig.slug(0): {"netPosition": "1"}})
            rig.client.settable_clock.tick_ns = 1_000  # every read is distinct

            await run_passes(rig.client, count=1)

            (settle,) = [c for c in ledger.calls if c[0] == "settle"]
            _, _, _, _, fill_ts_ns, settle_now_ns, _ = settle
            record = DurableFillRecord.from_bytes(
                rig.client._store_get("exec/polymarket_us/fill/ord-a")
            )
            assert record.ts_event == fill_ts_ns == settle_now_ns


def test_resolver_floors_unchanged_120_300_5_300() -> None:
    assert client_module._RESOLVER_ZERO_FILL_MIN_AGE_NS == 120 * SEC_NS
    assert client_module._RESOLVER_NO_ID_MIN_AGE_NS == 300 * SEC_NS
    assert client_module._RESOLVER_POLL_INTERVAL_SECS == 5
    assert client_module._RESOLVER_BACKOFF_CAP_SECS == 300


# ---------------------------------------------------------------------------
# WP-DR successors: midnight, registered vs unregistered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_fill_after_midnight_settles_via_registry_no_latch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(ambiguous_body("ord-a")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender) as rig:
            rig.client.set_now(NEXT_MIDNIGHT_NS - 10 * SEC_NS)
            await rig.client._submit_order(rig.buy())
            (intent_id,) = rig.open_intent_ids()
            backdate(rig.client, intent_id)
            rig.client.set_now(NEXT_MIDNIGHT_NS + 200 * SEC_NS)
            wire_order(rig, "ord-a", 0, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.37")
            wire_positions(rig, {rig.slug(0): {"netPosition": "1"}})

            await run_passes(rig.client, count=2)

            assert rig.latch.open_slot_count() == 0, "retired exactly once"
            assert UNBUDGETED not in rig.client.trading_refusals
            assert len(rig.events_named("OrderFilled")) == 1
            assert rig.ledger.cross_day_settles_total == 1
            assert decimal_spent(rig) == Decimal("0.37"), "the discovery day counts it once"


@pytest.mark.asyncio
async def test_accept_fill_after_midnight_unregistered_latches_fill_unbudgeted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Production reaches the latch only through a registry failure: here the
    registry double never registers, so the settle carries an unregistered
    booking and the integrity path falls back to the UNBUDGETED latch."""
    sender = ScriptedSender(ok(ambiguous_body("ord-a")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, ledger=NoRegisterLedger()) as rig:
            rig.client.set_now(NEXT_MIDNIGHT_NS - 10 * SEC_NS)
            await rig.client._submit_order(rig.buy())
            (intent_id,) = rig.open_intent_ids()
            backdate(rig.client, intent_id)
            rig.client.set_now(NEXT_MIDNIGHT_NS + 200 * SEC_NS)
            wire_order(rig, "ord-a", 0, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.37")
            wire_positions(rig, {rig.slug(0): {"netPosition": "1"}})

            await run_passes(rig.client, count=2)

            assert rig.latch.open_slot_count() == 0, "must not stay OPEN"
            assert UNBUDGETED in rig.client.trading_refusals
            assert intent_id not in rig.client._ambiguous_bookings


# ---------------------------------------------------------------------------
# E1 leak backstop and the retire-path property
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retire_logs_error_once_when_an_entry_is_still_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(ambiguous_body("ord-a")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender) as rig:
            await rig.client._submit_order(rig.buy())
            (intent_id,) = rig.open_intent_ids()
            assert rig.ledger.has_open_exposure(intent_id)

            rig.client._retire(intent_id, "OPERATOR_CLEARED", rig.clock.timestamp_ns())

            assert rig.ledger.has_open_exposure(intent_id), "the entry stays: headroom stays held"
            assert rig.client.resolver_error_count == 1
            assert len(rig.client.log_lines("ERROR", "open exposure")) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scenario", ["create_zero", "create_reject", "create_fill", "resolver_zero", "resolver_fill"]
)
async def test_every_retire_path_leaves_no_open_exposure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    scenario: str,
) -> None:
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=ScriptedSender()) as rig:
            slug = rig.slug()
            bodies = {
                "create_zero": client_module.json.dumps(
                    {
                        "id": "ord-1",
                        "executions": [],
                        "state": "ORDER_STATE_CANCELED",
                        "cumQuantity": 0,
                    }
                ).encode(),
                "create_reject": client_module.json.dumps(
                    {"code": 3, "message": "invalid", "details": []}
                ).encode(),
                "create_fill": accept_fill_body(slug, order_id="ord-1"),
            }
            if scenario.startswith("create"):
                status = 400 if scenario == "create_reject" else 200
                rig.sender.responses = [ok(bodies[scenario], status)]
                await rig.client._submit_order(rig.buy())
            else:
                rig.sender.responses = [ok(ambiguous_body("ord-1"))]
                await rig.client._submit_order(rig.buy())
                (pending,) = rig.open_intent_ids()
                backdate(rig.client, pending)
                if scenario == "resolver_zero":
                    _terminal_zero(rig, "ord-1", 0)
                    _empty_chain_evidence(rig)
                else:
                    wire_order(
                        rig, "ord-1", 0, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.37"
                    )
                    wire_positions(rig, {slug: {"netPosition": "1"}})
                await run_passes(rig.client, count=2)

            retired = rig.latch.current()
            assert retired is not None and rig.latch.open_slot_count() == 0
            assert not rig.ledger.has_open_exposure(retired.intent_id)
            assert rig.client.resolver_error_count == 0
            assert rig.client.log_lines("ERROR", "open exposure") == []


# ---------------------------------------------------------------------------
# 3.6 duplicate detector
# ---------------------------------------------------------------------------


async def _detector_case(
    rig: ParRig,
    monkeypatch: pytest.MonkeyPatch,
    *,
    leg: str,
    price: str,
    net: str,
    age_s: float = 400.0,
    baseline: tuple[str, str, int] | None = ("0", "0", 0),
    wire_quantity: str | None = "1",
    passes: int = 3,
) -> str:
    # The no-id branch re-checks an intent at most once per interval; the detector
    # needs consecutive PASSES, so the test removes the wall-clock gap, not the guard.
    monkeypatch.setattr(client_module, "_NO_ID_RECHECK_INTERVAL_NS", 0)
    instrument = rig.instruments[0]
    if leg == "no":
        from tests.unit.polymarket_us_exec_shapes import build_no_leg_instrument

        instrument = build_no_leg_instrument()
        rig.client._cache.add_instrument(instrument)
        rig.client._instrument_provider.add(instrument)
    intent_id = arm_open_intent(
        rig,
        0,
        instrument=instrument,
        venue_order_id="",
        age_s=age_s,
        wire_price=price,
        wire_quantity=wire_quantity,
        baseline=baseline,
        registered=True,
    )
    from tests.unit.polymarket_us_exec_shapes import build_position

    slug = rig.slug(0)
    wire_positions(rig, {slug: {**build_position(slug), "netPosition": net}})
    payloads = rig.client._private_read._payloads
    payloads[client_module.OPEN_ORDERS_PATH] = {"orders": []}
    payloads[client_module.PORTFOLIO_ACTIVITIES_PATH] = {"activities": [], "eof": True}
    if passes == 1:
        await run_one_pass(rig.client)
    else:
        await run_passes(rig.client, count=passes)
    return intent_id


@pytest.mark.asyncio
@pytest.mark.parametrize("leg,single,doubled", [("yes", "1", "2"), ("no", "-1", "-2")])
@pytest.mark.parametrize("price", ["0.08", "0.92"])
async def test_duplicate_detector_single_fill_does_not_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    leg: str,
    single: str,
    doubled: str,
    price: str,
) -> None:
    del doubled
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=ScriptedSender()) as rig:
            await _detector_case(rig, monkeypatch, leg=leg, price=price, net=single)
            assert rig.client.contradiction_events_total == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("leg,single,doubled", [("yes", "1", "2"), ("no", "-1", "-2")])
@pytest.mark.parametrize("price", ["0.08", "0.92"])
async def test_duplicate_detector_doubled_holding_trips(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    leg: str,
    single: str,
    doubled: str,
    price: str,
) -> None:
    del single
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=ScriptedSender()) as rig:
            await _detector_case(rig, monkeypatch, leg=leg, price=price, net=doubled)
            assert rig.client.contradiction_events_total == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["no_baseline", "no_wire_quantity"])
async def test_duplicate_detector_none_baseline_or_wire_quantity_not_evaluable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    case: str,
) -> None:
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=ScriptedSender()) as rig:
            await _detector_case(
                rig,
                monkeypatch,
                leg="yes",
                price="0.40",
                net="9",
                baseline=None if case == "no_baseline" else ("0", "0", 0),
                wire_quantity=None if case == "no_wire_quantity" else "1",
            )
            assert rig.client.contradiction_events_total == 0
            assert rig.client.resolver_error_count == 0


@pytest.mark.asyncio
async def test_duplicate_detector_needs_second_pass_and_lag_guard_age(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        async with par_rig(tmp_path / "young", monkeypatch, sender=ScriptedSender()) as rig:
            # Lower the no-id floor so the intent is examined at all: only the
            # detector's own lag guard (300 s) is then what keeps it quiet.
            with monkeypatch.context() as local:
                local.setattr(client_module, "_RESOLVER_NO_ID_MIN_AGE_NS", 100 * SEC_NS)
                await _detector_case(
                    rig, local, leg="yes", price="0.40", net="2", age_s=250.0, passes=4
                )
            assert rig.client.contradiction_events_total == 0, "younger than the lag guard"
        async with par_rig(tmp_path / "old", monkeypatch, sender=ScriptedSender()) as rig2:
            await _detector_case(rig2, monkeypatch, leg="yes", price="0.40", net="2", passes=1)
            # One pass is a first sighting at most: it needs a second consecutive pass.
            first = rig2.client.contradiction_events_total
            await run_passes(rig2.client, count=2)
            assert first == 0 and rig2.client.contradiction_events_total == 1


@pytest.mark.asyncio
async def test_duplicate_detector_records_contradiction_not_just_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=ScriptedSender()) as rig:
            intent_id = await _detector_case(rig, monkeypatch, leg="yes", price="0.40", net="2")
            (detail,) = rig.client.resolver_evidence_contradictions
            assert detail["intent_id"] == intent_id
            assert detail["event"] == "resolver_duplicate_suspect"
            assert rig.client.contradiction_events_total == 1
            assert rig.latch.is_open_intent(intent_id), "a contradiction never retires"


def test_leg_magnitude_of_signed_net_uses_the_no_as_short_yes_sign() -> None:
    magnitude = client_module._leg_magnitude_of_signed_net
    assert magnitude("2", "yes") == Decimal(2)
    assert magnitude("-2", "yes") == Decimal(0)
    assert magnitude("-2", "no") == Decimal(2)
    assert magnitude("2", "no") == Decimal(0)
    assert magnitude("not-a-number", "yes") is None
