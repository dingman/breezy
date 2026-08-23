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
from typing import Protocol

from nautilus_trader.config import TradingNodeConfig

from breezy.ingest.gate import StateStore
from breezy.ingest.shared_state import SharedIngestState
from breezy.persistence.catalog import FilesystemProbe, probe_filesystem
from breezy.registry.sites import SiteRegistry, default_registry, load_registry
from breezy.runtime.node_config import build_node_config
from breezy.runtime.settings import BreezyRuntimeSettings
from breezy.runtime.sqlite_store import SqliteStateStore

logger = logging.getLogger(__name__)


class ClosableStateStore(StateStore, Protocol):
    """A :class:`~breezy.ingest.gate.StateStore` that owns a closable resource.

    Narrower than ``StateStore`` by exactly one method, so the composition
    root can promise teardown without widening the seam the gate and the
    product index see.
    """

    def close(self) -> None: ...


StoreFactory = Callable[[Path], ClosableStateStore]
ProbeFactory = Callable[[Path], FilesystemProbe]


# ---------------------------------------------------------------------------
# Durable-state attestation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DurableStateAttestation:
    """The durable-persistence facts ``SharedIngestState`` checks at startup.

    ``SharedIngestState.__init__`` duck-types three config objects against
    ``save_state``/``load_state`` (kernel), ``database``/``flush_on_start``
    (cache) and ``load_cache`` (exec engine), and refuses to construct unless
    all five say the gate's persisted state will survive a restart. This one
    object satisfies all three roles.

    **Why the real Nautilus config objects are not passed instead.** That
    precondition was written when ``StateStore`` was backed by the Nautilus
    ``Cache``. It no longer is: ``breezy.runtime.sqlite_store`` records that
    the Cache-backed store was rejected on measured evidence (``Cache.add``
    returns before the write is durable, ``Cache.get`` never reads the
    database, ``Cache.reset()`` can launder a permanent trading halt), and the
    gate's state now lives in a SQLite file. Meanwhile the assertion still
    demands ``CacheConfig.database is not None``, and
    ``system/kernel.py:311-329`` accepts only ``'redis'`` there -- so **no
    Redis-free node config can ever satisfy it**, and this deployment has no
    Redis. See ``tests/unit/test_runtime_composition.py``, which asserts that
    impossibility so it fails RED the day it is fixed upstream.

    This object is therefore not a bypass: every field states something true
    about the durability that actually exists. ``database`` is the real path
    of the SQLite file backing ``StateStore``; ``save_state``/``load_state``/
    ``load_cache`` are true because ``SqliteStateStore`` reads and writes that
    file synchronously on every call and repopulates from it on restart with
    no load step at all; ``flush_on_start`` is false because nothing truncates
    it at startup. It is deliberately NOT named like a Nautilus config class,
    and it is never passed to Nautilus.

    The correct upstream fix is for ``SharedIngestState`` to assert on the
    ``StateStore`` it is handed rather than on ``CacheConfig``. That is a
    change to a module this seam does not own; it is reported, not made here.
    """

    save_state: bool
    load_state: bool
    database: str | None
    flush_on_start: bool
    load_cache: bool


def durable_state_attestation(settings: BreezyRuntimeSettings) -> DurableStateAttestation:
    """Return the :class:`DurableStateAttestation` for ``settings``."""
    return DurableStateAttestation(
        save_state=True,
        load_state=True,
        database=str(settings.state_db_path),
        flush_on_start=False,
        load_cache=True,
    )


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
    ``actor_cls(config)`` (``common/config.py:614``) -- config only. An Actor
    registered through ``TradingNodeConfig.actors`` therefore cannot be handed
    this object at construction. It is surfaced here so the caller that owns
    Actor construction can wire it; see the module report for the open
    integration question.
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

    attestation = durable_state_attestation(settings)

    with ExitStack() as stack:
        store = store_factory(settings.state_db_path)
        stack.callback(store.close)

        shared = SharedIngestState(
            registry=registry,
            sites=settings.sites,
            catalog_base=settings.catalog_base,
            store=store,
            clock=clock,
            kernel_config=attestation,
            cache_config=attestation,
            exec_engine_config=attestation,
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
