"""ING-2 S2, AC-D9: the installed unit's `--deadline-seconds` and
`OOMScoreAdjust` contract.

Deliberately text-only parsing, matching `test_quote_tape_service_memory_
ceiling.py`'s and `test_deploy_timer_hours.py`'s approach -- `systemd-analyze
verify` is exercised too, but only when the binary is on `PATH` (never a
silent pass: absence is reported via `pytest.skip`, per T-sdv).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from breezy.runtime.ingest_deadline import (
    DEFAULT_DEADLINE_SECONDS,
    STARTUP_AND_TAIL_ALLOWANCE_SECONDS,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_UNIT_PATH = _REPO_ROOT / "deploy" / "systemd" / "breezy-quote-tape-ingest.service"
_SUPERVISOR_UNIT_PATH = _REPO_ROOT / "deploy" / "systemd" / "breezy-trade-supervisor.service"

_DEADLINE_ARG_RE = re.compile(r"--deadline-seconds[ =](\d+)")
_TIMEOUT_START_SEC_RE = re.compile(r"^TimeoutStartSec=(\d+)$")
_OOM_SCORE_ADJUST_RE = re.compile(r"^OOMScoreAdjust=(-?\d+)$")

_EARLY_WARNING_MARGIN_SECONDS = 900


def _unit_text() -> str:
    return _UNIT_PATH.read_text()


def _exec_start_deadline_seconds() -> int:
    match = _DEADLINE_ARG_RE.search(_unit_text())
    assert match is not None, "ExecStart must pass --deadline-seconds explicitly"
    return int(match.group(1))


def _timeout_start_sec() -> int:
    for line in _unit_text().splitlines():
        match = _TIMEOUT_START_SEC_RE.match(line.strip())
        if match is not None:
            return int(match.group(1))
    raise AssertionError("TimeoutStartSec= is missing")


def _oom_score_adjust(text: str) -> int | None:
    for line in text.splitlines():
        match = _OOM_SCORE_ADJUST_RE.match(line.strip())
        if match is not None:
            return int(match.group(1))
    return None


def test_the_unit_exists() -> None:
    assert _UNIT_PATH.is_file()


def test_deadline_seconds_matches_the_module_default() -> None:
    assert _exec_start_deadline_seconds() == DEFAULT_DEADLINE_SECONDS


def test_deadline_seconds_is_within_the_approved_band() -> None:
    assert 600 <= _exec_start_deadline_seconds() <= 720


def test_deadline_seconds_leaves_the_timeout_margin() -> None:
    assert (
        _exec_start_deadline_seconds() <= _timeout_start_sec() - STARTUP_AND_TAIL_ALLOWANCE_SECONDS
    )


def test_deadline_plus_allowance_stays_under_the_early_warning_margin() -> None:
    total = _exec_start_deadline_seconds() + STARTUP_AND_TAIL_ALLOWANCE_SECONDS
    assert total <= _EARLY_WARNING_MARGIN_SECONDS


def test_timeout_start_sec_is_pinned_at_780() -> None:
    # O-1: --deadline-seconds 600 + the 180 s tail; keeps the last pre-window
    # run (16:15Z) dead before the 16:30Z launch window opens.
    assert _timeout_start_sec() == 780


def test_memory_directives_are_unchanged() -> None:
    text = _unit_text()
    assert "MemoryHigh=4G" in text
    assert "MemoryMax=6G" in text


def test_oom_score_adjust_is_exactly_500() -> None:
    assert _oom_score_adjust(_unit_text()) == 500


def test_oom_score_adjust_appears_exactly_once() -> None:
    lines = [line.strip() for line in _unit_text().splitlines()]
    matches = [line for line in lines if _OOM_SCORE_ADJUST_RE.match(line)]
    assert len(matches) == 1


def test_the_trade_supervisor_unit_never_sets_a_high_oom_score_adjust() -> None:
    if not _SUPERVISOR_UNIT_PATH.is_file():
        return
    value = _oom_score_adjust(_SUPERVISOR_UNIT_PATH.read_text())
    assert value is None or value < 500


def test_the_exit_contract_comment_mentions_deadline_deferral() -> None:
    assert "deadline deferral" in _unit_text()


def test_a_hand_run_hazard_note_is_present() -> None:
    text = _unit_text()
    assert "is-active" in text
    assert "L-50" in text


def test_systemd_analyze_verify_passes_when_available() -> None:
    analyzer = shutil.which("systemd-analyze")
    if analyzer is None:
        import pytest

        pytest.skip("systemd-analyze not on PATH")
    result = subprocess.run(
        [analyzer, "verify", str(_UNIT_PATH)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, (
        f"systemd-analyze verify failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )


def test_failure_of_any_exit_reaches_the_study_failed_notifier() -> None:
    """DEFER-STREAK-LOAD r2 (T15 a/b): exit 5 (and 3/4) rely on OnFailure=."""
    lines = [line.strip() for line in _unit_text().splitlines()]
    active = [line for line in lines if not line.startswith("#")]
    assert "OnFailure=breezy-study-failed@%n.service" in active
    assert not any(line.startswith("SuccessExitStatus=") for line in active)
