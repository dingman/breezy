"""ARM B7 / S4 WP6 (build half): the resting-order lifecycle, end to end, with NO venue.

Authority: ``docs/plans/backlog/MAKER_2026-10-12/S4_exec_resting_order_path_plan_r3.md`` section 6
WP6, ``..._r4_delta.md`` section 2 WP6, and ``ARM_MAKER_SHARP_2026-10-21/plan_r1.md`` row B7.

What is real here: the Nautilus ``Strategy`` (``manage_gtd_expiry=True``, so the GTD expiry is the
NATIVE time-alert timer on the strategy clock, never a hand-called cancel), its ``OrderFactory``,
the cache and message bus, and the REAL ``PolymarketUSExecutionClient`` with its real admission
(permit order count, notional budget, the K=1 submit latch), durable store, ledger, cancel loop,
poll booking and boot sweep. What is a double: the order sender and the private-read stub (local
objects, no socket) and the execution engine, which is replaced by :class:`_Bench` (it routes the
strategy's commands to the client and feeds the client's events back to the cache and strategy,
exactly the two jobs the engine does in a node).

Constants flipped in the tests, and why: the rig's ``_rig`` patches ``GTD_EXPIRY_VERIFIED`` to
``True`` (a resting submit is refused while it is ``False``). ``MAKER_COMMISSION_SIGN_VERIFIED``
and ``SLUG_SCOPED_CANCEL_ALL_VERIFIED`` stay ``False`` (the module values; the recognised
commission is therefore the clamp and the sweep cancels per id). B2 flips them from venue evidence.

The ``exec`` package is never imported here (barrier X1 pins its importers by set equality);
every symbol comes through ``tests/unit/ambig_latch_rig.py`` or the sibling suites.

Wall time: every await is bounded by :data:`WALL_S`.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import Counter
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pytest
from nautilus_trader.common.component import MessageBus, TestClock
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import (
    CancelAllOrders,
    CancelOrder,
    QueryOrder,
    SubmitOrder,
)
from nautilus_trader.model.enums import LiquiditySide, OrderSide, TimeInForce
from nautilus_trader.model.events import OrderEvent
from nautilus_trader.model.objects import Quantity
from nautilus_trader.portfolio.portfolio import Portfolio
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.trading.strategy import Strategy

from breezy.adapters.polymarket_us.errors import VenueTransportError
from breezy.adapters.polymarket_us.safety import live_trading_budget_remaining
from breezy.runtime.component_health_watch import install_resting_alert
from breezy.runtime.health import AlertPayload
from breezy.strategy.current_rung_hold.trial_day_latch import (
    startup_evidence_permits_arm,
    startup_evidence_refusal_reason,
)
from tests.unit.ambig_latch_rig import (
    OPEN_ORDERS_PATH,
    caps,
    client_module,
    response_sender,
    rig_slug,
    run_passes,
    submit_chain,
    write_canonical_verified,  # noqa: F401 -- reused as a fixture
    write_evidence,
)
from tests.unit.polymarket_us_exec_shapes import build_no_leg_instrument
from tests.unit.test_ambig_no_id_resolver import _negative, _retirement
from tests.unit.test_current_rung_hold_pre_arm_race import TRADER_ID
from tests.unit.test_polymarket_us_permit_issuance import enable_operator_gate
from tests.unit.test_polymarket_us_resting_cancel import CancelSender, _rig, _set_state
from tests.unit.test_polymarket_us_resting_query import _fill, _inert_bps
from tests.unit.test_polymarket_us_resting_submit import (
    _create_body,
    _expire_ns,
    _id_n,
    _Rig,
    _venue_order,
)
from tests.unit.test_polymarket_us_resting_sweep import _open_row, _second_process, _set_state_on

#: Every await in this module is bounded by this (a hung async test once ran 3.5 h).
WALL_S: Final[float] = 20.0
#: Hard ceiling on a whole scenario's wall time, asserted at the end.
SCENARIO_WALL_S: Final[float] = 60.0
NS: Final[int] = 1_000_000_000
#: The permit's order count for the lifecycle: six rests fit, the seventh and eighth are refused.
PERMIT_ORDER_COUNT: Final[int] = 6
SWEEP: Final[str] = submit_chain.RETIRE_BOOT_SWEEP_RESTING_NO_FILL
_EVIDENCE_KEY: Final[str] = client_module.STARTUP_EVIDENCE_KEY
_INDEX_KEY: Final[str] = client_module.RESTING_INDEX_KEY
_TIMER_PREFIX: Final[str] = "GTD-EXPIRY:"
_CANCELED: Final[str] = "ORDER_STATE_CANCELED"
_EXPIRED: Final[str] = "ORDER_STATE_EXPIRED"


# ---------------------------------------------------------------------------
# The bench: a native Strategy plus the two jobs the execution engine does
# ---------------------------------------------------------------------------


class _LifecycleStrategy(Strategy):  # type: ignore[misc]
    """Test-only: does exactly what the scenario tells it to (no logic of its own)."""


class _Bench:
    """Routes the strategy's commands to the real client and feeds its events back.

    ``RiskEngine.execute`` and ``ExecEngine.execute`` are the two endpoints the native
    ``OrderManager`` sends submit and cancel/query commands to. The client's own events arrive
    on the rig's ``ExecEngine.process`` list; :meth:`pump` applies each to its cached order (so
    the cache and the strategy see real order state) and publishes it on the strategy's
    ``events.order`` topic, which is how a closed order cancels its managed GTD timer.
    """

    def __init__(self, rig: _Rig) -> None:
        self.rig = rig
        self.client = rig.client
        self.clock = TestClock()
        self.clock.set_time(self.client._clock.timestamp_ns())
        portfolio = Portfolio(
            msgbus=MessageBus(trader_id=TRADER_ID, clock=self.clock),
            cache=self.client._cache,
            clock=self.clock,
        )
        self.strategy = _LifecycleStrategy(
            StrategyConfig(
                strategy_id="LifecycleStrategy-B7", order_id_tag="B7", manage_gtd_expiry=True
            )
        )
        self.strategy.register(
            trader_id=TRADER_ID,
            portfolio=portfolio,
            msgbus=self.client._msgbus,
            cache=self.client._cache,
            clock=self.clock,
        )
        self.strategy.start()
        self.inbox: list[Any] = []
        self.client._msgbus.register(endpoint="RiskEngine.execute", handler=self.inbox.append)
        self.client._msgbus.register(endpoint="ExecEngine.execute", handler=self.inbox.append)
        self.next_id = 0
        self.id_of_order: dict[str, int] = {}
        self._pumped = 0
        self.denied: list[str] = []
        self.no_id_ack = False

    # -- orders ------------------------------------------------------------

    def order(self, *, expire_s: int = 1_800, price: str = "0.40") -> Any:
        no = build_no_leg_instrument()
        expire = pd.Timestamp(_expire_ns(self.client, seconds=expire_s), unit="ns", tz="UTC")
        return self.strategy.order_factory.limit(
            instrument_id=no.id,
            order_side=OrderSide.BUY,
            quantity=Quantity(1, no.size_precision),
            price=no.make_price(price),
            time_in_force=TimeInForce.GTD,
            expire_time=expire,
            post_only=False,
        )

    def timers(self) -> list[str]:
        return sorted(n for n in self.clock.timer_names if n.startswith(_TIMER_PREFIX))

    def advance(self, seconds: float) -> None:
        """Move BOTH clocks and fire whatever the strategy clock now owes (the native timers)."""
        self.client.advance(seconds)
        target = self.clock.timestamp_ns() + int(seconds * NS)
        for handler in self.clock.advance_time(target):
            handler.handle()

    # -- the engine's two jobs --------------------------------------------

    def pump(self) -> None:
        events = self.rig.events
        for event in events[self._pumped :]:
            if not isinstance(event, OrderEvent):
                continue
            order = self.client._cache.order(event.client_order_id)
            if order is not None:
                order.apply(event)
            self.client._msgbus.publish(topic=f"events.order.{self.strategy.id}", msg=event)
        self._pumped = len(events)

    async def drain(self) -> None:
        """Hand every queued strategy command to the client, in order, each bounded."""
        while self.inbox:
            command = self.inbox.pop(0)
            if isinstance(command, SubmitOrder):
                await self._submit(command)
            elif isinstance(command, CancelOrder):
                await asyncio.wait_for(self.client._cancel_order(command), WALL_S)
            elif isinstance(command, CancelAllOrders):
                await asyncio.wait_for(self.client._cancel_all_orders(command), WALL_S)
            elif isinstance(command, QueryOrder):
                await asyncio.wait_for(self.client._query_order(command), WALL_S)
            else:  # pragma: no cover - a new command type must be routed deliberately
                raise TypeError(f"unrouted strategy command {type(command).__name__}")
            self.pump()

    async def _submit(self, command: SubmitOrder) -> None:
        """Script the venue's answer for the next id, then run the REAL submit."""
        n = self.next_id
        if self.no_id_ack:
            # a 200 whose body carries no venue order id: the no-id AMBIGUOUS path
            self.rig.sender.response = response_sender(200, b"{}").response
        else:
            self.rig.sender.response = response_sender(200, _create_body(_id_n(n))).response
            payloads: dict[str, Any] = self.client._private_read._payloads
            payloads[submit_chain.order_by_id_path(_id_n(n))] = _venue_order(command, id=_id_n(n))
            _inert_bps(self.rig, n)
        posts_before = len(self.rig.sender.calls)
        await asyncio.wait_for(self.client._submit_order(command), WALL_S)
        if self.no_id_ack:
            assert len(self.rig.sender.calls) == posts_before + 1, "the no-id rest did POST"
        elif len(self.rig.sender.calls) > posts_before:
            self.id_of_order[command.order.client_order_id.value] = n
            self.next_id += 1
        else:
            self.denied.append(command.order.client_order_id.value)

    def submit(self, order: Any) -> None:
        self.strategy.submit_order(order)

    def stop(self) -> None:
        self.strategy.stop()


def _honour_cancels(rig: _Rig, *, expired: frozenset[int] = frozenset()) -> None:
    """The venue honours every cancel POST of a LIVE order: it then reads CANCELED (or EXPIRED
    for the ids in ``expired``). A POST at an already-terminal order changes nothing."""

    def _on_cancel(order_id: str) -> None:
        n = int(order_id[-1])
        live = rig.client._private_read._payloads[submit_chain.order_by_id_path(order_id)]["order"]
        if live["state"] == "ORDER_STATE_NEW":
            _set_state(rig, n, _EXPIRED if n in expired else _CANCELED)

    rig.sender.on_cancel = _on_cancel


def _names(rig: _Rig) -> Counter[str]:
    return Counter(rig.event_names())


def _remaining(client: Any) -> tuple[Decimal, int]:
    notional, count = live_trading_budget_remaining(client._permit)
    return Decimal(notional), int(count)


def _evidence(client: Any) -> dict[str, Any]:
    raw = client._store_get(_EVIDENCE_KEY)
    assert raw is not None, "the boot wrote no startup evidence"
    decoded: dict[str, Any] = json.loads(raw)
    return decoded


def _index(client: Any) -> list[str]:
    raw = client._store_get(_INDEX_KEY)
    return [] if raw is None else list(json.loads(raw))


def _open_exposures(client: Any) -> list[str]:
    """Venue ids whose intent still holds a registered open exposure."""
    return sorted(
        venue_id
        for venue_id, (intent_id, _booking) in client._resting_bookings.items()
        if client._ledger.has_open_exposure(intent_id)
    )


class _RecordingSink:
    def __init__(self) -> None:
        self.payloads: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.payloads.append(payload)


def _bounded(scenario: Callable[[], Any]) -> Callable[[], Any]:
    async def _run() -> None:
        started = time.monotonic()
        await asyncio.wait_for(scenario(), timeout=SCENARIO_WALL_S)
        assert time.monotonic() - started < SCENARIO_WALL_S

    return _run


# ---------------------------------------------------------------------------
# Scenario 1: submit x8 -> poll -> fill -> cancel-replace -> station cancel ->
# GTD expiry (native timer) -> stop -> restart -> rehydrate + boot sweep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.usefixtures("write_canonical_verified")
async def test_resting_order_lifecycle_through_restart_and_boot_sweep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        enable_operator_gate(monkeypatch, order_count=str(PERMIT_ORDER_COUNT))
        with caps():
            await _lifecycle(tmp_path, monkeypatch)

    await _bounded(scenario)()


async def _lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rig = await _rig(tmp_path, monkeypatch)
    client = rig.client
    bench = _Bench(rig)
    _honour_cancels(rig)
    assert _remaining(client)[1] == PERMIT_ORDER_COUNT
    assert client._trading_refusals == [] and client._latch.open_slot_count() == 0
    # arm gate, stage 0: the rig's first boot had no open-orders read wired, and the gate
    # refuses an unreadable book (restated below, after a boot that reads it cleanly)
    first_evidence = _evidence(client)
    assert first_evidence["open_orders_read_refused"] is True
    assert startup_evidence_permits_arm(first_evidence) is False

    # -- stage 1: submit x8 through the strategy; the real admission refuses the surplus ----
    orders = [bench.order() for _ in range(8)]
    for order in orders:
        bench.submit(order)
    assert len(bench.timers()) == 8, "the strategy armed one managed GTD timer per submit"
    await bench.drain()
    accepted = orders[:PERMIT_ORDER_COUNT]
    refused = orders[PERMIT_ORDER_COUNT:]
    assert bench.denied == [o.client_order_id.value for o in refused]
    assert len(rig.sender.calls) == PERMIT_ORDER_COUNT, "refused rests never reach the venue"
    names = _names(rig)
    assert names["OrderAccepted"] == PERMIT_ORDER_COUNT and names["OrderDenied"] == 2
    assert [o.status.name for o in accepted] == ["ACCEPTED"] * PERMIT_ORDER_COUNT
    assert [o.status.name for o in refused] == ["DENIED", "DENIED"]
    assert sorted(client._resting_bookings) == [_id_n(i) for i in range(PERMIT_ORDER_COUNT)]
    assert _index(client) == [_id_n(i) for i in range(PERMIT_ORDER_COUNT)]
    assert _open_exposures(client) == [_id_n(i) for i in range(PERMIT_ORDER_COUNT)]
    assert _remaining(client)[1] == 0, "six order slots spent, none left for a seventh"
    spent_after_submit = client._ledger.spent_today_usd(now_ns=client._clock.timestamp_ns())
    assert client._latch.open_slot_count() == 0, "K=1 released after each bind"
    assert client._trading_refusals == []
    assert len(bench.timers()) == PERMIT_ORDER_COUNT, "closing a denied order cancelled its timer"
    assert client._this_process_resting_ids == frozenset(_id_n(i) for i in range(6))

    # -- stage 2: poll every bound rest; all still NEW, so nothing changes ----------------
    events_before = list(rig.event_names())
    for order in accepted:
        bench.strategy.query_order(order)
    await bench.drain()
    assert rig.event_names() == events_before
    assert _open_exposures(client) == [_id_n(i) for i in range(6)]
    assert client.resting_commission_alerts == () and client.resting_cancel_alerts == ()
    assert client._trading_refusals == []

    # -- stage 3: one fill (rest 0), booked by the poll as MAKER ---------------------------
    remaining_before_fill = _remaining(client)
    _fill(rig, 0, commission="0.01")
    bench.strategy.query_order(accepted[0])
    await bench.drain()
    (filled,) = [e for e in rig.events if type(e).__name__ == "OrderFilled"]
    assert filled.liquidity_side == LiquiditySide.MAKER
    assert filled.commission.as_decimal() == Decimal("0.01"), "positive commission is recognised"
    assert filled.last_px.as_decimal() == Decimal("0.40")
    (record,) = client.fill_records_for(build_no_leg_instrument().id)
    assert record.venue_order_id == _id_n(0)
    assert record.trade_id == submit_chain.maker_poll_trade_id(_id_n(0))
    assert submit_chain.is_maker_poll_fill(record.trade_id), "the harm-stop selector sees it"
    assert record.cumulative_qty == Decimal(1) and record.cumulative_cost == Decimal("0.40")
    assert _remaining(client) == remaining_before_fill, "a fill is spent, never restored"
    assert _open_exposures(client) == [_id_n(i) for i in range(1, 6)]
    assert _index(client) == [_id_n(i) for i in range(1, 6)]
    assert accepted[0].status.name == "FILLED"
    assert len(bench.timers()) == 5, "the filled order's managed GTD timer was cancelled"
    assert client._trading_refusals == [] and client.resting_commission_alerts == ()
    assert client._ledger.spent_today_usd(now_ns=client._clock.timestamp_ns()) >= spent_after_submit

    # -- stage 4: cancel-replace (rest 1 cancelled, a replacement rested in its place) ------
    remaining_before_replace = _remaining(client)
    bench.strategy.cancel_order(accepted[1])
    replacement = bench.order()
    bench.submit(replacement)
    await bench.drain()
    names = _names(rig)
    assert names["OrderCanceled"] == 1 and accepted[1].status.name == "CANCELED"
    assert replacement.status.name == "ACCEPTED"
    assert bench.id_of_order[replacement.client_order_id.value] == 6
    assert _open_exposures(client) == [_id_n(i) for i in (2, 3, 4, 5, 6)]
    assert _remaining(client) == remaining_before_replace, (
        "the cancel returned its slot and the replacement spent it again"
    )
    assert _id_n(1) not in client._resting_bookings and _id_n(1) not in _index(client)

    # -- stage 5: station cancel (every bound rest on the instrument, per id) ---------------
    remaining_before_station = _remaining(client)
    bench.strategy.cancel_all_orders(build_no_leg_instrument().id)
    await bench.drain()
    assert _names(rig)["OrderCanceled"] == 6, "rest 1 plus the five live ones"
    assert rig.sender.cancel_alls == [], "the strategy path never sends a venue cancel-all"
    assert sorted(c["order_id"] for c in rig.sender.cancels) == sorted(
        [_id_n(1), *(_id_n(i) for i in (2, 3, 4, 5, 6))]
    )
    assert _open_exposures(client) == [] and _index(client) == []
    assert _remaining(client)[1] == remaining_before_station[1] + 5
    assert bench.timers() == []
    assert client._cancel_in_flight == frozenset()

    # -- stage 6: GTD expiry through the native timer ----------------------------------------
    short = bench.order(expire_s=300)
    long = bench.order(expire_s=1_800)
    bench.submit(short)
    bench.submit(long)
    await bench.drain()
    short_n, long_n = (
        bench.id_of_order[short.client_order_id.value],
        bench.id_of_order[long.client_order_id.value],
    )
    assert (short_n, long_n) == (7, 8)
    assert len(bench.timers()) == 2
    remaining_before_expiry = _remaining(client)
    _set_state_on(client, short_n, _EXPIRED)  # the venue enforces the GTD at its own time
    bench.advance(301)  # the strategy's managed timer for the short order fires natively
    assert [type(c).__name__ for c in bench.inbox] == ["CancelOrder"]
    await bench.drain()
    assert _names(rig)["OrderExpired"] == 1 and short.status.name == "EXPIRED"
    assert _names(rig)["OrderCanceled"] == 6, "an expiry is not a cancel"
    assert _open_exposures(client) == [_id_n(long_n)]
    assert _remaining(client)[1] == remaining_before_expiry[1] + 1, "this-process id restored"
    assert long.status.name == "ACCEPTED" and len(bench.timers()) == 1
    assert client._trading_refusals == []

    # -- stage 7: a no-id rest (200 without an id) is left OPEN, then stop -------------------
    # The resolver loop (not started in this bench) refreshes the startup evidence on an age
    # gate; do exactly what it does, so the no-id context captures a holding baseline: the
    # venue nets filled rest 0 as one short YES, and our own rest 8 is on the book.
    long_row = dict(
        client._private_read._payloads[submit_chain.order_by_id_path(_id_n(long_n))]["order"]
    )
    held = {rig_slug(): {"netPosition": "-1"}}
    _negative(client, positions=held, open_orders=[long_row])
    client._note_open_orders_outcome(records=await client._read_open_orders())
    write_evidence(client, "-1")
    refreshed = _evidence(client)
    assert [o["own_resting"] for o in refreshed["open_orders"]] == [True]
    assert refreshed["open_orders_read_refused"] is False
    assert startup_evidence_permits_arm(refreshed) is True, "own resting orders are exempt"
    bench.no_id_ack = True
    no_id = bench.order(expire_s=1_800)
    bench.submit(no_id)
    await bench.drain()
    current = client._latch.current_open()
    assert current is not None and client._latch.open_slot_count() == 1
    assert [r.reason for r in client._trading_refusals] == [submit_chain.AMBIGUOUS_REASON]
    intent_id = current.intent_id
    long_payload = client._private_read._payloads[submit_chain.order_by_id_path(_id_n(long_n))]
    bench.stop()
    await client._disconnect()

    # -- stage 8: restart over the same store; rehydrate, boot sweep, retire the no-id intent -
    sender = CancelSender()
    second = await _second_process(
        tmp_path,
        monkeypatch,
        client,
        client.latch_cm,
        sender=sender,
        payloads={
            submit_chain.order_by_id_path(_id_n(long_n)): {"order": long_payload["order"]},
            OPEN_ORDERS_PATH: {"orders": [long_row]},
        },
    )
    _negative(second, positions=held, open_orders=[long_row])

    def _venue_honours_the_sweep(order_id: str) -> None:
        _set_state_on(second, int(order_id[-1]), _CANCELED)
        second._private_read._payloads[OPEN_ORDERS_PATH] = {"orders": []}

    sender.on_cancel = _venue_honours_the_sweep
    second._sweep_retire_admitted = True
    second._no_id_retire_admitted = True
    # the restart happens in the first process's (virtual) time, not 301 s before it
    second.advance(client.offset_clock.offset_ns / NS)
    permit_before_sweep = _remaining(second)
    await asyncio.wait_for(second._connect(), WALL_S)

    assert [c["order_id"] for c in sender.cancels] == [_id_n(long_n)], "only the live rest"
    assert sender.cancel_alls == [] and sender.calls == []
    assert intent_id in second._swept_resting_intent_ids
    assert _index(second) == [] and _open_exposures(second) == []
    assert _id_n(long_n) not in second._this_process_resting_ids
    assert not second._budget_was_restored(_id_n(long_n))
    # the boot seeds the day's spend from the durable POLL- record of the filled rest 0
    # (0.40); the sweep's cancel of the live rest restored nothing to this process's permit
    assert _remaining(second) == (permit_before_sweep[0] - Decimal("0.40"), permit_before_sweep[1])
    assert second._ledger.spent_today_usd(now_ns=second._clock.timestamp_ns()) == Decimal("0.40")
    evidence = _evidence(second)
    # the sweep re-writes the evidence from its certifying read: our rest is gone from the book
    assert evidence["open_orders"] == [] and evidence["open_orders_read_refused"] is False
    assert startup_evidence_refusal_reason(evidence) is None
    assert startup_evidence_permits_arm(evidence) is True
    assert second._trading_refusals == [], "a clean sweep leaves no latch"
    assert second._latch.current_open() is not None, "the no-id intent is still unresolved"

    second.advance(305)
    await run_passes(second, 1)
    assert _retirement(second) is None, "one consistent read retires nothing"
    second.advance(70)
    await run_passes(second, 1)
    assert _retirement(second) == SWEEP
    assert second._latch.open_slot_count() == 0
    assert not second._ledger.has_open_exposure(intent_id)
    assert second.resolver_evidence_contradictions == ()
    assert second.resting_cancel_alerts == () and second.resting_commission_alerts == ()
    await second._disconnect()


# ---------------------------------------------------------------------------
# Scenario 2 (ARM r1 row B7): async rest -> refused cancel -> retry with backoff ->
# venue expiry -> settle once -> permit restored only for this-process ids
# ---------------------------------------------------------------------------


class _RefusingSender(CancelSender):
    """The venue refuses the cancel POST until ``attempt_hook`` says otherwise."""

    def __init__(self) -> None:
        super().__init__()
        self.stamps: list[float] = []
        self.attempt_hook: Callable[[int, str], None] | None = None

    async def post_cancel_order(
        self, api_base_url: str, *, headers: Any, order_id: str, market_slug: str
    ) -> Any:
        self.stamps.append(time.monotonic())
        if self.attempt_hook is not None:
            self.attempt_hook(len(self.stamps), order_id)
        return await super().post_cancel_order(
            api_base_url, headers=headers, order_id=order_id, market_slug=market_slug
        )


@pytest.mark.asyncio
@pytest.mark.usefixtures("write_canonical_verified")
async def test_async_rest_refused_cancel_retries_then_venue_expiry_settles_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def scenario() -> None:
        enable_operator_gate(monkeypatch, order_count=str(PERMIT_ORDER_COUNT))
        with caps():
            await _refused_cancel_then_venue_expiry(tmp_path, monkeypatch)

    await _bounded(scenario)()


async def _refused_cancel_then_venue_expiry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backoff = (0.02, 0.04, 0.08)
    rig = await _rig(tmp_path, monkeypatch)  # its own 1 ms backoff is overridden just below
    monkeypatch.setattr(submit_chain, "CANCEL_RETRY_BACKOFF_S", backoff)
    # an ASYNC rest: the create ack is only an id; the confirm GET reads PENDING for a while
    monkeypatch.setattr(submit_chain, "RESTING_CONFIRM_DEADLINE_NS", 5_000_000_000)
    monkeypatch.setattr(submit_chain, "RESTING_CONFIRM_POLL_S", 0.005)
    sender = _RefusingSender()
    rig.sender = sender
    rig.client._order_sender = sender
    client = rig.client
    bench = _Bench(rig)

    first, second_order = bench.order(), bench.order()
    scripted: dict[str, Any] = client._private_read._payloads

    async def submit_async_rest(command: SubmitOrder) -> None:
        """The create ack carries only an id; the confirm GET reads PENDING, then NEW."""
        n = bench.next_id
        path = submit_chain.order_by_id_path(_id_n(n))
        scripted[path] = _venue_order(command, id=_id_n(n), state="ORDER_STATE_PENDING_RISK")
        _inert_bps(rig, n)
        rig.sender.response = response_sender(200, _create_body(_id_n(n))).response
        flip = asyncio.get_running_loop().call_later(
            0.05, lambda: scripted[path]["order"].update({"state": "ORDER_STATE_NEW"})
        )
        try:
            await asyncio.wait_for(client._submit_order(command), WALL_S)
        finally:
            flip.cancel()
        bench.id_of_order[command.order.client_order_id.value] = n
        bench.next_id += 1
        bench.pump()

    bench.submit(first)
    await submit_async_rest(bench.inbox.pop(0))
    assert first.status.name == "ACCEPTED", "accepted only after the GET read NEW"
    reads = [p for p in client._private_read.paths if p.endswith(_id_n(0))]
    assert len(reads) >= 2, "the confirm polled the GET until it read NEW"
    assert len(sender.calls) == 1, "one create POST"

    # a second rest, and let the client forget it armed this one (a rehydrated id)
    bench.submit(second_order)
    await bench.drain()
    assert second_order.status.name == "ACCEPTED"
    client._this_process_resting_ids = client._this_process_resting_ids - {_id_n(1)}
    assert client._this_process_resting_ids == frozenset({_id_n(0)})
    permit_two_rests = _remaining(client)
    assert permit_two_rests[1] == PERMIT_ORDER_COUNT - 2

    # the alert delivery wiring is the real one: the client's surface -> install_resting_alert
    bus = MessageBus(trader_id=TRADER_ID, clock=bench.clock)
    sink = _RecordingSink()
    install_resting_alert(
        bus,
        alerts=lambda: (*client.resting_cancel_alerts, *client.resting_commission_alerts),
        sink=sink,
    )
    delivered_while_refused: list[int] = []

    def attempts(attempt: int, order_id: str) -> None:
        if order_id != _id_n(0):
            return
        if attempt == 2:
            client.advance(601)  # past RETRY_ALERT_AGE_S: the alert fires, the latch is later
        if attempt == 3:
            assert client.resting_cancel_alerts, "alert recorded before any latch"
            assert client._trading_refusals == [], "alert-before-latch"
            bus.publish(topic="events.system.BENCH", msg=_state_event(bench.clock))
            delivered_while_refused.append(len(sink.payloads))
        if attempt == 4:
            _set_state_on(client, 0, _EXPIRED)  # the venue's own GTD expiry lands

    sender.attempt_hook = attempts
    sender.cancel_raises = VenueTransportError("refused (bench)")
    settles: list[str] = []
    ledger_type = type(client._ledger)
    real_settle = ledger_type.settle

    def spy(self: Any, key: str, **kwargs: Any) -> Any:
        settles.append(key)
        return real_settle(self, key, **kwargs)

    monkeypatch.setattr(ledger_type, "settle", spy)
    intent_0 = client._resting_bookings[_id_n(0)][0]
    intent_1 = client._resting_bookings[_id_n(1)][0]
    events_before = list(rig.event_names())

    bench.strategy.cancel_order(first)
    await bench.drain()

    # refused cancels retried with the configured backoff, changing nothing meanwhile
    posts = [c["order_id"] for c in sender.cancels]
    assert posts == [_id_n(0)] * len(posts) and len(posts) == 4
    gaps = [b - a for a, b in zip(sender.stamps, sender.stamps[1:], strict=False)]
    assert all(g >= want * 0.8 for g, want in zip(gaps, backoff, strict=False)), gaps
    assert delivered_while_refused == [1], "the CRITICAL alert reached the sink while refused"
    alert = sink.payloads[0]
    assert alert.event == "resting_cancel_alert" and alert.severity == "CRITICAL"
    assert _id_n(0) not in alert.detail, "order ids are redacted on the alert"
    # the venue expiry settles ONCE, as an expiry, and restores the permit for this process
    names = Counter(rig.event_names()[len(events_before) :])
    assert names["OrderExpired"] == 1 and names["OrderCanceled"] == 0
    assert first.status.name == "EXPIRED"
    assert settles == [intent_0]
    assert client._budget_was_restored(_id_n(0))
    assert _remaining(client)[1] == permit_two_rests[1] + 1
    assert client._trading_refusals == [] and client.resting_cancel_alerts == ()
    assert _index(client) == [_id_n(1)]

    # the rehydrated id: cancelled, settled once, NEVER restored to this process's permit
    sender.cancel_raises = None
    sender.attempt_hook = None
    _honour_cancels(rig, expired=frozenset({1}))
    before_second = _remaining(client)
    bench.strategy.cancel_order(second_order)
    await bench.drain()
    assert settles == [intent_0, intent_1]
    assert not client._budget_was_restored(_id_n(1))
    assert _remaining(client) == before_second
    assert _names(rig)["OrderExpired"] == 2
    assert _open_exposures(client) == [] and _index(client) == []

    # arm gate: a restart over a rest the venue will not cancel keeps the gate shut
    third = bench.order()
    bench.submit(third)
    await bench.drain()
    n_third = bench.id_of_order[third.client_order_id.value]
    stuck = CancelSender()  # its cancel POST changes nothing: the order stays NEW
    restarted = await _second_process(
        tmp_path,
        monkeypatch,
        client,
        client.latch_cm,
        sender=stuck,
        payloads={
            submit_chain.order_by_id_path(_id_n(n_third)): scripted[
                submit_chain.order_by_id_path(_id_n(n_third))
            ],
            OPEN_ORDERS_PATH: {"orders": [_open_row(_command_of(third), n_third)]},
        },
    )
    await asyncio.wait_for(restarted._connect(), WALL_S)
    reasons = [r.reason for r in restarted._trading_refusals]
    assert reasons == [submit_chain.RESTING_CANCEL_UNCONFIRMED_REASON]
    evidence = _evidence(restarted)
    assert startup_evidence_refusal_reason(evidence) == "resting_cancel_unconfirmed"
    assert startup_evidence_permits_arm(evidence) is False
    assert _index(restarted) == [_id_n(n_third)], "no row deleted unread"
    await restarted._disconnect()
    assert Counter(rig.event_names())["OrderCanceled"] == 0


def _command_of(order: Any) -> Any:
    """A minimal stand-in carrying ``.order`` for the rig's ``_open_row`` builder."""

    class _Command:
        pass

    command = _Command()
    command.order = order  # type: ignore[attr-defined]
    return command


def _state_event(clock: TestClock) -> Any:
    from nautilus_trader.common.enums import ComponentState
    from nautilus_trader.common.messages import ComponentStateChanged
    from nautilus_trader.model.identifiers import ClientId

    return ComponentStateChanged(
        trader_id=TRADER_ID,
        component_id=ClientId("BENCH"),
        component_type="Bench",
        state=ComponentState.RUNNING,
        config={},
        event_id=UUID4(),
        ts_event=clock.timestamp_ns(),
        ts_init=clock.timestamp_ns(),
    )
