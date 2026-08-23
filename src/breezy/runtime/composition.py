"""The Breezy ingestion composition root.

One function, :func:`ingest_runtime`, turns a validated
:class:`~breezy.runtime.settings.BreezyRuntimeSettings` into every live object
the process needs, and guarantees they are torn down again -- on the happy
path, on a body exception, and on a construction failure part-way through.

Ordering is load-bearing in both directions:

* **Up:** node config (pure, no resources) -> registry (read-only file) ->
  :class:`~breezy.runtime.sqlite_store.SqliteStateStore` (opens a file handle)
  -> :class:`~breezy.ingest.shared_state.SharedIngestState` (claims the
  process-wide slot and runs the startup preconditions).
* **Down:** exactly the reverse. ``SharedIngestState.dispose()`` releases the
  process slot; ``SqliteStateStore.close()`` closes the sqlite handle. A
  construction error must leak neither -- a leaked slot makes the failure
  unrecoverable in-process (the next attempt raises
  ``DuplicateSharedIngestStateError`` instead of the real cause), and a leaked
  handle keeps a WAL open on a database nobody owns.

``contextlib.ExitStack`` provides that guarantee natively; no bespoke teardown
machinery is written here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from nautilus_trader.config import TradingNodeConfig
from nautilus_trader.live.node import TradingNode

from breezy.ingest.config import NwsIngestActorConfig
from breezy.ingest.gate import ClosableStateStore
from breezy.ingest.nws_actor import NwsIngestActor
from breezy.ingest.shared_state import SharedIngestState
from breezy.persistence.catalog import FilesystemProbe, probe_filesystem
from breezy.registry.sites import SiteRegistry, default_registry, load_registry
from breezy.runtime.node_config import actor_component_id, build_node_config
from breezy.runtime.settings import BreezyRuntimeSettings
from breezy.runtime.sqlite_store import SqliteStateStore

logger = logging.getLogger(__name__)


StoreFactory = Callable[[Path], ClosableStateStore]
ProbeFactory = Callable[[Path], FilesystemProbe]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def load_site_registry(settings: BreezyRuntimeSettings) -> SiteRegistry:
    """Return the site registry: the packaged default, or ``registry_path``.

    ``default_registry()`` is ``lru_cache``d, so the common path pays for the
    TOML parse once per process. An explicit ``registry_path`` bypasses that
    cache deliberately -- a caller who names a file wants that file re-read,
    and ``load_registry`` raises ``FileNotFoundError`` if it is absent rather
    than silently falling back to the packaged one.
    """
    if settings.registry_path is None:
        return default_registry()
    return load_registry(settings.registry_path)


# ---------------------------------------------------------------------------
# The runtime bundle
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class BreezyIngestRuntime:
    """Every constructed component of one ingestion process.

    Note on ``shared``: ``ActorFactory.create`` instantiates each Actor as
    ``actor_cls(config)`` (``common/config.py:614``) -- config only, with no
    seam for a live object. ``NwsIngestActor.__init__`` requires
    ``shared=``, so these Actors cannot come from ``TradingNodeConfig.actors``
    at all. :func:`build_ingest_actors` constructs them here instead and
    :func:`build_ingest_node` registers them through the native
    ``Trader.add_actor``.
    """

    settings: BreezyRuntimeSettings
    registry: SiteRegistry
    store: ClosableStateStore
    shared: SharedIngestState
    node_config: TradingNodeConfig


@contextmanager
def ingest_runtime(
    settings: BreezyRuntimeSettings,
    *,
    clock: Callable[[], int] | None = None,
    probe: ProbeFactory = probe_filesystem,
    store_factory: StoreFactory = SqliteStateStore,
) -> Iterator[BreezyIngestRuntime]:
    """Construct, yield, and reliably tear down one ingestion runtime.

    ``clock`` defaults to ``time.time_ns``. It is the ONE nanosecond clock the
    gate, the product index, the transport and the cross-site burst window all
    read; a per-Actor Nautilus ``Clock`` cannot serve that role because each
    Actor gets its own (``trading/trader.py:342``).

    ``probe`` and ``store_factory`` are injected for the same reason
    ``SharedIngestState`` takes a ``probe``: every teardown path stays
    reachable in a test without a real mount or a real failure.
    """
    if clock is None:
        import time

        clock = time.time_ns

    # Built first, deliberately: it allocates nothing and validates the
    # trader id, so a malformed setting fails before any handle is opened.
    node_config = build_node_config(settings)
    registry = load_site_registry(settings)

    with ExitStack() as stack:
        store = store_factory(settings.state_db_path)
        stack.callback(store.close)

        # The durability probe needs a SECOND, independent handle on the same
        # backing medium -- for `SqliteStateStore` a fresh connection to the
        # same file. Built from the same `store_factory` and the same path, so
        # a test that injects a fake store gets a probe against that same fake
        # rather than against the real one.
        def open_state_store_view() -> ClosableStateStore:
            return store_factory(settings.state_db_path)

        shared = SharedIngestState(
            registry=registry,
            sites=settings.sites,
            catalog_base=settings.catalog_base,
            store=store,
            clock=clock,
            store_opener=open_state_store_view,
            check_proxy_env=settings.check_proxy_env,
            probe=probe,
        )
        stack.callback(shared.dispose)

        logger.info(
            "breezy ingest runtime composed: trader_id=%s sites=%s catalog_base=%s state_db=%s",
            settings.trader_id,
            settings.sites,
            settings.catalog_base,
            settings.state_db_path,
        )

        yield BreezyIngestRuntime(
            settings=settings,
            registry=registry,
            store=store,
            shared=shared,
            node_config=node_config,
        )


# ---------------------------------------------------------------------------
# Actor construction and native registration
# ---------------------------------------------------------------------------
#
# Why the Actors are built here rather than declared in the node config
# ---------------------------------------------------------------------
# `ActorFactory.create` ends in ``actor_cls(config)`` (``common/config.py:614``)
# -- exactly one positional argument, produced by round-tripping the config
# through JSON. `NwsIngestActor.__init__` is ``(config, *, shared, ...)`` with
# ``shared`` REQUIRED, and `breezy.ingest.shared_state` deliberately offers no
# module-level ``current()`` accessor, because a global getter is precisely how
# a second, unnoticed component graph gets built. So the config-driven route
# cannot construct these Actors, and no amount of config shaping changes that.
#
# The native alternative needs nothing built: ``Trader.add_actor(actor)``
# (``trading/trader.py:312``; ``add_actors`` at ``:355``) accepts an
# ALREADY-CONSTRUCTED Actor, and ``TradingNode.trader`` (``live/node.py:139``)
# exposes it. ``TradingNode.__init__`` builds the kernel -- and therefore the
# trader -- before ``build()`` is called, so registration happens on a node
# that has opened no client and no socket.
#
# Nothing in NautilusTrader is modified, subclassed around, or reimplemented,
# and no DI container or service locator is introduced: the dependency is
# passed explicitly, by hand, exactly once per Actor.


class IngestNode(Protocol):
    """The `TradingNode` surface :func:`build_ingest_node` touches.

    Narrow on purpose: a test can supply a recording double without standing
    up an event loop, and this states exactly which two members the wiring
    depends on.
    """

    @property
    def trader(self) -> Any: ...


IngestNodeFactory = Callable[[TradingNodeConfig], Any]


def build_ingest_actors(runtime: BreezyIngestRuntime) -> tuple[NwsIngestActor, ...]:
    """Return one :class:`NwsIngestActor` per configured site, `shared` injected.

    Order follows ``settings.sites`` so the registration order is the
    configuration order and therefore reproducible.

    ``component_id`` comes from
    :func:`breezy.runtime.node_config.actor_component_id` -- the same function
    the config-driven route used -- because all five Actors are the same class
    and would otherwise adopt the class name as their id and collide inside
    ``Trader.add_actor``.

    Call this ONCE per runtime: ``NwsIngestActor.__init__`` registers itself
    with the shared state, and a second registration for the same site raises
    ``DuplicateSiteRegistrationError`` by design.
    """
    settings = runtime.settings
    return tuple(
        NwsIngestActor(
            config=NwsIngestActorConfig(
                component_id=actor_component_id(venue, city),
                venue=venue,
                city=city,
                poll_interval_seconds=settings.poll_interval_seconds,
                parse_timeout_ms=settings.parse_timeout_ms,
            ),
            shared=runtime.shared,
        )
        for venue, city in settings.sites
    )


def build_ingest_node(
    runtime: BreezyIngestRuntime,
    *,
    node_factory: IngestNodeFactory = TradingNode,
) -> Any:
    """Build the node for ``runtime`` and register its ingest Actors natively.

    ``node_factory`` is injected for the same reason every other seam in this
    module is: the whole wiring stays exercisable against a recording double
    with no event loop, and against the real ``TradingNode`` without ever
    calling ``build()`` or ``run()``.

    The node is NOT built or run here. Lifecycle stays with the caller, which
    already owns ``dispose()``.
    """
    node = node_factory(runtime.node_config)
    actors = build_ingest_actors(runtime)
    for actor in actors:
        node.trader.add_actor(actor)
    logger.info(
        "registered %d ingest actor(s) via Trader.add_actor: %s",
        len(actors),
        [str(a.id) for a in actors],
    )
    return node
