"""AMBIG-LATCH-RESUME Phase B: the pure attribution module is pure (T48).

Authority: ``docs/plans/backlog/BACKLOG_PLANS_2026-10-03/
AMBIG-LATCH-RESUME_plan_r6.md`` sections 2.8.5 and the T48 row.

``no_id_attribution.py`` lives OUTSIDE ``exec/``, so the NO-SEND scanners never
read its body. Its safety argument ("pure, no I/O") is therefore enforced HERE,
by AST, on the module's own source.

**Scope, stated (r6, item 5).** Each check inspects one module's OWN source. It
does not walk transitive imports. Two compensating pins close the one first-party
import the attribution module has: (b) ``account_activity.py`` is pinned the same
way, and (c) the aliased ``_parse_rfc3339_ns`` body is pinned by callee set.
Stated, not pinned: ``account_activity``'s one first-party import,
``breezy.persistence.external_capital_flows``, does file I/O (``os.open``) for
its own writer and imports ``os``/``pathlib``; it has no network import, and
``no_id_attribution`` never reaches that writer (importing runs no I/O).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from tests.unit.test_execution_egress_firewall_guard import NETWORK_IMPORT_PREFIXES

ROOT: Final[Path] = Path(__file__).resolve().parents[2]
ADAPTER_DIR: Final[Path] = ROOT / "src" / "breezy" / "adapters" / "polymarket_us"
ATTRIBUTION: Final[Path] = ADAPTER_DIR / "no_id_attribution.py"
ACTIVITY: Final[Path] = ADAPTER_DIR / "account_activity.py"

FORBIDDEN_IMPORT_ROOTS: Final[frozenset[str]] = frozenset(
    {
        "asyncio",
        "os",
        "socket",
        "ssl",
        "http",
        "urllib",
        "requests",
        "httpx",
        "aiohttp",
        "subprocess",
        "threading",
        "pathlib",
        "io",
        "nautilus_trader.network",
        *NETWORK_IMPORT_PREFIXES,
    }
)
FORBIDDEN_CALLS: Final[frozenset[str]] = frozenset(
    {"open", "exec", "eval", "__import__", "getattr"}
)

ATTRIBUTION_IMPORTS: Final[frozenset[str]] = frozenset(
    {
        "dataclasses",
        "decimal",
        "enum",
        "typing",
        "collections.abc",
        "breezy.adapters.polymarket_us.account_activity",
    }
)
ACTIVITY_IMPORTS: Final[frozenset[str]] = frozenset(
    {
        "__future__",
        "calendar",
        "hashlib",
        "logging",
        "re",
        "collections.abc",
        "dataclasses",
        "datetime",
        "decimal",
        "typing",
        "breezy.persistence.external_capital_flows",
    }
)
PARSE_RFC3339_CALLEES: Final[frozenset[str]] = frozenset(
    {
        "isinstance",
        "TypeError",
        "ValueError",
        "_RFC3339_RE.match",
        "match.groups",
        "datetime.strptime",
        ".replace",
        "calendar.timegm",
        "parsed.timetuple",
        ".ljust",
        "int",
    }
)


def _dotted(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f".{node.attr}" if base is None else f"{base}.{node.attr}"
    return None


def imported_modules(source: str) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _violates_import(module: str) -> bool:
    if module in FORBIDDEN_IMPORT_ROOTS or any(
        module.startswith(root + ".") for root in FORBIDDEN_IMPORT_ROOTS
    ):
        return True
    return (
        module.startswith(("breezy.adapters.polymarket_us.exec", "breezy.runtime"))
        or "transport" in module
        or "signing" in module
    )


def purity_violations(source: str) -> list[str]:
    """Every purity breach in ``source`` (the attribution module's rules)."""
    found = [f"import {m}" for m in sorted(imported_modules(source)) if _violates_import(m)]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Await | ast.AsyncFunctionDef | ast.AsyncFor | ast.AsyncWith):
            found.append(f"async construct {type(node).__name__}")
        if isinstance(node, ast.Call):
            callee = _dotted(node.func)
            if callee in FORBIDDEN_CALLS:
                found.append(f"call {callee}")
    return found


def activity_violations(source: str) -> list[str]:
    """``account_activity``'s rules: no async construct, no ``open``/``exec``/
    ``eval``/``__import__`` call (``getattr`` is not used there and stays legal)."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Await | ast.AsyncFunctionDef | ast.AsyncFor | ast.AsyncWith):
            found.append(f"async construct {type(node).__name__}")
        if isinstance(node, ast.Call) and _dotted(node.func) in (FORBIDDEN_CALLS - {"getattr"}):
            found.append(f"call {_dotted(node.func)}")
    return found


# (a) the attribution module ---------------------------------------------------


def test_the_attribution_module_is_pure() -> None:
    source = ATTRIBUTION.read_text(encoding="utf-8")
    assert purity_violations(source) == []


def test_the_attribution_module_import_set_is_pinned_by_equality() -> None:
    assert imported_modules(ATTRIBUTION.read_text(encoding="utf-8")) == ATTRIBUTION_IMPORTS


def test_planting_an_impurity_fires_the_purity_check() -> None:
    source = ATTRIBUTION.read_text(encoding="utf-8")
    assert purity_violations(source + "\nimport asyncio\n")
    assert purity_violations(source + "\nasync def _planted():\n    return 1\n")
    assert purity_violations(source + "\nimport os\n")
    assert purity_violations(source + "\nopen('x')\n")
    assert imported_modules(source + "\nimport json\n") != ATTRIBUTION_IMPORTS


# (b) account_activity ---------------------------------------------------------


def test_account_activity_import_set_is_pinned_by_equality_and_has_no_io_call() -> None:
    source = ACTIVITY.read_text(encoding="utf-8")
    assert imported_modules(source) == ACTIVITY_IMPORTS
    assert activity_violations(source) == []


def test_planting_into_account_activity_fires_the_pin() -> None:
    source = ACTIVITY.read_text(encoding="utf-8")
    assert imported_modules(source + "\nimport socket\n") != ACTIVITY_IMPORTS
    assert activity_violations(source + "\nopen('x')\n")
    assert activity_violations(source + "\nasync def _planted():\n    return 1\n")


# (c) the aliased function -----------------------------------------------------


def _parse_function(source: str) -> ast.FunctionDef:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name == "_parse_rfc3339_ns":
            return node
    raise AssertionError("_parse_rfc3339_ns not found")


def _callees(fn: ast.AST) -> set[str]:
    return {
        _dotted(n.func) or ast.dump(n.func)[:40] for n in ast.walk(fn) if isinstance(n, ast.Call)
    }


def test_the_aliased_rfc3339_parser_callee_set_is_pinned() -> None:
    source = ACTIVITY.read_text(encoding="utf-8")
    assert _callees(_parse_function(source)) == PARSE_RFC3339_CALLEES


def test_the_alias_is_exactly_one_additive_public_name() -> None:
    tree = ast.parse(ACTIVITY.read_text(encoding="utf-8"))
    aliases = [
        n
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "parse_rfc3339_ns" for t in n.targets)
    ]
    assert len(aliases) == 1
    assert ast.unparse(aliases[0].value) == "_parse_rfc3339_ns"


def test_planting_into_the_parser_fires_the_callee_pin() -> None:
    source = ACTIVITY.read_text(encoding="utf-8")
    planted = source.replace(
        '    if not isinstance(value, str):\n        raise TypeError("timestamp is not a string")',
        '    open("/etc/passwd")\n    if not isinstance(value, str):\n'
        '        raise TypeError("timestamp is not a string")',
        1,
    )
    assert planted != source
    assert _callees(_parse_function(planted)) != PARSE_RFC3339_CALLEES
