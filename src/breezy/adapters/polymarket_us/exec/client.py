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
from collections.abc import Mapping
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
    OrderType,
    PositionSide,
)
from nautilus_trader.model.identifiers import AccountId, ClientOrderId, VenueOrderId

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
)
from breezy.adapters.polymarket_us.symbology import slug_to_instrument_id
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
    from nautilus_trader.model.identifiers import ClientId, InstrumentId, Venue
    from nautilus_trader.model.instruments import Instrument
    from nautilus_trader.model.objects import Money, Price, Quantity

    from breezy.ingest.gate import ClosableStateStore, StateStoreOpener

__all__ = [
    "FILL_INDEX_KEY_PREFIX",
    "FILL_KEY_PREFIX",
    "VENUE_ORDER_ID_KEY_PREFIX",
    "DurableFillRecord",
    "PolymarketUSExecutionClient",
    "PrivateRead",
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
    ts_event: int

    def to_bytes(self) -> bytes:
        return json.dumps(
            {
                "venueOrderId": self.venue_order_id,
                "clientOrderId": self.client_order_id,
                "instrumentId": self.instrument_id,
                "orderSide": self.order_side,
                "cumulativeQty": str(self.cumulative_qty),
                "cumulativeCost": str(self.cumulative_cost),
                "tsEvent": self.ts_event,
            },
            sort_keys=True,
        ).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        """Decode a record, refusing anything that is not exactly one.

        Every field is required. A partially-decodable record is refused
        rather than defaulted: a fill record missing its price is not a fill
        record with a zero price.
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
                ts_event=int(payload["tsEvent"]),
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ExecutionReportMappingError(
                f"a durable fill record is malformed: {type(exc).__name__}: {exc}"
            ) from None


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
        self._intent_reconciled: bool = False

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
        """
        try:
            self._set_account_id(self._issued_account_id)
            self._open_state_store()
            await self._wait_for_instruments()
            await self._publish_account_state()
            await self._confirm_account_registered()
            self._reconcile_submit_intent()
        except BaseException as exc:
            record_fatal_exec_fault(
                component=str(self.id),
                reason=(
                    f"_connect failed before the client reached a connected "
                    f"state ({type(exc).__name__}: {exc}); no order can ever "
                    "be evaluated against a client that never connected"
                ),
            )
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
        venue-touching module with no allowlist. Breezy has also submitted no
        order -- this increment cannot -- so an empty list is not merely
        permitted, it is TRUE.
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

    def _generate_submitted(self, order: Any, now_ns: int) -> None:
        """``OrderSubmitted`` -- shared by every D9 leaf that reaches a POST."""
        self.generate_order_submitted(
            strategy_id=order.strategy_id,
            instrument_id=order.instrument_id,
            client_order_id=order.client_order_id,
            ts_event=now_ns,
        )

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
            if submit_chain.is_cancelled(exc):
                raise
            return
        outcome = submit_chain.classify_create_order_outcome(
            response,
            instrument=instrument,
            account_id=self._issued_account_id,
            ts_init=now_ns,
        )
        retire_name = outcome.retirement_name
        if (
            outcome.kind == submit_chain.KIND_ACCEPT_FILL
            and outcome.fill is not None
            and retire_name is not None
            and outcome.filled_cost_usd is not None
        ):
            self._ledger.true_up_booking(
                booking, filled_cost_usd=outcome.filled_cost_usd, now_ns=now_ns
            )
            self._retire(intent.intent_id, retire_name, now_ns)
            self._generate_submitted(order, now_ns)
            fill = outcome.fill
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
        if outcome.generate_submitted:
            self._generate_submitted(order, now_ns)

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
