"""Guard (A6b-R6): nothing outside ``persistence/autonomy`` may import ``fold`` until seam 7a.

``fold`` ignores SWAP_CANCEL voiding until 7a, so a consumer outside the package could widen on a
cancelled pair. Seam 7a lands the voiding and removes this guard.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from tests.support.autonomy_scan import imported_modules, package_of
from tests.support.entry_points import REPO_ROOT, SRC_DIR

FOLD_MODULE: Final = "breezy.persistence.autonomy.fold"
AUTONOMY_DIR: Final[Path] = SRC_DIR / "breezy" / "persistence" / "autonomy"


def fold_reaches(source: str, package: str) -> list[int]:
    """Line numbers where ``source`` imports ``fold`` (any form) or names it as a string."""
    tree = ast.parse(source)
    lines = [
        lineno
        for module, lineno in imported_modules(tree, package=package)
        if module == FOLD_MODULE or module.startswith(FOLD_MODULE + ".")
    ]
    lines += [
        n.lineno
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value == FOLD_MODULE
    ]
    return sorted(lines)


def test_no_module_outside_autonomy_imports_fold() -> None:
    offenders: list[str] = []
    judged = 0
    for path in sorted(SRC_DIR.rglob("*.py")):
        if AUTONOMY_DIR in path.parents:
            continue
        judged += 1
        rel = str(path.relative_to(REPO_ROOT))
        found = fold_reaches(path.read_text(encoding="utf-8"), package_of(rel))
        offenders += [f"{rel}:{n}" for n in found]
    assert judged > 100
    assert offenders == []


def test_fold_scan_fires_on_every_planted_form() -> None:
    forms = {
        "import": "import breezy.persistence.autonomy.fold\n",
        "from": "from breezy.persistence.autonomy.fold import fold\n",
        "from_package": "from breezy.persistence.autonomy import fold\n",
        "relative": "from .autonomy import fold\n",
        "relative_module": "from .autonomy.fold import fold\n",
        "string": "importlib.import_module('breezy.persistence.autonomy.fold')\n",
    }
    for name, source in forms.items():
        assert fold_reaches(source, "breezy.persistence"), name
    assert fold_reaches("from breezy.persistence.autonomy import schemas\n", "x") == []
