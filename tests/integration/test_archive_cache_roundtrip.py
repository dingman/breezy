"""get_or_fetch round-trip: two stations × two years, fake fetch, tmp_path root."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path


class _Clock:
    def timestamp_ns(self) -> int:
        return 1_704_067_200_000_000_000


def _csv(station: str, year: int) -> bytes:
    return (
        "station,valid,tmpf\n"
        f"{station},{year}-01-01 00:00,32.0\n"
        f"{station},{year}-01-01 00:01,33.0\n"
    ).encode()


def test_get_or_fetch_roundtrip_two_stations_two_years(tmp_path: Path) -> None:
    from breezy.persistence.archive_cache import ArchiveCache
    from breezy.persistence.archive_request import iem_asos_1min_request

    fetches: list[tuple[str, int]] = []

    def fetch(request: object) -> bytes:
        station = request.station  # type: ignore[attr-defined]
        year = datetime.fromtimestamp(request.window_start / 1_000_000_000, tz=UTC).year  # type: ignore[attr-defined]
        fetches.append((station, year))
        return _csv(station, year)

    cache = ArchiveCache(root=tmp_path, fetch=fetch, clock=_Clock())
    requests = [
        iem_asos_1min_request(station, year)
        for station in ("KNYC", "KORD")
        for year in (2024, 2025)
    ]

    first_pass = [cache.get_or_fetch(request) for request in requests]
    assert len(fetches) == 4
    first_count = len(fetches)

    second_pass = [cache.get_or_fetch(request) for request in requests]
    assert len(fetches) == first_count
    assert second_pass == first_pass

    covered = cache.covered()
    assert {request.cache_key() for request in requests} <= set(covered)
    assert len(covered) == 4

    for request, body in zip(requests, first_pass, strict=True):
        read_back = cache.read(request)
        assert read_back == body
        assert hashlib.sha256(read_back).hexdigest() == hashlib.sha256(body).hexdigest()
