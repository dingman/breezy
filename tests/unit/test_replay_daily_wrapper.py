"""Execution-based tests for `deploy/systemd/replay-daily-run.sh` (AUD-09b
review fix 3, HIGH). Mirrors `test_score_live_trials_deploy.py`'s own idiom:
`$PY` and `systemctl` are both stubbed shell scripts dispatching on argv
shape, so the wrapper's own plumbing (exit codes, which script it calls,
under which conditions) is pinned without ever running the real census or
driver.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WRAPPER = _REPO_ROOT / "deploy" / "systemd" / "replay-daily-run.sh"


def _systemctl_stub(tmp_path: Path, *, environment_line: str = "", exit_code: int = 0) -> Path:
    stub = tmp_path / "systemctl-stub.sh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' {shlex.quote(environment_line)}\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def _python_stub(tmp_path: Path, *, report_skip_exit_code: int = 0) -> tuple[Path, Path]:
    """A `$PY` stub that logs every invocation shape -- the census, the
    runner's real path, and `--report-skip` are all dispatched here, never
    a real script. `report_skip_exit_code` models the skip recorder
    itself crashing (review follow-up fix)."""
    argv_log = tmp_path / "argv_log.txt"
    stub = tmp_path / "python-stub.sh"
    stub.write_text(
        f"""#!/usr/bin/env bash
ARGV_LOG={shlex.quote(str(argv_log))}
case "$*" in
  *"--report-skip"*)
    echo "REPORT_SKIP $*" >> "$ARGV_LOG"
    exit {report_skip_exit_code}
    ;;
  *"replay_sufficiency_census.py"*)
    echo "CENSUS $*" >> "$ARGV_LOG"
    exit 0
    ;;
  *"replay_daily_runner.py"*)
    echo "RUNNER $*" >> "$ARGV_LOG"
    exit 0
    ;;
  *)
    echo "UNKNOWN $*" >> "$ARGV_LOG"
    exit 0
    ;;
esac
""",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub, argv_log


def _run_wrapper(
    tmp_path: Path,
    *,
    python_stub: Path,
    systemctl_stub: Path,
    hold_lock: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    runtime_dir = tmp_path / "xdg-runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    env["XDG_RUNTIME_DIR"] = str(runtime_dir)
    env["BREEZY_LIVE_TALLY_OUTPUT_DIR"] = str(tmp_path / "derived")
    env["BREEZY_REPLAY_DAILY_PYTHON"] = str(python_stub)
    env["BREEZY_SYSTEMCTL"] = str(systemctl_stub)
    env["BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG"] = str(tmp_path / "quote_catalog")
    env["BREEZY_WEATHER_CATALOG_ROOT"] = str(tmp_path / "weather_catalog")
    env["BREEZY_REPLAY_DAILY_OUTPUT_ROOT"] = str(tmp_path / "out")
    # Never depend on the PRODUCTION tree's `deploy/families/` (the
    # wrapper's own `$REPO` is hardcoded to `/home/jon/breezy`) -- this
    # worktree's own manifests are what the fixture below asserts against.
    env["BREEZY_REPLAY_DAILY_FAMILIES_DIR"] = str(_REPO_ROOT / "deploy" / "families")

    lock_holder = None
    if hold_lock:
        lock_path = runtime_dir / "breezy-studies.lock"
        lock_holder = subprocess.Popen(
            ["/usr/bin/flock", str(lock_path), "sleep", "5"],
        )
        # Give the holder a moment to actually acquire the flock before the
        # wrapper races it -- avoids a rare TOCTOU flake on a loaded host.
        time.sleep(0.3)
    try:
        return subprocess.run(
            ["bash", str(_WRAPPER)],
            cwd=_REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    finally:
        if lock_holder is not None:
            lock_holder.wait(timeout=10)


def test_wrapper_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(_WRAPPER)], capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_systemctl_failure_exits_nonzero_never_a_benign_skip(tmp_path: Path) -> None:
    """Review fix 3: a `systemctl show` FAILURE is an infra problem, not
    "no family armed" -- it must exit non-zero so `OnFailure=` fires."""
    python_stub, argv_log = _python_stub(tmp_path)
    systemctl_stub = _systemctl_stub(tmp_path, exit_code=1)
    result = _run_wrapper(tmp_path, python_stub=python_stub, systemctl_stub=systemctl_stub)
    assert result.returncode != 0
    assert not argv_log.exists() or "REPORT_SKIP" not in argv_log.read_text()


def test_no_armed_family_exits_zero_and_records_a_skip(tmp_path: Path) -> None:
    python_stub, argv_log = _python_stub(tmp_path)
    systemctl_stub = _systemctl_stub(tmp_path, environment_line="")
    result = _run_wrapper(tmp_path, python_stub=python_stub, systemctl_stub=systemctl_stub)
    assert result.returncode == 0, result.stderr
    log_text = argv_log.read_text()
    assert "REPORT_SKIP" in log_text
    assert "NO_ARMED_FAMILY" in log_text
    assert "CENSUS" not in log_text
    assert "--report-skip" not in [
        line for line in log_text.splitlines() if line.startswith("RUNNER")
    ]


def test_lock_contention_exits_zero_and_records_a_skip(tmp_path: Path) -> None:
    python_stub, argv_log = _python_stub(tmp_path)
    systemctl_stub = _systemctl_stub(
        tmp_path, environment_line="Environment=BREEZY_SENDING_FAMILY_ID=pm_us_crh_v4",
    )
    result = _run_wrapper(
        tmp_path, python_stub=python_stub, systemctl_stub=systemctl_stub, hold_lock=True,
    )
    assert result.returncode == 0, result.stderr
    log_text = argv_log.read_text()
    assert "REPORT_SKIP" in log_text
    assert "LOCK_CONTENTION" in log_text
    assert "CENSUS" not in log_text


def test_a_crashing_skip_recorder_exits_nonzero_on_lock_contention(tmp_path: Path) -> None:
    """Coordinator follow-up: `report_skip()` used to end in `|| true`, so
    a crashing recorder (e.g. an OSError on the state file) left the skip
    unrecorded AND the wrapper exiting 0 -- nothing ever escalates. The
    recorder failing must itself be loud."""
    python_stub, argv_log = _python_stub(tmp_path, report_skip_exit_code=1)
    systemctl_stub = _systemctl_stub(
        tmp_path, environment_line="Environment=BREEZY_SENDING_FAMILY_ID=pm_us_crh_v4",
    )
    result = _run_wrapper(
        tmp_path, python_stub=python_stub, systemctl_stub=systemctl_stub, hold_lock=True,
    )
    assert result.returncode != 0
    log_text = (tmp_path / "derived" / "replay_daily.log").read_text()
    assert "skip recorder FAILED" in log_text
    assert "REPORT_SKIP" in argv_log.read_text()


def test_a_crashing_skip_recorder_exits_nonzero_on_no_armed_family(tmp_path: Path) -> None:
    python_stub, argv_log = _python_stub(tmp_path, report_skip_exit_code=1)
    systemctl_stub = _systemctl_stub(tmp_path, environment_line="")
    result = _run_wrapper(tmp_path, python_stub=python_stub, systemctl_stub=systemctl_stub)
    assert result.returncode != 0
    log_text = (tmp_path / "derived" / "replay_daily.log").read_text()
    assert "skip recorder FAILED" in log_text
    assert "REPORT_SKIP" in argv_log.read_text()


def test_a_normal_run_invokes_the_census_then_the_runner_and_no_skip(tmp_path: Path) -> None:
    python_stub, argv_log = _python_stub(tmp_path)
    systemctl_stub = _systemctl_stub(
        tmp_path, environment_line="Environment=BREEZY_SENDING_FAMILY_ID=pm_us_crh_v4",
    )
    result = _run_wrapper(tmp_path, python_stub=python_stub, systemctl_stub=systemctl_stub)
    assert result.returncode == 0, result.stderr
    log_text = argv_log.read_text()
    assert "CENSUS" in log_text
    assert "RUNNER" in log_text
    assert "REPORT_SKIP" not in log_text
