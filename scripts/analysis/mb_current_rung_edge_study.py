"""M_B -- the p_hold x ask edge measurement and its kill.

Spec: ``docs/evidence/grok_mb_design_2026-09-02.md`` SS1 (archive table, bins,
pre-filter, tape join, per-station-day statistic, sample, kill sentence) and
SS2 (survivorship and latency traps). Geometry per the memo's correction:
interiors are CLOSED 2F ``[A, A+1]`` (``Rung.contains`` in
``h4_preliminary_economic_read.py``); ``m = R - A in {0, 1}``; open tails are a
separate width class, never pooled with interiors.

WHAT THIS IS
------------
A two-part descriptive measurement, exactly the shape of the studies it sits
beside (``pmr_climatology_study.py``, ``ma_prelock_winner_ask_study.py``). It
constructs no order, no fill, no position, no fee and no P&L. NautilusTrader
remains the exclusive owner of backtesting and execution.

PART A -- ARCHIVE ``p_hold`` TABLE
-----------------------------------
Reuses ``pmr_climatology_study.build_running_max_days`` and CLI finals over
the SAME corpus (``2021-01-01..2025-12-31``, complete 24h days only, dense
stations only -- NYC excluded, L-13). Historical venue listings are
unavailable, so a PROXY rung is anchored directly on ``R(t)`` at each
LST hour ``h in {12..16}``:

* interior, ``m=0``:      rung ``[R, R+1]``,  hold iff CLI in ``[R, R+1]``
* interior, ``m=1``:      rung ``[R-1, R]``,  hold iff CLI in ``[R-1, R]``
* open upper:             rung ``[R, +inf)``, hold iff CLI ``>= R``
* open lower:              skipped in this window (p_hold ~ 0 by construction)

Bins are ``(station, season, hour, width, m)``. ``n_min = 90``
(``preliminary_final_revision_rate_study.SAMPLE_FLOOR_PER_SITE``, G-01); an
empty or under-powered cell reports ``n/a``, never ``0``. Wilson 95% LOWER
bound on hold (``archive_correction_probe.wilson_interval``,
``z=1.959963984540054``).

PART B -- TAPE JOIN, CURRENT RUNG, LAGGED
-------------------------------------------
For every Depth10 instant ``t`` in ``[12:00, 17:00)`` LST on an
afternoon-covered dense station-day, the CURRENT rung is
``rung_containing(REAL_ladder, R(t))`` -- the rung ``R(t)`` is IN at ``t``,
never the eventual CLI winner (survivorship, SS2). Because we are not faster
than a market-maker (L-9), the tradeable ask is read from the SAME
instrument's first captured snapshot with ``ts_event >= t + lag`` (latency,
SS2), never at ``t`` itself. ``edge = p_hold_lower - ask - theta*ask*(1-ask)``,
undefined when the archive cell is ``n/a``. K-depth: ``ask_sz >= 1.0``
(``ma_prelock_winner_ask_study.MIN_EXECUTABLE_SIZE``).

The unit of inference is the STATION-DAY: the first lagged executable
snapshot (ask in ``(0.05, 0.95)``, size ``>= 1.0``) is the one entry a
realistic strategy would actually take, not the afternoon's cheapest ask.

KILL SENTENCE (SS1)
--------------------
Dead if, over ``>= 15`` afternoon-covered station-days, no station-day's
first lagged current-rung snapshot has Wilson-lower ``p_hold`` strictly above
``ask + 0.06*ask*(1-ask)`` with size ``>= 1.0`` -- or if every tape-visited
``(station, season, h, width, m)`` cell is ``n/a`` / ``m=1`` / open-lower.
Below 15: UNDERPOWERED, not dead.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

sys.path.insert(0, str(Path(__file__).resolve().parent))

from archive_correction_probe import wilson_interval
from cli_basis_setup_win_rate_study import DENSE_STATIONS
from h4_preliminary_economic_read import (
    DepthObservation,
    Rung,
    RunningMaxSeries,
    is_interior_rung,
    load_depth,
    parse_ladder,
    require_preflight_attestation,
    rung_containing,
    running_max_at,
)
from ma_prelock_winner_ask_study import (
    ASK_QUALIFYING_HIGH,
    ASK_QUALIFYING_LOW,
    ASOS_FETCH_END,
    ASOS_FETCH_START,
    DEFAULT_QUOTE_TAPE_CATALOG,
    DEFAULT_SETTLEMENT_CATALOG,
    MIN_AFTERNOON_COVERAGE_MINUTES,
    MIN_EXECUTABLE_SIZE,
    afternoon_coverage_minutes,
    collect_preflight_summary,
    collect_window_instants,
    discover_station_days,
    instrument_ids_for,
    load_asos_series_for_day,
    load_settled_tmax_for_day,
)
from pmr_climatology_study import (
    RunningMaxDay,
    build_running_max_days,
    is_complete_day,
    load_cli_records,
    season_for,
)
from settlement_alignment_cache import DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
from settlement_alignment_study import (
    SiteSpec,
    asos_url,
    cache_path_for_url,
    load_sites,
    metar_temperatures,
    parse_asos_rows,
)

from breezy.normalize.climate_day import standard_time_zone

__all__ = [
    "ARCHIVE_HOURS",
    "ASK_BANDS",
    "DENSE_STATIONS",
    "FEE_THETA",
    "N_MIN",
    "POOLED_KILL_N_MIN",
    "STRATUM_KILL_N_MIN",
    "SURVIVE_N_MIN",
    "WIDTH_INTERIOR",
    "WIDTH_OPEN_LOWER",
    "WIDTH_OPEN_UPPER",
    "ArchiveCell",
    "ArchiveCellKey",
    "CurrentRungTrial",
    "HoldCase",
    "MbStationDaySummary",
    "MbVerdict",
    "RealizedStratum",
    "aggregate_hold_cases",
    "all_visited_cells_dead_by_construction",
    "break_even",
    "build_archive_table",
    "build_current_rung_trials",
    "build_hold_cases",
    "build_mb_station_day_summary",
    "build_realized_stratum",
    "build_report",
    "classify_ask_band",
    "classify_width",
    "evaluate_mb",
    "evaluate_mb_family",
    "find_lagged_entry",
    "first_executable_trial",
    "gather_taken_trials",
    "is_taken_trial",
    "proxy_rung",
]

# -- Pre-registered parameters, copied from the memo, never re-derived ------

#: LST hours the archive table and the tape join both condition on.
ARCHIVE_HOURS: Final[tuple[int, ...]] = (12, 13, 14, 15, 16)

#: G-01 `SAMPLE_FLOOR_PER_SITE` -- the minimum cell size before a Wilson bound
#: is reported at all. Below it: `n/a`, never `0`.
N_MIN: Final[int] = 90

#: `src/breezy/adapters/polymarket_us/fees.py`: the venue's published maker
#: fee coefficient, `theta * C * p * (1 - p)`.
FEE_THETA: Final[float] = 0.06


def break_even(ask: float) -> float:
    """`ask + theta*ask*(1-ask)` -- the settle rate at which `ask` breaks even."""
    return ask + FEE_THETA * ask * (1.0 - ask)

#: SS1's latency sensitivity sweep. K-B must hold at 10 AND 15.
LAG_MINUTES_SWEEP: Final[tuple[int, ...]] = (5, 10, 15)
K_B_REQUIRED_LAGS: Final[tuple[int, ...]] = (10, 15)

#: Kill-amendment thresholds (`docs/evidence/grok_mb_kill_amendment_2026-09-02.md`).
#: Evidence is the REALIZED hold rate of TAKEN trials against ask+fee, never
#: the archive base rate against ask -- the base rate is unconditional and the
#: ask is forecast-conditioned, so the original screen could neither fire nor
#: confirm (audited 09-02: MDW 09-01 noon, p_hold_lower=0.594 vs ask=0.06,
#: "edge"=+0.53 by the old formula, yet the day settled ABOVE that rung).
#: Kill MAY fire at this floor (pooled or any stratum); survive needs more.
POOLED_KILL_N_MIN: Final[int] = 60
STRATUM_KILL_N_MIN: Final[int] = 60
SURVIVE_N_MIN: Final[int] = 150

#: `{(0.05,0.15], (0.15,0.30], (0.30,0.95)}` -- covers the taken screen's ask
#: band `(0.05, 0.95)` with no gap and no overlap.
ASK_BANDS: Final[tuple[tuple[float, float], ...]] = ((0.05, 0.15), (0.15, 0.30), (0.30, 0.95))

WIDTH_INTERIOR: Final[str] = "interior_2F"
WIDTH_OPEN_UPPER: Final[str] = "open_upper"
WIDTH_OPEN_LOWER: Final[str] = "open_lower"

#: Same corpus as `pmr_climatology_study.START_DATE` / `.END_DATE` -- copied
#: rather than imported (that module's `__all__` does not re-export them
#: under `--no-implicit-reexport`).
ARCHIVE_START_DATE: Final[dt.date] = dt.date(2021, 1, 1)
ARCHIVE_END_DATE: Final[dt.date] = dt.date(2025, 12, 31)

DEFAULT_ARCHIVE_CACHE_DIR: Final[Path] = DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
DEFAULT_OUTPUT: Final[Path] = (
    Path.home() / ".local/share/breezy/derived/mb_current_rung_edge_2026-09-02.md"
)


# ---------------------------------------------------------------------------
# Part A -- archive p_hold table
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HoldCase:
    """One (station, climate-day, hour, width, m) archive trial."""

    city: str
    climate_day: dt.date
    season: str
    hour: int
    running_f: int
    settled_f: int
    width: str
    m: int | None
    held: bool


def proxy_rung(*, running_f: int, width: str, m: int | None) -> Rung:
    """Synthetic rung anchored on `R(t)` -- the archive side has no real ladder.

    Both interior phases are scored because the real ladder's phase relative
    to `R` is unknown from the archive alone (`Rung phase is assumed even`
    caveat, `pmr_climatology_study`). `city`/`climate_day`/`instrument_id`
    are placeholders: only `.contains()` is used on the result.
    """
    if width == WIDTH_INTERIOR:
        if m == 0:
            lower, upper = running_f, running_f + 1
        elif m == 1:
            lower, upper = running_f - 1, running_f
        else:
            raise ValueError(f"interior width requires m in (0, 1); got {m!r}")
        return Rung(
            instrument_id="proxy-interior",
            city="",
            climate_day=dt.date.min,
            lower_f=lower,
            upper_f=upper,
        )
    if width == WIDTH_OPEN_UPPER:
        return Rung(
            instrument_id="proxy-open-upper",
            city="",
            climate_day=dt.date.min,
            lower_f=running_f,
            upper_f=None,
        )
    raise ValueError(f"unsupported proxy width for the archive side: {width!r}")


#: The three proxy cells built at every (station, day, hour). Open-lower is
#: skipped in the 12-17 LST window: its p_hold is ~0 by construction (SS1).
_ARCHIVE_PROXY_CELLS: Final[tuple[tuple[str, int | None], ...]] = (
    (WIDTH_INTERIOR, 0),
    (WIDTH_INTERIOR, 1),
    (WIDTH_OPEN_UPPER, None),
)


def build_hold_cases(
    *, day: RunningMaxDay, settled_f: int, hours: Sequence[int] = ARCHIVE_HOURS
) -> tuple[HoldCase, ...]:
    """One `HoldCase` per (hour, width, m) for a complete climate day.

    `hours` defaults to the tape join's afternoon hours; a caller may widen it
    for a general-purpose climatology, but SS1 only needs `{12..16}`.
    """
    if not is_complete_day(day):
        raise ValueError(
            f"{day.city} {day.climate_day.isoformat()}: not a complete climate day "
            f"({day.covered_hours}/24 local-standard hours covered)"
        )
    season = season_for(day.climate_day)
    cases: list[HoldCase] = []
    for hour in hours:
        running = day.running_max_f[hour]
        assert running is not None  # guaranteed by is_complete_day
        for width, m in _ARCHIVE_PROXY_CELLS:
            rung = proxy_rung(running_f=running, width=width, m=m)
            cases.append(
                HoldCase(
                    city=day.city,
                    climate_day=day.climate_day,
                    season=season,
                    hour=hour,
                    running_f=running,
                    settled_f=settled_f,
                    width=width,
                    m=m,
                    held=rung.contains(settled_f),
                )
            )
    return tuple(cases)


#: `(city, season, hour, width, m)` -- `m` is `None` for the open tails.
ArchiveCellKey = tuple[str, str, int, str, "int | None"]


@dataclass(frozen=True, slots=True)
class ArchiveCell:
    """One conditional cell. `n` is ALWAYS reported: a rate without it is not
    a probability."""

    city: str
    season: str
    hour: int
    width: str
    m: int | None
    n: int
    hold_count: int

    @property
    def hold_rate(self) -> float:
        return self.hold_count / self.n if self.n else 0.0

    @property
    def p_hold_lower(self) -> float | None:
        """Wilson 95% LOWER bound on hold, or `None` below `N_MIN`.

        `None`, never `0.0`: an under-powered cell is UNDEFINED, not the worst
        possible cell in the table (SS1: "empty cell = n/a, never 0").
        """
        if self.n < N_MIN:
            return None
        return wilson_interval(self.hold_count, self.n)[0]


def aggregate_hold_cases(cases: Iterable[HoldCase]) -> dict[ArchiveCellKey, ArchiveCell]:
    counts: dict[ArchiveCellKey, list[int]] = defaultdict(lambda: [0, 0])
    for case in cases:
        key: ArchiveCellKey = (case.city, case.season, case.hour, case.width, case.m)
        bucket = counts[key]
        bucket[0] += 1
        bucket[1] += int(case.held)
    return {
        key: ArchiveCell(
            city=key[0],
            season=key[1],
            hour=key[2],
            width=key[3],
            m=key[4],
            n=values[0],
            hold_count=values[1],
        )
        for key, values in sorted(counts.items(), key=lambda item: _sort_key(item[0]))
    }


def _sort_key(key: ArchiveCellKey) -> tuple[str, str, int, str, int]:
    return (key[0], key[1], key[2], key[3], -1 if key[4] is None else key[4])


def build_archive_table(
    days_by_city: Mapping[str, Sequence[RunningMaxDay]],
    finals_by_city: Mapping[str, Mapping[dt.date, int]],
    *,
    hours: Sequence[int] = ARCHIVE_HOURS,
) -> dict[ArchiveCellKey, ArchiveCell]:
    """Build the full archive table across every dense station in one call."""
    cases: list[HoldCase] = []
    for city, days in days_by_city.items():
        finals = finals_by_city.get(city, {})
        for day in days:
            if not is_complete_day(day):
                continue
            settled_f = finals.get(day.climate_day)
            if settled_f is None:
                continue
            cases.extend(build_hold_cases(day=day, settled_f=settled_f, hours=hours))
    return aggregate_hold_cases(cases)


# ---------------------------------------------------------------------------
# Part B -- tape join, current rung, lagged
# ---------------------------------------------------------------------------


def classify_width(rung: Rung, running_f: int) -> tuple[str, int | None]:
    """Width class and margin `m` for the REAL rung `R(t)` currently sits in.

    `m = R(t) - lower_f` on an interior rung (0 or 1, per the memo's
    geometry correction). `None` on either open tail -- an unbounded band's
    margin was never measured by Part A's proxy table.
    """
    if is_interior_rung(rung):
        assert rung.lower_f is not None
        return WIDTH_INTERIOR, running_f - rung.lower_f
    if rung.lower_f is not None and rung.upper_f is None:
        return WIDTH_OPEN_UPPER, None
    return WIDTH_OPEN_LOWER, None


def classify_ask_band(ask: float) -> tuple[float, float]:
    """Which of `ASK_BANDS` an ask in the taken screen's `(0.05, 0.95)` falls in.

    Left-open, right-closed except the top band, which stays right-open at
    the screen's own `0.95` ceiling -- together the three bands partition
    `(0.05, 0.95)` with no gap and no overlap.
    """
    if 0.05 < ask <= 0.15:
        return (0.05, 0.15)
    if 0.15 < ask <= 0.30:
        return (0.15, 0.30)
    if 0.30 < ask < 0.95:
        return (0.30, 0.95)
    raise ValueError(f"ask {ask!r} is outside the taken screen's (0.05, 0.95) band")


@dataclass(frozen=True, slots=True)
class CurrentRungTrial:
    """One (depth instant, lag) evaluation of the CURRENT rung `R(t)` is in.

    Survivorship (SS2): `held` is whether the CLI final landed in THIS rung --
    the one `R(t)` occupied AT `t` -- never the eventual winner. A day where
    `R(t)` moves to a new rung mid-afternoon yields a separate trial, and an
    earlier trial's rung can be labelled not-held even though the day's
    eventual winner rung holds.
    """

    city: str
    climate_day: dt.date
    t: dt.datetime
    ts_lst: dt.datetime
    hour_lst: int
    running_f: int
    rung_instrument_id: str
    width: str
    m: int | None
    held: bool | None
    lag_minutes: int
    entry_ts: dt.datetime | None
    entry_ask: float | None
    entry_size: float | None
    p_hold_lower: float | None
    edge: float | None

    @property
    def executable(self) -> bool:
        """K-depth + the qualifying ask band -- the realistic-entry filter."""
        return (
            self.entry_ask is not None
            and ASK_QUALIFYING_LOW < self.entry_ask < ASK_QUALIFYING_HIGH
            and self.entry_size is not None
            and self.entry_size >= MIN_EXECUTABLE_SIZE
        )


def find_lagged_entry(
    rows: Sequence[DepthObservation], *, not_before: dt.datetime
) -> DepthObservation | None:
    """First row with `ts_event >= not_before`. `rows` must be time-ascending.

    Latency trap (SS2): the entry ask is read at `t + lag`, never at `t` --
    reading at `t` is the cancel race a market-maker always wins.
    """
    for row in rows:
        if row.ts_event >= not_before:
            return row
    return None


def build_current_rung_trials(
    *,
    city: str,
    climate_day: dt.date,
    ladder: Sequence[Rung],
    depth: Mapping[str, Sequence[DepthObservation]],
    series: RunningMaxSeries,
    window_instants: Sequence[dt.datetime],
    settled_f: int | None,
    lag_minutes: int,
    std_utc_offset_hours: float,
    archive: Mapping[ArchiveCellKey, ArchiveCell],
) -> tuple[CurrentRungTrial, ...]:
    """One trial per captured window instant, time-ascending."""
    tz = standard_time_zone(std_utc_offset_hours)
    lag = dt.timedelta(minutes=lag_minutes)
    season = season_for(climate_day)
    trials: list[CurrentRungTrial] = []
    for t in sorted(window_instants):
        running = running_max_at(series, t)
        if running is None:
            continue
        rung = rung_containing(ladder, running)
        if rung is None:
            continue
        width, m = classify_width(rung, running)
        ts_lst = t.astimezone(tz)
        held = None if settled_f is None else rung.contains(settled_f)
        entry_row = find_lagged_entry(depth.get(rung.instrument_id, ()), not_before=t + lag)
        entry_ask = None if entry_row is None else entry_row.best_ask
        entry_size = (
            None
            if entry_row is None or not entry_row.ask_ladder
            else entry_row.ask_ladder[0][1]
        )
        cell = archive.get((city, season, ts_lst.hour, width, m))
        p_hold_lower = None if cell is None else cell.p_hold_lower
        edge = (
            None
            if p_hold_lower is None or entry_ask is None
            else p_hold_lower - break_even(entry_ask)
        )
        trials.append(
            CurrentRungTrial(
                city=city,
                climate_day=climate_day,
                t=t,
                ts_lst=ts_lst,
                hour_lst=ts_lst.hour,
                running_f=running,
                rung_instrument_id=rung.instrument_id,
                width=width,
                m=m,
                held=held,
                lag_minutes=lag_minutes,
                entry_ts=None if entry_row is None else entry_row.ts_event,
                entry_ask=entry_ask,
                entry_size=entry_size,
                p_hold_lower=p_hold_lower,
                edge=edge,
            )
        )
    return tuple(trials)


def first_executable_trial(trials: Sequence[CurrentRungTrial]) -> CurrentRungTrial | None:
    """The FIRST realistic entry -- never the afternoon's cheapest ask (SS1)."""
    for trial in trials:
        if trial.executable:
            return trial
    return None


# ---------------------------------------------------------------------------
# Per-station-day summary and the SS1 verdict
# ---------------------------------------------------------------------------

MbStationDayStatus = Literal["SCORED", "PENDING"]


@dataclass(frozen=True, slots=True)
class MbStationDaySummary:
    city: str
    climate_day: dt.date
    status: MbStationDayStatus
    lag_minutes: int
    afternoon_coverage_minutes: float
    trials: tuple[CurrentRungTrial, ...]
    first_executable: CurrentRungTrial | None

    @property
    def afternoon_covered(self) -> bool:
        return self.afternoon_coverage_minutes >= MIN_AFTERNOON_COVERAGE_MINUTES


def build_mb_station_day_summary(
    *,
    city: str,
    climate_day: dt.date,
    ladder: Sequence[Rung],
    depth: Mapping[str, Sequence[DepthObservation]],
    series: RunningMaxSeries,
    settled_f: int | None,
    std_utc_offset_hours: float,
    archive: Mapping[ArchiveCellKey, ArchiveCell],
    lag_minutes: int,
) -> MbStationDaySummary:
    window_instants = collect_window_instants(
        depth, climate_day=climate_day, std_utc_offset_hours=std_utc_offset_hours
    )
    coverage = afternoon_coverage_minutes(window_instants)
    if settled_f is None:
        return MbStationDaySummary(
            city=city,
            climate_day=climate_day,
            status="PENDING",
            lag_minutes=lag_minutes,
            afternoon_coverage_minutes=coverage,
            trials=(),
            first_executable=None,
        )
    trials = build_current_rung_trials(
        city=city,
        climate_day=climate_day,
        ladder=ladder,
        depth=depth,
        series=series,
        window_instants=window_instants,
        settled_f=settled_f,
        lag_minutes=lag_minutes,
        std_utc_offset_hours=std_utc_offset_hours,
        archive=archive,
    )
    return MbStationDaySummary(
        city=city,
        climate_day=climate_day,
        status="SCORED",
        lag_minutes=lag_minutes,
        afternoon_coverage_minutes=coverage,
        trials=trials,
        first_executable=first_executable_trial(trials),
    )


def _cell_is_dead_by_construction(trial: CurrentRungTrial) -> bool:
    """Pre-filter cells (SS1): open-lower and interior m=1 never trade."""
    if trial.width == WIDTH_OPEN_LOWER:
        return True
    if trial.width == WIDTH_INTERIOR and trial.m == 1:
        return True
    return trial.p_hold_lower is None


def is_taken_trial(trial: CurrentRungTrial | None) -> bool:
    """The kill-amendment's TAKEN filter, applied to a station-day's ONE

    candidate (its first lagged executable current-rung snapshot). `trial`
    already satisfies `.executable` (ask band + K-depth) by construction --
    this adds the archive-side selection: `edge > 0` and a live cell. The
    archive still SELECTS; it is no longer the evidence (kill-amendment memo).
    A station-day whose first executable snapshot fails this contributes NO
    trial at all -- there is no "search further into the day" (one trial per
    station-day, kill-amendment SS "Independence").
    """
    if trial is None:
        return False
    return (
        trial.edge is not None
        and trial.edge > 0.0
        and not _cell_is_dead_by_construction(trial)
    )


def gather_taken_trials(
    summaries: Sequence[MbStationDaySummary],
) -> tuple[CurrentRungTrial, ...]:
    """One trial per afternoon-covered, taken station-day (never snapshot-weighted)."""
    covered = (
        summary
        for summary in summaries
        if summary.status == "SCORED" and summary.afternoon_covered
    )
    taken: list[CurrentRungTrial] = []
    for summary in covered:
        trial = summary.first_executable
        if trial is not None and is_taken_trial(trial):
            taken.append(trial)
    return tuple(taken)


def all_visited_cells_dead_by_construction(summaries: Sequence[MbStationDaySummary]) -> bool:
    """Structural family-dead check: every cell the TAPE ever visited (every

    captured instant's current rung, not just the one taken per day) is
    `n/a` / `m=1` / open-lower. Distinct from the taken set, which by
    definition never contains a dead-by-construction cell -- checking only
    taken trials here would be vacuously false.
    """
    visited = tuple(
        trial
        for summary in summaries
        if summary.status == "SCORED" and summary.afternoon_covered
        for trial in summary.trials
    )
    return bool(visited) and all(_cell_is_dead_by_construction(trial) for trial in visited)


@dataclass(frozen=True, slots=True)
class RealizedStratum:
    """Realized hold rate of TAKEN trials in one stratum (pooled/station/ask-band)."""

    label: str
    n: int
    k: int
    mean_ask: float
    break_even: float
    wilson_lower: float
    wilson_upper: float

    @property
    def realized_hold_rate(self) -> float:
        return self.k / self.n if self.n else 0.0

    @property
    def cell_dead(self) -> bool:
        """Wilson-95% UPPER below this stratum's own break-even, at n >= 60."""
        return self.n >= STRATUM_KILL_N_MIN and self.wilson_upper < self.break_even

    @property
    def survives(self) -> bool:
        """Wilson-95% LOWER above break-even, at n >= 150 (pooled-scale only)."""
        return self.n >= SURVIVE_N_MIN and self.wilson_lower > self.break_even


def build_realized_stratum(
    label: str, taken: Sequence[CurrentRungTrial]
) -> RealizedStratum | None:
    """`None` for an empty stratum -- a rate over nothing is undefined, not 0."""
    priced = tuple(trial for trial in taken if trial.entry_ask is not None)
    if not priced:
        return None
    n = len(priced)
    k = sum(1 for trial in priced if trial.held)
    mean_ask = sum(trial.entry_ask for trial in priced if trial.entry_ask is not None) / n
    lower, upper = wilson_interval(k, n)
    return RealizedStratum(
        label=label,
        n=n,
        k=k,
        mean_ask=mean_ask,
        break_even=break_even(mean_ask),
        wilson_lower=lower,
        wilson_upper=upper,
    )


def _station_strata(taken: Sequence[CurrentRungTrial]) -> tuple[RealizedStratum, ...]:
    by_station: dict[str, list[CurrentRungTrial]] = defaultdict(list)
    for trial in taken:
        by_station[trial.city].append(trial)
    strata = (
        build_realized_stratum(f"station:{city}", by_station[city])
        for city in sorted(by_station)
    )
    return tuple(stratum for stratum in strata if stratum is not None)


def _ask_band_strata(taken: Sequence[CurrentRungTrial]) -> tuple[RealizedStratum, ...]:
    by_band: dict[tuple[float, float], list[CurrentRungTrial]] = defaultdict(list)
    for trial in taken:
        if trial.entry_ask is not None:
            by_band[classify_ask_band(trial.entry_ask)].append(trial)
    strata = (
        build_realized_stratum(f"ask_band:{band[0]}-{band[1]}", by_band.get(band, ()))
        for band in ASK_BANDS
    )
    return tuple(stratum for stratum in strata if stratum is not None)


@dataclass(frozen=True, slots=True)
class MbVerdict:
    """Kill-amendment verdict at one lag (`grok_mb_kill_amendment_2026-09-02.md`)."""

    lag_minutes: int
    outcome: Literal["MB_DEAD", "UNDERPOWERED", "ALIVE"]
    n_taken: int
    pooled: RealizedStratum | None
    station_strata: tuple[RealizedStratum, ...]
    ask_band_strata: tuple[RealizedStratum, ...]
    all_visited_cells_dead: bool
    detail: str

    @property
    def cell_dead_strata(self) -> tuple[RealizedStratum, ...]:
        return tuple(
            stratum
            for stratum in (*self.station_strata, *self.ask_band_strata)
            if stratum.cell_dead
        )


def evaluate_mb(
    taken: Sequence[CurrentRungTrial],
    *,
    lag_minutes: int,
    all_visited_cells_dead: bool = False,
) -> MbVerdict:
    """Kill-amendment verdict: REALIZED hold rate of TAKEN trials vs ask+fee.

    Never the archive base rate against ask -- that screen can neither fire
    nor confirm (the 09-02 audit: MDW 09-01 noon had p_hold_lower=0.594 vs
    ask=0.06, "edge"=+0.53 by the superseded formula, and the day settled
    ABOVE that rung anyway; base rates clear low asks on most days by
    construction, which is not evidence of an edge).
    """
    pooled = build_realized_stratum("pooled", taken)
    station_strata = _station_strata(taken)
    ask_band_strata = _ask_band_strata(taken)
    cell_dead = tuple(
        stratum for stratum in (*station_strata, *ask_band_strata) if stratum.cell_dead
    )
    n_taken = pooled.n if pooled is not None else 0
    pooled_kill = pooled is not None and pooled.cell_dead
    pooled_survive = (
        pooled is not None and pooled.survives and not cell_dead and not all_visited_cells_dead
    )

    if pooled_kill or bool(cell_dead) or all_visited_cells_dead:
        outcome: Literal["MB_DEAD", "UNDERPOWERED", "ALIVE"] = "MB_DEAD"
        if all_visited_cells_dead:
            why = "every tape-visited cell is n/a/m=1/open-lower"
        elif pooled_kill:
            assert pooled is not None  # implied by pooled_kill
            why = (
                f"pooled Wilson-upper {pooled.wilson_upper:.4f} < "
                f"break-even {pooled.break_even:.4f} at n={n_taken}"
            )
        else:
            why = (
                f"{len(cell_dead)} stratum(-a) cell-dead: "
                f"{', '.join(s.label for s in cell_dead)}"
            )
        detail = f"lag={lag_minutes}min: MB_DEAD -- {why}"
    elif pooled_survive:
        outcome = "ALIVE"
        assert pooled is not None
        detail = (
            f"lag={lag_minutes}min: n_taken={n_taken} >= {SURVIVE_N_MIN}, pooled "
            f"Wilson-lower {pooled.wilson_lower:.4f} > break-even {pooled.break_even:.4f}, "
            f"no stratum cell-dead"
        )
    else:
        outcome = "UNDERPOWERED"
        detail = (
            f"lag={lag_minutes}min: n_taken={n_taken}; kill needs n>={POOLED_KILL_N_MIN}, "
            f"survive needs n>={SURVIVE_N_MIN} -- not dead, not alive"
        )
    return MbVerdict(
        lag_minutes=lag_minutes,
        outcome=outcome,
        n_taken=n_taken,
        pooled=pooled,
        station_strata=station_strata,
        ask_band_strata=ask_band_strata,
        all_visited_cells_dead=all_visited_cells_dead,
        detail=detail,
    )


def evaluate_mb_family(
    verdicts_by_lag: Mapping[int, MbVerdict],
) -> Literal["MB_DEAD", "UNDERPOWERED", "ALIVE"]:
    """Family verdict: MB_DEAD/ALIVE require both K-B lags (10 and 15) to agree."""
    required = tuple(verdicts_by_lag[lag] for lag in K_B_REQUIRED_LAGS)
    if all(verdict.outcome == "MB_DEAD" for verdict in required):
        return "MB_DEAD"
    if all(verdict.outcome == "ALIVE" for verdict in required):
        return "ALIVE"
    return "UNDERPOWERED"


# ---------------------------------------------------------------------------
# I/O -- archive corpus and tape (real runs only; the unit tests never hit
# this section)
# ---------------------------------------------------------------------------


def load_archive_days_and_finals(
    *,
    cache_dir: Path,
    spec: SiteSpec,
    start: dt.date = ARCHIVE_START_DATE,
    end: dt.date = ARCHIVE_END_DATE,
) -> tuple[tuple[RunningMaxDay, ...], dict[dt.date, int]]:
    """`RunningMaxDay`s and CLI-final `tmax_f` by day, for one dense station."""
    raw = cache_path_for_url(cache_dir, asos_url(spec.iem_asos_id, start, end), ".txt")
    if not raw.exists():
        raise SystemExit(f"ASOS cache miss for {spec.city}; expected: {raw}")
    rows = parse_asos_rows(raw.read_text(encoding="utf-8", errors="replace"))
    temperatures, _drops = metar_temperatures(
        city=spec.city, rows=rows, std_utc_offset_hours=spec.std_utc_offset_hours
    )
    in_window = tuple(row for row in temperatures if start <= row.climate_day <= end)
    days = build_running_max_days(
        city=spec.city, temperatures=in_window, std_utc_offset_hours=spec.std_utc_offset_hours
    )
    finals, _every, _drops2 = load_cli_records(
        cache_dir=cache_dir, spec=spec, start=start, end=end
    )
    finals_by_day = {
        day: record.tmax_f
        for day, record in finals.items()
        if record.tmax_f is not None
    }
    return days, finals_by_day


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _fmt_cell(cell: ArchiveCell | None) -> str:
    if cell is None:
        return "n | - | - | n/a"
    lower = cell.p_hold_lower
    lower_text = "n/a" if lower is None else f"{lower:.4f}"
    return f"{cell.n} | {cell.hold_count} | {cell.hold_rate:.4f} | {lower_text}"


def _fmt_price(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}"


def _fmt_edge(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.4f}"


def _fmt_stratum_row(stratum: RealizedStratum) -> str:
    dead = "CELL-DEAD" if stratum.cell_dead else ""
    return (
        f"| {stratum.label} | {stratum.n} | {stratum.k} | {stratum.realized_hold_rate:.4f} | "
        f"{stratum.mean_ask:.4f} | {stratum.break_even:.4f} | {stratum.wilson_lower:.4f} | "
        f"{stratum.wilson_upper:.4f} | {dead} |"
    )


def build_report(
    *,
    archive: Mapping[ArchiveCellKey, ArchiveCell],
    summaries_by_lag: Mapping[int, Sequence[MbStationDaySummary]],
    verdicts: Mapping[int, MbVerdict],
    family_outcome: Literal["MB_DEAD", "UNDERPOWERED", "ALIVE"],
    preflight: str,
    generated_at: dt.datetime,
) -> str:
    lines: list[str] = []
    add = lines.append

    add("# M_B -- current-rung p_hold x ask edge measurement and its kill")
    add("")
    add(f"Generated {generated_at.isoformat()} from")
    add("`scripts/analysis/mb_current_rung_edge_study.py`. Spec:")
    add("`docs/evidence/grok_mb_design_2026-09-02.md` SS1 / SS2.")
    add("")
    add(
        "A descriptive join, not a backtest: no order, fill, position, fee or P&L "
        "appears anywhere in this pipeline. NautilusTrader is the exclusive owner of "
        "backtesting and execution."
    )
    add("")
    add("## Tape integrity (LESSON L-8) -- verified before interpretation")
    add("")
    add(f"> {preflight}")
    add("")
    add("## Part A -- archive p_hold table (JJA / SON, h=13 and h=15)")
    add("")
    add("| station | season | h | width | m | n | holds | rate | Wilson-lower |")
    add("|---|---|---:|---|---|---:|---:|---:|---:|")
    for city in DENSE_STATIONS:
        for season in ("JJA", "SON"):
            for hour in (13, 15):
                for width, m in _ARCHIVE_PROXY_CELLS:
                    cell = archive.get((city, season, hour, width, m))
                    m_text = "-" if m is None else str(m)
                    add(f"| {city} | {season} | {hour} | {width} | {m_text} | {_fmt_cell(cell)} |")
    add("")
    add("### Pre-filter: interior m=1 is dead at every station/hour (all seasons)")
    add("")
    add("| station | season | h | n | holds | rate | Wilson-lower |")
    add("|---|---|---:|---:|---:|---:|---:|")
    for (city, season, hour, width, m), cell in sorted(archive.items(), key=lambda kv: kv[0]):
        if width == WIDTH_INTERIOR and m == 1:
            lower_text = (
                "n/a" if cell.p_hold_lower is None else f"{cell.p_hold_lower:.4f}"
            )
            add(
                f"| {city} | {season} | {hour} | {cell.n} | {cell.hold_count} | "
                f"{cell.hold_rate:.4f} | {lower_text} |"
            )
    add("")
    add("## Part B -- tape join, per-station-day, per lag")
    add("")
    for lag in sorted(summaries_by_lag):
        add(f"### lag = {lag} min")
        add("")
        add(
            "| station | day | status | coverage (min) | h | m | width | held | "
            "ask | size | p_hold_lower | edge | taken |"
        )
        add("|---|---|---|---:|---:|---|---|---|---:|---:|---:|---:|---|")
        ordered = sorted(summaries_by_lag[lag], key=lambda item: (item.city, item.climate_day))
        for summary in ordered:
            trial = summary.first_executable
            if trial is None:
                add(
                    f"| {summary.city} | {summary.climate_day.isoformat()} | "
                    f"{summary.status} | {summary.afternoon_coverage_minutes:.1f} | "
                    f"- | - | - | - | - | - | - | - | - |"
                )
                continue
            m_text = "-" if trial.m is None else str(trial.m)
            taken_text = "TAKEN" if is_taken_trial(trial) else ""
            add(
                f"| {summary.city} | {summary.climate_day.isoformat()} | {summary.status} | "
                f"{summary.afternoon_coverage_minutes:.1f} | {trial.hour_lst} | {m_text} | "
                f"{trial.width} | {trial.held} | {_fmt_price(trial.entry_ask)} | "
                f"{_fmt_price(trial.entry_size)} | "
                f"{'n/a' if trial.p_hold_lower is None else f'{trial.p_hold_lower:.4f}'} | "
                f"{_fmt_edge(trial.edge)} | {taken_text} |"
            )
        add("")
        verdict = verdicts[lag]
        add(
            "#### Realized-hold evidence (kill amendment: "
            "`docs/evidence/grok_mb_kill_amendment_2026-09-02.md`)"
        )
        add("")
        add(
            "| stratum | n | k | realized rate | mean ask | break-even | "
            "Wilson-lower | Wilson-upper | |"
        )
        add("|---|---:|---:|---:|---:|---:|---:|---:|---|")
        if verdict.pooled is not None:
            add(_fmt_stratum_row(verdict.pooled))
        for stratum in (*verdict.station_strata, *verdict.ask_band_strata):
            add(_fmt_stratum_row(stratum))
        add("")
        add(f"**{verdict.outcome}** (lag={lag}min) -- {verdict.detail}")
        add("")
    add("## Family verdict (both K-B lags, 10 and 15, must agree)")
    add("")
    add(f"**{family_outcome}**")
    add("")
    add("## Independence and the clock")
    add("")
    add(
        "One trial per station-day; snapshot-weighted pools are forbidden. "
        "Same-calendar-day stations are weakly dependent (shared synoptic "
        "weather) -- the Wilson interval is anti-conservative when treating "
        "several same-day station-days as independent draws "
        "(`docs/evidence/grok_mb_kill_amendment_2026-09-02.md`)."
    )
    add("")
    add(
        "Clock (memo): ~3 taken trials/day at the archive's dense-station rate "
        "-> n=60 around 2026-09-22, n=150 around 2026-10-21, both still SON. "
        "If taken stays at the 09-01 rate (~1/day), n=60/150 are 60/150 "
        "calendar days out. Archive table is frozen; only the tape-side "
        "Wilson waits."
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-cache-dir", default=str(DEFAULT_ARCHIVE_CACHE_DIR))
    parser.add_argument("--quote-catalog", default=str(DEFAULT_QUOTE_TAPE_CATALOG))
    parser.add_argument("--settlement-catalog", default=str(DEFAULT_SETTLEMENT_CATALOG))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument(
        "--preflight-attestation",
        default=None,
        help="Precomputed L-8 attestation string; computed in-process if omitted.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    archive_cache_dir = Path(args.archive_cache_dir).expanduser()
    quote_catalog = Path(args.quote_catalog).expanduser()
    settlement_catalog = Path(args.settlement_catalog).expanduser()

    specs_by_city = {spec.city: spec for spec in load_sites() if spec.city in DENSE_STATIONS}

    print("[mb] Part A: building the archive p_hold table ...", file=sys.stderr, flush=True)
    days_by_city: dict[str, tuple[RunningMaxDay, ...]] = {}
    finals_by_city: dict[str, dict[dt.date, int]] = {}
    for city in DENSE_STATIONS:
        spec = specs_by_city[city]
        days, finals = load_archive_days_and_finals(cache_dir=archive_cache_dir, spec=spec)
        days_by_city[city] = days
        finals_by_city[city] = finals
        print(
            f"[mb] {city}: {len(days)} days, {len(finals)} CLI finals",
            file=sys.stderr,
            flush=True,
        )
    archive = build_archive_table(days_by_city, finals_by_city)

    print("[mb] Part B: tape join over the afternoon window ...", file=sys.stderr, flush=True)
    depth_root = quote_catalog / "data" / "order_book_depths"
    if not depth_root.is_dir():
        raise SystemExit(f"no depth catalog at {depth_root}")
    station_days = discover_station_days(
        depth_root=depth_root,
        cities=DENSE_STATIONS,
        fetch_start=ASOS_FETCH_START,
        fetch_end=ASOS_FETCH_END,
    )
    if not station_days:
        raise SystemExit(
            f"no dense-station instruments captured for "
            f"{ASOS_FETCH_START}..{ASOS_FETCH_END} under {depth_root}"
        )
    if args.preflight_attestation:
        preflight = require_preflight_attestation(args.preflight_attestation)
    else:
        preflight = collect_preflight_summary(catalog_root=quote_catalog, station_days=station_days)

    summaries_by_lag: dict[int, list[MbStationDaySummary]] = {lag: [] for lag in LAG_MINUTES_SWEEP}
    for city, climate_day in station_days:
        spec = specs_by_city[city]
        instrument_ids = instrument_ids_for(
            depth_root=depth_root, city=city, climate_day=climate_day
        )
        ladder = parse_ladder(instrument_ids)
        depth = load_depth(catalog_root=quote_catalog, instrument_ids=instrument_ids)
        series, _on_day, _drops = load_asos_series_for_day(
            cache_dir=archive_cache_dir,
            spec=spec,
            fetch_start=ASOS_FETCH_START,
            fetch_end=ASOS_FETCH_END,
            climate_day=climate_day,
        )
        settled_tmax_f, _final_count, _provenance = load_settled_tmax_for_day(
            catalog_base=settlement_catalog, city=city, climate_day=climate_day
        )
        for lag in LAG_MINUTES_SWEEP:
            summaries_by_lag[lag].append(
                build_mb_station_day_summary(
                    city=city,
                    climate_day=climate_day,
                    ladder=ladder,
                    depth=depth,
                    series=series,
                    settled_f=settled_tmax_f,
                    std_utc_offset_hours=spec.std_utc_offset_hours,
                    archive=archive,
                    lag_minutes=lag,
                )
            )

    verdicts = {
        lag: evaluate_mb(
            gather_taken_trials(summaries_by_lag[lag]),
            lag_minutes=lag,
            all_visited_cells_dead=all_visited_cells_dead_by_construction(summaries_by_lag[lag]),
        )
        for lag in LAG_MINUTES_SWEEP
    }
    family_outcome = evaluate_mb_family(verdicts)

    report = build_report(
        archive=archive,
        summaries_by_lag=summaries_by_lag,
        verdicts=verdicts,
        family_outcome=family_outcome,
        preflight=preflight,
        generated_at=dt.datetime.now(tz=dt.UTC).replace(microsecond=0),
    )
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"[mb] wrote {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
