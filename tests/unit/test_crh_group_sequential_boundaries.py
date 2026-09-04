"""RED-first tests for `scripts/analysis/crh_group_sequential_boundaries.py`.

References for the K=2 sanity check: Jennison & Turnbull (2000), *Group
Sequential Methods with Applications to Clinical Trials*, Table 2.3 /
Lan & DeMets (1983) O'Brien-Fleming-type alpha-spending approximation,
one-sided alpha=0.025, K=2 equally spaced looks: boundaries approximately
(2.963, 1.969) (as cited in the task brief). Tolerance is generous (0.3)
because this is an *approximation family* ("approximately", per the source)
and this repo's recursion uses a finite numerical grid, not the reference
implementation's own quadrature.
"""

from __future__ import annotations

import sys
from itertools import pairwise
from pathlib import Path

import numpy as np
import pytest

_SCRIPTS_ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

import crh_group_sequential_boundaries as gs


def test_one_sided_spend_hits_alpha_exactly_at_t_equals_one():
    assert gs.one_sided_spend(1.0, 0.025) == pytest.approx(0.025, abs=1e-12)


def test_one_sided_spend_is_zero_at_t_equals_zero():
    assert gs.one_sided_spend(0.0, 0.025) == 0.0


def test_i_max_pinned_to_n_max_over_four():
    assert gs.i_max_for(160) == pytest.approx(40.0)
    assert gs.i_max_for(80) == pytest.approx(20.0)


def test_reference_table_has_sixteen_rows_for_default_schedule():
    rows = gs.build_reference_table(0.025, 160, 10, gs.i_max_for(160))
    assert len(rows) == 16
    assert [r.n_k for r in rows] == list(range(10, 161, 10))
    assert rows[0].t_k == pytest.approx(1 / 16)
    assert rows[-1].t_k == pytest.approx(1.0)


def test_efficacy_boundary_is_monotonically_decreasing():
    rows = gs.build_reference_table(0.025, 160, 10, gs.i_max_for(160))
    b_eff = [r.b_eff for r in rows]
    assert all(a > b for a, b in pairwise(b_eff))


def test_futility_boundary_mirrors_efficacy_by_symmetry():
    rows = gs.build_reference_table(0.025, 160, 10, gs.i_max_for(160))
    for r in rows:
        assert r.b_fut == pytest.approx(-r.b_eff, rel=5e-3, abs=0.02)


def test_terminal_look_spends_exactly_the_remaining_alpha_for_default_schedule():
    """Binding ruling (commit ca94177, PREREG v2 SS4 coordinator clarification):
    the terminal look spends EXACTLY the remaining alpha, so cumulative alpha
    at the terminal look is 0.025 to 1e-6 -- never forced to z_half."""
    rows = gs.build_reference_table(0.025, 160, 10, gs.i_max_for(160))
    assert rows[-1].alpha_spent_eff == pytest.approx(0.025, abs=1e-6)
    assert rows[-1].alpha_spent_fut == pytest.approx(0.025, abs=1e-6)


def test_terminal_boundary_lands_strictly_above_nominal_z_for_k16():
    """ "The terminal boundary is whatever the Lan-DeMets recursion yields from
    that remainder ... slightly above z" for K=16 equal looks (ruling text);
    it equals z_half only in the single-look limit (K=1)."""
    rows = gs.build_reference_table(0.025, 160, 10, gs.i_max_for(160))
    assert rows[-1].b_eff > gs.Z_ALPHA_ONE_SIDED
    assert rows[-1].b_fut < -gs.Z_ALPHA_ONE_SIDED


def test_single_look_terminal_boundary_equals_nominal_z():
    """Single-look limit (K=1, n_max == look_step): the terminal boundary
    reduces to the unconditional fixed-sample z_half, per the ruling.
    Tolerance is the numerical grid's own discretization error (GRID_NPTS
    trapezoid/interp grid, not floating-point precision) -- an order of
    magnitude tighter than the ~0.04 the K=16 terminal boundary sits above
    z_half, pinning that the single-look case is materially exact while
    K=16 is materially not."""
    rows = gs.build_reference_table(0.025, 10, 10, gs.i_max_for(10))
    assert len(rows) == 1
    assert rows[0].b_eff == pytest.approx(gs.Z_ALPHA_ONE_SIDED, abs=1e-4)
    assert rows[0].b_fut == pytest.approx(-gs.Z_ALPHA_ONE_SIDED, abs=1e-4)


def test_truncation_also_spends_exactly_the_remaining_alpha_at_t_trunc():
    """Truncation is a terminal look too (blueprint diff in ca94177: "terminal_look
    on remaining alpha ... at t_trunc"), so cumulative alpha at t_trunc is 0.025
    to 1e-6, exactly like the natural end-of-schedule terminal look."""
    rows = gs.build_reference_table(0.025, 160, 10, gs.i_max_for(160), truncate_at=60)
    assert len(rows) == 6
    assert rows[-1].n_k == 60
    assert rows[-1].alpha_spent_eff == pytest.approx(0.025, abs=1e-6)
    assert rows[-1].alpha_spent_fut == pytest.approx(0.025, abs=1e-6)


def test_boundary_for_accepts_a_tie_in_information_fraction_as_zero_increment():
    """Spec 'Tie guard (convergence edit)': I_k is a sum of non-negative
    terms so t can never decrease; a tie (t_k == t_{k-1}) is a valid look
    with a zero spending increment and a degenerate CONTINUE-forced
    boundary (nothing crosses); only a strict decrease is a wiring defect."""
    b_eff, b_fut = gs.boundary_for([0.5, 0.5], 0.025, is_terminal=False)
    assert b_eff == pytest.approx(float("inf"))
    assert b_fut == pytest.approx(float("-inf"))

    with pytest.raises(ValueError):
        gs.boundary_for([0.5, 0.4], 0.025, is_terminal=False)


def test_boundary_for_on_equal_t_grid_reproduces_reference_table_to_1e_minus_6():
    rows = gs.build_reference_table(0.025, 160, 10, gs.i_max_for(160))
    history: list[float] = []
    for idx, row in enumerate(rows):
        history.append(row.t_k)
        is_terminal = idx == len(rows) - 1
        b_eff, b_fut = gs.boundary_for(history, 0.025, is_terminal=is_terminal)
        assert b_eff == pytest.approx(row.b_eff, abs=1e-6)
        assert b_fut == pytest.approx(row.b_fut, abs=1e-6)


def test_alpha_spent_is_monotonically_nondecreasing_and_near_alpha():
    """Terminal look now solves for exactly the remaining alpha (ruling,
    ca94177), so total spent is 0.025 to 1e-6 exactly, not merely close."""
    rows = gs.build_reference_table(0.025, 160, 10, gs.i_max_for(160))
    spent = [r.alpha_spent_eff for r in rows]
    assert all(a <= b + 1e-9 for a, b in pairwise(spent))
    assert spent[-1] == pytest.approx(0.025, abs=1e-6)


def test_k2_reference_matches_literature_approximately():
    rows = gs.build_reference_table(0.025, 2, 1, gs.i_max_for(2))
    assert rows[0].b_eff == pytest.approx(2.963, abs=0.3)
    assert rows[1].b_eff == pytest.approx(1.969, abs=0.3)


def test_n_max_must_be_multiple_of_look_step():
    with pytest.raises(ValueError):
        gs.build_reference_table(0.025, 155, 10, gs.i_max_for(155))


def test_truncation_evaluates_a_valid_test_at_the_actual_info_fraction():
    """Truncation (n_trunc < n_max) IS a terminal look under the binding
    ruling (ca94177): the boundary is solved (not forced) from the
    remaining-alpha increment at the ACTUAL observed t_trunc. Assertion
    updated 2026-09-04: the previous version asserted `alpha_spent_eff ~=
    one_sided_spend(t_trunc)`, which encoded the REJECTED "truncation is
    not terminal, spend only the natural spending-function increment"
    reading; the `b_eff > Z_ALPHA_ONE_SIDED` direction is unchanged and
    still holds -- OBF spends almost nothing by t_trunc=0.375, so the
    "remaining" target is barely less than 0.025, and the still barely
    truncated density (early OBF boundaries are very wide) is close enough
    to the single-look case that the solved boundary lands just above
    z_half, same sign as the K=16 natural terminal look -- see
    test_truncation_also_spends_exactly_the_remaining_alpha_at_t_trunc for
    the alpha-spend invariant this test used to (incorrectly) approximate."""
    rows = gs.build_reference_table(0.025, 160, 10, gs.i_max_for(160), truncate_at=60)
    assert len(rows) == 6
    assert rows[-1].n_k == 60
    assert rows[-1].b_eff > gs.Z_ALPHA_ONE_SIDED
    assert rows[-1].alpha_spent_eff == pytest.approx(0.025, abs=1e-6)


def test_inputs_manifest_sha256_is_deterministic_and_input_sensitive():
    m1 = gs.inputs_manifest(0.025, gs.SPENDING_FUNCTION_ID, 160, 40.0, 10)
    m2 = gs.inputs_manifest(0.025, gs.SPENDING_FUNCTION_ID, 160, 40.0, 10)
    assert gs.sha256_of_inputs(m1) == gs.sha256_of_inputs(m2)

    m3 = gs.inputs_manifest(0.025, gs.SPENDING_FUNCTION_ID, 161, 40.0, 10)
    assert gs.sha256_of_inputs(m1) != gs.sha256_of_inputs(m3)


def test_build_output_shape_and_reproducible_sha():
    out1 = gs.build_output(0.025, 160, 10)
    out2 = gs.build_output(0.025, 160, 10)
    assert out1["inputs_sha256"] == out2["inputs_sha256"]
    assert len(out1["reference_table"]) == 16
    assert out1["i_max"] == pytest.approx(40.0)
    row_keys = set(out1["reference_table"][0].keys())
    assert row_keys == {
        "look_k",
        "n_k",
        "t_k",
        "b_eff",
        "b_fut",
        "alpha_spent_eff",
        "alpha_spent_fut",
    }


def test_simulation_fixed_pi_type_i_within_mc_bound():
    """Bound is widened beyond the pure Monte-Carlo margin (alpha +
    3*MC-SE) to also absorb the finite numerical-grid recursion's tail
    imprecision (see module docstring); it still pins Type I close to the
    nominal 0.025, not an arbitrary pass."""
    rows = gs.build_reference_table(0.025, 160, 10, gs.i_max_for(160))
    n_reps = 20_000
    result = gs.simulate_fixed_pi(rows, pi=0.41, delta=0.15, n_reps=n_reps, seed=20260904)
    assert result["leak_p_eq_pi"]["p_efficacy"] <= 0.025 + 0.015
    assert 10 <= result["leak_p_eq_pi"]["asn"] <= 160
    assert result["edge_p_eq_pi_plus_delta"]["p_efficacy"] > result["leak_p_eq_pi"]["p_efficacy"]


def test_simulation_drift_score_statistic_type_i_within_mc_bound():
    """The strategy-lead-ruled valid statistic (S_k, centred score on
    realized information) must control Type I under the drifting-ask DGP;
    the rejected plug-in Z_k form is reported for contrast only, with no
    such guarantee asserted."""
    rows = gs.build_reference_table(0.025, 160, 10, gs.i_max_for(160))
    n_reps = 20_000
    result = gs.simulate_drift(
        rows,
        alpha=0.025,
        n_max=160,
        i_max=gs.i_max_for(160),
        delta=0.15,
        n_reps=n_reps,
        seed=20260904,
    )
    mc_se = np.sqrt(0.025 * 0.975 / n_reps)
    score_type_i = result["type_i_delta_0"]["score_S_k_valid"]["p_efficacy"]
    assert score_type_i <= 0.025 + 3 * mc_se
    score_power = result["power_delta"]["score_S_k_valid"]["p_efficacy"]
    assert score_power > score_type_i


def test_main_writes_json_and_prints_table(tmp_path, capsys):
    out_path = tmp_path / "gs_boundaries.json"
    rc = gs.main(
        [
            "--alpha",
            "0.025",
            "--n-max",
            "160",
            "--look-step",
            "10",
            "--pi",
            "0.41",
            "--delta",
            "0.15",
            "--out",
            str(out_path),
            "--sim-reps",
            "2000",
        ]
    )
    assert rc == 0
    assert out_path.exists()
    printed = capsys.readouterr().out
    assert "reference_table" in printed
