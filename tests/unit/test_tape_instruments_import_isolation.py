"""Import isolation for the tape-instrument seam consumers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SCRIPTS_ANALYSIS: Final[Path] = REPO_ROOT / "scripts" / "analysis"
SRC_DIR: Final[Path] = REPO_ROOT / "src"

DEAD_STRATEGY_PREFIXES: Final[tuple[str, ...]] = (
    "breezy.strategy.calibration_mean_reversion",
    "breezy.strategy.cli_settlement_print_lock",
    "breezy.strategy.forecast_edge",
    "breezy.strategy.forecast_mispricing",
    "breezy.strategy.forecast_revision",
    "breezy.strategy.resting_ladder",
    "breezy.strategy.running_extreme_lock",
)

CONSUMER_MODULES: Final[tuple[str, ...]] = (
    "current_rung_hold_paper_replay",
    "whole_tape_paper_replay",
    "replay_sufficiency_census",
)


@pytest.mark.parametrize("module_name", CONSUMER_MODULES)
def test_tape_instrument_consumers_do_not_import_dead_strategy_packages(
    module_name: str,
) -> None:
    code = """
import importlib
import json
import sys
from pathlib import Path

repo = Path.cwd()
sys.path.insert(0, str(repo / "src"))
sys.path.insert(0, str(repo / "scripts" / "analysis"))
prefixes = tuple(json.loads(sys.argv[2]))
before = set(sys.modules)
importlib.import_module(sys.argv[1])
loaded = sorted(
    name
    for name in set(sys.modules) - before
    if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)
)
print(json.dumps(loaded))
if loaded:
    raise SystemExit("loaded dead strategy modules: " + ", ".join(loaded))
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{SRC_DIR}{os.pathsep}{SCRIPTS_ANALYSIS}"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            code,
            module_name,
            json.dumps(DEAD_STRATEGY_PREFIXES),
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == []
