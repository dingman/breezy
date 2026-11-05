"""The pinned NBP store/reader behind the p_NO loader, ported from `maker_stage0_pno_store`.

Reads ONLY the three NBP cycles that can feed climate day D (amendment 1): 13Z and 19Z of
D-1 and 01Z of D, first MAX column only. ``PNoStore`` holds those rows and computes the spec
section 3 per-rung ``PYes`` (calibration loaded, never refit). Logic is the Stage 0 store's, line
for line; the evaluation API (``classify_p_no``) lives in ``pno``.
"""

from __future__ import annotations

import bisect
import datetime as dt
import functools
import logging
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal, NamedTuple, Protocol

import pyarrow as pa

from breezy.domain.forecast_point import MINIMUM_PUBLICATION_LAG_NS
from breezy.ingest.nbm_quantile_actor import DEFAULT_NBM_QUANTILE_TIMER_INTERVAL_SECONDS
from breezy.normalize.climate_day import local_standard_date
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
VENUE: Final = "polymarket_us"
UNKNOWN_ERA: Final = "unknown_era"
NONFINITE_P_YES: Final = "nonfinite_p_yes"
_NS: Final = 10**9
_PLUS60_NS: Final = 3600 * _NS
END_OF_TIME_NS: Final = 2**62
_POLL_LAG_NS: Final = DEFAULT_NBM_QUANTILE_TIMER_INTERVAL_SECONDS * _NS
PUBLICATION_LAG_FLOOR_NS: Final[int] = MINIMUM_PUBLICATION_LAG_NS["NBM_NBP"]


class DerivedNbpRow(Protocol):
    """The fields of a derived NBP row this store reads (``persistence.nbp_derived_store``'s row).

    Structural on purpose: the layering contract bars ``strategy`` from importing the derived
    store, so disk access arrives through ``PartitionSource`` and rows through this protocol.
    """

    @property
    def station(self) -> str: ...
    @property
    def variable(self) -> str: ...
    @property
    def value_f(self) -> float | None: ...
    @property
    def available_at_ns(self) -> int: ...
    @property
    def cycle_runtime_ns(self) -> int: ...
    @property
    def valid_start_ns(self) -> int: ...
    @property
    def valid_end_ns(self) -> int: ...
    @property
    def nbm_version_era(self) -> str: ...
    @property
    def raw_sha256(self) -> str: ...


class PartitionSource(Protocol):
    """Where the pinned NBP partitions live (offline replay/parity only; live feeds the state)."""

    def partition_path(self, cycle_date: dt.date, hour: int) -> Path: ...

    def read_partition(self, path: Path) -> Sequence[DerivedNbpRow]: ...


class StationRefusedError(ValueError):
    """The station is outside LAX/MDW/MIA/SFO (NYC is refused)."""


class StationDayNotLoadedError(LookupError):
    """``(station, day)`` was not passed to ``PNoStore.from_source``."""

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


def read_pinned(source: PartitionSource, icao: str, day: dt.date) -> PinnedRead:
    """First-MAX-column rows of the three pinned cycles for ``icao``.

    A missing partition is logged and reported in ``missing``; an unreadable one raises
    ``PNoStoreReadError`` naming the path.
    """
    rows: list[DerivedNbpRow] = []
    consumed: set[tuple[int, str]] = set()
    missing: set[tuple[dt.date, int]] = set()
    for cycle_date, hour in _pinned(day):
        path = source.partition_path(cycle_date, hour)
        if not path.exists():
            _log.warning("NBP partition missing: %s", path)
            missing.add((cycle_date, hour))
            continue
        try:
            partition = source.read_partition(path)
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


@dataclass(frozen=True, slots=True)
class VectorChain:
    """Every complete vector a station-day can serve, newest first, for O(log n) lookup.

    ``ForecastQuantileState.value_at(now)`` is the newest complete vector with
    ``available_at_ns <= now``. Walking ``value_at(v.available_at_ns - 1)`` from the newest visits
    exactly the vectors that can ever be that answer, so ``at`` returns what ``value_at`` returns.
    ``releases`` is the sorted ``available_at_ns`` of those for the station-day's own climate day.
    """

    available_at_ns: tuple[int, ...]  # ascending
    vectors: tuple[ForecastQuantileVector, ...]  # aligned with available_at_ns
    releases: tuple[int, ...]

    def at(self, now_ns: int) -> ForecastQuantileVector | None:
        i = bisect.bisect_right(self.available_at_ns, now_ns)
        return self.vectors[i - 1] if i else None


def build_chain(state: ForecastQuantileState, climate_day: dt.date) -> VectorChain:
    newest_first: list[ForecastQuantileVector] = []
    vector = state.value_at(END_OF_TIME_NS)
    while vector is not None:
        newest_first.append(vector)
        vector = state.value_at(vector.available_at_ns - 1)
    vectors = tuple(reversed(newest_first))
    releases = {v.available_at_ns for v in vectors if v.climate_day == climate_day}
    return VectorChain(tuple(v.available_at_ns for v in vectors), vectors, tuple(sorted(releases)))


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
        self._chains: dict[tuple[str, dt.date, Stress], VectorChain] = {}
        self._points: dict[tuple[str, dt.date, int], Mapping[str, float]] = {}
        self.abstentions: set[tuple[str, dt.date, Stress, str]] = set()
        self.abstention_counts: Counter[tuple[Stress, str]] = Counter()
        self.served: set[tuple[str, dt.date, Stress]] = set()

    @classmethod
    def from_source(
        cls,
        source: PartitionSource,
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
                read = read_pinned(source, icao, day)
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

    def vector_chain(self, station: str, day: dt.date, stress: Stress) -> VectorChain:
        key = (station, day, stress)
        if key not in self._chains:
            self._chains[key] = build_chain(self.state(station, day, stress), day)
        return self._chains[key]

    def p_yes_points(
        self, station: str, day: dt.date, vector: ForecastQuantileVector, p_yes: Mapping[str, PYes]
    ) -> Mapping[str, float]:
        """The shared read-only ``{rung: point}`` view of ``p_yes`` (one per cycle)."""
        key = (station, day, vector.cycle_runtime_ns)
        if key not in self._points:
            self._points[key] = MappingProxyType({k: p.point for k, p in p_yes.items()})
        return self._points[key]

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
