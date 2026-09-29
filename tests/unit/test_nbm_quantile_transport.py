"""SL-3: the NBM NBP quantile bulletin transport.

No test here opens a real socket: every exchange is a `respx` fixture (the
same mechanism `test_nbm_forecast_transport.py` uses), and the suite runs
egress-blocked (`tests/conftest.py` blocks `socket.socket.connect` for every
test not marked `live`/`venue_live`/`real_money`/`allow_socket`).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import httpx
import pytest
import respx

from breezy.ingest.http import DisallowedHostError, OversizeBodyError, ServerError
from breezy.ingest.nbm_quantile_transport import (
    DEFAULT_NBM_QUANTILE_MAX_BODY_BYTES,
    DEFAULT_NBM_QUANTILE_STATIONS,
    NBM_QUANTILE_ALLOWED_HOSTS,
    NOMADS_QUANTILE_HOST,
    S3_QUANTILE_HOST,
    BothHostsFailedError,
    NbmQuantileTransport,
    build_nbm_quantile_transport,
)

CYCLE_DATE = dt.date(2026, 9, 28)
CYCLE_HOUR = 13

S3_URL = f"https://{S3_QUANTILE_HOST}/blend.20260928/13/text/blend_nbptx.t13z"
NOMADS_URL = (
    f"https://{NOMADS_QUANTILE_HOST}/pub/data/nccf/com/blend/prod/"
    "blend.20260928/13/text/blend_nbptx.t13z"
)


def _clock() -> int:
    return 1_789_000_000_000_000_000


def _transport(**kwargs: object) -> NbmQuantileTransport:
    return NbmQuantileTransport(clock=_clock, check_proxy_env=False, **kwargs)  # type: ignore[arg-type]


def _station_block(station: str, *, lines: int = 3) -> str:
    header = f"{station}    NBM V5.0 NBP GUIDANCE    9/28/2026  1300 UTC\n"
    body = "".join(f" ROW{i}  1|  2   3|  4\n" for i in range(lines))
    return header + body


# ---------------------------------------------------------------------------
# The host allowlist, and only the host allowlist
# ---------------------------------------------------------------------------


def test_the_allowlist_is_exactly_s3_and_nomads() -> None:
    assert NBM_QUANTILE_ALLOWED_HOSTS == frozenset({S3_QUANTILE_HOST, NOMADS_QUANTILE_HOST})
    assert _transport()._allowed_hosts == NBM_QUANTILE_ALLOWED_HOSTS


def test_another_allowlist_cannot_be_injected() -> None:
    with pytest.raises(ValueError, match="NBM_QUANTILE_ALLOWED_HOSTS"):
        _transport(allowed_hosts=frozenset({"api.weather.gov"}))


def test_stations_must_not_be_empty() -> None:
    with pytest.raises(ValueError, match="stations"):
        _transport(stations=frozenset())


# ---------------------------------------------------------------------------
# GET only
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_only_a_get_request_is_ever_sent() -> None:
    body = "PREAMBLE\n" + _station_block("KLAX")
    route = respx.get(S3_URL).mock(return_value=httpx.Response(200, text=body))

    await _transport(stations=frozenset({"KLAX"})).fetch_nbp_bulletin(
        cycle_date=CYCLE_DATE, cycle_hour=CYCLE_HOUR
    )

    assert route.call_count == 1
    assert route.calls[0].request.method == "GET"


# ---------------------------------------------------------------------------
# A non-allowlisted host is refused before any request reaches the wire
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_an_off_allowlist_origin_is_refused() -> None:
    rogue = _transport(s3_base_url="https://evil.example", nomads_base_url="https://evil.example")
    with pytest.raises(DisallowedHostError):
        await rogue.fetch_nbp_bulletin(cycle_date=CYCLE_DATE, cycle_hour=CYCLE_HOUR)


# ---------------------------------------------------------------------------
# Streaming filter: header preamble + only the configured stations
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_the_filter_keeps_the_preamble_and_only_wanted_stations() -> None:
    body = (
        "PREAMBLE LINE 1\nPREAMBLE LINE 2\n"
        + _station_block("KLAX")
        + _station_block("KMDW")
        + _station_block("KZZZ")
    )
    respx.get(S3_URL).mock(return_value=httpx.Response(200, text=body))

    result = await _transport(stations=frozenset({"KLAX", "KMDW"})).fetch_nbp_bulletin(
        cycle_date=CYCLE_DATE, cycle_hour=CYCLE_HOUR
    )

    assert "PREAMBLE LINE 1" in result.text
    assert "PREAMBLE LINE 2" in result.text
    assert "KLAX" in result.text
    assert "KMDW" in result.text
    assert "KZZZ" not in result.text
    assert result.raw_bytes == len(body.encode("utf-8"))


@respx.mock
@pytest.mark.asyncio
async def test_a_station_not_in_the_bulletin_yields_no_block_but_keeps_the_preamble() -> None:
    body = "PREAMBLE\n" + _station_block("KZZZ")
    respx.get(S3_URL).mock(return_value=httpx.Response(200, text=body))

    result = await _transport(stations=frozenset({"KLAX"})).fetch_nbp_bulletin(
        cycle_date=CYCLE_DATE, cycle_hour=CYCLE_HOUR
    )

    assert "PREAMBLE" in result.text
    assert "KZZZ" not in result.text
    assert "KLAX" not in result.text


# ---------------------------------------------------------------------------
# Bounded memory (L-53): a large synthetic stream keeps peak memory well
# below the stream size, because only the wanted blocks are ever retained.
# ---------------------------------------------------------------------------


def test_the_block_filter_itself_discards_unwanted_lines_without_retaining_them() -> None:
    """Deterministic, I/O-free proof of L-53: retained state never grows with
    the number of UNWANTED lines fed, only with wanted content.

    `respx`'s own mock transport pre-buffers the whole response body before
    this transport ever sees it (a property of the test double, not of a
    real socket), which makes an end-to-end `tracemalloc` peak dominated by
    that fixture overhead rather than by this code. This test isolates the
    one component actually responsible for the memory bound.
    """
    from breezy.ingest.nbm_quantile_transport import _StationBlockFilter

    small_filter = _StationBlockFilter(frozenset({"KLAX"}))
    for line in _station_block("KLAX").splitlines(keepends=True):
        small_filter.feed_line(line)
    small_kept_chars = len(small_filter.text())

    large_filter = _StationBlockFilter(frozenset({"KLAX"}))
    for n in range(20_000):
        for line in _station_block(f"K{n:05d}", lines=20).splitlines(keepends=True):
            large_filter.feed_line(line)
    for line in _station_block("KLAX").splitlines(keepends=True):
        large_filter.feed_line(line)
    large_kept_chars = len(large_filter.text())

    # 20,000 unwanted station blocks were fed to `large_filter` and NONE
    # reached `_kept`: the retained text is the SAME regardless of how much
    # unwanted content streamed past.
    assert large_kept_chars == small_kept_chars


@respx.mock
@pytest.mark.asyncio
async def test_the_filtered_result_is_a_tiny_fraction_of_a_large_stream() -> None:
    unwanted_blocks = "".join(_station_block(f"K{n:04d}", lines=150) for n in range(2000))
    body = "PREAMBLE\n" + unwanted_blocks + _station_block("KLAX") + _station_block("KMDW")
    stream_size = len(body.encode("utf-8"))
    assert stream_size > 5_000_000, "the synthetic stream must be large to be a meaningful test"
    respx.get(S3_URL).mock(return_value=httpx.Response(200, text=body))

    result = await _transport(stations=frozenset({"KLAX", "KMDW"})).fetch_nbp_bulletin(
        cycle_date=CYCLE_DATE, cycle_hour=CYCLE_HOUR
    )

    filtered_size = len(result.text.encode("utf-8"))
    # The filtered text is a tiny fraction of the stream: only 2 of 2002
    # blocks plus the preamble survive.
    assert filtered_size < stream_size / 20
    assert result.raw_bytes == stream_size


# ---------------------------------------------------------------------------
# AWS primary -> NOMADS fallback
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_aws_failure_falls_back_to_nomads() -> None:
    body = "PREAMBLE\n" + _station_block("KLAX")
    respx.get(S3_URL).mock(return_value=httpx.Response(500, text="server error"))
    nomads_route = respx.get(NOMADS_URL).mock(return_value=httpx.Response(200, text=body))

    result = await _transport(stations=frozenset({"KLAX"})).fetch_nbp_bulletin(
        cycle_date=CYCLE_DATE, cycle_hour=CYCLE_HOUR
    )

    assert nomads_route.call_count == 1
    assert result.source_host == NOMADS_QUANTILE_HOST
    assert "KLAX" in result.text


@respx.mock
@pytest.mark.asyncio
async def test_both_hosts_failing_raises_both_hosts_failed() -> None:
    respx.get(S3_URL).mock(return_value=httpx.Response(500, text="server error"))
    respx.get(NOMADS_URL).mock(return_value=httpx.Response(500, text="server error"))

    with pytest.raises(BothHostsFailedError) as excinfo:
        await _transport(stations=frozenset({"KLAX"})).fetch_nbp_bulletin(
            cycle_date=CYCLE_DATE, cycle_hour=CYCLE_HOUR
        )

    assert isinstance(excinfo.value.primary_error, ServerError)
    assert isinstance(excinfo.value.fallback_error, ServerError)


@respx.mock
@pytest.mark.asyncio
async def test_a_successful_aws_fetch_never_calls_nomads() -> None:
    body = "PREAMBLE\n" + _station_block("KLAX")
    respx.get(S3_URL).mock(return_value=httpx.Response(200, text=body))
    nomads_route = respx.get(NOMADS_URL).mock(return_value=httpx.Response(200, text=body))

    result = await _transport(stations=frozenset({"KLAX"})).fetch_nbp_bulletin(
        cycle_date=CYCLE_DATE, cycle_hour=CYCLE_HOUR
    )

    assert nomads_route.call_count == 0
    assert result.source_host == S3_QUANTILE_HOST


# ---------------------------------------------------------------------------
# Last-Modified is captured
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_last_modified_is_captured() -> None:
    body = "PREAMBLE\n" + _station_block("KLAX")
    respx.get(S3_URL).mock(
        return_value=httpx.Response(
            200, text=body, headers={"Last-Modified": "Mon, 28 Sep 2026 14:03:18 GMT"}
        )
    )

    result = await _transport(stations=frozenset({"KLAX"})).fetch_nbp_bulletin(
        cycle_date=CYCLE_DATE, cycle_hour=CYCLE_HOUR
    )

    assert result.last_modified == "Mon, 28 Sep 2026 14:03:18 GMT"
    assert result.fetched_at_ns == _clock()


@respx.mock
@pytest.mark.asyncio
async def test_missing_last_modified_is_none_not_a_default() -> None:
    body = "PREAMBLE\n" + _station_block("KLAX")
    respx.get(S3_URL).mock(return_value=httpx.Response(200, text=body))

    result = await _transport(stations=frozenset({"KLAX"})).fetch_nbp_bulletin(
        cycle_date=CYCLE_DATE, cycle_hour=CYCLE_HOUR
    )

    assert result.last_modified is None


# ---------------------------------------------------------------------------
# The sha256 covers the FULL raw stream, not the filtered text
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_sha256_covers_the_full_raw_stream_not_the_filtered_text() -> None:
    import hashlib

    body = "PREAMBLE\n" + _station_block("KLAX") + _station_block("KZZZ")
    respx.get(S3_URL).mock(return_value=httpx.Response(200, text=body))

    result = await _transport(stations=frozenset({"KLAX"})).fetch_nbp_bulletin(
        cycle_date=CYCLE_DATE, cycle_hour=CYCLE_HOUR
    )

    assert result.raw_sha256 == hashlib.sha256(body.encode("utf-8")).hexdigest()
    assert result.raw_sha256 != hashlib.sha256(result.text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# The body cap is enforced during streaming
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_the_body_cap_is_enforced_per_instance() -> None:
    body = "PREAMBLE\n" + _station_block("KLAX", lines=200)
    respx.get(S3_URL).mock(return_value=httpx.Response(200, text=body))
    respx.get(NOMADS_URL).mock(return_value=httpx.Response(200, text=body))

    transport = _transport(stations=frozenset({"KLAX"}), max_body_bytes=1024)
    with pytest.raises(BothHostsFailedError) as excinfo:
        await transport.fetch_nbp_bulletin(cycle_date=CYCLE_DATE, cycle_hour=CYCLE_HOUR)

    assert isinstance(excinfo.value.primary_error, OversizeBodyError)


def test_the_default_body_cap_clears_the_measured_bulletin_size() -> None:
    """The live 2026-09-28 13Z cycle measured 34,714,882 bytes."""
    assert DEFAULT_NBM_QUANTILE_MAX_BODY_BYTES >= 48 * 1024 * 1024


# ---------------------------------------------------------------------------
# Cycle-argument validation (before any socket opens)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("hour", [-1, 24, 99])
@pytest.mark.asyncio
async def test_a_cycle_hour_outside_the_day_is_refused_before_a_socket_opens(hour: int) -> None:
    with pytest.raises(ValueError):
        await _transport().fetch_nbp_bulletin(cycle_date=CYCLE_DATE, cycle_hour=hour)


@pytest.mark.asyncio
async def test_a_non_int_cycle_hour_is_refused() -> None:
    with pytest.raises(TypeError):
        await _transport().fetch_nbp_bulletin(cycle_date=CYCLE_DATE, cycle_hour=True)


@pytest.mark.asyncio
async def test_a_non_date_cycle_is_refused() -> None:
    # Deliberately the wrong runtime type, to exercise the transport's own
    # `isinstance` check. Typed `Any` here (never `# type: ignore`) so mypy
    # does not flag the call: this variable's whole PURPOSE is to carry a
    # value the static signature forbids, straight into a runtime check.
    bad_cycle_date: Any = "2026-09-28"
    with pytest.raises(TypeError):
        await _transport().fetch_nbp_bulletin(cycle_date=bad_cycle_date, cycle_hour=CYCLE_HOUR)


# ---------------------------------------------------------------------------
# The production default builds, without any network call (L-55)
# ---------------------------------------------------------------------------


def test_the_production_transport_factory_builds_without_network_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BREEZY_USER_AGENT", "breezy-test (contact@example.com)")

    transport = build_nbm_quantile_transport(_clock, check_proxy_env=False)

    assert transport._allowed_hosts == NBM_QUANTILE_ALLOWED_HOSTS
    assert transport._s3_base_url.startswith(f"https://{S3_QUANTILE_HOST}")
    assert transport._nomads_base_url.startswith(f"https://{NOMADS_QUANTILE_HOST}")
    assert transport._stations == DEFAULT_NBM_QUANTILE_STATIONS


# ---------------------------------------------------------------------------
# No egress: this whole module's tests run with sockets blocked by
# `tests/conftest.py`'s autouse fixture; `respx` intercepts httpx below the
# socket layer, so no test above ever needs `allow_socket`/`live`.
# ---------------------------------------------------------------------------


def test_this_test_module_carries_no_live_egress_marker() -> None:
    import ast
    from pathlib import Path

    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    marker_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in {
            "live",
            "venue_live",
            "real_money",
            "allow_socket",
        }:
            marker_names.add(node.attr)
    assert marker_names == set()
