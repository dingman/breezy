"""Provably value-free capture of venue response SHAPES (EXEC SPINE R-1).

R-1 needs the shapes of the private portfolio-positions, account-balances and
open-orders endpoints. Those responses ARE the operator's financial position,
and the artefact lands next to a git-tracked evidence tree.

The endpoint labels themselves are NOT named here, in prose or otherwise:
barrier B4 rule V2 (``tests/unit/test_polymarket_us_readonly_guard.py:151``)
bans an order-path literal anywhere under ``src/`` or ``scripts/``, and a
barrier that must be silenced is a barrier that will be silenced. The label is
a caller argument, validated against a plain-path charset.

Two existing walkers were considered and rejected as unusable here:

* ``_frame_schema`` (``scripts/venue/polymarket_us_auth_smoke.py:954``) and
  the ``diagnose_frame_payload`` machinery it delegates to;
* ``_walk_structure`` (``breezy/adapters/polymarket_us/data.py:534-565``).

Both do two things this module must never do: they record ``str(value)`` into
``safe_values`` (``data.py:544``), and they interpolate raw dict keys into the
published path (``data.py:549``). Applied to a private endpoint the first
publishes the balance and the second publishes the portfolio -- because
``GetUserPositionsResponse.positions`` is ``dict[str, UserPosition]`` keyed by
market slug (SDK snapshot ``types/portfolio.py``). They are correct for public
market-data frames; they are not made safe by being pointed somewhere else.

The guarantee this module offers instead:

**The output is a function of the payload's STRUCTURE and its allowlisted KEY
NAMES only.** Two payloads that differ solely in scalar values -- of any
magnitude, length, or sign -- render byte-identical text. Concretely:

* ``str()`` is never called on a payload value. Values reach only
  ``isinstance`` checks; the emitted token comes from a closed vocabulary.
* ``int`` and ``float`` collapse to one ``number`` token, because "integral or
  not" is itself a disclosure about a balance.
* No length, digit count, exponent, list cardinality, or numeric "scale" is
  recorded. A type name is the maximum granularity.
* A key not on the SDK-derived allowlist never appears; it is folded into
  ``unrecognized_key_count``, an integer.
* ``verify_value_free`` re-checks the finished tree against that grammar and
  the writer refuses -- writing nothing -- if it fires. That check consults no
  credential list, unlike ``find_secret_leak_offsets``
  (``polymarket_us_auth_smoke.py:307``), which by construction cannot see
  money.

Artefacts are written ``0600`` in a ``0700`` directory under the ``PRIVATE_``
prefix, which ``.gitignore`` excludes via ``docs/evidence/venue/**/PRIVATE_*``.
The mode protects against another local user; only the ignore rule protects
against ``git add``.

This module performs NO I/O against the venue. It takes an already-decoded
payload and returns a description.

It lives under ``scripts/venue/`` rather than in the ``breezy`` package for
the same reason ``polymarket_us_auth_smoke.py`` does: it is operator tooling
that WRITES into ``docs/evidence/``, and
``tests/unit/test_probe_containment.py::test_no_module_under_src_reads_docs_evidence``
bans that path as a runtime constant anywhere under ``src/``. Nothing on the
trading path imports this.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

#: Directory the R-1 artefacts land in. Shared with the auth smoke's evidence
#: directory deliberately: one place an operator looks. Safety comes from the
#: filename prefix, not from a separate location.
PRIVATE_SHAPE_DIRECTORY: Final[Path] = Path("docs/evidence/venue/polymarket_us")

#: The prefix ``.gitignore`` keys on (``docs/evidence/venue/**/PRIVATE_*``).
PRIVATE_ARTIFACT_PREFIX: Final[str] = "PRIVATE_"

SHAPE_DIR_MODE: Final[int] = 0o700
SHAPE_FILE_MODE: Final[int] = 0o600

#: Depth cap. A pathological payload must not raise ``RecursionError`` inside
#: a capture the operator is running once, under supervision.
MAX_SHAPE_DEPTH: Final[int] = 24

#: The COMPLETE vocabulary of value-derived tokens this module can emit. Every
#: one is a type name; none is derived from a payload value.
SHAPE_TYPE_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "null",
        "bool",
        "number",
        "string",
        "object",
        "array",
        "mixed",
        "unsupported",
        "truncated",
    }
)

#: The COMPLETE set of structural field names in the emitted tree.
SHAPE_STRUCTURAL_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "type",
        "keys",
        "items",
        "variants",
        "unrecognized_key_count",
        "unrecognized_value",
    }
)

#: Key names that may be published VERBATIM. Derived mechanically from every
#: ``TypedDict`` field in the committed SDK snapshot under
#: ``docs/evidence/venue/polymarket_us/sdk_snapshot/`` -- these are schema
#: names the vendor chose, not anything the operator's account contains. The
#: derivation is re-run and asserted by
#: ``tests/unit/test_polymarket_us_shape_capture.py``
#: (``test_allowlist_equals_the_committed_sdk_typed_dict_fields``), so the list
#: cannot silently drift from, or grow beyond, the schema it claims to be.
SHAPE_ALLOWED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "abbreviation",
        "accountBalanceChange",
        "accountBalanceSubscriptionSnapshot",
        "accountBalanceSubscriptionUpdate",
        "acknowledged",
        "active",
        "activities",
        "afterPosition",
        "aggressor",
        "alias",
        "amount",
        "archived",
        "askDepth",
        "assetAvailable",
        "assetNotional",
        "avgPx",
        "awayIcon",
        "balance",
        "balanceReservation",
        "balances",
        "bankId",
        "beforePosition",
        "bestAsk",
        "bestBid",
        "bidDepth",
        "bids",
        "bips",
        "bodPosition",
        "buyingPower",
        "canceledOrderIds",
        "cashOrderQty",
        "cashValue",
        "closed",
        "colorPrimary",
        "commissionNotionalCollected",
        "commissionNotionalTotalCollected",
        "commissionsBasisPoints",
        "cost",
        "costBasis",
        "createTime",
        "creationTime",
        "cumQuantity",
        "currency",
        "currentBalance",
        "currentPrice",
        "cursor",
        "description",
        "destinationAccountName",
        "endTime",
        "eof",
        "error",
        "event",
        "eventSlug",
        "events",
        "execution",
        "executions",
        "expired",
        "featured",
        "goodTillTime",
        "heartbeat",
        "highPx",
        "homeIcon",
        "icon",
        "id",
        "insertTime",
        "intent",
        "isAggressor",
        "label",
        "lastPx",
        "lastShares",
        "lastTradePx",
        "lastUpdated",
        "league",
        "leagues",
        "leavesQuantity",
        "limit",
        "liquidity",
        "logo",
        "lowPx",
        "maker",
        "makerCommissionsBasisPoints",
        "manualOrderIndicator",
        "marginRequirement",
        "market",
        "marketData",
        "marketDataLite",
        "marketMetadata",
        "marketSlug",
        "marketSlugs",
        "markets",
        "maxBlockTime",
        "name",
        "netPosition",
        "nextCursor",
        "offers",
        "offset",
        "openInterest",
        "openOrders",
        "order",
        "orderRejectReason",
        "orderSubscriptionSnapshot",
        "orderSubscriptionUpdate",
        "orders",
        "outcome",
        "page",
        "participateDontInitiate",
        "pendingCredit",
        "pendingWithdrawals",
        "position",
        "positionResolution",
        "positionSubscriptionSnapshot",
        "positionSubscriptionUpdate",
        "positions",
        "price",
        "provider",
        "providerIds",
        "px",
        "qty",
        "qtyAvailable",
        "qtyBought",
        "qtySold",
        "quantity",
        "query",
        "realized",
        "realizedPnl",
        "record",
        "recurrence",
        "request",
        "requestId",
        "safeName",
        "series",
        "seriesIds",
        "settledAt",
        "settlementPrice",
        "sharesTraded",
        "side",
        "slippageTolerance",
        "slug",
        "slugs",
        "sortOrder",
        "sports",
        "startTime",
        "state",
        "stats",
        "status",
        "subscribe",
        "subscriptionType",
        "synchronousExecution",
        "tags",
        "taker",
        "team",
        "teamId",
        "teamIds",
        "teams",
        "text",
        "ticks",
        "tif",
        "title",
        "trade",
        "tradeId",
        "tradeTime",
        "transactTime",
        "transactionId",
        "transactions",
        "type",
        "types",
        "unsettledFunds",
        "unsubscribe",
        "updateTime",
        "value",
        "volume",
    }
)

#: Endpoint labels are constants chosen by the caller, never payload data.
#: Anything outside this charset is refused rather than sanitised, so a path
#: carrying a market slug or a query string cannot become a filename.
_ENDPOINT_PATTERN: Final[re.Pattern[str]] = re.compile(r"\A/[A-Za-z0-9/_-]*\Z")

_ARTIFACT_SUFFIX: Final[str] = ".shape.json"

_REPORT_TITLE: Final[str] = "breezy venue response shape capture (value-free)"

ShapeNode = dict[str, Any]

__all__ = [
    "MAX_SHAPE_DEPTH",
    "PRIVATE_ARTIFACT_PREFIX",
    "PRIVATE_SHAPE_DIRECTORY",
    "SHAPE_ALLOWED_KEYS",
    "SHAPE_DIR_MODE",
    "SHAPE_FILE_MODE",
    "SHAPE_STRUCTURAL_FIELDS",
    "SHAPE_TYPE_TOKENS",
    "ShapeLeakError",
    "describe_shape",
    "render_shape_report",
    "shape_artifact_filename",
    "verify_value_free",
    "write_shape_artifact",
]


class ShapeLeakError(RuntimeError):
    """A shape tree carried something outside the value-free grammar.

    Like ``EvidenceLeakError``, the message reports the offending LOCATION and
    kind only. Echoing the offending material would reproduce the leak in the
    traceback, the terminal scrollback, and any log that captured them.
    """


# ---------------------------------------------------------------------------
# Description
# ---------------------------------------------------------------------------


def describe_shape(payload: object, *, depth: int = 0) -> ShapeNode:
    """Describe ``payload`` as key names and value TYPES, nothing else.

    ``payload`` is inspected by ``isinstance`` only. No branch of this
    function -- or of anything it calls -- converts a payload value to text.
    """
    if depth > MAX_SHAPE_DEPTH:
        return {"type": "truncated"}

    if payload is None:
        return {"type": "null"}
    # Before ``int``: ``bool`` is an ``int`` subclass in Python.
    if isinstance(payload, bool):
        return {"type": "bool"}
    if isinstance(payload, int | float):
        # One token for both. "Is the balance integral?" is a fact about the
        # value, and a two-token encoding would disclose it.
        return {"type": "number"}
    if isinstance(payload, str):
        return {"type": "string"}
    if isinstance(payload, Mapping):
        return _describe_mapping(payload, depth=depth)
    if isinstance(payload, Sequence) and not isinstance(payload, bytes | bytearray):
        return _describe_sequence(payload, depth=depth)
    # Anything else (bytes, Decimal, a stray object) is named by category and
    # never rendered. Falling back to ``str(payload)`` here is exactly the
    # defect this module exists to avoid.
    return {"type": "unsupported"}


def _describe_mapping(payload: Mapping[Any, Any], *, depth: int) -> ShapeNode:
    keys: dict[str, ShapeNode] = {}
    unrecognized_count = 0
    unrecognized_value: ShapeNode | None = None

    for key, value in payload.items():
        child = describe_shape(value, depth=depth + 1)
        if isinstance(key, str) and key in SHAPE_ALLOWED_KEYS:
            existing = keys.get(key)
            keys[key] = child if existing is None else _union(existing, child)
            continue
        # The key itself is discarded here and never referenced again. A
        # slug-keyed positions map therefore contributes a count and a merged
        # VALUE shape -- which is the useful part -- and no portfolio.
        unrecognized_count += 1
        unrecognized_value = (
            child if unrecognized_value is None else _union(unrecognized_value, child)
        )

    node: ShapeNode = {
        "type": "object",
        "keys": keys,
        "unrecognized_key_count": unrecognized_count,
    }
    if unrecognized_value is not None:
        node["unrecognized_value"] = unrecognized_value
    return node


def _describe_sequence(payload: Sequence[Any], *, depth: int) -> ShapeNode:
    items: ShapeNode | None = None
    for value in payload:
        child = describe_shape(value, depth=depth + 1)
        items = child if items is None else _union(items, child)
    # No length is recorded: the number of open orders or positions is itself
    # financial information, and an empty list is reported as a bare ``array``.
    return {"type": "array"} if items is None else {"type": "array", "items": items}


# ---------------------------------------------------------------------------
# Union of two shapes
# ---------------------------------------------------------------------------


def _canonical(node: ShapeNode) -> str:
    return json.dumps(node, sort_keys=True, separators=(",", ":"))


def _union(left: ShapeNode, right: ShapeNode) -> ShapeNode:
    if left == right:
        return left

    left_type = left["type"]
    right_type = right["type"]

    if left_type == "object" and right_type == "object":
        return _union_objects(left, right)
    if left_type == "array" and right_type == "array":
        left_items = left.get("items")
        right_items = right.get("items")
        if left_items is None:
            return right
        if right_items is None:
            return left
        return {"type": "array", "items": _union(left_items, right_items)}
    if _is_scalar(left) and _is_scalar(right):
        tokens = sorted(set(left_type.split("|")) | set(right_type.split("|")))
        return {"type": "|".join(tokens)}
    return _union_mixed(left, right)


def _is_scalar(node: ShapeNode) -> bool:
    return node.keys() == {"type"} and node["type"] not in {"object", "array", "mixed"}


def _union_objects(left: ShapeNode, right: ShapeNode) -> ShapeNode:
    left_keys: dict[str, ShapeNode] = left["keys"]
    right_keys: dict[str, ShapeNode] = right["keys"]
    keys: dict[str, ShapeNode] = {}
    for name in set(left_keys) | set(right_keys):
        if name in left_keys and name in right_keys:
            keys[name] = _union(left_keys[name], right_keys[name])
        else:
            keys[name] = left_keys.get(name) or right_keys[name]

    node: ShapeNode = {
        "type": "object",
        "keys": keys,
        # MAX, not sum: a union describes "an element of this collection", so
        # the count answers "how many unrecognized keys can one carry".
        "unrecognized_key_count": max(
            left["unrecognized_key_count"], right["unrecognized_key_count"]
        ),
    }
    left_value = left.get("unrecognized_value")
    right_value = right.get("unrecognized_value")
    if left_value is not None and right_value is not None:
        node["unrecognized_value"] = _union(left_value, right_value)
    elif left_value is not None:
        node["unrecognized_value"] = left_value
    elif right_value is not None:
        node["unrecognized_value"] = right_value
    return node


def _union_mixed(left: ShapeNode, right: ShapeNode) -> ShapeNode:
    variants: list[ShapeNode] = []
    for node in (left, right):
        if node["type"] == "mixed":
            variants.extend(node["variants"])
        else:
            variants.append(node)

    merged: list[ShapeNode] = []
    for variant in variants:
        for index, existing in enumerate(merged):
            if _mergeable(existing, variant):
                merged[index] = _union(existing, variant)
                break
        else:
            merged.append(variant)

    if len(merged) == 1:
        return merged[0]
    # Sorted for determinism: two payloads whose values differ must not
    # produce a different ordering.
    merged.sort(key=_canonical)
    return {"type": "mixed", "variants": merged}


def _mergeable(left: ShapeNode, right: ShapeNode) -> bool:
    if _is_scalar(left) and _is_scalar(right):
        return True
    return left["type"] == right["type"] and left["type"] in {"object", "array"}


# ---------------------------------------------------------------------------
# Verification -- independent of any credential list
# ---------------------------------------------------------------------------


def verify_value_free(shape: Mapping[str, Any], *, path: str = "$") -> None:
    """Raise ``ShapeLeakError`` unless ``shape`` matches the closed grammar.

    The grammar admits exactly: the structural field names, the type-token
    vocabulary, allowlisted key names, and one integer (a key count). Nothing
    a venue can put in a response body has a way through it.
    """
    if not isinstance(shape, Mapping):
        raise ShapeLeakError(f"shape node at {path} is not a mapping")

    unknown = set(shape) - SHAPE_STRUCTURAL_FIELDS
    if unknown:
        raise ShapeLeakError(
            f"shape node at {path} carries {len(unknown)} field(s) outside the "
            f"value-free grammar; their names are deliberately not reproduced"
        )

    node_type = shape.get("type")
    if not isinstance(node_type, str):
        raise ShapeLeakError(f"shape node at {path} has no type token")
    if not set(node_type.split("|")) <= SHAPE_TYPE_TOKENS:
        raise ShapeLeakError(
            f"shape node at {path} carries a type token outside the closed "
            f"vocabulary; it is deliberately not reproduced"
        )

    keys = shape.get("keys")
    if keys is not None:
        if not isinstance(keys, Mapping):
            raise ShapeLeakError(f"shape node at {path} has a non-mapping `keys`")
        for name, child in keys.items():
            if not isinstance(name, str) or name not in SHAPE_ALLOWED_KEYS:
                raise ShapeLeakError(
                    f"shape node at {path} publishes a key name that is not on "
                    f"the SDK allowlist; it is deliberately not reproduced"
                )
            verify_value_free(child, path=f"{path}.{name}")

    count = shape.get("unrecognized_key_count")
    if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
        raise ShapeLeakError(f"shape node at {path} has a malformed key count")

    for field in ("items", "unrecognized_value"):
        child = shape.get(field)
        if child is not None:
            verify_value_free(child, path=f"{path}.{field}")

    variants = shape.get("variants")
    if variants is not None:
        if not isinstance(variants, list):
            raise ShapeLeakError(f"shape node at {path} has non-list `variants`")
        for index, variant in enumerate(variants):
            verify_value_free(variant, path=f"{path}.variants[{index}]")


# ---------------------------------------------------------------------------
# Rendering and writing
# ---------------------------------------------------------------------------


def _validate_endpoint(endpoint: str) -> str:
    if not _ENDPOINT_PATTERN.fullmatch(endpoint):
        raise ValueError(
            "endpoint label must be a plain path of [A-Za-z0-9/_-]; refusing "
            "a label that could carry payload-derived text"
        )
    return endpoint


def render_shape_report(*, endpoint: str, shape: Mapping[str, Any]) -> str:
    """Render the artefact body. Deterministic: no timestamp, no digest.

    Determinism is a security property here, not a convenience. It is what
    makes "two payloads differing only in magnitude produce byte-identical
    artefacts" an assertion a test can make. Capture provenance belongs in the
    filename or an operator note, never in a body that must be comparable.
    """
    _validate_endpoint(endpoint)
    verify_value_free(shape)
    document = {"artifact": _REPORT_TITLE, "endpoint": endpoint, "shape": shape}
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


def shape_artifact_filename(endpoint: str, *, stamp: str | None = None) -> str:
    """``PRIVATE_``-prefixed filename for ``endpoint``, matching the ignore rule."""
    _validate_endpoint(endpoint)
    label = endpoint.strip("/").replace("/", "_")
    suffix = ""
    if stamp is not None:
        if not re.fullmatch(r"[A-Za-z0-9_-]+", stamp):
            raise ValueError("stamp must be [A-Za-z0-9_-]")
        suffix = f"_{stamp}"
    return f"{PRIVATE_ARTIFACT_PREFIX}{label}{suffix}{_ARTIFACT_SUFFIX}"


def write_shape_artifact(
    *,
    endpoint: str,
    payload: object,
    directory: Path = PRIVATE_SHAPE_DIRECTORY,
    stamp: str | None = None,
) -> Path:
    """Describe, verify, then write ``0600`` under a ``0700`` directory.

    Nothing is created before verification passes, so a refused capture leaves
    no partial artefact behind. ``O_EXCL`` means an existing artefact is never
    silently overwritten.
    """
    _validate_endpoint(endpoint)
    filename = shape_artifact_filename(endpoint, stamp=stamp)
    if not filename.startswith(PRIVATE_ARTIFACT_PREFIX) or os.sep in filename:
        raise ShapeLeakError("refusing to write an artefact without the PRIVATE_ prefix")

    shape = describe_shape(payload)
    verify_value_free(shape)
    text = render_shape_report(endpoint=endpoint, shape=shape)
    # Re-verify the round-tripped document: what is written is what was
    # checked, not merely something derived from it.
    verify_value_free(json.loads(text)["shape"])

    directory.mkdir(parents=True, exist_ok=True)
    # `mode=` on `mkdir` is masked by the umask and ignored for an existing
    # directory. Set it explicitly, unconditionally -- same reasoning as
    # `write_evidence` (`polymarket_us_auth_smoke.py:723-726`).
    directory.chmod(SHAPE_DIR_MODE)

    path = directory / filename
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, SHAPE_FILE_MODE)
    try:
        handle = os.fdopen(fd, "w", encoding="utf-8")
    except BaseException:
        os.close(fd)
        raise
    with handle:
        handle.write(text)
    os.chmod(path, SHAPE_FILE_MODE)
    return path
