"""Frozen forecast-side climate-day fixture table (FC-0a-4 Phase A + Phase B).

Data only: rows that pin (icao, runtime, ftime) -> climate_day phenomena
the parent plan names (MIA bleed, SFO/LAX UTC-cut miss, DST, v5-split
invariance, 18Z night-MIN refusal). Phase A's rows (provenance="synthetic")
use narrative 2026 dates chosen before any archive check. Phase B appends
one "observed" row per phenomenon below, each grounded in a REAL NWS CLI
FINAL record verified present in the on-disk settlement-alignment cache
(``settlement_alignment_cache.DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR``) -- see
``docs/evidence/forecast_txn_climate_day_cli_alignment_2026-09-19.md`` for
the verification run. "observed" never means a real forecast (TXN) value
was checked -- the fixture table carries no forecast value field at all,
by design (see ``ForecastDayFixture``) -- it means the row's
``expected_climate_day`` is a calendar date NWS actually published a CLI
report for at that station, not an invented future date.

No network. No nautilus_trader. No zoneinfo. Offsets in a row are the
frozen expected values for that row; the mapper never reads this table.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Final, Literal

__all__ = [
    "FORECAST_STATIONS",
    "FROZEN_AT",
    "FROZEN_FIXTURES",
    "FROZEN_TABLE_SHA256",
    "ForecastDayFixture",
    "table_digest",
]

_NS: Final[int] = 10**9
_VENUE: Final[str] = "polymarket_us"

Provenance = Literal["synthetic", "observed"]


def _utc_ns(year: int, month: int, day: int, hour: int) -> int:
    return int(datetime(year, month, day, hour, tzinfo=UTC).timestamp()) * _NS


@dataclass(frozen=True, kw_only=True, slots=True)
class ForecastDayFixture:
    """One frozen (icao, runtime, ftime) row and the climate day it must map to."""

    icao: str
    runtime_ns: int
    ftime_ns: int
    std_utc_offset_hours: float
    model: str
    expected_climate_day: date
    expected_utc_naive_day: date
    phenomenon: str
    provenance: Provenance
    expected_refusal: bool


#: ICAO -> registry city token. Offsets come from
#: ``registry.climate_day_window(venue, city)``, never from a literal here.
#: KNYC is excluded (parent §3.4).
FORECAST_STATIONS: Final[tuple[tuple[str, str], ...]] = (
    ("KMIA", "MIA"),
    ("KMDW", "MDW"),
    ("KSFO", "SFO"),
    ("KLAX", "LAX"),
)

FORECAST_VENUE: Final[str] = _VENUE

FROZEN_AT: Final[datetime] = datetime(2026, 9, 18, tzinfo=UTC)

#: Frozen at FC-0a-4 Phase B completion, over all 18 rows (9 synthetic +
#: 9 observed). Recompute via `table_digest(FROZEN_FIXTURES)`; any row
#: edit must recompute and update this value in the same change.
FROZEN_TABLE_SHA256: str | None = (
    "170eead77c0bbe4b1b876f215813932d14c919ac109296820765bce88aca97ee"
)

# Canonical TXN max-period cycle: runtime 12Z(D), ftime 06Z(D+1).
# Climate day under P2 is D at every forecast offset; UTC naive of ftime is D+1.
_JUL15_RUNTIME = _utc_ns(2026, 7, 15, 12)
_JUL16_FTIME_06 = _utc_ns(2026, 7, 16, 6)
_JUL15_CLIMATE = date(2026, 7, 15)
_JUL16_UTC = date(2026, 7, 16)

# v5-split pair (INFERRED boundary date; evidence-doc only in Phase B):
# same ftime, two runtimes, same climate day.
_V5_FTIME = _utc_ns(2024, 12, 3, 6)
_V5_CLIMATE = date(2024, 12, 2)
_V5_UTC = date(2024, 12, 3)

# Phase B "observed" anchor: 2024-12-02/03 verified present as real MIA/MDW/
# SFO/LAX CLI FINAL records (docs/evidence/forecast_txn_climate_day_cli_
# alignment_2026-09-19.md). Reused across the bleed/v5-split observed rows
# below so the digest-freezing table cites one measurement, not several.
_OBS_BLEED_RUNTIME = _utc_ns(2024, 12, 2, 12)
_OBS_BLEED_FTIME = _utc_ns(2024, 12, 3, 6)
_OBS_BLEED_CLIMATE = date(2024, 12, 2)
_OBS_BLEED_UTC = date(2024, 12, 3)
_OBS_V5_FTIME = _OBS_BLEED_FTIME

FROZEN_FIXTURES: Final[tuple[ForecastDayFixture, ...]] = (
    ForecastDayFixture(
        icao="KMIA",
        runtime_ns=_JUL15_RUNTIME,
        ftime_ns=_JUL16_FTIME_06,
        std_utc_offset_hours=-5.0,
        model="NBM_NBS",
        expected_climate_day=_JUL15_CLIMATE,
        expected_utc_naive_day=_JUL16_UTC,
        phenomenon="mia_period_end_bleed",
        provenance="synthetic",
        expected_refusal=False,
    ),
    ForecastDayFixture(
        icao="KMDW",
        runtime_ns=_JUL15_RUNTIME,
        ftime_ns=_JUL16_FTIME_06,
        std_utc_offset_hours=-6.0,
        model="NBM_NBS",
        expected_climate_day=_JUL15_CLIMATE,
        expected_utc_naive_day=_JUL16_UTC,
        phenomenon="mdw_period_end_bleed",
        provenance="synthetic",
        expected_refusal=False,
    ),
    ForecastDayFixture(
        icao="KSFO",
        runtime_ns=_JUL15_RUNTIME,
        ftime_ns=_JUL16_FTIME_06,
        std_utc_offset_hours=-8.0,
        model="NBM_NBS",
        expected_climate_day=_JUL15_CLIMATE,
        expected_utc_naive_day=_JUL16_UTC,
        phenomenon="sfo_utc_cut_miss",
        provenance="synthetic",
        expected_refusal=False,
    ),
    ForecastDayFixture(
        icao="KLAX",
        runtime_ns=_JUL15_RUNTIME,
        ftime_ns=_JUL16_FTIME_06,
        std_utc_offset_hours=-8.0,
        model="NBM_NBS",
        expected_climate_day=_JUL15_CLIMATE,
        expected_utc_naive_day=_JUL16_UTC,
        phenomenon="lax_utc_cut_miss",
        provenance="synthetic",
        expected_refusal=False,
    ),
    ForecastDayFixture(
        icao="KMIA",
        runtime_ns=_utc_ns(2026, 3, 8, 12),
        ftime_ns=_utc_ns(2026, 3, 9, 6),
        std_utc_offset_hours=-5.0,
        model="NBM_NBS",
        expected_climate_day=date(2026, 3, 8),
        expected_utc_naive_day=date(2026, 3, 9),
        phenomenon="dst_spring_forward",
        provenance="synthetic",
        expected_refusal=False,
    ),
    ForecastDayFixture(
        icao="KMIA",
        runtime_ns=_utc_ns(2026, 11, 1, 12),
        ftime_ns=_utc_ns(2026, 11, 2, 6),
        std_utc_offset_hours=-5.0,
        model="NBM_NBS",
        expected_climate_day=date(2026, 11, 1),
        expected_utc_naive_day=date(2026, 11, 2),
        phenomenon="dst_fall_back",
        provenance="synthetic",
        expected_refusal=False,
    ),
    ForecastDayFixture(
        icao="KMIA",
        runtime_ns=_utc_ns(2024, 12, 2, 12),
        ftime_ns=_V5_FTIME,
        std_utc_offset_hours=-5.0,
        model="NBM_NBS",
        expected_climate_day=_V5_CLIMATE,
        expected_utc_naive_day=_V5_UTC,
        phenomenon="v5_split_pre",
        provenance="synthetic",
        expected_refusal=False,
    ),
    ForecastDayFixture(
        icao="KMIA",
        runtime_ns=_utc_ns(2024, 12, 3, 0),
        ftime_ns=_V5_FTIME,
        std_utc_offset_hours=-5.0,
        model="NBM_NBS",
        expected_climate_day=_V5_CLIMATE,
        expected_utc_naive_day=_V5_UTC,
        phenomenon="v5_split_post",
        provenance="synthetic",
        expected_refusal=False,
    ),
    ForecastDayFixture(
        icao="KMIA",
        runtime_ns=_utc_ns(2026, 7, 15, 12),
        ftime_ns=_utc_ns(2026, 7, 15, 18),
        std_utc_offset_hours=-5.0,
        model="NBM_NBS",
        expected_climate_day=date(2026, 7, 15),
        expected_utc_naive_day=date(2026, 7, 15),
        phenomenon="night_min_18z",
        provenance="synthetic",
        expected_refusal=True,
    ),
    # ------------------------------------------------------------------
    # Phase B: "observed" rows. Each expected_climate_day below is a real
    # NWS CLI FINAL date, verified present for that station in the on-disk
    # settlement-alignment cache (2021-01-01..2025-12-31 coverage) -- see
    # docs/evidence/forecast_txn_climate_day_cli_alignment_2026-09-19.md.
    # ------------------------------------------------------------------
    ForecastDayFixture(
        icao="KMIA",
        runtime_ns=_OBS_BLEED_RUNTIME,
        ftime_ns=_OBS_BLEED_FTIME,
        std_utc_offset_hours=-5.0,
        model="NBM_NBS",
        expected_climate_day=_OBS_BLEED_CLIMATE,
        expected_utc_naive_day=_OBS_BLEED_UTC,
        phenomenon="mia_period_end_bleed",
        provenance="observed",
        expected_refusal=False,
    ),
    ForecastDayFixture(
        icao="KMDW",
        runtime_ns=_OBS_BLEED_RUNTIME,
        ftime_ns=_OBS_BLEED_FTIME,
        std_utc_offset_hours=-6.0,
        model="NBM_NBS",
        expected_climate_day=_OBS_BLEED_CLIMATE,
        expected_utc_naive_day=_OBS_BLEED_UTC,
        phenomenon="mdw_period_end_bleed",
        provenance="observed",
        expected_refusal=False,
    ),
    ForecastDayFixture(
        icao="KSFO",
        runtime_ns=_OBS_BLEED_RUNTIME,
        ftime_ns=_OBS_BLEED_FTIME,
        std_utc_offset_hours=-8.0,
        model="NBM_NBS",
        expected_climate_day=_OBS_BLEED_CLIMATE,
        expected_utc_naive_day=_OBS_BLEED_UTC,
        phenomenon="sfo_utc_cut_miss",
        provenance="observed",
        expected_refusal=False,
    ),
    ForecastDayFixture(
        icao="KLAX",
        runtime_ns=_OBS_BLEED_RUNTIME,
        ftime_ns=_OBS_BLEED_FTIME,
        std_utc_offset_hours=-8.0,
        model="NBM_NBS",
        expected_climate_day=_OBS_BLEED_CLIMATE,
        expected_utc_naive_day=_OBS_BLEED_UTC,
        phenomenon="lax_utc_cut_miss",
        provenance="observed",
        expected_refusal=False,
    ),
    ForecastDayFixture(
        icao="KMIA",
        runtime_ns=_utc_ns(2022, 3, 13, 12),
        ftime_ns=_utc_ns(2022, 3, 14, 6),
        std_utc_offset_hours=-5.0,
        model="NBM_NBS",
        expected_climate_day=date(2022, 3, 13),
        expected_utc_naive_day=date(2022, 3, 14),
        phenomenon="dst_spring_forward",
        provenance="observed",
        expected_refusal=False,
    ),
    ForecastDayFixture(
        icao="KMIA",
        runtime_ns=_utc_ns(2022, 11, 6, 12),
        ftime_ns=_utc_ns(2022, 11, 7, 6),
        std_utc_offset_hours=-5.0,
        model="NBM_NBS",
        expected_climate_day=date(2022, 11, 6),
        expected_utc_naive_day=date(2022, 11, 7),
        phenomenon="dst_fall_back",
        provenance="observed",
        expected_refusal=False,
    ),
    ForecastDayFixture(
        icao="KMIA",
        runtime_ns=_OBS_BLEED_RUNTIME,
        ftime_ns=_OBS_V5_FTIME,
        std_utc_offset_hours=-5.0,
        model="NBM_NBS",
        expected_climate_day=_OBS_BLEED_CLIMATE,
        expected_utc_naive_day=_OBS_BLEED_UTC,
        phenomenon="v5_split_pre",
        provenance="observed",
        expected_refusal=False,
    ),
    ForecastDayFixture(
        icao="KMIA",
        runtime_ns=_utc_ns(2024, 12, 3, 0),
        ftime_ns=_OBS_V5_FTIME,
        std_utc_offset_hours=-5.0,
        model="NBM_NBS",
        expected_climate_day=_OBS_BLEED_CLIMATE,
        expected_utc_naive_day=_OBS_BLEED_UTC,
        phenomenon="v5_split_post",
        provenance="observed",
        expected_refusal=False,
    ),
    ForecastDayFixture(
        icao="KMIA",
        runtime_ns=_OBS_BLEED_RUNTIME,
        ftime_ns=_utc_ns(2024, 12, 2, 18),
        std_utc_offset_hours=-5.0,
        model="NBM_NBS",
        expected_climate_day=_OBS_BLEED_CLIMATE,
        expected_utc_naive_day=_OBS_BLEED_CLIMATE,
        phenomenon="night_min_18z",
        provenance="observed",
        expected_refusal=True,
    ),
)


def table_digest(rows: Sequence[ForecastDayFixture]) -> str:
    """SHA-256 of a canonical JSON encoding of ``rows`` (hex digest)."""
    payload = [
        {
            "expected_climate_day": row.expected_climate_day.isoformat(),
            "expected_refusal": row.expected_refusal,
            "expected_utc_naive_day": row.expected_utc_naive_day.isoformat(),
            "ftime_ns": row.ftime_ns,
            "icao": row.icao,
            "model": row.model,
            "phenomenon": row.phenomenon,
            "provenance": row.provenance,
            "runtime_ns": row.runtime_ns,
            "std_utc_offset_hours": row.std_utc_offset_hours,
        }
        for row in rows
    ]
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
