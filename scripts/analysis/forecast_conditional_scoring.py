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

import datetime as dt
import itertools
import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from forecast_conditional_corpus import (
    BOOTSTRAP_ALPHA,
    BOOTSTRAP_ITERATIONS,
    BOOTSTRAP_SEED,
    LEAD_BINS_HOURS,
    RELIABILITY_BUCKET_EDGES,
    CorpusRow,
    LeakageError,
)

#: The models on the ladder, weakest reference first. ``p_constant`` is the
#: base-rate reference the Brier Skill Scores are taken against.
MODEL_FORECAST: Final[str] = "p_fc"
MODEL_PERSISTENCE: Final[str] = "p_persistence"
MODEL_CLIMATOLOGY: Final[str] = "p_clim"
MODEL_CONSTANT: Final[str] = "p_constant"
MODEL_KEYS: Final[tuple[str, ...]] = (
    MODEL_CONSTANT,
    MODEL_CLIMATOLOGY,
    MODEL_PERSISTENCE,
    MODEL_FORECAST,
)

#: Cluster keys the bootstrap will accept. ``station_day`` is retained ONLY so
#: that it can be REFUSED loudly for the headline family, where it degenerates
#: to one trial per cluster (review defect 4).
CLUSTER_STATION_DAY: Final[str] = "station_day"
CLUSTER_DATE: Final[str] = "date"
CLUSTER_STATION: Final[str] = "station"

#: Persistence is given the SAME train-fitted bias/sigma layer as the forecast,
#: at this nominal horizon, so the two are treated like-for-like.
PERSISTENCE_HORIZON_HOURS: Final[float] = 24.0

#: The plan's pre-declared calibration leg: |observed - predicted| <= epsilon
#: in every populated reliability bucket.
RELIABILITY_EPSILON: Final[float] = 0.05
LEG_PASS: Final[str] = "PASS"
LEG_FAIL: Final[str] = "FAIL"


@dataclass(frozen=True, slots=True)
class Trial:
    """One scored binary event on one station-day, under every model on the ladder."""

    family: str
    station: str
    climate_day: dt.date
    outcome: bool
    p_fc: float
    p_clim: float
    p_persistence: float | None = None
    p_constant: float | None = None

    def probability(self, which: str) -> float:
        value = {
            MODEL_FORECAST: self.p_fc,
            MODEL_CLIMATOLOGY: self.p_clim,
            MODEL_PERSISTENCE: self.p_persistence,
            MODEL_CONSTANT: self.p_constant,
        }[which]
        if value is None:
            raise ValueError(f"trial carries no probability for {which}")
        return value

    def cluster_key(self, cluster: str) -> object:
        return {
            CLUSTER_STATION_DAY: (self.station, self.climate_day),
            CLUSTER_DATE: self.climate_day,
            CLUSTER_STATION: self.station,
        }[cluster]


def brier(trials: Sequence[Trial], which: str) -> float:
    if not trials:
        raise ValueError("brier of an empty trial set is undefined")
    return sum((t.probability(which) - float(t.outcome)) ** 2 for t in trials) / len(trials)


@dataclass(frozen=True, slots=True)
class ReliabilityBucket:
    lower: float
    upper: float
    n: int
    predicted: float
    observed: float

    @property
    def abs_deviation(self) -> float:
        return abs(self.observed - self.predicted)

    def to_dict(self) -> dict[str, object]:
        return {
            "lower": self.lower,
            "upper": self.upper,
            "n": self.n,
            "predicted": self.predicted,
            "observed": self.observed,
            "abs_deviation": self.abs_deviation,
        }


def reliability(trials: Sequence[Trial], which: str) -> tuple[ReliabilityBucket, ...]:
    edges = (0.0, *RELIABILITY_BUCKET_EDGES, 1.0)
    buckets: list[ReliabilityBucket] = []
    for lower, upper in itertools.pairwise(edges):
        members = [
            t
            for t in trials
            if lower <= t.probability(which) < upper
            or (upper == 1.0 and t.probability(which) == 1.0)
        ]
        buckets.append(
            ReliabilityBucket(
                lower=lower,
                upper=upper,
                n=len(members),
                predicted=(
                    statistics.fmean([t.probability(which) for t in members]) if members else 0.0
                ),
                observed=(
                    statistics.fmean([float(t.outcome) for t in members]) if members else 0.0
                ),
            )
        )
    return tuple(buckets)


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


@dataclass(frozen=True, slots=True)
class ClusterCI:
    """A bootstrap interval that carries the cluster it was actually taken over."""

    against: str
    cluster: str
    n_clusters: int
    max_cluster_size: int
    low: float
    high: float
    point: float

    def to_dict(self) -> dict[str, object]:
        return {
            "against": self.against,
            "cluster": self.cluster,
            "n_clusters": self.n_clusters,
            "max_cluster_size": self.max_cluster_size,
            "ci95_low": self.low,
            "ci95_high": self.high,
            "point_estimate": self.point,
        }


def _clusters(trials: Sequence[Trial], cluster: str) -> list[list[Trial]]:
    grouped: dict[object, list[Trial]] = {}
    for trial in trials:
        grouped.setdefault(trial.cluster_key(cluster), []).append(trial)
    return [grouped[key] for key in sorted(grouped, key=repr)]


def assert_nondegenerate_clustering(trials: Sequence[Trial], *, cluster: str) -> None:
    """Refuse a cluster key that puts exactly one trial in every cluster.

    Review defect 4: the first artefact labelled its interval
    ``cluster_station_day`` while the headline family carries exactly ONE trial
    per station-day -- so every cluster had size 1 and the "cluster-robust"
    bootstrap was an ordinary IID trial bootstrap wearing a cluster-robust name.
    A label that describes a dependence structure the resampling never exploited
    is worse than no label, so the degenerate case is refused rather than
    silently produced.
    """
    if cluster not in (CLUSTER_STATION_DAY, CLUSTER_DATE, CLUSTER_STATION):
        raise ValueError(f"unknown cluster key {cluster!r}")
    blocks = _clusters(trials, cluster)
    if not blocks:
        raise ValueError("clustering an empty trial set is undefined")
    largest = max(len(b) for b in blocks)
    if largest <= 1:
        raise LeakageError(
            f"degenerate clustering: every {cluster!r} cluster holds exactly one trial "
            f"({len(blocks)} clusters), so a block bootstrap over it is an IID trial "
            "bootstrap. Labelling that interval cluster-robust would misrepresent it"
        )


def bootstrap_brier_difference_ci(
    trials: Sequence[Trial],
    *,
    against: str,
    cluster: str,
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
) -> ClusterCI:
    """Cluster block bootstrap of ``Brier_fc - Brier_<against>``.

    Whole clusters are drawn with replacement, all of their trials together. The
    returned object records the cluster key, the number of clusters and the
    largest cluster, so a reader can see whether the clustering did anything --
    which is exactly what the previous version's key claimed but did not show.

    ``cluster=CLUSTER_DATE`` is the shipped choice: the four stations share a
    synoptic pattern on a given date, so a date is the smallest unit that is
    plausibly independent. ``CLUSTER_STATION`` is reported alongside it because
    it is the interval that speaks to generalising to NEW stations -- with only
    four clusters it is crude, and is labelled as such.
    """
    blocks = _clusters(trials, cluster)
    if not blocks:
        raise ValueError("bootstrap of an empty trial set is undefined")
    rng = random.Random(seed)
    diffs: list[float] = []
    for _ in range(iterations):
        drawn: list[Trial] = []
        for _ in range(len(blocks)):
            drawn.extend(blocks[rng.randrange(len(blocks))])
        diffs.append(brier(drawn, MODEL_FORECAST) - brier(drawn, against))
    diffs.sort()
    lo = diffs[max(0, math.floor((BOOTSTRAP_ALPHA / 2.0) * len(diffs)))]
    hi = diffs[min(len(diffs) - 1, math.ceil((1.0 - BOOTSTRAP_ALPHA / 2.0) * len(diffs)) - 1)]
    return ClusterCI(
        against=against,
        cluster=cluster,
        n_clusters=len(blocks),
        max_cluster_size=max(len(b) for b in blocks),
        low=lo,
        high=hi,
        point=brier(trials, MODEL_FORECAST) - brier(trials, against),
    )


def brier_skill_score(trials: Sequence[Trial], which: str) -> float:
    """BSS against the CONSTANT base-rate reference, ``1 - B_model / B_ref``.

    The reference is the holdout base rate predicted for every trial, whose
    Brier is ``p(1 - p)``. Reporting this for every model removes the dependence
    on any one chosen baseline -- the failure mode that made the first headline
    uninformative.
    """
    base_rate = statistics.fmean([float(t.outcome) for t in trials])
    reference = base_rate * (1.0 - base_rate)
    if reference == 0.0:
        return float("nan")
    return 1.0 - brier(trials, which) / reference



@dataclass(frozen=True, slots=True)
class CalibrationLeg:
    """The plan's pre-declared reliability leg, EVALUATED rather than merely computed."""

    model: str
    epsilon: float
    verdict: str
    n_buckets_evaluated: int
    failing: tuple[dict[str, object], ...]
    worst_abs_deviation: float

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "epsilon": self.epsilon,
            "verdict": self.verdict,
            "n_buckets_evaluated": self.n_buckets_evaluated,
            "n_buckets_failing": len(self.failing),
            "failing_buckets": list(self.failing),
            "worst_abs_deviation": self.worst_abs_deviation,
            "multiplicity_note": (
                "Buckets are evaluated independently at epsilon=0.05, so across ~10 "
                "populated buckets roughly half a miss is EXPECTED under a perfectly "
                "calibrated model. A small number of failures -- especially in a "
                "low-n bucket -- is reported, not acted on. Re-conditioning the model "
                "in response to one would be exactly the post-hoc move L-21 forbids."
            ),
        }


def evaluate_calibration_leg(trials: Sequence[Trial], which: str) -> CalibrationLeg:
    """Evaluate ``|observed - predicted| <= RELIABILITY_EPSILON`` per populated bucket.

    Review defect 6: the first version COMPUTED reliability and then reported a
    verdict without ever testing the leg, and the evidence document omitted
    reliability entirely. The leg now produces an explicit PASS/FAIL with the
    offending buckets and their n, and a z-score so a thin-bucket miss is
    readable as noise rather than as a finding.
    """
    populated = [b for b in reliability(trials, which) if b.n]
    failing: list[dict[str, object]] = []
    for bucket in populated:
        if bucket.abs_deviation <= RELIABILITY_EPSILON:
            continue
        variance = bucket.predicted * (1.0 - bucket.predicted) / bucket.n
        failing.append(
            {
                "lower": bucket.lower,
                "upper": bucket.upper,
                "n": bucket.n,
                "predicted": bucket.predicted,
                "observed": bucket.observed,
                "abs_deviation": bucket.abs_deviation,
                "z": bucket.abs_deviation / math.sqrt(variance) if variance > 0 else float("inf"),
            }
        )
    return CalibrationLeg(
        model=which,
        epsilon=RELIABILITY_EPSILON,
        verdict=LEG_FAIL if failing else LEG_PASS,
        n_buckets_evaluated=len(populated),
        failing=tuple(failing),
        worst_abs_deviation=max((b.abs_deviation for b in populated), default=0.0),
    )


def underconfidence_signal(trials: Sequence[Trial], which: str) -> dict[str, object]:
    """Does every populated bucket sit BELOW the outcome frequency it predicted?

    Review defect 3, forward-looking: on the rung family every fitted bucket
    predicts less than it observes, which means the fitted sigma is too WIDE and
    the model is systematically UNDER-CONFIDENT. That is a concrete, falsifiable
    prediction about live behaviour -- a ``p > price + fee`` rule driven by this
    model would UNDER-FIRE, passing on rungs it should take -- and it belongs in
    the artefact rather than in a reviewer's notes.
    """
    populated = [b for b in reliability(trials, which) if b.n]
    below = [b for b in populated if b.observed > b.predicted]
    return {
        "n_buckets": len(populated),
        "n_buckets_observed_above_predicted": len(below),
        "all_buckets_underconfident": len(populated) > 0 and len(below) == len(populated),
        "mean_signed_deviation_observed_minus_predicted": (
            statistics.fmean([b.observed - b.predicted for b in populated]) if populated else 0.0
        ),
        "live_consequence": (
            "A uniformly under-confident model states probabilities lower than the "
            "frequencies it achieves, so a live 'take when p > ask + fee' rule fed by it "
            "UNDER-FIRES: it declines rungs whose realised hit rate would have cleared "
            "the threshold. Widening confidence is the safe direction for capital and "
            "the costly direction for opportunity; WP-7 must re-check sigma against "
            "PRICE before arming anything."
        ),
    }


