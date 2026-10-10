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
   Sole carve-out: resolver-retired terminal zero-fill, accept-fill or no-id
   no-fill clears the AMBIGUOUS refusal only (2026-10-02; accept-fill and
   no-id 2026-10-03).
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
import dataclasses
import json
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Final, NamedTuple, Protocol, Self

from nautilus_trader.core.uuid import UUID4
from nautilus_trader.execution.reports import (
    FillReport,
    OrderStatusReport,
    PositionStatusReport,
)
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
    TimeInForce,
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
from breezy.adapters.polymarket_us.account_activity import (
    PORTFOLIO_ACTIVITIES_PATH,
    TradeActivityRef,
    page_min_create_ts_ns,
    trade_rows_for_order,
)
from breezy.adapters.polymarket_us.errors import (
    ExecutionReportMappingError,
    FeeScheduleUnknownError,
    PolymarketUSError,
    VenuePayloadError,
)
from breezy.adapters.polymarket_us.exec import submit_chain
from breezy.adapters.polymarket_us.exec.endpoints import (
    ACCOUNT_BALANCES_PATH,
    OPEN_ORDERS_PATH,
    PORTFOLIO_POSITIONS_PATH,
)
from breezy.adapters.polymarket_us.exec.no_side_keys import (
    NO_SIDE_FIRST_LIVE_ORDER_KEY,
    first_live_order_payload,
)
from breezy.adapters.polymarket_us.exec.refusals import (
    ClassifiedRefusal,
    PrivateReadRefused,
    RefusalClass,
    classify_venue_refusal,
    refusals_after_successful_reconcile,
)
from breezy.adapters.polymarket_us.exec.reports import (
    NON_FILL_TERMINAL_STATUSES,
    OpenOrderRecord,
    build_execution_mass_status,
    derive_position_cost_basis,
    parse_account_balances,
    parse_open_orders,
    parse_order_status_report,
    parse_position_status_report,
    position_leg,
)
from breezy.adapters.polymarket_us.exec_fault import record_fatal_exec_fault
from breezy.adapters.polymarket_us.fees import (
    fee_schedule_bucket,
    polymarket_us_fee,
    taker_fee_at_fill,
    taker_fee_coefficient_of,
)
from breezy.adapters.polymarket_us.no_id_attribution import (
    NoIdEcho,
    NoIdLeg,
    classify_no_id_evidence,
    holding_delta_consistent,
    manual_leg_net_effect,
    no_id_aggressor_legs,
)
from breezy.adapters.polymarket_us.operator_controls import (
    DailyBudgetExhausted,
    SpendBooking,
    utc_day_for_ns,
)
from breezy.adapters.polymarket_us.parsing import _to_decimal
from breezy.adapters.polymarket_us.safety import (
    LiveTradingPermissionError,
    SessionNotionalExhausted,
    assert_live_order_submission_permitted,
    restore_live_trading_budget,
    seed_permit_budget_from_prior_spend,
    unrestore_live_trading_budget,
)
from breezy.adapters.polymarket_us.symbology import (
    base_slug_of,
    leg_of,
    no_leg_instrument_id,
    slug_to_instrument_id,
)
from breezy.domain.position_reporting_lag import (
    FILL_TS_EVENT_SOURCE_VENUE_TRANSACT_TIME,
    PositionReportingLag,
)
from breezy.ingest.gate import assert_state_store_durable
from breezy.persistence.exit_tags import (
    EXIT_CLIENT_ORDER_ID_TAG_PREFIX,
    EXIT_FAMILY_TAG_PREFIX,
    EXIT_POSITION_TAG_PREFIX,
    EXIT_RULE_TAG_PREFIX,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from datetime import date

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
    from nautilus_trader.execution.reports import ExecutionMassStatus
    from nautilus_trader.model.identifiers import ClientId, Venue
    from nautilus_trader.model.instruments import Instrument
    from nautilus_trader.model.objects import Price, Quantity

    from breezy.adapters.polymarket_us.leg_prices import Leg
    from breezy.ingest.gate import ClosableStateStore, StateStoreOpener
    from breezy.persistence.family_manifest import FamilyManifest

__all__ = [
    "BUDGET_EXHAUSTED_KEY_PREFIX",
    "BUDGET_RESTORE_KEY_PREFIX",
    "FILL_BY_DAY_KEY_PREFIX",
    "FILL_INDEX_KEY_PREFIX",
    "FILL_KEY_PREFIX",
    "RESOLVER_CONTEXT_KEY_PREFIX",
    "STARTUP_EVIDENCE_KEY",
    "STARTUP_OPEN_ORDERS_PRESENT_REASON",
    "VENUE_ORDER_ID_KEY_PREFIX",
    "AmbiguousResolverContext",
    "DurableFillRecord",
    "PolymarketUSExecutionClient",
    "PrivateRead",
    "StartupOpenOrderSnapshot",
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

#: AC6b/G4 (EDGE-2 plan r3, D9): ``<UTC day of DurableFillRecord.ts_event>``
#: -> the venue order ids whose fill records were written for that day, a
#: CANDIDATE set only (``record.ts_event`` is the sole authority on which
#: day a record actually belongs to -- a stale entry here is harmless,
#: filtered by the same day check the per-instrument walk already applies).
#: Exists because the boot-time spend seed (`_seed_spend_from_durable_fills`)
#: otherwise walks only `self._instrument_provider.list_all()`, and a
#: resolver fill resolved against a PAST-DAY instrument (the past-day loader
#: adds its instrument to `self._cache` only, never to the provider) is
#: reachable through no other index -- the store has no prefix scan. Written
#: INLINE inside :meth:`record_fill`, after the per-instrument
#: `FILL_INDEX_KEY_PREFIX` entry and before `FILL_BY_FINGERPRINT_KEY_PREFIX`,
#: for the same reason that entry is inline (see its own docstring below):
#: this module's own E0-NOSEND-RESOLVER invariant permits no separate
#: `self._store_set` callee from a scanned resolver coroutine.
FILL_BY_DAY_KEY_PREFIX: Final[str] = f"{STATE_KEY_NAMESPACE}fill_by_day/"

#: SP-3r: ``<UTC day>:<intent_fingerprint>`` -> the venue order id whose
#: fill record it names. Written INLINE inside :meth:`record_fill` (never as
#: a separate coroutine-level call -- E0-NOSEND's per-coroutine callee
#: allowlist has no ``self._store_set`` entry, and this module's own hard
#: invariant is to never widen it), always AFTER the fill record and its
#: `FILL_INDEX_KEY_PREFIX` entry, so a crash before this write still leaves
#: `_has_durable_fill_record` free to answer False (fail closed) rather than
#: finding a durable fill index it never wrote for.
#:
#: Scoped by UTC day (security review, r1.1) as defence in depth against
#: `client_order_id` reuse: Nautilus's native `ClientOrderIdGenerator`
#: (`common/generators.pyx`) embeds a minute-resolution UTC datetime tag in
#: every generated id, so `intent_fingerprint` (which hashes `client_order_id`
#: among other order fields) already differs across real UTC days under
#: normal operation -- the day scope guards a generator reset / clock
#: anomaly / `use_uuids=False` counter collision, not a reachable path today.
FILL_BY_FINGERPRINT_KEY_PREFIX: Final[str] = f"{STATE_KEY_NAMESPACE}fill_by_fingerprint/"

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

#: RESTING_BID_HUNT Rev 2 section 4.3: the never-arm refusal token the
#: strategy-side predicate (``trial_day_latch.startup_evidence_refusal_
#: reason``) returns, and this client logs at ERROR, when the boot's
#: open-order enumeration came back NON-EMPTY. Defined here (the producer,
#: lowest layer) so both sides spell one string.
STARTUP_OPEN_ORDERS_PRESENT_REASON: Final[str] = "startup_open_orders_present"

#: How many leading characters of a venue order id an ERROR line may carry.
_ORDER_ID_REDACT_PREFIX: Final[int] = 4


def _redact_order_id(venue_order_id: str) -> str:
    """A venue order id reduced to a short prefix for a log line."""
    return f"{venue_order_id[:_ORDER_ID_REDACT_PREFIX]}\u2026"


#: AUD-13b (plan §6 "Fail-closed semantics"): the event name every durable-
#: reconciliation refusal is surfaced under, and its NAMED latches. Each
#: refusal returns empty reports for its scope AND latches one of these --
#: emptiness is never indistinguishable from "nothing to report", and no
#: refusal borrows another's name.
RECONCILIATION_REFUSAL_EVENT: Final[str] = "reconciliation_refusal"
POSITIONS_READ_FAILED: Final[str] = "positions_read_failed"
RECORD_VENUE_DISAGREEMENT: Final[str] = "record_venue_disagreement"
FEE_COEFFICIENT_AMBIGUOUS: Final[str] = "fee_coefficient_ambiguous"
#: AUD-13b silent-failure review finding 1: an UNEXPECTED defect building one
#: position's reports (never a foreign payload shape -- that is
#: ``positions_read_failed`` -- and never a corrupt fee input -- that is
#: ``fee_coefficient_ambiguous``). Scoped to the ONE position it hit so a
#: defect in one position's build never drops every other position's reports.
DURABLE_REPORTS_BUILD_FAILED: Final[str] = "durable_reports_build_failed"

#: FU-8 r2/r2.1 (option A): a resolver-discovered fill whose order is unknown
#: to THIS run's cache (a cross-session fill) is NEVER booked at runtime --
#: booking it would double an already-visible position (L-47) or open a
#: phantom long on a settled market (L-18). This latch NAMES that outcome; it
#: is informational, NOT a control (the boot's own AUD-13b pass, and for a
#: venue-held T2 case `RECORD_VENUE_DISAGREEMENT`, are what actually alert and
#: attribute). Never counted on the boot pass's own `refusals` line --
#: `_BOOT_PASS_REFUSAL_LATCHES` below is what that sum iterates.
RESOLVER_FILL_NOT_BOOKED: Final[str] = "resolver_fill_not_booked"

#: What `_map_position` did with one venue position (AUD-13b). Anything that
#: is not one of the first three -- a mapping error, a non-long side -- is
#: `_MAP_UNPARSEABLE`, which fails the WHOLE read for the durable reports.
_MAP_OPEN: Final[str] = "open"
_MAP_GATED_OUT: Final[str] = "gated_out"
_MAP_INSTRUMENT_ABSENT: Final[str] = "instrument_absent"
_MAP_UNPARSEABLE: Final[str] = "unparseable"

#: The FIXED enum ``detail`` per latch (never an id, a date or exception text).
_RECONCILIATION_REFUSAL_DETAILS: Final[Mapping[str, str]] = {
    POSITIONS_READ_FAILED: "POSITIONS_READ_FAILED",
    RECORD_VENUE_DISAGREEMENT: "RECORD_VENUE_DISAGREEMENT",
    FEE_COEFFICIENT_AMBIGUOUS: "FEE_COEFFICIENT_AMBIGUOUS",
    DURABLE_REPORTS_BUILD_FAILED: "DURABLE_REPORTS_BUILD_FAILED",
    RESOLVER_FILL_NOT_BOOKED: "RESOLVER_FILL_NOT_BOOKED",
}

#: FU-8 r2.1 (architect REQUEST_CHANGES, load-bearing): the four latches the
#: boot pass's own `refusals` field sums over (`_durable_reconciliation_pass`
#: below). `RESOLVER_FILL_NOT_BOOKED` is deliberately EXCLUDED -- it is not a
#: boot-pass outcome at all (the resolver latches it outside any mass-status
#: pass), and it has no `refusals_resolver_fill_not_booked` field in
#: `_RECONCILIATION_COUNT_FIELDS`. Iterating `_RECONCILIATION_REFUSAL_DETAILS`
#: directly there instead would KeyError the moment this latch existed.
_BOOT_PASS_REFUSAL_LATCHES: Final[tuple[str, ...]] = (
    POSITIONS_READ_FAILED,
    RECORD_VENUE_DISAGREEMENT,
    FEE_COEFFICIENT_AMBIGUOUS,
    DURABLE_REPORTS_BUILD_FAILED,
)

#: The counts line's fields, in their fixed order (plan §6 "Regression
#: detector"). ``refusals`` is the sum of the per-cause fields.
_RECONCILIATION_COUNT_FIELDS: Final[tuple[str, ...]] = (
    "order_reports",
    "fill_reports",
    "records_considered",
    "gated_out",
    "instrument_absent",
    "refusals",
    f"refusals_{POSITIONS_READ_FAILED}",
    f"refusals_{RECORD_VENUE_DISAGREEMENT}",
    f"refusals_{FEE_COEFFICIENT_AMBIGUOUS}",
    f"refusals_{DURABLE_REPORTS_BUILD_FAILED}",
)


def format_reconciliation_counts_line(counts: Mapping[str, int]) -> str:
    """The one fixed-shape INFO line per durable reconciliation pass.

    A silent regression to ``[]`` reads ``order_reports=0 records_considered=N``,
    a different and greppable shape from a legitimate ``records_considered=0``.
    """
    fields = " ".join(f"{name}={counts[name]}" for name in _RECONCILIATION_COUNT_FIELDS)
    return f"durable reconciliation: {fields}"

#: D1/D2 (plan rev 6.1): durable, per-venue-order-id marker that a permit
#: slot was restored for it -- written by the CALLER (this client), never by
#: `safety.py`, which stores nothing of its own. Lets a LATER pass that
#: observes a genuine fill for the same id `unrestore` exactly what was
#: given back.
BUDGET_RESTORE_KEY_PREFIX: Final[str] = f"{STATE_KEY_NAMESPACE}budget_restore/"

#: Operator ruling 2026-09-14 ("once it reaches the maximum, it stops
#: trading for the rest of the day"): keyed
#: ``BUDGET_EXHAUSTED_KEY_PREFIX + <UTC YYYY-MM-DD>``, value ``b"1"``.
#: Written here (the exec client) on a typed dollar-ceiling denial and read
#: by ``TrialDayLatch.is_day_budget_exhausted`` under the same flock. Any
#: value at the key means exhausted (fail-closed); the key self-expires at
#: UTC midnight because a new day's key is never written -- no delete is
#: needed.
BUDGET_EXHAUSTED_KEY_PREFIX: Final[str] = f"{STATE_KEY_NAMESPACE}budget_exhausted/"

#: How often `_resolve_ambiguous_intents` checks for a durable resolver
#: context on the currently-OPEN submit intent. Build-side; revisable.
_RESOLVER_POLL_INTERVAL_SECS: Final[float] = 5.0

#: Ceiling on the CONSECUTIVE-failure backoff below -- never wait longer
#: than this between resolver attempts no matter how many failures in a row.
_RESOLVER_BACKOFF_CAP_SECS: Final[float] = 300.0

#: R-9a (HF-4 rev2, B4 supply side): the startup-evidence record is
#: refreshed by `_resolve_ambiguous_intents` itself whenever the watermark
#: (`self._last_evidence_write_ns`) is older than this -- on EVERY pass,
#: including one with no OPEN intent, which is exactly when the strategy's
#: re-arm gate (`_REARM_EVIDENCE_MAX_AGE_NS`, `continuous_strategy.py`) is
#: shopping for fresh evidence. At the 5.0s base poll interval this keeps
#: the record <= ~65s old whenever the resolver loop is healthy, comfortably
#: inside the 180s re-arm ceiling.
_EVIDENCE_REFRESH_AFTER_NS: Final[int] = 60 * 1_000_000_000

#: Age of a durable resolver context's ``created_ns``, past which an intent
#: still AMBIGUOUS raises the one-shot stale-intent alert below.
_STALE_INTENT_ALERT_AFTER_NS: Final[int] = 15 * 60 * 1_000_000_000

#: HIGH review fix (2026-09-24, post-ac691dc): the floor between
#: ``self._resolver_instrument_loader`` re-attempts for the SAME instrument
#: id, whether the last attempt hit or missed. ``ParquetDataCatalog.
#: instruments()`` is a synchronous full-catalog scan -- measured at
#: 1.06-1.36s wall time against the production catalog (13,132 instruments,
#: ``/home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us``,
#: 2026-09-24, ``systemd-run --user --scope -p MemoryMax=4G``), so a MISS
#: must not re-trigger it every ``_RESOLVER_POLL_INTERVAL_SECS`` forever.
#: 15 minutes matches ``_STALE_INTENT_ALERT_AFTER_NS``'s own magnitude: the
#: catalog only grows once per quote-tape recorder rotation cycle (hours),
#: so this is a conservative floor that still catches a catch-up well inside
#: an operator's incident-response window. The consecutive-failure backoff
#: below independently throttles the PASS rate while a miss persists (it
#: saturates at ``_RESOLVER_BACKOFF_CAP_SECS`` well under 15 minutes), so
#: this constant is what actually bounds the scan's own frequency.
_RESOLVER_INSTRUMENT_LOAD_RETRY_NS: Final[int] = 15 * 60 * 1_000_000_000

#: R-7-IMPL (`RULING R-7`, plan `docs/plans/backlog/R-7-IMPL_plan_r1_2026-09-26.md`
#: section 3): the venue `tsEvent` (`fill.ts_event`, sourced from
#: `transactTime`) a create-path accept-fill carries is trusted only inside
#: `[send_ns - bound, recv_ns + bound]` around the POST that produced it --
#: outside that window it is rejected, never substituted with a local clock.
#: Build-side, not operator-reserved. Evidence for the bound: a read-only log
#: grep of the 8 create-path fills observed 2026-09-13 through 2026-09-22 --
#: `transactTime` landed 21-83ms before local receive and 115ms-3.16s after
#: the preceding event, zero overshoot against either side. 2s is <=1.7% of
#: the `_REARM_MIN_DELAY_SECS=120` floor this record exists to verify.
_FILL_TS_EVENT_MAX_SKEW_NS: Final[int] = 2 * 1_000_000_000

#: R-7-IMPL: how long a create-path accept-fill's pending `PositionReportingLag`
#: entry waits for an eof-complete read to confirm the resulting LONG before
#: it is dropped as `UNCONFIRMED_TTL`. Diagnostic only (RULING R-7): an entry
#: that never confirms costs nothing but a bounded amount of process memory.
_POSITION_LAG_PENDING_TTL_NS: Final[int] = 30 * 60 * 1_000_000_000

#: R-7-IMPL: the poison value a SECOND create-path accept-fill on an
#: instrument with an already-pending entry writes over the entry's
#: `client_order_id` slot, instead of overwriting the entry outright.
#: `_match_position_lag` recognises it and drops the entry as
#: `MULTI_FILL_PENDING` -- a `PositionReportingLag` cannot be attributed to
#: one of two fills.
_MULTI_FILL_PENDING_SENTINEL: Final[str] = "R7_MULTI_FILL_PENDING"


class _PendingPositionLag(NamedTuple):
    """One unconfirmed create-path accept-fill, keyed by instrument in
    `_position_lag_pending` (test-gap hardening, 2026-09-26).

    A plain positional 5-tuple let the producer (`_submit_order`) and the
    matcher (`_match_position_lag`) desync silently on field ORDER -- e.g. a
    `send_ns`/`recv_ns` transposition reads clean at each call site and only
    surfaces as a wrong skew/ordering computation. A `NamedTuple` is still a
    tuple (unpacking, equality and indexing against existing test fixtures
    are unaffected), but every producer/matcher access now names the field.
    """

    fill_ts_event: int
    send_ns: int
    recv_ns: int
    client_order_id: str
    reads_without_long: int

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

#: INC-E2: the process-local booking-id sentinel recorded on a resolver
#: context for an exit-side order, which never books against the ledger at
#: all (`:347` budget, §5.8). `_BOOKING_IDS` (`operator_controls.py:157`) is
#: `itertools.count(1)`, so `-1` can never collide with a real booking id.
_NO_BOOKING_ID: Final[int] = -1

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

#: AC6b (EDGE-2 plan r3, D8/D9): a cross-process BUY fill resolved by
#: `_resolve_accept_fill` AFTER this process's own boot spend-seed
#: (`_seed_spend_from_durable_fills`) has already run. `booking is None`
#: means a PRIOR process took the booking this resolver pass is finishing;
#: `self._spend_seeded` means that walk already totalled today's fills
#: before this record existed, so it cannot have counted it -- the daily
#: budget would silently under-count unless this client stops trading until
#: a respawn's fresh seed reads `FILL_BY_DAY_KEY_PREFIX` and books the
#: record. A fill resolved BEFORE the seed ran is exempt (the seed counts
#: it, D8); every exit fill (`context.order_side == "SELL"`) is exempt too
#: (it spends no budget). ONE fixed reason so `_refuse` dedupes on it, the
#: same shape as `_FILL_WRITE_FAILED`/`_VENUE_ID_MAP_WRITE_FAILED` above --
#: no amount, no venue order id, in the reason string itself.
_RESOLVER_FILL_UNBUDGETED: Final[str] = (
    "a cross-process fill was resolved after this process's boot spend seed "
    "already ran; the daily budget cannot account for it until a respawn "
    "reseeds from today's fill index; this client refuses further submits "
    "until then"
)

#: INC-E2c: an exit-tagged order reached this coroutine with no
#: ``exit_manifest`` injected -- fails exactly like ``PERMIT_ABSENT_REASON``
#: (a missing collaborator denies, it never crashes the coroutine by calling
#: ``submit_chain.unmappable_exit_order_reason`` with ``manifest=None``).
_EXIT_MANIFEST_ABSENT_REASON: Final[str] = (
    "no exit family manifest is injected; this client refuses to submit an exit"
)

#: The four ``Order.tags`` prefixes an exit order carries (module docstring
#: of ``persistence/exit_tags.py``), and their lengths precomputed at import
#: time. ``_submit_order`` is E0-NOSEND-scanned (every ``ast.Call`` in its
#: body must be on ``EXEC_ORDER_COROUTINE_PERMITTED_CALLEES`` --
#: ``test_execution_egress_firewall_guard.py``), so tag matching there uses
#: slicing and ``==`` (neither is a call) against these precomputed lengths
#: rather than ``str.startswith(...)`` -- a call the cage would need a new
#: entry for, for a pure string comparison that does not need one.
_EXIT_RULE_TAG_PREFIX_LEN: Final[int] = len(EXIT_RULE_TAG_PREFIX)
_EXIT_POSITION_TAG_PREFIX_LEN: Final[int] = len(EXIT_POSITION_TAG_PREFIX)
_EXIT_FAMILY_TAG_PREFIX_LEN: Final[int] = len(EXIT_FAMILY_TAG_PREFIX)
_EXIT_CLIENT_ORDER_ID_TAG_PREFIX_LEN: Final[int] = len(EXIT_CLIENT_ORDER_ID_TAG_PREFIX)


@dataclass(frozen=True, slots=True)
class _AdapterExitAuthorization:
    """Adapter-side view satisfying ``submit_chain.ExitAuthorizationLike``
    structurally, reconstructed from the order's own tags and fields --
    never imported from ``strategy/`` (the importlinter layer contract:
    ``adapters`` sits below ``strategy``, module docstring of
    ``exec/submit_chain.py``'s ``ExitAuthorizationLike``).

    ``leg`` and ``limit_price`` are derived from the SAME order/instrument
    ``submit_chain``'s own cross-checks compare them against
    (``leg_of(instrument.id)``, ``order_price_decimal(order)``), so those
    two checks are necessarily tautological for THIS caller -- there is no
    second, independent source of truth at the exec-client boundary; only
    ``family_id`` (read from the ``exit_family_id=`` tag, independent of the
    order's own fields) exercises a genuine cross-check, against
    ``manifest.family_id``. ``quantity`` is pinned to the domain invariant
    (every exit is exactly 1 contract, ``ExitAuthorization.__post_init__``)
    rather than converted from the order via a new ``int(...)`` call, which
    the E0-NOSEND cage would need a new entry for.
    """

    family_id: str
    position_id: str
    client_order_id: str
    leg: Leg
    quantity: int
    limit_price: Decimal


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

    **EDGE-2 slice D (AC10, ruling b): ``query`` is an optional mapping,
    rendered EXACTLY ONCE and signed AND sent as that one string** -- never
    two independent renderings that could drift apart (the classic Ed25519
    integration failure; see ``http.py``'s module docstring). ``query=None``
    (every call site this protocol had before slice D) must remain
    byte-identical to the bare-path signature: an implementation MUST NOT
    append a query string when ``query`` is empty or absent.
    """

    async def __call__(
        self, path: str, query: Mapping[str, object] | None = None
    ) -> Mapping[str, Any]: ...


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


#: AUD-13b (ruling R-1 = O4): the two values a record's ``feeSource`` may
#: take. ``RECORDED`` is the venue's own attested fee; anything else is a
#: model output FOR THAT FILL'S ERA (theta as of ``ts_event``).
FEE_SOURCE_RECORDED: Final[str] = "RECORDED"
FEE_SOURCE_MODELLED_AT_FILL_TIME: Final[str] = "MODELLED_AT_FILL_TIME"
_FEE_SOURCES: Final[frozenset[str]] = frozenset(
    {FEE_SOURCE_RECORDED, FEE_SOURCE_MODELLED_AT_FILL_TIME}
)


def fee_source_for(*, fee_reconciled: bool, venue_fee_raw: str | None) -> str:
    """The O4 rule, in one place: ``RECORDED`` iff the fee reconciled AND the
    venue's raw fee is present -- ``fee_reconciled`` alone is not an
    attestation. Both write sites stamp this, and reconciliation re-derives
    it rather than trusting a stored value."""
    if fee_reconciled and venue_fee_raw is not None:
        return FEE_SOURCE_RECORDED
    return FEE_SOURCE_MODELLED_AT_FILL_TIME


def _optional_fee_coefficient_at_fill(raw: object) -> Decimal | None:
    """``feeCoefficientAtFill`` is optional-on-read (``None`` on every record
    written before AUD-13b); a present value must be a finite theta in
    ``[0, 1]``, exactly the range ``fees._fee_coefficient`` accepts."""
    if raw is None:
        return None
    theta = _to_decimal(raw, field="feeCoefficientAtFill", error=ExecutionReportMappingError)
    if theta < 0 or theta > 1:
        raise ExecutionReportMappingError(
            f"a durable fill record is malformed: feeCoefficientAtFill {theta} "
            "is outside [0, 1]"
        )
    return theta


def _optional_fee_source(raw: object) -> str | None:
    """``feeSource`` is optional-on-read; a present value must be one of the
    two ruled members, never a near-miss spelling."""
    if raw is None:
        return None
    if not isinstance(raw, str) or raw not in _FEE_SOURCES:
        raise ExecutionReportMappingError(
            f"a durable fill record is malformed: feeSource must be one of "
            f"{sorted(_FEE_SOURCES)} or null, got {raw!r}"
        )
    return raw


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
    #: AUD-13b / ruling R-1 = O4 mechanism (a): the taker theta of the
    #: ``Instrument`` in hand when the record was written. ``None`` on a legacy
    #: record (priced from the dated schedule instead) or when that
    #: instrument's schedule was unusable. On a RESOLVER record it is the theta
    #: at DISCOVERY time, the same upper-bound caveat as its ``ts_event``.
    fee_coefficient_at_fill: Decimal | None = None
    #: AUD-13b: :func:`fee_source_for` as stamped at write time. Diagnostic
    #: provenance only -- reconciliation re-derives it, never trusts it.
    fee_source: str | None = None

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
                "feeCoefficientAtFill": (
                    None
                    if self.fee_coefficient_at_fill is None
                    else str(self.fee_coefficient_at_fill)
                ),
                "feeSource": self.fee_source,
            },
            sort_keys=True,
        ).encode("utf-8")

    @classmethod
    def from_bytes(cls, raw: bytes) -> Self:
        """Decode a record, refusing anything that is not exactly one.

        Every field is required except ``venueFeeRaw``, ``tradeId``,
        ``orderQty``, ``feeCoefficientAtFill`` and ``feeSource``, which are
        optional-on-read so pre-GL-2/pre-B0/pre-AUD-13b records still decode
        (``None``). A present non-string ``venueFeeRaw``/
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
                fee_coefficient_at_fill=_optional_fee_coefficient_at_fill(
                    payload.get("feeCoefficientAtFill")
                ),
                fee_source=_optional_fee_source(payload.get("feeSource")),
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ExecutionReportMappingError(
                f"a durable fill record is malformed: {type(exc).__name__}: {exc}"
            ) from None


@dataclass(frozen=True, slots=True)
class _ReconciliationPass:
    """AUD-13b: one ``generate_mass_status`` pass's memoised positions read.

    ``error`` is the read's exception (re-raised into
    ``generate_position_status_reports``' own unchanged refusal path);
    otherwise ``position_reports`` is the mapped book, computed ONCE, and the
    two report lists are the durable reports gated on it.
    """

    error: Exception | None
    position_reports: tuple[PositionStatusReport, ...]
    order_reports: tuple[OrderStatusReport, ...]
    fill_reports: tuple[FillReport, ...]


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
    #: INC-E2 (POSITION_EXIT_EXECUTION_2026-09-16 fill accounting): the
    #: order's REAL Nautilus side name (``"BUY"``/``"SELL"``), so a resolver
    #: GET-fill books the same side the create-time order actually carried
    #: instead of the entry-only ``LONG_ONLY_SIDE`` hardcode. Trailing-
    #: optional, same AR-N6 shape as the two fields above: an OLD blob
    #: (written before this change, when every order this client ever built
    #: was a BUY) has no key at all and decodes to ``LONG_ONLY_SIDE`` --
    #: exactly what it always was.
    order_side: str = LONG_ONLY_SIDE
    #: EDGE-2 slice A (AC3): the closed-set ``submit_chain.create_fill_
    #: evidence(...).token`` for this with-id AMBIGUOUS create response.
    #: Same AR-N6 trailing-optional shape as the three fields above: an OLD
    #: blob (written before this change) has no ``createFillEvidence`` key,
    #: and absence decodes to ``submit_chain.CREATE_FILL_EVIDENCE_UNKNOWN``
    #: -- the same token an unparseable body itself renders, since neither
    #: case tells the resolver anything about create-time fill evidence.
    create_fill_evidence: str = submit_chain.CREATE_FILL_EVIDENCE_UNKNOWN
    #: FAILURE-KIND-DURABLE (2026-09-28): the last resolver failure kind
    #: classified for this intent, mirrored durably here so a restart does
    #: not lose it -- ``_resolver_last_failure_kind`` (this client's own
    #: field, seeded from this value on the first pass after a restart) is
    #: process-local memory only and dies with the process. Same AR-N6
    #: trailing-optional shape as the fields above: an OLD blob (written
    #: before this change) has no ``lastFailureKind`` key at all, and
    #: absence decodes to ``"none"`` -- exactly what an untouched intent's
    #: kind always was.
    last_failure_kind: str = "none"
    #: AMBIG-LATCH-RESUME (no-id resolver, plan r6 section 2.8.3): the exact wire
    #: fields the venue echoes on its own order objects. A no-id submit has no
    #: venue order id, so these (written BEFORE the POST) are the attribution
    #: join key. Same AR-N6 trailing-optional shape: an OLD blob has no keys and
    #: decodes ``None`` (the resolver then uses window-only rules).
    wire_market_slug: str | None = None
    wire_price: str | None = None
    wire_outcome_side: str | None = None
    wire_action: str | None = None
    #: The pre-POST holding snapshot (DM4): the slug's signed venue net, this
    #: instrument's durable net, and the evidence time they were read at. All
    #: three are ``None`` together (no baseline: the absolute rule applies).
    baseline_venue_net: str | None = None
    baseline_durable_net: str | None = None
    baseline_ts_ns: int | None = None

    @property
    def no_id_echo(self) -> NoIdEcho | None:
        """The wire echo a no-id attribution joins on, or ``None`` (an old blob
        written before these fields existed: the resolver then uses the
        window-only rules). A property, so the scanned resolver bodies build no
        object (no new callee)."""
        if (
            self.wire_market_slug is None
            or self.wire_price is None
            or self.wire_outcome_side is None
            or self.wire_action is None
        ):
            return None
        return NoIdEcho(
            slug=self.wire_market_slug,
            outcome_side=self.wire_outcome_side,
            action=self.wire_action,
            price=self.wire_price,
        )

    def to_bytes(self) -> bytes:
        return json.dumps(
            {
                "wireMarketSlug": self.wire_market_slug,
                "wirePrice": self.wire_price,
                "wireOutcomeSide": self.wire_outcome_side,
                "wireAction": self.wire_action,
                "baselineVenueNet": self.baseline_venue_net,
                "baselineDurableNet": self.baseline_durable_net,
                "baselineTsNs": self.baseline_ts_ns,
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
                "orderSide": self.order_side,
                "createFillEvidence": self.create_fill_evidence,
                "lastFailureKind": self.last_failure_kind,
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
        # INC-E2: same trailing-optional shape -- an old blob has no
        # `orderSide` key at all (every order it could ever have named was a
        # BUY), so absence decodes to `LONG_ONLY_SIDE`, never `None`.
        raw_order_side = payload.get("orderSide")
        order_side = LONG_ONLY_SIDE if raw_order_side is None else str(raw_order_side)
        # EDGE-2 slice A (AC3): same trailing-optional shape -- an old blob
        # has no `createFillEvidence` key at all (written before this
        # change), so absence decodes to
        # `submit_chain.CREATE_FILL_EVIDENCE_UNKNOWN`.
        raw_create_fill_evidence = payload.get("createFillEvidence")
        create_fill_evidence = (
            submit_chain.CREATE_FILL_EVIDENCE_UNKNOWN
            if raw_create_fill_evidence is None
            else str(raw_create_fill_evidence)
        )
        # FAILURE-KIND-DURABLE: same trailing-optional shape -- an old blob
        # has no `lastFailureKind` key at all (written before this change),
        # so absence decodes to `"none"`, exactly what an untouched intent's
        # kind always was.
        raw_last_failure_kind = payload.get("lastFailureKind")
        last_failure_kind = "none" if raw_last_failure_kind is None else str(raw_last_failure_kind)
        # AMBIG-LATCH-RESUME: same trailing-optional shape for the wire echo
        # fields and the pre-POST holding baseline.
        def _optional_text(key: str) -> str | None:
            value = payload.get(key)
            return None if value is None else str(value)

        raw_baseline_ts = payload.get("baselineTsNs")
        try:
            baseline_ts_ns = None if raw_baseline_ts is None else int(raw_baseline_ts)
        except (TypeError, ValueError):
            baseline_ts_ns = None
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
                order_side=order_side,
                create_fill_evidence=create_fill_evidence,
                last_failure_kind=last_failure_kind,
                wire_market_slug=_optional_text("wireMarketSlug"),
                wire_price=_optional_text("wirePrice"),
                wire_outcome_side=_optional_text("wireOutcomeSide"),
                wire_action=_optional_text("wireAction"),
                baseline_venue_net=_optional_text("baselineVenueNet"),
                baseline_durable_net=_optional_text("baselineDurableNet"),
                baseline_ts_ns=baseline_ts_ns,
            )
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise ExecutionReportMappingError(
                f"a durable resolver context is malformed: {type(exc).__name__}: {exc}"
            ) from None


@dataclass(frozen=True, slots=True)
class HoldingBaseline:
    """The pre-POST holding snapshot a no-id submit is later checked against:
    the slug's signed venue net, this instrument's durable net (both as the
    strings the context stores) and the evidence time they were read at."""

    venue_net: str
    durable_net: str
    ts_ns: int


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
class StartupOpenOrderSnapshot:
    """One enumerated open order, as the never-arm gate needs it: enough to
    name the order in a refusal (id, market, state) and nothing that would
    put a price or size into a durable row the gate never reads."""

    venue_order_id: str
    market_slug: str
    state: str


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
    #: RESTING_BID_HUNT Rev 2 section 4.3: the open-order enumeration. The
    #: gate arms only if the read SUCCEEDED (``open_orders_read_refused`` is
    #: ``False``) AND ``open_orders`` is EMPTY. A record written before these
    #: fields existed decodes as REFUSED (see ``from_bytes``): unrecorded is
    #: UNKNOWN, never "none open".
    open_orders_read_refused: bool = True
    open_orders: tuple[StartupOpenOrderSnapshot, ...] = ()

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
                "open_orders_read_refused": self.open_orders_read_refused,
                "open_orders": [
                    {
                        "venue_order_id": o.venue_order_id,
                        "market_slug": o.market_slug,
                        "state": o.state,
                    }
                    for o in self.open_orders
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
            # Pre-section-4.3 records carry neither key: decode as REFUSED
            # rather than raise -- the boot rewrites this row at the end of
            # `_connect`, and nothing reading the old bytes may mistake
            # "unrecorded" for "none open".
            if "open_orders_read_refused" in payload and "open_orders" in payload:
                open_orders_read_refused = _require_bool(
                    payload["open_orders_read_refused"], field="open_orders_read_refused"
                )
                raw_open_orders = payload["open_orders"]
                if not isinstance(raw_open_orders, list):
                    raise ExecutionReportMappingError(
                        "startup position evidence 'open_orders' is not a list"
                    )
                open_orders = tuple(
                    StartupOpenOrderSnapshot(
                        venue_order_id=str(entry["venue_order_id"]),
                        market_slug=str(entry["market_slug"]),
                        state=str(entry["state"]),
                    )
                    for entry in raw_open_orders
                )
            else:
                open_orders_read_refused = True
                open_orders = ()
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
                open_orders_read_refused=open_orders_read_refused,
                open_orders=open_orders,
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
#:
#: Derived from ``reports.NON_FILL_TERMINAL_STATUSES`` (this module already
#: imports from ``reports`` above) rather than hand-copied: ``reports.py`` is
#: the lower layer here -- it does not, and must not, import FROM
#: ``client.py`` -- so this module is the one that reuses the other's
#: constant, never the reverse. A second hand-written copy of the same three
#: statuses previously drifted from ``reports._assert_fill_progress_consistent``'s
#: own terminal check; this alias makes that impossible.
_RESOLVER_TERMINAL_STATUSES: Final[frozenset[OrderStatus]] = NON_FILL_TERMINAL_STATUSES
#: A GET-resolved report carrying a COMPLETE fill. ``PARTIALLY_FILLED`` is
#: deliberately EXCLUDED: it is a LIVE state -- the order can still receive
#: more fills or reach a terminal status later -- and must NEVER resolve the
#: intent. Only a genuinely terminal status ends it: ``FILLED`` here, or one
#: of ``_RESOLVER_TERMINAL_STATUSES`` with ``filled_qty > 0`` (the
#: terminal-fill case above).
_RESOLVER_FILL_STATUSES: Final[frozenset[OrderStatus]] = frozenset({OrderStatus.FILLED})


def _resolver_long_position_state(
    positions: Mapping[str, Any], slug: str, leg: Leg
) -> bool | None:
    """Resolution C/EDGE-2C: ``True`` -- a LONG on ``leg`` is present at
    ``slug`` (``leg`` KEEPS its name: per the 2026-09-16 ruling a NO holding
    IS a LONG on the NO-leg instrument, never a SHORT on the YES one).
    ``False`` -- confirmed no LONG on ``leg`` (the slug is absent, which IS a
    confirmed zero position, or the sign/outcome present belongs to the
    OTHER leg). ``None`` -- undetermined (malformed ``netPosition``, or an
    outcome/sign contradiction :func:`position_leg` refuses to guess); the
    caller MUST treat this exactly like a read failure: take no action, stay
    AMBIGUOUS, try again next pass. Never ``_refuse``s.
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
    if net == 0:
        return False
    metadata = payload.get("marketMetadata")
    metadata = metadata if isinstance(metadata, Mapping) else None
    try:
        held_leg = position_leg(
            net=net, metadata=metadata, context=f"resolver positions[{slug!r}]"
        )
    except ExecutionReportMappingError:
        return None
    return held_leg == leg


def _resolver_leg_holding_qty(
    positions: Mapping[str, Any], slug: str, leg: Leg
) -> Decimal | None:
    """EDGE-2 slice D (AC4(e)): the ABSOLUTE venue-reported holding on
    ``leg`` at ``slug``, from the SAME eof-complete positions page
    :func:`_resolver_long_position_state` reads -- its magnitude-aware
    sibling.

    ``Decimal(0)`` -- confirmed no holding on ``leg`` (the slug is absent,
    net is zero, or the holding present belongs to the OTHER leg -- mirrors
    :func:`_resolver_long_position_state`'s own ``held_leg == leg``
    comparison). ``None`` -- undetermined (malformed ``netPosition``, or a
    sign/outcome contradiction :func:`position_leg` refuses to guess); the
    caller MUST treat this exactly like a read failure: stay AMBIGUOUS,
    never retire on evidence it could not actually read.

    A prior same-day fill on this SAME instrument can leave a genuine LONG
    on ``leg`` even though THIS order never filled (AC4(e)'s whole reason
    for existing) -- the caller compares this magnitude against
    :meth:`PolymarketUSExecutionClient._durable_net_qty`'s own baseline
    rather than treating any holding at all as proof of a fill.
    """
    payload = positions.get(slug)
    if payload is None:
        return Decimal(0)
    if not isinstance(payload, Mapping):
        return None
    net_raw = payload.get("netPosition")
    if net_raw is None:
        return None
    try:
        net = _to_decimal(net_raw, field="netPosition", error=ExecutionReportMappingError)
    except ExecutionReportMappingError:
        return None
    if net == 0:
        return Decimal(0)
    metadata = payload.get("marketMetadata")
    metadata = metadata if isinstance(metadata, Mapping) else None
    try:
        held_leg = position_leg(
            net=net, metadata=metadata, context=f"resolver positions[{slug!r}]"
        )
    except ExecutionReportMappingError:
        return None
    if held_leg != leg:
        return Decimal(0)
    return abs(net)


#: EDGE-2 slice D (AC4(c)): the page cap for one resolver trade-activity
#: join -- the SAME cap Step 0 used (plan section 6, Q2 row). The account's
#: entire recorded history was 35 rows on 2026-09-27 (one page); 20 pages of
#: 100 rows each is ample headroom while still bounding worst-case portfolio-
#: quota pressure to a fixed number of GETs per resolver pass.
_RESOLVER_ACTIVITY_MAX_PAGES: Final[int] = 20
_RESOLVER_ACTIVITY_PAGE_LIMIT: Final[int] = 100
_RESOLVER_ACTIVITY_SORT_ORDER: Final[str] = "SORT_ORDER_DESCENDING"

#: AC4(d): a borrowed, UNVERIFIED defence-in-depth floor -- pinned EQUAL to
#: the strategy's own `_REARM_MIN_DELAY_SECS`
#: (`domain/position_reporting_lag.py:32`) by test
#: (`test_min_age_constant_equals_strategy_rearm_floor`), never imported
#: from `strategy` here: `adapters` sits BELOW `strategy` in the
#: import-linter layer contract, so this module names the same number
#: independently rather than importing it.
_RESOLVER_ZERO_FILL_MIN_AGE_NS: Final[int] = 120 * 1_000_000_000

#: AMBIG-LATCH-RESUME (no-id resolver, plan r6 section 2.8.4): the earliest age
#: at which the no-id branch may read the venue. The venue's acceptance
#: deadline is about ``created + 30 s`` plus a <= 30 s clock offset plus the
#: 5 s ``maxBlockTime``, which fixes the order's fate by about ``created +
#: 65 s``; the rest is eventual-consistency margin for the activities and
#: positions feeds (about 2x the with-id 120 s floor that gates the same read).
_RESOLVER_NO_ID_MIN_AGE_NS: Final[int] = 300 * 1_000_000_000
#: P-c: 30 s venue timestamp tolerance + 30 s clock offset + 5 s maxBlockTime.
_NO_ID_FATE_FIXED_NS: Final[int] = 65 * 1_000_000_000
#: A CHOICE, not a derivation: chosen only so the forward bound equals the
#: back-skew (a window symmetric about ``created_ns``). It has to absorb the
#: sign-to-POST gap, venue queueing (no documented bound) and ``createTime``
#: granularity; the measured total is 0.075-0.215 s (n = 9).
_NO_ID_WINDOW_FORWARD_SKEW_NS: Final[int] = 55 * 1_000_000_000
_NO_ID_WINDOW_FORWARD_NS: Final[int] = _NO_ID_FATE_FIXED_NS + _NO_ID_WINDOW_FORWARD_SKEW_NS
#: 4x the venue's 30 s timestamp window, so a skewed ``createTime`` cannot fall
#: before the attribution window.
_NO_ID_WINDOW_BACKSKEW_NS: Final[int] = 120 * 1_000_000_000
#: A pre-POST holding snapshot is only a baseline if no Breezy fill on the
#: instrument landed within this long before it (it might not reflect it yet).
_NO_ID_BASELINE_QUIET_NS: Final[int] = 300 * 1_000_000_000
#: The native reject reason for a no-id submit that complete venue reads show
#: neither an order nor a fill for (the name says what is proven).
_NO_ID_NO_FILL_REASON: Final[str] = (
    "resolver: complete venue reads show no order and no fill for this no-id submit"
)
#: After a CONTRADICTION or INCOMPLETE verdict the no-id branch makes no
#: further reads for that intent until this long has passed.
_NO_ID_RECHECK_INTERVAL_NS: Final[int] = 60 * 1_000_000_000
#: A manual trade this close to the baseline snapshot may or may not be in it
#: (the venue's 30 s timestamp tolerance), so it cannot be reconciled.
_NO_ID_MANUAL_STRADDLE_NS: Final[int] = 30 * 1_000_000_000

#: AC4(b): the two `createFillEvidence` tokens that BLOCK a resolver
#: zero-fill and raise `resolver_evidence_contradiction` if the GET still
#: reports terminal zero. `none` and `unknown` (legacy) are both admissible
#: on their own and never appear here -- neither short-circuits: AC4(c)/(d)/
#: (e) still gate every zero-fill regardless of which of those two applies.
_CREATE_FILL_EVIDENCE_BLOCKS_ZERO_FILL: Final[frozenset[str]] = frozenset(
    {
        submit_chain.CREATE_FILL_EVIDENCE_FILL_TYPE_PRESENT,
        submit_chain.CREATE_FILL_EVIDENCE_FILL_TYPE_UNMAPPABLE,
    }
)


@dataclass(frozen=True, slots=True)
class TradeJoin:
    """EDGE-2 slice D (AC4(c)): the outcome of paging
    ``/v1/portfolio/activities`` for ``ACTIVITY_TYPE_TRADE`` rows naming one
    venue order id.

    **``complete`` is EOF-ONLY** (binding coordinator amendment,
    2026-09-27, from the Step 0 evidence and its review -- see
    ``docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-23_MIA/
    README.md``, "Scope note"). Step 0 found the account's entire 35-row
    history fit on ONE page (``eof=true``) on every traversal, so the plan's
    ``min(createTime) < createdNs`` completeness branch was never exercised
    against the real venue and stays UNLICENSED (follow-up
    ``EDGE-2-MULTIPAGE``) until a real multi-page traversal is observed and
    Q2s is re-verified across a page boundary. A read that hits
    :data:`_RESOLVER_ACTIVITY_MAX_PAGES` before ``eof`` is therefore
    INCOMPLETE, never guessed complete from the running minimum createTime
    -- which :func:`PolymarketUSExecutionClient._order_trade_activity`
    still computes and logs (``page_min_create_ts_ns``), for observability
    only, never as a completeness signal.

    **EDGE-2-MULTIPAGE step 1 (2026-09-27): a malformed page also stops the
    read INCOMPLETE, never guessed complete.** Two defects (D1/D2) could
    previously make a read look complete when it was not: ``bool(page.get(
    "eof"))`` treated any truthy non-bool ``eof`` (``"false"``, ``1``, ...)
    as EOF (D1), and a page whose ``activities`` field was missing or not a
    list silently contributed zero rows while the loop carried on to a
    later ``eof`` (D2). Both are now refused: any page with a non-list
    ``activities`` or a present, non-bool ``eof`` stops the read the same
    way a page-cap hit does -- ``complete=False``, with whatever trades were
    already found on EARLIER pages still counted (a trade found before the
    malformed page must still raise a contradiction, never be discarded).
    The pagination boundary itself (D3, whether a cursor can skip or
    reorder rows) stays UNLICENSED until the Step 2 probe runs.

    **TRADE-ROW-DRIFT (2026-09-27): ``uninterpretable_rows`` mirrors the
    malformed-page shape above, one level down.** A TRADE row this join
    cannot read with confidence (``account_activity.TradeRowScan``) stops
    the read the same way a malformed PAGE does -- ``complete=False``, with
    trades already found (this page and earlier) still counted, never
    discarded.
    """

    complete: bool
    trade_count: int
    qty: Decimal
    last_trade_ts_ns: int | None
    uninterpretable_rows: int = 0


@dataclass(frozen=True, slots=True)
class NoIdTradeJoin:
    """The outcome of scanning ``/v1/portfolio/activities`` for every AGGRESSOR
    leg at or after a no-id submit's attribution window start (plan r6
    section 2.8.6).

    ``complete`` is True on ``eof`` OR on ORDERED early termination: the first
    page whose TRADE rows pass below the window start without any ordering
    violation. With non-increasing order among TRADE rows (checked on every row
    actually read, never assumed), every later TRADE row is also older, so it
    can hold no attributable leg. ``out_of_order`` stops the read incomplete.
    """

    complete: bool
    out_of_order: bool
    legs: tuple[NoIdLeg, ...]
    passive_manual: tuple[bool, ...]
    uninterpretable_rows: int
    pages: int


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
        exit_manifest: FamilyManifest | None = None,
        resolver_instrument_loader: Callable[[str], Any] | None = None,
        no_id_retire_admitted: bool = False,
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
        # AMBIG-LATCH-RESUME: how many AMBIGUOUS refusals a resolver clear has
        # removed (F6), the intent whose create POST is awaited in THIS
        # process, the per-intent "complete negative pass seen" stamp, and the
        # per-intent next no-id re-check time.
        self._ambiguous_refusal_clears: int = 0
        self._post_in_flight_intent_id: str | None = None
        self._resolved_no_id_ts_ns: dict[str, int] = {}
        self._no_id_next_check_ns: dict[str, int] = {}
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
        # AMBIG-LATCH-RESUME (DH1): whether the running supervisor can decode the
        # `RESOLVER_NO_ID_NO_FILL` retirement reason. Set once at node boot;
        # `_resolve_no_order` refuses to retire without it (fail closed).
        self._no_id_retire_admitted: bool = bool(no_id_retire_admitted)
        # Item 4 (slice 4 review): the family-halt chokepoint veto, injected
        # exactly the way the submit-intent latch is -- a plain callable this
        # adapters-layer module never imports the type of. `None` -> no veto,
        # matching every composition root that predates this parameter.
        self._submit_veto = submit_veto
        # INC-E2c: the registered exit family's manifest, injected exactly
        # like `submit_veto`/`submit_intent_latch` above -- `None` (the
        # default, matching every composition root that predates this
        # parameter) denies every exit-tagged order with
        # `_EXIT_MANIFEST_ABSENT_REASON` rather than dereferencing `None`
        # inside `submit_chain.unmappable_exit_order_reason`.
        self._exit_manifest = exit_manifest
        # 2026-09-24 stuck-prior-day-instrument fix: injected exactly like
        # `submit_veto`/`exit_manifest` above -- a plain callable this
        # adapters-layer module needs no `runtime` import to type. Given a
        # venue instrument id string, returns the native `Instrument`
        # definition if one can be obtained WITHOUT subscribing to market
        # data (composition's `ParquetDataCatalog.instruments()` historical
        # read is the intended source -- see `node_config.py`), or `None`
        # if it cannot. `None` (the default) matches every composition root
        # that predates this parameter: the resolver then escalates instead
        # of loading, exactly as it always has.
        self._resolver_instrument_loader = resolver_instrument_loader
        # Same field, dedup set: an instrument the loader could not produce
        # is escalated at ERROR exactly ONCE per instrument id, never every
        # ~5s poll for the process lifetime -- the same one-shot shape
        # `_resolver_stale_alerted_intent_ids` already uses below.
        self._resolver_missing_instrument_logged: set[str] = set()
        # HIGH review fix (2026-09-24, post-ac691dc): the LAST timestamp the
        # loader was attempted for an instrument id, whether it hit or
        # missed. Gates re-attempts to `_RESOLVER_INSTRUMENT_LOAD_RETRY_NS`
        # apart -- see that constant's docstring for the measured cost this
        # guards against.
        self._resolver_instrument_load_attempted_ns: dict[str, int] = {}
        self._intent_reconciled: bool = False
        # AC6b (EDGE-2 plan r3, D8): set `True` immediately after
        # `_seed_spend_from_durable_fills()` returns in `_connect`, with no
        # `await` between -- so every resolver-path fill this process ever
        # records is exactly one of two things: visible to the seed (this
        # flag still `False`), or refused as unbudgeted (this flag already
        # `True`). Never reset: the seed itself is idempotent per process
        # (`DailySpendLedger._seeded`, `_SEEDED_PERMIT_BUDGETS`), so a fill
        # found after a SECOND `_connect()` in the same process must still
        # refuse -- the seed will not re-walk it.
        self._spend_seeded: bool = False
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
        #: Operator ruling 2026-09-14: the ``budget stop`` line is logged
        #: ONCE per process per UTC day, not on every subsequent denial for
        #: the same exhausted day.
        self._budget_marker_written: set[str] = set()
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
        # FAILURE-KIND-PERSIST (r2/r3): `_resolver_stale_alert_details` now
        # holds up to TWO entries per intent id -- `id` (the first stale
        # sighting, set above) and `f"{id}:cause"` (a follow-up written only
        # once, only when a real cause is later identified; see the block
        # after the stale check below). Still mutated ONLY by whole-value
        # reassignment, for the same E0-NOSEND-RESOLVER reason.
        self._resolver_stale_alert_details: dict[str, Mapping[str, str]] = {}
        # EDGE-2 slice D (AC4): the health-surface bookkeeping for a
        # `resolver_evidence_contradiction` CRITICAL -- same shape and same
        # whole-value-reassignment discipline as the stale-intent pair
        # immediately above; `_retire` drops the entry on retirement (a
        # contradiction always leaves the intent OPEN, so only an operator
        # clearing path or a later consistent pass reaches `_retire` at all).
        self._resolver_contradiction_details: dict[str, Mapping[str, str]] = {}
        #: R-9a (HF-4 rev2, B4 supply side): the wall-clock timestamp of the
        #: MOST RECENT startup-evidence write -- the single writer is
        #: `_write_startup_position_evidence` (assigned at its own end), so
        #: a terminal-zero resolution's own evidence rewrite resets this
        #: too and no redundant GET follows a resolution. `0` before the
        #: first write makes the very first resolver pass refresh
        #: unconditionally (age is always >= the threshold against `0`).
        self._last_evidence_write_ns: int = 0
        # RESTING_BID_HUNT Rev 2 section 4.3: the LAST open-order enumeration,
        # carried into every `_write_startup_position_evidence` row --
        # including the synchronous `_resolve_terminal_zero` rewrite, which
        # cannot GET. REFUSED until the first read succeeds: fail closed.
        self._open_orders_read_refused: bool = True
        self._open_orders: tuple[OpenOrderRecord, ...] = ()
        # AUD-13b: the durable-record reconciliation's observable state.
        # Latched refusals persist for the process (deduped by latch+subject);
        # counts and fee sources describe the LAST pass only.
        self._reconciliation_refusal_latches: dict[tuple[str, str], Mapping[str, str]] = {}
        self._reconciliation_counts: Mapping[str, int] = dict.fromkeys(
            _RECONCILIATION_COUNT_FIELDS, 0
        )
        self._reconciled_fee_sources: Mapping[str, str] = {}
        # One memoised positions read (and its durable reports) per
        # `generate_mass_status` pass; `None` outside a pass.
        self._reconciliation_pass: _ReconciliationPass | None = None
        # FU-8 r2/r2.1: set True as the FIRST statement of
        # `generate_mass_status` (boot-only -- see that method's own
        # docstring and `test_the_settlement_landmine_stays_disarmed_only_
        # while_the_position_check_is_off`, which pins that no periodic
        # native reconciliation is ever enabled). Never reset -- a later
        # cache-miss fill after a reconnect still latches, the conservative
        # direction (plan r2 "Reconnect" edge case).
        self._boot_snapshot_started: bool = False
        # Set by `_map_position` at each return, read by the durable pass to
        # tell an unparseable row (fails the whole read) from a settled one.
        self._position_map_outcome: str = ""
        # R-7-IMPL (RULING R-7): `(fill_ts_event, send_ns, recv_ns,
        # client_order_id, reads_without_long)`, keyed by instrument -- one
        # entry per unconfirmed create-path accept-fill. Populated ONLY by
        # `_submit_order`'s accept-fill branch (never the resolver's);
        # matched and popped by `_match_position_lag`, called from
        # `_write_startup_position_evidence`. In memory only, lost on
        # restart -- an unconfirmed entry costs nothing but bounded memory.
        self._position_lag_pending: Mapping[InstrumentId, tuple[int, int, int, str, int]] = {}
        # R-7-IMPL: instruments `_match_position_lag` confirmed LONG as of
        # its LAST pass that actually read this instrument's position --
        # used to reject a SECOND pending fill's confirmation as
        # `PRIOR_LONG` (ambiguous attribution) instead of double-counting an
        # already-open LONG.
        self._position_lag_last_long: frozenset[InstrumentId] = frozenset()

    # -- observable state ---------------------------------------------------

    @property
    def reconciliation_refusals(self) -> tuple[Mapping[str, str], ...]:
        """AUD-13b: every latched durable-reconciliation refusal.

        **Read-only surface, deliberately -- not an emitted alert**, exactly
        like :attr:`stale_ambiguous_intent_alerts`: this module may not import
        ``breezy.runtime.health`` (barrier E0-TRANSPORT). Each entry is the
        WARN payload the runtime layer delivers: ``event`` is
        :data:`RECONCILIATION_REFUSAL_EVENT`, ``detail`` a fixed enum member
        per latch, ``latch`` the reason code, ``subject`` the instrument id
        (disagreement), the REDACTED venue order id (fee ambiguity) or ``""``
        (read failure).
        """
        return tuple(self._reconciliation_refusal_latches.values())

    @property
    def reconciliation_counts(self) -> Mapping[str, int]:
        """AUD-13b: the last durable pass's counts line, as numbers."""
        return dict(self._reconciliation_counts)

    @property
    def reconciled_fee_sources(self) -> Mapping[str, str]:
        """AUD-13b: ``venue_order_id -> feeSource`` for every fill report the
        last durable pass emitted (ruling R-1 = O4 provenance)."""
        return dict(self._reconciled_fee_sources)

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
    def ambiguous_refusal_clears(self) -> int:
        """How many AMBIGUOUS trading refusals a resolver retirement has
        cleared (F6). Read by the degraded alert so an episode added and
        cleared between two re-poll ticks is still counted."""
        return self._ambiguous_refusal_clears

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
            # FU-5 (2026-09-26 boot-overlap fix): the periodic resolver task
            # is now started in the `finally` below, AFTER `_wait_for_
            # instruments` and the immediate pass have both been awaited --
            # never before. Starting it here, unconditionally, let a slow
            # boot's periodic FIRST pass overlap the immediate pass's own
            # in-flight `run_in_executor` instrument load: the periodic pass
            # would see `_resolver_instrument_load_attempted_ns` just set by
            # the immediate pass, skip its own load under that gate, and
            # falsely log/escalate "not in the cache and could not be
            # loaded" for an instrument the immediate pass was still loading
            # successfully. Moving the `create_task` into the `finally`
            # below removes the overlap window entirely: the periodic task
            # provably does not exist until the immediate pass has returned
            # (normally, or via the exception it catches internally, or
            # even if `_wait_for_instruments` itself raises).
            try:
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
                # The periodic task started in `finally` below still runs for
                # the client's lifetime; this is an ADDITIONAL early pass, not
                # a replacement.
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
            finally:
                # Resolution A (plan rev 6.1): started here, for the
                # client's lifetime -- a named, firewall-scanned coroutine
                # (`EXEC_RESOLVER_COROUTINES`), never awaited inline. It is
                # a no-op every pass until an AMBIGUOUS outcome writes a
                # durable resolver context via `_note_ambiguous_open`. A
                # `finally`, not a plain trailing statement: it must run
                # even if `_wait_for_instruments` raises, so
                # `_cancel_resolver_task` (`_disconnect`, reached
                # unconditionally by the kernel's shutdown sequence even
                # when `_connect` itself never completes -- see
                # `execution_engine.py`'s unconditional `client.disconnect()`
                # and `system/kernel.py:stop_async`'s `_disconnect_clients`)
                # always has a task to cancel.
                self._resolver_task = self.create_task(
                    self._resolve_ambiguous_intents(),
                    log_msg="resolve_ambiguous_intents",
                )
            # EDGE-2 slice D: one boot-time liveness line naming the
            # resolver's zero-fill corroboration mechanism and its two
            # tunables -- so a node log FILE proves the hardened resolver is
            # the one actually running, without naming any operator-control
            # value (§9 deploy criteria).
            self._log.info(
                "resolver: zero-fill corroboration=activities_v1 "
                f"min_age_s={_RESOLVER_ZERO_FILL_MIN_AGE_NS // 1_000_000_000} "
                "legs=yes,no"
            )
            await self._publish_account_state()
            await self._confirm_account_registered()
            self._reconcile_submit_intent()
            # S0 (plan rev 3, R3-1): boot-seed the daily ledger and the
            # permit's session budget from today's durable fills, AFTER
            # intent reconciliation and BEFORE the startup position evidence
            # read below -- a mid-day relaunch must not re-grant budget a
            # prior process in this same calendar day already spent.
            self._seed_spend_from_durable_fills()
            # AC6b (EDGE-2 plan r3, D8): the NEXT statement, no `await`
            # between -- a fill the resolver's own immediate pass above
            # already recorded (before this line runs) was necessarily
            # visible to the seed call directly above; a fill recorded by
            # ANY later resolver pass in this process (periodic, or a
            # second `_connect`) cannot have been, and must refuse.
            self._spend_seeded = True
            # NO-SIDE S5 (E3-8/E4-1/E4-5): the equivalent boot-time trigger
            # for the bounded first-order containment window -- runs
            # immediately AFTER the spend seed (same walk target: today's
            # durable fill records), via `self._store_set`, no flock, no
            # `await` in between (same unlocked-write pattern as
            # `_reconcile_submit_intent`/`record_fill`), so it lands before
            # the resolver's NEXT periodic pass, not before its first.
            self._reconcile_no_side_first_order_key()
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

    def _has_durable_fill_record(self, fingerprint: str, created_ns: int) -> bool:
        """SP-3r: the real boot probe for a crash between ``record_fill`` and
        ``_retire``.

        Returns the literal ``True`` (the only value :meth:`~breezy.runtime.
        submit_intent.SubmitIntentLatch.reconcile_at_startup` treats as a
        match) iff the day-scoped ``FILL_BY_FINGERPRINT_KEY_PREFIX`` entry
        for ``(day, fingerprint)`` exists AND the fill record it names still
        decodes. ``day`` is derived from ``created_ns`` -- the OPEN intent's
        OWN creation time, never this boot's wall clock -- so a crash just
        before a UTC-midnight rollover still probes the day the intent was
        actually armed on, matching exactly the day :meth:`record_fill`
        wrote under.

        Every failure mode (a bad timestamp, an unreadable index, an
        undecodable index value, a missing or undecodable fill record)
        returns ``False``: absence is never synthesised into a match, and no
        exception ever escapes to crash boot over a probe that is read-only
        by construction.
        """
        try:
            day = utc_day_for_ns(created_ns).isoformat()
        except Exception as exc:  # noqa: BLE001 - an unusable timestamp must refuse, not crash boot
            self._log.warning(
                "durable fill probe: could not derive a UTC day from "
                f"created_ns ({type(exc).__name__}); refusing"
            )
            return False
        index_key = f"{FILL_BY_FINGERPRINT_KEY_PREFIX}{day}:{fingerprint}"
        try:
            venue_order_id_raw = self._store_get(index_key)
        except Exception as exc:  # noqa: BLE001 - a store error must refuse, not crash boot
            self._log.warning(
                f"durable fill probe: index read failed ({type(exc).__name__}); refusing"
            )
            return False
        if venue_order_id_raw is None:
            return False
        try:
            venue_order_id = venue_order_id_raw.decode("utf-8")
        except Exception as exc:  # noqa: BLE001 - an undecodable index value must refuse
            self._log.warning(
                f"durable fill probe: index value undecodable ({type(exc).__name__}); refusing"
            )
            return False
        try:
            fill_raw = self._store_get(f"{FILL_KEY_PREFIX}{venue_order_id}")
        except Exception as exc:  # noqa: BLE001 - a store error must refuse, not crash boot
            self._log.warning(
                f"durable fill probe: fill record read failed ({type(exc).__name__}); refusing"
            )
            return False
        if fill_raw is None:
            return False
        try:
            DurableFillRecord.from_bytes(fill_raw)
        except Exception as exc:  # noqa: BLE001 - an undecodable fill record must refuse
            self._log.warning(
                f"durable fill probe: fill record undecodable ({type(exc).__name__}); refusing"
            )
            return False
        return True

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

    def _seed_candidate_ids(self, today: date) -> list[str]:
        """AC6b/G4 (EDGE-2 plan r3, D9): every venue order id
        :meth:`_seed_spend_from_durable_fills` must consider -- the
        per-instrument ``FILL_INDEX_KEY_PREFIX`` walk over every instrument
        this client's provider has loaded (unchanged), followed by today's
        ``FILL_BY_DAY_KEY_PREFIX`` index, so a fill recorded against a
        PAST-DAY instrument the provider never loaded (the past-day loader
        populates only ``self._cache``) is still reachable.

        Not de-duplicated here: the caller's own ``seen`` set is the single
        de-dupe point, exactly as it already was for the provider walk
        alone -- an id reachable through BOTH walks is still counted once.

        Fails CLOSED exactly like the caller: an unreadable index of
        EITHER kind raises immediately rather than silently walking a
        partial set.
        """
        candidate_ids: list[str] = []
        for instrument in self._instrument_provider.list_all():
            instrument_id = str(instrument.id)
            index_key = f"{FILL_INDEX_KEY_PREFIX}{instrument_id}"
            indexed = self._read_fill_index(index_key)
            if indexed is None:
                raise PolymarketUSError(
                    f"the durable fill index at {index_key!r} could not be read; "
                    "the boot-time spend seed refuses to arm on an incomplete walk"
                )
            candidate_ids.extend(indexed)
        day_index_key = f"{FILL_BY_DAY_KEY_PREFIX}{today.isoformat()}"
        day_indexed = self._read_fill_index(day_index_key)
        if day_indexed is None:
            raise PolymarketUSError(
                f"the durable day-fill index at {day_index_key!r} could not be "
                "read; the boot-time spend seed refuses to arm on an incomplete walk"
            )
        candidate_ids.extend(day_indexed)
        return candidate_ids

    def _seed_spend_from_durable_fills(self) -> None:
        """S0 (plan rev 3, R3-1): book today's already-spent USD into the
        daily ledger and the permit's session budget before anything can
        arm.

        Walks every instrument this client's provider has loaded, plus
        today's day index (:meth:`_seed_candidate_ids`) -- summing
        ``DurableFillRecord.cumulative_cost`` for records whose ``ts_event``
        falls in today's UTC calendar day, de-duplicated per
        ``venue_order_id`` (the create and resolver paths overwrite the same
        key, and an id reachable through both walks is still one order, so
        one order is counted once).

        **Fails CLOSED.** ``_seed_candidate_ids`` raising -- a per-instrument
        or day-index corruption, not only a wholesale walk exception -- or a
        fill index naming a record this store cannot produce, propagates
        unchanged. Left uncaught, this reaches ``_connect``'s own fault
        latch, which records the fault and requests a native shutdown: the
        same direction ``_run_never_arm_walk``'s
        ``_POSITION_FILL_WALK_UNREADABLE`` path takes, one layer up.

        **Never reads or logs an operator-control value.** The only inputs
        are durable fill records already on disk; the only output is an INFO
        line naming the record count and the UTC day, never a dollar figure.

        **Idempotent.** A second ``_connect()`` in the same process re-walks
        the same records, but :meth:`DailySpendLedger.seed_spent` and
        :func:`seed_permit_budget_from_prior_spend` are each keyed to apply
        at most once, so re-running this method cannot double-book.
        """
        if self._ledger is None:
            return
        now_ns = self._clock.timestamp_ns()
        today = utc_day_for_ns(now_ns)
        seen: set[str] = set()
        total = Decimal(0)
        count = 0
        for venue_order_id in self._seed_candidate_ids(today):
            if venue_order_id in seen:
                continue
            seen.add(venue_order_id)
            raw = self._store_get(f"{FILL_KEY_PREFIX}{venue_order_id}")
            if raw is None:
                raise PolymarketUSError(
                    f"a durable fill index names venue order {venue_order_id!r} "
                    "but no record exists for it"
                )
            record = DurableFillRecord.from_bytes(raw)
            if utc_day_for_ns(record.ts_event) != today:
                continue
            total += record.cumulative_cost
            count += 1
        if count == 0:
            return
        self._ledger.seed_spent(day=today, spent_usd=total, now_ns=now_ns)
        if self._permit is not None:
            seed_permit_budget_from_prior_spend(permit=self._permit, spent_usd=total)
        self._log.info(
            f"seeded from {count} fill record(s) for {today.isoformat()}"
        )

    def _reconcile_no_side_first_order_key(self) -> None:
        """NO-SIDE S5 (E3-8/E4-1/E4-5): the equivalent, fail-closed boot
        trigger for the bounded first-order containment window (PREREG
        amendment §8 item 1b). If any NO-leg :class:`DurableFillRecord`
        exists (a crash between a Track A create-path submission and its
        own key write) while :data:`NO_SIDE_FIRST_LIVE_ORDER_KEY` is still
        absent, this writes it here -- before the resolver's next periodic
        pass -- so the containment window is entered even on that crash
        path. Idempotent: a second boot with the key already present is a
        no-op, and the key is never overwritten once set.

        Walks the SAME per-instrument ``FILL_INDEX_KEY_PREFIX`` index
        :meth:`_seed_spend_from_durable_fills` already walks, filtered to
        NO-leg instruments (:func:`leg_of`) -- never a full-store scan.
        Never raises: an unreadable fill index for one instrument is
        already fatal to the SEED above (which runs first and would have
        raised), so by the time control reaches here every index this
        client's provider names is known-readable.
        """
        if self._store_get(NO_SIDE_FIRST_LIVE_ORDER_KEY) is not None:
            return
        for instrument in self._instrument_provider.list_all():
            if leg_of(instrument.id) != "no":
                continue
            instrument_id = str(instrument.id)
            index_key = f"{FILL_INDEX_KEY_PREFIX}{instrument_id}"
            indexed = self._read_fill_index(index_key)
            if not indexed:
                continue
            venue_order_id = indexed[0]
            raw = self._store_get(f"{FILL_KEY_PREFIX}{venue_order_id}")
            if raw is None:
                continue
            record = DurableFillRecord.from_bytes(raw)
            self._store_set(
                NO_SIDE_FIRST_LIVE_ORDER_KEY,
                first_live_order_payload(
                    record.instrument_id,
                    record.ts_event,
                    venue_order_id=record.venue_order_id,
                ),
            )
            self._log.info(
                "no_side_first_order_key: written at boot reconcile "
                f"for instrument {instrument_id}"
            )
            return

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

        Up to TWO entries per currently-latched intent id: the first stale
        sighting (`last_failure_kind` as of that pass, "none" if this
        process has not yet classified a failure for it), and -- at most
        once, one pass later -- a follow-up carrying the cause once this
        process identifies one (FAILURE-KIND-PERSIST). An operator can
        therefore see two CRITICALs for one intent. `_retire` (the single
        chokepoint every resolution path runs through) drops BOTH entries
        the moment the intent retires, so a LATER intent reaching the same
        age surfaces again.
        """
        return tuple(self._resolver_stale_alert_details.values())

    @property
    def resolver_evidence_contradictions(self) -> tuple[Mapping[str, str], ...]:
        """EDGE-2 slice D (AC4): the health surface for a
        ``resolver_evidence_contradiction`` -- the GET evidence says
        terminal zero-fill, but the create-time evidence or the activities
        trade join for this venue order id says otherwise.

        **Read-only surface, deliberately -- not an emitted alert**, for the
        identical E0-TRANSPORT/E0-NOSEND-RESOLVER reason
        :attr:`stale_ambiguous_intent_alerts` documents: this module cannot
        import an `AlertSink`, and `_resolve_ambiguous_intents` may add no
        new callee beyond the ones this plan's AC9 rows allowlist. The
        runtime layer's health-watch subscriber builds the CRITICAL
        `AlertPayload` from this tuple.

        One entry per intent currently in contradiction -- `_retire` drops
        the entry on retirement, mirroring the stale-intent pair above.
        """
        return tuple(self._resolver_contradiction_details.values())

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

        FU-8 r2/r2.1: a fill resolved for an order this RUN never submitted
        (a cross-session fill, ``self._cache.order(...)`` returns ``None``)
        is never handed to ``generate_order_filled`` at all --
        ``_resolve_accept_fill``'s own ``_resolver_fill_order_unknown`` gate
        (next to ``_latch_reconciliation_refusal``) decides, and a crash
        anywhere in this coroutine still leaves the durable record as the
        source of truth either way.

        The LONG gate (``_resolver_long_position_state``) is slug-level,
        leg-aware ``netPosition`` sign corroboration ONLY (per
        ``reports.position_leg``), never magnitude-matched against the GET's
        own ``filled_qty`` -- the order-specific GET report is the sole
        authority for the quantity and price a fill is synthesized from; the
        positions read exists only to confirm a LONG on THIS order's own leg
        exists at all before acting (EDGE-2C: a NO holding is a LONG on the
        NO-leg instrument, per the 2026-09-16 ruling, never a SHORT on the
        YES one).
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
            # R-9a (HF-4 rev2, B4 supply side): age-gated startup-evidence
            # refresh, on EVERY pass -- including one with no OPEN intent,
            # which is exactly when the strategy's re-arm gate is
            # re-arm-shopping. Placed here (after the latch-None guard,
            # before `current_open()` below) deliberately: it must run
            # whether or not an intent is OPEN. The `except` is INERT
            # (R-9a): it must never touch `_resolver_consecutive_failures`
            # (that counter belongs to the order-GET path only, below) and
            # never `_refuse` -- a positions-endpoint blip must not slow
            # order resolution or halt trading. Every callee here
            # (`self._clock.timestamp_ns`, `self._private_read`,
            # `self._declared_positions`, `self._write_startup_position_
            # evidence`, `self._log.warning`) is already an
            # EXEC_RESOLVER_PERMITTED_CALLEES member -- zero allowlist
            # delta (verified by running the guard, unmodified).
            refresh_now_ns = self._clock.timestamp_ns()
            if refresh_now_ns - self._last_evidence_write_ns >= _EVIDENCE_REFRESH_AFTER_NS:
                try:
                    refresh_payload = await self._private_read(PORTFOLIO_POSITIONS_PATH)
                    refresh_positions = self._declared_positions(refresh_payload)
                    # Section 4.3: the open-order evidence is refreshed on the
                    # SAME age gate, so a rest appearing after boot reaches
                    # the re-arm gate. Its outcome (success OR failure) is
                    # recorded below; only the positions GET keeps this
                    # branch's "prior record kept" semantics.
                    try:
                        refresh_open_orders = await self._read_open_orders()
                    except Exception as open_exc:  # noqa: BLE001 - recorded as refused
                        self._note_open_orders_outcome(error=open_exc)
                    else:
                        self._note_open_orders_outcome(records=refresh_open_orders)
                except Exception as exc:  # noqa: BLE001 - inert; never `_refuse`
                    self._log.warning(
                        "resolver: startup-evidence refresh GET failed "
                        f"({type(exc).__name__}: {exc}); prior record kept"
                    )
                else:
                    self._write_startup_position_evidence(
                        now_ns=refresh_now_ns,
                        eof_complete=True,
                        position_read_refused=False,
                        raw_positions=refresh_positions,
                    )
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
                    f"{current.intent_id}; window-only no-id pass"
                )
                # AMBIG-LATCH-RESUME (window-only mode): no context means no
                # echo; the branch applies the strictest rules and acts only
                # after its own min age.
                try:
                    await self._resolve_no_id_intent(
                        current.intent_id, current.created_ns, None, None
                    )
                except Exception as exc:  # noqa: BLE001 - never kill the polling task
                    self._note_resolver_error(current.intent_id, exc)
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
            # FAILURE-KIND-DURABLE (2026-09-28): seed this process's
            # in-memory failure-kind map from the durable context the FIRST
            # time this intent is seen -- a restart's `_resolver_last_
            # failure_kind` starts empty (process-local memory), so without
            # this the first stale CRITICAL after a restart would always
            # read the dict-membership default `"none"`, discarding
            # whatever an earlier process already classified. Plain `in`/
            # `!=`/subscript/assignment only: no new callee
            # (E0-NOSEND-RESOLVER). A `"none"` durable kind seeds nothing --
            # identical to never having seeded at all.
            if (
                context.intent_id not in self._resolver_last_failure_kind
                and context.last_failure_kind != "none"
            ):
                self._resolver_last_failure_kind[context.intent_id] = context.last_failure_kind
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
            # FAILURE-KIND-PERSIST (r2/r3): a follow-up entry, written AT
            # MOST ONCE per intent per process, once a real cause is later
            # identified for an already-alerted intent. `last_failure_kind`
            # here is deliberately the value THIS process recorded on an
            # EARLIER pass (never this pass's own classification, which has
            # not run yet) -- the same one-pass-behind read the stale block
            # above already uses. Plain `in`/`!=`/subscript/f-string/dict-
            # unpacking only: no new callee (E0-NOSEND-RESOLVER).
            if (
                context.intent_id in self._resolver_stale_alerted_intent_ids
                and context.intent_id in self._resolver_last_failure_kind
                and self._resolver_last_failure_kind[context.intent_id] != "none"
                and self._resolver_last_failure_kind[context.intent_id]
                != self._resolver_stale_alert_details[context.intent_id]["last_failure_kind"]
                and f"{context.intent_id}:cause" not in self._resolver_stale_alert_details
            ):
                self._resolver_stale_alert_details = {
                    **self._resolver_stale_alert_details,
                    f"{context.intent_id}:cause": {
                        "severity": "CRITICAL",
                        "event": "open_intent_stale",
                        "site": "global",
                        "intent_id": context.intent_id,
                        "venue_order_id": context.venue_order_id,
                        "age_minutes": f"{stale_age_ns // 60_000_000_000}",
                        "last_failure_kind": self._resolver_last_failure_kind[
                            context.intent_id
                        ],
                        "alert_key": f"{context.intent_id}:cause",
                        "followup": "cause",
                    },
                }
            instrument = self._cache.instrument(InstrumentId.from_str(context.instrument_id))
            if instrument is None and self._resolver_instrument_loader is not None:
                # 2026-09-24 fix: the OPEN intent's instrument may belong to
                # a PRIOR day's node boot (the node boots for TODAY's
                # instruments only) and be absent from THIS run's cache. A
                # loader that can read it from durable history (never the
                # venue-backed InstrumentProvider, which refuses anything
                # outside the latest discovery cycle for an expired market,
                # and never subscribes to market data) is consulted here --
                # gated to `_RESOLVER_INSTRUMENT_LOAD_RETRY_NS` apart (HIGH
                # review fix, post-ac691dc): the loader is a synchronous
                # full-catalog scan, measured at 1.06-1.36s against the
                # production catalog -- see that constant's docstring.
                # Deliberately NOT `.get(...)`: a dict-method call here is a
                # new, unpermitted callee under E0-NOSEND-RESOLVER (see the
                # backoff comment above).
                # Deliberately NOT `.get(...)`: a dict-method call here is a
                # new, unpermitted callee under E0-NOSEND-RESOLVER (see the
                # backoff comment above).
                last_attempted_ns = self._resolver_instrument_load_attempted_ns[context.instrument_id] if context.instrument_id in self._resolver_instrument_load_attempted_ns else None  # noqa: E501, SIM401
                load_now_ns = self._clock.timestamp_ns()
                if (
                    last_attempted_ns is None
                    or load_now_ns - last_attempted_ns >= _RESOLVER_INSTRUMENT_LOAD_RETRY_NS
                ):
                    self._resolver_instrument_load_attempted_ns = {
                        **self._resolver_instrument_load_attempted_ns,
                        context.instrument_id: load_now_ns,
                    }
                    # Off the event loop: the scan is blocking local I/O, not
                    # a network call -- `self._loop` is the SAME loop this
                    # coroutine already runs on (`LiveExecutionClient.
                    # __init__`), and `run_in_executor` hands the call to the
                    # default thread pool so the rest of the node (order
                    # sends, quote processing) keeps running while it
                    # completes, instead of stalling behind it.
                    instrument = await self._loop.run_in_executor(
                        None, self._resolver_instrument_loader, context.instrument_id,
                    )
                    if instrument is not None:
                        self._cache.add_instrument(instrument)
            if instrument is None:
                # A miss counts toward the SAME consecutive-failure backoff
                # the GET path below uses -- every pass this intent fails to
                # progress on, for whatever reason, slows the next attempt.
                self._resolver_consecutive_failures += 1
                self._set_resolver_last_failure_kind(context, "instrument_unavailable")
                if context.instrument_id not in self._resolver_missing_instrument_logged:
                    self._resolver_missing_instrument_logged = (
                        self._resolver_missing_instrument_logged | {context.instrument_id}
                    )
                    self._log.error(
                        f"resolver: instrument {context.instrument_id} is not in "
                        "the cache and could not be loaded; this intent stays "
                        "AMBIGUOUS until a definition becomes available "
                        f"(backoff: {self._resolver_consecutive_failures} consecutive "
                        "failure(s))"
                    )
                else:
                    self._log.debug(
                        f"resolver: instrument {context.instrument_id} still "
                        "unavailable; retrying next pass "
                        f"(backoff: {self._resolver_consecutive_failures} consecutive "
                        "failure(s))"
                    )
                continue
            if context.venue_order_id == submit_chain.NO_VENUE_ORDER_ID:
                # AMBIG-LATCH-RESUME (attributed mode): the pre-POST context has
                # no venue id, so there is nothing a GET by id could resolve.
                # The with-id path from the GET below is byte-unchanged.
                try:
                    await self._resolve_no_id_intent(
                        current.intent_id, current.created_ns, context, instrument
                    )
                except Exception as exc:  # noqa: BLE001 - never kill the polling task
                    self._note_resolver_error(current.intent_id, exc)
                continue
            try:
                order_payload = await self._private_read(
                    submit_chain.order_by_id_path(context.venue_order_id)
                )
            except Exception as exc:  # noqa: BLE001 - GET failure stays AMBIGUOUS
                self._resolver_consecutive_failures += 1
                self._set_resolver_last_failure_kind(context, "get_exception")
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
                    # INC-E2d: `context.order_side` is the order's REAL side
                    # captured at `_note_ambiguous_open` time (INC-E2a) --
                    # "SELL" only for an exit, since every entry this client
                    # ever submits is a plain BUY (`allow_short=False`). A
                    # `context.order_side` of `LONG_ONLY_SIDE` ("BUY", the
                    # field's own default for an old blob predating this
                    # field) resolves `closing=False`, so a pre-existing
                    # durable context decodes with byte-identical behaviour.
                    closing=context.order_side == "SELL",
                )
            except Exception as exc:  # noqa: BLE001 - malformed stays AMBIGUOUS
                self._resolver_consecutive_failures += 1
                self._set_resolver_last_failure_kind(context, "mapping_error")
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
            # FAILURE-KIND-PERSIST (r2/r3, ARCH B1): a successful GET means
            # THIS pass's evidence supersedes whatever kind an earlier pass
            # recorded -- reset to "none" UNLESS the recorded kind is
            # `activities_uninterpretable`, which this pass's own join
            # (below) has not been re-examined yet and may still hold; the
            # clean-join clear right after the join call is the one place
            # that kind is reset. Plain `in`/`!=`/subscript: no new callee.
            if (
                context.intent_id not in self._resolver_last_failure_kind
                or self._resolver_last_failure_kind[context.intent_id]
                != "activities_uninterpretable"
            ):
                self._set_resolver_last_failure_kind(context, "none")

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

            # EDGE-2C (AC1/AC3): `base_slug_of`/`leg_of` are the sanctioned
            # readers for EITHER leg's id (`instrument_id_to_slug` refuses a
            # NO-leg id outright -- the L-48 crash this guard exists to
            # close); the whole derivation sits in one `try` because a
            # slug/leg/holding failure must never kill this coroutine any
            # more than a `_resolve_terminal_zero`/`_resolve_accept_fill`
            # failure does below.
            try:
                leg = leg_of(instrument.id)
                slug = base_slug_of(instrument.id)
                long_state = _resolver_long_position_state(positions, slug, leg)
            except Exception as exc:  # noqa: BLE001 - see the comment above
                self._note_resolver_error(context.intent_id, exc)
                continue
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

            # EDGE-2 slice D (AC4): the two shapes EDGE-2C's own boolean
            # corroboration (`long_state`) cannot decide alone -- the
            # ordinary zero-fill candidate (AC4(c)/(d)/(e) are now MANDATORY
            # for every terminal-zero, not only the ones `long_state`
            # already agreed with), a same-day PRIOR durable holding that
            # would otherwise wedge a true zero-fill (AC4(e)/AC7(iii)), and
            # an unheld fill on a settled market or a completed exit (D7).
            # `long_state is True` already proves a fill without a second
            # read (the ordinary same-session entry-fill shape); the join
            # is skipped ONLY in that one case.
            zero_fill_needs_evidence = is_terminal_zero
            fill_needs_evidence = is_fill and long_state is not True
            join: TradeJoin | None = None
            if zero_fill_needs_evidence or fill_needs_evidence:
                join = await self._order_trade_activity(context.venue_order_id, context.created_ns)
                if join is not None and join.uninterpretable_rows:
                    # TRADE-ROW-DRIFT r2 T-1: diagnosable, delivered via the
                    # SAME `open_intent_stale` CRITICAL every other failure
                    # kind above already reaches -- `self._set_resolver_last_
                    # failure_kind` is the E0-NOSEND-RESOLVER-allowlisted,
                    # durable-mirroring sibling of the plain dict assignment
                    # this used to be (FAILURE-KIND-DURABLE, 2026-09-28).
                    self._set_resolver_last_failure_kind(context, "activities_uninterpretable")
                elif join is not None and not join.uninterpretable_rows:
                    # FAILURE-KIND-PERSIST (r2/r3, ARCH B1): a CLEAN join
                    # (whether or not it is COMPLETE -- :2809 below decides
                    # that separately) clears a stale
                    # `activities_uninterpretable` kind the guarded reset
                    # above deliberately left alone.
                    self._set_resolver_last_failure_kind(context, "none")
            trade_found = join is not None and join.trade_count >= 1
            evidence_blocks_zero_fill = (
                context.create_fill_evidence in _CREATE_FILL_EVIDENCE_BLOCKS_ZERO_FILL
            )

            if is_terminal_zero:
                if trade_found or evidence_blocks_zero_fill:
                    # AC4: (c) found a trade, or (b) carries create-time
                    # fill evidence, while the GET itself reports terminal
                    # zero -- the two sources of truth disagree. Stays
                    # AMBIGUOUS; never terminal.
                    self._resolver_contradiction_details = {
                        **self._resolver_contradiction_details,
                        context.intent_id: {
                            "severity": "CRITICAL",
                            "event": "resolver_evidence_contradiction",
                            "site": "global",
                            "intent_id": context.intent_id,
                            "venue_order_id": context.venue_order_id,
                            "trade_count": f"{join.trade_count if join is not None else 0}",
                            "create_fill_evidence": context.create_fill_evidence,
                        },
                    }
                    self._log.error(
                        "resolver: evidence contradiction for venue order "
                        f"{context.venue_order_id} -- GET reports terminal "
                        f"zero-fill but trade_count="
                        f"{join.trade_count if join is not None else 0} "
                        f"create_fill_evidence={context.create_fill_evidence!r}; "
                        "stays AMBIGUOUS"
                    )
                    continue
                if join is None or not join.complete:
                    self._log.warning(
                        f"resolver: activities join incomplete for venue "
                        f"order {context.venue_order_id}; zero-fill stays "
                        "AMBIGUOUS pending a complete read"
                    )
                    continue
                age_ns = now_ns - context.created_ns
                if age_ns < _RESOLVER_ZERO_FILL_MIN_AGE_NS:
                    self._log.info(
                        f"resolver: venue order {context.venue_order_id} is "
                        "below the "
                        f"{_RESOLVER_ZERO_FILL_MIN_AGE_NS // 1_000_000_000}s "
                        "zero-fill min age; stays AMBIGUOUS"
                    )
                    continue
                # AC4(e): same-day reads only -- an instrument from the
                # past-day loader skips this leg entirely (a settled market
                # leaves the positions page, D2). "Same-day" is the SAME
                # provider walk `_seed_spend_from_durable_fills` uses: the
                # node loads only today's instruments into the provider, so
                # membership there (never the Nautilus `Cache`, which the
                # past-day loader also populates) is what distinguishes the
                # two regimes on every pass, not only the one where the
                # loader actually fired.
                same_day_instrument = False
                for candidate in self._instrument_provider.list_all():
                    if candidate.id == instrument.id:
                        same_day_instrument = True
                        break
                if same_day_instrument:
                    try:
                        venue_leg_qty = _resolver_leg_holding_qty(positions, slug, leg)
                        durable_qty = self._durable_net_qty(instrument.id)
                    except Exception as exc:  # noqa: BLE001 - see the comment above
                        self._note_resolver_error(context.intent_id, exc)
                        continue
                    if (
                        venue_leg_qty is None
                        or durable_qty is None
                        or venue_leg_qty > durable_qty
                    ):
                        self._log.warning(
                            "resolver: same-day holding baseline does not "
                            f"clear venue order {context.venue_order_id} "
                            f"(venue_leg_qty={venue_leg_qty} durable_qty="
                            f"{durable_qty}); stays AMBIGUOUS"
                        )
                        continue
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
            elif is_fill:
                fill_confirmed = long_state is True or (
                    join is not None and join.complete and join.trade_count >= 1
                )
                if fill_confirmed:
                    try:
                        self._resolve_accept_fill(context, report, instrument, now_ns)
                    except Exception as exc:  # noqa: BLE001 - see the comment above
                        self._note_resolver_error(context.intent_id, exc)
                        continue
                else:
                    self._log.warning(
                        "resolver: GET evidence and the positions/activities "
                        f"read disagree for venue order {context.venue_order_id} "
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
        # B3 (Decision 3, HF-4 rev2): `_retire` itself does not log -- one
        # INFO line per retirement, matching the strategy-side `rearm:`
        # observability seam's own per-transition discipline.
        self._log.info(
            f"resolver: retired intent {context.intent_id} "
            "(STATUS_REPORT_ZERO_FILL_TERMINAL)"
        )
        booking = self._ambiguous_bookings.pop(context.intent_id, None)
        if booking is not None:
            # Same-process only (Resolution E): on restart the ledger died
            # with the process and this dict is empty -- the reminted
            # budget already starts whole, so there is nothing to true up.
            # WP-DR: a booking from a PRIOR UTC day cannot be trued up (the
            # ledger day already rolled and its spend is gone); a zero-fill
            # carries no spend, so skipping is complete. Day-equality only,
            # never a blanket except: same-day ledger errors still escalate.
            if booking.day != utc_day_for_ns(now_ns):
                self._log.info(
                    f"resolver: skipped prior-day ledger true-up for intent "
                    f"{context.intent_id}; booking day {booking.day}, "
                    f"today {utc_day_for_ns(now_ns)}"
                )
            else:
                self._ledger.true_up_booking(
                    booking, filled_cost_usd=submit_chain.ZERO, now_ns=now_ns
                )
            # AC6 (EDGE-2 plan r3, D3): the permit restore is gated on the
            # SAME `booking is not None` check as the ledger true-up right
            # above -- a cross-process or next-day terminal-zero never took
            # a booking in THIS process, so the one permit slot it would
            # give back was never debited by this process's own ledger in
            # the first place. Restoring it anyway would re-grant a slot
            # nothing here ever spent (D3).
            if self._permit is not None and restore_live_trading_budget(
                permit=self._permit,
                venue_order_id=context.venue_order_id,
                order_notional_usd=context.notional_usd,
            ):
                self._mark_budget_restored(context.venue_order_id)
        else:
            self._log.info(
                "resolver: cross-process terminal-zero; permit restore skipped"
            )
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
        # 2026-10-02: the instrument-unscoped AMBIGUOUS refusal `_refuse`
        # appended at create time has no subject left once THIS terminal
        # zero-fill (GET-confirmed, EOF-complete empty trade join) has
        # retired the intent AND trued up the booking AND restored the
        # permit slot. It is therefore the LAST step: any raise above (the
        # resolver catches it, counts it, and the next pass takes the
        # `current is None` early return) leaves the refusal in place, the
        # conservative direction. Inline (not a helper) so
        # E0-NOSEND-RESOLVER's permitted callee set is unchanged. Cleared
        # only while the durable latch holds no other open intent; every
        # other reason stays. New list, no in-place mutation.
        if self._latch.current_open() is None:
            kept_refusals = [
                refusal
                for refusal in self._trading_refusals
                if refusal.reason != submit_chain.AMBIGUOUS_REASON
            ]
            if len(kept_refusals) != len(self._trading_refusals):
                self._trading_refusals = kept_refusals
                self._ambiguous_refusal_clears += 1
                self._log.info(
                    f"resolver: cleared the AMBIGUOUS trading refusal "
                    f"({submit_chain.AMBIGUOUS_REASON!r}) on retirement of "
                    f"intent {context.intent_id}"
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

        FU-8 r2/r2.1 (option A): ``generate_order_filled`` itself is now
        gated by ``_resolver_fill_order_unknown`` -- a fill for an order this
        RUN never submitted (cross-session) is NEVER booked at runtime. That
        gate runs AFTER the durable writes above (record_fill / retire /
        venue-id map), never before -- this method's own crash-safety
        ordering is unchanged. The gate is INFORMATIONAL, not a control: see
        its docstring.

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
            # INC-E2: the order's REAL side (`context.order_side`), never the
            # entry-only `LONG_ONLY_SIDE` hardcode -- an old context (written
            # before this change) still decodes `order_side` as
            # `LONG_ONLY_SIDE`, so this is byte-identical for every fill this
            # resolver has ever recorded to date.
            order_side=context.order_side,
            cumulative_qty=cumulative_qty,
            cumulative_cost=cumulative_cost,
            cumulative_fee=submit_chain.ZERO,
            fee_reconciled=False,
            # S3 item 3 (plan 2026-09-14): `ts_event` is the RESOLVER's own
            # wall-clock discovery time (`now_ns`, this method's own GET
            # timestamp), never a venue-reported execution time -- the
            # Order-only GET this path resolves from carries no execution
            # legs and no fill timestamp at all. This differs from the
            # CREATE path's `KIND_ACCEPT_FILL` branch, which stamps the
            # venue's own execution time. Consequence, stated rather than
            # papered over: the S0 boot-seed
            # (`_seed_spend_from_durable_fills`) buckets every durable fill
            # by `ts_event`, so a resolver-path fill DISCOVERED after UTC
            # midnight is booked into the discovery day's seed, never the
            # (unknown, possibly earlier) day the fill actually happened on
            # the venue. Conservative -- the discovery day's ledger and
            # permit budget see this spend even if the fill itself belongs
            # to the prior day, never the reverse.
            ts_event=now_ns,
            venue_fee_raw=None,
            trade_id=_synthetic_get_fill_trade_id(context.venue_order_id).value,
            order_qty=report.quantity.as_decimal(),
        )
        try:
            # AUD-13b (ruling R-1 = O4 (a)): stamp the theta of the instrument
            # in hand NOW -- i.e. at DISCOVERY, like `ts_event` above; the
            # true fill lies in [intent created, now] (evidence pack F3).
            self.record_fill(
                record,
                fill_time_instrument=instrument,
                intent_fingerprint=current.fingerprint,
                intent_created_ns=current.created_ns,
            )
        except Exception as exc:  # noqa: BLE001 - see the CREATE path's identical guard
            fill_record_bytes = record.to_bytes()
            detail = fill_record_bytes.decode()
            self._log.error(
                f"{_FILL_WRITE_FAILED}: {exc.__class__.__name__}: {exc}; record={detail}"
            )
            self._refuse(_FILL_WRITE_FAILED)
            return
        booking = self._ambiguous_bookings.pop(context.intent_id, None)
        if booking is not None and booking.day != utc_day_for_ns(now_ns):
            # WP-DR: a fill discovered on a NEW UTC day against a prior-day
            # booking cannot be trued up (the ledger day rolled) and the
            # in-process ledger has no additive API. Treat it as UNBOOKED so
            # the AC6b condition below latches the durable
            # `_RESOLVER_FILL_UNBUDGETED` refusal (fail-closed; a respawn
            # re-seeds the spend by the record's discovery-time ts_event).
            self._log.info(
                f"resolver: skipped prior-day ledger true-up for intent "
                f"{context.intent_id}; booking day {booking.day}, "
                f"today {utc_day_for_ns(now_ns)}"
            )
            booking = None
        elif booking is not None:
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
        # B3 (Decision 3, HF-4 rev2): `_retire` itself does not log -- one
        # INFO line per retirement, matching `_resolve_terminal_zero`'s own.
        self._log.info(
            f"resolver: retired intent {context.intent_id} "
            "(STATUS_REPORT_ACCEPT_FILL_TERMINAL)"
        )
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
        # AC6b (EDGE-2 plan r3, D6/D8/D9): a fill resolved in a PRIOR
        # process (`booking is None`) AFTER this process's own boot spend
        # seed already totalled today's fills (`self._spend_seeded`) is
        # invisible to that seed -- the daily budget would silently
        # under-count it for the rest of this process's lifetime (D6).
        # Exempt: a fill resolved BEFORE the seed ran (the seed counts it,
        # D8) and every exit fill (`order_side == "SELL"` spends no budget;
        # a legacy context with no recorded side decodes as `LONG_ONLY_SIDE`
        # and refuses, fail-closed). This only LATCHES a refusal -- it never
        # touches the record, ledger or permit already written above, and
        # it clears on respawn: the new process's seed reads
        # `FILL_BY_DAY_KEY_PREFIX` and books this record whether or not its
        # instrument is loaded (G4).
        if (
            booking is None
            and context.order_side != "SELL"
            and self._spend_seeded
        ):
            self._log.error(f"{_RESOLVER_FILL_UNBUDGETED}; intent={context.intent_id}")
            self._refuse(_RESOLVER_FILL_UNBUDGETED)
        # FU-8 r2/r2.1 (option A): a cross-session fill (this run never
        # submitted the order) is NEVER booked at runtime -- see the
        # helper's own docstring. Every durable write above (record_fill,
        # retire, venue-id map, permit true-up) has already happened.
        if self._resolver_fill_order_unknown(context, report):
            return
        self.generate_order_filled(
            strategy_id=StrategyId(context.strategy_id),
            instrument_id=InstrumentId.from_str(context.instrument_id),
            client_order_id=ClientOrderId(context.client_order_id),
            venue_order_id=submit_chain.venue_order_id(context.venue_order_id),
            venue_position_id=None,
            trade_id=_synthetic_get_fill_trade_id(context.venue_order_id),
            # INC-E2: the order's REAL side, reconstructed from the durable
            # context's own record (`OrderSide[...]` is a by-name lookup,
            # e.g. `OrderSide["BUY"] is OrderSide.BUY`) -- never the
            # hardcoded `OrderSide.BUY`.
            order_side=OrderSide[context.order_side],
            order_type=OrderType.LIMIT,
            last_qty=report.filled_qty,
            last_px=instrument.make_price(avg_px),
            quote_currency=USD,
            commission=Money(0, USD),
            liquidity_side=LiquiditySide.TAKER,
            ts_event=now_ns,
        )
        # 2026-10-03 (A3): the AMBIGUOUS refusal `_refuse` appended at create
        # time has no subject left once this GET-confirmed fill retirement
        # has recorded the fill, trued up the booking, closed the singleton
        # and emitted the fill. LAST statement: any raise above keeps the
        # refusal (the conservative direction). The cross-session early
        # return above never reaches here by design: AMBIGUOUS_REASON has
        # only `_submit_order` producers, so an entry exists only in the
        # submitting process. Inline (not a helper) so the resolver callee
        # set is unchanged. Every other reason stays.
        if self._latch.current_open() is None:
            kept_refusals = [
                refusal
                for refusal in self._trading_refusals
                if refusal.reason != submit_chain.AMBIGUOUS_REASON
            ]
            if len(kept_refusals) != len(self._trading_refusals):
                self._trading_refusals = kept_refusals
                self._ambiguous_refusal_clears += 1
                self._log.info(
                    f"resolver: cleared the AMBIGUOUS trading refusal "
                    f"({submit_chain.AMBIGUOUS_REASON!r}) on fill retirement of "
                    f"intent {context.intent_id}"
                )

    async def _order_trade_activity(
        self, venue_order_id: str, created_ns: int
    ) -> TradeJoin | None:
        """EDGE-2 slice D (AC4(c)/§4): page ``/v1/portfolio/activities``
        (``sortOrder=SORT_ORDER_DESCENDING``) until ``eof`` or
        :data:`_RESOLVER_ACTIVITY_MAX_PAGES`, joining every
        ``ACTIVITY_TYPE_TRADE`` row naming ``venue_order_id``
        (:func:`~breezy.adapters.polymarket_us.account_activity.
        trade_rows_for_order`).

        Returns ``None`` on any read or shape failure -- the caller treats
        that exactly like a positions-read failure: stay AMBIGUOUS, try
        again next pass. ``created_ns`` is accepted (and named in the log
        line) for the future ``EDGE-2-MULTIPAGE`` threshold branch; it is
        NOT consulted for completeness today (see :class:`TradeJoin`'s own
        docstring -- the coordinator amendment makes ``complete`` EOF-ONLY).

        EDGE-2-MULTIPAGE step 1 (r2 M-1): a MALFORMED page (``activities``
        not a list, or ``eof`` present and not a bool) never returns
        ``None`` -- unlike the read-failure/non-object shapes above, a
        malformed page still carries whatever trades earlier pages already
        found, so it stops the read the same way a page-cap hit does:
        ``TradeJoin(complete=False, ...)`` with those trades counted. A
        trade already found before the malformed page must still raise the
        resolver's evidence-contradiction CRITICAL; a bare ``None`` would
        have silently discarded that evidence instead.

        TRADE-ROW-DRIFT (r2): an uninterpretable TRADE row (:func:`~breezy.
        adapters.polymarket_us.account_activity.trade_rows_for_order`) stops
        the read the same way -- ``complete=False``, matches already found
        (this page and earlier) still counted, never discarded.
        """
        cursor: str | None = None
        trade_refs: list[TradeActivityRef] = []
        uninterpretable_rows = 0
        running_min_create_ts_ns: int | None = None
        reached_eof = False
        redacted = _redact_order_id(venue_order_id)
        for _page_index in range(_RESOLVER_ACTIVITY_MAX_PAGES):
            query: dict[str, object] = {
                "limit": _RESOLVER_ACTIVITY_PAGE_LIMIT,
                "sortOrder": _RESOLVER_ACTIVITY_SORT_ORDER,
            }
            if cursor:
                query["cursor"] = cursor
            try:
                page = await self._private_read(PORTFOLIO_ACTIVITIES_PATH, query)
            except Exception as exc:  # noqa: BLE001 - read failure stays AMBIGUOUS
                self._log.warning(
                    f"resolver: activities read failed for venue order {redacted} "
                    f"({type(exc).__name__}: {exc}); trade join incomplete"
                )
                return None
            if not isinstance(page, Mapping):
                self._log.warning(
                    f"resolver: activities page for venue order {redacted} was "
                    "not an object; trade join incomplete"
                )
                return None
            activities_field = page.get("activities")
            if not isinstance(activities_field, list):
                self._log.warning(
                    f"resolver: activities page for venue order {redacted} carried "
                    f"a non-list activities field (keys={[k for k in page]}); "
                    "trade join incomplete"
                )
                break
            scan = trade_rows_for_order(page, venue_order_id)
            trade_refs.extend(scan.refs)
            if scan.uninterpretable_rows:
                uninterpretable_rows += scan.uninterpretable_rows
                self._log.warning(
                    f"resolver: activities page for venue order {redacted} "
                    f"carried {scan.uninterpretable_rows} uninterpretable "
                    f"trade row(s) (first_reason={scan.first_reason}); "
                    "trade join incomplete"
                )
                break
            page_min = page_min_create_ts_ns(page)
            if page_min is not None and (
                running_min_create_ts_ns is None or page_min < running_min_create_ts_ns
            ):
                running_min_create_ts_ns = page_min
            eof_value = page.get("eof")
            if "eof" in page and not isinstance(eof_value, bool):
                self._log.warning(
                    f"resolver: activities page for venue order {redacted} carried "
                    f"a non-bool eof field (keys={[k for k in page]}); "
                    "trade join incomplete"
                )
                break
            if eof_value is True:
                reached_eof = True
                break
            next_cursor = page.get("nextCursor")
            cursor = next_cursor if isinstance(next_cursor, str) and next_cursor else None
            if not cursor:
                break
        if _page_index > 0:
            # M-3 (r2 delta): a multi-page read is visible at INFO -- the
            # Step 2 probe is triggered when this line appears (or the
            # account's activity count reaches 80+, checked outside code).
            self._log.info(
                f"resolver: activities join for venue order {redacted} traversed "
                f"{_page_index + 1} pages"
            )
        self._log.debug(
            f"resolver: activities join for venue order {redacted} "
            f"complete={reached_eof} trade_count={len(trade_refs)} "
            f"page_min_create_ts_ns={running_min_create_ts_ns} created_ns={created_ns}"
        )
        if not trade_refs:
            return TradeJoin(
                complete=reached_eof, trade_count=0, qty=submit_chain.ZERO,
                last_trade_ts_ns=None, uninterpretable_rows=uninterpretable_rows,
            )
        total_qty = sum((ref.qty for ref in trade_refs), submit_chain.ZERO)
        last_ts = max(ref.create_ts_ns for ref in trade_refs)
        return TradeJoin(
            complete=reached_eof, trade_count=len(trade_refs), qty=total_qty,
            last_trade_ts_ns=last_ts, uninterpretable_rows=uninterpretable_rows,
        )

    async def _no_id_trade_activity(self, window_start_ns: int) -> NoIdTradeJoin | None:
        """AMBIG-LATCH-RESUME (plan r6 2.8.6): page ``/v1/portfolio/activities``
        (``SORT_ORDER_DESCENDING``) collecting every AGGRESSOR leg at or after
        ``window_start_ns``. Same page loop and cap as
        :meth:`_order_trade_activity`, which stays byte-identical and eof-only;
        the duplication is deliberate (``RESOLVER-PAGE-LOOP-DRY`` is recorded
        in the plan, not done here).

        ``complete`` is True on ``eof`` or on ordered early termination (see
        :class:`NoIdTradeJoin`). It is False -- never guessed -- on the page cap,
        a missing cursor, a malformed page, an uninterpretable row, or any
        ordering violation. ``None`` on a read failure. Awaits only
        ``self._private_read(PORTFOLIO_ACTIVITIES_PATH, ...)``.
        """
        cursor: str | None = None
        found: tuple[NoIdLeg, ...] = ()
        found_passive: tuple[bool, ...] = ()
        uninterpretable_rows = 0
        prev_row_ts_ns: int | None = None
        pages = 0
        for _page_index in range(_RESOLVER_ACTIVITY_MAX_PAGES):
            query: dict[str, object] = {
                "limit": _RESOLVER_ACTIVITY_PAGE_LIMIT,
                "sortOrder": _RESOLVER_ACTIVITY_SORT_ORDER,
            }
            if cursor:
                query["cursor"] = cursor
            try:
                page = await self._private_read(PORTFOLIO_ACTIVITIES_PATH, query)
            except Exception as exc:  # noqa: BLE001 - read failure stays AMBIGUOUS
                self._log.warning(
                    f"resolver: no-id activities read failed ({type(exc).__name__}); "
                    "scan incomplete"
                )
                return None
            if not isinstance(page, Mapping):
                self._log.warning(
                    "resolver: no-id activities page was not an object; scan incomplete"
                )
                return None
            if not isinstance(page.get("activities"), list):
                self._log.warning(
                    "resolver: no-id activities page carried a non-list activities field; "
                    "scan incomplete"
                )
                return NoIdTradeJoin(
                    False, False, found, found_passive, uninterpretable_rows, pages
                )
            pages = _page_index + 1
            scan = no_id_aggressor_legs(page, window_start_ns, prev_row_ts_ns)
            found = (*found, *scan.legs)
            found_passive = (*found_passive, *scan.passive_manual)
            uninterpretable_rows += scan.uninterpretable_rows
            prev_row_ts_ns = scan.last_row_ts_ns
            if scan.out_of_order:
                self._log.warning(
                    "resolver: no-id activities rows are not in non-increasing time order; "
                    "scan incomplete"
                )
                return NoIdTradeJoin(
                    False, True, found, found_passive, uninterpretable_rows, pages
                )
            if scan.uninterpretable_rows:
                self._log.warning(
                    f"resolver: no-id activities page carried {scan.uninterpretable_rows} "
                    "uninterpretable trade row(s); scan incomplete"
                )
                return NoIdTradeJoin(
                    False, False, found, found_passive, uninterpretable_rows, pages
                )
            eof_value = page.get("eof")
            if "eof" in page and not isinstance(eof_value, bool):
                self._log.warning(
                    "resolver: no-id activities page carried a non-bool eof field; "
                    "scan incomplete"
                )
                return NoIdTradeJoin(
                    False, False, found, found_passive, uninterpretable_rows, pages
                )
            if scan.passed_window_start or eof_value is True:
                return NoIdTradeJoin(
                    True, False, found, found_passive, uninterpretable_rows, pages
                )
            next_cursor = page.get("nextCursor")
            cursor = next_cursor if isinstance(next_cursor, str) and next_cursor else None
            if not cursor:
                break
        return NoIdTradeJoin(False, False, found, found_passive, uninterpretable_rows, pages)

    async def _resolve_no_id_intent(
        self,
        intent_id: str,
        created_ns: int,
        context: AmbiguousResolverContext | None,
        instrument: Any,
    ) -> None:
        """AMBIG-LATCH-RESUME (plan r6 2.8.4-2.8.6): resolve an OPEN AMBIGUOUS
        intent that has NO venue order id, from complete GET reads only.

        ``context`` is ``None`` in window-only mode (the pre-POST write failed,
        or the intent predates contexts). Reads go through the same
        ``self._private_read`` / ``self._read_open_orders`` seams as the with-id
        resolver; this body can reach no send path (T42). It never retires on
        create-time evidence, partial or contradictory reads: every failure
        leaves the intent AMBIGUOUS and re-checks in
        :data:`_NO_ID_RECHECK_INTERVAL_NS`.
        """
        if intent_id == self._post_in_flight_intent_id:
            self._log.debug(f"resolver: no-id intent {intent_id} POST in flight; skipping")
            return
        now_ns = self._clock.timestamp_ns()
        age_ns = now_ns - created_ns
        if age_ns < _RESOLVER_NO_ID_MIN_AGE_NS:
            return
        if (
            context is None
            and age_ns >= _STALE_INTENT_ALERT_AFTER_NS
            and intent_id not in self._resolver_stale_alerted_intent_ids
        ):
            self._resolver_stale_alerted_intent_ids = self._resolver_stale_alerted_intent_ids | {
                intent_id
            }
            self._resolver_stale_alert_details = {
                **self._resolver_stale_alert_details,
                intent_id: {
                    "severity": "CRITICAL",
                    "event": "open_intent_stale",
                    "site": "global",
                    "intent_id": intent_id,
                    "venue_order_id": "none",
                    "age_minutes": f"{age_ns // 60_000_000_000}",
                    "last_failure_kind": "none",
                    "no_context": "true",
                    "next": "no_id_resolver_window_only",
                },
            }
        if intent_id in self._no_id_next_check_ns and now_ns < self._no_id_next_check_ns[intent_id]:
            return
        recheck_ns = now_ns + _NO_ID_RECHECK_INTERVAL_NS
        # Set BEFORE any read: every later exit (a raise included, whether caught
        # here or by the dispatch wrapper) is bounded to one pass per interval.
        # Nothing above this line reads the venue.
        self._no_id_next_check_ns[intent_id] = recheck_ns
        echo = None if context is None else context.no_id_echo
        window_start_ns = created_ns - _NO_ID_WINDOW_BACKSKEW_NS
        window_end_ns = created_ns + _NO_ID_WINDOW_FORWARD_NS

        try:
            positions_payload = await self._private_read(PORTFOLIO_POSITIONS_PATH)
            positions = self._declared_positions(positions_payload)
        except Exception as exc:  # noqa: BLE001 - transient; never `_refuse`
            self._resolver_consecutive_failures += 1
            self._no_id_next_check_ns[intent_id] = recheck_ns
            self._log.warning(
                f"resolver: no-id positions read failed ({type(exc).__name__}); "
                "stays AMBIGUOUS"
            )
            return
        open_orders_ok = True
        try:
            open_orders = await self._read_open_orders()
        except Exception as exc:  # noqa: BLE001 - recorded as INCOMPLETE below
            open_orders = ()
            open_orders_ok = False
            self._log.warning(
                f"resolver: no-id open-orders read failed ({type(exc).__name__})"
            )
        join = await self._no_id_trade_activity(window_start_ns)
        if join is None:
            self._resolver_consecutive_failures += 1
            self._no_id_next_check_ns[intent_id] = recheck_ns
            self._log.warning(
                f"resolver: no-id intent {intent_id} activities read failed; stays AMBIGUOUS"
            )
            return
        self._resolver_consecutive_failures = 0

        known = {
            leg.order_id
            for leg in join.legs
            if self.client_order_id_for(VenueOrderId(leg.order_id)) is not None
        } | {
            order.venue_order_id
            for order in open_orders
            if self.client_order_id_for(VenueOrderId(order.venue_order_id)) is not None
        }
        verdict = classify_no_id_evidence(
            legs=join.legs,
            passive_manual=join.passive_manual,
            legs_complete=join.complete,
            out_of_order=join.out_of_order,
            open_orders=open_orders,
            open_orders_ok=open_orders_ok,
            known_order_ids=known,
            echo=echo,
            window_start_ns=window_start_ns,
            window_end_ns=window_end_ns,
        )
        outcome_kind: str = verdict.kind
        outcome_token = f"{verdict.token}"
        manual_reason = ""

        if outcome_kind == "NO_FILL":
            # The positions baseline, checked only when attribution is clean.
            try:
                if echo is not None and context is not None:
                    same_day_instrument = False
                    listed_instruments = 0
                    for candidate in self._instrument_provider.list_all():
                        listed_instruments += 1
                        if candidate.id == instrument.id:
                            same_day_instrument = True
                            break
                    if listed_instruments == 0:
                        # An empty provider proves nothing about holdings.
                        outcome_kind = "INCOMPLETE"
                        outcome_token = "holding_unreadable"
                    elif same_day_instrument:
                        slug = base_slug_of(instrument.id)
                        venue_leg_qty = _resolver_leg_holding_qty(
                            positions, slug, leg_of(instrument.id)
                        )
                        durable_qty = self._durable_net_qty(instrument.id)
                        if venue_leg_qty is None or durable_qty is None:
                            outcome_kind = "INCOMPLETE"
                            outcome_token = "holding_unreadable"
                        elif (
                            context.baseline_venue_net is not None
                            and context.baseline_durable_net is not None
                            and context.baseline_ts_ns is not None
                        ):
                            manual = manual_leg_net_effect(
                                legs=join.legs,
                                passive_manual=join.passive_manual,
                                slug=echo.slug,
                                after_ns=context.baseline_ts_ns,
                                now_ns=now_ns,
                                settle_ns=_RESOLVER_ZERO_FILL_MIN_AGE_NS,
                                straddle_ns=_NO_ID_MANUAL_STRADDLE_NS,
                            )
                            # Deliberately NOT `.get(...)`: a dict-method call here is a
                            # new, unpermitted callee under E0-NOSEND-RESOLVER.
                            slug_payload = positions[slug] if slug in positions else None  # noqa: SIM401
                            now_venue_net = "0"
                            if slug_payload is not None:
                                now_venue_net = (
                                    f"{slug_payload['netPosition']}"
                                    if isinstance(slug_payload, Mapping)
                                    and "netPosition" in slug_payload
                                    else "unknown"
                                )
                            if manual.status == "unsettled" or manual.value is None:
                                if manual.status == "unsettled":
                                    outcome_kind = "INCOMPLETE"
                                    outcome_token = "manual_leg_unsettled"
                                else:
                                    outcome_kind = "CONTRADICTION"
                                    outcome_token = "unexplained_holding_delta"
                                    manual_reason = f"{manual.reason}"
                            else:
                                consistent = holding_delta_consistent(
                                    base_venue_net=context.baseline_venue_net,
                                    now_venue_net=now_venue_net,
                                    base_durable_net=context.baseline_durable_net,
                                    now_durable_net=durable_qty,
                                    leg_sign=1 if echo.outcome_side == "OUTCOME_SIDE_YES" else -1,
                                    manual_net=manual.value,
                                )
                                if consistent is None:
                                    outcome_kind = "INCOMPLETE"
                                    outcome_token = "holding_unreadable"
                                elif consistent is False:
                                    outcome_kind = "CONTRADICTION"
                                    outcome_token = "unexplained_holding_delta"
                                elif manual.count:
                                    self._log.info(
                                        "resolver: no-id holding delta reconciled by "
                                        f"{manual.count} manual leg(s)"
                                    )
                        elif (
                            echo.action == "ORDER_ACTION_BUY" and venue_leg_qty > durable_qty
                        ) or (echo.action != "ORDER_ACTION_BUY" and venue_leg_qty < durable_qty):
                            outcome_kind = "CONTRADICTION"
                            outcome_token = "unexplained_holding"
                elif echo is None:
                    listed_instruments = 0
                    for candidate in self._instrument_provider.list_all():
                        listed_instruments += 1
                        venue_leg_qty = _resolver_leg_holding_qty(
                            positions, base_slug_of(candidate.id), leg_of(candidate.id)
                        )
                        durable_qty = self._durable_net_qty(candidate.id)
                        if venue_leg_qty is None or durable_qty is None:
                            outcome_kind = "INCOMPLETE"
                            outcome_token = "holding_unreadable"
                            break
                        if venue_leg_qty != durable_qty:
                            outcome_kind = "CONTRADICTION"
                            outcome_token = "unexplained_holding"
                            break
                    if listed_instruments == 0:
                        outcome_kind = "INCOMPLETE"
                        outcome_token = "holding_unreadable"
            except Exception as exc:  # noqa: BLE001 - see `_resolve_ambiguous_intents`
                self._note_resolver_error(intent_id, exc)
                return

        if outcome_kind == "CONTRADICTION":
            holding = outcome_token in {"unexplained_holding", "unexplained_holding_delta"}
            details = {
                "severity": "CRITICAL",
                "event": "resolver_evidence_contradiction",
                "site": "global",
                "intent_id": intent_id,
                "venue_order_id": "none",
                "no_id": "true",
                "reason": outcome_token,
                "next": (
                    "no_id_recheck_60s_manual_reconcile_then_launch_after_market_resolution"
                    if holding
                    else "no_id_recheck_60s"
                ),
            }
            if manual_reason:
                details = {**details, "manual_reconcile": manual_reason}
            self._resolver_contradiction_details = {
                **self._resolver_contradiction_details,
                intent_id: details,
            }
            self._no_id_next_check_ns[intent_id] = recheck_ns
            self._log.error(
                f"resolver: no-id intent {intent_id} evidence contradiction "
                f"({outcome_token}); stays AMBIGUOUS, re-check in 60s"
            )
            return
        if outcome_kind == "INCOMPLETE":
            self._no_id_next_check_ns[intent_id] = recheck_ns
            self._log.warning(
                f"resolver: no-id intent {intent_id} evidence incomplete "
                f"({outcome_token}); stays AMBIGUOUS, re-check in 60s"
            )
            return
        if outcome_kind == "ADOPT":
            if context is None:
                return
            self._no_id_next_check_ns[intent_id] = recheck_ns
            try:
                self._adopt_no_id_venue_order(context, f"{verdict.order_id}")
                cached = self._cache.order(ClientOrderId(context.client_order_id))
                if cached is not None and cached.status is OrderStatus.INITIALIZED:
                    self._generate_submitted(cached, now_ns)
            except Exception as exc:  # noqa: BLE001 - stays AMBIGUOUS, next pass retries
                self._note_resolver_error(intent_id, exc)
                return
            self._log.warning(
                f"resolver: no-id intent {intent_id} adopted venue order "
                f"{_redact_order_id(f'{verdict.order_id}')}; resolving on the with-id path"
            )
            return
        # NO_FILL with the baseline passing: the H2 analogue, set only by a
        # complete negative pass in THIS run.
        self._resolved_no_id_ts_ns[intent_id] = now_ns
        # A blocked or failing retirement leaves the intent OPEN: re-check on
        # the interval, never on every 5 s poll.
        self._no_id_next_check_ns[intent_id] = recheck_ns
        try:
            self._resolve_no_order(intent_id, context, now_ns, positions)
        except Exception as exc:  # noqa: BLE001 - see `_resolve_ambiguous_intents`
            self._note_resolver_error(intent_id, exc)

    def _adopt_no_id_venue_order(
        self, context: AmbiguousResolverContext, venue_order_id: str
    ) -> None:
        """Record the venue order id the attribution join found, in the ONE
        durable key the with-id resolver already reads. Nothing else changes, so
        the next pass takes the unchanged with-id path (GET by id, then
        accept-fill / terminal-zero). No ``try``: a store failure propagates to
        the caller's ``try`` and the intent stays AMBIGUOUS."""
        adopted = dataclasses.replace(context, venue_order_id=venue_order_id)
        self._store_set(f"{RESOLVER_CONTEXT_KEY_PREFIX}{adopted.intent_id}", adopted.to_bytes())

    def _resolve_no_order(
        self,
        intent_id: str,
        context: AmbiguousResolverContext | None,
        now_ns: int,
        positions: Mapping[str, Any] | None = None,
    ) -> None:
        """Retire a no-id intent that complete reads show neither an order nor a
        fill for. Mirrors :meth:`_resolve_terminal_zero` step for step.

        Refuses unless the running supervisor can decode the new retirement
        reason (``_no_id_retire_admitted``, fail-closed) and unless
        ``_resolved_no_id_ts_ns`` carries a complete negative pass from THIS run
        (the SAFETY H2 analogue). The AMBIGUOUS-refusal clear is the LAST step.
        """
        if not self._no_id_retire_admitted:
            already_blocked = intent_id in self._resolver_contradiction_details
            self._resolver_contradiction_details = {
                **self._resolver_contradiction_details,
                intent_id: {
                    "severity": "CRITICAL",
                    "event": "resolver_no_id_retire_blocked",
                    "site": "global",
                    "intent_id": intent_id,
                    "venue_order_id": "none",
                    "no_id": "true",
                    "reason": "supervisor_decode_marker_absent",
                    "next": "next_node_boot_rereads_supervisor_marker",
                },
            }
            if not already_blocked:
                self._log.error(
                    f"resolver: no-id retirement of intent {intent_id} is blocked -- the "
                    "running supervisor's decode marker does not list the reason; fail-closed"
                )
            return
        if intent_id not in self._resolved_no_id_ts_ns:
            self._log.error(
                f"resolver: refusing to retire intent {intent_id} -- no complete negative "
                "no-id pass was recorded for it in this run; SAFETY H2 fail-closed"
            )
            return
        current = self._latch.current_open()
        if current is None or current.intent_id != intent_id:
            self._ambiguous_bookings.pop(intent_id, None)
            return
        self._retire(intent_id, "RESOLVER_NO_ID_NO_FILL", now_ns)
        self._log.info(f"resolver: retired intent {intent_id} (RESOLVER_NO_ID_NO_FILL)")
        booking = self._ambiguous_bookings.pop(intent_id, None)
        if booking is not None:
            # Same process only: on restart the ledger died with the process.
            # WP-DR: skip the true-up for a prior-UTC-day booking (no spend).
            if booking.day != utc_day_for_ns(now_ns):
                self._log.info(
                    f"resolver: skipped prior-day ledger true-up for intent "
                    f"{intent_id}; booking day {booking.day}, "
                    f"today {utc_day_for_ns(now_ns)}"
                )
            else:
                self._ledger.true_up_booking(
                    booking, filled_cost_usd=submit_chain.ZERO, now_ns=now_ns
                )
            if (
                self._permit is not None
                and context is not None
                and restore_live_trading_budget(
                    permit=self._permit,
                    venue_order_id=f"noid:{intent_id}",
                    order_notional_usd=context.notional_usd,
                )
            ):
                self._mark_budget_restored(f"noid:{intent_id}")
        else:
            self._log.info("resolver: cross-process no-id no-fill; permit restore skipped")
        if positions is not None:
            self._write_startup_position_evidence(
                now_ns=now_ns,
                eof_complete=True,
                position_read_refused=False,
                raw_positions=positions,
            )
        if context is not None:
            cached = self._cache.order(ClientOrderId(context.client_order_id))
            if cached is not None and cached.status is OrderStatus.INITIALIZED:
                # (INITIALIZED, REJECTED) is the legal edge the create path's
                # REJECT branch already uses.
                self.generate_order_rejected(
                    strategy_id=StrategyId(context.strategy_id),
                    instrument_id=InstrumentId.from_str(context.instrument_id),
                    client_order_id=ClientOrderId(context.client_order_id),
                    reason=_NO_ID_NO_FILL_REASON,
                    ts_event=now_ns,
                )
        # LAST: the AMBIGUOUS refusal has no subject left (same block as the
        # zero-fill and accept-fill clears). Any raise above keeps it.
        if self._latch.current_open() is None:
            kept_refusals = [
                refusal
                for refusal in self._trading_refusals
                if refusal.reason != submit_chain.AMBIGUOUS_REASON
            ]
            if len(kept_refusals) != len(self._trading_refusals):
                self._trading_refusals = kept_refusals
                self._ambiguous_refusal_clears += 1
                self._log.info(
                    f"resolver: cleared the AMBIGUOUS trading refusal "
                    f"({submit_chain.AMBIGUOUS_REASON!r}) on no-id retirement of "
                    f"intent {intent_id}"
                )


    def _durable_net_qty(self, instrument_id: InstrumentId) -> Decimal | None:
        """EDGE-2 slice D (§4 AC4(e) baseline): THIS instrument's own
        durable net quantity -- every recorded fill's ``cumulative_qty``,
        signed per :data:`_RECORD_SIGNS` (entry positive, exit negative) and
        summed. The SAME per-instrument ``FILL_INDEX_KEY_PREFIX`` walk
        :meth:`_seed_spend_from_durable_fills` uses, for ONE instrument.

        Returns ``None`` -- undetermined, never a synonym for zero -- on an
        unreadable index, an index naming a record this store cannot
        produce, a malformed record, or an unrecognised ``order_side``:
        AC4(e) must never retire a zero-fill on evidence it could not
        actually read. Like :meth:`_resolver_fill_order_unknown`, this is a
        read-only classifier listed as a resolver CALLEE only, never as a
        scanned resolver action site of its own.
        """
        index_key = f"{FILL_INDEX_KEY_PREFIX}{instrument_id}"
        indexed = self._read_fill_index(index_key)
        if indexed is None:
            return None
        net = Decimal(0)
        for venue_order_id in indexed:
            raw = self._store_get(f"{FILL_KEY_PREFIX}{venue_order_id}")
            if raw is None:
                return None
            try:
                record = DurableFillRecord.from_bytes(raw)
            except ExecutionReportMappingError:
                return None
            if record.order_side not in _RECORD_SIGNS:
                return None
            net += _RECORD_SIGNS[record.order_side] * record.cumulative_qty
        return net

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

        FU-8 r2/r2.1: ``self._boot_snapshot_started`` is set True as the
        FIRST statement below, before any ``await``. A resolver fill that
        races this exact pass -- observing the flag already ``True`` while
        THIS pass has not yet actually read the position that would explain
        it -- latches ``RESOLVER_FILL_NOT_BOOKED`` even though this same
        pass would, a moment later, have accounted for it. That is a false
        ALERT, never silence (plan r2 "Race during the mass status") -- the
        conservative direction the resolver is sync (``_resolve_ambiguous_
        intents``) has no ``await`` between ``record_fill`` and this check.
        """
        self._boot_snapshot_started = True
        self.reconciliation_active = True
        # AUD-13b: one memoised positions read per pass, shared by all three
        # generators so the durable gating and the position report can never
        # see two different books. Cleared again in the `finally` below.
        self._reconciliation_pass = None
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
            self._reconciliation_pass = None
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
        """One terminal order report per durable fill record the VENUE gates in.

        AUD-13b (plan §6; field map: evidence pack §5). The venue ``Order``
        carries no client-order-id field (``reports.py`` module docstring item
        2), so an order enumerated from the venue alone can only reconcile as
        ``EXTERNAL``. Breezy's durable fill record is the only place the
        client-order-id <-> venue-id binding exists -- but it is NOT the
        authority on whether the position is still open: a record is reported
        **iff a fresh venue positions read currently shows an open position
        for its (leg-resolved) instrument**. The venue decides *whether*; the
        record supplies *which order, which side, at what price*.

        Lands TOGETHER with :meth:`generate_fill_reports`: native
        reconciliation looks a fill up BY the venue order id an order report
        names (``live/execution_engine.py:1880-1881``); there is no fill-only
        loop. Every refusal is named and latched
        (:attr:`reconciliation_refusals`), never a bare ``[]``. A resting
        order has no durable fill record and so is never reported here
        (RESTING_BID_HUNT Rev 2 section 4.3 stands); ``open_only`` asks for
        open orders, and every durable report is terminal, so it gets none.

        Never raises: a failed read is captured and latched.
        """
        if getattr(command, "open_only", False):
            return []
        durable = self._reconciliation_pass
        if durable is None:
            payload: Any = None
            error: Exception | None = None
            try:
                payload = await self._private_read(PORTFOLIO_POSITIONS_PATH)
            except Exception as exc:  # noqa: BLE001 - latched as positions_read_failed
                error = exc
            durable = self._durable_reconciliation_pass(payload, error)
        return self._reports_for_command(durable.order_reports, command)

    async def generate_fill_reports(
        self,
        command: GenerateFillReports | None = None,
    ) -> list[FillReport]:
        """One ``FillReport`` per order report above, from the same pass.

        ``commission`` is ruling R-1 = O4: the venue-attested fee when the
        record carries one (``feeSource=RECORDED``), else the taker fee
        modelled with theta AS OF the fill (``MODELLED_AT_FILL_TIME``), else
        -- the AMBIGUOUS 2026-09-17 window or an unpinned date -- the whole
        instrument is REFUSED (``fee_coefficient_ambiguous``), never defaulted.
        ``trade_id`` is the record's, else the resolver's ``GET-<venue order
        id>`` form, byte-equal to what a same-process resolver fill used (F5).
        """
        durable = self._reconciliation_pass
        if durable is None:
            payload: Any = None
            error: Exception | None = None
            try:
                payload = await self._private_read(PORTFOLIO_POSITIONS_PATH)
            except Exception as exc:  # noqa: BLE001 - latched as positions_read_failed
                error = exc
            durable = self._durable_reconciliation_pass(payload, error)
        reports = self._reports_for_command(durable.fill_reports, command)
        venue_order_id = getattr(command, "venue_order_id", None)
        if venue_order_id is not None:
            reports = [r for r in reports if r.venue_order_id == venue_order_id]
        return reports

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
        durable = self._reconciliation_pass
        mapped: tuple[PositionStatusReport, ...] | None = None
        try:
            if durable is not None:
                # AUD-13b: this pass's memoised read. A failed one re-enters
                # the SAME refusal below, byte-for-byte as before.
                if durable.error is not None:
                    raise durable.error
                mapped = durable.position_reports
            else:
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

        if mapped is None:
            mapped, _ = self._map_positions(positions)
        return [
            report
            for report in mapped
            if instrument_filter is None or report.instrument_id == instrument_filter
        ]

    def _map_positions(
        self,
        positions: Mapping[str, Any],
    ) -> tuple[tuple[PositionStatusReport, ...], tuple[str, ...]]:
        """Map every venue position, in slug order, ONCE.

        Returns the forwarded reports and, per slug, the outcome
        :meth:`_map_position` recorded (``open`` / ``gated_out`` /
        ``instrument_absent`` / ``unparseable``).
        """
        reports: list[PositionStatusReport] = []
        outcomes: list[str] = []
        for slug in sorted(positions):
            self._position_map_outcome = _MAP_UNPARSEABLE
            report = self._map_position(slug, positions[slug])
            outcomes.append(self._position_map_outcome)
            if report is not None:
                reports.append(report)
        return tuple(reports), tuple(outcomes)

    # -- AUD-13b: durable-record reconciliation ------------------------------

    def _reports_for_command(self, reports: tuple[Any, ...], command: Any) -> list[Any]:
        instrument_id = getattr(command, "instrument_id", None)
        return [r for r in reports if instrument_id is None or r.instrument_id == instrument_id]

    def _durable_reconciliation_pass(
        self,
        payload: Any,
        error: Exception | None,
    ) -> _ReconciliationPass:
        """Map the positions read once, gate the durable records on it, and
        build both report lists. Memoised for the rest of a mass-status pass.

        Fail-closed walks (plan §6), each NAMED and latched:

        * the read failed, or the payload is unparseable in whole OR IN PART
          -> no durable report at all, ``positions_read_failed``. Partial
          gating is forbidden: a dropped row would turn "the venue says we
          hold this" into "it does not", the fail-OPEN direction;
        * the venue holds an instrument its records do not explain (no record,
          a net-quantity mismatch, an unknown side, a venue-id map row naming
          a DIFFERENT client order id) -> nothing for THAT instrument,
          ``record_venue_disagreement``. A MISSING map row is not a
          disagreement (evidence F7: pre-A1 records have none);
        * a record whose fee cannot be pinned to its fill time -> nothing for
          that instrument, ``fee_coefficient_ambiguous``.

        An instrument absent from the Nautilus cache is skipped by the engine
        anyway (``live/execution_engine.py:3056-3062``); it is COUNTED as its
        own field, never folded into ``gated_out`` (evidence F8).
        """
        counts: dict[str, int] = dict.fromkeys(_RECONCILIATION_COUNT_FIELDS, 0)
        position_reports: tuple[PositionStatusReport, ...] = ()
        order_reports: list[OrderStatusReport] = []
        fill_reports: list[FillReport] = []
        fee_sources: dict[str, str] = {}
        outcomes: tuple[str, ...] = ()
        if error is None:
            try:
                positions = self._declared_positions(payload)
                position_reports, outcomes = self._map_positions(positions)
            except Exception as exc:  # noqa: BLE001 - a foreign shape OR a mapping
                # defect is a failed read either way (silent-failure review
                # finding 1): `_map_positions` must run INSIDE this try, not
                # in an `else:` -- an `else:` clause is not covered by the
                # `try:` block's own `except`, so a mapping defect used to
                # escape uncaught.
                error = exc
        counts["gated_out"] = outcomes.count(_MAP_GATED_OUT)
        # Finding 4 (accepted as-is, LOW): `instrument_absent` is counted for
        # visibility only and deliberately never latched -- the engine
        # already no-ops on an uncached instrument natively
        # (``execution_engine.py:3056-3062``), so this is not a Breezy
        # refusal, and `_durable_reports_for_position` already logs a
        # WARNING for each occurrence.
        counts["instrument_absent"] = outcomes.count(_MAP_INSTRUMENT_ABSENT)
        if error is not None or _MAP_UNPARSEABLE in outcomes:
            self._latch_reconciliation_refusal(POSITIONS_READ_FAILED, "")
            counts[f"refusals_{POSITIONS_READ_FAILED}"] = 1
        else:
            for position in position_reports:
                try:
                    self._durable_reports_for_position(
                        position, counts, order_reports, fill_reports, fee_sources
                    )
                except Exception as exc:  # noqa: BLE001 - finding 1: NOTHING from a
                    # per-position build may reach the native handler, and one
                    # bad position must not drop every other position's reports.
                    self._latch_reconciliation_refusal(
                        DURABLE_REPORTS_BUILD_FAILED, str(position.instrument_id)
                    )
                    counts[f"refusals_{DURABLE_REPORTS_BUILD_FAILED}"] += 1
                    # Review fix (LOW): `_latch_reconciliation_refusal` already
                    # emits the deduped WARNING every alerting caller sees; a
                    # second WARNING here would double-log on EVERY pass this
                    # position keeps failing on (the latch WARNs once ever, this
                    # loop runs every pass). The exception detail the latch's
                    # fixed-enum log does not carry stays reachable at DEBUG.
                    self._log.debug(
                        "durable reconciliation: building reports for "
                        f"{position.instrument_id} raised ({type(exc).__name__}: {exc}); "
                        "nothing is reported for it; other positions are unaffected"
                    )
        counts["order_reports"] = len(order_reports)
        counts["fill_reports"] = len(fill_reports)
        counts["refusals"] = sum(
            counts[f"refusals_{latch}"] for latch in _BOOT_PASS_REFUSAL_LATCHES
        )
        self._reconciliation_counts = counts
        self._reconciled_fee_sources = fee_sources
        self._log.info(format_reconciliation_counts_line(counts))
        durable = _ReconciliationPass(
            error=error,
            position_reports=position_reports,
            order_reports=tuple(order_reports),
            fill_reports=tuple(fill_reports),
        )
        if self.reconciliation_active:
            self._reconciliation_pass = durable
        return durable

    def _durable_reports_for_position(
        self,
        position: PositionStatusReport,
        counts: dict[str, int],
        order_reports: list[OrderStatusReport],
        fill_reports: list[FillReport],
        fee_sources: dict[str, str],
    ) -> None:
        """Append the reports for ONE venue-open instrument, or latch why not.

        ``position.instrument_id`` is ``_map_position``'s LEG-RESOLVED id, so a
        NO-leg holding gates its ``^no`` records -- never a YES-leg re-lookup
        of the slug (coordinator decision 1; evidence F5).
        """
        instrument_id = position.instrument_id
        instrument = self._cache.instrument(instrument_id)
        if instrument is None:
            counts["instrument_absent"] += 1
            self._log.warning(
                f"durable reconciliation: {instrument_id} is held at the venue but "
                "not in the cache; the engine would skip its reports, so none are built"
            )
            return
        records = sorted(
            self.fill_records_for(instrument_id),
            key=lambda record: (record.ts_event, record.order_side != LONG_ONLY_SIDE),
        )
        counts["records_considered"] += len(records)
        if not self._records_explain_position(records, position):
            self._latch_reconciliation_refusal(RECORD_VENUE_DISAGREEMENT, str(instrument_id))
            counts[f"refusals_{RECORD_VENUE_DISAGREEMENT}"] += 1
            return
        built: list[tuple[OrderStatusReport, FillReport, str]] = []
        for record in records:
            try:
                commission, fee_source = self._reconciled_commission(record)
            except (ArithmeticError, ValueError) as exc:
                # Finding 2: a corrupt record (a price outside [0, 1] from bad
                # cumulative_cost/cumulative_qty, or a division by a zero
                # quantity) reaches `taker_fee_at_fill`'s own validation.
                # `taker_fee_at_fill` is left unchanged; fold the raise into
                # the SAME fee_coefficient_ambiguous handling below rather
                # than let it escape.
                self._log.warning(
                    "durable reconciliation: fee computation for "
                    f"{_redact_order_id(record.venue_order_id)} raised "
                    f"({type(exc).__name__}: {exc}); treated as fee_coefficient_ambiguous"
                )
                commission, fee_source = None, ""
            if commission is None:
                self._latch_reconciliation_refusal(
                    FEE_COEFFICIENT_AMBIGUOUS,
                    _redact_order_id(record.venue_order_id),
                    ts_event_bucket=fee_schedule_bucket(record.ts_event),
                )
                counts[f"refusals_{FEE_COEFFICIENT_AMBIGUOUS}"] += 1
                return
            built.append((*self._reports_for_record(record, instrument, commission), fee_source))
        for order_report, fill_report, fee_source in built:
            order_reports.append(order_report)
            fill_reports.append(fill_report)
            fee_sources[str(order_report.venue_order_id)] = fee_source

    def _records_explain_position(
        self,
        records: list[DurableFillRecord],
        position: PositionStatusReport,
    ) -> bool:
        """``True`` iff these records are exactly Breezy's account of the
        venue's position: at least one, every side known, the signed net
        quantity equal to the venue's, and no venue-id map row naming a
        different client order id."""
        if not records:
            return False
        if any(record.order_side not in _RECORD_SIGNS for record in records):
            return False
        net_qty = sum(
            (_RECORD_SIGNS[record.order_side] * record.cumulative_qty for record in records),
            Decimal(0),
        )
        if net_qty != position.quantity.as_decimal():
            return False
        for record in records:
            if record.cumulative_qty <= 0 or record.cumulative_cost <= 0:
                return False
            mapped = self.client_order_id_for(VenueOrderId(record.venue_order_id))
            if mapped is not None and mapped.value != record.client_order_id:
                self._log.warning(
                    "durable reconciliation: venue order "
                    f"{_redact_order_id(record.venue_order_id)} maps to "
                    f"{mapped.value} but its fill record names "
                    f"{record.client_order_id}; neither is picked"
                )
                return False
        return True

    @staticmethod
    def _reconciled_commission(record: DurableFillRecord) -> tuple[Money | None, str]:
        """Ruling R-1 = O4, re-derived from the record (never its stored
        ``feeSource``): the venue-attested fee, else the taker fee modelled
        with theta as of the fill, else ``None`` (refuse)."""
        fee_source = fee_source_for(
            fee_reconciled=record.fee_reconciled, venue_fee_raw=record.venue_fee_raw
        )
        if fee_source == FEE_SOURCE_RECORDED:
            return Money(record.cumulative_fee, USD), fee_source
        # G5 / evidence F3: a RESOLVER-path record's `ts_event` is its
        # DISCOVERY time, not the venue's fill time (which is unknown; it lies
        # in [intent created, ts_event]). It is used as the plan says, as an
        # upper bound -- exact only for create-path records. A resolver record
        # whose true interval straddled a schedule boundary cannot be bucketed
        # from `ts_event` alone; no fill time is invented here.
        commission = taker_fee_at_fill(
            quantity=record.cumulative_qty,
            price=record.cumulative_cost / record.cumulative_qty,
            ts_event_ns=record.ts_event,
            fee_coefficient_at_fill=record.fee_coefficient_at_fill,
        )
        return commission, fee_source

    def _reports_for_record(
        self,
        record: DurableFillRecord,
        instrument: Instrument,
        commission: Money,
    ) -> tuple[OrderStatusReport, FillReport]:
        """The native report pair for one record (evidence pack §5 field map).

        ``order_side`` is the RECORD's (ruling finding 8), never a hardcoded
        BUY: a SELL exit record must reconcile to a SELL. ``quantity`` is the
        original order size, else -- a legacy record -- the terminal filled
        portion (L-2). An IOC whose remainder the venue cancelled is reported
        ``CANCELED`` with its fill, never ``FILLED`` with ``filled < quantity``.
        """
        ts_init = self._clock.timestamp_ns()
        filled = record.cumulative_qty
        ordered = record.order_qty if record.order_qty is not None else filled
        avg_px = record.cumulative_cost / filled
        last_px = instrument.make_price(avg_px)
        order_side = OrderSide[record.order_side]
        venue_order_id = VenueOrderId(record.venue_order_id)
        client_order_id = ClientOrderId(record.client_order_id)
        trade_id = (
            TradeId(record.trade_id)
            if record.trade_id is not None
            else _synthetic_get_fill_trade_id(record.venue_order_id)
        )
        order_report = OrderStatusReport(
            account_id=self._issued_account_id,
            instrument_id=instrument.id,
            venue_order_id=venue_order_id,
            order_side=order_side,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.IOC,
            order_status=OrderStatus.FILLED if ordered == filled else OrderStatus.CANCELED,
            quantity=instrument.make_qty(ordered),
            filled_qty=instrument.make_qty(filled),
            report_id=UUID4(),
            ts_accepted=record.ts_event,
            ts_last=record.ts_event,
            ts_init=ts_init,
            client_order_id=client_order_id,
            price=last_px,
            avg_px=avg_px,
        )
        fill_report = FillReport(
            account_id=self._issued_account_id,
            instrument_id=instrument.id,
            venue_order_id=venue_order_id,
            trade_id=trade_id,
            order_side=order_side,
            last_qty=instrument.make_qty(filled),
            last_px=last_px,
            commission=commission,
            liquidity_side=LiquiditySide.TAKER,
            report_id=UUID4(),
            ts_event=record.ts_event,
            ts_init=ts_init,
            avg_px=avg_px,
            client_order_id=client_order_id,
        )
        return order_report, fill_report

    def _resolver_fill_order_unknown(
        self,
        context: AmbiguousResolverContext,
        report: Any,
    ) -> bool:
        """FU-8 r2/r2.1 (option A): whether ``_resolve_accept_fill``'s fill
        must NOT be booked at runtime -- ``True`` skips ``generate_order_
        filled`` entirely; ``False`` means proceed exactly as before this
        change.

        ``False`` (same session): ``self._cache.order(...)`` finds the
        order this run itself submitted -- byte-identical to HEAD (AC1).

        ``True`` (cross-session -- the order is unknown to this run's
        cache), told apart by ``self._boot_snapshot_started`` (set as the
        first statement of ``generate_mass_status``):

        * **T1, before the boot snapshot.** The startup mass status has not
          run yet; AUD-13b's durable reconciliation books this fill natively
          moments later, with full attribution (plan r2 boot trace). Nothing
          is latched -- one INFO line only, so the deferral is visible.
        * **T2, after the boot snapshot.** The boot pass already ran and
          either accounted for the position under a synthetic order (venue
          still held -- qty right, attribution coarse) or found nothing to
          hold (settled/closed). Booking here would double the position
          (L-47) or open a phantom long on a settled market (L-18) instead.
          Latches the NAMED refusal ``RESOLVER_FILL_NOT_BOOKED`` (subject
          ``_redact_order_id(context.venue_order_id)``) and logs one ERROR
          line with the instrument, the fill qty and Nautilus's own net qty
          (``positions_open``) -- log only, no branching on those numbers.

        This latch is INFORMATIONAL, not a control: it changes no booking
        decision and gates no order. Runtime delivery for it (and every
        other runtime latch) is a pre-existing, cross-cutting gap tracked
        separately as FU-8b -- the position itself stays visible either way,
        and the T2-held case is already alerted at boot via
        ``RECORD_VENUE_DISAGREEMENT``. Depends on ``generate_mass_status``
        staying boot-only, pinned by
        ``test_the_settlement_landmine_stays_disarmed_only_while_the_
        position_check_is_off`` and
        ``test_starts_no_continuous_reconciliation_polling``. Takes no
        sender or transport parameter and never references
        ``self._order_sender`` -- this reads only the already-reconciled
        ``self._cache``, never the venue.
        """
        if self._cache.order(ClientOrderId(context.client_order_id)) is not None:
            return False
        redacted = _redact_order_id(context.venue_order_id)
        if not self._boot_snapshot_started:
            self._log.info(
                f"resolver: fill for venue order {redacted} on "
                f"{context.instrument_id} arrived before the boot snapshot; "
                "deferred to boot durable reconciliation (AUD-13b) -- "
                "nothing booked here, nothing latched"
            )
            return True
        positions = self._cache.positions_open(
            instrument_id=InstrumentId.from_str(context.instrument_id),
        )
        net_qty = sum((position.signed_decimal_qty() for position in positions), Decimal(0))
        self._log.error(
            f"resolver: fill for venue order {redacted} on {context.instrument_id} "
            f"arrived after the boot snapshot -- fill_qty="
            f"{report.filled_qty.as_decimal()} nautilus_net_qty={net_qty}; NOT "
            "booked at runtime (FU-8 option A)"
        )
        self._latch_reconciliation_refusal(RESOLVER_FILL_NOT_BOOKED, redacted)
        return True

    def _latch_reconciliation_refusal(self, latch: str, subject: str, **extra: str) -> None:
        """Latch one NAMED durable-reconciliation refusal (deduped by latch and
        subject) and log it at WARNING. The ``detail`` is a fixed enum."""
        key = (latch, subject)
        if key in self._reconciliation_refusal_latches:
            return
        payload = {
            "event": RECONCILIATION_REFUSAL_EVENT,
            "detail": _RECONCILIATION_REFUSAL_DETAILS[latch],
            "latch": latch,
            "subject": subject,
            **extra,
        }
        self._reconciliation_refusal_latches = {
            **self._reconciliation_refusal_latches,
            key: payload,
        }
        self._log.warning(
            f"durable reconciliation refused: {latch} subject={subject or '-'}; "
            "nothing is reported for it and the engine falls back to inference"
        )

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

    @staticmethod
    def declared_positions(payload: Mapping[str, Any]) -> Mapping[str, Any]:
        """Public delegation to :meth:`_declared_positions` (AUD-02b P3(i)):
        the node's OWN positions-page parser, exposed so a build-side caller
        outside this class (``breezy.strategy.current_rung_hold.set_family_halt_cli``)
        reuses it rather than reaching through the private name. Pure
        delegation, verbatim -- every in-class call site keeps calling
        ``_declared_positions`` unchanged, and this stays a bare
        ``@staticmethod``: no instance, no connection, no I/O.
        """
        return PolymarketUSExecutionClient._declared_positions(payload)

    def _map_position(self, slug: str, payload: Any) -> PositionStatusReport | None:
        """One venue position -> one report, or ``None`` plus a refusal.

        ``slug`` is the DICT KEY of ``GetUserPositionsResponse.positions`` and
        is the only authoritative market identifier a ``UserPosition`` carries,
        which is why R-3 makes it a required keyword.
        """
        instrument = self._find_instrument(slug)
        if instrument is None:
            self._position_map_outcome = _MAP_INSTRUMENT_ABSENT
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

        # `mapped.leg` names which outcome the exposure belongs to; `reports.py`
        # is I/O-free (module docstring) and never resolves the real NO-leg
        # instrument, so this is the one place that does -- reusing
        # `_find_instrument`'s existing provider-then-cache lookup, applied to
        # the NO-leg id (`no_leg_instrument_id`, the same bijection
        # `parsing.parse_binary_option_pair` already builds every NO-leg
        # instrument through), never a new one.
        resolved_instrument_id = mapped.report.instrument_id
        if mapped.leg == "no":
            no_instrument = self._find_instrument(slug, leg="no")
            if no_instrument is None:
                self._position_map_outcome = _MAP_INSTRUMENT_ABSENT
                self._refuse(
                    f"the venue reports a NO-leg position in market {slug!r}, for "
                    "which no NO-leg instrument is loaded; it cannot be mapped, "
                    "priced or netted"
                )
                return None
            resolved_instrument_id = no_instrument.id

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
            self._position_map_outcome = _MAP_GATED_OUT
            return None

        if report.position_side == PositionSide.FLAT:
            # Deliberately not forwarded: see the module docstring's landmine
            # note. A FLAT report on a held binary books the close at the OPEN
            # price and realizes exactly zero.
            self._position_map_outcome = _MAP_GATED_OUT
            return None

        if report.position_side != PositionSide.LONG:
            self._refuse(
                f"the venue reports a non-long position in {report.instrument_id}; "
                "Breezy is long-only and cannot attribute it"
            )
            return None

        avg_px_open = self._entry_price(resolved_instrument_id, report.quantity, payload)
        self._position_map_outcome = _MAP_OPEN

        return PositionStatusReport(
            account_id=report.account_id,
            instrument_id=resolved_instrument_id,
            position_side=report.position_side,
            quantity=report.quantity,
            report_id=report.id,
            ts_last=report.ts_last,
            ts_init=report.ts_init,
            venue_position_id=report.venue_position_id,
            avg_px_open=avg_px_open,
        )

    def _find_instrument(self, slug: str, *, leg: Leg = "yes") -> Instrument | None:
        """Resolve a market slug to a loaded instrument, provider first.

        ``leg`` selects which of the market's two instruments to resolve:
        the YES id (:func:`slug_to_instrument_id`, the default -- unchanged
        from before ``leg`` existed) or the NO id (:func:`no_leg_instrument_id`)
        -- the same bijections :mod:`parsing` already uses to build both legs
        at discovery time. Never a new one.
        """
        try:
            instrument_id = (
                no_leg_instrument_id(slug) if leg == "no" else slug_to_instrument_id(slug)
            )
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

    def record_fill(
        self,
        record: DurableFillRecord,
        *,
        fill_time_instrument: Instrument | None = None,
        intent_fingerprint: str | None = None,
        intent_created_ns: int | None = None,
    ) -> None:
        """Persist one venue order's cumulative totals and index it.

        AUD-13b (ruling R-1 = O4 mechanism (a)): the two fill write sites pass
        ``fill_time_instrument`` -- the ``Instrument`` in hand when the fill
        is recorded -- and the record is stamped with that instrument's taker
        theta (:func:`~breezy.adapters.polymarket_us.fees.taker_fee_coefficient_of`,
        ``None`` if its schedule is unusable) and the O4 ``feeSource``
        (:func:`fee_source_for`). Done HERE, in the already-permitted inert
        store write, so neither guarded write site gains a callee. Without it
        (every direct caller) the record is persisted exactly as given.

        Written before the ``OrderFilled`` is published (R-7), so a crash
        between the venue's answer and the event still leaves the evidence on
        disk. A rewrite at the same ``venue_order_id`` is a cumulative UPDATE,
        not a second fill -- see :class:`DurableFillRecord`.

        The index is read FIRST and an unreadable one RAISES. Overwriting it
        would replace ids we could not see with the single one in hand,
        destroying every surviving record's reachability -- the store has no
        prefix scan, so an id absent from the index is an id that no longer
        exists as far as pricing is concerned.

        SP-3r: when both ``intent_fingerprint`` and ``intent_created_ns`` are
        given (both call sites pass the armed/open ``SubmitIntent``'s own
        fields), a day-scoped ``FILL_BY_FINGERPRINT_KEY_PREFIX`` entry is
        ALSO written here -- the last write in this method, i.e. strictly
        after the fill record and its instrument index above, and therefore
        still strictly before either caller's own ``_retire``. Done HERE
        (this method's body is not one of E0-NOSEND's scanned coroutines)
        rather than as a separate call from the scanned create/resolver
        coroutines, which may call only their own fixed allowlists. Any
        failure here (like any failure above) propagates to the caller's
        identical ``_FILL_WRITE_FAILED`` refusal path -- an index write
        failure never leaves the fill record written without it silently.
        """
        if fill_time_instrument is not None:
            record = dataclasses.replace(
                record,
                fee_coefficient_at_fill=taker_fee_coefficient_of(fill_time_instrument),
                fee_source=fee_source_for(
                    fee_reconciled=record.fee_reconciled,
                    venue_fee_raw=record.venue_fee_raw,
                ),
            )
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
        # AC6b/G4 (EDGE-2 plan r3, D9): a day-scoped candidate index, keyed
        # by `record.ts_event`'s OWN UTC day -- never `intent_created_ns` --
        # so the boot seed can reach a fill recorded under a PAST-DAY
        # instrument the instrument provider never loaded (the past-day
        # loader populates only `self._cache`). Same three-way
        # `_read_fill_index` read and fail-closed raise as the per-
        # instrument index above: overwriting an unreadable day index would
        # orphan every OTHER id it still names for that day.
        day_index_key = f"{FILL_BY_DAY_KEY_PREFIX}{utc_day_for_ns(record.ts_event).isoformat()}"
        day_indexed = self._read_fill_index(day_index_key)
        if day_indexed is None:
            raise PolymarketUSError(
                f"the durable day-fill index at {day_index_key!r} could not be "
                "read, so it cannot be safely rewritten: overwriting it would "
                "orphan every fill record it still names"
            )
        if record.venue_order_id not in day_indexed:
            day_indexed.append(record.venue_order_id)
            self._store_set(day_index_key, json.dumps(day_indexed).encode("utf-8"))
        if intent_fingerprint is not None and intent_created_ns is not None:
            day = utc_day_for_ns(intent_created_ns).isoformat()
            self._store_set(
                f"{FILL_BY_FINGERPRINT_KEY_PREFIX}{day}:{intent_fingerprint}",
                record.venue_order_id.encode("utf-8"),
            )

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

    def _mark_budget_exhausted(self, now_ns: int) -> None:
        """Durably mark today's UTC day as spend-exhausted (D1: shielded).

        Called from the two typed-exception arms in ``_submit_order``, both
        of which mean the operator's dollar ceiling was reached for the day.
        A write failure here is logged and swallowed -- it must NEVER
        prevent the caller's unconditional ``self._deny(...)`` from running;
        the marker is a durable convenience for the strategy's re-arm gate,
        never a precondition for denying an order that must be denied
        regardless. Logs the ``budget stop`` line at most once per process
        per UTC day. Never logs a dollar figure or either control's name.
        """
        day = utc_day_for_ns(now_ns).isoformat()
        try:
            self._store_set(f"{BUDGET_EXHAUSTED_KEY_PREFIX}{day}", b"1")
        except Exception as exc:  # noqa: BLE001 - a marker write must never crash the deny path
            self._log.error(
                f"budget stop marker write failed for {day}: "
                f"{exc.__class__.__name__}: {exc}"
            )
            return
        if day not in self._budget_marker_written:
            self._budget_marker_written.add(day)
            self._log.warning(
                f"budget stop: the day's spend ceiling is reached for {day}; "
                "no further orders will be authorized today"
            )

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
            open_orders_read_refused=self._open_orders_read_refused,
            open_orders=tuple(
                StartupOpenOrderSnapshot(
                    venue_order_id=o.venue_order_id,
                    market_slug=o.market_slug,
                    state=o.state,
                )
                for o in self._open_orders
            ),
        )
        self._store_set(STARTUP_EVIDENCE_KEY, evidence.to_bytes())
        # R-9a (HF-4 rev2): the single writer of the watermark the resolver's
        # refresh reads against -- a plain attribute assignment, invisible
        # to `find_exec_resolver_violations` (walks `ast.Call` only).
        self._last_evidence_write_ns = now_ns
        # R-7-IMPL (RULING R-7): the only place a create-path accept-fill's
        # `PositionReportingLag` can be confirmed -- an eof-complete,
        # non-refused positions read, exactly like the one just written
        # above. Never runs on a refused or non-eof-complete page (matching
        # neither confirms nor denies a LONG). `_match_position_lag` sits
        # outside both the order-lifecycle and resolver callee allowlists --
        # a pre-existing pattern this plan extends (security review, plan
        # r1.1), compensated by the order-sender reference ban in
        # `tests/unit/test_execution_egress_firewall_guard.py` -- so the
        # broad `except` here is required: any failure inside it must be
        # contained rather than propagate into a caller (`_connect`, the
        # resolver's age-gated refresh) that expects this method never to
        # raise. Evidence bytes above are unaffected either way -- they are
        # already durable by the time this runs.
        if eof_complete and not position_read_refused:
            try:
                self._match_position_lag(raw_positions, now_ns)
            except Exception as exc:  # noqa: BLE001 - contained; diagnostic only
                self._log.warning(
                    f"R7_LAG_REJECT reason=MATCH_FAILED detail="
                    f"{exc.__class__.__name__}: {exc}"
                )

    def _match_position_lag(self, raw_positions: Mapping[str, Any], now_ns: int) -> None:
        """R-7-IMPL producer's confirming half (RULING R-7).

        Per pending create-path accept-fill entry, in `_position_lag_pending`
        insertion order: reject a poisoned/implausible `tsEvent` outright;
        otherwise wait for a read taken after the fill's own receive time,
        then confirm or count a non-LONG read, until either a LONG confirms
        (a `PositionReportingLag` is logged and the entry is popped) or the
        entry ages out (`UNCONFIRMED_TTL`). Never calls `_map_position`,
        which latches trading refusals and mutates settled-position state --
        this function is a pure diagnostic and must have zero side effect
        on trading. An undetermined position (no payload for this instrument's
        slug, or a payload `parse_position_status_report` cannot map) leaves
        the entry pending, unchanged, for a later pass to resolve.
        """
        if not self._position_lag_pending:
            return
        bound_ns = _FILL_TS_EVENT_MAX_SKEW_NS
        still_pending: dict[InstrumentId, _PendingPositionLag] = {}
        determined_long: set[InstrumentId] = set()
        determined_not_long: set[InstrumentId] = set()
        for instrument_id, raw_entry in self._position_lag_pending.items():
            # `*raw_entry` accepts either a `_PendingPositionLag` (the
            # producer's real shape) or a same-length plain tuple (test
            # fixtures seed both) -- normalising here means `._replace()`
            # below never sees a bare tuple. A too-short/too-long
            # `raw_entry` (T10: a malformed pending entry) still raises,
            # caught by the caller's broad `except`.
            entry = _PendingPositionLag(*raw_entry)
            fill_ts_event, send_ns, recv_ns, client_order_id, reads_without_long = entry
            reject_reason: str | None = None
            if client_order_id == _MULTI_FILL_PENDING_SENTINEL:
                reject_reason = "MULTI_FILL_PENDING"
            elif fill_ts_event <= 0:
                reject_reason = "TS_EVENT_ABSENT"
            elif fill_ts_event < send_ns - bound_ns:
                reject_reason = "TS_EVENT_SKEW_PAST"
            elif fill_ts_event > recv_ns + bound_ns:
                reject_reason = "TS_EVENT_SKEW_FUTURE"
            if reject_reason is not None:
                self._log.warning(
                    f"R7_LAG_REJECT reason={reject_reason} instrument_id={instrument_id} "
                    f"client_order_id={client_order_id} fill_ts_event={fill_ts_event} "
                    f"send_ns={send_ns} recv_ns={recv_ns} bound_ns={bound_ns}"
                )
                continue
            if now_ns <= recv_ns:
                still_pending[instrument_id] = entry
                continue
            if instrument_id in self._position_lag_last_long:
                self._log.warning(
                    f"R7_LAG_REJECT reason=PRIOR_LONG instrument_id={instrument_id} "
                    f"client_order_id={client_order_id} fill_ts_event={fill_ts_event} "
                    f"send_ns={send_ns} recv_ns={recv_ns} bound_ns={bound_ns}"
                )
                continue
            slug = base_slug_of(instrument_id)
            payload = raw_positions.get(slug)
            instrument = self._cache.instrument(instrument_id)
            is_long = False
            determined = False
            if payload is None:
                determined = True
            elif instrument is not None and isinstance(payload, Mapping):
                try:
                    mapped = parse_position_status_report(
                        payload,
                        market_slug=slug,
                        instrument=instrument,
                        account_id=self._issued_account_id,
                        report_id=UUID4(),
                        ts_init=now_ns,
                    )
                except Exception:  # noqa: BLE001 - one bad position never blocks the rest
                    mapped = None
                if mapped is not None:
                    determined = True
                    is_long = (
                        not mapped.expired
                        and mapped.report.position_side == PositionSide.LONG
                        and mapped.leg == leg_of(instrument_id)
                    )
            if is_long:
                delta_ns = now_ns - fill_ts_event
                record = PositionReportingLag(
                    instrument_id=instrument_id,
                    fill_ts_event=fill_ts_event,
                    first_eof_read_ts_showing_long=now_ns,
                    delta_ns=delta_ns,
                    fill_ts_event_source=FILL_TS_EVENT_SOURCE_VENUE_TRANSACT_TIME,
                )
                self._log.info(
                    f"R7_POSITION_REPORTING_LAG instrument_id={record.instrument_id} "
                    f"client_order_id={client_order_id} fill_ts_event={record.fill_ts_event} "
                    f"fill_ts_event_source={record.fill_ts_event_source} "
                    f"first_eof_read_ts_showing_long={record.first_eof_read_ts_showing_long} "
                    f"delta_ns={record.delta_ns} delta_ms={record.delta_ns // 1_000_000} "
                    f"reads_without_long={reads_without_long} "
                    f"recv_skew_ns={fill_ts_event - recv_ns}"
                )
                determined_long.add(instrument_id)
                continue
            if determined:
                determined_not_long.add(instrument_id)
            if now_ns - recv_ns > _POSITION_LAG_PENDING_TTL_NS:
                self._log.warning(
                    f"R7_LAG_REJECT reason=UNCONFIRMED_TTL instrument_id={instrument_id} "
                    f"client_order_id={client_order_id} fill_ts_event={fill_ts_event} "
                    f"send_ns={send_ns} recv_ns={recv_ns} bound_ns={bound_ns}"
                )
                continue
            still_pending[instrument_id] = entry._replace(
                reads_without_long=reads_without_long + 1
            )
        self._position_lag_pending = still_pending
        self._position_lag_last_long = (
            self._position_lag_last_long - determined_not_long
        ) | determined_long

    async def _refresh_startup_position_evidence(self) -> None:
        """C1: fresh positions read at the END of `_connect`.

        Never raises: a read failure or a non-eof-complete page is RECORDED
        as refused, not swallowed and not propagated -- the strategy's
        `on_start` gate is the one place that acts on it.
        """
        now_ns = self._clock.timestamp_ns()
        # Section 4.3: enumerate open orders FIRST, independently of the
        # positions read -- each failure is recorded on its own flag, so the
        # gate's log names which read refused.
        try:
            open_orders = await self._read_open_orders()
        except Exception as exc:  # noqa: BLE001 - recorded as refused, never propagated
            self._note_open_orders_outcome(error=exc)
        else:
            self._note_open_orders_outcome(records=open_orders)
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

    async def _read_open_orders(
        self, slugs: Iterable[str] | None = None
    ) -> tuple[OpenOrderRecord, ...]:
        """RESTING_BID_HUNT Rev 2 section 4.3: enumerate the account's open
        orders -- ONE bare-path GET on ``OPEN_ORDERS_PATH`` through the
        injected ``PrivateRead`` seam, mapped by ``parse_open_orders``.

        Raises on any failure (``PrivateReadRefused``, a transport fault,
        ``ExecutionReportMappingError`` on a malformed body): the caller
        decides what a refused read means, and for the never-arm gate it
        means REFUSED, never empty. ``slugs`` narrows the RESULT client-side;
        the venue's ``slugs[]`` query is never sent, so the request is the
        same proven path-only signed GET every time and a caller's filter
        cannot hide a foreign order from the unfiltered enumeration.
        """
        payload = await self._private_read(OPEN_ORDERS_PATH)
        records = parse_open_orders(payload)
        if slugs is None:
            return records
        wanted = frozenset(slugs)
        return tuple(r for r in records if r.market_slug in wanted)

    def _note_open_orders_outcome(
        self,
        *,
        records: tuple[OpenOrderRecord, ...] | None = None,
        error: BaseException | None = None,
    ) -> None:
        """Record the latest open-order enumeration on this client (the
        state every subsequent evidence row carries) and log it: WARNING for
        a refused read, ERROR -- ids redacted to a prefix -- when any order
        is open (``STARTUP_OPEN_ORDERS_PRESENT_REASON``), one bounded
        WARNING when a row carried undeclared keys.
        """
        if error is not None or records is None:
            self._open_orders_read_refused = True
            self._open_orders = ()
            self._log.warning(
                "startup evidence: open-orders read failed "
                f"({type(error).__name__ if error is not None else 'no result'}); "
                "recording open_orders_read_refused=True"
            )
            return
        self._open_orders_read_refused = False
        self._open_orders = records
        drifted = [r for r in records if r.unknown_keys]
        if drifted:
            self._log.warning(
                f"startup evidence: {len(drifted)} open order row(s) carry undeclared "
                f"key(s); first row: {', '.join(drifted[0].unknown_keys)}"
            )
        if records:
            ids = ", ".join(_redact_order_id(r.venue_order_id) for r in records)
            self._log.error(
                f"{STARTUP_OPEN_ORDERS_PRESENT_REASON}: {len(records)} open order(s) on "
                f"the account ({ids}); the never-arm gate refuses until every one is "
                "enumerated and adopted or cancelled"
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
            f"{exc.__class__.__name__}; this intent stays AMBIGUOUS and "
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
        # FAILURE-KIND-PERSIST (r2/r3): the follow-up entry (item 6 in the
        # file-by-file plan), same clearing discipline.
        self._resolver_stale_alert_details.pop(f"{intent_id}:cause", None)
        # EDGE-2 slice D (AC4): same clearing discipline for the
        # contradiction health surface -- a no-op when `intent_id` never
        # contradicted.
        self._resolver_contradiction_details.pop(intent_id, None)

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
        booking: SpendBooking | None,
        now_ns: int,
        create_detail: str | None = None,
        fill_parse_error: str | None = None,
        create_fill_evidence: str = submit_chain.CREATE_FILL_EVIDENCE_UNKNOWN,
        wire_market_slug: str | None = None,
        wire_price: str | None = None,
        wire_outcome_side: str | None = None,
        wire_action: str | None = None,
        register_booking: bool = True,
        capture_holding_baseline: bool = False,
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

        INC-E2: ``booking`` is ``None`` for an exit-side order (§5.8, gross
        entry spend only -- no debit was ever booked to true up or release),
        so ``booking_id`` records the sentinel ``-1`` (``_BOOKING_IDS`` is
        1-indexed, `operator_controls.py:157`, so it never collides with a
        real booking) rather than dereferencing a ``None``.

        EDGE-2 slice A (AC3): ``create_fill_evidence`` is the caller's
        already-computed ``submit_chain.create_fill_evidence(response.body)
        .token`` -- a closed-set name, never a price, quantity, or id.

        AMBIG-LATCH-RESUME: the four ``wire_*`` values are the echo fields a
        no-id attribution joins on. ``register_booking=False`` writes the
        context but holds no in-memory booking (the PRE-POST call: a take that
        ends non-AMBIGUOUS must leave no entry). ``capture_holding_baseline``
        (pre-POST only) adds the DM4 holding snapshot read from LOCAL durable
        evidence; a raise there yields no baseline, never a denied take.
        """
        baseline: HoldingBaseline | None = None
        if capture_holding_baseline and wire_market_slug is not None:
            try:
                baseline = self._holding_baseline(order.instrument_id, wire_market_slug, now_ns)
            except Exception as exc:  # noqa: BLE001 - no baseline is the safe direction
                baseline = None
                self._log.warning(
                    f"no-id holding baseline unavailable ({exc.__class__.__name__}); "
                    "the absolute rule applies"
                )
        context = AmbiguousResolverContext(
            intent_id=intent_id,
            venue_order_id=venue_order_id,
            instrument_id=str(order.instrument_id),
            client_order_id=str(order.client_order_id.value),
            strategy_id=str(order.strategy_id.value),
            notional_usd=notional_usd,
            booking_id=_NO_BOOKING_ID if booking is None else booking.booking_id,
            created_ns=now_ns,
            create_detail=create_detail,
            fill_parse_error=fill_parse_error,
            order_side=order.side.name,
            create_fill_evidence=create_fill_evidence,
            wire_market_slug=wire_market_slug,
            wire_price=wire_price,
            wire_outcome_side=wire_outcome_side,
            wire_action=wire_action,
            baseline_venue_net=None if baseline is None else baseline.venue_net,
            baseline_durable_net=None if baseline is None else baseline.durable_net,
            baseline_ts_ns=None if baseline is None else baseline.ts_ns,
        )
        self._store_set(f"{RESOLVER_CONTEXT_KEY_PREFIX}{intent_id}", context.to_bytes())
        if register_booking:
            self._ambiguous_bookings[intent_id] = booking

    def _holding_baseline(
        self, instrument_id: InstrumentId, slug: str, now_ns: int
    ) -> HoldingBaseline | None:
        """The pre-POST holding snapshot from LOCAL durable evidence, or ``None``.

        No venue read is possible before the POST, so the snapshot is the
        startup-evidence record the resolver refreshes about every 60 s. ``None``
        (the resolver then uses the absolute rule) when the evidence is absent,
        refused or not eof-complete; the slug's net is unknown; the durable net
        is undeterminable; the evidence is older than the attribution back-skew
        (the activities scan must cover every manual trade after the snapshot);
        or a durable fill on this instrument landed within
        :data:`_NO_ID_BASELINE_QUIET_NS` before the snapshot (it may not yet
        reflect it). Sync, local reads only; never called from a resolver body.
        """
        evidence = self.read_startup_position_evidence()
        if evidence is None or evidence.position_read_refused or not evidence.eof_complete:
            return None
        if now_ns - evidence.ts_ns > _NO_ID_WINDOW_BACKSKEW_NS:
            return None
        venue_net = "0"
        for snapshot in evidence.positions:
            if snapshot.slug == slug:
                if snapshot.net_position is None:
                    return None
                venue_net = snapshot.net_position
        indexed = self._read_fill_index(f"{FILL_INDEX_KEY_PREFIX}{instrument_id}")
        if indexed is None:
            return None
        durable_net = Decimal(0)
        for venue_order_id in indexed:
            raw = self._store_get(f"{FILL_KEY_PREFIX}{venue_order_id}")
            if raw is None:
                return None
            record = DurableFillRecord.from_bytes(raw)
            if record.order_side not in _RECORD_SIGNS:
                return None
            if record.ts_event > evidence.ts_ns - _NO_ID_BASELINE_QUIET_NS:
                return None
            durable_net += _RECORD_SIGNS[record.order_side] * record.cumulative_qty
        return HoldingBaseline(venue_net, str(durable_net), evidence.ts_ns)

    def _set_resolver_last_failure_kind(
        self,
        context: AmbiguousResolverContext,
        kind: str,
    ) -> None:
        """FAILURE-KIND-DURABLE (2026-09-28): update the in-memory failure-
        kind map AND rewrite the durable resolver context's
        ``lastFailureKind`` so a restart does not lose it -- ``self.
        _resolver_last_failure_kind`` alone is process-local memory (see its
        field comment in ``__init__``) and the seed at the top of
        ``_resolve_ambiguous_intents`` is a restart's only other source.

        Plan r2 delta, helper discipline (L-48):

        * Writes to the store ONLY when ``kind`` actually CHANGES from what
          this process already has recorded in memory for ``context.
          intent_id`` -- the guarded reset a successful GET runs on EVERY
          pass would otherwise turn every clean poll into a durable write.
        * Synchronous, never ``await``s -- E0-NOSEND-RESOLVER allowlisted,
          exactly like :meth:`record_venue_order_id` above: one key, to the
          already-open local store, no path, no payload, no socket.
        * Wrapped in a broad ``except`` that logs and NEVER re-raises: every
          call site here sits OUTSIDE the narrow per-operation ``try``
          blocks the resolver pass otherwise uses, so an unguarded store
          failure would propagate out of ``_resolve_ambiguous_intents``
          itself and kill the resolver task for the process lifetime -- the
          exact crash L-48 exists to close. A failed durable write leaves
          the intent exactly as resolvable as it was before this call: still
          AMBIGUOUS, still polled next pass.
        """
        changed = self._resolver_last_failure_kind.get(context.intent_id) != kind
        self._resolver_last_failure_kind[context.intent_id] = kind
        if not changed:
            return
        try:
            rewritten = dataclasses.replace(context, last_failure_kind=kind)
            self._store_set(
                f"{RESOLVER_CONTEXT_KEY_PREFIX}{context.intent_id}", rewritten.to_bytes(),
            )
        except Exception as exc:  # noqa: BLE001 - L-48: never raise into the resolver
            self._log.warning(
                f"resolver: could not durably record last_failure_kind={kind!r} for "
                f"intent {context.intent_id} ({type(exc).__name__}: {exc}); staying "
                "in-memory only for this process"
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
        # INC-E2c: reconstruct the exit-order view from the order's OWN
        # tags -- never imported from `strategy/exit_wiring.py` (the
        # importlinter layer contract). Slicing + `==` only (see
        # `_EXIT_RULE_TAG_PREFIX_LEN`'s comment): every `ast.Call` inside
        # this coroutine must be on `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES`
        # (`test_execution_egress_firewall_guard.py`), so a `str.startswith`
        # call here would need a cage entry a pure comparison does not.
        order_tags = order.tags or []
        exit_rule_tag: str | None = None
        exit_position_id = ""
        exit_family_id = ""
        exit_client_order_id = ""
        for order_tag in order_tags:
            if order_tag[:_EXIT_RULE_TAG_PREFIX_LEN] == EXIT_RULE_TAG_PREFIX:
                exit_rule_tag = order_tag[_EXIT_RULE_TAG_PREFIX_LEN:]
            elif order_tag[:_EXIT_POSITION_TAG_PREFIX_LEN] == EXIT_POSITION_TAG_PREFIX:
                exit_position_id = order_tag[_EXIT_POSITION_TAG_PREFIX_LEN:]
            elif order_tag[:_EXIT_FAMILY_TAG_PREFIX_LEN] == EXIT_FAMILY_TAG_PREFIX:
                exit_family_id = order_tag[_EXIT_FAMILY_TAG_PREFIX_LEN:]
            elif (
                order_tag[:_EXIT_CLIENT_ORDER_ID_TAG_PREFIX_LEN]
                == EXIT_CLIENT_ORDER_ID_TAG_PREFIX
            ):
                exit_client_order_id = order_tag[_EXIT_CLIENT_ORDER_ID_TAG_PREFIX_LEN:]
        # An exit-tagged order the plan's `Order.closing_side` always makes a
        # SELL (`submit_exit`, `exit_wiring.py`); an order with the tag but
        # the wrong side is treated as a plain (untagged) order below rather
        # than risking an `exit_view` used uninitialised.
        is_exit_order = exit_rule_tag is not None and order.side == OrderSide.SELL
        exit_view: _AdapterExitAuthorization | None = None
        if is_exit_order:
            # Every log line for an exit carries `exit=` and the rule
            # (brief requirement), unconditionally -- before any deny/allow
            # decision below.
            self._log.warning(
                f"exit order exit={exit_rule_tag} position_id={exit_position_id} "
                f"client_order_id={order.client_order_id.value}"
            )
            # Item C (POSITION_EXIT_EXECUTION_2026-09-16.md review): deny
            # immediately when the instrument has vanished from the cache --
            # never fabricate a "yes"-leg placeholder to keep
            # `_AdapterExitAuthorization` constructible. The SAME reason
            # `unmappable_exit_order_reason`/`_unmappable_exit_shape_reason`
            # would eventually return for a `None` instrument, stated here
            # instead of manufactured evidence flowing into the shape check.
            if instrument is None:
                return self._deny(
                    order, "instrument is not a BinaryOption; refusing", now_ns,
                )
            exit_leg: Leg = leg_of(instrument.id)
            try:
                exit_limit_price = submit_chain.order_price_decimal(order)
            except (TypeError, ValueError, InvalidOperation):
                exit_limit_price = submit_chain.ZERO
            exit_view = _AdapterExitAuthorization(
                family_id=exit_family_id,
                position_id=exit_position_id,
                client_order_id=exit_client_order_id,
                leg=exit_leg,
                quantity=1,
                limit_price=exit_limit_price,
            )
            if self._exit_manifest is None:
                return self._deny(order, _EXIT_MANIFEST_ABSENT_REASON, now_ns)
            unmappable = submit_chain.unmappable_exit_order_reason(
                order, instrument, exit_view, self._exit_manifest
            )
        else:
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
        # BL-10 A1 (r2 delta, hard requirement): build, encode, fingerprint,
        # assert, then consume -- synchronously, no `await` anywhere in this
        # block, and BEFORE `authorize_order_cost` and BEFORE `self._latch.
        # arm`. Body-build now runs BEFORE the permit mint (not after, as
        # before BL-10): a `build_order_body`/`build_exit_order_body` raise
        # here spends no permit budget and arms no intent, because neither
        # has run yet.
        if is_exit_order:
            assert exit_view is not None  # narrowed by `is_exit_order` above
            body = submit_chain.build_exit_order_body(order, instrument, exit_view)
        else:
            body = submit_chain.build_order_body(order, instrument)
        encoded = submit_chain.encode_order_body(body)
        order_notional = submit_chain.order_notional_usd(order)
        fingerprint = submit_chain.wire_fingerprint_bytes(
            method=write_transport._WRITE_METHOD,
            path=write_transport.ORDERS_PATH,
            body=encoded,
        )
        try:
            authorization = assert_live_order_submission_permitted(
                credentials=self._credentials,
                permit=self._permit,
                manual_order_indicator=False,
                order_notional_usd=order_notional,
                request_fingerprint=fingerprint,
                now_ns=now_ns,
            )
            # Single-use and self-enforcing (`safety.py`'s `consume`): a
            # mismatched or already-spent capability raises here, before
            # `authorize_order_cost` or `self._latch.arm` ever run.
            authorization.consume(
                request_fingerprint=fingerprint,
                order_notional_usd=order_notional,
                now_ns=now_ns,
            )
        except SessionNotionalExhausted as exc:
            self._mark_budget_exhausted(now_ns)
            return self._deny(order, f"{exc}; this client refuses to submit", now_ns)
        except LiveTradingPermissionError as exc:
            return self._deny(order, f"{exc}; this client refuses to submit", now_ns)
        # INC-E2 budget (review MEDIUM 9): the daily budget is GROSS entry
        # spend (§5.8) -- an exit-side order never calls
        # `authorize_order_cost` and never debits the daily counter, so its
        # `booking` stays `None` through every downstream release/true-up
        # site below (each already guarded), and its proceeds never
        # replenish entry headroom. INC-E2c: an exit order now reaches this
        # coroutine (gated by `submit_chain.unmappable_exit_order_reason`
        # above, which the untagged/naked-short path never reaches), so
        # `is_exit_side` is `True` for exactly the orders `is_exit_order`
        # marked above -- the two conditions are equivalent by construction
        # (`unmappable_exit_order_reason`'s own shape check refuses any
        # exit-tagged order whose side is not SELL).
        is_exit_side = order.side == OrderSide.SELL
        booking: SpendBooking | None = None
        if not is_exit_side:
            try:
                booking = self._ledger.authorize_order_cost(
                    price_usd=submit_chain.order_price_decimal(order),
                    quantity=submit_chain.order_quantity_decimal(order),
                    now_ns=now_ns,
                )
            except DailyBudgetExhausted as exc:
                self._mark_budget_exhausted(now_ns)
                return self._deny(order, f"{exc}; this client refuses to submit", now_ns)
            except LiveTradingPermissionError as exc:
                return self._deny(order, f"{exc}; this client refuses to submit", now_ns)
        if self._intent_reconciled is not True:
            if booking is not None:
                self._ledger.release_booking(booking, now_ns=now_ns)
            return self._deny(order, submit_chain.RECONCILE_NOT_RUN_REASON, now_ns)
        try:
            intent = self._latch.arm(submit_chain.intent_fingerprint(order), now_ns=now_ns)
        except Exception as exc:  # noqa: BLE001 - store/latch failures must deny, not crash the loop
            if booking is not None:
                self._ledger.release_booking(booking, now_ns=now_ns)
            if submit_chain.is_latch_arm_refusal(exc):
                return self._deny(order, submit_chain.LATCH_ARM_REFUSED_REASON, now_ns)
            return self._deny(order, submit_chain.STORE_RAISED_REASON, now_ns)
        # AMBIG-LATCH-RESUME: the durable context BEFORE the POST, with no
        # `await` between `arm` and this write, so the resolver (same loop) can
        # never observe an armed intent without it. It carries the wire echo a
        # no-id resolution joins on. A write failure never POSTs.
        try:
            self._note_ambiguous_open(
                intent_id=intent.intent_id,
                venue_order_id=submit_chain.NO_VENUE_ORDER_ID,
                order=order,
                notional_usd=order_notional,
                booking=booking,
                now_ns=now_ns,
                register_booking=False,
                capture_holding_baseline=True,
                wire_market_slug=body["marketSlug"],
                wire_price=body["price"]["value"],
                wire_outcome_side=body["outcomeSide"],
                wire_action=body["action"],
            )
        except Exception:  # noqa: BLE001 - fail closed: never POST without a durable context
            if booking is not None:
                self._ledger.release_booking(booking, now_ns=now_ns)
            return self._deny(order, submit_chain.STORE_RAISED_REASON, now_ns)
        headers = self._write_signer.sign_headers(
            write_transport._WRITE_METHOD,
            write_transport.ORDERS_PATH,
        )
        self._post_in_flight_intent_id = intent.intent_id
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
            self._ambiguous_bookings[intent.intent_id] = booking
            if submit_chain.is_cancelled(exc):
                raise
            return
        finally:
            self._post_in_flight_intent_id = None
        outcome = submit_chain.classify_create_order_outcome(
            response,
            instrument=instrument,
            account_id=self._issued_account_id,
            ts_init=now_ns,
            # INC-E2 response-side leg check: `is_exit_order` is the SAME
            # tag-derived flag computed above (never re-derived here), so
            # the response is checked against the closing-order echo table
            # for exactly the orders the request side already tagged and
            # mapped as a close.
            closing=is_exit_order,
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
                    # INC-E2: the order's REAL side, never the entry-only
                    # `LONG_ONLY_SIDE` hardcode. `order.side` is always
                    # `OrderSide.BUY` today (`unmappable_order_reason`
                    # refuses every other side, byte-unchanged), so
                    # `.name` == `LONG_ONLY_SIDE` == "BUY" for every fill
                    # this branch has ever recorded.
                    order_side=order.side.name,
                    cumulative_qty=outcome.cumulative_qty,
                    cumulative_cost=outcome.cumulative_cost,
                    cumulative_fee=outcome.cumulative_fee,
                    fee_reconciled=outcome.fee_reconciled,
                    ts_event=fill.ts_event,
                    venue_fee_raw=fill.commission_raw,
                    trade_id=fill.trade_id.value,
                    order_qty=submit_chain.order_quantity_decimal(order),
                )
                # AUD-13b (ruling R-1 = O4 (a)): stamp the theta of the
                # instrument this order was priced and sent against.
                self.record_fill(
                    record,
                    fill_time_instrument=instrument,
                    intent_fingerprint=intent.fingerprint,
                    intent_created_ns=intent.created_ns,
                )
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
                if booking is not None:
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
                # INC-E2: the order's REAL side, never the hardcoded
                # `OrderSide.BUY`.
                order_side=order.side,
                order_type=OrderType.LIMIT,
                last_qty=fill.last_qty,
                last_px=fill.last_px,
                quote_currency=USD,
                commission=fill.commission,
                liquidity_side=LiquiditySide.TAKER,
                ts_event=fill.ts_event,
            )
            # R-7-IMPL (RULING R-7): remember this fill's venue `tsEvent`,
            # keyed by instrument, for `_match_position_lag` to confirm
            # against the next eof-complete positions read. One statement,
            # after every effect above, no `await`, no new callee --
            # `self._clock.timestamp_ns` is already permitted (E0-NOSEND).
            # `in` is a membership test, not an `ast.Call`, and a dict/tuple
            # LITERAL is not one either -- both invisible to
            # `find_exec_send_path_violations`, the same shape
            # `_last_evidence_write_ns`'s plain assignment already uses.
            # Deliberately still a plain positional tuple, NOT
            # `_PendingPositionLag(...)`/`._replace()` -- either would be an
            # `ast.Call` this order-lifecycle coroutine may not make
            # (E0-NOSEND; confirmed by planting one and watching
            # `test_e0_inert_no_shipped_exec_module_can_reach_the_network`
            # go red). `_match_position_lag` -- outside the scanned set --
            # normalises every entry to `_PendingPositionLag` on read, so
            # the field ORDER below must match that NamedTuple's declared
            # order exactly: `(fill_ts_event, send_ns, recv_ns,
            # client_order_id, reads_without_long)`.
            # Never for an exit order (INC-E2 widened this branch to close
            # fills too): only a create-path ENTRY establishes the LONG this
            # record measures confirmation of. A SECOND accept-fill on an
            # instrument with an unconfirmed entry poisons it with
            # `_MULTI_FILL_PENDING_SENTINEL` instead of overwriting it --
            # neither fill's confirmation would be attributable to one POST.
            if not is_exit_order:
                if order.instrument_id in self._position_lag_pending:
                    existing_lag_entry = self._position_lag_pending[order.instrument_id]
                    self._position_lag_pending = {
                        **self._position_lag_pending,
                        order.instrument_id: (
                            existing_lag_entry[0],
                            existing_lag_entry[1],
                            existing_lag_entry[2],
                            _MULTI_FILL_PENDING_SENTINEL,
                            existing_lag_entry[4],
                        ),
                    }
                else:
                    self._position_lag_pending = {
                        **self._position_lag_pending,
                        order.instrument_id: (
                            fill.ts_event,
                            now_ns,
                            self._clock.timestamp_ns(),
                            order.client_order_id.value,
                            0,
                        ),
                    }
            return
        if (
            outcome.kind == submit_chain.KIND_ZERO_FILL
            and retire_name is not None
            and outcome.venue_order_id is not None
        ):
            if booking is not None:
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
            if booking is not None:
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
            # L-36 / Resolution A2: the with-id write below OVERWRITES the
            # pre-POST context for this intent (same key) with the venue id,
            # keeping the wire echo fields. A no-id AMBIGUOUS (the `else:`)
            # is resolved by the automated no-id resolver on complete reads
            # only (2026-10-03, coordinator ruling CH1); `clear_submit_intent`
            # stays available and is never invoked by code.
            #
            # EDGE-2 slice A (AC3): closed-set create-time fill evidence,
            # parsed independently of `outcome` (option F1 -- a second
            # parse of the same body, only on this with-id branch).
            # `evidence.exec_types`/`.order_state`/`.order_cum`/`.skips` are
            # tuples/names/enum-shaped tokens only (never a price, quantity,
            # or id), embedded via f-string so this coroutine makes no
            # dotted call the E0-NOSEND allowlist does not already name.
            evidence = submit_chain.create_fill_evidence(response.body)
            self._log.error(
                "create-order AMBIGUOUS create-fill-evidence: "
                f"token={evidence.token} exec_types={evidence.exec_types} "
                f"order_state={evidence.order_state} order_cum={evidence.order_cum} "
                f"skips={evidence.skips} "
                f"client_order_id={order.client_order_id.value}"
            )
            self._note_ambiguous_open(
                intent_id=intent.intent_id,
                venue_order_id=outcome.venue_order_id,
                order=order,
                notional_usd=submit_chain.order_notional_usd(order),
                booking=booking,
                now_ns=now_ns,
                create_detail=outcome.detail,
                fill_parse_error=outcome.fill_parse_error,
                create_fill_evidence=evidence.token,
                wire_market_slug=body["marketSlug"],
                wire_price=body["price"]["value"],
                wire_outcome_side=body["outcomeSide"],
                wire_action=body["action"],
            )
        else:
            self._ambiguous_bookings[intent.intent_id] = booking

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

    def resume_if_refusals_cleared(self) -> bool:
        """Resume from DEGRADED once no refusal and no open submit intent remain.

        Returns True iff the call ends with the client RUNNING. Synchronous,
        no ``await``, and its callees are exactly ``self._latch.is_latched``,
        ``self.resume``, ``self.degrade``, ``self._log.info`` and
        ``self._log.warning``: the native ``_resume`` / ``_degrade`` actions are
        no-ops, so this changes a health indicator and sends nothing. RUNNING
        never gates sending (see ``_submit_order``'s refusal check, the permit,
        the latch and the operator caps).
        """
        if not self.is_degraded:
            return False
        if self._trading_refusals:
            return False
        if self._latch is None:
            return False
        try:
            latched = self._latch.is_latched()
        except Exception as exc:  # noqa: BLE001 - an unreadable latch must only skip the resume
            self._log.warning(
                f"health: resume skipped, latch unreadable ({exc.__class__.__name__})"
            )
            return False
        if latched:
            return False
        self.resume()
        if self._trading_refusals and not self.is_degraded:
            self._log.warning("health: a refusal landed during RESUMING; re-degrading")
            self.degrade()
            return False
        self._log.info("health: resumed from DEGRADED (no refusals, no open submit intent)")
        return True

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(client_id={self.id}, venue={self.venue}, "
            f"account_id={self._issued_account_id}, "
            f"refusals={len(self._trading_refusals)})"
        )
