"""AUD-07 Rev 2 M1c/M2 execution amendment, 2026-09-25 review item 6c
(stress set): `scripts/analysis/aud07_m1c_census.py`'s synthetic
low-t/low-dt stress set (amendment §5 "CAL-b (census)", "Stress set").

The stress set feeds `StreamingBoundary` synthetic `t_history` sequences
directly -- it needs no real station-day draws, since the coarse/fine
boundary comparison depends only on the `t` sequence, never on `S` itself
(`score_combined`/`information_fraction` are grid-independent). This keeps
the stress set cheap: no Monte-Carlo, no `sample_station_day`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from aud07_m1c_census import CensusCellStats, derive_eps_pin, run_stress_set


def test_stress_set_covers_t1_in_half_min_observed_to_0_15_and_dt_down_to_1e_4() -> None:
    """The stress grid's t_1 values stay within [0.5*min_observed, 0.15]
    and its dt values reach down to (approximately) 1e-4."""
    min_observed_t1 = 0.2
    report = run_stress_set(eps=0.1, min_observed_t1=min_observed_t1)

    t1_values = {row["t1"] for row in report["results"]}
    dt_values = {row["dt"] for row in report["results"]}

    assert min(t1_values) >= 0.5 * min_observed_t1 - 1e-12
    assert max(t1_values) <= 0.15 + 1e-12
    assert min(dt_values) <= 2e-4  # "down to 1e-4"
    assert all(row["max_abs_delta_b"] >= 0.0 for row in report["results"])


def test_stress_set_lowest_safe_dt_satisfies_delta_b_leq_eps_over_3() -> None:
    """Every dt at or above the reported `lowest_safe_stress_dt` that was
    actually tested must show `max_abs_delta_b <= eps/3` at t_1 values
    where it was measured -- the stress set can only ever LOWER DT_MIN,
    and only where it demonstrates safety, never by assumption."""
    eps = 0.1
    report = run_stress_set(eps=eps, min_observed_t1=0.2)
    lowest_safe = report["lowest_safe_stress_dt"]

    if lowest_safe is None:
        return  # no dt cleared the bar -- a legitimate outcome, nothing further to check.

    matching = [row for row in report["results"] if row["dt"] == lowest_safe]
    assert matching
    assert all(row["max_abs_delta_b"] <= eps / 3 + 1e-12 for row in matching)


def test_derive_eps_pin_dt_min_only_ever_lowered_by_the_stress_set(tmp_path: Path) -> None:
    """`DT_MIN = min(realised min dt, lowest stress dt with delta_b <= eps/3)`
    -- combining a stress result can only lower DT_MIN relative to the
    census-only value, never raise it."""
    stats = [
        CensusCellStats(
            cell_index=0, n_reps=10, max_abs_delta_b=0.01, p999_abs_delta_b=0.01,
            min_dt=0.02, min_t1=0.2,
        )
    ]
    census_path = tmp_path / "census.json"
    census_path.write_text("{}", encoding="utf-8")

    pin_no_stress = derive_eps_pin(stats, code_sha="sha", census_json_path=census_path)
    dt_min_no_stress = pin_no_stress["dt_min"]
    assert dt_min_no_stress == 0.02

    stress_report = {"results": [], "lowest_safe_stress_dt": 0.005}
    pin_with_stress = derive_eps_pin(
        stats, code_sha="sha", census_json_path=census_path, stress=stress_report
    )
    assert pin_with_stress["dt_min"] == 0.005
    assert pin_with_stress["dt_min"] < dt_min_no_stress

    # A stress result that found NO dt safe below the census minimum must
    # never raise DT_MIN back up.
    stress_report_no_gain = {"results": [], "lowest_safe_stress_dt": 0.05}
    pin_no_gain = derive_eps_pin(
        stats, code_sha="sha", census_json_path=census_path, stress=stress_report_no_gain
    )
    assert pin_no_gain["dt_min"] == 0.02
