"""Unit tests for the AUD-18 IEM MOS closed-day freshness check.

``tests/conftest.py`` blocks real sockets for anything not marked
``live``/``allow_socket``; nothing here carries either marker, and this
module never fetches -- ``check_and_alert`` reads only the on-disk manifest.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any, Final

import pytest

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
for _entry in (str(_REPO_ROOT / "scripts" / "archive"), str(_REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

from iem_mos_freshness_check import (
    IEM_MOS_ARCHIVE_STALE_EVENT,
    IemMosFreshnessDetail,
    check_and_alert,
    main,
)

from breezy.persistence.archive_cache import ArchiveCache
from breezy.persistence.archive_request import iem_mos_window_request

STATION_A: Final[str] = "KMIA"
STATION_B: Final[str] = "KLAX"
MODEL: Final[str] = "NBS"
_BODY: Final[bytes] = b"runtime,model,station\n2026-09-24 00:00:00,NBS,KMIA\n"


class _Clock:
    def timestamp_ns(self) -> int:
        return 1_790_000_000_000_000_000


class _RecordingSink:
    def __init__(self) -> None:
        self.emitted: list[Any] = []

    def emit(self, payload: Any) -> None:
        self.emitted.append(payload)


def _cache(root: Path) -> ArchiveCache:
    return ArchiveCache(root=root, fetch=lambda _request: _BODY, clock=_Clock())


def test_one_missed_night_emits_warn_per_station(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    cache = _cache(root)
    latest_day = dt.date(2026, 9, 24)
    stations = (STATION_A, STATION_B)
    # Entries through L-1 (2026-09-23), none for L (2026-09-24).
    for station in stations:
        request = iem_mos_window_request(
            station, latest_day - dt.timedelta(days=1), latest_day, MODEL
        )
        cache.get_or_fetch(request)

    sink = _RecordingSink()
    stale = check_and_alert(
        cache_root=root, stations=stations, model=MODEL, latest_day=latest_day, sink=sink
    )

    assert stale is True
    assert len(sink.emitted) == len(stations)
    assert {payload.site for payload in sink.emitted} == set(stations)
    assert all(payload.event == IEM_MOS_ARCHIVE_STALE_EVENT for payload in sink.emitted)
    assert all(payload.severity == "WARN" for payload in sink.emitted)
    assert all(
        payload.detail == IemMosFreshnessDetail.LATEST_CLOSED_DAY_MISSING.value
        for payload in sink.emitted
    )


def test_fresh_when_latest_closed_day_key_present(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    cache = _cache(root)
    latest_day = dt.date(2026, 9, 24)
    request = iem_mos_window_request(
        STATION_A, latest_day, latest_day + dt.timedelta(days=1), MODEL
    )
    cache.get_or_fetch(request)

    sink = _RecordingSink()
    stale = check_and_alert(
        cache_root=root, stations=(STATION_A,), model=MODEL, latest_day=latest_day, sink=sink
    )

    assert stale is False
    assert sink.emitted == []


def test_overwide_entry_spanning_latest_day_does_not_satisfy(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    cache = _cache(root)
    latest_day = dt.date(2026, 9, 25)
    wide = iem_mos_window_request(
        STATION_A, dt.date(2026, 9, 20), dt.date(2026, 9, 27), MODEL
    )
    cache.get_or_fetch(wide)

    sink = _RecordingSink()
    stale = check_and_alert(
        cache_root=root, stations=(STATION_A,), model=MODEL, latest_day=latest_day, sink=sink
    )

    assert stale is True
    assert len(sink.emitted) == 1
    assert sink.emitted[0].detail == IemMosFreshnessDetail.LATEST_CLOSED_DAY_MISSING.value


def test_missing_manifest_emits_single_global_alert(tmp_path: Path) -> None:
    root = tmp_path / "never-populated-cache"

    sink = _RecordingSink()
    stale = check_and_alert(
        cache_root=root,
        stations=(STATION_A, STATION_B),
        model=MODEL,
        latest_day=dt.date(2026, 9, 24),
        sink=sink,
    )

    assert stale is True
    assert len(sink.emitted) == 1
    assert sink.emitted[0].site == "global"
    assert sink.emitted[0].detail == IemMosFreshnessDetail.MANIFEST_MISSING.value


def test_unreadable_manifest_emits_alert_exit_0(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "cache"
    manifest_dir = root / "iem-mos"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "coverage.json").write_text("not valid json {{{")

    sink = _RecordingSink()
    stale = check_and_alert(
        cache_root=root, stations=(STATION_A,), model=MODEL,
        latest_day=dt.date(2026, 9, 24), sink=sink,
    )

    assert stale is True
    assert len(sink.emitted) == 1
    assert sink.emitted[0].detail == IemMosFreshnessDetail.MANIFEST_UNREADABLE.value

    monkeypatch.delenv("BREEZY_ALERT_WEBHOOK_URL", raising=False)
    code = main(["--cache-root", str(root), "--stations", STATION_A], env={})
    assert code == 0


def test_freshness_detail_has_no_path_or_user_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel_ua = "breezy-freshness-check-SENTINEL-UA-TESTONLY"
    monkeypatch.setenv("BREEZY_USER_AGENT", sentinel_ua)
    root = tmp_path / "never-populated-cache"

    sink = _RecordingSink()
    stale = check_and_alert(
        cache_root=root,
        stations=(STATION_A, STATION_B),
        model=MODEL,
        latest_day=dt.date(2026, 9, 24),
        sink=sink,
    )

    assert stale is True
    assert sink.emitted
    for payload in sink.emitted:
        for value in payload.to_dict().values():
            assert "/" not in value
            assert sentinel_ua not in value
        assert payload.detail in {detail.value for detail in IemMosFreshnessDetail}
