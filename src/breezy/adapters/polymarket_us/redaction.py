"""Redaction helpers for the Polymarket.us adapter (plan section 6, SEC-3).

Deliberately separated from :mod:`breezy.adapters.polymarket_us.errors` so that
redaction carries no dependency on the error hierarchy and can be imported by
the venue smoke script and the evidence writer as well as by error rendering.

Null-hypothesis note: ``redact_url`` is NOT re-implemented here. Breezy already
owns exactly one URL-redaction policy at ``breezy/ingest/http.py:272`` (strips
query-parameter values and ``user:pass@`` userinfo); a second implementation
would be a second policy that can silently drift. This module re-exports it and
adds only the genuinely new header and free-text helpers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from breezy.ingest.http import REDACTION_MARKER, redact_url

#: Replacement token substituted for any redacted value.
#:
#: Re-exported from the ingest layer, NOT redefined. ``redact_url`` and these
#: helpers form one redaction surface, and a second literal here is a second
#: policy that drifts: before unification, query values rendered ``REDACTED``
#: while headers and free text rendered ``<redacted>``.
REDACTED: str = REDACTION_MARKER

#: Header names (lower-cased for comparison) whose values must never be
#: rendered into a log line, an exception message, or an evidence artefact.
#: ``x-pm-timestamp`` is included not because it is secret but because it is
#: part of the signed canonical string, and an attacker holding a signature is
#: helped by knowing the exact timestamp it was computed over.
SENSITIVE_HEADERS: frozenset[str] = frozenset(
    {
        "x-pm-access-key",
        "x-pm-signature",
        "x-pm-timestamp",
        "authorization",
        "cookie",
        "set-cookie",
    }
)

__all__ = [
    "REDACTED",
    "SENSITIVE_HEADERS",
    "redact_headers",
    "redact_secure",
    "redact_text",
    "redact_url",
]


def redact_secure(value: object) -> str:
    """Render any credential-bearing value as the marker, reading nothing.

    Exists because ``SecureString`` is safe-by-name only: ``str()``/``repr()``
    of one delegates to ``get_redacted()``, which returns
    ``value[:4] + "..." + value[-4:]`` (``nautilus_trader/common/secure.py``
    ``:100-102``) and so publishes eight characters of the Ed25519 secret.
    Nautilus is IMMUTABLE, so Breezy interposes here.

    The argument is accepted and discarded on purpose: the function is a
    typed, greppable rendering seam that CANNOT leak, rather than a formatter
    whose safety depends on which branch it takes.
    """
    return REDACTED


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return a copy of ``headers`` with every sensitive value replaced.

    Header names are preserved verbatim (they are not secret and their presence
    is diagnostically useful); matching is case-insensitive because HTTP header
    names are. The input mapping is never mutated.
    """
    return {
        name: (REDACTED if name.lower() in SENSITIVE_HEADERS else value)
        for name, value in headers.items()
    }


def redact_text(text: str, secrets: Iterable[str]) -> str:
    """Return ``text`` with every non-empty member of ``secrets`` masked.

    Longer secrets are substituted first so that a secret which is a substring
    of another cannot leave a partial value behind.
    """
    scrubbed = text
    for secret in sorted({s for s in secrets if s}, key=len, reverse=True):
        scrubbed = scrubbed.replace(secret, REDACTED)
    return scrubbed
