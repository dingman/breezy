"""EXEC-PAR BG-1b: counter ingestion (pure ingest class and the watcher's order-event path)."""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.common.factories import OrderFactory
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import LiquiditySide, OrderSide, OrderType, TimeInForce
from nautilus_trader.model.events import OrderDenied, OrderFilled, OrderSubmitted
from nautilus_trader.model.identifiers import (
    AccountId,
    InstrumentId,
    StrategyId,
    TradeId,
    TraderId,
    VenueOrderId,
)
from nautilus_trader.model.objects import Money, Price, Quantity
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.runtime import breaker_watcher
from breezy.runtime.breaker_watcher import BreakerWatcherActor, ExecParStorePort
from breezy.runtime.exec_par_counter_ingest import (
    CounterAttributionError,
    CounterWriteError,
    ExecParCounterError,
    ExecParCounterIngest,
)
from breezy.runtime.exec_par_telemetry import WINDOW_NS
from breezy.runtime.submit_intent import SubmitIntentLatch, open_submit_intent_latch

SEC = 1_000_000_000
ARM = 1_700_000_000 * SEC + 123
DAY = "2026-10-11"
SLUG = "aec-nyc-high-2026-10-11-t70"
IID = InstrumentId.from_str(f"{SLUG}.POLYMARKET_US")
THETA = Decimal("0.0695")


class _Store:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.fail_set = False

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(k for k in self.data if k.startswith(prefix))

    def set(self, key: str, value: bytes) -> None:
        if self.fail_set:
            raise OSError("down")
        self.data[key] = value


@contextmanager
def _latch(tmp_path: Path, store: _Store | None = None) -> Iterator[SubmitIntentLatch]:
    with open_submit_intent_latch(store or _Store(), tmp_path / "s.db") as latch:
        yield latch


def _day_of(slug: str, ns: int) -> str:
    return DAY if ns >= ARM else "2026-10-10"


def _ingest(latch: SubmitIntentLatch, **kw: Any) -> ExecParCounterIngest:
    kw.setdefault("climate_day_of", _day_of)
    kw.setdefault("theta_of", lambda ts: THETA)
    return ExecParCounterIngest(store=latch, **kw)


def _post(ing: ExecParCounterIngest, coid: str = "O-1", ask: str = "0.40", at: int = ARM) -> bool:
    return ing.record_posted(
        client_order_id=coid,
        slug=SLUG,
        decision_ask=Decimal(ask),
        qty=Decimal(10),
        arm_ns=at,
    )


# -- posted entries, decision ask, windows -------------------------------


def test_posted_entry_persists_the_decision_ask_and_attributes_by_arm_time(tmp_path: Path) -> None:
    with _latch(tmp_path) as latch:
        ing = _ingest(latch)
        assert _post(ing) is True
        row = latch.read_order_anchor("O-1")
        assert row is not None
        assert (row.decision_ask, row.qty, row.notional) == ("0.40", "10", "4.00")
        assert (row.day, row.arm_ns, row.slug) == (DAY, ARM, SLUG)
        # the day is the ARM day even when the event arrives long after midnight
        assert _post(ing, "O-0", at=ARM - 10 * SEC * 3600) is True
        anchor = latch.read_order_anchor("O-0")
        assert anchor is not None and anchor.day == "2026-10-10"


def test_replayed_event_is_idempotent_and_does_not_double_count_the_window(tmp_path: Path) -> None:
    with _latch(tmp_path) as latch:
        ing = _ingest(latch)
        assert _post(ing) is True
        assert _post(ing) is False
        (window,) = latch.read_window_peaks(DAY)
        assert window.orders == 1
        assert window.window_start_ns == ARM - ARM % WINDOW_NS


def test_orders_within_one_five_second_window_share_it(tmp_path: Path) -> None:
    with _latch(tmp_path) as latch:
        ing = _ingest(latch)
        base = ARM - ARM % WINDOW_NS + WINDOW_NS
        for i, at in enumerate((base + 1, base + SEC, base + 6 * SEC)):
            _post(ing, f"O-{i}", at=at)
        counts = sorted(w.orders for w in latch.read_window_peaks(DAY))
        assert counts == [1, 2]


@pytest.mark.parametrize("bad", [None, Decimal(0), Decimal("-0.1"), Decimal("1.5")])
def test_missing_or_out_of_range_decision_ask_is_a_typed_failure_never_zero(
    tmp_path: Path, bad: Decimal | None
) -> None:
    with _latch(tmp_path) as latch:
        ing = _ingest(latch)
        with pytest.raises(CounterAttributionError):
            ing.record_posted(
                client_order_id="O-1", slug=SLUG, decision_ask=bad, qty=Decimal(10), arm_ns=ARM
            )
        assert latch.read_order_anchor("O-1") is None


def test_missing_arm_time_qty_or_day_is_a_typed_failure(tmp_path: Path) -> None:
    with _latch(tmp_path) as latch:
        ing = _ingest(latch)
        for kw in (
            {"arm_ns": None},
            {"qty": None},
            {"qty": Decimal(0)},
        ):
            args: dict[str, Any] = {
                "client_order_id": "O-1",
                "slug": SLUG,
                "decision_ask": Decimal("0.4"),
                "qty": Decimal(1),
                "arm_ns": ARM,
                **kw,
            }
            with pytest.raises(CounterAttributionError):
                ing.record_posted(**args)
        for bad_day in (None, "", 5):
            broken = _ingest(latch, climate_day_of=lambda s, n, d=bad_day: d)
            with pytest.raises(CounterAttributionError):
                _post(broken)
        raising = _ingest(latch, climate_day_of=lambda s, n: (_ for _ in ()).throw(KeyError(s)))
        with pytest.raises(CounterAttributionError):
            _post(raising)
        assert latch.read_order_anchors(DAY) == ()


def test_write_failure_surfaces_as_a_typed_error_without_values(tmp_path: Path) -> None:
    store = _Store()
    with _latch(tmp_path, store) as latch:
        ing = _ingest(latch)
        store.fail_set = True
        with pytest.raises(CounterWriteError) as info:
            _post(ing)
        assert isinstance(info.value, ExecParCounterError)
        assert "0.40" not in str(info.value)
        assert isinstance(info.value.__cause__, OSError)


# -- open cost flag seam ---------------------------------------------------


def test_open_cost_flag_seam_is_value_free_bool_and_absent_when_unwired(tmp_path: Path) -> None:
    with _latch(tmp_path) as latch:
        _post(_ingest(latch))
        assert latch.read_open_cost_flags(DAY) == ()  # no seam: no row, never a False default
        seen: list[tuple[str, str]] = []

        def flag(station: str, day: str) -> bool:
            seen.append((station, day))
            return True

        ing = _ingest(latch, open_cost_flag_of=flag, station_of=lambda slug: "NYC")
        _post(ing, "O-2")
        (row,) = latch.read_open_cost_flags(DAY)
        assert (row.station_day, row.exceeded) == (f"NYC@{DAY}", True)
        assert seen == [("NYC", DAY)]


def test_open_cost_flag_raise_or_non_bool_is_a_typed_failure(tmp_path: Path) -> None:
    with _latch(tmp_path) as latch:
        for fn in (lambda s, d: 1, lambda s, d: None, lambda s, d: 1 / 0):
            ing = _ingest(latch, open_cost_flag_of=fn)
            with pytest.raises(CounterAttributionError):
                _post(ing, "O-9")
        assert latch.read_open_cost_flags(DAY) == ()


# -- denial ------------------------------------------------------


def test_denial_attributed_by_event_time_and_labelled(tmp_path: Path) -> None:
    with _latch(tmp_path) as latch:
        ing = _ingest(latch)
        assert ing.record_denial(client_order_id="O-5", slug=SLUG, reason="k-full", ts_ns=ARM + 1)
        (row,) = latch.read_denials(DAY)
        assert (row.reason, row.client_order_id, row.arm_ns) == ("k-full", "O-5", ARM + 1)
        with pytest.raises(CounterAttributionError):
            ing.record_denial(client_order_id="O-6", slug=SLUG, reason="", ts_ns=ARM)


# -- fills ---------------------------------------------------------------


def _fill(ing: ExecParCounterIngest, **kw: Any) -> bool:
    args: dict[str, Any] = {
        "trade_id": "TR-1",
        "client_order_id": "O-1",
        "qty": Decimal(10),
        "px": Decimal("0.42"),
        "commission": Decimal("0.17"),
        "ts_event_ns": ARM + SEC,
        **kw,
    }
    return ing.record_fill(**args)


def test_fill_records_slippage_against_the_durable_decision_ask_and_both_fees(
    tmp_path: Path,
) -> None:
    with _latch(tmp_path) as latch:
        ing = _ingest(latch)
        _post(ing, ask="0.40")
        assert _fill(ing) is True
        (row,) = latch.read_fills(DAY)
        assert Decimal(row.slippage) == Decimal("0.02")
        assert Decimal(row.fee_realized) == Decimal("0.17")
        # unrounded exact: theta * C * p * (1 - p), no quantisation
        assert Decimal(row.fee_exact) == THETA * 10 * Decimal("0.42") * Decimal("0.58")
        assert Decimal(row.fee_theta) == THETA
        assert (row.day, row.arm_ns) == (DAY, ARM)
        assert _fill(ing) is False  # replay


def test_fill_attribution_follows_arm_day_even_when_the_fill_lands_next_day(
    tmp_path: Path,
) -> None:
    with _latch(tmp_path) as latch:
        ing = _ingest(latch)
        _post(ing, at=ARM)
        _fill(ing, ts_event_ns=ARM + 40 * 3600 * SEC)
        assert len(latch.read_fills(DAY)) == 1


def test_fill_without_an_anchor_commission_or_theta_fails_typed(tmp_path: Path) -> None:
    with _latch(tmp_path) as latch:
        ing = _ingest(latch)
        with pytest.raises(CounterAttributionError):  # no decision ask on record
            _fill(ing)
        _post(ing)
        with pytest.raises(CounterAttributionError):
            _fill(ing, commission=None)
        with pytest.raises(CounterAttributionError):
            _fill(ing, qty=None)
        no_theta = _ingest(latch, theta_of=lambda ts: None)
        with pytest.raises(CounterAttributionError):
            _fill(no_theta)
        assert latch.read_fills(DAY) == ()


# -- gappy marks ----------------------------------------------------------


def test_gappy_mark_write_and_validation(tmp_path: Path) -> None:
    with _latch(tmp_path) as latch:
        ing = _ingest(latch)
        assert ing.mark_gappy(day=DAY, cause="heartbeat_lapse", ts_ns=ARM) is True
        assert [m.day for m in latch.read_gappy_marks()] == [DAY]
        with pytest.raises(CounterAttributionError):
            ing.mark_gappy(day="", cause="x", ts_ns=ARM)


# -- native events -------------------------------------------------------


class _Rig:
    """A real Nautilus cache + order factory; orders are real ``LimitOrder`` objects."""

    def __init__(self) -> None:
        self.cache = TestComponentStubs.cache()
        self.clock = TestClock()
        self.clock.set_time(ARM)
        self.factory = OrderFactory(
            trader_id=TraderId("T-001"), strategy_id=StrategyId("S-1"), clock=self.clock
        )

    def order(self, side: OrderSide = OrderSide.BUY, px: str = "0.40") -> Any:
        order = self.factory.limit(
            instrument_id=IID,
            order_side=side,
            quantity=Quantity.from_int(10),
            price=Price.from_str(px),
            time_in_force=TimeInForce.IOC,
        )
        self.cache.add_order(order, position_id=None)
        return order


def _submitted(order: Any, ts: int = ARM) -> OrderSubmitted:
    return OrderSubmitted(
        TraderId("T-001"), StrategyId("S-1"), IID, order.client_order_id,
        AccountId("PM-001"), UUID4(), ts, ts,
    )  # fmt: skip


def _filled(order: Any, ts: int = ARM + SEC, trade: str = "TR-1") -> OrderFilled:
    return OrderFilled(
        TraderId("T-001"), StrategyId("S-1"), IID, order.client_order_id, VenueOrderId("V-1"),
        AccountId("PM-001"), TradeId(trade), None, order.side, OrderType.LIMIT,
        Quantity.from_int(10), Price.from_str("0.42"), USD, Money(0.17, USD),
        LiquiditySide.TAKER, UUID4(), ts, ts,
    )  # fmt: skip


def _denied(order: Any) -> OrderDenied:
    return OrderDenied(
        TraderId("T-001"), StrategyId("S-1"), IID, order.client_order_id,
        "OpenExposureBoundExceeded 12.50", UUID4(), ARM,
    )  # fmt: skip


def test_on_event_posts_fills_and_denials_from_native_events(tmp_path: Path) -> None:
    rig = _Rig()
    buy, denied = rig.order(), rig.order()
    with _latch(tmp_path) as latch:
        ing = _ingest(latch)
        ing.on_event(_submitted(buy), rig.cache.order)
        anchor = latch.read_order_anchor(str(buy.client_order_id))
        assert anchor is not None
        assert (anchor.arm_ns, Decimal(anchor.decision_ask), anchor.slug) == (
            ARM,
            Decimal("0.4"),
            SLUG,
        )
        ing.on_event(_filled(buy), rig.cache.order)
        (fill,) = latch.read_fills(DAY)
        assert Decimal(fill.slippage) == Decimal("0.02")
        ing.on_event(_denied(denied), rig.cache.order)
        (denial,) = latch.read_denials(DAY)
        assert denial.reason == "openexposureboundexceeded #"  # number-free label


def test_on_event_ignores_exits_and_unrelated_events(tmp_path: Path) -> None:
    rig = _Rig()
    sell = rig.order(OrderSide.SELL)
    with _latch(tmp_path) as latch:
        ing = _ingest(latch)
        ing.on_event(_submitted(sell), rig.cache.order)
        ing.on_event(_filled(sell), rig.cache.order)
        ing.on_event(_denied(sell), rig.cache.order)
        ing.on_event(object(), rig.cache.order)
        assert latch.read_order_anchors(DAY) == ()
        assert latch.read_fills(DAY) == ()
        assert latch.read_denials(DAY) == ()


def test_on_event_without_a_cached_order_fails_typed(tmp_path: Path) -> None:
    rig, other = _Rig(), _Rig()
    ghost = other.order()
    with _latch(tmp_path) as latch:
        ing = _ingest(latch)
        for event in (_submitted(ghost), _denied(ghost)):
            with pytest.raises(CounterAttributionError):
                ing.on_event(event, rig.cache.order)
        assert latch.read_order_anchors(DAY) == ()


# -- the watcher -----------------------------------------------------------


class _Sink:
    def emit(self, payload: object) -> None:  # pragma: no cover - not exercised
        raise AssertionError("no alert expected")


class _HbLatch:
    def write_breaker_heartbeat(self, *, hb_ns: int, resolver_pass_ns: int) -> None: ...
    def write_breaker_halt(self, reason: str, *, ts_ns: int) -> None: ...


def _watcher(rig: _Rig, ing: ExecParCounterIngest | None) -> BreakerWatcherActor:
    actor = BreakerWatcherActor(latch=_HbLatch(), alert_sink=_Sink(), counters=ing)
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=rig.cache,
        clock=rig.clock,
    )
    return actor


@pytest.mark.asyncio
async def test_watcher_ingests_order_events_from_its_subscription(tmp_path: Path) -> None:
    rig = _Rig()
    order = rig.order()
    with _latch(tmp_path) as latch:
        actor = _watcher(rig, _ingest(latch))
        actor.on_start()
        try:
            actor.msgbus.publish("events.order.S-1", _submitted(order))
            actor.msgbus.publish("events.order.S-1", _filled(order))
            assert len(latch.read_order_anchors(DAY)) == 1
            assert len(latch.read_fills(DAY)) == 1
            assert actor.ingest_fault_count == 0
        finally:
            actor.on_stop()
        # unsubscribed: later events are not ingested
        actor.msgbus.publish("events.order.S-1", _filled(order, trade="TR-2"))
        assert len(latch.read_fills(DAY)) == 1


@pytest.mark.asyncio
async def test_watcher_surfaces_a_write_failure_as_a_typed_fault_not_a_swallowed_debug(
    tmp_path: Path,
) -> None:
    rig = _Rig()
    order = rig.order()
    store = _Store()
    with _latch(tmp_path, store) as latch:
        actor = _watcher(rig, _ingest(latch))
        actor.on_start()
        try:
            store.fail_set = True
            actor.msgbus.publish("events.order.S-1", _submitted(order))
            assert actor.ingest_fault_count == 1
            assert isinstance(actor.last_ingest_fault, CounterWriteError)
        finally:
            actor.on_stop()


@pytest.mark.asyncio
async def test_without_counters_nothing_is_subscribed_so_k1_behaviour_is_unchanged(
    tmp_path: Path,
) -> None:
    rig = _Rig()
    order = rig.order()
    with _latch(tmp_path) as latch:
        actor = _watcher(rig, None)
        actor.on_start()
        try:
            actor.msgbus.publish("events.order.S-1", _submitted(order))
            assert latch.read_order_anchors(DAY) == ()
            assert actor.ingest_fault_count == 0
        finally:
            actor.on_stop()
    k1 = breaker_watcher.build_exec_watcher(1, latch=_HbLatch(), alert_sink=_Sink())
    assert not hasattr(k1, "ingest_fault_count")


def test_store_port_declares_the_counter_writers_and_the_latch_satisfies_it() -> None:
    port = {n for n, _ in inspect.getmembers(ExecParStorePort) if not n.startswith("_")}
    for name in (
        "write_order_anchor",
        "write_denial",
        "write_ambiguous",
        "write_fill",
        "write_open_cost_flag",
        "add_window_order",
        "write_gappy_mark",
        "read_order_anchor",
    ):
        assert name in port
    assert port <= {n for n, _ in inspect.getmembers(SubmitIntentLatch)}
