"""Forecast TXN (runtime, ftime) -> climate_day map (FC-0a-4 Phase A).

Pure. No I/O, no clock, no network, no ``nautilus_trader``, no ``zoneinfo``.
``std_utc_offset_hours`` is always caller-supplied from
``registry.climate_day_window(venue, city)``; this module holds no per-city
literal.

Every ns->date conversion goes through ``gaps.local_standard_date``
(gaps.py:392-405). The offset primitive lives in
``breezy.domain.climate_day`` (climate_day.py:26-53).
"""

from __future__ import annotations

from datetime import date
from typing import Final

from breezy.domain.climate_day import ClimateDayError
from breezy.ingest import gaps

__all__ = [
    "TXN_MAX_PERIOD_END_UTC_HOUR",
    "TXN_MAX_PERIOD_HOURS",
    "ForecastValidPeriodError",
    "climate_day_for_txn",
]

_NS: Final[int] = 10**9
_SECONDS_PER_HOUR: Final[int] = 3600
_SECONDS_PER_DAY: Final[int] = 86400

#: INFERRED / RE-VERIFY in Phase B. Daily-max TXN period ends at 06Z.
TXN_MAX_PERIOD_END_UTC_HOUR: Final[int] = 6

#: INFERRED / RE-VERIFY in Phase B. Daytime-max window length ending at ftime.
TXN_MAX_PERIOD_HOURS: Final[int] = 18


class ForecastValidPeriodError(ClimateDayError):
    """Raised when a TXN (runtime, ftime) pair is not a daily-max period."""


def climate_day_for_txn(
    *,
    icao: str,
    runtime_ns: int,
    ftime_ns: int,
    std_utc_offset_hours: float,
    model: str,
) -> date:
    """Map a TXN forecast (runtime, ftime) to the climate day it forecasts.

    P1 (INFERRED / UNVERIFIED; Phase-B B0 confirms or refutes): for NBS/GFS MOS
    the TXN element at ftime covers the period ENDING at ftime; the daytime-max
    period is the 18 h window ending ftime=06Z(D+1), starting 12Z(D)
    (parent §3.1:242). valid_start_ns = ftime_ns − 18 h.

    P2 (INFERRED / UNVERIFIED; Phase-B B0 confirms or refutes): climate_day =
    local_standard_date(valid_start_ns, std_utc_offset_hours).

    Four-offset arithmetic for ftime=06:00Z(D+1) → valid_start=12:00Z(D): KMIA
    07:00 EST D; KMDW 06:00 CST D; KSFO/KLAX 04:00 PST D. Day D at all four.
    The competing "local date of ftime" splits the panel (MIA 01:00 EST D+1,
    MDW 00:00 CST D+1, SFO/LAX 22:00 PST D) — the mislabelling the pin avoids.

    Daily-max discriminator: UTC hour of ftime is
    ``(ftime_ns // 10**9) % 86400 // 3600``. That hour must equal
    TXN_MAX_PERIOD_END_UTC_HOUR (6, INFERRED / RE-VERIFY). ftime UTC hour ≠ 6
    is not the daily-max TXN period.

    Leg-invariance: climate_day_for_txn does not take a contract side or a
    leg; the mapped climate day is identical for every contract on the
    station-day.

    ``icao`` and ``model`` identify the forecast row; they do not change the
    map. ``std_utc_offset_hours`` is always caller-supplied from
    ``registry.climate_day_window(venue, city)``.
    """
    if type(runtime_ns) is not int or type(ftime_ns) is not int:
        raise ForecastValidPeriodError("non-int ns")
    if std_utc_offset_hours is None:
        raise ForecastValidPeriodError("offset absent")
    if runtime_ns > ftime_ns:
        raise ForecastValidPeriodError("runtime after the period end")
    utc_hour = (ftime_ns // _NS) % _SECONDS_PER_DAY // _SECONDS_PER_HOUR
    if utc_hour != TXN_MAX_PERIOD_END_UTC_HOUR:
        raise ForecastValidPeriodError("not the daily-max TXN period")
    valid_start_ns = ftime_ns - TXN_MAX_PERIOD_HOURS * _SECONDS_PER_HOUR * _NS
    return gaps.local_standard_date(valid_start_ns, std_utc_offset_hours)
