"""Cross-module pins for MAKER-S2 constants that more than one WP consumes."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from scripts.analysis import maker_stage0_fill as fill
from scripts.analysis import maker_stage0_rule as rule

ANALYSIS_DIR = Path(__file__).resolve().parents[2] / "scripts/analysis"


def _assigners(name: str) -> list[str]:
    owners: list[str] = []
    for path in sorted(ANALYSIS_DIR.glob("maker_stage0_*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            if any(isinstance(t, ast.Name) and t.id == name for t in targets):
                owners.append(path.name)
                break
    return owners


def test_stale_h_has_single_owner() -> None:
    assert _assigners("STALE_H") == ["maker_stage0_pno.py"]


def test_max_rungs_single_owner_is_rule_module() -> None:
    default = inspect.signature(fill.simulate_station_day).parameters["max_rungs"].default
    assert default == rule.MAX_RUNGS
