"""Adapter-free exec-intent helpers (AUT-1 WP5-A, V-15).

``intent_fingerprint`` moved here byte-identically from the venue adapter's
``exec/submit_chain.py`` (which re-exports it), so wrapped AUT-1 audit units
can use it without importing any ``breezy.adapters.*`` module. The exec-store
key prefixes are restated, never imported, because ``exec/client.py`` is
byte-pinned; ``tests/unit/autonomy/test_exec_intent_parity.py`` pins them
equal to the client's constants.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from typing import Final

__all__ = [
    "FILL_BY_DAY_KEY_PREFIX",
    "FILL_BY_FINGERPRINT_KEY_PREFIX",
    "FILL_INDEX_KEY_PREFIX",
    "FILL_KEY_PREFIX",
    "RESOLVER_CONTEXT_KEY_PREFIX",
    "STATE_KEY_NAMESPACE",
    "VENUE_ORDER_ID_KEY_PREFIX",
    "intent_fingerprint",
    "utc_day_for_ns",
]

STATE_KEY_NAMESPACE: Final[str] = "exec/polymarket_us/"
VENUE_ORDER_ID_KEY_PREFIX: Final[str] = f"{STATE_KEY_NAMESPACE}venue_id/"
FILL_KEY_PREFIX: Final[str] = f"{STATE_KEY_NAMESPACE}fill/"
FILL_INDEX_KEY_PREFIX: Final[str] = f"{STATE_KEY_NAMESPACE}fill_index/"
FILL_BY_DAY_KEY_PREFIX: Final[str] = f"{STATE_KEY_NAMESPACE}fill_by_day/"
FILL_BY_FINGERPRINT_KEY_PREFIX: Final[str] = f"{STATE_KEY_NAMESPACE}fill_by_fingerprint/"
RESOLVER_CONTEXT_KEY_PREFIX: Final[str] = f"{STATE_KEY_NAMESPACE}resolver/"


def intent_fingerprint(order: object) -> str:
    payload = "\n".join(
        (
            str(getattr(order, "instrument_id", "")),
            str(getattr(order, "side", "")),
            str(getattr(order, "quantity", "")),
            str(getattr(order, "price", "")),
            str(getattr(order, "time_in_force", "")),
            str(getattr(order, "client_order_id", "")),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_NS_PER_SECOND: Final[int] = 1_000_000_000


def utc_day_for_ns(now_ns: int) -> date:
    """The UTC calendar day containing ``now_ns``: a restated copy of the adapter's
    ``operator_controls.utc_day_for_ns`` (V-15; the adapter module cannot be imported here).

    The audit's leg I derives the ``fill_by_fingerprint/<day>:<fp>`` key with this, from the
    intent's ``created_ns`` (``exec/client.py`` passes ``intent_created_ns``), and the day index
    from the fill's own ``ts_event``. Integer seconds, never a float. ``tests/unit/autonomy/
    test_exec_intent_parity.py`` pins it equal to the adapter over boundaries and random
    instants, and pins the client's two call-site inputs. Invalid input raises ``ValueError``;
    the adapter raises its own permission error for the same inputs.
    """
    if type(now_ns) is not int:
        raise ValueError(
            f"now_ns must be exactly int, not {type(now_ns).__name__}; the day boundary "
            f"is never derived from a float"
        )
    if now_ns <= 0:
        raise ValueError("now_ns must be a positive number of nanoseconds")
    return datetime.fromtimestamp(now_ns // _NS_PER_SECOND, UTC).date()
