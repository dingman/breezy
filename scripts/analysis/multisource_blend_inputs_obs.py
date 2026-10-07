"""F13 Phase A feature build: the ``obs_so_far`` reader (FB-R13 definition, FB-R15 source).

``obs_so_far`` is defined on ROUTINE hourly METAR readings only, for training and for any future
serving (L-13: no train/serve skew). The live path mixes METAR-exact rows with NWS integer-C
interval rows at a 5-minute cadence; the interval rows cannot be reproduced offline, so they are
excluded on both sides. The live path, cited here and imported nowhere:

* ``breezy.ingest.iem_observations`` / ``breezy.ingest.nws_observations`` turn a METAR ``T`` group
  (tenths of a degree C) into a ``StationObservation`` (``is_metar``);
* ``breezy.strategy.weather_common.running_extreme.RunningExtremeAccumulator`` keeps the climate
  day's running max and quantises each row with ``breezy.domain.temperature.round_half_up_f``
  (``floor(c_tenths / 10 * 9 / 5 + 32 + 0.5)``), on the local STANDARD-time day.

FB-R15: the training values are read from the routine-METAR store
(``scripts/archive/metar_routine_store.py``, via ``read_routine_metar``), whose ``tmpf`` is the
T group through ``round_half_up_f``. ``tmpf_source="column"`` rows are used and counted;
``"missing"`` rows are skipped and counted, never imputed; there is NO 1-minute fallback. The
station's ``obs_routine_minute_by_station`` pin is a validation filter: a row at another minute
is excluded and counted. ``available_at`` = report time + the obs lag. The store is read below the
sealed holdout only (a window reaching it is never requested).

Two DESCRIPTIVE, non-METAR arms from the 1-minute archive are returned and never feed a feature:
the raw 1-minute running max and the 5-minute whole-degF running max.

:func:`modal_routine_minute_by_station` derives the modal report minute per station from routine
report timestamps for the coordinator to pin (reported, never applied). Streamed; no network.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import math
import sys
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:  # runtime import is lazy: see read_routine_obs_year
    from scripts.archive.metar_routine_store import RoutineMetar

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src"), str(Path(__file__).resolve().parent)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from forecast_conditional_corpus import (  # type: ignore[import-not-found]
    OBS_CADENCE_SECONDS,
)

from breezy.analysis.multisource_blend_features import HOLDOUT_START, ObsReading
from breezy.domain.temperature import round_half_up_f
from breezy.persistence.archive_cache import (
    ArchiveCache,
    ArchiveCacheError,
    iem_asos_1min_request,
)

__all__ = [
    "DESCRIPTIVE_FIVE_MIN_SECONDS",
    "LIVE_PATH_CITATION",
    "MINUTES_PER_HOUR",
    "OBS_SOURCE_LABEL",
    "ROUTINE_OBS_CADENCE_SECONDS",
    "ObsQuantisationError",
    "ObsStoreError",
    "OneMinArms",
    "RoutineMinute",
    "RoutineObsYear",
    "live_quantised_f",
    "modal_routine_minute_by_station",
    "raw_running_max_at",
    "read_onemin_arms_year",
    "read_routine_obs_year",
    "routine_minute_pin_suggestion",
    "whole_f_to_c_tenths",
]

_NS: Final[int] = 1_000_000_000
#: FB-R13: routine METAR reports arrive hourly; this is the ``obs_cadence_seconds`` pin value.
ROUTINE_OBS_CADENCE_SECONDS: Final[int] = 3600
#: The live 5-minute grid, kept only for the DESCRIPTIVE 5-min arm (imported, never re-typed).
DESCRIPTIVE_FIVE_MIN_SECONDS: Final[int] = OBS_CADENCE_SECONDS
MINUTES_PER_HOUR: Final[int] = 60
OBS_SOURCE_LABEL: Final[str] = "iem_routine_metar_tgroup_round_half_up_f"
LIVE_PATH_CITATION: Final[str] = (
    "live obs path: src/breezy/ingest/iem_observations.py (METAR T-group, tenths C, "
    "station_observation_data_type) + src/breezy/ingest/nws_observations.py; quantised by "
    "src/breezy/strategy/weather_common/running_extreme.py via "
    "breezy.domain.temperature.round_half_up_f on the local standard-time climate day; FB-R13/"
    "FB-R15: only the routine hourly METAR reading (routine-METAR store, the station's routine "
    "report minute) is emulated, never the 5-minute NWS interval rows"
)


class ObsQuantisationError(RuntimeError):
    """The archive reading cannot be reproduced through the live quantisation: STOP (FB-R3)."""


class ObsStoreError(RuntimeError):
    """The routine-METAR store cannot be read as requested (missing, corrupt, sealed): STOP."""


@dataclass(slots=True)
class RoutineObsYear:
    """One station-year of routine-METAR readings reduced to the requested climate days."""

    readings_by_day: dict[dt.date, tuple[ObsReading, ...]] = field(default_factory=dict)
    counts: Counter[str] = field(default_factory=Counter)


@dataclass(slots=True)
class OneMinArms:
    """Non-METAR descriptive arms of one station-year of the 1-minute archive."""

    #: ``(ts_ns, running max degF)`` change points of the RAW 1-minute series.
    raw_max_by_day: dict[dt.date, tuple[tuple[int, float], ...]] = field(default_factory=dict)
    #: The same change points over the 5-minute whole-degF grid rows.
    five_min_max_by_day: dict[dt.date, tuple[tuple[int, float], ...]] = field(default_factory=dict)
    counts: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True, slots=True)
class RoutineMinute:
    """The modal report minute of one station's routine reports, with its support."""

    minute: int
    n: int
    share: float
    histogram: dict[int, int]


def modal_routine_minute_by_station(
    report_times: Mapping[str, Iterable[dt.datetime]],
) -> dict[str, RoutineMinute]:
    """The modal minute-of-hour of each station's routine report times (ties: lower minute).

    Stations without a report are omitted. The result is REPORTED for the coordinator to pin; it
    is never applied automatically.
    """
    out: dict[str, RoutineMinute] = {}
    for icao, times in report_times.items():
        histogram = Counter(when.minute for when in times)
        if not histogram:
            continue
        top = max(histogram.values())
        minute = min(m for m, count in histogram.items() if count == top)
        total = sum(histogram.values())
        out[icao] = RoutineMinute(minute, total, top / total, dict(sorted(histogram.items())))
    return out


def routine_minute_pin_suggestion(modal: Mapping[str, RoutineMinute]) -> dict[str, int]:
    """The ``obs_routine_minute_by_station`` pin value the modal minutes would give."""
    return {icao: entry.minute for icao, entry in sorted(modal.items())}


def whole_f_to_c_tenths(tmpf: int) -> int:
    """Whole degF as the integer tenths of a degree C a METAR ``T`` group carries."""
    return math.floor((tmpf - 32) * 50 / 9 + 0.5)


def live_quantised_f(tmpf: float) -> int:
    """``tmpf`` through the live function; refuses anything the round trip does not reproduce."""
    if not math.isfinite(tmpf) or tmpf != math.floor(tmpf):
        raise ObsQuantisationError(
            f"tmpf {tmpf!r} is not a whole degF; the live path cannot be reproduced from it"
        )
    whole = int(tmpf)
    quantised = round_half_up_f(whole_f_to_c_tenths(whole))
    if quantised != whole:
        raise ObsQuantisationError(
            f"tmpf {whole} round-trips to {quantised} through the live quantisation; refusing"
        )
    return quantised


def raw_running_max_at(changes: Sequence[tuple[int, float]], anchor_ns: int) -> float | None:
    """The raw 1-minute running max at ``anchor_ns`` (descriptive arm), or ``None``."""
    stamps = [ts for ts, _value in changes]
    index = bisect_right(stamps, anchor_ns)
    return changes[index - 1][1] if index else None


def _parse_row(valid: str, raw: str) -> tuple[dt.datetime, float]:
    try:
        when = dt.datetime.fromisoformat(valid).replace(tzinfo=dt.UTC)
        return when, float(raw)
    except ValueError as exc:
        raise ObsQuantisationError(f"unparseable archive row {valid!r}/{raw!r}: {exc}") from exc


def _check_tgroup_agrees(row: RoutineMetar, tmpf: int) -> None:
    """A T-group row's stored ``tmpf`` must be ``round_half_up_f`` of its tenths (STOP rule)."""
    if row.tgroup_c is None:
        raise ObsQuantisationError(f"{row.valid_utc}: a tgroup row carries no T-group value")
    quantised = round_half_up_f(round(row.tgroup_c * 10))
    if quantised != tmpf:
        raise ObsQuantisationError(
            f"{row.valid_utc}: T group {row.tgroup_c} C quantises to {quantised} F but the store "
            f"holds {tmpf} F; refusing"
        )


def _routine_window(
    year: int, cutoff_ns_by_day: Mapping[dt.date, int]
) -> tuple[dt.datetime, dt.datetime]:
    """The UTC window to request: the year, no later than the last cutoff, below the holdout."""
    last_ns = max(cutoff_ns_by_day.values(), default=0)
    latest = dt.datetime.fromtimestamp(last_ns // _NS, dt.UTC) + dt.timedelta(minutes=1)
    sealed = dt.datetime.combine(HOLDOUT_START, dt.time(), dt.UTC)
    start = dt.datetime(year, 1, 1, tzinfo=dt.UTC)
    return start, min(dt.datetime(year + 1, 1, 1, tzinfo=dt.UTC), latest, sealed)


def read_routine_obs_year(
    root: Path,
    icao: str,
    year: int,
    *,
    std_utc_offset_hours: float,
    routine_minute: int,
    lag_ns: int,
    cutoff_ns_by_day: Mapping[dt.date, int],
) -> RoutineObsYear:
    """One station-year of routine-METAR readings for the requested days, up to each day's cutoff.

    ``cutoff_ns_by_day`` names the days to keep and, per day, the latest instant any anchor needs;
    every other row is dropped (counted). Of the kept rows: ``missing`` ones are counted and
    skipped (never imputed), rows at another minute than ``routine_minute`` are counted as
    ``routine_pin_minute_excluded``, ``column``-sourced ones are used and counted, and every used
    row is counted in ``routine_rows_used``. A missing or corrupt store year raises
    :class:`ObsStoreError` (nothing is fabricated); the sealed holdout is never requested.
    """
    # Lazy: metar_routine_store -> metar_routine_minute_probe -> this module (modal helpers) and
    # the builder, so a top-level import here would be circular.
    from scripts.archive.metar_routine_store import RoutineMetarError, read_routine_metar

    out = RoutineObsYear()
    start, end = _routine_window(year, cutoff_ns_by_day)
    try:
        rows = read_routine_metar(icao, start, end, root) if end > start else []
    except RoutineMetarError as exc:
        raise ObsStoreError(f"{icao} {year}: {exc}") from exc
    offset = dt.timedelta(hours=std_utc_offset_hours)
    readings: dict[dt.date, list[ObsReading]] = {}
    for row in rows:
        ts_ns = int(row.valid_utc.timestamp()) * _NS
        cutoff = cutoff_ns_by_day.get((row.valid_utc + offset).date())
        if cutoff is None:
            out.counts["day_not_requested"] += 1
            continue
        if ts_ns > cutoff:
            out.counts["after_cutoff"] += 1
            continue
        if row.tmpf is None or row.tmpf_source == "missing":
            out.counts["routine_missing"] += 1
            continue
        if row.valid_utc.minute != routine_minute:
            out.counts["routine_pin_minute_excluded"] += 1
            continue
        if row.tmpf_source == "tgroup":
            _check_tgroup_agrees(row, row.tmpf)
        else:
            out.counts["routine_column_sourced"] += 1
        out.counts["routine_rows_used"] += 1
        readings.setdefault((row.valid_utc + offset).date(), []).append(
            ObsReading(
                ts_ns=ts_ns,
                available_at_ns=ts_ns + lag_ns,
                temp_f=float(row.tmpf),
                source=OBS_SOURCE_LABEL,
            )
        )
    out.readings_by_day = {day: tuple(items) for day, items in readings.items()}
    return out


def read_onemin_arms_year(
    cache: ArchiveCache,
    icao: str,
    year: int,
    *,
    std_utc_offset_hours: float,
    cutoff_ns_by_day: Mapping[dt.date, int],
) -> OneMinArms:
    """The NON-METAR descriptive arms of one station-year of the 1-minute archive.

    Neither arm feeds a feature (FB-R15). An unavailable year payload yields empty arms with
    ``onemin_year_payload_unavailable`` counted, never an exception (KNYC has no 1-min archive).
    """
    out = OneMinArms()
    try:
        body = cache.read(iem_asos_1min_request(icao, year))
    except ArchiveCacheError:
        out.counts["onemin_year_payload_unavailable"] += 1
        return out
    offset = dt.timedelta(hours=std_utc_offset_hours)
    grid_ns = DESCRIPTIVE_FIVE_MIN_SECONDS * _NS
    raw_changes: dict[dt.date, list[tuple[int, float]]] = {}
    five_changes: dict[dt.date, list[tuple[int, float]]] = {}
    running: dict[dt.date, float] = {}
    running_five: dict[dt.date, float] = {}
    previous_ns = -1
    stream = io.TextIOWrapper(io.BytesIO(body), encoding="utf-8", newline="")
    reader = csv.reader(stream)
    header = next(reader, None)
    if header is None or "valid(UTC)" not in header or "tmpf" not in header:
        raise ObsQuantisationError(f"{icao} {year}: the archive header has no valid(UTC)/tmpf")
    i_valid, i_temp = header.index("valid(UTC)"), header.index("tmpf")
    for row in reader:
        raw = row[i_temp].strip()
        if not raw or raw == "M":
            out.counts["onemin_missing_tmpf"] += 1
            continue
        when, tmpf = _parse_row(row[i_valid], raw)
        ts_ns = int(when.timestamp()) * _NS
        if ts_ns < previous_ns:
            out.counts["onemin_out_of_order"] += 1
            continue
        previous_ns = ts_ns
        quantised = float(live_quantised_f(tmpf))  # the STOP rule applies to every row
        day = (when + offset).date()
        cutoff = cutoff_ns_by_day.get(day)
        if cutoff is None or ts_ns > cutoff:
            continue
        if quantised > running.get(day, -math.inf):
            running[day] = quantised
            raw_changes.setdefault(day, []).append((ts_ns, quantised))
        if ts_ns % grid_ns == 0 and quantised > running_five.get(day, -math.inf):
            running_five[day] = quantised
            five_changes.setdefault(day, []).append((ts_ns, quantised))
    out.raw_max_by_day = {day: tuple(items) for day, items in raw_changes.items()}
    out.five_min_max_by_day = {day: tuple(items) for day, items in five_changes.items()}
    return out
