"""Unit tests for `breezy.runtime.node_config`.

These tests assert on the CONSTRUCTED config objects only. No `TradingNode`
is built and no event loop is started, so nothing here touches the network,
the filesystem, or the sibling-authored ingest Actor module.

The Actor is referenced by PATH STRING throughout (`ImportableActorConfig`),
which is why these tests pass without `breezy.ingest.nws_actor` existing:
`ActorFactory.create` resolves that string only when a real node is built.
"""

from __future__ import annotations

from pathlib import Path

import msgspec
import pytest
from nautilus_trader.common import Environment
from nautilus_trader.config import ImportableActorConfig, TradingNodeConfig
from nautilus_trader.model.identifiers import TraderId

from breezy.ingest.config import NwsIngestActorConfig
from breezy.runtime.node_config import (
    NWS_INGEST_ACTOR_CONFIG_PATH,
    NWS_INGEST_ACTOR_PATH,
    NodeConfigError,
    actor_component_id,
    build_actor_configs,
    build_node_config,
    validated_trader_id,
)
from breezy.runtime.settings import BreezyRuntimeSettings

ALL_SITES: tuple[tuple[str, str], ...] = (
    ("polymarket_us", "NYC"),
    ("polymarket_us", "SFO"),
    ("polymarket_us", "MIA"),
    ("polymarket_us", "MDW"),
    ("polymarket_us", "LAX"),
)


def make_settings(**overrides: object) -> BreezyRuntimeSettings:
    base: dict[str, object] = {
        "trader_id": "BREEZY-001",
        "sites": ALL_SITES,
        "catalog_base": Path("/srv/breezy/nws"),
        "state_db_path": Path("/srv/breezy/state/breezy-state.sqlite3"),
        "poll_interval_seconds": 300,
        "parse_timeout_ms": 250,
        "log_level": "INFO",
        "check_proxy_env": True,
        "registry_path": None,
    }
    base.update(overrides)
    return BreezyRuntimeSettings(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Actor configs
# ---------------------------------------------------------------------------


class TestBuildActorConfigs:
    def test_one_importable_actor_config_per_configured_site(self) -> None:
        configs = build_actor_configs(make_settings())

        assert len(configs) == len(ALL_SITES)
        assert all(isinstance(c, ImportableActorConfig) for c in configs)
        assert [(c.config["venue"], c.config["city"]) for c in configs] == list(ALL_SITES)

    def test_a_partial_site_set_yields_only_those_actors(self) -> None:
        configs = build_actor_configs(make_settings(sites=(("polymarket_us", "MIA"),)))

        assert len(configs) == 1
        assert configs[0].config["city"] == "MIA"

    def test_actor_and_config_are_referenced_by_colon_path_string(self) -> None:
        # A dotted path silently fails mid-run under `resolve_path`; the colon
        # form is the only one NautilusTrader 1.231.0 resolves reliably.
        assert NWS_INGEST_ACTOR_PATH == "breezy.ingest.nws_actor:NwsIngestActor"
        assert NWS_INGEST_ACTOR_CONFIG_PATH == "breezy.ingest.config:NwsIngestActorConfig"

        for config in build_actor_configs(make_settings()):
            assert config.actor_path == NWS_INGEST_ACTOR_PATH
            assert config.config_path == NWS_INGEST_ACTOR_CONFIG_PATH

    def test_building_configs_does_not_import_the_actor_module(self) -> None:
        # The whole point of the path-string indirection: this seam must build
        # while the Actor module is still being authored elsewhere.
        import sys

        sys.modules.pop("breezy.ingest.nws_actor", None)
        build_actor_configs(make_settings())
        assert "breezy.ingest.nws_actor" not in sys.modules

    def test_component_ids_are_unique_per_site(self) -> None:
        # ActorConfig.component_id defaults to None, which makes every Actor
        # take its class name as its id -- five identical ids, and
        # `Trader.add_actor` rejects the second one.
        ids = [c.config["component_id"] for c in build_actor_configs(make_settings())]

        assert len(set(ids)) == len(ALL_SITES)
        assert ids == [actor_component_id(v, c) for v, c in ALL_SITES]

    def test_actor_component_id_embeds_venue_and_city(self) -> None:
        assert actor_component_id("polymarket_us", "NYC") == "NWS-INGEST-polymarket_us-NYC"

    def test_payload_round_trips_through_the_real_actor_config_class(self) -> None:
        # `ActorFactory.create` msgspec-encodes `config` then `parse`s it into
        # the config class. Anything unserialisable or misnamed fails there,
        # at node build time, in production. Prove it round-trips here.
        for config in build_actor_configs(make_settings()):
            parsed = NwsIngestActorConfig.parse(msgspec.json.encode(config.config))
            assert isinstance(parsed, NwsIngestActorConfig)
            assert (parsed.venue, parsed.city) == (config.config["venue"], config.config["city"])

    def test_cadence_fields_come_from_settings_not_actor_defaults(self) -> None:
        settings = make_settings(poll_interval_seconds=45, parse_timeout_ms=900)

        for config in build_actor_configs(settings):
            parsed = NwsIngestActorConfig.parse(msgspec.json.encode(config.config))
            assert parsed.poll_interval_seconds == 45
            assert parsed.parse_timeout_ms == 900

    def test_no_deployment_path_leaks_into_the_actor_payload(self) -> None:
        # A Path on an ImportableActorConfig either fails to serialise or
        # silently diverges from the live object a later run reconstructs.
        settings = make_settings()
        for config in build_actor_configs(settings):
            for value in config.config.values():
                assert not isinstance(value, Path)
            assert str(settings.catalog_base) not in msgspec.json.encode(config.config).decode()
            assert str(settings.state_db_path) not in msgspec.json.encode(config.config).decode()


# ---------------------------------------------------------------------------
# Trader ID pre-validation
# ---------------------------------------------------------------------------


class TestValidatedTraderId:
    def test_accepts_a_well_formed_id(self) -> None:
        assert validated_trader_id("BREEZY-001") == TraderId("BREEZY-001")

    @pytest.mark.parametrize("bad", ["", "   ", "BREEZY", "-001", "BREEZY-", "BREEZY 001"])
    def test_rejects_a_malformed_id_before_nautilus_sees_it(self, bad: str) -> None:
        # MEASURED on nautilus-trader 1.231.0: `TraderId("bad")` does NOT raise
        # `ValueError` as its docstring (`model/identifiers.pyx:723-726`) claims.
        # It panics in Rust (`crates/model/src/identifiers/trader_id.rs:86`) and
        # ABORTS the process with SIGABRT (exit 134) -- uncatchable from Python.
        # A malformed `BREEZY_TRADER_ID` would therefore kill the process with a
        # Rust panic dump instead of a clear message, so this seam must refuse it
        # first. Never construct `TraderId` from unvalidated settings.
        with pytest.raises(NodeConfigError) as excinfo:
            validated_trader_id(bad)
        assert "trader_id" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Node config
# ---------------------------------------------------------------------------


class TestBuildNodeConfig:
    def test_returns_a_live_trading_node_config(self) -> None:
        config = build_node_config(make_settings())

        assert isinstance(config, TradingNodeConfig)
        assert config.environment == Environment.LIVE

    def test_registers_zero_catalogs_with_the_data_engine(self) -> None:
        # Measured platform finding F3: `DataEngine._query_catalog` breaks on
        # the first registered catalog that returns rows. `NautilusKernel`
        # registers one engine catalog per entry in `config.catalogs`
        # (`system/kernel.py:514-526`), so the ONLY safe count is zero.
        config = build_node_config(make_settings())

        assert config.catalogs == []

    def test_uses_no_redis_backed_cache_database(self) -> None:
        # `kernel.py:311-329`: 'redis' is the only cache database type the
        # kernel accepts; anything else raises. Breezy's durable state lives in
        # `SqliteStateStore`, so the cache database must stay None.
        config = build_node_config(make_settings())

        assert config.cache is not None
        assert config.cache.database is None
        assert config.cache.flush_on_start is False

    def test_uses_no_redis_backed_message_bus_database(self) -> None:
        assert build_node_config(make_settings()).message_bus is None

    def test_declares_no_data_or_exec_clients(self) -> None:
        # Ingestion is Actor-driven (polling HTTP), not DataClient-driven, and
        # this process trades nothing.
        config = build_node_config(make_settings())

        assert config.data_clients == {}
        assert config.exec_clients == {}

    def test_trader_id_comes_from_settings(self) -> None:
        config = build_node_config(make_settings(trader_id="BREEZY-042"))

        assert config.trader_id == TraderId("BREEZY-042")

    def test_malformed_trader_id_raises_node_config_error(self) -> None:
        with pytest.raises(NodeConfigError):
            build_node_config(make_settings(trader_id="nope"))

    def test_log_level_comes_from_settings(self) -> None:
        config = build_node_config(make_settings(log_level="DEBUG"))

        assert config.logging is not None
        assert config.logging.log_level == "DEBUG"

    def test_carries_one_actor_config_per_site(self) -> None:
        config = build_node_config(make_settings())

        assert len(config.actors) == len(ALL_SITES)
        assert config.actors == list(build_actor_configs(make_settings()))

    def test_no_deployment_value_is_hardcoded(self) -> None:
        a = build_node_config(make_settings(trader_id="BREEZY-001", log_level="INFO"))
        b = build_node_config(make_settings(trader_id="OTHER-999", log_level="WARNING"))

        assert a.trader_id != b.trader_id
        assert a.logging is not None
        assert b.logging is not None
        assert a.logging.log_level != b.logging.log_level
