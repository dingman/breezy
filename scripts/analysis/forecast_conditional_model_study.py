"""Stage 0b: does an NBS MOS forecast beat climatology at the venue's settlement? (WP-6)

WHAT THIS IS
    An OFFLINE, OUT-OF-SAMPLE measurement of FORECAST SKILL. ``forecast_conditional_corpus``
    joins three archives already on this host -- IEM NBS MOS forecasts, IEM
    1-minute ASOS observations, and parsed final NWS CLI climate days -- into one
    row per station-day. This module fits four predictive models on 2021-2024 and
    scores all four on an untouched 2025 holdout.

THE BASELINE LADDER, AND WHY CLIMATOLOGY IS NOT THE HEADLINE
    The original headline -- forecast vs climatology on "settled >= train median"
    -- was near-TAUTOLOGICAL and has been withdrawn as the headline (review
    defect 1). By construction that event sits at the training median, so ANY
    climatology is pinned near the constant-predictor Brier of
    ``base_rate * (1 - base_rate)``: measured, climatology scores barely better
    than a coin flip pooled, and WORSE than one at KSFO. A difference against a
    baseline that cannot move carries no information about the forecast.

    The headline is now ``Brier_fc`` vs ``Brier_persistence`` -- yesterday's
    settled high, given the SAME train-fitted bias and sigma treatment the
    forecast gets, so the comparison is like-for-like. Persistence is a real
    competitor: it knows the season, the station and the current regime. Beating
    it is not automatic, and it is the number to quote.

    Every model is additionally reported as a BRIER SKILL SCORE against the
    constant base-rate reference, so no comparison depends on a chosen baseline.

WHAT THIS DOES **NOT** LICENSE
    NOTHING HERE IS A TRADEABLE EDGE, AND NO NUMBER IN THIS STUDY SHOULD BE READ
    AS ONE. There is no venue price, no ask, no fee, no fill and no liftability
    anywhere in this module or its corpus. The venue prices the SAME public NBS
    guidance this study scores, so forecast skill relative to climatology or
    persistence says nothing about skill relative to the market. The tradeable
    quantity is ``p_fc - (ask + theta)`` with ``theta = 0.0695``; a 6.95-point
    fee is large next to any plausible residual mispricing. Establishing an
    economic claim requires joining the archived offer tape to these
    station-days. That is WP-7. It is not done here, and it is not implied here.

WHAT THIS IS NOT
    Not a backtest, not a trading simulation, not a strategy: it constructs no
    order, fill, position, fee or P&L and imports no Nautilus backtest machinery.
    Not the multi-variant cheap screen either -- that is WP-7, blocked on a
    pre-declared variant set with prediction-market sign-off. Nothing here
    selects a variant, and ``forecast_tape_screen.screen_tape`` structurally
    refuses a sweep.

THE SPLIT AND THE LEAK GUARDS
    Declared in ``forecast_conditional_corpus``; see that module's docstring --
    including which of them are real runtime guards and which are declarations
    over constants.
    The train-window guard is the SHIPPED
    ``breezy.strategy.weather_common.calibration.fit_error_model(train_end_exclusive=...)``,
    reused rather than reimplemented and never called from a strategy handler --
    this module is invoked by a human from the command line.

THIN DATA IS AN OUTCOME
    If a cell never reaches usable n the run reports ``INSUFFICIENT_DATA`` and
    EXITS 0. It never raises, and thin data is never dressed up as a verdict.

RECORDED LAYERING VIOLATION -- DELIBERATELY NOT FIXED HERE
    This module imports ``breezy.strategy.weather_common.calibration`` and
    ``...probability``. That literally violates "0b must not import strategy
    code", and ``lint-imports`` cannot see it because ``root_packages`` is
    ``["breezy", "nautilus_trader"]`` and ``scripts/`` is outside the graph -- so
    the contract reporting 3 kept / 0 broken is NOT evidence that this is clean.
    The reuse is deliberate: reimplementing ``fit_error_model``'s
    ``train_end_exclusive`` guard would be a second copy of the one check that
    matters most. The recommended repair -- relocating those two pure modules to
    ``breezy.forecast``, re-exporting for existing callers, and adding a
    ``forbidden`` contract -- touches imports the LIVE trading family uses and is
    deferred by the operator to its own change. Recorded, not fixed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import statistics
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

_SCRIPTS_ANALYSIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_ANALYSIS_DIR.parents[1]
for _entry in (str(_SCRIPTS_ANALYSIS_DIR), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

# The corpus half: the pre-declaration, the leak guards and the streaming
# archive readers. Re-exported below so the study is one import for a reader.
from forecast_conditional_corpus import (  # noqa: F401
    ARTEFACT_SCHEMA,
    BOOTSTRAP_ALPHA,
    BOOTSTRAP_ITERATIONS,
    BOOTSTRAP_SEED,
    CLIMATOLOGY_DOY_HALF_WINDOW,
    CLIMATOLOGY_MIN_SAMPLES,
    DECISION_UTC_HOUR,
    DECLARED_FEATURE_NAMES,
    FAMILY_MEDIAN,
    FAMILY_RUNG,
    FIT_END_EXCLUSIVE,
    FIT_START,
    HOLDOUT_END,
    HOLDOUT_START,
    LEAD_BINS_HOURS,
    MIN_HOLDOUT_STATION_DAYS_PER_STATION,
    MIN_HOLDOUT_STATION_DAYS_POOLED,
    MIN_TRAIN_STATION_DAYS,
    MOS_MODEL,
    NS,
    OBS_CADENCE_SECONDS,
    PRIMARY_LEAD_HOURS,
    R_LOCAL_HOURS,
    RELIABILITY_BUCKET_EDGES,
    RUNG_WIDTH_F,
    STATIONS,
    TARGET_DERIVED_NAMES,
    TARGET_NAME,
    TRIAL_FAMILIES,
    VERDICT_INSUFFICIENT_DATA,
    VERDICT_SCORED,
    CorpusRow,
    LeakageError,
    archive_payload_digests,
    assert_corpus_vintage,
    assert_features_exclude_target,
    assert_forecast_vintage,
    assert_single_cadence,
    assert_split_disjoint,
    assert_unique_station_days,
    build_corpus,
    corpus_digests,
    downsample_running_max,
    load_cached_corpus,
    split_corpus,
)
from forecast_conditional_report import (  # noqa: F401
    corpus_definition,
    render_artefact,
    render_markdown,
)
from forecast_conditional_scoring import (  # noqa: F401
    CLUSTER_DATE,
    CLUSTER_STATION,
    CLUSTER_STATION_DAY,
    LEG_FAIL,
    LEG_PASS,
    MODEL_CLIMATOLOGY,
    MODEL_CONSTANT,
    MODEL_FORECAST,
    MODEL_KEYS,
    MODEL_PERSISTENCE,
    PERSISTENCE_HORIZON_HOURS,
    RELIABILITY_EPSILON,
    CalibrationLeg,
    ClusterCI,
    PointError,
    ReliabilityBucket,
    Trial,
    assert_nondegenerate_clustering,
    bootstrap_brier_difference_ci,
    brier,
    brier_skill_score,
    evaluate_calibration_leg,
    point_error_by_lead,
    reliability,
    underconfidence_signal,
)

from breezy.strategy.weather_common.calibration import (
    ForecastErrorRecord,
    fit_error_model,
)
from breezy.strategy.weather_common.probability import ForecastErrorModel

# The three imports above are deliberately WIDE re-exports: this module is the one
# import a reader (or a test) needs for the whole Stage 0b surface, while the
# pre-declaration itself lives in exactly ONE place -- forecast_conditional_corpus --
# so there is no second copy of the split, the lead set or the feature set to drift.

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


def fit_train_error_model(rows: Sequence[CorpusRow]) -> ForecastErrorModel:
    """Fit the forecast bias/sigma model on TRAIN ONLY.

    Delegates the lookahead guard to the shipped
    ``fit_error_model(train_end_exclusive=...)`` rather than reimplementing it,
    so a corpus reaching into 2025 raises ``ValueError`` here.
    """
    assert_features_exclude_target(DECLARED_FEATURE_NAMES)
    records = [
        ForecastErrorRecord(
            location_id=row.station,
            target_date=row.climate_day,
            horizon_hours=float(PRIMARY_LEAD_HOURS),
            forecast_high_f=float(row.forecast_txn_f_by_lead[PRIMARY_LEAD_HOURS]),
            realized_high_f=float(row.settled_tmax_f),
        )
        for row in rows
        if PRIMARY_LEAD_HOURS in row.forecast_txn_f_by_lead
    ]
    return fit_error_model(records, train_end_exclusive=FIT_END_EXCLUSIVE)


@dataclass(frozen=True, slots=True)
class ClimatologyModel:
    """Per-(station, day-of-year) mean and sigma of the settled high, TRAIN ONLY."""

    by_station_doy: Mapping[tuple[str, int], tuple[float, float, int]]
    by_station: Mapping[str, tuple[float, float, int]]

    def predict(self, station: str, climate_day: dt.date) -> tuple[float, float] | None:
        cell = self.by_station_doy.get((station, _doy(climate_day)))
        if cell is not None and cell[2] >= CLIMATOLOGY_MIN_SAMPLES:
            return cell[0], cell[1]
        fallback = self.by_station.get(station)
        if fallback is None:
            return None
        return fallback[0], fallback[1]


def _doy(day: dt.date) -> int:
    """Day-of-year with Feb 29 folded onto Feb 28, so the grid is a fixed 365."""
    if day.month == 2 and day.day == 29:
        return dt.date(2021, 2, 28).timetuple().tm_yday
    return dt.date(2021, day.month, day.day).timetuple().tm_yday


def fit_climatology(rows: Sequence[CorpusRow]) -> ClimatologyModel:
    """Fit the baseline on TRAIN ONLY; refuses if a holdout day slipped in."""
    for row in rows:
        if row.climate_day >= FIT_END_EXCLUSIVE:
            raise ValueError(
                "lookahead bias: climatology record for "
                f"{row.station} target_date={row.climate_day.isoformat()} is at or after "
                f"train_end_exclusive={FIT_END_EXCLUSIVE.isoformat()}"
            )
    pooled: dict[tuple[str, int], list[float]] = {}
    by_station_values: dict[str, list[float]] = {}
    for row in rows:
        value = float(row.settled_tmax_f)
        by_station_values.setdefault(row.station, []).append(value)
        centre = _doy(row.climate_day)
        for offset in range(-CLIMATOLOGY_DOY_HALF_WINDOW, CLIMATOLOGY_DOY_HALF_WINDOW + 1):
            key = (row.station, ((centre - 1 + offset) % 365) + 1)
            pooled.setdefault(key, []).append(value)
    return ClimatologyModel(
        by_station_doy={key: _mu_sigma_n(vals) for key, vals in pooled.items()},
        by_station={key: _mu_sigma_n(vals) for key, vals in by_station_values.items()},
    )


def _mu_sigma_n(values: Sequence[float]) -> tuple[float, float, int]:
    n = len(values)
    mu = statistics.fmean(values)
    sigma = statistics.stdev(values) if n > 1 else 1.0
    return mu, max(sigma, 0.4), n


def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _p_at_least(threshold: int, mu: float, sigma: float) -> float:
    """P(settled integer >= threshold) with the 0.5F continuity correction."""
    return 1.0 - _norm_cdf((threshold - 0.5 - mu) / sigma)


def _p_in_rung(lower: int, mu: float, sigma: float) -> float:
    """P(settled integer in [lower, lower + RUNG_WIDTH_F - 1])."""
    upper = lower + RUNG_WIDTH_F - 1
    return _norm_cdf((upper + 0.5 - mu) / sigma) - _norm_cdf((lower - 0.5 - mu) / sigma)


# ---------------------------------------------------------------------------
# Trials and scoring
# ---------------------------------------------------------------------------


def median_thresholds(train: Sequence[CorpusRow]) -> dict[tuple[str, int], int]:
    """Per (station, month) settled-high median, from TRAIN ONLY.

    The headline event is ``settled >= T``. ``T`` is fixed from the training
    distribution so the event is roughly balanced -- and, critically, so no
    holdout observation participates in choosing it.
    """
    pooled: dict[tuple[str, int], list[int]] = {}
    for row in train:
        pooled.setdefault((row.station, row.climate_day.month), []).append(row.settled_tmax_f)
    return {key: round(statistics.median(vals)) for key, vals in pooled.items()}


def previous_settled_by_station_day(rows: Sequence[CorpusRow]) -> dict[tuple[str, dt.date], int]:
    """Map each station-day to the PRECEDING calendar day's settled high.

    Not leakage: yesterday's settled high is the persistence baseline's whole
    input and is knowable before today's decision instant. Only an exactly
    one-day gap qualifies -- a missing station-day breaks the chain rather than
    silently reaching further back, which would quietly make persistence a
    multi-day-stale predictor on exactly the days the archive is thin.

    CAVEAT, stated because it flatters the baseline this study is measured
    against: the value used is the CLI FINAL for D-1, which may still have been
    preliminary at 12:00Z on D. Persistence is therefore, if anything, slightly
    OPTIMISTIC here. The forecast beats it anyway, so the headline conclusion is
    conservative with respect to this caveat.
    """
    settled = {(row.station, row.climate_day): row.settled_tmax_f for row in rows}
    return {
        (station, day): settled[(station, day - dt.timedelta(days=1))]
        for (station, day) in settled
        if (station, day - dt.timedelta(days=1)) in settled
    }


def fit_persistence_model(
    rows: Sequence[CorpusRow], previous: Mapping[tuple[str, dt.date], int]
) -> ForecastErrorModel:
    """Fit persistence's bias/sigma with the SAME shipped fitter the forecast uses.

    Review defect 8: scoring a raw baseline against a bias-corrected,
    sigma-calibrated forecast is not a like-for-like comparison. Persistence
    gets the identical treatment -- same ``fit_error_model``, same
    ``train_end_exclusive`` lookahead guard, same per-(station, month, horizon)
    key structure -- so any remaining gap is skill, not preprocessing.
    """
    records = [
        ForecastErrorRecord(
            location_id=row.station,
            target_date=row.climate_day,
            horizon_hours=PERSISTENCE_HORIZON_HOURS,
            forecast_high_f=float(previous[(row.station, row.climate_day)]),
            realized_high_f=float(row.settled_tmax_f),
        )
        for row in rows
        if (row.station, row.climate_day) in previous
    ]
    return fit_error_model(records, train_end_exclusive=FIT_END_EXCLUSIVE)


def empirical_climatology_frequency(
    train: Sequence[CorpusRow], thresholds: Mapping[tuple[str, int], int]
) -> dict[tuple[str, int], float]:
    """Train frequency of ``settled >= T`` in each station's +/-7-DOY window.

    A NON-PARAMETRIC climatology, reported as a diagnostic beside the Gaussian
    one so the reader can see that the Gaussian baseline's near-coin-flip score
    is a property of the EVENT and not of the Gaussian assumption (review
    defect 1 nuance). Keyed by ``(station, doy)``.
    """
    pooled: dict[tuple[str, int], list[float]] = {}
    for row in train:
        threshold = thresholds.get((row.station, row.climate_day.month))
        if threshold is None:
            continue
        hit = float(row.settled_tmax_f >= threshold)
        centre = _doy(row.climate_day)
        for offset in range(-CLIMATOLOGY_DOY_HALF_WINDOW, CLIMATOLOGY_DOY_HALF_WINDOW + 1):
            pooled.setdefault((row.station, ((centre - 1 + offset) % 365) + 1), []).append(hit)
    return {key: statistics.fmean(vals) for key, vals in pooled.items()}


def build_trials(
    holdout: Sequence[CorpusRow],
    *,
    error_model: ForecastErrorModel,
    persistence_model: ForecastErrorModel,
    previous: Mapping[tuple[str, dt.date], int],
    climatology: ClimatologyModel,
    thresholds: Mapping[tuple[str, int], int],
    base_rates: Mapping[str, float],
) -> tuple[Trial, ...]:
    """One trial per station-day per family, priced by every model on the ladder.

    A station-day with no preceding day is DROPPED rather than scored without
    persistence: every model must be scored on exactly the same station-days, or
    the ladder compares different samples.
    """
    trials: list[Trial] = []
    for row in holdout:
        forecast = row.forecast_txn_f_by_lead.get(PRIMARY_LEAD_HOURS)
        if forecast is None:
            continue
        clim = climatology.predict(row.station, row.climate_day)
        if clim is None:
            continue
        prior = previous.get((row.station, row.climate_day))
        if prior is None:
            continue
        mu_fc = forecast + error_model.bias(
            row.station, row.climate_day, float(PRIMARY_LEAD_HOURS)
        )
        sigma_fc = error_model.sigma(row.station, row.climate_day, float(PRIMARY_LEAD_HOURS))
        mu_pers = prior + persistence_model.bias(
            row.station, row.climate_day, PERSISTENCE_HORIZON_HOURS
        )
        sigma_pers = persistence_model.sigma(
            row.station, row.climate_day, PERSISTENCE_HORIZON_HOURS
        )
        mu_clim, sigma_clim = clim
        threshold = thresholds.get((row.station, row.climate_day.month))
        if threshold is not None:
            trials.append(
                Trial(
                    family=FAMILY_MEDIAN,
                    station=row.station,
                    climate_day=row.climate_day,
                    outcome=row.settled_tmax_f >= threshold,
                    p_fc=_p_at_least(threshold, mu_fc, sigma_fc),
                    p_clim=_p_at_least(threshold, mu_clim, sigma_clim),
                    p_persistence=_p_at_least(threshold, mu_pers, sigma_pers),
                    p_constant=base_rates.get(FAMILY_MEDIAN, 0.5),
                )
            )
        lower = RUNG_WIDTH_F * math.floor(round(forecast) / RUNG_WIDTH_F)
        trials.append(
            Trial(
                family=FAMILY_RUNG,
                station=row.station,
                climate_day=row.climate_day,
                outcome=lower <= row.settled_tmax_f <= lower + RUNG_WIDTH_F - 1,
                p_fc=_p_in_rung(lower, mu_fc, sigma_fc),
                p_clim=_p_in_rung(lower, mu_clim, sigma_clim),
                p_persistence=_p_in_rung(lower, mu_pers, sigma_pers),
                p_constant=base_rates.get(FAMILY_RUNG, 0.5),
            )
        )
    return tuple(trials)


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EvaluationResult:
    verdict: str
    notes: tuple[str, ...]
    n_train_station_days: int
    n_holdout_station_days: int
    holdout_station_days_by_station: Mapping[str, int]
    brier_fc: float | None
    brier_clim: float | None
    brier_persistence: float | None = None
    brier_constant: float | None = None
    by_family: Mapping[str, Mapping[str, object]] = field(default_factory=dict)
    point_error: Mapping[int, PointError] = field(default_factory=dict)
    obs_cadence_seconds: int = OBS_CADENCE_SECONDS
    thresholds: Mapping[str, int] = field(default_factory=dict)
    empirical_climatology_brier: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict,
            "notes": list(self.notes),
            "trial_unit": "station-day",
            "n_train_station_days": self.n_train_station_days,
            "n_holdout_station_days": self.n_holdout_station_days,
            "holdout_station_days_by_station": {
                k: self.holdout_station_days_by_station[k]
                for k in sorted(self.holdout_station_days_by_station)
            },
            "headline_family": FAMILY_MEDIAN,
            "headline_comparison": "p_fc vs p_persistence",
            "brier_fc": self.brier_fc,
            "brier_clim": self.brier_clim,
            "brier_persistence": self.brier_persistence,
            "brier_constant": self.brier_constant,
            "empirical_climatology_brier_median_family": self.empirical_climatology_brier,
            "by_family": {k: self.by_family[k] for k in sorted(self.by_family)},
            "point_error_by_lead_hours": {
                str(k): self.point_error[k].to_dict() for k in sorted(self.point_error)
            },
            "obs_cadence_seconds": self.obs_cadence_seconds,
            "median_thresholds_f": {k: self.thresholds[k] for k in sorted(self.thresholds)},
        }


def _sufficiency_notes(
    train: Sequence[CorpusRow], holdout: Sequence[CorpusRow], per_station: Mapping[str, int]
) -> list[str]:
    notes: list[str] = []
    if len(train) < MIN_TRAIN_STATION_DAYS:
        notes.append(
            f"train station-days {len(train)} < floor {MIN_TRAIN_STATION_DAYS}"
        )
    if len(holdout) < MIN_HOLDOUT_STATION_DAYS_POOLED:
        notes.append(
            f"holdout station-days {len(holdout)} < floor {MIN_HOLDOUT_STATION_DAYS_POOLED}"
        )
    thin = sorted(
        s for s, n in per_station.items() if n < MIN_HOLDOUT_STATION_DAYS_PER_STATION
    )
    if thin:
        detail = ", ".join(f"{s}={per_station[s]}" for s in thin)
        notes.append(
            f"stations below the per-station floor "
            f"{MIN_HOLDOUT_STATION_DAYS_PER_STATION}: {detail}"
        )
    return notes


def evaluate(train: Sequence[CorpusRow], holdout: Sequence[CorpusRow]) -> EvaluationResult:
    """Fit on ``train``, score the whole ladder on ``holdout``. Thin data returns a verdict.

    Every model is scored on the IDENTICAL set of trials, so no comparison on
    the ladder is between different samples.
    """
    assert_unique_station_days(list(train) + list(holdout))
    assert_split_disjoint(train, holdout)
    assert_features_exclude_target(DECLARED_FEATURE_NAMES)
    assert_single_cadence({r.obs_cadence_seconds for r in list(train) + list(holdout)})

    per_station: dict[str, int] = {}
    for row in holdout:
        per_station[row.station] = per_station.get(row.station, 0) + 1
    notes = _sufficiency_notes(train, holdout, per_station)
    if notes:
        return EvaluationResult(
            verdict=VERDICT_INSUFFICIENT_DATA,
            notes=tuple(notes),
            n_train_station_days=len(train),
            n_holdout_station_days=len(holdout),
            holdout_station_days_by_station=per_station,
            brier_fc=None,
            brier_clim=None,
        )

    everything = list(train) + list(holdout)
    previous = previous_settled_by_station_day(everything)
    error_model = fit_train_error_model(train)
    persistence_model = fit_persistence_model(train, previous)
    climatology = fit_climatology(train)
    thresholds = median_thresholds(train)

    # The constant reference needs the holdout base rate, which is a property of
    # the OUTCOMES, never of any model. Built in a first pass with a placeholder,
    # then rebuilt once the rate is known, so no model sees it as a feature.
    provisional = build_trials(
        holdout,
        error_model=error_model,
        persistence_model=persistence_model,
        previous=previous,
        climatology=climatology,
        thresholds=thresholds,
        base_rates={},
    )
    base_rates = {
        family: statistics.fmean([float(x.outcome) for x in members])
        for family in TRIAL_FAMILIES
        if (members := [x for x in provisional if x.family == family])
    }
    trials = build_trials(
        holdout,
        error_model=error_model,
        persistence_model=persistence_model,
        previous=previous,
        climatology=climatology,
        thresholds=thresholds,
        base_rates=base_rates,
    )
    if not trials:
        return EvaluationResult(
            verdict=VERDICT_INSUFFICIENT_DATA,
            notes=("no scoreable holdout trial survived the join",),
            n_train_station_days=len(train),
            n_holdout_station_days=len(holdout),
            holdout_station_days_by_station=per_station,
            brier_fc=None,
            brier_clim=None,
        )

    by_family: dict[str, dict[str, object]] = {}
    for family in TRIAL_FAMILIES:
        members = tuple(x for x in trials if x.family == family)
        if not members:
            continue
        # The rung family's CLIMATOLOGY comparison is WITHDRAWN (review defect 3):
        # measured, that baseline scores worse than a constant, and a baseline
        # that loses to a constant is not a baseline. The rung's own fc numbers
        # are kept -- it is the venue's actual trading unit -- but it must be
        # scored against PRICE in WP-7, not against climatology here.
        comparisons = (
            (MODEL_PERSISTENCE, MODEL_CLIMATOLOGY)
            if family == FAMILY_MEDIAN
            else (MODEL_PERSISTENCE,)
        )
        intervals: list[dict[str, object]] = []
        for against in comparisons:
            for cluster in (CLUSTER_DATE, CLUSTER_STATION):
                assert_nondegenerate_clustering(members, cluster=cluster)
                intervals.append(
                    bootstrap_brier_difference_ci(
                        members, against=against, cluster=cluster
                    ).to_dict()
                )
        by_family[family] = {
            "n_trials": len(members),
            "base_rate": base_rates[family],
            "brier_by_model": {key: brier(members, key) for key in MODEL_KEYS},
            "brier_skill_score_vs_constant": {
                key: brier_skill_score(members, key) for key in MODEL_KEYS
            },
            "brier_difference_intervals": intervals,
            "station_day_clustering": (
                "REFUSED as degenerate: this family carries exactly one trial per "
                "station-day, so a station-day block bootstrap is an IID trial "
                "bootstrap. Intervals above are clustered by DATE (the shipped choice) "
                "and by STATION (only 4 clusters -- crude, but it is the interval that "
                "speaks to generalising to new stations)."
                if family == FAMILY_MEDIAN
                else "not applicable"
            ),
            "climatology_comparison": (
                "reported" if family == FAMILY_MEDIAN else
                "WITHDRAWN: measured Brier_clim on this family is WORSE than the "
                "constant base-rate reference, so it is not a baseline. Score this "
                "family against PRICE in WP-7."
            ),
            "by_station": {
                station: {
                    "n_trials": len(per),
                    "brier_by_model": {key: brier(per, key) for key in MODEL_KEYS},
                    "brier_difference_fc_minus_persistence": (
                        brier(per, MODEL_FORECAST) - brier(per, MODEL_PERSISTENCE)
                    ),
                }
                for station in sorted({x.station for x in members})
                if (per := tuple(x for x in members if x.station == station))
            },
            "reliability": {
                key: [b.to_dict() for b in reliability(members, key)] for key in MODEL_KEYS
            },
            "calibration_leg": {
                key: evaluate_calibration_leg(members, key).to_dict()
                for key in (MODEL_FORECAST, MODEL_PERSISTENCE, MODEL_CLIMATOLOGY)
            },
            "underconfidence_fc": underconfidence_signal(members, MODEL_FORECAST),
        }

    headline = tuple(x for x in trials if x.family == FAMILY_MEDIAN)
    empirical = empirical_climatology_frequency(train, thresholds)
    empirical_brier = (
        statistics.fmean(
            [
                (empirical.get((x.station, _doy(x.climate_day)), base_rates[FAMILY_MEDIAN])
                 - float(x.outcome)) ** 2
                for x in headline
            ]
        )
        if headline
        else None
    )
    return EvaluationResult(
        verdict=VERDICT_SCORED,
        notes=(),
        n_train_station_days=len(train),
        n_holdout_station_days=len(holdout),
        holdout_station_days_by_station=per_station,
        brier_fc=brier(headline, MODEL_FORECAST) if headline else None,
        brier_clim=brier(headline, MODEL_CLIMATOLOGY) if headline else None,
        brier_persistence=brier(headline, MODEL_PERSISTENCE) if headline else None,
        brier_constant=brier(headline, MODEL_CONSTANT) if headline else None,
        by_family=by_family,
        point_error=point_error_by_lead(holdout),
        obs_cadence_seconds=OBS_CADENCE_SECONDS,
        thresholds={f"{s}|{m}": v for (s, m), v in thresholds.items()},
        empirical_climatology_brier=empirical_brier,
    )


def exit_code_for(verdict: str) -> int:
    """INSUFFICIENT_DATA is a reported outcome, so it exits 0 like a scored run."""
    return 0 if verdict in (VERDICT_SCORED, VERDICT_INSUFFICIENT_DATA) else 1


# ---------------------------------------------------------------------------
# Artefact
# ---------------------------------------------------------------------------


DEFAULT_ARTEFACT: Final[Path] = (
    Path.home() / ".local/share/breezy/derived/forecast_conditional_model_study_wp6.json"
)
DEFAULT_MARKDOWN: Final[Path] = (
    _REPO_ROOT / "docs" / "evidence" / "FC_0b_FIT_AND_HOLDOUT_2026-09-19.md"
)


def code_provenance() -> dict[str, str]:
    """Commit SHA + worktree cleanliness of the code that produced the artefact.

    Read with ``git`` locally; no network. A dirty worktree is RECORDED as dirty
    rather than suppressed -- an artefact that cannot be traced to committed code
    should say so on its face, not look pristine.
    """
    import subprocess

    out: dict[str, str] = {}
    for label, command in (
        ("commit", ("git", "rev-parse", "HEAD")),
        ("branch", ("git", "rev-parse", "--abbrev-ref", "HEAD")),
        ("status_porcelain_lines", ("git", "status", "--porcelain")),
    ):
        try:
            result = subprocess.run(
                command, cwd=_REPO_ROOT, capture_output=True, text=True, check=True, timeout=30
            )
        except (OSError, subprocess.SubprocessError):
            out[label] = "UNAVAILABLE"
            continue
        value = result.stdout.strip()
        out[label] = (
            str(len(value.splitlines())) if label == "status_porcelain_lines" else value
        )
    out["worktree"] = "CLEAN" if out.get("status_porcelain_lines") == "0" else "DIRTY"
    for name in (
        "forecast_conditional_corpus.py",
        "forecast_conditional_model_study.py",
        "forecast_conditional_report.py",
        "forecast_conditional_scoring.py",
    ):
        path = _SCRIPTS_ANALYSIS_DIR / name
        out[f"sha256:{name}"] = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else "ABSENT"
        )
    return out


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stage 0b fit + 2025 holdout (WP-6)")
    parser.add_argument("--artefact", type=Path, default=DEFAULT_ARTEFACT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--corpus-json", type=Path, default=None)
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    progress = None if args.quiet else (lambda m: print(m, file=sys.stderr))

    if args.corpus_json is not None and args.corpus_json.is_file():
        # NOT a cheap path: the loader re-runs uniqueness, VINTAGE and cadence
        # over the untrusted file (review defect 5).
        rows = load_cached_corpus(args.corpus_json)
    else:
        rows = build_corpus(start=FIT_START, end=HOLDOUT_END, progress=progress)
        if args.corpus_json is not None:
            args.corpus_json.parent.mkdir(parents=True, exist_ok=True)
            args.corpus_json.write_text(
                json.dumps([r.to_dict() for r in rows], indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    train, holdout = split_corpus(rows)
    result = evaluate(train, holdout)
    artefact = render_artefact(
        result,
        input_digests=corpus_digests(rows),
        source_digests=archive_payload_digests(),
        provenance=code_provenance(),
    )
    args.artefact.parent.mkdir(parents=True, exist_ok=True)
    args.artefact.write_text(artefact, encoding="utf-8")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(render_markdown(result), encoding="utf-8")
    print(render_markdown(result))
    return exit_code_for(result.verdict)


if __name__ == "__main__":
    raise SystemExit(main())
