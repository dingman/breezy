"""IEM ASOS 1-minute request factory: station+year only, drop-counting rows."""

from __future__ import annotations

import datetime as dt


def test_request_is_built_purely_from_station_and_year() -> None:
    from breezy.persistence.archive_request import IEM_ASOS_1MIN_SOURCE, iem_asos_1min_request

    request = iem_asos_1min_request("KNYC", 2024)

    start = dt.datetime(2024, 1, 1, tzinfo=dt.UTC)
    end = dt.datetime(2025, 1, 1, tzinfo=dt.UTC)
    assert request.source == IEM_ASOS_1MIN_SOURCE
    assert request.station == "KNYC"
    assert request.product == "asos-1min"
    assert request.model is None
    assert request.window_start == int(start.timestamp()) * 1_000_000_000
    assert request.window_end == int(end.timestamp()) * 1_000_000_000
    assert not hasattr(request, "url")
    assert not hasattr(request, "hostname")


def test_count_rows_drops_never_interpolates() -> None:
    from breezy.persistence.archive_request import count_rows

    body = (
        b"station,valid,tmpf\n"
        b"KNYC,2024-01-01 00:00,32.0\n"
        b"\n"
        b"   \n"
        b"KNYC,2024-01-01 00:02,33.0\n"
    )

    assert count_rows(body) == 2
    assert count_rows(b"") == 0
    assert count_rows(b"station,valid,tmpf\n") == 0
    assert count_rows(b"\n\n") == 0
