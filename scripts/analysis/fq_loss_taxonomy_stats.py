"""TE-2 loss taxonomy: exact tests (stdlib only, pure). WP0 stub: bodies raise NotImplementedError.

Thresholds are named constants. ``T_LOC_TWO_SIDED_FORMULA`` is a placeholder: the predeclaration
must name the two-sided T-LOC formula (doubled smaller tail, or probability-mass) before Phase B.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

Status = Literal["TESTABLE", "TESTABLE-CONDITIONAL", "NOT-TESTABLE"]
Alternative = Literal["greater", "less", "two-sided"]

ALPHA_PRIMARY: Final = 0.02
ALPHA_ART: Final = 0.01
P_CLAMP: Final = 1e-9
T_LOC_TWO_SIDED_FORMULA: Final = "UNSET: name the formula in TE2_PREDECLARATION.json before Phase B"


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
    raise NotImplementedError


def lower_tail(probs: Sequence[float], k: int) -> float:
    raise NotImplementedError


def station_day_probability(p_hats: Sequence[float]) -> float:
    raise NotImplementedError


def cluster_station_days(
    station_days: Sequence[tuple[str, dt.date]],
) -> tuple[StationEventCluster, ...]:
    raise NotImplementedError


def cluster_probability(day_probs: Sequence[float]) -> float:
    raise NotImplementedError


def format_p_value(p: float) -> str:
    raise NotImplementedError


def t_win(
    cluster_probs: Sequence[float], w_obs: int, *, alpha: float = ALPHA_PRIMARY
) -> WinTestResult:
    raise NotImplementedError


def t_win_leave_one_out(
    clusters: Sequence[ClusterOutcome], *, alpha: float = ALPHA_PRIMARY
) -> LeaveOneOut:
    raise NotImplementedError


def h0k_cluster_probs(day_probs_by_cluster: Sequence[Sequence[float]]) -> tuple[float, ...]:
    raise NotImplementedError


def t_win_testability(null_probs: Sequence[float], *, alpha: float = ALPHA_PRIMARY) -> Status:
    """TESTABLE iff the minimum attainable p, P(W = 0) under H0-M, is at most ``alpha``."""
    raise NotImplementedError


def spread_fill(pmf: Mapping[int, float], tmax_f: int) -> SpreadFill:
    raise NotImplementedError


def spread_cluster_null(fill_qs: Sequence[float]) -> float:
    raise NotImplementedError


def cluster_tail_indicator(fill_tail_flags: Sequence[bool]) -> int:
    raise NotImplementedError


def t_spread(cluster_qs: Sequence[float], x_obs: int) -> float:
    raise NotImplementedError


def sign_test(diffs: Sequence[float], alternative: Alternative) -> SignTestResult:
    raise NotImplementedError


def min_attainable_p_sign(n: int, alternative: Alternative) -> float:
    raise NotImplementedError


def status_for_min_p(min_p: float, alpha: float) -> Status:
    raise NotImplementedError


def art_testability(n_clusters: int) -> Status:
    raise NotImplementedError


def t_loc_p_value(signs: Sequence[int], pis: Sequence[float]) -> float:
    """Two-sided exact p under independent Bernoulli(pi) signs; see ``T_LOC_TWO_SIDED_FORMULA``."""
    raise NotImplementedError


def t_loc_cluster(
    signs: Sequence[int], pi_min: Sequence[float], pi_max: Sequence[float]
) -> LocResult:
    raise NotImplementedError


def t_loc_min_attainable_p(pi_min: Sequence[float], pi_max: Sequence[float]) -> float:
    raise NotImplementedError


def t_spread_min_attainable_p(cluster_qs: Sequence[float]) -> float:
    raise NotImplementedError


def t_win_power(
    null_probs: Sequence[float],
    alt_day_probs_by_cluster: Sequence[Sequence[float]],
    *,
    alpha: float = ALPHA_PRIMARY,
) -> PowerResult:
    raise NotImplementedError


def t_spread_power(cluster_qs: Sequence[float], *, alpha: float = ALPHA_PRIMARY) -> float:
    raise NotImplementedError


def holm_plan(min_ps: Mapping[str, float], *, alpha: float = ALPHA_PRIMARY) -> HolmPlan:
    """Holm members only (T-LOC, T-SPREAD); any other key (e.g. T-EDGE) is a ``ValueError``."""
    raise NotImplementedError
