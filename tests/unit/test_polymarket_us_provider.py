"""``PolymarketUSInstrumentProvider`` -- the native Nautilus extension point.

Plan revision 2 section 6 (``instruments.py`` blueprint; this slice ships it as
``provider.py``) and build order Step 9.

The provider is a subclass of Nautilus's own
``nautilus_trader.common.providers.InstrumentProvider``. Nothing about
loading, caching, ``find``/``get_all``, ``initialize`` or the
``load_ids``/``load`` sync wrappers is re-implemented here -- only the two
venue-specific fetch overrides are.

No credential and no socket is involved: the provider is driven through the
already-shipped ``PolymarketUSHttpClient`` sitting on a recording stub
transport, and every payload is a committed capture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from nautilus_trader.common.component import TestClock
from nautilus_trader.common.providers import InstrumentProvider
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.core.correctness import PyCondition
from nautilus_trader.model.identifiers import InstrumentId, Symbol, Venue
from nautilus_trader.model.instruments import BinaryOption

from breezy.adapters.polymarket_us.errors import (
    InstrumentDefinitionError,
    PolymarketUSError,
    VenuePayloadError,
)
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.provider import (
    MARKET_BY_SLUG_PATH,
    PolymarketUSInstrumentProvider,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.adapters.polymarket_us.transport import QUOTA_KEY_INSTRUMENTS, VenueResponse

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW = REPO_ROOT / "docs" / "evidence" / "venue" / "polymarket_us" / "raw"

OPEN_SLUG = "tc-temp-nychigh-2026-08-25-lt79f"
CLOSED_SLUG = "tc-temp-nychigh-2026-04-23-gte72lt73f"

TS_INIT = 1_787_617_213_000_000_000


def raw_bytes(name: str) -> bytes:
    return (RAW / name).read_bytes()


class RecordingTransport:
    """Stub satisfying ``PolymarketUSReadTransport``: GET, quota key, nothing else."""

    def __init__(self, bodies: dict[str, bytes]) -> None:
        self._bodies: dict[str, bytes] = bodies
        self.calls: list[tuple[str, str]] = []

    async def get(self, url: str, *, headers: dict[str, str], quota_key: str) -> VenueResponse:
        self.calls.append((url, quota_key))
        assert headers == {}, "a public gateway read must send no auth headers"
        for slug, body in self._bodies.items():
            if url.endswith(f"/{slug}"):
                return VenueResponse(status=200, headers={}, body=body)
        return VenueResponse(status=404, headers={}, body=b"{}")


class UnusableSigner:
    """The public gateway path never signs; touching this is a test failure."""

    def sign_headers(self, *args: object, **kwargs: object) -> list[tuple[str, str]]:
        raise AssertionError("the instrument provider must not sign gateway reads")


class NullLogger:
    def debug(self, message: str) -> None: ...

    def info(self, message: str) -> None: ...

    def warning(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...


def build_provider(
    *,
    bodies: dict[str, bytes] | None = None,
    market_slugs: tuple[str, ...] = (OPEN_SLUG,),
    config: InstrumentProviderConfig | None = None,
) -> tuple[PolymarketUSInstrumentProvider, RecordingTransport, TestClock]:
    if bodies is None:
        bodies = {
            OPEN_SLUG: raw_bytes("market_open_510636_by_slug.json"),
            CLOSED_SLUG: raw_bytes("market_closed_15806_by_slug.json"),
        }
    transport = RecordingTransport(bodies)
    client = PolymarketUSHttpClient(
        transport=transport,  # type: ignore[arg-type]
        signer=UnusableSigner(),  # type: ignore[arg-type]
        api_base_url="https://api.polymarket.us",
        gateway_base_url="https://gateway.polymarket.us",
        logger=NullLogger(),
    )
    clock = TestClock()
    clock.set_time(TS_INIT)
    provider = PolymarketUSInstrumentProvider(
        client=client,
        config=config if config is not None else InstrumentProviderConfig(),
        venue=POLYMARKET_US_VENUE,
        market_slugs=market_slugs,
        clock=clock,
    )
    return provider, transport, clock


# ---------------------------------------------------------------------------
# Native extension point
# ---------------------------------------------------------------------------


def test_provider_is_a_native_nautilus_instrument_provider() -> None:
    provider, _, _ = build_provider()
    assert isinstance(provider, InstrumentProvider)
    # ``live/data_client.py:361`` runs exactly this check on the injected provider.
    PyCondition.type(provider, InstrumentProvider, "instrument_provider")


# ---------------------------------------------------------------------------
# Load path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_all_async_produces_binary_options_from_a_captured_payload() -> None:
    provider, _, _ = build_provider(market_slugs=(OPEN_SLUG, CLOSED_SLUG))
    await provider.load_all_async()

    assert provider.count == 2
    instrument = provider.find(InstrumentId(Symbol(OPEN_SLUG), POLYMARKET_US_VENUE))
    assert isinstance(instrument, BinaryOption)
    assert instrument.outcome == "Yes"


@pytest.mark.asyncio
async def test_ts_init_comes_from_the_injected_clock() -> None:
    provider, _, _ = build_provider()
    await provider.load_all_async()
    instrument = provider.find(InstrumentId(Symbol(OPEN_SLUG), POLYMARKET_US_VENUE))
    assert instrument is not None
    assert instrument.ts_init == TS_INIT


@pytest.mark.asyncio
async def test_instrument_info_carries_city_day_cluster_id() -> None:
    provider, _, _ = build_provider()
    await provider.load_all_async()
    instrument = provider.find(InstrumentId(Symbol(OPEN_SLUG), POLYMARKET_US_VENUE))
    assert instrument is not None
    assert instrument.info["city_day_cluster_id"] == "nyc:2026-08-25"


@pytest.mark.asyncio
async def test_provider_uses_only_the_gateway_market_by_slug_path_and_quota_key() -> None:
    provider, transport, _ = build_provider()
    await provider.load_all_async()

    assert len(transport.calls) == 1
    url, quota_key = transport.calls[0]
    assert url == ("https://gateway.polymarket.us" + MARKET_BY_SLUG_PATH.format(slug=OPEN_SLUG))
    assert quota_key == QUOTA_KEY_INSTRUMENTS


@pytest.mark.asyncio
async def test_repeated_load_of_the_same_slug_issues_one_request() -> None:
    """Instrument metadata is static for a session (plan section 8.2)."""
    provider, transport, _ = build_provider()
    await provider.load_all_async()
    await provider.load_all_async()
    await provider.load_async(InstrumentId(Symbol(OPEN_SLUG), POLYMARKET_US_VENUE))
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_load_ids_async_fetches_only_the_requested_ids() -> None:
    provider, transport, _ = build_provider(market_slugs=(OPEN_SLUG, CLOSED_SLUG))
    await provider.load_ids_async([InstrumentId(Symbol(CLOSED_SLUG), POLYMARKET_US_VENUE)])

    assert len(transport.calls) == 1
    assert transport.calls[0][0].endswith(CLOSED_SLUG)
    assert provider.count == 1


@pytest.mark.asyncio
async def test_initialize_honours_load_all_from_the_native_config() -> None:
    provider, transport, _ = build_provider(
        market_slugs=(OPEN_SLUG,), config=InstrumentProviderConfig(load_all=True)
    )
    await provider.initialize()
    assert provider.count == 1
    assert len(transport.calls) == 1


# ---------------------------------------------------------------------------
# Failure modes -- loud, never silent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_malformed_payload_is_rejected_loudly_and_adds_no_instrument() -> None:
    broken = json.loads(raw_bytes("market_open_510636_by_slug.json"))
    del broken["market"]["orderPriceMinTickSize"]
    provider, _, _ = build_provider(bodies={OPEN_SLUG: json.dumps(broken).encode("utf-8")})
    with pytest.raises(InstrumentDefinitionError):
        await provider.load_all_async()
    assert provider.count == 0


@pytest.mark.asyncio
async def test_one_bad_slug_fails_the_whole_load_rather_than_being_skipped() -> None:
    broken = json.loads(raw_bytes("market_closed_15806_by_slug.json"))
    del broken["market"]["minimumTradeQty"]
    provider, _, _ = build_provider(
        bodies={
            OPEN_SLUG: raw_bytes("market_open_510636_by_slug.json"),
            CLOSED_SLUG: json.dumps(broken).encode("utf-8"),
        },
        market_slugs=(OPEN_SLUG, CLOSED_SLUG),
    )
    with pytest.raises(InstrumentDefinitionError):
        await provider.load_all_async()


@pytest.mark.asyncio
async def test_a_payload_whose_slug_disagrees_with_the_request_is_rejected() -> None:
    swapped = json.loads(raw_bytes("market_open_510636_by_slug.json"))
    swapped["market"]["slug"] = CLOSED_SLUG
    provider, _, _ = build_provider(bodies={OPEN_SLUG: json.dumps(swapped).encode("utf-8")})
    with pytest.raises(InstrumentDefinitionError):
        await provider.load_all_async()


@pytest.mark.asyncio
async def test_an_instrument_id_outside_the_configured_slugs_is_rejected() -> None:
    provider, _, _ = build_provider()
    unknown = InstrumentId(Symbol(CLOSED_SLUG), POLYMARKET_US_VENUE)
    with pytest.raises(VenuePayloadError):
        await provider.load_ids_async([unknown])


@pytest.mark.asyncio
async def test_an_instrument_id_from_a_foreign_venue_is_rejected() -> None:
    provider, _, _ = build_provider()
    foreign = InstrumentId(Symbol(OPEN_SLUG), Venue("KALSHI"))
    with pytest.raises(VenuePayloadError):
        await provider.load_ids_async([foreign])


def test_a_configured_slug_that_is_malformed_is_rejected_at_construction() -> None:
    with pytest.raises(VenuePayloadError):
        build_provider(market_slugs=("tc.temp.dotted",))


def test_an_empty_slug_tuple_is_rejected_at_construction() -> None:
    with pytest.raises(VenuePayloadError):
        build_provider(market_slugs=())


@pytest.mark.asyncio
async def test_a_venue_error_status_propagates_instead_of_yielding_zero_instruments() -> None:
    provider, _, _ = build_provider(bodies={})
    with pytest.raises(PolymarketUSError):
        await provider.load_all_async()
    assert provider.count == 0


def test_provider_defines_no_order_or_execution_surface() -> None:
    forbidden = {"submit_order", "cancel_order", "modify_order", "generate_order_status_report"}
    assert forbidden.isdisjoint(dir(PolymarketUSInstrumentProvider))


def test_provider_module_declares_only_get_paths() -> None:
    assert MARKET_BY_SLUG_PATH.startswith("/v1/market/slug/")
    assert "{slug}" in MARKET_BY_SLUG_PATH


@pytest.mark.parametrize("attribute", ["find", "get_all", "add", "initialize", "count"])
def test_native_provider_surface_is_inherited_not_reimplemented(attribute: str) -> None:
    own = PolymarketUSInstrumentProvider.__dict__
    assert attribute not in own, f"{attribute} is provided natively by InstrumentProvider"
