"""LAT-1 revision-latency study: statistics, leak guards, tau and selection (plan r3 + r3.1).

Pure analysis core, no direct Nautilus import. The book arithmetic lives in
``breezy.strategy.weather_common.revision_gate``; every statistic that already exists in
``release_timing`` / ``nbp_calibration`` is delegated, never reimplemented.

KILL-COST is the RAW executable form (amendment 1): the DiD form is a diagnostic and never
kills. Every markout runs from ``t_dec`` (amendment 2). Missing-exit means "no bid in
``[t_exit, t_exit + W]``" everywhere (amendment 3).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Protocol

from breezy.analysis import nbp_calibration
from breezy.analysis.nbp_calibration import cluster_bootstrap_draws, percentile_interval
from breezy.analysis.release_timing import (
    EventObservation,
    SlopeCI,
    day_block_bootstrap_slope_ci,
    holm_reject,
    metar_offset_placebo_instants,
    time_to_fraction_of_move,
)
from breezy.domain.forecast_point import MINIMUM_PUBLICATION_LAG_NS
from breezy.strategy.forecast_quantile_ladder.calibration_artefact import LiveCalibration
from breezy.strategy.ladder_ev.forecast_state import (
    ForecastQuantileState,
    ForecastQuantileVector,
)
from breezy.strategy.ladder_ev.quantile_density import Rung
from breezy.strategy.no_ladder_maker.pno_store import (
    PartitionSource,
    PinnedRead,
    VectorChain,
    build_chain,
    ladder_p_yes,
    read_pinned,
)
from breezy.strategy.weather_common.revision_gate import (
    NS,
    BookRow,
    BookSeries,
    MissingClass,
    mid,
    revision,
)

__all__ = [
    "ARTEFACT_SHA256",
    "CONFIRM_START",
    "CUTOFF_C_NS",
    "KILL_BOOTSTRAP_DRAWS",
    "SEARCH_END",
    "STAGE1_FRAMING",
    "STAGE2_MIN_NET_USD",
    "TRADABLE_CYCLES",
    "TRADABLE_CYCLE_Z",
    "KillResult",
    "KillRow",
    "LeakGuardError",
    "MissingAttribution",
    "SelectionResult",
    "TauCycle",
    "TauReport",
    "VariantSummary",
]

#: Sha of the calibration artefact the study is pinned to (plan R1).
ARTEFACT_SHA256: Final[str] = "9c0b6d6e66a587c1b4e14e5f95ff5cedb3c7195f62f8ad4238191fdd75923a5e"
#: Corpus boundaries (plan guard 7). D = 2026-10-27 is excluded and counted.
SEARCH_END: Final[dt.date] = dt.date(2026, 10, 26)
CONFIRM_START: Final[dt.date] = dt.date(2026, 10, 28)
#: Provisional cutoff C; the prereg freeze sets the final value (next 00:00Z after the commit).
CUTOFF_C_NS: Final[int] = int(dt.datetime(2026, 10, 27, tzinfo=dt.UTC).timestamp()) * NS
#: The only executable NBP cycle (19Z of D-1); 01Z and 13Z are report-only strata.
TRADABLE_CYCLE_Z: Final[int] = 19
TRADABLE_CYCLES: Final[frozenset[int]] = frozenset({TRADABLE_CYCLE_Z})

KILL_BOOTSTRAP_DRAWS: Final[int] = 20000
KILL_SEED: Final[int] = 20260929
KILL_MIN_EVENTS: Final[int] = 30
KILL_MIN_CLUSTERS: Final[int] = 15
KILL_MIN_MEDIAN_PLACEBOS: Final[int] = 2
EXEC_MISSING_LIMIT: Final[float] = 0.25
CI_ALPHA: Final[float] = 0.05
HOLM_ALPHA: Final[float] = 0.025

TAU_PRIMARY_FLOOR: Final[float] = 0.13
TAU_ALT_FLOOR: Final[float] = 0.18
TAU_PRIMARY_QUANTILE: Final[float] = 0.60
TAU_ALT_QUANTILE: Final[float] = 0.80

STAGE2_MIN_NET_USD: Final[float] = 0.035
AUDIT_MEAN_USD: Final[float] = 0.04
AUDIT_HIT_RATE: Final[float] = 0.75
AUDIT_MEAN_OVER_SD: Final[float] = 1.0
QUALIFY_MIN_TAKES: Final[int] = 30
QUALIFY_MIN_CLUSTERS: Final[int] = 15
QUALIFY_MAX_MISSING_EXIT: Final[float] = 0.25
QUALIFY_PLACEBO_RATIO: Final[float] = 0.5
STAGE1_FRAMING: Final[str] = (
    "At about 59 takes and SE about 0.019, Stage 1 mainly ranks variants and excludes clearly "
    "negative ones; it is not evidence of edge."
)

PLACEBO_PRE_NS: Final[int] = 60 * 60 * NS
PLACEBO_POST_NS: Final[int] = 180 * 60 * NS
#: Nominal 07Z NBP release window in seconds of the UTC day, used when no ledger time exists.
NOMINAL_07Z_S: Final[tuple[int, int]] = (7 * 3600 + 55 * 60, 9 * 3600 + 40 * 60)
_DAY_NS: Final[int] = 86400 * NS
#: The provenance citation the prereg must carry (guard 5).
PROVENANCE_MARKERS: Final[tuple[str, ...]] = ("DEFAULT_SPLITS", "holdout_start")


class LeakGuardError(RuntimeError):
    """A fatal leak/data guard from the plan (numbered 1-11)."""

    def __init__(self, guard: int, message: str) -> None:
        super().__init__(f"leak guard {guard}: {message}")
        self.guard = guard


# ----------------------------------------------------------------------------- guards


def assert_guard_1(
    *,
    prev_available_at_ns: int,
    cur_available_at_ns: int,
    prev_climate_day: dt.date,
    cur_climate_day: dt.date,
    climate_day: dt.date,
) -> None:
    if prev_available_at_ns >= cur_available_at_ns:
        raise LeakGuardError(1, f"prev {prev_available_at_ns} not before cur {cur_available_at_ns}")
    if not prev_climate_day == cur_climate_day == climate_day:
        raise LeakGuardError(1, f"climate days {prev_climate_day}/{cur_climate_day}/{climate_day}")


def assert_guard_2(
    *, available_at_ns: int, lag_ns: int, t_dec_ns: int, chain_available_at_ns: int | None
) -> None:
    if not available_at_ns + lag_ns < t_dec_ns:
        raise LeakGuardError(2, "t_dec is not strictly after available_at + L")
    if chain_available_at_ns != available_at_ns:
        raise LeakGuardError(2, "chain.at(t_dec) is not the deciding release (superseded)")


def assert_guard_3(rows: Sequence[BookRow], t_ns: int) -> None:
    for row in rows:
        if row.ts_init > t_ns:
            raise LeakGuardError(3, f"row ts_init {row.ts_init} is after query time {t_ns}")


def assert_guard_4(*, available_at_ns: int, cycle_runtime_ns: int) -> None:
    floor = cycle_runtime_ns + MINIMUM_PUBLICATION_LAG_NS["NBM_NBP"]
    if available_at_ns < floor:
        raise LeakGuardError(4, f"available_at {available_at_ns} precedes the publication floor")


def assert_guard_5(
    search_days: Sequence[dt.date], *, artefact_sha256: str, prereg_text: str | None
) -> None:
    if artefact_sha256 != ARTEFACT_SHA256:
        raise LeakGuardError(5, "calibration artefact sha does not match the pin")
    if not search_days:
        raise LeakGuardError(5, "no search days")
    holdout_start = nbp_calibration.DEFAULT_SPLITS.holdout_start
    if holdout_start > min(search_days) - dt.timedelta(days=1):
        raise LeakGuardError(5, f"holdout_start {holdout_start} is too late for the search days")
    if prereg_text is None:  # stage tau runs before the prereg exists; the citation comes later
        return
    missing = [marker for marker in PROVENANCE_MARKERS if marker not in prereg_text]
    if missing:
        raise LeakGuardError(5, f"provenance citation absent from the prereg: {missing}")


def decision_record_sha256(records: Sequence[Mapping[str, object]]) -> str:
    payload = json.dumps(records, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def report_settlement[T](
    records: Sequence[Mapping[str, object]], open_truth: Callable[[], T]
) -> tuple[T, str]:
    """Guard 6: hash the decision records, open the truth, and require an unchanged hash."""
    before = decision_record_sha256(records)
    truth = open_truth()
    if decision_record_sha256(records) != before:
        raise LeakGuardError(6, "decision records changed while the truth was open")
    return truth, before


def assert_guard_7(*, climate_day: dt.date, t_dec_ns: int, pre_stage2: bool) -> None:
    if not pre_stage2:
        if climate_day < CONFIRM_START:
            raise LeakGuardError(7, f"stage 2 reads only D >= {CONFIRM_START}, got {climate_day}")
        return
    if climate_day >= CONFIRM_START:
        raise LeakGuardError(7, f"pre-stage-2 refuses D >= {CONFIRM_START}, got {climate_day}")
    if climate_day > SEARCH_END:
        raise LeakGuardError(7, f"D {climate_day} is outside the search corpus (excluded)")
    if t_dec_ns >= CUTOFF_C_NS:
        raise LeakGuardError(7, "search t_dec is at or after the cutoff C")


def _placebo_violation(
    instant_ns: int, releases_ns: Sequence[int], climate_day: dt.date, offset_hours: float
) -> str | None:
    lo, hi = instant_ns - PLACEBO_PRE_NS, instant_ns + PLACEBO_POST_NS
    if any(lo <= release <= hi for release in releases_ns):
        return "a release lies inside [p-60m, p+180m]"
    first_day = (lo // _DAY_NS) - 1
    for day_index in range(first_day, (hi // _DAY_NS) + 2):
        start = day_index * _DAY_NS + NOMINAL_07Z_S[0] * NS
        end = day_index * _DAY_NS + NOMINAL_07Z_S[1] * NS
        has_ledger = any(start <= release <= end for release in releases_ns)
        if not has_ledger and start <= hi and end >= lo:
            return "the nominal 07Z window overlaps [p-60m, p+180m]"
    local = dt.datetime.fromtimestamp(instant_ns // NS, tz=dt.UTC) + dt.timedelta(
        hours=offset_hours
    )
    if local.date() != climate_day:
        return f"local standard date {local.date()} is not D={climate_day}"
    return None


def placebo_instants(
    *,
    minute_of_hour: int,
    releases_ns: Sequence[int],
    days: Sequence[dt.date],
    climate_day: dt.date,
    offset_hours: float,
    instrument_id: str,
    event_instrument_id: str,
) -> tuple[int, ...]:
    """METAR-offset placebos post-filtered for guard 9 (same D, same instrument, no release)."""
    if instrument_id != event_instrument_id:
        return ()
    raw = metar_offset_placebo_instants(
        minute_of_hour=minute_of_hour, releases_ns=releases_ns, days=days, exclusion_s=0
    )
    return tuple(
        instant
        for instant in raw
        if _placebo_violation(instant, releases_ns, climate_day, offset_hours) is None
    )


def before_cutoff(instant_ns: int) -> bool:
    """True while a read instant is strictly before the cutoff C."""
    return instant_ns < CUTOFF_C_NS


def assert_guard_9(
    *,
    instant_ns: int,
    releases_ns: Sequence[int],
    climate_day: dt.date,
    offset_hours: float,
    instrument_id: str,
    event_instrument_id: str,
) -> None:
    if instrument_id != event_instrument_id:
        raise LeakGuardError(9, "placebo is on another instrument")
    reason = _placebo_violation(instant_ns, releases_ns, climate_day, offset_hours)
    if reason is not None:
        raise LeakGuardError(9, reason)


def assert_guard_10(population: int, takes: int, drops: Mapping[str, int]) -> None:
    if population != takes + sum(drops.values()):
        raise LeakGuardError(
            10, f"census identity broken: {population} != {takes} + {sum(drops.values())}"
        )


def assert_guard_11(
    t_dec_ns: int,
    t_exit_ns: int,
    t_exit_plus_w_ns: int,
    *,
    inside_permit: Callable[[int], bool],
) -> None:
    for label, instant in (
        ("t_dec", t_dec_ns),
        ("t_exit", t_exit_ns),
        ("t_exit+W", t_exit_plus_w_ns),
    ):
        if not inside_permit(instant):
            raise LeakGuardError(11, f"{label} is outside the nominal permit")


# --------------------------------------------------------------------- store helpers


def chain_for(state: ForecastQuantileState, climate_day: dt.date) -> VectorChain:
    return build_chain(state, climate_day)


def pinned_cycles(source: PartitionSource, icao: str, climate_day: dt.date) -> PinnedRead:
    return read_pinned(source, icao, climate_day)


def rung_deltas(
    *,
    prev: ForecastQuantileVector,
    cur: ForecastQuantileVector,
    ladder: Sequence[Rung],
    calibration: LiveCalibration,
    latitude_deg: float,
    climate_day: dt.date,
) -> dict[str, float]:
    """``dP_r`` per rung from ``ladder_p_yes`` on both releases (guard 1 first)."""
    assert_guard_1(
        prev_available_at_ns=prev.available_at_ns,
        cur_available_at_ns=cur.available_at_ns,
        prev_climate_day=prev.climate_day,
        cur_climate_day=cur.climate_day,
        climate_day=climate_day,
    )
    p_prev = ladder_p_yes(prev, ladder, calibration, latitude_deg)
    p_cur = ladder_p_yes(cur, ladder, calibration, latitude_deg)
    return revision(
        prev_p={rung: triple.point for rung, triple in p_prev.items()},
        cur_p={rung: triple.point for rung, triple in p_cur.items()},
        prev_climate_day=prev.climate_day,
        cur_climate_day=cur.climate_day,
        climate_day=climate_day,
        prev_available_at_ns=prev.available_at_ns,
        cur_available_at_ns=cur.available_at_ns,
    )


# ---------------------------------------------------------------------- statistics


def aligned_mark_change(
    rows: Sequence[BookRow] | BookSeries,
    *,
    t_dec_ns: int,
    x_ns: int,
    missing_at: Callable[[int], bool] | None = None,
) -> float | None:
    """``mid(t_dec + X) - mid(t_dec)`` as-of; None when either mid is missing (amendment 2),
    including an endpoint that is missing by gap or heartbeat (R3), never carried forward."""
    series = rows if isinstance(rows, BookSeries) else BookSeries(rows)
    if missing_at is not None and (missing_at(t_dec_ns) or missing_at(t_dec_ns + x_ns)):
        return None
    start, end = mid(series.as_of(t_dec_ns)), mid(series.as_of(t_dec_ns + x_ns))
    if start is None or end is None:
        return None
    return end - start


def fraction_of_move(
    series: Sequence[tuple[int, float]], t0_ns: int, level0: float
) -> float | None:
    """Half-life (seconds) via ``time_to_fraction_of_move(fraction=0.5, min_move=0.01)``."""
    return time_to_fraction_of_move(series, t0_ns, level0, fraction=0.5, min_move=0.01)


def mechanism_slope_ci(events: Sequence[EventObservation], *, n_boot: int, seed: int) -> SlopeCI:
    return day_block_bootstrap_slope_ci(events, n_boot=n_boot, alpha=CI_ALPHA, seed=seed)


def secondary_holm(pvalues: Sequence[float]) -> tuple[bool, ...]:
    return holm_reject(pvalues, alpha=HOLM_ALPHA)


@dataclass(frozen=True, slots=True)
class MissingAttribution:
    n_missing: int
    n_gap: int
    n_heartbeat: int
    share_gap: float
    share_heartbeat: float


def missing_attribution(flags: Sequence[MissingClass]) -> MissingAttribution:
    """Amendment 4: share of missing classifications from tape gaps vs heartbeat failure."""
    missing = [flag for flag in flags if flag.missing]
    n_gap = sum(1 for flag in missing if flag.reason == "quote_tape_gap")
    n_heartbeat = sum(1 for flag in missing if flag.reason == "heartbeat")
    total = len(missing)
    return MissingAttribution(
        n_missing=total,
        n_gap=n_gap,
        n_heartbeat=n_heartbeat,
        share_gap=n_gap / total if total else 0.0,
        share_heartbeat=n_heartbeat / total if total else 0.0,
    )


@dataclass(frozen=True, slots=True)
class KillRow:
    """One traded-subset event. ``y_raw`` runs ``t_dec -> t_dec + 60m``."""

    station: str
    climate_day: dt.date
    y_raw: float
    placebo_ys: tuple[float, ...]
    cost_e: float
    missing_exit: bool


@dataclass(frozen=True, slots=True)
class KillResult:
    verdict: str
    killed_on: str
    n: int
    n_climate: int
    n_station_days: int
    missing_exit_rate: float
    median_placebos: float
    k_raw: float | None
    k_raw_lo: float | None
    k_raw_hi: float | None
    k_did: float | None
    k_did_hi: float | None


class _Clustered(Protocol):
    @property
    def station(self) -> str: ...

    @property
    def climate_day(self) -> dt.date: ...


@dataclass(frozen=True, slots=True)
class ClusterInterval:
    mean: float
    lo: float
    hi: float
    p_one_sided: float


def wider_cluster_interval[C: _Clustered](
    items: Sequence[C], value: Callable[[C], float], *, iterations: int, seed: int
) -> ClusterInterval:
    """Mean of ``value`` with the WIDER of the station-day and climate-day clustered 95%
    intervals; ``p_one_sided`` is the larger share of draws at or below zero (H0: mean <= 0)."""

    def _mean(drawn: Sequence[C]) -> float:
        return math.fsum(value(item) for item in drawn) / len(drawn)

    lows: list[float] = []
    highs: list[float] = []
    ps: list[float] = []
    for key in (lambda item: (item.station, item.climate_day), lambda item: item.climate_day):
        draws = cluster_bootstrap_draws(
            items, statistic=_mean, cluster_key=key, seed=seed, iterations=iterations
        )
        lo, hi = percentile_interval(draws, alpha=CI_ALPHA)
        lows.append(lo)
        highs.append(hi)
        ps.append(sum(1 for d in draws if d <= 0.0) / len(draws))
    return ClusterInterval(_mean(items), min(lows), max(highs), max(ps))


def kill_cost(
    rows: Sequence[KillRow],
    *,
    iterations: int = KILL_BOOTSTRAP_DRAWS,
    seed: int = KILL_SEED,
    extra_missing: int = 0,
) -> KillResult:
    """KILL-COST on the traded subset (amendment 1). ``extra_missing`` counts traded events
    whose mid was unscorable: they count as missing-exit for INCONCLUSIVE-EXEC only."""
    n = len(rows)
    days = {row.climate_day for row in rows}
    station_days: dict[tuple[str, dt.date], int] = {}
    for row in rows:
        station_days.setdefault((row.station, row.climate_day), len(row.placebo_ys))
    median_placebos = statistics.median(station_days.values()) if station_days else 0.0
    total = n + extra_missing
    n_missing = sum(1 for row in rows if row.missing_exit) + extra_missing
    missing_rate = n_missing / total if total else 0.0
    k_raw = k_raw_lo = k_raw_hi = k_did = k_did_hi = None
    if rows:
        raw = wider_cluster_interval(
            rows, lambda row: row.y_raw - row.cost_e, iterations=iterations, seed=seed
        )
        k_raw, k_raw_lo, k_raw_hi = raw.mean, raw.lo, raw.hi
        with_placebos = [row for row in rows if row.placebo_ys]
        if with_placebos:
            did = wider_cluster_interval(
                with_placebos,
                lambda row: (
                    row.y_raw - math.fsum(row.placebo_ys) / len(row.placebo_ys) - row.cost_e
                ),
                iterations=iterations,
                seed=seed,
            )
            k_did, k_did_hi = did.mean, did.hi
    if (
        n < KILL_MIN_EVENTS
        or len(days) < KILL_MIN_CLUSTERS
        or (median_placebos < KILL_MIN_MEDIAN_PLACEBOS)
    ):
        verdict = "INCONCLUSIVE"
    elif missing_rate > EXEC_MISSING_LIMIT:
        verdict = "INCONCLUSIVE-EXEC"
    elif k_raw_hi is not None and k_raw_hi < 0:
        verdict = "KILL"
    else:
        verdict = "GO"
    return KillResult(
        verdict=verdict,
        killed_on="k_raw",
        n=n,
        n_climate=len(days),
        n_station_days=len(station_days),
        missing_exit_rate=missing_rate,
        median_placebos=float(median_placebos),
        k_raw=k_raw,
        k_raw_lo=k_raw_lo,
        k_raw_hi=k_raw_hi,
        k_did=k_did,
        k_did_hi=k_did_hi,
    )


# ------------------------------------------------------------------------------- tau


@dataclass(frozen=True, slots=True)
class TauCycle:
    available_at_ns: int
    cycle_hour: int
    delta_r_plus: float


@dataclass(frozen=True, slots=True)
class TauReport:
    n_input: int
    q60: float
    q80: float
    tau_primary: float
    tau_alt: float
    floor_primary_binds: bool
    floor_alt_binds: bool
    n_at_primary: int
    n_at_alt: int


def _quantile(sorted_values: Sequence[float], q: float) -> float:
    position = q * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def derive_tau(cycles: Sequence[TauCycle], *, freeze_ns: int) -> TauReport:
    """tau from NBP data alone: 19Z cycles with ``available_at < freeze`` and a positive dP_r+."""
    values = sorted(
        cycle.delta_r_plus
        for cycle in cycles
        if cycle.cycle_hour in TRADABLE_CYCLES
        and cycle.available_at_ns < freeze_ns
        and cycle.delta_r_plus > 0.0
    )
    if not values:
        raise ValueError("no positive 19Z revisions available before the freeze")
    q60 = _quantile(values, TAU_PRIMARY_QUANTILE)
    q80 = _quantile(values, TAU_ALT_QUANTILE)
    tau_primary = max(TAU_PRIMARY_FLOOR, q60)
    tau_alt = max(TAU_ALT_FLOOR, q80)
    return TauReport(
        n_input=len(values),
        q60=q60,
        q80=q80,
        tau_primary=tau_primary,
        tau_alt=tau_alt,
        floor_primary_binds=q60 < TAU_PRIMARY_FLOOR,
        floor_alt_binds=q80 < TAU_ALT_FLOOR,
        n_at_primary=sum(1 for value in values if value >= tau_primary),
        n_at_alt=sum(1 for value in values if value >= tau_alt),
    )


# ---------------------------------------------------------------------- selection


@dataclass(frozen=True, slots=True)
class VariantSummary:
    name: str
    primary: bool
    point: float
    lo: float
    hi: float
    n: int
    n_climate: int
    missing_exit_rate: float
    hit_rate: float
    mean_over_sd: float
    placebo_point: float
    n_placebo: int
    p_value: float
    #: Takes are ordered t_a < t_dec < t_exit. A sanity flag, NOT evidence of absence of leakage.
    timing_consistent: bool


@dataclass(frozen=True, slots=True)
class SelectionResult:
    status: str
    chosen: tuple[str, ...]
    stage2_go: bool
    audit_names: tuple[str, ...]
    flags: tuple[str, ...] = ()


def audit_pending(summary: VariantSummary) -> bool:
    """An implausibly good variant is held for an independent leak audit, never failed."""
    return (
        summary.point > AUDIT_MEAN_USD
        or summary.hit_rate > AUDIT_HIT_RATE
        or summary.mean_over_sd > AUDIT_MEAN_OVER_SD
    )


def qualifies(summary: VariantSummary) -> bool:
    return (
        summary.point > 0.0
        and summary.hi > 0.0
        and summary.n >= QUALIFY_MIN_TAKES
        and summary.n_climate >= QUALIFY_MIN_CLUSTERS
        and summary.missing_exit_rate <= QUALIFY_MAX_MISSING_EXIT
        and summary.timing_consistent
        and summary.n_placebo > 0
        and summary.placebo_point <= QUALIFY_PLACEBO_RATIO * summary.point
    )


def _rank(eligible: Sequence[VariantSummary]) -> tuple[VariantSummary, ...]:
    primary = [s for s in eligible if s.primary]
    secondaries = sorted((s for s in eligible if not s.primary), key=lambda s: (-s.lo, s.name))
    return tuple([*primary, *secondaries[:1]] if primary else secondaries[:2])


def select(summaries: Sequence[VariantSummary]) -> SelectionResult:
    """Frozen selection rule: V0 plus the best qualifying secondary, else the top two.

    A pending audit that could change the ranking (it would qualify but for the audit hold)
    withholds the selection: the result is AUDIT-PENDING with nothing chosen."""
    pending = tuple(s.name for s in summaries if audit_pending(s))
    flags = tuple(f"{s.name}:NO_PLACEBO_EVIDENCE" for s in summaries if s.n_placebo == 0)
    eligible = [s for s in summaries if s.name not in pending and qualifies(s)]
    ranked = _rank(eligible)
    could_change = [s for s in summaries if s.name in pending and qualifies(s)]
    if could_change and {s.name for s in _rank([*eligible, *could_change])} != {
        s.name for s in ranked
    }:
        return SelectionResult("AUDIT-PENDING", (), False, pending, flags)
    if ranked:
        return SelectionResult(
            "SELECTED",
            tuple(s.name for s in ranked),
            ranked[0].point >= STAGE2_MIN_NET_USD,
            pending,
            flags,
        )
    status = "AUDIT-PENDING" if pending else "SCREEN-FAIL"
    return SelectionResult(status, (), False, pending, flags)
