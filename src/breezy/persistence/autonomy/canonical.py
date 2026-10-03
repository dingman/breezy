"""Canonical bytes for hashed and persisted autonomy records (ARCH-0 AC 6)."""

from __future__ import annotations

import hashlib
import json
from decimal import Context, Decimal
from typing import Final

MAX_DECIMAL_DIGITS: Final[int] = 38
MAX_DECIMAL_ADJUSTED: Final[int] = 18
#: Own context: the ambient one (28 digits) would silently round 29-38 digit values.
_NORMALIZE_CONTEXT: Final[Context] = Context(prec=MAX_DECIMAL_DIGITS)


class CanonicalTypeError(TypeError):
    """A value has no canonical byte form."""


def sha256_hex(data: bytes) -> str:
    """Lowercase hex SHA-256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def decimal_str(value: Decimal) -> str:
    """Canonical string of a finite, bounded ``Decimal``; zero is ``"0"``."""
    if not isinstance(value, Decimal):
        raise CanonicalTypeError(f"decimal_str needs a Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise CanonicalTypeError("decimal_str refuses NaN and Infinity")
    if len(value.as_tuple().digits) > MAX_DECIMAL_DIGITS:
        raise CanonicalTypeError(f"decimal_str refuses more than {MAX_DECIMAL_DIGITS} digits")
    if value.is_zero():
        return "0"
    if abs(value.adjusted()) > MAX_DECIMAL_ADJUSTED:
        raise CanonicalTypeError(f"decimal_str refuses |adjusted()| > {MAX_DECIMAL_ADJUSTED}")
    return format(value.normalize(_NORMALIZE_CONTEXT), "f")


def _check_str(text: str) -> str:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalTypeError("lone surrogate in string") from exc
    return text


def _plain(value: object, active: frozenset[int]) -> object:
    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, str):
        return _check_str(value)
    if isinstance(value, Decimal):
        return decimal_str(value)
    if not isinstance(value, list | tuple | dict):
        raise CanonicalTypeError(f"no canonical form for {type(value).__name__}")
    if id(value) in active:
        raise CanonicalTypeError("cyclic structure")
    inner = active | {id(value)}
    if isinstance(value, dict):
        out: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalTypeError(f"non-str key {type(key).__name__}")
            out[_check_str(key)] = _plain(item, inner)
        return out
    return [_plain(item, inner) for item in value]


def canonical_json(value: object) -> bytes:
    """Sorted, compact, UTF-8 JSON bytes of ``value``."""
    return json.dumps(
        _plain(value, frozenset()),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
