"""HUNT-2 -- which LST hours, if any, carry ASK-RELATIVE edge.

WHY THIS EXISTS
---------------
`docs/evidence/ALL_HOURS_EDGE_TABLE_2026-09-20.md` powered all 24 LST hours of
the `p_hold` archive table. It also recorded, in its own SS3, the reason that
table may NOT be used to widen the decision window: `p_hold` is the LEFT side
of `p_bound > price + fee` and nothing else. Median `p_hold_lower` climbs
0.626 at hour 12 to 0.766 at hour 23 for a trivial reason -- by evening the
daily maximum is effectively settled, so the rung holding `R(t)` almost always
holds -- and the market prices those rungs toward 1 in step. A rising bound
against a rising price is not edge.

This module measures the WHOLE inequality per hour, against the
CONTEMPORANEOUS ask, net of the venue's fee at its current coefficient, and
reports the realised settlement outcome beside the claimed edge so the two can
be compared rather than conflated.

WHAT IT MEASURES
----------------
Per `(station, climate_day, hour_lst)`:

* `R(t0)` at the hour boundary `t0` from the ASOS running-max series, and the
  ladder rung that CONTAINS it -- never the eventual winner (survivorship).
* `p_bound` = the Wilson lower bound from the all-hours archive table, loaded
  BY PATH and sha-verified. Never promoted, never imported from the shipped
  `breezy.strategy.current_rung_hold.archive_table`.
* `ask` = the L0 ask of the FIRST liftable quote on that rung at or after
  `t0` and strictly before the next hour boundary.
* `fee` = `theta * p * (1 - p)` banker's-rounded to the cent at the venue's
  current `theta = 0.0695`, computed by `forecast_tape_screen.venue_fee`,
  which delegates to the LIVE `fee_on_ask`. The arithmetic is never restated.
* `claimed_edge = p_bound - (ask + fee)`; `realised_pnl = 1{held} - ask - fee`.

DISCIPLINE (the whole value of the work package)
------------------------------------------------
* STRICT AS-OF. The ASOS observation backing `R(t0)` must not postdate `t0`,
  and `t0` must not postdate the quote. Both are ASSERTED and raise
  `AsOfViolation`. `RULING_wp7_c2_realised_pnl_is_an_artefact_2026-09-20.md`
  records a false `+0.55` produced by exactly this class of bug, where an
  hour-of-day filter ran over a D-1..D+1 tape. Every window here is scoped by
  DATE AND HOUR, never hour alone.
* NO INSTANT-LEVEL ARGMAX. ONE pre-declared instant per
  `(station, day, hour)`: the FIRST liftable quote at or after the boundary.
  An argmax over ~10^3 instants fires on noise with probability tending to 1.
* 24 HOURS IS 24 HYPOTHESES. Realised-PnL significance is Holm-Bonferroni
  adjusted across the hours actually tested. Any hour that clears is
  IN-SAMPLE and needs post-freeze confirmation before it may be registered.
* REFUSE, NEVER IMPUTE. A ladder that is not a complete partition, an
  undefined `R(t0)`, an undefined archive cell, an absent settlement or no
  liftable quote all REFUSE the cell and are counted by reason.

This module constructs no order, no fill and no position. It does not touch
the shipped archive table, the decision-window constants, the fee pin or the
live family.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gc
import hashlib
import importlib.util
import itertools
import resource
import statistics
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli_basis_setup_win_rate_study import DENSE_STATIONS
from forecast_conditional_scoring import (
    CLUSTER_STATION_DAY,
    _clusters,
    bootstrap_cluster_draws,
    percentile_interval,
)
from forecast_tape_screen import venue_fee
from h4_preliminary_economic_read import (
    DepthObservation,
    Rung,
    RunningMaxSeries,
    load_depth,
    parse_ladder,
    rung_containing,
    running_max_at,
)
from ma_prelock_winner_ask_study import (
    ASK_QUALIFYING_HIGH,
    ASK_QUALIFYING_LOW,
    DEFAULT_QUOTE_TAPE_CATALOG,
    DEFAULT_SETTLEMENT_CATALOG,
    MIN_EXECUTABLE_SIZE,
    discover_station_days,
    instrument_ids_for,
    load_asos_series_for_day,
    load_settled_tmax_for_day,
)
from mb_current_rung_edge_study import (
    WIDTH_INTERIOR,
    WIDTH_OPEN_LOWER,
    WIDTH_OPEN_UPPER,
    classify_width,
)
from pmr_climatology_study import season_for
from settlement_alignment_cache import DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR
from settlement_alignment_study import load_sites

from breezy.normalize.climate_day import standard_time_zone

__all__ = [
    "ALL_HOURS",
    "ARCHIVE_TABLE_SHA256",
    "BOOTSTRAP_ITERATIONS",
    "MIN_CLUSTERS_TO_SCORE",
    "REFUSAL_REASONS",
    "TAKER_FEE_COEFFICIENT",
    "AsOfViolation",
    "HourRow",
    "HourScore",
    "LadderNotAPartitionError",
    "Refusal",
    "assert_as_of",
    "assert_complete_partition",
    "build_report",
    "claimed_edge",
    "evaluate_station_day_hour",
    "first_liftable_quote",
    "half_spread",
    "holm_adjusted",
    "hour_window_bounds",
    "load_p_bound_table",
    "partition_powered",
    "plan_hours_by_rung",
    "realised_pnl_per_contract",
    "running_max_reference_at",
    "score_hour",
    "take_fee",
    "width_and_m_codes",
]

# ---------------------------------------------------------------------------
# Pre-declared parameters. None of these is tuned after a first look.
# ---------------------------------------------------------------------------

#: The venue's CURRENT taker coefficient, measured on the wire 2026-09-17
#: (`docs/core/LESSONS.md`, the theta drift 0.06 -> 0.0695). Carried here as
#: this study's own declared constant; this module reads no pin and writes
#: none, and `venue_fee` is handed the value explicitly on every call.
TAKER_FEE_COEFFICIENT: Final[float] = 0.0695

#: Every LST hour of the local-standard day. The hypothesis set, fixed before
#: the first run -- 24 hours, therefore 24 hypotheses (Holm).
ALL_HOURS: Final[tuple[int, ...]] = tuple(range(24))

#: The all-hours `p_hold` table this study reads, and the sha256 it must have.
#: NOT promoted; loaded by path so that the shipped selector table is not even
#: importable from here.
DEFAULT_P_BOUND_TABLE: Final[Path] = (
    Path.home() / ".local/share/breezy/derived/archive_table_all_hours_2026_09_20.py"
)
ARCHIVE_TABLE_SHA256: Final[str] = (
    "ec231e0120fca513bed666b9a2d4af7405eb5f65f0f75f8a7177cd58526f49f7"
)

#: The tape's own span. Climate days outside it have no Depth10 capture.
TAPE_START_DATE: Final[dt.date] = dt.date(2026, 8, 30)
TAPE_END_DATE: Final[dt.date] = dt.date(2026, 9, 21)

#: The cached ASOS fetch window covering the tape. No network: a cache miss
#: REFUSES the station-day rather than fetching.
ASOS_CACHE_START: Final[dt.date] = dt.date(2026, 8, 30)
ASOS_CACHE_END: Final[dt.date] = dt.date(2026, 9, 20)

#: An hour is scored only with at least this many STATION-DAY clusters.
#: Not a new threshold: it is this programme's existing underpowered floor,
#: `mb_current_rung_edge_study`'s SS1 kill sentence ("over >= 15
#: afternoon-covered station-days ... Below 15: UNDERPOWERED, not dead").
#: Below it an hour is UNDERPOWERED and is excluded from the Holm family
#: entirely -- it is not scored, not reported as significant, and not counted
#: as a hypothesis. The first run of this study showed why: hours 17..23 each
#: carried 1-2 clusters, so every bootstrap resample returned the same mean,
#: the interval had zero width, the p-value pinned at the 1/B floor and all
#: seven hours read as "Holm-significant" off n=1. That is a property of the
#: resampler, not of the market.
MIN_CLUSTERS_TO_SCORE: Final[int] = 15

BOOTSTRAP_ITERATIONS: Final[int] = 2000
BOOTSTRAP_SEED: Final[int] = 20260920
BOOTSTRAP_ALPHA: Final[float] = 0.05

#: Width codes, as the archive table keys them.
_WIDTH_CODES: Final[Mapping[str, int]] = {
    WIDTH_INTERIOR: 0,
    WIDTH_OPEN_UPPER: 1,
    WIDTH_OPEN_LOWER: 2,
}

REASON_LADDER_NOT_PARTITION: Final[str] = "ladder_not_a_partition"
REASON_NO_LADDER: Final[str] = "no_captured_ladder"
REASON_ASOS_CACHE_MISS: Final[str] = "asos_cache_miss"
REASON_SETTLEMENT_UNAVAILABLE: Final[str] = "settlement_unavailable"
REASON_RUNNING_MAX_UNDEFINED: Final[str] = "running_max_undefined_at_hour"
REASON_RUNG_NOT_ON_LADDER: Final[str] = "running_max_outside_the_ladder"
REASON_P_BOUND_UNDEFINED: Final[str] = "p_bound_undefined_below_n_min"
#: DISTINCT from the above. The all-hours table tabulates interior (m=0,1)
#: and open-upper only -- the open LOWER tail is dead by construction and was
#: never measured, so a cell there is "outside the estimand", not
#: "under-powered". Pooling the two would misreport a structural absence as
#: a sample-size problem that more capture could fix.
REASON_OPEN_LOWER_NOT_TABULATED: Final[str] = "open_lower_tail_not_tabulated"
REASON_NO_LIFTABLE_QUOTE: Final[str] = "no_liftable_quote_in_the_hour"

REFUSAL_REASONS: Final[tuple[str, ...]] = (
    REASON_NO_LADDER,
    REASON_LADDER_NOT_PARTITION,
    REASON_ASOS_CACHE_MISS,
    REASON_SETTLEMENT_UNAVAILABLE,
    REASON_RUNNING_MAX_UNDEFINED,
    REASON_RUNG_NOT_ON_LADDER,
    REASON_OPEN_LOWER_NOT_TABULATED,
    REASON_P_BOUND_UNDEFINED,
    REASON_NO_LIFTABLE_QUOTE,
)


class AsOfViolation(RuntimeError):
    """A reference observation postdates the decision it is supposed to inform."""


class LadderNotAPartitionError(ValueError):
    """The captured rungs do not partition the integers; the cell is refused."""


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def assert_as_of(*, reference_ts_ns: int, decision_ts_ns: int, context: str) -> None:
    """Refuse a reference that is not strictly as-of the decision instant.

    `reference_ts_ns <= decision_ts_ns` or raise. The predecessor artefact this
    guard exists for (`RULING_wp7_c2_realised_pnl_is_an_artefact_2026-09-20.md`)
    reported a `+0.55` per-take result that was entirely an hour-of-day filter
    reaching across dates. A silent clamp, a warning or a dropped row would all
    have let that number ship; only a raise stops it.
    """
    if reference_ts_ns > decision_ts_ns:
        raise AsOfViolation(
            f"{context}: as-of violation -- the reference instant {reference_ts_ns} "
            f"postdates the decision instant {decision_ts_ns} by "
            f"{(reference_ts_ns - decision_ts_ns) / 1e9:.3f}s. The measurement would "
            "be using information the decision could not have had."
        )


def assert_complete_partition(ladder: Sequence[Rung]) -> None:
    """Refuse a ladder that is not a complete partition of the integers.

    A complete venue ladder is exactly one open LOWER tail, a contiguous run of
    closed 2F interiors, and exactly one open UPPER tail. A gap means some
    settled temperature belongs to no captured rung, so "the rung containing
    `R(t)`" is not well defined and neither is `p_hold`'s estimand. An
    incomplete capture is a REFUSAL, never a cell measured on whatever
    happened to be captured.
    """
    if not ladder:
        raise LadderNotAPartitionError("an empty ladder is not a partition")
    lowers = [rung for rung in ladder if rung.lower_f is None]
    uppers = [rung for rung in ladder if rung.upper_f is None]
    if len(lowers) != 1:
        raise LadderNotAPartitionError(
            f"ladder carries {len(lowers)} open lower tail(s); exactly one is required"
        )
    if len(uppers) != 1:
        raise LadderNotAPartitionError(
            f"ladder carries {len(uppers)} open upper tail(s); exactly one is required"
        )
    ordered = sorted(
        ladder,
        key=lambda rung: (
            rung.lower_f if rung.lower_f is not None else -10_000,
            rung.upper_f if rung.upper_f is not None else 10_000,
        ),
    )
    for left, right in itertools.pairwise(ordered):
        assert left.upper_f is not None
        assert right.lower_f is not None
        if left.upper_f + 1 != right.lower_f:
            raise LadderNotAPartitionError(
                f"gap or overlap between {left.instrument_id!r} (upper {left.upper_f}) "
                f"and {right.instrument_id!r} (lower {right.lower_f}); the ladder is "
                "not a partition of the integers"
            )


def hour_window_bounds(
    *, climate_day: dt.date, hour_lst: int, std_utc_offset_hours: float
) -> tuple[dt.datetime, dt.datetime]:
    """The UTC half-open span of LST hour `hour_lst` ON `climate_day`.

    Scoped by DATE AND HOUR. A window keyed on the hour alone is the WP-7 C2
    defect: over a tape spanning D-1..D+1 it silently pools three different
    days' instants into one "hour".
    """
    if hour_lst not in ALL_HOURS:
        raise ValueError(f"hour_lst must be in 0..23, was {hour_lst!r}")
    tz = standard_time_zone(std_utc_offset_hours)
    start_lst = dt.datetime.combine(climate_day, dt.time(hour=hour_lst), tzinfo=tz)
    start = start_lst.astimezone(dt.UTC)
    return start, start + dt.timedelta(hours=1)


def _liftable(row: DepthObservation) -> bool:
    """The realistic-entry screen: a real ask inside the qualifying band with
    at least `MIN_EXECUTABLE_SIZE` resting at L0. Identical in substance to
    `CurrentRungTrial.executable`."""
    if row.best_ask is None or not row.ask_ladder:
        return False
    if not ASK_QUALIFYING_LOW < row.best_ask < ASK_QUALIFYING_HIGH:
        return False
    return row.ask_ladder[0][1] >= MIN_EXECUTABLE_SIZE


def first_liftable_quote(
    rows: Sequence[DepthObservation], *, start: dt.datetime, end: dt.datetime
) -> DepthObservation | None:
    """The ONE pre-declared instant: the FIRST liftable quote in `[start, end)`.

    Deliberately NOT the cheapest, the widest-edge or the best of the hour. An
    argmax over the ~10^3 instants an hour of Depth10 capture holds selects on
    noise with probability tending to 1, and would turn a null corpus into a
    table of apparent opportunities.
    """
    for row in sorted(rows, key=lambda row: row.ts_event):
        if row.ts_event < start:
            continue
        if row.ts_event >= end:
            return None
        if _liftable(row):
            return row
    return None


def running_max_reference_at(
    series: RunningMaxSeries, instant: dt.datetime
) -> tuple[dt.datetime, int] | None:
    """`R(t)` AND the observation instant it came from, so as-of is checkable.

    `running_max_at` returns only the value, which cannot be audited for
    leakage. The value returned here is asserted to equal that function's, so
    this is a provenance wrapper, not a second implementation.
    """
    reference: tuple[dt.datetime, int] | None = None
    for observed_at, value in series:
        if observed_at > instant:
            break
        reference = (observed_at, value)
    expected = running_max_at(series, instant)
    if reference is None:
        assert expected is None
        return None
    assert reference[1] == expected
    return reference


# ---------------------------------------------------------------------------
# The inequality, per its three terms
# ---------------------------------------------------------------------------


def take_fee(ask: float) -> float:
    """The venue fee on `ask` at the CURRENT coefficient, banker's-rounded."""
    return venue_fee(ask_probability=ask, fee_coefficient=TAKER_FEE_COEFFICIENT)


def claimed_edge(*, p_bound: float, ask: float) -> float:
    """`p_bound - (ask + fee)` -- the whole take inequality, not its left side."""
    return p_bound - (ask + take_fee(ask))


def realised_pnl_per_contract(*, ask: float, held: bool) -> float:
    """Settled PnL of one $1-face YES contract bought at `ask` and held."""
    return (1.0 if held else 0.0) - ask - take_fee(ask)


def half_spread(row: DepthObservation) -> float | None:
    """`(ask - bid) / 2` from the SAME L0 snapshot. `None` with no bid."""
    if row.best_ask is None or row.best_bid is None:
        return None
    return (row.best_ask - row.best_bid) / 2.0


def width_and_m_codes(width: str, m: int | None) -> tuple[int, int]:
    """`(width_code, m_code)` as the archive table keys its cells."""
    code = _WIDTH_CODES[width]
    if width != WIDTH_INTERIOR:
        return code, 0
    if m not in (0, 1):
        raise ValueError(f"interior margin must be 0 or 1, was {m!r}")
    return code, m


# ---------------------------------------------------------------------------
# Rows, refusals and per-hour scores
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Refusal:
    """One `(station, day, hour)` that could not be measured, and why."""

    station: str
    climate_day: dt.date
    hour_lst: int
    reason: str


@dataclass(frozen=True, slots=True)
class HourRow:
    """One measured `(station, day, hour)` -- the ONE pre-declared instant."""

    station: str
    climate_day: dt.date
    hour_lst: int
    rung_instrument_id: str
    width: str
    m: int | None
    running_f: int
    reference_ts: dt.datetime
    decision_ts: dt.datetime
    p_bound: float
    ask: float
    fee: float
    half_spread: float | None
    claimed_edge: float
    held: bool
    realised_pnl: float

    def cluster_key(self, cluster: str) -> object:
        """Station-day clustering: the four stations' rungs on one day share a
        single weather outcome, so a row is NOT an independent draw."""
        if cluster != CLUSTER_STATION_DAY:
            raise ValueError(f"this study clusters on {CLUSTER_STATION_DAY!r}, not {cluster!r}")
        return (self.station, self.climate_day)


@dataclass(frozen=True, slots=True)
class HourScore:
    """The per-hour verdict, claimed and realised side by side."""

    hour_lst: int
    n: int
    n_clusters: int
    max_cluster_size: int
    mean_claimed_edge: float
    median_claimed_edge: float
    positive_claimed_fraction: float
    mean_half_spread: float | None
    mean_realised_pnl: float
    ci_low: float
    ci_high: float
    p_value: float

    def to_row(self) -> dict[str, object]:
        """A plain mapping for rendering. Never `dataclasses.asdict`."""
        return {
            "hour_lst": self.hour_lst,
            "n": self.n,
            "n_clusters": self.n_clusters,
            "max_cluster_size": self.max_cluster_size,
            "mean_claimed_edge": self.mean_claimed_edge,
            "median_claimed_edge": self.median_claimed_edge,
            "positive_claimed_fraction": self.positive_claimed_fraction,
            "mean_half_spread": self.mean_half_spread,
            "mean_realised_pnl": self.mean_realised_pnl,
            "ci95_low": self.ci_low,
            "ci95_high": self.ci_high,
            "p_value": self.p_value,
        }


def _mean_realised(rows: Sequence[HourRow]) -> float:
    if not rows:
        return 0.0
    return statistics.fmean(row.realised_pnl for row in rows)


def score_hour(
    rows: Sequence[HourRow],
    *,
    hour_lst: int,
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
) -> HourScore:
    """Score one hour. The interval is a STATION-DAY-clustered block bootstrap.

    Effective n is the CLUSTER count, never the row count: two rungs on the
    same station-day settle against one weather outcome.
    """
    if not rows:
        raise ValueError(f"hour {hour_lst} has no measured rows to score")
    blocks = _clusters(rows, CLUSTER_STATION_DAY)
    draws = bootstrap_cluster_draws(
        rows,
        statistic=_mean_realised,
        cluster=CLUSTER_STATION_DAY,
        iterations=iterations,
        seed=seed,
    )
    low, high = percentile_interval(draws, alpha=BOOTSTRAP_ALPHA)
    below = sum(1 for draw in draws if draw <= 0.0)
    above = sum(1 for draw in draws if draw >= 0.0)
    p_value = min(1.0, max(1.0 / len(draws), 2.0 * min(below, above) / len(draws)))
    spreads = [row.half_spread for row in rows if row.half_spread is not None]
    return HourScore(
        hour_lst=hour_lst,
        n=len(rows),
        n_clusters=len(blocks),
        max_cluster_size=max(len(block) for block in blocks),
        mean_claimed_edge=statistics.fmean(row.claimed_edge for row in rows),
        median_claimed_edge=statistics.median(row.claimed_edge for row in rows),
        positive_claimed_fraction=sum(1 for row in rows if row.claimed_edge > 0.0) / len(rows),
        mean_half_spread=statistics.fmean(spreads) if spreads else None,
        mean_realised_pnl=_mean_realised(rows),
        ci_low=low,
        ci_high=high,
        p_value=p_value,
    )


def partition_powered[RowT](
    by_hour: Mapping[int, Sequence[RowT]],
) -> tuple[dict[int, Sequence[RowT]], dict[int, Sequence[RowT]]]:
    """Split hours into `(powered, underpowered)` at `MIN_CLUSTERS_TO_SCORE`.

    Each hour carries at most ONE row per station-day by construction (one
    pre-declared instant), so within an hour the station-day cluster count
    EQUALS the row count and the block bootstrap coincides with a station-day
    bootstrap. That is the honest reading of the interval, and it is why the
    floor is expressed in clusters: they are the effective n.
    """
    powered: dict[int, Sequence[RowT]] = {}
    underpowered: dict[int, Sequence[RowT]] = {}
    for hour, rows in by_hour.items():
        target = powered if len(rows) >= MIN_CLUSTERS_TO_SCORE else underpowered
        target[hour] = rows
    return powered, underpowered


def holm_adjusted(p_values: Sequence[float]) -> tuple[float, ...]:
    """Holm-Bonferroni step-down adjusted p-values, IN INPUT ORDER.

    24 candidate hours is 24 hypotheses. Reporting an unadjusted per-hour
    p-value across a 24-hour sweep is how a null corpus produces an
    "opportunity": at alpha=0.05 the expected number of spurious winners is
    1.2 before any real effect exists.
    """
    if not p_values:
        return ()
    m = len(p_values)
    order = sorted(range(m), key=lambda index: p_values[index])
    adjusted = [0.0] * m
    running = 0.0
    for rank, index in enumerate(order):
        running = max(running, (m - rank) * p_values[index])
        adjusted[index] = min(1.0, running)
    return tuple(adjusted)


# ---------------------------------------------------------------------------
# The table load -- by path, sha-verified, never promoted
# ---------------------------------------------------------------------------


def load_p_bound_table(
    path: Path, *, expected_sha256: str = ARCHIVE_TABLE_SHA256
) -> Mapping[tuple[str, str, int, int, int], Decimal | None]:
    """Load `P_HOLD_LOWER` from the all-hours artefact AT `path`.

    Loaded as a standalone module object, never imported by package name: the
    shipped `breezy.strategy.current_rung_hold.archive_table` must not be
    reachable from this study, and this artefact must not become importable as
    if it were promoted.
    """
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise ValueError(
            f"{path}: sha256 {digest} does not match the declared "
            f"{expected_sha256}; refusing to measure against an unidentified table"
        )
    spec = importlib.util.spec_from_file_location("_hunt2_all_hours_table", path)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot load the archive table at {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.P_HOLD_LOWER


# ---------------------------------------------------------------------------
# One (station, day, hour) cell
# ---------------------------------------------------------------------------


def plan_hours_by_rung(
    *,
    climate_day: dt.date,
    std_utc_offset_hours: float,
    ladder: Sequence[Rung],
    series: RunningMaxSeries,
) -> dict[str | None, list[int]]:
    """Which rung each hour will ask about, decided WITHOUT reading the tape.

    `R(t0)` comes from the ASOS series alone, so the instrument an hour needs
    is known before a single Depth10 row is loaded. That is what lets the
    driver stream one instrument at a time. `None` collects the hours whose
    `R(t0)` is undefined or off-ladder; they refuse, and need no tape at all.
    """
    planned: dict[str | None, list[int]] = {}
    for hour_lst in ALL_HOURS:
        start, _end = hour_window_bounds(
            climate_day=climate_day,
            hour_lst=hour_lst,
            std_utc_offset_hours=std_utc_offset_hours,
        )
        reference = running_max_reference_at(series, start)
        rung = None if reference is None else rung_containing(ladder, reference[1])
        planned.setdefault(None if rung is None else rung.instrument_id, []).append(hour_lst)
    return planned


def evaluate_station_day_hour(
    *,
    station: str,
    climate_day: dt.date,
    hour_lst: int,
    std_utc_offset_hours: float,
    ladder: Sequence[Rung],
    depth: Mapping[str, Sequence[DepthObservation]],
    series: RunningMaxSeries,
    settled_f: int,
    p_bound_table: Mapping[tuple[str, str, int, int, int], Decimal | None],
) -> HourRow | Refusal:
    """Measure ONE cell, or refuse it with a reason. Never impute."""
    start, end = hour_window_bounds(
        climate_day=climate_day, hour_lst=hour_lst, std_utc_offset_hours=std_utc_offset_hours
    )
    reference = running_max_reference_at(series, start)
    if reference is None:
        return Refusal(station, climate_day, hour_lst, REASON_RUNNING_MAX_UNDEFINED)
    reference_ts, running_f = reference
    rung = rung_containing(ladder, running_f)
    if rung is None:
        return Refusal(station, climate_day, hour_lst, REASON_RUNG_NOT_ON_LADDER)
    width, m = classify_width(rung, running_f)
    width_code, m_code = width_and_m_codes(width, m)
    if width == WIDTH_OPEN_LOWER:
        return Refusal(station, climate_day, hour_lst, REASON_OPEN_LOWER_NOT_TABULATED)
    cell = p_bound_table.get((station, season_for(climate_day), hour_lst, width_code, m_code))
    if cell is None:
        return Refusal(station, climate_day, hour_lst, REASON_P_BOUND_UNDEFINED)
    quote = first_liftable_quote(depth.get(rung.instrument_id, ()), start=start, end=end)
    if quote is None:
        return Refusal(station, climate_day, hour_lst, REASON_NO_LIFTABLE_QUOTE)

    context = f"{station} {climate_day} h{hour_lst:02d}"
    decision_ts_ns = int(quote.ts_event.timestamp() * 1_000_000_000)
    assert_as_of(
        reference_ts_ns=int(reference_ts.timestamp() * 1_000_000_000),
        decision_ts_ns=decision_ts_ns,
        context=f"{context} (running-max reference vs quote)",
    )
    assert_as_of(
        reference_ts_ns=int(start.timestamp() * 1_000_000_000),
        decision_ts_ns=decision_ts_ns,
        context=f"{context} (hour boundary vs quote)",
    )

    assert quote.best_ask is not None
    ask = float(quote.best_ask)
    p_bound = float(cell)
    held = rung.contains(settled_f)
    return HourRow(
        station=station,
        climate_day=climate_day,
        hour_lst=hour_lst,
        rung_instrument_id=rung.instrument_id,
        width=width,
        m=m,
        running_f=running_f,
        reference_ts=reference_ts,
        decision_ts=quote.ts_event,
        p_bound=p_bound,
        ask=ask,
        fee=take_fee(ask),
        half_spread=half_spread(quote),
        claimed_edge=claimed_edge(p_bound=p_bound, ask=ask),
        held=held,
        realised_pnl=realised_pnl_per_contract(ask=ask, held=held),
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _fmt(value: float | None, places: int = 4) -> str:
    return "n/a" if value is None else f"{value:+.{places}f}"


def build_report(
    *,
    rows: Sequence[HourRow],
    refusals: Mapping[str, int],
    scores: Sequence[HourScore],
    adjusted: Sequence[float],
    underpowered: Mapping[int, int],
    station_days: int,
    generated_at: dt.datetime,
    table_path: Path,
    peak_rss_mb: float,
) -> str:
    lines: list[str] = []
    lines.append("# HUNT-2 -- hourly ASK-RELATIVE edge")
    lines.append("")
    lines.append(f"Generated (UTC): {generated_at.isoformat()}")
    lines.append(f"p_bound table: `{table_path}` sha256 `{ARCHIVE_TABLE_SHA256}` (NOT promoted)")
    lines.append(f"Fee coefficient theta = {TAKER_FEE_COEFFICIENT} (banker's-rounded to the cent)")
    lines.append(
        f"Corpus: {station_days} station-days, {len(rows)} measured cells "
        f"(ONE pre-declared instant per station-day-hour)."
    )
    lines.append(f"Peak RSS: {peak_rss_mb:.0f} MB")
    lines.append("")
    lines.append(
        f"Hours scored: {len(scores)} of 24 -- an hour needs at least "
        f"{MIN_CLUSTERS_TO_SCORE} station-day clusters (this programme's existing "
        f"underpowered floor). The Holm family is therefore {len(scores)} hypotheses, "
        "not 24; the remaining hours are UNDERPOWERED, not null."
    )
    lines.append("")
    lines.append(
        "Reading the interval honestly: one pre-declared instant per "
        "(station, day, hour) means each hour holds at most ONE row per "
        "station-day, so the station-day cluster count EQUALS n and the block "
        "bootstrap coincides with a station-day bootstrap. Effective n is the "
        "cluster column."
    )
    lines.append("")
    lines.append("## Per-hour scores")
    lines.append("")
    lines.append(
        "| hour LST | n | clusters | max blk | mean claimed | median claimed | frac>0 | "
        "mean 1/2-spread | mean realised PnL | clustered 95% CI | p | Holm p |"
    )
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|:--|---:|---:|")
    for score, holm in zip(scores, adjusted, strict=True):
        lines.append(
            f"| {score.hour_lst:02d} | {score.n} | {score.n_clusters} | "
            f"{score.max_cluster_size} | {_fmt(score.mean_claimed_edge)} | "
            f"{_fmt(score.median_claimed_edge)} | {score.positive_claimed_fraction:.3f} | "
            f"{_fmt(score.mean_half_spread)} | {_fmt(score.mean_realised_pnl)} | "
            f"[{_fmt(score.ci_low)}, {_fmt(score.ci_high)}] | {score.p_value:.4f} | "
            f"{holm:.4f} |"
        )
    lines.append("")
    lines.append("## Hours excluded as UNDERPOWERED (not scored, not hypotheses)")
    lines.append("")
    if underpowered:
        lines.append("| hour LST | clusters |")
        lines.append("|---:|---:|")
        for hour, count in sorted(underpowered.items()):
            lines.append(f"| {hour:02d} | {count} |")
    else:
        lines.append("None -- every hour with any measured cell cleared the floor.")
    lines.append("")
    lines.append("## Refusals by reason")
    lines.append("")
    lines.append("| reason | cells |")
    lines.append("|:--|---:|")
    for reason in REFUSAL_REASONS:
        lines.append(f"| {reason} | {refusals.get(reason, 0)} |")
    lines.append(f"| **total refused** | {sum(refusals.values())} |")
    lines.append("")
    cleared = [
        score.hour_lst
        for score, holm in zip(scores, adjusted, strict=True)
        if score.ci_low > 0.0 and holm <= BOOTSTRAP_ALPHA
    ]
    lines.append("## Verdict")
    lines.append("")
    if cleared:
        lines.append(
            f"Hours whose station-day-clustered 95% CI on realised PnL lies strictly "
            f"above zero AND whose Holm-adjusted p <= {BOOTSTRAP_ALPHA}: "
            f"{', '.join(f'{hour:02d}' for hour in cleared)}."
        )
    else:
        lines.append(
            "NO hour clears zero on realised PnL after Holm adjustment. On this corpus "
            "the decision window is not the binding constraint: widening it would not by "
            "itself produce profit."
        )
    lines.append("")
    lines.append(
        "Every hour above is measured IN-SAMPLE on the corpus that selected it. No hour "
        "may be registered into the decision window on this evidence alone; a selected "
        "hour requires post-freeze confirmation on data this study never saw."
    )
    lines.append("")
    return "\n".join(lines)


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HUNT-2 hourly ask-relative edge")
    parser.add_argument("--p-bound-table", default=str(DEFAULT_P_BOUND_TABLE))
    parser.add_argument("--quote-catalog", default=str(DEFAULT_QUOTE_TAPE_CATALOG))
    parser.add_argument("--settlement-catalog", default=str(DEFAULT_SETTLEMENT_CATALOG))
    parser.add_argument("--archive-cache-dir", default=str(DEFAULT_SETTLEMENT_ALIGNMENT_CACHE_DIR))
    parser.add_argument(
        "--output",
        default=str(
            Path.home()
            / ".local/share/breezy/derived/hunt2_hourly_ask_relative_edge"
            / "hourly_ask_relative_edge_2026-09-20.md"
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    table_path = Path(args.p_bound_table).expanduser()
    quote_catalog = Path(args.quote_catalog).expanduser()
    settlement_catalog = Path(args.settlement_catalog).expanduser()
    archive_cache_dir = Path(args.archive_cache_dir).expanduser()

    p_bound_table = load_p_bound_table(table_path)
    specs = {spec.city: spec for spec in load_sites() if spec.city in DENSE_STATIONS}

    depth_root = quote_catalog / "data" / "order_book_depths"
    if not depth_root.is_dir():
        raise SystemExit(f"no depth catalog at {depth_root}")
    station_days = discover_station_days(
        depth_root=depth_root,
        cities=DENSE_STATIONS,
        fetch_start=TAPE_START_DATE,
        fetch_end=TAPE_END_DATE,
    )

    rows: list[HourRow] = []
    refusals: dict[str, int] = dict.fromkeys(REFUSAL_REASONS, 0)
    scored_station_days = 0

    for station, climate_day in station_days:
        spec = specs[station]
        instrument_ids = instrument_ids_for(
            depth_root=depth_root, city=station, climate_day=climate_day
        )
        if not instrument_ids:
            refusals[REASON_NO_LADDER] += len(ALL_HOURS)
            continue
        try:
            ladder = parse_ladder(instrument_ids)
            assert_complete_partition(ladder)
        except (ValueError, LadderNotAPartitionError):
            refusals[REASON_LADDER_NOT_PARTITION] += len(ALL_HOURS)
            continue
        try:
            settled_f, _count, _path = load_settled_tmax_for_day(
                catalog_base=settlement_catalog, city=station, climate_day=climate_day
            )
        except Exception:  # noqa: BLE001 -- an absent catalog is a refusal, not a crash
            settled_f = None
        if settled_f is None:
            refusals[REASON_SETTLEMENT_UNAVAILABLE] += len(ALL_HOURS)
            continue
        try:
            series, _on_day, _drops = load_asos_series_for_day(
                cache_dir=archive_cache_dir,
                spec=spec,
                fetch_start=ASOS_CACHE_START,
                fetch_end=ASOS_CACHE_END,
                climate_day=climate_day,
            )
        except SystemExit:
            refusals[REASON_ASOS_CACHE_MISS] += len(ALL_HOURS)
            continue
        if not series:
            refusals[REASON_ASOS_CACHE_MISS] += len(ALL_HOURS)
            continue

        scored_station_days += 1
        # Streaming discipline: the rung an hour will ask about is decided from
        # the ASOS series ALONE, before any Depth10 is read, so the tape is then
        # loaded ONE INSTRUMENT at a time and dropped. Loading a whole
        # station-day's ladder at once peaked at 3.1 GB on this box, which is
        # not a safe neighbour for a live trade node.
        hours_by_rung = plan_hours_by_rung(
            climate_day=climate_day,
            std_utc_offset_hours=spec.std_utc_offset_hours,
            ladder=ladder,
            series=series,
        )
        for rung_id, hours in sorted(hours_by_rung.items(), key=lambda item: repr(item[0])):
            depth: dict[str, Sequence[DepthObservation]] = {}
            if rung_id is not None:
                depth = dict(
                    load_depth(catalog_root=quote_catalog, instrument_ids=[rung_id])
                )
            for hour_lst in hours:
                outcome = evaluate_station_day_hour(
                    station=station,
                    climate_day=climate_day,
                    hour_lst=hour_lst,
                    std_utc_offset_hours=spec.std_utc_offset_hours,
                    ladder=ladder,
                    depth=depth,
                    series=series,
                    settled_f=settled_f,
                    p_bound_table=p_bound_table,
                )
                if isinstance(outcome, Refusal):
                    refusals[outcome.reason] += 1
                else:
                    rows.append(outcome)
            depth.clear()
            del depth
            gc.collect()
        print(
            f"[hunt2] {station} {climate_day}: {len(rows)} rows so far",
            file=sys.stderr,
            flush=True,
        )

    by_hour: dict[int, list[HourRow]] = {}
    for row in rows:
        by_hour.setdefault(row.hour_lst, []).append(row)
    powered, underpowered = partition_powered(by_hour)
    scores = [score_hour(powered[hour], hour_lst=hour) for hour in sorted(powered)]
    adjusted = holm_adjusted(tuple(score.p_value for score in scores))
    underpowered_counts = {hour: len(rows) for hour, rows in sorted(underpowered.items())}

    peak_rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    report = build_report(
        rows=rows,
        refusals=refusals,
        scores=scores,
        adjusted=adjusted,
        underpowered=underpowered_counts,
        station_days=scored_station_days,
        generated_at=dt.datetime.now(tz=dt.UTC).replace(microsecond=0),
        table_path=table_path,
        peak_rss_mb=peak_rss_mb,
    )
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"[hunt2] wrote {output} (peak RSS {peak_rss_mb:.0f} MB)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
