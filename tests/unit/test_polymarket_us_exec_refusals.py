"""R-6d: the transient/durable refusal taxonomy, and what it refuses to read.

Authority: ``docs/plans/EXEC_SPINE_R5_R6_2026-09-02.md`` section R-6d. This
suite is PURE -- nothing here submits, cancels, retries, or contacts a venue.
The module under test classifies; acting on a classification is R-7's
business and is not reachable from here.

WHAT IS PINNED, AND WHY EACH PIN EXISTS
---------------------------------------

* **DURABLE is the DEFAULT, and it is tested AS the default.** The first test
  in this file drives the unrecognised cases -- an unknown status, an
  unrecognised gRPC code, a body that is not an envelope at all, no status at
  all -- and requires DURABLE from every one. A default that only a fallback
  branch reaches is a default nobody has measured; R-4's invariant 1 (the
  refusal latch never self-clears, ``exec/client.py``) is what rides on it.

* **The classifier reads ``code`` and HTTP status, never the human-readable
  text.** The 2026-09-02 capture found the venue's text IDENTICAL across gRPC
  codes 5, 12, 13 and 14 (plan section R-6d), so it carries zero discriminating
  information. ``test_the_classifier_ignores_message_text`` holds the status
  fixed and varies only the code -- a classifier that substring-matched the
  text would answer the same for both and fail -- and holds the code fixed
  while varying the text, which the same mutant also fails.

* **The envelope may not be assumed on the auth path.** The measured 401 body
  is 33 bytes and is not JSON. A parser that assumed ``google.rpc.Status``
  would raise on exactly the credential path, during boot, where it reads as a
  venue outage rather than a rejected signature.

* **12 UNIMPLEMENTED is permanent and vetoes the status.** Retrying a route the
  venue has not implemented is pure waste, so the code wins over an otherwise
  transient 5xx.

WHAT IS DELIBERATELY ABSENT
---------------------------

Timeout-driven classification. ``NautilusHttpTransport.get`` collapses
``HttpError`` and ``HttpTimeoutError`` into one ``VenueTransportError``
``from None`` (``transport.py``), so a timeout arrives carrying NO status and
NO body -- it takes the DURABLE default here, which is the safe direction, and
it is classified properly at R-6.5 where the write path's distinct error types
exist. ``test_a_timeout_is_not_classified_transient`` pins that.

EVIDENCE PROVENANCE, stated because it is not uniform
-----------------------------------------------------

The status/code pairs are MEASURED -- the 2026-09-02 boot capture, tabulated
in the plan at section R-5R. The 429 row is DOCUMENTED, not measured: the
venue's own rate-limit page
(``docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_rate-limits_2026-08-25.md:9,27``)
states the status and shows a body that is NOT a ``google.rpc.Status`` at all.
The 401 body's LENGTH and non-JSON-ness are measured; its bytes are not
recorded anywhere, so the fixture below is synthetic at that one point and
says so.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Final

import pytest

from breezy.adapters.polymarket_us.exec.refusals import (
    ClassifiedRefusal,
    RefusalClass,
    classify_venue_refusal,
    grpc_status_code,
    refusals_after_successful_reconcile,
)

REFUSALS_SOURCE: Final[Path] = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "breezy"
    / "adapters"
    / "polymarket_us"
    / "exec"
    / "refusals.py"
)

#: The venue's text was measured IDENTICAL across codes 5, 12, 13 and 14. Its
#: exact wording was not recorded, so this stands in for it: what the capture
#: established is that ONE string served every code, which is the whole
#: premise of the ignore-the-text rule.
SHARED_TEXT: Final[str] = "failed to reach the requested service"

#: The measured 401: 33 bytes, not JSON. Only the LENGTH and the
#: not-JSON-ness are evidence; these particular bytes are synthetic, and the
#: length is asserted below so the fixture cannot drift from the measurement.
NON_JSON_401_BODY: Final[bytes] = b"unauthorized: signature invalid\r\n"

#: The rate-limit body the venue's own documentation shows. It carries no
#: ``code`` key at all -- so the envelope is not uniform, and the classifier
#: must fall through to the status rather than fail on the absence.
DOCUMENTED_429_BODY: Final[bytes] = b'{ "status": 429, "message": "Too Many Requests" }'

INSTRUMENT: Final[str] = "highest-temperature-in-nyc-on-september-2"
OTHER_INSTRUMENT: Final[str] = "highest-temperature-in-chicago-on-september-2"


def grpc_body(code: int, *, text: str = SHARED_TEXT) -> bytes:
    """A ``google.rpc.Status`` envelope, in the shape the venue returns."""
    return json.dumps({"code": code, "message": text, "details": []}).encode("utf-8")


# ---------------------------------------------------------------------------
# The DEFAULT -- first, because it is the safe direction and the one every
# unmeasured future failure will take
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "body"),
    [
        pytest.param(418, None, id="an unknown status with no body"),
        pytest.param(400, grpc_body(3), id="a gRPC code outside the map"),
        pytest.param(409, b'{"error": "conflict"}', id="a JSON body that is not an envelope"),
        pytest.param(404, b"[]", id="a JSON body that is not even an object"),
        pytest.param(200, b"", id="an empty body"),
        pytest.param(None, None, id="no status at all"),
    ],
)
def test_an_unclassified_refusal_is_durable(status: int | None, body: bytes | None) -> None:
    """DURABLE is what the classifier returns when it has learned nothing.

    Not a fallback branch nobody exercises: every shape the capture did NOT
    establish arrives here, and every one of them must keep R-4's latch.
    """
    assert classify_venue_refusal(status=status, body=body) is RefusalClass.DURABLE


# ---------------------------------------------------------------------------
# Re-derivation -- the ONLY thing being TRANSIENT buys
# ---------------------------------------------------------------------------


def test_a_transient_http_status_is_reclassified_on_a_later_successful_reconcile() -> None:
    """A transient refusal for THIS instrument is re-derived; nothing else is.

    Three things are asserted at once, because they are one rule: the
    instrument's transient refusal is gone, its DURABLE refusal survives
    (R-4 invariant 1, unweakened), and another instrument's transient refusal
    is untouched -- a successful reconcile is evidence about the instrument it
    reconciled and about nothing else.
    """
    transient_here = ClassifiedRefusal(
        instrument=INSTRUMENT,
        reason="the venue position read failed",
        classification=classify_venue_refusal(status=503, body=grpc_body(14)),
    )
    durable_here = ClassifiedRefusal(
        instrument=INSTRUMENT,
        reason="the venue reports a position under an unusable slug",
        classification=classify_venue_refusal(status=404, body=grpc_body(5)),
    )
    transient_elsewhere = ClassifiedRefusal(
        instrument=OTHER_INSTRUMENT,
        reason="the venue position read failed",
        classification=classify_venue_refusal(status=500, body=grpc_body(13)),
    )
    latched = (transient_here, durable_here, transient_elsewhere)

    assert transient_here.classification is RefusalClass.TRANSIENT
    assert durable_here.classification is RefusalClass.DURABLE

    survivors = refusals_after_successful_reconcile(latched, instrument=INSTRUMENT)

    assert survivors == (durable_here, transient_elsewhere)
    assert latched == (transient_here, durable_here, transient_elsewhere), (
        "the input must not be mutated: the caller's latch is its own"
    )


def test_a_successful_reconcile_of_an_unrefused_instrument_changes_nothing() -> None:
    """Boundary: reconciling an instrument that has no refusal drops none."""
    latched = (
        ClassifiedRefusal(
            instrument=INSTRUMENT,
            reason="the venue position read failed",
            classification=RefusalClass.TRANSIENT,
        ),
    )

    assert refusals_after_successful_reconcile(latched, instrument=OTHER_INSTRUMENT) == latched
    assert refusals_after_successful_reconcile((), instrument=INSTRUMENT) == ()


# ---------------------------------------------------------------------------
# The scope limit: timeouts are OUT, and take the default
# ---------------------------------------------------------------------------


def test_a_timeout_is_not_classified_transient() -> None:
    """A timeout reaches this classifier carrying neither a status nor a body.

    ``NautilusHttpTransport.get`` raises one ``VenueTransportError`` for both
    ``HttpError`` and ``HttpTimeoutError``, ``from None``, and the read path is
    not R-6d's to change. So the timeout is DURABLE by default -- it is not
    guessed transient on the strength of a name.
    """
    assert classify_venue_refusal(status=None, body=None) is RefusalClass.DURABLE
    assert classify_venue_refusal(status=None, body=b"timeout") is RefusalClass.DURABLE


# ---------------------------------------------------------------------------
# Hard rule 1 -- the text discriminates nothing, so it is never read
# ---------------------------------------------------------------------------


def test_the_classifier_ignores_message_text() -> None:
    """Identical text, different codes -> different classes. And the reverse.

    The venue's text was measured identical across codes 5, 12, 13 and 14, so
    a substring match would read "this venue will never implement this" as
    "retry in a minute". Both halves below fail for any classifier that reads
    the text: the first varies only the code, the second varies only the text.
    """
    same_status = 500

    transient = classify_venue_refusal(status=same_status, body=grpc_body(13, text=SHARED_TEXT))
    durable = classify_venue_refusal(status=same_status, body=grpc_body(12, text=SHARED_TEXT))

    assert transient is RefusalClass.TRANSIENT
    assert durable is RefusalClass.DURABLE

    unavailable_worded_as_a_permanent_failure = classify_venue_refusal(
        status=503, body=grpc_body(14, text="this route is not implemented and never will be")
    )
    unimplemented_worded_as_an_outage = classify_venue_refusal(
        status=503, body=grpc_body(12, text="temporarily unavailable, please retry shortly")
    )

    assert unavailable_worded_as_a_permanent_failure is RefusalClass.TRANSIENT
    assert unimplemented_worded_as_an_outage is RefusalClass.DURABLE


def test_the_classifier_module_never_reads_the_text_field() -> None:
    """Structural companion to the behavioural pin above.

    The behavioural test can be satisfied by a classifier that reads the text
    *and* the code; this one refuses the read outright. Prose may name the
    field -- what may not appear is a quoted key or an attribute access, i.e.
    any way of actually getting at the value.
    """
    source = REFUSALS_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
        and isinstance(node.body[0].value.value, str)
    }
    string_constants = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]
    attributes = [node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)]

    assert "message" not in string_constants, "the classifier must not key on the text field"
    assert "message" not in attributes, "the classifier must not reach the text field"


# ---------------------------------------------------------------------------
# Hard rule 2 -- the envelope may not be assumed on the auth path
# ---------------------------------------------------------------------------


def test_a_non_json_401_body_classifies_without_raising() -> None:
    """The measured 401 body is 33 bytes and is not JSON.

    A parser that assumed ``google.rpc.Status`` would raise here -- on the
    credential path, during boot -- and the exception would be read as a venue
    outage rather than as a rejected signature. It classifies instead, and it
    classifies DURABLE: a rejected signature is not something a retry fixes.
    """
    assert len(NON_JSON_401_BODY) == 33, "the fixture must keep the measured length"

    assert grpc_status_code(NON_JSON_401_BODY) is None
    assert classify_venue_refusal(status=401, body=NON_JSON_401_BODY) is RefusalClass.DURABLE
    assert classify_venue_refusal(status=401, body=None) is RefusalClass.DURABLE


# ---------------------------------------------------------------------------
# The code map
# ---------------------------------------------------------------------------


def test_grpc_12_unimplemented_is_never_transient() -> None:
    """12 is permanent, and it VETOES an otherwise transient status.

    The measured pairing is 501/12, but the veto is on the code: a 503 body
    carrying 12 is still a route this venue has not implemented, and retrying
    it is pure waste.
    """
    for status in (501, 500, 503, 429, None):
        assert classify_venue_refusal(status=status, body=grpc_body(12)) is RefusalClass.DURABLE, (
            f"gRPC 12 must never be transient, and was not at status {status}"
        )


def test_a_501_with_no_body_is_durable() -> None:
    """The one place TRANSIENT is narrower than the plan's literal "429 or 5xx".

    501 is the status the capture measured carrying code 12, and "not
    implemented" is permanent whether or not the body survives to say so.
    Narrowing TRANSIENT moves toward the safe default, never away from it.
    """
    assert classify_venue_refusal(status=501, body=None) is RefusalClass.DURABLE
    assert classify_venue_refusal(status=501, body=b"") is RefusalClass.DURABLE


def test_the_measured_boot_envelope_classifies_as_the_capture_maps_it() -> None:
    """Every row of the 2026-09-02 capture, plus the documented 429.

    The rows are the plan's section R-5R table. The 429 row is the venue's own
    documentation, and its body is deliberately the shape the docs show -- no
    ``code`` key at all -- so the fall-through to the status is exercised by a
    real observed envelope and not only by a synthetic one.
    """
    measured = (
        (500, grpc_body(13), RefusalClass.TRANSIENT),
        (503, grpc_body(14), RefusalClass.TRANSIENT),
        (501, grpc_body(12), RefusalClass.DURABLE),
        (404, grpc_body(5), RefusalClass.DURABLE),
        (401, NON_JSON_401_BODY, RefusalClass.DURABLE),
        (429, DOCUMENTED_429_BODY, RefusalClass.TRANSIENT),
    )

    for status, body, expected in measured:
        assert classify_venue_refusal(status=status, body=body) is expected, (
            f"status {status} must classify {expected}"
        )


def test_the_envelope_decoder_reads_only_a_true_integer_code() -> None:
    """``code`` is an int in ``google.rpc.Status``. Anything else is unknown.

    ``True`` is an ``int`` in Python, so a body carrying ``{"code": true}``
    would otherwise decode as code 1 (CANCELLED) -- a class derived from a
    field the venue never sent.
    """
    assert grpc_status_code(grpc_body(14)) == 14
    assert grpc_status_code(b'{"code": "14"}') is None
    assert grpc_status_code(b'{"code": true}') is None
    assert grpc_status_code(b'{"code": 14.5}') is None
    assert grpc_status_code(b"not json at all") is None
    assert grpc_status_code(None) is None
    assert grpc_status_code('{"code": 14}') == 14
