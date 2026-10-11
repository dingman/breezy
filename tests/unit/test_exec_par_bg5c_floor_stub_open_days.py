"""EXEC-PAR BG-5c WP-C: A4 (per-station floor stub) and A5 (open days), end to end.

Two stations are used so the mixed-offset night is real: EAST (UTC-5) rolls to a new climate
day at 05:00Z, WEST (UTC-8) at 08:00Z, both in standard time all year.
"""

from __future__ import annotations

import asyncio
import dataclasses
import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from breezy.runtime.exec_par_governed_days import GovernedDays, governed_days_for
from breezy.runtime.exec_par_reconcile import DayCounts, PassStatus
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
)
from breezy.runtime.exec_par_settled_pnl import SettledPnlReading
from breezy.runtime.exec_par_stage_eval import (
    STOP_S15_CUMULATIVE,
    STOP_S15_DAY,
    STOP_S15_STAGE,
    DayCounters,
    DayPnl,
    StageSnapshot,
    Verdict,
    VerdictKind,
    evaluate_stage,
)
from breezy.runtime.exec_par_stage_runner import StageEvaluator
from breezy.runtime.exec_par_stage_snapshot import SnapshotInputs, build_stage_snapshot

NS = 1_000_000_000
HOUR = 3_600 * NS
D = Decimal


def ns_utc(month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    return int(dt.datetime(2026, month, day, hour, minute, tzinfo=dt.UTC).timestamp()) * NS


def label(month: int, day: int) -> str:
    return dt.date(2026, month, day).isoformat()


def days_obj() -> GovernedDays:
    return governed_days_for(("EAST", "WEST"), {"EAST": -5.0, "WEST": -8.0}.__getitem__)


GOV = days_obj()
#: 01:30 on the 11th for EAST, 22:30 on the 10th for WEST.
FLOOR_TS = ns_utc(10, 11, 6, 30)
FLOOR_LABELS = (label(10, 10), label(10, 11))
BOOT_TS = FLOOR_TS - HOUR
#: 01:30 on the 20th for EAST, 22:30 on the 19th for WEST: EAST is a day ahead.
NOW = ns_utc(10, 20, 6, 30)
TODAY = label(10, 19)
AHEAD = label(10, 20)


class Preds:
    """Budget = 1: breach iff aggregate <= -fraction."""

    def pnl_breaches_budget_fraction(self, *, aggregate_pnl: Decimal, fraction: Decimal) -> bool:
        return aggregate_pnl <= -fraction


def noon(day: str) -> int:
    parsed = dt.date.fromisoformat(day)
    return (
        int(dt.datetime(parsed.year, parsed.month, parsed.day, 12, tzinfo=dt.UTC).timestamp()) * NS
    )


def fill_row(day: str, coid: str, *, station: str = "EAST", arm_ns: int | None = None) -> FillRow:
    return FillRow(
        trade_id=f"t-{coid}",
        client_order_id=coid,
        day=day,
        arm_ns=noon(day) if arm_ns is None else arm_ns,
        qty="10",
        px="0.9",
        decision_ask="0.9",
        slippage="0",
        fee_realized="0.06",
        fee_exact="0.06255",
        fee_theta="0.0695",
        station=station,
    )


def counters(
    day: str,
    *,
    posted: int = 4,
    flags: tuple[OpenCostFlag, ...] = (),
    station: str = "EAST",
    first_arm: int | None = None,
) -> DayCounters:
    start = noon(day) if first_arm is None else first_arm
    fills = tuple(
        fill_row(day, f"{day}-{j}", station=station, arm_ns=start + j * 60 * NS)
        for j in range(posted)
    )
    windows = tuple(
        WindowPeak(day, start + j * 60 * NS, 1, "9", f"{day}-{j}") for j in range(posted)
    )
    return DayCounters(
        day=day,
        posted=posted,
        ambiguous=0,
        denied_counted=0,
        fills=fills,
        open_flags=flags,
        windows=windows,
    )


def reading(pnl: str = "0.01") -> SettledPnlReading:
    return SettledPnlReading(
        pnl=D(pnl), settled=4, ambiguous=0, pending=0, overdue=0, fee_unreconciled=0
    )


def span(first: dt.date, last: dt.date) -> list[str]:
    return [(first + dt.timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def build(
    *,
    through: str = AHEAD,
    stubs: dict[str, DayCounters] | None = None,
    whole_posted: dict[str, int] | None = None,
    pnl_over: dict[str, str] | None = None,
    extra_days: tuple[DayCounters, ...] = (),
    extra_pnl: tuple[DayPnl, ...] = (),
    **over: Any,
) -> StageSnapshot:
    """Stage floor 10-10/10-11; ``today`` 10-19; ``through`` is the last label in the snapshot."""
    whole_posted = whole_posted or {}
    pnl_over = pnl_over or {}
    default_stubs = {
        # WEST, 23:30 on the 10th (after the floor); EAST, 07:00 on the 11th (after the floor)
        FLOOR_LABELS[0]: counters(
            FLOOR_LABELS[0], posted=1, station="WEST", first_arm=FLOOR_TS + HOUR
        ),
        FLOOR_LABELS[1]: counters(FLOOR_LABELS[1], posted=2),
    }
    stubs = default_stubs if stubs is None else stubs
    days: list[DayCounters] = []
    pnl: list[DayPnl] = []
    for day in span(dt.date(2026, 10, 10), dt.date.fromisoformat(through)):
        posted = whole_posted.get(day, 5 if day in FLOOR_LABELS else 4)
        days.append(counters(day, posted=posted))
        pnl.append(DayPnl(day, reading(pnl_over.get(day, "0.01"))))
    base: dict[str, Any] = {
        "today": TODAY,
        "configured_k": 2,
        "effective_k": 2,
        "floor": StageReset(ts=FLOOR_TS, cause="k_change", halt_ts=None),
        "epochs": (EpochRow("sha", 2, None, BOOT_TS),),
        "excluded_days": (),
        "days": (*days, *extra_days),
        "pnl_days": (*pnl, *extra_pnl),
        "gappy_days": frozenset(),
        "pending_rebuild_days": frozenset(),
        "pass_status": PassStatus.OK,
        "looks": (),
        "stop_verdicts": (),
        "serial_baseline": None,
        "unattributed_ambiguous": 0,
        "governed": GOV,
        "predicates": Preds(),
        "floor_stubs": tuple(stubs.values()),
        # a post-floor P&L row for every stub that holds fills (WP-D writes them)
        "floor_stub_pnl": tuple(
            DayPnl(x.day, reading()) for x in stubs.values() if x.fills or x.ambiguous
        ),
    }
    base.update(over)
    return StageSnapshot(**base)


def stops(verdict: Verdict) -> tuple[str, ...]:
    assert verdict.kind is VerdictKind.STOP, verdict
    return verdict.stops


# -- A4: the floor stub is per station -----------------------------------------------------------


def test_floor_labels_are_per_station_and_the_stub_joins_the_stage() -> None:
    verdict = evaluate_stage(build())
    assert verdict.kind is not VerdictKind.FAIL, verdict.reason
    report = verdict.report
    assert report is not None
    assert report.floor_day == FLOOR_LABELS[0]  # the earliest station's floor day
    # closed labels 10-10..10-18; the two stubs (1 + 2) plus seven whole days of 4
    assert report.closed_days == 9
    assert report.posted == 1 + 2 + 7 * 4


def test_a_pre_floor_loss_on_the_floor_day_never_retrips_a_stop() -> None:
    losing_floor = build(pnl_over={FLOOR_LABELS[0]: "-0.5", FLOOR_LABELS[1]: "-0.5"})
    verdict = evaluate_stage(losing_floor)
    assert verdict.kind is not VerdictKind.STOP, verdict.stops
    assert verdict.kind is not VerdictKind.FAIL, verdict.reason


def test_the_same_loss_on_a_whole_post_floor_day_does_trip_s15() -> None:
    losing = build(pnl_over={label(10, 12): "-0.5"})
    found = stops(evaluate_stage(losing))
    assert STOP_S15_DAY in found and STOP_S15_STAGE in found


def test_floor_day_pnl_still_counts_toward_the_never_floored_cumulative_stop() -> None:
    drained = build(pnl_over={FLOOR_LABELS[0]: "-0.6", FLOOR_LABELS[1]: "-0.6"})
    assert STOP_S15_CUMULATIVE in stops(evaluate_stage(drained))


def test_a_stub_that_cannot_split_pre_and_post_floor_fails_closed() -> None:
    stubs = {x.day: x for x in build().floor_stubs}
    stubs[FLOOR_LABELS[0]] = dataclasses.replace(stubs[FLOOR_LABELS[0]], pre_floor_unknown=True)
    verdict = evaluate_stage(build(stubs=stubs))
    assert verdict.kind is VerdictKind.FAIL
    assert verdict.reason == "stage_eval_fail:pre_floor_unknown"


def test_a_missing_stub_over_non_empty_whole_day_counters_fails_closed() -> None:
    verdict = evaluate_stage(build(stubs={}))
    assert verdict.kind is VerdictKind.FAIL
    assert verdict.reason == "stage_eval_fail:pre_floor_unknown"


def test_a_missing_stub_over_an_empty_whole_day_is_an_empty_stub() -> None:
    empty = {x: counters(x, posted=0) for x in FLOOR_LABELS}
    snap = build(stubs={}, whole_posted={FLOOR_LABELS[0]: 0, FLOOR_LABELS[1]: 0})
    verdict = evaluate_stage(snap)
    assert verdict.kind is not VerdictKind.FAIL, verdict.reason
    assert verdict.report is not None and verdict.report.posted == 7 * 4
    assert empty  # (documents the shape of an explicit empty stub)


def test_a_fill_row_attributed_to_the_wrong_day_fails_closed() -> None:
    bad = dataclasses.replace(fill_row(label(10, 12), "x"), arm_ns=noon(label(10, 13)))
    days = list(build().days)
    index = next(i for i, x in enumerate(days) if x.day == label(10, 12))
    kept = days[index].fills or ()
    days[index] = dataclasses.replace(days[index], fills=(bad, *kept[1:]))
    verdict = evaluate_stage(build(days=tuple(days)))
    assert verdict.kind is VerdictKind.FAIL and verdict.reason == "stage_eval_fail:bad_counter"


# -- A5: open days ---------------------------------------------------------------------------------


def test_a_loss_on_the_open_ahead_label_trips_the_s15_day_stop_immediately() -> None:
    assert STOP_S15_DAY in stops(evaluate_stage(build(pnl_over={AHEAD: "-0.2"})))
    calm = evaluate_stage(build(pnl_over={AHEAD: "-0.01"}))
    assert calm.kind not in (VerdictKind.STOP, VerdictKind.FAIL)


def test_a_loss_on_the_open_today_label_trips_the_s15_day_stop_immediately() -> None:
    assert STOP_S15_DAY in stops(evaluate_stage(build(pnl_over={TODAY: "-0.2"})))


def test_open_data_enters_the_never_floored_cumulative_stop() -> None:
    found = stops(evaluate_stage(build(pnl_over={AHEAD: "-1.2"})))
    assert STOP_S15_CUMULATIVE in found and STOP_S15_DAY in found


def test_open_days_stay_out_of_minima_trailing_windows_and_the_cap() -> None:
    base = evaluate_stage(build())
    assert build().days[-1].day == AHEAD  # the snapshot carries the open ahead label

    def noisy(row: DayCounters) -> DayCounters:
        if row.day not in (TODAY, AHEAD):
            return row
        flag = OpenCostFlag(f"EAST@{row.day}", row.day, True, noon(row.day))
        return dataclasses.replace(row, posted=100, open_flags=(flag,))

    verdict = evaluate_stage(build(days=tuple(noisy(x) for x in build().days)))
    assert base.report is not None and verdict.report is not None
    assert verdict.report.posted == base.report.posted  # open posted never reaches the minima
    assert verdict.report.closed_days == base.report.closed_days == 9
    assert verdict.report.station_day_flag_days == ()  # the 2-of-5 trailing window is closed days
    assert verdict.kind not in (VerdictKind.STOP, VerdictKind.FAIL)


def test_an_entry_two_days_ahead_of_today_is_still_open_data() -> None:
    two_ahead = label(10, 21)
    verdict = evaluate_stage(
        build(
            extra_days=(counters(two_ahead, posted=1),), extra_pnl=(DayPnl(two_ahead, reading()),)
        )
    )
    assert verdict.kind is not VerdictKind.FAIL, verdict.reason


def test_an_entry_more_than_two_days_ahead_of_today_is_counter_missing() -> None:
    three_ahead = label(10, 22)
    verdict = evaluate_stage(
        build(
            extra_days=(counters(three_ahead, posted=1),),
            extra_pnl=(DayPnl(three_ahead, reading()),),
        )
    )
    assert verdict.kind is VerdictKind.FAIL
    assert verdict.reason == "stage_eval_fail:counter_missing"


# -- the builder: stub rows and the open tail ---------------------------------------------


def anchor(coid: str, day: str, arm_ns: int, station: str) -> OrderAnchor:
    return OrderAnchor(
        client_order_id=coid,
        slug=station,
        day=day,
        arm_ns=arm_ns,
        decision_ask="0.40",
        qty="10",
        notional="4",
        window_start_ns=arm_ns - arm_ns % (5 * NS),
        attribution="event_time",
        station=station,
    )


def b_fill(coid: str, day: str, arm_ns: int, station: str) -> FillRow:
    return dataclasses.replace(fill_row(day, coid, station=station, arm_ns=arm_ns))


@dataclass
class Reads:
    anchors: dict[str, tuple[OrderAnchor, ...]] = field(default_factory=dict)
    fills: dict[str, tuple[FillRow, ...]] = field(default_factory=dict)
    ambiguous: dict[str, tuple[AmbiguousRow, ...]] = field(default_factory=dict)
    denials: dict[str, tuple[DenialRow, ...]] = field(default_factory=dict)
    flags: dict[str, tuple[OpenCostFlag, ...]] = field(default_factory=dict)
    pnl: dict[str, SettledPnlDay] = field(default_factory=dict)

    def read_stage_reset(self) -> StageReset:
        return StageReset(FLOOR_TS, "k_change", None)

    def read_epoch_rows(self) -> tuple[EpochRow, ...]:
        return (EpochRow("sha", 2, None, BOOT_TS),)

    def read_excluded_days(self) -> tuple[ExcludedDay, ...]:
        return ()

    def read_looks(self) -> tuple[LookRow, ...]:
        return ()

    def read_stop_verdicts_since(self, ts_ns: int) -> tuple[StopVerdict, ...]:
        return ()

    def read_settled_pnl_day(self, day: str) -> SettledPnlDay | None:
        return self.pnl.get(day)

    def read_fills(self, day: str) -> tuple[FillRow, ...]:
        return self.fills.get(day, ())

    def read_denials(self, day: str) -> tuple[DenialRow, ...]:
        return self.denials.get(day, ())

    def read_open_cost_flags(self, day: str) -> tuple[OpenCostFlag, ...]:
        return self.flags.get(day, ())

    def read_window_peaks(self, day: str) -> tuple[WindowPeak, ...]:
        return ()

    def read_ambiguous(self, day: str) -> tuple[object, ...]:
        return self.ambiguous.get(day, ())

    def read_order_anchors(self, day: str) -> tuple[OrderAnchor, ...]:
        return self.anchors.get(day, ())

    def read_latest_entry_day(self) -> str | None:
        families: tuple[dict[str, Any], ...] = (
            self.anchors,
            self.ambiguous,
            self.denials,
            self.fills,
        )
        return max((day for fam in families for day, rows in fam.items() if rows), default=None)


@dataclass
class CounterReads:
    counts: dict[str, DayCounts] = field(default_factory=dict)

    def read_day_counts(self, day: str) -> DayCounts:
        return self.counts.get(day, DayCounts(0, 0, 0, D(0)))

    def read_gappy_days(self) -> frozenset[str]:
        return frozenset()

    def read_pending_rebuild(self, day: str) -> None:
        return None


def inputs(**over: Any) -> SnapshotInputs:
    base: dict[str, Any] = {
        "now_ns": NOW,
        "today": TODAY,
        "configured_k": 2,
        "effective_k": 2,
        "pass_status": PassStatus.OK,
        "governed": GOV,
        "predicates": Preds(),
        "serial_baseline": None,
        "counted_denial": lambda reason: True,
    }
    base.update(over)
    return SnapshotInputs(**base)


PRE = ns_utc(10, 10, 12)  # WEST 04:00 on the 10th: before the floor
POST_WEST = FLOOR_TS + HOUR  # WEST 23:30 on the 10th: after the floor, still label 10-10


def floor_day_reads() -> tuple[Reads, CounterReads]:
    first = FLOOR_LABELS[0]
    reads = Reads(
        anchors={
            first: (anchor("pre", first, PRE, "WEST"), anchor("post", first, POST_WEST, "WEST"))
        },
        fills={
            first: (b_fill("pre", first, PRE, "WEST"), b_fill("post", first, POST_WEST, "WEST"))
        },
        ambiguous={
            first: (
                AmbiguousRow("ipre", "armed_pre_boot", first, PRE, "slot", PRE, "WEST"),
                AmbiguousRow(
                    "ipost", "armed_post_boot", first, POST_WEST, "slot", POST_WEST, "WEST"
                ),
            )
        },
        denials={
            first: (
                DenialRow("dpre", "k-full", first, PRE, "WEST"),
                DenialRow("dpost", "k-full", first, POST_WEST, "WEST"),
            )
        },
        flags={
            first: (
                OpenCostFlag(f"WEST@{first}", first, True, PRE),
                OpenCostFlag(f"WEST2@{first}", first, False, POST_WEST),
            )
        },
    )
    counters_ = CounterReads(counts={first: DayCounts(2, 2, 2, D("8"))})
    return reads, counters_


def test_builder_floor_stub_counts_only_entries_armed_at_or_after_the_floor() -> None:
    reads, counter_reads = floor_day_reads()
    snap = build_stage_snapshot(reads, counter_reads, inputs())
    stub = {x.day: x for x in snap.floor_stubs}[FLOOR_LABELS[0]]
    assert stub.pre_floor_unknown is False
    assert stub.posted == 1 and stub.ambiguous == 1 and stub.denied_counted == 1
    assert stub.fills is not None and [f.client_order_id for f in stub.fills] == ["post"]
    assert stub.open_flags is not None and [f.station_day for f in stub.open_flags] == [
        f"WEST2@{FLOOR_LABELS[0]}"
    ]
    assert stub.windows is not None and sum(w.orders for w in stub.windows) == 1
    whole = {x.day: x for x in snap.days}[FLOOR_LABELS[0]]
    assert whole.posted == 2  # the whole-day counters are untouched (cumulative needs them)


def test_builder_stub_includes_an_entry_armed_exactly_at_the_floor() -> None:
    first = FLOOR_LABELS[0]
    reads = Reads(
        anchors={first: (anchor("edge", first, FLOOR_TS, "WEST"),)},
        fills={first: (b_fill("edge", first, FLOOR_TS, "WEST"),)},
    )
    snap = build_stage_snapshot(reads, CounterReads({first: DayCounts(1, 0, 1, D("4"))}), inputs())
    stub = {x.day: x for x in snap.floor_stubs}[first]
    assert stub.posted == 1 and stub.pre_floor_unknown is False


def test_builder_stub_is_unknown_when_counts_cannot_be_placed_on_rows() -> None:
    reads, counter_reads = floor_day_reads()
    counter_reads.counts[FLOOR_LABELS[0]] = DayCounts(5, 2, 2, D("20"))  # a BG-1d rebuild delta
    snap = build_stage_snapshot(reads, counter_reads, inputs())
    stub = {x.day: x for x in snap.floor_stubs}[FLOOR_LABELS[0]]
    assert stub.pre_floor_unknown is True
    assert evaluate_stage(snap).reason == "stage_eval_fail:pre_floor_unknown"


def test_builder_builds_a_stub_for_each_stations_floor_label_and_whole_days_elsewhere() -> None:
    reads, counter_reads = floor_day_reads()
    counter_reads.counts[label(10, 12)] = DayCounts(7, 0, 0, D(0))
    snap = build_stage_snapshot(reads, counter_reads, inputs())
    assert {x.day for x in snap.floor_stubs} == set(FLOOR_LABELS)
    whole = {x.day: x for x in snap.days}
    assert whole[label(10, 12)].posted == 7  # whole-day counters for post-floor days
    assert label(10, 12) not in {x.day for x in snap.floor_stubs}


def test_builder_reads_labels_through_the_latest_open_day_of_any_station() -> None:
    reads, counter_reads = floor_day_reads()
    snap = build_stage_snapshot(reads, counter_reads, inputs())
    labels = [x.day for x in snap.days]
    assert labels[0] == FLOOR_LABELS[0]
    assert labels[-1] == AHEAD and TODAY in labels
    assert snap.today == TODAY and snap.governed is GOV


def test_builder_probes_beyond_the_open_days_and_a_far_entry_fails_the_pass() -> None:
    reads, counter_reads = floor_day_reads()
    far = label(10, 22)  # three days after today: beyond the two-day allowance
    reads.anchors[far] = (anchor("far", far, ns_utc(10, 22, 12), "EAST"),)
    counter_reads.counts[far] = DayCounts(1, 0, 0, D("4"))
    snap = build_stage_snapshot(reads, counter_reads, inputs())
    assert far in {x.day for x in snap.days}
    assert evaluate_stage(snap).reason == "stage_eval_fail:counter_missing"


# -- A5: the daily trigger waits for the day to close ---------------------------------------


def test_the_daily_pass_waits_until_every_stations_day_has_closed() -> None:
    started: list[str] = []

    async def scenario() -> None:
        ports = SimpleNamespace(governed=GOV, settled_pnl_seq=None, monotonic_ns=lambda: 0)
        ev = StageEvaluator(ports, halt=lambda r, t: None, alert=lambda *a: True)  # type: ignore[arg-type]

        async def fake_pass(today: str) -> None:
            started.append(today)

        ev._pass = fake_pass  # type: ignore[method-assign]
        ev.bind_ingest_pending(lambda: 0)
        for hour in (6, 7):  # EAST has rolled to the 11th; WEST still on the 10th
            ev.service(ns_utc(10, 11, hour))
            await asyncio.sleep(0)
            if ev.task is not None:
                await ev.task
        assert started == [label(10, 10)]  # one boot pass, no new pass for EAST's roll
        ev.service(ns_utc(10, 11, 8, 1))  # WEST rolls: today changes
        await asyncio.sleep(0)
        if ev.task is not None:
            await ev.task

    asyncio.run(scenario())
    assert started == [label(10, 10), label(10, 11)]
