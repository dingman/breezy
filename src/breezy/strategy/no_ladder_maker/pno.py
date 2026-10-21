"""The calibrated p_NO evaluation API, ported from `maker_stage0_pno` (read-only, no truth).

A vector is visible only when ``available_at_ns`` is STRICTLY before the decision instant
(look-ahead guard) and at most ``stale_h`` old; ``stale_h`` comes from ``MakerRuleParams``.
p_yes is the spec section 3 point estimate: the mean over the resolved bootstrap draws of
``rung_probability_interval``, NOT ``LiveCalibration.resolve().point``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from breezy.strategy.ladder_ev.forecast_state import ForecastQuantileVector
from breezy.strategy.no_ladder_maker.pno_store import PNoStore, PYes, Stress, site

__all__ = [
    "FORECAST_DAY_MISMATCH",
    "FORECAST_NOT_YET_AVAILABLE",
    "FORECAST_STALE",
    "NO_VECTOR",
    "AbstainReason",
    "PNoAtInstant",
    "PNoStore",
    "classify_p_no",
    "release_instants",
]

_NS: Final = 10**9
NO_VECTOR: Final = "no_vector"
FORECAST_DAY_MISMATCH: Final = "forecast_day_mismatch"
FORECAST_STALE: Final = "forecast_stale"
FORECAST_NOT_YET_AVAILABLE: Final = "forecast_not_yet_available"


@dataclass(frozen=True, slots=True)
class AbstainReason:
    """Why no forecast is served for one (station, climate day, stress) call."""

    reason: str
    station: str
    climate_day: dt.date
    stress: Stress


@dataclass(frozen=True, slots=True)
class PNoAtInstant:
    """The calibrated forecast visible at one decision instant.

    ``p_yes_point_live`` is the spec §3 point estimate per rung (the maker rule trades on it);
    ``bounds`` are the YES-side ``(point, lower, upper)`` triples, recorded only.
    """

    p_yes_point_live: Mapping[str, float]
    bounds: Mapping[str, PYes]
    cycle: int
    available_at_ns: int
    vintage_age_s: float
    vector: ForecastQuantileVector

    def p_no(self, rung_id: str) -> float:
        return 1.0 - self.p_yes_point_live[rung_id]


def release_instants(
    store: PNoStore, station: str, climate_day: dt.date, *, stress: Stress
) -> tuple[int, ...]:
    """Sorted (stress-shifted) ``available_at_ns`` of every complete vector for the station-day.

    For WP6: schedule a forecast-release decision event at each so a resting bid is cancelled
    the instant a new vector drops p_NO below P_MIN.
    """
    return store.vector_chain(station, climate_day, stress).releases


def _abstain_reason(
    vector: ForecastQuantileVector | None, day: dt.date, now_ns: int, stale_h: int
) -> str | None:
    if vector is None:
        return NO_VECTOR
    if vector.climate_day != day:
        return FORECAST_DAY_MISMATCH
    return FORECAST_STALE if now_ns - vector.available_at_ns > stale_h * 3600 * _NS else None


def classify_p_no(
    store: PNoStore,
    station: str,
    climate_day: dt.date,
    decision_ts_ns: int,
    *,
    stress: Stress,
    stale_h: int,
) -> PNoAtInstant | AbstainReason:
    """The calibrated forecast for ``climate_day`` visible at ``decision_ts_ns``, or the reason.

    CONTRACT: ``decision_ts_ns`` is the instant the bid was posted/repriced (the decision),
    NEVER a fill or later book instant. Every abstention is
    recorded in ``store.abstentions`` / ``store.abstention_counts``, keyed by stress.
    """
    site(station)  # refuses NYC before any lookup
    chain = store.vector_chain(station, climate_day, stress)  # raises for an unloaded station-day
    vector = chain.at(decision_ts_ns - 1)
    reason = _abstain_reason(vector, climate_day, decision_ts_ns, stale_h)
    if reason == NO_VECTOR and chain.releases and chain.releases[-1] >= decision_ts_ns:
        reason = FORECAST_NOT_YET_AVAILABLE
    p_yes: Mapping[str, PYes] | str = ""
    if reason is None and vector is not None:
        p_yes = store.p_yes(station, climate_day, vector)
        reason = p_yes if isinstance(p_yes, str) else None
    if reason is not None or vector is None or isinstance(p_yes, str):
        reason = reason or NO_VECTOR
        store.abstentions.add((station, climate_day, stress, reason))
        store.abstention_counts[(stress, reason)] += 1
        return AbstainReason(reason, station, climate_day, stress)
    store.served.add((station, climate_day, stress))
    return PNoAtInstant(
        p_yes_point_live=store.p_yes_points(station, climate_day, vector, p_yes),
        bounds=p_yes,
        cycle=vector.cycle_runtime_ns,
        available_at_ns=vector.available_at_ns,
        vintage_age_s=(decision_ts_ns - vector.available_at_ns) / _NS,
        vector=vector,
    )
