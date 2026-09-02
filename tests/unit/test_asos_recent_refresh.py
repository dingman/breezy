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
