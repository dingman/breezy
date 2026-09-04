"""Differential tests for `breezy.domain.temperature` -- BL-24 Seam A-2.

`round_half_up_f` and `c_tenths_to_f` are a PORT of
`scripts/analysis/settlement_alignment_study.py:192-198`. These tests pin the
port against the original over a sweep of tenths values so the two copies
cannot silently drift.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType

import pytest

from breezy.domain.temperature import c_tenths_to_f, round_half_up_f

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"


@pytest.fixture(scope="module")
def study() -> ModuleType:
    if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))
    import settlement_alignment_study as module

    return module


@pytest.mark.parametrize("c_tenths", list(range(-400, 501)))
def test_round_half_up_f_matches_the_original_over_the_sweep(
    study: ModuleType, c_tenths: int,
) -> None:
    assert round_half_up_f(c_tenths) == study.round_half_up_f(c_tenths)


@pytest.mark.parametrize("c_tenths", list(range(-400, 501, 7)))
def test_c_tenths_to_f_matches_the_original_over_the_sweep(
    study: ModuleType, c_tenths: int,
) -> None:
    assert c_tenths_to_f(c_tenths) == study.c_tenths_to_f(c_tenths)


def test_round_half_up_f_rounds_half_away_from_floor() -> None:
    """`math.floor(x + 0.5)` always rounds an exact `.5` up, never to even."""
    assert round_half_up_f(0) == 32
    assert c_tenths_to_f(0) == 32.0
    # 50 c_tenths (5.0 C) -> 41.0 F exactly.
    assert round_half_up_f(50) == 41
    # -50 c_tenths (-5.0 C) -> 23.0 F exactly.
    assert round_half_up_f(-50) == 23
