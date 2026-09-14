"""RED-first tests for `exec/no_side_keys.py` (S5 plan, Track B commit 1).

E3-7 (safety 2): a structural AST scan proving the captured key
(`NO_SIDE_POSITION_SHAPE_CAPTURED_KEY`) is a `.set(`/write target ONLY in
the CLI module -- the node may read it, never write it. Mirrors
`test_polymarket_us_readonly_guard.find_write_egress_violations`'s shape:
walk every `*.py` under `src/` and `scripts/`, find every `ast.Call` whose
func is an attribute named `set` (`<expr>.set(...)`) whose first argument
is (or textually references) the captured-key constant, and assert the
only file where that fires is the CLI.
"""

from __future__ import annotations

import ast
from pathlib import Path

from breezy.adapters.polymarket_us.exec.no_side_keys import (
    NO_SIDE_FIRST_LIVE_ORDER_KEY,
    NO_SIDE_POSITION_SHAPE_CAPTURED_KEY,
    is_no_side_pending,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCAN_ROOTS = ("src", "scripts")
_CAPTURED_KEY_NAME = "NO_SIDE_POSITION_SHAPE_CAPTURED_KEY"
_CLI_MODULE_PATH = "src/breezy/runtime/mark_no_side_position_captured_cli.py"


def test_no_side_first_live_order_key_value() -> None:
    assert NO_SIDE_FIRST_LIVE_ORDER_KEY == "exec/polymarket_us/no_side/first_live_order"


def test_no_side_position_shape_captured_key_value() -> None:
    assert (
        NO_SIDE_POSITION_SHAPE_CAPTURED_KEY
        == "exec/polymarket_us/no_side/position_shape_captured"
    )


def test_is_no_side_pending_true_only_while_first_order_present_and_captured_absent() -> None:
    class _Store:
        def __init__(self, values: dict[str, bytes]) -> None:
            self._values = values

        def get(self, key: str) -> bytes | None:
            return self._values.get(key)

    assert is_no_side_pending(_Store({})) is False
    assert (
        is_no_side_pending(_Store({NO_SIDE_FIRST_LIVE_ORDER_KEY: b"{}"})) is True
    )
    assert (
        is_no_side_pending(
            _Store(
                {
                    NO_SIDE_FIRST_LIVE_ORDER_KEY: b"{}",
                    NO_SIDE_POSITION_SHAPE_CAPTURED_KEY: b"{}",
                }
            )
        )
        is False
    )


def _iter_python_sources() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for root in _SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            out.append((rel, path.read_text(encoding="utf-8")))
    return out


def find_captured_key_write_targets(path: str, source: str) -> list[int]:
    """Line numbers of every `<expr>.set(<...NO_SIDE_POSITION_SHAPE_
    CAPTURED_KEY...>, ...)` call in `source`. A name reference (the
    imported constant used as the first positional arg, or an f-string
    literally containing the key's own string value) both count -- the
    scan is deliberately conservative (never a false negative)."""
    tree = ast.parse(source, filename=path)
    hits: list[int] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "set"
            and node.args
        ):
            continue
        first_arg = node.args[0]
        references_key = False
        if isinstance(first_arg, ast.Name) and first_arg.id == _CAPTURED_KEY_NAME:
            references_key = True
        for sub in ast.walk(first_arg):
            if isinstance(sub, ast.Name) and sub.id == _CAPTURED_KEY_NAME:
                references_key = True
            if (
                isinstance(sub, ast.Constant)
                and isinstance(sub.value, str)
                and sub.value == NO_SIDE_POSITION_SHAPE_CAPTURED_KEY
            ):
                references_key = True
        if references_key:
            hits.append(node.lineno)
    return hits


def test_the_captured_key_is_a_write_target_only_in_the_cli_module() -> None:
    offenders = {
        path: hits
        for path, src in _iter_python_sources()
        if (hits := find_captured_key_write_targets(path, src)) and path != _CLI_MODULE_PATH
    }
    assert offenders == {}


def test_the_scan_detects_a_planted_write_outside_the_cli(tmp_path: Path) -> None:
    """Non-vacuity: the scan must actually fire on a planted violation."""
    planted = (
        "from breezy.adapters.polymarket_us.exec.no_side_keys import (\n"
        "    NO_SIDE_POSITION_SHAPE_CAPTURED_KEY,\n"
        ")\n"
        "\n"
        "def evil(store):\n"
        "    store.set(NO_SIDE_POSITION_SHAPE_CAPTURED_KEY, b'1')\n"
    )
    hits = find_captured_key_write_targets("scripts/evil.py", planted)
    assert hits == [6]


def test_the_cli_module_itself_is_expected_to_be_the_one_write_target() -> None:
    """Documents the CLI path this test enforces against -- if the CLI is
    ever moved/renamed, this pin (and the constant above) must move with
    it in the same commit."""
    assert _CLI_MODULE_PATH == "src/breezy/runtime/mark_no_side_position_captured_cli.py"
