"""ARCH-0 seam 1a import isolation for ``breezy.persistence``."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

from tests.support.entry_points import (
    REPO_ROOT,
    SRC_DIR,
    _entry_modules_from_pyproject_scripts,
    _entry_modules_from_scripts_importing,
    _entry_modules_from_systemd,
)

PERSISTENCE_INIT_PATH: Final[Path] = SRC_DIR / "breezy" / "persistence" / "__init__.py"
REMOVED_FACADE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "NETWORK_FILESYSTEM_TYPES",
        "WRITER_LOCK_FILENAME",
        "CatalogPathError",
        "CatalogWriteError",
        "ConcurrentWriterError",
        "FilesystemLocality",
        "FilesystemProbe",
        "NonMonotonicWriteError",
        "WriteOutcome",
        "WriterLockError",
        "WriterLockFilesystemError",
        "assert_writer_lock_filesystem_supported",
        "open_station_catalog",
        "probe_filesystem",
        "read_climate_day_as_of_settlement",
        "read_climate_day_including_corrections",
        "read_climate_days",
        "read_raw_products",
        "station_catalog_path",
        "write_records",
    }
)

PERSISTENCE_ENTRY_MODULES: Final[tuple[str, ...]] = tuple(
    sorted(
        _entry_modules_from_pyproject_scripts()
        | _entry_modules_from_systemd()
        | _entry_modules_from_scripts_importing("breezy.persistence")
    )
)
ENTRY_SMOKE_BUDGET_S: Final[float] = 60.0
_PERSISTENCE_PREFIX: Final[str] = "breezy.persistence."


@dataclass(frozen=True)
class FacadeConsumer:
    path: str
    lineno: int
    detail: str


@dataclass
class EntrySmokeRecorder:
    durations: list[tuple[str, float]]


@pytest.fixture(scope="module")
def entry_smoke_recorder() -> Iterator[EntrySmokeRecorder]:
    recorder = EntrySmokeRecorder([])
    yield recorder
    total = sum(duration for _, duration in recorder.durations)
    if len(recorder.durations) == len(PERSISTENCE_ENTRY_MODULES):
        assert total <= ENTRY_SMOKE_BUDGET_S, recorder.durations


def _python_files_under(relative_roots: Iterable[str]) -> Iterator[Path]:
    for relative_root in relative_roots:
        yield from sorted((REPO_ROOT / relative_root).rglob("*.py"))


def _is_mock_patch_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "patch"
    if isinstance(func, ast.Attribute):
        return func.attr == "patch"
    return False


def _first_persistence_name(target: str) -> str | None:
    if not target.startswith(_PERSISTENCE_PREFIX):
        return None
    return target.removeprefix(_PERSISTENCE_PREFIX).split(".", 1)[0]


def _string_call_targets(node: ast.Call) -> Iterator[tuple[str, str]]:
    func = node.func
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "setattr"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        yield ("setattr", node.args[0].value)

    if (
        (_is_mock_patch_call(node) or (isinstance(func, ast.Name) and func.id == "patch"))
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        yield ("patch", node.args[0].value)

    if _is_mock_patch_call(node) or (isinstance(func, ast.Name) and func.id == "patch"):
        for keyword in node.keywords:
            if (
                keyword.arg == "target"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            ):
                yield ("patch", keyword.value.value)


def _facade_consumer_hits(sources: Iterable[tuple[str, str]]) -> list[FacadeConsumer]:
    hits: list[FacadeConsumer] = []
    for path, source in sources:
        tree = ast.parse(source, filename=path)
        persistence_aliases: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "breezy.persistence":
                for alias in node.names:
                    if alias.name == "*" or alias.name in REMOVED_FACADE_NAMES:
                        hits.append(FacadeConsumer(path, node.lineno, f"from import {alias.name}"))
            elif isinstance(node, ast.ImportFrom) and node.module == "breezy":
                for alias in node.names:
                    if alias.name == "persistence":
                        persistence_aliases.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "breezy.persistence":
                        persistence_aliases.add(alias.asname or alias.name.split(".")[-1])
                    elif alias.name.startswith(_PERSISTENCE_PREFIX):
                        imported_name = alias.name.removeprefix(_PERSISTENCE_PREFIX).split(".", 1)[
                            0
                        ]
                        if imported_name in REMOVED_FACADE_NAMES:
                            hits.append(FacadeConsumer(path, node.lineno, f"import {alias.name}"))
            elif isinstance(node, ast.Call):
                for kind, target in _string_call_targets(node):
                    facade_name = _first_persistence_name(target)
                    if facade_name in REMOVED_FACADE_NAMES:
                        hits.append(FacadeConsumer(path, node.lineno, f"{kind} {target}"))
            elif (
                isinstance(node, ast.Attribute)
                and node.attr in REMOVED_FACADE_NAMES
                and isinstance(node.value, ast.Name)
                and node.value.id in persistence_aliases
            ):
                hits.append(FacadeConsumer(path, node.lineno, f"alias attribute {node.attr}"))
    return hits


def test_persistence_init_has_no_import_nodes() -> None:
    source = PERSISTENCE_INIT_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(PERSISTENCE_INIT_PATH))
    import_nodes = [
        node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert import_nodes == [], [ast.dump(node) for node in import_nodes]


def test_persistence_has_no_facade_consumers() -> None:
    planted_source = (
        "from unittest.mock import patch\n"
        "from breezy.persistence import *\n"
        "from breezy.persistence import (\n"
        "    write_records,\n"
        ")\n"
        "mock.patch('breezy.persistence.write_records')\n"
        "monkeypatch.setattr('breezy.persistence.write_records', object())\n"
        "patch(target='breezy.persistence.write_records')\n"
        "import breezy.persistence as p\n"
        "p.write_records\n"
        "from breezy import persistence\n"
        "persistence.write_records\n"
    )
    planted_hits = _facade_consumer_hits([("<planted>", planted_source)])
    assert planted_hits == [
        FacadeConsumer("<planted>", 2, "from import *"),
        FacadeConsumer("<planted>", 3, "from import write_records"),
        FacadeConsumer("<planted>", 6, "patch breezy.persistence.write_records"),
        FacadeConsumer("<planted>", 7, "setattr breezy.persistence.write_records"),
        FacadeConsumer("<planted>", 8, "patch breezy.persistence.write_records"),
        FacadeConsumer("<planted>", 10, "alias attribute write_records"),
        FacadeConsumer("<planted>", 12, "alias attribute write_records"),
    ]

    sources = (
        (str(path.relative_to(REPO_ROOT)), path.read_text(encoding="utf-8"))
        for path in _python_files_under(("src", "tests", "scripts"))
    )
    assert _facade_consumer_hits(sources) == []


@pytest.mark.parametrize("entry_module", PERSISTENCE_ENTRY_MODULES)
def test_persistence_entry_module_imports_cleanly(
    entry_module: str,
    entry_smoke_recorder: EntrySmokeRecorder,
) -> None:
    script = (
        "import importlib\n"
        "import sys\n"
        "from pathlib import Path\n"
        f"repo = Path({json.dumps(str(REPO_ROOT))})\n"
        f"entry = {json.dumps(entry_module)}\n"
        "if entry.startswith('scripts.'):\n"
        "    script_path = repo / (entry.replace('.', '/') + '.py')\n"
        "    sys.path.insert(0, str(script_path.parent))\n"
        "importlib.import_module(entry)\n"
    )
    start = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=ENTRY_SMOKE_BUDGET_S,
        check=False,
        cwd=REPO_ROOT,
    )
    duration = time.perf_counter() - start
    entry_smoke_recorder.durations.append((entry_module, duration))
    assert result.returncode == 0, result.stdout + result.stderr
