"""Guard (A6e-R2): nothing outside ``persistence/autonomy`` may import ``registry_store`` until 7d.

Until seams 7c and 7d wire ``transitions.validate`` into ``append``, the store applies only the
structural checks (chain, extension, fold, E-16 a row shape). A consumer outside the package could
therefore write rows no semantic rule has judged. Seam 7d removes this guard.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from tests.support.autonomy_scan import imported_modules, package_of
from tests.support.entry_points import REPO_ROOT, SRC_DIR

STORE_MODULE: Final = "breezy.persistence.autonomy.registry_store"
AUTONOMY_DIR: Final[Path] = SRC_DIR / "breezy" / "persistence" / "autonomy"


def store_reaches(source: str, package: str) -> list[int]:
    """Line numbers where ``source`` imports ``registry_store`` (any form) or names it."""
    tree = ast.parse(source)
    lines = [
        lineno
        for module, lineno in imported_modules(tree, package=package)
        if module == STORE_MODULE or module.startswith(STORE_MODULE + ".")
    ]
    lines += [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value == STORE_MODULE
    ]
    return sorted(lines)


def test_no_module_outside_autonomy_imports_registry_store() -> None:
    offenders: list[str] = []
    judged = 0
    for path in sorted(SRC_DIR.rglob("*.py")):
        if AUTONOMY_DIR in path.parents:
            continue
        judged += 1
        rel = str(path.relative_to(REPO_ROOT))
        found = store_reaches(path.read_text(encoding="utf-8"), package_of(rel))
        offenders += [f"{rel}:{n}" for n in found]
    assert judged > 100
    assert offenders == []


def test_store_scan_fires_on_every_planted_form() -> None:
    forms = {
        "import": "import breezy.persistence.autonomy.registry_store\n",
        "from": "from breezy.persistence.autonomy.registry_store import RegistryStore\n",
        "from_package": "from breezy.persistence.autonomy import registry_store\n",
        "relative": "from .autonomy import registry_store\n",
        "relative_module": "from .autonomy.registry_store import RegistryStore\n",
        "string": "importlib.import_module('breezy.persistence.autonomy.registry_store')\n",
    }
    for name, source in forms.items():
        assert store_reaches(source, "breezy.persistence"), name
    assert store_reaches("from breezy.persistence.autonomy import schemas\n", "x") == []
