"""EXEC-PAR BG-6 in ``BreakerWatcherActor``: counter-increase integrity halts, the intraday monitor
inside the tick, D3 heartbeat stop on a halt-write raise, entries-only, and K=1 neutrality.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.runtime.breaker_watcher import (
    BreakerWatcherActor,
    ExecRefusalAlertActor,
    build_exec_watcher,
)
from breezy.runtime.exec_par_intraday import IntradayPorts
from breezy.runtime.exec_par_records import StageEvalStamp
from breezy.runtime.exec_par_stage_eval import VerdictKind
from breezy.runtime.submit_intent import RetirementReason
from tests.unit.test_exec_par_bg1b_guard import _ingest, _latch, _SelStore
from tests.unit.test_exec_par_bg1b_ingest import ARM, _filled, _Rig, _submitted
from tests.unit.test_exec_par_bg5b_runner import BOOT_NS, NS, Rig, d, make_rig, ns_of, verdict
from tests.unit.test_exec_par_bg5b_watcher import NOW, _Client, _Exploding, _Sink
from tests.unit.test_exec_par_bg6_intraday import _Budget, _burst

HOUR = 3600 * NS


class _Latch:
    """Records halts/heartbeats; ``fail_halt`` makes the halt write raise."""

    def __init__(self) -> None:
        self.halts: list[str] = []
        self.heartbeats: list[int] = []
        self.fail_halt = 0

    def write_breaker_heartbeat(self, *, hb_ns: int, resolver_pass_ns: int) -> None:
        self.heartbeats.append(hb_ns)

    def write_breaker_halt(self, reason: str, *, ts_ns: int) -> None:
        if self.fail_halt:
            self.fail_halt -= 1
            raise OSError("injected halt failure")
        self.halts.append(reason)


def _actor(latch: Any, rig: _Rig, ingest: Any, sink: Any) -> BreakerWatcherActor:
    actor = BreakerWatcherActor(latch=latch, alert_sink=sink, counters=ingest)
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=rig.cache,
        clock=rig.clock,
    )
    actor.bind_client(lambda: _Client())
    return actor


# ---------------------------------------------------------------------------
# integration notes 2: any increase of ingest_fault_count / gappy_write_failures halts
# ---------------------------------------------------------------------------


class _Events:
    def __init__(self) -> None:
        self.rig = _Rig()
        self.order = self.rig.order()


@pytest.mark.asyncio
async def test_an_increase_of_ingest_fault_count_is_an_integrity_halt(tmp_path: Path) -> None:
    ev = _Events()
    rec = _Latch()
    with _latch(tmp_path, _SelStore()) as store_latch:
        actor = _actor(rec, ev.rig, _ingest(store_latch), _Sink())
        assert await actor.tick() is True and rec.halts == []  # no fault yet
        guard = actor.ingest_guard
        assert guard is not None
        guard.handle(_filled(ev.order), ev.rig.cache.order, ARM)  # fill with no anchor: a fault
        assert (guard.fault_count, guard.gappy_write_failures) == (1, 0)
        assert await actor.tick() is True
        assert rec.halts == ["ingest_fault"]
        assert len(rec.heartbeats) == 2  # a halt is not a heartbeat stop
        assert await actor.tick() is True
        assert rec.halts == ["ingest_fault"]  # acknowledged: no rewrite while it stays at 1


@pytest.mark.asyncio
async def test_an_increase_of_gappy_write_failures_is_an_integrity_halt_naming_it(
    tmp_path: Path,
) -> None:
    ev = _Events()
    rec = _Latch()
    store = _SelStore()
    with _latch(tmp_path, store) as store_latch:
        actor = _actor(rec, ev.rig, _ingest(store_latch), _Sink())
        guard = actor.ingest_guard
        assert guard is not None
        store.fail_prefixes = ("order/", "gappy/")  # the anchor AND its gappy mark fail
        guard.handle(_submitted(ev.order), ev.rig.cache.order, ARM)
        assert (guard.fault_count, guard.gappy_write_failures) == (1, 1)
        assert await actor.tick() is True
        assert rec.halts == ["ingest_fault,gappy_write_failure"]


@pytest.mark.asyncio
async def test_a_failed_halt_write_leaves_the_increase_pending_and_withholds_the_heartbeat(
    tmp_path: Path,
) -> None:
    ev = _Events()
    rec = _Latch()
    with _latch(tmp_path, _SelStore()) as store_latch:
        actor = _actor(rec, ev.rig, _ingest(store_latch), _Sink())
        guard = actor.ingest_guard
        assert guard is not None
        guard.handle(_filled(ev.order), ev.rig.cache.order, ARM)
        rec.fail_halt = 1
        assert await actor.tick() is False  # D3: the halt write raised, no heartbeat
        assert rec.heartbeats == [] and rec.halts == []
        assert await actor.tick() is True  # retried: still ahead of the acknowledged value
        assert rec.halts == ["ingest_fault"] and len(rec.heartbeats) == 1


@pytest.mark.asyncio
async def test_a_counter_that_never_increases_never_halts(tmp_path: Path) -> None:
    ev = _Events()
    rec = _Latch()
    with _latch(tmp_path, _SelStore()) as store_latch:
        actor = _actor(rec, ev.rig, _ingest(store_latch), _Sink())
        for _ in range(3):
            assert await actor.tick() is True
        assert rec.halts == [] and len(rec.heartbeats) == 3


# ---------------------------------------------------------------------------
# the monitor inside the tick (real latch, stage-eval ports)
# ---------------------------------------------------------------------------


def _rig(tmp_path: Path, **kw: Any) -> Any:
    ports = IntradayPorts(open_cost_port=_Budget(), open_cost_by_station_day=dict)
    return make_rig(
        tmp_path,
        seed=True,
        evaluate=lambda s: verdict(VerdictKind.PASS),
        port_over={"intraday": ports},
        **kw,
    )


def _watcher(rig: Rig) -> tuple[BreakerWatcherActor, TestClock]:
    clock = TestClock()
    clock.set_time(rig.clock.ns)
    actor = BreakerWatcherActor(latch=rig.spy, alert_sink=_Sink(), stage_eval_ports=rig.ports)  # type: ignore[arg-type]
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    actor.bind_client(lambda: _Client())
    assert actor.stage_evaluator is not None
    actor.stage_evaluator.bind_ingest_pending(lambda: 0)
    return actor, clock


async def _finish(actor: BreakerWatcherActor) -> None:
    """Let the boot pass the tick started run to its end before the rig closes."""
    evaluator = actor.stage_evaluator
    assert evaluator is not None and evaluator.task is not None
    await evaluator.task


def _stamp(rig: Rig) -> None:
    rig.latch.write_stage_eval_stamp(StageEvalStamp(rig.clock.ns, BOOT_NS))


@pytest.mark.asyncio
async def test_a_burst_in_the_tick_halts_flags_and_still_heartbeats(tmp_path: Path) -> None:
    with _rig(tmp_path) as rig:
        t0 = ns_of(d(2))
        _burst(rig, [t0 + i for i in range(5)])
        _stamp(rig)
        actor, _ = _watcher(rig)
        assert await actor.tick() is True
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s5_burst"
        assert record.hb_ns == rig.clock.ns  # the heartbeat was written after the halt
        assert rig.latch.read_force_k1_flag().kind.value == "set"
        assert rig.spy.calls[:3] == [
            "write_stop_verdict",
            "write_breaker_halt",
            "write_force_k1_flag",
        ]
        await _finish(actor)


@pytest.mark.asyncio
async def test_d3_a_halt_write_raise_in_the_tick_stops_only_the_heartbeat(tmp_path: Path) -> None:
    with _rig(tmp_path) as rig:
        t0 = ns_of(d(2))
        _burst(rig, [t0 + i for i in range(5)])
        _stamp(rig)
        rig.spy.fail.add("write_breaker_halt")
        actor, _ = _watcher(rig)
        assert await actor.tick() is False
        record = rig.breaker()
        assert record is None  # neither halt nor heartbeat reached the record
        assert rig.latch.read_force_k1_flag().kind.value == "set"  # flag still attempted+written
        assert len(rig.latch.read_stop_verdicts_since(0)) == 1  # marker written first
        # entries are denied by the stale/absent heartbeat path, exits are not
        assert rig.latch.admission_refusal("S-A", True) is None
        await _finish(actor)


@pytest.mark.asyncio
async def test_entries_only_after_an_intraday_halt_exits_and_the_resolver_stay_open(
    tmp_path: Path,
) -> None:
    with _rig(tmp_path) as rig:
        t0 = ns_of(d(2))
        _burst(rig, [t0 + i for i in range(5)])
        _stamp(rig)
        actor, _ = _watcher(rig)
        assert await actor.tick() is True
        assert rig.latch.admission_refusal("S-A", False) == "breaker_halted"
        assert rig.latch.admission_refusal("S-A", True) is None
        fp = "a1b2c3d4" * 8
        intent = rig.latch.arm_slot(fp, slug="S-A", is_exit=True, now_ns=rig.clock.ns)
        retired = rig.latch.retire(
            intent.intent_id, RetirementReason.RESOLVER_NO_ID_NO_FILL, now_ns=rig.clock.ns
        )
        assert retired.intent_id == intent.intent_id
        await _finish(actor)


@pytest.mark.asyncio
async def test_a_stale_stamp_in_the_tick_is_an_integrity_halt_without_the_flag(
    tmp_path: Path,
) -> None:
    with _rig(tmp_path) as rig:
        rig.latch.write_stage_eval_stamp(StageEvalStamp(rig.clock.ns - 27 * HOUR, BOOT_NS))
        actor, _ = _watcher(rig)
        assert await actor.tick() is True
        record = rig.breaker()
        assert record is not None and record.halted_reason == "stage_eval_stamp_stale"
        assert rig.latch.read_force_k1_flag().kind.value == "cleared"
        await _finish(actor)


@pytest.mark.asyncio
async def test_the_stop_class_halt_wins_the_sticky_reason_over_a_stale_stamp(
    tmp_path: Path,
) -> None:
    with _rig(tmp_path) as rig:
        t0 = ns_of(d(2))
        _burst(rig, [t0 + i for i in range(5)])
        rig.latch.write_stage_eval_stamp(StageEvalStamp(rig.clock.ns - 27 * HOUR, BOOT_NS))
        actor, _ = _watcher(rig)
        await actor.tick()
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s5_burst"
        await _finish(actor)


# ---------------------------------------------------------------------------
# K = 1 neutrality
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_k1_watcher_has_no_monitor_and_never_touches_ports_or_the_guard() -> None:
    sink = _Sink()
    watcher = build_exec_watcher(
        1,
        latch=object(),  # type: ignore[arg-type]
        alert_sink=sink,
        stage_eval_ports=_Exploding(),  # type: ignore[arg-type]
    )
    assert type(watcher) is ExecRefusalAlertActor
    assert not hasattr(watcher, "_intraday")
    assert not hasattr(watcher, "ingest_guard")
    clock = TestClock()
    clock.set_time(NOW)
    watcher.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    watcher.bind_client(lambda: _Client())
    assert await watcher.tick() is True  # a K=1 tick reads nothing new and writes nothing
