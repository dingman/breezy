"""Fill-versus-GTD-expiry: a fill for an order whose rest was already closed.

The managed GTD timer cancels at ``expire_time``; the venue (or the harness) then
answers ``OrderExpired``. ``_close_rest`` drops the rest and re-decides, so a fill
that is published afterwards for that same client order id finds no rest. Qty is 1
(one ``OrderFilled`` is the whole order; there is no partial-fill handler). The
order FSM rejects ``EXPIRED -> FILLED``; Nautilus still publishes that event
(``ExecutionEngine._apply_event_to_order`` returns true on ``InvalidStateTrigger``).
``deliver(..., engine_tolerant=True)`` is that publish path.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from nautilus_trader.model.enums import LiquiditySide
from nautilus_trader.test_kit.stubs.events import TestEventStubs

from breezy.strategy.no_ladder_maker.ladder_state import RestState
from breezy.strategy.no_ladder_maker.rule import P3_LICENSED_GTD_NS
from tests.strategy.no_ladder_maker.maker_strategy_support import (
    ACCOUNT,
    DAY,
    HOUR_NS,
    NOW_NS,
    NS,
    Harness,
    no_id,
    want,
)


def _rung(h: Harness) -> str:
    return h.rung("gte72lt73f")


def _arm(h: Harness) -> str:
    rung = _rung(h)
    h.install(lambda ctx: want((rung, 89)))
    return rung


def _fill_after_close(h: Harness, order: Any) -> None:
    """Publish ``OrderFilled`` even though the order FSM refuses to apply it."""
    instrument = h.cache.instrument(order.instrument_id)
    h.deliver(
        TestEventStubs.order_filled(
            order,
            instrument,
            account_id=ACCOUNT,
            liquidity_side=LiquiditySide.MAKER,
            ts_event=h.clock.timestamp_ns(),
        ),
        engine_tolerant=True,
    )


def _expire_after_fill(h: Harness, order: Any) -> None:
    """Publish ``OrderExpired`` after the order is already FILLED (FSM refuses it)."""
    h.deliver(
        TestEventStubs.order_expired(order, ts_event=h.clock.timestamp_ns()),
        engine_tolerant=True,
    )


def test_a_fill_after_expiry_holds_the_rung_and_cancels_the_live_repost() -> None:
    h = Harness()
    rung = _arm(h)
    h.book("gte72lt73f")
    (first,) = h.post_and_accept()
    h.advance_to(first.order.expire_time_ns)
    h.drain()  # the managed GTD timer's CancelOrder, unanswered until expire()
    h.expire(first.order)
    assert h.ladder.held == set()
    assert rung not in h.ladder.rests
    h.book("gte72lt73f", bids=(("0.06", 10),))
    (repost,) = h.post_and_accept()
    assert repost.order.client_order_id != first.order.client_order_id
    _fill_after_close(h, first.order)
    assert h.ladder.held == {rung}
    commands = h.drain()
    assert h.submits(commands) == []
    assert [c.client_order_id for c in h.cancels(commands)] == [repost.order.client_order_id]
    h.cancel_ack(repost.order)
    assert h.ladder.rests == {}
    assert h.ladder.held == {rung}
    h.book("gte72lt73f", bids=(("0.07", 10),))
    assert h.submits(h.drain()) == []
    assert (
        h.cache.orders_open(instrument_id=no_id("SFO", "gte72lt73f"), strategy_id=h.strategy.id)
        == []
    )


def test_a_fill_after_expiry_before_any_repost_blocks_the_next_post() -> None:
    h = Harness()
    rung = _arm(h)
    h.book("gte72lt73f")
    (first,) = h.post_and_accept()
    h.advance_to(first.order.expire_time_ns)
    h.drain()
    h.expire(first.order)
    assert h.submits(h.drain()) == []  # stale book: the re-post has not happened yet
    _fill_after_close(h, first.order)
    assert h.ladder.held == {rung}
    assert rung not in h.ladder.rests
    h.book("gte72lt73f", bids=(("0.06", 10),))
    assert h.submits(h.drain()) == []
    assert h.ladder.held == {rung}
    assert h.ladder.rests == {}


def test_an_expiry_at_t0_plus_4h_reposts_once_while_the_window_is_open() -> None:
    h = Harness()
    rung = _arm(h)
    h.book("gte72lt73f")
    (first,) = h.post_and_accept()
    cap = NOW_NS + P3_LICENSED_GTD_NS
    permit_end = NOW_NS + 10 * HOUR_NS
    midnight = (NOW_NS // (24 * HOUR_NS) + 1) * 24 * HOUR_NS
    assert first.order.expire_time_ns == cap
    assert cap < midnight < permit_end < h.ladder.hard_cancel_ns
    h.advance_to(cap)
    h.drain()
    h.expire(first.order)
    h.book("gte72lt73f", bids=(("0.06", 10),))
    (second,) = h.submits(h.drain())
    assert h.ladder.rests[rung].client_order_id == second.order.client_order_id
    assert second.order.expire_time_ns == midnight  # 4 h from 21:00Z crosses UTC midnight
    assert second.order.expire_time_ns < permit_end
    assert h.submits(h.drain()) == []


def test_no_repost_after_the_hard_cancel() -> None:
    h = Harness()
    rung = _arm(h)
    h.book("gte72lt73f")
    h.post_and_accept()
    h.advance_to(h.ladder.hard_cancel_ns)
    assert h.ladder.hard_cancelled is True
    hard = int(dt.datetime(2026, 9, 18, 17, 0, tzinfo=dt.UTC).timestamp()) * NS
    assert h.ladder.hard_cancel_ns == hard
    h.book("gte72lt73f", bids=(("0.06", 10),))
    assert h.submits(h.drain()) == []
    rest = h.ladder.rests.get(rung)
    assert rest is None or rest.state is RestState.CANCELING


def test_no_repost_after_the_permit_end() -> None:
    h = Harness()
    rung = _arm(h)
    permit_end = NOW_NS + 10 * HOUR_NS
    assert permit_end < h.ladder.hard_cancel_ns
    h.advance_to(permit_end)
    h.book("gte72lt73f")
    assert h.submits(h.drain()) == []
    assert h.strategy.counters["refused_expired_window"] >= 1
    assert rung not in h.ladder.rests
    assert DAY == dt.date(2026, 9, 18)


def test_a_fill_before_expiry_stays_held_and_is_not_reposted() -> None:
    h = Harness()
    rung = _arm(h)
    h.book("gte72lt73f")
    (first,) = h.post_and_accept()
    h.fill(first.order)
    assert h.ladder.held == {rung}
    assert h.ladder.rests == {}
    _expire_after_fill(h, first.order)
    assert h.ladder.held == {rung}
    assert h.ladder.rests == {}
    assert h.submits(h.drain()) == []
    h.book("gte72lt73f", bids=(("0.06", 10),))
    assert h.submits(h.drain()) == []
    assert rung not in h.ladder.rests
