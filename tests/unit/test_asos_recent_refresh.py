"""Unit tests for `scripts/analysis/asos_recent_refresh.py` (Item 4).

The offer-gate scan is CACHE-ONLY and ZERO-NETWORK by construction (its own
module docstring); this refresh runs as a SEPARATE step, ahead of the scan,
from the systemd timer where network is available. Every test here injects a
FAKE `HistoricalDataClient` (the same narrow `Protocol` already defined in
`settlement_alignment_study.py` for exactly this purpose) -- no real network
access, ever, in this suite.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts/analysis").as_posix())

from asos_recent_refresh import (
    RefreshReport,
    _fetch_text_paced_with_retry,
    _InterRequestPacer,
    _retry_wait_seconds,
    _RetryWaitBudget,
    lookback_days_since,
    refresh_recent_asos,
    refresh_window,
)
from settlement_alignment_study import load_sites

_LAX_SPEC = next(spec for spec in load_sites() if spec.city == "LAX")
_SFO_SPEC = next(spec for spec in load_sites() if spec.city == "SFO")


class _FakeClient:
    """A `HistoricalDataClient` double: canned responses or a raised error,
    keyed by URL substring so a test can target one site without the other.
    """

    def __init__(
        self,
        *,
        responses: dict[str, str] | None = None,
        raises_for: frozenset[str] = frozenset(),
    ) -> None:
        self._responses = responses or {}
        self._raises_for = raises_for

    def get(self, url: str, *, timeout: float) -> httpx.Response:
        for needle in self._raises_for:
            if needle in url:
                raise httpx.ConnectTimeout(f"synthetic timeout for {needle}")
        for needle, text in self._responses.items():
            if needle in url:
                return httpx.Response(200, text=text, request=httpx.Request("GET", url))
        return httpx.Response(200, text="", request=httpx.Request("GET", url))


_ASOS_CSV = (
    "station,valid,metar\n"
    "LAX,2026-09-02 00:51,KLAX 020051Z AUTO 10SM CLR 22/13 A2993 RMK T02200130 MADISHF\n"
)


# ---------------------------------------------------------------------------
# refresh_window -- pure
# ---------------------------------------------------------------------------


def test_refresh_window_spans_lookback_days_through_today() -> None:
    start, end = refresh_window(today=dt.date(2026, 9, 2), lookback_days=3)
    assert start == dt.date(2026, 8, 30)
    assert end == dt.date(2026, 9, 2)


def test_refresh_window_rejects_a_negative_lookback() -> None:
    with pytest.raises(ValueError, match="lookback_days"):
        refresh_window(today=dt.date(2026, 9, 2), lookback_days=-1)


# ---------------------------------------------------------------------------
# refresh_recent_asos -- the soft-fail orchestration
# ---------------------------------------------------------------------------


def test_refresh_recent_asos_records_fetched_for_a_real_response(tmp_path: Path) -> None:
    client = _FakeClient(responses={"LAX": _ASOS_CSV})
    report = refresh_recent_asos(
        client=client,
        cache_dir=tmp_path,
        sites=(_LAX_SPEC,),
        today=dt.date(2026, 9, 2),
        lookback_days=3,
    )
    assert len(report.results) == 1
    result = report.results[0]
    assert result.city == "LAX"
    assert result.outcome == "FETCHED"
    assert result.rows_found == 1
    assert report.any_shortfall is False


def test_refresh_recent_asos_fails_soft_on_a_network_error(tmp_path: Path) -> None:
    """L-8's discipline: a failed fetch is REPORTED, never raised, so the
    scan can still run on whatever is already cached.
    """
    client = _FakeClient(raises_for=frozenset({"LAX"}))
    report = refresh_recent_asos(
        client=client,
        cache_dir=tmp_path,
        sites=(_LAX_SPEC,),
        today=dt.date(2026, 9, 2),
        lookback_days=3,
    )
    result = report.results[0]
    assert result.outcome == "FETCH_FAILED"
    assert result.rows_found == 0
    assert result.detail is not None
    assert report.any_shortfall is True


def test_refresh_recent_asos_treats_an_empty_response_as_a_named_shortfall() -> None:
    """A 0-row fetch is not silently a success (L-8: a 0-row read is not a
    quiet market until verified) -- it is its own distinct, reported state.
    """
    client = _FakeClient(responses={"LAX": ""})
    report = refresh_recent_asos(
        client=client,
        cache_dir=Path("/tmp/does-not-need-to-exist-for-this-test"),
        sites=(_LAX_SPEC,),
        today=dt.date(2026, 9, 2),
        lookback_days=3,
    )
    result = report.results[0]
    assert result.outcome == "EMPTY_RESPONSE"
    assert result.rows_found == 0
    assert report.any_shortfall is True


def test_refresh_recent_asos_one_sites_failure_does_not_block_another(tmp_path: Path) -> None:
    """A network error for one station must never abort the whole refresh --
    every other site still gets its own fetch attempt.
    """
    client = _FakeClient(raises_for=frozenset({"LAX"}), responses={"SFO": _ASOS_CSV})
    report = refresh_recent_asos(
        client=client,
        cache_dir=tmp_path,
        sites=(_LAX_SPEC, _SFO_SPEC),
        today=dt.date(2026, 9, 2),
        lookback_days=3,
    )
    outcomes = {r.city: r.outcome for r in report.results}
    assert outcomes["LAX"] == "FETCH_FAILED"
    assert outcomes["SFO"] == "FETCHED"


def test_refresh_recent_asos_writes_into_the_cache_dir_the_scan_reads(tmp_path: Path) -> None:
    """The whole point: after a successful refresh, the SAME cache directory
    `load_recent_asos_rows` scans now holds the new `.txt` file.
    """
    client = _FakeClient(responses={"LAX": _ASOS_CSV})
    refresh_recent_asos(
        client=client,
        cache_dir=tmp_path,
        sites=(_LAX_SPEC,),
        today=dt.date(2026, 9, 2),
        lookback_days=3,
    )
    assert list(tmp_path.glob("*.txt")), "expected fetch_text_cached to write a cache file"


def test_refresh_report_generated_at_is_recorded() -> None:
    client = _FakeClient(responses={"LAX": _ASOS_CSV})
    report = refresh_recent_asos(
        client=client,
        cache_dir=Path("/tmp/unused-for-this-assertion"),
        sites=(_LAX_SPEC,),
        today=dt.date(2026, 9, 2),
        lookback_days=3,
    )
    assert isinstance(report, RefreshReport)
    assert report.generated_at.tzinfo is not None


def test_refresh_recent_asos_is_empty_for_no_sites(tmp_path: Path) -> None:
    client = _FakeClient()
    report = refresh_recent_asos(
        client=client, cache_dir=tmp_path, sites=(), today=dt.date(2026, 9, 2), lookback_days=3
    )
    assert report.results == ()
    assert report.any_shortfall is False


# ---------------------------------------------------------------------------
# lookback_days_since -- pure. Backs `--since`, an absolute-anchor alternative
# to `--lookback-days` that does not drift a day further from the anchor
# every day this unit runs (see ma_prelock_winner_ask_study.py:ASOS_FETCH_START).
# ---------------------------------------------------------------------------


def test_lookback_days_since_spans_from_since_to_today() -> None:
    assert (
        lookback_days_since(today=dt.date(2026, 9, 5), since=dt.date(2026, 8, 30)) == 6
    )


def test_lookback_days_since_is_zero_when_since_is_today() -> None:
    assert lookback_days_since(today=dt.date(2026, 9, 2), since=dt.date(2026, 9, 2)) == 0


def test_lookback_days_since_rejects_since_after_today() -> None:
    with pytest.raises(ValueError, match="since"):
        lookback_days_since(today=dt.date(2026, 8, 30), since=dt.date(2026, 9, 5))


def test_parse_args_since_defaults_to_none_and_parses_an_iso_date() -> None:
    from asos_recent_refresh import _parse_args

    assert _parse_args([]).since is None
    assert _parse_args(["--since", "2026-08-30"]).since == dt.date(2026, 8, 30)


# ---------------------------------------------------------------------------
# 429/5xx pacing and bounded retry (production evidence 2026-09-22..09-24:
# NYC fetched, SFO/MIA/MDW/LAX then each got a 429 back-to-back with ZERO
# spacing). `fetch_text_cached` itself is never modified -- this file's
# fakes hit only `refresh_recent_asos`'s own retry/pacing wrapper.
# ---------------------------------------------------------------------------


def _status_error(status_code: int, *, retry_after: str | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://example.invalid/asos.txt")
    headers = {"Retry-After": retry_after} if retry_after is not None else {}
    response = httpx.Response(status_code, request=request, headers=headers)
    return httpx.HTTPStatusError(str(status_code), request=request, response=response)


class _SequencedPerStationClient:
    """A `HistoricalDataClient` double keyed by URL substring (station ICAO
    id, e.g. ``SFO``): successive ``get`` calls matching a needle replay its
    own queue of ``(status_code, retry_after)`` pairs in order. A ``200``
    entry returns ``body``. A needle with an empty (or absent) queue answers
    a plain ``200`` with an empty body, matching ``_FakeClient``'s own
    default -- so tests only need to name the stations they care about.
    """

    def __init__(
        self,
        queues: dict[str, list[tuple[int, str | None]]],
        *,
        body: str = _ASOS_CSV,
    ) -> None:
        self._queues = {needle: list(seq) for needle, seq in queues.items()}
        self._body = body
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: float) -> httpx.Response:
        self.calls.append(url)
        request = httpx.Request("GET", url)
        for needle, queue in self._queues.items():
            if needle in url and queue:
                status_code, retry_after = queue.pop(0)
                if status_code == 200:
                    return httpx.Response(200, request=request, text=self._body)
                headers = {"Retry-After": retry_after} if retry_after is not None else {}
                return httpx.Response(status_code, request=request, headers=headers)
        return httpx.Response(200, request=request, text="")


def test_retry_wait_seconds_honours_retry_after_seconds_form_capped_at_60() -> None:
    exc = _status_error(429, retry_after="500")
    assert _retry_wait_seconds(exc, attempt=0) == 60.0


def test_retry_wait_seconds_honours_a_small_retry_after_uncapped() -> None:
    exc = _status_error(429, retry_after="30")
    assert _retry_wait_seconds(exc, attempt=0) == 30.0


def test_retry_wait_seconds_falls_back_to_exponential_backoff_without_retry_after() -> None:
    exc = _status_error(503)
    assert [_retry_wait_seconds(exc, attempt=n) for n in range(3)] == [5.0, 15.0, 45.0]


def test_second_station_429_then_200_recovers_after_one_retry(tmp_path: Path) -> None:
    """LAX (first) succeeds outright; SFO (second) gets one 429 then a 200
    on retry -- the fix for the production shortfall (which had no retry at
    all).
    """
    client = _SequencedPerStationClient(
        {"LAX": [(200, None)], "SFO": [(429, "3"), (200, None)]}
    )
    sleeps: list[float] = []

    report = refresh_recent_asos(
        client=client,
        cache_dir=tmp_path,
        sites=(_LAX_SPEC, _SFO_SPEC),
        today=dt.date(2026, 9, 2),
        lookback_days=3,
        delay_s=0.0,
        sleep=sleeps.append,
        monotonic=lambda: 0.0,
    )

    outcomes = {r.city: r.outcome for r in report.results}
    assert outcomes == {"LAX": "FETCHED", "SFO": "FETCHED"}
    assert report.any_shortfall is False
    # Retry-After=3 is well under the 60s cap, so it is honoured as-is.
    assert sleeps == [3.0]


def test_retry_after_is_honoured_and_capped_at_the_ceiling(tmp_path: Path) -> None:
    client = _SequencedPerStationClient({"SFO": [(429, "500"), (200, None)]})
    sleeps: list[float] = []

    report = refresh_recent_asos(
        client=client,
        cache_dir=tmp_path,
        sites=(_SFO_SPEC,),
        today=dt.date(2026, 9, 2),
        lookback_days=3,
        delay_s=0.0,
        sleep=sleeps.append,
        monotonic=lambda: 0.0,
    )

    assert report.results[0].outcome == "FETCHED"
    # Retry-After=500 is capped at the 60s ceiling, never used raw.
    assert sleeps == [60.0]


def test_wall_cap_stops_retrying_once_the_shared_budget_is_exhausted(tmp_path: Path) -> None:
    """A small, injected `retry_wait_budget_s` is a hard ceiling on the SUM
    of every wait across every station -- once it cannot cover the next
    wait, retrying stops immediately rather than waiting a truncated amount,
    and the station becomes an ordinary `FETCH_FAILED`.
    """
    client = _SequencedPerStationClient({"SFO": [(429, "50"), (429, "50"), (200, None)]})
    sleeps: list[float] = []

    report = refresh_recent_asos(
        client=client,
        cache_dir=tmp_path,
        sites=(_SFO_SPEC,),
        today=dt.date(2026, 9, 2),
        lookback_days=3,
        delay_s=0.0,
        sleep=sleeps.append,
        monotonic=lambda: 0.0,
        retry_wait_budget_s=60.0,
    )

    result = report.results[0]
    assert result.outcome == "FETCH_FAILED"
    # First wait (50s) fits in the 60s budget (10s left); the second wait
    # (also 50s) does not, so the retry is refused and the station fails
    # without ever reaching the 200 queued behind it.
    assert sleeps == [50.0]
    assert len(client.calls) == 2


def test_pacing_enforces_the_minimum_interval_between_station_requests(
    tmp_path: Path,
) -> None:
    """Every actual GET attempt is preceded by at least `delay_s` since the
    previous attempt -- charged whether or not the previous attempt
    succeeded, unlike `fetch_text_cached`'s own post-SUCCESS-only sleep
    (the exact production gap: a 429 skipped it entirely).
    """
    client = _SequencedPerStationClient({"LAX": [(200, None)], "SFO": [(200, None)]})
    clock = [100.0]

    def monotonic() -> float:
        return clock[0]

    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    report = refresh_recent_asos(
        client=client,
        cache_dir=tmp_path,
        sites=(_LAX_SPEC, _SFO_SPEC),
        today=dt.date(2026, 9, 2),
        lookback_days=3,
        delay_s=1.0,
        sleep=sleep,
        monotonic=monotonic,
    )

    assert [r.outcome for r in report.results] == ["FETCHED", "FETCHED"]
    assert sleeps == [1.0]


def test_pacing_tops_up_a_retry_backoff_that_is_shorter_than_its_own_floor(
    tmp_path: Path,
) -> None:
    """The pacer fires before EVERY attempt, including a retry right after
    a 429 -- so if its own minimum interval is LARGER than the retry
    backoff that already elapsed, it tops up the wait rather than skipping
    it (the exact production gap: `fetch_text_cached`'s post-SUCCESS-only
    sleep is skipped by a 429 entirely, never merely topped up).
    """
    client = _SequencedPerStationClient({"SFO": [(429, None), (200, None)]})
    clock = [0.0]

    def monotonic() -> float:
        return clock[0]

    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        clock[0] += seconds

    budget = _RetryWaitBudget(remaining_s=300.0)
    pacer = _InterRequestPacer(min_interval_s=10.0, monotonic=monotonic, sleep=sleep)

    text = _fetch_text_paced_with_retry(
        client, tmp_path, "https://example.invalid/?station=SFO",
        pacer=pacer, sleep=sleep, budget=budget,
    )

    assert text == _ASOS_CSV
    # attempt 1's own 5.0s backoff wait, then the pacer tops the elapsed
    # time up to its 10.0s floor before attempt 2 fires.
    assert waits == [5.0, 5.0]


def test_persistent_429_gives_fetch_failed_with_a_reported_shortfall(tmp_path: Path) -> None:
    """A station still failing after every retry is exhausted stays
    `FETCH_FAILED`, and the run's `any_shortfall` flag -- the signal
    `main()` prints loudly and the separate freshness check (already tested
    in `test_asos_cache_freshness_check.py`) alerts on independently -- is
    set.
    """
    client = _SequencedPerStationClient({"SFO": [(429, None)] * 10})
    sleeps: list[float] = []

    report = refresh_recent_asos(
        client=client,
        cache_dir=tmp_path,
        sites=(_SFO_SPEC,),
        today=dt.date(2026, 9, 2),
        lookback_days=3,
        delay_s=0.0,
        sleep=sleeps.append,
        monotonic=lambda: 0.0,
    )

    result = report.results[0]
    assert result.outcome == "FETCH_FAILED"
    assert "429" in (result.detail or "")
    assert report.any_shortfall is True
    # 1 initial attempt + 3 retries = 4 calls; 3 waits (5, 15, 45).
    assert len(client.calls) == 4
    assert sleeps == [5.0, 15.0, 45.0]
