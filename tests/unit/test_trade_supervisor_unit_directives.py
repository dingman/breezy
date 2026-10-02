"""Pin the supervisor unit's kill and restart directives.

The spawned trade node shares this unit's cgroup. ``KillMode=process`` is the
line the unit itself calls the most important: the default control-group kill
would SIGKILL a node that may be holding a position. Memory ceilings are
absent on purpose (a cgroup OOM is SIGKILL). Comments that mention those
directives do not count — the unit's own prose names them while forbidding them.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_UNIT = _REPO_ROOT / "deploy" / "systemd" / "breezy-trade-supervisor.service"

_REQUIRED: tuple[tuple[str, str], ...] = (
    ("KillMode", "process"),
    ("RestartPreventExitStatus", "2"),
    ("TimeoutStopSec", "120"),
    ("Restart", "always"),
)
_FORBIDDEN: tuple[str, ...] = ("MemoryHigh", "MemoryMax")


def _directive_values(unit_text: str, directive: str) -> list[str]:
    """Values of real ``Directive=`` lines. A comment never counts."""
    prefix = f"{directive}="
    found: list[str] = []
    for line in unit_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped.startswith(prefix):
            continue
        found.append(stripped[len(prefix) :])
    return found


def supervisor_unit_violations(path: Path) -> list[str]:
    """Return human-readable pin violations for the unit file at ``path``."""
    text = path.read_text(encoding="utf-8")
    violations: list[str] = []
    for directive, expected in _REQUIRED:
        values = _directive_values(text, directive)
        if values != [expected]:
            violations.append(f"{directive} values {values!r}, want {[expected]!r}")
    for directive in _FORBIDDEN:
        values = _directive_values(text, directive)
        if values:
            violations.append(f"{directive} must be absent, found {values!r}")
    return violations


def _replace_directive(text: str, directive: str, new_value: str) -> str:
    prefix = f"{directive}="
    replaced = False
    out: list[str] = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not replaced and not stripped.startswith("#") and stripped.startswith(prefix):
            newline = "\n" if line.endswith("\n") else ""
            out.append(f"{directive}={new_value}{newline}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        raise AssertionError(f"shipped unit has no {directive}= line to mutate")
    return "".join(out)


def _insert_service_directive(text: str, line: str) -> str:
    needle = "[Service]\n"
    if needle not in text:
        raise AssertionError("shipped unit has no [Service] section")
    return text.replace(needle, f"{needle}{line}\n", 1)


_MUTATIONS: tuple[tuple[str, Callable[[str], str]], ...] = (
    ("killmode", lambda text: _replace_directive(text, "KillMode", "control-group")),
    (
        "restart_prevent",
        lambda text: _replace_directive(text, "RestartPreventExitStatus", "0"),
    ),
    ("timeout_stop", lambda text: _replace_directive(text, "TimeoutStopSec", "90")),
    ("restart", lambda text: _replace_directive(text, "Restart", "no")),
    ("memory_max", lambda text: _insert_service_directive(text, "MemoryMax=1G")),
    ("memory_high", lambda text: _insert_service_directive(text, "MemoryHigh=512M")),
)


@pytest.mark.parametrize(
    "label",
    ["shipped", *[name for name, _mutate in _MUTATIONS]],
)
def test_supervisor_unit_parser_over_path(tmp_path: Path, label: str) -> None:
    """The parser takes a path. The shipped unit is clean; each mutated copy is not."""
    if label == "shipped":
        path = _UNIT
        expect_clean = True
    else:
        mutate = dict(_MUTATIONS)[label]
        mutated = mutate(_UNIT.read_text(encoding="utf-8"))
        assert mutated != _UNIT.read_text(encoding="utf-8")
        path = tmp_path / f"{label}.service"
        path.write_text(mutated, encoding="utf-8")
        expect_clean = False
    violations = supervisor_unit_violations(path)
    if expect_clean:
        assert violations == []
    else:
        assert violations, label


def test_a_comment_does_not_satisfy_or_violate_a_directive(tmp_path: Path) -> None:
    path = tmp_path / "comments-only.service"
    path.write_text(
        "[Service]\n"
        "# KillMode=process\n"
        "# Restart=always\n"
        "# NO MemoryHigh=/MemoryMax=\n"
        "Restart=always\n"
        "RestartPreventExitStatus=2\n"
        "TimeoutStopSec=120\n",
        encoding="utf-8",
    )
    violations = supervisor_unit_violations(path)
    assert any("KillMode" in item for item in violations)
    assert not any("MemoryHigh" in item or "MemoryMax" in item for item in violations)
