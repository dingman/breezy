"""TE-2 FQ v1 loss taxonomy: the pure core (no I/O).

WP0 stub. Every public function raises ``NotImplementedError``; the dataclasses are
structure only. Plan: ``docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-2_plan_r3_2.md``.
Statistics use the standard library only; band geometry comes only from
``bucket_facts_from_instrument_id`` (inclusive ``[A, B]``).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

Status = Literal["TESTABLE", "TESTABLE-CONDITIONAL", "NOT-TESTABLE"]
Alternative = Literal["greater", "less", "two-sided"]


@dataclass(frozen=True)
class FillFacts:
    """One fill's outcome-dependent descriptors, as the classifier consumes them."""

    fill_id: str
    station: str
    climate_day: dt.date
    edge_dist: int
    pit: float
    won: bool
    partition_complete: bool = True


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


@dataclass(frozen=True)
class HypothesisOutcome:
    name: str
    status: Status
    rejects: bool
    p_value: float | None = None
    power: float | None = None


@dataclass(frozen=True)
class VerdictInputs:
    t_win: HypothesisOutcome
    loo_rejects: bool
    t_loc: HypothesisOutcome
    t_spread: HypothesisOutcome
    t_art: HypothesisOutcome
    has_k4: bool = False
    material_k1a: bool = False
    k3_present: bool = False
    k1b_present: bool = False


@dataclass(frozen=True)
class Verdict:
    label: str
    sublabel: str | None
    qualifiers: tuple[str, ...]
    reason: str | None
    notes: tuple[str, ...]


@dataclass(frozen=True)
class DowngradeResult:
    decisions: Mapping[str, bool]
    range_notes: tuple[str, ...]
    scope_sensitive: tuple[str, ...]


@dataclass(frozen=True)
class K1bResult:
    flagged_fill_ids: tuple[str, ...]
    flagged_station_days: frozenset[tuple[str, dt.date]]
    in_scope_station_days: tuple[tuple[str, dt.date], ...]


@dataclass(frozen=True)
class TieReevaluation:
    downgraded: tuple[str, ...]
    variance_eligible: Mapping[str, bool]


@dataclass(frozen=True)
class GateResult:
    n_match: int
    n_total: int
    passed: bool


@dataclass(frozen=True)
class S0DComparison:
    n_match: int
    mismatched_fill_ids: tuple[str, ...]


def poisson_binomial_pmf(probs: Sequence[float]) -> tuple[float, ...]:
    raise NotImplementedError


def lower_tail(probs: Sequence[float], k: int) -> float:
    raise NotImplementedError


def station_day_probability(p_hats: Sequence[float]) -> float:
    raise NotImplementedError


def cluster_station_days(
    station_days: Iterable[tuple[str, dt.date]],
) -> tuple[StationEventCluster, ...]:
    raise NotImplementedError


def cluster_probability(day_probs: Sequence[float]) -> float:
    raise NotImplementedError


def format_p_value(p: float) -> str:
    raise NotImplementedError


def t_win(cluster_probs: Sequence[float], w_obs: int, *, alpha: float = 0.02) -> WinTestResult:
    raise NotImplementedError


def t_win_leave_one_out(clusters: Sequence[ClusterOutcome], *, alpha: float = 0.02) -> LeaveOneOut:
    raise NotImplementedError


def h0k_cluster_probs(day_probs_by_cluster: Sequence[Sequence[float]]) -> tuple[float, ...]:
    raise NotImplementedError


def edge_distance(instrument_id: str, tmax_f: int) -> int:
    raise NotImplementedError


def pit_midpoint(pmf: Mapping[int, float], tmax_f: int) -> float:
    raise NotImplementedError


def is_boundary(edge_dist: int, pit: float) -> bool:
    raise NotImplementedError


def is_tail(pit: float) -> bool:
    raise NotImplementedError


def primary_class_names() -> tuple[str, ...]:
    raise NotImplementedError


def verdict_labels() -> tuple[str, ...]:
    raise NotImplementedError


def classify_fills(fills: Sequence[FillFacts]) -> dict[str, str]:
    raise NotImplementedError


def station_day_k7_count(fills: Sequence[FillFacts]) -> int:
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
    alpha: float = 0.02,
) -> PowerResult:
    raise NotImplementedError


def t_spread_power(cluster_qs: Sequence[float], *, alpha: float = 0.02) -> float:
    raise NotImplementedError


def holm_plan(min_ps: Mapping[str, float], *, alpha: float = 0.02) -> HolmPlan:
    raise NotImplementedError


def is_material_k1a(delta_p: float, flips_decision: bool) -> bool:
    raise NotImplementedError


def decide_verdict(inputs: VerdictInputs) -> Verdict:
    raise NotImplementedError


def apply_downgrade(
    cluster_level: Mapping[str, bool],
    station_day_level: Mapping[str, bool],
    six_cluster_sensitivity: Mapping[str, bool],
) -> DowngradeResult:
    raise NotImplementedError


def render_footer(n_station_days: int, n_clusters: int) -> str:
    raise NotImplementedError


def report_phrase(outcome: HypothesisOutcome) -> str:
    raise NotImplementedError


def reevaluate_after_ties(
    before: Mapping[str, Status], after: Mapping[str, Status]
) -> TieReevaluation:
    raise NotImplementedError


def k1b_flags(
    fill_keys: Sequence[tuple[str, str, dt.date]], terminal_climate_day: dt.date
) -> K1bResult:
    raise NotImplementedError


def s0d_compare(
    logged: Mapping[str, float], reproduced: Mapping[str, float | None], *, tol: float = 1e-9
) -> S0DComparison:
    raise NotImplementedError


def classify_s0d_miss(
    *,
    bulletin_available: bool,
    bulletin_reissued: bool,
    cycle_selection_matches: bool,
    delta_survives_root_cause: bool,
) -> str:
    raise NotImplementedError


def reproduction_gate(per_fill_match: Sequence[bool | None], *, minimum: int = 23) -> GateResult:
    raise NotImplementedError


def holdout_violations(source: str, allowed_modules: Sequence[str]) -> tuple[str, ...]:
    raise NotImplementedError
