"""Poll-outcome error routing: one pure decision per possible poll result.

Implements the routing table in `docs/plans/PHASE1_ACTOR_BRIEF.md` §5. Every
transport, status-code, parse, write and supervision outcome of an NWS poll
maps to exactly one :class:`GateAction`, with a severity and the handful of
flags the Actor needs to execute it.

**This module decides; it never acts.** It does not import
:mod:`breezy.ingest.gate`, never constructs a `SettlementGate`, and returns a
frozen :class:`RouteDecision` for the caller to execute. That purity is
deliberate: it is what makes the table exhaustively testable without a live
gate, a live catalog, or a live socket. It is also why this module -- like
`gate.py` and `http.py` -- imports no `nautilus_trader` (the write-outcome
input is bound structurally, see :class:`WriteOutcomeLike`).

Three things in the table are easy to get wrong, and each has a dedicated
branch below rather than an incidental one:

**F4 -- "no exception" does not mean "success".** `http.py` raises only for
3xx (except 304), 403, 429 and 5xx. A **400 or 404 returns a normal
`FetchResult`**. So :func:`route_fetch_result` branches on `status_code` and
treats anything outside 2xx/304 as a failure. A 404 on a *configured* CLI
location is a **binding error** -- the station binding is wrong, and no amount
of retrying will make a mistyped location exist -- so it hard blocks rather
than joining the transient counter.

**304 is a no-op success.** Freshness is satisfied, so it routes to
`record_successful_poll`; but **no record is written and no digest is
recorded** (`FetchResult.text` and `.sha256` are both `None` by
`__post_init__` invariant). `RouteDecision.writes_record` is `False` for it,
so nothing downstream may infer a provenance record exists.

**Integrity alarms are not transport hiccups.** `RedirectError`,
`ContentEncodingError`, `DisallowedHostError`, `OversizeBodyError` and
`ProxyEnvironmentError` all hard block. `ContentEncodingError` in particular
means the SHA-256 digest would attest to *decompressed* bytes rather than what
came off the wire: a provenance failure, not a networking one. Only
`RateLimitedError`, `ServerError`, `TransportTimeoutError` and the bare
`TransportError` (connection reset / DNS failure, raised at `http.py`'s
generic `httpx.TransportError` branch) are transient.

A conditional-GET validator (`InvalidCacheValidatorError`) is an integrity
alarm for the same reason: a stored `ETag`/`Last-Modified` is **remote data we
persisted and echo back into an outbound request header**. Malformed means
either corrupted persisted state or a server attempting header injection
through a value we trusted enough to replay. It is deliberately *not* routed
to "drop the validator and retry unconditionally" -- that reads as graceful
degradation while silently converting a possible injection attempt into a
successful poll.

Two taxonomies are routed here, and both are enumerated by contract tests:
`ingest.http`'s `TransportError` tree, and `persistence.catalog`'s write-path
exceptions (reached through a deferred import -- see
:func:`catalog_error_routes` for why that indirection is load-bearing rather
than decorative).

Dispatch is on **exact type**, not `isinstance`. A future subclass therefore
lands on the fail-closed fallback (CRIT integrity alarm) instead of silently
inheriting "retry me" from its parent -- which matters most for the two cases
where a parent is benign: the bare `TransportError` base is routed
*transient*, and `ConcurrentWriterError` subclasses `WriterLockError`. Under
an `isinstance` chain, "forgot to route it" would quietly mean "retry it
forever". `tests/contract/test_transport_error_routing_contract.py` fails
loudly so an unrouted subclass never ships in the first place -- it has
already caught one for real.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from functools import cache
from types import MappingProxyType
from typing import Protocol

from breezy.ingest.http import (
    ContentEncodingError,
    DecodeError,
    DisallowedHostError,
    FetchResult,
    ForbiddenError,
    InvalidCacheValidatorError,
    OversizeBodyError,
    ProxyEnvironmentError,
    RateLimitedError,
    RedirectError,
    ServerError,
    TransportError,
    TransportTimeoutError,
    redact_url,
)
from breezy.normalize.cli_parse import (
    CliContentError,
    CliNotOurProductError,
    CliParseError,
    CliStructuralError,
)
from breezy.normalize.sanity import CliSanityError

__all__ = [
    "INTEGRITY_ALARM_OUTCOMES",
    "OUTCOME_SPECS",
    "PARSE_ERROR_ROUTES",
    "TRANSIENT_OUTCOMES",
    "TRANSPORT_ERROR_ROUTES",
    "GateAction",
    "OutcomeSpec",
    "PollOutcome",
    "RouteDecision",
    "Severity",
    "WriteOutcomeLike",
    "catalog_error_routes",
    "route_catalog_error",
    "route_fetch_result",
    "route_parse_failure",
    "route_sanity_violation",
    "route_transport_error",
    "route_unhandled_exception",
    "route_write_outcome",
]


# ---------------------------------------------------------------------------
# Public enums
# ---------------------------------------------------------------------------


class Severity(StrEnum):
    """How loudly the Actor logs the routing event itself.

    Distinct from the gate's own transition log level: the gate derives that
    from the resulting `GateState` plus its own CRIT-reason set. This is the
    severity of the *routing* event, for the Actor's log line and any alarm
    plumbed off it.
    """

    INFO = "INFO"
    WARNING = "WARNING"
    CRIT = "CRIT"


class GateAction(StrEnum):
    """The single `SettlementGate` recorder a poll outcome routes to.

    Each member's **value is the literal method name**, so an Actor dispatches
    with `getattr(gate, decision.action.value)(venue, city, detail=...)`.
    A unit test asserts every value resolves to a real callable on
    `SettlementGate`, so a rename over there fails here rather than at 07:30
    on a live poll.
    """

    RECORD_SUCCESSFUL_POLL = "record_successful_poll"
    RECORD_FORBIDDEN_403 = "record_forbidden_403"
    RECORD_TRANSIENT_FAILURE = "record_transient_failure"
    RECORD_PARSER_FAILURE = "record_parser_failure"
    RECORD_SANITY_VIOLATION = "record_sanity_violation"
    RECORD_OVERSIZE_OR_PARSE_TIMEOUT = "record_oversize_or_parse_timeout"
    RECORD_CLIENT_ERROR_DEFECT = "record_client_error_defect"
    RECORD_REDIRECT_INTEGRITY_ALARM = "record_redirect_integrity_alarm"
    RECORD_TRANSPORT_INTEGRITY_ALARM = "record_transport_integrity_alarm"
    RECORD_WRITE_INTEGRITY_VIOLATION = "record_write_integrity_violation"
    RECORD_TASK_DEATH = "record_task_death"


class PollOutcome(StrEnum):
    """What actually happened -- one member per row of the brief's §5 table.

    Deliberately finer-grained than :class:`GateAction`: several outcomes share
    a recorder (every integrity alarm but the redirect routes to
    `record_transport_integrity_alarm`), and collapsing them at this level
    would throw away exactly the diagnostic distinction the table exists to
    keep. Metrics and logs key on this; the gate keys on the action.
    """

    # -- success --------------------------------------------------------
    FETCHED = "fetched"
    NOT_MODIFIED = "not_modified"
    PERSISTED = "persisted"

    # -- integrity alarms (hard block, CRIT) -----------------------------
    REDIRECT = "redirect"
    CONTENT_ENCODING = "content_encoding"
    DISALLOWED_HOST = "disallowed_host"
    OVERSIZE_BODY = "oversize_body"
    PROXY_ENVIRONMENT = "proxy_environment"
    UNROUTED_TRANSPORT_ERROR = "unrouted_transport_error"
    TRANSPORT_CONTRACT_VIOLATION = "transport_contract_violation"
    CACHE_VALIDATOR = "cache_validator"
    WRITE_INTEGRITY_VIOLATION = "write_integrity_violation"

    # -- catalog write path (hard block, CRIT) ---------------------------
    CATALOG_PATH_DEFECT = "catalog_path_defect"
    NON_MONOTONIC_WRITE = "non_monotonic_write"
    WRITER_LOCK_FAILURE = "writer_lock_failure"
    CONCURRENT_WRITER = "concurrent_writer"
    CATALOG_WRITE_GROUPING_DRIFT = "catalog_write_grouping_drift"
    WRITER_LOCK_FILESYSTEM = "writer_lock_filesystem"
    UNROUTED_CATALOG_ERROR = "unrouted_catalog_error"

    # -- data quality (hard block, CRIT) ---------------------------------
    DECODE_FAILURE = "decode_failure"
    PARSE_FAILURE = "parse_failure"
    STRUCTURAL_REJECTION = "structural_rejection"
    SANITY_VIOLATION = "sanity_violation"
    UNROUTED_PARSE_ERROR = "unrouted_parse_error"
    BAD_REQUEST = "bad_request"
    STATION_BINDING_ERROR = "station_binding_error"
    UNEXPECTED_STATUS = "unexpected_status"

    # -- transient (counter, degrade after three) ------------------------
    RATE_LIMITED = "rate_limited"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    NETWORK_FAILURE = "network_failure"

    # -- routine: expected on a healthy system, NO gate action -----------
    NOT_OUR_PRODUCT = "not_our_product"

    # -- classified by the gate itself -----------------------------------
    FORBIDDEN = "forbidden"

    # -- supervision -----------------------------------------------------
    TASK_DEATH = "task_death"


# Only these are network hiccups. Everything else that fails is either an
# integrity alarm or a data-quality defect, and must not share the counter
# that degrades a site after three consecutive misses.
TRANSIENT_OUTCOMES: frozenset[PollOutcome] = frozenset(
    {
        PollOutcome.RATE_LIMITED,
        PollOutcome.SERVER_ERROR,
        PollOutcome.TIMEOUT,
        PollOutcome.NETWORK_FAILURE,
    }
)

# The body, its digest, the channel that carried them, or the durable record
# they were written to cannot be trusted. Never overlaps TRANSIENT_OUTCOMES:
# "retry me" and "someone may be tampering with a settlement feed" are
# different events and must never share a gate action.
INTEGRITY_ALARM_OUTCOMES: frozenset[PollOutcome] = frozenset(
    {
        PollOutcome.REDIRECT,
        PollOutcome.CONTENT_ENCODING,
        PollOutcome.DISALLOWED_HOST,
        PollOutcome.OVERSIZE_BODY,
        PollOutcome.PROXY_ENVIRONMENT,
        PollOutcome.UNROUTED_TRANSPORT_ERROR,
        PollOutcome.TRANSPORT_CONTRACT_VIOLATION,
        PollOutcome.CACHE_VALIDATOR,
        PollOutcome.WRITE_INTEGRITY_VIOLATION,
        PollOutcome.CATALOG_PATH_DEFECT,
        PollOutcome.NON_MONOTONIC_WRITE,
        PollOutcome.WRITER_LOCK_FAILURE,
        PollOutcome.CONCURRENT_WRITER,
        PollOutcome.CATALOG_WRITE_GROUPING_DRIFT,
        PollOutcome.WRITER_LOCK_FILESYSTEM,
        PollOutcome.UNROUTED_CATALOG_ERROR,
    }
)


# ---------------------------------------------------------------------------
# The decision
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutcomeSpec:
    """The fixed part of a routing row: everything derivable from the outcome
    alone, with no reference to the specific exception or response.
    """

    action: GateAction | None
    severity: Severity
    hard_blocks_site: bool
    proceed: bool = False
    writes_record: bool = False
    action_is_deferred: bool = False
    needs_cross_site_burst_signal: bool = False
    needs_final_window_signal: bool = False


@dataclass(frozen=True, slots=True)
class RouteDecision:
    """One routed poll outcome: what the Actor should do, and how loudly.

    Attributes
    ----------
    outcome
        What happened -- the §5 table row, for logs and metrics.
    action
        The single gate recorder to call. Its `.value` is the method name.

        **`None` means call no recorder at all.** Exactly one outcome uses it
        -- `NOT_OUR_PRODUCT`, a sibling station's product arriving on our poll,
        which is expected on a healthy system. It is typed `GateAction | None`
        rather than signalled by a separate boolean deliberately: under
        `mypy --strict` a caller that does `getattr(gate, d.action.value)`
        fails to type-check until it handles the case, whereas an ignorable
        flag would let a routine product quietly record a gate failure.
    severity
        Severity of the routing event itself (see :class:`Severity`).
    detail
        Audit string for the recorder's `detail=` kwarg. URLs are redacted;
        never carries a credential or a raw query string.
    proceed
        Whether the poll sequence continues after handling this decision.
        True only for `FETCHED` (continue to allowlist/parse/persist) and
        `PERSISTED` (continue to publish, §6 step 9).
    writes_record
        Whether a provenance record -- catalog record *and*
        `product_uuid -> raw_sha256` digest-index entry -- results from this
        outcome. **False for 304**, which is the point: a no-op success must
        never be handled by anything that assumes a record exists.
    action_is_deferred
        True only for `FETCHED`. `record_successful_poll` is §6 **step 8**,
        gated behind `WriteOutcome.is_complete` -- calling it on the fetch
        would open the gate over data that has not been persisted or verified.
        Route the later `WriteOutcome` through :func:`route_write_outcome` to
        redeem it.
    retry_after
        The server's `Retry-After`, when it sent one. Carried, never
        interpreted: backoff timing is the Actor's.
    needs_cross_site_burst_signal
        The recorder accepts the Actor's `cross_site_burst_detected=` keyword
        (403 only). The gate classifies UA-trap vs abuse itself, and now
        derives ITS OWN cross-site burst signal from durably persisted
        per-site state -- this flag names the SUPPLEMENTARY, transitional
        signal from the Actor-owned in-memory `CrossSite403Window`, kept as
        a belt-and-suspenders arm so it can only ever add an extra halt,
        never remove one, relative to the gate's own persisted-state
        derivation. `SettlementGate.record_forbidden_403`'s signature is
        unchanged by that derivation -- `cross_site_burst_detected=` is
        still exactly the keyword this flag tells the Actor to pass.
    needs_final_window_signal
        The recorder needs the Actor's `final_window_elapsed=` argument. The
        retry/backoff window belongs to the caller, as it does for the
        conflict window elsewhere in the gate.
    """

    outcome: PollOutcome
    action: GateAction | None
    severity: Severity
    detail: str
    proceed: bool
    writes_record: bool
    action_is_deferred: bool
    hard_blocks_site: bool
    retry_after: str | None = None
    needs_cross_site_burst_signal: bool = False
    needs_final_window_signal: bool = False

    @property
    def is_transient(self) -> bool:
        """Whether this is a network hiccup eligible for the transient counter."""
        return self.outcome in TRANSIENT_OUTCOMES

    @property
    def is_integrity_alarm(self) -> bool:
        """Whether the datum, its digest, or its channel cannot be trusted."""
        return self.outcome in INTEGRITY_ALARM_OUTCOMES


class WriteOutcomeLike(Protocol):
    """Structural view of `persistence.catalog.WriteOutcome`.

    Bound structurally rather than by import so this module stays free of
    `nautilus_trader` and `pyarrow`, keeping the whole table testable in a
    process that has neither loaded. A contract test asserts the real type
    satisfies it.
    """

    @property
    def is_complete(self) -> bool: ...

    @property
    def written(self) -> tuple[object, ...]: ...

    @property
    def skipped(self) -> tuple[object, ...]: ...

    @property
    def path(self) -> str: ...


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------

_SUCCESS = Severity.INFO
_WARN = Severity.WARNING
_CRIT = Severity.CRIT

_INTEGRITY = OutcomeSpec(
    action=GateAction.RECORD_TRANSPORT_INTEGRITY_ALARM,
    severity=_CRIT,
    hard_blocks_site=True,
)
_DATA_QUALITY_PARSE = OutcomeSpec(
    action=GateAction.RECORD_PARSER_FAILURE,
    severity=_CRIT,
    hard_blocks_site=True,
)
_CLIENT_DEFECT = OutcomeSpec(
    action=GateAction.RECORD_CLIENT_ERROR_DEFECT,
    severity=_CRIT,
    hard_blocks_site=True,
)
# The gate already carries an exact recorder for "the body was refused
# before we parsed it" -- shared by the 128 KiB transport cap and normalize's
# line-count/length caps. Both derive BLOCKED + CRIT, so safety is identical
# to the generic transport alarm; the reason code is what an operator reads.
_PRE_PARSE_REJECTION = OutcomeSpec(
    action=GateAction.RECORD_OVERSIZE_OR_PARSE_TIMEOUT,
    severity=_CRIT,
    hard_blocks_site=True,
)
_WRITE_INTEGRITY = OutcomeSpec(
    action=GateAction.RECORD_WRITE_INTEGRITY_VIOLATION,
    severity=_CRIT,
    hard_blocks_site=True,
)
_TRANSIENT = OutcomeSpec(
    action=GateAction.RECORD_TRANSIENT_FAILURE,
    severity=_WARN,
    hard_blocks_site=False,
    needs_final_window_signal=True,
)

_OUTCOME_SPECS: dict[PollOutcome, OutcomeSpec] = {
    # -- success --------------------------------------------------------
    PollOutcome.FETCHED: OutcomeSpec(
        action=GateAction.RECORD_SUCCESSFUL_POLL,
        severity=_SUCCESS,
        hard_blocks_site=False,
        proceed=True,
        writes_record=True,
        action_is_deferred=True,
    ),
    PollOutcome.NOT_MODIFIED: OutcomeSpec(
        action=GateAction.RECORD_SUCCESSFUL_POLL,
        severity=_SUCCESS,
        hard_blocks_site=False,
        # Terminal, and deliberately record-less: freshness is satisfied, but
        # a 304 carries no body, so there is nothing to parse, persist,
        # digest or publish.
        proceed=False,
        writes_record=False,
    ),
    PollOutcome.PERSISTED: OutcomeSpec(
        action=GateAction.RECORD_SUCCESSFUL_POLL,
        severity=_SUCCESS,
        hard_blocks_site=False,
        proceed=True,
        writes_record=True,
    ),
    # -- integrity alarms ------------------------------------------------
    PollOutcome.REDIRECT: OutcomeSpec(
        action=GateAction.RECORD_REDIRECT_INTEGRITY_ALARM,
        severity=_CRIT,
        hard_blocks_site=True,
    ),
    PollOutcome.CONTENT_ENCODING: _INTEGRITY,
    PollOutcome.DISALLOWED_HOST: _INTEGRITY,
    PollOutcome.OVERSIZE_BODY: _PRE_PARSE_REJECTION,
    PollOutcome.PROXY_ENVIRONMENT: _INTEGRITY,
    PollOutcome.UNROUTED_TRANSPORT_ERROR: _INTEGRITY,
    PollOutcome.TRANSPORT_CONTRACT_VIOLATION: _INTEGRITY,
    PollOutcome.CACHE_VALIDATOR: _INTEGRITY,
    PollOutcome.WRITE_INTEGRITY_VIOLATION: _WRITE_INTEGRITY,
    # -- catalog write path ----------------------------------------------
    PollOutcome.CATALOG_PATH_DEFECT: _WRITE_INTEGRITY,
    PollOutcome.NON_MONOTONIC_WRITE: _WRITE_INTEGRITY,
    PollOutcome.WRITER_LOCK_FAILURE: _WRITE_INTEGRITY,
    PollOutcome.CONCURRENT_WRITER: _WRITE_INTEGRITY,
    PollOutcome.CATALOG_WRITE_GROUPING_DRIFT: _WRITE_INTEGRITY,
    PollOutcome.WRITER_LOCK_FILESYSTEM: _WRITE_INTEGRITY,
    PollOutcome.UNROUTED_CATALOG_ERROR: _WRITE_INTEGRITY,
    # -- data quality ----------------------------------------------------
    PollOutcome.DECODE_FAILURE: _DATA_QUALITY_PARSE,
    PollOutcome.PARSE_FAILURE: _DATA_QUALITY_PARSE,
    PollOutcome.UNROUTED_PARSE_ERROR: _DATA_QUALITY_PARSE,
    PollOutcome.STRUCTURAL_REJECTION: _PRE_PARSE_REJECTION,
    PollOutcome.SANITY_VIOLATION: OutcomeSpec(
        action=GateAction.RECORD_SANITY_VIOLATION,
        severity=_CRIT,
        hard_blocks_site=True,
    ),
    PollOutcome.BAD_REQUEST: _CLIENT_DEFECT,
    PollOutcome.STATION_BINDING_ERROR: _CLIENT_DEFECT,
    PollOutcome.UNEXPECTED_STATUS: _CLIENT_DEFECT,
    # -- transient -------------------------------------------------------
    PollOutcome.RATE_LIMITED: _TRANSIENT,
    PollOutcome.SERVER_ERROR: _TRANSIENT,
    PollOutcome.TIMEOUT: _TRANSIENT,
    PollOutcome.NETWORK_FAILURE: _TRANSIENT,
    # -- routine ----------------------------------------------------------
    PollOutcome.NOT_OUR_PRODUCT: OutcomeSpec(
        # No recorder. Not a block, not a transient tick, not a degrade.
        # Recording anything here manufactures an outage out of normal
        # operation -- and `record_successful_poll` would be worse still,
        # since sibling products would keep this site "fresh" forever and
        # neither the staleness watchdog nor FINAL_CLI_OVERDUE would fire.
        action=None,
        severity=_SUCCESS,
        hard_blocks_site=False,
        proceed=False,
        writes_record=False,
    ),
    # -- classified by the gate ------------------------------------------
    PollOutcome.FORBIDDEN: OutcomeSpec(
        action=GateAction.RECORD_FORBIDDEN_403,
        severity=_CRIT,
        # A UA trap halts every site and an abuse block only degrades one --
        # the gate makes that call from its own persisted history, so routing
        # deliberately asserts neither. CRIT because the safe direction is
        # trap-over-abuse: an unnecessary halt costs trading time, a missed
        # trap costs API access outright.
        hard_blocks_site=False,
        needs_cross_site_burst_signal=True,
    ),
    # -- supervision -----------------------------------------------------
    PollOutcome.TASK_DEATH: OutcomeSpec(
        action=GateAction.RECORD_TASK_DEATH,
        severity=_CRIT,
        hard_blocks_site=True,
    ),
}

OUTCOME_SPECS: MappingProxyType[PollOutcome, OutcomeSpec] = MappingProxyType(_OUTCOME_SPECS)


_TRANSPORT_ERROR_ROUTES: dict[type[TransportError], PollOutcome] = {
    # The base class is raised directly by `http.py` for any other lower-level
    # httpx failure (connection refused/reset, DNS failure). That is a genuine
    # network hiccup, so it is an explicit transient row -- not the fallback.
    TransportError: PollOutcome.NETWORK_FAILURE,
    DisallowedHostError: PollOutcome.DISALLOWED_HOST,
    RedirectError: PollOutcome.REDIRECT,
    OversizeBodyError: PollOutcome.OVERSIZE_BODY,
    DecodeError: PollOutcome.DECODE_FAILURE,
    ForbiddenError: PollOutcome.FORBIDDEN,
    RateLimitedError: PollOutcome.RATE_LIMITED,
    ServerError: PollOutcome.SERVER_ERROR,
    TransportTimeoutError: PollOutcome.TIMEOUT,
    ProxyEnvironmentError: PollOutcome.PROXY_ENVIRONMENT,
    ContentEncodingError: PollOutcome.CONTENT_ENCODING,
    # A conditional-GET validator is remote data we STORED and are echoing
    # back into an outbound request header. Malformed means corrupted
    # persisted state or a server attempting header injection through a value
    # we trusted enough to replay -- so it stops, it does not degrade.
    # Deliberately NOT "drop the validator and retry unconditionally": that
    # looks like graceful degradation while silently converting a possible
    # injection attempt into a successful poll.
    InvalidCacheValidatorError: PollOutcome.CACHE_VALIDATOR,
}

TRANSPORT_ERROR_ROUTES: MappingProxyType[type[TransportError], PollOutcome] = MappingProxyType(
    _TRANSPORT_ERROR_ROUTES
)


# Statuses `http.py` documents as *raising* rather than returning. One of them
# arriving as a plain `FetchResult` means that contract moved, and routing it
# as an ordinary status would silently reopen the F4 hole.
def _is_raise_contract_status(status: int) -> bool:
    if 300 <= status < 400 and status != 304:
        return True
    return status in (403, 429) or status >= 500


# ---------------------------------------------------------------------------
# Routing functions -- pure, total, and free of side effects
# ---------------------------------------------------------------------------


def _decide(outcome: PollOutcome, detail: str, *, retry_after: str | None = None) -> RouteDecision:
    spec = _OUTCOME_SPECS[outcome]
    return RouteDecision(
        outcome=outcome,
        action=spec.action,
        severity=spec.severity,
        detail=detail,
        proceed=spec.proceed,
        writes_record=spec.writes_record,
        action_is_deferred=spec.action_is_deferred,
        hard_blocks_site=spec.hard_blocks_site,
        retry_after=retry_after,
        needs_cross_site_burst_signal=spec.needs_cross_site_burst_signal,
        needs_final_window_signal=spec.needs_final_window_signal,
    )


def _transport_detail(exc: TransportError) -> str:
    """Audit detail for a transport failure, with the extra context each
    required-kwarg subclass carries folded in (redacted where it is a URL).
    """
    base = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, RedirectError):
        location = redact_url(exc.location) if exc.location else "<none>"
        return f"{base} [status={exc.status_code} location={location}]"
    if isinstance(exc, ServerError):
        return f"{base} [status={exc.status_code}]"
    if isinstance(exc, RateLimitedError):
        return f"{base} [retry_after={exc.retry_after or '<none>'}]"
    return base


def route_transport_error(exc: TransportError) -> RouteDecision:
    """Route a `TransportError` raised by `HttpTransport.fetch`.

    Dispatch is on **exact type**. An unrecognised subclass fails closed as a
    CRIT integrity alarm rather than inheriting a parent's route -- because
    the alternative, quietly treating an unknown failure as retryable, is how
    an integrity event gets logged as a network blip. The enumeration contract
    test is what stops such a subclass reaching production at all; this branch
    is the seatbelt behind it.
    """
    outcome = _TRANSPORT_ERROR_ROUTES.get(type(exc))
    if outcome is None:
        return _decide(
            PollOutcome.UNROUTED_TRANSPORT_ERROR,
            f"unrouted TransportError subclass {type(exc).__name__}: {exc}. "
            "Failing closed as an integrity alarm; add an explicit row to "
            "breezy.ingest.routing.TRANSPORT_ERROR_ROUTES.",
        )
    retry_after = exc.retry_after if isinstance(exc, RateLimitedError) else None
    return _decide(outcome, _transport_detail(exc), retry_after=retry_after)


def route_fetch_result(result: FetchResult) -> RouteDecision:
    """Route a `FetchResult` -- i.e. a fetch that raised **nothing**.

    F4: that is not the same as a success. `http.py` raises only for 3xx
    (except 304), 403, 429 and 5xx, so a 400 or a 404 arrives here looking
    entirely ordinary.
    """
    status = result.status_code
    location = redact_url(result.url)
    detail = f"HTTP {status} from {location}"

    if _is_raise_contract_status(status):
        return _decide(
            PollOutcome.TRANSPORT_CONTRACT_VIOLATION,
            f"{detail}: ingest.http promises to raise for this status, so "
            "receiving it as a FetchResult means the transport contract "
            "changed. Failing closed rather than guessing a route.",
            retry_after=result.retry_after,
        )
    if 200 <= status < 300:
        return _decide(PollOutcome.FETCHED, detail, retry_after=result.retry_after)
    if status == 304:
        return _decide(
            PollOutcome.NOT_MODIFIED,
            f"{detail}: not modified -- freshness satisfied, no record written.",
            retry_after=result.retry_after,
        )
    if status == 400:
        return _decide(
            PollOutcome.BAD_REQUEST,
            f"{detail}: malformed request -- a defect on our side, not the origin's.",
            retry_after=result.retry_after,
        )
    if status == 404:
        return _decide(
            PollOutcome.STATION_BINDING_ERROR,
            f"{detail}: the configured CLI location does not exist -- the station "
            "binding is wrong. This is a binding error, never a transient.",
            retry_after=result.retry_after,
        )
    return _decide(
        PollOutcome.UNEXPECTED_STATUS,
        f"{detail}: undocumented status on a settlement endpoint; failing closed.",
        retry_after=result.retry_after,
    )


# Exact-type routes for the three parse categories. The BASE `CliParseError`
# is deliberately absent: it is documented NEVER RAISED DIRECTLY, so it has no
# category of its own and falls to the fail-closed branch below.
#
# `isinstance(exc, CliParseError)` is True for all three, so an isinstance
# check -- or an `except` chain with the base first -- collapses a routine
# sibling-station product into a stop-trading parse failure. That collapse is
# the whole reason this is a table.
_PARSE_ERROR_ROUTES: dict[type[CliParseError], PollOutcome] = {
    CliNotOurProductError: PollOutcome.NOT_OUR_PRODUCT,
    CliStructuralError: PollOutcome.STRUCTURAL_REJECTION,
    CliContentError: PollOutcome.PARSE_FAILURE,
}

PARSE_ERROR_ROUTES: MappingProxyType[type[CliParseError], PollOutcome] = MappingProxyType(
    _PARSE_ERROR_ROUTES
)


def route_parse_failure(exc: CliParseError) -> RouteDecision:
    """Route one of the three parse categories from `normalize.cli_parse`.

    They are NOT interchangeable, and only two of them are failures:

    * `CliNotOurProductError` -- **routine**. One WFO issues several cities'
      CLIs, so a sibling station's product arriving on our poll is expected on
      a healthy system. Short-circuits with **no gate action**: ignore the
      product and carry on. Never receiving *our* product is still caught, by
      the freshness / FINAL_CLI_OVERDUE watchdog that exists for that question.
    * `CliStructuralError` -- **loud**. A body that should never have been
      served to us (empty, oversize, truncated, malformed WMO heading),
      rejected before any expensive regex runs.
    * `CliContentError` -- **CRIT**. Structure passed, content unreadable:
      our own product arrived unusable, including a body header naming another
      station, which is a contradiction inside one product.

    Physically-impossible *values* are not in this hierarchy and never reach
    here -- see :func:`route_sanity_violation`.
    """
    outcome = _PARSE_ERROR_ROUTES.get(type(exc))
    if outcome is None:
        return _decide(
            PollOutcome.UNROUTED_PARSE_ERROR,
            f"unrouted CliParseError subclass {type(exc).__name__}: {exc}. "
            "Failing closed as a parser failure; add an explicit row to "
            "breezy.ingest.routing.PARSE_ERROR_ROUTES. Failing closed is "
            "deliberate: the dangerous direction is a new category silently "
            "inheriting CliNotOurProductError's 'ignore it and carry on'.",
        )
    return _decide(outcome, f"{type(exc).__name__}: {exc}")


def route_sanity_violation(exc: CliSanityError) -> RouteDecision:
    """Route a `CliSanityError` from `normalize.sanity.check_physical_sanity`.

    The producer for `SettlementGate.record_sanity_violation`, which had none.

    Kept as a separate dispatch path rather than a fourth parse category, and
    `CliSanityError` is deliberately not a `CliParseError`, for the same
    reason: the text parsed *correctly*, so recording PARSER_FAILURE would
    name the wrong cause in the audit trail an operator reads. A 250 F maximum
    is a malformed remote product or a parser defect, and it must fail loudly
    rather than settle quietly.

    Both are `ValueError` subclasses, so a never-crash boundary catch still
    catches both -- that is a safety net, not a route.
    """
    return _decide(PollOutcome.SANITY_VIOLATION, f"{type(exc).__name__}: {exc}")


def route_write_outcome(outcome: WriteOutcomeLike) -> RouteDecision:
    """Route the `WriteOutcome` from `persistence.catalog.write_records`.

    A complete write redeems the deferred `record_successful_poll` from the
    fetch (§6 step 8). A non-empty `skipped` -- **including the partial case
    where one record wrote and one did not** -- is an integrity violation, not
    a partial success: the catalog silently skips a same-range rewrite, so a
    skip means this poll's data collided with data already on disk.
    """
    if outcome.is_complete:
        return _decide(
            PollOutcome.PERSISTED,
            f"wrote {len(outcome.written)} record(s) to {outcome.path}",
        )
    return _decide(
        PollOutcome.WRITE_INTEGRITY_VIOLATION,
        f"catalog write incomplete at {outcome.path}: "
        f"{len(outcome.written)} written, {len(outcome.skipped)} skipped",
    )


@cache
def catalog_error_routes() -> Mapping[type[BaseException], PollOutcome]:
    """Exact-type routes for `persistence.catalog`'s write-path exceptions.

    Resolved through a **deferred import**, cached after the first call, for
    two reasons that both matter:

    1. `persistence.catalog` imports `nautilus_trader` and `pyarrow` at module
       scope. Importing it here would drag both into every consumer of this
       module and cost the whole transport table its ability to be exercised
       in a process that has loaded neither.
    2. Blast radius. `catalog.py` is a separate, actively-changing seam; a
       module-scope import would make `breezy.ingest.routing` -- and therefore
       every transport route in it -- unimportable whenever that module is
       momentarily broken. A deferred import confines that to callers who
       actually route a catalog error.

    Keys are the real class objects, never names: dispatch is exact-type, and
    string matching on exception names is the failure mode this whole taxonomy
    exists to avoid.
    """
    from breezy.persistence import catalog

    return MappingProxyType(
        {
            # Path components derive only from the registry object and a typed
            # date (brief §8), so a rejected component is a registry defect or
            # a traversal attempt -- never a retryable blip.
            catalog.CatalogPathError: PollOutcome.CATALOG_PATH_DEFECT,
            # `ts_init` is the replay sort key. A backwards write corrupts
            # ordering for every future backtest read of this station.
            catalog.NonMonotonicWriteError: PollOutcome.NON_MONOTONIC_WRITE,
            catalog.WriterLockError: PollOutcome.WRITER_LOCK_FAILURE,
            # Listed separately from its parent `WriterLockError` because
            # dispatch is exact-type. It is deliberately NOT transient: there
            # is exactly one Actor per (venue, city), so a second writer on
            # this station's catalog is a deployment defect, and quietly
            # retrying would let two processes race a settlement record.
            catalog.ConcurrentWriterError: PollOutcome.CONCURRENT_WRITER,
            # The skip detector can no longer be trusted -- which means
            # `WriteOutcome.is_complete` can no longer be trusted either.
            catalog.CatalogWriteError: PollOutcome.CATALOG_WRITE_GROUPING_DRIFT,
            catalog.WriterLockFilesystemError: PollOutcome.WRITER_LOCK_FILESYSTEM,
        }
    )


def route_catalog_error(exc: BaseException) -> RouteDecision:
    """Route an exception raised by the `persistence.catalog` write path.

    Complements :func:`route_write_outcome`: `write_records` reports a silent
    skip by *returning* a `WriteOutcome`, but reports these by *raising*. Both
    ends of that split must be covered or a durable-write failure reaches an
    OPEN gate on discipline alone.

    Exact-type dispatch, and an unrecognised exception fails closed as a write
    integrity violation -- the same posture as the transport fallback, for the
    same reason.
    """
    outcome = catalog_error_routes().get(type(exc))
    if outcome is None:
        return _decide(
            PollOutcome.UNROUTED_CATALOG_ERROR,
            f"unrouted catalog write-path error {type(exc).__name__}: {exc}. "
            "Failing closed as a write integrity violation; add an explicit "
            "row to breezy.ingest.routing.catalog_error_routes().",
        )
    return _decide(outcome, f"{type(exc).__name__}: {exc}")


def route_unhandled_exception(exc: BaseException) -> RouteDecision:
    """Route an unhandled exception from the supervised poll task (§4.1).

    The `add_done_callback` supervision path. A poll task that dies silently
    is a gate that stays OPEN over stale data -- exactly what the gate exists
    to prevent -- so this always hard blocks at CRIT.
    """
    return _decide(PollOutcome.TASK_DEATH, f"unhandled {type(exc).__name__}: {exc}")
