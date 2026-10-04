"""ARCH-0 seam 2a: autonomy package contract tests (AC 1)."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import tomllib
from collections.abc import Collection
from pathlib import Path
from typing import Any, Final

import pytest

from tests.support.entry_points import PYPROJECT_PATH, REPO_ROOT, SRC_DIR
from tests.support.host_python import resolve_breezy_python

AUTONOMY_DIR: Final[Path] = SRC_DIR / "breezy" / "persistence" / "autonomy"
AUTONOMY_PACKAGE: Final[str] = "breezy.persistence.autonomy"
#: Core modules exempt from contract (b). Empty at ARCH-0 (AC 2); AUT-1 WP1 appends the three
#: capture modules that exist to persist Nautilus custom data (the ``@customdataclass`` records,
#: the native ``StreamingFeatherWriter`` wrapper, and the publisher that builds the heartbeat
#: record), and part B appends the reader that decodes the stream through Nautilus's registered
#: Arrow decoders and enum parsers. Every other AUT-1 module is Nautilus-free and sits in contracts
#: (b) and (c).
NAUTILUS_PERMITTED: Final[frozenset[str]] = frozenset(
    f"{AUTONOMY_PACKAGE}.{m}"
    for m in ("capture_records", "capture_stream", "capture_publish", "capture_reader")
)
#: ``NAUTILUS_PERMITTED`` modules that import ``breezy.domain`` by design (``ForecastPoint``, the
#: leg helpers), and the one that imports pyarrow directly (the stream reader). The rest must not.
DOMAIN_PERMITTED: Final[frozenset[str]] = frozenset(
    f"{AUTONOMY_PACKAGE}.{m}" for m in ("capture_stream", "capture_reader")
)
PYARROW_DIRECT_PERMITTED: Final[frozenset[str]] = frozenset({f"{AUTONOMY_PACKAGE}.capture_reader"})
#: Core modules that may reach pyarrow, hence absent from contract (c) (AC 1).
PYARROW_REACHING: Final[frozenset[str]] = frozenset(
    f"{AUTONOMY_PACKAGE}.{m}"
    for m in (
        "label_schema",
        "family_bytes",
        "byte_binding",
        "registry_store",
        "replay",
        "resolver",
    )
)


def _contracts() -> list[dict[str, Any]]:
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    contracts: list[dict[str, Any]] = data["tool"]["importlinter"]["contracts"]
    # B8-R2: seam A's contracts by their exact name prefix; seam B's stdlib-only contract is pinned
    # by seam B's own test.
    return [c for c in contracts if c["name"].startswith("ARCH-0 autonomy (")]


def test_autonomy_init_has_no_import_nodes() -> None:
    tree = ast.parse((AUTONOMY_DIR / "__init__.py").read_text(encoding="utf-8"))
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.Import | ast.ImportFrom)]
    assert nodes == []
    assert ast.get_docstring(tree)


def test_three_arch0_contracts_are_strict_forbidden() -> None:
    contracts = _contracts()
    assert len(contracts) == 3
    for contract in contracts:
        assert contract["type"] == "forbidden"
        assert contract["allow_indirect_imports"] is False


def test_contract_a_names_the_package_and_forbids_adapters() -> None:
    a = [c for c in _contracts() if c["source_modules"] == [AUTONOMY_PACKAGE]]
    assert len(a) == 1
    assert a[0]["forbidden_modules"] == ["breezy.adapters"]


def test_contracts_b_and_c_list_existing_modules_only_never_the_package() -> None:
    bc = [c for c in _contracts() if c["source_modules"] != [AUTONOMY_PACKAGE]]
    assert len(bc) == 2
    existing = {f"{AUTONOMY_PACKAGE}.{p.stem}" for p in AUTONOMY_DIR.glob("*.py")} - {
        f"{AUTONOMY_PACKAGE}.__init__"
    }
    for contract in bc:
        sources = set(contract["source_modules"])
        assert AUTONOMY_PACKAGE not in sources
        assert sources <= existing
        assert len(sources) == len(contract["source_modules"])
    by_forbidden = {tuple(sorted(c["forbidden_modules"])): c for c in bc}
    b = by_forbidden[("breezy.domain", "nautilus_trader")]
    c = by_forbidden[("pyarrow",)]
    assert set(c["source_modules"]) == set(b["source_modules"]) - {
        f"{AUTONOMY_PACKAGE}.{m}"
        for m in (
            "label_schema",
            "family_bytes",
            "byte_binding",
            "byte_binding",
            "registry_store",
            "replay",
            "resolver",
        )
    }
    assert {f"{AUTONOMY_PACKAGE}.canonical", f"{AUTONOMY_PACKAGE}.wire"} <= set(b["source_modules"])


def _existing_modules() -> set[str]:
    return {
        f"{AUTONOMY_PACKAGE}.{p.stem}" for p in AUTONOMY_DIR.glob("*.py") if p.stem != "__init__"
    }


def _contract_sources() -> tuple[set[str], set[str]]:
    """(b)'s and (c)'s ``source_modules``, told apart by what they forbid."""
    by_forbidden = {
        tuple(sorted(c["forbidden_modules"])): set(c["source_modules"])
        for c in _contracts()
        if c["source_modules"] != [AUTONOMY_PACKAGE]
    }
    return by_forbidden[("breezy.domain", "nautilus_trader")], by_forbidden[("pyarrow",)]


def _classification_errors(
    existing: Collection[str], contract_b: Collection[str], permitted: Collection[str]
) -> set[str]:
    """Modules that sit in neither of the two sets, or in both."""
    return {m for m in existing if (m in contract_b) == (m in permitted)}


def test_every_autonomy_module_is_classified() -> None:
    contract_b, contract_c = _contract_sources()
    existing = _existing_modules()
    assert _classification_errors(existing, contract_b, NAUTILUS_PERMITTED) == set()
    assert contract_b - contract_c == PYARROW_REACHING & existing


def test_classification_scan_catches_a_planted_unclassified_module() -> None:
    contract_b, _ = _contract_sources()
    planted = f"{AUTONOMY_PACKAGE}.zz_planted"
    existing = _existing_modules() | {planted}
    assert _classification_errors(existing, contract_b, NAUTILUS_PERMITTED) == {planted}
    # In both sets is as wrong as in neither.
    both = _classification_errors(existing, contract_b | {planted}, NAUTILUS_PERMITTED | {planted})
    assert both == {planted}


def test_single_read_is_named_in_contracts_b_and_c() -> None:
    contract_b, contract_c = _contract_sources()
    name = f"{AUTONOMY_PACKAGE}.single_read"
    assert name in contract_b
    assert name in contract_c


_RUNTIME_PROBE: Final[str] = (
    "import importlib, json, sys; importlib.import_module(sys.argv[1]); "
    "print(json.dumps(sorted(sys.modules)))"
)


def _modules_loaded_by(module: str) -> list[str]:
    env = {**os.environ, "PYTHONPATH": str(SRC_DIR)}
    result = subprocess.run(
        [resolve_breezy_python(), "-c", _RUNTIME_PROBE, module],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=REPO_ROOT,
    )
    loaded: list[str] = json.loads(result.stdout.splitlines()[-1])
    return loaded


def _direct_imports(module: str) -> set[str]:
    """Top-level package names a module imports in its own source."""
    path = AUTONOMY_DIR / f"{module.rsplit('.', 1)[1]}.py"
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module.split(".")[0])
    return found


@pytest.mark.parametrize("module", sorted(_existing_modules()))
def test_autonomy_core_modules_nautilus_free_at_runtime(module: str) -> None:
    loaded = _modules_loaded_by(module)
    nautilus = [m for m in loaded if m.split(".")[0] == "nautilus_trader"]
    domain = [m for m in loaded if m == "breezy.domain" or m.startswith("breezy.domain.")]
    if module in NAUTILUS_PERMITTED:
        # a permitted module really does reach Nautilus (keeps the list honest)
        assert nautilus != []
        # WP1-R3 (SEC L8): only the nautilus-free assertion is skipped. Domain stays bounded to the
        # modules that import it by design, and a direct pyarrow import to the one decoder.
        if module not in DOMAIN_PERMITTED:
            assert domain == []
        if module not in PYARROW_DIRECT_PERMITTED:
            assert "pyarrow" not in _direct_imports(module)
        return
    assert nautilus == []
    assert domain == []
    if module not in PYARROW_REACHING:
        assert [m for m in loaded if m.split(".")[0] == "pyarrow"] == []


def test_runtime_probe_sees_a_known_heavy_import() -> None:
    """Positive control: the probe really reports loaded modules."""
    loaded = _modules_loaded_by("breezy.domain.instrument_leg")
    assert any(m.split(".")[0] == "nautilus_trader" for m in loaded)


AUT1_CONTRACT_NAME: Final[str] = "AUT-1 resolver consumers (removed by AUT-5a)"


def test_resolver_consumers_contract_forbids_every_live_package_strictly() -> None:
    """A8c-R2b: the import-linter half of the resolver consumer guard. Its name sits outside the
    ``ARCH-0 autonomy (`` prefix, so B8-R2's count of three is untouched. AUT-5a amends it."""
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    contracts = data["tool"]["importlinter"]["contracts"]
    named = [c for c in contracts if c["name"] == AUT1_CONTRACT_NAME]
    assert len(named) == 1
    contract = named[0]
    assert contract["type"] == "forbidden"
    assert set(contract["source_modules"]) == {
        "breezy.app",
        "breezy.strategy",
        "breezy.runtime",
        "breezy.adapters",
    }
    assert contract["forbidden_modules"] == [f"{AUTONOMY_PACKAGE}.resolver"]
    assert contract["allow_indirect_imports"] is False
    assert not AUT1_CONTRACT_NAME.startswith("ARCH-0 autonomy (")
    assert len(_contracts()) == 3


def test_contract_lists_are_final_at_the_last_seam_a_module() -> None:
    """8d: the resolver (sending and shadow) is the last seam A module. Contract (b) names every
    autonomy module, (c) every one but the pyarrow-reaching ones, and the resolver is in (b)
    only. The AUT-1 consumer contract is untouched (it names the resolver as forbidden)."""
    contract_b, contract_c = _contract_sources()
    existing = _existing_modules()
    resolver = f"{AUTONOMY_PACKAGE}.resolver"
    assert contract_b == existing
    assert contract_c == existing - PYARROW_REACHING
    assert resolver in contract_b and resolver not in contract_c
