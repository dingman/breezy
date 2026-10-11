"""EXEC-PAR BG-5b: the latch-backed ``CounterStorePort`` (BG-1d) over the BG-1b event rows.

BG-1b keeps no running totals: a day's counters are scans of exclusive event rows. So the
"stored" counts reconcile compares are

    scan(rows of the day) + the day's signed rebuild delta

and ``replace_day_counts`` stores ``durable - scan`` as that delta. A later event row (or a
retried one) therefore keeps counting, and the next reconcile re-derives the delta from the
then-current scan. ``read_day_counts`` never returns ``None``: an empty day is zero counts
(a lost write is the BG-1b ingest fault / gappy mark, not a missing counter).

Integration notes 1: ``clear_gappy_mark`` DELETES the ``gappy/<day>`` row (store ``delete``),
so a later fault on the same day re-creates the mark.

Spend is the sum of the posted entries' ``notional`` (ask times quantity). Currency values
stay inside this class and the reconcile port; nothing here logs them.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Protocol

from breezy.runtime.exec_par_reconcile import DayCounts, RebuildRecord
from breezy.runtime.exec_par_records import (
    AmbiguousRow,
    DayCountsDelta,
    FillRow,
    GappyMark,
    OrderAnchor,
    RebuildRow,
)

__all__ = ["CounterStoreLatch", "LatchCounterStore", "canonical_decimal", "scan_counts"]

_KIND_SEP = ","


def canonical_decimal(value: Decimal) -> str:
    """Plain, exponent-free decimal text with no trailing zeros (the record codec's form)."""
    if not value.is_finite():
        raise ValueError("non-finite decimal")
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


class CounterStoreLatch(Protocol):
    """The latch methods the counter store uses (a subset of ``SubmitIntentLatch``)."""

    def read_order_anchors(self, day: str) -> tuple[OrderAnchor, ...]: ...
    def read_ambiguous(self, day: str) -> tuple[AmbiguousRow, ...]: ...
    def read_fills(self, day: str) -> tuple[FillRow, ...]: ...
    def read_counts_delta(self, day: str) -> DayCountsDelta | None: ...
    def write_counts_delta(self, record: DayCountsDelta) -> None: ...
    def read_gappy_marks(self) -> tuple[GappyMark, ...]: ...
    def write_gappy_mark(self, record: GappyMark) -> bool: ...
    def delete_gappy_mark(self, day: str) -> bool: ...
    def read_rebuild_row(self, day: str) -> RebuildRow | None: ...
    def write_rebuild_row(self, record: RebuildRow) -> None: ...
    def retire_rebuild_row(self, day: str) -> bool: ...
    def write_reconcile_phase(self, *, start_ns: int, ok_ns: int | None) -> None: ...


def scan_counts(latch: CounterStoreLatch, day: str) -> DayCounts:
    """The BG-1b row scan of ``day``: posted anchors, AMBIGUOUS rows, distinct filled orders."""
    anchors = latch.read_order_anchors(day)
    spend = sum((Decimal(a.notional) for a in anchors), Decimal(0))
    return DayCounts(
        posted_entries=len(anchors),
        ambiguous=len(latch.read_ambiguous(day)),
        fills=len({f.client_order_id for f in latch.read_fills(day)}),
        spend_usd=spend,
    )


class LatchCounterStore:
    """``CounterStorePort`` over the latch. Loop thread only (the latch is single-writer)."""

    def __init__(self, latch: CounterStoreLatch, *, wall_ns: Callable[[], int]) -> None:
        self._latch = latch
        self._wall_ns = wall_ns

    def read_day_counts(self, day: str) -> DayCounts:
        scanned = scan_counts(self._latch, day)
        delta = self._latch.read_counts_delta(day)
        if delta is None:
            return scanned
        return DayCounts(
            posted_entries=scanned.posted_entries + delta.posted_entries,
            ambiguous=scanned.ambiguous + delta.ambiguous,
            fills=scanned.fills + delta.fills,
            spend_usd=scanned.spend_usd + Decimal(delta.spend),
        )

    def replace_day_counts(self, day: str, counts: DayCounts) -> None:
        scanned = scan_counts(self._latch, day)
        self._latch.write_counts_delta(
            DayCountsDelta(
                day=day,
                posted_entries=counts.posted_entries - scanned.posted_entries,
                ambiguous=counts.ambiguous - scanned.ambiguous,
                fills=counts.fills - scanned.fills,
                spend=canonical_decimal(counts.spend_usd - scanned.spend_usd),
            )
        )

    def read_gappy_days(self) -> frozenset[str]:
        return frozenset(mark.day for mark in self._latch.read_gappy_marks())

    def mark_gappy_day(self, day: str, kind: str) -> None:
        self._latch.write_gappy_mark(
            GappyMark(day=day, cause=kind, ts_ns=self._wall_ns(), cleared_ts=None)
        )

    def clear_gappy_mark(self, day: str) -> None:
        self._latch.delete_gappy_mark(day)

    def read_pending_rebuild(self, day: str) -> RebuildRecord | None:
        row = self._latch.read_rebuild_row(day)
        if row is None:
            return None
        return RebuildRecord(
            day=row.day,
            ts_ns=row.ts_ns,
            mismatch_kinds=tuple(row.mismatch_kinds.split(_KIND_SEP)),
            counts=DayCounts(row.posted_entries, row.ambiguous, row.fills, Decimal(row.spend)),
        )

    def write_rebuild_record(self, record: RebuildRecord) -> None:
        self._latch.write_rebuild_row(
            RebuildRow(
                day=record.day,
                ts_ns=record.ts_ns,
                mismatch_kinds=_KIND_SEP.join(record.mismatch_kinds),
                posted_entries=record.counts.posted_entries,
                ambiguous=record.counts.ambiguous,
                fills=record.counts.fills,
                spend=canonical_decimal(record.counts.spend_usd),
            )
        )

    def retire_pending_rebuild(self, day: str) -> None:
        self._latch.retire_rebuild_row(day)

    def write_reconcile_phase(self, *, start_ns: int, ok_ns: int | None) -> None:
        self._latch.write_reconcile_phase(start_ns=start_ns, ok_ns=ok_ns)
