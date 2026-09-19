"""WP-12 Seam B: the IEM MOS FALLBACK transport -- backfill only, never the live primary.

IEM MOS lags ~40 h and publishes whole degrees F. It is the backfill and
fallback source; NBM direct (``nbm_forecast_transport``) is the live primary.
This module proves three things about the fallback:

* it is paced by a NAMED pacer at >= 1 s between requests, charged INSIDE the
  fetch (the containment shape ``scripts/venue/iem_mos_probe_transport.py``
  established), so the pacing cannot be bypassed by a caller;
* it is a distinct, named ``allowed_hosts`` on the hardened transport -- not a
  ``ProbeTransport``, never the settlement origin, and never a disguised host;
* the live forecast actor does not import it.

No socket opens here.
"""

from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest
import respx

from breezy.ingest.http import HttpTransport
from breezy.ingest.iem_mos_fallback_transport import (
    IEM_MOS_ALLOWED_HOSTS,
    IEM_MOS_HOST,
    IEM_MOS_MIN_INTERVAL_NS,
    IemMosFallbackTransport,
    IemMosPacer,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "breezy" / "ingest"
NS = 1_000_000_000
MOS_URL_PREFIX = f"https://{IEM_MOS_HOST}/cgi-bin/request/mos.py"


class FakeClock:
    def __init__(self) -> None:
        self.now_ns = 1_789_000_000_000_000_000

    def __call__(self) -> int:
        return self.now_ns


def _transport(clock: FakeClock, pacer: IemMosPacer) -> IemMosFallbackTransport:
    return IemMosFallbackTransport(clock=clock, pacer=pacer, check_proxy_env=False)


# ---------------------------------------------------------------------------
# The named pacer, >= 1 s, charged inside the fetch
# ---------------------------------------------------------------------------


def test_the_minimum_interval_is_at_least_one_second() -> None:
    assert IEM_MOS_MIN_INTERVAL_NS >= NS


@pytest.mark.asyncio
async def test_the_pacer_sleeps_the_residual_before_a_second_request() -> None:
    clock = FakeClock()
    slept: list[float] = []

    async def sleeper(seconds: float) -> None:
        slept.append(seconds)
        clock.now_ns += int(seconds * NS)

    pacer = IemMosPacer(clock=clock, sleeper=sleeper)
    await pacer.wait()
    clock.now_ns += NS // 4  # only 250 ms of real work
    await pacer.wait()

    assert slept == [pytest.approx(0.75)]


@pytest.mark.asyncio
async def test_the_pacer_does_not_sleep_when_the_interval_has_already_elapsed() -> None:
    clock = FakeClock()
    slept: list[float] = []

    async def sleeper(seconds: float) -> None:  # pragma: no cover - must not run
        slept.append(seconds)

    pacer = IemMosPacer(clock=clock, sleeper=sleeper)
    await pacer.wait()
    clock.now_ns += 5 * NS
    await pacer.wait()

    assert slept == []


@respx.mock
@pytest.mark.asyncio
async def test_the_pacer_is_charged_inside_the_fetch_not_by_the_caller() -> None:
    respx.get(url__startswith=MOS_URL_PREFIX).mock(return_value=httpx.Response(200, text="a,b\n"))
    clock = FakeClock()
    waits: list[int] = []

    class CountingPacer(IemMosPacer):
        async def wait(self) -> None:
            waits.append(1)
            await super().wait()

    transport = _transport(clock, CountingPacer(clock=clock))
    await transport.fetch_mos_csv(
        station="KMIA", model="NBS", sts="2026-09-01T00:00Z", ets="2026-09-02T00:00Z"
    )

    assert waits == [1]


# ---------------------------------------------------------------------------
# Containment
# ---------------------------------------------------------------------------


def test_the_allowlist_is_exactly_the_iem_host_and_nothing_else() -> None:
    assert IEM_MOS_ALLOWED_HOSTS == frozenset({"mesonet.agron.iastate.edu"})
    clock = FakeClock()
    assert _transport(clock, IemMosPacer(clock=clock))._allowed_hosts == IEM_MOS_ALLOWED_HOSTS


def _imported_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    names |= {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    return names


def _executable_strings(source: str) -> list[str]:
    """Every string constant that is not a docstring.

    Docstrings are exempt for the reason ``test_probe_containment.py`` gives
    about ``docs/evidence``: CITING the probe this transport's containment
    shape was proven by is provenance, not a dependency on it.
    """
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def test_the_host_is_a_plain_literal_with_no_disguise() -> None:
    source = (SRC / "iem_mos_fallback_transport.py").read_text(encoding="utf-8")

    assert IEM_MOS_HOST in _executable_strings(source), (
        "the host must be one plain literal a host audit can grep for"
    )
    tree = ast.parse(source)
    assert [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr == "join"] == []
    assert "noqa" not in "".join(
        line for line in source.splitlines() if line.lstrip().startswith(("#", "IEM"))
    )


def test_it_is_the_hardened_transport_and_never_a_probe_transport() -> None:
    assert issubclass(IemMosFallbackTransport, HttpTransport)
    source = (SRC / "iem_mos_fallback_transport.py").read_text(encoding="utf-8")

    assert "breezy.ingest.probe_transport" not in _imported_modules(source)
    assert "SETTLEMENT_HOSTS" not in _executable_strings(source)
    assert "SETTLEMENT_HOSTS" not in [
        node.id
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Name)
    ]


def test_another_allowlist_cannot_be_injected() -> None:
    clock = FakeClock()
    with pytest.raises(ValueError, match="IEM_MOS_ALLOWED_HOSTS"):
        IemMosFallbackTransport(
            clock=clock,
            pacer=IemMosPacer(clock=clock),
            check_proxy_env=False,
            allowed_hosts=frozenset({"api.weather.gov"}),
        )


@pytest.mark.asyncio
async def test_the_settlement_endpoints_are_closed() -> None:
    clock = FakeClock()
    transport = _transport(clock, IemMosPacer(clock=clock))
    with pytest.raises(NotImplementedError):
        await transport.fetch_discovery_list("NYC")
    with pytest.raises(NotImplementedError):
        await transport.fetch_product("00000000-0000-0000-0000-000000000000")
    with pytest.raises(NotImplementedError):
        await transport.fetch_station_observations("KMDW", limit=1)


@pytest.mark.parametrize(
    ("station", "model", "sts", "ets"),
    [
        ("KORD", "NBS", "2026-09-01T00:00Z", "2026-09-02T00:00Z"),
        ("KMIA", "GFSX", "2026-09-01T00:00Z", "2026-09-02T00:00Z"),
        ("KMIA", "NBS", "yesterday", "2026-09-02T00:00Z"),
        ("KMIA", "NBS", "2026-09-01T00:00Z", "https://evil.example"),
    ],
)
@pytest.mark.asyncio
async def test_an_out_of_alphabet_argument_is_refused_before_a_socket_opens(
    station: str, model: str, sts: str, ets: str
) -> None:
    clock = FakeClock()
    transport = _transport(clock, IemMosPacer(clock=clock))
    with pytest.raises(ValueError):
        await transport.fetch_mos_csv(station=station, model=model, sts=sts, ets=ets)


# ---------------------------------------------------------------------------
# Fallback, not primary
# ---------------------------------------------------------------------------


def test_the_live_forecast_actor_does_not_import_the_fallback_transport() -> None:
    """NBM direct is the live primary; the fallback is backfill only."""
    source = (SRC / "nbm_forecast_actor.py").read_text(encoding="utf-8")

    assert "breezy.ingest.iem_mos_fallback_transport" not in _imported_modules(source)
    assert IEM_MOS_HOST not in _executable_strings(source)


def test_the_module_declares_itself_backfill_only() -> None:
    from breezy.ingest import iem_mos_fallback_transport as module

    assert module.IEM_MOS_IS_LIVE_PRIMARY is False
    assert "FALLBACK" in (module.__doc__ or "")
