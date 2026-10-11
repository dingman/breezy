"""EXEC-PAR BG-5a: the evaluator is split into five pure modules; hygiene holds for each."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from breezy.runtime import exec_par_stage_eval as facade

_NAMES = ("types", "stats", "fees", "rules", "eval")
_PATHS = [Path(facade.__file__).with_name(f"exec_par_stage_{n}.py") for n in _NAMES]
_FORBIDDEN = ("nautilus_trader", "breezy.adapters", "logging", "time", "os", "sqlite3", "random")


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


@pytest.mark.parametrize("path", _PATHS, ids=_NAMES)
def test_each_module_is_pure_and_small(path: Path) -> None:
    for name in _imports(path):
        assert not name.startswith(_FORBIDDEN), (path.name, name)
        assert name not in {"breezy.runtime.breaker_watcher", "breezy.runtime.submit_intent"}
    text = path.read_text()
    for token in ("datetime.now", "date.today", "time.time", "monotonic_ns", "logger.", "print("):
        assert token not in text, (path.name, token)
    assert len(text.splitlines()) <= 800


def test_the_import_graph_is_acyclic_types_first() -> None:
    order = {f"breezy.runtime.exec_par_stage_{n}": i for i, n in enumerate(_NAMES)}
    for path, name in zip(_PATHS, _NAMES, strict=True):
        for dep in _imports(path):
            if dep in order:
                assert order[dep] < order[f"breezy.runtime.exec_par_stage_{name}"], (name, dep)


def test_every_public_name_is_importable_from_the_facade() -> None:
    for public in facade.__all__:
        assert hasattr(facade, public), public
    for needed in ("evaluate_stage", "StageSnapshot", "Verdict", "wilson_deff_upper_bound",
                   "fee_stage_tolerance", "STOP_S5_BURST", "STOP_S9_STATION_DAY_INTRADAY",
                   "STOP_OUTCOMES", "Z_ONE_SIDED_95"):  # fmt: skip
        assert needed in facade.__all__
