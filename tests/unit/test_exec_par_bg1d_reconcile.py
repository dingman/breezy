"""EXEC-PAR BG-1d: reconcile BG-1b counters against the durable sources (fakes only)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import cast

import pytest

from breezy.runtime.exec_par_reconcile import (
    RECONCILE_BOUND_NS,
    DayCounts,
    DayOutcomeKind,
    PassResult,
    PassStatus,
    RebuildRecord,
    ReconcileOrderingError,
    SlotDayCounts,
    reconcile_day,
    run_reconcile_pass,
)
from breezy.runtime.exec_par_records import ExcludedDay

S = 1_000_000_000
D1 = "2026-10-08"
D2 = "2026-10-09"


def _counts(posted: int = 3, amb: int = 1, fills: int = 2, spend: str = "12.50") -> DayCounts:
    return DayCounts(posted_entries=posted, ambiguous=amb, fills=fills, spend_usd=Decimal(spend))


@dataclass
class FakeSources:
    fills: dict[str, int | None] = field(default_factory=dict)
    slots: dict[str, SlotDayCounts | None] = field(default_factory=dict)
    spend: dict[str, Decimal | None] = field(default_factory=dict)
    reads: list[str] = field(default_factory=list)

    def set_day(self, day: str, c: DayCounts) -> None:
        self.fills[day] = c.fills
        self.slots[day] = SlotDayCounts(posted_entries=c.posted_entries, ambiguous=c.ambiguous)
        self.spend[day] = c.spend_usd

    def fill_count(self, day: str) -> int | None:
        self.reads.append("fills")
        return self.fills.get(day)

    def slot_counts(self, day: str) -> SlotDayCounts | None:
        self.reads.append("slots")
        return self.slots.get(day)

    def ledger_spend(self, day: str) -> Decimal | None:
        self.reads.append("ledger")
        return self.spend.get(day)


@dataclass
class FakeCounters:
    counts: dict[str, DayCounts] = field(default_factory=dict)
    gappy: set[str] = field(default_factory=set)
    rebuilds: list[RebuildRecord] = field(default_factory=list)
    phases: list[tuple[int, int | None]] = field(default_factory=list)
    log: list[str] = field(default_factory=list)

    def read_day_counts(self, day: str) -> DayCounts | None:
        self.log.append("read")
        return self.counts.get(day)

    def replace_day_counts(self, day: str, counts: DayCounts) -> None:
        self.log.append("replace")
        self.counts[day] = counts

    def read_gappy_days(self) -> frozenset[str]:
        return frozenset(self.gappy)

    def clear_gappy_mark(self, day: str) -> None:
        self.gappy.discard(day)

    def write_rebuild_record(self, record: RebuildRecord) -> None:
        self.rebuilds.append(record)

    def write_reconcile_phase(self, *, start_ns: int, ok_ns: int | None) -> None:
        self.phases.append((start_ns, ok_ns))


@dataclass
class FakeExcluded:
    rows: list[ExcludedDay] = field(default_factory=list)

    def add_excluded_day(self, record: ExcludedDay) -> bool:
        if any(r.day == record.day for r in self.rows):
            return False
        self.rows.append(record)
        return True


def _ticker(*times: int) -> Callable[[], int]:
    it = iter(times)
    last = [times[-1]]

    def clock() -> int:
        value = next(it, last[0])
        last[0] = value
        return value

    return clock


# -- pure per-day decision --------------------------------------------------


def test_matching_non_gappy_day_is_unchanged() -> None:
    c = _counts()
    verdict = reconcile_day(
        D1, stored=c, fills=2, slots=SlotDayCounts(3, 1), spend=Decimal("12.50"), gappy=False
    )
    assert verdict.kind is DayOutcomeKind.UNCHANGED
    assert verdict.mismatch_kinds == ()


def test_mismatch_reports_each_kind_sorted_and_rebuilds_from_durable() -> None:
    stored = _counts(posted=2, amb=0, fills=1, spend="1")
    verdict = reconcile_day(
        D1, stored=stored, fills=2, slots=SlotDayCounts(3, 1), spend=Decimal("12.50"), gappy=False
    )
    assert verdict.kind is DayOutcomeKind.REBUILT
    assert verdict.mismatch_kinds == ("ambiguous", "fills", "posted_entries", "spend")
    assert verdict.rebuilt == _counts()


def test_missing_counters_rebuild_with_missing_kind() -> None:
    verdict = reconcile_day(
        D1, stored=None, fills=2, slots=SlotDayCounts(3, 1), spend=Decimal("12.50"), gappy=False
    )
    assert verdict.kind is DayOutcomeKind.REBUILT
    assert verdict.mismatch_kinds == ("missing",)


def test_gappy_day_with_matching_counters_still_rebuilds_with_no_mismatch() -> None:
    verdict = reconcile_day(
        D1, stored=_counts(), fills=2, slots=SlotDayCounts(3, 1), spend=Decimal("12.50"), gappy=True
    )
    assert verdict.kind is DayOutcomeKind.REBUILT
    assert verdict.mismatch_kinds == ()


@pytest.mark.parametrize(
    ("fills", "slots", "spend", "reason"),
    [
        (None, SlotDayCounts(3, 1), Decimal(1), "fills_unreadable"),
        (2, None, Decimal(1), "slots_unreadable"),
        (2, SlotDayCounts(3, 1), None, "ledger_unreadable"),
        (2, SlotDayCounts(1, 2), Decimal(1), "ambiguous_exceeds_posted"),
        (4, SlotDayCounts(3, 1), Decimal(1), "fills_exceed_posted"),
        (0, SlotDayCounts(0, 0), Decimal(5), "spend_without_entries"),
        (2, SlotDayCounts(3, 1), Decimal(0), "fills_without_spend"),
        (2, SlotDayCounts(3, 1), Decimal(-1), "negative_spend"),
        (-1, SlotDayCounts(3, 1), Decimal(1), "negative_count"),
    ],
)
def test_inconsistent_durable_sources_are_unreconcilable(
    fills: int | None, slots: SlotDayCounts | None, spend: Decimal | None, reason: str
) -> None:
    verdict = reconcile_day(D1, stored=_counts(), fills=fills, slots=slots, spend=spend, gappy=True)
    assert verdict.kind is DayOutcomeKind.DAY_EXCLUDED
    assert verdict.reason == reason
    assert verdict.rebuilt is None


# -- the pass ----------------------------------------------------------------


def _run(
    days: tuple[str, ...],
    counters: FakeCounters,
    sources: FakeSources,
    excluded: FakeExcluded,
    clock: Callable[[], int],
    ingested: Callable[[], bool] = lambda: True,
) -> PassResult:
    return run_reconcile_pass(
        days,
        mass_status_ingested=ingested,
        counters=counters,
        sources=sources,
        excluded=excluded,
        clock_ns=clock,
    )


def test_rebuild_case_rewrites_counters_clears_gappy_records_and_emits_event() -> None:
    counters = FakeCounters(counts={D1: _counts(posted=1)}, gappy={D1})
    sources = FakeSources()
    sources.set_day(D1, _counts())
    excluded = FakeExcluded()

    result = _run((D1,), counters, sources, excluded, _ticker(100, 110, 120))

    assert result.status is PassStatus.OK
    assert counters.counts[D1] == _counts()
    assert counters.gappy == set()
    assert [r.day for r in counters.rebuilds] == [D1]
    assert counters.rebuilds[0].mismatch_kinds == ("posted_entries",)
    assert [(e.day, e.mismatch_kinds) for e in result.rebuild_events] == [(D1, ("posted_entries",))]
    assert result.excluded_events == ()
    assert excluded.rows == []
    assert [o.kind for o in result.outcomes] == [DayOutcomeKind.REBUILT]


def test_exclusion_case_adds_excluded_day_and_leaves_counters_and_mark_alone() -> None:
    counters = FakeCounters(counts={D1: _counts()}, gappy={D1})
    sources = FakeSources()
    sources.set_day(D1, _counts())
    sources.fills[D1] = None  # the fill index is unreadable
    excluded = FakeExcluded()

    result = _run((D1,), counters, sources, excluded, _ticker(100, 110, 120))

    assert [o.kind for o in result.outcomes] == [DayOutcomeKind.DAY_EXCLUDED]
    assert [(r.day, r.cause, r.ts) for r in excluded.rows] == [
        (D1, "unreconcilable:fills_unreadable", 110)
    ]
    assert [e.day for e in result.excluded_events] == [D1]
    assert counters.counts[D1] == _counts()
    assert counters.gappy == {D1}  # the mark stays: an excluded day is skipped, not healed
    assert counters.rebuilds == []
    assert result.rebuild_events == ()


def test_already_excluded_day_is_not_double_reported() -> None:
    counters = FakeCounters(counts={D1: _counts()}, gappy={D1})
    sources = FakeSources()
    sources.set_day(D1, _counts())
    sources.spend[D1] = None
    excluded = FakeExcluded(rows=[ExcludedDay(day=D1, cause="earlier", ts=1)])

    result = _run((D1,), counters, sources, excluded, _ticker(100, 110, 120))

    assert [o.kind for o in result.outcomes] == [DayOutcomeKind.DAY_EXCLUDED]
    assert result.excluded_events == ()
    assert len(excluded.rows) == 1


def test_phase_timestamps_are_recorded_start_then_ok() -> None:
    counters = FakeCounters(counts={D1: _counts()})
    sources = FakeSources()
    sources.set_day(D1, _counts())

    result = _run((D1,), counters, sources, FakeExcluded(), _ticker(1_000, 1_500, 2_000))

    assert result.reconcile_start_ns == 1_000
    assert result.reconcile_ok_ns == 2_000
    assert counters.phases == [(1_000, None), (1_000, 2_000)]


def test_ordering_guard_refuses_before_any_read_or_write() -> None:
    counters = FakeCounters(counts={D1: _counts()}, gappy={D1})
    sources = FakeSources()
    sources.set_day(D1, _counts())
    excluded = FakeExcluded()

    with pytest.raises(ReconcileOrderingError):
        _run((D1,), counters, sources, excluded, _ticker(1, 2, 3), ingested=lambda: False)

    assert sources.reads == []
    assert counters.log == []
    assert counters.phases == []
    assert counters.rebuilds == []
    assert excluded.rows == []
    assert counters.gappy == {D1}


def test_ordering_guard_that_raises_is_treated_as_not_ingested() -> None:
    def boom() -> bool:
        raise RuntimeError("probe failed")

    counters = FakeCounters()
    with pytest.raises(ReconcileOrderingError):
        _run((D1,), counters, FakeSources(), FakeExcluded(), _ticker(1), ingested=boom)
    assert counters.phases == []


def test_non_bool_ordering_guard_is_refused() -> None:
    with pytest.raises(ReconcileOrderingError):
        _run(
            (D1,),
            FakeCounters(),
            FakeSources(),
            FakeExcluded(),
            _ticker(1),
            ingested=cast("Callable[[], bool]", lambda: 1),
        )


def test_bound_is_300_seconds() -> None:
    assert RECONCILE_BOUND_NS == 300 * S


def test_exceeding_300s_returns_reconcile_stuck_without_halting_and_stops_early() -> None:
    counters = FakeCounters(counts={D1: _counts(), D2: _counts()}, gappy={D1, D2})
    sources = FakeSources()
    sources.set_day(D1, _counts())
    sources.set_day(D2, _counts())
    # start=0; D1 checked at 100 s (ok); D2 checked at 301 s -> stuck.
    clock = _ticker(0, 100 * S, 301 * S, 302 * S)

    result = _run((D1, D2), counters, sources, FakeExcluded(), clock)

    assert result.status is PassStatus.RECONCILE_STUCK
    assert result.status.value == "reconcile_stuck"
    assert result.reconcile_ok_ns is None
    assert [o.day for o in result.outcomes] == [D1]
    assert result.unprocessed_days == (D2,)
    assert counters.gappy == {D2}
    assert counters.phases == [(0, None)]


def test_exactly_300s_is_not_stuck() -> None:
    counters = FakeCounters(counts={D1: _counts()})
    sources = FakeSources()
    sources.set_day(D1, _counts())

    result = _run((D1,), counters, sources, FakeExcluded(), _ticker(0, 150 * S, 300 * S))

    assert result.status is PassStatus.OK
    assert result.reconcile_ok_ns == 300 * S


def test_finishing_past_the_bound_is_stuck_and_ok_is_not_recorded() -> None:
    counters = FakeCounters(counts={D1: _counts()})
    sources = FakeSources()
    sources.set_day(D1, _counts())

    result = _run((D1,), counters, sources, FakeExcluded(), _ticker(0, 10 * S, 301 * S))

    assert result.status is PassStatus.RECONCILE_STUCK
    assert result.reconcile_ok_ns is None
    assert counters.phases == [(0, None)]


def test_pass_is_deterministic_and_order_independent() -> None:
    def build() -> tuple[FakeCounters, FakeSources, FakeExcluded]:
        counters = FakeCounters(counts={D1: _counts(posted=9), D2: _counts()}, gappy={D1, D2})
        sources = FakeSources()
        sources.set_day(D1, _counts())
        sources.set_day(D2, _counts())
        sources.spend[D2] = None
        return counters, sources, FakeExcluded()

    a_c, a_s, a_e = build()
    b_c, b_s, b_e = build()
    first = _run((D1, D2), a_c, a_s, a_e, _ticker(5, 6, 7, 8, 9))
    second = _run((D2, D1, D1), b_c, b_s, b_e, _ticker(5, 6, 7, 8, 9))

    assert first == second
    assert a_c.counts == b_c.counts
    assert a_e.rows == b_e.rows
    assert [o.day for o in first.outcomes] == [D1, D2]
