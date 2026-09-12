"""Resolution A/C/D (plan rev 6.1): ``_resolve_ambiguous_intents`` end to end.

A with-id AMBIGUOUS create-order outcome (L-36: the strict ZERO_FILL shape is
unreachable; a no-fill IOC comes back AMBIGUOUS with a venue id) leaves the
account-wide submit intent OPEN with a durable resolver context. This module
drives the REAL resolver coroutine -- one bounded pass at a time, via the
overridable ``_resolver_poll_interval_secs`` seam -- through:

* a GET that never returns terminal evidence (stays OPEN, no action);
* a GET-confirmed terminal-zero + an eof-complete positions read showing no
  LONG (retires, trues the booking up to ZERO, cancels natively, IN_FLIGHT-
  clearing via the strategy's own ``on_order_denied``-sibling handler is out
  of THIS module's scope -- see the build report);
* the SAFETY H2 mutation shape: a resolver that never calls the GET must
  never retire (proven by never wiring a terminal response into the stub).

Fixtures reused, never redefined: ``_build_race_client`` / ``_SlowSender`` /
``_submit_command`` (``test_current_rung_hold_pre_arm_race.py``);
``credentials`` / ``enable_operator_gate``
(``test_polymarket_us_permit_issuance.py``); ``build_instrument``
(``polymarket_us_exec_shapes.py``).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.component import LiveClock
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.model.events import OrderDenied

from breezy.adapters.polymarket_us.exec.client import (
    RESOLVER_CONTEXT_KEY_PREFIX,
    AmbiguousResolverContext,
    PolymarketUSExecutionClient,
    StartupPositionSnapshot,
    _synthetic_get_fill_trade_id,
)
from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
)
from breezy.adapters.polymarket_us.safety import live_trading_budget_remaining
from breezy.adapters.polymarket_us.symbology import instrument_id_to_slug
from breezy.adapters.polymarket_us.transport import VenueResponse
from breezy.runtime.submit_intent import (
    CURRENT_INTENT_KEY,
    SubmitIntentCorrupt,
    SubmitIntentMismatch,
    SubmitIntentState,
)
from breezy.strategy.current_rung_hold.composition import family_halt_submit_veto
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    open_trial_day_latch,
)
from tests.unit.operator_control_env import operator_control_env
from tests.unit.polymarket_us_exec_shapes import TS_EVENT_TEXT, build_instrument
from tests.unit.test_current_rung_hold_pre_arm_race import (
    STRATEGY_ID,
    TRADER_ID,
    _build_race_client,
    _SlowSender,
    _submit_command,
)
from tests.unit.test_polymarket_us_permit_issuance import enable_operator_gate
from tests.unit.test_polymarket_us_submit_order_chain import (
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
)

#: Captured at IMPORT time, before any test's `monkeypatch.setattr(asyncio,
#: "sleep", ...)` can run. `_run_n_passes_recording_sleeps` is called TWICE
#: in one test (item 2, 2026-09-11 addendum): a helper that instead did
#: `real_sleep = asyncio.sleep` on its second call would capture the FIRST
#: call's still-installed fake, whose own closed-over pass budget is
#: already exhausted -- parking forever on an `Event` nothing ever sets.
_REAL_ASYNCIO_SLEEP = asyncio.sleep


def _ambiguous_create_body(order_id: str) -> bytes:
    """L-36: 200 + id + executions == [] with no terminal state/cumQuantity."""
    return json.dumps({"id": order_id, "executions": []}).encode("utf-8")


def _order_get_body(
    order_id: str,
    *,
    slug: str,
    state: str,
    cum_quantity: float,
    avg_px: str | None = None,
) -> dict[str, Any]:
    order: dict[str, Any] = {
        "id": order_id,
        "marketSlug": slug,
        "side": "ORDER_SIDE_BUY",
        "type": "ORDER_TYPE_LIMIT",
        "price": {"value": "0.40", "currency": "USD"},
        "quantity": 1,
        "cumQuantity": cum_quantity,
        "leavesQuantity": 1 - cum_quantity,
        "tif": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
        "state": state,
        "createTime": TS_EVENT_TEXT,
    }
    if avg_px is not None:
        order["avgPx"] = {"value": avg_px, "currency": "USD"}
    return {
        "order": order
    }


async def _arm_one_ambiguous_intent(
    tmp_path: Path,
) -> tuple[PolymarketUSExecutionClient, str, str, Any, list[Any]]:
    """Drive ``_submit_order`` to the with-id AMBIGUOUS branch once.

    Returns the client, the venue_order_id, the market slug the resolver
    will need to query positions under, the latch context manager the
    caller MUST keep referenced (dropping it GCs the generator, which
    releases the flock immediately -- ``SubmitIntentLockNotHeld`` on the
    very next latch call), and the ``ExecEngine.process`` event sink every
    native event (``OrderSubmitted``, ``OrderFilled``, ``OrderCanceled``, ...)
    this client publishes lands in.
    """
    sender = _SlowSender()
    order_id = "ord-amb-1"
    sender.response = VenueResponse(status=200, headers={}, body=_ambiguous_create_body(order_id))
    client, order_events, _permit, latch_cm = await _build_race_client(tmp_path, sender=sender)
    factory = OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=LiveClock())
    command = _submit_command(client, factory, "a")
    await client._submit_order(command)

    assert client._latch is not None
    assert client._latch.is_latched() is True, "the with-id AMBIGUOUS outcome must leave OPEN"
    instrument = build_instrument()
    slug = instrument_id_to_slug(instrument.id)
    return client, order_id, slug, latch_cm, order_events


async def _run_resolver_passes(client: PolymarketUSExecutionClient, count: int) -> None:
    """Drive ``count`` bounded passes of the real resolver coroutine.

    ``_resolver_poll_interval_secs`` is monkeypatched to ``0.0`` so each
    pass's ``asyncio.sleep`` yields to the loop without a real delay; the
    task is cancelled (never left pending) once enough passes have run.
    """
    client._resolver_poll_interval_secs = lambda: 0.0  # type: ignore[method-assign]
    task = asyncio.get_event_loop().create_task(client._resolve_ambiguous_intents())
    try:
        for _ in range(count * 50 + 5):
            await asyncio.sleep(0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _run_exactly_one_pass(client: PolymarketUSExecutionClient) -> None:
    """Like :func:`_run_resolver_passes`, but for a test that needs the
    pass COUNT itself to be exact (item 1, slice 4 review) rather than "at
    least one and it settled": a zero poll interval on every iteration lets
    an intent that never resolves run an UNBOUNDED number of passes inside
    any finite yield budget, since each one completes with no real await.
    The first ``_resolver_poll_interval_secs`` call (before pass 1) returns
    ``0.0``; every call after that returns an hour, parking the loop inside
    an ``asyncio.sleep`` that never completes in this test -- so exactly
    ONE pass has run by the time the yield budget below is spent.
    """
    calls = {"count": 0}

    def _poll_interval() -> float:
        calls["count"] += 1
        return 0.0 if calls["count"] == 1 else 3600.0

    client._resolver_poll_interval_secs = _poll_interval  # type: ignore[method-assign]
    task = asyncio.get_event_loop().create_task(client._resolve_ambiguous_intents())
    try:
        for _ in range(200):
            await asyncio.sleep(0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def _run_n_passes_recording_sleeps(
    client: PolymarketUSExecutionClient,
    *,
    passes: int,
    monkeypatch: pytest.MonkeyPatch,
) -> list[float]:
    """Drive exactly ``passes`` passes of the real resolver coroutine,
    recording the ``asyncio.sleep`` DURATION requested before each one --
    an injected clock/sleep, never wall time (item 2, 2026-09-11 incident
    addendum).

    ``_resolver_poll_interval_secs`` is left at its real default (5.0s) so
    the backoff math under test is exercised at production values;
    ``asyncio.sleep`` itself is monkeypatched so none of it is actually
    waited. The (``passes`` + 1)-th sleep call parks on an ``Event`` that
    never fires, which bounds the run to EXACTLY ``passes`` passes -- the
    same problem, and the same fix, ``_run_exactly_one_pass`` documents: a
    faked sleep never really suspends, so an unbounded resolver loop would
    otherwise run far more passes than intended inside any finite yield
    budget.
    """
    sleeps: list[float] = []
    calls = {"count": 0}
    never = asyncio.Event()

    async def fake_sleep(seconds: float) -> None:
        calls["count"] += 1
        if calls["count"] > passes:
            await never.wait()
        sleeps.append(seconds)
        await _REAL_ASYNCIO_SLEEP(0)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    task = asyncio.get_event_loop().create_task(client._resolve_ambiguous_intents())
    try:
        for _ in range(passes * 20 + 20):
            await _REAL_ASYNCIO_SLEEP(0)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    return sleeps


@pytest.mark.asyncio
async def test_resolver_backoff_doubles_on_consecutive_get_failures_and_resets_on_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Item 2 (2026-09-11 incident addendum): 5s, 5s, 10s, 20s, 40s on four
    consecutive GET failures, then a mapped (even non-terminal) GET resets
    the counter and the very next sleep is back at the plain 5s base."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(tmp_path)
        path = f"/v1/order/{order_id}"
        # No payload wired for this path: the stub's `self._payloads[path]`
        # raises `KeyError`, exactly the "GET failure" shape the backoff
        # counts (`except Exception` in `_resolve_ambiguous_intents`).

        sleeps = await _run_n_passes_recording_sleeps(client, passes=5, monkeypatch=monkeypatch)

        assert sleeps == [5.0, 5.0, 10.0, 20.0, 40.0]
        assert client._resolver_consecutive_failures == 5

        client._private_read._payloads[path] = _order_get_body(  # type: ignore[attr-defined]
            order_id, slug=slug, state="ORDER_STATE_NEW", cum_quantity=0,
        )
        sleeps_after_success = await _run_n_passes_recording_sleeps(
            client, passes=2, monkeypatch=monkeypatch,
        )

        assert sleeps_after_success[0] == 80.0, (
            "the sleep BEFORE the recovering pass still backs off"
        )
        assert client._resolver_consecutive_failures == 0
        assert sleeps_after_success[1] == 5.0, "reset: the pass AFTER success is back at the base"
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_stale_open_intent_alerts_once_and_resets_on_retirement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Item 3 (2026-09-11 incident addendum): a still-AMBIGUOUS intent
    whose durable ``created_ns`` is already >15 minutes old surfaces exactly
    ONE entry on the ``stale_ambiguous_intent_alerts`` health property,
    never a second time for the same intent, and the entry clears on
    retirement so a later intent can surface again."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(tmp_path)

        current = client._latch.current_open()
        assert current is not None
        raw_context = client._store_get(f"{RESOLVER_CONTEXT_KEY_PREFIX}{current.intent_id}")
        assert raw_context is not None
        context = AmbiguousResolverContext.from_bytes(raw_context)
        backdated = replace(
            context, created_ns=client._clock.timestamp_ns() - (16 * 60 * 1_000_000_000),
        )
        client._store_set(
            f"{RESOLVER_CONTEXT_KEY_PREFIX}{current.intent_id}", backdated.to_bytes(),
        )
        # Non-terminal GET: the intent stays OPEN across every pass below.
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(order_id, slug=slug, state="ORDER_STATE_NEW", cum_quantity=0)

        await _run_resolver_passes(client, count=3)

        alerts = client.stale_ambiguous_intent_alerts
        assert len(alerts) == 1, "never re-surfaced twice while the same intent stays OPEN"
        assert alerts[0]["severity"] == "CRITICAL"
        assert alerts[0]["event"] == "open_intent_stale"
        assert alerts[0]["intent_id"] == current.intent_id
        assert alerts[0]["venue_order_id"] == order_id
        assert int(alerts[0]["age_minutes"]) >= 16

        # Retire it (terminal-zero, no LONG), then arm a SECOND ambiguous
        # intent equally stale -- the dedup must not still be latched.
        client._private_read._payloads[f"/v1/order/{order_id}"] = _order_get_body(  # type: ignore[attr-defined]
            order_id, slug=slug, state="ORDER_STATE_CANCELED", cum_quantity=0,
        )
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {}, "eof": True,
        }
        await _run_resolver_passes(client, count=1)
        assert client._latch.current() is not None
        assert client._latch.current().state is SubmitIntentState.RETIRED
        assert current.intent_id not in client._resolver_stale_alerted_intent_ids
        assert client.stale_ambiguous_intent_alerts == ()

        await client._disconnect()


@pytest.mark.asyncio
async def test_a_get_that_never_returns_terminal_evidence_leaves_the_intent_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """SAFETY H2's own AC: restart with OPEN + a durable resolver context and
    a ``_private_read`` that never returns terminal -> stays OPEN, no
    restore, no ``OrderCanceled``, IN_FLIGHT untouched (IN_FLIGHT is a
    strategy-side concern outside this module's scope; the client-visible
    half is asserted here: the singleton, the events, the booking)."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(tmp_path)
        # PENDING, not terminal: never wires a terminal response in.
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(order_id, slug=slug, state="ORDER_STATE_NEW", cum_quantity=0)

        await _run_resolver_passes(client, count=3)

        assert client._latch is not None
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN
        _, remaining = live_trading_budget_remaining(client._permit)
        assert remaining == 1, "no restore on a non-terminal GET"
        assert current.intent_id in client._ambiguous_bookings
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_get_confirmed_terminal_zero_with_no_long_retires_and_trues_up_to_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Resolution D: terminal + filled_qty==0 + eof-complete positions with
    no LONG -> retires (STATUS_REPORT_ZERO_FILL_TERMINAL), trues the booking
    up to ZERO, and cancels natively."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(tmp_path)
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(order_id, slug=slug, state="ORDER_STATE_CANCELED", cum_quantity=0)
        # eof-complete, no LONG anywhere.
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {},
            "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        assert client._latch is not None
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        assert current.retirement_reason is not None
        assert current.retirement_reason.value == "STATUS_REPORT_ZERO_FILL_TERMINAL"
        # D1/D2 (plan rev 6.1): true_up_booking(ZERO) frees the LEDGER's
        # notional reservation; restore_live_trading_budget (called right
        # after retire, in _resolve_terminal_zero) is the SEPARATE mechanism
        # that gives back the PERMIT's own order-count slot and notional --
        # this no-fill IOC never actually spent either, so both return to
        # their full issued budget.
        remaining_notional, remaining_count = live_trading_budget_remaining(client._permit)
        assert remaining_count == 2
        assert remaining_notional == Decimal("1000.00")
        assert current.intent_id not in client._ambiguous_bookings
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_terminal_zero_resolution_rewrites_the_startup_position_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """C1 (plan rev 6.1): the strategy's re-arm gate must read FRESH
    evidence, never a boot-time snapshot -- a terminal-zero resolution
    rewrites the SAME durable key from the SAME eof-complete page it just
    used to confirm there is no LONG, distinct from whatever `_connect`
    wrote at startup."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(tmp_path)
        at_connect = client.read_startup_position_evidence()
        assert at_connect is not None
        assert at_connect.positions == (), "the fixture connects against an empty book"

        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(order_id, slug=slug, state="ORDER_STATE_CANCELED", cum_quantity=0)
        # A DIFFERENT slug carries a position -- proves the rewrite reflects
        # THIS pass's fresh read, not a stale copy of what `_connect` wrote.
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {"a-different-market": {"netPosition": "5"}},
            "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        evidence = client.read_startup_position_evidence()
        assert evidence is not None
        assert evidence.eof_complete is True
        assert evidence.position_read_refused is False
        assert evidence.positions == (
            StartupPositionSnapshot(slug="a-different-market", net_position="5"),
        )
        assert evidence.ts_ns >= at_connect.ts_ns
        await client._disconnect()


def _order_filled_events(order_events: list[Any]) -> list[Any]:
    return [event for event in order_events if type(event).__name__ == "OrderFilled"]


@pytest.mark.asyncio
async def test_a_get_confirmed_fill_with_a_long_present_records_a_synthesized_fill_and_retires(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Slice 3, RED test 1 (plan rev 6.1): FILLED + a LONG present on an
    eof-complete positions read -> exactly one durable fill record, exactly
    one native ``OrderFilled`` carrying the synthetic ``GET-`` trade id,
    retires ``STATUS_REPORT_ACCEPT_FILL_TERMINAL``, and the booking is trued
    up to the synthesized cumulative cost.

    Superseded review fix 4 (was: ``..._is_inert_pending_slice_3``, pinning
    the deliberately inert placeholder) -- UPDATED, not deleted, now that
    slice 3 ships the real resolution."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.40",
        )
        # eof-complete, a LONG present at this instrument's slug.
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {slug: {"netPosition": "1"}},
            "eof": True,
        }
        instrument = build_instrument()
        refusals_before = client.trading_refusals

        await _run_resolver_passes(client, count=1)

        assert client._latch is not None
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        assert current.retirement_reason is not None
        assert current.retirement_reason.value == "STATUS_REPORT_ACCEPT_FILL_TERMINAL"
        assert current.intent_id not in client._ambiguous_bookings, "booking must be popped"

        records = client.fill_records_for(instrument.id)
        assert len(records) == 1, "exactly one durable fill record"
        record = records[0]
        assert record.venue_order_id == order_id
        assert record.cumulative_qty == Decimal(1)
        assert record.cumulative_cost == Decimal("0.40")
        assert record.fee_reconciled is False

        filled = _order_filled_events(order_events)
        assert len(filled) == 1, "exactly one native OrderFilled"
        assert filled[0].trade_id.value == f"GET-{order_id}"
        assert filled[0].last_qty.as_decimal() == Decimal(1)
        assert filled[0].last_px.as_decimal() == Decimal("0.40")

        _, remaining = live_trading_budget_remaining(client._permit)
        assert remaining == 1  # true-up to the SAME cost as booked -- no change
        assert client.trading_refusals == refusals_before, (
            "fee_reconciled=False must be a durable flag on the record, "
            "never a NEW latched trading refusal (the initial AMBIGUOUS "
            "submit's own refusal, captured before the resolver ran, is "
            "unrelated and expected to still be present)"
        )
        await client._disconnect()


class _FakeFilledQty:
    def as_decimal(self) -> Decimal:
        return Decimal(1)


class _FakeAcceptFillReport:
    """Duck-typed stand-in: ``_resolve_accept_fill`` only reads ``avg_px``
    and ``filled_qty.as_decimal()`` off its ``report`` argument."""

    avg_px = Decimal("0.40")
    filled_qty = _FakeFilledQty()


@pytest.mark.asyncio
async def test_resolve_accept_fill_restart_reentry_against_an_already_retired_singleton_is_a_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Slice 3, RED test 2: a restart re-entry that finds the singleton
    ALREADY RETIRED must call ``_retire`` ZERO times (``retire`` is NOT
    idempotent -- ``SubmitIntentMismatch`` on a non-OPEN singleton) and must
    still complete its cleanup without raising."""
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
        instrument = build_instrument()

        # Retire the intent for real, through the normal first-run path.
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.40",
        )
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {slug: {"netPosition": "1"}},
            "eof": True,
        }
        await _run_resolver_passes(client, count=1)
        retired = client._latch.current()
        assert retired is not None
        assert retired.state is SubmitIntentState.RETIRED

        # Simulate a FRESH resolver run's re-entry: a durable context for the
        # SAME (now-retired) intent, resolved by a fresh GET in THIS run.
        context = AmbiguousResolverContext(
            intent_id=armed.intent_id,
            venue_order_id=order_id,
            instrument_id=instrument.id.value,
            client_order_id="O-does-not-matter",
            strategy_id=STRATEGY_ID.value,
            notional_usd=Decimal("0.40"),
            booking_id=1,
            created_ns=client._clock.timestamp_ns(),
        )
        client._resolved_by_get_ts_ns[armed.intent_id] = client._clock.timestamp_ns()

        retire_calls: list[Any] = []
        original_retire = client._retire

        def _spy_retire(*args: Any, **kwargs: Any) -> None:
            retire_calls.append((args, kwargs))
            original_retire(*args, **kwargs)

        client._retire = _spy_retire  # type: ignore[method-assign]

        client._resolve_accept_fill(
            context, _FakeAcceptFillReport(), instrument, client._clock.timestamp_ns(),
        )

        assert retire_calls == [], (
            "retire must never be called against an already-retired singleton"
        )
        # Cleanup completed without raising: the singleton is untouched.
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        assert current.intent_id == armed.intent_id
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_get_confirmed_fill_with_no_long_present_never_authorizes_a_fill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Slice 3, RED test 3: ``status==FILLED`` ALONE must never authorize a
    fill -- the LONG cross-check is load-bearing. Pins the positive case
    (FILLED but NO LONG present -> the disagreement branch, stays AMBIGUOUS,
    nothing recorded); this test is also the mutation shape the coordinator
    asked for -- deleting ``and long_state is True`` from the dispatch would
    flip this from AMBIGUOUS-no-op to a wrongly-authorized fill, and this
    test would go RED."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.40",
        )
        # eof-complete, but NO LONG anywhere -- disagrees with the FILLED
        # status.
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {},
            "eof": True,
        }
        instrument = build_instrument()

        await _run_resolver_passes(client, count=1)

        assert client._latch is not None
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN, (
            "FILLED alone, without a confirmed LONG, must never authorize a fill"
        )
        assert current.intent_id in client._ambiguous_bookings
        assert client.fill_records_for(instrument.id) == ()
        assert _order_filled_events(order_events) == []
        await client._disconnect()


@pytest.mark.asyncio
async def test_resolve_terminal_zero_itself_refuses_to_retire_without_a_this_run_get(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Review fix 2: SAFETY H2 must be load-bearing INSIDE
    ``_resolve_terminal_zero`` itself, not only structural via the caller's
    branch shape. Calls it directly with a context whose ``intent_id`` was
    NEVER stamped into ``_resolved_by_get_ts_ns`` -- if the guard were
    missing, this would retire on the durable context alone."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        assert client._latch is not None
        armed = client._latch.current()
        assert armed is not None
        instrument = build_instrument()

        context = AmbiguousResolverContext(
            intent_id=armed.intent_id,
            venue_order_id=order_id,
            instrument_id=instrument.id.value,
            client_order_id="O-does-not-matter",
            strategy_id=STRATEGY_ID.value,
            notional_usd=client._ambiguous_bookings[armed.intent_id].cost,
            booking_id=client._ambiguous_bookings[armed.intent_id].booking_id,
            created_ns=client._clock.timestamp_ns(),
        )
        assert armed.intent_id not in client._resolved_by_get_ts_ns

        client._resolve_terminal_zero(context, client._clock.timestamp_ns())

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN, (
            "the guard inside _resolve_terminal_zero itself must refuse to "
            "retire absent a this-run GET timestamp"
        )
        assert armed.intent_id in client._ambiguous_bookings, "booking must not be popped either"
        await client._disconnect()


@pytest.mark.asyncio
async def test_the_get_call_is_load_bearing_deleting_it_would_go_red(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """SAFETY H2 mutation shape: the ONLY evidence that can ever retire this
    intent is a terminal GET made by THIS resolver in THIS run. Proven here
    by making the injected read raise for the order-by-id path specifically
    -- if the retire logic did not genuinely depend on that call's outcome
    (e.g. a hypothetical shortcut that retires on durable-context presence
    alone), this test would go GREEN despite the GET always failing; instead
    it stays OPEN, which is the behaviour this test pins."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        # No payload is ever registered for this path: `_PrivateReadStub.
        # __call__` does `self._payloads[path]`, so every attempt raises a
        # plain `KeyError` -- the GET "always fails" shape.
        assert f"/v1/order/{order_id}" not in client._private_read._payloads  # type: ignore[attr-defined]

        await _run_resolver_passes(client, count=5)

        assert client._latch is not None
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN
        # The load-bearing assertion: NO terminal GET was ever recorded for
        # this intent, because every attempt raised.
        assert client._resolved_by_get_ts_ns.get(current.intent_id) is None
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_corrupt_singleton_never_kills_the_resolver_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Review fix 3: a ``SubmitIntentCorrupt`` from the bare
    ``self._latch.current()`` call must not propagate out of the coroutine
    and silently kill the resolver task for the process lifetime. Caught the
    way ``is_latched()`` does: fail closed (OPEN-unknown, never retire,
    never act), logged at ERROR ONCE, and polling continues."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, _order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        assert client._latch is not None
        client._store_set(CURRENT_INTENT_KEY, b"not valid json")
        with pytest.raises(SubmitIntentCorrupt):
            client._latch.current()  # sanity: this really is the corrupt shape

        client._resolver_poll_interval_secs = lambda: 0.0  # type: ignore[method-assign]
        task = asyncio.get_event_loop().create_task(client._resolve_ambiguous_intents())
        try:
            for _ in range(3 * 50 + 5):
                await asyncio.sleep(0)
            assert not task.done(), "a corrupt singleton must never kill the resolver task"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        assert client._resolver_corrupt_logged is True
        await client._disconnect()


@pytest.mark.asyncio
async def test_disconnect_awaits_the_resolver_tasks_cancellation_before_returning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Review fix 1: ``_disconnect`` must mirror ``data.py``'s
    ``_cancel_update_instruments`` exactly -- ``task.cancel()`` THEN
    ``await task`` inside ``try``/``except asyncio.CancelledError`` -- so
    shutdown ordering vs the store close is deterministic. A fire-and-forget
    ``.cancel()`` with no following ``await`` never gives the event loop a
    chance to actually deliver the cancellation before ``_disconnect``
    returns, so the resolver task is provably still ``not done()`` right
    after -- that is the RED this test pins closed."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        sender = _SlowSender()
        client, _order_events, _permit, _latch_cm = await _build_race_client(
            tmp_path, sender=sender,
        )
        task = client._resolver_task
        assert task is not None
        assert not task.done()

        await client._disconnect()

        assert task.done(), (
            "_disconnect must await the resolver task's cancellation before "
            "returning, not fire-and-forget it"
        )
        assert client._resolver_task is None
        assert client._store is None


def test_synthetic_get_fill_trade_id_is_a_pure_function_of_venue_order_id() -> None:
    """Slice 3, RED test 4: same input, same output, always -- no clock, no
    counter, no randomness -- and visibly distinguishable from a venue-issued
    trade id via its ``GET-`` prefix."""
    first = _synthetic_get_fill_trade_id("ord-amb-1")
    second = _synthetic_get_fill_trade_id("ord-amb-1")
    assert first == second
    assert first.value == "GET-ord-amb-1"

    other = _synthetic_get_fill_trade_id("ord-amb-2")
    assert other != first
    assert other.value == "GET-ord-amb-2"


@pytest.mark.asyncio
async def test_a_terminal_canceled_with_a_partial_fill_and_a_long_resolves_as_a_terminal_fill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Partial-fill review, RED test 1 (HIGH): CANCELED with filled_qty > 0
    is the normal IOC partial-fill shape (minimumTradeQty 0.01), NOT a
    terminal-zero. It must resolve as a TERMINAL-FILL via
    ``_resolve_accept_fill`` -- same LONG gate, same synthesized TradeId,
    ``fee_reconciled=False`` -- never a silent, forever-AMBIGUOUS wedge."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_CANCELED", cum_quantity=0.5, avg_px="0.40",
        )
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {slug: {"netPosition": "0.5"}},
            "eof": True,
        }
        instrument = build_instrument()

        await _run_resolver_passes(client, count=1)

        assert client._latch is not None
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        assert current.retirement_reason is not None
        assert current.retirement_reason.value == "STATUS_REPORT_ACCEPT_FILL_TERMINAL"
        assert current.intent_id not in client._ambiguous_bookings

        records = client.fill_records_for(instrument.id)
        assert len(records) == 1, "exactly one durable fill record for the partial"
        record = records[0]
        assert record.cumulative_qty == Decimal("0.5")
        assert record.cumulative_cost == Decimal("0.20")
        assert record.fee_reconciled is False

        filled = _order_filled_events(order_events)
        assert len(filled) == 1
        assert filled[0].trade_id.value == f"GET-{order_id}"
        assert filled[0].last_qty.as_decimal() == Decimal("0.5")

        _, remaining = live_trading_budget_remaining(client._permit)
        assert remaining == 1  # true-up releases 0.20 of the 0.40 booked
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_terminal_canceled_with_zero_fill_still_resolves_as_terminal_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Partial-fill review, RED test 1 companion: the SAME terminal status
    with filled_qty == 0 must still resolve as terminal-ZERO, unchanged --
    proving the widened terminal-status set did not blur the two branches
    together."""
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
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {},
            "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        assert client._latch is not None
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        assert current.retirement_reason is not None
        assert current.retirement_reason.value == "STATUS_REPORT_ZERO_FILL_TERMINAL"
        await client._disconnect()


@pytest.mark.asyncio
async def test_partially_filled_never_resolves_and_a_later_terminal_poll_does(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Partial-fill review, RED test 2 (HIGH): PARTIALLY_FILLED is a LIVE
    state and must never resolve the intent -- no record, no retire, the
    loop keeps polling. A LATER poll that returns a genuinely terminal
    status (CANCELED, cum > 0) is the one that resolves it."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_PARTIALLY_FILLED", cum_quantity=0.5,
            avg_px="0.40",
        )
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {slug: {"netPosition": "0.5"}},
            "eof": True,
        }
        instrument = build_instrument()

        await _run_resolver_passes(client, count=1)

        assert client._latch is not None
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN, "PARTIALLY_FILLED must never resolve"
        assert current.intent_id in client._ambiguous_bookings
        assert client.fill_records_for(instrument.id) == ()
        assert _order_filled_events(order_events) == []

        # A later poll: the order reached a genuinely terminal status.
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_CANCELED", cum_quantity=0.5, avg_px="0.40",
        )
        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        assert current.retirement_reason is not None
        assert current.retirement_reason.value == "STATUS_REPORT_ACCEPT_FILL_TERMINAL"
        assert len(client.fill_records_for(instrument.id)) == 1
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_non_positive_avg_px_never_authorizes_a_synthesized_fill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Partial-fill review, RED test 3 (MEDIUM): ``avg_px <= 0`` must stay
    AMBIGUOUS exactly like ``avg_px is None`` -- never ``instrument.
    make_price(0)``, which would synthesize a fill at a nonsensical zero
    price."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_FILLED", cum_quantity=1, avg_px="0.00",
        )
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {slug: {"netPosition": "1"}},
            "eof": True,
        }
        instrument = build_instrument()

        await _run_resolver_passes(client, count=1)

        assert client._latch is not None
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN, "avg_px <= 0 must never authorize a fill"
        assert client.fill_records_for(instrument.id) == ()
        assert _order_filled_events(order_events) == []
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_retire_raise_does_not_kill_the_resolver_task_and_counts_the_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Item 1 (slice 4 review, HIGH): `_retire` raising `SubmitIntentMismatch`
    (ARCH M2) -- or `restore_live_trading_budget` raising
    `LiveTradingPermissionError` -- must never kill
    `_resolve_ambiguous_intents` for the process lifetime. The exception is
    caught, `resolver_error_count` increments, the intent stays OPEN, and
    the VERY NEXT poll still runs against the real `_retire` again."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(tmp_path)
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(order_id, slug=slug, state="ORDER_STATE_CANCELED", cum_quantity=0)
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {},
            "eof": True,
        }
        assert client._latch is not None
        armed = client._latch.current()
        assert armed is not None

        original_retire = client._retire
        should_raise = {"value": True}

        def _maybe_raise(*args: Any, **kwargs: Any) -> None:
            if should_raise["value"]:
                raise SubmitIntentMismatch(armed.intent_id, None, None)
            return original_retire(*args, **kwargs)

        client._retire = _maybe_raise  # type: ignore[method-assign]

        await _run_exactly_one_pass(client)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN, "never retired on the raising pass"
        assert client.resolver_error_count == 1

        # The NEXT pass must still run -- flip back to the real `_retire`
        # and confirm the SAME intent resolves normally on a LATER pass.
        should_raise["value"] = False
        await _run_exactly_one_pass(client)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED, "a later poll must still resolve it"
        assert client.resolver_error_count == 1, "the counter does not grow once the raise stops"
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_family_halt_veto_denies_wait_class_and_spends_zero_permit_slots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Item 4 (slice 4 review, HIGH): the family-halt chokepoint veto, proven
    end to end -- a REAL `TrialDayLatch` (sharing the client's OWN
    submit-intent latch store/flock) whose `record_duplicate_fill` sets the
    durable family-halt key, wrapped by the real `family_halt_submit_veto`
    (composition.py), consulted by the real `_submit_order` immediately
    before the permit spend. A non-None reason denies WAIT-class: zero
    permit slots spent, the reason carried verbatim, and the intent latch
    never arms.

    `client._submit_veto` is assigned post-construction here (never a
    production wiring path) because `_build_race_client`
    (`test_current_rung_hold_pre_arm_race.py`) is out of this seam's file
    list; the constructor kwarg, config field and factory/CLI/composition
    plumbing that reach this exact attribute in production are proven
    separately (mypy + `lint-imports` on `exec/client.py`, `config.py`,
    `factories.py`, `runtime/node_config.py`, `runtime/trade_cli.py`,
    `app/trade.py`).
    """
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        sender = _SlowSender()
        client, order_events, permit, _latch_cm = await _build_race_client(
            tmp_path, sender=sender,
        )
        assert client._latch is not None
        trial_day_latch = open_trial_day_latch(
            client._latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX,
        )
        client._submit_veto = family_halt_submit_veto(  # type: ignore[method-assign]
            trial_day_latch,
        )
        trial_day_latch.record_duplicate_fill(
            "SFO",
            "2026-09-04",
            venue_order_id="venue-order-halt-1",
            qty=Decimal(1),
            fill_px=Decimal("0.50"),
            fee=Decimal("0.01"),
            ts_ns=1,
        )
        _, remaining_before = live_trading_budget_remaining(permit)
        factory = OrderFactory(trader_id=TRADER_ID, strategy_id=STRATEGY_ID, clock=LiveClock())
        command = _submit_command(client, factory, "a")

        await client._submit_order(command)

        denials = [e for e in order_events if isinstance(e, OrderDenied)]
        assert len(denials) == 1
        assert denials[0].reason == "family_halt"
        _, remaining_after = live_trading_budget_remaining(permit)
        assert remaining_after == remaining_before, "a WAIT deny must spend nothing"
        assert client._latch.is_latched() is False, "a WAIT deny must never arm"
        assert sender.calls == [], "the veto must deny before any venue contact"
        await client._disconnect()
