"""R2.2: every symbol named in the citation map stays importable.

The map is ``docs/plans/refactor_2026-10-01/R2_2_citation_map.md``. Each table
row names a symbol that must be an attribute of both ``script_module`` (the
``scripts/analysis`` path rulings import) and ``new_module`` (where the name
is bound after the move). ``new_location`` must be a real line that still
contains that symbol.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAP_PATH = REPO_ROOT / "docs/plans/refactor_2026-10-01/R2_2_citation_map.md"
_ANALYSIS_SCRIPTS = REPO_ROOT / "scripts" / "analysis"


def _table_rows(text: str) -> list[tuple[str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str]] = []
    for line in text.splitlines():
        if not line.startswith("| `"):
            continue
        cells = [cell.strip().strip("`").strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 5:
            raise AssertionError(f"citation map row does not have 5 cells: {line}")
        cite, symbol, script_module, new_module, new_location = cells
        rows.append((cite, symbol, script_module, new_module, new_location))
    return rows


def test_r2_2_citation_map_symbols_resolve() -> None:
    rows = _table_rows(MAP_PATH.read_text())
    assert rows, "citation map table is empty"
    if str(_ANALYSIS_SCRIPTS) not in sys.path:
        sys.path.insert(0, _ANALYSIS_SCRIPTS.as_posix())

    loaded: dict[str, object] = {}
    for cite, symbol, script_module, new_module, new_location in rows:
        assert symbol != "annotations", cite
        assert symbol.isidentifier(), f"{cite} symbol {symbol!r} is not an identifier"
        for module_name in (script_module, new_module):
            if module_name not in loaded:
                loaded[module_name] = importlib.import_module(module_name)
        script_mod = loaded[script_module]
        new_mod = loaded[new_module]
        assert hasattr(script_mod, symbol), f"{script_module}.{symbol} missing ({cite})"
        assert hasattr(new_mod, symbol), f"{new_module}.{symbol} missing ({cite})"
        rel, sep, line_text = new_location.rpartition(":")
        assert sep and line_text.isdigit(), f"bad location {new_location} ({cite})"
        source_line = (REPO_ROOT / rel).read_text().splitlines()[int(line_text) - 1]
        assert symbol in source_line, f"{new_location} does not name {symbol} ({cite})"
