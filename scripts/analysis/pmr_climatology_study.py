"""Climatology of the late-rise hazard: ``P(M > upper_f | station, hour, season, headroom)``.

WHAT THIS IS
------------
An OFFLINE PHYSICAL/STATISTICAL MEASUREMENT over historical NWS observations.
It produces a table of conditional probabilities as a MODEL INPUT, in exactly
the shape of the two studies it sits beside --
``settlement_alignment_study.py`` and the G-01 revision-rate study behind
``docs/evidence/observation_lock_falsification_2026-08-31.md``.

WHAT THIS IS NOT
----------------
It is NOT a backtest, NOT a trading simulation, NOT a strategy evaluation.
It never constructs an order, a fill, a position, a fee, or a P&L, and it never
imports ``nautilus_trader``'s backtest machinery. NautilusTrader is the
EXCLUSIVE owner of backtesting, validation runs, position management and
execution; this script hands it a parameter table and nothing else.

THE QUANTITY
------------
Let ``R(t)`` be the running maximum temperature observed so far in a station's
climate day, as of the END of local-standard hour ``t`` (so ``R(t)`` uses only
observations whose local-standard hour is ``<= t`` -- no look-ahead). Let ``M``
be that climate day's settled maximum.

The venue's interior rungs are CLOSED 2F intervals (``gte<A>lt<B>f`` grammar),
so the rung containing ``R(t)`` is ``[floor, floor + 1]`` with
``floor = 2 * floor(R / 2)`` and ceiling ``upper_f = floor + 1``. The LOSS
EVENT is therefore ``M > upper_f`` -- a BUCKET CROSSING -- not ``M > R(t)``.
A 1F late rise from ``R = 78`` inside ``[78, 79]`` still pays in full.

PRIMARY quantity:    ``P(M > upper_f | station, hour, season, headroom)``
SECONDARY quantity:  ``P(M > R(t)  | station, hour, season, headroom)``

``headroom = upper_f - R(t)`` is an integer in ``{0, 1}`` and is the PRIMARY
conditioning variable. It is NEVER pooled: a rule that triggers the instant
``R(t)`` reaches a rung fires at ``headroom = 0``, the worst-conditioned cell,
so a pooled number silently under-prices exactly the cell that would trade
most (``docs/strategies/archive/FEEDBACK_FOR_GROK_2026-08-31.md`` section 3, item 7).
``headroom == 1 - margin`` where ``margin = R(t) - floor``; both are surfaced
because the surrounding studies speak in margins and the rung phase is not
known a priori (phase 0 and phase 1 simply swap the two labels).

TWO SETTLEMENT BASES, DELIBERATELY BOTH REPORTED
------------------------------------------------
Settlement is the NWS CLI **integer** ``tmax_f``. ``R(t)`` can only be built
from the ASOS METAR ``T`` remark group, which is a DIFFERENT INSTRUMENT read in
TENTHS OF A DEGREE C and then rounded. So
``P(M_cli > upper_f) != P(M_obs > upper_f)`` and the gap between them is a
measurable BASIS, not a rounding nuisance. Both tables are produced:

* ``cli``  -- settlement truth. ``M`` is the CLI final ``tmax_f``. This is the
  operationally correct hazard: a strategy observes ASOS ``R(t)`` and settles
  on the CLI number. ``M_cli < R(t)`` is POSSIBLE here (negative basis) and is
  counted explicitly, never folded into the crossing count.
* ``obs``  -- self-consistent physics. ``M`` is the same climate day's ASOS
  maximum, so ``M >= R(t)`` holds by construction.

There is NO third variant with ``R`` in CLI units: the archive carries one CLI
value per climate day, so an hourly CLI-basis ``R(t)`` does not exist. The
per-station basis distribution is reported instead, and if that basis is
comparable to the 2F rung width the ASOS-driven ``R(t)`` is unusable for an
integer-settled ladder -- which would be a legitimate refutation, not a defect.

TIME OF MAXIMUM -- TWO INDEPENDENT ESTIMATES
--------------------------------------------
``T*`` (the local-standard hour of the daily maximum) is estimated twice:
from the ASOS series, and from the archived CLI products' own ``MAXIMUM <v>
<h:mm> <AM|PM>`` line, whose column header declares ``TIME (LST)``. Breezy's
production parser (``breezy.normalize.cli_parse``) DISCARDS that field; this
study parses it out of the archived raw text. Where the two disagree, the
disagreement is reported rather than reconciled -- in particular, a systematic
+1h CLI-minus-ASOS offset confined to DST months would show the ``(LST)``
column label to be untrue.

NETWORK
-------
Zero network access. Every input is read from the existing
settlement-alignment archive cache; a cache miss is refused, never fetched
(``settlement_bucket_gate.read_cached``).
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Final
from zipfile import ZipFile

from archive_correction_probe import wilson_interval
from settlement_alignment_cache import (
    DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR,
    require_settlement_alignment_cache_dir,
)
from settlement_alignment_study import (
    END_DATE,
    METAR_T_RE,
    START_DATE,
    MetarTemperature,
    SiteSpec,
    afos_url,
    asos_url,
    c_tenths_to_f,
    issue_utc_from_iem_filename,
    load_sites,
    metar_temperatures,
    parse_asos_rows,
    parse_metar_t_group,
    round_half_up_f,
    split_iem_afos_products,
    wilson_lower_bound,
    year_chunks,
)
from settlement_bucket_gate import BUCKET_WIDTH_F, read_cached

from breezy.normalize.classify import ClassificationError, classify_issuance

# `_TEMPERATURE_BLOCK_RE` / `_OBSERVED_SUBSECTION_RE` are imported rather than
# re-derived ON PURPOSE. `cli_parse`'s own docstring records why: the
# TEMPERATURE (F) block also carries NORMAL and RECORD sub-blocks with their
# OWN `MAXIMUM` rows, so anything reading a MAXIMUM line must anchor on the
# observed YESTERDAY/TODAY subsection and nowhere else. Writing a second
# extractor here is exactly the silent mis-parse that module exists to prevent.
from breezy.normalize.cli_parse import (
    _OBSERVED_SUBSECTION_RE,
    _TEMPERATURE_BLOCK_RE,
    CliParseError,
    parse_cli_product,
)
from breezy.normalize.climate_day import standard_time_zone

# Re-exported so the passthroughs are intentional under strict no-implicit-reexport.
__all__ = [
    "BUCKET_WIDTH_F",
    "METAR_T_RE",
    "Cell",
    "CliRecord",
    "ExceedanceCase",
    "RunningMaxDay",
    "aggregate",
    "bucket_floor_f",
    "bucket_upper_f",
    "build_exceedance_cases",
    "build_running_max_days",
    "c_tenths_to_f",
    "crosses_bucket",
    "headline_verdict",
    "headroom_f",
    "is_complete_day",
    "local_standard_hour",
    "margin_f",
    "metar_temperatures",
    "parse_cli_max_time",
    "parse_metar_t_group",
    "resolution_floor",
    "round_half_up_f",
    "season_for",
    "wilson_interval",
    "wilson_lower_bound",
    "wilson_upper",
]

import re

DEFAULT_OUTPUT: Final[Path] = Path("docs/evidence/pmr_climatology_2026-09-01.md")
DEFAULT_CACHE_DIR: Final[Path] = DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR

#: Local-standard hours in a climate day. A day is used only if EVERY one of
#: them carries at least one observation, so `R(t)` is defined at every `t` and
#: the hour axis is never silently ragged.
HOURS_PER_DAY: Final[int] = 24

SEASONS: Final[tuple[str, ...]] = ("DJF", "MAM", "JJA", "SON")
_SEASON_BY_MONTH: Final[dict[int, str]] = {
    12: "DJF", 1: "DJF", 2: "DJF",
    3: "MAM", 4: "MAM", 5: "MAM",
    6: "JJA", 7: "JJA", 8: "JJA",
    9: "SON", 10: "SON", 11: "SON",
}

#: The level the §0.1 headline is stated at. A readout point, not a
#: threshold this study tunes toward or passes judgement against.
HEADLINE_LEVEL: Final[float] = 0.05

#: Reference levels the report scans for. These are DESCRIPTIVE readout points,
#: not thresholds this study tunes toward or passes judgement against.
REFERENCE_LEVELS: Final[tuple[float, ...]] = (0.05, 0.01, 0.005, 0.001)

# -- Pre-registered decision rules (fixed BEFORE the corpus was read) ---------

#: Pre-registration 1. If `P(T* > 17:00 LST) > 0.05` at MDW, MIA or NYC, a
#: clock-based "the peak already happened" rule is PHYSICALLY FALSE there.
PREREG_LATE_PEAK_HOUR: Final[int] = 17
PREREG_LATE_PEAK_RATE: Final[float] = 0.05
PREREG_LATE_PEAK_STATIONS: Final[tuple[str, ...]] = ("MDW", "MIA", "NYC")

#: Pre-registration 2. If `T*` is BIMODAL at LAX or SFO, a single-hour
#: threshold is false there regardless of its value. Bimodal, stated as an
#: objective criterion so the verdict is not an eyeball call: the hour
#: histogram has >= 2 local maxima at least `_SEPARATION` hours apart, each
#: carrying >= `_MIN_PEAK_SHARE` of the season's days, with the minimum
#: between them <= `_TROUGH_SHARE` of the SMALLER peak.
PREREG_BIMODAL_STATIONS: Final[tuple[str, ...]] = ("LAX", "SFO")
PREREG_BIMODAL_SEPARATION_HOURS: Final[int] = 3
PREREG_BIMODAL_MIN_PEAK_SHARE: Final[float] = 0.10
PREREG_BIMODAL_TROUGH_SHARE: Final[float] = 0.60

#: Pre-registration 3. A CLI final is IMPLAUSIBLE against its own ASOS series
#: when its `tmax_f` exceeds the whole climate day's ASOS maximum by more than
#: this, or exceeds every ASOS reading within +/-30 min of its own stated time
#: by more than this. Implausible records are REPORTED AND KEPT -- they are the
#: hazard (MDW 2021-12-30: `MAXIMUM 55  7:11 AM`, final 39, no correction flag).
PREREG_IMPLAUSIBLE_MARGIN_F: Final[int] = 5
PREREG_IMPLAUSIBLE_WINDOW_MINUTES: Final[int] = 30

#: `MAXIMUM <token> <time> <AM|PM>` inside the observed subsection.
#:
#: TWO time spellings, because the offices do not agree and reading only one
#: silently drops a whole station. Verified in the archive: KLOT prints
#: `MAXIMUM 30   2:52 PM` (`CLIMDW_202101010637.txt`) while KOKX prints
#: `MAXIMUM 48    602 AM` (`CLINYC_202101010622.txt`) with no colon at all.
#:
#: Anchored to ONE LINE (`[ \t]`, never `\s`, which would span a newline and
#: let the MINIMUM row's time be read as the maximum's). The mandatory trailing
#: `AM`/`PM` is what stops a bare RECORD-column integer being read as a time.
CLI_MAX_TIME_RE: Final[re.Pattern[str]] = re.compile(
    r"MAXIMUM[ \t]+(?P<token>-?\S+)[ \t]+"
    r"(?P<time>\d{1,2}:\d{2}|\d{3,4})[ \t]*(?P<ampm>AM|PM)"
)


# ---------------------------------------------------------------------------
# Local standard time
# ---------------------------------------------------------------------------


def local_standard_hour(instant: dt.datetime, std_utc_offset_hours: float) -> int:
    """Return the local-STANDARD-time hour (0..23) containing `instant`.

    Uses the site's fixed standard offset via
    `breezy.normalize.climate_day.standard_time_zone` -- never `ZoneInfo`,
    which follows DST and would shift every hour bucket in this study by one
    across roughly two thirds of the year. This is the same convention
    `breezy.ingest.records._climate_day_end_ns` uses for the day boundary, so
    hour 23 of climate day D ends exactly at that function's instant.
    """
    return instant.astimezone(standard_time_zone(std_utc_offset_hours)).hour


def season_for(climate_day: dt.date) -> str:
    return _SEASON_BY_MONTH[climate_day.month]


# ---------------------------------------------------------------------------
# 2F rung arithmetic
# ---------------------------------------------------------------------------


def bucket_floor_f(value_f: int) -> int:
    """Floor of the 2F rung containing `value_f`, at phase 0."""
    return int(math.floor(value_f / BUCKET_WIDTH_F) * BUCKET_WIDTH_F)


def bucket_upper_f(value_f: int) -> int:
    """Ceiling (INCLUSIVE) of the 2F rung containing `value_f`.

    The venue's interior rungs are CLOSED integer intervals `[A, A+1]` under
    the `gte<A>lt<B>f` grammar, so the last value that still settles YES is
    `A + 1`, not `B`. The loss event is `M > upper_f`.
    """
    return bucket_floor_f(value_f) + int(BUCKET_WIDTH_F) - 1


def margin_f(value_f: int) -> int:
    """How far `value_f` sits ABOVE its rung's floor: 0 or 1."""
    return value_f - bucket_floor_f(value_f)


def headroom_f(value_f: int) -> int:
    """How far `value_f` sits BELOW its rung's inclusive ceiling: 0 or 1.

    The primary conditioning variable. `headroom == 0` is the cell a rule that
    fires on reaching a rung actually trades in, and it is never pooled with
    `headroom == 1`.
    """
    return bucket_upper_f(value_f) - value_f


def crosses_bucket(*, running_f: int, settled_f: int) -> bool:
    """Did the settled maximum leave the rung `running_f` sat in?

    Total on purpose: `settled_f < running_f` is impossible when both come
    from the same observations, but entirely possible when `settled_f` is the
    CLI integer and `running_f` is ASOS-derived. That case is NOT a crossing;
    it is a negative basis, and the caller counts it separately.
    """
    return settled_f > bucket_upper_f(running_f)


# ---------------------------------------------------------------------------
# Running maximum R(t)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunningMaxDay:
    """One station-climate-day's running maximum, resolved to the hour axis."""

    city: str
    climate_day: dt.date
    #: `R(t)` at the END of each local-standard hour 0..23, in whole F.
    #: `None` for hours strictly before the day's first observation.
    running_max_f: tuple[int | None, ...]
    #: The climate day's ASOS maximum, in whole F.
    observed_max_f: int
    #: The same maximum unrounded, in F, from the METAR tenths-of-C reading.
    observed_max_unrounded_f: float
    #: `T*` -- local-standard hour of the first observation attaining the day's
    #: maximum UNROUNDED reading. Deliberately NOT the rounded series: rounding
    #: to whole F creates ties, and a first-attaining rule over the rounded
    #: series breaks every one of them toward the morning, biasing `T*` hours
    #: early and manufacturing disagreement against the CLI-stated time.
    hour_of_max: int
    #: UTC instant of that observation.
    instant_of_max: dt.datetime
    #: The same statistic over the ROUNDED series -- carried only so the
    #: tie-driven gap between the two is visible rather than assumed away.
    hour_of_rounded_max: int
    observation_count: int
    covered_hours: int


def is_complete_day(day: RunningMaxDay) -> bool:
    """True when every local-standard hour carries at least one observation.

    The completeness filter is strict rather than "mostly covered": a day with
    a hole cannot state `R(t)` for the hours inside it, and a ragged hour axis
    would silently mix "no observation yet" with "no rise yet".
    """
    return day.covered_hours == HOURS_PER_DAY


def build_running_max_days(
    *,
    city: str,
    temperatures: Iterable[MetarTemperature],
    std_utc_offset_hours: float,
) -> tuple[RunningMaxDay, ...]:
    """Accumulate `R(t)` per climate day from parsed METAR temperatures.

    `R(t)` is built by a single forward pass over instants sorted ascending,
    so no observation later than `t` can influence `R(t)`. The accumulator is
    reset at every climate-day boundary -- the boundary itself comes from
    `climate_day_for_instant` inside `metar_temperatures`, i.e. local standard
    midnight, matching `_climate_day_end_ns`.
    """
    grouped: dict[dt.date, list[MetarTemperature]] = defaultdict(list)
    for temperature in temperatures:
        grouped[temperature.climate_day].append(temperature)

    days: list[RunningMaxDay] = []
    for climate_day in sorted(grouped):
        rows = sorted(grouped[climate_day], key=lambda row: row.valid_utc)
        series: list[int | None] = [None] * HOURS_PER_DAY
        covered = [False] * HOURS_PER_DAY
        running: int | None = None
        running_unrounded = -math.inf
        hour_of_max = 0
        hour_of_rounded_max = 0
        instant_of_max = rows[0].valid_utc
        previous_hour = -1
        for row in rows:
            hour = local_standard_hour(row.valid_utc, std_utc_offset_hours)
            covered[hour] = True
            # Carry the accumulator forward across hours with no observation:
            # `R` at the end of an empty hour is whatever it was at the end of
            # the previous one.
            for gap_hour in range(previous_hour + 1, hour):
                series[gap_hour] = running
            if running is None or row.rounded_f > running:
                running = row.rounded_f
                hour_of_rounded_max = hour
            if row.temp_f > running_unrounded:
                running_unrounded = row.temp_f
                hour_of_max = hour
                instant_of_max = row.valid_utc
            series[hour] = running
            previous_hour = hour
        for tail_hour in range(previous_hour + 1, HOURS_PER_DAY):
            series[tail_hour] = running

        assert running is not None  # a grouped day always has >= 1 observation
        days.append(
            RunningMaxDay(
                city=city,
                climate_day=climate_day,
                running_max_f=tuple(series),
                observed_max_f=running,
                observed_max_unrounded_f=running_unrounded,
                hour_of_max=hour_of_max,
                instant_of_max=instant_of_max,
                hour_of_rounded_max=hour_of_rounded_max,
                observation_count=len(rows),
                covered_hours=sum(covered),
            )
        )
    return tuple(days)


# ---------------------------------------------------------------------------
# The statistic
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExceedanceCase:
    """One (station, climate-day, hour) observation of the late-rise hazard."""

    city: str
    climate_day: dt.date
    season: str
    hour: int
    running_f: int
    settled_f: int
    upper_f: int
    margin_f: int
    headroom_f: int
    #: The same climate day's ASOS maximum, carried so a crossing can be
    #: attributed. On the `obs` basis this equals `settled_f`.
    observed_max_f: int
    #: PRIMARY: did the settled max leave the rung? `M > upper_f`.
    crosses_bucket: bool
    #: Of those crossings, the ones the ASOS series ITSELF already shows -- the
    #: day genuinely got hotter than the rung ceiling. A crossing that is NOT a
    #: physics crossing is a BASIS crossing: the weather stayed inside the rung
    #: and the CLI integer still landed above it. Reporting the two together
    #: presents an instrument mismatch as if it were weather.
    physics_crosses_bucket: bool
    #: SECONDARY: did the settled max merely exceed `R(t)`? `M > R(t)`.
    exceeds: bool
    #: `settled_f - running_f`. NEGATIVE is possible on the CLI basis.
    gain_f: int


def build_exceedance_cases(
    *, day: RunningMaxDay, settled_f: int
) -> tuple[ExceedanceCase, ...]:
    """One case per local-standard hour of a COMPLETE climate day."""
    if not is_complete_day(day):
        raise ValueError(
            f"{day.city} {day.climate_day.isoformat()}: not a complete climate day "
            f"({day.covered_hours}/{HOURS_PER_DAY} local-standard hours covered)"
        )
    season = season_for(day.climate_day)
    cases: list[ExceedanceCase] = []
    for hour in range(HOURS_PER_DAY):
        running = day.running_max_f[hour]
        assert running is not None  # guaranteed by is_complete_day
        cases.append(
            ExceedanceCase(
                city=day.city,
                climate_day=day.climate_day,
                season=season,
                hour=hour,
                running_f=running,
                settled_f=settled_f,
                upper_f=bucket_upper_f(running),
                margin_f=margin_f(running),
                headroom_f=headroom_f(running),
                observed_max_f=day.observed_max_f,
                crosses_bucket=crosses_bucket(running_f=running, settled_f=settled_f),
                physics_crosses_bucket=crosses_bucket(
                    running_f=running, settled_f=day.observed_max_f
                ),
                exceeds=settled_f > running,
                gain_f=settled_f - running,
            )
        )
    return tuple(cases)


CellKey = tuple[str, str, int, int]


@dataclass(frozen=True, slots=True)
class Cell:
    """One conditional cell. `n` is ALWAYS reported: a rate without it is not
    a probability."""

    city: str
    season: str
    hour: int
    headroom_f: int
    n: int
    cross_count: int
    #: Crossings the ASOS series itself already shows.
    physics_cross_count: int
    #: Crossings where the weather stayed inside the rung and the CLI integer
    #: still left it. Zero by construction on the `obs` basis.
    basis_only_cross_count: int
    exceed_count: int
    #: Days where the settled value came in BELOW `R(t)` (CLI basis only).
    negative_basis_count: int

    @property
    def cross_rate(self) -> float:
        return self.cross_count / self.n if self.n else 0.0

    @property
    def physics_cross_rate(self) -> float:
        return self.physics_cross_count / self.n if self.n else 0.0

    @property
    def basis_only_cross_rate(self) -> float:
        return self.basis_only_cross_count / self.n if self.n else 0.0

    @property
    def resolution_floor(self) -> float | None:
        """Smallest Wilson upper this cell could report -- at zero events."""
        return resolution_floor(self.n)

    @property
    def exceed_rate(self) -> float:
        return self.exceed_count / self.n if self.n else 0.0

    @property
    def cross_wilson_upper(self) -> float | None:
        return wilson_upper(self.cross_count, self.n)

    @property
    def exceed_wilson_upper(self) -> float | None:
        return wilson_upper(self.exceed_count, self.n)


def resolution_floor(total: int) -> float | None:
    """The smallest Wilson 95% upper bound a cell of size `total` can report.

    Attained at ZERO observed events, where the bound collapses to the closed
    form `z**2 / (n + z**2)`. Any reference level below this is unreachable
    with the corpus on hand -- a statement about statistical POWER, never about
    the physics. Reporting "risk never falls below 0.1%" without it would
    misread a sample-size limit as a hazard.
    """
    if total <= 0:
        return None
    return wilson_upper(0, total)


def wilson_upper(successes: int, total: int) -> float | None:
    """Wilson 95% UPPER bound -- the conservative direction for this decision.

    The quantity being bounded is a FAILURE probability, so the risk of being
    wrong lives at the top of the interval, not the bottom. Returns `None` for
    an empty cell: an upper bound on nothing is not zero, it is undefined, and
    reporting 0.0 there would read as the safest cell in the table.
    """
    if total <= 0:
        return None
    return wilson_interval(successes, total)[1]


def aggregate(cases: Iterable[ExceedanceCase]) -> dict[CellKey, Cell]:
    counts: dict[CellKey, list[int]] = defaultdict(lambda: [0, 0, 0, 0, 0, 0])
    for case in cases:
        key: CellKey = (case.city, case.season, case.hour, case.headroom_f)
        bucket = counts[key]
        bucket[0] += 1
        bucket[1] += int(case.crosses_bucket)
        bucket[2] += int(case.physics_crosses_bucket)
        bucket[3] += int(case.crosses_bucket and not case.physics_crosses_bucket)
        bucket[4] += int(case.exceeds)
        bucket[5] += int(case.gain_f < 0)
    return {
        key: Cell(
            city=key[0],
            season=key[1],
            hour=key[2],
            headroom_f=key[3],
            n=values[0],
            cross_count=values[1],
            physics_cross_count=values[2],
            basis_only_cross_count=values[3],
            exceed_count=values[4],
            negative_basis_count=values[5],
        )
        for key, values in sorted(counts.items())
    }


def merge_cells(cells: Iterable[Cell]) -> Cell | None:
    """Pool cells that already share `city`/`headroom` (e.g. across seasons).

    Never used to pool ACROSS headroom -- that is the pooling the study exists
    to refuse.
    """
    materialized = tuple(cells)
    if not materialized:
        return None
    first = materialized[0]
    return Cell(
        city=first.city,
        season="ALL",
        hour=first.hour,
        headroom_f=first.headroom_f,
        n=sum(cell.n for cell in materialized),
        cross_count=sum(cell.cross_count for cell in materialized),
        physics_cross_count=sum(cell.physics_cross_count for cell in materialized),
        basis_only_cross_count=sum(cell.basis_only_cross_count for cell in materialized),
        exceed_count=sum(cell.exceed_count for cell in materialized),
        negative_basis_count=sum(cell.negative_basis_count for cell in materialized),
    )


# ---------------------------------------------------------------------------
# CLI finals: settled value AND the time-of-max field Breezy's parser discards
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CliMaxTime:
    """The `MAXIMUM <v> <h:mm> <AM|PM>` row's time, as printed."""

    hour: int
    minute: int

    @property
    def hour_of_day(self) -> int:
        return self.hour


def parse_cli_max_time(product_text: str) -> CliMaxTime | None:
    """Extract the observed MAXIMUM's stated time from a CLI product.

    Anchored on the observed YESTERDAY/TODAY subsection of the TEMPERATURE (F)
    block, reusing `breezy.normalize.cli_parse`'s own block/subsection
    patterns, so a RECORD or NORMAL sub-block's MAXIMUM row can never be read
    instead. Returns `None` when the product prints no time (sentinel rows,
    and some preliminaries).

    The column header declares this time to be `(LST)`. That claim is NOT
    trusted here -- it is carried through unmodified so the report can measure
    it against the ASOS-derived hour.
    """
    block_match = _TEMPERATURE_BLOCK_RE.search(product_text)
    if block_match is None:
        return None
    observed_match = _OBSERVED_SUBSECTION_RE.search(block_match.group("block"))
    if observed_match is None:
        return None
    time_match = CLI_MAX_TIME_RE.search(observed_match.group("subsection"))
    if time_match is None:
        return None
    printed = time_match.group("time")
    if ":" in printed:
        hour_text, minute_text = printed.split(":", 1)
    else:
        hour_text, minute_text = printed[:-2], printed[-2:]
    hour = int(hour_text)
    minute = int(minute_text)
    if not (1 <= hour <= 12) or not (0 <= minute <= 59):
        return None
    if time_match.group("ampm") == "AM":
        hour = 0 if hour == 12 else hour
    else:
        hour = 12 if hour == 12 else hour + 12
    return CliMaxTime(hour=hour, minute=minute)


@dataclass(frozen=True, slots=True)
class CliRecord:
    """One CLI product, reduced to what this study needs.

    PRELIMINARIES ARE CARRIED, not just finals. Settlement is the final, so
    the crossing tables use finals only -- but the archetypal hazard
    (MDW 2021-12-30: `MAXIMUM 55  7:11 AM`, final 39, no correction marker)
    lives in a PRELIMINARY, and any rule reading a running max reads
    preliminaries. Scanning finals alone would miss it entirely.
    """

    city: str
    climate_day: dt.date
    #: `breezy.normalize.classify.classify_issuance` output: FINAL / PRELIMINARY / ...
    issuance: str
    tmax_f: int | None
    tmax_sentinel: str
    max_time: CliMaxTime | None
    is_correction_bbb: bool
    issued_at_utc: dt.datetime | None
    source: str


def iter_cached_cli_products(
    *, cache_dir: Path, spec: SiteSpec, start: dt.date, end: dt.date
) -> Iterator[tuple[str, str, str]]:
    """Yield `(source_url, member_name, product_text)` from the AFOS zip cache.

    Plumbing only: the URL shape, the year chunking, the cache-miss refusal and
    the product splitting are all the existing helpers. Nothing here parses a
    product.
    """
    for chunk_start, chunk_end in year_chunks(start, end):
        url = afos_url(spec.site.cli_location, chunk_start, chunk_end, limit=3_000)
        zip_bytes = read_cached(cache_dir, url, ".zip")
        with ZipFile(BytesIO(zip_bytes)) as archive:
            for member in sorted(archive.namelist()):
                raw_text = archive.read(member).decode("utf-8", errors="replace")
                for product_text in split_iem_afos_products(raw_text):
                    yield url, member, product_text


def load_cli_records(
    *, cache_dir: Path, spec: SiteSpec, start: dt.date, end: dt.date
) -> tuple[dict[dt.date, CliRecord], tuple[CliRecord, ...], Counter[str]]:
    """Return `(finals_by_day, every_record, drops)` from the AFOS zip cache.

    `finals_by_day` keeps the latest-issued FINAL per climate day -- the
    settlement value. `every_record` keeps ALL parseable products, finals and
    preliminaries alike, because the implausibility scan needs the
    preliminaries (see `CliRecord`).
    """
    finals: dict[dt.date, CliRecord] = {}
    every: list[CliRecord] = []
    drops: Counter[str] = Counter()
    floor_instant = dt.datetime.min.replace(tzinfo=dt.UTC)
    for url, member, product_text in iter_cached_cli_products(
        cache_dir=cache_dir, spec=spec, start=start, end=end
    ):
        try:
            parsed = parse_cli_product(
                product_text,
                cli_location=spec.site.cli_location,
                body_header_regex=spec.site.body_header_regex,
            )
            issuance = classify_issuance(product_text)
        except (CliParseError, ClassificationError, ValueError):
            drops["cli_parse_error"] += 1
            continue
        if parsed.summary_date < start or parsed.summary_date > end:
            continue
        record = CliRecord(
            city=spec.city,
            climate_day=parsed.summary_date,
            issuance=issuance,
            tmax_f=parsed.tmax.value_f,
            tmax_sentinel=parsed.tmax.sentinel,
            max_time=parse_cli_max_time(product_text),
            is_correction_bbb=parsed.is_correction_bbb,
            issued_at_utc=issue_utc_from_iem_filename(member),
            source=f"{url}#{member}",
        )
        every.append(record)
        if issuance != "FINAL":
            continue
        existing = finals.get(parsed.summary_date)
        if existing is None or (record.issued_at_utc or floor_instant) >= (
            existing.issued_at_utc or floor_instant
        ):
            finals[parsed.summary_date] = record
    # Counted over the SELECTED finals, never over every product seen: the same
    # climate day appears many times across retransmissions, and counting
    # per-product inflated this past the number of climate days that exist.
    drops["cli_final_without_max_time"] = sum(
        1 for final in finals.values() if final.max_time is None
    )
    return finals, tuple(every), drops


# ---------------------------------------------------------------------------
# Implausibility -- reported and KEPT, never filtered out
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImplausibleCliRecord:
    city: str
    climate_day: dt.date
    issuance: str
    cli_tmax_f: int
    asos_max_f: int
    cli_max_hour: int | None
    asos_near_stated_time_max_f: int | None
    reason: str
    source: str


def implausible_cli_records(
    *,
    days_by_date: Mapping[dt.date, RunningMaxDay],
    records: Iterable[CliRecord],
    temperatures_by_day: Mapping[dt.date, Sequence[MetarTemperature]],
    std_utc_offset_hours: float,
) -> tuple[tuple[ImplausibleCliRecord, ...], int]:
    """CLI products whose value and stated time CONTRADICT their own ASOS series.

    Returns `(flagged, uncorroborated_count)`.

    The two outcomes are kept apart on purpose. "The ASOS says something
    different" is an integrity signal; "the ASOS was not looking at that
    minute" is a CADENCE artifact of an hourly station and says nothing about
    the product. Folding the second into the first put a 1.8% bad-print rate
    on NYC that was entirely an artifact of KNYC reporting at :51.

    Flagged records are REPORTED AND KEPT -- they are the hazard, never
    outliers to exclude. MDW 2021-12-30 (`MAXIMUM 55  7:11 AM`, final 39, no
    correction marker) is the archetype, and it is a PRELIMINARY.
    """
    flagged: list[ImplausibleCliRecord] = []
    uncorroborated = 0
    window = dt.timedelta(minutes=PREREG_IMPLAUSIBLE_WINDOW_MINUTES)
    for record in sorted(records, key=lambda row: (row.climate_day, row.issuance, row.source)):
        if record.tmax_f is None:
            continue
        day = days_by_date.get(record.climate_day)
        if day is None:
            continue
        reasons: list[str] = []
        if record.tmax_f - day.observed_max_f > PREREG_IMPLAUSIBLE_MARGIN_F:
            reasons.append("exceeds_asos_daily_max")

        near_max: int | None = None
        if record.max_time is not None:
            stated_local = dt.datetime.combine(
                record.climate_day,
                dt.time(record.max_time.hour, record.max_time.minute),
                tzinfo=standard_time_zone(std_utc_offset_hours),
            )
            nearby = [
                row.rounded_f
                for row in temperatures_by_day.get(record.climate_day, ())
                if abs(row.valid_utc - stated_local) <= window
            ]
            if nearby:
                near_max = max(nearby)
                if record.tmax_f - near_max > PREREG_IMPLAUSIBLE_MARGIN_F:
                    reasons.append("exceeds_asos_at_stated_time")
            else:
                uncorroborated += 1

        if reasons:
            flagged.append(
                ImplausibleCliRecord(
                    city=record.city,
                    climate_day=record.climate_day,
                    issuance=record.issuance,
                    cli_tmax_f=record.tmax_f,
                    asos_max_f=day.observed_max_f,
                    cli_max_hour=None if record.max_time is None else record.max_time.hour,
                    asos_near_stated_time_max_f=near_max,
                    reason="+".join(reasons),
                    source=record.source,
                )
            )
    return tuple(flagged), uncorroborated


# ---------------------------------------------------------------------------
# Time-of-maximum distributions
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HourDistribution:
    label: str
    n: int
    counts: tuple[int, ...]

    def share(self, hour: int) -> float:
        return self.counts[hour] / self.n if self.n else 0.0

    def tail_share(self, hour_exclusive: int) -> float:
        if not self.n:
            return 0.0
        return sum(self.counts[hour_exclusive + 1 :]) / self.n

    def percentile_hour(self, quantile: float) -> int | None:
        if not self.n:
            return None
        target = quantile * self.n
        cumulative = 0
        for hour, count in enumerate(self.counts):
            cumulative += count
            if cumulative >= target:
                return hour
        return HOURS_PER_DAY - 1


def hour_distribution(label: str, hours: Iterable[int]) -> HourDistribution:
    counts = [0] * HOURS_PER_DAY
    total = 0
    for hour in hours:
        counts[hour] += 1
        total += 1
    return HourDistribution(label=label, n=total, counts=tuple(counts))


def is_bimodal(distribution: HourDistribution) -> tuple[bool, str]:
    """Apply the PRE-REGISTERED bimodality criterion (see the constants)."""
    if distribution.n == 0:
        return False, "no data"
    shares = [distribution.share(hour) for hour in range(HOURS_PER_DAY)]
    peaks = [
        hour
        for hour in range(HOURS_PER_DAY)
        if shares[hour] >= PREREG_BIMODAL_MIN_PEAK_SHARE
        and shares[hour] >= shares[(hour - 1) % HOURS_PER_DAY]
        and shares[hour] >= shares[(hour + 1) % HOURS_PER_DAY]
    ]
    for left in peaks:
        for right in peaks:
            if right - left < PREREG_BIMODAL_SEPARATION_HOURS:
                continue
            trough = min(shares[left + 1 : right])
            smaller = min(shares[left], shares[right])
            if trough <= PREREG_BIMODAL_TROUGH_SHARE * smaller:
                return True, (
                    f"peaks at {left:02d}h ({shares[left]:.1%}) and {right:02d}h "
                    f"({shares[right]:.1%}), trough {trough:.1%}"
                )
    peak_text = ", ".join(f"{hour:02d}h {shares[hour]:.1%}" for hour in peaks) or "none"
    return False, f"qualifying peaks: {peak_text}"


# ---------------------------------------------------------------------------
# Per-station pipeline
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class StationResult:
    city: str
    std_utc_offset_hours: float
    observation_count: int
    day_count: int
    complete_day_count: int
    drops: Counter[str]
    cells_cli: dict[CellKey, Cell]
    cells_obs: dict[CellKey, Cell]
    cli_day_count: int
    basis_counts: Counter[int]
    asos_hour_of_max: dict[str, HourDistribution]
    cli_hour_of_max: dict[str, HourDistribution]
    cli_minus_asos_hour: Counter[int]
    cli_minus_asos_hour_dst: Counter[int]
    cli_minus_asos_hour_std: Counter[int]
    gain_counts_cli: dict[int, Counter[int]]
    gain_counts_obs: dict[int, Counter[int]]
    implausible: tuple[ImplausibleCliRecord, ...]
    uncorroborated_stated_times: int
    cli_missing_max_time: int


_DST_MONTHS: Final[frozenset[int]] = frozenset({4, 5, 6, 7, 8, 9, 10})


def analyse_station(*, cache_dir: Path, spec: SiteSpec) -> StationResult:
    raw = read_cached(cache_dir, asos_url(spec.iem_asos_id, START_DATE, END_DATE), ".txt")
    rows = parse_asos_rows(raw.decode("utf-8", errors="replace"))
    temperatures, drops = metar_temperatures(
        city=spec.city,
        rows=rows,
        std_utc_offset_hours=spec.std_utc_offset_hours,
    )
    in_window = tuple(
        row for row in temperatures if START_DATE <= row.climate_day <= END_DATE
    )
    del temperatures, rows, raw

    days = build_running_max_days(
        city=spec.city,
        temperatures=in_window,
        std_utc_offset_hours=spec.std_utc_offset_hours,
    )
    complete = tuple(day for day in days if is_complete_day(day))
    drops["incomplete_climate_day"] = len(days) - len(complete)

    temperatures_by_day: dict[dt.date, list[MetarTemperature]] = defaultdict(list)
    for row in in_window:
        temperatures_by_day[row.climate_day].append(row)

    finals, cli_records, cli_drops = load_cli_records(
        cache_dir=cache_dir, spec=spec, start=START_DATE, end=END_DATE
    )
    drops.update(cli_drops)
    flagged, uncorroborated = implausible_cli_records(
        days_by_date={day.climate_day: day for day in complete},
        records=cli_records,
        temperatures_by_day=temperatures_by_day,
        std_utc_offset_hours=spec.std_utc_offset_hours,
    )

    cases_cli: list[ExceedanceCase] = []
    cases_obs: list[ExceedanceCase] = []
    basis_counts: Counter[int] = Counter()
    cli_day_count = 0
    asos_hours: dict[str, list[int]] = defaultdict(list)
    cli_hours: dict[str, list[int]] = defaultdict(list)
    hour_delta: Counter[int] = Counter()
    hour_delta_dst: Counter[int] = Counter()
    hour_delta_std: Counter[int] = Counter()
    missing_max_time = 0

    for day in complete:
        season = season_for(day.climate_day)
        asos_hours[season].append(day.hour_of_max)
        cases_obs.extend(build_exceedance_cases(day=day, settled_f=day.observed_max_f))

        final = finals.get(day.climate_day)
        if final is None or final.tmax_f is None:
            drops["missing_cli_final"] += 1
            continue
        cli_day_count += 1
        basis_counts[final.tmax_f - day.observed_max_f] += 1
        cases_cli.extend(build_exceedance_cases(day=day, settled_f=final.tmax_f))
        if final.max_time is None:
            missing_max_time += 1
            continue
        cli_hours[season].append(final.max_time.hour)
        delta = final.max_time.hour - day.hour_of_max
        hour_delta[delta] += 1
        if day.climate_day.month in _DST_MONTHS:
            hour_delta_dst[delta] += 1
        else:
            hour_delta_std[delta] += 1

    gain_cli: dict[int, Counter[int]] = {0: Counter(), 1: Counter()}
    for case in cases_cli:
        if case.exceeds:
            gain_cli[case.headroom_f][min(case.gain_f, 6)] += 1
    gain_obs: dict[int, Counter[int]] = {0: Counter(), 1: Counter()}
    for case in cases_obs:
        if case.exceeds:
            gain_obs[case.headroom_f][min(case.gain_f, 6)] += 1

    return StationResult(
        city=spec.city,
        std_utc_offset_hours=spec.std_utc_offset_hours,
        observation_count=len(in_window),
        day_count=len(days),
        complete_day_count=len(complete),
        drops=drops,
        cells_cli=aggregate(cases_cli),
        cells_obs=aggregate(cases_obs),
        cli_day_count=cli_day_count,
        basis_counts=basis_counts,
        asos_hour_of_max={
            season: hour_distribution(f"{spec.city} {season} ASOS", hours)
            for season, hours in sorted(asos_hours.items())
        },
        cli_hour_of_max={
            season: hour_distribution(f"{spec.city} {season} CLI", hours)
            for season, hours in sorted(cli_hours.items())
        },
        cli_minus_asos_hour=hour_delta,
        cli_minus_asos_hour_dst=hour_delta_dst,
        cli_minus_asos_hour_std=hour_delta_std,
        gain_counts_cli=gain_cli,
        gain_counts_obs=gain_obs,
        implausible=flagged,
        uncorroborated_stated_times=uncorroborated,
        cli_missing_max_time=missing_max_time,
    )


def pool_seasons(cells: Mapping[CellKey, Cell], *, city: str) -> dict[CellKey, Cell]:
    """Pool a station's cells across SEASONS only. Headroom stays split."""
    pooled: dict[CellKey, Cell] = {}
    for hour in range(HOURS_PER_DAY):
        for headroom in (0, 1):
            members = [
                cells[(city, season, hour, headroom)]
                for season in SEASONS
                if (city, season, hour, headroom) in cells
            ]
            merged = merge_cells(members)
            if merged is not None:
                pooled[(city, "ALL", hour, headroom)] = merged
    return pooled


@dataclass(frozen=True, slots=True)
class HeadlineVerdict:
    """Does an hour exist after which the crossing risk stays below `level`?"""

    city: str
    headroom_f: int
    level: float
    reached: bool
    hour: int | None
    #: True when `level` sits BELOW the cells' resolution floor, i.e. the corpus
    #: could not have answered the question either way. A verdict must never
    #: read as a physical finding when it is really a sample-size limit.
    underpowered: bool
    detail: str


def headline_verdict(
    cells: Mapping[CellKey, Cell],
    *,
    city: str,
    season: str,
    headroom: int,
    level: float,
) -> HeadlineVerdict:
    """`season` is REQUIRED, never defaulted: a season that matches no cell
    silently yields an empty size list and a confident REFUTED verdict built
    on nothing. Making the caller name it turns that into a visible mistake."""
    if not any(key[0] == city and key[1] == season for key in cells):
        raise ValueError(
            f"no cells for city={city!r} season={season!r}; "
            f"a verdict over an empty selection is not a verdict"
        )
    sizes = [
        cell.n
        for key, cell in cells.items()
        if key[0] == city and key[1] == season and key[3] == headroom and cell.n
    ]
    floor = resolution_floor(min(sizes)) if sizes else None
    underpowered = floor is not None and level < floor
    hour = first_hour_below(cells, city=city, season=season, headroom=headroom, level=level)
    if underpowered:
        return HeadlineVerdict(
            city=city,
            headroom_f=headroom,
            level=level,
            reached=False,
            hour=None,
            underpowered=True,
            detail=(
                f"UNDERPOWERED: {level:.3%} is below this corpus's resolution floor "
                f"of {floor:.3%} (smallest cell n={min(sizes)}); the question cannot "
                f"be answered either way from these data"
            ),
        )
    if hour is None:
        return HeadlineVerdict(
            city=city,
            headroom_f=headroom,
            level=level,
            reached=False,
            hour=None,
            underpowered=False,
            detail=(
                f"REFUTED: no hour exists after which the Wilson-95% upper bound "
                f"stays at or below {level:.3%} for the rest of the climate day"
            ),
        )
    return HeadlineVerdict(
        city=city,
        headroom_f=headroom,
        level=level,
        reached=True,
        hour=hour,
        underpowered=False,
        detail=(
            f"from {hour:02d}h local standard the bound stays at or below {level:.3%}"
        ),
    )


def first_hour_below(
    cells: Mapping[CellKey, Cell],
    *,
    city: str,
    season: str,
    headroom: int,
    level: float,
) -> int | None:
    """First hour from which the Wilson UPPER bound stays at or below `level`.

    "Stays" is the operative word: a single hour dipping under a level and
    popping back out is not an hour after which the risk is small.
    """
    # A missing or empty cell counts as NOT below: an unknown hour cannot be
    # claimed as safe, and treating it as safe is exactly how a coverage hole
    # turns into a confident answer.
    below: list[bool] = []
    for hour in range(HOURS_PER_DAY):
        cell = cells.get((city, season, hour, headroom))
        if cell is None or cell.n == 0:
            below.append(False)
            continue
        bound = cell.cross_wilson_upper
        below.append(bound is not None and bound <= level)
    for hour in range(HOURS_PER_DAY):
        if all(below[hour:]):
            return hour
    return None


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _int_or_na(value: int | None) -> str:
    return "n/a" if value is None else str(value)


def _mean_delta(counts: Counter[int]) -> float:
    total = sum(counts.values())
    if not total:
        return 0.0
    return sum(delta * count for delta, count in counts.items()) / total


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.3f}%"


def _cell_row(cell: Cell) -> str:
    return (
        f"| {cell.city} | {cell.season} | {cell.hour:02d} | {cell.headroom_f} | {cell.n} | "
        f"{cell.cross_count} | {_pct(cell.cross_rate)} | {_pct(cell.cross_wilson_upper)} | "
        f"{cell.physics_cross_count} | {cell.basis_only_cross_count} | "
        f"{cell.exceed_count} | {_pct(cell.exceed_rate)} | {_pct(cell.exceed_wilson_upper)} | "
        f"{cell.negative_basis_count} | {_pct(cell.resolution_floor)} |"
    )


_CELL_HEADER: Final[str] = (
    "| station | season | hour | headroom | n | cross | cross rate | cross Wilson-95 UPPER | "
    "of which physics | of which basis-only | "
    "exceed | exceed rate | exceed Wilson-95 UPPER | neg-basis | resolution floor |\n"
    "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"
)


def _distribution_row(distribution: HourDistribution) -> str:
    percentiles = [distribution.percentile_hour(q) for q in (0.05, 0.25, 0.5, 0.75, 0.95)]
    rendered = " / ".join("n/a" if hour is None else f"{hour:02d}" for hour in percentiles)
    return (
        f"| {distribution.label} | {distribution.n} | {rendered} | "
        f"{_pct(distribution.tail_share(PREREG_LATE_PEAK_HOUR))} |"
    )


#: `(label, selector)` pairs for the two settlement bases. Named rather than
#: written as inline lambdas so the selector's type is checkable.
_CellSelector = Callable[["StationResult"], dict[CellKey, Cell]]
_BASES: Final[tuple[tuple[str, _CellSelector], ...]] = (
    ("cli", lambda result: result.cells_cli),
    ("obs", lambda result: result.cells_obs),
)


def build_report(
    results: Sequence[StationResult], *, generated_at: dt.datetime, cache_dir: Path
) -> str:
    lines: list[str] = []
    add = lines.append

    add("# P(M > rung ceiling) climatology — the late-rise hazard, measured")
    add("")
    add(f"Generated {generated_at.isoformat()} from "
        f"`scripts/analysis/pmr_climatology_study.py`.")
    add(f"Archive cache: `{cache_dir}` (zero network; cache misses are refused).")
    add(f"Corpus window: {START_DATE.isoformat()} .. {END_DATE.isoformat()}.")
    add("")
    add("## 0. What this document is")
    add("")
    add("A physical/statistical measurement over historical NWS observations, in the")
    add("shape of `settlement_alignment_study.py` and the G-01 revision-rate study. It")
    add("is **not** a backtest, **not** a trading simulation and **not** a strategy")
    add("evaluation: no order, fill, position, fee or P&L appears anywhere in the")
    add("pipeline that produced it. NautilusTrader is the exclusive owner of")
    add("backtesting and execution; this is a parameter table it may later consume.")
    add("")
    add("### Definitions")
    add("")
    add("* `R(t)` — running maximum, in whole °F, as of the **end of local-standard")
    add("  hour `t`**. Built by one forward pass over instants sorted ascending, so no")
    add("  observation after `t` can influence it. Reset at local-standard midnight,")
    add("  the same boundary `breezy.ingest.records._climate_day_end_ns` defines.")
    add("* Rung — the venue's interior contracts are **closed** 2°F intervals")
    add("  `[A, A+1]` (`gte<A>lt<B>f` grammar). `upper_f = A + 1` is the last value")
    add("  that still settles YES.")
    add("* **`headroom = upper_f − R(t)` ∈ {0, 1}** — the primary conditioning")
    add("  variable, never pooled. A rule that fires on reaching a rung fires at")
    add("  `headroom = 0`.")
    add("* **Crossing** (PRIMARY) — `M > upper_f`. The loss event.")
    add("* Exceedance (SECONDARY) — `M > R(t)`. Reported for completeness; a 1°F rise")
    add("  inside the rung is harmless.")
    add("* `margin = R(t) − A = 1 − headroom`, carried because the surrounding studies")
    add("  speak in margins.")
    add("* Wilson 95% **UPPER** bounds throughout. The quantity is a failure")
    add("  probability, so the risk of being wrong is at the top of the interval. An")
    add("  empty cell reports `n/a`, never `0`.")
    add("* Completeness — a climate day is used only when **all 24** local-standard")
    add("  hours carry at least one observation.")
    add("")
    add("### Two settlement bases")
    add("")
    add("| basis | `M` | note |")
    add("|---|---|---|")
    add("| `cli` (PRIMARY) | NWS CLI final `tmax_f` (integer) | settlement truth; "
        "`M < R(t)` possible and counted as neg-basis, never as a crossing |")
    add("| `obs` (SECONDARY) | same day's ASOS maximum | self-consistent; `M >= R(t)` "
        "by construction |")
    add("")
    add("`R(t)` exists only in ASOS units — the archive carries one CLI value per")
    add("climate day, so an hourly CLI-basis `R(t)` is not measurable. §2 reports the")
    add("METAR↔CLI basis instead.")
    add("")

    # -- 0.1 computed headline ----------------------------------------------
    add("## 0.1 Headline — computed, not asserted")
    add("")
    add("Every line below is generated from the cells in §7. The reference level is")
    add(f"{HEADLINE_LEVEL:.0%} on the Wilson-95% **upper** bound of the crossing rate, held")
    add("for the rest of the climate day; seasons are pooled here for resolution")
    add("(§5.0), headroom never is. `REFUTED` means no such hour exists.")
    add("")
    add("| station | basis | headroom | verdict | detail |")
    add("|---|---|---:|---|---|")
    for result in results:
        for basis_label, extract in _BASES:
            pooled = pool_seasons(extract(result), city=result.city)
            for headroom in (0, 1):
                verdict = headline_verdict(
                    pooled,
                    city=result.city,
                    season="ALL",
                    headroom=headroom,
                    level=HEADLINE_LEVEL,
                )
                label = (
                    f"**{verdict.hour:02d}h**"
                    if verdict.reached
                    else ("UNDERPOWERED" if verdict.underpowered else "**REFUTED**")
                )
                add(
                    f"| {result.city} | {basis_label} | {headroom} | {label} | "
                    f"{verdict.detail} |"
                )
    add("")
    add("And the reason the `cli` and `obs` columns differ — the residual risk once")
    add("the climate day is physically over (hour 23), where the `obs` basis has")
    add("**zero** crossings by construction:")
    add("")
    add("| station | headroom | `cli` cross rate @23h | of which late-day physics | "
        "of which METAR↔CLI basis |")
    add("|---|---:|---:|---:|---:|")
    for result in results:
        pooled = pool_seasons(result.cells_cli, city=result.city)
        for headroom in (0, 1):
            cell = pooled.get((result.city, "ALL", 23, headroom))
            if cell is None:
                continue
            add(
                f"| {result.city} | {headroom} | {_pct(cell.cross_rate)} | "
                f"{_pct(cell.physics_cross_rate)} | {_pct(cell.basis_only_cross_rate)} |"
            )
    add("")

    # -- 1. corpus -----------------------------------------------------------
    add("## 1. Corpus and denominators")
    add("")
    add("| station | std offset | METAR obs | climate days | complete days | "
        "complete+CLI days | case rows (cli) | case rows (obs) |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|")
    for result in results:
        add(
            f"| {result.city} | {result.std_utc_offset_hours:+.0f} | "
            f"{result.observation_count} | {result.day_count} | "
            f"{result.complete_day_count} | {result.cli_day_count} | "
            f"{sum(cell.n for cell in result.cells_cli.values())} | "
            f"{sum(cell.n for cell in result.cells_obs.values())} |"
        )
    add("")
    add("Drop reasons (every row that did not reach a case):")
    add("")
    add("| station | reason | count |")
    add("|---|---|---:|")
    for result in results:
        for reason, count in sorted(result.drops.items()):
            if count:
                add(f"| {result.city} | {reason} | {count} |")
    add("")

    # -- 2. basis ------------------------------------------------------------
    add("## 2. METAR↔CLI basis — the unit mismatch, measured")
    add("")
    add("`CLI tmax_f − ASOS daily max`, in whole °F, over complete days that also")
    add("carry a CLI final. A basis comparable to the 2°F rung width makes an")
    add("ASOS-driven `R(t)` unusable for an integer-settled ladder.")
    add("")
    add("| station | n | mean | median | sd | P(=0) | P(|Δ|≥1) | P(|Δ|≥2) | min | max |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for result in results:
        counts = result.basis_counts
        total = sum(counts.values())
        if not total:
            add(f"| {result.city} | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a |")
            continue
        values: list[int] = []
        for delta, count in counts.items():
            values.extend([delta] * count)
        exact = counts[0] / total
        ge1 = sum(count for delta, count in counts.items() if abs(delta) >= 1) / total
        ge2 = sum(count for delta, count in counts.items() if abs(delta) >= 2) / total
        add(
            f"| {result.city} | {total} | {statistics.fmean(values):+.3f} | "
            f"{statistics.median(values):+.1f} | {statistics.pstdev(values):.3f} | "
            f"{_pct(exact)} | {_pct(ge1)} | {_pct(ge2)} | {min(values):+d} | "
            f"{max(values):+d} |"
        )
    add("")
    add("Full basis histogram:")
    add("")
    add("| station | Δ °F | n | share |")
    add("|---|---:|---:|---:|")
    for result in results:
        total = sum(result.basis_counts.values())
        for delta in sorted(result.basis_counts):
            count = result.basis_counts[delta]
            add(f"| {result.city} | {delta:+d} | {count} | "
                f"{_pct(count / total if total else 0.0)} |")
    add("")

    # -- 3. time of maximum --------------------------------------------------
    add("## 3. Time of the daily maximum, `T*` — two independent estimates")
    add("")
    add("Hours are local STANDARD time. The ASOS estimate is the first observation")
    add("attaining the day's maximum UNROUNDED reading — not the rounded series,")
    add("whose ties would break toward the morning and bias `T*` hours early. The")
    add("CLI estimate is the archived product's own")
    add("`MAXIMUM <v> <h:mm> <AM|PM>` field, whose column header declares `TIME (LST)`")
    add("— a claim this study measures rather than trusts (see §3.3). Breezy's")
    add("production parser discards that field; it is parsed here from raw text.")
    add("")
    add("### 3.1 Distribution by station and season")
    add("")
    add("| series | n | T* p05 / p25 / p50 / p75 / p95 (LST hour) | "
        f"P(T* > {PREREG_LATE_PEAK_HOUR}:00) |")
    add("|---|---:|---|---:|")
    for result in results:
        for season in SEASONS:
            for source in (result.asos_hour_of_max, result.cli_hour_of_max):
                distribution = source.get(season)
                if distribution is not None:
                    add(_distribution_row(distribution))
    add("")
    add("### 3.2 Full T* hour histogram (ASOS, share of season-days)")
    add("")
    add("| station | season | n | " + " | ".join(f"{hour:02d}" for hour in range(24)) + " |")
    add("|---|---|---:|" + "---:|" * 24)
    for result in results:
        for season in SEASONS:
            distribution = result.asos_hour_of_max.get(season)
            if distribution is None:
                continue
            shares = " | ".join(
                f"{distribution.share(hour) * 100:.1f}" for hour in range(24)
            )
            add(f"| {result.city} | {season} | {distribution.n} | {shares} |")
    add("")
    add("### 3.3 CLI-stated hour minus ASOS hour — is the `(LST)` label true?")
    add("")
    add("A systematic `+1` **confined to the DST months** (Apr–Oct) would show the")
    add("CLI time to be local DAYLIGHT time despite the `(LST)` column header. An")
    add("offset present in BOTH month groups is not DST aliasing — it is an")
    add("instrument/sampling difference (the CLI max comes from 1-minute ASOS data")
    add("and, per §2, usually reads 0–1°F above the 5-minute METAR series, so it")
    add("points at a peak minute the METAR series never sampled).")
    add("")
    add("| station | n | mean Δ | mode Δ | P(Δ<0) | P(Δ=0) | P(Δ=+1) | "
        "DST-months mean Δ | DST-months mode Δ | DST P(Δ=+1) | "
        "STD-months mean Δ | STD-months mode Δ | STD P(Δ=+1) |")
    add("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for result in results:
        total = sum(result.cli_minus_asos_hour.values())
        if not total:
            add(f"| {result.city} | 0 |" + " n/a |" * 12)
            continue
        dst_total = sum(result.cli_minus_asos_hour_dst.values())
        std_total = sum(result.cli_minus_asos_hour_std.values())
        mode = result.cli_minus_asos_hour.most_common(1)[0][0]
        dst_mode = (
            result.cli_minus_asos_hour_dst.most_common(1)[0][0] if dst_total else None
        )
        std_mode = (
            result.cli_minus_asos_hour_std.most_common(1)[0][0] if std_total else None
        )
        negative = sum(
            count for delta, count in result.cli_minus_asos_hour.items() if delta < 0
        )
        add(
            f"| {result.city} | {total} | {_mean_delta(result.cli_minus_asos_hour):+.3f} | "
            f"{mode:+d} | {_pct(negative / total)} | "
            f"{_pct(result.cli_minus_asos_hour[0] / total)} | "
            f"{_pct(result.cli_minus_asos_hour[1] / total)} | "
            f"{_mean_delta(result.cli_minus_asos_hour_dst):+.3f} | "
            f"{'n/a' if dst_mode is None else f'{dst_mode:+d}'} | "
            f"{_pct(result.cli_minus_asos_hour_dst[1] / dst_total) if dst_total else 'n/a'} | "
            f"{_mean_delta(result.cli_minus_asos_hour_std):+.3f} | "
            f"{'n/a' if std_mode is None else f'{std_mode:+d}'} | "
            f"{_pct(result.cli_minus_asos_hour_std[1] / std_total) if std_total else 'n/a'} |"
        )
    add("")

    # -- 4. pre-registered verdicts -----------------------------------------
    add("## 4. Pre-registered decision rules — verdicts, reported verbatim")
    add("")
    add(f"**PR-1.** *If `P(T* > {PREREG_LATE_PEAK_HOUR}:00 LST) > "
        f"{PREREG_LATE_PEAK_RATE:.2f}` at MDW, MIA or NYC, then a clock-based "
        "\"after the peak\" rule is PHYSICALLY FALSE at that station.*")
    add("")
    add("| station | series | season | n | P(T* > 17:00) | verdict |")
    add("|---|---|---|---:|---:|---|")
    for result in results:
        if result.city not in PREREG_LATE_PEAK_STATIONS:
            continue
        for label, source in (("ASOS", result.asos_hour_of_max), ("CLI", result.cli_hour_of_max)):
            for season in ("ALL", *SEASONS):
                if season == "ALL":
                    merged_counts = [0] * HOURS_PER_DAY
                    total = 0
                    for distribution in source.values():
                        for hour in range(HOURS_PER_DAY):
                            merged_counts[hour] += distribution.counts[hour]
                        total += distribution.n
                    distribution = HourDistribution(
                        label="ALL", n=total, counts=tuple(merged_counts)
                    )
                else:
                    maybe = source.get(season)
                    if maybe is None:
                        continue
                    distribution = maybe
                share = distribution.tail_share(PREREG_LATE_PEAK_HOUR)
                prereg_verdict = (
                    "**RULE FALSE at this station**"
                    if share > PREREG_LATE_PEAK_RATE
                    else "not falsified"
                )
                add(
                    f"| {result.city} | {label} | {season} | {distribution.n} | "
                    f"{_pct(share)} | {prereg_verdict} |"
                )
    add("")
    add("**PR-2.** *If `T*` is BIMODAL at LAX or SFO, a single-hour threshold is false")
    add("there regardless of its value.* Criterion, fixed in advance: ≥2 local maxima")
    add(f"≥{PREREG_BIMODAL_SEPARATION_HOURS}h apart, each ≥"
        f"{PREREG_BIMODAL_MIN_PEAK_SHARE:.0%} of the season's days, with the trough")
    add(f"between them ≤{PREREG_BIMODAL_TROUGH_SHARE:.0%} of the smaller peak.")
    add("")
    add("| station | season | n | verdict | detail |")
    add("|---|---|---:|---|---|")
    for result in results:
        if result.city not in PREREG_BIMODAL_STATIONS:
            continue
        for season in SEASONS:
            distribution = result.asos_hour_of_max.get(season)
            if distribution is None:
                continue
            bimodal, detail = is_bimodal(distribution)
            add(
                f"| {result.city} | {season} | {distribution.n} | "
                f"{'**BIMODAL — threshold false**' if bimodal else 'unimodal'} | "
                f"{detail} |"
            )
    add("")
    add("**PR-3.** *A CLI final is implausible against its own ASOS series when its")
    add(f"`tmax_f` exceeds the day's ASOS maximum by >{PREREG_IMPLAUSIBLE_MARGIN_F}°F,")
    add(f"or exceeds every ASOS reading within ±{PREREG_IMPLAUSIBLE_WINDOW_MINUTES} min")
    add("of its own stated time by the same margin. Implausible records are REPORTED")
    add("AND KEPT — they are the hazard, not outliers.*")
    add("")
    add("Scanned over ALL parseable CLI products, PRELIMINARIES INCLUDED — the")
    add("archetype is a preliminary, and any rule reading a running max reads")
    add("preliminaries. A stated time with no ASOS observation inside the window is")
    add("counted separately as *uncorroborated*: that is a cadence artifact of an")
    add("hourly station, not a contradiction, and folding it in would put a bogus")
    add("bad-print rate on NYC alone.")
    add("")
    add("| station | complete+CLI days | implausible products | of which PRELIMINARY | "
        "rate vs day count | uncorroborated stated times | CLI finals w/o a stated time |")
    add("|---|---:|---:|---:|---:|---:|---:|")
    for result in results:
        total = result.cli_day_count
        preliminary = sum(
            1 for record in result.implausible if record.issuance != "FINAL"
        )
        add(
            f"| {result.city} | {total} | {len(result.implausible)} | {preliminary} | "
            f"{_pct(len(result.implausible) / total if total else 0.0)} | "
            f"{result.uncorroborated_stated_times} | "
            f"{result.cli_missing_max_time} |"
        )
    add("")
    add("Every implausible record (none excluded from any table above or below):")
    add("")
    add("| station | climate day | issuance | CLI tmax | stated hour (LST) | ASOS day max | "
        "ASOS near stated time | reason |")
    add("|---|---|---|---:|---:|---:|---:|---|")
    for result in results:
        for record in result.implausible:
            add(
                f"| {record.city} | {record.climate_day.isoformat()} | {record.issuance} | "
                f"{record.cli_tmax_f} | "
                f"{'n/a' if record.cli_max_hour is None else f'{record.cli_max_hour:02d}'} | "
                f"{record.asos_max_f} | "
                f"{_int_or_na(record.asos_near_stated_time_max_f)} | "
                f"{record.reason} |"
            )
    add("")

    # -- 5. headline ---------------------------------------------------------
    add("## 5. Headline — first hour after which the crossing risk stays below a level")
    add("")
    add("The hour from which the Wilson-95% **upper** bound on `P(M > upper_f)` stays")
    add("at or below each reference level for the rest of the climate day. `—` means")
    add("no such hour exists: the risk never gets that small before midnight. These")
    add("levels are readout points, not thresholds this study passes judgement")
    add("against or tunes toward.")
    add("")
    add("### 5.0 Resolution — what this corpus can and cannot resolve")
    add("")
    add("A cell with zero observed events reports a Wilson upper of exactly")
    add("`z²/(n + z²)`. That is the **resolution floor**: no reference level below it")
    add("is reachable with this corpus, however safe the physics is. Per-station,")
    add("per-season, per-headroom cells run a few hundred station-days, so levels")
    add("below roughly 1% are unreachable at that granularity — a statement about")
    add("statistical POWER, not about the hazard. §5.3 pools seasons (never")
    add("headroom) to buy resolution, at the cost of the seasonal conditioning.")
    add("")
    add("| station | median cell n (per season, per headroom) | resolution floor | "
        "pooled-season cell n | pooled resolution floor |")
    add("|---|---:|---:|---:|---:|")
    for result in results:
        sizes = sorted(cell.n for cell in result.cells_cli.values())
        median_n = int(statistics.median(sizes)) if sizes else 0
        pooled_n = median_n * len(SEASONS)
        add(
            f"| {result.city} | {median_n} | {_pct(resolution_floor(median_n))} | "
            f"{pooled_n} | {_pct(resolution_floor(pooled_n))} |"
        )
    add("")
    add("### 5.1 First hour, per station × season × headroom")
    add("")
    for basis_label, extract in _BASES:
        for headroom in (0, 1):
            add(f"**basis `{basis_label}`, headroom {headroom}**")
            add("")
            add("| station | season | "
                + " | ".join(f"≤{level:.3%}" for level in REFERENCE_LEVELS)
                + " |")
            add("|---|---|" + "---:|" * len(REFERENCE_LEVELS))
            for result in results:
                cells = extract(result)
                for season in SEASONS:
                    entries = []
                    for level in REFERENCE_LEVELS:
                        reached = first_hour_below(
                            cells,
                            city=result.city,
                            season=season,
                            headroom=headroom,
                            level=level,
                        )
                        entries.append("—" if reached is None else f"{reached:02d}h")
                    add(f"| {result.city} | {season} | " + " | ".join(entries) + " |")
            add("")

    # -- 5.2 physics vs basis at end of day ---------------------------------
    add("### 5.2 End-of-day decomposition — is the residual risk weather, or the instrument?")
    add("")
    add("At hour 23 the climate day is physically OVER: on the `obs` basis")
    add("`R(23) == M` by construction, so every `obs` crossing count here is exactly")
    add("zero. Anything left on the `cli` basis at hour 23 is therefore NOT late-day")
    add("weather — it is the METAR↔CLI instrument basis of §2 landing the settled")
    add("integer outside a rung the observations never left.")
    add("")
    add("| station | season | headroom | n | cross rate @23h | of which physics | "
        "of which basis-only | cross Wilson-95 UPPER @23h |")
    add("|---|---|---:|---:|---:|---:|---:|---:|")
    for result in results:
        for season in SEASONS:
            for headroom in (0, 1):
                cell = result.cells_cli.get((result.city, season, 23, headroom))
                if cell is None:
                    continue
                add(
                    f"| {result.city} | {season} | {headroom} | {cell.n} | "
                    f"{_pct(cell.cross_rate)} | {_pct(cell.physics_cross_rate)} | "
                    f"{_pct(cell.basis_only_cross_rate)} | "
                    f"{_pct(cell.cross_wilson_upper)} |"
                )
    add("")

    # -- 5.3 season-pooled --------------------------------------------------
    add("### 5.3 Season-pooled (headroom still never pooled)")
    add("")
    add("Four times the denominator, at the cost of the seasonal conditioning that")
    add("§4 shows to matter (MDW/NYC winters are the late-peak seasons). Reported")
    add("because §5.0 shows the per-season cells cannot resolve below ~1%; NOT a")
    add("replacement for §5.1.")
    add("")
    for basis_label, extract in _BASES:
        add(f"**basis `{basis_label}`**")
        add("")
        add("| station | headroom | "
            + " | ".join(f"≤{level:.3%}" for level in REFERENCE_LEVELS)
            + " | cross rate @23h | n @23h | resolution floor @23h |")
        add("|---|---:|" + "---:|" * (len(REFERENCE_LEVELS) + 3))
        for result in results:
            pooled = pool_seasons(extract(result), city=result.city)
            for headroom in (0, 1):
                entries = []
                for level in REFERENCE_LEVELS:
                    reached = first_hour_below(
                        pooled, city=result.city, season="ALL", headroom=headroom, level=level
                    )
                    entries.append("—" if reached is None else f"{reached:02d}h")
                last = pooled.get((result.city, "ALL", 23, headroom))
                add(
                    f"| {result.city} | {headroom} | " + " | ".join(entries) + " | "
                    + (f"{_pct(last.cross_rate)} | {last.n} | "
                       f"{_pct(last.resolution_floor)} |" if last else "n/a | 0 | n/a |")
                )
        add("")

    # -- 6. gain distribution ------------------------------------------------
    add("## 6. Conditional on an exceedance, how big is the late rise?")
    add("")
    add("`M − R(t)` restricted to cases where `M > R(t)`, per station and headroom,")
    add("capped at ≥6°F. The crossing column is the share of those exceedances that")
    add("actually left the rung — the quantity that matters.")
    add("")
    add("| basis | station | headroom | exceedances | +1 | +2 | +3 | +4 | +5 | ≥6 | "
        "crossing share of exceedances |")
    add("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    _gain_selectors: tuple[tuple[str, Callable[[StationResult], dict[int, Counter[int]]]], ...] = (
        ("cli", lambda result: result.gain_counts_cli),
        ("obs", lambda result: result.gain_counts_obs),
    )
    for (basis_label, gains), (_, cells_of) in zip(_gain_selectors, _BASES, strict=True):
        for result in results:
            table = gains(result)
            cells = cells_of(result)
            for headroom in (0, 1):
                counts = table[headroom]
                total = sum(counts.values())
                crossings = sum(
                    cell.cross_count
                    for cell in cells.values()
                    if cell.headroom_f == headroom
                )
                buckets = " | ".join(str(counts.get(gain, 0)) for gain in range(1, 7))
                add(
                    f"| {basis_label} | {result.city} | {headroom} | {total} | {buckets} | "
                    f"{_pct(crossings / total if total else 0.0)} |"
                )
    add("")

    # -- 7. full table -------------------------------------------------------
    add("## 7. Full conditional table")
    add("")
    add("Every cell, every denominator. `cross` is the PRIMARY quantity")
    add("(`M > upper_f`); `exceed` is the secondary (`M > R(t)`); `neg-basis` counts")
    add("days where the settled value came in below `R(t)` — possible on the `cli`")
    add("basis only, and never counted as a crossing.")
    add("")
    for basis_label, extract in _BASES:
        add(f"### 7.{1 if basis_label == 'cli' else 2} basis `{basis_label}`")
        add("")
        add(_CELL_HEADER)
        for result in results:
            for key in sorted(extract(result)):
                add(_cell_row(extract(result)[key]))
        add("")

    add("## 8. Limitations")
    add("")
    add("* `R(t)` is ASOS-derived and settlement is the CLI integer. §2 measures that")
    add("  basis; it is a real, irreducible source of error in any rule driven by")
    add("  `R(t)`. No hourly CLI-basis `R(t)` is measurable from this archive.")
    add("* NYC is hourly-cadence; the other four are 5-minute. An hourly station's")
    add("  `R(t)` is a coarser lower bound on the true running maximum, which biases")
    add("  its exceedance and crossing rates UPWARD relative to a 5-minute station.")
    add("  The tables are per-station and never pooled, so this does not contaminate")
    add("  the others.")
    add("* Rung phase is assumed even (`[A, A+1]`, A even). An odd-phase ladder simply")
    add("  swaps the two headroom labels; both are reported, so both phases are")
    add("  covered.")
    add("* The completeness filter is strict (all 24 hours). §1 reports what it drops.")
    add("* **Resolution floor.** A zero-event cell of size `n` reports a Wilson")
    add("  upper of `z²/(n + z²)`. With ~200–300 station-days per per-season cell")
    add("  that floor is ~1.4–2.2%, and ~0.4% season-pooled. Reference levels below")
    add("  those are unreachable HERE regardless of the physics; §5.0 tabulates it")
    add("  and §0.1 refuses to issue a verdict below it.")
    add("* **`T*` is estimated two ways and they differ by ~1h at every station, in")
    add("  BOTH DST and standard months** (§3.3). That rules out the `(LST)` label")
    add("  being a disguised daylight-time field, but it leaves the two estimates")
    add("  genuinely disagreeing; neither is adjusted to match the other.")
    add("* Preliminaries are scanned for implausibility (§4, PR-3) but the crossing")
    add("  tables use FINALS only, because the final is what settles. A rule reading")
    add("  a preliminary running max carries the PR-3 hazard rate on top of")
    add("  everything in §5.")
    add("* This study measures physics. It says nothing about whether any of it is")
    add("  tradable: no price, spread, depth, fee or fill appears in it. That question")
    add("  belongs to NautilusTrader, and to order-book data Breezy does not yet hold.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", default=str(DEFAULT_CACHE_DIR))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--station",
        action="append",
        default=None,
        help="restrict to these cities (repeatable); default is every registry site",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    cache_dir = require_settlement_alignment_cache_dir(args.cache_dir)
    sites = load_sites()
    if args.station:
        wanted = {name.upper() for name in args.station}
        sites = tuple(spec for spec in sites if spec.city.upper() in wanted)
    if not sites:
        print("no matching registry sites", file=sys.stderr)
        return 2

    results: list[StationResult] = []
    for spec in sorted(sites, key=lambda site: site.city):
        print(f"[pmr] {spec.city}: reading archive ...", file=sys.stderr, flush=True)
        results.append(analyse_station(cache_dir=cache_dir, spec=spec))
        print(
            f"[pmr] {spec.city}: {results[-1].complete_day_count} complete days, "
            f"{results[-1].cli_day_count} with a CLI final",
            file=sys.stderr,
            flush=True,
        )

    report = build_report(
        results,
        generated_at=dt.datetime.now(tz=dt.UTC).replace(microsecond=0),
        cache_dir=cache_dir,
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"[pmr] wrote {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
