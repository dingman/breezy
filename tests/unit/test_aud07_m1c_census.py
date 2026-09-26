"""AUD-07 Rev 2 M1c/M2 execution amendment: `aud07_m1c_census.py`'s
chunkable, resumable CAL-b census (2026-09-25 fix -- the original
all-in-one invocation ran all 49 cells x 400 reps serially in one process,
about 15h wall time, fitting no plan §4.4 schedule segment and losing
everything to a `RuntimeMaxSec` kill).

Also covers the synthetic low-t/low-dt stress set (amendment §5 "CAL-b
(census)", "Stress set"), which feeds `StreamingBoundary` synthetic
`t_history` sequences directly -- no real station-day draws needed, since
the coarse/fine boundary comparison depends only on the `t` sequence,
never on `S` itself.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from aud07_live_rule_crossing_sim import (
    LOOK_STEP,
    M1C_GRID,
    N_DEPTHS,
    N_MAX,
    ResumeKeyConflictError,
    load_eps_pin,
)
from aud07_m1c_census import (
    STRESS_CELL_INDEX,
    CensusCellStats,
    derive_eps_pin,
    run_census_cell,
    run_census_chunk,
    run_derive_pin,
    run_stress_chunk,
    run_stress_set,
)
from aud07_m1c_merge import MergeCoverageError, MergeStageError


def test_stress_set_covers_t1_in_half_min_observed_to_0_15_and_dt_down_to_1e_4() -> None:
    """The stress grid's t_1 values stay within [0.5*min_observed, 0.15]
    and its dt values reach down to (approximately) 1e-4. `run_stress_set`
    is a pure measurement now: no `eps` dependency (review fix)."""
    min_observed_t1 = 0.2
    report = run_stress_set(min_observed_t1=min_observed_t1)

    t1_values = {row["t1"] for row in report["results"]}
    dt_values = {row["dt"] for row in report["results"]}

    assert min(t1_values) >= 0.5 * min_observed_t1 - 1e-12
    assert max(t1_values) <= 0.15 + 1e-12
    assert min(dt_values) <= 2e-4  # "down to 1e-4"
    assert all(row["max_abs_delta_b"] >= 0.0 for row in report["results"])


def test_derive_eps_pin_dt_min_only_ever_lowered_by_the_stress_set(tmp_path: Path) -> None:
    """`DT_MIN` is lowered (never raised) by any stress `result` whose
    `max_abs_delta_b <= eps/3` at the eps `derive_eps_pin` itself computes
    from the census -- the safety derivation moved INTO `derive_eps_pin`
    (review fix: `run_stress_set` no longer needs eps up front)."""
    stats = [
        CensusCellStats(
            cell_index=0, n_reps=10, max_abs_delta_b=0.01, p999_abs_delta_b=0.01,
            min_dt=0.02, min_t1=0.2,
        )
    ]
    # eps here = max(0.02, 3*0.01) = 0.03 -> eps/3 = 0.01.
    census_path = tmp_path / "census.json"
    census_path.write_text("{}", encoding="utf-8")

    pin_no_stress = derive_eps_pin(stats, code_sha="sha", census_json_path=census_path)
    assert pin_no_stress["dt_min"] == 0.02

    stress_with_gain = {"results": [{"t1": 0.1, "dt": 0.005, "max_abs_delta_b": 0.005}]}
    pin_with_gain = derive_eps_pin(
        stats, code_sha="sha", census_json_path=census_path, stress=stress_with_gain
    )
    assert pin_with_gain["dt_min"] == 0.005
    assert pin_with_gain["dt_min"] < pin_no_stress["dt_min"]

    # A stress result that never clears eps/3 must never raise DT_MIN.
    stress_no_gain = {"results": [{"t1": 0.1, "dt": 0.05, "max_abs_delta_b": 0.05}]}
    pin_no_gain = derive_eps_pin(
        stats, code_sha="sha", census_json_path=census_path, stress=stress_no_gain
    )
    assert pin_no_gain["dt_min"] == 0.02


# ---------------------------------------------------------------------------
# Chunked census + derive-pin (2026-09-25 fix)
# ---------------------------------------------------------------------------
_TINY_REPS = 1


def test_chunked_census_plus_derive_pin_equals_the_all_in_one_result(tmp_path: Path) -> None:
    """Chunked (one `run_census_chunk` call per cell, many files) must
    produce the SAME derived eps_pin/census as all-in-one (one wide
    `run_census_chunk` call covering all 49 cells in one file) -- proving
    chunking has no effect on the result. `_TINY_REPS` keeps this fast
    while covering the real, full 49-cell grid (never a shrunk grid --
    `run_derive_pin` requires exactly 49 cells)."""
    code_sha = "a" * 40
    n_cells = len(M1C_GRID)

    all_in_one_dir = tmp_path / "all_in_one"
    all_in_one_dir.mkdir()
    run_census_chunk(
        0, n_cells, out_path=all_in_one_dir / "cell_all.jsonl",
        reps_per_cell=_TINY_REPS, code_sha=code_sha,
    )
    run_stress_chunk(
        out_path=all_in_one_dir / "stress.jsonl", code_sha=code_sha, in_dir=all_in_one_dir
    )
    pin_all_in_one = run_derive_pin(
        in_dir=all_in_one_dir,
        out_census=all_in_one_dir / "census.json",
        out_pin=all_in_one_dir / "eps_pin.json",
    )

    chunked_dir = tmp_path / "chunked"
    chunked_dir.mkdir()
    for i in range(n_cells):
        run_census_chunk(
            i, i + 1, out_path=chunked_dir / f"cell_{i:02d}.jsonl",
            reps_per_cell=_TINY_REPS, code_sha=code_sha,
        )
    run_stress_chunk(
        out_path=chunked_dir / "stress.jsonl", code_sha=code_sha, in_dir=chunked_dir
    )
    pin_chunked = run_derive_pin(
        in_dir=chunked_dir,
        out_census=chunked_dir / "census.json",
        out_pin=chunked_dir / "eps_pin.json",
    )

    for field in ("eps", "dt_min", "census_max"):
        assert pin_all_in_one[field] == pin_chunked[field], field

    census_all_in_one = json.loads((all_in_one_dir / "census.json").read_text(encoding="utf-8"))
    census_chunked = json.loads((chunked_dir / "census.json").read_text(encoding="utf-8"))
    assert census_all_in_one["cells"] == census_chunked["cells"]


def test_resume_skips_done_cells(tmp_path: Path) -> None:
    out_path = tmp_path / "cell_00_01.jsonl"
    run_census_chunk(0, 2, out_path=out_path, reps_per_cell=_TINY_REPS, code_sha="a" * 40)
    rows_first = out_path.read_text(encoding="utf-8").splitlines()
    assert len(rows_first) == 2

    run_census_chunk(0, 2, out_path=out_path, reps_per_cell=_TINY_REPS, code_sha="a" * 40)
    rows_resumed = out_path.read_text(encoding="utf-8").splitlines()
    assert rows_resumed == rows_first  # no duplicates.

    with pytest.raises(ResumeKeyConflictError):
        run_census_chunk(0, 1, out_path=out_path, reps_per_cell=_TINY_REPS, code_sha="b" * 40)


def test_stress_chunk_resume_skips_when_already_done(tmp_path: Path) -> None:
    out_path = tmp_path / "stress.jsonl"
    run_stress_chunk(out_path=out_path, code_sha="a" * 40)
    first = out_path.read_text(encoding="utf-8")

    run_stress_chunk(out_path=out_path, code_sha="a" * 40)  # resumes: no duplicate row.
    assert out_path.read_text(encoding="utf-8") == first
    assert len(first.splitlines()) == 1

    with pytest.raises(ResumeKeyConflictError):
        run_stress_chunk(out_path=out_path, code_sha="b" * 40)


def test_derive_pin_refuses_missing_cells(tmp_path: Path) -> None:
    in_dir = tmp_path / "cal_b"
    in_dir.mkdir()
    code_sha = "a" * 40
    n_cells = len(M1C_GRID)
    # Only cells 0..(n_cells-2): cell n_cells-1 is missing.
    run_census_chunk(
        0, n_cells - 1, out_path=in_dir / "cell_all.jsonl",
        reps_per_cell=_TINY_REPS, code_sha=code_sha,
    )
    run_stress_chunk(out_path=in_dir / "stress.jsonl", code_sha=code_sha, in_dir=in_dir)

    with pytest.raises(MergeCoverageError, match="missing"):
        run_derive_pin(in_dir=in_dir, out_census=tmp_path / "c.json", out_pin=tmp_path / "p.json")


def test_derive_pin_refuses_mixed_code_shas(tmp_path: Path) -> None:
    in_dir = tmp_path / "cal_b"
    in_dir.mkdir()
    n_cells = len(M1C_GRID)
    run_census_chunk(
        0, n_cells - 1, out_path=in_dir / "cell_a.jsonl",
        reps_per_cell=_TINY_REPS, code_sha="a" * 40,
    )
    run_census_chunk(
        n_cells - 1, n_cells, out_path=in_dir / "cell_b.jsonl",
        reps_per_cell=_TINY_REPS, code_sha="b" * 40,
    )
    run_stress_chunk(out_path=in_dir / "stress.jsonl", code_sha="a" * 40, in_dir=in_dir)

    with pytest.raises(MergeStageError, match="code_sha"):
        run_derive_pin(in_dir=in_dir, out_census=tmp_path / "c.json", out_pin=tmp_path / "p.json")


def test_derive_pin_refuses_missing_stress_row(tmp_path: Path) -> None:
    in_dir = tmp_path / "cal_b"
    in_dir.mkdir()
    n_cells = len(M1C_GRID)
    run_census_chunk(
        0, n_cells, out_path=in_dir / "cell_all.jsonl",
        reps_per_cell=_TINY_REPS, code_sha="a" * 40,
    )
    # No stress row written at all.
    with pytest.raises(MergeCoverageError, match="stress"):
        run_derive_pin(in_dir=in_dir, out_census=tmp_path / "c.json", out_pin=tmp_path / "p.json")


def test_stress_row_identity_never_collides_with_a_real_cell() -> None:
    assert STRESS_CELL_INDEX < 0
    assert all(c != STRESS_CELL_INDEX for c in range(len(M1C_GRID)))


# ---------------------------------------------------------------------------
# AUD-07 M1c-eps_k (RULING PR-1, 2026-09-26): per-depth census + terminal
# bucket, and `derive_eps_pin`'s per-depth pin.
# ---------------------------------------------------------------------------


def test_run_census_cell_buckets_deltas_by_depth_and_a_terminal_bucket() -> None:
    """`run_census_cell` reports a length-`N_DEPTHS` per-depth table
    (`None` where a rep's first terminal look pre-empted that depth) plus a
    terminal bucket, without changing the pre-existing pooled fields'
    shape."""
    stats = run_census_cell(0, n_reps=5, seed=20260926_001)
    assert stats.max_abs_delta_by_depth is not None
    assert len(stats.max_abs_delta_by_depth) == N_DEPTHS
    assert all(v is None or v >= 0.0 for v in stats.max_abs_delta_by_depth)
    assert stats.terminal_max_abs_delta is None or stats.terminal_max_abs_delta >= 0.0
    # The last depth coincides with look_n == N_MAX, structurally always a
    # terminal look -- never populated in the interim table.
    assert N_MAX // LOOK_STEP == N_DEPTHS
    assert stats.max_abs_delta_by_depth[N_DEPTHS - 1] is None


def test_derive_eps_pin_produces_a_per_depth_pin_that_load_eps_pin_accepts(
    tmp_path: Path,
) -> None:
    """When every cell carries per-depth data, `derive_eps_pin` emits
    `eps_by_depth`/`eps_terminal`/`census_max_by_depth`/
    `census_terminal_max`, and the result LOADS cleanly via
    `load_eps_pin` -- proving the two layers agree on shape and the floor/
    3x-census invariants."""
    stats = [
        CensusCellStats(
            cell_index=i, n_reps=10, max_abs_delta_b=0.05, p999_abs_delta_b=0.05,
            min_dt=0.02, min_t1=0.2,
            max_abs_delta_by_depth=tuple(
                (0.01 * (depth + 1)) if depth < 3 else None for depth in range(N_DEPTHS)
            ),
            terminal_max_abs_delta=0.005,
        )
        for i in range(2)
    ]
    census_path = tmp_path / "census.json"
    census_path.write_text("{}", encoding="utf-8")

    pin = derive_eps_pin(stats, code_sha="abc123", census_json_path=census_path)

    assert len(pin["eps_by_depth"]) == N_DEPTHS
    assert len(pin["census_max_by_depth"]) == N_DEPTHS
    assert pin["eps_terminal"] == pytest.approx(max(0.02, 3.0 * 0.005))
    assert pin["eps"] == max([*pin["eps_by_depth"], pin["eps_terminal"]])
    # depth 4 (index 3) has NO observation (None on both stats rows, since
    # only depths 1-3 -- indices 0-2 -- were given a value above) -- falls
    # back to the global disclosure eps, never the floor.
    assert pin["eps_by_depth"][3] == pin["eps"]

    pin_path = tmp_path / "eps_pin.json"
    pin_path.write_text(json.dumps(pin), encoding="utf-8")
    loaded = load_eps_pin(pin_path, code_sha="abc123")
    assert loaded.eps_by_depth == tuple(pin["eps_by_depth"])
    assert loaded.eps_terminal == pin["eps_terminal"]


def test_derive_eps_pin_omits_per_depth_keys_when_any_cell_lacks_depth_data(
    tmp_path: Path,
) -> None:
    """A single legacy (scalar-only) row anywhere in `cell_stats` keeps the
    WHOLE derivation legacy -- never a partially-populated table."""
    stats = [
        CensusCellStats(
            cell_index=0, n_reps=10, max_abs_delta_b=0.01, p999_abs_delta_b=0.01,
            min_dt=0.02, min_t1=0.2,
            max_abs_delta_by_depth=(0.01,) * N_DEPTHS, terminal_max_abs_delta=0.001,
        ),
        CensusCellStats(
            cell_index=1, n_reps=10, max_abs_delta_b=0.01, p999_abs_delta_b=0.01,
            min_dt=0.02, min_t1=0.2,
        ),
    ]
    census_path = tmp_path / "census.json"
    census_path.write_text("{}", encoding="utf-8")

    pin = derive_eps_pin(stats, code_sha="abc123", census_json_path=census_path)
    assert "eps_by_depth" not in pin
    assert "eps_terminal" not in pin
