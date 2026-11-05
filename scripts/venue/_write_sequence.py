"""Helpers for the OP-SEQ bot-driven positive control (R-OP-SEQ) and R-6.5P.

Authority: ``docs/plans/OP_SEQ_BOT_POSITIVE_CONTROL_2026-09-04.md``,
"Converged peer review" section, items 1, 4, 6, 8 and 9.

**Zero venue egress.** No ``.post(``, no ``HttpClient``, no signing. This
module is imported BY the B4-exempt write-SIGNING probe script (the reverse
direction of the zero-importers pin ``find_probe_importers`` enforces on the
probe module itself) and never the other way around. Every signed request
stays in the probe file, which is the one deliberate, reviewed B4 exemption;
this module only
performs LOCAL disk writes (the artefact and its write-ahead marker), which
B4's write-egress scanner does not gate at all (it matches HTTP write verbs
and order-path strings, not ``os.open``). Keeping this module free of
``.post``/``HttpClient``/signing means it needs no B4 exemption of its own
and adds no cage row.

Covers: instrument selection, the GTC control-order body, both the legacy
(v1, 7-field) and v2 (13-field) closed document schemas and their artefact
writers, the write-ahead intent marker, and the three-way verdict
computation. Kept out of the 800-line probe file for exactly that reason --
none of it is write egress.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final

from breezy.adapters.polymarket_us import provider as _provider
from breezy.adapters.polymarket_us.config import PolymarketUSMarketDiscoveryConfig
from breezy.adapters.polymarket_us.errors import PolymarketUSError, VenuePayloadError
from breezy.adapters.polymarket_us.exec.submit_chain import ORDER_BODY_KEYS
from breezy.adapters.polymarket_us.provider import discovery_candidate_slugs

__all__ = [
    "CLOSED_NO",
    "CLOSED_YES_BOTH_VERBS",
    "CONTROL_ORDER_BODY_KEYS",
    "INCONCLUSIVE",
    "INTENT_MARKER_TOKEN",
    "MARKER_DOCUMENT_FIELDS",
    "PRIVATE_ARTIFACT_PREFIX",
    "PRIVATE_SHAPE_DIRECTORY",
    "PROBE_DOCUMENT_FIELDS",
    "SEQUENCE_DOCUMENT_FIELDS",
    "SHAPE_DIR_MODE",
    "SHAPE_FILE_MODE",
    "ArtifactSchemaError",
    "CollectingLog",
    "ProbeObservation",
    "ProbeRefusal",
    "SequenceObservation",
    "build_control_order_body",
    "classify_enumeration",
    "compute_verdict",
    "is_empty_open_orders",
    "json_top_level_type",
    "market_list_query",
    "observation_document",
    "probe_artifact_filename",
    "probe_intent_marker_filename",
    "render_probe_report",
    "render_sequence_report",
    "select_control_instrument",
    "sequence_artifact_filename",
    "sequence_document",
    "write_intent_marker",
    "write_probe_artifact",
    "write_sequence_artifact",
]


class CollectingLog:
    """A ``SupportsVenueLog`` that keeps lines instead of printing them."""

    __slots__ = ("lines",)

    def __init__(self) -> None:
        self.lines: list[str] = []

    def debug(self, message: str) -> None:
        self.lines.append(message)

    def info(self, message: str) -> None:
        self.lines.append(message)

    def warning(self, message: str) -> None:
        self.lines.append(message)

    def error(self, message: str) -> None:
        self.lines.append(message)


def is_empty_open_orders(body: bytes | None) -> bool | None:
    """Whether ``body`` decodes to ``{"orders": []}``.

    Checked ONCE, in memory, and never recorded (D1): the artefact carries
    the reason code this produced, never the list or its length. ``None``
    means the body could not be read as the expected shape at all, which the
    caller treats the same as "not proven empty".
    """
    if not body:
        return None
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    orders = payload.get("orders")
    if not isinstance(orders, list):
        return None
    return len(orders) == 0


def json_top_level_type(body: bytes | None) -> str | None:
    """The top-level JSON type name of ``body`` -- never its content."""
    if not body:
        return None
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return None
    return type(payload).__name__

#: Shared with the other R-5R/R-6.5P/R-OP-SEQ evidence: one place an operator looks.
PRIVATE_SHAPE_DIRECTORY: Final[Path] = Path("docs/evidence/venue/polymarket_us")
PRIVATE_ARTIFACT_PREFIX: Final[str] = "PRIVATE_"
SHAPE_DIR_MODE: Final[int] = 0o700
SHAPE_FILE_MODE: Final[int] = 0o600

_STAMP_CHARSET: Final[str] = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)


class ProbeRefusal(PolymarketUSError):
    """The hard safety gate refused this run before any write was attempted."""


class ArtifactSchemaError(PolymarketUSError):
    """A rendered artefact or marker does not match its closed schema."""


def _is_plain_token(value: str) -> bool:
    return bool(value) and all(character in _STAMP_CHARSET for character in value)


def _filename_suffix(stamp: str | None) -> str:
    if stamp is None:
        return ""
    if not _is_plain_token(stamp):
        raise ValueError("stamp must be a plain [A-Za-z0-9_-] token")
    return f"_{stamp}"


def _write_o_excl(path: Path, text: str) -> None:
    """The one ``O_EXCL``-under-``0700`` write primitive, shared by every artefact.

    Never silently overwrites: a re-probe carries a new stamp or it fails
    loudly.
    """
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, SHAPE_FILE_MODE)
    try:
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
    except BaseException:
        os.close(descriptor)
        raise
    with handle:
        handle.write(text)
    os.chmod(path, SHAPE_FILE_MODE)


# ==========================================================================
# v1 (legacy, R-6.5P) -- closed 7-field schema
# ==========================================================================

_ARTIFACT_TITLE: Final[str] = "breezy venue write-signing probe (value-free)"

#: The COMPLETE set of fields an artefact carries (L-8).
PROBE_DOCUMENT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "artifact",
        "preflight_status",
        "preflight_reason",
        "write_status",
        "write_response_type",
        "postflight_status",
        "postflight_reason",
    }
)


@dataclass(frozen=True, slots=True)
class ProbeObservation:
    """Everything the legacy probe may publish. Statuses and reason codes only."""

    preflight_status: int | None
    preflight_reason: str | None
    write_status: int | None
    write_response_type: str | None
    postflight_status: int | None
    postflight_reason: str | None


def observation_document(observation: ProbeObservation) -> dict[str, Any]:
    """The closed v1 document. Every field is a status, a reason code, or a type name."""
    document: dict[str, Any] = {
        "artifact": _ARTIFACT_TITLE,
        "preflight_status": observation.preflight_status,
        "preflight_reason": observation.preflight_reason,
        "write_status": observation.write_status,
        "write_response_type": observation.write_response_type,
        "postflight_status": observation.postflight_status,
        "postflight_reason": observation.postflight_reason,
    }
    if set(document) != PROBE_DOCUMENT_FIELDS:
        raise ArtifactSchemaError("the probe document does not match its closed schema")
    return document


def render_probe_report(observation: ProbeObservation) -> str:
    """Render the v1 artefact body. Deterministic: no timestamp, no digest."""
    return json.dumps(observation_document(observation), indent=2, sort_keys=True) + "\n"


def probe_artifact_filename(*, stamp: str | None = None) -> str:
    """``PRIVATE_``-prefixed filename, matching the ``.gitignore`` rule."""
    return f"{PRIVATE_ARTIFACT_PREFIX}write_signing_probe{_filename_suffix(stamp)}.json"


def write_probe_artifact(
    observation: ProbeObservation,
    *,
    directory: Path = PRIVATE_SHAPE_DIRECTORY,
    stamp: str | None = None,
) -> Path:
    """Render, re-verify the v1 schema, then write ``0600`` under a ``0700`` directory."""
    filename = probe_artifact_filename(stamp=stamp)
    if not filename.startswith(PRIVATE_ARTIFACT_PREFIX) or os.sep in filename:
        raise ArtifactSchemaError("refusing to write an artefact without the PRIVATE_ prefix")

    text = render_probe_report(observation)
    if set(json.loads(text)) != PROBE_DOCUMENT_FIELDS:
        raise ArtifactSchemaError("round-tripped document does not match the closed schema")

    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(SHAPE_DIR_MODE)
    path = directory / filename
    _write_o_excl(path, text)
    return path


# ==========================================================================
# Write-ahead intent marker (widened, converged review item 6)
# ==========================================================================

INTENT_MARKER_TOKEN: Final[str] = "WRITE_ATTEMPTED"

MARKER_DOCUMENT_FIELDS: Final[frozenset[str]] = frozenset(
    {"artifact", "paths", "written_at_utc", "marker"}
)


def probe_intent_marker_filename(*, stamp: str | None = None) -> str:
    """``PRIVATE_``-prefixed filename for the write-ahead intent marker."""
    return f"{PRIVATE_ARTIFACT_PREFIX}write_signing_probe_intent{_filename_suffix(stamp)}.json"


def write_intent_marker(
    *, directory: Path, stamp: str | None, paths: tuple[str, ...]
) -> Path:
    """Write-ahead marker, written IMMEDIATELY BEFORE the first write is issued.

    Value-free: the write PATHS (constants), a wall-clock timestamp, and the
    literal :data:`INTENT_MARKER_TOKEN`. Same ``0600``-under-``0700``,
    ``O_EXCL`` discipline as the final artefact.
    """
    filename = probe_intent_marker_filename(stamp=stamp)
    document = {
        "artifact": "breezy venue write-signing probe intent marker (value-free)",
        "paths": list(paths),
        "written_at_utc": dt.datetime.now(tz=dt.UTC).isoformat(),
        "marker": INTENT_MARKER_TOKEN,
    }
    if set(document) != MARKER_DOCUMENT_FIELDS:
        raise ArtifactSchemaError("the intent marker does not match its closed schema")
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(SHAPE_DIR_MODE)
    path = directory / filename
    _write_o_excl(path, text)
    return path


# ==========================================================================
# v2 (R-OP-SEQ) -- closed 13-field schema
# ==========================================================================

#: Safety floor (19 ticks above the $0.01 control) -- see the plan's "Why the
#: $0.20 floor" note. A safety floor, not a strategy parameter.
_CONTROL_ASK_FLOOR: Final[Decimal] = Decimal("0.20")
_CONTROL_TICK: Final[Decimal] = Decimal("0.01")
_CONTROL_MAX_MIN_QTY: Final[Decimal] = Decimal(1)
_CONTROL_PRICE: Final[Decimal] = Decimal("0.01")

_ORDER_TYPE_LIMIT: Final[str] = "ORDER_TYPE_LIMIT"
_TIF_GTC: Final[str] = "TIME_IN_FORCE_GOOD_TILL_CANCEL"
_OUTCOME_SIDE_YES: Final[str] = "OUTCOME_SIDE_YES"
_ORDER_ACTION_BUY: Final[str] = "ORDER_ACTION_BUY"
_MANUAL_AUTOMATIC: Final[str] = "MANUAL_ORDER_INDICATOR_AUTOMATIC"

#: The GTC control body's exact key set, derived from the shipped IOC body's
#: key set rather than recited -- ``synchronousExecution``/``maxBlockTime``
#: exist for the IOC block-until-done path and are dropped;
#: ``participateDontInitiate`` (maker-only, venue-enforced) is added.
#: ``ORDER_BODY_KEYS`` itself is never widened.
CONTROL_ORDER_BODY_KEYS: Final[frozenset[str]] = (
    ORDER_BODY_KEYS - {"synchronousExecution", "maxBlockTime"}
) | {"participateDontInitiate"}

CLOSED_YES_BOTH_VERBS: Final[str] = "CLOSED_YES_BOTH_VERBS"
CLOSED_NO: Final[str] = "CLOSED_NO"
INCONCLUSIVE: Final[str] = "INCONCLUSIVE"

_SEQUENCE_ARTIFACT_TITLE: Final[str] = (
    "breezy venue op-sequence bot-driven positive control probe (value-free)"
)

#: Schema v2, closed to exactly 13 fields (plan "Artefact" section, closed).
SEQUENCE_DOCUMENT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "artifact",
        "preflight_status",
        "preflight_reason",
        "selection_reason",
        "rest_status",
        "rest_reason",
        "enumeration_status",
        "enumeration_reason",
        "cancel_status",
        "cancel_response_type",
        "postflight_status",
        "postflight_reason",
        "verdict",
    }
)
assert len(SEQUENCE_DOCUMENT_FIELDS) == 13


@dataclass(frozen=True, slots=True)
class SequenceObservation:
    """Everything the sequence may publish. Statuses, reason codes, verdict."""

    preflight_status: int | None
    preflight_reason: str | None
    selection_reason: str | None
    rest_status: int | None
    rest_reason: str | None
    enumeration_status: int | None
    enumeration_reason: str | None
    cancel_status: int | None
    cancel_response_type: str | None
    postflight_status: int | None
    postflight_reason: str | None
    verdict: str


def sequence_document(observation: SequenceObservation) -> dict[str, Any]:
    """The closed v2 document. Every field is a status, reason code or verdict."""
    document: dict[str, Any] = {
        "artifact": _SEQUENCE_ARTIFACT_TITLE,
        "preflight_status": observation.preflight_status,
        "preflight_reason": observation.preflight_reason,
        "selection_reason": observation.selection_reason,
        "rest_status": observation.rest_status,
        "rest_reason": observation.rest_reason,
        "enumeration_status": observation.enumeration_status,
        "enumeration_reason": observation.enumeration_reason,
        "cancel_status": observation.cancel_status,
        "cancel_response_type": observation.cancel_response_type,
        "postflight_status": observation.postflight_status,
        "postflight_reason": observation.postflight_reason,
        "verdict": observation.verdict,
    }
    if set(document) != SEQUENCE_DOCUMENT_FIELDS:
        raise ArtifactSchemaError("the sequence document does not match its closed schema")
    return document


def render_sequence_report(observation: SequenceObservation) -> str:
    """Render the v2 artefact body. Deterministic: no timestamp, no digest."""
    return json.dumps(sequence_document(observation), indent=2, sort_keys=True) + "\n"


def sequence_artifact_filename(*, stamp: str | None = None) -> str:
    """``PRIVATE_``-prefixed filename for the v2 sequence artefact.

    A DISTINCT filename from :func:`probe_artifact_filename` (converged
    review item 8): the two schemas never collide on disk.
    """
    return f"{PRIVATE_ARTIFACT_PREFIX}write_sequence_probe{_filename_suffix(stamp)}.json"


def write_sequence_artifact(
    observation: SequenceObservation,
    *,
    directory: Path = PRIVATE_SHAPE_DIRECTORY,
    stamp: str | None = None,
) -> Path:
    """Render, re-verify the v2 schema, write ``0600``-under-``0700``, plus a ``.sha256`` sidecar.

    Its OWN filename builder and writer (converged review item 8) -- never
    shared with :func:`write_probe_artifact`.
    """
    filename = sequence_artifact_filename(stamp=stamp)
    if not filename.startswith(PRIVATE_ARTIFACT_PREFIX) or os.sep in filename:
        raise ArtifactSchemaError("refusing to write an artefact without the PRIVATE_ prefix")

    text = render_sequence_report(observation)
    if set(json.loads(text)) != SEQUENCE_DOCUMENT_FIELDS:
        raise ArtifactSchemaError("round-tripped document does not match the closed v2 schema")

    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(SHAPE_DIR_MODE)
    path = directory / filename
    _write_o_excl(path, text)

    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    sidecar_path = path.with_name(path.name + ".sha256")
    _write_o_excl(sidecar_path, f"{digest}  {path.name}\n")
    return path


def compute_verdict(
    *,
    rest_status: int | None,
    order_id_present: bool,
    enumeration_ok: bool,
    cancel_ok: bool,
    postflight_ok: bool,
) -> str:
    """Three-way verdict, never a free-text word.

    ``CLOSED_NO`` iff S3 401/403. ``CLOSED_YES_BOTH_VERBS`` iff S3
    200-with-id AND S4 enumerated-and-unfilled AND S5 ok AND S6 200-empty.
    Everything else is ``INCONCLUSIVE``.
    """
    if rest_status in (401, 403):
        return CLOSED_NO
    if rest_status == 200 and order_id_present and enumeration_ok and cancel_ok and postflight_ok:
        return CLOSED_YES_BOTH_VERBS
    return INCONCLUSIVE


def build_control_order_body(slug: str) -> dict[str, Any]:
    """The GTC BUY YES control body, built in-function from the slug only."""
    return {
        "marketSlug": slug,
        "type": _ORDER_TYPE_LIMIT,
        "price": {"value": f"{_CONTROL_PRICE:.2f}", "currency": "USD"},
        "quantity": 1,
        "tif": _TIF_GTC,
        "outcomeSide": _OUTCOME_SIDE_YES,
        "action": _ORDER_ACTION_BUY,
        "manualOrderIndicator": _MANUAL_AUTOMATIC,
        "participateDontInitiate": True,
    }


def market_list_query(discovery: PolymarketUSMarketDiscoveryConfig) -> dict[str, object]:
    """Page-1 query for ``GET /v1/markets``, in the provider's own shape.

    Mirrors ``PolymarketUSInstrumentProvider._query`` (offset 0 only -- one
    page, per the plan's "Page 1 only" ruling).
    """
    query: dict[str, object] = {
        "limit": discovery.limit,
        "offset": 0,
        "orderBy": discovery.order_by,
        "orderDirection": discovery.order_direction,
        "categories": discovery.categories,
    }
    if discovery.archived is not None:
        query["archived"] = discovery.archived
    if discovery.include_closed:
        return query
    if discovery.active is not None:
        query["active"] = discovery.active
    if discovery.closed is not None:
        query["closed"] = discovery.closed
    return query


def _decimal_field(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _decimal_amount(amount: Any) -> Decimal | None:
    if not isinstance(amount, Mapping):
        return None
    return _decimal_field(amount.get("value"))


def _markets_by_slug(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    markets = payload.get("markets")
    result: dict[str, Mapping[str, Any]] = {}
    if not isinstance(markets, list):
        return result
    for market in markets:
        if isinstance(market, Mapping):
            slug = market.get("slug")
            if isinstance(slug, str):
                result[slug] = market
    return result


def select_control_instrument(
    payload: Mapping[str, Any],
    *,
    city_codes: tuple[str, ...],
) -> str | None:
    """The lexicographically smallest eligible weather-bucket slug, or ``None``.

    ``VenuePayloadError`` from the shared candidate join is never a crash --
    it is exactly one more way to have zero eligible candidates. Eligibility
    (all required): not resolved/closed; ``bestAskQuote.value >= $0.20``;
    ``orderPriceMinTickSize == $0.01``; ``minimumTradeQty <= 1``. The slug
    grammar check is already applied by ``discovery_candidate_slugs`` itself.
    """
    try:
        slugs = discovery_candidate_slugs(payload, city_codes=city_codes)
    except VenuePayloadError:
        return None

    markets = _markets_by_slug(payload)
    eligible: list[str] = []
    for slug in slugs:
        market = markets.get(slug)
        if market is None:
            continue
        if _provider._resolved_reason(market) is not None:
            continue
        ask = _decimal_amount(market.get("bestAskQuote"))
        if ask is None or ask < _CONTROL_ASK_FLOOR:
            continue
        tick = _decimal_field(market.get("orderPriceMinTickSize"))
        if tick != _CONTROL_TICK:
            continue
        min_qty = _decimal_field(market.get("minimumTradeQty"))
        if min_qty is None or min_qty > _CONTROL_MAX_MIN_QTY:
            continue
        eligible.append(slug)

    if not eligible:
        return None
    return min(eligible)


def classify_enumeration(status: int | None, body: bytes | None, order_id: str) -> str:
    """Classify one enumeration read against ``order_id``.

    Returns ``"absent"`` (id not found, or the read itself is unusable),
    ``"filled"`` (found with ``cumQuantity > 0`` or a filled state), or
    ``"ok"`` (found, resting, unfilled). Never persists the id, the payload,
    or a count -- the caller maps this token to a value-free reason code.
    """
    if status != 200 or not body:
        return "absent"
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return "absent"
    if not isinstance(payload, Mapping):
        return "absent"
    orders = payload.get("orders")
    if not isinstance(orders, list):
        return "absent"
    match: Mapping[str, Any] | None = None
    for order in orders:
        if isinstance(order, Mapping) and order.get("id") == order_id:
            match = order
            break
    if match is None:
        return "absent"
    cum_quantity = match.get("cumQuantity")
    state = match.get("state")
    filled = (isinstance(cum_quantity, (int, float)) and cum_quantity > 0) or (
        state == "ORDER_STATE_FILLED"
    )
    return "filled" if filled else "ok"
