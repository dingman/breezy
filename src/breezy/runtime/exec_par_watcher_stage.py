"""EXEC-PAR BG-5b/BG-6: the stage-evaluator and intraday glue of ``BreakerWatcherActor`` (a mixin).

BG-6: the same ports arm an :class:`~breezy.runtime.exec_par_intraday.IntradayMonitor` that is
checked on every tick right after the evaluator service and acts through the evaluator's writers.

When the K>1 watcher is given ``stage_eval_ports`` it owns a
:class:`~breezy.runtime.exec_par_stage_runner.StageEvaluator`. The tick only calls its cheap
``service()`` (integrity checks, pending-halt retry, scheduling); each pass runs in its own
detached task, never inside ``tick()``, and ``on_stop`` cancels it. While the evaluator reports
a halt write pending or a marker / flag-mark failure, the heartbeat is withheld (D3).
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from breezy.runtime.exec_par_counter_ingest import AmbiguousMarkSource
from breezy.runtime.exec_par_ingest_guard import IngestGuard
from breezy.runtime.exec_par_intraday import IntradayMonitor
from breezy.runtime.exec_par_stage_runner import StageEvalPorts, StageEvaluator

logger = logging.getLogger(__name__)

__all__ = ["HeartbeatWithheldError", "StageEvalWatcherMixin", "combined_ingest_pending"]


def combined_ingest_pending(
    guard: IngestGuard, marks: AmbiguousMarkSource | None
) -> Callable[[], int]:
    """Queued ingest events plus durable AMBIGUOUS marks not yet ingested (both must drain)."""

    def pending() -> int:
        return guard.pending + (0 if marks is None else len(marks.ambiguous_marks_pending()))

    return pending


class HeartbeatWithheldError(RuntimeError):
    """The stage evaluator has an unresolved integrity write: do not heartbeat (D3)."""


class StageEvalWatcherMixin:
    """Holds the optional evaluator; every method is a no-op when there is none."""

    _stage_eval: StageEvaluator | None = None
    _intraday: IntradayMonitor | None = None
    _intraday_ports: StageEvalPorts | None = None
    _intraday_wiring_failed = False

    def _init_stage_eval(
        self,
        ports: StageEvalPorts | None,
        *,
        halt: Callable[[str, int], None],
        alert: Callable[[str, str, str], bool],
    ) -> None:
        self._stage_eval = None if ports is None else StageEvaluator(ports, halt=halt, alert=alert)
        self._intraday = None
        self._intraday_ports = ports
        self._intraday_wiring_failed = False

    @property
    def stage_evaluator(self) -> StageEvaluator | None:
        return self._stage_eval

    def _stage_eval_bind_guard(
        self, guard: IngestGuard | None, marks: AmbiguousMarkSource | None
    ) -> None:
        """A reconcile never runs over queued events or pending AMBIGUOUS marks (BG-1b / BG-1d).

        Without a guard nothing is bound, and the pass fails closed (``ingest_unbound``)."""
        if self._stage_eval is not None and guard is not None:
            self._stage_eval.bind_ingest_pending(combined_ingest_pending(guard, marks))

    def _stage_eval_cancel(self) -> None:
        if self._stage_eval is not None:
            self._stage_eval.cancel()

    def _stage_eval_service(self, now_ns: int) -> None:
        evaluator = self._stage_eval
        if evaluator is None:
            return
        evaluator.service(now_ns)  # never raises; schedules, never awaits a pass
        self._intraday_check(evaluator, now_ns)

    def _intraday_check(self, evaluator: StageEvaluator, now_ns: int) -> None:
        """BG-6: the intraday monitor, built on first use and acting through the evaluator's own
        writers (M3 order, D3). Unusable ports are an integrity halt, never a silent skip."""
        if self._intraday is None and not self._intraday_wiring_failed:
            ports = self._intraday_ports
            try:
                if ports is None:
                    raise ValueError("no stage-eval ports")
                self._intraday = IntradayMonitor(
                    reads=ports.store,
                    counters=ports.counters,
                    governed=ports.governed,
                    boot_ns=ports.boot_ns,
                    intraday=ports.intraday,
                    stop=evaluator.stop_class,
                    integrity=evaluator.integrity_halt,
                )
            except Exception as exc:  # noqa: BLE001 - fail closed, once
                self._intraday_wiring_failed = True
                logger.error("exec_par intraday monitor wiring failed: %s", type(exc).__name__)
                evaluator.integrity_halt(f"stage_eval_fail:intraday_wiring:{type(exc).__name__}")
        if self._intraday is not None:
            self._intraday.check(now_ns)  # never raises

    def _stage_eval_gate(self) -> None:
        if self._stage_eval is not None and not self._stage_eval.heartbeat_ok:
            raise HeartbeatWithheldError("stage evaluator integrity write unresolved")
