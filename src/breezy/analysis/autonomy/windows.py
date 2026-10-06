"""Forward-window and slot arithmetic (AUT-4 r11 §3.1 Z4, §3.5 W7). Pure; no clock, no I/O."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Final

from breezy.persistence.autonomy.pins import (
    FORWARD_WINDOW_DAYS_MAX,
    FORWARD_WINDOW_DAYS_MIN,
    MAX_VERDICT_VALIDITY_H,
)

NS_PER_S: Final[int] = 1_000_000_000
SECONDS_PER_HOUR: Final[int] = 3_600


@dataclass(frozen=True, slots=True)
class ForwardWindow:
    """One tumbling window: ``start`` and ``end`` are both INCLUSIVE climate days."""

    index: int
    start: dt.date
    end: dt.date


def slot_start_ns(slot_date: dt.date, slot_utc: str) -> int:
    """Epoch ns of ``slot_date`` at ``slot_utc`` (``"HH:MM"``), the unit's ``OnCalendar``."""
    hour, minute = slot_utc.split(":")
    start = dt.datetime(
        slot_date.year, slot_date.month, slot_date.day, int(hour), int(minute), tzinfo=dt.UTC
    )
    return int(start.timestamp()) * NS_PER_S


def valid_until_ns(slot_start: int, validity_h: int = MAX_VERDICT_VALIDITY_H) -> int:
    """``slot_start + validity_h`` hours; never above the ceiling ``MAX_VERDICT_VALIDITY_H``."""
    if validity_h > MAX_VERDICT_VALIDITY_H:
        raise ValueError(f"validity {validity_h} h exceeds the ceiling {MAX_VERDICT_VALIDITY_H} h")
    if validity_h <= 0:
        raise ValueError("validity must be positive")
    return slot_start + validity_h * SECONDS_PER_HOUR * NS_PER_S


def forward_window(anchor: dt.date, window_days: int, on: dt.date) -> ForwardWindow:
    """The tumbling window of ``window_days`` days, anchored at ``anchor``, that contains ``on``."""
    if not FORWARD_WINDOW_DAYS_MIN <= window_days <= FORWARD_WINDOW_DAYS_MAX:
        raise ValueError(
            f"window_days {window_days} outside the pins range "
            f"[{FORWARD_WINDOW_DAYS_MIN}, {FORWARD_WINDOW_DAYS_MAX}]"
        )
    elapsed = (on - anchor).days
    if elapsed < 0:
        raise ValueError(f"{on} precedes the window anchor {anchor}")
    index = elapsed // window_days
    start = anchor + dt.timedelta(days=index * window_days)
    return ForwardWindow(index, start, start + dt.timedelta(days=window_days - 1))


def nominee_may_use_day(day: dt.date, nomination_date: dt.date, window_end: dt.date) -> bool:
    """A nominee uses only climate days strictly after its nomination's UTC date, up to the end."""
    return nomination_date < day <= window_end
