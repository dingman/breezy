"""Contract: every `TransportError` subclass has an explicit route.

This file exists for one reason, and it is not to check today's table. It is
to **fail loudly when a future `TransportError` subclass is added without a
route**, because an unrouted transport error silently degrades into generic
task-death supervision -- which erases the distinction between a network
hiccup (retry, degrade after three) and an integrity alarm (hard block, CRIT,
someone is tampering with a settlement feed). Those two must never share a
gate action, and the only durable way to guarantee that is to enumerate the
taxonomy rather than trust a reviewer to notice.

Two traps this file is written around, both hit for real before:

* `RedirectError`, `RateLimitedError` and `ServerError` take **required
  keyword arguments**. A naive `cls()` construction raises `TypeError`, the
  test goes red for an unrelated reason, and the next person "fixes" it by
  weakening the enumeration. Construction is therefore an explicit per-class
  table, and a new subclass missing from *it* fails just as loudly as one
  missing from the routes.
* `__subclasses__()` is one level deep. Any subclass with its own subclasses
  would be invisible, so the walk recurses.

Test-local subclasses (this suite defines a couple deliberately) are excluded
by module, so the contract measures `breezy`'s taxonomy and not pytest's
import order -- which `pytest-randomly` varies run to run.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping

import pytest

from breezy.ingest import http as http_module
from breezy.ingest.http import (
    ContentEncodingError,
    DecodeError,
    DisallowedHostError,
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
    TRANSPORT_ERROR_ROUTES,
    GateAction,
    PollOutcome,
    route_transport_error,
)

pytestmark = pytest.mark.contract


# Explicit construction table. Required-kwarg classes are the whole reason this
# is a table and not `cls("x")` in a loop.
TRANSPORT_ERROR_CONSTRUCTORS: Mapping[type[TransportError], Callable[[], TransportError]] = {
    TransportError: lambda: TransportError("generic transport failure"),
    DisallowedHostError: lambda: DisallowedHostError("host not in allowlist"),
    RedirectError: lambda: RedirectError(
        "redirect", status_code=301, location="https://example.invalid/"
    ),
    OversizeBodyError: lambda: OversizeBodyError("body exceeded cap"),
    DecodeError: lambda: DecodeError("not valid utf-8"),
    ForbiddenError: lambda: ForbiddenError("403 forbidden"),
    RateLimitedError: lambda: RateLimitedError("429 too many requests", retry_after="60"),
    ServerError: lambda: ServerError("503 service unavailable", status_code=503),
    TransportTimeoutError: lambda: TransportTimeoutError("read timeout"),
    ProxyEnvironmentError: lambda: ProxyEnvironmentError("HTTPS_PROXY is set"),
    ContentEncodingError: lambda: ContentEncodingError("content-encoding: gzip"),
    InvalidCacheValidatorError: lambda: InvalidCacheValidatorError(
        "stored ETag contains a CR/LF"
    ),
}

_UNROUTED_CONSEQUENCE = (
    "An unrouted transport error silently degrades into generic task-death "
    "supervision, losing the distinction between a network hiccup (transient: "
    "retry, degrade after three) and an integrity alarm (CRIT, hard block). "
    "At runtime this class will fail closed -- routed to a CRIT transport "
    "integrity alarm that hard blocks the site -- because 'I do not recognise "
    "this error' is not evidence that it is benign. Failing closed is a "
    "seatbelt, not a route: add an explicit row to "
    "breezy.ingest.routing.TRANSPORT_ERROR_ROUTES and give it a deliberate "
    "route, transient or integrity."
)


def _all_subclasses(root: type[TransportError]) -> set[type[TransportError]]:
    """Every transitive subclass of `root`.

    `__subclasses__()` returns only direct children, so a two-level hierarchy
    would hide a class from a naive enumeration. Recursion is not speculative
    generality here: it is the difference between this test doing its job and
    appearing to.
    """
    found: set[type[TransportError]] = set()
    for child in root.__subclasses__():
        found.add(child)
        found |= _all_subclasses(child)
    return found


def breezy_transport_error_taxonomy() -> set[type[TransportError]]:
    """The `TransportError` hierarchy as defined by `breezy`, base included.

    Filtered to `breezy.*` modules so subclasses defined inside this test suite
    (for fail-closed and exact-dispatch coverage) cannot pollute the contract.
    """
    return {TransportError} | {
        cls for cls in _all_subclasses(TransportError) if cls.__module__.startswith("breezy.")
    }


def unrouted(
    taxonomy: set[type[TransportError]], routes: Mapping[type[TransportError], PollOutcome]
) -> list[str]:
    """Names of taxonomy members with no explicit route, sorted."""
    return sorted(cls.__name__ for cls in taxonomy if cls not in routes)


def failure_message(missing: list[str]) -> str:
    return (
        f"Unrouted TransportError subclass(es): {', '.join(missing)}. "
        + _UNROUTED_CONSEQUENCE
    )


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


def test_every_transport_error_subclass_has_an_explicit_route() -> None:
    taxonomy = breezy_transport_error_taxonomy()
    missing = unrouted(taxonomy, TRANSPORT_ERROR_ROUTES)

    assert not missing, failure_message(missing)


def test_every_transport_error_subclass_has_a_construction_recipe() -> None:
    """The construction table must track the taxonomy too.

    Otherwise a new required-kwarg subclass makes the routing test above
    unrunnable rather than red, and the failure gets misread as a broken test.
    """
    taxonomy = breezy_transport_error_taxonomy()
    missing = sorted(
        cls.__name__ for cls in taxonomy if cls not in TRANSPORT_ERROR_CONSTRUCTORS
    )

    assert not missing, (
        f"No construction recipe for: {', '.join(missing)}. Add one to "
        "TRANSPORT_ERROR_CONSTRUCTORS -- note that RedirectError, RateLimitedError "
        "and ServerError take required keyword arguments, so `cls()` will not do."
    )


def test_the_taxonomy_walk_actually_finds_the_hierarchy() -> None:
    """Guards the `breezy.*` filter itself.

    A filter that matched nothing would make both tests above pass vacuously,
    which is the quietest possible way for this contract to stop working.
    """
    taxonomy = breezy_transport_error_taxonomy()

    assert len(taxonomy) >= 12
    assert TransportError in taxonomy
    assert ContentEncodingError in taxonomy
    assert all(cls.__module__ == http_module.__name__ for cls in taxonomy)


def test_every_routed_exception_actually_routes_when_constructed() -> None:
    """End-to-end over the taxonomy: construct each one and route it.

    Proves the table is reachable, not merely present -- and that no route
    raises on a real instance of the class it claims to handle.
    """
    for cls in sorted(breezy_transport_error_taxonomy(), key=lambda c: c.__name__):
        decision = route_transport_error(TRANSPORT_ERROR_CONSTRUCTORS[cls]())

        assert decision.outcome is not PollOutcome.UNROUTED_TRANSPORT_ERROR, (
            f"{cls.__name__} fell through to the fail-closed fallback despite "
            "having a table entry -- routing dispatches on exact type, so the "
            "table key must be the class itself."
        )
        assert decision.outcome is TRANSPORT_ERROR_ROUTES[cls]
        assert isinstance(decision.action, GateAction)


# ---------------------------------------------------------------------------
# Proof the contract fails when a route is removed
# ---------------------------------------------------------------------------


def test_the_enumeration_detects_a_removed_route() -> None:
    """The test above is only worth having if it can fail.

    Feed the same check a table with one row deleted and assert it names the
    class *and* states the consequence -- so the guard is proven live, without
    editing production code.
    """
    taxonomy = breezy_transport_error_taxonomy()
    pruned = {
        cls: outcome
        for cls, outcome in TRANSPORT_ERROR_ROUTES.items()
        if cls is not ContentEncodingError
    }

    missing = unrouted(taxonomy, pruned)

    # Membership, not equality: asserting the exact list would make this
    # proof-of-mechanism re-fail every time the taxonomy legitimately grows,
    # which is the failure mode that tempts people to weaken the enumeration.
    assert "ContentEncodingError" in missing
    message = failure_message(missing)
    assert "ContentEncodingError" in message
    assert "task-death" in message
    assert "integrity alarm" in message


def test_the_enumeration_detects_a_brand_new_unrouted_subclass() -> None:
    """The scenario the contract actually exists for: someone adds a subclass
    to `http.py` and forgets the routing table.

    Two assertions, and the second is the important one.

    (a) The enumeration catches it, and the message names it and says what
        happens.
    (b) At *runtime* it fails closed as an integrity alarm rather than being
        treated as transient.

    (b) is what would catch a future refactor from exact-type lookup to an
        `isinstance` chain. Because the bare `TransportError` base class is
        itself routed as transient, an `isinstance`-ordered chain would make
        every forgotten subclass silently inherit "retry me" -- and this
        contract would keep passing while production quietly retried an
        integrity event as a network blip.
    """

    class HypotheticalTlsPinningError(TransportError):
        pass

    # (a) the enumeration catches it, and says why it matters
    missing = unrouted({HypotheticalTlsPinningError}, TRANSPORT_ERROR_ROUTES)
    assert missing == ["HypotheticalTlsPinningError"]
    message = failure_message(missing)
    assert "HypotheticalTlsPinningError" in message
    assert "fail closed" in message
    assert "deliberate" in message

    # (b) and at runtime it fails closed, never transient
    decision = route_transport_error(HypotheticalTlsPinningError("pin mismatch"))
    assert decision.outcome is PollOutcome.UNROUTED_TRANSPORT_ERROR
    assert decision.is_transient is False
    assert decision.is_integrity_alarm is True
    assert decision.hard_blocks_site is True
    assert decision.action is not GateAction.RECORD_TRANSIENT_FAILURE


def test_the_base_class_is_routed_transient_which_is_why_dispatch_is_exact() -> None:
    """`http.py:357` raises a **bare** `TransportError` for a generic lower-level
    httpx failure (connection refused/reset, DNS failure). That is a base-class
    instance, not a subclass, so `TransportError.__subclasses__()` alone never
    sees it -- hence the taxonomy is `{TransportError} | subclasses`.

    It is a network hiccup, so it belongs on the transient counter. Recording
    that here alongside the exact-dispatch guarantee, because the two rulings
    are only safe together: transient-base plus `isinstance` dispatch would
    make "forgot to route it" mean "retried forever".
    """
    assert TransportError in TRANSPORT_ERROR_ROUTES

    decision = route_transport_error(TransportError("connection reset by peer"))

    assert decision.is_transient is True
    assert decision.is_integrity_alarm is False
    assert decision.action is GateAction.RECORD_TRANSIENT_FAILURE


# ---------------------------------------------------------------------------
# Structural contract with the consumed modules
# ---------------------------------------------------------------------------


def test_the_real_write_outcome_satisfies_the_routing_protocol() -> None:
    """`routing` binds `WriteOutcome` structurally so it stays free of
    `nautilus_trader`. This is the test that keeps that decoupling honest."""
    from breezy.ingest.routing import WriteOutcomeLike, route_write_outcome
    from breezy.persistence.catalog import WriteOutcome

    complete: WriteOutcomeLike = WriteOutcome(written=(), skipped=(), path="/catalog/nyc")
    assert route_write_outcome(complete).outcome is PollOutcome.PERSISTED


# ---------------------------------------------------------------------------
# The same contract for the catalog write-path taxonomy
# ---------------------------------------------------------------------------
#
# `persistence.catalog`'s exceptions have no common root -- they descend from
# ValueError, RuntimeError and Exception separately -- so `__subclasses__()`
# cannot walk them. The taxonomy is therefore "every exception class DEFINED in
# that module", which catches a new one however it is based.


def catalog_error_taxonomy() -> set[type[BaseException]]:
    import inspect

    from breezy.persistence import catalog

    return {
        obj
        for obj in vars(catalog).values()
        if inspect.isclass(obj)
        and issubclass(obj, BaseException)
        and obj.__module__ == catalog.__name__
    }


def test_every_catalog_write_path_exception_has_an_explicit_route() -> None:
    from breezy.ingest.routing import catalog_error_routes

    routes = catalog_error_routes()
    missing = sorted(cls.__name__ for cls in catalog_error_taxonomy() if cls not in routes)

    assert not missing, (
        f"Unrouted catalog write-path exception(s): {', '.join(missing)}. "
        "write_records reports a silent skip by RETURNING a WriteOutcome but "
        "reports these by RAISING; an unrouted one escapes to generic "
        "task-death supervision, so a durable-write failure would reach an "
        "OPEN gate on discipline alone. At runtime it fails closed as a write "
        "integrity violation -- a seatbelt, not a route. Add an explicit row "
        "to breezy.ingest.routing.catalog_error_routes()."
    )


def test_the_catalog_taxonomy_walk_actually_finds_the_hierarchy() -> None:
    """Same vacuity guard as the transport side: a module filter that matched
    nothing would make the contract above pass while checking nothing."""
    from breezy.persistence import catalog

    taxonomy = catalog_error_taxonomy()

    assert len(taxonomy) >= 6
    assert catalog.ConcurrentWriterError in taxonomy
    assert catalog.WriterLockError in taxonomy


def test_the_catalog_enumeration_detects_a_removed_route() -> None:
    from breezy.ingest.routing import catalog_error_routes
    from breezy.persistence import catalog

    pruned = {
        cls: outcome
        for cls, outcome in catalog_error_routes().items()
        if cls is not catalog.ConcurrentWriterError
    }
    missing = sorted(cls.__name__ for cls in catalog_error_taxonomy() if cls not in pruned)

    assert "ConcurrentWriterError" in missing


def test_routing_does_not_import_nautilus_merely_to_be_imported() -> None:
    """The catalog table is resolved through a deferred import.

    `persistence.catalog` pulls in `nautilus_trader` and `pyarrow`, and is a
    separate actively-changing seam. Importing it at `routing` module scope
    would make every transport route in this file unimportable whenever that
    module is momentarily broken -- so the decoupling is checked, not assumed.
    """
    import ast
    import pathlib

    import breezy.ingest.routing as routing_module

    tree = ast.parse(pathlib.Path(routing_module.__file__).read_text())
    module_scope_imports = {
        alias.name if isinstance(node, ast.Import) else (node.module or "")
        for node in tree.body
        if isinstance(node, ast.Import | ast.ImportFrom)
        for alias in node.names
    }

    assert not any(name.startswith("nautilus_trader") for name in module_scope_imports)
    assert not any("persistence" in name for name in module_scope_imports)


# ---------------------------------------------------------------------------
# The parse-category taxonomy (normalize/cli_parse + normalize/sanity)
# ---------------------------------------------------------------------------
#
# Ordered `except` and exact-type dispatch both depend on the SHAPE of this
# hierarchy, not just its membership. If a future edit makes one category an
# ancestor of another, ordered dispatch silently changes meaning while every
# membership test keeps passing -- so the shape is pinned here explicitly.


def test_the_three_parse_categories_are_siblings() -> None:
    """All three must be DIRECT children of `CliParseError`, and none may be
    an ancestor of another.

    If `CliStructuralError` ever became a base of `CliContentError`, an
    ordered `except` chain would route content failures to the structural
    reason code without a single test failing -- and exact-type dispatch would
    still work, so the two strategies would silently disagree.
    """
    from breezy.normalize.cli_parse import (
        CliContentError,
        CliNotOurProductError,
        CliParseError,
        CliStructuralError,
    )

    categories = (CliNotOurProductError, CliStructuralError, CliContentError)

    for cls in categories:
        assert cls.__bases__ == (CliParseError,), (
            f"{cls.__name__} is no longer a direct child of CliParseError. "
            "Ordered `except` dispatch changes meaning when the hierarchy "
            "deepens; re-check breezy.ingest.routing.PARSE_ERROR_ROUTES."
        )

    for a, b in itertools.permutations(categories, 2):
        assert not issubclass(a, b), (
            f"{a.__name__} became a subclass of {b.__name__}. The three parse "
            "categories must stay siblings -- one routine, two blocking."
        )


def test_cli_sanity_error_is_outside_the_parse_hierarchy() -> None:
    """The separation is what stops `route_parse_failure` recording
    PARSER_FAILURE for a physically-impossible value."""
    from breezy.normalize.cli_parse import CliParseError
    from breezy.normalize.sanity import CliSanityError

    assert not issubclass(CliSanityError, CliParseError)
    assert not issubclass(CliParseError, CliSanityError)
    # Both remain ValueError so a never-crash boundary catch still works.
    assert issubclass(CliSanityError, ValueError)
    assert issubclass(CliParseError, ValueError)


def parse_error_taxonomy() -> set[type[BaseException]]:
    """Every `CliParseError` subclass defined in `breezy`, base EXCLUDED.

    The base is documented NEVER RAISED DIRECTLY, so it has no category of its
    own and is deliberately unrouted (see the test below).
    """
    from breezy.normalize.cli_parse import CliParseError

    def walk(root: type[BaseException]) -> set[type[BaseException]]:
        found: set[type[BaseException]] = set()
        for child in root.__subclasses__():
            found.add(child)
            found |= walk(child)
        return found

    return {cls for cls in walk(CliParseError) if cls.__module__.startswith("breezy.")}


def test_every_parse_category_has_an_explicit_route() -> None:
    from breezy.ingest.routing import PARSE_ERROR_ROUTES

    missing = sorted(
        cls.__name__ for cls in parse_error_taxonomy() if cls not in PARSE_ERROR_ROUTES
    )

    assert not missing, (
        f"Unrouted CliParseError subclass(es): {', '.join(missing)}. Because "
        "isinstance(exc, CliParseError) is True for every category, an "
        "unrouted one is indistinguishable from a routine sibling-station "
        "product to any isinstance-based handler -- which would ignore a real "
        "parse failure and keep trading. At runtime it fails closed as a "
        "parser failure; that is a seatbelt, not a route. Add an explicit row "
        "to breezy.ingest.routing.PARSE_ERROR_ROUTES and decide whether it is "
        "routine, structural or content."
    )


def test_the_parse_taxonomy_walk_actually_finds_the_categories() -> None:
    from breezy.normalize.cli_parse import (
        CliContentError,
        CliNotOurProductError,
        CliStructuralError,
    )

    taxonomy = parse_error_taxonomy()

    assert len(taxonomy) >= 3
    assert {CliNotOurProductError, CliStructuralError, CliContentError} <= taxonomy


def test_the_parse_base_is_deliberately_unrouted() -> None:
    """Recorded as a decision, not an oversight: routing the never-raised base
    would give it a category it does not have, and the fail-closed branch is
    the correct handling if one ever appears."""
    from breezy.ingest.routing import PARSE_ERROR_ROUTES, PollOutcome, route_parse_failure
    from breezy.normalize.cli_parse import CliParseError

    assert CliParseError not in PARSE_ERROR_ROUTES
    assert route_parse_failure(CliParseError("x")).outcome is PollOutcome.UNROUTED_PARSE_ERROR


def test_the_parse_enumeration_detects_a_removed_route() -> None:
    from breezy.ingest.routing import PARSE_ERROR_ROUTES
    from breezy.normalize.cli_parse import CliNotOurProductError

    pruned = {
        cls: outcome
        for cls, outcome in PARSE_ERROR_ROUTES.items()
        if cls is not CliNotOurProductError
    }
    missing = sorted(cls.__name__ for cls in parse_error_taxonomy() if cls not in pruned)

    assert "CliNotOurProductError" in missing
