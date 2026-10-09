"""Y5 (plan r15 section 3.9, r8): every daemon restart step of the operator runbook marks it first.

A forgotten marker fails toward the CRITICAL page, never toward silence, so the runbook itself must
carry the ``--mark-buildside-restart`` line immediately before each ``systemctl --user restart`` of
a data-path daemon (the supervisor, the recorder and NWS ingest).
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Final

from breezy.runtime.unit_health_daemons import DATA_PATH_DAEMONS

RUNBOOK: Final = Path(__file__).resolve().parents[2] / "docs" / "plans" / "R8_OPERATOR_RUNBOOK.md"
_RESTART_RE: Final = re.compile(r"systemctl --user restart ([A-Za-z0-9@._-]+)")
_MARKER: Final = "-m breezy.runtime.autonomy_health_cli --mark-buildside-restart"
_IGNORED_BETWEEN: Final = ("systemctl --user daemon-reload",)


def _fenced_command_lines() -> list[tuple[int, int, str]]:
    """``(block, line number, text)`` of every non-blank line inside a fenced block, in order."""
    lines: list[tuple[int, int, str]] = []
    inside = False
    block = 0
    for number, text in enumerate(RUNBOOK.read_text().splitlines(), start=1):
        if text.lstrip().startswith("```"):
            inside = not inside
            block += inside
        elif inside and text.strip():
            lines.append((block, number, text.strip()))
    return lines


def _restart_steps() -> list[tuple[int, str, str | None]]:
    """Each fenced restart of a data-path daemon, with the fenced line just before it."""
    commands = _fenced_command_lines()
    found: list[tuple[int, str, str | None]] = []
    for index, (block, number, text) in enumerate(commands):
        match = _RESTART_RE.fullmatch(text)
        if match is None or match.group(1) not in DATA_PATH_DAEMONS:
            continue
        before = [t for b, _n, t in commands[:index] if b == block and t not in _IGNORED_BETWEEN]
        found.append((number, match.group(1), before[-1] if before else None))
    return found


def test_runbook_daemon_restart_steps_mark_buildside_first() -> None:
    steps = _restart_steps()
    assert len(steps) >= 4, "the runbook's four supervisor restart steps (r8 Y5) must be fenced"
    for number, unit, previous in steps:
        assert previous is not None and _MARKER in previous, f"line {number}: no marker before"
        words = shlex.split(previous)
        assert words[words.index("--mark-buildside-restart") + 1] == unit, f"line {number}"
        assert "--reason" in words and "--commit" in words, f"line {number}"


def test_runbook_has_no_unfenced_daemon_restart_command() -> None:
    """A restart named only in prose cannot be pinned, so it would escape the marker rule."""
    fenced = {number for _block, number, _text in _fenced_command_lines()}
    for number, text in enumerate(RUNBOOK.read_text().splitlines(), start=1):
        match = _RESTART_RE.search(text)
        if match and match.group(1) in DATA_PATH_DAEMONS:
            assert number in fenced, f"line {number}: restart outside a fenced block"


def test_a_restart_without_a_marker_is_detected(tmp_path: Path, monkeypatch: object) -> None:
    """Positive control: the scan reports a missing marker instead of passing vacuously."""
    import pytest

    assert isinstance(monkeypatch, pytest.MonkeyPatch)
    fake = tmp_path / "RUNBOOK.md"
    fake.write_text("```\nsystemctl --user restart breezy-trade-supervisor.service\n```\n")
    monkeypatch.setattr(f"{__name__}.RUNBOOK", fake)
    ((_number, unit, previous),) = _restart_steps()
    assert unit == "breezy-trade-supervisor.service" and previous is None
