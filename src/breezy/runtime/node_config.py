"""Builds the `TradingNodeConfig` for each Breezy process ROLE.

Two roles, two functions, deliberately not one parameterised function:

* :func:`build_node_config` -- the NWS-ingestion process. Actor-driven,
  zero data clients, zero venue configuration. It must start on a host that
  has never been given a Polymarket.us endpoint.
* :func:`build_quote_tape_node_config` -- the venue quote-tape recorder.
  One read-only data client, native streaming persistence, zero Actors,
  zero exec clients. It cannot start without venue configuration.

Collapsing them would make venue configuration a hard startup requirement of
the weather collector; that regression has already happened once and the
role split is what prevents it recurring.

Null hypothesis, checked against the installed ``nautilus-trader==1.231.0``
before anything here was written:

* **Actor registration is native, but NOT via config for our Actor.**
  ``NautilusKernelConfig.actors`` is a list of ``ImportableActorConfig`` and
  the kernel instantiates each one via ``ActorFactory.create``
  (``system/kernel.py:528-531``), which ends in ``actor_cls(config)``
  (``common/config.py:614``) -- one positional argument, round-tripped through
  JSON. ``NwsIngestActor`` requires a live ``SharedIngestState``, so that route
  cannot build it. The other native route can and is used:
  ``Trader.add_actor(actor)`` (``trading/trader.py:312``) takes an
  already-constructed Actor, reached through ``TradingNode.trader``
  (``live/node.py:139``). See
  :func:`breezy.runtime.composition.build_ingest_node`. Nothing is built to run
  an Actor per site.
* **Signal handling is native.** ``NautilusKernel._setup_loop``
  (``system/kernel.py:558-572``) registers SIGTERM/SIGINT/SIGABRT for every
  non-BACKTEST environment. See ``breezy.runtime.cli``.
* **Logging configuration is native** (``LoggingConfig``).

What this module therefore adds is only the mapping from
:class:`~breezy.runtime.settings.BreezyRuntimeSettings` onto those native
config objects, plus two refusals Nautilus does not make safely itself
(see ``validated_trader_id`` and the zero-catalog rule below). Actor
construction is NOT here: it needs a live object and therefore belongs to the
composition root.

Deployment values are never hardcoded here: every one comes from settings.
"""

from __future__ import annotations

import os
import re
import stat
from datetime import time as datetime_time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pandas as pd
from msgspec.structs import replace as msgspec_replace
from nautilus_trader.common import Environment
from nautilus_trader.config import (
    CacheConfig,
    LoggingConfig,
    TradingNodeConfig,
)
from nautilus_trader.core.uuid import UUID4
from nautilus_trader.model.data import (
    InstrumentClose,
    InstrumentStatus,
    MarkPriceUpdate,
    OrderBookDepth10,
    QuoteTick,
    TradeTick,
)
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.persistence.config import StreamingConfig
from nautilus_trader.persistence.writer import RotationMode

from breezy.adapters.polymarket_us.tape_records import (
    DepthTruncation,
    QuoteTapeGap,
    VenueClockOffset,
    VenueSettlementSnapshot,
)
from breezy.persistence.catalog import CatalogPathError
from breezy.runtime.settings import BreezyRuntimeSettings, PolymarketUSQuoteTapeSettings

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Import-time only. At RUNTIME the adapter package must be reached from
    # inside :func:`build_quote_tape_node_config`, never at module scope:
    # `breezy/runtime/__init__.py` eagerly imports `composition`, which imports
    # this module, while `adapters.polymarket_us.config` imports
    # `breezy.runtime.settings` -- so a module-scope adapter import here closes
    # the cycle and raises `ImportError: partially initialized module`.
    # Measured, not hypothesised. Keeping it under TYPE_CHECKING means mypy
    # still checks the signature with the real type.
    from breezy.adapters.polymarket_us.config import PolymarketUSDataClientConfig

#: The ingest Actor's ``"pkg.mod:Class"`` colon path.
#:
#: Retained as a NAME only -- deliberately NOT used to register the Actor.
#: ``ActorFactory.create`` ends in ``actor_cls(config)``
#: (``common/config.py:614``): one positional argument, round-tripped through
#: JSON. ``NwsIngestActor.__init__`` requires ``shared: SharedIngestState``,
#: a live object, so the config-driven route cannot construct it at all.
#: :func:`breezy.runtime.composition.build_ingest_node` constructs each Actor
#: explicitly and registers it through the native ``Trader.add_actor``
#: (``trading/trader.py:312``, reached via ``TradingNode.trader`` at
#: ``live/node.py:139``). These constants remain so a test can assert the
#: importable route is NOT in use.
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


def build_node_config(settings: BreezyRuntimeSettings) -> TradingNodeConfig:
    """Return the `TradingNodeConfig` for the ingestion process.

    Three deliberate zeroes:

    **Zero catalogs.** ``catalogs=[]``. ``NautilusKernel`` registers one
    ``DataEngine`` catalog per entry (``system/kernel.py:514-526``), and
    measured platform finding F3 is that ``DataEngine._query_catalog`` breaks
    on the first registered catalog that returns rows. Breezy reads and writes
    its per-station ``ParquetDataCatalog`` roots directly, outside the
    DataEngine, so the correct registered count is zero -- not "one, carefully".

    **Zero declared actors.** ``actors=[]``. Not an omission: the ingest
    Actors are constructed by
    :func:`breezy.runtime.composition.build_ingest_actors` with their
    ``SharedIngestState`` injected, then registered through the native
    ``Trader.add_actor`` (``trading/trader.py:312``). The
    ``ImportableActorConfig`` route is structurally unusable for them --
    ``ActorFactory.create`` ends in ``actor_cls(config)``
    (``common/config.py:614``), one positional argument, and there is no seam
    in it for a live shared object.

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
        actors=[],
        data_clients={},
        exec_clients={},
        # The other half of the read-only cage. `exec_clients={}` removes the
        # venue-facing transport; `strategies=[]` removes the only component
        # that calls `submit_order` at all. Both are stated rather than
        # defaulted so the intent is visible in review and testable in source
        # -- an unset field and a deliberately empty one are indistinguishable
        # on the built config. Pinned by
        # `TestTheReadOnlyCageIsDeclaredNotDefaulted`.
        strategies=[],
    )
    return cast(TradingNodeConfig, config)


#: What the quote-tape recorder persists, and nothing else.
#:
#: Every entry is here because it CANNOT be reconstructed later -- Polymarket.us
#: weather markets have no history and no backfill:
#:
#: * ``QuoteTick`` -- top of book, the tape's spine.
#: * ``OrderBookDepth10`` -- ten levels per side. Without it, slippage at any
#:   size beyond the best level is unmeasurable, and Phase 1.5.3 must net the
#:   measured gap against "realistic slippage at the intended size". A study
#:   forced to assume the best level fills the whole order understates slippage
#:   and can produce a FALSE GO on the premise-falsification gate.
#: * ``TradeTick`` -- executed prints. The only ground truth for what actually
#:   traded rather than what was merely quoted (REQ-DATA-04).
#: * ``MarkPriceUpdate`` -- the venue's own ``settlementPx`` while the market
#:   is live.
#: * ``InstrumentClose`` -- the venue's own TERMINAL settlement value. Plan
#:   item 1.2's ledger needs it and venue REST may not retain it afterwards.
#: * ``InstrumentStatus`` -- market-state transitions, carrying the raw venue
#:   state string verbatim in ``reason``.
#: * ``QuoteTapeGap`` -- the intervals during which the recorder was NOT
#:   receiving. Without these on disk, a reconnect is invisible to anyone
#:   reading only the parquet, and gaps plausibly correlate with fast-moving
#:   books, biasing the surviving sample toward calm periods.
#: * ``VenueClockOffset`` -- host-vs-venue clock drift over time. The auth
#:   smoke measured a ~131 second host offset.
#: * ``BinaryOption`` -- the instrument definitions WITHOUT which none of the
#:   above reads back: ``ParquetDataCatalog.query`` reconstructs price and size
#:   from raw integers and needs the instrument's precision to do it.
#:
#: The list is EXCLUSIVE (``persistence/config.py:47-48``: "if this is
#: specified then **only** the included types will be written"), which is the
#: point: without it the ``"*"`` bus subscription the kernel installs
#: (``system/kernel.py:604``) would write every account, order and position
#: event this process never generates, plus every log-adjacent message, into
#: the tape directory.
QUOTE_TAPE_INCLUDE_TYPES: list[type] = [
    QuoteTick,
    OrderBookDepth10,
    TradeTick,
    MarkPriceUpdate,
    InstrumentClose,
    InstrumentStatus,
    QuoteTapeGap,
    VenueClockOffset,
    VenueSettlementSnapshot,
    DepthTruncation,
    BinaryOption,
]

#: Flush cadence for the feather writer, in milliseconds.
#:
#: The writer buffers and flushes on ``check_flush``
#: (``persistence/writer.py``); with no interval configured, a recorder killed
#: between flushes loses whatever was buffered. Ten seconds bounds the loss of
#: an unbackfillable series at ten seconds of quotes while keeping the syscall
#: rate negligible for a handful of weather markets.
QUOTE_TAPE_FLUSH_INTERVAL_MS: int = 10_000

#: Mode the tape root is created with. Matches
#: ``breezy.runtime.health.SNAPSHOT_DIR_MODE`` and the station-catalog
#: convention. The tape is not a secret, but it is strategy-inferable: which
#: markets Breezy watches, and from what moment. ``fsspec``'s ``makedirs`` --
#: which is what Nautilus reaches on the streaming path -- would otherwise
#: create it under the process umask, typically world-readable ``0755``.
QUOTE_TAPE_ROOT_MODE: int = 0o700

#: Rotate the feather stream on a schedule rather than never.
#:
#: ``StreamingConfig.rotation_mode`` defaults to ``NO_ROTATION``, which is one
#: ever-growing file per type for the process lifetime -- an unbounded
#: disk-exhaustion path for a recorder meant to run for months.
#:
#: DAILY in UTC because the study's unit of analysis is a market-day: a
#: size-based cut would fall at arbitrary instants and turn "which files cover
#: 2026-08-25" into a scan.
#:
#: ACCEPTED, UNMITIGATED RISK -- read this before assuming a size bound exists.
#: Nautilus rotation modes are MUTUALLY EXCLUSIVE, not layered:
#: ``_check_file_rotation`` (``persistence/writer.py:290-320``) is an
#: ``if/elif`` chain, and ``max_file_size`` is read ONLY by the
#: ``RotationMode.SIZE`` branch. Under ``SCHEDULED_DATES`` it is dead, so
#: passing it would state a bound that does not exist -- worse than none,
#: because it stops the next reader looking. It is therefore NOT passed.
#:
#: The consequence: one day's file is UNBOUNDED. A venue frame storm produces
#: one arbitrarily large feather and no error. This is accepted rather than
#: fixed because the alternatives are worse for an unbackfillable tape: SIZE
#: mode destroys the day-partitioning the analysis depends on, and a
#: hand-rolled periodic size poll would have to reach into the writer's private
#: rotation state, which is exactly the kind of Nautilus-internals coupling
#: this project forbids. Mitigate OUTSIDE the process -- disk alerting on the
#: tape volume. Both halves are pinned by
#: ``tests/contract/test_quote_tape_streaming_contract.py``
#: (``test_a_scheduled_rotation_ignores_max_file_size_entirely`` and its
#: ``SIZE`` control), so a Nautilus version that gains a dual-trigger mode
#: fails RED instead of silently changing the tape's on-disk layout.
QUOTE_TAPE_ROTATION_MODE: RotationMode = RotationMode.SCHEDULED_DATES
QUOTE_TAPE_ROTATION_INTERVAL: pd.Timedelta = pd.Timedelta(days=1)
QUOTE_TAPE_ROTATION_TIME: datetime_time = datetime_time(0, 0, 0, 0)
QUOTE_TAPE_ROTATION_TIMEZONE: str = "UTC"


def prepare_quote_tape_root(root: Path) -> Path:
    """Create the tape root privately and safely BEFORE Nautilus touches it.

    Nautilus reaches the streaming path through ``fsspec``, whose ``makedirs``
    honours the process umask and performs no symlink check. This function is
    the seam that restores the convention the rest of the repo already follows
    (``breezy.persistence.catalog.open_station_catalog``): mode ``0700``, and a
    refusal -- not a warning -- if what is on disk is not a real directory.

    The symlink check uses ``os.lstat``, which does NOT follow links.
    ``Path.mkdir(exist_ok=True)`` falls back to ``self.is_dir()``, which DOES,
    so a symlink planted at the root is reported as "already a directory" and
    every subsequent write lands in the link's target. An aliased tape root is
    the worst case here: it merges or redirects an archive that can never be
    re-recorded, and no read-back can detect it.

    Idempotent, and it TIGHTENS an existing root rather than accepting it: a
    directory created by an earlier, laxer version must not stay world-readable
    just because it already exists.
    """
    root.parent.mkdir(parents=True, exist_ok=True)
    try:
        root.mkdir(mode=QUOTE_TAPE_ROOT_MODE, exist_ok=True)
    except FileExistsError:
        # `mkdir(exist_ok=True)` swallows this only when the target is a
        # directory; a regular file reaches here.
        pass

    try:
        status = os.lstat(root)
    except OSError as exc:  # pragma: no cover - defensive
        raise CatalogPathError(
            f"quote-tape root {root} could not be verified as a real directory "
            f"({exc}); refusing to record through a path whose identity on disk "
            "is unknown"
        ) from exc

    if stat.S_ISLNK(status.st_mode):
        raise CatalogPathError(
            f"quote-tape root {root} is a symlink; refusing to record through "
            "it, because every write would land in the link's target and the "
            "tape cannot be re-recorded"
        )
    if not stat.S_ISDIR(status.st_mode):
        raise CatalogPathError(
            f"quote-tape root {root} exists and is not a directory; refusing to "
            "record through it"
        )

    # `mkdir`'s mode argument is masked by the umask, and an already-existing
    # root keeps whatever mode it had, so the mode is set explicitly. Safe now
    # that the `lstat` above has established this is not a symlink.
    os.chmod(root, QUOTE_TAPE_ROOT_MODE)
    return root


def build_quote_tape_node_config(
    settings: PolymarketUSQuoteTapeSettings,
    data_client_config: PolymarketUSDataClientConfig,
) -> TradingNodeConfig:
    """Return the `TradingNodeConfig` for the **quote-tape recorder** process.

    Separate from :func:`build_node_config` because it is a separate ROLE, not
    a variant of the ingestion node. The ingestion process must start on a host
    with no venue configuration at all; this one cannot start without it. One
    function serving both would make venue configuration a hard startup
    requirement for the weather collector -- the exact regression this shape
    exists to prevent.

    Null hypothesis, checked against the installed ``nautilus-trader==1.231.0``
    before any persistence code was considered:

    * **Live-run persistence is native.** ``NautilusKernel.__init__`` builds a
      ``StreamingFeatherWriter`` whenever ``config.streaming`` is set and
      subscribes it to the whole message bus
      (``system/kernel.py:508-509``, ``:586-604``), writing to
      ``<catalog_path>/<environment>/<instance_id>``. Nothing about capture
      needs authoring.
    * **Reading it back is native.** ``ParquetDataCatalog.convert_stream_to_data``
      (``persistence/catalog/parquet.py:2604``) documents ``subdirectory``
      as "Either 'backtest' or 'live'" and converts the feather stream into
      the catalog's parquet layout, from which ``catalog.query`` returns real
      ``QuoteTick`` objects. Measured end to end: two quotes written, two read
      back with bid/ask intact.

    So this function writes no persistence code. It supplies a
    ``StreamingConfig`` and the data-client registration, and that is all.

    **Zero exec clients**, stated explicitly rather than defaulted. This
    process has no order path and the empty mapping is the assertion of that.

    **Zero registered catalogs**, for the same reason
    :func:`build_node_config` has none: ``catalogs=[]`` concerns
    ``DataEngine`` query routing, which is unrelated to the streaming writer
    and carries the finding-F3 hazard.

    **One catalog root for the venue, not one per market.** The
    ``@customdataclass``-era rule "one catalog root per station" applies to
    custom types that carry no ``instrument_id`` and therefore write flat.
    ``QuoteTick`` carries one, so the catalog partitions natively into
    ``data/quote_tick/<instrument_id>/`` -- measured, not assumed. A root per
    market would fragment a natively-partitioned dataset for nothing.
    """
    # Deferred to call time to break the package import cycle documented at
    # the TYPE_CHECKING block above.
    from breezy.adapters.polymarket_us.factories import POLYMARKET_US_CLIENT_NAME

    # ONE identity, used twice. `NautilusKernelConfig.instance_id`
    # (`system/config.py:108`) is honoured by the kernel (`system/kernel.py:160`)
    # and names the streaming directory (`system/kernel.py:589`); the same value
    # is handed to the data client so every `QuoteTapeGap` row it writes names
    # the run that produced it. Generated here rather than left to default
    # because the kernel's own default is created too late to be readable, and
    # a gap row without this identity is unpartitionable across restarts --
    # which fails UNSAFE, by under-excluding contaminated intervals.
    instance_id = UUID4()
    # `msgspec.structs.replace` rather than reconstructing by hand: it is the
    # supported copy-with-change for a frozen Struct and it re-runs
    # `__post_init__`, so the config's own validation is not bypassed here.
    data_client_config = msgspec_replace(
        data_client_config, recorder_instance_id=instance_id.value
    )

    # `msgspec.Struct` config classes are untyped to mypy (compiled Nautilus
    # surface), so the constructor call is typed as Any at this one boundary.
    config: Any = TradingNodeConfig(
        instance_id=instance_id,
        environment=Environment.LIVE,
        trader_id=validated_trader_id(settings.trader_id),
        logging=LoggingConfig(log_level=settings.log_level),
        cache=CacheConfig(database=None, flush_on_start=False),
        message_bus=None,
        catalogs=[],
        actors=[],
        data_clients={POLYMARKET_US_CLIENT_NAME: data_client_config},
        exec_clients={},
        # Same pair as in `build_node_config`, for the same reason: the
        # recorder is a tape, not a trader.
        strategies=[],
        streaming=StreamingConfig(
            catalog_path=str(settings.catalog_root),
            include_types=QUOTE_TAPE_INCLUDE_TYPES,
            flush_interval_ms=QUOTE_TAPE_FLUSH_INTERVAL_MS,
            rotation_mode=QUOTE_TAPE_ROTATION_MODE,
            rotation_interval=QUOTE_TAPE_ROTATION_INTERVAL,
            rotation_time=QUOTE_TAPE_ROTATION_TIME,
            rotation_timezone=QUOTE_TAPE_ROTATION_TIMEZONE,
        ),
    )
    return cast(TradingNodeConfig, config)
