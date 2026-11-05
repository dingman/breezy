"""EXEC-PAR BG-1b: a never-raising guard around counter ingestion (retry, gappy mark, fault ring).

Nothing here may raise into the msgbus or the watcher tick. A failed event is:

1. counted (``fault_count`` is monotonic for the life of the process: BG-6 raises its
   integrity halt on any increase);
2. kept in a bounded in-memory retry queue (``QUEUE_CAP``) and retried, oldest first, on every
   tick before new work; an overflow drops the OLDEST event, counts it and gappy-marks its day;
3. gappy-marked for its attributed day (else its event-time day), so BG-1d reconciliation
   rebuilds that day from durable sources. If that mark cannot be written either, it is counted
   in ``gappy_write_failures``.

A retry that fails again is not a new fault (the first failure already was counted and marked).
AMBIGUOUS-mark faults need no queue: the ledger keeps the marks pending until acknowledged.
"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from typing import Any, Final

from breezy.runtime.exec_par_counter_ingest import (
    AmbiguousMarkSource,
    ExecParCounterError,
    ExecParCounterIngest,
)

__all__ = ["FAULT_RING", "QUEUE_CAP", "CounterUnexpectedError", "IngestGuard"]

logger = logging.getLogger(__name__)

QUEUE_CAP: Final[int] = 1000
FAULT_RING: Final[int] = 20
_GAPPY_CAUSE: Final[str] = "ingest_fault"


class CounterUnexpectedError(ExecParCounterError):
    """An untyped exception escaped ingestion (the original is chained as ``__cause__``)."""


class IngestGuard:
    """Loop-thread only; every public method is total (never raises)."""

    def __init__(
        self,
        ingest: ExecParCounterIngest,
        *,
        queue_cap: int = QUEUE_CAP,
        ring: int = FAULT_RING,
    ) -> None:
        if queue_cap <= 0 or ring <= 0:
            raise ValueError("queue_cap and ring must be positive")
        self._ingest = ingest
        self._queue_cap = queue_cap
        self._queue: deque[object] = deque()
        self._faults: deque[ExecParCounterError] = deque(maxlen=ring)
        self._fault_count = 0
        self._gappy_write_failures = 0
        self._overflow_count = 0

    # -- observability ------------------------------------------------------

    @property
    def fault_count(self) -> int:
        return self._fault_count

    @property
    def gappy_write_failures(self) -> int:
        return self._gappy_write_failures

    @property
    def overflow_count(self) -> int:
        return self._overflow_count

    @property
    def pending(self) -> int:
        return len(self._queue)

    @property
    def recent_faults(self) -> tuple[ExecParCounterError, ...]:
        return tuple(self._faults)

    # -- the three entry points ---------------------------------------------

    def handle(self, event: object, order_of: Callable[[Any], Any], now_ns: int) -> None:
        """Ingest one event; on any failure count, gappy-mark and queue it."""
        try:
            self._ingest.on_event(event, order_of)
        except Exception as exc:  # noqa: BLE001 - total by contract
            self._note_fault(exc)
            self._gappy(event, now_ns)
            self._enqueue(event, now_ns)

    def retry(self, order_of: Callable[[Any], Any], now_ns: int) -> None:
        """Retry every queued event, oldest first; survivors keep their place."""
        batch = list(self._queue)
        self._queue.clear()
        survivors: list[object] = []
        for event in batch:
            try:
                self._ingest.on_event(event, order_of)
            except Exception:  # noqa: BLE001 - total by contract
                survivors.append(event)
        self._queue.extendleft(reversed(survivors))

    def ingest_marks(self, marks: AmbiguousMarkSource, now_ns: int) -> None:
        """Ingest the ledger's pending AMBIGUOUS marks (they stay pending on a failure)."""
        try:
            self._ingest.ingest_ambiguous_marks(marks, now_ns=now_ns)
        except Exception as exc:  # noqa: BLE001 - total by contract
            self._note_fault(exc)

    # -- internals ----------------------------------------------------------

    def _note_fault(self, exc: Exception) -> None:
        if isinstance(exc, ExecParCounterError):
            fault = exc
        else:
            fault = CounterUnexpectedError(f"unexpected ingest failure ({type(exc).__name__})")
            fault.__cause__ = exc
        self._fault_count += 1
        self._faults.append(fault)
        logger.error("exec_par ingest fault: %s", type(fault).__name__)

    def _gappy(self, event: object, now_ns: int) -> None:
        try:
            day = self._ingest.gappy_day_of_event(event)
            if day is None:
                raise ValueError("no day")
            self._ingest.mark_gappy(day=day, cause=_GAPPY_CAUSE, ts_ns=now_ns)
        except Exception:  # noqa: BLE001 - total by contract
            self._gappy_write_failures += 1

    def _enqueue(self, event: object, now_ns: int) -> None:
        if len(self._queue) >= self._queue_cap:
            dropped = self._queue.popleft()
            self._overflow_count += 1
            self._note_fault(CounterUnexpectedError("ingest retry queue overflow"))
            self._gappy(dropped, now_ns)
        self._queue.append(event)
