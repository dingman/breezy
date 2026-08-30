"""Unit tests for archived CLI supersession selection.

These pin the live/archive runtime type barrier in both directions. The mutant
they kill is widening either selector's `_require_unwrapped` to a union or
Protocol, which would legalise a merged live+archived stream.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any

import pytest

from breezy.domain.archived_climate_day import (
    ARCHIVED_CLIMATE_DAY_SCHEMA_VERSION,
    ArchivedClimateDay,
)
from breezy.domain.archived_selection import (
    latest_by_archived_climate_day,
    select_archived_climate_day,
)
from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.domain.selection import latest_by_climate_day

_DAY = dt.date(2026, 8, 22)
_ISSUED_NS = int(dt.datetime(2026, 8, 23, 6, 27, tzinfo=dt.UTC).timestamp()) * 1_000_000_000
_ARCHIVE_RETRIEVED_NS = (
    int(dt.datetime(2026, 8, 29, 12, 0, tzinfo=dt.UTC).timestamp()) * 1_000_000_000
)
_LIVE_RETRIEVED_NS = _ISSUED_NS + 300_000_000_000
_SHA = hashlib.sha256(b"archive-selection").hexdigest()


def make_archived_day(**overrides: Any) -> ArchivedClimateDay:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": _DAY,
        "tmax_f": 84,
        "tmin_f": 63,
        "tavg_f": 74,
        "tmax_flag": None,
        "tmin_flag": None,
        "tavg_flag": None,
        "is_final": True,
        "correction_flag": False,
        "is_correction_bbb": False,
        "revision_seq": 1,
        "issuing_office": "KOKX",
        "wmo_transmission_sequence": "100",
        "wmo_bbb_token": None,
        "issuance_time_ns": _ISSUED_NS,
        "issuance_time_source": "wmo_filename",
        "archive_retrieved_at_ns": _ARCHIVE_RETRIEVED_NS,
        "archive_source_url": "https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?<redacted>",
        "archive_job_version": "breezy-archive-backfill@stage2-test",
        "parser_version": "breezy.normalize.cli_parse@0.1.0",
        "registry_version": "1.0.0",
        "raw_sha256": _SHA,
        "station_year_yield": 0.9836,
        "admission_era": "modern",
        "schema_version": ARCHIVED_CLIMATE_DAY_SCHEMA_VERSION,
    }
    kwargs.update(overrides)
    return ArchivedClimateDay(**kwargs)


def make_live_day(**overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": _DAY,
        "tmax_f": 84,
        "tmin_f": 63,
        "tavg_f": 74,
        "tmax_flag": None,
        "tmin_flag": None,
        "tavg_flag": None,
        "is_final": True,
        "correction_flag": False,
        "revision_seq": 1,
        "is_superseded": False,
        "issuing_office": "KOKX",
        "issuance_time_ns": _ISSUED_NS,
        "retrieved_at_ns": _LIVE_RETRIEVED_NS,
        "parser_version": "breezy.normalize.cli_parse@0.1.0",
        "registry_version": "1.0.0",
        "raw_sha256": _SHA,
        "source_channel": "api.weather.gov",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": int(dt.datetime(2026, 8, 23, 5, 0, tzinfo=dt.UTC).timestamp())
        * 1_000_000_000,
    }
    kwargs.update(overrides)
    return NwsClimateDay(**kwargs)


def test_live_selector_rejects_archived_row_and_mixed_stream() -> None:
    """Separation mutant: widening live `_require_unwrapped` to live|archived."""
    archived = make_archived_day()
    live = make_live_day()

    with pytest.raises(TypeError, match="ArchivedClimateDay"):
        latest_by_climate_day([archived])

    with pytest.raises(TypeError, match="ArchivedClimateDay"):
        latest_by_climate_day([live, archived])


def test_archived_selector_rejects_live_row_symmetrically() -> None:
    """Separation mutant: archived helper accepting `NwsClimateDay`."""
    with pytest.raises(TypeError, match="NwsClimateDay"):
        latest_by_archived_climate_day([make_live_day()])


def test_archived_selection_duplicates_live_ordering_with_finality_leading() -> None:
    """Selection mutant: ordering by timestamp before `is_final`."""
    final = make_archived_day(tmax_f=84, is_final=True, revision_seq=1)
    late_prelim = make_archived_day(
        tmax_f=82,
        is_final=False,
        revision_seq=9,
        issuance_time_ns=_ISSUED_NS + 7 * 86_400_000_000_000,
        archive_retrieved_at_ns=_ARCHIVE_RETRIEVED_NS + 7 * 86_400_000_000_000,
    )

    selected = select_archived_climate_day([late_prelim, final], "NYC", _DAY)

    assert selected is final
    assert selected.tmax_f == 84


def test_archived_as_of_bound_filters_before_ordering() -> None:
    """Selection mutant: letting a later final leak into an earlier as-of answer."""
    preliminary = make_archived_day(
        tmax_f=82,
        is_final=False,
        issuance_time_ns=_ISSUED_NS - 10_000_000_000,
    )
    final = make_archived_day(tmax_f=84, is_final=True)

    selected = select_archived_climate_day(
        [preliminary, final],
        "NYC",
        _DAY,
        as_of_ts_init=preliminary.ts_init,
    )

    assert selected is preliminary
    assert selected.is_final is False
