"""Exact-parse wire validators for autonomy records (ARCH-0 AC 5).

Every refusal raises :class:`WireRefused` carrying a member of the closed
:class:`WireRefusalReason`. Records serialise through explicit ``to_wire`` and
``from_wire`` methods; ``dataclasses.asdict`` and ``astuple`` are never used.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

from breezy.persistence.autonomy.canonical import CanonicalTypeError, decimal_str

SHA256_RE: Final[re.Pattern[str]] = re.compile(r"^[0-9a-f]{64}\Z")
#: Kept equal to ``trial_day_latch.FAMILY_ID_PATTERN`` (test-asserted; not imported: layering).
FAMILY_ID_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_-]{1,64}\Z")

#: Schema ids a parsed record may carry. Grows as record types land.
ACCEPTED_SCHEMAS: Final[frozenset[str]] = frozenset(
    {
        "demand/v1",
        "drill_marker/v1",
        "journal/v1",
        "lineage/v1",
        "refit_run/v1",
        "registry/v1",
        "registry_export/v1",
        "root/v1",
        "verdict/v1",
    }
)


class WireRefusalReason(StrEnum):
    MALFORMED_JSON = "malformed_json"
    NOT_AN_OBJECT = "not_an_object"
    DUPLICATE_KEY = "duplicate_key"
    NON_FINITE_NUMBER = "non_finite_number"
    FLOAT_TOKEN = "float_token"
    MISSING_KEY = "missing_key"
    UNKNOWN_KEY = "unknown_key"
    WRONG_TYPE = "wrong_type"
    BOOL_AS_INT = "bool_as_int"
    UNKNOWN_SCHEMA = "unknown_schema"
    BAD_VALUE = "bad_value"


class WireRefused(ValueError):
    """A wire record was refused; ``reason`` is machine-readable."""

    def __init__(self, reason: WireRefusalReason, detail: str = "") -> None:
        super().__init__(f"{reason.value}: {detail}" if detail else reason.value)
        self.reason = reason
        self.detail = detail


def _no_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in pairs:
        if key in out:
            raise WireRefused(WireRefusalReason.DUPLICATE_KEY, key)
        out[key] = value
    return out


def _refuse_constant(token: str) -> object:
    raise WireRefused(WireRefusalReason.NON_FINITE_NUMBER, token)


def _refuse_float(token: str) -> object:
    raise WireRefused(WireRefusalReason.FLOAT_TOKEN, token)


def parse_json_exact(raw: bytes | str) -> dict[str, object]:
    """Parse one JSON object, refusing anything ambiguous or inexact."""
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        parsed = json.loads(
            text,
            object_pairs_hook=_no_duplicates,
            parse_float=_refuse_float,
            parse_constant=_refuse_constant,
        )
    except WireRefused:
        raise
    except (ValueError, RecursionError) as exc:
        raise WireRefused(WireRefusalReason.MALFORMED_JSON, type(exc).__name__) from exc
    if not isinstance(parsed, dict):
        raise WireRefused(WireRefusalReason.NOT_AN_OBJECT, type(parsed).__name__)
    if "schema" in parsed:
        schema = parsed["schema"]
        if not isinstance(schema, str) or schema not in ACCEPTED_SCHEMAS:
            raise WireRefused(WireRefusalReason.UNKNOWN_SCHEMA, repr(schema)[:80])
    return parsed


def require_exact_keys(
    obj: Mapping[str, object],
    *,
    required: Collection[str],
    optional: Collection[str] = (),
) -> None:
    missing = sorted(set(required) - obj.keys())
    if missing:
        raise WireRefused(WireRefusalReason.MISSING_KEY, ",".join(missing))
    unknown = sorted(obj.keys() - set(required) - set(optional))
    if unknown:
        raise WireRefused(WireRefusalReason.UNKNOWN_KEY, ",".join(unknown))


def _get(obj: Mapping[str, object], key: str) -> object:
    if key not in obj:
        raise WireRefused(WireRefusalReason.MISSING_KEY, key)
    return obj[key]


def require_str(obj: Mapping[str, object], key: str) -> str:
    value = _get(obj, key)
    if not isinstance(value, str):
        raise WireRefused(WireRefusalReason.WRONG_TYPE, key)
    return value


def require_int(obj: Mapping[str, object], key: str) -> int:
    value = _get(obj, key)
    if isinstance(value, bool):
        raise WireRefused(WireRefusalReason.BOOL_AS_INT, key)
    if not isinstance(value, int):
        raise WireRefused(WireRefusalReason.WRONG_TYPE, key)
    return value


def require_bool(obj: Mapping[str, object], key: str) -> bool:
    value = _get(obj, key)
    if not isinstance(value, bool):
        raise WireRefused(WireRefusalReason.WRONG_TYPE, key)
    return value


def require_ns(obj: Mapping[str, object], key: str) -> int:
    value = require_int(obj, key)
    if value < 0:
        raise WireRefused(WireRefusalReason.BAD_VALUE, key)
    return value


def require_sha256(obj: Mapping[str, object], key: str) -> str:
    value = require_str(obj, key)
    if SHA256_RE.fullmatch(value) is None:
        raise WireRefused(WireRefusalReason.BAD_VALUE, key)
    return value


def require_enum(obj: Mapping[str, object], key: str, *, allowed: Collection[str]) -> str:
    value = require_str(obj, key)
    if value not in allowed:
        raise WireRefused(WireRefusalReason.BAD_VALUE, key)
    return value


def require_decimal_str(obj: Mapping[str, object], key: str) -> Decimal:
    """A ``Decimal`` from a string that is already in canonical ``decimal_str`` form."""
    text = require_str(obj, key)
    try:
        value = Decimal(text)
        canonical = decimal_str(value)
    except (InvalidOperation, CanonicalTypeError) as exc:
        raise WireRefused(WireRefusalReason.BAD_VALUE, key) from exc
    if canonical != text:
        raise WireRefused(WireRefusalReason.BAD_VALUE, key)
    return value
