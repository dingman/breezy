"""EDGE-2 plan r3 (AC6/AC6b) slice B: the terminal-zero budget guard, the
cross-process fill budget refusal, and the ``fill_by_day`` day index.

Authority: ``docs/plans/backlog/EDGE_2026-09-27/
EDGE-2_ambiguous_executions_resolver_plan_r3_2026-09-27.md``, AC6/AC6b, §5
slice B, §7 "Slice B". The r3 convergence record names two tests here as
BINDING for the security verdict:
``test_boot_pass_resolution_of_prior_process_fill_does_not_refuse_and_is_seeded``
(both parametrizations) and ``test_unreadable_day_index_fails_the_seed_closed``.

WHAT THIS FILE ADDS
--------------------
* AC6: ``_resolve_terminal_zero`` restores the current permit's slot only
  when the AMBIGUOUS booking was taken in THIS process (``booking is not
  None``).
* AC6b: ``_resolve_accept_fill`` latches ``_RESOLVER_FILL_UNBUDGETED``
  (DURABLE, instrument-unscoped, same as every other bare ``_refuse``
  producer) iff ``booking is None`` AND ``context.order_side != "SELL"`` AND
  ``self._spend_seeded`` -- never for an exit, never for a fill the boot
  seed has not run past yet (D8).
* The ``FILL_BY_DAY_KEY_PREFIX`` day index, written inline inside
  ``record_fill`` and read by ``_seed_spend_from_durable_fills`` via the new
  ``_seed_candidate_ids`` helper (D9/G4), so a fill recorded under a
  PAST-DAY instrument the provider never loaded is still seeded.

Fixtures reused, never redefined (this repo's own convention):
``_arm_one_ambiguous_intent`` / ``_arm_one_no_leg_ambiguous_intent`` /
``_build_client_with_custom_loader`` / ``_no_leg_order_get_body`` /
``_order_get_body`` / ``_run_resolver_passes``
(``test_current_rung_hold_ambiguous_resolver.py``); ``STRATEGY_ID`` /
``_build_rig`` / ``_build_accept_fill_rig`` / ``_accept_fill_caps`` /
``_ambiguous_with_id_body`` / ``_FakeOrderSender`` /
``_FakeResolverAcceptFillReport`` / ``_issued_permit`` / ``_record_at`` /
``_reopened_fill_record`` (``test_polymarket_us_exec_client.py``);
``enable_operator_gate`` (``test_polymarket_us_permit_issuance.py``);
``build_instrument`` / ``build_position`` (``polymarket_us_exec_shapes.py``);
``write_canonical_verified`` (``test_polymarket_us_submit_order_chain.py``).

No test here assigns a value to either operator-reserved control, and no
test here changes a cap value.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.component import LiveClock
from nautilus_trader.model.events import OrderFilled

from breezy.adapters.polymarket_us.errors import PolymarketUSError
from breezy.adapters.polymarket_us.exec.client import (
    _FILL_WRITE_FAILED,
    _RESOLVER_FILL_UNBUDGETED,
    BUDGET_RESTORE_KEY_PREFIX,
    FILL_BY_DAY_KEY_PREFIX,
    FILL_BY_FINGERPRINT_KEY_PREFIX,
    AmbiguousResolverContext,
)
from breezy.adapters.polymarket_us.exec.endpoints import PORTFOLIO_POSITIONS_PATH
from breezy.adapters.polymarket_us.exec_fault import clear_fatal_exec_fault
from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
    DailySpendLedger,
    utc_day_for_ns,
)
from breezy.adapters.polymarket_us.safety import live_trading_budget_remaining
from breezy.adapters.polymarket_us.transport import VenueResponse
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import SubmitIntentState
from tests.unit.operator_control_env import operator_control_env
from tests.unit.polymarket_us_exec_shapes import (
    build_instrument,
    build_position,
    build_second_instrument,
)
from tests.unit.test_current_rung_hold_ambiguous_resolver import (
    _arm_one_ambiguous_intent,
    _arm_one_no_leg_ambiguous_intent,
    _build_client_with_custom_loader,
    _no_leg_order_get_body,
    _order_get_body,
    _run_resolver_passes,
)
from tests.unit.test_polymarket_us_exec_client import (
    STRATEGY_ID,
    _accept_fill_caps,
    _ambiguous_with_id_body,
    _build_accept_fill_rig,
    _build_rig,
    _FakeOrderSender,
    _FakeResolverAcceptFillReport,
    _issued_permit,
    _record_at,
    _reopened_fill_record,
)
from tests.unit.test_polymarket_us_permit_issuance import enable_operator_gate
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)


@pytest.fixture(autouse=True)
def _clean_exec_fault_latch() -> Iterator[None]:
    """The exec-fault latch is process-global (`exec_fault.py`); the two
    fail-closed day-index tests below deliberately force `_connect` to
    fault, and must not poison a later, unrelated test in this same process
    (mirrors `test_polymarket_us_exec_client.py`'s identical fixture)."""
    clear_fatal_exec_fault()
    yield
    clear_fatal_exec_fault()


# ---------------------------------------------------------------------------
# AC6: the terminal-zero permit restore is gated on `booking is not None`.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_same_process_terminal_zero_still_restores_permit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(order_id, slug=slug, state="ORDER_STATE_CANCELED", cum_quantity=0)
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {},
            "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        _, remaining_count = live_trading_budget_remaining(client._permit)
        assert remaining_count == 2, "same-process terminal-zero must restore the permit slot"
        assert client._store_get(f"{BUDGET_RESTORE_KEY_PREFIX}{order_id}") is not None
        await client._disconnect()


@pytest.mark.asyncio
async def test_cross_process_terminal_zero_does_not_restore_current_permit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        assert client._latch is not None
        armed = client._latch.current()
        assert armed is not None
        # Simulate the post-restart shape directly: no same-process booking.
        client._ambiguous_bookings.pop(armed.intent_id, None)
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(order_id, slug=slug, state="ORDER_STATE_CANCELED", cum_quantity=0)
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {},
            "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        _, remaining_count = live_trading_budget_remaining(client._permit)
        assert remaining_count == 1, (
            "a cross-process terminal-zero must never restore a slot this "
            "process's own ledger never debited (D3)"
        )
        assert client._store_get(f"{BUDGET_RESTORE_KEY_PREFIX}{order_id}") is None
        await client._disconnect()


# ---------------------------------------------------------------------------
# AC6b: the cross-process fill budget refusal.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_process_accept_fill_latches_unbudgeted_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """RED against r2's bare `booking is None` rule (D8): this shape is
    exactly what r2 would have refused on every boot. GREEN under r3: the
    boot's own `_connect` already ran (`_spend_seeded` is `True`), so this
    genuinely-unbudgeted cross-process BUY fill must latch."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        assert client._spend_seeded is True
        assert client._latch is not None
        armed = client._latch.current()
        assert armed is not None
        client._ambiguous_bookings.pop(armed.intent_id, None)
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.40",
        )
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {slug: {"netPosition": "1"}},
            "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        assert _RESOLVER_FILL_UNBUDGETED in client.trading_refusals
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED, (
            "the latch only stops further submits -- the fill is still recorded and retired"
        )
        await client._disconnect()


@pytest.mark.asyncio
async def test_cross_process_no_leg_buy_fill_latches_unbudgeted_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """The venue's GET echoes `(ORDER_SIDE_SELL, ORDER_INTENT_BUY_SHORT)`
    for a NO-leg OPENING buy -- AC6b must still refuse, because the
    classification uses `context.order_side` (the RECORDED "BUY"), never
    the venue's wire-side echo."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, venue_order_id, slug, _latch_cm = await _arm_one_no_leg_ambiguous_intent(
            tmp_path,
        )
        assert client._spend_seeded is True
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{venue_order_id}"
        ] = _no_leg_order_get_body(
            venue_order_id, slug=slug, state="ORDER_STATE_FILLED", cum_quantity=1,
            avg_px="0.40",
        )
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {slug: {**build_position(slug), "netPosition": "-1"}},
            "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        assert _RESOLVER_FILL_UNBUDGETED in client.trading_refusals
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        await client._disconnect()


@pytest.mark.asyncio
async def test_legacy_context_without_order_side_refuses_as_a_buy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """A context blob written before INC-E2 carries no `orderSide` key at
    all -- it decodes as `LONG_ONLY_SIDE` ("BUY"), and AC6b must refuse it
    exactly like an explicit BUY: only a RECORDED "SELL" is exempt."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    order_id = "ord-ac6b-legacy"
    with _accept_fill_caps():
        await rig.client._connect()
        assert rig.client._spend_seeded is True
        armed = rig.client._latch.arm("5" * 64, now_ns=rig.clock.timestamp_ns())
        instrument = rig.instrument
        now_ns = rig.clock.timestamp_ns()
        legacy_blob = json.dumps(
            {
                "intentId": armed.intent_id,
                "venueOrderId": order_id,
                "instrumentId": str(instrument.id),
                "clientOrderId": "O-legacy",
                "strategyId": str(STRATEGY_ID.value),
                "notionalUsd": "0.40",
                "bookingId": 1,
                "createdNs": now_ns,
                # No "orderSide" key at all -- a genuinely pre-INC-E2 blob.
            },
            sort_keys=True,
        ).encode("utf-8")
        context = AmbiguousResolverContext.from_bytes(legacy_blob)
        assert context.order_side == "BUY"
        rig.client._resolved_by_get_ts_ns[armed.intent_id] = now_ns
        assert rig.client._ambiguous_bookings.get(armed.intent_id) is None

        rig.client._resolve_accept_fill(
            context, _FakeResolverAcceptFillReport(), instrument, now_ns,
        )

        assert _RESOLVER_FILL_UNBUDGETED in rig.client.trading_refusals
        await rig.client._disconnect()


@pytest.mark.asyncio
async def test_cross_process_sell_exit_fill_does_not_refuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """RED against r2's rule: a cross-process exit fill spends no budget and
    must never latch, even though `booking is None` and `_spend_seeded` is
    `True` -- both hold here, and it must still not refuse."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    order_id = "ord-ac6b-sell-cross"
    with _accept_fill_caps():
        await rig.client._connect()
        assert rig.client._spend_seeded is True
        armed = rig.client._latch.arm("6" * 64, now_ns=rig.clock.timestamp_ns())
        instrument = rig.instrument
        now_ns = rig.clock.timestamp_ns()
        context = AmbiguousResolverContext(
            intent_id=armed.intent_id,
            venue_order_id=order_id,
            instrument_id=str(instrument.id),
            client_order_id="O-sell-cross",
            strategy_id=str(STRATEGY_ID.value),
            notional_usd=Decimal("0.40"),
            booking_id=-1,
            created_ns=now_ns,
            order_side="SELL",
        )
        rig.client._resolved_by_get_ts_ns[armed.intent_id] = now_ns
        assert rig.client._ambiguous_bookings.get(armed.intent_id) is None

        rig.client._resolve_accept_fill(
            context, _FakeResolverAcceptFillReport(), instrument, now_ns,
        )

        assert rig.client.trading_refusals == ()
        assert rig.client.is_degraded is False
        current = rig.client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        await rig.client._disconnect()


@pytest.mark.asyncio
async def test_same_process_sell_exit_fill_does_not_refuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """(D8 item 3) An exit's OWN in-process booking is ALSO always `None`
    (`_NO_BOOKING_ID`) -- a same-session exit fill is mechanically identical
    to the cross-process shape at this predicate, and must not refuse
    either: only `order_side` decides for an exit, never the booking."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    order_id = "ord-ac6b-sell-same"
    with _accept_fill_caps():
        await rig.client._connect()
        armed = rig.client._latch.arm("7" * 64, now_ns=rig.clock.timestamp_ns())
        instrument = rig.instrument
        now_ns = rig.clock.timestamp_ns()
        context = AmbiguousResolverContext(
            intent_id=armed.intent_id,
            venue_order_id=order_id,
            instrument_id=str(instrument.id),
            client_order_id="O-sell-same",
            strategy_id=str(STRATEGY_ID.value),
            notional_usd=Decimal("0.40"),
            booking_id=-1,
            created_ns=now_ns,
            order_side="SELL",
        )
        rig.client._resolved_by_get_ts_ns[armed.intent_id] = now_ns

        rig.client._resolve_accept_fill(
            context, _FakeResolverAcceptFillReport(), instrument, now_ns,
        )

        assert rig.client.trading_refusals == ()
        await rig.client._disconnect()


@pytest.mark.asyncio
async def test_same_process_accept_fill_does_not_refuse(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """`booking is not None` (this process's own `_submit_order` took it) --
    AC6b must never fire regardless of `_spend_seeded`."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    order_id = "ord-ac6b-same-process"
    sender.response = VenueResponse(status=200, headers={}, body=_ambiguous_with_id_body(order_id))
    with _accept_fill_caps():
        await rig.client._connect()
        command = rig.limit_buy()
        rig.client._cache.add_order(command.order, position_id=None)
        await rig.client._submit_order(command)

        current = rig.client._latch.current_open()
        assert current is not None
        instrument = rig.instrument
        now_ns = rig.clock.timestamp_ns()
        assert current.intent_id in rig.client._ambiguous_bookings, (
            "the with-id AMBIGUOUS submit path must have taken a real booking"
        )
        context = AmbiguousResolverContext(
            intent_id=current.intent_id,
            venue_order_id=order_id,
            instrument_id=str(instrument.id),
            client_order_id=command.order.client_order_id.value,
            strategy_id=str(STRATEGY_ID.value),
            notional_usd=Decimal("0.40"),
            booking_id=1,
            created_ns=now_ns,
        )
        rig.client._resolved_by_get_ts_ns[current.intent_id] = now_ns

        rig.client._resolve_accept_fill(
            context, _FakeResolverAcceptFillReport(), instrument, now_ns,
        )

        # The with-id AMBIGUOUS create-order outcome itself already latches
        # an unrelated refusal at submit time (`_submit_order#5`,
        # "create-order outcome is AMBIGUOUS after a response") -- AC6b's
        # OWN refusal is what must be absent here.
        assert _RESOLVER_FILL_UNBUDGETED not in rig.client.trading_refusals
        await rig.client._disconnect()


@pytest.mark.asyncio
async def test_periodic_pass_fill_before_seed_is_counted_not_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """D8: a fill resolved while `self._spend_seeded` is still `False` (the
    real shape of `_connect`'s own immediate pass, which always runs BEFORE
    its own seed line) must not refuse, and the seed run right after it
    must count the record it just wrote."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    order_id = "ord-ac6b-pre-seed"
    with _accept_fill_caps():
        await rig.client._connect()
        # Model a resolver pass that ran BEFORE the seed line in `_connect`
        # (D8): the flag is reset to what it provably is at that point.
        rig.client._spend_seeded = False
        armed = rig.client._latch.arm("8" * 64, now_ns=rig.clock.timestamp_ns())
        instrument = rig.instrument
        now_ns = rig.clock.timestamp_ns()
        context = AmbiguousResolverContext(
            intent_id=armed.intent_id,
            venue_order_id=order_id,
            instrument_id=str(instrument.id),
            client_order_id="O-pre-seed",
            strategy_id=str(STRATEGY_ID.value),
            notional_usd=Decimal("0.40"),
            booking_id=-1,
            created_ns=now_ns,
        )
        rig.client._resolved_by_get_ts_ns[armed.intent_id] = now_ns

        rig.client._resolve_accept_fill(
            context, _FakeResolverAcceptFillReport(), instrument, now_ns,
        )

        assert rig.client.trading_refusals == ()
        assert rig.client.is_degraded is False

        rig.client._seed_spend_from_durable_fills()
        assert rig.client._ledger.spent_today_usd(now_ns=now_ns) == Decimal("0.37")
        await rig.client._disconnect()


@pytest.mark.asyncio
async def test_spend_seeded_is_set_immediately_after_the_seed(tmp_path: Path) -> None:
    """The flag is `False` INSIDE the seed and `True` before
    `_reconcile_no_side_first_order_key`, the next statement after it in
    `_connect` -- the same trace-spy technique the existing seed-ordering
    test uses (`test_the_seed_runs_after_intent_reconciliation_and_before_
    position_evidence`)."""
    rig = _build_rig(tmp_path, spend_ledger=DailySpendLedger())
    trace: list[str] = []

    original_seed = rig.client._seed_spend_from_durable_fills
    original_no_side = rig.client._reconcile_no_side_first_order_key

    def _spy_seed() -> Any:
        trace.append(f"seed_start:flag={rig.client._spend_seeded}")
        result = original_seed()
        trace.append(f"seed_end:flag={rig.client._spend_seeded}")
        return result

    def _spy_no_side() -> Any:
        trace.append(f"no_side:flag={rig.client._spend_seeded}")
        return original_no_side()

    rig.client._seed_spend_from_durable_fills = _spy_seed  # type: ignore[method-assign]
    rig.client._reconcile_no_side_first_order_key = _spy_no_side  # type: ignore[method-assign]

    assert rig.client._spend_seeded is False
    await rig.client._connect()

    assert trace == [
        "seed_start:flag=False",
        "seed_end:flag=False",
        "no_side:flag=True",
    ], trace
    assert rig.client._spend_seeded is True
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_unbudgeted_refusal_precedes_the_order_unknown_early_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """`_resolver_fill_order_unknown` (FU-8) runs AFTER every durable write
    and returns early, skipping ONLY `generate_order_filled` -- never the
    refusal check above it. This order was never cached by THIS run (the
    FU-8 gate fires), and the refusal must still latch."""
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    order_id = "ord-ac6b-order-unknown"
    with _accept_fill_caps():
        await rig.client._connect()
        armed = rig.client._latch.arm("9" * 64, now_ns=rig.clock.timestamp_ns())
        instrument = rig.instrument
        now_ns = rig.clock.timestamp_ns()
        context = AmbiguousResolverContext(
            intent_id=armed.intent_id,
            venue_order_id=order_id,
            instrument_id=str(instrument.id),
            client_order_id="O-cross-session-unknown",
            strategy_id=str(STRATEGY_ID.value),
            notional_usd=Decimal("0.40"),
            booking_id=-1,
            created_ns=now_ns,
        )
        rig.client._resolved_by_get_ts_ns[armed.intent_id] = now_ns
        # No `rig.client._cache.add_order(...)`: this order is unknown to
        # THIS run's cache, so `_resolver_fill_order_unknown` returns True.

        rig.client._resolve_accept_fill(
            context, _FakeResolverAcceptFillReport(), instrument, now_ns,
        )

        assert _RESOLVER_FILL_UNBUDGETED in rig.client.trading_refusals
        fills = [e for e in rig.order_events if isinstance(e, OrderFilled)]
        assert fills == [], "the FU-8 gate must still skip generate_order_filled"
        await rig.client._disconnect()


# ---------------------------------------------------------------------------
# The boot-pass ordering tests (the r3 convergence record's binding RED test).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("same_day", [True, False], ids=["same_day", "past_day"])
async def test_boot_pass_resolution_of_prior_process_fill_does_not_refuse_and_is_seeded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
    same_day: bool,
) -> None:
    """BINDING (r3 convergence record): a fresh process's own IMMEDIATE
    resolver pass (`_connect`'s `first_pass_immediate=True`, which always
    runs BEFORE that same process's own boot seed) resolves a PRIOR
    process's fill. `booking is None` (this process never took it) but
    `self._spend_seeded` is still `False` at that point (D8) -- the fill
    must NOT refuse, and the seed that runs moments later in the SAME
    `_connect()` must count it exactly once, whether or not this fresh
    process's provider ever loaded the instrument (D9: same-day via the
    provider walk, past-day via `fill_by_day/<today>`)."""
    enable_operator_gate(monkeypatch, order_count="2")
    store_path = tmp_path / "exec_state.db"
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        # "process 1": arms one with-id AMBIGUOUS intent, then "restarts" --
        # releasing the exclusive flock -- leaving the OPEN intent and its
        # durable resolver context on disk for the fresh process to inherit.
        first_client, order_id, slug, first_latch_cm, _order_events = (
            await _arm_one_ambiguous_intent(tmp_path)
        )
        await first_client._disconnect()
        first_latch_cm.__exit__(None, None, None)

        target_instrument = build_instrument()

        def _loader(instrument_id: str) -> Any:
            return target_instrument if instrument_id == str(target_instrument.id) else None

        client, latch_cm = await _build_client_with_custom_loader(
            tmp_path,
            store_path=store_path,
            resolver_instrument_loader=None if same_day else _loader,
        )
        if same_day:
            client._cache.add_instrument(target_instrument)
            client._instrument_provider.add(target_instrument)
        else:
            # A real boot's provider is never EMPTY -- it always has
            # TODAY's OTHER instruments loaded; only the fill's OWN
            # (past-day) instrument is absent. This isolates the
            # `fill_by_day` mechanism from the unrelated "provider loaded
            # zero instruments" guard.
            other_instrument = build_second_instrument()
            client._cache.add_instrument(other_instrument)
            client._instrument_provider.add(other_instrument)
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.40",
        )
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {slug: {"netPosition": "1"}},
            "eof": True,
        }
        try:
            await client._connect()

            assert client.trading_refusals == (), client.trading_refusals
            current = client._latch.current()
            assert current is not None
            assert current.state is SubmitIntentState.RETIRED

            now_ns = client._clock.timestamp_ns()
            assert client._ledger.spent_today_usd(now_ns=now_ns) == Decimal("0.40")
            remaining_notional, remaining_count = live_trading_budget_remaining(client._permit)
            assert remaining_notional == Decimal("1000.00") - Decimal("0.40")
            assert remaining_count == 2, "the seed never touches the order-count budget"

            # Not double-booked: a second seed run in the same process is a
            # no-op (idempotent), never re-subtracting the notional again.
            client._seed_spend_from_durable_fills()
            remaining_notional_again, _ = live_trading_budget_remaining(client._permit)
            assert remaining_notional_again == remaining_notional
        finally:
            await client._disconnect()
            latch_cm.__exit__(None, None, None)


@pytest.mark.asyncio
async def test_respawn_seed_books_the_cross_process_fill_into_ledger_and_permit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A respawn (a THIRD process, in the terminology of the plan's clearing
    path) whose own provider ALSO never loads the record's instrument (the
    past-day shape) can reach it through no path but `fill_by_day/<today>` --
    proving G4 independent of any live resolver pass."""
    enable_operator_gate(monkeypatch, session_notional="12.00", order_count="10")
    store_path = tmp_path / "exec_state.db"
    # A real boot's provider is never EMPTY -- it always has TODAY's OTHER
    # instruments loaded; only the fill's OWN (past-day) instrument is
    # absent. `build_second_instrument()` stands in for that unrelated
    # instrument so this test isolates the `fill_by_day` mechanism, not the
    # unrelated "provider loaded zero instruments" guard.
    other_instrument = build_second_instrument()

    boot1 = _build_rig(
        tmp_path, store_path=store_path, spend_ledger=DailySpendLedger(), instrument_loaded=False,
    )
    boot1.cache.add_instrument(other_instrument)
    boot1.client._instrument_provider.add(other_instrument)
    await boot1.client._connect()
    now_ns = boot1.clock.timestamp_ns()
    boot1.client.record_fill(
        _record_at(
            boot1,
            ts_event=now_ns,
            order="V-RESPAWN-PAST-DAY",
            qty=Decimal(1),
            cost=Decimal("4.00"),
        ),
    )
    await boot1.client._disconnect()

    permit = _issued_permit(LiveClock())
    boot2 = _build_rig(
        tmp_path,
        store_path=store_path,
        spend_ledger=DailySpendLedger(),
        live_trading_permit=permit,
        instrument_loaded=False,
    )
    boot2.cache.add_instrument(other_instrument)
    boot2.client._instrument_provider.add(other_instrument)
    await boot2.client._connect()

    assert boot2.client.trading_refusals == ()
    assert boot2.client._ledger.spent_today_usd(now_ns=now_ns) == Decimal("4.00")
    assert live_trading_budget_remaining(permit) == (Decimal("8.00"), 10)
    await boot2.client._disconnect()


# ---------------------------------------------------------------------------
# `record_fill` / the seed's `fill_by_day` mechanics.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_fill_writes_the_day_index_before_the_fingerprint_key(
    tmp_path: Path,
) -> None:
    rig = _build_rig(tmp_path, spend_ledger=DailySpendLedger())
    await rig.client._connect()
    now_ns = rig.clock.timestamp_ns()
    written_keys: list[str] = []
    original_store_set = rig.client._store_set

    def _spy_store_set(key: str, value: bytes) -> None:
        written_keys.append(key)
        original_store_set(key, value)

    rig.client._store_set = _spy_store_set  # type: ignore[method-assign]

    rig.client.record_fill(
        _record_at(rig, ts_event=now_ns, order="V-DAY-ORDER", qty=Decimal(1), cost=Decimal("1.00")),
        intent_fingerprint="fp-day-order",
        intent_created_ns=now_ns,
    )

    day = utc_day_for_ns(now_ns).isoformat()
    day_index_pos = written_keys.index(f"{FILL_BY_DAY_KEY_PREFIX}{day}")
    fingerprint_pos = next(
        i for i, key in enumerate(written_keys) if key.startswith(FILL_BY_FINGERPRINT_KEY_PREFIX)
    )
    assert day_index_pos < fingerprint_pos, written_keys
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_day_index_write_failure_takes_the_fill_write_failed_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    sender = _FakeOrderSender()
    rig = _build_accept_fill_rig(tmp_path, monkeypatch=monkeypatch, sender=sender)
    order_id = "ord-ac6b-day-index-boom"
    with _accept_fill_caps():
        await rig.client._connect()
        armed = rig.client._latch.arm("a" * 64, now_ns=rig.clock.timestamp_ns())
        now_ns = rig.clock.timestamp_ns()
        day = utc_day_for_ns(now_ns).isoformat()
        # Corrupt TODAY's day index directly -- the per-instrument index is
        # untouched, so only the NEW day-index read can be the failure.
        rig.client._store_set(f"{FILL_BY_DAY_KEY_PREFIX}{day}", b"{not json at all")
        instrument = rig.instrument
        context = AmbiguousResolverContext(
            intent_id=armed.intent_id,
            venue_order_id=order_id,
            instrument_id=str(instrument.id),
            client_order_id="O-day-index-boom",
            strategy_id=str(STRATEGY_ID.value),
            notional_usd=Decimal("0.40"),
            booking_id=-1,
            created_ns=now_ns,
        )
        rig.client._resolved_by_get_ts_ns[armed.intent_id] = now_ns

        rig.client._resolve_accept_fill(
            context, _FakeResolverAcceptFillReport(), instrument, now_ns,
        )

        assert rig.client.trading_refusals[-1] == _FILL_WRITE_FAILED
        current = rig.client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN, (
            "a failed day-index write must not retire the intent"
        )
        await rig.client._disconnect()
    # `record_fill` writes `fill/<id>` and the per-instrument index BEFORE
    # the (corrupted) day index -- durability of what it already wrote is
    # unaffected by a later step's fail-closed raise.
    assert _reopened_fill_record(rig.store_path, order_id) is not None


@pytest.mark.asyncio
async def test_record_fill_day_index_is_idempotent_on_rewrite(tmp_path: Path) -> None:
    rig = _build_rig(tmp_path, spend_ledger=DailySpendLedger())
    await rig.client._connect()
    now_ns = rig.clock.timestamp_ns()
    record = _record_at(
        rig, ts_event=now_ns, order="V-REWRITE", qty=Decimal(1), cost=Decimal("1.00"),
    )
    rig.client.record_fill(record)
    rig.client.record_fill(
        dataclasses.replace(record, cumulative_qty=Decimal(2), cumulative_cost=Decimal("2.00")),
    )

    day = utc_day_for_ns(now_ns).isoformat()
    indexed = rig.client._read_fill_index(f"{FILL_BY_DAY_KEY_PREFIX}{day}")
    assert indexed == ["V-REWRITE"]
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_seed_counts_an_id_reachable_by_both_walks_once(tmp_path: Path) -> None:
    """A today-instrument fill is written into BOTH the per-instrument index
    AND the day index (unconditionally, by `record_fill`) -- the seed's
    total must equal its cost exactly once, never twice."""
    rig = _build_rig(tmp_path, spend_ledger=DailySpendLedger())
    await rig.client._connect()
    now_ns = rig.clock.timestamp_ns()
    rig.client.record_fill(
        _record_at(
            rig, ts_event=now_ns, order="V-BOTH-WALKS", qty=Decimal(1), cost=Decimal("5.00"),
        ),
    )

    rig.client._seed_spend_from_durable_fills()

    assert rig.client._ledger.spent_today_usd(now_ns=now_ns) == Decimal("5.00")
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_seed_twice_in_one_process_does_not_double_book(tmp_path: Path) -> None:
    rig = _build_rig(tmp_path, spend_ledger=DailySpendLedger())
    await rig.client._connect()
    now_ns = rig.clock.timestamp_ns()
    rig.client.record_fill(
        _record_at(rig, ts_event=now_ns, order="V-TWICE", qty=Decimal(1), cost=Decimal("3.00")),
    )
    rig.client._seed_spend_from_durable_fills()
    rig.client._seed_spend_from_durable_fills()

    assert rig.client._ledger.spent_today_usd(now_ns=now_ns) == Decimal("3.00")
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_seed_skips_a_day_index_entry_whose_record_ts_event_is_another_day(
    tmp_path: Path,
) -> None:
    rig = _build_rig(tmp_path, spend_ledger=DailySpendLedger(), instrument_loaded=False)
    await rig.client._connect()
    now_ns = rig.clock.timestamp_ns()
    yesterday_ns = now_ns - 2 * 24 * 60 * 60 * 1_000_000_000
    today = utc_day_for_ns(now_ns).isoformat()
    # `record_fill` itself would key this under YESTERDAY's own day index --
    # a stale TODAY entry is planted by hand to prove the seed's per-record
    # `ts_event` day filter, not `record_fill`'s own keying.
    rig.client.record_fill(
        _record_at(
            rig, ts_event=yesterday_ns, order="V-STALE-DAY", qty=Decimal(1), cost=Decimal("6.00"),
        ),
    )
    rig.client._store_set(
        f"{FILL_BY_DAY_KEY_PREFIX}{today}", json.dumps(["V-STALE-DAY"]).encode("utf-8"),
    )

    rig.client._seed_spend_from_durable_fills()

    assert rig.client._ledger.spent_today_usd(now_ns=now_ns) == Decimal(0)
    await rig.client._disconnect()


@pytest.mark.asyncio
async def test_unreadable_day_index_fails_the_seed_closed(tmp_path: Path) -> None:
    """BINDING (r3 convergence record): a corrupt TODAY day index -- not a
    per-instrument corruption -- must still refuse to seed, and `_connect`
    must propagate the fault rather than silently arm on an incomplete
    walk (mirrors ``test_a_corrupt_fill_index_for_one_instrument_fails_the_
    seed_closed_and_never_arms``'s per-instrument sibling)."""
    rig = _build_rig(tmp_path, spend_ledger=DailySpendLedger())
    today = utc_day_for_ns(rig.clock.timestamp_ns()).isoformat()
    with SqliteStateStore(rig.store_path) as store:
        store.set(f"{FILL_BY_DAY_KEY_PREFIX}{today}", b"{not json at all")

    with pytest.raises(PolymarketUSError):
        await rig.client._connect()


@pytest.mark.asyncio
async def test_day_index_naming_a_missing_record_fails_the_seed_closed(tmp_path: Path) -> None:
    rig = _build_rig(tmp_path, spend_ledger=DailySpendLedger())
    today = utc_day_for_ns(rig.clock.timestamp_ns()).isoformat()
    with SqliteStateStore(rig.store_path) as store:
        store.set(
            f"{FILL_BY_DAY_KEY_PREFIX}{today}",
            json.dumps(["V-GHOST-DAY-ENTRY"]).encode("utf-8"),
        )

    with pytest.raises(PolymarketUSError):
        await rig.client._connect()
