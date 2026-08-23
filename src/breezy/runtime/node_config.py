"""Builds the `TradingNodeConfig` for the Breezy NWS-ingestion process.

Null hypothesis, checked against the installed ``nautilus-trader==1.231.0``
before anything here was written:

* **Actor registration is native.** ``NautilusKernelConfig.actors`` is a list
  of ``ImportableActorConfig`` and the kernel instantiates each one via
  ``ActorFactory.create`` (``system/kernel.py:528-531``). Nothing needs to be
  built to run an Actor per site.
* **Signal handling is native.** ``NautilusKernel._setup_loop``
  (``system/kernel.py:558-572``) registers SIGTERM/SIGINT/SIGABRT for every
  non-BACKTEST environment. See ``breezy.runtime.cli``.
* **Logging configuration is native** (``LoggingConfig``).

What this module therefore adds is only the mapping from
:class:`~breezy.runtime.settings.BreezyRuntimeSettings` onto those native
config objects, plus two refusals Nautilus does not make safely itself
(see ``validated_trader_id`` and the zero-catalog rule below).

Deployment values are never hardcoded here: every one comes from settings.
"""

from __future__ import annotations

import re
from typing import Any, cast

from nautilus_trader.common import Environment
from nautilus_trader.config import (
    CacheConfig,
    ImportableActorConfig,
    LoggingConfig,
    TradingNodeConfig,
)
from nautilus_trader.model.identifiers import TraderId

from breezy.runtime.settings import BreezyRuntimeSettings

#: The ingest Actor, referenced by ``"pkg.mod:Class"`` colon path.
#:
#: A path STRING rather than an import, deliberately. ``ActorFactory.create``
#: resolves it at node-build time (``common/config.py:611-614``), so this
#: module -- and its tests -- stay buildable while the Actor module is
#: authored separately. A DOTTED path is not equivalent: ``resolve_path``
#: requires the colon form and a dotted one fails mid-run.
NWS_INGEST_ACTOR_PATH = "breezy.ingest.nws_actor:NwsIngestActor"

#: The Actor's ``ActorConfig`` subclass, same colon-path convention.
NWS_INGEST_ACTOR_CONFIG_PATH = "breezy.ingest.config:NwsIngestActorConfig"

#: Prefix of the per-site ``component_id``. See :func:`actor_component_id`.
_COMPONENT_ID_PREFIX = "NWS-INGEST"

#: Two non-empty, whitespace-free segments either side of a single hyphen --
#: the shape ``TraderId``'s own docstring requires ("TESTER-001").
_TRADER_ID_PATTERN = re.compile(r"^[^\s-]+-[^\s-]+$")


class NodeConfigError(ValueError):
    """Raised when settings cannot be mapped onto a valid node config.

    Every message names the offending setting, matching
    :class:`~breezy.runtime.settings.SettingsError`'s convention, so the CLI
    can surface it verbatim.
    """


def validated_trader_id(value: str) -> TraderId:
    """Return a ``TraderId``, refusing a malformed value BEFORE Nautilus sees it.

    **This pre-check is not defensive duplication.** Measured against the
    installed 1.231.0: ``TraderId("bad")`` does not raise the ``ValueError``
    its docstring promises (``model/identifiers.pyx:723-726``). It panics in
    Rust (``crates/model/src/identifiers/trader_id.rs:86``) and **aborts the
    process with SIGABRT (exit 134)** -- uncatchable from Python, and printing
    a Rust panic dump as the process's only output. A misconfigured
    ``BREEZY_TRADER_ID`` must fail as a clear, catchable configuration error,
    so the value is validated here and never handed over unchecked.
    """
    if not _TRADER_ID_PATTERN.match(value):
        raise NodeConfigError(
            f"trader_id {value!r} is malformed: it must be two non-empty, "
            "whitespace-free segments separated by a single hyphen (e.g. "
            "'BREEZY-001'). Set BREEZY_TRADER_ID accordingly."
        )
    return TraderId(value)


def actor_component_id(venue: str, city: str) -> str:
    """Return the unique ``component_id`` for the Actor serving ``venue``/``city``.

    Required, not cosmetic: ``ActorConfig.component_id`` defaults to ``None``,
    which makes every Actor adopt its class name as its id. All five ingest
    Actors are the same class, so without this they would collide and
    ``Trader.add_actor`` would reject the second one.
    """
    return f"{_COMPONENT_ID_PREFIX}-{venue}-{city}"


def build_actor_configs(
    settings: BreezyRuntimeSettings,
) -> tuple[ImportableActorConfig, ...]:
    """Return one :class:`ImportableActorConfig` per configured site.

    The payload carries only msgspec-serialisable scalars. It deliberately
    carries no ``Path``, callable, or object reference: ``ActorFactory.create``
    round-trips ``config`` through JSON, so anything else either fails to
    encode or silently diverges from the live object a later run rebuilds.
    """
    return tuple(
        ImportableActorConfig(
            actor_path=NWS_INGEST_ACTOR_PATH,
            config_path=NWS_INGEST_ACTOR_CONFIG_PATH,
            config={
                "component_id": actor_component_id(venue, city),
                "venue": venue,
                "city": city,
                "poll_interval_seconds": settings.poll_interval_seconds,
                "parse_timeout_ms": settings.parse_timeout_ms,
            },
        )
        for venue, city in settings.sites
    )


def build_node_config(settings: BreezyRuntimeSettings) -> TradingNodeConfig:
    """Return the `TradingNodeConfig` for the ingestion process.

    Two deliberate zeroes:

    **Zero catalogs.** ``catalogs=[]``. ``NautilusKernel`` registers one
    ``DataEngine`` catalog per entry (``system/kernel.py:514-526``), and
    measured platform finding F3 is that ``DataEngine._query_catalog`` breaks
    on the first registered catalog that returns rows. Breezy reads and writes
    its per-station ``ParquetDataCatalog`` roots directly, outside the
    DataEngine, so the correct registered count is zero -- not "one, carefully".

    **Zero cache/message-bus database.** ``kernel.py:311-329`` accepts only
    ``'redis'`` for either backing store and raises for anything else. There is
    no Redis in this deployment, and Breezy's durable state deliberately does
    not live in the Nautilus ``Cache`` at all -- it lives in
    :class:`~breezy.runtime.sqlite_store.SqliteStateStore`. Leaving both
    ``None`` is therefore the only correct setting, and it is stated
    explicitly rather than defaulted so the intent is visible and testable.
    """
    # `msgspec.Struct` config classes are untyped to mypy (compiled Nautilus
    # surface), so the constructor call is typed as Any at this one boundary.
    config: Any = TradingNodeConfig(
        environment=Environment.LIVE,
        trader_id=validated_trader_id(settings.trader_id),
        logging=LoggingConfig(log_level=settings.log_level),
        cache=CacheConfig(database=None, flush_on_start=False),
        message_bus=None,
        catalogs=[],
        actors=list(build_actor_configs(settings)),
        data_clients={},
        exec_clients={},
    )
    return cast(TradingNodeConfig, config)
