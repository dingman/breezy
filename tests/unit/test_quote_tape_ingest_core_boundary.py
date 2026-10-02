"""The ingest core must not depend on the console entry module.

Timers and ``python -m`` load ``breezy.runtime.quote_tape_ingest_cli``.
A back-edge from the implementation module loads that entry twice: once as
``__main__`` and once under its real name. The dependency runs entry → core
only. This scan is the pin.
"""

from __future__ import annotations

import ast
from pathlib import Path

_CORE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "breezy"
    / "runtime"
    / "quote_tape_ingest_core.py"
)
_BANNED = "quote_tape_ingest_cli"


def _references(tree: ast.AST) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _BANNED in alias.name or (alias.asname is not None and _BANNED in alias.asname):
                    found.append(f"import {alias.name} (line {node.lineno})")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if _BANNED in module:
                found.append(f"from {module} (line {node.lineno})")
            for alias in node.names:
                if _BANNED in alias.name or (alias.asname is not None and _BANNED in alias.asname):
                    found.append(f"imported name {alias.name} (line {node.lineno})")
        elif isinstance(node, ast.Name) and _BANNED in node.id:
            found.append(f"name {node.id} (line {node.lineno})")
        elif isinstance(node, ast.Attribute) and _BANNED in node.attr:
            found.append(f"attribute {node.attr} (line {node.lineno})")
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _BANNED in node.value
        ):
            found.append(f"string {node.value!r} (line {node.lineno})")
    return found


def test_quote_tape_ingest_core_does_not_reference_the_cli_module() -> None:
    source = _CORE.read_text(encoding="utf-8")
    found = _references(ast.parse(source))
    assert found == []
