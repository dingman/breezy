"""AST scans for the stage-policy construction ban and the one-home rule (ARCH-0 seam A 6c; AC 15).

Every scan is a pure function of ``(path, source)`` that returns ``Finding`` rows, so one function
judges the real tree and planted sources.

* ``find_policy_violations`` judges one module under two rules.

  (i) In **every** ``src`` module: a write that targets ``pins``, ``stage_policy``, ``transitions``,
  ``live_orders_gate`` or ``family_manifest`` (assignment, ``setattr``, ``delattr``,
  ``object.__setattr__``, ``__dict__``, ``importlib.reload``, mock and monkeypatch, ``globals()``
  and ``vars()`` writes, ``sys.modules`` writes, rebinding an imported name), and any reference to
  a private seam outside its defining module.

  (ii) In every autonomy-owned module other than ``stage_policy.py``: any reference to
  ``dataclasses.replace``, ``copy.copy``, ``copy.deepcopy``, ``copy.replace``, ``object.__new__``,
  the copy dunders, ``<expr>.__class__(...)``, ``type(<expr>)(...)``, ``pickle`` loads, ``copyreg``,
  ``importlib`` and ``StagePolicy(...)`` reached through any import alias (resolved per module).

  Rule (ii) exemptions are reviewed literal rows ``(module, call description)`` and never cover a
  ``StagePolicy`` construction. Allowlist rows ``(module, finding detail)`` cover a private-seam
  reference, or a write whose target the scan cannot resolve (a ``sys.modules`` key); they never
  cover rule (ii).

* ``find_predicate_reads`` enforces that only the reviewed homes read a stage's kind sets.
"""

from __future__ import annotations

import ast
from collections.abc import Collection, Mapping
from pathlib import PurePosixPath
from typing import Final

from tests.support.autonomy_scan import Finding, walk_with_scope

__all__ = [
    "POLICY_MODULES",
    "PREDICATE_NAMES",
    "PRIVATE_SEAMS",
    "find_policy_violations",
    "find_predicate_reads",
    "in_construction_scope",
]

#: Modules whose names are policy: a write that targets any of them is refused everywhere in src.
POLICY_MODULES: Final = frozenset(
    {"pins", "stage_policy", "transitions", "live_orders_gate", "family_manifest"}
)
#: Private seam name -> the module stem that may define and use it.
PRIVATE_SEAMS: Final[Mapping[str, str]] = {
    "_append": "registry_store",
    "_resolve": "resolver",
    "_replay_full": "replay",
    "_lineage_policy_authorized": "live_orders_gate",
    "_verify_ruling_file": "live_orders_gate",
}
_BUILD_SEAM: Final = "stage_policy._build"
_BANNED_REFERENCES: Final = frozenset(
    {
        "dataclasses.replace",
        "copy.copy",
        "copy.deepcopy",
        "copy.replace",
        "object.__new__",
        "pickle.load",
        "pickle.loads",
        "copyreg",
    }
)
_DYNAMIC_IMPORT_ROOTS: Final = frozenset({"importlib", "__import__", "copyreg"})
_DYNAMIC_IMPORT_PREFIXES: Final = ("importlib.", "copyreg.")
_COPY_DUNDERS: Final = frozenset({"__copy__", "__deepcopy__", "__replace__"})
_LITERAL_ATTRS: Final = frozenset(
    {"replace", "copy", "deepcopy", "__class__", "__new__", "StagePolicy", *_COPY_DUNDERS}
)
_WRITE_CALLS: Final = frozenset({"setattr", "delattr", "object.__setattr__", "object.__delattr__"})
_MAX_ALIAS_DEPTH: Final = 8
_STAGE_POLICY_FILE: Final = "src/breezy/persistence/autonomy/stage_policy.py"

RULE_WRITE: Final = "policy-write"
RULE_SEAM: Final = "policy-private-seam"
RULE_CONSTRUCTION: Final = "policy-construction"
RULE_PREDICATE: Final = "predicate-read"

PREDICATE_NAMES: Final = frozenset(
    {
        "enabled_widening_kinds",
        "admission_implemented",
        "ENABLED_WIDENING_KINDS",
        "_ADMISSION_IMPLEMENTED",
    }
)


def in_construction_scope(path: str) -> bool:
    """True for an autonomy-owned file other than ``stage_policy.py`` (rule ii; ruling A6-R2)."""
    if path == _STAGE_POLICY_FILE:
        return False
    parts = PurePosixPath(path).parts
    if parts[:2] == ("src", "breezy"):
        return any(p.startswith("autonomy") for p in parts[2:-1]) or "autonomy" in parts[-1]
    return parts[:1] == ("scripts",) and "autonomy" in parts[-1]


def _package_of(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts[:-1])


def _absolute(node: ast.ImportFrom, package: str) -> str:
    if node.level == 0:
        return node.module or ""
    parts = package.split(".") if package else []
    base = parts[: max(len(parts) - (node.level - 1), 0)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _dotted(expr: ast.AST, aliases: Mapping[str, str]) -> str | None:
    if isinstance(expr, ast.Name):
        return aliases.get(expr.id, expr.id)
    if isinstance(expr, ast.Attribute):
        base = _dotted(expr.value, aliases)
        return f"{base}.{expr.attr}" if base is not None else None
    return None


def _import_aliases(tree: ast.AST, package: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                aliases[alias.asname or top] = alias.name if alias.asname else top
        elif isinstance(node, ast.ImportFrom):
            base = _absolute(node, package)
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{base}.{alias.name}" if base else alias.name
    return aliases


def _with_assignment_aliases(tree: ast.AST, imported: Mapping[str, str]) -> dict[str, str]:
    """Imports plus ``X = <dotted>`` aliases, resolved to a fixed point (``SP = StagePolicy``)."""
    aliases = dict(imported)
    for _ in range(_MAX_ALIAS_DEPTH):
        changed = False
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or target.id in imported:
                continue
            resolved = _dotted(node.value, aliases)
            if (
                resolved is not None
                and resolved != target.id
                and aliases.get(target.id) != resolved
            ):
                aliases[target.id] = resolved
                changed = True
        if not changed:
            break
    return aliases


def _components(dotted: str) -> list[str]:
    return dotted.split(".")


def _mentions_policy(expr: ast.AST, aliases: Mapping[str, str]) -> bool:
    """True when a name, attribute chain or string literal under ``expr`` names a policy module."""
    for node in ast.walk(expr):
        if isinstance(node, ast.Name | ast.Attribute):
            dotted = _dotted(node, aliases)
            if dotted is not None and POLICY_MODULES.intersection(_components(dotted)):
                return True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if POLICY_MODULES.intersection(_components(node.value)):
                return True
    return False


def _write_finding(path: str, node: ast.AST, detail: str) -> Finding:
    return Finding(path, getattr(node, "lineno", 0), RULE_WRITE, detail)


def _store_findings(
    path: str, node: ast.AST, aliases: Mapping[str, str], imported: Collection[str]
) -> list[Finding]:
    ctx = getattr(node, "ctx", None)
    if not isinstance(ctx, ast.Store | ast.Del):
        return []
    if isinstance(node, ast.Name):
        if node.id in imported and POLICY_MODULES.intersection(_components(aliases[node.id])):
            return [_write_finding(path, node, f"rebind:{aliases[node.id]}")]
        return []
    if isinstance(node, ast.Attribute):
        if _mentions_policy(node.value, aliases):
            return [_write_finding(path, node, f"assign:{_dotted(node, aliases)}")]
        return []
    if not isinstance(node, ast.Subscript):
        return []
    base = node.value
    if isinstance(base, ast.Call) and _dotted(base.func, aliases) in {"globals", "vars"}:
        return [_write_finding(path, node, "globals-or-vars-write")]
    if _dotted(base, aliases) == "sys.modules" or _mentions_policy(base, aliases):
        return [_write_finding(path, node, f"subscript-write:{_dotted(base, aliases)}")]
    return []


def _call_write_findings(path: str, node: ast.Call, aliases: Mapping[str, str]) -> list[Finding]:
    callee = _dotted(node.func, aliases)
    if callee is None:
        return []
    if callee in _WRITE_CALLS and node.args and _mentions_policy(node.args[0], aliases):
        return [_write_finding(path, node, callee)]
    if callee == "vars" and node.args and _mentions_policy(node.args[0], aliases):
        return [_write_finding(path, node, "vars")]
    if callee.endswith("importlib.reload") or callee == "reload":
        return [_write_finding(path, node, "importlib.reload")]
    if callee in {"importlib.import_module", "__import__"} and _mentions_policy(node, aliases):
        return [_write_finding(path, node, f"{callee}:policy")]
    return []


def _mock_findings(path: str, node: ast.AST, aliases: Mapping[str, str]) -> list[Finding]:
    if isinstance(node, ast.ImportFrom | ast.Import):
        names = [node.module or ""] if isinstance(node, ast.ImportFrom) else []
        names += [a.name for a in node.names]
        if any(n == "mock" or n.startswith(("unittest.mock", "mock.")) for n in names):
            return [_write_finding(path, node, "mock-import")]
        return []
    if isinstance(node, ast.Name | ast.Attribute):
        dotted = _dotted(node, aliases) or ""
        root = _components(dotted)[0]
        if root == "monkeypatch" or dotted.startswith("unittest.mock"):
            return [_write_finding(path, node, f"mock:{dotted}")]
    return []


def _dict_findings(path: str, node: ast.AST, aliases: Mapping[str, str]) -> list[Finding]:
    if (
        isinstance(node, ast.Attribute)
        and node.attr == "__dict__"
        and _mentions_policy(node.value, aliases)
    ):
        return [_write_finding(path, node, "__dict__")]
    return []


def _write_rule(
    path: str, tree: ast.AST, aliases: Mapping[str, str], imported: Collection[str]
) -> list[Finding]:
    found: list[Finding] = []
    for node in ast.walk(tree):
        found += _store_findings(path, node, aliases, imported)
        found += _mock_findings(path, node, aliases)
        found += _dict_findings(path, node, aliases)
        if isinstance(node, ast.Call):
            found += _call_write_findings(path, node, aliases)
    return found


def _seam_name(node: ast.AST, aliases: Mapping[str, str]) -> str | None:
    """The private seam ``node`` references, or ``None``."""
    name: str | None = None
    if isinstance(node, ast.Name):
        name = node.id
    elif isinstance(node, ast.Attribute):
        name = node.attr
    elif isinstance(node, ast.alias):
        name = node.name.split(".")[-1]
    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
        name = node.value
    if name in PRIVATE_SEAMS:
        return name
    if isinstance(node, ast.Name | ast.Attribute):
        dotted = _dotted(node, aliases) or ""
        if dotted.endswith(_BUILD_SEAM):
            return _BUILD_SEAM
    return None


def _seam_rule(
    path: str, tree: ast.AST, aliases: Mapping[str, str], allowlist: Collection[tuple[str, str]]
) -> list[Finding]:
    stem = PurePosixPath(path).stem
    found: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").endswith("stage_policy"):
            found += [
                Finding(path, node.lineno, RULE_SEAM, _BUILD_SEAM)
                for alias in node.names
                if alias.name == "_build"
            ]
        seam = _seam_name(node, aliases)
        if seam is None or (seam != _BUILD_SEAM and PRIVATE_SEAMS[seam] == stem):
            continue
        if seam == _BUILD_SEAM and stem == "stage_policy":
            continue
        if (path, seam) in allowlist:
            continue
        found.append(Finding(path, getattr(node, "lineno", 0), RULE_SEAM, seam))
    return found


def _is_type_call(expr: ast.AST, aliases: Mapping[str, str]) -> bool:
    return (
        isinstance(expr, ast.Call)
        and _dotted(expr.func, aliases) == "type"
        and len(expr.args) == 1
        and not expr.keywords
    )


def _construction_for(path: str, node: ast.AST, aliases: Mapping[str, str]) -> list[Finding]:
    def hit(detail: str) -> list[Finding]:
        return [Finding(path, getattr(node, "lineno", 0), RULE_CONSTRUCTION, detail)]

    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute) and node.func.attr == "__class__":
            return hit("<expr>.__class__(...)")
        if _is_type_call(node.func, aliases):
            return hit("type(<expr>)(...)")
        callee = _dotted(node.func, aliases) or ""
        if "StagePolicy" in _components(callee):
            return hit("StagePolicy(...)")
        if callee in {"getattr", "setattr"} and len(node.args) > 1:
            arg = node.args[1]
            if isinstance(arg, ast.Constant) and arg.value in _LITERAL_ATTRS:
                return hit(f"getattr:{arg.value}")
    if isinstance(node, ast.Name | ast.Attribute) and isinstance(node.ctx, ast.Load):
        dotted = _dotted(node, aliases) or ""
        if isinstance(node, ast.Attribute) and node.attr in _COPY_DUNDERS:
            return hit(f"<expr>.{node.attr}")
        if dotted in _BANNED_REFERENCES or dotted in _DYNAMIC_IMPORT_ROOTS:
            return hit(dotted)
        if isinstance(node, ast.Name) and dotted.startswith(_DYNAMIC_IMPORT_PREFIXES):
            return hit(dotted)
    return []


def _construction_rule(path: str, tree: ast.AST, aliases: Mapping[str, str]) -> list[Finding]:
    found: list[Finding] = []
    for node in ast.walk(tree):
        found += _construction_for(path, node, aliases)
    return found


def _exempt(finding: Finding, exemptions: Collection[tuple[str, str]]) -> bool:
    return "StagePolicy" not in finding.detail and (finding.path, finding.detail) in exemptions


def find_policy_violations(
    path: str,
    source: str,
    *,
    exemptions: Collection[tuple[str, str]] = (),
    allowlist: Collection[tuple[str, str]] = (),
) -> list[Finding]:
    """Rules (i) and (ii) over one module; ``path`` is repo-relative (it decides the scope)."""
    tree = ast.parse(source, filename=path)
    imported = _import_aliases(tree, _package_of(path))
    aliases = _with_assignment_aliases(tree, imported)
    found = [
        f for f in _write_rule(path, tree, aliases, imported) if (path, f.detail) not in allowlist
    ]
    found += _seam_rule(path, tree, aliases, allowlist)
    if in_construction_scope(path):
        found += [f for f in _construction_rule(path, tree, aliases) if not _exempt(f, exemptions)]
    return found


def find_predicate_reads(
    path: str, source: str, homes: Mapping[str, Mapping[str, Collection[str]]]
) -> list[Finding]:
    """Every reference to a stage kind set outside its reviewed home.

    ``homes[path]`` maps an enclosing scope (``"*"`` for any) to the names it may reference.
    """
    tree = ast.parse(source, filename=path)
    allowed = homes.get(path, {})
    found: list[Finding] = []
    for node, scope in walk_with_scope(tree):
        names = _predicate_names(node)
        for name in names:
            if name in allowed.get(scope, ()) or name in allowed.get("*", ()):
                continue
            found.append(Finding(path, getattr(node, "lineno", 0), RULE_PREDICATE, name, scope))
    return found


def _predicate_names(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Name):
        candidates = [node.id]
    elif isinstance(node, ast.Attribute):
        candidates = [node.attr]
    elif isinstance(node, ast.keyword):
        candidates = [node.arg or ""]
    elif isinstance(node, ast.alias):
        candidates = [node.name.split(".")[-1]]
    elif isinstance(node, ast.Constant) and isinstance(node.value, str):
        candidates = [node.value]
    elif isinstance(node, ast.arg):
        candidates = [node.arg]
    else:
        candidates = []
    return [c for c in candidates if c in PREDICATE_NAMES]
