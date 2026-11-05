"""Pure NBP drift and freshness predicates (AUT-6 WP5, plan r15 section 2).

Moved unchanged in behaviour from ``scripts/analysis/nbp_learning_nightly.py`` so the AUT-6 daily
producer can call them without importing a script. Nothing here sends an alert, reads a file or
touches the clock: the nightly script keeps the alerting and the positive controls and calls these
for the numbers. Weather-only; the frozen holdout is excluded by :func:`final_pre_holdout_rows`.
"""

from __future__ import annotations

import datetime as dt
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from breezy.analysis.nbp_calibration import (
    DEFAULT_SPLITS,
    FIT_STATUS_OK,
    FitNotConvergedError,
    NbpCalibrationArtefact,
    crps_numerical,
)
from breezy.domain.quantile_density import CdfMethod, EmosParams, Percentiles, apply_emos, build_cdf

__all__ = [
    "DRIFT_CALIBRATION_CRPS_DELTA_THRESHOLD_F",
    "DRIFT_MEAN_RESIDUAL_THRESHOLD_F",
    "FINAL_LABEL_STALE_AFTER",
    "HOLDOUT_START",
    "LABEL_STATUS_FINAL",
    "LABEL_STATUS_PROVISIONAL",
    "NBP_STALE_CYCLE_AFTER",
    "DriftResult",
    "FreshnessResult",
    "LearningRow",
    "calibration_crps_delta",
    "compute_freshness",
    "drift_flags",
    "final_pre_holdout_rows",
    "instant_from_ns",
    "newest_final_label_day",
]

_NS_PER_SECOND: Final[int] = 1_000_000_000
HOLDOUT_START: Final[dt.date] = DEFAULT_SPLITS.holdout_start

LABEL_STATUS_FINAL: Final[str] = "FINAL"
LABEL_STATUS_PROVISIONAL: Final[str] = "PROVISIONAL"

# NBP TXN cycles used by this family are 01Z, 13Z and 19Z; the longest normal
# gap is 12h (01Z->13Z). 18h gives one missed/pending cycle's worth of slack
# while still alerting before a whole cadence day disappears.
NBP_STALE_CYCLE_AFTER: Final[dt.timedelta] = dt.timedelta(hours=18)

# Final CLI rows usually publish after the climate day has ended, with
# overnight local lag. 72h tolerates weekend/backfill latency but alerts
# before the learning loop can silently run for several nights on old labels.
FINAL_LABEL_STALE_AFTER: Final[dt.timedelta] = dt.timedelta(hours=72)

DRIFT_MEAN_RESIDUAL_THRESHOLD_F: Final[float] = 2.5
# A >0.75 degF average CRPS regression is larger than routine tenth-degree
# numerical jitter and large enough to matter before it can dominate rung edge.
DRIFT_CALIBRATION_CRPS_DELTA_THRESHOLD_F: Final[float] = 0.75


@dataclass(frozen=True, slots=True)
class LearningRow:
    station: str
    climate_day: dt.date
    label_status: str
    cli_tmax_f: float
    m2_median_f: float
    p_m2: float
    p_m1: float
    outcome: bool
    percentiles: Percentiles | None = None
    nbm_version: str = "v5.0"

    @property
    def residual_f(self) -> float:
        return self.cli_tmax_f - self.m2_median_f


@dataclass(frozen=True, slots=True)
class FreshnessResult:
    newest_cycle: dt.datetime | None
    newest_final_label_day: dt.date | None
    stale_cycle: bool
    stale_label: bool


@dataclass(frozen=True, slots=True)
class DriftResult:
    n: int
    mean_residual_f: float | None
    shift_f: float | None
    drifted: bool
    calibration_crps_delta: float | None
    calibration_drifted: bool


def instant_from_ns(ns: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(ns / _NS_PER_SECOND, tz=dt.UTC)


def final_pre_holdout_rows(rows: Sequence[LearningRow]) -> tuple[LearningRow, ...]:
    return tuple(
        row
        for row in rows
        if row.label_status == LABEL_STATUS_FINAL and row.climate_day < HOLDOUT_START
    )


def newest_final_label_day(rows: Sequence[LearningRow]) -> dt.date | None:
    return max(
        (row.climate_day for row in rows if row.label_status == LABEL_STATUS_FINAL),
        default=None,
    )


def _label_freshness_instant(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day + dt.timedelta(days=1), dt.time.min, tzinfo=dt.UTC)


def compute_freshness(
    *,
    newest_cycle: dt.datetime | None,
    newest_label_day: dt.date | None,
    now: dt.datetime,
) -> FreshnessResult:
    """Stale-cycle and stale-label flags; a missing cycle or label day is stale."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    stale_cycle = newest_cycle is None or now - newest_cycle > NBP_STALE_CYCLE_AFTER
    stale_label = (
        newest_label_day is None
        or now - _label_freshness_instant(newest_label_day) > FINAL_LABEL_STALE_AFTER
    )
    return FreshnessResult(
        newest_cycle=newest_cycle,
        newest_final_label_day=newest_label_day,
        stale_cycle=stale_cycle,
        stale_label=stale_label,
    )


def calibration_crps_delta(
    rows: Sequence[LearningRow],
    *,
    frozen_artefact: NbpCalibrationArtefact | None,
) -> float | None:
    if frozen_artefact is None:
        return None
    if frozen_artefact.fit_status != FIT_STATUS_OK:
        raise FitNotConvergedError(
            f"frozen artefact refused: fit_status={frozen_artefact.fit_status!r}, "
            f"not {FIT_STATUS_OK!r}"
        )
    method = CdfMethod(frozen_artefact.cdf_method)
    deltas: list[float] = []
    for row in rows:
        if row.percentiles is None:
            continue
        params = frozen_artefact.emos_params_by_version.get(row.nbm_version)
        if params is None:
            continue
        a, gamma = params
        base_cdf = build_cdf(method, row.percentiles)
        frozen_cdf = apply_emos(
            base_cdf,
            row.percentiles,
            EmosParams(a=a, gamma=gamma, delta=frozen_artefact.delta),
        )
        frozen_crps = crps_numerical(frozen_cdf, row.cli_tmax_f, center=row.percentiles.q50)
        raw_crps = crps_numerical(base_cdf, row.cli_tmax_f, center=row.percentiles.q50)
        deltas.append(frozen_crps - raw_crps)
    if not deltas:
        return None
    return statistics.fmean(deltas)


def drift_flags(
    *,
    rows: Sequence[LearningRow],
    frozen_mean_residual_f: float = 0.0,
    frozen_artefact: NbpCalibrationArtefact | None = None,
    positive_control: bool = False,
    calibration_positive_control: bool = False,
) -> DriftResult:
    """Mean-residual shift and calibration CRPS delta over the FINAL pre-holdout rows."""
    final_rows = final_pre_holdout_rows(rows)
    if not final_rows and not positive_control and not calibration_positive_control:
        return DriftResult(
            n=0,
            mean_residual_f=None,
            shift_f=None,
            drifted=False,
            calibration_crps_delta=None,
            calibration_drifted=False,
        )
    mean_residual = (
        frozen_mean_residual_f + DRIFT_MEAN_RESIDUAL_THRESHOLD_F + 0.1
        if positive_control
        else statistics.fmean(row.residual_f for row in final_rows)
        if final_rows
        else None
    )
    shift = None if mean_residual is None else mean_residual - frozen_mean_residual_f
    drifted = shift is not None and abs(shift) > DRIFT_MEAN_RESIDUAL_THRESHOLD_F
    crps_delta = calibration_crps_delta(final_rows, frozen_artefact=frozen_artefact)
    if calibration_positive_control:
        crps_delta = DRIFT_CALIBRATION_CRPS_DELTA_THRESHOLD_F + 0.1
    calibration_drifted = (
        crps_delta is not None and crps_delta > DRIFT_CALIBRATION_CRPS_DELTA_THRESHOLD_F
    )
    return DriftResult(
        n=len(final_rows),
        mean_residual_f=mean_residual,
        shift_f=shift,
        drifted=drifted,
        calibration_crps_delta=crps_delta,
        calibration_drifted=calibration_drifted,
    )
