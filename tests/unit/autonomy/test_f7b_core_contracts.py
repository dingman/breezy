"""F7b-core import contracts (F7B-R25).

The two pure statistics cores sit under one strict import-linter `forbidden` contract named
OUTSIDE the `ARCH-0 autonomy (` prefix (so `test_three_arch0_contracts_are_strict_forbidden`
stays at three). Every other F7b-core module carries an explicit classification row, and a
membership scan catches a new, unclassified module.
"""

from __future__ import annotations

import ast
import shutil
import sys
import tomllib
from collections.abc import Collection
from pathlib import Path
from typing import Any, Final

from tests.support.entry_points import PYPROJECT_PATH, SRC_DIR
from tests.unit.test_autonomy_contracts import _modules_loaded_by

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
EXEMPT: Final = "exempt:"
LIVE_REACH_PREFIXES: Final = (
    "nautilus_trader",
    "breezy.strategy",
    "breezy.runtime",
    "breezy.adapters",
    "breezy.app",
)

#: module -> classification. Every F7b-core module has a row; a reasoned exemption names its reason.
CLASSIFICATION: Final[dict[str, str]] = {
    "breezy.analysis.autonomy.eprocess": STRICT,
    "breezy.analysis.autonomy.confidence_sequence": STRICT,
    "breezy.analysis.autonomy.evidence_row": NO_LIVE_REACH,
    # The evaluator also hosts the C6 `label` seam (moved verbatim from `FqOfflinePlugin`), which
    # imports `labeling.fq_scorer`; offline_plugins reached that scorer before F7b-core as well.
    # `evaluate_e_process` and the guard chain use none of it.
    "breezy.analysis.autonomy.evaluators.forecast_quantile_ladder": (
        EXEMPT + "label seam reaches strategy/runtime/adapters/nautilus through labeling.fq_scorer"
    ),
    # `scoring_batch` -> `persistence.autonomy.label_store` (PYARROW_REACHING in ARCH-0 contract c).
    "breezy.analysis.labeling.scoring_batch": NO_LIVE_REACH,
}
#: Modules whose classification admits pyarrow (the exempt evaluator and scoring_batch).
PYARROW_REACHING_ROWS: Final = {
    "breezy.analysis.autonomy.evaluators.forecast_quantile_ladder",
    "breezy.analysis.labeling.scoring_batch",
}


def _contract() -> dict[str, Any]:
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    named = [c for c in data["tool"]["importlinter"]["contracts"] if c["name"] == CONTRACT_NAME]
    assert len(named) == 1
    contract: dict[str, Any] = named[0]
    return contract


AUTONOMY_ROOT: Final[Path] = ANALYSIS / "autonomy"
AUTONOMY_PREFIX: Final = "breezy.analysis.autonomy"

#: Every module under `analysis/autonomy/**` that existed at 1ecacc87 (before F7b-core). They carry
#: their own ARCH-0 classification; a module in neither this set nor CLASSIFICATION fails the scan.
PRE_EXISTING_AUTONOMY_MODULES: Final = frozenset(
    {
        "breezy.analysis.autonomy.budget",
        "breezy.analysis.autonomy.calibration_ni",
        "breezy.analysis.autonomy.eval_stats",
        "breezy.analysis.autonomy.leakage",
        "breezy.analysis.autonomy.metric_registry",
        "breezy.analysis.autonomy.offline_plugins",
        "breezy.analysis.autonomy.permutation",
        "breezy.analysis.autonomy.seeding",
        "breezy.analysis.autonomy.windows",
    }
)


def _scoped_modules(root: Path = AUTONOMY_ROOT) -> set[str]:
    """Every module under `analysis/autonomy/**` (package `__init__` files excluded), so a new
    module anywhere there must be classified or allowlisted."""
    return {
        ".".join((AUTONOMY_PREFIX, *p.relative_to(root).with_suffix("").parts))
        for p in root.rglob("*.py")
        if p.stem != "__init__" and "__pycache__" not in p.parts
    }


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
    known = set(CLASSIFICATION) | PRE_EXISTING_AUTONOMY_MODULES
    assert _unclassified(_scoped_modules(), known) == set()
    assert {m for m in CLASSIFICATION if m.startswith(AUTONOMY_PREFIX)} <= _scoped_modules()
    for module, value in CLASSIFICATION.items():
        assert value in {STRICT, NO_LIVE_REACH} or value.startswith(EXEMPT), module
        if value.startswith(EXEMPT):
            assert len(value) > len(EXEMPT) + 20, f"{module}: an exemption needs a reason"


def _reaches(module: str) -> tuple[set[str], bool]:
    loaded = _modules_loaded_by(module)
    live = {m for m in loaded if m.startswith(LIVE_REACH_PREFIXES)}
    return live, any(m.split(".")[0] == "pyarrow" for m in loaded)


def test_each_classification_row_is_true_at_runtime() -> None:
    """The rows are measured, not asserted: a probe imports each module in a fresh interpreter."""
    for module, value in CLASSIFICATION.items():
        live, arrow = _reaches(module)
        if value == STRICT:
            assert live == set() and not arrow, module
        elif value == NO_LIVE_REACH:
            assert live == set(), module
            assert arrow == (module in PYARROW_REACHING_ROWS), module
        else:  # an exemption must still be a real reach, or it should be reclassified
            assert live != set(), module


def test_classification_scan_catches_a_planted_unclassified_module(tmp_path: Path) -> None:
    """The REAL scan, pointed at a copy of the tree: a new module anywhere under autonomy/**
    (top level or a new package) is reported; the allowlist and CLASSIFICATION are not."""
    root = tmp_path / "autonomy"
    shutil.copytree(AUTONOMY_ROOT, root, ignore=shutil.ignore_patterns("__pycache__"))
    known = set(CLASSIFICATION) | PRE_EXISTING_AUTONOMY_MODULES
    assert _unclassified(_scoped_modules(root), known) == set()
    (root / "zz_planted_top.py").write_text("", encoding="utf-8")
    (root / "newpkg").mkdir()
    (root / "newpkg" / "zz_planted_nested.py").write_text("", encoding="utf-8")
    assert _unclassified(_scoped_modules(root), known) == {
        f"{AUTONOMY_PREFIX}.zz_planted_top",
        f"{AUTONOMY_PREFIX}.newpkg.zz_planted_nested",
    }
