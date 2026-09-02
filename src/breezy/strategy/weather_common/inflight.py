"""The one in-flight order question every weather strategy asks, asked once.

WHY THIS MODULE EXISTS
----------------------
Every weather strategy used to read ``cache.orders_open(instrument_id=...)``
for two different questions -- "is anything working?" (the re-submission
gate) and "how much am I already committed to?" (the ``pending_qty`` feed of
:class:`breezy.strategy.weather_common.risk.PortfolioSnapshot`). Both were
wrong in the same way, because ``Order.is_open_c``
(``nautilus_trader/model/orders/base.pyx``) is
``ACCEPTED / TRIGGERED / PENDING_CANCEL / PENDING_UPDATE / PARTIALLY_FILLED``:
it EXCLUDES ``INITIALIZED`` and ``SUBMITTED``, and ``Cache.add_order`` never
writes ``_index_orders_open`` (only ``update_order`` does). Inside the
submit -> ACCEPTED window a strategy therefore saw an empty book, passed its
own gate, and re-derived its size from a position that did not yet include
the order already in flight -- a duplicate order, up to 2x intended size.

That is not merely untidy: ``pending_qty`` feeds ``PortfolioSnapshot.net_qty``,
and ``net_qty`` is what ``RiskLimits.max_position_contracts`` -- an
OPERATOR-RESERVED control, and the only cumulative position cap that exists
anywhere in this system (Nautilus's ``RiskEngine`` has none) -- is screened
against. Settled 0 -> BUY 200 passes (200 <= 250) -> a second cycle inside
the window still reads 0 -> a second BUY 200 passes -> net 400 against a cap
of 250. See ``docs/plans/T1_STRATEGY_INFLIGHT_BLINDNESS_2026-09-02.md`` §0.

THE PREDICATE
-------------
``not order.is_closed`` over ``cache.orders(instrument_id=...)``.

``is_closed_c`` (``base.pyx``) is ``DENIED / REJECTED / CANCELED / EXPIRED /
FILLED``; its complement is a strict SUPERSET of ``is_open``, adding exactly
``INITIALIZED / SUBMITTED / EMULATED / RELEASED``. ``cache.orders(...)`` is
dict-backed and unfiltered by openness, so there is no double count.

*Not* ``orders_open() + orders_inflight()``: ``is_inflight_c`` is
``SUBMITTED / PENDING_CANCEL / PENDING_UPDATE`` only, so ``INITIALIZED``
would stay invisible -- and ``INITIALIZED`` is live-reachable, since the
execution engine drains its own queue and a later handler invocation can
observe one. *Not* a Breezy-side in-flight ledger keyed on ``on_order_*``
events either: that duplicates cache state and needs cancel/reject/
partial-fill bookkeeping that can drift.

``Order.signed_decimal_qty()`` (``base.pyx``) is built from ``leaves_qty``,
not ``quantity``, so counting a ``PARTIALLY_FILLED`` order here does NOT
double-count the filled portion the portfolio's settled position already
carries.

RELATED, DELIBERATELY NOT SHARED
--------------------------------
``breezy.runtime.backtest_order_guard.BacktestOrderGuard._working_sell_orders``
applies the SAME predicate for the naked-short screen, and is intentionally
left as its own copy: ``runtime`` importing ``strategy`` would invert this
repo's layering (``strategy`` is the top layer -- see the import-linter
contract in ``pyproject.toml``), and the guard is safety-critical, already
correct, and heavily tested. The cross-reference is the shared artefact; the
three lines of duplication are the deliberate price of not touching a correct
safety module for zero correctness gain. Change one, read the other.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable

    from nautilus_trader.cache.base import CacheFacade
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.model.orders.base import Order

__all__ = ["signed_working_qty", "working_orders"]


def working_orders(cache: CacheFacade, instrument_id: InstrumentId) -> list[Order]:
    """Every order for ``instrument_id`` this strategy has committed and not yet lost.

    Includes ``INITIALIZED`` and ``SUBMITTED`` -- the two statuses
    ``cache.orders_open(...)`` misses, and the whole reason this module
    exists. See the module docstring for the predicate's derivation.
    """
    return [order for order in cache.orders(instrument_id=instrument_id) if not order.is_closed]


def signed_working_qty(orders: Iterable[Order]) -> float:
    """Signed sum of the UNFILLED quantity across ``orders``: BUY positive, SELL negative.

    Read ``leaves_qty``-based (via ``Order.signed_decimal_qty()``), so a
    partially filled order contributes only what is still outstanding.

    KNOWN LIMITATION, recorded rather than papered over: a single signed
    scalar cannot express a jointly-naked pair -- a +50 net may be a 60 BUY
    against a 10 SELL, and the SELL leg is unrecoverable from the sum. That
    case is covered at submit time, in both backtest and live, by
    ``breezy.runtime.backtest_order_guard.BacktestOrderGuard``, which sums
    working SELLs directly.
    """
    return sum((float(order.signed_decimal_qty()) for order in orders), 0.0)
