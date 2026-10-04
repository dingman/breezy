"""ARCH-0 seam 8c: source guards on the resolver (consumer-blocked until AUT-5a)."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest

from breezy.persistence.autonomy.byte_binding import (
    CHILD_MANIFEST_ALLOWLIST,
)
from tests.support.entry_points import REPO_ROOT, SRC_DIR

AUTONOMY_SRC: Final = SRC_DIR / "breezy" / "persistence" / "autonomy"
RESOLVER_SOURCE: Final = AUTONOMY_SRC / "resolver.py"


# --- guards: nothing outside the autonomy package reaches the resolver (A8c-R2a) ---

RESOLVER_MODULE: Final = "breezy.persistence.autonomy.resolver"
AUTONOMY_PACKAGE: Final = "breezy.persistence.autonomy"
PERSISTENCE_PACKAGE: Final = "breezy.persistence"
SCAN_ROOTS: Final = (SRC_DIR, REPO_ROOT / "scripts")


def _module_of(path: Path) -> str:
    """The dotted module of ``path`` under ``src/``; a script is ``scripts.<stem path>``."""
    if path.is_relative_to(SRC_DIR):
        parts = path.relative_to(SRC_DIR).with_suffix("").parts
    else:
        parts = ("scripts", *path.relative_to(REPO_ROOT / "scripts").with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def _absolute(node: ast.ImportFrom, module: str, *, is_package: bool) -> str | None:
    """The dotted module an ``ImportFrom`` names, with a relative level resolved against
    ``module`` (``None`` when the level climbs out of the tree)."""
    if node.level == 0:
        return node.module
    base = module.split(".") if is_package else module.split(".")[:-1]
    climb = node.level - 1
    if climb > len(base):
        return None
    anchor = base[: len(base) - climb]
    return ".".join([*anchor, *([node.module] if node.module else [])])


def _imports_resolver(source: str, module: str = "", *, is_package: bool = False) -> list[int]:
    """Line numbers where ``source`` (the module ``module``) reaches the resolver: any import form
    (relative levels resolved), a dynamic import of its dotted name, or an attribute access
    ``autonomy.resolver`` on an imported ``autonomy`` package."""
    lines: list[int] = []
    package_names: set[str] = set()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == RESOLVER_MODULE:
                    lines.append(node.lineno)
                if alias.name == AUTONOMY_PACKAGE and alias.asname:
                    package_names.add(alias.asname)
        elif isinstance(node, ast.ImportFrom):
            target = _absolute(node, module, is_package=is_package)
            if target is None:
                continue
            if target == RESOLVER_MODULE:
                lines.append(node.lineno)
            for alias in node.names:
                if target == AUTONOMY_PACKAGE and alias.name == "resolver":
                    lines.append(node.lineno)
                if target == PERSISTENCE_PACKAGE and alias.name == "autonomy":
                    package_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Constant) and node.value == RESOLVER_MODULE:
            lines.append(node.lineno)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Attribute) and node.attr == "resolver"):
            continue
        dotted = ast.unparse(node.value)
        if dotted in package_names or dotted == AUTONOMY_PACKAGE:
            lines.append(node.lineno)
    return sorted(set(lines))


def _is_sanctioned(module: str) -> bool:
    """Only the autonomy package itself may name the resolver (AUT-5a amends this)."""
    return module.startswith(f"{AUTONOMY_PACKAGE}.")


def test_nothing_outside_the_autonomy_package_imports_the_resolver_until_aut_5a() -> None:
    """AUT-5a amends this guard. Until then no module of ``src/`` or ``scripts/`` outside
    ``breezy.persistence.autonomy`` may reach ``resolver`` (strategy, runtime, adapters, app,
    persistence siblings and scripts alike), so the live path is byte-for-byte unchanged."""
    judged = 0
    hits: list[str] = []
    for base in SCAN_ROOTS:
        for path in sorted(base.rglob("*.py")):
            module = _module_of(path)
            if _is_sanctioned(module):
                continue
            judged += 1
            source = path.read_text(encoding="utf-8")
            hits += [
                f"{path}:{n}"
                for n in _imports_resolver(source, module, is_package=path.name == "__init__.py")
            ]
    assert judged > 300  # not vacuous: every non-autonomy module of src/ and scripts/
    assert hits == []


@pytest.mark.parametrize(
    ("planted", "module"),
    [
        ("import breezy.persistence.autonomy.resolver\n", "breezy.strategy.x"),
        (
            "from breezy.persistence.autonomy.resolver import resolve_sending_family\n",
            "breezy.runtime.x",
        ),
        ("from breezy.persistence.autonomy import resolver\n", "breezy.adapters.x"),
        (
            "import importlib\nimportlib.import_module('breezy.persistence.autonomy.resolver')\n",
            "breezy.strategy.x",
        ),
        ("from ..persistence.autonomy import resolver\n", "breezy.app.x"),
        ("from ..persistence.autonomy.resolver import resolve_sending_family\n", "breezy.app.x"),
        ("from .autonomy import resolver\n", "breezy.persistence.sibling"),
        ("from breezy.persistence import autonomy\nautonomy.resolver.x\n", "breezy.app.x"),
        (
            "import breezy.persistence.autonomy as aut\nprint(aut.resolver)\n",
            "breezy.app.x",
        ),
        ("import breezy.persistence.autonomy\nbreezy.persistence.autonomy.resolver\n", "scripts.x"),
    ],
    ids=[
        "import", "from-module", "from-package", "dynamic", "relative-package",
        "relative-module", "relative-sibling", "attribute", "aliased-attribute", "dotted-attribute",
    ],
)  # fmt: skip
def test_the_resolver_guard_fires_on_every_import_form(planted: str, module: str) -> None:
    assert _imports_resolver(planted, module)
    assert not _is_sanctioned(module)
    assert _imports_resolver("from breezy.persistence.autonomy import replay\n", module) == []
    assert _imports_resolver("from ..persistence.autonomy import replay\n", module) == []


def test_the_resolver_guard_exempts_only_the_autonomy_package() -> None:
    assert _is_sanctioned("breezy.persistence.autonomy.replay")
    assert _is_sanctioned("breezy.persistence.autonomy.resolver")
    assert not _is_sanctioned("breezy.persistence.autonomy")  # the package init is no importer
    for outsider in ("breezy.app.trade", "breezy.persistence.family_manifest", "scripts.ops.x"):
        assert not _is_sanctioned(outsider)
    # a relative import inside the package resolves to the resolver and is sanctioned by module
    inside = "breezy.persistence.autonomy.replay"
    assert _imports_resolver("from . import resolver\n", inside)
    assert _is_sanctioned(inside)


def test_nothing_outside_live_orders_gate_references_the_private_lineage_gate() -> None:
    """8a review L1: the resolver calls only the public ``lineage_policy_authorized``."""
    offenders: list[str] = []
    judged = 0
    for path in sorted((SRC_DIR / "breezy").rglob("*.py")):
        if path.name == "live_orders_gate.py":
            continue
        judged += 1
        for line in _private_gate_references(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.name}:{line}")
    assert judged > 100 and offenders == []
    assert "lineage_policy_authorized" in RESOLVER_SOURCE.read_text(encoding="utf-8")


def _private_gate_references(source: str) -> list[int]:
    found: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Name)
            and node.id == "_lineage_policy_authorized"
            or isinstance(node, ast.Attribute)
            and node.attr == "_lineage_policy_authorized"
        ):
            found.append(node.lineno)
        elif isinstance(node, ast.alias) and node.name == "_lineage_policy_authorized":
            found.append(getattr(node, "lineno", 0))
        elif isinstance(node, ast.Constant) and node.value == "_lineage_policy_authorized":
            found.append(node.lineno)
    return found


@pytest.mark.parametrize(
    "planted",
    [
        "from breezy.persistence.live_orders_gate import _lineage_policy_authorized\n",
        "import breezy.persistence.live_orders_gate as g\ng._lineage_policy_authorized(1)\n",
        "x = '_lineage_policy_authorized'\n",
    ],
)
def test_the_private_gate_scan_fires_on_each_form(planted: str) -> None:
    assert _private_gate_references(planted)
    assert _private_gate_references("from x import lineage_policy_authorized\n") == []


def test_exit_gate_stays_code_only() -> None:
    """The exit rule is a code-committed allowlist: the registry cannot declare one. ``exit_gate``
    imports only the manifest type, the autonomy package never imports it, and a child's
    ``exit_rule`` is not allowlisted, so a child that declares one differs from its root."""
    gate = (SRC_DIR / "breezy" / "persistence" / "exit_gate.py").read_text(encoding="utf-8")
    tree = ast.parse(gate)
    imported = {
        n.module
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("breezy")
    }
    assert imported == {"breezy.persistence.family_manifest"}
    assert "_EXIT_RULE_REGISTERED_FAMILIES: Final[frozenset[str]]" in gate
    for path in AUTONOMY_SRC.glob("*.py"):
        assert "exit_gate" not in path.read_text(encoding="utf-8"), path.name
    assert "exit_rule" not in CHILD_MANIFEST_ALLOWLIST
    assert "no_leg_exit" not in CHILD_MANIFEST_ALLOWLIST


# --- A8d-R3 (SEC 2): inside the autonomy package too, an import-node allowlist ---

#: The autonomy modules that may import the resolver. Empty: its only consumers are AUT-5a's
#: (outside the package) and the tests.
AUTONOMY_RESOLVER_IMPORTERS: Final[frozenset[str]] = frozenset()


def _import_nodes_naming_resolver(source: str, module: str) -> list[int]:
    """Lines of the Import and ImportFrom nodes of ``source`` that name the resolver."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            if any(a.name == RESOLVER_MODULE for a in node.names):
                lines.append(node.lineno)
        elif isinstance(node, ast.ImportFrom):
            target = _absolute(node, module, is_package=False)
            if target == RESOLVER_MODULE or (
                target == AUTONOMY_PACKAGE and any(a.name == "resolver" for a in node.names)
            ):
                lines.append(node.lineno)
    return lines


def test_no_autonomy_module_imports_the_resolver_outside_the_allowlist() -> None:
    judged, hits = 0, []
    for path in sorted(AUTONOMY_SRC.glob("*.py")):
        module = _module_of(path)
        if module == RESOLVER_MODULE or module in AUTONOMY_RESOLVER_IMPORTERS:
            continue
        judged += 1
        hits += [
            f"{path.name}:{n}"
            for n in _import_nodes_naming_resolver(path.read_text(encoding="utf-8"), module)
        ]
    assert judged > 30  # not vacuous
    assert hits == []


@pytest.mark.parametrize(
    "planted",
    [
        "import breezy.persistence.autonomy.resolver\n",
        "from breezy.persistence.autonomy.resolver import resolve_sending_family\n",
        "from breezy.persistence.autonomy import resolver\n",
        "from . import resolver\n",
        "from .resolver import ResolvedFamily\n",
    ],
)
def test_the_autonomy_import_scan_fires_on_each_form(planted: str) -> None:
    assert _import_nodes_naming_resolver(planted, "breezy.persistence.autonomy.replay")
    assert not _import_nodes_naming_resolver(
        "from breezy.persistence.autonomy import chain\n", "breezy.persistence.autonomy.replay"
    )
