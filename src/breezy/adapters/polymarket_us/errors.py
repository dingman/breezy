"""Typed error taxonomy for the Polymarket.us adapter (plan section 6).

Every message rendered by these types is built from the HTTP method, a
redacted URL, a status code, and a redacted header view -- never a raw header
map and never a response body. That is a structural guarantee: the only helper
for building request context, :func:`format_request_context`, redacts before it
formats, so there is no path that formats a raw header value by accident.
"""

from __future__ import annotations

from collections.abc import Mapping

from breezy.adapters.polymarket_us.redaction import redact_headers, redact_url

__all__ = [
    "BoundsSemanticsError",
    "CredentialConfigError",
    "CredentialSerializationError",
    "CredentialSourceError",
    "FeeScheduleUnknownError",
    "GatewayForbiddenError",
    "InstrumentDefinitionError",
    "MakerRebateUnmodelledError",
    "MethodNotPermittedError",
    "PolymarketUSError",
    "SignatureClockSkewError",
    "VenueAuthError",
    "VenuePayloadError",
    "VenueRateLimitError",
    "VenueStatusError",
    "VenueTransportError",
    "format_request_context",
]


class PolymarketUSError(Exception):
    """Base class for every Polymarket.us adapter failure."""


class CredentialConfigError(PolymarketUSError, ValueError):
    """Credential *configuration* violates the no-secret-in-config rule.

    Inherits ``ValueError`` as well as :class:`PolymarketUSError` so that
    callers written against the original ``ValueError`` contract keep working
    while the class still sits inside one adapter-wide taxonomy. This is the
    single definition; :mod:`breezy.adapters.polymarket_us.credentials`
    re-exports it rather than declaring a second, parallel root.
    """


class CredentialSourceError(CredentialConfigError):
    """Credential material is missing, ambiguous, malformed, or unsafely stored.

    Raised without ever echoing the offending value.

    Homed here, not in :mod:`~breezy.adapters.polymarket_us.env`. Two
    same-named classes in one package means ``except CredentialSourceError``
    catches whichever one the caller happened to import and silently misses
    the other -- the loader seam and the signing seam each raised a different
    class before this was unified.
    """


class CredentialSerializationError(CredentialConfigError):
    """A credential object was pushed through a serialisation protocol.

    Raised by ``PolymarketUSCredentials.__reduce__``/``__deepcopy__`` for
    pickle, ``copy.deepcopy``, and everything layered on them (including
    ``dataclasses.asdict``, which recurses via ``deepcopy``).

    This RAISES rather than emitting a redacted placeholder on purpose.
    ``SecureString`` keeps the plaintext in ``_value`` and a second copy in the
    ``_bytes`` bytearray and defines no reduction hook of its own
    (``nautilus_trader/common/secure.py:44-52``), so a serialised credential
    carries the full Ed25519 secret in cleartext. Nautilus is IMMUTABLE, so the
    refusal is interposed on Breezy's container instead. A placeholder would
    round-trip into a silently broken credential that fails far from its cause;
    credentials are loaded from the environment in-process and are never
    legitimately transported.
    """


class MethodNotPermittedError(PolymarketUSError):
    """An HTTP method outside the read-only allow-list was attempted.

    This is order-submission barrier B2: the read-only slice signs ``GET`` and
    nothing else, enforced in the signer itself rather than at a call site.
    """


class SignatureClockSkewError(PolymarketUSError):
    """The local clock drifted outside the venue's Ed25519 signing window.

    Raised locally, with a named cause, instead of letting the venue reject the
    request opaquely.
    """


class VenueAuthError(PolymarketUSError):
    """The venue rejected our credentials or signature (401/403 on the API)."""


class GatewayForbiddenError(PolymarketUSError):
    """``gateway.polymarket.us`` returned 403 to a non-browser request (G15)."""


class VenueRateLimitError(PolymarketUSError):
    """The venue returned 429, or a stopgap 'Global Rate Limit Exceeded'."""

    def __init__(self, message: str, *, retry_after: str | None) -> None:
        super().__init__(message)
        self.retry_after: str | None = retry_after


class VenueStatusError(PolymarketUSError):
    """The venue returned an unexpected, non-specific HTTP status."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(f"{message} (status_code={status_code})")
        self.status_code: int = status_code


class VenuePayloadError(PolymarketUSError, ValueError):
    """A venue payload is missing, malformed, or outside physical sanity bounds.

    Raised at the JSON -> domain trust boundary. A payload that cannot be
    converted without guessing is an error, never a value to coerce or a field
    to default: a silently coerced price or size becomes a wrong settlement
    join or a wrong order size much later, with nothing pointing back here.

    Inherits ``ValueError`` for the same reason
    :class:`CredentialConfigError` does -- it IS a value-domain failure -- while
    still sitting inside the one adapter-wide taxonomy so a caller can write
    ``except PolymarketUSError`` and miss nothing.
    """


class InstrumentDefinitionError(VenuePayloadError):
    """An instrument definition payload cannot be turned into a valid instrument.

    Distinct from the general payload error because the *consequence* differs:
    a bad quote frame can be dropped and the next one used, whereas a bad
    instrument definition must abort the load. The instrument provider raises
    this rather than skipping the market, so a venue schema change surfaces as
    a failed start-up instead of a silently short instrument list.
    """


class BoundsSemanticsError(VenuePayloadError):
    """A weather slug's verbatim bounds are not corroborated by the venue prose.

    The slug stores its comparator tokens verbatim (``lt79``) while the venue's
    own ``description``/``title`` may spell the same contract differently
    ("less than or equal to 78F", "78 or below"). Those agree ONLY if the
    settlement reading is a whole degree, and only if the venue's two
    spellings actually describe the same half-line -- neither of which this
    adapter is entitled to assume.

    Raised by
    :func:`~breezy.adapters.polymarket_us.symbology.assert_bounds_cross_checked`
    so a consumer cannot treat ``<`` and ``<=`` as interchangeable without
    having validated them against the venue's own words.
    """


class FeeScheduleUnknownError(PolymarketUSError):
    """A fee-consuming path was reached while the venue fee schedule is UNKNOWN.

    Generic Nautilus machinery -- ``MakerTakerFeeModel.get_commission``
    (``backtest/models/fee.pyx:96-99``) among it -- reads the typed
    ``maker_fee``/``taker_fee`` fields directly and nothing else. Whatever
    those fields hold IS the fee, as far as that machinery is concerned.

    On the UNKNOWN branch they hold ``Decimal(0)``, because ``BinaryOption``
    defaults them via ``maker_fee or Decimal(0)``
    (``model/instruments/binary_option.pyx:148-149``) and the adapter has no
    coefficient to pass. A zero there is a REAL, VALID number, not a marker,
    so an unresolved schedule silently reads as a FREE VENUE and inflates
    apparent edge.

    On the KNOWN branch they hold the market's own ``theta`` instead, which
    is a different failure and not a milder one: read as a flat notional rate
    it overstates by ``theta * C * p^2``, with an UNBOUNDED relative error as
    ``p -> 1`` and the venue fee's symmetry about ``p = 0.50`` destroyed. The
    only real defence there is barrier F2 in
    ``tests/unit/test_polymarket_us_fee_guard.py``, which keeps a default fee
    model off every backtest venue.

    So neither branch makes the flat fields safe to read, and this guard is
    what makes the UNKNOWN branch fail loudly rather than freely. Raised by
    :func:`~breezy.adapters.polymarket_us.parsing.assert_fee_schedule_known`,
    which every fee-consuming path must call. Not a ``VenuePayloadError``: the
    payload is fine, it is Breezy's knowledge of the schedule that is missing.
    """


class MakerRebateUnmodelledError(PolymarketUSError):
    """A maker-only (post-only) order reached the fee model, which cannot price it.

    The venue's documented maker coefficient is **negative** (-0.0125): a
    REBATE, i.e. income. ``PolymarketUSFeeModel`` charges makers at the taker
    coefficient (+theta) because no captured payload carries a maker/taker
    split, and applying an unobserved rebate would understate cost.

    That inference is safe for a TAKER gate and only for a taker gate. At
    C=100, p=0.50 the venue would pay $0.3125 while the model charges $1.50 --
    wrong by $1.8125 and wrong in SIGN. Any maker/posting strategy backtested
    against it is negative by construction and therefore unevaluable, so a
    post-only order -- an explicit maker-only intent -- is refused rather than
    silently priced with an inverted sign.

    Resolve by observing a real maker fill and recording the venue's actual
    maker treatment, not by relaxing this refusal.
    """


class VenueTransportError(PolymarketUSError):
    """A transport-level failure (connect, TLS, timeout, malformed response)."""


def format_request_context(
    *,
    method: str,
    url: str,
    headers: Mapping[str, str] | None = None,
    status_code: int | None = None,
) -> str:
    """Build a log-safe one-line description of a venue request.

    The URL passes through :func:`redact_url` (query values and userinfo
    stripped) and the headers through :func:`redact_headers`. No response body
    is ever accepted by this function, so none can be formatted.
    """
    parts = [method, redact_url(url)]
    if status_code is not None:
        parts.append(f"status={status_code}")
    if headers is not None:
        parts.append(f"headers={redact_headers(headers)!r}")
    return " ".join(parts)
