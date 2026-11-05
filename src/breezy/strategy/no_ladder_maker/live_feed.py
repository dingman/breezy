"""The live NBP feed behind the maker's ``PNoStore`` (serve side of the pinned reader).

The simulator reads the three pinned NBP cycles of a station-day from disk
(``pno_store.read_pinned``). Live, the same rows arrive as ``ForecastPoint`` records on the message
bus. This module turns each record into a ``DerivedNbpRow``-shaped row, applies the SAME pin
(``pno_store._pinned``: 13Z and 19Z of D-1 and 01Z of D) and the SAME first-MAX-column rule
(``pno_store._first_max_column``), and builds a ``PNoStore`` over them. Nothing here decides a
price; the decision core (``pno``, ``selector``, ``rule``) is unchanged.

Serve-side skew guard (plan section 3, the ``nbp_late_arrival`` log). Visibility of a vector is
``max(modelled availability, actual arrival)`` BY CONSTRUCTION: the store holds only rows this
process has received, and a decision is always evaluated at the current clock, so no decision can
ever use a vector before it arrived. The row keeps its PUBLICATION instant as ``available_at_ns``
(``stress == "none"``: no extra modelled delay), so the staleness gate measures the forecast's true
age -- stamping the arrival instead would make a late or backfilled vector look younger than it is
and let a stale forecast stay tradable longer. Every arrival later than its publication is counted
and logged as ``nbp_late_arrival`` (and reported to ``on_late_arrival``).
"""

from __future__ import annotations

import datetime as dt
import logging
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from breezy.domain.forecast_point import ForecastPoint
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import LiveCalibration
from breezy.strategy.ladder_ev.forecast_state import NBP_QUANTILE_MODEL, NBP_QUANTILE_VARIABLES
from breezy.strategy.ladder_ev.quantile_density import Rung
from breezy.strategy.no_ladder_maker.pno_store import (
    DerivedNbpRow,
    PNoStore,
    _cycle_key,
    _first_max_column,
    _pinned,
)

__all__ = [
    "LATE_ARRIVAL_EVENT",
    "LiveNbpFeed",
    "LiveNbpRow",
    "PushOutcome",
]

_log = logging.getLogger(__name__)

LATE_ARRIVAL_EVENT: Final[str] = "nbp_late_arrival"
_NS: Final[int] = 10**9


@dataclass(frozen=True, slots=True)
class LiveNbpRow:
    """A ``ForecastPoint`` in the shape ``PNoStore`` reads (``pno_store.DerivedNbpRow``)."""

    station: str
    variable: str
    value_f: float | None
    available_at_ns: int
    cycle_runtime_ns: int
    valid_start_ns: int
    valid_end_ns: int
    nbm_version_era: str
    raw_sha256: str


@dataclass(frozen=True, slots=True)
class PushOutcome:
    """What one pushed record did: ``accepted`` rows change the store; ``late_ns`` > 0 = skew."""

    accepted: bool
    reason: str
    late_ns: int = 0


class LiveNbpFeed:
    """Accumulates live rows per ICAO and builds the maker's ``PNoStore`` per station.

    ``ladders`` are the (station, day) rung ladders the strategy has subscribed; ``stores`` are
    rebuilt (cheaply, lazily) whenever a new row or a changed ladder invalidates them.
    """

    def __init__(
        self,
        *,
        calibration: LiveCalibration,
        icao_by_station: Mapping[str, str],
        on_late_arrival: Callable[[str, int, int], None] | None = None,
    ) -> None:
        self._calibration = calibration
        self._icao_by_station = dict(icao_by_station)
        self._station_by_icao = {icao: s for s, icao in self._icao_by_station.items()}
        self._rows: dict[str, dict[tuple[int, str], LiveNbpRow]] = {
            icao: {} for icao in self._station_by_icao
        }
        self._ladders: dict[tuple[str, dt.date], tuple[Rung, ...]] = {}
        self._stores: dict[tuple[str, dt.date], PNoStore] = {}
        self._on_late_arrival = on_late_arrival
        self.counters: Counter[str] = Counter()

    # -- ingest -----------------------------------------------------------------------------

    def push(self, point: ForecastPoint, *, arrival_ns: int) -> PushOutcome:
        """Record one ``ForecastPoint``; never raises on a record it does not want."""
        if point.model != NBP_QUANTILE_MODEL:
            self.counters["foreign_model"] += 1
            return PushOutcome(False, "foreign_model")
        if point.variable not in NBP_QUANTILE_VARIABLES:
            self.counters["foreign_variable"] += 1
            return PushOutcome(False, "foreign_variable")
        station = self._station_by_icao.get(point.station)
        if station is None:
            self.counters["unknown_station"] += 1
            return PushOutcome(False, "unknown_station")
        if point.value_f is None:
            self.counters[f"absent_{point.absence_reason}"] += 1
            return PushOutcome(False, "absent")
        late_ns = max(0, arrival_ns - point.available_at_ns)
        row = LiveNbpRow(
            station=point.station,
            variable=point.variable,
            value_f=point.value_f,
            available_at_ns=point.available_at_ns,
            cycle_runtime_ns=point.cycle_runtime_ns,
            valid_start_ns=point.valid_start_ns,
            valid_end_ns=point.valid_end_ns,
            nbm_version_era=f"v{point.model_version}",
            raw_sha256="",
        )
        key = (point.cycle_runtime_ns, point.variable)
        known = self._rows[point.station].get(key)
        if known is not None and known.valid_start_ns <= row.valid_start_ns:
            self.counters["duplicate"] += 1
            return PushOutcome(
                False, "duplicate"
            )  # first MAX column wins; a reissue never moves it
        self._rows[point.station][key] = row
        self._stores = {k: v for k, v in self._stores.items() if k[0] != station}
        self.counters["pushed"] += 1
        if late_ns > 0:
            self.counters[LATE_ARRIVAL_EVENT] += 1
            _log.warning(
                "%s station=%s cycle_runtime_ns=%d variable=%s late_ns=%d",
                LATE_ARRIVAL_EVENT,
                station,
                point.cycle_runtime_ns,
                point.variable,
                late_ns,
            )
            if self._on_late_arrival is not None:
                self._on_late_arrival(station, point.cycle_runtime_ns, late_ns)
        return PushOutcome(True, "pushed", late_ns)

    # -- ladders and stores -----------------------------------------------------------------

    def set_ladder(self, station: str, day: dt.date, rungs: Sequence[Rung]) -> None:
        """Declare (or change) a station-day's ladder; invalidates that station's store."""
        ladder = tuple(rungs)
        if self._ladders.get((station, day)) == ladder:
            return
        self._ladders[(station, day)] = ladder
        self._stores.pop((station, day), None)

    def pinned_rows(self, station: str, day: dt.date) -> list[DerivedNbpRow]:
        """First-MAX-column rows of the three pinned cycles of ``day`` (sim: ``read_pinned``)."""
        pins = set(_pinned(day))
        by_cycle: dict[int, list[LiveNbpRow]] = {}
        for row in self._rows[self._icao_by_station[station]].values():
            if _cycle_key(row.cycle_runtime_ns) in pins:
                by_cycle.setdefault(row.cycle_runtime_ns, []).append(row)
        kept: list[DerivedNbpRow] = []
        for rows in by_cycle.values():
            kept.extend(_first_max_column(rows))
        return kept

    def store(self, station: str, day: dt.date) -> PNoStore | None:
        """The ``PNoStore`` for the station-day, or ``None`` before its ladder is declared."""
        ladder = self._ladders.get((station, day))
        if ladder is None:
            return None
        cached = self._stores.get((station, day))
        if cached is not None:
            return cached
        rows = self.pinned_rows(station, day)
        consumed = frozenset((r.cycle_runtime_ns, r.raw_sha256) for r in rows)
        built = PNoStore(
            {(station, day): rows},
            consumed,
            self._calibration,
            {(station, day): ladder},
        )
        self._stores[(station, day)] = built
        return built

    def complete_cycle_count(self, station: str, day: dt.date) -> int:
        """Pinned cycles with all seven variables (observability only)."""
        per_cycle: dict[int, set[str]] = {}
        for row in self.pinned_rows(station, day):
            per_cycle.setdefault(row.cycle_runtime_ns, set()).add(row.variable)
        return sum(1 for v in per_cycle.values() if v == set(NBP_QUANTILE_VARIABLES))
