from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import (
    OS_EGRESS_BLOCK_ENV_VAR,
    execution_egress_abort_reason,
)
from tests.support import bwrap_host_phase as phase
from tests.unit.test_execution_egress_firewall_guard import (
    CanaryOutcome,
    find_exec_test_marker_violations,
    find_execution_egress_modules,
)
from tests.unit.test_polymarket_us_readonly_guard import Violation

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable
PLUGIN = "tests.support.bwrap_host_phase"
WITNESS_CONFTEST = REPO_ROOT / "tests/fixtures/bwrap_host_phase/witness_dir/conftest.py"


def _child_env(**extra: str) -> dict[str, str]:
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/tmp",
        "PYTHONPATH": str(REPO_ROOT / "src"),
    }
    env.update(extra)
    return env


def _phase_env(**extra: str) -> dict[str, str]:
    return _child_env(**{phase.BWRAP_HOST_PHASE_ENV_VAR: "1"}, **extra)


def _run_child(
    args: list[str], *, env_extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = _phase_env(**(env_extra or {}))
    return subprocess.run(
        [PYTHON, "-m", "pytest", "-q", "-p", PLUGIN, *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


class StrictBlocker(phase.Phase2ImportBlocker):
    pass


def _import_witness_conftest(module_name: str) -> None:
    spec = importlib.util.spec_from_file_location(module_name, WITNESS_CONFTEST)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.pop(module_name, None)
    spec.loader.exec_module(module)


def test_fixture_tripwires_inert_in_phase1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(phase.BWRAP_HOST_PHASE_ENV_VAR, raising=False)
    _import_witness_conftest("phase1_witness_conftest")

    monkeypatch.setenv(phase.BWRAP_HOST_PHASE_ENV_VAR, "1")
    with pytest.raises(RuntimeError, match="phase-2 ignore-collect"):
        _import_witness_conftest("phase2_witness_conftest")


def test_phase1_plugin_writes_confirm_file_collect_only_or_run(tmp_path: Path) -> None:
    confirm = tmp_path / "confirm"
    confirm.write_text("old-token", encoding="utf-8")
    env = _child_env(**{phase.COLLECT_ONLY_CONFIRM_FILE_ENV_VAR: str(confirm)})

    collect = subprocess.run(
        [
            PYTHON,
            "-m",
            "pytest",
            "-q",
            "-p",
            PLUGIN,
            "--confcutdir=tests/integration",
            "--collect-only",
            "tests/integration/test_bwrap_host_phase_witness.py",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert collect.returncode == 0, collect.stdout + collect.stderr
    assert confirm.read_text(encoding="utf-8") == "collect-only"

    run = subprocess.run(
        [
            PYTHON,
            "-m",
            "pytest",
            "-q",
            "-p",
            PLUGIN,
            "--confcutdir=tests/integration",
            "tests/integration/test_bwrap_host_phase_witness.py",
        ],
        cwd=REPO_ROOT,
        env={**env, OS_EGRESS_BLOCK_ENV_VAR: "1"},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert confirm.read_text(encoding="utf-8") == "run"

    absent = tmp_path / "absent-confirm"
    refused_absent = subprocess.run(
        [
            PYTHON,
            "-m",
            "pytest",
            "-q",
            "-p",
            PLUGIN,
            "--confcutdir=tests/integration",
            "--collect-only",
            "tests/integration/test_bwrap_host_phase_witness.py",
        ],
        cwd=REPO_ROOT,
        env={**env, phase.COLLECT_ONLY_CONFIRM_FILE_ENV_VAR: str(absent)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert refused_absent.returncode != 0
    assert not absent.exists()

    symlink_target = tmp_path / "symlink-target"
    symlink = tmp_path / "symlink-confirm"
    symlink.symlink_to(symlink_target)
    refused_symlink = subprocess.run(
        [
            PYTHON,
            "-m",
            "pytest",
            "-q",
            "-p",
            PLUGIN,
            "--confcutdir=tests/integration",
            "--collect-only",
            "tests/integration/test_bwrap_host_phase_witness.py",
        ],
        cwd=REPO_ROOT,
        env={**env, phase.COLLECT_ONLY_CONFIRM_FILE_ENV_VAR: str(symlink)},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert refused_symlink.returncode != 0
    assert not symlink_target.exists()


def test_phase1_plugin_loaded_once_with_dash_p_and_pytest_plugins() -> None:
    result = subprocess.run(
        [
            PYTHON,
            "-m",
            "pytest",
            "-q",
            "-p",
            PLUGIN,
            "--confcutdir=tests/integration",
            "--collect-only",
            "tests/integration/test_bwrap_host_phase_witness.py",
        ],
        cwd=REPO_ROOT,
        env=_child_env(PYTEST_PLUGINS=PLUGIN),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Plugin already registered" not in result.stdout + result.stderr


def test_phase1_plugin_does_not_read_environ_during_tests(tmp_path: Path) -> None:
    test_file = tmp_path / "test_environ_guard.py"
    test_file.write_text(
        "from __future__ import annotations\n"
        "import os\n\n"
        "def test_runtime_environ_get_can_be_forbidden(monkeypatch):\n"
        "    def forbidden_get(*args, **kwargs):\n"
        "        raise AssertionError('plugin read os.environ during test runtime')\n"
        "    monkeypatch.setattr(os.environ, 'get', forbidden_get)\n"
        "    assert True\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            PYTHON,
            "-m",
            "pytest",
            "-q",
            "-p",
            PLUGIN,
            f"--confcutdir={tmp_path}",
            str(test_file),
        ],
        cwd=REPO_ROOT,
        env=_child_env(),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_conftest_non_one_phase_value_does_not_take_phase2_admission_path() -> None:
    result = subprocess.run(
        [
            PYTHON,
            "-m",
            "pytest",
            "-q",
            "-p",
            PLUGIN,
            "--collect-only",
            "tests/unit/test_holdout_ruling_filed_verbatim.py",
        ],
        cwd=REPO_ROOT,
        env=_child_env(**{phase.BWRAP_HOST_PHASE_ENV_VAR: "true"}),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 2
    assert f"{phase.BWRAP_HOST_PHASE_ENV_VAR} must be exactly '1'" in combined


def test_p2_admission_requires_exact_env_one() -> None:
    blocker = phase.Phase2ImportBlocker({"nautilus_trader"})
    for value in (None, "", "true", "1 "):
        env: dict[str, str] = {} if value is None else {phase.BWRAP_HOST_PHASE_ENV_VAR: value}
        admitted = phase.phase2_admission(
            environ=env,
            meta_path=[blocker],
            modules={},
            egress_paths=[],
            early_witness=True,
            positional_args=phase.registry_paths(),
            widening_options=[],
            ignore_collect_active=True,
        )
        assert not admitted.admitted
    assert phase.phase2_admission(
        environ={phase.BWRAP_HOST_PHASE_ENV_VAR: "1"},
        meta_path=[blocker],
        modules={},
        egress_paths=[],
        early_witness=True,
        positional_args=phase.registry_paths(),
        widening_options=[],
        ignore_collect_active=True,
    ).admitted


def test_p2_admission_refused_when_phase1_attestation_also_set() -> None:
    blocker = phase.Phase2ImportBlocker({"nautilus_trader"})
    admitted = phase.phase2_admission(
        environ={
            phase.BWRAP_HOST_PHASE_ENV_VAR: "1",
            OS_EGRESS_BLOCK_ENV_VAR: "1",
        },
        meta_path=[blocker],
        modules={},
        egress_paths=[],
        early_witness=True,
        positional_args=phase.registry_paths(),
        widening_options=[],
        ignore_collect_active=True,
    )
    assert not admitted.admitted
    assert "attestation" in admitted.reason


def test_p2_pytest_plugins_or_addopts_env_not_admitted() -> None:
    blocker = phase.Phase2ImportBlocker({"nautilus_trader"})
    for key in ("PYTEST_PLUGINS", "PYTEST_ADDOPTS"):
        admitted = phase.phase2_admission(
            environ={phase.BWRAP_HOST_PHASE_ENV_VAR: "1", key: "injected"},
            meta_path=[blocker],
            modules={},
            egress_paths=[],
            early_witness=True,
            positional_args=phase.registry_paths(),
            widening_options=[],
            ignore_collect_active=True,
        )
        assert not admitted.admitted
        assert "PYTEST_PLUGINS/PYTEST_ADDOPTS" in admitted.reason


def test_p2_option_widening_refused() -> None:
    blocker = phase.Phase2ImportBlocker({"nautilus_trader"})
    for option in (
        "--noconftest",
        "--pyargs",
        "--confcutdir tests",
        "-c evil.ini",
        "-cevil.ini",
        "-o addopts=-q",
        "--override-ini addopts=-q",
        "--override-ini=addopts=-q",
    ):
        admitted = phase.phase2_admission(
            environ={phase.BWRAP_HOST_PHASE_ENV_VAR: "1"},
            meta_path=[blocker],
            modules={},
            egress_paths=[],
            early_witness=True,
            positional_args=phase.registry_paths(),
            widening_options=[option],
            ignore_collect_active=True,
        )
        assert not admitted.admitted
        assert option in admitted.reason


def test_p2_parse_early_args_flags_attached_config_and_override_ini() -> None:
    positionals, widening = phase._parse_early_args(
        [
            "-cevil.ini",
            "-o",
            "addopts=-q",
            "--override-ini=pythonpath=/tmp",
            *phase.registry_paths(),
        ]
    )
    assert positionals == phase.registry_paths()
    assert widening == (
        "-cevil.ini",
        "-o addopts=-q",
        "--override-ini=pythonpath=/tmp",
    )


def test_p2_admission_refused_without_blocker_at_meta_path_head() -> None:
    blocker = phase.Phase2ImportBlocker({"nautilus_trader"})
    admitted = phase.phase2_admission(
        environ={phase.BWRAP_HOST_PHASE_ENV_VAR: "1"},
        meta_path=[object(), blocker],
        modules={},
        egress_paths=[],
        early_witness=True,
        positional_args=phase.registry_paths(),
        widening_options=[],
        ignore_collect_active=True,
    )
    assert not admitted.admitted
    assert "meta_path[0]" in admitted.reason


def test_p2_admission_refused_when_blocker_is_subclass() -> None:
    blocker = StrictBlocker({"nautilus_trader"})
    admitted = phase.phase2_admission(
        environ={phase.BWRAP_HOST_PHASE_ENV_VAR: "1"},
        meta_path=[blocker],
        modules={},
        egress_paths=[],
        early_witness=True,
        positional_args=phase.registry_paths(),
        widening_options=[],
        ignore_collect_active=True,
    )
    assert not admitted.admitted
    assert "meta_path[0]" in admitted.reason


def test_p2_admission_refused_when_ignore_collect_evidence_false() -> None:
    blocker = phase.Phase2ImportBlocker({"nautilus_trader"})
    admitted = phase.phase2_admission(
        environ={phase.BWRAP_HOST_PHASE_ENV_VAR: "1"},
        meta_path=[blocker],
        modules={},
        egress_paths=[],
        early_witness=True,
        positional_args=phase.registry_paths(),
        widening_options=[],
        ignore_collect_active=False,
    )
    assert not admitted.admitted
    assert "pytest_ignore_collect" in admitted.reason


def test_p2_admission_refused_when_refused_module_already_loaded() -> None:
    blocker = phase.Phase2ImportBlocker({"nautilus_trader"})
    admitted = phase.phase2_admission(
        environ={phase.BWRAP_HOST_PHASE_ENV_VAR: "1"},
        meta_path=[blocker],
        modules={"nautilus_trader": object()},
        egress_paths=[],
        early_witness=True,
        positional_args=phase.registry_paths(),
        widening_options=[],
        ignore_collect_active=True,
    )
    assert not admitted.admitted
    assert "already loaded" in admitted.reason


def test_p2_admission_refuses_unmappable_egress_path() -> None:
    blocker = phase.Phase2ImportBlocker({"nautilus_trader"})
    admitted = phase.phase2_admission(
        environ={phase.BWRAP_HOST_PHASE_ENV_VAR: "1"},
        meta_path=[blocker],
        modules={},
        egress_paths=["README.md"],
        early_witness=True,
        positional_args=phase.registry_paths(),
        widening_options=[],
        ignore_collect_active=True,
    )
    assert not admitted.admitted
    assert "unmappable" in admitted.reason


def test_p2_every_live_egress_hit_maps_to_a_refused_module() -> None:
    blocker = phase.Phase2ImportBlocker({"nautilus_trader", "breezy.adapters"})
    egress_paths = sorted({violation.path for violation in find_execution_egress_modules()})
    assert egress_paths
    blocker.refuse(
        name
        for path in egress_paths
        for name in [phase.module_name_for_path(path)]
        if name is not None
    )
    admitted = phase.phase2_admission(
        environ={phase.BWRAP_HOST_PHASE_ENV_VAR: "1"},
        meta_path=[blocker],
        modules={},
        egress_paths=egress_paths,
        early_witness=True,
        positional_args=phase.registry_paths(),
        widening_options=[],
        ignore_collect_active=True,
    )
    assert admitted.admitted, admitted.reason


def test_n2_rule_without_phase_evidence_is_unchanged() -> None:
    planted = [Violation("src/breezy/adapters/polymarket_us/exec/__init__.py", 0, "E0", "planted")]
    cases = [
        ([], False, None),
        (planted, False, None),
        (planted, True, CanaryOutcome(True, "blocked")),
        (planted, True, CanaryOutcome(False, "reached")),
    ]
    for egress_modules, attested, outcome in cases:
        before = execution_egress_abort_reason(
            egress_modules=egress_modules,
            attested=attested,
            outcome=outcome,
        )
        after = execution_egress_abort_reason(
            egress_modules=egress_modules,
            attested=attested,
            outcome=outcome,
            bwrap_host_phase=None,
        )
        assert after == before


def test_n2_rule_phase_and_attestation_mutually_exclusive() -> None:
    admitted = phase.Phase2Admission(True, "admitted")
    planted = [Violation("src/breezy/adapters/polymarket_us/exec/__init__.py", 0, "E0", "planted")]
    reason = execution_egress_abort_reason(
        egress_modules=planted,
        attested=True,
        outcome=None,
        bwrap_host_phase=admitted,
    )
    assert reason is not None
    assert "phase 1 attestation and phase 2 are mutually exclusive" in reason


def test_p2_blocker_refuses_nautilus_adapters_and_planted_egress_module() -> None:
    blocker = phase.Phase2ImportBlocker({"nautilus_trader", "breezy.adapters"})
    blocker.refuse(["breezy.adapters.polymarket_us.exec.client"])
    for name in (
        "nautilus_trader",
        "nautilus_trader.model",
        "breezy.adapters",
        "breezy.adapters.polymarket_us.symbology",
        "breezy.adapters.polymarket_us.exec.client",
    ):
        assert blocker.refuses(name), name
    assert not blocker.refuses("breezy.runtime")


def test_p2_child_admitted_collects_registry_and_loads_no_refused_module() -> None:
    result = _run_child(["--collect-only", "-v", *sorted(phase.BWRAP_HOST_TEST_FILES)])
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "test_phase2_witness_sees_phase_env_only" in combined
    assert phase.REFUSAL_PREFIX not in combined


def test_p2_child_with_nautilus_preloaded_aborts_before_collection() -> None:
    result = _run_child(
        [
            "--collect-only",
            "-p",
            "tests.fixtures.bwrap_host_phase.pytest_plugins_witness",
            *sorted(phase.BWRAP_HOST_TEST_FILES),
        ]
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 2
    assert phase.REFUSAL_PREFIX in combined
    assert "extra -p" in combined
    assert "test_phase2_witness_sees_phase_env_only" not in combined


def test_p2_child_outside_registry_exits_2() -> None:
    result = _run_child(["tests/fixtures/bwrap_host_phase/p2_outside_registry.py"])
    combined = result.stdout + result.stderr
    assert result.returncode == 2
    assert "outside bwrap_host registry" in combined


def test_p2_ignore_collect_blocks_recursive_non_registry_conftest() -> None:
    """No positional args means the early-hook registry check cannot refuse first.

    Pytest then uses its default recursive `tests/` collection root. The only
    barrier between that walk and the non-registry fixture conftest tripwire is
    this plugin's pytest_ignore_collect hook.
    """
    result = _run_child(["--collect-only", "-v"])
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "phase-2 ignore-collect imported a non-registry conftest" not in combined
    assert "test_witness_dir_module_should_not_be_collected" not in combined
    assert "test_phase2_witness_sees_phase_env_only" in combined


def test_p2_child_test_importing_nautilus_outside_registry_is_refused_before_import() -> None:
    result = _run_child(["tests/fixtures/bwrap_host_phase/p2_imports_nautilus.py"])
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "outside bwrap_host registry" in combined
    assert "test_importing_nautilus_should_never_run" not in combined


def test_phase2_session_verdict_fails_on_skip_count_mismatch_or_loaded_module() -> None:
    assert (
        phase.phase2_session_verdict(
            passed=phase.BWRAP_HOST_EXPECTED_TESTS,
            skipped=0,
            failed=0,
            expected=phase.BWRAP_HOST_EXPECTED_TESTS,
            loaded_refused=[],
        )
        is None
    )
    assert "expected" in (
        phase.phase2_session_verdict(
            passed=phase.BWRAP_HOST_EXPECTED_TESTS + 1,
            skipped=0,
            failed=0,
            expected=phase.BWRAP_HOST_EXPECTED_TESTS,
            loaded_refused=[],
        )
        or ""
    )
    assert "skipped" in (
        phase.phase2_session_verdict(
            passed=phase.BWRAP_HOST_EXPECTED_TESTS,
            skipped=1,
            failed=0,
            expected=phase.BWRAP_HOST_EXPECTED_TESTS,
            loaded_refused=[],
        )
        or ""
    )
    assert "refused module loaded" in (
        phase.phase2_session_verdict(
            passed=phase.BWRAP_HOST_EXPECTED_TESTS,
            skipped=0,
            failed=0,
            expected=phase.BWRAP_HOST_EXPECTED_TESTS,
            loaded_refused=["nautilus_trader"],
        )
        or ""
    )


def test_phase1_skips_bwrap_host_items_naming_phase2() -> None:
    result = subprocess.run(
        [
            PYTHON,
            "-m",
            "pytest",
            "-q",
            "-p",
            PLUGIN,
            "-rs",
            "--confcutdir=tests/integration",
            "tests/integration/test_bwrap_host_phase_witness.py",
        ],
        cwd=REPO_ROOT,
        env=_child_env(**{OS_EGRESS_BLOCK_ENV_VAR: "1"}),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "phase 2" in combined


def test_bwrap_host_registry_equals_marked_files() -> None:
    marked: set[str] = set()
    for path in (REPO_ROOT / "tests").rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "bwrap_host"
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "mark"
            ):
                marked.add(rel)
    assert marked == set(phase.BWRAP_HOST_TEST_FILES)


def test_bwrap_host_registry_outside_unit_and_contract_dirs() -> None:
    for path in phase.BWRAP_HOST_TEST_FILES:
        assert not path.startswith("tests/unit/")
        assert not path.startswith("tests/contract/")


def test_bwrap_host_files_import_no_subprocess_nautilus_or_adapters() -> None:
    allowed_support_subprocess = "tests/support/bwrap_harness.py"
    denied_imports = {
        "socket",
        "http",
        "httpx",
        "urllib",
        "requests",
        "aiohttp",
        "websockets",
        "ctypes",
        "runpy",
        "nautilus_trader",
        "breezy.adapters",
        "breezy.strategy",
        "subprocess",
    }
    files = [*phase.BWRAP_HOST_TEST_FILES, allowed_support_subprocess]
    offenders: list[str] = []
    for rel in files:
        tree = ast.parse((REPO_ROOT / rel).read_text(encoding="utf-8"), filename=rel)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".", 1)[0]
                if rel == allowed_support_subprocess and top == "subprocess":
                    continue
                if name in denied_imports or top in denied_imports:
                    offenders.append(f"{rel}: imports {name}")
    assert offenders == []


def test_bwrap_host_expected_tests_equals_collected_count() -> None:
    result = _run_child(["--collect-only", "-q", *sorted(phase.BWRAP_HOST_TEST_FILES)])
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert (
        f"{phase.BWRAP_HOST_EXPECTED_TESTS} tests collected" in combined
        or f": {phase.BWRAP_HOST_EXPECTED_TESTS}" in combined
    )


def test_conftest_marker_set_unchanged_by_plugin() -> None:
    source = (
        "from breezy.adapters.polymarket_us import exec\npytestmark = pytest.mark.allow_socket\n"
    )
    violations = find_exec_test_marker_violations("tests/bad.py", source)
    assert violations
