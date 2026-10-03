"""ARCH-0 seam 2a: autonomy package contract tests (AC 1)."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path
from typing import Any, Final

from tests.support.entry_points import PYPROJECT_PATH, SRC_DIR

AUTONOMY_DIR: Final[Path] = SRC_DIR / "breezy" / "persistence" / "autonomy"
AUTONOMY_PACKAGE: Final[str] = "breezy.persistence.autonomy"


def _contracts() -> list[dict[str, Any]]:
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    contracts: list[dict[str, Any]] = data["tool"]["importlinter"]["contracts"]
    return [c for c in contracts if "autonomy" in c["name"].lower() and "ARCH-0" in c["name"]]


def test_autonomy_init_has_no_import_nodes() -> None:
    tree = ast.parse((AUTONOMY_DIR / "__init__.py").read_text(encoding="utf-8"))
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)]
    assert nodes == []
    assert ast.get_docstring(tree)


def test_three_arch0_contracts_are_strict_forbidden() -> None:
    contracts = _contracts()
    assert len(contracts) == 3
    for contract in contracts:
        assert contract["type"] == "forbidden"
        assert contract["allow_indirect_imports"] is False


def test_contract_a_names_the_package_and_forbids_adapters() -> None:
    a = [c for c in _contracts() if c["source_modules"] == [AUTONOMY_PACKAGE]]
    assert len(a) == 1
    assert a[0]["forbidden_modules"] == ["breezy.adapters"]


def test_contracts_b_and_c_list_existing_modules_only_never_the_package() -> None:
    bc = [c for c in _contracts() if c["source_modules"] != [AUTONOMY_PACKAGE]]
    assert len(bc) == 2
    existing = {f"{AUTONOMY_PACKAGE}.{p.stem}" for p in AUTONOMY_DIR.glob("*.py")} - {
        f"{AUTONOMY_PACKAGE}.__init__"
    }
    for contract in bc:
        sources = set(contract["source_modules"])
        assert AUTONOMY_PACKAGE not in sources
        assert sources <= existing
        assert len(sources) == len(contract["source_modules"])
    by_forbidden = {tuple(sorted(c["forbidden_modules"])): c for c in bc}
    b = by_forbidden[("breezy.domain", "nautilus_trader")]
    c = by_forbidden[("pyarrow",)]
    assert set(c["source_modules"]) == set(b["source_modules"]) - {
        f"{AUTONOMY_PACKAGE}.{m}"
        for m in ("label_schema", "family_bytes", "registry_store", "replay", "resolver")
    }
    assert {f"{AUTONOMY_PACKAGE}.canonical", f"{AUTONOMY_PACKAGE}.wire"} <= set(b["source_modules"])
