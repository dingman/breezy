"""AUD-07 Rev 2 M1c/M2 execution amendment, tests 22-26 and 29 (plan §3, §8).

Covers the driver/resume/stage-separation/snapshot machinery in
`scripts/analysis/aud07_live_rule_crossing_sim.py`, the merge module
`scripts/analysis/aud07_m1c_merge.py`, and the shell drivers
`aud07_m1c_sweep.sh`/`aud07_m1c_cell.sh` (exercised only via the
`AUD07_CELL_CMD` test stub -- no real Monte-Carlo cell, no heavy job).
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

import aud07_live_rule_crossing_sim as sim_mod
from aud07_live_rule_crossing_sim import (
    AUDIT_TARGET,
    M1C_GRID,
    EpsPin,
    EpsPinValidationError,
    ForeignStageRowError,
    ResumeKeyConflictError,
    StageDirMismatchError,
    _assert_snapshot_imports,
    _resolve_audit_every,
    load_eps_pin,
    run_cell,
    run_chunk,
)
from aud07_live_rule_crossing_sim import (
    main as sim_main,
)
from aud07_m1c_merge import (
    MergeConflictError,
    MergeCoverageError,
    MergeStageError,
    merge_stage,
    pool_80k_substreams,
)

_SWEEP_SH = _SCRIPTS_ANALYSIS_DIR / "aud07_m1c_sweep.sh"
_CELL_SH = _SCRIPTS_ANALYSIS_DIR / "aud07_m1c_cell.sh"


def _future_cutoff_iso(days: int = 1) -> str:
    """A ``--cutoff``/``CUTOFF`` value guaranteed to be in the future.

    Computed at test-run time rather than hardcoded: a hardcoded absolute
    cutoff rots the instant that date is in the past, since ``cell.sh``
    treats a past/near cutoff as a reason to DEFER before it ever reaches
    the test stub or its regex -- failing tests that have nothing to do
    with the deferral behavior itself (GATE-1).
    """
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Test 22
# ---------------------------------------------------------------------------
def test_audit_premise_violation_aborts_the_cell_writes_no_row_and_the_driver_exits_nonzero(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs"
    queue = tmp_path / "queue.txt"
    queue.write_text("0\n", encoding="utf-8")
    calls_file = tmp_path / "calls.txt"

    # A stub cell command that records each invocation and always fails --
    # standing in for a real cell that raised AuditPremiseViolation (which
    # the CLI, in production, translates to a non-zero exit and no row
    # written).
    stub = tmp_path / "stub_cmd.sh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$1" >> "{calls_file}"\n'
        "exit 1\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    env = {**os.environ, "RUN_DIR": str(run_dir), "AUD07_CELL_CMD": str(stub)}

    result1 = subprocess.run(
        [
            "bash",
            str(_SWEEP_SH),
            "--code-sha",
            "deadbeef",
            "--stage",
            "20k",
            "--queue",
            str(queue),
            "--cutoff",
            _future_cutoff_iso(),
            "-P",
            "1",
        ],
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result1.returncode != 0, result1.stderr
    failed_file = run_dir / "20k" / "FAILED"
    assert failed_file.exists()
    assert failed_file.read_text(encoding="utf-8").startswith("0 rc=")
    assert calls_file.read_text(encoding="utf-8").strip().splitlines() == ["0"]

    # A second sweep start must refuse (fail-closed) WITHOUT invoking the
    # cell command again.
    result2 = subprocess.run(
        [
            "bash",
            str(_SWEEP_SH),
            "--code-sha",
            "deadbeef",
            "--stage",
            "20k",
            "--queue",
            str(queue),
            "--cutoff",
            _future_cutoff_iso(),
            "-P",
            "1",
        ],
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )
    assert result2.returncode != 0
    assert calls_file.read_text(encoding="utf-8").strip().splitlines() == ["0"], (
        "the second sweep start must NOT re-invoke the cell command"
    )


# ---------------------------------------------------------------------------
# Test 23
# ---------------------------------------------------------------------------
def test_resume_skips_done_cells_never_duplicates_and_raises_on_code_sha_mismatch(
    tmp_path: Path,
) -> None:
    stage_dir = tmp_path / "20k"
    stage_dir.mkdir()
    out_path = stage_dir / "cell_00_01.jsonl"

    run_chunk(0, 2, out_path=out_path, n_reps=3, npts=41, stage="20k", code_sha="sha-a")
    rows_after_first = out_path.read_text(encoding="utf-8").splitlines()
    assert len(rows_after_first) == 2

    # Resuming with the IDENTICAL key skips both cells -- no duplicate rows.
    run_chunk(0, 2, out_path=out_path, n_reps=3, npts=41, stage="20k", code_sha="sha-a")
    rows_after_resume = out_path.read_text(encoding="utf-8").splitlines()
    assert rows_after_resume == rows_after_first

    # A different code_sha on an already-done cell raises rather than
    # silently overwriting or duplicating.
    with pytest.raises(ResumeKeyConflictError):
        run_chunk(
            0, 1, out_path=out_path, n_reps=3, npts=41, stage="20k", code_sha="sha-B-DIFFERENT"
        )

    # Killed write: truncate to drop the trailing newline of the last row,
    # then append garbage that is itself a complete (parseable) line before
    # a final incomplete line -- resume must repair by truncating back to
    # the last COMPLETE line and re-run the incomplete one.
    killed_path = stage_dir / "cell_killed.jsonl"
    run_chunk(0, 1, out_path=killed_path, n_reps=3, npts=41, stage="20k", code_sha="sha-a")
    good_line = killed_path.read_text(encoding="utf-8")
    assert good_line.endswith("\n")
    incomplete_row = '{"stage": "20k", "cell_index": 1, "substream": null'  # a killed write
    with killed_path.open("a", encoding="utf-8") as f:
        f.write(incomplete_row)
    run_chunk(0, 2, out_path=killed_path, n_reps=3, npts=41, stage="20k", code_sha="sha-a")
    repaired_text = killed_path.read_text(encoding="utf-8")
    repaired_rows = [json.loads(line) for line in repaired_text.splitlines()]
    assert {row["cell_index"] for row in repaired_rows} == {0, 1}

    # A complete but unparsable line raises.
    bad_path = stage_dir / "cell_bad.jsonl"
    bad_path.write_text("not json at all\n", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        run_chunk(0, 1, out_path=bad_path, n_reps=3, npts=41, stage="20k", code_sha="sha-a")


# ---------------------------------------------------------------------------
# Test 24
# ---------------------------------------------------------------------------
def test_stage_separation(tmp_path: Path) -> None:
    wrong_dir = tmp_path / "not_the_stage_name"
    wrong_dir.mkdir()
    with pytest.raises(StageDirMismatchError):
        sim_main(
            [
                "--cells",
                "0:1",
                "--n-reps",
                "1",
                "--npts",
                "41",
                "--out",
                str(wrong_dir / "cell_00.jsonl"),
                "--stage",
                "20k",
            ]
        )

    # A foreign-stage row already in the file raises via run_chunk.
    foreign_path = tmp_path / "foreign.jsonl"
    foreign_path.write_text(
        json.dumps({"stage": "80k", "cell_index": 0, "substream": 0}) + "\n", encoding="utf-8"
    )
    with pytest.raises(ForeignStageRowError):
        run_chunk(0, 1, out_path=foreign_path, n_reps=1, npts=41, stage="20k", code_sha="sha-a")

    # The merge refuses mixed stages.
    mixed_stage_path = tmp_path / "mixed_stage.jsonl"
    mixed_stage_path.write_text(
        json.dumps({"stage": "20k", "cell_index": 0}) + "\n"
        + json.dumps({"stage": "80k", "cell_index": 1}) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(MergeStageError):
        merge_stage([mixed_stage_path], stage="20k")

    # The merge refuses more than one code_sha across the 20k/80k/cal_c stages.
    mixed_sha_path = tmp_path / "mixed_sha.jsonl"
    rows = [
        {"stage": "20k", "cell_index": i, "substream": None, "code_sha": sha, "eps_pin_sha256": "p"}
        for i, sha in zip(range(49), ["sha-a"] * 48 + ["sha-b"])
    ]
    mixed_sha_path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    with pytest.raises(MergeStageError):
        merge_stage([mixed_sha_path], stage="20k")


# ---------------------------------------------------------------------------
# Test 25
# ---------------------------------------------------------------------------
def test_merge_rejects_conflicting_duplicates_and_incomplete_coverage(tmp_path: Path) -> None:
    def _row(cell_index: int, *, crossing_count: int = 1, substream: int | None = None) -> dict:
        return {
            "stage": "20k",
            "cell_index": cell_index,
            "substream": substream,
            "code_sha": "sha-a",
            "eps_pin_sha256": "p",
            "crossing_count": crossing_count,
            "wall_s": 1.23,
        }

    conflict_path = tmp_path / "conflict.jsonl"
    conflict_path.write_text(
        json.dumps(_row(0, crossing_count=1)) + "\n" + json.dumps(_row(0, crossing_count=2)) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(MergeConflictError):
        merge_stage([conflict_path], stage="20k")

    # Identical duplicates (differing only in wall_s) dedupe cleanly.
    dedup_path = tmp_path / "dedup.jsonl"
    rows = [_row(i) for i in range(49)]
    lines = [json.dumps(r) for r in rows]
    lines.append(json.dumps({**rows[0], "wall_s": 9.99}))  # same identity, only wall_s differs
    dedup_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    merged = merge_stage([dedup_path], stage="20k")
    assert len(merged) == 49

    # Incomplete coverage (cell 48 missing) raises.
    incomplete_path = tmp_path / "incomplete.jsonl"
    incomplete_path.write_text(
        "\n".join(json.dumps(_row(i)) for i in range(48)) + "\n", encoding="utf-8"
    )
    with pytest.raises(MergeCoverageError):
        merge_stage([incomplete_path], stage="20k")

    # --mixed-only coverage: cells 0..15 plus 48 only.
    mixed_only_path = tmp_path / "mixed_only.jsonl"
    mixed_cells = list(range(16)) + [48]
    mixed_only_path.write_text(
        "\n".join(json.dumps(_row(i)) for i in mixed_cells) + "\n", encoding="utf-8"
    )
    merged_mixed = merge_stage([mixed_only_path], stage="20k", mixed_only=True)
    assert {row["cell_index"] for row in merged_mixed} == set(mixed_cells)
    with pytest.raises(MergeCoverageError):
        merge_stage([mixed_only_path], stage="20k", mixed_only=False)


# ---------------------------------------------------------------------------
# Test 26
# ---------------------------------------------------------------------------
def test_snapshot_import_assertion_raises_when_breezy_resolves_outside_the_snapshot(
    tmp_path: Path,
) -> None:
    with pytest.raises(AssertionError):
        _assert_snapshot_imports(tmp_path)
    _assert_snapshot_imports(_REPO_ROOT)  # the real root never raises.


# ---------------------------------------------------------------------------
# Test 29
# ---------------------------------------------------------------------------
def test_80k_substream_pooling_equals_direct_accumulation() -> None:
    import random

    rng = random.Random(20260925_290001)
    per_substream_reps = 25
    substream_terminal_s: list[list[float]] = [
        [rng.gauss(0.0, 1.0) for _ in range(per_substream_reps)] for _ in range(4)
    ]
    substream_look_counts: list[list[int]] = [
        [rng.randrange(1, 17) for _ in range(per_substream_reps)] for _ in range(4)
    ]

    sub_rows = []
    for terminals, look_counts in zip(substream_terminal_s, substream_look_counts):
        crossing_count = sum(1 for s in terminals if s >= 1.0)
        sub_rows.append(
            {
                "crossing_count": crossing_count,
                "n_reps": per_substream_reps,
                "sum_look_count": sum(look_counts),
                "loss_stop_count": 0,
                "sum_s_terminal": sum(terminals),
                "sum_s2_terminal": sum(s * s for s in terminals),
            }
        )

    pooled = pool_80k_substreams(sub_rows)

    all_terminals = [s for chunk in substream_terminal_s for s in chunk]
    all_look_counts = [n for chunk in substream_look_counts for n in chunk]
    direct_n_reps = len(all_terminals)
    direct_crossing_count = sum(1 for s in all_terminals if s >= 1.0)
    direct_sum_look_count = sum(all_look_counts)
    direct_sum_s = sum(all_terminals)
    direct_sum_s2 = sum(s * s for s in all_terminals)

    # Exact `==` on the integer fields.
    assert pooled["crossing_count"] == direct_crossing_count
    assert pooled["n_reps"] == direct_n_reps
    assert pooled["sum_look_count"] == direct_sum_look_count

    # Relative tolerance ~1e-12 on the float sums.
    assert pooled["sum_s_terminal"] == pytest.approx(direct_sum_s, rel=1e-12)
    assert pooled["sum_s2_terminal"] == pytest.approx(direct_sum_s2, rel=1e-12)


# ---------------------------------------------------------------------------
# 2026-09-25 review fixes (python REQUEST_CHANGES, test audit)
# ---------------------------------------------------------------------------


def test_main_asserts_snapshot_imports_for_gated_stages_but_not_smoke(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Review item 3: `main()` calls `_assert_snapshot_imports` for
    cal_a/cal_b/cal_c/20k/80k; `smoke` is exempt (decided and tested)."""
    monkeypatch.setattr(sim_mod, "_REPO_ROOT", tmp_path)

    gated_dir = tmp_path / "20k"
    gated_dir.mkdir()
    with pytest.raises(AssertionError):
        sim_main(
            [
                "--cells", "0:1", "--n-reps", "1", "--npts", "41",
                "--out", str(gated_dir / "cell_00.jsonl"),
                "--stage", "20k", "--code-sha", "deadbeef",
            ]
        )

    smoke_dir = tmp_path / "smoke"
    smoke_dir.mkdir()
    # smoke is exempt from the snapshot assertion, so this must NOT raise
    # AssertionError even though `_REPO_ROOT` is patched to a dir with no
    # breezy package -- it runs the (cheap) cell for real instead.
    rc = sim_main(
        [
            "--cells", "0:1", "--n-reps", "1", "--npts", "41",
            "--out", str(smoke_dir / "cell_00.jsonl"),
            "--stage", "smoke", "--code-sha", "deadbeef",
        ]
    )
    assert rc == 0


def test_eps_pin_validation_rejects_dt_min_leq_zero(tmp_path: Path) -> None:
    """Review item 6a."""
    payload = {
        "eps": 0.03,
        "dt_min": 0.0,
        "census_max": 0.005,
        "census_sha256": "d" * 64,
        "code_sha": "sha-a",
    }
    path = tmp_path / "eps_pin_zero_dt.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(EpsPinValidationError, match="dt_min"):
        load_eps_pin(path, code_sha="sha-a")

    path2 = tmp_path / "eps_pin_negative_dt.json"
    path2.write_text(json.dumps({**payload, "dt_min": -1e-6}), encoding="utf-8")
    with pytest.raises(EpsPinValidationError, match="dt_min"):
        load_eps_pin(path2, code_sha="sha-a")


def test_audit_every_defaults_from_n_reps_and_audit_target_and_rejects_too_few_audits() -> None:
    """Review item 6b: `audit_every` is computed from `n_reps`/`AUDIT_TARGET`
    when omitted, and an explicit value yielding fewer than `AUDIT_TARGET`
    audits is REJECTED."""
    assert _resolve_audit_every(20000, None) == 20000 // AUDIT_TARGET == 50
    assert _resolve_audit_every(80000, None) == 80000 // AUDIT_TARGET == 200
    # Too few reps for even one full AUDIT_TARGET batch: never divide by zero.
    assert _resolve_audit_every(200, None) == 1

    # An explicit value that clears the bar is accepted verbatim.
    assert _resolve_audit_every(1000, 2) == 2  # 1000 // 2 = 500 >= 400

    with pytest.raises(ValueError, match="audit"):
        _resolve_audit_every(1000, 10)  # 1000 // 10 = 100 < 400

    # Wired through run_cell: the resolved value is stamped on the row. eps
    # is deliberately generous (this is a wiring check, not a proximity
    # calibration) so every-rep auditing at audit_every=1 never trips
    # AuditPremiseViolation on this small rep count.
    pin = EpsPin(
        eps=1.0, dt_min=1e-6, census_sha256="0" * 64, census_max=0.0, code_sha="s", sha256="0" * 64
    )
    mixed_index = next(i for i, c in enumerate(M1C_GRID) if c.side_mix == "mixed" and c.k == 2)
    result = run_cell(
        M1C_GRID[mixed_index],
        cell_index=mixed_index,
        seed=20260925_950001,
        n_reps=40,
        npts=401,
        boundary_mode="refined",
        eps_pin=pin,
        coarse_npts=151,
        audit_every=None,
    )
    assert result.audit_every == max(1, 40 // AUDIT_TARGET) == 1


def test_cell_sh_rejects_shell_metacharacters_in_cell_arg_stage_and_cmd_without_executing(
    tmp_path: Path,
) -> None:
    """Review item 1 (CRITICAL): no value cell.sh reads is ever `eval`'d --
    a metacharacter-carrying cell arg, `STAGE`, or `AUD07_CELL_CMD` is
    rejected before anything runs."""
    run_dir = tmp_path / "runs"
    calls_file = tmp_path / "calls.txt"
    marker = tmp_path / "PWNED"
    stub = tmp_path / "stub.sh"
    stub.write_text(
        f'#!/usr/bin/env bash\necho "$1 $2" >> "{calls_file}"\nexit 0\n', encoding="utf-8"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    base_env = {
        **os.environ,
        "RUN_DIR": str(run_dir),
        "STAGE": "20k",
        "CUTOFF": _future_cutoff_iso(),
        "AUD07_CELL_CMD": str(stub),
    }

    r_arg = subprocess.run(
        ["bash", str(_CELL_SH), f"0; touch {marker}"],
        env=base_env, capture_output=True, text=True, check=False,
    )
    assert r_arg.returncode != 0
    assert not marker.exists()
    assert not calls_file.exists()

    r_stage = subprocess.run(
        ["bash", str(_CELL_SH), "0"],
        env={**base_env, "STAGE": f"20k; touch {marker}"},
        capture_output=True, text=True, check=False,
    )
    assert r_stage.returncode != 0
    assert not marker.exists()
    assert not calls_file.exists()

    r_cmd = subprocess.run(
        ["bash", str(_CELL_SH), "0"],
        env={**base_env, "AUD07_CELL_CMD": f"{stub} ; touch {marker}"},
        capture_output=True, text=True, check=False,
    )
    assert r_cmd.returncode != 0
    assert not marker.exists()
    assert not calls_file.exists()


def test_cell_sh_defers_near_cutoff_runs_far_cutoff_and_uses_the_class_median(
    tmp_path: Path,
) -> None:
    """Review item 2: the §3.4 est_wall/cutoff deferral."""
    run_dir = tmp_path / "runs"
    stage_dir = run_dir / "20k"
    stage_dir.mkdir(parents=True)
    calls_file = tmp_path / "calls.txt"
    stub = tmp_path / "stub.sh"
    stub.write_text(
        f'#!/usr/bin/env bash\necho "ran $1" >> "{calls_file}"\nexit 0\n', encoding="utf-8"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    def _run(cell_arg: str, cutoff_iso: str) -> subprocess.CompletedProcess:
        env = {
            **os.environ,
            "RUN_DIR": str(run_dir),
            "STAGE": "20k",
            "CUTOFF": cutoff_iso,
            "AUD07_CELL_CMD": str(stub),
        }
        return subprocess.run(
            ["bash", str(_CELL_SH), cell_arg], env=env, capture_output=True, text=True, check=False
        )

    far = _future_cutoff_iso()
    r_far = _run("48", far)
    assert r_far.returncode == 0, r_far.stderr
    assert "ran 48" in calls_file.read_text(encoding="utf-8")

    near = (datetime.now(UTC) + timedelta(seconds=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r_near = _run("47", near)
    assert r_near.returncode == 0, r_near.stderr
    deferred_text = (stage_dir / "DEFERRED").read_text(encoding="utf-8")
    assert "47" in deferred_text
    assert "ran 47" not in calls_file.read_text(encoding="utf-8")

    # Seed completed "mixed"-class (cell_index 0-15) rows with a small
    # median wall_s, then use a cutoff that fits the MEDIAN (12s) but NOT
    # the class default (4928s) -- proving the median, not the default,
    # drove the decision.
    (stage_dir / "cell_00.jsonl").write_text(
        json.dumps({"cell_index": 0, "wall_s": 5.0}) + "\n"
        + json.dumps({"cell_index": 1, "wall_s": 15.0}) + "\n",
        encoding="utf-8",
    )
    fits_median_only = (datetime.now(UTC) + timedelta(seconds=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r_median = _run("2", fits_median_only)
    assert r_median.returncode == 0, r_median.stderr
    assert "ran 2" in calls_file.read_text(encoding="utf-8")


def test_sweep_sh_exports_thread_env_vars_itself(tmp_path: Path) -> None:
    """Review item 4."""
    run_dir = tmp_path / "runs"
    queue = tmp_path / "queue.txt"
    queue.write_text("0\n", encoding="utf-8")
    env_report = tmp_path / "env_report.txt"
    stub = tmp_path / "stub.sh"
    report_line = (
        'echo "OPENBLAS=$OPENBLAS_NUM_THREADS OMP=$OMP_NUM_THREADS '
        f'MKL=$MKL_NUM_THREADS" >> "{env_report}"\n'
    )
    stub.write_text(
        "#!/usr/bin/env bash\n" + report_line + "exit 0\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    env = {k: v for k, v in os.environ.items() if not k.endswith("_NUM_THREADS")}
    env.update({"RUN_DIR": str(run_dir), "AUD07_CELL_CMD": str(stub)})

    result = subprocess.run(
        [
            "bash", str(_SWEEP_SH),
            "--code-sha", "deadbeef", "--stage", "20k",
            "--queue", str(queue), "--cutoff", _future_cutoff_iso(), "-P", "1",
        ],
        env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert env_report.read_text(encoding="utf-8").strip() == "OPENBLAS=1 OMP=1 MKL=1"


def test_malformed_completed_row_degrades_to_the_default_and_the_cell_still_runs(
    tmp_path: Path,
) -> None:
    """Re-verification fix: a malformed completed row (non-int
    `cell_index`, non-numeric/non-positive `wall_s`) must be SKIPPED with a
    counted stderr WARN, never crash the estimator -- the cell then falls
    back to the class default and still runs (or defers) correctly."""
    run_dir = tmp_path / "runs"
    stage_dir = run_dir / "20k"
    stage_dir.mkdir(parents=True)
    calls_file = tmp_path / "calls.txt"
    stub = tmp_path / "stub.sh"
    stub.write_text(
        f'#!/usr/bin/env bash\necho "ran $1" >> "{calls_file}"\nexit 0\n', encoding="utf-8"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    # Malformed rows: non-int cell_index, non-numeric wall_s, negative
    # wall_s, non-finite wall_s -- all in the "mixed" class (0-15).
    malformed_rows = [
        {"cell_index": "0", "wall_s": 5.0},
        {"cell_index": 1, "wall_s": "not-a-number"},
        {"cell_index": 2, "wall_s": -5.0},
        {"cell_index": 3, "wall_s": float("nan")},
    ]
    (stage_dir / "cell_00.jsonl").write_text(
        "\n".join(json.dumps(row) for row in malformed_rows) + "\n", encoding="utf-8"
    )

    env = {
        **os.environ,
        "RUN_DIR": str(run_dir),
        "STAGE": "20k",
        # Far enough to fit the class default (4928s for "mixed") but the
        # malformed rows above must never be allowed to produce a bogus
        # median that would change this outcome.
        "CUTOFF": (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "AUD07_CELL_CMD": str(stub),
    }
    result = subprocess.run(
        ["bash", str(_CELL_SH), "4"], env=env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "ran 4" in calls_file.read_text(encoding="utf-8")
    assert "WARN" in result.stderr
    assert "4" in result.stderr  # 4 malformed rows skipped


def test_estimator_crash_lands_in_failed_not_a_bare_traceback(tmp_path: Path) -> None:
    """Re-verification fix: an unexpected error in the estimator (never a
    type-validation skip) must append to FAILED and exit 255, never a bare
    traceback."""
    run_dir = tmp_path / "runs"
    stage_dir = run_dir / "20k"
    stage_dir.mkdir(parents=True)
    calls_file = tmp_path / "calls.txt"
    stub = tmp_path / "stub.sh"
    stub.write_text(
        f'#!/usr/bin/env bash\necho "ran $1" >> "{calls_file}"\nexit 0\n', encoding="utf-8"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    # An unreadable row file: a genuine unexpected error (PermissionError),
    # never a type-validation case.
    unreadable = stage_dir / "cell_00.jsonl"
    unreadable.write_text(json.dumps({"cell_index": 0, "wall_s": 5.0}) + "\n", encoding="utf-8")
    unreadable.chmod(0o000)
    try:
        env = {
            **os.environ,
            "RUN_DIR": str(run_dir),
            "STAGE": "20k",
            "CUTOFF": (datetime.now(UTC) + timedelta(days=1)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "AUD07_CELL_CMD": str(stub),
        }
        result = subprocess.run(
            ["bash", str(_CELL_SH), "1"], env=env, capture_output=True, text=True, check=False
        )
    finally:
        unreadable.chmod(0o644)

    assert result.returncode == 255, (result.returncode, result.stderr)
    assert not calls_file.exists()
    failed_text = (stage_dir / "FAILED").read_text(encoding="utf-8")
    assert "1" in failed_text
    assert "Traceback" not in result.stderr


# ---------------------------------------------------------------------------
# 2026-09-25 census-chunking fix: cell.sh --stage cal_b dispatch
# ---------------------------------------------------------------------------
def test_cell_sh_cal_b_dispatches_to_the_census_per_cell_cli_and_validates_its_args(
    tmp_path: Path,
) -> None:
    """cal_b is a DIFFERENT computation from cal_a/cal_c (the boundary-delta
    census, not a crossing-rate Monte-Carlo) -- cell.sh must dispatch it to
    `aud07_m1c_census.py`, never to `aud07_live_rule_crossing_sim.py`, with
    the same validated-args, no-eval discipline."""
    run_dir = tmp_path / "runs"
    env_ok = {
        **os.environ,
        "RUN_DIR": str(run_dir),
        "STAGE": "cal_b",
        "CODE_SHA": "deadbeef",
        "N_REPS": "1",
        "CUTOFF": (datetime.now(UTC) + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    result = subprocess.run(
        ["bash", str(_CELL_SH), "0"], env=env_ok, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    out_path = run_dir / "cal_b" / "cell_00.jsonl"
    row = json.loads(out_path.read_text(encoding="utf-8").splitlines()[0])
    assert row["stage"] == "cal_b"
    assert row["cell_index"] == 0
    assert row["boundary_mode"] == "census"

    # Missing N_REPS is refused (cal_b still needs it, for --reps-per-cell)
    # before anything runs.
    env_missing_n_reps = {k: v for k, v in env_ok.items() if k != "N_REPS"}
    result2 = subprocess.run(
        ["bash", str(_CELL_SH), "1"],
        env=env_missing_n_reps, capture_output=True, text=True, check=False,
    )
    assert result2.returncode != 0
    assert not (run_dir / "cal_b" / "cell_01.jsonl").exists()


# ---------------------------------------------------------------------------
# AUD-07 DEFERRED gate (RULING_backlog_resolution_2026-09-28.md, "the AUD-07
# chain never advances to 80k while 20k/DEFERRED is non-empty or 20k coverage
# of cells 0-48 is incomplete"). Nothing enforced this before: `sweep.sh`
# only refused on an existing FAILED file, and `--mixed-only` merges needed
# only cells 0-15 and 48. These tests exercise the smallest enforcement --
# `sweep.sh` itself refusing `--stage 80k` -- via the same `AUD07_CELL_CMD`
# stub pattern used above, never a real Monte-Carlo cell.
# ---------------------------------------------------------------------------
def _stub_cell_cmd(tmp_path: Path, calls_file: Path) -> Path:
    stub = tmp_path / "stub_80k_cmd.sh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$1" >> "{calls_file}"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return stub


def _write_full_20k_coverage(run_dir: Path) -> None:
    """49 synthetic, minimal `stage=20k` rows -- cells 0..48 -- the exact
    shape `check_coverage_20k` (`aud07_m1c_merge.py`) needs and nothing
    more (no `code_sha`/`eps_pin_sha256`: this path never calls
    `merge_stage`, only `load_stage_rows` + `check_coverage_20k`)."""
    twentyk_dir = run_dir / "20k"
    twentyk_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(
        json.dumps({"stage": "20k", "cell_index": i, "substream": None}) for i in range(49)
    )
    (twentyk_dir / "cell_all.jsonl").write_text(lines + "\n", encoding="utf-8")


def test_sweep_sh_refuses_stage_80k_when_20k_deferred_is_non_empty(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs"
    _write_full_20k_coverage(run_dir)
    (run_dir / "20k" / "DEFERRED").write_text("12\n", encoding="utf-8")

    queue = tmp_path / "queue.txt"
    queue.write_text("0\n", encoding="utf-8")
    calls_file = tmp_path / "calls.txt"
    stub = _stub_cell_cmd(tmp_path, calls_file)
    env = {**os.environ, "RUN_DIR": str(run_dir), "AUD07_CELL_CMD": str(stub)}

    result = subprocess.run(
        [
            "bash", str(_SWEEP_SH),
            "--code-sha", "deadbeef", "--stage", "80k",
            "--queue", str(queue), "--cutoff", _future_cutoff_iso(), "-P", "1",
        ],
        env=env, capture_output=True, text=True, check=False,
    )

    assert result.returncode != 0
    assert "DEFERRED" in result.stderr
    assert not calls_file.exists(), (
        "the 80k cell command must never run while 20k/DEFERRED is non-empty"
    )


def test_sweep_sh_refuses_stage_80k_when_20k_coverage_is_incomplete(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs"
    # 20k/ exists but is missing cell 48 -- incomplete coverage, no DEFERRED file at all.
    twentyk_dir = run_dir / "20k"
    twentyk_dir.mkdir(parents=True, exist_ok=True)
    lines = "\n".join(
        json.dumps({"stage": "20k", "cell_index": i, "substream": None}) for i in range(48)
    )
    (twentyk_dir / "cell_all.jsonl").write_text(lines + "\n", encoding="utf-8")

    queue = tmp_path / "queue.txt"
    queue.write_text("0\n", encoding="utf-8")
    calls_file = tmp_path / "calls.txt"
    stub = _stub_cell_cmd(tmp_path, calls_file)
    env = {**os.environ, "RUN_DIR": str(run_dir), "AUD07_CELL_CMD": str(stub)}

    result = subprocess.run(
        [
            "bash", str(_SWEEP_SH),
            "--code-sha", "deadbeef", "--stage", "80k",
            "--queue", str(queue), "--cutoff", _future_cutoff_iso(), "-P", "1",
        ],
        env=env, capture_output=True, text=True, check=False,
    )

    assert result.returncode != 0
    assert "coverage" in result.stderr
    # Review fix: the underlying `check_coverage_20k` exception text (which
    # names the actual missing cell) must be INCORPORATED into the one
    # refusal line -- not merely present somewhere in combined stderr (the
    # python subprocess's stderr passes through unprefixed regardless, so a
    # bare substring check would pass even with the bug: the refusal line
    # itself renders as "...is incomplete: " with nothing after the colon).
    refusal_lines = [
        line for line in result.stderr.splitlines() if "is incomplete:" in line
    ]
    assert refusal_lines, result.stderr
    assert len(refusal_lines) == 1, result.stderr
    detail = refusal_lines[0].split("is incomplete:", 1)[1].strip()
    assert detail, f"refusal line carries no detail after the colon: {refusal_lines[0]!r}"
    assert "missing cell(s)" in detail
    assert "48" in detail
    assert not calls_file.exists(), (
        "the 80k cell command must never run while 20k coverage is incomplete"
    )


def test_sweep_sh_allows_stage_80k_once_20k_is_fully_covered_and_deferred_is_empty(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs"
    _write_full_20k_coverage(run_dir)
    # An empty DEFERRED file (every deferred cell later drained) must not refuse.
    (run_dir / "20k" / "DEFERRED").write_text("", encoding="utf-8")

    queue = tmp_path / "queue.txt"
    queue.write_text("0\n", encoding="utf-8")
    calls_file = tmp_path / "calls.txt"
    stub = _stub_cell_cmd(tmp_path, calls_file)
    env = {**os.environ, "RUN_DIR": str(run_dir), "AUD07_CELL_CMD": str(stub)}

    result = subprocess.run(
        [
            "bash", str(_SWEEP_SH),
            "--code-sha", "deadbeef", "--stage", "80k",
            "--queue", str(queue), "--cutoff", _future_cutoff_iso(), "-P", "1",
        ],
        env=env, capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert calls_file.read_text(encoding="utf-8").strip().splitlines() == ["0"]


def test_sweep_sh_never_gates_stages_other_than_80k(tmp_path: Path) -> None:
    """A `--stage 20k` sweep must never consult its own DEFERRED/coverage
    state -- the gate is an 80k-only precondition."""
    run_dir = tmp_path / "runs"
    # No 20k/ directory at all; a 20k-gating-itself bug would refuse here.
    queue = tmp_path / "queue.txt"
    queue.write_text("0\n", encoding="utf-8")
    calls_file = tmp_path / "calls.txt"
    stub = _stub_cell_cmd(tmp_path, calls_file)
    env = {**os.environ, "RUN_DIR": str(run_dir), "AUD07_CELL_CMD": str(stub)}

    result = subprocess.run(
        [
            "bash", str(_SWEEP_SH),
            "--code-sha", "deadbeef", "--stage", "20k",
            "--queue", str(queue), "--cutoff", _future_cutoff_iso(), "-P", "1",
        ],
        env=env, capture_output=True, text=True, check=False,
    )

    assert result.returncode == 0, result.stderr
    assert calls_file.read_text(encoding="utf-8").strip().splitlines() == ["0"]
