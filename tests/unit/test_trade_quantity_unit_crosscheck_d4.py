"""D4: the crosscheck library path clears days only through registry row 0."""

from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from breezy.analysis.maker_search_declarations import SEARCH_DECLARATIONS
from breezy.analysis.trade_quantity_unit import ClearanceRefused

_SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "analysis"
    / "trade_quantity_unit_crosscheck.py"
)
_ROW0_SHA = SEARCH_DECLARATIONS[0].sha256
_ROW1_SHA = SEARCH_DECLARATIONS[1].sha256


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("trade_quantity_unit_crosscheck_d4", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_crosscheck_refuses_second_look_declaration_sha() -> None:
    with pytest.raises(ClearanceRefused, match="second-look"):
        _load_script().firewall_clearance(_ROW1_SHA)


def test_crosscheck_row0_sha_refuses_second_look_day() -> None:
    clearance = _load_script().firewall_clearance(_ROW0_SHA)
    with pytest.raises(ClearanceRefused, match="second-look"):
        clearance("LAX", dt.date(2026, 10, 14))


def test_crosscheck_row0_sha_still_clears_declared_day() -> None:
    clearance = _load_script().firewall_clearance(_ROW0_SHA)
    assert clearance("LAX", dt.date(2026, 10, 1)) is None
