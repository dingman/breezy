"""TE-2 loss taxonomy: per-fill descriptors, classifier, K1b and S0-D logic (pure).

WP0 stub: bodies raise NotImplementedError.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

PIT_TAIL_LOW: Final = 0.05
PIT_TAIL_HIGH: Final = 0.95
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


def edge_distance(instrument_id: str, tmax_f: int) -> int:
    raise NotImplementedError


def pit_midpoint(pmf: Mapping[int, float], tmax_f: int) -> float:
    raise NotImplementedError


def is_boundary(edge_dist: int, pit: float) -> bool:
    raise NotImplementedError


def is_tail(pit: float) -> bool:
    raise NotImplementedError


def classify_fills(fills: Sequence[FillFacts]) -> dict[str, FillClass]:
    raise NotImplementedError


def station_day_k7_count(fills: Sequence[FillFacts]) -> int:
    raise NotImplementedError


def k1b_flags(
    fill_keys: Sequence[tuple[str, str, dt.date]], terminal_climate_day: dt.date
) -> K1bResult:
    raise NotImplementedError


def s0d_compare(
    logged: Mapping[str, float],
    reproduced: Mapping[str, float | None],
    *,
    tol: float = S0D_TOLERANCE,
) -> S0DComparison:
    raise NotImplementedError


def classify_s0d_miss(
    *,
    bulletin_available: bool,
    bulletin_reissued: bool,
    cycle_selection_matches: bool,
    delta_survives_root_cause: bool,
) -> S0DMiss:
    """UNTESTABLE, then CYCLE_AMBIGUOUS, then K1A; a delta that does not survive is NO_DEFECT."""
    raise NotImplementedError


def reproduction_gate(
    per_fill_match: Sequence[bool | None], *, minimum: int = S0D_MIN_MATCH
) -> GateResult:
    raise NotImplementedError
