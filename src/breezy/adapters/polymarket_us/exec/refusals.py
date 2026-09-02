"""Is a refusal TRANSIENT or DURABLE? Classification only -- never a retry.

Authority: ``docs/plans/EXEC_SPINE_R5_R6_2026-09-02.md`` section R-6d.
**Pure.** Every function here takes plain values, performs no I/O, holds no
state, and returns a verdict. Nothing here retries, schedules, sleeps, or
sends: acting on a classification is R-7's business, and
``nautilus_trader/live/retry.py``'s ``RetryManager`` -- a retry EXECUTOR, not
a classifier -- is banned by name by the parent plan's barrier B8.

NULL HYPOTHESIS: REFUTED (plan N8). ``grep -rn "retryable|RETRYABLE|AMBIGUOUS|
Ambiguous"`` across the installed Nautilus returns **0 files** (positive
control ``retry_`` -> 32 files), so no native taxonomy exists to extend. Breezy
owns this one, and owns it in exactly two classes.

Breezy's own near-neighbour is not one either.
``PolymarketUSHttpClient._raise_for_status`` (``http.py``) maps a status onto
an EXCEPTION TYPE -- rate limit, auth, unexpected. That answers "what went
wrong", never "may this refusal be re-derived later", which is the only
question this module exists to answer.

THE TWO CLASSES, AND WHAT EACH ONE BUYS
----------------------------------------

* :attr:`RefusalClass.TRANSIENT` -- the venue was rate limited or failing at
  boot. This is the ONLY class that may be re-derived on a subsequent
  successful reconcile of the SAME instrument
  (:func:`refusals_after_successful_reconcile`).
* :attr:`RefusalClass.DURABLE` -- everything else, **and the default**. It
  keeps R-4's invariant 1 exactly: the refusal latch never self-clears
  (``exec/client.py``). Every failure shape the venue capture did not
  establish lands here, which is the safe direction.

TWO RULES FROM THE MEASURED ENVELOPE, NEITHER OF THEM SOFT
-----------------------------------------------------------

The venue returns ``google.rpc.Status`` -- ``{code, message, details}`` -- and
the 2026-09-02 capture found **the human-readable text IDENTICAL across codes
5, 12, 13 and 14**. It discriminates nothing.

1. **Classification is on ``code`` and HTTP status ONLY; the text is never
   read.** A substring match would classify 501 UNIMPLEMENTED exactly as it
   classifies 503 UNAVAILABLE -- reading "this venue will never implement
   this" as "retry in a minute". The ban is mechanised, not merely stated:
   ``test_the_classifier_module_never_reads_the_text_field`` refuses a quoted
   key or an attribute access on that field anywhere in this file.
2. **The envelope may not be assumed.** The measured 401 body is 33 bytes and
   is **not JSON**; the venue's documented 429 body is JSON but carries no
   ``code`` key at all
   (``docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_rate-limits_2026-08-25.md``).
   So :func:`grpc_status_code` returns ``None`` for anything it cannot read as
   a true integer code and NEVER raises. A parser that assumed the envelope
   would throw on the credential path, during boot, where the exception reads
   as a venue outage rather than as a rejected signature.

WHAT THIS MODULE DELIBERATELY DOES NOT CLASSIFY
------------------------------------------------

**Timeouts.** ``NautilusHttpTransport.get`` (``transport.py``) collapses
``HttpError`` and ``HttpTimeoutError`` into one ``VenueTransportError`` with
``from None``, and the parent plan forbids changing the read path. A timeout
therefore arrives here carrying NO status and NO body, and takes the DURABLE
default rather than being guessed transient on the strength of its name. The
write path's two distinct error types arrive at R-6.5, which is where a
timeout can be classified honestly.

WHO CALLS THIS -- R-6.5a GIVES IT ITS FIRST PRODUCTION CALLER
----------------------------------------------------------------

Until R-6.5a, nothing did -- the same shape R-4 landed in (a library with zero
construction sites). The consumer has now arrived: the injected
``private_read`` closure (``factories.py``) raises :class:`PrivateReadRefused`
on any non-2xx status instead of decoding the body as a payload -- the
``PrivateRead`` protocol's own docstring (``exec/client.py``) states this as
an obligation every implementation must meet, present or future
(Kalshi included). ``PolymarketUSExecutionClient.generate_position_status_
reports`` catches it and calls :func:`classify_venue_refusal` with its
``status`` and ``body`` directly -- the status/body pair that used to live
only at the transport boundary, on ``VenueResponse``, OUTSIDE ``exec/``. This
module still takes plain ints and bytes rather than importing that type:
``exec/`` importing ``transport.py`` is banned outright by E0-INERT, and
``PrivateReadRefused`` is what carries the pair across that boundary legally.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

__all__ = [
    "PERMANENT_GRPC_CODES",
    "PERMANENT_SERVER_STATUSES",
    "RATE_LIMIT_STATUS",
    "TRANSIENT_GRPC_CODES",
    "ClassifiedRefusal",
    "PrivateReadRefused",
    "RefusalClass",
    "classify_venue_refusal",
    "grpc_status_code",
    "refusals_after_successful_reconcile",
]


@dataclass(frozen=True)
class PrivateReadRefused(Exception):
    """The venue answered a private read with a non-2xx HTTP status.

    RAISED by an injected :class:`~breezy.adapters.polymarket_us.exec.client.
    PrivateRead` implementation -- never returned as a decoded mapping. See
    that protocol's own docstring for the obligation this type exists to
    satisfy: before R-6.5a, ``factories.py``'s ``private_read`` closure
    discarded ``response.status`` outright and handed a 503's
    ``google.rpc.Status`` body to :func:`~breezy.adapters.polymarket_us.
    exec.endpoints.decode_private_payload` as if it were a payload, which
    meant :func:`classify_venue_refusal` could never be fed a real caller.
    This type is that feed.

    ``status`` and ``body`` are exactly :func:`classify_venue_refusal`'s two
    keyword parameters. ``path`` is the bare path that was signed -- never a
    full URL, which a caller conforming to the protocol never has either.

    No ``slots=True``: on an ``Exception`` subclass it buys nothing --
    ``BaseException`` already carries a ``__dict__``, so the slot declaration
    does not stop an arbitrary attribute from being attached, and dropping it
    removes a false sense of closure the docstring must not imply.

    ``__reduce__`` is required, not optional: the dataclass-generated
    ``__init__`` never calls ``Exception.__init__``, so ``self.args == ()``,
    and ``BaseException``'s own ``__reduce__`` reconstructs via
    ``cls(*self.args)`` -- a ``TypeError`` on ``pickle.dumps``,
    ``copy.copy``, or ``copy.deepcopy``, which
    ``logging.handlers.QueueHandler`` triggers by pickling ``exc_info``.
    Overriding it explicitly is the fix; a ``__post_init__`` that calls
    ``super().__init__(...)`` would work too but leaves a second, redundant
    ``args`` tuple sitting beside the three real fields for no benefit.

    **The body is the operator's own financial position and must never reach
    a log, an exception message, a ``repr``, or an artefact.**
    ``field(repr=False)`` stops the dataclass-GENERATED ``__repr__`` alone --
    it does not touch ``str()``, and ``dataclasses.asdict`` ignores it
    entirely -- so both dunders below are overridden explicitly, and
    ``asdict``/``astuple`` applied to this type anywhere under ``src/`` are
    flagged by an AST LINT, not proven absent by it -- see
    :func:`find_asdict_or_astuple_on_private_read_refused` in
    ``tests/unit/test_polymarket_us_exec_refusals.py`` for exactly what it
    can and cannot see.
    """

    status: int
    path: str
    body: bytes = field(repr=False)

    def __str__(self) -> str:
        return f"PrivateReadRefused(path={self.path!r}, status={self.status})"

    __repr__ = __str__

    def __reduce__(self) -> tuple[type[PrivateReadRefused], tuple[int, str, bytes]]:
        """Pickle/``copy`` support: reconstruct through the real fields.

        ``BaseException.__reduce__`` reconstructs via ``cls(*self.args)``,
        and ``self.args`` is empty here (the dataclass ``__init__`` never
        calls ``Exception.__init__``). Returning the field tuple directly is
        what makes ``pickle``, ``copy.copy`` and ``copy.deepcopy`` work.
        """
        return (PrivateReadRefused, (self.status, self.path, self.body))


class RefusalClass(Enum):
    """How a refusal may be treated LATER. Two members, and no third.

    A third member would be a class nothing measured, and every consumer would
    have to guess which side of the re-derivation rule it falls on.
    """

    TRANSIENT = "TRANSIENT"
    """The venue was rate limited or failing. Re-derivable (see the module
    docstring); this is the ONLY class that is."""

    DURABLE = "DURABLE"
    """Everything else, and the default. Keeps R-4's invariant 1."""


#: gRPC codes MEASURED at boot on 2026-09-02 that describe a venue which is
#: implemented and failing: 14 UNAVAILABLE (positions, open orders) and
#: 13 INTERNAL (balances). Plan section R-5R tabulates the capture.
TRANSIENT_GRPC_CODES: Final[frozenset[int]] = frozenset({13, 14})

#: gRPC codes that are PERMANENT, and which therefore VETO an otherwise
#: transient status: 12 UNIMPLEMENTED (measured on the open-orders GET route --
#: the venue does not register that verb, so retrying is pure waste) and
#: 5 NOT_FOUND (measured on a signed unknown path).
PERMANENT_GRPC_CODES: Final[frozenset[int]] = frozenset({5, 12})

#: DOCUMENTED, not measured: the venue's rate-limit page states this status,
#: and its example body carries no gRPC code at all.
RATE_LIMIT_STATUS: Final[int] = 429

#: 5xx statuses that are NOT transient. 501 is the wire form of the permanent
#: code 12 -- the capture measured exactly that pairing -- and "not
#: implemented" stays permanent whether or not a body survives to say so.
#: This is the one point where TRANSIENT is narrower than the plan's literal
#: "429 or 5xx", and it narrows TOWARD the safe default, never away from it.
PERMANENT_SERVER_STATUSES: Final[frozenset[int]] = frozenset({501})

_SERVER_ERROR_LOWER: Final[int] = 500
_SERVER_ERROR_UPPER: Final[int] = 600


@dataclass(frozen=True, slots=True)
class ClassifiedRefusal:
    """One refusal, the instrument it is about, and how it may be treated.

    Frozen: a classification is a record of what was observed, and re-deriving
    one means building a new set (:func:`refusals_after_successful_reconcile`),
    never mutating an existing verdict in place.

    ``instrument`` is a plain string -- the venue's market slug, or the string
    form of a native ``InstrumentId``. This module imports no Nautilus type
    because it needs none, and the caller that has one knows which it holds.
    """

    instrument: str
    reason: str
    classification: RefusalClass


def grpc_status_code(body: bytes | str | None) -> int | None:
    """Read the gRPC code out of a venue error body, or ``None``. NEVER raises.

    ``None`` means "this body told us nothing" and covers every shape the
    venue actually produces outside the envelope: no body at all, the measured
    33-byte non-JSON 401, the documented 429 body that has no code key, a JSON
    array, or a code field that is not a true integer.

    ``True`` is an ``int`` in Python, so a bool is rejected explicitly: without
    that check ``{"code": true}`` would decode as code 1 and a class would be
    derived from a field the venue never sent.
    """
    if body is None:
        return None
    try:
        payload = json.loads(body)
    except (ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    code = payload.get("code")
    if isinstance(code, bool) or not isinstance(code, int):
        return None
    return code


def classify_venue_refusal(
    *,
    status: int | None,
    body: bytes | str | None = None,
) -> RefusalClass:
    """Classify one refusal from its HTTP status and gRPC code. Nothing else.

    ``status`` is the HTTP status the venue returned, or ``None`` when the
    failure carried none (a transport failure or a timeout). ``body`` is the
    raw response body, undecoded; it is read ONLY for its gRPC code.

    Precedence, in order, and each step justified by the capture:

    1. A PERMANENT code vetoes everything. 12 UNIMPLEMENTED and 5 NOT_FOUND
       describe a venue that will answer the same way next time.
    2. A TRANSIENT code (14 UNAVAILABLE, 13 INTERNAL) classifies transient.
    3. Otherwise the status decides: 429, or a 5xx that is not one of the
       permanent server statuses.
    4. Otherwise DURABLE -- the default, and the safe direction.

    The human-readable text is never consulted at any step; the capture
    measured it identical across four different codes, so it discriminates
    nothing at all.
    """
    code = grpc_status_code(body)
    if code is not None:
        if code in PERMANENT_GRPC_CODES:
            return RefusalClass.DURABLE
        if code in TRANSIENT_GRPC_CODES:
            return RefusalClass.TRANSIENT
    return _classify_status(status)


def _classify_status(status: int | None) -> RefusalClass:
    """The status-only half. ``None`` -- a timeout, a TLS failure -- is DURABLE."""
    if status is None:
        return RefusalClass.DURABLE
    if status == RATE_LIMIT_STATUS:
        return RefusalClass.TRANSIENT
    if status in PERMANENT_SERVER_STATUSES:
        return RefusalClass.DURABLE
    if _SERVER_ERROR_LOWER <= status < _SERVER_ERROR_UPPER:
        return RefusalClass.TRANSIENT
    return RefusalClass.DURABLE


def refusals_after_successful_reconcile(
    refusals: Sequence[ClassifiedRefusal],
    *,
    instrument: str,
) -> tuple[ClassifiedRefusal, ...]:
    """Re-derive the refusal set after ONE instrument reconciled successfully.

    Exactly one thing is dropped: a :attr:`RefusalClass.TRANSIENT` refusal
    about ``instrument``. A successful reconcile is evidence about the
    instrument it reconciled and about nothing else, so another instrument's
    transient refusal survives untouched -- and so does every DURABLE one,
    which is R-4's invariant 1 restated rather than weakened.

    Returns a NEW tuple; the caller's sequence is never mutated.
    """
    return tuple(
        refusal
        for refusal in refusals
        if not (
            refusal.instrument == instrument and refusal.classification is RefusalClass.TRANSIENT
        )
    )
