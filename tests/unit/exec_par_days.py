"""Test support: single-station UTC day conventions for the EXEC-PAR fixtures (BG-5c WP-C).

``UtcDays`` satisfies the ``DayConvention`` protocol of ``exec_par_governed_days`` with the UTC
date as the day label, so the BG-5a/5b fixtures (which label days by UTC date) keep their
meaning. The production convention is ``GovernedDays`` (per-station standard time).
"""

from __future__ import annotations

import datetime as dt

NS = 1_000_000_000


def utc_label(ns: int) -> str:
    return dt.datetime.fromtimestamp(ns // NS, dt.UTC).date().isoformat()


class UtcDays:
    """One synthetic station whose day is the UTC date."""

    def entry_day(self, station: str, arm_ns: int) -> str:
        return utc_label(arm_ns)

    def open_days_at(self, ts_ns: int) -> frozenset[str]:
        return frozenset({utc_label(ts_ns)})

    def today(self, ts_ns: int) -> str:
        return utc_label(ts_ns)
