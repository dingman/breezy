"""Pure parsing of Polymarket.us ``GET /v1/portfolio/activities`` pages into
:class:`~breezy.persistence.external_capital_flows.ExternalCapitalFlow`
records (FU-13b).

No I/O and no venue client here -- the caller (a ``scripts/venue/`` puller,
built in a later stage) owns the signed GET via
``PolymarketUSHttpClient.get_authenticated`` and hands this module the
decoded JSON page. Keeping this module I/O-free is what makes
``parse_external_flows`` exhaustively unit-testable against captured (and
synthetic) payload shapes without a fake transport.

Activity-type literals are the full ``ACTIVITY_TYPE_*`` names from the SDK
snapshot (``docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/
types/portfolio.py:8-16``). ``ACTIVITY_TYPE_TRADE`` and
``ACTIVITY_TYPE_POSITION_RESOLUTION`` are ignored: proceeds and capital
already cover them (FU-13b plan, "Types filter"). The remaining five are
capital-flow types and get a sign per :data:`FLOW_TYPES`. Any other value of
``type`` is kept as :data:`UNRECOGNISED_KIND` with only a timestamp and a
transaction-id hash -- never an amount, since an unknown type's sign
convention is unknown (FU-13b plan, "Shape drift (L-17)").

Shape drift: the captured payload carries the full record (status, amount,
createTime, updateTime, transactionId, failure fields) both directly on
``accountBalanceChange`` AND duplicated inside its single
``transactions[0]`` entry -- beyond what the SDK's ``AccountBalanceChange``
TypedDict declares (that TypedDict has only ``transactions``). This module
therefore prefers the top-level fields and falls back to a *single* nested
entry only when the top level is absent; anything else (no top level and
zero or more-than-one nested entries) is UNPARSEABLE rather than guessed at.

Diagnostics (log lines, on the UNPARSEABLE path) never carry amounts, ids,
or any other payload value -- only the activity index, its ``type``, and a
short structural reason (AC10).
"""

from __future__ import annotations

import calendar
import hashlib
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from breezy.persistence.external_capital_flows import ExternalCapitalFlow

__all__ = [
    "FLOW_TYPES",
    "KNOWN_STATUSES",
    "PARSE_STATUS_OK",
    "PARSE_STATUS_UNPARSEABLE",
    "PORTFOLIO_ACTIVITIES_PATH",
    "UNRECOGNISED_KIND",
    "TradeActivityRef",
    "page_min_create_ts_ns",
    "parse_external_flows",
    "trade_rows_for_order",
]

_logger = logging.getLogger(__name__)

#: The sole occurrence of this literal under ``src/`` and ``scripts/`` (AC8) --
#: the puller (a later stage) passes it to
#: ``PolymarketUSHttpClient.get_authenticated``.
PORTFOLIO_ACTIVITIES_PATH: Final[str] = "/v1/portfolio/activities"

UNRECOGNISED_KIND: Final[str] = "UNRECOGNISED"
PARSE_STATUS_OK: Final[str] = "OK"
PARSE_STATUS_UNPARSEABLE: Final[str] = "UNPARSEABLE"

_SIGN_BASIS_TYPE_TABLE: Final[str] = "type_table"
_SIGN_BASIS_TYPE_TABLE_UNOBSERVED: Final[str] = "type_table_unobserved"
_SIGN_BASIS_LITERAL: Final[str] = "literal"
_SIGN_BASIS_NA: Final[str] = "n/a"


@dataclass(frozen=True)
class _FlowTypeSpec:
    """One row of the :data:`FLOW_TYPES` sign table.

    ``sign`` is ``+1``/``-1`` for a type whose sign is asserted by the type
    itself (deposits and bonuses are always credits; a withdrawal, never
    observed live, is asserted debit and flagged accordingly), or ``None``
    when the type's own literal amount sign is trusted as-is (a transfer can
    run either direction).
    """

    kind: str
    sign: int | None
    sign_basis: str


#: Keyed by the FULL ``ACTIVITY_TYPE_*`` name (SDK snapshot
#: ``types/portfolio.py:9-15``). ``ACTIVITY_TYPE_TRADE`` and
#: ``ACTIVITY_TYPE_POSITION_RESOLUTION`` are deliberately absent -- they are
#: ignored before this table is consulted, never parsed as flows.
FLOW_TYPES: Final[Mapping[str, _FlowTypeSpec]] = {
    "ACTIVITY_TYPE_ACCOUNT_DEPOSIT": _FlowTypeSpec(
        kind="ACCOUNT_DEPOSIT", sign=1, sign_basis=_SIGN_BASIS_TYPE_TABLE
    ),
    "ACTIVITY_TYPE_ACCOUNT_ADVANCED_DEPOSIT": _FlowTypeSpec(
        kind="ACCOUNT_ADVANCED_DEPOSIT", sign=1, sign_basis=_SIGN_BASIS_TYPE_TABLE
    ),
    "ACTIVITY_TYPE_ACCOUNT_WITHDRAWAL": _FlowTypeSpec(
        kind="ACCOUNT_WITHDRAWAL", sign=-1, sign_basis=_SIGN_BASIS_TYPE_TABLE_UNOBSERVED
    ),
    "ACTIVITY_TYPE_REFERRAL_BONUS": _FlowTypeSpec(
        kind="REFERRAL_BONUS", sign=1, sign_basis=_SIGN_BASIS_TYPE_TABLE
    ),
    "ACTIVITY_TYPE_TRANSFER": _FlowTypeSpec(
        kind="TRANSFER", sign=None, sign_basis=_SIGN_BASIS_LITERAL
    ),
}

_IGNORED_ACTIVITY_TYPES: Final[frozenset[str]] = frozenset(
    {"ACTIVITY_TYPE_TRADE", "ACTIVITY_TYPE_POSITION_RESOLUTION"}
)

#: The two ``ACCOUNT_BALANCE_CHANGE_STATUS_*`` values AC5 permits to be
#: counted. Any other status (a real failure/cancel status, or a value never
#: seen before) is preserved verbatim on the record so a caller can observe
#: ``status not in KNOWN_STATUSES`` -- this module does not gate on it.
KNOWN_STATUSES: Final[frozenset[str]] = frozenset(
    {
        "ACCOUNT_BALANCE_CHANGE_STATUS_COMPLETED",
        "ACCOUNT_BALANCE_CHANGE_STATUS_PENDING",
    }
)

_REQUIRED_TOP_LEVEL_KEYS: Final[tuple[str, ...]] = ("status", "amount", "createTime")

_RFC3339_RE: Final[re.Pattern[str]] = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})(\.\d+)?Z$"
)


def _has_failure_marker(record: Mapping[str, Any] | None) -> bool:
    """True if ``record`` carries a non-empty failure marker.

    Checks ``failureReason``/``failureCode`` (non-empty string) and
    ``failureAction`` (not ``None``) -- the shape observed both at the top
    level of ``accountBalanceChange`` and nested inside its
    ``transactions[0]`` entry.
    """
    if not record:
        return False
    if record.get("failureReason"):
        return True
    if record.get("failureCode"):
        return True
    return record.get("failureAction") is not None


def _nested_first(balance_change: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if not isinstance(balance_change, Mapping):
        return None
    transactions = balance_change.get("transactions")
    if isinstance(transactions, list) and transactions and isinstance(transactions[0], Mapping):
        return transactions[0]
    return None


def _resolve_record(
    balance_change: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any] | None, str | None]:
    """Top-level-then-single-nested-fallback record resolution (L-17).

    Returns ``(record, None)`` on success, or ``(None, reason)`` where
    ``reason`` is a short, payload-free structural description.
    """
    if not isinstance(balance_change, Mapping):
        return None, "accountBalanceChange missing"
    if all(balance_change.get(key) is not None for key in _REQUIRED_TOP_LEVEL_KEYS):
        return balance_change, None
    transactions = balance_change.get("transactions")
    if isinstance(transactions, list) and len(transactions) == 1 and isinstance(
        transactions[0], Mapping
    ):
        return transactions[0], None
    count = len(transactions) if isinstance(transactions, list) else 0
    return None, f"top level absent and nested count={count}"


def _parse_rfc3339_ns(value: object) -> int:
    """Parse an RFC3339 UTC timestamp (``...Z``, up to nanosecond precision)
    into nanoseconds since the epoch. Raises :class:`ValueError` on anything
    that does not match -- callers convert that into an UNPARSEABLE record,
    never a payload-carrying exception.
    """
    if not isinstance(value, str):
        raise TypeError("timestamp is not a string")
    match = _RFC3339_RE.match(value)
    if match is None:
        raise ValueError("timestamp does not match RFC3339 Z format")
    date_part, time_part, frac_part = match.groups()
    parsed = datetime.strptime(f"{date_part}T{time_part}", "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    epoch_s = calendar.timegm(parsed.timetuple())
    frac_digits = (frac_part[1:] if frac_part else "").ljust(9, "0")[:9]
    return epoch_s * 1_000_000_000 + int(frac_digits)


def _hash_transaction_id(transaction_id: object) -> str | None:
    if not isinstance(transaction_id, str) or not transaction_id:
        return None
    return hashlib.sha256(transaction_id.encode("utf-8")).hexdigest()


def _decimal_amount(amount: object) -> tuple[Decimal | None, str | None]:
    if not isinstance(amount, Mapping):
        return None, None
    currency = amount.get("currency")
    currency = currency if isinstance(currency, str) else None
    value = amount.get("value")
    if not isinstance(value, str) or not value:
        return None, currency
    try:
        return Decimal(value), currency
    except InvalidOperation:
        return None, currency


def _unparseable_flow(kind: str) -> ExternalCapitalFlow:
    return ExternalCapitalFlow(
        kind=kind,
        signed_amount=None,
        currency=None,
        status=None,
        create_ts_ns=None,
        update_ts_ns=None,
        transaction_id_sha256=None,
        sign_basis=_SIGN_BASIS_NA,
        parse_status=PARSE_STATUS_UNPARSEABLE,
        failed=False,
    )


def _parse_activity(
    activity: Mapping[str, Any], index: int, activity_type: Any
) -> ExternalCapitalFlow:
    spec = FLOW_TYPES.get(activity_type) if isinstance(activity_type, str) else None
    balance_change = activity.get("accountBalanceChange")
    balance_change = balance_change if isinstance(balance_change, Mapping) else None
    record, reason = _resolve_record(balance_change)
    fallback_kind = spec.kind if spec is not None else UNRECOGNISED_KIND

    if record is None:
        _logger.warning(
            "activities[%d] type=%s unparseable: %s", index, activity_type, reason
        )
        return _unparseable_flow(fallback_kind)

    try:
        create_ts_ns = _parse_rfc3339_ns(record.get("createTime"))
    except (ValueError, TypeError):
        _logger.warning("activities[%d].accountBalanceChange.createTime unparseable", index)
        return _unparseable_flow(fallback_kind)

    update_time = record.get("updateTime")
    try:
        update_ts_ns = (
            _parse_rfc3339_ns(update_time) if update_time is not None else create_ts_ns
        )
    except (ValueError, TypeError):
        update_ts_ns = create_ts_ns

    failed = _has_failure_marker(balance_change) or _has_failure_marker(
        _nested_first(balance_change)
    )
    transaction_id_sha256 = _hash_transaction_id(record.get("transactionId"))
    status = record.get("status")
    status = status if isinstance(status, str) else None

    if spec is None:
        # Unrecognised activity type: timestamp and hash only, no amount --
        # an unknown type's sign convention cannot be trusted (L-17).
        return ExternalCapitalFlow(
            kind=UNRECOGNISED_KIND,
            signed_amount=None,
            currency=None,
            status=None,
            create_ts_ns=create_ts_ns,
            update_ts_ns=update_ts_ns,
            transaction_id_sha256=transaction_id_sha256,
            sign_basis=_SIGN_BASIS_NA,
            parse_status=PARSE_STATUS_OK,
            failed=failed,
        )

    decimal_value, currency = _decimal_amount(record.get("amount"))
    signed_amount: Decimal | None = None
    if decimal_value is not None:
        signed_amount = (
            decimal_value if spec.sign is None else Decimal(spec.sign) * abs(decimal_value)
        )

    return ExternalCapitalFlow(
        kind=spec.kind,
        signed_amount=signed_amount,
        currency=currency,
        status=status,
        create_ts_ns=create_ts_ns,
        update_ts_ns=update_ts_ns,
        transaction_id_sha256=transaction_id_sha256,
        sign_basis=spec.sign_basis,
        parse_status=PARSE_STATUS_OK,
        failed=failed,
    )


def parse_external_flows(page: Mapping[str, Any]) -> list[ExternalCapitalFlow]:
    """Parse one decoded ``GET /v1/portfolio/activities`` page.

    Pure: no I/O, never raises on a malformed individual record (it becomes
    an UNPARSEABLE :class:`ExternalCapitalFlow` instead, with a payload-free
    diagnostic logged). ``ACTIVITY_TYPE_TRADE`` and
    ``ACTIVITY_TYPE_POSITION_RESOLUTION`` rows are dropped entirely.
    """
    activities = page.get("activities")
    if not isinstance(activities, list):
        return []
    flows: list[ExternalCapitalFlow] = []
    for index, activity in enumerate(activities):
        if not isinstance(activity, Mapping):
            continue
        activity_type = activity.get("type")
        if activity_type in _IGNORED_ACTIVITY_TYPES:
            continue
        flows.append(_parse_activity(activity, index, activity_type))
    return flows


# ---------------------------------------------------------------------------
# EDGE-2 slice D (AC4(c)): the resolver's trade-activity join.
#
# Authority: docs/plans/backlog/EDGE_2026-09-27/
# EDGE-2_ambiguous_executions_resolver_plan_r3_2026-09-27.md section 5 (file
# `account_activity.py` row). Pure, no I/O -- the resolver coroutine
# (`exec/client.py::_order_trade_activity`) owns the paginated GET and hands
# each decoded page to these functions.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TradeActivityRef:
    """One ``ACTIVITY_TYPE_TRADE`` activity row naming a specific venue order
    id, extracted from a portfolio activities page.

    AC3/AC4(c): never carries a price or a dollar amount -- only what the
    resolver's zero-fill gate needs to prove a trade happened, roughly when,
    and how much. A malformed ``qtyDecimal`` or ``createTime`` on an
    otherwise-matched row never drops the match itself (a genuine trade for
    this order id must never be silently lost); it degrades to ``Decimal(0)``
    / ``0`` instead, so the row still counts toward ``trade_count``.
    """

    qty: Decimal
    create_ts_ns: int
    is_aggressor: bool


def _trade_qty_decimal(trade: Mapping[str, Any]) -> Decimal:
    raw = trade.get("qtyDecimal")
    if raw is None:
        return Decimal(0)
    try:
        return Decimal(str(raw))
    except InvalidOperation:
        return Decimal(0)


def _trade_create_ts_ns(trade: Mapping[str, Any]) -> int:
    try:
        return _parse_rfc3339_ns(trade.get("createTime"))
    except (ValueError, TypeError):
        return 0


def trade_rows_for_order(
    page: Mapping[str, Any], venue_order_id: str
) -> tuple[TradeActivityRef, ...]:
    """AC4(c): every ``ACTIVITY_TYPE_TRADE`` row on ``page`` whose aggressor
    or passive leg names ``venue_order_id`` -- an EXACT id match on
    ``trade.aggressor.id`` / ``trade.passive.id`` (captured shape:
    ``docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-05_SFO/
    activities_p0.json``).

    ``marketSlug`` is deliberately NOT consulted here: L-17's captured
    evidence (``activities_slug.json``) proved the venue's ``marketSlug``
    query parameter is not a trade filter, so this module never treats slug
    equality as evidence of a match for a SPECIFIC order id either -- only
    the id itself.
    """
    activities = page.get("activities")
    if not isinstance(activities, list):
        return ()
    refs: list[TradeActivityRef] = []
    for activity in activities:
        if not isinstance(activity, Mapping):
            continue
        if activity.get("type") != "ACTIVITY_TYPE_TRADE":
            continue
        trade = activity.get("trade")
        trade = trade if isinstance(trade, Mapping) else {}
        aggressor = trade.get("aggressor")
        aggressor = aggressor if isinstance(aggressor, Mapping) else {}
        passive = trade.get("passive")
        passive = passive if isinstance(passive, Mapping) else {}
        is_aggressor = aggressor.get("id") == venue_order_id
        is_passive = passive.get("id") == venue_order_id
        if not (is_aggressor or is_passive):
            continue
        refs.append(
            TradeActivityRef(
                qty=_trade_qty_decimal(trade),
                create_ts_ns=_trade_create_ts_ns(trade),
                is_aggressor=is_aggressor,
            )
        )
    return tuple(refs)


def _activity_create_ts_ns(activity: Mapping[str, Any]) -> int | None:
    """The one timestamp ``activity`` carries, by type, in nanoseconds --
    mirrors ``scripts/venue/edge2_ambiguous_order_probe.py``'s
    ``activity_create_time`` type dispatch exactly (trade -> its own
    ``createTime``; position-resolution -> the after-leg's ``updateTime``;
    everything else -> the balance-change top-level-then-nested-fallback
    ``createTime``, L-17). Returns ``None`` if no parseable timestamp is
    found -- never guessed.
    """
    kind = activity.get("type")
    if kind == "ACTIVITY_TYPE_TRADE":
        trade = activity.get("trade")
        raw = trade.get("createTime") if isinstance(trade, Mapping) else None
    elif kind == "ACTIVITY_TYPE_POSITION_RESOLUTION":
        resolution = activity.get("positionResolution")
        after = resolution.get("afterPosition") if isinstance(resolution, Mapping) else None
        raw = after.get("updateTime") if isinstance(after, Mapping) else None
    else:
        balance = activity.get("accountBalanceChange")
        balance = balance if isinstance(balance, Mapping) else None
        raw = balance.get("createTime") if balance is not None else None
        if raw is None:
            nested = _nested_first(balance)
            raw = nested.get("createTime") if nested is not None else None
    try:
        return _parse_rfc3339_ns(raw)
    except (ValueError, TypeError):
        return None


def page_min_create_ts_ns(page: Mapping[str, Any]) -> int | None:
    """The minimum activity ``createTime`` on ``page``, in nanoseconds.

    **Observability only (EDGE-2 slice D coordinator amendment,
    2026-09-27).** Step 0 (``docs/evidence/venue/polymarket_us/
    AMBIGUOUS_ORDER_2026-09-23_MIA/README.md``) found the account's entire
    35-row history fit on ONE page (``eof=true``) on every traversal, so the
    plan's ``min(createTime) < createdNs`` completeness branch was never
    exercised against the real venue and stays UNLICENSED (follow-up
    ``EDGE-2-MULTIPAGE``) until a real multi-page traversal is observed and
    Q2s is re-verified across a page boundary. The resolver's own
    ``_order_trade_activity`` therefore computes ``complete`` from ``eof``
    ALONE and never from this value -- this function exists so the running
    minimum can still be logged (``page_min_create_ts_ns=``) for that future
    verification.

    Returns ``None`` if no activity on ``page`` carries a parseable
    timestamp of any kind.
    """
    activities = page.get("activities")
    if not isinstance(activities, list):
        return None
    times: list[int] = []
    for activity in activities:
        if not isinstance(activity, Mapping):
            continue
        ts = _activity_create_ts_ns(activity)
        if ts is not None:
            times.append(ts)
    return min(times) if times else None
