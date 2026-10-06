"""F7b-core import contracts (F7B-R25).

The two pure statistics cores sit under one strict import-linter `forbidden` contract named
OUTSIDE the `ARCH-0 autonomy (` prefix (so `test_three_arch0_contracts_are_strict_forbidden`
stays at three). Every other F7b-core module carries an explicit classification row, and a
membership scan catches a new, unclassified module.
"""

from __future__ import annotations

import ast
import sys
import tomllib
from collections.abc import Collection
from pathlib import Path
from typing import Any, Final

from tests.support.entry_points import PYPROJECT_PATH, SRC_DIR

ANALYSIS: Final[Path] = SRC_DIR / "breezy" / "analysis"
CONTRACT_NAME: Final = (
    "F7b-core pure statistics cores never reach Nautilus, the live path or pyarrow"
)
PURE_CORES: Final = (
    "breezy.analysis.autonomy.eprocess",
    "breezy.analysis.autonomy.confidence_sequence",
)
FORBIDDEN: Final = {
    "nautilus_trader",
    "breezy.strategy",
    "breezy.runtime",
    "breezy.adapters",
    "breezy.app",
    "pyarrow",
}
#: The only breezy module a pure core may import (stdlib-only, no pyarrow chain: verified).
PURE_CORE_BREEZY_ALLOWED: Final = {"breezy.analysis.stats.scoring_core"}

STRICT: Final = "strict_contract"
NO_LIVE_REACH: Final = "never_reaches_nautilus_strategy_runtime_adapters"

#: module -> classification. Every F7b-core module has a row; a reasoned exemption names its reason.
CLASSIFICATION: Final[dict[str, str]] = {
    "breezy.analysis.autonomy.eprocess": STRICT,
    "breezy.analysis.autonomy.confidence_sequence": STRICT,
}


def _contract() -> dict[str, Any]:
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    named = [c for c in data["tool"]["importlinter"]["contracts"] if c["name"] == CONTRACT_NAME]
    assert len(named) == 1
    contract: dict[str, Any] = named[0]
    return contract


def _scoped_modules() -> set[str]:
    """Every F7b-core module that exists on disk: the explicit names plus the whole evaluators
    package (a new evaluator module must be classified too)."""
    found = {m for m in CLASSIFICATION if _path(m).exists()}
    evaluators = ANALYSIS / "autonomy" / "evaluators"
    if evaluators.is_dir():
        found |= {
            f"breezy.analysis.autonomy.evaluators.{p.stem}"
            for p in evaluators.glob("*.py")
            if p.stem != "__init__"
        }
    return found


def _path(module: str) -> Path:
    return SRC_DIR / Path(*module.split(".")).with_suffix(".py")


def _unclassified(existing: Collection[str], classified: Collection[str]) -> set[str]:
    return {m for m in existing if m not in classified}


def test_f7b_core_contract_is_strict_and_outside_the_arch0_prefix() -> None:
    contract = _contract()
    assert contract["type"] == "forbidden"
    assert contract["allow_indirect_imports"] is False
    assert not CONTRACT_NAME.startswith("ARCH-0 autonomy (")
    assert contract["source_modules"] == list(PURE_CORES)  # modules, never a package
    assert set(contract["forbidden_modules"]) == FORBIDDEN


def test_pure_cores_import_only_stdlib_and_scoring_core() -> None:
    for module in PURE_CORES:
        tree = ast.parse(_path(module).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, module
                names = [node.module or ""]
            for name in names:
                top = name.split(".")[0]
                assert top in sys.stdlib_module_names or top == "breezy", (module, name)
                if top == "breezy":
                    assert name in PURE_CORE_BREEZY_ALLOWED, (module, name)


def test_scoring_core_is_stdlib_only_so_the_pyarrow_ban_is_kept() -> None:
    """Verify-first (F7B-R25): `scoring_core` does not reach pyarrow."""
    tree = ast.parse((ANALYSIS / "stats" / "scoring_core.py").read_text(encoding="utf-8"))
    tops: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            tops |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            tops.add((node.module or "").split(".")[0])
    assert tops <= set(sys.stdlib_module_names) | {"__future__"}


def test_every_f7b_core_module_is_classified() -> None:
    assert _unclassified(_scoped_modules(), CLASSIFICATION) == set()
    assert set(CLASSIFICATION.values()) <= {STRICT, NO_LIVE_REACH} or all(
        v.startswith("exempt:") for v in CLASSIFICATION.values() if v not in {STRICT, NO_LIVE_REACH}
    )


def test_classification_scan_catches_a_planted_unclassified_module() -> None:
    planted = "breezy.analysis.autonomy.evaluators.zz_planted"
    existing = _scoped_modules() | {planted}
    assert _unclassified(existing, CLASSIFICATION) == {planted}
