"""R-4: the reconciling, order-refusing Polymarket.us execution client.

Authority: ``docs/plans/EXEC_SPINE_2026-09-01.md`` section R-4.

WHAT THIS MODULE IS, AND WHY IT MATTERS MORE THAN ITS SIZE SUGGESTS
------------------------------------------------------------------

This is the first module in Breezy that publishes an ``AccountState``, and the
Nautilus risk engine is **INERT until one exists**:
``risk/engine.pyx:684-689`` returns ``True`` -- order allowed -- whenever
``account_for_venue(...)`` is ``None``, and ``:691-692`` does the same for a
margin account. Every notional and position cap, ``max_notional_per_order``
included, therefore turns on for the FIRST time at the moment this client
connects. That behaviour is pinned by
``tests/contract/test_risk_engine_ordering_enforcement.py``.

**It submits at most one order per station-day, and every other lifecycle
coroutine still refuses.** ``_submit_order`` is BUY-only, IOC, quantity-1,
and permit-gated: it denies before any venue contact unless the trading
refusals are clear, an account exists, the write-canonical string has been
verified (``write_transport.WRITE_CANONICAL_STRING_VERIFIED``, which stays
``False`` outside an explicit operator-approved increment), a live
``OrderSubmissionPermit`` is present, and
``assert_live_order_submission_permitted`` (B6) passes. Once armed, the
durable submit-intent latch (``runtime/submit_intent.py``) makes the POST
one-shot per station-day even across a process restart -- a second attempt
for an already-consumed day is refused by the latch before ``post_order`` is
ever reached. ``_cancel_order`` still carries a denial body; the remaining
lifecycle coroutines raise. The order-path literal itself lives only in
``write_transport.py`` (``ORDERS_PATH``), which this module reads through
the attribute rather than spelling out itself: barrier V2
(``tests/unit/test_polymarket_us_readonly_guard.py``) refuses a bare
order-path literal inside any OTHER venue-touching module with no
allowlist.

NULL-HYPOTHESIS VERDICTS, WITH THE `path:line` ACTUALLY OPENED
--------------------------------------------------------------

* ``LiveExecutionClient`` provides the lifecycle -- **CONFIRMED**. Breezy
  subclasses it (``live/execution_client.py:66``) and implements the
  coroutines the base declares abstract.
* ``_set_account_id`` (``execution/client.pyx:148``) and
  ``generate_account_state`` (``:329``) are **NATIVE ``cpdef`` methods that we
  CALL, not gaps we fill.** ``generate_account_state`` builds the
  ``AccountState`` and publishes it on the message bus itself; overriding
  either would be a reimplementation of the framework.
* ``_query_account`` is **genuinely absent from the base** -- it is called at
  ``live/execution_client.py:332`` with nothing defining it there, so the
  ``QueryAccount`` path raises ``AttributeError`` until a subclass supplies
  it. (It is not absent from the tree: nine shipped adapters define it and
  ``adapters/_template/execution.py:155`` documents it as a subclass
  responsibility. What is absent is a base implementation.)
* ``calculate_commission`` (``execution/client.pyx:165``) is a **native
  extension point**, and its own docstring says so: "Override this method to
  provide venue-specific commission logic for inferred fills generated during
  reconciliation." Unoverridden it returns ``None``, and
  ``live/reconciliation.py:507-508`` then books ``Money(0, quote_currency)``
  -- an implied-zero fee on every reconciled fill, which is exactly what
  ``assert_fee_schedule_known`` exists to prevent. The override delegates to
  :func:`~breezy.adapters.polymarket_us.fees.polymarket_us_fee`, so the
  reconciled fee and the modelled fee cannot drift apart.

THE DURABLE STORE IS A DELIBERATE REFUSAL OF A NATIVE, NOT A GAP
-----------------------------------------------------------------

Stating this the wrong way round would be the same defect as fabricating a
native, one sign flipped. **Nautilus DOES persist this natively.**
``cache/cache.pyx:393-394`` restores orders on start and ``:1366-1368``
rebuilds ``_index_venue_order_ids[venue_order_id] = client_order_id``, so the
venue-id map is native; ``cache/database.pyx:709-755`` ``load_position``
replays the stored ``OrderFilled`` events and reconstructs the ``Position``,
so ``avg_px_open`` is derived from fills and survives byte-exact, making the
fill record native too.

The only supported backend is Redis: ``system/kernel.py:312`` accepts
``type == "redis"`` and ``:324-329`` raises for anything else, and
``common/config.py:385`` requires Redis >= 6.2. **We decline that
dependency.** An external server as a hard runtime requirement of the trading
process is a new failure mode, a new operational surface, and a second network
egress the N2 firewall does not model. So the Breezy store is a refusal of a
native we could have had, on stated grounds -- not a gap we discovered.

The store is :class:`~breezy.runtime.sqlite_store.SqliteStateStore`, which
already exists and is already used by ingest. It is **injected as an opener**
rather than imported, for two reasons: ``breezy.runtime`` sits ABOVE
``breezy.adapters`` in the import-linter layer contract, and the store confines
itself to its constructing thread (``sqlite_store.py:120``, ``:128-135``), so
it must be built where it is written -- inside :meth:`_connect`, on the
execution engine's event loop -- never at config-build time on the main thread.

Three key prefixes, all under ``exec/polymarket_us/``, which **is** the
portability seam: a second venue gets its own prefix, never a shared one.

* ``exec/polymarket_us/venue_id/<id>``          -> ``ClientOrderId``
* ``exec/polymarket_us/fill/<venue order id>``  -> the fill record
* ``exec/polymarket_us/fill_index/<instrument>`` -> the venue order ids for it

The third is not in the plan's two-prefix sketch and is required by a measured
constraint: ``SqliteStateStore`` exposes ``get``/``set`` and no prefix scan
(``sqlite_store.py:158``, ``:173``), so a fill cannot be found BY INSTRUMENT
without an index key. Reconciliation looks up by instrument, not by venue
order id, so without it the fill record would be unreachable at exactly the
moment it is needed.

FOREIGN AND UNMATCHED POSITIONS: REFUSE TO TRADE, NOT TO START
---------------------------------------------------------------

A node that cannot boot while holding real risk is worse than the risk. **Every
LONG the venue reports is forwarded**, whatever we can or cannot say about its
price; what a position we cannot attribute earns is a latched trading refusal
and an ERROR log -- the node starts, reports the exposure, alerts, and denies.

Excluding one was tried and is WRONG, for a reason that is not about pricing at
all. Breezy's own caps size off ``Strategy.portfolio.net_position``
(``strategy/forecast_mispricing/strategy.py:399``), which is derived from the
reconciled position. An excluded position reads there as **zero**, so
``max_position_contracts``, ``max_event_notional``,
``max_simultaneous_positions`` and ``exclusive_conflict``
(``strategy/weather_common/risk.py:339-352``) would every one of them compute
from a portfolio that does not contain risk the account is actually carrying.
A hidden position also can never be exited: ``settled_qty() == 0`` refuses the
close as ``SHORTS_DISABLED`` (``risk.py:430-435``).

``avg_px_open`` is therefore resolved in three steps, best evidence first:

1. **Breezy's durable fill records** -- the NET REMAINING COST BASIS, not "the
   entry print". See invariant (4) below for why that distinction is load
   bearing and what it costs to get wrong.
2. **The venue's own ``cost``/``qtyBought``**, and only while ``qtySold == 0``
   (:func:`~breezy.adapters.polymarket_us.exec.reports.derive_position_cost_basis`);
   outside that condition ``cost`` may or may not be net of sells and the
   snapshot does not say which. See invariant (5): even inside that condition,
   fee-inclusion in ``cost`` is unverified.
3. **Unpriced** -- ``avg_px_open=None`` -- plus a refusal.

Step 3 has a MEASURED cost, stated here because the opposite was believed and
written down. An unpriced position report does not "generate nothing". With no
cached quote and an empty position cache, ``execution_engine.py:2947-3011``
synthesises a MARKET ``OrderStatusReport`` carrying ``price=None`` and
``avg_px=None``, and ``create_inferred_order_filled_event`` then reaches
``live/reconciliation.py:493`` -- ``last_px = instrument.make_price(0.0)``. So
the position books at an entry price of **0.00** (with a cached quote it books
at the quote instead, which is why the fallback order matters). See invariant
(3) for the precise condition under which each of those two happens, and why
it does not change what this client does.

That is accepted, not overlooked. The QUANTITY is right, and quantity is what
every cap reads; the price is wrong, and the latched refusal is exactly the
guarantee that no Breezy order is ever sized, priced or exited against it.
Dropping the position would have made the quantity wrong too -- and a wrong
quantity is the one that trades.

A **FLAT** venue report is the one exception, and it is not forwarded.
``position_check_interval_secs=None`` is a REQUIRED half of that refusal: with
it set, ``_create_flat_position_report`` (``execution_engine.py:1022``, called
at ``:967-975``) synthesises the very FLAT report this client declines to send,
from config alone. Both halves are pinned --
``tests/contract/test_exec_client_reconciliation_contract.py``. On a settled binary that is
the trigger for the landmine pinned in
``tests/contract/test_reconciliation_settlement_price_hazard.py``:
``generate_missing_orders`` defaults ``True`` (``live/config.py:183``) and
``calculate_reconciliation_price`` (``live/reconciliation.py:549``) returns
``avg_px_open`` itself for a long-to-flat target, so the close books at the
OPEN price and every settled trade realizes exactly zero. Closing a settled
binary is R-9's job, keyed on the NWS print at 1.00 or 0.00 -- never on a venue
FLAT at the price we paid.

FIVE INVARIANTS, EACH WITH ITS OWN VERIFIED CITATION
-----------------------------------------------------

1. **The refusal latch is NODE-GLOBAL and never self-clears.** Once
   :meth:`_refuse` appends a reason, nothing in this client removes it --
   not a later successful reconcile, not the condition that caused it being
   fixed, not a disconnect/reconnect cycle within one running process
   (``self._trading_refusals``, appended-only). Only a full process
   RESTART re-derives the refusal set from scratch, by reconciling again.
   Pinned by
   ``tests/unit/test_polymarket_us_exec_client.py::test_a_latched_refusal_persists_across_a_reconnect_after_the_condition_clears``.
2. **Native PnL and native cash are NON-AUTHORITATIVE while a position is
   unattributable, in both directions.** For an unpriced forward
   (``avg_px_open`` booked at 0.00, invariant 3), native
   ``Position.unrealized_pnl`` (``model/position.pyx:812-840``, reading
   ``avg_px_open`` set at fill time by ``:95``) shows the FULL current mark
   as phantom unrealized gain -- ``_calculate_points`` at ``:983-989``
   computes ``avg_px_close - avg_px_open`` with ``avg_px_open == 0``. Native
   cash is not merely "debited zero because the price was zero": Breezy's
   account carries ``calculate_account_state=False`` (default;
   ``accounting/factory.pyx:125``, never overridden -- see the R-4 review's
   balance-semantics contract pin), so ``Portfolio.update_order``
   (``portfolio.pyx:500-501``) returns before any balance is ever touched by
   a reconciled fill, priced or not. ``max_equity_fraction`` reads that same
   native ``balance_total`` (``strategy/forecast_mispricing/strategy.py:419``).
   So: any operator PnL surface or cash-based gate must read Breezy's own
   ledger (the durable fill records) or a fresh venue read, never native
   ``Position``/``Account`` PnL or balance, while a refusal is latched.
3. **The zero-price booking is the NORM for a foreign or unpriced instrument,
   not a rare edge.** With no ``QuoteTick`` cached, an unpriced forward books
   at 0.00 (module docstring, step 3 above). VERIFIED: if a ``QuoteTick`` IS
   cached for that instrument, ``_create_position_reconciliation_report``
   (``live/execution_engine.py:2871-2877``) instead books at the quote's
   ``ask_price`` for a BUY-side reconciliation. Neither outcome changes what
   this client does: the refusal in :meth:`_entry_price` latches the moment
   it returns ``None``, which happens BEFORE Nautilus ever computes a
   reconciliation price -- the latch does not depend on, and is not
   weakened by, whichever of the two Nautilus happens to book.
4. **Step 1's basis is the NET REMAINING COST BASIS, not the entry print --
   deliberately.** :meth:`_entry_price_from_records` nets
   ``sum(signed cost) / sum(signed qty)`` across every durable record, SELLs
   included with a negative sign. Chosen because it conserves LIFETIME
   REALIZED PNL across a cache-less restart. Worked example: BUY 4@0.50,
   then SELL 1@0.60 (realizing 0.10 on the exited contract) leaves a durable
   net basis of ``3 @ 0.4667`` (``(2.00 - 0.60) / 3``); settling the
   remaining 3 at 1.00 realizes ``1.60`` lifetime (``0.10`` already booked
   plus ``1.50`` on the remainder) -- exactly right. Nautilus's OWN in-memory
   same-side average (0.50, ignoring the exit) would instead realize
   ``1.50`` at settlement and silently lose the ``0.10`` already booked on
   the partial exit. So ``avg_px_open`` here is NOT "the price entered at"
   after a partial exit, and no R-5-or-later rule may read it as one.
5. **Step 2's fee-inclusion is UNOBSERVED.** Whether the venue's ``cost``
   field is net of trading fees is undefined by the snapshot
   (``types/portfolio.py:21-34``) and no live capture has settled it (every
   authenticated smoke run recorded a connectivity FAIL). A step-2 price is
   therefore sound for SIZING (the ``qtySold == 0`` condition removes the
   netting ambiguity) but UNVERIFIED for any PnL-truth purpose -- it is used
   here only because step 1 could not price the position at all, never as a
   substitute for step 1 where step 1 is available.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Final, Protocol, Self

from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.reports import PositionStatusReport
from nautilus_trader.live.execution_client import LiveExecutionClient
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.enums import (
    AccountType,
    LiquiditySide,
    OmsType,
    OrderSide,
    OrderStatus,
    OrderType,
    PositionSide,
)
from nautilus_trader.model.identifiers import (
    AccountId,
    ClientOrderId,
    InstrumentId,
    StrategyId,
    TradeId,
    VenueOrderId,
)
from nautilus_trader.model.objects import Money

import breezy.adapters.polymarket_us.write_transport as write_transport  # noqa: PLR0402
from breezy.adapters.polymarket_us.errors import (
    ExecutionReportMappingError,
    FeeScheduleUnknownError,
    PolymarketUSError,
    VenuePayloadError,
)
from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.adapters.polymarket_us.exec.endpoints import (
    ACCOUNT_BALANCES_PATH,
    PORTFOLIO_POSITIONS_PATH,
)
from breezy.adapters.polymarket_us.exec.refusals import (
    ClassifiedRefusal,
    PrivateReadRefused,
    RefusalClass,
    classify_venue_refusal,
    refusals_after_successful_reconcile,
)
from breezy.adapters.polymarket_us.exec.reports import (
    build_execution_mass_status,
    derive_position_cost_basis,
    parse_account_balances,
    parse_order_status_report,
    parse_position_status_report,
)
from breezy.adapters.polymarket_us.exec_fault import record_fatal_exec_fault
from breezy.adapters.polymarket_us.fees import polymarket_us_fee
from breezy.adapters.polymarket_us.parsing import _to_decimal
from breezy.adapters.polymarket_us.safety import (
    LiveTradingPermissionError,
    assert_live_order_submission_permitted,
    restore_live_trading_budget,
    unrestore_live_trading_budget,
)
from breezy.adapters.polymarket_us.symbology import instrument_id_to_slug, slug_to_instrument_id
from breezy.ingest.gate import assert_state_store_durable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from nautilus_trader.cache.cache import Cache
    from nautilus_trader.common.component import LiveClock, MessageBus
    from nautilus_trader.common.providers import InstrumentProvider
    from nautilus_trader.execution.messages import (
        BatchCancelOrders,
        CancelAllOrders,
        CancelOrder,
        GenerateFillReports,
        GenerateOrderStatusReport,
        GenerateOrderStatusReports,
        GeneratePositionStatusReports,
        ModifyOrder,
        QueryAccount,
        SubmitOrder,
        SubmitOrderList,
    )
    from nautilus_trader.execution.reports import (
        ExecutionMassStatus,
        FillReport,
        OrderStatusReport,
    )
    from nautilus_trader.model.identifiers import ClientId, Venue
    from nautilus_trader.model.instruments import Instrument
    from nautilus_trader.model.objects import Price, Quantity

    from breezy.ingest.gate import ClosableStateStore, StateStoreOpener

__all__ = [
    "BUDGET_RESTORE_KEY_PREFIX",
    "FILL_INDEX_KEY_PREFIX",
    "FILL_KEY_PREFIX",
    "RESOLVER_CONTEXT_KEY_PREFIX",
    "STARTUP_EVIDENCE_KEY",
    "VENUE_ORDER_ID_KEY_PREFIX",
    "AmbiguousResolverContext",
    "DurableFillRecord",
    "PolymarketUSExecutionClient",
    "PrivateRead",
    "StartupPositionEvidence",
    "StartupPositionSnapshot",
]

#: The venue-scoped namespace every durable key here sits under. A second
#: venue gets its OWN prefix; nothing is shared across venues by design.
STATE_KEY_NAMESPACE: Final[str] = "exec/polymarket_us/"

#: Venue ``id`` -> ``ClientOrderId``. This venue issues no client order id, so
#: without this map every Breezy order reconciles as ``StrategyId("EXTERNAL")``
#: (``execution_engine.py:3556``).
VENUE_ORDER_ID_KEY_PREFIX: Final[str] = f"{STATE_KEY_NAMESPACE}venue_id/"

#: Venue order id -> the fill record. Written at fill application (R-7), read
#: here to supply ``avg_px_open`` for a Breezy-opened position.
FILL_KEY_PREFIX: Final[str] = f"{STATE_KEY_NAMESPACE}fill/"

#: Instrument -> the venue order ids whose fill records belong to it. Needed
#: because the store has no prefix scan; see the module docstring.
FILL_INDEX_KEY_PREFIX: Final[str] = f"{STATE_KEY_NAMESPACE}fill_index/"

#: Resolution A/E (plan rev 6.1): intent_id -> the durable resolver context
#: for one with-id AMBIGUOUS create-order outcome. Written by
#: `_note_ambiguous_open` BEFORE `_resolve_ambiguous_intents` can ever
#: observe it. Each `intent_id` is a fresh UUID4 hex (`SubmitIntentLatch.
#: arm`), so an old key is never overwritten or collided with.
RESOLVER_CONTEXT_KEY_PREFIX: Final[str] = f"{STATE_KEY_NAMESPACE}resolver/"

#: C1 (plan rev 6.1): the strategy's never-arm/re-arm gate reads this key at
#: `on_start` and after every resolver terminal-zero resolution
#: (`read_startup_position_evidence`). Overwritten on EVERY write -- there is
#: exactly one row, the most recent evidence, never a history.
STARTUP_EVIDENCE_KEY: Final[str] = f"{STATE_KEY_NAMESPACE}startup_evidence"

#: D1/D2 (plan rev 6.1): durable, per-venue-order-id marker that a permit
#: slot was restored for it -- written by the CALLER (this client), never by
#: `safety.py`, which stores nothing of its own. Lets a LATER pass that
#: observes a genuine fill for the same id `unrestore` exactly what was
#: given back.
BUDGET_RESTORE_KEY_PREFIX: Final[str] = f"{STATE_KEY_NAMESPACE}budget_restore/"

#: How often `_resolve_ambiguous_intents` checks for a durable resolver
#: context on the currently-OPEN submit intent. Build-side; revisable.
_RESOLVER_POLL_INTERVAL_SECS: Final[float] = 5.0

#: Ceiling on the CONSECUTIVE-failure backoff below -- never wait longer
#: than this between resolver attempts no matter how many failures in a row.
_RESOLVER_BACKOFF_CAP_SECS: Final[float] = 300.0

#: Age of a durable resolver context's ``created_ns``, past which an intent
#: still AMBIGUOUS raises the one-shot stale-intent alert below.
_STALE_INTENT_ALERT_AFTER_NS: Final[int] = 15 * 60 * 1_000_000_000

#: The only order side Breezy OPENS with. ``allow_short=False`` is permanent
#: (``strategy/weather_common/risk.py:139``).
LONG_ONLY_SIDE: Final[str] = "BUY"

#: How a durable fill record's side enters the netting. An exit is not a short
#: and is not foreign: R-8/R-9 sell to CLOSE, and the remainder is still ours.
#: Any other side is refused rather than assigned a sign.
_RECORD_SIGNS: Final[Mapping[str, Decimal]] = {
    LONG_ONLY_SIDE: Decimal(1),
    "SELL": Decimal(-1),
}

_DEFAULT_INSTRUMENT_WAIT_SECONDS: Final[float] = 30.0
_DEFAULT_ACCOUNT_REGISTRATION_SECONDS: Final[float] = 30.0

#: I1b -- the durable fill write (``record_fill``) itself raised. ONE fixed
#: reason so `_refuse` dedupes on it (`_refuse` keys on the reason string,
#: not a per-exception message); the exception detail goes in the ERROR log
#: line instead, never here.
_FILL_WRITE_FAILED: Final[str] = (
    "the durable fill write raised; this client refuses further submits "
    "until an operator investigates"
)

#: I1b -- the record was written, but the venue's cumulative fee could not be
#: reconciled to its fill-type legs (`fee_reconciled=False`). The fill is
#: real; only the fee is untrusted, so retire/publish still proceed.
_FEE_UNRECONCILED: Final[str] = (
    "a durable fill record's venue fee could not be reconciled to its legs; "
    "this client refuses further submits until an operator investigates"
)

#: A1 -- the venue order id -> client order id map write raised. ONE fixed
#: reason so `_refuse` dedupes on it (`_refuse` keys on the reason string,
#: not a per-exception message); the exception detail goes in the ERROR log
#: line instead, never here -- and that log line is emitted by the A1 block
#: itself, before `_refuse`, so it is never deduped even when the reason
#: repeats (Trade-off 3/13).
_VENUE_ID_MAP_WRITE_FAILED: Final[str] = (
    "the venue order id -> client order id map write raised; this client "
    "refuses further submits until an operator investigates"
)


class PrivateRead(Protocol):
    """The injected authenticated read: one GET-shaped call, and nothing else.

    A protocol that cannot express a write verb cannot be asked to perform one
    -- the same reasoning as
    :class:`~breezy.adapters.polymarket_us.transport.PolymarketUSReadTransport`,
    one layer up. It is INJECTED rather than constructed here so that this
    module imports no network-capable client at all: the transport, the signer
    and the base URLs are assembled outside the ``exec/`` package, and barrier
    E0-INERT's transport-import ban keeps it that way.

    **On any non-2xx HTTP status, an implementation MUST raise
    :class:`~breezy.adapters.polymarket_us.exec.refusals.PrivateReadRefused`
    -- carrying that status, the bare ``path``, and the raw body -- rather
    than return a decoded mapping.** Before R-6.5a, the shipped closure
    (``factories.py``) discarded the status and decoded whatever body came
    back, so a 503 carrying a ``google.rpc.Status`` JSON object was handed to
    the caller as if it were a real payload and
    :func:`~breezy.adapters.polymarket_us.exec.refusals.classify_venue_refusal`
    could never be reached. This obligation binds every implementation,
    present or future -- a second venue (Kalshi) inherits it from this
    docstring rather than rediscovering the defect.
    """

    async def __call__(self, path: str) -> Mapping[str, Any]: ...


def _require_bool(value: object, *, field: str) -> bool:
    """``feeReconciled`` must decode to exactly ``bool`` -- never ``0``/``1``
    or a truthy string standing in for it (I1b)."""
    if not isinstance(value, bool):
        raise TypeError(f"{field} must be a JSON boolean, got {type(value).__name__}")
    return value


def _optional_venue_fee_raw(raw: object) -> str | None:
    """``venueFeeRaw`` is optional-on-read; a present value must be a string.

    ``str(payload.get("venueFeeRaw"))`` on a missing/null key would yield the
    string ``"None"`` and book a fake raw fee. Missing and JSON null are
    ``None``; anything else that is not ``str`` is a mapping error.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ExecutionReportMappingError(
            f"a durable fill record is malformed: venueFeeRaw must be a string "
            f"or null, got {type(raw).__name__}"
        )
    return raw


def _optional_trade_id(raw: object) -> str | None:
    """``tradeId`` is optional-on-read; a present value must be a string.

    ``None`` on a legacy record written before this field existed, or on an
    absent/null key. A present non-``str`` value is a mapping error, exactly
    like :func:`_optional_venue_fee_raw`.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ExecutionReportMappingError(
            f"a durable fill record is malformed: tradeId must be a string "
            f"or null, got {type(raw).__name__}"
        )
    return raw


def _optional_order_qty(raw: object) -> Decimal | None:
    """``orderQty`` is optional-on-read; a present value must be a finite
    decimal (S-M1).

    ``None`` on a legacy record written before this field existed, or on an
    absent/null key -- NEVER inferred from ``cumulative_qty`` and never
    defaulted to ``Decimal(1)``. A present non-finite value (``"NaN"``,
    ``"Infinity"``) is refused by :func:`_to_decimal`'s ``is_finite()`` guard.
    """
    if raw is None:
        return None
    return _to_decimal(raw, field="orderQty", error=ExecutionReportMappingError)


@dataclass(frozen=True, kw_only=True)
class DurableFillRecord:
    """What Breezy actually paid, on disk, CUMULATIVE per venue order.

    ``Decimal`` throughout and JSON-encoded as STRINGS: a fill price that went
    through a binary ``float`` on its way to disk would come back a different
    number, and this record is the sole evidence of a position's entry price
    after a restart.

    **Cumulative, not per fill, and the distinction is the routine case.** One
    order sweeping N ask levels produces N fills under ONE ``venue_order_id``,
    and the store is keyed by that id, so a per-fill record would be
    OVERWRITTEN N times and only the last clip would survive. The recorded size
    would then not match the venue's, and Breezy's OWN position would become
    unattributable on the ordinary path -- not on an edge case.

    So a rewrite is a MONOTONE UPDATE of one order's running totals, which is
    also the shape the venue reports natively: ``cumQuantity`` and ``avgPx``
    (``types/orders.py:70-92``), from which R-7 forms
    ``cumulative_cost = cumQuantity * avgPx``. Cost rather than an average
    price is stored because averaging ACROSS orders is then a plain sum --
    ``sum(cost) / sum(qty)`` -- with no re-weighting step to get wrong.

    ``order_side`` keeps its sign: a SELL record NETS against the longs (an
    R-8/R-9 partial exit), it does not poison the instrument.
    """

    venue_order_id: str
    client_order_id: str
    instrument_id: str
    order_side: str
    cumulative_qty: Decimal
    cumulative_cost: Decimal
    cumulative_fee: Decimal
    fee_reconciled: bool
    ts_event: int
    venue_fee_raw: str | None = None
    #: B0: an opaque venue-or-synthetic match id (create: the venue's own
    #: ``Execution.tradeId``; resolver: the self-labelling ``GET-<venue_order_id>``
    #: synthetic form) -- two provenances under one field, never a
    #: ``tradeIdSource``. ``None`` on a legacy record (S-M1).
    trade_id: str | None = None
    #: B0: the ORIGINAL order size in contracts -- NOT the filled size.
    #: ``None`` on a legacy record; never inferred from ``cumulative_qty``,
    #: never defaulted to ``Decimal(1)`` (S-M1).
    order_qty: Decimal | None = None

    def to_bytes(self) -> bytes:
        return json.dumps(
            {
                "venueOrderId": self.venue_order_id,
                "clientOrderId": self.client_order_id,
                "instrumentId": self.instrument_id,
                "orderSide": self.order_side,
                "cumulativeQty": str(self.cumulative_qty),
                "cumulativeCost": str(self.cumulative_cost),
                "cumulativeFee": str(self.cumulative_fee),
                "feeReconciled": self.fee_reconciled,
                "tsEvent": self.ts_event,
                "venueFeeRaw": self.venue_fee_raw,
                "tradeId": self.trade_id,
                "orderQty": None if self.order_qty is None else str(self.order_qty),
            },
            sort_keys=True,
        ).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        """Decode a record, refusing anything that is not exactly one.

        Every field is required except ``venueFeeRaw``, ``tradeId`` and
        ``orderQty``, which are optional-on-read so pre-GL-2/pre-B0 records
        still decode (``None``). A present non-string ``venueFeeRaw``/
        ``tradeId``, or a present non-finite ``orderQty``, is refused. A
        partially-decodable record is refused rather than defaulted: a fill
        record missing its price is not a fill record with a zero price.
        """
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise ExecutionReportMappingError(
                f"a durable fill record is not valid JSON ({len(raw)} bytes): {exc}"
            ) from None
        if not isinstance(payload, dict):
            raise ExecutionReportMappingError(
                f"a durable fill record decoded to a {type(payload).__name__}, not an object"
            )
        try:
            return cls(
                venue_order_id=str(payload["venueOrderId"]),
                client_order_id=str(payload["clientOrderId"]),
                instrument_id=str(payload["instrumentId"]),
                order_side=str(payload["orderSide"]),
                # `_to_decimal` (parsing.py) refuses non-finite values via
                # `is_finite()`. A bare `Decimal(str(...))` here decoded
                # "NaN"/"Infinity" cleanly, and the later `net_cost <= 0`
                # comparison in `_entry_price_from_records` then raised
                # `decimal.InvalidOperation` OUTSIDE any per-position `try`
                # -- propagating to `generate_mass_status`'s OUTER except and
                # discarding every position report, not just this one.
                cumulative_qty=_to_decimal(
                    payload["cumulativeQty"],
                    field="cumulativeQty",
                    error=ExecutionReportMappingError,
                ),
                cumulative_cost=_to_decimal(
                    payload["cumulativeCost"],
                    field="cumulativeCost",
                    error=ExecutionReportMappingError,
                ),
                cumulative_fee=_to_decimal(
                    payload["cumulativeFee"],
                    field="cumulativeFee",
                    error=ExecutionReportMappingError,
                ),
                fee_reconciled=_require_bool(payload["feeReconciled"], field="feeReconciled"),
                ts_event=int(payload["tsEvent"]),
                venue_fee_raw=_optional_venue_fee_raw(payload.get("venueFeeRaw")),
                trade_id=_optional_trade_id(payload.get("tradeId")),
                order_qty=_optional_order_qty(payload.get("orderQty")),
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ExecutionReportMappingError(
                f"a durable fill record is malformed: {type(exc).__name__}: {exc}"
            ) from None


@dataclass(frozen=True, slots=True)
class AmbiguousResolverContext:
    """Resolution A/E (plan rev 6.1): durable evidence for one with-id
    AMBIGUOUS create-order outcome, written by ``_note_ambiguous_open``
    BEFORE ``_resolve_ambiguous_intents`` can ever observe it.

    ``booking_id`` is process-local context ONLY -- the ledger it names dies
    with the process (restart re-entry never re-derives a booking from this
    field; it retires and clears with no true-up and no restore, since the
    reminted budget already starts whole).
    """

    intent_id: str
    venue_order_id: str
    instrument_id: str
    client_order_id: str
    strategy_id: str
    notional_usd: Decimal
    booking_id: int
    created_ns: int
    # SP-2 I3 (L-37 (2)/(3)): names-only, already capped by the producer
    # (`submit_chain._capped_diagnostic` / `_detail_tree_token`) -- this
    # class never truncates. Trailing-optional so an OLD blob (written
    # before this change) still decodes with both `None` (AR-N6); no
    # schema version, no migration. AC-19's disqualification rule: a
    # captured row carrying an AUTHENTIC truncation marker, `<depth-capped>`,
    # `+N more`, or a `\xNN` escape is incomplete evidence and must not be
    # used to declare `_EXECUTION_DRIFT_ALLOWED_KEYS` (I4/R-6) -- re-capture,
    # or raise the cap in a follow-up, never remove it.
    create_detail: str | None = None
    fill_parse_error: str | None = None

    def to_bytes(self) -> bytes:
        return json.dumps(
            {
                "intentId": self.intent_id,
                "venueOrderId": self.venue_order_id,
                "instrumentId": self.instrument_id,
                "clientOrderId": self.client_order_id,
                "strategyId": self.strategy_id,
                "notionalUsd": str(self.notional_usd),
                "bookingId": self.booking_id,
                "createdNs": self.created_ns,
                "createDetail": self.create_detail,
                "fillParseError": self.fill_parse_error,
            },
            sort_keys=True,
        ).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise ExecutionReportMappingError(
                f"a durable resolver context is not valid JSON ({len(raw)} bytes): {exc}"
            ) from None
        if not isinstance(payload, dict):
            raise ExecutionReportMappingError(
                f"a durable resolver context decoded to a {type(payload).__name__}, "
                "not an object"
            )
        # Trailing-optional fields are read OUTSIDE the strict `try` below,
        # via `.get(...)`, so an old blob that never carried them still
        # decodes -- `KeyError` there is precisely what must NOT happen.
        raw_create_detail = payload.get("createDetail")
        create_detail = None if raw_create_detail is None else str(raw_create_detail)
        raw_fill_parse_error = payload.get("fillParseError")
        fill_parse_error = None if raw_fill_parse_error is None else str(raw_fill_parse_error)
        try:
            return cls(
                intent_id=str(payload["intentId"]),
                venue_order_id=str(payload["venueOrderId"]),
                instrument_id=str(payload["instrumentId"]),
                client_order_id=str(payload["clientOrderId"]),
                strategy_id=str(payload["strategyId"]),
                notional_usd=_to_decimal(
                    payload["notionalUsd"],
                    field="notionalUsd",
                    error=ExecutionReportMappingError,
                ),
                booking_id=int(payload["bookingId"]),
                created_ns=int(payload["createdNs"]),
                create_detail=create_detail,
                fill_parse_error=fill_parse_error,
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ExecutionReportMappingError(
                f"a durable resolver context is malformed: {type(exc).__name__}: {exc}"
            ) from None


@dataclass(frozen=True, slots=True)
class StartupPositionSnapshot:
    """One venue slug's net position, as recorded in :class:`StartupPositionEvidence`.

    Item 2 (slice 4 review, CRITICAL, shared with the strategy seam):
    ``net_position`` is ``None`` when the venue's own entry for ``slug`` was
    missing or malformed -- UNKNOWN, never a synonym for flat. EVERY slug the
    page named is recorded, dropped or not: the latch treats an ABSENT slug
    as a confirmed-flat zero, so silently omitting a slug this page could not
    parse would let a real LONG be armed over.
    """

    slug: str
    net_position: str | None


@dataclass(frozen=True, slots=True)
class StartupPositionEvidence:
    """C1 (plan rev 6.1): durable startup/re-arm evidence for the strategy's
    never-arm gate, read via
    :meth:`PolymarketUSExecutionClient.read_startup_position_evidence`.

    Written at the END of ``_connect`` (after reconciliation and this
    client's own positions read) and rewritten after every resolver
    terminal-zero resolution, so the gate is never reading a boot-time
    snapshot. Every flag must be exactly ``True`` -- and
    ``position_read_refused`` exactly ``False`` -- for the gate to treat the
    book as known; an EMPTY ``positions`` without ``eof_complete`` is
    UNKNOWN, never "flat".
    """

    ts_ns: int
    eof_complete: bool
    position_read_refused: bool
    fill_walk_complete: bool
    positions: tuple[StartupPositionSnapshot, ...]

    def to_bytes(self) -> bytes:
        return json.dumps(
            {
                "v": 1,
                "ts_ns": self.ts_ns,
                "eof_complete": self.eof_complete,
                "position_read_refused": self.position_read_refused,
                "fill_walk_complete": self.fill_walk_complete,
                "positions": [
                    {"slug": p.slug, "net_position": p.net_position} for p in self.positions
                ],
            },
            sort_keys=True,
        ).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise ExecutionReportMappingError(
                f"startup position evidence is not valid JSON ({len(raw)} bytes): {exc}"
            ) from None
        if not isinstance(payload, dict):
            raise ExecutionReportMappingError(
                f"startup position evidence decoded to a {type(payload).__name__}, not an object"
            )
        try:
            if int(payload["v"]) != 1:
                raise ExecutionReportMappingError(
                    f"startup position evidence has an unknown schema version {payload['v']!r}"
                )
            raw_positions = payload["positions"]
            if not isinstance(raw_positions, list):
                raise ExecutionReportMappingError(
                    "startup position evidence 'positions' is not a list"
                )
            snapshots = tuple(
                StartupPositionSnapshot(
                    slug=str(entry["slug"]),
                    net_position=(
                        None if entry["net_position"] is None else str(entry["net_position"])
                    ),
                )
                for entry in raw_positions
            )
            return cls(
                ts_ns=int(payload["ts_ns"]),
                eof_complete=_require_bool(payload["eof_complete"], field="eof_complete"),
                position_read_refused=_require_bool(
                    payload["position_read_refused"], field="position_read_refused"
                ),
                fill_walk_complete=_require_bool(
                    payload["fill_walk_complete"], field="fill_walk_complete"
                ),
                positions=snapshots,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ExecutionReportMappingError(
                f"startup position evidence is malformed: {type(exc).__name__}: {exc}"
            ) from None


#: Resolution C/D (plan rev 6.1), widened by the partial-fill review: the
#: native statuses a GET-resolved ``OrderStatusReport`` can carry when it is
#: TERMINAL -- the exact analogue of
#: ``submit_chain._IOC_ZERO_FILL_TERMINAL_STATES``, on the native enum this
#: report uses instead of the raw venue string. This same set now covers
#: BOTH terminal outcomes: with ``filled_qty == 0`` it is Resolution D
#: (terminal-zero, ``_resolve_terminal_zero``); with ``filled_qty > 0`` it is
#: a TERMINAL-FILL -- the normal IOC partial-fill shape once
#: ``minimumTradeQty`` dropped to 0.01 (a CANCELED/EXPIRED order can still
#: carry real filled shares) -- resolved by ``_resolve_accept_fill`` exactly
#: like a full FILLED.
_RESOLVER_TERMINAL_STATUSES: Final[frozenset[OrderStatus]] = frozenset(
    {OrderStatus.CANCELED, OrderStatus.REJECTED, OrderStatus.EXPIRED}
)
#: A GET-resolved report carrying a COMPLETE fill. ``PARTIALLY_FILLED`` is
#: deliberately EXCLUDED: it is a LIVE state -- the order can still receive
#: more fills or reach a terminal status later -- and must NEVER resolve the
#: intent. Only a genuinely terminal status ends it: ``FILLED`` here, or one
#: of ``_RESOLVER_TERMINAL_STATUSES`` with ``filled_qty > 0`` (the
#: terminal-fill case above).
_RESOLVER_FILL_STATUSES: Final[frozenset[OrderStatus]] = frozenset({OrderStatus.FILLED})


def _resolver_long_position_state(positions: Mapping[str, Any], slug: str) -> bool | None:
    """Resolution C: ``True`` -- a LONG is present at ``slug``. ``False`` --
    confirmed no LONG (the slug is absent, which IS a confirmed zero
    position). ``None`` -- undetermined (malformed ``netPosition``); the
    caller MUST treat this exactly like a read failure: take no action,
    stay AMBIGUOUS, try again next pass. Never ``_refuse``s.
    """
    payload = positions.get(slug)
    if payload is None:
        return False
    if not isinstance(payload, Mapping):
        return None
    net_raw = payload.get("netPosition")
    if net_raw is None:
        return None
    try:
        net = _to_decimal(net_raw, field="netPosition", error=ExecutionReportMappingError)
    except ExecutionReportMappingError:
        return None
    return net > 0


def _synthetic_get_fill_trade_id(venue_order_id: str) -> TradeId:
    """Slice 3: a pure, deterministic function of ``venue_order_id`` alone.

    The venue never issues a per-execution trade id for a GET-confirmed
    fill (the Order schema has no execution legs) -- this is Breezy's OWN
    synthetic id, prefixed ``GET-`` so it is VISIBLY distinguishable from a
    venue-issued trade id anywhere it is logged or compared. Same input,
    same output, always: no clock, no counter, no randomness.
    """
    return TradeId(f"GET-{venue_order_id}")


class PolymarketUSExecutionClient(LiveExecutionClient):
    """Reconciles the Polymarket.us account, and refuses every order.

    See the module docstring for the null-hypothesis verdicts, the durable
    store's justification, and why every LONG the venue reports is forwarded --
    priced from our own fill records where we have them, from the venue's cost
    basis where that is sound, and unpriced-plus-refused otherwise.
    """

    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        client_id: ClientId,
        venue: Venue,
        instrument_provider: InstrumentProvider,
        msgbus: MessageBus,
        cache: Cache,
        clock: LiveClock,
        private_read: PrivateRead,
        state_store_opener: StateStoreOpener,
        account_number: str,
        instrument_wait_timeout_s: float = _DEFAULT_INSTRUMENT_WAIT_SECONDS,
        account_registration_timeout_s: float = _DEFAULT_ACCOUNT_REGISTRATION_SECONDS,
        order_sender: Any = None,
        write_signer: Any = None,
        live_trading_permit: Any = None,
        spend_ledger: Any = None,
        submit_intent_latch: Any = None,
        credentials: Any = None,
        api_base_url: str = "",
        retirement_reasons: Any = None,
        submit_veto: Callable[[], str | None] | None = None,
    ) -> None:
        """Build the client. Every input is checked here, not at first use.

        The two operator-reserved controls -- max daily budget and max per
        position -- are **not** parameters of this class and are not read
        anywhere in it. Their absence fails closed, and this increment refuses
        every order unconditionally, which is strictly stronger than any cap.

        ``callable()`` is the strongest check available on ``private_read``
        here: it excludes a non-callable, and it does NOT establish that the
        call returns an awaitable. A synchronous callable passed in its place
        fails at the first ``await`` inside :meth:`_publish_account_state`, not
        at construction. Narrowing that would need a call, and calling an
        injected venue read at construction time is the one thing this class
        must not do.
        """
        if not callable(private_read):
            raise TypeError("private_read must be a callable; it is awaited at use")
        if not callable(state_store_opener):
            raise TypeError("state_store_opener must be callable")
        if not isinstance(account_number, str) or not account_number.strip():
            raise ValueError(
                "account_number must be a non-empty string; it becomes the "
                "AccountId suffix and cannot be derived from anything else"
            )
        for name, timeout in (
            ("instrument_wait_timeout_s", instrument_wait_timeout_s),
            ("account_registration_timeout_s", account_registration_timeout_s),
        ):
            # `bool` is a subclass of `int`, so a bare `isinstance(x, int)`
            # accepts `True` and this client would then wait ONE second for the
            # instrument load. A boolean where a duration was declared is a
            # wiring bug, and a plausible-looking one.
            if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
                raise ValueError(f"{name} must be a positive number, got {timeout!r}")

        super().__init__(
            loop=loop,
            client_id=client_id,
            venue=venue,
            # NETTING: one position per instrument, which is what a binary
            # market is. CASH with a USD base currency, because Polymarket.us
            # is fully collateralised; `AccountType.BETTING` is banned by
            # barrier X2 -- it models back/lay stake, not a 0-1 binary.
            oms_type=OmsType.NETTING,
            account_type=AccountType.CASH,
            base_currency=USD,
            instrument_provider=instrument_provider,
            msgbus=msgbus,
            cache=cache,
            clock=clock,
        )

        self._private_read: PrivateRead = private_read
        self._state_store_opener: StateStoreOpener = state_store_opener
        # Stored as handed in. No `float()` coercion: barrier E0's sibling
        # structural pin bans a `float` call anywhere under `exec/`, because
        # it cannot tell a timeout from a price -- and it is right not to try.
        self._instrument_wait_timeout_s: float = instrument_wait_timeout_s
        self._account_registration_timeout_s: float = account_registration_timeout_s

        # `_set_account_id` (`execution/client.pyx:148-152`) requires the
        # issuer to equal the client id, so the id is derived, never supplied.
        self._issued_account_id: AccountId = AccountId(
            f"{client_id.value}-{account_number.strip()}",
        )

        self._store: ClosableStateStore | None = None
        self._store_thread: int | None = None
        self._trading_refusals: list[ClassifiedRefusal] = []
        self._settled_positions: list[InstrumentId] = []
        self._order_sender = order_sender
        self._write_signer = write_signer
        self._permit = live_trading_permit
        self._ledger = spend_ledger
        # The composition root's ALREADY-OPENED latch -- see
        # `_reconcile_submit_intent` and `_disconnect`.
        self._latch: Any = submit_intent_latch
        self._credentials = credentials
        self._api_base_url = api_base_url
        self._retirement_reasons = retirement_reasons
        # Item 4 (slice 4 review): the family-halt chokepoint veto, injected
        # exactly the way the submit-intent latch is -- a plain callable this
        # adapters-layer module never imports the type of. `None` -> no veto,
        # matching every composition root that predates this parameter.
        self._submit_veto = submit_veto
        self._intent_reconciled: bool = False
        # Resolution A/E (plan rev 6.1): the live `SpendBooking` for a
        # with-id AMBIGUOUS intent, held ONLY for same-process true-up.
        # Restart re-entry finds this dict empty (the ledger died too) and
        # correctly skips true-up/release -- the reminted budget already
        # starts whole.
        self._ambiguous_bookings: dict[str, Any] = {}
        # SAFETY H2: set ONLY by a terminal GET the resolver itself makes in
        # THIS run. A durable record can schedule a GET; it can never
        # authorize a retirement on its own.
        self._resolved_by_get_ts_ns: dict[str, int] = {}
        self._resolver_task: asyncio.Task[None] | None = None
        #: Review fix 3 (Slice 2): a corrupt singleton is logged at ERROR
        #: ONCE, not every poll interval for the process lifetime.
        self._resolver_corrupt_logged = False
        # Item 1 (slice 4 review): a resolver action raising must never kill
        # the polling task for the process lifetime. The counter increments
        # on EVERY caught failure (so "no intents" and "resolver dead" are
        # distinguishable); the log is deduped per intent id so a still-open
        # intent that fails every poll does not spam the log at the poll
        # interval.
        self._resolver_error_count: int = 0
        self._resolver_errored_intent_ids: set[str] = set()
        # Item 2 (2026-09-11 incident addendum): consecutive resolver
        # failures (mapping error, GET exception, 5xx) since the last
        # successful GET -- drives the bounded exponential backoff inlined
        # in `_resolve_ambiguous_intents` itself (never a helper method: a
        # new callee there is an E0-NOSEND-RESOLVER violation against
        # ``tests/unit/test_execution_egress_firewall_guard.py``, which
        # stays untouched). Reset to 0 by that same coroutine on any
        # successful GET.
        self._resolver_consecutive_failures: int = 0
        self._resolver_last_failure_kind: dict[str, str] = {}
        # Item 3 (2026-09-11 incident addendum): one-shot stale-intent
        # bookkeeping for `stale_ambiguous_intent_alerts` above. An intent id
        # enters `_resolver_stale_alerted_intent_ids` the first time its
        # durable context's age crosses `_STALE_INTENT_ALERT_AFTER_NS` while
        # still unresolved (never re-added while it stays the same OPEN
        # intent); `_retire` drops both entries on retirement. Mutated ONLY
        # by whole-value reassignment (`x = x | {...}` / dict-unpacking),
        # never `.add`/`.update`, for the same E0-NOSEND-RESOLVER reason.
        self._resolver_stale_alerted_intent_ids: frozenset[str] = frozenset()
        self._resolver_stale_alert_details: dict[str, Mapping[str, str]] = {}

    # -- observable state ---------------------------------------------------

    @property
    def trading_refusals(self) -> tuple[str, ...]:
        """Every reason this client would refuse to trade, in the order found.

        Populated by reconciliation. R-4 refuses every order regardless; this
        is the evidence an operator needs about WHY the venue state could not
        be attributed, and it is what R-6/R-7 key their own refusal on.

        R-6.5a: the internal latch is now a list of
        :class:`~breezy.adapters.polymarket_us.exec.refusals.ClassifiedRefusal`
        (TRANSIENT/DURABLE), never exposed here -- every existing consumer of
        this property reads reason strings, and none of them move.
        """
        return tuple(refusal.reason for refusal in self._trading_refusals)

    @property
    def resolver_error_count(self) -> int:
        """Item 1 (slice 4 review): total resolver-action failures caught so
        far, for the health surface. Distinguishes "no AMBIGUOUS intents to
        resolve" (stays 0) from "the resolver keeps failing" (climbs) -- the
        polling task itself never dies either way."""
        return self._resolver_error_count

    @property
    def settled_positions(self) -> tuple[InstrumentId, ...]:
        """Instruments the venue reports as EXPIRED with a nonzero position.

        Routine, not an error -- every weather binary settles -- but never
        live risk, so these are excluded from the mass status.
        """
        return tuple(self._settled_positions)

    @property
    def state_store_owner_thread(self) -> int | None:
        """The thread ident the durable store was constructed on.

        Exposed because thread affinity is a hard precondition, not an
        implementation detail: a store built anywhere but the loop that writes
        it passes every other test and fails only at run time.
        """
        return self._store_thread

    # -- lifecycle ----------------------------------------------------------

    async def _connect(self) -> None:
        """Open the durable store, load instruments, publish the account.

        Ordering is deliberate. The account id is set first so that a mass
        status is always attributable even if a later step degrades; the store
        is opened HERE so it is constructed on the loop thread that writes it;
        durability is proven by round-trip before anything is written to it.

        **Wrapped in a fault latch, deliberately not a swallow.** Every
        statement below either raises (a durability failure at
        :meth:`_open_state_store`) or refuses internally and returns (the
        instrument wait, the registration wait) -- except
        :meth:`_publish_account_state`, which has no internal try/except and
        propagates whatever the injected venue read raises. Left unwrapped,
        such a failure is swallowed by the NATIVE task-completion handler
        (``nautilus_trader/live/execution_client.py:212-226``): it logs the
        exception and simply skips ``_set_connected(True)``, so the task
        completes normally and ``breezy-trade`` would exit ``EXIT_OK`` having
        never reconciled (EXEC SPINE risk 2). Recording the fault here, then
        RE-RAISING unchanged, adds an observable trace without altering the
        native control flow one bit -- the same "record, then re-raise"
        idiom :meth:`_open_state_store` already uses for its own durability
        failure.

        **Also requests the native shutdown, which the latch alone did not.**
        ``BALANCES_SHAPE_DRIFT_2026-09-04.md``: latching the fault here was
        already live, but nothing asked the kernel to stop -- the node stayed
        ``RUNNING`` with ``ExecEngine.check_connected() == False`` for 60s
        until killed by hand. ``self.shutdown_system(reason)``
        (``Component.shutdown_system``, ``common/component.pyx:2163-2183``)
        publishes the native ``ShutdownSystem`` command on
        ``"commands.system.shutdown"``, which ``NautilusKernel
        ._on_shutdown_system`` (``system/kernel.py:613-628``) turns into a
        clean ``stop_async()`` -- the SAME mechanism
        :meth:`~breezy.adapters.polymarket_us.data.PolymarketUSDataClient
        ._request_fatal_shutdown` already uses for a data-client connect
        failure. No parallel shutdown path is introduced: this calls the one
        native method directly rather than re-deriving the data client's
        retry-budgeted watchdog wrapper, which exists for a long-lived polling
        loop this coroutine is not.
        """
        try:
            self._set_account_id(self._issued_account_id)
            self._open_state_store()
            # Resolution A (plan rev 6.1): started here, unconditionally,
            # for the client's lifetime -- a named, firewall-scanned
            # coroutine (`EXEC_RESOLVER_COROUTINES`), never awaited inline.
            # It is a no-op every pass until an AMBIGUOUS outcome writes a
            # durable resolver context via `_note_ambiguous_open`.
            self._resolver_task = self.create_task(
                self._resolve_ambiguous_intents(),
                log_msg="resolve_ambiguous_intents",
            )
            await self._wait_for_instruments()
            # Item 2 (2026-09-12 boot-ordering addendum): ONE synchronous,
            # bounded resolver pass -- AWAITED here, not merely scheduled --
            # after instruments are loaded (the pass needs
            # `self._cache.instrument(...)` to resolve anything) but still
            # well before this method returns and before Nautilus's own
            # kernel-level reconciliation ever runs. A boot with nothing to
            # resolve (no latch bound yet, or no OPEN intent) completes this
            # with no sleep and no observable delay -- see
            # `_resolve_ambiguous_intents`'s `first_pass_immediate` docstring.
            # The periodic task above still runs for the client's lifetime;
            # this is an ADDITIONAL early pass, not a replacement.
            #
            # Review fix (2026-09-12): caught LOCALLY, deliberately narrower
            # than this method's own `except BaseException` below. The
            # periodic task's exceptions are only ever logged by Nautilus's
            # native `_on_task_completed` -- never fatal -- and this
            # immediate call must fail exactly the same way, not latch a
            # fatal fault and shut the node down at boot over a transient
            # read this SAME coroutine's periodic run would retry moments
            # later. Only `type(exc).__name__` is logged, never `exc` or any
            # resolver-context value (durable state can carry venue ids).
            try:
                await self._resolve_ambiguous_intents(first_pass_immediate=True)
            except Exception as exc:  # noqa: BLE001 - see comment above
                self._log.warning(
                    f"immediate resolver pass failed; periodic resolver "
                    f"continues ({type(exc).__name__})"
                )
            await self._publish_account_state()
            await self._confirm_account_registered()
            self._reconcile_submit_intent()
            # C1 (plan rev 6.1): the strategy's never-arm gate needs FRESH
            # startup evidence, taken AFTER reconciliation -- last, not
            # first, so a position opened or closed by whatever reconcile
            # observed is reflected in it. Never raises: a read failure is
            # RECORDED as refused, never propagated (see the method's own
            # docstring for why).
            await self._refresh_startup_position_evidence()
        except BaseException as exc:
            reason = (
                f"_connect failed before the client reached a connected "
                f"state ({type(exc).__name__}: {exc}); no order can ever "
                "be evaluated against a client that never connected"
            )
            record_fatal_exec_fault(component=str(self.id), reason=reason)
            self.shutdown_system(reason)
            raise

    def _has_durable_fill_record(self, fingerprint: str) -> bool:
        """Nothing supplies a fill probe today; absence is False, never synthesised."""
        del fingerprint
        return False

    def _reconcile_submit_intent(self) -> None:
        """Reconcile the INJECTED (composition-root-opened) latch before any
        ``arm`` (R-7). This client never opens one (L-22). Unset, D6 denies
        every order; the thread assertion fails closed against a cross-
        thread adoption, which would race the latch's own ``threading.Lock``.
        """
        if self._latch is None or self._store is None:
            self._intent_reconciled = False
            return
        assert threading.get_ident() == self._latch.opening_thread_ident, (
            "the submit-intent latch must be reconciled on the thread that "
            "opened it; this client never opens its own latch and refuses "
            "to adopt one from another thread"
        )
        self._latch.reconcile_at_startup(
            has_durable_fill_record=self._has_durable_fill_record,
            now_ns=self._clock.timestamp_ns(),
        )
        self._intent_reconciled = True

    def _resolver_poll_interval_secs(self) -> float:
        """Overridable seam: tests shrink this to iterate the loop fast."""
        return _RESOLVER_POLL_INTERVAL_SECS

    @property
    def stale_ambiguous_intent_alerts(self) -> tuple[Mapping[str, str], ...]:
        """Item 3 (2026-09-11 incident addendum): the health surface for a
        still-OPEN, still-unresolved intent whose durable context's age has
        crossed `_STALE_INTENT_ALERT_AFTER_NS`.

        **Read-only surface, deliberately -- not an emitted alert.** This
        module cannot call `breezy.runtime.health.emit_alert` (barrier
        E0-TRANSPORT, `_refuse`'s own docstring) or add a new callee to
        `_resolve_ambiguous_intents` (E0-NOSEND-RESOLVER,
        ``tests/unit/test_execution_egress_firewall_guard.py``, which stays
        untouched). Exactly like `trading_refusals` / `resolver_error_count`
        above, the resolver only RECORDS the condition here; the runtime
        layer's health-watch subscriber is the one place with both an
        `AlertSink` and permission to import it, and is where the CRITICAL
        `open_intent_stale` `AlertPayload` (intent_id, venue_order_id, age
        in minutes, last failure kind) is built from this tuple.

        One entry per currently-latched intent id -- `_retire` (the single
        chokepoint every resolution path runs through) drops the entry the
        moment the intent retires, so a LATER intent reaching the same age
        surfaces again.
        """
        return tuple(self._resolver_stale_alert_details.values())

    async def _resolve_ambiguous_intents(self, *, first_pass_immediate: bool = False) -> None:
        """Resolution A (plan rev 6.1): named, firewall-scanned client
        coroutine for the with-id AMBIGUOUS class (L-36). Started from
        ``_connect`` after ``_open_state_store``; runs for the client's
        lifetime.

        Item 2 (2026-09-12 boot-ordering addendum): ``first_pass_immediate``
        makes this call run EXACTLY ONE pass, with NO initial sleep, and
        then return -- ``_connect`` awaits it directly (bounded to the
        single GET + retire attempt this docstring already describes) so a
        durable fill record for an already-OPEN with-id intent exists
        before ``_connect`` returns, ahead of Nautilus's own kernel-level
        reconciliation. The default (``False``, used by the periodic
        background task ``_connect`` also still starts) reproduces today's
        behaviour exactly: every iteration sleeps first, forever. No new
        callee is introduced -- the gate below is pure boolean logic, never
        a call, so it is invisible to ``find_exec_resolver_violations``.

        Each pass is a no-op unless the account-wide submit intent is OPEN
        with a durable resolver context (written by ``_note_ambiguous_open``
        -- a no-id AMBIGUOUS never gets one, and stays operator-only). GET
        exception, 5xx, malformed body, PENDING/non-terminal status, or
        not-found all leave the pass with NOTHING done: the intent stays
        AMBIGUOUS and the NEXT pass tries again -- exhaustion of one pass's
        evidence gathering is never terminal.

        Bypasses ``generate_order_status_report`` deliberately (ARCH M1):
        that method collapses four distinct failure shapes into ``None``,
        and fail-open is the one outcome this design forbids. This
        coroutine calls ``_private_read`` + ``submit_chain.order_by_id_path``
        + ``parse_order_status_report`` directly, so a read failure and an
        unmappable body are each observed for what they are.

        Crash safety: a crash between ``_retire`` and ``generate_order_
        filled`` (or ``generate_order_canceled``) loses only the in-process
        native event -- acceptable because this client's Nautilus ``Cache``
        is ``database=None`` (no native event persists across a restart
        regardless), and the durable fill record ``record_fill`` wrote
        BEFORE ``_retire`` is the source of truth: a later increment's
        never-arm ``on_start`` walk replays it into TRIAL state (next
        slice), so nothing this record represents is actually lost.

        The LONG gate (``_resolver_long_position_state``) is slug-level
        ``netPosition > 0`` corroboration ONLY, never magnitude-matched
        against the GET's own ``filled_qty`` -- the order-specific GET
        report is the sole authority for the quantity and price a fill is
        synthesized from; the positions read exists only to confirm a LONG
        exists at all before acting.
        """
        first_iteration = True
        while True:
            # Item 2 (2026-09-12 boot-ordering addendum): a one-shot caller
            # (`first_pass_immediate=True`) returns here on its SECOND trip
            # through the loop top -- i.e. after exactly one pass, however
            # that pass ended (an early `continue` branch below, or falling
            # off the end of the loop body). Pure booleans, no new callee.
            if first_pass_immediate and not first_iteration:
                return
            if not (first_pass_immediate and first_iteration):
                # Item 2 (2026-09-11 incident addendum): bounded exponential
                # backoff on CONSECUTIVE resolver failures, inlined here rather
                # than in a helper method -- a new callee in THIS coroutine is
                # an E0-NOSEND-RESOLVER violation
                # (``tests/unit/test_execution_egress_firewall_guard.py``,
                # which stays untouched), and every name below (`asyncio.sleep`,
                # `self._resolver_poll_interval_secs`) is already permitted.
                # Base interval unaffected: 0.0 doubled is still 0.0, so tests
                # that shrink the base to iterate fast see no behaviour change.
                # 5s, 5s, 10s, 20s, ... capped at `_RESOLVER_BACKOFF_CAP_SECS`.
                base_interval = self._resolver_poll_interval_secs()
                if self._resolver_consecutive_failures <= 0:
                    sleep_secs = base_interval
                else:
                    doubled = base_interval * (2 ** (self._resolver_consecutive_failures - 1))
                    # Deliberately NOT `min(...)`: a builtin call here is a new,
                    # unpermitted callee under E0-NOSEND-RESOLVER (see above).
                    sleep_secs = doubled if doubled < _RESOLVER_BACKOFF_CAP_SECS else _RESOLVER_BACKOFF_CAP_SECS  # noqa: E501, FURB136
                await asyncio.sleep(sleep_secs)
            first_iteration = False
            if self._latch is None:
                self._log.debug("resolver: no latch bound; skipping this pass")
                continue
            try:
                current = self._latch.current_open()
            except self._latch.CorruptError:
                # Fail closed like `is_latched()` does: a corrupt singleton
                # is treated as OPEN-unknown -- never retire, never act, but
                # the task itself must survive. Polling continues rather
                # than stopping: an operator's `breezy-clear-submit-intent`
                # rewrites the record out from under this, and the very
                # next pass would then observe a valid one again. Logged
                # ONCE so a persistent corruption does not spam every poll
                # interval for the process lifetime.
                if not self._resolver_corrupt_logged:
                    self._resolver_corrupt_logged = True
                    self._log.error(
                        "resolver: the submit-intent singleton is corrupt; "
                        "treating it as OPEN-unknown and continuing to poll "
                        "(fail closed, never retiring on unreadable state)"
                    )
                continue
            if current is None:
                self._log.debug("resolver: no OPEN intent; nothing to resolve this pass")
                continue
            raw_context = self._store_get(f"{RESOLVER_CONTEXT_KEY_PREFIX}{current.intent_id}")
            if raw_context is None:
                # No-id AMBIGUOUS, or nothing to resolve yet.
                self._log.debug(
                    f"resolver: no durable resolver context for intent "
                    f"{current.intent_id}; nothing to resolve this pass"
                )
                continue
            try:
                context = AmbiguousResolverContext.from_bytes(raw_context)
            except ExecutionReportMappingError as exc:
                self._log.error(
                    f"resolver context for intent {current.intent_id} is "
                    f"malformed ({exc}); this intent stays AMBIGUOUS"
                )
                continue
            if context.intent_id != current.intent_id:
                self._log.error(
                    f"resolver context key {current.intent_id} carries a "
                    f"foreign intent_id {context.intent_id}; refusing to act on it"
                )
                continue
            # Item 3 (2026-09-11 incident addendum), inlined for the same
            # E0-NOSEND-RESOLVER reason as the backoff above: a one-shot
            # health-surface entry (`stale_ambiguous_intent_alerts`) the
            # first time this OPEN intent's age crosses
            # `_STALE_INTENT_ALERT_AFTER_NS`. Mutated by whole-value
            # reassignment only (`|`, dict-unpacking) -- never `.add`, which
            # would itself be a new, unpermitted callee here.
            stale_age_ns = self._clock.timestamp_ns() - context.created_ns
            if (
                stale_age_ns >= _STALE_INTENT_ALERT_AFTER_NS
                and context.intent_id not in self._resolver_stale_alerted_intent_ids
            ):
                self._resolver_stale_alerted_intent_ids = (
                    self._resolver_stale_alerted_intent_ids | {context.intent_id}
                )
                # Deliberately NOT `.get(...)`: a dict-method call here is a
                # new, unpermitted callee under E0-NOSEND-RESOLVER (see the
                # backoff comment above).
                last_failure_kind = self._resolver_last_failure_kind[context.intent_id] if context.intent_id in self._resolver_last_failure_kind else "none"  # noqa: E501, SIM401
                self._resolver_stale_alert_details = {
                    **self._resolver_stale_alert_details,
                    context.intent_id: {
                        "severity": "CRITICAL",
                        "event": "open_intent_stale",
                        "site": "global",
                        "intent_id": context.intent_id,
                        "venue_order_id": context.venue_order_id,
                        "age_minutes": f"{stale_age_ns // 60_000_000_000}",
                        "last_failure_kind": last_failure_kind,
                    },
                }
            instrument = self._cache.instrument(InstrumentId.from_str(context.instrument_id))
            if instrument is None:
                self._log.warning(
                    f"resolver: instrument {context.instrument_id} not in the "
                    "cache; retrying next pass"
                )
                continue
            try:
                order_payload = await self._private_read(
                    submit_chain.order_by_id_path(context.venue_order_id)
                )
            except Exception as exc:  # noqa: BLE001 - GET failure stays AMBIGUOUS
                self._resolver_consecutive_failures += 1
                self._resolver_last_failure_kind[context.intent_id] = "get_exception"
                self._log.warning(
                    f"resolver GET failed for venue order {context.venue_order_id} "
                    f"({type(exc).__name__}: {exc}); stays AMBIGUOUS "
                    f"(backoff: {self._resolver_consecutive_failures} consecutive "
                    "failure(s))"
                )
                continue
            order_body: Mapping[str, Any]
            nested = order_payload.get("order") if isinstance(order_payload, Mapping) else None
            if isinstance(nested, Mapping):
                order_body = nested
            elif isinstance(order_payload, Mapping):
                order_body = order_payload
            else:
                self._log.warning(
                    f"resolver GET for venue order {context.venue_order_id} "
                    "returned an unmappable body shape; stays AMBIGUOUS"
                )
                continue
            try:
                report = parse_order_status_report(
                    order_body,
                    instrument=instrument,
                    account_id=self._issued_account_id,
                    report_id=UUID4(),
                    ts_init=self._clock.timestamp_ns(),
                )
            except Exception as exc:  # noqa: BLE001 - malformed stays AMBIGUOUS
                self._resolver_consecutive_failures += 1
                self._resolver_last_failure_kind[context.intent_id] = "mapping_error"
                self._log.warning(
                    f"resolver GET body for venue order {context.venue_order_id} "
                    f"did not map ({type(exc).__name__}: {exc}); stays AMBIGUOUS "
                    f"(backoff: {self._resolver_consecutive_failures} consecutive "
                    "failure(s))"
                )
                continue
            # A body that MAPPED is a successful GET -- reset the backoff
            # even when the status below is PENDING/non-terminal: the venue
            # is reachable and the shape still parses, which is exactly what
            # the backoff exists to detect the absence of.
            self._resolver_consecutive_failures = 0

            if report.order_status is OrderStatus.PARTIALLY_FILLED:
                # A LIVE state: the order can still receive more fills or
                # reach a terminal status later. Never resolves the intent --
                # logged at INFO (not a problem, just progress) and polled
                # again; a LATER pass that observes a genuinely terminal
                # status is the one that acts.
                self._log.info(
                    f"resolver: venue order {context.venue_order_id} is "
                    f"PARTIALLY_FILLED (cum={report.filled_qty}); a live "
                    "state, never resolves -- stays AMBIGUOUS, keep polling"
                )
                continue

            filled_qty_is_zero = report.filled_qty.as_decimal() == submit_chain.ZERO
            is_terminal = report.order_status in _RESOLVER_TERMINAL_STATUSES
            is_terminal_zero = is_terminal and filled_qty_is_zero
            # A terminal status (CANCELED/REJECTED/EXPIRED) with filled_qty >
            # 0 is the normal IOC partial-fill shape (minimumTradeQty 0.01):
            # a TERMINAL-FILL, resolved by `_resolve_accept_fill` exactly
            # like a full FILLED.
            is_terminal_fill = is_terminal and not filled_qty_is_zero
            is_full_fill = (
                report.order_status in _RESOLVER_FILL_STATUSES and not filled_qty_is_zero
            )
            is_fill = is_terminal_fill or is_full_fill
            if not is_terminal_zero and not is_fill:
                self._log.warning(
                    f"resolver: venue order {context.venue_order_id} is "
                    f"neither terminal nor a fill (status={report.order_status}, "
                    f"filled_qty={report.filled_qty}); stays AMBIGUOUS, keep polling"
                )
                continue

            try:
                positions_payload = await self._private_read(PORTFOLIO_POSITIONS_PATH)
                positions = self._declared_positions(positions_payload)
            except Exception as exc:  # noqa: BLE001 - transient; never `_refuse`
                self._log.warning(
                    f"resolver positions read failed ({type(exc).__name__}: {exc}); "
                    "stays AMBIGUOUS"
                )
                continue

            slug = instrument_id_to_slug(instrument.id)
            long_state = _resolver_long_position_state(positions, slug)
            if long_state is None:
                self._log.warning(
                    f"resolver could not determine {slug}'s position from an "
                    "eof-complete read; stays AMBIGUOUS"
                )
                continue

            now_ns = self._clock.timestamp_ns()
            # SAFETY H2: set ONLY here, by a terminal GET made in THIS run.
            # A durable record can schedule a GET; it can never by itself
            # authorize a retirement.
            self._resolved_by_get_ts_ns[current.intent_id] = now_ns

            if is_terminal_zero and long_state is False:
                # Item 1 (slice 4 review): `restore_live_trading_budget` can
                # raise `LiveTradingPermissionError` and `_retire` can raise
                # `SubmitIntentMismatch` (ARCH M2) -- unlike the GET/positions
                # reads above, nothing here awaited, so an unwrapped raise
                # would kill this coroutine for the process lifetime. Caught,
                # counted, and logged; the NEXT poll still runs.
                try:
                    self._resolve_terminal_zero(context, now_ns, positions)
                except Exception as exc:  # noqa: BLE001 - see the comment above
                    self._note_resolver_error(context.intent_id, exc)
                    continue
            elif is_fill and long_state is True:
                try:
                    self._resolve_accept_fill(context, report, instrument, now_ns)
                except Exception as exc:  # noqa: BLE001 - see the comment above
                    self._note_resolver_error(context.intent_id, exc)
                    continue
            else:
                self._log.warning(
                    "resolver: GET evidence and the positions read disagree "
                    f"for venue order {context.venue_order_id} "
                    f"(status={report.order_status}, long_present={long_state}); "
                    "stays AMBIGUOUS pending a consistent read"
                )

    def _resolve_terminal_zero(
        self,
        context: AmbiguousResolverContext,
        now_ns: int,
        positions: Mapping[str, Any] | None = None,
    ) -> None:
        """Resolution D: GET-confirmed terminal, zero-filled, no LONG.

        Mirrors the CREATE-time ``KIND_ZERO_FILL`` branch exactly (same
        ledger op, same native event), on evidence from a GET instead of
        the create response. ARCH M2: ``retire`` is NOT idempotent
        (``SubmitIntentMismatch`` on a non-OPEN or foreign singleton), so
        ``current()`` is read and checked FIRST -- a re-entry against an
        already-retired singleton cleans up and returns without calling
        ``retire`` a second time.

        Review fix 2 (Slice 2): SAFETY H2 is made load-bearing HERE, not
        only structural at the call site -- this method itself refuses to
        retire unless ``context.intent_id`` was stamped into
        ``self._resolved_by_get_ts_ns`` by a terminal GET made in THIS run.
        A durable resolver context can schedule a GET; it can never by
        itself authorize a retirement.

        D1/D2 (plan rev 6.1): ONLY after ``retire`` succeeds, give back the
        one permit slot this no-fill IOC never actually spent. ``positions``
        is the SAME eof-complete page ``_resolve_ambiguous_intents`` already
        read this pass -- ``None`` only when a test calls this method
        directly (:func:`test_resolve_terminal_zero_itself_refuses_to_retire_
        without_a_this_run_get`), in which case the startup-evidence rewrite
        is skipped rather than fabricated from nothing.
        """
        if context.intent_id not in self._resolved_by_get_ts_ns:
            self._log.error(
                f"resolver: refusing to retire intent {context.intent_id} -- "
                "no terminal GET was recorded for it in this run; SAFETY H2 "
                "fail-closed"
            )
            return
        current = self._latch.current_open()
        if current is None or current.intent_id != context.intent_id:
            self._ambiguous_bookings.pop(context.intent_id, None)
            return
        # A1-c: backfill for a context written before this change, which
        # only the resolver will ever see again -- idempotent (same key,
        # same bytes). OUTSIDE the guard above: `context.venue_order_id`
        # is a plain str here, always present. No `return` (A-B2): the
        # retire, true-up and native cancel below must still run.
        try:
            self.record_venue_order_id(
                submit_chain.venue_order_id(context.venue_order_id),
                ClientOrderId(context.client_order_id),
            )
        except Exception as exc:  # noqa: BLE001
            self._log.error(
                f"{_VENUE_ID_MAP_WRITE_FAILED}: {exc.__class__.__name__}: {exc}; "
                f"venue_order_id={context.venue_order_id} "
                f"client_order_id={context.client_order_id}"
            )
            self._refuse(_VENUE_ID_MAP_WRITE_FAILED)
        self._retire(context.intent_id, "STATUS_REPORT_ZERO_FILL_TERMINAL", now_ns)
        booking = self._ambiguous_bookings.pop(context.intent_id, None)
        if booking is not None:
            # Same-process only (Resolution E): on restart the ledger died
            # with the process and this dict is empty -- the reminted
            # budget already starts whole, so there is nothing to true up.
            self._ledger.true_up_booking(booking, filled_cost_usd=submit_chain.ZERO, now_ns=now_ns)
        if self._permit is not None and restore_live_trading_budget(
            permit=self._permit,
            venue_order_id=context.venue_order_id,
            order_notional_usd=context.notional_usd,
        ):
            self._mark_budget_restored(context.venue_order_id)
        if positions is not None:
            self._write_startup_position_evidence(
                now_ns=now_ns,
                eof_complete=True,
                position_read_refused=False,
                raw_positions=positions,
            )
        self.generate_order_canceled(
            strategy_id=StrategyId(context.strategy_id),
            instrument_id=InstrumentId.from_str(context.instrument_id),
            client_order_id=ClientOrderId(context.client_order_id),
            venue_order_id=submit_chain.venue_order_id(context.venue_order_id),
            ts_event=now_ns,
        )

    def _resolve_accept_fill(
        self,
        context: AmbiguousResolverContext,
        report: Any,
        instrument: Any,
        now_ns: int,
    ) -> None:
        """Slice 3 (plan rev 6.1): GET-confirmed FILLED/PARTIALLY_FILLED with
        a LONG present on an eof-complete positions read.

        The venue's Order schema carries no execution legs, so the fill is
        SYNTHESIZED from ``cumQuantity``/``avgPx`` -- the same two fields the
        CREATE path's own I1a totals are built from. ``trade_id`` is a pure,
        deterministic, VISIBLY SYNTHETIC function of ``venue_order_id``
        (:func:`_synthetic_get_fill_trade_id`) so nothing downstream can ever
        mistake it for a venue-issued trade id. ``commission`` is
        ``Money(0, USD)`` and ``fee_reconciled`` is ``False`` -- the fee is
        genuinely unknown from an Order-only GET, recorded DURABLY as such on
        the fill record itself. This deliberately never calls ``_refuse``
        (unlike the CREATE path's own ``_FEE_UNRECONCILED``): I2's residual-
        bucket mechanism reads the durable ``fee_reconciled`` flag, and
        latching ``_trading_refusals`` here would halt trading over a fee
        gap this design already expects and durably records.

        Ordering mirrors the CREATE-time ``KIND_ACCEPT_FILL`` branch exactly
        for the same crash-safety reason: ``record_fill`` (durable) happens
        BEFORE ``retire`` (singleton state) happens BEFORE
        ``generate_order_filled`` (the native event) -- a crash at any point
        still leaves the durable evidence a restart can read.

        SAFETY H2 and ARCH M2 apply identically to :meth:`_resolve_terminal_
        zero`: refuses to act absent a this-run GET timestamp, and reads
        ``current()`` first so a re-entry against an already-retired
        singleton cleans up and returns without a second ``retire`` call.
        """
        if context.intent_id not in self._resolved_by_get_ts_ns:
            self._log.error(
                f"resolver: refusing to record a fill for intent "
                f"{context.intent_id} -- no terminal GET was recorded for "
                "it in this run; SAFETY H2 fail-closed"
            )
            return
        current = self._latch.current_open()
        if current is None or current.intent_id != context.intent_id:
            self._ambiguous_bookings.pop(context.intent_id, None)
            return
        avg_px = report.avg_px
        if avg_px is None or avg_px <= 0:
            self._log.error(
                f"resolver: GET confirms a FILL for venue order "
                f"{context.venue_order_id} with no usable avg_px "
                f"({avg_px!r}); a fill cannot be synthesized from this "
                "evidence -- stays AMBIGUOUS"
            )
            return
        cumulative_qty = report.filled_qty.as_decimal()
        cumulative_cost = cumulative_qty * avg_px
        record = DurableFillRecord(
            venue_order_id=context.venue_order_id,
            client_order_id=context.client_order_id,
            instrument_id=context.instrument_id,
            order_side=LONG_ONLY_SIDE,
            cumulative_qty=cumulative_qty,
            cumulative_cost=cumulative_cost,
            cumulative_fee=submit_chain.ZERO,
            fee_reconciled=False,
            ts_event=now_ns,
            venue_fee_raw=None,
            trade_id=_synthetic_get_fill_trade_id(context.venue_order_id).value,
            order_qty=report.quantity.as_decimal(),
        )
        try:
            self.record_fill(record)
        except Exception as exc:  # noqa: BLE001 - see the CREATE path's identical guard
            fill_record_bytes = record.to_bytes()
            detail = fill_record_bytes.decode()
            self._log.error(
                f"{_FILL_WRITE_FAILED}: {exc.__class__.__name__}: {exc}; record={detail}"
            )
            self._refuse(_FILL_WRITE_FAILED)
            return
        booking = self._ambiguous_bookings.pop(context.intent_id, None)
        if booking is not None:
            self._ledger.true_up_booking(booking, filled_cost_usd=cumulative_cost, now_ns=now_ns)
        # A1-b (B-2): anchored to the indentation of the statement this
        # block PRECEDES (`_retire`, 8-space function-body indent), NOT the
        # `true_up_booking` line above -- `_ambiguous_bookings` is
        # same-process only and EMPTY after a restart, so a block inside
        # `if booking is not None:` would silently skip the write on
        # exactly the post-restart reconciliation path this exists to
        # serve. No `return` (A-B2): `_retire` and `generate_order_filled`
        # below must still run.
        try:
            self.record_venue_order_id(
                submit_chain.venue_order_id(context.venue_order_id),
                ClientOrderId(context.client_order_id),
            )
        except Exception as exc:  # noqa: BLE001
            self._log.error(
                f"{_VENUE_ID_MAP_WRITE_FAILED}: {exc.__class__.__name__}: {exc}; "
                f"venue_order_id={context.venue_order_id} "
                f"client_order_id={context.client_order_id}"
            )
            self._refuse(_VENUE_ID_MAP_WRITE_FAILED)
        self._retire(context.intent_id, "STATUS_REPORT_ACCEPT_FILL_TERMINAL", now_ns)
        # D2 (plan rev 6.1): a genuine fill surfacing for a venue order this
        # resolver already restored a permit slot for (a superseded
        # terminal-zero determination) must give that slot back. Never fires
        # on the ordinary path -- `_resolve_terminal_zero` retires the
        # singleton, so a later pass for the same intent never reaches here.
        if self._permit is not None and self._budget_was_restored(context.venue_order_id):
            unrestore_live_trading_budget(
                permit=self._permit,
                venue_order_id=context.venue_order_id,
                order_notional_usd=context.notional_usd,
            )
        self.generate_order_filled(
            strategy_id=StrategyId(context.strategy_id),
            instrument_id=InstrumentId.from_str(context.instrument_id),
            client_order_id=ClientOrderId(context.client_order_id),
            venue_order_id=submit_chain.venue_order_id(context.venue_order_id),
            venue_position_id=None,
            trade_id=_synthetic_get_fill_trade_id(context.venue_order_id),
            order_side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            last_qty=report.filled_qty,
            last_px=instrument.make_price(avg_px),
            quote_currency=USD,
            commission=Money(0, USD),
            liquidity_side=LiquiditySide.TAKER,
            ts_event=now_ns,
        )

    async def _disconnect(self) -> None:
        """Close the durable store. A failing close does not fail the shutdown.

        The reference is dropped FIRST so a half-closed handle can never be
        written to afterwards, and the close is wrapped because at that point
        the only handle is the local one: an exception escaping here would
        abort the disconnect over a resource that is already unreachable.

        The submit-intent latch is NOT closed here -- it is the composition
        root's, never opened by this client; only the reconciled flag resets.
        """
        self._intent_reconciled = False
        await self._cancel_resolver_task()
        store = self._store
        self._store = None
        if store is None:
            return
        try:
            store.close()
        except Exception as exc:  # noqa: BLE001 - a failing close must not abort the shutdown
            self._log.error(
                f"The durable execution store did not close cleanly "
                f"({type(exc).__name__}: {exc}); its handle is now unreachable"
            )

    async def _cancel_resolver_task(self) -> None:
        """Mirrors ``data.py``'s ``_cancel_update_instruments`` exactly: the
        reference is dropped first, then ``cancel()`` is followed by an
        ``await`` so the cancellation is actually delivered before this
        returns -- never fire-and-forget. Deterministic shutdown ordering
        depends on this: the store is closed only AFTER the resolver task
        has genuinely stopped touching it."""
        task = self._resolver_task
        self._resolver_task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _open_state_store(self) -> None:
        """Construct the store on THIS thread and prove it actually persists.

        :func:`~breezy.ingest.gate.assert_state_store_durable` is reused rather
        than re-implemented: it round-trips through an independently opened
        handle, so a store that only looks durable fails here at start-up
        instead of losing a fill record silently months later. A store that
        cannot be shown to persist fails the connect CLOSED -- unlike a venue
        position we cannot attribute, this is a local defect with no risk held
        against it.

        The proof runs on the LOCAL handle, BEFORE assignment. Assigning first
        leaves the client holding a store PROVEN non-durable with its sqlite
        handle never closed, and :meth:`_require_store` only checks for
        ``None`` -- so R-7's ``record_fill`` would write to it and believe the
        write. The failed handle is closed on the way out, and a close that
        itself fails is logged rather than allowed to mask the real cause.
        """
        store = self._state_store_opener()
        try:
            assert_state_store_durable(store, opener=self._state_store_opener)
        except BaseException:
            try:
                store.close()
            except Exception as close_exc:  # noqa: BLE001 - never mask the durability failure
                self._log.error(
                    "A store that failed the durability proof could not be "
                    f"closed either ({type(close_exc).__name__}: {close_exc})"
                )
            raise
        self._store = store
        self._store_thread = threading.get_ident()

    async def _wait_for_instruments(self) -> None:
        """Load instruments under a hard time bound.

        Unbounded, a venue that accepts the connection and never answers would
        hang the connect coroutine forever with no log line and no account
        state -- the same silent non-start as the mass-status trap. The bound
        is a refusal, not a crash: with no instruments nothing can be mapped,
        so every position becomes unattributable and the client denies.
        """
        try:
            await asyncio.wait_for(
                self._instrument_provider.initialize(),
                timeout=self._instrument_wait_timeout_s,
            )
        except TimeoutError:
            self._refuse(
                "the instrument load did not finish within "
                f"{self._instrument_wait_timeout_s}s; no venue position can be "
                "mapped to an instrument"
            )
            return
        except Exception as exc:  # noqa: BLE001 - a broken load must refuse, never crash the connect
            self._refuse(f"the instrument load failed: {type(exc).__name__}: {exc}")
            return

        if self._instrument_provider.count == 0:
            self._refuse(
                "the instrument provider loaded no instruments; no venue "
                "position can be mapped to an instrument"
            )

    async def _confirm_account_registered(self) -> None:
        """Wait, bounded, for the published account to appear in the cache.

        Until it does, ``risk/engine.pyx:684-689`` fails OPEN on every cap.
        Not raising: a node that cannot boot while holding real risk is worse
        than the risk, and an unregistered account is latched as a refusal --
        which, with the submit precondition below, denies every order.
        """
        try:
            await self._await_account_registered(
                timeout_secs=self._account_registration_timeout_s,
            )
        except Exception as exc:  # noqa: BLE001 - an unregistered account refuses, it does not crash
            # Phrased as "the wait failed", not "it did not register": this
            # handler sees ANY exception, and asserting a specific cause for an
            # unknown one is how a misleading refusal reason gets written.
            self._refuse(
                f"the wait for account {self._issued_account_id} to appear in "
                f"the cache failed ({type(exc).__name__}: {exc}); until it is "
                "registered every Nautilus risk cap remains inert"
            )

    # -- account ------------------------------------------------------------

    async def _query_account(self, command: QueryAccount) -> None:
        """Absent from ``LiveExecutionClient`` and CALLED at ``:332``.

        Without it the ``QueryAccount`` command path raises. It re-reads the
        venue rather than replaying a cached figure: the point of the command
        is to ask.
        """
        await self._publish_account_state()

    async def _publish_account_state(self) -> None:
        """Read balances and publish the native ``AccountState``.

        ``generate_account_state`` (``execution/client.pyx:329``) constructs
        and publishes the event itself; Breezy supplies the balances and
        nothing more.
        """
        payload = await self._private_read(ACCOUNT_BALANCES_PATH)
        balances = parse_account_balances(payload)
        self.generate_account_state(
            balances=list(balances),
            margins=[],
            reported=True,
            ts_event=self._clock.timestamp_ns(),
        )

    # -- reconciliation -----------------------------------------------------

    async def generate_mass_status(
        self,
        lookback_mins: int | None = None,
    ) -> ExecutionMassStatus:
        """Assemble the mass status, and NEVER return ``None``.

        The native implementation (``live/execution_client.py:498-514``)
        catches every exception at ``:512`` and returns ``None`` at ``:514``.
        A ``None`` is a reconciliation failure, and a reconciliation failure
        stops the trader from starting -- with one log line and no order. So
        every ``Exception`` is caught and reported INSIDE, and the result is an
        honest, possibly-empty mass status plus a latched trading refusal.

        ``Exception``, precisely: ``CancelledError`` is a ``BaseException`` and
        is deliberately NOT caught. A cancelled reconciliation is the loop
        shutting this coroutine down, and swallowing that would report a
        confident empty status for a read that never happened.

        The ASSEMBLY is inside the ``try`` as well, not only the three report
        reads. It constructs a real ``ExecutionMassStatus`` and calls three
        native ``add_*_reports``; run outside, anything it raised would escape
        to the native ``return None`` path -- the exact silent non-start this
        method exists to prevent, arriving through the one statement not
        covered. Its fallback re-assembles with NO reports, which is the
        smallest thing the native constructor can be asked to build.

        An empty mass status is safe here and a ``None`` is not: at start-up
        the cache holds no positions (``database=None``), so an empty status
        closes nothing, whereas a ``None`` means the node never runs.

        ``lookback_mins`` is accepted for the native signature and IGNORED.
        Every read this client makes is a full current-state snapshot -- the
        balances and positions surfaces take no time window -- so there is no
        window to narrow, and pretending to honour one would be worse than
        saying so.
        """
        self.reconciliation_active = True
        try:
            try:
                order_reports = await self.generate_order_status_reports(None)
                fill_reports = await self.generate_fill_reports(None)
                position_reports = await self.generate_position_status_reports(None)
            except Exception as exc:  # noqa: BLE001  # pragma: no cover - see below
                self._refuse(
                    "reconciliation failed while generating reports "
                    f"({type(exc).__name__}: {exc}); reporting an EMPTY mass status "
                    "rather than the native None, which would stop the trader"
                )
                order_reports, fill_reports, position_reports = [], [], []

            try:
                return self._assemble(order_reports, fill_reports, position_reports)
            except Exception as exc:  # noqa: BLE001 - the assembly must not reach the native handler
                self._refuse(
                    "the mass status assembly rejected a report "
                    f"({type(exc).__name__}: {exc}); reporting an EMPTY mass "
                    "status rather than the native None, which would stop the "
                    "trader. Reconciliation is now blind to real venue state"
                )
                return self._assemble([], [], [])
        finally:
            self.reconciliation_active = False

    def _assemble(
        self,
        order_reports: list[OrderStatusReport],
        fill_reports: list[FillReport],
        position_reports: list[PositionStatusReport],
    ) -> ExecutionMassStatus:
        return build_execution_mass_status(
            client_id=self.id,
            account_id=self._issued_account_id,
            report_id=UUID4(),
            ts_init=self._clock.timestamp_ns(),
            order_reports=order_reports,
            fill_reports=fill_reports,
            position_reports=position_reports,
        )

    async def generate_order_status_report(
        self,
        command: GenerateOrderStatusReport,
    ) -> OrderStatusReport | None:
        """By-id order read on the private read seam (R-7-STATUS).

        Returning ``None`` remains the native contract for "not found"
        (``live/execution_client.py:343``). The path is templated so V2 does
        not see the private order resource as one literal.
        """
        venue_order_id = getattr(command, "venue_order_id", None)
        if venue_order_id is None:
            self._log.warning(
                "No venue_order_id on the order status query; returning None",
            )
            return None
        path = submit_chain.order_by_id_path(str(venue_order_id))
        try:
            payload = await self._private_read(path)
        except Exception as exc:  # noqa: BLE001 - None is the native not-found contract
            self._log.warning(
                f"order status read failed ({type(exc).__name__}: {exc}); returning None"
            )
            return None
        instrument = self._cache.instrument(command.instrument_id)
        if instrument is None:
            return None
        body: Mapping[str, Any]
        nested = payload.get("order") if isinstance(payload, Mapping) else None
        if isinstance(nested, Mapping):
            body = nested
        elif isinstance(payload, Mapping):
            body = payload
        else:
            return None
        try:
            return parse_order_status_report(
                body,
                instrument=instrument,
                account_id=self._issued_account_id,
                report_id=UUID4(),
                ts_init=self._clock.timestamp_ns(),
            )
        except Exception as exc:  # noqa: BLE001 - unmappable is not-found, not a crash
            self._log.warning(
                f"order status payload did not map ({type(exc).__name__}: {exc})"
            )
            return None

    async def generate_order_status_reports(
        self,
        command: GenerateOrderStatusReports | None = None,
    ) -> list[OrderStatusReport]:
        """Empty, and empty for a stated reason.

        The venue's open-order read surface is not declared by R-3's endpoint
        table, and barrier V2 refuses its path literal inside any
        venue-touching module with no allowlist. Breezy DOES submit orders
        (R-7's ``_submit_order``, one per station-day) -- what remains
        unimplemented is reading THEM BACK by status: this method returns an
        empty list unconditionally, not because nothing was ever submitted.
        """
        return []

    async def generate_fill_reports(
        self,
        command: GenerateFillReports | None = None,
    ) -> list[FillReport]:
        """Empty, and empty for a stated reason.

        Fills would come from the portfolio activities surface, which is the
        evidence source the submit-intent latch needs and the cash source
        settlement needs. It is read-only and lands with the increment that
        has something to reconcile against; here there are no fills, because
        there are no orders.
        """
        return []

    async def generate_position_status_reports(
        self,
        command: GeneratePositionStatusReports | None = None,
    ) -> list[PositionStatusReport]:
        """Map the venue's open positions, refusing what cannot be attributed.

        Never raises. The native ``generate_mass_status`` would turn any
        exception into a ``None`` mass status and a silent non-start, and the
        override above must not have to rely on that not happening.
        """
        instrument_filter = getattr(command, "instrument_id", None)
        try:
            payload = await self._private_read(PORTFOLIO_POSITIONS_PATH)
            positions = self._declared_positions(payload)
        except Exception as exc:  # noqa: BLE001 - see the docstring: NOTHING may reach the native handler
            # R-6.5a: a status-carrying refusal is classified TRANSIENT/
            # DURABLE on its actual HTTP status and gRPC code; anything else
            # (a transport fault, a mapping-shape error) keeps the DURABLE
            # default `classify_venue_refusal` itself defines -- this is the
            # ONE production caller that feeds it a real status and body.
            classification = (
                classify_venue_refusal(status=exc.status, body=exc.body)
                if isinstance(exc, PrivateReadRefused)
                else RefusalClass.DURABLE
            )
            self._refuse(
                "the venue position read failed "
                f"({type(exc).__name__}: {exc}); no position can be attributed",
                classification=classification,
            )
            return []

        reports: list[PositionStatusReport] = []
        for slug in sorted(positions):
            report = self._map_position(slug, positions[slug])
            if report is None:
                continue
            if instrument_filter is not None and report.instrument_id != instrument_filter:
                continue
            reports.append(report)
        return reports

    @staticmethod
    def _declared_positions(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Pull ``positions`` out of the response, refusing a foreign shape."""
        positions = payload.get("positions")
        if positions is None:
            raise ExecutionReportMappingError(
                "the venue position response declares no 'positions' key; an "
                "absent map is not an empty map"
            )
        if not isinstance(positions, dict):
            raise ExecutionReportMappingError(
                f"the venue position response carries a {type(positions).__name__} "
                "under 'positions' where an object keyed by market slug was declared"
            )
        if payload.get("eof") is not True:
            # R-4P-1 (interim; R-4P-2 cursor-following pagination is
            # deliberately deferred). `GetUserPositionsResponse` is
            # cursor-paginated -- it carries `nextCursor` and `eof` alongside
            # `positions` -- and this client does not follow a cursor. Page 1
            # is not the whole book, so treating it as one silently
            # under-reports exposure to every risk cap that sizes off
            # `portfolio.net_position`. `eof` is `total=False` on the venue's
            # own TypedDict, so an ABSENT `eof` is UNKNOWN, never `True` --
            # only an explicit `eof: true` is a terminal page.
            raise ExecutionReportMappingError(
                "the venue position response is not marked eof=true; page 1 "
                "is not necessarily the whole book and this client does not "
                "follow a cursor (R-4P-1: refuse rather than silently "
                "truncate)"
            )
        return positions

    def _map_position(self, slug: str, payload: Any) -> PositionStatusReport | None:
        """One venue position -> one report, or ``None`` plus a refusal.

        ``slug`` is the DICT KEY of ``GetUserPositionsResponse.positions`` and
        is the only authoritative market identifier a ``UserPosition`` carries,
        which is why R-3 makes it a required keyword.
        """
        instrument = self._find_instrument(slug)
        if instrument is None:
            self._refuse(
                f"the venue reports a position in market {slug!r}, for which no "
                "instrument is loaded; it cannot be mapped, priced or netted"
            )
            return None

        try:
            mapped = parse_position_status_report(
                payload,
                market_slug=slug,
                instrument=instrument,
                account_id=self._issued_account_id,
                report_id=UUID4(),
                ts_init=self._clock.timestamp_ns(),
            )
        except (ExecutionReportMappingError, VenuePayloadError) as exc:
            self._refuse(f"the position in market {slug!r} could not be mapped: {exc}")
            return None

        # R-6.5a: this is "an instrument's reconciliation succeeded" -- the
        # payload for `slug` was read AND mapped without error. Chosen as the
        # narrowest point that covers every outcome below it (expired, FLAT,
        # or a live LONG) rather than duplicating the call in each branch.
        # Nothing in THIS client's own refusal producers is instrument-scoped
        # yet (only the whole-account read failure in
        # `generate_position_status_reports` classifies today, and that one
        # is account-wide, not per-instrument), so this re-derivation has no
        # production trigger to fire against until a later increment adds
        # one -- the same shape R-6d's classifier itself landed in.
        self._trading_refusals = list(
            refusals_after_successful_reconcile(self._trading_refusals, instrument=slug)
        )

        report = mapped.report
        if mapped.expired:
            # Settled, not tradeable. Reported, it would count as capacity
            # every exposure cap downstream could still trade against.
            if report.instrument_id not in self._settled_positions:
                self._settled_positions.append(report.instrument_id)
            self._log.warning(
                f"Venue reports an EXPIRED position in {report.instrument_id} "
                f"({report.quantity}); excluded from reconciliation as settled, "
                "not live risk",
            )
            return None

        if report.position_side == PositionSide.FLAT:
            # Deliberately not forwarded: see the module docstring's landmine
            # note. A FLAT report on a held binary books the close at the OPEN
            # price and realizes exactly zero.
            return None

        if report.position_side != PositionSide.LONG:
            self._refuse(
                f"the venue reports a non-long position in {report.instrument_id}; "
                "Breezy is long-only and cannot attribute it"
            )
            return None

        avg_px_open = self._entry_price(report.instrument_id, report.quantity, payload)

        return PositionStatusReport(
            account_id=report.account_id,
            instrument_id=report.instrument_id,
            position_side=report.position_side,
            quantity=report.quantity,
            report_id=report.id,
            ts_last=report.ts_last,
            ts_init=report.ts_init,
            venue_position_id=report.venue_position_id,
            avg_px_open=avg_px_open,
        )

    def _find_instrument(self, slug: str) -> Instrument | None:
        """Resolve a market slug to a loaded instrument, provider first."""
        try:
            instrument_id = slug_to_instrument_id(slug)
        except VenuePayloadError as exc:
            self._refuse(f"the venue reports a position under an unusable slug: {exc}")
            return None
        found = self._instrument_provider.find(instrument_id)
        if found is not None:
            return found
        return self._cache.instrument(instrument_id)

    def _entry_price(
        self,
        instrument_id: InstrumentId,
        quantity: Quantity,
        payload: Any,
    ) -> Decimal | None:
        """The position's ``avg_px_open``: our records, then the venue, then none.

        Never returns zero and never causes the position to be dropped. See the
        module docstring for why the third step's measured cost -- the position
        books at 0.00 -- is accepted rather than avoided by exclusion.
        """
        recorded = self._entry_price_from_records(instrument_id, quantity)
        if recorded is not None:
            return recorded

        derived = self._entry_price_from_venue(instrument_id, payload)
        if derived is not None:
            self._refuse(
                f"the position in {instrument_id} is priced from the VENUE's own "
                f"cost basis ({derived}), not from a Breezy fill record; it is "
                "reported as real exposure but is not attributable to an order "
                "this bot placed"
            )
            return derived

        self._refuse(
            f"the venue reports {quantity} in {instrument_id} that neither a "
            "durable fill record nor the venue's own cost basis can price; it "
            "is reported UNPRICED, which books it at the last cached quote or "
            "at 0.00, so no order may ever be sized or exited against it"
        )
        return None

    def _entry_price_from_records(
        self,
        instrument_id: InstrumentId,
        quantity: Quantity,
    ) -> Decimal | None:
        """The entry price Breezy's own durable fill records support.

        Records are CUMULATIVE PER VENUE ORDER, so the average across orders is
        ``sum(cost) / sum(qty)`` -- with SELL records netted, not refused: after
        an R-8/R-9 partial exit the remaining position is still Breezy's own,
        and treating its exit record as poison would make our own position
        unattributable exactly when we most need to price it.
        """
        records = self.fill_records_for(instrument_id)
        if not records:
            self._refuse(
                f"the venue reports {quantity} in {instrument_id} with no durable "
                "fill record; the position is foreign or its record was lost"
            )
            return None

        unknown_side = sorted(
            {record.order_side for record in records if record.order_side not in _RECORD_SIGNS}
        )
        if unknown_side:
            self._refuse(
                f"a durable fill record for {instrument_id} carries side(s) "
                f"{unknown_side}, which are neither an open nor an exit; no "
                "entry price can be netted from them"
            )
            return None

        net_qty = sum(
            (_RECORD_SIGNS[record.order_side] * record.cumulative_qty for record in records),
            Decimal(0),
        )
        net_cost = sum(
            (_RECORD_SIGNS[record.order_side] * record.cumulative_cost for record in records),
            Decimal(0),
        )
        if net_qty != quantity.as_decimal():
            self._refuse(
                f"the venue reports {quantity} in {instrument_id} but the durable "
                f"fill records net to {net_qty}; the size does not match, so the "
                "difference has no entry price of ours"
            )
            return None
        if net_qty <= 0 or net_cost <= 0:
            self._refuse(
                f"the durable fill records for {instrument_id} net to "
                f"{net_qty} at a cost of {net_cost}; no entry price can be "
                "derived from them"
            )
            return None
        return net_cost / net_qty

    def _entry_price_from_venue(
        self,
        instrument_id: InstrumentId,
        payload: Any,
    ) -> Decimal | None:
        """``cost / qtyBought``, and only while ``qtySold == 0``.

        The derivation and the condition it is sound under both live in
        :func:`~breezy.adapters.polymarket_us.exec.reports.derive_position_cost_basis`;
        this wrapper exists only to turn a malformed payload into a refusal
        rather than an exception on the reconciliation path.
        """
        try:
            return derive_position_cost_basis(payload)
        except (ExecutionReportMappingError, VenuePayloadError) as exc:
            self._refuse(f"the venue cost basis for {instrument_id} could not be read: {exc}")
            return None

    # -- durable state ------------------------------------------------------

    def record_venue_order_id(
        self,
        venue_order_id: VenueOrderId,
        client_order_id: ClientOrderId,
    ) -> None:
        """Persist the venue ``id`` -> ``ClientOrderId`` map.

        The venue issues no client order id, so this map is the only thing
        that stops a Breezy order reconciling as ``StrategyId("EXTERNAL")``
        after a restart.
        """
        self._store_set(
            f"{VENUE_ORDER_ID_KEY_PREFIX}{venue_order_id.value}",
            client_order_id.value.encode("utf-8"),
        )

    def client_order_id_for(self, venue_order_id: VenueOrderId) -> ClientOrderId | None:
        raw = self._store_get(f"{VENUE_ORDER_ID_KEY_PREFIX}{venue_order_id.value}")
        if raw is None:
            return None
        return ClientOrderId(raw.decode("utf-8"))

    def record_fill(self, record: DurableFillRecord) -> None:
        """Persist one venue order's cumulative totals and index it.

        Written before the ``OrderFilled`` is published (R-7), so a crash
        between the venue's answer and the event still leaves the evidence on
        disk. A rewrite at the same ``venue_order_id`` is a cumulative UPDATE,
        not a second fill -- see :class:`DurableFillRecord`.

        The index is read FIRST and an unreadable one RAISES. Overwriting it
        would replace ids we could not see with the single one in hand,
        destroying every surviving record's reachability -- the store has no
        prefix scan, so an id absent from the index is an id that no longer
        exists as far as pricing is concerned.
        """
        index_key = f"{FILL_INDEX_KEY_PREFIX}{record.instrument_id}"
        indexed = self._read_fill_index(index_key)
        if indexed is None:
            raise PolymarketUSError(
                f"the durable fill index at {index_key!r} could not be read, so "
                "it cannot be safely rewritten: overwriting it would orphan "
                "every fill record it still names"
            )
        self._store_set(f"{FILL_KEY_PREFIX}{record.venue_order_id}", record.to_bytes())
        if record.venue_order_id not in indexed:
            indexed.append(record.venue_order_id)
            self._store_set(index_key, json.dumps(indexed).encode("utf-8"))

    def fill_records_for(
        self,
        instrument_id: InstrumentId,
    ) -> tuple[DurableFillRecord, ...]:
        """Every durable fill record for ``instrument_id``.

        An index entry whose record is missing or malformed yields an EMPTY
        result, never a partial one: a partial set would understate the
        position's cost and produce a confident, wrong entry price.
        """
        indexed = self._read_fill_index(f"{FILL_INDEX_KEY_PREFIX}{instrument_id}")
        if indexed is None:
            return ()  # unreadable; `_read_fill_index` has already refused
        records: list[DurableFillRecord] = []
        for venue_order_id in indexed:
            raw = self._store_get(f"{FILL_KEY_PREFIX}{venue_order_id}")
            if raw is None:
                self._refuse(
                    f"the fill index for {instrument_id} names venue order "
                    f"{venue_order_id!r} but no record exists for it"
                )
                return ()
            try:
                records.append(DurableFillRecord.from_bytes(raw))
            except ExecutionReportMappingError as exc:
                self._refuse(f"a durable fill record for {instrument_id} is unreadable: {exc}")
                return ()
        return tuple(records)

    def _read_fill_index(self, key: str) -> list[str] | None:
        """The indexed venue order ids, ``[]`` for absent, ``None`` for UNREADABLE.

        The three-way return is the whole point. Collapsing "unreadable" into
        "empty" makes a corrupt index indistinguishable from a fresh one, and
        the writer then overwrites it with a single entry -- silently deleting
        every id it still held.
        """
        raw = self._store_get(key)
        if raw is None:
            return []
        try:
            decoded = json.loads(raw)
        except ValueError:
            self._refuse(f"the durable fill index at {key!r} is not valid JSON")
            return None
        if not isinstance(decoded, list) or not all(isinstance(v, str) for v in decoded):
            self._refuse(f"the durable fill index at {key!r} is not a list of ids")
            return None
        return list(decoded)

    def _store_set(self, key: str, value: bytes) -> None:
        self._require_store().set(key, value)

    def _store_get(self, key: str) -> bytes | None:
        return self._require_store().get(key)

    def _require_store(self) -> ClosableStateStore:
        store = self._store
        if store is None:
            raise PolymarketUSError(
                "the durable execution store is not open; it is opened inside "
                "_connect, on the thread that writes it"
            )
        if threading.get_ident() != self._store_thread:
            raise PolymarketUSError(
                "the durable execution store is being used from a thread other "
                "than the one it was constructed on; it is thread-confined by "
                "design (sqlite_store.py:128-135)"
            )
        return store

    # -----------------------------------------------------------------------
    # C1/C2/D2 (plan rev 6.1): startup/re-arm position evidence, and the
    # durable budget-restore marker.
    # -----------------------------------------------------------------------

    def read_startup_position_evidence(self) -> StartupPositionEvidence | None:
        """The most recently written :class:`StartupPositionEvidence`, or
        ``None`` if `_connect` has never completed once in this store."""
        raw = self._store_get(STARTUP_EVIDENCE_KEY)
        if raw is None:
            return None
        return StartupPositionEvidence.from_bytes(raw)

    def _fill_walk_complete(self) -> bool:
        """C2: every known instrument's durable fill index is READABLE.

        ``_read_fill_index`` returns ``[]`` for an absent index (success --
        no fills yet for that instrument) and ``None`` for a corrupt one
        (failure). There is no store-wide prefix scan
        (module docstring, ``sqlite_store.py``), so "every durable fill
        record" is walked the only way reachable: by instrument, over the
        native cache's own inventory.

        Item 3 (slice 4 review): an EMPTY enumeration is FAIL CLOSED, not
        vacuously complete. ``_wait_for_instruments`` already ran earlier in
        ``_connect``, so a genuinely empty instrument set is not a shape a
        real CRH trading day ever produces -- it is exactly as suspicious as
        a corrupt index, and treated the same way.
        """
        try:
            instruments = self._cache.instruments(self.venue)
        except Exception as exc:  # noqa: BLE001 - enumeration failure marks the walk incomplete
            self._log.warning(
                f"startup evidence: fill-walk instrument enumeration failed "
                f"({type(exc).__name__}: {exc})"
            )
            return False
        if not instruments:
            self._log.warning(
                "startup evidence: fill-walk found zero instruments in the "
                "cache; treating the walk as incomplete rather than vacuously "
                "complete"
            )
            return False
        for instrument in instruments:
            if self._read_fill_index(f"{FILL_INDEX_KEY_PREFIX}{instrument.id}") is None:
                return False
        return True

    def _write_startup_position_evidence(
        self,
        *,
        now_ns: int,
        eof_complete: bool,
        position_read_refused: bool,
        raw_positions: Mapping[str, Any],
    ) -> None:
        """Project an eof-complete (or refused) positions page into
        :class:`StartupPositionEvidence` and overwrite the single durable row.

        Item 2 (slice 4 review, CRITICAL): EVERY slug the page names is
        recorded -- never dropped -- with ``net_position=None`` when its
        entry is missing or not a mapping. The never-arm latch treats an
        ABSENT slug as a confirmed-flat zero, so dropping a slug this page
        could not parse would let a real LONG be armed over; ``None`` is
        UNKNOWN and must fail the gate closed instead.
        """
        snapshots: list[StartupPositionSnapshot] = []
        for slug in sorted(raw_positions):
            payload = raw_positions[slug]
            net_position: str | None = None
            if isinstance(payload, Mapping):
                net_raw = payload.get("netPosition")
                if net_raw is not None:
                    net_position = str(net_raw)
            snapshots.append(StartupPositionSnapshot(slug=slug, net_position=net_position))
        evidence = StartupPositionEvidence(
            ts_ns=now_ns,
            eof_complete=eof_complete,
            position_read_refused=position_read_refused,
            fill_walk_complete=self._fill_walk_complete(),
            positions=tuple(snapshots),
        )
        self._store_set(STARTUP_EVIDENCE_KEY, evidence.to_bytes())

    async def _refresh_startup_position_evidence(self) -> None:
        """C1: fresh positions read at the END of `_connect`.

        Never raises: a read failure or a non-eof-complete page is RECORDED
        as refused, not swallowed and not propagated -- the strategy's
        `on_start` gate is the one place that acts on it.
        """
        now_ns = self._clock.timestamp_ns()
        try:
            payload = await self._private_read(PORTFOLIO_POSITIONS_PATH)
            declared = self._declared_positions(payload)
        except Exception as exc:  # noqa: BLE001 - recorded, never propagated; see docstring
            self._log.warning(
                f"startup evidence: positions read failed ({type(exc).__name__}: {exc}); "
                "recording position_read_refused=True"
            )
            self._write_startup_position_evidence(
                now_ns=now_ns, eof_complete=False, position_read_refused=True, raw_positions={},
            )
            return
        self._write_startup_position_evidence(
            now_ns=now_ns, eof_complete=True, position_read_refused=False, raw_positions=declared,
        )

    def _mark_budget_restored(self, venue_order_id: str) -> None:
        """D2: durable evidence that a permit slot was restored for
        ``venue_order_id`` -- written by the CALLER; `safety.py` stores
        nothing of its own (D1)."""
        self._store_set(f"{BUDGET_RESTORE_KEY_PREFIX}{venue_order_id}", b"1")

    def _budget_was_restored(self, venue_order_id: str) -> bool:
        return self._store_get(f"{BUDGET_RESTORE_KEY_PREFIX}{venue_order_id}") is not None

    def _note_resolver_error(self, intent_id: str, exc: BaseException) -> None:
        """Item 1 (slice 4 review): record one caught resolver-action
        failure without ever raising itself -- the caller's ``continue`` is
        what keeps the polling task alive.

        The counter increments unconditionally; the ERROR log is deduped per
        ``intent_id`` so a still-OPEN intent that fails on every single poll
        (e.g. an unknown permit) logs once, not at the poll interval for the
        rest of the process's life.
        """
        self._resolver_error_count += 1
        if intent_id in self._resolver_errored_intent_ids:
            return
        self._resolver_errored_intent_ids.add(intent_id)
        self._log.error(
            f"resolver: acting on intent {intent_id} raised "
            f"{exc.__class__.__name__}: {exc}; this intent stays AMBIGUOUS and "
            "the resolver keeps polling"
        )

    # -- commission ---------------------------------------------------------

    def calculate_commission(
        self,
        instrument: Instrument,
        last_qty: Quantity,
        last_px: Price,
        liquidity_side: LiquiditySide,
    ) -> Money | None:
        """Override the native reconciliation-fill commission hook.

        ``execution/client.pyx:165`` returns ``None`` unless a venue overrides
        it, and ``live/reconciliation.py:507-508`` turns that ``None`` into
        ``Money(0, quote_currency)`` -- an implied-zero fee booked into a
        realized PnL. This override exists to pre-empt that.

        **It must never raise, and that is a hard contract, not a preference.**
        ``live/reconciliation.py:506`` calls it with NO handler anywhere on the
        path ``execution_engine.py:2599 -> :3499 -> reconciliation.py:507``, so
        an uncontained exception is a node that does not START -- while holding
        real risk, which is the one outcome this module exists to prevent.
        ``Money or None`` is the base contract's own stated return
        (``execution/client.pyx:191``), so ``None`` is inside it.

        The three liquidity sides, and why each is priced rather than refused:

        * ``TAKER`` -- the ordinary case, priced at the venue's coefficient.
        * ``NO_LIQUIDITY_SIDE`` -- IN the base contract's declared domain
          (``:186``) and REACHABLE: a cached marketable LIMIT order infers it
          (``reconciliation.py:468-478``), and a marketable limit is how a
          taker crosses a CLOB. Priced at TAKER, which is the conservative
          reading of an unknown side.
        * ``MAKER`` -- priced at TAKER **plus a latched refusal**. Breezy is
          taker-only, so a maker fill is an event it did not intend; the
          documented maker coefficient is a REBATE, so the taker figure
          OVERSTATES the cost and errs in the safe direction.

        An unknown fee schedule returns ``None`` and latches a refusal (the
        refusal logs at ERROR). Nautilus then books ``Money(0)`` on an inferred
        fill of a position the refusal guarantees Breezy will never trade:
        bookkeeping inaccuracy on a FROZEN position, against a node that cannot
        report at all. That is the trade, stated rather than hidden.
        """
        if liquidity_side == LiquiditySide.MAKER:
            self._refuse(
                f"a MAKER reconciliation fill was priced for {instrument.id}: "
                "Breezy is taker-only, so this is a fill it did not intend, and "
                "the venue's documented maker coefficient is a REBATE -- the "
                "TAKER coefficient charged here overstates the cost"
            )
        try:
            return polymarket_us_fee(instrument, last_qty, last_px)
        except FeeScheduleUnknownError as exc:
            self._refuse(
                f"the fee schedule for {instrument.id} is UNKNOWN, so a "
                f"reconciliation fill cannot be priced ({exc}); Nautilus will "
                "book a ZERO fee on it, and this refusal is what guarantees "
                "the position it belongs to is never traded"
            )
            return None
        except Exception as exc:  # noqa: BLE001 - see the docstring: this MUST NOT raise
            self._refuse(
                f"a reconciliation fill for {instrument.id} could not be priced "
                f"({type(exc).__name__}: {exc}); Nautilus will book a ZERO fee "
                "on it, and this refusal freezes the instrument"
            )
            return None

    # -- the order surface: refusal, and nothing else -----------------------

    def _deny(self, order: Any, reason: str, now_ns: int) -> None:
        """Log + ``OrderDenied`` -- the shared D1-D9 exit. Named in the E0-NOSEND allowlist."""
        self._log.error(f"Refusing {order.client_order_id!r}: {reason}")
        self.generate_order_denied(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            reason=reason,
            ts_event=now_ns,
        )

    def _retire(self, intent_id: str, retire_name: str, now_ns: int) -> None:
        """Retire the armed intent -- shared D9 exit. E0-NOSEND allowlisted, like :meth:`_deny`."""
        self._latch.retire(
            intent_id,
            submit_chain.retirement_member(self._retirement_reasons, retire_name),
            now_ns=now_ns,
        )
        # Item 3 (2026-09-11 incident addendum): every retirement path runs
        # through here, so this is the ONE place the stale-intent alert's
        # bookkeeping clears -- a later intent that reaches the same age
        # alerts again. A no-op when `intent_id` was never latched.
        self._resolver_stale_alerted_intent_ids = self._resolver_stale_alerted_intent_ids - {
            intent_id
        }
        self._resolver_stale_alert_details.pop(intent_id, None)

    def _generate_submitted(self, order: Any, now_ns: int) -> None:
        """``OrderSubmitted`` -- shared by every D9 leaf that reaches a POST."""
        self.generate_order_submitted(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            ts_event=now_ns,
        )

    def _note_ambiguous_open(
        self,
        *,
        intent_id: str,
        venue_order_id: str,
        order: Any,
        notional_usd: Decimal,
        booking: Any,
        now_ns: int,
        create_detail: str | None = None,
        fill_parse_error: str | None = None,
    ) -> None:
        """Resolution A/E: record durable resolver context for a with-id
        AMBIGUOUS outcome, and hold the live ``SpendBooking`` for
        same-process true-up. Inert sync callee, named in the E0-NOSEND
        allowlist like :meth:`_deny`/:meth:`_retire` -- writes only to the
        already-open local store and a process-local dict; reaches no
        network.

        SP-2 I3: ``create_detail`` / ``fill_parse_error`` are attribute
        reads from the caller's already-classified ``outcome`` -- both
        already capped and names-only by the time they reach here. This
        method does NOT truncate them again (S-L1).
        """
        context = AmbiguousResolverContext(
            intent_id=intent_id,
            venue_order_id=venue_order_id,
            instrument_id=str(order.instrument_id),
            client_order_id=str(order.client_order_id.value),
            strategy_id=str(order.strategy_id.value),
            notional_usd=notional_usd,
            booking_id=booking.booking_id,
            created_ns=now_ns,
            create_detail=create_detail,
            fill_parse_error=fill_parse_error,
        )
        self._store_set(f"{RESOLVER_CONTEXT_KEY_PREFIX}{intent_id}", context.to_bytes())
        self._ambiguous_bookings[intent_id] = booking

    async def _submit_order(self, command: SubmitOrder) -> None:
        """Authorize, arm, POST, retire. Deny before any venue contact."""
        order = command.order
        now_ns = self._clock.timestamp_ns()
        if self._trading_refusals:
            reason = submit_chain.latched_refusal_reason(self._trading_refusals[0].reason)
            return self._deny(order, reason, now_ns)
        if self._cache.account_for_venue(self.venue) is None:
            reason = submit_chain.missing_account_reason(self.venue)
            return self._deny(order, reason, now_ns)
        if self._order_sender is None:
            return self._deny(order, submit_chain.SENDER_ABSENT_REASON, now_ns)
        if write_transport.WRITE_CANONICAL_STRING_VERIFIED is not True:
            return self._deny(order, submit_chain.CANONICAL_UNVERIFIED_REASON, now_ns)
        instrument = self._cache.instrument(order.instrument_id)
        unmappable = submit_chain.unmappable_order_reason(order, instrument)
        if unmappable is not None:
            return self._deny(order, unmappable, now_ns)
        if submit_chain.permit_is_missing(self._permit):
            return self._deny(order, submit_chain.PERMIT_ABSENT_REASON, now_ns)
        # SAFETY C1 (plan rev 6.1): the authoritative re-check, immediately
        # before the permit spend below and with NO `await` between here and
        # `self._latch.arm(...)`. Two `_submit_order` tasks created in one
        # synchronous burst (`submit_order` wraps every command in its own
        # task, `live/execution_client.py:277-282`) cannot interleave between
        # this line and `arm()`: whichever task's `SubmitOrder` was scheduled
        # first runs this whole prefix -- including `arm()` -- with no
        # suspension point, so the second task observes `is_latched() is
        # True` here, before it has spent anything. This is a WAIT, not a
        # refusal: no money, no permit, no `_trading_refusals` entry.
        if self._latch is not None and self._latch.is_latched():
            return self._deny(order, submit_chain.OPEN_INTENT_WAIT_REASON, now_ns)
        # Item 4 (slice 4 review): the family-halt chokepoint veto -- the
        # SAME class of race as SAFETY C1 above (an already-created
        # `_submit_order` task is not reachable by the strategy's own
        # `_hunt_tick` pre-check), fixed the SAME way: an authoritative
        # synchronous re-check immediately before the permit spend, with NO
        # `await` between this line and `assert_live_order_submission_
        # permitted` below. A non-None reason is a WAIT, not a refusal: no
        # money, no permit, no `_trading_refusals` entry -- the reason
        # string the veto returned is carried verbatim on the denial.
        if self._submit_veto is not None:
            veto_reason = self._submit_veto()
            if veto_reason is not None:
                return self._deny(order, veto_reason, now_ns)
        try:
            assert_live_order_submission_permitted(
                credentials=self._credentials,
                permit=self._permit,
                manual_order_indicator=False,
                order_notional_usd=submit_chain.order_notional_usd(order),
                request_fingerprint=submit_chain.order_fingerprint_bytes(order),
                now_ns=now_ns,
            )
        except LiveTradingPermissionError as exc:
            return self._deny(order, f"{exc}; this client refuses to submit", now_ns)
        body = submit_chain.build_order_body(order, instrument)
        encoded = submit_chain.encode_order_body(body)
        try:
            booking = self._ledger.authorize_order_cost(
                price_usd=submit_chain.order_price_decimal(order),
                quantity=submit_chain.order_quantity_decimal(order),
                now_ns=now_ns,
            )
        except LiveTradingPermissionError as exc:
            return self._deny(order, f"{exc}; this client refuses to submit", now_ns)
        if self._intent_reconciled is not True:
            self._ledger.release_booking(booking, now_ns=now_ns)
            return self._deny(order, submit_chain.RECONCILE_NOT_RUN_REASON, now_ns)
        try:
            intent = self._latch.arm(submit_chain.intent_fingerprint(order), now_ns=now_ns)
        except Exception as exc:  # noqa: BLE001 - store/latch failures must deny, not crash the loop
            self._ledger.release_booking(booking, now_ns=now_ns)
            if submit_chain.is_latch_arm_refusal(exc):
                return self._deny(order, submit_chain.LATCH_ARM_REFUSED_REASON, now_ns)
            return self._deny(order, submit_chain.STORE_RAISED_REASON, now_ns)
        headers = self._write_signer.sign_headers(
            write_transport._WRITE_METHOD,
            write_transport.ORDERS_PATH,
        )
        try:
            response = await self._order_sender.post_order(
                self._api_base_url,
                headers=headers,
                body=encoded,
            )
        except Exception as exc:
            self._refuse(submit_chain.AMBIGUOUS_REASON)
            self._log.error(submit_chain.AMBIGUOUS_REASON)
            # Exception TYPE only -- never its message, which may embed a
            # URL, header, or other request detail the transport layer
            # raised against (see `redact_url` at the transport boundary,
            # which this log line does not have the luxury of re-applying).
            self._log.error(
                "create-order AMBIGUOUS detail: path=exception "
                f"exc_type={exc.__class__.__name__} "
                f"client_order_id={order.client_order_id.value}"
            )
            if submit_chain.is_cancelled(exc):
                raise
            return
        outcome = submit_chain.classify_create_order_outcome(
            response,
            instrument=instrument,
            account_id=self._issued_account_id,
            ts_init=now_ns,
        )
        classified_line = (
            f"create-order classified kind={outcome.kind} {outcome.detail} "
            f"client_order_id={order.client_order_id.value}"
        )
        if outcome.kind == submit_chain.KIND_AMBIGUOUS:
            self._log.error(classified_line)
        else:
            # E0-NOSEND allowlists `_log.error` / `_log.warning` on this
            # coroutine, not `_log.info`. WARNING is the closest permitted
            # level for a non-AMBIGUOUS classified line.
            self._log.warning(classified_line)
        if outcome.venue_order_id is not None:
            # A1: the ONE point all four outcome kinds pass through --
            # ACCEPT_FILL, ZERO_FILL and a with-id AMBIGUOUS all carry a
            # venue id here; a REJECT and a no-id AMBIGUOUS do not (AC-2).
            # Corroborating evidence written AFTER the venue was POSTed:
            # must refuse and FALL THROUGH on failure, never crash or
            # short-circuit the dispatch below (A-B2 -- no `return`).
            try:
                self.record_venue_order_id(
                    submit_chain.venue_order_id(outcome.venue_order_id),
                    order.client_order_id,
                )
            except Exception as exc:  # noqa: BLE001
                self._log.error(
                    f"{_VENUE_ID_MAP_WRITE_FAILED}: {exc.__class__.__name__}: {exc}; "
                    f"venue_order_id={outcome.venue_order_id} "
                    f"client_order_id={order.client_order_id.value}"
                )
                self._refuse(_VENUE_ID_MAP_WRITE_FAILED)
        retire_name = outcome.retirement_name
        if (
            outcome.kind == submit_chain.KIND_ACCEPT_FILL
            and outcome.fill is not None
            and retire_name is not None
            and outcome.filled_cost_usd is not None
        ):
            fill = outcome.fill
            # I1b (LIVE_FILL_SCORING_CHAIN_2026-09-05): `record_fill` is the
            # FIRST effectful action of this branch -- before `true_up_booking`,
            # `_retire`, `_generate_submitted` and `generate_order_filled` --
            # so a crash right after the venue's answer still leaves durable
            # evidence on disk (R-7; `SqliteStateStore.set` COMMITs before
            # returning). Building `record` has no side effect of its own, so
            # it stays inside this same `try`: an accept-fill outcome missing
            # its order-level totals (should be impossible after I1a) is
            # refused on the identical failure path, never guessed at.
            record: DurableFillRecord | None = None
            try:
                if (
                    outcome.cumulative_qty is None
                    or outcome.cumulative_cost is None
                    or outcome.cumulative_fee is None
                ):
                    raise PolymarketUSError(
                        "an accept-fill outcome carried no order-level totals; "
                        "a durable fill record cannot be built"
                    )
                record = DurableFillRecord(
                    venue_order_id=fill.venue_order_id.value,
                    client_order_id=order.client_order_id.value,
                    instrument_id=order.instrument_id.value,
                    order_side=LONG_ONLY_SIDE,
                    cumulative_qty=outcome.cumulative_qty,
                    cumulative_cost=outcome.cumulative_cost,
                    cumulative_fee=outcome.cumulative_fee,
                    fee_reconciled=outcome.fee_reconciled,
                    ts_event=fill.ts_event,
                    venue_fee_raw=fill.commission_raw,
                    trade_id=fill.trade_id.value,
                    order_qty=submit_chain.order_quantity_decimal(order),
                )
                self.record_fill(record)
            except Exception as exc:  # noqa: BLE001 - deliberately broad: this
                # guards ONE evidence write and ANY failure of it must halt
                # trading rather than lose the event. Narrowing to the known
                # raisers (an unreadable index, a store error, a `to_bytes`
                # encode failure, or the totals guard above) would let an
                # unlisted exception escape into the task handler, which
                # swallows it -- silently losing both the record and the
                # refusal.
                if record is None:
                    detail = "no record built"
                else:
                    fill_record_bytes = record.to_bytes()
                    detail = fill_record_bytes.decode()
                self._log.error(
                    f"{_FILL_WRITE_FAILED}: {exc.__class__.__name__}: {exc}; record={detail}"
                )
                self._refuse(_FILL_WRITE_FAILED)
            else:
                self._ledger.true_up_booking(
                    booking, filled_cost_usd=outcome.filled_cost_usd, now_ns=now_ns
                )
                self._retire(intent.intent_id, retire_name, now_ns)
                if outcome.fee_reconciled is False:
                    # The fill is real; only the fee is untrusted -- the
                    # record is STILL written and retire/publish still
                    # proceed. I2 keeps an unreconciled fill out of scoring.
                    self._refuse(_FEE_UNRECONCILED)
            self._generate_submitted(order, now_ns)  # UNCONDITIONAL: Nautilus's
            # order FSM has NO (INITIALIZED, FILLED) transition
            # (`_ORDER_STATE_TABLE`, `model/orders/base.pyx:94-157`), so
            # skipping `OrderSubmitted` here would make the `OrderFilled`
            # below unbookable -- the exact outcome this ordering prevents.
            self.generate_order_filled(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                venue_order_id=fill.venue_order_id,
                venue_position_id=None,
                trade_id=fill.trade_id,
                order_side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                last_qty=fill.last_qty,
                last_px=fill.last_px,
                quote_currency=USD,
                commission=fill.commission,
                liquidity_side=LiquiditySide.TAKER,
                ts_event=fill.ts_event,
            )
            return
        if (
            outcome.kind == submit_chain.KIND_ZERO_FILL
            and retire_name is not None
            and outcome.venue_order_id is not None
        ):
            self._ledger.true_up_booking(
                booking, filled_cost_usd=submit_chain.ZERO, now_ns=now_ns
            )
            self._retire(intent.intent_id, retire_name, now_ns)
            self._generate_submitted(order, now_ns)
            self.generate_order_canceled(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                venue_order_id=submit_chain.venue_order_id(outcome.venue_order_id),
                ts_event=now_ns,
            )
            return
        if outcome.kind == submit_chain.KIND_REJECT and retire_name is not None:
            self._ledger.release_booking(booking, now_ns=now_ns)
            self._retire(intent.intent_id, retire_name, now_ns)
            self.generate_order_rejected(
                strategy_id=order.strategy_id,
                instrument_id=order.instrument_id,
                client_order_id=order.client_order_id,
                reason=outcome.reason,
                ts_event=now_ns,
            )
            return
        self._refuse(submit_chain.AMBIGUOUS_REASON)
        self._log.error(submit_chain.AMBIGUOUS_REASON)
        # `outcome.detail` is redacted (shape and length only, never body
        # content) by `submit_chain._body_detail` -- safe to log even
        # though the response it summarises may be adversarial.
        if outcome.detail is not None:
            # `outcome.fill_parse_error`, when present, is the
            # `ExecutionReportMappingError` message `fill_generation`
            # swallowed to reach this fallthrough -- names-only (its own
            # full key tree, never a value; see `reports.py`'s
            # `_key_tree`), so it is safe to log verbatim. Absent on every
            # other AMBIGUOUS cause (no response, a non-mapping body, a
            # missing order id).
            fill_parse_error_suffix = (
                f" fill_parse_error={outcome.fill_parse_error}"
                if outcome.fill_parse_error is not None
                else ""
            )
            self._log.error(
                "create-order AMBIGUOUS detail: path=classified "
                f"{outcome.detail} client_order_id={order.client_order_id.value}"
                f"{fill_parse_error_suffix}"
            )
        if outcome.generate_submitted:
            self._generate_submitted(order, now_ns)
        if outcome.venue_order_id is not None:
            # L-36 / Resolution A2: with-id only. A no-id AMBIGUOUS has
            # nothing a GET could ever resolve and stays operator-only
            # (`clear_submit_intent`, untouched).
            self._note_ambiguous_open(
                intent_id=intent.intent_id,
                venue_order_id=outcome.venue_order_id,
                order=order,
                notional_usd=submit_chain.order_notional_usd(order),
                booking=booking,
                now_ns=now_ns,
                create_detail=outcome.detail,
                fill_parse_error=outcome.fill_parse_error,
            )

    async def _cancel_order(self, command: CancelOrder) -> None:
        """Refuse. There is nothing to cancel: nothing can be sent."""
        reason = (
            "EXEC_SPINE R-4 has no order path, so no order of ours can be "
            "resting at the venue to cancel"
        )
        self._log.error(f"Refusing to cancel {command.client_order_id!r}: {reason}")
        self.generate_order_cancel_rejected(
            strategy_id=command.strategy_id,
            instrument_id=command.instrument_id,
            client_order_id=command.client_order_id,
            venue_order_id=command.venue_order_id,
            reason=reason,
            ts_event=self._clock.timestamp_ns(),
        )

    async def _submit_order_list(self, command: SubmitOrderList) -> None:
        raise NotImplementedError(self._unsupported("order lists"))

    async def _modify_order(self, command: ModifyOrder) -> None:
        raise NotImplementedError(self._unsupported("order modification"))

    async def _cancel_all_orders(self, command: CancelAllOrders) -> None:
        raise NotImplementedError(self._unsupported("cancel-all"))

    async def _batch_cancel_orders(self, command: BatchCancelOrders) -> None:
        raise NotImplementedError(self._unsupported("batch cancel"))

    @staticmethod
    def _unsupported(what: str) -> str:
        """Raise rather than no-op: a silent no-op reads as acceptance."""
        return (
            f"{what} is not supported by the Polymarket.us execution client. "
            "Only _submit_order and _cancel_order carry denial bodies; this "
            "path raises so it cannot be mistaken for success"
        )

    # -- refusals -----------------------------------------------------------

    def _refuse(
        self,
        reason: str,
        *,
        classification: RefusalClass = RefusalClass.DURABLE,
    ) -> None:
        """Record a reason this client cannot be trusted to trade, and alert.

        ERROR, not WARNING: an unattributable position is the operator's
        problem to resolve, and the node will go on running -- refusing -- in
        the meantime. Deduplicated so a per-reconcile loop cannot bury the log.

        ``classification`` (R-6.5a) defaults to
        :attr:`~breezy.adapters.polymarket_us.exec.refusals.RefusalClass.DURABLE`
        -- the safe default that keeps invariant 1 unweakened for every
        producer that does not (yet) have an HTTP status to classify from.
        The signature keeps ``(reason: str)`` as its whole positional shape so
        the 25-site producer pin
        (``tests/unit/test_exec_refusal_health_surface.py``, keyed by
        enclosing-function#ordinal) does not move: this is a keyword-only
        addition, not a change to how any existing call site is shaped.
        Every latched entry is instrument-UNSCOPED (``instrument=""``) from
        this method -- no producer here names one yet -- so nothing recorded
        through this method can ever be cleared by
        :meth:`_map_position`'s :func:`~breezy.adapters.polymarket_us.exec.
        refusals.refusals_after_successful_reconcile` call, which matches
        refusals only by a specific instrument.

        **R-6c: the first refusal while not yet degraded also degrades the
        component.** An ERROR line and a ``trading_refusals`` property are
        both things a HUMAN reads; neither is a state anything can act on.
        ``Component.degrade()`` (``$NT/common/component.pyx:2098-2127``) is
        the native FSM transition for exactly this -- "running, but not
        healthy" -- and it publishes a ``ComponentStateChanged`` on
        ``events.system.<component_id>`` (``:2210-2225``). Nothing here
        reimplements it and nothing here subscribes to it: the
        operator-facing subscriber lives at the wiring layer in
        ``breezy.runtime.component_health_watch``, because
        ``breezy.runtime.health`` is a module NO module under ``exec/`` may
        import (barrier E0-TRANSPORT,
        ``tests/unit/test_execution_egress_firewall_guard.py``).

        **R-6.5a fix: gated on ``self.is_degraded`` (native FSM state), never
        on ``self._trading_refusals`` being momentarily empty.**
        :meth:`_map_position`'s reconciliation-clearing call
        (:func:`~breezy.adapters.polymarket_us.exec.refusals.
        refusals_after_successful_reconcile`) can drop every remaining entry
        for one instrument and leave the list empty while the component is
        STILL degraded from an earlier refusal. The list's own emptiness is
        therefore not a proxy for "never yet degraded" -- only the
        component's own state is, and tracking a second, parallel boolean
        here would just be a second place for the two to drift.

        Legal from ``RUNNING``, which is always this client's state when a
        refusal fires: ``NautilusKernel.start_async`` runs ``_start_engines()``
        (``$NT/system/kernel.py:1021``) -- which calls ``client.start()``
        SYNCHRONOUSLY via ``ExecutionEngine._start``
        (``$NT/execution/engine.pyx:666-668``) -- BEFORE ``_connect_clients()``
        (``:1022``) schedules ``_connect``. It is also SAFE from any other
        state without a guard here: ``_trigger_fsm`` catches
        ``InvalidStateTrigger``, logs it and returns without publishing
        (``component.pyx:2188-2196``), so a refusal can never raise out of
        this method on account of the FSM.

        Driven ONCE, off the same latch that dedupes the ERROR log, so the
        subscriber alerts exactly once no matter how many reconcile cycles
        refuse. **DEGRADED is a health INDICATOR, not a kill switch**: several
        of the twenty-five producers that reach this method are ROUTINE on an
        account an operator has also traded by hand (the full triage lives in
        ``tests/unit/test_exec_refusal_health_surface.py``), so nothing here
        stops the node, publishes a shutdown, or writes a fault latch.
        """
        if any(refusal.reason == reason for refusal in self._trading_refusals):
            return
        was_already_degraded = self.is_degraded
        self._trading_refusals.append(
            ClassifiedRefusal(instrument="", reason=reason, classification=classification)
        )
        self._log.error(f"Trading refused: {reason}")
        if not was_already_degraded:
            self.degrade()

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(client_id={self.id}, venue={self.venue}, "
            f"account_id={self._issued_account_id}, "
            f"refusals={len(self._trading_refusals)})"
        )
