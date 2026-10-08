"""AUT-6 import closure: no AUT-6 entry module may reach the venue adapters or the CRH package.

Plan r15 section 3.1.2. Two checks per module: a static walk of module-level imports (ancestor
packages added), and a fresh-subprocess ``sys.modules`` check after importing it. WP5 contributes
the ``breezy.analysis.nbp_drift`` case and the positive control; later work packages append their
entry points to ``ENTRY_MODULES``.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

from tests.support.entry_points import SRC_DIR

FORBIDDEN_PREFIXES: Final[tuple[str, ...]] = (
    "breezy.adapters",
    "breezy.strategy.current_rung_hold",
)

#: Entry modules judged so far. Append only; each work package adds its own.
ENTRY_MODULES: Final[tuple[str, ...]] = (
    "breezy.analysis.nbp_drift",
    "breezy.runtime.autonomy_canary_cli",
)


def _source_path(module: str, roots: tuple[Path, ...] = (SRC_DIR,)) -> Path | None:
    for root in roots:
        path = root.joinpath(*module.split("."))
        for candidate in (path.with_suffix(".py"), path / "__init__.py"):
            if candidate.is_file():
                return candidate
    return None


def _module_level_imports(path: Path, module: str) -> set[str]:
    package = module.rsplit(".", 1)[0] if path.name != "__init__.py" else module
    found: set[str] = set()
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level:
            base = package.rsplit(".", node.level - 1)[0] if node.level > 1 else package
            target = f"{base}.{node.module}" if node.module else base
            found.add(target)
    return found


def static_closure(module: str, roots: tuple[Path, ...] = (SRC_DIR,)) -> set[str]:
    """Every ``breezy`` module reachable by module-level imports, ancestors included."""
    seen: set[str] = set()
    todo = [module]
    while todo:
        name = todo.pop()
        parts = name.split(".")
        for i in range(1, len(parts) + 1):
            ancestor = ".".join(parts[:i])
            if ancestor in seen:
                continue
            path = _source_path(ancestor, roots)
            if path is None:
                continue
            seen.add(ancestor)
            todo.extend(_module_level_imports(path, ancestor))
    return seen


def static_offenders(module: str, roots: tuple[Path, ...] = (SRC_DIR,)) -> set[str]:
    return {m for m in static_closure(module, roots) if m.startswith(FORBIDDEN_PREFIXES)}


def runtime_offenders(module: str, extra_path: Path | None = None) -> set[str]:
    code = (f"import sys\nsys.path.insert(0, {str(extra_path)!r})\n" if extra_path else "") + (
        "import importlib, sys\n"
        f"importlib.import_module({module!r})\n"
        f"bad = sorted(m for m in sys.modules if m.startswith({FORBIDDEN_PREFIXES!r}))\n"
        "print('\\n'.join(bad))\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr
    return {line for line in done.stdout.splitlines() if line}


@pytest.mark.parametrize("module", ENTRY_MODULES)
def test_aut6_entry_points_import_no_adapter_and_no_crh_package(module: str) -> None:
    assert static_closure(module), "the walk found nothing: the check would be vacuous"
    assert static_offenders(module) == set(), module
    assert runtime_offenders(module) == set(), module


def test_import_closure_positive_control_fails_both_checks(tmp_path: Path) -> None:
    """A fixture entry module importing ``trial_day_latch`` fails the walk and the subprocess."""
    fixture = tmp_path / "aut6_fixture_entry.py"
    fixture.write_text(
        "from breezy.strategy.current_rung_hold import trial_day_latch\n", encoding="utf-8"
    )
    roots = (tmp_path, SRC_DIR)
    assert static_offenders("aut6_fixture_entry", roots) != set()
    assert runtime_offenders("aut6_fixture_entry", tmp_path) != set()
