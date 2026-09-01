# EXEC SPINE — shortest sound path to one real, filled, reconciled order

**Status:** ACTIVE. Supersedes `docs/plans/EXEC_CLIENT_NOSEND_PLAN.md` (1993 lines; terminal
state was a process that refuses every order — zero evidence value against the stop gate, and
unreviewable at that length).
**Date:** 2026-09-01

## Goal state

> Positive ROI observed from real, very small marketable orders, with the confidence-interval
> **lower bound** clearing break-even.

This plan reaches the **first two prerequisites** of that gate:

1. **One real, filled, reconciled order** (R-1 … R-8).
2. **Settlement-as-exit** (R-9), without which a fill is an open position and no return can be
   computed — strictly required to produce the CI the gate asks for.

**Goal-state predicate (R-8).** After a single live run: the venue reports one filled order;
Breezy's cache holds a matching `OrderFilled` for the same `ClientOrderId`; a restart of the
node reconciles that position without denial and without a synthetic zero price; and the
realized cost is within one tick of the price we sent.

**End-to-end walk.** Node starts → exec client connects → account queried → `AccountState`
published → account present in cache → risk caps become live (see §Ordering) → instruments
loaded → strategy emits a marketable IOC BUY of 1 contract → guard passes it → `_submit_order`
signs and POSTs → venue returns `id` (+ `executions`) → fill applied → restart → mass status
reconciles the position → settlement closes it → one realized PnL row.

## Non-goals (ruthlessly cut — do NOT design these)

| Cut | Why |
|---|---|
| Four-type authority algebra | One chokepoint already exists (`safety.py:626`). |
| Full six-coroutine denial surface | Five have no live caller. Only `_submit_order` / `_cancel_order` get real bodies. |
| `/v1/portfolio/activities` fill mapping | Moot if `synchronousExecution` returns `executions` inline (OQ-4). |
| `reports.execution.{venue}` post-application verifier as a **blocker** | Keep as an alert only. |
| `exec/direction.py` | No consumer on this path. |
| Error classification beyond `{terminal, retryable, AMBIGUOUS}` | Matches Nautilus' native Command-outcome taxonomy; more is speculative. |

## Standing constraints (binding, every increment)

- **Nautilus Trader is IMMUTABLE.** Never modify, fork, patch, or reimplement it. Extend only
  through native extension points. Every increment states a null-hypothesis verdict.
- **Long-only, taker.** `allow_short=False` (`strategy/weather_common/risk.py:139`) is never
  changed, and no increment proposes changing it.
- **Operator-reserved controls stay unset.** Max **daily budget** and max **per position** are
  the operator's two values. We build the mechanism and the refusal; we never assign a number,
  and absence of a value must FAIL CLOSED, not default.
- **Never weaken or delete a safety, settlement, or contract test to go green.**
- **Test gate is `scripts/ci/run_tests_no_egress.sh`**, never bare pytest (the egress-firewall
  barrier aborts bare runs once `exec/` is armed). No live network in tests.
- **TDD mandatory.** Every increment lists its RED tests, and they land before implementation.
- **Paired-barrier discipline (carried from NS-5, unchanged).** Any barrier narrowing happens in
  the SAME commit as the compensating strengthening, with a non-vacuity proof showing the new
  test fails if the strengthening is removed.

---

## Ordering enforcement: the risk engine is INERT until an account exists

**Verified defect.** `nautilus_trader/risk/engine.pyx:682-692`:

```
if account is None:
    ...
    return True   # TODO: Temporary early return
if account.is_margin_account:
    return True
```

Every notional and position cap Nautilus offers — including `max_notional_per_order` — is
**inert** until a real `AccountState` is in the cache. Therefore **no increment that can submit
an order may land before R-4 publishes an account.** This ordering is enforced by a test, not by
prose.

**RED test `test_risk_caps_are_inert_without_account`** (contract-marked, runs under the
no-egress gate, no live network):

1. Cache with **no** account, `max_notional_per_order` configured → submit an over-cap order →
   assert it is **NOT** denied. This pins the fail-open as a known hazard so it cannot silently
   change under us.
2. Same order, same cap, **with** an `AccountState` in cache → assert `OrderDenied` on the
   `ExecEngine.process` msgbus endpoint. *(non-vacuity: step 2 fails if the account publish in
   R-4 is removed.)*
3. An **under**-cap order with the account present → assert it is accepted. *(non-vacuity:
   proves step 2 denied on the cap, not on account presence.)*

**Belt-and-braces mechanism.** Start the node in `TradingState.HALTED` and flip to `ACTIVE` only
after the account is confirmed in cache. Whether HALTED is evaluated before or after the account
fail-open is **unverified** — the RED test is the arbiter. If HALTED does not dominate, the
fallback is a Breezy-owned precondition in `_submit_order` that refuses when
`cache.account_for_venue(POLYMARKET_US)` is `None`. One of the two must be green before R-7.

---

## Increments

### R-1 — Live shape capture (value-free)

**Null hypothesis:** no Nautilus surface records venue response *shapes* without values.
**CONFIRMED absent** — the host is Breezy's own `scripts/venue/polymarket_us_auth_smoke.py`.

Capture key sets, types, and scales — **never values** — for `/v1/portfolio/positions`,
`/v1/account/balances`, `/v1/orders/open`. Extend the existing private-evidence path
(`polymarket_us_auth_smoke.py:702-736`, 0600/0700 with post-redaction leak verification).

**Do NOT reuse `_frame_schema` (`:954`) or `data.py:_walk_structure` (`:534-565`).** Both emit
`safe_values[...] = str(value)` and interpolate dict keys into published paths — pointed at
balances they publish the operator's money; pointed at positions they publish the portfolio as
field names. R-1 needs a keys-and-types-only walker with an explicit no-values assertion.

**RED:** `test_shape_capture_emits_no_scalar_values` (feed a fixture with distinctive sentinels;
assert no sentinel appears anywhere in the artifact); `test_shape_capture_artifact_mode_is_0600`.
**Done when:** artifacts for all three paths exist, and the leak check passes.

### R-2 — Trading process

**Null hypothesis:** Nautilus already provides the process shell. **CONFIRMED present** —
`TradingNode` / `NautilusKernel`. Breezy adds only a config builder and an entry point.

Third builder in `runtime/node_config.py` (siblings at `:163` and `:381`), settings loader, and
a `breezy-trade` entry point mirroring `runtime/quote_tape_cli.py` (`Node` protocol `:123-132`,
`_run_node` `:177-213`, latched-fault exit code). Config pins `CacheConfig(database=None,
flush_on_start=False)` like both siblings, and **`inflight_check_interval_ms=0`** — see OQ-5.

**RED:** builder returns a config with exactly one exec client and the data client; entry point
exits non-zero on a latched fault. **Done when:** the process starts, reaches `RUNNING`, and
exits `STOPPED` cleanly with no exec client behaviour yet.

### R-3 — `exec/endpoints.py` + report mappers

**Null hypothesis:** Nautilus supplies the report *types*. **CONFIRMED present** —
`OrderStatusReport`, `FillReport`, `PositionStatusReport`, `ExecutionMassStatus`. Breezy supplies
only venue→report mapping. Narrow strictly to what reconciliation consumes.

**Verified defect to fix here — money is rounded before the mapper sees it.**
`sdk_snapshot/.../types/account.py:19-33` types every balance field as **`float`**
(`currentBalance`, `buyingPower`, …), and the shipped decoder uses bare `json.loads`, so the JSON
literal is destroyed before any mapper runs. Convert with `json.loads(body,
parse_float=Decimal)` on the private-endpoint path. Market prices are unaffected — `Amount`
(`types/common.py`) carries `value` as a decimal **string**.

`AccountBalance.currency` must be identically `USD` to match `BinaryOption.currency`
(`parsing.py:1204`); a non-USD balance is a hard refusal, not a coercion.

**RED:** `test_balance_decode_preserves_decimal_literal` (a body containing `0.1` must not become
`0.1000000000000000055…`); `test_non_usd_balance_is_refused`; per-report mapper round-trips.
**Done when:** mappers are total over the R-1 captured shapes and refuse on unknown-shape input.

### R-4 — The reconciling, order-refusing client — **this de-inerts the risk engine**

**Null hypothesis:** `LiveExecutionClient` provides the lifecycle. **CONFIRMED present**; Breezy
subclasses it. **`_query_account` is CONFIRMED absent** — called at
`nautilus_trader/live/execution_client.py:332` with nothing defining it, so it must be
implemented or the call path raises.

Implement: `_connect`, `_set_account_id`, `generate_account_state`, `_query_account`,
`generate_mass_status`, a bounded instrument wait, and the input precondition. **Only
`_submit_order` and `_cancel_order` get real denial bodies**; the other four raise a plain
unsupported error.

This is the increment that **publishes the first `AccountState`, and therefore the increment that
makes every notional and position cap live for the first time.** Nothing before it is protected
by a Nautilus cap.

Two inherited traps to handle explicitly:
- `generate_mass_status` returns `None` on **any** exception (`live/execution_client.py:498-514`)
  → reconciliation failure → the trader never starts. Catch and report inside, never leak.
- `avg_px_open is None` walks five fallbacks ending at `instrument.make_price(0.0)` — a position
  entered at price **zero**. `UserPosition` has **no average-entry-price field** (only `cost`,
  `qtyBought`, `netPosition`, all `total=False`). **Design:** for positions Breezy opened
  in-process, supply `avg_px_open` from our own `executions[].lastPx`; **refuse** (do not
  synthesize) for foreign positions. A flat account emits no position reports, so R-8 is
  reachable before `cost` semantics are known — they first bind at the restart after the first
  fill (OQ-1).

**No client-order-id exists at this venue.** Every Breezy order would otherwise reconcile as
EXTERNAL. Keep an in-process venue-`id` → `ClientOrderId` map seeded from the synchronous
`CreateOrderResponse.id`, **persisted in `SqliteStateStore`** — the Nautilus cache is memory-only
under `database=None`, so without persistence a restart orphans the position.

**RED:** account state published with the right `AccountId` and USD balance; mass status on an
empty account returns an empty-but-non-`None` status; a foreign position with no derivable entry
price is **refused**, never priced at zero; `_submit_order` refuses; the ordering test above goes
green at step 2.
**Done when:** the node starts, reconciles a flat account, and refuses every order.

### R-5 — Live signing probe (paired barrier)

**Null hypothesis:** signing is unknown. **REFUTED** — `sdk_snapshot/.../auth.py` documents
`message = f"{timestamp}{method}{path}"`, no body, and `client.py:132` uses it for **every**
method including POST. Residual risk is exactly one live confirmation (OQ-2).

**Probe:** `POST /v1/orders/open/cancel` with a **non-empty** body (`{"slugs": [<one slug>]}`)
while `GET /v1/orders/open` proves that slug flat. Two requests, max. **Cannot open exposure** —
cancel-all is the only write verb that is strictly exposure-reducing. Follow the two-hypothesis
discriminating shape already proven in `_probe_signing_variants`
(`polymarket_us_auth_smoke.py` ~`:1050-1095`), including the "both accepted" and "inconclusive"
branches.

**Paired barriers (same commit as the narrowing):**
- Add a **third** canonical-string builder consuming the already-inert `CanonicalRequest.body`
  seam (`signing.py:122`) and narrow the inertness pin to name the new consumer.
- Add a **separate** `PolymarketUSWriteTransport` protocol rather than widening the GET-only
  closure (`transport.py:129`) or the module-level `PERMITTED_METHODS` (`signing.py:84`).
- Narrow B7 (zero permit callers) to **exactly one** caller at an exact path, with a non-vacuity
  proof: remove the caller and the test must fail.

Also fix `NautilusHttpTransport.get` (`transport.py:328-365`), which collapses `HttpError` and
`HttpTimeoutError` into one `VenueTransportError` with `from None` — **destroying the timeout
signal the R-7 ambiguity latch depends on.** The write transport must preserve it.

**RED:** write transport refuses any method outside its own allowlist; body joins the canonical
string in the new builder and does not in the old one; barrier tests fail without their pairs.
**Done when:** signing is confirmed live, or the probe returns inconclusive and R-7 is blocked.

### R-6 — Live order guard + Breezy-owned caps

**Null hypothesis:** a new guard is needed. **REFUTED** — `BacktestOrderGuard`
(`runtime/backtest_order_guard.py:107-205`) is already venue-agnostic; it touches only
`cache.orders_open(instrument_id=...)` and `portfolio.net_position(...)`. **Only
`install_order_guard` (`:208`) is backtest-typed.** The live installer is a ~3-line sibling
taking `(portfolio, cache, msgbus)` and subscribing to `ORDER_EVENT_TOPIC` (`:80`).

**One required behaviour change:** with `generate_missing_orders=True`, reconciliation emits
RECONCILIATION-tagged LIMIT orders including opposite-side SELLs, which would trip
`_refuse_naked_short` and crash the node. The live installer must **exempt RECONCILIATION-tagged
orders** — and only those.

**Breezy-owned caps.** `safety.py` already enforces per-order and per-session notional
(`BREEZY_MAX_ORDER_NOTIONAL_USD`, `BREEZY_MAX_SESSION_NOTIONAL_USD`, …, none with defaults).
The two operator-reserved controls are **different quantities** and are added here as
mechanism-only: max **daily** budget (rolling calendar-day spend-down) and max **per position**.
Unit declaration (L-2): for a long-only binary book max loss = premium = price x qty, so *max per
position* is measured in **USD cost**, not contracts. **Both values are left unset; unset fails
closed.**

**RED:** guard installs on a live-shaped msgbus and refuses a naked short; a
RECONCILIATION-tagged SELL passes; an order exceeding a *set* daily budget is refused; an
**unset** daily budget refuses everything (fail-closed), and the refusal names the missing
control.
**Done when:** the live node reconciles with the guard installed and no crash.

### R-7 — `_submit_order` + `POST /v1/orders` with the ambiguity latch

**Null hypothesis:** Nautilus classifies ambiguous submits. **CONFIRMED present** — the native
Command-outcome taxonomy (definitive local failure / definitive result / unknown live outcome)
is exactly `{terminal, retryable, AMBIGUOUS}`. We map onto it; we do not invent a taxonomy.

**IOC only.** Marketable, taker, long-only. Send `synchronousExecution=True` with `maxBlockTime`
(OQ-4) so the fill returns inline.

**Ambiguity latch.** On timeout or any non-definitive response, latch `SUBMIT_AMBIGUOUS`:
**never resubmit**, reconcile only, and halt new submissions until an operator clears it. This is
required because the venue has no client-order-id — a resubmit cannot be deduplicated and would
silently double the position.

**Nautilus in-flight checks.** The 1.231.0 docs say `inflight_check_retries` are retries to
**verify**, not to resubmit — so the earlier premise appears refuted and the real hazard is a
*false terminal* after the retry budget on orders we cannot query by ID. Both readings imply the
same action: `inflight_check_interval_ms=0` (documented "set to 0 to disable"). Confirm against
`nautilus_trader/live/execution_engine.pyx` before R-8; the plan is robust either way.

**RED:** a timeout latches `SUBMIT_AMBIGUOUS` and a second submit is refused; a definitive reject
does **not** latch; the venue `id` is mapped to the `ClientOrderId` and persisted; a submit
without a permit is refused at `safety.py:626`; a non-IOC order is refused.
**Done when:** all green under the no-egress gate, with the risk-engine ordering test green.

### R-8 — The first real order

Operator present. **One contract**, marketable, IOC. Target a **losing rung offered at 0.01 in
large size** (L-7/L-9): bounded known loss of ~$0.01 plus fees, maximum path evidence at minimum
cost. This proves the order path — **it is not an ROI sample**, and no ROI claim may cite it.

**Done when** the goal-state predicate at the top of this document holds, including the restart
reconciliation.

### R-9 — Settlement as exit

Not needed to place one order; **strictly required to compute the ROI confidence interval.**
Settlement truth is already in hand and venue-portable (both venues settle on NWS), so this is a
mapping increment, not a research one. Existing settlement tests are protected — none may be
weakened to land it.

**Done when** a filled position produces one realized-PnL row through settlement, and the
per-trade return feeds the CI estimator. At sigma/mu ~ 8 per trade, roughly **n ~ 300
station-days** are needed before a lower bound can clear break-even; R-9 starts that clock.

---

## Risks, sharpest first

**Resolvable now (before any real order)**
1. **Risk caps inert without an account** (`risk/engine.pyx:682-692`). Mitigation: the ordering
   test + HALTED-until-account. If both mechanisms fail, R-7 does not land.
2. **Money rounded by bare `json.loads`** on float-typed balances. Mitigation: R-3
   `parse_float=Decimal`, pinned by test.
3. **No client-order-id ⇒ everything reconciles EXTERNAL, and a restart orphans it.** Mitigation:
   persisted id map in `SqliteStateStore`.
4. **Reconciliation SELLs crash the guard.** Mitigation: R-6 RECONCILIATION exemption.
5. **Timeout signal destroyed at `transport.py:328-365`** → the latch cannot distinguish
   ambiguous from terminal. Mitigation: preserve it in the write transport (R-5).
6. **`generate_mass_status` swallowing an exception to `None`** → the trader never starts, with no
   diagnostic. Mitigation: internal catch-and-report (R-4).
7. **No instrument-level price bound** — `binary_option.pyx:144-145` passes
   `max_price=None, min_price=None`, so `Price(0.00)`/`Price(1.00)` are constructible and
   Breezy's own guard (`parsing.py:282-283`) is *inclusive*. Mitigation: refuse 0.00/1.00 at the
   Breezy submit precondition; do not rely on the instrument.

**Resolvable ONLY by a real order**
8. **`cost` semantics on `UserPosition`** — no avg-entry field exists; whether `cost` is signed,
   cumulative, or net cannot be learned from a flat account (OQ-1). Binds at the first restart
   after a fill, not before R-8.
9. **Whether the body joins the canonical signing string** (OQ-2) — R-5 narrows this to one live
   confirmation, but only a real signed write settles it.
10. **Whether `synchronousExecution=True` actually returns `executions` inline**, and the unit of
    `maxBlockTime` (OQ-4). If it does not, R-7's fill path needs a poll and OQ-6 reopens.

## Open questions

| # | Question | Closed by | Needs a real order? |
|---|---|---|---|
| OQ-1 | Does `/v1/portfolio/positions` carry a usable average entry price at a known scale? | R-1 shape / R-4 design | **Yes** for semantics; shape now. Hard prerequisite for reconciling a non-Breezy position. |
| OQ-2 | Does the request body join the canonical signing string? | R-5 | **Yes** (one live confirmation) |
| OQ-3 | Is `POST /v1/order/preview` non-mutating? | R-5 (secondary probe) | Yes — do not assume; if unproven, do not call it |
| OQ-4 | Does `synchronousExecution=True` return `executions` inline, and what unit is `maxBlockTime`? | R-7 | **Yes** |
| OQ-5 | Do `inflight_check_retries` verify or resubmit in 1.231.0? | R-2/R-7 code read of `live/execution_engine.pyx` | No |
| OQ-6 | Does `GET /v1/orders/open` return orders Breezy did not place? | R-1 / R-4 | No (observable while flat) |
| OQ-7 | Does the existing `_SHORT` ban collide with reading `intent` on an open order? | R-4 | No |

## Verification

Every increment runs `scripts/ci/run_tests_no_egress.sh`. RED output is kept as the change
artifact for each increment. No increment is "done" on a claim; done means the named tests are
green under the gate and the completion criteria above are demonstrated.
