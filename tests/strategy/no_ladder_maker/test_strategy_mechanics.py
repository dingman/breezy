"""ARM C2: how ``NoLadderMakerStrategy`` turns decisions into Nautilus commands.

The decision core is replaced by a scripted selector here (its equality with the design driver is
C3 and ``test_strategy_parity.py``); what is pinned is the mapping: BUY NO GTD qty 1 on the NO leg,
price change = cancel then re-post on ``OrderCanceled``, MAX_RUNGS with held rungs, shadow mode,
the refusal guards, the entry veto, the native poll timer, the hard-cancel backstop and ``on_stop``.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from typing import Any

import pytest
from nautilus_trader.model.enums import OrderSide, TimeInForce
from nautilus_trader.model.instruments import BinaryOption

from breezy.strategy.no_ladder_maker.config import AllowShortNotPermittedError, NoLadderMakerConfig
from breezy.strategy.no_ladder_maker.ladder_state import RestState
from breezy.strategy.no_ladder_maker.records import CANCEL_PMIN, Decision
from breezy.strategy.no_ladder_maker.rule import P3_LICENSED_GTD_NS
from breezy.strategy.no_ladder_maker.strategy import (
    REPOST_BACKOFF_S,
    DepthSubscriptionBudgetError,
)
from tests.strategy.no_ladder_maker.maker_strategy_support import (
    BANDS,
    DAY,
    HOUR_NS,
    NOW_NS,
    NS,
    TRADER,
    Harness,
    cents_of,
    no_id,
    want,
    yes_id,
)


def _rung(h: Harness, band: str) -> str:
    return h.rung(band)


# --- config ------------------------------------------------------------------------------------


def test_config_defaults_fail_closed_and_refuse_short_and_unmanaged_expiry() -> None:
    config = NoLadderMakerConfig(stations=("SFO",))
    assert config.shadow_only is True
    assert config.allow_short is False
    assert config.manage_gtd_expiry is True
    with pytest.raises(AllowShortNotPermittedError):
        NoLadderMakerConfig(stations=("SFO",), allow_short=True)
    with pytest.raises(ValueError, match="manage_gtd_expiry"):
        NoLadderMakerConfig(stations=("SFO",), manage_gtd_expiry=False)
    with pytest.raises(ValueError, match="stations"):
        NoLadderMakerConfig()
    with pytest.raises(ValueError, match="poll_interval_s"):
        NoLadderMakerConfig(stations=("SFO",), poll_interval_s=0)


# --- instruments and Depth10 ---------------------------------------------------------------------


def test_depth10_is_subscribed_on_the_yes_instrument_of_every_high_rung_only() -> None:
    h = Harness(start=False)
    subscribed: list[str] = []
    h.strategy.subscribe_order_book_depth = lambda iid, *a, **k: subscribed.append(str(iid))
    h.strategy.start()
    assert sorted(subscribed) == sorted(str(yes_id("SFO", b)) for b in BANDS)
    assert all("NO" not in s.split(".")[0].upper().split("-")[-1:] for s in subscribed)
    assert sorted(h.ladder.rungs) == sorted(subscribed)


def test_a_rung_without_its_no_leg_in_the_cache_is_skipped_not_traded() -> None:
    h = Harness(with_no_legs=False)
    assert h.ladder.rungs == {}
    assert h.strategy.counters["no_leg_not_in_cache"] == len(BANDS)


def test_other_days_and_other_stations_are_not_registered() -> None:
    h = Harness(stations=("SFO",), day=DAY + dt.timedelta(days=1))
    assert h.ladder.rungs == {}  # the cache holds day D+2 only: D+1 (the target) is absent


def test_the_depth_subscription_budget_refuses_to_start_past_the_bound() -> None:
    with pytest.raises(DepthSubscriptionBudgetError, match="exceed 3"):
        Harness(max_depth_subscriptions=3)


def test_target_day_is_tomorrow_in_each_stations_standard_time() -> None:
    h = Harness(stations=("SFO", "MIA"))
    assert {k for k in h.strategy.ladders} == {("SFO", DAY), ("MIA", DAY)}


# --- posting ------------------------------------------------------------------------------


def test_a_wanted_rung_posts_buy_no_gtd_qty_1_on_the_no_leg() -> None:
    h = Harness()
    rung = _rung(h, "gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    h.book("gte72lt73f")
    (submit,) = h.submits(h.drain())
    order = submit.order
    assert order.instrument_id == no_id("SFO", "gte72lt73f")
    assert order.side is OrderSide.BUY
    assert order.quantity.as_decimal() == 1
    assert order.time_in_force is TimeInForce.GTD
    assert order.is_post_only is False
    assert cents_of(submit) == 89
    midnight = (NOW_NS // (24 * HOUR_NS) + 1) * 24 * HOUR_NS
    assert order.expire_time_ns == min(midnight, NOW_NS + 10 * HOUR_NS, NOW_NS + P3_LICENSED_GTD_NS)
    assert h.ladder.rests[rung].state is RestState.SUBMITTED


def test_no_book_no_attempt() -> None:
    h = Harness()
    rung = _rung(h, "gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    h.book("gte70lt71f")  # a different rung's book
    assert h.submits(h.drain()) == []


def test_unchanged_decision_does_not_resubmit() -> None:
    h = Harness()
    rung = _rung(h, "gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    h.book("gte72lt73f")
    h.post_and_accept()
    h.book("gte72lt73f", bids=(("0.06", 10),))
    assert h.drain() == []


def test_price_change_cancels_then_reposts_only_on_order_canceled() -> None:
    h = Harness()
    rung = _rung(h, "gte72lt73f")
    price = {"cents": 89}
    h.install(lambda ctx: want((rung, price["cents"])))
    h.book("gte72lt73f")
    (first,) = h.post_and_accept()
    price["cents"] = 87
    h.book("gte72lt73f", bids=(("0.06", 10),))
    commands = h.drain()
    assert len(h.cancels(commands)) == 1 and h.submits(commands) == []
    h.book("gte72lt73f", bids=(("0.07", 10),))  # still cancelling: no second cancel, no re-post
    assert h.drain() == []
    h.cancel_ack(first.order)
    (second,) = h.submits(h.drain())
    assert cents_of(second) == 87 and second.order.client_order_id != first.order.client_order_id


def test_a_rung_the_decision_drops_is_cancelled_and_not_reposted() -> None:
    h = Harness()
    rung = _rung(h, "gte72lt73f")
    state = {"wanted": True}
    h.install(
        lambda ctx: (
            want((rung, 89))
            if state["wanted"]
            else Decision(drop_reason=CANCEL_PMIN, forecast_valid=True)
        )
    )
    h.book("gte72lt73f")
    (first,) = h.post_and_accept()
    state["wanted"] = False
    h.book("gte72lt73f", bids=(("0.06", 10),))
    assert [c.client_order_id for c in h.cancels(h.drain())] == [first.order.client_order_id]
    h.cancel_ack(first.order)
    assert h.drain() == []
    assert h.ladder.rests == {}


def test_max_rungs_two_caps_live_plus_held_in_rank_order() -> None:
    h = Harness()
    rungs = [_rung(h, b) for b in ("gte68lt69f", "gte70lt71f", "gte72lt73f")]
    h.install(lambda ctx: want((rungs[0], 89), (rungs[1], 88), (rungs[2], 87)))
    for band in ("gte68lt69f", "gte70lt71f", "gte72lt73f"):
        h.book(band)
    submits = h.post_and_accept()
    assert [str(s.order.instrument_id) for s in submits] == [
        str(no_id("SFO", "gte68lt69f")),
        str(no_id("SFO", "gte70lt71f")),
    ]


def test_a_fill_holds_the_rung_and_it_still_counts_toward_max_rungs() -> None:
    h = Harness()
    rungs = [_rung(h, b) for b in ("gte68lt69f", "gte70lt71f", "gte72lt73f")]
    h.install(lambda ctx: want((rungs[0], 89), (rungs[1], 88), (rungs[2], 87)))
    for band in ("gte68lt69f", "gte70lt71f", "gte72lt73f"):
        h.book(band)
    first, second = h.post_and_accept()
    h.fill(first.order)
    assert h.ladder.held == {rungs[0]}
    h.book("gte72lt73f", bids=(("0.06", 10),))
    assert h.submits(h.drain()) == []  # held + live == MAX_RUNGS: the third rung waits
    h.expire(second.order)  # the second rest expires and its slot frees
    (again,) = h.submits(h.drain())  # rank order: the freed slot goes to the second rung again
    assert str(again.order.instrument_id) == str(no_id("SFO", "gte70lt71f"))
    assert rungs[0] not in h.ladder.rests  # the held rung is never re-posted
    assert rungs[2] not in h.ladder.rests  # held + live == MAX_RUNGS still


# --- shadow and refusal guards -----------------------------------------------------------


def test_shadow_mode_sends_nothing_and_keeps_a_virtual_rest() -> None:
    h = Harness(shadow_only=True)
    rung = _rung(h, "gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    h.book("gte72lt73f")
    h.book("gte72lt73f", bids=(("0.06", 10),))
    assert h.drain() == []
    assert h.ladder.rests[rung].state is RestState.SHADOW
    assert h.ladder.rests[rung].bid_cents == 89


@pytest.mark.parametrize(
    ("kwargs", "counter"),
    [
        ({"permit_expires_at_ns": None}, "refused_phase0_permit_absent"),
        ({"permit_expires_at_ns": NOW_NS - 1}, "refused_expired_window"),
        ({"fee_verified": lambda now_ns: False}, "refused_fee_unverified"),
    ],
)
def test_send_guards_refuse_before_any_order_is_built(kwargs: dict[str, Any], counter: str) -> None:
    h = Harness(**kwargs)
    rung = _rung(h, "gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    h.book("gte72lt73f")
    assert h.drain() == []
    assert h.strategy.counters[counter] >= 1
    assert h.ladder.rests == {}


def test_a_marketable_bid_is_never_placed() -> None:
    h = Harness()
    rung = _rung(h, "gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    # YES bid 12c -> NO ask 88c; a 89c NO bid would take.
    h.book("gte72lt73f", bids=(("0.12", 10),))
    assert h.drain() == []
    assert h.strategy.counters["refused_MARKETABLE"] == 1


def test_a_truncated_ask_side_at_our_level_is_never_placed() -> None:
    h = Harness()
    rung = _rung(h, "gte72lt73f")
    h.install(lambda ctx: want((rung, 62)))
    asks = tuple((f"0.{c:02d}", 5) for c in range(11, 21))  # ten levels, deepest YES ask 20c
    h.book("gte72lt73f", asks=asks)
    assert h.drain() == []
    assert h.strategy.counters["refused_TRUNCATED_FRAME"] == 1


def test_a_denied_order_backs_off_before_the_rung_is_posted_again() -> None:
    h = Harness()
    rung = _rung(h, "gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    h.book("gte72lt73f")
    (first,) = h.submits(h.drain())
    h.deny(first.order)
    h.book("gte72lt73f", bids=(("0.06", 10),))
    assert h.drain() == [] and h.strategy.counters["backoff"] == 1
    h.advance(REPOST_BACKOFF_S + 1)
    h.drain()
    h.book("gte72lt73f", bids=(("0.07", 10),))
    assert len(h.submits(h.drain())) == 1


def test_a_rejected_order_also_backs_off() -> None:
    h = Harness()
    rung = _rung(h, "gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    h.book("gte72lt73f")
    (first,) = h.submits(h.drain())
    h.reject(first.order)
    h.book("gte72lt73f", bids=(("0.06", 10),))
    assert h.submits(h.drain()) == []


def test_a_gtd_expiry_event_redecides_and_reposts_within_the_permit() -> None:
    h = Harness()
    rung = _rung(h, "gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    h.book("gte72lt73f")
    (first,) = h.post_and_accept()
    h.advance_to(first.order.expire_time_ns)  # Nautilus' managed GTD timer fires its cancel
    h.drain()
    h.expire(first.order)
    assert h.submits(h.drain()) == [], "the last frame is hours old: a fresh one is required"
    h.book("gte72lt73f", bids=(("0.06", 10),))
    (second,) = h.submits(h.drain())
    assert second.order.expire_time_ns > first.order.expire_time_ns
    assert second.order.expire_time_ns <= NOW_NS + 10 * HOUR_NS  # never past the permit


# --- veto, hard cancel, stop ---------------------------------------------------------------------


def test_an_entry_veto_blocks_posting_and_cancels_each_live_order_once_per_deadline() -> None:
    veto: dict[str, str | None] = {"reason": None}
    h = Harness(veto=lambda: veto["reason"])
    rung = _rung(h, "gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    h.book("gte72lt73f")
    (first,) = h.post_and_accept()
    veto["reason"] = "family_halt"
    h.book("gte72lt73f", bids=(("0.06", 10),))
    commands = h.drain()
    assert [c.client_order_id for c in h.cancels(commands)] == [first.order.client_order_id], (
        "family halt -> a CancelOrder for every live order, read per order from the cache"
    )
    assert h.cancel_alls(commands) == [] and h.cancel_all_calls == []
    assert h.submits(commands) == []
    h.book("gte72lt73f", bids=(("0.07", 10),))
    h.advance(31)  # the poll re-sweeps, but the cancel is still inside its deadline
    again = h.drain()
    assert h.cancels(again) == [] and h.cancel_alls(again) == [], "one cancel per deadline"


def test_a_veto_is_noticed_by_the_poll_timer_without_any_book_update() -> None:
    veto: dict[str, str | None] = {"reason": None}
    h = Harness(veto=lambda: veto["reason"])
    rung = _rung(h, "gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    h.book("gte72lt73f")
    (first,) = h.post_and_accept()
    veto["reason"] = "loss_stop_fail"
    h.advance(31)
    assert [c.client_order_id for c in h.cancels(h.drain())] == [first.order.client_order_id]
    assert h.strategy.counters["cancel_everything_veto"] == 1


def test_a_raising_veto_fails_closed() -> None:
    def boom() -> str | None:
        raise RuntimeError("unreadable")

    h = Harness(veto=boom)
    rung = _rung(h, "gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    h.book("gte72lt73f")
    assert h.submits(h.drain()) == []


def test_on_stop_cancels_every_live_order_and_sends_nothing_when_there_is_none() -> None:
    idle = Harness()
    idle.drain()
    idle.strategy.stop()
    assert idle.drain() == []
    h = Harness()
    rung = _rung(h, "gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    h.book("gte72lt73f")
    (first,) = h.post_and_accept()
    h.strategy.stop()
    assert [c.client_order_id for c in h.cancels(h.drain())] == [first.order.client_order_id]


def test_nothing_is_posted_after_stop() -> None:
    h = Harness()
    rung = _rung(h, "gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    h.book("gte72lt73f")
    (first,) = h.post_and_accept()
    h.strategy.stop()
    h.drain()
    h.cancel_ack(first.order)
    assert h.submits(h.drain()) == []


def test_the_hard_cancel_alert_cancels_the_station_and_stops_posting() -> None:
    h = Harness()
    rung = _rung(h, "gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    hard = h.ladder.hard_cancel_ns
    assert hard > NOW_NS  # D 09:00 LST: after the permit window (R10-ERRATUM)
    assert hard == int(dt.datetime(2026, 9, 18, 17, 0, tzinfo=dt.UTC).timestamp()) * NS
    h.book("gte72lt73f")
    (first,) = h.post_and_accept()
    h.clock.set_time(hard)
    h.strategy._on_hard_alert(SimpleNamespace(name=f"MAKER-HARD:SFO:{DAY.isoformat()}"))
    assert [c.client_order_id for c in h.cancels(h.drain())] == [first.order.client_order_id]
    h.book("gte72lt73f", bids=(("0.06", 10),))
    assert h.submits(h.drain()) == []


def test_the_hard_cancel_alert_is_scheduled_at_the_ladders_hard_cancel_instant() -> None:
    h = Harness()
    h.install(lambda ctx: want())
    h.advance_to(h.ladder.hard_cancel_ns)
    assert h.ladder.hard_cancelled is True


def test_the_poll_timer_queries_every_live_rest_in_flight_or_accepted() -> None:
    h = Harness()
    accepted_rung, pending_rung = _rung(h, "gte70lt71f"), _rung(h, "gte72lt73f")
    state = {"both": False}
    h.install(
        lambda ctx: (
            want((accepted_rung, 89), (pending_rung, 88))
            if state["both"]
            else want((accepted_rung, 89))
        )
    )
    h.book("gte70lt71f")
    h.post_and_accept()
    state["both"] = True
    h.book("gte72lt73f")  # submitted, never accepted
    (pending,) = h.submits(h.drain())
    h.mark_submitted(pending)
    h.advance(31)
    queried = {q.client_order_id for q in h.queries(h.drain())}
    assert queried == {
        h.ladder.rests[accepted_rung].client_order_id,
        h.ladder.rests[pending_rung].client_order_id,
    }
    assert h.ladder.rests[pending_rung].state is RestState.SUBMITTED


def test_a_handler_failure_never_raises() -> None:
    h = Harness()
    rung = _rung(h, "gte72lt73f")

    def boom(ctx: object) -> Decision:
        raise RuntimeError("selector blew up")

    h.install(boom)
    h.book("gte72lt73f")  # must not raise (L-16)
    assert h.drain() == []
    assert rung not in h.ladder.rests


def test_current_yes_instrument_slug_feeds_the_fee_drift_probe() -> None:
    h = Harness()
    slug = h.strategy.current_yes_instrument_slug()
    assert slug is not None and slug.startswith("tc-temp-sfohigh-2026-09-18-")
    assert Harness(with_no_legs=False).strategy.current_yes_instrument_slug() is None


def test_a_cached_instrument_without_known_weather_facts_is_not_a_rung() -> None:
    h = Harness(start=False)
    first = h.cache.instrument(yes_id("SFO", "gte72lt73f"))
    assert first is not None
    bare = BinaryOption.from_dict({**BinaryOption.to_dict(first), "info": {}})
    h.cache.add_instrument(bare)  # replaces the rung's instrument with one that has no facts
    h.strategy.start()
    assert h.rung("gte72lt73f") not in h.ladder.rungs
    assert h.strategy.counters["rung_facts_unavailable"] == 1


def test_instrument_info_gives_the_same_rung_edges_as_the_simulators_slug_grammar() -> None:
    """The live ladder reads ``instrument.info``; the simulator parsed the slug. They must agree."""
    from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
    from breezy.domain.weather_bucket_facts import read_weather_bucket_facts
    from tests.unit.polymarket_us_exec_shapes import build_instrument

    instrument = build_instrument()  # a captured venue market, parsed by the real adapter
    assert read_weather_bucket_facts(instrument.info) == bucket_facts_from_instrument_id(
        str(instrument.id)
    )


def test_a_no_position_already_open_on_a_rung_counts_toward_max_rungs_after_a_relaunch() -> None:
    from nautilus_trader.common.factories import OrderFactory
    from nautilus_trader.model.enums import LiquiditySide, OmsType
    from nautilus_trader.model.identifiers import PositionId, StrategyId
    from nautilus_trader.model.objects import Price
    from nautilus_trader.model.position import Position
    from nautilus_trader.test_kit.stubs.events import TestEventStubs

    from tests.strategy.no_ladder_maker.maker_strategy_support import ACCOUNT

    h = Harness(start=False)
    no = h.cache.instrument(no_id("SFO", "gte72lt73f"))
    assert no is not None
    setup = OrderFactory(trader_id=TRADER, strategy_id=StrategyId("SETUP-X"), clock=h.clock)
    order = setup.limit(
        instrument_id=no.id,
        order_side=OrderSide.BUY,
        quantity=no.make_qty(1),
        price=Price.from_str("0.89"),
    )
    fill = TestEventStubs.order_filled(
        order,
        no,
        account_id=ACCOUNT,
        liquidity_side=LiquiditySide.MAKER,
        position_id=PositionId("P-1"),
        ts_event=NOW_NS,
    )
    h.cache.add_position(Position(instrument=no, fill=fill), OmsType.NETTING)
    h.strategy.start()
    assert h.ladder.held == {h.rung("gte72lt73f")}
    wants = [h.rung(b) for b in ("gte68lt69f", "gte70lt71f", "gte72lt73f")]
    h.install(lambda ctx: want(*[(r, 89 - i) for i, r in enumerate(wants)]))
    for band in ("gte68lt69f", "gte70lt71f"):
        h.book(band)
    posted = h.submits(h.drain())
    assert [str(c.order.instrument_id) for c in posted] == [str(no_id("SFO", "gte68lt69f"))], (
        "one held rung + one live rung == MAX_RUNGS: the third is not posted"
    )


def test_nothing_is_posted_before_the_window_opens_at_d_minus_1_1650z() -> None:
    """Live window = sim window (plan r2 D4): D-1 16:50Z to the permit end."""
    opens = int(dt.datetime(2026, 9, 17, 16, 50, tzinfo=dt.UTC).timestamp()) * NS
    h = Harness(now_ns=opens - 600 * NS)
    rung = _rung(h, "gte72lt73f")
    h.install(lambda ctx: want((rung, 89)))
    assert h.ladder.window_open_ns == opens
    h.book("gte72lt73f")
    assert h.drain() == [] and h.strategy.counters["refused_before_window"] == 1
    h.advance_to(opens)
    h.book("gte72lt73f", bids=(("0.06", 10),))
    assert len(h.submits(h.drain())) == 1
