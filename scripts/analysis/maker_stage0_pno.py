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
import functools
import logging
import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal, NamedTuple

import pyarrow as pa

from breezy.ingest.nbm_quantile_actor import DEFAULT_NBM_QUANTILE_TIMER_INTERVAL_SECONDS
from breezy.normalize.climate_day import local_standard_date
from breezy.persistence.nbp_derived_store import (
    PUBLICATION_LAG_FLOOR_NS,
    DerivedNbpRow,
    partition_path,
    read_partition,
)
from breezy.registry.sites import default_registry
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import (
    CalibrationArtefactUnknownVersionError,
    LiveCalibration,
)
from breezy.strategy.ladder_ev.forecast_state import (
    NBP_QUANTILE_VARIABLES,
    ForecastQuantileState,
    ForecastQuantileVector,
)
from breezy.strategy.ladder_ev.quantile_density import (
    Percentiles,
    Rung,
    _assert_complete_partition,
    rung_probability_interval,
)

_log = logging.getLogger(__name__)

Stress = Literal["none", "plus60", "poll_lag"]

STATIONS: Final = ("LAX", "MDW", "MIA", "SFO")
STALE_H: Final = 8
VENUE: Final = "polymarket_us"
NO_VECTOR: Final = "no_vector"
FORECAST_DAY_MISMATCH: Final = "forecast_day_mismatch"
FORECAST_STALE: Final = "forecast_stale"
UNKNOWN_ERA: Final = "unknown_era"
NONFINITE_P_YES: Final = "nonfinite_p_yes"
FORECAST_NOT_YET_AVAILABLE: Final = "forecast_not_yet_available"
_NS: Final = 10**9
_PLUS60_NS: Final = 3600 * _NS
_POLL_LAG_NS: Final = DEFAULT_NBM_QUANTILE_TIMER_INTERVAL_SECONDS * _NS
_STALE_NS: Final = STALE_H * 3600 * _NS
_END_OF_TIME_NS: Final = 2**62


class StationRefusedError(ValueError):
    """The station is outside LAX/MDW/MIA/SFO (NYC is refused)."""


class StationDayNotLoadedError(LookupError):
    """``(station, day)`` was not passed to ``PNoStore.from_root``."""

    def __init__(self, station: str, day: dt.date) -> None:
        super().__init__(f"station-day not loaded: {station} {day.isoformat()}")


class PNoStoreReadError(RuntimeError):
    """A pinned NBP partition exists but cannot be read (corrupt or unreadable)."""

    def __init__(self, path: Path) -> None:
        super().__init__(f"cannot read NBP partition {path}")


class PYes(NamedTuple):
    """YES-side ``(point, lower, upper)`` probability of one rung (95% bootstrap interval)."""

    point: float
    lower: float
    upper: float


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


class Site(NamedTuple):
    icao: str
    offset_hours: float
    latitude_deg: float


@functools.cache
def site(station: str) -> Site:
    if station not in STATIONS:
        raise StationRefusedError(f"{station!r} is not one of {STATIONS}")
    registry = default_registry()
    return Site(
        icao=registry.settlement_site(VENUE, station).icao,
        offset_hours=registry.climate_day_window(VENUE, station).std_utc_offset_hours,
        latitude_deg=registry.enrichment_coordinates(VENUE, station).lat,
    )


def _cycle_key(cycle_ns: int) -> tuple[dt.date, int]:
    stamp = dt.datetime.fromtimestamp(cycle_ns // _NS, tz=dt.UTC)
    return stamp.date(), stamp.hour


def _pinned(day: dt.date) -> tuple[tuple[dt.date, int], ...]:
    """The only cycles that may feed day D: 13Z and 19Z of D-1, 01Z of D."""
    prev = day - dt.timedelta(days=1)
    return ((prev, 13), (prev, 19), (day, 1))


def _first_max_column(rows: Sequence[DerivedNbpRow]) -> list[DerivedNbpRow]:
    # Sorted latest-first, the dict keeps the LAST row per variable = the earliest valid_start.
    latest_first = sorted(rows, key=lambda r: r.valid_start_ns, reverse=True)
    return list({row.variable: row for row in latest_first}.values())


def _delay_ns(row: DerivedNbpRow, stress: Stress) -> int:
    if stress == "poll_lag":
        return _POLL_LAG_NS
    floor_governed = row.available_at_ns == row.cycle_runtime_ns + PUBLICATION_LAG_FLOOR_NS
    return _PLUS60_NS if stress == "plus60" and floor_governed else 0


def build_state(
    rows: Sequence[DerivedNbpRow], offset: float, stress: Stress
) -> ForecastQuantileState:
    state = ForecastQuantileState()
    for row in rows:
        if row.variable in NBP_QUANTILE_VARIABLES:
            state.push(
                variable=row.variable,
                value_f=row.value_f,
                available_at_ns=row.available_at_ns + _delay_ns(row, stress),
                cycle_runtime_ns=row.cycle_runtime_ns,
                climate_day=local_standard_date(row.valid_end_ns, offset),
                model_version=row.nbm_version_era,
            )
    return state


class PinnedRead(NamedTuple):
    rows: list[DerivedNbpRow]
    consumed: set[tuple[int, str]]
    missing: set[tuple[dt.date, int]]


def read_pinned(root: Path, icao: str, day: dt.date) -> PinnedRead:
    """First-MAX-column rows of the three pinned cycles for ``icao``.

    A missing partition is logged and reported in ``missing``; an unreadable one raises
    ``PNoStoreReadError`` naming the path.
    """
    rows: list[DerivedNbpRow] = []
    consumed: set[tuple[int, str]] = set()
    missing: set[tuple[dt.date, int]] = set()
    for cycle_date, hour in _pinned(day):
        path = partition_path(root, cycle_date, hour)
        if not path.exists():
            _log.warning("NBP partition missing: %s", path)
            missing.add((cycle_date, hour))
            continue
        try:
            partition = read_partition(path)
        except (OSError, ValueError, pa.ArrowException) as exc:
            raise PNoStoreReadError(path) from exc
        mine = [
            r for r in partition
            if r.station == icao and _cycle_key(r.cycle_runtime_ns) == (cycle_date, hour)
        ]  # fmt: skip
        kept = _first_max_column(mine)
        rows.extend(kept)
        consumed.update((r.cycle_runtime_ns, r.raw_sha256) for r in kept)
    return PinnedRead(rows, consumed, missing)


def _percentiles(vector: ForecastQuantileVector) -> Percentiles:
    return Percentiles(
        q10=vector.q10, q25=vector.q25, q50=vector.q50, q75=vector.q75, q90=vector.q90,
        mean=vector.mean, sd=vector.sd,
    )  # fmt: skip


def _complement(rung: Rung) -> list[Rung]:
    ladder = [Rung(rung.rung_id, rung.lo, rung.hi)]
    if rung.lo is not None:
        ladder.append(Rung("_below", None, rung.lo - 1))
    if rung.hi is not None:
        ladder.append(Rung("_above", rung.hi + 1, None))
    return ladder


def _is_complete_partition(ladder: Sequence[Rung]) -> bool:
    try:
        _assert_complete_partition(ladder)
    except ValueError:  # the ONLY failure that selects the complement fallback
        return False
    return True


def ladder_p_yes(
    vector: ForecastQuantileVector,
    ladder: Sequence[Rung],
    calibration: LiveCalibration,
    latitude_deg: float,
) -> dict[str, PYes]:
    """Per-rung ``PYes`` via ``rung_probability_interval`` over ``resolve(...).draws``.

    A ladder that is not a complete partition falls back to each rung's complement ladder.
    Empty draws / a failed sum-to-1 check propagate; an unknown NBM era raises
    ``CalibrationArtefactUnknownVersionError`` (never pooled).
    """
    resolved = calibration.resolve(
        vector.model_version, latitude_deg=latitude_deg, climate_day=vector.climate_day
    )
    pct, method, draws = _percentiles(vector), calibration.cdf_method, resolved.draws
    if _is_complete_partition(ladder):
        interval = rung_probability_interval(pct, method, draws, ladder)
    else:
        interval = {
            rung.rung_id: rung_probability_interval(pct, method, draws, _complement(rung))[
                rung.rung_id
            ]
            for rung in ladder
        }
    return {rung_id: PYes(*triple) for rung_id, triple in interval.items()}


def p_yes_is_valid(p_yes: Mapping[str, PYes]) -> bool:
    """Every ``(point, lower, upper)`` is finite and within [0, 1]."""
    return all(math.isfinite(x) and 0.0 <= x <= 1.0 for triple in p_yes.values() for x in triple)


class PNoStore:
    """Pinned-cycle rows for the requested station-days, calibration and ladders.

    ``abstentions`` is the SET of ``(station, climate_day, stress, reason)`` ever hit;
    ``abstention_counts`` counts calls per ``(stress, reason)`` (stresses never mix);
    ``served`` is the set of ``(station, climate_day, stress)`` that got a forecast at least once.
    """

    def __init__(
        self,
        rows: Mapping[tuple[str, dt.date], Sequence[DerivedNbpRow]],
        consumed: frozenset[tuple[int, str]],
        calibration: LiveCalibration,
        ladders: Mapping[tuple[str, dt.date], Sequence[Rung]],
        missing_cycles: frozenset[tuple[dt.date, int]] = frozenset(),
    ) -> None:
        self._rows, self._consumed = rows, consumed
        self._calibration, self._ladders = calibration, ladders
        self.missing_cycles = missing_cycles
        self._states: dict[tuple[str, dt.date, Stress], ForecastQuantileState] = {}
        self._p_yes: dict[tuple[str, dt.date, int], Mapping[str, PYes] | str] = {}
        self.abstentions: set[tuple[str, dt.date, Stress, str]] = set()
        self.abstention_counts: Counter[tuple[Stress, str]] = Counter()
        self.served: set[tuple[str, dt.date, Stress]] = set()

    @classmethod
    def from_root(
        cls,
        nbp_root: Path,
        *,
        stations: Sequence[str],
        days: Sequence[dt.date],
        calibration: LiveCalibration,
        ladders: Mapping[tuple[str, dt.date], Sequence[Rung]],
    ) -> PNoStore:
        rows: dict[tuple[str, dt.date], Sequence[DerivedNbpRow]] = {}
        consumed: set[tuple[int, str]] = set()
        missing: set[tuple[dt.date, int]] = set()
        for station in stations:
            icao = site(station).icao  # refuses NYC
            for day in days:
                if (station, day) not in ladders:
                    raise ValueError(f"no rung ladder supplied for {station} {day}")
                read = read_pinned(nbp_root, icao, day)
                rows[(station, day)] = read.rows
                consumed |= read.consumed
                missing |= read.missing
        return cls(rows, frozenset(consumed), calibration, ladders, frozenset(missing))

    def consumed_cycles(self) -> frozenset[tuple[int, str]]:
        """``(cycle_runtime_ns, raw_sha256)`` of every cycle read (for ``pin_inputs``)."""
        return self._consumed

    def require_loaded(self, station: str, day: dt.date) -> None:
        if (station, day) not in self._rows:
            raise StationDayNotLoadedError(station, day)

    def state(self, station: str, day: dt.date, stress: Stress) -> ForecastQuantileState:
        self.require_loaded(station, day)
        key = (station, day, stress)
        if key not in self._states:
            self._states[key] = build_state(
                self._rows[(station, day)], site(station).offset_hours, stress
            )
        return self._states[key]

    def p_yes(
        self, station: str, day: dt.date, vector: ForecastQuantileVector
    ) -> Mapping[str, PYes] | str:
        """Immutable per-rung ``PYes``, or the abstention reason (``unknown_era``/nonfinite)."""
        key = (station, day, vector.cycle_runtime_ns)
        if key not in self._p_yes:
            self._p_yes[key] = self._compute_p_yes(station, day, vector)
        return self._p_yes[key]

    def _compute_p_yes(
        self, station: str, day: dt.date, vector: ForecastQuantileVector
    ) -> Mapping[str, PYes] | str:
        try:
            computed = ladder_p_yes(
                vector, self._ladders[(station, day)], self._calibration,
                site(station).latitude_deg,
            )  # fmt: skip
        except CalibrationArtefactUnknownVersionError:
            return UNKNOWN_ERA
        except ValueError as exc:
            raise ValueError(
                f"p_yes failed for {station} {day.isoformat()} "
                f"cycle {vector.cycle_runtime_ns}: {exc}"
            ) from exc
        return MappingProxyType(computed) if p_yes_is_valid(computed) else NONFINITE_P_YES


def release_instants(
    store: PNoStore, station: str, climate_day: dt.date, *, stress: Stress
) -> tuple[int, ...]:
    """Sorted (stress-shifted) ``available_at_ns`` of every complete vector for the station-day.

    For WP6: schedule a forecast-release decision event at each so a resting bid is cancelled
    the instant a new vector drops p_NO below P_MIN.
    """
    state = store.state(station, climate_day, stress)
    instants: set[int] = set()
    vector = state.value_at(_END_OF_TIME_NS)
    while vector is not None:
        if vector.climate_day == climate_day:
            instants.add(vector.available_at_ns)
        vector = state.value_at(vector.available_at_ns - 1)
    return tuple(sorted(instants))


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
    state = store.state(station, climate_day, stress)  # raises for an unloaded station-day
    vector = state.value_at(decision_ts_ns - 1)
    reason = _abstain_reason(vector, climate_day, decision_ts_ns)
    if reason == NO_VECTOR and any(
        t >= decision_ts_ns for t in release_instants(store, station, climate_day, stress=stress)
    ):
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
        p_yes_point_live=MappingProxyType({k: p.point for k, p in p_yes.items()}),
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
