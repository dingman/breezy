"""MAKER-S2 WP2 -- S-6 verify-first: alignment and vintage-age lines, never a fill/bid/p_no.

Split from ``maker_stage0_pno`` so the simulator cannot import it by accident. Runs only on
2026-06-30 (amendment §1 item 3).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from breezy.normalize.climate_day import local_standard_date
from breezy.persistence.nbp_derived_store import DerivedNbpRow
from breezy.strategy.ladder_ev.forecast_state import NBP_QUANTILE_MODEL, ForecastQuantileState
from scripts.analysis.forecast_climate_day_map import climate_day_for_txn
from scripts.analysis.maker_stage0_pno import STATIONS, Site, build_state, read_pinned, site

VERIFY_FIRST_DAY: Final = dt.date(2026, 6, 30)
_NS: Final = 10**9
_TOLERANCE_MIN: Final = 30.0
#: Spec §3.1 p50 ages (min) at 16:50Z D-1, 00:00Z D, 02:50Z D (avail 14:04Z, 20:17Z, 02:04Z).
_EXPECTED_AGE_MIN: Final = (("16:50Z D-1", -1, 16, 50, 166.0), ("00:00Z D", 0, 0, 0, 223.0),
                            ("02:50Z D", 0, 2, 50, 46.0))  # fmt: skip


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
    rows: Sequence[DerivedNbpRow], station: str, st: Site, day: dt.date
) -> list[AlignmentLine]:
    lines: list[AlignmentLine] = []
    for row in rows:
        if row.variable != "TXN_Q50":
            continue
        mapped = local_standard_date(row.valid_end_ns, st.offset_hours)
        txn_day = climate_day_for_txn(
            icao=st.icao, runtime_ns=row.cycle_runtime_ns, ftime_ns=row.valid_end_ns,
            std_utc_offset_hours=st.offset_hours, model=NBP_QUANTILE_MODEL, kind="max",
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
    """S-6 verify-first: alignment and vintage-age lines only, never a fill/bid/p_no."""
    if climate_day != VERIFY_FIRST_DAY:
        raise ValueError(
            f"verify-first runs only on {VERIFY_FIRST_DAY.isoformat()}, got {climate_day}"
        )
    alignment: list[AlignmentLine] = []
    ages: list[VintageAgeLine] = []
    for station in STATIONS:
        st = site(station)
        rows = read_pinned(nbp_root, st.icao, climate_day).rows
        alignment += _alignment(rows, station, st, climate_day)
        ages += _ages(build_state(rows, st.offset_hours, "none"), station, climate_day)
    return VerifyFirstReport(climate_day, tuple(alignment), tuple(ages))
