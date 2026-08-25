"""A fully-redacting ``SecureString`` for Polymarket.us credential material.

Why this module exists
----------------------
``nautilus_trader.common.secure.SecureString`` is safe-by-name only. Its
``get_redacted()`` returns ``value[:4] + "..." + value[-4:]``
(``nautilus_trader/common/secure.py:100-102``) and both ``__str__`` (``:133``)
and ``__repr__`` (``:139``) route through it, so rendering one publishes the
first and last FOUR base64 characters of the Ed25519 secret.

``PolymarketUSCredentials`` hand-writes a ``__repr__`` that closes this for the
*container*, but ``dataclasses.asdict()`` walks past that hook entirely: it
detects ``__dataclass_fields__`` and recurses into each field via ``getattr``,
so the ``copy.deepcopy`` lands on the ``SecureString`` itself and the upstream
leaking ``__repr__`` renders. Reproduced before this module existed::

    {'key_id': SecureString(name='polymarket_us_key_id', value=AAAA...ZZ==),
     'secret_key': SecureString(name='polymarket_us_secret_key', value=AAAA...ZZ=)}

(fragments shown as ``AAAA``/``ZZ`` -- the real run rendered the actual first
and last four base64 characters of the key in each slot.)

Nautilus Trader is IMMUTABLE (CLAUDE.md). This module does not modify, patch or
monkey-patch it: subclassing is a native extension point. Breezy constructs
every credential-bearing ``SecureString`` itself (``env.py``), so the subclass
covers all real construction sites and the leak is closed *structurally*,
wherever the object is rendered, rather than only at the container's repr.

The AST barrier ``find_asdict_on_credentials`` in
``tests/unit/test_polymarket_us_credential_serialization.py`` is retained as
defence in depth: it stops the ``asdict``-on-a-credential idiom being written at
all, which still matters because ``asdict`` yields raw, picklable credential
objects regardless of how they render.

Scope, stated plainly
---------------------
This subclass closes the RENDERING seam only. It deliberately does NOT add a
``__reduce__``/``__deepcopy__`` refusal: the container already refuses pickling
and copying, and a refusal here would make ``dataclasses.asdict`` raise, which
is a behaviour change beyond the rendering fix. Serialisation of a credential
remains guarded by ``PolymarketUSCredentials`` and by the AST barrier.

``mask_api_key`` (``common/secure.py``) takes a plain ``str`` and is a module
function, not a method, so it cannot be overridden here; it is banned repo-wide
by the ``BANNED_PARTIAL_HELPERS`` barrier in
``tests/unit/test_polymarket_us_secret_exposure.py``.
"""

from __future__ import annotations

from nautilus_trader.common.secure import SecureString

from breezy.adapters.polymarket_us.redaction import REDACTED

__all__ = ["RedactedSecureString"]


class RedactedSecureString(SecureString):
    """``SecureString`` that renders no fragment of the protected value.

    Behaviour is otherwise unchanged: ``get_value()`` still returns the secret,
    ``clear()``, ``__eq__``, ``__bool__`` and ``__len__`` are inherited intact.
    Only the rendering surface is overridden.
    """

    def get_redacted(self, visible_chars: int = 4) -> str:
        """Return the redaction marker; ``visible_chars`` is ignored on purpose.

        The base implementation returns ``value[:n] + "..." + value[-n:]``. The
        parameter is accepted so the override stays substitutable, and
        discarded so that no caller -- including Nautilus itself -- can dial the
        redaction back open.
        """
        return REDACTED

    def __str__(self) -> str:
        return REDACTED

    def __repr__(self) -> str:
        # ``_name`` is a caller-chosen label (e.g. "polymarket_us_secret_key"),
        # never secret material, and keeps the render diagnostically useful.
        return f"RedactedSecureString(name={self._name!r}, value={REDACTED})"

    def __format__(self, format_spec: str) -> str:
        """Cover ``f"{secure}"`` / ``format(secure, spec)`` for every spec.

        ``object.__format__`` raises ``TypeError`` for a non-empty spec, so
        without this an f-string with a format spec would be a rendering path
        that never reaches ``__str__``.
        """
        return REDACTED
