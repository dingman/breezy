"""EXEC SPINE R-2: the trading process's settings and node config.

Scope of the increment under test, stated so a later reader cannot mistake it:
this is CONFIG AND PROCESS ONLY. The trading process must start, reach
``RUNNING`` and stop cleanly while carrying **no execution client and no order
path at all**. Every assertion below that mentions execution is therefore an
assertion about ABSENCE, and it is deliberate rather than incidental.

Three things are pinned that a casual reading would treat as details:

* ``exec_clients``/``strategies``/``exec_algorithms`` are all empty. Each one
  alone is a route to ``submit_order``; the cage is the set, not any member.
* ``inflight_check_interval_ms == 0``. Polymarket.us has **no
  client-order-id**, so nothing that re-queries or re-resolves an order by id
  can be trusted here. Verified against the installed
  ``nautilus_trader/live/execution_engine.py``: ``0`` is the value that keeps
  the continuous-reconciliation task from ever being scheduled (``:383-386``)
  and that zeroes the in-flight branch inside it (``:574-575``, ``:591-592``,
  ``:648``).
* ``CacheConfig(database=None, flush_on_start=False)`` -- identical to both
  sibling builders, because the only accepted database type is Redis
  (``system/kernel.py:311-329``) and Breezy's durable state does not live in
  the Nautilus cache.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from nautilus_trader.common import Environment
from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.model.identifiers import TraderId

from breezy.adapters.polymarket_us.config import (
    PolymarketUSDataClientConfig,
    PolymarketUSExecClientConfig,
)
from breezy.adapters.polymarket_us.factories import POLYMARKET_US_CLIENT_NAME
from breezy.adapters.polymarket_us.safety import MAX_ORDER_NOTIONAL_USD_ENV_VAR
from breezy.runtime.node_config import NodeConfigError, build_trade_node_config
from breezy.runtime.settings import (
    TRADE_TRADER_ID_VAR,
    BreezyTradeSettings,
    SettingsError,
    load_trade_settings,
)

#: The environment a provisioned trading host carries. Venue values are
#: ``.invalid`` hosts: nothing in this file performs network I/O.
TRADE_ENV: dict[str, str] = {
    TRADE_TRADER_ID_VAR: "BREEZYTRADE-001",
}


def make_trade_settings(**overrides: object) -> BreezyTradeSettings:
    base: dict[str, object] = {
        "trader_id": "BREEZYTRADE-001",
        "log_level": "INFO",
    }
    base.update(overrides)
    return BreezyTradeSettings(**base)  # type: ignore[arg-type]


def make_data_client_config() -> PolymarketUSDataClientConfig:
    return PolymarketUSDataClientConfig(
        # Deliberate test-double origin off the venue domain.
        allow_foreign_origin=True,
        api_base_url="https://api.example.invalid",
        gateway_base_url="https://gateway.example.invalid",
        ws_url="wss://ws.example.invalid",
        instrument_reload_interval_mins=5,
        user_agent="breezy-test/1.0 (+mailto:ops@example.invalid)",
    )


def make_exec_client_config(**overrides: object) -> PolymarketUSExecClientConfig:
    """EXEC SPINE W. ``state_store_opener`` is left unset here on purpose --
    it is `build_trade_node_config`'s own job to inject it (see that
    function's docstring), and this helper's callers exist to test exactly
    that function.
    """
    base: dict[str, object] = {
        "venue": make_data_client_config(),
        "account_number": "001",
        "state_store_path": str(Path(tempfile.mkdtemp()) / "exec_state.db"),
    }
    base.update(overrides)
    return PolymarketUSExecClientConfig(**base)  # type: ignore[arg-type]


#: Test-local stand-in for the operator's per-order USD ceiling
#: (`BREEZY_MAX_ORDER_NOTIONAL_USD`). `build_trade_node_config` configures the
#: NATIVE per-order notional cap from that control and FAILS CLOSED when it is
#: absent, so every builder call in this module needs it present. The number is
#: arbitrary and test-local: it is not a production risk setting, and it is not
#: either operator-reserved control (max daily budget, max per position),
#: neither of which is read, defaulted or inferred anywhere on this path. The
#: refusal itself is covered by
#: `tests/contract/test_native_order_cap_wiring.py`, which is where it belongs.
OPERATOR_ORDER_CEILING_USD = "25"


@pytest.fixture(autouse=True)
def _operator_order_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(MAX_ORDER_NOTIONAL_USD_ENV_VAR, OPERATOR_ORDER_CEILING_USD)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class TestTradeSettings:
    def test_trader_id_is_required_with_no_default(self) -> None:
        # Unlike the collector and the recorder, the trading role has NO
        # fallback trader id. `TraderId` is stamped on every order and every
        # position this process will ever create; inheriting the collector's
        # shared `BREEZY-001` would make venue-side and log-side attribution
        # ambiguous, and would let a host provisioned only for weather ingest
        # start a trading process by accident.
        with pytest.raises(SettingsError) as excinfo:
            load_trade_settings({})

        assert TRADE_TRADER_ID_VAR in str(excinfo.value)

    def test_blank_trader_id_is_refused(self) -> None:
        with pytest.raises(SettingsError):
            load_trade_settings({TRADE_TRADER_ID_VAR: "   "})

    def test_trader_id_comes_from_the_trading_role_variable(self) -> None:
        assert load_trade_settings(TRADE_ENV).trader_id == "BREEZYTRADE-001"

    def test_the_collector_trader_id_does_not_satisfy_the_trading_role(self) -> None:
        with pytest.raises(SettingsError):
            load_trade_settings({"BREEZY_TRADER_ID": "BREEZY-001"})

    def test_log_level_is_read_and_validated(self) -> None:
        settings = load_trade_settings({**TRADE_ENV, "BREEZY_LOG_LEVEL": "DEBUG"})

        assert settings.log_level == "DEBUG"

        with pytest.raises(SettingsError):
            load_trade_settings({**TRADE_ENV, "BREEZY_LOG_LEVEL": "LOUD"})

    def test_needs_no_weather_collector_variables(self) -> None:
        assert "BREEZY_SITES" not in TRADE_ENV
        assert "BREEZY_CATALOG_BASE" not in TRADE_ENV

        assert load_trade_settings(TRADE_ENV).trader_id == "BREEZYTRADE-001"

    def test_carries_no_operator_reserved_control(self) -> None:
        # The two operator-reserved controls -- max DAILY budget and max PER
        # POSITION -- are added as mechanism in R-6 and are never given a value
        # anywhere in the repo. A settings object that carried a field for
        # either would be the place a default silently appeared.
        fields = set(BreezyTradeSettings.__dataclass_fields__)
        reserved = {"daily", "budget", "position", "notional", "max"}

        assert not any(word in name for name in fields for word in reserved), fields


# ---------------------------------------------------------------------------
# The node config
# ---------------------------------------------------------------------------


class TestTradeNodeConfig:
    def test_returns_a_live_trading_node_config(self) -> None:
        config = build_trade_node_config(
            make_trade_settings(), make_data_client_config(), make_exec_client_config()
        )

        assert isinstance(config, TradingNodeConfig)
        assert config.environment == Environment.LIVE

    def test_registers_exactly_the_read_only_data_client(self) -> None:
        config = build_trade_node_config(
            make_trade_settings(), make_data_client_config(), make_exec_client_config()
        )

        assert set(config.data_clients) == {POLYMARKET_US_CLIENT_NAME}

    def test_the_trade_node_config_registers_exactly_one_exec_client(self) -> None:
        """EXEC SPINE W. R-4's client had ZERO construction sites before this;
        the key equals `POLYMARKET_US_CLIENT_NAME` because the derived
        `AccountId` issuer (`exec/client.py:535-537`) is the one every other
        assumption keys on."""
        config = build_trade_node_config(
            make_trade_settings(), make_data_client_config(), make_exec_client_config()
        )

        assert set(config.exec_clients) == {POLYMARKET_US_CLIENT_NAME}

    def test_the_exec_client_config_state_store_opener_is_injected_here(self) -> None:
        """`exec_config_from_env` always leaves this `None` -- an `adapters`
        package may not import `SqliteStateStore` (`runtime` sits ABOVE
        `adapters`). This function is on the `runtime` side of that boundary
        and is where the real opener is threaded through, exactly the way
        `build_quote_tape_node_config` threads `recorder_instance_id`."""
        exec_config = make_exec_client_config()
        assert exec_config.state_store_opener is None  # the input is unfilled

        config = build_trade_node_config(
            make_trade_settings(), make_data_client_config(), exec_config
        )

        built = config.exec_clients[POLYMARKET_US_CLIENT_NAME]
        assert built.state_store_opener is not None
        assert callable(built.state_store_opener)

    def test_the_trade_node_config_still_declares_no_strategies_and_no_exec_algorithms(
        self,
    ) -> None:
        # W wires a client that RECONCILES and REFUSES; it does not make the
        # node able to ORIGINATE an order. `strategies=[]` removes the
        # component that calls `submit_order` (`trading/strategy.pyx`), and
        # `exec_algorithms=[]` removes the second, easily-missed route
        # (`execution/algorithm.pyx` carries `submit_order` in its own right).
        config = build_trade_node_config(
            make_trade_settings(), make_data_client_config(), make_exec_client_config()
        )

        assert config.strategies == []
        assert config.exec_algorithms == []

    def test_pins_the_inflight_check_interval_to_zero(self) -> None:
        # The venue has no client-order-id. `_check_inflight_orders`
        # (`live/execution_engine.py:701`) issues `QueryOrder` commands to
        # VERIFY -- it never resubmits -- but after
        # `inflight_check_retries` it calls `_resolve_inflight_order`, a
        # FALSE TERMINAL on an order we cannot query by id. Zero removes the
        # whole loop.
        config = build_trade_node_config(
            make_trade_settings(), make_data_client_config(), make_exec_client_config()
        )

        assert config.exec_engine is not None
        assert config.exec_engine.inflight_check_interval_ms == 0

    def test_starts_no_continuous_reconciliation_polling(self) -> None:
        # `live/execution_engine.py:383-386` schedules the continuous
        # reconciliation task if ANY of the three intervals is truthy. Pinning
        # the in-flight interval to zero is only half the statement; this
        # asserts the other two are absent too, so the task is never created.
        # If a Nautilus upgrade gives either a default, this fails loudly
        # rather than starting a poller nobody asked for.
        config = build_trade_node_config(
            make_trade_settings(), make_data_client_config(), make_exec_client_config()
        )

        assert config.exec_engine is not None
        assert config.exec_engine.open_check_interval_secs is None
        assert config.exec_engine.position_check_interval_secs is None

    def test_uses_no_redis_backed_cache_or_message_bus(self) -> None:
        config = build_trade_node_config(
            make_trade_settings(), make_data_client_config(), make_exec_client_config()
        )

        assert config.cache is not None
        assert config.cache.database is None
        assert config.cache.flush_on_start is False
        assert config.message_bus is None

    def test_declares_no_actors_and_registers_no_data_engine_catalogs(self) -> None:
        config = build_trade_node_config(
            make_trade_settings(), make_data_client_config(), make_exec_client_config()
        )

        assert config.actors == []
        assert config.catalogs == []

    def test_writes_no_tape(self) -> None:
        # The recorder streams; the trader does not. A second process writing
        # into the tape root would interleave two runs' feather files under
        # one catalog and make the recorded tape unattributable.
        config = build_trade_node_config(
            make_trade_settings(), make_data_client_config(), make_exec_client_config()
        )

        assert config.streaming is None

    def test_a_non_latch_submit_intent_latch_is_refused_at_config_build_time(
        self,
    ) -> None:
        """``PolymarketUSExecClientConfig.submit_intent_latch`` is typed
        ``object | None`` because ``adapters`` cannot import ``runtime``
        (`exec/client.py` duck-types it as ``self._latch: Any``). This
        function is on the ``runtime`` side of that boundary and CAN import
        the real type, so a caller-supplied object that is not a genuine,
        already-opened ``SubmitIntentLatch`` must be refused HERE -- before
        it is threaded onto the exec client config at all -- never silently
        accepted and duck-typed downstream."""
        with pytest.raises(NodeConfigError):
            build_trade_node_config(
                make_trade_settings(),
                make_data_client_config(),
                make_exec_client_config(),
                submit_intent_latch=object(),
            )

    def test_trader_id_comes_from_settings(self) -> None:
        config = build_trade_node_config(
            make_trade_settings(trader_id="BREEZYTRADE-042"),
            make_data_client_config(),
            make_exec_client_config(),
        )

        assert config.trader_id == TraderId("BREEZYTRADE-042")

    def test_malformed_trader_id_raises_node_config_error(self) -> None:
        with pytest.raises(NodeConfigError):
            build_trade_node_config(
                make_trade_settings(trader_id="nope"),
                make_data_client_config(),
                make_exec_client_config(),
            )

    def test_log_level_comes_from_settings(self) -> None:
        config = build_trade_node_config(
            make_trade_settings(log_level="WARNING"),
            make_data_client_config(),
            make_exec_client_config(),
        )

        assert config.logging is not None
        assert config.logging.log_level == "WARNING"

    def test_state_store_path_is_not_narrowed_by_a_bare_assert(self) -> None:
        """``assert`` is STRIPPED under ``python -O``; a narrowing that relies
        on it silently vanishes in an optimized interpreter and a ``None``
        could then flow into ``SqliteStateStore(None)``. Regression for the
        MEDIUM defect: ``state_store_path`` must be narrowed with ``cast(str,
        ...)`` (this file's own idiom, used twice elsewhere), never with a
        bare ``assert ... is not None``.
        """
        import ast
        import inspect

        from breezy.runtime import node_config

        source = inspect.getsource(node_config.build_trade_node_config)
        tree = ast.parse(source)
        assert_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
        assert assert_nodes == [], (
            "build_trade_node_config must not use a bare `assert` for "
            "type-narrowing (it is stripped under `python -O`); found: "
            f"{[ast.dump(node) for node in assert_nodes]}"
        )
