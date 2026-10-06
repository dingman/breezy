"""Stage 0b scoring: the trial, the baseline ladder's metrics and their intervals (WP-6).

Scoring half of ``forecast_conditional_model_study.py``. It knows nothing about
weather, archives or models -- it takes already-priced :class:`Trial` records and
produces Brier scores, Brier Skill Scores, reliability, the pre-declared
calibration leg, and cluster block-bootstrap intervals.

THREE THINGS THIS MODULE EXISTS TO GET RIGHT
    1. EVERY METRIC NAMES ITS REFERENCE. A Brier difference is meaningless
       without the baseline it is taken against, so :class:`ClusterCI` carries
       ``against`` and every score is additionally reported as a Brier Skill
       Score against the constant base-rate reference.
    2. EVERY INTERVAL NAMES ITS CLUSTER, AND PROVES IT DID SOMETHING.
       :func:`assert_nondegenerate_clustering` REFUSES a cluster key that puts
       one trial in every cluster, and :class:`ClusterCI` records
       ``n_clusters``/``max_cluster_size`` so a reader can check.
    3. THE CALIBRATION LEG IS EVALUATED, NOT MERELY COMPUTED.
       :func:`evaluate_calibration_leg` returns an explicit PASS/FAIL against
       the pre-declared epsilon, with the offending buckets, their n and a
       z-score, plus the multiplicity note that stops a single thin-bucket miss
       from being read as a finding.

No network, no clock, no I/O, no ``nautilus_trader``.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass

from forecast_conditional_corpus import (
    LEAD_BINS_HOURS,
    CorpusRow,
)

from breezy.analysis.stats.scoring_core import (  # noqa: F401
    BOOTSTRAP_ALPHA,
    BOOTSTRAP_ITERATIONS,
    BOOTSTRAP_SEED,
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
    RELIABILITY_BUCKET_EDGES,
    RELIABILITY_EPSILON,
    CalibrationLeg,
    ClusterCI,
    LeakageError,
    ReliabilityBucket,
    SupportsClusterKey,
    Trial,
    _clusters,
    assert_nondegenerate_clustering,
    bootstrap_brier_difference_ci,
    bootstrap_cluster_draws,
    brier,
    brier_skill_score,
    evaluate_calibration_leg,
    percentile_interval,
    reliability,
    underconfidence_signal,
)


@dataclass(frozen=True, slots=True)
class PointError:
    n: int
    mae: float
    rmse: float
    bias: float

    def to_dict(self) -> dict[str, object]:
        return {"n": self.n, "mae": self.mae, "rmse": self.rmse, "bias": self.bias}


def point_error_by_lead(rows: Sequence[CorpusRow]) -> dict[int, PointError]:
    """MAE / RMSE / mean signed error of the raw ``txn`` forecast, per declared lead."""
    out: dict[int, PointError] = {}
    for lead in LEAD_BINS_HOURS:
        errs = [
            float(r.settled_tmax_f) - float(r.forecast_txn_f_by_lead[lead])
            for r in rows
            if lead in r.forecast_txn_f_by_lead
        ]
        if not errs:
            continue
        out[lead] = PointError(
            n=len(errs),
            mae=statistics.fmean([abs(e) for e in errs]),
            rmse=math.sqrt(statistics.fmean([e * e for e in errs])),
            bias=statistics.fmean(errs),
        )
    return out

