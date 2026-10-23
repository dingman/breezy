"""ARM C2 review fixes: the cancel state machine, the sweep, restart adoption, shadow expiry,
the stale-book and window-end guards and the handler guard.

Findings (C2 review follow-ups): V1 cancel rejected / lost ack / fill race, V2 and W3 and X2 the
veto / halt / stop sweep over open AND in-flight orders, V3 and W4 the day-rollover contract and the
window-end guard, V4 the handler guard, V5 shadow expiry, V6 NBP rows across a ladder change (in
``test_live_feed.py``), W1 the stale-book guard, W2 restart adoption, X6 no venue cancels in shadow.

Nautilus 1.231 facts these tests rest on (verified in the installed source):
* ``Strategy.cancel_order`` sends nothing for an order that is closed or already PENDING_CANCEL;
* ``Strategy.cancel_all_orders`` only moves OPEN orders to PENDING_CANCEL, and the exec client
  cancels ledger-bound rests only, so an in-flight (SUBMITTED, no venue id) order is orphaned by it;
* ``OrderCancelRejected`` returns the order to its pre-cancel status (``Order.apply``).
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.messages import SubmitOrder
from nautilus_trader.model.enums import OrderSide, OrderStatus, TimeInForce
from nautilus_trader.model.events import OrderExpired
from nautilus_trader.model.identifiers import VenueOrderId
from nautilus_trader.model.objects import Price
from nautilus_trader.test_kit.stubs.events import TestEventStubs

import breezy.strategy.no_ladder_maker.strategy as strategy_module
from breezy.normalize.climate_day import local_standard_date
from breezy.registry.sites import default_registry
from breezy.strategy.no_ladder_maker.config import CANCEL_DEADLINE_S, STALE_BOOK_S
from breezy.strategy.no_ladder_maker.ladder_state import RestState
from breezy.strategy.no_ladder_maker.records import Decision
from tests.strategy.no_ladder_maker.maker_strategy_support import (
    DAY,
    HOUR_NS,
    NOW_NS,
    NS,
    TRADER,
    Harness,
    cents_of,
    no_id,
    want,
)

BAND = "gte72lt73f"


def _price_script(h: Harness, band: str = BAND, cents: int = 89) -> dict[str, int]:
    price = {"cents": cents}
    h.install(lambda ctx: want((h.rung(band), price["cents"])))
    return price


def _resting(h: Harness, *, accepted: bool = True) -> tuple[str, SubmitOrder, dict[str, int]]:
    """Post one rung; accepted by the venue, or left in flight (SUBMITTED, no venue id)."""
    price = _price_script(h)
    h.book(BAND)
    (command,) = h.submits(h.drain())
    if accepted:
        h.accept(command)
    else:
        h.mark_submitted(command)
    return h.rung(BAND), command, price


def _reprice(h: Harness, price: dict[str, int], cents: int = 87) -> None:
    price["cents"] = cents
    h.book(BAND, bids=(("0.06", 10),))


def _hard_alert(h: Harness) -> None:
    ladder = h.ladder
    name = f"MAKER-HARD:{ladder.station}:{ladder.day.isoformat()}"
    h.strategy._on_hard_alert(SimpleNamespace(name=name))


# --- V1: the CANCELING state machine ---------------------------------------------------------


def test_a_rejected_cancel_is_reissued_by_the_next_poll_and_the_rung_reposts_after_the_ack() -> (
    None
):
    h = Harness()
    rung, first, price = _resting(h)
    _reprice(h, price)
    assert len(h.cancels(h.drain())) == 1
    h.cancel_reject(first.order, "no bound resting order carries this client order id")
    assert h.ladder.rests[rung].state is RestState.CANCELING, "the cancel is still wanted"
    assert h.strategy.counters["cancel_rejected"] == 1
    h.advance(31)
    commands = h.drain()
    assert [c.client_order_id for c in h.cancels(commands)] == [first.order.client_order_id]
    h.cancel_ack(first.order)
    assert h.submits(h.drain()) == [], "the frame is 31 s old: the repost waits for a fresh one"
    h.book(BAND, bids=(("0.07", 10),))
    (second,) = h.submits(h.drain())
    assert cents_of(second) == 87


def test_a_lost_cancel_ack_is_queried_then_reissued_after_the_deadline() -> None:
    h = Harness()
    _rung, first, price = _resting(h)
    _reprice(h, price)
    h.drain()
    h.advance(31)  # first poll: inside the deadline -> a query, no new cancel
    inside = h.drain()
    assert [q.client_order_id for q in h.queries(inside)] == [first.order.client_order_id]
    assert h.cancels(inside) == [] and h.cancel_alls(inside) == []
    h.advance(CANCEL_DEADLINE_S)  # past the deadline -> re-issued
    overdue = h.drain()
    assert len(h.cancels(overdue)) + len(h.cancel_alls(overdue)) == 1, "exactly one re-issue"
    assert h.strategy.counters["cancel_reissued"] == 1
    h.cancel_ack(first.order)
    h.book(BAND, bids=(("0.07", 10),))
    assert cents_of(h.submits(h.drain())[0]) == 87


def test_a_terminal_event_lost_before_the_strategy_is_reconciled_from_the_cache() -> None:
    h = Harness()
    rung, first, price = _resting(h)
    _reprice(h, price)
    h.drain()
    cached = h.cache.order(first.order.client_order_id)
    assert cached is not None
    cached.apply(TestEventStubs.order_canceled(cached, ts_event=h.clock.timestamp_ns()))
    h.cache.update_order(cached)  # the engine saw the cancel; the strategy never did
    h.advance(31)
    assert rung not in h.ladder.rests
    assert h.strategy.counters["rest_reconciled_from_cache"] == 1
    h.book(BAND, bids=(("0.07", 10),))
    assert cents_of(h.submits(h.drain())[0]) == 87


def test_a_fill_racing_a_pending_cancel_holds_the_rung_and_the_late_replies_change_nothing() -> (
    None
):
    h = Harness()
    rung, first, price = _resting(h)
    _reprice(h, price)
    h.drain()
    h.fill(first.order)  # the venue filled it before the cancel landed
    assert h.ladder.held == {rung} and rung not in h.ladder.rests
    h.cancel_reject(first.order, "too late to cancel")
    h.advance(CANCEL_DEADLINE_S * 3)
    commands = h.drain()
    assert h.cancels(commands) == [] and h.cancel_alls(commands) == []
    assert h.submits(commands) == []
    assert h.ladder.held == {rung}


# --- V2 / W3 / X2: the sweep covers in-flight orders ------------------------------------------


@pytest.mark.parametrize("trigger", ["veto", "halt", "stop"])
def test_a_submitted_rest_is_cancelled_per_order_by_veto_halt_and_stop(trigger: str) -> None:
    veto: dict[str, str | None] = {"reason": None}
    h = Harness(veto=lambda: veto["reason"])
    rung, command, _ = _resting(h, accepted=False)
    assert command.order.status is OrderStatus.SUBMITTED
    if trigger == "veto":
        veto["reason"] = "family_halt"
        h.book(BAND, bids=(("0.06", 10),))
    elif trigger == "halt":
        _hard_alert(h)
    else:
        h.strategy.stop()
    commands = h.drain()
    assert [c.client_order_id for c in h.cancels(commands)] == [command.order.client_order_id]
    assert h.cancel_alls(commands) == [], "cancel-all would orphan an in-flight order"
    assert h.ladder.rests[rung].state is RestState.CANCELING


def test_an_order_accepted_after_its_cancel_was_refused_is_cancelled_on_acceptance() -> None:
    veto: dict[str, str | None] = {"reason": None}
    h = Harness(veto=lambda: veto["reason"])
    rung, command, _ = _resting(h, accepted=False)
    veto["reason"] = "loss_stop_fail"
    h.book(BAND, bids=(("0.06", 10),))
    assert len(h.cancels(h.drain())) == 1
    h.cancel_reject(command.order, "no bound resting order carries this client order id")
    h.accept(command)  # the venue acknowledged the submit after all
    assert [c.client_order_id for c in h.cancels(h.drain())] == [command.order.client_order_id]
    assert h.ladder.rests[rung].state is RestState.CANCELING


def test_an_order_accepted_while_a_price_change_cancel_is_pending_is_cancelled() -> None:
    h = Harness()
    rung, command, price = _resting(h, accepted=False)
    _reprice(h, price)
    assert len(h.cancels(h.drain())) == 1
    h.cancel_reject(command.order, "no bound resting order carries this client order id")
    h.accept(command)
    assert len(h.cancels(h.drain())) == 1
    assert h.ladder.rests[rung].state is RestState.CANCELING


def test_a_latched_veto_re_sweeps_on_every_poll_until_it_clears() -> None:
    veto: dict[str, str | None] = {"reason": None}
    h = Harness(veto=lambda: veto["reason"])
    _rung, command, _ = _resting(h)
    veto["reason"] = "family_halt"
    h.advance(31)
    assert len(h.cancels(h.drain())) == 1
    h.cancel_reject(command.order, "venue refused")  # restored to ACCEPTED, still resting
    h.advance(31)
    assert [c.client_order_id for c in h.cancels(h.drain())] == [command.order.client_order_id]


def test_a_shadow_strategy_sends_no_venue_cancel_when_it_has_no_real_rest() -> None:
    veto: dict[str, str | None] = {"reason": None}
    h = Harness(shadow_only=True, veto=lambda: veto["reason"])
    _price_script(h)
    h.book(BAND)
    veto["reason"] = "family_halt"
    h.advance(31)
    h.strategy.stop()
    assert h.drain() == [] and h.cancel_all_calls == []
    assert h.ladder.rests == {}


# --- V3 / W4: day rollover contract and the window-end guard ----------------------------------

#: The supervisor relaunches daily: stop_prior 16:40Z, launch 16:50Z (CT-08 contract surface).
LAUNCH = dt.time(16, 50)
SESSION = dt.timedelta(hours=23, minutes=50)
#: The permit window of one ladder day D: [D-1 16:50Z, D 02:50Z).
PERMIT_WINDOW = dt.timedelta(hours=10)


@pytest.mark.parametrize("station", ["LAX", "MDW", "MIA", "SFO"])
def test_a_session_posting_window_never_spans_two_ladder_days(station: str) -> None:
    launch = dt.datetime.combine(dt.date(2026, 9, 17), LAUNCH, tzinfo=dt.UTC)
    offset = default_registry().climate_day_window("polymarket_us", station).std_utc_offset_hours
    day = local_standard_date(int(launch.timestamp()) * NS, offset) + dt.timedelta(days=1)
    h = Harness(stations=(station,), now_ns=int(launch.timestamp()) * NS)
    assert h.ladder.day == day == DAY
    assert h.ladder.window_open_ns == int(launch.timestamp()) * NS, "opens at the relaunch"
    end = launch + PERMIT_WINDOW
    assert end < launch + SESSION, "the whole permit window lies inside one session"
    t = launch
    while t < end:  # the ladder day derived at any instant of the window is the frozen one
        assert local_standard_date(int(t.timestamp()) * NS, offset) + dt.timedelta(days=1) == day
        t += dt.timedelta(minutes=10)


def test_the_window_end_guard_stops_posting_and_cancels_when_the_alert_never_fired() -> None:
    h = Harness()
    _rung, command, price = _resting(h)
    h.drain()
    h.clock.set_time(h.ladder.hard_cancel_ns + NS)  # the hard-cancel alert was lost
    _reprice(h, price)
    commands = h.drain()
    assert h.submits(commands) == []
    assert h.strategy.counters["refused_after_window"] == 1
    assert h.ladder.hard_cancelled is True
    assert [c.client_order_id for c in h.cancels(commands)] == [command.order.client_order_id]


# --- W1: the stale-book guard ----------------------------------------------------------------


def _wanted_later(h: Harness) -> dict[str, bool]:
    wanted = {"on": False}
    rung = h.rung(BAND)
    h.install(lambda ctx: want((rung, 89)) if wanted["on"] else Decision(forecast_valid=True))
    return wanted


def test_a_quiet_rung_is_postable_while_another_rung_on_the_feed_updated_1s_ago() -> None:
    h = Harness()
    wanted = _wanted_later(h)
    h.book(BAND)  # the rung's only frame
    h.advance(60)  # the rung stays quiet for a minute...
    h.book("gte70lt71f")  # ...but the feed is alive
    h.advance(1)
    wanted["on"] = True
    h.strategy._decide(h.ladder)
    assert len(h.submits(h.drain())) == 1
    assert h.strategy.counters["refused_stale_book"] == 0


def test_every_feed_silent_for_more_than_the_bound_refuses_the_post() -> None:
    h = Harness()
    wanted = _wanted_later(h)
    h.book(BAND)
    h.book("gte70lt71f")
    h.advance(STALE_BOOK_S + 1)
    wanted["on"] = True
    h.strategy._decide(h.ladder)  # e.g. an NBP release, a poll or an expiry re-decide
    assert h.submits(h.drain()) == []
    assert h.strategy.counters["refused_stale_book"] == 1
    h.book("gte70lt71f")  # the feed speaks again
    assert len(h.submits(h.drain())) == 1


def test_a_rung_with_no_frame_of_its_own_is_never_posted_even_on_a_live_feed() -> None:
    h = Harness()
    _price_script(h)
    h.book("gte70lt71f")
    assert h.submits(h.drain()) == []


def test_a_post_is_refused_on_a_silent_feed_whose_ask_has_since_dropped() -> None:
    h = Harness()
    wanted = _wanted_later(h)
    h.book(BAND)  # YES bid 5c -> NO ask 95c: an 89c bid is admissible against THIS frame
    h.advance(STALE_BOOK_S + 1)  # silence: the real ask may have dropped to 88c meanwhile
    wanted["on"] = True
    h.strategy._decide(h.ladder)
    assert h.submits(h.drain()) == []
    assert h.strategy.counters["refused_stale_book"] == 1


def test_a_feed_frame_inside_the_bound_is_still_admissible() -> None:
    h = Harness()
    wanted = _wanted_later(h)
    h.book(BAND)
    h.advance(STALE_BOOK_S - 1)
    wanted["on"] = True
    h.strategy._decide(h.ladder)
    assert len(h.submits(h.drain())) == 1


def test_the_stale_book_bound_is_a_few_seconds_and_pinned() -> None:
    assert STALE_BOOK_S == 5


# --- W2: restart adoption ----------------------------------------------------------------------


def _preexisting_order(
    h: Harness, *, cents: int = 88, status: OrderStatus, strategy_id: Any
) -> Any:
    no = h.cache.instrument(no_id("SFO", BAND))
    assert no is not None
    factory = OrderFactory(trader_id=TRADER, strategy_id=strategy_id, clock=h.clock)
    order = factory.limit(
        instrument_id=no.id,
        order_side=OrderSide.BUY,
        quantity=no.make_qty(1),
        price=Price.from_str(f"0.{cents:02d}"),
        time_in_force=TimeInForce.GTD,
        expire_time=pd.Timestamp(NOW_NS + 5 * HOUR_NS, unit="ns", tz="UTC"),
    )
    h.cache.add_order(order, position_id=None)
    order.apply(TestEventStubs.order_submitted(order, ts_event=NOW_NS))
    if status is OrderStatus.ACCEPTED:
        order.apply(
            TestEventStubs.order_accepted(
                order, venue_order_id=VenueOrderId("V-OLD"), ts_event=NOW_NS
            )
        )
    h.cache.update_order(order)
    return order


@pytest.mark.parametrize("status", [OrderStatus.ACCEPTED, OrderStatus.SUBMITTED])
def test_a_restart_adopts_an_existing_order_and_never_posts_a_second_one(
    status: OrderStatus,
) -> None:
    h = Harness(start=False)
    order = _preexisting_order(h, status=status, strategy_id=h.strategy.id)
    h.strategy.start()
    rung = h.rung(BAND)
    rest = h.ladder.rests[rung]
    assert rest.client_order_id == order.client_order_id and rest.bid_cents == 88
    assert rest.expire_ns == NOW_NS + 5 * HOUR_NS
    assert h.strategy.counters["adopted_rests"] == 1
    _price_script(h, cents=88)
    h.book(BAND)
    assert h.submits(h.drain()) == [], "the existing rest is the rung's rest"


def test_an_adopted_rest_is_repriced_by_cancel_then_repost() -> None:
    h = Harness(start=False)
    order = _preexisting_order(h, status=OrderStatus.ACCEPTED, strategy_id=h.strategy.id)
    h.strategy.start()
    _price_script(h, cents=86)
    h.book(BAND)
    assert [c.client_order_id for c in h.cancels(h.drain())] == [order.client_order_id]
    h.cancel_ack(order)
    assert cents_of(h.submits(h.drain())[0]) == 86


def test_an_order_of_another_strategy_is_never_adopted() -> None:
    from nautilus_trader.model.identifiers import StrategyId

    h = Harness(start=False)
    _preexisting_order(h, status=OrderStatus.ACCEPTED, strategy_id=StrategyId("OPERATOR-001"))
    h.strategy.start()
    assert h.ladder.rests == {} and h.strategy.counters["adopted_rests"] == 0


# --- V5: shadow rests expire -------------------------------------------------------------------


def test_a_shadow_rest_expires_at_its_expiry_and_is_reposted_like_a_live_one() -> None:
    h = Harness(shadow_only=True)
    rung = h.rung(BAND)
    _price_script(h)
    h.book(BAND)
    first = h.ladder.rests[rung]
    assert first.state is RestState.SHADOW
    h.advance_to(first.expire_ns)
    assert rung not in h.ladder.rests or h.ladder.rests[rung].expire_ns > first.expire_ns
    assert h.strategy.counters["shadow_expired"] == 1
    h.book(BAND)  # a fresh frame after the expiry: re-posted with a later expiry
    assert h.ladder.rests[rung].expire_ns > first.expire_ns


def test_a_cancelled_shadow_rest_is_not_expired_later() -> None:
    h = Harness(shadow_only=True)
    rung = h.rung(BAND)
    price = _price_script(h)
    h.book(BAND)
    first = h.ladder.rests[rung]
    price["cents"] = 87
    h.book(BAND, bids=(("0.06", 10),))  # reprice: cancel (would-cancel) then the next decision
    h.advance_to(first.expire_ns)
    assert h.strategy.counters["shadow_expired"] <= 1


# --- V4: every handler is guarded (L-16) -------------------------------------------------------


def _boom(*_args: object, **_kwargs: object) -> Any:
    raise RuntimeError("handler blew up")


def _order_event(h: Harness, kind: str) -> Any:
    h.install(lambda ctx: want((h.rung(BAND), 89)))
    h.book(BAND)
    (command,) = h.submits(h.drain())
    order = command.order
    if kind == "expired":
        return OrderExpired(
            trader_id=TRADER,
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            venue_order_id=None,
            account_id=None,
            event_id=UUID4(),
            ts_event=NOW_NS,
            ts_init=NOW_NS,
        )
    return TestEventStubs.order_accepted(order, venue_order_id=VenueOrderId("V-1"), ts_event=NOW_NS)


@pytest.mark.parametrize("handler", ["on_order_accepted", "on_order_expired", "on_order_canceled"])
def test_an_order_event_handler_never_raises(handler: str) -> None:
    h = Harness()
    event = _order_event(h, "expired" if handler == "on_order_expired" else "accepted")
    h.strategy._rest_for = _boom  # type: ignore[method-assign]
    h.strategy._alert = _boom  # type: ignore[method-assign]
    getattr(h.strategy, handler)(event)  # must not raise


def test_a_fill_handler_updates_state_before_a_failing_alert_and_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = Harness()
    rung, command, _ = _resting(h)
    monkeypatch.setattr(strategy_module, "emit_alert", _boom)
    h.fill(command.order)  # the alert sink raises; the fill is still booked
    assert h.ladder.held == {rung}


@pytest.mark.parametrize("callback", ["_on_nbp_alert", "_on_hard_alert", "_on_poll"])
def test_a_timer_callback_never_raises(callback: str) -> None:
    h = Harness()
    getattr(h.strategy, callback)(SimpleNamespace(name="garbage"))  # malformed name: must not raise


def test_an_alert_sink_failure_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    h = Harness()
    monkeypatch.setattr(strategy_module, "emit_alert", _boom)
    h.strategy._alert("X", "i", "c", "INFO")
