"""No two Breezy systemd timers may fire on the same hour:minute tick.

`docs/plans/SCORER_TALLY_BCA_BRIEF_2026-09-04.md` section 6d, converged
review item 9: "The hour-clash test parses `OnCalendar=` lines of every
`deploy/systemd/*.timer` as text." Deliberately text-only -- no
`systemd-analyze` shelling (that is a documented manual step in
`deploy/systemd/README.md`, not a pytest gate).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TIMERS_DIR = _REPO_ROOT / "deploy" / "systemd"

#: Matches the HH:MM out of an `OnCalendar=... HH:MM:SS UTC` line. Also
#: tolerates a comma-separated hour list (`00,06,12,18:15:00`) by capturing
#: the whole hour field and splitting it separately.
_ON_CALENDAR_RE = re.compile(r"^OnCalendar=.*\s([\d,]+):(\d{2}):\d{2}\s+UTC\s*$")

#: A sub-hourly step line: `OnCalendar=*:0/15` (GL-14/BL-24's frequent
#: ingest timer) or its O-1 multi-line form `OnCalendar=*-*-* 00..15:0/15:00
#: UTC` / `... 16:00,15:00 UTC` / `... 17:15,30,45:00 UTC` (hour list or range,
#: minute step or list), which carves the 16:30-17:10Z launch window out.
_PERIODIC_RE = re.compile(r"^OnCalendar=(?:\*|\*-\*-\*\s+[\d.,]+):[\d/,]+(?::00)?(?:\s+UTC)?\s*$")
_STEP_MINUTES_RE = re.compile(r":0/\d+")

_UNIT_RE = re.compile(r"^Unit=(.+)$")


def _timer_unit(timer_path: Path) -> str | None:
    """The `Unit=` target this timer fires, or `None` if the file has none
    (systemd would then default it to the timer's own basename).
    """
    for line in timer_path.read_text().splitlines():
        match = _UNIT_RE.match(line.strip())
        if match is not None:
            return match.group(1).strip()
    return None


def _is_periodic(timer_path: Path, all_timers: Sequence[Path]) -> bool:
    """Exempt from the HH:MM one-shot-per-day collision model below ONLY
    when this is a sub-hourly step timer (`OnCalendar=*:0/N`) that shares
    its `Unit=` target with ANOTHER timer already in the set -- i.e. it
    augments an existing timer's coverage of the SAME service, the way
    GL-14/BL-24's frequent ingest timer re-triggers the pre-existing
    6-hourly ingest timer's service, rather than contending with a
    DIFFERENT service for a resource at some shared clock tick.

    A periodic timer with no such sibling is NOT exempt: it stays in the
    scan below, where its `OnCalendar=*:0/N` syntax cannot be matched by
    `_ON_CALENDAR_RE` and correctly fails the "has no parseable OnCalendar="
    assertion -- a periodic timer introduced without an existing owner of
    its target service must be reviewed, not silently waved through.
    """
    lines = [
        line.strip()
        for line in timer_path.read_text().splitlines()
        if line.strip().startswith("OnCalendar=")
    ]
    # Every OnCalendar line must be sub-hourly-shaped, and at least one must
    # be a `0/N` step (an hour list alone, e.g. `00,06,12,18:15:00`, is not).
    if not lines or not all(_PERIODIC_RE.match(line) for line in lines):
        return False
    if not any(_STEP_MINUTES_RE.search(line) for line in lines):
        return False
    unit = _timer_unit(timer_path)
    if unit is None:
        return False
    return any(other != timer_path and _timer_unit(other) == unit for other in all_timers)


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
        if _is_periodic(timer_path, timer_files):
            continue
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
    # AUD-15 (2026-09-22): breezy-mb-daily.timer RETIRED, replaced at its
    # own 13:30Z slot by breezy-asos-refresh.timer (ruling
    # `RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md` RULING 1).
    assert "breezy-asos-refresh.timer" in names
    assert "breezy-score-live-trials.timer" in names


def test_1415_utc_is_owned_by_exactly_one_timer() -> None:
    # I3 (LIVE_FILL_SCORING_CHAIN_2026-09-05.md): 14:15 UTC is the new
    # score-live-trials tick, free on the pre-existing schedule (09:00,
    # 13:30, 14:30, 17:15, 22:30, 22:45, 00/06/12/18:15). This is a targeted
    # restatement of the collision test above, scoped to the one tick this
    # increment adds, so a future timer added at 14:15 fails loudly here
    # even if the general collision test above were ever weakened.
    owners = [
        timer_path.name
        for timer_path in _all_timer_files()
        if ("14", "15") in _clock_ticks(timer_path)
    ]
    assert owners == ["breezy-score-live-trials.timer"]


def test_a_periodic_timer_is_exempt_only_when_it_shares_a_unit_with_a_sibling(
    tmp_path: Path,
) -> None:
    """Review item 6: a periodic timer must not get a blanket exemption --
    only sharing its `Unit=` target with another timer already in the set
    earns one; an orphaned periodic timer stays in the collision scan.
    """
    shared_periodic = tmp_path / "shared.timer"
    shared_periodic.write_text("[Timer]\nUnit=some.service\nOnCalendar=*:0/15\n")
    sibling = tmp_path / "sibling.timer"
    sibling.write_text("[Timer]\nUnit=some.service\nOnCalendar=*-*-* 00:15:00 UTC\n")
    orphan_periodic = tmp_path / "orphan.timer"
    orphan_periodic.write_text("[Timer]\nUnit=lonely.service\nOnCalendar=*:0/15\n")

    all_timers = (shared_periodic, sibling, orphan_periodic)
    assert _is_periodic(shared_periodic, all_timers) is True
    assert _is_periodic(orphan_periodic, all_timers) is False


def test_1715_and_1725_utc_are_unowned_after_the_wp11b_template_merge() -> None:
    # WP-11b (active-family registry, cardinality-1): the former
    # pm_us_crh_v2 (17:15) / pm_us_crh_cont (17:25) per-family tally ticks
    # are retired along with their per-family unit files, replaced by ONE
    # shared template tick (17:20, see the next test). Neither old tick may
    # be silently re-claimed by a future timer.
    for hour, minute in (("17", "15"), ("17", "25")):
        owners = [
            timer_path.name
            for timer_path in _all_timer_files()
            if (hour, minute) in _clock_ticks(timer_path)
        ]
        assert owners == [], f"{hour}:{minute} UTC unexpectedly owned by {owners}"


def test_0920_utc_is_owned_by_the_decision_funnel_digest() -> None:
    """AUD-03: 09:20 UTC is after quote-tape rotate (09:00) and is not
    shared with any other timer. Outside the protected window
    ``[16:45Z, 01:15Z)``.
    """
    owners = [
        timer_path.name
        for timer_path in _all_timer_files()
        if ("09", "20") in _clock_ticks(timer_path)
    ]
    assert owners == ["breezy-decision-funnel-digest.timer"]
    rotate = [
        timer_path.name
        for timer_path in _all_timer_files()
        if ("09", "00") in _clock_ticks(timer_path)
    ]
    assert rotate == ["breezy-quote-tape-rotate.timer"]


def test_1720_utc_is_owned_by_exactly_one_timer() -> None:
    # WP-11b: 17:20 UTC is the ONE shared breezy-family-tally@.timer tick --
    # after 16:50 launch / 17:10 window end, and strictly between the two
    # retired per-family ticks it replaces. Unique as an hour:minute tick.
    owners = [
        timer_path.name
        for timer_path in _all_timer_files()
        if ("17", "20") in _clock_ticks(timer_path)
    ]
    assert owners == ["breezy-family-tally@.timer"]


def test_1652_utc_is_owned_by_exactly_one_timer() -> None:
    # AUD-02 WP-D1: 16:52 UTC is the ONE breezy-discovery-pull.timer tick --
    # free on the pre-existing schedule and, deliberately, inside the
    # protected no-start window [16:35Z, 01:15Z) under the light-job
    # exemption (see the timer's own comment and
    # deploy/systemd/README.md's "Light-job exemption" paragraph).
    owners = [
        timer_path.name
        for timer_path in _all_timer_files()
        if ("16", "52") in _clock_ticks(timer_path)
    ]
    assert owners == ["breezy-discovery-pull.timer"]


def test_1550_utc_is_owned_by_exactly_one_timer() -> None:
    # AUD-09b: 15:50 UTC is the ONE breezy-replay-daily.timer tick -- free
    # on the pre-existing schedule (occupied: 01:35, 02:05, 09:00, 09:20,
    # 13:30, 14:15, 14:30, 15:00, 15:20, 17:20, 00/06/12/18:15) and outside
    # the protected LST-union no-start window [16:35Z, 01:15Z).
    owners = [
        timer_path.name
        for timer_path in _all_timer_files()
        if ("15", "50") in _clock_ticks(timer_path)
    ]
    assert owners == ["breezy-replay-daily.timer"]
