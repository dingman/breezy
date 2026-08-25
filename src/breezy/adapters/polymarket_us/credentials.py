"""Credential containment for the Polymarket.us adapter.

NautilusConfig instances are serialised and may be written to disk by the
Nautilus kernel. This module keeps secret-bearing values out of those config
types entirely: config carries only environment variable names, while runtime
credential material lives in SecureString fields on a non-config object.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, get_args, get_origin, get_type_hints

from nautilus_trader.common.config import NautilusConfig
from nautilus_trader.common.secure import SecureString

from breezy.adapters.polymarket_us.errors import (
    CredentialConfigError,
    CredentialSerializationError,
)
from breezy.adapters.polymarket_us.redaction import REDACTED
from breezy.adapters.polymarket_us.secure import RedactedSecureString

__all__ = [
    "CredentialConfigError",
    "CredentialSerializationError",
    "PolymarketUSCredentials",
    "PolymarketUSSecretsRefConfig",
    "RedactedSecureString",
    "assert_config_type_excludes_secrets",
]


class PolymarketUSSecretsRefConfig(NautilusConfig, frozen=True):
    """Serializable references to runtime Polymarket.us credential sources."""

    key_id_env_var: str = "POLYMARKET_US_KEY_ID"
    secret_key_env_var: str = "POLYMARKET_US_SECRET_KEY"
    secret_key_file_env_var: str = "POLYMARKET_US_SECRET_KEY_FILE"

    def __post_init__(self) -> None:
        _require_env_name(self.key_id_env_var, field="key_id_env_var")
        _require_env_name(self.secret_key_env_var, field="secret_key_env_var")
        _require_env_name(self.secret_key_file_env_var, field="secret_key_file_env_var")


@dataclass(frozen=True, slots=True)
class PolymarketUSCredentials:
    """Runtime-only Polymarket.us credentials.

    Both fields are :class:`RedactedSecureString` -- Breezy's subclass of
    Nautilus's ``SecureString`` -- and the object is deliberately not a
    NautilusConfig. ``__post_init__`` REFUSES a bare ``SecureString``: the base
    class renders ``value[:4] + "..." + value[-4:]``
    (``nautilus_trader/common/secure.py:100-102``), and any path that reaches a
    field object directly -- ``dataclasses.asdict`` most notably -- walks past
    the container's ``__repr__`` and renders through it. Requiring the subclass
    is what makes the redaction structural rather than opt-in.

    ``__repr__`` is still hand-written and still load-bearing: the generated
    dataclass repr would name each field's value, and defence in depth means
    the container does not rely solely on the field type.
    """

    key_id: RedactedSecureString
    secret_key: RedactedSecureString

    def __repr__(self) -> str:
        return f"PolymarketUSCredentials(key_id={REDACTED}, secret_key={REDACTED})"

    # -- Serialisation refusal (review items 1 and 2) ----------------------
    #
    # ``__repr__`` above and the ``RedactedSecureString`` field type guard the
    # *rendering* seam only. Serialisation bypasses both and is strictly worse:
    # the underlying ``SecureString`` holds the
    # plaintext in ``_value`` plus a second copy in the ``_bytes`` bytearray
    # and defines no reduction hook (``nautilus_trader/common/secure.py``
    # ``:44-52``), so a pickled credential carries the FULL Ed25519 secret in
    # cleartext, and ``dataclasses.asdict`` -- which recurses through
    # ``copy.deepcopy`` -- yields raw SecureStrings whose own ``__repr__``
    # republishes the first/last four characters.
    #
    # Nautilus is IMMUTABLE, so SecureString is never patched; the refusal is
    # interposed here, on Breezy's own container.
    # These RAISE rather than emitting a redacted placeholder: a placeholder
    # would round-trip into a silently broken credential failing far from its
    # cause, and there is no legitimate reason to transport a credential --
    # it is loaded from the environment, in-process, at startup.

    def __reduce__(self) -> tuple[Any, ...]:
        """Refuse pickling on every protocol (also covers ``copy.deepcopy``)."""
        raise CredentialSerializationError(
            "PolymarketUSCredentials must never be pickled: the underlying "
            "SecureString stores the Ed25519 secret in cleartext and would be "
            "serialised verbatim. Pass the credential object itself, or "
            "re-load it from the environment in the target process."
        )

    def __getstate__(self) -> Any:
        """Refuse state extraction (``copy.copy``, ``__reduce_ex__`` fallback)."""
        raise CredentialSerializationError(
            "PolymarketUSCredentials exposes no serialisable state: its "
            "SecureString fields hold the Ed25519 secret in cleartext."
        )

    def __copy__(self) -> PolymarketUSCredentials:
        raise CredentialSerializationError(
            "PolymarketUSCredentials must not be copied; it is immutable, so "
            "share the instance instead."
        )

    def __deepcopy__(self, memo: dict[int, Any]) -> PolymarketUSCredentials:
        """Refuse deep-copying.

        ``dataclasses.asdict`` never reaches this hook -- it recurses into field
        values via ``getattr`` -- which is why the fields are
        ``RedactedSecureString``. This guard covers direct ``copy.deepcopy``.
        """
        raise CredentialSerializationError(
            "PolymarketUSCredentials must not be deep-copied. This also blocks "
            "any direct copy of the credential graph. Render credentials with "
            "breezy.adapters.polymarket_us.redaction.redact_secure."
        )

    def __post_init__(self) -> None:
        if not isinstance(self.key_id, RedactedSecureString):
            raise TypeError(
                "key_id must be a RedactedSecureString; a bare SecureString "
                "renders the first and last four characters of its value"
            )
        if not isinstance(self.secret_key, RedactedSecureString):
            raise TypeError(
                "secret_key must be a RedactedSecureString; a bare SecureString "
                "renders the first and last four characters of its value"
            )
        if not self.key_id.get_value():
            raise CredentialConfigError("key_id must not be empty")
        if not self.secret_key.get_value():
            raise CredentialConfigError("secret_key must not be empty")

    def is_complete(self) -> bool:
        """Return True when both credential fields are present and uncleared."""
        try:
            return bool(self.key_id.get_value()) and bool(self.secret_key.get_value())
        except ValueError:
            return False


def assert_config_type_excludes_secrets(config_type: type[NautilusConfig]) -> None:
    """Fail if a NautilusConfig subclass can directly carry secret material."""
    if not issubclass(config_type, NautilusConfig):
        raise TypeError("config_type must be a NautilusConfig subclass")
    hints = get_type_hints(config_type)
    for field, annotation in hints.items():
        if _annotation_contains_secret_type(annotation):
            raise CredentialConfigError(
                f"{config_type.__name__}.{field} must not carry secret-bearing values"
            )


def _annotation_contains_secret_type(annotation: Any) -> bool:
    if annotation is PolymarketUSCredentials:
        return True
    # Any SecureString subclass counts -- RedactedSecureString included, and
    # any future one -- so the ban cannot be sidestepped by declaring a
    # subclass on a config field.
    if isinstance(annotation, type) and issubclass(annotation, SecureString):
        return True
    origin = get_origin(annotation)
    if origin is None:
        return False
    return any(_annotation_contains_secret_type(arg) for arg in get_args(annotation))


def _require_env_name(value: str, *, field: str) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field} must be str")
    if not value:
        raise CredentialConfigError(f"{field} must not be empty")
    if value.strip() != value:
        raise CredentialConfigError(f"{field} must not contain surrounding whitespace")
    if "=" in value or "\x00" in value:
        raise CredentialConfigError(f"{field} is not a valid environment variable name")


assert_config_type_excludes_secrets(PolymarketUSSecretsRefConfig)
