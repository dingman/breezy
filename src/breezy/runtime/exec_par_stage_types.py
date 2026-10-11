"""EXEC-PAR BG-5a: stage-evaluator constants, snapshot and verdict types, shared helpers.

Split out of :mod:`breezy.runtime.exec_par_stage_eval` (no behaviour change). Pure: no I/O,
no clock, no logging, no Nautilus or ``breezy.adapters`` import.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
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

# -- thresholds (spec citations in the names' comments) -----------------------

#: s1 ladder: configured K -> stage label, and the demotion target.
STAGE_OF_K: Final[Mapping[int, str]] = MappingProxyType({1: "S0", 2: "S1", 4: "S2", 6: "S3"})
DEMOTE_K: Final[Mapping[int, int]] = MappingProxyType({2: 1, 4: 2, 6: 4})
RESTART_S1_K: Final[int] = 2
S3_K: Final[int] = 6

STAGE_CAP_DAYS: Final[int] = 15  # s1 item 5
EXTENSION_DAYS: Final[int] = 5  # s1 item 2
FAILED_LOOKS_FOR_DEMOTION: Final[int] = 2  # s1 item 4
MIN_POSTED_ORDERS: Final[int] = 30  # K10 look minimum
MIN_NONEXCLUDED_DAYS: Final[int] = 8  # K10 look minimum
MIN_FILL_DAYS: Final[int] = 5  # s1 table: climate days with >=1 entry fill
CLEANUP_HOLD_DAYS: Final[int] = 30  # M5
MAX_EXCLUDED_DAYS: Final[int] = 2  # 10a cap
TRAILING_DAYS: Final[int] = 5  # s6, s9 windows

S6_SHARE_LIMIT: Final[Decimal] = Decimal("0.30")
S9_MIN_FLAG_DAYS: Final[int] = 2
S9_MIN_ORDERS: Final[int] = 6
S9_SHARE_LIMIT: Final[Decimal] = Decimal("0.50")
S9_ZERO: Final[Decimal] = Decimal(0)

DAY_FRACTION: Final[Decimal] = Decimal("0.15")  # s15
STAGE_FRACTION: Final[Decimal] = Decimal("0.40")
CUMULATIVE_FRACTION: Final[Decimal] = Decimal("1.0")

#: s7 theta (PREREG theta; adapters/polymarket_us/fees.py post-drift coefficient). Not importable
#: here (no adapters import); a stored fill's ``fee_theta`` must equal it exactly.
FEE_THETA: Final[Decimal] = Decimal("0.0695")
CENT: Final[Decimal] = Decimal("0.01")
FEE_STAGE_FLOOR: Final[Decimal] = Decimal("0.02")
FEE_STAGE_PER_ORDER: Final[Decimal] = Decimal("0.005")
SLIPPAGE_MEAN_LIMIT: Final[Decimal] = Decimal("0.005")
SLIPPAGE_TAIL_PRICE: Final[Decimal] = Decimal("0.02")
TAIL_SHARE_LIMIT: Final[Decimal] = Decimal("0.10")
FEE_UNRECONCILED_LIMIT: Final[Decimal] = Decimal("0.10")
PARITY_LIMIT: Final[Decimal] = Decimal("0.005")
PARITY_MIN_SERIAL_FILLS: Final[int] = 20

#: One-sided normal quantiles for the Wilson helper (90% and 95%).
Z_ONE_SIDED_90: Final[float] = 1.2815515655446004
Z_ONE_SIDED_95: Final[float] = 1.6448536269514722

BUDGET_NOTE: Final[str] = (
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

S5_REASONS: Final[frozenset[str]] = frozenset({STOP_S5_CLOPPER_PEARSON, STOP_S5_BURST})


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

    def to_json_dict(self) -> dict[str, object]:
        """Every field named explicitly (no ``asdict``; see the credential-serialisation guard)."""
        return {
            "day": self.day,
            "posted": self.posted,
            "ambiguous": self.ambiguous,
            "fills": self.fills,
        }


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

    def to_json_dict(self) -> dict[str, object]:
        """Every field named explicitly (no ``asdict``; see the credential-serialisation guard)."""
        return {
            "stage": self.stage,
            "configured_k": self.configured_k,
            "effective_k": self.effective_k,
            "floor_day": self.floor_day,
            "today": self.today,
            "closed_days": self.closed_days,
            "nonexcluded_days": self.nonexcluded_days,
            "excluded_days": self.excluded_days,
            "posted": self.posted,
            "ambiguous": self.ambiguous,
            "ambiguous_rate": self.ambiguous_rate,
            "fills": self.fills,
            "filled_orders": self.filled_orders,
            "days_with_fill": self.days_with_fill,
            "m_bar": self.m_bar,
            "day_stats": [d.to_json_dict() for d in self.day_stats],
            "minima_met": self.minima_met,
            "dropped_share": self.dropped_share,
            "station_day_flag_days": self.station_day_flag_days,
            "window_flag_days": self.window_flag_days,
            "slippage_mean": self.slippage_mean,
            "slippage_tail_share": self.slippage_tail_share,
            "parity_diff": self.parity_diff,
            "fee_unreconciled_share": self.fee_unreconciled_share,
            "per_fill_fee_mismatches": self.per_fill_fee_mismatches,
            "section5_halt_in_stage": self.section5_halt_in_stage,
            "held_days": self.held_days,
            "promotion_blocked_reason": self.promotion_blocked_reason,
            "promotion_pending_commit": self.promotion_pending_commit,
            "pnl_pending": self.pnl_pending,
            "pnl_overdue": self.pnl_overdue,
            "pnl_ambiguous_unresolved": self.pnl_ambiguous_unresolved,
            "programme_paused": self.programme_paused,
            "notes": self.notes,
        }


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


class StageFail(Exception):
    """An integrity failure; ``reason`` is the full halt reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def fail(kind: str) -> StageFail:
    return StageFail(f"stage_eval_fail:{kind}")


ISO_DAY: Final = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


def parse_day(text: object) -> dt.date:
    """Strict ``YYYY-MM-DD`` (ISO basic and week forms are rejected)."""
    if not isinstance(text, str) or ISO_DAY.fullmatch(text) is None:
        raise fail("bad_day")
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        raise fail("bad_day") from None


def parse_dec(value: object, *, nonfinite: str = "fill_decimal") -> Decimal:
    """``str`` or ``Decimal`` only (never a float); non-finite raises ``nonfinite``."""
    if isinstance(value, bool) or not isinstance(value, str | Decimal):
        raise fail("fill_decimal")
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        raise fail("fill_decimal") from None
    if not parsed.is_finite():
        raise fail(nonfinite)
    return parsed


def check_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise fail("bad_counter")
    return value


@dataclass(frozen=True, slots=True)
class StageContext:
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
