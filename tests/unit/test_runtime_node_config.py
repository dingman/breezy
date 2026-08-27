"""Unit tests for `breezy.runtime.node_config`.

These tests assert on the CONSTRUCTED config objects only. No `TradingNode`
is built and no event loop is started, so nothing here touches the network,
the filesystem, or the sibling-authored ingest Actor module.

The ingest Actors are deliberately NOT declared in this config: they need a
live `SharedIngestState`, which `ActorFactory.create` (`actor_cls(config)`,
`common/config.py:614`) has no seam for. They are constructed and registered by
`breezy.runtime.composition` through the native `Trader.add_actor`. These tests
therefore assert the config declares ZERO actors, and never import
`breezy.ingest.nws_actor`.
"""

from __future__ import annotations

import ast
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
    build_node_config,
    validated_trader_id,
)
from breezy.runtime.settings import BreezyRuntimeSettings

#: Read as SOURCE by `TestTheReadOnlyCageIsDeclaredNotDefaulted`.
NODE_CONFIG_SOURCE = (
    Path(__file__).resolve().parents[2] / "src" / "breezy" / "runtime" / "node_config.py"
)

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


class TestActorsAreNotRegisteredByConfig:
    """REPLACES `TestBuildActorConfigs`.

    `build_actor_configs` produced one `ImportableActorConfig` per site. That
    route cannot work for this Actor: `ActorFactory.create` ends in
    `actor_cls(config)` (`common/config.py:614`) -- one positional argument,
    round-tripped through JSON -- while `NwsIngestActor.__init__` requires a
    live `SharedIngestState`. The Actors are now constructed and registered by
    `breezy.runtime.composition.build_ingest_node` through the native
    `Trader.add_actor` (`trading/trader.py:312`); see
    `tests/unit/test_runtime_actor_wiring.py`, which took over the
    per-site-count, component-id and cadence assertions.
    """

    def test_the_node_config_declares_no_actors(self) -> None:
        config = build_node_config(make_settings())

        assert config.actors == []

    def test_the_importable_route_is_not_used_for_any_site(self) -> None:
        for sites in (ALL_SITES, (("polymarket_us", "MIA"),)):
            config = build_node_config(make_settings(sites=sites))
            assert not any(
                isinstance(a, ImportableActorConfig) and a.actor_path == NWS_INGEST_ACTOR_PATH
                for a in config.actors
            )

    def test_build_actor_configs_is_gone(self) -> None:
        """It must not come back: an `ImportableActorConfig` for this Actor
        would fail at node-build time, in production, with a TypeError about a
        missing `shared` argument.
        """
        from breezy.runtime import node_config

        assert not hasattr(node_config, "build_actor_configs")

    def test_the_colon_paths_are_retained_as_names_only(self) -> None:
        # Kept so tests (and humans) can assert the importable route is NOT in
        # use. A dotted path would fail mid-run under `resolve_path`; the colon
        # form is the only one NautilusTrader 1.231.0 resolves reliably.
        assert NWS_INGEST_ACTOR_PATH == "breezy.ingest.nws_actor:NwsIngestActor"
        assert NWS_INGEST_ACTOR_CONFIG_PATH == "breezy.ingest.config:NwsIngestActorConfig"

    def test_building_the_node_config_does_not_import_the_actor_module(self) -> None:
        # Still true, and still worth keeping: this seam must build without
        # dragging in the Actor module and its heavyweight imports.
        import sys

        # The eviction MUST be restored. Leaving it popped lets a later import
        # build a SECOND module object with its own `__dict__` while
        # `composition.py:39` still holds the first -- so string-form
        # `monkeypatch.setattr("breezy.ingest.nws_actor....")` patches a module
        # nobody is executing. That produced a real 1-in-3 order-dependent
        # failure in the PostSettlementRevision alert test, which passed in
        # isolation and failed only when this test ran first. The assertion
        # below is unchanged; only the cleanup is added.
        saved = sys.modules.pop("breezy.ingest.nws_actor", None)
        try:
            build_node_config(make_settings())
            assert "breezy.ingest.nws_actor" not in sys.modules
        finally:
            if saved is not None:
                sys.modules["breezy.ingest.nws_actor"] = saved

    def test_actor_component_id_embeds_venue_and_city(self) -> None:
        # Still owned here: `build_ingest_actors` calls this function to keep
        # five same-class Actors from colliding inside `Trader.add_actor`.
        assert actor_component_id("polymarket_us", "NYC") == "NWS-INGEST-polymarket_us-NYC"

    def test_component_ids_are_unique_per_site(self) -> None:
        ids = [actor_component_id(v, c) for v, c in ALL_SITES]

        assert len(set(ids)) == len(ALL_SITES)

    def test_the_actor_config_class_still_accepts_the_payload_shape(self) -> None:
        # `build_ingest_actors` constructs `NwsIngestActorConfig` directly now,
        # so the msgspec round-trip is no longer on the production path -- but
        # the field names it passes must still be the real ones.
        parsed = NwsIngestActorConfig.parse(
            msgspec.json.encode(
                {
                    "component_id": actor_component_id("polymarket_us", "NYC"),
                    "venue": "polymarket_us",
                    "city": "NYC",
                    "poll_interval_seconds": 45,
                    "parse_timeout_ms": 900,
                }
            )
        )

        assert isinstance(parsed, NwsIngestActorConfig)
        assert (parsed.venue, parsed.city) == ("polymarket_us", "NYC")
        assert parsed.poll_interval_seconds == 45
        assert parsed.parse_timeout_ms == 900


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

    def test_declares_no_data_clients_exec_clients_strategies_or_exec_algorithms(
        self,
    ) -> None:
        # Ingestion is Actor-driven (polling HTTP), not DataClient-driven, and
        # this process trades nothing.
        #
        # `strategies` is the OTHER half of the read-only cage and was
        # unguarded until 2026-08-27. `exec_clients={}` alone removes the
        # venue-facing transport; a registered `Strategy` is what would call
        # `submit_order` in the first place (`trading/strategy.pyx`), and the
        # kernel instantiates every entry in `strategies` unconditionally
        # (`system/kernel.py`). Pinning one without the other pins half a pair.
        #
        # `exec_algorithms` is the THIRD field of that pair, added 2026-08-27.
        # `ExecAlgorithm` subclasses `Actor` but carries the order-submission
        # surface a Strategy has -- `submit_order`, `modify_order`,
        # `cancel_order` (`execution/algorithm.pyx`) -- and the kernel builds
        # every entry via `ExecAlgorithmFactory.create` on the same
        # unconditional path as `strategies`. A cage that names two of the
        # three leaves the third as an unreviewed route to an execution path.
        config = build_node_config(make_settings())

        assert config.data_clients == {}
        assert config.exec_clients == {}
        assert config.strategies == []
        assert config.exec_algorithms == []

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

    def test_carries_no_actor_configs(self) -> None:
        # See `TestActorsAreNotRegisteredByConfig` for why this is zero and not
        # one-per-site.
        config = build_node_config(make_settings())

        assert config.actors == []

    def test_no_deployment_value_is_hardcoded(self) -> None:
        a = build_node_config(make_settings(trader_id="BREEZY-001", log_level="INFO"))
        b = build_node_config(make_settings(trader_id="OTHER-999", log_level="WARNING"))

        assert a.trader_id != b.trader_id
        assert a.logging is not None
        assert b.logging is not None
        assert a.logging.log_level != b.logging.log_level


# ---------------------------------------------------------------------------
# The read-only cage is DECLARED, not defaulted
# ---------------------------------------------------------------------------


def _node_config_calls() -> list[ast.Call]:
    """Every `TradingNodeConfig(...)` construction in `runtime.node_config`.

    Read from source rather than from a built object: `strategies == []` is
    also what an unconfigured `TradingNodeConfig()` returns, so a runtime
    assertion cannot distinguish "declared empty" from "never considered".
    Only the source can.
    """
    tree = ast.parse(NODE_CONFIG_SOURCE.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "TradingNodeConfig"
    ]


def _empty_literal_keywords(call: ast.Call) -> set[str]:
    """Keyword names in `call` bound to an empty list or dict literal."""
    return {
        kw.arg
        for kw in call.keywords
        if kw.arg is not None
        and isinstance(kw.value, ast.List | ast.Dict)
        and not getattr(kw.value, "elts", [])
        and not getattr(kw.value, "keys", [])
    }


class TestTheReadOnlyCageIsDeclaredNotDefaulted:
    """Both halves of the execution cage are stated at every build site.

    `exec_clients={}` has always been explicit here; `strategies` was left to
    the Nautilus default. That asymmetry is the defect: a default is invisible
    in review and silently follows upstream if it ever changes, while the
    fields are one set -- a `Strategy` is the caller of `submit_order`, and
    an `ExecClient` is what carries the call to a venue. Any one alone is
    enough to make the others harmless; none being declared is how a
    read-only process stops being read-only without anyone editing a line that
    mentions execution.

    `exec_algorithms` is the third member of that set and was unpinned until
    2026-08-27. It is NOT redundant with `strategies`: an `ExecAlgorithm`
    reaches `submit_order` in its own right (`execution/algorithm.pyx`), so a
    config carrying `strategies=[]` and a populated `exec_algorithms` is a
    read-only process that can trade.
    """

    def test_the_repo_builds_exactly_the_node_configs_this_rule_covers(self) -> None:
        # Guards the rule against silently going vacuous if a build site moves.
        assert len(_node_config_calls()) == 2

    @pytest.mark.parametrize("field", ["exec_clients", "strategies", "exec_algorithms"])
    def test_every_node_config_declares_the_field_empty(self, field: str) -> None:
        for call in _node_config_calls():
            assert field in _empty_literal_keywords(call), (
                f"{NODE_CONFIG_SOURCE.name}:{call.lineno}: TradingNodeConfig(...) does not "
                f"declare `{field}` as an empty literal"
            )
