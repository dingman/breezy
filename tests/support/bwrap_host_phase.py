from __future__ import annotations

import importlib.abc
import os
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

BWRAP_HOST_PHASE_ENV_VAR: Final[str] = "BREEZY_BWRAP_HOST_PHASE"
COLLECT_ONLY_CLAIM_ENV_VAR: Final[str] = "BREEZY_GATE_COLLECT_ONLY_CLAIM"
COLLECT_ONLY_CONFIRM_FILE_ENV_VAR: Final[str] = "BREEZY_GATE_COLLECT_ONLY_CONFIRM_FILE"
OS_EGRESS_BLOCK_ENV_VAR: Final[str] = "BREEZY_TEST_OS_EGRESS_BLOCK"
REFUSAL_PREFIX: Final[str] = "[breezy] phase-2 not admitted"

BWRAP_HOST_TEST_FILES: Final[frozenset[str]] = frozenset(
    {
        "tests/integration/test_autonomy_sandbox_namespace.py",
        "tests/integration/test_bus_handoff_namespace.py",
        "tests/integration/test_bwrap_host_phase_witness.py",
        "tests/integration/test_wal_snapshot_namespace.py",
    }
)
#: 3 witness tests + the 24 namespace tests of WP-B2b-3 + the 2 bus-handoff tests of
#: WP-B2c + the 4 WAL-snapshot tests of WP-B3. Each WP that adds a real-namespace test
#: widens this in the same commit (L-12).
BWRAP_HOST_EXPECTED_TESTS: Final[int] = 33

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_BASE_REFUSED: Final[frozenset[str]] = frozenset({"nautilus_trader", "breezy.adapters"})
_ALLOWED_P_PLUGINS: Final[frozenset[str]] = frozenset({__name__, "no:randomly", "no:cacheprovider"})
_VALUE_OPTIONS: Final[frozenset[str]] = frozenset(
    {
        "--basetemp",
        "--rootdir",
        "--confcutdir",
        "-c",
        "--config-file",
        "--import-mode",
        "-m",
        "-k",
        "-p",
    }
)

_PHASE_VALUE = os.environ.get(BWRAP_HOST_PHASE_ENV_VAR)
_PHASE_REQUESTED = _PHASE_VALUE is not None
_PHASE_ACTIVE = _PHASE_VALUE == "1"
_COLLECT_ONLY_CLAIM_VALUE: str | None = None
_COLLECT_ONLY_CONFIRM_FILE: str | None = None
_EARLY_WITNESS = False
_EARLY_POSITIONAL_ARGS: tuple[str, ...] = ()
_EARLY_WIDENING_OPTIONS: tuple[str, ...] = ()
_IGNORE_COLLECT_REGISTERED = False
_IGNORE_COLLECT_USED = False


@dataclass(frozen=True)
class Phase2Admission:
    admitted: bool
    reason: str


@dataclass(frozen=True)
class Phase2Evidence:
    early_witness: bool
    positional_args: tuple[str, ...]
    widening_options: tuple[str, ...]
    ignore_collect_active: bool


class Phase2ImportBlocker(importlib.abc.MetaPathFinder):
    def __init__(self, refused: Iterable[str] = ()) -> None:
        self._refused: set[str] = set(refused)

    @property
    def refused_modules(self) -> frozenset[str]:
        return frozenset(self._refused)

    def refuse(self, names: Iterable[str]) -> None:
        self._refused.update(name for name in names if name)

    def refuses(self, name: str) -> bool:
        return any(name == refused or name.startswith(refused + ".") for refused in self._refused)

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: object | None = None,
    ) -> None:
        if self.refuses(fullname):
            raise ImportError(f"phase-2 import blocked: {fullname}")


_BLOCKER = Phase2ImportBlocker(_BASE_REFUSED)


def _phase_requested(environ: Mapping[str, str] | None = None) -> bool:
    if environ is None:
        return _PHASE_REQUESTED
    return BWRAP_HOST_PHASE_ENV_VAR in environ


def _phase_active(environ: Mapping[str, str] | None = None) -> bool:
    if environ is None:
        return _PHASE_ACTIVE
    return environ.get(BWRAP_HOST_PHASE_ENV_VAR) == "1"


def module_name_for_path(path: str) -> str | None:
    path = path.split("::", 1)[0]
    if not path.endswith(".py"):
        return None
    if path.startswith("src/"):
        return path.removeprefix("src/").removesuffix(".py").replace("/", ".")
    if path.startswith("scripts/"):
        return path.removesuffix(".py").replace("/", ".")
    return None


def registry_paths() -> tuple[str, ...]:
    return tuple(sorted(BWRAP_HOST_TEST_FILES))


def phase2_evidence() -> Phase2Evidence:
    return Phase2Evidence(
        early_witness=_EARLY_WITNESS,
        positional_args=_EARLY_POSITIONAL_ARGS,
        widening_options=_EARLY_WIDENING_OPTIONS,
        ignore_collect_active=_IGNORE_COLLECT_REGISTERED,
    )


def _egress_module_names_from_tree() -> tuple[str, ...]:
    prefixes = (
        "src/breezy/adapters/polymarket_us/exec/",
        "src/breezy/adapters/kalshi/exec/",
    )
    basenames = {
        "execution.py",
        "execution_client.py",
        "exec_client.py",
        "order_submit.py",
        "order_router.py",
        "orders.py",
        "submit_chain.py",
        "trading.py",
        "write_transport.py",
    }
    names: set[str] = set()
    for root in ("src", "scripts"):
        base = _REPO_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*.py"):
            rel = path.relative_to(_REPO_ROOT).as_posix()
            if rel.startswith(prefixes) or path.name in basenames:
                name = module_name_for_path(rel)
                if name is not None:
                    names.add(name)
    return tuple(sorted(names))


if _phase_active():
    _BLOCKER.refuse(_egress_module_names_from_tree())
    sys.meta_path.insert(0, _BLOCKER)


def _blocked_module_names(modules: Mapping[str, object], blocker: Phase2ImportBlocker) -> list[str]:
    return sorted(name for name in modules if blocker.refuses(name))


def phase2_admission(
    *,
    environ: Mapping[str, str],
    meta_path: Sequence[object],
    modules: Mapping[str, object],
    egress_paths: Sequence[str],
    early_witness: bool,
    positional_args: Sequence[str],
    widening_options: Sequence[str],
    ignore_collect_active: bool,
) -> Phase2Admission:
    if environ.get(BWRAP_HOST_PHASE_ENV_VAR) != "1":
        return Phase2Admission(False, f"{BWRAP_HOST_PHASE_ENV_VAR} must be exactly '1'")
    if environ.get(OS_EGRESS_BLOCK_ENV_VAR) is not None:
        return Phase2Admission(False, "phase 1 attestation is present")
    if not meta_path or type(meta_path[0]) is not Phase2ImportBlocker:
        return Phase2Admission(False, "Phase2ImportBlocker is not at sys.meta_path[0]")
    blocker = meta_path[0]
    for path in egress_paths:
        name = module_name_for_path(path)
        if name is None:
            return Phase2Admission(False, f"unmappable egress path: {path}")
        if not blocker.refuses(name):
            return Phase2Admission(False, f"egress module is not refused: {name}")
    loaded = _blocked_module_names(modules, blocker)
    if loaded:
        return Phase2Admission(False, "refused module already loaded: " + ", ".join(loaded))
    if not early_witness:
        return Phase2Admission(False, "early witness missing")
    outside = sorted(
        arg
        for arg in positional_args
        if _normalise_positional_arg(arg) not in BWRAP_HOST_TEST_FILES
    )
    if outside:
        return Phase2Admission(False, "outside bwrap_host registry: " + ", ".join(outside))
    if widening_options:
        return Phase2Admission(False, "; ".join(widening_options))
    if "PYTEST_PLUGINS" in environ or "PYTEST_ADDOPTS" in environ:
        return Phase2Admission(False, "PYTEST_PLUGINS/PYTEST_ADDOPTS must be absent")
    if not ignore_collect_active:
        return Phase2Admission(False, "pytest_ignore_collect is not active")
    return Phase2Admission(True, "admitted")


def phase2_session_verdict(
    *,
    passed: int,
    skipped: int,
    failed: int,
    expected: int,
    loaded_refused: Sequence[str],
) -> str | None:
    if loaded_refused:
        return "refused module loaded: " + ", ".join(loaded_refused)
    if skipped:
        return f"phase 2 skipped {skipped} test(s)"
    if failed:
        return f"phase 2 failed {failed} test(s)"
    if passed != expected:
        return f"phase 2 expected {expected} passed test(s), got {passed}"
    return None


def _normalise_positional_arg(arg: str) -> str:
    arg = arg.split("::", 1)[0]
    path = Path(arg)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(_REPO_ROOT).as_posix()
        except ValueError:
            return arg
    return path.as_posix()


def _parse_early_args(args: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    positionals: list[str] = []
    widening: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            positionals.extend(args[i + 1 :])
            break
        if arg == "-p":
            value = args[i + 1] if i + 1 < len(args) else ""
            if value not in _ALLOWED_P_PLUGINS:
                widening.append(f"extra -p {value}")
            i += 2
            continue
        if arg.startswith("-p") and arg != "-p":
            value = arg[2:]
            if value not in _ALLOWED_P_PLUGINS:
                widening.append(f"extra -p {value}")
            i += 1
            continue
        if arg in {"--noconftest", "--pyargs"}:
            widening.append(arg)
            i += 1
            continue
        if arg.startswith("-c") and arg != "-c":
            widening.append(arg)
            i += 1
            continue
        if arg == "-o" or arg == "--override-ini":
            value = args[i + 1] if i + 1 < len(args) else ""
            widening.append(f"{arg} {value}".strip())
            i += 2
            continue
        if arg.startswith("-o") and arg != "-o":
            widening.append(arg)
            i += 1
            continue
        if arg.startswith("--override-ini="):
            widening.append(arg)
            i += 1
            continue
        if arg in {"--rootdir", "--confcutdir", "-c", "--config-file", "--import-mode"}:
            value = args[i + 1] if i + 1 < len(args) else ""
            widening.append(f"{arg} {value}".strip())
            i += 2
            continue
        if any(
            arg.startswith(option + "=")
            for option in ("--rootdir", "--confcutdir", "--config-file", "--import-mode")
        ):
            widening.append(arg)
            i += 1
            continue
        if arg in _VALUE_OPTIONS:
            i += 2
            continue
        if arg.startswith("-"):
            i += 1
            continue
        positionals.append(arg)
        i += 1
    return tuple(positionals), tuple(widening)


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(
    early_config: pytest.Config,
    parser: pytest.Parser,
    args: list[str],
) -> None:
    del parser
    global _EARLY_WITNESS, _EARLY_POSITIONAL_ARGS, _EARLY_WIDENING_OPTIONS
    global _IGNORE_COLLECT_REGISTERED
    if not _phase_active():
        return
    _EARLY_WITNESS = True
    _EARLY_POSITIONAL_ARGS, _EARLY_WIDENING_OPTIONS = _parse_early_args(args)
    _IGNORE_COLLECT_REGISTERED = _ignore_collect_impl_registered(early_config)
    admission = phase2_admission(
        environ=os.environ,
        meta_path=sys.meta_path,
        modules=sys.modules,
        egress_paths=[],
        early_witness=_EARLY_WITNESS,
        positional_args=_EARLY_POSITIONAL_ARGS,
        widening_options=_EARLY_WIDENING_OPTIONS,
        ignore_collect_active=_IGNORE_COLLECT_REGISTERED,
    )
    if not admission.admitted:
        print(f"{REFUSAL_PREFIX}: {admission.reason}", file=sys.stderr)
        raise SystemExit(2)


def _ignore_collect_impl_registered(config: pytest.Config) -> bool:
    hook = config.pluginmanager.hook.pytest_ignore_collect
    return any(
        getattr(impl, "function", None) is pytest_ignore_collect for impl in hook.get_hookimpls()
    )


def pytest_configure(config: pytest.Config) -> None:
    global _COLLECT_ONLY_CLAIM_VALUE, _COLLECT_ONLY_CONFIRM_FILE
    _COLLECT_ONLY_CLAIM_VALUE = os.environ.get(COLLECT_ONLY_CLAIM_ENV_VAR)
    _COLLECT_ONLY_CONFIRM_FILE = os.environ.get(COLLECT_ONLY_CONFIRM_FILE_ENV_VAR)
    config.addinivalue_line(
        "markers",
        "bwrap_host: real namespace test run only in the gate's bwrap host phase",
    )
    if _phase_requested() and not _phase_active():
        pytest.exit(
            f"{REFUSAL_PREFIX}: {BWRAP_HOST_PHASE_ENV_VAR} must be exactly '1'",
            returncode=2,
        )
    if _phase_requested():
        return
    confirm_file = _COLLECT_ONLY_CONFIRM_FILE
    if confirm_file:
        token = "collect-only" if bool(config.option.collectonly) else "run"
        fd = os.open(confirm_file, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(token)
    if _COLLECT_ONLY_CLAIM_VALUE == "1" and not bool(config.option.collectonly):
        pytest.exit(
            f"{REFUSAL_PREFIX}: collect-only claim mismatch",
            returncode=2,
        )


@pytest.hookimpl(tryfirst=True)
def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool | None:
    del config
    global _IGNORE_COLLECT_USED
    if not _phase_active():
        return None
    _IGNORE_COLLECT_USED = True
    path = Path(collection_path)
    try:
        rel = path.resolve().relative_to(_REPO_ROOT).as_posix()
    except ValueError:
        return True
    if path.is_dir():
        registry = [(_REPO_ROOT / item) for item in BWRAP_HOST_TEST_FILES]
        return not any(_is_ancestor_or_self(path.resolve(), item.resolve()) for item in registry)
    return rel not in BWRAP_HOST_TEST_FILES


def _is_ancestor_or_self(parent: Path, child: Path) -> bool:
    return parent == child or parent in child.parents


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if not _phase_active():
        skip = pytest.mark.skip(
            reason="bwrap_host test runs in phase 2 of scripts/ci/run_tests_no_egress.sh"
        )
        for item in items:
            if item.get_closest_marker("bwrap_host") is not None:
                item.add_marker(skip)
        return
    if not _IGNORE_COLLECT_USED:
        pytest.exit(f"{REFUSAL_PREFIX}: pytest_ignore_collect was not exercised", returncode=2)
    for item in items:
        rel = Path(str(item.fspath)).resolve().relative_to(_REPO_ROOT).as_posix()
        if rel not in BWRAP_HOST_TEST_FILES:
            pytest.exit(f"{REFUSAL_PREFIX}: outside bwrap_host registry: {rel}", returncode=2)
        if item.get_closest_marker("bwrap_host") is None:
            pytest.exit(f"{REFUSAL_PREFIX}: unmarked phase-2 item: {rel}", returncode=2)


_PASSED = 0
_SKIPPED = 0
_FAILED = 0


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if not _phase_active() or report.when != "call":
        return
    global _PASSED, _SKIPPED, _FAILED
    if report.passed:
        _PASSED += 1
    elif report.skipped:
        _SKIPPED += 1
    elif report.failed:
        _FAILED += 1


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    del exitstatus
    if not _phase_active():
        return
    if bool(session.config.option.collectonly):
        return
    if not _IGNORE_COLLECT_USED:
        session.exitstatus = 1
        terminal = session.config.pluginmanager.get_plugin("terminalreporter")
        if terminal is not None:
            terminal.write_line(f"{REFUSAL_PREFIX}: pytest_ignore_collect was not exercised")
        return
    blocker = (
        sys.meta_path[0]
        if sys.meta_path and type(sys.meta_path[0]) is Phase2ImportBlocker
        else _BLOCKER
    )
    loaded = _blocked_module_names(sys.modules, blocker)
    reason = phase2_session_verdict(
        passed=_PASSED,
        skipped=_SKIPPED,
        failed=_FAILED,
        expected=BWRAP_HOST_EXPECTED_TESTS,
        loaded_refused=loaded,
    )
    if reason is not None:
        session.exitstatus = 1
        terminal = session.config.pluginmanager.get_plugin("terminalreporter")
        if terminal is not None:
            terminal.write_line(f"{REFUSAL_PREFIX}: {reason}")
