# ORDER_EGRESS_PLAN.md rev 1 — merged adversarial review

**VERDICT: BLOCK — unanimous.** Four independent lenses (architecture/omission,
security/cage, runtime/execution-path, prediction-market/domain) each returned BLOCK
independently, without visibility of one another. Findings below are DE-DUPLICATED and
the one inter-reviewer contradiction is RESOLVED. Items marked **[OV]** were re-verified
by the orchestrator directly against source.

The plan is not scrapped. Its build-order insight (E-0 first; the whole
report/reconcile surface is GET, so most of the goal lands before any write capability
exists) survived every lens and must be preserved. What follows is what must change.

---

## RESOLVED CONTRADICTION

The domain reviewer endorsed the plan's claim that a price-less, trigger-less MARKET
order hits `continue` at `risk/engine.pyx:848-851`. The runtime reviewer called that
citation wrong. **The runtime reviewer is correct [OV]:** `:786-789` is the MARKET branch
(`"Cannot check MARKET order risk: no prices for ..."`); `:848-851` sits inside the
TRAILING_STOP branch, which a MARKET order never reaches. The *conclusion* (never emit
MARKET) is unaffected and correct. But the plan tagged this `[V]` — "verified by direct
read at the cited line" — and it was not, which means §0.2's evidence tags cannot be
trusted as a class and every `[V]` claim needs re-checking in revision 2.

---

## BLOCKING — the walk does not reach the goal

**BL-1 [OV] No increment registers a strategy; the finished walk still cannot place an
order.** `runtime/node_config.py:204,212,218` pins THREE empty literals, and its own
comment says `strategies=[]` "removes **the only component that calls `submit_order` at
all**". The plan disposes of `exec_clients` only. Execute E-0..E-12 perfectly and you get
a live-capable execution client with zero order sources. **This is LESSONS L-3 recurring
inside the document written to fix L-3** — the plan decomposed the egress long pole and
inherited a second undecomposed one, because it lived behind a different file's barrier.

**BL-2 [OV] All six strategies emit MARKET orders; E-4 refuses MARKET by name.**
`forecast_edge.py:168`, `strike_ladder.py:305`, `harness_probe.py:199`,
`forecast_mispricing/strategy.py:349`, `calibration_mean_reversion/strategy.py:375`,
`forecast_revision/strategy.py:371`. Whichever strategy BL-1 eventually registers is
either LIMIT-only by luck or **denied 100% of the time** — and the denial is counted and
named, so the bot looks healthy while emitting nothing.

**BL-3 [OV] The direction mapping is never stated, and the only committed direction test
asserts a transform that must never fire.** `parsing.py:1086` builds ONE `BinaryOption`
per slug from `long_sides[0]`. Breezy never holds a NO-side instrument, so the venue's
`price.value = 1.00 - X` rule is the IDENTITY for every order Breezy can construct. The
plan's E-10 price row and its only direction RED encode the inversion. Worse,
`risk.py:75-78` comments that "short YES is spelled buy NO" — an implementer following it
maps `OrderSide.SELL` to `ORDER_INTENT_BUY_SHORT`, turning a reducing sell of 100 @ 0.30
into a **buy of 100 NO at 0.70**, which also self-matches the resting YES. The plan's test
passes while this happens. **The mitigation creates the 49x hazard it was written to
prevent.**

---

## BLOCKING — the settlement exit cannot work

**BL-4 [OV] `generate_order_filled` on a FILLED order raises `InvalidStateTrigger`.**
`model/orders/base.pyx:110-160` has 8 transitions INTO `FILLED` and **none FROM** it. The
plan disabled `generate_missing_orders` to fix the price, then kept only the fill half —
there is no order for the fill to land on. G3 is unreachable as designed. The fix is the
report path: return a synthetic closing `OrderStatusReport` + `FillReport` at the venue's
settlement price and let external-order reconciliation create the order.

**BL-5 [OV] The settlement signal is gated on a value the live capture does not carry.**
`parsing.py:229` sets `TERMINAL_SETTLEMENT_METHOD = "..._EVENT_TIER_1"`, while
`parsing.py:220-222` records that the live capture carries **`..._EVENT_TIER_2`**
(TIER_1 was seen once, on an archived file). With `generate_missing_orders=False` removing
every fallback, **nothing closes the position**: PnL is never booked, and after 12 stuck
buckets `max_simultaneous_positions` is exhausted and the bot stops trading while
believing it is fully invested. The venue's own `GET /v1/markets/{slug}/settlement` — a
read-only call usable at E-2 with zero write capability — is never mentioned in the plan.

**BL-6 [OV] `generate_missing_orders=False` turns a position discrepancy into SUCCESS.**
`live/execution_engine.py:2503-2510`: on `not quantities_match`, logs a warning and
`return True`. The plan pins NETTING, so the strict hedging branch is unreachable. G1
asserts "reconciliation SUCCEEDED rather than swallowed" — under this config SUCCEEDED no
longer implies matched, and the assertion passes precisely in the state it was written to
detect. The promised halt has no owner: no module, no increment.

---

## BLOCKING — the operator contract is not enforceable

**BL-7 [OV] Permit renewal resets the session budget, so the maximum-daily-budget control
is unenforceable beyond 15 minutes.** `safety.py:547-549` re-reads the ceilings from the
environment on every issuance; `:574-578` installs a FRESH `_Budget` under a fresh
`permit_id`; `_PERMIT_BUDGETS` (`:332`) is keyed per permit with nothing aggregating
across them. `PERMIT_TTL_NS` is 15 minutes (`:157`), so any real session MUST renew, and
each renewal restores the full ceiling — **~32x on an 8-hour day**. No malice required;
the TTL forces it. This defeats one of the two controls the operator reserved. Renewal
must carry forward the REMAINING budget, and `issue_live_trading_permit` needs the B6a
treatment (exactly one caller, pinned path) — today it has **no caller barrier at all**.

**BL-8 [OV] The permit carries no endpoint scope, so cancel-all to exposure-opening is a
one-line edit.** The chokepoint takes credentials, permit, indicator, notional,
fingerprint, now_ns — **no path, no method**. The only endpoint constraint anywhere is a
frozenset literal inside `exec/transport.py`. From E-7 the full real-money environment
(D3/D4/D5 + operator id) must already be set, so going from cancel-only to order-sending
is one frozenset edit plus its pin, same commit, same author, **zero additional operator
act**. The plan's "exposure-opening first reachable at E-10" is true of the code and false
of the authority. Fix costs one field: an operator-set endpoint allowlist carried on the
permit and hashed into its payload.

**BL-9 [OV] N2 reports; it does not stop.** `find_execution_egress_modules` appears only
in the test file — `conftest.py` never consults it, and there is no `UsageError` or
`shouldstop`. A failing assertion fails ONE test while pytest runs everything else in the
same process. The plan's completion criterion ("a bare `uv run pytest -q` fails N2")
conflates *fails* with *prevents*: a suite containing a write-capable transport would
transmit first and print a red test afterward. The rule must move into `pytest_configure`
and abort before collection.

**BL-10 `request_fingerprint` has no contract.** `safety.py:644-646` defines it as opaque
caller-chosen bytes; `consume` re-checks a hash of caller-supplied input against a
caller-supplied digest. Nothing ties either to the bytes actually transmitted. A
fingerprint over a constant, or over `(method, path)` only, yields one capability
authorizing ANY body at the minted notional — a different market, side, or size. The
plan's paired RED passes for any fingerprint function, because the test uses the same one.
Needs a single named `request_fingerprint(method, path, body_bytes)`, an AST ban on any
other construction, and a test that mutates one byte of the body handed to the transport.

**BL-11 [OV] The plan's own notional-cap remedy has a zero-value fail-open.**
`risk/engine.pyx:677` is `if max_notional_setting:` — a **present `Decimal(0)` is falsy**,
so the cap never fires. E-4's guard checks presence only. Since E-4 computes
`cost_cap = payout_cap x price` at instrument load, a bucket with no quote yet yields
`cost_cap = 0`, `set_max_notional_per_order` accepts it, Breezy's presence check passes,
and that instrument has **no ceiling at all** — the H-1 class of bypass reached *through*
the remedy. Guard must assert present AND `Decimal` AND `> 0.01` AND round-trips non-zero
when re-read from the engine.

**BL-12 Cancel has no notional, so it either bypasses the chokepoint or spends the
operator's budget.** `safety.py:678-679` refuses `order_notional_usd <= 0`; `:712-713`
decrements both budget dimensions at mint. E-6 requires the capability consumed on EVERY
dispatch path, and E-6's only endpoint is cancel-all. So either cancels skip the
chokepoint (voiding the plan's central guarantee) or every cancel burns an order-count
unit and fabricated dollars — and with `RetryManagerPool` on that path, a retry storm
exhausts the permit, which then blocks the submit path **and the kill switch** together.
Needs a separate zero-notional, non-decrementing cancel authority.

---

## BLOCKING — runtime correctness

**BL-13 Nautilus fabricates `OrderRejected(reason="UNKNOWN")` under the ambiguity latch.**
`live/execution_engine.py:736-750` → `_resolve_inflight_order` (`:767-795`) after
`inflight_check_retries` (default 5, `live/config.py:186` — unpinned by the plan). ~15-25s
after an ambiguous submit, the cache marks the order REJECTED and goes flat while the
venue may hold it. E-9's latch stops *Breezy* resubmitting; it does nothing about the
framework silently clearing state, and Nautilus's version is what the risk engine and
portfolio read. Fix: pin the retry count, and treat a synthetic UNKNOWN rejection on a
latched market as a latch TRIGGER, never a resolution.

**BL-14 Crash recovery is absent; the cache is non-durable.**
`grep -niE "crash|restart|persist|CacheConfig"` over the plan returns ZERO hits, while
`node_config.py:199,455` pins `cache=CacheConfig(database=None, flush_on_start=False)`.
Die holding a position → restart → empty cache → BL-6's silent-pass reconciliation → the
bot runs with **zero knowledge of live exposure**, all caps see zero, and it can open a
second position in the same market. Every gate green. E-3 must make the persistence
decision explicitly, alongside `oms_type`/`account_type`.

**BL-15 `AccountId` is never set, which re-arms H-1 one step upstream.**
`execution/client.pyx:135` initialises `account_id = None`; `_set_account_id` (`:148-152`)
is unmentioned anywhere in the plan. And the failure is silent in exactly the way the plan
exists to prevent: `live/execution_client.py:536-540` — if `not self.account_id`, log a
warning and **return as if successful**. So a `_connect` that fetches balances, calls
`generate_account_state`, and awaits registration produces one warning, no account in
cache, and `risk/engine.pyx:684-689` `return True`. H-1 fully restored.

**BL-16 A refusing fill mapper takes down ALL THREE report types.**
`live/execution_client.py:498-514` gathers the three plural report coroutines in a bare
`asyncio.gather` inside one `try`, returning `None` on any exception — no
`return_exceptions=True`. The plan's named refusal in `generate_fill_reports` therefore
discards order-status and position reports too; the kernel then logs "Execution state
could not be reconciled" and **does not start the trader**. After E-10 that means: crash
holding a position → restart → no reconciliation → no trader → no settlement exit, no
cancel, position abandoned, on one ERROR line. Refuse per RECORD, not per call.

---

## HIGH — must be answered in revision 2, not deferred

- **A FIFTH native fail-open [OV]:** `risk/engine.pyx:949,968,1001,1026` all guard on
  `free is not None`. If the emitted `AccountBalance.currency` is not identically the
  instrument quote currency (USD), `balance_free` returns `None` and every cash check
  passes — H-1 reproduced with a perfectly valid account in the cache. A venue balance
  reported as `USDC` does it. Add to the F-table as F-5, plus a currency-identity contract
  test and a `BalanceCurrencyMismatchError` denial.
- **IOC orders never appear in `/v1/orders/open`.** All three live strategies submit IOC.
  E-9's resolution ladder leads with open-orders, which is structurally empty for IOC, then
  falls to activities — whose mapper the plan says refuses until E-12, AFTER exposure opens
  at E-10. Reorder the ladder to lead with position/balance delta, both E-3-verified GETs.
- **The venue documents a pre-ack cancel that bounds the ambiguity** ("You can always
  cancel an order before you have received an acknowledgement", and pure cancels are exempt
  from the stopgap). Market-scoped cancel-all is allowlisted from E-6. E-9 converts a
  venue-supported bounded resolution into an unbounded human page. Use it — it is not a
  resubmit.
- **Absolute price bounds [0.01, 0.99] are unhandled.** Tick-aligned does not mean valid;
  an out-of-bounds price returns an order id for an order that can never fill, consuming
  the bucket via `pending_qty` and the exclusivity rule, possibly never appearing in
  open-orders to be cancelled. Add `PriceOutOfVenueBoundsError` with REDs at 0.005/0.995.
- **E-7 cannot discriminate OQ-1 with an empty body** (all three non-domain reviewers
  agreed independently). `cancel_all` sends `{}` when unparameterised, so both hypotheses
  produce the same canonical string and a 200 closes OQ-1 falsely. Send
  `{"slugs":[<one slug proven to have zero open orders>]}` — non-empty body AND scoped, so
  it cannot cancel the operator's manual orders elsewhere on the same key.
- **Submit timeout unspecified against the 5s stopgap.** A 3s client timeout manufactures
  the ambiguity the plan fears, for an order the venue will itself reject at 5s. Pin it
  above the stopgap.
- **`order_notional_usd` has no unit line** — the one operator-facing dollar quantity,
  checked against D3 and decrementing the permit budget, is absent from the §3 unit ledger.
  At p=0.05 premium vs payout differ 20x. Declare it premium at risk, with a test that the
  value passed to `consume` equals the value in the signed body.
- **The maker prohibition is enforced only against `post_only`**, which does not prevent a
  GTC limit resting and filling as maker. `resting_ladder.py` is a registrable strategy
  submitting three GTC orders. Either refuse non-IOC/FOK at the execution boundary or
  retract the non-goal.
- **`account_type` / `base_currency` are never chosen.** `AccountType.CASH` is never
  affirmatively selected in 1026 lines; `base_currency` never appears. MARGIN is handled as
  a runtime denial for a condition decided once at construction.
- **OQ-5 (fractional quantities) is already answered on disk** — the captured OpenAPI says
  `quantity: number/double`, "Supports decimal quantities on markets whose minimumTradeQty
  is less than 1". The plan weighs only the two NON-normative sources. Its "conservative"
  fallback of whole contracts makes the E-12 probe **100x larger** than necessary on the
  increment whose whole purpose is minimising first-send risk.
- **Voided / terminated markets are unhandled**, and two of the three terminal states in
  `EXPIRED_MARKET_STATES` are not in the venue's enum at all (no `SETTLED`, no `CLOSED`;
  the real one, `MARKET_STATE_TERMINATED`, is absent from Breezy's set). A voided market
  settling at 0 would book a 100% loss on a trade that refunded capital — permanently, into
  an append-only calibration archive.
- **Arch N9/N10 silently dropped** from the barrier table without being retired by name.
- **The plan's `[V]` tags are unreliable** (see RESOLVED CONTRADICTION) — re-verify all.

---

## PRESERVE — every lens tried to break these and could not

- **E-0 first.** The A-1 reasoning is sound and the ordering is correct.
- **The N-1 insight** — the entire report/reconcile surface is GET — genuinely lets G1/G3/G4
  land before any write capability exists. Best structural idea in the document.
- **Denying BEFORE Nautilus is consulted (E-4)** is the only correct response to what is
  now five silent fail-opens, and RED "prove a 1000x order PASSES with Breezy's denial
  removed" is exactly the proof-by-construction discipline required.
- **Rejecting settlement option (a)** — writing settlement price into `avg_px_open` would
  corrupt entry-price arithmetic and all downstream attribution. Correct.
- **Refusing to substitute `PortfolioFacade.equity()`** for the static `_equity()`.
- **"Never resubmit"** as the answer to the missing idempotency key — necessary, though it
  must be split so an ACKNOWLEDGED venue reject (terminal, no double-position risk) is
  distinguished from a transport timeout.
- **Reuse over authorship**: `RetryManagerPool` wired not written, native state machine
  untouched, `AccountType.BETTING` banned by name, `SandboxExecutionClient` refused on
  fee-model grounds. No lens found a single violation of the immutable-foundation rule.
- **The E-7 epistemics** — "preview's non-mutating status is the very thing under test, so
  it cannot also be the assumption that makes the test safe" — is right. Keep the decision;
  fix the probe body.
