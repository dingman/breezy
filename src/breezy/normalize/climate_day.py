"""Map an instant to its climate day.

PURE module: no I/O, no clock access, no `nautilus_trader` import, no
global state.

The climate day runs local-STANDARD-time midnight to midnight, all year
round -- regardless of whether the calendar date falls under daylight
saving. This module NEVER uses `zoneinfo.ZoneInfo`: an IANA zone follows
DST, which would alias the climate-day window across the spring/fall
transitions and silently settle the wrong day. The standard-time offset
is always supplied by the caller (from the site registry); nothing here
hardcodes a per-city value.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


class ClimateDayError(ValueError):
    """Raised when an instant cannot be mapped to a climate day."""


def standard_time_zone(std_utc_offset_hours: float) -> timezone:
    """Build a fixed-offset `timezone` for a site's local STANDARD time.

    `std_utc_offset_hours` must be the site's STANDARD (winter) UTC
    offset year-round, e.g. -5.0 for America/New_York, -6.0 for
    America/Chicago, -8.0 for America/Los_Angeles. Never derive this from
    an IANA zone at call time -- that would follow DST.
    """
    return timezone(timedelta(hours=std_utc_offset_hours))


def climate_day_for_instant(instant: datetime, std_utc_offset_hours: float) -> date:
    """Return the local-standard-time calendar date containing `instant`.

    `instant` must be timezone-aware; a naive datetime is rejected because
    its alignment to UTC would be ambiguous, and this is a settlement-path
    function where an ambiguous conversion is a silent-wrong-day risk.
    """
    if instant.tzinfo is None:
        raise ClimateDayError(
            "instant must be timezone-aware; a naive datetime has ambiguous UTC alignment"
        )
    tz = standard_time_zone(std_utc_offset_hours)
    return instant.astimezone(tz).date()
