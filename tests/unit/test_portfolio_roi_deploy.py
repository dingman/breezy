"""AUD-04 (docs/plans/backlog/AUDIT_2026-09-21/AUD-04-portfolio-roi-measurement.md
section 6 D1, section 7 step 5, section 8 AC#1). The `breezy-portfolio-roi`
systemd deploy surface: unit + timer + wrapper. Shape mirrors
`test_family_tally_v2_deploy.py`, hermetic -- this module parses unit and
wrapper TEXT directly, and never runs `systemctl`/`daemon-reload`.

`scripts/analysis/portfolio_roi_report.py` is built in a parallel,
disjoint-file commit and is deliberately NOT invoked here -- the wrapper's
own subprocess test stubs `python` so marker-gating and argv construction
are verified without it.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD_DIR = _REPO_ROOT / "deploy" / "systemd"
_SERVICE = _SYSTEMD_DIR / "breezy-portfolio-roi.service"
_TIMER = _SYSTEMD_DIR / "breezy-portfolio-roi.timer"
_WRAPPER = _SYSTEMD_DIR / "portfolio-roi-run.sh"

_PERMITTED_ENV_FILES = frozenset({"%h/.config/breezy/alerts.env"})
_FORBIDDEN_ENV_SUBSTRINGS = ("breezy-trade.env", "polymarket.env", "operator.env")


def _directive_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if not line.strip().startswith("#")]


def _directive_value(text: str, directive: str) -> str | None:
    prefix = f"{directive}="
    for line in _directive_lines(text):
        if line.startswith(prefix):
            return line[len(prefix) :]
    return None


def test_unit_and_timer_and_wrapper_exist() -> None:
    assert _SERVICE.is_file()
    assert _TIMER.is_file()
    assert _WRAPPER.is_file()


def test_wrapper_is_executable_and_valid_bash() -> None:
    assert os.access(_WRAPPER, os.X_OK)
    result = subprocess.run(
        ["bash", "-n", str(_WRAPPER)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_service_is_a_oneshot_with_no_restart_and_no_install() -> None:
    text = _SERVICE.read_text()
    lines = _directive_lines(text)
    assert "Type=oneshot" in lines
    assert not any(line.startswith("Restart=") for line in lines)
    assert not any(line == "[Install]" for line in lines)


def test_timer_declares_install_wanted_by_timers_target() -> None:
    text = _TIMER.read_text()
    assert "[Install]" in text
    assert "WantedBy=timers.target" in _directive_lines(text)


def test_timer_fires_at_1740_utc_and_is_persistent() -> None:
    text = _TIMER.read_text()
    assert "OnCalendar=*-*-* 17:40:00 UTC" in _directive_lines(text)
    assert "Persistent=true" in _directive_lines(text)


def test_timer_tick_is_after_the_1720_family_tally_tick() -> None:
    match = re.search(
        r"^OnCalendar=\S+\s+(\d{2}):(\d{2}):(\d{2})\s+UTC\s*$",
        _TIMER.read_text(),
        re.MULTILINE,
    )
    assert match is not None, f"{_TIMER.name} has no parseable OnCalendar="
    tick = _dt.time(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    assert tick > _dt.time(17, 20, 0)


def test_service_declares_memory_ceiling_in_the_light_unit_band() -> None:
    text = _SERVICE.read_text()
    assert _directive_value(text, "MemoryHigh") == "512M"
    assert _directive_value(text, "MemoryMax") == "1G"


def test_service_declares_umask_and_studies_slice() -> None:
    lines = _directive_lines(_SERVICE.read_text())
    assert "UMask=0077" in lines
    assert "Slice=breezy-studies.slice" in lines


def test_service_declares_onfailure_notifier() -> None:
    lines = _directive_lines(_SERVICE.read_text())
    assert "OnFailure=breezy-study-failed@%n.service" in lines


def test_service_declares_only_the_allowlisted_alert_env_file() -> None:
    lines = _directive_lines(_SERVICE.read_text())
    env_files = [
        line.removeprefix("EnvironmentFile=").lstrip("-")
        for line in lines
        if line.startswith("EnvironmentFile=")
    ]
    assert set(env_files) == _PERMITTED_ENV_FILES
    assert not any(
        forbidden in env_file for env_file in env_files for forbidden in _FORBIDDEN_ENV_SUBSTRINGS
    )


def test_service_exec_start_invokes_the_wrapper() -> None:
    lines = _directive_lines(_SERVICE.read_text())
    exec_start_lines = [line for line in lines if line.startswith("ExecStart=")]
    assert len(exec_start_lines) == 1
    assert exec_start_lines[0] == (
        "ExecStart=/home/jon/breezy/deploy/systemd/portfolio-roi-run.sh"
    )


def test_wrapper_names_the_shared_studies_lock_path_identically() -> None:
    lines = _WRAPPER.read_text().splitlines()
    assert 'LOCK="$LOCK_DIR/breezy-studies.lock"' in lines


def test_wrapper_exec_line_carries_no_stderr_redirect() -> None:
    lines = _WRAPPER.read_text().splitlines()
    exec_lines = [line for line in lines if line.strip().startswith('exec 9>>"$LOCK"')]
    assert len(exec_lines) == 1
    assert "2>>" not in exec_lines[0]


def test_wrapper_lock_preamble_precedes_the_first_interpreter_invocation() -> None:
    lines = _WRAPPER.read_text().splitlines()
    preamble_index = next(
        (i for i, line in enumerate(lines) if line.strip() == "unset POSIXLY_CORRECT"), None
    )
    assert preamble_index is not None
    invocation_index = next(
        (
            i
            for i, line in enumerate(lines)
            if re.match(r'^\s*(if\s+)?"\$PY"\s', line)
        ),
        None,
    )
    assert invocation_index is not None
    assert preamble_index < invocation_index


def test_wrapper_invokes_the_report_script_with_no_arguments() -> None:
    """The plan (section 7 steps 2-3) names portfolio_roi_report.py's loader
    FUNCTION signatures and output artefact paths but no CLI/argparse
    contract -- an ASSUMPTION this wrapper states in its own header. This
    test pins that assumption so a later CLI addition on the script side is
    a visible, reviewed change to this wrapper and this test together."""
    lines = _WRAPPER.read_text().splitlines()
    invocation_lines = [
        line
        for line in lines
        if '"$PY" "$REPO/scripts/analysis/portfolio_roi_report.py"' in line
    ]
    assert len(invocation_lines) == 1
    invocation = invocation_lines[0].strip()
    assert invocation.startswith('if "$PY" "$REPO/scripts/analysis/portfolio_roi_report.py"')
    # No extra token between the script path and the output redirection --
    # i.e. no CLI argument was smuggled onto this line.
    after_script = invocation.split("portfolio_roi_report.py\"", 1)[1]
    before_redirect = after_script.split(">>", 1)[0].strip()
    assert before_redirect == ""


def _run_wrapper(
    tmp_path: Path,
    *,
    stub_python: Path | None = None,
    create_marker: bool = True,
    xdg_runtime_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    out_dir = tmp_path / "derived"
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["BREEZY_LIVE_TALLY_OUTPUT_DIR"] = str(out_dir)
    if stub_python is not None:
        env["BREEZY_PORTFOLIO_ROI_PYTHON"] = str(stub_python)
    if xdg_runtime_dir is not None:
        env["XDG_RUNTIME_DIR"] = str(xdg_runtime_dir)
    if create_marker:
        stamp = _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
        (out_dir / f"score_live_trials_ok_{stamp}").touch()
    return subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_wrapper_exits_nonzero_and_never_invokes_the_report_when_marker_absent(
    tmp_path: Path,
) -> None:
    stub = tmp_path / "stub_python.sh"
    capture = tmp_path / "argv_capture.txt"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{capture}"\nexit 0\n')
    stub.chmod(0o755)

    result = _run_wrapper(tmp_path, stub_python=stub, create_marker=False)

    assert result.returncode != 0
    assert not capture.exists()


def test_wrapper_invokes_the_report_when_marker_present(tmp_path: Path) -> None:
    stub = tmp_path / "stub_python.sh"
    capture = tmp_path / "argv_capture.txt"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{capture}"\nexit 0\n')
    stub.chmod(0o755)

    result = _run_wrapper(tmp_path, stub_python=stub, create_marker=True)

    assert result.returncode == 0, result.stderr
    assert capture.exists()
    # The stub receives exactly ONE argv token -- the report script's own
    # path -- proving the wrapper passes no CLI flags of its own.
    assert capture.read_text().splitlines() == [
        str(_REPO_ROOT / "scripts" / "analysis" / "portfolio_roi_report.py")
    ]


def test_wrapper_reports_failure_from_the_stub_report_script(tmp_path: Path) -> None:
    stub = tmp_path / "stub_python.sh"
    stub.write_text("#!/usr/bin/env bash\nexit 1\n")
    stub.chmod(0o755)

    result = _run_wrapper(tmp_path, stub_python=stub)

    assert result.returncode == 1


def test_wrapper_skips_on_lock_contention_and_never_invokes_the_report(
    tmp_path: Path,
) -> None:
    import fcntl

    xdg_runtime_dir = tmp_path / "xdg-runtime"
    xdg_runtime_dir.mkdir(parents=True)
    lock_path = xdg_runtime_dir / "breezy-studies.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stub = tmp_path / "stub_python.sh"
        capture = tmp_path / "argv_capture.txt"
        stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{capture}"\nexit 0\n')
        stub.chmod(0o755)

        result = _run_wrapper(tmp_path, stub_python=stub, xdg_runtime_dir=xdg_runtime_dir)

        assert result.returncode == 0
        assert not capture.exists()
        log_path = tmp_path / "derived" / "portfolio_roi.log"
        assert log_path.is_file()
        assert "SKIPPED -- another study holds the studies lock" in log_path.read_text()
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)


# ---------------------------------------------------------------------------
# D6 fix: the unit ships with StandardOutput=journal, but every say() line
# and the report script's own stdout used to land in $LOG only -- never on
# this process's stdout -- so `journalctl --user -u breezy-portfolio-roi`
# showed nothing. These tests pin the fix: say() reaches both places, the
# script's OWN output never reaches stdout except for the single last
# `PORTFOLIO_ROI `-prefixed dimensionless summary line, and a
# currency-shaped summary line is withheld rather than echoed (defence in
# depth against a future currency-carrying journal_line()).
# ---------------------------------------------------------------------------


def test_say_lines_reach_both_the_log_file_and_stdout(tmp_path: Path) -> None:
    result = _run_wrapper(tmp_path, create_marker=False)

    assert result.returncode == 1
    log_path = tmp_path / "derived" / "portfolio_roi.log"
    marker_text = "PORTFOLIO ROI SKIPPED -- no score-live-trials success marker for"
    assert marker_text in log_path.read_text()
    assert marker_text in result.stdout


def test_successful_run_emits_only_the_last_portfolio_roi_line_to_stdout(
    tmp_path: Path,
) -> None:
    stub = tmp_path / "stub_python.sh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'noise before the summary'\n"
        "echo 'PORTFOLIO_ROI period=2026-01-01..2026-01-02 n_fills=1'\n"
        "echo 'some other diagnostic output'\n"
        "echo 'PORTFOLIO_ROI period=2026-01-03..2026-01-04 n_fills=2'\n"
        "exit 0\n"
    )
    stub.chmod(0o755)

    result = _run_wrapper(tmp_path, stub_python=stub)

    assert result.returncode == 0, result.stderr
    portfolio_roi_stdout_lines = [
        line for line in result.stdout.splitlines() if line.startswith("PORTFOLIO_ROI ")
    ]
    assert portfolio_roi_stdout_lines == ["PORTFOLIO_ROI period=2026-01-03..2026-01-04 n_fills=2"]
    # None of the script's other output lines -- including the EARLIER
    # PORTFOLIO_ROI-prefixed line -- ever reach stdout.
    assert "noise before the summary" not in result.stdout
    assert "some other diagnostic output" not in result.stdout
    assert "PORTFOLIO_ROI period=2026-01-01..2026-01-02 n_fills=1" not in result.stdout
    # But the full script output, including the noise, still lands in the
    # log for post-hoc debugging.
    log_text = (tmp_path / "derived" / "portfolio_roi.log").read_text()
    assert "noise before the summary" in log_text
    assert "some other diagnostic output" in log_text
    assert "PORTFOLIO_ROI period=2026-01-01..2026-01-02 n_fills=1" in log_text
    assert "PORTFOLIO_ROI period=2026-01-03..2026-01-04 n_fills=2" in log_text


def test_a_run_with_no_portfolio_roi_line_emits_none_to_stdout(tmp_path: Path) -> None:
    stub = tmp_path / "stub_python.sh"
    stub.write_text("#!/usr/bin/env bash\necho 'unrelated output'\nexit 0\n")
    stub.chmod(0o755)

    result = _run_wrapper(tmp_path, stub_python=stub)

    assert result.returncode == 0, result.stderr
    assert not any(line.startswith("PORTFOLIO_ROI ") for line in result.stdout.splitlines())


def test_a_currency_like_summary_line_is_withheld_from_stdout(tmp_path: Path) -> None:
    stub = tmp_path / "stub_python.sh"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'PORTFOLIO_ROI period=2026-01-01..2026-01-02 total=$5.00'\n"
        "exit 0\n"
    )
    stub.chmod(0o755)

    result = _run_wrapper(tmp_path, stub_python=stub)

    assert result.returncode == 0, result.stderr
    assert "PORTFOLIO ROI SUMMARY WITHHELD -- currency-like token" in result.stdout
    assert "total=" not in result.stdout
    assert "5.00" not in result.stdout
    # The real line is still captured to the log for debugging.
    assert "total=" in (tmp_path / "derived" / "portfolio_roi.log").read_text()


def test_a_failed_report_run_emits_the_failed_line_to_stdout_and_exits_nonzero(
    tmp_path: Path,
) -> None:
    stub = tmp_path / "stub_python.sh"
    stub.write_text("#!/usr/bin/env bash\necho 'boom' >&2\nexit 1\n")
    stub.chmod(0o755)

    result = _run_wrapper(tmp_path, stub_python=stub)

    assert result.returncode == 1
    assert "PORTFOLIO ROI REPORT FAILED" in result.stdout
    assert "boom" in (tmp_path / "derived" / "portfolio_roi.log").read_text()


def test_lock_contention_skip_line_reaches_stdout_with_exit_zero(tmp_path: Path) -> None:
    import fcntl

    xdg_runtime_dir = tmp_path / "xdg-runtime"
    xdg_runtime_dir.mkdir(parents=True)
    lock_path = xdg_runtime_dir / "breezy-studies.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = _run_wrapper(tmp_path, xdg_runtime_dir=xdg_runtime_dir)

        assert result.returncode == 0
        assert "SKIPPED -- another study holds the studies lock" in result.stdout
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
