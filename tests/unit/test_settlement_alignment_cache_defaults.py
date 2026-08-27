"""Regression tests for settlement-alignment archive cache defaults."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR = _REPO_ROOT / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

_SCRIPT_NAMES = (
    "settlement_alignment_diagnosis",
    "settlement_bucket_gate",
    "settlement_bucket_guard_band",
    "settlement_alignment_study",
)


def _analysis_modules() -> tuple[ModuleType, ...]:
    return tuple(importlib.import_module(name) for name in _SCRIPT_NAMES)


def test_settlement_alignment_default_cache_dir_is_home_absolute_and_shared() -> None:
    expected = Path.home() / ".local/share/breezy/archive/settlement-alignment-cache"

    for module in _analysis_modules():
        cache_dir = module.parse_args([]).cache_dir

        assert cache_dir == expected
        assert cache_dir.is_absolute()
        assert "~" not in cache_dir.parts
        assert Path("/tmp") not in (cache_dir, *cache_dir.parents)


def test_settlement_alignment_cache_dir_cli_override_wins(tmp_path: Path) -> None:
    override = tmp_path / "operator-cache"

    for module in _analysis_modules():
        args = module.parse_args(["--cache-dir", str(override)])

        assert args.cache_dir == override


def test_settlement_alignment_cache_dir_tilde_override_expands() -> None:
    for module in _analysis_modules():
        args = module.parse_args(["--cache-dir", "~/operator-cache"])

        assert args.cache_dir == Path.home() / "operator-cache"
        assert "~" not in args.cache_dir.parts


@pytest.mark.parametrize("module", _analysis_modules(), ids=_SCRIPT_NAMES)
def test_missing_settlement_alignment_cache_dir_raises_named_error(
    module: ModuleType, tmp_path: Path
) -> None:
    missing_cache = tmp_path / "missing-cache"
    output = tmp_path / f"{module.__name__}.md"

    with pytest.raises(FileNotFoundError) as exc_info:
        module.main(["--cache-dir", str(missing_cache), "--output", str(output)])

    assert exc_info.type.__name__ == "SettlementAlignmentCacheError"
    assert str(missing_cache) in str(exc_info.value)
    assert not output.exists()
