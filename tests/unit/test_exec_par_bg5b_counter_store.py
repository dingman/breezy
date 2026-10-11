"""EXEC-PAR BG-5b: the latch-backed ``CounterStorePort`` (BG-1d) and the real reconcile pass."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

import pytest

from breezy.runtime.exec_par_counter_store import LatchCounterStore
from breezy.runtime.exec_par_reconcile import (
    CounterStorePort,
    DayCounts,
    DayOutcomeKind,
    PassStatus,
    RebuildRecord,
    SlotDayCounts,
    run_reconcile_pass,
)
from breezy.runtime.exec_par_records import (
    EXEC_PAR_PREFIX,
    AmbiguousRow,
    FillRow,
    GappyMark,
    OrderAnchor,
)
from breezy.runtime.submit_intent import SubmitIntentLatch, open_submit_intent_latch

P = EXEC_PAR_PREFIX
DAY = "2026-11-30"
WALL = 5_000


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


@contextmanager
def _open(tmp_path: Path) -> Iterator[tuple[SubmitIntentLatch, _Store]]:
    store = _Store()
    with open_submit_intent_latch(store, tmp_path / "s.db", clock_ns=lambda: 1) as latch:
        yield latch, store


def _anchor(coid: str, notional: str = "4", day: str = DAY) -> OrderAnchor:
    return OrderAnchor(coid, "slug", day, 100, "0.40", "10", notional, 100, "event_time", "STN")


def _fill(trade: str, coid: str, day: str = DAY) -> FillRow:
    return FillRow(
        trade, coid, day, 100, "10", "0.41", "0.40", "0.01", "0.17", "0.168", "0.0695", "STN"
    )


def _seed(latch: SubmitIntentLatch) -> None:
    latch.write_order_anchor(_anchor("O-1", "4"))
    latch.write_order_anchor(_anchor("O-2", "2.5"))
    latch.write_order_anchor(_anchor("O-3", "1", day="2026-12-01"))
    latch.write_ambiguous(AmbiguousRow("a1", "armed_pre_boot", DAY, 5, "slot", 6, "STN"))
    latch.write_fill(_fill("T-1", "O-1"))
    latch.write_fill(_fill("T-2", "O-1"))  # partial fills of one order count once


def _store(latch: SubmitIntentLatch) -> LatchCounterStore:
    return LatchCounterStore(latch, wall_ns=lambda: WALL)


def test_read_day_counts_aggregates_the_event_rows_for_that_day_only(tmp_path: Path) -> None:
    with _open(tmp_path) as (latch, _):
        _seed(latch)
        counts = _store(latch).read_day_counts(DAY)
    assert counts == DayCounts(posted_entries=2, ambiguous=1, fills=1, spend_usd=Decimal("6.5"))


def test_an_empty_day_reads_as_zero_counts_not_none(tmp_path: Path) -> None:
    with _open(tmp_path) as (latch, _):
        assert _store(latch).read_day_counts(DAY) == DayCounts(0, 0, 0, Decimal(0))


def test_replace_day_counts_stores_a_signed_delta_and_later_events_still_count(
    tmp_path: Path,
) -> None:
    with _open(tmp_path) as (latch, store):
        _seed(latch)
        counters = _store(latch)
        counters.replace_day_counts(DAY, DayCounts(5, 2, 3, Decimal("9.25")))
        assert counters.read_day_counts(DAY) == DayCounts(5, 2, 3, Decimal("9.25"))
        assert P + f"counts_delta/{DAY}" in store.data
        latch.write_order_anchor(_anchor("O-4", "1"))  # a later event keeps counting
        assert counters.read_day_counts(DAY) == DayCounts(6, 2, 3, Decimal("10.25"))
        counters.replace_day_counts(DAY, DayCounts(1, 0, 0, Decimal(0)))  # shrink is legal
        assert counters.read_day_counts(DAY) == DayCounts(1, 0, 0, Decimal(0))


def test_gappy_marks_round_trip_clear_deletes_and_remark_recreates(tmp_path: Path) -> None:
    with _open(tmp_path) as (latch, store):
        counters = _store(latch)
        assert counters.read_gappy_days() == frozenset()
        counters.mark_gappy_day(DAY, "counter_missing")
        assert counters.read_gappy_days() == frozenset({DAY})
        assert latch.read_gappy_marks() == (GappyMark(DAY, "counter_missing", WALL, None),)
        counters.clear_gappy_mark(DAY)
        assert counters.read_gappy_days() == frozenset()
        assert P + f"gappy/{DAY}" not in store.data
        counters.mark_gappy_day(DAY, "later_fault")
        assert latch.read_gappy_marks()[0].cause == "later_fault"


def test_pending_rebuild_note_round_trips_and_retires_with_an_audit_row(tmp_path: Path) -> None:
    record = RebuildRecord(DAY, 9, ("fills", "spend"), DayCounts(3, 1, 2, Decimal("1.5")))
    with _open(tmp_path) as (latch, store):
        counters = _store(latch)
        assert counters.read_pending_rebuild(DAY) is None
        counters.write_rebuild_record(record)
        assert counters.read_pending_rebuild(DAY) == record
        counters.retire_pending_rebuild(DAY)
        assert counters.read_pending_rebuild(DAY) is None
        counters.retire_pending_rebuild(DAY)  # nothing pending: harmless
        assert P + f"rebuild_log/{DAY}/9" in store.data


def test_write_reconcile_phase_goes_to_the_reconcile_phase_row(tmp_path: Path) -> None:
    with _open(tmp_path) as (latch, _):
        counters = _store(latch)
        counters.write_reconcile_phase(start_ns=3, ok_ns=None)
        phase = latch.read_reconcile_phase()
        assert phase is not None and (phase.reconcile_start_ns, phase.reconcile_ok_ns) == (3, None)
        counters.write_reconcile_phase(start_ns=3, ok_ns=8)
        phase = latch.read_reconcile_phase()
        assert phase is not None and phase.reconcile_ok_ns == 8


def test_the_store_satisfies_the_reconcile_port_at_runtime(tmp_path: Path) -> None:
    port_methods = {
        name
        for name in vars(CounterStorePort)
        if not name.startswith("_") and name != "__abstractmethods__"
    }
    with _open(tmp_path) as (latch, _):
        counters = _store(latch)
        for name in port_methods:
            assert callable(getattr(counters, name)), name


class _Sources:
    def __init__(self, counts: DayCounts) -> None:
        self._counts = counts

    def entry_fill_count(self, day: str) -> int | None:
        return self._counts.fills

    def slot_counts(self, day: str) -> SlotDayCounts | None:
        return SlotDayCounts(self._counts.posted_entries, self._counts.ambiguous)

    def ledger_spend(self, day: str) -> Decimal | None:
        return self._counts.spend_usd


class _Excluded:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add_excluded_day(self, record: object) -> bool:
        self.added.append(record)
        return True


def test_a_real_reconcile_pass_rebuilds_clears_the_mark_and_converges(tmp_path: Path) -> None:
    with _open(tmp_path) as (latch, store):
        _seed(latch)
        counters = _store(latch)
        counters.mark_gappy_day(DAY, "heartbeat_lapse")
        durable = DayCounts(3, 1, 2, Decimal("7.5"))  # the durable sources know better
        ticks = iter(range(0, 10_000, 1))

        def run() -> object:
            return run_reconcile_pass(
                [DAY],
                mass_status_ingested=lambda: True,
                counters=counters,
                sources=_Sources(durable),
                excluded=_Excluded(),
                monotonic_ns=lambda: next(ticks),
                wall_ns=lambda: WALL,
                counters_expected=lambda day: True,
            )

        first = run()
        assert first.status is PassStatus.OK  # type: ignore[attr-defined]
        assert first.outcomes[0].kind is DayOutcomeKind.REBUILT  # type: ignore[attr-defined]
        assert counters.read_day_counts(DAY) == durable
        assert counters.read_gappy_days() == frozenset()
        assert counters.read_pending_rebuild(DAY) is None
        assert P + f"gappy/{DAY}" not in store.data
        second = run()
        assert second.outcomes[0].kind is DayOutcomeKind.UNCHANGED  # type: ignore[attr-defined]
        phase = latch.read_reconcile_phase()
        assert phase is not None and phase.reconcile_ok_ns == WALL


def test_an_inconsistent_source_excludes_the_day_through_the_excluded_writer(
    tmp_path: Path,
) -> None:
    excluded = _Excluded()
    with _open(tmp_path) as (latch, _):
        counters = _store(latch)
        result = run_reconcile_pass(
            [DAY],
            mass_status_ingested=lambda: True,
            counters=counters,
            sources=_Sources(DayCounts(1, 2, 0, Decimal(0))),  # ambiguous > posted
            excluded=excluded,
            monotonic_ns=iter(range(100)).__next__,
            wall_ns=lambda: WALL,
            counters_expected=lambda day: True,
        )
    assert result.outcomes[0].kind is DayOutcomeKind.DAY_EXCLUDED
    assert len(excluded.added) == 1


@pytest.mark.parametrize("bad", ["", "a/b", "x y"])
def test_day_keys_with_separators_are_refused(tmp_path: Path, bad: str) -> None:
    with _open(tmp_path) as (latch, _), pytest.raises(ValueError):
        _store(latch).read_day_counts(bad)
