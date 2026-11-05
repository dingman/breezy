"""Process discovery by argv, shared by the trade supervisor and the AUT-6 meta-detectors.

``pgrep`` exits 1 when nothing matches and 2 or more on an error. ``find_pid_by_argv_checked``
keeps the two apart (an error raises ``OSError``); ``find_pid_by_argv`` is the supervisor's
long-standing form, which reads both as "not found".
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from typing import Any, Final

PGREP: Final = "pgrep"
_TIMEOUT_S: Final = 5
_NO_MATCH_RC: Final = 1

Run = Callable[..., Any]


def find_pid_by_argv_checked(anchor_pattern: str, *, run: Run | None = None) -> int | None:
    """The first PID whose argv matches ``pgrep -f <anchor_pattern>``; ``None`` if none does.

    Raises ``OSError`` when ``pgrep`` cannot run, times out or reports an error.
    """
    runner = run if run is not None else subprocess.run  # looked up per call: patchable
    try:
        result = runner(
            [PGREP, "-f", anchor_pattern],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OSError(f"pgrep failed: {type(exc).__name__}") from None
    if result.returncode not in (0, _NO_MATCH_RC):
        raise OSError(f"pgrep failed: rc={result.returncode}")
    for line in result.stdout.splitlines():
        text = line.strip()
        if text.isdigit():
            return int(text)
    return None


def find_pid_by_argv(anchor_pattern: str, *, run: Run | None = None) -> int | None:
    """``pgrep -f <anchor_pattern>``, anchored (trailing ``$``) by the caller. The first matching
    PID, or ``None`` (including when ``pgrep`` itself fails)."""
    try:
        return find_pid_by_argv_checked(anchor_pattern, run=run)
    except OSError:
        return None
