"""ClimateDayReading: the pure settlement-facing reading type.

PURE module: no I/O, no clock access, no `nautilus_trader` import, no
global state.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

from breezy.normalize.units import TemperatureReadingF

SourceGrade = Literal["SETTLEMENT"]


@dataclass(frozen=True)
class ClimateDayReading:
    """A single site's climate-day temperature reading.

    This is a PLAIN frozen dataclass -- it is NOT a NautilusTrader `Data`
    type, and this module has no dependency on `nautilus_trader`.

    `source_grade` is set to `"SETTLEMENT"` only via the `from_nws(...)`
    classmethod. Be honest about what this is: it is VISIBILITY for
    review, not an unforgeable settlement token. The dataclass remains
    directly constructible with any `source_grade` value a caller
    chooses to pass -- nothing in this module prevents bypassing
    `from_nws`. Downstream code must not treat the field's presence as
    proof of provenance.
    """

    station: str
    climate_day: date
    tmax: TemperatureReadingF
    tmin: TemperatureReadingF
    tavg: TemperatureReadingF
    is_final: bool
    has_correction_evidence: bool
    source_grade: SourceGrade

    @classmethod
    def from_nws(
        cls,
        *,
        station: str,
        climate_day: date,
        tmax: TemperatureReadingF,
        tmin: TemperatureReadingF,
        tavg: TemperatureReadingF,
        is_final: bool,
        has_correction_evidence: bool,
    ) -> ClimateDayReading:
        """Construct a reading from already-classified/parsed NWS pieces.

        Callers assemble `tmax`/`tmin`/`tavg` via `cli_parse.py`,
        `is_final` via `classify.classify_issuance(...) == "FINAL"`, and
        `has_correction_evidence` via `classify.has_correction_evidence(...)`.
        This classmethod does no parsing itself -- it only stamps
        `source_grade`.
        """
        return cls(
            station=station,
            climate_day=climate_day,
            tmax=tmax,
            tmin=tmin,
            tavg=tavg,
            is_final=is_final,
            has_correction_evidence=has_correction_evidence,
            source_grade="SETTLEMENT",
        )
