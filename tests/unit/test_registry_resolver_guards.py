"""ARCH-0 seam 8c: source guards on the resolver (consumer-blocked until AUT-5a)."""

from __future__ import annotations

import ast
from typing import Final

import pytest

from breezy.persistence.autonomy.family_bytes import (
    CHILD_MANIFEST_ALLOWLIST,
)
from tests.support.entry_points import SRC_DIR

AUTONOMY_SRC: Final = SRC_DIR / "breezy" / "persistence" / "autonomy"
RESOLVER_SOURCE: Final = AUTONOMY_SRC / "resolver.py"


# --- guards: nothing outside the resolver reaches it, and nothing reaches the private gate ---

RESOLVER_MODULE: Final = "breezy.persistence.autonomy.resolver"
LIVE_PACKAGES: Final = ("strategy", "runtime", "adapters")


def _imports_resolver(source: str) -> list[int]:
    """Line numbers where ``source`` imports the resolver module (any import form, or a dynamic
    import of its dotted name)."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            lines += [node.lineno for a in node.names if a.name == RESOLVER_MODULE]
        elif isinstance(node, ast.ImportFrom) and node.module:
            hit = node.module == RESOLVER_MODULE or (
                node.module == "breezy.persistence.autonomy"
                and any(a.name == "resolver" for a in node.names)
            )
            if hit:
                lines.append(node.lineno)
        elif isinstance(node, ast.Constant) and node.value == RESOLVER_MODULE:
            lines.append(node.lineno)
    return lines


def test_no_live_process_imports_the_resolver_until_aut_5a() -> None:
    """AUT-5a removes this guard. Until then no strategy, runtime or adapters module (the live
    processes' code) may import ``resolver``, so the live path is byte-for-byte unchanged."""
    judged = 0
    hits: list[str] = []
    for package in LIVE_PACKAGES:
        for path in sorted((SRC_DIR / "breezy" / package).rglob("*.py")):
            judged += 1
            hits += [f"{path}:{n}" for n in _imports_resolver(path.read_text(encoding="utf-8"))]
    assert judged > 50  # not vacuous
    assert hits == []


@pytest.mark.parametrize(
    "planted",
    [
        "import breezy.persistence.autonomy.resolver\n",
        "from breezy.persistence.autonomy.resolver import resolve_sending_family\n",
        "from breezy.persistence.autonomy import resolver\n",
        "import importlib\nimportlib.import_module('breezy.persistence.autonomy.resolver')\n",
    ],
    ids=["import", "from-module", "from-package", "dynamic"],
)
def test_the_resolver_guard_fires_on_every_import_form(planted: str) -> None:
    assert _imports_resolver(planted)
    assert _imports_resolver("from breezy.persistence.autonomy import replay\n") == []


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
