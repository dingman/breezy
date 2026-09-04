"""Unit tests for `breezy.ingest.nws_observation_transport` -- BL-24 Seam B, section 2.

`NwsObservationTransport` subclasses the hardened settlement transport and
adds ONE path builder. Everything that hardens a request -- allowlist, TLS
floor, no redirects, body cap, digest-before-decode, receipt stamp -- is
inherited by IDENTITY (converged review item 5), and the settlement product
methods are CLOSED on it (L-22: exclusion is unforgeable, not offered).

`respx` intercepts `httpx` at the transport layer (as a context-managed
router, the idiom `test_ingest_nws_actor.py` uses); no socket opens.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import httpx
import pytest
import respx

from breezy.ingest import http as http_module
from breezy.ingest import nws_observation_transport as transport_module
from breezy.ingest.http import DisallowedHostError, HttpTransport, RateLimitedError
from breezy.ingest.nws_observation_transport import (
    DEFAULT_OBSERVATION_MAX_BODY_BYTES,
    MAX_OBSERVATION_LIMIT,
    OBSERVATION_ACCEPT,
    InvalidObservationLimitError,
    NwsObservationTransport,
    UnregisteredStationError,
)

UA = "breezy-test/1.0 (+mailto:ops@example.invalid)"
_NOW_NS = 1_788_489_297_658_387_295
_EMPTY = httpx.Response(200, json={"features": []})


def _clock() -> int:
    return _NOW_NS


def _transport(**overrides: object) -> NwsObservationTransport:
    kwargs: dict[str, object] = {"clock": _clock, "user_agent": UA, "check_proxy_env": False}
    kwargs.update(overrides)
    return NwsObservationTransport(**kwargs)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_the_settlement_fetch_methods_are_closed_on_the_observation_transport() -> None:
    transport = _transport()
    with pytest.raises(NotImplementedError):
        await transport.fetch_discovery_list("MDW")
    with pytest.raises(NotImplementedError):
        await transport.fetch_product("00000000-0000-0000-0000-000000000000")


def test_the_settlement_transport_has_no_observation_method() -> None:
    """The settlement `HttpTransport` never gains the method -- L-22."""
    assert not hasattr(HttpTransport, "fetch_station_observations")
    assert "fetch_station_observations" not in inspect.getsource(http_module)


@pytest.mark.asyncio
async def test_a_host_other_than_api_weather_gov_is_refused_before_the_socket_opens() -> None:
    transport = _transport(base_url="https://api.example.invalid")
    with respx.mock(assert_all_called=False) as router:
        route = router.get("https://api.example.invalid/stations/KMDW/observations").mock(
            return_value=_EMPTY
        )
        with pytest.raises(DisallowedHostError):
            await transport.fetch_station_observations("KMDW", limit=5)
        assert not route.called


@pytest.mark.asyncio
@pytest.mark.parametrize("icao", ["KORD", "KJFK", "KPHI"])
async def test_an_unregistered_icao_is_refused_before_the_socket_opens(icao: str) -> None:
    """Shape passes; membership in the registry's closed ICAO set does not."""
    with respx.mock(assert_all_called=False) as router:
        route = router.get(url__startswith="https://api.weather.gov/").mock(return_value=_EMPTY)
        with pytest.raises(UnregisteredStationError):
            await _transport().fetch_station_observations(icao, limit=5)
        assert not route.called


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "icao", ["kmdw", "KMDW/", "../KMDW", "KMDW?limit=1", "K MDW", "KMD", "KMDWX", ""]
)
async def test_a_malformed_icao_is_refused_before_the_socket_opens(icao: str) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(url__startswith="https://api.weather.gov/").mock(return_value=_EMPTY)
        with pytest.raises(ValueError):
            await _transport().fetch_station_observations(icao, limit=5)
        assert not route.called


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1, MAX_OBSERVATION_LIMIT + 1, "50", 5.0, True])
async def test_the_limit_is_a_builder_formatted_int_within_bounds(limit: object) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.get(url__startswith="https://api.weather.gov/").mock(return_value=_EMPTY)
        with pytest.raises(InvalidObservationLimitError):
            await _transport().fetch_station_observations("KMDW", limit=limit)  # type: ignore[arg-type]
        assert not route.called


@pytest.mark.asyncio
async def test_a_registered_icao_fetches_exactly_the_documented_url() -> None:
    with respx.mock as router:
        route = router.get("https://api.weather.gov/stations/KMDW/observations?limit=500").mock(
            return_value=_EMPTY
        )
        result = await _transport().fetch_station_observations("KMDW", limit=500)

    assert route.call_count == 1
    request = route.calls[0].request
    assert request.method == "GET"
    assert str(request.url) == "https://api.weather.gov/stations/KMDW/observations?limit=500"
    assert request.headers["Accept"] == OBSERVATION_ACCEPT
    assert request.headers["User-Agent"] == UA
    assert "If-None-Match" not in request.headers
    assert "If-Modified-Since" not in request.headers
    assert result.retrieved_at_ns == _NOW_NS
    assert result.status_code == 200


@pytest.mark.asyncio
async def test_a_429_surfaces_as_the_existing_rate_limited_error() -> None:
    with respx.mock as router:
        router.get(url__startswith="https://api.weather.gov/").mock(
            return_value=httpx.Response(429, headers={"Retry-After": "30"})
        )
        with pytest.raises(RateLimitedError):
            await _transport().fetch_station_observations("KMDW", limit=1)


def test_the_body_cap_covers_a_full_500_row_response() -> None:
    """The recorded KMDW fixture (newest 300 rows of a full 500-row response,
    trimmed to keep the test suite small -- see `test_nws_observations_parse.py`
    module docstring) is still well over the 128 KiB settlement default."""
    fixture = Path(__file__).resolve().parents[1] / "fixtures" / "nws"
    size = (fixture / "kmdw_observations_2026-09-04.json").stat().st_size
    assert size > http_module.DEFAULT_MAX_BODY_BYTES
    assert DEFAULT_OBSERVATION_MAX_BODY_BYTES > size


_INHERITED_METHODS = (
    "_fetch",
    "_validate_url",
    "_build_client",
    "_raise_for_status",
    "_read_capped_body",
    "_reject_unexpected_content_encoding",
    "_not_modified_result",
)
_INHERITED_FUNCTIONS = (
    "_resolved_user_agent",
    "_validated_header_value",
    "_validated_path_identifier",
    "_conditional_headers",
    "assert_clean_proxy_env",
)


def test_the_transport_shadows_none_of_the_inherited_hardening() -> None:
    """Converged item 5 -- asserted by IDENTITY, the only barrier against a subclass shadow."""
    for name in _INHERITED_METHODS:
        assert getattr(NwsObservationTransport, name) is getattr(HttpTransport, name), name

    for name in _INHERITED_FUNCTIONS:
        # Either not present in the module namespace, or the http.py object itself.
        assert getattr(transport_module, name, None) in (None, getattr(http_module, name)), name

    tree = ast.parse(inspect.getsource(transport_module))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert defined.isdisjoint(_INHERITED_METHODS)
    assert defined.isdisjoint(_INHERITED_FUNCTIONS)
