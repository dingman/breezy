"""The generated closure manifest is a pure literal: a name in it is data, never a use.

``src/breezy/persistence/autonomy/closure_manifest.py`` lists every module of each pinned closure
as a string. Source-text guards that scan ``src/`` for a module name (the canary store, the exit
gate) would trip on that list, so they exempt the one file and call :func:`assert_pure_literal` so
the exemption cannot become a hiding place for code.
"""

from __future__ import annotations

import ast
from pathlib import Path

__all__ = ["assert_pure_literal", "is_pure_literal"]


def is_pure_literal(source: str) -> bool:
    """A docstring, two ``from`` imports and ONE annotated ``MappingProxyType`` literal whose keys
    are strings and whose values are tuples of strings (data only, never an expression)."""
    body = ast.parse(source).body
    if [type(n) for n in body] != [ast.Expr, ast.ImportFrom, ast.ImportFrom, ast.AnnAssign]:
        return False
    imports = {
        (n.module, tuple(a.name for a in n.names)) for n in body if isinstance(n, ast.ImportFrom)
    }
    if imports != {("types", ("MappingProxyType",)), ("typing", ("Final",))}:
        return False
    assign = body[3]
    value = assign.value if isinstance(assign, ast.AnnAssign) else None
    if not (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id == "MappingProxyType"
        and len(value.args) == 1
    ):
        return False
    try:
        data = ast.literal_eval(value.args[0])
    except ValueError:
        return False
    return isinstance(data, dict) and all(
        isinstance(key, str)
        and isinstance(names, tuple)
        and all(isinstance(name, str) for name in names)
        for key, names in data.items()
    )


def assert_pure_literal(path: Path) -> None:
    assert is_pure_literal(path.read_text(encoding="utf-8")), f"{path.name} is not a pure literal"
