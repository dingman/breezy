"""Tests for how the ingest Actors actually reach their `SharedIngestState`.

The defect this pins
--------------------
`node_config.py` registered the Actor through ``ImportableActorConfig``.
``ActorFactory.create`` ends in ``actor_cls(config)``
(``nautilus_trader/common/config.py:614``) -- exactly one positional argument.
But ``NwsIngestActor.__init__`` is ``(config, *, shared: SharedIngestState,
...)`` with ``shared`` REQUIRED, and `shared_state.py` deliberately exposes no
module-level ``current()`` accessor (a global getter is how a second, unnoticed
component graph gets built). So the config-driven path could never construct
our Actor at all.

The native fix, verified against the installed nautilus-trader 1.231.0:

* ``Trader.add_actor(actor: Actor)`` -- ``trading/trader.py:312``
  (``add_actors`` at ``:355``) takes an already-constructed Actor instance.
* ``TradingNode.trader`` -- ``live/node.py:139`` -- exposes it, and
  ``TradingNode.__init__`` builds the kernel (and therefore the trader) before
  ``build()`` is ever called (``live/node.py:71-75``).

So the composition root constructs each Actor itself with ``shared=`` injected
and registers it natively. Nothing in Nautilus is modified, subclassed around,
or reimplemented, and no DI container or service locator is introduced.

No test here calls ``TradingNode.run()`` or opens a socket.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from breezy.ingest.nws_actor import NwsIngestActor
from breezy.persistence.catalog import FilesystemLocality, FilesystemProbe
from breezy.runtime.composition import (
    BreezyIngestRuntime,
    build_ingest_actors,
    build_ingest_node,
    ingest_runtime,
)
from breezy.runtime.node_config import NWS_INGEST_ACTOR_PATH, actor_component_id
from breezy.runtime.settings import BreezyRuntimeSettings

SITES: tuple[tuple[str, str], ...] = (("polymarket_us", "NYC"), ("polymarket_us", "LAX"))


def _local_probe(path: Path) -> FilesystemProbe:
    return FilesystemProbe(
        path=str(path),
        mount_point="/",
        fs_type="ext4",
        locality=FilesystemLocality.LOCAL,
        detail="fake probe",
    )


@pytest.fixture
def settings(tmp_path: Path) -> BreezyRuntimeSettings:
    return BreezyRuntimeSettings(
        trader_id="BREEZY-001",
        sites=SITES,
        catalog_base=tmp_path / "catalog",
        state_db_path=tmp_path / "state" / "breezy.sqlite3",
        poll_interval_seconds=300,
        parse_timeout_ms=250,
        log_level="INFO",
        check_proxy_env=False,
        registry_path=None,
    )


@pytest.fixture
def runtime(settings: BreezyRuntimeSettings) -> Iterator[BreezyIngestRuntime]:
    with ingest_runtime(settings, probe=_local_probe) as rt:
        yield rt


class RecordingTrader:
    def __init__(self) -> None:
        self.actors: list[Any] = []

    def add_actor(self, actor: Any) -> None:
        self.actors.append(actor)


class RecordingNode:
    """The `TradingNode` surface `build_ingest_node` is allowed to touch."""

    def __init__(self, config: Any) -> None:
        self.config = config
        self.trader = RecordingTrader()


# ---------------------------------------------------------------------------
# The node config no longer tries to build our Actor from a config path
# ---------------------------------------------------------------------------


def test_the_node_config_registers_no_importable_ingest_actor(
    runtime: BreezyIngestRuntime,
) -> None:
    paths = [a.actor_path for a in runtime.node_config.actors]
    assert NWS_INGEST_ACTOR_PATH not in paths
    assert runtime.node_config.actors == []


# ---------------------------------------------------------------------------
# Actors are constructed with `shared=` injected
# ---------------------------------------------------------------------------


def test_one_actor_is_built_per_configured_site(runtime: BreezyIngestRuntime) -> None:
    actors = build_ingest_actors(runtime)

    assert len(actors) == len(SITES)
    assert all(isinstance(a, NwsIngestActor) for a in actors)


def test_every_actor_receives_the_one_shared_state(runtime: BreezyIngestRuntime) -> None:
    actors = build_ingest_actors(runtime)

    for actor in actors:
        assert actor._shared is runtime.shared
        assert actor._shared.gate is runtime.shared.gate
        assert actor._shared.product_index is runtime.shared.product_index


def test_each_actor_gets_its_unique_component_id(runtime: BreezyIngestRuntime) -> None:
    ids = [str(a.id) for a in build_ingest_actors(runtime)]

    assert ids == [actor_component_id(venue, city) for venue, city in SITES]
    assert len(set(ids)) == len(ids)


def test_actor_config_carries_the_settings_poll_and_parse_values(
    runtime: BreezyIngestRuntime,
) -> None:
    for actor in build_ingest_actors(runtime):
        assert actor.config.poll_interval_seconds == runtime.settings.poll_interval_seconds
        assert actor.config.parse_timeout_ms == runtime.settings.parse_timeout_ms


# ---------------------------------------------------------------------------
# Registration goes through the NATIVE `Trader.add_actor`
# ---------------------------------------------------------------------------


def test_actors_are_registered_through_trader_add_actor(
    runtime: BreezyIngestRuntime,
) -> None:
    node = build_ingest_node(runtime, node_factory=RecordingNode)

    assert isinstance(node, RecordingNode)
    assert node.config is runtime.node_config
    assert len(node.trader.actors) == len(SITES)
    assert all(isinstance(a, NwsIngestActor) for a in node.trader.actors)


def test_the_built_node_receives_the_shared_state_bearing_actors(
    runtime: BreezyIngestRuntime,
) -> None:
    node = build_ingest_node(runtime, node_factory=RecordingNode)

    for actor in node.trader.actors:
        assert actor._shared is runtime.shared


def test_a_real_trading_node_accepts_the_actors(runtime: BreezyIngestRuntime) -> None:
    """Against the REAL `TradingNode`/`Trader` -- constructed only, never built
    and never run, so no client and no socket is opened.

    The loop is created and closed here rather than left to Nautilus:
    `common/functions.py:get_event_loop` deliberately REFUSES to create one
    while pytest is running, so `TradingNode(config)` raises unless a loop is
    supplied. Passing one explicitly also keeps this test independent of
    whatever loop state an earlier test left behind.
    """
    import asyncio

    from nautilus_trader.live.node import TradingNode

    loop = asyncio.new_event_loop()
    node = build_ingest_node(runtime, node_factory=lambda cfg: TradingNode(cfg, loop=loop))
    try:
        registered = node.trader.actors()
        assert len(registered) == len(SITES)
        assert {str(a.id) for a in registered} == {
            actor_component_id(venue, city) for venue, city in SITES
        }
        assert all(a._shared is runtime.shared for a in registered)
    finally:
        for actor in node.trader.actors():
            actor.shutdown_executor()
        node.dispose()
        loop.close()
