"""EXEC-PAR BG-5b: the in-node stage-evaluator driver (D-PREREG r4 1a, K5/K6, L2, M3, N1-N3, O5).

:class:`StageEvaluator` is owned by the K>1 ``BreakerWatcherActor``. It never runs inside
``tick()``: ``service()`` (called from the tick, cheap and synchronous) only checks integrity,
retries a pending halt and, when a pass is due, starts a DETACHED ``asyncio`` task on the loop
thread. Everything runs on the loop thread (K5: inline, no executor), so the single-writer
latch methods are never touched from another thread.

Schedule (r4 1a "Scheduling"): a BOOT pass on the first service, then a DAILY pass on the first
service after ``governed.today(now)`` changes (the earliest still-open climate day over the
governed stations, so a change means every governed station's day has closed; a station that is
already on the next label does not trigger one, BG-5c A5).
The settled-P&L-triggered pass of 1a is not scheduled: nothing in the node observes a
settlement ingest (BG-1c seam); the daily pass reads whatever rows exist, and the optional
``refresh_settled_pnl`` hook is where that driver plugs in.

A pass has two timestamped phases (N3): RECONCILE (``reconcile_start_ns`` / ``reconcile_ok_ns``,
bound 300 s, else ``reconcile_stuck``) and EVALUATE (``stage_eval_last_start_ns`` /
``stage_eval_last_ok_ns``, bound 60 s, else ``stage_eval_stuck``; the pure evaluation over
2 s is ``stage_eval_slow``). Both bounds are checked on every service call, so a pass hung on
an await is caught while the loop still runs (L2); a pass that blocks the loop is L4.

Verdict handling (the node NEVER promotes, r4.5 O5):

* STOP: the ``stop_verdict`` marker FIRST (M3; a failed write is ``stop_marker_write_fail`` and
  stops the heartbeat), then the entries-only halt, then the force-K1 flag (stop-class
  verdicts only). The flag write is attempted even if the halt write raised; a failed flag
  write sets ``flag_write_failed`` on the breaker record (and a failure to set THAT stops the
  heartbeat). The flag is keyed on every pass's verdict.
* FAIL: an integrity halt with the verdict's reason; no flag, no marker.
* HOLD / PROMOTION_ELIGIBLE: the report and an alert. Nothing else.
* PASS: the stamp ``{ts_ns, boot_ns}``. HOLD, PROMOTION_ELIGIBLE and a fully handled STOP stamp
  too (a held stage must not look stale after 26 h); FAIL and a slow pass do not.

Every exception ends in a halt (``stage_eval_fail:<kind>`` or ``telemetry_write_fail``); a halt
write that raises is retried on the next service and withholds the heartbeat (D3).
``_pending_halt`` keeps only the FIRST reason: the breaker halt is sticky (first reason wins)
and the durable stop-verdict marker carries the stop reason, so a later one adds nothing.
A failed ``stop_verdict`` marker write stops the heartbeat until a node restart: fail-closed by
design (r4.3 M3: "a failed write of that marker is itself the integrity halt
``stop_marker_write_fail``, and the heartbeat stops (D3)"); it is never retried or cleared here.

Clocks: every integrity AGE (stuck 60 s, reconcile 300 s, slow 2 s) is measured on the ONE
injected monotonic clock (``ports.monotonic_ns``), so a wall-clock step can neither trip nor
mask a bound. The wall clock (``ports.wall_ns``, the ``now_ns`` of ``service``) is used only for
stamps, record timestamps, halt times and climate-day labels. ``stage_eval_slow`` times the
snapshot build plus the pure evaluation (M4's reconcile exclusion stands: reconciliation has its
own 300 s bound and is not part of the 2 s span).

Reconcile never runs over a non-empty ingest retry queue (``bind_ingest_pending``): a queued
event whose row lands after a rebuild would be counted twice. The pass waits for the queue to
drain; the wait is inside the reconcile phase, so a queue that never drains is
``reconcile_stuck``. Currency
values never leave the injected ports: alerts, logs and the report carry reasons, counts,
ratios and day labels only.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Final, Protocol

from breezy.runtime.exec_par_days_port import DayConvention
from breezy.runtime.exec_par_reconcile import (
    RECONCILE_BOUND_NS,
    CounterStorePort,
    DurableDaySources,
    PassResult,
    PassStatus,
    ReconcileOrderingError,
    run_reconcile_pass,
)
from breezy.runtime.exec_par_records import (
    ExcludedDay,
    ForceK1Flag,
    StageEvalLiveness,
    StageEvalStamp,
    StageReportDoc,
    StopVerdict,
)
from breezy.runtime.exec_par_stage_eval import evaluate_stage
from breezy.runtime.exec_par_stage_report import report_json
from breezy.runtime.exec_par_stage_snapshot import (
    SnapshotInputs,
    SnapshotReads,
    build_stage_snapshot,
    stage_day_labels,
)
from breezy.runtime.exec_par_stage_types import (
    HOLD_CLEANUP_DEMOTION,
    PnlPredicatePort,
    SerialBaseline,
    StageSnapshot,
    Verdict,
    VerdictKind,
)

__all__ = [
    "STAGE_EVAL_SLOW_NS",
    "STAGE_EVAL_STUCK_NS",
    "StageEvalPorts",
    "StageEvalStore",
    "StageEvaluator",
]

logger = logging.getLogger(__name__)

_NS: Final[int] = 1_000_000_000
#: L2 / N3: an evaluate phase older than this with no completion is ``stage_eval_stuck``.
STAGE_EVAL_STUCK_NS: Final[int] = 60 * _NS
#: K5 / M4: the pure evaluation step may take at most this long (strictly more is slow).
STAGE_EVAL_SLOW_NS: Final[int] = 2 * _NS

REASON_STUCK: Final[str] = "stage_eval_stuck"
REASON_SLOW: Final[str] = "stage_eval_slow"
REASON_TASK_DIED: Final[str] = "stage_eval_task_died"
REASON_RECONCILE_STUCK: Final[str] = "reconcile_stuck"
REASON_TELEMETRY: Final[str] = "telemetry_write_fail"
REASON_MARKER_FAIL: Final[str] = "stop_marker_write_fail"
REASON_DAY_EXCLUDED: Final[str] = "day_excluded"
_FAIL_PREFIX: Final[str] = "stage_eval_fail:"

EVENT_STOP: Final[str] = "EXEC_PAR_STAGE_STOP"
EVENT_FAIL: Final[str] = "EXEC_PAR_STAGE_EVAL_FAIL"
EVENT_HOLD: Final[str] = "EXEC_PAR_STAGE_HOLD"
EVENT_PROMOTION_ELIGIBLE: Final[str] = "EXEC_PAR_STAGE_PROMOTION_ELIGIBLE"
EVENT_STUCK: Final[str] = "EXEC_PAR_STAGE_EVAL_STUCK"
EVENT_SLOW: Final[str] = "EXEC_PAR_STAGE_EVAL_SLOW"
EVENT_TASK_DIED: Final[str] = "EXEC_PAR_STAGE_EVAL_TASK_DIED"
EVENT_RECONCILE_STUCK: Final[str] = "EXEC_PAR_RECONCILE_STUCK"
EVENT_INTEGRITY: Final[str] = "EXEC_PAR_STAGE_INTEGRITY_HALT"
EVENT_FLAG_WRITE_FAILED: Final[str] = "EXEC_PAR_FORCE_K1_FLAG_WRITE_FAILED"
EVENT_COUNTER_REBUILT: Final[str] = "EXEC_PAR_COUNTER_REBUILT"
EVENT_DAY_EXCLUDED: Final[str] = "EXEC_PAR_DAY_EXCLUDED"

_EVENT_OF_REASON: Final[dict[str, str]] = {
    REASON_STUCK: EVENT_STUCK,
    REASON_SLOW: EVENT_SLOW,
    REASON_TASK_DIED: EVENT_TASK_DIED,
    REASON_RECONCILE_STUCK: EVENT_RECONCILE_STUCK,
}
_OUTBOX_MAX: Final[int] = 64
_PHASE_RECONCILE: Final[str] = "reconcile"
_PHASE_EVALUATE: Final[str] = "evaluate"


class StageEvalStore(SnapshotReads, Protocol):
    """The latch methods the driver uses: the snapshot reads plus the single-writer writes."""

    def write_stop_verdict(self, record: StopVerdict) -> None: ...
    def write_force_k1_flag(self, record: ForceK1Flag) -> None: ...
    def mark_flag_write_failed(self) -> None: ...
    def write_stage_eval_stamp(self, record: StageEvalStamp) -> None: ...
    def write_stage_eval_liveness(self, record: StageEvalLiveness) -> None: ...
    def read_stage_eval_liveness(self) -> StageEvalLiveness | None: ...
    def write_stage_report(self, record: StageReportDoc) -> None: ...
    def add_excluded_day(self, record: ExcludedDay) -> bool: ...


@dataclass(frozen=True, slots=True)
class StageEvalPorts:
    """Every injected dependency of a pass (K6: reads, predicates and the clock are injected).

    ``governed`` is the one day convention (BG-5c R1): ``governed.today(ts)`` is the EARLIEST
    still-open climate day over the governed stations and ``governed.entry_day(station, arm_ns)``
    is the label every counter, reconcile and settled-P&L path attributes by (I2).
    ``await_ready`` (optional) is awaited before the reconcile (the boot pass waits here for the
    Nautilus mass-status ingest, spec 10a); ``refresh_settled_pnl`` (optional) is awaited before
    the snapshot (the BG-1c accumulator driver after a settlement ingest).
    """

    store: StageEvalStore
    counters: CounterStorePort
    sources: DurableDaySources
    mass_status_ingested: Callable[[], bool]
    counters_expected: Callable[[str], bool]
    predicates: PnlPredicatePort
    serial_baseline: Callable[[], SerialBaseline | None]
    governed: DayConvention
    configured_k: int
    effective_k: Callable[[], int]
    boot_ns: int
    wall_ns: Callable[[], int]
    monotonic_ns: Callable[[], int]
    counted_denial: Callable[[str], bool] | None = None
    await_ready: Callable[[], Awaitable[None]] | None = None
    refresh_settled_pnl: Callable[[], Awaitable[None]] | None = None
    #: Cheap poll of a monotone "settled-P&L seen" counter (BG-5c supplies it). A change since
    #: the previous poll triggers a pass (r4 1a / s15: "the tick that first observes a new
    #: settled-P&L value"). ``None`` means no such seam exists yet.
    settled_pnl_seq: Callable[[], int] | None = None
    #: Seconds between checks of the ingest retry queue while a pass waits to reconcile.
    ingest_poll_s: float = 0.5
    #: The pure evaluator (BG-5a); injectable so the wiring is testable with canned verdicts.
    evaluate: Callable[[StageSnapshot], Verdict] = evaluate_stage


class _PassFailure(Exception):
    """A pass step failed with a known halt reason (the message never carries values)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class StageEvaluator:
    """Schedules and runs the passes, applies verdicts and enforces the liveness bounds."""

    def __init__(
        self,
        ports: StageEvalPorts,
        *,
        halt: Callable[[str, int], None],
        alert: Callable[[str, str, str], bool],
    ) -> None:
        self._ports = ports
        self._halt = halt
        self._alert = alert
        self._task: asyncio.Future[None] | None = None
        self._seq = 0
        self._handled_seq = 0
        self._death_reported: set[int] = set()
        self._boot_started = False
        self._last_attempt_today: str | None = None
        self._stopping = False
        self._phase: str | None = None
        self._phase_start = 0
        self._stuck_reported: set[tuple[int, str]] = set()
        self._eval_ok_ns: int | None = None
        self._pending_halt: tuple[str, int] | None = None
        self._heartbeat_stopped = False
        self._tick_fault = False
        self._outbox: list[tuple[str, str, str]] = []
        self._ingest_pending: Callable[[], int] | None = None
        self._liveness_seeded = False
        self._last_settled_seq: int | None = None
        self._settled_dirty = False

    def bind_ingest_pending(self, pending: Callable[[], int]) -> None:
        """Late-bind the ingest guard's retry-queue length (a reconcile waits for zero)."""
        self._ingest_pending = pending

    # -- observability -----------------------------------------------------

    @property
    def task(self) -> asyncio.Future[None] | None:
        """The (strongly held) outstanding or last pass task."""
        return self._task

    @property
    def heartbeat_ok(self) -> bool:
        """``False`` while a halt write is pending, after a marker / flag-mark failure, or on a
        service fault: the watcher then withholds its heartbeat (D3)."""
        return not (self._heartbeat_stopped or self._pending_halt is not None or self._tick_fault)

    # -- the per-tick entry point ------------------------------------------

    def service(self, now_ns: int) -> None:
        """Integrity checks, pending-halt retry, alert retry, then start a pass if one is due.

        Synchronous and cheap; never raises (a fault withholds this tick's heartbeat)."""
        self._tick_fault = False
        try:
            self._check_integrity()
            self._flush_pending_halt()
            self._flush_outbox()
        except Exception as exc:  # noqa: BLE001 - contained; the missing heartbeat is the signal
            self._tick_fault = True
            logger.error("exec_par stage evaluator service failed: %s", type(exc).__name__)
        try:
            self._poll_settled_seq()
        except Exception as exc:  # noqa: BLE001 - isolated: a bad poll never blocks scheduling
            self._tick_fault = True
            logger.error("exec_par settled_pnl_seq poll failed: %s", type(exc).__name__)
        try:
            self._maybe_start(now_ns)
        except Exception as exc:  # noqa: BLE001 - contained; the missing heartbeat is the signal
            self._tick_fault = True
            logger.error("exec_par stage evaluator service failed: %s", type(exc).__name__)

    def cancel(self) -> None:
        """``on_stop``: cancel the outstanding task (threadsafe) and start no more passes."""
        self._stopping = True
        task = self._task
        if task is None or task.done():
            return
        loop = task.get_loop()
        try:
            current: asyncio.AbstractEventLoop | None = asyncio.get_running_loop()
        except RuntimeError:
            current = None
        if current is loop:
            task.cancel()
        elif not loop.is_closed():
            loop.call_soon_threadsafe(task.cancel)

    # -- scheduling and integrity ---------------------------------------------

    def _poll_settled_seq(self) -> None:
        read = self._ports.settled_pnl_seq
        if read is None:
            return
        value = read()
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError("settled_pnl_seq must return an int")
        if self._last_settled_seq is not None and value != self._last_settled_seq:
            self._settled_dirty = True
        self._last_settled_seq = value

    def _maybe_start(self, now_ns: int) -> None:
        if self._stopping:
            return
        task = self._task
        if task is not None and not task.done():
            return
        today = self._ports.governed.today(now_ns)
        if self._boot_started and today == self._last_attempt_today and not self._settled_dirty:
            return
        self._settled_dirty = False
        self._boot_started = True
        self._last_attempt_today = today
        self._seq += 1
        seq = self._seq
        new_task = asyncio.get_running_loop().create_task(
            self._run(seq, today), name=f"exec_par_stage_eval_{seq}"
        )
        new_task.add_done_callback(lambda done: self._on_done(done, seq))
        self._task = new_task

    def _on_done(self, task: asyncio.Future[None], seq: int) -> None:
        if self._stopping:
            return
        if task.cancelled() or task.exception() is not None:
            self._report_death(seq)

    def _report_death(self, seq: int) -> None:
        if seq in self._death_reported or self._handled_seq == seq:
            return
        self._death_reported.add(seq)
        self._integrity(REASON_TASK_DIED)

    def _check_integrity(self) -> None:
        task = self._task
        if task is not None and task.done() and not self._stopping:
            self._report_death(self._seq)  # per-tick check, independent of the done-callback
        if task is None or task.done() or self._phase is None:
            return
        age = self._ports.monotonic_ns() - self._phase_start
        if self._phase == _PHASE_EVALUATE and age > STAGE_EVAL_STUCK_NS:
            self._report_once(REASON_STUCK)
        elif self._phase == _PHASE_RECONCILE and age > RECONCILE_BOUND_NS:
            self._report_once(REASON_RECONCILE_STUCK)

    def _report_once(self, reason: str) -> None:
        key = (self._seq, reason)
        if key in self._stuck_reported:
            return
        self._stuck_reported.add(key)
        self._integrity(reason)

    # -- halts and alerts ----------------------------------------------------

    def _integrity(self, reason: str, *, announce: bool = True) -> None:
        """An integrity halt (no flag). A halt write that raises stays pending."""
        if announce:
            event = (
                EVENT_FAIL
                if reason.startswith(_FAIL_PREFIX)
                else _EVENT_OF_REASON.get(reason, EVENT_INTEGRITY)
            )
            self._emit("CRITICAL", event, f"integrity halt reason={reason}")
        self._latch_halt(reason, self._ports.wall_ns())

    def _latch_halt(self, reason: str, ts_ns: int) -> bool:
        try:
            self._halt(reason, ts_ns)
        except Exception as exc:  # noqa: BLE001 - D3: heartbeat withheld, retried next service
            logger.error("exec_par stage halt write failed (%s): %s", reason, type(exc).__name__)
            if self._pending_halt is None:
                self._pending_halt = (reason, ts_ns)
            return False
        return True

    def _flush_pending_halt(self) -> None:
        pending = self._pending_halt
        if pending is None:
            return
        self._pending_halt = None
        self._latch_halt(*pending)

    def _emit(self, severity: str, event: str, detail: str) -> None:
        try:
            sent = self._alert(severity, event, detail)
        except Exception:  # noqa: BLE001 - a lost alert is retried, never fatal
            sent = False
        if not sent and len(self._outbox) < _OUTBOX_MAX:
            self._outbox.append((severity, event, detail))

    def _flush_outbox(self) -> None:
        queued, self._outbox = self._outbox, []
        for item in queued:
            self._emit(*item)

    # -- one pass -------------------------------------------------------------

    async def _run(self, seq: int, today: str) -> None:
        try:
            await self._pass(today)
        except asyncio.CancelledError:
            raise
        except _PassFailure as failure:
            self._integrity(failure.reason)
        except Exception as exc:  # noqa: BLE001 - every exception ends in a halt
            self._integrity(f"{_FAIL_PREFIX}pass:{type(exc).__name__}")
        finally:
            self._phase = None
        self._handled_seq = seq

    def _telemetry(self, write: Callable[[], object]) -> None:
        try:
            write()
        except Exception as exc:  # noqa: BLE001 - BG-1 write failure is an integrity halt
            logger.error("exec_par stage telemetry write failed: %s", type(exc).__name__)
            raise _PassFailure(REASON_TELEMETRY) from None

    async def _pass(self, today: str) -> None:
        ports = self._ports
        self._seed_liveness()
        start = ports.wall_ns()
        self._phase, self._phase_start = _PHASE_RECONCILE, ports.monotonic_ns()
        self._telemetry(lambda: ports.counters.write_reconcile_phase(start_ns=start, ok_ns=None))
        if ports.await_ready is not None:
            await ports.await_ready()
        pending = self._ingest_pending
        if pending is None:  # unbound is NOT "nothing queued": fail closed
            raise _PassFailure(f"{_FAIL_PREFIX}ingest_unbound")
        while pending() > 0:  # never reconcile over a queued retry (no double count)
            await asyncio.sleep(ports.ingest_poll_s)
        result = self._reconcile(today)  # sync, no await since the queue check
        await asyncio.sleep(0)

        eval_start = ports.wall_ns()
        self._phase, self._phase_start = _PHASE_EVALUATE, ports.monotonic_ns()
        previous_ok = self._eval_ok_ns
        self._telemetry(
            lambda: ports.store.write_stage_eval_liveness(
                StageEvalLiveness(eval_start, previous_ok)
            )
        )
        if ports.refresh_settled_pnl is not None:
            await ports.refresh_settled_pnl()
        await asyncio.sleep(0)
        verdict, elapsed = self._timed_evaluate(today, result.status, eval_start)
        self._phase = None

        now = ports.wall_ns()
        stampable = self._apply(verdict, now)
        slow = elapsed > STAGE_EVAL_SLOW_NS
        if slow:
            self._integrity(REASON_SLOW)
        if stampable and not slow:
            self._telemetry(
                lambda: ports.store.write_stage_eval_stamp(StageEvalStamp(now, ports.boot_ns))
            )
            self._eval_ok_ns = now
            self._telemetry(
                lambda: ports.store.write_stage_eval_liveness(StageEvalLiveness(eval_start, now))
            )

    def _reconcile(self, today: str) -> PassResult:
        ports = self._ports
        try:
            through = max({today, *ports.governed.open_days_at(ports.wall_ns())})
            labels = stage_day_labels(
                ports.store.read_stage_reset(),
                ports.store.read_epoch_rows(),
                ports.governed,
                today,
                through,
            )
            result = run_reconcile_pass(
                labels,
                mass_status_ingested=ports.mass_status_ingested,
                counters=ports.counters,
                sources=ports.sources,
                excluded=ports.store,
                monotonic_ns=ports.monotonic_ns,
                wall_ns=ports.wall_ns,
                counters_expected=ports.counters_expected,
            )
        except ReconcileOrderingError:
            raise _PassFailure(f"{_FAIL_PREFIX}reconcile_ordering") from None
        except Exception as exc:  # noqa: BLE001 - mapped to a halt reason
            raise _PassFailure(f"{_FAIL_PREFIX}reconcile:{type(exc).__name__}") from None
        for rebuilt in result.rebuild_events:
            self._emit(
                "WARN",
                EVENT_COUNTER_REBUILT,
                f"day={rebuilt.day} mismatch_kinds={','.join(rebuilt.mismatch_kinds)}",
            )
        for excluded in result.excluded_events:
            self._emit("CRITICAL", EVENT_DAY_EXCLUDED, f"day={excluded.day} cause={excluded.cause}")
        if result.excluded_events:
            self._integrity(REASON_DAY_EXCLUDED, announce=False)
        return result

    def _snapshot(self, today: str, status: PassStatus, now_ns: int) -> StageSnapshot:
        ports = self._ports
        try:
            return build_stage_snapshot(
                ports.store,
                ports.counters,
                SnapshotInputs(
                    now_ns=now_ns,
                    today=today,
                    configured_k=ports.configured_k,
                    effective_k=ports.effective_k(),
                    pass_status=status,
                    governed=ports.governed,
                    predicates=ports.predicates,
                    serial_baseline=ports.serial_baseline(),
                    counted_denial=ports.counted_denial,
                    on_read_error=self._log_read_error,
                ),
            )
        except Exception as exc:  # noqa: BLE001 - mapped to a halt reason
            raise _PassFailure(f"{_FAIL_PREFIX}snapshot:{type(exc).__name__}") from None

    def _seed_liveness(self) -> None:
        """Seed ``previous_ok`` from the store once, so a restart never writes None over it."""
        if self._liveness_seeded:
            return
        try:
            row = self._ports.store.read_stage_eval_liveness()
        except Exception as exc:  # noqa: BLE001 - a corrupt row is an integrity failure
            logger.error("exec_par liveness read failed: %s", type(exc).__name__)
            raise _PassFailure(f"{_FAIL_PREFIX}liveness_read") from None
        self._eval_ok_ns = None if row is None else row.stage_eval_last_ok_ns
        self._liveness_seeded = True

    @staticmethod
    def _log_read_error(what: str, day: str, exc_type: str) -> None:
        logger.error("exec_par snapshot read failed: what=%s day=%s exc=%s", what, day, exc_type)

    def _timed_evaluate(self, today: str, status: PassStatus, now_ns: int) -> tuple[Verdict, int]:
        """The synchronous span (snapshot build + pure evaluation) against the 2 s bound."""
        clock = self._ports.monotonic_ns
        began = clock()
        snapshot = self._snapshot(today, status, now_ns)
        try:
            verdict = self._ports.evaluate(snapshot)
        except Exception as exc:  # noqa: BLE001 - mapped to a halt reason
            raise _PassFailure(f"{_FAIL_PREFIX}evaluate:{type(exc).__name__}") from None
        return verdict, clock() - began

    # -- verdict handling -------------------------------------------------------

    def _apply(self, verdict: Verdict, now: int) -> bool:
        """Apply one verdict; ``True`` if the pass may stamp."""
        kind = verdict.kind
        if kind is VerdictKind.STOP:
            return self._apply_stop(verdict, now)
        if kind is VerdictKind.FAIL:
            reason = verdict.reason or f"{_FAIL_PREFIX}unknown"
            self._integrity(reason)
            self._write_report(verdict, now, best_effort=True)
            return False
        self._write_report(verdict, now)
        if kind is VerdictKind.HOLD:
            self._emit("WARN", EVENT_HOLD, self._hold_detail(verdict))
        elif kind is VerdictKind.PROMOTION_ELIGIBLE:
            blockers = ",".join(verdict.look_blockers) or "none"
            self._emit(
                "WARN",
                EVENT_PROMOTION_ELIGIBLE,
                f"look={verdict.look_number} blockers={blockers}; the node never promotes "
                "(requires the BG-10(f) record)",
            )
        return True

    @staticmethod
    def _hold_detail(verdict: Verdict) -> str:
        detail = f"reason={verdict.reason}"
        if verdict.reason == HOLD_CLEANUP_DEMOTION:
            detail += f" target_k={verdict.target_k}; the coordinator commits the lower K"
        return detail

    def _apply_stop(self, verdict: Verdict, now: int) -> bool:
        reason = verdict.reason or f"{_FAIL_PREFIX}unknown"
        marker_ok = self._write_marker(reason, now)
        if not marker_ok:
            self._heartbeat_stopped = True  # D3
            self._emit("CRITICAL", EVENT_INTEGRITY, f"integrity halt reason={REASON_MARKER_FAIL}")
        self._latch_halt(reason if marker_ok else REASON_MARKER_FAIL, now)
        if verdict.sets_flag:
            self._set_flag(reason, now)
        outcome = None if verdict.outcome is None else verdict.outcome.value
        self._emit(
            "CRITICAL",
            EVENT_STOP,
            f"reason={reason} outcome={outcome} target_k={verdict.target_k} "
            f"stops={','.join(verdict.stops)}",
        )
        self._write_report(verdict, now)
        return marker_ok

    def _write_marker(self, reason: str, now: int) -> bool:
        try:
            self._ports.store.write_stop_verdict(StopVerdict(reason=reason, ts_ns=now))
        except Exception as exc:  # noqa: BLE001 - becomes stop_marker_write_fail
            logger.error("exec_par stop marker write failed: %s", type(exc).__name__)
            return False
        return True

    def _set_flag(self, reason: str, now: int) -> None:
        store = self._ports.store
        try:
            store.write_force_k1_flag(ForceK1Flag(reason=reason, ts_ns=now, set_by="stage_eval"))
            return
        except Exception as exc:  # noqa: BLE001 - logged at ERROR; M3 marks the breaker record
            logger.error("exec_par force-K1 flag write failed: %s", type(exc).__name__)
        self._emit("CRITICAL", EVENT_FLAG_WRITE_FAILED, f"flag write failed for reason={reason}")
        try:
            store.mark_flag_write_failed()
        except Exception as exc:  # noqa: BLE001 - D3: cannot record the loss, stop the heartbeat
            logger.error("exec_par flag_write_failed mark failed: %s", type(exc).__name__)
            self._heartbeat_stopped = True

    def _write_report(self, verdict: Verdict, now: int, *, best_effort: bool = False) -> None:
        doc = StageReportDoc(
            ts_ns=now,
            verdict=verdict.kind.value,
            reason=verdict.reason,
            report_json=None if verdict.report is None else report_json(verdict.report),
        )
        try:
            self._ports.store.write_stage_report(doc)
        except Exception as exc:  # noqa: BLE001
            logger.error("exec_par stage report write failed: %s", type(exc).__name__)
            if not best_effort:
                raise _PassFailure(REASON_TELEMETRY) from None
