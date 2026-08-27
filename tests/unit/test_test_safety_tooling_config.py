"""Config guardrails for the test-safety and tooling seam."""

from __future__ import annotations

import ast
import tomllib
from pathlib import Path
from typing import Any

_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"
_REPO_ROOT = _PYPROJECT.parent
_VENUE_LIVE_MARKER = (
    "venue_live: test performs real authenticated calls against the live Polymarket.us "
    "venue; gated behind BREEZY_VENUE_LIVE=1 AND BREEZY_ALLOW_CREDENTIALED_PYTEST=1 "
    "AND --venue-live"
)
_BANNED_POLYMARKET_COM_ADAPTERS = (
    "breezy.adapters.polymarket",
    "nautilus_trader.adapters.polymarket",
)


def _pyproject() -> dict[str, Any]:
    return tomllib.loads(_PYPROJECT.read_text())


def _iter_python_files() -> list[Path]:
    roots = [_REPO_ROOT / "src", _REPO_ROOT / "scripts"]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(path for path in root.rglob("*.py") if ".venv" not in path.parts)
    return sorted(files)


def test_nautilus_trader_dependency_is_exactly_the_contract_version() -> None:
    dependencies = _pyproject()["project"]["dependencies"]

    assert "nautilus-trader==1.231.0" in dependencies
    assert not any(dep.startswith("nautilus-trader~=") for dep in dependencies)


def test_venue_live_marker_documents_the_existing_three_lock_gate() -> None:
    markers = _pyproject()["tool"]["pytest"]["ini_options"]["markers"]

    assert _VENUE_LIVE_MARKER in markers


def test_import_linter_enforces_layers_and_polymarket_com_adapter_ban() -> None:
    config = _pyproject()["tool"]["importlinter"]

    assert config["root_packages"] == ["breezy"]
    assert config["include_external_packages"] is True

    contracts = {contract["name"]: contract for contract in config["contracts"]}
    layers = contracts["Breezy top-level source packages follow the documented layer direction"]
    forbidden = contracts["Breezy never imports the Nautilus Polymarket .com adapter"]

    assert layers["type"] == "layers"
    assert layers["containers"] == ["breezy"]
    assert layers["exhaustive"] is True
    assert layers["layers"] == [
        # `strategy` is the top layer as of 2026-08-27: strategies reach DOWN
        # into `runtime` (the backtest feed's shared `ClientId`) and `ingest`
        # (the shared weather `DataType` factories), and nothing reaches back
        # up. The backtest harness in `runtime` takes strategies as
        # already-constructed objects, so it never imports one.
        "strategy",
        "runtime",
        "adapters",
        "ingest",
        "persistence | registry | normalize",
        "features | settlement",
        "domain",
    ]
    assert set(layers["ignore_imports"]) == {
        "breezy.adapters.polymarket_us.config -> breezy.runtime.settings",
        "breezy.adapters.polymarket_us.factories -> breezy.runtime.settings",
        "breezy.ingest.nws_actor -> breezy.runtime.health",
        "breezy.persistence.quote_tape_gaps -> breezy.adapters.polymarket_us.tape_records",
    }

    assert forbidden["type"] == "forbidden"
    assert forbidden["source_modules"] == ["breezy"]
    assert forbidden["forbidden_modules"] == ["nautilus_trader"]
    assert forbidden["allow_indirect_imports"] is True
    assert all(
        "nautilus_trader.adapters.polymarket" not in ignored
        for ignored in forbidden["ignore_imports"]
    )


def test_polymarket_com_adapter_imports_are_banned_repo_wide() -> None:
    offenders: list[str] = []
    for path in _iter_python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            imported_modules: list[str] = []
            if isinstance(node, ast.Import):
                imported_modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules = [node.module]

            for imported_module in imported_modules:
                if any(
                    imported_module == banned or imported_module.startswith(f"{banned}.")
                    for banned in _BANNED_POLYMARKET_COM_ADAPTERS
                ):
                    relative = path.relative_to(_REPO_ROOT)
                    offenders.append(f"{relative}:{node.lineno}: {imported_module}")

    assert offenders == []
