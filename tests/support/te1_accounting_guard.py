"""AST scanner for the TE-1 accounting guard (merge 5): who may reference ``accounting``.

The module ``breezy.analysis.labeling.accounting`` books P&L for the report; nothing else may read
it (a statistic built from accounting sums would breach AUT-2 D3, E-TE1-a). The scanner resolves a
file's imports to fully qualified names and flags:

* any ``import`` / ``from ... import`` whose resolved target is that module or below it, including
  ``from breezy.analysis.labeling import accounting`` and relative forms inside the package;
* any attribute chain that resolves, through the file's import aliases, to that module or below it;
* a string literal naming the module (``importlib.import_module``).

The bare name ``accounting`` is never matched: ``nautilus_trader.accounting`` exists.

Known gap: ``importlib.import_module`` / ``__import__`` with a COMPUTED name (anything but a string
literal naming the module) is not caught.
"""

from __future__ import annotations

import ast
from pathlib import Path

__all__ = ["TARGET", "offending_lines", "scan_file", "scan_tree"]

TARGET = "breezy.analysis.labeling.accounting"


def _module_of(path: Path, root: Path) -> str:
    """The dotted module of ``path`` under a ``src`` root, or ``""`` for a script."""
    try:
        rel = path.relative_to(root / "src")
    except ValueError:
        return ""
    parts = list(rel.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_from(node: ast.ImportFrom, module: str, is_package: bool) -> str:
    if node.level == 0:
        return node.module or ""
    base = module.split(".")
    if not is_package:
        base = base[:-1]
    base = base[: len(base) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _is_target(name: str) -> bool:
    return name == TARGET or name.startswith(TARGET + ".")


def _dotted(node: ast.AST) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def offending_lines(source: str, *, module: str = "", is_package: bool = False) -> list[int]:
    """Line numbers in ``source`` that reference the accounting module (empty when clean)."""
    return scan_tree(ast.parse(source), module=module, is_package=is_package)


def scan_tree(tree: ast.AST, *, module: str = "", is_package: bool = False) -> list[int]:
    aliases: dict[str, str] = {}
    hits: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
                if _is_target(alias.name):
                    hits.add(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            source = _resolve_from(node, module, is_package)
            for alias in node.names:
                full = f"{source}.{alias.name}" if source else alias.name
                aliases[alias.asname or alias.name] = full
                if _is_target(source) or _is_target(full):
                    hits.add(node.lineno)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            dotted = _dotted(node)
            if dotted is None:
                continue
            head, _, rest = dotted.partition(".")
            resolved = aliases.get(head, head) + ("." + rest if rest else "")
            if _is_target(resolved):
                hits.add(node.lineno)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _is_target(node.value)
        ):
            hits.add(node.lineno)
    return sorted(hits)


def scan_file(path: Path, root: Path) -> list[int]:
    module = _module_of(path, root)
    return offending_lines(
        path.read_text(encoding="utf-8"), module=module, is_package=path.name == "__init__.py"
    )
