"""Phase 2 (the bwrap_host registry) runs exactly once per parallel run: in the serial tail.

Driver tests run ``run_tests_parallel.sh`` against the throwaway toolchain in
``_gate_helpers``; proof tests drive ``gate_shards.py phase2-proof`` and ``deferred-rc``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import pytest

from tests.unit import _gate_helpers as helpers
from tests.unit._gate_helpers import REPO_ROOT, _fake, _run_parallel
from tests.unit.test_gate_shards import PERSIST_ID, _flake_shell
from tests.unit.test_run_tests_no_egress_phases import _defer_run, _par_gate, _run_script

SHARDS_PY: Final[Path] = REPO_ROOT / "scripts" / "ci" / "gate_shards.py"
run_dir = helpers.run_dir
_remove_fake_homes = helpers._remove_fake_homes

DEFERRED: Final[str] = "[breezy] gate: phase1 rc=0 phase2 DEFERRED (parallel shard; NOT a gate run)"
TAIL_OK: Final[str] = "[breezy] gate: phase1 rc=0 phase2 rc=0"
#: Pytest output that merely mentions the verdict words; it must never move a count.
TRACEBACK: Final[str] = (
    "E   AssertionError: [breezy] gate: phase1 rc=0 phase2 DEFERRED (parallel shard)\n"
    "    saw 'phase2 rc=0' and 'DEFERRED' in the output\n"
)


def _calls_phase2(fake: Any) -> list[dict[str, object]]:
    return [c for c in fake.calls() if c["phase2"] == "1"]


def test_exactly_one_phase2_call_and_it_is_the_tails(tmp_path: Path, run_dir: Path) -> None:
    fake = _fake(tmp_path)
    result = _run_parallel(fake, run_dir, "--shards", "2")
    assert result.returncode == 0, result.stdout + result.stderr
    phase2 = _calls_phase2(fake)
    assert len(phase2) == 1
    assert Path(str(phase2[0]["gate_dir"])).name == "tail"
    assert "[phase2] phase 2 ran once, in the tail" in result.stdout


def test_job_logs_carry_the_deferred_and_phase2_lines(tmp_path: Path, run_dir: Path) -> None:
    fake = _fake(tmp_path)
    assert _run_parallel(fake, run_dir, "--shards", "2").returncode == 0
    for shard in sorted((run_dir / "logs").glob("s?.log")):
        text = shard.read_text(encoding="utf-8")
        assert text.count("phase2 DEFERRED") == 1 and "phase2 rc=" not in text
    tail = (run_dir / "logs" / "tail.log").read_text(encoding="utf-8")
    assert tail.count("phase2 rc=0") == 1 and "DEFERRED" not in tail


def test_an_inherited_phase2_variable_does_not_reach_the_tail(
    tmp_path: Path, run_dir: Path
) -> None:
    fake = _fake(tmp_path)
    extra = {"BREEZY_GATE_PHASE2": "skip"}
    result = _run_parallel(fake, run_dir, "--shards", "2", extra_env=extra)
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_calls_phase2(fake)) == 1


def test_a_failing_tail_phase2_makes_the_run_red(tmp_path: Path, run_dir: Path) -> None:
    fake = _fake(tmp_path)
    extra = {"BREEZY_FAKE_PHASE2_RC": "7"}
    result = _run_parallel(fake, run_dir, "--shards", "2", extra_env=extra)
    assert result.returncode == 7
    assert "GATE GREEN" not in result.stdout and "GATE RED" in result.stdout
    assert len(_calls_phase2(fake)) == 1


def test_an_empty_tail_is_red_with_rc_4_because_phase2_never_ran(
    tmp_path: Path, run_dir: Path
) -> None:
    fake = _fake(tmp_path, ids=["tests/unit/test_one.py::test_a"])
    result = _run_parallel(fake, run_dir, "--shards", "1")
    assert result.returncode == 4, result.stdout + result.stderr
    assert "phase 2 never ran" in result.stdout
    assert _calls_phase2(fake) == []
    assert "GATE GREEN" not in result.stdout


# --- F1: a deferred run never exits 0; only the driver maps it back ---------------------------


def test_a_serial_defer_run_with_a_valid_token_exits_deferred_pass_rc_never_zero(
    tmp_path: Path,
) -> None:
    result = _defer_run(tmp_path, _par_gate(tmp_path))
    assert result.returncode == 10, result.stderr


def test_the_driver_accepts_rc_10_plus_the_line_from_a_deferred_shard(
    tmp_path: Path, run_dir: Path
) -> None:
    fake = _fake(tmp_path)
    result = _run_parallel(fake, run_dir, "--shards", "2")
    assert result.returncode == 0, result.stdout + result.stderr
    raw = (run_dir / "logs" / "s0.rc").read_text(encoding="utf-8").split()[0]
    assert raw == "10"  # the job really exited DEFERRED_PASS_RC; the driver mapped it


def test_the_driver_rejects_rc_10_from_the_tail(tmp_path: Path, run_dir: Path) -> None:
    fake = _fake(tmp_path)
    extra = {"BREEZY_FAKE_PHASE2_RC": "10"}
    result = _run_parallel(fake, run_dir, "--shards", "2", extra_env=extra)
    assert result.returncode == 10
    assert "GATE GREEN" not in result.stdout and "GATE RED" in result.stdout


def test_the_driver_rejects_rc_10_without_a_phase1_pass_line(tmp_path: Path, run_dir: Path) -> None:
    fake = _fake(tmp_path, force_rc=10)  # phase 1 itself exits 10: "phase1 rc=10 ... DEFERRED"
    result = _run_parallel(fake, run_dir, "--shards", "2")
    assert result.returncode == 10, result.stdout + result.stderr
    assert "GATE GREEN" not in result.stdout


def _deferred_rc(tmp_path: Path, rc: int, log: str | None) -> int:
    path = tmp_path / "job.log"
    if log is not None:
        path.write_text(log, encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(SHARDS_PY), "deferred-rc", "--rc", str(rc), "--log", str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    return int(out.stdout)


@pytest.mark.parametrize(
    ("rc", "log", "expected"),
    [
        (10, DEFERRED + "\n", 0),
        (10, "noise\n" + DEFERRED + "\n", 0),
        (10, None, 10),
        (10, "", 10),
        (10, "[breezy] gate: phase1 rc=3 phase2 DEFERRED (parallel shard; NOT a gate run)\n", 10),
        (10, DEFERRED + "\n" + DEFERRED + "\n", 10),
        (10, TRACEBACK, 10),
        (10, TAIL_OK + "\n", 10),
        (1, DEFERRED + "\n", 1),
        (5, DEFERRED + "\n", 5),
    ],
)
def test_deferred_rc_maps_only_rc_10_with_exactly_one_anchored_pass_line(
    tmp_path: Path, rc: int, log: str | None, expected: int
) -> None:
    assert _deferred_rc(tmp_path, rc, log) == expected


# --- phase2-proof, over anchored wrapper verdict lines -----------------------------------------


def _proof(
    tmp_path: Path, shards: list[str | None], tail: str | None
) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(SHARDS_PY), "phase2-proof"]
    for i, text in enumerate(shards):
        path = tmp_path / f"s{i}.log"
        if text is not None:
            path.write_text(text, encoding="utf-8")
        args += ["--shard-log", str(path)]
    if tail is not None:
        (tmp_path / "tail.log").write_text(tail, encoding="utf-8")
    args += ["--tail-log", str(tmp_path / "tail.log")]
    return subprocess.run(args, capture_output=True, text=True, check=False, cwd=REPO_ROOT)


def test_proof_passes_for_deferred_shards_and_one_tail_line(tmp_path: Path) -> None:
    result = _proof(tmp_path, [f"noise\n{DEFERRED}\n", f"{DEFERRED}\n"], f"x\n{TAIL_OK}\n")
    assert result.returncode == 0, result.stdout
    assert "ran once, in the tail" in result.stdout


def test_proof_ignores_pytest_output_that_mentions_the_verdict_words(tmp_path: Path) -> None:
    good = _proof(tmp_path, [TRACEBACK + DEFERRED + "\n"], TRACEBACK + TAIL_OK + "\n")
    assert good.returncode == 0, good.stdout
    # A mention alone neither supplies the missing verdict line nor adds a second one.
    only_mention = tmp_path / "m"
    only_mention.mkdir()
    bad = _proof(only_mention, [TRACEBACK], TRACEBACK)
    assert bad.returncode == 4
    assert "0 DEFERRED line" in bad.stdout and "0 'phase2 rc=0' line" in bad.stdout


@pytest.mark.parametrize(
    ("shards", "tail", "needle"),
    [
        ([DEFERRED + "\n"], None, "phase 2 never ran"),
        ([DEFERRED + "\n"], "", "0 'phase2 rc=0' line"),
        (["pytest output only\n"], TAIL_OK + "\n", "0 DEFERRED line"),
        ([None], TAIL_OK + "\n", "no readable log"),
        ([DEFERRED + "\n" + TAIL_OK + "\n"], TAIL_OK + "\n", "ran phase 2"),
        ([DEFERRED + "\n" + DEFERRED + "\n"], TAIL_OK + "\n", "2 DEFERRED line"),
        ([DEFERRED + "\n"], TAIL_OK + "\n" + TAIL_OK + "\n", "2 'phase2 rc=0' line"),
        ([DEFERRED + "\n"], "[breezy] gate: phase1 rc=0 phase2 rc=7\n", "failing or odd phase 2"),
        ([DEFERRED + "\n"], TAIL_OK + "\n" + DEFERRED + "\n", "tail deferred"),
    ],
)
def test_proof_rc_4_when_phase2_did_not_run_exactly_once_in_the_tail(
    tmp_path: Path, shards: list[str | None], tail: str | None, needle: str
) -> None:
    result = _proof(tmp_path, shards, tail)
    assert result.returncode == 4, result.stdout
    assert needle in result.stdout


def test_a_non_empty_tail_whose_log_is_missing_gives_rc_4(tmp_path: Path) -> None:
    result = _proof(tmp_path, [DEFERRED + "\n"], None)  # tail.log is never written
    assert result.returncode == 4
    assert "phase 2 never ran: the tail has no readable log" in result.stdout


# --- F4: real wrapper output, flake rerun, bad tail phase 2 -------------------------------------


def test_proof_accepts_real_wrapper_stderr_from_a_defer_run_and_a_serial_run(
    tmp_path: Path,
) -> None:
    deferred_dir = tmp_path / "d"
    deferred_dir.mkdir()
    deferred = _defer_run(deferred_dir, _par_gate(deferred_dir))
    serial_dir = tmp_path / "t"
    serial_dir.mkdir()
    serial = _run_script(serial_dir)
    assert deferred.returncode == 10 and serial.returncode == 0
    proof_dir = tmp_path / "p"
    proof_dir.mkdir()
    result = _proof(proof_dir, [deferred.stderr], serial.stderr)
    assert result.returncode == 0, result.stdout


def test_a_deferred_flake_rerun_is_included_in_the_proof_and_supersedes(
    tmp_path: Path, run_dir: Path
) -> None:
    fake = _flake_shell(tmp_path, fail_once=[PERSIST_ID])
    result = _run_parallel(fake, run_dir, "--shards", "2")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "load-flake rerun (once)" in result.stdout
    flake_log = (run_dir / "logs" / "flake.log").read_text(encoding="utf-8")
    assert flake_log.count("phase2 DEFERRED") == 1 and "phase2 rc=" not in flake_log
    assert "(3 deferred job(s))" in result.stdout  # two shards plus the flake rerun
    assert len(_calls_phase2(fake)) == 1


def test_a_bad_tail_phase2_suppresses_the_flake_rerun(tmp_path: Path, run_dir: Path) -> None:
    # The tail's phase-1 flake masks its phase-2 rc (the wrapper exits phase 1's rc), so the
    # flake planner alone would accept the rerun and supersede the tail.
    fake = _flake_shell(tmp_path, fail_once=[PERSIST_ID])
    extra = {"BREEZY_FAKE_PHASE2_RC": "7"}
    result = _run_parallel(fake, run_dir, "--shards", "2", extra_env=extra)
    assert result.returncode != 0 and "GATE GREEN" not in result.stdout
    assert "no load-flake rerun" in result.stdout
    assert not (run_dir / "junit" / "flake-rerun.xml").exists()
