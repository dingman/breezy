"""MAKER-S2 WP2 -- the calibrated p_NO loader (offline, read-only, no truth).

Reads ONLY the three NBP cycles that can feed climate day D (amendment §1): 13Z and 19Z of
D-1 and 01Z of D, for LAX/MDW/MIA/SFO. Each contributes its FIRST MAX column only (the actor's
D+1 filter), pushed into ``ForecastQuantileState`` with its own ``available_at_ns``. A vector is
visible only when ``available_at_ns`` is STRICTLY before the decision instant (look-ahead guard)
and at most ``STALE_H`` old (this module OWNS ``STALE_H``; downstream rules import it).

p_yes is the spec §3 point estimate (= live ``p_hat``): the mean over the resolved bootstrap
draws of ``rung_probability_interval`` (``F(hi + .5) - F(lo - .5)``), NOT
``LiveCalibration.resolve().point``. The maker rule trades on this point. The LIVE taker rule
differs: it prices NO on ``p_upper`` and YES on ``p_lower``; ``bounds`` carries those YES-side
``(point, lower, upper)`` triples for the record only. The calibration is loaded, never refit.

Report-only stresses: ``plus60`` delays floor-governed rows by 60 min (P2); ``poll_lag`` delays
EVERY ``available_at_ns`` by the imported actor poll interval. Stress shifts ``available_at``
used by the stale test too (up to 60 min fresher at the 8 h edge); that is accepted and stated.

A 07Z cycle is moot: 07Z D-1 arrives about 08:10Z and is 8 h stale at about 16:10Z, before the
16:50Z launch (08:10 + 8:00 < 16:50); 07Z D arrives after the 02:50Z permit end; a late 13Z (max
137 min, valid by 15:17Z) is also pre-launch. No truth module is imported.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from breezy.strategy.ladder_ev.forecast_state import ForecastQuantileVector
from scripts.analysis.maker_stage0_pno_store import (
    NONFINITE_P_YES,
    STATIONS,
    UNKNOWN_ERA,
    VENUE,
    PinnedRead,
    PNoStore,
    PNoStoreReadError,
    PYes,
    Site,
    StationDayNotLoadedError,
    StationRefusedError,
    Stress,
    build_state,
    ladder_p_yes,
    p_yes_is_valid,
    read_pinned,
    site,
)

__all__ = [
    "FORECAST_DAY_MISMATCH",
    "FORECAST_NOT_YET_AVAILABLE",
    "FORECAST_STALE",
    "NONFINITE_P_YES",
    "NO_VECTOR",
    "STALE_H",
    "STATIONS",
    "UNKNOWN_ERA",
    "VENUE",
    "AbstainReason",
    "PNoAtInstant",
    "PNoStore",
    "PNoStoreReadError",
    "PYes",
    "PinnedRead",
    "Site",
    "StationDayNotLoadedError",
    "StationRefusedError",
    "Stress",
    "assert_decision_before",
    "build_state",
    "classify_p_no",
    "covered_but_never_forecast_visible",
    "ladder_p_yes",
    "load_p_no",
    "p_yes_is_valid",
    "read_pinned",
    "release_instants",
    "site",
]

_NS: Final = 10**9
STALE_H: Final = 8
NO_VECTOR: Final = "no_vector"
FORECAST_DAY_MISMATCH: Final = "forecast_day_mismatch"
FORECAST_STALE: Final = "forecast_stale"
FORECAST_NOT_YET_AVAILABLE: Final = "forecast_not_yet_available"
_STALE_NS: Final = STALE_H * 3600 * _NS


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


def assert_decision_before(decision_ts_ns: int, fill_ts_ns: int) -> None:
    """Raise ``ValueError`` if a forecast decision instant is later than the fill it explains."""
    if decision_ts_ns > fill_ts_ns:
        raise ValueError(
            f"decision instant {decision_ts_ns} is after fill instant {fill_ts_ns}: p_NO must "
            "be read at the decision (post/reprice) instant, never at the fill"
        )


def _abstain_reason(vector: ForecastQuantileVector | None, day: dt.date, now_ns: int) -> str | None:
    if vector is None:
        return NO_VECTOR
    if vector.climate_day != day:
        return FORECAST_DAY_MISMATCH
    return FORECAST_STALE if now_ns - vector.available_at_ns > _STALE_NS else None


def classify_p_no(
    store: PNoStore,
    station: str,
    climate_day: dt.date,
    decision_ts_ns: int,
    *,
    stress: Stress,
) -> PNoAtInstant | AbstainReason:
    """The calibrated forecast for ``climate_day`` visible at ``decision_ts_ns``, or the reason.

    CONTRACT: ``decision_ts_ns`` is the instant the bid was posted/repriced (the decision),
    NEVER a fill or later book instant (see ``assert_decision_before``). Every abstention is
    recorded in ``store.abstentions`` / ``store.abstention_counts``, keyed by stress.
    """
    site(station)  # refuses NYC before any lookup
    chain = store.vector_chain(station, climate_day, stress)  # raises for an unloaded station-day
    vector = chain.at(decision_ts_ns - 1)
    reason = _abstain_reason(vector, climate_day, decision_ts_ns)
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


def load_p_no(
    store: PNoStore,
    station: str,
    climate_day: dt.date,
    decision_ts_ns: int,
    *,
    stress: Stress,
) -> PNoAtInstant | None:
    """``classify_p_no`` without the reason (abstentions are still recorded on the store)."""
    result = classify_p_no(store, station, climate_day, decision_ts_ns, stress=stress)
    return None if isinstance(result, AbstainReason) else result


def covered_but_never_forecast_visible(
    store: PNoStore, station_days: Iterable[tuple[str, dt.date]], *, stress: Stress
) -> frozenset[tuple[str, dt.date]]:
    """Station-days never served a forecast under ``stress`` (the shrinking denominator)."""
    return frozenset(sd for sd in station_days if (*sd, stress) not in store.served)
