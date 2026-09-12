"""RED/GREEN coverage for ``breezy.runtime.process_probe`` (SP-6 AM-11,
rows 19/19b)."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from breezy.runtime.process_probe import (
    PidProbe,
    ProbeOutcome,
    find_pid_by_argv,
    pid_cmdline_matches,
    probe_pid_by_argv,
)


def _fake_runner(
    *, stdout: str = "", raise_exc: BaseException | None = None
) -> Callable[..., subprocess.CompletedProcess[str]]:
    def _runner(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if raise_exc is not None:
            raise raise_exc
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    return _runner


# --------------------------------------------------------------------------
# row 19 -- probe_pid_by_argv / find_pid_by_argv
# --------------------------------------------------------------------------


def test_a_timeout_is_reported_as_failed_not_absent() -> None:
    runner = _fake_runner(raise_exc=subprocess.TimeoutExpired(cmd="pgrep", timeout=5))

    result = probe_pid_by_argv("breezy-trade$", runner=runner)

    assert result == PidProbe(ProbeOutcome.FAILED, None)


def test_an_oserror_is_reported_as_failed_not_absent() -> None:
    """SEC2-M1: the ENOMEM `fork` case -- `subprocess.run` raises
    `OSError`, and this must never be read as an absence."""
    runner = _fake_runner(raise_exc=OSError("fork failed: Cannot allocate memory"))

    result = probe_pid_by_argv("breezy-trade$", runner=runner)

    assert result == PidProbe(ProbeOutcome.FAILED, None)


def test_no_match_is_absent() -> None:
    runner = _fake_runner(stdout="")

    result = probe_pid_by_argv("breezy-trade$", runner=runner)

    assert result == PidProbe(ProbeOutcome.ABSENT, None)


def test_a_match_is_found_with_the_pid() -> None:
    runner = _fake_runner(stdout="12345\n")

    result = probe_pid_by_argv("breezy-trade$", runner=runner)

    assert result == PidProbe(ProbeOutcome.FOUND, 12345)


def test_find_pid_by_argv_preserves_todays_none_for_both_cases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from breezy.runtime import process_probe

    monkeypatch.setattr(
        process_probe,
        "probe_pid_by_argv",
        lambda anchor, **kwargs: PidProbe(ProbeOutcome.ABSENT, None),
    )
    assert find_pid_by_argv("breezy-trade$") is None

    monkeypatch.setattr(
        process_probe,
        "probe_pid_by_argv",
        lambda anchor, **kwargs: PidProbe(ProbeOutcome.FAILED, None),
    )
    assert find_pid_by_argv("breezy-trade$") is None

    monkeypatch.setattr(
        process_probe,
        "probe_pid_by_argv",
        lambda anchor, **kwargs: PidProbe(ProbeOutcome.FOUND, 999),
    )
    assert find_pid_by_argv("breezy-trade$") == 999


# --------------------------------------------------------------------------
# row 19b -- pid_cmdline_matches (AM-13)
# --------------------------------------------------------------------------


def _write_cmdline(proc_root: Path, pid: int, *args: str) -> None:
    pid_dir = proc_root / str(pid)
    pid_dir.mkdir(parents=True, exist_ok=True)
    (pid_dir / "cmdline").write_bytes(("\x00".join(args) + "\x00").encode())


def test_pid_cmdline_matches_confirms_a_live_anchor(tmp_path: Path) -> None:
    _write_cmdline(tmp_path, 111, "/home/jon/breezy/.venv/bin/breezy-trade")

    assert pid_cmdline_matches(111, "breezy-trade$", proc_root=tmp_path) is True


def test_pid_cmdline_matches_is_false_for_a_different_process(tmp_path: Path) -> None:
    _write_cmdline(tmp_path, 222, "/usr/bin/some-other-process")

    assert pid_cmdline_matches(222, "breezy-trade$", proc_root=tmp_path) is False


def test_pid_cmdline_matches_is_none_when_proc_is_unreadable(tmp_path: Path) -> None:
    assert pid_cmdline_matches(999999, "breezy-trade$", proc_root=tmp_path) is None


def test_pid_cmdline_matches_never_forks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_cmdline(tmp_path, 333, "breezy-trade")

    def _bomb(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("pid_cmdline_matches must never fork a subprocess")

    monkeypatch.setattr(subprocess, "run", _bomb)
    monkeypatch.setattr(subprocess, "Popen", _bomb)

    assert pid_cmdline_matches(333, "breezy-trade$", proc_root=tmp_path) is True
