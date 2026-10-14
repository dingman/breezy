"""MAKER-S2 WP2 -- the calibrated p_NO loader (offline, read-only, no truth).

Reads ONLY the three NBP cycles that can feed climate day D (amendment §1): 13Z and 19Z of
D-1 and 01Z of D, for LAX/MDW/MIA/SFO. Each contributes its FIRST MAX column only (the actor's
D+1 filter), pushed into ``ForecastQuantileState`` with its own ``available_at_ns``. A vector is
visible only when ``available_at_ns`` is STRICTLY before the decision instant (look-ahead guard)
and at most ``STALE_H`` old.

p_yes is the live point estimate: the mean over the resolved bootstrap draws of
``rung_probability_interval`` -- what ``ArtefactBoundsProvider`` wraps and ``decision.evaluate``
trades on (``F(hi + .5) - F(lo - .5)``), NOT ``LiveCalibration.resolve().point``. The calibration
is loaded, never refit.

Report-only stresses: ``plus60`` delays floor-governed rows by 60 min (P2); ``poll_lag`` delays
EVERY ``available_at_ns`` by the imported actor poll interval.

A 07Z cycle is moot: 07Z D-1 arrives about 08:10Z and is 8 h stale at about 16:10Z, before the
16:50Z launch (08:10 + 8:00 < 16:50); 07Z D arrives after the 02:50Z permit end; a late 13Z (max
137 min, valid by 15:17Z) is also pre-launch. The live-side bias runs the other way (replay
``available_at`` = Last-Modified / floor); ``poll_lag`` measures it. No truth module is imported.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, NamedTuple

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
    rung_probability_interval,
)
from scripts.analysis.forecast_climate_day_map import climate_day_for_txn

Stress = Literal["none", "plus60", "poll_lag"]

STATIONS: Final = ("LAX", "MDW", "MIA", "SFO")
STALE_H: Final = 8
VERIFY_FIRST_DAY: Final = dt.date(2026, 6, 30)
VENUE: Final = "polymarket_us"
_NS: Final = 10**9
_PLUS60_NS: Final = 3600 * _NS
_POLL_LAG_NS: Final = DEFAULT_NBM_QUANTILE_TIMER_INTERVAL_SECONDS * _NS
_STALE_NS: Final = STALE_H * 3600 * _NS
_TOLERANCE_MIN: Final = 30.0
#: Spec §3.1 p50 ages (min) at 16:50Z D-1, 00:00Z D, 02:50Z D (avail 14:04Z, 20:17Z, 02:04Z).
_EXPECTED_AGE_MIN: Final = (("16:50Z D-1", -1, 16, 50, 166.0), ("00:00Z D", 0, 0, 0, 223.0),
                            ("02:50Z D", 0, 2, 50, 46.0))  # fmt: skip


class StationRefusedError(ValueError):
    """The station is outside LAX/MDW/MIA/SFO (NYC is refused)."""


class PYes(NamedTuple):
    point: float
    lower: float
    upper: float


@dataclass(frozen=True, slots=True)
class PNoAtInstant:
    """The calibrated forecast visible at one decision instant.

    ``p_yes_point_live`` is the live point estimate per rung; ``bounds`` is
    recorded only (spec §3: the point estimate defines P_MIN/b_max/§6.9).
    """

    p_yes_point_live: Mapping[str, float]
    bounds: Mapping[str, PYes]
    cycle: int
    available_at_ns: int
    vintage_age_s: float
    vector: ForecastQuantileVector

    def p_no(self, rung_id: str) -> float:
        return 1.0 - self.p_yes_point_live[rung_id]


class _Site(NamedTuple):
    icao: str
    offset_hours: float
    latitude_deg: float


def _site(station: str) -> _Site:
    if station not in STATIONS:
        raise StationRefusedError(f"{station!r} is not one of {STATIONS}")
    registry = default_registry()
    return _Site(
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
    latest_first = sorted(rows, key=lambda r: r.valid_start_ns, reverse=True)
    return list({row.variable: row for row in latest_first}.values())


def _delay_ns(row: DerivedNbpRow, stress: Stress) -> int:
    if stress == "poll_lag":
        return _POLL_LAG_NS
    floor_governed = row.available_at_ns == row.cycle_runtime_ns + PUBLICATION_LAG_FLOOR_NS
    return _PLUS60_NS if stress == "plus60" and floor_governed else 0


def _build_state(
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


def _read_pinned(
    root: Path, icao: str, day: dt.date
) -> tuple[list[DerivedNbpRow], set[tuple[int, str]]]:
    """First-MAX-column rows of the three pinned cycles for ``icao`` (missing files skipped)."""
    rows: list[DerivedNbpRow] = []
    consumed: set[tuple[int, str]] = set()
    for cycle_date, hour in _pinned(day):
        path = partition_path(root, cycle_date, hour)
        if not path.exists():
            continue
        mine = [
            r for r in read_partition(path)
            if r.station == icao and _cycle_key(r.cycle_runtime_ns) == (cycle_date, hour)
        ]  # fmt: skip
        kept = _first_max_column(mine)
        rows.extend(kept)
        consumed.update((r.cycle_runtime_ns, r.raw_sha256) for r in kept)
    return rows, consumed


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


def ladder_p_yes(
    vector: ForecastQuantileVector,
    ladder: Sequence[Rung],
    calibration: LiveCalibration,
    latitude_deg: float,
) -> dict[str, PYes]:
    """Per-rung ``PYes`` via ``rung_probability_interval`` over ``resolve(...).draws``.

    A non-partition ladder falls back to each rung's complement ladder. An unknown NBM era
    raises ``CalibrationArtefactUnknownVersionError`` (never pooled).
    """
    resolved = calibration.resolve(
        vector.model_version, latitude_deg=latitude_deg, climate_day=vector.climate_day
    )
    pct, method = _percentiles(vector), calibration.cdf_method
    try:  # a partition ladder is evaluated whole
        interval = rung_probability_interval(pct, method, resolved.draws, ladder)
    except ValueError:
        interval = {
            rung.rung_id: rung_probability_interval(pct, method, resolved.draws, _complement(rung))[
                rung.rung_id
            ]
            for rung in ladder
        }
    return {rung_id: PYes(*triple) for rung_id, triple in interval.items()}


class PNoStore:
    """Pinned-cycle rows for the requested station-days, calibration and ladders."""

    def __init__(
        self,
        rows: Mapping[tuple[str, dt.date], Sequence[DerivedNbpRow]],
        consumed: frozenset[tuple[int, str]],
        calibration: LiveCalibration,
        ladders: Mapping[tuple[str, dt.date], Sequence[Rung]],
    ) -> None:
        self._rows, self._consumed = rows, consumed
        self._calibration, self._ladders = calibration, ladders
        self._states: dict[tuple[str, dt.date, Stress], ForecastQuantileState] = {}
        self._p_yes: dict[tuple[str, dt.date, int], dict[str, PYes] | None] = {}
        self.abstentions: Counter[str] = Counter()

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
        for station in stations:
            site = _site(station)  # refuses NYC
            for day in days:
                if (station, day) not in ladders:
                    raise ValueError(f"no rung ladder supplied for {station} {day}")
                rows[(station, day)], seen = _read_pinned(nbp_root, site.icao, day)
                consumed |= seen
        return cls(rows, frozenset(consumed), calibration, ladders)

    def consumed_cycles(self) -> frozenset[tuple[int, str]]:
        """``(cycle_runtime_ns, raw_sha256)`` of every cycle read (for ``pin_inputs``)."""
        return self._consumed

    def state(self, station: str, day: dt.date, stress: Stress) -> ForecastQuantileState:
        key = (station, day, stress)
        if key not in self._states:
            offset = _site(station).offset_hours
            self._states[key] = _build_state(self._rows[(station, day)], offset, stress)
        return self._states[key]

    def p_yes(
        self, station: str, day: dt.date, vector: ForecastQuantileVector
    ) -> dict[str, PYes] | None:
        key = (station, day, vector.cycle_runtime_ns)
        if key not in self._p_yes:
            try:
                self._p_yes[key] = ladder_p_yes(
                    vector, self._ladders[(station, day)], self._calibration,
                    _site(station).latitude_deg,
                )  # fmt: skip
            except CalibrationArtefactUnknownVersionError:
                self._p_yes[key] = None
        return self._p_yes[key]


def _abstain_reason(vector: ForecastQuantileVector | None, day: dt.date, now_ns: int) -> str | None:
    if vector is None:
        return "no_vector"
    if vector.climate_day != day:
        return "forecast_day_mismatch"
    return "forecast_stale" if now_ns - vector.available_at_ns > _STALE_NS else None


def load_p_no(
    store: PNoStore,
    station: str,
    climate_day: dt.date,
    decision_ts_ns: int,
    *,
    stress: Stress,
) -> PNoAtInstant | None:
    """The calibrated forecast for ``climate_day`` visible at ``decision_ts_ns``, or ``None``.

    Abstentions are counted in ``store.abstentions`` (``no_vector``,
    ``forecast_day_mismatch``, ``forecast_stale``, ``unknown_era``), never pooled.
    """
    _site(station)
    vector = store.state(station, climate_day, stress).value_at(decision_ts_ns - 1)
    reason = _abstain_reason(vector, climate_day, decision_ts_ns)
    if vector is None or reason is not None:
        store.abstentions[reason or "no_vector"] += 1
        return None
    p_yes = store.p_yes(station, climate_day, vector)
    if p_yes is None:
        store.abstentions["unknown_era"] += 1
        return None
    return PNoAtInstant(
        p_yes_point_live={rung_id: p.point for rung_id, p in p_yes.items()},
        bounds=p_yes,
        cycle=vector.cycle_runtime_ns,
        available_at_ns=vector.available_at_ns,
        vintage_age_s=(decision_ts_ns - vector.available_at_ns) / _NS,
        vector=vector,
    )


@dataclass(frozen=True, slots=True)
class AlignmentLine:
    station: str
    cycle_ns: int
    max_column_climate_day: dt.date
    txn_climate_day: dt.date
    matches_climate_day_for_txn: bool


@dataclass(frozen=True, slots=True)
class VintageAgeLine:
    station: str
    instant: str
    cycle_ns: int | None
    age_min: float | None
    expected_age_min: float
    within_tolerance: bool


@dataclass(frozen=True, slots=True)
class VerifyFirstReport:
    climate_day: dt.date
    alignment: tuple[AlignmentLine, ...]
    vintage_age: tuple[VintageAgeLine, ...]


def _alignment(
    rows: Sequence[DerivedNbpRow], station: str, site: _Site, day: dt.date
) -> list[AlignmentLine]:
    lines: list[AlignmentLine] = []
    for row in rows:
        if row.variable != "TXN_Q50":
            continue
        mapped = local_standard_date(row.valid_end_ns, site.offset_hours)
        txn_day = climate_day_for_txn(
            icao=site.icao, runtime_ns=row.cycle_runtime_ns, ftime_ns=row.valid_end_ns,
            std_utc_offset_hours=site.offset_hours, model="NBM_NBP", kind="max",
        )  # fmt: skip
        lines.append(
            AlignmentLine(station, row.cycle_runtime_ns, mapped, txn_day, mapped == txn_day)
        )
    return lines


def _ages(state: ForecastQuantileState, station: str, day: dt.date) -> list[VintageAgeLine]:
    lines: list[VintageAgeLine] = []
    for label, day_offset, hour, minute, expected in _EXPECTED_AGE_MIN:
        instant = dt.datetime(day.year, day.month, day.day, hour, minute, tzinfo=dt.UTC)
        now_ns = int((instant + dt.timedelta(days=day_offset)).timestamp()) * _NS
        vector = state.value_at(now_ns - 1)
        age = None if vector is None else (now_ns - vector.available_at_ns) / _NS / 60.0
        cycle = None if vector is None else vector.cycle_runtime_ns
        ok = age is not None and abs(age - expected) <= _TOLERANCE_MIN
        lines.append(VintageAgeLine(station, label, cycle, age, expected, ok))
    return lines


def verify_first_s6(nbp_root: Path, climate_day: dt.date) -> VerifyFirstReport:
    """S-6 verify-first: alignment and vintage-age lines only, never a fill/bid/p_no.

    Runs only on 2026-06-30 (amendment §1 item 3); the simulator never calls it.
    """
    if climate_day != VERIFY_FIRST_DAY:
        raise ValueError(
            f"verify-first runs only on {VERIFY_FIRST_DAY.isoformat()}, got {climate_day}"
        )
    alignment: list[AlignmentLine] = []
    ages: list[VintageAgeLine] = []
    for station in STATIONS:
        site = _site(station)
        rows, _ = _read_pinned(nbp_root, site.icao, climate_day)
        alignment += _alignment(rows, station, site, climate_day)
        ages += _ages(_build_state(rows, site.offset_hours, "none"), station, climate_day)
    return VerifyFirstReport(climate_day, tuple(alignment), tuple(ages))
