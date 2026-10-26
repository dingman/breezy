"""AST analysis of the split test files for the parallel gate (stdlib only).

Affinity: which tests use an expensive module-scoped fixture and must share one
process. Drift: reasons a split file is no longer safe to cut at function
granularity. Used by ``gate_shards.py`` and pinned by ``tests/unit/test_gate_shards.py``.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

_WIDE_SCOPES: Final[frozenset[str]] = frozenset({"class", "module", "package", "session"})
_MUTATORS: Final[frozenset[str]] = frozenset(
    {
        "append",
        "extend",
        "add",
        "update",
        "setdefault",
        "pop",
        "clear",
        "insert",
        "remove",
        "discard",
        "popitem",
    }
)
_CONTAINER_CALLS: Final[frozenset[str]] = frozenset(
    {"list", "dict", "set", "defaultdict", "deque", "Counter", "OrderedDict"}
)


def _fixture_options(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict[str, Any] | None:
    """Keyword options of a ``@pytest.fixture`` decorator, or ``None`` if not a fixture."""
    for deco in node.decorator_list:
        target = deco.func if isinstance(deco, ast.Call) else deco
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name != "fixture":
            continue
        options: dict[str, Any] = {}
        if isinstance(deco, ast.Call):
            for kw in deco.keywords:
                if kw.arg and isinstance(kw.value, ast.Constant):
                    options[kw.arg] = kw.value.value
        return options
    return None


def _fixture_scope(options: Mapping[str, Any]) -> str:
    return str(options.get("scope", "function"))


def _functions(tree: ast.AST) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def _arg_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    args = node.args
    return {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}


def affinity_consumers(source: str, fixtures: Iterable[str]) -> set[str]:
    """Test names (``test_f`` / ``Class::test_m``) using ``fixtures``, directly or
    through another fixture defined in the same file."""
    tree = ast.parse(source)
    fixture_defs = {
        f.name: _arg_names(f) for f in _functions(tree) if _fixture_options(f) is not None
    }
    affected = set(fixtures)
    changed = True
    while changed:
        changed = False
        for name, args in fixture_defs.items():
            if name not in affected and args & affected:
                affected.add(name)
                changed = True
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test") and _arg_names(node) & affected:
                found.add(node.name)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name.startswith("test")
                    and _arg_names(item) & affected
                ):
                    found.add(f"{node.name}::{item.name}")
    return found


def _has_teardown_after_yield(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    yields = [n for n in ast.walk(node) if isinstance(n, (ast.Yield, ast.YieldFrom))]
    if not yields:
        return False
    last = node.body[-1]
    final_plain_yield = (
        len(yields) == 1 and isinstance(last, ast.Expr) and isinstance(last.value, ast.Yield)
    )
    return not final_plain_yield


def _module_accumulators(tree: ast.Module) -> dict[str, int]:
    """Module-level container names that some function mutates (name -> line)."""
    containers: set[str] = set()
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign):
            continue
        value = stmt.value
        is_container = isinstance(value, (ast.List, ast.Dict, ast.Set)) or (
            isinstance(value, ast.Call)
            and getattr(value.func, "id", getattr(value.func, "attr", "")) in _CONTAINER_CALLS
        )
        if is_container:
            containers |= {t.id for t in stmt.targets if isinstance(t, ast.Name)}
    mutated: dict[str, int] = {}
    for func in _functions(tree):
        for node in ast.walk(func):
            target: ast.AST | None = None
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in _MUTATORS:
                    target = node.func.value
            elif isinstance(node, (ast.Assign, ast.AugAssign, ast.Delete)):
                targets = (
                    node.targets if isinstance(node, (ast.Assign, ast.Delete)) else [node.target]
                )
                for t in targets:
                    if isinstance(t, ast.Subscript):
                        target = t.value
            if isinstance(target, ast.Name) and target.id in containers:
                mutated.setdefault(target.id, getattr(node, "lineno", 0))
    return mutated


def _wide_conftest_fixtures(conftest_sources: Iterable[str]) -> dict[str, str]:
    wide: dict[str, str] = {}
    for source in conftest_sources:
        for func in _functions(ast.parse(source)):
            options = _fixture_options(func)
            if options is not None and _fixture_scope(options) in _WIDE_SCOPES:
                wide[func.name] = _fixture_scope(options)
    return wide


def drift_problems(
    source: str, fixtures: Sequence[str], conftest_sources: Iterable[str] = ()
) -> list[str]:
    """Reasons ``source`` is no longer safe to cut at function granularity."""
    tree = ast.parse(source)
    problems: list[str] = []
    defs = {f.name: f for f in _functions(tree) if _fixture_options(f) is not None}
    for name in fixtures:
        func = defs.get(name)
        options = _fixture_options(func) if func is not None else None
        if func is None or options is None:
            problems.append(f"affinity fixture {name!r} is missing")
        elif _fixture_scope(options) != "module":
            problems.append(f"affinity fixture {name!r} is not scope='module'")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {"usefixtures", "getfixturevalue"}:
            problems.append(f"{node.attr} at line {node.lineno} hides fixture use from the sharder")
    for name, func in defs.items():
        options = _fixture_options(func) or {}
        scope = _fixture_scope(options)
        if options.get("autouse") and scope in _WIDE_SCOPES:
            problems.append(f"autouse fixture {name!r} has scope {scope!r}")
        if scope in _WIDE_SCOPES and _has_teardown_after_yield(func):
            problems.append(f"{scope}-scoped fixture {name!r} has code after yield")
    for name, line in sorted(_module_accumulators(tree).items()):
        problems.append(f"module-level accumulator {name} is mutated (line {line})")
    wide = _wide_conftest_fixtures(conftest_sources)
    used = {a for f in _functions(tree) for a in _arg_names(f)}
    for name in sorted(set(wide) & used):
        problems.append(f"uses conftest fixture {name!r} (scope {wide[name]!r})")
    return problems
