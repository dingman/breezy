"""EXEC-PAR WP4 review rulings (r5.1 E14.1-E14.9), each test-first.

E14.1 stuck-refusal visibility, E14.2 resolver fairness (latch), E14.3 local
settle guards, E14.4 create-path hardening, E14.5 contradiction counting, E14.7
detector counter reset (the detector also acts at K=1), E14.8 abandon on the
not-open early return.
"""

from __future__ import annotations

import json
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest

from breezy.adapters.polymarket_us.safety import LiveTradingPermissionError
from tests.unit.exec_par_rig import (
    PORTFOLIO_POSITIONS_PATH,
    SEC_NS,
    AmbiguousResolverContext,
    ParRig,
    RetirementReason,
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
    spy_retire,
    submit_chain,
    wire_order,
    wire_positions,
    zero_fill_body,
)
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)

AMBIGUOUS = submit_chain.AMBIGUOUS_REASON


class _RaisingSender(ScriptedSender):
    """A sender whose POST raises: a no-id AMBIGUOUS."""

    def __init__(self) -> None:
        super().__init__(RuntimeError("transport down (test)"))


def _terminal_zero(rig: ParRig, order_id: str, index: int) -> None:
    wire_order(rig, order_id, index, state="ORDER_STATE_CANCELED", cum_quantity=0)


# ---------------------------------------------------------------------------
# E14.1 a settle failure that leaves the AMBIGUOUS refusal latched is visible
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["zero", "noid"])
async def test_settle_failure_leaves_a_visible_stuck_refusal(
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
            tmp_path,
            monkeypatch,
            sender=sender,
            ledger=ledger,
            max_slots=2,
            client_kwargs=kwargs,
        ) as rig:
            assert rig.client.stuck_refusals_after_settle_failure_total == 0
            await rig.client._submit_order(rig.buy())
            (intent_id,) = rig.open_intent_ids()
            if path == "zero":
                backdate(rig.client, intent_id)
                _terminal_zero(rig, "ord-z", 0)
            else:
                rig.client.advance(400)
                payloads = rig.client._private_read._payloads
                payloads[client_module.OPEN_ORDERS_PATH] = {"orders": []}
                payloads[client_module.PORTFOLIO_ACTIVITIES_PATH] = {"activities": [], "eof": True}
            wire_positions(rig, {})
            ledger.settle_raises = 1

            await run_passes(rig.client, count=2)

            assert AMBIGUOUS in rig.client.trading_refusals, "fail-closed: still latched"
            assert rig.client.stuck_refusals_after_settle_failure_total == 1
            lines = rig.client.log_lines("ERROR", "stuck")
            assert len(lines) == 1
            assert rig.slug(0) in lines[0] and "AMBIGUOUS" in lines[0]


# ---------------------------------------------------------------------------
# E14.2 resolver fairness: a failure penalty expires after 300 s
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failure_penalty_orders_failing_slots_after_healthy_then_expires(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        async with par_rig(
            tmp_path, monkeypatch, sender=ScriptedSender(), max_slots=3, connect=False
        ) as rig:
            a = arm_open_intent(rig, 0, age_s=900)
            b = arm_open_intent(rig, 1, age_s=800)
            c = arm_open_intent(rig, 2, age_s=700)
            now = rig.clock.timestamp_ns()
            failures = {a: 2}
            served = {b: 7, c: 5}
            recent = {a: now - 10 * SEC_NS}

            picked = rig.latch.next_open_for_resolution(failures, served, recent)
            assert picked is not None and picked.intent_id == c, "healthy, least recently served"

            stale = {a: now - 301 * SEC_NS}
            picked = rig.latch.next_open_for_resolution(failures, served, stale)
            assert picked is not None and picked.intent_id == a, "penalty expired: by served"

            # The two-argument form keeps the pre-E14 meaning (failures dominate).
            picked = rig.latch.next_open_for_resolution(failures, served)
            assert picked is not None and picked.intent_id == c


@pytest.mark.asyncio
async def test_no_slot_waits_longer_than_k_polls_plus_300s_while_healthy_slots_cycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    poll = 5
    with caps():
        async with par_rig(
            tmp_path, monkeypatch, sender=ScriptedSender(), max_slots=3, connect=False
        ) as rig:
            ids = [arm_open_intent(rig, i, age_s=900 - 100 * i) for i in range(3)]
            failing = ids[0]
            failures: dict[str, int] = {}
            served: dict[str, int] = {}
            last_failure: dict[str, int] = {}
            served_at: dict[str, list[int]] = {i: [] for i in ids}
            for step in range(600):
                now = rig.clock.timestamp_ns()
                picked = rig.latch.next_open_for_resolution(failures, served, last_failure)
                assert picked is not None
                served = {**served, picked.intent_id: step + 1}
                served_at[picked.intent_id].append(step * poll)
                if picked.intent_id == failing:
                    failures = {**failures, failing: failures.get(failing, 0) + 1}
                    last_failure = {**last_failure, failing: now}
                rig.client.advance(poll)
            times = served_at[failing]
            assert len(times) >= 3, "the failing slot is retried, not starved"
            gaps = [later - earlier for earlier, later in pairwise(times)]
            assert max(gaps) <= 3 * poll + 300


# ---------------------------------------------------------------------------
# E14.3 local settle guards at the post-POST zero-fill / reject sites and the
# pre-POST context-failure handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["zero", "reject"])
async def test_post_post_settle_raise_is_guarded_abandons_and_retires(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    kind: str,
) -> None:
    ledger = SpyLedger()
    body = (
        ok(zero_fill_body())
        if kind == "zero"
        else ok(json.dumps({"code": 3, "message": "invalid", "details": []}).encode(), 400)
    )
    with caps():
        async with par_rig(
            tmp_path, monkeypatch, sender=ScriptedSender(body), ledger=ledger
        ) as rig:
            spy_retire(rig, ledger)
            ledger.settle_raises = 1

            await rig.client._submit_order(rig.buy())  # must not raise

            (settle,) = [c for c in ledger.calls if c[0] == "settle"]
            names = [c[0] for c in ledger.calls]
            assert names == ["settle", "abandon", "retire"], names
            assert rig.latch.open_slot_count() == 0
            assert not rig.ledger.has_open_exposure(settle[1])
            assert rig.events_named("OrderCanceled" if kind == "zero" else "OrderRejected")
            assert rig.client.log_lines("ERROR", "settle")


@pytest.mark.asyncio
async def test_pre_post_context_failure_preserves_the_original_store_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    ledger = SpyLedger()
    sender = ScriptedSender(ok(zero_fill_body()))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, ledger=ledger) as rig:
            real_set = rig.client._store_set

            def failing_set(key: str, value: bytes) -> None:
                if key.startswith(client_module.RESOLVER_CONTEXT_KEY_PREFIX):
                    raise OSError("store went away (test)")
                real_set(key, value)

            rig.client._store_set = failing_set
            ledger.settle_raises = 1

            await rig.client._submit_order(rig.buy())  # the denial, not the settle error

            assert rig.denied_reasons() == [submit_chain.STORE_RAISED_REASON]
            assert sender.calls == []
            assert [c[0] for c in ledger.calls] == ["settle", "abandon"]
            assert rig.client.log_lines("ERROR", "settle")


# ---------------------------------------------------------------------------
# E14.4 create-path hardening
# ---------------------------------------------------------------------------


async def _create_path_settle_raise(rig: ParRig, ledger: SpyLedger) -> str:
    rig.sender.responses = [ok(accept_fill_body(rig.slug(0), order_id="ord-f1"))]
    ledger.client = rig.client
    ledger.settle_raises = 1
    with pytest.raises(LiveTradingPermissionError):
        await rig.client._submit_order(rig.buy())
    (intent_id,) = rig.open_intent_ids()
    return intent_id


@pytest.mark.asyncio
async def test_resolver_fill_record_is_idempotent_against_the_create_path_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    ledger = SpyLedger()
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=ScriptedSender(), ledger=ledger) as rig:
            intent_id = await _create_path_settle_raise(rig, ledger)
            instrument = rig.instruments[0]
            assert len(rig.client.fill_records_for(instrument.id)) == 1
            backdate(rig.client, intent_id)
            wire_order(rig, "ord-f1", 0, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.37")
            wire_positions(rig, {rig.slug(0): {"netPosition": "1"}})

            await run_one_pass(rig.client)

            records = rig.client.fill_records_for(instrument.id)
            assert len(records) == 1, "one record per venue order, no double fill record"
            assert rig.latch.open_slot_count() == 0


@pytest.mark.asyncio
async def test_failed_with_id_upgrade_never_lets_the_no_id_route_retire_as_no_fill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    ledger = SpyLedger()
    with caps():
        async with par_rig(
            tmp_path,
            monkeypatch,
            sender=ScriptedSender(),
            ledger=ledger,
            client_kwargs={"no_id_retire_admitted": True},
        ) as rig:
            real_note = rig.client._note_ambiguous_open
            calls = {"count": 0}

            def failing_upgrade(**kwargs: Any) -> None:
                calls["count"] += 1
                if calls["count"] >= 2:  # the pre-POST write (1st) succeeded
                    raise OSError("store went away (test)")
                real_note(**kwargs)

            rig.client._note_ambiguous_open = failing_upgrade
            intent_id = await _create_path_settle_raise(rig, ledger)
            context = AmbiguousResolverContext.from_bytes(
                rig.client._store_get(f"{client_module.RESOLVER_CONTEXT_KEY_PREFIX}{intent_id}")
            )
            assert context.venue_order_id == submit_chain.NO_VENUE_ORDER_ID, "upgrade failed"

            rig.client.advance(400)
            payloads = rig.client._private_read._payloads
            payloads[client_module.OPEN_ORDERS_PATH] = {"orders": []}
            payloads[client_module.PORTFOLIO_ACTIVITIES_PATH] = {"activities": [], "eof": True}
            # The venue shows the real holding, consistent with the durable fill:
            # the evidence alone would classify NO_FILL and retire the intent.
            from tests.unit.polymarket_us_exec_shapes import build_position

            slug = rig.slug(0)
            wire_positions(rig, {slug: {**build_position(slug), "netPosition": "1"}})
            await run_passes(rig.client, count=3)

            assert rig.latch.is_open_intent(intent_id), "a durable fill exists: never NO_FILL"
            assert not rig.events_named("OrderRejected")
            assert rig.client.log_lines("ERROR", "durable fill")


# ---------------------------------------------------------------------------
# E14.5 contradiction_events_total
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminal_zero_with_a_long_holding_is_counted_once_and_stays_counted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=ScriptedSender(), connect=True) as rig:
            intent_id = arm_open_intent(rig, 0, venue_order_id="ord-z", age_s=400, registered=True)
            _terminal_zero(rig, "ord-z", 0)
            wire_positions(rig, {rig.slug(0): {"netPosition": "1"}})
            payloads = rig.client._private_read._payloads
            payloads[client_module.PORTFOLIO_ACTIVITIES_PATH] = {"activities": [], "eof": True}

            await run_passes(rig.client, count=3)

            assert rig.latch.is_open_intent(intent_id), "the holding blocks the zero-fill"
            assert rig.client.contradiction_events_total == 1, "once per intent, not per pass"

            wire_positions(rig, {})  # the holding clears; the intent now retires
            await run_passes(rig.client, count=3)

            assert not rig.latch.is_open_intent(intent_id)
            assert rig.client.contradiction_events_total == 1, "monotonic: retiring never undoes it"


def test_contradiction_events_docstring_names_what_it_counts() -> None:
    doc = client_module.PolymarketUSExecutionClient.contradiction_events_total.__doc__ or ""
    assert "DUPLICATE_SUSPECT" in doc and "holding" in doc and "consistent" in doc


# ---------------------------------------------------------------------------
# E14.7 the detector acts at K=1; its consecutive counter resets on a pass that
# could not evaluate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_counter_resets_on_a_pass_whose_reads_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    monkeypatch.setattr(client_module, "_NO_ID_RECHECK_INTERVAL_NS", 0)
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=ScriptedSender()) as rig:  # K=1
            arm_open_intent(
                rig,
                0,
                venue_order_id="",
                age_s=400,
                wire_quantity="1",
                baseline=("0", "0", 0),
                registered=True,
            )
            slug = rig.slug(0)
            from tests.unit.polymarket_us_exec_shapes import build_position

            doubled = {slug: {**build_position(slug), "netPosition": "2"}}
            wire_positions(rig, doubled)
            payloads = rig.client._private_read._payloads
            payloads[client_module.OPEN_ORDERS_PATH] = {"orders": []}
            payloads[client_module.PORTFOLIO_ACTIVITIES_PATH] = {"activities": [], "eof": True}

            await run_one_pass(rig.client)  # first sighting
            del payloads[PORTFOLIO_POSITIONS_PATH]  # the next pass cannot read positions
            await run_one_pass(rig.client)
            wire_positions(rig, doubled)
            await run_one_pass(rig.client)  # a first sighting AGAIN, not a second
            assert rig.client.duplicate_suspect_total == 0

            await run_one_pass(rig.client)  # now two consecutive evaluable sightings
            assert rig.client.duplicate_suspect_total == 1


# ---------------------------------------------------------------------------
# E14.8 the not-open early return abandons its registry entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("body", ["zero", "accept", "no_order"])
async def test_not_open_early_return_abandons_the_registry_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    body: str,
) -> None:
    with caps():
        async with par_rig(
            tmp_path,
            monkeypatch,
            sender=ScriptedSender(ok(ambiguous_body("ord-a"))),
            client_kwargs={"no_id_retire_admitted": True},
        ) as rig:
            await rig.client._submit_order(rig.buy())
            (intent_id,) = rig.open_intent_ids()
            raw = rig.client._store_get(f"{client_module.RESOLVER_CONTEXT_KEY_PREFIX}{intent_id}")
            context = AmbiguousResolverContext.from_bytes(raw)
            assert rig.ledger.has_open_exposure(intent_id)
            now_ns = rig.clock.timestamp_ns()
            rig.latch.retire(intent_id, RetirementReason.DEFINITIVE_REJECT, now_ns=now_ns)
            rig.client._resolved_by_get_ts_ns[intent_id] = now_ns
            rig.client._resolved_no_id_ts_ns[intent_id] = now_ns

            if body == "zero":
                rig.client._resolve_terminal_zero(context, now_ns)
            elif body == "accept":
                rig.client._resolve_accept_fill(context, None, rig.instruments[0], now_ns)
            else:
                rig.client._resolve_no_order(intent_id, context, now_ns)

            assert not rig.ledger.has_open_exposure(intent_id), "no registry entry leaks"
            assert decimal_spent(rig) == Decimal("0.37"), "abandon adds no spend"
