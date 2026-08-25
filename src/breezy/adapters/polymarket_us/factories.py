"""Node wiring for the Polymarket.us read-only data client (plan Step 12).

Authority: ``docs/plans/POLYMARKET_US_READONLY_AUTH_PLAN.md`` (revision 2)
section 6 ``factories.py`` (``:883-905``), section 7 environment contract
(``:930-949``), section 8.3 startup flow (``:1026-1042``), controls S3 and
S14.

Null hypothesis, settled by reading the install
-----------------------------------------------
Nautilus already owns everything about client registration and construction
ordering, and none of it is rebuilt here:

* ``LiveDataClientFactory`` is the extension point
  (``live/factories.py:27-40``);
* ``TradingNode.add_data_client_factory(name, FactoryClass)`` registers the
  CLASS (``live/node.py:230``);
* ``LiveDataClientBuilder.build_data_clients`` resolves the name, calls
  ``factory.create(...)`` and then performs ``register_client``,
  ``register_default_client`` and venue routing itself
  (``live/node_builder.py:143-201``).

So this module contributes exactly two things: the concrete object graph, and
the environment-to-config translation the venue contract requires.

Why the factory must import its collaborators concretely
--------------------------------------------------------
``create`` is a ``@staticmethod`` invoked on the class, not on an instance
(``live/node_builder.py:177``). There is no ``self``, no constructor, and no
registration hook that could carry an injected provider or parser. Anything
the client needs must therefore be imported here by name. That is a property
of the native extension point, not a design choice.

Why credentials are resolved HERE and nowhere else
--------------------------------------------------
``load_polymarket_us_credentials`` performs synchronous ``os.open`` /
``os.fstat`` / ``os.read`` on the key file (plan ``:520-530``).
``TradingNode.build()`` (``live/node.py:272-280``) is an ordinary synchronous
method that runs BEFORE ``run()`` starts the event loop, so a blocking read
here costs nothing. The same call inside ``_connect`` or a reconnect handler
would block the single trading loop and stall every other client on it,
including the settlement feed. ``developer_guide/adapters.md:263-266`` states
the rule; ``adapters/databento/factories.py:59`` is the in-tree precedent.

This module is READ-ONLY by construction: it builds a GET-only HTTP client
(barriers B1-B3) and registers no execution client factory.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Mapping

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, Logger, MessageBus
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.live.config import LiveDataClientConfig
from nautilus_trader.live.factories import LiveDataClientFactory

from breezy.adapters.polymarket_us.config import PolymarketUSDataClientConfig
from breezy.adapters.polymarket_us.data import (
    MarketsFeed,
    PolymarketUSDataClient,
    build_data_client,
)
from breezy.adapters.polymarket_us.env import load_polymarket_us_credentials
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.parsing import parse_quote_tick
from breezy.adapters.polymarket_us.provider import PolymarketUSInstrumentProvider
from breezy.adapters.polymarket_us.signing import Ed25519RequestSigner, SigningVariant
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE, slug_to_instrument_id
from breezy.adapters.polymarket_us.transport import (
    NautilusHttpTransport,
    build_default_quota,
    build_keyed_quotas,
)
from breezy.adapters.polymarket_us.websocket import PolymarketUSMarketsWebSocket
from breezy.runtime.settings import SettingsError

__all__ = [
    "API_BASE_ENV_VAR",
    "GATEWAY_BASE_ENV_VAR",
    "MARKET_SLUGS_ENV_VAR",
    "POLYMARKET_US_CLIENT_NAME",
    "SIGNING_VARIANT_ENV_VAR",
    "USER_AGENT_ENV_VAR",
    "WS_MARKETS_REQUIRES_AUTH",
    "WS_URL_ENV_VAR",
    "PolymarketUSLiveDataClientFactory",
    "config_from_env",
]

#: The conventional registration name. It becomes the ``ClientId`` verbatim
#: (``data.derive_client_id``), so it must equal the key used in the node's
#: ``data_clients`` mapping.
POLYMARKET_US_CLIENT_NAME: str = "POLYMARKET_US"

# Plan section 7. Venue-qualified rather than ``BREEZY_VENUE_*`` because Kalshi
# is a committed second venue with a different key format, and one process will
# eventually hold both key sets (plan D1).
API_BASE_ENV_VAR: str = "POLYMARKET_US_API_BASE"
GATEWAY_BASE_ENV_VAR: str = "POLYMARKET_US_GATEWAY_BASE"
WS_URL_ENV_VAR: str = "POLYMARKET_US_WS_URL"
MARKET_SLUGS_ENV_VAR: str = "POLYMARKET_US_MARKET_SLUGS"
USER_AGENT_ENV_VAR: str = "POLYMARKET_US_USER_AGENT"

#: Optional. Absent means the evidence-backed default, ``PATH_ONLY``
#: (plan section 5.1: docs snapshot ``:82,94,105`` and the SDK's
#: ``auth.py:26-27`` agree that the query string is NOT signed).
SIGNING_VARIANT_ENV_VAR: str = "POLYMARKET_US_SIGNING_VARIANT"

#: UNRESOLVED venue fact E1: whether ``/v1/ws/markets`` requires authentication
#: at all. The SDK signs it (``sdk_snapshot/.../websocket/base.py:51``), so the
#: safe assumption is "yes" until the smoke test measures otherwise. Being
#: wrong in this direction costs a redundant signature; being wrong the other
#: way is a handshake rejection with no quotes at all. Flipping this to
#: ``False`` also re-enables the native pyo3 reconnect, because a public socket
#: has no stale-timestamp problem (plan section 5.3).
WS_MARKETS_REQUIRES_AUTH: bool = True


def config_from_env(
    env: Mapping[str, str] | None = None,
) -> PolymarketUSDataClientConfig:
    """Build a data-client config from the section 7 environment contract.

    Every variable is REQUIRED with no default
    (``TRADING_ENABLEMENT_FINDINGS.md:254-256``), and every unset one is named
    in a single :class:`SettingsError` so an operator fixes the whole
    environment in one pass instead of one variable per run.

    This is deliberately a module function rather than something ``create``
    does: a config that already carries endpoints must not be silently
    overridden from the environment, and the node's own config assembly is the
    right place to decide which source wins.
    """

    source = os.environ if env is None else env

    missing: list[str] = []
    values: dict[str, str] = {}
    for name in (
        API_BASE_ENV_VAR,
        GATEWAY_BASE_ENV_VAR,
        WS_URL_ENV_VAR,
        MARKET_SLUGS_ENV_VAR,
        USER_AGENT_ENV_VAR,
    ):
        raw = source.get(name, "")
        if not raw.strip():
            missing.append(name)
        else:
            values[name] = raw.strip()
    if missing:
        raise SettingsError(
            "Polymarket.us venue configuration is incomplete; every variable is "
            "required with no default. Unset or empty: " + ", ".join(missing)
        )

    slugs = tuple(part.strip() for part in values[MARKET_SLUGS_ENV_VAR].split(","))
    if any(not slug for slug in slugs):
        raise SettingsError(
            f"{MARKET_SLUGS_ENV_VAR} contains a blank entry; it must be a "
            "comma-separated list of non-empty market slugs"
        )

    raw_variant = source.get(SIGNING_VARIANT_ENV_VAR, "").strip()
    if raw_variant:
        try:
            variant = SigningVariant(raw_variant)
        except ValueError as exc:
            permitted = ", ".join(item.value for item in SigningVariant)
            raise SettingsError(
                f"{SIGNING_VARIANT_ENV_VAR} must be one of: {permitted}; was {raw_variant!r}"
            ) from exc
    else:
        variant = SigningVariant.PATH_ONLY

    return PolymarketUSDataClientConfig(
        api_base_url=values[API_BASE_ENV_VAR],
        gateway_base_url=values[GATEWAY_BASE_ENV_VAR],
        ws_url=values[WS_URL_ENV_VAR],
        market_slugs=slugs,
        user_agent=values[USER_AGENT_ENV_VAR],
        signing_variant=variant,
    )


def _required(value: str | None, *, field: str) -> str:
    """Narrow a ``str | None`` config field that ``__post_init__`` guarantees.

    ``PolymarketUSDataClientConfig.__post_init__`` already refuses an unset
    value, so this can only fire if the config was bypassed. It stays because
    ``msgspec.Struct`` performs no validation on direct construction and mypy
    cannot see the ``__post_init__`` guarantee.
    """
    if value is None or not value.strip():
        raise SettingsError(
            f"PolymarketUSDataClientConfig.{field} is unset; every venue "
            "parameter is a required input with no default"
        )
    return value


def _instrument_provider_config_for(
    config: PolymarketUSDataClientConfig,
) -> InstrumentProviderConfig:
    """Ensure Nautilus initializes the configured Polymarket.us slug universe."""
    provider_config = config.instrument_provider
    if provider_config.load_all or provider_config.load_ids:
        return provider_config
    return InstrumentProviderConfig(
        load_ids=frozenset(slug_to_instrument_id(slug) for slug in config.market_slugs),
        filters=provider_config.filters,
        filter_callable=provider_config.filter_callable,
        log_warnings=provider_config.log_warnings,
        use_gamma_markets=provider_config.use_gamma_markets,
    )


class PolymarketUSLiveDataClientFactory(LiveDataClientFactory):
    """Construct the read-only Polymarket.us data client for a ``TradingNode``.

    Registered as a CLASS, never an instance::

        node.add_data_client_factory(
            POLYMARKET_US_CLIENT_NAME, PolymarketUSLiveDataClientFactory
        )

    and the same key must appear in ``TradingNodeConfig.data_clients`` so that
    ``ClientId(name)`` routes consistently (``live/node_builder.py:163,177``).
    """

    @staticmethod
    def create(
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: LiveDataClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> PolymarketUSDataClient:
        """Resolve credentials, build the object graph, and wire the client.

        The parameter type stays the base ``LiveDataClientConfig`` that
        ``live/factories.py:33-40`` declares, and the venue type is asserted
        rather than declared: narrowing the signature would make the override
        unsound, and the node passes whatever the operator put in
        ``data_clients``.
        """
        if not isinstance(config, PolymarketUSDataClientConfig):
            raise SettingsError(
                "PolymarketUSLiveDataClientFactory requires a "
                f"PolymarketUSDataClientConfig; got {type(config).__name__}"
            )

        api_base_url = _required(config.api_base_url, field="api_base_url")
        gateway_base_url = _required(config.gateway_base_url, field="gateway_base_url")
        ws_url = _required(config.ws_url, field="ws_url")
        user_agent = _required(config.user_agent, field="user_agent")

        # BLOCKING filesystem I/O, deliberately performed here: `build()` runs
        # before the event loop starts (`live/node.py:272-280`). Never move
        # this into a coroutine or a reconnect path (plan :520-530).
        credentials = load_polymarket_us_credentials(config.secrets)

        signer = Ed25519RequestSigner.for_variant(
            credentials,
            clock=clock,
            variant=SigningVariant(config.signing_variant),
        )
        transport = NautilusHttpTransport(
            timeout_secs=config.http_timeout_secs,
            default_quota=build_default_quota(config.global_requests_per_second),
            keyed_quotas=build_keyed_quotas(
                instrument_requests_per_minute=config.instrument_requests_per_minute,
                book_requests_per_minute=config.book_requests_per_minute,
            ),
            default_headers={"User-Agent": user_agent},
        )
        http_client = PolymarketUSHttpClient(
            transport=transport,
            signer=signer,
            api_base_url=api_base_url,
            gateway_base_url=gateway_base_url,
            logger=Logger(f"{name}-http"),
        )
        instrument_provider = PolymarketUSInstrumentProvider(
            client=http_client,
            config=_instrument_provider_config_for(config),
            venue=POLYMARKET_US_VENUE,
            market_slugs=config.market_slugs,
            clock=clock,
        )

        ws_signer = signer if WS_MARKETS_REQUIRES_AUTH else None
        ws_logger = Logger(f"{name}-ws")

        def feed_factory(handler: Callable[[bytes], None]) -> MarketsFeed:
            # The socket takes its frame handler at construction time and the
            # data client IS that handler, so the client builds its own feed
            # from this closure rather than receiving a pre-built socket.
            return PolymarketUSMarketsWebSocket(
                ws_url=ws_url,
                signer=ws_signer,
                handler=handler,
                loop=loop,
                heartbeat_secs=config.ws_heartbeat_secs,
                idle_timeout_secs=config.ws_idle_timeout_secs,
                logger=ws_logger,
            )

        return build_data_client(
            loop=loop,
            name=name,
            config=config,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            instrument_provider=instrument_provider,
            feed_factory=feed_factory,
            quote_parser=parse_quote_tick,
        )
