"""EXEC-PAR WP4 (r5 5.WP4 + r5.1 delta): the order path of the exec client.

Admission before spend (r5 3.3), the body/quantity pins, registration at arm
(E4/E11), settle with a fresh clock after the POST (3.5, D5), exits never
registered, the refusal scope and dedupe (3.4, D3) and the in-flight set (D4).

Everything drives the REAL client, latch and ledger through ``exec_par_rig``;
only the venue sender is a double. The rig's clock is injected and absolute, so
no test depends on the wall clock. Operator caps are bound through the single
whitelisted seam (``tests/unit/operator_control_env``) with placeholder values.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from breezy.adapters.polymarket_us.operator_controls import DailySpendLedger
from breezy.adapters.polymarket_us.safety import LiveTradingPermissionError
from breezy.runtime.submit_intent import BREAKER_KEY
from tests.unit.exec_par_rig import (
    ARMED_EXIT_MANIFEST,
    BASE_NS,
    NEXT_MIDNIGHT_NS,
    SEC_NS,
    GatedSender,
    ParRig,
    RetirementReason,
    ScriptedSender,
    accept_fill_body,
    ambiguous_body,
    caps,
    client_module,
    decimal_spent,
    exit_fill_body,
    ok,
    par_rig,
    submit_chain,
    zero_fill_body,
)
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)

WAIT = submit_chain.OPEN_INTENT_WAIT_REASON
#: A tight placeholder budget makes cap/budget exceed 0.50; the sentinel frozen
#: label keeps K > 1 standing (the live label is not ABOVE it).
SENTINEL_BUCKET = ">0.50"
ADM = {"f_adm": Decimal("0.50"), "f_breaker": Decimal("0.25")}


def _untouched(rig: ParRig, permit: tuple[Any, int], spent: Decimal) -> None:
    """No permit slot, no booking, no day-stop marker since the snapshot."""
    assert rig.remaining_permit() == permit
    assert decimal_spent(rig) == spent
    assert rig.day_stop_marker() is None


# ---------------------------------------------------------------------------
# 3.3 admission before spend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_k_full_denial_before_permit_spend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(
        ok(ambiguous_body("ord-a")), ok(ambiguous_body("ord-b")), ok(zero_fill_body())
    )
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            a, b, c = rig.instruments
            await rig.client._submit_order(rig.buy(a))
            await rig.client._submit_order(rig.buy(b))
            assert rig.latch.open_slot_count() == 2
            permit, spent = rig.remaining_permit(), decimal_spent(rig)

            await rig.client._submit_order(rig.buy(c))

            assert rig.denied_reasons() == [WAIT]
            assert len(sender.calls) == 2
            _untouched(rig, permit, spent)
            assert rig.latch.open_slot_count() == 2


@pytest.mark.asyncio
async def test_same_slug_denial_before_permit_spend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = GatedSender(ok(zero_fill_body(order_id="ord-a")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            first = asyncio.create_task(rig.client._submit_order(rig.buy(rig.instrument)))
            await sender.wait_started(0)
            permit, spent = rig.remaining_permit(), decimal_spent(rig)

            await rig.client._submit_order(rig.buy(rig.instrument))

            assert rig.denied_reasons() == [WAIT]
            _untouched(rig, permit, spent)
            sender.release(0)
            await first
            assert rig.latch.open_slot_count() == 0


@pytest.mark.asyncio
async def test_v2_predicate_false_is_wait_before_permit_spend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = GatedSender(ok(zero_fill_body(order_id="ord-a")))
    with caps():
        async with par_rig(
            tmp_path, monkeypatch, sender=sender, max_slots=2, v2_predicate=lambda: False
        ) as rig:
            first = asyncio.create_task(rig.client._submit_order(rig.buy(rig.instruments[0])))
            await sender.wait_started(0)
            permit, spent = rig.remaining_permit(), decimal_spent(rig)

            await rig.client._submit_order(rig.buy(rig.instruments[1]))

            assert rig.denied_reasons() == [WAIT]
            _untouched(rig, permit, spent)
            sender.release(0)
            await first


@pytest.mark.asyncio
async def test_v2_predicate_raises_is_wait_before_permit_spend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    def boom() -> bool:
        raise RuntimeError("predicate exploded")

    sender = GatedSender(ok(zero_fill_body(order_id="ord-a")))
    with caps():
        async with par_rig(
            tmp_path, monkeypatch, sender=sender, max_slots=2, v2_predicate=boom
        ) as rig:
            first = asyncio.create_task(rig.client._submit_order(rig.buy(rig.instruments[0])))
            await sender.wait_started(0)
            permit, spent = rig.remaining_permit(), decimal_spent(rig)

            await rig.client._submit_order(rig.buy(rig.instruments[1]))

            assert rig.denied_reasons() == [WAIT]
            _untouched(rig, permit, spent)
            sender.release(0)
            await first


@pytest.mark.asyncio
async def test_exposure_precheck_denial_before_permit_spend_no_day_stop_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(ambiguous_body("ord-a")), ok(zero_fill_body()))
    with caps(daily="1.00"):
        async with par_rig(
            tmp_path,
            monkeypatch,
            sender=sender,
            max_slots=2,
            ledger_kwargs=ADM,
            frozen_bucket=SENTINEL_BUCKET,
        ) as rig:
            await rig.client._submit_order(rig.buy(rig.instruments[0]))
            permit, spent = rig.remaining_permit(), decimal_spent(rig)

            await rig.client._submit_order(rig.buy(rig.instruments[1]))

            denied = rig.denied_reasons()
            assert len(denied) == 1
            assert "AMBIGUOUS open exposure" in denied[0]
            assert len(sender.calls) == 1
            _untouched(rig, permit, spent)


class _BlindPrecheckLedger(DailySpendLedger):
    """A ledger whose read-only pre-check always passes, so a test can reach
    the in-lock authority behind it (the race the pre-check cannot close)."""

    def exposure_admission_refusal(
        self, price_usd: Decimal, quantity: Decimal, now_ns: int
    ) -> str | None:
        return None


@pytest.mark.asyncio
async def test_inlock_bound_race_after_passing_precheck_is_plain_deny(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(ambiguous_body("ord-a")), ok(zero_fill_body()))
    with caps(daily="1.00"):
        async with par_rig(
            tmp_path,
            monkeypatch,
            sender=sender,
            max_slots=2,
            ledger=_BlindPrecheckLedger(**ADM),
            frozen_bucket=SENTINEL_BUCKET,
        ) as rig:
            await rig.client._submit_order(rig.buy(rig.instruments[0]))
            (_, count_before) = rig.remaining_permit()
            spent = decimal_spent(rig)

            await rig.client._submit_order(rig.buy(rig.instruments[1]))

            denied = rig.denied_reasons()
            assert len(denied) == 1
            assert "AMBIGUOUS open exposure" in denied[0]
            assert len(sender.calls) == 1, "the in-lock refusal must precede any POST"
            assert rig.remaining_permit()[1] == count_before - 1, "the permit slot may burn once"
            assert decimal_spent(rig) == spent, "no booking was made"
            assert rig.day_stop_marker() is None, "an open-exposure bound is not a day stop"
            assert rig.latch.open_slot_count() == 1, "the second slot was never armed"


@pytest.mark.asyncio
async def test_entry_halt_denies_entries_before_permit_spend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(zero_fill_body()))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            rig.latch.write_breaker_halt("test halt", ts_ns=rig.clock.timestamp_ns())
            permit, spent = rig.remaining_permit(), decimal_spent(rig)

            await rig.client._submit_order(rig.buy(rig.instrument))

            assert rig.denied_reasons() == [WAIT]
            assert sender.calls == []
            _untouched(rig, permit, spent)


@pytest.mark.asyncio
async def test_breaker_record_store_raise_or_garbled_denies_entries_not_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(zero_fill_body()))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            rig.latch._store.set(BREAKER_KEY, b"\xff not json")
            permit, spent = rig.remaining_permit(), decimal_spent(rig)

            await rig.client._submit_order(rig.buy(rig.instrument))

            assert rig.denied_reasons() == [WAIT]
            assert sender.calls == []
            _untouched(rig, permit, spent)

            real_get = rig.latch._store.get

            def raising_get(key: str) -> bytes | None:
                if key == BREAKER_KEY:
                    raise OSError("store went away")
                return real_get(key)  # type: ignore[no-any-return]

            rig.latch._store.get = raising_get
            await rig.client._submit_order(rig.buy(rig.instrument))
            assert rig.denied_reasons() == [WAIT, WAIT]
            assert sender.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("which", ["heartbeat", "resolver_pass"])
async def test_stale_heartbeat_or_stale_resolver_pass_denies_entries_at_k_gt_1_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    which: str,
) -> None:
    now = BASE_NS
    stale = {"heartbeat": (now - 120 * SEC_NS, now), "resolver_pass": (now, now - 700 * SEC_NS)}
    hb_ns, pass_ns = stale[which]
    with caps():
        sender_many = ScriptedSender(ok(zero_fill_body()))
        async with par_rig(tmp_path / "k2", monkeypatch, sender=sender_many, max_slots=2) as rig:
            rig.latch.write_breaker_heartbeat(hb_ns=hb_ns, resolver_pass_ns=pass_ns)
            await rig.client._submit_order(rig.buy(rig.instrument))
            assert rig.denied_reasons() == [WAIT]
            assert sender_many.calls == []

        sender_one = ScriptedSender(ok(zero_fill_body()))
        async with par_rig(tmp_path / "k1", monkeypatch, sender=sender_one) as rig1:
            rig1.latch.write_breaker_heartbeat(hb_ns=hb_ns, resolver_pass_ns=pass_ns)
            await rig1.client._submit_order(rig1.buy(rig1.instrument))
            assert rig1.denied_reasons() == []
            assert len(sender_one.calls) == 1


# ---------------------------------------------------------------------------
# concurrency and the slot table
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_distinct_slugs_both_post_concurrently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = GatedSender(ok(zero_fill_body(order_id="ord-a")), ok(zero_fill_body(order_id="ord-b")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            task_a = asyncio.create_task(rig.client._submit_order(rig.buy(rig.instruments[0])))
            await sender.wait_started(0)
            task_b = asyncio.create_task(rig.client._submit_order(rig.buy(rig.instruments[1])))
            await sender.wait_started(1)
            assert rig.latch.open_slot_count() == 2
            sender.release(0)
            sender.release(1)
            await asyncio.gather(task_a, task_b)

            assert len(sender.calls) == 2
            assert rig.denied_reasons() == []
            assert rig.latch.open_slot_count() == 0
            assert decimal_spent(rig) == Decimal(0)


@pytest.mark.asyncio
async def test_exit_other_slug_passes_when_k_gt_1_but_not_at_k1(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    with caps():
        for slots in (2, 1):
            sender = GatedSender(ok(zero_fill_body(order_id="ord-a")), ok(zero_fill_body()))
            async with par_rig(
                tmp_path / f"k{slots}",
                monkeypatch,
                sender=sender,
                max_slots=slots,
                exit_manifest=ARMED_EXIT_MANIFEST,
            ) as rig:
                entry = asyncio.create_task(rig.client._submit_order(rig.buy(rig.instruments[0])))
                await sender.wait_started(0)
                exit_task = asyncio.create_task(
                    rig.client._submit_order(rig.exit_sell(rig.instruments[1]))
                )
                if slots == 2:
                    await sender.wait_started(1)
                    assert len(sender.calls) == 2, "an exit on another slug is K-exempt"
                    assert rig.denied_reasons() == []
                    sender.release(1)
                else:
                    await exit_task
                    assert len(sender.calls) == 1, "at K=1 an exit waits behind the open entry"
                    assert rig.denied_reasons() == [WAIT]
                sender.release(0)
                await asyncio.gather(entry, exit_task)


# ---------------------------------------------------------------------------
# wire pins and unmappable instruments
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_body_slug_mismatch_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    real_build = submit_chain.build_order_body

    def wrong_slug(order: Any, instrument: Any) -> Any:
        return {**real_build(order, instrument), "marketSlug": "some-other-market"}

    monkeypatch.setattr(submit_chain, "build_order_body", wrong_slug)
    sender = ScriptedSender(ok(zero_fill_body()))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender) as rig:
            permit, spent = rig.remaining_permit(), decimal_spent(rig)
            await rig.client._submit_order(rig.buy(rig.instrument))
            assert len(rig.denied_reasons()) == 1
            assert sender.calls == []
            _untouched(rig, permit, spent)


@pytest.mark.asyncio
async def test_body_quantity_not_equal_order_quantity_denied(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    real_build = submit_chain.build_order_body

    def wrong_quantity(order: Any, instrument: Any) -> Any:
        return {**real_build(order, instrument), "quantity": 2}

    monkeypatch.setattr(submit_chain, "build_order_body", wrong_quantity)
    sender = ScriptedSender(ok(zero_fill_body()))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender) as rig:
            permit, spent = rig.remaining_permit(), decimal_spent(rig)
            await rig.client._submit_order(rig.buy(rig.instrument))
            assert len(rig.denied_reasons()) == 1
            assert sender.calls == []
            _untouched(rig, permit, spent)


@pytest.mark.asyncio
async def test_unmappable_instrument_denied_not_raised(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    def refuse(_instrument_id: Any) -> str:
        raise ValueError("foreign venue")

    monkeypatch.setattr(client_module, "base_slug_of", refuse)
    sender = ScriptedSender(ok(zero_fill_body()))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender) as rig:
            permit, spent = rig.remaining_permit(), decimal_spent(rig)
            await rig.client._submit_order(rig.buy(rig.instrument))
            assert len(rig.denied_reasons()) == 1
            assert sender.calls == []
            _untouched(rig, permit, spent)


# ---------------------------------------------------------------------------
# E4 / E11: registration at arm
# ---------------------------------------------------------------------------


class _RegisterFailsLedger(DailySpendLedger):
    def register_open_exposure(self, *args: Any, **kwargs: Any) -> None:
        raise LiveTradingPermissionError("registry bug (test double)")


@pytest.mark.asyncio
async def test_register_failure_after_arm_releases_booking_retires_slot_no_post(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(zero_fill_body()))
    with caps():
        async with par_rig(
            tmp_path, monkeypatch, sender=sender, ledger=_RegisterFailsLedger()
        ) as rig:
            await rig.client._submit_order(rig.buy(rig.instrument))

            assert sender.calls == [], "a failed registration must never POST"
            assert len(rig.denied_reasons()) == 1
            assert decimal_spent(rig) == Decimal(0), "the booking was released"
            retired = rig.latch.current()
            assert retired is not None
            assert retired.retirement_reason is RetirementReason.DEFINITIVE_REJECT
            assert rig.latch.open_slot_count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("slots", [1, 2])
async def test_exit_fill_never_adds_daily_spend_or_exposure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    slots: int,
) -> None:
    with caps():
        async with par_rig(
            tmp_path,
            monkeypatch,
            sender=ScriptedSender(),
            max_slots=slots,
            exit_manifest=ARMED_EXIT_MANIFEST,
        ) as rig:
            slug = rig.slug()
            rig.sender.responses = [
                ok(
                    exit_fill_body(
                        slug,
                        order_id="ord-exit-1",
                        side="ORDER_SIDE_SELL",
                        intent="ORDER_INTENT_SELL_LONG",
                    )
                )
            ]
            await rig.client._submit_order(rig.exit_sell())

            assert len(rig.sender.calls) == 1
            assert len(rig.events_named("OrderFilled")) == 1
            assert decimal_spent(rig) == Decimal(0)
            assert rig.ledger.uncharged_open_total() == Decimal(0)
            assert rig.ledger.ambiguous_open_total() == Decimal(0)
            assert rig.latch.open_slot_count() == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("slots", [1, 2])
async def test_stuck_exit_does_not_count_toward_f_adm_or_f_breaker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    slots: int,
) -> None:
    sender = ScriptedSender(ok(ambiguous_body("ord-exit-amb")))
    with caps(daily="1.00"):
        async with par_rig(
            tmp_path,
            monkeypatch,
            sender=sender,
            max_slots=slots,
            ledger_kwargs=ADM,
            exit_manifest=ARMED_EXIT_MANIFEST,
            frozen_bucket=SENTINEL_BUCKET,
        ) as rig:
            await rig.client._submit_order(rig.exit_sell())

            assert rig.latch.open_slot_count() == 1, "the AMBIGUOUS exit holds its slot"
            assert rig.ledger.ambiguous_open_total() == Decimal(0)
            assert rig.ledger.unknown_key_count() == 0
            assert rig.ledger.breaker_fraction_exceeded() is False
            (intent_id,) = rig.open_intent_ids()
            assert rig.ledger.has_open_exposure(intent_id) is False


# ---------------------------------------------------------------------------
# 3.4 refusal scope, D3 dedupe, D4 in-flight set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lone_ambiguous_at_k_gt_1_is_scoped_other_slugs_proceed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(ambiguous_body("ord-a")), ok(zero_fill_body()))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            await rig.client._submit_order(rig.buy(rig.instruments[0]))
            assert rig.client.trading_refusal_scopes == (rig.slug(0),)

            await rig.client._submit_order(rig.buy(rig.instruments[1]))

            assert len(sender.calls) == 2, "the other slug is not blocked by a scoped refusal"
            assert rig.denied_reasons() == []
            await rig.client._submit_order(rig.buy(rig.instruments[0]))
            assert len(rig.denied_reasons()) == 1, "the ambiguous slug itself stays blocked"
            assert len(sender.calls) == 2


@pytest.mark.asyncio
async def test_k1_unscoped_refusal_denies_all_as_today(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = ScriptedSender(ok(ambiguous_body("ord-a")), ok(zero_fill_body()))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender) as rig:
            await rig.client._submit_order(rig.buy(rig.instruments[0]))
            assert rig.client.trading_refusal_scopes == ("",)

            await rig.client._submit_order(rig.buy(rig.instruments[1]))

            (reason,) = rig.denied_reasons()
            assert reason.startswith("this client has latched a trading refusal")
            assert len(sender.calls) == 1


@pytest.mark.asyncio
async def test_refuse_dedupes_on_reason_and_instrument(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    async with par_rig(tmp_path, monkeypatch, sender=ScriptedSender(), connect=False) as rig:
        client = rig.client
        client._refuse("same reason", instrument="slug-1")
        client._refuse("same reason", instrument="slug-1")
        assert client.trading_refusal_scopes == ("slug-1",)
        client._refuse("same reason", instrument="slug-2")
        client._refuse("same reason")
        client._refuse("same reason")
        assert client.trading_refusal_scopes == ("slug-1", "slug-2", "")
        assert client.trading_refusals == ("same reason",) * 3
        assert {r.classification for r in client._trading_refusals} == {
            client_module.RefusalClass.DURABLE
        }


@pytest.mark.asyncio
async def test_in_flight_ids_are_a_set_not_a_single_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = GatedSender(ok(zero_fill_body(order_id="ord-a")), ok(zero_fill_body(order_id="ord-b")))
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            task_a = asyncio.create_task(rig.client._submit_order(rig.buy(rig.instruments[0])))
            await sender.wait_started(0)
            task_b = asyncio.create_task(rig.client._submit_order(rig.buy(rig.instruments[1])))
            await sender.wait_started(1)
            both = rig.client._post_in_flight_intent_ids
            assert isinstance(both, frozenset) and len(both) == 2

            sender.release(1)
            await task_b
            remaining = rig.client._post_in_flight_intent_ids
            assert len(remaining) == 1 and remaining < both, "A's POST is still in flight"

            sender.release(0)
            await task_a
            assert rig.client._post_in_flight_intent_ids == frozenset()


# ---------------------------------------------------------------------------
# 3.5 settle with a fresh clock after the POST await (F12, D5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_authorize_during_post_await_does_not_break_true_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = GatedSender(
        ok(accept_fill_body("", order_id="placeholder")), ok(zero_fill_body(order_id="ord-b"))
    )
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            sender.responses[0] = ok(accept_fill_body(rig.slug(0), order_id="ord-a"))
            task_a = asyncio.create_task(rig.client._submit_order(rig.buy(rig.instruments[0])))
            await sender.wait_started(0)
            rig.client.advance(30)
            task_b = asyncio.create_task(rig.client._submit_order(rig.buy(rig.instruments[1])))
            await sender.wait_started(1)

            sender.release(0)
            await task_a
            assert len(rig.events_named("OrderFilled")) == 1
            assert decimal_spent(rig) == Decimal("0.74"), "A realized 0.37, B booked 0.37"

            sender.release(1)
            await task_b
            assert decimal_spent(rig) == Decimal("0.37"), "B's zero-fill released its booking"
            assert rig.latch.open_slot_count() == 0


@pytest.mark.asyncio
async def test_concurrent_authorize_during_post_await_crossing_midnight_no_stuck_slot_events_emitted(  # noqa: E501
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = GatedSender(
        ok(accept_fill_body("", order_id="placeholder")), ok(zero_fill_body(order_id="ord-b"))
    )
    with caps():
        async with par_rig(tmp_path, monkeypatch, sender=sender, max_slots=2) as rig:
            sender.responses[0] = ok(accept_fill_body(rig.slug(0), order_id="ord-a"))
            # The breaker record is absent 12 h after boot at these clocks, which
            # (rightly) denies K > 1 entries: publish a fresh heartbeat at each.
            rig.client.set_now(NEXT_MIDNIGHT_NS - 10 * SEC_NS)
            rig.latch.write_breaker_heartbeat(
                hb_ns=rig.clock.timestamp_ns(), resolver_pass_ns=rig.clock.timestamp_ns()
            )
            task_a = asyncio.create_task(rig.client._submit_order(rig.buy(rig.instruments[0])))
            await sender.wait_started(0)
            rig.client.set_now(NEXT_MIDNIGHT_NS + 10 * SEC_NS)
            rig.latch.write_breaker_heartbeat(
                hb_ns=rig.clock.timestamp_ns(), resolver_pass_ns=rig.clock.timestamp_ns()
            )
            task_b = asyncio.create_task(rig.client._submit_order(rig.buy(rig.instruments[1])))
            await sender.wait_started(1)

            sender.release(0)
            await task_a

            assert len(rig.events_named("OrderSubmitted")) == 1
            assert len(rig.events_named("OrderFilled")) == 1
            assert rig.latch.open_slot_count() == 1, "only B is open: A's slot retired"
            assert rig.client.resolver_error_count == 0
            assert rig.ledger.cross_day_settles_total == 1
            assert client_module._RESOLVER_FILL_UNBUDGETED not in rig.client.trading_refusals
            sender.release(1)
            await task_b
