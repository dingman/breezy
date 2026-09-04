"""Node wiring for the Polymarket.us read-only data client (plan Step 12).

Authority: ``docs/plans/archive/POLYMARKET_US_READONLY_AUTH_PLAN.md`` (revision 2)
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

This module is read-only at the Nautilus registration boundary: it builds a
GET-only HTTP client (barriers B1-B3, including the B3 receiver-graph tests)
and registers no execution client factory.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from nautilus_trader.cache.cache import Cache
from nautilus_trader.common.component import LiveClock, Logger, MessageBus
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.live.config import LiveDataClientConfig, LiveExecClientConfig
from nautilus_trader.live.factories import LiveDataClientFactory, LiveExecClientFactory
from nautilus_trader.model.identifiers import ClientId

from breezy.adapters.polymarket_us.config import (
    ORIGIN_FIELD_SCHEMES,
    POLYMARKET_US_ALLOW_FOREIGN_ORIGIN_ENV_VAR,
    POLYMARKET_US_API_BASE_URL,
    POLYMARKET_US_GATEWAY_BASE_URL,
    POLYMARKET_US_WS_BASE_URL,
    PolymarketUSDataClientConfig,
    PolymarketUSExecClientConfig,
    PolymarketUSMarketDiscoveryConfig,
    assert_well_formed_origin,
)
from breezy.adapters.polymarket_us.data import (
    MarketsFeed,
    PolymarketUSDataClient,
    build_data_client,
)
from breezy.adapters.polymarket_us.env import load_polymarket_us_credentials
from breezy.adapters.polymarket_us.exec.client import PolymarketUSExecutionClient
from breezy.adapters.polymarket_us.exec.endpoints import (
    PRIVATE_READ_QUOTA_KEY,
    decode_private_payload,
)
from breezy.adapters.polymarket_us.exec.refusals import PrivateReadRefused
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.parsing import parse_quote_tick
from breezy.adapters.polymarket_us.provider import PolymarketUSInstrumentProvider
from breezy.adapters.polymarket_us.signing import Ed25519RequestSigner, SigningVariant
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.adapters.polymarket_us.transport import (
    NautilusHttpTransport,
    build_default_quota,
    build_keyed_quotas,
    build_shared_http_client,
)
from breezy.adapters.polymarket_us.websocket import PolymarketUSMarketsWebSocketPool
from breezy.adapters.polymarket_us.write_transport import PolymarketUSWriteTransport
from breezy.runtime.settings import SettingsError, proxy_env_check_enabled

__all__ = [
    "ACCOUNT_NUMBER_ENV_VAR",
    "API_BASE_ENV_VAR",
    "DISCOVERY_RELOAD_INTERVAL_ENV_VAR",
    "EXEC_STATE_DB_ENV_VAR",
    "GATEWAY_BASE_ENV_VAR",
    "MARKET_SLUGS_ENV_VAR",
    "POLYMARKET_US_ALLOW_FOREIGN_ORIGIN_ENV_VAR",
    "POLYMARKET_US_CLIENT_NAME",
    "SIGNING_VARIANT_ENV_VAR",
    "USER_AGENT_ENV_VAR",
    "WS_MARKETS_REQUIRES_AUTH",
    "WS_URL_ENV_VAR",
    "PolymarketUSLiveDataClientFactory",
    "PolymarketUSLiveExecClientFactory",
    "config_from_env",
    "exec_config_from_env",
]

#: The conventional registration name. It becomes the ``ClientId`` verbatim
#: (``data.derive_client_id``), so it must equal the key used in the node's
#: ``data_clients`` mapping.
POLYMARKET_US_CLIENT_NAME: str = "POLYMARKET_US"

# Plan section 7. Venue-qualified rather than ``BREEZY_VENUE_*`` because Kalshi
# is a committed second venue with a different key format, and one process will
# eventually hold both key sets (plan D1).
#
# G-19 B1/B2: the first four are OPTIONAL OVERRIDES. Each names a value the
# venue publishes about itself, so the bot pins or derives it and starts with
# none of them set; the variable exists only to point a run at a staging host
# or a test double.
API_BASE_ENV_VAR: str = "POLYMARKET_US_API_BASE"
GATEWAY_BASE_ENV_VAR: str = "POLYMARKET_US_GATEWAY_BASE"
WS_URL_ENV_VAR: str = "POLYMARKET_US_WS_URL"
DISCOVERY_RELOAD_INTERVAL_ENV_VAR: str = "POLYMARKET_US_DISCOVERY_RELOAD_INTERVAL_MINS"
MARKET_SLUGS_ENV_VAR: str = "POLYMARKET_US_MARKET_SLUGS"

#: REQUIRED. A contact string is an enablement ceiling, not a venue fact: the
#: bot cannot derive who to contact about its traffic, and must never invent a
#: placeholder.
USER_AGENT_ENV_VAR: str = "POLYMARKET_US_USER_AGENT"

#: Maps each optional origin override to the config field it feeds. Built from
#: :data:`ORIGIN_FIELD_SCHEMES` so the environment reader and the config
#: validator can never disagree about which scheme a field accepts.
_ORIGIN_ENV_VARS: tuple[tuple[str, str, str], ...] = tuple(
    (env_var, field, scheme)
    for env_var, (field, scheme) in zip(
        (API_BASE_ENV_VAR, GATEWAY_BASE_ENV_VAR, WS_URL_ENV_VAR),
        ORIGIN_FIELD_SCHEMES,
        strict=True,
    )
)

#: Optional. Absent means the evidence-backed default, ``PATH_ONLY``
#: (plan section 5.1: docs snapshot ``:82,94,105`` and the SDK's
#: ``auth.py:26-27`` agree that the query string is NOT signed).
SIGNING_VARIANT_ENV_VAR: str = "POLYMARKET_US_SIGNING_VARIANT"

# EXEC SPINE W (docs/plans/EXEC_SPINE_R5_R6_2026-09-02.md section 3, OQ-I).
#
# REQUIRED. `account_number` has ZERO producers anywhere else in the repo
# (`grep -rn "account_number" src/ scripts/` outside `exec/client.py` returns
# nothing but the constructor parameter itself) -- it exists only as the
# `AccountId` suffix (`exec/client.py:535-537`). Read fresh from the
# operator's venue configuration on every process start, alongside the
# credentials at `~/.config/breezy/polymarket.env` -- the SAME mechanism that
# already makes those credentials stable across a restart makes this value
# stable too: a static environment variable, never generated, cached or
# derived. A changed value re-labels every future event under a new
# `AccountId`; it orphans nothing in the durable store, whose keys are
# prefixed by venue, never by account (`exec/client.py:80-92`).
ACCOUNT_NUMBER_ENV_VAR: str = "POLYMARKET_US_ACCOUNT_NUMBER"

#: REQUIRED. Absolute path to the durable execution state store
#: (`breezy.runtime.sqlite_store.SqliteStateStore`). Deploy path, an operator
#: ceiling like `BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG` -- no default, and
#: never guessed, because a wrong path silently starts a fresh, empty store.
EXEC_STATE_DB_ENV_VAR: str = "POLYMARKET_US_EXEC_STATE_DB"

#: UNRESOLVED venue fact E1: whether ``/v1/ws/markets`` requires authentication
#: at all. The SDK signs it (``sdk_snapshot/.../websocket/base.py:51``), so the
#: safe assumption is "yes" until the smoke test measures otherwise. Being
#: wrong in this direction costs a redundant signature; being wrong the other
#: way is a handshake rejection with no quotes at all. Flipping this to
#: ``False`` also re-enables the native pyo3 reconnect, because a public socket
#: has no stale-timestamp problem (plan section 5.3).
WS_MARKETS_REQUIRES_AUTH: bool = True

#: Exact value required to engage the origin-allowlist escape.
_ALLOW_FOREIGN_ORIGIN_ENV_VALUE: str = "1"


def _allow_foreign_origin(source: Mapping[str, str]) -> bool:
    """Read the separately-named escape from the venue-domain allowlist.

    Environment resolution belongs HERE, never in ``config.py``: the config is
    a serialisation target that must consult no environment
    (``developer_guide/adapters.md:263-266``, and
    ``test_config_module_never_imports_os``). The answer is then carried as an
    explicit, auditable config FIELD rather than re-read downstream.

    Exact-match on ``"1"``. ``true``/``yes``/``on`` must NOT unlock it: a
    half-remembered spelling should fail closed, loudly, at startup.
    """
    return (
        source.get(POLYMARKET_US_ALLOW_FOREIGN_ORIGIN_ENV_VAR, "").strip()
        == _ALLOW_FOREIGN_ORIGIN_ENV_VALUE
    )


def _origin_override(
    source: Mapping[str, str],
    env_var: str,
    field: str,
    scheme: str,
    pinned: str,
    *,
    allow_foreign: bool = False,
) -> str:
    """Return the validated override, or the pinned venue constant."""
    raw = source.get(env_var, "").strip()
    if not raw:
        return pinned
    try:
        return assert_well_formed_origin(field, raw, scheme=scheme, allow_foreign=allow_foreign)
    except SettingsError as exc:
        raise SettingsError(f"{env_var} is not a usable override: {exc}") from exc


def config_from_env(
    env: Mapping[str, str] | None = None,
) -> PolymarketUSDataClientConfig:
    """Build a data-client config from the section 7 environment contract.

    Exactly one variable is REQUIRED: :data:`USER_AGENT_ENV_VAR`, a contact
    string the bot cannot self-derive. Every other venue variable is an
    OPTIONAL OVERRIDE of a value the bot already knows or derives (G-19 B1/B2),
    so a correctly-provisioned host carries one variable, not five, and a
    missing venue fact is never reported as an operator failure.

    An override that IS present is validated exactly as strictly as the pinned
    value: an override may relocate a host, never relax the transport.

    This is deliberately a module function rather than something ``create``
    does: a config that already carries endpoints must not be silently
    overridden from the environment, and the node's own config assembly is the
    right place to decide which source wins.
    """

    source = os.environ if env is None else env

    raw_user_agent = source.get(USER_AGENT_ENV_VAR, "").strip()
    if not raw_user_agent:
        raise SettingsError(
            f"{USER_AGENT_ENV_VAR} is required and has no default: it is a "
            "contact string for venue operators, which Breezy must never "
            "invent. Every other Polymarket.us venue variable is optional."
        )

    api_env, gateway_env, ws_env = _ORIGIN_ENV_VARS
    allow_foreign = _allow_foreign_origin(source)
    api_base_url = _origin_override(
        source, *api_env, POLYMARKET_US_API_BASE_URL, allow_foreign=allow_foreign
    )
    gateway_base_url = _origin_override(
        source, *gateway_env, POLYMARKET_US_GATEWAY_BASE_URL, allow_foreign=allow_foreign
    )
    ws_url = _origin_override(
        source, *ws_env, POLYMARKET_US_WS_BASE_URL, allow_foreign=allow_foreign
    )

    raw_interval = source.get(DISCOVERY_RELOAD_INTERVAL_ENV_VAR, "").strip()
    reload_interval: int | None = None
    if raw_interval:
        try:
            reload_interval = int(raw_interval)
        except ValueError as exc:
            raise SettingsError(
                f"{DISCOVERY_RELOAD_INTERVAL_ENV_VAR} is an optional override; "
                f"when set it must be a positive integer, was {raw_interval!r}"
            ) from exc
        if reload_interval <= 0:
            raise SettingsError(
                f"{DISCOVERY_RELOAD_INTERVAL_ENV_VAR} is an optional override; "
                f"when set it must be a positive integer, was {raw_interval!r}"
            )
    legacy_slugs: tuple[str, ...] = ()
    raw_legacy_slugs = source.get(MARKET_SLUGS_ENV_VAR, "").strip()
    if raw_legacy_slugs:
        legacy_slugs = tuple(part.strip() for part in raw_legacy_slugs.split(","))
        if any(not slug for slug in legacy_slugs):
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
        api_base_url=api_base_url,
        gateway_base_url=gateway_base_url,
        ws_url=ws_url,
        market_slugs=legacy_slugs,
        instrument_reload_interval_mins=reload_interval,
        user_agent=raw_user_agent,
        signing_variant=variant,
        allow_foreign_origin=allow_foreign,
    )


def exec_config_from_env(
    env: Mapping[str, str] | None = None,
) -> PolymarketUSExecClientConfig:
    """Build the execution-client config (EXEC SPINE W).

    Reuses :func:`config_from_env` verbatim for every shared venue fact --
    origins, user agent, signing variant, market discovery -- so this is not a
    second, competing environment policy for the same variables. Only the two
    values genuinely new to the execution surface are read here:
    :data:`ACCOUNT_NUMBER_ENV_VAR` and :data:`EXEC_STATE_DB_ENV_VAR`, both
    REQUIRED with no default.

    ``state_store_opener`` is deliberately left unset: this module is an
    ``adapters`` package and may not import
    ``breezy.runtime.sqlite_store.SqliteStateStore`` (the import-linter layer
    contract puts ``runtime`` above ``adapters``). It is filled in by
    :func:`breezy.runtime.node_config.build_trade_node_config`.
    """
    source = os.environ if env is None else env
    venue_config = config_from_env(env)

    account_number = source.get(ACCOUNT_NUMBER_ENV_VAR, "").strip()
    if not account_number:
        raise SettingsError(
            f"{ACCOUNT_NUMBER_ENV_VAR} is required and has no default: it "
            "becomes the AccountId suffix and Breezy cannot derive it from "
            "anything else"
        )

    raw_state_db = source.get(EXEC_STATE_DB_ENV_VAR, "").strip()
    if not raw_state_db:
        raise SettingsError(f"{EXEC_STATE_DB_ENV_VAR} is required and has no default")
    state_store_path = Path(raw_state_db)
    if not state_store_path.is_absolute():
        raise SettingsError(
            f"{EXEC_STATE_DB_ENV_VAR} must be an absolute path, was {raw_state_db!r}"
        )
    if any(part == ".." for part in state_store_path.parts):
        raise SettingsError(
            f"{EXEC_STATE_DB_ENV_VAR} must not contain a '..' segment, was {raw_state_db!r}"
        )

    return PolymarketUSExecClientConfig(
        venue=venue_config,
        account_number=account_number,
        state_store_path=str(state_store_path),
    )


def _required(
    value: str | None, *, field: str, config_name: str = "PolymarketUSDataClientConfig"
) -> str:
    """Narrow a ``str | None`` config field that ``__post_init__`` guarantees.

    Both configs' ``__post_init__`` already refuse an unset value, so this can
    only fire if a config was bypassed. It stays because ``msgspec.Struct``
    performs no validation on direct construction and mypy cannot see the
    ``__post_init__`` guarantee.
    """
    if value is None or not value.strip():
        raise SettingsError(
            f"{config_name}.{field} is unset; every venue parameter is a "
            "required input with no default"
        )
    return value


def _instrument_provider_config_for(
    config: PolymarketUSDataClientConfig,
) -> InstrumentProviderConfig:
    """Ensure Nautilus initializes via autonomous market discovery."""
    provider_config = config.instrument_provider
    if provider_config.load_all or provider_config.load_ids:
        return provider_config
    return InstrumentProviderConfig(
        load_all=True,
        filters=provider_config.filters,
        filter_callable=provider_config.filter_callable,
        log_warnings=provider_config.log_warnings,
        use_gamma_markets=provider_config.use_gamma_markets,
    )


# ---------------------------------------------------------------------------
# Shared object-graph caches -- ONE HTTP client, ONE instrument provider
# ---------------------------------------------------------------------------
#
# Defect A. `LiveExecClientFactory.create` and `LiveDataClientFactory.create`
# are both `@staticmethod`s invoked with no channel back to each other's
# object graph (`live/node_builder.py:143-246`), so before this each factory
# built its OWN `PolymarketUSHttpClient` -- and therefore its own
# `nautilus_pyo3.HttpClient`, which is where the rate limiter actually lives
# (`transport.py:317-323`: `keyed_quotas` is a construction-time argument of
# the pyo3 client itself, an in-process token bucket scoped to that ONE
# object). Two clients built from the SAME quota configuration are two
# INDEPENDENT buckets: the venue -- which enforces per-account/per-IP, not
# per-Python-object -- sees up to 2x the configured discovery/instrument
# request rate, worst at node startup when both instrument providers load
# concurrently.
#
# This is a native idiom this repo missed, not an invention. Every shipped
# multi-client Nautilus adapter shares one graph via a module-level
# `@lru_cache(1)` factory function called from BOTH `create()`s -- most
# tellingly the shipped `nautilus_trader.adapters.polymarket` adapter, our
# closest sibling: `get_polymarket_http_client`
# (`adapters/polymarket/factories.py:42-43`, `@lru_cache(1)`) and
# `get_polymarket_instrument_provider` (`:100-101`, `@lru_cache(1)`), each
# called from both `PolymarketLiveDataClientFactory.create` and
# `PolymarketLiveExecClientFactory.create`.
#
# Cached by VALUE, not by identity: `PolymarketUSDataClientConfig` is a
# frozen, hashable `msgspec.Struct` (verified: two independently-constructed,
# value-equal instances hash and compare equal), and the data and exec
# factories each build their OWN config instance from the same environment
# (`config_from_env` / `exec_config_from_env` in `trade_cli.py`) -- so two
# distinct-but-equal config objects must still resolve to the SAME cached
# client. `lru_cache` raises `TypeError` if a config is ever unhashable,
# rather than silently falling through to build a second, unshared client --
# that would reintroduce this exact defect invisibly, so it is left to raise.
#
# `maxsize=1`: this process runs exactly one venue configuration for its
# lifetime, exactly like the native precedent.
@lru_cache(maxsize=1)
def _shared_polymarket_us_signer(
    config: PolymarketUSDataClientConfig, clock: LiveClock
) -> Ed25519RequestSigner:
    # BLOCKING filesystem I/O, deliberately performed here: see
    # `PolymarketUSLiveDataClientFactory`'s "Why credentials are resolved
    # HERE" docstring. Loaded once and shared, rather than once per factory.
    credentials = load_polymarket_us_credentials(config.secrets)
    return Ed25519RequestSigner.for_variant(
        credentials,
        clock=clock,
        variant=SigningVariant(config.signing_variant),
    )


def _shared_polymarket_us_client(config: PolymarketUSDataClientConfig) -> Any:
    """The ONE pyo3 HttpClient. Both wrappers call this; a second client halves Quota."""
    user_agent = _required(config.user_agent, field="user_agent")
    return build_shared_http_client(
        timeout_secs=config.http_timeout_secs,
        default_quota=build_default_quota(config.global_requests_per_second),
        keyed_quotas=build_keyed_quotas(
            discovery_requests_per_minute=config.discovery_requests_per_minute,
            instrument_requests_per_minute=config.instrument_requests_per_minute,
            book_requests_per_minute=config.book_requests_per_minute,
        ),
        default_headers={"User-Agent": user_agent},
        # One operator switch for both transports; see the identical
        # comment previously carried on each factory's own construction.
        check_proxy_env=proxy_env_check_enabled(),
    )


@lru_cache(maxsize=1)
def _shared_polymarket_us_write_transport(
    config: PolymarketUSDataClientConfig,
) -> PolymarketUSWriteTransport:
    """Constructed here; nothing dispatches through it until R-7."""
    return PolymarketUSWriteTransport(client=_shared_polymarket_us_client(config))


@lru_cache(maxsize=1)
def _shared_polymarket_us_transport(
    config: PolymarketUSDataClientConfig,
) -> NautilusHttpTransport:
    """The ONE transport -- and therefore the ONE rate-limiter token bucket."""
    client = _shared_polymarket_us_client(config)
    _shared_polymarket_us_write_transport(config)
    return NautilusHttpTransport(client=client)


@lru_cache(maxsize=1)
def _shared_polymarket_us_http_client(
    config: PolymarketUSDataClientConfig, clock: LiveClock
) -> PolymarketUSHttpClient:
    return PolymarketUSHttpClient(
        transport=_shared_polymarket_us_transport(config),
        signer=_shared_polymarket_us_signer(config, clock),
        api_base_url=config.api_base_url,
        gateway_base_url=config.gateway_base_url,
        logger=Logger(f"{POLYMARKET_US_CLIENT_NAME}-http"),
    )


@lru_cache(maxsize=1)
def _shared_polymarket_us_instrument_provider(
    client: PolymarketUSHttpClient,
    provider_config: InstrumentProviderConfig,
    discovery: PolymarketUSMarketDiscoveryConfig,
    clock: LiveClock,
) -> PolymarketUSInstrumentProvider:
    """The ONE instrument provider, dissolving a divergence risk.

    R-4's ``_find_instrument`` fallback (``exec/client.py:992-1002``) was
    mitigating two independent providers loading concurrently at startup and
    transiently disagreeing on which instruments were resolved. One shared
    provider removes the possibility entirely rather than papering over it.
    """
    return PolymarketUSInstrumentProvider(
        client=client,
        config=provider_config,
        venue=POLYMARKET_US_VENUE,
        discovery=discovery,
        clock=clock,
        logger=Logger(f"{POLYMARKET_US_CLIENT_NAME}-discovery"),
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

        ws_url = config.ws_url

        # BLOCKING filesystem I/O may happen here, deliberately: `build()`
        # runs before the event loop starts (`live/node.py:272-280`). Never
        # move this into a coroutine or a reconnect path (plan :520-530).
        # SHARED with the sibling exec-side factory below (defect A): both
        # factories call the same `@lru_cache(1)` getters with an
        # equal-valued `config`, so exactly ONE transport (and therefore ONE
        # rate-limiter token bucket), ONE signer and ONE instrument provider
        # exist for the process, never two independently-quota'd clients.
        # See the "Shared object-graph caches" block above `create`.
        signer = _shared_polymarket_us_signer(config, clock)
        http_client = _shared_polymarket_us_http_client(config, clock)
        instrument_provider = _shared_polymarket_us_instrument_provider(
            http_client,
            _instrument_provider_config_for(config),
            config.market_discovery,
            clock,
        )

        ws_signer = signer if WS_MARKETS_REQUIRES_AUTH else None
        ws_logger = Logger(f"{name}-ws")

        def feed_factory(handler: Callable[[bytes], None]) -> MarketsFeed:
            # The socket takes its frame handler at construction time and the
            # data client IS that handler, so the client builds its own feed
            # from this closure rather than receiving a pre-built socket.
            #
            # A pool, not a bare `PolymarketUSMarketsWebSocket`: the venue caps
            # subscriptions per connection (`websocket.MAX_SUBSCRIPTIONS_PER_
            # CONNECTION`, empirically measured 2026-08-30) and silently drops
            # every subscription past it. The pool shards across as many
            # connections as the live slug count requires; for <=
            # MAX_SUBSCRIPTIONS_PER_CONNECTION slugs it behaves identically to
            # the single connection it replaces.
            return PolymarketUSMarketsWebSocketPool(
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


class PolymarketUSLiveExecClientFactory(LiveExecClientFactory):
    """Construct the reconciling, order-refusing Polymarket.us execution client.

    EXEC SPINE W (``docs/plans/EXEC_SPINE_R5_R6_2026-09-02.md`` section 3).
    Registered exactly like the data-side sibling::

        node.add_exec_client_factory(
            POLYMARKET_US_CLIENT_NAME, PolymarketUSLiveExecClientFactory
        )

    **This is where the GET-only guarantee actually lives.**
    :class:`~breezy.adapters.polymarket_us.exec.client.PrivateRead` is a
    ``typing.Protocol`` with no ``runtime_checkable`` decorator
    (``exec/client.py:335-347``), so nothing at the client boundary can verify
    the injected callable at runtime beyond ``callable()``. The closure built
    below is a GET, and only a GET: it calls ``transport.get`` -- the same
    GET-only wrapper the read-only data client already uses
    (``transport.py:242-325``) -- and signs through
    ``Ed25519RequestSigner.sign_headers``, whose ``PERMITTED_METHODS ==
    frozenset({"GET"})`` (``signing.py:84``) refuses every other verb
    (``:260-265``). **No ``query`` parameter exists on the closure or on
    ``PrivateRead.__call__`` itself** -- the same reasoning that keeps a
    paginated read from being smuggled into a signed path segment applies
    here: ``query_string`` is always the empty string, so the signature is
    always over the BARE path.

    **The durable-store opener is injected, never imported.** This module is
    an ``adapters`` package; ``breezy.runtime.sqlite_store.SqliteStateStore``
    lives in ``runtime``, ABOVE ``adapters`` in the import-linter layer
    contract. ``config.state_store_opener`` is filled in by
    ``breezy.runtime.node_config.build_trade_node_config`` -- see that
    module's docstring -- and is threaded straight through, unopened, to
    :class:`PolymarketUSExecutionClient`, which itself only ever calls it
    from ``_connect``, on the loop thread that will write to it.
    """

    @staticmethod
    def create(
        loop: asyncio.AbstractEventLoop,
        name: str,
        config: LiveExecClientConfig,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
    ) -> PolymarketUSExecutionClient:
        if not isinstance(config, PolymarketUSExecClientConfig):
            raise SettingsError(
                "PolymarketUSLiveExecClientFactory requires a "
                f"PolymarketUSExecClientConfig; got {type(config).__name__}"
            )
        venue_config = config.venue
        if not isinstance(venue_config, PolymarketUSDataClientConfig):
            raise SettingsError(
                "PolymarketUSExecClientConfig.venue must be a "
                f"PolymarketUSDataClientConfig; got {type(venue_config).__name__}"
            )
        account_number = _required(
            config.account_number,
            field="account_number",
            config_name="PolymarketUSExecClientConfig",
        )
        state_store_opener = config.state_store_opener
        if state_store_opener is None:
            raise SettingsError(
                "PolymarketUSExecClientConfig.state_store_opener is unset; "
                "build_trade_node_config must inject it before the node is built"
            )

        # SHARED with `PolymarketUSLiveDataClientFactory` (defect A): both
        # factories call the same `@lru_cache(1)` getters with an
        # equal-valued `venue_config`, so this is the SAME transport (and
        # therefore the SAME rate-limiter token bucket), the SAME signer and
        # the SAME instrument provider the data client built -- never a
        # second, independently-quota'd object graph. See the "Shared
        # object-graph caches" block above `PolymarketUSLiveDataClientFactory`.
        # BLOCKING filesystem I/O may happen on a cache miss: see the
        # identical comment on `PolymarketUSLiveDataClientFactory.create`.
        signer = _shared_polymarket_us_signer(venue_config, clock)
        transport = _shared_polymarket_us_transport(venue_config)
        http_client = _shared_polymarket_us_http_client(venue_config, clock)
        instrument_provider = _shared_polymarket_us_instrument_provider(
            http_client,
            _instrument_provider_config_for(venue_config),
            venue_config.market_discovery,
            clock,
        )

        stripped_api_base_url = venue_config.api_base_url.rstrip("/")

        async def private_read(path: str) -> Mapping[str, Any]:
            """The injected ``PrivateRead``: one signed GET, decoded Decimal-safe.

            No ``query`` parameter, by construction (see the class docstring):
            the bare ``path`` is what is signed AND what is fetched, so the two
            can never drift apart. ``PolymarketUSHttpClient`` is deliberately
            NOT used for this call: its own ``_decode`` (`http.py:249-263`)
            calls ``json.loads`` with no ``parse_float``, which would silently
            replace a private-surface money literal with a different `float`
            (`exec/endpoints.py` module docstring). ``decode_private_payload``
            is the Decimal-preserving decode this surface requires.

            R-6.5a: any non-2xx status is raised as ``PrivateReadRefused`` --
            carrying the status, the bare path, and the raw body -- rather
            than handed to ``decode_private_payload``.
            ``NautilusHttpTransport.get`` (``transport.py``) returns a
            ``VenueResponse`` for any status short of a 3xx or a transport
            fault, so before this check a 503 whose body was a
            ``google.rpc.Status`` JSON object decoded as if it were a
            payload, and ``classify_venue_refusal`` (``exec/refusals.py``)
            could never be reached. See ``PrivateRead.__call__``'s own
            docstring (``exec/client.py``): every implementation, present or
            future, carries this same obligation.
            """
            headers = dict(signer.sign_headers("GET", path, query_string=""))
            response = await transport.get(
                f"{stripped_api_base_url}{path}",
                headers=headers,
                quota_key=PRIVATE_READ_QUOTA_KEY,
            )
            if not 200 <= response.status < 300:
                raise PrivateReadRefused(status=response.status, path=path, body=response.body)
            return decode_private_payload(response.body, context=path)

        client = PolymarketUSExecutionClient(
            loop=loop,
            client_id=ClientId(name),
            venue=POLYMARKET_US_VENUE,
            instrument_provider=instrument_provider,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
            private_read=private_read,
            state_store_opener=state_store_opener,
            account_number=account_number,
            instrument_wait_timeout_s=config.instrument_wait_timeout_s,
            account_registration_timeout_s=config.account_registration_timeout_s,
        )
        # Composition-root latch, stored for R-7's ``_connect``. This increment
        # does not consume it. The exec client never opens its own latch.
        # ``LiveExecutionClient`` is Cython: extra attrs may be refused, in
        # which case the injected config field is the remaining store.
        try:
            object.__setattr__(
                client, "_submit_intent_latch", config.submit_intent_latch
            )
        except (AttributeError, TypeError):
            pass
        return client
