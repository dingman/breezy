"""Forecast TXN (runtime, ftime) -> climate_day map (FC-0a-4 Phase A/B).

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
from typing import Final, Literal

from breezy.domain.climate_day import ClimateDayError
from breezy.ingest import gaps

__all__ = [
    "TXN_MAX_PERIOD_END_UTC_HOUR",
    "TXN_MIN_PERIOD_END_UTC_HOUR",
    "ForecastValidPeriodError",
    "TxnPeriodKind",
    "climate_day_for_txn",
]

_NS: Final[int] = 10**9
_SECONDS_PER_HOUR: Final[int] = 3600
_SECONDS_PER_DAY: Final[int] = 86400

#: Which daily extremum a TXN row's ftime targets. REQUIRED on every call
#: to ``climate_day_for_txn`` -- never inferred from the row -- so a
#: daily-MIN row can never be silently consumed as a daily-MAX.
TxnPeriodKind = Literal["max", "min"]

#: MEASURED 2026-09-19 against live NBS
#: (docs/evidence/FC_0a_TXN_OCCUPANCY_2026-09-19.md): a full-file census of
#: 14,720 real rows (4 stations -- KLAX/KMDW/KMIA/KSFO -- x 40 days) shows
#: ``txn`` is non-empty at EXACTLY two ftime UTC hours -- 00Z and 12Z -- and
#: 0% (0/1760-1920 rows each) at every other 3-hourly ftime the venue
#: publishes, including the previously-frozen 06Z (0/14,720 populated).
#: This SUPERSEDES the earlier ``TXN_MAX_PERIOD_END_UTC_HOUR = 6``
#: (INFERRED), which matched none of the 14,720 real rows -- as coded, the
#: prior constant raised ``ForecastValidPeriodError`` on every real live
#: NBS ``txn`` value.
#:
#: 00Z is the daily-MAX end hour, confirmed by magnitude, not by any label
#: in the data: mean ``txn`` at ftime=00Z is 11.6-13.7 F warmer than at
#: ftime=12Z, at all four stations independently, consistent with
#: local-afternoon-high vs local-overnight-low regardless of each
#: station's UTC offset (see the evidence doc's "Max vs min
#: disambiguation"). ``xnd`` was checked and REFUTED as a max/min
#: discriminator -- its value set overlaps at both hours -- so it must
#: never be used for this purpose.
TXN_MAX_PERIOD_END_UTC_HOUR: Final[int] = 0

#: MEASURED alongside ``TXN_MAX_PERIOD_END_UTC_HOUR`` (same evidence doc,
#: same census). Daily-MIN ftime end hour.
TXN_MIN_PERIOD_END_UTC_HOUR: Final[int] = 12

_PERIOD_END_UTC_HOUR_BY_KIND: Final[dict[TxnPeriodKind, int]] = {
    "max": TXN_MAX_PERIOD_END_UTC_HOUR,
    "min": TXN_MIN_PERIOD_END_UTC_HOUR,
}


class ForecastValidPeriodError(ClimateDayError):
    """Raised when a TXN (runtime, ftime) pair is not the requested-kind daily period."""


def climate_day_for_txn(
    *,
    icao: str,
    runtime_ns: int,
    ftime_ns: int,
    std_utc_offset_hours: float,
    model: str,
    kind: TxnPeriodKind,
) -> date:
    """Map a TXN forecast (runtime, ftime) to the climate day it forecasts.

    ``kind`` is REQUIRED and MUST be supplied by the caller -- it is never
    inferred from the row. Breezy trades daily HIGH markets; a daily-MIN
    (``kind="min"``) row silently accepted as a MAX would be catastrophic
    and invisible. Enforcement: ``kind`` selects which measured ftime UTC
    hour is expected (00 for "max", 12 for "min"); a row whose ftime UTC
    hour does not match the REQUESTED kind's hour is refused exactly like
    any other wrong hour -- there is no separate "wrong kind" code path to
    accidentally skip, so a MIN row (ftime 12Z) called with
    ``kind="max"`` raises the identical ``ForecastValidPeriodError`` a
    06Z or 18Z row would.

    MEASURED (docs/evidence/FC_0a_TXN_OCCUPANCY_2026-09-19.md; 14,720 real
    NBS rows / 4 stations / 40 days): ``txn`` is populated at exactly two
    ftime UTC hours -- 00Z (daily MAX) and 12Z (daily MIN) -- and at NO
    other hour, in particular NEVER at the previously-frozen 06Z
    (0/14,720). A row at any other ftime UTC hour is refused, including
    06Z: 0% measured occupancy there means a 06Z row is anomalous, not a
    slow-to-arrive daily period, and must never be silently mapped.

    Day-labeling (P2): ``climate_day = local_standard_date(ftime_ns,
    std_utc_offset_hours)`` -- directly, with NO period-length
    subtraction. Every registered station offset is a negative whole-hour
    offset in [-5, -8]; at both measured end hours (00 and 12) that keeps
    the local conversion of ftime within a single calendar day short of
    local midnight, so the local date of ftime itself is already the
    correct climate day for the period ending there: at 00Z the local
    conversion falls in the evening of the PRECEDING local day (the day
    the afternoon max belongs to); at 12Z it falls in the morning of the
    SAME local day as ftime's own UTC date (the day the overnight min
    belongs to). Re-verified against a real archive: an exhaustive
    alignment run (``scripts/analysis/forecast_txn_climate_day_cli_alignment.py``)
    reproduces the real NWS CLI archive's own day label with ZERO
    mismatches over 7,274 real station-days.

    PERIOD LENGTH IS UNVERIFIED. The occupancy census that fixed the two
    end hours above determines only WHEN ``txn`` publishes, never the
    number of hours each aggregation window spans (12h, 18h, or
    something else) -- that would require correlating ``txn`` against an
    independent truth source within the same file, which this measurement
    did not do. Day-labeling above does not need that length (it uses
    ftime's own local date, not a subtracted "valid start"), so this gap
    does not block trading the MAX element; it remains open for any other
    use of window length (e.g. the window-coverage forecast-accuracy
    corollary in ``forecast_txn_climate_day_cli_alignment.py``). Do not
    assume 12h or 18h for it.

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
    if kind not in _PERIOD_END_UTC_HOUR_BY_KIND:
        raise ForecastValidPeriodError(f"unknown TXN period kind: {kind!r}")
    expected_hour = _PERIOD_END_UTC_HOUR_BY_KIND[kind]
    utc_hour = (ftime_ns // _NS) % _SECONDS_PER_DAY // _SECONDS_PER_HOUR
    if utc_hour != expected_hour:
        raise ForecastValidPeriodError(
            f"not the daily-{kind} TXN period: ftime UTC hour {utc_hour} != {expected_hour}"
        )
    return gaps.local_standard_date(ftime_ns, std_utc_offset_hours)
