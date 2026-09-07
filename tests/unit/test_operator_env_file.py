"""The operator's gitignored root file for the two reserved caps.

Names of the two controls are derived at runtime from the shipped inventory so
this module does not join the Layer B census. Values written into tmp files are
asserted absent from the script's stdout and stderr.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Final

from breezy.adapters.polymarket_us.operator_controls import OPERATOR_RESERVED_CONTROL_ENV_VARS

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
EXAMPLE: Final[Path] = REPO_ROOT / "operator.env.example"
SCRIPT: Final[Path] = REPO_ROOT / "scripts" / "operator" / "print_operator_controls.py"
SECRET: Final[str] = "LEAKTOKEN_ABSENT_FROM_OUTPUT"
UNSET_TOKEN: Final[str] = "<unset>"
SET_TOKEN: Final[str] = "<set>"


def _inventory_names() -> list[str]:
    # Layer A6 forbids list() of the inventory; copy by loop instead.
    names: list[str] = []
    for name in OPERATOR_RESERVED_CONTROL_ENV_VARS:
        names.append(name)  # noqa: PERF402
    return names


def _expected_report(token: str) -> list[str]:
    lines: list[str] = []
    for name in OPERATOR_RESERVED_CONTROL_ENV_VARS:
        lines.append(f"{name}={token}")
    return lines


def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    for name in OPERATOR_RESERVED_CONTROL_ENV_VARS:
        env.pop(name, None)
    return env


def _run_script(
    args: list[str],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _assert_secret_absent(completed: subprocess.CompletedProcess[str]) -> None:
    combined = completed.stdout + completed.stderr
    assert SECRET not in combined


def _write_operator_file(
    path: Path,
    *,
    names: list[str] | None = None,
    value: str = SECRET,
    extra_lines: tuple[str, ...] = (),
    mode: int = 0o600,
) -> Path:
    chosen = names
    if chosen is None:
        chosen = _inventory_names()
    lines: list[str] = []
    for name in chosen:
        lines.append(f"{name}={value}")
    lines.extend(extra_lines)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    path.chmod(mode)
    return path


def test_template_exists() -> None:
    assert EXAMPLE.is_file()


def test_template_values_are_exactly_unset_and_no_digit_follows_equals() -> None:
    text = EXAMPLE.read_text(encoding="utf-8")
    value_lines = 0
    for line in text.splitlines():
        if "=" not in line:
            continue
        after = line.split("=", 1)[1]
        assert after == UNSET_TOKEN
        assert not any(character.isdigit() for character in after)
        value_lines += 1
    assert value_lines > 0


def test_template_keys_equal_the_inventory() -> None:
    keys: list[str] = []
    for line in EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        key, _, _ = stripped.partition("=")
        keys.append(key)
    assert keys == _inventory_names()


def test_gitignore_ignores_operator_env_and_not_the_example() -> None:
    ignored = subprocess.run(
        ["git", "check-ignore", "-v", "--", "operator.env"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert ignored.returncode == 0
    assert "/operator.env" in ignored.stdout

    example = subprocess.run(
        ["git", "check-ignore", "--", "operator.env.example"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert example.returncode == 1


def test_presence_reports_unset_when_both_are_absent() -> None:
    completed = _run_script([], env=_clean_env())
    assert completed.returncode == 1
    assert completed.stdout.splitlines() == _expected_report(UNSET_TOKEN)
    assert completed.stderr == ""


def test_presence_reports_unset_for_the_sentinel() -> None:
    env = _clean_env()
    for name in OPERATOR_RESERVED_CONTROL_ENV_VARS:
        env[name] = UNSET_TOKEN
    completed = _run_script([], env=env)
    assert completed.returncode == 1
    assert completed.stdout.splitlines() == _expected_report(UNSET_TOKEN)
    assert completed.stderr == ""


def test_presence_reports_set_when_both_are_present() -> None:
    env = _clean_env()
    for name in OPERATOR_RESERVED_CONTROL_ENV_VARS:
        env[name] = SECRET
    completed = _run_script([], env=env)
    assert completed.returncode == 0
    assert completed.stdout.splitlines() == _expected_report(SET_TOKEN)
    assert completed.stderr == ""
    _assert_secret_absent(completed)


def test_check_file_rejects_an_unknown_key(tmp_path: Path) -> None:
    path = _write_operator_file(
        tmp_path / "operator.env",
        extra_lines=("BREEZY_TRADING_ENABLED=1",),
    )
    completed = _run_script(["--check-file", str(path)])
    assert completed.returncode == 2
    assert completed.stderr.strip() == "unexpected key: BREEZY_TRADING_ENABLED"
    _assert_secret_absent(completed)


def test_check_file_rejects_a_symlink(tmp_path: Path) -> None:
    target = _write_operator_file(tmp_path / "real.env")
    link = tmp_path / "link.env"
    link.symlink_to(target)
    completed = _run_script(["--check-file", str(link)])
    assert completed.returncode == 2
    assert completed.stderr.strip() == "path is a symlink"
    _assert_secret_absent(completed)


def test_check_file_rejects_group_readable_mode(tmp_path: Path) -> None:
    path = _write_operator_file(tmp_path / "operator.env", mode=0o640)
    assert stat.S_IMODE(path.stat().st_mode) & stat.S_IRGRP
    completed = _run_script(["--check-file", str(path)])
    assert completed.returncode == 2
    assert completed.stderr.strip() == "mode has group or other bits"
    _assert_secret_absent(completed)


def test_check_file_rejects_a_repeated_key(tmp_path: Path) -> None:
    first = None
    for name in OPERATOR_RESERVED_CONTROL_ENV_VARS:
        if first is None:
            first = name
    assert first is not None
    path = _write_operator_file(
        tmp_path / "operator.env",
        extra_lines=(f"{first}={SECRET}",),
    )
    completed = _run_script(["--check-file", str(path)])
    assert completed.returncode == 2
    assert completed.stderr.strip() == "repeated key"
    _assert_secret_absent(completed)


def test_check_file_rejects_a_malformed_line(tmp_path: Path) -> None:
    path = _write_operator_file(
        tmp_path / "operator.env",
        extra_lines=("not a valid assignment",),
    )
    completed = _run_script(["--check-file", str(path)])
    assert completed.returncode == 2
    assert completed.stderr.strip() == "malformed line"
    _assert_secret_absent(completed)


def test_check_file_rejects_a_file_with_one_key_missing(tmp_path: Path) -> None:
    first = None
    for name in OPERATOR_RESERVED_CONTROL_ENV_VARS:
        if first is None:
            first = name
    assert first is not None
    path = _write_operator_file(tmp_path / "operator.env", names=[first])
    completed = _run_script(["--check-file", str(path)])
    assert completed.returncode == 2
    assert completed.stderr.strip() == "missing key"
    _assert_secret_absent(completed)


def test_check_file_accepts_a_well_formed_file(tmp_path: Path) -> None:
    path = _write_operator_file(tmp_path / "operator.env")
    completed = _run_script(["--check-file", str(path)])
    assert completed.returncode == 0
    assert completed.stdout.splitlines() == _expected_report(SET_TOKEN)
    assert completed.stderr == ""
    _assert_secret_absent(completed)
