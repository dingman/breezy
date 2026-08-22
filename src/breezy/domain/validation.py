"""Field guards shared by Breezy's record types.

These are deliberately *structural* checks -- the invariants a record must satisfy
to be internally coherent and safely encodable to Arrow. Physical-plausibility
bounds on parsed weather values (max <= 130 F, min >= -100 F, plausible day-over-day
deltas) belong to the normalization layer, which runs before a record is built.

They are plain module-level functions rather than a shared base class on purpose:
Breezy record classes never inherit from one another.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

_HEX_DIGEST = re.compile(r"\A[0-9a-f]{64}\Z")


def require_text(value: Any, name: str) -> str:
    """Return `value` if it is a non-empty `str`, else raise."""
    if not isinstance(value, str):
        raise TypeError(f"`{name}` must be a `str`, was {type(value).__name__}")

    if not value.strip():
        raise ValueError(f"`{name}` must be a non-empty string")

    return value


def require_optional_text(value: Any, name: str) -> str | None:
    """Return `value` if it is `None` or a non-empty `str`, else raise."""
    if value is None:
        return None

    return require_text(value, name)


def require_int(value: Any, name: str) -> int:
    """Return `value` if it is an `int`, else raise.

    `bool` is rejected explicitly: it is an `int` subclass, and a stray `True`
    would encode as ``1`` in an ``int64`` column without complaint.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"`{name}` must be an `int`, was {type(value).__name__}")

    return value


def require_optional_int(value: Any, name: str) -> int | None:
    if value is None:
        return None

    return require_int(value, name)


def require_optional_float(value: Any, name: str) -> float | None:
    """Return `value` coerced to `float`, or `None`.

    Coercion is explicit so an `int` input cannot make an otherwise identical
    record fail an equality check after an Arrow ``double`` round-trip.
    """
    if value is None:
        return None

    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"`{name}` must be a real number, was {type(value).__name__}")

    return float(value)


def require_bool(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"`{name}` must be a `bool`, was {type(value).__name__}")

    return value


def require_pure_date(value: Any, name: str) -> dt.date:
    """Return `value` if it is exactly a `datetime.date`, else raise.

    `datetime.datetime` subclasses `datetime.date`, so an `isinstance` check
    accepts one and Arrow's ``date32`` then silently discards the time component
    -- turning a timezone-bearing instant into a climate day with no warning.
    """
    if type(value) is not dt.date:
        raise TypeError(
            f"`{name}` must be exactly a `datetime.date` "
            f"(not `{type(value).__name__}`); a climate day has no time component",
        )

    return value


def require_optional_pure_date(value: Any, name: str) -> dt.date | None:
    if value is None:
        return None

    return require_pure_date(value, name)


def require_hex_digest(value: Any, name: str) -> str:
    """Return `value` if it is a 64-character lowercase hex SHA-256 digest."""
    if not isinstance(value, str) or not _HEX_DIGEST.match(value):
        raise ValueError(
            f"`{name}` must be a 64-character lowercase hex SHA-256 digest, was {value!r}",
        )

    return value
