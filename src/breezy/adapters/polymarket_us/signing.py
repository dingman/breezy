"""Ed25519 request signing for the Polymarket.us retail API (plan section 6).

Canonical string
----------------
``timestamp_ms + HTTP_METHOD + path``, signed with the account's Ed25519
private key, base64-encoded into ``X-PM-Signature``.

The DEFAULT builder signs the path WITHOUT the query string. Evidence:

* ``docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_authentication_2026-08-25.md:82``
  -- "The signature is built by combining the timestamp, HTTP method, and
  path"; the worked example at ``:92-96`` computes
  ``message = f"{timestamp}{method}{path}"`` over a bare path.
* ``docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/auth.py:26-27``
  builds the identical string; ``client.py:132`` passes the path only, with the
  query handed separately to httpx.

:func:`build_canonical_path_with_query` ships alongside it as the hypothesis to
DISPROVE at the live smoke probe (plan section 5.1). It is selectable at runtime
through :class:`SigningVariant`.

What that enum actually enforces (corrected -- an earlier revision of this
docstring claimed a typo was "a construction error", which is false):
:class:`SigningVariant` is a :class:`enum.StrEnum`, so its members hash and
compare equal to their plain-string values. ``BUILDERS[variant]`` therefore
accepts the bare string ``"path_only"`` just as readily as
``SigningVariant.PATH_ONLY`` -- there is no construction-time rejection. What IS
enforced is that an UNKNOWN variant raises ``KeyError`` at the ``BUILDERS``
lookup, so a typo fails loudly at signer construction rather than silently
falling back to the wrong canonical scheme. The enum's real value is
discoverability and a single definition of the legal set, not type enforcement.

This is not a security boundary in the read-only slice: the ``GET``-only check
(barrier B2) is independent of the variant and runs before any secret is used,
so no variant value can widen what may be signed.

Inherited protocol weakness (recorded, not fixed): the canonical string has no
field delimiter, so distinct ``(timestamp, method, path)`` triples could in
principle collide. Not exploitable in this read-only slice -- ``method`` is the
fixed constant ``"GET"`` and ``timestamp`` is a 13-digit clock value -- but it
matters once a write path with variable methods exists.

Order-submission barrier B2: :meth:`Ed25519RequestSigner.sign_headers` refuses
to sign any method other than ``GET``. There is no configuration that relaxes
it; a write path must add a method to :data:`PERMITTED_METHODS` deliberately.
"""

from __future__ import annotations

import base64
import binascii
import enum
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from nacl.signing import SigningKey
from nautilus_trader.common.component import Clock

from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
from breezy.adapters.polymarket_us.errors import (
    CredentialSourceError,
    MethodNotPermittedError,
    SignatureClockSkewError,
)
from breezy.adapters.polymarket_us.redaction import REDACTED

__all__ = [
    "ACCESS_KEY_HEADER",
    "BUILDERS",
    "DEFAULT_SKEW_TOLERANCE_MS",
    "PERMITTED_METHODS",
    "SIGNATURE_HEADER",
    "TIMESTAMP_HEADER",
    "CanonicalRequest",
    "CanonicalStringBuilder",
    "Ed25519RequestSigner",
    "SigningVariant",
    "build_canonical_path_with_query",
    "build_canonical_path_without_query",
]

#: Read-only slice: the signer signs GET and nothing else (barrier B2).
PERMITTED_METHODS: frozenset[str] = frozenset({"GET"})

#: The venue rejects a request whose timestamp is more than 30 seconds from
#: server time. Breezy fails locally at the same boundary so host clock drift
#: surfaces as a named error rather than an opaque venue rejection.
DEFAULT_SKEW_TOLERANCE_MS: int = 30_000

ACCESS_KEY_HEADER: str = "X-PM-Access-Key"
TIMESTAMP_HEADER: str = "X-PM-Timestamp"
SIGNATURE_HEADER: str = "X-PM-Signature"

_ED25519_SEED_BYTES: int = 32
_ED25519_EXPANDED_BYTES: int = 64


class SigningVariant(enum.StrEnum):
    """Which canonical-string scheme to sign with."""

    #: DEFAULT. Documented and SDK-confirmed: the query string is NOT signed.
    PATH_ONLY = "path_only"
    #: Hypothesis under test at the live smoke probe. Never the default.
    PATH_WITH_QUERY = "path_with_query"


@dataclass(frozen=True, slots=True)
class CanonicalRequest:
    """The inputs a canonical-string builder is allowed to see.

    ``body`` exists as an inert seam for gap G3 (does the request body
    participate in the signed string?). This slice is GET-only, so both G3
    branches produce byte-identical input and both shipped builders ignore it;
    a unit test pins that inertness.
    """

    timestamp_ms: int
    method: str
    path: str
    query_string: str = ""
    body: bytes = field(default=b"")


CanonicalStringBuilder = Callable[[CanonicalRequest], bytes]


def build_canonical_path_without_query(request: CanonicalRequest) -> bytes:
    """DEFAULT. ``timestamp + METHOD + path``; ignores query string and body.

    Evidence: ``api-reference_authentication_2026-08-25.md:82,94``;
    ``sdk_snapshot/polymarket_us_0.1.2/auth.py:26-27``; ``client.py:132``.
    """
    return f"{request.timestamp_ms}{request.method}{request.path}".encode()


def build_canonical_path_with_query(request: CanonicalRequest) -> bytes:
    """Hypothesis under test at the live smoke probe; ignores the body.

    Appends ``?<query_string>`` when a query is present, and is byte-identical
    to the default builder when it is not.
    """
    path = request.path
    if request.query_string:
        path = f"{path}?{request.query_string}"
    return f"{request.timestamp_ms}{request.method}{path}".encode()


BUILDERS: Mapping[SigningVariant, CanonicalStringBuilder] = MappingProxyType(
    {
        SigningVariant.PATH_ONLY: build_canonical_path_without_query,
        SigningVariant.PATH_WITH_QUERY: build_canonical_path_with_query,
    }
)


def _load_signing_key(secret_b64: str) -> SigningKey:
    """Decode a base64 Ed25519 secret into a signing key, echoing nothing.

    Accepts both the 32-byte seed and the 64-byte ``seed || public`` form, the
    same two shapes the venue SDK accepts (``auth.py:31-34``).
    """
    try:
        raw = base64.b64decode(secret_b64, validate=True)
    except (binascii.Error, ValueError):
        raise CredentialSourceError(
            "Polymarket.us secret key is not valid base64 (value withheld)"
        ) from None
    if len(raw) == _ED25519_EXPANDED_BYTES:
        raw = raw[:_ED25519_SEED_BYTES]
    if len(raw) != _ED25519_SEED_BYTES:
        raise CredentialSourceError(
            "Polymarket.us secret key must decode to "
            f"{_ED25519_SEED_BYTES} or {_ED25519_EXPANDED_BYTES} bytes; "
            f"got {len(raw)} (value withheld)"
        )
    try:
        return SigningKey(raw)
    except (TypeError, ValueError):
        raise CredentialSourceError(
            "Polymarket.us secret key is not a usable Ed25519 seed (value withheld)"
        ) from None


class Ed25519RequestSigner:
    """Produce the three Polymarket.us authentication headers for a GET.

    The signing key is rebuilt from the credential on every call and dropped
    when the call returns, so no long-lived key object holds secret material.
    """

    __slots__ = ("_canonicalize", "_clock", "_credentials", "_skew_tolerance_ms")

    def __init__(
        self,
        credentials: PolymarketUSCredentials,
        *,
        clock: Clock,
        canonicalize: CanonicalStringBuilder = build_canonical_path_without_query,
        skew_tolerance_ms: int = DEFAULT_SKEW_TOLERANCE_MS,
    ) -> None:
        if skew_tolerance_ms <= 0:
            raise ValueError("skew_tolerance_ms must be positive")
        self._credentials = credentials
        self._clock = clock
        self._canonicalize = canonicalize
        self._skew_tolerance_ms = skew_tolerance_ms

    @classmethod
    def for_variant(
        cls,
        credentials: PolymarketUSCredentials,
        *,
        clock: Clock,
        variant: SigningVariant = SigningVariant.PATH_ONLY,
        skew_tolerance_ms: int = DEFAULT_SKEW_TOLERANCE_MS,
    ) -> Ed25519RequestSigner:
        """Build a signer from a :class:`SigningVariant` rather than a callable."""
        return cls(
            credentials,
            clock=clock,
            canonicalize=BUILDERS[variant],
            skew_tolerance_ms=skew_tolerance_ms,
        )

    @property
    def skew_tolerance_ms(self) -> int:
        return self._skew_tolerance_ms

    def assert_within_window(self, timestamp_ms: int) -> None:
        """Raise if ``timestamp_ms`` is outside the signing window.

        The boundary is inclusive: a drift of exactly ``skew_tolerance_ms``
        is accepted, matching the venue's "within 30 seconds" wording.
        """
        drift_ms = timestamp_ms - self._clock.timestamp_ms()
        if abs(drift_ms) > self._skew_tolerance_ms:
            raise SignatureClockSkewError(
                f"Request timestamp drifts {drift_ms} ms from the local clock, outside "
                f"the +/-{self._skew_tolerance_ms} ms Ed25519 signing window; venue "
                "signature verification will fail until the host clock is corrected"
            )

    def sign_headers(
        self,
        method: str,
        path: str,
        *,
        query_string: str = "",
        timestamp_ms: int | None = None,
    ) -> list[tuple[str, str]]:
        """Return the signed auth headers as ordered ``(name, value)`` pairs.

        A ``list[tuple[str, str]]`` -- not a dict -- because
        ``nautilus_pyo3.WebSocketConfig.headers`` requires that shape
        (``core/nautilus_pyo3.pyi:5531-5544``). The HTTP call site converts
        with ``dict(...)`` at exactly one place, since ``HttpClient.get``
        takes ``dict[str, str] | None`` (``:5441-5448``).
        """
        if method not in PERMITTED_METHODS:
            raise MethodNotPermittedError(
                "Polymarket.us request signing is restricted to "
                f"{sorted(PERMITTED_METHODS)} in the read-only slice; "
                f"refused to sign method {method!r}"
            )
        effective_ts = self._clock.timestamp_ms() if timestamp_ms is None else timestamp_ms
        self.assert_within_window(effective_ts)

        canonical = self._canonicalize(
            CanonicalRequest(
                timestamp_ms=effective_ts,
                method=method,
                path=path,
                query_string=query_string,
            )
        )
        signing_key = _load_signing_key(self._credentials.secret_key.get_value())
        signature = base64.b64encode(signing_key.sign(canonical).signature).decode("ascii")
        return [
            (ACCESS_KEY_HEADER, self._credentials.key_id.get_value()),
            (TIMESTAMP_HEADER, str(effective_ts)),
            (SIGNATURE_HEADER, signature),
        ]

    def __repr__(self) -> str:
        return f"Ed25519RequestSigner({REDACTED})"
