"""ARCH-0 seam 2a: planted-control test for import-linter contract (c) (AC 1)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Final

import pytest

from tests.support.entry_points import SRC_DIR
from tests.support.host_python import resolve_sibling_entrypoint
from tests.unit.test_autonomy_contracts import _contract_sources

_PLANTED_PYARROW: Final[str] = (
    "\nfrom typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    import pyarrow\n"
)


def _emit_contract_c_only() -> str:
    _, contract_c = _contract_sources()
    sources = ", ".join(json.dumps(m) for m in sorted(contract_c))
    return (
        "[tool.importlinter]\n"
        'root_packages = ["breezy"]\n'
        "include_external_packages = true\n\n"
        "[[tool.importlinter.contracts]]\n"
        'name = "planted-control copy of contract (c)"\n'
        'type = "forbidden"\n'
        f"source_modules = [{sources}]\n"
        'forbidden_modules = ["pyarrow"]\n'
        "allow_indirect_imports = false\n"
    )


def _lint_copy(workdir: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": str(workdir / "src")}
    return subprocess.run(
        [str(resolve_sibling_entrypoint("lint-imports"))],
        cwd=workdir,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


@pytest.mark.heavy
@pytest.mark.parametrize("module", ["canonical"])
def test_contract_c_refuses_planted_pyarrow_reach(module: str, tmp_path: Path) -> None:
    shutil.copytree(SRC_DIR, tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__"))
    (tmp_path / "pyproject.toml").write_text(_emit_contract_c_only(), encoding="utf-8")

    clean = _lint_copy(tmp_path)
    clean_output = clean.stdout + clean.stderr
    assert clean.returncode == 0, clean_output
    assert "1 kept" in clean_output
    assert "BROKEN" not in clean_output

    target = tmp_path / "src" / "breezy" / "persistence" / "autonomy" / f"{module}.py"
    target.write_text(target.read_text(encoding="utf-8") + _PLANTED_PYARROW, encoding="utf-8")
    planted = _lint_copy(tmp_path)
    planted_output = planted.stdout + planted.stderr
    assert planted.returncode != 0, planted_output
    assert "BROKEN" in planted_output
