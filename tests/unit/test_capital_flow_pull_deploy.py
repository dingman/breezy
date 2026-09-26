"""FU-13b stage 2: the `breezy-capital-flow-pull` systemd deploy surface
(unit + timer + wrapper).

Authority: ``docs/plans/backlog/NIGHT_2026-09-26/FU-13b_plan_r2_2026-09-26.md``
File-by-File Plan, round-2 review binding amendment 1. Shape mirrors
``test_portfolio_roi_deploy.py``, hermetic -- this module parses unit and
wrapper TEXT directly (plus a stubbed-python subprocess run of the wrapper
itself), and never runs `systemctl`/`daemon-reload`.

`scripts/venue/polymarket_us_capital_flow_pull.py` is exercised directly by
`tests/unit/test_polymarket_us_capital_flow_pull.py`; this module stubs
`python` for the wrapper's own subprocess tests, so marker-free argv/pipe
behaviour is verified without a real venue-touching process.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD_DIR = _REPO_ROOT / "deploy" / "systemd"
_SERVICE = _SYSTEMD_DIR / "breezy-capital-flow-pull.service"
_TIMER = _SYSTEMD_DIR / "breezy-capital-flow-pull.timer"
_WRAPPER = _SYSTEMD_DIR / "capital-flow-pull-run.sh"

_PERMITTED_ENV_FILES = frozenset(
    {
        "%h/.config/breezy/breezy.env",
        "%h/.config/breezy/polymarket.env",
        "%h/.config/breezy/alerts.env",
    }
)
_FORBIDDEN_ENV_SUBSTRINGS = ("breezy-trade.env", "operator.env")


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
    lines = _directive_lines(_SERVICE.read_text())
    assert "Type=oneshot" in lines
    assert not any(line.startswith("Restart=") for line in lines)
    assert not any(line == "[Install]" for line in lines)


def test_service_orders_before_the_portfolio_roi_service() -> None:
    lines = _directive_lines(_SERVICE.read_text())
    assert "Before=breezy-portfolio-roi.service" in lines


def test_service_declares_onfailure_notifier() -> None:
    lines = _directive_lines(_SERVICE.read_text())
    assert "OnFailure=breezy-study-failed@%n.service" in lines


def test_service_declares_memory_max_and_timeout() -> None:
    text = _SERVICE.read_text()
    assert _directive_value(text, "MemoryMax") == "512M"
    assert _directive_value(text, "TimeoutStartSec") == "300"


def test_service_declares_umask() -> None:
    assert "UMask=0077" in _directive_lines(_SERVICE.read_text())


def test_service_declares_exactly_the_permitted_env_files() -> None:
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
        "ExecStart=/home/jon/breezy/deploy/systemd/capital-flow-pull-run.sh"
    )


def test_timer_declares_install_wanted_by_timers_target() -> None:
    text = _TIMER.read_text()
    assert "[Install]" in text
    assert "WantedBy=timers.target" in _directive_lines(text)


def test_timer_fires_at_1730_utc_and_is_persistent() -> None:
    text = _TIMER.read_text()
    assert "OnCalendar=*-*-* 17:30:00 UTC" in _directive_lines(text)
    assert "Persistent=true" in _directive_lines(text)


def test_timer_tick_is_before_the_1740_portfolio_roi_tick() -> None:
    match = re.search(
        r"^OnCalendar=\S+\s+(\d{2}):(\d{2}):(\d{2})\s+UTC\s*$",
        _TIMER.read_text(),
        re.MULTILINE,
    )
    assert match is not None, f"{_TIMER.name} has no parseable OnCalendar="
    tick = _dt.time(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    assert tick < _dt.time(17, 40, 0)
    assert tick > _dt.time(17, 20, 0)


# ---------------------------------------------------------------------------
# Wrapper: no temp file, greps only the summary line (round-2 amendment 1)
# ---------------------------------------------------------------------------


def _code_lines(text: str) -> list[str]:
    """Non-comment, non-blank lines only -- so this module's own comments
    (which document the amendment by NAMING what it avoids, e.g. `mktemp`)
    cannot trip a plain substring search over the whole file."""
    return [
        line
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_wrapper_uses_no_temp_file() -> None:
    code = "\n".join(_code_lines(_WRAPPER.read_text()))
    assert "mktemp" not in code
    assert "SCRIPT_OUT" not in code
    assert "trap" not in code


def test_wrapper_only_greps_the_capital_flow_pull_summary_line() -> None:
    grep_lines = [
        line
        for line in _code_lines(_WRAPPER.read_text())
        if "grep" in line and "CAPITAL_FLOW_PULL" in line
    ]
    assert len(grep_lines) == 1
    assert "grep '^CAPITAL_FLOW_PULL '" in grep_lines[0]


def test_wrapper_declares_pipefail() -> None:
    lines = _WRAPPER.read_text().splitlines()
    assert "set -o pipefail" in lines


def _run_wrapper(stub: Path) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["BREEZY_CAPITAL_FLOW_PULL_PYTHON"] = str(stub)
    return subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _write_stub(tmp_path: Path, script: str) -> Path:
    stub = tmp_path / "stub_python.sh"
    stub.write_text(f"#!/usr/bin/env bash\n{script}\n")
    stub.chmod(0o755)
    return stub


def test_successful_run_emits_only_the_summary_line(tmp_path: Path) -> None:
    stub = _write_stub(
        tmp_path,
        "echo 'noise line, never a CAPITAL_FLOW_PULL line'\n"
        "echo 'CAPITAL_FLOW_PULL status=OK pages=1 records=0 path=/tmp/x.json'\n"
        "exit 0\n",
    )

    result = _run_wrapper(stub)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "CAPITAL_FLOW_PULL status=OK pages=1 records=0 path=/tmp/x.json"
    assert "noise line" not in result.stdout


def test_a_run_with_no_summary_line_fails(tmp_path: Path) -> None:
    stub = _write_stub(tmp_path, "echo 'no marker here'\nexit 0\n")

    result = _run_wrapper(stub)

    assert result.returncode == 1
    assert "CAPITAL_FLOW_PULL_RUN FAILED" in result.stdout


def test_a_failed_puller_exits_nonzero_and_still_surfaces_the_error_line(tmp_path: Path) -> None:
    stub = _write_stub(
        tmp_path,
        "echo 'CAPITAL_FLOW_PULL status=ERROR error=VenueStatusError'\nexit 1\n",
    )

    result = _run_wrapper(stub)

    assert result.returncode == 1
    assert result.stdout.strip() == "CAPITAL_FLOW_PULL status=ERROR error=VenueStatusError"


def test_a_currency_like_summary_line_is_withheld(tmp_path: Path) -> None:
    stub = _write_stub(
        tmp_path,
        "echo 'CAPITAL_FLOW_PULL status=OK pages=1 records=1 path=/tmp/x.json total=$5.00'\n"
        "exit 0\n",
    )

    result = _run_wrapper(stub)

    assert result.returncode == 0
    assert "CAPITAL_FLOW_PULL SUMMARY WITHHELD -- currency-like token" in result.stdout
    assert "5.00" not in result.stdout
