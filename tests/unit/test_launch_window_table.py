"""ARCH-0 seam 4a: the 16:30Z-17:10Z launch window (ARCH section 5.2, P6-3; errata E-9, E-10).

Two contracts:

* ``test_no_unit_overlaps_launch_window[existing_units]``: outside the launch-path table, no
  deployed timer-driven unit's ``[slot, slot + AccuracySec + flock wait + start-phase bound +
  TimeoutStopSec]`` meets ``[16:30Z, 17:10Z)`` for any firing. The start-phase bound follows E-9:
  ``TimeoutStartSec`` re-arms for each ``ExecStartPre=``, ``ExecStart=`` and ``ExecStartPost=``
  command, so a unit's bound is the sum over its commands, plus ``RuntimeMaxSec`` when set. A
  oneshot with no ``TimeoutStartSec`` is unbounded and overlaps by definition.
* ``test_launch_path_units_end_before_next_fixed_point[existing_units]``: every firing of every
  launch-path row ends (``start + flock wait + TimeoutStartSec``) at or before its stated bound,
  and that bound is strictly before the next supervisor fixed point (STOP 16:40, pre-launch
  16:45, LAUNCH 16:50, window close 17:00, release 17:10).

One deployed timer overlaps today (``KNOWN_OVERLAP_TIMERS``). It is carried as a strict-xfail
parameter owned by AUT-6 O-1, not exempted: ``[existing_units]`` still checks every other timer,
and the carried parameter fails strict the moment its timer stops overlapping. Drop-ins under
``<unit>.service.d`` and ``<unit>.timer.d`` are applied; an unparseable drop-in fails closed.

The OnCalendar parser understands only the forms the repo uses (``*-*-* HH[,HH]:MM[:SS] UTC`` and
``*:MM[/step]``) and refuses anything else, so an unsupported schedule fails the gate instead of
being skipped.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final, NamedTuple

import pytest

from tests.support.autonomy_owner import OwnerPending
from tests.support.entry_points import DEPLOY_SYSTEMD_DIR

_DAY_S: Final = 24 * 3600
WINDOW_START_S: Final = 16 * 3600 + 30 * 60
WINDOW_END_S: Final = 17 * 3600 + 10 * 60

#: Supervisor fixed points inside the window (``pins.SCHEDULE_*``, ARCH section 5.2).
FIXED_POINTS_S: Final[tuple[int, ...]] = (
    16 * 3600 + 40 * 60,  # STOP
    16 * 3600 + 45 * 60,  # pre-launch engine pass
    16 * 3600 + 50 * 60,  # LAUNCH
    17 * 3600,  # launch window closes
    WINDOW_END_S,  # deferred firings resume
)

DEPLOYED_DIR: Final[Path] = DEPLOY_SYSTEMD_DIR
#: Seam 4a deploys 18 timer files (one a template) giving about 120 firings a day, 96 of them the
#: 15 minute ingest timer. The floors only guard a vacuous parse.
MIN_DEPLOYED_FIRINGS: Final = 60
MIN_TABLE_FIRINGS: Final = 30

_DEFAULT_ACCURACY_S: Final = 60
_DEFAULT_TIMEOUT_STOP_S: Final = 90
_UNBOUNDED: Final = float("inf")


def hms(text: str) -> int:
    """``HH:MM`` or ``HH:MM:SS`` to seconds of the day."""
    parts = [int(p) for p in text.split(":")]
    parts += [0] * (3 - len(parts))
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def fmt(seconds: float) -> str:
    if seconds == _UNBOUNDED:
        return "unbounded"
    whole = int(seconds)
    return f"{whole // 3600 % 24:02d}:{whole // 60 % 60:02d}:{whole % 60:02d}"


# ---------------------------------------------------------------------------
# The launch-path table (ARCH section 5.2; E-6 one-time row; E-10(b))
# ---------------------------------------------------------------------------


class LaunchPathRow(NamedTuple):
    unit: str
    firings: tuple[str, ...]
    flock_wait_s: int
    timeout_start_s: int
    #: Seconds after the firing by which the row guarantees it is finished (the ARCH "Ends by").
    ends_after_s: int


def _every_five_minutes(first: str, last: str) -> tuple[str, ...]:
    return tuple(fmt(s)[:8] for s in range(hms(first), hms(last) + 1, 300))


LAUNCH_PATH_TABLE: Final[tuple[LaunchPathRow, ...]] = (
    LaunchPathRow("intraday_reconciliation_producer", ("16:35", "17:05"), 30, 240, 270),
    LaunchPathRow("post_stop_reconcile", ("16:41",), 20, 100, 120),
    LaunchPathRow("prelaunch_engine_pass", ("16:45",), 60, 180, 240),
    LaunchPathRow("intraday_producer", _every_five_minutes("16:30", "17:05"), 10, 120, 130),
    LaunchPathRow(
        "intraday_engine_pass",
        (
            "16:32:30",
            "16:37:30",
            "16:42:30",
            "16:47:30",
            "16:52:30",
            "16:57:30",
            "17:02:30",
            "17:07:30",
        ),
        20,
        120,
        140,
    ),
    LaunchPathRow("dead_man", ("16:30", "17:00"), 10, 60, 70),
    LaunchPathRow("aut6_health", ("16:31", "16:41", "16:51", "17:01"), 0, 120, 120),
    LaunchPathRow("canary_scheduled", ("16:30", "16:45"), 0, 60, 60),
    LaunchPathRow("alert_redeliver", _every_five_minutes("16:30", "17:05"), 0, 60, 60),
    # E-6: the one-time L1 bootstrap, ending <= 16:41:15 (before the 16:42:30 intraday pass).
    LaunchPathRow("l1_bootstrap_one_time", ("16:40:05",), 10, 60, 70),
)

#: Deployed units that are launch-path rows. None at seam 4a; AUT-2, AUT-5 and AUT-6 add rows here
#: and their unit files in the same change. Pinned by equality so a landing unit cannot be missed.
#: AUT-6 WP1 adds the alert redeliver (table row ``alert_redeliver``, every five minutes).
DEPLOYED_LAUNCH_PATH_UNITS: Final[frozenset[str]] = frozenset(
    {"breezy-autonomy-alert-redeliver.service"}
)


def next_fixed_point_s(start_s: int) -> int | None:
    return next((p for p in FIXED_POINTS_S if p > start_s), None)


def launch_path_violations(rows: Sequence[LaunchPathRow]) -> list[str]:
    """Rows whose firings do not finish on time or do not finish before the next fixed point."""
    problems: list[str] = []
    for row in rows:
        for firing in row.firings:
            start = hms(firing)
            worst_end = start + row.flock_wait_s + row.timeout_start_s
            bound = start + row.ends_after_s
            if worst_end > bound:
                problems.append(f"{row.unit}@{firing}: worst end {fmt(worst_end)} > {fmt(bound)}")
            point = next_fixed_point_s(start)
            if point is not None and bound >= point:
                problems.append(
                    f"{row.unit}@{firing}: ends {fmt(bound)}, next fixed point {fmt(point)}"
                )
    return problems


# ---------------------------------------------------------------------------
# Unit and timer parsing
# ---------------------------------------------------------------------------


class UnsupportedUnitSyntax(Exception):
    """A schedule or duration this module does not model; the gate refuses it."""


_FIELD_MAX: Final = {"hour": 24, "minute": 60, "second": 60}


def _expand(field: str, kind: str) -> list[int]:
    values: set[int] = set()
    limit = _FIELD_MAX[kind]
    for item in field.split(","):
        if item == "*":
            values.update(range(limit))
        elif "/" in item:
            start, step = item.split("/")
            first = 0 if start == "*" else int(start)
            values.update(range(first, limit, int(step)))
        elif ".." in item:
            low, high = item.split("..")
            values.update(range(int(low), int(high) + 1))
        elif item.isdigit():
            values.add(int(item))
        else:
            raise UnsupportedUnitSyntax(f"OnCalendar field {item!r}")
    return sorted(values)


def parse_on_calendar(expression: str) -> list[int]:
    """Seconds of the UTC day at which ``expression`` fires."""
    tokens = expression.split()
    if tokens and tokens[-1] == "UTC":
        tokens = tokens[:-1]
    elif tokens and tokens[-1].isalpha():
        raise UnsupportedUnitSyntax(f"timezone {tokens[-1]!r}")
    date_tokens = [t for t in tokens if "-" in t]
    time_tokens = [t for t in tokens if ":" in t]
    if len(time_tokens) != 1 or len(date_tokens) + 1 != len(tokens):
        raise UnsupportedUnitSyntax(f"OnCalendar {expression!r}")
    if date_tokens and date_tokens[0] != "*-*-*":
        raise UnsupportedUnitSyntax(f"OnCalendar date {date_tokens[0]!r}")
    parts = time_tokens[0].split(":")
    if len(parts) not in (2, 3):
        raise UnsupportedUnitSyntax(f"OnCalendar time {time_tokens[0]!r}")
    seconds = _expand(parts[2], "second") if len(parts) == 3 else [0]
    hours = _expand(parts[0], "hour")
    minutes = _expand(parts[1], "minute")
    return sorted(h * 3600 + m * 60 + s for h in hours for m in minutes for s in seconds)


_DURATION_RE: Final = re.compile(
    r"(\d+)\s*(us|ms|seconds|second|sec|s|minutes|minute|min|hour|hr|h)?"
)
_UNIT_SECONDS: Final = {
    None: 1.0, "us": 1e-6, "ms": 1e-3, "s": 1.0, "sec": 1.0, "second": 1.0, "seconds": 1.0,
    "min": 60.0, "minute": 60.0, "minutes": 60.0, "h": 3600.0, "hr": 3600.0, "hour": 3600.0,
}  # fmt: skip


def parse_duration_s(value: str) -> float:
    """A systemd time span in seconds; ``infinity`` is unbounded."""
    text = value.strip()
    if text == "infinity":
        return _UNBOUNDED
    total = 0.0
    position = 0
    while position < len(text):
        match = _DURATION_RE.match(text, position)
        if match is None or match.end() == position:
            raise UnsupportedUnitSyntax(f"duration {value!r}")
        total += int(match.group(1)) * _UNIT_SECONDS[match.group(2)]
        position = match.end()
        while position < len(text) and text[position] == " ":
            position += 1
    return total


def _directives(text: str, *, strict: bool = False) -> dict[str, list[str]]:
    """``key -> values`` of a unit text. ``strict`` (drop-ins) refuses what it cannot parse."""
    found: dict[str, list[str]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";", "[")):
            continue
        if strict and ("=" not in line or line.endswith("\\")):
            raise UnsupportedUnitSyntax(f"drop-in line {line[:40]!r}")
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        found.setdefault(key.strip(), []).append(value.strip())
    return found


def merged_directives(text: str, dropin_dir: Path) -> dict[str, list[str]]:
    """The unit's directives with ``<dropin_dir>/*.conf`` applied in name order.

    An empty assignment resets the key (systemd list semantics); any later value replaces or extends
    it. A drop-in this module cannot parse raises, so an override is never silently ignored.
    """
    merged = _directives(text)
    if dropin_dir.is_dir():
        for conf in sorted(dropin_dir.glob("*.conf")):
            for key, values in _directives(conf.read_text(encoding="utf-8"), strict=True).items():
                merged.setdefault(key, [])
                for value in values:
                    if value == "":
                        merged[key] = []
                    else:
                        merged[key].append(value)
        merged = {k: v for k, v in merged.items() if v}
    return merged


class UnitSpec(NamedTuple):
    name: str
    service_type: str
    start_commands: int
    timeout_start_s: float
    runtime_max_s: float
    timeout_stop_s: float
    flock_wait_s: int


_FLOCK_WAIT_RE: Final = re.compile(r"\bflock\b[^\n]*?\s-w\s+(\d+)")


def _flock_wait_s(service_text: str, directory: Path) -> int:
    texts = [service_text]
    for line in _directives(service_text).get("ExecStart", []):
        for token in line.split():
            candidate = Path(token.lstrip("-@+!"))
            if candidate.suffix == ".sh" and (directory / candidate.name).is_file():
                texts.append((directory / candidate.name).read_text(encoding="utf-8"))
    return max((int(m.group(1)) for t in texts for m in _FLOCK_WAIT_RE.finditer(t)), default=0)


def parse_service(name: str, text: str, directory: Path) -> UnitSpec:
    found = merged_directives(text, directory / f"{name}.d")
    service_type = found.get("Type", ["simple"])[-1]
    commands = sum(
        len(found.get(key, [])) for key in ("ExecStartPre", "ExecStart", "ExecStartPost")
    )
    timeout_start = (
        parse_duration_s(found["TimeoutStartSec"][-1])
        if "TimeoutStartSec" in found
        else (_UNBOUNDED if service_type == "oneshot" else float(_DEFAULT_TIMEOUT_STOP_S))
    )
    runtime_max = parse_duration_s(found["RuntimeMaxSec"][-1]) if "RuntimeMaxSec" in found else 0.0
    if service_type != "oneshot" and "RuntimeMaxSec" not in found:
        runtime_max = _UNBOUNDED  # a daemon with no runtime cap never ends
    timeout_stop = (
        parse_duration_s(found["TimeoutStopSec"][-1])
        if "TimeoutStopSec" in found
        else float(_DEFAULT_TIMEOUT_STOP_S)
    )
    return UnitSpec(
        name, service_type, max(commands, 1), timeout_start, runtime_max, timeout_stop,
        _flock_wait_s(text, directory),
    )  # fmt: skip


class Firing(NamedTuple):
    timer: str
    unit: str
    slot_s: int
    worst_end_s: float


def _timer_target(timer_name: str, directives: Mapping[str, list[str]]) -> str:
    target = directives.get("Unit", [timer_name.removesuffix(".timer") + ".service"])[-1]
    return target.replace("@%i", "@")


def firings(directory: Path) -> list[Firing]:
    """Every firing of every timer-driven unit under ``directory``, with its worst-case end."""
    found: list[Firing] = []
    for timer in sorted(directory.glob("*.timer")):
        timer_directives = merged_directives(
            timer.read_text(encoding="utf-8"), directory / f"{timer.name}.d"
        )
        service_path = directory / _timer_target(timer.name, timer_directives)
        if not service_path.is_file():
            raise UnsupportedUnitSyntax(f"{timer.name} targets a unit with no file")
        spec = parse_service(service_path.name, service_path.read_text(encoding="utf-8"), directory)
        accuracy = (
            parse_duration_s(timer_directives["AccuracySec"][-1])
            if "AccuracySec" in timer_directives
            else float(_DEFAULT_ACCURACY_S)
        )
        delay = (
            parse_duration_s(timer_directives["RandomizedDelaySec"][-1])
            if "RandomizedDelaySec" in timer_directives
            else 0.0
        )
        bound = spec.timeout_start_s * spec.start_commands + spec.runtime_max_s
        for expression in timer_directives.get("OnCalendar", []):
            for slot in parse_on_calendar(expression):
                end = slot + accuracy + delay + spec.flock_wait_s + bound + spec.timeout_stop_s
                found.append(Firing(timer.stem, spec.name, slot, end))
        if not timer_directives.get("OnCalendar"):
            raise UnsupportedUnitSyntax(f"{timer.name} has no OnCalendar")
    return found


def window_overlaps(
    directory: Path,
    *,
    launch_path_units: frozenset[str] = frozenset(),
    only_timer: str | None = None,
    skip_timers: frozenset[str] = frozenset(),
) -> list[Firing]:
    """Firings that meet ``[16:30Z, 17:10Z)``, excluding launch-path units (the table's job).

    ``only_timer`` restricts the result to one timer; ``skip_timers`` drops carried timers.
    """
    return [
        f
        for f in firings(directory)
        if f.unit not in launch_path_units
        and f.timer not in skip_timers
        and (only_timer is None or f.timer == only_timer)
        and f.slot_s < WINDOW_END_S
        and f.worst_end_s > WINDOW_START_S
    ]


def deployed_launch_path_violations(directory: Path, units: frozenset[str]) -> list[Firing]:
    """In-window firings of deployed launch-path units that end at or after the next fixed point."""
    late: list[Firing] = []
    for firing in firings(directory):
        if firing.unit not in units or not WINDOW_START_S <= firing.slot_s < WINDOW_END_S:
            continue
        point = next_fixed_point_s(firing.slot_s)
        if point is not None and firing.worst_end_s >= point:
            late.append(firing)
    return late


#: Deployed timers that overlap the window today. Each is carried as a strict-xfail parameter of
#: ``test_no_unit_overlaps_launch_window`` (owner AUT-6:O-1, a ledger row each), not exempted: the
#: parameter asserts the timer does not overlap, so it XPASSes, fails strict, and forces its row and
#: parameter out in the commit that fixes the deploy unit. It is a finding for the coordinator.
#:
#: * ``breezy-discovery-pull`` fires at 16:52 by design under its own "light-job exemption", but
#:   ``TimeoutStartSec=1800`` runs it to about 17:22 and ARCH section 5.2 lists no such row.
#:
#: ``breezy-quote-tape-ingest-frequent`` left this set when the O-1 deploy change (72eddbf6) removed
#: its 16:30, 16:45 and 17:00 firings and bounded ``TimeoutStartSec`` to 780; it is now checked by
#: ``[existing_units]`` like every other timer.
KNOWN_OVERLAP_TIMERS: Final[tuple[str, ...]] = ("breezy-discovery-pull",)
KNOWN_OVERLAP_PARAM_PREFIX: Final = "known_overlap_"


# ---------------------------------------------------------------------------
# Gate tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unit_set",
    [
        "existing_units",
        pytest.param(
            "known_overlap_breezy-discovery-pull",
            id="known_overlap_breezy-discovery-pull",
            marks=pytest.mark.xfail(
                strict=True, raises=OwnerPending, reason="AUT-6:O-1; blocks none"
            ),
        ),
    ],
)
def test_no_unit_overlaps_launch_window(unit_set: str) -> None:
    if unit_set.startswith(KNOWN_OVERLAP_PARAM_PREFIX):
        timer = unit_set.removeprefix(KNOWN_OVERLAP_PARAM_PREFIX)
        assert timer in KNOWN_OVERLAP_TIMERS
        found = window_overlaps(DEPLOYED_DIR, only_timer=timer)
        if found:  # carried: an overlap raises OwnerPending; no overlap XPASSes and fails strict
            raise OwnerPending(
                f"{timer} overlaps: {[(fmt(f.slot_s), fmt(f.worst_end_s)) for f in found]}"
            )
        return
    assert unit_set == "existing_units"
    found = window_overlaps(
        DEPLOYED_DIR,
        launch_path_units=DEPLOYED_LAUNCH_PATH_UNITS,
        skip_timers=frozenset(KNOWN_OVERLAP_TIMERS),
    )
    assert found == [], [(f.timer, fmt(f.slot_s), fmt(f.worst_end_s)) for f in found]
    all_timers = {f.timer for f in firings(DEPLOYED_DIR)}
    assert set(KNOWN_OVERLAP_TIMERS) <= all_timers
    assert len(firings(DEPLOYED_DIR)) >= MIN_DEPLOYED_FIRINGS


@pytest.mark.parametrize("unit_set", ["existing_units"])
def test_launch_path_units_end_before_next_fixed_point(unit_set: str) -> None:
    assert unit_set == "existing_units"
    assert sum(len(row.firings) for row in LAUNCH_PATH_TABLE) >= MIN_TABLE_FIRINGS
    assert launch_path_violations(LAUNCH_PATH_TABLE) == []
    deployed = {f.unit for f in firings(DEPLOYED_DIR)}
    assert DEPLOYED_LAUNCH_PATH_UNITS <= deployed
    assert deployed_launch_path_violations(DEPLOYED_DIR, DEPLOYED_LAUNCH_PATH_UNITS) == []


# ---------------------------------------------------------------------------
# Positive and negative controls
# ---------------------------------------------------------------------------


def _write_unit(
    directory: Path, name: str, *, calendar: str, service: str, timer_extra: str = ""
) -> None:
    (directory / f"{name}.timer").write_text(
        f"[Timer]\nOnCalendar={calendar}\n{timer_extra}\n", encoding="utf-8"
    )
    (directory / f"{name}.service").write_text(service, encoding="utf-8")


_ONESHOT = "[Service]\nType=oneshot\nExecStart=/bin/true\nTimeoutStartSec={timeout}\n"


@pytest.mark.parametrize(
    ("case", "calendar", "service", "timer_extra"),
    [
        ("slot_inside_window", "*-*-* 16:52:00 UTC", _ONESHOT.format(timeout=60), ""),
        ("long_run_started_before_window", "*-*-* 15:50:00 UTC", _ONESHOT.format(timeout=3000), ""),
        (
            "accuracy_pushes_into_window",
            "*-*-* 16:29:00 UTC",
            _ONESHOT.format(timeout=30),
            "AccuracySec=2min",
        ),
        ("every_fifteen_minutes", "*:0/15", _ONESHOT.format(timeout=60), ""),
        (
            "unbounded_oneshot",
            "*-*-* 09:00:00 UTC",
            "[Service]\nType=oneshot\nExecStart=/bin/true\n",
            "",
        ),
        (
            "daemon_without_runtime_cap",
            "*-*-* 09:00:00 UTC",
            "[Service]\nType=simple\nExecStart=/bin/true\n",
            "",
        ),
        (
            "two_commands_rearm_the_timeout",
            "*-*-* 16:10:00 UTC",
            "[Service]\nType=oneshot\nExecStartPre=/bin/true\nExecStart=/bin/true\nTimeoutStartSec=600\n",
            "",
        ),
        (
            "flock_wait_adds",
            "*-*-* 16:29:00 UTC",
            (
                "[Service]\nType=oneshot\n"
                "ExecStart=/usr/bin/flock -w 120 /x/lock /bin/true\nTimeoutStartSec=10\n"
            ),
            "AccuracySec=1s",
        ),
        ("hour_list", "*-*-* 00,16,18:30:00 UTC", _ONESHOT.format(timeout=60), ""),
    ],
)
def test_the_overlap_scan_fires_on_every_planted_unit(
    tmp_path: Path, case: str, calendar: str, service: str, timer_extra: str
) -> None:
    _write_unit(tmp_path, "planted", calendar=calendar, service=service, timer_extra=timer_extra)
    assert [f.unit for f in window_overlaps(tmp_path)] != [], case


@pytest.mark.parametrize(
    ("case", "calendar", "service", "timer_extra"),
    [
        ("morning_unit", "*-*-* 09:00:00 UTC", _ONESHOT.format(timeout=600), ""),
        (
            "ends_before_window",
            "*-*-* 15:00:00 UTC",
            _ONESHOT.format(timeout=3000),
            "AccuracySec=1s",
        ),
        ("starts_after_window", "*-*-* 17:20:00 UTC", _ONESHOT.format(timeout=60), ""),
        ("seconds_precision", "*-*-* 17:10:00 UTC", _ONESHOT.format(timeout=60), ""),
    ],
)
def test_the_overlap_scan_ignores_units_outside_the_window(
    tmp_path: Path, case: str, calendar: str, service: str, timer_extra: str
) -> None:
    _write_unit(tmp_path, "planted", calendar=calendar, service=service, timer_extra=timer_extra)
    assert window_overlaps(tmp_path) == [], case


def test_a_launch_path_unit_is_excluded_from_the_overlap_scan(tmp_path: Path) -> None:
    _write_unit(
        tmp_path, "launch", calendar="*-*-* 16:45:00 UTC", service=_ONESHOT.format(timeout=60)
    )
    assert window_overlaps(tmp_path)
    assert window_overlaps(tmp_path, launch_path_units=frozenset({"launch.service"})) == []


@pytest.mark.parametrize(
    "calendar",
    ["Mon *-*-* 16:52:00 UTC", "*-*-* 16:52:00 Europe/Paris", "hourly", "*-*-1 16:52:00 UTC"],
)
def test_unsupported_schedules_fail_closed(tmp_path: Path, calendar: str) -> None:
    _write_unit(tmp_path, "planted", calendar=calendar, service=_ONESHOT.format(timeout=60))
    with pytest.raises(UnsupportedUnitSyntax):
        firings(tmp_path)


def test_a_timer_without_a_service_file_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "orphan.timer").write_text(
        "[Timer]\nOnCalendar=*-*-* 09:00:00 UTC\n", encoding="utf-8"
    )
    with pytest.raises(UnsupportedUnitSyntax):
        firings(tmp_path)


def test_the_calendar_parser_expands_the_repo_forms() -> None:
    assert parse_on_calendar("*-*-* 09:20:00 UTC") == [hms("09:20")]
    assert parse_on_calendar("*-*-* 00,06,12,18:15:00 UTC") == [
        hms(h) for h in ("00:15", "06:15", "12:15", "18:15")
    ]
    quarter = parse_on_calendar("*:0/15")
    assert len(quarter) == 96 and hms("16:30") in quarter and hms("16:45") in quarter
    assert parse_on_calendar("*:01/10")[:3] == [hms("00:01"), hms("00:11"), hms("00:21")]


def test_the_duration_parser_reads_systemd_spans() -> None:
    assert parse_duration_s("1800") == 1800
    assert parse_duration_s("30min") == 1800
    assert parse_duration_s("1h 30min") == 5400
    assert parse_duration_s("90s") == 90
    assert parse_duration_s("infinity") == _UNBOUNDED
    with pytest.raises(UnsupportedUnitSyntax):
        parse_duration_s("soon")


def test_the_launch_path_table_fires_on_a_late_row() -> None:
    late = LaunchPathRow(
        "late_pass", ("16:47:30",), 20, 120, 150
    )  # ends 16:50:00, the LAUNCH point
    assert launch_path_violations([late])
    slow = LaunchPathRow("slow_pass", ("16:35",), 30, 300, 270)  # worst end beyond its stated bound
    assert launch_path_violations([slow])
    fine = LaunchPathRow("fine_pass", ("16:35",), 30, 240, 270)
    assert launch_path_violations([fine]) == []


def test_a_deployed_launch_path_unit_that_ends_after_its_fixed_point_is_flagged(
    tmp_path: Path,
) -> None:
    _write_unit(
        tmp_path, "launch", calendar="*-*-* 16:45:00 UTC", service=_ONESHOT.format(timeout=600)
    )
    names = frozenset({"launch.service"})
    assert deployed_launch_path_violations(tmp_path, names)
    assert deployed_launch_path_violations(tmp_path, frozenset()) == []
    _write_unit(
        tmp_path, "tight", calendar="*-*-* 16:45:00 UTC",
        service="[Service]\nType=oneshot\nExecStart=/bin/true\nTimeoutStartSec=30\nTimeoutStopSec=5\n",
    )  # fmt: skip
    assert deployed_launch_path_violations(tmp_path, frozenset({"tight.service"})) == []


def test_the_launch_path_table_matches_the_arch_firings() -> None:
    by_unit = {row.unit: row for row in LAUNCH_PATH_TABLE}
    assert by_unit["intraday_producer"].firings[0] == "16:30:00"
    assert len(by_unit["intraday_producer"].firings) == 8
    assert len(by_unit["alert_redeliver"].firings) == 8
    assert len(by_unit["intraday_engine_pass"].firings) == 8
    assert hms(by_unit["l1_bootstrap_one_time"].firings[0]) + by_unit[
        "l1_bootstrap_one_time"
    ].ends_after_s == hms("16:41:15")


def test_the_ingest_unit_has_an_effective_timeout_of_780_and_is_not_carried() -> None:
    assert "breezy-quote-tape-ingest-frequent" not in KNOWN_OVERLAP_TIMERS
    spec = parse_service(
        "breezy-quote-tape-ingest.service",
        (DEPLOYED_DIR / "breezy-quote-tape-ingest.service").read_text(encoding="utf-8"),
        DEPLOYED_DIR,
    )
    assert spec.timeout_start_s == 780  # O-1 (72eddbf6): the effective TimeoutStartSec
    assert spec.service_type == "oneshot"


def test_one_overlap_does_not_hide_another(tmp_path: Path) -> None:
    _write_unit(
        tmp_path, "first", calendar="*-*-* 16:40:00 UTC", service=_ONESHOT.format(timeout=60)
    )
    _write_unit(
        tmp_path, "second", calendar="*-*-* 16:50:00 UTC", service=_ONESHOT.format(timeout=60)
    )
    assert {f.timer for f in window_overlaps(tmp_path)} == {"first", "second"}
    assert {f.timer for f in window_overlaps(tmp_path, skip_timers=frozenset({"first"}))} == {
        "second"
    }
    assert {f.timer for f in window_overlaps(tmp_path, only_timer="first")} == {"first"}


def _dropin(directory: Path, unit_file: str, text: str, name: str = "override.conf") -> None:
    folder = directory / f"{unit_file}.d"
    folder.mkdir(exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


def test_a_service_dropin_that_raises_timeout_start_sec_is_applied(tmp_path: Path) -> None:
    _write_unit(tmp_path, "u", calendar="*-*-* 16:00:00 UTC", service=_ONESHOT.format(timeout=60))
    assert window_overlaps(tmp_path) == []
    _dropin(tmp_path, "u.service", "[Service]\nTimeoutStartSec=3000\n")
    assert [f.timer for f in window_overlaps(tmp_path)] == ["u"]


def test_a_service_dropin_that_makes_the_unit_a_daemon_is_applied(tmp_path: Path) -> None:
    _write_unit(tmp_path, "u", calendar="*-*-* 09:00:00 UTC", service=_ONESHOT.format(timeout=60))
    _dropin(tmp_path, "u.service", "[Service]\nType=simple\nTimeoutStartSec=\n")
    assert [f.timer for f in window_overlaps(tmp_path)] == ["u"]  # unbounded daemon


def test_a_timer_dropin_that_adds_an_oncalendar_slot_is_applied(tmp_path: Path) -> None:
    _write_unit(tmp_path, "u", calendar="*-*-* 09:00:00 UTC", service=_ONESHOT.format(timeout=60))
    _dropin(tmp_path, "u.timer", "[Timer]\nOnCalendar=*-*-* 16:45:00 UTC\n")
    assert [f.slot_s for f in window_overlaps(tmp_path)] == [hms("16:45")]


def test_a_timer_dropin_that_resets_oncalendar_replaces_the_schedule(tmp_path: Path) -> None:
    _write_unit(tmp_path, "u", calendar="*-*-* 16:45:00 UTC", service=_ONESHOT.format(timeout=60))
    assert window_overlaps(tmp_path)
    _dropin(tmp_path, "u.timer", "[Timer]\nOnCalendar=\nOnCalendar=*-*-* 09:00:00 UTC\n")
    assert window_overlaps(tmp_path) == []


@pytest.mark.parametrize(
    "text", ["[Service]\nthis is not a directive\n", "[Service]\nExecStart=a \\\n b\n"]
)
def test_an_unparseable_dropin_fails_closed(tmp_path: Path, text: str) -> None:
    _write_unit(tmp_path, "u", calendar="*-*-* 09:00:00 UTC", service=_ONESHOT.format(timeout=60))
    _dropin(tmp_path, "u.service", text)
    with pytest.raises(UnsupportedUnitSyntax):
        firings(tmp_path)
