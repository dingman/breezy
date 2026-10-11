"""EXEC-PAR BG-6: the in-node intraday monitor (D-PREREG r4 1a, s5, s9; r4.1 K4, L1; r4.3 M3).

Run from the K>1 watcher's tick, on the loop thread, right after the BG-5b evaluator service. It
gathers the stage-window inputs from the BG-1 rows, applies the PURE predicates of
:mod:`breezy.runtime.exec_par_intraday_rules` and acts through the BG-5b evaluator's own writers,
never its own copies of them:

* a stop-class rule (s5 Clopper-Pearson, s5 burst, s9 station-day 0.25) goes through
  ``StageEvaluator.stop_class``: the ``stop_verdict`` marker FIRST, then the entries-only halt in
  ``BREAKER_KEY``, then the force-K1 flag (M3, r4 1a "Write order");
* an integrity condition (stale or never-written stamp, an unreadable stamp, a failed read, an
  unbound port, a predicate raise or non-bool) goes through ``StageEvaluator.integrity_halt``:
  a halt, no flag, no marker.

Window (D-PREREG s5): entries with ARM time at or after the latest ``stage_reset`` instant, with
excluded days skipped, over every label from the stage start through the latest OPEN label (BG-5c
N-C: open days are evaluated immediately). Labels come from the one day convention
(``entry_day``); the floor labels (``open_days_at(floor.ts)``) are read from the per-entry rows and
filtered by arm time, every later label from the BG-1 day counts. s9 counts ALL open positions of
each station-day, regardless of arm time or floor. AMBIGUOUS entries without a station-day
(``unattributed``) are not part of any window here; the daily evaluator reports them.

A condition is acted on when it STARTS (edge-triggered): the halt is sticky and the marker is
durable, so repeating them every 5 s tick would only flood the store. A pending halt write, a flag
write failure and a marker failure are carried by the evaluator (D3, M3). ``check`` never raises.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Protocol

from breezy.runtime.exec_par_days_port import DayConvention
from breezy.runtime.exec_par_intraday_rules import (
    IntradayInputError,
    IntradayInputs,
    IntradayPredicateError,
    OpenCostPort,
    intraday_stop_reasons,
)
from breezy.runtime.exec_par_reconcile import DayCounts
from breezy.runtime.exec_par_records import (
    AmbiguousRow,
    EpochRow,
    ExcludedDay,
    OrderAnchor,
    StageEvalStamp,
    StageReset,
)
from breezy.runtime.exec_par_stage_snapshot import stage_day_labels
from breezy.runtime.exec_par_stamp_gate import (
    REASON_STAMP_STALE,
    REASON_STAMP_UNREADABLE,
    stamp_denial,
)

__all__ = [
    "REASON_INTRADAY_UNBOUND",
    "IntradayCounts",
    "IntradayMonitor",
    "IntradayPorts",
    "IntradayReads",
    "gather_intraday_inputs",
]

logger = logging.getLogger(__name__)

_FAIL_PREFIX: Final[str] = "stage_eval_fail:"
REASON_INTRADAY_UNBOUND: Final[str] = f"{_FAIL_PREFIX}intraday_unbound"
_REASON_INPUTS: Final[str] = f"{_FAIL_PREFIX}intraday_inputs"
_REASON_READ_PREFIX: Final[str] = f"{_FAIL_PREFIX}intraday_read:"


class IntradayReads(Protocol):
    """The latch reads the monitor uses (a subset of ``SubmitIntentLatch``; loop thread)."""

    def read_stage_reset(self) -> StageReset | None: ...
    def read_epoch_rows(self) -> tuple[EpochRow, ...]: ...
    def read_excluded_days(self) -> tuple[ExcludedDay, ...]: ...
    def read_order_anchors(self, day: str) -> tuple[OrderAnchor, ...]: ...
    def read_ambiguous(self, day: str) -> tuple[object, ...]: ...
    def read_stage_eval_stamp(self) -> StageEvalStamp | None: ...


class IntradayCounts(Protocol):
    """The slice of ``CounterStorePort`` the monitor reads."""

    def read_day_counts(self, day: str) -> DayCounts | None: ...


@dataclass(frozen=True, slots=True)
class IntradayPorts:
    """The s9 inputs the node's wiring supplies (K6: aggregates in, a bool out).

    ``open_cost_by_station_day()`` returns the open cost of ALL open positions per
    ``<station>@<day>`` (summed Decimals; they never leave the port's caller and are never
    logged). ``open_cost_port`` is the ledger's ``open_cost_exceeds_budget_fraction``.
    """

    open_cost_port: OpenCostPort
    open_cost_by_station_day: Callable[[], Mapping[str, Decimal]]


def _ambiguous_rows(rows: tuple[object, ...]) -> tuple[AmbiguousRow, ...]:
    picked = tuple(row for row in rows if isinstance(row, AmbiguousRow))
    if len(picked) != len(rows):
        raise IntradayInputError("ambiguous rows are not AmbiguousRow")
    return picked


def gather_intraday_inputs(
    *,
    reads: IntradayReads,
    counters: IntradayCounts,
    governed: DayConvention,
    intraday: IntradayPorts,
    now_ns: int,
) -> IntradayInputs:
    """The stage-window totals, AMBIGUOUS arm times and open costs (BG-4 ``--dry-eval`` reuses)."""
    floor = reads.read_stage_reset()
    epochs = reads.read_epoch_rows()
    excluded = frozenset(row.day for row in reads.read_excluded_days())
    today = governed.today(now_ns)
    through = max({today, *governed.open_days_at(now_ns)})
    labels = stage_day_labels(floor, epochs, governed, today, through)
    floor_labels = frozenset() if floor is None else governed.open_days_at(floor.ts)
    posted = 0
    ambiguous = 0
    arm_times: list[int] = []
    for day in labels:
        if day in excluded:
            continue
        if floor is not None and day in floor_labels:
            cutoff = floor.ts
            anchors = reads.read_order_anchors(day)
            marks = tuple(
                r for r in _ambiguous_rows(reads.read_ambiguous(day)) if r.arm_ns >= cutoff
            )
            posted += sum(1 for a in anchors if a.arm_ns >= cutoff)
            ambiguous += len(marks)
            arm_times.extend(r.arm_ns for r in marks)
            continue
        counts = counters.read_day_counts(day)
        if counts is None:
            raise IntradayInputError("day counts missing")
        posted += counts.posted_entries
        ambiguous += counts.ambiguous
        if counts.ambiguous:
            arm_times.extend(r.arm_ns for r in _ambiguous_rows(reads.read_ambiguous(day)))
    return IntradayInputs(
        posted=posted,
        ambiguous=ambiguous,
        ambiguous_arm_ns=tuple(arm_times),
        open_cost_by_station_day=dict(intraday.open_cost_by_station_day()),
    )


class IntradayMonitor:
    """Evaluates the intraday rules and the stamp once per tick. Loop thread; never raises."""

    def __init__(
        self,
        *,
        reads: IntradayReads,
        counters: IntradayCounts,
        governed: DayConvention,
        boot_ns: int,
        intraday: IntradayPorts | None,
        stop: Callable[[str, int], bool],
        integrity: Callable[[str], None],
    ) -> None:
        self._reads = reads
        self._counters = counters
        self._governed = governed
        self._boot_ns = boot_ns
        self._intraday = intraday
        self._stop = stop
        self._integrity = integrity
        self._active_stops: frozenset[str] = frozenset()
        self._active_integrity: frozenset[str] = frozenset()

    def check(self, now_ns: int) -> None:
        """One evaluation. Stop-class rules first (their reason wins the sticky halt), then the
        integrity conditions; each fresh condition is acted on once.

        At most ONE new stop-class reason is acted on per check: ``stop_verdict`` markers are
        keyed by ``ts_ns`` and a second marker at the same instant would be refused. The others
        stay un-acted and are picked up on the next tick (5 s later); the first marker already
        forces the stop path (N1), so no stop is lost, only delayed by a tick.
        """
        try:
            stops, integrity = self._evaluate(now_ns)
        except Exception as exc:  # noqa: BLE001 - total by contract; an unknown fault is a halt
            stops, integrity = (), (f"{_FAIL_PREFIX}intraday:{type(exc).__name__}",)
        fresh = [reason for reason in stops if reason not in self._active_stops]
        acted = frozenset(fresh[:1])
        for reason in acted:
            self._stop(reason, now_ns)
        for reason in integrity:
            if reason not in self._active_integrity:
                self._integrity(reason)
        self._active_stops = (self._active_stops & frozenset(stops)) | acted
        self._active_integrity = frozenset(integrity)

    def _evaluate(self, now_ns: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
        stops: tuple[str, ...] = ()
        integrity: list[str] = []
        ports = self._intraday
        if ports is None:
            integrity.append(REASON_INTRADAY_UNBOUND)
        else:
            try:
                inputs = gather_intraday_inputs(
                    reads=self._reads,
                    counters=self._counters,
                    governed=self._governed,
                    intraday=ports,
                    now_ns=now_ns,
                )
                stops = intraday_stop_reasons(inputs, ports.open_cost_port)
            except IntradayPredicateError as exc:
                integrity.append(exc.reason)
            except IntradayInputError:
                integrity.append(_REASON_INPUTS)
            except Exception as exc:  # noqa: BLE001 - only the TYPE is kept: no value in a reason
                logger.error("exec_par intraday read failed: %s", type(exc).__name__)
                integrity.append(f"{_REASON_READ_PREFIX}{type(exc).__name__}")
        stamp_reason = self._stamp_reason(now_ns)
        if stamp_reason is not None:
            integrity.append(stamp_reason)
        return stops, tuple(integrity)

    def _stamp_reason(self, now_ns: int) -> str | None:
        """Stale or never-written (after 26 h) and unreadable stamps are integrity; a pending
        boot pass is only an entry denial (the latch's), never a halt."""
        try:
            stamp = self._reads.read_stage_eval_stamp()
        except Exception as exc:  # noqa: BLE001 - an unreadable stamp is fail-closed
            logger.error("exec_par stamp read failed: %s", type(exc).__name__)
            return REASON_STAMP_UNREADABLE
        denial = stamp_denial(stamp, boot_ns=self._boot_ns, now_ns=now_ns)
        return denial if denial == REASON_STAMP_STALE else None
