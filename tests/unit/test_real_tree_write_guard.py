"""RED-first proof for `tests.support.real_tree_write_guard`: the audit
hook attributes writes to THIS test process, catching them even when a
racy before/after tree-stat snapshot could not tell them apart from a
concurrent external writer.

Every path used here lives under `tmp_path` -- this module never performs
a real write against an operator home directory. `tmp_path` stands in for
the `_REAL_*` constants the guarded production modules build from
`Path.home()`: same wiring, a harmless root.
"""

from __future__ import annotations

import os
from pathlib import Path

from tests.support.real_tree_write_guard import install_real_tree_write_guard


def test_write_mode_open_under_the_root_is_recorded(tmp_path: Path) -> None:
    guard = install_real_tree_write_guard(tmp_path)
    guard.active = True
    target = tmp_path / "x"
    with open(target, "w", encoding="utf-8") as fh:
        fh.write("data")
    guard.active = False

    assert any("open" in offense and str(target) in offense for offense in guard.offenses), (
        guard.offenses
    )


def test_os_replace_into_the_root_is_recorded(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside-src"
    outside.write_text("data", encoding="utf-8")
    guard = install_real_tree_write_guard(tmp_path)
    guard.active = True
    destination = tmp_path / "moved-in"
    os.replace(outside, destination)
    guard.active = False

    assert any(
        "os.rename" in offense and str(destination) in offense for offense in guard.offenses
    ), guard.offenses


def test_read_mode_open_under_the_root_is_not_recorded(tmp_path: Path) -> None:
    target = tmp_path / "y"
    target.write_text("data", encoding="utf-8")
    guard = install_real_tree_write_guard(tmp_path)
    guard.active = True
    with open(target, encoding="utf-8") as fh:
        fh.read()
    guard.active = False

    assert guard.offenses == []


def test_write_mode_open_outside_the_root_is_not_recorded(tmp_path: Path) -> None:
    elsewhere_dir = tmp_path.parent / f"{tmp_path.name}-elsewhere"
    elsewhere_dir.mkdir()
    guard = install_real_tree_write_guard(tmp_path)
    guard.active = True
    with open(elsewhere_dir / "z", "w", encoding="utf-8") as fh:
        fh.write("data")
    guard.active = False

    assert guard.offenses == []


def test_writes_while_inactive_are_never_recorded(tmp_path: Path) -> None:
    guard = install_real_tree_write_guard(tmp_path)
    # guard.active is False by construction -- never flipped on here.
    with open(tmp_path / "w", "w", encoding="utf-8") as fh:
        fh.write("data")

    assert guard.offenses == []
