"""The per-``(venue, city)`` NWS ingest Actor.

Governing spec: ``docs/plans/PHASE1_ACTOR_BRIEF.md``. One instance per site,
five in production. It polls the NWS API on a Nautilus timer, routes every
outcome through :mod:`breezy.ingest.routing` into the one
:class:`~breezy.ingest.gate.SettlementGate`, persists settlement-grade records
through :mod:`breezy.persistence.catalog`, and republishes them on the message
bus.

Null hypothesis, checked against the installed ``nautilus-trader==1.231.0``
before a line of this module was written
-----------------------------------------------------------------------------
**Native, and therefore used rather than rebuilt:**

* Timer scheduling -- ``Clock.set_timer(name, interval, callback=...)``. No
  polling loop is hand-rolled.
* Message-bus publication -- ``Actor.publish_data(DataType, Data)``
  (``common/actor.pyx:2813``).
* A durable, write-through key/value seam -- ``Cache.add(str, bytes)`` /
  ``Cache.get(str)`` (``cache/cache.pyx``). This is where the resume cursor
  lives (SS3.3).
* Component lifecycle -- ``on_start`` / ``on_stop``.
* Off-loop execution -- the **stdlib** ``loop.run_in_executor``.

**Genuinely absent, and therefore authored here (with the evidence):**

* *A cross-thread bridge from the timer callback to the event loop.* Measured
  (SS4.1, pinned by ``tests/contract/test_live_timer_thread_affinity.py``): the
  callback runs on a Rust ``_DummyThread`` with **no running loop**, so
  ``asyncio.create_task`` raises. ``asyncio.run_coroutine_threadsafe`` is the
  only primitive that works and returns a supervision handle.
* *Re-subscription / reconnect / task supervision.* ``grep -rn
  'reconnect|resubscribe' live/*.py`` in the install returns **zero** hits, and
  ``LiveDataEngine.connect()`` calls ``client.connect()`` exactly once. For a
  polling HTTP client none of the native WebSocket reconnect machinery applies
  -- there is no socket.
* *A resume cursor.* ``grep -c 'resume_cursor' common/actor.pyx`` is **0**.
  ``on_save`` is not a substitute: ``save_state``/``load_state`` are
  ``NautilusKernelConfig`` fields and ``Trader.save()`` runs only from
  ``kernel.stop()``, so on SIGKILL it never runs at all.
* *A data-completeness deadline distinct from a liveness watchdog.* Nothing in
  Nautilus models "today's climate day is complete".

**Deliberately NOT used, with the measurement that ruled it out:**

* ``Actor.run_in_executor`` (F2). ``common/actor.pyx:1047-1067`` returns a
  ``TaskId``; in no-executor mode the callable's return value is discarded
  outright, and no result channel is reachable through the ``Actor`` public
  API. It cannot host work whose result this Actor needs.
* ``DataEngine`` catalog registration and ``request_data`` (F1, F3). F3 is the
  dangerous one: ``_query_catalog`` stops at the first registered catalog that
  returns rows, so with one catalog root per station -- which trap 21 forces,
  because a custom type without ``instrument_id`` writes flat -- stations 2..N
  would silently warm-start from station 1's records. **Zero catalogs are
  registered.** Consequently ``on_historical_data`` is never called and is not
  defined here as dead code.

Threading contract (SS4.1, and it is load-bearing)
--------------------------------------------------
``SqliteStateStore`` is **thread-confined** (``runtime/sqlite_store.py:72-79``:
any access from a thread other than the constructing one raises). The
:class:`~breezy.ingest.gate.SettlementGate` and
:class:`~breezy.ingest.product_index.ProductIntegrityIndex` both sit on it. So:

* ``on_poll_timer`` runs on the Rust thread and does exactly two things --
  submit and return. It mutates no Actor state and touches no store.
* ``_on_poll_done`` runs on the **completing** thread (measured: ``MainThread``
  normally, the tokio thread when the future is already done at attach time).
  It therefore marshals the gate call back onto the loop with
  ``call_soon_threadsafe`` rather than calling the gate inline. Without that
  hop a real deployment raises ``RuntimeError`` out of the store on the first
  failed poll -- i.e. supervision would itself fail exactly when supervision
  matters.
* Executor work is restricted to catalog I/O and the pure ``normalize``
  parsers. Neither touches the store.

What runs off the loop, and why that and not the parse (SS3.1)
--------------------------------------------------------------
The parse is bounded (128 KiB transport cap, structural allowlist ahead of
every regex, 0.33 ms measured worst case). The catalog path is not: ``os.open``
+ ``fcntl.flock``, two pyarrow read-backs inside ``write_records``, and a
warm-start read over the whole station catalog that **grows monotonically with
retention**. That is what would freeze the loop -- and with it every venue
heartbeat in the process. Catalog I/O therefore runs on a
``ThreadPoolExecutor`` via the stdlib ``loop.run_in_executor``.

The parse is *also* dispatched to that executor, but for a different reason:
SS6 requires a real wall-clock ceiling on it, and ``asyncio.wait_for`` needs an
awaitable -- it cannot bound a synchronous call. Honest limit: a Python thread
cannot be killed, so a genuinely wedged parse keeps a worker thread but no
longer holds the event loop, and the site hard-blocks on
``OVERSIZE_OR_PARSE_TIMEOUT`` either way.

Retention assumption behind the unbounded reads
------------------------------------------------
``read_climate_days`` and ``read_raw_products`` read a station's whole catalog.
The budget is ~2 records per climate day per station (one preliminary, one
final), i.e. ~730/year -- so the warm-start read and the ``revision_seq``
lookup stay small for years. If retention policy changes, both become
unbounded and need a bounded accessor; that is a stated assumption, not a
proof.

Standing constraints honoured here (SS8)
-----------------------------------------
NautilusTrader is immutable: this module subclasses ``Actor`` and calls its
public API only. No credential, host, User-Agent or personal identifier appears
in this source -- the transport owns all of that, and the Actor never
constructs a URL (it passes a registry-sourced CLI location and a UUID).
Every catalog path component derives from the registry object and a typed date,
never from parsed product text.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime as dt
import json
import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Final
from zoneinfo import ZoneInfo

from nautilus_trader.common.actor import Actor
from nautilus_trader.core.data import Data
from nautilus_trader.model.data import DataType
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.nws_raw_product import NwsRawProduct
from breezy.ingest.config import NwsIngestActorConfig
from breezy.ingest.gate import GateReason, SettlementGate
from breezy.ingest.http import FetchResult, TransportError
from breezy.ingest.nws_envelope import (
    DiscoveryEntry,
    NwsEnvelopeError,
    NwsEnvelopeStructureError,
    ProductEnvelope,
    parse_discovery_list,
    parse_product_envelope,
)
from breezy.ingest.product_index import ProductIntegrityIndex
from breezy.ingest.records import build_climate_day, build_raw_product
from breezy.ingest.routing import (
    GateAction,
    PollOutcome,
    RouteDecision,
    Severity,
    route_catalog_error,
    route_fetch_result,
    route_parse_failure,
    route_sanity_violation,
    route_transport_error,
    route_unhandled_exception,
    route_write_outcome,
)
from breezy.ingest.shared_state import SharedIngestState
from breezy.normalize.classify import (
    ClassificationError,
    classify_issuance,
    has_correction_evidence,
)
from breezy.normalize.cli_parse import (
    CliParseError,
    CliStructuralHeader,
    ParsedCliProduct,
    check_structural_allowlist,
    parse_cli_product,
)
from breezy.normalize.climate_day import standard_time_zone
from breezy.normalize.sanity import CliSanityError
from breezy.persistence.catalog import (
    WriteOutcome,
    open_station_catalog,
    read_climate_days,
    read_raw_products,
    write_records,
)

__all__ = [
    "CURSOR_KEY_PREFIX",
    "PARSER_VERSION",
    "VALIDATORS_KEY_PREFIX",
    "NwsIngestActor",
    "nws_climate_day_data_type",
    "nws_raw_product_data_type",
]

logger = logging.getLogger(__name__)

#: Provenance of the code that produced a `ParsedCliProduct`. Stored on every
#: settlement record so a later parser change is attributable.
PARSER_VERSION: Final[str] = "breezy.normalize.cli_parse@0.1.0"

CURSOR_KEY_PREFIX: Final[str] = "breezy:nws:cursor:"
VALIDATORS_KEY_PREFIX: Final[str] = "breezy:nws:validators:"

#: Staleness thresholds, derived from the configured poll interval rather than
#: from new config fields. Four missed intervals is a degrade; twelve is a
#: block. Both are multipliers on the ONE cadence the site actually has, so a
#: site polling every five minutes and one polling every hour get proportionate
#: watchdogs without a second knob to keep in sync.
STALENESS_DEGRADE_INTERVALS: Final[int] = 4
STALENESS_BLOCK_INTERVALS: Final[int] = 12

#: The Actor owns the retry window; the gate only records its outcome
#: (`record_transient_failure(final_window_elapsed=...)`, mirroring the
#: `conflict_window_elapsed` precedent).
DEFAULT_TRANSIENT_RETRY_WINDOW_NS: Final[int] = 3600 * 1_000_000_000
DEFAULT_MAX_BACKOFF_NS: Final[int] = 1800 * 1_000_000_000

_NS_PER_SECOND: Final[int] = 1_000_000_000
_MAX_BACKOFF_EXPONENT: Final[int] = 16

#: `(ts_init, record class name, raw_sha256)`. See `record_cursor`.
Cursor = tuple[int, str, str]


# ---------------------------------------------------------------------------
# The shared DataType factories
# ---------------------------------------------------------------------------
#
# Trap 4/20: `DataType.topic` builds the routing topic from metadata by
# INSERTION ORDER, while `DataType.__eq__`/`__hash__` compare a `frozenset` and
# therefore ignore order. Equality-based unit tests pass while production
# delivers zero messages. The only defence is one shared factory per type,
# used by the live path, the warm-start path and any `BacktestDataConfig`.
#
# Phase 1 carries NO metadata, deliberately: a metadata-bearing subscriber
# never receives a metadata-less publication, so an empty metadata mapping here
# and an omitted `BacktestDataConfig(metadata=...)` there match by
# construction.


@lru_cache(maxsize=1)
def nws_climate_day_data_type() -> DataType:
    """The ONE `DataType` for `NwsClimateDay`. Never construct another."""
    return DataType(NwsClimateDay)


@lru_cache(maxsize=1)
def nws_raw_product_data_type() -> DataType:
    """The ONE `DataType` for `NwsRawProduct`. Never construct another."""
    return DataType(NwsRawProduct)


class _AbortPoll(Exception):
    """Internal control flow: this poll's batch stops here.

    Raised only *after* the gate has already been driven by the handler that
    raised it, so it carries no routing information of its own and never
    escapes this module. It exists so the batch aborts as a unit: see
    :meth:`NwsIngestActor.poll_once` for why a partial batch must not be
    persisted (``record_successful_poll`` clears every per-site block, so one
    good product would launder away the block a sibling just earned) and why
    the integrity index must not be written before the abort is known (an
    observed uuid is deduped away forever on the next poll).
    """


@dataclass(frozen=True, slots=True)
class _PreparedProduct:
    """One product that passed SS6 steps 5-7 and is ready to persist."""

    fetch: FetchResult
    envelope: ProductEnvelope
    header: CliStructuralHeader
    parsed: ParsedCliProduct


def _data_type_for(record: Data) -> DataType:
    if isinstance(record, NwsClimateDay):
        return nws_climate_day_data_type()
    if isinstance(record, NwsRawProduct):
        return nws_raw_product_data_type()
    raise TypeError(f"no shared DataType factory for {type(record).__name__}")


# ---------------------------------------------------------------------------
# The Actor
# ---------------------------------------------------------------------------


class NwsIngestActor(Actor):
    """Polls, validates, persists and republishes one site's NWS CLI products.

    Parameters
    ----------
    config : NwsIngestActorConfig
        Scalar-only, msgspec-serialisable site configuration.
    shared : SharedIngestState
        The process-wide container. The Actor **receives** it; it never
        constructs one, and registration at construction proves it holds the
        container's own gate and index rather than private copies (SS3.6).
    refetch_known_products : bool
        Backfill / replay-repair mode. Normally `False`: discovery-time dedupe
        (SS3.4 Job 1) drops every uuid the index already knows, which is what
        prevents both unbounded duplicate accumulation and the crash-induced
        CRIT hard-block. Setting it `True` deliberately re-fetches known ids,
        which is the ONLY situation in which the integrity tripwire (Job 2) can
        fire at all.
    """

    def __init__(
        self,
        config: NwsIngestActorConfig,
        *,
        shared: SharedIngestState,
        parser_version: str = PARSER_VERSION,
        transient_retry_window_ns: int = DEFAULT_TRANSIENT_RETRY_WINDOW_NS,
        max_backoff_ns: int = DEFAULT_MAX_BACKOFF_NS,
        refetch_known_products: bool = False,
    ) -> None:
        super().__init__(config)
        self._config = config
        self._shared = shared
        self._venue = config.venue
        self._city = config.city
        self._parser_version = parser_version
        self._transient_retry_window_ns = transient_retry_window_ns
        self._max_backoff_ns = max_backoff_ns

        self.refetch_known_products = refetch_known_products

        registry = shared.registry
        self._site = registry.settlement_site(self._venue, self._city)
        self._window = registry.climate_day_window(self._venue, self._city)
        self._deadline = registry.settlement_deadline(self._venue, self._city)
        self._registry_version = registry.registry_version

        # Two mechanisms guard the shared-instance invariant; this is the
        # second. A container makes a duplicate impossible; this makes an Actor
        # that built its OWN gate fail at startup rather than trade against
        # private state.
        shared.register_site_actor(
            self._venue,
            self._city,
            component_id=str(self.id),
            gate=shared.gate,
            product_index=shared.product_index,
        )

        self._loop: asyncio.AbstractEventLoop | None = None
        self._timers_armed = False
        self._catalog: ParquetDataCatalog | None = None
        self._cursor: Cursor | None = None
        self._cursor_loaded = False

        self._backoff_until_ns = 0
        self._transient_streak = 0
        self._transient_streak_started_ns: int | None = None

        # A worker per Actor, not a shared pool: a wedged parse on one site
        # must not starve the other four. Two workers so a timed-out (and
        # therefore unkillable) parse thread cannot block the subsequent
        # catalog write on the same executor.
        self._executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix=f"breezy-nws-{self._venue}-{self._city}"
        )

        # Injectable seams. Held as attributes so a test can substitute one
        # without patching module globals -- and, more importantly, so the
        # catalog write path is a single named collaborator rather than a
        # call buried mid-coroutine.
        self.write_records: Callable[[ParquetDataCatalog, Sequence[Data]], WriteOutcome] = (
            write_records
        )
        self.parse_cli_product: Callable[..., ParsedCliProduct] = parse_cli_product
        self.classify_issuance: Callable[[str], str] = classify_issuance

    # -- read-only accessors -------------------------------------------

    @property
    def gate(self) -> SettlementGate:
        return self._shared.gate

    @property
    def product_index(self) -> ProductIntegrityIndex:
        return self._shared.product_index

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        """The loop captured in :meth:`on_start`, or `None` in a backtest."""
        return self._loop

    @property
    def poll_timer_armed(self) -> bool:
        return self._timers_armed

    @property
    def resume_cursor(self) -> Cursor | None:
        if not self._cursor_loaded:
            self._cursor = self._load_cursor()
            self._cursor_loaded = True
        return self._cursor

    @property
    def staleness_degraded_after_ns(self) -> int:
        return (
            int(self._config.poll_interval_seconds)
            * STALENESS_DEGRADE_INTERVALS
            * _NS_PER_SECOND
        )

    @property
    def staleness_blocked_after_ns(self) -> int:
        return (
            int(self._config.poll_interval_seconds)
            * STALENESS_BLOCK_INTERVALS
            * _NS_PER_SECOND
        )

    # -- lifecycle ------------------------------------------------------

    def on_start(self) -> None:
        """Capture the loop, warm-start, and arm both timers.

        The loop reference comes from ``asyncio.get_running_loop()`` here and
        nowhere else: base ``Actor`` exposes no loop attribute at all, and the
        only other route is ``ActorExecutor._loop``, a private attribute. In a
        **backtest** this raises, which is the correct signal that the bridge
        is not needed -- and this Actor then arms no poll timer, so a backtest
        performs no network I/O by construction rather than by discipline.
        """
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None
            logger.info(
                "no running event loop for %s/%s: backtest mode, no polling armed",
                self._venue,
                self._city,
            )
            return

        # Supervised exactly like the timer-path coroutines below: a warm
        # start that raises (corrupt catalog, permission error, disk full)
        # must reach the settlement gate, not vanish as "Task exception was
        # never retrieved". `_submit` already retains the strong reference
        # `run_coroutine_threadsafe` needs (via `_chain_future`'s done-
        # callback chain) and routes any exception through `_on_poll_done` ->
        # `_record_task_death` -> the gate -- reused as-is rather than
        # duplicated, so warm start and poll share one supervision path.
        self._submit(self.warm_start())
        self._arm_timers()

    def on_stop(self) -> None:
        self._cancel_timers()

    def on_dispose(self) -> None:
        self.shutdown_executor()

    def shutdown_executor(self) -> None:
        """Release the worker threads. Idempotent."""
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _arm_timers(self) -> None:
        if self._timers_armed:
            return
        self.clock.set_timer(
            name=self._poll_timer_name,
            interval=timedelta(seconds=int(self._config.poll_interval_seconds)),
            callback=self.on_poll_timer,
        )
        # SS6: the data-completeness deadline is scheduled on a WALL CLOCK,
        # independent of poll outcome. It is the only orthogonal defence
        # against a perpetual-304 staleness attack, where every poll succeeds,
        # `last_successful_poll_ns` keeps resetting, the liveness watchdog
        # stays satisfied indefinitely, and no record is ever written.
        self.clock.set_timer(
            name=self._deadline_timer_name,
            interval=timedelta(
                seconds=int(self._config.final_deadline_check_interval_seconds)
            ),
            callback=self.on_deadline_timer,
        )
        self._timers_armed = True

    def _cancel_timers(self) -> None:
        if not self._timers_armed:
            return
        for name in (self._poll_timer_name, self._deadline_timer_name):
            try:
                self.clock.cancel_timer(name)
            except (KeyError, ValueError):  # pragma: no cover - defensive
                logger.debug("timer %s was already cancelled", name)
        self._timers_armed = False

    @property
    def _poll_timer_name(self) -> str:
        return f"nws-poll-{self._venue}-{self._city}"

    @property
    def _deadline_timer_name(self) -> str:
        return f"nws-final-deadline-{self._venue}-{self._city}"

    # -- the cross-thread bridge (SS4.1) ---------------------------------

    def on_poll_timer(self, event: object) -> None:
        """Timer callback. Runs on a Rust ``_DummyThread``: submit and return.

        Measured, and each line encodes one of the four hazards:

        * there is **no running loop** on this thread, so ``create_task``
          raises -- ``run_coroutine_threadsafe`` is the primitive;
        * Rust **swallows** anything raised here (the only trace is a
          ``nautilus_common::timer`` ERROR log), so supervision must be the
          returned handle, not an escaping exception;
        * two distinct OS thread idents were observed across fires and
          simultaneity was not disproven, so no Actor state is mutated here;
        * ``run_coroutine_threadsafe`` raises if the loop is closed. That guard
          returns **quietly**: a shutdown race is not a settlement event, and
          tripping the gate on it would block a site every time the process
          stops.
        """
        self._submit(self.poll_once())

    def on_deadline_timer(self, event: object) -> None:
        """Timer callback for the data-completeness clock. Same bridge rules."""
        self._submit(self.check_final_deadline())

    def _submit(self, coro: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            coro.close()
            return
        try:
            future = asyncio.run_coroutine_threadsafe(coro, loop)
        except RuntimeError:  # pragma: no cover - shutdown race
            coro.close()
            return
        future.add_done_callback(self._on_poll_done)

    def _on_poll_done(self, future: concurrent.futures.Future[None]) -> None:
        """Supervision. Runs on the **completing** thread, not necessarily the
        loop -- so the gate call is marshalled back rather than made inline.

        This is not defensive tidiness. ``SqliteStateStore`` confines itself to
        its constructing thread and raises otherwise, so an inline gate call
        here would raise out of the supervision path precisely when a poll has
        already failed: the gate would never reach BLOCKED and the site would
        keep reading OPEN over stale data.
        """
        if future.cancelled():
            return
        exc = future.exception()
        if exc is None:
            return
        loop = self._loop
        if loop is None or loop.is_closed():  # pragma: no cover - shutdown race
            logger.critical("poll task died after loop close: %r", exc)
            return
        loop.call_soon_threadsafe(self._record_task_death, exc)

    def _record_task_death(self, exc: BaseException) -> None:
        logger.critical(
            "poll task for %s/%s died: %r", self._venue, self._city, exc, exc_info=exc
        )
        self._execute(route_unhandled_exception(exc))

    # -- SS6 step 1: may we perform network I/O? --------------------------

    def network_allowed(self) -> bool:
        """The **narrow** predicate, and getting it wrong bricks the system.

        This is deliberately NOT ``require_open``. The settlement gate is a
        *use-time* gate consumed by the settlement resolver. It defaults to
        BLOCKED until a successful poll, and ``record_successful_poll`` is only
        reachable *from* a poll -- so "a blocked site does not poll" deadlocks
        on first boot and never recovers. Worse, every per-site block
        (parser_failure, sanity_violation, transient_blocked, task_dead,
        write_integrity_violation, stale_blocked, ...) clears *only* on a
        successful poll, so the same rule would turn one transient hiccup into
        a permanent outage requiring a database edit.

        Only two things genuinely forbid network I/O:

        1. the **global** ``ua_trap_blocked`` latch -- polling on into a UA trap
           is what costs us API access outright;
        2. an active backoff window we ourselves set.

        ``blocking_causes`` is used rather than ``status().reason`` because
        ``reason`` is the most recent transition *event*, not the current root
        cause: a successful poll on a UA-trapped site logs
        ``reason=SUCCESSFUL_POLL`` while the latch is still active.
        """
        if GateReason.UA_TRAP_403 in self.gate.blocking_causes(self._venue, self._city):
            logger.warning(
                "skipping poll for %s/%s: global UA-trap latch is set",
                self._venue,
                self._city,
            )
            return False
        if self._now() < self._backoff_until_ns:
            logger.info(
                "skipping poll for %s/%s: backing off until %d",
                self._venue,
                self._city,
                self._backoff_until_ns,
            )
            return False
        return True

    # -- SS6: the poll sequence ------------------------------------------

    async def poll_once(self) -> None:
        """One full poll: SS6 steps 1-12.

        **Stage B is batched, and that is a deliberate reading of step 4.**
        The brief notes there that a single poll may yield several unfetched
        ids and that ``write_records`` requires non-decreasing ``ts_init``
        *within a batch* -- a requirement that only bites if a batch is
        actually written. Writing one product per call was tried and is
        **wrong**: two products retrieved inside one clock tick share a
        ``retrieved_at_ns``, so the second write is an exact ``ts_init``-range
        rewrite, which the catalog discards **silently** with a bare ``print``
        (``parquet.py:378-380``) and reports as ``skipped`` -- routing straight
        to ``record_write_integrity_violation``, CRIT, hard-block. Observed
        for real: a preliminary and a final ingested in one poll blocked the
        site and lost one record. One batch, one write, one parquet file per
        type covering that range.

        The batch also **aborts as a unit** on any hard failure, and step 8
        moves inside the batch phase for that reason: if a later product fails
        validation, nothing earlier has been observed into the integrity index
        yet, so every product in the aborted batch is still re-fetchable on the
        next poll. Observing first and aborting after would dedupe those ids
        away permanently -- a settlement record silently never ingested.
        Persisting a partial batch and recording success would be worse still:
        ``record_successful_poll`` clears every per-site block, so one good
        product would launder away the block a sibling product just earned.
        """
        self.check_staleness()
        if not self.network_allowed():
            return

        etag, last_modified = self._load_validators()
        try:
            result = await self._shared.transport.fetch_discovery_list(
                self._site.cli_location,
                if_none_match=etag,
                if_modified_since=last_modified,
            )
        except TransportError as exc:
            self._execute(route_transport_error(exc))
            return

        decision = route_fetch_result(result)
        if decision.outcome is PollOutcome.NOT_MODIFIED:
            # Terminal branch, NOT step 9. Freshness is satisfied; there is no
            # body, so no record, no digest, no cursor movement. A 304 produces
            # no `WriteOutcome`, so it must never pass through anything gated
            # on `is_complete`.
            self._store_validators(result)
            self._execute(decision)
            return
        if not decision.proceed:
            self._execute(decision)
            return

        self._store_validators(result)
        try:
            entries = self._parse_discovery(result)
        except (NwsEnvelopeError, ValueError) as exc:
            self._block_bad_body("discovery list", exc)
            return

        pending = self._undeduped(entries)
        if not pending:
            # SS6 step 4: nothing new. The poll genuinely succeeded, so
            # freshness is satisfied -- this is the routine steady state.
            self.gate.record_successful_poll(
                self._venue,
                self._city,
                detail=f"discovery list carried {len(entries)} product(s), none new",
            )
            self._on_successful_poll()
            return

        # Fetch in issuance order so retrieval order -- and therefore
        # `ts_init` order -- follows issuance order, keeping a preliminary and
        # a final ingested in one poll in a meaningful sequence rather than an
        # arbitrary one.
        prepared: list[_PreparedProduct] = []
        try:
            for entry in sorted(pending, key=lambda e: e.issuance_time_ns):
                candidate = await self._prepare_product(entry)
                if candidate is not None:
                    prepared.append(candidate)
        except _AbortPoll:
            # The gate has already been driven by the handler that raised.
            return

        if not prepared:
            # Every product was a sibling station's (SS5: routine). Recording
            # anything here would manufacture an outage out of normal
            # operation -- and `record_successful_poll` would be worse, since
            # sibling products would keep this site "fresh" forever while
            # neither the staleness watchdog nor FINAL_CLI_OVERDUE fired.
            return

        # -- step 8: the integrity tripwire, for the whole batch.
        for candidate in prepared:
            if not self._observe_integrity(candidate):
                return

        # -- steps 9-11.
        try:
            records = await self._persist_batch(prepared)
        except ValueError as exc:
            # A builder consistency failure (window/site mismatch, station
            # disagreement, a final whose `ts_event` post-dates its
            # `ts_init`). These are misclassification detectors, not
            # tolerances.
            self.gate.record_parser_failure(
                self._venue, self._city, detail=f"{type(exc).__name__}: {exc}"
            )
            return
        except BaseException as exc:  # noqa: BLE001 - routed by exact type
            self._execute(route_catalog_error(exc))
            return

        if records is None:
            return

        # -- step 12: publish, then advance the cursor.
        self._publish_records(records)
        self._record_final_if_final(records)

    def _parse_discovery(self, result: FetchResult) -> tuple[DiscoveryEntry, ...]:
        text = result.text
        if text is None:  # pragma: no cover - guaranteed by FetchResult
            raise ValueError("a non-304 FetchResult must carry text")
        if len(text.encode("utf-8")) > int(self._config.discovery_max_bytes):
            raise ValueError(
                f"discovery list is larger than the configured "
                f"{self._config.discovery_max_bytes}-byte cap"
            )
        payload = json.loads(text)
        if not isinstance(payload, dict):
            # `NwsEnvelopeStructureError` rather than a bare `TypeError`, and
            # this is load-bearing rather than stylistic: the caller catches
            # the envelope module's own error family to route a malformed body
            # as a data-quality block. A `TypeError` would escape that handler
            # into task-death supervision, which claims the wrong cause -- the
            # body was bad, the poll task was fine.
            raise NwsEnvelopeStructureError(
                f"discovery list must be a JSON object, got {type(payload).__name__}"
            )
        return parse_discovery_list(payload)

    def _undeduped(self, entries: Sequence[DiscoveryEntry]) -> list[DiscoveryEntry]:
        """SS3.4 Job 1 -- ordinary dedupe, and it is mandatory.

        Without it the discovery list returns the same id every poll, each
        re-fetch gets a fresh ``retrieved_at_ns`` and therefore a fresh
        ``ts_init``, and the write **succeeds** -- appending a duplicate
        ``NwsRawProduct``, verbatim ``raw_text`` and all, every cycle. The
        alternative branch is worse: an exact ``ts_init``-range collision makes
        ``write_records`` report ``skipped``, which routes to
        ``record_write_integrity_violation`` -- CRIT, hard-block. So an
        ungraceful crash right after a successful write would hard-block the
        site on its next poll.

        Keyed by ``product_uuid`` and answered by ``known_digest``: cheap, no
        body required, and it happens *before* the product fetch.
        """
        if self.refetch_known_products:
            return list(entries)
        return [
            entry
            for entry in entries
            if self.product_index.known_digest(entry.product_uuid) is None
        ]

    async def _prepare_product(self, entry: DiscoveryEntry) -> _PreparedProduct | None:
        """SS6 steps 5-7 for one product: fetch, structural allowlist, parse,
        classify, sanity-bound validation.

        Returns `None` for a **routine** sibling-station product -- one WFO
        issues several cities' CLIs, so `CLIJFK` arriving on the NYC poll is
        expected on a healthy system. Raises :class:`_AbortPoll` for every real
        failure, after driving the gate.
        """
        try:
            result = await self._shared.transport.fetch_product(entry.product_uuid)
        except TransportError as exc:
            self._execute(route_transport_error(exc))
            raise _AbortPoll from exc

        decision = route_fetch_result(result)
        if not decision.proceed:
            # An unsolicited 304 on a product fetch lands here as a contract
            # violation rather than a quiet success: closing the signature
            # stops us *asking* for one, but a buggy origin or an intermediate
            # cache can still volunteer one, and that would take the identical
            # silent-staleness route.
            self._execute(decision)
            raise _AbortPoll

        try:
            envelope = self._parse_envelope(result)
        except (NwsEnvelopeError, ValueError) as exc:
            self._block_bad_body("product envelope", exc)
            raise _AbortPoll from exc

        # -- step 6: the structural allowlist, ALONE and ahead of the parser.
        try:
            header = await self._bounded(
                lambda: check_structural_allowlist(
                    envelope.product_text, cli_location=self._site.cli_location
                )
            )
        except TimeoutError as exc:
            self._record_parse_timeout("structural allowlist")
            raise _AbortPoll from exc
        except CliParseError as exc:
            routed = route_parse_failure(exc)
            self._execute(routed)
            if routed.outcome is PollOutcome.NOT_OUR_PRODUCT:
                return None
            raise _AbortPoll from exc

        # -- step 7: parse, then classify, then sanity-bound validation.
        # Three distinct failure modes with three distinct CRIT reason codes.
        try:
            parsed = await self._bounded(
                lambda: self.parse_cli_product(
                    envelope.product_text,
                    cli_location=self._site.cli_location,
                    body_header_regex=self._site.body_header_regex,
                )
            )
        except TimeoutError as exc:
            self._record_parse_timeout("CLI parse")
            raise _AbortPoll from exc
        except CliSanityError as exc:
            # SS6 step 7's third failure mode, and it reaches us from INSIDE
            # the parser: `parse_cli_product` already runs
            # `check_physical_sanity` (`normalize/cli_parse.py:572`), so
            # re-running it here would be a second copy that can drift. What
            # the Actor owns is the ROUTE, and it is deliberately distinct
            # from a parse failure: the text parsed correctly, so recording
            # PARSER_FAILURE would name the wrong cause in the audit trail an
            # operator reads. `CliSanityError` is not a `CliParseError`
            # precisely so an `except CliParseError` cannot swallow it -- and
            # this clause must therefore sit ABOVE that one, since both are
            # `ValueError` subclasses.
            self._execute(route_sanity_violation(exc))
            raise _AbortPoll from exc
        except CliParseError as exc:
            routed = route_parse_failure(exc)
            self._execute(routed)
            if routed.outcome is PollOutcome.NOT_OUR_PRODUCT:
                return None
            raise _AbortPoll from exc

        try:
            # Classification is the highest-consequence parsing rule in the
            # system -- a preliminary mistaken for a final settles trades on a
            # value NWS has not finalised -- so it is its own step with its own
            # reason code, never folded into "parse".
            issuance = self.classify_issuance(envelope.product_text)
        except ClassificationError as exc:
            self.gate.record_ambiguous_headline(
                self._venue, self._city, detail=f"{type(exc).__name__}: {exc}"
            )
            raise _AbortPoll from exc

        logger.info(
            "%s/%s prepared %s product %s for climate day %s (correction_evidence=%s)",
            self._venue,
            self._city,
            issuance,
            entry.product_uuid,
            parsed.summary_date.isoformat(),
            has_correction_evidence(envelope.product_text),
        )
        return _PreparedProduct(
            fetch=result, envelope=envelope, header=header, parsed=parsed
        )

    def _parse_envelope(self, result: FetchResult) -> ProductEnvelope:
        text = result.text
        if text is None:  # pragma: no cover - guaranteed by FetchResult
            raise ValueError("a non-304 FetchResult must carry text")
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise NwsEnvelopeStructureError(
                f"product envelope must be a JSON object, got {type(payload).__name__}"
            )
        return parse_product_envelope(payload)

    def _observe_integrity(self, prepared: _PreparedProduct) -> bool:
        """SS3.4 Job 2 -- the tripwire, and it should never fire.

        NWS assigns a fresh uuid to every re-issue and ``/products/{id}``
        bodies are immutable by id, so after discovery-time dedupe this can
        only be reached by a *deliberate* re-fetch (backfill, replay repair).
        That is the point: it is a cheap invariant guard on an assumption we do
        not control, and its value is precisely that it costs nothing until the
        assumption breaks. It is not dead code -- do not delete it, and do not
        infer from "it should never fire" that it can be skipped.

        A ``store.get`` that *raises* deliberately propagates rather than
        becoming a MISMATCH: that is still fail-closed (no outcome is returned,
        the poll aborts into task supervision, the site blocks) and it avoids
        latching a sticky CRIT on a transient cache blip.
        """
        digest = prepared.fetch.sha256
        if digest is None:  # pragma: no cover - guaranteed by FetchResult
            raise ValueError("a non-304 FetchResult must carry a digest")
        uuid = prepared.envelope.product_uuid
        observation = self.product_index.observe(uuid, digest)
        if not observation.is_integrity_alarm:
            return True
        # `routing` has no producer for a product-index MISMATCH; the closest
        # exact recorder is the transport integrity alarm, which is the correct
        # severity (CRIT, hard-block) and the correct claim: the datum's digest
        # cannot be trusted.
        self.gate.record_transport_integrity_alarm(
            self._venue,
            self._city,
            detail=f"product-index MISMATCH for {uuid}: {observation.detail}",
        )
        return False

    async def _persist_batch(
        self, prepared: Sequence[_PreparedProduct]
    ) -> tuple[Data, ...] | None:
        """Steps 9-11 for the whole poll. Returns the written records, or
        `None` when the write did not complete (the gate is already driven).
        """
        catalog = self._open_catalog()
        existing = await self._run_off_loop(lambda: read_climate_days(catalog))

        # Monotonic per `(station, climate_day)`, starting at 1, and counted
        # ACROSS the batch as well as against the catalog: two records for one
        # climate day arriving in a single poll must be seq 1 and 2, never 1
        # and 1. No default of `1` -- a silent one would mask a missing
        # increment on a correction, and the settlement resolver re-checks the
        # LATEST revision for a climate day, not the first ingested.
        seq_by_day: dict[dt.date, int] = {}
        for record in existing:
            if record.station != self._site.cli_location:
                continue
            seq_by_day[record.climate_day] = seq_by_day.get(record.climate_day, 0) + 1

        records: list[Data] = []
        for candidate in prepared:
            day = candidate.parsed.summary_date
            seq_by_day[day] = seq_by_day.get(day, 0) + 1
            raw_product = build_raw_product(
                site=self._site,
                registry_version=self._registry_version,
                fetch=candidate.fetch,
                product_text=candidate.envelope.product_text,
                product_uuid=candidate.envelope.product_uuid,
                product_code=candidate.envelope.product_code,
                issuing_office=candidate.envelope.issuing_office,
                wmo_collective_id=candidate.envelope.wmo_collective_id,
                # Line 3 and the line-2 BBB token come from the STRUCTURALLY
                # VALIDATED header, never from the JSON envelope: the NWS API
                # serves neither key, and `parse_product_envelope` correctly
                # returns `None` rather than fabricating one.
                awips_pil=candidate.header.awips_pil,
                wmo_bbb_token=candidate.header.wmo_bbb,
                issuance_time_ns=candidate.envelope.issuance_time_ns,
                climate_day=day,
            )
            climate_day = build_climate_day(
                site=self._site,
                window=self._window,
                raw_product=raw_product,
                parsed=candidate.parsed,
                parser_version=self._parser_version,
                revision_seq=seq_by_day[day],
                # Records are never rewritten, so this is a historical note
                # about what was known at write time, not a selection input.
                is_superseded=False,
            )
            records.append(raw_product)
            records.append(climate_day)

        # `write_records` checks non-decreasing `ts_init` PER TYPE, so the sort
        # only has to be stable within a type. Sorting the whole batch by the
        # cursor key gives that and a deterministic publish order in one step.
        ordered: tuple[Data, ...] = tuple(sorted(records, key=self.record_cursor))
        outcome = await self._run_off_loop(lambda: self.write_records(catalog, ordered))

        decision = route_write_outcome(outcome)
        self._execute(decision)
        if decision.outcome is not PollOutcome.PERSISTED:
            return None
        return ordered


    # -- publication and the resume cursor (SS3.3) ------------------------

    @staticmethod
    def record_cursor(record: Data) -> Cursor:
        """The resume cursor for one record.

        **Not a bare ``ts_init``.** An ``NwsClimateDay`` and the
        ``NwsRawProduct`` it was parsed from share one ``retrieved_at_ns`` by
        design, and a poll that ingests a preliminary *and* a final after
        downtime may stamp them identically. With a strict ``>`` on ``ts_init``
        alone, a crash after publishing the first and before the second loses
        the second **permanently**. With ``>=``, every warm start re-publishes
        the last record. So the cursor is a tuple, compared **strictly**, and
        the class name plus ``raw_sha256`` give a deterministic total order
        that a catalog read reproduces exactly.
        """
        raw_sha256 = str(record.to_dict()["raw_sha256"])
        return (int(record.ts_init), type(record).__name__, raw_sha256)

    def _publish_records(self, records: Sequence[Data]) -> None:
        for record in sorted(records, key=self.record_cursor):
            cursor = self.record_cursor(record)
            if self.resume_cursor is not None and cursor <= self.resume_cursor:
                continue
            self.publish_data(_data_type_for(record), record)
            # Durability follows the publish immediately, so the window
            # SS3.3 recovers is one record wide rather than one poll wide.
            self._save_cursor(cursor)

    def _record_final_if_final(self, records: Sequence[Data]) -> None:
        for record in records:
            if isinstance(record, NwsClimateDay) and record.is_final:
                self.gate.record_final_received(
                    self._venue, self._city, record.climate_day.isoformat()
                )

    async def warm_start(self) -> None:
        """SS3.2: read this Actor's OWN catalog and republish past the cursor.

        Deliberately not ``request_data``. F1 drops the metadata so a
        warm-start response would publish on a topic a metadata-bearing
        subscription cannot match, and F3 answers from the **first** registered
        catalog that returns rows -- so with one catalog root per station,
        stations 2..N would warm-start from station 1's records. That is
        confidently wrong data. Zero catalogs are registered, ``request_data``
        is never called, and ``on_historical_data`` is therefore never invoked
        and does not exist here.

        The republish goes through the SAME shared ``DataType`` factory the
        live path uses, so live and replay topics match by construction.
        """
        catalog = self._open_catalog()
        records = await self._run_off_loop(
            lambda: [*read_climate_days(catalog), *read_raw_products(catalog)]
        )
        if not records:
            return
        for record in sorted(records, key=self.record_cursor):
            cursor = self.record_cursor(record)
            if self.resume_cursor is not None and cursor <= self.resume_cursor:
                continue
            self.publish_data(_data_type_for(record), record)
            self._save_cursor(cursor)

    def reset_cursor(self) -> None:
        """Rewind to "nothing published". Operational replay-repair tool."""
        self._cursor = None
        self._cursor_loaded = True
        self.cache.add(self._cursor_key, b"")

    @property
    def _cursor_key(self) -> str:
        return f"{CURSOR_KEY_PREFIX}{self._venue}:{self._city}"

    def _load_cursor(self) -> Cursor | None:
        raw = self.cache.get(self._cursor_key)
        if not raw:
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
            return (int(payload[0]), str(payload[1]), str(payload[2]))
        except (ValueError, TypeError, IndexError, KeyError):
            # Fail closed by REPLAYING rather than by skipping: an
            # unreadable cursor must never be read as "everything was already
            # published". Over-publication is idempotent for subscribers;
            # silent loss of a settlement record is not.
            logger.error(
                "corrupt resume cursor for %s/%s; replaying from the beginning",
                self._venue,
                self._city,
            )
            return None

    def _save_cursor(self, cursor: Cursor) -> None:
        """Persist through ``Cache.add`` -- write-through per mutation.

        ``on_save`` is the wrong home and this was measured: ``save_state`` /
        ``load_state`` are ``NautilusKernelConfig`` fields, not ``ActorConfig``
        fields, and ``Trader.save()`` is called **only** from ``kernel.stop()``
        / ``stop_async()``. On SIGKILL, OOM or host loss it never runs, so a
        cursor kept there is frozen at the last *graceful* shutdown -- possibly
        never written at all.
        """
        self._cursor = cursor
        self._cursor_loaded = True
        self.cache.add(self._cursor_key, json.dumps(list(cursor)).encode("utf-8"))

    # -- conditional-GET validators ---------------------------------------

    @property
    def _validators_key(self) -> str:
        return f"{VALIDATORS_KEY_PREFIX}{self._venue}:{self._city}"

    def _load_validators(self) -> tuple[str | None, str | None]:
        raw = self.cache.get(self._validators_key)
        if not raw:
            return (None, None)
        try:
            payload = json.loads(raw.decode("utf-8"))
            etag = payload.get("etag")
            last_modified = payload.get("last_modified")
        except (ValueError, AttributeError):
            return (None, None)
        return (
            etag if isinstance(etag, str) else None,
            last_modified if isinstance(last_modified, str) else None,
        )

    def _store_validators(self, result: FetchResult) -> None:
        """Persist the validators the origin actually sent.

        Only overwritten when the header is present: a 304 that omits its
        ``ETag`` must not erase the one that produced it, or the next poll
        silently becomes unconditional. The values are stored raw and are
        re-validated by the transport (charset and length) before they reach a
        socket -- a malformed one raises ``InvalidCacheValidatorError`` and
        routes as an integrity alarm, because a stored validator is remote data
        we echo back into an outbound request header.
        """
        etag, last_modified = self._load_validators()
        new_etag = result.headers.get("etag")
        new_last_modified = result.headers.get("last-modified")
        if new_etag is None and new_last_modified is None:
            return
        payload = {
            "etag": new_etag if new_etag is not None else etag,
            "last_modified": (
                new_last_modified if new_last_modified is not None else last_modified
            ),
        }
        self.cache.add(self._validators_key, json.dumps(payload).encode("utf-8"))

    # -- watchdogs ---------------------------------------------------------

    def check_staleness(self) -> None:
        """Data-staleness alarm on the polled channel.

        ``check_freshness`` has deliberately no recovery branch: freshness is
        *defined* by a recent successful poll, and ``record_successful_poll``
        is the only legitimate way staleness clears. A clock that moves
        backwards fails the site closed with its own reason rather than being
        silently clamped -- a non-monotonic clock invalidates every freshness
        threshold and every ``ts_init`` ordering assumption in the system.
        """
        self.gate.check_freshness(
            self._venue,
            self._city,
            degraded_after_ns=self.staleness_degraded_after_ns,
            blocked_after_ns=self.staleness_blocked_after_ns,
        )

    async def check_final_deadline(self) -> None:
        """The data-completeness clock, on a wall schedule (SS6, SS5b).

        Distinct from liveness, and it must stay that way at the call site as
        well as in the state machine: a site polling cleanly every five minutes
        and simply never receiving the final stays "fresh" indefinitely, because
        freshness only proves NWS is still answering. ``record_successful_poll``
        does **not** clear an overdue final; only ``record_final_received`` for
        that exact climate day does.

        Keyed by climate day, so a final for yesterday can never clear today's
        block.
        """
        now = self._now()
        climate_day = self._most_recent_completed_climate_day(now)
        deadline_ns = self._settlement_deadline_ns(climate_day)
        if now < deadline_ns:
            return
        if await self._have_final_for(climate_day, as_of_ts_init=now):
            return
        self.gate.record_final_overdue(
            self._venue,
            self._city,
            climate_day.isoformat(),
            deadline_ns,
            detail=(
                f"no final CLI for {self._site.cli_location} {climate_day.isoformat()} "
                f"by the venue deadline"
            ),
        )

    def _most_recent_completed_climate_day(self, now_ns: int) -> dt.date:
        """The last climate day that has definitely ended.

        The climate day runs local **standard** midnight to midnight
        year-round. Deriving it from UTC, or from the DST-following local
        clock, is a settlement-correctness bug of the same class as mistaking a
        preliminary for a final.
        """
        local = dt.datetime.fromtimestamp(
            now_ns // _NS_PER_SECOND,
            tz=standard_time_zone(self._window.std_utc_offset_hours),
        )
        return local.date() - dt.timedelta(days=1)

    def _settlement_deadline_ns(self, climate_day: dt.date) -> int:
        """The venue's settlement instant for ``climate_day``.

        Read from ``settlement_deadline`` -- the DST-following **venue** clock
        (ET for all five cities, including the three that are not in ET) -- and
        never from ``climate_day_window``, which is the fixed standard-time
        offset used for the climate-day boundary and nothing else. They are
        separate accessors returning separate types precisely so this cannot be
        gotten wrong by autocomplete.
        """
        hour_text, minute_text = self._deadline.settlement_time_local.split(":")
        when = dt.datetime.combine(
            climate_day + dt.timedelta(days=1),
            dt.time(int(hour_text), int(minute_text)),
            tzinfo=ZoneInfo(self._deadline.settlement_timezone),
        )
        return int(when.timestamp()) * _NS_PER_SECOND

    async def _have_final_for(self, climate_day: dt.date, *, as_of_ts_init: int) -> bool:
        """Durable answer, read off the catalog rather than off process memory.

        An in-memory "we saw the final" set would silently reset on restart and
        re-block a site that is actually complete. The settlement accessor is
        used, not the truth accessor: this asks what the venue should have
        settled on, not what we believe now.
        """
        from breezy.persistence.catalog import read_climate_day_as_of_settlement

        catalog = self._open_catalog()
        record = await self._run_off_loop(
            lambda: read_climate_day_as_of_settlement(
                catalog,
                station=self._site.cli_location,
                climate_day=climate_day,
                as_of_ts_init=as_of_ts_init,
            )
        )
        return record is not None and record.is_final

    # -- routing execution -------------------------------------------------

    def _execute(self, decision: RouteDecision) -> None:
        """Drive the gate from one routed decision.

        ``GateAction.value`` is the literal recorder name, so dispatch is
        ``getattr``. Two flags must not be conflated:

        * ``action_is_deferred`` (only on FETCHED) -- do **not** call
          ``record_successful_poll`` yet; that is step 11, gated behind
          ``WriteOutcome.is_complete``. Calling it on the fetch would open the
          gate over data that has not been persisted or verified.
        * ``action is None`` -- call **no** recorder at all. Exactly one
          outcome uses it (a sibling station's product), and recording anything
          there would manufacture an outage out of normal operation.
        """
        self._log_decision(decision)
        self._update_backoff(decision)

        if decision.action is None or decision.action_is_deferred:
            return

        kwargs: dict[str, Any] = {"detail": decision.detail}
        if decision.needs_cross_site_burst_signal:
            # The gate owns the UA-trap-vs-abuse decision; the container owns
            # the cross-site timing no single Actor can see. Get this wrong in
            # the safe direction: an unnecessary global halt costs trading
            # time, a missed UA trap costs API access entirely.
            kwargs["cross_site_burst_detected"] = self._shared.observe_forbidden_403(
                self._venue, self._city
            )
        if decision.needs_final_window_signal:
            kwargs["final_window_elapsed"] = self._final_window_elapsed()

        recorder = getattr(self.gate, decision.action.value)
        recorder(self._venue, self._city, **kwargs)

        if decision.action is GateAction.RECORD_SUCCESSFUL_POLL:
            self._on_successful_poll()

    def _log_decision(self, decision: RouteDecision) -> None:
        level = {
            Severity.INFO: logging.INFO,
            Severity.WARNING: logging.WARNING,
            Severity.CRIT: logging.CRITICAL,
        }[decision.severity]
        logger.log(
            level,
            "%s/%s poll outcome=%s action=%s: %s",
            self._venue,
            self._city,
            decision.outcome.value,
            decision.action.value if decision.action else "<none>",
            decision.detail,
        )

    def _on_successful_poll(self) -> None:
        self._transient_streak = 0
        self._transient_streak_started_ns = None
        self._backoff_until_ns = 0

    def _update_backoff(self, decision: RouteDecision) -> None:
        if not decision.is_transient:
            return
        now = self._now()
        self._transient_streak += 1
        if self._transient_streak_started_ns is None:
            self._transient_streak_started_ns = now
        self._backoff_until_ns = now + self._backoff_ns(decision)

    def _backoff_ns(self, decision: RouteDecision) -> int:
        """Honour ``Retry-After`` when the origin sent a usable one.

        The value is carried by routing, never interpreted there: backoff
        timing is the Actor's. A non-integer (HTTP-date) form falls through to
        the exponential schedule rather than being parsed loosely -- guessing
        at a date format on a rate-limit response is how a client turns a
        temporary throttle into a ban.
        """
        if decision.retry_after is not None:
            try:
                seconds = int(decision.retry_after.strip())
            except ValueError:
                seconds = -1
            if seconds >= 0:
                return min(seconds * _NS_PER_SECOND, self._max_backoff_ns)
        # A left shift rather than `2**exponent`: `int.__pow__` is typed to
        # return `Any` (a negative exponent yields a float), which would smuggle
        # an untyped value into a nanosecond deadline under mypy strict. The
        # exponent is also capped so a long outage cannot build an arbitrarily
        # large integer before `min` clamps it.
        exponent = min(max(self._transient_streak - 1, 0), _MAX_BACKOFF_EXPONENT)
        base = int(self._config.poll_interval_seconds) * _NS_PER_SECOND
        return min(base << exponent, self._max_backoff_ns)

    def _final_window_elapsed(self) -> bool:
        started = self._transient_streak_started_ns
        if started is None:
            return False
        return self._now() - started >= self._transient_retry_window_ns

    def _block_bad_body(self, what: str, exc: Exception) -> None:
        """A malformed or hostile body shape is a data-quality failure.

        It blocks the site: the response is not a CLI product, so nothing
        downstream can be trusted to settle on. Failing closed is deliberate --
        "I do not recognise this body" is not evidence that it is benign.
        """
        self.gate.record_parser_failure(
            self._venue,
            self._city,
            detail=f"malformed {what}: {type(exc).__name__}: {exc}",
        )

    def _record_parse_timeout(self, stage: str) -> None:
        """SS6: the 250 ms fuzz ceiling is a CI-time property test, not a
        production circuit-breaker -- nothing there measures real elapsed time.
        This is the runtime guarantee, so the loop's safety stops depending on
        regex authors never regressing.
        """
        self.gate.record_oversize_or_parse_timeout(
            self._venue,
            self._city,
            detail=(
                f"{stage} exceeded the {self._config.parse_timeout_ms} ms ceiling for "
                f"{self._site.cli_location}"
            ),
        )

    # -- plumbing ----------------------------------------------------------

    def _now(self) -> int:
        """The ONE injected nanosecond clock.

        Nautilus gives every Actor its own ``Clock`` object
        (``trading/trader.py:342``), so a signal correlated across Actors --
        the cross-site burst window is one -- must not be timed off any single
        Actor's clock. The container's clock is also the transport's and the
        gate's, so a receipt stamp that becomes ``ts_init`` and the freshness
        watchdog that reads it can never diverge.
        """
        return self._shared.clock()

    def _open_catalog(self) -> ParquetDataCatalog:
        if self._catalog is None:
            base: Path = self._shared.catalog_base
            self._catalog = open_station_catalog(base, self._venue, self._city)
        return self._catalog

    async def _run_off_loop[T](self, fn: Callable[[], T]) -> T:
        """Run blocking work on the worker pool via the **stdlib**
        ``loop.run_in_executor`` -- unaffected by F2, which is about
        ``Actor.run_in_executor``.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(self._executor, fn)

    async def _bounded[T](self, fn: Callable[[], T]) -> T:
        """Run ``fn`` off the loop under a real wall-clock ceiling.

        ``asyncio.wait_for`` needs an awaitable and cannot bound a synchronous
        call, which is why the parse is dispatched to the executor even though
        it is cheap. Honest limit: a Python thread cannot be killed, so a
        genuinely wedged parse keeps a worker but no longer holds the event
        loop -- and the site hard-blocks either way.
        """
        return await asyncio.wait_for(
            self._run_off_loop(fn), int(self._config.parse_timeout_ms) / 1000
        )
