# Order egress — implementation plan

**Status:** REVISION 1. Not executed. Not yet peer-reviewed.
**Created:** 2026-08-31.
**Closes:** LESSONS `L-3` — the active plan `DATA_CAPTURE_AND_RISK_PLAN.md`, executed
perfectly to completion, still ends with a bot that cannot place an order
(`LESSONS.md:104-146`). This document is the missing workstream, decomposed.

**Authority chain.** `EXECUTION_CLIENT_NATIVE_AUDIT_2026-08-31.md` (Nautilus side,
H-1..H-6) and `EGRESS_PREREQUISITES_2026-08-31.md` (cage + venue side, A-0..A-4,
B-0..B-5, C) are the evidence base and win on fact. `TRADING_SYSTEM_ARCHITECTURE.md`
§8 is the prior design and is retained where the evidence does not refute it;
§10 below lists every place it is now refuted. `GO_LIVE_PLAN.md` Phase F
(`:227-236`) is the only prior written home of this workstream and is SUPERSEDED
(`:3-17`) — it is cited here for the *existence* of the workstream and the
operator gates D1-D5 (`:242-251`) and for nothing else.

**Companion, not superseded.** `DATA_CAPTURE_AND_RISK_PLAN.md` remains the active
plan for P0-P7. This plan does not re-plan it. §2.3 of that plan
(`:286-302`) declares the exposure unit that every cap here is measured in and
is treated as fixed input.

---

## 0. Evidence status

### 0.1 Classes of claim used below

| Tag | Meaning |
|---|---|
| `[V]` | **Verified in this planning pass** by direct read of the cited file at the cited line. |
| `[E]` | Inherited from a committed evidence doc that states it was orchestrator-verified. Cited to the evidence doc AND to its own source cite. |
| `[I]` | **Inferred** — a design consequence I drew, not a fact read off a file. Flagged everywhere it appears. |
| `[U]` | **Unknown.** Never assumed away. Every `[U]` has an entry in §7 or §8. |

### 0.2 New facts established in this pass (not in either evidence doc)

These are `[V]` and they change the build order. Adversarial reviewers should
attack these first, because nothing upstream has reviewed them.

| # | Fact | Cite | Consequence |
|---|---|---|---|
| **N-1** | The **entire** report / account / reconciliation surface the venue exposes is `GET`: `GET /v1/account/balances` (`sdk_snapshot/polymarket_us_0.1.2/resources/account.py:15`), `GET /v1/portfolio/positions` (`resources/portfolio.py:19`), `GET /v1/portfolio/activities` (`:24`), `GET /v1/orders/open` (`resources/orders.py:34`), `GET /v1/order/{order_id}` (`:42`). Only submit (`POST /v1/orders`, `:27`), cancel (`POST /v1/order/{id}/cancel`, `:47`), modify (`:55`), cancel-all (`:62`), preview (`:70`) and close-position (`:78`) are `POST`. | above | A **fully functional, reconciling `LiveExecutionClient` that refuses every order** can be built on the EXISTING byte-identical GET-only read stack, with **zero write capability anywhere in the tree**. This is the single largest de-risking available and it drives §6's ordering. |
| **N-2** | `max_notional_per_order` is `dict[str, int]` **keyed by instrument-id string** and is populated ONLY from static config at `RiskEngineConfig` load (`NT/risk/engine.pyx:192-196`); the lookup is `self._max_notional_per_order.get(instrument.id)` (`:670`) and a miss leaves `max_notional = None`, so the cap at `:912-917` **never fires**. | `NT/risk/engine.pyx:192-196, 670-672, 912-917`; `NT/risk/config.py:44` | Breezy discovers its instrument universe at RUNTIME (`provider.py`, `factories.py:393-400`), so the config dict is necessarily empty and H-2's "good news" cap is **inert by default**. Native remedy exists and is a *runtime call*: `cpdef set_max_notional_per_order` (`NT/risk/engine.pyx:279`). See §3.2 and increment E-4. |
| **N-3** | For a **LIMIT** order `last_px = order.price` (`NT/risk/engine.pyx:855`) and `effective_price = last_px` (`:875`), so the checked notional is `qty × limit_price`. For an order with **neither** a price nor a trigger price (i.e. **MARKET**), control enters the trailing-stop branch and, absent cached market data, hits `self._log.warning(...)` then **`continue`** (`:848-851`) — the order is skipped, not denied. | `NT/risk/engine.pyx:818-856, 871-880, 907` | **Breezy must never emit a MARKET order.** This is a fourth fail-open on the same code path as H-1. Contract test in E-4. |
| **N-4** | `CreateOrderRequest` carries `synchronousExecution: bool` and `maxBlockTime`, described as "will block until the order is filled, rejected, canceled, or expired" (`docs_snapshots/api-reference_orders_create-order_2026-08-25.md:107-113`), and `CreateOrderResponse` carries only `id` and `executions` (`:127-139`). | above | Confirms B-1 independently: the response echoes no client-supplied identity. `synchronousExecution` is a *candidate* ambiguity-reducer and is **not adopted** — see OQ-6. |
| **N-5** | `participateDontInitiate` ("order must rest on the book prior to matching (maker only)") is a first-class request field (`create-order:85-89`). | above | The post-only refusal (B-3, `fees.py:199-208`) must be re-expressed as a *request-construction* refusal at the execution boundary, not only a fee-model refusal. |
| **N-6** | `_query_account` is **called** at `NT/live/execution_client.py:332` and has **no definition** in the file; `_query_order` **is** defined at `:516`. | above | H-4 confirmed by direct read. Only `_query_account` is missing. |

### 0.3 What was NOT verified in this pass

- The bodies of `nautilus_pyo3.calculate_reconciliation_price` (Rust, unreadable) — inherited `[E]`.
- Whether `Price(0.00)` / `Price(1.00)` survive fill validation — inherited `[E]`, still `[U]`. RED test in E-5.
- `_reconcile_position_report_hedging` — not read; Breezy is NETTING (`[I]`, pin it in E-3).
- Every `[U]` in §7.

---

## 1. GOAL STATE and WALK (LESSONS L-3)

### GOAL STATE (falsifiable predicate)

> With operator gates D1-D5 set and a permit issued, a running Breezy `TradingNode`:
> **G1** reconciles a **true** venue account at startup — a non-`None` `Account`
> is in the Nautilus `Cache` before the first `SubmitOrder` is accepted, sourced
> from `GET /v1/account/balances`, and startup reconciliation is asserted to have
> SUCCEEDED rather than swallowed.
> **G2** accepts a strategy `SubmitOrder` for a weather `BinaryOption`, translates
> it to a signed `POST /v1/orders`, and drives it through Nautilus's native order
> state machine to a terminal state (`FILLED`/`CANCELED`/`REJECTED`) off **real
> venue events**, with no Breezy-authored state machine, retry loop or position
> ledger.
> **G3** exits at settlement with realized PnL equal to
> `qty × (settlementPx − avg_px_open) − fees` — **not** zero, **not** a stale quote.
> **G4** refuses, with a **named, counted refusal raised before Nautilus is
> consulted**, every order it cannot price, size, direction-encode or account for:
> no cached account, MARKET type, post-only, SELL under `allow_short=False`,
> unpopulated per-instrument notional cap, unsupported order type, unresolved
> `SUBMIT_AMBIGUOUS` latch.
> **G5** does all of the above with **no** cage barrier deleted or weakened,
> evidenced by every barrier's paired non-vacuity proof still passing.

**Falsifier.** Any of G1-G5 failing against the live venue; or the full suite
passing green while any of G1-G5 is unimplemented. G5's falsifier is specific:
a barrier whose *scope* narrowed without a strictly stronger assertion landing in
the **same commit**.

### WALK (checked end-to-end, not increment-by-increment)

```
E-0  arm the firewall for the exec/ directory      ──▶ G5 precondition; makes E-1..E-12 non-silent
E-1  cage strengthening, zero exec code            ──▶ G5
E-2  exec/endpoints.py + read-only venue reports   ──▶ G1 (data), G4 (report inputs)
E-3  exec/client.py, refuses everything            ──▶ G1 (AccountState emitted, reconciliation asserted), G2 (skeleton)
E-4  Breezy-side denial layer + runtime caps       ──▶ G4 complete
E-5  settlement exit                               ──▶ G3 complete
E-6  exec/{signing,transport,egress}.py, allowlist = {cancel-all}
                                                   ──▶ G2 (write chain exists; cannot open exposure)
E-7  signature-scheme probe (cancel-all when flat) ──▶ resolves OQ-1 (body in canonical string)
E-8  allowlist += preview; preview probe           ──▶ resolves OQ-2 (preview mutation), OQ-3 (direction), OQ-5 (fractional qty)
E-9  SUBMIT_AMBIGUOUS latch + one-in-flight        ──▶ G2 (safe under the 5s stopgap), G4
E-10 allowlist += POST /v1/orders; _submit_order   ──▶ G2 COMPLETE — first exposure-opening capability
E-11 allowlist += cancel; _cancel_order            ──▶ G2 (working-order management), G4 (kill switch has teeth)
E-12 single-order live probe + evidence            ──▶ G1..G5 all demonstrated on the live venue
```

**Where the walk is checked, not assumed.** G1 lands at **E-3** — `AccountState`
emission is the *first* thing `_connect` does and everything after depends on it.
G3 lands at **E-5** and G4 at **E-4**, both *before* any write capability exists
(E-6): settlement is the only exit (`AUDIT:97`), so the exit and the refusals must
work before the entrance opens. G2 is **not** reached until **E-10**; E-6 creates
the write chain but its allowlist holds one entry that cannot open exposure.
**No increment depends on an unresolved `[U]`** — E-10 is gated on E-7/E-8 having
*resolved* OQ-1/OQ-2/OQ-3, and §7 says what happens if they do not.

**The gap this walk exposes:** without E-2/E-3, G1 is unreachable and H-1 silently
disarms every native risk check — so a plan starting at the write path would reach
a green suite that proves nothing.

---

## 2. Reuse ledger

### 2.1 Nautilus provides it — do NOT rebuild (null hypothesis CONFIRMED)

`[E]`, all from `EXECUTION_CLIENT_NATIVE_AUDIT_2026-08-31.md:133-142` with its
own cites into the installed `nautilus_trader==1.231.0`:

| Capability | Native anchor | Breezy's job |
|---|---|---|
| Order state machine, 14 states | `NT/model/enums.py:383-397` | none |
| Lifecycle event construction + msgbus routing | `NT/execution/client.pyx:329-917` (`generate_account_state:329`, `generate_order_denied:370`, `generate_order_submitted:411`, `generate_order_rejected:447`, `generate_order_accepted:491`, `generate_order_filled:820`) `[V]` | call them |
| Order cache, `orders_open`/`orders_inflight` | `NT/execution/client.pyx` + `Cache` | none |
| Position tracking, OMS position-ID resolution | `:826, 853-857` | none |
| Startup + continuous reconciliation, in-flight recovery | `NT/live/execution_engine.py` | supply reports |
| **Exponential backoff / retry** | `NT/live/retry.py:24-62`; `RetryManagerPool` `:242` `[V]` | **wire it; never write a backoff loop** |
| Submit-rate throttling | `NT/risk/engine.pyx:142, 1084` | configure |
| `TradingState` kill gating | `NT/risk/engine.pyx:556-580` | configure |
| Native IOC | `TimeInForce.IOC`, `NT/model/enums.py:446-453` | map |
| `BinaryOption` as a first-class 0-1 instrument | `NT/model/instruments/binary_option.pyx` | already built (`parsing.py:1200-1221` `[V]`) |
| Per-order notional cap | `NT/risk/engine.pyx:912-917` — **but see N-2** | populate at runtime |
| Rate-limited pooled HTTP with keyed quotas | `nautilus_pyo3.HttpClient` | already wrapped |

**Explicitly do not "improve":** `CashAccount.calculate_pnls` special-cases
`InstrumentClass.SPORTS_BETTING` only; `BinaryOption` is `BINARY_OPTION` and
takes the generic `notional_value` branch, which is arithmetically correct at
multiplier=1 (`AUDIT:144-149` `[E]`). `AccountType.BETTING` /
`accounting/accounts/betting.pyx` is a **different** model (back/lay stake) and
is **not** a drop-in — banned by name in E-1.

### 2.2 The existing read adapter provides it — reuse VERBATIM

All `[V]`, all constructed together at `factories.py:366-400`:

| Component | Path | Reused for | Changed? |
|---|---|---|---|
| `Ed25519RequestSigner` | `signing.py:185-286` | nothing on the write path — see §3.2 | **BYTE-IDENTICAL.** `PERMITTED_METHODS = frozenset({"GET"})` (`signing.py:84`) is never widened. |
| `NautilusHttpTransport` | `transport.py:237-368` | all read/report/account traffic in E-2, E-3 | **BYTE-IDENTICAL.** Its `_build_get_only_callable` (`:129-148`) B3 closure is untouched. |
| `PolymarketUSHttpClient` | `http.py:94-270` | `get_authenticated` for balances/positions/orders/activities | **BYTE-IDENTICAL.** `PERMITTED_METHODS` (`http.py:64`) never widened. |
| `PolymarketUSInstrumentProvider` | `provider.py` | shared instrument cache between data and exec clients | unchanged |
| `PolymarketUSCredentials` + loader | `credentials.py`, `factories.py:364` | the exec client's own credential load | unchanged |
| `assert_live_order_submission_permitted` / `issue_live_trading_permit` / `LiveOrderSubmissionAuthorization` | `safety.py:527-716` | the capability chain | **one** typed-strictness fix (A-2, `safety.py:463`); no semantic change |
| `PolymarketUSFeeModel` maker refusal | `fees.py:190-208` | mirrored at the execution boundary (N-5) | unchanged; **extended**, not replaced |
| Venue settlement price parsing | `parsing.py:1020-1034` (`InstrumentClose` from `stats.settlementPx`) | the settlement exit price of E-5 | unchanged |
| `PolymarketUSLiveDataClientFactory` shape | `factories.py:320-437` | template for the exec factory | unchanged |

### 2.3 GENUINELY ABSENT — the short list Breezy must author

Searched: `NT/execution/`, `NT/live/`, `NT/risk/`, `NT/accounting/` and the
adapter package. Negatives are credible because the searches are named.

1. **Venue protocol translation.** `SubmitOrder` → `CreateOrderRequest` JSON, and
   venue order/fill/position/balance JSON → `OrderStatusReport` / `FillReport` /
   `PositionStatusReport` / `AccountState`. Nautilus supplies the report *types*
   and nothing that fills them from this venue.
2. **`AccountState` emission.** `generate_account_state` exists
   (`NT/execution/client.pyx:329`) but **nothing calls it for you**
   (`AUDIT:36-40` `[E]`); `NT/live/node_builder.py:201-263` never seeds an account.
3. **Settlement-as-exit semantics.** `grep -n "settle|Settle" NT/execution/engine.pyx`
   → zero matches (`AUDIT:90-93` `[E]`). `InstrumentClose` is data-side only.
4. **Per-venue order-type refusal.** Nautilus validates price, quantity and GTD
   expiry only (`NT/risk/engine.pyx:584-606`); order-type support is *entirely* the
   client's job (`AUDIT:160-169` `[E]`). 7 of 9 Nautilus types must be refused
   because the venue exposes only LIMIT/MARKET (`sdk_snapshot/.../types/orders.py:7`
   `[E]`) — and MARKET is refused too (N-3).
5. **`SUBMIT_AMBIGUOUS` latch + one-in-flight-per-market invariant** — the
   substitute for the missing venue idempotency key (B-1). Nautilus's in-flight
   check (`inflight_check_interval_ms=2000`, `NT/live/config.py:184` `[V]`) queries
   by `ClientOrderId`, which this venue does not echo.
6. **The write-side signing/transport/egress chain and its capability threading.**
7. **A reserved data-path share** of the 20 req/s key-wide budget that egress
   cannot consume (B-4 `[E]`; `api-reference_rate-limits_2026-08-25.md:15` `[V]`).

Everything not on this list is a *configuration* task, not a build task.

---

## 3. The unit ledger (LESSONS L-2)

Every native substitution below carries `unit before / unit after / equal because`.
No substitution ships without one.

### 3.1 The system unit

Fixed input from `DATA_CAPTURE_AND_RISK_PLAN.md:288`: **every ceiling is
PREMIUM AT RISK, in USD.** This plan introduces no second unit.

### 3.2 `max_notional_per_order` — a genuine native fit, written down

**unit before** = Breezy §2.3 per-order ceiling = `qty × entry_price` USD premium
(`DATA_CAPTURE_AND_RISK_PLAN.md:298`). **unit after** =
`instrument.notional_value(effective_quantity, last_px)` → non-inverse
`qty × multiplier × price` (`NT/model/instruments/base.pyx:844` `[E]`) with
`BinaryOption` multiplier hardcoded to `1` (`binary_option.pyx:138` `[E]`), and
for a **LIMIT** order `last_px = order.price` (`NT/risk/engine.pyx:855` `[V]`),
`effective_price = last_px` (`:875` `[V]`) → `qty × limit_price` USD.
**equal because** multiplier is 1, so the native notional is cash outlay, not
payout; and for a BUY LIMIT the limit price is the **maximum** price payable, so
`qty × limit_price ≥ qty × fill_price` = premium actually at risk. The
substitution is an **upper bound**, conservative in the safe direction; an
equality only for a resting limit that fills at its own price.
**Conversion rule, recorded once:** a payout-denominated Breezy cap converts as
`cost_cap = payout_cap × price` (`AUDIT:71` `[E]`) — at p=0.05 the native cap is
20× *smaller* than a payout cap, the inverse of L-2's `net_exposure` mistake.
**Caveat:** see N-2 — the cap is inert until `set_max_notional_per_order` is
called per discovered instrument (`NT/risk/engine.pyx:279` `[V]`). E-4 does that.

### 3.3 `PortfolioFacade.equity()` is NOT Breezy's `_equity()` — DO NOT SUBSTITUTE

**unit before** = `self._config.starting_equity`, a static configured float
(`strategy/forecast_revision/strategy.py:411`, `calibration_mean_reversion/strategy.py:437`,
`forecast_mispricing/strategy.py:411` `[V]`). **unit after** = native
`PortfolioFacade.equity()` (`NT/portfolio/base.pyx:67`) = account balance **plus
the mark value of open positions** (`DATA_CAPTURE_AND_RISK_PLAN.md` §0.3 `[E]`).
**NOT equal** — native equity moves with the mark, so an equity-fraction cap
computed from it *ratchets up* as open positions appreciate: the exact
mark-to-market-in-a-ceiling defect L-2 was written about (`LESSONS.md:83-84`).
**Disposition: no substitution in this plan.** Once E-3 emits `AccountState`,
`equity()` returns a real number for the first time and the substitution becomes
*tempting*; it is named here so that temptation is a reviewed decision later, not
a silent one. Barrier in E-4: a static test that no strategy or sizing module
calls `portfolio.equity(` / `net_exposure(` / `net_exposures(`.

### 3.4 `AccountBalance` free vs total — a unit decision on emission

The native free-balance guard reads `account.balance_free(instrument.quote_currency)`
(`NT/risk/engine.pyx:696` `[V]`). **Decision:** `AccountBalance.free` is emitted
from the venue's **available/withdrawable** figure, never a total including
open-order-locked collateral; `locked` carries the difference. **equal because**
the guard's semantics are "cash available to spend on a new order" = available
not locked; emitting `total` as `free` would loosen the guard by the locked
amount — the fail-open direction. `[U]` the exact field names on
`GetAccountBalancesResponse` are unread (OQ-7); the decision above is the *rule*,
and the mapping is pinned by a contract test in E-3 against a captured payload.

---

## 4. Module layout

```
src/breezy/adapters/polymarket_us/
    http.py  transport.py  signing.py    ← UNCHANGED, BYTE-FOR-BYTE. GET-only.
    exec/
        __init__.py        (E-0)  docstring only; its existence arms N2
        endpoints.py       (E-2)  the ONLY module holding venue order-path literals
        reports.py         (E-2)  venue JSON → Nautilus report objects; pure, no I/O
        client.py          (E-3)  the ONE LiveExecutionClient subclass
        denial.py          (E-4)  Breezy-side pre-Nautilus refusals
        settlement.py      (E-5)  settlement → explicit fill
        signing.py         (E-6)  own key load, own method frozenset, own canonicalisation
        transport.py       (E-6)  write-capable pyo3 client; own quota bucket
        egress.py          (E-6)  the single dispatch surface; holds the capability chain
        ambiguity.py       (E-9)  SUBMIT_AMBIGUOUS latch + one-in-flight registry
        config.py          (E-3)  PolymarketUSExecClientConfig
        factories.py       (E-3)  PolymarketUSLiveExecClientFactory
```

Per-module contract. "Trips" names the barrier the module's *existence or content*
violates today; "Paired assertion" is the strictly-stronger check that must land in
the **same commit** as the allowance.

| Module | Responsibility | MUST NOT contain | Trips | Paired assertion earning the allowance |
|---|---|---|---|---|
| `exec/__init__.py` | Nothing. A docstring naming this plan. | any import, any code | **N2/E0** (new rule) | N2 goes from vacuous to live: from this commit the suite requires an attested + substantiated OS firewall. `test_n2_the_shipped_tree_currently_has_no_execution_egress_module` (`test_execution_egress_firewall_guard.py:592`) is **inverted** to assert the set is exactly the known exec paths. |
| `exec/endpoints.py` | Every venue path template + method, as data. | any HTTP call, any `.post`/`.request` attribute, any decision | **B4/V2** (`_ORDER_PATH_RE` matches `/v1/orders`, `/v1/orders/open`, `/v1/order/{id}`) | V2 exemption is an **exact-path allowlist of this one file**, paired with: the file's path literals are an **equality-pinned frozenset** (`==`, not `<=`); every entry is `(method, template)` and the methods frozenset is equality-pinned; `assert is_venue_touching("src/.../exec/endpoints.py", tree) is True`. V1/V3/V4 still apply here in full — no write-method literal, no `.post`. |
| `exec/reports.py` | Pure venue-JSON → `OrderStatusReport` / `FillReport` / `PositionStatusReport` / `AccountState` mapping. | I/O, clocks, decisions | none | pure-function test suite; a test asserting the module imports nothing from `exec/transport.py` or `exec/egress.py`. |
| `exec/client.py` | The ONE `LiveExecutionClient` subclass. Lifecycle, report coroutines, `_query_account`, `_query_order`, delegation to `denial`/`egress`. | **any write verb** (per arch §8.3 N3, `TRADING_SYSTEM_ARCHITECTURE.md:1327-1332`); any endpoint literal; any signing | **B6b** (`test_adapter_package_defines_no_live_execution_client`, `test_polymarket_us_readonly_guard.py:550`); **N2/E2** | B6b is **narrowed, not deleted**: exactly **one** subclass exists, at this exact path, and the `LiveExecutionClient` import appears in no other module. Zero **and** two both fail. This is the non-vacuity proof B6b never had (A-3). |
| `exec/denial.py` | Every Breezy-side refusal, each a named exception with a counter. | network, endpoints, signing | none | each refusal has a contract test that EXECUTES the path and asserts the refusal happens **before** Nautilus is consulted. |
| `exec/settlement.py` | Settlement price → explicit `generate_order_filled`. | network | none | RED test that a `Price` of exactly `0.00`/`1.00` survives construction and fill validation, written and failing before the module exists. |
| `exec/signing.py` | Own Ed25519 key load, own `PERMITTED_METHODS` frozenset, own canonicalisation, path-segment validation, permit provenance verification. | any import from `polymarket_us/signing.py` | **B4/V1** (`"POST"` literal); **B2 is UNCHANGED** (B-0 `[E]`) | V1 exemption is an **exact-path allowlist of this one file**, paired with: its `PERMITTED_METHODS` is equality-pinned to exactly the set the plan names; a static test that `signing.PERMITTED_METHODS` is **never assigned to** from anywhere in `src/`/`scripts/` (closes A-4 #8, the rebinding widening); every interpolated path segment matches `^[A-Za-z0-9_-]+$` before entering the canonical string. |
| `exec/transport.py` | Write-capable pyo3 client, own quota bucket, refuses any `(method, path)` not on the frozen allowlist. | decisions, sizing, gates | **B4/V3** (`.post`) | V3 exemption is an **exact-path allowlist of this one file**, paired with: the dispatch signature **takes `LiveOrderSubmissionAuthorization` positionally** (skipping the chokepoint is a `TypeError`, arch §8.4) and **consumes** it before any I/O; the allowlist is an equality-pinned frozenset of `(method, path)` pairs; `PERMITTED_QUOTA_KEYS` on the read path (`transport.py:98-106`) gains **no** order bucket, asserted by equality pin. |
| `exec/egress.py` | The single dispatch surface: request construction, signing call, chokepoint call, capability threading, response parsing. **Under 200 lines** (arch §8.8). | decision logic, sizing, edge, gates, retry loops | **B6a** (`test_safety_chokepoint_has_no_caller_in_this_slice`, `readonly_guard.py:570`) | B6a is **narrowed, not deleted**: **exactly one** caller, at this exact path. `assert len(callers) == 1` — never `<= 1` (closes A-4 #5). Paired: the capability must be *consumed* (`consume(...)`) on every dispatch path, asserted by a test that a dispatch which skips `consume` fails (closes A-4 #6). |
| `exec/ambiguity.py` | `SUBMIT_AMBIGUOUS` latch, one-in-flight-per-`marketSlug` registry, fail-closed halt reads. | network | none | fail-closed test: an unreadable latch store resolves to `HALT_ALL_DISPATCH`, never permitted (arch §8.6). |
| `exec/config.py`, `exec/factories.py` | Config with every field required-no-default; factory mirroring `factories.py:320-437`. | defaults for any operator gate | **N7** (arch §8.3) | static scan: no `getenv` default, no `or`-fallback, no `try/except` producing a truthy value for `BREEZY_TRADING_ENABLED`. |

**Prefix rules vs allowlists — the distinction a reviewer will test.** The E0
rule *is* a directory prefix (`any file under exec/`) and that is correct: a
prefix used to **classify hazard** fails CLOSED as the directory grows. Every
*exemption* above is an **exact path** and never a prefix, because a prefix used
to **grant an allowance** fails OPEN as the directory grows (A-4 #1). Any review
comment conflating the two is answered here.

---

## 5. Cage rework contract

### 5.1 The invariant

**No barrier is deleted. Each barrier that must change is a narrowed
re-expression shipped with a strictly stronger assertion in the SAME commit.**
A commit that lands a narrowing without its pair is reverted, not amended.

### 5.2 Barrier disposition

| Barrier | Today | Becomes | Same-commit pair |
|---|---|---|---|
| **B1** `http.py:64` GET-only | data path | **UNCHANGED** | equality pin on `http.PERMITTED_METHODS` |
| **B2** `signing.py:84` GET-only | data path | **UNCHANGED** (B-0 `[E]`: signing is identical for writes, so a separate module suffices) | equality pin + no-rebinding scan |
| **B3** GET-only closure `transport.py:129-148, 325` | data path | **UNCHANGED**; `exec/transport.py` gets its **own** closure | `exec/transport.py`'s closure gets the same receiver-graph test (`readonly_guard.py:456-490`) |
| **B4/V1** write-method literal | all venue-touching | **NARROWED** to an exact-path allowlist of `exec/signing.py` | equality-pinned method frozenset in that file; `_WRITE_METHODS` itself becomes equality-pinned |
| **B4/V2** order-path literal | all venue-touching | **NARROWED** to an exact-path allowlist of `exec/endpoints.py` | equality-pinned `(method, template)` frozenset; `_ORDER_PATH_RE` becomes equality-pinned |
| **B4/V3** write attribute | all venue-touching | **NARROWED** to an exact-path allowlist of `exec/transport.py` | `.request` remains banned **everywhere including the allowlisted files**; `_WRITE_ATTRS` becomes equality-pinned |
| **B4/V4** `getattr` bypass | all venue-touching | **UNCHANGED, everywhere** | — |
| **B5** SDK signing import ban | repo-wide | **UNCHANGED** | `SDK_IMPORT_ORACLE` becomes equality-pinned |
| **B6a** chokepoint has **zero** callers | `src`,`scripts` | **exactly ONE**, at `exec/egress.py` | `== 1`; plus capability-must-be-consumed test |
| **B6b** no execution client | adapter pkg | **exactly ONE** subclass, at `exec/client.py`; import nowhere else | `== 1`; plus the import-site scan |
| **N1** pyo3 clients blocked in tests | CI | **UNCHANGED** | — |
| **N2** firewall-before-egress | CI | **EXTENDED** with the E0 path rule and the underscore verbs | the "currently empty" pin (`:592`) inverts to an exact-set pin |
| **node_config** both sites empty-literal | `node_config.py:204,212,218,460,463,464` `[V]` | recorder site stays empty; trading site pinned to **exactly one** `exec_clients` key | `len(_node_config_calls()) == 2` retained (`test_runtime_node_config.py:338-339`) |
| **F2 / N6** `SandboxExecutionClient` | — | **banned** by import and construction (arch §9.1) | static scan + a test that the ban is not vacuous |
| **new** `accounting/accounts/betting.pyx` / `AccountType.BETTING` | — | **banned** by name | `AUDIT:148-149`: a different model, not a drop-in |

### 5.3 A-4's eight silent-failure modes, each with its counter

| # | Failure mode | Counter, and where it lands |
|---|---|---|
| 1 | Directory-prefix allowlist → permanent blanket exemption | every exemption is an exact path (§4); a test asserts each allowlist entry resolves to an existing file and that the allowlist frozenset is equality-pinned. **E-1** |
| 2 | Escaping the classifier — egress outside the adapter package, importing nothing, base URL from env | `assert is_venue_touching(p, ast.parse(read(p))) is True` for **every** path in §4's layout, including paths that do not exist yet. **E-1** |
| 3 | Loosening the global rule instead of allowlisting the file (a one-token diff at `readonly_guard.py:112-114` disarms 19 modules) | `_WRITE_METHODS`, `_WRITE_ATTRS`, `_ORDER_PATH_RE`, `EGRESS_SCAN_ROOTS`, `SDK_IMPORT_ORACLE`, `_EGRESS_MODULE_BASENAMES`, `_EGRESS_CLASS_SUFFIXES`, `_EGRESS_CLASS_BASES`, `_EGRESS_FUNCTION_NAMES` all become **equality-pinned**. **E-1** |
| 4 | N2 blindness to the planned filenames and underscore overrides (A-1) | **E-0**, increment #1 |
| 5 | B6a inverted to "at most one" → zero passes and the chokepoint is dead code | `== 1` exactly, plus a proof-by-construction that zero fails. **E-6** |
| 6 | Capability accepted but never consumed → single-use/expiry/replay inert while budget still decrements at mint | a test that a dispatch path which does not call `consume(...)` fails; a test that a second dispatch with the same capability raises. **E-6** |
| 7 | An exec test marked `allow_socket`/`live`/`venue_live`/`real_money` restores the real pyo3 clients and lifts the socket block (`tests/conftest.py:336-342, 397-404` `[E]`) | a static test asserting **no** test file under `tests/` that imports anything from `breezy.adapters.polymarket_us.exec` carries any of those four markers. **E-1** |
| 8 | Data-path widening by rebinding: `signing.PERMITTED_METHODS = frozenset({"GET","POST"})` from the exec module | AST scan banning assignment to `PERMITTED_METHODS` / `PERMITTED_QUOTA_KEYS` / `_WRITE_*` on any imported module object, repo-wide. **E-1** |

Plus **A-2** (`safety.py:463`, `consume()` does not type-check its notional; a
`Decimal` subclass overriding `__ne__` satisfies the re-check at any magnitude):
fix mirrors `safety.py:676`'s `if type(order_notional_usd) is not Decimal`.
Lands in **E-1** with a RED test using a lying `__ne__` subclass.

### 5.4 The five cage layers (A-0) — all five are in scope

A rework scoped to one file lands red, or lands green while the layer that
mattered was never seen (`PREREQ:25-26` `[E]`). The five:

1. `tests/unit/test_polymarket_us_readonly_guard.py` — B3, B4, B5, B6a, B6b, S16
2. production code — B1 (`http.py:64`), B2 (`signing.py:84`) and their own suites
3. `tests/unit/test_execution_egress_firewall_guard.py` — N1-N5
4. `tests/unit/test_runtime_node_config.py:333-349` — the empty-literal pin at **both** build sites
5. `tests/unit/test_polymarket_us_permit_issuance.py` — permit-constructor allowlist (`:756-781` `[V]`) and the blanket environment-write ban (`:1324-1387` `[V]`)

Every increment below names which of the five it touches.

---

## 6. Ordered increments

Every increment carries a **[NO-SEND]** / **[SEND]** marker. Summary of what
becomes reachable, so the answer is in one place:

| E-0 | E-1 | E-2 | E-3 | E-4 | E-5 | **E-6** | E-7 | E-8 | E-9 | **E-10** | E-11 | E-12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| none | none | GET | GET | GET | GET | **+`POST /v1/orders/open/cancel`** | = | +`POST /v1/order/preview` | = | **+`POST /v1/orders`** | +`POST /v1/order/{id}/cancel` | = |

> **Live order capability first becomes reachable at E-6**, and what becomes
> reachable is cancel-all only — it cannot open exposure. **Exposure-opening
> capability first becomes reachable at E-10.** Between them no commit widens the
> allowlist by more than one entry, and each widening is its own commit with its
> own equality pin. `POST /v1/order/{id}/modify`, `POST /v1/order/close-position`
> and the institutional `insert-order` surface are **never** added by this plan.

---

### E-0 — Arm the egress firewall for `exec/` · **[NO-SEND]** · MUST BE FIRST

**Why first (A-1 `[E, CRITICAL]`).** `_EGRESS_MODULE_BASENAMES`
(`test_execution_egress_firewall_guard.py:161-171` `[V]`) contains none of the
planned filenames, and `_EGRESS_FUNCTION_NAMES` (`:178-180` `[V]`) contains no
underscore form, while the Nautilus overrides a real client implements are
`_submit_order`, `_cancel_order`, … (`NT/live/execution_client.py:598-633` `[V]`).
Today N2 fires only through E2. **A write-capable `exec/transport.py` landing
before `exec/client.py` means `find_execution_egress_modules()` returns empty,
the firewall attestation is never demanded, and an ordinary `uv run pytest -q`
can transmit a signed live order with every gate green.** There is no retail
sandbox; every POST is real money (`TRADING_ENABLEMENT_FINDINGS.md:251` `[E]`).

**Goal.** Rule **E0**: any file under `src/breezy/adapters/polymarket_us/exec/`
is an execution-egress surface. Add the underscore forms to
`_EGRESS_FUNCTION_NAMES`. Create `exec/__init__.py` (docstring only) in the
**same commit**.

**RED first.** (a) An in-memory `exec/transport.py` with no class, no known
basename and no bare order verb yields a rule-`E0` violation — fails before the
rule exists. (b) A venue-touching module defining `async def _submit_order` is
detected as `E3`.

**Files.** `tests/unit/test_execution_egress_firewall_guard.py`;
`src/breezy/adapters/polymarket_us/exec/__init__.py`.

**Barriers.** Layer 3. Pure extension; nothing loosened.
`test_n2_the_shipped_tree_currently_has_no_execution_egress_module` (`:592`)
inverts to an **exact-set** pin naming `exec/__init__.py`, so N2 can never go
vacuous again.

**Completion.** Both REDs GREEN; `find_execution_egress_modules()` returns
exactly `[exec/__init__.py]`; **the full suite now requires
`scripts/ci/run_tests_no_egress.sh`** (`:139` `[V]`) — a bare `uv run pytest -q`
fails N2, and the runbook is updated in the same commit. The N4 classifier is
untouched: `Connection refused` still classifies as REACHED (`:331-334` `[V]`).

---

### E-1 — Cage strengthening, zero exec code · **[NO-SEND]**

**Goal.** Land every counter in §5.3 (#1, #2, #3, #6-prep, #7, #8) and the A-2
fix while the tree has no exec module beyond `__init__.py`. Strengthening before
narrowing means every later narrowing is measured against a pinned baseline.

**RED first — one per §5.3 counter, each written to fail on today's tree.**
(1) A `Decimal` subclass overriding `__ne__ → False` passes
`LiveOrderSubmissionAuthorization.consume(order_notional_usd=…)` at arbitrary
magnitude (A-2); fix mirrors `safety.py:676` at `:463`. (2) A one-token widening
of `_WRITE_METHODS` leaves the suite green (A-4 #3) — closed by equality pins on
all nine rule constants named in §5.3 #3. (3) A planted
`src/breezy/egress_outside_the_package.py` building its base URL from
`os.environ` is **not** venue-touching (A-4 #2) — closed by asserting
`is_venue_touching(p) is True` for **every** path in §4's layout, including paths
that do not yet exist. (4) A test file importing `…polymarket_us.exec` marked
`@pytest.mark.allow_socket` is undetected (A-4 #7). (5) Rebinding
`signing.PERMITTED_METHODS` from another module is unbanned (A-4 #8).

**Files.** `safety.py` (`:463` only); the three guard suites; new
`tests/unit/test_cage_rule_constants_are_pinned.py`.

**Barriers.** Layers 1, 2, 3, 5. Every change strictly stronger; no allowlist
created yet. `SandboxExecutionClient`, `AccountType.BETTING` and
`accounting/accounts/betting` banned by name with non-vacuity proofs.

---

### E-2 — `exec/endpoints.py` + `exec/reports.py` on the EXISTING GET stack · **[NO-SEND]**

**Null hypothesis: NATIVE — insufficient.** Nautilus defines `OrderStatusReport`,
`FillReport`, `PositionStatusReport` and gathers all three in
`generate_mass_status` (`NT/live/execution_client.py:499-503` `[V]`), which the
engine calls at startup (`NT/live/execution_engine.py:1709-1712` `[E]`). It
supplies no mapping from this venue's JSON. **GENUINELY ABSENT: the mapping only.**

**Goal.** A frozen endpoint table plus pure report mappers. All five sources are
`GET` (N-1), so this reuses `PolymarketUSHttpClient` **byte-identical** and adds
**no** write capability:

| Nautilus surface | Venue call `[V]` |
|---|---|
| `generate_account_state` | `GET /v1/account/balances` (`resources/account.py:15`) |
| `generate_position_status_reports` | `GET /v1/portfolio/positions` (`resources/portfolio.py:19`) |
| `generate_order_status_reports` | `GET /v1/orders/open` (`resources/orders.py:34`) |
| `generate_order_status_report` | `GET /v1/order/{order_id}` (`resources/orders.py:42`) |
| `generate_fill_reports` | `GET /v1/portfolio/activities` (`resources/portfolio.py:24`) — `[U]` OQ-8 |

**RED first.** Mapper tests against captured payloads. Where no payload has ever
been observed — **fills, and the fixed-point `price_scale` /
`fractional_quantity_scale` decoding** (B-2 #6 `[E]`) — the mapper **raises a
named error rather than guessing**, and that refusal is the RED. A guessed decode
that reads a price 100× wrong is worse than a refusal.

**Barriers.** Layer 1 — **B4/V2 narrowing, the first allowance in this plan**,
with the §4 pairing (exact-path allowlist for `exec/endpoints.py` +
equality-pinned `(method, template)` frozenset + `is_venue_touching` assertion).
V1/V3/V4 still apply in full to both new files: **no write-method literal and no
`.post` anywhere in this increment.** Layer 3: N2's exact-set pin grows by two.

**Completion.** Mappers round-trip captured payloads; unobserved shapes refuse by
name; `scan_write_egress()` reports zero violations outside the one V2-allowlisted
path.

---

### E-3 — `exec/client.py`: the execution client that refuses everything · **[NO-SEND]**

**Null hypothesis: NATIVE — sufficient for the machinery, insufficient for the
seams.** `LiveExecutionClient` supplies everything but eight
`NotImplementedError` coroutines (`NT/live/execution_client.py:598-633` `[V]`)
and the four report coroutines. **GENUINELY ABSENT:** `AccountState` emission
(§2.3 item 2) and `_query_account` (N-6).

**Goal.** One `PolymarketUSExecutionClient(LiveExecutionClient)`.

- `_connect`: credentials → `GET /v1/account/balances` → `generate_account_state`
  → `_await_account_registered` (`NT/live/execution_client.py:534-567` `[V]`).
  **Fails closed** if the balance read fails: no account, no connect.
- Four report coroutines from E-2's mappers. **`_query_account` defined
  explicitly** (N-6) — omitting it raises `AttributeError` inside a created task,
  swallowed into `_log.exception` (`:226` `[E]`): a silent failure, not a
  `NotImplementedError`.
- **All eight lifecycle coroutines implemented as refusals** via
  `generate_order_denied` (`NT/execution/client.pyx:370` `[V]`) — terminal,
  pre-venue, no `OrderSubmitted` (`AUDIT:164-169` `[E]`). Only
  `_connect`/`_disconnect` are real.
- **Startup reconciliation asserted to have SUCCEEDED**, not swallowed
  (REQ-EXEC-04, `TRADING_ENABLEMENT_PLAN.md:143` `[V]`). Mismatch **halts; it
  never self-heals** (`TRADING_SYSTEM_ARCHITECTURE.md:1212` `[V]`).
- Config: every field required-no-default. `LiveExecEngineConfig` pinned by test:
  `generate_missing_orders=False` (E-5's prerequisite; native default is `True`,
  `NT/live/config.py:183` `[V]`); `inflight_check_interval_ms=2000` (`:184` `[V]`);
  `open_check_interval_secs` / `position_check_interval_secs` left `None` **for
  now** — H-5: enabling the position check before E-5 makes the wrong-price fill
  fire **repeatedly** rather than once (`AUDIT:113-120` `[E]`). Re-decided in E-5.
- OMS pinned to **NETTING** by test — `_reconcile_position_report_hedging`
  (`NT/live/execution_engine.py:2349`) was never read (`AUDIT:180-181` `[E]`).

**RED first.** (a) A node with the exec client registered starts and
`cache.account_for_venue(...)` is **not `None`** before any strategy runs.
(b) Each of the eight coroutines emits `OrderDenied` with a named reason and
**never** `OrderSubmitted`. (c) `_query_account` exists and is awaited without
`AttributeError`. (d) A balance-read failure makes `_connect` raise.

**Barriers.** Layer 1 — **B6b narrowed** per §4 (exactly one subclass at exactly
this path, `== 1`, import nowhere else). Layer 4 — the trading `TradingNodeConfig`
site's `exec_clients` moves `{}` → exactly one key
(`node_config.py:204` `[V]`); the recorder site (`:460` `[V]`) stays `{}`;
`len(_node_config_calls()) == 2` retained (`test_runtime_node_config.py:338` `[V]`).
Layer 3 — N2 exact-set grows. **No write verb, literal or signing change.**

**Completion.** **G1 met.** All four REDs GREEN.

---

### E-4 — The denial layer: H-1, N-2, N-3 and the refusal matrix · **[NO-SEND]**

**Null hypothesis: NATIVE — insufficient, and dangerously so.** Four fail-opens
on one code path: `NT/risk/engine.pyx:682-689` `[V]` — no cached account logs at
**debug** and `return True` (**pass**); `:691-692` `[V]` — `is_margin_account`
passes unconditionally; `:670-672` + N-2 `[V]` — an unpopulated
`max_notional_per_order` leaves the `:912-917` cap inert; `:848-851` + N-3 `[V]`
— an order with no price and no trigger price is `continue`d, i.e. skipped.
Breezy must deny **before** Nautilus is consulted; a green run is not evidence
the native check engaged (`AUDIT:48-52` `[E]`).

**Goal.** `exec/denial.py` — every refusal named, counted, raised pre-Nautilus:

| Refusal | Trigger | Evidence |
|---|---|---|
| `NoCachedAccountError` | `cache.account_for_venue(...) is None` | H-1 `[E]`; `engine.pyx:682-689` `[V]` |
| `MarginAccountUnsupportedError` | `account.is_margin_account` | `:691-692` `[V]` |
| `UnpopulatedNotionalCapError` | instrument absent from the risk engine's cap map | N-2 `[V]` |
| `MarketOrderRefusedError` | `order.order_type is MARKET` | N-3 `[V]` |
| `UnsupportedOrderTypeError` | any of the 7 types the venue does not expose | `sdk_snapshot/.../types/orders.py:7` `[E]` |
| `PostOnlyRefusedError` | `order.is_post_only` → `participateDontInitiate` | N-5 `[V]`; B-3 `[E]`; `fees.py:199-208` `[V]` |
| `ShortSideRefusedError` | non-reducing SELL under `allow_short=False` | H-6 `[E]` |
| `AmbiguousSubmitLatchedError` | the market's latch is set | E-9 |

Plus the **native configuration** N-2 requires: call
`RiskEngine.set_max_notional_per_order(instrument_id, cost_cap)`
(`NT/risk/engine.pyx:279` `[V]`) for **every** instrument as it loads, carrying
§3.2's L-2 line in the code and applying `cost_cap = payout_cap × price` wherever
a Breezy cap is payout-denominated.

**RED first.** Each row: construct the condition, submit, assert the named Breezy
exception, assert `generate_order_denied` fired **and** the risk engine was never
reached. Two extra: (i) with **no** account cached and Breezy's denial removed, an
order at 1000× the intended notional **passes** the native check — the H-1
proof-by-construction, written so nobody later reads a green run as evidence;
(ii) §3.3's barrier — a static test that no strategy or sizing module calls
`portfolio.equity(` / `net_exposure(` / `net_exposures(`.

**Barriers.** None narrowed; Layer 1 gains scans.
**Completion.** **G4 met.** `describe_binding_order` re-run against actual
defaults (`DATA_CAPTURE_AND_RISK_PLAN.md:302` `[V]`).

---

### E-5 — Settlement is the exit · **[NO-SEND]**

**The problem (H-3 `[E]`).** On settlement the venue reports flat while the cache
holds the position open. `generate_missing_orders` defaults **True**
(`NT/live/config.py:183` `[V]`), so the engine synthesises a closing order
(`NT/live/execution_engine.py:2500-2566`) priced by
`_create_position_reconciliation_report` (`:2839-2924`): (1)
`calculate_reconciliation_price` — an accounting reconstruction, **not** a
settlement price; (2) the last cached quote — but a settled market publishes an
**empty book** (`data.py:624-641` `[V]`); (3) **`current_avg_px`** — close at
entry, **zero PnL**. Since the bid side cannot support a stop-out, settlement is
the **only** exit, so this corrupts the single event that realizes all PnL.

**Decision — option (b).** `generate_missing_orders=False`; Breezy emits the
closing fill explicitly via `generate_order_filled`
(`NT/execution/client.pyx:820` `[V]`) at the venue's own settlement price.

- **Rejected (a)** ("return the settled position with `avg_px_open` set to the
  settlement price"): writes a false *entry* price, corrupting average-price
  arithmetic and all downstream PnL attribution — self-consistent and wrong.
- **Rejected (c)** ("leave `position_check_interval_secs=None`"): startup
  reconciliation still runs the position path
  (`NT/live/execution_engine.py:1749-1770` `[E]`), so (c) alone is insufficient.
- **Cost of (b), stated:** a genuinely unknown venue position is no longer
  synthesised. Acceptable and preferred — Breezy is the sole trader on an
  operator-controlled key, and an unrecognised position must **halt**, not
  self-heal (`TRADING_SYSTEM_ARCHITECTURE.md:1212` `[V]`). A test asserts the halt.

**Price source.** `stats.settlementPx` → `InstrumentClose`, already parsed on the
data path (`parsing.py:1020-1034` `[V]`, `close_type=CONTRACT_EXPIRED`). The
execution side subscribes to the same fact rather than re-deriving it. `[I]` —
nothing in the execution engine subscribes to `InstrumentClose`
(`AUDIT:90-93` `[E]`), so the wiring is Breezy's.

**RED first, before the module exists.** A `Price` of exactly `0.00` and exactly
`1.00` must survive `make_price`, `Price` validation and fill validation. This is
`[U]` (`AUDIT:176-179` `[E]`); the only suggestive evidence is
`instrument.make_price(0.0)` at `NT/live/reconciliation.py:493`. **If this RED
cannot be made GREEN, E-5 stops and OQ-4 escalates** — the fallback settles at the
nearest representable tick and **reports the residual as a named error**, never a
silent clamp. **Second RED:** a settled position closed through the native path
books `realized_pnl == 0`; it must fail after the fix.

**Barriers.** None narrowed. H-5 re-decided here: with the settlement price
correct, `position_check_interval_secs` may be enabled — value and reason
recorded, or it stays `None` and that is recorded. Enabling it before this
increment is forbidden.

**Completion.** **G3 met** — realized PnL equals
`qty × (settlementPx − avg_px_open) − fees` in a test that executes the path.

---

### E-6 — The write chain, allowlisted to ONE non-exposure endpoint · **[SEND — narrowly]**

> **First commit at which live order capability is reachable.** What is reachable
> is `POST /v1/orders/open/cancel` and nothing else: it can cancel working
> orders; it **cannot open exposure**. Say so in the commit message.

**Null hypothesis: GENUINELY ABSENT** (§2.3 item 6). Searched `NT/adapters/` for
a reusable venue-agnostic signed-write transport: every adapter writes its own
(`NT/adapters/binance/execution.py`, `NT/adapters/dydx/execution.py` `[V]`
existence). Nautilus supplies `nautilus_pyo3.HttpClient` and `RetryManagerPool`;
both are wired, neither reimplemented.

**Goal.** `exec/signing.py`, `exec/transport.py`, `exec/egress.py` per §4.

- **Signing is identical for writes** (B-0 `[E]`): same three headers, same
  canonical string `timestamp_ms + METHOD + path`, same Ed25519
  (`api-reference_authentication_2026-08-25.md:82,92-96` `[E]`; SDK
  `auth.py:26-27` `[E]`). **No nonce, no EIP-712, no on-chain transaction, no
  wallet, no allowance, no ERC-20/1155 approval** — those are Polymarket **.com**,
  a different venue. The work is a widened frozenset in a *separate* module;
  B1/B2/B3 stay byte-identical.
- The body seam is already present and inert (`signing.py:108-123` `[V]`).
  `exec/signing.py` implements **both** branches behind one variant and defaults
  to the documented no-body form; E-7 decides. `[U]` OQ-1.
- **Path-segment validation before signing:** every interpolated segment matches
  `^[A-Za-z0-9_-]+$`. The canonical string has no field delimiter
  (`signing.py:37-41` `[V]`), so same-method path ambiguity is the residual once
  variable paths exist.
- `exec/transport.py`: own pyo3 client, own closure, own quota bucket, and an
  **equality-pinned frozenset of exactly one `(method, path)` pair**. Dispatch
  takes `LiveOrderSubmissionAuthorization` **positionally** and calls `consume(...)`
  before any I/O.
- `exec/egress.py`: request construction, chokepoint call, capability threading,
  response parsing. **Under 200 lines.** No decision logic — every refusal already
  happened in E-4 (arch §8.8).
- **Retry: wire `RetryManagerPool` (`NT/live/retry.py:242` `[V]`)** — never write a
  backoff loop. Enabled for **read/status/cancel only**; the submit path has no
  retry and never will (B-1).
- **Reserved data-path share** (B-4 `[E]`): sized so `egress_rps + data_rps < 20`
  with headroom; exhausting the egress share latches `HALT_NEW_EXPOSURE` rather
  than consuming the tape's share. The data path claims 15 rps
  (`transport.py:122` `[V]`) against a 20 rps key-wide cap (`transport.py:119`
  `[V]`; `api-reference_rate-limits_2026-08-25.md:15` `[V]`) — **5 rps remain and
  the split must be re-derived, not assumed.** OQ-9.

**RED first.** (i) A dispatch without the capability is a `TypeError` at the call
site. (ii) A capability minted for one `(method, path, body, notional)` refuses a
different one. (iii) A second dispatch with the same capability raises "already
been used" (`safety.py:468-471` `[V]`). (iv) A `(method, path)` off the frozen
allowlist is refused **before** signing, so no signature is ever produced for it.
(v) A dispatch that skips `consume(...)` fails a static test (A-4 #6).

**Barriers.** Layer 1 — **B4/V1 narrowed** (exact path `exec/signing.py`),
**B4/V3 narrowed** (exact path `exec/transport.py`), **B6a narrowed to `== 1`**
at `exec/egress.py`, each with its §4 pair in this commit; `.request` stays banned
in all three. Layer 2 — `http.py` / `signing.py` / `transport.py` diffs are
**empty**, asserted by an equality test on those three files' `PERMITTED_*`
constants.

**Completion.** All five REDs GREEN; `scan_write_egress()` reports violations at
**exactly** the three allowlisted paths and nowhere else; the suite still runs
only under the firewall launcher.

---

### E-7 — Signature-scheme probe: cancel-all while provably flat · **[SEND — operator-run]**

**Deviation from the brief, stated openly.** The brief names preview's
non-mutation as the highest-leverage unknown and asks for it as an early
increment. I agree on leverage and am **not** making it the first live write: a
POST is a POST, and preview's non-mutating status is **the very thing under
test**, so it cannot also be the assumption that makes the test safe.
`POST /v1/orders/open/cancel` with **zero open orders** is a provable no-op in
the exposure dimension — worst case it cancels orders we have verified we do not
have. It answers OQ-1 at strictly lower risk, and it is only possible *because*
E-2/E-3 give us a read-only way to prove we are flat. Preview follows immediately
in E-8.

**Goal.** Resolve OQ-1. No-body canonical string correct → 200. Body participates
→ **401 on 100% of submissions** (B-2 #1 `[E]`), surfaced for one no-op request.

**Preconditions, all hard.** D1 satisfied (`PREREQ:211` `[E]`); operator present;
`GET /v1/orders/open` empty immediately before the probe; firewall lifted
**deliberately** for this run only, out of CI; permit issued at the minimum
ceiling; `manualOrderIndicator` explicit. Run under `scripts/venue/`
(venue-touching by path, C2, `readonly_guard.py:128-131` `[V]`): documented
no-body variant first, then on 401 one retry with the body-hash variant —
**two requests maximum** — with status, headers and the redacted canonical-string
shape digest-signed into `docs/evidence/venue/polymarket_us/`.

**Branch.** No-body works → keep the default, close OQ-1. Body required →
`exec/signing.py`'s variant flips and every downstream request construction is
re-verified. Both 401 → **stop**; OQ-1 escalates and E-8..E-12 do not proceed.

---

### E-8 — Preview probe: direction encoding, mutation, precision · **[SEND — operator-gated]**

**Goal.** Extend the allowlist by **exactly one entry** —
`POST /v1/order/preview` — and resolve, with zero intended capital at risk:

- **OQ-2** — is preview non-mutating? `[U]`. Measured by an immediately following
  `GET /v1/orders/open` + `GET /v1/portfolio/positions`, both unchanged.
  **`POLYMARKET_US_BUILD_PLAN.md:20` permits preview only on venue/operator
  confirmation, which does not exist on disk** (`PREREQ:162-165` `[E]`) — so this
  is **operator-gated**, not merely operator-run.
- **OQ-3 — direction encoding.** Precedence **is** documented and the repo's
  claim that it is not is stale: *"If both are sent, `outcomeSide`+`action`
  wins"* (`api-reference_orders_overview_2026-08-25.md:114` `[V]`); *"To trade the
  NO side at any price X, set `price.value = 1.00 - X`"* (`:158` `[V]`). What is
  unverified is whether the venue **enforces** what it documents; the failure mode
  is a wrong-side fill costing up to **49× the intended leg at a 0.02 limit**
  (`PREREQ:173` `[E]`). Preview's expected-fill response is the read-only oracle.
- **OQ-5 — fractional quantities.** The venue contradicts itself: `overview:185`
  `[V]` says extra precision is silently normalized down, with
  `minimumTradeQty=0.01` on 729/729 weather markets, while
  `learn_trading_basics_fractional-shares:9,30` `[E]` says whole contracts only.
  Preview's echoed quantity settles it.
- **Tick alignment** — `orderPriceMinTickSize` per market, never a global
  constant (REQ-VENUE-06).

**Design rule enforced here `[I]`.** Breezy sends **both** `outcomeSide`+`action`
**and** `intent`, mutually consistent, with a contract test asserting they agree
— so a venue honouring either field produces the same side. Belt-and-braces, and
cheap.

**Branch.** Preview mutates → the allowlist entry is **reverted**, OQ-2 closes
NEGATIVE, and OQ-3/OQ-5 fall through to E-12's single-order probe at minimum
size. That fallback is more expensive and is not silently adopted.

---

### E-9 — `SUBMIT_AMBIGUOUS` and the one-in-flight invariant · **[NO-SEND — no new endpoint]**

**The problem (B-1 `[HARD BLOCK]` `[E]`).**
`grep -niE "clordid|clientorderid|client_order_id|idempot"` over the retail
create-order snapshot returns **nothing**; `CreateOrderResponse` carries only
`id` and `executions` (N-4 `[V]`). The institutional `insert-order` schema *does*
carry `clordId` (`api-reference_trading_insert-order_2026-08-25.md:63` `[E]`) but
the operator decision is **retail** (`POLYMARKET_US_BUILD_PLAN.md:18` `[E]`), so
it does not transfer. Compose with the 5-second stopgap — rejects carrying
`Global Rate Limit Exceeded` plus *"You do not need to throttle your traffic in
response to them"* (`api-reference_rate-limits_2026-08-25.md:48-56` `[V]`) — and
**a naive retry is a double position with no venue-side dedup.**

**Design — never a resubmit.**

1. **One in flight per `marketSlug`, enforced locally.** This is the *mechanism*
   replacing the missing idempotency key: with at most one outstanding submit per
   market, an unmatched venue order in that market is unambiguously ours. `[I]` —
   the load-bearing choice of this increment; attack it here.
2. On timeout or unclassifiable response, latch `SUBMIT_AMBIGUOUS` for that market
   and permit **only** read / status / cancel / reconciliation work (REQ-EXEC-07,
   `TRADING_ENABLEMENT_PLAN.md:146` `[V]`).
3. Resolve by polling `GET /v1/order/{orderId}` when an `id` was returned, else
   `GET /v1/orders/open` + `GET /v1/portfolio/activities` filtered on
   `(marketSlug, side, price, quantity, time-window)`.
4. **If the poll cannot uniquely resolve, the latch stays set and escalates to the
   operator.** It never times out into "probably fine". There is no protocol-level
   guarantee here — only the one-in-flight invariant plus a bounded window.
5. **Fail-closed halt reads** (arch §8.6): any exception, timeout or absent row
   reading a latch is `HALT_ALL_DISPATCH`.
6. **Thread ownership** (arch §8.6; REQ-RISK-02/REQ-EXEC-09): the halt store used
   by egress is constructed **on the event-loop thread egress dispatches from**,
   with a startup assertion pinning the owning thread identity —
   `SqliteStateStore` confinement is to the CONSTRUCTING thread
   (`sqlite_store.py:101-104` `[E]`).

**RED first.** (i) A timed-out submit latches and a second submit for the same
market is refused by name. (ii) A static test that **no** code path resubmits a
create-order. (iii) An unreadable latch store resolves to halt. (iv) A latch call
from a foreign thread fails.

---

### E-10 — `POST /v1/orders` and `_submit_order` · **[SEND — EXPOSURE-OPENING]**

> **First commit at which Breezy can open a position.** Gated on D2 funding, D3,
> D4, D5, `BREEZY_TRADING_OPERATOR_ID` and a real-money approval artifact —
> **none of which exist today** (`PREREQ:209-218` `[E]`).

**Goal.** Allowlist grows by **exactly one**. `_submit_order` translates
`SubmitOrder` → `CreateOrderRequest` → egress → `generate_order_submitted` →
venue events. `_submit_order_list` continues to refuse.

| Field | Value | Cite |
|---|---|---|
| `marketSlug` | from `InstrumentId` via `symbology.py` | the only required field, `create-order:60-63` `[V]` |
| `type` | `ORDER_TYPE_LIMIT` **always** | N-3 forbids MARKET |
| `price.value` | **always the YES/long side**; NO at X is sent as `1.00 − X` | `overview:158` `[V]` |
| `quantity` | pre-aligned to `minimumTradeQty` | `overview:185` `[V]`; OQ-5 |
| `tif` | mapped from Nautilus `TimeInForce`; IOC is native | `NT/model/enums.py:446-453` `[E]` |
| `participateDontInitiate` | **never true** | N-5 `[V]`; B-3 `[E]` |
| `intent` **and** `outcomeSide`+`action` | both, mutually consistent | `overview:114` `[V]` |
| `manualOrderIndicator` | `MANUAL_ORDER_INDICATOR_AUTOMATIC`, required, explicit | `overview:230-237` `[V]`; chokepoint refuses `None` (`safety.py:674-675` `[V]`) |
| `synchronousExecution` | **false** | N-4 `[V]`; OQ-6 |

**Precision.** Every `Price`/`Quantity` pre-validated **before** construction:
Rust panics SIGABRT rather than raising (REQ-EXEC-06,
`TRADING_ENABLEMENT_PLAN.md:145` `[V]`).

**RED first.** (i) A NO-side order at 0.30 produces `price.value = 0.70` — the
49× hazard, asserted directly. (ii) An off-tick price is refused before
construction. (iii) A submit while the latch is set is refused. (iv) A submit with
no cached account is refused by Breezy (E-4 regression). (v) The full path from
`Strategy.submit_order` to `generate_order_submitted` runs against a recording
transport with **zero** real network calls.

**Completion.** **G2 met in the machinery**; not yet demonstrated live (E-12).

---

### E-11 — Cancel · **[SEND]**

Allowlist grows by **exactly one**: `POST /v1/order/{id}/cancel`
(`resources/orders.py:47` `[V]`). `_cancel_order` and `_cancel_all_orders`
implemented; `_modify_order` and `_batch_cancel_orders` continue to **refuse** —
modify semantics rest on a demonstrably drifted SDK snapshot alone (B-2 #7 `[E]`:
six order-endpoint doc pages and the entire private-WebSocket page were never
captured). Cancel is retried through `RetryManagerPool` — idempotent in effect,
unlike submit. REQ-RISK-08's kill switch gains teeth: read / status / cancel
always permitted; submit / replace / increase require the kill switch clear
**and** D4 set.

---

### E-12 — Single-order live probe and enablement · **[SEND — real money]**

One order, minimum tradable size, at a price that will not fill immediately, then
cancel. Captures: the fill payload shape (**never observed** — B-2 #6 `[E]`, so
E-2's fill mapper is still refusing-by-default until this lands), commission
parsing, `price_scale` / `fractional_quantity_scale` decoding, and the naked-short
question (OQ-10, unknowable read-only, operator-gated). Evidence digest-signed
into `docs/evidence/venue/polymarket_us/`. Tier-1 enablement follows as a separate
operator decision outside this plan.

---

## 7. The unknown-resolution track

Unknowns are never silently assumed away. Each row states how it closes and what
happens if it does not.

| ID | Unknown | Class | Resolved by | If it does not resolve |
|---|---|---|---|---|
| **OQ-1** | Does the POST body participate in the Ed25519 canonical string? (B-2 #1 `[E]`) | **live probe, no-op** | E-7 | E-8..E-12 do not proceed. 100% of submissions would 401. |
| **OQ-2** | Is `POST /v1/order/preview` non-mutating? (B-2 #2 `[E]`) | **operator-gated live probe** | E-8 | Allowlist entry reverted; OQ-3/OQ-5 fall through to E-12 at higher cost. |
| **OQ-3** | Does the venue **enforce** the documented `outcomeSide`+`action` precedence and `price.value = 1.00 − X`? | **read-mostly**: preview echo | E-8 | E-10 proceeds only at minimum size with an immediate position read-back. |
| **OQ-4** | Do `Price(0.00)` / `Price(1.00)` survive fill validation? (`AUDIT:176-179` `[E]`) | **local, RED test** | E-5 | Settle at the nearest representable tick and **report the residual as a named error**; never silently clamp. |
| **OQ-5** | Fractional quantities: venue docs contradict themselves (B-2 #5 `[E]`) | **read-mostly**: preview echo | E-8 | Assume whole contracts (the conservative branch) and record the assumption. |
| **OQ-6** | Should `synchronousExecution` be used to collapse submit ambiguity? (N-4 `[V]`) | **deferred, then live** | after E-12 | Default `false`. It interacts with the 5s stopgap and *lengthens* the window in which the outcome is unknown, so it is not adopted on a hypothesis. |
| **OQ-7** | Exact field names / units on `GetAccountBalancesResponse` | **read-only** | E-3, from a captured authenticated GET | `_connect` fails closed; the client does not start. |
| **OQ-8** | Is `GET /v1/portfolio/activities` the fill source, and what is its schema? | **read-only** | E-2/E-3 | The fill mapper refuses by name until E-12 observes a real fill. |
| **OQ-9** | The egress/data split of the 20 req/s key-wide budget (B-4 `[E]`) | **measurement** | measured during E-7/E-8; the data path currently claims 15 rps (`transport.py:122` `[V]`) | The egress bucket is set to the smallest workable value and the data share is reserved; starving the tape mid-position is a named failure mode, not an accepted cost. |
| **OQ-10** | Naked-short acceptance (B-2 #4 `[E]`) | **unknowable read-only, operator-gated** | E-12 at the earliest | `allow_short=False` stands. Nothing depends on it. |
| **OQ-11** | Modify / batch-cancel / private-WebSocket semantics (B-2 #7 `[E]`) | **DEFERRED — out of scope** | not in this plan | `_modify_order` and `_batch_cancel_orders` refuse permanently until documented. |
| **OQ-12** | Bodies of `calculate_reconciliation_price` / `create_inferred_reconciliation_trade_id` (Rust, unreadable) | **DEFERRED** | not in this plan | E-5's option (b) makes them irrelevant to the settlement price — that is part of why (b) was chosen. |
| **OQ-13** | `_reconcile_position_report_hedging` behaviour (`AUDIT:180-181` `[E]`) | **DEFERRED** | not in this plan | OMS is pinned to NETTING by test in E-3, so the unread path is unreachable. |

**Operator-gated, not agent-decidable:** D2 funding, D3
`BREEZY_MAX_ORDER_NOTIONAL_USD`, D4 `BREEZY_TRADING_ENABLED`, D5 session
notional + order count, `BREEZY_TRADING_OPERATOR_ID`, the real-money approval
artifact, OQ-2's preview permission, and OQ-10. All are **NO** today except D1
(`PREREQ:209-218` `[E]`). No increment sets them; shipped code cannot
(`test_polymarket_us_permit_issuance.py:1324-1387` `[V]`).

---

## 8. Risk register

Ranked by cost-of-being-wrong × probability.

| # | Risk | Sev | Mitigation | The test that proves it |
|---|---|---|---|---|
| **R-1** | An exec file lands before the E0 rule; `uv run pytest -q` transmits a signed live order with every gate green (A-1 `[E]`) | **CRITICAL** | E-0 is increment #1, in the same commit that creates `exec/` | `test_n2_...` with an exact-set pin; the planted-`exec/transport.py` detector RED |
| **R-2** | No `AccountState` → every native notional/balance check silently bypassed; a green run proves nothing (H-1 `[E]`) | **CRITICAL** | Breezy denies before Nautilus is consulted (E-4); `_connect` fails closed without balances (E-3) | E-4 RED (i): with Breezy's denial removed and no account cached, a 1000× notional order **passes** the native check |
| **R-3** | A retry after an ambiguous submit creates a double position; no venue dedup (B-1 `[E]`) | **CRITICAL** | `SUBMIT_AMBIGUOUS` latch, one-in-flight-per-market, **no resubmit ever** (E-9) | E-9 RED (ii): a static test that no code path resubmits a create-order |
| **R-4** | Settlement books at entry price → zero PnL on the only exit (H-3 `[E]`) | **CRITICAL** | `generate_missing_orders=False` + explicit fill at `stats.settlementPx` (E-5) | E-5 RED: a settled position through the native path books `realized_pnl == 0`; must fail after the fix |
| **R-5** | Wrong-side fill from a direction-encoding error — up to 49× the intended leg at a 0.02 limit (B-2 #3 `[E]`) | **CRITICAL** | `price.value = 1.00 − X` for NO; both encodings sent consistently; preview oracle (E-8) | E-10 RED (i): a NO order at 0.30 produces `price.value = 0.70` |
| **R-6** | `max_notional_per_order` is inert because the per-instrument dict is empty (N-2 `[V]`) | **HIGH** | runtime `set_max_notional_per_order` per discovered instrument (E-4) | E-4: `UnpopulatedNotionalCapError` refuses any instrument with no entry |
| **R-7** | A MARKET order's notional is never checked (N-3 `[V]`) | **HIGH** | MARKET refused client-side (E-4); `ORDER_TYPE_LIMIT` always (E-10) | E-4 `MarketOrderRefusedError` contract test |
| **R-8** | A barrier is weakened rather than narrowed — the one-token diff at `readonly_guard.py:112-114` disarms 19 modules (A-3 `[E]`) | **HIGH** | every rule constant equality-pinned (E-1); every narrowing paired in-commit | `test_cage_rule_constants_are_pinned.py` |
| **R-9** | Egress starves the quote tape: one 20 rps bucket shared with the data path (B-4 `[E]`) | **HIGH** | reserved data share; exhausting the egress share latches `HALT_NEW_EXPOSURE` (E-6) | a test that egress cannot consume the reserved data quota key |
| **R-10** | Post-only order priced with the wrong **sign** — venue pays $0.3125, model charges $1.50 (B-3 `[E]`) | **HIGH** | refusal moves to the execution boundary (E-4), not only the fee model | `PostOnlyRefusedError` contract test; `participateDontInitiate` never true |
| **R-11** | Preview turns out to be mutating (OQ-2) | **HIGH** | operator-gated; immediate read-back of open orders and positions (E-8) | the read-back assertion is the test |
| **R-12** | An exec test marked `allow_socket`/`live`/`venue_live`/`real_money` restores real pyo3 clients (A-4 #7 `[E]`) | **MEDIUM** | static ban on those markers in any test importing `exec` (E-1) | planted-marker detector RED |
| **R-13** | `_query_account` undefined → `AttributeError` swallowed into `_log.exception` (H-4 / N-6 `[V]`) | **MEDIUM** | defined explicitly (E-3) | E-3 RED (c) |
| **R-14** | Enabling `position_check_interval_secs` before E-5 makes the wrong-price fill fire repeatedly (H-5 `[E]`) | **MEDIUM** | left `None` until E-5; re-decided there with a recorded reason | a config pin test in E-3 |
| **R-15** | Capability accepted but never consumed — expiry/replay inert while budget still decrements at mint (A-4 #6 `[E]`) | **MEDIUM** | `consume()` required on every dispatch path (E-6) | the skip-consume static test |
| **R-16** | `native equity()` silently substituted for `_equity()` once E-3 makes it non-zero (L-2, §3.3) | **MEDIUM** | named as a behaviour change; static ban on `portfolio.equity(` in strategy/sizing (E-4) | the static scan |
| **R-17** | The fill mapper guesses an unobserved payload shape (B-2 #6 `[E]`) | **MEDIUM** | refuse-by-name until E-12 observes a real fill (E-2) | the refusal is the test |
| **R-18** | `consume()` accepts a lying `Decimal` subclass at any magnitude (A-2 `[E]`) | **MEDIUM** | type-exactness mirroring `safety.py:676` (E-1) | E-1 RED (1) |

---

## 9. Non-goals

Named so their absence is a decision, not an omission.

1. **Short-side support.** `allow_short=False` is the default and stays. The bid
   side cannot support a stop-out — median top-of-book bid is 0.3 contracts
   (`MEMORY: weather market bid side is empty`) — and `CashAccount.balance_impact`
   **credits** a SELL (`NT/accounting/accounts/cash.pyx:482-495`, H-6 `[E]`), so
   the native cash check is wrong **directionally** for a short binary. Not a
   formality: a real control.
2. **Maker / post-only strategies.** Refused outright. The maker coefficient is
   **−0.0125, a rebate**, while Breezy charges the taker coefficient on both
   sides — at C=100, p=0.50 the venue **pays** $0.3125 and the model **charges**
   $1.50: wrong by $1.8125 and wrong in **sign** (B-3 `[E]`). A posting strategy
   is negative by construction and unevaluable.
3. **`SandboxExecutionClient` / Nautilus paper mode.** Banned: it constructs
   `SimulatedExchange` directly with a hardcoded `MakerTakerFeeModel`
   (`NT/adapters/sandbox/execution.py:109-124` `[E]`) → 50× fee overstatement at
   p=0.98 with unbounded relative error `1/(1-p)`, plus `LatencyModel(0)`.
   Simultaneously too pessimistic on cost and too optimistic on fill (arch §9.1).
4. **Order modify.** `_modify_order` refuses permanently — modify semantics rest
   on a demonstrably drifted SDK snapshot alone (B-2 #7 `[E]`). Cancel-and-resubmit
   is not offered either: it reopens B-1.
5. **Batch / order-list submission.** `_submit_order_list` and
   `_batch_cancel_orders` refuse; batched semantics unverified.
6. **The institutional DMA surface** (`insert-order`, `clordId`). The operator
   decision is retail (`POLYMARKET_US_BUILD_PLAN.md:18` `[E]`). Its idempotency key
   is exactly what would solve B-1 and it is out of reach — **saying so is part of
   this plan, because a reviewer will ask.**
7. **Kalshi portability.** The exec client is venue-specific by construction; the
   *seams* (report mappers, denial layer, settlement exit) are portable. Nothing is
   generalised speculatively (YAGNI; CLAUDE.md Engineering Priority 5).
8. **Deterministic client order IDs.** Deleted as a design, not deferred: the
   retail schema has no field to carry one (B-1 `[E]`), so `ClientOrderId` stays
   Nautilus-local and the venue cannot reject the duplicate.
9. **A Breezy-authored retry/backoff.** `RetryManagerPool` is wired
   (`NT/live/retry.py:242` `[V]`); writing one is a rejection-on-sight.
10. **Re-planning `DATA_CAPTURE_AND_RISK_PLAN.md`.** Its P0-P7 sequence is
    unchanged. The only hard dependencies are **P5-fix** (`allow_short=False`
    correct before E-4) and **§2.3** (the unit).

---

## 10. Documents this plan requires to be corrected

Correction is part of the increment named, not a follow-up.

| Stale claim | Where | Refuted by | Corrected in |
|---|---|---|---|
| "Retries reuse the deterministic client order ID of §7.3" | `TRADING_SYSTEM_ARCHITECTURE.md:1375` `[V]`, and §7.3's "so a retry is a duplicate the venue rejects" `[V]` at `:1196` | B-1 `[E]`; N-4 `[V]` | **E-9** |
| "no documented precedence for `intent` vs `outcomeSide`+`action`" | `.claude/skills/polymarket-us-integration/SKILL.md:153,248,306`; `TRADING_ENABLEMENT_PLAN.md:90` `[E]` | `overview:114` `[V]` | **E-8** |
| `manualOrderIndicator` is "bool \| Rare" | `SKILL.md:151` `[E]` | required string enum, `overview:230-237` `[V]` | **E-10** |
| REQ-VENUE-04 G2 "order endpoints undocumented" | `TRADING_ENABLEMENT_PLAN.md:89` `[V]` | 11 endpoints + 2 OpenAPI schemas on disk `[E]` | **E-2** |
| REQ-VENUE-06 G4 "tick/minQty never observed" | `TRADING_ENABLEMENT_PLAN.md:91` `[V]` | 729/729 raw market objects `[E]` | **E-2** |
| drifted line refs for chokepoint / B6b / B3 closure | `TRADING_SYSTEM_ARCHITECTURE.md` §8.3-8.4 `[V]` | `safety.py:32`→`:626`; `readonly_guard.py:533`→`:550`; `transport.py:105-124`→`:129-148,325` `[E]` | **E-1** |
| §8.0 "reduces to effectively one enforced chain" | `TRADING_SYSTEM_ARCHITECTURE.md:1241-1251` `[V]` | still true of the *chain*, but §4/§5 add per-file structural pairs it did not contemplate | **E-6** |
| "fee_schedule_status is UNKNOWN" | `docs/evidence/roi_feasibility_2026-08-26.md:72-80` `[E]` | `parsing.py:477-489,1183-1195`. **Append-only regime — re-date, do NOT edit.** | **E-3** |

`GO_LIVE_PLAN.md` Phase F is **retired** by this document: on merge, its
`:227-236` gains a pointer here, and its retained value collapses to operator
gates D1-D5 alone.

---

## 11. Sequencing constraints against the active plan

- **E-4 requires `DATA_CAPTURE_AND_RISK_PLAN.md` P5-fix** (`allow_short=False`
  correctness). E-0..E-3 do not.
- **E-0..E-5 are independent of P0-P7** and can run in parallel with them.
- **E-6..E-12 require the operator gates** and are therefore not schedulable by
  an agent at all — they are enablement events.
- **E-0 changes every developer's test command** repo-wide from the moment it
  lands. That is a coordination cost paid once, deliberately, at the front.

---

## 12. How to review this plan

Two questions, per LESSONS L-3 (`:152-155`):

1. **Is what is written here correct?** Attack §0.2 first — N-1..N-6 are new and
   unreviewed. Then attack §3's unit lines and §6's RED tests.
2. **What is NOT here, and would its absence stop the goal?** The known thin
   spots, named so the hunt starts somewhere real:
   - **E-9's one-in-flight invariant is the load-bearing substitute for a
     protocol guarantee we do not have.** If it is wrong, R-3 is unmitigated.
   - **The fill mapper is a refusal, not an implementation, until E-12.** A
     `FillReport` that never arrives means positions reconcile from the position
     endpoint alone; whether that is sufficient is `[I]`, not verified.
   - **Nothing here covers the private WebSocket.** All order/fill state is
     polled. Whether polling at the reserved rate is fast enough to keep
     `inflight_check_threshold_ms=5000` (`NT/live/config.py:185` `[V]`) honest
     is unmeasured — and it interacts with OQ-9.
   - **`_disconnect` semantics with working orders are unspecified here.**
     Whether shutdown should cancel-all is a policy question this plan does not
     answer.
