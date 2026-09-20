"""The MOS read path resolves a DATE RANGE, not a calendar year (WP-7 blocker).

Why this test exists
--------------------
``build_corpus`` read forecasts as ``mos_cache.read(iem_mos_request(icao, year,
...))`` -- a YEAR-keyed lookup. The 2026 NBS backfill landed as EXPLICIT-WINDOW
entries (``2026-08-25 .. 2026-09-20``), which a year key can never name, so the
forecast leg read as absent and the WP-7 screen returned INSUFFICIENT-DATA at
n = 0 against a corpus that was actually on disk.

The three properties asserted here are exactly the three ways that failure can
recur:

1. a requested range inside a WINDOW entry resolves to that entry;
2. a day covered by BOTH a year entry and a window entry resolves ONCE -- a
   duplicated forecast row would double-weight a station-day in the screen's
   per-station-day trial unit; and
3. a requested day covered by NEITHER raises, naming the days. A silent
   shortfall here is indistinguishable from a real null, which is the failure
   this whole cycle was spent diagnosing.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _entry in (str(REPO_ROOT / "scripts" / "analysis"), str(REPO_ROOT / "src")):
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

MODEL = "NBS"
STATION = "KSFO"


class _Clock:
    def timestamp_ns(self) -> int:
        return 1_704_067_200_000_000_000


def _mos_csv(*runtimes: str) -> bytes:
    header = "station,model,runtime,ftime,txn\n"
    body = "".join(
        f"{STATION},{MODEL},{stamp},{stamp[:10]} 00:00:00,70\n" for stamp in runtimes
    )
    return (header + body).encode("utf-8")


def _cache(root: Path, payloads: dict[str, bytes]) -> Any:
    """A real ArchiveCache over ``root``; ``payloads`` is keyed by cache key."""
    from breezy.persistence.archive_cache import ArchiveCache

    def _fetch(request: Any) -> bytes:
        try:
            return payloads[request.cache_key()]
        except KeyError:  # pragma: no cover - a test-setup defect, never silent
            raise AssertionError(f"no prepared payload for {request.cache_key()}") from None

    return ArchiveCache(root=root, fetch=_fetch, clock=_Clock())


def _commit(cache: Any, request: Any, payloads: dict[str, bytes], body: bytes) -> None:
    payloads[request.cache_key()] = body
    cache.get_or_fetch(request)


def test_a_september_2026_range_resolves_to_the_window_entry(tmp_path: Path) -> None:
    from forecast_conditional_corpus import resolve_mos_coverage

    from breezy.persistence.archive_request import iem_mos_window_request

    payloads: dict[str, bytes] = {}
    cache = _cache(tmp_path, payloads)
    window = iem_mos_window_request(
        STATION, dt.date(2026, 8, 25), dt.date(2026, 9, 21), MODEL
    )
    _commit(cache, window, payloads, _mos_csv("2026-09-10 12:00:00"))

    coverage = resolve_mos_coverage(
        cache,
        station=STATION,
        start=dt.date(2026, 9, 1),
        end=dt.date(2026, 9, 21),
        model=MODEL,
    )

    assert coverage.requests() == (window,)
    assert coverage.days_for(window) == frozenset(
        dt.date(2026, 9, 1) + dt.timedelta(days=i) for i in range(20)
    )


def test_a_day_in_both_a_year_and_a_window_entry_resolves_exactly_once(
    tmp_path: Path,
) -> None:
    from forecast_conditional_corpus import read_mos_windows, resolve_mos_coverage

    from breezy.persistence.archive_request import iem_mos_request, iem_mos_window_request

    payloads: dict[str, bytes] = {}
    cache = _cache(tmp_path, payloads)
    year = iem_mos_request(STATION, 2026, MODEL)
    window = iem_mos_window_request(
        STATION, dt.date(2026, 8, 25), dt.date(2026, 9, 21), MODEL
    )
    _commit(cache, year, payloads, _mos_csv("2026-09-10 12:00:00"))
    _commit(cache, window, payloads, _mos_csv("2026-09-10 12:00:00"))

    coverage = resolve_mos_coverage(
        cache,
        station=STATION,
        start=dt.date(2026, 9, 10),
        end=dt.date(2026, 9, 11),
        model=MODEL,
    )

    # ONE entry answers the day -- never both, or the day is weighted twice.
    assert len(coverage.requests()) == 1
    day = dt.date(2026, 9, 10)
    owners = [r for r in coverage.requests() if day in coverage.days_for(r)]
    assert len(owners) == 1
    # And the read path yields that day's rows from exactly one payload.
    yielded = list(read_mos_windows(cache, coverage))
    assert len(yielded) == 1
    assert [days for _body, days in yielded] == [frozenset({day})]


def test_a_day_covered_by_no_entry_raises_and_names_the_days(tmp_path: Path) -> None:
    from forecast_conditional_corpus import MosCoverageGapError, resolve_mos_coverage

    from breezy.persistence.archive_request import iem_mos_window_request

    payloads: dict[str, bytes] = {}
    cache = _cache(tmp_path, payloads)
    window = iem_mos_window_request(
        STATION, dt.date(2026, 8, 25), dt.date(2026, 9, 3), MODEL
    )
    _commit(cache, window, payloads, _mos_csv("2026-09-01 12:00:00"))

    with pytest.raises(MosCoverageGapError) as excinfo:
        resolve_mos_coverage(
            cache,
            station=STATION,
            start=dt.date(2026, 9, 1),
            end=dt.date(2026, 9, 6),
            model=MODEL,
        )

    error = excinfo.value
    assert error.missing_days == (
        dt.date(2026, 9, 3),
        dt.date(2026, 9, 4),
        dt.date(2026, 9, 5),
    )
    assert "2026-09-03" in str(error)
    # The partial coverage rides on the exception so a caller that must report
    # rather than abort (the screen, under §4) can do so with the gap NAMED.
    assert error.coverage.requests() == (window,)
