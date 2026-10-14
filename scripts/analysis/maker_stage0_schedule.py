"""MAKER-S2 WP1: the process schedule -- PRIMARY on every day, a logged-relaunch OVERLAY beside it.

Plan r4 delta (d). One schedule source decides the label: the PRIMARY (nominal) schedule.

* Window: ``permit_window_for_day(D-1)`` = ``[D-1 16:50Z, D 02:50Z)`` (imported, not restated).
* Cuts: the UTC-midnight GTD cut (``D 00:00Z``), the permit expiry (the window end) and
  ``STOP_PRIOR_UTC`` on ``D`` (imported; after the window, so inert for in-window bids but listed).
* The OVERLAY is a report-only second pass: it adds a ``RELAUNCH`` cut (cancel-on-stop and a new
  episode) at each logged mid-day boot of a day whose node log fully covers the window. It never
  replaces the PRIMARY mapping and never sets a label. Days with no covering log
(``node_log_absent``)
  and full-day outage days keep the PRIMARY schedule.

A boot line is the day's LAUNCH (no cut) unless the node was already up when the window opened
(a permit issued before ``start`` that is still valid then): then every in-window boot is a
relaunch.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from breezy.runtime.trade_supervisor_core import STOP_PRIOR_UTC
from scripts.analysis.maker_stage0_nodelog import (
    LogStatus,
    NodeLogScan,
    boots_in_window,
    classify_day,
    permit_meets_window,
)
from scripts.analysis.nbp_shadow_parity_pure import permit_window_for_day

__all__ = [
    "Cut",
    "DaySchedule",
    "day_log_status",
    "overlay_schedule",
    "primary_schedule",
    "process_schedule",
    "schedule_to_dict",
    "write_schedule",
]

GTD_MIDNIGHT: Final[str] = "GTD_MIDNIGHT"
PERMIT_EXPIRY: Final[str] = "PERMIT_EXPIRY"
STOP_PRIOR: Final[str] = "STOP_PRIOR"
RELAUNCH: Final[str] = "RELAUNCH"
_NS: Final[int] = 1_000_000_000


@dataclass(frozen=True, slots=True)
class Cut:
    """An instant at which every resting bid is cancelled (a new episode starts after it)."""

    kind: str
    instant_ns: int


@dataclass(frozen=True, slots=True)
class DaySchedule:
    climate_day: dt.date
    window_start_ns: int
    window_end_ns: int
    cuts: tuple[Cut, ...]

    @property
    def window(self) -> tuple[int, int]:
        return self.window_start_ns, self.window_end_ns


def _utc_ns(day: dt.date, at: dt.time) -> int:
    return int(dt.datetime.combine(day, at, tzinfo=dt.UTC).timestamp()) * _NS


def _ordered(cuts: Iterable[Cut]) -> tuple[Cut, ...]:
    return tuple(sorted(cuts, key=lambda c: (c.instant_ns, c.kind)))


def primary_schedule(climate_day: dt.date) -> DaySchedule:
    """The nominal schedule for ``climate_day`` (identical on every day)."""
    start, end = permit_window_for_day(climate_day - dt.timedelta(days=1))
    cuts = (
        Cut(GTD_MIDNIGHT, _utc_ns(climate_day, dt.time(0, 0))),
        Cut(PERMIT_EXPIRY, end),
        Cut(STOP_PRIOR, _utc_ns(climate_day, STOP_PRIOR_UTC)),
    )
    return DaySchedule(climate_day, start, end, _ordered(cuts))


def process_schedule(days: Iterable[dt.date]) -> dict[dt.date, DaySchedule]:
    """PRIMARY schedule for every day (node logs never enter it)."""
    return {day: primary_schedule(day) for day in sorted(set(days))}


def day_log_status(
    days: Iterable[dt.date], scans: Sequence[NodeLogScan]
) -> dict[dt.date, LogStatus]:
    return {d: classify_day(scans, primary_schedule(d).window) for d in sorted(set(days))}


def _relaunch_instants(scans: Sequence[NodeLogScan], base: DaySchedule) -> list[int]:
    boots = boots_in_window(scans, base.window)
    already_up = any(
        p.issued_ns < base.window_start_ns and permit_meets_window(p, base.window)
        for scan in scans
        for p in scan.permits
    )
    return boots if already_up else boots[1:]


def overlay_schedule(
    days: Iterable[dt.date], scans: Sequence[NodeLogScan]
) -> dict[dt.date, DaySchedule]:
    """Report-only: PRIMARY plus a ``RELAUNCH`` cut per logged mid-day boot on covered LIVE days."""
    status = day_log_status(days, scans)
    out: dict[dt.date, DaySchedule] = {}
    for day, state in status.items():
        base = primary_schedule(day)
        if state is not LogStatus.LIVE:
            out[day] = base
            continue
        extra = [Cut(RELAUNCH, ns) for ns in _relaunch_instants(scans, base)]
        out[day] = DaySchedule(
            day, base.window_start_ns, base.window_end_ns, _ordered([*base.cuts, *extra])
        )
    return out


def schedule_to_dict(
    schedule: Mapping[dt.date, DaySchedule], *, kind: str = "PRIMARY"
) -> dict[str, Any]:
    days = {
        day.isoformat(): {
            "window_start_ns": item.window_start_ns,
            "window_end_ns": item.window_end_ns,
            "cuts": [{"kind": c.kind, "instant_ns": c.instant_ns} for c in item.cuts],
        }
        for day, item in sorted(schedule.items())
    }
    return {"schedule": kind, "days": days}


def write_schedule(
    path: Path, schedule: Mapping[dt.date, DaySchedule], *, kind: str = "PRIMARY"
) -> Path:
    """Deterministic JSON (``process_schedule.json`` / ``process_schedule_overlay.json``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(schedule_to_dict(schedule, kind=kind), indent=2, sort_keys=True)
    path.write_text(body + "\n", encoding="utf-8")
    return path
