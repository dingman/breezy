"""NO-side durable-state key constants (S5 plan, E2-1/E3-6).

I/O-free: two ``Final`` string constants plus tiny pure helpers over an
already-open :class:`~breezy.runtime.submit_intent.StateStore`. Never opens
a store, never imports ``breezy.runtime`` (adapters sits below runtime and
strategy in the layers contract, ``pyproject.toml:75-91``) -- callers pass
their own already-open store in.

The bounded first-order protocol (amendment
``docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md`` section 8):
while :data:`NO_SIDE_FIRST_LIVE_ORDER_KEY` exists and
:data:`NO_SIDE_POSITION_SHAPE_CAPTURED_KEY` does not, the strategy refuses
to arm any further NO take account-wide, and the first NO trial is scored
as residual. Only the operator-run CLI
(``breezy.runtime.mark_no_side_position_captured_cli``) may ever WRITE the
captured key -- see the AST scan in
``tests/unit/test_no_side_keys.py::test_the_captured_key_is_a_write_target_
only_in_the_cli_module`` (E3-7): the node may read either key, never write
the captured one.
"""

from __future__ import annotations

import json
from typing import Protocol

__all__ = [
    "NO_SIDE_FIRST_LIVE_ORDER_KEY",
    "NO_SIDE_POSITION_SHAPE_CAPTURED_KEY",
    "first_live_order_payload",
    "is_no_side_pending",
]

#: Written atomically at NO create-path submission time (E3-1(i)), and
#: equivalently at boot reconciliation (E3-8) when a NO-leg durable fill
#: exists with this key still absent. Payload: instrument id, venue order
#: id (when known), timestamp -- opaque to every reader in this module.
NO_SIDE_FIRST_LIVE_ORDER_KEY = "exec/polymarket_us/no_side/first_live_order"

#: Written ONLY by the operator CLI, after the venue position payload for
#: the first NO fill has been captured and a ruling fixes the per-leg
#: position mapping. Its presence ends the pending/containment window.
NO_SIDE_POSITION_SHAPE_CAPTURED_KEY = "exec/polymarket_us/no_side/position_shape_captured"


class _ReadableStore(Protocol):
    def get(self, key: str) -> bytes | None: ...


def first_live_order_payload(
    instrument_id: str,
    ts_ns: int,
    *,
    venue_order_id: str | None = None,
) -> bytes:
    """The single, shared payload shape for :data:`NO_SIDE_FIRST_LIVE_ORDER_KEY`.

    Every writer (the strategy's arm-time write and the exec client's
    boot-reconcile write, E3-8) MUST render the identical JSON shape --
    keys ``instrumentId``/``venueOrderId``/``tsNs``, ``sort_keys=True`` --
    so no reader ever has to know which site wrote a given record.
    ``venue_order_id`` is ``None`` at arm time (the venue has not answered
    yet) and a real id once the boot-reconcile path recovers it from an
    already-durable :class:`DurableFillRecord`.
    """
    payload = {
        "instrumentId": instrument_id,
        "venueOrderId": venue_order_id,
        "tsNs": ts_ns,
    }
    return json.dumps(payload, sort_keys=True).encode("utf-8")


def is_no_side_pending(store: _ReadableStore) -> bool:
    """``True`` while the bounded first-order protocol is in its
    containment window: the first-order key exists and the captured key
    does not. Both reads are plain ``store.get`` -- no flock is taken or
    required (mirrors ``_reconcile_submit_intent``'s own unlocked reads)."""
    return (
        store.get(NO_SIDE_FIRST_LIVE_ORDER_KEY) is not None
        and store.get(NO_SIDE_POSITION_SHAPE_CAPTURED_KEY) is None
    )
