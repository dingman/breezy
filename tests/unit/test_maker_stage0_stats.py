"""MAKER-S2 WP5 RED tests: the pure Stage 0 numerics (hand-computed fixtures only).

Plan: docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r3.md WP5 (L173-190) and the r4
delta (a) fitted ANOVA ICC, (f) lower median / IQR, (h) Test B, (i)5 intervals.
Spec: docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md section 6.9 (:290-304).
"""

from __future__ import annotations

import ast
import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.analysis import maker_stage0_stats as st

ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "scripts/analysis"


@dataclass(frozen=True)
class Item:
    cluster: str
    value: float

    def cluster_key(self, cluster: str) -> object:
        return self.cluster


def _brute_upper_tail(qs: list[float], lo: int) -> float:
    total = 0.0
    for flags in itertools.product((0, 1), repeat=len(qs)):
        if sum(flags) < lo:
            continue
        weight = 1.0
        for q, flag in zip(qs, flags, strict=True):
            weight *= q if flag else 1.0 - q
        total += weight
    return total


def test_poisson_binomial_tail_matches_brute_force() -> None:
    qs = [0.1, 0.2, 0.3, 0.05, 0.4]
    for lo in range(len(qs) + 2):
        assert st.poisson_binomial_upper_tail(qs, lo) == pytest.approx(
            _brute_upper_tail(qs, lo), abs=1e-12
        )


def test_test_a_uses_1_5_margin_and_caps_at_one() -> None:
    # q = 1.5 p = [0.3, 0.6]: P(L >= 2) = 0.18 ; P(L >= 1) = 1 - 0.7 * 0.4 = 0.72
    assert st.exact_test_a([0.2, 0.4], 2) == pytest.approx(0.18)
    assert st.exact_test_a([0.2, 0.4], 1) == pytest.approx(0.72)
    assert st.exact_test_a([0.8], 1) == pytest.approx(1.0)  # min(1, 1.5 * 0.8) = 1


def test_rate_ratio_test_uses_1_5_margin() -> None:
    # n_f = 10, n_u = 30 -> pi0 = 15 / 45 = 1/3 ; L_f = 3, L_u = 1 -> P(Bin(4, 1/3) >= 3) = 1/9
    assert st.rate_ratio_pi0(10, 30) == pytest.approx(1 / 3)
    assert st.rate_ratio_test_b(10, 30, 3, 1) == pytest.approx(1 / 9)
    assert st.rate_ratio_pi0(20, 20) == pytest.approx(0.6)  # 1.5 margin, not 0.5


def test_rate_ratio_with_no_losses_cannot_fail() -> None:
    assert st.rate_ratio_test_b(10, 30, 0, 0) == 1.0
    assert st.rate_ratio_test_b(0, 30, 0, 2) == 1.0  # no filled rows: nothing to test


def test_power_line_is_monotone_in_k() -> None:
    line = st.power_line([0.05] * 40)
    powers = [row.power for row in line.rows]
    assert [row.k for row in line.rows] == [1.5, 2.0, 3.0]
    assert powers == sorted(powers)
    assert powers[0] < 0.05  # at k = 1.5 the critical count is an alpha-level test
    assert powers[-1] > powers[0]
    assert line.critical_count is not None
    assert line.fills_needed_for_ten_expected_losses == 200  # ceil(10 / 0.05)


def test_power_line_without_a_reachable_critical_count_is_zero() -> None:
    line = st.power_line([0.5])
    assert line.critical_count is None
    assert [row.power for row in line.rows] == [0.0, 0.0, 0.0]


def test_fitted_icc_matches_hand_anova() -> None:
    # a=[1,1] b=[0,0] c=[1,0]: N=6 k=3 ybar=.5 SSB=1.0 SSW=.5 MSB=.5 MSW=1/6 m0=2 rho=.5
    fit = st.anova_icc({"a": [1.0, 1.0], "b": [0.0, 0.0], "c": [1.0, 0.0]})
    assert fit.rho == pytest.approx(0.5)
    assert fit.msb == pytest.approx(0.5)
    assert fit.msw == pytest.approx(1 / 6)
    assert fit.m0 == pytest.approx(2.0)
    assert fit.deff_hat == pytest.approx(1.5)
    assert fit.n_eff_hat == pytest.approx(4.0)  # 3 * 2 / 1.5


def test_fitted_icc_is_undefined_when_n_sd_equals_n0_or_degenerate() -> None:
    assert st.anova_icc({"a": [1.0], "b": [0.0], "c": [1.0]}).rho is None  # n_sd == n0
    assert st.anova_icc({"a": [1.0, 0.0]}).rho is None  # n0 < 2
    assert st.anova_icc({"a": [0.0, 0.0], "b": [0.0, 0.0]}).rho is None  # no fills
    assert st.anova_icc({"a": [1.0, 1.0], "b": [1.0, 1.0]}).rho is None  # all fills
    undefined = st.anova_icc({"a": [1.0], "b": [0.0]})
    assert undefined.deff_hat is None
    assert undefined.n_eff_hat is None


def test_fitted_icc_is_truncated_to_the_unit_interval() -> None:
    negative = st.anova_icc({"a": [1.0, 0.0], "b": [1.0, 0.0], "c": [1.0, 0.0]})
    assert negative.rho == 0.0
    perfect = st.anova_icc({"a": [1.0, 1.0], "b": [0.0, 0.0]})
    assert perfect.rho == 1.0


def test_wilson_and_clopper_pearson_known_values() -> None:
    low, high = st.wilson_interval(0, 10) or (None, None)
    assert low == pytest.approx(0.0, abs=1e-12)
    assert high == pytest.approx(0.27753, abs=1e-4)
    cp_low, cp_high = st.clopper_pearson(0, 10) or (None, None)
    assert cp_low == 0.0
    assert cp_high == pytest.approx(1 - 0.025 ** (1 / 10), abs=1e-9)
    assert st.wilson_interval(0, 0) is None


def test_lower_median_and_inverted_cdf_iqr() -> None:
    bids = [0.76, 0.70, 0.74, 0.72]
    assert st.lower_median(bids) == 0.72  # sorted index floor((4 - 1) / 2) = 1
    assert st.lower_median([0.71, 0.73, 0.75]) == 0.73
    assert st.lower_median([]) is None
    assert st.inverted_cdf_iqr(bids) == (0.70, 0.74)
    assert st.inverted_cdf_iqr([]) is None


def test_fewer_than_five_clusters_prints_not_estimable_and_null_key() -> None:
    items = [Item(f"d{i}", 1.0) for i in range(4) for _ in range(3)]
    assert st.cluster_interval(items, lambda rows: len(rows) / 12.0) is None
    five = [Item(f"d{i}", float(i)) for i in range(5)]
    interval = st.cluster_interval(five, lambda rows: sum(r.value for r in rows) / len(rows))
    assert interval is not None
    assert interval.n_clusters == 5
    assert interval.low <= interval.high


def test_seeded_cluster_bootstrap_is_reproducible() -> None:
    items = [Item(f"d{i % 7}", float(i % 3)) for i in range(40)]

    def mean(rows: Sequence[Item]) -> float:
        return sum(r.value for r in rows) / len(rows)

    first = st.cluster_interval(items, mean)
    second = st.cluster_interval(items, mean)
    assert first is not None
    assert first == second
    assert first.se > 0.0


def test_one_sided_upper_bound_is_the_95th_percentile() -> None:
    items = [Item(f"d{i}", float(i)) for i in range(10)]

    def mean(rows: Sequence[Item]) -> float:
        return sum(r.value for r in rows) / len(rows)

    two_sided = st.cluster_interval(items, mean)
    upper = st.cluster_upper_bound(items, mean)
    assert two_sided is not None
    assert upper is not None
    assert upper <= two_sided.high  # 95th <= 97.5th percentile


def test_tail_table_bins_and_pooled_exact_test() -> None:
    rows = [
        st.TailRow("LAX", "2026-07-01", "v0", 0.01, 0),
        st.TailRow("LAX", "2026-07-02", "v0", 0.03, 0),
        st.TailRow("MDW", "2026-07-02", "v0", 0.05, 1),
        st.TailRow("MDW", "2026-07-03", "v1", 0.07, 1),  # above 0.06: not a tail row
    ]
    table = st.tail_table(rows)
    assert [b.label for b in table.bins] == ["[0,.02)", "[.02,.04)", "[.04,.06)"]
    assert [b.n for b in table.bins] == [1, 1, 1]
    assert table.bins[2].observed == 1.0
    assert table.bins[2].mean_p == pytest.approx(0.05)
    assert table.n == 3
    assert table.expected == pytest.approx(0.09)
    assert table.observed == 1
    # two-sided exact: upper tail P(L >= 1) = 1 - .99*.97*.95 ; doubled and capped at 1
    upper = 1 - 0.99 * 0.97 * 0.95
    assert table.p_value == pytest.approx(min(1.0, 2 * upper))
    assert table.miscalibrated is False


def test_tail_table_flags_miscalibration() -> None:
    rows = [st.TailRow("LAX", f"2026-07-{d:02d}", "v0", 0.01, 1) for d in range(1, 11)]
    table = st.tail_table(rows)
    assert table.p_value is not None
    assert table.p_value < 0.05
    assert table.miscalibrated is True
    assert table.bins[0].observed is not None
    assert math.isclose(table.bins[0].observed, 1.0)


def test_stats_module_imports_no_truth_loader() -> None:
    tree = ast.parse((ANALYSIS_DIR / "maker_stage0_stats.py").read_text())
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "load_truth" not in imported
    assert "TruthTable" not in imported


# --- review fixes: hand values and edge cases --------------------------------------------------


def test_power_line_hand_computed_critical_count_and_power() -> None:
    # three fills at p = .1: margin q = .15 -> P(L >= 3) = .15^3 = .003375 < .05 but
    # P(L >= 2) = 3 * .15^2 * .85 + .003375 = .06075 >= .05, so the critical count is 3.
    # Power at k: q = k * .1 -> P(L = 3) = q^3: .003375 (k=1.5), .008 (k=2), .027 (k=3).
    line = st.power_line([0.1, 0.1, 0.1])
    assert line.critical_count == 3
    assert [row.power for row in line.rows] == pytest.approx([0.003375, 0.008, 0.027])
    assert line.fills_needed_for_ten_expected_losses == 100


def test_single_value_median_and_iqr() -> None:
    assert st.lower_median([0.7]) == 0.7
    assert st.inverted_cdf_iqr([0.7]) == (0.7, 0.7)


def test_anova_icc_with_nan_input_is_undefined_never_zero() -> None:
    fit = st.anova_icc({"a": [1.0, math.nan], "b": [0.0, 1.0], "c": [1.0, 0.0]})
    assert fit.rho is None and fit.n_eff_hat is None and fit.deff_hat is None
    assert fit.msb is None and fit.msw is None


def test_anova_icc_with_no_groups_or_only_empty_groups_is_undefined() -> None:
    assert st.anova_icc({}).rho is None
    assert st.anova_icc({"a": [], "b": []}).n0 == 0


def test_rate_ratio_test_b_refuses_more_losses_than_rows() -> None:
    with pytest.raises(ValueError, match="losses"):
        st.rate_ratio_test_b(2, 5, 3, 0)
    with pytest.raises(ValueError, match="losses"):
        st.rate_ratio_test_b(5, 2, 0, 3)
