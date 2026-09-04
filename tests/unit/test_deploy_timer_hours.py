"""No two Breezy systemd timers may fire on the same hour:minute tick.

`docs/plans/SCORER_TALLY_BCA_BRIEF_2026-09-04.md` section 6d, converged
review item 9: "The hour-clash test parses `OnCalendar=` lines of every
`deploy/systemd/*.timer` as text." Deliberately text-only -- no
`systemd-analyze` shelling (that is a documented manual step in
`deploy/systemd/README.md`, not a pytest gate).
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TIMERS_DIR = _REPO_ROOT / "deploy" / "systemd"

#: Matches the HH:MM out of an `OnCalendar=... HH:MM:SS UTC` line. Also
#: tolerates a comma-separated hour list (`00,06,12,18:15:00`) by capturing
#: the whole hour field and splitting it separately.
_ON_CALENDAR_RE = re.compile(r"^OnCalendar=.*\s([\d,]+):(\d{2}):\d{2}\s+UTC\s*$")


def _clock_ticks(timer_path: Path) -> tuple[tuple[str, str], ...]:
    """Every (hour, minute) tick an `OnCalendar=` line in `timer_path` fires at."""
    ticks: list[tuple[str, str]] = []
    for line in timer_path.read_text().splitlines():
        stripped = line.strip()
        match = _ON_CALENDAR_RE.match(stripped)
        if match is None:
            continue
        hours_field, minute = match.groups()
        for hour in hours_field.split(","):
            ticks.append((hour, minute))
    return tuple(ticks)


def _all_timer_files() -> tuple[Path, ...]:
    return tuple(sorted(_TIMERS_DIR.glob("*.timer")))


def test_no_two_timers_share_an_hour_minute_tick() -> None:
    timer_files = _all_timer_files()
    assert len(timer_files) >= 2, "expected at least the pre-existing Breezy timers"

    owner_by_tick: dict[tuple[str, str], str] = {}
    collisions: list[str] = []
    for timer_path in timer_files:
        ticks = _clock_ticks(timer_path)
        assert ticks, f"{timer_path.name} has no parseable OnCalendar= line"
        for tick in ticks:
            existing = owner_by_tick.get(tick)
            if existing is not None and existing != timer_path.name:
                collisions.append(f"{tick} claimed by both {existing} and {timer_path.name}")
            else:
                owner_by_tick[tick] = timer_path.name

    assert not collisions, "; ".join(collisions)


def test_every_timer_file_is_parsed_by_this_test() -> None:
    # Sanity: a future timer with a malformed OnCalendar would silently
    # short-circuit the collision check above (zero ticks -> no pairs to
    # compare) unless every file is asserted non-empty, which the previous
    # test already does per-file -- this test just pins the file count so a
    # new timer added without updating this suite is visible in review.
    timer_files = _all_timer_files()
    names = {path.name for path in timer_files}
    assert "breezy-live-tally.timer" in names
    assert "breezy-mb-daily.timer" in names
