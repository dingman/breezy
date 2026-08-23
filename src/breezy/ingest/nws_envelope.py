"""Parse the api.weather.gov JSON envelopes into typed provenance fields.

PURE module: no I/O, no clock access, no `httpx`/`nautilus_trader` import, no
global state. This module closes the gap between `ingest.http.FetchResult`
(the raw HTTP body) and `ingest.records.build_raw_product` (which requires
`product_uuid`, `product_code`, `issuing_office`, `wmo_collective_id`,
`awips_pil`, `wmo_bbb_token`, `issuance_time_ns` and `product_text` as
separate, already-typed arguments): nothing else parses the NWS JSON
envelope into those fields.

Two envelope shapes, two parsers
---------------------------------
`GET /products/types/CLI/locations/{loc}` (the discovery list) returns a
top-level `"@graph"` array of metadata-only entries -- no product body.
`GET /products/{id}` (a single product) returns one object with the same
metadata keys plus `"productText"`, the verbatim product body.
:func:`parse_discovery_list` and :func:`parse_product_envelope` mirror that
split rather than sharing one polymorphic entry point, so a caller can never
accidentally treat a discovery entry as if it carried a body.

Fail closed, never guess
-------------------------
Every field this module returns is either read verbatim from the payload
under a validated type and shape, or explicitly `None` because the source
JSON never carries it. Nothing is defaulted, normalised, or inferred:

* A `product_uuid` is matched against the canonical UUID shape and returned
  **byte-identical**, never round-tripped through `uuid.UUID` -- the same
  rule `ingest.http` follows for the same reason, because this value is a
  settlement lookup key.
* A missing, `None`, or wrong-typed required field raises
  :class:`NwsEnvelopeFieldError` -- never a default, never a silent skip.
* A timestamp with no UTC offset (naive) raises
  :class:`NwsEnvelopeTimestampError` rather than being assumed to be UTC:
  the assumption would be silently wrong the first time it wasn't.
* The payload's node count and nesting depth are capped and checked
  *before* any field is walked out of it, so a pathological or hostile
  envelope is rejected in bounded work rather than walked arbitrarily deep.
* An empty `"@graph"` list is a valid, empty result (nothing has been
  published yet); a **missing** `"@graph"` key is a structural error --
  those are different claims about the payload and must not collapse.

`awips_pil` and `wmo_bbb_token` are **not** derivable from either JSON
envelope api.weather.gov actually serves (verified live against the real
API): neither key appears in a discovery entry or a product body. Both are
themselves line 3 and the line-2 BBB token *of the product text*, which is
`breezy.normalize.cli_parse`'s job to extract, not this module's. Rather
than reimplement that parse here (a second, divergent copy of the same
extraction) or invent placeholder text, :func:`parse_product_envelope`
reads the two keys defensively -- `None` when absent, exactly as observed
against the real API today -- and never fabricates a value.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    "DEFAULT_MAX_GRAPH_ITEMS",
    "DiscoveryEntry",
    "NwsEnvelopeError",
    "NwsEnvelopeFieldError",
    "NwsEnvelopeStructureError",
    "NwsEnvelopeTimestampError",
    "NwsEnvelopeUuidError",
    "ProductEnvelope",
    "parse_discovery_list",
    "parse_iso8601_to_ns",
    "parse_product_envelope",
]

_EPOCH: Final[dt.datetime] = dt.datetime(1970, 1, 1, tzinfo=dt.UTC)
_NS_PER_SECOND: Final[int] = 1_000_000_000
_NS_PER_MICROSECOND: Final[int] = 1_000

DEFAULT_MAX_GRAPH_ITEMS: Final[int] = 200
"""A real discovery list for one CLI location runs to a handful of entries
(NWS purges old ones); this gives generous headroom while still rejecting a
pathologically large list cheaply."""

MAX_JSON_DEPTH: Final[int] = 20
"""Real envelopes nest at most two or three levels deep (`{"@graph": [{...}]}`
or a flat product object); this rejects a deeply-nested payload designed to
exhaust a naive recursive walk, well before any field extraction runs."""

MAX_JSON_NODES: Final[int] = 10_000
"""Total dict/list/scalar node count across the whole payload. A real
discovery list at `DEFAULT_MAX_GRAPH_ITEMS` entries with a dozen scalar
fields each runs to a few thousand nodes at most; this caps the walk cost
of a payload before any field is read out of it."""

# A product id / discovery-entry `"id"` as api.weather.gov assigns it: a
# canonical UUID. Matched WITHOUT normalising -- see `ingest.http`'s
# `_PRODUCT_ID_PATTERN` docstring for why: the id returned here must be
# byte-identical to the id fetched and the id recorded as provenance, and
# round-tripping through `uuid.UUID` would silently accept and rewrite
# non-canonical forms (`urn:uuid:`, braces).
_UUID_PATTERN = re.compile(
    r"\A[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\Z"
)


class NwsEnvelopeError(ValueError):
    """Base class for every reason an NWS JSON envelope could not be parsed."""


class NwsEnvelopeStructureError(NwsEnvelopeError):
    """The payload's shape is wrong: missing/mistyped `@graph`, or it
    exceeds the structural node-count or nesting-depth cap."""


class NwsEnvelopeFieldError(NwsEnvelopeError):
    """A required field is missing, `None`, or the wrong type."""


class NwsEnvelopeUuidError(NwsEnvelopeFieldError):
    """A required id field is not a canonical UUID string."""


class NwsEnvelopeTimestampError(NwsEnvelopeFieldError):
    """A timestamp field is naive (no UTC offset) or is not valid ISO-8601."""


@dataclass(frozen=True, slots=True)
class DiscoveryEntry:
    """One entry of a discovery list's `"@graph"` array."""

    product_uuid: str
    product_code: str
    issuing_office: str
    wmo_collective_id: str
    issuance_time_ns: int


@dataclass(frozen=True, slots=True)
class ProductEnvelope:
    """A single fetched product's JSON envelope, parsed to typed fields."""

    product_uuid: str
    product_code: str
    issuing_office: str
    wmo_collective_id: str
    issuance_time_ns: int
    product_text: str
    awips_pil: str | None
    wmo_bbb_token: str | None


def parse_iso8601_to_ns(value: str) -> int:
    """Parse a timezone-aware ISO-8601 timestamp into UNIX nanoseconds.

    Raises :class:`NwsEnvelopeTimestampError` if `value` cannot be parsed as
    ISO-8601, or if it parses but carries no UTC offset (a naive timestamp).
    A naive timestamp is refused rather than assumed to be UTC: NWS
    timestamps are always offset-qualified in practice, so a naive value is
    itself a signal that something upstream is wrong, and assuming UTC would
    make that signal silent.
    """
    try:
        parsed = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise NwsEnvelopeTimestampError(
            f"could not parse {value!r} as an ISO-8601 timestamp"
        ) from exc

    if parsed.utcoffset() is None:
        raise NwsEnvelopeTimestampError(
            f"timestamp {value!r} is naive (carries no UTC offset); refusing to "
            "assume UTC"
        )

    delta = parsed - _EPOCH
    return (delta.days * 86_400 + delta.seconds) * _NS_PER_SECOND + (
        delta.microseconds * _NS_PER_MICROSECOND
    )


def _enforce_bounds(payload: Any) -> None:
    """Cap total node count and nesting depth before any field is walked.

    Raises :class:`NwsEnvelopeStructureError` on the first violation found.
    Runs as a single pre-pass, ahead of every field-extraction helper below.
    """
    counter = [0]
    _walk_bounds(payload, depth=0, counter=counter)


def _walk_bounds(node: Any, *, depth: int, counter: list[int]) -> None:
    counter[0] += 1
    if counter[0] > MAX_JSON_NODES:
        raise NwsEnvelopeStructureError(
            f"payload exceeds the {MAX_JSON_NODES}-node structural cap"
        )
    if depth > MAX_JSON_DEPTH:
        raise NwsEnvelopeStructureError(
            f"payload exceeds the {MAX_JSON_DEPTH}-level nesting-depth cap"
        )
    if isinstance(node, Mapping):
        for child in node.values():
            _walk_bounds(child, depth=depth + 1, counter=counter)
    elif isinstance(node, list):
        for child in node:
            _walk_bounds(child, depth=depth + 1, counter=counter)


def _require_str(payload: Mapping[str, Any], key: str, *, context: str) -> str:
    if key not in payload or payload[key] is None:
        raise NwsEnvelopeFieldError(f"{context}: missing required field {key!r}")
    value = payload[key]
    if not isinstance(value, str):
        raise NwsEnvelopeFieldError(
            f"{context}: field {key!r} must be a string, got {type(value).__name__}"
        )
    if value == "":
        raise NwsEnvelopeFieldError(f"{context}: field {key!r} must not be empty")
    return value


def _require_uuid(payload: Mapping[str, Any], key: str, *, context: str) -> str:
    value = _require_str(payload, key, context=context)
    if _UUID_PATTERN.match(value) is None:
        raise NwsEnvelopeUuidError(
            f"{context}: field {key!r} is not a canonical UUID string"
        )
    return value


def _optional_str(payload: Mapping[str, Any], key: str, *, context: str) -> str | None:
    """Return the string at `key`, or `None` when absent or explicitly null.

    Unlike :func:`_require_str`, absence is not an error -- `awips_pil` and
    `wmo_bbb_token` genuinely do not appear in either NWS JSON envelope
    today. A value that *is* present but is neither a string nor `None`
    still raises: that shape has never been observed and is not silently
    accepted.
    """
    if key not in payload:
        return None
    value = payload[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise NwsEnvelopeFieldError(
            f"{context}: field {key!r} must be a string or null when present, "
            f"got {type(value).__name__}"
        )
    return value


def _parse_metadata(payload: Mapping[str, Any], *, context: str) -> tuple[str, str, str, str, int]:
    """Extract the five metadata fields shared by both envelope shapes."""
    product_uuid = _require_uuid(payload, "id", context=context)
    product_code = _require_str(payload, "productCode", context=context)
    issuing_office = _require_str(payload, "issuingOffice", context=context)
    wmo_collective_id = _require_str(payload, "wmoCollectiveId", context=context)
    issuance_time_ns = parse_iso8601_to_ns(
        _require_str(payload, "issuanceTime", context=context)
    )
    return product_uuid, product_code, issuing_office, wmo_collective_id, issuance_time_ns


def parse_discovery_list(
    payload: Mapping[str, Any], *, max_items: int = DEFAULT_MAX_GRAPH_ITEMS
) -> tuple[DiscoveryEntry, ...]:
    """Parse a discovery-list response's `"@graph"` array into entries.

    An empty `"@graph"` list is a valid result (nothing has been published
    for this location yet) and returns an empty tuple. A **missing**
    `"@graph"` key is a different claim -- the response is not shaped like a
    discovery list at all -- and raises :class:`NwsEnvelopeStructureError`.

    Raises :class:`NwsEnvelopeStructureError` if the payload exceeds the
    structural node/depth caps, if `"@graph"` is missing or not a list, if
    it has more than `max_items` entries, or if any entry is not an object.
    Raises :class:`NwsEnvelopeFieldError` (or the more specific
    :class:`NwsEnvelopeUuidError` / :class:`NwsEnvelopeTimestampError`) if an
    entry is missing a required field or the field is malformed.
    """
    _enforce_bounds(payload)

    if "@graph" not in payload:
        raise NwsEnvelopeStructureError("payload is missing the required '@graph' key")

    graph = payload["@graph"]
    if not isinstance(graph, list):
        raise NwsEnvelopeStructureError(
            f"'@graph' must be a list, got {type(graph).__name__}"
        )
    if len(graph) > max_items:
        raise NwsEnvelopeStructureError(
            f"'@graph' has {len(graph)} entries, exceeding the {max_items}-item cap"
        )

    entries = []
    for index, item in enumerate(graph):
        if not isinstance(item, Mapping):
            raise NwsEnvelopeStructureError(
                f"'@graph[{index}]' must be an object, got {type(item).__name__}"
            )
        context = f"'@graph[{index}]'"
        product_uuid, product_code, issuing_office, wmo_collective_id, issuance_time_ns = (
            _parse_metadata(item, context=context)
        )
        entries.append(
            DiscoveryEntry(
                product_uuid=product_uuid,
                product_code=product_code,
                issuing_office=issuing_office,
                wmo_collective_id=wmo_collective_id,
                issuance_time_ns=issuance_time_ns,
            )
        )
    return tuple(entries)


def parse_product_envelope(payload: Mapping[str, Any]) -> ProductEnvelope:
    """Parse a single-product response into a :class:`ProductEnvelope`.

    Raises :class:`NwsEnvelopeStructureError` if the payload exceeds the
    structural node/depth caps. Raises :class:`NwsEnvelopeFieldError` (or
    the more specific :class:`NwsEnvelopeUuidError` /
    :class:`NwsEnvelopeTimestampError`) if a required field is missing,
    `None`, or the wrong type.

    `awips_pil` and `wmo_bbb_token` are read defensively and are `None`
    whenever the payload does not carry them -- which is every payload
    api.weather.gov actually serves today (see the module docstring). They
    are never derived from `product_text` here.
    """
    _enforce_bounds(payload)
    context = "product envelope"
    product_uuid, product_code, issuing_office, wmo_collective_id, issuance_time_ns = (
        _parse_metadata(payload, context=context)
    )
    product_text = _require_str(payload, "productText", context=context)
    awips_pil = _optional_str(payload, "awipsIdentifier", context=context)
    wmo_bbb_token = _optional_str(payload, "wmoBBB", context=context)

    return ProductEnvelope(
        product_uuid=product_uuid,
        product_code=product_code,
        issuing_office=issuing_office,
        wmo_collective_id=wmo_collective_id,
        issuance_time_ns=issuance_time_ns,
        product_text=product_text,
        awips_pil=awips_pil,
        wmo_bbb_token=wmo_bbb_token,
    )
