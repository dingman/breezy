"""AUT-4 WP2: the AUT-4 modules never import or write the AUD-18 hypothesis ledger (r11 RC-3)."""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[3] / "src" / "breezy"
_AUT4_ROOTS = (_SRC / "analysis" / "autonomy", _SRC / "analysis" / "stats")
_AUT4_FILES = (_SRC / "persistence" / "autonomy" / "sample_size.py",)
_FORBIDDEN_MODULES = ("hypothesis_ledger", "hypothesis_register")
_FORBIDDEN_LITERAL = "hypothesis_ledger.jsonl"


def _aut4_sources() -> list[Path]:
    paths = [p for root in _AUT4_ROOTS for p in root.rglob("*.py")]
    return sorted([*paths, *_AUT4_FILES])


def _imported_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(part for alias in node.names for part in alias.name.split("."))
        elif isinstance(node, ast.ImportFrom):
            names.update((node.module or "").split("."))
            names.update(alias.name for alias in node.names)
    return names


def test_aut4_never_imports_or_writes_hypothesis_ledger() -> None:
    sources = _aut4_sources()
    assert len(sources) >= 10  # non-vacuous: the AUT-4 packages are actually scanned
    for path in sources:
        tree = ast.parse(path.read_text())
        assert not _imported_names(tree) & set(_FORBIDDEN_MODULES), path
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert _FORBIDDEN_LITERAL not in node.value, path


def test_isolation_scan_fires_on_a_synthetic_violation() -> None:
    bad = ast.parse("from breezy.analysis.hypothesis_ledger import recompute_mde\n")
    assert _imported_names(bad) & set(_FORBIDDEN_MODULES)
    literal = ast.parse("path = 'x/hypothesis_ledger.jsonl'\n")
    assert any(
        isinstance(n, ast.Constant) and _FORBIDDEN_LITERAL in str(n.value)
        for n in ast.walk(literal)
    )
