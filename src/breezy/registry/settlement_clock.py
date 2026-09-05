"""Shared settlement-clock arithmetic for a `(venue, city)` site.

Promoted (I2, `docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md` section
3.0/I2) from `breezy.ingest.nws_actor.NwsIngestActor._settlement_deadline_ns`,
a private five-line method: both `check_final_deadline` (the NWS-completeness
clock) and `scripts/analysis/score_live_trials.py`'s live fill reader need
the venue's settlement instant for a climate day, and duplicating that
arithmetic is exactly the kind of drift this promotion avoids. `nws_actor.py`
now calls this module instead of computing it inline; its own tests are
unaffected because they exercise `check_final_deadline`, never the private
method directly.

The venue's settlement instant is `climate_day + 1` at
`SettlementDeadline.settlement_time_local` in
`SettlementDeadline.settlement_timezone` -- the DST-following VENUE clock
(America/New_York for every Polymarket.us site today, regardless of station
location), never `ClimateDayWindow.std_utc_offset_hours`, which is the fixed
standard-time offset that defines the climate day's own midnight-to-midnight
window and nothing else. `breezy.registry.sites` documents that separation;
this module never imports `ClimateDayWindow`.
"""

from __future__ import annotations

import datetime as dt
from typing import Final
from zoneinfo import ZoneInfo

from breezy.registry.sites import SettlementDeadline

__all__ = ["settlement_deadline_ns"]

_NS_PER_SECOND: Final[int] = 1_000_000_000


def settlement_deadline_ns(deadline: SettlementDeadline, climate_day: dt.date) -> int:
    """The venue's settlement instant for `climate_day`, in ns since epoch.

    `climate_day + 1` at `deadline.settlement_time_local` in
    `deadline.settlement_timezone`.
    """
    hour_text, minute_text = deadline.settlement_time_local.split(":")
    when = dt.datetime.combine(
        climate_day + dt.timedelta(days=1),
        dt.time(int(hour_text), int(minute_text)),
        tzinfo=ZoneInfo(deadline.settlement_timezone),
    )
    return int(when.timestamp()) * _NS_PER_SECOND
