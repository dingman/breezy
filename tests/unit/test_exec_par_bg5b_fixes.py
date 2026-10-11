"""EXEC-PAR BG-5b fix round: counter exactness, service always runs, unwired guard, settled trigger,
liveness seeding, slow span, one monotonic clock, diagnostics and audit trail."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.runtime.exec_par_reconcile import DayCounts
from breezy.runtime.exec_par_records import (
    EXEC_PAR_PREFIX,
    GappyMark,
    OrderAnchor,
    StageEvalLiveness,
)
from breezy.runtime.exec_par_stage_eval import VerdictKind
from breezy.runtime.exec_par_stage_types import StageSnapshot, Verdict
from tests.unit.test_exec_par_bg5b_runner import NS, Rig, d, make_rig, ns_of, verdict

P = EXEC_PAR_PREFIX


def _pass_rig(tmp_path: Path, **kw: object):  # type: ignore[no-untyped-def]
    return make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS), **kw)  # type: ignore[arg-type]


def _anchor(coid: str, day: str) -> OrderAnchor:
    return OrderAnchor(
        coid, "slug", day, ns_of(day), "0.40", "10", "4", ns_of(day), "event_time", "STN"
    )


# -- item 1: a retried ingest after a rebuild is never counted twice -------------------------


@pytest.mark.asyncio
async def test_reconcile_waits_for_the_ingest_retry_queue_so_a_retried_event_counts_once(
    tmp_path: Path,
) -> None:
    pending = {"n": 1}
    with _pass_rig(tmp_path, seed=True, port_over={"ingest_poll_s": 0.001}) as rig:
        rig.ev.bind_ingest_pending(lambda: pending["n"])
        rig.latch.write_order_anchor(_anchor("O-1", d(1)))
        rig.sources.counts[d(1)] = DayCounts(2, 0, 0, Decimal(8))  # O-2's row is still queued
        rig.ev.service(rig.clock.ns)
        await asyncio.sleep(0.05)
        assert rig.latch.read_reconcile_phase() is not None
        assert rig.events("EXEC_PAR_COUNTER_REBUILT") == []  # no rebuild while a retry is queued
        rig.latch.write_order_anchor(_anchor("O-2", d(1)))  # the retry lands
        pending["n"] = 0
        task = rig.ev.task
        assert task is not None
        await asyncio.wait_for(task, 5)
        assert rig.events("EXEC_PAR_COUNTER_REBUILT") == []  # scan now equals the durable count
        counts = rig.ports.counters.read_day_counts(d(1))
        assert counts is not None and counts.posted_entries == 2  # exact, not 3


@pytest.mark.asyncio
async def test_a_retry_queue_that_never_drains_is_reconcile_stuck(tmp_path: Path) -> None:
    with _pass_rig(tmp_path, seed=True, port_over={"ingest_poll_s": 0.001}) as rig:
        rig.ev.bind_ingest_pending(lambda: 3)
        rig.ev.service(rig.clock.ns)
        await asyncio.sleep(0.05)
        rig.clock.mono += 301 * NS
        rig.ev.service(rig.clock.ns)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "reconcile_stuck"
        rig.ev.cancel()
        await asyncio.sleep(0.05)


# -- item 6: restart keeps the persisted last_ok --------------------------------------------


@pytest.mark.asyncio
async def test_liveness_previous_ok_is_seeded_from_the_store_after_a_restart(
    tmp_path: Path,
) -> None:
    with make_rig(
        tmp_path, evaluate=lambda s: verdict(VerdictKind.FAIL, "stage_eval_fail:x")
    ) as rig:
        rig.latch.write_stage_eval_liveness(StageEvalLiveness(5, 777))
        await rig.run_pass()
        live = rig.latch.read_stage_eval_liveness()
        assert live is not None and live.stage_eval_last_ok_ns == 777  # not overwritten with None
        assert live.stage_eval_last_start_ns == rig.clock.ns


# -- item 7: the slow bound covers the snapshot build too -----------------------------------


@pytest.mark.asyncio
async def test_a_slow_snapshot_build_is_stage_eval_slow(tmp_path: Path) -> None:
    holder: list[Rig] = []

    def slow_baseline() -> None:
        holder[0].clock.mono += 3 * NS  # read while the snapshot is being built

    with _pass_rig(tmp_path) as rig:
        holder.append(rig)
        rig.ev._ports = dataclasses.replace(rig.ports, serial_baseline=slow_baseline)
        await rig.run_pass()
        record = rig.breaker()
        assert record is not None and record.halted_reason == "stage_eval_slow"
        assert rig.latch.read_stage_eval_stamp() is None


# -- item 9: exception TYPE (never the message) reaches the runner log ----------------------


@pytest.mark.asyncio
async def test_a_failed_per_day_read_logs_its_type_and_never_its_message(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.ERROR)
    with make_rig(tmp_path, seed=True) as rig:

        def boom(day: str) -> tuple[object, ...]:
            raise OSError("secret-amount-123.45")

        rig.latch.read_open_cost_flags = boom  # type: ignore[method-assign,assignment]
        await rig.run_pass()
    assert "OSError" in caplog.text and "open_flags" in caplog.text
    assert "secret-amount" not in caplog.text and "123.45" not in caplog.text


def test_clearing_a_gappy_mark_writes_an_audit_row_first(tmp_path: Path) -> None:
    with make_rig(tmp_path) as rig:
        mark = GappyMark(d(1), "ingest_fault", 42, None)
        rig.latch.write_gappy_mark(mark)
        assert rig.latch.delete_gappy_mark(d(1)) is True
        assert P + f"gappy/{d(1)}" not in rig.store.data
        assert P + f"gappy_log/{d(1)}/42" in rig.store.data
        assert rig.latch.delete_gappy_mark(d(1)) is False
        assert [k for k in rig.store.data if "gappy_log" in k] == [P + f"gappy_log/{d(1)}/42"]


# -- item 4: a settled-P&L change triggers a pass --------------------------------------------


@pytest.mark.asyncio
async def test_a_changed_settled_pnl_seq_triggers_exactly_one_extra_pass(tmp_path: Path) -> None:
    seen: list[str] = []
    seq = {"v": 1}

    def evaluate(snap: StageSnapshot) -> Verdict:
        seen.append("pass")
        return verdict(VerdictKind.PASS)

    with make_rig(
        tmp_path,
        evaluate=evaluate,
        port_over={"settled_pnl_seq": lambda: seq["v"]},
    ) as rig:
        await rig.run_pass()
        assert seen == ["pass"]
        rig.ev.service(rig.clock.ns + NS)  # unchanged: nothing
        assert len(seen) == 1
        seq["v"] = 2
        await rig.run_pass(rig.clock.ns + 2 * NS)
        assert len(seen) == 2
        rig.ev.service(rig.clock.ns + 3 * NS)
        assert rig.ev.task is not None and rig.ev.task.done()
        assert len(seen) == 2  # observed once, no repeat


@pytest.mark.asyncio
async def test_a_seq_change_during_a_pass_runs_one_follow_up_after_it(tmp_path: Path) -> None:
    gate = asyncio.Event()
    seen: list[int] = []
    seq = {"v": 1}

    async def refresh() -> None:
        if not seen:
            await gate.wait()

    def evaluate(snap: StageSnapshot) -> Verdict:
        seen.append(1)
        return verdict(VerdictKind.PASS)

    with make_rig(
        tmp_path,
        evaluate=evaluate,
        refresh=refresh,
        port_over={"settled_pnl_seq": lambda: seq["v"]},
    ) as rig:
        rig.ev.service(rig.clock.ns)
        first = rig.ev.task
        seq["v"] = 2
        rig.ev.service(rig.clock.ns + NS)  # outstanding: remembered, not started
        assert rig.ev.task is first
        gate.set()
        assert first is not None
        await first
        rig.ev.service(rig.clock.ns + 2 * NS)
        assert rig.ev.task is not first
        await rig.ev.task  # type: ignore[misc]
        assert len(seen) == 2


@pytest.mark.parametrize("bad", ["x", True, None])
@pytest.mark.asyncio
async def test_a_bad_settled_pnl_seq_withholds_the_heartbeat(tmp_path: Path, bad: object) -> None:
    with _pass_rig(tmp_path, port_over={"settled_pnl_seq": lambda: bad}) as rig:
        rig.ev.service(rig.clock.ns)
        assert not rig.ev.heartbeat_ok


# -- confirm round -----------------------------------------------------------------------


class _Marks:
    def __init__(self, pending: set[tuple[str, str]]) -> None:
        self.pending = pending

    def ambiguous_marks_pending(self) -> frozenset[tuple[str, str]]:
        return frozenset(self.pending)


class _Guard:
    def __init__(self, n: int) -> None:
        self.pending = n


def test_combined_ingest_pending_counts_the_event_queue_and_pending_marks() -> None:
    from breezy.runtime.exec_par_watcher_stage import combined_ingest_pending

    marks = _Marks({("i1", "slug")})
    guard = _Guard(2)
    pending = combined_ingest_pending(guard, marks)  # type: ignore[arg-type]
    assert pending() == 3
    guard.pending = 0
    assert pending() == 1
    marks.pending.clear()
    assert pending() == 0
    assert combined_ingest_pending(guard, None)() == 0  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_a_pending_ambiguous_mark_is_ingested_before_the_rebuild_so_it_counts_once(
    tmp_path: Path,
) -> None:
    from breezy.runtime.exec_par_records import AmbiguousRow
    from breezy.runtime.exec_par_watcher_stage import combined_ingest_pending

    marks = _Marks({("a1", "slug")})
    with _pass_rig(tmp_path, seed=True, port_over={"ingest_poll_s": 0.001}) as rig:
        rig.ev.bind_ingest_pending(combined_ingest_pending(_Guard(0), marks))  # type: ignore[arg-type]
        rig.latch.write_order_anchor(_anchor("O-1", d(1)))
        rig.sources.counts[d(1)] = DayCounts(1, 1, 0, Decimal(4))  # the durable side has the mark
        rig.ev.service(rig.clock.ns)
        await asyncio.sleep(0.05)
        assert rig.events("EXEC_PAR_COUNTER_REBUILT") == []  # no rebuild over a pending mark
        rig.latch.write_ambiguous(
            AmbiguousRow("a1", "armed_pre_boot", d(1), ns_of(d(1)), "slot", 1, "STN")
        )
        marks.pending.clear()  # the tick ingested it
        task = rig.ev.task
        assert task is not None
        await asyncio.wait_for(task, 5)
        counts = rig.ports.counters.read_day_counts(d(1))
        assert counts is not None and counts.ambiguous == 1  # once, never 2
        assert rig.events("EXEC_PAR_COUNTER_REBUILT") == []
        assert rig.latch.read_counts_delta(d(1)) is None


@pytest.mark.asyncio
async def test_a_mark_that_never_drains_is_reconcile_stuck(tmp_path: Path) -> None:
    from breezy.runtime.exec_par_watcher_stage import combined_ingest_pending

    with _pass_rig(tmp_path, seed=True, port_over={"ingest_poll_s": 0.001}) as rig:
        rig.ev.bind_ingest_pending(combined_ingest_pending(_Guard(0), _Marks({("a", "s")})))  # type: ignore[arg-type]
        rig.ev.service(rig.clock.ns)
        await asyncio.sleep(0.05)
        rig.clock.mono += 301 * NS
        rig.ev.service(rig.clock.ns)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "reconcile_stuck"
        rig.ev.cancel()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_an_unbound_ingest_pending_fails_closed_not_zero(tmp_path: Path) -> None:
    with _pass_rig(tmp_path, seed=True, bind_ingest=False) as rig:
        await rig.run_pass()
        record = rig.breaker()
        assert record is not None and record.halted_reason == "stage_eval_fail:ingest_unbound"
        assert rig.latch.read_stage_eval_stamp() is None


@pytest.mark.asyncio
async def test_a_raising_settled_seq_poll_does_not_block_the_pass_but_withholds_heartbeat(
    tmp_path: Path,
) -> None:
    def boom() -> int:
        raise RuntimeError("poll down")

    with _pass_rig(tmp_path, port_over={"settled_pnl_seq": boom}) as rig:
        rig.ev.service(rig.clock.ns)
        assert rig.ev.task is not None  # the boot pass still started
        assert not rig.ev.heartbeat_ok  # ...and the heartbeat is withheld for the raise
        await rig.ev.task
        assert rig.latch.read_stage_eval_stamp() is not None
        rig.clock.ns = ns_of(d(5)) + 10  # the daily pass is not blocked either
        rig.ev.service(rig.clock.ns)
        assert rig.ev.task is not None and not rig.ev.task.done()
        await rig.ev.task
