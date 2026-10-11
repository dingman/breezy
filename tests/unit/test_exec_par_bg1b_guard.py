"""EXEC-PAR BG-1b: failed ingest events are retried, gappy-marked and never raised to the msgbus."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.runtime.breaker_watcher import BreakerWatcherActor
from breezy.runtime.exec_par_counter_ingest import ExecParCounterError, ExecParCounterIngest
from breezy.runtime.exec_par_ingest_guard import FAULT_RING, QUEUE_CAP, IngestGuard
from breezy.runtime.submit_intent import SubmitIntentLatch, open_submit_intent_latch
from tests.unit.test_exec_par_bg1b_ingest import (
    ARM,
    DAY,
    SEC,
    _day_of,
    _filled,
    _HbLatch,
    _Rig,
    _Sink,
    _submitted,
    _watcher,
)


class _SelStore:
    """Fails ``set`` for keys under any prefix in ``fail_prefixes`` (selective outage)."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}
        self.fail_prefixes: tuple[str, ...] = ()

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(k for k in self.data if k.startswith(prefix))

    def set(self, key: str, value: bytes) -> None:
        if any(f"/exec_par/{p}" in key for p in self.fail_prefixes):
            raise OSError("down")
        self.data[key] = value


@contextmanager
def _latch(tmp_path: Path, store: _SelStore) -> Iterator[SubmitIntentLatch]:
    with open_submit_intent_latch(store, tmp_path / "s.db") as latch:
        yield latch


def _ingest(latch: SubmitIntentLatch, **kw: Any) -> ExecParCounterIngest:
    kw.setdefault("climate_day_of", _day_of)
    kw.setdefault("theta_of", lambda ts: Decimal("0.0695"))
    return ExecParCounterIngest(store=latch, **kw)


def test_a_failed_anchor_write_is_retried_and_the_later_fill_lands(tmp_path: Path) -> None:
    rig = _Rig()
    order = rig.order()
    store = _SelStore()
    with _latch(tmp_path, store) as latch:
        guard = IngestGuard(_ingest(latch))
        store.fail_prefixes = ("order/", "gappy/")
        guard.handle(_submitted(order), rig.cache.order, ARM)
        assert (guard.fault_count, guard.pending) == (1, 1)
        assert guard.gappy_write_failures == 1  # the gappy mark also failed: counted
        store.fail_prefixes = ()
        guard.handle(_filled(order), rig.cache.order, ARM + SEC)  # no anchor yet: queued
        assert guard.pending == 2
        guard.retry(rig.cache.order, ARM + 2 * SEC)  # FIFO: the anchor first, then the fill
        assert guard.pending == 0
        assert len(latch.read_order_anchors(DAY)) == 1
        assert len(latch.read_fills(DAY)) == 1
        assert guard.fault_count == 2  # monotonic: a successful retry never lowers it


def test_every_fault_writes_a_gappy_mark_for_the_event_day(tmp_path: Path) -> None:
    rig = _Rig()
    order = rig.order()
    with _latch(tmp_path, _SelStore()) as latch:
        guard = IngestGuard(_ingest(latch))
        guard.handle(_filled(order), rig.cache.order, ARM + SEC)  # fill with no anchor
        assert guard.fault_count == 1 and guard.gappy_write_failures == 0
        assert [m.day for m in latch.read_gappy_marks()] == [DAY]


def test_the_window_is_repaired_when_only_the_window_write_failed(tmp_path: Path) -> None:
    rig = _Rig()
    order = rig.order()
    store = _SelStore()
    with _latch(tmp_path, store) as latch:
        guard = IngestGuard(_ingest(latch))
        store.fail_prefixes = ("window/",)
        guard.handle(_submitted(order), rig.cache.order, ARM)
        assert len(latch.read_order_anchors(DAY)) == 1  # anchor landed
        assert latch.read_window_peaks(DAY) == ()
        store.fail_prefixes = ()
        guard.retry(rig.cache.order, ARM + 5 * SEC)
        (window,) = latch.read_window_peaks(DAY)
        assert window.orders == 1
        guard.handle(_submitted(order), rig.cache.order, ARM + 6 * SEC)  # replay: not doubled
        assert latch.read_window_peaks(DAY)[0].orders == 1


def test_queue_overflow_drops_the_oldest_marks_its_day_gappy_and_counts(tmp_path: Path) -> None:
    rig = _Rig()
    orders = [rig.order() for _ in range(3)]
    store = _SelStore()
    with _latch(tmp_path, store) as latch:
        guard = IngestGuard(_ingest(latch), queue_cap=2)
        store.fail_prefixes = ("order/",)
        for i, order in enumerate(orders):
            guard.handle(_submitted(order, ARM + i), rig.cache.order, ARM + i)
        assert (guard.pending, guard.overflow_count) == (2, 1)
        assert [m.day for m in latch.read_gappy_marks()] == [DAY]
    assert QUEUE_CAP == 1000


def test_untyped_raises_from_injected_callables_are_contained_and_chained(tmp_path: Path) -> None:
    rig = _Rig()
    order = rig.order()

    def bad_theta(ts: int) -> Decimal | None:
        raise RuntimeError("theta boom")

    def bad_station(slug: str) -> str:
        raise RuntimeError("station boom")

    with _latch(tmp_path, _SelStore()) as latch:
        guard = IngestGuard(
            _ingest(latch, station_of=bad_station, open_cost_flag_of=lambda s, d: True)
        )
        guard.handle(_submitted(order), rig.cache.order, ARM)  # station_of raises
        assert guard.fault_count == 1
        (fault,) = guard.recent_faults
        assert isinstance(fault, ExecParCounterError)
        assert isinstance(fault.__cause__, RuntimeError)
        guard2 = IngestGuard(_ingest(latch, theta_of=bad_theta))
        guard2.handle(_submitted(order), rig.cache.order, ARM)
        guard2.handle(_filled(order), rig.cache.order, ARM + SEC)
        assert guard2.fault_count == 1
        assert isinstance(guard2.recent_faults[0].__cause__, RuntimeError)


def test_fault_ring_keeps_the_last_twenty(tmp_path: Path) -> None:
    rig = _Rig()
    with _latch(tmp_path, _SelStore()) as latch:
        guard = IngestGuard(_ingest(latch), queue_cap=QUEUE_CAP)
        for i in range(FAULT_RING + 5):
            guard.handle(_filled(rig.order(), ARM + i), rig.cache.order, ARM + i)
        assert guard.fault_count == FAULT_RING + 5
        assert len(guard.recent_faults) == FAULT_RING == 20


# -- the watcher -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_exception_reaches_the_msgbus_and_the_fault_is_counted(tmp_path: Path) -> None:
    rig = _Rig()
    order = rig.order()
    with _latch(tmp_path, _SelStore()) as latch:
        ingest = _ingest(latch, theta_of=lambda ts: (_ for _ in ()).throw(RuntimeError("x")))
        actor = _watcher(rig, ingest)
        actor.on_start()
        try:
            actor.msgbus.publish("events.order.S-1", _submitted(order))
            actor.msgbus.publish("events.order.S-1", _filled(order))  # raises untyped inside
            assert actor.ingest_fault_count == 1
            assert isinstance(actor.last_ingest_fault, ExecParCounterError)
            assert len(actor.recent_ingest_faults) == 1
        finally:
            actor.on_stop()


class _RecLatch(_HbLatch):
    def __init__(self) -> None:
        self.halts: list[str] = []
        self.heartbeats: list[int] = []

    def write_breaker_heartbeat(self, *, hb_ns: int, resolver_pass_ns: int) -> None:
        self.heartbeats.append(hb_ns)

    def write_breaker_halt(self, reason: str, *, ts_ns: int) -> None:
        self.halts.append(reason)


class _TrippedClient:
    contradiction_events_total = 0
    duplicate_suspect_total = 0
    ambiguous_notional_breaker_tripped = True
    resolver_last_pass_ns = 0
    open_intent_ages: tuple[tuple[str, str, int], ...] = ()
    held_position_slugs: tuple[str, ...] = ()
    unreadable_slot_keys: tuple[str, ...] = ()
    k_forced_to_1_reason = None
    stuck_refusals_after_settle_failure_total = 0
    no_fill_retire_refusals_total = 0


class _ExplodingMarks:
    def ambiguous_marks_pending(self) -> frozenset[tuple[str, str]]:
        raise RuntimeError("ledger boom")

    def ack_ambiguous_marks(self, marks: Any) -> None: ...


@pytest.mark.asyncio
async def test_the_halt_is_written_before_ingest_and_an_ingest_raise_cannot_stop_it(
    tmp_path: Path,
) -> None:
    rig = _Rig()
    rec = _RecLatch()
    with _latch(tmp_path, _SelStore()) as latch:
        actor = BreakerWatcherActor(
            latch=rec,
            alert_sink=_Sink(),
            counters=_ingest(latch),
            ambiguous_marks=_ExplodingMarks(),
        )
        actor.register_base(
            portfolio=TestComponentStubs.portfolio(),
            msgbus=TestComponentStubs.msgbus(),
            cache=rig.cache,
            clock=rig.clock,
        )
        actor.bind_client(lambda: _TrippedClient())
        assert await actor.tick() is True
        assert rec.halts == ["ambiguous_notional"]
        assert len(rec.heartbeats) == 1
        assert actor.ingest_fault_count == 1
        assert len(actor.recent_ingest_faults) == 1
