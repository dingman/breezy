"""Execution-based tests for `deploy/systemd/decision-funnel-digest-run.sh`'s
family-id resolution (EDGE-3 plan item 12, the wrapper test named beside
test 28). Mirrors `test_replay_daily_wrapper.py`'s idiom: `$PY` and
`systemctl` are both stubbed shell scripts dispatching on argv shape, so the
wrapper's own plumbing (whether it passes `--family-id`, and with what
value) is pinned without ever running the real digest.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WRAPPER = _REPO_ROOT / "deploy" / "systemd" / "decision-funnel-digest-run.sh"


def _systemctl_stub(tmp_path: Path, *, environment_line: str = "", exit_code: int = 0) -> Path:
    stub = tmp_path / "systemctl-stub.sh"
    stub.write_text(
        f"#!/usr/bin/env bash\nprintf '%s\\n' {shlex.quote(environment_line)}\nexit {exit_code}\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)
    return stub


def _python_stub(tmp_path: Path) -> tuple[Path, Path]:
    argv_log = tmp_path / "argv_log.txt"
    stub = tmp_path / "python-stub.sh"
    stub.write_text(
        f"""#!/usr/bin/env bash
echo "$@" >> {shlex.quote(str(argv_log))}
exit 0
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
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    env["HOME"] = str(home)
    runtime_dir = tmp_path / "xdg-runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    env["XDG_RUNTIME_DIR"] = str(runtime_dir)
    env["BREEZY_DECISION_FUNNEL_PYTHON"] = str(python_stub)
    env["BREEZY_DECISION_FUNNEL_OUTPUT_DIR"] = str(tmp_path / "derived")
    env["BREEZY_SYSTEMCTL"] = str(systemctl_stub)
    env["POLYMARKET_US_EXEC_STATE_DB"] = str(tmp_path / "exec_state.db")
    return subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_wrapper_script_is_valid_bash() -> None:
    result = subprocess.run(
        ["bash", "-n", str(_WRAPPER)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_digest_wrapper_passes_the_validated_supervisor_family_id(tmp_path: Path) -> None:
    python_stub, argv_log = _python_stub(tmp_path)
    systemctl_stub = _systemctl_stub(
        tmp_path,
        environment_line="Environment=BREEZY_SENDING_FAMILY_ID=pm_us_crh_v4",
    )
    result = _run_wrapper(tmp_path, python_stub=python_stub, systemctl_stub=systemctl_stub)
    assert result.returncode == 0, result.stderr
    argv = argv_log.read_text()
    assert "--family-id pm_us_crh_v4" in argv
    assert "--store-path" in argv


def test_digest_wrapper_omits_family_id_when_the_supervisor_var_is_absent(
    tmp_path: Path,
) -> None:
    python_stub, argv_log = _python_stub(tmp_path)
    systemctl_stub = _systemctl_stub(tmp_path, environment_line="")
    result = _run_wrapper(tmp_path, python_stub=python_stub, systemctl_stub=systemctl_stub)
    assert result.returncode == 0, result.stderr
    argv = argv_log.read_text()
    assert "--family-id" not in argv
    assert "--store-path" in argv


def test_digest_wrapper_omits_an_invalid_family_id(tmp_path: Path) -> None:
    python_stub, argv_log = _python_stub(tmp_path)
    systemctl_stub = _systemctl_stub(
        tmp_path,
        environment_line="Environment=BREEZY_SENDING_FAMILY_ID=has/a/slash",
    )
    result = _run_wrapper(tmp_path, python_stub=python_stub, systemctl_stub=systemctl_stub)
    assert result.returncode == 0, result.stderr
    argv = argv_log.read_text()
    assert "--family-id" not in argv


def test_digest_wrapper_exits_75_on_a_systemctl_infrastructure_failure(tmp_path: Path) -> None:
    """A `systemctl show` FAILURE is an infra problem, not "no family
    armed" -- SKIPPED-INFRA, exit 75, same as the sibling lock-infra
    failures (never a benign skip that hides a real fault)."""
    python_stub, argv_log = _python_stub(tmp_path)
    systemctl_stub = _systemctl_stub(tmp_path, exit_code=1)
    result = _run_wrapper(tmp_path, python_stub=python_stub, systemctl_stub=systemctl_stub)
    assert result.returncode == 75
    assert not argv_log.exists()
