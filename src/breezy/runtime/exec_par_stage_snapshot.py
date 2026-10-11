"""EXEC-PAR BG-5b: the PURE stage-snapshot builder (D-PREREG r4.1 K6).

Turns injected store reads and predicates into one immutable
:class:`~breezy.runtime.exec_par_stage_types.StageSnapshot` for the BG-5a evaluator. It is
pure: no clock (``now``, ``today`` and the day function are inputs), no logging, no
Nautilus, no ``breezy.adapters`` write path. Currency values are carried as the store
holds them and never printed; the one comparison against a budget fraction happens inside
the injected predicate port (K6).

Day model (BG-5c R1, A4, A5). Labels are per-station standard-time days: the snapshot covers the
labels from the earlier of the first K>1 boot and the stations' floor days through the LATEST
open label of any governed station (``governed.open_days_at(now)``), plus a bounded probe past
that for entries that lead ``today`` by more than the two-day allowance (the evaluator turns those
into ``counter_missing``). Each station's floor label also gets a post-floor STUB built from the
per-entry rows (``arm_ns >= floor.ts``); every other label uses the whole-day counters. A stub
whose rows cannot account for the stored counts (a BG-1d rebuild restored counts, not rows) is
``pre_floor_unknown``.

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

import dataclasses
import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from breezy.runtime.exec_par_counter_ingest import UNATTRIBUTED
from breezy.runtime.exec_par_days_port import DayConvention
from breezy.runtime.exec_par_reconcile import DayCounts, PassStatus, RebuildRecord
from breezy.runtime.exec_par_records import (
    AmbiguousRow,
    DenialRow,
    EpochRow,
    ExcludedDay,
    FillRow,
    LookRow,
    OpenCostFlag,
    OrderAnchor,
    SettledPnlDay,
    StageReset,
    StopVerdict,
    WindowPeak,
    canonical_decimal,
)
from breezy.runtime.exec_par_settled_pnl import settled_pnl_or_fail
from breezy.runtime.exec_par_stage_types import (
    MAX_OPEN_DAYS_AHEAD,
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

#: A day range wider than this is a clock or epoch fault, never walked. The range is bounded
#: by the spec itself: a stage is at most 15 days (+5 extension) plus the days since the first
#: K>1 boot that s15-cumulative needs, so 400 days is far beyond any real stage.
MAX_SNAPSHOT_DAYS = 400

#: How many days past ``today + MAX_OPEN_DAYS_AHEAD`` are probed for entries that lead ``today``
#: by more than the allowance. Bounded: day-keyed rows cannot be enumerated without a day.
AHEAD_PROBE_DAYS = 7


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
    def read_order_anchors(self, day: str) -> tuple[OrderAnchor, ...]: ...
    def read_latest_entry_day(self) -> str | None: ...


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
    governed: DayConvention
    predicates: PnlPredicatePort
    serial_baseline: SerialBaseline | None
    #: ``None`` means no classification exists yet (BG-11): ``denied_counted`` is then ``None``.
    counted_denial: Callable[[str], bool] | None
    #: Told ``(what, day, exception_type_name)`` when a per-day read fails; never the message.
    on_read_error: Callable[[str, str, str], None] | None = None


def _first_k_gt1_day(epochs: tuple[EpochRow, ...], governed: DayConvention, today: str) -> str:
    """Instant-only (boot): the earliest station's open day at the first K>1 boot."""
    for epoch in epochs:
        if epoch.effective_k > 1:
            return min(governed.open_days_at(epoch.boot_ts))
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
    governed: DayConvention,
    today: str,
    through: str,
) -> tuple[str, ...]:
    """The days a pass reads and reconciles: the earlier of the first K>1 day and the stations'
    floor days, through ``through`` (the latest open label of any station). A clock fault (start
    after ``through``) reads ``through`` only. Floor and boot are instants, so they use
    ``open_days_at`` (BG-5c R1)."""
    first_k_day = _first_k_gt1_day(epochs, governed, today)
    start = first_k_day if floor is None else min(first_k_day, *governed.open_days_at(floor.ts))
    return _day_range(start, max(through, today))


def _safe[T](
    read: Callable[[], T], what: str, day: str, report: Callable[[str, str, str], None] | None
) -> T | None:
    """A per-day read: a raise is a missing value (never a default). Only the exception TYPE
    is reported (the message could carry a currency value)."""
    try:
        return read()
    except Exception as exc:  # noqa: BLE001 - mapped to None; the evaluator FAILs on a missing value
        if report is not None:
            report(what, day, type(exc).__name__)
        return None


Report = Callable[[str, str, str], None] | None


def _denied_counted(
    reads: SnapshotReads, day: str, classify: Callable[[str], bool] | None, report: Report
) -> int | None:
    if classify is None:
        return None

    def count() -> int:
        return sum(1 for row in reads.read_denials(day) if classify(row.reason))

    return _safe(count, "denied", day, report)


def _fill_detail(
    reads: SnapshotReads, day: str, counted: int | None, report: Report
) -> tuple[FillRow, ...] | None:
    rows = _safe(lambda: reads.read_fills(day), "fills", day, report)
    if rows is None or counted is None:
        return None
    if len({row.client_order_id for row in rows}) != counted:
        return None  # counts rebuilt from the durable sources: no per-fill detail to evaluate
    return rows


def _day_counters(
    reads: SnapshotReads, counters: SnapshotCounters, inputs: SnapshotInputs, day: str
) -> DayCounters:
    report = inputs.on_read_error
    counts = _safe(lambda: counters.read_day_counts(day), "counts", day, report)
    return DayCounters(
        day=day,
        posted=None if counts is None else counts.posted_entries,
        ambiguous=None if counts is None else counts.ambiguous,
        denied_counted=_denied_counted(reads, day, inputs.counted_denial, report),
        fills=_fill_detail(reads, day, None if counts is None else counts.fills, report),
        open_flags=_safe(lambda: reads.read_open_cost_flags(day), "open_flags", day, report),
        windows=_safe(lambda: reads.read_window_peaks(day), "windows", day, report),
    )


def _stub_ambiguous(rows: tuple[object, ...]) -> tuple[AmbiguousRow, ...]:
    if not all(isinstance(row, AmbiguousRow) for row in rows):
        raise TypeError("ambiguous rows are not AmbiguousRow")
    return tuple(row for row in rows if isinstance(row, AmbiguousRow))


def _stub_windows(anchors: tuple[OrderAnchor, ...]) -> tuple[WindowPeak, ...]:
    """BG-1b's per-window peaks, re-derived from the post-floor anchors only."""
    grouped: dict[int, list[OrderAnchor]] = {}
    for anchor in anchors:
        grouped.setdefault(anchor.window_start_ns, []).append(anchor)
    return tuple(
        WindowPeak(
            day=group[0].day,
            window_start_ns=start,
            orders=len(group),
            notional=canonical_decimal(sum((Decimal(a.notional) for a in group), Decimal(0))),
            coids=",".join(sorted(a.client_order_id for a in group)),
        )
        for start, group in sorted(grouped.items())
    )


def _floor_stub(
    reads: SnapshotReads,
    counters: SnapshotCounters,
    inputs: SnapshotInputs,
    floor_ts: int,
    day: str,
) -> DayCounters:
    """One floor label's counters from ONLY the entries armed at or after ``floor_ts`` (A4).

    A read that fails leaves every field ``None`` (the evaluator FAILs on a missing counter). The
    stub is ``pre_floor_unknown`` when the stored whole-day counts are not accounted for by the
    per-entry rows (a rebuild restored counts, not rows), so no pre/post split can be proven.
    """
    report = inputs.on_read_error
    anchors = _anchors_at(reads, day, report)
    ambiguous = _safe(lambda: _stub_ambiguous(reads.read_ambiguous(day)), "ambiguous", day, report)
    fills = _safe(lambda: reads.read_fills(day), "fills", day, report)
    flags = _safe(lambda: reads.read_open_cost_flags(day), "open_flags", day, report)
    counts = _safe(lambda: counters.read_day_counts(day), "counts", day, report)
    if anchors is None or ambiguous is None or fills is None or flags is None or counts is None:
        return DayCounters(day, None, None, None, None, None, None)
    post_anchors = tuple(a for a in anchors if a.arm_ns >= floor_ts)
    post_fills = tuple(f for f in fills if f.arm_ns >= floor_ts)
    unknown = (
        counts.posted_entries != len(anchors)
        or counts.ambiguous != len(ambiguous)
        or counts.fills != len({f.client_order_id for f in fills})
    )
    return DayCounters(
        day=day,
        posted=len(post_anchors),
        ambiguous=sum(1 for row in ambiguous if row.arm_ns >= floor_ts),
        denied_counted=_stub_denied(reads, day, floor_ts, inputs.counted_denial, report),
        fills=post_fills,
        open_flags=tuple(f for f in flags if f.ts_ns >= floor_ts),
        windows=_stub_windows(post_anchors),
        pre_floor_unknown=unknown,
    )


def _stub_denied(
    reads: SnapshotReads,
    day: str,
    floor_ts: int,
    classify: Callable[[str], bool] | None,
    report: Report,
) -> int | None:
    if classify is None:
        return None

    def count() -> int:
        return sum(
            1 for row in reads.read_denials(day) if row.arm_ns >= floor_ts and classify(row.reason)
        )

    return _safe(count, "denied", day, report)


def _anchors_at(reads: SnapshotReads, day: str, report: Report) -> tuple[OrderAnchor, ...] | None:
    return _safe(lambda: reads.read_order_anchors(day), "anchors", day, report)


def _activity(reads: SnapshotReads, day: str, report: Report) -> tuple[int, int, int] | None:
    """(anchors, AMBIGUOUS marks, denials) on ``day``; ``None`` if a read failed. An AMBIGUOUS
    mark can exist without an anchor, so anchors alone do not prove a day is quiet."""
    anchors = _anchors_at(reads, day, report)
    ambiguous = _safe(lambda: reads.read_ambiguous(day), "ambiguous", day, report)
    denials = _safe(lambda: reads.read_denials(day), "denials", day, report)
    if anchors is None or ambiguous is None or denials is None:
        return None
    return len(anchors), len(ambiguous), len(denials)


def _ahead_tail(
    reads: SnapshotReads,
    counters: SnapshotCounters,
    inputs: SnapshotInputs,
    covered_through: str,
) -> tuple[DayCounters, ...]:
    """Activity past the covered labels. Within the allowance it is open data; beyond it the
    evaluator reports ``counter_missing``. A bounded day probe covers the next
    ``AHEAD_PROBE_DAYS`` days past the allowance; ANY row dated later than that is found by a
    key-prefix scan (``read_latest_entry_day``) and fails closed. A label with no activity is
    not added."""
    today = dt.date.fromisoformat(inputs.today)
    covered = dt.date.fromisoformat(covered_through)
    rows: list[DayCounters] = []
    for offset in range(1, MAX_OPEN_DAYS_AHEAD + AHEAD_PROBE_DAYS + 1):
        day_date = today + dt.timedelta(days=offset)
        if day_date <= covered:
            continue
        day = day_date.isoformat()
        seen = _activity(reads, day, inputs.on_read_error)
        if seen is None:
            rows.append(DayCounters(day, None, None, None, None, None, None))
        elif any(seen):
            row = _day_counters(reads, counters, inputs, day)
            # Counts that under-report the rows actually present are unknown, never a quiet day.
            under = (row.posted or 0) < seen[0] or (row.ambiguous or 0) < seen[1]
            rows.append(dataclasses.replace(row, posted=None) if under else row)
    probed_to = today + dt.timedelta(days=MAX_OPEN_DAYS_AHEAD + AHEAD_PROBE_DAYS)
    latest = reads.read_latest_entry_day()  # a stage-level read: a failure propagates
    if latest is not None and dt.date.fromisoformat(latest) > probed_to:
        rows.append(DayCounters(latest, None, None, None, None, None, None))
    return tuple(rows)


def _day_pnl(reads: SnapshotReads, day: str, report: Report) -> DayPnl | None:
    """``None``: no row (omitted); a ``DayPnl`` with a ``None`` reading: row unreadable."""
    try:
        row = reads.read_settled_pnl_day(day)
        return None if row is None else DayPnl(day, settled_pnl_or_fail(row))
    except Exception as exc:  # noqa: BLE001 - an unreadable row is FAIL territory, never zero
        if report is not None:
            report("settled_pnl", day, type(exc).__name__)
        return DayPnl(day, None)


def _unattributed_ambiguous(reads: SnapshotReads, report: Report) -> int | None:
    return _safe(lambda: len(reads.read_ambiguous(UNATTRIBUTED)), "unattributed", "-", report)


def build_stage_snapshot(
    reads: SnapshotReads, counters: SnapshotCounters, inputs: SnapshotInputs
) -> StageSnapshot:
    """Gather one snapshot on the loop thread. Stage-level read failures propagate."""
    floor = reads.read_stage_reset()
    epochs = reads.read_epoch_rows()
    excluded = reads.read_excluded_days()
    looks = tuple(LookRecord(x.day, LookOutcome(x.outcome)) for x in reads.read_looks())
    verdicts = reads.read_stop_verdicts_since(0)

    governed = inputs.governed
    through = max({inputs.today, *governed.open_days_at(inputs.now_ns)})
    labels = stage_day_labels(floor, epochs, governed, inputs.today, through)
    tail = _ahead_tail(reads, counters, inputs, labels[-1])
    all_labels = (*labels, *(x.day for x in tail))

    pnl = tuple(
        row for day in all_labels if (row := _day_pnl(reads, day, inputs.on_read_error)) is not None
    )
    gappy = counters.read_gappy_days()
    pending = frozenset(day for day in labels if counters.read_pending_rebuild(day) is not None)
    stubs = (
        ()
        if floor is None
        else tuple(
            _floor_stub(reads, counters, inputs, floor.ts, day)
            for day in sorted(governed.open_days_at(floor.ts))
        )
    )
    return StageSnapshot(
        today=inputs.today,
        configured_k=inputs.configured_k,
        effective_k=inputs.effective_k,
        floor=floor,
        epochs=epochs,
        excluded_days=excluded,
        days=(*(_day_counters(reads, counters, inputs, day) for day in labels), *tail),
        pnl_days=pnl,
        gappy_days=gappy,
        pending_rebuild_days=pending,
        pass_status=inputs.pass_status,
        looks=looks,
        stop_verdicts=verdicts,
        serial_baseline=inputs.serial_baseline,
        unattributed_ambiguous=_unattributed_ambiguous(reads, inputs.on_read_error),
        governed=governed,
        predicates=inputs.predicates,
        floor_stubs=stubs,
    )
