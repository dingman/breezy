"""RED-first suite for INC-6 deploy of
`docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md` Sec 4/6 -- the new
15:00 UTC `breezy-position-monitor-report` unit pair +
`deploy/systemd/position-monitor-report-run.sh`. Mirrors
`test_score_live_trials_deploy.py`'s idiom: the wrapper's own `$PY` is
stubbed with a shell script that dispatches on the invocation shape, so
argv and failure propagation are pinned against a stub, never the real
`position_monitor_nightly_report.py` CLI.

NOTE on the `REPO=` literal (worktree portability): like every sibling
wrapper (`score-live-trials-run.sh`, `family-tally-v2-run.sh`,
`k1-daily-run.sh`), `position-monitor-report-run.sh` hardcodes
`REPO=/home/jon/breezy` -- the deployed production tree, never the checkout
this test file happens to run from. Assertions about the invoked script's
own path are therefore built from the WRAPPER's own `REPO=` line
(`_wrapper_repo_literal`), never from this file's `_REPO_ROOT` (which is
`/home/jon/breezy-ilp` under this worktree) -- the same accepted deviation
noted for `test_score_live_trials_deploy.py`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD_DIR = _REPO_ROOT / "deploy" / "systemd"
_WRAPPER = _SYSTEMD_DIR / "position-monitor-report-run.sh"
_README = _SYSTEMD_DIR / "README.md"

_REPO_ASSIGNMENT_RE = re.compile(r"^REPO=(\S+)\s*$", re.MULTILINE)


def _wrapper_repo_literal() -> str:
    """The wrapper's own hardcoded `REPO=` value (never this test's own
    checkout root -- see the module docstring)."""
    match = _REPO_ASSIGNMENT_RE.search(_WRAPPER.read_text())
    assert match is not None, "position-monitor-report-run.sh has no REPO= assignment"
    return match.group(1)


def _make_stub(
    tmp_path: Path, *, report_exit: int = 0
) -> tuple[Path, Path]:
    """A dispatching stub `$PY`: recognises the report CLI invocation shape,
    logs it to `argv_log`, and exits `report_exit`. Returns
    (stub_path, argv_log_path)."""
    argv_log = tmp_path / "argv_log.txt"
    script = f"""#!/usr/bin/env bash
ARGV_LOG={argv_log!s}
case "$*" in
  *"position_monitor_nightly_report.py"*)
    echo "REPORT $*" >> "$ARGV_LOG"
    exit {report_exit}
    ;;
  *)
    echo "UNKNOWN $*" >> "$ARGV_LOG"
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
    env["BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG"] = str(
        tmp_path / "catalog" / "quote_tape" / "polymarket_us"
    )
    env["BREEZY_SCORED_TRIALS_DIR"] = str(tmp_path / "scored_trials")
    env["BREEZY_LIVE_TALLY_OUTPUT_DIR"] = str(tmp_path / "derived")
    if stub_python is not None:
        env["BREEZY_POSITION_MONITOR_REPORT_PYTHON"] = str(stub_python)
    return subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _summaries_dir(tmp_path: Path) -> Path:
    catalog_root = tmp_path / "catalog" / "quote_tape" / "polymarket_us"
    return catalog_root.parent / "monitor" / "summaries"


def _report_calls(argv_log: Path) -> list[str]:
    if not argv_log.exists():
        return []
    return [line for line in argv_log.read_text().splitlines() if line.startswith("REPORT")]


def test_wrapper_exists_and_is_executable() -> None:
    assert _WRAPPER.exists()
    assert os.access(_WRAPPER, os.X_OK)


def test_wrapper_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(_WRAPPER)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_report_argv_pinned_summaries_scored_trials_and_output_paths(tmp_path: Path) -> None:
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode == 0, result.stderr

    calls = _report_calls(argv_log)
    assert len(calls) == 1
    call = calls[0]

    repo = _wrapper_repo_literal()
    assert f"{repo}/scripts/analysis/position_monitor_nightly_report.py" in call
    assert f"--summaries-dir {_summaries_dir(tmp_path)}" in call
    assert f"--scored-trials-dir {tmp_path / 'scored_trials'}" in call
    assert "--out" in call
    assert "--markdown" in call
    assert "position_monitor_report_" in call
    assert "--corpus-summary" not in call


def test_summaries_dir_matches_composition_derivation_from_catalog_root(tmp_path: Path) -> None:
    # composition.py:490/567 -- monitor_root = catalog_root.parent / "monitor";
    # summaries_dir = monitor_root / "summaries". Never a second,
    # independently hand-maintained literal.
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode == 0, result.stderr
    call = _report_calls(argv_log)[0]
    catalog_root = tmp_path / "catalog" / "quote_tape" / "polymarket_us"
    expected_summaries = catalog_root.parent / "monitor" / "summaries"
    assert str(expected_summaries) in call
    assert str(expected_summaries).endswith("quote_tape/monitor/summaries")


def test_corpus_summary_flag_included_as_the_newest_report_when_corpus_dir_present(
    tmp_path: Path,
) -> None:
    stub, argv_log = _make_stub(tmp_path)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    corpus_dir = home / ".local" / "share" / "breezy" / "derived" / "hypothetical_hold_corpus"
    corpus_dir.mkdir(parents=True, exist_ok=True)
    older = corpus_dir / "hypothetical_hold_corpus_report_1000000000000000000.json"
    newer = corpus_dir / "hypothetical_hold_corpus_report_2000000000000000000.json"
    older.write_text(json.dumps({"usable_station_days": 3}))
    newer.write_text(json.dumps({"usable_station_days": 9}))

    env = dict(os.environ)
    env["HOME"] = str(home)
    xdg_runtime = tmp_path / "xdg_runtime"
    xdg_runtime.mkdir(parents=True, exist_ok=True)
    env["XDG_RUNTIME_DIR"] = str(xdg_runtime)
    env["BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG"] = str(
        tmp_path / "catalog" / "quote_tape" / "polymarket_us"
    )
    env["BREEZY_SCORED_TRIALS_DIR"] = str(tmp_path / "scored_trials")
    env["BREEZY_LIVE_TALLY_OUTPUT_DIR"] = str(tmp_path / "derived")
    env["BREEZY_POSITION_MONITOR_REPORT_PYTHON"] = str(stub)

    result = subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    call = _report_calls(argv_log)[0]
    assert f"--corpus-summary {newer}" in call
    assert str(older) not in call


def test_corpus_summary_flag_omitted_when_corpus_dir_absent(tmp_path: Path) -> None:
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode == 0, result.stderr
    call = _report_calls(argv_log)[0]
    assert "--corpus-summary" not in call


def test_report_failure_wrapper_exits_nonzero_and_logs(tmp_path: Path) -> None:
    stub, argv_log = _make_stub(tmp_path, report_exit=1)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode != 0
    assert len(_report_calls(argv_log)) == 1
    log_text = (tmp_path / "derived" / "position_monitor_report.log").read_text()
    assert "FAILED" in log_text


def test_wrapper_runs_end_to_end_when_summaries_and_scored_trials_dirs_are_absent(
    tmp_path: Path,
) -> None:
    """The wrapper never special-cases a missing directory itself -- it
    passes whatever paths it derives straight through, relying on the
    report CLI's own graceful empty-store behaviour (verified 2026-09-15:
    `read_monitor_summaries`/`read_scored_trials` return zero rows on a
    missing directory, never raise). This stub emulates that success path;
    the point pinned here is that the WRAPPER itself adds no skip/refuse
    logic for the missing-directory case."""
    stub, argv_log = _make_stub(tmp_path)
    result = _run_wrapper(tmp_path, stub_python=stub)
    assert result.returncode == 0, result.stderr
    assert len(_report_calls(argv_log)) == 1


def test_lock_contention_skips_without_invoking_python(tmp_path: Path) -> None:
    import fcntl

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
        env["BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG"] = str(
            tmp_path / "catalog" / "quote_tape" / "polymarket_us"
        )
        env["BREEZY_SCORED_TRIALS_DIR"] = str(tmp_path / "scored_trials")
        env["BREEZY_LIVE_TALLY_OUTPUT_DIR"] = str(tmp_path / "derived")
        env["BREEZY_POSITION_MONITOR_REPORT_PYTHON"] = str(stub)
        result = subprocess.run(
            ["bash", str(_WRAPPER)],
            cwd=_REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
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
    assert 'exit 75' in text
    assert re.search(r"another study holds the studies lock.*exit 0", text) is not None


def test_wrapper_never_enables_posix_mode() -> None:
    text = _WRAPPER.read_text()
    assert "unset POSIXLY_CORRECT" in text
    non_comment_lines = [
        line for line in text.splitlines() if not line.strip().startswith("#")
    ]
    assert not any("set -o posix" in line for line in non_comment_lines)


def test_position_monitor_report_unit_pair_exists_and_wires_to_wrapper() -> None:
    service_path = _SYSTEMD_DIR / "breezy-position-monitor-report.service"
    timer_path = _SYSTEMD_DIR / "breezy-position-monitor-report.timer"
    assert service_path.exists()
    assert timer_path.exists()

    service_text = service_path.read_text()
    exec_lines = [line for line in service_text.splitlines() if line.startswith("ExecStart=")]
    assert len(exec_lines) == 1
    assert exec_lines[0].strip().endswith("position-monitor-report-run.sh")
    assert "TimeoutStartSec=" in service_text
    assert "EnvironmentFile=" not in service_text
    assert "Environment=" not in service_text
    assert "Slice=breezy-studies.slice" in service_text
    assert "Type=oneshot" in service_text
    assert not any(
        line.strip() == "[Install]" for line in service_text.splitlines()
    ), "the service is started BY the timer and must carry no [Install] section"

    timer_text = timer_path.read_text()
    assert "Unit=breezy-position-monitor-report.service" in timer_text
    assert "OnCalendar=*-*-* 15:00:00 UTC" in timer_text
    assert "Persistent=true" in timer_text
    assert "[Install]" in timer_text
    assert "WantedBy=timers.target" in timer_text


def test_service_carries_a_modest_memory_ceiling_below_the_heavy_studies() -> None:
    text = (_SYSTEMD_DIR / "breezy-position-monitor-report.service").read_text()
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
    assert max_bytes < heavy_floor_bytes


def test_readme_documents_the_new_unit() -> None:
    text = _README.read_text()
    assert "breezy-position-monitor-report" in text
    assert "position-monitor-report-run.sh" in text
