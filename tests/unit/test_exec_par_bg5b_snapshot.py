"""EXEC-PAR BG-5b: the pure snapshot builder (injected store reads and predicates, K6)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from breezy.runtime.exec_par_counter_ingest import UNATTRIBUTED
from breezy.runtime.exec_par_reconcile import DayCounts, PassStatus, RebuildRecord
from breezy.runtime.exec_par_records import (
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
)
from breezy.runtime.exec_par_stage_eval import (
    LookOutcome,
    SerialBaseline,
    VerdictKind,
    evaluate_stage,
)
from breezy.runtime.exec_par_stage_snapshot import (
    MAX_SNAPSHOT_DAYS,
    SnapshotInputs,
    build_stage_snapshot,
)
from tests.unit.exec_par_days import UtcDays

NS = 1_000_000_000
BASE = dt.date(2026, 12, 1)


def d(i: int) -> str:
    return (BASE + dt.timedelta(days=i)).isoformat()


def ns_of(day: str) -> int:
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.UTC).timestamp()) * NS


GOV = UtcDays()


class _Preds:
    def __init__(self) -> None:
        self.calls = 0

    def pnl_breaches_budget_fraction(self, *, aggregate_pnl: Decimal, fraction: Decimal) -> bool:
        self.calls += 1
        return aggregate_pnl <= -fraction


@dataclass
class _Reads:
    """Fake of the latch reads the builder uses."""

    reset: StageReset | None = field(
        default_factory=lambda: StageReset(ns_of(d(0)) + 5, "k_change", None)
    )
    epochs: tuple[EpochRow, ...] = field(
        default_factory=lambda: (EpochRow("sha", 2, None, ns_of(d(0)) + 5),)
    )
    excluded: tuple[ExcludedDay, ...] = ()
    looks: tuple[LookRow, ...] = ()
    verdicts: tuple[StopVerdict, ...] = ()
    pnl: dict[str, SettledPnlDay] = field(default_factory=dict)
    fills: dict[str, tuple[FillRow, ...]] = field(default_factory=dict)
    denials: dict[str, tuple[DenialRow, ...]] = field(default_factory=dict)
    flags: dict[str, tuple[OpenCostFlag, ...]] = field(default_factory=dict)
    windows: dict[str, tuple[WindowPeak, ...]] = field(default_factory=dict)
    ambiguous_unattributed: int = 0
    raise_on: set[str] = field(default_factory=set)
    #: The floor day d(0) holds three post-floor entries (they back the default counters' 3 posted).
    anchors: dict[str, tuple[OrderAnchor, ...]] = field(
        default_factory=lambda: {d(0): tuple(_anchor(d(0), f"A-{i}") for i in range(3))}
    )

    def _maybe(self, name: str) -> None:
        if name in self.raise_on:
            raise OSError(name)

    def read_stage_reset(self) -> StageReset | None:
        self._maybe("stage_reset")
        return self.reset

    def read_epoch_rows(self) -> tuple[EpochRow, ...]:
        self._maybe("epochs")
        return self.epochs

    def read_excluded_days(self) -> tuple[ExcludedDay, ...]:
        self._maybe("excluded")
        return self.excluded

    def read_looks(self) -> tuple[LookRow, ...]:
        self._maybe("looks")
        return self.looks

    def read_stop_verdicts_since(self, ts_ns: int) -> tuple[StopVerdict, ...]:
        self._maybe("verdicts")
        return tuple(v for v in self.verdicts if v.ts_ns >= ts_ns)

    def read_settled_pnl_day(self, day: str) -> SettledPnlDay | None:
        self._maybe(f"pnl:{day}")
        return self.pnl.get(day)

    def read_fills(self, day: str) -> tuple[FillRow, ...]:
        self._maybe(f"fills:{day}")
        return self.fills.get(day, ())

    def read_denials(self, day: str) -> tuple[DenialRow, ...]:
        self._maybe(f"denials:{day}")
        return self.denials.get(day, ())

    def read_open_cost_flags(self, day: str) -> tuple[OpenCostFlag, ...]:
        self._maybe(f"flags:{day}")
        return self.flags.get(day, ())

    def read_window_peaks(self, day: str) -> tuple[WindowPeak, ...]:
        self._maybe(f"windows:{day}")
        return self.windows.get(day, ())

    def read_ambiguous(self, day: str) -> tuple[object, ...]:
        if day != UNATTRIBUTED:
            return ()  # per-day AMBIGUOUS rows (the floor stub reads them): none in these tests
        self._maybe("unattributed")
        return (object(),) * self.ambiguous_unattributed

    def read_order_anchors(self, day: str) -> tuple[OrderAnchor, ...]:
        self._maybe(f"anchors:{day}")
        return self.anchors.get(day, ())

    def read_latest_entry_day(self) -> str | None:
        self._maybe("latest_entry_day")
        return max((day for day, rows in self.anchors.items() if rows), default=None)


@dataclass
class _Counters:
    counts: dict[str, DayCounts] = field(default_factory=dict)
    gappy: frozenset[str] = frozenset()
    pending: dict[str, RebuildRecord] = field(default_factory=dict)
    raise_on: set[str] = field(default_factory=set)
    default_posted: int = 3

    def read_day_counts(self, day: str) -> DayCounts:
        if day in self.raise_on:
            raise OSError("counts")
        return self.counts.get(day, DayCounts(self.default_posted, 0, 0, Decimal(0)))

    def read_gappy_days(self) -> frozenset[str]:
        return self.gappy

    def read_pending_rebuild(self, day: str) -> RebuildRecord | None:
        return self.pending.get(day)


def _anchor(day: str, coid: str) -> OrderAnchor:
    arm = ns_of(day) + 10  # after the floor (d(0) + 5 ns)
    return OrderAnchor(coid, "slug", day, arm, "0.40", "10", "4", arm, "event_time", "STN")


def _inputs(**over: object) -> SnapshotInputs:
    base: dict[str, object] = {
        "now_ns": ns_of(d(4)) + 100,
        "today": d(4),
        "configured_k": 2,
        "effective_k": 2,
        "pass_status": PassStatus.OK,
        "governed": GOV,
        "predicates": _Preds(),
        "serial_baseline": None,
        "counted_denial": None,
    }
    base.update(over)
    return SnapshotInputs(**base)  # type: ignore[arg-type]


def _fill(day: str, coid: str = "O-1", trade: str = "T-1") -> FillRow:
    return FillRow(
        trade, coid, day, ns_of(day), "10", "0.41", "0.40", "0.01", "0.17", "0.168", "0.0695", "STN"
    )


def test_happy_path_feeds_the_real_evaluator_to_a_pass() -> None:
    snap = build_stage_snapshot(_Reads(), _Counters(), _inputs())
    assert snap.today == d(4) and snap.configured_k == 2 and snap.effective_k == 2
    assert [x.day for x in snap.days] == [d(0), d(1), d(2), d(3), d(4)]
    assert all(x.posted == 3 and x.ambiguous == 0 for x in snap.days)
    assert snap.pass_status is PassStatus.OK
    assert snap.unattributed_ambiguous == 0
    assert evaluate_stage(snap).kind is VerdictKind.PASS


def test_floor_epochs_excluded_looks_and_verdicts_are_carried() -> None:
    reads = _Reads(
        excluded=(ExcludedDay(d(2), "unreconcilable:x", 7),),
        looks=(LookRow(d(3), "failed", 9), LookRow(d(2), "not_taken", 8)),
        verdicts=(StopVerdict("s15_day", 11),),
    )
    snap = build_stage_snapshot(reads, _Counters(), _inputs())
    assert snap.floor == reads.reset
    assert snap.epochs == reads.epochs
    assert snap.excluded_days == reads.excluded
    assert [(x.day, x.outcome) for x in snap.looks] == [
        (d(3), LookOutcome.FAILED),
        (d(2), LookOutcome.NOT_TAKEN),
    ]
    assert snap.stop_verdicts == reads.verdicts


def test_missing_floor_is_carried_as_none_for_the_evaluator_to_fail() -> None:
    snap = build_stage_snapshot(_Reads(reset=None), _Counters(), _inputs())
    assert snap.floor is None
    assert evaluate_stage(snap).reason == "stage_eval_fail:floor_missing"


def test_day_range_starts_at_the_first_k_gt1_epoch_before_the_floor() -> None:
    reads = _Reads(
        epochs=(
            EpochRow("a", 1, None, ns_of(d(-2)) + 1),
            EpochRow("b", 2, None, ns_of(d(-1)) + 1),
        ),
        reset=StageReset(ns_of(d(1)) + 1, "stop_clear", 5),
    )
    snap = build_stage_snapshot(reads, _Counters(), _inputs())
    labels = [x.day for x in snap.days]
    assert (labels[0], labels[-1]) == (d(-1), d(4))


def test_no_k_gt1_epoch_means_only_today() -> None:
    reads = _Reads(epochs=(EpochRow("a", 1, None, ns_of(d(0)) + 1),))
    snap = build_stage_snapshot(reads, _Counters(), _inputs())
    assert d(4) in [x.day for x in snap.days]
    assert len(snap.days) <= 5


def test_clock_before_the_first_epoch_still_builds_and_the_evaluator_fails() -> None:
    snap = build_stage_snapshot(
        _Reads(anchors={}), _Counters(), _inputs(today=d(-3), now_ns=ns_of(d(-3)) + 100)
    )
    assert [x.day for x in snap.days] == [d(-3)]
    assert evaluate_stage(snap).kind is VerdictKind.FAIL


def test_runaway_day_range_is_refused_not_walked() -> None:
    reads = _Reads(
        epochs=(EpochRow("a", 2, None, ns_of(d(0)) - (MAX_SNAPSHOT_DAYS + 5) * 86_400 * NS),)
    )
    with pytest.raises(ValueError):
        build_stage_snapshot(reads, _Counters(), _inputs())


def test_counters_come_from_the_counter_port_and_fill_rows_from_the_store() -> None:
    reads = _Reads(fills={d(1): (_fill(d(1), "O-1", "T-1"), _fill(d(1), "O-1", "T-2"))})
    counters = _Counters(counts={d(1): DayCounts(4, 1, 1, Decimal(2))})
    snap = build_stage_snapshot(reads, counters, _inputs())
    row = next(x for x in snap.days if x.day == d(1))
    assert (row.posted, row.ambiguous) == (4, 1)
    assert row.fills is not None and len(row.fills) == 2  # partial fills of one order


def test_fill_detail_that_does_not_cover_the_counted_fills_is_missing_not_partial() -> None:
    reads = _Reads(fills={d(1): (_fill(d(1)),)})
    counters = _Counters(counts={d(1): DayCounts(4, 0, 3, Decimal(2))})  # 3 filled, 1 detailed
    row = next(x for x in build_stage_snapshot(reads, counters, _inputs()).days if x.day == d(1))
    assert row.fills is None
    assert evaluate_stage(build_stage_snapshot(reads, counters, _inputs())).kind is VerdictKind.FAIL


@pytest.mark.parametrize(
    ("what", "field_name"),
    [
        ("fills:{d}", "fills"),
        ("flags:{d}", "open_flags"),
        ("windows:{d}", "windows"),
    ],
)
def test_a_failing_per_day_read_becomes_a_none_field_never_a_default(
    what: str, field_name: str
) -> None:
    reads = _Reads(raise_on={what.format(d=d(2))})
    snap = build_stage_snapshot(reads, _Counters(), _inputs())
    row = next(x for x in snap.days if x.day == d(2))
    assert getattr(row, field_name) is None
    assert evaluate_stage(snap).reason == "stage_eval_fail:missing_counter"


def test_a_failing_counter_read_makes_posted_and_ambiguous_none() -> None:
    snap = build_stage_snapshot(_Reads(), _Counters(raise_on={d(2)}), _inputs())
    row = next(x for x in snap.days if x.day == d(2))
    assert row.posted is None and row.ambiguous is None


def test_denied_counted_is_none_without_a_classifier_and_counts_with_one() -> None:
    reads = _Reads(
        denials={
            d(1): (
                DenialRow("O-1", "k-full", d(1), 1, "STN"),
                DenialRow("O-2", "breaker", d(1), 2, "STN"),
                DenialRow("O-3", "cool-off", d(1), 3, "STN"),
            )
        }
    )
    plain = build_stage_snapshot(reads, _Counters(), _inputs())
    assert next(x for x in plain.days if x.day == d(1)).denied_counted is None
    counted = build_stage_snapshot(
        reads, _Counters(), _inputs(counted_denial=lambda reason: reason != "breaker")
    )
    assert next(x for x in counted.days if x.day == d(1)).denied_counted == 2
    assert next(x for x in counted.days if x.day == d(2)).denied_counted == 0


def test_a_classifier_that_raises_marks_the_day_none() -> None:
    reads = _Reads(denials={d(1): (DenialRow("O-1", "k-full", d(1), 1, "STN"),)})

    def boom(_: str) -> bool:
        raise RuntimeError("x")

    snap = build_stage_snapshot(reads, _Counters(), _inputs(counted_denial=boom))
    assert next(x for x in snap.days if x.day == d(1)).denied_counted is None


def test_settled_pnl_rows_become_readings_and_an_unreadable_row_becomes_none() -> None:
    row = SettledPnlDay(d(1), "-1.5", 2, 1, 0, 0, 0, "0")
    reads = _Reads(pnl={d(1): row}, raise_on={f"pnl:{d(2)}"})
    snap = build_stage_snapshot(reads, _Counters(), _inputs())
    by_day = {x.day: x.reading for x in snap.pnl_days}
    reading = by_day[d(1)]
    assert reading is not None and reading.pnl == Decimal("-1.5") and reading.settled == 2
    assert reading.ambiguous == 1
    assert by_day[d(2)] is None
    assert d(3) not in by_day  # absent row: omitted, the evaluator decides if it is required


def test_gappy_pending_unattributed_and_pass_status_are_carried() -> None:
    pending = RebuildRecord(d(2), 1, ("fills",), DayCounts(1, 0, 0, Decimal(0)))
    snap = build_stage_snapshot(
        _Reads(ambiguous_unattributed=2),
        _Counters(gappy=frozenset({d(3)}), pending={d(2): pending}),
        _inputs(pass_status=PassStatus.RECONCILE_STUCK),
    )
    assert snap.gappy_days == frozenset({d(3)})
    assert snap.pending_rebuild_days == frozenset({d(2)})
    assert snap.unattributed_ambiguous == 2
    assert snap.pass_status is PassStatus.RECONCILE_STUCK


def test_unreadable_unattributed_ambiguous_is_none() -> None:
    snap = build_stage_snapshot(_Reads(raise_on={"unattributed"}), _Counters(), _inputs())
    assert snap.unattributed_ambiguous is None
    assert evaluate_stage(snap).reason == "stage_eval_fail:unattributed_ambiguous"


@pytest.mark.parametrize("name", ["stage_reset", "epochs", "excluded", "looks", "verdicts"])
def test_a_failing_stage_level_read_propagates_it_is_never_defaulted(name: str) -> None:
    with pytest.raises(OSError):
        build_stage_snapshot(_Reads(raise_on={name}), _Counters(), _inputs())


def test_an_unknown_look_outcome_propagates() -> None:
    with pytest.raises(ValueError):
        build_stage_snapshot(_Reads(looks=(LookRow(d(1), "maybe", 1),)), _Counters(), _inputs())


def test_serial_baseline_predicates_and_clock_are_passed_through_untouched() -> None:
    baseline = SerialBaseline(fills=30, mean_slippage=Decimal("0.001"))
    preds = _Preds()
    snap = build_stage_snapshot(
        _Reads(), _Counters(), _inputs(serial_baseline=baseline, predicates=preds)
    )
    assert snap.serial_baseline is baseline
    assert snap.predicates is preds
    assert snap.governed is GOV
    assert preds.calls == 0  # the builder itself never evaluates a currency predicate
