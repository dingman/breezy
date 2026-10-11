"""TE-2 loss taxonomy: exact tests (stdlib only, pure). Plan: TE-2_plan_r3_2.md section 2.

Every test is exact (Poisson-binomial or binomial enumeration), at station-event cluster level.
Thresholds are named constants. Nothing here reads a file or a clock.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

Status = Literal["TESTABLE", "TESTABLE-CONDITIONAL", "NOT-TESTABLE"]
Alternative = Literal["greater", "less", "two-sided"]

ALPHA_PRIMARY: Final = 0.02
ALPHA_ART: Final = 0.01
P_CLAMP: Final = 1e-9
P_PRINT_FLOOR: Final = 1e-12
PIT_TAIL_LOW: Final = 0.05
PIT_TAIL_HIGH: Final = 0.95
HOLM_MEMBERS: Final = frozenset({"T-LOC", "T-SPREAD"})
H1_SPREAD_FACTOR: Final = 2.0
#: The two-sided T-LOC p-value: twice the smaller exact tail of the number of positive cluster
#: signs (a Poisson-binomial under the pi vector), capped at 1. It is the same construction as the
#: two-sided exact sign test, so T-LOC and ``sign_test`` agree when every pi is 0.5. A probability
#: mass rule is rejected: under pi = 0.5 every sign vector is equally likely and it returns 1.0
#: for the all-same-sign outcome, which would make T-LOC untestable by construction.
T_LOC_TWO_SIDED_FORMULA: Final = "doubled_smaller_tail"


@dataclass(frozen=True)
class StationEventCluster:
    station: str
    climate_days: tuple[dt.date, ...]


@dataclass(frozen=True)
class ClusterOutcome:
    station: str
    p_c: float
    won: bool


@dataclass(frozen=True)
class WinTestResult:
    p_value: float
    rejects: bool
    n_clusters: int
    w_obs: int


@dataclass(frozen=True)
class LeaveOneOut:
    dropped_station: str
    w_obs: int
    n_clusters: int
    p_value: float
    rejects: bool


@dataclass(frozen=True)
class SpreadFill:
    pit: float
    is_tail_miss: bool
    q_f: float


@dataclass(frozen=True)
class SignTestResult:
    n_after_drops: int
    n_dropped: int
    n_positive: int
    p_value: float


@dataclass(frozen=True)
class LocResult:
    p_value: float
    p_at_pi_min: float
    p_at_pi_max: float


@dataclass(frozen=True)
class PowerResult:
    power: float
    w_star: int
    power_max_pc: float
    power_independent: float


@dataclass(frozen=True)
class HolmPlan:
    k: int
    alpha_step1: float
    statuses: Mapping[str, Status]


def poisson_binomial_pmf(probs: Sequence[float]) -> tuple[float, ...]:
    """The exact pmf of the number of successes of independent Bernoulli(p_i) trials."""
    pmf = [1.0]
    for p in probs:
        nxt = [0.0] * (len(pmf) + 1)
        for k, mass in enumerate(pmf):
            nxt[k] += mass * (1.0 - p)
            nxt[k + 1] += mass * p
        pmf = nxt
    return tuple(pmf)


def lower_tail(probs: Sequence[float], k: int) -> float:
    """P(W <= k); 0 for a negative ``k``."""
    if k < 0:
        return 0.0
    return min(1.0, math.fsum(poisson_binomial_pmf(probs)[: k + 1]))


def upper_tail(probs: Sequence[float], k: int) -> float:
    """P(X >= k), summed from the upper end so a tiny tail keeps its precision."""
    pmf = poisson_binomial_pmf(probs)
    if k <= 0:
        return 1.0
    return min(1.0, math.fsum(pmf[k:]))


def station_day_probability(p_hats: Sequence[float]) -> float:
    """P_d: the rungs of a station-day are mutually exclusive, so the probabilities add."""
    return min(1.0, math.fsum(p_hats))


def cluster_station_days(
    station_days: Sequence[tuple[str, dt.date]],
) -> tuple[StationEventCluster, ...]:
    """Station-events: consecutive climate days at one station; a one-day gap splits."""
    by_station: dict[str, list[dt.date]] = {}
    for station, day in station_days:
        by_station.setdefault(station, []).append(day)
    clusters: list[StationEventCluster] = []
    for station in sorted(by_station):
        run: list[dt.date] = []
        for day in sorted(set(by_station[station])):
            if run and (day - run[-1]).days > 1:
                clusters.append(StationEventCluster(station, tuple(run)))
                run = []
            run.append(day)
        clusters.append(StationEventCluster(station, tuple(run)))
    return tuple(clusters)


def cluster_probability(day_probs: Sequence[float]) -> float:
    """P_c: the max over the cluster's P_d, clamped below 1 (valid under any dependence)."""
    return min(max(day_probs), 1.0 - P_CLAMP)


def format_p_value(p: float) -> str:
    """A p-value below 1e-12 prints as ``< 1e-12``, never 0."""
    if p < P_PRINT_FLOOR:
        return "< 1e-12"
    return f"{p:.4g}"


def t_win(
    cluster_probs: Sequence[float], w_obs: int, *, alpha: float = ALPHA_PRIMARY
) -> WinTestResult:
    """Lower-tail P(W <= w_obs) under H0-M (independent Bernoulli(P_c) cluster wins)."""
    p = lower_tail(cluster_probs, w_obs)
    return WinTestResult(p_value=p, rejects=p <= alpha, n_clusters=len(cluster_probs), w_obs=w_obs)


def t_win_leave_one_out(
    clusters: Sequence[ClusterOutcome], *, alpha: float = ALPHA_PRIMARY
) -> LeaveOneOut:
    """Drop the largest-P_c cluster (ties to the alphabetically first station) and retest."""
    dropped = min(clusters, key=lambda c: (-c.p_c, c.station))
    rest = [c for c in clusters if c is not dropped]
    w_obs = sum(1 for c in rest if c.won)
    result = t_win([c.p_c for c in rest], w_obs, alpha=alpha)
    return LeaveOneOut(
        dropped_station=dropped.station,
        w_obs=w_obs,
        n_clusters=len(rest),
        p_value=result.p_value,
        rejects=result.rejects,
    )


def h0k_cluster_probs(day_probs_by_cluster: Sequence[Sequence[float]]) -> tuple[float, ...]:
    """The H0-K companion: the same max-over-cluster rule and clamp, on ask-implied values."""
    return tuple(cluster_probability(days) for days in day_probs_by_cluster)


def t_win_testability(null_probs: Sequence[float], *, alpha: float = ALPHA_PRIMARY) -> Status:
    """TESTABLE iff the minimum attainable p, P(W = 0) under H0-M, is at most ``alpha``."""
    return status_for_min_p(lower_tail(null_probs, 0), alpha)


def pit_midpoint_of(pmf: Mapping[int, float], tmax_f: int) -> float:
    """Mid-PIT of an integer outcome: P(X < t) + P(X = t) / 2."""
    below = math.fsum(m for v, m in pmf.items() if v < tmax_f)
    return below + pmf.get(tmax_f, 0.0) / 2.0


def spread_fill(pmf: Mapping[int, float], tmax_f: int) -> SpreadFill:
    """Per-fill mid-PIT and the null tail-miss probability, both from THIS fill's pmf."""
    pit = pit_midpoint_of(pmf, tmax_f)
    q_f = math.fsum(
        m for v, m in pmf.items() if not PIT_TAIL_LOW <= pit_midpoint_of(pmf, v) <= PIT_TAIL_HIGH
    )
    is_tail = not PIT_TAIL_LOW <= pit <= PIT_TAIL_HIGH
    return SpreadFill(pit=pit, is_tail_miss=is_tail, q_f=q_f)


def spread_cluster_null(fill_qs: Sequence[float]) -> float:
    """q_c = min(1, sum q_f): the union (Boole) upper bound, conservative for an upper tail."""
    return min(1.0, math.fsum(fill_qs))


def cluster_tail_indicator(fill_tail_flags: Sequence[bool]) -> int:
    """A_c = 1 if any fill in the cluster is a tail miss."""
    return int(any(fill_tail_flags))


def t_spread(cluster_qs: Sequence[float], x_obs: int) -> float:
    """Upper-tail P(X >= x_obs), X = sum A_c, Poisson-binomial over the cluster nulls."""
    return upper_tail(cluster_qs, x_obs)


def _binomial_half_tail(n: int, k: int, side: Literal["ge", "le"]) -> float:
    ks = range(k, n + 1) if side == "ge" else range(k + 1)
    return math.fsum(math.comb(n, i) for i in ks) / 2.0**n


def sign_test(diffs: Sequence[float], alternative: Alternative) -> SignTestResult:
    """Exact sign test at null 0.5; zeros are dropped and ``n_after_drops`` is reported."""
    nonzero = [d for d in diffs if d != 0]
    n, pos = len(nonzero), sum(1 for d in nonzero if d > 0)
    ge, le = _binomial_half_tail(n, pos, "ge"), _binomial_half_tail(n, pos, "le")
    p = {"greater": ge, "less": le, "two-sided": min(1.0, 2.0 * min(ge, le))}[alternative]
    return SignTestResult(n_after_drops=n, n_dropped=len(diffs) - n, n_positive=pos, p_value=p)


def min_attainable_p_sign(n: int, alternative: Alternative) -> float:
    """The smallest p a sign test on ``n`` untied clusters can reach."""
    base = 0.5**n
    return min(1.0, 2.0 * base) if alternative == "two-sided" else base


def status_for_min_p(min_p: float, alpha: float) -> Status:
    """TESTABLE iff the minimum attainable p is at most ``alpha``; never "did not reject"."""
    return "TESTABLE" if min_p <= alpha else "NOT-TESTABLE"


def art_testability(n_clusters: int) -> Status:
    return status_for_min_p(min_attainable_p_sign(n_clusters, "greater"), ALPHA_ART)


def t_loc_p_value(signs: Sequence[int], pis: Sequence[float]) -> float:
    """Two-sided exact p, formula ``T_LOC_TWO_SIDED_FORMULA`` (doubled smaller tail)."""
    n_pos = sum(1 for s in signs if s > 0)
    ge, le = upper_tail(pis, n_pos), lower_tail(pis, n_pos)
    return min(1.0, 2.0 * min(ge, le))


def t_loc_cluster(
    signs: Sequence[int], pi_min: Sequence[float], pi_max: Sequence[float]
) -> LocResult:
    """INDICATIVE collapse: the larger of the p-values under the all-min and all-max pi vectors."""
    p_min, p_max = t_loc_p_value(signs, pi_min), t_loc_p_value(signs, pi_max)
    return LocResult(p_value=max(p_min, p_max), p_at_pi_min=p_min, p_at_pi_max=p_max)


def t_loc_min_attainable_p(pi_min: Sequence[float], pi_max: Sequence[float]) -> float:
    """Min over the number of positive signs of the max-of-two p, with the test's own nulls."""
    n = len(pi_min)
    return min(
        t_loc_cluster([1] * k + [-1] * (n - k), pi_min, pi_max).p_value for k in range(n + 1)
    )


def t_spread_min_attainable_p(cluster_qs: Sequence[float]) -> float:
    """The smallest upper-tail p: every cluster a tail miss, P(X = n) = prod q_c."""
    return upper_tail(cluster_qs, len(cluster_qs))


def _clamped_independent_union(day_probs: Sequence[float]) -> float:
    return min(1.0 - math.prod(1.0 - p for p in day_probs), 1.0 - P_CLAMP)


def t_win_power(
    null_probs: Sequence[float],
    alt_day_probs_by_cluster: Sequence[Sequence[float]],
    *,
    alpha: float = ALPHA_PRIMARY,
) -> PowerResult:
    """Power of {W <= w*} (w* the largest w with P_H0(W <= w) <= alpha) under H1-K.

    Cluster power is the minimum over the max-P_c and the independent-union alternative.
    """
    w_star = max(
        (w for w in range(len(null_probs) + 1) if lower_tail(null_probs, w) <= alpha), default=-1
    )
    p_max = lower_tail(h0k_cluster_probs(alt_day_probs_by_cluster), w_star)
    p_ind = lower_tail([_clamped_independent_union(d) for d in alt_day_probs_by_cluster], w_star)
    return PowerResult(
        power=min(p_max, p_ind), w_star=w_star, power_max_pc=p_max, power_independent=p_ind
    )


def t_spread_power(cluster_qs: Sequence[float], *, alpha: float = ALPHA_PRIMARY) -> float:
    """Power of the T-SPREAD reject region against H1-S (each q_c doubled, capped at 1)."""
    x_star = min(
        (x for x in range(len(cluster_qs) + 1) if upper_tail(cluster_qs, x) <= alpha), default=None
    )
    if x_star is None:
        return 0.0
    h1 = [min(1.0, H1_SPREAD_FACTOR * q) for q in cluster_qs]
    return upper_tail(h1, x_star)


def holm_plan(min_ps: Mapping[str, float], *, alpha: float = ALPHA_PRIMARY) -> HolmPlan:
    """Holm members only (T-LOC, T-SPREAD); any other key (e.g. T-EDGE) is a ``ValueError``.

    A member with min p > alpha is NOT-TESTABLE and dropped BEFORE Holm, so k shrinks. Among the
    k remaining, min p <= alpha / k is TESTABLE; the rest are TESTABLE-CONDITIONAL.
    """
    extra = set(min_ps) - HOLM_MEMBERS
    if extra:
        raise ValueError(f"not Holm family members: {sorted(extra)}")
    alive = {name for name, p in min_ps.items() if p <= alpha}
    k = len(alive)
    step1 = alpha / k if k else 0.0
    statuses: dict[str, Status] = {}
    for name, p in min_ps.items():
        if name not in alive:
            statuses[name] = "NOT-TESTABLE"
        else:
            statuses[name] = "TESTABLE" if p <= step1 else "TESTABLE-CONDITIONAL"
    return HolmPlan(k=k, alpha_step1=step1, statuses=statuses)
