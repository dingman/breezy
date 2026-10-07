"""F13 Phase A feature build: the ``obs_so_far`` reader (FB-R13, supersedes FB-R3's 5-min cadence).

``obs_so_far`` is defined on ROUTINE hourly METAR readings only, for training and for any future
serving (L-13: no train/serve skew). The live path mixes METAR-exact rows with NWS integer-C
interval rows at a 5-minute cadence; the interval rows cannot be reproduced from the whole-degF
1-minute archive, so they are excluded on both sides. The live path, cited here and imported
nowhere:

* ``breezy.ingest.iem_observations`` / ``breezy.ingest.nws_observations`` turn a METAR ``T`` group
  (tenths of a degree C) into a ``StationObservation`` (``is_metar``);
* ``breezy.strategy.weather_common.running_extreme.RunningExtremeAccumulator`` keeps the climate
  day's running max and quantises each row with ``breezy.domain.temperature.round_half_up_f``
  (``floor(c_tenths / 10 * 9 / 5 + 32 + 0.5)``), on the local STANDARD-time day.

Each routine value is the 1-minute archive's reading at the station's routine report minute
(``obs_routine_minute_by_station`` pin), pushed through whole degF -> tenths C ->
``round_half_up_f`` (the identity on every whole degF, asserted by a test over -80..140);
``available_at`` = report time + the obs lag. A reading the round trip cannot reproduce stops the
read with :class:`ObsQuantisationError`. Two DESCRIPTIVE arms are returned and never feed a
feature: the raw 1-minute running max and the 5-minute whole-degF running max.

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
from typing import Final

_REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT), str(_REPO_ROOT / "src"), str(Path(__file__).resolve().parent)):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from forecast_conditional_corpus import (  # type: ignore[import-not-found]
    OBS_CADENCE_SECONDS,
)

from breezy.analysis.multisource_blend_features import ObsReading
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
    "ObsYear",
    "RoutineMinute",
    "live_quantised_f",
    "modal_routine_minute_by_station",
    "raw_running_max_at",
    "read_obs_year",
    "routine_minute_pin_suggestion",
    "whole_f_to_c_tenths",
]

_NS: Final[int] = 1_000_000_000
#: FB-R13: routine METAR reports arrive hourly; this is the ``obs_cadence_seconds`` pin value.
ROUTINE_OBS_CADENCE_SECONDS: Final[int] = 3600
#: The live 5-minute grid, kept only for the DESCRIPTIVE 5-min arm (imported, never re-typed).
DESCRIPTIVE_FIVE_MIN_SECONDS: Final[int] = OBS_CADENCE_SECONDS
MINUTES_PER_HOUR: Final[int] = 60
OBS_SOURCE_LABEL: Final[str] = "iem_asos_1min_whole_f_via_metar_tgroup_quantisation"
LIVE_PATH_CITATION: Final[str] = (
    "live obs path: src/breezy/ingest/iem_observations.py (METAR T-group, tenths C, "
    "station_observation_data_type) + src/breezy/ingest/nws_observations.py; quantised by "
    "src/breezy/strategy/weather_common/running_extreme.py via "
    "breezy.domain.temperature.round_half_up_f on the local standard-time climate day; FB-R13: "
    "only the routine hourly METAR reading (the station's routine report minute) is emulated, "
    "never the 5-minute NWS interval rows"
)


class ObsQuantisationError(RuntimeError):
    """The archive reading cannot be reproduced through the live quantisation: STOP (FB-R3)."""


@dataclass(slots=True)
class ObsYear:
    """One station-year reduced to the requested climate days."""

    readings_by_day: dict[dt.date, tuple[ObsReading, ...]] = field(default_factory=dict)
    #: Descriptive only: ``(ts_ns, running max degF)`` change points of the RAW 1-minute series.
    raw_max_by_day: dict[dt.date, tuple[tuple[int, float], ...]] = field(default_factory=dict)
    #: Descriptive only: the same change points over the 5-minute whole-degF grid rows.
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


def read_obs_year(
    cache: ArchiveCache,
    icao: str,
    year: int,
    *,
    std_utc_offset_hours: float,
    routine_minute: int,
    lag_ns: int,
    cutoff_ns_by_day: Mapping[dt.date, int],
) -> ObsYear:
    """One station-year of routine-METAR readings for the requested days, up to each day's cutoff.

    Only rows at ``routine_minute`` (minute of the hour) become readings; every other minute is
    counted as ``non_routine_minute`` and feeds the descriptive arms only.

    ``cutoff_ns_by_day`` names the days to keep and, per day, the latest instant any anchor needs;
    every other row is dropped (counted) as it streams past. A missing or unreadable year payload
    yields an empty :class:`ObsYear` with the reason counted, never an exception.
    """
    out = ObsYear()
    try:
        body = cache.read(iem_asos_1min_request(icao, year))
    except ArchiveCacheError:
        out.counts["year_payload_unavailable"] += 1
        return out
    offset = dt.timedelta(hours=std_utc_offset_hours)
    grid_ns = DESCRIPTIVE_FIVE_MIN_SECONDS * _NS
    readings: dict[dt.date, list[ObsReading]] = {}
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
            out.counts["missing_tmpf"] += 1
            continue
        when, tmpf = _parse_row(row[i_valid], raw)
        ts_ns = int(when.timestamp()) * _NS
        if ts_ns < previous_ns:
            out.counts["out_of_order"] += 1
            continue
        previous_ns = ts_ns
        quantised = float(live_quantised_f(tmpf))  # the STOP rule applies to every row
        day = (when + offset).date()
        cutoff = cutoff_ns_by_day.get(day)
        if cutoff is None:
            out.counts["day_not_requested"] += 1
            continue
        if ts_ns > cutoff:
            out.counts["after_cutoff"] += 1
            continue
        if quantised > running.get(day, -math.inf):
            running[day] = quantised
            raw_changes.setdefault(day, []).append((ts_ns, quantised))
        if ts_ns % grid_ns == 0 and quantised > running_five.get(day, -math.inf):
            running_five[day] = quantised
            five_changes.setdefault(day, []).append((ts_ns, quantised))
        if when.minute != routine_minute:
            out.counts["non_routine_minute"] += 1
        else:
            readings.setdefault(day, []).append(
                ObsReading(
                    ts_ns=ts_ns,
                    available_at_ns=ts_ns + lag_ns,
                    temp_f=quantised,
                    source=OBS_SOURCE_LABEL,
                )
            )
    out.readings_by_day = {day: tuple(items) for day, items in readings.items()}
    out.raw_max_by_day = {day: tuple(items) for day, items in raw_changes.items()}
    out.five_min_max_by_day = {day: tuple(items) for day, items in five_changes.items()}
    return out
