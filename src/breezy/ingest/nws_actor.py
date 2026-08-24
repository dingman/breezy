"""The NautilusTrader ``Actor`` that drives NWS Climate (CLI) product ingestion.

Governing rulings: ``docs/plans/PHASE1_ACTOR_BRIEF.md`` SS3-SS7 and
``docs/plans/WEATHER_INGESTION_PROPOSAL.md`` SS2.3, SS5, SS10. Every framework
claim below was verified by executing against the installed
``nautilus-trader==1.231.0``, not by reading its documentation, and each is
pinned by a test marked ``contract`` so a version bump fails RED.

One instance per ``(venue, city)``; five in production. All five share ONE
:class:`~breezy.ingest.shared_state.SharedIngestState`, and each proves it at
startup through :meth:`SharedIngestState.register_site_actor`.

Null hypothesis -- what Nautilus already provides, and is therefore ADOPTED
rather than rebuilt
-------------------------------------------------------------------------
* ``Clock.set_timer(name, interval, start_time, callback)``
  (``common/component.pyx:419``) for the poll cadence **and** the five-city
  stagger. The stagger is a ``start_time`` argument, not a throttling problem;
  ``Throttler`` is declined (proposal SS10 -- it drops messages in drop mode and
  re-arms from the Rust timer thread in buffer mode).
* ``Clock.set_time_alert(..., override=True, allow_past=False)``
  (``:316``) for the per-climate-day final-overdue deadline, with
  ``next_time_ns`` (``:295``) as the armed-ness query -- it returns ``0`` when
  absent -- and ``cancel_timer`` (``:543``) to clear it.
* ``Actor.publish_data`` (``actor.pyx:2813``) and the
  ``on_start``/``on_stop``/``on_reset``/``on_dispose`` lifecycle
  (``actor.pyx:244-334``).
* ``Component.degrade()``/``resume()`` as an OPERATOR OUTPUT (reversible:
  ``component.pyx:1650``). ``fault()`` is never called -- it is terminal and the
  FSM has no exit from ``FAULTED`` (``:2129``, ``:1649-1654``), while our
  BLOCKED must be clearable by a clean poll.
* ``live/retry.py``'s ``RetryManager`` for the INTRA-poll attempt loop, and
  ``get_exponential_backoff`` inside it.
* ``ParquetDataCatalog`` through ``breezy.persistence.catalog``.

What is genuinely ours, with the evidence
-----------------------------------------
* **The Rust-timer-thread bridge.** A ``LiveClock`` timer callback runs on a
  Rust/tokio thread with **no running event loop**, and Rust **swallows** any
  exception raised there. ``asyncio.create_task`` raises; the only working
  primitive is ``asyncio.run_coroutine_threadsafe(coro, loop)`` against a loop
  captured in ``on_start``, and the returned future's ``exception()`` is the
  ONLY seam that carries a failed poll to the gate. Measured and pinned in
  ``tests/contract/test_live_timer_thread_affinity.py``.
  ``Actor.run_in_executor`` is declined: it discards the callable's return value
  and hands back a fresh ``TaskId`` with no ``add_done_callback``
  (``actor.pyx:1091-1096``).
* **The ``Retry-After``-honouring INTER-poll backoff window, and its per-site
  persisted state.** ``RetryManager`` computes its delay solely from attempt
  count (``retry.py:186-194``); ``exc.retry_after`` is never read. And
  ``RetryManagerPool.acquire()`` calls ``clear()`` (``:335`` -> ``:206-210``),
  so the manager holds no per-site state at all.
* **A data-staleness watchdog for HTTP.** Nautilus ships none --
  ``idle_timeout_ms`` is WebSocket-only. Mirrored onto the poll channel through
  ``SettlementGate.check_freshness``.
* **The NWS JSON envelope readers** (:func:`parse_discovery_list`,
  :func:`parse_product_envelope`), with explicit size and depth caps.
* **The revision/supersession write path.** ``ParquetDataCatalog`` gives
  serialization, not supersession semantics: ``revision_seq`` is monotonic per
  ``(station, climate_day)`` and a correction is a NEW record with a later
  ``ts_init``, never a rewrite of the same range (which the catalog silently
  discards, ``parquet.py:378-380``).
* **The resume cursor.** ``Cache.add`` is fire-and-forget and ``Cache.get``
  never reads the database (``cache/cache.pyx:1700-1708``, ``:2853``), and
  ``on_save`` runs on *graceful* stop only -- which is not the case a crash
  cursor exists for. The cursor goes through the durable
  :class:`~breezy.ingest.gate.StateStore`, written at the instant of publish.

Three deliberate deviations, stated rather than hidden
------------------------------------------------------
1. **The parse runs on the thread-pool executor, not inline.** The brief's SS3.1
   says "parse inline" and its SS6 demands a real wall-clock ceiling routed to
   ``record_oversize_or_parse_timeout``. Those cannot both hold:
   ``asyncio.wait_for`` around a synchronous call is a no-op, so an inline parse
   has no ceiling that can ever fire. Running it on the executor under
   ``wait_for`` delivers SS6's runtime guarantee -- the event loop stays
   responsive whatever the parse does -- and preserves SS3.1's actual concern,
   which was never inlineness for its own sake.
2. **A malformed JSON envelope is raised as
   ``normalize.cli_parse.CliContentError``.** ``routing.py`` dispatches on exact
   type and has no row for an envelope failure; ``CliContentError`` means
   "structure passed, content unreadable", which is exactly what a body served
   from ``/products/{id}`` that is not a usable product envelope is. Reusing it
   keeps ``routing.py`` untouched and its exact-type dispatch intact.
3. **Two outcomes have no ``routing.py`` row and are recorded directly:**
   ``ClassificationError`` -> ``record_ambiguous_headline`` (brief SS5 names the
   route; ``GateAction`` carries no member for it) and a
   ``ProductIntegrityOutcome.MISMATCH`` -> ``record_transport_integrity_alarm``
   (the fetched document cannot be trusted). Both are flagged for the routing
   seam's owner rather than papered over here.

This module logs through the stdlib :mod:`logging`, not ``self.log``: a
``logging.Handler`` forwarding into the Nautilus ``Logger`` is installed by the
composition root, and the Nautilus ``Logger`` silently DISCARDS records when
logging is uninitialized (``component.pyx:1450-1451``), which would make every
kernel-less test blind.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime as dt
import json
import logging
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Protocol
from zoneinfo import ZoneInfo

import msgspec
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.component import Logger
from nautilus_trader.common.config import ActorConfig
from nautilus_trader.core.data import Data
from nautilus_trader.live.retry import RetryManager
from nautilus_trader.model.data import DataType

from breezy.domain.data_types import climate_day_type, raw_product_type
from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.nws_raw_product import NwsRawProduct
from breezy.ingest.gate import GateReason, GateState, SettlementGate, StateStore
from breezy.ingest.http import (
    FetchResult,
    HttpTransport,
    ServerError,
    TransportError,
    TransportTimeoutError,
)
from breezy.ingest.product_index import ProductIntegrityIndex
from breezy.ingest.records import build_climate_day, build_raw_product
from breezy.ingest.routing import (
    GateAction,
    PollOutcome,
    RouteDecision,
    catalog_error_routes,
    route_catalog_error,
    route_fetch_result,
    route_parse_failure,
    route_sanity_violation,
    route_transport_error,
    route_unhandled_exception,
    route_write_outcome,
)
from breezy.normalize.classify import ClassificationError, classify_issuance
from breezy.normalize.cli_parse import (
    CliContentError,
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
    read_climate_day_including_corrections,
    read_climate_days,
    read_raw_products,
    write_records,
)
from breezy.persistence.state_store import StateStoreCorruptError
from breezy.registry.sites import SiteRegistry

__all__ = [
    "DEFAULT_POLL_INTERVAL_SECONDS",
    "DEFAULT_STAGGER_SECONDS",
    "MAX_DISCOVERY_ENTRIES",
    "MAX_INFLIGHT_TASKS",
    "MAX_JSON_DEPTH",
    "PARSER_VERSION",
    "PARSE_TIME_CEILING_SECONDS",
    "RETRYABLE_TRANSPORT_ERRORS",
    "DiscoveryEntry",
    "ExecutorDisposedError",
    "IngestContainer",
    "NonCorrectionSupersessionError",
    "NwsIngestActor",
    "NwsIngestActorConfig",
    "ProductEnvelope",
    "ResumeCursor",
    "build_actor_config",
    "final_overdue_timer_name",
    "parse_discovery_list",
    "parse_product_envelope",
    "poll_timer_name",
]

logger = logging.getLogger(__name__)

NS_PER_SECOND: Final[int] = 1_000_000_000

DEFAULT_POLL_INTERVAL_SECONDS: Final[int] = 300
DEFAULT_STAGGER_SECONDS: Final[int] = 30

#: Wall-clock ceiling on one CLI parse. The 0.25 s figure is the fuzz corpus's
#: CI-time property bound against a measured worst case of 0.33 ms; here it is a
#: production circuit-breaker, which is a different job (brief SS6).
PARSE_TIME_CEILING_SECONDS: Final[float] = 0.25

#: Hard cap on cross-thread submissions this Actor will hold at once.
#:
#: ``may_poll()`` deliberately checks only the UA-trap latch and the backoff
#: window, never general BLOCKED state -- a site that is blocked MUST keep
#: polling, because a successful poll is the only thing that clears a block. The
#: consequence is that the poll timer keeps firing through any fault, so
#: ``_inflight`` needs a bound that does not depend on faults being rare. In
#: steady state the set holds at most one poll, one warm start and one
#: final-overdue submission, so reaching this cap is already a CRIT-worthy
#: anomaly rather than a tuning question.
MAX_INFLIGHT_TASKS: Final[int] = 32

#: Nesting depth cap for either NWS JSON document. A CLI discovery list is two
#: levels deep and a product envelope one; anything approaching this is either
#: an upstream defect or a decompression-bomb-shaped input.
MAX_JSON_DEPTH: Final[int] = 12

#: Cap on discovery-list entries considered in one poll. NWS returns a bounded
#: recent window; a list far larger than this is not a list we should walk.
MAX_DISCOVERY_ENTRIES: Final[int] = 64

#: Stamped into every persisted `NwsClimateDay`. Bumping the parser REQUIRES
#: bumping this, and re-parsing the full fixture corpus with a fail-on-diff
#: gate against previously settled values (proposal SS6, supply chain).
PARSER_VERSION: Final[str] = "breezy.normalize.cli_parse/1"

#: The ONLY exception types the intra-poll `RetryManager` may catch.
#:
#: **These must be sibling LEAF types, never the base ``TransportError``.**
#: ``live/retry.py:172`` is ``except self.exc_types as e:`` -- ordinary,
#: isinstance-based ``except``. Every integrity error in ``ingest/http.py``
#: (``RedirectError``, ``ContentEncodingError``, ``DisallowedHostError``,
#: ``OversizeBodyError``, ``ProxyEnvironmentError``, ``InvalidCacheValidatorError``)
#: subclasses ``TransportError``, so listing the base would make the manager
#: swallow and silently RETRY a redirect on a settlement endpoint -- exactly what
#: ``record_redirect_integrity_alarm`` exists to hard-block. Listing only
#: siblings means ``except`` genuinely does not match them and they propagate
#: uncaught to ``routing.py``'s exact-type dispatch, which is the property the
#: whole design rests on.
#:
#: ``retry_check`` is not an alternative: ``retry.py:174-183`` returns ``None``
#: with ``result=False`` rather than re-raising, converting an integrity alarm
#: into a silent no-op, which is worse than retrying it.
#:
#: ``RateLimitedError`` is deliberately EXCLUDED. ``RetryManager`` cannot honour
#: ``Retry-After`` (delay derives solely from attempt count, ``retry.py:186-194``;
#: ``exc.retry_after`` is never read), so retrying a 429 in ~0.5-2 s against a
#: server-stated wait risks escalating into an NWS abuse block -- and the gate's
#: UA-trap block is permanent until a manual ``acknowledge_ua_trap_resolved()``.
#: **Condition for adding it:** only once the ``Retry-After``-honouring
#: inter-poll backoff window governs the intra-poll loop too. Do not instead
#: raise ``delay_max_ms`` to accommodate a ``Retry-After``: that would apply the
#: server's worst-case wait to every ordinary 5xx blip and push the retry
#: sequence up against the per-site poll cadence.
RETRYABLE_TRANSPORT_ERRORS: Final[tuple[type[BaseException], ...]] = (
    ServerError,
    TransportTimeoutError,
)

class NonCorrectionSupersessionError(Exception):
    """A non-correction issuance would supersede an existing CORRECTION.

    Raised from the write path when a product that is **not** a correction
    carries settlement values that DIFFER from the correction already stored for
    the same ``(station, climate_day)``.

    The scenario this exists for, verbatim: a FINAL publishes TMAX 79; a genuine
    ``CCA`` correction publishes 80; a delayed ``RRA`` retransmission of the
    *uncorrected* text arrives last. ``revision_seq`` is assigned on ingestion
    order alone, so the retransmission would take the highest revision and the
    corrected temperature would silently revert -- and because ``RRx`` is a
    routine retransmission and not a correction, no other alarm in the system
    fires on it.

    Deliberately NOT a ``ValueError``: ``routing.catalog_error_routes()``
    dispatches on exact type, and this is not a catalog fault. It is routed by
    :meth:`NwsIngestActor._ingest_product` to
    ``record_write_integrity_violation`` -- fail closed, block the site, write
    nothing. Refusing the WRITE is what closes the hole at this seam; correcting
    ``revision_seq`` alone would not, because the downstream selector orders by
    arrival time ahead of ``revision_seq``.
    """


class ExecutorDisposedError(RuntimeError):
    """Off-loop work was requested after :meth:`dispose_resources` ran.

    ``dispose_resources`` sets both executor attributes to ``None``, and a
    coroutine suspended mid-poll at that instant resumes and reads the attribute
    fresh. Handing that ``None`` to ``loop.run_in_executor`` is NOT a no-op:
    ``BaseEventLoop.run_in_executor`` resolves ``None`` to
    ``self._default_executor`` and, when that is also ``None``, CONSTRUCTS a
    fresh process-wide ``ThreadPoolExecutor``
    (``asyncio/base_events.py:888-896``, CPython 3.13.13 as installed).

    That silently escapes the single-worker serialisation this Actor's catalog
    path depends on -- ``write_records`` takes an ``flock`` on the station root
    and requires non-decreasing ``ts_init`` within a batch, which is why both
    executors are ``max_workers=1``. The failure would be invisible at exactly
    the point the design needs it to be loud.

    **Raised rather than returned as a "shutting down" outcome**, deliberately.
    Every seam that reads an executor runs inside ``poll_once`` or
    ``warm_start``, and an exception escaping those already has ONE supervision
    path that exists and is tested: the future returned by :meth:`_submit`
    carries it to :meth:`_on_task_done`, which routes it through
    ``route_unhandled_exception`` to a BLOCKED gate, or logs a CRITICAL when the
    loop is already gone. A sentinel return value would instead need a new
    branch at every call site and a new row in ``routing.py`` -- and every one of
    those branches would be a fresh place to continue quietly, which is the bug.

    BLOCKED is also the safe resting state: the gate is per-site and a clean
    poll reopens it on the next boot, whereas a concurrent unserialised catalog
    write corrupts the settlement record.
    """


_CURSOR_KEY_PREFIX: Final[str] = "nwsactor:cursor:"
_BACKOFF_KEY_PREFIX: Final[str] = "nwsactor:backoff:"
_VALIDATOR_KEY_PREFIX: Final[str] = "nwsactor:validators:"


def poll_timer_name(venue: str, city: str) -> str:
    """The poll timer's name for one site.

    Clocks are per-component (``trading/trader.py:342`` gives every Actor its
    own ``Clock``), so these cannot collide across the five Actors -- the site
    is in the name for operator legibility, not for uniqueness.
    """
    return f"poll:{venue}:{city}"


def final_overdue_timer_name(city: str, climate_day: dt.date) -> str:
    """The final-overdue alert's name, keyed by the EXACT climate day.

    ``record_final_overdue`` is a data-completeness clock, not a liveness one,
    and ``record_successful_poll`` deliberately does not clear it. A final for
    yesterday must not clear today's block, so the day is part of the identity.
    """
    return f"final-overdue:{city}:{climate_day.isoformat()}"


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class NwsIngestActorConfig(ActorConfig, frozen=True):
    """Configuration for one ``(venue, city)`` NWS ingest Actor.

    Defined in this module rather than a shared config package, which is the
    Nautilus idiom: config lives with its Actor.

    Every field is JSON-round-trippable, because ``ActorFactory.create``
    re-encodes ``ImportableActorConfig.config`` to JSON and decodes it through
    this class (``common/config.py:609-614``). A ``Path``, a ``re.Pattern`` or a
    live object here fails at deployment time, not at construction.

    **msgspec validates on DECODE, not on ``__init__``.** ``NwsIngestActorConfig(
    city=7)`` is accepted in silence. Route untrusted mappings through
    :func:`build_actor_config`, which is the only path that validates.

    ``ActorConfig`` is imported from ``nautilus_trader.common.config`` -- a typed
    ``.py`` -- and never from ``nautilus_trader.common.actor``, which is compiled
    and erases to ``Any``, silently defeating config typing.
    """

    venue: str
    city: str
    poll_interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS
    #: Position in the five-city stagger. Multiplied by `stagger_seconds` and
    #: added to the timer's `start_time` -- see SS2.3.
    stagger_index: int = 0
    stagger_seconds: int = DEFAULT_STAGGER_SECONDS
    #: Freshness watchdog thresholds. Liveness only: a site that polls cleanly
    #: and simply never receives the final stays fresh here, which is why the
    #: final-overdue deadline exists separately.
    staleness_degraded_after_seconds: int = 3_600
    staleness_blocked_after_seconds: int = 10_800
    #: Intra-poll retry budget. Kept small deliberately: the whole retry
    #: sequence must stay far below `poll_interval_seconds`.
    max_retries: int = 2
    retry_delay_initial_ms: int = 500
    retry_delay_max_ms: int = 2_000
    retry_backoff_factor: int = 2
    parse_ceiling_seconds: float = PARSE_TIME_CEILING_SECONDS
    max_products_per_poll: int = 8
    #: How long the first poll waits for warm start to finish republishing. On
    #: expiry the poll proceeds anyway: a delayed warm start costs at worst a
    #: duplicate publication, whereas refusing to poll would stop the site's
    #: only path back to OPEN.
    warm_start_timeout_seconds: float = 30.0


def build_actor_config(raw: Mapping[str, Any]) -> NwsIngestActorConfig:
    """Build a validated :class:`NwsIngestActorConfig` from an untrusted mapping.

    The construction path that actually type-checks. ``msgspec.Struct.__init__``
    does not validate, so a directly-constructed config accepts wrong types in
    silence; ``msgspec.convert(..., strict=True)`` is where validation happens,
    and ``forbid_unknown_fields`` (inherited from ``NautilusConfig``) turns a
    misspelled key into an error rather than a silently ignored setting.
    """
    return msgspec.convert(dict(raw), type=NwsIngestActorConfig, strict=True)


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResumeCursor:
    """How far publication has durably progressed.

    **Not a bare ``ts_init``.** ``NwsClimateDay`` and ``NwsRawProduct`` from one
    fetch share ``retrieved_at_ns``, and a poll that ingests a preliminary and a
    final after downtime may stamp them identically. With a strict ``>`` on a
    bare ``ts_init``, a crash after publishing the first and before the second
    loses the second permanently; with ``>=``, every warm start re-publishes the
    last record. The tie-breaker is the dedupe key (``raw_sha256``), which is
    recoverable from the record itself after a restart -- a per-Actor publish
    sequence would not be.

    Comparison is strict ``>`` on the ``(ts_init, dedupe_key)`` tuple.
    """

    ts_init: int
    dedupe_key: str

    def precedes(self, *, ts_init: int, dedupe_key: str) -> bool:
        """Whether ``(ts_init, dedupe_key)`` sorts strictly after this cursor."""
        return (ts_init, dedupe_key) > (self.ts_init, self.dedupe_key)


@dataclass(frozen=True, slots=True)
class DiscoveryEntry:
    """One candidate product from the discovery list."""

    product_uuid: str
    issuance_time_ns: int


@dataclass(frozen=True, slots=True)
class ProductEnvelope:
    """The provenance an ``/products/{id}`` JSON envelope carries around the text."""

    product_uuid: str
    product_code: str
    issuing_office: str
    wmo_collective_id: str
    issuance_time_ns: int
    product_text: str


class IngestContainer(Protocol):
    """What this Actor needs from the process-wide container.

    Bound structurally so the seam is explicit and testable;
    :class:`~breezy.ingest.shared_state.SharedIngestState` satisfies it. It is
    NOT an invitation to substitute a private container: the Actor still calls
    :meth:`register_site_actor`, which rejects any gate or index that is not the
    container's own object.
    """

    @property
    def gate(self) -> SettlementGate: ...

    @property
    def product_index(self) -> ProductIntegrityIndex: ...

    @property
    def transport(self) -> HttpTransport: ...

    @property
    def store(self) -> StateStore: ...

    @property
    def clock(self) -> Callable[[], int]: ...

    @property
    def registry(self) -> SiteRegistry: ...

    @property
    def catalog_base(self) -> Path: ...

    def register_site_actor(
        self,
        venue: str,
        city: str,
        *,
        component_id: str,
        gate: SettlementGate,
        product_index: ProductIntegrityIndex,
    ) -> None: ...

    def observe_forbidden_403(self, venue: str, city: str) -> bool: ...


# ---------------------------------------------------------------------------
# Envelope readers -- size and depth capped
# ---------------------------------------------------------------------------


def _json_depth(value: object, *, limit: int, depth: int = 0) -> int:
    if depth > limit:
        raise CliContentError(
            f"NWS JSON document exceeds the maximum nesting depth of {limit}; "
            "refusing to walk it"
        )
    if isinstance(value, dict):
        for item in value.values():
            _json_depth(item, limit=limit, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            _json_depth(item, limit=limit, depth=depth + 1)
    return depth


def _loads_capped(body: str) -> Any:
    try:
        document = json.loads(body)
    except (json.JSONDecodeError, RecursionError) as exc:
        raise CliContentError(f"NWS response body is not decodable JSON: {exc}") from exc
    _json_depth(document, limit=MAX_JSON_DEPTH)
    return document


def _issuance_time_ns(raw: object) -> int:
    if not isinstance(raw, str) or not raw:
        raise CliContentError(f"issuanceTime must be a non-empty ISO-8601 string, got {raw!r}")
    try:
        # `fromisoformat` parses a trailing `Z` natively on 3.11+. A
        # `.replace("Z", "+00:00")` shim is not merely redundant here -- it is
        # unanchored, so it would also rewrite a `Z` appearing anywhere else in
        # the string rather than only the zone designator.
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError as exc:
        raise CliContentError(f"issuanceTime {raw!r} is not ISO-8601: {exc}") from exc
    if parsed.tzinfo is None:
        raise CliContentError(f"issuanceTime {raw!r} carries no timezone offset")
    return int(parsed.timestamp() * NS_PER_SECOND)


def parse_discovery_list(body: str, *, cli_location: str) -> tuple[DiscoveryEntry, ...]:
    """Read ``/products/types/CLI/locations/{loc}`` into candidate product ids.

    Returned in ascending ``issuanceTime`` order so that fetching the batch in
    order also stamps ``retrieved_at_ns`` -- hence ``ts_init`` -- in order, which
    ``write_records`` requires (non-decreasing within a batch).

    Entries whose ``productCode`` is not ``CLI`` are dropped silently: that is a
    routine property of the endpoint, not a data-quality event. The station is
    NOT trusted from this document -- binding is enforced later by the structural
    allowlist against the product's own AWIPS PIL, because one WFO issues several
    cities' products.

    Raises ``CliContentError`` (a ``CliParseError``, so it routes as a parse
    failure) for an undecodable, over-deep or structurally wrong document.
    """
    document = _loads_capped(body)
    if not isinstance(document, dict):
        raise CliContentError(
            f"discovery list for {cli_location} is not a JSON object "
            f"(got {type(document).__name__})"
        )
    graph = document.get("@graph")
    if graph is None:
        raise CliContentError(f"discovery list for {cli_location} carries no '@graph' member")
    if not isinstance(graph, list):
        raise CliContentError(
            f"discovery list '@graph' for {cli_location} is not a list "
            f"(got {type(graph).__name__})"
        )
    if len(graph) > MAX_DISCOVERY_ENTRIES:
        raise CliContentError(
            f"discovery list for {cli_location} carries {len(graph)} entries, "
            f"exceeding the {MAX_DISCOVERY_ENTRIES}-entry cap"
        )

    entries: list[DiscoveryEntry] = []
    for item in graph:
        if not isinstance(item, dict):
            raise CliContentError(
                f"discovery list entry for {cli_location} is not an object "
                f"(got {type(item).__name__})"
            )
        if item.get("productCode") != "CLI":
            continue
        product_uuid = item.get("id")
        if not isinstance(product_uuid, str) or not product_uuid:
            raise CliContentError(
                f"discovery list entry for {cli_location} carries no usable 'id'"
            )
        entries.append(
            DiscoveryEntry(
                product_uuid=product_uuid,
                issuance_time_ns=_issuance_time_ns(item.get("issuanceTime")),
            )
        )

    entries.sort(key=lambda entry: (entry.issuance_time_ns, entry.product_uuid))
    return tuple(entries)


def parse_product_envelope(body: str) -> ProductEnvelope:
    """Read an ``/products/{id}`` JSON envelope.

    ``productText`` is the verbatim product; ``raw_sha256`` is computed over it
    and is a different value from the envelope body's ``response_sha256``. Both
    are stored (see ``ingest/records.build_raw_product``).
    """
    document = _loads_capped(body)
    if not isinstance(document, dict):
        raise CliContentError(
            f"product envelope is not a JSON object (got {type(document).__name__})"
        )

    def _text(field: str) -> str:
        value = document.get(field)
        if not isinstance(value, str) or not value:
            raise CliContentError(
                f"product envelope field {field!r} must be a non-empty string, got {value!r}"
            )
        return value

    return ProductEnvelope(
        product_uuid=_text("id"),
        product_code=_text("productCode"),
        issuing_office=_text("issuingOffice"),
        wmo_collective_id=_text("wmoCollectiveId"),
        issuance_time_ns=_issuance_time_ns(document.get("issuanceTime")),
        product_text=_text("productText"),
    )


# ---------------------------------------------------------------------------
# The Actor
# ---------------------------------------------------------------------------


class NwsIngestActor(Actor):
    """Polls, parses, persists and publishes one site's NWS CLI products.

    See the module docstring for the null-hypothesis findings and the three
    stated deviations. The poll sequence itself is
    ``PHASE1_ACTOR_BRIEF.md`` SS6, implemented in :meth:`poll_once`.
    """

    def __init__(self, config: NwsIngestActorConfig, *, container: IngestContainer) -> None:
        super().__init__(config)
        self._config = config
        self._container = container
        self._gate = container.gate
        self._index = container.product_index
        self._transport = container.transport
        self._store = container.store
        self._wall_clock = container.clock
        self._registry = container.registry
        self._site = self._registry.settlement_site(config.venue, config.city)
        self._window = self._registry.climate_day_window(config.venue, config.city)
        self._deadline = self._registry.settlement_deadline(config.venue, config.city)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._warm_start_complete: asyncio.Event | None = None
        self._io_executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._parse_executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._catalog: Any = None
        # Mutated from SEVERAL threads at once -- Rust/tokio timer threads
        # (`_submit`), the loop thread, and whichever thread completes a future
        # (`_on_task_done`). Note the plural: there is no single tokio timer
        # thread. Two `LiveClock` timers armed for the same instant are MEASURED
        # running concurrently on distinct threads
        # (`tests/contract/test_live_timer_concurrency.py`), and this Actor arms
        # two -- the poll cadence and the final-overdue alert. So two `_submit`
        # calls really can be in flight together.
        #
        # `set.add`/`discard` are individually atomic under the GIL, but the cap
        # in `_submit` is a check-then-act pair and needs a real critical
        # section spanning BOTH halves.
        self._inflight_lock = threading.Lock()
        self._inflight: set[concurrent.futures.Future[None]] = set()
        self._parse_stalls = 0
        #: Reentrancy guard for :meth:`poll_once`. Loop-thread only.
        self._poll_in_flight = False
        self._retry_logger = Logger(f"NwsIngestActor.{config.venue}.{config.city}")
        self.parse_ceiling_seconds = config.parse_ceiling_seconds
        self.staleness_blocked_after_seconds = config.staleness_blocked_after_seconds

        self._cursor: ResumeCursor | None = self._load_cursor()

    # -- introspection --------------------------------------------------

    @property
    def venue(self) -> str:
        return self._config.venue

    @property
    def city(self) -> str:
        return self._config.city

    @property
    def event_loop(self) -> asyncio.AbstractEventLoop | None:
        """The loop captured in ``on_start``, or ``None`` in a backtest.

        ``None`` is the live-path guard: ``asyncio.get_running_loop()`` raising
        is the correct signal that the cross-thread bridge is unavailable, and
        the timer callback must then perform no network I/O rather than reaching
        for a fallback.
        """
        return self._loop

    @property
    def resume_cursor(self) -> ResumeCursor | None:
        return self._cursor

    @property
    def cursor_store_key(self) -> str:
        return f"{_CURSOR_KEY_PREFIX}{self.venue}:{self.city}"

    @property
    def backoff_store_key(self) -> str:
        return f"{_BACKOFF_KEY_PREFIX}{self.venue}:{self.city}"

    @property
    def validator_store_key(self) -> str:
        return f"{_VALIDATOR_KEY_PREFIX}{self.venue}:{self.city}"

    @property
    def backoff_until_ns(self) -> int:
        """The instant the inter-poll backoff window expires; ``0`` when clear.

        Read through the store on every access rather than cached: the window is
        a safety property, and a cached copy is a second source of truth for it.

        The ``get()`` is INSIDE the ``try``. In production the store is
        ``FileStateStore``, whose ``get()`` raises ``StateStoreCorruptError`` on a
        per-key CRC32 failure -- a ``RuntimeError`` subclass
        (``state_store.py:149,153``), so it is neither a decode error nor caught
        by the decode handler. Left outside, it raises out of :meth:`may_poll`
        into :meth:`poll_once` and thence into generic task death every cycle:
        the site does end up off the network, but by an unhandled exception
        rather than by this window, and this CRIT -- the one diagnostic that
        names the actual cause -- never fires. Failing closed by accident is not
        failing closed.
        """
        try:
            raw = self._store.get(self.backoff_store_key)
            if raw is None:
                return 0
            payload = json.loads(raw.decode("utf-8"))
            return int(payload["until_ns"])
        except (ValueError, KeyError, TypeError, UnicodeDecodeError, StateStoreCorruptError):
            logger.critical(
                "%s/%s: backoff window state is corrupt; failing closed by holding the "
                "site off the network until the next clean write",
                self.venue,
                self.city,
            )
            return self._wall_clock() + self._config.poll_interval_seconds * NS_PER_SECOND

    # -- lifecycle ------------------------------------------------------

    def on_start(self) -> None:
        """Capture the loop, prove the shared-instance invariant, arm the clocks."""
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            # A backtest. Base `Actor` exposes no loop attribute at all, and the
            # only other route is the private `ActorExecutor._loop`, so this is
            # the whole of the live-path detection.
            self._loop = None
            logger.info(
                "%s/%s: no running event loop at on_start -- backtest mode, no network I/O",
                self.venue,
                self.city,
            )

        self._container.register_site_actor(
            self.venue,
            self.city,
            component_id=str(self.id),
            gate=self._gate,
            product_index=self._index,
        )
        # TWO single-worker executors, not one, and not one with more workers.
        #
        # `asyncio.wait_for` cancels only the awaiting coroutine;
        # `concurrent.futures.Future.cancel()` is a no-op once a call has
        # STARTED, and Python cannot interrupt a running thread. A parse that
        # stalls therefore owns its worker permanently. Sharing one worker with
        # catalog I/O means every later write and every catalog read queues
        # behind that stall forever -- and because `may_poll()` deliberately
        # ignores general BLOCKED state, the timer keeps firing into a site that
        # can never complete the successful poll that would clear the block.
        #
        # Raising `max_workers` only buys N stalls before the same wedge, which
        # is a delay and not a fix. Isolation is the fix: with its own worker, a
        # wedged parse can starve nothing but later parses -- and those fail
        # loudly and fail closed, at `parse_ceiling_seconds`, through
        # `record_oversize_or_parse_timeout`.
        #
        # Both stay `max_workers=1`. For catalog I/O that is a requirement, not
        # a default: `write_records` takes an `flock` on the station root and
        # `write_records` demands non-decreasing `ts_init` within a batch, so
        # this station's catalog operations must stay serialised.
        self._io_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"breezy-nws-io-{self.city}"
        )
        self._parse_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"breezy-nws-parse-{self.city}"
        )
        self._catalog = open_station_catalog(self._container.catalog_base, self.venue, self.city)

        base = self.clock.utc_now()
        offset = dt.timedelta(seconds=self._config.stagger_index * self._config.stagger_seconds)
        self.clock.set_timer(
            name=poll_timer_name(self.venue, self.city),
            interval=dt.timedelta(seconds=self._config.poll_interval_seconds),
            start_time=base + offset,
            callback=self._on_poll_timer,
        )
        self.arm_final_overdue()

        # Republish anything the previous process persisted but never published
        # (SS3.3's crash window). Submitted rather than awaited, because `on_start`
        # is a synchronous Cython handler; skipped entirely in a backtest, where
        # there is no live bridge and the replay path supplies the data.
        #
        # The gate below is load-bearing, not tidiness. Warm start reads the
        # catalog through the same single-worker executor the poll writes
        # through, so without it the first poll can persist, publish and advance
        # the cursor WHILE warm start is still queued behind it -- and warm start
        # then republishes that same record against the cursor it read earlier.
        # `poll_once` therefore waits for warm start to finish before its first
        # fetch.
        if self._loop is not None:
            self._warm_start_complete = asyncio.Event()
            self._submit(self._run_warm_start(), what="warm-start")

    def on_stop(self) -> None:
        """Cancel every armed timer, then ask every in-flight submission to stop.

        ``cancel_timer`` runs ``Condition.is_in(name, self.timer_names)`` and
        raises ``KeyError`` for an unknown name (``component.pyx:991-995``), so a
        blind cancel would raise. ``cancel_timers()`` iterates the live names and
        is the safe form.

        The cancellation request is a REQUEST, not a drain, and the distinction
        is forced rather than chosen: ``on_stop`` is a synchronous Cython handler
        running ON the loop thread, so it cannot ``await``, and blocking here
        would deadlock against the very coroutines it waited for -- they need
        this same thread to progress. (``drain_for_test`` is ``async`` for that
        reason and is unusable from the real lifecycle.)

        ``run_coroutine_threadsafe``'s ``concurrent.futures.Future`` stays
        PENDING until its task finishes, so ``cancel()`` succeeds and
        ``_chain_future``'s ``_call_check_cancel`` hops ``task.cancel()`` onto
        the loop (``asyncio/futures.py:393-397``). The coroutine then raises
        ``CancelledError`` at its next await, which :meth:`_on_task_done` returns
        on quietly -- so a clean shutdown does not manufacture a gate strike out
        of a poll that was told to stop.

        This cannot hang on a wedged parse worker, which is the constraint that
        chose ``shutdown(wait=False)``: cancelling the awaiting coroutine never
        touches the worker thread, and that thread is abandoned either way.

        It SHRINKS the window :class:`ExecutorDisposedError` guards; it does not
        close it. ``dispose_resources`` is reachable without ``stop()``, and a
        coroutine already past its last await point cannot be cancelled.
        """
        self.clock.cancel_timers()
        with self._inflight_lock:
            outstanding = list(self._inflight)
        for future in outstanding:
            future.cancel()

    def on_reset(self) -> None:
        """Drop in-memory state only.

        The resume cursor deliberately survives: it is durable state whose whole
        purpose is to outlive a process, and clearing it here would re-publish
        the entire catalog on the next warm start.
        """
        with self._inflight_lock:
            self._inflight.clear()
        self._poll_in_flight = False

    def on_dispose(self) -> None:
        self.dispose_resources()

    def dispose_resources(self) -> None:
        """Release both executors. Idempotent.

        ``wait=False`` deliberately: a wedged parse worker cannot be
        interrupted, so waiting on it would make disposal itself hang. The
        thread is abandoned and dies when (if) its callable returns.
        """
        io_executor, self._io_executor = self._io_executor, None
        if io_executor is not None:
            io_executor.shutdown(wait=False, cancel_futures=True)
        parse_executor, self._parse_executor = self._parse_executor, None
        if parse_executor is not None:
            parse_executor.shutdown(wait=False, cancel_futures=True)

    def _require_executor(
        self,
        executor: concurrent.futures.ThreadPoolExecutor | None,
        *,
        kind: str,
    ) -> concurrent.futures.ThreadPoolExecutor:
        """The ONLY reader of the two executor attributes. Never returns ``None``.

        Every ``run_in_executor`` call in this class goes through here, so
        ``run_in_executor(None, ...)`` -- and the process-wide multi-worker
        executor CPython builds for it -- is structurally unreachable rather
        than merely avoided by convention. See :class:`ExecutorDisposedError`
        for why this raises instead of returning a shutting-down sentinel.
        """
        if executor is None:
            raise ExecutorDisposedError(
                f"{self.venue}/{self.city}: {kind} was requested after the executors were "
                f"disposed. Refusing to fall back to the loop's default executor: it is "
                f"multi-worker, which would break the single-worker serialisation that "
                f"`write_records`' station-root flock and its non-decreasing-`ts_init`-"
                f"within-a-batch requirement depend on"
            )
        return executor

    # -- the SS4.1 bridge -------------------------------------------------

    def _on_poll_timer(self, event: object) -> None:
        """Timer callback -- runs on a **Rust/tokio thread**. Submit and return.

        Three measured hazards are encoded here rather than merely known:
        Rust swallows any exception raised in this callback, so supervision must
        be explicit; the callback is concurrent-capable, so no Actor state is
        mutated here; and ``run_coroutine_threadsafe`` raises if the loop is
        closed, which is the shutdown race.

        "A" thread, not "the" thread. This Actor's two timers are MEASURED
        running concurrently on distinct threads
        (``tests/contract/test_live_timer_concurrency.py``), so this callback and
        :meth:`_on_final_overdue_timer` can be inside :meth:`_submit` at the same
        instant.
        """
        self._submit(self.poll_once(), what="poll")

    def _on_final_overdue_timer(self, event: object) -> None:
        """Final-overdue alert callback -- also a Rust thread. Submit and return.

        The gate write goes through the loop like every other one: brief SS4.1
        hazard 2 puts ALL state mutation on the loop thread.
        """
        pending_day, deadline_ns = self.pending_final_deadline()
        self._submit(self._record_final_overdue(pending_day, deadline_ns), what="final-overdue")

    def _submit(self, coro: Any, *, what: str) -> None:
        loop = self._loop
        if loop is None:
            # Backtest: the live bridge does not exist, so there is nothing to
            # submit to. Closing the coroutine avoids a "never awaited" warning.
            coro.close()
            logger.debug("%s/%s: %s suppressed -- no live loop", self.venue, self.city, what)
            return
        if loop.is_closed():
            # Shutdown race. Deliberately quiet rather than a gate strike: the
            # process is going away, and a CRIT here would fire on every clean
            # shutdown and train operators to ignore it.
            coro.close()
            logger.info("%s/%s: %s dropped -- loop closed", self.venue, self.city, what)
            return
        # Bound BEFORE scheduling. `may_poll()` deliberately does not consult
        # general BLOCKED state, so the timer keeps firing through any fault; an
        # unconditional `add` therefore leaks one future per cadence tick for as
        # long as the fault lasts.
        #
        # ONE hold of the lock spans the check, the schedule and the insert,
        # because they are a single check-then-act sequence -- not three. This
        # Actor arms TWO timers (the poll cadence and the final-overdue alert),
        # so two callbacks can be inside `_submit` at once, and a lock released
        # between the check and the insert admits both at the boundary: the set
        # lands at `MAX_INFLIGHT_TASKS + 1` with no CRITICAL logged, silently
        # defeating the alarm the cap exists to raise. The correctness of the
        # bound must not rest on how the Rust timer threads happen to be
        # scheduled, which is undocumented and free to change on a version bump.
        #
        # Holding the lock across `run_coroutine_threadsafe` is safe and
        # non-blocking: it takes no lock of ours, performs no `await`, and only
        # hands `call_soon_threadsafe` a callback (`asyncio/tasks.py`). Nothing
        # else in this critical section acquires a second lock, so there is no
        # lock-ordering hazard with `_on_task_done`, which takes this same lock
        # alone. `add_done_callback` stays OUTSIDE, both because it can run the
        # callback inline on an already-done future -- which would re-enter this
        # lock -- and to preserve the ordering guarantee below.
        with self._inflight_lock:
            if len(self._inflight) >= MAX_INFLIGHT_TASKS:
                coro.close()
                logger.critical(
                    "%s/%s: %s DROPPED -- %d in-flight submissions already outstanding, at "
                    "the cap of %d. In steady state this set holds at most a poll, a warm "
                    "start and a final-overdue record, so this means submissions are not "
                    "completing",
                    self.venue,
                    self.city,
                    what,
                    MAX_INFLIGHT_TASKS,
                    MAX_INFLIGHT_TASKS,
                )
                return
            try:
                future = asyncio.run_coroutine_threadsafe(coro, loop)
            except RuntimeError:
                # The loop finished closing between the `is_closed()` test above
                # and here. Nothing has been inserted yet, so there is no partial
                # state to unwind; the `with` block releases the lock on the way
                # out of this `return` like any other.
                coro.close()
                logger.info("%s/%s: %s dropped -- loop closing", self.venue, self.city, what)
                return
            self._inflight.add(future)
        # Attached AFTER the set membership above, so the callback's `discard`
        # can never run before the `add` it is meant to undo.
        future.add_done_callback(self._on_task_done)

    def _on_task_done(self, future: concurrent.futures.Future[None]) -> None:
        """Retrieve the failure. **This is the only supervision seam there is.**

        ``concurrent.futures.Future.add_done_callback`` runs on the completing
        thread -- or on the submitting (tokio) thread if the future was already
        done at attach time -- so nothing here may touch Actor state or the gate
        directly. The routing hop goes back through the loop.

        The ``is_closed()`` test and the hop are a TOCTOU pair: the loop can
        finish closing between them, and ``call_soon_threadsafe`` then raises
        ``RuntimeError`` INSIDE a ``concurrent.futures`` done-callback -- which
        CPython logs through its own internal logger and swallows. The failed
        poll would then never reach ``route_unhandled_exception`` and never be
        recorded as a gate strike: a dead poller behind an OPEN gate, reported
        nowhere this project looks. The pre-check is kept (it is the common,
        cheap case) and the hop is guarded, so all three branches genuinely land
        on the same CRIT.
        """
        with self._inflight_lock:
            self._inflight.discard(future)
        try:
            exc = future.exception()
        except concurrent.futures.CancelledError:
            return
        if exc is None:
            return
        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(self._handle_task_death, exc)
                return
            except RuntimeError:
                pass
        logger.critical(
            "%s/%s: poll task died with %r but the loop is gone; the gate could not "
            "be driven to BLOCKED",
            self.venue,
            self.city,
            exc,
        )

    def _handle_task_death(self, exc: BaseException) -> None:
        self._execute(route_unhandled_exception(exc))

    async def drain_for_test(self, timeout: float = 5.0) -> None:
        """Await every in-flight cross-thread submission. Test seam only."""
        deadline = asyncio.get_running_loop().time() + timeout
        while self._inflight:
            if asyncio.get_running_loop().time() > deadline:
                raise TimeoutError("in-flight poll tasks did not settle")
            await asyncio.sleep(0.005)
        await asyncio.sleep(0)

    def fire_poll_timer_for_test(self) -> None:
        """Invoke the poll timer callback exactly as the Rust thread would."""
        self._on_poll_timer(None)

    async def fire_final_overdue_for_test(self, climate_day: dt.date) -> None:
        """Invoke the final-overdue deadline for ``climate_day`` inline."""
        _, deadline_ns = self.pending_final_deadline()
        await self._record_final_overdue(climate_day, deadline_ns)

    async def force_ingest_for_test(self, product_uuid: str) -> None:
        """Run stage B for one product id, bypassing discovery."""
        await self._ingest_product(DiscoveryEntry(product_uuid, self._wall_clock()))

    def reset_cursor_for_test(self) -> None:
        """Simulate a crash between persist and publish."""
        self._cursor = None
        self._store.set(self.cursor_store_key, b"")

    # -- SS6 step 1: may we perform network I/O? --------------------------

    def may_poll(self) -> bool:
        """Whether network I/O is permitted right now.

        **This is deliberately NOT ``require_open``.** The settlement gate is a
        *use-time* gate consumed by the settlement resolver. It defaults to
        BLOCKED until a successful poll, and ``record_successful_poll`` is only
        reachable FROM a poll -- so "a blocked site does not poll" deadlocks on
        first boot and never recovers. Every per-site block is cleared only by a
        successful poll, so the same rule would turn one transient hiccup into a
        permanent outage requiring a database edit.

        Only two things genuinely forbid I/O: the GLOBAL ``ua_trap_blocked``
        latch (continuing to poll into a UA trap is what costs API access
        outright) and an active backoff window.
        """
        causes = self._gate.blocking_causes(self.venue, self.city)
        if GateReason.UA_TRAP_403 in causes:
            logger.error(
                "%s/%s: poll suppressed -- the GLOBAL UA-trap latch is set. It clears "
                "only through SettlementGate.acknowledge_ua_trap_resolved()",
                self.venue,
                self.city,
            )
            return False
        until = self.backoff_until_ns
        if until and self._wall_clock() < until:
            logger.info(
                "%s/%s: poll suppressed -- backoff window active for a further %.1fs",
                self.venue,
                self.city,
                (until - self._wall_clock()) / NS_PER_SECOND,
            )
            return False
        return True

    def arm_backoff(self, *, seconds: float, reason: str) -> None:
        """Open the inter-poll backoff window.

        Ours to own: ``RetryManager`` cannot honour ``Retry-After`` and holds no
        per-site state. Persisted, so a restart cannot launder the wait.
        """
        until = self._wall_clock() + int(max(seconds, 0.0) * NS_PER_SECOND)
        self._store.set(
            self.backoff_store_key,
            json.dumps({"until_ns": until, "reason": reason}).encode("utf-8"),
        )
        logger.warning(
            "%s/%s: backoff armed for %.1fs (%s)", self.venue, self.city, seconds, reason
        )

    def _clear_backoff(self) -> None:
        if self._store.get(self.backoff_store_key):
            self._store.set(self.backoff_store_key, json.dumps({"until_ns": 0}).encode("utf-8"))

    @staticmethod
    def _retry_after_seconds(value: str | None) -> float | None:
        """Read a ``Retry-After`` header value.

        Delta-seconds only. An HTTP-date form is deliberately not parsed: it
        depends on agreement with the origin's clock, and a skewed one would
        silently produce either no wait at all or an unbounded one.
        """
        if value is None:
            return None
        try:
            seconds = float(value.strip())
        except ValueError:
            return None
        return seconds if seconds >= 0 else None

    # -- SS6 -- the poll sequence -----------------------------------------

    async def poll_once(self) -> None:
        """One complete poll: discovery, dedupe, per-product ingest, publish.

        Two stages, not one. The missing stage in earlier designs was discovery,
        which is where ``product_uuid`` -- the identifier dedupe and the
        integrity tripwire key on -- comes from.

        **Non-reentrant, and an overlapping fire is SKIPPED rather than queued.**
        ``_submit`` schedules on every timer tick regardless of whether the
        previous poll is still in flight, and two overlapping polls can both pass
        the ``known_digest(...) is None`` check before either reaches
        ``_index.observe(...)``. Both then read the same catalog state and both
        compute ``revision_seq = 1`` for one ``(station, climate_day)``, breaking
        the monotonic-per-key invariant; the second write also trips a
        WRITE_INTEGRITY_VIOLATION CRIT manufactured out of a benign scheduling
        duplicate.

        Skipped, not queued, for two reasons. Queuing preserves ``_inflight``
        growth -- a poll that cannot finish accumulates one queued successor per
        cadence tick, which is the unbounded leak this whole seam is being fixed
        for. And the skipped work is worthless: a queued poll would re-fetch the
        same discovery list moments later, while the next scheduled tick is at
        most ``poll_interval_seconds`` (300 s default) away against an upstream
        that publishes twice a DAY. Latency cost, effectively nil; correctness
        cost of queuing, real.

        The flag is set and cleared entirely on the loop thread, with no ``await``
        between the test and the set, so the check-and-claim is atomic without a
        lock. It is deliberately NOT in ``_submit``: that runs on the Rust timer
        thread, where brief SS4.1 hazard 2 forbids mutating Actor state.
        """
        if self._poll_in_flight:
            logger.warning(
                "%s/%s: poll skipped -- the previous poll is still in flight. Overlapping "
                "polls race `revision_seq` for one (station, climate_day); the next "
                "scheduled tick will pick this up",
                self.venue,
                self.city,
            )
            return
        self._poll_in_flight = True
        try:
            await self._poll_once_guarded()
        finally:
            self._poll_in_flight = False

    async def _poll_once_guarded(self) -> None:
        """The poll body. Never call directly -- :meth:`poll_once` owns the guard."""
        await self._await_warm_start()
        self.check_staleness()
        if not self.may_poll():
            return

        if_none_match, if_modified_since = self._load_validators()
        try:
            fetch = await self._fetch_with_retry(
                "nws-discovery",
                self._transport.fetch_discovery_list,
                self._site.cli_location,
                if_none_match=if_none_match,
                if_modified_since=if_modified_since,
            )
        except TransportError as exc:
            self._execute(route_transport_error(exc))
            return

        decision = route_fetch_result(fetch)
        if decision.outcome is PollOutcome.NOT_MODIFIED:
            # Terminal branch. Freshness IS satisfied, so this records a
            # successful poll -- but no record is written and no digest recorded,
            # which is exactly why the final-overdue deadline runs on a wall
            # clock independent of poll outcome.
            self._store_validators(fetch)
            self._execute(decision)
            return
        if not decision.proceed:
            self._execute(decision)
            return

        self._store_validators(fetch)
        if fetch.text is None:  # pragma: no cover - FetchResult invariant
            raise CliContentError("a non-304 discovery response carried no body")

        try:
            entries = parse_discovery_list(fetch.text, cli_location=self._site.cli_location)
        except CliParseError as exc:
            self._execute(route_parse_failure(exc))
            return

        pending = [
            entry
            for entry in entries
            if self._index.known_digest(entry.product_uuid) is None
        ][: self._config.max_products_per_poll]

        if not pending:
            # Nothing new to fetch. A clean poll -- and the step that stops the
            # discovery list's stable ids being re-fetched, re-stamped with a
            # fresh `ts_init` and re-appended to the catalog every cycle. The
            # deferred `record_successful_poll` is redeemed here because there is
            # no write to gate it behind: nothing needed persisting.
            logger.info(
                "%s/%s: discovery returned %d CLI product(s), all already ingested",
                self.venue,
                self.city,
                len(entries),
            )
            self._execute(decision, redeem_deferred=True)
            return

        for entry in pending:
            if not await self._ingest_product(entry):
                return

    async def _ingest_product(self, entry: DiscoveryEntry) -> bool:
        """Stage B for one product. Returns whether the poll may continue."""
        try:
            fetch = await self._fetch_with_retry(
                "nws-product", self._transport.fetch_product, entry.product_uuid
            )
        except TransportError as exc:
            self._execute(route_transport_error(exc))
            return False

        decision = route_fetch_result(fetch)
        if not decision.proceed:
            self._execute(decision)
            return False
        if fetch.text is None:  # pragma: no cover - FetchResult invariant
            raise CliContentError("a non-304 product response carried no body")

        try:
            envelope = parse_product_envelope(fetch.text)
            # The structural allowlist runs ALONE and ahead of the parser: a
            # sibling station's product (CLIJFK on the NYC poll) or a CLM
            # monthly is routine, and must be rejected structurally rather than
            # parsed and caught downstream.
            header = check_structural_allowlist(
                envelope.product_text, cli_location=self._site.cli_location
            )
            parsed = await self._parse_with_ceiling(envelope.product_text)
            issuance = classify_issuance(envelope.product_text)
        except CliSanityError as exc:
            self._execute(route_sanity_violation(exc))
            return False
        except ClassificationError as exc:
            # Brief SS5 routes this to `record_ambiguous_headline`, but
            # `routing.GateAction` carries no member for it -- recorded directly
            # and flagged to the routing seam's owner.
            self._record_directly(
                "record_ambiguous_headline",
                f"{type(exc).__name__}: {exc}",
                hard_blocks_site=True,
            )
            return False
        except TimeoutError as exc:
            self._record_directly(
                "record_oversize_or_parse_timeout",
                f"parse exceeded the {self.parse_ceiling_seconds}s wall-clock ceiling: {exc}",
                hard_blocks_site=True,
            )
            return False
        except CliParseError as exc:
            routed = route_parse_failure(exc)
            self._execute(routed)
            # A sibling station's product is expected on a healthy system:
            # ignore it and carry on, never a block.
            return routed.outcome is PollOutcome.NOT_OUR_PRODUCT

        integrity = self._index.observe(entry.product_uuid, _sha256_text(envelope.product_text))
        if integrity.is_integrity_alarm:
            # The tripwire of brief SS3.4 job 2. It should never fire in steady
            # state -- NWS assigns a fresh uuid to every re-issue and
            # `/products/{id}` bodies are immutable by id -- and that is exactly
            # the point: it costs nothing until the assumption breaks. Do NOT
            # delete it as dead code.
            self._record_directly(
                "record_transport_integrity_alarm",
                f"product integrity MISMATCH for {entry.product_uuid}: {integrity.detail}",
                hard_blocks_site=True,
            )
            return False

        try:
            existing = await self._read_existing_off_loop(parsed.summary_date)
            records = self._build_records(fetch, envelope, parsed, header, existing)
            outcome = await self._write_off_loop(records)
        except NonCorrectionSupersessionError as exc:
            # A settlement-value regression, not a catalog fault -- so it is
            # recorded directly rather than routed, exactly like the two outcomes
            # named in the module docstring's deviation 3. Fail CLOSED: nothing is
            # written, and the site blocks until an operator has looked at it.
            self._record_directly(
                "record_write_integrity_violation", str(exc), hard_blocks_site=True
            )
            return False
        except tuple(catalog_error_routes()) as exc:
            self._execute(route_catalog_error(exc))
            return False

        write_decision = route_write_outcome(outcome)
        self._execute(write_decision)
        if not write_decision.proceed:
            return False

        # Sorted by the cursor's own key, never by build order. `advance_cursor`
        # overwrites unconditionally, so publishing out of cursor order leaves the
        # cursor BELOW the maximum key it just published -- and warm start, which
        # filters with a strict `>` on the same pair, then re-publishes the
        # remainder on every restart, forever. See `_cursor_key`.
        for record, data_type in sorted(records, key=lambda item: _cursor_key(item[0])):
            self.publish_record(record, data_type)

        if issuance == "FINAL":
            climate_day = _climate_day_of(records)
            if climate_day is not None:
                self._clear_final_overdue(climate_day)
        return True

    async def _read_existing_off_loop(self, climate_day: dt.date) -> NwsClimateDay | None:
        """Read the current record for ``(station, climate_day)`` OFF the loop.

        ``read_climate_day_including_corrections`` is documented "Unbounded on
        purpose" (``catalog.py:620-659``): it reads the station's WHOLE catalog
        per lookup through a pyarrow dataset scan, and that work grows
        monotonically with retention. It therefore carries the exact hazard
        :meth:`_write_off_loop`'s docstring names -- all five site Actors share
        ONE event loop, and the loop every venue heartbeat runs on must not be
        frozen by a settlement-history scan. It goes through the same I/O
        executor the write does, for the same reason and with the same
        serialisation against that station's catalog.

        The result is threaded into :meth:`_build_records` as a parameter rather
        than re-read there: one read, one answer, and the supersession guard and
        the ``revision_seq`` computation cannot disagree about what was on disk.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._require_executor(self._io_executor, kind="a settlement-history catalog read"),
            lambda: read_climate_day_including_corrections(
                self._catalog, station=self._site.cli_location, climate_day=climate_day
            ),
        )

    def _build_records(
        self,
        fetch: FetchResult,
        envelope: ProductEnvelope,
        parsed: ParsedCliProduct,
        header: CliStructuralHeader,
        existing: NwsClimateDay | None,
    ) -> list[tuple[Data, DataType]]:
        """Build the archive record and the settlement record.

        The order returned is build order, NOT publication order: the caller
        publishes through `_cursor_key` so that publication and warm start share
        one total order.

        Split deliberately (brief SS3.5): the two builders have different inputs
        and different failure modes, and only the second can fail on parse.

        ``header`` is threaded in from the caller's single structural scan rather
        than re-derived here. ``CliStructuralHeader``'s own docstring gives the
        reason: two independent scans of the same bytes for the same facts will
        eventually disagree, and the fact they would disagree about is "was this
        product a correction?" -- a supersession decision on a settled climate day.

        ``revision_seq`` is computed here -- monotonic per
        ``(station, climate_day)``, starting at 1. ``is_superseded`` is always
        ``False`` at write time: records are never rewritten, so it is a
        historical note about what was known then, not a selection input.

        ``existing`` is the current on-disk record for this
        ``(station, climate_day)``, read OFF the event loop by
        :meth:`_read_existing_off_loop` and threaded in. It is a parameter and
        not a second read for the same reason ``header`` is: the supersession
        guard and the ``revision_seq`` computation must be deciding against the
        SAME observation of the catalog.
        """
        raw = build_raw_product(
            site=self._site,
            registry_version=self._registry.registry_version,
            fetch=fetch,
            product_text=envelope.product_text,
            product_uuid=envelope.product_uuid,
            product_code=envelope.product_code,
            issuing_office=envelope.issuing_office,
            wmo_collective_id=envelope.wmo_collective_id,
            awips_pil=header.awips_pil,
            wmo_bbb_token=header.wmo_bbb,
            issuance_time_ns=envelope.issuance_time_ns,
            climate_day=parsed.summary_date,
        )
        revision_seq = 1 if existing is None else existing.revision_seq + 1
        if revision_seq > 1:
            logger.critical(
                "%s/%s: revision %d for climate_day=%s (correction_evidence=%s). If this day "
                "was already settled, the settlement resolver must re-check the LATEST "
                "revision, not the first ingested.",
                self.venue,
                self.city,
                revision_seq,
                parsed.summary_date.isoformat(),
                header.is_correction_bbb,
            )
        day = build_climate_day(
            site=self._site,
            window=self._window,
            raw_product=raw,
            parsed=parsed,
            parser_version=PARSER_VERSION,
            revision_seq=revision_seq,
            is_superseded=False,
        )
        self._guard_correction_supersession(existing=existing, incoming=day, header=header)
        return [
            (raw, raw_product_type(venue=self.venue, city=self.city)),
            (day, climate_day_type(venue=self.venue, city=self.city)),
        ]

    def _guard_correction_supersession(
        self,
        *,
        existing: NwsClimateDay | None,
        incoming: NwsClimateDay,
        header: CliStructuralHeader,
    ) -> None:
        """Refuse to let a NON-correction silently supersede a correction.

        ``revision_seq`` is assigned on ingestion ORDER, which is the whole
        problem: a delayed ``RRA`` retransmission of an uncorrected final that
        lands after a genuine ``CCA`` correction takes the higher revision, and
        ``RRx`` is a routine retransmission so nothing else in the system alarms
        on it. The corrected temperature reverts, silently.

        Three conditions, all required, so this cannot manufacture an outage out
        of routine NWS behaviour:

        1. Something is already stored for this ``(station, climate_day)`` and it
           IS a correction -- tested on the STORED record's ``correction_flag``.
        2. The incoming product is NOT a correction -- tested on
           ``header.is_correction_bbb`` ALONE.
        3. The incoming SETTLEMENT VALUES differ from the stored ones. An
           identical retransmission reverts nothing and stays an ordinary
           revision -- the same reasoning that keeps a sibling station's product
           from being a gate strike.

        **The two sides deliberately use DIFFERENT signals, and that asymmetry
        is the whole point rather than an oversight.** ``correction_flag`` is the
        free-text ``_CORRECTION_RE`` superset scanned over the WHOLE product
        body, so any incidental "CORRECTED"/"CORRECTION" wording -- a remark
        about a different date, say -- sets it. Widening a side to that superset
        has OPPOSITE consequences depending on which side it is:

        * **Stored side (condition 1), broad signal** -- the guard engages MORE
          often. Safe direction: at worst it costs an operator an alert.
        * **Incoming side (condition 2), broad signal** -- the guard engages LESS
          often, because the product gets to CLAIM it is a correction. Unsafe
          direction: a stale non-correction outranks a real correction and a
          settlement value silently reverts, with no alarm anywhere.

        Same widening, opposite consequence. So condition 2 uses
        ``header.is_correction_bbb``: the positional, structurally-validated
        verdict off the WMO BBB token, which ``classify.py:68-70`` explicitly
        designates for *supersession decisions* while designating the free-text
        flag ADVISORY and "for the audit trail" (``:64-65``). ``CC[A-Z]`` also
        means a genuine ``CCB`` following a ``CCA`` is still positionally a
        correction (``cli_parse._CORRECTION_BBB_RE``), so a second correction to
        one climate day passes cleanly and this cannot manufacture an outage out
        of NWS working correctly.

        Raises
        ------
        NonCorrectionSupersessionError
            Routed by :meth:`_ingest_product` to
            ``record_write_integrity_violation``: block the site, write nothing.
        """
        if existing is None or not existing.correction_flag:
            return
        # `incoming.correction_flag` is deliberately NOT consulted here -- see the
        # asymmetry argument in the docstring. On this side the free-text
        # superset would let any product carrying the word "CORRECTED" anywhere
        # in its body disclaim the guard.
        if header.is_correction_bbb:
            return
        if _settlement_values(incoming) == _settlement_values(existing):
            return
        raise NonCorrectionSupersessionError(
            f"a NON-correction issuance would supersede the stored correction for "
            f"station={existing.station} climate_day={existing.climate_day.isoformat()}: "
            f"stored revision {existing.revision_seq} "
            f"{_settlement_values(existing)} (correction_flag=True) vs incoming "
            f"{_settlement_values(incoming)} "
            f"(wmo_bbb={header.wmo_bbb!r}, is_correction_bbb={header.is_correction_bbb}, "
            f"correction_flag={incoming.correction_flag}). Refusing the write: "
            f"`revision_seq` is assigned on ingestion order, so this would outrank the "
            f"correction and silently revert a corrected settlement value"
        )

    async def _parse_with_ceiling(self, product_text: str) -> ParsedCliProduct:
        """Parse under a real wall-clock ceiling.

        Deviation 1 of the module docstring: this runs on the thread pool rather
        than inline. ``asyncio.wait_for`` around a synchronous call cannot
        interrupt it, so an inline parse has no ceiling that can ever fire --
        which would leave SS6's runtime guarantee depending on regex authors never
        regressing. On the pool, a stalled parse costs one worker thread and the
        event loop keeps serving every other component in the process.

        It costs one worker on the parse-ONLY executor, and that separation is
        what makes the previous sentence true of catalog I/O as well. Cancelling
        the ``wait_for`` cancels the awaiting coroutine, and (through
        ``asyncio.futures._chain_future``) the underlying
        ``concurrent.futures.Future`` too -- which removes the work item if it has
        not STARTED, and does nothing at all if it has. So the ceiling bounds the
        loop's wait, never the worker's occupancy: the honest accounting is that a
        started-and-stalled parse is permanently lost, and every subsequent parse
        for this site then fails closed at the ceiling through
        ``record_oversize_or_parse_timeout``. That is loud, per-poll, and
        recoverable by restart -- and, crucially, it no longer takes the write and
        warm-start paths down with it.
        """
        loop = asyncio.get_running_loop()
        executor = self._require_executor(self._parse_executor, kind="a CLI parse")
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(
                    executor,
                    lambda: parse_cli_product(
                        product_text,
                        cli_location=self._site.cli_location,
                        body_header_regex=self._site.body_header_regex,
                    ),
                ),
                timeout=self.parse_ceiling_seconds,
            )
        except TimeoutError:
            # Explicit supervision, because the thread cannot be reclaimed. The
            # caller routes the timeout to the gate; this records the SEPARATE
            # fact that a parse worker may now be permanently occupied, which is
            # the thing an operator needs in order to decide on a restart.
            self._parse_stalls += 1
            logger.critical(
                "%s/%s: parse exceeded %.3fs and cannot be interrupted; the parse worker "
                "may be permanently occupied (stall #%d). Catalog I/O is on a separate "
                "executor and is unaffected, but every further parse for this site will "
                "fail closed at the ceiling until the process is restarted",
                self.venue,
                self.city,
                self.parse_ceiling_seconds,
                self._parse_stalls,
            )
            raise

    async def _write_off_loop(self, records: Sequence[tuple[Data, DataType]]) -> WriteOutcome:
        """Persist off the event loop (brief SS3.1).

        The blocking work is catalog I/O, not the parse: ``write_records`` takes
        an ``flock`` on the station root and performs two pyarrow read-backs, and
        the as-of accessors read the station's whole catalog per lookup. That
        work grows monotonically with retention and would freeze the identical
        loop every venue heartbeat runs on. ``loop.run_in_executor`` is the
        asyncio method and is unaffected by the ``Actor.run_in_executor`` finding.
        """
        loop = asyncio.get_running_loop()
        payload = [record for record, _ in records]
        return await loop.run_in_executor(
            self._require_executor(self._io_executor, kind="a catalog write"),
            lambda: write_records(self._catalog, payload),
        )

    async def _fetch_with_retry(
        self, name: str, func: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> FetchResult:
        """Run one fetch through the intra-poll ``RetryManager``.

        ONE retry sequence collapses into ONE gate strike: three TCP attempts
        inside one poll are not three failed polls. That is a deliberate change
        to what ``gate._TRANSIENT_DEGRADE_THRESHOLD`` counts -- a strike now means
        one retry-EXHAUSTED poll, not one network hiccup -- and it is stated here
        rather than absorbed silently.

        ``RetryManager.run`` returns a bare ``None`` on failure and logs through
        the Nautilus ``Logger``, which discards records when logging is
        uninitialized (``component.pyx:1450-1451``). The failure is therefore read
        off ``.result``/``.last_exception``, never off log output, and it is
        re-raised so the caller's exact-type routing sees the original exception
        rather than a ``None`` that would fall through as success.
        """
        manager: RetryManager[FetchResult] = RetryManager(
            max_retries=self._config.max_retries,
            delay_initial_ms=self._config.retry_delay_initial_ms,
            delay_max_ms=self._config.retry_delay_max_ms,
            backoff_factor=self._config.retry_backoff_factor,
            logger=self._retry_logger,
            exc_types=RETRYABLE_TRANSPORT_ERRORS,
        )
        result = await manager.run(name, [self.venue, self.city], func, *args, **kwargs)
        if manager.result and result is not None:
            return result
        exc = manager.last_exception
        if exc is None:
            raise TransportError(
                f"{name} produced neither a result nor an exception "
                f"(RetryManager.message={manager.message!r})"
            )
        raise exc

    # -- decision execution ---------------------------------------------

    def _execute(self, decision: RouteDecision, *, redeem_deferred: bool = False) -> None:
        """Drive the gate from one routed outcome, then mirror it to the operator.

        ``GateAction.value`` is the literal recorder name, so dispatch is
        ``getattr``. ``action is None`` means call no recorder at all -- exactly
        one outcome uses it (a sibling station's product), and recording anything
        there would manufacture an outage out of normal operation.
        """
        logger.log(_LOG_LEVELS[decision.severity.value], "%s/%s: %s", self.venue, self.city, decision.detail)

        # `route_fetch_result` carries `retry_after` through on EVERY branch,
        # success included, so this must be gated on the outcome rather than on
        # the header's presence: a 200 that happens to carry `Retry-After` must
        # not put the site into backoff.
        if decision.retry_after is not None and decision.action is not (
            GateAction.RECORD_SUCCESSFUL_POLL
        ):
            seconds = self._retry_after_seconds(decision.retry_after)
            if seconds is not None:
                self.arm_backoff(seconds=seconds, reason=f"Retry-After on {decision.outcome.value}")

        if decision.action is None:
            return
        if decision.action_is_deferred and not redeem_deferred:
            # `record_successful_poll` on a FETCHED would open the gate over data
            # that has not been persisted or verified. `route_write_outcome`
            # redeems it at SS6 step 11.
            return

        recorder = getattr(self._gate, decision.action.value)
        kwargs: dict[str, Any] = {"detail": decision.detail}
        if decision.needs_cross_site_burst_signal:
            kwargs["cross_site_burst_detected"] = self._container.observe_forbidden_403(
                self.venue, self.city
            )
        if decision.needs_final_window_signal:
            kwargs["final_window_elapsed"] = False
        recorder(self.venue, self.city, **kwargs)

        if decision.action is GateAction.RECORD_SUCCESSFUL_POLL:
            self._clear_backoff()
        self._mirror_component_state()

    def _record_directly(self, recorder_name: str, detail: str, *, hard_blocks_site: bool) -> None:
        """Call a gate recorder that ``routing.py`` carries no row for.

        Two exist today (see the module docstring, deviation 3). Kept as an
        explicit, named path rather than an ad-hoc call so they are greppable
        when the routing table grows rows for them.
        """
        logger.critical("%s/%s: %s", self.venue, self.city, detail)
        getattr(self._gate, recorder_name)(self.venue, self.city, detail=detail)
        self._mirror_component_state()

    def _mirror_component_state(self) -> None:
        """Mirror gate BLOCKED onto ``Component.degrade()``.

        Adopted as an OUTPUT, never as the representation: operators get
        ``ComponentStateChanged`` on ``events.system.{id}``, and gate truth is
        never read back from component state. ``fault()`` is never called -- it is
        terminal, and our BLOCKED must be clearable by a clean poll.
        """
        # Branch on `state`, NEVER on `reason`: `GateStatus.reason` is the most
        # recent transition EVENT, not the current root cause -- a successful poll
        # on a site still blocked by something else sets `reason=SUCCESSFUL_POLL`
        # while `state` correctly stays BLOCKED.
        blocked = self._gate.status(self.venue, self.city).state is GateState.BLOCKED
        if blocked and self.is_running:
            self.degrade()
        elif not blocked and self.is_degraded:
            self.resume()

    # -- staleness watchdog ----------------------------------------------

    def check_staleness(self) -> None:
        """Escalate a silent poll channel. Nautilus ships no HTTP equivalent."""
        self._gate.check_freshness(
            self.venue,
            self.city,
            degraded_after_ns=self._config.staleness_degraded_after_seconds * NS_PER_SECOND,
            blocked_after_ns=self.staleness_blocked_after_seconds * NS_PER_SECOND,
        )
        self._mirror_component_state()

    # -- the final-overdue deadline --------------------------------------

    def pending_final_deadline(self) -> tuple[dt.date, int]:
        """The climate day whose final is next due, and the venue-clock instant.

        The climate day runs local-STANDARD midnight to midnight -- never UTC and
        never the DST-adjusted clock -- so the day boundary comes from
        ``climate_day_window``. The DEADLINE is the venue's civil clock (08:00 ET
        for all five cities, including the three not in ET), which DOES observe
        DST, so it comes from ``settlement_deadline``. Two different clocks, two
        different accessors, deliberately not interchangeable.
        """
        now_ns = self._wall_clock()
        now = dt.datetime.fromtimestamp(now_ns / NS_PER_SECOND, tz=dt.UTC)
        station_now = now + dt.timedelta(hours=self._window.std_utc_offset_hours)
        candidate = station_now.date() - dt.timedelta(days=1)
        deadline_ns = self._deadline_ns(candidate)
        if deadline_ns <= now_ns:
            candidate = station_now.date()
            deadline_ns = self._deadline_ns(candidate)
        return candidate, deadline_ns

    def _deadline_ns(self, climate_day: dt.date) -> int:
        """The venue settlement instant for the day AFTER ``climate_day``."""
        local = dt.time.fromisoformat(self._deadline.settlement_time_local)
        zone = ZoneInfo(self._deadline.settlement_timezone)
        moment = dt.datetime.combine(climate_day + dt.timedelta(days=1), local, tzinfo=zone)
        return int(moment.timestamp() * NS_PER_SECOND)

    def arm_final_overdue(self) -> None:
        """Arm (or re-arm) the wall-clock deadline for the pending climate day.

        ``override=True`` is required: a duplicate name without it raises
        ``KeyError`` (``component.pyx:316``, verified). ``allow_past=False``
        rejects a past instant rather than firing immediately, and
        :meth:`pending_final_deadline` guarantees a future one.

        This schedule is INDEPENDENT of poll outcome, and that is the whole
        point: it is the only orthogonal defence against a perpetual-304
        staleness attack, where every poll succeeds, ``last_successful_poll_ns``
        keeps resetting, and no record is ever written.
        """
        climate_day, deadline_ns = self.pending_final_deadline()
        self.clock.set_time_alert(
            name=final_overdue_timer_name(self.city, climate_day),
            alert_time=dt.datetime.fromtimestamp(deadline_ns / NS_PER_SECOND, tz=dt.UTC),
            callback=self._on_final_overdue_timer,
            override=True,
            allow_past=False,
        )

    async def _record_final_overdue(self, climate_day: dt.date, deadline_ns: int) -> None:
        self._gate.record_final_overdue(
            self.venue, self.city, climate_day.isoformat(), deadline_ns
        )
        self._mirror_component_state()
        self.arm_final_overdue()

    def _clear_final_overdue(self, climate_day: dt.date) -> None:
        """Clear the deadline for the EXACT climate day whose final just arrived."""
        self._gate.record_final_received(self.venue, self.city, climate_day.isoformat())
        name = final_overdue_timer_name(self.city, climate_day)
        if self.clock.next_time_ns(name) > 0:
            self.clock.cancel_timer(name)
        self._mirror_component_state()

    # -- publication and the resume cursor -------------------------------

    def publish_record(self, record: Data, data_type: DataType) -> None:
        """Publish one record, then advance the durable cursor.

        The RAW record is published, never a ``CustomData`` wrapper:
        ``publish_data`` runs ``Condition.type(data, data_type.type, ...)``
        (``actor.pyx:2827``) and a wrapper raises ``TypeError``. The wrapper
        governs data submitted to the ``DataEngine``, not data an Actor
        publishes.

        The cursor advances AFTER the publish and is written durably in the same
        call, so it is correct at the instant of any crash: a record published
        with no durable cursor would be re-published on warm start (harmless);
        a cursor advanced before publication would lose the record (not).
        """
        self.publish_data(data_type, record)
        self.advance_cursor(ts_init=record.ts_init, dedupe_key=_dedupe_key(record))

    def advance_cursor(self, *, ts_init: int, dedupe_key: str) -> None:
        cursor = ResumeCursor(ts_init=ts_init, dedupe_key=dedupe_key)
        self._cursor = cursor
        self._store.set(
            self.cursor_store_key,
            json.dumps({"ts_init": cursor.ts_init, "dedupe_key": cursor.dedupe_key}).encode(
                "utf-8"
            ),
        )

    def is_after_cursor(self, *, ts_init: int, dedupe_key: str) -> bool:
        """Whether a record still needs publishing. Strict ``>`` on the pair."""
        if self._cursor is None:
            return True
        return self._cursor.precedes(ts_init=ts_init, dedupe_key=dedupe_key)

    def _load_cursor(self) -> ResumeCursor | None:
        """Load the durable cursor, failing TOWARDS re-publishing.

        The ``get()`` is INSIDE the ``try`` for the reason given on
        :attr:`backoff_until_ns`, with a sharper consequence here: this runs from
        ``__init__``, so a ``StateStoreCorruptError`` escaping it takes the
        Actor's CONSTRUCTION down. The site then does not exist, cannot poll, and
        the documented direction -- re-publish rather than risk losing a
        settlement record -- never gets a chance to apply.
        """
        try:
            raw = self._store.get(self.cursor_store_key)
            if not raw:
                return None
            payload = json.loads(raw.decode("utf-8"))
            return ResumeCursor(
                ts_init=int(payload["ts_init"]), dedupe_key=str(payload["dedupe_key"])
            )
        except (ValueError, KeyError, TypeError, UnicodeDecodeError, StateStoreCorruptError):
            logger.critical(
                "%s/%s: resume cursor is unreadable; warm start will re-publish from the "
                "beginning of this station's catalog rather than risk losing a record",
                self.venue,
                self.city,
            )
            return None

    async def _run_warm_start(self) -> None:
        """Warm start, always releasing the gate that :meth:`poll_once` waits on.

        The ``finally`` matters: if warm start raises, the exception still
        reaches the done-callback and drives the gate to BLOCKED via
        ``record_task_death``, but polling must not be wedged behind an event
        that will never be set. Fail closed on the DATA, not on the loop.
        """
        try:
            await self.warm_start()
        finally:
            if self._warm_start_complete is not None:
                self._warm_start_complete.set()

    async def _await_warm_start(self) -> None:
        event = self._warm_start_complete
        if event is None or event.is_set():
            return
        try:
            await asyncio.wait_for(
                event.wait(), timeout=self._config.warm_start_timeout_seconds
            )
        except TimeoutError:
            logger.critical(
                "%s/%s: warm start did not finish within %.0fs; polling anyway. Records "
                "persisted by a previous process may be republished once warm start "
                "completes",
                self.venue,
                self.city,
                self._config.warm_start_timeout_seconds,
            )

    async def warm_start(self) -> None:
        """Republish everything past the cursor from this Actor's OWN catalog.

        ``request_data`` and ``DataEngine.register_catalog`` are NOT used, and
        that is a correctness ruling rather than a preference:
        ``DataEngine._query_catalog`` breaks on the FIRST registered catalog that
        returns rows, so with one catalog root per station, stations 2..N would
        silently warm-start from station 1's records -- confidently wrong data for
        four of five cities. ``catalog.custom_data`` also drops ``metadata``, so
        the response would publish on the metadata-less topic
        ``historical.data.NwsClimateDay*`` that no production subscriber matches.

        Republication therefore goes through the SAME shared ``DataType``
        factory as the live path, which is what makes the two topics one string.
        Consequently ``on_historical_data`` is never called; it is deliberately
        not implemented as dead code.
        """
        loop = asyncio.get_running_loop()
        raws, days = await loop.run_in_executor(
            self._require_executor(self._io_executor, kind="a warm-start catalog read"),
            self._read_catalog,
        )

        pending: list[tuple[Data, DataType]] = []
        for raw in raws:
            if not raw.verify_digest():
                # sha256(raw_text) is computed at ingestion and verified before
                # any later settlement use. A stored digest alone is circular.
                logger.critical(
                    "%s/%s: stored digest MISMATCH for product_uuid=%s climate_day=%s -- the "
                    "archived text was mutated at rest; refusing to republish it",
                    self.venue,
                    self.city,
                    raw.product_uuid,
                    raw.climate_day,
                )
                continue
            if self.is_after_cursor(ts_init=raw.ts_init, dedupe_key=_dedupe_key(raw)):
                pending.append((raw, raw_product_type(venue=self.venue, city=self.city)))
        for day in days:
            if self.is_after_cursor(ts_init=day.ts_init, dedupe_key=_dedupe_key(day)):
                pending.append((day, climate_day_type(venue=self.venue, city=self.city)))

        pending.sort(key=lambda item: _cursor_key(item[0]))
        for record, data_type in pending:
            self.publish_record(record, data_type)

    def _read_catalog(self) -> tuple[list[NwsRawProduct], list[NwsClimateDay]]:
        return read_raw_products(self._catalog), read_climate_days(self._catalog)

    def _store_validators(self, fetch: FetchResult) -> None:
        """Persist the discovery list's ``ETag``/``Last-Modified`` for the next poll.

        Conditional GET is correct on the discovery LIST -- a mutable index of
        what exists -- and never on ``/products/{id}``, whose bodies are immutable
        by id. The transport enforces the latter structurally:
        ``fetch_product`` takes no validator parameters at all.
        """
        etag = fetch.headers.get("etag")
        last_modified = fetch.headers.get("last-modified")
        if etag is None and last_modified is None:
            return
        self._store.set(
            self.validator_store_key,
            json.dumps({"etag": etag, "last_modified": last_modified}).encode("utf-8"),
        )

    def _load_validators(self) -> tuple[str | None, str | None]:
        """Load the stored conditional-GET validators, dropping them on doubt.

        The ``get()`` is INSIDE the ``try`` for the reason given on
        :attr:`backoff_until_ns`. This runs at the top of :meth:`poll_once`,
        BEFORE any fetch, so a ``StateStoreCorruptError`` escaping it blocks the
        site outright -- the opposite of the documented direction, which is one
        uncached fetch.
        """
        try:
            raw = self._store.get(self.validator_store_key)
            if not raw:
                return None, None
            payload = json.loads(raw.decode("utf-8"))
            etag = payload.get("etag")
            last_modified = payload.get("last_modified")
        except (ValueError, TypeError, UnicodeDecodeError, StateStoreCorruptError):
            # A malformed validator is remote data we STORED and would echo back
            # into an outbound header. Dropping it and fetching unconditionally
            # is the safe direction here: the cost is one uncached fetch.
            logger.warning(
                "%s/%s: stored cache validators are unreadable; fetching unconditionally",
                self.venue,
                self.city,
            )
            return None, None
        return (
            etag if isinstance(etag, str) else None,
            last_modified if isinstance(last_modified, str) else None,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LOG_LEVELS: Final[dict[str, int]] = {
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "CRIT": logging.CRITICAL,
}


def _sha256_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _dedupe_key(record: Data) -> str:
    """The cursor's tie-breaker: the record's own dedupe key.

    Both record types carry ``raw_sha256``, so the key is recoverable from the
    catalog after a restart -- which a per-Actor publish sequence would not be.
    The record class name is prefixed so the archive and settlement records from
    one fetch, which share both ``ts_init`` and ``raw_sha256``, still order
    deterministically.
    """
    digest = getattr(record, "raw_sha256", "")
    return f"{type(record).__name__}:{digest}"


def _cursor_key(record: Data) -> tuple[int, str]:
    """The resume cursor's total order. **One definition, used by BOTH paths.**

    The live publish loop and warm start must agree on this ordering or the
    cursor is unsound: `advance_cursor` overwrites unconditionally, so a
    publication order that disagrees with this one settles the cursor below the
    greatest key it published, and warm start's strict `>` then re-publishes
    everything above it on every single restart. Two records from one fetch share
    `ts_init`, so the tiebreaker alone decides which way that falls.
    """
    return (record.ts_init, _dedupe_key(record))


def _settlement_values(
    record: NwsClimateDay,
) -> tuple[int | None, int | None, int | None, str | None, str | None, str | None]:
    """The settlement-bearing content of a climate-day record.

    Value/sentinel-flag PAIRS, not bare values: ``tmax_f`` is ``None`` both when
    NWS published a sentinel and when a field is absent, so comparing values
    alone would call a trace and a missing reading identical.

    Deliberately excludes provenance (``ts_init``, ``revision_seq``,
    ``raw_sha256``, ``retrieved_at_ns``, ``product`` identity): those differ on
    every re-issue by construction, so including them would make every
    retransmission look like a content change and turn
    :meth:`NwsIngestActor._guard_correction_supersession` into a blanket block on
    routine NWS behaviour.
    """
    return (
        record.tmax_f,
        record.tmin_f,
        record.tavg_f,
        record.tmax_flag,
        record.tmin_flag,
        record.tavg_flag,
    )


def _climate_day_of(records: Sequence[tuple[Data, DataType]]) -> dt.date | None:
    for record, _ in records:
        if isinstance(record, NwsClimateDay):
            return record.climate_day
    return None
