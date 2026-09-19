"""WP-12 Seam B: the NBM/NOMADS forecast transport. NBM direct is the live PRIMARY.

Containment is INHERITED, never forked: the transport subclasses
:class:`breezy.ingest.http.HttpTransport` exactly as
:class:`breezy.ingest.nws_observation_transport.NwsObservationTransport` does,
so the host allowlist, the TLS floor, ``follow_redirects=False``, the
streaming body cap and the receipt stamp are the shipped ones.

No test here opens a socket: every exchange is a ``respx`` fixture, and the
suite runs egress-blocked.
"""

from __future__ import annotations

import ast
import datetime as dt
from pathlib import Path

import httpx
import pytest
import respx

from breezy.ingest.http import DisallowedHostError, HttpTransport, OversizeBodyError
from breezy.ingest.nbm_forecast_transport import (
    NBM_ALLOWED_HOSTS,
    NBM_HOST,
    NbmForecastTransport,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CYCLE_DATE = dt.date(2026, 9, 19)
BULLETIN_URL = (
    f"https://{NBM_HOST}/pub/data/nccf/com/blend/prod/blend.20260919/12/text/blend_nbstx.t12z"
)


def _clock() -> int:
    return 1_789_000_000_000_000_000


def _transport(**kwargs: object) -> NbmForecastTransport:
    return NbmForecastTransport(clock=_clock, check_proxy_env=False, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The host, and only the host
# ---------------------------------------------------------------------------


def test_the_allowlist_is_exactly_the_nomads_host() -> None:
    assert NBM_ALLOWED_HOSTS == frozenset({"nomads.ncep.noaa.gov"})
    assert _transport()._allowed_hosts == NBM_ALLOWED_HOSTS


def test_the_host_is_named_literally_and_never_assembled() -> None:
    """A `".".join(...)` or an f-string host would defeat every grep-based audit."""
    source = (
        REPO_ROOT / "src" / "breezy" / "ingest" / "nbm_forecast_transport.py"
    ).read_text(encoding="utf-8")
    assert '"nomads.ncep.noaa.gov"' in source
    assert "noqa" not in source
    tree = ast.parse(source)
    joins = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "join"
    ]
    assert joins == []


def test_another_allowlist_cannot_be_injected() -> None:
    with pytest.raises(ValueError, match="NBM_ALLOWED_HOSTS"):
        _transport(allowed_hosts=frozenset({"api.weather.gov"}))


def test_the_settlement_allowlist_is_untouched_by_this_seam() -> None:
    from breezy.ingest.shared_state import DEFAULT_ALLOWED_HOSTS

    assert DEFAULT_ALLOWED_HOSTS == frozenset({"api.weather.gov"})


# ---------------------------------------------------------------------------
# Inherited hardening, asserted by identity
# ---------------------------------------------------------------------------


def test_it_subclasses_the_hardened_transport() -> None:
    assert issubclass(NbmForecastTransport, HttpTransport)


@pytest.mark.parametrize(
    "control", ["_validate_url", "_build_client", "_raise_for_status", "_read_capped_body"]
)
def test_no_hardening_control_is_forked(control: str) -> None:
    assert control not in vars(NbmForecastTransport)
    assert getattr(NbmForecastTransport, control) is getattr(HttpTransport, control)


@pytest.mark.asyncio
async def test_the_settlement_endpoints_are_closed() -> None:
    transport = _transport()
    with pytest.raises(NotImplementedError):
        await transport.fetch_discovery_list("NYC")
    with pytest.raises(NotImplementedError):
        await transport.fetch_product("00000000-0000-0000-0000-000000000000")
    with pytest.raises(NotImplementedError):
        await transport.fetch_station_observations("KMDW", limit=1)


# ---------------------------------------------------------------------------
# The one endpoint. The caller supplies a cycle, never a URL.
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_it_fetches_the_collective_nbs_bulletin_for_a_cycle() -> None:
    route = respx.get(BULLETIN_URL).mock(return_value=httpx.Response(200, text="BULLETIN"))

    result = await _transport().fetch_nbs_bulletin(cycle_date=CYCLE_DATE, cycle_hour=12)

    assert route.call_count == 1
    assert route.calls[0].request.method == "GET"
    assert result.text == "BULLETIN"
    assert result.url == BULLETIN_URL


@pytest.mark.parametrize("hour", [-1, 24, 99])
@pytest.mark.asyncio
async def test_a_cycle_hour_outside_the_day_is_refused_before_a_socket_opens(hour: int) -> None:
    with pytest.raises(ValueError):
        await _transport().fetch_nbs_bulletin(cycle_date=CYCLE_DATE, cycle_hour=hour)


@pytest.mark.asyncio
async def test_a_non_int_cycle_hour_is_refused() -> None:
    with pytest.raises(TypeError):
        await _transport().fetch_nbs_bulletin(cycle_date=CYCLE_DATE, cycle_hour=True)


@pytest.mark.asyncio
async def test_a_non_date_cycle_is_refused() -> None:
    with pytest.raises(TypeError):
        await _transport().fetch_nbs_bulletin(cycle_date="2026-09-19", cycle_hour=12)  # type: ignore[arg-type]


@respx.mock
@pytest.mark.asyncio
async def test_an_off_allowlist_origin_is_refused() -> None:
    rogue = NbmForecastTransport(
        clock=_clock, check_proxy_env=False, base_url="https://evil.example"
    )
    with pytest.raises(DisallowedHostError):
        await rogue.fetch_nbs_bulletin(cycle_date=CYCLE_DATE, cycle_hour=12)


@respx.mock
@pytest.mark.asyncio
async def test_the_body_cap_is_enforced_per_instance() -> None:
    respx.get(BULLETIN_URL).mock(return_value=httpx.Response(200, text="x" * 5000))

    transport = _transport(max_body_bytes=1024)
    with pytest.raises(OversizeBodyError):
        await transport.fetch_nbs_bulletin(cycle_date=CYCLE_DATE, cycle_hour=12)


def test_the_default_body_cap_clears_the_measured_bulletin_size() -> None:
    """The live collective bulletin measured 20-28 MB on 2026-09-19."""
    from breezy.ingest.nbm_forecast_transport import DEFAULT_NBM_MAX_BODY_BYTES

    assert DEFAULT_NBM_MAX_BODY_BYTES >= 32 * 1024 * 1024
