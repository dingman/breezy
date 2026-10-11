"""EXEC-PAR BG-5a: the pure stage evaluator (D-PREREG r4 + r4.1..r4.5; fakes only).

Spec sections cited per test: s1 looks/floor/cap, s5 helper, s6, s7, s9, s15,
K10 (look minimum, m-bar), L3/M5 holds, N5 outcomes, O2/O5 (never promotes).
All dates are in 2027 (never inside the M1-v3 window).
"""

from __future__ import annotations

import ast
import dataclasses
import datetime as dt
import subprocess
import sys
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pytest

from breezy.runtime import exec_par_stage_eval as mod
from breezy.runtime.exec_par_reconcile import PassStatus
from breezy.runtime.exec_par_records import (
    EpochRow,
    ExcludedDay,
    FillRow,
    OpenCostFlag,
    StageReset,
    StopVerdict,
    WindowPeak,
)
from breezy.runtime.exec_par_settled_pnl import SettledPnlReading
from breezy.runtime.exec_par_stage_eval import (
    HOLD_CAP_MINIMA_UNMET,
    HOLD_CLEANUP_DEMOTION,
    HOLD_LOOK_NOT_TAKEN,
    HOLD_LOOK_WINDOW_CLOSED,
    STOP_CLASS_REASONS,
    STOP_DEMOTION_EXCLUDED_DAYS,
    STOP_DEMOTION_SECOND_FAILED_LOOK,
    STOP_OUTCOMES,
    STOP_S5_BURST,
    STOP_S5_CLOPPER_PEARSON,
    STOP_S6_DROPPED_SHARE,
    STOP_S7_COEFFICIENT,
    STOP_S7_PER_ORDER,
    STOP_S7_PER_STAGE,
    STOP_S9_STATION_DAY_2_OF_5,
    STOP_S9_STATION_DAY_INTRADAY,
    STOP_S9_WINDOW_5S,
    STOP_S15_CUMULATIVE,
    STOP_S15_DAY,
    STOP_S15_STAGE,
    DayCounters,
    DayPnl,
    LookOutcome,
    LookRecord,
    SerialBaseline,
    StageSnapshot,
    StopOutcome,
    Verdict,
    VerdictKind,
    evaluate_stage,
    fee_stage_tolerance,
    wilson_deff_upper_bound,
)
from tests.unit.exec_par_days import UtcDays

NS = 1_000_000_000
D = Decimal
BASE = dt.date(2027, 1, 1)


def d(i: int) -> str:
    return (BASE + dt.timedelta(days=i)).isoformat()


def ns_of(day: str, hour: int = 12) -> int:
    parsed = dt.date.fromisoformat(day)
    stamp = dt.datetime(parsed.year, parsed.month, parsed.day, hour, tzinfo=dt.UTC)
    return int(stamp.timestamp()) * NS


@dataclass
class FakePredicates:
    """Budget = 1: breach iff aggregate <= -fraction. ``mode`` breaks one fraction."""

    mode: str = "ok"
    only_fraction: Decimal | None = None
    calls: list[tuple[Decimal, Decimal]] = field(default_factory=list)

    def pnl_breaches_budget_fraction(self, *, aggregate_pnl: Decimal, fraction: Decimal) -> bool:
        self.calls.append((aggregate_pnl, fraction))
        broken = self.only_fraction is None or fraction == self.only_fraction
        if broken and self.mode == "raise":
            raise RuntimeError("ledger down")
        if broken and self.mode == "nonbool":
            return 1  # type: ignore[return-value]
        return aggregate_pnl <= -fraction


def fill(
    day: str,
    coid: str,
    *,
    trade: str | None = None,
    qty: str = "10",
    px: str = "0.9",
    ask: str | None = None,
    slip: str = "0",
    realized: str = "0.06",
    exact: str = "0.06255",
    theta: str = "0.0695",
) -> FillRow:
    if ask is None:  # slippage is re-derived as px - decision_ask (fix round item 12)
        ask = str(D(px) - D(slip))
    return FillRow(
        trade_id=trade or f"t-{coid}",
        client_order_id=coid,
        day=day,
        arm_ns=ns_of(day),
        qty=qty,
        px=px,
        decision_ask=ask,
        slippage=slip,
        fee_realized=realized,
        fee_exact=exact,
        fee_theta=theta,
        station="STN",
    )


def counters(
    day: str,
    *,
    posted: int = 4,
    amb: int = 0,
    denied: int | None = 0,
    fills: tuple[FillRow, ...] | None = None,
    flags: tuple[OpenCostFlag, ...] = (),
    windows: tuple[WindowPeak, ...] | None = None,
    slip: str = "0",
) -> DayCounters:
    if fills is None:
        fills = tuple(fill(day, f"{day}-{j}", slip=slip) for j in range(posted))
    if windows is None:
        windows = tuple(
            WindowPeak(day, ns_of(day) + j * 60 * NS, 1, "9", f"{day}-{j}") for j in range(posted)
        )
    return DayCounters(
        day=day,
        posted=posted,
        ambiguous=amb,
        denied_counted=denied,
        fills=fills,
        open_flags=flags,
        windows=windows,
    )


def reading(pnl: str = "0.01", *, settled: int = 4, fee_unrec: int = 0) -> SettledPnlReading:
    return SettledPnlReading(
        pnl=D(pnl),
        settled=settled,
        ambiguous=0,
        pending=0,
        overdue=0,
        fee_unreconciled=fee_unrec,
    )


def build(
    n: int = 8,
    *,
    posted: int = 4,
    k: int = 2,
    eff: int | None = None,
    day_over: dict[int, dict[str, object]] | None = None,
    pnl_over: dict[int, str] | None = None,
    **over: object,
) -> StageSnapshot:
    """Stage with ``n`` closed days (d(1)..d(n)) plus today = d(n+1).

    The floor is the start of d(1), so d(1) is the floor-day stub (every entry on it is
    post-floor and the stub mirrors its whole-day counters); d(0) is a pre-floor day, needed for
    s15-cumulative from the first K>1 boot."""
    day_over = day_over or {}
    pnl_over = pnl_over or {}
    days: list[DayCounters] = [counters(d(0), posted=0)]
    pnl: list[DayPnl] = []
    for i in range(1, n + 2):
        kw: dict[str, object] = {"posted": posted}
        kw.update(day_over.get(i, {}))
        day_counters = counters(d(i), **kw)  # type: ignore[arg-type]
        days.append(day_counters)
        if i in pnl_over:
            pnl.append(DayPnl(d(i), reading(pnl_over[i])))
        elif day_counters.posted:
            pnl.append(DayPnl(d(i), reading()))
    base: dict[str, object] = {
        "today": d(n + 1),
        "configured_k": k,
        "effective_k": k if eff is None else eff,
        "floor": StageReset(ts=ns_of(d(1), 0), cause="k_change", halt_ts=None),
        "epochs": (EpochRow("sha", k, None, ns_of(d(0), 10)),),
        "excluded_days": (),
        "days": tuple(days),
        "pnl_days": tuple(pnl),
        "gappy_days": frozenset(),
        "pending_rebuild_days": frozenset(),
        "pass_status": PassStatus.OK,
        "looks": (),
        "stop_verdicts": (),
        "serial_baseline": None,
        "unattributed_ambiguous": 0,
        "governed": UtcDays(),
        "predicates": FakePredicates(),
    }
    base.update(over)
    if "floor_stubs" not in over:
        base["floor_stubs"] = tuple(x for x in base["days"] if x.day == d(1))  # type: ignore[attr-defined]
    return StageSnapshot(**base)  # type: ignore[arg-type]


def excl(*idx: int) -> tuple[ExcludedDay, ...]:
    return tuple(ExcludedDay(d(i), "unreconcilable:x", ns_of(d(i))) for i in idx)


def stop_reasons(v: Verdict) -> tuple[str, ...]:
    assert v.kind is VerdictKind.STOP, v
    return v.stops


# -- healthy path, never promotes (O2/O5) ------------------------------------


def test_healthy_stage_at_look_minimum_is_promotion_eligible_never_promoted() -> None:
    v = evaluate_stage(build(8))
    assert v.kind is VerdictKind.PROMOTION_ELIGIBLE
    assert v.look_number == 1
    assert v.look_blockers == ()
    assert not v.sets_flag
    assert v.report is not None and v.report.stage == "S1"
    assert not hasattr(v, "promoted")


def test_evaluate_is_deterministic_and_does_not_mutate_its_snapshot() -> None:
    snap = build(8)
    before = dataclasses.astuple(snap)[:5]
    assert evaluate_stage(snap) == evaluate_stage(snap)
    assert dataclasses.astuple(snap)[:5] == before


def test_k1_is_pass_and_not_evaluated() -> None:
    v = evaluate_stage(build(8, k=1, pnl_over={3: "-9"}))
    assert v.kind is VerdictKind.PASS and v.report is None


@pytest.mark.parametrize("k", [0, 3, 5, 7, 8])
def test_k_outside_the_ladder_is_an_integrity_fail(k: int) -> None:
    v = evaluate_stage(build(8, k=k))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:invalid_k"


def test_effective_k_above_configured_is_an_integrity_fail() -> None:
    v = evaluate_stage(build(8, k=2, eff=4))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:invalid_k"


def test_forced_k_blocks_promotion_but_not_stops() -> None:
    v = evaluate_stage(build(8, k=4, eff=1))
    assert v.kind is VerdictKind.PASS
    assert v.report is not None and v.report.promotion_blocked_reason == "k_forced"
    stopped = evaluate_stage(build(8, k=4, eff=1, pnl_over={2: "-0.2"}))
    assert stopped.kind is VerdictKind.STOP


# -- look minimum K10 / L3 ----------------------------------------------------


def test_look_needs_30_posted_orders_29_waits() -> None:
    # 7 days x 4 + 1 day x 1 = 29 posted over 8 days
    v29 = evaluate_stage(build(8, day_over={8: {"posted": 1}}))
    assert v29.kind is VerdictKind.PASS and v29.report is not None
    assert v29.report.posted == 29 and not v29.report.minima_met
    v30 = evaluate_stage(build(8, day_over={8: {"posted": 2}}))
    assert v30.kind is VerdictKind.PROMOTION_ELIGIBLE and v30.report is not None
    assert v30.report.posted == 30


def test_look_needs_8_nonexcluded_days_7_waits() -> None:
    assert evaluate_stage(build(7, posted=5)).kind is VerdictKind.PASS
    assert evaluate_stage(build(8, posted=5)).kind is VerdictKind.PROMOTION_ELIGIBLE


def test_excluded_days_never_count_toward_the_8_day_minimum() -> None:
    nine_one_excluded = build(9, posted=5, excluded_days=excl(3))
    assert evaluate_stage(nine_one_excluded).kind is VerdictKind.PROMOTION_ELIGIBLE
    nine_two_excluded = build(9, posted=5, excluded_days=excl(3, 4))
    v = evaluate_stage(nine_two_excluded)
    assert v.kind is VerdictKind.PASS and v.report is not None
    assert v.report.nonexcluded_days == 7


def test_excluded_day_data_is_skipped_even_if_gappy_or_lossy() -> None:
    v = evaluate_stage(
        build(
            9,
            posted=5,
            excluded_days=excl(3),
            gappy_days=frozenset({d(3)}),
            pnl_over={3: "-0.5"},  # would trip the day (-0.15) and stage (-0.40) stops if counted
            day_over={3: {"denied": None}},
        )
    )
    assert v.kind is VerdictKind.PROMOTION_ELIGIBLE


# -- floor (s1) ----------------------------------------------------------------


def test_floor_day_and_earlier_data_never_enter_the_stage_windows() -> None:
    pre = counters(d(0), posted=9, amb=9, flags=(OpenCostFlag("A", d(0), True, 1),))
    older = counters(d(-1), posted=9)
    snap = build(
        8,
        days=tuple(x for x in build(8).days if x.day != d(0)) + (pre, older),
        pnl_days=build(8).pnl_days + (DayPnl(d(0), reading("-0.5")), DayPnl(d(-1), reading("-9"))),
    )
    v = evaluate_stage(snap)
    assert v.kind is VerdictKind.PROMOTION_ELIGIBLE and v.report is not None
    assert v.report.posted == 32 and v.report.ambiguous == 0


def test_cumulative_is_exempt_from_the_floor_and_counts_the_floor_day() -> None:
    snap = build(8)
    snap = dataclasses.replace(snap, pnl_days=snap.pnl_days + (DayPnl(d(0), reading("-1.1")),))
    v = evaluate_stage(snap)
    assert STOP_S15_CUMULATIVE in stop_reasons(v)
    assert STOP_S15_STAGE not in v.stops and STOP_S15_DAY not in v.stops


def test_cumulative_ignores_days_before_the_first_k_gt_1_boot() -> None:
    snap = build(8)
    snap = dataclasses.replace(snap, pnl_days=snap.pnl_days + (DayPnl(d(-5), reading("-50")),))
    assert evaluate_stage(snap).kind is VerdictKind.PROMOTION_ELIGIBLE


# -- excluded days demotion (10a/H1) ------------------------------------------


def test_more_than_two_excluded_days_is_a_demotion_verdict() -> None:
    v3 = evaluate_stage(build(10, posted=5, k=4, excluded_days=excl(2, 3, 4)))
    assert v3.kind is VerdictKind.STOP and v3.reason == STOP_DEMOTION_EXCLUDED_DAYS
    assert v3.outcome is StopOutcome.DOWN_ONE_STAGE and v3.target_k == 2 and v3.sets_flag
    v2 = evaluate_stage(build(10, posted=5, k=4, excluded_days=excl(2, 3)))
    assert v2.kind is not VerdictKind.STOP


def test_excluded_days_before_the_floor_are_not_counted_in_the_stage() -> None:
    old = tuple(ExcludedDay(d(-i), "x", 1) for i in (1, 2, 3, 4))
    assert evaluate_stage(build(8, excluded_days=old)).kind is VerdictKind.PROMOTION_ELIGIBLE


# -- stage cap, L3 and M5 -------------------------------------------------------


def test_day_15_cap_holds_when_minima_unmet_day_14_still_waits() -> None:
    assert evaluate_stage(build(14, posted=0)).kind is VerdictKind.PASS
    v = evaluate_stage(build(15, posted=0))
    assert v.kind is VerdictKind.HOLD and v.reason == HOLD_CAP_MINIMA_UNMET
    assert not v.sets_flag and v.outcome is None


def test_cap_counts_excluded_days() -> None:
    v = evaluate_stage(build(15, posted=0, excluded_days=excl(2, 3)))
    assert v.kind is VerdictKind.HOLD and v.reason == HOLD_CAP_MINIMA_UNMET


def test_minima_that_become_true_only_after_the_cap_never_unhold() -> None:
    # day 15 has 0 posted; days 16+ would add orders: minima judged over the first 15 days
    over: dict[int, dict[str, object]] = {i: {"posted": 0} for i in range(1, 16)}
    over.update({16: {"posted": 40}, 17: {"posted": 40}})
    v = evaluate_stage(build(17, posted=0, day_over=over))
    assert v.kind is VerdictKind.HOLD and v.reason == HOLD_CAP_MINIMA_UNMET


def test_m5_cleanup_demotion_at_30_held_days_29_still_l3() -> None:
    v29 = evaluate_stage(build(29, posted=0))
    assert v29.kind is VerdictKind.HOLD and v29.reason == HOLD_CAP_MINIMA_UNMET
    v30 = evaluate_stage(build(30, posted=0, k=4))
    assert v30.kind is VerdictKind.HOLD and v30.reason == HOLD_CLEANUP_DEMOTION
    assert v30.target_k == 2 and not v30.sets_flag and v30.stops == ()


def test_m5_at_s1_goes_to_k1_and_pauses_the_programme() -> None:
    v = evaluate_stage(build(30, posted=0, k=2))
    assert v.reason == HOLD_CLEANUP_DEMOTION and v.target_k == 1
    assert v.report is not None and v.report.programme_paused


def test_m5_counts_nonexcluded_days_only() -> None:
    v = evaluate_stage(build(31, posted=0, excluded_days=excl(2, 3)))
    assert v.reason == HOLD_CAP_MINIMA_UNMET  # 29 non-excluded
    v = evaluate_stage(build(32, posted=0, excluded_days=excl(2, 3)))
    assert v.reason == HOLD_CLEANUP_DEMOTION  # 30 non-excluded


def test_m5_counter_is_not_reset_by_a_not_taken_look() -> None:
    looks = (LookRecord(d(10), LookOutcome.NOT_TAKEN),)
    assert evaluate_stage(build(29, looks=looks)).reason == HOLD_LOOK_NOT_TAKEN
    assert evaluate_stage(build(30, looks=looks)).reason == HOLD_CLEANUP_DEMOTION


# -- looks (s1 1-4) -------------------------------------------------------------


def test_first_failed_look_opens_a_five_day_extension() -> None:
    failed = (LookRecord(d(8), LookOutcome.FAILED),)
    v12 = evaluate_stage(build(12, looks=failed))
    assert v12.kind is VerdictKind.PASS  # only 4 days since the failed look
    v13 = evaluate_stage(build(13, looks=failed))
    assert v13.kind is VerdictKind.PROMOTION_ELIGIBLE and v13.look_number == 2


def test_extension_days_skip_excluded_days() -> None:
    failed = (LookRecord(d(8), LookOutcome.FAILED),)
    v = evaluate_stage(build(13, looks=failed, excluded_days=excl(10)))
    assert v.kind is VerdictKind.PASS
    v = evaluate_stage(build(14, looks=failed, excluded_days=excl(10)))
    assert v.kind is VerdictKind.PROMOTION_ELIGIBLE and v.look_number == 2


def test_relook_that_would_fall_after_day_15_happens_on_day_15() -> None:
    failed = (LookRecord(d(13), LookOutcome.FAILED),)
    assert evaluate_stage(build(14, looks=failed)).kind is VerdictKind.PASS
    v = evaluate_stage(build(15, looks=failed))
    assert v.kind is VerdictKind.PROMOTION_ELIGIBLE and v.look_number == 2


def test_second_failed_look_is_a_demotion_verdict() -> None:
    looks = (LookRecord(d(8), LookOutcome.FAILED), LookRecord(d(13), LookOutcome.FAILED))
    v = evaluate_stage(build(13, k=4, looks=looks))
    assert v.kind is VerdictKind.STOP and v.reason == STOP_DEMOTION_SECOND_FAILED_LOOK
    assert v.outcome is StopOutcome.DOWN_ONE_STAGE and v.target_k == 2 and v.sets_flag


def test_looks_before_the_floor_do_not_count() -> None:
    old = (LookRecord(d(-3), LookOutcome.FAILED), LookRecord(d(-1), LookOutcome.FAILED))
    v = evaluate_stage(build(8, looks=old))
    assert v.kind is VerdictKind.PROMOTION_ELIGIBLE and v.look_number == 1


def test_passed_look_leaves_the_pass_to_the_k_change_commit() -> None:
    v = evaluate_stage(build(9, looks=(LookRecord(d(8), LookOutcome.PASSED),)))
    assert v.kind is VerdictKind.PASS


def test_look_not_taken_holds_the_stage_without_a_demotion() -> None:
    v = evaluate_stage(build(9, looks=(LookRecord(d(8), LookOutcome.NOT_TAKEN),)))
    assert v.kind is VerdictKind.HOLD and v.reason == HOLD_LOOK_NOT_TAKEN and not v.sets_flag


def test_unrecorded_look_after_the_cap_holds() -> None:
    v = evaluate_stage(build(16, posted=5))
    assert v.kind is VerdictKind.HOLD and v.reason == HOLD_LOOK_WINDOW_CLOSED


def test_s3_is_terminal_no_promotion_look() -> None:
    v = evaluate_stage(build(9, k=6))
    assert v.kind is VerdictKind.PASS


# -- report fields (O5, K10) ----------------------------------------------------


def test_report_carries_day_level_ambiguous_counts_per_stage_day() -> None:
    snap = build(8, day_over={2: {"amb": 2}, 5: {"amb": 1}}, excluded_days=excl(3))
    v = evaluate_stage(snap)
    assert v.report is not None
    stats = {s.day: (s.posted, s.ambiguous) for s in v.report.day_stats}
    assert stats[d(2)] == (4, 2) and stats[d(5)] == (4, 1) and stats[d(1)] == (4, 0)
    assert d(3) not in stats and d(9) not in stats  # excluded day and open today
    assert v.report.ambiguous == 3
    assert v.report.excluded_days == (d(3),)


def test_m_bar_is_posted_over_nonexcluded_climate_days() -> None:
    v = evaluate_stage(build(9, posted=5, excluded_days=excl(3), day_over={1: {"posted": 8}}))
    assert v.report is not None
    # 8 days (day 3 excluded): 8 + 7*5 = 43 posted
    assert v.report.posted == 43 and v.report.nonexcluded_days == 8
    assert v.report.m_bar == D(43) / D(8)


def test_report_states_the_budget_flag_caveat_and_ambiguous_rate() -> None:
    v = evaluate_stage(build(8, day_over={1: {"amb": 4}}))
    assert v.report is not None
    assert v.report.ambiguous_rate == D(4) / D(32)
    assert any("budget" in note for note in v.report.notes)


def test_report_and_verdict_are_frozen_and_carry_no_currency_values() -> None:
    v = evaluate_stage(build(8, pnl_over={4: "-0.123456"}))
    assert "0.123456" not in repr(v)
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.kind = VerdictKind.PASS  # type: ignore[misc]
    assert v.report is not None
    with pytest.raises(dataclasses.FrozenInstanceError):
        v.report.posted = 0  # type: ignore[misc]


def test_section5_halt_marker_in_the_stage_blocks_the_look() -> None:
    marker = (StopVerdict(STOP_S5_BURST, ns_of(d(4))),)
    v = evaluate_stage(build(8, stop_verdicts=marker))
    assert v.kind is VerdictKind.PROMOTION_ELIGIBLE
    assert "s5_halt_in_stage" in v.look_blockers
    old = (StopVerdict(STOP_S5_BURST, ns_of(d(-4))),)
    assert evaluate_stage(build(8, stop_verdicts=old)).look_blockers == ()


# -- s6 dropped-candidate share, S3 only (K7) ------------------------------------


def _share(denied: int, posted: int) -> dict[int, dict[str, object]]:
    return {i: {"posted": posted, "denied": denied} for i in range(1, 10)}


def test_s6_share_exactly_0_30_does_not_stop_above_does_at_s3() -> None:
    v = evaluate_stage(build(8, k=6, day_over=_share(3, 7)))  # 3/10
    assert v.kind is not VerdictKind.STOP
    assert v.report is not None and v.report.dropped_share == D("0.3")
    v = evaluate_stage(build(8, k=6, day_over=_share(4, 7)))  # 4/11
    assert v.kind is VerdictKind.STOP and v.reason == STOP_S6_DROPPED_SHARE
    assert v.outcome is StopOutcome.SUSPEND and v.target_k == 1


def test_s6_needs_two_consecutive_daily_evaluations() -> None:
    over: dict[int, dict[str, object]] = {i: {"posted": 4, "denied": 0} for i in range(1, 10)}
    over[8] = {"posted": 4, "denied": 100}  # only the last closed day's window is high
    v = evaluate_stage(build(8, k=6, day_over=over))
    assert v.kind is not VerdictKind.STOP
    over[7] = {"posted": 4, "denied": 100}  # now the window ending d(7) is high too
    v = evaluate_stage(build(8, k=6, day_over=over))
    assert STOP_S6_DROPPED_SHARE in v.stops


def test_s6_uses_the_trailing_5_eligible_days_only() -> None:
    over: dict[int, dict[str, object]] = {i: {"posted": 4, "denied": 0} for i in range(1, 10)}
    over[1] = {"posted": 4, "denied": 1000}  # outside the trailing-5 windows
    over[2] = {"posted": 4, "denied": 1000}
    v = evaluate_stage(build(8, k=6, day_over=over))
    assert v.kind is not VerdictKind.STOP


def test_s6_is_report_only_before_s3_even_when_high_or_missing() -> None:
    v = evaluate_stage(build(8, k=4, day_over=_share(50, 7)))
    assert v.kind is not VerdictKind.STOP and STOP_S6_DROPPED_SHARE not in v.stops
    assert v.report is not None and v.report.dropped_share is not None
    v = evaluate_stage(build(8, k=4, day_over=_share(0, 7) | {3: {"denied": None}}))
    assert v.kind is not VerdictKind.FAIL
    assert v.report is not None and v.report.dropped_share is None


def test_s6_missing_counter_at_s3_is_fail() -> None:
    v = evaluate_stage(build(8, k=6, day_over={4: {"denied": None}}))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:missing_counter:denied"


# -- s7 fee / slippage parity -----------------------------------------------------


def _one_day_fills(day: str, *fills: FillRow) -> dict[int, dict[str, object]]:
    index = int((dt.date.fromisoformat(day) - BASE).days)
    return {index: {"fills": tuple(fills)}}


def test_s7_coefficient_must_equal_theta_exactly_and_halts() -> None:
    bad = fill(d(2), "c1", theta="0.06")
    v = evaluate_stage(build(8, day_over=_one_day_fills(d(2), bad)))
    assert v.kind is VerdictKind.STOP and STOP_S7_COEFFICIENT in v.stops
    assert v.outcome is StopOutcome.RESTART_S1 and v.target_k == 2
    near = fill(d(2), "c1", theta="0.06950")
    v = evaluate_stage(build(8, day_over=_one_day_fills(d(2), near)))
    assert STOP_S7_COEFFICIENT not in v.stops


def test_s7_unparseable_coefficient_counts_as_a_mismatch_halt() -> None:
    bad = fill(d(2), "c1", theta="None")
    v = evaluate_stage(build(8, day_over=_one_day_fills(d(2), bad)))
    assert STOP_S7_COEFFICIENT in stop_reasons(v)


def test_s7_single_fill_order_must_match_rounded_expectation_exactly() -> None:
    bad = fill(d(2), "c1", realized="0.07")
    v = evaluate_stage(build(8, day_over=_one_day_fills(d(2), bad)))
    assert STOP_S7_PER_ORDER in stop_reasons(v)
    # half-even: theta*10*0.5*0.5 = 0.17375 -> 0.17 ; 0.0695*2*0.5*0.5=0.03475 -> 0.03
    ok = fill(d(2), "c1", px="0.5", ask="0.5", exact="0.17375", realized="0.17")
    assert (
        STOP_S7_PER_ORDER not in evaluate_stage(build(8, day_over=_one_day_fills(d(2), ok))).stops
    )


def test_s7_expectation_is_rounded_to_the_cent() -> None:
    # theta*C*p*(1-p) = 0.0695*2*0.5*0.5 = 0.03475 -> 0.03 (not 0.04)
    lo = fill(d(2), "c1", qty="2", px="0.5", ask="0.5", exact="0.03475", realized="0.03")
    hi = fill(d(2), "c1", qty="2", px="0.5", ask="0.5", exact="0.03475", realized="0.04")
    assert (
        STOP_S7_PER_ORDER not in evaluate_stage(build(8, day_over=_one_day_fills(d(2), lo))).stops
    )
    assert STOP_S7_PER_ORDER in evaluate_stage(build(8, day_over=_one_day_fills(d(2), hi))).stops


def test_s7_multi_fill_order_allows_one_cent_but_not_two() -> None:
    def pair(a: str, b: str) -> dict[int, dict[str, object]]:
        f1 = fill(d(2), "c1", trade="t1", qty="5", exact="0.031275", realized=a)
        f2 = fill(d(2), "c1", trade="t2", qty="5", exact="0.031275", realized=b)
        return _one_day_fills(d(2), f1, f2)

    assert STOP_S7_PER_ORDER not in evaluate_stage(build(8, day_over=pair("0.03", "0.03"))).stops
    assert STOP_S7_PER_ORDER not in evaluate_stage(build(8, day_over=pair("0.03", "0.04"))).stops
    assert STOP_S7_PER_ORDER in evaluate_stage(build(8, day_over=pair("0.03", "0.05"))).stops


def test_s7_per_fill_mismatches_are_report_only() -> None:
    f1 = fill(d(2), "c1", trade="t1", qty="5", exact="0.031275", realized="0.02")
    f2 = fill(d(2), "c1", trade="t2", qty="5", exact="0.031275", realized="0.04")
    v = evaluate_stage(build(8, day_over=_one_day_fills(d(2), f1, f2)))
    assert v.kind is VerdictKind.PROMOTION_ELIGIBLE
    assert v.report is not None and v.report.per_fill_fee_mismatches == 2


def test_s7_per_stage_tolerance_is_max_2c_or_half_cent_per_order() -> None:
    assert fee_stage_tolerance(0) == D("0.02")
    assert fee_stage_tolerance(4) == D("0.02")
    assert fee_stage_tolerance(5) == D("0.025")
    assert fee_stage_tolerance(40) == D("0.2")


def test_s7_per_stage_halts_when_every_multi_fill_order_runs_one_cent_high() -> None:
    over: dict[int, dict[str, object]] = {}
    for i in range(1, 10):
        f1 = fill(d(i), f"{d(i)}-a", trade=f"{d(i)}-1", qty="5", exact="0.031275", realized="0.03")
        f2 = fill(d(i), f"{d(i)}-a", trade=f"{d(i)}-2", qty="5", exact="0.031275", realized="0.04")
        over[i] = {"fills": (f1, f2), "posted": 4}
    v = evaluate_stage(build(8, day_over=over))
    assert STOP_S7_PER_STAGE in stop_reasons(v) and STOP_S7_PER_ORDER not in v.stops


def test_s7_missing_decision_ask_is_fail() -> None:
    bad = fill(d(2), "c1", ask="")
    v = evaluate_stage(build(8, day_over=_one_day_fills(d(2), bad)))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:fill_decimal"


def _slip_snapshot(
    slow: int = 0, *, slip: str = "0.03", base: str = "0", unrec: int = 0, **kw: Any
) -> StageSnapshot:
    over: dict[int, dict[str, object]] = {}
    count = 0
    for i in range(1, 10):
        fills = []
        for j in range(5):
            fills.append(fill(d(i), f"{d(i)}-{j}", slip=slip if count < slow else base))
            count += 1
        over[i] = {"fills": tuple(fills), "posted": 5}
    snap = build(8, posted=5, day_over=over, **kw)
    if unrec:
        pnl = list(snap.pnl_days)
        pnl[0] = DayPnl(pnl[0].day, reading(fee_unrec=unrec))
        snap = dataclasses.replace(snap, pnl_days=tuple(pnl))
    return snap


def test_slippage_tail_ten_percent_ok_eleven_blocks_the_look() -> None:
    ok = evaluate_stage(_slip_snapshot(4, slip="0.03", base="0"))  # 4/40 = 10%
    assert ok.kind is VerdictKind.PROMOTION_ELIGIBLE and "slippage_tail" not in ok.look_blockers
    bad = evaluate_stage(_slip_snapshot(5, slip="0.03", base="0"))  # 12.5%
    assert "slippage_tail" in bad.look_blockers
    boundary = evaluate_stage(_slip_snapshot(40, slip="0.02", base="0"))  # 0.02 is not above
    assert "slippage_tail" not in boundary.look_blockers


def test_slippage_mean_0_005_ok_above_blocks_the_look() -> None:
    ok = evaluate_stage(_slip_snapshot(40, slip="0.005"))
    assert "slippage_mean" not in ok.look_blockers
    bad = evaluate_stage(_slip_snapshot(40, slip="0.0051"))
    assert "slippage_mean" in bad.look_blockers


def test_fee_unreconciled_share_ten_percent_ok_above_blocks_the_look() -> None:
    assert "fee_unreconciled" not in evaluate_stage(_slip_snapshot(unrec=4)).look_blockers
    assert "fee_unreconciled" in evaluate_stage(_slip_snapshot(unrec=5)).look_blockers


def test_parity_only_gates_with_20_serial_fills() -> None:
    ok = evaluate_stage(
        _slip_snapshot(40, slip="0.005", serial_baseline=SerialBaseline(20, D("0")))
    )
    assert "parity" not in ok.look_blockers
    assert ok.report is not None and ok.report.parity_diff == D("0.005")
    bad = evaluate_stage(
        _slip_snapshot(40, slip="0.005", serial_baseline=SerialBaseline(20, D("-0.0001")))
    )
    assert "parity" in bad.look_blockers
    few = evaluate_stage(
        _slip_snapshot(40, slip="0.005", serial_baseline=SerialBaseline(19, D("-0.5")))
    )
    assert "parity" not in few.look_blockers
    assert few.report is not None and few.report.parity_diff == D("0.505")


def test_parity_baseline_with_20_fills_but_no_mean_is_fail() -> None:
    v = evaluate_stage(_slip_snapshot(serial_baseline=SerialBaseline(25, None)))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:parity_baseline"


def test_look_blocked_when_fewer_than_5_days_have_a_fill() -> None:
    over: dict[int, dict[str, object]] = {i: {"fills": ()} for i in range(1, 6)}
    v = evaluate_stage(build(8, day_over=over))
    assert v.kind is VerdictKind.PROMOTION_ELIGIBLE
    assert "fill_days_below_5" in v.look_blockers and "no_fills" not in v.look_blockers
    ok = evaluate_stage(build(8, day_over={i: {"fills": ()} for i in range(1, 4)}))
    assert "fill_days_below_5" not in ok.look_blockers


# -- s9 concentration -----------------------------------------------------------------


def _flag(day: str) -> tuple[OpenCostFlag, ...]:
    return (OpenCostFlag("NYC", day, False, 1), OpenCostFlag("CHI", day, True, 2))


def test_s9_station_day_2_of_last_5_days_is_a_demotion() -> None:
    one = evaluate_stage(build(8, day_over={8: {"flags": _flag(d(8))}}))
    assert STOP_S9_STATION_DAY_2_OF_5 not in one.stops
    two = evaluate_stage(
        build(8, k=4, day_over={7: {"flags": _flag(d(7))}, 8: {"flags": _flag(d(8))}})
    )
    assert two.kind is VerdictKind.STOP and two.reason == STOP_S9_STATION_DAY_2_OF_5
    assert two.outcome is StopOutcome.DOWN_ONE_STAGE and two.target_k == 2 and two.sets_flag


def test_s9_flags_older_than_the_last_5_days_do_not_count() -> None:
    v = evaluate_stage(build(8, day_over={1: {"flags": _flag(d(1))}, 2: {"flags": _flag(d(2))}}))
    assert STOP_S9_STATION_DAY_2_OF_5 not in v.stops
    edge = evaluate_stage(build(8, day_over={4: {"flags": _flag(d(4))}, 8: {"flags": _flag(d(8))}}))
    assert STOP_S9_STATION_DAY_2_OF_5 in edge.stops  # days 4..8 are the last five


def test_s9_excluded_days_are_skipped_so_the_window_reaches_further_back() -> None:
    snap = build(
        8,
        excluded_days=excl(8),
        day_over={3: {"flags": _flag(d(3))}, 7: {"flags": _flag(d(7))}},
    )
    # eligible closed days 1..7: last five are 3..7
    assert STOP_S9_STATION_DAY_2_OF_5 in evaluate_stage(snap).stops


def _burst(day: str, notionals: list[str], per_window: int = 1) -> tuple[WindowPeak, ...]:
    return tuple(
        WindowPeak(day, ns_of(day) + j * 5 * NS, per_window, n, f"{day}-w{j}")
        for j, n in enumerate(notionals)
    )


def test_s9_five_second_window_share_over_half_on_2_of_5_days() -> None:
    hot = ["60", "10", "10", "10", "5", "5"]  # 6 orders, 60/100 = 0.6
    snap = build(
        8,
        k=6,
        day_over={7: {"windows": _burst(d(7), hot)}, 8: {"windows": _burst(d(8), hot)}},
    )
    v = evaluate_stage(snap)
    assert v.kind is VerdictKind.STOP and v.reason == STOP_S9_WINDOW_5S
    assert v.outcome is StopOutcome.DOWN_ONE_STAGE and v.target_k == 4


def test_s9_five_second_share_exactly_half_does_not_flag() -> None:
    half = ["50", "10", "10", "10", "10", "10"]
    snap = build(
        8,
        day_over={7: {"windows": _burst(d(7), half)}, 8: {"windows": _burst(d(8), half)}},
    )
    assert STOP_S9_WINDOW_5S not in evaluate_stage(snap).stops


def test_s9_five_second_rule_needs_at_least_6_orders_on_the_day() -> None:
    five = ["90", "5", "5", "5", "5"]  # 5 orders, share 0.82
    snap = build(
        8,
        day_over={7: {"windows": _burst(d(7), five)}, 8: {"windows": _burst(d(8), five)}},
    )
    assert STOP_S9_WINDOW_5S not in evaluate_stage(snap).stops
    six = ["90", "5", "5", "5", "5", "5"]
    snap = build(8, day_over={7: {"windows": _burst(d(7), six)}, 8: {"windows": _burst(d(8), six)}})
    assert STOP_S9_WINDOW_5S in evaluate_stage(snap).stops


def test_s9_five_second_rule_counts_orders_not_windows() -> None:
    # 3 windows holding 2 orders each = 6 orders
    day7 = _burst(d(7), ["70", "15", "15"], per_window=2)
    day8 = _burst(d(8), ["70", "15", "15"], per_window=2)
    snap = build(8, day_over={7: {"windows": day7}, 8: {"windows": day8}})
    assert STOP_S9_WINDOW_5S in evaluate_stage(snap).stops


def test_s9_intraday_constant_is_exported_for_bg6() -> None:
    assert STOP_S9_STATION_DAY_INTRADAY in STOP_CLASS_REASONS
    assert STOP_OUTCOMES[STOP_S9_STATION_DAY_INTRADAY] is StopOutcome.RESTART_S1


# -- s15 P&L stops through the predicate port ------------------------------------------


@pytest.mark.parametrize(
    ("pnl", "trips"),
    [("-0.15", True), ("-0.1500001", True), ("-0.1499999", False), ("-0.14", False)],
)
def test_s15_day_stop_boundary(pnl: str, trips: bool) -> None:
    v = evaluate_stage(build(8, k=2, pnl_over={3: pnl}))
    assert (STOP_S15_DAY in v.stops) is trips
    if trips:
        assert v.outcome is StopOutcome.RESTART_S1 and v.target_k == 2 and v.sets_flag


def test_s15_day_stop_applies_to_the_open_day_too() -> None:
    assert STOP_S15_DAY in evaluate_stage(build(8, pnl_over={9: "-0.2"})).stops


def test_s15_day_stop_skips_excluded_days_and_the_floor_day() -> None:
    snap = build(8, excluded_days=excl(3), pnl_over={3: "-5"})
    assert STOP_S15_DAY not in evaluate_stage(snap).stops
    assert STOP_S15_CUMULATIVE in evaluate_stage(snap).stops  # cumulative still counts it


def test_s15_stage_stop_boundary_minus_0_40_over_the_stage() -> None:
    # A4: d(1) is the floor-day stub (not stage data); the stage is d(2)..d(8) plus the open d(9)
    each_ok = {i: "-0.0499" for i in range(2, 10)} | {1: "0"}  # -0.3992 total
    each_trip = {i: "-0.05" for i in range(2, 10)} | {1: "0"}  # -0.40 total
    ok = evaluate_stage(build(8, pnl_over=each_ok))
    assert STOP_S15_STAGE not in ok.stops
    bad = evaluate_stage(build(8, k=4, pnl_over=each_trip))
    assert bad.kind is VerdictKind.STOP and bad.reason == STOP_S15_STAGE
    assert bad.outcome is StopOutcome.DOWN_ONE_STAGE and bad.target_k == 2


def test_s15_stage_stop_skips_excluded_days() -> None:
    over = {2: "-0.14", 3: "-0.14", 4: "-0.14", 5: "-0.14"}
    snap = build(8, excluded_days=excl(2), pnl_over=over)
    # with day 2 the stage total is -0.51 (stop); without it -0.37 (no stop)
    assert STOP_S15_STAGE not in evaluate_stage(snap).stops


def test_s15_cumulative_stop_at_minus_1_0_includes_excluded_days_and_is_k1() -> None:
    snap = build(8, excluded_days=excl(5), pnl_over={5: "-1.08"})  # +0.08 elsewhere: -1.00 total
    v = evaluate_stage(snap)
    assert v.kind is VerdictKind.STOP and v.reason == STOP_S15_CUMULATIVE
    assert v.outcome is StopOutcome.K1_AMENDMENT and v.target_k == 1 and v.sets_flag
    near = evaluate_stage(build(8, excluded_days=excl(5), pnl_over={5: "-1.07"}))
    assert STOP_S15_CUMULATIVE not in near.stops


def test_s15_passes_aggregates_and_budget_fractions_to_the_port() -> None:
    preds = FakePredicates()
    evaluate_stage(build(8, predicates=preds, pnl_over={2: "-0.01"}))
    fractions = {f for _, f in preds.calls}
    assert fractions == {D("0.15"), D("0.40"), D("1.0")}
    assert all(type(a) is Decimal for a, _ in preds.calls)
    stage_total = [a for a, f in preds.calls if f == D("0.40")]
    # A4: d(1) is the floor-day stub and its whole-day P&L is skipped: d(2)..d(8) and the open
    # d(9) are 8 days of +0.01, minus 0.02 on day 2
    assert stage_total == [D("0.06")]


@pytest.mark.parametrize("mode", ["raise", "nonbool"])
@pytest.mark.parametrize(
    ("fraction", "name"),
    [("0.15", "s15_day"), ("0.40", "s15_stage"), ("1.0", "s15_cumulative")],
)
def test_predicate_raise_or_nonbool_is_a_fail_naming_the_predicate(
    mode: str, fraction: str, name: str
) -> None:
    preds = FakePredicates(mode=mode, only_fraction=D(fraction))
    v = evaluate_stage(build(8, predicates=preds))
    assert v.kind is VerdictKind.FAIL and not v.sets_flag
    assert v.reason == f"stage_eval_fail:predicate:{name}"


def test_predicate_failure_dominates_a_stop_found_by_another_rule() -> None:
    preds = FakePredicates(mode="raise", only_fraction=D("1.0"))
    v = evaluate_stage(build(8, predicates=preds, excluded_days=excl(2, 3, 4)))
    assert v.kind is VerdictKind.FAIL


def test_missing_pnl_row_for_a_day_with_entries_is_fail_never_zero() -> None:
    snap = build(8)
    snap = dataclasses.replace(snap, pnl_days=tuple(p for p in snap.pnl_days if p.day != d(4)))
    v = evaluate_stage(snap)
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:settled_pnl_missing"


def test_unreadable_pnl_reading_is_fail() -> None:
    snap = build(8)
    pnl = tuple(DayPnl(p.day, None) if p.day == d(4) else p for p in snap.pnl_days)
    v = evaluate_stage(dataclasses.replace(snap, pnl_days=pnl))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:settled_pnl_missing"


def test_a_day_without_entries_needs_no_pnl_row() -> None:
    v = evaluate_stage(build(8, day_over={2: {"posted": 0}}, posted=5))
    assert v.kind is VerdictKind.PROMOTION_ELIGIBLE or v.kind is VerdictKind.PASS


# -- outcomes and precedence ("After a halt", N5) ------------------------------------------


EXPECTED_OUTCOMES = {
    STOP_S5_CLOPPER_PEARSON: StopOutcome.RESTART_S1,
    STOP_S5_BURST: StopOutcome.RESTART_S1,
    STOP_S6_DROPPED_SHARE: StopOutcome.SUSPEND,
    STOP_S7_COEFFICIENT: StopOutcome.RESTART_S1,
    STOP_S7_PER_ORDER: StopOutcome.RESTART_S1,
    STOP_S7_PER_STAGE: StopOutcome.RESTART_S1,
    STOP_S9_STATION_DAY_INTRADAY: StopOutcome.RESTART_S1,
    STOP_S9_STATION_DAY_2_OF_5: StopOutcome.DOWN_ONE_STAGE,
    STOP_S9_WINDOW_5S: StopOutcome.DOWN_ONE_STAGE,
    STOP_S15_DAY: StopOutcome.RESTART_S1,
    STOP_S15_STAGE: StopOutcome.DOWN_ONE_STAGE,
    STOP_S15_CUMULATIVE: StopOutcome.K1_AMENDMENT,
    STOP_DEMOTION_SECOND_FAILED_LOOK: StopOutcome.DOWN_ONE_STAGE,
    STOP_DEMOTION_EXCLUDED_DAYS: StopOutcome.DOWN_ONE_STAGE,
}


def test_every_stop_reason_maps_to_the_after_a_halt_outcome() -> None:
    assert dict(STOP_OUTCOMES) == EXPECTED_OUTCOMES
    assert STOP_CLASS_REASONS == frozenset(EXPECTED_OUTCOMES)


def test_stop_reason_constants_are_distinct_strings() -> None:
    assert len(set(EXPECTED_OUTCOMES)) == len(EXPECTED_OUTCOMES)
    assert all(isinstance(r, str) and r for r in EXPECTED_OUTCOMES)


@pytest.mark.parametrize(
    ("k", "outcome", "target"),
    [
        (2, StopOutcome.DOWN_ONE_STAGE, 1),
        (4, StopOutcome.DOWN_ONE_STAGE, 2),
        (6, StopOutcome.DOWN_ONE_STAGE, 4),
        (2, StopOutcome.RESTART_S1, 2),
        (4, StopOutcome.RESTART_S1, 2),
        (6, StopOutcome.RESTART_S1, 2),
    ],
)
def test_target_k_follows_the_ladder(k: int, outcome: StopOutcome, target: int) -> None:
    reason = STOP_S15_STAGE if outcome is StopOutcome.DOWN_ONE_STAGE else STOP_S15_DAY
    # A4: d(1) is the floor-day stub, so its whole-day P&L is not stage data
    stage = {i: "-0.06" for i in range(2, 9)} | {1: "0", 9: "0"}
    pnl = stage if reason == STOP_S15_STAGE else {3: "-0.2"}
    v = evaluate_stage(build(8, k=k, pnl_over=pnl))
    assert v.reason == reason and v.outcome is outcome and v.target_k == target


def test_multiple_stops_report_the_most_restrictive_and_list_all() -> None:
    bad_fee = fill(d(2), "c1", theta="0.06")
    snap = build(8, k=4, day_over=_one_day_fills(d(2), bad_fee), pnl_over={5: "-1.1"})
    v = evaluate_stage(snap)
    assert v.reason == STOP_S15_CUMULATIVE and v.target_k == 1
    assert {STOP_S7_COEFFICIENT, STOP_S15_CUMULATIVE, STOP_S15_DAY} <= set(v.stops)


def test_s1_restart_beats_nothing_and_demotion_at_s1_goes_to_k1() -> None:
    snap = build(8, k=2, pnl_over={3: "-0.2"} | {i: "-0.05" for i in (1, 2, 4, 5, 6, 7, 8)})
    v = evaluate_stage(snap)
    # day stop (restart S1 -> K=2) and stage stop (down one -> K=1): K=1 is more restrictive
    assert v.reason == STOP_S15_STAGE and v.target_k == 1


# -- integrity (FAIL) -----------------------------------------------------------------------


def test_reconcile_stuck_pass_status_is_fail() -> None:
    v = evaluate_stage(build(8, pass_status=PassStatus.RECONCILE_STUCK))
    assert v.kind is VerdictKind.FAIL and v.reason == "reconcile_stuck" and not v.sets_flag


def test_still_gappy_day_in_the_stage_is_fail() -> None:
    v = evaluate_stage(build(8, gappy_days=frozenset({d(4)})))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:gappy"


def test_gappy_today_counts_and_gappy_pre_floor_does_not() -> None:
    assert evaluate_stage(build(8, gappy_days=frozenset({d(9)}))).kind is VerdictKind.FAIL
    pre = evaluate_stage(build(8, gappy_days=frozenset({d(0), d(-3)})))
    assert pre.kind is VerdictKind.PROMOTION_ELIGIBLE


def test_pending_rebuild_day_in_the_stage_is_fail() -> None:
    v = evaluate_stage(build(8, pending_rebuild_days=frozenset({d(2)})))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:pending_rebuild"


def test_fail_dominates_a_stop() -> None:
    snap = build(8, gappy_days=frozenset({d(2)}), pnl_over={3: "-9"})
    assert evaluate_stage(snap).kind is VerdictKind.FAIL


def test_missing_day_counters_are_fail() -> None:
    snap = build(8)
    snap = dataclasses.replace(snap, days=tuple(x for x in snap.days if x.day != d(3)))
    v = evaluate_stage(snap)
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:missing_day"


def test_missing_todays_counters_are_fail() -> None:
    snap = build(8)
    snap = dataclasses.replace(snap, days=tuple(x for x in snap.days if x.day != d(9)))
    assert evaluate_stage(snap).kind is VerdictKind.FAIL


@pytest.mark.parametrize("field_name", ["posted", "ambiguous", "fills", "open_flags", "windows"])
def test_none_counter_field_is_fail_not_zero(field_name: str) -> None:
    snap = build(8)
    changes: dict[str, Any] = {field_name: None}
    broken = tuple(dataclasses.replace(x, **changes) if x.day == d(3) else x for x in snap.days)
    v = evaluate_stage(dataclasses.replace(snap, days=broken))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:missing_counter"


def test_negative_or_inconsistent_counters_are_fail() -> None:
    v = evaluate_stage(build(8, day_over={3: {"posted": 2, "amb": 3}}))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:bad_counter"


def test_duplicate_day_counters_are_fail() -> None:
    snap = build(8)
    v = evaluate_stage(dataclasses.replace(snap, days=snap.days + (snap.days[0],)))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:duplicate_day"


def test_unattributed_ambiguous_entries_are_fail() -> None:
    v = evaluate_stage(build(8, unattributed_ambiguous=1))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:unattributed_ambiguous"
    v = evaluate_stage(build(8, unattributed_ambiguous=None))
    assert v.kind is VerdictKind.FAIL


def test_missing_floor_is_fail() -> None:
    v = evaluate_stage(build(8, floor=None))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:floor_missing"


def test_today_before_the_floor_day_is_non_monotonic_fail() -> None:
    v = evaluate_stage(build(8, today=d(-1)))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:non_monotonic"


def test_non_monotonic_epochs_are_fail() -> None:
    epochs = (EpochRow("a", 2, None, ns_of(d(0), 10)), EpochRow("b", 2, None, ns_of(d(0), 9)))
    v = evaluate_stage(build(8, epochs=epochs))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:non_monotonic"


def test_no_k_gt_1_epoch_is_not_a_fail_cumulative_starts_today() -> None:
    # fix round item 9: a node forced to K=1 from its first boot is legitimately serial
    v = evaluate_stage(build(8, epochs=(EpochRow("a", 1, None, ns_of(d(0), 10)),)))
    assert v.kind is VerdictKind.PROMOTION_ELIGIBLE


def test_bad_today_label_is_fail() -> None:
    v = evaluate_stage(build(8, today="not-a-date"))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:bad_day"


# -- Wilson-DEFF helper (ICC is an argument, never estimated) ---------------------------------


def test_wilson_deff_upper_bound_known_values() -> None:
    # k=7, n=39, no design effect, one-sided 90%: plain Wilson upper bound
    assert wilson_deff_upper_bound(
        7, 39, icc=0.0, m_bar=3.0, z=mod.Z_ONE_SIDED_90
    ) == pytest.approx(0.2707, abs=5e-4)


def test_wilson_deff_widens_with_icc_and_m_bar_and_95_is_wider_than_90() -> None:
    base = wilson_deff_upper_bound(7, 39, icc=0.0, m_bar=3.0, z=mod.Z_ONE_SIDED_90)
    wide = wilson_deff_upper_bound(7, 39, icc=0.4147, m_bar=3.0, z=mod.Z_ONE_SIDED_90)
    assert wide > base
    assert wilson_deff_upper_bound(7, 39, icc=0.4147, m_bar=3.0, z=mod.Z_ONE_SIDED_95) > wide
    assert wilson_deff_upper_bound(7, 39, icc=0.4147, m_bar=1.0, z=mod.Z_ONE_SIDED_90) == base


def test_wilson_deff_edges_and_validation() -> None:
    assert 0.0 < wilson_deff_upper_bound(0, 30, icc=0.1, m_bar=4.0, z=mod.Z_ONE_SIDED_90) < 1.0
    assert wilson_deff_upper_bound(
        30, 30, icc=0.1, m_bar=4.0, z=mod.Z_ONE_SIDED_90
    ) == pytest.approx(1.0)
    for args in [(1, 0, 0.1), (-1, 10, 0.1), (11, 10, 0.1), (1, 10, -0.1)]:
        with pytest.raises(ValueError):
            wilson_deff_upper_bound(args[0], args[1], icc=args[2], m_bar=2.0, z=1.28)


def test_evaluator_signature_has_no_icc_estimation_inputs() -> None:
    names = {f.name for f in dataclasses.fields(StageSnapshot)}
    assert not any("icc" in n for n in names)
    assert not any("icc" in f.name for f in dataclasses.fields(Verdict))


# -- scale and purity ---------------------------------------------------------------------------


def test_many_fills_still_evaluate_correctly() -> None:
    over: dict[int, dict[str, object]] = {}
    for i in range(1, 10):
        fills = tuple(fill(d(i), f"{d(i)}-{j}") for j in range(1_200))
        over[i] = {"fills": fills, "posted": 1_200}
    v = evaluate_stage(build(8, day_over=over))
    assert v.kind is VerdictKind.PROMOTION_ELIGIBLE
    assert v.report is not None and v.report.fills == 8 * 1_200


MODULE_PATH = Path(mod.__file__)


def _imported_modules() -> set[str]:
    tree = ast.parse(MODULE_PATH.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def test_module_imports_no_nautilus_adapters_io_clock_or_logging() -> None:
    imported = _imported_modules()
    forbidden = ("nautilus_trader", "breezy.adapters", "logging", "time", "os", "sqlite3", "random")
    for name in imported:
        assert not name.startswith(forbidden), name
    assert "breezy.runtime.breaker_watcher" not in imported
    assert "breezy.runtime.submit_intent" not in imported


def test_module_has_no_clock_reads_or_logging_calls() -> None:
    source = MODULE_PATH.read_text()
    for token in (
        "datetime.now",
        "date.today",
        "time.time",
        "monotonic_ns",
        "time.monotonic",
        "logger.",
        "print(",
    ):
        assert token not in source, token


def test_importing_the_module_does_not_load_nautilus_or_the_adapters() -> None:
    code = (
        "import sys, breezy.runtime.exec_par_stage_eval;"
        "bad=[m for m in sys.modules if m.startswith(('nautilus_trader','breezy.adapters'))];"
        "print(','.join(bad)); sys.exit(1 if bad else 0)"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout + done.stderr


# -- fix round (spec-fidelity 78 / failure-mode 62 reviews) --------------------------------------


def _floor_day_today(pnl: str, *, posted: int = 4) -> StageSnapshot:
    """``today`` is the floor day itself (a stop_clear on day D): the floor is d(0) at noon and
    every entry on d(0) is armed at noon, so the floor-day stub holds all of them (A4)."""
    return build(
        0,
        today=d(0),
        floor=StageReset(ts=ns_of(d(0)), cause="k_change", halt_ts=None),
        days=(counters(d(0), posted=posted),),
        floor_stubs=(counters(d(0), posted=posted),),
        pnl_days=(DayPnl(d(0), reading(pnl)),),
    )


def test_h1_today_equal_to_floor_day_is_excluded_from_every_floored_window() -> None:
    v = evaluate_stage(_floor_day_today("-0.5"))
    assert v.kind is VerdictKind.PASS and v.stops == ()
    assert v.report is not None and v.report.closed_days == 0 and v.report.posted == 0


def test_h1_cumulative_still_trips_on_a_floor_day_loss() -> None:
    v = evaluate_stage(_floor_day_today("-1.2"))
    assert v.kind is VerdictKind.STOP and v.stops == (STOP_S15_CUMULATIVE,)
    assert STOP_S15_DAY not in v.stops and STOP_S15_STAGE not in v.stops


def test_h1_floor_day_counters_are_not_validated_as_stage_data() -> None:
    floor = StageReset(ts=ns_of(d(0)), cause="k_change", halt_ts=None)
    stub = counters(d(0), posted=4, denied=None)
    snap = build(0, today=d(0), floor=floor, days=(stub,), floor_stubs=(stub,),
                 pnl_days=(DayPnl(d(0), reading("0.01")),))  # fmt: skip
    assert evaluate_stage(snap).kind is VerdictKind.PASS


@pytest.mark.parametrize(
    ("k", "eff", "pnl", "target"),
    [
        (4, 1, {3: "-0.2"}, 1),
        (6, 2, {3: "-0.2"}, 2),
        (4, 2, {3: "-0.2"}, 2),
        (4, 4, {3: "-0.2"}, 2),
    ],
)
def test_h2_target_k_is_clamped_to_a_forced_effective_k(
    k: int, eff: int, pnl: dict[int, str], target: int
) -> None:
    v = evaluate_stage(build(8, k=k, eff=eff, pnl_over=pnl))
    assert v.reason == STOP_S15_DAY and v.target_k == target


def test_h2_down_one_stage_is_clamped_too() -> None:
    # A4: d(1) is the floor-day stub, so its whole-day P&L is not stage data
    each = {i: "-0.06" for i in range(2, 9)} | {1: "0", 9: "0"}
    v = evaluate_stage(build(8, k=4, eff=1, pnl_over=each))
    assert v.reason == STOP_S15_STAGE and v.target_k == 1


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_h3_non_finite_pnl_is_fail(bad: str) -> None:
    snap = build(8)
    pnl = tuple(DayPnl(p.day, reading(bad)) if p.day == d(3) else p for p in snap.pnl_days)
    v = evaluate_stage(dataclasses.replace(snap, pnl_days=pnl))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:pnl_nonfinite"


@pytest.mark.parametrize("field_name", ["fee_realized", "fee_exact"])
@pytest.mark.parametrize("bad", ["NaN", "Infinity"])
def test_h3_non_finite_fee_is_fail(field_name: str, bad: str) -> None:
    changes: dict[str, Any] = {field_name: bad}
    row = dataclasses.replace(fill(d(2), "c1"), **changes)
    v = evaluate_stage(build(8, day_over=_one_day_fills(d(2), row)))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:pnl_nonfinite"


@pytest.mark.parametrize(
    "field_name", ["settled", "ambiguous", "pending", "overdue", "fee_unreconciled"]
)
def test_h3_negative_reading_counts_are_fail(field_name: str) -> None:
    snap = build(8)
    reading_2 = snap.pnl_days[2].reading
    assert reading_2 is not None
    changes: dict[str, Any] = {field_name: -1}
    broken = dataclasses.replace(reading_2, **changes)
    pnl = tuple(DayPnl(p.day, broken) if p is snap.pnl_days[2] else p for p in snap.pnl_days)
    v = evaluate_stage(dataclasses.replace(snap, pnl_days=pnl))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:bad_counter"


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"px": "1.5"}, "fill_sanity"),
        ({"px": "-0.1"}, "fill_sanity"),
        ({"qty": "0"}, "fill_sanity"),
        ({"qty": "-3"}, "fill_sanity"),
        ({"px": 0.9}, "fill_decimal"),
        ({"qty": 10}, "fill_decimal"),
    ],
)
def test_h3_fill_sanity_and_no_float_input(changes: dict[str, Any], reason: str) -> None:
    row = dataclasses.replace(fill(d(2), "c1", ask="0.9"), **changes)
    v = evaluate_stage(build(8, day_over=_one_day_fills(d(2), row)))
    assert v.kind is VerdictKind.FAIL and v.reason == f"stage_eval_fail:{reason}"


def test_h3_decimal_objects_are_accepted_as_fill_input() -> None:
    # deliberately a Decimal where FillRow.qty is typed str: the evaluator must accept it
    row = dataclasses.replace(fill(d(2), "c1"), qty=cast("str", D("10")))
    assert evaluate_stage(build(8, day_over=_one_day_fills(d(2), row))).kind is not VerdictKind.FAIL


def test_h3_duplicate_fill_ids_are_fail() -> None:
    a = fill(d(2), "c1", trade="dup")
    b = fill(d(3), "c2", trade="dup")
    snap = build(8, day_over=_one_day_fills(d(2), a) | _one_day_fills(d(3), b))
    v = evaluate_stage(snap)
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:duplicate_fill"


@pytest.mark.parametrize(
    "args",
    [
        {"icc": float("nan")},
        {"icc": float("inf")},
        {"m_bar": float("nan")},
        {"m_bar": float("inf")},
        {"z": float("nan")},
        {"z": float("inf")},
    ],
)
def test_h3_wilson_rejects_non_finite_floats(args: dict[str, float]) -> None:
    kw = {"icc": 0.1, "m_bar": 3.0, "z": 1.28} | args
    with pytest.raises(ValueError):
        wilson_deff_upper_bound(7, 39, **kw)


def test_h3_wilson_clamps_deff_to_at_least_one() -> None:
    base = wilson_deff_upper_bound(7, 39, icc=0.4, m_bar=1.0, z=mod.Z_ONE_SIDED_90)
    assert wilson_deff_upper_bound(7, 39, icc=0.4, m_bar=0.5, z=mod.Z_ONE_SIDED_90) == base


def _with_pre_floor(
    *, pnl_missing: bool = False, counters_missing: bool = False, excluded: bool = False
) -> StageSnapshot:
    pre_days = [counters(d(i), posted=4) for i in (-3, -2, -1)]
    pre_pnl = [DayPnl(d(i), reading("0.01")) for i in (-3, -2, -1)]
    if counters_missing:
        pre_days = [x for x in pre_days if x.day != d(-2)]
    if pnl_missing:
        pre_pnl = [x for x in pre_pnl if x.day != d(-2)]
    base = build(
        8,
        epochs=(EpochRow("sha", 2, None, ns_of(d(-3), 10)),),
        excluded_days=excl(-2) if excluded else (),
    )
    return dataclasses.replace(
        base, days=base.days + tuple(pre_days), pnl_days=base.pnl_days + tuple(pre_pnl)
    )


def test_h4_pre_floor_days_with_entries_and_rows_pass() -> None:
    assert evaluate_stage(_with_pre_floor()).kind is VerdictKind.PROMOTION_ELIGIBLE


def test_h4_missing_pnl_row_before_the_floor_is_fail() -> None:
    v = evaluate_stage(_with_pre_floor(pnl_missing=True))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:missing_pnl_day"


def test_h4_missing_counters_before_the_floor_cannot_be_verified() -> None:
    v = evaluate_stage(_with_pre_floor(counters_missing=True))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:missing_day"


def test_h4_unreconciled_excluded_day_before_the_floor_is_skipped() -> None:
    snap = _with_pre_floor(pnl_missing=True, excluded=True)
    snap = dataclasses.replace(snap, gappy_days=frozenset({d(-2)}))  # still unreconciled
    assert evaluate_stage(snap).kind is VerdictKind.PROMOTION_ELIGIBLE


def test_h4_pre_floor_day_with_no_entries_needs_no_row() -> None:
    snap = _with_pre_floor()
    days = tuple(counters(x.day, posted=0) if x.day == d(-2) else x for x in snap.days)
    pnl = tuple(p for p in snap.pnl_days if p.day != d(-2))
    assert (
        evaluate_stage(dataclasses.replace(snap, days=days, pnl_days=pnl)).kind
        is not VerdictKind.FAIL
    )


def test_h5_unexpected_exception_is_a_named_fail_without_its_message() -> None:
    class Boom(UtcDays):
        def open_days_at(self, ts_ns: int) -> frozenset[str]:
            raise ValueError("secret pnl 1234.56")

    v = evaluate_stage(build(8, governed=Boom()))
    assert v.kind is VerdictKind.FAIL and not v.sets_flag
    assert v.reason == "stage_eval_fail:internal:ValueError"
    assert "1234" not in repr(v)


def test_h5_reconcile_stuck_keeps_its_exact_name() -> None:
    v = evaluate_stage(build(8, pass_status=PassStatus.RECONCILE_STUCK))
    assert v.reason == "reconcile_stuck"


def test_m6_excluded_day_with_unreadable_reading_is_skipped() -> None:
    snap = build(8, excluded_days=excl(3), gappy_days=frozenset({d(3)}))  # unreconciled
    pnl = tuple(DayPnl(p.day, None) if p.day == d(3) else p for p in snap.pnl_days)
    assert evaluate_stage(dataclasses.replace(snap, pnl_days=pnl)).kind is not VerdictKind.FAIL
    gone = tuple(p for p in snap.pnl_days if p.day != d(3))
    assert evaluate_stage(dataclasses.replace(snap, pnl_days=gone)).kind is not VerdictKind.FAIL


def test_m7_today_row_is_required_like_closed_days() -> None:
    # BG-1c writes a row per arm day with any entry (exec_par_settled_pnl.py:234-244), not
    # only once something settles, so an absent row for a day with entries is not zero.
    snap = build(8)
    gone = tuple(p for p in snap.pnl_days if p.day != d(9))
    v = evaluate_stage(dataclasses.replace(snap, pnl_days=gone))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:settled_pnl_missing"


def test_m8_pending_overdue_ambiguous_are_reported_and_never_halt() -> None:
    snap = build(8)
    busy = SettledPnlReading(
        D("0.01"), settled=1, ambiguous=1, pending=2, overdue=3, fee_unreconciled=0
    )
    pnl = tuple(DayPnl(p.day, busy) if p.day in (d(2), d(3)) else p for p in snap.pnl_days)
    v = evaluate_stage(dataclasses.replace(snap, pnl_days=pnl))
    assert v.kind is VerdictKind.PROMOTION_ELIGIBLE and v.report is not None
    assert (v.report.pnl_pending, v.report.pnl_overdue, v.report.pnl_ambiguous_unresolved) == (
        4,
        6,
        2,
    )


def test_m9_no_k_gt_1_epoch_makes_cumulative_start_today() -> None:
    old_loss = evaluate_stage(
        build(8, epochs=(EpochRow("a", 1, None, ns_of(d(0), 10)),), pnl_over={4: "-1.5"})
    )
    assert STOP_S15_CUMULATIVE not in old_loss.stops  # day 4 predates "first K>1" (= today)


def test_m10_s3_is_terminal_no_hold_and_no_cleanup_demotion() -> None:
    assert evaluate_stage(build(15, k=6, posted=0)).kind is VerdictKind.PASS
    assert evaluate_stage(build(30, k=6, posted=0)).kind is VerdictKind.PASS
    looks = (LookRecord(d(5), LookOutcome.NOT_TAKEN),)
    assert evaluate_stage(build(30, k=6, looks=looks)).kind is VerdictKind.PASS


def test_m10_stops_still_apply_at_s3() -> None:
    assert evaluate_stage(build(8, k=6, pnl_over={3: "-0.2"})).kind is VerdictKind.STOP


def test_m11_equal_target_k_is_broken_by_severity_suspend_first() -> None:
    snap = build(8, k=6, day_over=_share(4, 7), pnl_over={5: "-1.2"})
    v = evaluate_stage(snap)
    assert {STOP_S6_DROPPED_SHARE, STOP_S15_CUMULATIVE} <= set(v.stops)
    assert v.target_k == 1 and v.reason == STOP_S6_DROPPED_SHARE


def test_m11_restart_s1_beats_down_one_stage_on_equal_target() -> None:
    pnl = {3: "-0.2"} | {i: "-0.05" for i in (1, 2, 4, 5, 6, 7, 8)}
    v = evaluate_stage(build(8, k=4, pnl_over=pnl))
    assert {STOP_S15_DAY, STOP_S15_STAGE} <= set(v.stops)
    assert v.reason == STOP_S15_DAY and v.target_k == 2


def test_m12_slippage_is_rederived_from_px_and_decision_ask() -> None:
    bad = dataclasses.replace(fill(d(2), "c1", ask="0.9"), slippage="0.01")
    v = evaluate_stage(build(8, day_over=_one_day_fills(d(2), bad)))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:slippage_inconsistent"
    ok = dataclasses.replace(fill(d(2), "c1", ask="0.89"), slippage="0.01")
    assert evaluate_stage(build(8, day_over=_one_day_fills(d(2), ok))).kind is not VerdictKind.FAIL


def test_m12_derived_slippage_feeds_the_blockers() -> None:
    snap = _slip_snapshot(40, slip="0.0051")
    assert "slippage_mean" in evaluate_stage(snap).look_blockers


@pytest.mark.parametrize(
    "bad", ["2027-1-1", "20270105", "2027/01/05", "2027-W01-1", "", " 2027-01-05"]
)
def test_l13_day_labels_must_be_iso_yyyy_mm_dd(bad: str) -> None:
    for over in (
        {"today": bad},
        {"gappy_days": frozenset({bad})},
        {"pending_rebuild_days": frozenset({bad})},
        {"excluded_days": (ExcludedDay(bad, "x", 1),)},
        {"looks": (LookRecord(bad, LookOutcome.FAILED),)},
    ):
        v = evaluate_stage(build(8, **over))
        assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:bad_day", over


def test_l13_day_keys_of_counters_and_pnl_rows_are_validated() -> None:
    snap = build(8)
    v = evaluate_stage(dataclasses.replace(snap, days=snap.days + (counters("20270105"),)))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:bad_day"
    v = evaluate_stage(
        dataclasses.replace(snap, pnl_days=snap.pnl_days + (DayPnl("x", reading()),))
    )
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:bad_day"


def test_l14_passed_look_without_a_commit_is_flagged_in_the_report() -> None:
    v = evaluate_stage(build(9, looks=(LookRecord(d(8), LookOutcome.PASSED),)))
    assert v.kind is VerdictKind.PASS and v.report is not None
    assert v.report.promotion_pending_commit is True
    assert evaluate_stage(build(9)).report.promotion_pending_commit is False  # type: ignore[union-attr]


def test_l16_no_currency_value_appears_in_repr_for_any_of_several_amounts() -> None:
    secrets = ["-0.123456", "-0.7654321", "0.0000417"]
    pnl = {2 + i: s for i, s in enumerate(secrets)}
    v = evaluate_stage(build(8, pnl_over=pnl))
    text = repr(v)
    assert all(s.lstrip("-") not in text for s in secrets)


# -- pnl-row criterion: a fill or an AMBIGUOUS mark, not posted>0 (coordinator ruling) -----------


def _without_row(snap: StageSnapshot, day: str) -> StageSnapshot:
    return dataclasses.replace(snap, pnl_days=tuple(p for p in snap.pnl_days if p.day != day))


@pytest.mark.parametrize("index", [4, 9])  # a closed day and today
def test_all_unfilled_ioc_day_needs_no_pnl_row(index: int) -> None:
    snap = build(8, day_over={index: {"fills": (), "amb": 0}})
    v = evaluate_stage(_without_row(snap, d(index)))
    assert v.kind is not VerdictKind.FAIL


def test_all_unfilled_ioc_day_before_the_floor_needs_no_pnl_row() -> None:
    snap = _with_pre_floor()
    days = tuple(counters(x.day, posted=4, fills=()) if x.day == d(-2) else x for x in snap.days)
    snap = dataclasses.replace(snap, days=days)
    assert evaluate_stage(_without_row(snap, d(-2))).kind is VerdictKind.PROMOTION_ELIGIBLE


def test_one_fill_without_a_row_still_fails() -> None:
    one = (fill(d(4), "only"),)
    snap = build(8, day_over={4: {"posted": 1, "fills": one}})
    v = evaluate_stage(_without_row(snap, d(4)))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:settled_pnl_missing"


def test_one_fill_before_the_floor_without_a_row_fails_missing_pnl_day() -> None:
    snap = _with_pre_floor()
    days = tuple(
        counters(x.day, posted=1, fills=(fill(x.day, "only"),)) if x.day == d(-2) else x
        for x in snap.days
    )
    v = evaluate_stage(_without_row(dataclasses.replace(snap, days=days), d(-2)))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:missing_pnl_day"


def test_an_ambiguous_mark_without_fills_needs_a_row() -> None:
    snap = build(8, day_over={4: {"fills": (), "amb": 1}})
    v = evaluate_stage(_without_row(snap, d(4)))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:settled_pnl_missing"


# -- final fix round (confirm review READY 88) -----------------------------------------------------


def test_f1_m5_target_is_clamped_to_a_forced_effective_k() -> None:
    v = evaluate_stage(build(30, posted=0, k=4, eff=1))
    assert v.reason == HOLD_CLEANUP_DEMOTION and v.target_k == 1
    assert (
        v.report is not None and not v.report.programme_paused
    )  # S2 -> S1 demotion, not S1 -> K=1
    unforced = evaluate_stage(build(30, posted=0, k=4))
    assert unforced.target_k == 2


@pytest.mark.parametrize("unreconciled", [True, False])
def test_f2_pre_floor_excluded_day_is_exempt_only_while_unreconciled(unreconciled: bool) -> None:
    snap = _with_pre_floor(pnl_missing=True, excluded=True)
    if unreconciled:
        snap = dataclasses.replace(snap, gappy_days=frozenset({d(-2)}))
        assert evaluate_stage(snap).kind is VerdictKind.PROMOTION_ELIGIBLE
    else:
        v = evaluate_stage(snap)
        assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:missing_pnl_day"


@pytest.mark.parametrize("which", ["gappy_days", "pending_rebuild_days"])
def test_f2_stage_excluded_day_is_exempt_while_gappy_or_pending_rebuild(which: str) -> None:
    flagged: dict[str, Any] = {which: frozenset({d(3)})}
    snap = build(8, excluded_days=excl(3), **flagged)
    assert evaluate_stage(_without_row(snap, d(3))).kind is not VerdictKind.FAIL


def test_f2_reconciled_stage_excluded_day_with_fills_and_no_row_fails() -> None:
    snap = build(8, excluded_days=excl(3))
    v = evaluate_stage(_without_row(snap, d(3)))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:missing_pnl_day"


def test_f2_reconciled_excluded_day_with_no_fills_or_ambiguous_needs_no_row() -> None:
    snap = build(8, excluded_days=excl(3), day_over={3: {"fills": ()}})
    assert evaluate_stage(_without_row(snap, d(3))).kind is not VerdictKind.FAIL


@pytest.mark.parametrize(
    "baseline",
    [
        SerialBaseline(25, D("NaN")),
        SerialBaseline(25, D("Infinity")),
        SerialBaseline(25, 0.1),  # type: ignore[arg-type]
        SerialBaseline(-1, D("0")),
        SerialBaseline(-1, None),
        SerialBaseline(2.5, D("0")),  # type: ignore[arg-type]
        SerialBaseline(True, D("0")),
    ],
)
def test_f3_invalid_serial_baseline_is_fail(baseline: SerialBaseline) -> None:
    v = evaluate_stage(build(8, serial_baseline=baseline))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:parity_baseline"


def test_f3_valid_serial_baselines_pass_validation() -> None:
    for ok in (SerialBaseline(0, None), SerialBaseline(19, None), SerialBaseline(25, D("0.001"))):
        assert evaluate_stage(build(8, serial_baseline=ok)).kind is not VerdictKind.FAIL


@pytest.mark.parametrize("k", [float("nan"), float("inf")])
def test_f4_wilson_rejects_non_finite_k(k: float) -> None:
    with pytest.raises(ValueError):
        wilson_deff_upper_bound(k, 39, icc=0.1, m_bar=3.0, z=1.28)  # type: ignore[arg-type]


@pytest.mark.parametrize("n", [float("nan"), float("inf")])
def test_f4_wilson_rejects_non_finite_n(n: float) -> None:
    with pytest.raises(ValueError):
        wilson_deff_upper_bound(7, n, icc=0.1, m_bar=3.0, z=1.28)  # type: ignore[arg-type]


def test_f5_negative_window_notional_is_fail() -> None:
    windows = _burst(d(8), ["-10", "60", "60", "10", "10", "10"])  # sums positive, 6 orders
    v = evaluate_stage(build(8, day_over={8: {"windows": windows}}))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:window_notional"


def test_f6_first_k_day_after_today_is_fail() -> None:
    epochs = (EpochRow("sha", 2, None, ns_of(d(12), 10)),)
    v = evaluate_stage(build(8, epochs=epochs))
    assert v.kind is VerdictKind.FAIL and v.reason == "stage_eval_fail:epoch_after_today"
    same_day = (EpochRow("sha", 2, None, ns_of(d(9), 10)),)
    assert evaluate_stage(build(8, epochs=same_day)).kind is not VerdictKind.FAIL
