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

Day model. A "climate day" is the ISO label the BG-1 counters use (arm time,
I2). ``floor_day = day_of_ns(floor.ts)``; the stage covers the days strictly
after it (a day cannot be split, and a stop computed on pre-floor data must
not re-trip). *Closed* days are ``floor_day < d < today``; the open ``today``
joins the closed days only for the P&L stops and the fee checks (s7, s15),
which act on the first pass after the data lands. Promotion looks, the cap, the
minima, s6 and s9 use closed days. Excluded days are skipped by every window,
so a trailing window of 5 reaches further back past them; they count toward
the 15-day cap and, for s15-cumulative, their settled P&L still counts.

Stop reasons for the intraday rules (s5 Clopper-Pearson, burst, s9 station-day
0.25) are exported as constants only: BG-6 evaluates those.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from enum import Enum
from itertools import pairwise
from math import isfinite, sqrt
from types import MappingProxyType
from typing import Final, Protocol

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

# -- thresholds (spec citations in the names' comments) -----------------------

#: s1 ladder: configured K -> stage label, and the demotion target.
_STAGE_OF_K: Final[Mapping[int, str]] = MappingProxyType({1: "S0", 2: "S1", 4: "S2", 6: "S3"})
_DEMOTE_K: Final[Mapping[int, int]] = MappingProxyType({2: 1, 4: 2, 6: 4})
_RESTART_S1_K: Final[int] = 2
_S3_K: Final[int] = 6

STAGE_CAP_DAYS: Final[int] = 15  # s1 item 5
_EXTENSION_DAYS: Final[int] = 5  # s1 item 2
_FAILED_LOOKS_FOR_DEMOTION: Final[int] = 2  # s1 item 4
_MIN_POSTED_ORDERS: Final[int] = 30  # K10 look minimum
_MIN_NONEXCLUDED_DAYS: Final[int] = 8  # K10 look minimum
_MIN_FILL_DAYS: Final[int] = 5  # s1 table: climate days with >=1 entry fill
CLEANUP_HOLD_DAYS: Final[int] = 30  # M5
_MAX_EXCLUDED_DAYS: Final[int] = 2  # 10a cap
_TRAILING_DAYS: Final[int] = 5  # s6, s9 windows

_S6_SHARE_LIMIT: Final[Decimal] = Decimal("0.30")
_S9_MIN_FLAG_DAYS: Final[int] = 2
_S9_MIN_ORDERS: Final[int] = 6
_S9_SHARE_LIMIT: Final[Decimal] = Decimal("0.50")
_S9_ZERO: Final[Decimal] = Decimal(0)

_DAY_FRACTION: Final[Decimal] = Decimal("0.15")  # s15
_STAGE_FRACTION: Final[Decimal] = Decimal("0.40")
_CUMULATIVE_FRACTION: Final[Decimal] = Decimal("1.0")

#: s7 theta (PREREG theta; adapters/polymarket_us/fees.py post-drift coefficient). Not importable
#: here (no adapters import); a stored fill's ``fee_theta`` must equal it exactly.
_FEE_THETA: Final[Decimal] = Decimal("0.0695")
_CENT: Final[Decimal] = Decimal("0.01")
_FEE_STAGE_FLOOR: Final[Decimal] = Decimal("0.02")
_FEE_STAGE_PER_ORDER: Final[Decimal] = Decimal("0.005")
_SLIPPAGE_MEAN_LIMIT: Final[Decimal] = Decimal("0.005")
_SLIPPAGE_TAIL_PRICE: Final[Decimal] = Decimal("0.02")
_TAIL_SHARE_LIMIT: Final[Decimal] = Decimal("0.10")
_FEE_UNRECONCILED_LIMIT: Final[Decimal] = Decimal("0.10")
_PARITY_LIMIT: Final[Decimal] = Decimal("0.005")
_PARITY_MIN_SERIAL_FILLS: Final[int] = 20

#: One-sided normal quantiles for the Wilson helper (90% and 95%).
Z_ONE_SIDED_90: Final[float] = 1.2815515655446004
Z_ONE_SIDED_95: Final[float] = 1.6448536269514722

_BUDGET_NOTE: Final[str] = (
    "station-day and window flags are evaluated against each day's own budget; "
    "if the operator budget changed, the flags are not comparable across days"
)

# -- stop-class reasons and their "After a halt" outcomes (r4 s1, K4, N5) ------

STOP_S5_CLOPPER_PEARSON: Final[str] = "s5_clopper_pearson"  # BG-6, intraday
STOP_S5_BURST: Final[str] = "s5_burst"  # BG-6, intraday
STOP_S6_DROPPED_SHARE: Final[str] = "s6_dropped_share"
STOP_S7_COEFFICIENT: Final[str] = "s7_fee_coefficient"
STOP_S7_PER_ORDER: Final[str] = "s7_fee_per_order"
STOP_S7_PER_STAGE: Final[str] = "s7_fee_per_stage"
STOP_S9_STATION_DAY_INTRADAY: Final[str] = "s9_station_day_open_cost"  # BG-6, intraday
STOP_S9_STATION_DAY_2_OF_5: Final[str] = "s9_station_day_2_of_5"
STOP_S9_WINDOW_5S: Final[str] = "s9_window_5s"
STOP_S15_DAY: Final[str] = "s15_day"
STOP_S15_STAGE: Final[str] = "s15_stage"
STOP_S15_CUMULATIVE: Final[str] = "s15_cumulative"
STOP_DEMOTION_SECOND_FAILED_LOOK: Final[str] = "demotion_second_failed_promotion"
STOP_DEMOTION_EXCLUDED_DAYS: Final[str] = "demotion_excluded_days"

HOLD_CAP_MINIMA_UNMET: Final[str] = "l3_cap_minima_unmet"
HOLD_LOOK_WINDOW_CLOSED: Final[str] = "l3_look_window_closed"
HOLD_LOOK_NOT_TAKEN: Final[str] = "l3_look_not_taken"
HOLD_CLEANUP_DEMOTION: Final[str] = "m5_cleanup_demotion"

_S5_REASONS: Final[frozenset[str]] = frozenset({STOP_S5_CLOPPER_PEARSON, STOP_S5_BURST})


class StopOutcome(Enum):
    """The post-halt outcome of the r4 s1 "After a halt" table (N5)."""

    RESTART_S1 = "restart_s1"
    DOWN_ONE_STAGE = "down_one_stage"
    K1_AMENDMENT = "k1_amendment"
    SUSPEND = "suspend"


STOP_OUTCOMES: Final[Mapping[str, StopOutcome]] = MappingProxyType(
    {
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
)
STOP_CLASS_REASONS: Final[frozenset[str]] = frozenset(STOP_OUTCOMES)


# -- public input types ---------------------------------------------------------


class PnlPredicatePort(Protocol):
    """The P&L slice of ``LedgerPredicatePort`` (BG-1e; K6). Declared here so this module
    never imports the Nautilus-bound ``breaker_watcher``: ``DailySpendLedger`` satisfies it."""

    def pnl_breaches_budget_fraction(
        self, *, aggregate_pnl: Decimal, fraction: Decimal
    ) -> bool: ...


class LookOutcome(Enum):
    PASSED = "passed"
    FAILED = "failed"
    #: O2 item 4/7: V1-V3 failed or BG-10(f) gave no usable record; no look, the stage holds.
    NOT_TAKEN = "not_taken"


@dataclass(frozen=True, slots=True)
class LookRecord:
    """A recorded promotion look; ``day`` is the climate day it was taken on."""

    day: str
    outcome: LookOutcome


@dataclass(frozen=True, slots=True)
class SerialBaseline:
    """The K=1 pre-boot fill ledger (BG-1c) reduced for s7 parity: fill count and mean slippage."""

    fills: int
    mean_slippage: Decimal | None


@dataclass(frozen=True, slots=True)
class DayCounters:
    """One arm-time climate day of BG-1b counters; ``None`` means missing (FAIL, never 0).

    ``denied_counted`` is the s6 numerator (OpenExposureBoundExceeded, K-full, cool-off,
    throttle, free balance, BG-11 pre-filter WAITs; breaker and stale excluded). It may be
    ``None`` before S3 (K7).
    """

    day: str
    posted: int | None
    ambiguous: int | None
    denied_counted: int | None
    fills: tuple[FillRow, ...] | None
    open_flags: tuple[OpenCostFlag, ...] | None
    windows: tuple[WindowPeak, ...] | None


@dataclass(frozen=True, slots=True)
class DayPnl:
    """A day's settled-P&L reading; ``None`` marks a row that is expected but unreadable."""

    day: str
    reading: SettledPnlReading | None


@dataclass(frozen=True, slots=True)
class StageSnapshot:
    """Everything one pass reads. The caller (loop thread) builds it from the BG-1 ports.

    ``days`` carries the counters of every non-excluded stage day plus ``today`` (when it is
    strictly after the floor day), and, for s15-cumulative, of every day from the first K>1
    boot through the floor day (their ``posted`` decides whether a settled-P&L row is
    required). Other days are ignored. ``pnl_days`` lists every day with a settled-P&L row (and
    ``None`` readings for expected-but-unreadable rows) since the first K>1 boot, for
    s15-cumulative. ``gappy_days`` and ``pending_rebuild_days`` are the still-unreconciled
    days after the BG-1d pass whose ``pass_status`` is given. ``looks`` are the recorded
    promotion looks. ``unattributed_ambiguous`` is the count of AMBIGUOUS rows BG-1b could
    not place on a day (``None`` = unreadable).
    """

    today: str
    configured_k: int
    effective_k: int
    floor: StageReset | None
    epochs: tuple[EpochRow, ...]
    excluded_days: tuple[ExcludedDay, ...]
    days: tuple[DayCounters, ...]
    pnl_days: tuple[DayPnl, ...]
    gappy_days: frozenset[str]
    pending_rebuild_days: frozenset[str]
    pass_status: PassStatus
    looks: tuple[LookRecord, ...]
    stop_verdicts: tuple[StopVerdict, ...]
    serial_baseline: SerialBaseline | None
    unattributed_ambiguous: int | None
    day_of_ns: Callable[[int], str]
    predicates: PnlPredicatePort


# -- public output types ---------------------------------------------------------


class VerdictKind(Enum):
    PASS = "pass"
    STOP = "stop"
    PROMOTION_ELIGIBLE = "promotion_eligible"
    HOLD = "hold"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class DayStat:
    """Per stage day counts for BG-10(f) (r4.5 O5): the day-level AMBIGUOUS counts."""

    day: str
    posted: int
    ambiguous: int
    fills: int


@dataclass(frozen=True, slots=True)
class StageReport:
    """Report fields. No currency amounts: counts, ratios and flags only."""

    stage: str
    configured_k: int
    effective_k: int
    floor_day: str
    today: str
    closed_days: int
    nonexcluded_days: int
    excluded_days: tuple[str, ...]
    posted: int
    ambiguous: int
    ambiguous_rate: Decimal | None
    fills: int
    filled_orders: int
    days_with_fill: int
    m_bar: Decimal | None
    day_stats: tuple[DayStat, ...]
    minima_met: bool
    dropped_share: Decimal | None
    station_day_flag_days: tuple[str, ...]
    window_flag_days: tuple[str, ...]
    slippage_mean: Decimal | None
    slippage_tail_share: Decimal | None
    parity_diff: Decimal | None
    fee_unreconciled_share: Decimal | None
    per_fill_fee_mismatches: int
    section5_halt_in_stage: bool
    held_days: int
    promotion_blocked_reason: str | None
    #: A PASSED look is on record but the K change (stage_reset) has not landed yet.
    promotion_pending_commit: bool
    #: Entries inside the settlement deadline (not charged), past it (charged as a full-cost
    #: loss) and AMBIGUOUS-unresolved (charged), summed over the stage's settled-P&L rows.
    pnl_pending: int
    pnl_overdue: int
    pnl_ambiguous_unresolved: int
    programme_paused: bool
    notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Verdict:
    """One pass's verdict. STOP and HOLD(M5) carry ``target_k``; STOP sets the flag."""

    kind: VerdictKind
    reason: str | None = None
    outcome: StopOutcome | None = None
    target_k: int | None = None
    stops: tuple[str, ...] = ()
    sets_flag: bool = False
    look_number: int | None = None
    #: Deterministic reasons the look would FAIL even before BG-10(f) (s7 slippage, fee
    #: reconciliation, parity, fill days, s5 halt); the caller records a failed look.
    look_blockers: tuple[str, ...] = ()
    report: StageReport | None = None


# -- pure helpers (public) --------------------------------------------------------


def fee_stage_tolerance(orders: int) -> Decimal:
    """s7 per-stage fee tolerance: ``max(2 c, 0.5 c x orders)`` in dollars."""
    return max(_FEE_STAGE_FLOOR, _FEE_STAGE_PER_ORDER * orders)


def wilson_deff_upper_bound(k: int, n: int, *, icc: float, m_bar: float, z: float) -> float:
    """One-sided Wilson upper bound on a pooled rate with the design effect (s5).

    ``DEFF = 1 + (m_bar - 1) x icc`` and ``n_eff = n / DEFF``. ``icc`` is an ARGUMENT: the
    evaluator never estimates it (r4.5 O2/O5); BG-10(f) supplies ICC_v. ``z`` is
    :data:`Z_ONE_SIDED_90` or :data:`Z_ONE_SIDED_95`.
    """
    if not all(isfinite(v) for v in (icc, m_bar, z)):
        raise ValueError("Wilson-DEFF arguments must be finite")
    if n <= 0 or k < 0 or k > n or icc < 0 or m_bar <= 0 or z <= 0:
        raise ValueError("invalid Wilson-DEFF arguments")
    n_eff = n / max(1.0, 1.0 + (m_bar - 1.0) * icc)  # DEFF is never below 1
    p = k / n
    z2 = z * z
    centre = p + z2 / (2.0 * n_eff)
    spread = z * sqrt(p * (1.0 - p) / n_eff + z2 / (4.0 * n_eff * n_eff))
    return min(1.0, (centre + spread) / (1.0 + z2 / n_eff))


# -- internals ----------------------------------------------------------------------


class _Fail(Exception):
    """An integrity failure; ``reason`` is the full halt reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _fail(kind: str) -> _Fail:
    return _Fail(f"stage_eval_fail:{kind}")


_ISO_DAY: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def _day(text: object) -> dt.date:
    """Strict ``YYYY-MM-DD`` (ISO basic and week forms are rejected)."""
    if not isinstance(text, str) or _ISO_DAY.fullmatch(text) is None:
        raise _fail("bad_day")
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        raise _fail("bad_day") from None


def _dec(value: object, *, nonfinite: str = "fill_decimal") -> Decimal:
    """``str`` or ``Decimal`` only (never a float); non-finite raises ``nonfinite``."""
    if isinstance(value, bool) or not isinstance(value, str | Decimal):
        raise _fail("fill_decimal")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        raise _fail("fill_decimal") from None
    if not parsed.is_finite():
        raise _fail(nonfinite)
    return parsed


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _fail("bad_counter")
    return value


@dataclass(frozen=True, slots=True)
class _Fill:
    trade: str
    order: str
    qty: Decimal
    px: Decimal
    slip: Decimal
    realized: Decimal
    exact: Decimal
    theta_ok: bool


@dataclass(frozen=True, slots=True)
class _Ctx:
    snap: StageSnapshot
    floor: StageReset
    floor_day: str
    today: str
    closed: tuple[str, ...]
    eligible: tuple[str, ...]
    live: tuple[str, ...]
    excluded_in_stage: tuple[str, ...]
    by_day: Mapping[str, DayCounters]
    pnl: Mapping[str, SettledPnlReading | None]
    first_k_day: str
    stage_k: int


def _day_label(snap: StageSnapshot, ns: int) -> str:
    return snap.day_of_ns(ns)


def _validate_k(snap: StageSnapshot) -> None:
    k, eff = snap.configured_k, snap.effective_k
    ints = all(isinstance(v, int) and not isinstance(v, bool) for v in (k, eff))
    if not ints or k not in _STAGE_OF_K or not 1 <= eff <= k:
        raise _fail("invalid_k")


def _first_k_gt1_day(snap: StageSnapshot) -> str:
    if any(later.boot_ts <= earlier.boot_ts for earlier, later in pairwise(snap.epochs)):
        raise _fail("non_monotonic")
    for epoch in snap.epochs:
        if epoch.effective_k > 1:
            return _day_label(snap, epoch.boot_ts)
    return snap.today  # forced to K=1 from its first boot: legitimately serial, cumulative empty


def _span(after: dt.date, before: dt.date) -> tuple[str, ...]:
    """ISO days strictly between ``after`` and ``before``."""
    count = (before - after).days - 1
    return tuple((after + dt.timedelta(days=i)).isoformat() for i in range(1, count + 1))


def _build_ctx(snap: StageSnapshot) -> _Ctx:
    if snap.floor is None:
        raise _fail("floor_missing")
    today = _day(snap.today)
    floor_day = _day_label(snap, snap.floor.ts)
    floor_date = _day(floor_day)
    if today < floor_date:
        raise _fail("non_monotonic")
    first_k_day = _first_k_gt1_day(snap)
    _day(first_k_day)
    excluded = {x.day for x in snap.excluded_days}
    for label in (*excluded, *snap.gappy_days, *snap.pending_rebuild_days):
        _day(label)
    for look in snap.looks:
        _day(look.day)
    closed = _span(floor_date, today)
    eligible = tuple(x for x in closed if x not in excluded)
    # The open today joins only when it is strictly after the floor day (item H1).
    open_today = snap.today not in excluded and today > floor_date
    live = (*eligible, snap.today) if open_today else eligible
    in_stage = tuple(sorted(x for x in excluded if floor_day < x <= snap.today))
    by_day: dict[str, DayCounters] = {}
    for row in snap.days:
        _day(row.day)
        if row.day in by_day:
            raise _fail("duplicate_day")
        by_day[row.day] = row
    pnl: dict[str, SettledPnlReading | None] = {}
    for entry in snap.pnl_days:
        _day(entry.day)
        if entry.day in pnl:
            raise _fail("duplicate_day")
        pnl[entry.day] = entry.reading
    return _Ctx(
        snap,
        snap.floor,
        floor_day,
        snap.today,
        closed,
        eligible,
        live,
        in_stage,
        by_day,
        pnl,
        first_k_day,
        snap.configured_k,
    )


def _validate_counters(ctx: _Ctx) -> None:
    for label in ctx.live:
        row = ctx.by_day.get(label)
        if row is None:
            raise _fail("missing_day")
        if (
            row.posted is None
            or row.ambiguous is None
            or row.fills is None
            or row.open_flags is None
            or row.windows is None
        ):
            raise _fail("missing_counter")
        if _count(row.posted) < _count(row.ambiguous):
            raise _fail("bad_counter")
        if row.denied_counted is not None:
            _count(row.denied_counted)
        if any(r.day != label for rows in (row.fills, row.open_flags, row.windows) for r in rows):
            raise _fail("bad_counter")
        for window in row.windows:
            _count(window.orders)
        if label in ctx.snap.gappy_days:
            raise _fail("gappy")
        if label in ctx.snap.pending_rebuild_days:
            raise _fail("pending_rebuild")


def _validate_reading(reading: SettledPnlReading) -> None:
    if not isinstance(reading.pnl, Decimal) or not reading.pnl.is_finite():
        raise _fail("pnl_nonfinite")
    counts = (
        reading.settled,
        reading.ambiguous,
        reading.pending,
        reading.overdue,
        reading.fee_unreconciled,
    )
    for value in counts:
        _count(value)


def _needs_pnl_row(row: DayCounters) -> bool:
    """A settled-P&L row must exist for a day with posted entries (ruling item 4)."""
    return bool(row.posted)


def _validate_pre_floor(ctx: _Ctx, excluded: set[str]) -> None:
    """s15-cumulative is never floored: every day since the first K>1 boot needs its row."""
    first = _day(ctx.first_k_day)
    for offset in range((_day(ctx.floor_day) - first).days + 1):
        label = (first + dt.timedelta(days=offset)).isoformat()
        if label in excluded:
            continue  # an unreconciled excluded day counts only once reconciled (10a)
        row = ctx.by_day.get(label)
        if row is None:
            raise _fail("missing_day")
        if row.posted is None:
            raise _fail("missing_counter")
        if _needs_pnl_row(row) and ctx.pnl.get(label) is None:
            raise _fail("missing_pnl_day")


def _validate_pnl(ctx: _Ctx) -> None:
    excluded = {x.day for x in ctx.snap.excluded_days}
    for reading in ctx.pnl.values():
        if reading is not None:
            _validate_reading(reading)
    # BG-1c writes a row per arm day with entries (exec_par_settled_pnl.py:234-244), settled
    # or not, so today needs its row like every closed day.
    for label in ctx.live:
        if _needs_pnl_row(ctx.by_day[label]) and ctx.pnl.get(label) is None:
            raise _fail("settled_pnl_missing")
    _validate_pre_floor(ctx, excluded)
    for label, reading in ctx.pnl.items():
        if reading is None and label >= ctx.first_k_day and label not in excluded:
            raise _fail("settled_pnl_missing")


def _parse_fills(ctx: _Ctx, labels: Iterable[str]) -> list[_Fill]:
    parsed: list[_Fill] = []
    seen: set[str] = set()
    for label in labels:
        for row in ctx.by_day[label].fills or ():
            ask = _dec(row.decision_ask)  # a missing decision ask is FAIL (s7)
            try:
                theta = Decimal(row.fee_theta)
                theta_ok = theta.is_finite() and theta == _FEE_THETA
            except (InvalidOperation, TypeError, ValueError):
                theta_ok = False
            qty, px, stored = _dec(row.qty), _dec(row.px), _dec(row.slippage)
            realized = _dec(row.fee_realized, nonfinite="pnl_nonfinite")
            exact = _dec(row.fee_exact, nonfinite="pnl_nonfinite")
            if not 0 <= px <= 1 or qty <= 0:
                raise _fail("fill_sanity")
            if row.trade_id in seen:
                raise _fail("duplicate_fill")
            seen.add(row.trade_id)
            slip = px - ask  # s7: slippage per fill is fill_px - decision ask
            if slip != stored:
                raise _fail("slippage_inconsistent")
            parsed.append(
                _Fill(row.trade_id, row.client_order_id, qty, px, slip, realized, exact, theta_ok)
            )
    return parsed


def _fee(qty: Decimal, px: Decimal) -> Decimal:
    return (_FEE_THETA * qty * px * (1 - px)).quantize(_CENT, rounding=ROUND_HALF_EVEN)


def _fee_findings(fills: list[_Fill]) -> tuple[list[str], int]:
    """s7 halts (coefficient, per order, per stage) and the report-only per-fill mismatches."""
    found: list[str] = []
    if any(not f.theta_ok for f in fills):
        found.append(STOP_S7_COEFFICIENT)
    orders: dict[str, list[_Fill]] = {}
    for f in fills:
        orders.setdefault(f.order, []).append(f)
    for group in orders.values():
        expected = (
            _FEE_THETA * sum((f.qty * f.px * (1 - f.px) for f in group), Decimal(0))
        ).quantize(_CENT, rounding=ROUND_HALF_EVEN)
        slack = Decimal(0) if len(group) == 1 else _CENT
        if abs(sum((f.realized for f in group), Decimal(0)) - expected) > slack:
            found.append(STOP_S7_PER_ORDER)
            break
    gap = abs(
        sum((f.realized for f in fills), Decimal(0)) - sum((f.exact for f in fills), Decimal(0))
    )
    if gap > fee_stage_tolerance(len(orders)):
        found.append(STOP_S7_PER_STAGE)
    mismatches = sum(1 for f in fills if f.realized != _fee(f.qty, f.px))
    return found, mismatches


def _share(denied: int, posted: int) -> Decimal:
    total = denied + posted
    return Decimal(denied) / Decimal(total) if total else Decimal(0)


def _dropped_share(ctx: _Ctx, window: Sequence[str]) -> Decimal | None:
    denied = posted = 0
    for label in window:
        row = ctx.by_day[label]
        if row.denied_counted is None or row.posted is None:
            return None
        denied += row.denied_counted
        posted += row.posted
    return _share(denied, posted)


def _s6(ctx: _Ctx) -> tuple[Decimal | None, bool]:
    """Trailing-5 share on the last closed day, and whether two consecutive windows trip."""
    if any(ctx.by_day[x].denied_counted is None for x in ctx.eligible):
        if ctx.stage_k == _S3_K:
            raise _fail("missing_counter:denied")
        return None, False
    last = _dropped_share(ctx, ctx.eligible[-_TRAILING_DAYS:]) if ctx.eligible else None
    prev = _dropped_share(ctx, ctx.eligible[:-1][-_TRAILING_DAYS:]) if ctx.eligible[:-1] else None
    tripped = (
        last is not None and prev is not None and last > _S6_SHARE_LIMIT and prev > _S6_SHARE_LIMIT
    )
    return last, tripped


def _window_flagged(row: DayCounters) -> bool:
    windows = row.windows or ()
    if sum(_count(w.orders) for w in windows) < _S9_MIN_ORDERS:
        return False
    notionals = [_dec(w.notional) for w in windows]
    total = sum(notionals, Decimal(0))
    if total <= _S9_ZERO:
        raise _fail("window_notional")
    return max(notionals) / total > _S9_SHARE_LIMIT


def _s9(ctx: _Ctx) -> tuple[tuple[str, ...], tuple[str, ...]]:
    last = ctx.eligible[-_TRAILING_DAYS:]
    station = tuple(x for x in last if any(f.exceeded for f in ctx.by_day[x].open_flags or ()))
    burst = tuple(x for x in last if _window_flagged(ctx.by_day[x]))
    return station, burst


def _breaches(port: PnlPredicatePort, name: str, aggregate: Decimal, fraction: Decimal) -> bool:
    try:
        result = port.pnl_breaches_budget_fraction(aggregate_pnl=aggregate, fraction=fraction)
    except Exception:  # noqa: BLE001 - any raise is an integrity trip (K6)
        raise _fail(f"predicate:{name}") from None
    if type(result) is not bool:
        raise _fail(f"predicate:{name}")
    return result


def _s15(ctx: _Ctx) -> list[str]:
    """Day, stage and cumulative stops, all through the predicate port."""
    port = ctx.snap.predicates
    found: list[str] = []
    stage_total = Decimal(0)
    day_hit = False
    for label in ctx.live:
        reading = ctx.pnl.get(label)
        if reading is None:
            continue
        stage_total += reading.pnl
        day_hit = day_hit or _breaches(port, "s15_day", reading.pnl, _DAY_FRACTION)
    if day_hit:
        found.append(STOP_S15_DAY)
    if _breaches(port, "s15_stage", stage_total, _STAGE_FRACTION):
        found.append(STOP_S15_STAGE)
    cumulative = sum(
        (
            r.pnl
            for day, r in ctx.pnl.items()
            if r is not None and ctx.first_k_day <= day <= ctx.today
        ),
        Decimal(0),
    )
    if _breaches(port, "s15_cumulative", cumulative, _CUMULATIVE_FRACTION):
        found.append(STOP_S15_CUMULATIVE)
    return found


#: Tie-break between stops with the same target K: most severe first (item M11).
_SEVERITY: Final[Mapping[StopOutcome, int]] = MappingProxyType(
    {
        StopOutcome.SUSPEND: 0,
        StopOutcome.K1_AMENDMENT: 1,
        StopOutcome.RESTART_S1: 2,
        StopOutcome.DOWN_ONE_STAGE: 3,
    }
)


def _target_k(outcome: StopOutcome, k: int, effective_k: int) -> int:
    """The K the ramp goes to; never above a K the node was already forced down to (H2)."""
    if outcome is StopOutcome.RESTART_S1:
        target = _RESTART_S1_K
    elif outcome is StopOutcome.DOWN_ONE_STAGE:
        target = _DEMOTE_K[k]
    else:
        target = 1
    return min(target, effective_k) if effective_k < k else target


def _stage_looks(ctx: _Ctx) -> list[LookRecord]:
    return sorted((x for x in ctx.snap.looks if x.day > ctx.floor_day), key=lambda x: x.day)


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


def _stage_stats(ctx: _Ctx, fills: list[_Fill]) -> _Stats:
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
            Decimal(sum(1 for s in slips if s > _SLIPPAGE_TAIL_PRICE)) / len(slips)
            if slips
            else None
        ),
        unreconciled=Decimal(unrec) / len(orders) if orders else None,
    )


def _parity(base: SerialBaseline | None, mean: Decimal | None) -> Decimal | None:
    if base is None:
        return None
    if base.mean_slippage is None:
        if base.fills >= _PARITY_MIN_SERIAL_FILLS:
            raise _fail("parity_baseline")
        return None
    return None if mean is None else mean - base.mean_slippage


def _blockers(ctx: _Ctx, stats: _Stats, parity: Decimal | None) -> tuple[str, ...]:
    """Deterministic look failures (s7 promotion conditions, s5 halt, fill days)."""
    out: list[str] = []
    if any(v.reason in _S5_REASONS and v.ts_ns >= ctx.floor.ts for v in ctx.snap.stop_verdicts):
        out.append("s5_halt_in_stage")
    if stats.fill_days < _MIN_FILL_DAYS:
        out.append("fill_days_below_5")
    if stats.slip_mean is None:
        out.append("no_fills")
    elif stats.slip_mean > _SLIPPAGE_MEAN_LIMIT:
        out.append("slippage_mean")
    if stats.slip_tail is not None and stats.slip_tail > _TAIL_SHARE_LIMIT:
        out.append("slippage_tail")
    if stats.unreconciled is not None and stats.unreconciled > _FEE_UNRECONCILED_LIMIT:
        out.append("fee_unreconciled")
    base = ctx.snap.serial_baseline
    if (
        base is not None
        and base.fills >= _PARITY_MIN_SERIAL_FILLS
        and parity is not None
        and parity > _PARITY_LIMIT
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


def _report(ctx: _Ctx, c: _Checks, **extra: object) -> StageReport:
    s = c.stats
    fields: dict[str, object] = {
        "stage": _STAGE_OF_K[ctx.stage_k],
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
        "notes": (_BUDGET_NOTE,),
    }
    fields.update(extra)
    return StageReport(**fields)  # type: ignore[arg-type]


def _stop_findings(
    ctx: _Ctx, looks: list[LookRecord], s6_tripped: bool, c: _Checks, fee: list[str], pnl: list[str]
) -> list[str]:
    found: list[str] = []
    if len(ctx.excluded_in_stage) > _MAX_EXCLUDED_DAYS:
        found.append(STOP_DEMOTION_EXCLUDED_DAYS)
    if sum(1 for x in looks if x.outcome is LookOutcome.FAILED) >= _FAILED_LOOKS_FOR_DEMOTION:
        found.append(STOP_DEMOTION_SECOND_FAILED_LOOK)
    if ctx.stage_k == _S3_K and s6_tripped:
        found.append(STOP_S6_DROPPED_SHARE)
    found += fee
    if len(c.station_days) >= _S9_MIN_FLAG_DAYS:
        found.append(STOP_S9_STATION_DAY_2_OF_5)
    if len(c.burst_days) >= _S9_MIN_FLAG_DAYS:
        found.append(STOP_S9_WINDOW_5S)
    return found + pnl


def _evaluate(snap: StageSnapshot) -> Verdict:
    _validate_k(snap)
    if snap.configured_k == 1:
        return Verdict(VerdictKind.PASS)  # S0: no K>1 stage to evaluate
    if snap.pass_status is not PassStatus.OK:
        raise _Fail("reconcile_stuck")
    ctx = _build_ctx(snap)
    _validate_counters(ctx)
    if snap.unattributed_ambiguous is None or snap.unattributed_ambiguous != 0:
        raise _fail("unattributed_ambiguous")
    _validate_pnl(ctx)

    fee_stops, per_fill = _fee_findings(_parse_fills(ctx, ctx.live))
    share, s6_tripped = _s6(ctx)
    station_days, burst_days = _s9(ctx)
    pnl_stops = _s15(ctx)
    stats = _stage_stats(ctx, _parse_fills(ctx, ctx.eligible))
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
        sum(ctx.by_day[x].posted or 0 for x in capped) >= _MIN_POSTED_ORDERS
        and len(capped) >= _MIN_NONEXCLUDED_DAYS,
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
            return _target_k(kind, ctx.stage_k, eff), _SEVERITY[kind]

        # Lowest resulting K first, then severity; ties keep evaluation order (min is stable).
        primary = min(findings, key=rank)
        outcome = STOP_OUTCOMES[primary]
        return Verdict(
            VerdictKind.STOP,
            primary,
            outcome,
            _target_k(outcome, ctx.stage_k, eff),
            tuple(findings),
            True,
            report=_report(ctx, checks),
        )
    return _base_verdict(ctx, looks, checks)


def _look_state(
    ctx: _Ctx, looks: list[LookRecord], minima_met: bool
) -> tuple[str | None, int | None]:
    """(hold reason, look number due) once no stop fired. At most one is set."""
    if ctx.stage_k == _S3_K:
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
        if since < _EXTENSION_DAYS and n_closed < STAGE_CAP_DAYS:
            return None, None  # the 5-day extension is still running
    if n_closed > STAGE_CAP_DAYS:
        return HOLD_LOOK_WINDOW_CLOSED, None
    return None, 1 + len(failed)


def _base_verdict(ctx: _Ctx, looks: list[LookRecord], c: _Checks) -> Verdict:
    """No stop fired: hold (L3/M5), look due, or pass."""
    held, look_number = _look_state(ctx, looks, c.minima_met)
    nonexcluded = len(ctx.eligible)
    if held is not None and nonexcluded >= CLEANUP_HOLD_DAYS:
        to_k = _DEMOTE_K[ctx.stage_k]
        return Verdict(
            VerdictKind.HOLD,
            HOLD_CLEANUP_DEMOTION,
            StopOutcome.DOWN_ONE_STAGE,
            to_k,
            report=_report(ctx, c, held_days=nonexcluded, programme_paused=to_k == 1),
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
    except _Fail as failure:
        return Verdict(VerdictKind.FAIL, reason=failure.reason)
    except Exception as exc:  # noqa: BLE001 - last resort; never echo the message (could carry money)
        return Verdict(VerdictKind.FAIL, reason=f"stage_eval_fail:internal:{type(exc).__name__}")
