"""MAKER S2 WP0 -- pure core of the Stage-0 probe (no I/O).

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md WP0 (L108-117) and
S2_stage0_replay_plan_r4_delta.md (e), (i)3. The direction check, census re-assertions and the
clock-offset delta live here; ``maker_stage0_probe`` is the I/O layer that feeds them.
Inverted or inconclusive direction is an S-2 STOP (``StopS2``), never a recorded flip.
"""

from __future__ import annotations

import datetime as dt
import statistics
from bisect import bisect_left
from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from typing import TYPE_CHECKING, Final

from breezy.adapters.polymarket_us.symbology import leg_of
from breezy.analysis import maker_tape_census as core
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id

if TYPE_CHECKING:
    from nautilus_trader.model.data import OrderBookDepth10
    from nautilus_trader.model.identifiers import InstrumentId

_NS: Final[int] = 1_000_000_000
_HOUR_NS: Final[int] = 3_600 * _NS
FIX_MIN: Final[float] = 0.9
INVERT_MAX: Final[float] = 0.1
MIN_DEFINED_PER_SIDE: Final[int] = 200
FIRST_REPLAYABLE_CUTOFF_UTC: Final[tuple[int, int]] = (16, 50)  # D-1 16:50Z, per plan section 3
_P95_PERCENT: Final[int] = 95
_Samples = Sequence[tuple[int, int]]  # (ts_init, signed offset_ns)
StationDay = tuple[str, dt.date]


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
    """Per-side counts. A tie (print exactly at the mid) AGREES (frozen ``>=`` / ``<=``) and is
    also counted in ``n_tie`` so a tie-excluded rate can be reported (report-only)."""

    n_agree: int = 0
    n_disagree: int = 0
    n_undefined: int = 0
    n_tie: int = 0  # subset of n_agree

    @property
    def n_defined(self) -> int:
        """Prints with a defined prior mid (agree + disagree)."""
        return self.n_agree + self.n_disagree

    @property
    def agreement(self) -> float | None:
        """The frozen statistic: agree / defined, ties counted as agreeing."""
        return self.n_agree / self.n_defined if self.n_defined else None

    @property
    def agreement_excl_ties(self) -> float | None:
        """Report-only: (agree - ties) / (defined - ties); never a verdict input."""
        defined = self.n_defined - self.n_tie
        return (self.n_agree - self.n_tie) / defined if defined else None

    def to_dict(self) -> dict[str, object]:
        """JSON-ready tally including both agreement rates."""
        return {
            **asdict(self),
            "n_defined": self.n_defined,
            "agreement": self.agreement,
            "agreement_excl_ties": self.agreement_excl_ties,
        }


@dataclass(frozen=True, slots=True)
class DirectionResult:
    verdict: str  # FIXED | INVERTED | INCONCLUSIVE | INSUFFICIENT
    buyer: SideTally
    seller: SideTally
    mid_age_ns: Mapping[str, int | None] | None = None  # report-only: print ts - mid frame ts

    def to_dict(self) -> dict[str, object]:
        """JSON-ready verdict, tallies, frozen thresholds and the mid-age distribution."""
        return {
            "verdict": self.verdict,
            "buyer": self.buyer.to_dict(),
            "seller": self.seller.to_dict(),
            "mid_age_ns": None if self.mid_age_ns is None else dict(self.mid_age_ns),
            "thresholds": {
                "fix_min": FIX_MIN,
                "invert_max": INVERT_MAX,
                "min_defined_per_side": MIN_DEFINED_PER_SIDE,
            },
        }


def gap_free_frames(frames: Iterable[Frame], gaps: Collection[Gap]) -> list[Frame]:
    """Frames whose ``ts`` lies in no gap (inclusive ends; an open gap runs to infinity).

    CLOCKS: gap rows carry the RECORDER node clock (``data.py`` stamps ``started_ns``/``ended_ns``
    from ``self._clock.timestamp_ns()``); ``Frame.ts_ns`` is the VENUE ``transactTime``. The two
    are compared directly, so the exclusion edge can be off by the clock offset (Delta, which
    the report states and S-7 caps at 10 min); the plan is literal here and this is not corrected.
    """

    def covered(ts: int) -> bool:
        return any(g.start_ns <= ts and (g.end_ns is None or ts <= g.end_ns) for g in gaps)

    return sorted((f for f in frames if not covered(f.ts_ns)), key=lambda f: f.ts_ns)


def _agrees(side: str, price: Decimal, mid: Decimal) -> bool:
    return price >= mid if side == core.BUYER else price <= mid


def direction_result(
    prints: Iterable[core.PrintRecord], frames_by_rung: Mapping[str, Sequence[Frame]]
) -> DirectionResult:
    """BUYER prints >= the prior YES mid, SELLER prints <= it. ``frames_by_rung`` is gap-free.

    The prior frame is the last one STRICTLY before the print. Ties agree (frozen) and are
    counted separately; the age of every defined mid is recorded (report-only).
    """
    stamps = {rung: [f.ts_ns for f in fs] for rung, fs in frames_by_rung.items()}
    counts = {core.BUYER: [0, 0, 0, 0], core.SELLER: [0, 0, 0, 0]}  # agree, disagree, undef, tie
    ages: list[int] = []
    for record in prints:
        if record.aggressor not in counts:
            continue
        row = counts[record.aggressor]
        index = bisect_left(stamps.get(record.rung, ()), record.ts_event_ns) - 1
        frame = frames_by_rung[record.rung][index] if index >= 0 else None
        if frame is None or frame.mid is None:
            row[2] += 1
            continue
        ages.append(record.ts_event_ns - frame.ts_ns)
        row[0 if _agrees(record.aggressor, record.price_yes, frame.mid) else 1] += 1
        row[3] += record.price_yes == frame.mid
    result = classify_direction(SideTally(*counts[core.BUYER]), SideTally(*counts[core.SELLER]))
    return replace(result, mid_age_ns=distribution(ages))


def classify_direction(buyer: SideTally, seller: SideTally) -> DirectionResult:
    """Per-side rule: FIXED both >= 0.9, INVERTED both <= 0.1, else INCONCLUSIVE; any side
    with fewer than 200 defined prints is INSUFFICIENT (all three non-FIXED outcomes STOP)."""
    if min(buyer.n_defined, seller.n_defined) < MIN_DEFINED_PER_SIDE:
        return DirectionResult("INSUFFICIENT", buyer, seller)
    rates = [buyer.agreement or 0.0, seller.agreement or 0.0]
    if all(r >= FIX_MIN for r in rates):
        return DirectionResult("FIXED", buyer, seller)
    if all(r <= INVERT_MAX for r in rates):
        return DirectionResult("INVERTED", buyer, seller)
    return DirectionResult("INCONCLUSIVE", buyer, seller)


def enforce_direction(result: DirectionResult) -> DirectionResult:
    """Return ``result`` when FIXED, else raise ``StopS2`` carrying it."""
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
    """Census over per-instance prints; the first copy (sorted instance order) of a trade wins."""
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
    """Return ``counts`` unless an S1 invariant failed, then raise ``CensusViolation``."""
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
    """Per instance: Delta over its samples with ``window[0] <= ts_init < window[1]``.

    An instance with no sample in the window has NO entry (unknown, never zero).
    """
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
    """Max over instances; None (unknown, NOT zero) when no instance has a sample."""
    return max((d.delta_ns for d in per_instance.values()), default=None)


# --- Pure rules shared with the I/O layer -----------------------------------------------
def station_day_key(
    instrument_id: InstrumentId, days: Collection[dt.date], stations: Collection[str]
) -> StationDay | None:
    """``(station, day)`` for an in-scope YES-leg maker instrument, else None.

    Applies the S1 licence (``admit_print``: maker stations only, declared days only) BEFORE
    anything is counted, so NYC and undeclared days vanish unrecorded.
    """
    if leg_of(instrument_id) != "yes":
        return None
    facts = bucket_facts_from_instrument_id(str(instrument_id))
    if facts is None or not core.admit_print(
        facts.settlement_station, facts.climate_day, days, stations
    ):
        return None
    return (facts.settlement_station, facts.climate_day)


def mid_of(depth: OrderBookDepth10) -> Decimal | None:
    """Top-of-book YES mid, or None when either side of the book is empty."""
    bid, ask = depth.bids[0], depth.asks[0]
    if bid.size.as_double() <= 0 or ask.size.as_double() <= 0:
        return None
    return (Decimal(str(bid.price)) + Decimal(str(ask.price))) / 2


def listing_abstain(listing_ns: int | None, window_start_ns: int) -> bool:
    """True when never listed, or listed after the window opens (D-1 12:00Z).

    ``listing_ns`` is the earliest ``BinaryOption.ts_init`` of the station-day, the same field
    S1 uses for ``first_seen_ns`` (``scripts/analysis/maker_tape_census.py:147``): the
    recorder's receipt of the definition, so a late boot errs toward abstaining.
    """
    return listing_ns is None or listing_ns > window_start_ns


def ladder_parity(
    rungs_by_station_day: Mapping[StationDay, Collection[str]], stations: Sequence[str]
) -> dict[str, dict[str, object]]:
    """Per station: how many station-days carry N rungs; ``uniform`` if N never varies."""
    out: dict[str, dict[str, object]] = {}
    for station in stations:
        sizes: dict[str, int] = defaultdict(int)
        for (st, _day), rungs in rungs_by_station_day.items():
            if st == station and rungs:
                sizes[str(len(rungs))] += 1
        out[station] = {"rungs_per_day": dict(sorted(sizes.items())), "uniform": len(sizes) <= 1}
    return out


def distribution(values: Sequence[int]) -> dict[str, int | None]:
    """n / min / p50 (median_low) / p95 (nearest rank) / max; None-valued when empty."""
    ordered = sorted(values)
    if not ordered:
        return {"n": 0, "min": None, "p50": None, "p95": None, "max": None}
    rank = -(-_P95_PERCENT * len(ordered) // 100)  # ceil(0.95 n), integer arithmetic
    return {
        "n": len(ordered),
        "min": ordered[0],
        "p50": int(statistics.median_low(ordered)),
        "p95": ordered[rank - 1],
        "max": ordered[-1],
    }


@dataclass(frozen=True, slots=True)
class StationDayCoverage:
    """One station-day. ``live_hours``/``gap_overlap_hours``/``delta_ns`` are on the process-live
    (bid-live) window; the ``maker_*`` hours are the S1 maker window, a separate labelled column."""

    station: str
    climate_day: str
    live_hours: float
    gap_overlap_hours: float
    listing_ns: int | None
    listing_abstain: bool  # no listing, or listed after D-1 12:00Z
    delta_ns: int | None  # None = unknown (no sample in the window), never 0
    maker_live_hours: float = 0.0
    maker_gap_overlap_hours: float = 0.0


def hours(intervals: Iterable[tuple[int, int]]) -> float:
    """Total length of ``(start_ns, end_ns)`` intervals in hours."""
    return sum(end - start for start, end in intervals) / _HOUR_NS


def live_and_gap_hours(
    span: tuple[int, int], spans: Sequence[core.AliveSpan]
) -> tuple[float, float]:
    """``(live, gap_overlap)`` hours inside ``span``: alive-span union, and the part of it lost
    to recorded gaps."""
    live = hours(core.covered_intervals(span, [replace(s, gaps=()) for s in spans]))
    return live, live - hours(core.covered_intervals(span, spans))


def unique_prints(prints: Mapping[str, Sequence[core.PrintRecord]]) -> list[core.PrintRecord]:
    """First-wins dedupe on trade_id in sorted instance order (as ``count_census``)."""
    first: dict[str, core.PrintRecord] = {}
    for instance in sorted(prints):
        for record in prints[instance]:
            first.setdefault(record.trade_id, record)
    return list(first.values())
