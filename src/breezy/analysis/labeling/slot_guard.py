"""The score-live-trials catch-up guard (AUT-2 r7 WP6, section 3.10, L2 and V1).

``Persistent=true`` means a host outage across 13:55Z fires the tally at the next timer activation,
at any hour. ``ExecCondition=slot-guard-run.sh`` refuses a start whose worst-case span
``[start, start + AccuracySec + TimeoutStartSec + TimeoutStopSec]`` meets the launch window
``[16:30Z, 17:10Z)`` or whose start lies in the heavy night ``[01:00Z, 04:30Z)``. The scheduled
start (the timer's own ``OnCalendar`` time, within its ``AccuracySec``) is always permitted. Every
bound is read from the unit files; an absent ``TimeoutStopSec`` is systemd's 90 s default (V6).

Exit codes: 0 permit, ``SLOT_GUARD_REFUSED_RC`` (10) deliberate refusal, 255 any internal error;
the wrapper maps them to 0 / 1 / 255 for systemd.
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from breezy.analysis.labeling.constants import (
    CATCHUP_DENY_UTC,
    SLOT_GUARD_REFUSED_RC,
    SYSTEMD_DEFAULT_TIMEOUT_STOP_S,
)

__all__ = [
    "LAUNCH_WINDOW",
    "NIGHT_WINDOW",
    "SlotDecision",
    "catch_up_permitted",
    "main",
    "parse_systemd_span_s",
]

#: The ARCH launch window opens at 16:30Z (``CATCHUP_DENY_UTC`` holds the derived deny START, 16:30
#: minus the current units' worst-case span, which the guard recomputes from the unit files). Its
#: end and the heavy night come straight from ``CATCHUP_DENY_UTC``; a test ties the 16:30 to it.
_LAUNCH_FROM: Final = dt.time(16, 30)
_LAUNCH_UNTIL: Final = CATCHUP_DENY_UTC[0][1]
_NIGHT_FROM: Final = CATCHUP_DENY_UTC[1][0]
_NIGHT_UNTIL: Final = CATCHUP_DENY_UTC[1][1]
LAUNCH_WINDOW: Final = (_LAUNCH_FROM, _LAUNCH_UNTIL)
NIGHT_WINDOW: Final = (_NIGHT_FROM, _NIGHT_UNTIL)
_DEFAULT_ACCURACY_S: Final = 60.0  # systemd's default AccuracySec
_INTERNAL_ERROR_RC: Final = 255
_UNIT_RE: Final = re.compile(r"\Abreezy-[a-z0-9-]{1,64}\Z")
_SPAN_RE: Final = re.compile(r"\A(\d+(?:\.\d+)?)\s*(us|ms|s|sec|min|m|h|d)?\Z")
_SPAN_UNITS: Final = {
    None: 1.0,
    "us": 1e-6,
    "ms": 1e-3,
    "s": 1.0,
    "sec": 1.0,
    "min": 60.0,
    "m": 60.0,
    "h": 3600.0,
    "d": 86400.0,
}
_CALENDAR_RE: Final = re.compile(r"\A\*-\*-\*\s+(\d\d):(\d\d):(\d\d)\s+UTC\Z")


@dataclass(frozen=True)
class SlotDecision:
    permitted: bool
    reason: str | None = None


def parse_systemd_span_s(text: str) -> float:
    """Seconds in a systemd time span of one number and one unit (a bare number is seconds)."""
    found = _SPAN_RE.match(text.strip())
    if found is None:
        raise ValueError(f"not a systemd time span: {text!r}")
    return float(found.group(1)) * _SPAN_UNITS[found.group(2)]


def _directives(text: str, section: str, key: str) -> list[str]:
    values: list[str] = []
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1]
        elif current == section and line.startswith(f"{key}="):
            values.append(line.split("=", 1)[1].strip())
    return values


def _one_span(text: str, section: str, key: str, default: float | None) -> float:
    values = _directives(text, section, key)
    if not values:
        if default is None:
            raise ValueError(f"{key} is absent")
        return default
    return parse_systemd_span_s(values[-1])


def _scheduled_times(timer_text: str) -> list[dt.time]:
    times: list[dt.time] = []
    for line in _directives(timer_text, "Timer", "OnCalendar"):
        found = _CALENDAR_RE.match(line)
        if found is None:
            raise ValueError("OnCalendar is not a plain daily UTC time")
        times.append(dt.time(int(found[1]), int(found[2]), int(found[3])))
    return times


def _at(day: dt.date, clock: dt.time) -> dt.datetime:
    return dt.datetime.combine(day, clock, tzinfo=dt.UTC)


def catch_up_permitted(now_utc: dt.datetime, timer_text: str, service_text: str) -> SlotDecision:
    """Whether a start at ``now_utc`` is permitted, from the timer and service unit texts."""
    accuracy = _one_span(timer_text, "Timer", "AccuracySec", _DEFAULT_ACCURACY_S)
    start_s = _one_span(service_text, "Service", "TimeoutStartSec", None)
    stop_s = _one_span(
        service_text, "Service", "TimeoutStopSec", float(SYSTEMD_DEFAULT_TIMEOUT_STOP_S)
    )
    now = now_utc.astimezone(dt.UTC)
    for scheduled in _scheduled_times(timer_text):
        slot = _at(now.date(), scheduled)
        if slot <= now <= slot + dt.timedelta(seconds=accuracy):
            return SlotDecision(True)
    end = now + dt.timedelta(seconds=accuracy + start_s + stop_s)
    window_lo, window_hi = _at(now.date(), _LAUNCH_FROM), _at(now.date(), _LAUNCH_UNTIL)
    if now < window_hi and end >= window_lo:
        return SlotDecision(False, "launch_window")
    if _at(now.date(), _NIGHT_FROM) <= now < _at(now.date(), _NIGHT_UNTIL):
        return SlotDecision(False, "heavy_night")
    return SlotDecision(True)


def _default_unit_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "deploy" / "systemd"


def main(
    argv: Sequence[str] | None = None,
    *,
    now: dt.datetime | None = None,
    unit_dir: Path | None = None,
) -> int:
    """0 permit, 10 deliberate refusal (prints the deferral line), 255 any internal error."""
    try:
        parser = argparse.ArgumentParser(prog="slot_guard", exit_on_error=False)
        parser.add_argument("--unit", required=True)
        args = parser.parse_args(list(argv) if argv is not None else sys.argv[1:])
        if _UNIT_RE.match(args.unit) is None:
            raise ValueError("the unit name is not a plain breezy-* name")
        directory = unit_dir if unit_dir is not None else _default_unit_dir()
        timer = (directory / f"{args.unit}.timer").read_text(encoding="utf-8")
        service = (directory / f"{args.unit}.service").read_text(encoding="utf-8")
        decision = catch_up_permitted(now or dt.datetime.now(dt.UTC), timer, service)
    except (SystemExit, Exception):  # noqa: BLE001 - every internal failure is exit 255 (V1)
        return _INTERNAL_ERROR_RC
    if decision.permitted:
        return 0
    print(f"SCORE_LIVE_TRIALS CATCHUP_DEFERRED reason={decision.reason}")
    return SLOT_GUARD_REFUSED_RC


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
