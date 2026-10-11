"""EXEC-PAR BG-5b: the in-node stage-evaluator driver (passes, verdict handling, integrity checks).

Driven on a real asyncio loop against a REAL ``SubmitIntentLatch`` over an in-memory store; a
spy records the call order and injects write failures. ``evaluate`` is injected for the
verdict-path tests and left real for the end-to-end ones.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.runtime.exec_par_counter_store import LatchCounterStore
from breezy.runtime.exec_par_reconcile import DayCounts, SlotDayCounts
from breezy.runtime.exec_par_records import (
    EXEC_PAR_PREFIX,
    EpochRow,
    ExcludedDay,
    FillRow,
    OrderAnchor,
    SettledPnlDay,
    StageReset,
)
from breezy.runtime.exec_par_stage_eval import STOP_CLASS_REASONS, Verdict, VerdictKind
from breezy.runtime.exec_par_stage_runner import (
    STAGE_EVAL_SLOW_NS,
    STAGE_EVAL_STUCK_NS,
    StageEvalPorts,
    StageEvaluator,
)
from breezy.runtime.exec_par_stage_types import (
    DayStat,
    StageReport,
    StageSnapshot,
    StopOutcome,
)
from breezy.runtime.submit_intent import (
    BREAKER_KEY,
    SubmitIntentLatch,
    open_submit_intent_latch,
)
from breezy.runtime.submit_intent_slots import BreakerRecord, parse_breaker
from tests.unit.exec_par_days import UtcDays

P = EXEC_PAR_PREFIX
NS = 1_000_000_000
BASE = dt.date(2026, 12, 1)
BOOT_NS = 12345


def d(i: int) -> str:
    return (BASE + dt.timedelta(days=i)).isoformat()


def ns_of(day: str) -> int:
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.UTC).timestamp()) * NS


GOV = UtcDays()


class _Store:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    def set(self, key: str, value: bytes) -> None:
        self.data[key] = value

    def keys_with_prefix(self, prefix: str) -> list[str]:
        return sorted(k for k in self.data if k.startswith(prefix))

    def delete(self, key: str) -> bool:
        return self.data.pop(key, None) is not None


class _Spy:
    """Delegates to the latch; records tracked calls in order and injects failures."""

    TRACKED = frozenset(
        {
            "write_stop_verdict",
            "write_force_k1_flag",
            "mark_flag_write_failed",
            "write_stage_eval_stamp",
            "write_stage_eval_liveness",
            "write_stage_report",
            "write_breaker_halt",
            "add_excluded_day",
        }
    )

    def __init__(self, latch: SubmitIntentLatch) -> None:
        self._latch = latch
        self.calls: list[str] = []
        self.fail: set[str] = set()

    def __getattr__(self, name: str) -> object:
        attr = getattr(self._latch, name)
        if name not in self.TRACKED:
            return attr

        def wrapper(*args: object, **kwargs: object) -> object:
            self.calls.append(name)
            if name in self.fail:
                raise OSError(f"injected {name}")
            return attr(*args, **kwargs)

        return wrapper


class _Preds:
    def pnl_breaches_budget_fraction(self, *, aggregate_pnl: Decimal, fraction: Decimal) -> bool:
        return aggregate_pnl <= -fraction


@dataclass
class _Sources:
    counts: dict[str, DayCounts] = field(default_factory=dict)

    def entry_fill_count(self, day: str) -> int | None:
        return self.counts.get(day, DayCounts(0, 0, 0, Decimal(0))).fills

    def slot_counts(self, day: str) -> SlotDayCounts | None:
        c = self.counts.get(day, DayCounts(0, 0, 0, Decimal(0)))
        return SlotDayCounts(c.posted_entries, c.ambiguous)

    def ledger_spend(self, day: str) -> Decimal | None:
        return self.counts.get(day, DayCounts(0, 0, 0, Decimal(0))).spend_usd


class _Clock:
    def __init__(self, ns: int) -> None:
        self.ns = ns
        self.mono = 0

    def wall(self) -> int:
        return self.ns

    def monotonic(self) -> int:
        return self.mono


@dataclass
class Rig:
    store: _Store
    latch: SubmitIntentLatch
    spy: _Spy
    clock: _Clock
    alerts: list[tuple[str, str, str]]
    sources: _Sources
    ev: StageEvaluator
    halts: list[tuple[str, int]]
    ports: StageEvalPorts

    async def run_pass(self, now: int | None = None) -> None:
        self.ev.service(self.clock.ns if now is None else now)
        task = self.ev.task
        assert task is not None
        await asyncio.wait_for(asyncio.shield(task), 5)

    def events(self, name: str) -> list[tuple[str, str, str]]:
        return [a for a in self.alerts if a[1] == name]

    def breaker(self) -> BreakerRecord | None:
        raw = self.store.get(BREAKER_KEY)
        return None if raw is None else parse_breaker(raw)


def verdict(kind: VerdictKind, reason: str | None = None, **kw: object) -> Verdict:
    return Verdict(kind, reason, **kw)  # type: ignore[arg-type]


def _report() -> StageReport:
    return StageReport(
        stage="S1", configured_k=2, effective_k=2, floor_day=d(0), today=d(4), closed_days=3,
        nonexcluded_days=3, excluded_days=(), posted=9, ambiguous=2, ambiguous_rate=Decimal("0.2"),
        fills=0, filled_orders=0, days_with_fill=0, m_bar=Decimal(3),
        day_stats=(DayStat(d(1), 3, 1, 0), DayStat(d(2), 3, 1, 0)),
        minima_met=False, dropped_share=None, station_day_flag_days=(), window_flag_days=(),
        slippage_mean=None, slippage_tail_share=None, parity_diff=None,
        fee_unreconciled_share=None, per_fill_fee_mismatches=0, section5_halt_in_stage=False,
        held_days=0, promotion_blocked_reason=None, promotion_pending_commit=False,
        pnl_pending=0, pnl_overdue=0, pnl_ambiguous_unresolved=0, programme_paused=False,
        notes=("n",),
    )  # fmt: skip


@contextmanager
def make_rig(
    tmp_path: Path,
    *,
    evaluate: Callable[[StageSnapshot], Verdict] | None = None,
    now: int | None = None,
    ready: Callable[[], object] | None = None,
    refresh: Callable[[], object] | None = None,
    mass_status: bool = True,
    seed: bool = False,
    port_over: dict[str, object] | None = None,
    bind_ingest: bool = True,
) -> Iterator[Rig]:
    store = _Store()
    clock = _Clock(ns_of(d(4)) + 100 if now is None else now)
    with open_submit_intent_latch(
        store, tmp_path / "s.db", max_slots=2, v2_predicate=lambda: True, clock_ns=lambda: BOOT_NS
    ) as latch:
        if seed:
            latch.write_epoch_row(EpochRow("sha", 2, None, ns_of(d(0)) + 5))
            latch.write_stage_reset(StageReset(ns_of(d(0)) + 5, "k_change", None))
        spy = _Spy(latch)
        alerts: list[tuple[str, str, str]] = []
        halts: list[tuple[str, int]] = []
        sources = _Sources()

        def halt(reason: str, ts: int) -> None:
            halts.append((reason, ts))
            spy.write_breaker_halt(reason, ts_ns=ts)  # type: ignore[operator]

        ports = StageEvalPorts(
            store=spy,  # type: ignore[arg-type]
            counters=LatchCounterStore(spy, wall_ns=clock.wall),  # type: ignore[arg-type]
            sources=sources,
            mass_status_ingested=lambda: mass_status,
            counters_expected=lambda day: False,
            predicates=_Preds(),
            serial_baseline=lambda: None,
            governed=GOV,
            configured_k=2,
            effective_k=lambda: 2,
            boot_ns=BOOT_NS,
            wall_ns=clock.wall,
            monotonic_ns=clock.monotonic,
            await_ready=ready,  # type: ignore[arg-type]
            refresh_settled_pnl=refresh,  # type: ignore[arg-type]
            **({} if evaluate is None else {"evaluate": evaluate}),  # type: ignore[arg-type]
        )
        if port_over:
            ports = dataclasses.replace(ports, **port_over)  # type: ignore[arg-type]

        def alert(severity: str, event: str, detail: str) -> bool:
            alerts.append((severity, event, detail))
            return True

        ev = StageEvaluator(ports, halt=halt, alert=alert)
        if bind_ingest:
            ev.bind_ingest_pending(lambda: 0)
        yield Rig(store, latch, spy, clock, alerts, sources, ev, halts, ports)


# ---------------------------------------------------------------------------
# scheduling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_boot_pass_runs_once_then_a_daily_pass_only_when_the_day_changes(
    tmp_path: Path,
) -> None:
    seen: list[str] = []

    def evaluate(snap: StageSnapshot) -> Verdict:
        seen.append(snap.today)
        return verdict(VerdictKind.PASS)

    with make_rig(tmp_path, evaluate=evaluate) as rig:
        await rig.run_pass()
        first = rig.ev.task
        rig.ev.service(rig.clock.ns + NS)  # same day: nothing new
        assert rig.ev.task is first
        await rig.run_pass(rig.clock.ns + 2 * NS)
        assert seen == [d(4)]
        rig.clock.ns = ns_of(d(5)) + 10  # the climate day closed
        await rig.run_pass()
        assert seen == [d(4), d(5)]
        assert rig.ev.task is not first


@pytest.mark.asyncio
async def test_no_second_pass_starts_while_one_is_outstanding(tmp_path: Path) -> None:
    gate = asyncio.Event()

    async def ready() -> None:
        await gate.wait()

    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS), ready=ready) as rig:
        rig.ev.service(rig.clock.ns)
        first = rig.ev.task
        rig.clock.ns = ns_of(d(5)) + 10
        rig.ev.service(rig.clock.ns)
        assert rig.ev.task is first  # outstanding: a day change does not start another
        gate.set()
        assert first is not None
        await first


# ---------------------------------------------------------------------------
# verdict paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pass_writes_stamp_with_boot_ns_liveness_and_reconcile_phase(tmp_path: Path) -> None:
    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS)) as rig:
        await rig.run_pass()
        stamp = rig.latch.read_stage_eval_stamp()
        assert stamp is not None and stamp.boot_ns == BOOT_NS and stamp.ts_ns == rig.clock.ns
        live = rig.latch.read_stage_eval_liveness()
        assert live is not None
        assert live.stage_eval_last_start_ns == rig.clock.ns
        assert live.stage_eval_last_ok_ns == rig.clock.ns
        phase = rig.latch.read_reconcile_phase()
        assert phase is not None and phase.reconcile_ok_ns == rig.clock.ns
        assert rig.halts == [] and rig.breaker() is None
        assert rig.latch.read_force_k1_flag().kind.value == "cleared"
        assert rig.ev.heartbeat_ok


@pytest.mark.asyncio
async def test_stamp_boot_ns_is_the_latch_boot_ns_not_a_later_clock(tmp_path: Path) -> None:
    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS)) as rig:
        assert rig.latch.boot_ns == BOOT_NS
        await rig.run_pass(rig.clock.ns + 99 * NS)
        stamp = rig.latch.read_stage_eval_stamp()
        assert stamp is not None and stamp.boot_ns == rig.latch.boot_ns


@pytest.mark.asyncio
async def test_hold_reports_alerts_and_stamps_without_halting(tmp_path: Path) -> None:
    v = verdict(VerdictKind.HOLD, "l3_cap_minima_unmet", report=_report())
    with make_rig(tmp_path, evaluate=lambda s: v) as rig:
        await rig.run_pass()
        doc = rig.latch.read_stage_report()
        assert doc is not None and doc.verdict == "hold" and doc.reason == "l3_cap_minima_unmet"
        assert doc.report_json is not None and '"ambiguous":1' in doc.report_json
        assert [a[1] for a in rig.alerts] == ["EXEC_PAR_STAGE_HOLD"]
        assert rig.latch.read_stage_eval_stamp() is not None
        assert rig.halts == [] and rig.breaker() is None


@pytest.mark.asyncio
async def test_promotion_eligible_never_promotes_only_reports_and_alerts(tmp_path: Path) -> None:
    v = verdict(
        VerdictKind.PROMOTION_ELIGIBLE, look_number=1, look_blockers=("parity",), report=_report()
    )
    with make_rig(tmp_path, evaluate=lambda s: v) as rig:
        before = dict(rig.store.data)
        await rig.run_pass()
        written = {k for k in rig.store.data if k not in before or before[k] != rig.store.data[k]}
        assert written <= {
            P + "stage_eval/stamp",
            P + "stage_eval/liveness",
            P + "stage_eval/reconcile_phase",
            P + "stage_eval/report",
        }
        assert rig.latch.read_stage_reset() is None
        assert rig.latch.read_looks() == ()
        assert rig.latch.read_latest_cleanup_demotion() is None
        assert rig.halts == []
        events = rig.events("EXEC_PAR_STAGE_PROMOTION_ELIGIBLE")
        assert len(events) == 1 and "parity" in events[0][2] and "look=1" in events[0][2]
        doc = rig.latch.read_stage_report()
        assert doc is not None and "day_stats" in (doc.report_json or "")


@pytest.mark.asyncio
async def test_stop_orders_marker_then_halt_then_flag_then_alerts(tmp_path: Path) -> None:
    v = verdict(
        VerdictKind.STOP, "s15_day", outcome=StopOutcome.RESTART_S1, target_k=2,
        stops=("s15_day",), sets_flag=True, report=_report(),
    )  # fmt: skip
    with make_rig(tmp_path, evaluate=lambda s: v) as rig:
        await rig.run_pass()
        order = [
            c
            for c in rig.spy.calls
            if c in {"write_stop_verdict", "write_breaker_halt", "write_force_k1_flag"}
        ]
        assert order == ["write_stop_verdict", "write_breaker_halt", "write_force_k1_flag"]
        marker = rig.latch.read_latest_stop_verdict()
        assert marker is not None and marker.reason == "s15_day" and marker.ts_ns == rig.clock.ns
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s15_day"
        assert not record.flag_write_failed
        state = rig.latch.read_force_k1_flag()
        assert state.kind.value == "set" and state.record is not None
        assert state.record.reason == "s15_day" and state.record.set_by == "stage_eval"
        assert [a[1] for a in rig.alerts] == ["EXEC_PAR_STAGE_STOP"]
        assert rig.alerts[0][0] == "CRITICAL" and "s15_day" in rig.alerts[0][2]
        assert rig.ev.heartbeat_ok


@pytest.mark.asyncio
async def test_stop_without_sets_flag_writes_no_flag(tmp_path: Path) -> None:
    v = verdict(VerdictKind.STOP, "s15_day", sets_flag=False)
    with make_rig(tmp_path, evaluate=lambda s: v) as rig:
        await rig.run_pass()
        assert "write_force_k1_flag" not in rig.spy.calls
        assert rig.breaker() is not None


@pytest.mark.asyncio
async def test_marker_write_failure_halts_stops_the_heartbeat_and_still_flags(
    tmp_path: Path,
) -> None:
    v = verdict(VerdictKind.STOP, "s15_day", sets_flag=True, report=_report())
    with make_rig(tmp_path, evaluate=lambda s: v) as rig:
        rig.spy.fail.add("write_stop_verdict")
        await rig.run_pass()
        record = rig.breaker()
        assert record is not None and record.halted_reason == "stop_marker_write_fail"
        assert rig.latch.read_force_k1_flag().kind.value == "set"  # the flag is still attempted
        assert not rig.ev.heartbeat_ok  # D3: the heartbeat stops
        assert rig.latch.read_stage_eval_stamp() is None
        order = [
            c
            for c in rig.spy.calls
            if c in {"write_stop_verdict", "write_breaker_halt", "write_force_k1_flag"}
        ]
        assert order == ["write_stop_verdict", "write_breaker_halt", "write_force_k1_flag"]


@pytest.mark.asyncio
async def test_flag_write_failure_marks_flag_write_failed_on_the_breaker_record(
    tmp_path: Path,
) -> None:
    v = verdict(VerdictKind.STOP, "s15_stage", sets_flag=True, report=_report())
    with make_rig(tmp_path, evaluate=lambda s: v) as rig:
        rig.spy.fail.add("write_force_k1_flag")
        await rig.run_pass()
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s15_stage"
        assert record.flag_write_failed is True
        assert rig.latch.read_force_k1_flag().kind.value == "cleared"
        assert rig.events("EXEC_PAR_FORCE_K1_FLAG_WRITE_FAILED")
        assert rig.ev.heartbeat_ok  # the halt itself latched: the heartbeat is not stopped
        order = [
            c
            for c in rig.spy.calls
            if c
            in {
                "write_stop_verdict",
                "write_breaker_halt",
                "write_force_k1_flag",
                "mark_flag_write_failed",
            }
        ]
        assert order == [
            "write_stop_verdict",
            "write_breaker_halt",
            "write_force_k1_flag",
            "mark_flag_write_failed",
        ]


@pytest.mark.asyncio
async def test_flag_failure_and_a_failed_mark_stops_the_heartbeat(tmp_path: Path) -> None:
    v = verdict(VerdictKind.STOP, "s15_stage", sets_flag=True)
    with make_rig(tmp_path, evaluate=lambda s: v) as rig:
        rig.spy.fail.update({"write_force_k1_flag", "mark_flag_write_failed"})
        await rig.run_pass()
        assert not rig.ev.heartbeat_ok
        assert rig.events("EXEC_PAR_FORCE_K1_FLAG_WRITE_FAILED")


@pytest.mark.asyncio
async def test_stop_halt_write_failure_withholds_heartbeat_attempts_flag_and_retries(
    tmp_path: Path,
) -> None:
    v = verdict(VerdictKind.STOP, "s15_day", sets_flag=True, report=_report())
    with make_rig(tmp_path, evaluate=lambda s: v) as rig:
        rig.spy.fail.add("write_breaker_halt")
        await rig.run_pass()
        assert (
            rig.latch.read_force_k1_flag().kind.value == "set"
        )  # flag attempted despite the raise
        assert not rig.ev.heartbeat_ok
        assert rig.breaker() is None
        rig.spy.fail.discard("write_breaker_halt")
        rig.ev.service(rig.clock.ns + NS)  # the next tick retries the halt
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s15_day"
        assert rig.ev.heartbeat_ok


@pytest.mark.asyncio
async def test_fail_halts_with_the_reason_sets_no_flag_and_no_marker_or_stamp(
    tmp_path: Path,
) -> None:
    v = verdict(VerdictKind.FAIL, "stage_eval_fail:gappy")
    with make_rig(tmp_path, evaluate=lambda s: v) as rig:
        await rig.run_pass()
        record = rig.breaker()
        assert record is not None and record.halted_reason == "stage_eval_fail:gappy"
        assert rig.latch.read_force_k1_flag().kind.value == "cleared"
        assert rig.latch.read_latest_stop_verdict() is None
        assert rig.latch.read_stage_eval_stamp() is None
        assert rig.events("EXEC_PAR_STAGE_EVAL_FAIL")


# ---------------------------------------------------------------------------
# exception paths: every one ends in a halt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_evaluator_exception_halts_as_a_fail_kind(tmp_path: Path) -> None:
    def boom(snap: StageSnapshot) -> Verdict:
        raise RuntimeError("secret 123.45")

    with make_rig(tmp_path, evaluate=boom) as rig:
        await rig.run_pass()
        record = rig.breaker()
        assert record is not None
        assert record.halted_reason == "stage_eval_fail:evaluate:RuntimeError"
        assert "123.45" not in (record.halted_reason or "")
        assert all("123.45" not in a[2] for a in rig.alerts)


@pytest.mark.asyncio
async def test_a_snapshot_read_failure_halts(tmp_path: Path) -> None:
    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS)) as rig:

        def broken() -> tuple[ExcludedDay, ...]:
            raise OSError("down")

        rig.latch.read_excluded_days = broken  # type: ignore[method-assign]
        await rig.run_pass()
        record = rig.breaker()
        assert record is not None and record.halted_reason == "stage_eval_fail:snapshot:OSError"


@pytest.mark.asyncio
async def test_reconcile_before_the_mass_status_ingest_halts_as_an_ordering_fail(
    tmp_path: Path,
) -> None:
    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS), mass_status=False) as rig:
        await rig.run_pass()
        record = rig.breaker()
        assert record is not None and record.halted_reason == "stage_eval_fail:reconcile_ordering"


@pytest.mark.asyncio
async def test_a_reconcile_exception_halts(tmp_path: Path) -> None:
    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS)) as rig:

        def broken(day: str) -> int | None:
            raise OSError("fills down")

        rig.sources.entry_fill_count = broken  # type: ignore[method-assign]
        await rig.run_pass()
        record = rig.breaker()
        assert record is not None and record.halted_reason == "stage_eval_fail:reconcile:OSError"


@pytest.mark.parametrize(
    "failing", ["write_stage_eval_stamp", "write_stage_eval_liveness", "write_stage_report"]
)
@pytest.mark.asyncio
async def test_a_telemetry_write_failure_halts_as_telemetry_write_fail(
    tmp_path: Path, failing: str
) -> None:
    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS, report=_report())) as rig:
        rig.spy.fail.add(failing)
        await rig.run_pass()
        record = rig.breaker()
        assert record is not None and record.halted_reason == "telemetry_write_fail"
        assert rig.latch.read_stage_eval_stamp() is None or failing != "write_stage_eval_stamp"


@pytest.mark.asyncio
async def test_reconcile_phase_write_failure_halts_as_telemetry_write_fail(tmp_path: Path) -> None:
    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS)) as rig:

        def broken(*, start_ns: int, ok_ns: int | None) -> None:
            raise OSError("down")

        rig.latch.write_reconcile_phase = broken  # type: ignore[method-assign]
        await rig.run_pass()
        record = rig.breaker()
        assert record is not None and record.halted_reason == "telemetry_write_fail"


@pytest.mark.asyncio
async def test_reconcile_exclusion_halts_day_excluded_and_alerts(tmp_path: Path) -> None:
    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS), seed=True) as rig:
        rig.sources.counts[d(2)] = DayCounts(1, 2, 0, Decimal(0))  # ambiguous > posted
        await rig.run_pass()
        record = rig.breaker()
        assert record is not None and record.halted_reason == "day_excluded"
        assert [x.day for x in rig.latch.read_excluded_days()] == [d(2)]
        assert any(d(2) in a[2] for a in rig.events("EXEC_PAR_DAY_EXCLUDED"))


@pytest.mark.asyncio
async def test_reconcile_rebuild_alerts_with_day_and_kinds(tmp_path: Path) -> None:
    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS), seed=True) as rig:
        rig.sources.counts[d(1)] = DayCounts(2, 0, 0, Decimal(0))  # durable has 2, rows have 0
        await rig.run_pass()
        events = rig.events("EXEC_PAR_COUNTER_REBUILT")
        assert len(events) == 1 and d(1) in events[0][2] and "posted_entries" in events[0][2]
        assert rig.breaker() is None


@pytest.mark.asyncio
async def test_reconcile_stuck_bound_breach_in_the_pass_halts_via_the_evaluator(
    tmp_path: Path,
) -> None:
    with make_rig(tmp_path, seed=True) as rig:  # real evaluator
        rig.clock.mono = 0

        def jump(day: str) -> int:
            rig.clock.mono += 301 * NS  # one slow source read blows the 300 s bound
            return 0

        rig.sources.entry_fill_count = jump  # type: ignore[method-assign]
        await rig.run_pass()
        record = rig.breaker()
        assert record is not None and record.halted_reason == "reconcile_stuck"


# ---------------------------------------------------------------------------
# per-tick integrity checks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_await_hung_evaluate_phase_is_stage_eval_stuck_after_60s_not_before(
    tmp_path: Path,
) -> None:
    never = asyncio.Event()

    async def refresh() -> None:
        await never.wait()

    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS), refresh=refresh) as rig:
        rig.ev.service(rig.clock.ns)
        await asyncio.sleep(0.05)
        rig.clock.ns += 10_000 * NS  # a wall-clock jump alone never trips an age bound
        rig.clock.mono += STAGE_EVAL_STUCK_NS - NS
        rig.ev.service(rig.clock.ns)
        assert rig.breaker() is None
        rig.clock.mono += 2 * NS
        rig.ev.service(rig.clock.ns)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "stage_eval_stuck"
        assert rig.events("EXEC_PAR_STAGE_EVAL_STUCK")
        rig.ev.cancel()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_await_hung_reconcile_phase_is_reconcile_stuck_after_300s(tmp_path: Path) -> None:
    never = asyncio.Event()

    async def ready() -> None:
        await never.wait()

    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS), ready=ready) as rig:
        rig.ev.service(rig.clock.ns)
        await asyncio.sleep(0.05)
        rig.clock.ns += 10_000 * NS
        rig.clock.mono += 299 * NS
        rig.ev.service(rig.clock.ns)
        assert rig.breaker() is None
        rig.clock.mono += 2 * NS
        rig.ev.service(rig.clock.ns)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "reconcile_stuck"
        rig.ev.cancel()
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_slow_evaluation_over_2s_halts_after_applying_the_verdict_and_skips_the_stamp(
    tmp_path: Path,
) -> None:
    holder: list[Rig] = []

    def slow(snap: StageSnapshot) -> Verdict:
        holder[0].clock.mono += STAGE_EVAL_SLOW_NS + 1
        return verdict(VerdictKind.PASS)

    with make_rig(tmp_path, evaluate=slow) as rig:
        holder.append(rig)
        await rig.run_pass()
        record = rig.breaker()
        assert record is not None and record.halted_reason == "stage_eval_slow"
        assert rig.latch.read_stage_eval_stamp() is None
        assert rig.events("EXEC_PAR_STAGE_EVAL_SLOW")


@pytest.mark.asyncio
async def test_a_fast_evaluation_at_exactly_2s_is_not_slow(tmp_path: Path) -> None:
    holder: list[Rig] = []

    def edge(snap: StageSnapshot) -> Verdict:
        holder[0].clock.mono += STAGE_EVAL_SLOW_NS
        return verdict(VerdictKind.PASS)

    with make_rig(tmp_path, evaluate=edge) as rig:
        holder.append(rig)
        await rig.run_pass()
        assert rig.breaker() is None and rig.latch.read_stage_eval_stamp() is not None


@pytest.mark.asyncio
async def test_slow_stop_still_applies_the_stop_first(tmp_path: Path) -> None:
    holder: list[Rig] = []

    def slow_stop(snap: StageSnapshot) -> Verdict:
        holder[0].clock.mono += STAGE_EVAL_SLOW_NS + 1
        return verdict(VerdictKind.STOP, "s15_day", sets_flag=True)

    with make_rig(tmp_path, evaluate=slow_stop) as rig:
        holder.append(rig)
        await rig.run_pass()
        record = rig.breaker()
        assert record is not None and record.halted_reason == "s15_day"  # sticky: first wins
        assert rig.latch.read_force_k1_flag().kind.value == "set"
        assert rig.events("EXEC_PAR_STAGE_EVAL_SLOW")


@pytest.mark.asyncio
async def test_task_death_via_the_done_callback_halts_task_died(tmp_path: Path) -> None:
    async def ready() -> None:
        raise asyncio.CancelledError  # the pass task is cancelled from outside

    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS), ready=ready) as rig:
        rig.ev.service(rig.clock.ns)
        task = rig.ev.task
        assert task is not None
        await asyncio.wait({task}, timeout=5)
        await asyncio.sleep(0)  # let the done-callback run
        rig.ev.service(rig.clock.ns + NS)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "stage_eval_task_died"
        assert rig.events("EXEC_PAR_STAGE_EVAL_TASK_DIED")


@pytest.mark.asyncio
async def test_task_death_is_caught_by_the_per_tick_done_check_without_the_callback(
    tmp_path: Path,
) -> None:
    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS)) as rig:
        loop = asyncio.get_running_loop()
        dead = loop.create_future()
        dead.set_exception(RuntimeError("died before the callback was attached"))
        dead.exception()  # mark retrieved
        rig.ev._task = dead
        rig.ev._seq = 1
        rig.ev.service(rig.clock.ns)
        record = rig.breaker()
        assert record is not None and record.halted_reason == "stage_eval_task_died"


@pytest.mark.asyncio
async def test_a_completed_pass_is_not_a_dead_task(tmp_path: Path) -> None:
    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS)) as rig:
        await rig.run_pass()
        await asyncio.sleep(0)
        rig.ev.service(rig.clock.ns + NS)
        rig.ev.service(rig.clock.ns + 2 * NS)
        assert rig.breaker() is None


@pytest.mark.asyncio
async def test_a_fail_pass_is_handled_not_reported_dead_as_well(tmp_path: Path) -> None:
    with make_rig(
        tmp_path, evaluate=lambda s: verdict(VerdictKind.FAIL, "stage_eval_fail:x")
    ) as rig:
        await rig.run_pass()
        await asyncio.sleep(0)
        rig.ev.service(rig.clock.ns + NS)
        assert rig.halts == [("stage_eval_fail:x", rig.clock.ns)]


# ---------------------------------------------------------------------------
# cancel / on_stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancel_cancels_the_outstanding_task_without_a_task_died_halt(tmp_path: Path) -> None:
    never = asyncio.Event()

    async def ready() -> None:
        await never.wait()

    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS), ready=ready) as rig:
        rig.ev.service(rig.clock.ns)
        task = rig.ev.task
        assert task is not None and not task.done()
        rig.ev.cancel()
        await asyncio.wait({task}, timeout=5)
        assert task.cancelled()
        rig.ev.service(rig.clock.ns + NS)
        assert rig.breaker() is None
        assert rig.halts == []


@pytest.mark.asyncio
async def test_cancel_from_a_foreign_thread_is_threadsafe(tmp_path: Path) -> None:
    never = asyncio.Event()

    async def ready() -> None:
        await never.wait()

    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS), ready=ready) as rig:
        rig.ev.service(rig.clock.ns)
        task = rig.ev.task
        assert task is not None
        worker = threading.Thread(target=rig.ev.cancel)
        worker.start()
        worker.join()
        await asyncio.wait({task}, timeout=5)
        assert task.cancelled()


@pytest.mark.asyncio
async def test_after_cancel_no_new_pass_is_started(tmp_path: Path) -> None:
    with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS)) as rig:
        rig.ev.cancel()
        rig.ev.service(rig.clock.ns)
        assert rig.ev.task is None


def test_cancel_without_a_task_is_a_noop(tmp_path: Path) -> None:
    with make_rig(tmp_path) as rig:
        rig.ev.cancel()
        assert rig.ev.task is None


def test_the_task_is_held_by_a_strong_reference(tmp_path: Path) -> None:
    async def scenario() -> None:
        import gc

        never = asyncio.Event()

        async def ready() -> None:
            await never.wait()

        with make_rig(tmp_path, evaluate=lambda s: verdict(VerdictKind.PASS), ready=ready) as rig:
            rig.ev.service(rig.clock.ns)
            gc.collect()
            await asyncio.sleep(0.01)
            task = rig.ev.task
            assert task is not None and not task.done()
            rig.ev.cancel()
            await asyncio.wait({task}, timeout=5)

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# end to end with the real evaluator
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_evaluator_pass_on_a_seeded_stage(tmp_path: Path) -> None:
    with make_rig(tmp_path, seed=True) as rig:
        await rig.run_pass()
        assert rig.breaker() is None
        stamp = rig.latch.read_stage_eval_stamp()
        assert stamp is not None and stamp.boot_ns == BOOT_NS
        doc = rig.latch.read_stage_report()
        assert doc is not None and doc.verdict == "pass"


@pytest.mark.asyncio
async def test_real_evaluator_stop_on_a_day_loss_runs_the_full_ordered_response(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    with make_rig(tmp_path, seed=True) as rig:
        order_id = "O-1"
        rig.latch.write_order_anchor(
            OrderAnchor(
                order_id,
                "slug",
                d(1),
                ns_of(d(1)),
                "0.40",
                "10",
                "4",
                ns_of(d(1)),
                "event_time",
                "STN",
            )
        )
        rig.latch.write_fill(
            FillRow(
                "T-1",
                order_id,
                d(1),
                ns_of(d(1)),
                "10",
                "0.40",
                "0.40",
                "0",
                "0.17",
                "0.17",
                "0.0695",
                "STN",
            )
        )
        rig.sources.counts[d(1)] = DayCounts(1, 0, 1, Decimal(4))
        rig.latch.write_settled_pnl_day(SettledPnlDay(d(1), "-987.65", 1, 0, 0, 0, 0, "0"))
        await rig.run_pass()
        record = rig.breaker()
        assert record is not None and record.halted_reason in STOP_CLASS_REASONS
        marker = rig.latch.read_latest_stop_verdict()
        assert marker is not None and marker.reason == record.halted_reason
        assert rig.latch.read_force_k1_flag().kind.value == "set"
        assert "987.65" not in caplog.text
        assert all("987.65" not in a[2] for a in rig.alerts)
        doc = rig.latch.read_stage_report()
        assert doc is not None and "987.65" not in (doc.report_json or "")
