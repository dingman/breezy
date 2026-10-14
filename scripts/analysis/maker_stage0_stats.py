"""MAKER-S2 WP5: Stage 0 numerics (pure; no I/O, no truth).

Plan ``docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md`` WP5 (L173-190) + r4 delta
(a) fitted ICC, (f) lower median / IQR / bootstrap, (h) Test B. Spec v0.3 section 6.9
(``docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md`` :290-304) defines both exact tests.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, NamedTuple

import numpy as np
from scipy import stats as sps

from breezy.analysis.stats.scoring_core import (
    CLUSTER_DATE,
    SupportsClusterKey,
    bootstrap_cluster_draws,
    percentile_interval,
)

AS_MARGIN: Final[float] = 1.5  # spec :296 ``as_margin``
ALPHA: Final[float] = 0.05
MIN_EXPECTED_LOSSES: Final[float] = 10.0  # spec :298
MIN_CLUSTERS: Final[int] = 5  # fewer climate dates: "not estimable"
POWER_KS: Final[tuple[float, ...]] = (1.5, 2.0, 3.0)
ONE_SIDED_ALPHA: Final[float] = 0.10  # percentile_interval alpha whose upper end is the 95th
TAIL_EDGES: Final[tuple[float, ...]] = (0.0, 0.02, 0.04, 0.06)
TAIL_LABELS: Final[tuple[str, ...]] = ("[0,.02)", "[.02,.04)", "[.04,.06)")
STATE_PASS: Final[str] = "PASS"
STATE_FAIL: Final[str] = "FAIL"
STATE_UNSCREENED: Final[str] = "UNSCREENED"
STRATUM_LABELS: Final[tuple[str, ...]] = ("[0.94,0.96)", "[0.96,0.98)", "[0.98,1]", "<0.94")
_STRATUM_EDGES: Final[tuple[tuple[float, str], ...]] = (
    (0.98, "[0.98,1]"),
    (0.96, "[0.96,0.98)"),
    (0.94, "[0.94,0.96)"),
)
_DENOM_EPS: Final[float] = 1e-12

# --- exact tests ------------------------------------------------------------------------------


def _pmf(qs: Sequence[float]) -> list[float]:
    pmf = [1.0]
    for q in qs:
        nxt = [0.0] * (len(pmf) + 1)
        for count, mass in enumerate(pmf):
            nxt[count] += mass * (1.0 - q)
            nxt[count + 1] += mass * q
        pmf = nxt
    return pmf


def poisson_binomial_upper_tail(qs: Sequence[float], lo: int) -> float:
    """Exact ``P(L >= lo)`` for independent Bernoulli(q_i)."""
    return math.fsum(_pmf(qs)[max(lo, 0) :])


def _margin(ps: Sequence[float], k: float) -> list[float]:
    return [min(1.0, k * p) for p in ps]


def exact_test_a(ps: Sequence[float], losses: int) -> float:
    """Test A: ``P(L >= l_obs)`` under independent ``Bernoulli(min(1, 1.5 p_i))`` (spec :296)."""
    return poisson_binomial_upper_tail(_margin(ps, AS_MARGIN), losses)


def rate_ratio_pi0(n_f: int, n_u: int) -> float:
    """``pi0 = 1.5 n_f / (1.5 n_f + n_u)``: the filled share of losses under H0."""
    if n_f + n_u <= 0:
        raise ValueError("rate ratio needs at least one row")
    return AS_MARGIN * n_f / (AS_MARGIN * n_f + n_u)


def rate_ratio_test_b(n_f: int, n_u: int, l_f: int, l_u: int) -> float:
    """Test B: Poisson-conditional rate-ratio test (approximation, valid at p <= 0.06).

    Given ``L = L_f + L_u``, ``L_f ~ Bin(L, pi0)``, one-sided exact; ``L = 0`` cannot fail.
    """
    if l_f + l_u == 0 or n_f == 0:
        return 1.0
    pi0 = rate_ratio_pi0(n_f, n_u)
    return float(sps.binomtest(l_f, l_f + l_u, pi0, alternative="greater").pvalue)


@dataclass(frozen=True)
class PowerRow:
    k: float
    power: float


@dataclass(frozen=True)
class PowerLine:
    """Analytic ``P(Test A FAIL | k)`` at the exact critical count (no simulation)."""

    critical_count: int | None
    rows: tuple[PowerRow, ...]
    fills_needed_for_ten_expected_losses: int | None


def power_line(ps: Sequence[float]) -> PowerLine:
    pmf = _pmf(_margin(ps, AS_MARGIN))
    crit = next((lo for lo in range(1, len(pmf)) if math.fsum(pmf[lo:]) < ALPHA), None)
    rows = tuple(
        PowerRow(k, 0.0 if crit is None else poisson_binomial_upper_tail(_margin(ps, k), crit))
        for k in POWER_KS
    )
    mean_p = math.fsum(ps) / len(ps) if ps else 0.0
    needed = math.ceil(round(MIN_EXPECTED_LOSSES / mean_p, 9)) if mean_p > 0 else None
    return PowerLine(crit, rows, needed)


# --- pooled section 6.9 screen ----------------------------------------------------------------


class ScreenRow(NamedTuple):
    """One scored section 6.9 row: model p_YES, whether YES settled, filled or not."""

    p_yes: float
    loss: bool
    filled: bool
    climate_day: str


@dataclass(frozen=True)
class Stratum:
    label: str
    n_f: int
    n_u: int
    l_f: int
    l_u: int
    expected: float
    p_a: float
    p_b: float


@dataclass(frozen=True)
class Screen:
    n_filled: int
    n_unfilled: int
    expected_losses: float
    losses_filled: int
    losses_unfilled: int
    p_a: float
    p_b: float
    state: str
    clusters_a: int
    clusters_b: int
    power: PowerLine
    strata: tuple[Stratum, ...]  # descriptive only: a stratum never sets the state
    mix_adjusted_ratio: float | None


def stratum_label(p_yes: float) -> str:
    p_no = round(1.0 - p_yes, 9)
    return next((label for edge, label in _STRATUM_EDGES if p_no >= edge), STRATUM_LABELS[-1])


def _stratum(label: str, rows: Sequence[ScreenRow]) -> Stratum:
    ps = [r.p_yes for r in rows if r.filled]
    n_u = len(rows) - len(ps)
    l_f = sum(r.loss for r in rows if r.filled)
    l_u = sum(r.loss for r in rows if not r.filled)
    return Stratum(
        label, len(ps), n_u, l_f, l_u, math.fsum(ps),
        exact_test_a(ps, l_f), rate_ratio_test_b(len(ps), n_u, l_f, l_u),
    )  # fmt: skip


def _mix_ratio(strata: Sequence[Stratum]) -> float | None:
    """Filled losses over the losses the unfilled strata rates imply for the filled mix."""
    both = [s for s in strata if s.n_f and s.n_u]
    implied = math.fsum(s.n_f * s.l_u / s.n_u for s in both)
    return math.fsum(s.l_f for s in both) / implied if implied > 0 else None


def pooled_screen(rows: Sequence[ScreenRow]) -> Screen:
    """Spec :290-304: pooled Tests A and B; ``UNSCREENED`` below 10 expected losses."""
    pooled = _stratum("pooled", rows)
    if pooled.expected < MIN_EXPECTED_LOSSES:
        state = STATE_UNSCREENED
    else:
        state = STATE_FAIL if min(pooled.p_a, pooled.p_b) < ALPHA else STATE_PASS
    strata = tuple(
        _stratum(label, [r for r in rows if stratum_label(r.p_yes) == label])
        for label in STRATUM_LABELS
    )
    filled = [r for r in rows if r.filled]
    return Screen(
        pooled.n_f, pooled.n_u, pooled.expected, pooled.l_f, pooled.l_u, pooled.p_a, pooled.p_b,
        state, len({r.climate_day for r in filled}), len({r.climate_day for r in rows}),
        power_line([r.p_yes for r in filled]), strata, _mix_ratio(strata),
    )  # fmt: skip


# --- intervals --------------------------------------------------------------------------------


def _proportion_ci(k: int, n: int, method: str) -> tuple[float, float] | None:
    if n <= 0:
        return None
    ci = sps.binomtest(k, n).proportion_ci(confidence_level=1 - ALPHA, method=method)
    return float(ci.low), float(ci.high)


def wilson_interval(k: int, n: int) -> tuple[float, float] | None:
    return _proportion_ci(k, n, "wilson")


def clopper_pearson(k: int, n: int) -> tuple[float, float] | None:
    return _proportion_ci(k, n, "exact")


@dataclass(frozen=True)
class BootInterval:
    """Climate-date cluster-bootstrap 95% two-sided percentile interval (seed 20260919 x 2000)."""

    n_clusters: int
    low: float
    high: float
    se: float


def n_clusters[C: SupportsClusterKey](items: Sequence[C]) -> int:
    return len({repr(item.cluster_key(CLUSTER_DATE)) for item in items})


def cluster_interval[C: SupportsClusterKey](
    items: Sequence[C], statistic: Callable[[Sequence[C]], float]
) -> BootInterval | None:
    """None ("not estimable") with fewer than five climate-date clusters."""
    count = n_clusters(items)
    if count < MIN_CLUSTERS:
        return None
    draws = bootstrap_cluster_draws(items, statistic=statistic, cluster=CLUSTER_DATE)
    low, high = percentile_interval(draws)
    return BootInterval(count, low, high, statistics.stdev(draws))


def cluster_upper_bound[C: SupportsClusterKey](
    items: Sequence[C], statistic: Callable[[Sequence[C]], float]
) -> float | None:
    """One-sided 95% upper bound: the 95th percentile of the same seeded draws."""
    if n_clusters(items) < MIN_CLUSTERS:
        return None
    draws = bootstrap_cluster_draws(items, statistic=statistic, cluster=CLUSTER_DATE)
    return percentile_interval(draws, alpha=ONE_SIDED_ALPHA)[1]


# --- fitted ANOVA ICC (report-only; r4 delta (a)) ---------------------------------------------


@dataclass(frozen=True)
class IccFit:
    n_sd: int
    n0: int
    msb: float | None
    msw: float | None
    m0: float | None
    rho: float | None  # None = "undefined": never a substitute value
    deff_hat: float | None
    n_eff_hat: float | None


def anova_icc(groups: Mapping[str, Sequence[float]]) -> IccFit:
    """One-way ANOVA ICC over climate-date clusters, truncated to [0, 1].

    Undefined when n0 < 2, n_sd = n0 (MSW has 0 df), or ``MSB + (m0 - 1) MSW`` is 0.
    """
    kept = {key: values for key, values in groups.items() if values}
    n0, n_sd = len(kept), sum(len(v) for v in kept.values())
    if n0 < 2 or n_sd == n0:
        return IccFit(n_sd, n0, None, None, None, None, None, None)
    grand = math.fsum(v for values in kept.values() for v in values) / n_sd
    means = {key: math.fsum(values) / len(values) for key, values in kept.items()}
    ssb = math.fsum(len(kept[key]) * (means[key] - grand) ** 2 for key in kept)
    ssw = math.fsum((v - means[key]) ** 2 for key in kept for v in kept[key])
    msb, msw = ssb / (n0 - 1), ssw / (n_sd - n0)
    m0 = (n_sd - math.fsum(len(v) ** 2 for v in kept.values()) / n_sd) / (n0 - 1)
    denom = msb + (m0 - 1.0) * msw
    if denom <= _DENOM_EPS:
        return IccFit(n_sd, n0, msb, msw, m0, None, None, None)
    rho = min(1.0, max(0.0, (msb - msw) / denom))
    n_eff = math.fsum(len(v) / (1.0 + (len(v) - 1) * rho) for v in kept.values())
    return IccFit(n_sd, n0, msb, msw, m0, rho, 1.0 + (m0 - 1.0) * rho, n_eff)


# --- bid statistics (r4 delta (f)) ------------------------------------------------------------


def lower_median(values: Sequence[float]) -> float | None:
    """Sorted index ``floor((n - 1) / 2)``: an on-tick value, never an interpolation."""
    return sorted(values)[(len(values) - 1) // 2] if values else None


def inverted_cdf_iqr(values: Sequence[float]) -> tuple[float, float] | None:
    if not values:
        return None
    q1, q3 = np.quantile(np.asarray(values, dtype=float), [0.25, 0.75], method="inverted_cdf")
    return float(q1), float(q3)


# --- tail reliability (report-only) -----------------------------------------------------------


@dataclass(frozen=True)
class TailRow:
    """One inclusive 2 F band probability for one day-D vector, with its realised outcome."""

    station: str
    climate_day: str
    vector: str
    p_yes: float
    outcome: int


@dataclass(frozen=True)
class TailBin:
    label: str
    n: int
    n_dates: int
    mean_p: float | None
    observed: float | None
    ci: tuple[float, float] | None


@dataclass(frozen=True)
class TailTable:
    bins: tuple[TailBin, ...]
    n: int
    expected: float
    observed: int
    p_value: float | None  # pooled two-sided exact: the doubled smaller tail, capped at 1
    miscalibrated: bool


def _tail_bin(label: str, rows: Sequence[TailRow]) -> TailBin:
    hits = sum(r.outcome for r in rows)
    mean_p = math.fsum(r.p_yes for r in rows) / len(rows) if rows else None
    observed = hits / len(rows) if rows else None
    return TailBin(
        label, len(rows), len({r.climate_day for r in rows}), mean_p, observed,
        clopper_pearson(hits, len(rows)),
    )  # fmt: skip


def tail_table(rows: Sequence[TailRow]) -> TailTable:
    """Bins ``[0,.02) [.02,.04) [.04,.06)`` (p_YES < 0.06 only) and the pooled exact test."""
    tail = [r for r in rows if 0.0 <= r.p_yes < TAIL_EDGES[-1]]
    edges = zip(TAIL_LABELS, TAIL_EDGES[:-1], TAIL_EDGES[1:], strict=True)
    bins = tuple(_tail_bin(lb, [r for r in tail if lo <= r.p_yes < hi]) for lb, lo, hi in edges)
    observed, expected = sum(r.outcome for r in tail), math.fsum(r.p_yes for r in tail)
    if not tail:
        return TailTable(bins, 0, expected, observed, None, False)
    pmf = _pmf([r.p_yes for r in tail])
    upper, lower = math.fsum(pmf[observed:]), math.fsum(pmf[: observed + 1])
    p_value = min(1.0, 2.0 * min(upper, lower))
    return TailTable(bins, len(tail), expected, observed, p_value, p_value < ALPHA)
