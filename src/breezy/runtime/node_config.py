"""Builds the `TradingNodeConfig` for each Breezy process ROLE.

Three roles, three functions, deliberately not one parameterised function:

* :func:`build_node_config` -- the NWS-ingestion process. Actor-driven,
  zero data clients, zero venue configuration. It must start on a host that
  has never been given a Polymarket.us endpoint.
* :func:`build_quote_tape_node_config` -- the venue quote-tape recorder.
  One read-only data client, native streaming persistence, zero Actors,
  zero exec clients. It cannot start without venue configuration.
* :func:`build_trade_node_config` -- the trading process (EXEC SPINE R-2).
  One read-only data client, no streaming, and -- in THIS increment -- still
  zero exec clients, zero strategies and zero exec algorithms: it is a
  process shell that can start, run and stop, and cannot submit an order.
  It additionally refuses to start without a trading identity of its own.

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
    LiveExecEngineConfig,
    LiveRiskEngineConfig,
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
from breezy.runtime.settings import (
    BreezyRuntimeSettings,
    BreezyTradeSettings,
    PolymarketUSQuoteTapeSettings,
)
from breezy.runtime.sqlite_store import SqliteStateStore

if TYPE_CHECKING:  # pragma: no cover - typing only
    # Import-time only. At RUNTIME the adapter package must be reached from
    # inside :func:`build_quote_tape_node_config`, never at module scope:
    # `breezy/runtime/__init__.py` eagerly imports `composition`, which imports
    # this module, while `adapters.polymarket_us.config` imports
    # `breezy.runtime.settings` -- so a module-scope adapter import here closes
    # the cycle and raises `ImportError: partially initialized module`.
    # Measured, not hypothesised. Keeping it under TYPE_CHECKING means mypy
    # still checks the signature with the real type.
    from breezy.adapters.polymarket_us.config import (
        PolymarketUSDataClientConfig,
        PolymarketUSExecClientConfig,
    )

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
            f"trader_id {value!r} is malformed: it must be EXACTLY two "
            "non-empty, whitespace-free segments separated by a single hyphen "
            "(e.g. 'BREEZY-001'); a second hyphen is not allowed. Set the "
            "trader-id variable for this role accordingly -- BREEZY_TRADER_ID "
            "for ingestion, BREEZY_TRADE_TRADER_ID for the trading process."
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
        # The THIRD field that reaches an execution path. `ExecAlgorithm`
        # subclasses `Actor`, so it is easy to read as data-side, but it
        # carries `submit_order`/`modify_order`/`cancel_order` in its own
        # right (`execution/algorithm.pyx`) and the kernel instantiates every
        # entry unconditionally. `strategies=[]` does not cover it.
        exec_algorithms=[],
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
        # Same set as in `build_node_config`, for the same reason: the
        # recorder is a tape, not a trader.
        strategies=[],
        exec_algorithms=[],
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


def build_trade_risk_engine_config(
    market_slugs: tuple[str, ...],
) -> LiveRiskEngineConfig:
    """Return the trading process's NATIVE pre-trade risk configuration.

    Nothing here is new machinery: ``RiskEngine`` already implements a
    per-order notional cap (``risk/engine.pyx:675-679``, denial reason
    ``NOTIONAL_EXCEEDS_MAX_PER_ORDER`` at ``:912-917``) and the kernel already
    builds the engine from this config. Until now Breezy configured **no**
    native risk caps at all, so that mechanism sat unused.

    **Shape, read from source, not guessed.**
    ``RiskEngineConfig.max_notional_per_order`` is ``dict[str, int]``
    (``risk/config.py:44``) keyed by instrument-ID string --
    ``_initialize_risk_checks`` calls ``InstrumentId.from_str_c`` on every key
    (``risk/engine.pyx:193-196``). It is NOT a scalar and there is no
    all-instruments form, so the cap can only cover instrument IDs that exist
    when the config is built. That is why ``market_slugs`` is the input.

    **Residual, stated rather than papered over.** Markets discovered at
    runtime by the instrument provider are NOT in this mapping and are NOT
    covered by this cap; only statically declared slugs
    (``POLYMARKET_US_MARKET_SLUGS``) are. The always-applicable
    per-order chokepoint remains
    :func:`breezy.adapters.polymarket_us.safety.authorize_live_order_submission`,
    which enforces the operator's exact ``Decimal`` ceiling on every order.
    This function adds a second, native, independent line of defence for the
    markets it can key; it does not replace the first.

    **And a second residual, already pinned elsewhere.** Every cap below
    ``risk/engine.pyx:684-689`` is inert until a real ``AccountState`` is
    cached -- see ``tests/contract/test_risk_engine_ordering_enforcement.py``,
    which is the authority on that ordering constraint.

    The VALUE is the operator's, never Breezy's: it comes from
    :func:`~breezy.adapters.polymarket_us.safety.operator_max_order_notional_whole_usd`,
    which fails closed when the control is absent. There is deliberately no
    default, no fallback and no literal on this path. The two OPERATOR-RESERVED
    controls -- max daily budget and max per position -- are NOT here, are not
    derivable from what is here, and are never assigned by this repo.
    """
    # Deferred to call time to break the package import cycle documented at
    # the TYPE_CHECKING block at the top of this module.
    from breezy.adapters.polymarket_us.safety import (
        operator_max_order_notional_whole_usd,
    )
    from breezy.adapters.polymarket_us.symbology import slug_to_instrument_id

    ceiling_usd = operator_max_order_notional_whole_usd()
    return LiveRiskEngineConfig(
        # Stated, not defaulted: `bypass=True` disables every pre-trade check
        # including the cap above (`risk/engine.pyx:273-277`).
        bypass=False,
        max_notional_per_order={
            str(slug_to_instrument_id(slug)): ceiling_usd for slug in market_slugs
        },
    )


def build_trade_node_config(
    settings: BreezyTradeSettings,
    data_client_config: PolymarketUSDataClientConfig,
    exec_client_config: PolymarketUSExecClientConfig,
    *,
    submit_intent_latch: object | None = None,
) -> TradingNodeConfig:
    """Return the `TradingNodeConfig` for the **trading** process (EXEC SPINE W).

    A THIRD role, and a third function, for the reason the first two are
    separate: the weather collector must start on a host with no venue
    configuration, the recorder must refuse to start without it, and this one
    must additionally refuse to start without a trading identity of its own
    (:data:`breezy.runtime.settings.TRADE_TRADER_ID_VAR`). Collapsing any two
    of the three makes one role's requirement another role's outage.

    Null hypothesis, re-checked against the installed ``nautilus-trader==1.231.0``:
    **Nautilus already provides the process shell.** ``TradingNode`` /
    ``NautilusKernel`` build every engine, install the signal handlers
    (``system/kernel.py:558-572``) and own start/stop. This function therefore
    authors no process machinery. It maps settings onto native config objects,
    and makes exactly one non-default decision (the in-flight pin below).

    **EXEC SPINE W wires the execution client in, and it is STILL not able to
    submit an order.** R-4's ``PolymarketUSExecutionClient`` had ZERO
    construction sites until this increment: ``PolymarketUSLiveExecClientFactory``
    (``adapters/polymarket_us/factories.py``) is registered against this exact
    ``exec_clients`` key by ``breezy.runtime.trade_cli``, so the client that
    was previously only exercised by fixtures is now CONSTRUCTED by the node.
    That de-inerts every Nautilus risk cap for the first time in the running
    process (``risk/engine.pyx:684-689`` returns ``True`` -- order allowed --
    while no ``AccountState`` is cached). What remains a structural property
    of the returned config, not a convention, is that nothing can ORIGINATE an
    order:

    * ``strategies=[]`` -- nothing that calls ``submit_order``
      (``trading/strategy.pyx``);
    * ``exec_algorithms=[]`` -- the second route, easy to misread as data-side
      because ``ExecAlgorithm`` subclasses ``Actor``, but it carries
      ``submit_order``/``modify_order``/``cancel_order`` in its own right
      (``execution/algorithm.pyx``) and the kernel instantiates every entry
      unconditionally.

    Both are stated as empty literals rather than defaulted, so the intent is
    visible in review and checkable from source --
    ``TestTheReadOnlyCageIsDeclaredNotDefaulted`` reads this call. The
    execution client's OWN cage -- ``_submit_order`` and ``_cancel_order``
    carry an unconditional denial body, and the other four lifecycle
    coroutines raise -- is R-4's, unchanged by W (``exec/client.py``).

    **``exec_client_config.state_store_opener`` is injected HERE, not earlier.**
    ``breezy.adapters.polymarket_us.factories`` is an ``adapters`` package and
    may not import :class:`~breezy.runtime.sqlite_store.SqliteStateStore`
    (``runtime`` sits ABOVE ``adapters`` in the import-linter layer contract),
    so :func:`~breezy.adapters.polymarket_us.factories.exec_config_from_env`
    always leaves this field ``None``. This function is on the ``runtime``
    side of that boundary, so it is where the real opener is built and
    threaded through via ``msgspec.structs.replace`` -- the identical pattern
    :func:`build_quote_tape_node_config` already uses for
    ``recorder_instance_id``. The opener is never CALLED here: the store is
    thread-confined (``sqlite_store.py:120,128-135``) and must be constructed
    on the execution engine's own event loop, inside ``_connect`` -- see
    ``exec/client.py``'s module docstring.

    **``inflight_check_interval_ms=0`` -- READ THIS BEFORE CHANGING IT.**

    The authority for the disable is CODE, not the config docstring:
    ``live/execution_engine.py:574-575`` and ``:591-592`` both guard on
    ``if self.inflight_check_interval_ms > 0`` before arming the in-flight
    timer and before contributing an interval, and ``:383-386`` schedules the
    continuous-reconciliation task at all only if one of the three intervals
    is truthy. Zero therefore genuinely disables in-flight checking; verified
    by reading the installed source, not inferred from documentation.

    The config docstring (``live/config.py:111-114``) says only "the interval
    (milliseconds) between checking whether in-flight orders have exceeded
    their time-in-flight threshold. This should not be set less than the
    ``inflight_check_threshold_ms``." It documents **no** disable semantic,
    and its "should not be set less than" guidance does not contemplate 0 --
    0 is trivially less than the 5000 ms default threshold. A future reader
    who follows the docstring alone will "helpfully" raise this to 5000 and
    silently re-arm in-flight checking. Do not.

    Why the pin matters here specifically: **Polymarket.us has no
    client-order-id.** ``_check_inflight_orders``
    (``live/execution_engine.py:701``) issues ``QueryOrder`` commands to
    VERIFY -- it does not resubmit -- but after ``inflight_check_retries``
    attempts it calls ``_resolve_inflight_order``, resolving as FAILED an
    order we have no id with which to ask about. A false terminal on a venue
    with no deduplication key is the first step toward a doubled position.

    **``CacheConfig(database=None, flush_on_start=False)``** -- identical to
    both sibling builders. ``kernel.py:311-329`` accepts only ``'redis'`` for
    either backing store; there is no Redis in this deployment, and Breezy's
    durable state deliberately lives outside the Nautilus cache.

    **No streaming.** The recorder writes the tape; the trader does not. A
    second process streaming into the same catalog root would interleave two
    runs' feather files and make the tape unattributable.

    **No operator-reserved control appears here.** Max daily budget and max
    per position are the operator's two values, added as mechanism in a later
    increment, never assigned by Breezy, and fail-closed when absent. There is
    nothing to reference from a node config, so nothing is referenced.

    **Native pre-trade risk caps ARE configured here**, via
    :func:`build_trade_risk_engine_config` -- read its docstring for the shape
    the cap takes and for the two residuals it does not close. The per-order
    notional ceiling is the operator's existing
    ``BREEZY_MAX_ORDER_NOTIONAL_USD``, which is a per-ORDER control and is not
    one of the two reserved ones. Building this config therefore RAISES
    ``LiveTradingPermissionError`` when that control is unset: the trading
    process refuses to start rather than starting uncapped. The two read-only
    roles above are unaffected -- they have no execution surface and no risk
    engine traffic, so requiring a trading ceiling from them would only make a
    weather host fail for a value it can never use.
    """
    # Deferred to call time to break the package import cycle documented at
    # the TYPE_CHECKING block at the top of this module.
    from breezy.adapters.polymarket_us.factories import POLYMARKET_US_CLIENT_NAME

    # `PolymarketUSExecClientConfig.state_store_path` is typed `str | None`
    # because `None` is only the constructor default that lets
    # `__post_init__` raise a clear error; that same `__post_init__` already
    # guarantees a non-empty string by the time an instance exists. Narrowed
    # here, once, for mypy -- not re-validated.
    state_store_path = cast(str, exec_client_config.state_store_path)

    # See the docstring: the store is opened only inside `_connect`, on the
    # execution engine's own loop -- this closure never runs here.
    # ``submit_intent_latch`` is the composition root's already-opened latch
    # (object, never a factory). The exec client stores it; R-7's ``_connect``
    # is what will consume it. A second ``open_submit_intent_latch`` here
    # would flock-conflict with the composition root and kill the process.
    exec_client_config = msgspec_replace(
        exec_client_config,
        state_store_opener=lambda: SqliteStateStore(state_store_path),
        submit_intent_latch=submit_intent_latch,
    )

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
        data_clients={POLYMARKET_US_CLIENT_NAME: data_client_config},
        exec_clients={POLYMARKET_US_CLIENT_NAME: exec_client_config},
        strategies=[],
        exec_algorithms=[],
        exec_engine=LiveExecEngineConfig(inflight_check_interval_ms=0),
        risk_engine=build_trade_risk_engine_config(data_client_config.market_slugs),
    )
    return cast(TradingNodeConfig, config)
