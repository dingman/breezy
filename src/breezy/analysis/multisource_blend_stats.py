"""F13 Phase A blend, part 4: paired-delta statistics, acceptance rules, reporting and gates.

Split out of ``breezy.analysis.multisource_blend``; re-exported by that facade.
"""

from __future__ import annotations

import datetime as dt
import math
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

import numpy as np
from scipy.special import stdtr, stdtrit

from breezy.analysis.multisource_blend_features import (
    HORIZONS,
    LEVEL_SOURCES,
    C1LagEvidenceError,
    FeatureRow,
    InsufficientFoldsError,
    InsufficientRowsError,
    PreregIncompleteError,
)
from breezy.analysis.multisource_blend_folds import ScoredRow, blend_cdf

#: Plan acceptance 1: the lower bound is one-sided 97.5 %.
ALPHA_ONE_SIDED: Final[float] = 0.025
_LOG_FLOOR: Final[float] = 1e-12

# ------------------------------------------------------------------ statistics


def mean_arm_crps(scored: Sequence[ScoredRow], arm: str) -> float:
    values = [s.crps[arm] for s in scored if arm in s.crps]
    if not values:
        raise InsufficientRowsError(f"no scored rows carry arm {arm!r}")
    return math.fsum(values) / len(values)


def mean_arm_difference(scored: Sequence[ScoredRow], first: str, second: str) -> float:
    """Mean of ``CRPS(first) - CRPS(second)``; positive means ``second`` is better."""
    values = [
        s.crps[first] - s.crps[second] for s in scored if first in s.crps and second in s.crps
    ]
    if not values:
        raise InsufficientRowsError(f"no scored rows carry both {first!r} and {second!r}")
    return math.fsum(values) / len(values)


def _grouped_difference(
    scored: Sequence[ScoredRow], first: str, second: str, key: Callable[[ScoredRow], Any]
) -> dict[Any, float]:
    groups: dict[Any, list[float]] = {}
    for s in scored:
        if first in s.crps and second in s.crps:
            groups.setdefault(key(s), []).append(s.crps[first] - s.crps[second])
    return {k: math.fsum(v) / len(v) for k, v in groups.items()}


def delta_by_day(
    scored: Sequence[ScoredRow], first: str, second: str
) -> list[tuple[dt.date, float]]:
    """One value per climate day: the mean difference across stations and horizons."""
    return sorted(_grouped_difference(scored, first, second, lambda s: s.climate_day).items())


def per_fold_delta(scored: Sequence[ScoredRow], first: str, second: str) -> dict[int, float]:
    return _grouped_difference(scored, first, second, lambda s: s.fold_id)


def per_station_delta(scored: Sequence[ScoredRow], first: str, second: str) -> dict[str, float]:
    return _grouped_difference(scored, first, second, lambda s: s.station)


def fold_mean_crps(scored: Sequence[ScoredRow], arm: str) -> dict[int, float]:
    groups: dict[int, list[float]] = {}
    for s in scored:
        if arm in s.crps and s.fold_id is not None:
            groups.setdefault(s.fold_id, []).append(s.crps[arm])
    return {k: math.fsum(v) / len(v) for k, v in sorted(groups.items())}


def stationary_bootstrap_means(
    values: Sequence[float], *, mean_block: float, n_boot: int, seed: int
) -> list[float]:
    """Politis-Romano stationary bootstrap of the mean (geometric blocks, circular), ascending.

    No stationary bootstrap exists elsewhere in the repo (``scoring_core`` and ``release_timing``
    resample i.i.d. clusters), so this is the one implementation of it.

    Two documented approximations (S6): ``values`` are treated as ADJACENT in time, so a
    non-adjacent climate day (a gap left by a missing or excluded day) is bridged as if it followed
    its predecessor; and the series is CIRCULAR, so a block that runs past the last value wraps to
    the first, joining two ends that are not neighbours. Both slightly understate the dependence
    structure at gaps and at the ends; neither is corrected here.
    """
    n = len(values)
    if n < 2:
        raise ValueError("a stationary bootstrap needs at least 2 observations")
    if mean_block < 1.0 or n_boot < 1:
        raise ValueError("mean_block must be >= 1 and n_boot >= 1")
    data = np.asarray(values, dtype=np.float64)
    rng = np.random.default_rng(seed)
    positions = np.arange(n)
    means = np.empty(n_boot, dtype=np.float64)
    for i in range(n_boot):
        fresh = rng.random(n) < 1.0 / mean_block
        fresh[0] = True
        last = np.maximum.accumulate(np.where(fresh, positions, 0))
        starts = rng.integers(0, n, size=n)
        means[i] = data[(starts[last] + positions - last) % n].mean()
    return sorted(float(v) for v in means)


def lower_bound_one_sided(draws: Sequence[float], alpha: float = ALPHA_ONE_SIDED) -> float:
    if not draws:
        raise ValueError("a bound over zero draws is undefined")
    ordered = sorted(draws)
    return ordered[min(len(ordered) - 1, int(alpha * len(ordered)))]


@dataclass(frozen=True, slots=True)
class DeltaSummary:
    mean: float
    lb: float
    n_days: int


def delta_summary(
    day_values: Sequence[tuple[dt.date, float]], *, n_boot: int, seed: int, mean_block: float = 7.0
) -> DeltaSummary:
    ordered = [v for _day, v in sorted(day_values)]
    draws = stationary_bootstrap_means(ordered, mean_block=mean_block, n_boot=n_boot, seed=seed)
    return DeltaSummary(
        mean=math.fsum(ordered) / len(ordered),
        lb=lower_bound_one_sided(draws),
        n_days=len(ordered),
    )


def fold_sd(values: Sequence[float]) -> float:
    if len(values) < 2:
        raise InsufficientFoldsError("a fold-to-fold SD needs at least 2 folds")
    return statistics.stdev(values)


def minimum_effect_floor(m0_fold_crps: Sequence[float], multiple: float | None) -> float:
    """R15: the floor is a pre-registered multiple of the M0 fold-to-fold CRPS SD."""
    if multiple is None or not (math.isfinite(multiple) and multiple > 0.0):
        raise PreregIncompleteError("floor_multiple is not pinned in the prereg")
    return multiple * fold_sd(m0_fold_crps)


def fold_sign_threshold(n_folds: int) -> int:
    """``ceil(0.75 * n_folds)`` in integer arithmetic."""
    return (3 * n_folds + 3) // 4


@dataclass(frozen=True, slots=True)
class M0PrimeStatus:
    within_tolerance: bool
    worse_than_champion: bool
    difference: float


def m0_prime_status(*, m0_crps: float, m0_prime_crps: float, tolerance: float) -> M0PrimeStatus:
    """M0' must not be worse than M0 by more than ``tolerance`` (absolute CRPS, degF)."""
    difference = m0_prime_crps - m0_crps
    return M0PrimeStatus(difference <= tolerance, difference > 0.0, difference)


class Verdict(StrEnum):
    ACCEPT = "ACCEPT"
    NO_SKILL = "NO_SKILL"
    HELD_LEAK_AUDIT = "HELD_LEAK_AUDIT"
    REFUSED_M0PRIME_WORSE = "REFUSED_M0PRIME_WORSE"


@dataclass(frozen=True, slots=True)
class AcceptanceInputs:
    m0p_vs_m3: DeltaSummary
    m0_vs_m3: DeltaSummary
    fold_means_m0p_vs_m3: Sequence[float]
    m0_fold_crps: Sequence[float]
    floor_multiple: float | None
    leak_audit_multiple: float | None
    m0p_minus_m0: float
    m0p_tolerance: float | None
    station_deltas: Mapping[str, float]
    station_tolerance: float | None
    lag_rerun: DeltaSummary | None
    lag_rows_lost: Any
    #: S2: M0' vs M3 re-scored on shuffled labels; a positive one-sided lower bound is a leak
    negative_control: DeltaSummary


@dataclass(frozen=True, slots=True)
class AcceptanceDecision:
    verdict: Verdict
    reasons: tuple[str, ...]
    report: dict[str, Any]


def _lb_failures(label: str, summary: DeltaSummary, floor: float) -> list[str]:
    failures: list[str] = []
    if not summary.lb > 0.0:
        failures.append(f"{label} one-sided 97.5% lower bound {summary.lb:.4f} is not > 0")
    if summary.lb < floor:
        failures.append(f"{label} lower bound {summary.lb:.4f} is below the floor {floor:.4f}")
    return failures


def _leak_reasons(inputs: AcceptanceInputs, spread: float) -> list[str]:
    """S2 / S4: anything that looks too good, or skill found in shuffled labels, holds the run."""
    assert inputs.leak_audit_multiple is not None
    limit = inputs.leak_audit_multiple * spread
    reasons = [
        f"delta {label} {summary.mean:.4f} exceeds {inputs.leak_audit_multiple} x the fold "
        f"spread {spread:.4f}: audit for leakage before believing it"
        for label, summary in (
            ("CRPS(M0prime) - CRPS(M3)", inputs.m0p_vs_m3),
            ("CRPS(M0) - CRPS(M3)", inputs.m0_vs_m3),
        )
        if summary.mean > limit
    ]
    if inputs.negative_control.lb > 0.0:
        reasons.append(
            f"negative control (shuffled labels) one-sided lower bound "
            f"{inputs.negative_control.lb:.4f} is > 0: the pipeline finds skill in noise"
        )
    return reasons


def decide_acceptance(inputs: AcceptanceInputs) -> AcceptanceDecision:
    """Acceptance 1-8 (R15, R25). Acceptance 9 is the diagnostics report."""
    for name in ("m0p_tolerance", "station_tolerance", "leak_audit_multiple"):
        if getattr(inputs, name) is None:
            raise PreregIncompleteError(f"{name} is not pinned in the prereg")
    assert inputs.m0p_tolerance is not None and inputs.station_tolerance is not None
    assert inputs.leak_audit_multiple is not None
    floor = minimum_effect_floor(inputs.m0_fold_crps, inputs.floor_multiple)
    spread = fold_sd(inputs.m0_fold_crps)
    report: dict[str, Any] = {
        "floor": floor,
        "floor_multiple": inputs.floor_multiple,
        "m0_fold_sd": spread,
        "fold_sign_needed": fold_sign_threshold(len(inputs.fold_means_m0p_vs_m3)),
        "m0p_vs_m0_two_sided": {
            "difference": inputs.m0p_minus_m0,
            "abs_difference": abs(inputs.m0p_minus_m0),
            "tolerance": inputs.m0p_tolerance,
            "gating": "one_sided_worse_only",
        },
        "negative_control": {
            "mean": inputs.negative_control.mean,
            "lb": inputs.negative_control.lb,
            "n_days": inputs.negative_control.n_days,
        },
        "lag_rerun": {
            "mean": None if inputs.lag_rerun is None else inputs.lag_rerun.mean,
            "lb": None if inputs.lag_rerun is None else inputs.lag_rerun.lb,
            "rows_lost": inputs.lag_rows_lost,
        },
    }
    leaks = _leak_reasons(inputs, spread)
    if leaks:
        return AcceptanceDecision(Verdict.HELD_LEAK_AUDIT, tuple(leaks), report)
    if inputs.m0p_minus_m0 > inputs.m0p_tolerance:
        reason = (
            f"M0' is worse than M0 by {inputs.m0p_minus_m0:.4f}, beyond the tolerance "
            f"{inputs.m0p_tolerance}"
        )
        return AcceptanceDecision(Verdict.REFUSED_M0PRIME_WORSE, (reason,), report)
    reasons = _lb_failures("CRPS(M0prime) - CRPS(M3)", inputs.m0p_vs_m3, floor)
    reasons += _lb_failures("CRPS(M0) - CRPS(M3)", inputs.m0_vs_m3, floor)
    positive = sum(1 for v in inputs.fold_means_m0p_vs_m3 if v > 0.0)
    needed = report["fold_sign_needed"]
    if positive < needed:
        reasons.append(
            f"only {positive} of {len(inputs.fold_means_m0p_vs_m3)} folds improve (need {needed})"
        )
    reasons += [
        f"station {station} degraded: mean delta {value:.4f} is below -{inputs.station_tolerance}"
        for station, value in sorted(inputs.station_deltas.items())
        if value < -inputs.station_tolerance
    ]
    if inputs.lag_rerun is None:
        reasons.append("the +60 min lag-sensitivity rerun is absent")
    elif inputs.lag_rerun.lb < 0.0:
        reasons.append(f"lag +60 min rerun lower bound {inputs.lag_rerun.lb:.4f} is below 0")
    verdict = Verdict.NO_SKILL if reasons else Verdict.ACCEPT
    return AcceptanceDecision(verdict, tuple(reasons), report)


# ------------------------------------------------------------------ reporting + gates


@dataclass(frozen=True, slots=True)
class Missingness:
    n: int
    missing: int

    @property
    def share(self) -> float:
        return self.missing / self.n if self.n else 0.0


def level_counts(scored: Sequence[ScoredRow], arm: str) -> dict[int, int]:
    """S3: rows by the ladder level ``arm`` effectively scored them at. Reported, never gating."""
    counts: dict[int, int] = {}
    for s in scored:
        if arm in s.levels:
            counts[s.levels[arm]] = counts.get(s.levels[arm], 0) + 1
    return dict(sorted(counts.items()))


def complete_case_delta(scored: Sequence[ScoredRow], first: str, second: str) -> dict[str, Any]:
    """S3: ``CRPS(first) - CRPS(second)`` over rows where ``second`` used EVERY source (LAMP, PFM
    and MOS present). Diagnostic only: it conditions on source availability and never gates."""
    complete = [
        s.crps[first] - s.crps[second]
        for s in scored
        if s.levels.get(second) == len(LEVEL_SOURCES) and first in s.crps and second in s.crps
    ]
    days = {
        s.climate_day
        for s in scored
        if s.levels.get(second) == len(LEVEL_SOURCES) and first in s.crps and second in s.crps
    }
    return {
        "label": "diagnostic_only_never_gating",
        "n_rows": len(complete),
        "n_days": len(days),
        "mean": math.fsum(complete) / len(complete) if complete else None,
    }


def lamp_missingness_by_horizon(rows: Sequence[FeatureRow]) -> dict[str, Missingness]:
    out: dict[str, Missingness] = {}
    for horizon in HORIZONS:
        subset = [r for r in rows if r.horizon == horizon]
        if subset:
            out[horizon] = Missingness(len(subset), sum(1 for r in subset if r.lamp.missing))
    return out


def lag_rows_lost(base: Sequence[FeatureRow], shifted: Sequence[FeatureRow]) -> dict[str, int]:
    """Rows whose source is present in ``base`` and absent after the +60 min lag shift."""
    after = {(r.station, r.climate_day, r.horizon): r for r in shifted}
    lost = {"lamp": 0, "pfm": 0, "mos": 0}
    for row in base:
        other = after.get((row.station, row.climate_day, row.horizon))
        if other is None:
            continue
        lost["lamp"] += int(not row.lamp.missing and other.lamp.missing)
        lost["pfm"] += int(row.pfm_mu_f is not None and other.pfm_mu_f is None)
        lost["mos"] += int(row.mos_mu_f is not None and other.mos_mu_f is None)
    return lost


def diagnostics(
    scored: Sequence[ScoredRow], *, arm: str, nu: float, rung_edges: Sequence[int]
) -> dict[str, Any]:
    """Acceptance 9: CRPS by horizon, PIT, 80/95 coverage, rung-ladder log score, RMSE."""
    rows = [s for s in scored if arm in s.arm_predictions]
    if not rows:
        raise InsufficientRowsError(f"no scored rows carry arm {arm!r}")
    edges = [float(e) - 0.5 for e in sorted(rung_edges)]
    pit_bins = [0] * 10
    inside = {0.8: 0, 0.95: 0}
    log_scores: list[float] = []
    squared: list[float] = []
    by_horizon: dict[str, list[float]] = {}
    for s in rows:
        p = s.arm_predictions[arm]
        z = (s.observed_f - p.mu) / p.sigma
        pit_bins[min(9, int(float(stdtr(nu, z)) * 10))] += 1
        for level in inside:
            inside[level] += int(abs(z) <= float(stdtrit(nu, 0.5 + level / 2.0)))
        cdf = blend_cdf(p)
        label = round(s.observed_f) - 0.5
        lower = max((e for e in edges if e <= label), default=None)
        upper = min((e for e in edges if e > label), default=None)
        mass = (1.0 if upper is None else cdf(upper)) - (0.0 if lower is None else cdf(lower))
        log_scores.append(math.log(max(mass, _LOG_FLOOR)))
        squared.append((p.mu - s.observed_f) ** 2)
        by_horizon.setdefault(s.horizon, []).append(s.crps[arm])
    n = len(rows)
    return {
        "arm": arm,
        "n": n,
        "crps_by_horizon": {h: math.fsum(v) / len(v) for h, v in sorted(by_horizon.items())},
        "pit_histogram": pit_bins,
        "coverage_80": inside[0.8] / n,
        "coverage_95": inside[0.95] / n,
        "mean_rung_log_score": math.fsum(log_scores) / n,
        "rmse_descriptive": math.sqrt(math.fsum(squared) / n),
        "rmse_label": "descriptive_only",
    }


#: C1 lag evidence and ``pins.source_lags_ns`` (C1-R4). Not the feature ``LEVEL_SOURCES``.
C1_LAG_SOURCES: Final[tuple[str, ...]] = ("lamp-mdl", "lav-iem", "pfm", "mos-gfs", "obs")


def require_c1_measured_lags(
    measured_days: Mapping[str, int],
    *,
    required: Sequence[str],
    min_days: int = 14,
    uncensored: Mapping[str, int] | None = None,
    min_uncensored: int | None = None,
) -> None:
    """Phase A scores only after C1 has measured every source's lag for ``min_days`` days."""
    for source in required:
        days = measured_days.get(source)
        if days is None or days < min_days:
            raise C1LagEvidenceError(
                f"C1 has {days} measured lag days for {source!r}; Phase A needs {min_days}"
            )
        if min_uncensored is not None:
            count = (uncensored or {}).get(source)
            if count is None or count < min_uncensored:
                raise C1LagEvidenceError(
                    f"C1 has {count} uncensored lag samples for {source!r}; needs {min_uncensored}"
                )
