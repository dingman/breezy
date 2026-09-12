"""Three-state process-liveness probe (SP-6 AM-11, B4, AM-13/SEC2-M1).

``trade_supervisor.py``'s own ``find_pid_by_argv`` is
``subprocess.run(["pgrep", "-f", anchor_pattern], ...)``, returning
``None`` on a match failure exactly as it does on a genuine absence --
measured: a transient ``pgrep`` fork failure (this host has documented
OOM/swap history) is indistinguishable from "the process is not running"
in the caller. This module gives that probe a THIRD state, ``FAILED``,
so a caller (A11, A12) can tell "I don't know" from "it's gone" and never
turn a probe hiccup into a false CRITICAL.

``find_pid_by_argv`` MOVES here verbatim as a thin wrapper preserving
today's exact two-state return (``int | None``) -- re-exported from
``trade_supervisor`` so its one caller (``default_ports``) and every
other existing import are unaffected by the move.

``pid_cmdline_matches`` is a SEPARATE primitive (AM-13): a pure
``/proc/<pid>/cmdline`` read, no fork, that CONFIRMS a pid the caller
already tracks -- it never DISCOVERS one (discovery stays with
``probe_pid_by_argv``). Reading it first, before falling back to a fresh
``pgrep``, is what takes A11's healthy-path fork rate to zero: this is a
pure read.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

__all__ = [
    "PidProbe",
    "ProbeOutcome",
    "find_pid_by_argv",
    "pid_cmdline_matches",
    "probe_pid_by_argv",
]

_DEFAULT_PROC_ROOT: Final[Path] = Path("/proc")


class ProbeOutcome(str, Enum):
    """The three things a process-liveness probe can honestly report."""

    FOUND = "found"
    ABSENT = "absent"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class PidProbe:
    """``outcome`` is always meaningful; ``pid`` is set only for FOUND."""

    outcome: ProbeOutcome
    pid: int | None


def probe_pid_by_argv(
    anchor_pattern: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> PidProbe:
    """``pgrep -f <anchor_pattern>`` (anchored -- trailing ``$`` -- by the
    caller), shelling out via ``runner`` (injectable for tests -- never
    executes a real ``pgrep`` when a caller supplies a fake).

    A probe FAILURE (``OSError`` -- including an ENOMEM fork failure --
    or a timeout) is FAILED, never conflated with ABSENT. No matching PID
    line is ABSENT. A matching PID is FOUND.
    """
    try:
        result = runner(
            ["pgrep", "-f", anchor_pattern],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return PidProbe(ProbeOutcome.FAILED, None)
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped.isdigit():
            return PidProbe(ProbeOutcome.FOUND, int(stripped))
    return PidProbe(ProbeOutcome.ABSENT, None)


def find_pid_by_argv(anchor_pattern: str) -> int | None:
    """Back-compat wrapper: preserves the PRE-SP-6 two-state contract
    (FOUND -> pid, everything else -> ``None``) for callers that predate
    the three-state :class:`ProbeOutcome` (``default_ports`` in
    ``trade_supervisor.py``, re-exported from there so this move is
    invisible to it and to SP-1)."""
    probe = probe_pid_by_argv(anchor_pattern)
    return probe.pid if probe.outcome is ProbeOutcome.FOUND else None


def pid_cmdline_matches(
    pid: int,
    anchor_pattern: str,
    *,
    proc_root: Path = _DEFAULT_PROC_ROOT,
) -> bool | None:
    """A pure ``/proc/<pid>/cmdline`` read -- no fork, ever. CONFIRMS a
    pid the caller already tracks against ``anchor_pattern`` (the same
    regex ``pgrep -f`` would search for); it never DISCOVERS a pid.

    Returns ``True`` when any NUL-separated ``cmdline`` argument matches
    ``anchor_pattern``, ``False`` when none does (identity-confirming: a
    REUSED pid now running a different program fails this), and ``None``
    when the file is unreadable (the process exited, or a permission
    error) -- a third state, never conflated with a genuine non-match.
    """
    cmdline_path = proc_root / str(pid) / "cmdline"
    try:
        raw = cmdline_path.read_bytes()
    except OSError:
        return None
    pattern = re.compile(anchor_pattern)
    args = (arg.decode(errors="replace") for arg in raw.split(b"\x00") if arg)
    return any(pattern.search(arg) for arg in args)
