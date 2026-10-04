"""AUT-1 WP5 stage 2b, W3: the advisory exec-store view (plan r12 section 3.11.1).

``read_exec_view`` reads the exec store through the E-8 snapshot helper with ``take_flock=False``
(E-7a rule 3, E-8a): it never takes the intent flock and never opens the live store, only a
recovered copy in the audit's cache directory. The result is ADVISORY: it may lag the live store, so
it never counts toward the join verdict on its own. Venue order ids leave this module only as
sha256. A snapshot failure is ``exec_snapshot_failed``, an unknown key under the exec namespace is
``exec_key_prefix_unknown`` (key-schema drift) and an undecodable record is
``exec_record_undecodable``; none is ever an empty view.
"""

import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final

from breezy.analysis.capture_audit_cache import cache_dir_parts, ensure_cache_dir
from breezy.analysis.capture_audit_input_types import (
    ExecFill,
    ExecOrder,
    ExecView,
    ResolverContext,
)
from breezy.analysis.capture_audit_model import AuditInputError
from breezy.domain.exec_intent import (
    FILL_BY_DAY_KEY_PREFIX,
    FILL_BY_FINGERPRINT_KEY_PREFIX,
    FILL_INDEX_KEY_PREFIX,
    FILL_KEY_PREFIX,
    RESOLVER_CONTEXT_KEY_PREFIX,
    STATE_KEY_NAMESPACE,
    VENUE_ORDER_ID_KEY_PREFIX,
)
from breezy.runtime.autonomy_sandbox.wal_snapshot import (
    SnapshotReadFailure,
    WalSnapshot,
    connect_snapshot_readonly,
    exec_snapshot,
)

__all__ = ["KNOWN_EXEC_SUBPREFIXES", "read_exec_view"]

#: Sub-prefixes of ``exec/polymarket_us/`` the audit knows (any other key in that namespace is
#: key-schema drift). The first six are the domain constants.
KNOWN_EXEC_SUBPREFIXES: Final[tuple[str, ...]] = (
    VENUE_ORDER_ID_KEY_PREFIX,
    FILL_KEY_PREFIX,
    FILL_INDEX_KEY_PREFIX,
    FILL_BY_DAY_KEY_PREFIX,
    FILL_BY_FINGERPRINT_KEY_PREFIX,
    RESOLVER_CONTEXT_KEY_PREFIX,
    f"{STATE_KEY_NAMESPACE}startup_evidence",
    f"{STATE_KEY_NAMESPACE}budget_restore/",
    f"{STATE_KEY_NAMESPACE}budget_exhausted/",
    f"{STATE_KEY_NAMESPACE}intent/",
    f"{STATE_KEY_NAMESPACE}no_side/",
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _undecodable(detail: str) -> AuditInputError:
    return AuditInputError("exec_record_undecodable", detail)


def _json_object(raw: bytes, what: str) -> dict[str, Any]:
    try:
        body = json.loads(raw)
    except ValueError:
        raise _undecodable(what) from None
    if not isinstance(body, dict):
        raise _undecodable(what)
    return body


def _fill_of(raw: bytes) -> ExecFill:
    body = _json_object(raw, "fill")
    try:
        trade = body.get("tradeId")
        return ExecFill(
            client_order_id=str(body["clientOrderId"]),
            venue_order_id_sha256=_sha(str(body["venueOrderId"])),
            trade_id=None if trade is None else str(trade),
            instrument_id=str(body["instrumentId"]),
            order_side=str(body["orderSide"]),
            cumulative_qty=str(body["cumulativeQty"]),
            cumulative_cost=str(body["cumulativeCost"]),
            ts_event=int(body["tsEvent"]),
            fee_reconciled=bool(body["feeReconciled"]),
        )
    except (KeyError, TypeError, ValueError):
        raise _undecodable("fill") from None


def _resolver_of(raw: bytes) -> ResolverContext:
    body = _json_object(raw, "resolver")
    try:
        return ResolverContext(
            intent_id=str(body["intentId"]),
            client_order_id=str(body["clientOrderId"]),
            instrument_id=str(body["instrumentId"]),
            created_ns=int(body["createdNs"]),
        )
    except (KeyError, TypeError, ValueError):
        raise _undecodable("resolver") from None


def _index_ids(raw: bytes) -> tuple[str, ...]:
    try:
        ids = json.loads(raw)
    except ValueError:
        raise _undecodable("fill_by_day") from None
    if not isinstance(ids, list) or not all(isinstance(v, str) for v in ids):
        raise _undecodable("fill_by_day")
    return tuple(_sha(v) for v in ids)


def _text(raw: bytes, what: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise _undecodable(what) from None


def _view_of(rows: Iterable[tuple[str, bytes]]) -> ExecView:
    fills: list[ExecFill] = []
    by_day: dict[str, tuple[str, ...]] = {}
    by_fp: dict[str, str] = {}
    orders: list[ExecOrder] = []
    resolvers: list[ResolverContext] = []
    for key, raw in rows:
        if not key.startswith(STATE_KEY_NAMESPACE):
            continue
        if not key.startswith(KNOWN_EXEC_SUBPREFIXES):
            raise AuditInputError("exec_key_prefix_unknown", "key_schema_drift")
        if key.startswith(FILL_KEY_PREFIX):
            fills.append(_fill_of(raw))
        elif key.startswith(FILL_BY_DAY_KEY_PREFIX):
            by_day[key[len(FILL_BY_DAY_KEY_PREFIX) :]] = _index_ids(raw)
        elif key.startswith(FILL_BY_FINGERPRINT_KEY_PREFIX):
            by_fp[key[len(FILL_BY_FINGERPRINT_KEY_PREFIX) :]] = _sha(_text(raw, "fingerprint"))
        elif key.startswith(VENUE_ORDER_ID_KEY_PREFIX):
            orders.append(
                ExecOrder(_text(raw, "venue_id"), _sha(key[len(VENUE_ORDER_ID_KEY_PREFIX) :]))
            )
        elif key.startswith(RESOLVER_CONTEXT_KEY_PREFIX):
            resolvers.append(_resolver_of(raw))
    return ExecView(
        fills=tuple(sorted(fills, key=lambda f: (f.ts_event, f.venue_order_id_sha256))),
        fill_by_day=by_day,
        fill_by_fingerprint=by_fp,
        orders=tuple(sorted(orders, key=lambda o: (o.client_order_id, o.venue_order_id_sha256))),
        resolvers=tuple(sorted(resolvers, key=lambda r: r.intent_id)),
    )


def read_exec_view(data_root: Path) -> ExecView:
    """The advisory exec-store view (venue ids hashed); raises ``AuditInputError`` on failure."""
    ensure_cache_dir(data_root)
    with exec_snapshot(
        cache_dir=data_root.joinpath(*cache_dir_parts()), take_flock=False, data_root=data_root
    ) as outcome:
        if isinstance(outcome, SnapshotReadFailure) or not isinstance(outcome, WalSnapshot):
            reason = getattr(getattr(outcome, "reason", None), "value", "unknown")
            raise AuditInputError("exec_snapshot_failed", str(reason))
        try:
            conn = connect_snapshot_readonly(outcome)
            try:
                rows = [(str(k), bytes(v)) for k, v in conn.execute("SELECT key, value FROM state")]
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001 - any store error is a fail-loud ERROR, never a pass
            raise AuditInputError("exec_snapshot_failed", type(exc).__name__) from None
    return _view_of(rows)
