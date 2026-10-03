"""O-1 (coordinator ruling O1-R1): the frequent quote-tape ingest must stay
out of the node's 16:50Z LAUNCH window (ARCH section 5.2, 16:30-17:10Z).

Text-only: every value is read from the unit files under the repo root, never
from host state (no systemctl, no systemd-analyze).
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD_DIR = _REPO_ROOT / "deploy" / "systemd"
_FREQUENT_TIMER = _SYSTEMD_DIR / "breezy-quote-tape-ingest-frequent.timer"
_SIX_HOURLY_TIMER = _SYSTEMD_DIR / "breezy-quote-tape-ingest.timer"
_SERVICE = _SYSTEMD_DIR / "breezy-quote-tape-ingest.service"

_WINDOW_START_MINUTE = 16 * 60 + 30
_WINDOW_END_MINUTE = 17 * 60 + 10
#: systemd's documented default when TimeoutStopSec= is not set.
_SYSTEMD_DEFAULT_TIMEOUT_STOP_SEC = 90

_CALENDAR_RE = re.compile(r"^OnCalendar=\*-\*-\*\s+([\d.,]+):([\d/,]+):00\s+UTC\s*$")


def _expand_field(field: str, upper: int) -> set[int]:
    values: set[int] = set()
    for part in field.split(","):
        if "/" in part:
            start, step = part.split("/")
            values.update(range(int(start), upper, int(step)))
        elif ".." in part:
            low, high = part.split("..")
            values.update(range(int(low), int(high) + 1))
        else:
            values.add(int(part))
    return values


def _firing_minutes_of_day(timer_path: Path) -> set[int]:
    firings: set[int] = set()
    lines = [
        line.strip()
        for line in timer_path.read_text().splitlines()
        if line.strip().startswith("OnCalendar=")
    ]
    assert lines, f"{timer_path.name} has no OnCalendar="
    for line in lines:
        match = _CALENDAR_RE.match(line)
        assert match is not None, f"unparseable OnCalendar line: {line}"
        hours = _expand_field(match.group(1), 24)
        minutes = _expand_field(match.group(2), 60)
        firings.update(h * 60 + m for h in hours for m in minutes)
    return firings


def _unit_int(path: Path, key: str, default: int | None = None) -> int:
    match = re.search(rf"^{key}=(\d+)$", path.read_text(), re.MULTILINE)
    if match is None:
        assert default is not None, f"{key}= missing in {path.name}"
        return default
    return int(match.group(1))


def test_frequent_timer_never_fires_in_the_launch_window() -> None:
    inside = sorted(
        m
        for m in _firing_minutes_of_day(_FREQUENT_TIMER)
        if _WINDOW_START_MINUTE <= m < _WINDOW_END_MINUTE
    )
    assert inside == [], f"firings inside [16:30, 17:10): {inside}"


def test_frequent_timer_keeps_every_other_fifteen_minute_tick() -> None:
    expected = {m for m in range(0, 24 * 60, 15)} - {16 * 60 + 30, 16 * 60 + 45, 17 * 60}
    assert _firing_minutes_of_day(_FREQUENT_TIMER) == expected


def test_six_hourly_timer_never_fires_in_the_launch_window() -> None:
    inside = [
        m
        for m in _firing_minutes_of_day(_SIX_HOURLY_TIMER)
        if _WINDOW_START_MINUTE <= m < _WINDOW_END_MINUTE
    ]
    assert inside == []


def test_last_pre_window_run_is_dead_before_the_window_opens() -> None:
    last_pre_window = max(
        m for m in _firing_minutes_of_day(_FREQUENT_TIMER) if m < _WINDOW_START_MINUTE
    )
    worst_case_seconds = _unit_int(_SERVICE, "TimeoutStartSec") + _unit_int(
        _SERVICE, "TimeoutStopSec", _SYSTEMD_DEFAULT_TIMEOUT_STOP_SEC
    )
    assert last_pre_window * 60 + worst_case_seconds < _WINDOW_START_MINUTE * 60


def test_timeout_start_sec_is_deadline_plus_documented_tail() -> None:
    from breezy.runtime.ingest_deadline import STARTUP_AND_TAIL_ALLOWANCE_SECONDS

    deadline = int(re.search(r"--deadline-seconds[ =](\d+)", _SERVICE.read_text()).group(1))  # type: ignore[union-attr]
    assert _unit_int(_SERVICE, "TimeoutStartSec") == deadline + STARTUP_AND_TAIL_ALLOWANCE_SECONDS
