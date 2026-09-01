"""Row-by-row tests for the poll-outcome error-routing table.

Every row of `docs/plans/archive/PHASE1_ACTOR_BRIEF.md` §5 gets an explicit test here,
including the three the brief singles out as easy to get wrong:

* **F4** -- a 400 or 404 comes back as a *normal* `FetchResult`, with no
  exception. Routing on "no exception means success" is a live defect, so the
  status-code rows are tested against real `FetchResult` values, not mocks.
* **304** -- freshness is satisfied but no record and no digest exist. Asserted
  directly (`writes_record is False`), because "no-op success" that routes to
  something implying a record is exactly the bug the brief warns about.
* **Integrity vs transient** -- only `RateLimitedError`, `ServerError` and
  `TransportTimeoutError` (plus the bare-`TransportError` network-failure case)
  are transient. Every other transport failure is an integrity alarm that hard
  blocks the site, and each is asserted individually rather than as a group.

These tests never construct a `SettlementGate`: the routing function decides,
it does not act. That purity is what makes the table exhaustively testable.
"""

from __future__ import annotations

import httpx
import pytest

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
)
from breezy.ingest.routing import (
    INTEGRITY_ALARM_OUTCOMES,
    OUTCOME_SPECS,
    TRANSIENT_OUTCOMES,
    GateAction,
    PollOutcome,
    Severity,
    catalog_error_routes,
    route_catalog_error,
    route_fetch_result,
    route_parse_failure,
    route_sanity_violation,
    route_transport_error,
    route_unhandled_exception,
    route_write_outcome,
)
from breezy.normalize.cli_parse import (
    CliContentError,
    CliNotOurProductError,
    CliParseError,
    CliStructuralError,
)
from breezy.normalize.sanity import CliSanityError

_URL = "https://api.weather.gov/products/types/CLI/locations/NYC?limit=1"


# `FetchResult.retrieved_at_ns` is unconditional (present on a 304 too) and
# rejects zero/negative, so the helper stamps a fixed positive instant rather
# than defaulting it.
_RETRIEVED_AT_NS = 1_787_000_000_000_000_000


def _result(status_code: int, *, retry_after: str | None = None) -> FetchResult:
    """Build a `FetchResult` the way `HttpTransport` would for `status_code`."""
    body_bearing = status_code != 304
    return FetchResult(
        text="CLI text" if body_bearing else None,
        sha256="a" * 64 if body_bearing else None,
        status_code=status_code,
        headers=httpx.Headers({}),
        url=_URL,
        retrieved_at_ns=_RETRIEVED_AT_NS,
        retry_after=retry_after,
    )


class _FakeWriteOutcome:
    """Structural stand-in for `persistence.catalog.WriteOutcome`.

    The real type drags in `nautilus_trader` and `pyarrow`; routing is
    deliberately free of both, so the unit tests bind to the same structural
    protocol the production code does. `tests/contract/` proves the real type
    satisfies it.
    """

    def __init__(self, *, written: int, skipped: int, path: str = "/catalog/nyc") -> None:
        self.written = tuple(object() for _ in range(written))
        self.skipped = tuple(object() for _ in range(skipped))
        self.path = path

    @property
    def is_complete(self) -> bool:
        return not self.skipped


# ---------------------------------------------------------------------------
# Transport-error rows (brief §5, rows 1-10)
# ---------------------------------------------------------------------------

_INTEGRITY_ALARMS = [
    pytest.param(
        RedirectError("moved", status_code=301, location="https://evil.example/x?k=v"),
        PollOutcome.REDIRECT,
        GateAction.RECORD_REDIRECT_INTEGRITY_ALARM,
        id="redirect",
    ),
    pytest.param(
        ContentEncodingError("gzip"),
        PollOutcome.CONTENT_ENCODING,
        GateAction.RECORD_TRANSPORT_INTEGRITY_ALARM,
        id="content-encoding",
    ),
    pytest.param(
        DisallowedHostError("not allowlisted"),
        PollOutcome.DISALLOWED_HOST,
        GateAction.RECORD_TRANSPORT_INTEGRITY_ALARM,
        id="disallowed-host",
    ),
    pytest.param(
        OversizeBodyError("too big"),
        PollOutcome.OVERSIZE_BODY,
        GateAction.RECORD_OVERSIZE_OR_PARSE_TIMEOUT,
        id="oversize-body",
    ),
    pytest.param(
        ProxyEnvironmentError("HTTPS_PROXY set"),
        PollOutcome.PROXY_ENVIRONMENT,
        GateAction.RECORD_TRANSPORT_INTEGRITY_ALARM,
        id="proxy-environment",
    ),
    pytest.param(
        InvalidCacheValidatorError("ETag contains CRLF"),
        PollOutcome.CACHE_VALIDATOR,
        GateAction.RECORD_TRANSPORT_INTEGRITY_ALARM,
        id="cache-validator",
    ),
]


@pytest.mark.parametrize(("exc", "outcome", "action"), _INTEGRITY_ALARMS)
def test_integrity_alarms_hard_block_at_crit(
    exc: TransportError, outcome: PollOutcome, action: GateAction
) -> None:
    decision = route_transport_error(exc)

    assert decision.outcome is outcome
    assert decision.action is action
    assert decision.severity is Severity.CRIT
    assert decision.is_integrity_alarm is True
    assert decision.hard_blocks_site is True
    assert decision.is_transient is False
    assert decision.proceed is False
    assert decision.writes_record is False


def test_content_encoding_is_an_integrity_alarm_not_a_transport_hiccup() -> None:
    """The digest would attest to decompressed bytes, not what came off the wire.

    That is a provenance failure, so it must never share the transient
    counter with a 5xx or a timeout.
    """
    decision = route_transport_error(ContentEncodingError("br"))

    assert decision.is_transient is False
    assert decision.is_integrity_alarm is True
    assert decision.action is GateAction.RECORD_TRANSPORT_INTEGRITY_ALARM


def test_redirect_detail_redacts_the_location_header() -> None:
    decision = route_transport_error(
        RedirectError("moved", status_code=302, location="https://evil.example/x?token=SECRET")
    )

    assert "SECRET" not in decision.detail
    assert "REDACTED" in decision.detail
    assert "302" in decision.detail


def test_redirect_without_a_location_header_still_routes() -> None:
    decision = route_transport_error(RedirectError("moved", status_code=307, location=None))

    assert decision.action is GateAction.RECORD_REDIRECT_INTEGRITY_ALARM
    assert "307" in decision.detail


def test_decode_error_is_a_data_quality_block() -> None:
    """A body that is not valid UTF-8 is not a CLI product."""
    decision = route_transport_error(DecodeError("invalid start byte"))

    assert decision.outcome is PollOutcome.DECODE_FAILURE
    assert decision.action is GateAction.RECORD_PARSER_FAILURE
    assert decision.severity is Severity.CRIT
    assert decision.hard_blocks_site is True
    assert decision.is_transient is False


def test_forbidden_routes_to_the_403_recorder_and_asks_for_the_burst_signal() -> None:
    """The gate classifies UA-trap vs abuse itself; the Actor owns the clock."""
    decision = route_transport_error(ForbiddenError("403"))

    assert decision.outcome is PollOutcome.FORBIDDEN
    assert decision.action is GateAction.RECORD_FORBIDDEN_403
    assert decision.needs_cross_site_burst_signal is True
    assert decision.needs_final_window_signal is False
    assert decision.is_transient is False
    assert decision.is_integrity_alarm is False
    # The gate decides whether this halts one site or all of them.
    assert decision.hard_blocks_site is False


_TRANSIENTS = [
    pytest.param(
        RateLimitedError("429", retry_after="120"),
        PollOutcome.RATE_LIMITED,
        id="rate-limited",
    ),
    pytest.param(ServerError("503", status_code=503), PollOutcome.SERVER_ERROR, id="server-error"),
    pytest.param(TransportTimeoutError("read timeout"), PollOutcome.TIMEOUT, id="timeout"),
    pytest.param(TransportError("connection reset"), PollOutcome.NETWORK_FAILURE, id="network"),
]


@pytest.mark.parametrize(("exc", "outcome"), _TRANSIENTS)
def test_transient_failures_increment_the_transient_counter(
    exc: TransportError, outcome: PollOutcome
) -> None:
    decision = route_transport_error(exc)

    assert decision.outcome is outcome
    assert decision.action is GateAction.RECORD_TRANSIENT_FAILURE
    assert decision.severity is Severity.WARNING
    assert decision.is_transient is True
    assert decision.is_integrity_alarm is False
    assert decision.hard_blocks_site is False
    assert decision.needs_final_window_signal is True
    assert decision.proceed is False
    assert decision.writes_record is False


def test_rate_limited_carries_retry_after_for_the_caller_to_honour() -> None:
    decision = route_transport_error(RateLimitedError("429", retry_after="90"))

    assert decision.retry_after == "90"


def test_rate_limited_without_retry_after_carries_none() -> None:
    decision = route_transport_error(RateLimitedError("429", retry_after=None))

    assert decision.retry_after is None


def test_non_rate_limited_errors_carry_no_retry_after() -> None:
    assert route_transport_error(ServerError("500", status_code=500)).retry_after is None


def test_server_error_detail_names_the_status_code() -> None:
    assert "502" in route_transport_error(ServerError("bad gateway", status_code=502)).detail


def test_every_transport_decision_names_the_exception_class() -> None:
    """An operator reading the gate detail must be able to tell which failure
    mode fired without cross-referencing the log line that produced it."""
    decision = route_transport_error(OversizeBodyError("too big"))

    assert "OversizeBodyError" in decision.detail


# ---------------------------------------------------------------------------
# Unrouted transport errors fail CLOSED
# ---------------------------------------------------------------------------


def test_an_unrouted_transport_subclass_fails_closed_as_an_integrity_alarm() -> None:
    """Defence in depth behind the enumeration contract test.

    The contract test is what stops an unrouted subclass being *shipped*; this
    is what stops one that somehow ships from being silently treated as a
    retryable network hiccup.
    """

    class FutureTransportError(TransportError):
        pass

    decision = route_transport_error(FutureTransportError("something new"))

    assert decision.outcome is PollOutcome.UNROUTED_TRANSPORT_ERROR
    assert decision.action is GateAction.RECORD_TRANSPORT_INTEGRITY_ALARM
    assert decision.severity is Severity.CRIT
    assert decision.hard_blocks_site is True
    assert decision.is_transient is False
    assert "FutureTransportError" in decision.detail
    assert "unrouted" in decision.detail.lower()


def test_routes_match_on_exact_type_never_on_inheritance() -> None:
    """A subclass of a *transient* error must not silently inherit "retry me".

    Exact-type dispatch is what makes the fail-closed fallback reachable, and
    therefore what makes the enumeration contract test load-bearing rather
    than decorative.
    """

    class StricterRateLimit(RateLimitedError):
        pass

    decision = route_transport_error(StricterRateLimit("429", retry_after="5"))

    assert decision.outcome is PollOutcome.UNROUTED_TRANSPORT_ERROR
    assert decision.is_transient is False


# ---------------------------------------------------------------------------
# Status-code rows (brief §5 F4) -- these arrive with NO exception
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [200, 201, 299])
def test_2xx_proceeds_to_parse_with_a_deferred_success_action(status: int) -> None:
    decision = route_fetch_result(_result(status))

    assert decision.outcome is PollOutcome.FETCHED
    assert decision.action is GateAction.RECORD_SUCCESSFUL_POLL
    assert decision.severity is Severity.INFO
    assert decision.proceed is True
    assert decision.writes_record is True
    # §6: record_successful_poll is step 8, gated behind WriteOutcome.is_complete.
    assert decision.action_is_deferred is True
    assert decision.hard_blocks_site is False


def test_304_is_a_no_op_success_that_writes_no_record_and_no_digest() -> None:
    decision = route_fetch_result(_result(304))

    assert decision.outcome is PollOutcome.NOT_MODIFIED
    assert decision.action is GateAction.RECORD_SUCCESSFUL_POLL
    assert decision.severity is Severity.INFO
    assert decision.writes_record is False
    assert decision.proceed is False
    assert decision.action_is_deferred is False
    assert decision.hard_blocks_site is False
    assert decision.is_transient is False


def test_400_is_a_client_error_defect_not_a_transient() -> None:
    decision = route_fetch_result(_result(400))

    assert decision.outcome is PollOutcome.BAD_REQUEST
    assert decision.action is GateAction.RECORD_CLIENT_ERROR_DEFECT
    assert decision.severity is Severity.CRIT
    assert decision.hard_blocks_site is True
    assert decision.is_transient is False
    assert decision.writes_record is False


def test_404_on_a_configured_cli_location_is_a_binding_error_not_a_transient() -> None:
    """The station binding is wrong -- retrying cannot fix a bad location."""
    decision = route_fetch_result(_result(404))

    assert decision.outcome is PollOutcome.STATION_BINDING_ERROR
    assert decision.action is GateAction.RECORD_CLIENT_ERROR_DEFECT
    assert decision.severity is Severity.CRIT
    assert decision.hard_blocks_site is True
    assert decision.is_transient is False


@pytest.mark.parametrize("status", [100, 401, 402, 405, 410, 422, 451])
def test_unexpected_statuses_fail_closed(status: int) -> None:
    decision = route_fetch_result(_result(status))

    assert decision.outcome is PollOutcome.UNEXPECTED_STATUS
    assert decision.action is GateAction.RECORD_CLIENT_ERROR_DEFECT
    assert decision.severity is Severity.CRIT
    assert decision.hard_blocks_site is True


@pytest.mark.parametrize("status", [301, 305, 306, 403, 429, 500, 503])
def test_a_status_http_promises_to_raise_on_is_a_transport_contract_violation(
    status: int,
) -> None:
    """`http.py` raises for 3xx (except 304), 403, 429 and 5xx.

    One arriving as a plain `FetchResult` means that contract moved. Routing it
    as an ordinary status would silently re-open the exact hole F4 describes,
    so it fails closed and names the drift instead.
    """
    decision = route_fetch_result(_result(status))

    assert decision.outcome is PollOutcome.TRANSPORT_CONTRACT_VIOLATION
    assert decision.action is GateAction.RECORD_TRANSPORT_INTEGRITY_ALARM
    assert decision.severity is Severity.CRIT
    assert decision.hard_blocks_site is True


def test_fetch_result_detail_redacts_the_query_string() -> None:
    decision = route_fetch_result(_result(404))

    assert "REDACTED" in decision.detail
    assert "limit=1" not in decision.detail
    assert "404" in decision.detail


def test_fetch_result_retry_after_is_carried_through() -> None:
    """A 4xx may still carry Retry-After; the caller decides what to do with it."""
    assert route_fetch_result(_result(400, retry_after="30")).retry_after == "30"


# ---------------------------------------------------------------------------
# Parse, write and supervision rows
# ---------------------------------------------------------------------------


def test_parse_failure_is_a_data_quality_block() -> None:
    decision = route_parse_failure(CliContentError("no TEMPERATURE (F) block found"))

    assert decision.outcome is PollOutcome.PARSE_FAILURE
    assert decision.action is GateAction.RECORD_PARSER_FAILURE
    assert decision.severity is Severity.CRIT
    assert decision.hard_blocks_site is True
    assert decision.is_transient is False
    assert decision.writes_record is False
    assert "TEMPERATURE" in decision.detail


def test_a_complete_write_redeems_the_deferred_success_action() -> None:
    decision = route_write_outcome(_FakeWriteOutcome(written=2, skipped=0))

    assert decision.outcome is PollOutcome.PERSISTED
    assert decision.action is GateAction.RECORD_SUCCESSFUL_POLL
    assert decision.severity is Severity.INFO
    assert decision.action_is_deferred is False
    assert decision.writes_record is True
    # §6 step 9: publish follows.
    assert decision.proceed is True
    assert decision.hard_blocks_site is False


@pytest.mark.parametrize(
    ("written", "skipped"),
    [(0, 2), (1, 1)],
    ids=["fully-skipped", "partial"],
)
def test_a_skipped_or_partial_write_is_an_integrity_violation(written: int, skipped: int) -> None:
    decision = route_write_outcome(_FakeWriteOutcome(written=written, skipped=skipped))

    assert decision.outcome is PollOutcome.WRITE_INTEGRITY_VIOLATION
    assert decision.action is GateAction.RECORD_WRITE_INTEGRITY_VIOLATION
    assert decision.severity is Severity.CRIT
    assert decision.hard_blocks_site is True
    assert decision.proceed is False
    assert decision.writes_record is False
    assert str(skipped) in decision.detail


def test_write_violation_detail_names_the_catalog_path() -> None:
    decision = route_write_outcome(_FakeWriteOutcome(written=1, skipped=1, path="/cat/pm/nyc"))

    assert "/cat/pm/nyc" in decision.detail


def test_unhandled_exception_routes_to_task_death() -> None:
    decision = route_unhandled_exception(ZeroDivisionError("division by zero"))

    assert decision.outcome is PollOutcome.TASK_DEATH
    assert decision.action is GateAction.RECORD_TASK_DEATH
    assert decision.severity is Severity.CRIT
    assert decision.hard_blocks_site is True
    assert decision.proceed is False
    assert "ZeroDivisionError" in decision.detail


# ---------------------------------------------------------------------------
# Decision-object invariants
# ---------------------------------------------------------------------------


def test_the_decision_is_immutable() -> None:
    decision = route_fetch_result(_result(200))

    with pytest.raises((AttributeError, TypeError)):
        decision.action = GateAction.RECORD_TASK_DEATH  # type: ignore[misc]


def test_every_gate_action_value_is_a_settlement_gate_method_name() -> None:
    """`GateAction.value` is the literal recorder name, so an Actor can
    dispatch with `getattr(gate, decision.action.value)`."""
    from breezy.ingest.gate import SettlementGate

    for action in GateAction:
        assert callable(getattr(SettlementGate, action.value))


def test_only_the_documented_outcomes_are_transient() -> None:
    """Pins the brief's "only these are transient" rule as one assertion over
    the whole table, so a future row cannot quietly join the set."""
    assert TRANSIENT_OUTCOMES == frozenset(
        {
            PollOutcome.RATE_LIMITED,
            PollOutcome.SERVER_ERROR,
            PollOutcome.TIMEOUT,
            PollOutcome.NETWORK_FAILURE,
        }
    )


def test_transient_and_integrity_alarm_are_mutually_exclusive() -> None:
    """A network hiccup and an integrity alarm are different events; nothing
    may be filed as both, which is the distinction the whole table exists to
    preserve."""
    assert TRANSIENT_OUTCOMES.isdisjoint(INTEGRITY_ALARM_OUTCOMES)


def test_every_poll_outcome_has_a_spec() -> None:
    """No `PollOutcome` member may exist without a routing spec -- an outcome
    with no spec would raise `KeyError` deep inside a live poll."""
    for outcome in PollOutcome:
        assert outcome in OUTCOME_SPECS


# ---------------------------------------------------------------------------
# Conditional-GET validator (brief §6 step 2 -- If-None-Match / If-Modified-Since)
# ---------------------------------------------------------------------------


def test_an_invalid_cache_validator_hard_blocks_rather_than_degrading() -> None:
    """A stored `ETag` is remote-supplied data we echo back into a request.

    Malformed means one of two things -- corrupted persisted state, or a
    server attempting header injection through a value we trusted enough to
    replay. Both deserve a stop.
    """
    decision = route_transport_error(InvalidCacheValidatorError("ETag contains CRLF"))

    assert decision.outcome is PollOutcome.CACHE_VALIDATOR
    assert decision.action is GateAction.RECORD_TRANSPORT_INTEGRITY_ALARM
    assert decision.severity is Severity.CRIT
    assert decision.is_integrity_alarm is True
    assert decision.is_transient is False
    assert decision.hard_blocks_site is True


def test_an_invalid_cache_validator_never_becomes_a_retry_without_the_validator() -> None:
    """The tempting "graceful degradation" -- drop the validator, retry
    unconditionally -- silently converts a possible header-injection attempt
    into a successful poll. That is precisely the quiet failure this table
    exists to eliminate, so it is asserted against directly.
    """
    decision = route_transport_error(InvalidCacheValidatorError("ETag has a control char"))

    assert decision.action is not GateAction.RECORD_SUCCESSFUL_POLL
    assert decision.action is not GateAction.RECORD_TRANSIENT_FAILURE
    assert decision.proceed is False
    assert decision.writes_record is False
    assert decision.needs_final_window_signal is False


# ---------------------------------------------------------------------------
# Catalog write-path errors (brief §6 steps 6-7)
# ---------------------------------------------------------------------------


def test_every_catalog_write_error_hard_blocks_at_crit() -> None:
    from breezy.persistence import catalog

    cases: list[tuple[BaseException, PollOutcome]] = [
        (catalog.CatalogPathError("bad component"), PollOutcome.CATALOG_PATH_DEFECT),
        (catalog.NonMonotonicWriteError("ts_init went backwards"), PollOutcome.NON_MONOTONIC_WRITE),
        (catalog.WriterLockError("could not lock"), PollOutcome.WRITER_LOCK_FAILURE),
        (catalog.ConcurrentWriterError("another writer holds it"), PollOutcome.CONCURRENT_WRITER),
        (catalog.CatalogWriteError("grouping changed"), PollOutcome.CATALOG_WRITE_GROUPING_DRIFT),
        (catalog.WriterLockFilesystemError("nfs"), PollOutcome.WRITER_LOCK_FILESYSTEM),
    ]

    for exc, expected in cases:
        decision = route_catalog_error(exc)

        assert decision.outcome is expected, type(exc).__name__
        assert decision.action is GateAction.RECORD_WRITE_INTEGRITY_VIOLATION
        assert decision.severity is Severity.CRIT
        assert decision.hard_blocks_site is True
        assert decision.is_transient is False
        assert decision.proceed is False
        assert decision.writes_record is False
        assert type(exc).__name__ in decision.detail


def test_a_concurrent_writer_is_routed_distinctly_from_its_parent_lock_error() -> None:
    """`ConcurrentWriterError` subclasses `WriterLockError`, so this is the
    catalog-side proof that dispatch is exact-type and not `isinstance`:
    an `isinstance` chain would collapse the child into the parent's row and
    lose "another process is writing this station" as a distinct diagnosis.
    """
    from breezy.persistence import catalog

    assert issubclass(catalog.ConcurrentWriterError, catalog.WriterLockError)

    child = route_catalog_error(catalog.ConcurrentWriterError("busy"))
    parent = route_catalog_error(catalog.WriterLockError("busy"))

    assert child.outcome is PollOutcome.CONCURRENT_WRITER
    assert parent.outcome is PollOutcome.WRITER_LOCK_FAILURE
    assert child.outcome is not parent.outcome  # type: ignore[comparison-overlap]  # tautological given the preceding `is` assert; kept as explicit documentation that the two enum members are mutually exclusive


def test_an_unrouted_catalog_error_fails_closed() -> None:
    class FutureCatalogError(RuntimeError):
        pass

    decision = route_catalog_error(FutureCatalogError("something new"))

    assert decision.outcome is PollOutcome.UNROUTED_CATALOG_ERROR
    assert decision.action is GateAction.RECORD_WRITE_INTEGRITY_VIOLATION
    assert decision.severity is Severity.CRIT
    assert decision.hard_blocks_site is True
    assert "FutureCatalogError" in decision.detail
    assert "unrouted" in decision.detail.lower()


def test_catalog_error_routes_is_stable_across_calls() -> None:
    """The table is resolved lazily (a deferred import) but must not be
    rebuilt per call -- a fresh mapping each time would make identity-based
    reasoning and the contract test's enumeration subtly unstable."""
    assert catalog_error_routes() is catalog_error_routes()


# ---------------------------------------------------------------------------
# The three parse categories (normalize/cli_parse) -- one routine, two blocking
# ---------------------------------------------------------------------------


def test_a_sibling_station_product_is_routine_and_calls_no_gate_recorder() -> None:
    """One WFO issues several cities' CLIs -- KOKX issues NYC + JFK + LGA + EWR.

    A `CLIJFK` arriving on the NYC poll is EXPECTED on a healthy system. It is
    the one outcome in the whole table with no gate action at all: recording
    anything here manufactures an outage out of normal operation, and because
    a hard block clears only on a successful poll, it would be sticky.
    """
    decision = route_parse_failure(CliNotOurProductError("AWIPS PIL CLIJFK is not CLINYC"))

    assert decision.outcome is PollOutcome.NOT_OUR_PRODUCT
    assert decision.action is None
    assert decision.severity is Severity.INFO
    assert decision.hard_blocks_site is False
    assert decision.is_transient is False
    assert decision.is_integrity_alarm is False
    assert decision.writes_record is False
    assert decision.proceed is False


def test_a_sibling_station_product_must_not_record_a_successful_poll() -> None:
    """Routing this to `record_successful_poll` would be worse than blocking.

    Freshness is measured from the last successful poll, so sibling products
    would keep NYC "fresh" forever and the staleness watchdog -- plus
    FINAL_CLI_OVERDUE, the control actually designed for "our product never
    arrived" -- would never fire. `action is None` is what prevents that.
    """
    decision = route_parse_failure(CliNotOurProductError("CLM monthly summary, not CLI"))

    assert decision.action is not GateAction.RECORD_SUCCESSFUL_POLL
    assert decision.action is not GateAction.RECORD_TRANSIENT_FAILURE
    assert decision.action is not GateAction.RECORD_PARSER_FAILURE
    assert decision.action is None


def test_a_structural_rejection_blocks_with_the_pre_parse_reason_code() -> None:
    """A body that should never have been served to us: empty, oversize,
    truncated, or carrying a malformed WMO heading. Rejected before any
    expensive regex runs (brief §6 step 3), which is exactly what the gate's
    `record_oversize_or_parse_timeout` reason describes.
    """
    decision = route_parse_failure(CliStructuralError("WMO heading does not match its shape"))

    assert decision.outcome is PollOutcome.STRUCTURAL_REJECTION
    assert decision.action is GateAction.RECORD_OVERSIZE_OR_PARSE_TIMEOUT
    assert decision.severity is Severity.CRIT
    assert decision.hard_blocks_site is True
    assert decision.is_transient is False


def test_structural_and_content_failures_get_distinct_reason_codes() -> None:
    """"Should never have been served to us" and "our product arrived
    unreadable" are different operator questions at 07:30."""
    structural = route_parse_failure(CliStructuralError("body too short for a WMO header"))
    content = route_parse_failure(CliContentError("unrecognized temperature token"))

    assert structural.outcome is not content.outcome
    assert structural.action is not content.action
    assert content.action is GateAction.RECORD_PARSER_FAILURE
    assert structural.hard_blocks_site is True
    assert content.hard_blocks_site is True


def test_parse_dispatch_is_exact_type_never_isinstance() -> None:
    """All three satisfy `isinstance(exc, CliParseError)`.

    An `isinstance` check against the base -- or an `except` chain with the
    base first -- silently collapses a routine sibling product into a
    stop-trading parse failure. Three inputs, three different outcomes, is the
    assertion that pins it.
    """
    categories = (CliNotOurProductError, CliStructuralError, CliContentError)
    for cls in categories:
        assert isinstance(cls("x"), CliParseError)

    outcomes = {route_parse_failure(cls("x")).outcome for cls in categories}

    assert len(outcomes) == 3


def test_the_bare_parse_base_fails_closed() -> None:
    """`CliParseError` is documented NEVER RAISED DIRECTLY, so it gets no
    route. If one ever appears it is an unclassified parse failure, and the
    safe reading of "I cannot categorise this" is to stop, not to shrug.
    """
    decision = route_parse_failure(CliParseError("raised directly, somehow"))

    assert decision.outcome is PollOutcome.UNROUTED_PARSE_ERROR
    assert decision.action is GateAction.RECORD_PARSER_FAILURE
    assert decision.severity is Severity.CRIT
    assert decision.hard_blocks_site is True
    assert "unrouted" in decision.detail.lower()


def test_a_future_parse_subclass_fails_closed_rather_than_being_treated_as_routine() -> None:
    """The dangerous direction is a new subclass silently inheriting
    `CliNotOurProductError`'s "ignore it and carry on"."""

    class CliFutureError(CliParseError):
        pass

    decision = route_parse_failure(CliFutureError("something new"))

    assert decision.outcome is PollOutcome.UNROUTED_PARSE_ERROR
    assert decision.action is not None
    assert decision.hard_blocks_site is True
    assert "CliFutureError" in decision.detail


# ---------------------------------------------------------------------------
# Sanity violations (normalize/sanity) -- deliberately outside the parse tree
# ---------------------------------------------------------------------------


def test_a_sanity_violation_routes_to_the_gates_dedicated_recorder() -> None:
    """`record_sanity_violation` has existed on the gate with no producer.

    This is it. A CLI reporting a 250 F maximum parsed perfectly -- so
    recording PARSER_FAILURE would name the wrong cause in the audit trail.
    """
    decision = route_sanity_violation(CliSanityError("MAXIMUM 250 F exceeds 140 F envelope"))

    assert decision.outcome is PollOutcome.SANITY_VIOLATION
    assert decision.action is GateAction.RECORD_SANITY_VIOLATION
    assert decision.severity is Severity.CRIT
    assert decision.hard_blocks_site is True
    assert decision.is_transient is False
    assert decision.proceed is False
    assert decision.writes_record is False
    assert "250" in decision.detail


def test_a_sanity_violation_is_not_reachable_through_parse_routing() -> None:
    """`CliSanityError` is deliberately NOT a `CliParseError`, so
    `route_parse_failure` structurally cannot record PARSER_FAILURE for it.
    Kept as two dispatch paths, never folded into one.
    """
    assert not issubclass(CliSanityError, CliParseError)

    parse_outcomes = {
        route_parse_failure(cls("x")).outcome
        for cls in (CliNotOurProductError, CliStructuralError, CliContentError, CliParseError)
    }

    assert PollOutcome.SANITY_VIOLATION not in parse_outcomes


def test_sanity_and_parse_failures_carry_different_gate_actions() -> None:
    sanity = route_sanity_violation(CliSanityError("min above max"))
    content = route_parse_failure(CliContentError("bad token"))

    assert sanity.action is not content.action


# ---------------------------------------------------------------------------
# Ruling: the gate's exact recorder beats the generic transport alarm
# ---------------------------------------------------------------------------


def test_oversize_body_uses_the_gates_dedicated_recorder_not_the_generic_alarm() -> None:
    """Both derive BLOCKED + CRIT so safety is identical -- but the reason
    code is what an operator reads at 07:30, and the gate already has an exact
    recorder for a body rejected before parse."""
    decision = route_transport_error(OversizeBodyError("exceeded the 128 KiB cap"))

    assert decision.action is GateAction.RECORD_OVERSIZE_OR_PARSE_TIMEOUT
    assert decision.action is not GateAction.RECORD_TRANSPORT_INTEGRITY_ALARM  # type: ignore[comparison-overlap]  # tautological given the preceding `is` assert; kept as explicit documentation that the two enum members are mutually exclusive
    # Still not a transport hiccup.
    assert decision.is_integrity_alarm is True
    assert decision.is_transient is False
    assert decision.hard_blocks_site is True


def test_the_pre_parse_rejection_recorder_is_shared_by_both_size_guards() -> None:
    """The 128 KiB transport cap and the normalize line-count/length caps are
    the same operator question -- "the body was refused before we parsed it" --
    so they share a recorder while keeping distinct outcomes for diagnosis."""
    transport = route_transport_error(OversizeBodyError("128 KiB cap"))
    structural = route_parse_failure(CliStructuralError("oversize line count"))

    assert transport.action is structural.action
    assert transport.outcome is not structural.outcome
