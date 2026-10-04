"""AUT-1 WP1 part A: the launch-window guard (r8 section 3.11), pure integer arithmetic."""

import datetime as dt

import pytest

from breezy.persistence.autonomy.capture_schedule import (
    LAUNCH_WINDOW_UTC,
    launch_window_guard,
    seconds_outside_launch_window,
)

NS = 10**9


def _at(hour: int, minute: int, second: int = 0, *, day: int = 3, extra_ns: int = 0) -> int:
    stamp = dt.datetime(2026, 10, day, hour, minute, second, tzinfo=dt.UTC)
    return int(stamp.timestamp()) * NS + extra_ns


def test_launch_window_is_1630_to_1710_utc() -> None:
    assert LAUNCH_WINDOW_UTC == ((16, 30), (17, 10))


def test_launch_window_guard_boundaries() -> None:
    """True means the run may start: [now, now + flock_wait + timeout] must not meet [16:30, 17:10).

    MUTATION: a half-open run end (``<`` instead of ``<=``) turns the 16:30:00-exact end green.
    """
    # 16:25 + 30 s + 120 s ends 16:27:30: allowed.
    assert launch_window_guard(_at(16, 25), 30, 120) is True
    # ends exactly 16:30:00: meets the window's first instant.
    assert launch_window_guard(_at(16, 27, 30), 30, 120) is False
    # ends one nanosecond before 16:30:00: allowed.
    assert launch_window_guard(_at(16, 27, 29, extra_ns=999_999_999), 30, 120) is True
    # starts inside the window, at its first and last instants.
    assert launch_window_guard(_at(16, 30), 0, 0) is False
    assert launch_window_guard(_at(17, 9, 59, extra_ns=999_999_999), 0, 0) is False
    # the window end is exclusive.
    assert launch_window_guard(_at(17, 10), 30, 120) is True
    # a run that spans the whole window from before it.
    assert launch_window_guard(_at(15, 0), 0, 3 * 3600) is False
    # a run that begins the previous evening and ends in the next day's window.
    assert launch_window_guard(_at(23, 0, day=3), 0, 18 * 3600) is False
    assert launch_window_guard(_at(23, 0, day=3), 0, 15 * 3600) is True


@pytest.mark.parametrize("wait, timeout", [(-1, 0), (0, -1), (-5, -5)])
def test_launch_window_guard_refuses_negative_budgets(wait: int, timeout: int) -> None:
    with pytest.raises(ValueError):
        launch_window_guard(_at(10, 0), wait, timeout)
    with pytest.raises(ValueError):
        launch_window_guard(-1, 0, 0)


def test_seconds_outside_launch_window_spanning_window() -> None:
    """16:00 to 18:00 is 7200 s, of which the 2400 s window is excluded."""
    assert seconds_outside_launch_window(_at(16, 0), _at(18, 0)) == 4800
    # a start inside the window counts only the tail after 17:10.
    assert seconds_outside_launch_window(_at(16, 45), _at(17, 15)) == 300
    assert seconds_outside_launch_window(_at(16, 30), _at(17, 10)) == 0
    assert seconds_outside_launch_window(_at(10, 0), _at(11, 0)) == 3600
    # two full days contain two windows.
    assert seconds_outside_launch_window(_at(0, 0, day=3), _at(0, 0, day=5)) == 172_800 - 2 * 2400
    assert seconds_outside_launch_window(_at(9, 0), _at(9, 0)) == 0


def test_seconds_outside_launch_window_rejects_a_reversed_span() -> None:
    with pytest.raises(ValueError):
        seconds_outside_launch_window(_at(10, 0), _at(9, 0))
