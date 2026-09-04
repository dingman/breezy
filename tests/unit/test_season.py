"""Pins `breezy.domain.season.season_for` against the literal table at
`scripts/analysis/pmr_climatology_study.py:182-187` (`_SEASON_BY_MONTH`).
`scripts/` is unimportable from `src/breezy` (layers contract), so this test
pins the measured literals directly rather than importing the script.
"""

from __future__ import annotations

import datetime as dt

import pytest

from breezy.domain.season import season_for

#: Verbatim copy of `scripts/analysis/pmr_climatology_study.py:182-187`.
_EXPECTED_SEASON_BY_MONTH = {
    12: "DJF", 1: "DJF", 2: "DJF",
    3: "MAM", 4: "MAM", 5: "MAM",
    6: "JJA", 7: "JJA", 8: "JJA",
    9: "SON", 10: "SON", 11: "SON",
}


@pytest.mark.parametrize("month", range(1, 13))
def test_season_for_matches_the_pinned_climatology_study_table(month: int) -> None:
    climate_day = dt.date(2026, month, 15)
    assert season_for(climate_day) == _EXPECTED_SEASON_BY_MONTH[month]
