"""EXEC-PAR BG-5a: the PURE stage evaluator (D-PREREG r4 + r4.1..r4.5; inert, unwired).

One function, :func:`evaluate_stage`, over one immutable :class:`StageSnapshot`
built by the (later, BG-5b) loop-thread wiring from the BG-1 ports. No I/O, no
clock read (``today`` and the day function are injected), no logging, no
Nautilus and no ``breezy.adapters`` import. Currency values are summed only
inside the call, handed to the injected :class:`PnlPredicatePort` (K6:
aggregate in, ``bool`` out) and never placed in the verdict or the report.

Verdict kinds: PASS; STOP (a stop-class reason plus the "After a halt"
outcome, N5); PROMOTION_ELIGIBLE (the look is due; the evaluator NEVER
promotes, r4.5 O5, and computes no ICC-based pass: ICC is an argument of the
:func:`wilson_deff_upper_bound` helper, estimated by BG-10(f)); HOLD (L3, the
look not taken, or the M5 cleanup demotion); FAIL (an integrity failure,
which dominates every STOP and carries the halt reason). Unexpected
exceptions are not caught here: the wiring maps them to
``stage_eval_fail:<kind>``.

Day model (BG-5c R1, A4, A5). A "climate day" is the ISO label of an entry's ARM time under its
OWN station's standard time (``snap.governed.entry_day``); stations roll over at different
instants, so ``today`` is the EARLIEST still-open label and a label after it is OPEN data.

* *Floor (A4).* Each station's floor day is ``entry_day(station, floor.ts)``; ``floor_days =
  open_days_at(floor.ts)``. A floor label's stage counters are its post-floor STUB (only entries
  armed at or after ``floor.ts``), supplied in ``snap.floor_stubs``; the stub is a stage day and
  obeys the same rules, so a pre-floor loss can never re-trip a stop. A stub that cannot split
  pre- from post-floor entries FAILs (``pre_floor_unknown``); a floor label with no stub is an
  empty stub only when its whole-day counters are empty. Every other label uses whole-day
  counters. The floor labels' settled-P&L rows are WHOLE-day (they carry pre-floor entries): s15-day
  and s15-stage read the post-floor STUB row (``snap.floor_stub_pnl``, required whenever the stub
  has fills or AMBIGUOUS marks; WP-D writes it) and s15-cumulative, never floored, the whole-day
  row.
* *Closed* days are ``floor_day <= d < today``. *Open* days are ``today`` and any later label that
  carries data (A5), up to ``MAX_OPEN_DAYS_AHEAD`` ahead; an entry further ahead is
  ``counter_missing``. Open days join the closed days for the halt rules that act on the first
  pass after data lands (s7 fees, s15-day, s15-stage, s15-cumulative); the look minima, the
  trailing windows (s6, s9), the cap and the daily trigger use closed days only.
* Excluded days are skipped by every window, so a trailing window of 5 reaches further back past
  them; they count toward the 15-day cap and, for s15-cumulative, their settled P&L still counts.

Stop reasons for the intraday rules (s5 Clopper-Pearson, burst, s9 station-day
0.25) are exported as constants only: BG-6 evaluates those.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass, replace
from decimal import Decimal
from itertools import pairwise

from breezy.runtime.exec_par_reconcile import PassStatus
from breezy.runtime.exec_par_records import ExcludedDay
from breezy.runtime.exec_par_settled_pnl import SettledPnlReading
from breezy.runtime.exec_par_stage_fees import (
    ParsedFill,
    fee_findings,
    fee_stage_tolerance,
    parse_fills,
)
from breezy.runtime.exec_par_stage_rules import (
    SEVERITY,
    s6_share,
    s9_flags,
    s15_findings,
    target_k,
)
from breezy.runtime.exec_par_stage_stats import (
    wilson_deff_upper_bound,
)
from breezy.runtime.exec_par_stage_types import (
    BUDGET_NOTE,
    CLEANUP_HOLD_DAYS,
    DEMOTE_K,
    EXTENSION_DAYS,
    FAILED_LOOKS_FOR_DEMOTION,
    FEE_UNRECONCILED_LIMIT,
    HOLD_CAP_MINIMA_UNMET,
    HOLD_CLEANUP_DEMOTION,
    HOLD_LOOK_NOT_TAKEN,
    HOLD_LOOK_WINDOW_CLOSED,
    MAX_EXCLUDED_DAYS,
    MAX_OPEN_DAYS_AHEAD,
    MIN_FILL_DAYS,
    MIN_NONEXCLUDED_DAYS,
    MIN_POSTED_ORDERS,
    PARITY_LIMIT,
    PARITY_MIN_SERIAL_FILLS,
    S3_K,
    S5_REASONS,
    S9_MIN_FLAG_DAYS,
    SLIPPAGE_MEAN_LIMIT,
    SLIPPAGE_TAIL_PRICE,
    STAGE_CAP_DAYS,
    STAGE_OF_K,
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
    TAIL_SHARE_LIMIT,
    Z_ONE_SIDED_90,
    Z_ONE_SIDED_95,
    DayCounters,
    DayPnl,
    DayStat,
    LookOutcome,
    LookRecord,
    PnlPredicatePort,
    SerialBaseline,
    StageContext,
    StageFail,
    StageReport,
    StageSnapshot,
    StopOutcome,
    Verdict,
    VerdictKind,
    check_count,
    fail,
    parse_day,
)

__all__ = [
    "CLEANUP_HOLD_DAYS",
    "HOLD_CAP_MINIMA_UNMET",
    "HOLD_CLEANUP_DEMOTION",
    "HOLD_LOOK_NOT_TAKEN",
    "HOLD_LOOK_WINDOW_CLOSED",
    "STAGE_CAP_DAYS",
    "STOP_CLASS_REASONS",
    "STOP_DEMOTION_EXCLUDED_DAYS",
    "STOP_DEMOTION_SECOND_FAILED_LOOK",
    "STOP_OUTCOMES",
    "STOP_S5_BURST",
    "STOP_S5_CLOPPER_PEARSON",
    "STOP_S6_DROPPED_SHARE",
    "STOP_S7_COEFFICIENT",
    "STOP_S7_PER_ORDER",
    "STOP_S7_PER_STAGE",
    "STOP_S9_STATION_DAY_2_OF_5",
    "STOP_S9_STATION_DAY_INTRADAY",
    "STOP_S9_WINDOW_5S",
    "STOP_S15_CUMULATIVE",
    "STOP_S15_DAY",
    "STOP_S15_STAGE",
    "Z_ONE_SIDED_90",
    "Z_ONE_SIDED_95",
    "DayCounters",
    "DayPnl",
    "DayStat",
    "LookOutcome",
    "LookRecord",
    "PnlPredicatePort",
    "SerialBaseline",
    "StageReport",
    "StageSnapshot",
    "StopOutcome",
    "Verdict",
    "VerdictKind",
    "evaluate_stage",
    "fee_stage_tolerance",
    "wilson_deff_upper_bound",
]


def _validate_k(snap: StageSnapshot) -> None:
    k, eff = snap.configured_k, snap.effective_k
    ints = all(isinstance(v, int) and not isinstance(v, bool) for v in (k, eff))
    if not ints or k not in STAGE_OF_K or not 1 <= eff <= k:
        raise fail("invalid_k")


def _open_days_at(snap: StageSnapshot, ts_ns: int) -> frozenset[str]:
    """Instant-only lookup (boot, floor): every governed station's open day at ``ts_ns``.

    An exception from the injected convention is not caught here: ``evaluate_stage`` maps it to
    the named last-resort ``stage_eval_fail:internal:<type>`` (no message)."""
    days = snap.governed.open_days_at(ts_ns)
    if not days:
        raise fail("bad_day")
    return days


def _first_k_gt1_day(snap: StageSnapshot) -> str:
    if any(later.boot_ts <= earlier.boot_ts for earlier, later in pairwise(snap.epochs)):
        raise fail("non_monotonic")
    for epoch in snap.epochs:
        if epoch.effective_k > 1:
            return min(_open_days_at(snap, epoch.boot_ts))
    return snap.today  # forced to K=1 from its first boot: legitimately serial, cumulative empty


def _span(after: dt.date, before: dt.date) -> tuple[str, ...]:
    """ISO days strictly between ``after`` and ``before``."""
    count = (before - after).days - 1
    return tuple((after + dt.timedelta(days=i)).isoformat() for i in range(1, count + 1))


def _is_empty(row: DayCounters) -> bool:
    """No activity at all: no entry, AMBIGUOUS mark, fill, denial, open-cost flag or window (a
    ``None`` entry count is NOT empty: it is unknown)."""
    return (
        row.posted == 0
        and row.ambiguous == 0
        and not row.fills
        and not row.denied_counted
        and not row.open_flags
        and not row.windows
    )


def _stage_view(
    floor_days: frozenset[str],
    whole: Mapping[str, DayCounters],
    stubs: Mapping[str, DayCounters],
) -> dict[str, DayCounters]:
    """Whole-day counters, with each floor label replaced by its post-floor stub (A4)."""
    view = dict(whole)
    for label in floor_days:
        stub = stubs.get(label)
        row = whole.get(label)
        if stub is not None:
            view[label] = stub
        elif row is not None:
            # No stub: whole-day counters are trustworthy as post-floor only if empty.
            view[label] = row if _is_empty(row) else replace(row, pre_floor_unknown=True)
    return view


def _counter_missing_ahead(rows: tuple[DayCounters, ...], today: dt.date) -> None:
    """A5: an entry further than ``MAX_OPEN_DAYS_AHEAD`` days after ``today`` has no counter row
    in any window the evaluator reads, so it is ``counter_missing``."""
    limit = today + dt.timedelta(days=MAX_OPEN_DAYS_AHEAD)
    for row in rows:
        if parse_day(row.day) > limit and not _is_empty(row):
            raise fail("counter_missing")


def _build_ctx(snap: StageSnapshot) -> StageContext:
    if snap.floor is None:
        raise fail("floor_missing")
    today = parse_day(snap.today)
    floor_days = _open_days_at(snap, snap.floor.ts)
    for label in floor_days:
        parse_day(label)
    floor_day, floor_last = min(floor_days), max(floor_days)
    floor_date = parse_day(floor_day)
    if today < floor_date:
        raise fail("non_monotonic")
    first_k_day = _first_k_gt1_day(snap)
    parse_day(first_k_day)
    if first_k_day > snap.today:
        raise fail("epoch_after_today")
    excluded = {x.day for x in snap.excluded_days}
    for label in (*excluded, *snap.gappy_days, *snap.pending_rebuild_days):
        parse_day(label)
    for look in snap.looks:
        parse_day(look.day)
    _counter_missing_ahead(snap.days, today)
    ahead_limit = today + dt.timedelta(days=MAX_OPEN_DAYS_AHEAD)
    open_days = (
        snap.today,
        *sorted(x.day for x in snap.days if today < parse_day(x.day) <= ahead_limit),
    )
    stage_excluded = {
        x.day
        for x in snap.excluded_days
        if x.day <= max(open_days) and _excluded_in_stage(x, snap, floor_day, floor_last)
    }
    closed = _span(floor_date - dt.timedelta(days=1), today)
    eligible = tuple(x for x in closed if x not in stage_excluded)
    live = (*eligible, *(x for x in open_days if x not in stage_excluded))
    whole: dict[str, DayCounters] = {}
    for row in snap.days:
        parse_day(row.day)
        if row.day in whole:
            raise fail("duplicate_day")
        whole[row.day] = row
    stubs: dict[str, DayCounters] = {}
    for row in snap.floor_stubs:
        parse_day(row.day)
        if row.day in stubs:
            raise fail("duplicate_day")
        stubs[row.day] = row
    pnl: dict[str, SettledPnlReading | None] = {}
    for entry in snap.pnl_days:
        parse_day(entry.day)
        if entry.day in pnl:
            raise fail("duplicate_day")
        pnl[entry.day] = entry.reading
    stub_pnl: dict[str, SettledPnlReading | None] = {}
    for entry in snap.floor_stub_pnl:
        parse_day(entry.day)
        if entry.day in stub_pnl:
            raise fail("duplicate_day")
        stub_pnl[entry.day] = entry.reading
    return StageContext(
        snap,
        snap.floor,
        floor_day,
        floor_last,
        floor_days,
        snap.today,
        max(open_days),
        closed,
        eligible,
        live,
        open_days,
        tuple(sorted(stage_excluded)),
        _stage_view(floor_days, whole, stubs),
        whole,
        pnl,
        stub_pnl,
        first_k_day,
        snap.configured_k,
    )


def _excluded_in_stage(
    row: ExcludedDay, snap: StageSnapshot, floor_day: str, floor_last: str
) -> bool:
    """An exclusion belongs to this stage when its label is a stage label and, on a floor label,
    it was recorded at or after the floor (an older one belonged to the previous stage)."""
    if row.day < floor_day:
        return False
    if row.day > floor_last:
        return True
    return snap.floor is not None and row.ts >= snap.floor.ts


def _fill_attribution_ok(ctx: StageContext, label: str, row: DayCounters) -> bool:
    """Each fill row sits on ``entry_day(its station, its arm time)``, and a floor stub holds no
    pre-floor entry (A4): a leak either way is a bad counter."""
    gov = ctx.snap.governed
    for fill_row in row.fills or ():
        try:
            if gov.entry_day(fill_row.station, fill_row.arm_ns) != label:
                return False
        except Exception:  # noqa: BLE001 - an unmappable row is a bad counter
            return False
        if label in ctx.floor_days and fill_row.arm_ns < ctx.floor.ts:
            return False
    return True


def _validate_counters(ctx: StageContext) -> None:
    for label in ctx.live:
        row = ctx.by_day.get(label)
        if row is None:
            raise fail("missing_day")
        if row.pre_floor_unknown:
            raise fail("pre_floor_unknown")
        if (
            row.posted is None
            or row.ambiguous is None
            or row.fills is None
            or row.open_flags is None
            or row.windows is None
        ):
            raise fail("missing_counter")
        if check_count(row.posted) < check_count(row.ambiguous):
            raise fail("bad_counter")
        if row.denied_counted is not None:
            check_count(row.denied_counted)
        if any(r.day != label for rows in (row.fills, row.open_flags, row.windows) for r in rows):
            raise fail("bad_counter")
        if not _fill_attribution_ok(ctx, label, row):
            raise fail("bad_counter")
        for window in row.windows:
            check_count(window.orders)
        if label in ctx.snap.gappy_days:
            raise fail("gappy")
        if label in ctx.snap.pending_rebuild_days:
            raise fail("pending_rebuild")


def _validate_reading(reading: SettledPnlReading) -> None:
    if not isinstance(reading.pnl, Decimal) or not reading.pnl.is_finite():
        raise fail("pnl_nonfinite")
    counts = (
        reading.settled,
        reading.ambiguous,
        reading.pending,
        reading.overdue,
        reading.fee_unreconciled,
    )
    for value in counts:
        check_count(value)


def _needs_pnl_row(row: DayCounters) -> bool:
    """A settled-P&L row exists exactly when the day has an entry fill or an AMBIGUOUS mark.

    That is what BG-1c writes (``exec_par_settled_pnl.py:181-191``, ``_check_fill``): an
    all-unfilled IOC day (posted but no fill and no AMBIGUOUS mark) has no row and needs none.
    """
    return bool(row.fills) or bool(row.ambiguous)


def _validate_cumulative_rows(ctx: StageContext, unreconciled: frozenset[str]) -> None:
    """s15-cumulative is never floored: every day since the first K>1 boot needs its row.

    Covers the pre-floor days, the floor labels (judged on their WHOLE-day counters: the row
    carries pre-floor entries too) and the excluded stage days (the other live stage days are
    checked by the caller). An excluded day is exempt only while it is not yet reconciled (10a):
    once its counters reconcile it counts, so a fill or AMBIGUOUS mark with no row is a FAIL.
    """
    first = parse_day(ctx.first_k_day)
    labels = [
        (first + dt.timedelta(days=offset)).isoformat()
        for offset in range((parse_day(ctx.floor_last) - first).days + 1)
    ]
    excluded = {x.day for x in ctx.snap.excluded_days}
    for label in (*labels, *ctx.excluded_in_stage):
        if label in excluded and label in unreconciled:
            continue
        row = ctx.whole_day.get(label)
        if row is None:
            raise fail("missing_day")
        if row.fills is None or row.ambiguous is None:
            raise fail("missing_counter")
        if _needs_pnl_row(row) and ctx.pnl.get(label) is None:
            raise fail("missing_pnl_day")


def _validate_pnl(ctx: StageContext) -> None:
    unreconciled = ctx.snap.gappy_days | ctx.snap.pending_rebuild_days
    for reading in (*ctx.pnl.values(), *ctx.stub_pnl.values()):
        if reading is not None:
            _validate_reading(reading)
    # BG-1c writes a row per arm day with entries (exec_par_settled_pnl.py:234-244), settled
    # or not, so today needs its row like every closed day.
    for label in ctx.live:
        if label in ctx.floor_days:
            # A floor stub with post-floor fills or AMBIGUOUS marks needs its own settled-P&L
            # row (WP-D writes it, plan r2.2); never lean on s15-cumulative alone. The whole-day
            # row is judged by the cumulative check below.
            if _needs_pnl_row(ctx.by_day[label]) and ctx.stub_pnl.get(label) is None:
                raise fail("settled_pnl_missing")
            continue
        if _needs_pnl_row(ctx.by_day[label]) and ctx.pnl.get(label) is None:
            raise fail("settled_pnl_missing")
    _validate_cumulative_rows(ctx, unreconciled)
    excluded = {x.day for x in ctx.snap.excluded_days}
    for label, reading in ctx.pnl.items():
        if (
            reading is None
            and label >= ctx.first_k_day
            and not (label in excluded and label in unreconciled)
        ):
            raise fail("settled_pnl_missing")


def _stage_looks(ctx: StageContext) -> list[LookRecord]:
    # A look on a floor label may predate the reset: only labels after every floor label count.
    return sorted((x for x in ctx.snap.looks if x.day > ctx.floor_last), key=lambda x: x.day)


@dataclass(frozen=True, slots=True)
class _Stats:
    """Stage totals over the closed, non-excluded days (the look inputs)."""

    posted: int
    ambiguous: int
    n_days: int
    filled_orders: int
    fill_count: int
    fill_days: int
    slip_mean: Decimal | None
    slip_tail: Decimal | None
    unreconciled: Decimal | None


def _stage_stats(ctx: StageContext, fills: list[ParsedFill]) -> _Stats:
    slips = [f.slip for f in fills]
    orders = {f.order for f in fills}
    unrec = sum(r.fee_unreconciled for x in ctx.eligible if (r := ctx.pnl.get(x)) is not None)
    return _Stats(
        posted=sum(ctx.by_day[x].posted or 0 for x in ctx.eligible),
        ambiguous=sum(ctx.by_day[x].ambiguous or 0 for x in ctx.eligible),
        n_days=len(ctx.eligible),
        filled_orders=len(orders),
        fill_count=len(fills),
        fill_days=sum(1 for x in ctx.eligible if ctx.by_day[x].fills),
        slip_mean=sum(slips, Decimal(0)) / len(slips) if slips else None,
        slip_tail=(
            Decimal(sum(1 for s in slips if s > SLIPPAGE_TAIL_PRICE)) / len(slips)
            if slips
            else None
        ),
        unreconciled=Decimal(unrec) / len(orders) if orders else None,
    )


def _parity(base: SerialBaseline | None, mean: Decimal | None) -> Decimal | None:
    if base is None:
        return None
    fills, slip = base.fills, base.mean_slippage
    if isinstance(fills, bool) or not isinstance(fills, int) or fills < 0:
        raise fail("parity_baseline")
    if slip is not None and not (isinstance(slip, Decimal) and slip.is_finite()):
        raise fail("parity_baseline")
    if base.mean_slippage is None:
        if base.fills >= PARITY_MIN_SERIAL_FILLS:
            raise fail("parity_baseline")
        return None
    return None if mean is None else mean - base.mean_slippage


def _blockers(ctx: StageContext, stats: _Stats, parity: Decimal | None) -> tuple[str, ...]:
    """Deterministic look failures (s7 promotion conditions, s5 halt, fill days)."""
    out: list[str] = []
    # N1: a marker older than the floor was consumed by that stage_reset; only ts >= floor counts.
    if any(v.reason in S5_REASONS and v.ts_ns >= ctx.floor.ts for v in ctx.snap.stop_verdicts):
        out.append("s5_halt_in_stage")
    if stats.fill_days < MIN_FILL_DAYS:
        out.append("fill_days_below_5")
    if stats.slip_mean is None:
        out.append("no_fills")
    elif stats.slip_mean > SLIPPAGE_MEAN_LIMIT:
        out.append("slippage_mean")
    if stats.slip_tail is not None and stats.slip_tail > TAIL_SHARE_LIMIT:
        out.append("slippage_tail")
    if stats.unreconciled is not None and stats.unreconciled > FEE_UNRECONCILED_LIMIT:
        out.append("fee_unreconciled")
    base = ctx.snap.serial_baseline
    if (
        base is not None
        and base.fills >= PARITY_MIN_SERIAL_FILLS
        and parity is not None
        and parity > PARITY_LIMIT
    ):
        out.append("parity")
    return tuple(out)


@dataclass(frozen=True, slots=True)
class _Checks:
    """Everything the rules computed, for the report."""

    stats: _Stats
    share: Decimal | None
    station_days: tuple[str, ...]
    burst_days: tuple[str, ...]
    per_fill_mismatches: int
    parity: Decimal | None
    blockers: tuple[str, ...]
    minima_met: bool
    #: (pending, overdue, AMBIGUOUS-unresolved) entry counts over the stage's settled-P&L rows.
    pnl_counts: tuple[int, int, int]
    pending_commit: bool


def _report(ctx: StageContext, c: _Checks, **extra: object) -> StageReport:
    s = c.stats
    fields: dict[str, object] = {
        "stage": STAGE_OF_K[ctx.stage_k],
        "configured_k": ctx.stage_k,
        "effective_k": ctx.snap.effective_k,
        "floor_day": ctx.floor_day,
        "today": ctx.today,
        "closed_days": len(ctx.closed),
        "nonexcluded_days": s.n_days,
        "excluded_days": ctx.excluded_in_stage,
        "posted": s.posted,
        "ambiguous": s.ambiguous,
        "ambiguous_rate": Decimal(s.ambiguous) / Decimal(s.posted) if s.posted else None,
        "fills": s.fill_count,
        "filled_orders": s.filled_orders,
        "days_with_fill": s.fill_days,
        "m_bar": Decimal(s.posted) / Decimal(s.n_days) if s.n_days else None,
        "day_stats": tuple(
            DayStat(
                x,
                ctx.by_day[x].posted or 0,
                ctx.by_day[x].ambiguous or 0,
                len(ctx.by_day[x].fills or ()),
            )
            for x in ctx.eligible
        ),
        "minima_met": c.minima_met,
        "dropped_share": c.share,
        "station_day_flag_days": c.station_days,
        "window_flag_days": c.burst_days,
        "slippage_mean": s.slip_mean,
        "slippage_tail_share": s.slip_tail,
        "parity_diff": c.parity,
        "fee_unreconciled_share": s.unreconciled,
        "per_fill_fee_mismatches": c.per_fill_mismatches,
        "section5_halt_in_stage": "s5_halt_in_stage" in c.blockers,
        "held_days": 0,
        "promotion_blocked_reason": None,
        "promotion_pending_commit": c.pending_commit,
        "pnl_pending": c.pnl_counts[0],
        "pnl_overdue": c.pnl_counts[1],
        "pnl_ambiguous_unresolved": c.pnl_counts[2],
        "programme_paused": False,
        "notes": (BUDGET_NOTE,),
    }
    fields.update(extra)
    return StageReport(**fields)  # type: ignore[arg-type]


def _stop_findings(
    ctx: StageContext,
    looks: list[LookRecord],
    s6_tripped: bool,
    c: _Checks,
    fee: list[str],
    pnl: list[str],
) -> list[str]:
    found: list[str] = []
    if len(ctx.excluded_in_stage) > MAX_EXCLUDED_DAYS:
        found.append(STOP_DEMOTION_EXCLUDED_DAYS)
    if sum(1 for x in looks if x.outcome is LookOutcome.FAILED) >= FAILED_LOOKS_FOR_DEMOTION:
        found.append(STOP_DEMOTION_SECOND_FAILED_LOOK)
    if ctx.stage_k == S3_K and s6_tripped:
        found.append(STOP_S6_DROPPED_SHARE)
    found += fee
    if len(c.station_days) >= S9_MIN_FLAG_DAYS:
        found.append(STOP_S9_STATION_DAY_2_OF_5)
    if len(c.burst_days) >= S9_MIN_FLAG_DAYS:
        found.append(STOP_S9_WINDOW_5S)
    return found + pnl


def _evaluate(snap: StageSnapshot) -> Verdict:
    _validate_k(snap)
    if snap.configured_k == 1:
        return Verdict(VerdictKind.PASS)  # S0: no K>1 stage to evaluate
    if snap.pass_status is not PassStatus.OK:
        raise StageFail("reconcile_stuck")
    ctx = _build_ctx(snap)
    _validate_counters(ctx)
    if snap.unattributed_ambiguous is None or snap.unattributed_ambiguous != 0:
        raise fail("unattributed_ambiguous")
    _validate_pnl(ctx)

    fee_stops, per_fill = fee_findings(parse_fills(ctx, ctx.live))
    share, s6_tripped = s6_share(ctx)
    station_days, burst_days = s9_flags(ctx)
    pnl_stops = s15_findings(ctx)
    stats = _stage_stats(ctx, parse_fills(ctx, ctx.eligible))
    parity = _parity(snap.serial_baseline, stats.slip_mean)
    looks = _stage_looks(ctx)
    readings = [r for x in ctx.eligible if (r := ctx.pnl.get(x)) is not None]
    capped = [x for x in ctx.closed[:STAGE_CAP_DAYS] if x in set(ctx.eligible)]
    checks = _Checks(
        stats,
        share,
        station_days,
        burst_days,
        per_fill,
        parity,
        _blockers(ctx, stats, parity),
        sum(ctx.by_day[x].posted or 0 for x in capped) >= MIN_POSTED_ORDERS
        and len(capped) >= MIN_NONEXCLUDED_DAYS,
        (
            sum(r.pending for r in readings),
            sum(r.overdue for r in readings),
            sum(r.ambiguous for r in readings),
        ),
        any(x.outcome is LookOutcome.PASSED for x in looks),
    )
    findings = _stop_findings(ctx, looks, s6_tripped, checks, fee_stops, pnl_stops)
    if findings:
        eff = snap.effective_k

        def rank(reason: str) -> tuple[int, int]:
            kind = STOP_OUTCOMES[reason]
            return target_k(kind, ctx.stage_k, eff), SEVERITY[kind]

        # Lowest resulting K first, then severity; ties keep evaluation order (min is stable).
        primary = min(findings, key=rank)
        outcome = STOP_OUTCOMES[primary]
        return Verdict(
            VerdictKind.STOP,
            primary,
            outcome,
            target_k(outcome, ctx.stage_k, eff),
            tuple(findings),
            True,
            report=_report(ctx, checks),
        )
    return _base_verdict(ctx, looks, checks)


def _look_state(
    ctx: StageContext, looks: list[LookRecord], minima_met: bool
) -> tuple[str | None, int | None]:
    """(hold reason, look number due) once no stop fired. At most one is set."""
    if ctx.stage_k == S3_K:
        return None, None  # S3 is terminal: no look, so neither L3 nor M5 applies
    n_closed = len(ctx.closed)
    if any(x.outcome is LookOutcome.NOT_TAKEN for x in looks):
        return HOLD_LOOK_NOT_TAKEN, None
    if any(x.outcome is LookOutcome.PASSED for x in looks):
        return None, None  # the lower/higher-K commit is the caller's; nothing more to look at
    if not minima_met:
        return (HOLD_CAP_MINIMA_UNMET if n_closed >= STAGE_CAP_DAYS else None), None
    failed = [x for x in looks if x.outcome is LookOutcome.FAILED]
    if failed:
        since = sum(1 for x in ctx.eligible if x > failed[-1].day)
        if since < EXTENSION_DAYS and n_closed < STAGE_CAP_DAYS:
            return None, None  # the 5-day extension is still running
    if n_closed > STAGE_CAP_DAYS:
        return HOLD_LOOK_WINDOW_CLOSED, None
    return None, 1 + len(failed)


def _base_verdict(ctx: StageContext, looks: list[LookRecord], c: _Checks) -> Verdict:
    """No stop fired: hold (L3/M5), look due, or pass."""
    held, look_number = _look_state(ctx, looks, c.minima_met)
    nonexcluded = len(ctx.eligible)
    if held is not None and nonexcluded >= CLEANUP_HOLD_DAYS:
        to_k = target_k(StopOutcome.DOWN_ONE_STAGE, ctx.stage_k, ctx.snap.effective_k)
        return Verdict(
            VerdictKind.HOLD,
            HOLD_CLEANUP_DEMOTION,
            StopOutcome.DOWN_ONE_STAGE,
            to_k,
            report=_report(
                ctx, c, held_days=nonexcluded, programme_paused=DEMOTE_K[ctx.stage_k] == 1
            ),
        )
    if held is not None:
        return Verdict(VerdictKind.HOLD, held, report=_report(ctx, c, held_days=nonexcluded))
    if look_number is None:
        return Verdict(VerdictKind.PASS, report=_report(ctx, c))
    if ctx.snap.effective_k != ctx.stage_k:
        return Verdict(
            VerdictKind.PASS, report=_report(ctx, c, promotion_blocked_reason="k_forced")
        )
    return Verdict(
        VerdictKind.PROMOTION_ELIGIBLE,
        look_number=look_number,
        look_blockers=c.blockers,
        report=_report(ctx, c),
    )


def evaluate_stage(snapshot: StageSnapshot) -> Verdict:
    """Evaluate one snapshot. Pure: same snapshot, same verdict; nothing is written."""
    try:
        return _evaluate(snapshot)
    except StageFail as failure:
        return Verdict(VerdictKind.FAIL, reason=failure.reason)
    except Exception as exc:  # noqa: BLE001 - last resort; never echo the message (could carry money)
        return Verdict(VerdictKind.FAIL, reason=f"stage_eval_fail:internal:{type(exc).__name__}")
