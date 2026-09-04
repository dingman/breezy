"""Unit tests for `breezy.ingest.nws_observation_rebuild` -- BL-24 Seam B, A8 helpers.

Pure functions the Actor's restart rebuild is decided with. The instants are
the recorded fixture's: fetched 2026-09-04T02:34:57Z, KMDW, local STANDARD
time UTC-6, so the current climate day began at 2026-09-03T06:00:00Z.
"""

from __future__ import annotations

import datetime as dt

import pytest

from breezy.ingest.nws_observation_rebuild import (
    REBUILD_ROW_MARGIN,
    local_standard_midnight_ns,
    observation_fetch_limit,
    rebuild_is_trusted,
)

_NS = 1_000_000_000
_FETCH_INSTANT_NS = 1_788_489_297_658_387_295
_MDW_STD_OFFSET_HOURS = -6.0
_MIDNIGHT_NS = int(dt.datetime(2026, 9, 3, 6, 0, tzinfo=dt.UTC).timestamp()) * _NS
_BOUND_NS = 2_700 * _NS


def test_local_standard_midnight_is_the_climate_days_start_never_dst() -> None:
    # September in Chicago is CDT (UTC-5) on the wall clock; the climate day
    # still starts at CST midnight (06:00Z), never at 05:00Z.
    assert local_standard_midnight_ns(_FETCH_INSTANT_NS, _MDW_STD_OFFSET_HOURS) == _MIDNIGHT_NS


def test_local_standard_midnight_uses_integer_arithmetic_only() -> None:
    midnight = local_standard_midnight_ns(_FETCH_INSTANT_NS, _MDW_STD_OFFSET_HOURS)
    assert isinstance(midnight, int)
    assert midnight % _NS == 0


@pytest.mark.parametrize(
    ("elapsed_seconds", "expected"),
    [
        (0, REBUILD_ROW_MARGIN),
        (1, 1 + REBUILD_ROW_MARGIN),
        (300, 1 + REBUILD_ROW_MARGIN),
        (301, 2 + REBUILD_ROW_MARGIN),
        (86_400, 288 + REBUILD_ROW_MARGIN),
        (10 * 86_400, 500),
    ],
)
def test_the_fetch_limit_follows_the_brief_and_caps_at_the_api_ceiling(
    elapsed_seconds: int, expected: int
) -> None:
    assert observation_fetch_limit(elapsed_seconds) == expected


def test_a_negative_elapsed_is_refused() -> None:
    with pytest.raises(ValueError):
        observation_fetch_limit(-1)


def test_a_rebuild_reaching_midnight_with_no_gap_over_the_bound_is_trusted() -> None:
    rows = tuple(range(_MIDNIGHT_NS - 600 * _NS, _FETCH_INSTANT_NS, 300 * _NS))
    assert rebuild_is_trusted(
        sorted_observed_ns=rows, midnight_ns=_MIDNIGHT_NS, staleness_bound_ns=_BOUND_NS
    )


def test_a_rebuild_whose_oldest_row_is_after_midnight_plus_the_bound_is_not_trusted() -> None:
    rows = tuple(range(_MIDNIGHT_NS + _BOUND_NS + _NS, _FETCH_INSTANT_NS, 300 * _NS))
    assert not rebuild_is_trusted(
        sorted_observed_ns=rows, midnight_ns=_MIDNIGHT_NS, staleness_bound_ns=_BOUND_NS
    )


def test_a_rebuild_with_a_gap_over_the_bound_is_not_trusted() -> None:
    before = tuple(range(_MIDNIGHT_NS, _MIDNIGHT_NS + 3_600 * _NS, 300 * _NS))
    after = tuple(range(_MIDNIGHT_NS + 3_600 * _NS + _BOUND_NS + _NS, _FETCH_INSTANT_NS, 300 * _NS))
    assert not rebuild_is_trusted(
        sorted_observed_ns=before + after, midnight_ns=_MIDNIGHT_NS, staleness_bound_ns=_BOUND_NS
    )


def test_an_empty_rebuild_is_never_trusted() -> None:
    assert not rebuild_is_trusted(
        sorted_observed_ns=(), midnight_ns=_MIDNIGHT_NS, staleness_bound_ns=_BOUND_NS
    )


def test_a_single_row_at_midnight_is_trusted_when_within_the_bound() -> None:
    """One row has no consecutive gap; coverage from midnight is what is checked."""
    assert rebuild_is_trusted(
        sorted_observed_ns=(_MIDNIGHT_NS,), midnight_ns=_MIDNIGHT_NS, staleness_bound_ns=_BOUND_NS
    )
