"""RED-first: ``nbp_version_breaks`` flags a version change only between consecutive climate days.

KNYC has no 2025 rows (v4.2 on 2024-12-31, v4.3 on 2026-01-01); the change across that gap is not
an observed break and must not split a fold. A real change seen by other stations still reports.
"""

from __future__ import annotations

import datetime as dt

from breezy.analysis import multisource_blend as msb
from scripts.analysis.multisource_blend_inputs_report import nbp_version_breaks
from tests.unit.test_multisource_blend import _row


def _r(station: str, day: dt.date, version: str) -> msb.FeatureRow:
    return _row(
        station=station,
        day=day,
        version=version,
        horizon="D0",
        y=70.0,
        nbp=70.0,
        sd=3.0,
        obs=None,
        lamp=None,
        pfm=None,
        mos=None,
    )


def test_version_change_across_station_day_gap_is_not_a_break() -> None:
    rows = [
        _r("KNYC", dt.date(2024, 12, 31), "v4.2"),
        _r("KNYC", dt.date(2026, 1, 1), "v4.3"),
    ]
    assert nbp_version_breaks(rows) == []


def test_equal_version_across_gap_is_not_a_break() -> None:
    rows = [
        _r("KNYC", dt.date(2024, 12, 31), "v4.2"),
        _r("KNYC", dt.date(2026, 1, 1), "v4.2"),
    ]
    assert nbp_version_breaks(rows) == []


def test_consecutive_day_change_still_breaks_while_gapped_station_does_not() -> None:
    rows = [
        _r("KNYC", dt.date(2024, 12, 31), "v4.2"),
        _r("KNYC", dt.date(2026, 1, 1), "v4.3"),
        _r("KORD", dt.date(2025, 5, 27), "v4.2"),
        _r("KORD", dt.date(2025, 5, 28), "v4.3"),
    ]
    assert nbp_version_breaks(rows) == ["2025-05-28"]
