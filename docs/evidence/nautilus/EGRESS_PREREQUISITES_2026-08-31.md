# Order-egress prerequisites — cage rework + venue knowledge audit, 2026-08-31

Companion to `EXECUTION_CLIENT_NATIVE_AUDIT_2026-08-31.md` (the Nautilus side).
Three findings below were **re-verified by the orchestrator directly against the
files**, not accepted on report; they are marked [VERIFIED BY ORCHESTRATOR].

---

## PART A — THE READ-ONLY CAGE

### A-0 Scope correction: the cage is FIVE layers, not one file

`tests/unit/test_polymarket_us_readonly_guard.py` holds **B3, B4, B5, B6a, B6b and
S16 only**. B1 and B2 are production code plus their own tests. Three further layers
exist that any single-file rework would never see:

- `tests/unit/test_execution_egress_firewall_guard.py` — barriers N1-N5
- `tests/unit/test_runtime_node_config.py:333-349` — the `exec_clients={}` /
  `strategies=[]` / `exec_algorithms=[]` empty-literal pin at **both** build sites
- `tests/unit/test_polymarket_us_permit_issuance.py` — permit-constructor allowlist
  (`:756-781`) and a blanket ban on shipped code writing the process environment
  (`:1324-1387`)

**A rework scoped to one file lands red — or worse, lands green while the layer that
mattered was never seen.**

### A-1 [CRITICAL, VERIFIED BY ORCHESTRATOR] The egress firewall is BLIND to the planned filenames

`tests/unit/test_execution_egress_firewall_guard.py:161-172`, verbatim:

```
_EGRESS_MODULE_BASENAMES = frozenset(
    {"execution.py", "execution_client.py", "exec_client.py",
     "order_submit.py", "order_router.py", "orders.py", "trading.py"}
)
_EGRESS_FUNCTION_NAMES = frozenset(
    {"submit_order", "place_order", "cancel_order", "modify_order", "submit_order_list"}
)
```

The planned module names — `egress.py`, `client.py`, `transport.py`, `signing.py`
(`TRADING_SYSTEM_ARCHITECTURE.md:1319-1324`) — match **none** of them. And the
Nautilus overrides a real client implements are **underscore-prefixed**
(`_submit_order`, `_cancel_order`, … at `nautilus_trader/live/execution_client.py:608-633`),
so **E3 never fires either**.

Today N2 fires only through E2, the `LiveExecutionClient` subclass.

**The consequence is the worst failure mode available to this project.** If a
write-capable `exec/transport.py` lands in any commit BEFORE `exec/client.py`, then
`find_execution_egress_modules()` returns empty, the OS-firewall attestation is never
demanded, and **an ordinary `uv run pytest -q` can transmit a signed live order with
every gate green.** There is no retail sandbox — every POST is real money
(`TRADING_ENABLEMENT_FINDINGS.md:251`).

**MANDATORY, in the same commit that creates the directory and before any other exec
file:** add an **E0 path rule** — *any* file under
`src/breezy/adapters/polymarket_us/exec/` is an execution-egress surface — plus the
underscore forms in `_EGRESS_FUNCTION_NAMES`. This is a pure extension; nothing is
loosened. **This is the single highest-priority item in the entire egress workstream
and it must land FIRST.**

### A-2 [MEDIUM, VERIFIED BY ORCHESTRATOR] `consume()` does not type-check its notional

`safety.py:463` is `if order_notional_usd != self.order_notional_usd:` — no type check.
The chokepoint at `:676` does `if type(order_notional_usd) is not Decimal`. Python tries
the LEFT operand's `__ne__` first, so a `Decimal` subclass overriding `__ne__` to return
`False` satisfies the re-check at any magnitude. `consume` is the one boundary where the
module's otherwise-consistent type-exactness discipline lapses. Fix mirrors `:676`.

### A-3 The rework principle: no barrier is deleted, each change is PAIRED

Every barrier that must change is a **narrowed re-expression** shipped with a strictly
stronger assertion in the same commit:

| Barrier | Today | Becomes | Paired with |
|---|---|---|---|
| B4 | no write verb in any venue-touching file | exact-path allowlist of 3 files | verb confined to ONE equality-pinned frozenset per file; `.request` still banned everywhere; the rule constants themselves become equality-pinned |
| B6a | **zero** chokepoint callers | **exactly one**, at a pinned path | capability must be taken positionally AND consumed before I/O |
| B6b | **no** execution client | **exactly one**, at a pinned path | gains the non-vacuity proof it never had |
| node_config | both sites empty-literal pinned | recorder stays empty; trading site pinned to exactly one key | `len(_node_config_calls()) == 2` kept |

**Allowlist must be exact paths, never a directory prefix** — a `startswith(".../exec/")`
allowance silently exempts every future file under `exec/` forever.

**Rule constants carry no equality pin today** (`_WRITE_METHODS`, `_WRITE_ATTRS`,
`_ORDER_PATH_RE`, `EGRESS_SCAN_ROOTS`, `SDK_IMPORT_ORACLE`). Pinning them is a pure
coverage increase and closes the "weaken the global rule instead of the local
exemption" move — a one-token diff at `readonly_guard.py:112-114` currently disarms
the barrier for all 19 venue modules.

### A-4 Ranked ways this rework gets silently wrong

1. **Directory-prefix allowlist** instead of exact paths → permanent blanket exemption.
2. **Escaping the classifier entirely** — put egress outside the adapter package, import
   nothing from it, build the base URL from env. Drops C1 and every V rule with **zero
   diff to any barrier**. Already documented as the classifier's residual gap
   (`readonly_guard.py:75-82`). Counter: assert `is_venue_touching(<each exec path>) is True`.
3. **Loosening the global rule** rather than allowlisting files (see A-3).
4. **A-1's N2 blindness.**
5. **B6a inverted to "at most one"** rather than "exactly one" → zero callers passes
   again and the chokepoint becomes dead code while egress dispatches.
6. **Capability accepted but never consumed** → single-use, expiry and replay protection
   all inert, while budget still decrements at mint so every counter reads correct.
7. **An exec test marked `allow_socket`/`live`/`venue_live`/`real_money`** — conftest
   restores the REAL pyo3 clients and lifts the socket block
   (`tests/conftest.py:336-342, 397-404`).
8. **Data-path widening by rebinding**: `signing.PERMITTED_METHODS = frozenset({"GET","POST"})`
   from the exec module. The frozenset is immutable; the module attribute is not, and no
   barrier bans the assignment.

---

## PART B — VENUE WRITE-PATH KNOWLEDGE

### B-0 The good news: signing is IDENTICAL for writes

There is **no separate signing scheme for orders**. Same three headers
(`X-PM-Access-Key`/`X-PM-Timestamp`/`X-PM-Signature`), same canonical string
`timestamp_ms + METHOD + path`, same Ed25519
(`docs_snapshots/api-reference_orders_create-order_2026-08-25.md:534-555`; SDK
`auth.py:26-27`). **No nonce, no EIP-712, no on-chain transaction, no wallet, no
allowance, no ERC-20/1155 approval** — those are Polymarket **.com**, a different venue.

So the signing work is widening a method frozenset in a **separate** `exec/signing.py`,
leaving B1/B2/B3 byte-identical. That is a much smaller job than assumed.

### B-1 [HARD BLOCK, VERIFIED BY ORCHESTRATOR] There is NO client-order-id on the retail schema

`grep -niE "clordid|clientorderid|client_order_id|idempot"` over the retail
`create-order` snapshot returns **nothing**. The institutional `insert-order` schema
*does* carry `clordId` (`api-reference_trading_insert-order_2026-08-25.md:63`) — but the
operator decision is **retail** (`POLYMARKET_US_BUILD_PLAN.md:18`), so that does not
transfer.

**This invalidates a stated architecture decision.**
`TRADING_SYSTEM_ARCHITECTURE.md:1375` says "Retries reuse the deterministic client order
ID of §7.3", and §7.3 requires the same decision re-derived after a crash to produce the
same client order ID "**so a retry is a duplicate the venue rejects**". The retail venue
provides no field to carry that ID, so **the venue cannot reject the duplicate**.
Nautilus's `ClientOrderId` would be local-only.

Now compose that with the venue's documented 5-second stopgap
(`api-reference_rate-limits_2026-08-25.md:48-52`): an order not processed within 5s is
rejected with the message `Global Rate Limit Exceeded`, and the venue explicitly says
"**You do not need to throttle your traffic in response to them.**" The venue is
actively inviting an immediate retry of an order whose true fate is ambiguous, against a
schema with no idempotency key.

**A naive retry is a double position with no venue-side dedup.** The design must be a
`SUBMIT_AMBIGUOUS` latch that refuses to retry and instead reconciles via
`GET /v1/order/{orderId}` — never a resubmit. `TRADING_ENABLEMENT_PLAN.md:147`
(REQ-EXEC-07) already mandates this; the architecture's §7.3 text must be corrected to
match, because the two currently contradict each other.

### B-2 The remaining HARD BLOCKS before a first order

1. **Does the POST body participate in the canonical string?** UNKNOWN. Venue and SDK
   both say `timestamp + METHOD + path` with no body term, but every observation on
   disk is a GET. If wrong, **100% of submissions 401**. The `body: bytes` seam exists
   and is deliberately inert (`signing.py:108-123`).
2. **Is `POST /v1/order/preview` truly non-mutating?** UNKNOWN, and the **highest-leverage
   unknown on the list** — if provable, it resolves #1 and the direction-encoding
   question with zero capital at risk. `POLYMARKET_US_BUILD_PLAN.md:20` permits its use
   only on venue/operator confirmation, which does not exist on disk.
3. **Direction encoding.** Correction to a stale repo claim: precedence **IS**
   documented — `outcomeSide`+`action` wins over `intent`
   (`api-reference_orders_orders-overview_2026-08-25.md:114`), and `price.value` ALWAYS
   refers to the YES/long side, so trading NO at X means sending `1.00 - X` (`:141,151-158`).
   `SKILL.md:153,248,306` and `TRADING_ENABLEMENT_PLAN.md:90` all still say "no
   documented precedence" — **stale, correct them**. What remains unverified is only
   whether the venue ENFORCES what it documents; the failure mode is a wrong-side fill
   costing up to 49x the intended leg at a 0.02 limit.
4. **Naked short acceptance** — unknowable read-only, operator-gated. OQ-4 stays open.
5. **Fractional quantities contradict themselves in the venue's own docs**:
   `orders-overview:185` says extra precision is silently normalized down and
   `minimumTradeQty=0.01` on 729/729 weather markets, but
   `learn_trading_basics_fractional-shares:9,30` says "does not support fractional
   contracts… whole event contracts". Unresolvable without a real order.
6. **No fill payload has ever been observed**, so commission parsing and the fixed-point
   `price_scale`/`fractional_quantity_scale` decoding are unverified.
7. **Six order-endpoint doc pages and the entire private-WebSocket page were never
   captured.** Cancel/modify/get-order rest on the SDK snapshot alone — and that SDK is
   already demonstrably drifted (omits `TIME_IN_FORCE_DAY`; types `quantity` as `int`
   where the OpenAPI says `number/double`). It is not a safe sole oracle.

### B-3 Fees: taker settled, maker unresolved and wrong in SIGN

Taker theta = 0.06 confirmed on **729/729** market objects across every raw capture
(the "60 instruments" figure elsewhere refers only to the 2026-08-30 open-climate
universe). `Fee = theta * C * p * (1-p)`. `assert_fee_schedule_known` opens today.

**Maker theta is -0.0125 — a REBATE.** Breezy charges BOTH sides at the taker
coefficient because the market payload carries one coefficient with no split. At C=100,
p=0.50 the venue **pays** $0.3125 while the model **charges** $1.50: wrong by $1.8125 and
wrong in **sign**. Handled honestly today — post-only orders are REFUSED outright with
`MakerRebateUnmodelledError` rather than mispriced (`fees.py:199-208`) — and that refusal
must survive at the **execution** boundary, not only in backtest.

### B-4 Rate limit is SHARED with the data path

20 req/s per API key across ALL authenticated endpoints
(`api-reference_rate-limits_2026-08-25.md:15`). Order egress competes with the quote tape
for one bucket. A reserved data-path share that egress cannot consume is required and
currently unmeasured — starving the tape mid-position is a real failure mode.

### B-5 Operator gates: D1 satisfied, everything else NOT

| Gate | State |
|---|---|
| D1 KYC + API key | **YES** — authenticated GET returned 200 on 4 independent runs |
| D2 funding | UNKNOWN — no balance ever read |
| D3 `BREEZY_MAX_ORDER_NOTIONAL_USD` | **NO** — unset, no default |
| D4 `BREEZY_TRADING_ENABLED` (exactly "1") | **NO** |
| D5 session notional + order count | **NO** |
| `BREEZY_TRADING_OPERATOR_ID` | **NO** |
| Real-money approval artifact | **NO** |
| CI OS-egress firewall | armed but **vacuous** until `exec/` exists |

---

## PART C — STALE CLAIMS TO CORRECT

| Claim | Where | Refuted by |
|---|---|---|
| "no documented precedence for intent vs outcomeSide+action" | `SKILL.md:153,248,306`; `TRADING_ENABLEMENT_PLAN.md:90` | `orders-overview:114` documents it |
| `manualOrderIndicator` is "bool \| Rare" | `SKILL.md:151` | required string enum (`orders-overview:230-237`) |
| "Retries reuse the deterministic client order ID" | `TRADING_SYSTEM_ARCHITECTURE.md:1375` | no such field on the retail schema (B-1) |
| REQ-VENUE-04 G2 "order endpoints undocumented" | `TRADING_ENABLEMENT_PLAN.md:89` | 11 endpoints + 2 OpenAPI schemas on disk |
| REQ-VENUE-06 G4 "tick/minQty never observed" | `TRADING_ENABLEMENT_PLAN.md:91` | 729/729 raw market objects |
| "fee_schedule_status is UNKNOWN; nothing writes KNOWN" | `docs/evidence/roi_feasibility_2026-08-26.md:72-80` | `parsing.py:477-489,1183-1195`. **Evidence file under an append-only regime — re-date, do not edit.** |
| doc line refs for chokepoint/B6b/B3 closure | `TRADING_SYSTEM_ARCHITECTURE.md` | drifted: `safety.py:32`->`:626`, `readonly_guard.py:533`->`:550`, `transport.py:105-124`->`:129-148,325` |
