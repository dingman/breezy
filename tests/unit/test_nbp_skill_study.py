"""RED-first tests for the `nbp_skill_study` CLI's holdout guard (SL-8; plan
`FORECAST_NBP_PROBABILISTIC_FAMILY_Rev3_2026-09-29.md` S7 row SL-8).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "analysis" / "nbp_skill_study.py"
_spec = importlib.util.spec_from_file_location("nbp_skill_study", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
nbp_skill_study = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = nbp_skill_study
_spec.loader.exec_module(nbp_skill_study)


def test_default_stage_is_validate_and_never_needs_authorization() -> None:
    assert nbp_skill_study.main([]) == 0


def test_stage_holdout_without_authorization_refuses() -> None:
    with pytest.raises(nbp_skill_study.HoldoutNotCoordinatorAuthorizedError):
        nbp_skill_study.main(["--stage", "holdout"])


def test_stage_holdout_with_authorization_runs() -> None:
    assert nbp_skill_study.main(["--stage", "holdout", "--coordinator-authorized"]) == 0
