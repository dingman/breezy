"""EXEC-PAR BG-5b: the stage-evaluator glue of ``BreakerWatcherActor`` (a mixin).

When the K>1 watcher is given ``stage_eval_ports`` it owns a
:class:`~breezy.runtime.exec_par_stage_runner.StageEvaluator`. The tick only calls its cheap
``service()`` (integrity checks, pending-halt retry, scheduling); each pass runs in its own
detached task, never inside ``tick()``, and ``on_stop`` cancels it. While the evaluator reports
a halt write pending or a marker / flag-mark failure, the heartbeat is withheld (D3).
"""

from __future__ import annotations

from collections.abc import Callable

from breezy.runtime.exec_par_stage_runner import StageEvalPorts, StageEvaluator

__all__ = ["HeartbeatWithheldError", "StageEvalWatcherMixin"]


class HeartbeatWithheldError(RuntimeError):
    """The stage evaluator has an unresolved integrity write: do not heartbeat (D3)."""


class StageEvalWatcherMixin:
    """Holds the optional evaluator; every method is a no-op when there is none."""

    _stage_eval: StageEvaluator | None = None

    def _init_stage_eval(
        self,
        ports: StageEvalPorts | None,
        *,
        halt: Callable[[str, int], None],
        alert: Callable[[str, str, str], bool],
    ) -> None:
        self._stage_eval = None if ports is None else StageEvaluator(ports, halt=halt, alert=alert)

    @property
    def stage_evaluator(self) -> StageEvaluator | None:
        return self._stage_eval

    def _stage_eval_cancel(self) -> None:
        if self._stage_eval is not None:
            self._stage_eval.cancel()

    def _stage_eval_service(self, now_ns: int) -> None:
        if self._stage_eval is not None:
            self._stage_eval.service(now_ns)  # never raises; schedules, never awaits a pass

    def _stage_eval_gate(self) -> None:
        if self._stage_eval is not None and not self._stage_eval.heartbeat_ok:
            raise HeartbeatWithheldError("stage evaluator integrity write unresolved")
