"""Shared AST-scan plumbing for the ARCH-0 autonomy envelope and one-writer gates.

Every scan is a pure function ``(path, source) -> list[Finding]`` so a test can run it over the real
tree and over a planted source string with the same code. Judged-file enumeration is separate, so a
test can also assert a minimum judged count and fail a vacuous scan.
"""

from __future__ import annotations

import ast
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from tests.support.entry_points import REPO_ROOT, SCRIPTS_DIR, SRC_DIR

__all__ = [
    "Finding",
    "ScanFn",
    "autonomy_source_files",
    "core_source_files",
    "imported_modules",
    "module_name",
    "package_of",
    "relative_path",
    "scan_files",
    "walk_with_scope",
]

_BREEZY_SRC: Final[Path] = SRC_DIR / "breezy"
_CORE_DIR: Final[Path] = _BREEZY_SRC / "persistence" / "autonomy"


@dataclass(frozen=True, slots=True)
class Finding:
    """One scan hit; ``scope`` is the enclosing function's qualified name ('' at module level)."""

    path: str
    lineno: int
    rule: str
    detail: str
    scope: str = ""


ScanFn = Callable[[str, str], list[Finding]]


def relative_path(path: Path) -> str:
    """The repo-relative POSIX path of ``path``."""
    return path.resolve().relative_to(REPO_ROOT).as_posix()


def autonomy_source_files() -> list[Path]:
    """Every autonomy-owned Python source: any ``autonomy`` package under ``src/breezy`` plus any
    ``*autonomy*.py`` module or script (operator CLIs and cut-over scripts land under ``scripts/``).
    """
    found = {
        p for p in _BREEZY_SRC.rglob("*.py") if "autonomy" in p.relative_to(_BREEZY_SRC).parts[:-1]
    }
    found |= {p for p in _BREEZY_SRC.rglob("*autonomy*.py")}
    found |= {p for p in SCRIPTS_DIR.rglob("*autonomy*.py")}
    return sorted(found)


def core_source_files() -> list[Path]:
    """The ARCH-0 core: every module of ``breezy.persistence.autonomy``."""
    return sorted(_CORE_DIR.glob("*.py"))


def module_name(path: Path) -> str:
    """Dotted module name of a repo file (``src/breezy/a/b.py`` -> ``breezy.a.b``)."""
    relative = path.resolve().relative_to(REPO_ROOT)
    parts = list(relative.with_suffix("").parts)
    if parts[0] == "src":
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def package_of(relative: str) -> str:
    """Package a repo-relative source path belongs to, for resolving relative imports."""
    parts = list(Path(relative).with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts[:-1])  # a package's __init__ and a plain module share their parent


def scan_files(files: Iterable[Path], scan: ScanFn) -> list[Finding]:
    """Run ``scan`` over each file; the path handed to the scan is repo-relative."""
    findings: list[Finding] = []
    for path in files:
        findings.extend(scan(relative_path(path), path.read_text(encoding="utf-8")))
    return findings


def walk_with_scope(tree: ast.AST) -> Iterator[tuple[ast.AST, str]]:
    """Every node with its enclosing function or class qualified name ('' at module level)."""

    def visit(node: ast.AST, scope: str) -> Iterator[tuple[ast.AST, str]]:
        yield node, scope
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            scope = f"{scope}.{node.name}" if scope else node.name
        for child in ast.iter_child_nodes(node):
            yield from visit(child, scope)

    yield from visit(tree, "")


def imported_modules(tree: ast.AST, *, package: str = "") -> list[tuple[str, int]]:
    """Every module a file imports, with line numbers, absolute names only.

    ``from a.b import c`` yields ``a.b`` and ``a.b.c`` so a ban on a submodule cannot hide behind a
    package import. Relative imports resolve against ``package`` (the importing module's package).
    """
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(node, package)
            if base is None:
                continue
            found.append((base, node.lineno))
            found.extend((f"{base}.{alias.name}", node.lineno) for alias in node.names)
    return found


def _resolve_from(node: ast.ImportFrom, package: str) -> str | None:
    if node.level == 0:
        return node.module
    parts = package.split(".") if package else []
    keep = len(parts) - (node.level - 1)
    if keep < 0:
        return None
    base = ".".join(parts[:keep])
    if node.module:
        return f"{base}.{node.module}" if base else node.module
    return base or None
