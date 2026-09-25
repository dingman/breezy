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
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from aud07_live_rule_crossing_sim import (
    ForeignStageRowError,
    ResumeKeyConflictError,
    StageDirMismatchError,
    _assert_snapshot_imports,
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
            "2026-09-26T00:00:00Z",
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
            "2026-09-26T00:00:00Z",
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
