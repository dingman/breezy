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
from collections.abc import Iterator, Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any, ClassVar

import pytest
from nacl.signing import SigningKey
from nautilus_trader.common.component import LiveClock, MessageBus
from nautilus_trader.config import InstrumentProviderConfig
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.live.factories import LiveDataClientFactory, LiveExecClientFactory
from nautilus_trader.model.identifiers import ClientId, TraderId
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.adapters.polymarket_us import factories as factories_module
from breezy.adapters.polymarket_us import transport as transport_module
from breezy.adapters.polymarket_us.config import (
    PolymarketUSDataClientConfig,
    PolymarketUSExecClientConfig,
)
from breezy.adapters.polymarket_us.credentials import (
    PolymarketUSCredentials,
    PolymarketUSSecretsRefConfig,
)
from breezy.adapters.polymarket_us.data import PolymarketUSDataClient
from breezy.adapters.polymarket_us.exec.client import PolymarketUSExecutionClient
from breezy.adapters.polymarket_us.exec.endpoints import ACCOUNT_BALANCES_PATH
from breezy.adapters.polymarket_us.factories import (
    ACCOUNT_NUMBER_ENV_VAR,
    API_BASE_ENV_VAR,
    DISCOVERY_RELOAD_INTERVAL_ENV_VAR,
    EXEC_STATE_DB_ENV_VAR,
    GATEWAY_BASE_ENV_VAR,
    USER_AGENT_ENV_VAR,
    WS_URL_ENV_VAR,
    PolymarketUSLiveDataClientFactory,
    PolymarketUSLiveExecClientFactory,
    config_from_env,
    exec_config_from_env,
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
from breezy.adapters.polymarket_us.write_transport import PolymarketUSWriteTransport
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
        client: Any,
        permitted_quota_keys: frozenset[str] | None = None,
    ) -> None:
        self.client = client
        self.permitted_quota_keys = permitted_quota_keys
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


@pytest.fixture(autouse=True)
def _clear_shared_polymarket_us_caches() -> Iterator[None]:
    """Isolate every test from defect A's fix.

    ``_shared_polymarket_us_signer``/``_transport``/``_http_client``/
    ``_instrument_provider`` are process-global ``functools.lru_cache``s,
    keyed by VALUE on ``PolymarketUSDataClientConfig`` -- deliberately, so
    the data and exec factories share one object graph (defect A). Many
    tests in this module build a client from an equal-valued default config
    (``make_config()``), so without clearing these between tests the SECOND
    such test would silently receive the FIRST test's cached -- and
    differently stubbed -- object graph instead of building its own.
    """
    factories_module._shared_polymarket_us_signer.cache_clear()
    factories_module._shared_polymarket_us_transport.cache_clear()
    factories_module._shared_polymarket_us_http_client.cache_clear()
    factories_module._shared_polymarket_us_instrument_provider.cache_clear()
    transport_module.build_shared_http_client._reset_for_tests()
    yield
    factories_module._shared_polymarket_us_signer.cache_clear()
    factories_module._shared_polymarket_us_transport.cache_clear()
    factories_module._shared_polymarket_us_http_client.cache_clear()
    factories_module._shared_polymarket_us_instrument_provider.cache_clear()
    transport_module.build_shared_http_client._reset_for_tests()


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Patch the two collaborators that would otherwise open a real socket."""
    StubTransport.instances = []
    calls: list[str] = []
    loop_states: list[bool] = []
    credentials = make_credentials()
    seen_refs: list[PolymarketUSSecretsRefConfig] = []
    factory_calls: list[dict[str, Any]] = []

    def fake_shared_client(**kwargs: Any) -> object:
        factory_calls.append(kwargs)
        return object()

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
    monkeypatch.setattr(factories_module, "build_shared_http_client", fake_shared_client)
    monkeypatch.setattr(factories_module, "load_polymarket_us_credentials", fake_loader)
    return {
        "calls": calls,
        "loop_states": loop_states,
        "credentials": credentials,
        "seen_refs": seen_refs,
        "factory_calls": factory_calls,
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

    assert wired["factory_calls"][0]["default_headers"]["User-Agent"] == USER_AGENT


def test_create_never_reads_the_ingest_user_agent_variable() -> None:
    """S14: the adapter owns its User-Agent; ``BREEZY_USER_AGENT`` is ingest-only."""
    source = inspect.getsource(factories_module)

    assert "BREEZY_USER_AGENT" not in source


def test_create_budgets_the_transport_from_the_config_quotas(
    wired: dict[str, Any],
) -> None:
    build_client(make_config(http_timeout_secs=7, instrument_requests_per_minute=4))
    call = wired["factory_calls"][0]

    assert call["timeout_secs"] == 7
    assert [key for key, _ in call["keyed_quotas"]] == [
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
# EXEC SPINE W -- PolymarketUSLiveExecClientFactory
# ---------------------------------------------------------------------------

ACCOUNT_NUMBER = "acct-001"


def make_exec_config(tmp_path: Path, **overrides: Any) -> PolymarketUSExecClientConfig:
    kwargs: dict[str, Any] = {
        "venue": make_config(),
        "account_number": ACCOUNT_NUMBER,
        "state_store_path": str(tmp_path / "exec_state.db"),
        # Never opened by `create()` itself -- see the class docstring -- but
        # `PolymarketUSExecutionClient.__init__` requires a callable.
        "state_store_opener": lambda: pytest.fail(  # pragma: no cover - never called here
            "the factory must never open the store; only _connect may"
        ),
    }
    kwargs.update(overrides)
    return PolymarketUSExecClientConfig(**kwargs)


def build_exec_client(
    config: PolymarketUSExecClientConfig,
    *,
    name: str = CLIENT_NAME,
) -> PolymarketUSExecutionClient:
    clock = LiveClock()
    trader_id = TraderId("SMOKE-001")
    msgbus = MessageBus(trader_id=trader_id, clock=clock)
    cache = TestComponentStubs.cache()
    loop = asyncio.new_event_loop()
    try:
        return PolymarketUSLiveExecClientFactory.create(
            loop=loop,
            name=name,
            config=config,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
        )
    finally:
        loop.close()


def test_exec_factory_subclasses_the_native_base_and_create_is_a_staticmethod() -> None:
    """``add_exec_client_factory`` takes the CLASS, exactly as the data side."""
    assert issubclass(PolymarketUSLiveExecClientFactory, LiveExecClientFactory)
    raw = inspect.getattr_static(PolymarketUSLiveExecClientFactory, "create")
    assert isinstance(raw, staticmethod)


def test_exec_create_derives_the_client_id_and_venue(tmp_path: Path, wired: dict[str, Any]) -> None:
    client = build_exec_client(make_exec_config(tmp_path))

    assert client.id == ClientId(CLIENT_NAME)
    assert client.venue == POLYMARKET_US_VENUE
    assert isinstance(client, PolymarketUSExecutionClient)


def test_exec_create_derives_the_account_id_from_account_number(
    tmp_path: Path, wired: dict[str, Any]
) -> None:
    """OQ-I: `account_number` is the ONLY source of the `AccountId` suffix."""
    client = build_exec_client(make_exec_config(tmp_path, account_number="9999"))

    assert repr(client).endswith("refusals=0)")
    assert f"{CLIENT_NAME}-9999" in repr(client)


def test_exec_create_never_opens_the_injected_store(tmp_path: Path, wired: dict[str, Any]) -> None:
    """The opener is forwarded, never called -- construction happens off the
    main thread, inside `_connect`, on the execution engine's own loop."""
    client = build_exec_client(make_exec_config(tmp_path))

    assert client.state_store_owner_thread is None


def test_exec_create_forwards_the_timeouts(tmp_path: Path, wired: dict[str, Any]) -> None:
    client = build_exec_client(
        make_exec_config(
            tmp_path, instrument_wait_timeout_s=12.0, account_registration_timeout_s=34.0
        )
    )

    assert client._instrument_wait_timeout_s == 12.0
    assert client._account_registration_timeout_s == 34.0


def test_exec_create_rejects_a_config_of_the_wrong_type(wired: dict[str, Any]) -> None:
    with pytest.raises(SettingsError, match="PolymarketUSExecClientConfig"):
        build_exec_client("not-a-config")  # type: ignore[arg-type]


def test_exec_create_rejects_a_config_with_no_store_opener(
    tmp_path: Path, wired: dict[str, Any]
) -> None:
    """`exec_config_from_env` always leaves this unset (layer contract); only
    `build_trade_node_config` may fill it in. A config that reaches the
    factory unset means that injection was skipped."""
    config = make_exec_config(tmp_path, state_store_opener=None)

    with pytest.raises(SettingsError, match="state_store_opener"):
        build_exec_client(config)


def test_exec_create_wires_its_own_instrument_provider(
    tmp_path: Path, wired: dict[str, Any]
) -> None:
    client = build_exec_client(make_exec_config(tmp_path))
    provider = client._instrument_provider

    assert isinstance(provider, PolymarketUSInstrumentProvider)
    assert provider.venue == POLYMARKET_US_VENUE


def test_exec_create_wires_the_live_write_transport_when_canonical_verified(
    tmp_path: Path, wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """C5: with the flip landed (``write_transport.py:48`` now True), the
    factory binds the live sender at construction time. Patched in the
    factories module's own namespace since ``WRITE_CANONICAL_STRING_VERIFIED``
    is read there via a ``from``-import (``factories.py:102``, ``:725``).
    """
    monkeypatch.setattr(factories_module, "WRITE_CANONICAL_STRING_VERIFIED", True)

    client = build_exec_client(make_exec_config(tmp_path))

    assert isinstance(client._order_sender, PolymarketUSWriteTransport)


def test_exec_create_wires_no_order_sender_when_canonical_unverified(
    tmp_path: Path, wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Companion to the above: the blocking controls from here on are
    ``order_enablement.py``'s permit preconditions, ``safety.py``'s
    live-trading permit, the operator caps, and the exact-``"1"``
    enablement variable -- this flag no longer gates a fresh factory build
    once it is True, so the False branch must be forced to prove it still
    declines to wire a sender.
    """
    monkeypatch.setattr(factories_module, "WRITE_CANONICAL_STRING_VERIFIED", False)

    client = build_exec_client(make_exec_config(tmp_path))

    assert client._order_sender is None


class RecordingTransport:
    """Records every GET this factory's `private_read` closure issues."""

    instances: ClassVar[list[RecordingTransport]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.calls: list[dict[str, Any]] = []
        RecordingTransport.instances.append(self)

    async def get(self, url: str, *, headers: Mapping[str, str], quota_key: str) -> Any:
        self.calls.append({"url": url, "headers": dict(headers), "quota_key": quota_key})
        from breezy.adapters.polymarket_us.transport import VenueResponse

        body = (
            b'{"balances": [{"currency": "USD", "currentBalance": 4242.42, '
            b'"buyingPower": 4242.42, "lastUpdated": "2026-09-02T00:00:00Z"}]}'
        )
        return VenueResponse(status=200, headers={}, body=body)


def test_the_wired_private_read_signs_exactly_one_get_over_the_bare_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, wired: dict[str, Any]
) -> None:
    """The GET-only guarantee lives HERE (class docstring): no `query`
    parameter exists on the closure at all, so the signed string and the
    fetched URL can never drift apart."""
    RecordingTransport.instances = []
    monkeypatch.setattr(factories_module, "NautilusHttpTransport", RecordingTransport)
    client = build_exec_client(make_exec_config(tmp_path))

    payload = asyncio.run(client._private_read(ACCOUNT_BALANCES_PATH))

    assert len(RecordingTransport.instances) == 1
    recorded = RecordingTransport.instances[0].calls
    assert len(recorded) == 1
    assert recorded[0]["url"].endswith(ACCOUNT_BALANCES_PATH)
    assert "?" not in recorded[0]["url"], "no query string may ever reach a signed private read"
    # Decimal-preserving decode (`decode_private_payload`), not the plain
    # `json.loads` `PolymarketUSHttpClient._decode` would have used.
    balance = payload["balances"][0]
    assert isinstance(balance["currentBalance"], Decimal)
    assert balance["currentBalance"] == Decimal("4242.42")


def test_the_wired_private_read_has_no_query_parameter_in_its_signature(
    tmp_path: Path, wired: dict[str, Any]
) -> None:
    """Non-vacuity for the test above, at the signature rather than the call:
    a query CANNOT be smuggled in because the closure accepts none."""
    client = build_exec_client(make_exec_config(tmp_path))

    params = inspect.signature(client._private_read).parameters
    assert list(params) == ["path"]


# ---------------------------------------------------------------------------
# R-6.5b-0 -- shared HttpClient injected into the read transport
# ---------------------------------------------------------------------------


_REPO_ROOT = Path(__file__).resolve().parents[2]
_FACTORIES_MODULE_PATH = "src/breezy/adapters/polymarket_us/factories.py"


def test_shared_transport_injects_the_client_from_the_factory(
    wired: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """R-6.5b-0: ``_shared_polymarket_us_transport`` injects the factory client."""
    sentinel = object()
    monkeypatch.setattr(
        factories_module, "build_shared_http_client", lambda **_kwargs: sentinel
    )
    build_client(make_config())

    assert StubTransport.instances[0].client is sentinel


def test_factories_module_has_no_write_egress() -> None:
    """R-6.5b-0 RED 7 / L-15: B4 on factories.py is empty (pin; may already pass)."""
    from tests.unit.test_polymarket_us_readonly_guard import find_write_egress_violations

    source = (_REPO_ROOT / _FACTORIES_MODULE_PATH).read_text(encoding="utf-8")
    assert find_write_egress_violations(_FACTORIES_MODULE_PATH, source) == []


# ---------------------------------------------------------------------------
# EXEC SPINE W -- exec_config_from_env
# ---------------------------------------------------------------------------


def make_exec_env(tmp_path: Path, **overrides: str) -> dict[str, str]:
    env = make_env()
    env[ACCOUNT_NUMBER_ENV_VAR] = ACCOUNT_NUMBER
    env[EXEC_STATE_DB_ENV_VAR] = str(tmp_path / "exec_state.db")
    env.update(overrides)
    return env


def test_exec_config_from_env_builds_the_documented_configuration(tmp_path: Path) -> None:
    config = exec_config_from_env(make_exec_env(tmp_path))

    assert config.account_number == ACCOUNT_NUMBER
    assert config.state_store_path == str(tmp_path / "exec_state.db")
    assert config.state_store_opener is None, "only build_trade_node_config may inject this"
    assert config.venue is not None
    assert config.venue.user_agent == USER_AGENT


def test_exec_config_from_env_names_account_number_with_no_default(tmp_path: Path) -> None:
    """OQ-I: zero producers anywhere else -- this is the ONLY source."""
    env = make_exec_env(tmp_path)
    del env[ACCOUNT_NUMBER_ENV_VAR]

    with pytest.raises(SettingsError) as excinfo:
        exec_config_from_env(env)

    assert ACCOUNT_NUMBER_ENV_VAR in str(excinfo.value)


def test_exec_config_from_env_account_number_is_stable_across_a_restart(tmp_path: Path) -> None:
    """OQ-I's stability half: the source is a static environment variable,
    read fresh each call, never generated -- so two 'restarts' against the
    SAME operator configuration must agree byte-for-byte."""
    env = make_exec_env(tmp_path)

    first = exec_config_from_env(env)
    second = exec_config_from_env(dict(env))  # a fresh mapping, same content

    assert first.account_number == second.account_number == ACCOUNT_NUMBER


def test_exec_config_from_env_names_the_state_db_with_no_default(tmp_path: Path) -> None:
    env = make_exec_env(tmp_path)
    del env[EXEC_STATE_DB_ENV_VAR]

    with pytest.raises(SettingsError) as excinfo:
        exec_config_from_env(env)

    assert EXEC_STATE_DB_ENV_VAR in str(excinfo.value)


def test_exec_config_from_env_rejects_a_relative_state_db_path(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="absolute"):
        exec_config_from_env(make_exec_env(tmp_path, **{EXEC_STATE_DB_ENV_VAR: "relative/path.db"}))


def test_exec_config_from_env_rejects_a_dotdot_segment(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match=r"\.\."):
        exec_config_from_env(
            make_exec_env(tmp_path, **{EXEC_STATE_DB_ENV_VAR: str(tmp_path / ".." / "exec.db")})
        )


def test_exec_config_from_env_reuses_config_from_env_for_shared_venue_facts(
    tmp_path: Path,
) -> None:
    """Not a second, competing environment policy -- verified rather than
    merely asserted: the same override that moves the data client's origin
    moves the exec client's."""
    env = make_exec_env(tmp_path, **{API_BASE_ENV_VAR: "https://staging.example.invalid"})

    exec_cfg = exec_config_from_env({**env, "POLYMARKET_US_ALLOW_FOREIGN_ORIGIN": "1"})

    assert exec_cfg.venue is not None
    assert exec_cfg.venue.api_base_url == "https://staging.example.invalid"


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


def test_the_data_client_factory_itself_defines_no_execution_surface() -> None:
    """R-2's boundary, narrowed rather than deleted at EXEC SPINE W.

    Before W, no execution-client factory existed anywhere in this module and
    this test asserted that absence directly. W adds exactly ONE --
    ``PolymarketUSLiveExecClientFactory``, covered by its own suite below --
    so the property worth keeping is narrower: the DATA client factory class
    itself still defines no ``create`` beyond the one native contract
    declares, and still never touches ``exec_clients``/``submit_order``.
    """
    source = inspect.getsource(PolymarketUSLiveDataClientFactory)

    assert "LiveExecClientFactory" not in source
    assert "LiveExecutionClientFactory" not in source
    assert "submit_order" not in source
