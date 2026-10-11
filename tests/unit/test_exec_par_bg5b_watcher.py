"""EXEC-PAR BG-5b: the stage evaluator inside ``BreakerWatcherActor`` (and K=1 neutrality)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.component import TestClock
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.runtime.breaker_watcher import (
    BreakerWatcherActor,
    ExecRefusalAlertActor,
    build_exec_watcher,
)
from breezy.runtime.exec_par_constants import EXEC_PAR_MAX_CONCURRENT_INTENTS
from breezy.runtime.exec_par_stage_eval import Verdict, VerdictKind
from breezy.runtime.exec_par_stage_runner import StageEvaluator
from breezy.runtime.health import AlertPayload
from tests.unit.test_exec_par_bg5b_runner import NS, Rig, make_rig, verdict

NOW = 1_800_000_000 * NS


class _Sink:
    def __init__(self) -> None:
        self.emitted: list[AlertPayload] = []

    def emit(self, payload: AlertPayload) -> None:
        self.emitted.append(payload)


@dataclass
class _Client:
    contradiction_events_total: int = 0
    duplicate_suspect_total: int = 0
    ambiguous_notional_breaker_tripped: bool = False
    pass_ns: int = NOW
    open_intent_ages: tuple[tuple[str, str, int], ...] = ()
    held_position_slugs: tuple[str, ...] = ()
    unreadable_slot_keys: tuple[str, ...] = ()
    k_forced_to_1_reason: str | None = None
    stuck_refusals_after_settle_failure_total: int = 0
    no_fill_retire_refusals_total: int = 0

    @property
    def resolver_last_pass_ns(self) -> int:
        return self.pass_ns


class _Exploding:
    """Ports whose every attribute access fails: proves K=1 never touches the evaluator."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"K=1 touched the stage-eval ports: {name}")


def _watcher(
    rig: Rig, *, sink: _Sink | None = None, latch: object | None = None
) -> tuple[BreakerWatcherActor, _Sink, TestClock]:
    the_sink = sink if sink is not None else _Sink()
    clock = TestClock()
    clock.set_time(rig.clock.ns)
    actor = BreakerWatcherActor(
        latch=latch if latch is not None else rig.latch,  # type: ignore[arg-type]
        alert_sink=the_sink,
        stage_eval_ports=rig.ports,
    )
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    actor.bind_client(lambda: _Client())
    return actor, the_sink, clock


def _rig(tmp_path: Path, **kw: object):  # type: ignore[no-untyped-def]
    return make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS), **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# K=1 neutrality
# ---------------------------------------------------------------------------


def test_production_k_is_one_and_the_k1_watcher_is_not_the_breaker() -> None:
    assert EXEC_PAR_MAX_CONCURRENT_INTENTS == 1
    sink = _Sink()
    watcher = build_exec_watcher(
        EXEC_PAR_MAX_CONCURRENT_INTENTS,
        latch=object(),  # type: ignore[arg-type]
        alert_sink=sink,
        stage_eval_ports=_Exploding(),  # type: ignore[arg-type]
    )
    assert type(watcher) is ExecRefusalAlertActor
    assert not isinstance(watcher, BreakerWatcherActor)
    assert not hasattr(watcher, "stage_evaluator")


@pytest.mark.asyncio
async def test_k1_watcher_with_stage_eval_ports_ticks_without_any_store_write() -> None:
    class _Latch:
        def write_breaker_heartbeat(self, *, hb_ns: int, resolver_pass_ns: int) -> None:
            raise AssertionError("K=1 wrote a heartbeat")

        def write_breaker_halt(self, reason: str, *, ts_ns: int) -> None:
            raise AssertionError("K=1 wrote a halt")

    watcher = build_exec_watcher(
        1,
        latch=_Latch(),
        alert_sink=_Sink(),
        stage_eval_ports=_Exploding(),  # type: ignore[arg-type]
    )
    clock = TestClock()
    clock.set_time(NOW)
    watcher.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=TestComponentStubs.msgbus(),
        cache=TestComponentStubs.cache(),
        clock=clock,
    )
    watcher.bind_client(lambda: _Client())
    assert await watcher.tick() is True
    watcher.on_stop()  # nothing to cancel, nothing to touch


def test_k_greater_than_one_arms_the_evaluator_only_when_given_ports(tmp_path: Path) -> None:
    class _Latch:
        def write_breaker_heartbeat(self, *, hb_ns: int, resolver_pass_ns: int) -> None: ...
        def write_breaker_halt(self, reason: str, *, ts_ns: int) -> None: ...
        def write_amendment(self, record: object) -> None: ...

    bare = build_exec_watcher(2, latch=_Latch(), alert_sink=_Sink())
    assert isinstance(bare, BreakerWatcherActor) and bare.stage_evaluator is None
    with _rig(tmp_path) as rig:
        armed = build_exec_watcher(
            2,
            latch=rig.latch,
            alert_sink=_Sink(),
            stage_eval_ports=rig.ports,
        )
        assert isinstance(armed, BreakerWatcherActor)
        assert isinstance(armed.stage_evaluator, StageEvaluator)


# ---------------------------------------------------------------------------
# K>1 wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tick_starts_the_boot_pass_as_a_detached_task_and_does_not_wait_for_it(
    tmp_path: Path,
) -> None:
    never = asyncio.Event()

    async def ready() -> None:
        await never.wait()

    with _rig(tmp_path, ready=ready) as rig:
        actor, _, _ = _watcher(rig)
        assert await asyncio.wait_for(actor.tick(), 2) is True  # tick returns; pass still hung
        ev = actor.stage_evaluator
        assert ev is not None and ev.task is not None and not ev.task.done()
        assert rig.latch.read_breaker_record() is not None  # the heartbeat was written
        actor.on_stop()
        await asyncio.wait({ev.task}, timeout=5)
        assert ev.task.cancelled()


@pytest.mark.asyncio
async def test_a_completed_pass_stamps_with_the_latch_boot_ns(tmp_path: Path) -> None:
    with _rig(tmp_path) as rig:
        actor, _, _ = _watcher(rig)
        await actor.tick()
        ev = actor.stage_evaluator
        assert ev is not None and ev.task is not None
        await ev.task
        stamp = rig.latch.read_stage_eval_stamp()
        assert stamp is not None and stamp.boot_ns == rig.latch.boot_ns
        assert await actor.tick() is True


@pytest.mark.asyncio
async def test_on_stop_cancels_the_outstanding_pass_task(tmp_path: Path) -> None:
    never = asyncio.Event()

    async def refresh() -> None:
        await never.wait()

    with _rig(tmp_path, refresh=refresh) as rig:
        actor, _, _ = _watcher(rig)
        await actor.tick()
        ev = actor.stage_evaluator
        assert ev is not None and ev.task is not None
        await asyncio.sleep(0.05)
        actor.on_stop()
        await asyncio.wait({ev.task}, timeout=5)
        assert ev.task.cancelled()
        assert rig.latch.read_breaker_record() is not None
        record = rig.latch.read_breaker_record()
        assert record is not None and not record.is_halted  # a stop is not a task death


@pytest.mark.asyncio
async def test_a_pending_integrity_halt_withholds_the_heartbeat_but_keeps_ticking(
    tmp_path: Path,
) -> None:
    verdicts: list[Verdict] = [verdict(VerdictKind.FAIL, "stage_eval_fail:gappy")]
    with make_rig(tmp_path, evaluate=lambda s: verdicts[0]) as rig:
        real_halt = rig.latch.write_breaker_halt
        calls = {"fail": True}

        class _FlakyLatch:
            def __getattr__(self, name: str) -> object:
                return getattr(rig.latch, name)

            def write_breaker_halt(self, reason: str, *, ts_ns: int) -> None:
                if calls["fail"]:
                    raise OSError("store down")
                real_halt(reason, ts_ns=ts_ns)

        actor, _, _ = _watcher(rig, latch=_FlakyLatch())
        await actor.tick()  # starts the pass
        ev = actor.stage_evaluator
        assert ev is not None and ev.task is not None
        await ev.task
        # the FAIL halt write raised: pending, so no heartbeat is written
        hb_before = rig.latch.read_breaker_record()
        assert await actor.tick() is False
        assert not ev.heartbeat_ok
        assert rig.latch.read_breaker_record() == hb_before
        calls["fail"] = False
        # the next tick retries the halt, latches it, and (resolved) resumes the heartbeat
        assert await actor.tick() is True
        record = rig.latch.read_breaker_record()
        assert record is not None and record.halted_reason == "stage_eval_fail:gappy"


@pytest.mark.asyncio
async def test_evaluator_alerts_go_through_the_watchers_sink(tmp_path: Path) -> None:
    v = verdict(VerdictKind.PROMOTION_ELIGIBLE, look_number=1)
    with make_rig(tmp_path, evaluate=lambda s: v) as rig:
        sink = _Sink()
        actor, _, _ = _watcher(rig, sink=sink)
        await actor.tick()
        ev = actor.stage_evaluator
        assert ev is not None and ev.task is not None
        await ev.task
        events = [p.event for p in sink.emitted]
        assert "EXEC_PAR_STAGE_PROMOTION_ELIGIBLE" in events
        assert {p.site for p in sink.emitted if p.event.startswith("EXEC_PAR_STAGE")} == {
            "exec_par_watcher"
        }


@pytest.mark.asyncio
async def test_existing_triggers_still_halt_with_the_evaluator_attached(tmp_path: Path) -> None:
    with _rig(tmp_path) as rig:
        actor, _, _ = _watcher(rig)
        actor.bind_client(lambda: _Client(contradiction_events_total=1))
        await actor.tick()
        record = rig.latch.read_breaker_record()
        assert record is not None and record.halted_reason == "contradiction"


def test_actor_subclass_relationship_is_unchanged() -> None:
    assert issubclass(BreakerWatcherActor, Actor)
    assert issubclass(BreakerWatcherActor, ExecRefusalAlertActor)
