"""RED-first suite for the nightly `breezy-exit-window-study` deploy --
`deploy/systemd/exit-window-study-run.sh` +
`breezy-exit-window-study.service`/`.timer`, mirroring
`test_position_monitor_report_deploy.py`'s idiom: the wrapper's own `$PY` is
stubbed with a shell script that dispatches on the invocation shape, so argv
and failure propagation are pinned against a stub, never the real
`current_rung_hold_exit_window_study.py` CLI.

One dispatch branch (the sqlite3 read-only backup step) execs the REAL
Python interpreter running these tests (`sys.executable`) instead of faking
success, and the "study" branch reads the copy's own marker row back through
that same real interpreter before exiting -- so
`test_backup_step_produces_a_real_readable_sqlite_copy` proves the wrapper's
own inline backup code actually copies data (read at the moment the study
CLI would see it, before the wrapper's own cleanup trap removes the temp
dir), not just that it invoked *something*.

NOTE on the `REPO=` literal (worktree portability): like every sibling
wrapper, `exit-window-study-run.sh` hardcodes `REPO=/home/jon/breezy` -- the
deployed production tree, never the checkout this test file happens to run
from. Assertions about the invoked script's own path are therefore built
from the WRAPPER's own `REPO=` line (`_wrapper_repo_literal`), never from
this file's `_REPO_ROOT` (which is `/home/jon/breezy-ilp` under this
worktree) -- the same accepted deviation noted for
`test_score_live_trials_deploy.py`.
"""

from __future__ import annotations

import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD_DIR = _REPO_ROOT / "deploy" / "systemd"
_WRAPPER = _SYSTEMD_DIR / "exit-window-study-run.sh"
_SERVICE = _SYSTEMD_DIR / "breezy-exit-window-study.service"
_TIMER = _SYSTEMD_DIR / "breezy-exit-window-study.timer"
_README = _SYSTEMD_DIR / "README.md"

_REPO_ASSIGNMENT_RE = re.compile(r"^REPO=(\S+)\s*$", re.MULTILINE)

_LIVE_STATE_DB_ENV_LITERAL = "/home/jon/.local/share/breezy/state/exec_polymarket_us.sqlite"

_READ_MARKER_PY = """\
import sqlite3
import sys

try:
    conn = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
    rows = conn.execute("SELECT value FROM marker").fetchall()
    print(",".join(row[0] for row in rows))
except Exception as exc:  # noqa: BLE001 -- test helper, reports any failure as content
    print(f"ERROR:{exc}")
"""


def _wrapper_repo_literal() -> str:
    """The wrapper's own hardcoded `REPO=` value (never this test's own
    checkout root -- see the module docstring)."""
    match = _REPO_ASSIGNMENT_RE.search(_WRAPPER.read_text())
    assert match is not None, "exit-window-study-run.sh has no REPO= assignment"
    return match.group(1)


def _make_state_db(path: Path, *, marker: str = "seed") -> Path:
    """A real, tiny sqlite3 file at `path` with one identifiable row, so a
    copy of it can be verified by content rather than by mere existence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE marker (value TEXT NOT NULL)")
        conn.execute("INSERT INTO marker (value) VALUES (?)", (marker,))
        conn.commit()
    finally:
        conn.close()
    return path


def _make_stub(tmp_path: Path, *, study_exit: int = 0) -> tuple[Path, Path]:
    """A dispatching stub `$PY`: recognises the study CLI invocation shape
    and the inline sqlite3-backup invocation shape.

    The backup branch execs the REAL interpreter running this test
    (`sys.executable`), so the backup step genuinely copies data. The study
    branch reads the `--state-db` copy's own marker row back through that
    same real interpreter and logs it as `CONTENT <value>` BEFORE exiting --
    this happens while the wrapper's temp dir still exists (the
    cleanup trap fires only after this process returns), so it observes
    exactly what the real study CLI would have read. Logs every call to
    `argv_log`. Returns (stub_path, argv_log_path).
    """
    argv_log = tmp_path / "argv_log.txt"
    read_marker_script = tmp_path / "read_marker.py"
    read_marker_script.write_text(_READ_MARKER_PY)
    real_python = sys.executable
    # `$*` is flattened to one line (embedded newlines -> spaces) before
    # logging: the real wrapper's own inline python is a multi-line `-c`
    # argument, and an un-flattened echo would split ONE call across many
    # log lines, breaking the one-call-per-line contract every assertion
    # below relies on.
    script = f"""#!/usr/bin/env bash
ARGV_LOG={argv_log!s}
FLAT=$(printf '%s' "$*" | tr '\\n' ' ')
case "$*" in
  *"current_rung_hold_exit_window_study.py"*)
    echo "STUDY $FLAT" >> "$ARGV_LOG"
    STATE_DB_ARG=""
    PREV=""
    for arg in "$@"; do
      if [ "$PREV" = "--state-db" ]; then
        STATE_DB_ARG="$arg"
      fi
      PREV="$arg"
    done
    CONTENT=$({real_python!s} {read_marker_script!s} "$STATE_DB_ARG" 2>&1)
    echo "CONTENT $CONTENT" >> "$ARGV_LOG"
    exit {study_exit}
    ;;
  *"sqlite3.connect"*)
    echo "BACKUP $FLAT" >> "$ARGV_LOG"
    exec {real_python!s} "$@"
    ;;
  *)
    echo "UNKNOWN $FLAT" >> "$ARGV_LOG"
    exit 0
    ;;
esac
"""
    stub = tmp_path / "stub_python.sh"
    stub.write_text(script)
    stub.chmod(0o755)
    return stub, argv_log


def _run_wrapper(
    tmp_path: Path,
    *,
    stub_python: Path | None,
    state_db: Path | None,
    set_state_db_env: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    # Redirect the flock's runtime dir away from the real host
    # `/run/user/1000` -- never contend with (or depend on) a real study's
    # lock file.
    xdg_runtime = tmp_path / "xdg_runtime"
    xdg_runtime.mkdir(parents=True, exist_ok=True)
    env["XDG_RUNTIME_DIR"] = str(xdg_runtime)
    env["BREEZY_LIVE_TALLY_OUTPUT_DIR"] = str(tmp_path / "derived")
    if set_state_db_env:
        assert state_db is not None
        env["POLYMARKET_US_EXEC_STATE_DB"] = str(state_db)
    else:
        env.pop("POLYMARKET_US_EXEC_STATE_DB", None)
    if stub_python is not None:
        env["BREEZY_EXIT_WINDOW_STUDY_PYTHON"] = str(stub_python)
    return subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _calls(argv_log: Path, prefix: str) -> list[str]:
    if not argv_log.exists():
        return []
    return [line for line in argv_log.read_text().splitlines() if line.startswith(prefix)]


def test_wrapper_exists_and_is_executable() -> None:
    assert _WRAPPER.exists()
    assert os.access(_WRAPPER, os.X_OK)


def test_wrapper_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(_WRAPPER)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_wrapper_requires_state_db_env_var(tmp_path: Path) -> None:
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub, state_db=None, set_state_db_env=False)
    assert result.returncode != 0
    assert not _calls(argv_log, "BACKUP")
    assert not _calls(argv_log, "STUDY")


def test_study_argv_pinned_stations_since_day_obs_source_and_run_stamp(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path / "state" / "exec_polymarket_us.sqlite")
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub, state_db=state_db)
    assert result.returncode == 0, result.stderr

    calls = _calls(argv_log, "STUDY")
    assert len(calls) == 1
    call = calls[0]

    repo = _wrapper_repo_literal()
    assert f"{repo}/scripts/analysis/current_rung_hold_exit_window_study.py" in call
    assert "--stations LAX MDW MIA SFO" in call
    assert "--since-climate-day 2026-09-05" in call
    assert "--obs-source fetch" in call
    assert re.search(r"--run-stamp \d{4}-\d{2}-\d{2}_nightly", call) is not None
    assert "--depth-source" not in call  # default depth-source: let the CLI auto-select


def test_state_db_copy_is_used_never_the_live_path(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path / "state" / "exec_polymarket_us.sqlite")
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub, state_db=state_db)
    assert result.returncode == 0, result.stderr

    backup_calls = _calls(argv_log, "BACKUP")
    assert len(backup_calls) == 1
    assert str(state_db) in backup_calls[0]

    study_call = _calls(argv_log, "STUDY")[0]
    match = re.search(r"--state-db (\S+)", study_call)
    assert match is not None
    state_db_arg = match.group(1)
    assert state_db_arg != str(state_db)
    assert "breezy-exit-window-study" in state_db_arg  # inside the wrapper's own mktemp dir


def test_backup_step_produces_a_real_readable_sqlite_copy(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path / "state" / "exec_polymarket_us.sqlite", marker="canary")
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub, state_db=state_db)
    assert result.returncode == 0, result.stderr

    content_lines = _calls(argv_log, "CONTENT")
    assert len(content_lines) == 1
    assert content_lines[0] == "CONTENT canary"

    # The cleanup trap fires only after the study CLI call above returns --
    # by the time this process exits, its own temp dir must be gone.
    study_call = _calls(argv_log, "STUDY")[0]
    match = re.search(r"--state-db (\S+)", study_call)
    assert match is not None
    assert not Path(match.group(1)).parent.exists()


def test_backup_failure_wrapper_exits_nonzero_before_invoking_the_study_cli(
    tmp_path: Path,
) -> None:
    """A state-db path that does not exist makes the REAL sqlite3 backup
    branch fail (`mode=ro` on a missing file raises) -- the wrapper must
    surface that as a failure and never reach the study CLI."""
    missing_state_db = tmp_path / "state" / "does_not_exist.sqlite"
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub, state_db=missing_state_db)
    assert result.returncode != 0
    assert _calls(argv_log, "BACKUP")
    assert not _calls(argv_log, "STUDY")
    log_text = (tmp_path / "derived" / "exit_window_study.log").read_text()
    assert "SKIPPED" in log_text


def test_study_failure_wrapper_exits_nonzero_and_logs(tmp_path: Path) -> None:
    state_db = _make_state_db(tmp_path / "state" / "exec_polymarket_us.sqlite")
    stub, argv_log = _make_stub(tmp_path, study_exit=1)
    result = _run_wrapper(tmp_path, stub_python=stub, state_db=state_db)
    assert result.returncode != 0
    assert len(_calls(argv_log, "STUDY")) == 1
    log_text = (tmp_path / "derived" / "exit_window_study.log").read_text()
    assert "FAILED" in log_text


def test_lock_contention_skips_without_invoking_python(tmp_path: Path) -> None:
    import fcntl

    state_db = _make_state_db(tmp_path / "state" / "exec_polymarket_us.sqlite")
    stub, argv_log = _make_stub(tmp_path)
    xdg_runtime = tmp_path / "xdg_runtime_locked"
    xdg_runtime.mkdir(parents=True, exist_ok=True)
    lock_path = xdg_runtime / "breezy-studies.lock"
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    fcntl.flock(lock_fd, fcntl.LOCK_EX)
    try:
        env = dict(os.environ)
        home = tmp_path / "home"
        home.mkdir(parents=True, exist_ok=True)
        env["HOME"] = str(home)
        env["XDG_RUNTIME_DIR"] = str(xdg_runtime)
        env["BREEZY_LIVE_TALLY_OUTPUT_DIR"] = str(tmp_path / "derived")
        env["POLYMARKET_US_EXEC_STATE_DB"] = str(state_db)
        env["BREEZY_EXIT_WINDOW_STUDY_PYTHON"] = str(stub)
        result = subprocess.run(
            ["bash", str(_WRAPPER)],
            cwd=_REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert not argv_log.exists()
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


def test_wrapper_names_the_shared_studies_lock_path_identically_to_k1() -> None:
    k1_wrapper = _SYSTEMD_DIR / "k1-daily-run.sh"
    mine = _WRAPPER.read_text()
    theirs = k1_wrapper.read_text()
    assert 'LOCK="$LOCK_DIR/breezy-studies.lock"' in mine
    assert 'LOCK="$LOCK_DIR/breezy-studies.lock"' in theirs


def test_lock_preamble_skip_not_kill_and_infra_failure_exit_codes() -> None:
    text = _WRAPPER.read_text()
    assert "flock -n 9" in text
    assert "exit 75" in text
    assert re.search(r"another study holds the studies lock.*exit 0", text) is not None


def test_wrapper_never_enables_posix_mode() -> None:
    text = _WRAPPER.read_text()
    assert "unset POSIXLY_CORRECT" in text
    non_comment_lines = [line for line in text.splitlines() if not line.strip().startswith("#")]
    assert not any("set -o posix" in line for line in non_comment_lines)


def test_exit_window_study_unit_pair_exists_and_wires_to_wrapper() -> None:
    assert _SERVICE.exists()
    assert _TIMER.exists()

    service_text = _SERVICE.read_text()
    exec_lines = [line for line in service_text.splitlines() if line.startswith("ExecStart=")]
    assert len(exec_lines) == 1
    assert exec_lines[0].strip().endswith("exit-window-study-run.sh")
    assert "TimeoutStartSec=" in service_text
    assert "EnvironmentFile=" not in service_text
    assert f"Environment=POLYMARKET_US_EXEC_STATE_DB={_LIVE_STATE_DB_ENV_LITERAL}" in service_text
    assert "Slice=breezy-studies.slice" in service_text
    assert "Type=oneshot" in service_text
    assert "WorkingDirectory=/home/jon/breezy" in service_text
    assert not any(
        line.strip() == "[Install]" for line in service_text.splitlines()
    ), "the service is started BY the timer and must carry no [Install] section"

    timer_text = _TIMER.read_text()
    assert "Unit=breezy-exit-window-study.service" in timer_text
    assert "OnCalendar=*-*-* 15:20:00 UTC" in timer_text
    assert "Persistent=true" in timer_text
    assert "[Install]" in timer_text
    assert "WantedBy=timers.target" in timer_text


def test_state_db_env_literal_is_byte_identical_to_sibling_services() -> None:
    sibling = (_SYSTEMD_DIR / "breezy-score-live-trials.service").read_text()
    mine = _SERVICE.read_text()
    assert f"Environment=POLYMARKET_US_EXEC_STATE_DB={_LIVE_STATE_DB_ENV_LITERAL}" in sibling
    assert f"Environment=POLYMARKET_US_EXEC_STATE_DB={_LIVE_STATE_DB_ENV_LITERAL}" in mine


def test_service_carries_a_modest_memory_ceiling_below_the_heavy_studies() -> None:
    text = _SERVICE.read_text()
    high_match = re.search(r"^MemoryHigh=(\d+)([KMGT]?)$", text, re.MULTILINE)
    max_match = re.search(r"^MemoryMax=(\d+)([KMGT]?)$", text, re.MULTILINE)
    assert high_match is not None
    assert max_match is not None

    multipliers = {"": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}

    def _bytes(match: re.Match[str]) -> float:
        number, suffix = match.groups()
        return float(number) * multipliers[suffix]

    high_bytes = _bytes(high_match)
    max_bytes = _bytes(max_match)
    heavy_floor_bytes = 12 * multipliers["G"]  # k1/mb/offer-gate MemoryHigh
    assert 0 < high_bytes < max_bytes
    assert max_bytes == 2 * multipliers["G"]
    assert max_bytes < heavy_floor_bytes


def test_timer_does_not_clash_with_any_sibling_hour_minute_tick() -> None:
    my_tick = "15:20:00 UTC"
    for other in _SYSTEMD_DIR.glob("*.timer"):
        if other == _TIMER:
            continue
        text = other.read_text()
        assert f"OnCalendar=*-*-* {my_tick}" not in text, other


def test_readme_documents_the_new_unit() -> None:
    text = _README.read_text()
    assert "breezy-exit-window-study" in text
    assert "exit-window-study-run.sh" in text
