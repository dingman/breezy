# Nautilus execution-path native audit — 2026-08-31

**Nautilus 1.231.0**, installed at `.venv/lib/python3.13/site-packages/nautilus_trader/`
(`NT/` below). Null hypothesis under test: *"Nautilus already provides everything needed
to submit a live order; Breezy need only subclass its sanctioned extension points."*

**VERDICT: CONFIRMED, with three narrow evidenced exceptions.** Nautilus supplies the
whole order lifecycle, state machine, position tracking, reconciliation loop, retry
primitives and pre-trade risk. Breezy authors only venue protocol translation,
`AccountState` emission, and settlement-to-0/1 semantics.

Every fact below was **re-verified by the orchestrator directly against the installed
source**, not accepted on an agent's report.

---

## H-1 [CRITICAL] The RiskEngine balance check FAILS OPEN with no account

`NT/risk/engine.pyx:682-689`, verbatim:

```
cdef Account account = self._cache.account_for_venue(instrument.id.venue, account_id)

if account is None:
    self._log.debug(
        f"Cannot find account for venue {instrument.id.venue} "
        ...
    )
    return True  # TODO: Temporary early return until handling routing/multiple venues
```

`return True` is **pass**. The log is at **debug**, which Breezy does not emit in
production. So if the execution client never emits `AccountState`, every notional and
balance check is silently bypassed — no error, no warning, no denial.

`generate_account_state` exists (`NT/execution/client.pyx:329`) but **nothing calls it
for you**; the client must fetch venue balances and call it itself, normally inside
`_connect` before `_await_account_registered` (`NT/live/execution_client.py:534-567`).
`NT/live/node_builder.py:201-263` never seeds an account either.

**This is the third instance of the LESSONS L-2 pattern** — the native *mechanism* is
real and the *degree* is not what it appears. The first two were `TradingState.REDUCING`
(does not deny an opening BUY from flat) and the free-balance guard (conditional on
`not allow_borrowing`). Here the control is not merely narrower than assumed: it is
**entirely absent until we do something**, and its absence is indistinguishable from
success.

**Binding consequence.** A contract test must assert that submitting an order with no
account in the cache is DENIED by Breezy before Nautilus is consulted. We cannot rely on
the native check as the only line, and we must never read a green run as evidence that
it engaged. Also note `account.is_margin_account: return True` at `:691` — a second
unconditional pass.

## H-2 [HIGH] `max_notional_per_order` is COST-denominated, not payout-denominated

`NT/risk/engine.pyx:907`:
`notional = instrument.notional_value(effective_quantity, last_px, use_quote_for_inverse=True)`
→ non-inverse `qty * multiplier * price` (`NT/model/instruments/base.pyx:844`).

`BinaryOption` hardcodes `multiplier=Quantity.from_int_c(1)`
(`NT/model/instruments/binary_option.pyx:138`) and Breezy builds `BinaryOption`
(`adapters/polymarket_us/parsing.py:1200-1218`).

So **native notional = qty x price = cash outlay**, while max payout on a 0-1 contract is
`qty x 1.00`. **At a 0.05 price the native cap is 20x smaller than a payout cap** —
the exact inverse of the mistake this plan already shipped once with `net_exposure`.

This is GOOD news for §2.3: native `max_notional_per_order` is denominated in **premium
paid**, which is the unit §2.3 declares (*premium at risk*). It is therefore a genuine
native fit — but the conversion must still be written down, and any payout-denominated
Breezy cap converts as `cost_cap = payout_cap x price`.

## H-3 [HIGH] Settlement reconciles as a synthetic fill at the WRONG price

On settlement the venue reports the position flat while the Nautilus cache still holds it
open. Because `generate_missing_orders` defaults **True** (`NT/live/config.py:183`), the
engine synthesizes a closing order (`NT/live/execution_engine.py:2500-2566`) priced by
`_create_position_reconciliation_report` (`:2839-2924`):

1. `calculate_reconciliation_price(...)` — a Rust pyo3 call, **body not readable in the
   venv**. Its documented contract is the price that makes the *average price* arithmetic
   work out (`NT/live/reconciliation.py:580-586`) — an accounting reconstruction, **not a
   settlement price**.
2. Fallback: the last cached quote's ask/bid (`:2871-2877`) — but Breezy's own read side
   documents that a settled market publishes an **empty book**
   (`adapters/polymarket_us/data.py:624-641`).
3. Final fallback: `current_avg_px` — i.e. **close at your own entry price, realizing
   exactly zero PnL** (`:2879-2881`).

There is **no settlement concept in the execution layer at all**: `settle|Settle` over
`NT/execution/engine.pyx` returns zero matches. `InstrumentClose` (`NT/model/data.pyx:4198`)
is data-side only; Breezy already produces it (`parsing.py:1026-1031`) and strategies
consume it, but nothing in the execution engine subscribes.

**Consequence: an unattended settlement can book at entry price (zero PnL) or a stale
quote, never at the true 0.00/1.00.** For a bot whose ONLY exit is settlement (the bid
side cannot support a stop-out), this corrupts the single event that realizes all PnL.
Options, most conservative first: (a) return the settled position with `avg_px_open` set
to the venue settlement price; (b) `generate_missing_orders=False` and emit the fill
explicitly via `generate_order_filled`; (c) leave `position_check_interval_secs=None`
(the default) — but startup reconciliation still runs the position path
(`NT/live/execution_engine.py:1749-1770`), so (c) alone is not sufficient.

## H-4 [MEDIUM] `_query_account` is called but never defined

`NT/live/execution_client.py:332` calls `self._query_account(command)`. Grepping the file
returns **only that call site** — no definition, and it is absent from the
"Coroutines to implement" block (`:595-636`). A subclass that omits it raises
`AttributeError` **inside a created task**, swallowed into `_log.exception` (`:226`) —
a silent failure, not a `NotImplementedError`. Breezy must define it explicitly.

## H-5 [MEDIUM] Continuous reconciliation is OFF by default

`inflight_check_interval_ms=2000` is on (`NT/live/config.py:184`), but
`open_check_interval_secs` and `position_check_interval_secs` both default to `None`
(`:188,195`) and the loop skips them when falsy
(`NT/live/execution_engine.py:578-585, 663-688`). Startup reconciliation does run
(`reconciliation=True` default, `:177`). Enabling these is a deliberate decision with a
direct interaction with H-3 — turning the position check on without fixing the settlement
price makes the wrong-price fill fire repeatedly rather than once.

## H-6 [MEDIUM] `CashAccount.balance_impact` credits a SELL

`NT/accounting/accounts/cash.pyx:482-495`: BUY -> `-notional`, SELL -> `+notional`
(`+qty*price`) — spot semantics, "selling inventory you own". For a short binary the true
exposure is `qty*(1-price)`. Shorting is not executable today (empty bid side) and P5-fix
now denies it by default, but if a SELL ever leaves the machine the native cash check is
wrong **directionally**, not merely imprecise. Reinforces that `allow_short=False` is a
real control and not a formality.

---

## Confirmed PRESENT — do not rebuild

Order state machine (14 states, `NT/model/enums.py:383-397`); lifecycle event
construction and msgbus routing (`NT/execution/client.pyx:329-917`); order caching and
`orders_open`/`orders_inflight`; position tracking with OMS position-ID resolution
(`:826, 853-857`); startup + continuous reconciliation; in-flight order recovery;
submit-rate throttling (`NT/risk/engine.pyx:142, 1084`); `TradingState` gating
(`:556-580`); exponential backoff (`NT/live/retry.py:24-62`, `RetryManagerPool` `:242` --
**wire it, do not write one**); native IOC (`TimeInForce.IOC`, `NT/model/enums.py:446-453`);
`BinaryOption` as a first-class 0-1 instrument.

**One caution recorded so nobody "improves" it:** `CashAccount.calculate_pnls`
special-cases `InstrumentClass.SPORTS_BETTING` only (`cash.pyx:459-465`); `BinaryOption`
is `BINARY_OPTION` (`binary_option.pyx:131`) and takes the generic `notional_value`
branch, which for multiplier=1 and price in [0,1] is arithmetically correct. Nautilus
also ships `AccountType.BETTING` and `accounting/accounts/betting.pyx` — a **different**
model (back/lay stake), NOT a drop-in for a cash-settled 0-1 contract.

## Must implement (all raise `NotImplementedError`)

`_connect`, `_disconnect`, `_submit_order`, `_submit_order_list`, `_modify_order`,
`_cancel_order`, `_cancel_all_orders`, `_batch_cancel_orders`
(`NT/live/execution_client.py:598-633`), plus the four report coroutines
(`:343-438`) which are required in practice because `generate_mass_status` gathers all
three plural ones (`:499-503`) and the engine calls it at startup
(`NT/live/execution_engine.py:1709-1712`). Plus `_query_account` per H-4.

## Refusal mechanism for unsupported order types

The venue exposes only LIMIT/MARKET
(`docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/types/orders.py:7`),
so **7 of Nautilus's 9 order types must be refused**. Nautilus validates price, quantity
and GTD expiry only (`NT/risk/engine.pyx:584-606`) — per-venue order-type support is
**entirely the client's job**. Use `generate_order_denied`
(`NT/execution/client.pyx:370-409`) for "never supported" (terminal, pre-venue, no
`OrderSubmitted` needed), and `generate_order_rejected` (`:447-489`) only for genuine
venue rejections after `OrderSubmitted`.

## NOT verified — do not treat as settled

- Bodies of `nautilus_pyo3.calculate_reconciliation_price` and
  `create_inferred_reconciliation_trade_id` (Rust, no readable source in the venv).
- `accounting/accounts/betting.pyx` bodies.
- **Whether a `Price` of exactly 0.00 or 1.00 survives fill validation and
  `_check_price`.** Suggestive but unproven: `instrument.make_price(0.0)` is used as a
  fallback at `NT/live/reconciliation.py:493`. **Needs a RED test before the settlement
  path depends on it.**
- `_reconcile_position_report_hedging` (`NT/live/execution_engine.py:2349`) — only the
  NETTING path was read.

---

# ADDENDUM 2026-08-31 — the native notional cap fails open THREE ways

Found while authoring `docs/plans/ORDER_EGRESS_PLAN.md`; **all re-verified by the
orchestrator directly against `NT/risk/engine.pyx`.** This supersedes the optimistic
framing of H-2 above: the cap is correctly *denominated*, and by default it never
*fires*.

| # | Condition | Line | Behaviour |
|---|---|---|---|
| F-1 | no account cached for the venue | `:684-689` | `return True` — **passes** |
| F-2 | `account.is_margin_account` | `:691` | `return True` — **passes** |
| F-3 | instrument absent from `_max_notional_per_order` | `:675, 677` | `.get()` -> `None`, `if max_notional_setting:` is false — **no cap applied** |
| F-4 | MARKET order with no cached quote or trade | `:786-789` | `continue` — **notional never checked for that order** |

## F-3 is the one that bites Breezy specifically

`self._max_notional_per_order: dict[InstrumentId, Decimal] = {}` (`:179`) is populated
**only** at construction, by iterating the static `RiskEngineConfig.max_notional_per_order`
mapping (`:194-196`). The per-order lookup is `.get(instrument.id)` (`:675`).

**Breezy's instruments are discovered at runtime.** Weather buckets are daily and their
IDs (`tc-temp-nychigh-2026-08-30-gte84lt85f.POLYMARKET_US`) cannot exist in a static
config written in advance. So the dict is empty for every instrument Breezy actually
trades, and the cap is **inert**.

The native remedy exists and must be used: `cpdef void set_max_notional_per_order(
InstrumentId, new_value)` at `:279`, called at runtime as instruments are discovered.
That is a wiring obligation, not a new abstraction — but a plan that says "NATIVE:
configure `max_notional_per_order`" and stops there ships **no cap at all**.

## F-4: never emit MARKET

A MARKET order's notional is checked only when a quote or trade is cached; otherwise the
engine logs at **warning** and `continue`s past the check (`:786-789`). Breezy's read side
documents that a settled market publishes an **empty book**
(`adapters/polymarket_us/data.py:624-641`) — precisely when a stale MARKET order is most
dangerous. The plan's rule to emit LIMIT only is therefore a safety control, not a style
preference. For LIMIT, `last_px = order.price` unconditionally (`:854`), so the check
always has a price to work with.

## Why this is recorded as a pattern, not four bugs

This is the **second-order form of LESSONS L-2**, now observed for the third time: the
audit is right about the *mechanism* and wrong about its *degree*. `TradingState.REDUCING`
does not deny an opening BUY from flat; the free-balance guard is conditional on
`not allow_borrowing`; and now the notional cap has four independent silent-pass paths.

**Every one of them fails OPEN and logs below the level we emit** — debug for F-1,
nothing at all for F-3, warning for F-4. There is no observable difference between "the
cap allowed this order" and "the cap was never consulted."

**Binding consequence for P4 and the egress plan.** A "NATIVE — configure it" verdict is
not complete until a contract test **executes the native path and asserts a DENIAL**.
Asserting that a permitted order passes proves nothing here, because passing is also what
total absence looks like. Breezy must additionally carry its own denial ahead of the
native check, so that the native layer is defence in depth rather than the only line.
