"""Lane splitting for ``scripts/ci/run_tier.sh T1 --lanes N`` (pure function).

The exact-partition proof against ``--collect-only`` lives in the shell script
and refuses to run on any mismatch; these tests pin the function it relies on.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LANES_PY = _REPO_ROOT / "scripts" / "ci" / "tier_lanes.py"
_TIER_SH = _REPO_ROOT / "scripts" / "ci" / "run_tier.sh"
_LANE_SH = _REPO_ROOT / "scripts" / "ci" / "run_t1_lanes.sh"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("tier_lanes", _LANES_PY)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


lanes_mod = _load()

_SERIAL = ("tests/unit/test_archive_import_contract.py", "tests/unit/test_tier_infra.py")
_FILES = [f"tests/unit/test_f{i:02d}.py" for i in range(17)] + list(_SERIAL)


def _weight(path: str) -> int:
    return (int(re.findall(r"\d+", path)[-1]) % 5 + 1) if "_f" in path else 1


def test_lanes_are_disjoint_complete_and_exclude_the_serial_files() -> None:
    lanes, serial = lanes_mod.split_lanes(_FILES, 3, _weight)
    flat = [f for lane in lanes for f in lane]
    assert len(flat) == len(set(flat))
    assert sorted([*flat, *serial]) == sorted(_FILES)
    assert serial == sorted(_SERIAL)
    assert set(flat).isdisjoint(_SERIAL)
    assert len(lanes) == 3 and all(lanes)


def test_split_is_deterministic_and_input_order_independent() -> None:
    first = lanes_mod.split_lanes(_FILES, 3, _weight)
    assert first == lanes_mod.split_lanes(_FILES, 3, _weight)
    assert first == lanes_mod.split_lanes(list(reversed(_FILES)), 3, _weight)


def test_split_balances_by_weight() -> None:
    lanes, _ = lanes_mod.split_lanes(_FILES, 3, _weight)
    loads = [sum(_weight(f) for f in lane) for lane in lanes]
    assert max(loads) - min(loads) <= max(_weight(f) for f in _FILES)


def test_one_lane_holds_every_non_serial_file() -> None:
    lanes, serial = lanes_mod.split_lanes(_FILES, 1, _weight)
    assert len(lanes) == 1 and len(lanes[0]) == len(_FILES) - len(_SERIAL)
    assert serial == sorted(_SERIAL)


def test_non_positive_lane_count_is_refused() -> None:
    with pytest.raises(ValueError, match="lanes"):
        lanes_mod.split_lanes(_FILES, 0, _weight)


def test_discovery_matches_pytest_file_patterns(tmp_path: Path) -> None:
    (tmp_path / "tests" / "unit" / "__pycache__").mkdir(parents=True)
    for name in ("test_a.py", "b_test.py", "helper.py", "conftest.py", "test_c.txt"):
        (tmp_path / "tests" / "unit" / name).write_text("", encoding="utf-8")
    (tmp_path / "tests" / "unit" / "__pycache__" / "test_x.py").write_text("", encoding="utf-8")
    found = lanes_mod.discover_test_files(tmp_path, ["tests/unit"])
    assert found == ["tests/unit/b_test.py", "tests/unit/test_a.py"]


def test_serial_files_exist_in_the_repo() -> None:
    assert all((_REPO_ROOT / f).is_file() for f in lanes_mod.SERIAL_FILES)


def test_excl_is_a_single_constant_every_tier_expands() -> None:
    text = _TIER_SH.read_text(encoding="utf-8")
    literal = "not live and not venue_live and not real_money"
    assert text.count(literal) == 1
    assert len(re.findall(r"^EXCL=", text, flags=re.MULTILINE)) == 1
    # The lane hand-off must carry exactly the expression the serial T1 arm uses.
    exprs = re.findall(r'"\$EXCL and not contract and not heavy"', text)
    assert len(exprs) == 2
    assert "--lanes" in text


def test_lane_count_defaults_to_one_serial_run() -> None:
    text = _TIER_SH.read_text(encoding="utf-8")
    assert re.search(r"^lanes=1$", text, flags=re.MULTILINE)


def test_lane_runner_proves_the_partition_before_running() -> None:
    text = _LANE_SH.read_text(encoding="utf-8")
    assert text.index("cmp -s") < text.index("&\n")  # proof precedes the background lanes
    assert "refusing to run" in text
