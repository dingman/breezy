"""Factory and node wiring for the Polymarket.us read-only slice (plan Step 12).

Authority: ``docs/plans/archive/POLYMARKET_US_READONLY_AUTH_PLAN.md`` (revision 2)
section 6 ``factories.py`` (``:883-905``), section 7 environment contract
(``:930-949``), section 8.3 startup flow (``:1026-1042``) and control S3.

Why this seam needs its own suite
---------------------------------
``LiveDataClientFactory.create`` is a ``@staticmethod`` invoked on the CLASS
(``live/factories.py:32-40``; ``live/node_builder.py:177-184`` calls
``factory.create(...)`` on the registered type, and ``live/node.py:230``
registers a ``type[LiveDataClientFactory]``, never an instance). Nothing can
be injected into it, so the factory must import its collaborators concretely
and every wiring decision it makes is untestable by inspection alone.

Two properties are load-bearing and are proven here rather than asserted:

* **Credentials are resolved at FACTORY time, before the event loop runs.**
  ``load_polymarket_us_credentials`` performs synchronous ``os.open`` /
  ``os.fstat`` / ``os.read`` (plan ``:520-530``). ``TradingNode.build()``
  (``live/node.py:272-280``) is a plain synchronous method that runs before
  ``run()`` starts the loop, so the factory is the correct place; calling it
  from a coroutine would stall every other client on the loop, including the
  settlement feed. :func:`test_credentials_are_resolved_with_no_running_event_loop`
  pins that.
* **``client_id`` / ``venue`` derivation survives the factory.** ``data.py``
  owns and tests the derivation; this suite proves the factory actually goes
  through it rather than reconstructing the client by hand.

The pyo3 HTTP transport is stubbed because ``tests/conftest.py:314`` replaces
``nautilus_pyo3.HttpClient`` with a raising sentinel for every non-socket
test. That block is a safety guard and is NOT weakened here: the stub stands
in at the Breezy seam (``NautilusHttpTransport``), one level above it.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
from collections.abc import Mapping
from typing import Any, ClassVar

import pytest
from nacl.signing import SigningKey
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.live.factories import LiveDataClientFactory
from nautilus_trader.model.identifiers import ClientId, TraderId
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us import factories as factories_module
from breezy.adapters.polymarket_us.config import PolymarketUSDataClientConfig
from breezy.adapters.polymarket_us.credentials import (
    PolymarketUSCredentials,
    PolymarketUSSecretsRefConfig,
)
from breezy.adapters.polymarket_us.data import PolymarketUSDataClient
from breezy.adapters.polymarket_us.factories import (
    API_BASE_ENV_VAR,
    DISCOVERY_RELOAD_INTERVAL_ENV_VAR,
    GATEWAY_BASE_ENV_VAR,
    USER_AGENT_ENV_VAR,
    WS_URL_ENV_VAR,
    PolymarketUSLiveDataClientFactory,
    config_from_env,
)
from breezy.adapters.polymarket_us.parsing import parse_quote_tick
from breezy.adapters.polymarket_us.provider import PolymarketUSInstrumentProvider
from breezy.adapters.polymarket_us.secure import RedactedSecureString
from breezy.adapters.polymarket_us.signing import (
    SigningVariant,
    build_canonical_path_with_query,
    build_canonical_path_without_query,
)
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.adapters.polymarket_us.websocket import (
    PolymarketUSMarketsWebSocket,
    PolymarketUSMarketsWebSocketPool,
)
from breezy.runtime.settings import SettingsError

CLIENT_NAME = "POLYMARKET_US"
SLUG = "tc-temp-nychigh-2026-08-25-lt79f"
OTHER_SLUG = "tc-temp-mdwhigh-2026-08-25-lt91f"
USER_AGENT = "breezy-smoke/1.0 (+mailto:ops@example.com)"


# ---------------------------------------------------------------------------
# Doubles
# ---------------------------------------------------------------------------


class StubTransport:
    """Stands in for ``NautilusHttpTransport`` so no pyo3 client is built."""

    instances: ClassVar[list[StubTransport]] = []

    def __init__(
        self,
        *,
        timeout_secs: int,
        default_quota: Any,
        keyed_quotas: list[tuple[str, Any]],
        default_headers: dict[str, str],
        permitted_quota_keys: frozenset[str] | None = None,
        check_proxy_env: bool = True,
        approved_proxy_env_vars: frozenset[str] | None = None,
    ) -> None:
        self.timeout_secs = timeout_secs
        self.default_quota = default_quota
        self.keyed_quotas = keyed_quotas
        self.default_headers = dict(default_headers)
        self.check_proxy_env = check_proxy_env
        self.approved_proxy_env_vars = approved_proxy_env_vars
        StubTransport.instances.append(self)

    async def get(
        self, url: str, *, headers: Mapping[str, str], quota_key: str
    ) -> Any:  # pragma: no cover - never called in these tests
        raise AssertionError("the factory must not perform any read at wiring time")


def make_credentials() -> PolymarketUSCredentials:
    """An ephemeral, in-process Ed25519 credential. Never a real key."""
    secret = base64.b64encode(bytes(SigningKey.generate())).decode("ascii")
    return PolymarketUSCredentials(
        key_id=RedactedSecureString(str(UUID4()), name="polymarket_us_key_id"),
        secret_key=RedactedSecureString(secret, name="polymarket_us_secret_key"),
    )


def make_env(**overrides: str) -> dict[str, str]:
    env = {
        API_BASE_ENV_VAR: "https://api.polymarket.us",
        GATEWAY_BASE_ENV_VAR: "https://gateway.polymarket.us",
        WS_URL_ENV_VAR: "wss://api.polymarket.us",
        DISCOVERY_RELOAD_INTERVAL_ENV_VAR: "5",
        USER_AGENT_ENV_VAR: USER_AGENT,
    }
    env.update(overrides)
    return env


def make_config(**overrides: Any) -> PolymarketUSDataClientConfig:
    kwargs: dict[str, Any] = {
        "secrets": PolymarketUSSecretsRefConfig(),
        "api_base_url": "https://api.polymarket.us",
        "gateway_base_url": "https://gateway.polymarket.us",
        "ws_url": "wss://api.polymarket.us",
        "instrument_reload_interval_mins": 5,
        "user_agent": USER_AGENT,
    }
    kwargs.update(overrides)
    return PolymarketUSDataClientConfig(**kwargs)


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch the two collaborators that would otherwise open a real socket."""
    StubTransport.instances = []
    calls: list[str] = []
    loop_states: list[bool] = []
    credentials = make_credentials()
    seen_refs: list[PolymarketUSSecretsRefConfig] = []

    def fake_loader(
        secrets_ref: PolymarketUSSecretsRefConfig, **kwargs: Any
    ) -> PolymarketUSCredentials:
        calls.append("credentials")
        seen_refs.append(secrets_ref)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            loop_states.append(False)
        else:  # pragma: no cover - the failure this test exists to catch
            loop_states.append(True)
        return credentials

    monkeypatch.setattr(factories_module, "NautilusHttpTransport", StubTransport)
    monkeypatch.setattr(factories_module, "load_polymarket_us_credentials", fake_loader)
    return {
        "calls": calls,
        "loop_states": loop_states,
        "credentials": credentials,
        "seen_refs": seen_refs,
    }


def build_client(
    config: PolymarketUSDataClientConfig,
    *,
    name: str = CLIENT_NAME,
) -> PolymarketUSDataClient:
    clock = LiveClock()
    trader_id = TraderId("SMOKE-001")
    msgbus = MessageBus(trader_id=trader_id, clock=clock)
    cache = TestComponentStubs.cache()
    loop = asyncio.new_event_loop()
    try:
        return PolymarketUSLiveDataClientFactory.create(
            loop=loop,
            name=name,
            config=config,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
        )
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# The factory contract
# ---------------------------------------------------------------------------


def test_factory_subclasses_the_native_base_and_create_is_a_staticmethod() -> None:
    """``add_data_client_factory`` takes the CLASS (``live/node.py:230``)."""
    assert issubclass(PolymarketUSLiveDataClientFactory, LiveDataClientFactory)
    raw = inspect.getattr_static(PolymarketUSLiveDataClientFactory, "create")
    assert isinstance(raw, staticmethod)


def test_create_derives_the_client_id_from_the_registered_name(
    wired: dict[str, Any],
) -> None:
    client = build_client(make_config())

    assert client.id == ClientId(CLIENT_NAME)


def test_create_uses_the_module_constant_venue(wired: dict[str, Any]) -> None:
    client = build_client(make_config())

    assert client.venue == POLYMARKET_US_VENUE


def test_create_returns_the_adapter_data_client(wired: dict[str, Any]) -> None:
    client = build_client(make_config())

    assert isinstance(client, PolymarketUSDataClient)


def test_credentials_are_resolved_exactly_once_at_factory_time(
    wired: dict[str, Any],
) -> None:
    build_client(make_config())

    assert wired["calls"] == ["credentials"]


def test_credentials_are_resolved_with_no_running_event_loop(
    wired: dict[str, Any],
) -> None:
    """Blocking key-file I/O must never happen on the trading loop (plan :520-530)."""
    build_client(make_config())

    assert wired["loop_states"] == [False]


def test_credentials_are_resolved_from_the_config_supplied_env_var_names(
    wired: dict[str, Any],
) -> None:
    secrets = PolymarketUSSecretsRefConfig(key_id_env_var="POLYMARKET_US_KEY_ID")
    build_client(make_config(secrets=secrets))

    assert wired["seen_refs"] == [secrets]


def test_create_wires_the_instrument_provider_with_discovery_config(
    wired: dict[str, Any],
) -> None:
    client = build_client(make_config())
    provider = client._instrument_provider

    assert isinstance(provider, PolymarketUSInstrumentProvider)
    assert provider._discovery.city_codes == ("nyc", "sfo", "mia", "mdw", "lax")
    assert provider.venue == POLYMARKET_US_VENUE


def test_create_wires_native_provider_load_all_for_discovery(
    wired: dict[str, Any],
) -> None:
    """The node calls InstrumentProvider.initialize(), so native load_all must be set."""
    client = build_client(make_config(instrument_provider=InstrumentProviderConfig()))
    provider = client._instrument_provider

    assert provider._load_all_on_start is True
    assert provider._load_ids_on_start is None


def test_create_preserves_an_explicit_native_provider_loading_config(
    wired: dict[str, Any],
) -> None:
    client = build_client(make_config(instrument_provider=InstrumentProviderConfig(load_all=True)))
    provider = client._instrument_provider

    assert provider._load_all_on_start is True


def test_create_passes_the_configured_user_agent_to_the_transport(
    wired: dict[str, Any],
) -> None:
    build_client(make_config())

    assert StubTransport.instances[0].default_headers["User-Agent"] == USER_AGENT


def test_create_never_reads_the_ingest_user_agent_variable() -> None:
    """S14: the adapter owns its User-Agent; ``BREEZY_USER_AGENT`` is ingest-only."""
    source = inspect.getsource(factories_module)

    assert "BREEZY_USER_AGENT" not in source


def test_create_budgets_the_transport_from_the_config_quotas(
    wired: dict[str, Any],
) -> None:
    build_client(make_config(http_timeout_secs=7, instrument_requests_per_minute=4))
    transport = StubTransport.instances[0]

    assert transport.timeout_secs == 7
    assert [key for key, _ in transport.keyed_quotas] == [
        "discovery",
        "instruments",
        "book",
        "portfolio",
    ]


def test_create_builds_a_markets_socket_bound_to_the_configured_url(
    wired: dict[str, Any],
) -> None:
    client = build_client(make_config())
    feed = client._feed

    # The venue caps subscriptions per connection (`websocket.py`
    # `MAX_SUBSCRIPTIONS_PER_CONNECTION`), so the factory wires a sharding
    # pool rather than a bare socket. Its first shard is a real
    # `PolymarketUSMarketsWebSocket`, built eagerly (never connected), so
    # every configuration assertion below still applies to it unchanged.
    assert isinstance(feed, PolymarketUSMarketsWebSocketPool)
    shard = feed._shards[0]
    assert isinstance(shard, PolymarketUSMarketsWebSocket)
    assert shard._ws_url == "wss://api.polymarket.us"


def test_create_signs_the_markets_socket_until_e1_is_measured(
    wired: dict[str, Any],
) -> None:
    """Plan section 5.3(a): the SDK signs the markets WS, so assume auth is required."""
    client = build_client(make_config())

    # Narrowed, not ignored: `requires_auth` is NOT on the `MarketsFeed`
    # Protocol (`data.py:132-156`), so asserting it through that static type
    # was asserting against a shape the Protocol never promised.
    feed = client._feed
    assert isinstance(feed, PolymarketUSMarketsWebSocketPool)
    shard = feed._shards[0]
    assert isinstance(shard, PolymarketUSMarketsWebSocket)
    assert shard.requires_auth is True


def test_create_wires_the_venue_quote_parser(wired: dict[str, Any]) -> None:
    client = build_client(make_config())

    assert client._quote_parser is parse_quote_tick


@pytest.mark.parametrize(
    ("variant", "expected"),
    [
        (SigningVariant.PATH_ONLY, build_canonical_path_without_query),
        (SigningVariant.PATH_WITH_QUERY, build_canonical_path_with_query),
    ],
)
def test_create_selects_the_builder_named_by_signing_variant(
    wired: dict[str, Any],
    variant: SigningVariant,
    expected: Any,
) -> None:
    client = build_client(make_config(signing_variant=variant))
    feed = client._feed
    assert isinstance(feed, PolymarketUSMarketsWebSocketPool)
    shard = feed._shards[0]
    assert isinstance(shard, PolymarketUSMarketsWebSocket)
    signer = shard._signer

    assert signer is not None
    assert signer._canonicalize is expected


def test_create_rejects_a_config_of_the_wrong_type(wired: dict[str, Any]) -> None:
    with pytest.raises(SettingsError, match="PolymarketUSDataClientConfig"):
        build_client("not-a-config")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Section 7 environment contract
# ---------------------------------------------------------------------------


def test_config_from_env_builds_the_documented_configuration() -> None:
    config = config_from_env(make_env())

    assert config.api_base_url == "https://api.polymarket.us"
    assert config.gateway_base_url == "https://gateway.polymarket.us"
    assert config.ws_url == "wss://api.polymarket.us"
    assert config.instrument_reload_interval_mins == 5
    assert config.user_agent == USER_AGENT
    assert config.signing_variant == SigningVariant.PATH_ONLY


def test_config_from_env_names_the_only_required_variable() -> None:
    """G-19: only the contact string is an operator input.

    The four venue-fact variables are optional overrides, so an empty
    environment must not accuse the operator of failing to supply them.
    """
    with pytest.raises(SettingsError) as excinfo:
        config_from_env({})

    message = str(excinfo.value)
    assert USER_AGENT_ENV_VAR in message
    for name in (
        API_BASE_ENV_VAR,
        GATEWAY_BASE_ENV_VAR,
        WS_URL_ENV_VAR,
        DISCOVERY_RELOAD_INTERVAL_ENV_VAR,
    ):
        assert name not in message


def test_config_from_env_rejects_a_non_integer_reload_interval() -> None:
    with pytest.raises(SettingsError):
        config_from_env(make_env(**{DISCOVERY_RELOAD_INTERVAL_ENV_VAR: "soon"}))


def test_config_from_env_rejects_a_non_positive_reload_interval() -> None:
    with pytest.raises(SettingsError):
        config_from_env(make_env(**{DISCOVERY_RELOAD_INTERVAL_ENV_VAR: "0"}))



def test_config_from_env_carries_no_secret_value() -> None:
    """S1: only environment variable NAMES may reach a NautilusConfig."""
    config = config_from_env(make_env())
    rendered = config.json().decode("utf-8")

    assert "POLYMARKET_US_KEY_ID" in rendered
    assert config.secrets.secret_key_file_env_var == "POLYMARKET_US_SECRET_KEY_FILE"


# ---------------------------------------------------------------------------
# Non-goals
# ---------------------------------------------------------------------------


def test_module_defines_no_execution_client_factory() -> None:
    source = inspect.getsource(factories_module)

    assert "LiveExecClientFactory" not in source
    assert "LiveExecutionClientFactory" not in source
