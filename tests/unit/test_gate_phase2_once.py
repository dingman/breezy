"""Phase 2 (the bwrap_host registry) runs exactly once per parallel run: in the serial tail.

Driver tests run ``run_tests_parallel.sh`` against the throwaway toolchain from
``test_gate_shards``; proof tests drive ``gate_shards.py phase2-proof`` on written logs.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest

from tests.unit.test_gate_shards import (  # noqa: F401  (fixtures are used by name)
    REPO_ROOT,
    SHARDS_PY,
    _fake,
    _remove_fake_homes,
    _run_parallel,
)


@pytest.fixture
def run_dir() -> Iterator[Path]:
    path = REPO_ROOT / ".pytest-tmp" / f"p2-{uuid.uuid4().hex[:8]}"
    yield path
    shutil.rmtree(path, ignore_errors=True)


DEFERRED: Final[str] = "[breezy] gate: phase1 rc=0 phase2 DEFERRED (parallel shard; NOT a gate run)"
TAIL_OK: Final[str] = "[breezy] gate: phase1 rc=0 phase2 rc=0"


def _calls_phase2(fake: object) -> list[dict[str, object]]:
    return [c for c in fake.calls() if c["phase2"] == "1"]  # type: ignore[attr-defined]


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
    result = _run_parallel(fake, run_dir, "--shards", "2", extra_env={"BREEZY_GATE_PHASE2": "skip"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert len(_calls_phase2(fake)) == 1


def test_a_failing_tail_phase2_makes_the_run_red(tmp_path: Path, run_dir: Path) -> None:
    fake = _fake(tmp_path)
    result = _run_parallel(fake, run_dir, "--shards", "2", extra_env={"BREEZY_FAKE_PHASE2_RC": "7"})
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
