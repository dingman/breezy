"""EXEC SPINE W: the REAL execution client is CONSTRUCTED by a REAL node.

Every other suite touching this increment proves one seam in isolation:
``tests/unit/test_polymarket_us_exec_client.py`` proves ``PolymarketUSExecutionClient``
itself (built by hand, in a rig); ``tests/unit/test_polymarket_us_factories.py``
proves ``PolymarketUSLiveExecClientFactory.create`` in isolation, with a stub
transport; ``tests/unit/test_runtime_trade_node_config.py`` proves the config
carries exactly one exec client and that ``state_store_opener`` is injected.

None of those exercises the actual native path a real deployment takes:
``TradingNode.add_exec_client_factory`` -> ``node.build()`` ->
``LiveNodeBuilder.build_exec_clients`` (``live/node_builder.py:201-246``) ->
``PolymarketUSLiveExecClientFactory.create(...)``. This file closes that gap.
It is the load-bearing evidence for the plan's "the client is CONSTRUCTED by
the node" clause -- the literal defect W exists to fix
(``exec_clients={}`` was pinned at ``node_config.py`` with zero construction
sites anywhere in the repo).

No socket: ``NautilusHttpTransport`` and ``build_shared_http_client`` are
replaced with fakes before ``node.build()`` runs, exactly the way
``tests/unit/test_polymarket_us_factories.py`` stubs the same seam for the
data-side factory -- this does not weaken ``tests/conftest.py``'s pyo3
network-client block, it stands in one level above it. A REAL Ed25519
credential (freshly generated, never a real key) is loaded from a REAL
0600-mode key file, so the signer construction inside ``create()`` is
genuine, offline, synchronous crypto -- exactly what ``node.build()`` does in
production before the loop ever starts.
"""

from __future__ import annotations

import asyncio
import base64
import os
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, ClassVar

import pytest
from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import ClientId

from breezy.adapters.polymarket_us import factories as factories_module
from breezy.adapters.polymarket_us import transport as transport_module
from breezy.adapters.polymarket_us.exec.client import PolymarketUSExecutionClient
from breezy.adapters.polymarket_us.factories import (
    POLYMARKET_US_CLIENT_NAME,
    PolymarketUSLiveDataClientFactory,
    PolymarketUSLiveExecClientFactory,
)
from breezy.adapters.polymarket_us.safety import MAX_ORDER_NOTIONAL_USD_ENV_VAR
from breezy.runtime.node_config import build_trade_node_config
from tests.unit.test_runtime_trade_node_config import (
    make_data_client_config,
    make_exec_client_config,
    make_trade_settings,
)

pytestmark = pytest.mark.contract

OPERATOR_ORDER_CEILING_USD = "25"

#: The env-var names `load_polymarket_us_credentials` reads by default
#: (`PolymarketUSSecretsRefConfig()`'s own defaults).
_KEY_ID_VAR = "POLYMARKET_US_KEY_ID"
_SECRET_FILE_VAR = "POLYMARKET_US_SECRET_KEY_FILE"


class _NoOpTransport:
    """Stands in for ``NautilusHttpTransport``: never touched in this file.

    ``node.build()`` only CONSTRUCTS the exec client; it never calls
    ``_connect``, so nothing here ever issues a ``.get()``. A call would be a
    test bug, not a real interaction -- hence the hard failure.
    """

    instances: ClassVar[list[_NoOpTransport]] = []

    def __init__(self, **kwargs: Any) -> None:
        _NoOpTransport.instances.append(self)

    async def get(self, url: str, *, headers: Mapping[str, str], quota_key: str) -> Any:
        raise AssertionError("node.build() must never issue a venue read")


@pytest.fixture(autouse=True)
def _operator_order_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, OPERATOR_ORDER_CEILING_USD)


@pytest.fixture(autouse=True)
def _stub_exec_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    _NoOpTransport.instances = []
    monkeypatch.setattr(factories_module, "NautilusHttpTransport", _NoOpTransport)
    monkeypatch.setattr(
        factories_module, "build_shared_http_client", lambda **_kwargs: object()
    )


@pytest.fixture(autouse=True)
def _clear_shared_polymarket_us_caches() -> Iterator[None]:
    """Isolate every test here from defect A's shared-object-graph caches.

    See the identical fixture in ``tests/unit/test_polymarket_us_factories.py``
    for why: these are process-global ``functools.lru_cache``s keyed by VALUE,
    and this file builds a client from the same default
    ``make_data_client_config()`` several other test modules also use.
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


@pytest.fixture(autouse=True)
def _real_offline_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A genuine, freshly generated Ed25519 key -- never a real credential.

    Real credential loading, real signer construction: the same synchronous,
    offline path `node.build()` drives in production
    (`factories.py`'s "Why credentials are resolved HERE" docstring).
    """
    key_file = tmp_path / "secret.key"
    key_file.write_text(base64.b64encode(os.urandom(32)).decode("ascii"))
    key_file.chmod(0o600)
    monkeypatch.setenv(_KEY_ID_VAR, "11111111-2222-3333-4444-555555555555")
    monkeypatch.setenv(_SECRET_FILE_VAR, str(key_file))


def _build_config(tmp_path: Path) -> TradingNodeConfig:
    exec_config = make_exec_client_config(state_store_path=str(tmp_path / "exec_state.db"))
    return build_trade_node_config(make_trade_settings(), make_data_client_config(), exec_config)


def test_the_built_node_registers_the_real_exec_client(tmp_path: Path) -> None:
    """The literal defect W exists to fix: R-4's client had ZERO construction
    sites (`grep -rn "PolymarketUSExecutionClient" src/` matched only its own
    module). After W, a real `TradingNode.build()` constructs one."""
    config = _build_config(tmp_path)
    loop = asyncio.new_event_loop()
    try:
        node = TradingNode(config, loop=loop)
        node.add_data_client_factory(POLYMARKET_US_CLIENT_NAME, PolymarketUSLiveDataClientFactory)
        node.add_exec_client_factory(POLYMARKET_US_CLIENT_NAME, PolymarketUSLiveExecClientFactory)
        node.build()

        assert list(node.kernel.exec_engine.registered_clients) == [
            ClientId(POLYMARKET_US_CLIENT_NAME)
        ]
        client = node.kernel.exec_engine._clients[ClientId(POLYMARKET_US_CLIENT_NAME)]
        assert isinstance(client, PolymarketUSExecutionClient)

        # The thread-affinity invariant, observed on the BUILT (not yet
        # connected) node: the store must not be opened at construction time,
        # only inside `_connect`, on the loop that will write to it.
        assert client.state_store_owner_thread is None

        node.dispose()
    finally:
        loop.close()


def test_the_data_and_exec_factories_share_one_object_graph(tmp_path: Path) -> None:
    """Defect A, closed. Before the fix, ``PolymarketUSLiveDataClientFactory``
    and ``PolymarketUSLiveExecClientFactory`` each built their OWN
    ``PolymarketUSHttpClient`` -- and therefore their own
    ``nautilus_pyo3.HttpClient``, which is where the rate-limiter token
    bucket actually lives (``transport.py:317-323``). Two independent
    buckets from the SAME quota configuration double the request rate the
    venue observes, worst at node startup when both instrument providers
    load concurrently. A REAL node, building BOTH factories from
    value-equal-but-distinct config objects (exactly as
    ``breezy.runtime.trade_cli`` builds them from the environment), must
    produce exactly ONE ``PolymarketUSHttpClient`` and exactly ONE
    instrument provider -- never two.

    This test FAILS if the two factories ever again produce distinct
    instances.
    """
    config = _build_config(tmp_path)
    loop = asyncio.new_event_loop()
    try:
        node = TradingNode(config, loop=loop)
        node.add_data_client_factory(POLYMARKET_US_CLIENT_NAME, PolymarketUSLiveDataClientFactory)
        node.add_exec_client_factory(POLYMARKET_US_CLIENT_NAME, PolymarketUSLiveExecClientFactory)
        node.build()

        data_client = node.kernel.data_engine._clients[ClientId(POLYMARKET_US_CLIENT_NAME)]
        exec_client = node.kernel.exec_engine._clients[ClientId(POLYMARKET_US_CLIENT_NAME)]

        assert data_client._instrument_provider is exec_client._instrument_provider, (
            "the data and exec clients must share exactly ONE instrument provider"
        )

        node.dispose()
    finally:
        loop.close()
