"""The per-``(venue, city)`` NWS ingest Actor.

Governing spec: ``docs/plans/archive/PHASE1_ACTOR_BRIEF.md``. One instance per site,
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
  ``kernel.stop()``, so on SIGKILL it never runs at all. **Nor is ``Cache``**:
  ``Cache.add`` forwards to a database only ``if self._database is not None``
  (``cache/cache.pyx:1704-1708``) and ``cache_general`` resets ``self._general``
  to ``{}`` without one (``:298``), while Breezy sets
  ``CacheConfig(database=None)`` (``runtime/node_config.py:150`` ->
  ``system/kernel.py:310-311``). So the cursor and the conditional-GET
  validators live in ``SharedIngestState.store`` -- Breezy's own durable
  ``SqliteStateStore``, alongside the gate and the product index.
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
import re
from collections.abc import Awaitable, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from zoneinfo import ZoneInfo

from nautilus_trader.common.actor import Actor
from nautilus_trader.core.data import Data
from nautilus_trader.model.data import DataType
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.nws_raw_product import NwsRawProduct
from breezy.ingest import gaps
from breezy.ingest.config import NwsIngestActorConfig
from breezy.ingest.gate import GateReason, GateState, GateStatus, SettlementGate, StateStore
from breezy.ingest.http import REDACTION_MARKER, FetchResult, TransportError
from breezy.ingest.nws_envelope import (
    DiscoveryEntry,
    NwsEnvelopeError,
    NwsEnvelopeStructureError,
    ProductEnvelope,
    parse_discovery_list,
    parse_product_envelope,
)
from breezy.ingest.product_index import (
    CorruptProductIndexEntryError,
    ProductIntegrityIndex,
)
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
from breezy.normalize.sanity import CliSanityError
from breezy.persistence.catalog import (
    WriteOutcome,
    open_station_catalog,
    read_climate_days,
    read_raw_products,
    write_records,
)

if TYPE_CHECKING:  # pragma: no cover - typing only; see `_health` for the cycle.
    from breezy.runtime.health import (
        AlertCondition,
        AlertPayload,
        AlertSink,
        AlertState,
        GapSummary,
        HealthSnapshot,
    )

__all__ = [
    "CURSOR_KEY_PREFIX",
    "DEFAULT_OBSERVABILITY_IO_TIMEOUT_S",
    "LEDGER_UNAVAILABLE",
    "PARSER_VERSION",
    "VALIDATORS_KEY_PREFIX",
    "NwsIngestActor",
    "nws_climate_day_data_type",
    "nws_raw_product_data_type",
]

logger = logging.getLogger(__name__)

#: `AlertCondition.key.kind`/`event` for "this site's gap ledger could not be
#: read or reconciled this cycle".
#:
#: Declared HERE and not in `runtime/health.py` alongside that module's other
#: kind constants, and the asymmetry is deliberate: `health.py` documents
#: itself as importing nothing from `breezy.ingest` and knowing nothing of the
#: ledger's vocabulary, while the condition is raised only from this module's
#: `reconcile_and_report` failure handler. `AlertConditionKey.kind` is a plain
#: `str` by that module's own design ("kept as plain strings (not an `Enum`) so
#: the ... wiring code can construct `AlertConditionKey`s without importing an
#: enum"), so the wiring owning the condition also owns its name.
LEDGER_UNAVAILABLE: Final[str] = "ledger_unavailable"

#: Character ceiling for the scrubbed ledger-failure detail. Deliberately
#: tighter than `health.MAX_ALERT_DETAIL_CHARS` (200): that constant bounds
#: over-collection into a webhook, this one bounds how much attacker- or
#: environment-influenced exception text can be echoed into a DISK artifact
#: whose whole redaction guarantee is otherwise "no field slot exists to hold
#: it".
LEDGER_DETAIL_MAX_CHARS: Final[int] = 120

#: Any whitespace-delimited token containing a path separator, an `@`, or a
#: `:`-scheme-shaped URL is dropped whole rather than trimmed. These are the
#: three shapes that carry the values `runtime/health.py` names as forbidden:
#: absolute state-db/catalog paths (pyarrow and sqlite interpolate them into
#: their messages), and the User-Agent contact address
#: (`breezy-weather-ingest/0.1 (+mailto:<address>)`, which an HTTP-layer
#: failure can echo). Token-granular so the surrounding, developer-authored
#: sentence still reads.
_UNSAFE_DETAIL_TOKEN: Final[re.Pattern[str]] = re.compile(r"\S*[/\\@]\S*")

#: Everything outside this set becomes a space. Bounds the residue after
#: token redaction to plain prose and punctuation -- no newlines (so a
#: multi-line upstream body cannot be pasted in), no control characters (so a
#: log or JSON consumer cannot be steered), no quotes-as-structure games.
_UNSAFE_DETAIL_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9 _.,:;()<>'\[\]=+-]")


def _scrub_failure_detail(exc: BaseException) -> str:
    """Render `exc` as a bounded, redacted one-line summary.

    **Why this exists.** `SiteHealth.ledger_unavailable` and the
    `LEDGER_UNAVAILABLE` alert payload both carry this string, so it lands in
    a 0600 disk artifact AND is POSTed to an operator-configured webhook --
    i.e. off-host. `health.py`'s redaction guarantee is structural ("there is
    no attribute slot to hold `user_agent_contact` or an absolute path"), and
    a free-text field punches a hole straight through it: the source is an
    exception message, which is environment-influenced (sqlite and pyarrow
    interpolate absolute paths) and, one layer up, upstream-influenced (NWS
    product text).

    Containment, in order: the exception CLASS NAME is kept verbatim (it is
    developer-authored and structural, and is what actually names the
    failure); the message is reduced to its FIRST LINE, then path/contact/URL
    tokens are dropped whole, then the residue is restricted to a plain-prose
    character set and length-bounded.

    Honest limit: this bounds and de-identifies echoed text, it does not
    prove an arbitrary message carries no information at all. The guaranteed
    part of the contract is the class name; the message tail is best-effort
    diagnosis under a 120-character ceiling.
    """
    kind = type(exc).__name__
    message = str(exc).split("\n", 1)[0]
    message = _UNSAFE_DETAIL_TOKEN.sub(REDACTION_MARKER, message)
    message = _UNSAFE_DETAIL_CHARS.sub(" ", message)
    message = " ".join(message.split())
    if len(message) > LEDGER_DETAIL_MAX_CHARS:
        message = message[:LEDGER_DETAIL_MAX_CHARS].rstrip() + "..."
    return f"{kind}: {message}" if message else kind


#: Wall-clock ceiling, in seconds, for the observability path's OFF-LOOP
#: blocking calls: the alert fan-out (`emit_alert` ->
#: `WebhookAlertSink.emit` -> a synchronous `httpx` POST, itself 5s-capped) and
#: the snapshot write (`write_snapshot_atomic`: `mkdir` + `chmod` + `fsync` +
#: rename, all uninterruptible on a stalled mount).
#:
#: Not `parse_timeout_ms` (250 ms), which bounds a CPU-bound regex and would
#: fire on any healthy `fsync`; and not unbounded, which is the actual defect
#: this exists to close -- an unbounded `run_in_executor` over a wedged mount
#: parks a worker forever, so `poll_once` never completes, its future never
#: resolves, `_on_poll_done` -> `_record_task_death` never fires and the
#: settlement gate keeps reading OPEN over stale data. Comfortably below the
#: 300s default poll interval, so a breach is a real stall and not a slow disk.
DEFAULT_OBSERVABILITY_IO_TIMEOUT_S: Final[float] = 30.0


def _health() -> Any:
    """Import :mod:`breezy.runtime.health` at CALL time, not import time.

    ``breezy/runtime/__init__.py`` imports ``breezy.runtime.composition``,
    which imports ``NwsIngestActor`` from this module -- so a module-scope
    ``from breezy.runtime.health import ...`` here is a genuine circular
    import, and not a latent one: it was executed and it fails outright with
    *"cannot import name 'NwsIngestActor' from partially initialized module"*
    whenever this module is imported before ``breezy.runtime``.

    Deferring to call time is the same fix :meth:`NwsIngestActor._have_final_for`
    already applies to ``read_climate_day_as_of_settlement``, and it costs one
    ``sys.modules`` hit per poll. The dependency direction stays correct on
    paper too: ``health`` imports neither ``breezy.ingest`` nor anything else
    from ``breezy`` -- it takes plain ``str``/``int``/``bool`` and its own
    ``GapSummary`` -- so this is a wiring edge, never a layering inversion.
    """
    from breezy.runtime import health

    return health


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

#: A site continuously BLOCKED for this many poll intervals raises the
#: `SiteBlocked` alert. Same reasoning as the two multipliers above -- derived
#: from the ONE cadence the site actually has, so there is no second knob to
#: keep in sync, and a five-minute site and an hourly site get proportionate
#: patience without either being configured separately.
SITE_BLOCKED_ALERT_INTERVALS: Final[int] = 4

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
        self.sleep_between_product_fetches: Callable[[float], Awaitable[None]] = asyncio.sleep

        # -- WI-10/WI-12 observability seams (see `reconcile_and_report`).
        #
        # Attributes rather than constructor parameters, matching the three
        # seams above: the Actor is built by `runtime.composition` from a
        # msgspec-serialisable `ActorConfig`, which cannot carry a `Path` or a
        # live `AlertSink`, so the wiring layer sets these after construction.
        #: Where to write the per-cycle `HealthSnapshot`. `None` (the default)
        #: writes no file at all -- an unconfigured deployment must not start
        #: dropping artifacts in the working directory.
        self.health_snapshot_path: Path | None = None
        #: The process-wide `AlertSink`. `None` resolves `LoggingAlertSink`
        #: (or `WebhookAlertSink`, iff `BREEZY_ALERT_WEBHOOK_URL` is set) on
        #: first use and caches it -- so no `httpx.Client` and no TLS context
        #: is ever built for a deployment that configured no webhook.
        self.alert_sink: AlertSink | None = None
        #: The most recently emitted snapshot, for introspection and tests.
        self.last_health_snapshot: HealthSnapshot | None = None

        #: Ceiling for the two off-loop observability calls; see
        #: `DEFAULT_OBSERVABILITY_IO_TIMEOUT_S`. An attribute, like the seams
        #: above, so a test can shorten it without patching module globals.
        self.observability_io_timeout_s: float = DEFAULT_OBSERVABILITY_IO_TIMEOUT_S

        self._alert_state: AlertState | None = None
        #: Mutual exclusion for `poll_once`; see that method's docstring.
        self._poll_in_flight = False
        #: Set by `reconcile_and_report` when `gaps.reconcile` raised, cleared
        #: when it succeeds. Read by `_alert_conditions` to raise
        #: `LEDGER_UNAVAILABLE`, so a swallowed ledger failure is loud.
        self._ledger_failure_detail: str | None = None
        self._blocked_since_ns: int | None = None
        self._process_started_at_ns = shared.clock()

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
            start_time=self._stagger_start_time(),
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
            # `start_time=None` -- UNSTAGGERED, deliberately, and the asymmetry
            # with the poll timer above is the point. The stagger exists to
            # spread concurrent HTTP requests to `api.weather.gov` across five
            # sites so a synchronised burst cannot latch the UA trap.
            # `check_final_deadline` performs NO network I/O -- it reads this
            # site's own catalog and calls `record_final_overdue` -- so it
            # gains nothing from the spreading and would only inherit the
            # delay. At site index 4 (240s of a 300s interval) sharing the
            # offset pushed cold-start deadline checking from 300s to 540s and
            # overdue->page latency from ~600s to ~1080s: roughly eight minutes
            # burned ahead of an 08:00 ET settlement deadline, in exchange for
            # nothing.
            start_time=None,
            callback=self.on_deadline_timer,
        )
        self._timers_armed = True

    def _stagger_start_time(self) -> dt.datetime | None:
        """This site's timer phase, or `None` for "start now".

        **Native mechanism, not a Breezy one.** `Clock.set_timer` already
        takes `start_time=` (`nautilus_trader/common/component.pyx:419-478`,
        forwarded to `set_timer_ns(start_time_ns=...)`; the `TestClock`
        implementation is at `:705-739` and the `LiveClock` one at
        `:930-979`). With `fire_immediately=False` (the default) the first
        event lands at `start_time + interval` and every event after that one
        `interval` later -- so an offset is a PHASE SHIFT and never a change
        to the steady-state cadence. Nothing here re-implements scheduling.

        Why it matters: without it all five Actors arm identical timers at the
        same instant and fire together, producing five concurrent bursts to
        `api.weather.gov` under a single User-Agent -- the documented route
        into the UA trap, which latches every site and clears only by manual
        operator action.

        The offset itself is assigned by the composition root
        (`breezy.runtime.composition.site_stagger_offset_seconds`), the only
        place that knows the full site set; this method just reads it.
        """
        offset = int(self._config.stagger_offset_seconds)
        if offset <= 0:
            return None
        # `Clock` is compiled Cython, so `utc_now()` erases to `Any`; the
        # annotation is asserted here rather than trusted.
        now: dt.datetime = self.clock.utc_now()
        return now + timedelta(seconds=offset)

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

    @property
    def poll_in_flight(self) -> bool:
        """Is a poll cycle currently running? See :meth:`poll_once`."""
        return self._poll_in_flight

    async def poll_once(self) -> None:
        """One full poll: SS6 steps 1-12, under mutual exclusion.

        **Cycles may not overlap, and that is a correctness rule rather than a
        tidiness one.** :meth:`on_poll_timer` fires on a wall schedule and
        submits unconditionally, so a cycle that outruns its interval (a slow
        upstream, a backed-up disk) overlaps its successor. Two overlapping
        cycles then reach ``AlertState`` -- which documents itself as
        "deliberately not thread-safe ... exactly one poll loop is expected to
        own an instance" (``runtime/health.py``) -- and its ``evaluate`` is a
        read-modify-write over ``self._active``. One cycle's write landing on
        the other's stale read LOSES the false->true edge: `UA_TRAP_LATCHED`
        and `SITE_BLOCKED`, the persistent-silent conditions the alerting
        exists to catch, then stay silent until the 24h re-notify.

        BELT AND BRACES with the thread confinement in :meth:`_emit_health`
        (``evaluate`` on the loop thread, only the sink fan-out off it), and
        deliberately not removed as redundant: confinement stops two workers
        racing, this guard stops two *cycles* interleaving at all -- which also
        bounds executor pressure and keeps the ordering between a cycle's
        conditions and its snapshot.

        The guard is a plain flag, not an ``asyncio.Lock``, because the
        overlapping fire must be DROPPED rather than queued: queueing turns a
        slow cycle into an ever-growing backlog of polls against
        ``api.weather.gov`` -- the burst shape that latches the UA trap -- and
        every queued cycle would be reporting a moment that has already passed.
        The next timer fire polls normally; nothing is lost but a duplicate.

        Check-and-set is atomic by construction: it runs to completion on the
        event-loop thread before the first ``await``, and the flag is cleared
        in a ``finally`` so a raising cycle cannot wedge polling permanently.
        (The exception still propagates: it is the poll task's death, which
        ``_on_poll_done`` -> ``_record_task_death`` must see.)
        """
        if self._poll_in_flight:
            logger.warning(
                "skipping overlapping poll cycle for %s/%s: the previous cycle "
                "is still running",
                self._venue,
                self._city,
            )
            return
        self._poll_in_flight = True
        try:
            await self._poll_cycle()
        finally:
            self._poll_in_flight = False

    async def _poll_cycle(self) -> None:
        """The cycle body. Called only by :meth:`poll_once`, under its guard.

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

        **Why gap reconciliation and health emission sit at the very top.**
        :meth:`reconcile_and_report` is called beside :meth:`check_staleness`
        and **before** the ``network_allowed()`` early return, because that is
        the only line reached on every timer fire. The 304 branch, the
        no-new-products branch and the network-disallowed branch all return
        early -- and those are exactly the polls a gap ledger exists to
        observe. Attaching after the terminal publish would miss all of them,
        i.e. would miss the entire steady state.
        """
        self.check_staleness()
        await self.reconcile_and_report()
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

        try:
            entries = self._parse_discovery(result)
        except (NwsEnvelopeError, ValueError) as exc:
            self._block_bad_body("discovery list", exc)
            return

        pending = self._undeduped(entries)
        if not pending:
            # SS6 step 4: nothing new. The poll genuinely succeeded, so
            # freshness is satisfied -- this is the routine steady state.
            self._store_validators(result)
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
            for index, entry in enumerate(sorted(pending, key=lambda e: e.issuance_time_ns)):
                await self._pace_product_fetch(index)
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
            self._store_validators(result)
            return

        # -- step 8: the integrity tripwire, for the whole batch. READ-ONLY
        # here; the durable mark is step 11b, after the write is confirmed.
        for candidate in prepared:
            if not self._check_integrity(candidate):
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
        except Exception as exc:  # noqa: BLE001 - routed by exact catalog type
            self._execute(route_catalog_error(exc))
            return

        if records is None:
            return

        # -- step 11b: NOW the uuids are durably "seen".
        #
        # This must never run before the write above is CONFIRMED. The mark is
        # what `_undeduped` (SS3.4 Job 1) consults to decide a product has
        # already been ingested, and it is durable -- so a mark written ahead
        # of a persist that then fails (or a process death in that window) is
        # permanent, silent data loss: the uuid reads as already-seen forever,
        # the product is never re-fetched, and it is absent from the catalog.
        # That is exactly how a corrected FINAL disappears with no alert and a
        # position settles on the superseded temperature.
        #
        # Reversing the order fails in the recoverable direction instead. A
        # crash between the confirmed write and this mark costs only the mark:
        # the next poll re-fetches and re-persists a product already on disk.
        # `_persist_batch` nudges a colliding `retrieved_at_ns` strictly past
        # the catalog's current maximum `ts_init` (WI-11), so that re-write
        # appends a later revision of identical content rather than tripping
        # the exact-range rewrite `write_records` reports as `skipped`; and
        # supersession resolves by `(is_final, ts_init, revision_seq)`, so the
        # settled readings are unchanged. A duplicate revision is a cost. A
        # lost correction is not survivable.
        #
        # Before publish, not after: `_observe_integrity` is the only remaining
        # write here, and a death between it and the publish is already covered
        # -- the records are durable and the cursor has not moved, so warm start
        # republishes them.
        for candidate in prepared:
            if not self._observe_integrity(candidate):
                return

        self._store_validators(result)

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

    async def _pace_product_fetch(self, index: int) -> None:
        """Delay product-body requests after the first request in a poll.

        The discovery list is one request per site and is already staggered
        across sites by runtime composition. A cold-start backlog is different:
        every pending `/products/{id}` body would otherwise be fetched
        back-to-back inside this one Actor. The delay sits *after* issuance
        sorting and *before* `_prepare_product`, so the first body fetch is still
        immediate and `ts_init` order still follows issuance order. The sleep
        seam is injectable because tests must prove pacing without spending
        real wall-clock time.
        """
        if index == 0:
            return
        delay_seconds = float(self._config.product_fetch_delay_seconds)
        if delay_seconds <= 0:
            return
        await self.sleep_between_product_fetches(delay_seconds)

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

    def _integrity_alarm(self, uuid: str, detail: str) -> None:
        # `routing` has no producer for a product-index MISMATCH; the closest
        # exact recorder is the transport integrity alarm, which is the correct
        # severity (CRIT, hard-block) and the correct claim: the datum's digest
        # cannot be trusted.
        self.gate.record_transport_integrity_alarm(
            self._venue,
            self._city,
            detail=f"product-index MISMATCH for {uuid}: {detail}",
        )

    @staticmethod
    def _require_digest(prepared: _PreparedProduct) -> str:
        digest = prepared.fetch.sha256
        if digest is None:  # pragma: no cover - guaranteed by FetchResult
            raise ValueError("a non-304 FetchResult must carry a digest")
        return digest

    def _check_integrity(self, prepared: _PreparedProduct) -> bool:
        """SS3.4 Job 2 at step 8 -- the tripwire's VERDICT, with no write.

        The check and the durable record are deliberately split across the
        catalog write: the verdict has to precede the write (mutated bytes must
        never be persisted or published), while the record has to follow it
        (see the step 11b comment in :meth:`poll_once` -- a durable mark ahead
        of a confirmed persist is permanent silent data loss). This half is
        therefore strictly read-only, and :meth:`_observe_integrity` performs
        the identical comparison again afterwards on the durable path.

        Same verdict as :meth:`_observe_integrity`, reached through the
        read-only accessor: an entry whose digest differs is the CRIT event,
        and unreadable persisted evidence -- which
        :meth:`~breezy.ingest.product_index.ProductIntegrityIndex.known_digest`
        reports by RAISING rather than by returning ``None``, so corruption can
        never read as a clean slate -- is the same event. A ``store.get`` that
        raises still propagates (fail-closed into task supervision) exactly as
        before.
        """
        digest = self._require_digest(prepared)
        uuid = prepared.envelope.product_uuid
        try:
            known = self.product_index.known_digest(uuid)
        except CorruptProductIndexEntryError as exc:
            self._integrity_alarm(
                uuid,
                f"cannot verify product_uuid={uuid}: {exc.detail}. "
                "Failing closed -- an unreadable entry is not a clean slate.",
            )
            return False
        if known is None or known == digest:
            return True
        self._integrity_alarm(
            uuid,
            f"INTEGRITY: product_uuid={uuid} was first seen with "
            f"raw_sha256={known} and is now reported as raw_sha256={digest}. "
            "An already-issued NWS product changed bytes under a stable uuid "
            "-- upstream mutation, not a revision.",
        )
        return False

    def _observe_integrity(self, prepared: _PreparedProduct) -> bool:
        """SS3.4 Job 2 at step 11b -- the tripwire's DURABLE RECORD, and it
        should never fire.

        Runs only after the catalog write is CONFIRMED (see the step 11b
        comment in :meth:`poll_once`), because
        :meth:`~breezy.ingest.product_index.ProductIntegrityIndex.observe`
        writes the uuid durably and that mark is what suppresses every future
        re-fetch. :meth:`_check_integrity` has already returned the same
        verdict read-only before the write, so an alarm here means the index
        gained a conflicting entry mid-poll; it is kept rather than assumed
        away, and it is still fail-closed -- the records are durable and the
        cursor has not moved, so warm start republishes them.

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
        digest = self._require_digest(prepared)
        uuid = prepared.envelope.product_uuid
        observation = self.product_index.observe(uuid, digest)
        if not observation.is_integrity_alarm:
            return True
        self._integrity_alarm(uuid, observation.detail)
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
        # WI-11: a fast backlog drain can land two SEPARATE polls on the same
        # clock tick (the injected nanosecond clock genuinely reads the same
        # instant twice, or a warm-start replay is fast enough that it
        # measurably does). `ts_init` is `retrieved_at_ns` (fetch time), so
        # two single-product batches that share a tick produce a `ts_init`
        # range for this batch that EXACTLY matches a range already on disk.
        # `write_records` discards an exact-range rewrite SILENTLY
        # (`persistence/catalog.py` module docstring, "Corrections"), which
        # routes to `record_write_integrity_violation` -- CRIT, hard-block --
        # and the second poll's products are durably lost. Every candidate
        # reaching this point already passed `_undeduped` (SS3.4 Job 1), so
        # its content is never a legitimate duplicate of what's on disk; a
        # collision here is ALWAYS a fresh product colliding on the clock
        # alone, never a rewrite that should be rejected. Nudging this
        # batch's stamp strictly past the catalog's current maximum
        # `ts_init` is therefore always correct, not merely a workaround: it
        # never reorders anything relative to what is already durable, and
        # only degrades timestamp precision (by nanoseconds) for the
        # specific candidates whose real fetch instant already collided.
        seq_by_day: dict[dt.date, int] = {}
        existing_max_ts_init: int | None = None
        for record in existing:
            if record.station != self._site.cli_location:
                continue
            seq_by_day[record.climate_day] = seq_by_day.get(record.climate_day, 0) + 1
            if existing_max_ts_init is None or record.ts_init > existing_max_ts_init:
                existing_max_ts_init = record.ts_init

        records: list[Data] = []
        for candidate in prepared:
            day = candidate.parsed.summary_date
            seq_by_day[day] = seq_by_day.get(day, 0) + 1
            fetch = candidate.fetch
            if existing_max_ts_init is not None and fetch.retrieved_at_ns <= existing_max_ts_init:
                fetch = replace(fetch, retrieved_at_ns=existing_max_ts_init + 1)
            raw_product = build_raw_product(
                site=self._site,
                registry_version=self._registry_version,
                fetch=fetch,
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
        """Rewind to "nothing published". Operational replay-repair tool.

        Written through to the durable store, not merely to ``self._cursor``:
        rewinding in memory only would silently un-rewind on the next process,
        so the operator would run the repair, restart, and get no replay.
        """
        self._cursor = None
        self._cursor_loaded = True
        self._state_store.set(self._cursor_key, b"")

    @property
    def _state_store(self) -> StateStore:
        """The ONE durable store -- **not** the Nautilus ``Cache``.

        ``Cache`` cannot hold this. ``CacheConfig.database`` is ``None`` in
        every Breezy node config (``runtime/node_config.py:150`` ->
        ``system/kernel.py:310-311``), and ``Cache.add`` forwards to a database
        only ``if self._database is not None`` (``cache/cache.pyx:1704-1708``)
        while ``cache_general`` resets ``self._general`` to ``{}`` when there is
        none (``:298``). So a cursor kept in ``Cache`` is a plain dict that dies
        with the process, and after a restart ``warm_start`` republishes the
        ENTIRE retained station catalog while the first poll goes out
        unconditional.

        Thread contract: ``StateStore`` is ``SqliteStateStore`` in every
        deployment and is **thread-confined** (``runtime/sqlite_store.py:71-79``
        raises off its constructing thread). Every caller of this property --
        ``_load_cursor``/``_save_cursor``/``reset_cursor``/``_load_validators``/
        ``_store_validators`` -- is reached only from the event-loop thread, the
        same thread the gate and the product index already use it from. Nothing
        handed to ``_run_off_loop`` may touch it; executor work stays restricted
        to catalog I/O and the pure ``normalize`` parsers, neither of which does.
        """
        return self._shared.store

    @property
    def _cursor_key(self) -> str:
        return f"{CURSOR_KEY_PREFIX}{self._venue}:{self._city}"

    def _load_cursor(self) -> Cursor | None:
        raw = self._state_store.get(self._cursor_key)
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
        """Persist to the durable store -- write-through per mutation.

        Two homes were ruled out, both by measurement:

        * ``on_save``. ``save_state``/``load_state`` are ``NautilusKernelConfig``
          fields, not ``ActorConfig`` fields, and ``Trader.save()`` is called
          **only** from ``kernel.stop()``/``stop_async()``. On SIGKILL, OOM or
          host loss it never runs, so a cursor kept there is frozen at the last
          *graceful* shutdown -- possibly never written at all.
        * ``Cache.add``. It is write-through only when a cache database is
          configured, and Breezy configures none; see :attr:`_state_store`.
          Enabling one is not an option -- that would be reaching for a Nautilus
          facility this deployment deliberately does not run, to carry Breezy's
          own state, when Breezy already owns a durable store.

        ``SqliteStateStore.set`` commits before it returns, so the durability
        boundary coincides exactly with this call -- which is what lets the
        crash window stay one record wide rather than one poll wide.
        """
        self._cursor = cursor
        self._cursor_loaded = True
        self._state_store.set(self._cursor_key, json.dumps(list(cursor)).encode("utf-8"))

    # -- conditional-GET validators ---------------------------------------

    @property
    def _validators_key(self) -> str:
        return f"{VALIDATORS_KEY_PREFIX}{self._venue}:{self._city}"

    def _load_validators(self) -> tuple[str | None, str | None]:
        raw = self._state_store.get(self._validators_key)
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
        self._state_store.set(self._validators_key, json.dumps(payload).encode("utf-8"))

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

    # -- WI-10 / WI-12: gap reconciliation, health snapshot, alerts ---------

    async def reconcile_and_report(self) -> None:
        """Reconcile the durable gap ledger, then emit the health snapshot and
        this cycle's alerts. Once per poll cycle, at the top of
        :meth:`poll_once` -- see that method's docstring for why the top.

        **Failure isolation is the point of this method existing at all.**
        ``gaps.reconcile`` deliberately does not swallow: it raises
        ``TamperedGapLedgerError`` on a corrupted ledger, because containment
        is the attachment point's job rather than a pure function's. So both
        halves are wrapped here, and independently: losing reconciliation for
        one cycle is recoverable, losing the poll is not -- and the snapshot is
        *more* valuable, not less, on the cycle where reconciliation just
        failed, so a ledger failure must not suppress it.

        ``Exception`` and not ``BaseException``: ``asyncio.CancelledError`` is
        a shutdown signal and must keep propagating. Neither branch touches the
        settlement gate, which is deliberate -- a defect in our own
        observability is not evidence about the venue's data, and recording one
        as a site block would take a healthy site offline for a bookkeeping
        bug.

        **Thread confinement (SS4.1).** ``reconcile`` WRITES to the
        thread-confined ``SqliteStateStore``, so it runs inline on the event
        loop, exactly like the gate and the product index. Only the catalog
        read -- unbounded, ``flock``-taking pyarrow I/O -- goes through
        ``_run_off_loop``. Reversing that raises ``RuntimeError`` out of the
        store, and only in a real deployment.
        """
        now_ns = self._now()
        entries: tuple[gaps.GapEntry, ...] = ()
        revisions: tuple[gaps.RevisionEvent, ...] = ()

        try:
            catalog = self._open_catalog()
            records = await self._run_off_loop(lambda: read_climate_days(catalog))
            result = gaps.reconcile(
                store=self._shared.store,
                now_ns=now_ns,
                venue=self._venue,
                city=self._city,
                station=self._site.cli_location,
                std_utc_offset_hours=self._window.std_utc_offset_hours,
                settlement_delay_time_local=self._deadline.settlement_delay_time_local,
                settlement_delay_timezone=self._deadline.settlement_delay_timezone,
                records=records,
            )
            revisions = result.revisions
            entries = gaps.site_entries(self._shared.store, self._venue, self._city)
            self._ledger_failure_detail = None
        except Exception as exc:
            # Swallowed, still -- but never SILENT. Left as a bare
            # `logger.exception` this branch reported a perfectly healthy site
            # forever: `entries` stays `()`, so the snapshot publishes
            # `open_gaps: []` and no condition fires, while a
            # `TamperedGapLedgerError` on one corrupt row raises every cycle
            # and revision detection -- the only defence against a superseded
            # final -- is dead. The operator dashboard would show green.
            #
            # So the failure becomes a CRITICAL `LEDGER_UNAVAILABLE` condition
            # (raised in `_alert_conditions` off this attribute) and the
            # snapshot is emitted anyway, on this cycle above all: a cycle
            # whose reconciliation just failed is when the snapshot matters
            # most. Scrubbed at CAPTURE, not at render, so the one stored
            # string is safe for both consumers it reaches -- the 0600 disk
            # artifact and the off-host webhook payload. See
            # `_scrub_failure_detail`.
            self._ledger_failure_detail = _scrub_failure_detail(exc)
            logger.exception(
                "gap reconciliation failed for %s/%s -- swallowed so the poll continues",
                self._venue,
                self._city,
            )

        try:
            await self._emit_health(now_ns, entries=entries, revisions=revisions)
        except TimeoutError:
            # NOT swallowed, and the one exception to this method's containment
            # rule. Every other failure here is a defect in our own
            # observability and must not take a healthy site offline -- but a
            # `TimeoutError` from `_bounded_io` means a worker thread is parked
            # on uninterruptible I/O and is never coming back. A Python thread
            # cannot be killed, so with `max_workers=2` a second stall exhausts
            # the pool and every later cycle hangs before it can report
            # anything. Propagating routes it to `_on_poll_done` ->
            # `_record_task_death` -> the settlement gate, which fails CLOSED
            # over data we can no longer prove fresh. Silence here is the
            # fail-OPEN.
            raise
        except Exception:
            logger.exception(
                "health emission failed for %s/%s -- swallowed so the poll continues",
                self._venue,
                self._city,
            )

    async def _emit_health(
        self,
        now_ns: int,
        *,
        entries: Sequence[gaps.GapEntry],
        revisions: Sequence[gaps.RevisionEvent],
    ) -> None:
        """Build this cycle's alert conditions and `HealthSnapshot`, dispatch,
        and write the snapshot atomically if a path is configured.

        The ``GapEntry -> GapSummary`` mapping lives HERE, at the call site,
        and that is deliberate: ``health.py`` does not import
        ``breezy.ingest`` and ``gaps.py`` does not import ``health`` -- neither
        module may learn the other's vocabulary, so the adapter belongs to the
        wiring that already knows both.
        """
        health = _health()

        status = self.gate.status(self._venue, self._city)
        causes = self.gate.blocking_causes(self._venue, self._city)
        ua_latched = GateReason.UA_TRAP_403 in causes
        site_label = f"{self._venue}/{self._city}"
        today = gaps.local_standard_date(now_ns, self._window.std_utc_offset_hours)

        # `open_gaps` deliberately includes ACKNOWLEDGED_LOST: an acknowledged
        # day is muted for re-notify, never hidden. Removing it from the
        # snapshot would make an operator's acknowledgement look like a repair.
        summaries = tuple(
            health.GapSummary(
                climate_day=entry.climate_day.isoformat(),
                state=entry.state.value,
                severity=gaps.severity_for(entry.climate_day, today).value,
                days_until_retention_loss=gaps.days_remaining_until_retention_loss(
                    entry.climate_day, today
                ),
            )
            for entry in entries
            if entry.state is not gaps.GapState.RESOLVED
        )
        acknowledged_lost = sum(
            1 for entry in entries if entry.state is gaps.GapState.ACKNOWLEDGED_LOST
        )

        conditions = self._alert_conditions(
            now_ns,
            health=health,
            site_label=site_label,
            status=status,
            causes=causes,
            ua_latched=ua_latched,
            entries=entries,
            summaries=summaries,
            revisions=revisions,
        )
        # SPLIT ACROSS THE THREAD BOUNDARY, deliberately, and the split line
        # is the whole point.
        #
        # `evaluate` -- ON THE LOOP THREAD. It is a read-modify-write over
        # `AlertState`'s two dicts, and that class documents itself as
        # "deliberately not thread-safe ... exactly one poll loop is expected
        # to own an instance". Running it on an executor worker made that
        # ownership claim false: it was safe only because no other code path
        # dispatches alerts today -- thread-safety by exclusion, which the
        # next caller added anywhere silently converts into a data race over
        # the exact transitions that must never be lost (`UA_TRAP_LATCHED`,
        # `SITE_BLOCKED` are latched-persistent, so a lost false->true edge is
        # not re-tried until the 24h re-notify). It is pure bookkeeping over
        # a handful of dict entries, so it costs the loop nothing.
        #
        # `emit_alert` -- OFF THE LOOP, under the same ceiling as before. This
        # is the half with a real reason to leave: `WebhookAlertSink.emit` is
        # a SYNCHRONOUS `httpx.Client.post` with a 5s default timeout, and the
        # incident case is exactly the case it fires in -- several sites
        # transitioning to blocked at once serialises those POSTs and delays
        # every other site's poll and final-overdue check near a settlement
        # deadline.
        #
        # The `dispatch` contract is preserved exactly: `emitted` is what this
        # cycle DECIDED to emit, never what the sink managed to deliver, and
        # `emit_alert` still swallows every sink failure inside the worker.
        # The whole fan-out is one `_bounded_io` call, as `dispatch` was, so a
        # black-holed webhook still trips the ceiling and routes to
        # `_record_task_death` rather than parking a worker forever.
        tracker = self._alert_tracker(health)
        sink = self._resolved_alert_sink(health)
        payloads = tracker.evaluate(conditions, now_ns=now_ns)
        emitted = len(payloads)
        if payloads:
            await self._bounded_io(lambda: self._emit_all(health, sink, payloads))

        snapshot = health.HealthSnapshot(
            schema_version=health.SCHEMA_VERSION,
            process_started_at_ns=self._process_started_at_ns,
            snapshot_at_ns=now_ns,
            trader_id=str(getattr(self, "trader_id", "") or ""),
            sites=(
                health.SiteHealth(
                    venue=self._venue,
                    city=self._city,
                    gate_state=status.state.value,
                    gate_reason=status.reason.value,
                    blocking_causes=tuple(cause.value for cause in causes),
                    last_successful_poll_ns=status.last_successful_poll_ns,
                    cursor=self._cursor_text(),
                    open_gaps=summaries,
                    acknowledged_lost_count=acknowledged_lost,
                    # The FILE-based half of the `LEDGER_UNAVAILABLE` signal.
                    # The alert alone is not enough: `BREEZY_ALERT_WEBHOOK_URL`
                    # is unset by default, so `resolve_alert_sink` yields a
                    # LOGGING sink and the CRITICAL reaches nothing an operator
                    # polls -- while the runbook points them at
                    # `health-<venue>.<city>.json`. Without this field that
                    # file shows `open_gaps: []`, byte-identical to a healthy
                    # site, for a ledger that has been unreadable for days.
                    ledger_unavailable=self._ledger_failure_detail,
                ),
            ),
            ua_trap_latched=ua_latched,
            alerts_emitted_this_cycle=emitted,
        )
        self.last_health_snapshot = snapshot
        snapshot_path = self.health_snapshot_path
        if snapshot_path is not None:
            # Off the loop for the same reason as the dispatch above:
            # `write_snapshot_atomic` does an `fsync` plus a rename, and a
            # stalled disk must not be able to hold the poll cycle's thread.
            # BOUNDED for the second reason: off-loop-and-unbounded is a
            # fail-open, not a fix -- see `_bounded_io`.
            await self._bounded_io(
                lambda: health.write_snapshot_atomic(snapshot_path, snapshot)
            )

    @staticmethod
    def _emit_all(health: Any, sink: AlertSink, payloads: Sequence[AlertPayload]) -> None:
        """The blocking half of the old `AlertState.dispatch`, run on a worker.

        Kept as a named method rather than a comprehension inside the lambda so
        the executor call site reads as "fan out these already-decided
        payloads" -- the decision itself happened on the loop thread.
        """
        for payload in payloads:
            health.emit_alert(sink, payload)

    def _alert_conditions(
        self,
        now_ns: int,
        *,
        health: Any,
        site_label: str,
        status: GateStatus,
        causes: Sequence[GateReason],
        ua_latched: bool,
        entries: Sequence[gaps.GapEntry],
        summaries: Sequence[GapSummary],
        revisions: Sequence[gaps.RevisionEvent],
    ) -> list[AlertCondition]:
        """Every condition this site tracks, evaluated fresh for this cycle.

        ``AlertState.evaluate`` leaves a key it is not handed untouched, so
        every standing condition is passed on every cycle -- including the ones
        that are ``active=False``, which is what lets a cleared condition fire
        again next time it sets.

        ``detail`` strings are short and structural by construction: no
        absolute path, no upstream body or header, no settings field. The
        snapshot has no slot for those either, so neither artifact can leak
        ``user_agent_contact``.
        """
        blocked_after_ns = (
            int(self._config.poll_interval_seconds) * SITE_BLOCKED_ALERT_INTERVALS * _NS_PER_SECOND
        )
        # Duration is measured from when THIS process first OBSERVED the block,
        # never from `GateStatus.at_ns`. Two independent reasons, both found by
        # test rather than by inspection:
        #
        # 1. `at_ns` is the last TRANSITION instant, and a blocked site keeps
        #    transitioning -- `check_staleness` alone re-records every cycle.
        #    Elapsed-since-`at_ns` therefore resets continuously and a
        #    permanently blocked site would never reach the threshold at all.
        # 2. A never-polled site reports `BLOCKED` with `at_ns == 0`, so the
        #    same arithmetic reads the entire Unix epoch as downtime and pages
        #    CRITICAL on every fresh deployment.
        #
        # In-memory and never persisted, matching `AlertState`'s own cold-start
        # stance: at boot the site is unobserved, so the clock starts now and a
        # genuinely dead-on-arrival deployment alerts after the threshold --
        # which is the ONLY signal for that case, since `PollStale` cannot fire
        # while `last_successful_poll_ns` is still `None`. Sampled once per
        # cycle, because once per cycle is the only observation cadence there
        # is.
        if status.state is GateState.BLOCKED:
            if self._blocked_since_ns is None:
                self._blocked_since_ns = now_ns
        else:
            self._blocked_since_ns = None
        blocked_long = (
            self._blocked_since_ns is not None
            and now_ns - self._blocked_since_ns >= blocked_after_ns
        )
        last_poll_ns = status.last_successful_poll_ns
        poll_stale = (
            last_poll_ns is not None and now_ns - last_poll_ns >= self.staleness_degraded_after_ns
        )

        conditions: list[AlertCondition] = [
            health.AlertCondition(
                key=health.AlertConditionKey(kind=health.UA_TRAP_LATCHED, site="global"),
                active=ua_latched,
                severity="CRITICAL",
                event=health.UA_TRAP_LATCHED,
                detail="global UA-trap latch is set; every site has stopped polling",
            ),
            health.AlertCondition(
                key=health.AlertConditionKey(kind=health.SITE_BLOCKED, site=site_label),
                active=blocked_long,
                severity="CRITICAL",
                event=health.SITE_BLOCKED,
                detail=(
                    f"blocked for at least {SITE_BLOCKED_ALERT_INTERVALS} poll intervals; "
                    f"causes={','.join(cause.value for cause in causes)}"
                ),
            ),
            health.AlertCondition(
                key=health.AlertConditionKey(kind=health.FINAL_OVERDUE, site=site_label),
                active=GateReason.FINAL_CLI_OVERDUE in causes,
                severity="CRITICAL",
                event=health.FINAL_OVERDUE,
                detail="the final CLI is overdue past the venue settlement deadline",
            ),
            health.AlertCondition(
                key=health.AlertConditionKey(kind=health.POLL_STALE, site=site_label),
                active=poll_stale,
                severity="WARN",
                event=health.POLL_STALE,
                detail=(
                    f"no successful poll for at least {STALENESS_DEGRADE_INTERVALS} poll intervals"
                ),
            ),
            # CRITICAL, and passed on EVERY cycle -- inactive ones included,
            # so `AlertState` sees the true->false edge and the next failure
            # is a fresh false->true rather than a 24h-muted repeat.
            #
            # This is the only signal that `reconcile_and_report`'s swallowed
            # branch fired. Without it the ledger can be unreadable
            # indefinitely while the snapshot reports `open_gaps: []` -- zero
            # gaps and zero alerts are exactly what a HEALTHY site looks like,
            # so the failure is indistinguishable from success. CRITICAL and
            # not WARN because a dead ledger means revision detection is off:
            # a superseded final can be settled on with nothing to notice it.
            health.AlertCondition(
                key=health.AlertConditionKey(kind=LEDGER_UNAVAILABLE, site=site_label),
                active=self._ledger_failure_detail is not None,
                severity="CRITICAL",
                event=LEDGER_UNAVAILABLE,
                detail=(
                    "gap ledger reconciliation failed; open_gaps in this snapshot is "
                    f"NOT authoritative ({self._ledger_failure_detail})"
                ),
            ),
        ]

        # One condition per gap inside the retention warning band, keyed by
        # climate day so several simultaneous gaps each alert once rather than
        # collapsing into a single flapping condition. ACKNOWLEDGED_LOST is
        # muted for re-notify but still fires on transition and still appears
        # in the snapshot -- acknowledgement silences repetition, not the fact.
        acknowledged_days = {
            entry.climate_day.isoformat()
            for entry in entries
            if entry.state is gaps.GapState.ACKNOWLEDGED_LOST
        }
        for summary in summaries:
            conditions.append(
                health.AlertCondition(
                    key=health.AlertConditionKey(
                        kind=health.GAP_RETENTION_WARNING,
                        site=site_label,
                        extra=summary.climate_day,
                    ),
                    active=summary.severity != gaps.GapSeverity.INFO.value,
                    severity=summary.severity.upper(),
                    event=health.GAP_RETENTION_WARNING,
                    detail=(
                        f"climate day {summary.climate_day} is {summary.state} with "
                        f"{summary.days_until_retention_loss} day(s) until assumed "
                        f"retention loss"
                    ),
                    renotify_muted=summary.climate_day in acknowledged_days,
                )
            )

        # A revision is an EVENT, not a standing condition: `extra` carries the
        # new sequence number so each distinct revision is a distinct key and
        # therefore always a false->true transition. Passed only on the cycle
        # it is observed; a key not passed is left untouched, never cleared.
        for revision in revisions:
            conditions.append(
                health.AlertCondition(
                    key=health.AlertConditionKey(
                        kind=health.POST_SETTLEMENT_REVISION,
                        site=site_label,
                        extra=f"{revision.climate_day.isoformat()}:{revision.new_revision_seq}",
                    ),
                    active=True,
                    severity="CRITICAL",
                    event=health.POST_SETTLEMENT_REVISION,
                    detail=(
                        f"climate day {revision.climate_day.isoformat()} revised "
                        f"{revision.previous_revision_seq}->{revision.new_revision_seq} "
                        f"correction={revision.correction_flag} "
                        f"superseded={revision.is_superseded}"
                    ),
                )
            )
        return conditions

    def _alert_tracker(self, health: Any) -> AlertState:
        """The one `AlertState` for this site, created on first use.

        Never seeded from persisted state: a UA-trap latch or an open gap that
        is already true at boot must read as a false->true transition on cycle
        1 and fire. Computing transitions against persisted prior state would
        make exactly those persistent, silent conditions never alert.
        """
        if self._alert_state is None:
            self._alert_state = health.AlertState()
        state: AlertState = self._alert_state
        return state

    def _resolved_alert_sink(self, health: Any) -> AlertSink:
        """The configured sink, or a lazily-resolved default.

        Resolution is deferred to first use rather than done in ``__init__``
        so that a deployment with no ``BREEZY_ALERT_WEBHOOK_URL`` never
        constructs an ``httpx.Client`` or an ``ssl.SSLContext`` at all.
        """
        if self.alert_sink is None:
            self.alert_sink = health.resolve_alert_sink()
        sink: AlertSink = self.alert_sink
        return sink

    def _cursor_text(self) -> str | None:
        """The resume cursor rendered for the snapshot.

        A compact `"<ts_init>:<record class>:<raw sha256>"`, not the tuple: the
        snapshot is a machine-readable operator artifact, and the digest is
        already public provenance stored beside every record.
        """
        cursor = self.resume_cursor
        if cursor is None:
            return None
        return f"{cursor[0]}:{cursor[1]}:{cursor[2]}"

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
        # The ONE copy of this arithmetic lives in `gaps` (extracted from this
        # module's own former private method). Two copies of the fixed-standard
        # -offset-vs-DST derivation is precisely the divergence that silently
        # fabricates or hides gaps, so the private copy is gone rather than
        # merely kept in agreement.
        climate_day = gaps.most_recent_completed_climate_day(now, self._window.std_utc_offset_hours)
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

    async def _bounded_io[T](self, fn: Callable[[], T]) -> T:
        """Run blocking OBSERVABILITY I/O off the loop under a real ceiling.

        Distinct from :meth:`_bounded` only in which clock it reads:
        `_bounded` bounds a CPU-bound parse with `parse_timeout_ms` (250 ms),
        which any healthy `fsync` or webhook POST would breach. This one uses
        `observability_io_timeout_s` (30s default, well under the 300s poll
        interval), so a breach means a genuine stall.

        Why a ceiling at all, given the work is already off the loop: an
        unbounded `run_in_executor` over a wedged mount or a black-holed
        webhook parks a worker permanently, so the awaiting `poll_once` never
        completes, its future never resolves, and `_on_poll_done` ->
        `_record_task_death` -> the settlement gate never runs. The site then
        reads OPEN over data nothing is refreshing -- silence presented as
        health, which is the exact failure the health path exists to prevent.

        Honest limit, identical to `_bounded`'s: a Python thread cannot be
        killed, so `wait_for` frees the *cycle*, not the worker. The stall
        still surfaces -- loudly, as task death -- instead of hanging.
        """
        return await asyncio.wait_for(
            self._run_off_loop(fn), self.observability_io_timeout_s
        )

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
