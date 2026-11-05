"""AUT-1 launch-window arithmetic (r8 section 3.11; r12 unchanged): pure integer nanoseconds.

The launch window is [16:30Z, 17:10Z) every UTC day: half-open, so the instant 17:10:00 is outside
it. ARCH-0's ``pins`` carries only the window END for registry validation, with no equivalent of
these two functions, so AUT-1 owns them.
"""

from typing import Final

__all__ = ["LAUNCH_WINDOW_UTC", "launch_window_guard", "seconds_outside_launch_window"]

LAUNCH_WINDOW_UTC: Final[tuple[tuple[int, int], tuple[int, int]]] = ((16, 30), (17, 10))

_NS: Final[int] = 10**9
_DAY_NS: Final[int] = 86_400 * _NS
_MINUTE_NS: Final[int] = 60 * _NS
_HOUR_NS: Final[int] = 3600 * _NS
_WINDOW_START_NS: Final[int] = (
    LAUNCH_WINDOW_UTC[0][0] * _HOUR_NS + LAUNCH_WINDOW_UTC[0][1] * _MINUTE_NS
)
_WINDOW_END_NS: Final[int] = (
    LAUNCH_WINDOW_UTC[1][0] * _HOUR_NS + LAUNCH_WINDOW_UTC[1][1] * _MINUTE_NS
)


def _window_overlap_ns(start_ns: int, end_ns: int) -> int:
    """Nanoseconds of [start_ns, end_ns) inside any day's window."""
    total = 0
    for day in range(start_ns // _DAY_NS, end_ns // _DAY_NS + 1):
        low = max(start_ns, day * _DAY_NS + _WINDOW_START_NS)
        high = min(end_ns, day * _DAY_NS + _WINDOW_END_NS)
        total += max(0, high - low)
    return total


def launch_window_guard(now_ns: int, flock_wait_s: int, timeout_start_s: int) -> bool:
    """True when a run starting at ``now_ns`` may proceed.

    The run's worst-case span is the closed interval [now, now + flock_wait + timeout_start]. It
    must not meet a window [16:30:00, 17:10:00): an end at exactly 16:30:00 already meets it, and
    a start at exactly 17:10:00 does not.
    """
    if now_ns < 0 or flock_wait_s < 0 or timeout_start_s < 0:
        raise ValueError("now_ns, flock_wait_s and timeout_start_s must be non-negative")
    end_ns = now_ns + (flock_wait_s + timeout_start_s) * _NS
    for day in range(now_ns // _DAY_NS, end_ns // _DAY_NS + 1):
        window_start = day * _DAY_NS + _WINDOW_START_NS
        window_end = day * _DAY_NS + _WINDOW_END_NS
        if now_ns < window_end and end_ns >= window_start:
            return False
    return True


def seconds_outside_launch_window(start_ns: int, end_ns: int) -> int:
    """Whole seconds of [start_ns, end_ns) that lie outside the daily launch window."""
    if end_ns < start_ns:
        raise ValueError("end_ns precedes start_ns")
    return (end_ns - start_ns - _window_overlap_ns(start_ns, end_ns)) // _NS
