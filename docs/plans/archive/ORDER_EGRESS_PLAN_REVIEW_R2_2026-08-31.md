# ORDER_EGRESS_PLAN.md rev 2 — merged round-2 review

**VERDICT: BLOCK** (2 BLOCK, 2 APPROVE-WITH-CHANGES). Same four lenses, each re-reading
its own rev-1 findings. **Rev 2 closed 15 of 16 blocking findings genuinely** — the
reviewers' words, not the author's: it "fixed the *mechanisms* rather than the
*sentences*". What remains is one survivor, two defects introduced BY fixes, and one
error the orchestrator caused. Items marked **[OV]** were re-verified by the orchestrator
directly against source or captured evidence.

## Round-2 verdicts

| Lens | Verdict | Residual |
|---|---|---|
| architecture / omission | **BLOCK** | R2-1: there is no trading node |
| prediction-market / domain | **BLOCK** | settlement idempotency; settlement source inverted |
| security / cage | APPROVE-WITH-CHANGES | cancel chokepoint is a submit bypass (blocks E-7) |
| runtime / execution-path | APPROVE-WITH-CHANGES | position attribution; dead retry pool |

---

## R2-BL-1 [CRITICAL] [OV] There is no trading node. BL-1 survives in a third form.

`grep -rn "TradingNode(" src/` returns **ZERO HITS**. `TradingNodeConfig(` appears exactly
twice: `node_config.py:195` and `:450`.

- `build_node_config` (`:163`) — which rev 2 calls "the trading site" in five separate
  sections — states in its own docstring (`:164`): *"Return the `TradingNodeConfig` for
  the **ingestion process**."* Its only production caller is `ingest_runtime`
  (`composition.py:310`).
- It pins a **FOURTH** empty literal the plan never mentions in 1547 lines:
  `data_clients={}` (`:203`).
- `build_recorder_node_config` (`:450`) is the only builder carrying a Polymarket data
  client, and the plan correctly orders it unchanged ("the recorder is a tape, not a
  trader").

So E-3 installs the exec client and E-6 registers a quote-driven strategy
(`forecast_mispricing/strategy.py:166,196` subscribes and acts in `on_quote_tick`) into
the **weather-ingest** process, which has no Polymarket data client. The subscription
routes nowhere, `on_quote_tick` never fires, no `SubmitOrder` is produced. E-6's RED (ii)
passes anyway because it drives the strategy from a **harness**, not the composed node —
the component is proven and the composition is not.

**This is LESSONS L-3 for the THIRD time, each iteration one layer further out:** the
egress workstream had no home, then strategy registration, now the trading process
itself. Each time the missing thing was the CONTAINER for what had just been built, and
each time it was invisible because it had never been decomposed.

**Fix:** an increment BEFORE E-6 that builds the trading process — a third
`TradingNodeConfig` builder + composition root + entry point, `data_clients` carrying
exactly one Polymarket client, `len(_node_config_calls()) == 3` replacing the `== 2` pin
— or an explicitly argued decision to make the recorder the trading node (which
contradicts `node_config.py:461-462`). E-6's RED (ii) must then drive the COMPOSED node
and assert a `QuoteTick` reaches `on_quote_tick`.

## R2-BL-2 [CRITICAL] [OV] The settlement source was inverted against evidence in this repo — and the orchestrator caused it.

Rev 2 promoted `GET /v1/markets/{slug}/settlement` to PRIMARY and demoted TIER_1 to
"corroborator". **The orchestrator's revision brief instructed this**, on the strength of
round 1's phrase "TIER_1 was seen once, on an archived file". That characterisation was
never verified and is wrong.

Captured evidence, re-read this pass [OV] — **five** `/settlement` captures, all 404:

```
settlement_open_510636.json          {"code":5,"message":"Settlement not found for market tc-temp-nychigh-2026-08-25-lt79f"}
settlement_open_510636_fromEp3.json  (same)
settlement_closed_15806.json         {"code":5,"message":"Settlement not found for market tc-temp-nychigh-2026-04-23-gte72lt73f"}
settlement_closed_15806_fromEp3.json (same)
settlement_closed_15389_fromEp3.json {"code":5,"message":"Settlement not found for market tc-temp-nychigh-2026-04-22-gte64f"}
```

Against the demoted source, on the two RESOLVED weather buckets:

| capture | method | settlementPx | closePx |
|---|---|---|---|
| `book_closed_15806.json` | **EVENT_TIER_1** | **1.0000** | ABSENT |
| `book_closed_15389.json` | **EVENT_TIER_1** | **0.0000** | ABSENT |
| `book_open_510636.json` (open) | EVENT_TIER_2 | 0.4900 | 0.4900 (a daily mark) |

`VENUE_FACTS_2026-08-25.md:14` has said so since 2026-08-25: *"A resolved book showed
final-looking `settlementPx`, but `/settlement` **also returned 404 for resolved weather
buckets**."* The plan cites the endpoint only from the doc snapshot and the SDK stub, and
never cites `VENUE_FACTS` at all.

**TIER_1 is 2/2 on exactly the case that matters, with correct 0/1 payouts and `closePx`
absent — the discriminator `parsing.py:887-892` already implements.** The endpoint has
never once returned 200 in this repo's evidence.

**Fix — invert the priority back.** PRIMARY = `stats.settlementPx` gated on
`EVENT_TIER_1`, from the market-book GET already in use, with `closePx`-absent as
corroborating discriminator. SECONDARY = `/settlement`, **whose 404 is the EXPECTED
response** and must be handled as such, never as an error. Cite `VENUE_FACTS:14` and all
five raw captures. Add an OQ: "does `/settlement` ever return 200 for a weather bucket?
Unresolved; 0/5 captures."

**Process note, recorded deliberately:** the orchestrator verified every Nautilus claim
against installed source and took this venue-evidence claim on report, then amplified it
into an instruction that a downstream agent correctly executed. The lesson is not "trust
agents less" — it is that **verification effort must follow the claim's consequence, not
its source's convenience.** Nautilus claims were cheap to check so they were checked;
this one required opening five JSON files.

## R2-BL-3 [CRITICAL] The settlement fill has no deterministic identity, so every poll re-applies it.

Nautilus dedupes reconciliation fills **solely by `trade_id`**
(`live/execution_engine.py:3364, 3418-3421`). A settlement is not a venue trade — no
venue `TradeId`, no `VenueOrderId` — so E-5 must fabricate both, and the plan never says
how. Rev 1 hid this behind `InvalidStateTrigger`; moving to the report path correctly
exposed it.

Hold 100 @ 0.30, settles at 1.00. Poll 1 → flat, +$70 realized. Poll 2, one interval
later, same synthetic close with a fresh `TradeId` → dedup misses → **short 100** at a
price the venue never quoted. Poll 3 → short 200. `allow_short=False` is a PRE-TRADE
control and does not touch the reconciliation path. PnL inflates $70/cycle into an
append-only calibration archive. The second dedup arm reads the cache, which a restart
clears.

**Fix:** `TradeId` and `VenueOrderId` as pure deterministic functions of
`(instrument_id, settlement_ts, settlement_px)` — e.g. `SETTLE-<slug>-<settlementSetTime>`
— so re-polling and post-restart re-reporting are idempotent by construction. RED: emit
the settlement report THREE times, assert one fill, one position transition, PnL booked
once. Also pin `commission = Money(0, USD)` (the venue's own `theta*p*(1-p)` is zero at
p in {0,1}) and `liquidity_side = NO_LIQUIDITY_SIDE` — currently unspecified, and
`fees.py:163-171` RAISES on a sideless fill, so the choice is load-bearing and silent.
Re-open OQ-14: the report path makes the deterministic-trade-id half MORE relevant, not
less; the rev-2 rationale for deferring it is inverted.

## R2-BL-4 [CRITICAL] The cancellation chokepoint becomes a full submit bypass. [OV]

BL-12's fix split authority into three chokepoints. The plan describes the cancellation
one as "zero-notional, **non-decrementing**, scope-checked" — where "scope-checked" means
checked against the permit's endpoint allowlist. **At E-11 that allowlist necessarily
contains `POST /v1/orders`.** Verified [OV]: the plan specifies **no distinct return
types** and **no cancel-class endpoint restriction**.

So `assert_live_order_cancellation_permitted(method="POST", path="/v1/orders",
request_fingerprint=<over the real CreateOrderRequest bytes>)` passes scope, mints a
capability matching a genuine submission, and the transport POSTs a live order — **D3 and
D5 both bypassed, non-decrementing, invisible to both operator controls, repeatable
without limit.** Splitting authority to fix a budget-accounting bug created a sibling key
with none of the locks.

**Fix (E-1, blocking for E-7):** three DISTINCT frozen types with their own payload
discriminators; three transport entry points each doing `type(auth) is X` (never
`isinstance`); cancellation additionally restricted to an equality-pinned **cancel-class**
frozenset (permit scope is necessary, never sufficient); reduce-only restricted to
`/v1/orders` with a session count ceiling so "non-decrementing" never means "unlimited".
REDs: a cancellation authority for `/v1/orders` refused AT MINT, and refused AT DISPATCH
by the submit path.

## R2-BL-5 [CRITICAL] The settlement fill will open a phantom short, not close the long.

`execution/engine.pyx:1561-1562` [OV]: `_determine_netting_position_id` returns
`PositionId(f"{fill.instrument_id}-{fill.strategy_id}")` — position identity includes the
strategy. `live/execution_engine.py:3551-3556` [OV]: an unclaimed report gets
`strategy_id = StrategyId("EXTERNAL")`.

Entry carries strategy `S` → `INSTR-S`. The settlement report is unclaimed → `EXTERNAL` →
resolves to `INSTR-EXTERNAL`, a DIFFERENT position. **The long stays open at entry price
with PnL never realized — the exact H-3 defect this increment exists to fix — plus a
phantom short.**

**Fix, and it is native:** E-6's registered strategy claims every instrument it trades via
`StrategyConfig.external_order_claims` (`trading/config.py:91`); E-5 states the settlement
report is attributed to the claiming strategy. Pin `filter_unclaimed_external_orders=False`
(`live/config.py:180`, default False) — set True it would silently discard the settlement
report entirely (`live/execution_engine.py:3575-3580`). RED: the settlement fill resolves
to the SAME `PositionId` as the entry.

---

## HIGH — must be answered, not deferred

- **The retry pool is wired and dead.** `RetryManager.run` retries only on `exc_types`
  (`live/retry.py:101,172`), and the transport translates only pyo3 transport failures
  into exceptions (`transport.py:328-340`) — a `429` is a normal response object. There is
  still no `(status, body) -> {terminal, retryable, AMBIGUOUS}` table, and it is the sole
  input to E-10's latch. Ship it as data in `exec/endpoints.py`; `exec/transport.py` raises
  typed exceptions for the retryable set.
- **The in-flight mark's write-ahead ordering is unstated.** It must be committed to
  durable storage BEFORE the request leaves the process. There are now TWO durable stores
  with different backends (Nautilus cache on Redis, latch on `SqliteStateStore`) and
  nothing says which is authoritative on disagreement after restart. The latch must be —
  the cache can be cleared by `_resolve_inflight_order`.
- **Redis mid-session loss degrades to STALE, not absent, state.** `flush_on_start=False`
  makes the persisted cache authoritative at startup. If Redis dies while positions are
  written, restart loads a cache that is confidently wrong; a position whose quantity
  matches but whose `avg_px_open` is stale reconciles CLEAN and corrupts G3 silently. Needs
  a staleness fence (monotonic sequence + venue cross-check, reconcile-or-halt) and a
  Redis-loss drill.
- **Fail-closed disarms the kill switch.** "Unreadable latch store ⇒ `HALT_ALL_DISPATCH`"
  contradicts "read/status/cancel always permitted" — and blocks the cancel that is the
  only way to reduce exposure on a venue with no stop-out. Make it two-directional:
  unreadable ⇒ `HALT_NEW_EXPOSURE`, cancel still permitted.
- **Endpoint-scope matching is unspecified and the venue's paths NEST.** `/v1/orders`
  prefixes `/v1/orders/open/cancel`; `/v1/order/` prefixes both preview and cancel. A
  `startswith` makes an operator grant of cancel-all authorise submission. This is the
  plan's own doctrine — "a prefix that grants an allowance fails OPEN" — unapplied to the
  field that now governs real-money capability. Exact `(method, template)` pairs only.
- **The issuer barrier's `== 1` is unsatisfiable at E-1** (`exec/factories.py` does not
  exist until E-3), pressuring it toward the `<= 1` that A-4 #5 forbids. Make it `== 0`
  with the allowlist declared at E-1, flipping to `== 1` at E-3 as its own paired
  assertion.
- **Preview's authority is unassigned** — the first concrete instance of R2-BL-4.
- **E-6.4's YES-denomination RED is vacuous** — it compares the parser's output to the
  parser's own input, so it is GREEN under both hypotheses. **The assumption is TRUE and
  provable from a capture on disk:** `book_open_510636.json` has
  `stats.lastPriceSample.longPx = 0.5300` matching the book's best bid, with
  `shortPx = 0.47 = 1 - longPx`. Use that independent oracle, on a fixture materially off
  0.50 (a 0.50/0.50 market is indistinguishable under either hypothesis).
- **The settlement watchdog did not land** (`grep -ci watchdog` = 0). A position past
  `expiration_ns` with no settlement price from ANY source must latch a named
  `SettlementOverdueError`. This is what makes R2-BL-2's whole class loud instead of
  silent.
- **`external_order_claims` / `filter_unclaimed_external_orders`** unpinned (see R2-BL-5).
- **`cost_cap = payout_cap x price` computed at instrument load** — the zero case is
  closed, the STALENESS case is not: a cap derived at 0.50 permits 10x the contracts at
  0.05. If §4.1's claim that all ceilings are already premium USD holds, delete the
  conversion from the runtime path.
- **The fee reserve is dropped from §4.2's "equal because"** — at p=0.05 the taker fee is
  ~5.7% of premium, the region the weather model targets, so the substitution is not the
  unqualified upper bound claimed.

---

## CLOSED IN ROUND 2 — do not re-litigate

BL-3 direction map (now a total 2-row map, `price.value` unmodified, inversion AST-banned,
exhaustive test re-run at E-11 against serialised body bytes — "the 49x hazard is asserted
at the wire, not at the function"); BL-4 mechanism (report path verified correct against
`live/execution_engine.py:3582-3600`; `generate_missing_orders=False` remains meaningful);
BL-6 (named halt owner `_assert_reconciled`, G1 restated as cache/report match); BL-7
(session ledger keyed by operator, never reset, carry-forward — the 32x hole is closed);
BL-9 (moved into `pytest_configure`, aborts before collection — prevention, not reporting);
BL-10 (one `request_fingerprint`, AST ban, one-byte-mutation RED, plus a notional derived
from the bytes that will be transmitted); BL-11 (four-part cap guard, plus instruments with
no quote are not registered at all); BL-13 (`inflight_check_retries` pinned; synthetic
UNKNOWN is a latch TRIGGER); BL-15 (`_set_account_id` FIRST, never trusting the await's
return); BL-16 (per-record refusal); N-11a; F-5; `AccountType.CASH` chosen; price bounds;
resting-TIF refusal; `TERMINATED` as a distinct non-0/1 state; OQ-5 closed making E-13 100x
smaller; the reordered ambiguity ladder and pre-ack cancel bound; E-8's probe body fixed
to be both non-empty AND market-scoped.

All four lenses independently confirmed: **no violation of the immutable-foundation rule
anywhere in E-0..E-13.**
