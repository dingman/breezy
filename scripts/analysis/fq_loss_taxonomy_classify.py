"""TE-2 loss taxonomy: per-fill descriptors, classifier, K1b and S0-D logic (pure).

Plan: TE-2_plan_r3_2.md sections 3 and 4. Band geometry comes only from
``bucket_facts_from_instrument_id`` (inclusive [A, B] bands).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from scripts.analysis.fq_loss_taxonomy_stats import PIT_TAIL_HIGH, PIT_TAIL_LOW, pit_midpoint_of

PIT_CENTRAL_LOW: Final = 0.10
PIT_CENTRAL_HIGH: Final = 0.90
S0D_MIN_MATCH: Final = 23
S0D_TOLERANCE: Final = 1e-9


class FillClass(StrEnum):
    """Primary class in pinned precedence order, then the UNTESTABLE marker.

    UNTESTABLE is a flag (K7 needs a complete partition), not a primary class: it is carried in
    the same mapping only so a fill is never silently reclassified as BODY_MISS.
    """

    WIN = "WIN"
    SIBLING_WON = "SIBLING_WON"
    BOUNDARY = "BOUNDARY"
    TAIL = "TAIL"
    BAND_SELECTION = "BAND_SELECTION"
    BODY_MISS = "BODY_MISS"
    UNTESTABLE = "UNTESTABLE"


class S0DMiss(StrEnum):
    K1A = "K1a"
    UNTESTABLE = "UNTESTABLE"
    CYCLE_AMBIGUOUS = "CYCLE_AMBIGUOUS"
    NO_DEFECT = "NO_DEFECT"


@dataclass(frozen=True)
class FillFacts:
    fill_id: str
    station: str
    climate_day: dt.date
    edge_dist: int
    pit: float
    won: bool
    partition_complete: bool = True


@dataclass(frozen=True)
class K1bResult:
    flagged_fill_ids: tuple[str, ...]
    flagged_station_days: frozenset[tuple[str, dt.date]]
    in_scope_station_days: tuple[tuple[str, dt.date], ...]


@dataclass(frozen=True)
class GateResult:
    n_match: int
    n_total: int
    passed: bool


@dataclass(frozen=True)
class S0DComparison:
    n_match: int
    mismatched_fill_ids: tuple[str, ...]


class UnparseableInstrument(ValueError):
    """The instrument id has no weather-bucket facts (never silently skipped)."""


def edge_distance(instrument_id: str, tmax_f: int) -> int:
    """Integer degF from ``tmax_f`` to the nearest edge of the bought inclusive interval.

    0 inside the interval; an open side is never the nearest edge. A ``^no`` leg uses the YES
    interval (the id carries the same slug).
    """
    facts = bucket_facts_from_instrument_id(instrument_id)
    if facts is None:
        raise UnparseableInstrument(instrument_id)
    lower, upper = facts.lower_f, facts.upper_f
    if lower is not None and tmax_f < lower:
        return lower - tmax_f
    if upper is not None and tmax_f > upper:
        return tmax_f - upper
    return 0


def pit_midpoint(pmf: Mapping[int, float], tmax_f: int) -> float:
    return pit_midpoint_of(pmf, tmax_f)


def is_tail(pit: float) -> bool:
    return not PIT_TAIL_LOW <= pit <= PIT_TAIL_HIGH


def is_boundary(edge_dist: int, pit: float) -> bool:
    return edge_dist == 1 and not is_tail(pit)


def _is_central(pit: float) -> bool:
    return PIT_CENTRAL_LOW <= pit <= PIT_CENTRAL_HIGH


def _station_days(fills: Sequence[FillFacts]) -> dict[tuple[str, dt.date], list[FillFacts]]:
    grouped: dict[tuple[str, dt.date], list[FillFacts]] = {}
    for fill in fills:
        grouped.setdefault((fill.station, fill.climate_day), []).append(fill)
    return grouped


def _classify_loser(fill: FillFacts, day_fills: Sequence[FillFacts]) -> FillClass:
    if any(f.won for f in day_fills):
        return FillClass.SIBLING_WON
    if is_boundary(fill.edge_dist, fill.pit):
        return FillClass.BOUNDARY
    if is_tail(fill.pit):
        return FillClass.TAIL
    if len(day_fills) >= 2 and _is_central(fill.pit):
        complete = all(f.partition_complete for f in day_fills)
        return FillClass.BAND_SELECTION if complete else FillClass.UNTESTABLE
    return FillClass.BODY_MISS


def classify_fills(fills: Sequence[FillFacts]) -> dict[str, FillClass]:
    """The primary class per fill, first match wins: WIN, SIBLING_WON, BOUNDARY, TAIL,
    BAND_SELECTION, BODY_MISS. K7 needs a complete partition, else the fill is UNTESTABLE."""
    grouped = _station_days(fills)
    return {
        f.fill_id: FillClass.WIN
        if f.won
        else _classify_loser(f, grouped[(f.station, f.climate_day)])
        for f in fills
    }


def station_day_k7_count(fills: Sequence[FillFacts]) -> int:
    """Station-days holding at least one BAND_SELECTION fill."""
    classes = classify_fills(fills)
    return sum(
        1
        for day_fills in _station_days(fills).values()
        if any(classes[f.fill_id] is FillClass.BAND_SELECTION for f in day_fills)
    )


def k1b_flags(
    fill_keys: Sequence[tuple[str, str, dt.date]], terminal_climate_day: dt.date
) -> K1bResult:
    """K1b: fills past the (post-hoc) terminal climate day; in-scope days exclude them."""
    flagged = [key for key in fill_keys if key[2] > terminal_climate_day]
    days = sorted({(station, day) for _fid, station, day in fill_keys})
    flagged_days = frozenset((station, day) for _fid, station, day in flagged)
    return K1bResult(
        flagged_fill_ids=tuple(fid for fid, _s, _d in flagged),
        flagged_station_days=flagged_days,
        in_scope_station_days=tuple(sd for sd in days if sd not in flagged_days),
    )


def s0d_compare(
    logged: Mapping[str, float],
    reproduced: Mapping[str, float | None],
    *,
    tol: float = S0D_TOLERANCE,
) -> S0DComparison:
    """A fill matches iff its reproduced p-hat exists and is within ``tol`` of the logged one."""
    mismatched = []
    for fill_id, value in logged.items():
        got = reproduced.get(fill_id)
        if got is None or abs(got - value) > tol:
            mismatched.append(fill_id)
    return S0DComparison(
        n_match=len(logged) - len(mismatched), mismatched_fill_ids=tuple(mismatched)
    )


def classify_s0d_miss(
    *,
    bulletin_available: bool,
    bulletin_reissued: bool,
    cycle_selection_matches: bool,
    delta_survives_root_cause: bool,
) -> S0DMiss:
    """UNTESTABLE, then CYCLE_AMBIGUOUS, then K1A; a delta that does not survive is NO_DEFECT."""
    if not bulletin_available or bulletin_reissued:
        return S0DMiss.UNTESTABLE
    if not cycle_selection_matches:
        return S0DMiss.CYCLE_AMBIGUOUS
    return S0DMiss.K1A if delta_survives_root_cause else S0DMiss.NO_DEFECT


def reproduction_gate(
    per_fill_match: Sequence[bool | None], *, minimum: int = S0D_MIN_MATCH
) -> GateResult:
    """STOP below ``minimum`` matches; ``None`` (UNTESTABLE) counts as a non-match."""
    n_match = sum(1 for m in per_fill_match if m is True)
    return GateResult(n_match=n_match, n_total=len(per_fill_match), passed=n_match >= minimum)
