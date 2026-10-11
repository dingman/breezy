"""TE-2 loss taxonomy: AST guards over script source text (pure).

``holdout_violations`` is an allowlist pin: an import must name an allowed module (exact or a
dotted child, never a string-prefix lookalike), an allowed name where a name allowlist exists,
and must not reach the holdout opener, a post-freeze evidence path (any spelling), a dynamic
import, or the execution package. ``io_violations`` finds I/O imports and ``open``/``print``
calls. The forbidden spellings are assembled at runtime so this file passes its own pin.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping, Sequence
from typing import Final

_HOLDOUT_OPENER: Final = "tuodloh_nepo"[::-1]
_EXEC_PACKAGE: Final = "breezy.adapters.polymarket_us.exec"
_FROZEN_PATH: Final = re.compile(r"(^|[/\\])m1[-_ ]?v3([/\\]|$)", re.IGNORECASE)
_DYNAMIC_CALLS: Final = frozenset({"__import__", "eval", "exec", "compile"})
_IO_MODULES: Final = frozenset(
    {
        "os", "sys", "io", "pathlib", "subprocess", "sqlite3", "socket", "logging", "shutil",
        "tempfile", "urllib", "http", "ssl", "glob", "fileinput", "requests", "json", "hashlib",
    }
)  # fmt: skip
_IO_CALLS: Final = frozenset({"open", "print", "input"})


def _under(module: str, allowed: Sequence[str]) -> bool:
    """Exact-or-dotted-child match: ``math`` allows ``math.x`` but never ``mathx``."""
    return any(module == a or module.startswith(a + ".") for a in allowed)


def _static_text(node: ast.AST) -> str | None:
    """The statically known text of a string expression (constants, f-strings, ``+``)."""
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.JoinedStr):
        parts = [_static_text(v) for v in node.values]
        return None if any(p is None for p in parts) else "".join(p for p in parts if p)
    if isinstance(node, ast.FormattedValue):
        return _static_text(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _static_text(node.left), _static_text(node.right)
        return None if left is None or right is None else left + right
    return None


def _import_violations(
    node: ast.Import | ast.ImportFrom,
    allowed_modules: Sequence[str],
    allowed_names: Mapping[str, frozenset[str]],
) -> list[str]:
    found: list[str] = []
    if isinstance(node, ast.Import):
        modules = [alias.name for alias in node.names]
        names: list[ast.alias] = []
    else:
        if node.level or node.module is None:
            return [f"line {node.lineno}: relative import"]
        modules, names = [node.module], list(node.names)
    for module in modules:
        if not _under(module, allowed_modules):
            found.append(f"line {node.lineno}: module {module!r} is not on the allowlist")
        if _under(module, [_EXEC_PACKAGE]):
            found.append(f"line {node.lineno}: direct execution-package import {module!r}")
    for alias in names:
        listed = allowed_names.get(modules[0])
        if alias.name == "*" or alias.name == _HOLDOUT_OPENER:
            found.append(f"line {node.lineno}: forbidden import name {alias.name!r}")
        elif listed is not None and alias.name not in listed:
            found.append(f"line {node.lineno}: name {alias.name!r} is not on the allowlist")
    return found


def _node_violations(node: ast.AST) -> list[str]:
    line = getattr(node, "lineno", 0)
    if isinstance(node, ast.Attribute) and _HOLDOUT_OPENER in node.attr:
        return [f"line {line}: attribute access to the holdout opener"]
    if isinstance(node, ast.Name) and _HOLDOUT_OPENER in node.id:
        return [f"line {line}: name reference to the holdout opener"]
    if isinstance(node, ast.Name) and node.id in _DYNAMIC_CALLS:
        return [f"line {line}: dynamic code or import {node.id!r}"]
    text = (
        _static_text(node) if isinstance(node, ast.Constant | ast.JoinedStr | ast.BinOp) else None
    )
    if text is None:
        return []
    found = []
    if _HOLDOUT_OPENER in text.lower():
        found.append(f"line {line}: string access to the holdout opener")
    if _FROZEN_PATH.search(text):
        found.append(f"line {line}: path under a post-freeze evidence directory")
    return found


def holdout_violations(
    source: str,
    allowed_modules: Sequence[str],
    allowed_names: Mapping[str, frozenset[str]] | None = None,
) -> tuple[str, ...]:
    names = allowed_names or {}
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import | ast.ImportFrom):
            found.extend(_import_violations(node, allowed_modules, names))
        else:
            found.extend(_node_violations(node))
    return tuple(dict.fromkeys(found))


def io_violations(source: str) -> tuple[str, ...]:
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules = [node.module]
        line = getattr(node, "lineno", 0)
        found.extend(
            f"line {line}: I/O import {m!r}" for m in modules if m.split(".")[0] in _IO_MODULES
        )
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in _IO_CALLS
        ):
            found.append(f"line {line}: I/O call {node.func.id!r}")
    return tuple(found)
