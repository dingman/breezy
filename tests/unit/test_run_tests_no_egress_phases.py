from __future__ import annotations

import stat
import subprocess
from pathlib import Path

from tests.support import bwrap_host_phase as phase

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "run_tests_no_egress.sh"


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _fake_python(path: Path, *, phase2_rc: int = 0) -> None:
    _write_executable(
        path,
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "log=${BREEZY_FAKE_LOG:?}\n"
        "if [[ ${1:-} == '-I' ]]; then\n"
        "  shift; [[ ${1:-} == '-c' ]]; shift; shift\n"
        "  printf '%s\\n' tests/integration/test_bwrap_host_phase_witness.py\n"
        "  exit 0\n"
        "fi\n"
        "printf 'PYTEST env:%s:%s:%s:%s:%s args:%s\\n' \"${BREEZY_BWRAP_HOST_PHASE-}\" "
        '"${BREEZY_TEST_OS_EGRESS_BLOCK-}" "${BREEZY_GATE_COLLECT_ONLY_CLAIM-}" '
        '"${PYTEST_PLUGINS-}" "${PYTEST_ADDOPTS-}" "$*" >> "$log"\n'
        "if [[ ${BREEZY_BWRAP_HOST_PHASE-} == '1' ]]; then exit " + str(phase2_rc) + "; fi\n"
        "if [[ $* == *--phase1-fail* ]]; then exit 5; fi\n"
        "if [[ $* == *'--noconftest -k --co'* ]]; then exit 4; fi\n"
        "if [[ $* == *--collect-only* || $* == *--co* || $* == *--collectonly* ]]; then\n"
        "  if [[ $* != *'no:tests.support.bwrap_host_phase'* "
        "&& -n ${BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE-} ]]; then\n"
        '    printf collect-only > "$BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE"\n'
        "  fi\n"
        "  exit 0\n"
        "fi\n"
        "exit 0\n",
    )


def _fake_bwrap(path: Path) -> None:
    _write_executable(
        path,
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "while [[ $# -gt 0 ]]; do\n"
        "  if [[ $1 == -- ]]; then shift; break; fi\n"
        "  case $1 in\n"
        '    --setenv) key=$2; val=$3; export "$key=$val"; shift 3;;\n'
        "    --dev-bind|--ro-bind) shift 3;;\n"
        "    --chdir|--dev|--proc) shift 2;;\n"
        "    --unshare-*|--disable-userns) shift;;\n"
        "    *) break;;\n"
        "  esac\n"
        "done\n"
        'exec "$@"\n',
    )


def _fake_unshare(path: Path) -> None:
    _write_executable(
        path,
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ $# -eq 3 && $1 == '-r' && $2 == '-n' && $3 == 'true' ]]; then exit 0; fi\n"
        "shift 2\n"
        'exec "$@"\n',
    )


def _script_env(
    *,
    bin_dir: Path,
    fake_python: Path,
    log: Path,
    gate_dir: Path,
    extra_env: dict[str, str] | None = None,
) -> dict[str, str]:
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(gate_dir.parent / "home"),
        "BREEZY_PYTHON": str(fake_python),
        "BREEZY_FAKE_LOG": str(log),
        "BREEZY_GATE_DIR": str(gate_dir),
        "PYTHONPATH": str(REPO_ROOT / "src"),
    }
    if extra_env:
        env.update(extra_env)
    return env


def _run_script(
    tmp_path: Path,
    *args: str,
    phase2_rc: int = 0,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_python = bin_dir / "python"
    _fake_python(fake_python, phase2_rc=phase2_rc)
    _fake_bwrap(bin_dir / "bwrap")
    _fake_unshare(bin_dir / "unshare")
    log = tmp_path / "calls.log"
    env = _script_env(
        bin_dir=bin_dir,
        fake_python=fake_python,
        log=log,
        gate_dir=tmp_path / "gate",
        extra_env=extra_env,
    )
    return subprocess.run(
        [str(SCRIPT), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def _log(tmp_path: Path) -> str:
    return (tmp_path / "calls.log").read_text(encoding="utf-8")


def test_gate_runs_phase2_after_phase1_failure_and_exits_phase1_rc(tmp_path: Path) -> None:
    result = _run_script(tmp_path, "--phase1-fail")
    assert result.returncode == 5
    assert "phase1 rc=5 phase2 rc=0" in result.stderr
    assert _log(tmp_path).count("PYTEST") == 2


def test_gate_exits_phase2_rc_when_phase1_green(tmp_path: Path) -> None:
    result = _run_script(tmp_path, phase2_rc=7)
    assert result.returncode == 7
    assert "phase1 rc=0 phase2 rc=7" in result.stderr


def test_gate_omits_phase2_only_for_collect_only_confirmed(tmp_path: Path) -> None:
    result = _run_script(tmp_path, "--collect-only")
    assert result.returncode == 0
    assert "phase2 omitted (collect-only confirmed)" in result.stderr
    assert _log(tmp_path).count("PYTEST") == 1


def test_collect_only_claim_with_noconftest_exits_nonzero_and_runs_phase2(tmp_path: Path) -> None:
    result = _run_script(tmp_path, "--noconftest", "-k", "--co")
    assert result.returncode == 4
    assert "phase1 rc=4 phase2 rc=0" in result.stderr
    assert _log(tmp_path).count("PYTEST") == 2


def test_collect_only_with_plugin_disabled_runs_phase2(tmp_path: Path) -> None:
    result = _run_script(tmp_path, "-p", "no:tests.support.bwrap_host_phase", "--co")
    assert result.returncode == 0
    assert "phase1 rc=0 phase2 rc=0" in result.stderr
    assert _log(tmp_path).count("PYTEST") == 2


def test_phase2_env_has_phase_var_and_no_attestation(tmp_path: Path) -> None:
    result = _run_script(tmp_path)
    assert result.returncode == 0
    lines = _log(tmp_path).splitlines()
    assert "env:1:::" in lines[-1]


def test_phase2_env_scrubs_pytest_plugins_and_addopts(tmp_path: Path) -> None:
    result = _run_script(
        tmp_path,
        extra_env={"PYTEST_PLUGINS": "tests.bad", "PYTEST_ADDOPTS": "--noconftest"},
    )
    assert result.returncode == 0
    assert "env:1:::" in _log(tmp_path).splitlines()[-1]


def test_phase2_argv_loads_plugin_and_registry_files_only(tmp_path: Path) -> None:
    result = _run_script(tmp_path, "tests/unit/test_probe_containment.py")
    assert result.returncode == 0
    phase2_line = _log(tmp_path).splitlines()[-1]
    assert "-p tests.support.bwrap_host_phase" in phase2_line
    assert "-m bwrap_host" in phase2_line
    assert "tests/integration/test_bwrap_host_phase_witness.py" in phase2_line
    assert "tests/unit/test_probe_containment.py" not in phase2_line


def test_phase2_refuses_when_attestation_inherited(tmp_path: Path) -> None:
    result = _run_script(tmp_path, extra_env={"BREEZY_TEST_OS_EGRESS_BLOCK": "1"})
    assert result.returncode == 3
    assert "phase 2 refuses" in result.stderr


def test_phase2_refuses_empty_registry(tmp_path: Path) -> None:
    fake_python = tmp_path / "python"
    _write_executable(fake_python, "#!/usr/bin/env bash\nexit 0\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_bwrap(bin_dir / "bwrap")
    env = _script_env(
        bin_dir=bin_dir,
        fake_python=fake_python,
        log=tmp_path / "calls.log",
        gate_dir=tmp_path / "gate",
    )
    result = subprocess.run(
        [str(SCRIPT)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 3
    assert "empty phase-2 registry" in result.stderr


def test_phase1_unsets_phase2_var(tmp_path: Path) -> None:
    result = _run_script(tmp_path, extra_env={phase.BWRAP_HOST_PHASE_ENV_VAR: "1"})
    assert result.returncode == 0
    first_line = _log(tmp_path).splitlines()[0]
    assert first_line.startswith("PYTEST env::1:")
    assert "-p tests.support.bwrap_host_phase" in first_line


def test_script_has_no_exec_before_phase2() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "exec bwrap" not in text
    assert "exec unshare" not in text
    assert "if bwrap_ok" in text
    assert "elif unshare_ok" in text


def test_confirm_file_mode_0600_and_removed(tmp_path: Path) -> None:
    result = _run_script(tmp_path)
    assert result.returncode == 0
    gate_dir = tmp_path / "gate"
    assert list(gate_dir.glob("p1-confirm.*")) == []


def test_gate_dir_reuse_is_chmod_0700(tmp_path: Path) -> None:
    gate_dir = tmp_path / "gate"
    gate_dir.mkdir(mode=0o755)
    result = _run_script(tmp_path)
    assert result.returncode == 0, result.stderr
    assert stat.S_IMODE(gate_dir.stat().st_mode) == 0o700
