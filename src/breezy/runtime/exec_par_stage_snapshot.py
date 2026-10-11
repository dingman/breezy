"""EXEC-PAR BG-5b: the PURE stage-snapshot builder (D-PREREG r4.1 K6).

Turns injected store reads and predicates into one immutable
:class:`~breezy.runtime.exec_par_stage_types.StageSnapshot` for the BG-5a evaluator. It is
pure: no clock (``now``, ``today`` and the day function are inputs), no logging, no
Nautilus, no ``breezy.adapters`` write path. Currency values are carried as the store
holds them and never printed; the one comparison against a budget fraction happens inside
the injected predicate port (K6).

Failure semantics (spec 10a: "a missing day or a None value counts as FAIL, never 0"):

* A per-day read that raises becomes a ``None`` field, so the evaluator FAILs with
  ``stage_eval_fail:missing_counter`` (or ``settled_pnl_missing``) instead of reading a
  default. The one exception is a fill detail that does not cover the counted fills: a BG-1d
  rebuild can restore counts but not per-fill slippage and fees, so such a day carries
  ``fills=None`` rather than a partial tuple.
* A stage-level read (floor, epochs, excluded days, looks, markers) that raises propagates:
  the wiring maps it to ``stage_eval_fail:snapshot``.

``denied_counted`` (the s6 numerator) needs the per-reason denial classification and the
BG-11 pre-filter WAIT counters, which do not exist yet. With no ``counted_denial``
classifier it is ``None`` (report-only before S3, a FAIL at S3: K7).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from breezy.runtime.exec_par_counter_ingest import UNATTRIBUTED
from breezy.runtime.exec_par_reconcile import DayCounts, PassStatus, RebuildRecord
from breezy.runtime.exec_par_records import (
    DenialRow,
    EpochRow,
    ExcludedDay,
    FillRow,
    LookRow,
    OpenCostFlag,
    SettledPnlDay,
    StageReset,
    StopVerdict,
    WindowPeak,
)
from breezy.runtime.exec_par_settled_pnl import settled_pnl_or_fail
from breezy.runtime.exec_par_stage_types import (
    DayCounters,
    DayPnl,
    LookOutcome,
    LookRecord,
    PnlPredicatePort,
    SerialBaseline,
    StageSnapshot,
)

__all__ = [
    "MAX_SNAPSHOT_DAYS",
    "SnapshotCounters",
    "SnapshotInputs",
    "SnapshotReads",
    "build_stage_snapshot",
    "stage_day_labels",
]

#: A day range wider than this is a clock or epoch fault, never walked.
MAX_SNAPSHOT_DAYS = 400


class SnapshotReads(Protocol):
    """The latch reads the builder uses (loop thread; a subset of ``SubmitIntentLatch``)."""

    def read_stage_reset(self) -> StageReset | None: ...
    def read_epoch_rows(self) -> tuple[EpochRow, ...]: ...
    def read_excluded_days(self) -> tuple[ExcludedDay, ...]: ...
    def read_looks(self) -> tuple[LookRow, ...]: ...
    def read_stop_verdicts_since(self, ts_ns: int) -> tuple[StopVerdict, ...]: ...
    def read_settled_pnl_day(self, day: str) -> SettledPnlDay | None: ...
    def read_fills(self, day: str) -> tuple[FillRow, ...]: ...
    def read_denials(self, day: str) -> tuple[DenialRow, ...]: ...
    def read_open_cost_flags(self, day: str) -> tuple[OpenCostFlag, ...]: ...
    def read_window_peaks(self, day: str) -> tuple[WindowPeak, ...]: ...
    def read_ambiguous(self, day: str) -> tuple[object, ...]: ...


class SnapshotCounters(Protocol):
    """The slice of ``CounterStorePort`` the builder reads (after the reconcile pass)."""

    def read_day_counts(self, day: str) -> DayCounts | None: ...
    def read_gappy_days(self) -> frozenset[str]: ...
    def read_pending_rebuild(self, day: str) -> RebuildRecord | None: ...


@dataclass(frozen=True, slots=True)
class SnapshotInputs:
    """Everything the builder needs that is not a store read."""

    now_ns: int
    today: str
    configured_k: int
    effective_k: int
    pass_status: PassStatus
    day_of_ns: Callable[[int], str]
    predicates: PnlPredicatePort
    serial_baseline: SerialBaseline | None
    #: ``None`` means no classification exists yet (BG-11): ``denied_counted`` is then ``None``.
    counted_denial: Callable[[str], bool] | None


def _first_k_gt1_day(
    epochs: tuple[EpochRow, ...], day_of_ns: Callable[[int], str], today: str
) -> str:
    for epoch in epochs:
        if epoch.effective_k > 1:
            return day_of_ns(epoch.boot_ts)
    return today


def _day_range(start: str, end: str) -> tuple[str, ...]:
    first, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if first > last:
        return (end,)  # a clock fault: the evaluator FAILs on it; read only today
    count = (last - first).days + 1
    if count > MAX_SNAPSHOT_DAYS:
        raise ValueError("snapshot day range is implausibly wide")
    return tuple((first + dt.timedelta(days=i)).isoformat() for i in range(count))


def stage_day_labels(
    floor: StageReset | None,
    epochs: tuple[EpochRow, ...],
    day_of_ns: Callable[[int], str],
    today: str,
) -> tuple[str, ...]:
    """The days a pass reads and reconciles: the earlier of the first K>1 day and the floor
    day, through ``today``. A clock fault (start after today) reads ``today`` only."""
    first_k_day = _first_k_gt1_day(epochs, day_of_ns, today)
    start = first_k_day if floor is None else min(first_k_day, day_of_ns(floor.ts))
    return _day_range(start, today)


def _safe[T](read: Callable[[], T]) -> T | None:
    """A per-day read: a raise is a missing value (never a default)."""
    try:
        return read()
    except Exception:  # noqa: BLE001 - mapped to None; the evaluator FAILs on a missing value
        return None


def _denied_counted(
    reads: SnapshotReads, day: str, classify: Callable[[str], bool] | None
) -> int | None:
    if classify is None:
        return None

    def count() -> int:
        return sum(1 for row in reads.read_denials(day) if classify(row.reason))

    return _safe(count)


def _fill_detail(reads: SnapshotReads, day: str, counted: int | None) -> tuple[FillRow, ...] | None:
    rows = _safe(lambda: reads.read_fills(day))
    if rows is None or counted is None:
        return None
    if len({row.client_order_id for row in rows}) != counted:
        return None  # counts rebuilt from the durable sources: no per-fill detail to evaluate
    return rows


def _day_counters(
    reads: SnapshotReads, counters: SnapshotCounters, inputs: SnapshotInputs, day: str
) -> DayCounters:
    counts = _safe(lambda: counters.read_day_counts(day))
    return DayCounters(
        day=day,
        posted=None if counts is None else counts.posted_entries,
        ambiguous=None if counts is None else counts.ambiguous,
        denied_counted=_denied_counted(reads, day, inputs.counted_denial),
        fills=_fill_detail(reads, day, None if counts is None else counts.fills),
        open_flags=_safe(lambda: reads.read_open_cost_flags(day)),
        windows=_safe(lambda: reads.read_window_peaks(day)),
    )


def _day_pnl(reads: SnapshotReads, day: str) -> DayPnl | None:
    """``None``: no row (omitted); a ``DayPnl`` with a ``None`` reading: row unreadable."""
    try:
        row = reads.read_settled_pnl_day(day)
        return None if row is None else DayPnl(day, settled_pnl_or_fail(row))
    except Exception:  # noqa: BLE001 - an unreadable row is FAIL territory, never zero
        return DayPnl(day, None)


def _unattributed_ambiguous(reads: SnapshotReads) -> int | None:
    return _safe(lambda: len(reads.read_ambiguous(UNATTRIBUTED)))


def build_stage_snapshot(
    reads: SnapshotReads, counters: SnapshotCounters, inputs: SnapshotInputs
) -> StageSnapshot:
    """Gather one snapshot on the loop thread. Stage-level read failures propagate."""
    floor = reads.read_stage_reset()
    epochs = reads.read_epoch_rows()
    excluded = reads.read_excluded_days()
    looks = tuple(LookRecord(x.day, LookOutcome(x.outcome)) for x in reads.read_looks())
    verdicts = reads.read_stop_verdicts_since(0)

    labels = stage_day_labels(floor, epochs, inputs.day_of_ns, inputs.today)

    pnl = tuple(row for day in labels if (row := _day_pnl(reads, day)) is not None)
    gappy = counters.read_gappy_days()
    pending = frozenset(day for day in labels if counters.read_pending_rebuild(day) is not None)
    return StageSnapshot(
        today=inputs.today,
        configured_k=inputs.configured_k,
        effective_k=inputs.effective_k,
        floor=floor,
        epochs=epochs,
        excluded_days=excluded,
        days=tuple(_day_counters(reads, counters, inputs, day) for day in labels),
        pnl_days=pnl,
        gappy_days=gappy,
        pending_rebuild_days=pending,
        pass_status=inputs.pass_status,
        looks=looks,
        stop_verdicts=verdicts,
        serial_baseline=inputs.serial_baseline,
        unattributed_ambiguous=_unattributed_ambiguous(reads),
        day_of_ns=inputs.day_of_ns,
        predicates=inputs.predicates,
    )
