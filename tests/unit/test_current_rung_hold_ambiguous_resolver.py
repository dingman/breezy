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
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest
from nautilus_trader.accounting.factory import AccountFactory
from nautilus_trader.cache.cache import Cache
from nautilus_trader.cache.config import CacheConfig
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.common.enums import ComponentState
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.common.messages import ComponentStateChanged
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.live.config import LiveExecEngineConfig
from nautilus_trader.live.execution_engine import LiveExecutionEngine
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.events import AccountState, OrderDenied
from nautilus_trader.model.identifiers import ClientId, ClientOrderId, Venue, VenueOrderId
from nautilus_trader.model.instruments import BinaryOption

from breezy.adapters.polymarket_us.account_activity import PORTFOLIO_ACTIVITIES_PATH
from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.adapters.polymarket_us.exec.client import (
    _BOOT_PASS_REFUSAL_LATCHES,
    _RECONCILIATION_COUNT_FIELDS,
    # EDGE-2 slice D (AC4(c)): the activities pagination tunables, asserted
    # directly by the `_order_trade_activity` cursor-forwarding tests below.
    _RESOLVER_ACTIVITY_MAX_PAGES,
    _RESOLVER_ACTIVITY_PAGE_LIMIT,
    _RESOLVER_ACTIVITY_SORT_ORDER,
    _RESOLVER_INSTRUMENT_LOAD_RETRY_NS,
    # EDGE-2 slice D (AC4(d)): every resolver-pass fixture that drives a
    # zero-fill decision must now age its context past this floor -- see
    # `_ARMED_AGE_PAST_MIN_NS` and `_backdate_resolver_context` below.
    _RESOLVER_ZERO_FILL_MIN_AGE_NS,
    _VENUE_ID_MAP_WRITE_FAILED,
    FILL_INDEX_KEY_PREFIX,
    FILL_KEY_PREFIX,
    RESOLVER_CONTEXT_KEY_PREFIX,
    RESOLVER_FILL_NOT_BOOKED,
    AmbiguousResolverContext,
    DurableFillRecord,
    PolymarketUSExecutionClient,
    StartupPositionSnapshot,
    _resolver_long_position_state,
    _synthetic_get_fill_trade_id,
)
from breezy.adapters.polymarket_us.exec.endpoints import (
    ACCOUNT_BALANCES_PATH,
    OPEN_ORDERS_PATH,
    PORTFOLIO_POSITIONS_PATH,
)
from breezy.adapters.polymarket_us.operator_controls import (
    MAX_DAILY_BUDGET_USD_ENV_VAR,
    MAX_POSITION_COST_USD_ENV_VAR,
    DailySpendLedger,
)
from breezy.adapters.polymarket_us.parsing import parse_binary_option
from breezy.adapters.polymarket_us.safety import (
    issue_live_trading_permit,
    live_trading_budget_remaining,
)
from breezy.adapters.polymarket_us.symbology import (
    POLYMARKET_US_VENUE,
    base_slug_of,
    instrument_id_to_slug,
)
from breezy.adapters.polymarket_us.transport import VenueResponse
from breezy.runtime.component_health_watch import install_resolver_contradiction_alert
from breezy.runtime.health import AlertPayload
from breezy.runtime.sqlite_store import SqliteStateStore
from breezy.runtime.submit_intent import (
    CURRENT_INTENT_KEY,
    RetirementReason,
    SubmitIntent,
    SubmitIntentCorrupt,
    SubmitIntentMismatch,
    SubmitIntentState,
    open_submit_intent_latch,
)
from breezy.strategy.current_rung_hold.composition import family_halt_submit_veto
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    open_trial_day_latch,
)
from tests.unit.operator_control_env import operator_control_env
from tests.unit.polymarket_us_exec_shapes import (
    TS_EVENT_TEXT,
    TS_INIT,
    build_instrument,
    build_no_leg_instrument,
    build_position,
    build_second_instrument,
)
from tests.unit.test_current_rung_hold_pre_arm_race import (
    ACCOUNT_NUMBER,
    CLIENT_ID,
    STRATEGY_ID,
    TRADER_ID,
    _build_race_client,
    _SlowSender,
    _submit_command,
)
from tests.unit.test_polymarket_us_permit_issuance import credentials, enable_operator_gate
from tests.unit.test_polymarket_us_submit_order_chain import (
    _balances_payload,
    _FakeSigner,
    _PrivateReadStub,
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


#: The venue's REAL terminal-order shape (2026-09-24 production evidence,
#: venue order CP05MNWMAWP6): ``leavesQuantity=0`` regardless of how much of
#: ``quantity`` filled -- mirrors
#: ``reports._TERMINAL_ORDER_STATUSES``/``ORDER_STATE_TO_ORDER_STATUS``, kept
#: as raw venue strings here since this module never imports the mapped
#: enum. Used only to pick ``_order_get_body``'s DEFAULT ``leavesQuantity``.
_TERMINAL_STATES_FOR_LEAVES_DEFAULT = frozenset(
    {"ORDER_STATE_FILLED", "ORDER_STATE_CANCELED", "ORDER_STATE_REJECTED", "ORDER_STATE_EXPIRED"}
)


def _order_get_body(
    order_id: str,
    *,
    slug: str,
    state: str,
    cum_quantity: float,
    avg_px: str | None = None,
    leaves_quantity: float | None = None,
) -> dict[str, Any]:
    """``leaves_quantity`` defaults to the venue's real shape: 0 for a
    terminal ``state`` (regardless of how ``cum_quantity`` split against
    ``quantity``), or the ``quantity - cumQuantity`` identity for a live
    state. Override explicitly only to construct a deliberately
    inconsistent body."""
    if leaves_quantity is None:
        leaves_quantity = 0 if state in _TERMINAL_STATES_FOR_LEAVES_DEFAULT else 1 - cum_quantity
    order: dict[str, Any] = {
        "id": order_id,
        "marketSlug": slug,
        "side": "ORDER_SIDE_BUY",
        "intent": "ORDER_INTENT_BUY_LONG",
        "type": "ORDER_TYPE_LIMIT",
        "price": {"value": "0.40", "currency": "USD"},
        "quantity": 1,
        "cumQuantity": cum_quantity,
        "leavesQuantity": leaves_quantity,
        "tif": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
        "state": state,
        "createTime": TS_EVENT_TEXT,
    }
    if avg_px is not None:
        order["avgPx"] = {"value": avg_px, "currency": "USD"}
    return {
        "order": order
    }


def _no_leg_order_get_body(
    order_id: str,
    *,
    slug: str,
    state: str,
    cum_quantity: float,
    avg_px: str | None = None,
    leaves_quantity: float | None = None,
) -> dict[str, Any]:
    """EDGE-2C: :func:`_order_get_body`'s NO-leg sibling. The venue's real
    echo for an OPENING order on the NO leg is exactly
    ``(ORDER_SIDE_SELL, ORDER_INTENT_BUY_SHORT)``
    (``leg_prices.VENUE_SIDE_FOR_LEG``/``VENUE_INTENT_FOR_LEG``,
    ``assert_echo_matches_leg``), never the YES leg's
    ``(ORDER_SIDE_BUY, ORDER_INTENT_BUY_LONG)`` `_order_get_body` always
    builds -- a NO-leg GET body carrying the YES echo would itself be
    refused by ``_order_side_for_leg`` as a wrong-leg echo, unrelated to the
    crash this module tests."""
    body = _order_get_body(
        order_id,
        slug=slug,
        state=state,
        cum_quantity=cum_quantity,
        avg_px=avg_px,
        leaves_quantity=leaves_quantity,
    )
    body["order"]["side"] = "ORDER_SIDE_SELL"
    body["order"]["intent"] = "ORDER_INTENT_BUY_SHORT"
    return body


#: EDGE-2 slice D (AC4(d)): comfortably past `_RESOLVER_ZERO_FILL_MIN_AGE_NS`
#: (one extra second) -- every fixture in this module that drives a
#: zero-fill decision through the FULL `_resolve_ambiguous_intents` pass
#: must age its context past the floor, since a fresh `LiveClock()`-stamped
#: context (the pre-slice-D shape every helper here built) is always well
#: under it.
_ARMED_AGE_PAST_MIN_NS: Final[int] = _RESOLVER_ZERO_FILL_MIN_AGE_NS + 1_000_000_000


def _backdate_resolver_context(
    client: PolymarketUSExecutionClient, intent_id: str, *, age_ns: int = _ARMED_AGE_PAST_MIN_NS,
) -> None:
    """Rewrite the durable resolver context's ``created_ns`` to ``age_ns``
    before "now" -- mirrors :func:`_rewrite_resolver_context_instrument`'s
    in-place rewrite pattern. Without this, EVERY resolver-pass fixture
    below would fail AC4(d)'s new minimum-age gate: a `LiveClock()`-stamped
    context is always well under
    :data:`_RESOLVER_ZERO_FILL_MIN_AGE_NS`, and the plan's own r3 AC4(d)
    makes that floor mandatory for a resolver zero-fill, superseding the
    pre-slice-D immediate-retirement shape these fixtures originally built.
    """
    raw = client._store_get(f"{RESOLVER_CONTEXT_KEY_PREFIX}{intent_id}")
    assert raw is not None
    context = AmbiguousResolverContext.from_bytes(raw)
    backdated_ns = client._clock.timestamp_ns() - age_ns
    rewritten = replace(context, created_ns=backdated_ns)
    client._store_set(f"{RESOLVER_CONTEXT_KEY_PREFIX}{intent_id}", rewritten.to_bytes())


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
    # FU-8: the real `ExecutionEngine` adds a submitted order to the cache
    # BEFORE it ever reaches the client (`execution/engine.pyx:1122`). This
    # harness calls `_submit_order` directly, bypassing that engine step, so
    # it is replicated here -- otherwise `self._cache.order(...)` can never
    # find an order THIS SAME test run submitted, which is exactly the
    # cross-session shape `_resolver_fill_order_unknown` (FU-8) exists to
    # detect, and every same-session resolver fixture below would be
    # spuriously treated as cross-session.
    client._cache.add_order(command.order, position_id=None)
    await client._submit_order(command)

    assert client._latch is not None
    assert client._latch.is_latched() is True, "the with-id AMBIGUOUS outcome must leave OPEN"
    # EDGE-2 slice D (AC4(d)): age the context past the new mandatory
    # zero-fill min-age floor -- see `_backdate_resolver_context`'s own
    # docstring. A CALLER that needs to test the floor ITSELF (a fresh,
    # unaged context) rewrites `created_ns` back via the SAME helper.
    current = client._latch.current_open()
    assert current is not None
    _backdate_resolver_context(client, current.intent_id)
    instrument = build_instrument()
    slug = instrument_id_to_slug(instrument.id)
    return client, order_id, slug, latch_cm, order_events


async def _arm_one_ambiguous_intent_isolating_resolver_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[PolymarketUSExecutionClient, str, str, Any, list[Any]]:
    """Like :func:`_arm_one_ambiguous_intent`, but suppresses A1-a's
    submit-path venue-id-map write during arming.

    Without this, every resolver-side venue-id-map test below would be
    VACUOUS: the very submit that goes with-id AMBIGUOUS already runs
    through A1-a (the one point ALL FOUR outcome kinds pass through), which
    writes the row before the resolver ever runs. A test asserting only
    that the row exists afterward could not tell A1-a's write apart from
    A1-b/A1-c's -- exactly the vacuity shape A-B3 already found once.
    """
    with monkeypatch.context() as isolating:
        isolating.setattr(
            PolymarketUSExecutionClient,
            "record_venue_order_id",
            lambda self, venue_order_id, client_order_id: None,
        )
        result = await _arm_one_ambiguous_intent(tmp_path)
    client, order_id = result[0], result[1]
    assert client.client_order_id_for(VenueOrderId(order_id)) is None, (
        "the submit-path write must be suppressed for this fixture to be non-vacuous"
    )
    return result


async def _arm_one_no_leg_ambiguous_intent(
    tmp_path: Path,
) -> tuple[PolymarketUSExecutionClient, str, str, Any]:
    """EDGE-2C: arms an account-wide OPEN intent whose durable resolver
    context points at the NO-leg sibling of :func:`build_instrument`'s
    market -- the with-id AMBIGUOUS shape a real NO-side entry leaves (S5).

    Built directly against the latch/context primitives (the same shape
    ``test_no_side_fill_attribution_2026_09_14.py``'s
    ``test_a_resolved_fill_books_to_the_context_instrument_not_a_slug_lookup``
    uses), never through ``_submit_order``: every submission rig in THIS
    module (``_submit_command``) hard-codes the YES instrument.

    Returns the client, the venue order id, the NO leg's base slug (equal to
    the YES leg's -- both legs share one market), and the latch context
    manager the caller MUST keep referenced.
    """
    sender = _SlowSender()
    client, _order_events, _permit, latch_cm = await _build_race_client(tmp_path, sender=sender)
    no_instrument = build_no_leg_instrument()
    client._cache.add_instrument(no_instrument)
    client._instrument_provider.add(no_instrument)
    slug = base_slug_of(no_instrument.id)

    armed = client._latch.arm("1" * 64, now_ns=client._clock.timestamp_ns())
    venue_order_id = "ord-no-amb-1"
    context = AmbiguousResolverContext(
        intent_id=armed.intent_id,
        venue_order_id=venue_order_id,
        instrument_id=str(no_instrument.id),
        client_order_id="O-NO-AMB-1",
        strategy_id=STRATEGY_ID.value,
        notional_usd=Decimal("0.40"),
        booking_id=1,
        # EDGE-2 slice D (AC4(d)): pre-aged past the mandatory zero-fill
        # min-age floor -- see `_backdate_resolver_context`'s docstring.
        created_ns=client._clock.timestamp_ns() - _ARMED_AGE_PAST_MIN_NS,
    )
    client._store_set(f"{RESOLVER_CONTEXT_KEY_PREFIX}{armed.intent_id}", context.to_bytes())
    return client, venue_order_id, slug, latch_cm


def _foreign_venue_instrument() -> BinaryOption:
    """EDGE-2C test 8: the SAME captured market as :func:`build_instrument`,
    parsed onto a venue that is NOT ``POLYMARKET_US`` -- ``base_slug_of``'s
    own venue check (``symbology.py:310-314``) raises ``VenuePayloadError``
    for it, a slug-derivation failure this plan's AC3 guard must survive
    (unlike the NO-leg reserved-separator raise AC1 makes disappear
    entirely, THIS raise still happens after the fix -- it is exactly what
    the guard exists for)."""
    market: dict[str, Any] = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "docs"
            / "evidence"
            / "venue"
            / "polymarket_us"
            / "raw"
            / "market_open_510636_by_slug.json"
        ).read_text(encoding="utf-8")
    )
    return parse_binary_option(market, venue=Venue("KALSHI"), ts_init=TS_INIT)


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


# ==========================================================================
# EDGE-2 slice A (AC3): `AmbiguousResolverContext.create_fill_evidence` --
# the closed-set `createFillEvidence` token threaded from
# `submit_chain.create_fill_evidence` through `_note_ambiguous_open` into the
# durable context, with the same AR-N6 trailing-optional shape as
# `create_detail`/`fill_parse_error`/`order_side`.
# ==========================================================================


def test_resolver_context_round_trips_create_fill_evidence() -> None:
    """A NEW row round-trips whatever token it was given, through
    `to_bytes`/`from_bytes`."""
    context = AmbiguousResolverContext(
        intent_id="intent-cfe",
        venue_order_id="venue-cfe",
        instrument_id="instrument-cfe",
        client_order_id="client-cfe",
        strategy_id="strategy-cfe",
        notional_usd=Decimal("1.00"),
        booking_id=1,
        created_ns=TS_INIT,
        create_fill_evidence=submit_chain.CREATE_FILL_EVIDENCE_FILL_TYPE_PRESENT,
    )
    round_tripped = AmbiguousResolverContext.from_bytes(context.to_bytes())
    assert round_tripped.create_fill_evidence == submit_chain.CREATE_FILL_EVIDENCE_FILL_TYPE_PRESENT


def test_legacy_resolver_context_without_field_decodes_as_unknown() -> None:
    """AR-N6: a blob written before EDGE-2 slice A (no `createFillEvidence`
    key at all) decodes to `submit_chain.CREATE_FILL_EVIDENCE_UNKNOWN` --
    the same token an unparseable create-order body renders, since neither
    case tells the resolver anything about create-time fill evidence."""
    old_blob = json.dumps(
        {
            "intentId": "intent-old-cfe",
            "venueOrderId": "venue-old-cfe",
            "instrumentId": "instrument-old-cfe",
            "clientOrderId": "client-old-cfe",
            "strategyId": "strategy-old-cfe",
            "notionalUsd": "1.00",
            "bookingId": 11,
            "createdNs": TS_INIT,
        },
        sort_keys=True,
    ).encode("utf-8")

    old_context = AmbiguousResolverContext.from_bytes(old_blob)
    assert old_context.create_fill_evidence == submit_chain.CREATE_FILL_EVIDENCE_UNKNOWN


@pytest.mark.asyncio
async def test_submit_order_passes_response_body_evidence_to_note_ambiguous_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """End-to-end: `_submit_order`'s with-id AMBIGUOUS branch computes
    `submit_chain.create_fill_evidence(response.body)` and threads its
    `.token` into the durable `AmbiguousResolverContext` -- never a price,
    quantity, or id, and never `unknown` for a body that parsed cleanly to
    `executions: []` (that is `none`, a decided absence, not decode
    failure)."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        current = client._latch.current_open()
        assert current is not None
        raw_context = client._store_get(f"{RESOLVER_CONTEXT_KEY_PREFIX}{current.intent_id}")
        assert raw_context is not None
        context = AmbiguousResolverContext.from_bytes(raw_context)
        assert context.venue_order_id == order_id
        assert context.create_fill_evidence == submit_chain.CREATE_FILL_EVIDENCE_NONE
        await client._disconnect()


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
async def test_a_get_confirmed_expired_zero_fill_with_real_venue_leaves_retires(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """2026-09-24 production evidence (venue order CP05MNWMAWP6): a
    read-only GET of the stuck order returned
    ``state=ORDER_STATE_EXPIRED, quantity=1, cumQuantity=0,
    leavesQuantity=0`` -- the venue's REAL terminal-order shape, not the
    ``leaves == quantity - cumQuantity`` identity every other test in this
    module builds via ``_order_get_body``'s default formula. Before the fix,
    ``parse_order_status_report`` refused this body (1 - 0 = 1 != 0), the
    resolver logged ``mapping_error`` and stayed AMBIGUOUS forever, and the
    submit intent never retired -- the exact shape that blocked the
    supervisor from launching the node. This proves the resolver now
    RETIRES it as a terminal zero-fill (Resolution D) instead."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(tmp_path)
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_EXPIRED", cum_quantity=0,
            leaves_quantity=0,
        )
        # eof-complete, no LONG anywhere.
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {},
            "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        assert client._latch is not None
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED, (
            "must retire, not stay AMBIGUOUS, on the venue's real terminal "
            "leavesQuantity=0 shape"
        )
        assert current.retirement_reason is not None
        assert current.retirement_reason.value == "STATUS_REPORT_ZERO_FILL_TERMINAL"
        assert current.intent_id not in client._ambiguous_bookings
        await client._disconnect()


def _rewrite_resolver_context_instrument(
    client: PolymarketUSExecutionClient, intent_id: str, instrument_id: str,
) -> None:
    """Rewrite the durable resolver context's ``instrument_id`` in place --
    simulates the production shape (2026-09-24, node NODE-A boot log): a
    with-id AMBIGUOUS intent whose instrument belongs to a PRIOR day's node
    boot and is absent from THIS run's cache/instrument-provider universe
    (the node boots for TODAY's instruments only, per
    ``resolve_station_instrument_ids``)."""
    raw = client._store_get(f"{RESOLVER_CONTEXT_KEY_PREFIX}{intent_id}")
    assert raw is not None
    context = AmbiguousResolverContext.from_bytes(raw)
    rewritten = replace(context, instrument_id=instrument_id)
    client._store_set(f"{RESOLVER_CONTEXT_KEY_PREFIX}{intent_id}", rewritten.to_bytes())


@pytest.mark.asyncio
async def test_a_stuck_prior_day_instrument_absent_from_cache_is_loaded_and_retires(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """2026-09-24 production deadlock: an OPEN intent's instrument belongs
    to YESTERDAY's node boot and is absent from THIS run's cache. Before the
    fix the resolver logged a WARN every pass forever and never retired,
    deadlocking the supervisor's launch gate across days. A loader that CAN
    produce the definition (mirrors the ParquetDataCatalog historical read
    ``resolve_station_instrument_ids`` already uses) must be consulted and
    the result added to the cache -- never fetched through the venue-backed
    ``InstrumentProvider`` (which refuses anything outside the latest
    discovery cycle for an expired market -- ``load_ids_async``,
    ``provider.py:437-453``) and never subscribed to market data."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        stale_instrument = build_second_instrument()
        assert client._cache.instrument(stale_instrument.id) is None, (
            "fixture invariant: the stale instrument must start absent from the cache"
        )
        current = client._latch.current_open()
        assert current is not None
        _rewrite_resolver_context_instrument(client, current.intent_id, str(stale_instrument.id))
        stale_slug = instrument_id_to_slug(stale_instrument.id)
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=stale_slug, state="ORDER_STATE_EXPIRED", cum_quantity=0,
            leaves_quantity=0,
        )
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {},
            "eof": True,
        }

        loader_calls: list[str] = []

        def _loader(instrument_id: str) -> Any:
            loader_calls.append(instrument_id)
            return stale_instrument if instrument_id == str(stale_instrument.id) else None

        client._resolver_instrument_loader = _loader  # type: ignore[method-assign]

        def _forbidden(*_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError(
                "the resolver must never reach the venue-backed InstrumentProvider "
                "(a subscription/network path) to resolve a past-day instrument"
            )

        monkeypatch.setattr(client._instrument_provider, "load", _forbidden)
        monkeypatch.setattr(client._instrument_provider, "load_async", _forbidden)
        monkeypatch.setattr(client._instrument_provider, "load_ids_async", _forbidden)

        await _run_resolver_passes(client, count=1)

        assert loader_calls == [str(stale_instrument.id)]
        assert client._cache.instrument(stale_instrument.id) is stale_instrument
        # (c) No market-data subscription: the venue-backed provider never
        # learns about the loaded instrument -- a pure Cache write, nothing else.
        assert client._instrument_provider.find(stale_instrument.id) is None

        refreshed = client._latch.current()
        assert refreshed is not None
        assert refreshed.state is SubmitIntentState.RETIRED
        assert refreshed.retirement_reason is not None
        assert refreshed.retirement_reason.value == "STATUS_REPORT_ZERO_FILL_TERMINAL"
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_stuck_prior_day_instrument_unobtainable_stays_open_and_escalates_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """When the loader cannot produce the definition (catalog miss, or no
    loader injected at all) the intent must stay AMBIGUOUS and OPEN forever
    -- retiring without venue evidence is forbidden -- but the operator must
    see ONE ERROR naming the instrument, not a WARN every poll interval for
    the process lifetime.

    ``self._log`` is Nautilus's own Cython logger (not stdlib ``logging``);
    ``caplog``/``monkeypatch.setattr`` cannot observe or replace it -- see
    ``test_connect_immediate_pass_exception_handler_logs_type_only_never_the_value``
    above and ``test_ambiguous_exception_path_source_logs_the_exception_type_never_its_str``
    in ``test_polymarket_us_submit_order_chain.py`` for the same,
    already-established limitation. The dedup set the resolver must guard
    the ERROR with is asserted directly (the exact idiom
    ``_resolver_stale_alerted_intent_ids`` already uses above), plus a
    static source-shape check that the ``self._log.error`` call site is
    gated by membership in that set."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, _order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        stale_instrument = build_second_instrument()
        current = client._latch.current_open()
        assert current is not None
        _rewrite_resolver_context_instrument(client, current.intent_id, str(stale_instrument.id))
        client._resolver_instrument_loader = lambda _instrument_id: None  # type: ignore[method-assign]

        await _run_resolver_passes(client, count=3)

        refreshed = client._latch.current()
        assert refreshed is not None
        assert refreshed.state is SubmitIntentState.OPEN, (
            "never retire an intent without venue evidence for its own instrument"
        )
        # Escalated exactly once -- the dedup set carries exactly this one
        # instrument id despite 3 passes each re-observing the cache miss.
        assert client._resolver_missing_instrument_logged == {str(stale_instrument.id)}
        await client._disconnect()


def test_the_missing_instrument_escalation_is_gated_by_the_dedup_set() -> None:
    """Static pin (see the docstring above): the source must guard
    ``self._log.error`` for the missing-instrument case with the SAME
    ``not in ... / | {...}`` dedup shape ``_resolver_stale_alerted_intent_ids``
    already uses, never an unconditional per-pass call."""
    import inspect

    source = inspect.getsource(PolymarketUSExecutionClient._resolve_ambiguous_intents)
    marker = "_resolver_missing_instrument_logged"
    assert marker in source, "the resolver must carry a missing-instrument dedup set"
    idx = source.index(marker)
    guard_block = source[max(0, idx - 200) : idx + 400]
    assert "self._log.error" in guard_block
    assert "not in" in guard_block


def _backdate_load_attempt(
    client: PolymarketUSExecutionClient, instrument_id: str, *, ago_ns: int,
) -> None:
    """Rewrite the resolver's recorded last-attempt timestamp for
    ``instrument_id`` to ``ago_ns`` nanoseconds before the REAL clock's
    current reading -- the SAME backdating idiom
    ``test_a_stale_open_intent_alerts_once_and_resets_on_retirement`` above
    uses for ``context.created_ns``. ``self._clock`` on this Nautilus
    ``Component`` is a read-only Cython attribute (``AttributeError:
    attribute '_clock' ... is not writable``) and cannot be swapped for a
    fake, so the elapsed-time seam this module controls instead is the
    resolver's OWN plain-dict bookkeeping."""
    client._resolver_instrument_load_attempted_ns = {
        **client._resolver_instrument_load_attempted_ns,
        instrument_id: client._clock.timestamp_ns() - ago_ns,
    }


@pytest.mark.asyncio
async def test_a_load_miss_does_not_rescan_the_catalog_within_the_retry_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """HIGH review fix (2026-09-24, post-ac691dc): the loader is a
    synchronous full-catalog scan measured at 1.06-1.36s against the
    production catalog -- a MISS must not re-invoke it on every ~5s poll
    forever. Only the FIRST pass (no prior attempt recorded) may call it;
    every later pass within ``_RESOLVER_INSTRUMENT_LOAD_RETRY_NS`` must
    skip the call entirely."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, _order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        stale_instrument = build_second_instrument()
        current = client._latch.current_open()
        assert current is not None
        _rewrite_resolver_context_instrument(client, current.intent_id, str(stale_instrument.id))

        loader_calls: list[str] = []

        def _loader(instrument_id: str) -> Any:
            loader_calls.append(instrument_id)
            return None

        client._resolver_instrument_loader = _loader  # type: ignore[method-assign]

        await _run_resolver_passes(client, count=1)
        assert loader_calls == [str(stale_instrument.id)], "the first pass must attempt the scan"

        # Well within the retry interval -- real elapsed test-runtime is
        # microseconds; several more passes must not re-invoke the scan.
        await _run_resolver_passes(client, count=3)
        assert loader_calls == [str(stale_instrument.id)], (
            "a miss must not re-invoke the loader again before the retry interval elapses"
        )

        # Explicitly close to, but still short of, the retry interval -- 5s
        # margin (not 1ns) so the assertion is not flaky against the real
        # wall-clock jitter between the backdate call and the resolver's
        # OWN later `self._clock.timestamp_ns()` read inside the pass.
        _backdate_load_attempt(
            client,
            str(stale_instrument.id),
            ago_ns=_RESOLVER_INSTRUMENT_LOAD_RETRY_NS - 5_000_000_000,
        )
        await _run_resolver_passes(client, count=1)
        assert loader_calls == [str(stale_instrument.id)], (
            "well short of the retry interval must still skip the scan"
        )
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_load_miss_engages_the_same_consecutive_failure_backoff_as_a_get_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """HIGH review fix: a miss must count toward the SAME
    ``_resolver_consecutive_failures`` backoff the GET-exception and
    mapping-error branches already use -- not a separate, unthrottled
    failure mode."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, _order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        stale_instrument = build_second_instrument()
        current = client._latch.current_open()
        assert current is not None
        _rewrite_resolver_context_instrument(client, current.intent_id, str(stale_instrument.id))
        client._resolver_instrument_loader = lambda _id: None  # type: ignore[method-assign]

        assert client._resolver_consecutive_failures == 0

        await _run_resolver_passes(client, count=1)

        assert client._resolver_consecutive_failures >= 1
        assert client._resolver_last_failure_kind[current.intent_id] == "instrument_unavailable"
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_load_hit_after_the_retry_interval_retires_the_intent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """HIGH review fix: a catalog catch-up must still resolve the intent --
    once ``_RESOLVER_INSTRUMENT_LOAD_RETRY_NS`` has elapsed since the last
    (missed) attempt, a later pass whose loader now returns the definition
    must retire the intent exactly as the happy path does."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        stale_instrument = build_second_instrument()
        current = client._latch.current_open()
        assert current is not None
        _rewrite_resolver_context_instrument(client, current.intent_id, str(stale_instrument.id))

        miss_calls = {"n": 0}

        def _missing_loader(_id: str) -> Any:
            miss_calls["n"] += 1
            return None

        client._resolver_instrument_loader = _missing_loader  # type: ignore[method-assign]
        await _run_resolver_passes(client, count=1)
        assert miss_calls["n"] == 1
        refreshed = client._latch.current()
        assert refreshed is not None
        assert refreshed.state is SubmitIntentState.OPEN

        # The catalog "catches up" and the retry interval elapses.
        _backdate_load_attempt(
            client, str(stale_instrument.id), ago_ns=_RESOLVER_INSTRUMENT_LOAD_RETRY_NS,
        )
        stale_slug = instrument_id_to_slug(stale_instrument.id)
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=stale_slug, state="ORDER_STATE_EXPIRED", cum_quantity=0,
            leaves_quantity=0,
        )
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {},
            "eof": True,
        }
        client._resolver_instrument_loader = (  # type: ignore[method-assign]
            lambda instrument_id: stale_instrument
            if instrument_id == str(stale_instrument.id)
            else None
        )

        # `_run_resolver_passes` bounds its wait to a FIXED count of
        # zero-delay `asyncio.sleep(0)` yields -- correct for every OTHER
        # pass in this test file, which never actually leaves the event
        # loop, but WRONG here: the retry gate now passes, so THIS pass
        # calls the loader via `self._loop.run_in_executor(...)` -- a real
        # hop to an OS thread whose completion is posted back via
        # `call_soon_threadsafe` from a different thread and races the
        # fixed yield budget. Confirmed by direct instrumentation: the gate
        # evaluates correctly every time (elapsed >= the interval, since
        # real wall-clock time only moves forward from the backdate call),
        # but intermittently the resolver task was still suspended on that
        # executor Future -- never having reached
        # `self._cache.add_instrument(instrument)` -- when
        # `_run_resolver_passes` cancelled it after its fixed budget ran
        # out. A pure yield-count bound (even a large one) is still a CPU
        # proxy for wall time, not wall time itself, and can be exhausted in
        # a few milliseconds regardless of count -- too short if the host is
        # under memory pressure and the executor thread hop is slow. Poll
        # for the actual observable outcome against a real wall-clock
        # deadline instead: deterministic because it terminates on the real
        # condition, and still bounded so a genuine regression fails loudly
        # rather than hanging.
        client._resolver_poll_interval_secs = lambda: 0.0  # type: ignore[method-assign]
        resolver_task = asyncio.get_event_loop().create_task(
            client._resolve_ambiguous_intents(),
        )
        try:
            deadline = time.monotonic() + 10.0
            while True:
                refreshed = client._latch.current()
                if refreshed is not None and refreshed.state is SubmitIntentState.RETIRED:
                    break
                if time.monotonic() >= deadline:
                    pytest.fail(
                        "the load-hit pass never retired the intent within the poll budget",
                    )
                await asyncio.sleep(0.005)
        finally:
            resolver_task.cancel()
            await asyncio.gather(resolver_task, return_exceptions=True)

        assert client._cache.instrument(stale_instrument.id) is stale_instrument
        refreshed = client._latch.current()
        assert refreshed is not None
        assert refreshed.state is SubmitIntentState.RETIRED
        assert refreshed.retirement_reason is not None
        assert refreshed.retirement_reason.value == "STATUS_REPORT_ZERO_FILL_TERMINAL"
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
        # B0-d/AC-5: the self-labelling GET- synthetic trade id, and the
        # venue's own echoed ORIGINAL order size (`report.quantity`, a
        # DIFFERENT field from `cumulative_qty`/`filled_qty` above).
        assert record.trade_id == f"GET-{order_id}"
        assert record.order_qty == Decimal(1)
        # AUD-13b (ruling R-1 = O4 mechanism (a)): the RESOLVER write site
        # stamps the theta of the Instrument in hand (the fixture's 0.06) and
        # the ruled fee source -- no venue fee on an Order-only GET, so MODELLED.
        assert record.fee_coefficient_at_fill == Decimal("0.06")
        assert record.fee_source == "MODELLED_AT_FILL_TIME"

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


@pytest.mark.asyncio
async def test_a_resolver_retire_records_the_venue_id_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """A1-b: the venue id -> client order id map is backfilled on the
    resolver's accept-fill terminal -- the durable attribution for a
    context written before this change ever shipped (the submit-path write
    is suppressed by the fixture below so this test cannot be satisfied by
    A1-a's own write instead)."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = (
            await _arm_one_ambiguous_intent_isolating_resolver_writes(tmp_path, monkeypatch)
        )
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

        assert client.client_order_id_for(VenueOrderId(order_id)) is not None
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_resolver_terminal_zero_retire_records_the_venue_id_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """A1-c (AM-10): the SAME backfill on the resolver's OTHER terminal --
    a separate method with a different post-condition, so one test cannot
    drive both (AM-10). The submit-path write is suppressed (see the
    fixture docstring) so this cannot be satisfied by A1-a instead."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = (
            await _arm_one_ambiguous_intent_isolating_resolver_writes(tmp_path, monkeypatch)
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(order_id, slug=slug, state="ORDER_STATE_CANCELED", cum_quantity=0)
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {},
            "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        assert client.client_order_id_for(VenueOrderId(order_id)) is not None
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_resolver_accept_fill_with_no_same_process_booking_still_records_the_venue_id_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """(B-2) The ONLY test that catches a wrong-indent A1-b: every OTHER
    resolver fixture builds a booking, so a block placed inside `if booking
    is not None:` would pass every one of them while silently skipping the
    write on exactly the post-restart reconciliation path A1 exists to
    serve -- `_ambiguous_bookings` is same-process-only and EMPTY after a
    restart (`client.py` around `_resolve_accept_fill`'s booking pop).
    MUTATION pair 5 moves the A1-b block to the wrong indent and shows THIS
    test, and only this test, go RED."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = (
            await _arm_one_ambiguous_intent_isolating_resolver_writes(tmp_path, monkeypatch)
        )
        assert client._latch is not None
        armed = client._latch.current()
        assert armed is not None
        # Simulate the post-restart shape directly: no same-process booking.
        client._ambiguous_bookings.pop(armed.intent_id, None)
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

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED, (
            "the terminal must still complete with no booking present"
        )
        assert client.client_order_id_for(VenueOrderId(order_id)) is not None
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_map_write_failure_still_retires_and_fills_on_the_accept_fill_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """(A-B2) A `record_venue_order_id` raise must REFUSE and FALL THROUGH,
    never `return`: `_retire`, the budget true-up/unrestore check and
    `generate_order_filled` must all still run."""
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
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {slug: {"netPosition": "1"}},
            "eof": True,
        }

        def _boom(venue_order_id: VenueOrderId, client_order_id: ClientOrderId) -> None:
            raise RuntimeError("simulated venue-id map write failure")

        monkeypatch.setattr(client, "record_venue_order_id", _boom)

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        assert client.trading_refusals[-1] == _VENUE_ID_MAP_WRITE_FAILED
        filled = _order_filled_events(order_events)
        assert len(filled) == 1, "generate_order_filled must still run"
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_map_write_failure_still_retires_and_cancels_on_the_terminal_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """(A-B2) The same guard on the OTHER terminal: `_retire`,
    `true_up_booking`, `restore_live_trading_budget`,
    `_write_startup_position_evidence` and `generate_order_canceled` must
    all still run after a `record_venue_order_id` raise (N2)."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(order_id, slug=slug, state="ORDER_STATE_CANCELED", cum_quantity=0)
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {},
            "eof": True,
        }

        def _boom(venue_order_id: VenueOrderId, client_order_id: ClientOrderId) -> None:
            raise RuntimeError("simulated venue-id map write failure")

        monkeypatch.setattr(client, "record_venue_order_id", _boom)

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        assert client.trading_refusals[-1] == _VENUE_ID_MAP_WRITE_FAILED
        _, remaining_count = live_trading_budget_remaining(client._permit)
        assert remaining_count == 2, "restore_live_trading_budget must still run"
        evidence = client.read_startup_position_evidence()
        assert evidence is not None, "_write_startup_position_evidence must still run"
        canceled = [e for e in order_events if type(e).__name__ == "OrderCanceled"]
        assert len(canceled) == 1, "generate_order_canceled must still run"
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
            client._latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, family_id="pm_us_crh_v4",
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


@pytest.mark.asyncio
async def test_a_policy_halt_veto_denies_wait_class_and_spends_zero_permit_slots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AUD-02b (§7 step 0a test (1)): the SAME end-to-end proof as
    ``test_a_family_halt_veto_denies_wait_class_and_spends_zero_permit_slots``
    immediately above, but the halt is set via the NEW
    ``TrialDayLatch.record_policy_halt`` (the write
    ``breezy-set-family-halt`` uses) rather than
    ``record_duplicate_fill`` -- proving the new writer's payload is read by
    the SAME ``is_family_halted`` and denied by the SAME
    ``family_halt_submit_veto`` chokepoint, with no new mechanism.
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
            client._latch, key_prefix=CONTINUOUS_TRIAL_KEY_PREFIX, family_id="pm_us_crh_v4",
        )
        client._submit_veto = family_halt_submit_veto(  # type: ignore[method-assign]
            trial_day_latch,
        )
        trial_day_latch.record_policy_halt(
            reason="AUD-02b: enforcing RULING_A1 disposition (ii)",
            evidence_sha256="0" * 64,
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


# ---------------------------------------------------------------------------
# Item 2 (2026-09-12, boot-ordering addendum): `_connect` must run ONE
# synchronous resolver pass, with NO initial sleep, before it returns -- so a
# durable fill record for an unresolved with-id intent exists before
# Nautilus's own kernel-level reconciliation ever runs. Ordering only: the
# classification rule itself (`fee_reconciled=False`/`cumulative_fee=ZERO`
# on a GET-confirmed fill) is UNCHANGED and pinned again below.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_pass_immediate_resolves_a_get_confirmed_fill_with_no_sleep(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """RED: ``_resolve_ambiguous_intents`` must accept ``first_pass_immediate``
    and, when set, run exactly one bounded pass -- no ``asyncio.sleep`` at
    all -- resolving an already-OPEN with-id intent synchronously. Today the
    coroutine takes no such argument (``TypeError``) and always sleeps first.
    """
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
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {slug: {"netPosition": "1"}},
            "eof": True,
        }

        async def boom(_seconds: float) -> None:
            raise AssertionError("the immediate first pass must never sleep")

        monkeypatch.setattr(asyncio, "sleep", boom)

        await client._resolve_ambiguous_intents(first_pass_immediate=True)

        assert client._latch is not None
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        filled = _order_filled_events(order_events)
        assert len(filled) == 1, "one bounded pass must fully resolve the fill, synchronously"
        await client._disconnect()


@pytest.mark.asyncio
async def test_connect_awaits_the_immediate_pass_before_the_background_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED: ``_connect`` must AWAIT one ``first_pass_immediate=True`` call
    into the resolver before it returns, in addition to (not instead of)
    starting the periodic background task. Today ``_connect`` calls the
    coroutine exactly once, via ``create_task``, with no immediate pass.
    """
    enable_operator_gate(monkeypatch, order_count="2")
    calls: list[bool] = []

    async def fake_resolve(self: Any, *, first_pass_immediate: bool = False) -> None:
        calls.append(first_pass_immediate)

    monkeypatch.setattr(
        PolymarketUSExecutionClient,
        "_resolve_ambiguous_intents",
        fake_resolve,
        raising=True,
    )
    sender = _SlowSender()
    sender.response = VenueResponse(status=200, headers={}, body=b"{}")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, _order_events, _permit, _latch_cm = await _build_race_client(
            tmp_path, sender=sender,
        )

    assert calls[:1] == [True], (
        "the FIRST resolver call _connect awaits must be the immediate, "
        "bounded pass, ahead of the periodic background task"
    )
    # The background task is merely SCHEDULED by `create_task`, not run
    # synchronously -- one real yield gives it its turn.
    await asyncio.sleep(0)
    assert False in calls, "the periodic background task must still be started"
    client._resolver_task.cancel()
    await asyncio.gather(client._resolver_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_connect_immediate_pass_never_sleeps_with_nothing_to_resolve(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED (timing-unchanged AC): an ordinary boot with no OPEN intent must
    reach `_connect`'s immediate pass and return with NO `asyncio.sleep`
    call at all -- if the immediate pass slept first like the periodic
    loop does, EVERY `_connect()` in this suite would block for the full
    poll interval once awaited synchronously here.
    """
    enable_operator_gate(monkeypatch, order_count="2")

    async def boom(_seconds: float) -> None:
        raise AssertionError("_connect's own immediate pass must never sleep")

    sender = _SlowSender()
    sender.response = VenueResponse(status=200, headers={}, body=b"{}")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ), monkeypatch.context() as m:
        m.setattr(asyncio, "sleep", boom)
        client, _order_events, _permit, _latch_cm = await _build_race_client(
            tmp_path, sender=sender,
        )
    assert client._latch is not None
    assert client._latch.is_latched() is False, "no order was ever submitted; nothing to resolve"
    client._resolver_task.cancel()
    await asyncio.gather(client._resolver_task, return_exceptions=True)
    await client._disconnect()


# ---------------------------------------------------------------------------
# Review fix (2026-09-12): the immediate `first_pass_immediate=True` call
# must not be able to latch a FATAL fault -- only the periodic task's
# exceptions are meant to be merely logged (Nautilus's own
# `_on_task_completed`); an exception the pass does not catch internally
# (unlike a `CorruptError` from `current_open()`, or a mapped GET failure)
# must be caught LOCALLY in `_connect`, logged at WARNING with the
# exception TYPE only, and let `_connect` proceed.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_survives_an_unhandled_exception_in_the_immediate_resolver_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED: today the immediate call sits inside `_connect`'s own
    `except BaseException` -> `record_fatal_exec_fault` + `shutdown_system`,
    so any exception the pass does not swallow internally would fatally
    shut the node down at boot. It must instead be caught locally, letting
    `_connect` complete and the periodic task still start.
    """
    calls: list[bool] = []

    async def fake_resolve(self: Any, *, first_pass_immediate: bool = False) -> None:
        calls.append(first_pass_immediate)
        if first_pass_immediate:
            raise RuntimeError("store boom")

    monkeypatch.setattr(
        PolymarketUSExecutionClient,
        "_resolve_ambiguous_intents",
        fake_resolve,
        raising=True,
    )
    fault_calls: list[str] = []
    monkeypatch.setattr(
        "breezy.adapters.polymarket_us.exec.client.record_fatal_exec_fault",
        lambda **kwargs: fault_calls.append(kwargs.get("reason", "")),
    )
    enable_operator_gate(monkeypatch, order_count="2")
    sender = _SlowSender()
    sender.response = VenueResponse(status=200, headers={}, body=b"{}")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        # If `_connect` re-raises, this call itself raises -- the test would
        # fail with the RuntimeError propagating here, which IS the RED
        # failure shape against today's unwrapped code.
        client, _order_events, _permit, _latch_cm = await _build_race_client(
            tmp_path, sender=sender,
        )

    assert fault_calls == [], "the immediate pass's own exception must never latch a fatal fault"
    assert calls[:1] == [True], "the immediate pass must still have been attempted first"
    await asyncio.sleep(0)
    assert False in calls, "the periodic background task must still be started despite the failure"
    client._resolver_task.cancel()
    await asyncio.gather(client._resolver_task, return_exceptions=True)
    await client._disconnect()


def test_connect_immediate_pass_exception_handler_logs_type_only_never_the_value() -> None:
    """Static pin: ``self._log`` is Nautilus's own Cython logger, not stdlib
    ``logging`` -- ``caplog`` cannot observe it (see
    ``test_ambiguous_exception_path_source_logs_the_exception_type_never_its_str``
    in ``test_polymarket_us_submit_order_chain.py`` for the same,
    already-established limitation). The source text is the reliable check
    that the handler logs ``type(exc).__name__`` only, at WARNING, and never
    the exception's ``str`` or any resolver-context value.
    """
    import inspect

    source = inspect.getsource(PolymarketUSExecutionClient._connect)
    start = source.index("await self._resolve_ambiguous_intents(first_pass_immediate=True)")
    end = source.index("await self._publish_account_state()")
    block = source[start:end]
    assert "except Exception as exc" in block
    assert "self._log.warning" in block
    assert "type(exc).__name__" in block
    assert "{exc}" not in block, "must never log the exception's own str -- it may carry a value"
    assert "str(exc)" not in block


# ---------------------------------------------------------------------------
# HF-4 (post-take re-arm reachability): C2 -- a 60s age-gated startup-
# evidence refresh inside `_resolve_ambiguous_intents`, and a retire INFO
# line in the resolver (B3, Decision 3). Fixtures reused, never redefined:
# `_arm_one_ambiguous_intent`, `_run_exactly_one_pass`,
# `_run_n_passes_recording_sleeps`, `_order_get_body`.
# ---------------------------------------------------------------------------


def _retired_intent(current: Any, *, retired_ns: int) -> SubmitIntent:
    return SubmitIntent(
        intent_id=current.intent_id,
        fingerprint=current.fingerprint,
        created_ns=current.created_ns,
        state=SubmitIntentState.RETIRED,
        retired_ns=retired_ns,
        retirement_reason=RetirementReason.OPERATOR_CLEARED,
    )


@pytest.mark.asyncio
async def test_a_pass_with_no_open_intent_refreshes_stale_startup_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC-12 (B4 i, R-9a): the refresh runs on EVERY pass, including one
    with NO OPEN intent -- exactly when the strategy's re-arm gate is
    shopping for fresh evidence."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, _order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        assert client._latch is not None
        current = client._latch.current()
        assert current is not None
        client._store_set(
            CURRENT_INTENT_KEY,
            _retired_intent(current, retired_ns=client._clock.timestamp_ns()).to_bytes(),
        )
        assert client._latch.current_open() is None

        before = client.read_startup_position_evidence()
        assert before is not None
        client._last_evidence_write_ns = 0  # back-date -- force the refresh
        # A DIFFERENT slug than `_connect`'s own read -- proves the rewrite
        # reflects THIS pass's fresh GET, not a stale copy.
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {"a-different-market": {"netPosition": "3"}}, "eof": True,
        }

        await _run_exactly_one_pass(client)

        after = client.read_startup_position_evidence()
        assert after is not None
        assert after.ts_ns > before.ts_ns
        assert any(row.slug == "a-different-market" for row in after.positions)
        await client._disconnect()


@pytest.mark.asyncio
async def test_the_refresh_re_enumerates_open_orders_so_a_post_boot_rest_reaches_the_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """RESTING_BID_HUNT Rev 2 §4.3: R-9a's age-gated refresh carries the
    open-order evidence forward FRESH -- an order that rests AFTER boot is
    seen by the re-arm gate on the very next refreshed pass, and the written
    record refuses (`startup_open_orders_present`)."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, _order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        assert client._latch is not None
        current = client._latch.current()
        assert current is not None
        client._store_set(
            CURRENT_INTENT_KEY,
            _retired_intent(current, retired_ns=client._clock.timestamp_ns()).to_bytes(),
        )
        before = client.read_startup_position_evidence()
        assert before is not None
        assert before.open_orders == ()
        client._last_evidence_write_ns = 0  # back-date -- force the refresh
        client._private_read._payloads[OPEN_ORDERS_PATH] = {  # type: ignore[attr-defined]
            "orders": [
                {
                    "id": "RESTING0001A",
                    "marketSlug": "a-different-market",
                    "side": "ORDER_SIDE_BUY",
                    "type": "ORDER_TYPE_LIMIT",
                    "price": {"value": "0.01", "currency": "USD"},
                    "quantity": 1,
                    "cumQuantity": 0,
                    "leavesQuantity": 1,
                    "tif": "TIME_IN_FORCE_GOOD_TILL_CANCEL",
                    "state": "ORDER_STATE_NEW",
                    "createTime": "2026-09-16T17:00:00.000000000Z",
                }
            ]
        }

        await _run_exactly_one_pass(client)

        after = client.read_startup_position_evidence()
        assert after is not None
        assert after.ts_ns > before.ts_ns
        assert after.open_orders_read_refused is False
        assert [o.venue_order_id for o in after.open_orders] == ["RESTING0001A"]
        from breezy.strategy.current_rung_hold.trial_day_latch import (
            STARTUP_OPEN_ORDERS_PRESENT_REASON,
            startup_evidence_refusal_reason,
        )

        decoded = json.loads(after.to_bytes())
        assert startup_evidence_refusal_reason(decoded) == STARTUP_OPEN_ORDERS_PRESENT_REASON
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_fresh_evidence_record_is_not_refetched_within_the_refresh_interval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC-13: at most one positions GET per 60s from the refresh -- a
    second pass immediately after the first (well inside the 60s window
    the first pass's OWN write just re-armed) must not re-fetch."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        # Non-terminal GET: the order-GET path itself never reads positions,
        # isolating every positions-path hit to the refresh alone.
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(order_id, slug=slug, state="ORDER_STATE_NEW", cum_quantity=0)
        client._last_evidence_write_ns = 0  # back-date -- pass 1 must refresh

        original_read = client._private_read
        positions_hits = {"count": 0}

        async def _counting_read(path: str) -> Any:
            if path == PORTFOLIO_POSITIONS_PATH:
                positions_hits["count"] += 1
            return await original_read(path)

        client._private_read = _counting_read

        await _run_n_passes_recording_sleeps(client, passes=2, monkeypatch=monkeypatch)

        assert positions_hits["count"] == 1
        await client._disconnect()


@pytest.mark.asyncio
async def test_a_failed_refresh_read_leaves_the_prior_evidence_intact_and_the_resolver_alive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC-14: a failed refresh GET is caught, logged WARNING, leaves the
    prior record intact, never calls `_refuse`, never touches
    `_resolver_consecutive_failures` (that counter belongs to the
    order-GET path only), and never kills the coroutine -- a LATER pass
    with the endpoint restored still resolves.

    Deviation from the plan's own wording (verified, not assumed): `self.
    _log` is Nautilus's OWN Cython logger with READ-ONLY attributes --
    `client._log = <double>` raises `AttributeError: attribute '_log' ...
    is not writable`, and `client._log.info = <double>` raises the same
    for the Logger object itself (measured directly against the installed
    `nautilus_trader.common.component.Logger`). `caplog` cannot observe it
    either (the established limitation this file's own
    `test_connect_immediate_pass_exception_handler_logs_type_only_never_
    the_value` already documents). Both the refresh's own WARNING and the
    resolver's retire INFO (B3) are therefore pinned by SOURCE TEXT below
    -- the same reliable check that existing test already uses -- never a
    runtime double."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        prior = client.read_startup_position_evidence()
        assert prior is not None
        client._last_evidence_write_ns = 0  # back-date -- force the refresh to fire
        del client._private_read._payloads[PORTFOLIO_POSITIONS_PATH]  # type: ignore[attr-defined]
        failures_before = client._resolver_consecutive_failures
        refused: list[str] = []
        client._refuse = refused.append  # type: ignore[assignment]
        # Non-terminal GET: isolates the refresh's own exception handling
        # from the order-GET failure path (which DOES touch the counter).
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(order_id, slug=slug, state="ORDER_STATE_NEW", cum_quantity=0)

        await _run_exactly_one_pass(client)

        after = client.read_startup_position_evidence()
        assert after == prior
        assert client._resolver_consecutive_failures == failures_before
        assert refused == []

        # A later pass, with the endpoint restored, still resolves.
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {}, "eof": True,
        }
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(order_id, slug=slug, state="ORDER_STATE_CANCELED", cum_quantity=0)

        await _run_exactly_one_pass(client)

        assert client._latch is not None
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        await client._disconnect()

    import inspect

    refresh_source = inspect.getsource(PolymarketUSExecutionClient._resolve_ambiguous_intents)
    assert "self._log.warning(" in refresh_source
    assert "startup-evidence refresh" in refresh_source
    for method, reason in (
        (PolymarketUSExecutionClient._resolve_terminal_zero, "STATUS_REPORT_ZERO_FILL_TERMINAL"),
        (PolymarketUSExecutionClient._resolve_accept_fill, "STATUS_REPORT_ACCEPT_FILL_TERMINAL"),
    ):
        source = inspect.getsource(method)
        retire_call = f'self._retire(context.intent_id, "{reason}", now_ns)'
        assert retire_call in source
        assert "retired intent" in source
        tail = source[source.index(retire_call) + len(retire_call) :]
        # Immediately after `_retire(...)` -- an optional comment, then the
        # ONE `self._log.info(...)` call, within the next few lines (never
        # buried after unrelated logic further down the method).
        immediate = tail[:250]
        assert "self._log.info(" in immediate, (
            f"{method.__name__}: the retire INFO line must immediately follow _retire()"
        )


# ---------------------------------------------------------------------------
# Coordinator item D (POSITION_EXIT_EXECUTION_2026-09-16.md, security review):
# `_resolve_ambiguous_intents` must derive `closing` from the durable
# context's own `order_side`, mirroring INC-E2's `parse_fill_report(closing=)`
# wiring -- otherwise a GET-resolved EXIT order always applies the entry echo
# table, always classifies `mapping_error`, and leaves the account-wide
# `SubmitIntentLatch` OPEN forever.
# ---------------------------------------------------------------------------


def _closing_order_get_body(
    order_id: str, *, slug: str, side: str, intent: str, cum_quantity: float, avg_px: str,
) -> dict[str, Any]:
    """``_order_get_body``'s shape with the (side, intent) echo pair driven
    independently, so a closing-order GET response can be built for either
    the pinned YES or NO close echo."""
    return {
        "order": {
            "id": order_id,
            "marketSlug": slug,
            "side": side,
            "intent": intent,
            "type": "ORDER_TYPE_LIMIT",
            "price": {"value": avg_px, "currency": "USD"},
            "quantity": 1,
            "cumQuantity": cum_quantity,
            "leavesQuantity": 1 - cum_quantity,
            "tif": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
            "state": "ORDER_STATE_FILLED",
            "createTime": TS_EVENT_TEXT,
            "avgPx": {"value": avg_px, "currency": "USD"},
        }
    }


async def _arm_one_ambiguous_exit_intent(
    tmp_path: Path,
) -> tuple[PolymarketUSExecutionClient, str, str, Any, list[Any]]:
    """Like :func:`_arm_one_ambiguous_intent`, but the durable resolver
    context is overwritten to ``order_side="SELL"`` immediately after
    arming -- standing in for a real exit order's own AMBIGUOUS create (item
    A wires the exit-manifest gate that would let a real one reach here;
    this test isolates the resolver's GET-side behaviour from that gate)."""
    client, order_id, slug, latch_cm, order_events = await _arm_one_ambiguous_intent(tmp_path)
    assert client._latch is not None
    current = client._latch.current_open()
    assert current is not None
    key = f"{RESOLVER_CONTEXT_KEY_PREFIX}{current.intent_id}"
    raw = client._store_get(key)
    assert raw is not None
    context = AmbiguousResolverContext.from_bytes(raw)
    client._store_set(key, replace(context, order_side="SELL").to_bytes())
    return client, order_id, slug, latch_cm, order_events


@pytest.mark.asyncio
async def test_a_stored_exit_context_with_the_pinned_close_echo_resolves_via_the_get_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """RED (pre-fix): `parse_order_status_report` carried no `closing`
    parameter, so this GET body -- the pinned YES-close echo (SELL/
    SELL_LONG) -- always refused as a wrong-side entry echo and stayed
    `mapping_error`/AMBIGUOUS forever. GREEN: the resolver derives
    `closing=True` from the stored context's own `order_side == "SELL"`,
    the report maps, and the exit resolves through the SAME
    `_resolve_accept_fill` an entry fill does."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, order_events = await _arm_one_ambiguous_exit_intent(
            tmp_path,
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _closing_order_get_body(
            order_id,
            slug=slug,
            side="ORDER_SIDE_SELL",
            intent="ORDER_INTENT_SELL_LONG",
            cum_quantity=1,
            avg_px="0.55",
        )
        # eof-complete, a LONG still present (a closing SELL reduces it, but
        # `_resolve_accept_fill`'s own positions check only asks whether one
        # is present, never how many contracts remain).
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {slug: {"netPosition": "1"}},
            "eof": True,
        }
        instrument = build_instrument()

        await _run_resolver_passes(client, count=1)

        for kind in client._resolver_last_failure_kind.values():
            assert kind != "mapping_error", (
                "the exit GET response must map, never stay mapping_error"
            )
        assert client._resolver_consecutive_failures == 0

        assert client._latch is not None
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        assert current.retirement_reason is not None
        assert current.retirement_reason.value == "STATUS_REPORT_ACCEPT_FILL_TERMINAL"

        records = client.fill_records_for(instrument.id)
        assert len(records) == 1
        assert records[0].order_side == "SELL"
        assert records[0].cumulative_cost == Decimal("0.55")

        filled = _order_filled_events(order_events)
        assert len(filled) == 1
        assert filled[0].order_side == OrderSide.SELL
        assert filled[0].last_px.as_decimal() == Decimal("0.55")
        await client._disconnect()


@pytest.mark.asyncio
async def test_the_same_get_body_under_an_entry_context_stays_mapping_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """The disjoint-table regression guard: the IDENTICAL close-echoed GET
    body, resolved under a plain entry context (`order_side` left at its
    `LONG_ONLY_SIDE` default, exactly what a pre-existing durable blob
    decodes to), must still classify `mapping_error` -- `closing` is derived
    from the context, never from the response body."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _closing_order_get_body(
            order_id,
            slug=slug,
            side="ORDER_SIDE_SELL",
            intent="ORDER_INTENT_SELL_LONG",
            cum_quantity=1,
            avg_px="0.55",
        )
        client._private_read._payloads["/v1/portfolio/positions"] = {  # type: ignore[attr-defined]
            "positions": {slug: {"netPosition": "1"}},
            "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        assert client._resolver_consecutive_failures >= 1
        assert client._latch is not None
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN, (
            "an entry context must never resolve against a close echo"
        )
        await client._disconnect()


# ---------------------------------------------------------------------------
# FU-5 (2026-09-26 boot-overlap fix): `_connect` must not create the
# periodic resolver task until AFTER `_wait_for_instruments` and the
# immediate `first_pass_immediate=True` pass have both been awaited. Before
# the fix, the periodic task was created FIRST -- a slow boot's periodic
# first pass could then overlap the immediate pass's own in-flight
# `run_in_executor` instrument load, see the just-set
# `_resolver_instrument_load_attempted_ns` gate, skip its own load, and
# falsely log/escalate "not in the cache and could not be loaded" for an
# instrument the immediate pass was still loading successfully.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_periodic_resolver_task_is_created_only_after_the_immediate_pass_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """RED on today's ordering: ``_connect`` calls ``create_task`` for the
    periodic resolver BEFORE it awaits the immediate
    ``first_pass_immediate=True`` pass. Recorded via a faked
    ``_resolve_ambiguous_intents`` and a wrapped ``create_task`` so the
    ordering is observed directly, not inferred from timing.
    """
    enable_operator_gate(monkeypatch, order_count="2")
    events: list[str] = []

    async def fake_resolve(self: Any, *, first_pass_immediate: bool = False) -> None:
        if first_pass_immediate:
            events.append("immediate_pass_start")
            await asyncio.sleep(0)
            events.append("immediate_pass_end")
        else:
            events.append("periodic_pass_start")
            await asyncio.sleep(3600)

    monkeypatch.setattr(
        PolymarketUSExecutionClient, "_resolve_ambiguous_intents", fake_resolve, raising=True,
    )
    real_create_task = PolymarketUSExecutionClient.create_task

    def fake_create_task(self: Any, coro: Any, **kwargs: Any) -> Any:
        events.append("resolver_task_created")
        return real_create_task(self, coro, **kwargs)

    monkeypatch.setattr(
        PolymarketUSExecutionClient, "create_task", fake_create_task, raising=True,
    )
    sender = _SlowSender()
    sender.response = VenueResponse(status=200, headers={}, body=b"{}")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, _order_events, _permit, _latch_cm = await _build_race_client(
            tmp_path, sender=sender,
        )

    assert events == [
        "immediate_pass_start",
        "immediate_pass_end",
        "resolver_task_created",
    ], events
    client._resolver_task.cancel()
    await asyncio.gather(client._resolver_task, return_exceptions=True)


@pytest.mark.asyncio
async def test_periodic_resolver_task_exists_after_connect_when_the_immediate_pass_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The periodic task must still exist, and not be done, after `_connect`
    returns even when the immediate pass raises an exception `_connect`
    catches internally -- the `finally` that creates it must run on that
    path exactly as it does on the success path.
    """
    enable_operator_gate(monkeypatch, order_count="2")

    async def fake_resolve(self: Any, *, first_pass_immediate: bool = False) -> None:
        if first_pass_immediate:
            raise RuntimeError("immediate pass boom")
        await asyncio.sleep(3600)

    monkeypatch.setattr(
        PolymarketUSExecutionClient, "_resolve_ambiguous_intents", fake_resolve, raising=True,
    )
    sender = _SlowSender()
    sender.response = VenueResponse(status=200, headers={}, body=b"{}")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, _order_events, _permit, _latch_cm = await _build_race_client(
            tmp_path, sender=sender,
        )

    assert client._resolver_task is not None
    assert not client._resolver_task.done()
    client._resolver_task.cancel()
    await asyncio.gather(client._resolver_task, return_exceptions=True)


async def _build_client_with_custom_loader(
    tmp_path: Path,
    *,
    store_path: Path,
    resolver_instrument_loader: Callable[[str], Any] | None,
) -> tuple[PolymarketUSExecutionClient, Any]:
    """Like ``_build_race_client``, but stops SHORT of calling ``_connect``
    -- the caller drives it -- and accepts an injected
    ``resolver_instrument_loader``, a seam ``_build_race_client`` has none
    for. Built with an EMPTY cache/provider (no ``build_instrument()`` add):
    reproduces a process restart against a durable store that already
    carries an OPEN with-id AMBIGUOUS intent for an instrument this fresh
    process has not loaded yet -- exactly the shape the loader exists for.
    """
    loop = asyncio.get_running_loop()
    clock = LiveClock()
    msgbus = MessageBus(trader_id=TRADER_ID, clock=clock)
    cache = Cache(database=None, config=CacheConfig(database=None, flush_on_start=False))
    provider = InstrumentProvider()

    read = _PrivateReadStub(
        {
            ACCOUNT_BALANCES_PATH: _balances_payload(),
            PORTFOLIO_POSITIONS_PATH: {"positions": {}, "eof": True},
            # EDGE-2 slice D (AC4(c)): EOF-complete, no trade rows, by default.
            PORTFOLIO_ACTIVITIES_PATH: {"activities": [], "eof": True},
        },
    )

    def _on_account_state(state: AccountState) -> None:
        if cache.account(state.account_id) is None:
            cache.add_account(AccountFactory.create(state))
        else:
            cache.account(state.account_id).apply(state)

    msgbus.register(endpoint="Portfolio.update_account", handler=_on_account_state)

    live_permit = issue_live_trading_permit(clock=clock)
    latch_cm = open_submit_intent_latch(SqliteStateStore(store_path), store_path)
    submit_intent_latch = latch_cm.__enter__()
    ledger = DailySpendLedger()

    client = PolymarketUSExecutionClient(
        loop=loop,
        client_id=CLIENT_ID,
        venue=POLYMARKET_US_VENUE,
        instrument_provider=provider,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        private_read=read,
        state_store_opener=lambda: SqliteStateStore(store_path),
        account_number=ACCOUNT_NUMBER,
        instrument_wait_timeout_s=1.0,
        account_registration_timeout_s=1.0,
        order_sender=_SlowSender(),
        write_signer=_FakeSigner(),
        live_trading_permit=live_permit,
        spend_ledger=ledger,
        submit_intent_latch=submit_intent_latch,
        credentials=credentials(),
        api_base_url="https://api.polymarket.us",
        retirement_reasons=RetirementReason,
        resolver_instrument_loader=resolver_instrument_loader,
    )
    return client, latch_cm


@pytest.mark.asyncio
async def test_an_overlapping_boot_does_not_log_could_not_be_loaded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """RED on today's ordering: a slow instrument loader lets the immediate
    pass's ``run_in_executor`` load stay in flight while a (buggy-code)
    periodic first pass reaches the SAME gate, sees the just-set
    ``_resolver_instrument_load_attempted_ns`` entry, skips its own load,
    and falsely counts/escalates the "could not be loaded" failure for an
    instrument the immediate pass is actually about to load successfully.

    ``self._log`` is Nautilus's own Cython logger and cannot be observed
    directly (see this module's other static-log tests) --
    ``_resolver_consecutive_failures`` and
    ``_resolver_missing_instrument_logged`` are the same proxy the rest of
    this suite already uses for this ERROR's gating.
    """
    enable_operator_gate(monkeypatch, order_count="2")
    store_path = tmp_path / "exec_state.db"
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        # First "process": arms one with-id AMBIGUOUS intent against
        # `build_instrument()`, then "restarts" -- releasing the exclusive
        # flock (the same idiom `test_cross_restart_second_engine_never_
        # takes_a_second_trial` uses) -- leaving the OPEN intent + durable
        # resolver context on disk for the second client to inherit.
        first_client, order_id, slug, first_latch_cm, _order_events = (
            await _arm_one_ambiguous_intent(tmp_path)
        )
        await first_client._disconnect()
        first_latch_cm.__exit__(None, None, None)

        target_instrument = build_instrument()
        release = threading.Event()
        load_started = threading.Event()

        def _slow_loader(instrument_id: str) -> Any:
            load_started.set()
            release.wait(timeout=5.0)
            return target_instrument if instrument_id == str(target_instrument.id) else None

        client, latch_cm = await _build_client_with_custom_loader(
            tmp_path, store_path=store_path, resolver_instrument_loader=_slow_loader,
        )
        # A benign, non-terminal GET body for the durable intent's own venue
        # order -- isolates the counter under test to the instrument-load
        # race: an unstubbed path here would 404/KeyError and increment
        # `_resolver_consecutive_failures` for an UNRELATED reason on every
        # pass, confounding the assertion below.
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(order_id, slug=slug, state="ORDER_STATE_NEW", cum_quantity=0)
        client._resolver_poll_interval_secs = lambda: 0.0  # type: ignore[method-assign]
        try:
            connect_task = asyncio.get_event_loop().create_task(client._connect())
            # Let the immediate pass reach the slow loader and suspend there.
            for _ in range(500):
                if load_started.is_set():
                    break
                await asyncio.sleep(0)
            assert load_started.is_set(), "the immediate pass never reached the slow loader"
            # Give a (buggy-code) periodic task every opportunity to run
            # while the loader thread is still blocked.
            for _ in range(500):
                await asyncio.sleep(0)
            release.set()
            await connect_task
        finally:
            release.set()
            await client._disconnect()
            latch_cm.__exit__(None, None, None)

    assert client._resolver_consecutive_failures == 0, (
        "an overlapping periodic pass falsely counted the immediate pass's "
        "in-flight load as a failure"
    )
    assert client._resolver_missing_instrument_logged == set(), (
        "an overlapping periodic pass falsely escalated the 'could not be "
        "loaded' ERROR for an instrument the immediate pass was still loading"
    )
    assert client._cache.instrument(target_instrument.id) is not None


# ---------------------------------------------------------------------------
# FU-8 r2/r2.1: a cross-session resolver fill is never booked at runtime; a
# named informational latch (`resolver_fill_not_booked`) records it instead.
#
# Every test below drives the REAL `_resolve_accept_fill` and its REAL
# `record_fill` (L-42) directly, rather than through the full with-id
# AMBIGUOUS create-order dance (already proven end to end by this module's
# own characterisation pin, `test_a_get_confirmed_fill_with_a_long_present_
# records_a_synthesized_fill_and_retires`, which is ALSO this suite's
# mutation check for M1: forcing `_resolver_fill_order_unknown` to return
# `True` unconditionally fails that test, because its order IS in the
# client's own cache -- the same-session case). The latch (`self._latch`)
# is armed directly via `SubmitIntentLatch.arm`, which is the exact
# mechanism `_submit_order` itself uses -- so `self._latch.current_open()`
# sees a real OPEN intent, without needing a live venue POST.
#
# A real `Cache` and a real `LiveExecutionEngine` are used throughout (Test
# Strategy header, plan r2) -- registered exactly like `test_exec_client_
# reconciliation_contract.py`'s own `_build_engine`/`_build_client`, but
# defined locally here: `tests/unit` does not import from `tests/contract`
# (the dependency runs the other way across this suite).
# ---------------------------------------------------------------------------


class _Fu8Qty:
    """Duck-typed ``Quantity``/``Price`` stand-in: only ``.as_decimal()`` is
    read by `_resolve_accept_fill`."""

    def __init__(self, value: Decimal) -> None:
        self._value = value

    def as_decimal(self) -> Decimal:
        return self._value


class _Fu8FillReport:
    """Duck-typed stand-in matching every field `_resolve_accept_fill` reads
    off its ``report`` argument: ``avg_px``, ``filled_qty.as_decimal()`` and
    ``quantity.as_decimal()`` (the venue's echoed ORIGINAL order size, a
    DIFFERENT field from ``filled_qty`` -- see `record.order_qty`)."""

    def __init__(self, *, avg_px: Decimal, filled_qty: Decimal, order_qty: Decimal) -> None:
        self.avg_px = avg_px
        self.filled_qty = _Fu8Qty(filled_qty)
        self.quantity = _Fu8Qty(order_qty)


def _fu8_build_engine(
    loop: asyncio.AbstractEventLoop,
) -> tuple[LiveExecutionEngine, Cache, MessageBus, LiveClock]:
    """A real ``Cache`` and a real ``LiveExecutionEngine``, the shipped
    ``LiveExecEngineConfig`` defaults (``position_check_interval_secs=None``,
    pinned elsewhere -- see this helper's own docstring citation of test 10:
    ``test_the_settlement_landmine_stays_disarmed_only_while_the_position_
    check_is_off`` and ``test_starts_no_continuous_reconciliation_polling``).
    """
    clock = LiveClock()
    msgbus = MessageBus(trader_id=TRADER_ID, clock=clock)
    cache = Cache(database=None, config=CacheConfig(database=None, flush_on_start=False))
    cache.add_instrument(build_instrument())
    engine = LiveExecutionEngine(
        loop=loop, msgbus=msgbus, cache=cache, clock=clock, config=LiveExecEngineConfig(),
    )
    return engine, cache, msgbus, clock


def _fu8_build_client(
    loop: asyncio.AbstractEventLoop,
    tmp_path: Path,
    *,
    read: Any,
    cache: Cache,
    msgbus: MessageBus,
    clock: LiveClock,
    submit_intent_latch: Any,
) -> PolymarketUSExecutionClient:
    provider = InstrumentProvider()
    provider.add(build_instrument())
    provider.add(build_no_leg_instrument())
    return PolymarketUSExecutionClient(
        loop=loop,
        client_id=CLIENT_ID,
        venue=POLYMARKET_US_VENUE,
        instrument_provider=provider,
        msgbus=msgbus,
        cache=cache,
        clock=clock,
        private_read=read,
        state_store_opener=lambda: SqliteStateStore(tmp_path / "exec_state.db"),
        account_number=ACCOUNT_NUMBER,
        instrument_wait_timeout_s=2.0,
        account_registration_timeout_s=2.0,
        submit_intent_latch=submit_intent_latch,
        retirement_reasons=RetirementReason,
    )


async def _fu8_rig(
    tmp_path: Path,
    *,
    positions_payload: Mapping[str, Any] | None = None,
) -> tuple[PolymarketUSExecutionClient, LiveExecutionEngine, Cache, Any]:
    """One connected client + a registered real engine, with an OPEN
    submit-intent latch ready for ``arm`` -- no order ever submitted through
    ``_submit_order``, so ``self._cache.order(...)`` starts genuinely empty
    (the cross-session shape FU-8 exists for)."""
    loop = asyncio.get_running_loop()
    engine, cache, msgbus, clock = _fu8_build_engine(loop)
    cache.add_instrument(build_no_leg_instrument())

    def _on_account_state(state: AccountState) -> None:
        if cache.account(state.account_id) is None:
            cache.add_account(AccountFactory.create(state))
        else:
            cache.account(state.account_id).apply(state)

    msgbus.register(endpoint="Portfolio.update_account", handler=_on_account_state)

    read = _PrivateReadStub(
        {
            ACCOUNT_BALANCES_PATH: _balances_payload(),
            PORTFOLIO_POSITIONS_PATH: positions_payload
            if positions_payload is not None
            else {"positions": {}, "eof": True},
        },
    )
    store_path = tmp_path / "exec_state.db"
    latch_cm = open_submit_intent_latch(SqliteStateStore(store_path), store_path)
    submit_intent_latch = latch_cm.__enter__()
    client = _fu8_build_client(
        loop, tmp_path, read=read, cache=cache, msgbus=msgbus, clock=clock,
        submit_intent_latch=submit_intent_latch,
    )
    engine.register_client(client)
    await client._connect()
    return client, engine, cache, latch_cm


async def _fu8_teardown(client: PolymarketUSExecutionClient, latch_cm: Any) -> None:
    await client._disconnect()
    latch_cm.__exit__(None, None, None)


def _fu8_arm(client: PolymarketUSExecutionClient) -> Any:
    """Arm the latch directly -- the same mechanism `_submit_order` itself
    uses -- so `self._latch.current_open()` sees a real OPEN intent with no
    live venue POST."""
    now_ns = client._clock.timestamp_ns()
    intent = client._latch.arm("a" * 64, now_ns=now_ns)
    client._resolved_by_get_ts_ns[intent.intent_id] = now_ns
    return intent


@pytest.mark.asyncio
async def test_fu8_t1_before_the_boot_snapshot_defers_and_the_boot_pass_books_it_natively(
    tmp_path: Path,
) -> None:
    """AC2/AC4, plain T1: `_boot_snapshot_started` is False, so the fill is
    NOT booked here -- no latch, `generate_order_filled` never runs. The
    durable `record_fill` write (L-42) already happened, so the LATER boot
    pass (`engine.reconcile_execution_state`) books it natively, under the
    real client order id, with the real quantity -- AC2's "booked" outcome."""
    client, engine, cache, latch_cm = await _fu8_rig(tmp_path)
    try:
        assert client._boot_snapshot_started is False
        instrument = build_instrument()
        intent = _fu8_arm(client)
        now_ns = client._clock.timestamp_ns()
        context = AmbiguousResolverContext(
            intent_id=intent.intent_id,
            venue_order_id="V-FU8-T1-1",
            instrument_id=instrument.id.value,
            client_order_id="O-FU8-T1-1",
            strategy_id=STRATEGY_ID.value,
            notional_usd=Decimal("0.40"),
            booking_id=1,
            created_ns=now_ns,
        )
        report = _Fu8FillReport(
            avg_px=Decimal("0.40"), filled_qty=Decimal(1), order_qty=Decimal(1),
        )
        filled_calls: list[Any] = []
        client.generate_order_filled = lambda **kw: filled_calls.append(kw)  # type: ignore[method-assign]

        client._resolve_accept_fill(context, report, instrument, now_ns)

        assert filled_calls == [], "T1: generate_order_filled must never run"
        assert client.reconciliation_refusals == (), "T1: nothing is latched"
        assert len(client.fill_records_for(instrument.id)) == 1, "record_fill still ran"
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED

        # The client-order-id map row was ALSO written (A1-b) -- required for
        # the boot pass below to attribute the durable record correctly.
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {
                instrument_id_to_slug(instrument.id): {
                    **build_position(instrument_id_to_slug(instrument.id)),
                    "netPosition": "1",
                    "qtyBought": "1",
                    "qtySold": "0",
                    "cost": {"value": "0.40", "currency": "USD"},
                },
            },
            "eof": True,
        }

        assert await engine.reconcile_execution_state(timeout_secs=5.0) is True

        assert cache.order(ClientOrderId("O-FU8-T1-1")) is not None, (
            "the later boot pass must book the fill natively, with attribution"
        )
        positions = cache.positions_open(instrument_id=instrument.id)
        assert len(positions) == 1
        assert positions[0].quantity == instrument.make_qty(1)
    finally:
        await _fu8_teardown(client, latch_cm)


@pytest.mark.asyncio
async def test_fu8_t1_on_a_settled_market_books_nothing_and_latches_nothing(
    tmp_path: Path,
) -> None:
    """r2.1 AC2 addendum: a T1 deferral whose boot pass finds the market
    SETTLED (`expired`, gated out -- `_map_position`) attributes nothing,
    because there is nothing held to attribute -- accepted in writing (r2.1
    item 2). No latch either: a settled market is not a disagreement."""
    client, engine, cache, latch_cm = await _fu8_rig(tmp_path)
    try:
        instrument = build_instrument()
        intent = _fu8_arm(client)
        now_ns = client._clock.timestamp_ns()
        context = AmbiguousResolverContext(
            intent_id=intent.intent_id,
            venue_order_id="V-FU8-T1-SETTLED-1",
            instrument_id=instrument.id.value,
            client_order_id="O-FU8-T1-SETTLED-1",
            strategy_id=STRATEGY_ID.value,
            notional_usd=Decimal("0.40"),
            booking_id=1,
            created_ns=now_ns,
        )
        report = _Fu8FillReport(
            avg_px=Decimal("0.40"), filled_qty=Decimal(1), order_qty=Decimal(1),
        )
        client._resolve_accept_fill(context, report, instrument, now_ns)
        assert client.reconciliation_refusals == ()

        slug = instrument_id_to_slug(instrument.id)
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {slug: {**build_position(slug), "expired": True}},
            "eof": True,
        }

        assert await engine.reconcile_execution_state(timeout_secs=5.0) is True

        assert cache.order(ClientOrderId("O-FU8-T1-SETTLED-1")) is None, "nothing to attribute"
        assert cache.positions_open(instrument_id=instrument.id) == []
        assert client.reconciliation_refusals == (), "a settled market is not a disagreement"
    finally:
        await _fu8_teardown(client, latch_cm)


@pytest.mark.asyncio
async def test_fu8_t1_with_a_venue_disagreement_latches_record_venue_disagreement(
    tmp_path: Path,
) -> None:
    """r2.1 AC2 addendum: a T1 deferral whose boot pass finds the venue
    reporting a DIFFERENT quantity than the durable record latches
    `record_venue_disagreement` -- a pre-existing boot outcome, unrelated to
    FU-8's own latch, but one T1 can now land on."""
    client, engine, cache, latch_cm = await _fu8_rig(tmp_path)
    try:
        instrument = build_instrument()
        intent = _fu8_arm(client)
        now_ns = client._clock.timestamp_ns()
        context = AmbiguousResolverContext(
            intent_id=intent.intent_id,
            venue_order_id="V-FU8-T1-DISAGREE-1",
            instrument_id=instrument.id.value,
            client_order_id="O-FU8-T1-DISAGREE-1",
            strategy_id=STRATEGY_ID.value,
            notional_usd=Decimal("0.40"),
            booking_id=1,
            created_ns=now_ns,
        )
        report = _Fu8FillReport(
            avg_px=Decimal("0.40"), filled_qty=Decimal(1), order_qty=Decimal(1),
        )
        client._resolve_accept_fill(context, report, instrument, now_ns)

        # The record says qty=1; the venue disagrees and reports 5.
        slug = instrument_id_to_slug(instrument.id)
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {
                slug: {
                    **build_position(slug),
                    "netPosition": "5",
                    "qtyBought": "5",
                    "qtySold": "0",
                },
            },
            "eof": True,
        }

        assert await engine.reconcile_execution_state(timeout_secs=5.0) is True

        assert cache.order(ClientOrderId("O-FU8-T1-DISAGREE-1")) is None
        assert any(
            r["latch"] == "record_venue_disagreement" for r in client.reconciliation_refusals
        ), client.reconciliation_refusals
    finally:
        await _fu8_teardown(client, latch_cm)


@pytest.mark.asyncio
async def test_fu8_t2_venue_held_never_doubles_the_position_and_latches_resolver_fill_not_booked(
    tmp_path: Path,
) -> None:
    """AC3/AC4, architect 6a: the boot pass ALREADY ran (no durable record
    yet, so it latches `record_venue_disagreement` and forwards the position
    -- Nautilus synthesizes a RECONCILIATION order for the venue's own qty).
    A LATER resolver fill for the SAME qty must not double it, must book no
    order for its own client order id, and must latch
    `resolver_fill_not_booked`."""
    instrument = build_instrument()
    slug = instrument_id_to_slug(instrument.id)
    client, engine, cache, latch_cm = await _fu8_rig(
        tmp_path,
        positions_payload={
            "positions": {
                slug: {
                    **build_position(slug),
                    "netPosition": "4",
                    "qtyBought": "4",
                    "qtySold": "0",
                },
            },
            "eof": True,
        },
    )
    try:
        assert await engine.reconcile_execution_state(timeout_secs=5.0) is True
        assert client._boot_snapshot_started is True
        positions_before = cache.positions_open(instrument_id=instrument.id)
        assert len(positions_before) == 1
        assert positions_before[0].quantity == instrument.make_qty(4)

        intent = _fu8_arm(client)
        now_ns = client._clock.timestamp_ns()
        context = AmbiguousResolverContext(
            intent_id=intent.intent_id,
            venue_order_id="V-FU8-T2-1",
            instrument_id=instrument.id.value,
            client_order_id="O-FU8-T2-1",
            strategy_id=STRATEGY_ID.value,
            notional_usd=Decimal("1.48"),
            booking_id=1,
            created_ns=now_ns,
        )
        report = _Fu8FillReport(
            avg_px=Decimal("0.37"), filled_qty=Decimal(4), order_qty=Decimal(4),
        )
        filled_calls: list[Any] = []
        client.generate_order_filled = lambda **kw: filled_calls.append(kw)  # type: ignore[method-assign]

        client._resolve_accept_fill(context, report, instrument, now_ns)

        assert filled_calls == [], "T2: generate_order_filled must never run"
        assert cache.order(ClientOrderId("O-FU8-T2-1")) is None
        positions_after = cache.positions_open(instrument_id=instrument.id)
        assert len(positions_after) == 1
        assert positions_after[0].quantity == instrument.make_qty(4), "must not double"
        assert len(client.fill_records_for(instrument.id)) == 1, "record_fill still ran"
        assert any(
            r["latch"] == RESOLVER_FILL_NOT_BOOKED for r in client.reconciliation_refusals
        ), client.reconciliation_refusals
    finally:
        await _fu8_teardown(client, latch_cm)


@pytest.mark.asyncio
async def test_fu8_t2_venue_expired_books_nothing_and_latches_resolver_fill_not_booked(
    tmp_path: Path,
) -> None:
    """AC3/AC4, architect 6b (expired): the boot pass gates the position out
    entirely (settled, `_map_position`'s `expired` branch) -- Nautilus holds
    NOTHING. A later resolver fill must still book nothing (never a phantom
    long on a settled market, L-18) and must latch."""
    instrument = build_instrument()
    slug = instrument_id_to_slug(instrument.id)
    client, engine, cache, latch_cm = await _fu8_rig(
        tmp_path,
        positions_payload={
            "positions": {slug: {**build_position(slug), "expired": True}},
            "eof": True,
        },
    )
    try:
        assert await engine.reconcile_execution_state(timeout_secs=5.0) is True
        assert client._boot_snapshot_started is True
        assert cache.positions_open(instrument_id=instrument.id) == []

        intent = _fu8_arm(client)
        now_ns = client._clock.timestamp_ns()
        context = AmbiguousResolverContext(
            intent_id=intent.intent_id,
            venue_order_id="V-FU8-T2-EXPIRED-1",
            instrument_id=instrument.id.value,
            client_order_id="O-FU8-T2-EXPIRED-1",
            strategy_id=STRATEGY_ID.value,
            notional_usd=Decimal("1.48"),
            booking_id=1,
            created_ns=now_ns,
        )
        report = _Fu8FillReport(
            avg_px=Decimal("0.37"), filled_qty=Decimal(4), order_qty=Decimal(4),
        )
        client._resolve_accept_fill(context, report, instrument, now_ns)

        assert cache.positions_open(instrument_id=instrument.id) == [], "no phantom long"
        assert cache.order(ClientOrderId("O-FU8-T2-EXPIRED-1")) is None
        assert any(
            r["latch"] == RESOLVER_FILL_NOT_BOOKED for r in client.reconciliation_refusals
        ), client.reconciliation_refusals
    finally:
        await _fu8_teardown(client, latch_cm)


@pytest.mark.asyncio
async def test_fu8_t2_venue_flat_books_nothing_and_latches_resolver_fill_not_booked(
    tmp_path: Path,
) -> None:
    """AC3/AC4, architect 6b (FLAT): same as the expired case, but the venue
    reports a genuine FLAT (`netPosition=0`, gated out) rather than expired."""
    instrument = build_instrument()
    slug = instrument_id_to_slug(instrument.id)
    client, engine, cache, latch_cm = await _fu8_rig(
        tmp_path,
        positions_payload={
            "positions": {
                slug: {
                    **build_position(slug),
                    "netPosition": "0",
                    "qtyBought": "4",
                    "qtySold": "4",
                },
            },
            "eof": True,
        },
    )
    try:
        assert await engine.reconcile_execution_state(timeout_secs=5.0) is True
        assert cache.positions_open(instrument_id=instrument.id) == []

        intent = _fu8_arm(client)
        now_ns = client._clock.timestamp_ns()
        context = AmbiguousResolverContext(
            intent_id=intent.intent_id,
            venue_order_id="V-FU8-T2-FLAT-1",
            instrument_id=instrument.id.value,
            client_order_id="O-FU8-T2-FLAT-1",
            strategy_id=STRATEGY_ID.value,
            notional_usd=Decimal("1.48"),
            booking_id=1,
            created_ns=now_ns,
        )
        report = _Fu8FillReport(
            avg_px=Decimal("0.37"), filled_qty=Decimal(4), order_qty=Decimal(4),
        )
        client._resolve_accept_fill(context, report, instrument, now_ns)

        assert cache.positions_open(instrument_id=instrument.id) == []
        assert cache.order(ClientOrderId("O-FU8-T2-FLAT-1")) is None
        assert any(
            r["latch"] == RESOLVER_FILL_NOT_BOOKED for r in client.reconciliation_refusals
        ), client.reconciliation_refusals
    finally:
        await _fu8_teardown(client, latch_cm)


@pytest.mark.asyncio
async def test_fu8_no_leg_fill_never_touches_the_yes_sibling(tmp_path: Path) -> None:
    """Architect 6c: the subject and log use the leg-resolved
    `context.instrument_id` (a `^no` composite id) -- the YES sibling stays
    untouched throughout."""
    yes_instrument = build_instrument()
    no_instrument = build_no_leg_instrument()
    client, _engine, cache, latch_cm = await _fu8_rig(tmp_path)
    try:
        # T2: the NO-leg shape itself is under test, not the boot dance.
        client._boot_snapshot_started = True
        intent = _fu8_arm(client)
        now_ns = client._clock.timestamp_ns()
        context = AmbiguousResolverContext(
            intent_id=intent.intent_id,
            venue_order_id="V-FU8-NO-1",
            instrument_id=no_instrument.id.value,
            client_order_id="O-FU8-NO-1",
            strategy_id=STRATEGY_ID.value,
            notional_usd=Decimal("0.40"),
            booking_id=1,
            created_ns=now_ns,
        )
        report = _Fu8FillReport(
            avg_px=Decimal("0.40"), filled_qty=Decimal(1), order_qty=Decimal(1),
        )
        filled_calls: list[Any] = []
        client.generate_order_filled = lambda **kw: filled_calls.append(kw)  # type: ignore[method-assign]

        client._resolve_accept_fill(context, report, no_instrument, now_ns)

        assert filled_calls == []
        assert cache.order(ClientOrderId("O-FU8-NO-1")) is None
        assert cache.positions_open(instrument_id=no_instrument.id) == []
        assert cache.positions_open(instrument_id=yes_instrument.id) == [], "YES sibling untouched"
        assert any(
            r["latch"] == RESOLVER_FILL_NOT_BOOKED for r in client.reconciliation_refusals
        ), client.reconciliation_refusals
    finally:
        await _fu8_teardown(client, latch_cm)


@pytest.mark.asyncio
async def test_fu8_security_cache_miss_sends_no_report_and_still_retires(
    tmp_path: Path,
) -> None:
    """Security (c), strengthened: on the cache-miss path, spies on
    `_send_mass_status_report`, `_send_order_status_report` and
    `generate_order_filled` record ZERO calls, and the intent still retires."""
    instrument = build_instrument()
    client, _engine, _cache, latch_cm = await _fu8_rig(tmp_path)
    try:
        client._boot_snapshot_started = True
        mass_status_calls: list[Any] = []
        order_status_calls: list[Any] = []
        filled_calls: list[Any] = []
        client._send_mass_status_report = lambda *a, **kw: mass_status_calls.append(  # type: ignore[method-assign]
            (a, kw),
        )
        client._send_order_status_report = lambda *a, **kw: order_status_calls.append(  # type: ignore[method-assign]
            (a, kw),
        )
        client.generate_order_filled = lambda **kw: filled_calls.append(kw)  # type: ignore[method-assign]

        intent = _fu8_arm(client)
        now_ns = client._clock.timestamp_ns()
        context = AmbiguousResolverContext(
            intent_id=intent.intent_id,
            venue_order_id="V-FU8-SEC-1",
            instrument_id=instrument.id.value,
            client_order_id="O-FU8-SEC-1",
            strategy_id=STRATEGY_ID.value,
            notional_usd=Decimal("0.40"),
            booking_id=1,
            created_ns=now_ns,
        )
        report = _Fu8FillReport(
            avg_px=Decimal("0.40"), filled_qty=Decimal(1), order_qty=Decimal(1),
        )

        client._resolve_accept_fill(context, report, instrument, now_ns)

        assert mass_status_calls == []
        assert order_status_calls == []
        assert filled_calls == []
        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED, "the intent must still retire"
    finally:
        await _fu8_teardown(client, latch_cm)


@pytest.mark.asyncio
async def test_fu8_a_resolve_race_at_the_boot_snapshot_latches_even_though_it_would_explain_it(
    tmp_path: Path,
) -> None:
    """Plan r2 edge case "Race during the mass status": `_boot_snapshot_
    started` is set as the FIRST statement of `generate_mass_status`, before
    its first await. A resolve landing while THIS SAME pass is still in
    flight (and would, moments later, have explained the position) still
    latches -- a false ALERT, never silence."""
    instrument = build_instrument()
    slug = instrument_id_to_slug(instrument.id)
    client, engine, _cache, latch_cm = await _fu8_rig(
        tmp_path,
        positions_payload={
            "positions": {
                slug: {
                    **build_position(slug),
                    "netPosition": "4",
                    "qtyBought": "4",
                    "qtySold": "0",
                },
            },
            "eof": True,
        },
    )
    try:
        assert client._boot_snapshot_started is False
        entered = asyncio.Event()
        release = asyncio.Event()
        original_position_reports = client.generate_position_status_reports

        async def _slow_positions(lookback_mins: int | None = None) -> Any:
            entered.set()
            await release.wait()
            return await original_position_reports(lookback_mins)

        client.generate_position_status_reports = _slow_positions  # type: ignore[method-assign]

        boot_task = asyncio.ensure_future(engine.reconcile_execution_state(timeout_secs=5.0))
        await asyncio.wait_for(entered.wait(), timeout=2.0)
        assert client._boot_snapshot_started is True, "set before the first await"

        intent = _fu8_arm(client)
        now_ns = client._clock.timestamp_ns()
        context = AmbiguousResolverContext(
            intent_id=intent.intent_id,
            venue_order_id="V-FU8-RACE-1",
            instrument_id=instrument.id.value,
            client_order_id="O-FU8-RACE-1",
            strategy_id=STRATEGY_ID.value,
            notional_usd=Decimal("1.48"),
            booking_id=1,
            created_ns=now_ns,
        )
        report = _Fu8FillReport(
            avg_px=Decimal("0.37"), filled_qty=Decimal(4), order_qty=Decimal(4),
        )
        client._resolve_accept_fill(context, report, instrument, now_ns)

        assert any(
            r["latch"] == RESOLVER_FILL_NOT_BOOKED for r in client.reconciliation_refusals
        ), "a false alert, never silence, even though this in-flight pass would have explained it"

        release.set()
        assert await boot_task is True
    finally:
        await _fu8_teardown(client, latch_cm)


def test_fu8_boot_pass_refusal_latches_all_have_a_counts_field_and_the_new_latch_has_none() -> None:
    """r2.1 item 4 / M3 mutation guard: every `_BOOT_PASS_REFUSAL_LATCHES`
    entry has a `refusals_<latch>` field in `_RECONCILIATION_COUNT_FIELDS`
    (AC6's load-bearing invariant -- dropping this tuple and summing over
    ALL details instead would KeyError the moment `resolver_fill_not_booked`
    existed), and the new latch itself has none -- it is not a boot-pass
    outcome, so the counts line stays byte-identical (test 9)."""
    for latch in _BOOT_PASS_REFUSAL_LATCHES:
        assert f"refusals_{latch}" in _RECONCILIATION_COUNT_FIELDS, latch
    assert f"refusals_{RESOLVER_FILL_NOT_BOOKED}" not in _RECONCILIATION_COUNT_FIELDS
    assert RESOLVER_FILL_NOT_BOOKED not in _BOOT_PASS_REFUSAL_LATCHES


# ---------------------------------------------------------------------------
# EDGE-2C: the NO-leg resolver crash (`instrument_id_to_slug` raised outside
# any `try` at the old `client.py:2419-2420`). Tests 1/2/8/9 drive the REAL
# `_resolve_ambiguous_intents` pass; tests 3-7 exercise the pure
# `_resolver_long_position_state` helper directly.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_leg_terminal_get_does_not_raise_on_reserved_separator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC1/AC3: a with-id AMBIGUOUS intent on the NO leg must not crash the
    resolver coroutine. RED today: `instrument_id_to_slug` raises
    `VenuePayloadError` on the NO leg's composite id (the reserved `^`
    separator), unwrapped -- the intent never retires."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, venue_order_id, slug, _latch_cm = await _arm_one_no_leg_ambiguous_intent(tmp_path)
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{venue_order_id}"
        ] = _no_leg_order_get_body(
            venue_order_id, slug=slug, state="ORDER_STATE_EXPIRED", cum_quantity=0,
        )
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {},
            "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        assert current.retirement_reason is not None
        assert current.retirement_reason.value == "STATUS_REPORT_ZERO_FILL_TERMINAL"
        await client._disconnect()


@pytest.mark.asyncio
async def test_no_leg_terminal_fill_with_short_yes_net_resolves_accept_fill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC2/AC4: a NO-leg terminal fill, corroborated by a NEGATIVE
    `netPosition` on the base slug (a short YES == a NO holding, per the
    2026-09-16 ruling), resolves through `_resolve_accept_fill` -- no
    deadlock. RED today: the unwrapped raise kills the pass before the fill
    is ever considered, so the intent never retires."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, venue_order_id, slug, _latch_cm = await _arm_one_no_leg_ambiguous_intent(tmp_path)
        no_instrument = build_no_leg_instrument()
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

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        assert current.retirement_reason is not None
        assert current.retirement_reason.value == "STATUS_REPORT_ACCEPT_FILL_TERMINAL"
        records = client.fill_records_for(no_instrument.id)
        assert len(records) == 1
        # Risk register (plan §9): the synthesized cumulative_cost is
        # cum x avgPx, in the ALREADY-leg-translated (instrument) price
        # space -- wire avgPx 0.40 (YES-denominated) is 1 - 0.40 = 0.60 on
        # the NO instrument (Rev 5 E5-1), so cost = 1 x 0.60 = 0.60.
        assert records[0].cumulative_cost == Decimal("0.60")
        await client._disconnect()


def test_no_leg_positive_net_on_base_slug_is_not_a_no_holding() -> None:
    """AC2 regression: a POSITIVE `netPosition` on the base slug is a YES
    holding, never a NO holding -- `held` is `False` for the NO leg, so a
    NO-leg terminal fill against it must disagree (stay AMBIGUOUS), never
    resolve as accepted. RED today: the 2-arg signature refuses the `leg`
    the fix adds."""
    slug = instrument_id_to_slug(build_instrument().id)
    positions = {slug: {**build_position(slug), "netPosition": "4"}}
    assert _resolver_long_position_state(positions, slug, "no") is False


def test_no_leg_outcome_no_with_negative_net_is_a_no_holding() -> None:
    """AC2: `marketMetadata.outcome="No"` with a negative `netPosition` is a
    NO holding -- `held` is `True` for the NO leg."""
    slug = instrument_id_to_slug(build_instrument().id)
    positions = {
        slug: {
            **build_position(slug),
            "netPosition": "-4",
            "marketMetadata": {"slug": slug, "outcome": "No"},
        },
    }
    assert _resolver_long_position_state(positions, slug, "no") is True


def test_holding_outcome_sign_contradiction_is_undetermined_for_both_legs() -> None:
    """AC2/`position_leg`'s own ruling: an `outcome`/sign contradiction is
    refused rather than guessed -- `held` is `None` (undetermined, stays
    AMBIGUOUS) for either leg, never a guess in either direction."""
    slug = instrument_id_to_slug(build_instrument().id)
    yes_contradiction = {
        slug: {
            **build_position(slug),
            "netPosition": "-4",
            "marketMetadata": {"slug": slug, "outcome": "Yes"},
        },
    }
    no_contradiction = {
        slug: {
            **build_position(slug),
            "netPosition": "4",
            "marketMetadata": {"slug": slug, "outcome": "No"},
        },
    }
    assert _resolver_long_position_state(yes_contradiction, slug, "yes") is None
    assert _resolver_long_position_state(no_contradiction, slug, "no") is None


def test_yes_leg_holding_semantics_unchanged() -> None:
    """AC4 regression matrix: the YES leg's `held` reading is byte-identical
    to before this plan -- absent -> False, net>0 -> True, net==0 -> False,
    net<0 -> False."""
    slug = instrument_id_to_slug(build_instrument().id)
    assert _resolver_long_position_state({}, slug, "yes") is False
    assert (
        _resolver_long_position_state(
            {slug: {**build_position(slug), "netPosition": "4"}}, slug, "yes",
        )
        is True
    )
    assert (
        _resolver_long_position_state(
            {slug: {**build_position(slug), "netPosition": "0"}}, slug, "yes",
        )
        is False
    )
    assert (
        _resolver_long_position_state(
            {slug: {**build_position(slug), "netPosition": "-4"}}, slug, "yes",
        )
        is False
    )


def test_malformed_net_position_stays_ambiguous_for_both_legs() -> None:
    """Unchanged: a `netPosition` that does not parse as a finite decimal is
    undetermined (`None`) for either leg, never guessed."""
    slug = instrument_id_to_slug(build_instrument().id)
    positions = {slug: {**build_position(slug), "netPosition": "not-a-number"}}
    assert _resolver_long_position_state(positions, slug, "yes") is None
    assert _resolver_long_position_state(positions, slug, "no") is None


@pytest.mark.asyncio
async def test_slug_derivation_failure_is_logged_counted_and_resolver_keeps_polling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC3: ANY exception deriving the slug/leg/holding -- not only the
    NO-leg reserved-separator shape AC1 fixes -- is caught, counted via
    `_note_resolver_error`, and never kills the task. A genuinely
    foreign-venue instrument (`base_slug_of`'s own venue check) is used here
    because it is a raise this plan does NOT make disappear -- exactly what
    AC3's per-intent guard exists for."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        foreign_instrument = _foreign_venue_instrument()
        client._cache.add_instrument(foreign_instrument)
        current_open = client._latch.current_open()
        assert current_open is not None
        _rewrite_resolver_context_instrument(
            client, current_open.intent_id, str(foreign_instrument.id),
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(order_id, slug=slug, state="ORDER_STATE_CANCELED", cum_quantity=0)
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {},
            "eof": True,
        }

        # Exactly ONE pass (`first_pass_immediate=True` runs the body once and
        # returns -- `client.py`'s own docstring): unlike the terminal-
        # resolving tests above, this intent never retires, so driving it
        # through `_run_resolver_passes`'s many zero-interval spins would
        # re-fail on every single pass and inflate the counter past 1.
        await client._resolve_ambiguous_intents(first_pass_immediate=True)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN, (
            "an undetermined slug derivation must stay AMBIGUOUS, never retire"
        )
        assert client._resolver_error_count == 1
        await client._disconnect()


@pytest.mark.asyncio
async def test_periodic_resolver_task_survives_a_no_leg_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC3, direct: the REAL periodic task (`_resolve_ambiguous_intents`, no
    `first_pass_immediate`) is still `done() is False` after a NO-leg pass
    whose GET is terminal-zero. RED today: the unwrapped raise ends the
    task, so it is `done()` (with an exception) after exactly one pass."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, venue_order_id, slug, _latch_cm = await _arm_one_no_leg_ambiguous_intent(tmp_path)
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{venue_order_id}"
        ] = _no_leg_order_get_body(
            venue_order_id, slug=slug, state="ORDER_STATE_EXPIRED", cum_quantity=0,
        )
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {},
            "eof": True,
        }
        client._resolver_poll_interval_secs = lambda: 0.0  # type: ignore[method-assign]

        task = asyncio.get_event_loop().create_task(client._resolve_ambiguous_intents())
        try:
            for _ in range(55):
                await asyncio.sleep(0)
            assert task.done() is False, "the periodic task must survive a NO-leg pass"
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await client._disconnect()


# ---------------------------------------------------------------------------
# EDGE-2 slice D (AC4/AC7/AC10): the resolver's zero-fill evidence gate.
#
# Authority: docs/plans/backlog/EDGE_2026-09-27/
# EDGE-2_ambiguous_executions_resolver_plan_r3_2026-09-27.md, section 7.
# Binding coordinator amendment (2026-09-27, Step 0 evidence and its
# review): AC4(c) completeness is EOF-ONLY -- the
# ``min(createTime) < createdNs`` branch is UNLICENSED until a real
# multi-page traversal is observed (follow-up EDGE-2-MULTIPAGE).
# ---------------------------------------------------------------------------


def test_min_age_constant_equals_strategy_rearm_floor() -> None:
    """AC4(d): the borrowed, UNVERIFIED 120s floor is pinned EQUAL to the
    strategy's own re-arm floor. This test imports both; production code
    never imports `strategy` from `adapters` (the layer contract)."""
    from breezy.strategy.current_rung_hold.continuous_strategy import (
        _REARM_MIN_DELAY_SECS,
    )

    assert _RESOLVER_ZERO_FILL_MIN_AGE_NS == _REARM_MIN_DELAY_SECS * 1_000_000_000


@pytest.mark.asyncio
async def test_zero_fill_before_min_age_stays_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC4(d): otherwise-clean zero-fill evidence (terminal GET, complete
    activities with no trade, no create-time fill evidence) is NOT enough on
    its own -- a context younger than `_RESOLVER_ZERO_FILL_MIN_AGE_NS` stays
    AMBIGUOUS."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        current = client._latch.current_open()
        assert current is not None
        _backdate_resolver_context(client, current.intent_id, age_ns=0)  # freshly armed
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_EXPIRED", cum_quantity=0, leaves_quantity=0,
        )
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {}, "eof": True,
        }
        # Default activities payload (`_build_race_client`) is already
        # eof-complete with zero trade rows.

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN, (
            "a context younger than the min-age floor must never retire"
        )
        await client._disconnect()


@pytest.mark.asyncio
async def test_order_trade_activity_requests_page_two_with_next_cursor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC4(c)/AC10, direct: page 1's `nextCursor` is forwarded VERBATIM as
    page 2's `cursor`, with `sortOrder`/`limit` unchanged -- proven directly
    against `_order_trade_activity`, not the full resolver dispatch. Page 2
    is `eof`, so the join is complete."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        pages = [
            {"activities": [], "eof": False, "nextCursor": "c1"},
            {"activities": [], "eof": True},
        ]
        queries: list[Mapping[str, object] | None] = []

        async def _paged_read(path: str, query: Mapping[str, object] | None = None) -> Any:
            assert path == PORTFOLIO_ACTIVITIES_PATH
            queries.append(query)
            return pages[len(queries) - 1]

        client._private_read = _paged_read

        join = await client._order_trade_activity(order_id, client._clock.timestamp_ns())

        assert join is not None
        assert join.complete is True
        assert len(queries) == 2
        assert queries[0] == {
            "limit": _RESOLVER_ACTIVITY_PAGE_LIMIT, "sortOrder": _RESOLVER_ACTIVITY_SORT_ORDER,
        }
        assert queries[1] == {
            "limit": _RESOLVER_ACTIVITY_PAGE_LIMIT, "sortOrder": _RESOLVER_ACTIVITY_SORT_ORDER,
            "cursor": "c1",
        }
        await client._disconnect()


@pytest.mark.asyncio
async def test_order_trade_activity_missing_cursor_without_eof_is_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC4(c), direct: `eof=false` with NO `nextCursor` means the read
    stops -- never loops, never guesses a next page -- and the join is
    INCOMPLETE, never complete."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        queries: list[Mapping[str, object] | None] = []

        async def _no_cursor_read(path: str, query: Mapping[str, object] | None = None) -> Any:
            assert path == PORTFOLIO_ACTIVITIES_PATH
            queries.append(query)
            return {"activities": [], "eof": False}

        client._private_read = _no_cursor_read

        join = await client._order_trade_activity(order_id, client._clock.timestamp_ns())

        assert join is not None
        assert join.complete is False
        assert len(queries) == 1, "a missing cursor must stop the read after ONE page"
        await client._disconnect()


@pytest.mark.asyncio
async def test_order_trade_activity_cap_hit_is_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC4(c), direct: 20 pages, each carrying a fresh `nextCursor`, NEVER
    `eof` -- the read stops at `_RESOLVER_ACTIVITY_MAX_PAGES` and the join
    is INCOMPLETE. Also proves cursor forwarding holds across the WHOLE run
    (not just page 1 -> page 2): query N+1 always carries page N's own
    `nextCursor`."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        queries: list[Mapping[str, object] | None] = []

        async def _never_eof_read(path: str, query: Mapping[str, object] | None = None) -> Any:
            assert path == PORTFOLIO_ACTIVITIES_PATH
            queries.append(query)
            return {"activities": [], "eof": False, "nextCursor": f"c{len(queries)}"}

        client._private_read = _never_eof_read

        join = await client._order_trade_activity(order_id, client._clock.timestamp_ns())

        assert join is not None
        assert join.complete is False
        assert len(queries) == _RESOLVER_ACTIVITY_MAX_PAGES
        for index in range(1, len(queries)):
            assert queries[index]["cursor"] == f"c{index}", (
                f"query {index} must carry page {index - 1}'s own nextCursor"
            )
        await client._disconnect()


@pytest.mark.asyncio
async def test_terminal_zero_requires_complete_activities_with_no_trade_for_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC4(c): an INCOMPLETE activities read (no `eof`, no `nextCursor` --
    the read simply stops) never authorizes a zero-fill, even with every
    other AC4 condition satisfied."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_EXPIRED", cum_quantity=0, leaves_quantity=0,
        )
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {}, "eof": True,
        }
        client._private_read._payloads[PORTFOLIO_ACTIVITIES_PATH] = {  # type: ignore[attr-defined]
            "activities": [], "eof": False,
        }

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN
        await client._disconnect()


@pytest.mark.asyncio
async def test_trade_activity_for_order_id_blocks_zero_fill_and_raises_contradiction_critical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC4: a GET-terminal-zero order whose activities join finds a real
    TRADE row for THIS venue order id is a CONTRADICTION, not a zero-fill --
    stays AMBIGUOUS and raises the `resolver_evidence_contradiction`
    CRITICAL health-surface entry."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_EXPIRED", cum_quantity=0, leaves_quantity=0,
        )
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {}, "eof": True,
        }
        client._private_read._payloads[PORTFOLIO_ACTIVITIES_PATH] = {  # type: ignore[attr-defined]
            "activities": [
                {
                    "type": "ACTIVITY_TYPE_TRADE",
                    "trade": {
                        "aggressor": {"id": order_id},
                        "marketSlug": slug,
                        "qtyDecimal": "1",
                        "createTime": "2026-09-23T17:22:07.900000000Z",
                    },
                },
            ],
            "eof": True,
        }
        assert client.resolver_evidence_contradictions == ()

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN, "a contradiction never retires"
        contradictions = client.resolver_evidence_contradictions
        assert len(contradictions) == 1
        assert contradictions[0]["severity"] == "CRITICAL"
        assert contradictions[0]["event"] == "resolver_evidence_contradiction"
        assert contradictions[0]["venue_order_id"] == order_id
        assert contradictions[0]["trade_count"] == "1"
        await client._disconnect()


@pytest.mark.asyncio
async def test_create_fill_evidence_fill_type_blocks_zero_fill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC4(b): `createFillEvidence=fill_type_present` blocks a zero-fill
    even with an otherwise-clean GET and activities join, and raises the
    same contradiction CRITICAL."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        current = client._latch.current_open()
        assert current is not None
        raw = client._store_get(f"{RESOLVER_CONTEXT_KEY_PREFIX}{current.intent_id}")
        assert raw is not None
        context = AmbiguousResolverContext.from_bytes(raw)
        blocked = replace(
            context, create_fill_evidence=submit_chain.CREATE_FILL_EVIDENCE_FILL_TYPE_PRESENT,
        )
        client._store_set(
            f"{RESOLVER_CONTEXT_KEY_PREFIX}{current.intent_id}", blocked.to_bytes(),
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_EXPIRED", cum_quantity=0, leaves_quantity=0,
        )
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {}, "eof": True,
        }
        # Default activities payload: eof-complete, zero trade rows -- proves
        # (b) alone, independent of (c), blocks the zero-fill.

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN
        contradictions = client.resolver_evidence_contradictions
        assert len(contradictions) == 1
        assert contradictions[0]["create_fill_evidence"] == (
            submit_chain.CREATE_FILL_EVIDENCE_FILL_TYPE_PRESENT
        )
        await client._disconnect()


@pytest.mark.asyncio
async def test_unknown_create_fill_evidence_still_requires_activities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC4(b): `unknown` (a legacy blob) is admissible but never sufficient
    on its own -- it still needs (c)/(d)/(e) to retire. Proven here by
    pairing `unknown` with an INCOMPLETE activities read: must stay
    AMBIGUOUS, exactly like `none` would."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        current = client._latch.current_open()
        assert current is not None
        raw = client._store_get(f"{RESOLVER_CONTEXT_KEY_PREFIX}{current.intent_id}")
        assert raw is not None
        context = AmbiguousResolverContext.from_bytes(raw)
        unknown = replace(
            context, create_fill_evidence=submit_chain.CREATE_FILL_EVIDENCE_UNKNOWN,
        )
        client._store_set(f"{RESOLVER_CONTEXT_KEY_PREFIX}{current.intent_id}", unknown.to_bytes())
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_EXPIRED", cum_quantity=0, leaves_quantity=0,
        )
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {}, "eof": True,
        }
        client._private_read._payloads[PORTFOLIO_ACTIVITIES_PATH] = {  # type: ignore[attr-defined]
            "activities": [], "eof": False,
        }

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN, (
            "unknown is admissible but never short-circuits (c)/(d)/(e)"
        )
        # Never a contradiction: `unknown` does not block, and no trade was found.
        assert client.resolver_evidence_contradictions == ()
        await client._disconnect()


@pytest.mark.asyncio
async def test_activities_read_failure_stays_ambiguous_and_counts_backoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC4(c): a raised exception on the activities GET is a read failure,
    not a completeness signal -- stays AMBIGUOUS, never a contradiction."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_EXPIRED", cum_quantity=0, leaves_quantity=0,
        )
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {}, "eof": True,
        }
        original_read = client._private_read

        async def _failing_activities_read(
            path: str, query: Mapping[str, object] | None = None,
        ) -> Any:
            if path == PORTFOLIO_ACTIVITIES_PATH:
                raise RuntimeError("synthetic activities failure")
            return await original_read(path, query)

        client._private_read = _failing_activities_read

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN
        assert client.resolver_evidence_contradictions == ()
        await client._disconnect()


@pytest.mark.asyncio
async def test_min_create_time_below_created_ns_without_eof_is_not_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Binding coordinator amendment (2026-09-27): AC4(c) completeness is
    EOF-ONLY. A read that pages `_RESOLVER_ACTIVITY_MAX_PAGES` times, NEVER
    reaching `eof`, but whose running minimum `createTime` is already far
    below `context.createdNs` on every page, must still be INCOMPLETE --
    the `min(createTime) < createdNs` shortcut stays UNLICENSED
    (follow-up EDGE-2-MULTIPAGE) until a real multi-page traversal is
    observed. RED today only in the sense that a licensed-shortcut
    implementation would retire here; the coordinator amendment forbids
    that implementation."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_EXPIRED", cum_quantity=0, leaves_quantity=0,
        )
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {}, "eof": True,
        }
        activities_calls = {"count": 0}
        original_read = client._private_read

        async def _never_eof_activities(
            path: str, query: Mapping[str, object] | None = None,
        ) -> Any:
            if path == PORTFOLIO_ACTIVITIES_PATH:
                activities_calls["count"] += 1
                # `createTime` is far in the past on EVERY page -- if the
                # (forbidden) threshold shortcut were licensed, the FIRST
                # page alone would already satisfy it.
                return {
                    "activities": [
                        {
                            "type": "ACTIVITY_TYPE_TRADE",
                            "trade": {
                                "aggressor": {"id": "SOME-OTHER-ORDER"},
                                "marketSlug": slug,
                                "qtyDecimal": "1",
                                "createTime": "2020-01-01T00:00:00.000000000Z",
                            },
                        },
                    ],
                    "eof": False,
                    "nextCursor": f"page-{activities_calls['count']}",
                }
            return await original_read(path, query)

        client._private_read = _never_eof_activities

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN, (
            "a read that never reaches eof must stay AMBIGUOUS regardless of "
            "how far in the past the running minimum createTime is"
        )
        # The cap: each resolver pass makes EXACTLY `_RESOLVER_ACTIVITY_MAX_
        # PAGES` (20) GETs before giving up incomplete, never more per pass
        # -- `_run_resolver_passes` may drive several passes in one bounded
        # window (the intent never resolves), so the total is a positive
        # multiple of 20, not 20 itself.
        assert activities_calls["count"] > 0
        assert activities_calls["count"] % 20 == 0
        await client._disconnect()


# ---------------------------------------------------------------------------
# EDGE-2-MULTIPAGE step 1 (r2 delta M-1/M-2/M-3/M-5): D1 (`bool(page.get(
# "eof"))` treats any truthy non-bool as EOF) and D2 (a page whose
# `activities` field is not a list silently contributes zero rows while the
# loop pages on) could each make a read look complete when it was not. Both
# are refused below: a malformed page (non-list `activities`, or a present
# non-bool `eof`) stops the read INCOMPLETE, the same shape a page-cap hit
# already has -- never `None`, so a trade an EARLIER page already found is
# never discarded.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("eof_value", "expected_complete"),
    [
        ("false", False),
        ("true", False),
        (1, False),
        ("0", False),
        (0, False),
        (None, False),  # a present null -- distinct from a missing key
        (True, True),  # control
    ],
)
async def test_eof_non_bool_truthy_is_incomplete(
    eof_value: object,
    expected_complete: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """T1 (r2 M-5): JSON decodes only `true`/`false` to `bool`, so any
    non-bool `eof` PRESENT on the page -- including an explicit null -- is
    venue schema drift (D1), never evidence of completion. RED today:
    `bool("false")`, `bool(1)` and `bool("0")` are all truthy, so the read
    is wrongly reported complete for every non-bool case; only the `True`
    control is genuinely complete."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )

        async def _single_page(path: str, query: Mapping[str, object] | None = None) -> Any:
            assert path == PORTFOLIO_ACTIVITIES_PATH
            return {"activities": [], "eof": eof_value}

        client._private_read = _single_page

        join = await client._order_trade_activity(order_id, client._clock.timestamp_ns())

        assert join is not None
        assert join.complete is expected_complete
        assert join.trade_count == 0
        await client._disconnect()


@pytest.mark.asyncio
async def test_page_without_activities_list_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """T2 (r2 M-1/M-5): page 1 carries no `activities` field at all (D2).
    The read must stop THERE, incomplete -- never page past it to page 2's
    `eof=True` and report a false complete-with-zero-trades. RED today:
    `complete=True, trade_count=0` (the malformed page silently contributes
    zero rows and the loop pages on to page 2's eof)."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        pages: list[Mapping[str, object]] = [
            {"eof": False, "nextCursor": "c1"},
            {"activities": [], "eof": True},
        ]
        queries: list[Mapping[str, object] | None] = []

        async def _paged_read(path: str, query: Mapping[str, object] | None = None) -> Any:
            assert path == PORTFOLIO_ACTIVITIES_PATH
            queries.append(query)
            return pages[len(queries) - 1]

        client._private_read = _paged_read

        join = await client._order_trade_activity(order_id, client._clock.timestamp_ns())

        assert join is not None
        assert join.complete is False
        assert join.trade_count == 0
        assert len(queries) == 1, (
            "a malformed page must stop the read immediately, never page past it"
        )
        await client._disconnect()


@pytest.mark.asyncio
async def test_page_two_without_activities_list_is_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """T2b (r2 M-5 domain item 2; kills M9): page 1 is well-formed with a
    NON-matching trade row, page 2 is malformed. The malformed-page guard
    must fire on EVERY page, not only page 1 -- a guard hoisted before the
    loop would let page 2 through unchecked and wrongly report `eof=True`
    as complete."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        pages: list[Mapping[str, object]] = [
            {
                "activities": [
                    {
                        "type": "ACTIVITY_TYPE_TRADE",
                        "trade": {
                            "aggressor": {"id": "SOME-OTHER-ORDER"},
                            "qtyDecimal": "1",
                            "createTime": "2026-09-23T17:22:07.900000000Z",
                        },
                    },
                ],
                "eof": False,
                "nextCursor": "c1",
            },
            {"activities": "not-a-list", "eof": True},
        ]
        queries: list[Mapping[str, object] | None] = []

        async def _paged_read(path: str, query: Mapping[str, object] | None = None) -> Any:
            assert path == PORTFOLIO_ACTIVITIES_PATH
            queries.append(query)
            return pages[len(queries) - 1]

        client._private_read = _paged_read

        join = await client._order_trade_activity(order_id, client._clock.timestamp_ns())

        assert join is not None
        assert join.complete is False
        assert join.trade_count == 0
        assert len(queries) == 2, "page 2 must be READ, then refused -- not skipped"
        await client._disconnect()


@pytest.mark.asyncio
async def test_terminal_zero_with_malformed_eof_never_retires(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """T3 (r2 M-5), end to end: a single page whose `eof` is a truthy
    non-bool (`"false"`), with otherwise-clean zero-fill evidence (terminal
    GET, empty activities, min age and baseline already satisfied by
    `_arm_one_ambiguous_intent`), must stay AMBIGUOUS -- never retire. RED
    today: `bool("false")` is truthy, so `_order_trade_activity` reports the
    read complete and `_resolve_terminal_zero` retires it as
    `STATUS_REPORT_ZERO_FILL_TERMINAL`."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_EXPIRED", cum_quantity=0, leaves_quantity=0,
        )
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {}, "eof": True,
        }
        client._private_read._payloads[PORTFOLIO_ACTIVITIES_PATH] = {  # type: ignore[attr-defined]
            "activities": [], "eof": "false",
        }

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN, (
            "a malformed non-bool eof must never authorize a zero-fill retirement"
        )
        await client._disconnect()


@pytest.mark.asyncio
async def test_trade_on_page_one_then_malformed_page_two_still_contradicts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """T7 (r2 M-5; pins M-1): a real TRADE for THIS venue order id on page
    1, followed by a malformed page 2, with a GET-terminal-zero order. The
    resolver's evidence-contradiction CRITICAL must still fire -- a
    malformed LATER page must never discard a trade an EARLIER page already
    found. RED today (pre-M-1 `return None` shape): `_order_trade_activity`
    returns `None` for the malformed page, so the caller's `join is None`
    branch stays AMBIGUOUS WITHOUT ever raising the CRITICAL -- the trade
    found on page 1 is silently lost."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        terminal_zero_body = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_EXPIRED", cum_quantity=0, leaves_quantity=0,
        )
        positions_body = {"positions": {}, "eof": True}
        activities_pages: list[Mapping[str, object]] = [
            {
                "activities": [
                    {
                        "type": "ACTIVITY_TYPE_TRADE",
                        "trade": {
                            "aggressor": {"id": order_id},
                            "marketSlug": slug,
                            "qtyDecimal": "1",
                            "createTime": "2026-09-23T17:22:07.900000000Z",
                        },
                    },
                ],
                "eof": False,
                "nextCursor": "c1",
            },
            {"activities": "not-a-list", "eof": True},
        ]
        activities_calls = {"count": 0}

        async def _routed_read(path: str, query: Mapping[str, object] | None = None) -> Any:
            if path == f"/v1/order/{order_id}":
                return terminal_zero_body
            if path == PORTFOLIO_POSITIONS_PATH:
                return positions_body
            assert path == PORTFOLIO_ACTIVITIES_PATH
            page = activities_pages[activities_calls["count"]]
            activities_calls["count"] += 1
            return page

        client._private_read = _routed_read
        assert client.resolver_evidence_contradictions == ()

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN, "a contradiction never retires"
        contradictions = client.resolver_evidence_contradictions
        assert len(contradictions) == 1
        assert contradictions[0]["severity"] == "CRITICAL"
        assert contradictions[0]["trade_count"] == "1"
        await client._disconnect()


def test_the_malformed_page_warnings_name_the_keys_they_saw() -> None:
    """r2 M-2/M-5 (L-37): the malformed-page refusals must name the keys
    they saw on the offending page, never `type(...).__name__` -- `self.
    _log` is Nautilus's own Cython logger and cannot be observed at runtime
    (established limitation, see the docstrings above), so this is a
    source-level AST check that the function contains exactly two
    `[k for k in page]` list comprehensions (the shape M-2 mandates,
    because it adds no new callee the egress firewall guard would need to
    admit -- `.keys()`/`list()`/`sorted()` are NOT on its allowlist)."""
    import ast
    import inspect
    import textwrap

    source = textwrap.dedent(
        inspect.getsource(PolymarketUSExecutionClient._order_trade_activity),
    )
    tree = ast.parse(source)
    key_naming_comprehensions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ListComp)
        and isinstance(node.elt, ast.Name)
        and node.elt.id == "k"
        and node.generators
        and isinstance(node.generators[0].target, ast.Name)
        and node.generators[0].target.id == "k"
        and isinstance(node.generators[0].iter, ast.Name)
        and node.generators[0].iter.id == "page"
    ]
    assert len(key_naming_comprehensions) == 2, (
        "both the non-list-activities and non-bool-eof warnings must name "
        "the keys they saw via `[k for k in page]`"
    )


def test_a_multi_page_activities_read_logs_an_info_signal() -> None:
    """T8 (r2 M-3, M-5): a read that traverses more than one page must log
    an INFO line naming the page count -- the Step 2 probe trigger. `self.
    _log` cannot be observed at runtime (see above), so this is the same
    source-level pin idiom
    `test_the_missing_instrument_escalation_is_gated_by_the_dedup_set`
    already uses."""
    import inspect

    source = inspect.getsource(PolymarketUSExecutionClient._order_trade_activity)
    marker = "_page_index > 0"
    assert marker in source, "the multi-page signal must be gated on more than one page"
    idx = source.index(marker)
    block = source[idx : idx + 400]
    assert "self._log.info(" in block
    assert "pages" in block


@pytest.mark.asyncio
async def test_same_day_prior_durable_holding_does_not_block_true_zero_fill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC4(e)/AC7(iii): a same-day PRIOR durable fill on this instrument
    explains the venue's LONG holding, so a true zero-fill for a SECOND,
    unrelated order on the SAME instrument still retires -- the holding
    cannot wedge it."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        instrument = build_instrument()
        prior_fill = DurableFillRecord(
            venue_order_id="ord-prior-fill-1",
            client_order_id="C-ord-prior-fill-1",
            instrument_id=str(instrument.id),
            order_side="BUY",
            cumulative_qty=Decimal(1),
            cumulative_cost=Decimal("0.40"),
            cumulative_fee=Decimal(0),
            fee_reconciled=True,
            ts_event=client._clock.timestamp_ns(),
        )
        client.record_fill(prior_fill)
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_EXPIRED", cum_quantity=0, leaves_quantity=0,
        )
        # The venue reports a LONG explained EXACTLY by the prior fill.
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {slug: {"netPosition": "1"}}, "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED, (
            "a fully-explained prior holding must never wedge a true zero-fill"
        )
        assert current.retirement_reason is not None
        assert current.retirement_reason.value == "STATUS_REPORT_ZERO_FILL_TERMINAL"
        await client._disconnect()


@pytest.mark.asyncio
async def test_same_day_unexplained_holding_blocks_zero_fill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC4(e) negative: the SAME venue-reported LONG, but with NO durable
    fill record to explain it, must NOT retire as zero-fill."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_EXPIRED", cum_quantity=0, leaves_quantity=0,
        )
        # No durable fill record explains this LONG at all.
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {slug: {"netPosition": "1"}}, "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN, (
            "an unexplained holding must never be waved through as zero-fill"
        )
        await client._disconnect()


@pytest.mark.asyncio
async def test_durable_net_qty_read_failure_stays_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC4(e): an unreadable durable-fill index for THIS instrument is
    undetermined, never zero -- stays AMBIGUOUS, counted as a resolver
    error, never retired on evidence it could not read."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        instrument = build_instrument()
        client._store_set(f"{FILL_INDEX_KEY_PREFIX}{instrument.id}", b"not-valid-json")
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_EXPIRED", cum_quantity=0, leaves_quantity=0,
        )
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {slug: {"netPosition": "1"}}, "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN, (
            "an unreadable durable-fill index is undetermined, never zero -- "
            "must never retire on evidence it could not read"
        )
        await client._disconnect()


@pytest.mark.asyncio
async def test_past_day_read_skips_holding_leg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC4(e): past-day reads (instrument absent from
    `_instrument_provider.list_all()`) skip the holding leg entirely --
    proven by a holding that would FAIL (e) if it were evaluated (no
    durable fill explains it) still retiring as zero-fill, because it is
    never checked for a past-day instrument (D2: a settled market's
    position is meaningless corroboration)."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        # `build_second_instrument()` is added to the CACHE only, never to
        # `_instrument_provider` -- the same-day membership test this plan's
        # AC4(e) baseline reads must see it as a past-day instrument.
        stale_instrument = build_second_instrument()
        assert client._cache.instrument(stale_instrument.id) is None
        client._cache.add_instrument(stale_instrument)
        current = client._latch.current_open()
        assert current is not None
        _rewrite_resolver_context_instrument(client, current.intent_id, str(stale_instrument.id))
        stale_slug = instrument_id_to_slug(stale_instrument.id)
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=stale_slug, state="ORDER_STATE_EXPIRED", cum_quantity=0,
            leaves_quantity=0,
        )
        # An UNEXPLAINED holding on the past-day slug -- would fail (e) if
        # evaluated, since no durable fill record exists for this instrument.
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {stale_slug: {"netPosition": "1"}}, "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED, (
            "a past-day read must skip AC4(e)'s holding leg entirely"
        )
        await client._disconnect()


@pytest.mark.asyncio
async def test_fill_resolves_on_trade_join_when_holding_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """D7: a GET-confirmed FILL with NO holding present (a settled market or
    a completed exit) still resolves -- via the activities trade join, not
    the positions leg -- and records the synthesized fill."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_EXPIRED", cum_quantity=1, avg_px="0.40",
            leaves_quantity=0,
        )
        # No holding at all -- the settled-market/completed-exit shape.
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {}, "eof": True,
        }
        client._private_read._payloads[PORTFOLIO_ACTIVITIES_PATH] = {  # type: ignore[attr-defined]
            "activities": [
                {
                    "type": "ACTIVITY_TYPE_TRADE",
                    "trade": {
                        "aggressor": {"id": order_id},
                        "marketSlug": slug,
                        "qtyDecimal": "1",
                        "createTime": "2026-09-23T17:22:07.900000000Z",
                    },
                },
            ],
            "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        assert current.retirement_reason is not None
        assert current.retirement_reason.value == "STATUS_REPORT_ACCEPT_FILL_TERMINAL"
        raw = client._store_get(f"{FILL_KEY_PREFIX}{order_id}")
        assert raw is not None, "the trade-join-confirmed fill must be recorded durably"
        await client._disconnect()


@pytest.mark.asyncio
async def test_mia_0923_past_day_shape_retires_zero_fill_with_empty_trade_join(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC7(i): the verbatim MIA 09-23 shape (past-day loader instrument,
    positions `{}` eof, GET `EXPIRED qty=1 cum=0 leaves=0`, complete
    activities with no trade for the id) retires as
    `STATUS_REPORT_ZERO_FILL_TERMINAL`."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        stale_instrument = build_second_instrument()
        assert client._cache.instrument(stale_instrument.id) is None
        client._cache.add_instrument(stale_instrument)
        current = client._latch.current_open()
        assert current is not None
        _rewrite_resolver_context_instrument(client, current.intent_id, str(stale_instrument.id))
        stale_slug = instrument_id_to_slug(stale_instrument.id)
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=stale_slug, state="ORDER_STATE_EXPIRED", cum_quantity=0,
            leaves_quantity=0,
        )
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {}, "eof": True,
        }
        client._private_read._payloads[PORTFOLIO_ACTIVITIES_PATH] = {  # type: ignore[attr-defined]
            "activities": [], "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.RETIRED
        assert current.retirement_reason is not None
        assert current.retirement_reason.value == "STATUS_REPORT_ZERO_FILL_TERMINAL"
        await client._disconnect()


@pytest.mark.asyncio
async def test_mia_0923_past_day_shape_with_trade_row_stays_ambiguous(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """AC7(ii): the SAME MIA 09-23 shape, but the activities page carries a
    real TRADE row for this venue order id -- CONTRADICTION, stays
    AMBIGUOUS."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, _slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        stale_instrument = build_second_instrument()
        assert client._cache.instrument(stale_instrument.id) is None
        client._cache.add_instrument(stale_instrument)
        current = client._latch.current_open()
        assert current is not None
        _rewrite_resolver_context_instrument(client, current.intent_id, str(stale_instrument.id))
        stale_slug = instrument_id_to_slug(stale_instrument.id)
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=stale_slug, state="ORDER_STATE_EXPIRED", cum_quantity=0,
            leaves_quantity=0,
        )
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {}, "eof": True,
        }
        client._private_read._payloads[PORTFOLIO_ACTIVITIES_PATH] = {  # type: ignore[attr-defined]
            "activities": [
                {
                    "type": "ACTIVITY_TYPE_TRADE",
                    "trade": {
                        "aggressor": {"id": order_id},
                        "marketSlug": stale_slug,
                        "qtyDecimal": "1",
                        "createTime": "2026-09-23T17:22:07.900000000Z",
                    },
                },
            ],
            "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        current = client._latch.current()
        assert current is not None
        assert current.state is SubmitIntentState.OPEN, (
            "a real trade row for this id must never let the order retire as zero-fill"
        )
        contradictions = client.resolver_evidence_contradictions
        assert len(contradictions) == 1
        assert contradictions[0]["venue_order_id"] == order_id
        await client._disconnect()


class _RecordingAlertSink:
    """An `AlertSink` that keeps every payload it is handed."""

    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


def _tick_health_watch_topic(msgbus: MessageBus) -> None:
    """Publish one `ComponentStateChanged` on the shared health-watch topic
    -- the SAME poll-trigger shape `install_resolver_contradiction_alert`'s
    own test module drives by hand."""
    msgbus.publish(
        topic="events.system.SOME_COMPONENT",
        msg=ComponentStateChanged(
            trader_id=TRADER_ID,
            component_id=ClientId("SOME_COMPONENT"),
            component_type="SomeComponent",
            state=ComponentState.RUNNING,
            config={},
            event_id=UUID4(),
            ts_event=0,
            ts_init=0,
        ),
    )


@pytest.mark.asyncio
async def test_a_resolver_contradiction_is_delivered_through_the_installed_watch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    write_canonical_verified: None,  # noqa: F811
) -> None:
    """Silent-failure review of 75b9008 (BLOCKING): a contradiction the REAL
    resolver raises must reach an operator through the REAL
    `install_resolver_contradiction_alert` watch -- recording it on
    `resolver_evidence_contradictions` alone is not delivery. Negative
    control: no contradiction, no alert, even after the watch polls."""
    enable_operator_gate(monkeypatch, order_count="2")
    with operator_control_env(MAX_DAILY_BUDGET_USD_ENV_VAR, "1000.00"), operator_control_env(
        MAX_POSITION_COST_USD_ENV_VAR, "10.00",
    ):
        client, order_id, slug, _latch_cm, _order_events = await _arm_one_ambiguous_intent(
            tmp_path,
        )
        sink = _RecordingAlertSink()
        install_resolver_contradiction_alert(
            client._msgbus,
            contradictions=lambda: client.resolver_evidence_contradictions,
            sink=sink,
        )

        # Negative control FIRST: a clean, non-contradicting pass (the
        # shared rig's default terminal-zero-friendly fixtures are not
        # wired here, so this pass simply finds nothing terminal yet) must
        # never alert, even once the watch polls.
        _tick_health_watch_topic(client._msgbus)
        assert sink.payloads == []

        # Now wire the CONTRADICTION shape: GET terminal zero, but the
        # activities join finds a real TRADE row for this venue order id.
        client._private_read._payloads[  # type: ignore[attr-defined]
            f"/v1/order/{order_id}"
        ] = _order_get_body(
            order_id, slug=slug, state="ORDER_STATE_EXPIRED", cum_quantity=0, leaves_quantity=0,
        )
        client._private_read._payloads[PORTFOLIO_POSITIONS_PATH] = {  # type: ignore[attr-defined]
            "positions": {}, "eof": True,
        }
        client._private_read._payloads[PORTFOLIO_ACTIVITIES_PATH] = {  # type: ignore[attr-defined]
            "activities": [
                {
                    "type": "ACTIVITY_TYPE_TRADE",
                    "trade": {
                        "aggressor": {"id": order_id},
                        "marketSlug": slug,
                        "qtyDecimal": "1",
                        "createTime": "2026-09-23T17:22:07.900000000Z",
                    },
                },
            ],
            "eof": True,
        }

        await _run_resolver_passes(client, count=1)

        # The resolver pass itself records the condition but publishes no
        # `ComponentStateChanged` of its own -- delivery requires the watch
        # to actually poll.
        assert client.resolver_evidence_contradictions != ()
        assert sink.payloads == [], "recording alone is not delivery"

        _tick_health_watch_topic(client._msgbus)

        assert len(sink.payloads) == 1, sink.payloads
        payload = sink.payloads[0]
        assert payload.severity == "CRITICAL"
        assert payload.event == "resolver_evidence_contradiction"
        assert order_id in payload.detail

        # A second poll with the SAME still-open contradiction must not
        # re-alert (dedupe by intent id).
        _tick_health_watch_topic(client._msgbus)
        assert len(sink.payloads) == 1
        await client._disconnect()
