"""MAKER S2 WP0 -- pure core of the Stage-0 probe (no I/O).

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md WP0 (L108-117) and
S2_stage0_replay_plan_r4_delta.md (e), (i)3. The direction check, census re-assertions and the
clock-offset delta live here; ``maker_stage0_probe`` is the I/O layer that feeds them.
Inverted or inconclusive direction is an S-2 STOP (``StopS2``), never a recorded flip.
"""

from __future__ import annotations

import datetime as dt
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Final

from breezy.analysis import maker_tape_census as core

_NS: Final[int] = 1_000_000_000
FIX_MIN: Final[float] = 0.9
INVERT_MAX: Final[float] = 0.1
MIN_DEFINED_PER_SIDE: Final[int] = 200
FIRST_REPLAYABLE_CUTOFF_UTC: Final[tuple[int, int]] = (16, 50)  # D-1 16:50Z, per plan section 3
_Samples = Sequence[tuple[int, int]]  # (ts_init, signed offset_ns)


class StopS2(Exception):
    """Direction is not FIXED: back to the spec. Carries the result for the sidecar."""

    def __init__(self, result: DirectionResult) -> None:
        super().__init__(f"STOP S-2 direction check {result.verdict}: {result.to_dict()}")
        self.result = result


class CensusViolation(Exception):
    """A S1 census invariant (0 NO_AGGRESSOR / duplicate trade_id / opposite twin) failed."""


# --- Direction check ------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class Frame:
    ts_ns: int
    mid: Decimal | None  # None: one-sided or empty book


@dataclass(frozen=True, slots=True)
class Gap:
    start_ns: int
    end_ns: int | None  # None: still open, runs on


@dataclass(frozen=True, slots=True)
class SideTally:
    n_agree: int = 0
    n_disagree: int = 0
    n_undefined: int = 0

    @property
    def n_defined(self) -> int:
        return self.n_agree + self.n_disagree

    @property
    def agreement(self) -> float | None:
        return self.n_agree / self.n_defined if self.n_defined else None

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "n_defined": self.n_defined, "agreement": self.agreement}


@dataclass(frozen=True, slots=True)
class DirectionResult:
    verdict: str  # FIXED | INVERTED | INCONCLUSIVE | INSUFFICIENT
    buyer: SideTally
    seller: SideTally

    def to_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict,
            "buyer": self.buyer.to_dict(),
            "seller": self.seller.to_dict(),
            "thresholds": {
                "fix_min": FIX_MIN,
                "invert_max": INVERT_MAX,
                "min_defined_per_side": MIN_DEFINED_PER_SIDE,
            },
        }


def gap_free_frames(frames: Iterable[Frame], gaps: Collection[Gap]) -> list[Frame]:
    """Frames whose ``ts`` lies in no gap (inclusive ends; an open gap runs to infinity)."""

    def covered(ts: int) -> bool:
        return any(g.start_ns <= ts and (g.end_ns is None or ts <= g.end_ns) for g in gaps)

    return sorted((f for f in frames if not covered(f.ts_ns)), key=lambda f: f.ts_ns)


def _agrees(side: str, price: Decimal, mid: Decimal) -> bool:
    return price >= mid if side == core.BUYER else price <= mid


def direction_result(
    prints: Iterable[core.PrintRecord], frames_by_rung: Mapping[str, Sequence[Frame]]
) -> DirectionResult:
    """BUYER prints >= the prior YES mid, SELLER prints <= it. ``frames_by_rung`` is gap-free."""
    stamps = {rung: [f.ts_ns for f in fs] for rung, fs in frames_by_rung.items()}
    counts = {core.BUYER: [0, 0, 0], core.SELLER: [0, 0, 0]}  # agree, disagree, undefined
    for record in prints:
        if record.aggressor not in counts:
            continue
        row = counts[record.aggressor]
        index = bisect_left(stamps.get(record.rung, ()), record.ts_event_ns) - 1
        mid = frames_by_rung[record.rung][index].mid if index >= 0 else None
        if mid is None:
            row[2] += 1
        else:
            row[0 if _agrees(record.aggressor, record.price_yes, mid) else 1] += 1
    return classify_direction(SideTally(*counts[core.BUYER]), SideTally(*counts[core.SELLER]))


def classify_direction(buyer: SideTally, seller: SideTally) -> DirectionResult:
    if min(buyer.n_defined, seller.n_defined) < MIN_DEFINED_PER_SIDE:
        return DirectionResult("INSUFFICIENT", buyer, seller)
    rates = [buyer.agreement or 0.0, seller.agreement or 0.0]
    if all(r >= FIX_MIN for r in rates):
        return DirectionResult("FIXED", buyer, seller)
    if all(r <= INVERT_MAX for r in rates):
        return DirectionResult("INVERTED", buyer, seller)
    return DirectionResult("INCONCLUSIVE", buyer, seller)


def enforce_direction(result: DirectionResult) -> DirectionResult:
    if result.verdict != "FIXED":
        raise StopS2(result)
    return result


def first_replayable_day(first_print_ns: int) -> dt.date:
    """D needs the feed from D-1 16:50Z; a first print after that instant pushes to D+1."""
    day = dt.datetime.fromtimestamp(first_print_ns // _NS, dt.UTC).date()
    hour, minute = FIRST_REPLAYABLE_CUTOFF_UTC
    cutoff = dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=dt.UTC)
    return day + dt.timedelta(days=1 if first_print_ns <= int(cutoff.timestamp()) * _NS else 2)


# --- Census re-assertions -------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CensusCounts:
    n_prints: int
    no_aggressor: int
    duplicate_trade_ids: int  # a trade_id repeated WITHIN one instance
    opposite_side_twins: int  # same rung/ts/price/size printed as both BUYER and SELLER
    cross_instance_overlap: int  # trade_ids seen by >1 instance (legal; deduped first-wins)


def count_census(prints_by_instance: Mapping[str, Sequence[core.PrintRecord]]) -> CensusCounts:
    seen_in: dict[str, set[str]] = defaultdict(set)
    first: dict[str, core.PrintRecord] = {}
    duplicates = 0
    for instance in sorted(prints_by_instance):
        ids: set[str] = set()
        for record in prints_by_instance[instance]:
            duplicates += record.trade_id in ids
            ids.add(record.trade_id)
            seen_in[record.trade_id].add(instance)
            first.setdefault(record.trade_id, record)
    sides: dict[tuple[str, int, Decimal, Decimal], set[str]] = defaultdict(set)
    for r in first.values():
        sides[(r.rung, r.ts_event_ns, r.price_yes, r.size)].add(r.aggressor)
    return CensusCounts(
        n_prints=len(first),
        no_aggressor=sum(r.aggressor == core.NO_AGGRESSOR for r in first.values()),
        duplicate_trade_ids=duplicates,
        opposite_side_twins=sum({core.BUYER, core.SELLER} <= s for s in sides.values()),
        cross_instance_overlap=sum(len(v) > 1 for v in seen_in.values()),
    )


def reassert_census(counts: CensusCounts) -> CensusCounts:
    if counts.no_aggressor or counts.duplicate_trade_ids or counts.opposite_side_twins:
        raise CensusViolation(f"census re-assertion failed: {asdict(counts)}")
    return counts


# --- Clock offset ---------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class InstanceDayDelta:
    """Delta = max |offset_ns| over one recorder instance's samples in a station-day window."""

    delta_ns: int
    samples: int
    min_offset_ns: int
    max_offset_ns: int
    instance: str = ""
    station: str = ""
    climate_day: str = ""


def instance_day_deltas(
    samples_by_instance: Mapping[str, _Samples], window: tuple[int, int]
) -> dict[str, InstanceDayDelta]:
    out: dict[str, InstanceDayDelta] = {}
    for instance, samples in samples_by_instance.items():
        offsets = [o for ts, o in samples if window[0] <= ts < window[1]]
        if offsets:
            out[instance] = InstanceDayDelta(
                max(abs(o) for o in offsets), len(offsets), min(offsets), max(offsets),
                instance=instance,
            )  # fmt: skip
    return out


def station_day_delta(per_instance: Mapping[str, InstanceDayDelta]) -> int | None:
    return max((d.delta_ns for d in per_instance.values()), default=None)
