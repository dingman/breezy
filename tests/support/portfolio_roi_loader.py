"""The ONE loader of ``scripts/analysis/portfolio_roi_report.py`` for tests.

Several test modules need the script as a module and used to load their own copy, each replacing
``sys.modules["portfolio_roi_report"]``. Two distinct module objects then coexisted, and a patch
made through one never reached code running on the other. Loading here is idempotent: an existing
``sys.modules`` entry is always returned, and nothing ever overwrites one.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

__all__ = ["load_portfolio_roi_report"]

_NAME = "portfolio_roi_report"
_PATH = Path(__file__).resolve().parents[2] / "scripts" / "analysis" / "portfolio_roi_report.py"


def load_portfolio_roi_report() -> ModuleType:
    existing = sys.modules.get(_NAME)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(_NAME, _PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(_NAME, None)
        raise
    return module
