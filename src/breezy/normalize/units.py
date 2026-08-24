"""Unit handling for settlement temperature values.

PURE module: no I/O, no clock access, no `nautilus_trader` import, no
global state.

Settlement values stay exactly as NWS publishes them: whole-degree
Fahrenheit integers, or an explicit sentinel when the value is genuinely
absent (never imputed, never coerced to 0). A published value may also
carry `is_record` -- NWS's own "tied or broke the period-of-record"
qualifier -- which is preserved rather than discarded; see
`TemperatureReadingF.is_record`. `fahrenheit_to_celsius` is provided for
ENRICHMENT use only -- it is a separate, clearly-named function so it is
structurally obvious that no settlement code path silently runs a value
through a conversion.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SentinelFlag = Literal["NONE", "M", "T", "MS", "MB"]
"""The published-value state for a settlement temperature field.

- "NONE": a genuine numeric value is present in `value_f`.
- "M":    missing (NWS renders this as `M` or `MM` in the raw product).
- "T":    trace amount (used for precipitation-adjacent fields; some
          CLI products render a temperature-position field as `T`).
- "MS":   missing, value at a specific observation time.
- "MB":   missing, value at midnight.
"""


@dataclass(frozen=True, slots=True)
class TemperatureReadingF:
    """A single settlement temperature value, in whole-degree Fahrenheit.

    This is the SETTLEMENT representation -- values here are exactly as
    published, never converted. `value_f` is populated if and only if
    `sentinel == "NONE"`. When a sentinel is present, `value_f` is `None`;
    it is never imputed to 0 or any other placeholder number.
    """

    value_f: int | None
    sentinel: SentinelFlag
    is_record: bool = False
    """`True` when the raw CLI token carried a trailing ``R`` qualifier,
    meaning the value tied or broke the daily period-of-record for that
    date (NWS footer legend: ``R  INDICATES RECORD WAS SET OR TIED.``).

    Orthogonal to `sentinel`, not an alternative to it: a record-setting
    reading is by definition a REAL published value, so `is_record=True`
    can only ever pair with `sentinel == "NONE"` -- a missing/trace value
    has nothing to have tied or broken. Defaults to `False` so every
    existing call site that never mentions records is unaffected.

    This mirrors, at the pure parsing layer, the paired-value/qualifier
    pattern `breezy.domain.nws_climate_day.NwsClimateDay` already uses for
    its `tmax_flag`/`tmin_flag`/`tavg_flag` sentinel columns -- it is
    deliberately NOT a new, unrelated flag concept. Wiring this bit
    through to that persisted column is `breezy.ingest.records`' job (it
    owns the `TemperatureReadingF` -> `NwsClimateDay` mapping) and is not
    done here.
    """

    def __post_init__(self) -> None:
        if self.sentinel == "NONE" and self.value_f is None:
            raise ValueError("value_f must be set when sentinel is 'NONE'")
        if self.sentinel != "NONE" and self.value_f is not None:
            raise ValueError("value_f must be None when a sentinel is present")
        if self.is_record and self.sentinel != "NONE":
            raise ValueError(
                "is_record must be False when a sentinel is present -- a missing/"
                "trace value cannot also be a record"
            )


def fahrenheit_to_celsius(value_f: int) -> float:
    """Convert a published Fahrenheit value to Celsius.

    ENRICHMENT USE ONLY. Never call this on a settlement path -- settlement
    values are stored and compared exactly as NWS publishes them (°F).
    """
    return (value_f - 32) * 5.0 / 9.0
