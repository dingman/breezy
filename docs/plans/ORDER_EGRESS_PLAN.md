# Order egress — implementation plan

> **SPLIT AND PARTIALLY SUPERSEDED — 2026-08-31.** Three adversarial review rounds
> (16 blocking → 5 criticals → ~7 criticals + ~10 highs) showed this document
> DIVERGING: each revision's fixes created defects faster than they closed them.
> See `ORDER_EGRESS_PLAN_REVIEW_R3_2026-08-31.md` and LESSONS L-4.
>
> **Do not implement from this file.**
>
> - **E-0..E-4** (NO-SEND: firewall, cage, trading process, endpoints + report
>   mappers, refusing execution client) → **`EXEC_CLIENT_NOSEND_PLAN.md`**.
> - **E-5..E-14** (denial layer, settlement exit, order-source enablement, and
>   every SEND increment incl. the multi-type authority algebra) → deferred to
>   successor plans, to be written after the container exists as code.
>
> **Known-false claims retained here for the record, NOT for use:** N-14 ("the
> process itself does not exist") is FALSE — a `TradingNode` is built and run today
> (`quote_tape_cli.py:195`, `:151-156`); the real gap is the absence of a
> trading-ROLE config and a `breezy-trade` entry point. The settlement `TradeId`
> format exceeds the 36-char cap and is unconstructable. The primary settlement
> source names the wrong endpoint and the wrong field path. Findings, evidence and
> the surviving material worth carrying forward are in the round-3 review.


**Status:** **REVISION 3.** Not executed. Revision 1 was reviewed by four
independent adversarial lenses (architecture/omission, security/cage,
runtime/execution-path, prediction-market/domain), each blind to the others, and
**all four returned BLOCK**. Revision 2 closed 15 of those 16 findings and drew
2 BLOCK / 2 APPROVE-WITH-CHANGES. This revision resolves R2-BL-1..R2-BL-5 and
every HIGH item in `docs/plans/ORDER_EGRESS_PLAN_REVIEW_R2_2026-08-31.md`, or
rebuts a finding with evidence. §2 is the disposition for both rounds.
**Created:** 2026-08-31. **Revised (rev 2, rev 3):** 2026-08-31.

**Closes:** LESSONS `L-3` — the active plan `DATA_CAPTURE_AND_RISK_PLAN.md`,
executed perfectly to completion, still ends with a bot that cannot place an
order (`LESSONS.md:104-146`).

**What changed from revision 2, in one paragraph.** Revision 2 committed L-3 a
**third** time, one layer further out each round: first the egress workstream had
no home, then the order source had no registration, and now **the process itself
does not exist**. `grep -rn "TradingNode(" src/` returns **zero hits** `[V]`;
`build_node_config` — which revision 2 called "the trading site" in five separate
sections — says in its own docstring (`node_config.py:164` `[V]`) *"Return the
`TradingNodeConfig` for the **ingestion process**"*, pins a **fourth** empty
literal revision 2 never mentioned (`data_clients={}`, `:203` `[V]`), and is
reached only from `ingest_runtime` (`composition.py:310` `[V]`). Revision 3 adds
**E-2 — the trading process**, the container every later increment runs inside,
placed *before* the execution client rather than after the strategy so that no
increment again builds a component with nowhere to live. It inverts the
settlement source back to the market book gated on `EVENT_TIER_1`, against
captured evidence in this repo that the round-2 brief had contradicted
(R2-BL-2); gives the settlement fill a **deterministic identity** and a claiming
strategy, so re-polling can no longer manufacture a phantom short (R2-BL-3,
R2-BL-5); and splits one capability type into **three distinct frozen types**,
because revision 2's chokepoint split had created a submit bypass (R2-BL-4).
Nothing was cut. Where revision 2's own text is now wrong it is corrected in
place and the correction is recorded in §0.2, not silently overwritten.

**Authority chain.** `EXECUTION_CLIENT_NATIVE_AUDIT_2026-08-31.md` (Nautilus
side, H-1..H-6) and `EGRESS_PREREQUISITES_2026-08-31.md` (cage + venue side,
A-0..A-4, B-0..B-5, C) are the evidence base and win on fact.
`ORDER_EGRESS_PLAN_REVIEW_R2_2026-08-31.md` is the specification for this
revision and wins over both where it corrects them; the round-1 review
`ORDER_EGRESS_PLAN_REVIEW_2026-08-31.md` stays binding where round 2 did not
supersede it. **Raw captured venue evidence outranks every document above,
including a review and including an orchestrator instruction** — R2-BL-2 exists
because that precedence was inverted exactly once, and the correction is
structural, not an apology. `TRADING_SYSTEM_ARCHITECTURE.md` §8 is
the prior design, retained where nothing refutes it; §11 lists every place it is
now refuted. `GO_LIVE_PLAN.md` Phase F (`:227-236`) is SUPERSEDED (`:3-17`) and
is cited only for the *existence* of the workstream and operator gates D1-D5.

**Companion, not superseded.** `DATA_CAPTURE_AND_RISK_PLAN.md` remains the active
plan for P0-P7 and is not re-planned here. Its §2.3 (`:286-302`) declares the
exposure unit every cap here is measured in and is fixed input.

---

## 0. Evidence status

### 0.1 Classes of claim

| Tag | Meaning |
|---|---|
| `[V]` | **Verified in the revision-2 pass** by direct read of the cited file at the cited line, by me, after the review invalidated the tag class. |
| `[E]` | Inherited from a committed evidence doc that states it was orchestrator-verified; cited to the doc AND its own source cite. |
| `[I]` | **Inferred** — a design consequence, not a fact read off a file. Flagged everywhere. |
| `[U]` | **Unknown.** Never assumed away; every `[U]` has a row in §8. |

### 0.2 Corrections made to this document's own text

The review found one wrong citation: revision 1 cited `risk/engine.pyx:848-851`
for the MARKET-order `continue`; that range is inside the **TRAILING_STOP**
branch, which a MARKET order never reaches. The correct site is `:786-789`
(`"Cannot check MARKET order risk: no prices for {instrument.id}"` then
`continue`) `[V]`. The conclusion — never emit MARKET — was right; the citation
was not. **Every `[V]` in revision 2 has been re-read at its line.** Four
citations moved and are corrected in place: `engine.pyx:848-851 → :786-789`;
the cap lookup `:670 → :675`; the cap truthiness test `→ :677`;
`live/execution_client.py` account-id warning `:536-540 → :544-546`.

**Revision 3 corrects four claims revision 2 made in its own voice.** Each was
wrong in a way a green suite would not have caught, which is why they are listed
rather than quietly overwritten.

| # | Revision 2 said | Actually `[V]` | Consequence |
|---|---|---|---|
| **C-1** | `node_config.py` pins **three** empty literals; `build_node_config` is "the trading site" | It pins **four** — `data_clients={}` (`:203`) as well — and `build_node_config` (`:163`) is the **ingestion** process by its own docstring (`:164`), reached only from `ingest_runtime` (`composition.py:310`). There is **no trading site**: `grep -rn "TradingNode(" src/` → zero hits; the only `TradingNode(` in the repo is `scripts/venue/polymarket_us_auth_smoke.py:1623` | **R2-BL-1.** New **E-2**; N-14 |
| **C-2** | "TIER_1 was seen once, on an archived file" (N-11), so `/v1/markets/{slug}/settlement` becomes the primary source | TIER_1 is **2/2 on the resolved weather buckets on disk**, with correct 0/1 payouts; `/v1/markets/{slug}/settlement` is **0/5 — every capture is a 404** | **R2-BL-2.** N-15; source inverted back in **E-6** |
| **C-3** | the recorder builder is `build_recorder_node_config` | it is **`build_quote_tape_node_config`** (`node_config.py:381`); the line cites (`:450-464`) were right, the name was not | naming only, corrected throughout |
| **C-4** | the three-chokepoint split closes BL-12 | it opens a submit bypass: no distinct return types and no cancel-class endpoint restriction were specified | **R2-BL-4.** §6.3, **E-1** |

C-2 is the one that matters methodologically. The claim entered revision 1 as an
unverified characterisation, was amplified by the round-2 brief into an
instruction, and was executed faithfully. It cost five `cat`s to check. **The rule
this document now runs on: verification effort follows the claim's consequence,
not its source's convenience** — a claim that decides where settlement prices come
from is checked against raw captures even when a reviewer, an orchestrator or this
document's own previous revision already asserted it.

### 0.3 New facts established across the three passes

`[V]`, all re-read for revision 2; N-11 and N-7 are **corrected** in revision 3
(§0.2 C-1, C-2).

| # | Fact | Cite | Consequence |
|---|---|---|---|
| **N-1** | The **entire** report / account / reconciliation / settlement surface is `GET`: `/v1/account/balances` (`sdk_snapshot/polymarket_us_0.1.2/resources/account.py:15`), `/v1/portfolio/positions` (`resources/portfolio.py:19`), `/v1/portfolio/activities` (`:24`), `/v1/orders/open` (`resources/orders.py:34`), `/v1/order/{order_id}` (`:42`), **`/v1/markets/{slug}/settlement`** (`resources/markets.py:37-39`). Only submit (`/v1/orders`, `:27`), cancel (`:47`), modify (`:55`), cancel-all (`:62`), preview (`:70`), close-position (`:78`) are `POST`. | above | A **fully reconciling `LiveExecutionClient` that refuses every order** can be built on the existing byte-identical GET-only read stack with **zero write capability in the tree**. Drives §7's ordering. Survived all four lenses. |
| **N-2** | `max_notional_per_order` is `dict[str,int]` keyed by instrument-id string, populated ONLY from static config at load (`NT/risk/engine.pyx:192-196`); lookup is `self._max_notional_per_order.get(instrument.id)` (`:675`) and a miss leaves `max_notional = None`, so the cap at `:912-917` never fires. | `NT/risk/engine.pyx:192-196, 675-679, 912-917`; `NT/risk/config.py:44` | Breezy discovers instruments at RUNTIME, so the dict is necessarily empty and H-2's cap is **inert by default**. Native remedy is a runtime call: `cpdef set_max_notional_per_order` (`:279`). |
| **N-3** | A MARKET order with no cached quote **and** no cached trade logs a warning and **`continue`s** — skipped, not denied (`NT/risk/engine.pyx:786-789`). For a LIMIT order `last_px = order.price` (`:855`). | above | Never emit MARKET. Fourth fail-open (F-4). |
| **N-4** | `CreateOrderRequest` carries `synchronousExecution` + `maxBlockTime` (`create-order:107-113`); `CreateOrderResponse` carries only `id` and `executions` (`:127-139`). | above | Confirms B-1 independently: no client identity is echoed. |
| **N-5** | `participateDontInitiate` — "order must rest on the book prior to matching (maker only)" — is a first-class request field (`create-order:85-89`). | above | The maker refusal must be a *request-construction* refusal, not only a fee-model one. |
| **N-6** | `_query_account` is **called** (`NT/live/execution_client.py:332`) and never defined; `_query_order` **is** defined (`:516`). | above | H-4 confirmed by direct read. |
| **N-7** | **CORRECTED (C-1).** `node_config.py` pins **FOUR** empty literals at the ingest site — `data_clients={}` (`:203`), `exec_clients={}` (`:204`), `strategies=[]` (`:212`), `exec_algorithms=[]` (`:218`) — and the quote-tape site repeats three of them (`:460,463,464`) while carrying one data client (`:459`). The comment at `:205-211` states `strategies=[]` "removes **the only component that calls `submit_order` at all**". Revision 2 named three of the four and called the ingest site "the trading site"; it is not one (N-14). | `src/breezy/runtime/node_config.py:195-220, 450-465` `[V]` | **BL-1** and **R2-BL-1**. Revision 1's walk ended with no order source; revision 2's ended with no process. Now **E-2** then **E-7**. |
| **N-8** | **Three strategies emit MARKET unconditionally** — `forecast_edge.py:168`, `strike_ladder.py:305`, `harness_probe.py:199`. The three weather strategies branch on `use_limit_orders`, which **defaults `True`** (`forecast_mispricing/config.py:110`, `forecast_revision/config.py:123`, `calibration_mean_reversion/config.py:126`) and emits LIMIT + `TimeInForce.IOC`; the MARKET arm (`forecast_revision/strategy.py:371`, `forecast_mispricing/strategy.py:349`, `calibration_mean_reversion/strategy.py:375`) is one config flag away. | above `[V]` | **BL-2, scope-corrected.** See §2. |
| **N-9** | `parsing.py:1083-1086` requires **exactly one** long market side and builds ONE `BinaryOption` per slug from `long_sides[0]`. Breezy therefore never holds a NO-side instrument. | `src/breezy/adapters/polymarket_us/parsing.py:1081-1091` `[V]` | **BL-3.** The venue's `price.value = 1.00 − X` rule is the **identity** for every order Breezy can construct; implementing the inversion creates the hazard it was meant to prevent. |
| **N-10** | `model/orders/base.pyx` `_ORDER_STATE_TABLE` has **eight transitions INTO `FILLED` and none FROM it** — the table ends at `(PARTIALLY_FILLED, FILLED)` with no `(FILLED, …)` key. | `NT/model/orders/base.pyx:110-160` `[V]` | **BL-4.** `generate_order_filled` on a FILLED order raises `InvalidStateTrigger`. The settlement exit must use the **report** path. |
| **N-11** | **CORRECTED (C-2).** `TERMINAL_SETTLEMENT_METHOD = "…_EVENT_TIER_1"` (`parsing.py:229`) and `parsing.py:220-222` records that an **OPEN** market's capture carries `…_EVENT_TIER_2`. Revision 2 added "TIER_1 was seen once, on an archived file" — that was never verified and is wrong: see N-15. | `parsing.py:220-222, 229` `[V]`; N-15 | **BL-5 stands** — an `InstrumentClose` trigger alone still closes nothing, because TIER_2 is what an open market carries. **The price SOURCE conclusion drawn from it does not** (R2-BL-2). |
| **N-12** | `EXPIRED_MARKET_STATES = {MARKET_STATE_EXPIRED, MARKET_STATE_SETTLED, MARKET_STATE_CLOSED}` (`parsing.py:212-214`), but the venue's documented enum is `OPEN, PREOPEN, HALTED, SUSPENDED, MATCH_AND_CLOSE_AUCTION, EXPIRED, TERMINATED` (`docs_snapshots/api-reference_websocket_markets_2026-08-25.md`; `api-reference_markets_get-market-book_2026-08-25.md`). **`SETTLED` and `CLOSED` do not exist; `TERMINATED` — the real second terminal state — is absent from Breezy's set.** | above `[V]` | A voided/terminated market is invisible to the settlement path. §11 defect D-4. |
| **N-13** | `DatabaseConfig.type` accepts **`{'redis'}` only** (field-inspected against installed 1.231.0); `node_config.py:199,455` pin `CacheConfig(database=None, flush_on_start=False)`. | `NT/common/config.py` `DatabaseConfig` docstring `[V]`; `node_config.py:199,455` `[V]` | **BL-14.** Durable cache is a Redis dependency, and it is a hard prerequisite of E-12. |

**Established in the revision-3 pass.** N-14..N-21 are the newest and least
reviewed facts in this document; attack these before anything else.

| # | Fact | Cite | Consequence |
|---|---|---|---|
| **N-14** | **Breezy has two processes and neither trades.** `grep -rn "TradingNode(" src/` → **zero hits**. `TradingNodeConfig(` appears exactly twice: `build_node_config` (`:163`, docstring `:164` = *"the ingestion process"*, sole production caller `ingest_runtime` at `composition.py:310`) and `build_quote_tape_node_config` (`:381`, comment `:461-462` = *"the recorder is a tape, not a trader"*). Entry points are `breezy` and `breezy-quote-tape` only (`pyproject.toml:256,260`), and `:257-259` states the two are deliberately separate processes. | `src/breezy/runtime/node_config.py:163-164, 203-218, 381, 451-464`; `composition.py:310`; `pyproject.toml:255-260` `[V]` | **R2-BL-1.** A strategy or exec client registered into `build_node_config` joins a node with **`data_clients={}`** — quotes reach nothing, `on_quote_tick` never fires. **E-2** builds the third process. |
| **N-15** | **The settlement endpoint has never returned 200 in this repo; the market book has, twice, on exactly the case that matters.** Five `/settlement` captures, all `{"code":5,"message":"Settlement not found for market …"}`: `settlement_open_510636.json`, `settlement_open_510636_fromEp3.json`, `settlement_closed_15806.json`, `settlement_closed_15806_fromEp3.json`, `settlement_closed_15389_fromEp3.json`. Both **resolved** weather buckets carry `settlementPriceCalculationMethod = …EVENT_TIER_1` with `stats.settlementPx` `1.0000` / `0.0000`, a populated `settlementSetTime`, and **`closePx` absent**. The one OPEN capture carries TIER_2, `closePx == settlementPx == 0.4900`, i.e. a daily mark. | `docs/evidence/venue/polymarket_us/raw/{settlement_*,book_closed_15806,book_closed_15389,book_open_510636}.json` `[V]`; `VENUE_FACTS_2026-08-25.md:14` `[E]` | **R2-BL-2.** Primary source is the market book gated on TIER_1; `/settlement` is secondary and its **404 is the expected response**. |
| **N-16** | Reconciliation dedupes fills **solely by `TradeId`**: `get_existing_fill_for_trade_id(order, report.trade_id)` and `report.trade_id in order.trade_ids`. There is no other idempotency key on the report path. | `NT/live/execution_engine.py:3364-3369, 3418-3421` `[V]` | **R2-BL-3.** A settlement fill with a fresh `TradeId` per poll re-applies every cycle. Identity must be a pure function of the settlement facts. |
| **N-17** | **Position identity includes the strategy.** `_determine_netting_position_id` returns `PositionId(f"{fill.instrument_id}-{fill.strategy_id}")`. An unclaimed external report resolves `strategy_id` via `get_external_order_claim(...)` and otherwise falls back to `StrategyId("EXTERNAL")`. `StrategyConfig.external_order_claims: list[InstrumentId] \| None` is the native claim mechanism; `filter_unclaimed_external_orders` defaults `False` and, set `True`, **discards** an unclaimed report outright. | `NT/execution/engine.pyx:1561-1562`; `NT/live/execution_engine.py:3551, 3556, 3575-3580`; `NT/trading/config.py:91`; `NT/live/config.py:180` `[V]` | **R2-BL-5.** Without a claim the settlement fill lands on `INSTR-EXTERNAL` — a phantom short beside a long that never closes. Native fix, no authored code. |
| **N-18** | `RetryManager.run` retries **only** exceptions in `exc_types` (`exc_types` is a constructor parameter; the handler is `except self.exc_types as e`). Breezy's transport raises only on pyo3 transport failure; an HTTP `429` or `503` is an ordinary response object and is never retried. | `NT/live/retry.py:101, 172` `[V]`; `adapters/polymarket_us/transport.py:328-340` `[V]` | **HIGH.** `RetryManagerPool` as wired in revision 2 is **dead on the venue's own rate-limit responses**. The `(status, body) → {terminal, retryable, AMBIGUOUS}` table is the missing input, and it is also E-11's latch input. |
| **N-19** | `FillReport.__init__` takes `commission` and `liquidity_side` as **explicit required parameters** (alongside `account_id, instrument_id, venue_order_id, trade_id, order_side, last_qty, last_px, report_id, ts_event, ts_init`, with `avg_px`, `client_order_id`, `venue_position_id` optional). | `NT/execution/reports.pyx` `FillReport.__init__` `[V]` | **R2-BL-3.** Both values are chosen by Breezy at construction; neither has a default to fall back on. |
| **N-20** | The node-config barrier quantifies over **every** `TradingNodeConfig(...)` call site in `runtime/node_config.py` and asserts `exec_clients`, `strategies`, `exec_algorithms` are **empty literals** at each, with a separate pin that there are exactly two sites. | `tests/unit/test_runtime_node_config.py:289-305, 338-349` `[V]` | A third builder carrying a strategy **fails this barrier as written**. It must therefore be re-expressed **per site** with the exact expected value, not relaxed — §6.2. |
| **N-21** | An independent YES-denomination oracle exists on disk: in `book_open_510636.json` the best bid is `0.5300` and `stats.lastPriceSample.longPx` is `0.5300`, with `shortPx = 0.47 = 1 − longPx`. The market is materially off 0.50, so the two hypotheses are distinguishable. | `docs/evidence/venue/polymarket_us/raw/book_open_510636.json` `[V]` | **HIGH.** Replaces E-7.4's vacuous self-comparison with a real oracle. |

### 0.4 The F-table — five native fail-opens on one code path

Revision 1 named four. The review found a fifth. All five are why E-6 denies
**before** Nautilus is consulted, and why a green run is never evidence a native
check engaged.

| ID | Fail-open | Cite `[V]` | Breezy's denial |
|---|---|---|---|
| **F-1** | No cached account → `self._log.debug(...)` then **`return True`** (pass) | `NT/risk/engine.pyx:684-689` | `NoCachedAccountError` |
| **F-2** | `account.is_margin_account` → **`return True`** unconditionally | `:691-692` | `MarginAccountUnsupportedError`, plus `account_type=CASH` fixed at construction |
| **F-3** | Per-instrument cap absent **or falsy**: `max_notional_setting: Decimal \| None = …get(instrument.id)` then `if max_notional_setting:` — a **present `Decimal("0")` is falsy**, so the cap never fires | `:675-679` | `UnpopulatedNotionalCapError` — present **and** `Decimal` **and** `> Decimal("0.01")` **and** round-trips non-zero when re-read |
| **F-4** | MARKET with no cached quote and no cached trade → warning then **`continue`** (skipped) | `:786-789` | `MarketOrderRefusedError`; `ORDER_TYPE_LIMIT` always |
| **F-5** | **NEW.** All four cash checks guard on `free is not None`; `balance_free(quote_currency)` returns `None` when the emitted `AccountBalance.currency` is not identically the instrument's quote currency (`USD`). A venue balance reported as `USDC` reproduces F-1 **with a perfectly valid account in the cache.** | `:949, 968, 1001, 1026` | `BalanceCurrencyMismatchError` at `AccountState` emission time — `_connect` fails closed |

`BinaryOption.currency` is `USD` (`parsing.py:1204` `[V]`), so F-5's identity test
is `emitted_balance.currency == USD`, asserted at emission, not at submit.

---

## 1. GOAL STATE and WALK (LESSONS L-3)

### GOAL STATE (falsifiable predicate)

> With operator gates D1-D5 set and a permit issued, a running Breezy
> `TradingNode`:
> **G0** **exists as a process at all** — a `TradingNode` built from a
> `TradingNodeConfig` that carries a Polymarket.us **data** client, a registered
> strategy and a registered execution client, started from its own entry point,
> in which a live `QuoteTick` for a weather instrument **reaches the registered
> strategy's `on_quote_tick`**.
> **G1** reconciles a **true** venue account at startup — `account_id` is set, a
> non-`None` `Account` denominated in `USD` is in the Nautilus `Cache` before the
> first `SubmitOrder`, and reconciliation is asserted **by Breezy** to have
> matched, not merely to have returned.
> **G2** carries a decision from **a registered strategy** through
> `submit_order` → a signed `POST /v1/orders` → Nautilus's native order state
> machine to a terminal state off **real venue events**, with no Breezy-authored
> state machine, retry loop or position ledger.
> **G3** exits at settlement with realized PnL equal to
> `qty × (settlementPx − avg_px_open) − fees` — **not** zero, **not** a stale
> quote, and **not** dependent on a signal the live venue does not emit.
> **G4** refuses, with a **named, counted refusal raised before Nautilus is
> consulted**, every order it cannot price, size, direction-encode, time or
> account for — covering all five fail-opens of §0.4.
> **G5** does all of the above with **no** cage barrier deleted or weakened, and
> with the operator's two reserved controls (budget ceiling, position ceiling)
> enforceable across a whole session rather than a 15-minute window.
> **G6** survives a crash while holding a position: restart reconstructs true
> exposure or refuses to trade.

**Falsifier.** Any of G0-G6 failing live; or the suite passing green while any is
unimplemented. G0's falsifier is the one that has been missed three times and is
now mechanical: **a `QuoteTick` that does not reach `on_quote_tick` in the
composed node**, asserted against the node the entry point builds and never
against a test harness. G5's falsifier is a barrier whose scope narrowed without a
strictly stronger assertion in the **same commit**. G6's falsifier is a restart
that trades with an empty cache.

**G6 is new in revision 2** (BL-14). **G0 is new in revision 3** (R2-BL-1), and it
is deliberately first: every other clause is a property *of a running process*, so
a goal state that never named the process could be fully satisfied on paper by
components that have nowhere to run. That is the precise shape of all three L-3
recurrences.

### 1.0 The container check, performed before the walk was written

The question the last three rounds each failed to ask, asked here of every
artifact this plan creates: **what container does this need in order to run, and
does an increment build that container?**

| Artifact | Container it needs to run | Which increment builds that container | Before rev 3 |
|---|---|---|---|
| `PolymarketUSExecutionClient` | a `TradingNode` whose config registers it in `exec_clients` **and** that is actually instantiated and started | **E-2** builds the node + entry point; **E-4** registers the client into it | **nothing** — `build_node_config` is the ingest process and is never given an exec client by any running code |
| the registered strategy | the same node, with a **data** client feeding it quotes | **E-2** (data client), **E-7** (strategy registration) | **nothing** — `build_node_config` pins `data_clients={}` (`:203` `[V]`), so a subscription routes nowhere |
| report mappers (`exec/reports.py`) | an exec client whose report coroutines the `LiveExecutionEngine` calls | **E-4**, inside E-2's node | E-3 built mappers with no caller |
| the settlement exit | the reconciliation cycle of a live engine, plus a claiming strategy for position attribution | **E-6**, needing **E-2** + **E-7** | E-5 emitted reports into a reconciliation loop that never ran |
| the denial layer | a `RiskEngine` in a started node, reached from a real `submit_order` | **E-5**, inside E-2's node | E-4 proved denials against directly-constructed orders |
| the write chain | the exec client's `_submit_order`, reached from a registered strategy | **E-8**, needing **E-2** + **E-4** + **E-7** | — |
| the durable session ledger | a process with a lifetime; a restart to survive | **E-2**'s process, **E-12**'s durability | ledger was process-local in a process that did not exist |

Two of the seven rows read "nothing" before this revision. Both are the same
omission at different depths, and both are closed by a single increment placed
**before** the components that need it rather than after them.

### WALK — increment by increment, with what each ADDS

Revision 1 asserted a walk. Revision 2 executed it but only over the layer it had
decomposed. This one names, for every increment, the goal clause it advances
**and the process it runs inside** — the column whose absence is R2-BL-1.

| # | Increment | Adds toward the goal | Runs inside | Send |
|---|---|---|---|---|
| **E-0** | Arm the egress firewall for `exec/`; abort collection, not just fail | G5 precondition — makes every later increment non-silent | CI | none |
| **E-1** | Cage strengthening + permit hardening (three authority types, endpoint scope, budget carry-forward, single issuer, fingerprint contract) | **G5** complete for authority; nothing else can be trusted until this holds | CI | none |
| **E-2** | **NEW — the trading process:** `build_trading_node_config` + `trading_runtime` composition root + `breezy-trade` entry point, with **one Polymarket data client** and nothing else | **G0** — the container every later increment runs inside. First time a Breezy `TradingNode` exists at all | itself | GET + WS (same surface as the recorder) |
| **E-3** | `exec/endpoints.py` + `exec/reports.py` over the existing GET stack, incl. the retry-classification table | G1 (report inputs), G3 (settlement **price source**), G4 (denial inputs) | E-2's node | GET |
| **E-4** | `exec/client.py` — `account_id` set, `AccountState` emitted, Breezy-side reconciliation match assertion, Redis-backed cache + staleness fence, `CASH` account; **all eight lifecycle coroutines refuse** | **G1** complete; **G6** complete; G2 skeleton | E-2's node | GET |
| **E-5** | Denial layer over all five fail-opens + venue-bounds + time-in-force refusals | **G4** complete | E-2's node | GET |
| **E-6** | Settlement exit via a **deterministically identified** synthetic closing `OrderStatusReport` + `FillReport` at the TIER_1 settlement price, attributed to the claiming strategy | **G3** complete | E-2's node | GET |
| **E-7** | Order-source enablement: register exactly one strategy, LIMIT/IOC-only, `external_order_claims` set, exhaustive direction mapping pinned | **G0** complete (quote → `on_quote_tick` in the composed node); G2 **source** exists; **G3** attribution | E-2's node | GET |
| **E-8** | `exec/{signing,transport,egress}.py`; allowlist = one scoped cancel-all | G2 transport; **cannot open exposure** | E-2's node | `POST /v1/orders/open/cancel` |
| **E-9** | Signature-scheme probe (scoped cancel-all with a **non-empty** body) | resolves OQ-1 | operator script | as E-8 |
| **E-10** | Allowlist += preview; preview probe | resolves OQ-2, OQ-3, tick/bounds | operator script | + `POST /v1/order/preview` |
| **E-11** | Ambiguity latch, in-flight invariant, pre-ack cancel resolution, Nautilus synthetic-rejection interception | G2 safe under the 5 s stopgap; G4 | E-2's node | no new endpoint |
| **E-12** | Allowlist += `POST /v1/orders`; `_submit_order`; durable session ledger | **G2** complete — **first exposure-opening capability** | E-2's node | + `POST /v1/orders` |
| **E-13** | Allowlist += order cancel; `_cancel_order` / `_cancel_all_orders` | G2 working-order management; G4 kill switch has teeth | E-2's node | + `POST /v1/order/{id}/cancel` |
| **E-14** | Single-order live probe, fill-payload capture, enablement | G0-G6 demonstrated live | E-2's node | real money |

**The walk check, performed — increment by increment, what each ADDS.**

- **E-0** adds the *precondition* for every later claim: without the E0 path rule
  arming at collection time, any subsequent increment can land write capability
  invisibly, so no later increment's green is evidence of anything. Adds no goal
  clause; makes the other twelve legible.
- **E-1** adds **G5** for authority: three distinct capability types, an
  operator-set endpoint scope of exact `(method, template)` pairs, a
  never-reset session ledger, one fingerprint constructor, one permit issuer.
  Nothing after this point can quietly acquire authority it was not granted.
- **E-2** adds **G0**: a process. It is the first increment whose output is a
  thing that *runs*. Before it, everything this plan builds is a component with
  nowhere to live — the C-1 defect. Its oracle is a live `QuoteTick` observed in
  the node the entry point builds.
- **E-3** adds G1's, G3's and G4's *inputs*: the endpoint table, the per-record
  report mappers and the retry-classification table. It adds no capability; it
  adds the data every later increment consumes.
- **E-4** adds **G1** and **G6**, *inside E-2's node*: a true account in the cache
  before any order, a Breezy-owned reconciliation match assertion, a Redis-backed
  cache with a staleness fence. It is also the first increment to narrow the new
  node's `exec_clients`.
- **E-5** adds **G4**: five named denials in front of five native fail-opens, each
  executing before the `RiskEngine` is consulted.
- **E-6** adds **G3**: PnL is realized at settlement, once, at the TIER_1 price,
  on a deterministic identity that re-polling and restart cannot duplicate.
- **E-7** adds the second half of **G0** and the *source* half of **G2**: a
  registered strategy that receives quotes in the composed node and produces real
  `SubmitOrder`s, every one denied at the boundary, with `external_order_claims`
  set so E-6's settlement fill lands on the *same* position.
- **E-8** adds G2's transport, scoped to one endpoint that cannot open exposure.
- **E-9** and **E-10** add no goal clause — they resolve OQ-1/OQ-2/OQ-3, and G2 is
  not claimable while those are `[U]`.
- **E-11** adds G2's *safety* under the venue's 5 s stopgap: the latch, the
  one-in-flight invariant, and interception of Nautilus's synthetic rejection.
- **E-12** adds **G2**: the first exposure-opening capability, with the durable
  ledger that makes G5's budget control survive a restart.
- **E-13** adds G4's teeth — a kill switch that can actually reduce exposure — and
  E-11's bounded ambiguity resolution.
- **E-14** demonstrates **G0-G6** live, once, at `minimumTradeQty`.

**Coverage.** G0 ← E-2+E-7. G1 ← E-3+E-4. G2 ← E-7 (source) + E-8/E-12
(transport) + E-5 (orders the denial layer will not refuse). G3 ← E-3+E-6+E-7
(attribution). G4 ← E-5+E-13. G5 ← E-0+E-1+E-12 (durability). G6 ← E-4. **No
increment depends on an unresolved `[U]`**: E-12 is gated on E-9/E-10 having
resolved OQ-1/OQ-2/OQ-3, and §8 states the branch if they do not.

**Where E-2 sits and why it is not later.** The review's fix permitted an
increment "before E-7". It is placed **before E-4** instead, because the exec
client, the report mappers, the denial layer and the settlement exit each need the
same container, and building it after them would repeat the error one layer
shallower rather than removing it. From E-2 onward, every increment's RED runs
against **the node the `breezy-trade` entry point builds**, never a harness that
merely resembles it.

**Where E-7 sits and why.** It is `[NO-SEND]` and lands *before* the write chain,
so registering a strategy produces a full decision→`submit_order`→**denied**
trace with zero network capability. That is the only configuration in which the
BL-2 class of defect is observable rather than theoretical: if the registered
strategy emits anything E-5 refuses, E-7 fails **loudly and offline**.

**The rejected alternative, argued.** The review offered "make the recorder the
trading node". Rejected on evidence: `build_quote_tape_node_config` exists
*because* the two roles have incompatible startup requirements — the ingest
process must start on a host with **no** venue configuration and the recorder
must refuse to start **without** it (`pyproject.toml:257-259` `[V]`), the recorder
pins `StreamingConfig` writing every message to a feather stream (`:465-473`
`[V]`), and its own comment says "the recorder is a tape, not a trader"
(`:461-462` `[V]`). Making the tape trade would couple the calibration archive's
integrity to the trading process's uptime, which is exactly backwards: the tape's
value is that it keeps recording when trading halts.

---

## 2. Review disposition — both rounds

Accepted unless stated. Where I rebut, the rebuttal is evidenced and the finding
is still addressed.

### 2.1 Round 1 — BL-1..BL-16 and every HIGH

| ID | Disposition | Where |
|---|---|---|
| **BL-1** no order source | **ACCEPTED — the most serious finding.** N-7. | **E-7**; §1 walk; G2 restated to require a registered strategy |
| **BL-2** strategies emit MARKET | **ACCEPTED, scope-corrected** (see below) | **E-7** |
| **BL-3** direction mapping inverted | **ACCEPTED in full.** N-9. The inversion is **not implemented at all** and is banned by AST scan. | **E-7** §6.3; E-12 request table |
| **BL-4** `generate_order_filled` on FILLED | **ACCEPTED.** N-10. Rebuilt on the report path. | **E-6** |
| **BL-5** TIER_1 signal absent live | **ACCEPTED as to the trigger, REVERSED as to the source** (R2-BL-2, C-2). `InstrumentClose` alone still closes nothing; but the primary price source is the **market book gated on TIER_1**, not the endpoint. N-11, N-15. | **E-3**, **E-6** |
| **BL-6** discrepancy → SUCCESS | **ACCEPTED.** `live/execution_engine.py:2503-2510` `[V]`. Breezy owns the match assertion. | **E-4** |
| **BL-7** budget resets on renewal | **ACCEPTED.** `safety.py:547-551, 574-578` `[V]`; TTL 15 min `:157`. | **E-1**; durable ledger **E-12** |
| **BL-8** permit has no endpoint scope | **ACCEPTED.** Chokepoint takes no method/path (`safety.py:626-634` `[V]`). | **E-1** |
| **BL-9** N2 reports, does not stop | **ACCEPTED.** `find_execution_egress_modules` appears only in its own test file `[V]`; `conftest.py:227` already has `pytest_configure` and `:268` already uses `pytest.exit` — the mechanism exists and is unused for N2. | **E-0** |
| **BL-10** fingerprint has no contract | **ACCEPTED.** `safety.py:644-646` `[V]`. | **E-1** |
| **BL-11** zero-value cap fail-open | **ACCEPTED.** F-3, `engine.pyx:677` `[V]`. | **E-5** |
| **BL-12** cancel has no notional | **ACCEPTED.** `safety.py:678-679, 712-713` `[V]`. Separate non-decrementing cancel authority. | **E-1**, **E-8** |
| **BL-13** synthetic `OrderRejected(UNKNOWN)` | **ACCEPTED.** `live/execution_engine.py:736-751 → _resolve_inflight_order :766-795` `[V]`; `inflight_check_retries=5` (`live/config.py:186` `[V]`). | **E-11** |
| **BL-14** no crash recovery | **ACCEPTED.** N-13. New goal clause **G6**. | **E-4** |
| **BL-15** `AccountId` never set | **ACCEPTED.** `execution/client.pyx:135` `account_id = None`, `_set_account_id` `:148-152` `[V]`; `live/execution_client.py:544-546` warns and returns as if successful `[V]`. | **E-4** |
| **BL-16** refusing fill mapper kills all three reports | **ACCEPTED.** bare `asyncio.gather` at `live/execution_client.py:500-504`, `return None` `:515` `[V]`. Refuse per RECORD. | **E-3** |
| HIGH — fifth fail-open | ACCEPTED | §0.4 **F-5**; **E-5** |
| HIGH — IOC never in `/v1/orders/open` | ACCEPTED; ladder reordered to lead with position/balance delta | **E-11** |
| HIGH — pre-ack cancel bounds ambiguity | ACCEPTED. `rate-limits:58,60` `[V]` — "Pure cancels are not affected"; "You can always cancel an order before you have received an acknowledgement". | **E-11** |
| HIGH — absolute price bounds | ACCEPTED. `overview:162,164` `[V]` — an out-of-bounds price **still returns an orderID** and never fills. | **E-5** |
| HIGH — E-9 empty body cannot discriminate | ACCEPTED; scoped non-empty body | **E-9** |
| HIGH — submit timeout vs 5 s stopgap | ACCEPTED; pinned above the stopgap | **E-11**, **E-12** |
| HIGH — `order_notional_usd` unit line | ACCEPTED | **§3.5** |
| HIGH — maker prohibition only vs `post_only` | ACCEPTED. `resting_ladder.py:190,204` submit `TimeInForce.GTC, post_only=False` `[V]`. Non-IOC/FOK refused at the boundary. | **E-5**, §10 non-goal 2 |
| HIGH — `account_type`/`base_currency` unchosen | ACCEPTED | **E-4** |
| HIGH — OQ-5 already answered on disk | **ACCEPTED, and it changes E-14's size** | **§8 OQ-5**, **E-14** |
| HIGH — voided/terminated markets | ACCEPTED. N-12. | **E-6**, §11 D-4 |
| HIGH — arch N9/N10 dropped | ACCEPTED; retired by name | **§6.2** |
| HIGH — `[V]` tags unreliable | ACCEPTED; whole class re-verified | **§0.2** |

**The one partial rebuttal — BL-2's scope.** The finding says all six strategies
emit MARKET and whichever is registered is "denied 100 % of the time". Verified
`[V]`: **three** are unconditional MARKET (`forecast_edge.py:168`,
`strike_ladder.py:305`, `harness_probe.py:199`); the three weather strategies
branch on `use_limit_orders`, which **defaults `True`** in all three configs
(`forecast_mispricing/config.py:110`, `forecast_revision/config.py:123`,
`calibration_mean_reversion/config.py:126`) and emits LIMIT with
`TimeInForce.IOC`; their MARKET arm is the `else`. So a weather strategy
registered at default config is *not* denied 100 % of the time. **This narrows
the finding and does not weaken it**, for three reasons, and the correction is
what makes E-7 specifiable: (i) it identifies exactly which strategies are
registrable — only the three weather ones; (ii) the MARKET arm is **one config
flag** from a 100 %-denial bot that looks healthy, so E-5's refusal must be paired
with a config-level ban, not just a runtime denial; (iii) `resting_ladder.py` is
LIMIT but **GTC**, which the maker prohibition must also refuse. A rebuttal that
made the finding *smaller* without those three consequences would be a defect;
these are in E-5 and E-7.

### 2.2 Round 2 — R2-BL-1..R2-BL-5 and every HIGH

| ID | Disposition | Where |
|---|---|---|
| **R2-BL-1** there is no trading node | **ACCEPTED — the most serious finding, and the third L-3 recurrence.** N-14, C-1. The container is built **before** the components that need it, not before E-7 only. | **E-2**; §1.0 container check; **G0**; §6.2 barrier row |
| **R2-BL-2** settlement source inverted | **ACCEPTED, with one citation corrected** (see below). N-15. Primary reverts to `stats.settlementPx` gated on `EVENT_TIER_1`; `/settlement` is secondary and its **404 is the expected response**. | **E-3**, **E-6**; **OQ-16** |
| **R2-BL-3** settlement fill has no deterministic identity | **ACCEPTED, with one citation narrowed** (see below). N-16, N-19. | **E-6**; **OQ-14 re-opened** |
| **R2-BL-4** cancellation chokepoint is a submit bypass | **ACCEPTED in full.** C-4. Three distinct frozen types, `type(auth) is X`, cancel-class endpoint frozenset, reduce-only ceiling. | **E-1** (blocking for **E-8**); §6.3 |
| **R2-BL-5** settlement fill opens a phantom short | **ACCEPTED in full, and the fix is native.** N-17. | **E-7** (`external_order_claims`), **E-6** (attribution), **E-4** (`filter_unclaimed_external_orders=False`) |
| HIGH — retry pool wired and dead | **ACCEPTED.** N-18. Classification table as **data** in `exec/endpoints.py`; typed exceptions raised by `exec/transport.py`; it is also E-11's latch input. | **E-3**, **E-8**, **E-11** |
| HIGH — in-flight mark write-ahead ordering unstated | **ACCEPTED.** The latch is committed to `SqliteStateStore` **before** the request leaves the process, and the **latch is authoritative** over the Nautilus cache on disagreement after restart — the cache can be cleared by `_resolve_inflight_order` (`live/execution_engine.py:766-795` `[V]`), the latch cannot. | **E-11** |
| HIGH — Redis mid-session loss degrades to STALE | **ACCEPTED.** Staleness fence: monotonic session sequence + venue cross-check, reconcile-or-halt; a Redis-loss drill. | **E-4** |
| HIGH — fail-closed disarms the kill switch | **ACCEPTED.** Two-directional: unreadable latch store ⇒ `HALT_NEW_EXPOSURE`, **cancel still permitted**. | **E-11**, §6.4 |
| HIGH — endpoint-scope matching unspecified; paths NEST | **ACCEPTED.** Exact `(method, template)` pairs; `startswith`/`in` AST-banned on scope comparison. | **E-1**, §6.3 |
| HIGH — issuer barrier `== 1` unsatisfiable at E-1 | **ACCEPTED.** `== 0` at E-1 with the allowlist declared, flipping to `== 1` at **E-4** as its own paired assertion. | **E-1**, **E-4** |
| HIGH — preview's authority unassigned | **ACCEPTED.** Preview takes a fourth type or none — resolved explicitly in §6.3. | **E-1**, **E-10** |
| HIGH — E-7.4's YES RED is vacuous | **ACCEPTED, and the oracle is on disk.** N-21. | **E-7.4** |
| HIGH — settlement watchdog did not land | **ACCEPTED.** `SettlementOverdueError` latches when a position is past `expiration_ns` with no price from any source. | **E-6** |
| HIGH — `external_order_claims` unpinned | **ACCEPTED** (R2-BL-5). | **E-4**, **E-7** |
| HIGH — `cost_cap` staleness | **ACCEPTED, and the conversion is DELETED.** §4.1's unit claim does hold, so the conversion was dead code carrying a staleness hazard. | **§4.2**, **E-5** |
| HIGH — fee reserve dropped from §4.2 | **ACCEPTED.** The bound is qualified, not unqualified. | **§4.2** |

**R2-BL-2 — accepted, one citation corrected.** The finding says `closePx`-absent
is "the discriminator `parsing.py:887-892` already implements". It is not:
`_is_terminal_settlement` (`:887-892` `[V]`) requires the market **state** to be
terminal **and** the method to be `TERMINAL_SETTLEMENT_METHOD`, and never reads
`closePx` at all. The `closePx`-absent property is a **real, unimplemented**
corroborator, 2/2 on the resolved captures and contradicted on the open one
(N-15). Correcting this matters because an implementer told the discriminator
already exists would ship nothing, and the state∧method conjunction alone cannot
distinguish "TIER_1 and settled" from "TIER_1 and mid-auction". E-6 implements it
as a third conjunct, with the divergence recorded as a named refusal rather than a
silent preference.

**R2-BL-3 — accepted, one citation narrowed.** The finding argues the
`liquidity_side` choice is load-bearing because "`fees.py:163-171` RAISES on a
sideless fill". That raise is in Breezy's **backtest** `FeeModel`
(`fees.py:163-171` `[V]`), which the live report path does not call, so as stated
it overclaims. The conclusion is nonetheless correct and the pin is **mandatory**
for a stronger reason: `FillReport.__init__` takes `commission` and
`liquidity_side` as **explicit required parameters** (N-19 `[V]`) — there is no
default to fall through to, so the value is chosen either deliberately or by
accident. The narrower argument is the one E-6 records, and the `fees.py` raise is
kept as the second-order reason: any later routing of a settlement fill through
Breezy's fee model would raise, so a wrong choice fails loudly there too.

**BL-3, one clarification that prevents a bad fix.** `risk.py:75-78` `[V]` reads
*"on a Polymarket CLOB you cannot sell tokens you do not hold — 'short YES' is
spelled 'buy NO', a different instrument with its own book"*. In context that is
the **justification for `allow_short=False`**, not an instruction to map
`OrderSide.SELL` to `ORDER_INTENT_BUY_SHORT`. The review's hazard is real — an
implementer skimming it would map exactly that way — but the comment itself is
correct and must **not** be "fixed". E-7 removes the ambiguity by stating the
mapping exhaustively in one place and banning the NO-side vocabulary from `exec/`.

---

## 3. Reuse ledger

### 3.1 Nautilus provides it — do NOT rebuild (null hypothesis CONFIRMED)

`[E]` from `EXECUTION_CLIENT_NATIVE_AUDIT_2026-08-31.md:133-142` with its own
cites into installed `nautilus_trader==1.231.0`. No lens found a single violation
of the immutable-foundation rule in revision 1; that posture is unchanged.

| Capability | Native anchor | Breezy's job |
|---|---|---|
| Order state machine, 14 states, `_ORDER_STATE_TABLE` | `NT/model/enums.py:383-397`; `NT/model/orders/base.pyx:110-160` `[V]` | **obey it** — see N-10 |
| Lifecycle event construction + msgbus routing | `NT/execution/client.pyx:329-917` (`generate_account_state:329`, `_denied:370`, `_submitted:411`, `_rejected:447`, `_accepted:491`, `_filled:820`) `[V]` | call them |
| Order cache, `orders_open`/`orders_inflight`, position tracking | `NT/execution/client.pyx:826, 853-857` | none |
| Startup + continuous reconciliation, in-flight recovery | `NT/live/execution_engine.py` | supply reports; **assert the match ourselves** (BL-6) |
| **Exponential backoff / retry** | `NT/live/retry.py:24-62`; `RetryManagerPool` `:242` `[V]` | **wire it; never write a backoff loop** |
| Submit-rate throttling; `TradingState` gating | `NT/risk/engine.pyx:142, 1084`; `:556-580` | configure |
| Native IOC / FOK | `TimeInForce`, `NT/model/enums.py:446-453` `[E]` | map |
| `BinaryOption` 0-1 instrument | `NT/model/instruments/binary_option.pyx` | already built (`parsing.py:1200-1221` `[V]`) |
| Per-order notional cap | `NT/risk/engine.pyx:912-917` — see N-2/F-3 | populate at runtime, guard the zero |
| Durable cache | `CacheConfig.database` → `DatabaseConfig(type="redis")` `[V]` | **configure** (G6), not build |
| Rate-limited pooled HTTP with keyed quotas | `nautilus_pyo3.HttpClient` | already wrapped |
| **The process container itself** — `TradingNode`, `TradingNodeConfig`, `LiveExecClientFactory` / `LiveDataClientFactory` registration, kernel lifecycle | `NT/live/node.py`; `NT/live/factories.py`; `NT/system/kernel.py` `[E]` | **configure and instantiate one** (E-2). Breezy authors a config builder, a composition root and an entry point — **no runtime**. The two existing builders (`node_config.py:163, 381` `[V]`) are the pattern to mirror |
| **Position attribution for external reports** | `StrategyConfig.external_order_claims` (`NT/trading/config.py:91`); `get_external_order_claim` (`NT/live/execution_engine.py:3551`) `[V]` | **set the claim** (E-7). Breezy authors no position-id logic — N-17 |
| **Fill idempotency on the report path** | dedup by `TradeId` (`NT/live/execution_engine.py:3364-3369, 3418-3421`) `[V]` | **supply a deterministic `TradeId`** (E-6). Breezy authors no dedup — it makes the native one work |

**Do not "improve":** `CashAccount.calculate_pnls` special-cases
`InstrumentClass.SPORTS_BETTING` only; `BinaryOption` is `BINARY_OPTION` and takes
the generic `notional_value` branch, correct at multiplier 1 (`AUDIT:144-149`
`[E]`). `AccountType.BETTING` / `accounting/accounts/betting.pyx` is a different
model (back/lay stake) — banned by name in E-1.

### 3.2 The existing read adapter — reuse VERBATIM

All `[V]`, constructed together at `factories.py:366-400`.

| Component | Path | Reused for | Changed? |
|---|---|---|---|
| `Ed25519RequestSigner` | `signing.py:185-286` | nothing on the write path — §6 | **BYTE-IDENTICAL**; `PERMITTED_METHODS = {"GET"}` (`:84`) never widened |
| `NautilusHttpTransport` | `transport.py:237-368` | all read/report/account/settlement traffic | **BYTE-IDENTICAL**; the B3 closure (`:129-148`) untouched |
| `PolymarketUSHttpClient` | `http.py:94-270` | `get_authenticated` for balances/positions/orders/activities/settlement | **BYTE-IDENTICAL**; `PERMITTED_METHODS` (`:64`) never widened |
| `PolymarketUSInstrumentProvider` | `provider.py` | instrument cache shared by data and exec clients | unchanged |
| `PolymarketUSCredentials` + loader | `credentials.py`; `factories.py:364` | the exec client's own credential load | unchanged |
| chokepoint / permit / capability | `safety.py:527-716` | the capability chain | **HARDENED** in E-1: BL-7/8/10/12. Payload version `v2 → v3`. |
| maker refusal | `fees.py:190-208` | mirrored at the execution boundary, and **widened** to non-IOC/FOK | unchanged; extended |
| venue settlement parsing | `parsing.py:1020-1034` | secondary settlement source (primary is the endpoint) | unchanged; **`EXPIRED_MARKET_STATES` corrected** (N-12, §11 D-4) |
| data-client factory shape | `factories.py:320-437` | template for the exec factory | unchanged |

### 3.3 GENUINELY ABSENT — what Breezy must author

1. **Venue protocol translation** — `SubmitOrder` → `CreateOrderRequest`; venue
   JSON → `OrderStatusReport`/`FillReport`/`PositionStatusReport`/`AccountState`.
2. **`AccountState` emission** — `generate_account_state` exists
   (`NT/execution/client.pyx:329`) but **nothing calls it for you**
   (`AUDIT:36-40` `[E]`); `node_builder.py:201-263` never seeds an account. Add
   `_set_account_id` (BL-15).
3. **Settlement-as-exit semantics** — `grep "settle|Settle" NT/execution/engine.pyx`
   → zero matches (`AUDIT:90-93` `[E]`).
4. **Per-venue order-type and time-in-force refusal** — Nautilus validates price,
   quantity and GTD expiry only (`NT/risk/engine.pyx:584-606`); the rest is
   entirely the client's job (`AUDIT:160-169` `[E]`).
5. **`SUBMIT_AMBIGUOUS` latch + one-in-flight invariant + interception of
   Nautilus's synthetic `OrderRejected(UNKNOWN)`** (BL-13).
6. **The write-side signing/transport/egress chain and its capability threading.**
7. **A reserved data-path share** of the 20 req/s key-wide budget (B-4 `[E]`;
   `api-reference_rate-limits_2026-08-25.md:15` `[V]`).
8. **A session-scoped, carry-forward operator budget ledger** (BL-7) — Nautilus
   has no concept of an operator spend ceiling at all.
9. **A trading process** (R2-BL-1, N-14). Nautilus supplies `TradingNode` and
   every factory it needs; what is absent is a Breezy `TradingNodeConfig` builder
   that registers a venue data client, a strategy and an execution client
   together, a composition root that starts it, and an entry point that reaches
   it. Breezy has two processes — ingest (`build_node_config`, `data_clients={}`)
   and the quote tape (`build_quote_tape_node_config`, `exec_clients={}`) — and
   **neither can trade by construction**. This is configuration and composition,
   not a runtime; the null hypothesis holds everywhere except the config itself.
10. **A `(status, body) → {terminal, retryable, AMBIGUOUS}` classification table**
    (N-18). `RetryManagerPool` retries only `exc_types`, and the venue's 429/503
    arrive as ordinary responses — so the *policy* is absent even though the
    *mechanism* is native. Breezy authors the table, never the backoff.

---

## 4. The unit ledger (LESSONS L-2)

Every native substitution carries `unit before / unit after / equal because`.

### 4.1 The system unit

Fixed input from `DATA_CAPTURE_AND_RISK_PLAN.md:288`: **every ceiling is PREMIUM
AT RISK, in USD.** No second unit is introduced.

### 4.2 `max_notional_per_order` — a genuine native fit

**unit before** = Breezy §2.3 per-order ceiling = `qty × entry_price` USD premium
(`DATA_CAPTURE_AND_RISK_PLAN.md:298`). **unit after** =
`instrument.notional_value(effective_quantity, last_px)` → non-inverse
`qty × multiplier × price` (`NT/model/instruments/base.pyx:844` `[E]`) with
`BinaryOption` multiplier hardcoded to 1 (`binary_option.pyx:138` `[E]`), and for
a **LIMIT** order `last_px = order.price` (`NT/risk/engine.pyx:855` `[V]`),
`effective_price = last_px` (`:875` `[V]`) → `qty × limit_price` USD.
**equal because** multiplier is 1, so native notional is cash outlay, not payout;
and for a BUY LIMIT the limit price is the **maximum** payable, so
`qty × limit_price ≥ qty × fill_price` = premium at risk. An upper bound on **premium**,
conservative in the safe direction; equality only for a resting limit filling at
its own price.

**The bound is not unqualified — the fee reserve (HIGH).** `qty × limit_price` is
an upper bound on premium *paid*, not on cash *consumed*: the taker fee is charged
on top. With taker theta 0.06 the fee is `0.06 × p × (1 − p) × qty`, which at
p = 0.05 is **≈5.7 % of premium** (`0.06 × 0.05 × 0.95 = 0.00285` per contract
against `0.05` of premium) — and p ≈ 0.05 is precisely the region the weather
model targets. So the native cap bounds `qty × limit_price` while the account is
debited up to `qty × limit_price × 1.057`. **equal because** is therefore
qualified: equal **to premium at risk**, and an under-estimate of **cash
consumed** by up to the fee rate. Two consequences, both in E-5: the operator's
D3 ceiling and the permit budget are premium-denominated and stay so (§4.5), and
the value handed to `set_max_notional_per_order` is reduced by the maximum fee
reserve so the native cap cannot admit an order the balance cannot fund. The
maximum of `0.06 × p × (1 − p)` is at p = 0.5, so a flat 1.5 % reserve dominates
every price — stated as a constant with its derivation, not tuned.

**The `payout_cap × price` conversion is DELETED (HIGH).** Revision 2 kept a
conversion `cost_cap = payout_cap × price` computed at instrument load. §4.1 says
every ceiling is already premium USD, and that claim holds — `DATA_CAPTURE_AND_RISK_PLAN.md:298`
`[V]` states the per-order ceiling as `qty × entry_price`. A conversion from a unit
nothing produces is dead code, and dead code that multiplies by a **price sampled
once at load** is a staleness hazard: a cap derived at 0.50 admits **10×** the
contracts once the price falls to 0.05, silently, with no test failing. The
premium ceiling is therefore passed to `set_max_notional_per_order`
**unconverted** (less the fee reserve above), and E-5 carries an AST scan banning
any multiplication of a cap by a price anywhere under `exec/`.

**Caveats:** N-2 (inert until `set_max_notional_per_order`, `:279` `[V]`) and
**F-3** (a `Decimal("0")` is falsy at `:677`, so any instrument whose cap computes
to zero gets **no ceiling at all** — the H-1 class of bypass reached *through* the
remedy). E-5 guards both.

### 4.3 `PortfolioFacade.equity()` is NOT `_equity()` — DO NOT SUBSTITUTE

**unit before** = `self._config.starting_equity`, a static configured float
(`forecast_revision/strategy.py:411`, `calibration_mean_reversion/strategy.py:437`,
`forecast_mispricing/strategy.py:411` `[V]`). **unit after** = native `equity()`
(`NT/portfolio/base.pyx:67`) = balance **plus mark value of open positions**
(`DATA_CAPTURE_AND_RISK_PLAN.md` §0.3 `[E]`). **NOT equal** — native equity moves
with the mark, so an equity-fraction cap *ratchets up* as positions appreciate:
the exact defect L-2 was written about (`LESSONS.md:83-84`). **No substitution in
this plan.** Once E-4 emits `AccountState`, `equity()` returns a real number for
the first time and the substitution becomes tempting; named here so that is a
reviewed decision later, never a silent one. Barrier in E-5: a static test that no
strategy or sizing module calls `portfolio.equity(`/`net_exposure(`/`net_exposures(`.
*Preserved unanimously by all four lenses.*

### 4.4 `AccountBalance` free vs total — a unit decision on emission

The native cash guards read `account.balance_free(instrument.quote_currency)`
(`NT/risk/engine.pyx:696` `[V]`) and every one of them is gated on
`free is not None` (`:949,968,1001,1026` `[V]` — **F-5**). **Decisions, both
enforced at emission:** (a) `AccountBalance.free` is the venue's
**available/withdrawable** figure, never a total including order-locked
collateral; `locked` carries the difference — **equal because** the guard means
"cash available to spend on a new order", and emitting `total` as `free` loosens
it by the locked amount, the fail-open direction. (b) `AccountBalance.currency`
**must be identically `USD`**, the `BinaryOption` quote currency
(`parsing.py:1204` `[V]`); anything else (e.g. `USDC`) makes `balance_free`
return `None` and reproduces F-1 with a valid account cached. `[U]` the exact
field names on `GetAccountBalancesResponse` are unread (OQ-7); these are the
*rules*, pinned by contract tests in E-4 against a captured payload.

### 4.5 `order_notional_usd` — the one operator-facing dollar quantity (NEW)

Absent from revision 1's ledger, and it is the value checked against the
operator's D3 ceiling (`safety.py:680-681` `[V]`) and decremented from the permit
budget (`:712-713` `[V]`).

- **unit** = **premium at risk, USD** = `quantity × price.value` for a BUY,
  computed from the **same** `Decimal`s that are serialised into the request
  body. Not payout (`quantity × 1.00`), which differs **20×** at p=0.05 — the
  precise magnitude of the L-2 error.
- **equal because** §4.1's unit is premium at risk and §4.2 shows the native
  per-order cap is the same quantity, so D3, the permit budget and
  `max_notional_per_order` are all denominated identically and compose.
- **Enforced, not asserted:** one function
  `order_notional_usd(request: CreateOrderRequest) -> Decimal` derives it **from
  the request object that will be serialised**, and a contract test asserts the
  value passed to `consume(...)` equals the value recoverable from the transmitted
  body bytes. A separately-computed notional is exactly BL-10's hazard in the
  dollar dimension.
- **SELL:** a reducing sell releases premium rather than risking it. Its
  `order_notional_usd` is `quantity × price.value` too, because the chokepoint
  refuses `<= 0` (`safety.py:678-679` `[V]`) and a zero would be rejected — but a
  reducing sell **must not decrement the operator's opening budget**. Resolved the
  same way as cancels (BL-12): a `reduce_only` authority that verifies against
  `cache.position(...)` and does not decrement. §6.2 N-11a.

---

## 5. Module layout

```
src/breezy/adapters/polymarket_us/
    http.py  transport.py  signing.py    ← UNCHANGED, BYTE-FOR-BYTE. GET-only.
    safety.py                            ← HARDENED in E-1 (scope, ledger, fingerprint, cancel authority)
    exec/
        __init__.py        (E-0)  docstring only; its existence arms N2
        endpoints.py       (E-3)  the ONLY module holding venue order-path literals
        reports.py         (E-3)  venue JSON → Nautilus reports; pure; per-RECORD refusal
        client.py          (E-4)  the ONE LiveExecutionClient subclass
        denial.py          (E-5)  Breezy-side pre-Nautilus refusals (F-1..F-5 + venue bounds + TIF)
        settlement.py      (E-6)  settlement → synthetic closing OrderStatusReport + FillReport
        direction.py       (E-7)  the total OrderSide → (intent, outcomeSide, action, price) map
        fingerprint.py     (E-1)  the ONE request_fingerprint(method, path, body_bytes)
        signing.py         (E-8)  own key load, own method frozenset, own canonicalisation
        transport.py       (E-8)  write-capable pyo3 client; own quota bucket
        egress.py          (E-8)  the single dispatch surface; holds the capability chain
        ambiguity.py       (E-11) SUBMIT_AMBIGUOUS latch, in-flight registry, synthetic-reject interception
        config.py          (E-4)  PolymarketUSExecClientConfig
        factories.py       (E-4)  PolymarketUSLiveExecClientFactory
src/breezy/runtime/
    node_config.py                       ← E-2 adds build_trading_node_config (THIRD builder);
                                            E-4 narrows its exec_clients, E-7 its strategies
    trading_composition.py     (E-2)  the trading composition root: build node, register factories, start
    trade_cli.py               (E-2)  the `breezy-trade` entry point, mirroring quote_tape_cli.py
    settings.py                          ← E-2 adds load_trading_settings, mirroring load_quote_tape_settings
```

**The E-2 files mirror an established shape, they do not invent one.** The quote
tape is already a separate process with its own settings loader
(`settings.py:517` `[V]`), its own node-config builder (`node_config.py:381`
`[V]`), its own CLI (`quote_tape_cli.py:216-223` `[V]`) and its own entry point
(`pyproject.toml:260` `[V]`). E-2 is the third instance of that pattern, not a new
abstraction — no factory-of-factories, no shared "process framework", no
generalisation over three cases (YAGNI).

| Module | Responsibility | MUST NOT contain | Trips | Paired assertion earning the allowance |
|---|---|---|---|---|
| `exec/__init__.py` | nothing but a docstring | any import or code | **N2/E0** (new) | N2 becomes live **and blocking at collection** (BL-9); the "currently empty" pin (`test_execution_egress_firewall_guard.py:594`) inverts to an exact-set pin |
| `exec/endpoints.py` | every venue path template + method, as data; **and the `(status, body) → {terminal, retryable, AMBIGUOUS}` classification table, also as data** (N-18) | any HTTP call, `.post`, `.request`, any decision, any `except` | **B4/V2** (`_ORDER_PATH_RE` matches `/v1/orders`, `/v1/orders/open`, `/v1/order/{id}`) | V2 exemption is an **exact-path allowlist of this one file** + the path frozenset is **equality-pinned** as `(method, template)` pairs + `assert is_venue_touching(<this path>) is True`. V1/V3/V4 apply here in full. `/v1/markets/{slug}/settlement` does **not** match `_ORDER_PATH_RE` `[V]` and needs no exemption. |
| `exec/reports.py` | pure venue-JSON → report mapping, **per-record** refusal | I/O, clocks, decisions, raising out of a report coroutine | none | pure-function suite; a test that an unmappable record does **not** empty the other two report lists (BL-16) |
| `exec/client.py` | the ONE `LiveExecutionClient` subclass; lifecycle, reports, `_query_account`, `_query_order` | **any write verb** (arch §8.3 N3), any endpoint literal, any signing | **B6b** (`readonly_guard.py:550` `[V]`); **N2/E2** | B6b **narrowed**: exactly **one** subclass at this exact path, `== 1`, import nowhere else — the non-vacuity proof it never had |
| `exec/denial.py` | every Breezy-side refusal, named + counted | network, endpoints, signing | none | each refusal has a contract test that EXECUTES the path and asserts refusal **before** Nautilus is consulted |
| `exec/settlement.py` | settlement price → synthetic closing reports, **with a deterministic `(VenueOrderId, TradeId)` derived only from `(instrument_id, settlementSetTime, settlementPx)`** | network, `generate_order_filled` on a FILLED order, **any clock read, UUID, counter or cache read in the identity function** | none | RED that `Price(0.00)`/`Price(1.00)` survive; RED that the report path books non-zero PnL; **RED that emitting the same settlement three times books one fill**; AST scan that the identity function calls nothing impure |
| `exec/direction.py` | the **total** `OrderSide → (intent, outcomeSide, action, price)` map | any `1.00 - x`, any `_SHORT`, any `OUTCOME_SIDE_NO` | none | exhaustive 2-row table pinned by test; AST scan banning `_SHORT`, `OUTCOME_SIDE_NO` and any `1 - price` form anywhere under `exec/` (BL-3) |
| `exec/fingerprint.py` | the ONE `request_fingerprint(method, path, body_bytes)` | anything else | none | AST ban on any other construction of the bytes passed to the chokepoint; a test that mutating **one byte** of the body handed to the transport makes `consume` raise (BL-10) |
| `exec/signing.py` | own Ed25519 key load, own `PERMITTED_METHODS`, own canonicalisation, path-segment validation, permit provenance | any import from `polymarket_us/signing.py` | **B4/V1**; B2 **UNCHANGED** (B-0 `[E]`) | V1 exemption is an **exact-path allowlist of this one file** + equality-pinned method frozenset + a static test that `signing.PERMITTED_METHODS` is never **assigned to** anywhere in `src/`/`scripts/` (A-4 #8) + every interpolated path segment matches `^[A-Za-z0-9_-]+$` |
| `exec/transport.py` | write-capable pyo3 client, own quota bucket, refuses any `(method, path)` off the frozen allowlist; **raises the typed exceptions named by `endpoints.py`'s classification table, so `RetryManagerPool` can see them** (N-18) | decisions, sizing, gates, **any retry or backoff of its own** | **B4/V3** (`.post`) | V3 exemption is an **exact-path allowlist of this one file** + dispatch takes the authorization **positionally** and **consumes** it before any I/O + the allowlist is equality-pinned + read-path `PERMITTED_QUOTA_KEYS` (`transport.py:98-106`) gains **no** order bucket, equality-pinned |
| `exec/egress.py` | the single dispatch surface: request construction, chokepoint call, capability threading, response parsing. **< 200 lines** (arch §8.8) | decision logic, sizing, edge, gates, retry loops, **any `isinstance` test on an authority object** | **B6a** (`readonly_guard.py:570` `[V]`) | B6a **narrowed**: **exactly one** caller of each of the **four** chokepoints, at pinned paths, `== 1` never `<= 1` (A-4 #5); each dispatch entry point checks `type(auth) is <its own type>` (R2-BL-4) |
| `exec/ambiguity.py` | latch, in-flight registry, synthetic-reject interception, **two-directional** fail-closed halt reads, **write-ahead commit of the in-flight mark** | network, any halt state that blocks cancellation | none | fail-closed test: an unreadable latch store resolves to `HALT_NEW_EXPOSURE` **and a cancel still dispatches**; a test that the in-flight mark is durable **before** the request is handed to the transport |
| `exec/config.py`, `exec/factories.py` | config, every field required-no-default; factory mirroring `factories.py:320-437` | any default for an operator gate | **N7** (arch §8.3) | static scan: no `getenv` default, no `or`-fallback, no `try/except` producing a truthy value for `BREEZY_TRADING_ENABLED` |

**The node_config narrowing is strictly stronger, not weaker — stated in full,
because it is the one barrier this plan relaxes at a real site.** Today the rule
is *"at every `TradingNodeConfig(...)` call site, `exec_clients`, `strategies` and
`exec_algorithms` are empty literals"*, plus *"there are exactly 2 sites"*
(`test_runtime_node_config.py:338-349` `[V]`). It is replaced, in the same commit
as each narrowing, by a rule keyed on the **enclosing function name**:

| Site | `data_clients` | `exec_clients` | `strategies` | `exec_algorithms` |
|---|---|---|---|---|
| `build_node_config` (ingest) | `{}` | `{}` | `[]` | `[]` |
| `build_quote_tape_node_config` | exactly `{POLYMARKET_US_CLIENT_NAME: …}` | `{}` | `[]` | `[]` |
| `build_trading_node_config` (E-2) | exactly `{POLYMARKET_US_CLIENT_NAME: …}` | `{}` → one key at **E-4** | `[]` → one entry at **E-7** | `[]` **permanently** |

Five assertions make this stronger than what it replaces, and each must land in
the same commit as the change it covers: (1) **every** call site's enclosing
function is in the table — an unknown site is a **failure**, not an unchecked
pass, which the current rule cannot express; (2) each field is pinned to its
**exact** expected value, not merely to emptiness, so the ingest and quote-tape
sites become *harder* to change than they are today; (3) `exec_algorithms == []`
is asserted at all three sites unconditionally; (4) a test that the ingest and
quote-tape builders are **byte-unchanged** by E-2, E-4 and E-7; (5) an import-side
test that neither `ingest_runtime` (`composition.py:310` `[V]`) nor
`quote_tape_cli` (`:223` `[V]`) can reach `build_trading_node_config`, so the two
read-only processes cannot acquire an order path by a call-graph change alone. The
count pin moves `== 2 → == 3` and stays an equality (A-4 #5).

**Prefix rules vs allowlists.** The E0 rule *is* a directory prefix (`any file
under exec/`) and that is correct: a prefix that **classifies hazard** fails
CLOSED as the directory grows. Every *exemption* is an **exact path**, never a
prefix, because a prefix that **grants an allowance** fails OPEN as the directory
grows (A-4 #1).

---

## 6. Cage and authority contract

### 6.1 The invariant

**No barrier is deleted. Each barrier that must change is a narrowed
re-expression shipped with a strictly stronger assertion in the SAME commit.** A
commit landing a narrowing without its pair is reverted, not amended.

### 6.2 Barrier disposition

| Barrier | Today | Becomes | Same-commit pair |
|---|---|---|---|
| **B1** `http.py:64` GET-only | data path | **UNCHANGED** | equality pin |
| **B2** `signing.py:84` GET-only | data path | **UNCHANGED** (B-0 `[E]`) | equality pin + no-rebinding scan |
| **B3** GET-only closure `transport.py:129-148,325` | data path | **UNCHANGED**; `exec/transport.py` gets its own | the receiver-graph test (`readonly_guard.py:456-490`) applied to the new closure |
| **B4/V1** write-method literal | all venue-touching | **NARROWED** → exact path `exec/signing.py` | equality-pinned method frozenset; `_WRITE_METHODS` pinned |
| **B4/V2** order-path literal | all venue-touching | **NARROWED** → exact path `exec/endpoints.py` | equality-pinned `(method, template)` frozenset; `_ORDER_PATH_RE` pinned |
| **B4/V3** write attribute | all venue-touching | **NARROWED** → exact path `exec/transport.py` | `.request` banned **everywhere, including the allowlisted files**; `_WRITE_ATTRS` pinned |
| **B4/V4** `getattr` bypass | all venue-touching | **UNCHANGED everywhere** | — |
| **B5** SDK signing import ban | repo-wide | **UNCHANGED** | `SDK_IMPORT_ORACLE` pinned |
| **B6a** chokepoint has **zero** callers | `src`,`scripts` | **exactly ONE per chokepoint**, all in `exec/egress.py` | `== 1` for each of the **four** (submit / cancel / reduce-only / preview); capability-must-be-consumed test; **`type(auth) is X` at each dispatch entry point and an AST ban on `isinstance` against any authority type** (R2-BL-4) |
| **new — permit issuer** | `issue_live_trading_permit` has **no** caller barrier and is in the package `__all__` (`__init__.py:107,191` `[V]`) | **`== 0` callers at E-1** with the one-entry allowlist declared and empty, **flipping to `== 1` at E-4** when `exec/factories.py` first exists | E-1: `== 0` plus a proof that a planted caller fails; E-4: `== 1` plus a proof that `== 0` and `== 2` both fail. Never `<= 1` (A-4 #5) |
| **new — endpoint scope matching** | no scope exists | scope entries are **exact `(method, template)` pairs**, compared by set membership on the pair | AST ban on `startswith`, `in <str>`, `re.match` and `fnmatch` anywhere in the scope comparison; a RED that a permit scoped to `POST /v1/orders/open/cancel` refuses `POST /v1/orders` **and** `POST /v1/order/{id}/cancel` |
| **B6b** no execution client | adapter pkg | **exactly ONE** subclass at `exec/client.py` | `== 1`; import-site scan |
| **N1** pyo3 clients blocked in tests | CI | **UNCHANGED** | — |
| **N2** firewall-before-egress | CI | **EXTENDED**: E0 path rule, underscore verbs, **and moved into `pytest_configure` to abort collection** (BL-9) | the "currently empty" pin inverts to an exact-set pin; a proof that a planted exec file aborts the session rather than reddening one test |
| **node_config** four empty literals at two sites, and the barrier quantifies over **every** site (N-20) | `node_config.py:203,204,212,218` (ingest) / `:459,460,463,464` (quote tape) `[V]`; `test_runtime_node_config.py:289-305, 338-349` `[V]` | **Re-expressed PER SITE, in three paired steps.** E-2 adds a third site (`build_trading_node_config`) and moves the count pin `== 2 → == 3`. E-4 narrows **that site's** `exec_clients` `{}` → exactly one key. E-7 narrows **that site's** `strategies` `[]` → exactly one entry. The ingest site keeps all four literals empty and the quote-tape site keeps its three empty with its one data client, **forever**; `exec_algorithms` stays `[]` at **all three** sites permanently. | See below — the strictly-stronger pair |
| **N6 / F2** `SandboxExecutionClient` | — | **banned** by import and construction (arch §9.1) | static scan + non-vacuity proof |
| **N7** D4 has no default | — | **UNCHANGED, extended** to the new operator env vars of E-1 | AST scan |
| **N8** post-only refusal at the execution boundary | — | **WIDENED** to any time-in-force that can rest (non-IOC/FOK) | see E-5 |
| **N9** dry-run routes to a stub egress | arch §8.3 | **RETIRED BY NAME.** Superseded by structure: E-3..E-7 have no write-capable module in the tree at all, which is strictly stronger than routing to a stub. Re-examine if a dry-run mode is ever added after E-8. | the E-8 allowlist equality pin |
| **N10** egress refuses to construct without circuit-breaker thresholds | arch §8.3 | **RETAINED, and moved earlier**: `exec/egress.py` refuses to construct when drawdown / rejection-count thresholds are absent, same treatment as N7 | construction-raises test |
| **new** `AccountType.BETTING` / `accounts/betting` | — | **banned by name** | `AUDIT:148-149`: a different model, not a drop-in |

### 6.3 The permit is now a scoped, session-budgeted, single-issuer credential

Four defects, all `[V]`, all closed in **E-1**. Payload version `v2 → v3`
(`safety.py:278` `[V]`), which invalidates every outstanding permit — the correct
direction.

| # | Defect | Cite | Fix |
|---|---|---|---|
| **BL-7** | Renewal resets the budget: `:547-551` re-reads ceilings from env, `:574-578` installs a **fresh** `_Budget` under a fresh `permit_id`, `_PERMIT_BUDGETS` (`:332`) aggregates nothing, and `PERMIT_TTL_NS` is 15 min (`:157`) so renewal is **forced** — ≈32× the operator's ceiling on an 8-hour day | `safety.py` `[V]` | a process-level **session ledger** keyed by `operator_id`, created on first issuance and **never reset**; renewal binds to the existing ledger and carries the REMAINING budget forward. Durable form is a **hard prerequisite of E-12** (§6.4). |
| **BL-8** | No endpoint scope: the chokepoint takes credentials, permit, indicator, notional, fingerprint, `now_ns` — **no method, no path** (`:626-634`). The only endpoint constraint is a frozenset inside `exec/transport.py`, so cancel-only → order-sending is one edit **with zero additional operator act**, and from E-9 the full D3/D4/D5 environment is already set | `safety.py:626-634` `[V]` | the permit carries an **operator-set endpoint allowlist**, hashed into `_permit_payload`; the chokepoint takes `method` and `path` and refuses off-scope. New env var, no default, N7 treatment. **The plan's "exposure-opening first reachable at E-12" becomes true of the authority, not only of the code.** |
| **BL-10** | `request_fingerprint` is "opaque bytes … computed by the caller over whatever uniquely determines it" (`:644-646`); `consume` re-checks caller-supplied input against a caller-supplied digest. A fingerprint over a constant yields one capability authorising **any** body at the minted notional | `safety.py:644-646` `[V]` | one named `exec/fingerprint.py::request_fingerprint(method, path, body_bytes)`; AST ban on any other construction; a RED that **mutating one byte of the body handed to the transport** makes `consume` raise |
| **BL-12** | Cancel has no notional: `:678-679` refuses `<= 0`, `:712-713` decrements both budget dimensions at mint. So cancels either skip the chokepoint (voiding the guarantee) or **burn the operator's budget** — and with `RetryManagerPool` on that path a retry storm exhausts the permit, blocking submit **and the kill switch** together | `safety.py:678-679, 712-713` `[V]` | **four** chokepoints, not one — see §6.3.1, which is the corrected form after R2-BL-4. B6a becomes `== 1` for each. |
| **R2-BL-4** | **The revision-2 fix opened a submit bypass.** Splitting the chokepoint gave cancellation a **non-decrementing** authority whose only endpoint constraint was the permit's scope — and from E-12 that scope necessarily contains `POST /v1/orders`. So `assert_live_order_cancellation_permitted(method="POST", path="/v1/orders", request_fingerprint=<over a real CreateOrderRequest>)` passes scope, mints a capability indistinguishable from a submission's, and the transport POSTs a live order: **D3 and D5 bypassed, nothing decremented, invisible to both operator controls, repeatable without limit.** | this plan, rev 2 §6.3 | §6.3.1: four **distinct frozen types**, `type(auth) is X` at four distinct transport entry points, a **cancel-class endpoint frozenset** that permit scope is necessary but never sufficient for, and a session ceiling on reduce-only. |

**Plus N-11a, found while fixing BL-12:** `issue_live_trading_permit` has **no
caller barrier at all** and is re-exported in the package `__all__`
(`adapters/polymarket_us/__init__.py:107,191` `[V]`). Any module may mint a permit
from the operator's environment. E-1 gives it the B6a treatment — exactly one
caller, at a pinned path in `exec/factories.py` — and removes it from `__all__`.

#### 6.3.1 Four authority types, and why one type could not work

The defect R2-BL-4 found is not that the split was wrong — it is that **one type
with four meanings is one key with four locks removed**. A capability is a
bearer token; if the *only* thing distinguishing "may cancel" from "may submit" is
a field the minting call sets, then any caller that can reach the cheaper mint
function has the expensive authority.

| Type (frozen, distinct class) | Minted by | Decrements | Endpoint constraint | Extra invariant |
|---|---|---|---|---|
| `SubmitAuthorization` | `assert_live_order_submission_permitted` | **budget and order count** | permit scope **and** `(method, template)` ∈ `SUBMIT_ENDPOINTS` (exactly `POST /v1/orders`) | the fingerprint covers the exact body bytes (BL-10) |
| `CancelAuthorization` | `assert_live_order_cancellation_permitted` | never | permit scope **and** `(method, template)` ∈ `CANCEL_ENDPOINTS` (exactly `POST /v1/orders/open/cancel`, `POST /v1/order/{id}/cancel`) | zero-notional; **always permitted under `HALT_NEW_EXPOSURE`** (§6.4) |
| `ReduceOnlyAuthorization` | `assert_reduce_only_submission_permitted` | order count only, **not budget** (§4.5) | permit scope **and** `(method, template)` ∈ `SUBMIT_ENDPOINTS` | verifies a covering `cache.position(...)`; **session ceiling** on reduce-only mints, so "non-decrementing" never means "unlimited" |
| `PreviewAuthorization` | `assert_preview_permitted` | never | permit scope **and** `(method, template)` ∈ `PREVIEW_ENDPOINTS` (exactly `POST /v1/order/preview`) | refuses unless OQ-2 is CLOSED-POSITIVE; **HIGH — this is the concrete instance R2-BL-4 named**: preview had no authority assigned at all in revision 2, so it would have been dispatched under whichever type was nearest |

Five structural rules, all landing at **E-1**, all blocking for **E-8**:

1. Each type is a distinct `@dataclass(frozen=True)` with its own payload
   discriminator hashed into the HMAC tag; a tag minted for one type never
   verifies as another.
2. `exec/transport.py` exposes **four** dispatch entry points, each taking its own
   type **positionally** and checking `type(auth) is <that type>` — never
   `isinstance`, which a subclass defeats. AST scan bans `isinstance` against any
   authority type anywhere under `exec/`.
3. The four endpoint frozensets are **disjoint** and equality-pinned, and their
   union equals the transport allowlist — asserted, so an endpoint can never be
   dispatchable under no class or under two.
4. **Permit scope is necessary, never sufficient.** Both checks run: the
   operator's scope AND the class frozenset. A permit scoped to everything still
   cannot submit through a `CancelAuthorization`.
5. The submit path additionally refuses any authority whose class frozenset is not
   `SUBMIT_ENDPOINTS`, so the refusal exists at **mint** and again at **dispatch**.

**REDs (E-1).** (i) A cancellation authority minted for `POST /v1/orders` is
refused **at mint**. (ii) A cancellation authority that somehow exists for
`POST /v1/orders` is refused **at dispatch** by the submit path. (iii) A subclass
of `CancelAuthorization` is refused by the `type(...) is` check. (iv) A
reduce-only authority beyond the session ceiling is refused. (v) A preview
authority dispatched at `POST /v1/orders` is refused twice.

### 6.4 The operator's two reserved controls, made enforceable

The operator reserves budget and position ceilings and nothing else. Both were
defeasible in revision 1.

- **Budget:** BL-7's session ledger. In E-1 it is process-local, which closes the
  32× hole but not a restart. **Before E-12** the ledger must be durable, sharing
  the fail-closed store of `exec/ambiguity.py`, so a crash-restart cannot
  resurrect spent budget. Stated as a prerequisite, not a follow-up.
- **Fail-closed is two-directional (HIGH).** Revision 2 said an unreadable latch
  store resolves to `HALT_ALL_DISPATCH`. That contradicts "read / status / cancel
  always permitted" and, worse, **disarms the only control that can reduce
  exposure** on a venue with no stop-out: a storage fault would leave a live
  position with cancellation blocked. Corrected: an unreadable or inconsistent
  halt/latch store resolves to **`HALT_NEW_EXPOSURE`** — submit, reduce-only and
  preview refuse; **cancel still dispatches**. There is no state in this system in
  which cancellation is denied. The RED asserts both halves in one test: new
  exposure refused **and** a cancel dispatched.
- **Position:** `max_position_contracts` remains a venue/liquidity bound
  (`DATA_CAPTURE_AND_RISK_PLAN.md:299`), and the operator-facing ceiling is
  premium at risk (§4.1) enforced by D3/D5 plus the runtime-populated
  `max_notional_per_order` (§4.2) with F-3's zero-guard.

### 6.5 A-4's eight silent-failure modes, each with its counter

| # | Failure mode | Counter | Lands |
|---|---|---|---|
| 1 | Directory-prefix allowlist → blanket exemption | every exemption is an exact path (§5); each allowlist entry must resolve to an existing file and the frozenset is equality-pinned | E-1 |
| 2 | Escaping the classifier — egress outside the package, base URL from env | `assert is_venue_touching(p) is True` for **every** path in §5's layout, including paths that do not yet exist | E-1 |
| 3 | Loosening the global rule instead of allowlisting the file (a one-token diff at `readonly_guard.py:112-114` disarms 19 modules) | equality pins on `_WRITE_METHODS`, `_WRITE_ATTRS`, `_ORDER_PATH_RE`, `EGRESS_SCAN_ROOTS`, `SDK_IMPORT_ORACLE`, `_EGRESS_MODULE_BASENAMES`, `_EGRESS_CLASS_SUFFIXES`, `_EGRESS_CLASS_BASES`, `_EGRESS_FUNCTION_NAMES` | E-1 |
| 4 | N2 blind to planned filenames / underscore overrides (A-1) | **E-0**, increment #1 — and BL-9's abort-at-collection | E-0 |
| 5 | B6a inverted to "at most one" → zero passes, chokepoint becomes dead code | `== 1` per chokepoint + a proof that zero fails | E-8 |
| 6 | Capability accepted but never consumed | a dispatch path that skips `consume(...)` fails a static test; a second dispatch with the same capability raises | E-8 |
| 7 | An exec test marked `allow_socket`/`live`/`venue_live`/`real_money` restores the real pyo3 clients (`tests/conftest.py:336-342, 397-404` `[E]`) | static ban on those four markers in any test importing `…polymarket_us.exec` | E-1 |
| 8 | Data-path widening by rebinding `signing.PERMITTED_METHODS` | repo-wide AST ban on assignment to `PERMITTED_METHODS` / `PERMITTED_QUOTA_KEYS` / `_WRITE_*` on any imported module object | E-1 |

Plus **A-2** (`safety.py:463` `[V]` — `consume()` compares notionals with `!=`
and does not type-check, so a `Decimal` subclass overriding `__ne__` satisfies the
re-check at any magnitude): fix mirrors `:676`'s `type(x) is not Decimal`. E-1,
with a RED using a lying subclass.

### 6.6 The five cage layers (A-0) — all five in scope

1. `tests/unit/test_polymarket_us_readonly_guard.py` — B3, B4, B5, B6a, B6b, S16
2. production code — B1 (`http.py:64`), B2 (`signing.py:84`) and their suites
3. `tests/unit/test_execution_egress_firewall_guard.py` — N1-N5, **plus `tests/conftest.py`** (BL-9 moves enforcement there)
4. `tests/unit/test_runtime_node_config.py:333-349` — today the empty-literal pin at **both** sites over **three** fields; from E-2 the **per-site value table** of §6.2 over **three sites** and **four** fields, `data_clients` included (C-1)
5. `tests/unit/test_polymarket_us_permit_issuance.py` — permit-constructor allowlist (`:756-781` `[V]`) and the blanket environment-write ban (`:1324-1387` `[V]`)

---

## 7. Ordered increments

Every increment carries a **[NO-SEND]** / **[SEND]** marker.

| E-0 | E-1 | **E-2** | E-3 | E-4 | E-5 | E-6 | E-7 | **E-8** | E-9 | E-10 | E-11 | **E-12** | E-13 | E-14 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| none | none | GET + WS | GET | GET | GET | GET | GET | **+scoped `POST /v1/orders/open/cancel`** | = | +`POST /v1/order/preview` | = | **+`POST /v1/orders`** | +`POST /v1/order/{id}/cancel` | = |

> **Live order capability first becomes reachable at E-8** — a market-scoped
> cancel-all that cannot open exposure. **Exposure-opening capability first
> becomes reachable at E-12**, and after BL-8's fix that is true of the
> **authority** as well as the code: reaching `POST /v1/orders` requires the
> operator to add it to the permit's endpoint allowlist, which no agent can do
> (N7 treatment). Between E-8 and E-12 no commit widens the allowlist by more
> than one entry. `POST /v1/order/{id}/modify`, `POST /v1/order/close-position`
> and the institutional `insert-order` surface are **never** added.

---

### E-0 — Arm the egress firewall for `exec/`, and make it ABORT · **[NO-SEND]** · MUST BE FIRST

**Why first (A-1 `[E, CRITICAL]`).** `_EGRESS_MODULE_BASENAMES`
(`test_execution_egress_firewall_guard.py:161-171` `[V]`) contains none of the
planned filenames and `_EGRESS_FUNCTION_NAMES` (`:178-180` `[V]`) no underscore
form, while the overrides a real client implements are `_submit_order`,
`_cancel_order`, … (`NT/live/execution_client.py:598-633` `[V]`). Today N2 fires
only through E2. A write-capable `exec/transport.py` landing before
`exec/client.py` means `find_execution_egress_modules()` returns empty and an
ordinary `uv run pytest -q` can transmit a signed live order with every gate
green. No retail sandbox exists; every POST is real money
(`TRADING_ENABLEMENT_FINDINGS.md:251` `[E]`).

**BL-9 — and reporting is not stopping.** `find_execution_egress_modules` appears
**only inside its own test module** `[V]`; `conftest.py` never consults it and
there is no `UsageError` or `shouldstop`. A failing assertion reddens **one test**
while pytest runs everything else *in the same process* — so a suite containing a
write-capable transport would **transmit first and print red afterward**. The
mechanism already exists: `conftest.py:227` defines `pytest_configure` and `:268`
already calls `pytest.exit` `[V]`.

**Goal.** (a) Rule **E0**: any file under
`src/breezy/adapters/polymarket_us/exec/` is an execution-egress surface.
(b) Underscore forms added to `_EGRESS_FUNCTION_NAMES`.
(c) **The N2 rule moves into `pytest_configure` and aborts before collection**
when egress modules exist without an attested-and-substantiated firewall; the
test-module assertion remains as its non-vacuity proof.
(d) `exec/__init__.py` (docstring only) in the **same commit**.

**RED first.** (i) An in-memory `exec/transport.py` with no class, no known
basename and no bare order verb yields a rule-`E0` violation. (ii) A
venue-touching module defining `async def _submit_order` is detected as `E3`.
(iii) **A planted exec file with no attestation aborts the session at
configure time** — asserted by running a child pytest process and checking it
never reaches collection, not by asserting a single test failed.

**Files.** `tests/unit/test_execution_egress_firewall_guard.py`;
`tests/conftest.py`; `src/breezy/adapters/polymarket_us/exec/__init__.py`.

**Barriers.** Layers 3 and (new) conftest. Pure extension; nothing loosened. The
"currently empty" pin (`:594`) inverts to an exact-set pin naming
`exec/__init__.py`, so N2 can never go vacuous again.

**Completion.** All three REDs GREEN; the full suite requires
`scripts/ci/run_tests_no_egress.sh` (`:139` `[V]`) and a bare `uv run pytest -q`
**aborts at configure**, not after running. The N4 classifier is untouched:
`Connection refused` still classifies as REACHED (`:331-334` `[V]`).

---

### E-1 — Cage strengthening and permit hardening · **[NO-SEND]**

**Goal.** Land §6.5's eight counters, A-2, and all four permit defects of §6.3
plus N-11a, while the tree has no exec module beyond `__init__.py` and
`fingerprint.py`. Strengthening before narrowing means every later narrowing is
measured against a pinned baseline. **This increment is where the operator's
budget control becomes real** — everything after it inherits an authority that
cannot be reset, cannot be self-issued, and cannot be pointed at an endpoint the
operator did not name.

**RED first — one per defect, each failing on today's tree.**
(1) A `Decimal` subclass overriding `__ne__ → False` passes `consume(...)` at
arbitrary magnitude (A-2, `:463`). (2) Issuing a second permit restores the full
session budget after the first is spent (BL-7) — the ≈32×/day hole.
(3) A permit issued for cancel-only authorises a submit path (BL-8).
(4) A fingerprint computed over a constant lets one capability dispatch a
**different body** at the same notional (BL-10); the RED mutates one byte of the
bytes handed to the transport. (5) A cancel either bypasses the chokepoint or
decrements the operator's order-count budget (BL-12). (6) A module outside the
issuer mints a permit from the operator's environment (N-11a). (6b) The five REDs
of §6.3.1 — a cancellation authority for `POST /v1/orders` refused **at mint** and
again **at dispatch**, a subclass defeating a `type(...) is` check, a reduce-only
mint beyond the session ceiling, and preview dispatched off its own class set
(R2-BL-4). (6c) A permit scoped to `POST /v1/orders/open/cancel` authorises
`POST /v1/orders` because the comparison is a prefix — the nesting is real
(`/v1/orders` prefixes `/v1/orders/open/cancel`; `/v1/order/` prefixes both
preview and `{id}/cancel`), so this RED is written against the venue's actual
paths, not a synthetic pair. (7) Widening
`_WRITE_METHODS` by one token leaves the suite green (A-4 #3). (8) A planted
`src/breezy/egress_outside_the_package.py` reading its base URL from `os.environ`
is **not** venue-touching (A-4 #2). (9) A test importing `…exec` marked
`@pytest.mark.allow_socket` is undetected (A-4 #7). (10) Rebinding
`signing.PERMITTED_METHODS` from another module is unbanned (A-4 #8).

**The issuer barrier is `== 0` here, not `== 1` (HIGH).** Revision 2 gave
`issue_live_trading_permit` "the B6a treatment — exactly one caller, at a pinned
path in `exec/factories.py`". That file does not exist until E-4, so `== 1` is
**unsatisfiable at E-1** and the pressure would be to write `<= 1`, which A-4 #5
forbids for exactly this reason: `<= 1` is satisfied by zero, so the barrier
passes while dead. Corrected: E-1 asserts **`== 0` callers** with the one-entry
path allowlist **declared and empty**, plus a proof that a planted caller fails.
E-4 flips it to **`== 1`** in the same commit that creates `exec/factories.py`,
with a proof that both `== 0` and `== 2` fail there. Two equalities, never an
inequality, and each is satisfiable at the moment it lands.

**Files.** `safety.py`; new `exec/fingerprint.py`;
`adapters/polymarket_us/__init__.py` (remove `issue_live_trading_permit` from
`__all__`); the three guard suites; new
`tests/unit/test_cage_rule_constants_are_pinned.py`.

**Barriers.** Layers 1, 2, 3, 5. Every change strictly stronger; **no allowlist
is created yet**. `SandboxExecutionClient`, `AccountType.BETTING` and
`accounting/accounts/betting` banned by name with non-vacuity proofs. Arch N9 is
retired by name and N10 is retained (§6.2).

**Completion.** **G5** met for authority. All REDs GREEN. Permit payload is `v3`;
every outstanding `v2` permit is refused. Four distinct authority types exist,
none of which can reach another's endpoints (§6.3.1).

---

### E-2 — The trading process: the container everything else runs inside · **[NO-SEND — GET + WS only]**

> **R2-BL-1, the third recurrence of L-3.** `grep -rn "TradingNode(" src/` returns
> **zero hits** `[V]`. `build_node_config` (`:163`) is the **ingestion** process by
> its own docstring (`:164`) and pins `data_clients={}` (`:203`);
> `build_quote_tape_node_config` (`:381`) is the tape and pins `exec_clients={}`
> (`:460`). Registering a strategy or an execution client into either one puts it
> in a process that either has no venue data or is contractually not a trader.
> **Revision 2's walk ended with an execution client, a strategy, and no process.**

**Null hypothesis: NATIVE — sufficient for the runtime, absent for the
configuration.** `TradingNode` (`NT/live/node.py`), the kernel lifecycle
(`NT/system/kernel.py`) and both factory registration paths
(`NT/live/factories.py`) are complete and are **not** extended here. What is
absent is a Breezy `TradingNodeConfig` that names a venue data client, a strategy
and an execution client together, a composition root that builds and starts it,
and an entry point that reaches it. **GENUINELY ABSENT: configuration and
composition only** — no runtime, no framework, no abstraction over the three
processes (§3.3 item 9).

**Goal.** A third process, mirroring the quote tape's established shape exactly:

- `node_config.build_trading_node_config(settings, data_client_config)` — the
  **third** `TradingNodeConfig(...)` call site. At this increment:
  `data_clients={POLYMARKET_US_CLIENT_NAME: data_client_config}`,
  **`exec_clients={}`**, **`strategies=[]`**, **`exec_algorithms=[]`**, all four
  declared as explicit literals so the cage rule of §6.2 can read them from
  source. `catalogs=[]` and `actors=[]` for the same reasons `build_node_config`
  gives (`:164-192` `[V]`); **no `StreamingConfig`** — the tape records, the
  trader trades.
- `runtime/trading_composition.py::trading_runtime(...)` — builds the node,
  registers the Polymarket data client factory, starts, and owns shutdown.
  Mirrors `composition.py:272-310` `[V]` without reusing it: `ingest_runtime`
  builds the weather-ingest node and its Actors, which this process must not have.
- `runtime/trade_cli.py::main` + `breezy-trade` in `[project.scripts]`. A
  **separate** process from `breezy` and `breezy-quote-tape` for the reason
  `pyproject.toml:257-259` `[V]` already states about the other two: the weather
  collector must start on a host with no venue configuration, and this one must
  refuse to start without it.
- `settings.load_trading_settings(env)` mirroring `load_quote_tape_settings`
  (`settings.py:517` `[V]`), with **no defaults** for any operator gate (N7).
- **`CacheConfig(database=DatabaseConfig(type="redis"), flush_on_start=False)`**
  is set here, not at E-4 — the durable cache is a property of the process, and
  E-4's G6 test needs a process to restart. `DatabaseConfig.type` accepts
  `{'redis'}` only (N-13 `[V]`). If Redis is unreachable the process **refuses to
  start** (fail-closed, N10 treatment).

**Why this is before E-4 and not before E-7.** The review's fix permitted an
increment "before E-7". Four artifacts need this container — the exec client, the
report mappers, the denial layer and the settlement exit — and each of them is
built before E-7. Placing the container after them would leave four components
proven in harnesses and unproven in composition, which is the same defect one
layer shallower. §1.0 is the check that produced this ordering.

**RED first — and every one of them drives the node the entry point builds.**
(i) `len(_node_config_calls()) == 3` fails on today's tree, and the **per-site**
value table of §6.2 fails for the new site until it is declared. (ii) The composed
node **starts and stops cleanly** against a stubbed venue transport, with the
Polymarket data client registered and `node.trader` present. (iii) A `QuoteTick`
for a weather instrument, injected at the data client's boundary, is observable in
the node's `Cache` — **the G0 oracle at the data half**; the strategy half lands
at E-7 with `on_quote_tick`. (iv) `trade_cli.main` with the venue environment
absent **exits non-zero without constructing a node** — the mirror of the quote
tape's refusal. (v) `ingest_runtime` and `quote_tape_cli` do **not** reach
`build_trading_node_config`, asserted on the import graph (§6.2 pair 5).
(vi) With Redis unreachable the process refuses to start and does **not** fall
back to `database=None`.

**Files.** `src/breezy/runtime/node_config.py` (add the third builder);
`src/breezy/runtime/trading_composition.py`; `src/breezy/runtime/trade_cli.py`;
`src/breezy/runtime/settings.py`; `pyproject.toml`;
`tests/unit/test_runtime_node_config.py`; new
`tests/contract/test_trading_node_composition_contract.py`.

**Barriers.** Layer 4 only, and it is the narrowing §6.2 specifies in full: the
count pin moves `== 2 → == 3` **in the same commit** as the five strictly-stronger
assertions, of which four constrain the two existing sites *more* tightly than
today's rule does. **No exec client, no strategy, no write verb, no endpoint
literal, no signing change** — this increment adds a process, not a capability.
The process it adds can do exactly what the quote-tape recorder can do, minus
recording.

**Completion.** **G0** met at the data half: a Breezy `TradingNode` exists, starts
from its own entry point, and receives venue quotes. Every increment from here
names this node as the thing it changes.

---

### E-3 — `exec/endpoints.py` + `exec/reports.py` on the EXISTING GET stack · **[NO-SEND]**

**Null hypothesis: NATIVE — insufficient.** Nautilus defines the three report
types and gathers them in `generate_mass_status`
(`NT/live/execution_client.py:499-503` `[V]`), which the engine calls at startup
(`NT/live/execution_engine.py:1709-1712` `[E]`). It supplies no mapping from this
venue's JSON. **GENUINELY ABSENT: the mapping only.**

**Goal.** A frozen endpoint table, a frozen **response-classification** table, and
pure report mappers. All sources are `GET` (N-1), so this reuses
`PolymarketUSHttpClient` **byte-identical** and adds **no** write capability. It
runs inside **E-2's node** — the report coroutines have a caller from E-4 onward.

| Nautilus surface | Venue call `[V]` |
|---|---|
| `generate_account_state` | `GET /v1/account/balances` (`resources/account.py:15`) |
| `generate_position_status_reports` | `GET /v1/portfolio/positions` (`resources/portfolio.py:19`) |
| `generate_order_status_reports` | `GET /v1/orders/open` (`resources/orders.py:34`) |
| `generate_order_status_report` | `GET /v1/order/{order_id}` (`resources/orders.py:42`) |
| `generate_fill_reports` | `GET /v1/portfolio/activities` (`resources/portfolio.py:24`) — `[U]` OQ-8 |
| **settlement price — PRIMARY (E-6)** | **`GET /v1/markets/{slug}` market book** — `stats.settlementPx`, gated on `settlementPriceCalculationMethod == …EVENT_TIER_1`, `settlementSetTime` present and `closePx` **absent**. Already in use by the data path; 2/2 on the resolved weather captures (N-15 `[V]`) |
| settlement price — SECONDARY (E-6) | `GET /v1/markets/{slug}/settlement` (`resources/markets.py:37-39`) — **0/5 in this repo's captures, every one a 404** (N-15 `[V]`). Mapped, and its **404 is the expected response**, never an error |

**BL-16 — refuse per RECORD, never per call.** `generate_mass_status` gathers the
three plural coroutines in a **bare `asyncio.gather` inside one `try`** with no
`return_exceptions=True`, and returns `None` on any exception
(`NT/live/execution_client.py:500-515` `[V]`). Revision 1's "the fill mapper
raises a named error rather than guessing" would therefore discard **order-status
and position reports too**; the kernel then logs "Execution state could not be
reconciled" and **does not start the trader**. After E-12 that means: crash
holding a position → restart → no reconciliation → no trader → no settlement
exit, no cancel, position abandoned, on one ERROR line. **Corrected:** every
mapper returns the records it can map, and emits a counted, alerted
`UnmappableRecordError` **per record**; no report coroutine ever raises.

**The retry-classification table, as data (HIGH, N-18).** `RetryManager.run`
retries **only** exceptions listed in `exc_types` (`NT/live/retry.py:101,172`
`[V]`), and Breezy's transport raises only on pyo3 transport failure
(`transport.py:328-340` `[V]`) — so a venue `429` or `503` is an ordinary response
object and `RetryManagerPool`, as revision 2 wired it, **never fires on the venue's
own rate-limit responses**. It was wired and dead. E-3 therefore ships a frozen
`(status, error_code) → {TERMINAL, RETRYABLE, AMBIGUOUS}` table in
`exec/endpoints.py` as **data**, with a named typed exception per RETRYABLE class;
`exec/transport.py` (E-8) raises those types and hands them to `RetryManagerPool`
as `exc_types`. The table is equality-pinned and **total**: an unlisted
`(status, error_code)` classifies as **AMBIGUOUS**, not as terminal — the
fail-closed direction, because a wrongly-terminal submit is exactly B-1's double
position. This table is also **the sole input to E-11's latch**, which is why it
lands here rather than beside the transport that consumes it.

**RED first.** (i) Mappers round-trip captured payloads. (ii) An unmappable fill
record leaves the order-status and position lists **intact** and increments a
counter. (ii-b) The classification table is total — a `(599, "")` pair classifies
AMBIGUOUS — and a `429` classifies RETRYABLE with a typed exception the pool's
`exc_types` accepts. (ii-c) `GET /v1/markets/{slug}/settlement` returning
`{"code":5,"message":"Settlement not found …"}` maps to **absent**, is **not**
counted as an error, and does not increment any failure counter (N-15). (iii) The unobserved decodings — fills, and the fixed-point
`price_scale` / `fractional_quantity_scale` (B-2 #6 `[E]`) — refuse **by record,
by name**, never guess. A guessed decode reading a price 100× wrong is worse than
a refusal; discarding two report types to express that refusal is worse still.

**Barriers.** Layer 1 — **B4/V2 narrowing, the first allowance in this plan**,
with §5's pairing. V1/V3/V4 apply in full: **no write-method literal and no
`.post` anywhere in this increment.** `/v1/markets/{slug}/settlement` does not
match `_ORDER_PATH_RE` `[V]` and requires no exemption. Layer 3: the N2 exact-set
pin grows by two.

**Completion.** `scan_write_egress()` reports zero violations outside the one
V2-allowlisted path.

---

### E-4 — `exec/client.py`: the client that refuses everything, and can be restarted · **[NO-SEND]**

**Null hypothesis: NATIVE — sufficient for the machinery, insufficient for the
seams.** `LiveExecutionClient` supplies all but eight `NotImplementedError`
coroutines (`NT/live/execution_client.py:598-633` `[V]`) and the report
coroutines. **GENUINELY ABSENT:** `AccountState` emission, `_set_account_id`,
`_query_account`, the reconciliation **match** assertion, and the durability
decision.

**Goal.** One `PolymarketUSExecutionClient(LiveExecutionClient)`.

- **BL-15 — `account_id` must be set explicitly.** `execution/client.pyx:135`
  initialises `self.account_id = None` and `_set_account_id` (`:148-152`, which
  asserts `id.value == account_id.get_issuer()`) is the only setter `[V]`. The
  failure is silent in exactly the way this plan exists to prevent:
  `live/execution_client.py:544-546` `[V]` — `if not self.account_id:` log a
  warning and **return as if successful**. A `_connect` that fetches balances,
  calls `generate_account_state` and awaits registration would then produce one
  warning, **no account in cache**, and `risk/engine.pyx:684-689` `return True` —
  **F-1 fully restored**. `_connect` therefore: `_set_account_id(...)` FIRST →
  fetch balances → assert currency identity (F-5) → `generate_account_state` →
  `_await_account_registered` → **assert the account is actually in the cache**,
  never trusting the await's return.
- **`_connect` fails closed** on any of: balance read failure, currency mismatch,
  account absent from cache after the await.
- **`_query_account` defined explicitly** (N-6) — omitting it raises
  `AttributeError` inside a created task, swallowed into `_log.exception`
  (`:226` `[E]`).
- **All eight lifecycle coroutines refuse** via `generate_order_denied`
  (`NT/execution/client.pyx:370` `[V]`) — terminal, pre-venue, no `OrderSubmitted`
  (`AUDIT:164-169` `[E]`). Only `_connect`/`_disconnect` are real.
- **BL-6 — Breezy owns the reconciliation match assertion.** With
  `generate_missing_orders=False`, `live/execution_engine.py:2503-2510` `[V]` logs
  a warning on `not quantities_match` and **`return True`**. Since NETTING is
  pinned, the strict hedging branch is unreachable, so native "SUCCEEDED" no
  longer implies "matched" and G1's assertion would pass **precisely in the state
  it was written to detect**. Breezy therefore compares its own
  `PositionStatusReport` set against the cache after `generate_mass_status` and
  **halts on any discrepancy** (`TRADING_SYSTEM_ARCHITECTURE.md:1212` `[V]`:
  reconciliation mismatch halts, it never self-heals). The halt has a named owner:
  `exec/client.py::_assert_reconciled`.
- **BL-14 / G6 — the durability decision, made explicitly.**
  `node_config.py:199,455` pin `CacheConfig(database=None, flush_on_start=False)`
  `[V]`, and `DatabaseConfig.type` accepts **`{'redis'}` only** `[V]`. Die holding
  a position → restart → empty cache → BL-6's silent pass → the bot runs with
  **zero knowledge of live exposure**, every cap sees zero, and it can open a
  second position in the same market with every gate green. **Decision: the
  trading node runs `CacheConfig(database=DatabaseConfig(type="redis", …),
  flush_on_start=False)`** — set at **E-2**, because durability is a property of
  the process, not of the client. `flush_on_start` stays `False`: flushing would
  erase the recovery state this is for. The ingest and quote-tape nodes keep
  `database=None`; they hold no positions. Redis is a real new infrastructure
  dependency and is accepted rather than hidden; it is a **hard prerequisite of
  E-12**, and until it is in place the process refuses to start (N10 treatment).
  `[I]` — I considered and rejected "reconstruct from venue reports alone at
  startup": reports give positions but not the `ClientOrderId` ↔ venue-id mapping
  the ambiguity latch of E-11 depends on.
- **The staleness fence — Redis loss mid-session (HIGH).** `flush_on_start=False`
  makes the persisted cache **authoritative at startup**, so a Redis that dies
  while positions are being written degrades the cache to **stale, not absent** —
  the dangerous direction. A position whose `quantity` still matches but whose
  `avg_px_open` is stale reconciles **CLEAN** and corrupts G3 silently, because
  quantity is what the native comparison checks
  (`live/execution_engine.py:2503-2510` `[V]`). Three parts, all here:
  (a) Breezy writes a **monotonic session sequence** on every position-affecting
  event and asserts at startup that the loaded sequence is the highest it ever
  wrote; (b) `_assert_reconciled` compares **average entry price and quantity**,
  not quantity alone, against the venue `PositionStatusReport`; (c) a sequence gap
  or any field mismatch is **reconcile-or-halt**, never a warning. **A drill, not
  only a test:** kill Redis mid-session while holding a position, restart, and
  assert the process halts rather than trades. `[I]` on which venue field carries
  average entry price — OQ-17.
- **`filter_unclaimed_external_orders=False`, pinned explicitly (R2-BL-5).**
  Native default is already `False` (`NT/live/config.py:180` `[V]`), but set
  `True` it makes the engine **silently discard** an unclaimed external report
  (`live/execution_engine.py:3575-3580` `[V]`) — which after E-6 is the settlement
  fill, the single event that realizes all PnL. A defaulted value and a chosen one
  are indistinguishable in review, so it is stated and tested on the built config.
- **Account shape chosen once, not denied at runtime.**
  `account_type=AccountType.CASH`; `base_currency=None` (multi-currency, matching
  the venue's per-currency balance list) with F-5's identity check as the control.
  `oms_type=OmsType.NETTING`, pinned by test —
  `_reconcile_position_report_hedging` (`NT/live/execution_engine.py:2349`) was
  never read (`AUDIT:180-181` `[E]`), and pinning NETTING makes it unreachable.
  `[U]` whether `base_currency=USD` would be strictly safer: OQ-11.
- **Config pins.** `generate_missing_orders=False` (E-6's prerequisite; native
  default `True`, `NT/live/config.py:183` `[V]`); `inflight_check_interval_ms=2000`
  (`:184` `[V]`); **`inflight_check_threshold_ms` pinned ABOVE the venue's 5 s
  stopgap** and `inflight_check_retries` pinned explicitly (`:185,186` `[V]`) —
  both are BL-13 inputs; `open_check_interval_secs` / `position_check_interval_secs`
  left `None` **for now** (H-5: enabling the position check before E-6 makes a
  wrong-price fill fire repeatedly, `AUDIT:113-120` `[E]`), re-decided in E-6.

**RED first — every one of these drives E-2's composed node, started through
`trading_composition.trading_runtime`, never a bespoke test node.** (a) The node
starts with the exec client registered and `cache.account_for_venue(...)` is
**not `None`**, with `account_id` set, before any strategy runs. (b) `_connect` with `account_id` unset does **not** silently
succeed. (c) A venue balance in a non-`USD` currency makes `_connect` raise
(F-5). (d) Each of the eight coroutines emits `OrderDenied` with a named reason
and **never** `OrderSubmitted`. (e) `_query_account` is awaited without
`AttributeError`. (f) A position-quantity discrepancy **halts**, and the test
asserts the halt rather than the absence of an exception (BL-6). (g) Kill the
process holding a position, restart, and the cache reports the position (G6).
(h) Kill **Redis** holding a position, restart the process, and it **halts**.
(i) A venue position whose quantity matches but whose average entry price differs
**halts** — revision 2's quantity-only comparison passes it. (j) The built config
carries `filter_unclaimed_external_orders=False`.

**Barriers.** Layer 1 — **B6b narrowed** per §5; the **permit-issuer barrier
flips `== 0` → `== 1`** in this commit, the first in which `exec/factories.py`
exists, with proofs that both `== 0` and `== 2` fail. Layer 4 — **only the E-2
site's** `exec_clients` moves `{}` → exactly one key, under §6.2's per-site value
table; `strategies` and `exec_algorithms` stay `[]` there in this increment; the
ingest (`:203,204,212,218` `[V]`) and quote-tape (`:459,460,463,464` `[V]`) sites
are byte-unchanged and pinned to their exact values — stricter than the emptiness
rule they had before. `len(_node_config_calls()) == 3` retained. Layer 3 — N2
exact-set grows. **No write verb, literal or signing change.**

**Completion.** **G1** and **G6** met, inside a process that exists.

---

### E-5 — The denial layer over all five fail-opens · **[NO-SEND]**

**Null hypothesis: NATIVE — insufficient, and dangerously so.** §0.4's F-table
lists **five** silent fail-opens on one code path. Breezy denies **before**
Nautilus is consulted; a green run is never evidence a native check engaged
(`AUDIT:48-52` `[E]`). *This discipline was preserved unanimously by all four
lenses; only its coverage grew.*

**Goal.** `exec/denial.py` — every refusal named, counted, alerted, raised
pre-Nautilus.

| Refusal | Trigger | Evidence |
|---|---|---|
| `NoCachedAccountError` | `cache.account_for_venue(...) is None` | **F-1**, `engine.pyx:684-689` `[V]` |
| `MarginAccountUnsupportedError` | `account.is_margin_account` | **F-2**, `:691-692` `[V]` |
| `UnpopulatedNotionalCapError` | cap absent, non-`Decimal`, `<= Decimal("0.01")`, **or** not round-tripping non-zero when re-read from the engine | **F-3**, `:675-679` `[V]` — BL-11 |
| `MarketOrderRefusedError` | `order.order_type is MARKET` | **F-4**, `:786-789` `[V]` |
| `BalanceCurrencyMismatchError` | emitted `AccountBalance.currency != USD` | **F-5**, `:949,968,1001,1026` `[V]` |
| `UnsupportedOrderTypeError` | any of the 7 types the venue does not expose | `sdk_snapshot/.../types/orders.py:7` `[E]` |
| `RestingTimeInForceRefusedError` | **any TIF other than IOC or FOK** | BL/HIGH maker gap — see below |
| `PostOnlyRefusedError` | `order.is_post_only` → `participateDontInitiate` | N-5 `[V]`; B-3 `[E]`; `fees.py:199-208` `[V]` |
| `PriceOutOfVenueBoundsError` | `price.value` outside **[0.01, 0.99]** | `overview:162,164` `[V]` |
| `ShortSideRefusedError` | non-reducing SELL under `allow_short=False` | H-6 `[E]`; `risk.py:83` `[V]` |
| `AmbiguousSubmitLatchedError` | the market's latch is set | E-11 |

**BL-11 in full.** `engine.pyx:677` is `if max_notional_setting:` — a **present
`Decimal("0")` is falsy**, so the cap never fires `[V]`. Since E-5 computes
`cost_cap = payout_cap × price` at instrument load (§4.2), a bucket with **no
quote yet** yields `cost_cap = 0`, `set_max_notional_per_order` accepts it, a
presence-only check passes, and that instrument has **no ceiling at all** — the
F-1 class of bypass reached *through the remedy*. The guard is therefore
four-part (present, `Decimal`, `> 0.01`, round-trips non-zero), and instruments
with no quote are **not registered for trading at all** until one arrives.

**The maker prohibition, widened (HIGH).** Revision 1 enforced it only against
`post_only`, which does not prevent a **GTC limit resting and filling as maker**.
`resting_ladder.py:190,204` `[V]` submits `TimeInForce.GTC, post_only=False`
precisely to rest. Since the modelled maker fee is wrong in **sign** (B-3 `[E]`),
the boundary refuses **any time-in-force that can rest**: only `IOC` and `FOK`
pass. This is the same conclusion §10's non-goal 2 asserts, now *enforced*
instead of asserted — and it makes `resting_ladder.py` structurally
unregistrable, which E-7 records.

**The absolute price bounds (HIGH).** Tick-aligned is **not** valid.
`overview:164` `[V]`: *"Invalid prices (below 0.01 or above 0.99) are restricted
at the exchange level. Since the order is sent to the exchange, you will still
receive an orderID, but the order will never fill because it gets rejected during
validation."* An out-of-bounds order therefore **consumes the bucket** via
`pending_qty` and the exclusivity rule while being unfillable, and may never
appear in `/v1/orders/open` to be cancelled. Refused client-side, with REDs at
0.005 and 0.995.

**Native configuration N-2 requires.** Call
`RiskEngine.set_max_notional_per_order(instrument_id, cost_cap)`
(`engine.pyx:279` `[V]`) for every instrument as it loads, carrying §4.2's L-2
line in the code.

**RED first.** Each row: construct the condition, submit, assert the named Breezy
exception, assert `generate_order_denied` fired **and** the risk engine was never
reached. Plus: (i) with **no** account cached and Breezy's denial removed, an
order at 1000× the intended notional **passes** the native check — the F-1
proof-by-construction, written so nobody later reads a green run as evidence
(*preserved by all four lenses*); (ii) the same construction for F-3 with
`Decimal("0")` and for F-5 with a `USDC` balance; (iii) §4.3's barrier — no
strategy or sizing module calls `portfolio.equity(`/`net_exposure(`/`net_exposures(`.

**Completion.** **G4** met. `describe_binding_order` re-run against actual
defaults (`DATA_CAPTURE_AND_RISK_PLAN.md:302` `[V]`).

---

### E-6 — Settlement is the exit, via the REPORT path · **[NO-SEND]**

**The problem (H-3 `[E]`), and revision 1's broken fix.** On settlement the venue
reports flat while the cache holds the position open. With
`generate_missing_orders=True` (native default, `NT/live/config.py:183` `[V]`) the
engine synthesises a closing order priced by `_create_position_reconciliation_report`
(`NT/live/execution_engine.py:2839-2924`): an accounting reconstruction, then the
last cached quote — but a settled market publishes an **empty book**
(`data.py:624-641` `[V]`) — then **`current_avg_px`**, i.e. close at entry, **zero
PnL**. Settlement is the only exit, so this corrupts the single event that
realizes all PnL.

**BL-4 — revision 1's mechanism could not execute.** It set
`generate_missing_orders=False` and emitted the closing fill with
`generate_order_filled`. `_ORDER_STATE_TABLE` has **eight transitions into
`FILLED` and none out of it** (`NT/model/orders/base.pyx:110-160` `[V]`), so the
call raises `InvalidStateTrigger`: revision 1 **disabled the machinery that
creates the closing order and then kept only the fill half**. G3 was unreachable
as designed.

**BL-5 — the trigger it waited on is not emitted live.**
`TERMINAL_SETTLEMENT_METHOD = "…_EVENT_TIER_1"` (`parsing.py:229` `[V]`) while
`parsing.py:220-222` `[V]` records that an **open** market's capture carries
`…_EVENT_TIER_2`. With `generate_missing_orders=False` removing every fallback,
waiting on `InstrumentClose` alone means **nothing closes the position**: PnL
never booked, and after `max_simultaneous_positions` stuck buckets the bot stops
trading while believing it is fully invested. **That conclusion stands. The
conclusion revision 2 drew about the price SOURCE does not — see R2-BL-2 below.**

**Corrected design — seven changes.**

1. **Report path, not the fill path.** `exec/client.py` returns a **synthetic
   closing `OrderStatusReport` plus a matching `FillReport`** at the settlement
   price, and lets Nautilus's external-order reconciliation create the order and
   apply the fill through legal transitions. Nothing in Nautilus is patched; the
   native reconciliation path is used **as designed**, which is why this is a
   configuration-and-reports change rather than an authored state machine.
2. **R2-BL-2 — the price source is the MARKET BOOK, and the endpoint is
   secondary.** Revision 2 promoted `GET /v1/markets/{slug}/settlement` to primary
   on the strength of a characterisation ("TIER_1 was seen once, on an archived
   file") that was never verified and is **wrong**. The captured evidence in this
   repo, re-read (N-15 `[V]`):

   | Source | Resolved weather buckets | Open bucket |
   |---|---|---|
   | `stats.settlementPx` + `…EVENT_TIER_1` + `closePx` absent | **2/2 correct** — `1.0000` and `0.0000`, `settlementSetTime` populated | not TIER_1 (TIER_2, `closePx == settlementPx`, a daily mark) — correctly rejected |
   | `GET /v1/markets/{slug}/settlement` | **0/2** — `{"code":5,"message":"Settlement not found …"}` | 0/1, same |

   Five captures, **five 404s, zero 200s**, and `VENUE_FACTS_2026-08-25.md:14`
   `[E]` has said so since 2026-08-25: *"A resolved book showed final-looking
   `settlementPx`, but `/settlement` **also returned 404 for resolved weather
   buckets**."* **Inverted back:** PRIMARY is `stats.settlementPx` from the market
   book, admitted **only** under a three-part conjunction — method is
   `…EVENT_TIER_1`, `settlementSetTime` is present, and **`closePx` is absent**.
   SECONDARY is `/v1/markets/{slug}/settlement`, whose **404 is the expected
   response** and is mapped to "absent", never to an error and never to a retry
   (E-3). If it ever returns 200 and **disagrees** with the primary, that is a
   named `SettlementSourceConflictError` halt — not a preference order, because
   nothing on disk justifies trusting either over the other.

   **One citation in the finding is corrected.** R2-BL-2 says `closePx`-absent is
   "the discriminator `parsing.py:887-892` already implements". It is not:
   `_is_terminal_settlement` (`:887-892` `[V]`) requires terminal **state** AND
   `TERMINAL_SETTLEMENT_METHOD`, and never reads `closePx`. The `closePx`
   discriminator is real and **unimplemented**; E-6 adds it as the third conjunct.
   It matters because state∧method alone cannot separate "TIER_1 and settled" from
   "TIER_1 and mid-auction", and an implementer told it already exists ships
   nothing.

   The `InstrumentClose` path (`parsing.py:1020-1034` `[V]`) remains a
   corroborator, not the trigger. The trigger is a market leaving the tradable
   states, polled on the reconciliation cycle.
3. **R2-BL-3 — the settlement fill has a deterministic identity.** Nautilus
   dedupes reconciliation fills **solely by `TradeId`** (N-16 `[V]`:
   `get_existing_fill_for_trade_id`, `report.trade_id in order.trade_ids`). A
   settlement is not a venue trade: there is no venue `TradeId` and no
   `VenueOrderId`, so E-6 must fabricate both. Revision 2 did not say how, and a
   fresh id per poll re-applies the fill every cycle: hold 100 @ 0.30 settling at
   1.00 → poll 1 books +$70 and goes flat → poll 2 **shorts 100** at a price the
   venue never quoted → poll 3 shorts 200, with $70 of phantom PnL per cycle
   flowing into an append-only calibration archive. `allow_short=False` is a
   **pre-trade** control and never touches the reconciliation path; the second
   dedup arm reads the cache, which a restart clears.

   **Both ids are pure functions of the settlement facts and nothing else:**
   `VenueOrderId(f"SETTLE-{slug}-{settlementSetTime}")` and
   `TradeId(f"SETTLE-{slug}-{settlementSetTime}-{settlementPx}")`, with no clock
   read, no UUID, no counter, no cache lookup — AST-scanned (§5). Re-polling and
   post-restart re-reporting are then idempotent **by construction**, not by
   remembering. `settlementPx` is included so a venue correction produces a
   *different, deliberate* fill rather than a silently-ignored duplicate.
4. **R2-BL-3 — `commission` and `liquidity_side` are pinned.**
   `FillReport.__init__` requires both explicitly (N-19 `[V]`), so they are chosen
   either deliberately or by accident. `commission = Money(0, USD)` — the venue's
   own fee is `theta × p × (1 − p)`, which is **exactly zero** at p ∈ {0, 1}, so
   settlement is genuinely free and a non-zero value would fabricate cost.
   `liquidity_side = LiquiditySide.NO_LIQUIDITY_SIDE` — settlement crosses no
   book. Secondary reason to pin rather than default: any later routing of this
   fill through Breezy's own fee model raises on a sideless fill
   (`fees.py:163-171` `[V]`), so a wrong choice fails loudly there too.
5. **R2-BL-5 — the fill must land on the SAME position as the entry.**
   `_determine_netting_position_id` returns
   `PositionId(f"{fill.instrument_id}-{fill.strategy_id}")` (N-17 `[V]`), and an
   unclaimed external report resolves to `StrategyId("EXTERNAL")`
   (`live/execution_engine.py:3551,3556` `[V]`). So an entry under strategy `S`
   sits on `INSTR-S` while the settlement report would land on `INSTR-EXTERNAL`:
   **the long stays open at entry price with PnL never realized — the exact H-3
   defect this increment exists to fix — beside a phantom short.** The fix is
   native and costs no authored code: the registered strategy claims every
   instrument it trades via `StrategyConfig.external_order_claims`
   (`NT/trading/config.py:91` `[V]`) at **E-7**, and
   `filter_unclaimed_external_orders=False` is pinned at **E-4** so the report is
   not discarded instead (`:3575-3580` `[V]`). E-6 states that the settlement
   report is attributed to the claiming strategy and tests it.
6. **The settlement watchdog (HIGH) — this is what makes the whole class loud.**
   Every source above can be absent: TIER_1 may never appear, `/settlement` may
   404 forever, the market may sit in an unmapped state. A position past its
   instrument's `expiration_ns` with **no settlement price from any source** after
   a bounded grace period latches a named **`SettlementOverdueError`** — halting
   new exposure, alerting, and leaving cancellation available (§6.4). Without it,
   every failure in this section is silent and looks like a position that simply
   has not settled yet; with it, R2-BL-2's entire class is loud.
7. **`generate_missing_orders=False` is retained**, and its cost is now owned:
   BL-6's silent-pass is covered by E-4's Breezy-side match assertion, so
   "reconciliation returned" and "reconciliation matched" are separate facts.

**Terminal-state correction (N-12, HIGH).** `EXPIRED_MARKET_STATES` is
`{EXPIRED, SETTLED, CLOSED}` (`parsing.py:212-214` `[V]`), but the venue's
documented enum is `OPEN, PREOPEN, HALTED, SUSPENDED, MATCH_AND_CLOSE_AUCTION,
EXPIRED, TERMINATED` `[V]`: **`SETTLED` and `CLOSED` do not exist**, and
`TERMINATED` — the real second terminal state, i.e. a **voided** market — is
absent from Breezy's set. A voided market settling at 0 would book a 100 % loss on
a trade that refunded capital, permanently, into an append-only calibration
archive. E-6 therefore: adds `MARKET_STATE_TERMINATED` as a **distinct** terminal
state that is **never** priced at 0/1 but routed to a named
`VoidedMarketError`-halt for operator resolution; keeps `SETTLED`/`CLOSED` for
backward compatibility only if a raw capture is ever found containing them, and
otherwise removes them with the evidence recorded (§11 D-4).

**RED first, before the module exists.** (i) `generate_order_filled` on a FILLED
order raises `InvalidStateTrigger` — the characterisation of BL-4, so the report
path is chosen for a reason on the record. (ii) A settled position closed through
the **native** path books `realized_pnl == 0` — must fail after the fix.
(ii-a) **Emitting the same settlement report three times books exactly one fill,
one position transition and one PnL entry** (R2-BL-3), and a fourth emission
**after a process restart** still books nothing new. (ii-b) The settlement fill
resolves to the **same `PositionId` as the entry** — the RED asserts equality of
the two `PositionId`s, which fails today because the report is unclaimed
(R2-BL-5). (ii-c) An open TIER_2 market with `closePx == settlementPx` is
**refused** as a settlement source; a resolved TIER_1 market with `closePx`
absent is accepted — both fixtures are the captures of N-15, used verbatim.
(ii-d) A `/settlement` 404 alongside a valid TIER_1 book settles **normally**,
with no error counted. (ii-e) A `/settlement` 200 disagreeing with TIER_1 halts.
(ii-f) A position past `expiration_ns` with no price from any source latches
`SettlementOverdueError` and **a cancel still dispatches**.
(iii) `Price(0.00)` and `Price(1.00)` survive `make_price`, `Price` validation and
fill validation. This is `[U]` (`AUDIT:176-179` `[E]`); the only suggestive
evidence is `instrument.make_price(0.0)` at `NT/live/reconciliation.py:493`. **If
this RED cannot be made GREEN, E-6 stops and OQ-4 escalates** — the fallback
settles at the nearest representable tick and **reports the residual as a named
error**, never a silent clamp. (iv) A market in `MARKET_STATE_TERMINATED` does
**not** book a 0 settlement.

**Barriers.** None narrowed. H-5 re-decided: with the price correct,
`position_check_interval_secs` may be enabled — value and reason recorded, or it
stays `None` and that is recorded. Enabling it before this increment is forbidden.

**Completion.** **G3** met — realized PnL equals
`qty × (settlementPx − avg_px_open) − fees`, booked **once**, on the **entry's**
position, in a test that executes the path inside E-2's node.
*Rejecting settlement option (a) — writing the settlement price into
`avg_px_open`, which would corrupt entry-price arithmetic and all downstream
attribution — was preserved by all four lenses and stands.*

---

### E-7 — Order-source enablement: the increment revision 1 did not have · **[NO-SEND]**

> **BL-1, the most serious finding.** `node_config.py` pins **three** empty
> literals, not one: `exec_clients={}` (`:204`), `strategies=[]` (`:212`),
> `exec_algorithms=[]` (`:218`) `[V]`, and its own comment at `:205-211` says
> `strategies=[]` "removes **the only component that calls `submit_order` at
> all**". Revision 1 disposed of `exec_clients` only. Executed perfectly, it
> produced a live-capable execution client with **zero order sources** — LESSONS
> L-3 recurring inside the document written to fix L-3, because the second long
> pole lived behind a different file's barrier.

**Goal.** Register exactly one strategy **into E-2's node**, convert it to an
order shape the denial layer accepts, claim the instruments it trades, and state
the direction mapping exhaustively — **all while the tree still has no write
capability**, so the whole decision→order path can be exercised with every order
denied at the boundary.

**E-7.0 — `external_order_claims`, and why it belongs to the strategy (R2-BL-5).**
The registered strategy's `StrategyConfig` sets `external_order_claims` to every
`InstrumentId` it trades (`NT/trading/config.py:91` `[V]`). This is not a
convenience: position identity is `f"{instrument_id}-{strategy_id}"` (N-17 `[V]`),
so without the claim E-6's settlement report resolves to `StrategyId("EXTERNAL")`
and lands on a **different position** — the entry stays open at entry price and a
phantom short appears beside it. The claim is the native mechanism that makes the
settlement fill and the entry the same position. Because instruments are
discovered at runtime, the claim list is populated as instruments register, and a
RED asserts that an instrument the strategy can trade but has **not** claimed is
refused at order construction — an unclaimed instrument is a settlement failure
waiting to happen, so it is refused at entry rather than discovered at exit.

**E-7.1 — Which strategy is registrable, and why.** `[V]`:

| Strategy | Order type | TIF | Registrable? |
|---|---|---|---|
| `forecast_edge.py:168` | MARKET, unconditional | — | **No** — F-4 |
| `strike_ladder.py:305` | MARKET, unconditional | — | **No** — F-4 |
| `harness_probe.py:199` | MARKET, unconditional | — | **No** — F-4 |
| `resting_ladder.py:190,204,340` | LIMIT | **GTC**, `post_only=False` | **No** — resting TIF refused (E-5) |
| `forecast_mispricing/strategy.py:341/349` | LIMIT if `use_limit_orders` (**default `True`**, `config.py:110`) else MARKET | **IOC** | **Yes**, with the flag banned from `False` |
| `forecast_revision/strategy.py:363/371` | same (`config.py:123`) | **IOC** | **Yes**, same condition |
| `calibration_mean_reversion/strategy.py:367/375` | same (`config.py:126`) | **IOC** | **Yes**, same condition |

**E-7.2 — The MARKET arm is removed, not merely denied.** E-5's
`MarketOrderRefusedError` is a runtime backstop. Leaving the arm in place means a
one-flag change produces a bot denied 100 % of the time **while looking healthy**
— every refusal named and counted, which reads as a working safety system. E-7
therefore: (a) makes `use_limit_orders` accept only `True` on the registered
strategy's config, raising at construction; (b) adds a static test that the
registered strategy module contains no `order_factory.market(` call; (c) records
the other four strategies as **backtest-only** by name.

**E-7.3 — The direction mapping, stated once and exhaustively (BL-3).**

`parsing.py:1083-1086` `[V]` requires **exactly one** long market side and builds
ONE `BinaryOption` per slug from `long_sides[0]`, so **Breezy never holds a
NO-side instrument**. The venue's rule *"To trade the NO side at any price X, set
`price.value = 1.00 − X`"* (`overview:158` `[V]`) is therefore the **identity** for
every order Breezy can construct. Revision 1 made that inversion its E-11 price
row and its **only** committed direction RED — a test asserting a transform that
must never fire, while the transform that runs on 100 % of orders had no test at
all. **The mitigation created the 49× hazard it was written to prevent.**

`exec/direction.py` is a **total** function over `OrderSide` with exactly two arms:

| `OrderSide` | Meaning on our YES instrument | `intent` | `outcomeSide` | `action` | `price.value` |
|---|---|---|---|---|---|
| `BUY` | open / increase long YES | `ORDER_INTENT_BUY_LONG` | `OUTCOME_SIDE_YES` | `ORDER_ACTION_BUY` | the YES limit price, **unmodified** |
| `SELL` | reduce / close long YES (never naked — E-5) | `ORDER_INTENT_SELL_LONG` | `OUTCOME_SIDE_YES` | `ORDER_ACTION_SELL` | the YES limit price, **unmodified** |

Both encodings are sent, mutually consistent, so a venue honouring either field
produces the same side — the documented precedence is `outcomeSide`+`action`
(`overview:114` `[V]`). **`ORDER_INTENT_BUY_SHORT`, `ORDER_INTENT_SELL_SHORT`,
`OUTCOME_SIDE_NO` and any `1 - price` form are banned by AST scan anywhere under
`exec/`** — structurally unreachable, not merely unused.

**A clarification that prevents a bad fix.** `risk.py:75-78` `[V]` reads *"'short
YES' is spelled 'buy NO', a different instrument with its own book"*. In context
that is the **justification for `allow_short=False`**, and it is correct. An
implementer skimming it would map `OrderSide.SELL → ORDER_INTENT_BUY_SHORT`,
turning a reducing sell of 100 @ 0.30 into a **buy of 100 NO at 0.70** that also
self-matches the resting YES (`overview:141-158` `[V]` documents the self-match).
The comment must **not** be edited; the table above is the fix.

**E-7.4 — The price-side assumption, with a real oracle (HIGH).** The table
assumes our `BinaryOption`'s `Price` is denominated in YES terms, because the
instrument is built from the long side (`parsing.py:1083-1086` `[V]`) and the
venue documents `price.value` as always the long side (`overview:141-158` `[V]`).
That is an inference, not a read.

**Revision 2's RED for it was vacuous** — "the best ask in the cached quote must
equal the YES-side ask in the raw capture" compares the parser's output to the
parser's own input, so it is GREEN under **both** hypotheses. Corrected, and the
assumption turns out to be **provably true from a capture already on disk**
(N-21 `[V]`): in `book_open_510636.json` the best bid is `0.5300` and
`stats.lastPriceSample.longPx` is `0.5300`, with `shortPx = 0.47 = 1 − longPx`.
`lastPriceSample` is produced by the venue **independently of the book array**, so
it is a genuine external oracle: if our `Price` were NO-denominated the cached bid
would track `shortPx`, not `longPx`. The fixture is deliberately this one because
it is **materially off 0.50** — a 0.50/0.50 market is indistinguishable under
either hypothesis and would re-create the vacuity in a different costume. The RED
asserts the cached top-of-book bid equals `stats.lastPriceSample.longPx` and is
**not** equal to `shortPx`. If it fails, E-7 stops — this is the assumption whose
silent failure costs 49×.

**RED first.** (i) The registered node's `TradingNodeConfig` has exactly one
strategy entry and `exec_algorithms == []`. (ii) **In the node
`trading_composition.trading_runtime` builds** — not a harness — a `QuoteTick`
injected at the data client's boundary reaches the registered strategy's
`on_quote_tick` (`forecast_mispricing/strategy.py:166,196` `[V]` subscribes and
acts there), and the resulting `SubmitOrder` reaches `_submit_order` and is
**denied by name with no network call**. This is the **G0 oracle** and the direct
answer to R2-BL-1: revision 2's version of this RED passed against a harness while
the composed node had `data_clients={}`, so the subscription routed nowhere.
(ii-b) The same RED run against a config whose `data_clients` is empty **fails**,
so the test cannot go vacuous the way its predecessor did. (iii) An exhaustive parametrised test over **both** `OrderSide` values
asserts the four-tuple and that `price.value` is **unmodified**. (iv) AST scan:
`_SHORT`, `OUTCOME_SIDE_NO`, `1 - price` absent from `exec/`. (v) Constructing the
registered strategy's config with `use_limit_orders=False` raises. (vi) The
YES-denomination RED of E-7.4, against `book_open_510636.json`. (vii) The
strategy's `external_order_claims` contains every instrument it can trade, and an
unclaimed instrument is refused at order construction (E-7.0).

**Barriers.** Layer 4 — the **third and last** node_config narrowing under §6.2's
per-site table: `strategies` moves `[]` → exactly one entry **at the E-2 site
only**, paired with `exec_algorithms == []` asserted at **all three** sites and
the ingest and quote-tape sites byte-unchanged; `len(_node_config_calls()) == 3`
retained. No write capability is added.

**Completion.** **G0** complete — a venue quote reaches a registered strategy in
the process the entry point builds. G2's **source** exists. The bot produces real
orders end to end and every one is refused at the boundary with zero network
capability — the only configuration in which BL-2's class of defect is observable
rather than theoretical.

---

### E-8 — The write chain, allowlisted to ONE scoped non-exposure endpoint · **[SEND — narrowly]**

> **First commit at which live order capability is reachable.** What is reachable
> is a **market-scoped** `POST /v1/orders/open/cancel` and nothing else: it can
> cancel working orders in one named market; it cannot open exposure. After E-1's
> BL-8 fix the permit's operator-set endpoint allowlist must also name it, so this
> is an operator act, not an author's.

**Null hypothesis: GENUINELY ABSENT.** Searched `NT/adapters/` for a reusable
venue-agnostic signed-write transport: every adapter writes its own
(`NT/adapters/binance/execution.py`, `NT/adapters/dydx/execution.py` `[V]`
existence). Nautilus supplies `nautilus_pyo3.HttpClient` and `RetryManagerPool`;
both are wired, neither reimplemented. *Reuse-over-authorship was preserved by all
four lenses; no lens found a foundation violation.*

**Goal.** `exec/signing.py`, `exec/transport.py`, `exec/egress.py` per §5.

- **Signing is identical for writes** (B-0 `[E]`): same three headers, same
  canonical string `timestamp_ms + METHOD + path`, same Ed25519
  (`api-reference_authentication_2026-08-25.md:82,92-96` `[E]`; SDK
  `auth.py:26-27` `[E]`). **No nonce, no EIP-712, no on-chain transaction, no
  wallet, no allowance, no ERC-20/1155 approval** — those are Polymarket **.com**,
  a different venue. The work is a widened frozenset in a *separate* module;
  B1/B2/B3 stay byte-identical.
- The body seam already exists and is inert (`signing.py:108-123` `[V]`).
  `exec/signing.py` implements **both** branches behind one variant and defaults to
  the documented no-body form; E-9 decides. `[U]` OQ-1.
- **Path-segment validation before signing:** every interpolated segment matches
  `^[A-Za-z0-9_-]+$`. The canonical string has no field delimiter
  (`signing.py:37-41` `[V]`), so same-method path ambiguity is the residual once
  variable paths exist.
- `exec/transport.py`: own pyo3 client, own closure, own quota bucket, an
  **equality-pinned frozenset of exactly one `(method, template)` pair**, and
  **four** dispatch entry points, each taking its own authority type
  **positionally**, checking `type(auth) is <that type>` (never `isinstance`,
  §6.3.1) and **consuming** it before any I/O. At this increment only the
  cancellation entry point has a reachable endpoint; the other three exist and
  refuse, so the type discipline is proven before it guards real money.
- `exec/egress.py`: request construction, chokepoint call (**one of three**, per
  §6.3 BL-12), capability threading, response parsing. **< 200 lines.** No
  decision logic — every refusal already happened in E-5.
- **Retry: wire `RetryManagerPool` (`NT/live/retry.py:242` `[V]`)** — never write a
  backoff loop — **and make it non-dead (HIGH, N-18).** `RetryManager.run` retries
  only exceptions listed in `exc_types` (`:101,172` `[V]`), so the pool as revision
  2 wired it would never fire on the venue's own `429`/`503`, which arrive as
  ordinary response objects (`transport.py:328-340` `[V]`). `exec/transport.py`
  therefore raises the typed exceptions named by E-3's classification table, and
  those types are the pool's `exc_types` — pinned by an equality test that the two
  sets are identical, so a class added to the table without a raiser, or a raiser
  without a table entry, fails. Enabled for **read / status / cancel only**; the
  submit path has no retry and never will (B-1). An **AMBIGUOUS** classification is
  never retryable — it latches (E-11). Because cancels use the
  **non-decrementing** `CancelAuthorization` (§6.3.1), a retry storm can no longer
  exhaust the permit and disarm the kill switch.
- **Reserved data-path share** (B-4 `[E]`): sized so `egress_rps + data_rps < 20`
  with headroom; exhausting the egress share latches `HALT_NEW_EXPOSURE` rather
  than consuming the tape's share. The data path claims 15 rps
  (`transport.py:122` `[V]`) against a 20 rps key-wide cap (`transport.py:119`
  `[V]`; `rate-limits:15` `[V]`) — **5 rps remain and the split must be re-derived,
  not assumed.** OQ-9.
- **N10 retained:** `exec/egress.py` refuses to construct when the circuit-breaker
  thresholds are absent.

**RED first.** (i) A dispatch without the capability is a `TypeError` at the call
site. (i-b) A `CancelAuthorization` handed to the submit entry point is refused by
the `type(...) is` check, and a subclass of it is refused too (R2-BL-4).
(ii) A capability minted for one `(method, path, body, notional)` refuses a
different one — **including a one-byte body mutation** (BL-10). (iii) A second
dispatch with the same capability raises "already been used"
(`safety.py:468-471` `[V]`). (iv) A `(method, path)` off the frozen allowlist **or
off the permit's endpoint scope** is refused **before** signing, so no signature is
ever produced for it (BL-8). (v) A dispatch that skips `consume(...)` fails a
static test. (vi) A cancel consumes a cancellation authority and leaves the
operator's budget **unchanged** (BL-12).

**Barriers.** Layer 1 — **B4/V1** (exact path `exec/signing.py`), **B4/V3** (exact
path `exec/transport.py`), **B6a → `== 1` per chokepoint** at `exec/egress.py`,
each with its §5 pair in this commit; `.request` stays banned in all three.
Layer 2 — `http.py`/`signing.py`/`transport.py` diffs are **empty**, asserted by an
equality test on those files' `PERMITTED_*` constants.

---

### E-9 — Signature-scheme probe: market-scoped cancel-all while provably flat · **[SEND — operator-run]**

**The epistemic decision, preserved.** The brief and the review both name
preview's non-mutation as the highest-leverage unknown. I keep revision 1's
ordering: **a POST is a POST, and preview's non-mutating status is the very thing
under test, so it cannot also be the assumption that makes the test safe.** A
cancel-all against a market verified to have zero open orders is a provable no-op
in the exposure dimension. *This reasoning was explicitly endorsed by the review;
only the probe body was wrong.*

**HIGH — the probe body is corrected.** All three non-domain reviewers
independently found that `cancel_all` with no parameters sends `{}`
(`sdk_snapshot/.../resources/orders.py:62-66` `[V]`), so **both** signing
hypotheses produce the same canonical string and a 200 would close OQ-1 **falsely**.
The probe therefore sends `{"slugs": [<one slug proven to have zero open orders>]}`
— **non-empty**, so it discriminates, **and scoped**, so it cannot cancel the
operator's manual orders elsewhere on the same API key. Exact request-field name
is `[U]` until the schema is read: OQ-12.

**Goal.** Resolve OQ-1. No-body canonical string correct → 200. Body participates
→ **401 on 100 % of submissions** (B-2 #1 `[E]`), surfaced for one no-op request.

**Preconditions, all hard.** D1 satisfied (`PREREQ:211` `[E]`); operator present;
the permit's endpoint scope names **only** cancel-all; `GET /v1/orders/open`
returns zero orders **for that slug** immediately before the probe; firewall
lifted deliberately for this run only, out of CI; permit at the minimum ceiling;
`manualOrderIndicator` explicit. Run under `scripts/venue/` (venue-touching by
path, C2, `readonly_guard.py:128-131` `[V]`). Documented no-body variant first;
on 401 one retry with the body-hash variant — **two requests maximum** — with
status, headers and the redacted canonical-string shape digest-signed into
`docs/evidence/venue/polymarket_us/`.

**Branch.** No-body works → keep the default, close OQ-1. Body required →
`exec/signing.py`'s variant flips and every downstream request construction is
re-verified. Both 401 → **stop**; OQ-1 escalates and E-10..E-14 do not proceed.

---

### E-10 — Preview probe: mutation, direction confirmation, precision · **[SEND — operator-gated]**

**Goal.** Extend the allowlist by **exactly one entry** — `POST /v1/order/preview`
— and the permit's operator-set scope likewise, then resolve with zero intended
capital at risk. **Preview dispatches under its own `PreviewAuthorization`**
(§6.3.1): revision 2 assigned it no authority at all, which is the concrete
instance R2-BL-4 named — an unassigned dispatch takes whichever type is nearest,
and the nearest was the non-decrementing one whose scope reaches `POST /v1/orders`.

- **OQ-2** — is preview non-mutating? `[U]`. Measured by an immediately following
  `GET /v1/orders/open` + `GET /v1/portfolio/positions`, both unchanged.
  **`POLYMARKET_US_BUILD_PLAN.md:20` permits preview only on venue/operator
  confirmation, which does not exist on disk** (`PREREQ:162-165` `[E]`) — so this
  is **operator-gated**, not merely operator-run.
- **OQ-3 — direction confirmation, now with the right hypothesis.** E-7 fixed the
  mapping; preview's expected-fill response **confirms** it. The question is no
  longer "does `1.00 − X` work" (it never fires) but "does a
  `(BUY, YES, price=0.30)` request preview as a buy of the YES side at 0.30". The
  documented precedence is `outcomeSide`+`action` (`overview:114` `[V]`); what is
  unverified is enforcement.
- **Tick alignment and absolute bounds** — `orderPriceMinTickSize` per market,
  never a global constant (REQ-VENUE-06), plus E-5's [0.01, 0.99] guard confirmed
  against preview's response.

**Branch.** Preview mutates → the allowlist entry and the permit scope entry are
**reverted**, OQ-2 closes NEGATIVE, and OQ-3 falls through to E-14's single-order
probe at the minimum tradable size. That fallback is more expensive and is not
silently adopted.

---

### E-11 — Ambiguity: the latch, the invariant, and the framework · **[NO-SEND — no new endpoint]**

**The problem (B-1 `[HARD BLOCK]` `[E]`).**
`grep -niE "clordid|clientorderid|client_order_id|idempot"` over the retail
create-order snapshot returns **nothing**; `CreateOrderResponse` carries only `id`
and `executions` (N-4 `[V]`). The institutional `insert-order` schema *does* carry
`clordId` (`api-reference_trading_insert-order_2026-08-25.md:63` `[E]`) but the
operator decision is **retail** (`POLYMARKET_US_BUILD_PLAN.md:18` `[E]`). Compose
with the 5-second stopgap — rejects carrying `Global Rate Limit Exceeded` plus
*"You do not need to throttle your traffic in response to them"*
(`rate-limits:48-56` `[V]`) — and **a naive retry is a double position with no
venue-side dedup.**

**Design — never a resubmit.** *"Never resubmit" was preserved by all four lenses,
with one required split, adopted below as (2).*

1. **One in flight per `marketSlug`, enforced locally.** The mechanism replacing
   the missing idempotency key: with at most one outstanding submit per market, an
   unmatched venue order in that market is unambiguously ours. `[I]` — the
   load-bearing choice; attack it here.
   **HIGH — the write-ahead ordering, now stated.** The in-flight mark is
   committed to `SqliteStateStore` and **fsynced before the request leaves the
   process**, never after and never concurrently: a mark written after dispatch
   loses exactly the crash window it exists to cover. There are now two durable
   stores with different backends — the Nautilus cache on Redis (E-2) and the
   latch on SQLite — and on disagreement after a restart **the latch is
   authoritative**. The reason is asymmetric and structural: the cache can be
   cleared by `_resolve_inflight_order` fabricating a rejection
   (`live/execution_engine.py:766-795` `[V]`, BL-13), while nothing clears the
   latch but an explicit resolution. A cache that says "flat" and a latch that says
   "in flight" resolves to **in flight**, every time.
2. **Split the ambiguity by kind (review requirement).** An **acknowledged venue
   reject** is terminal and carries no double-position risk — it resolves
   immediately and does not latch. Only a **transport timeout or unclassifiable
   response** latches `SUBMIT_AMBIGUOUS`, permitting read / status / cancel /
   reconciliation work only (REQ-EXEC-07, `TRADING_ENABLEMENT_PLAN.md:146` `[V]`).
3. **HIGH — resolve with the venue's own pre-ack cancel, which is not a resubmit.**
   `rate-limits:58,60` `[V]`: *"Pure cancels are not affected — a standalone cancel
   is never rejected by this stopgap"* and *"You can always cancel an order before
   you have received an acknowledgement, and even before it has been processed."*
   A **market-scoped cancel-all** — allowlisted since E-8 — therefore **bounds** the
   ambiguity: whatever the submit did, the market is flat afterwards. Revision 1
   converted a venue-supported bounded resolution into an unbounded human page.
   Corrected.
4. **HIGH — the read ladder is reordered.** Revision 1 led with
   `GET /v1/orders/open`, which is **structurally empty for IOC**, and all three
   registrable strategies submit IOC (`forecast_revision/strategy.py:368` `[V]` and
   siblings). It then fell to `/v1/portfolio/activities`, whose mapper refuses
   until E-14 — **after** exposure opens at E-12. The ladder now leads with the
   **position and balance delta**, both E-4-verified GETs with mappers proven at
   E-3/E-4, then `GET /v1/order/{orderId}` when an `id` was returned, then
   open-orders, then activities.
5. **BL-13 — intercept Nautilus's synthetic rejection.**
   `live/execution_engine.py:736-751` → `_resolve_inflight_order` (`:766-795`)
   `[V]`: after `inflight_check_retries` (default **5**, `live/config.py:186` `[V]`)
   the engine fabricates `OrderRejected(reason="UNKNOWN")` for a `SUBMITTED` order,
   marking the cache REJECTED and flat while the venue may still hold it — roughly
   15-25 s after an ambiguous submit. E-11's latch stops *Breezy* resubmitting and
   does nothing about the **framework** clearing state, and Nautilus's version is
   what the risk engine and portfolio read. **Fix:** pin `inflight_check_retries`
   and `inflight_check_threshold_ms` explicitly in E-4, and treat a synthetic
   `UNKNOWN` rejection **on a latched market as a latch TRIGGER, never a
   resolution** — the cache going flat is evidence to distrust, not evidence to act
   on.
6. **HIGH — submit timeout pinned above the stopgap.** A 3 s client timeout
   manufactures the very ambiguity this increment exists to handle, for an order
   the venue will itself reject at 5 s (`rate-limits:48-52` `[V]`). The submit
   timeout is pinned **above** 5 s (proposed 8 s) and asserted; `maxBlockTime` and
   `synchronousExecution` remain unused (OQ-6).
7. **If the ladder plus the scoped cancel cannot uniquely resolve, the latch stays
   set and escalates.** It never times out into "probably fine".
8. **Fail-closed halt reads, two-directional (HIGH, §6.4).** Any exception,
   timeout or absent row resolves to **`HALT_NEW_EXPOSURE`** — submit, reduce-only
   and preview refuse — and **cancellation still dispatches**. Revision 2's
   `HALT_ALL_DISPATCH` contradicted "read / status / cancel always permitted" and
   would have disarmed the only control that reduces exposure on a venue with no
   stop-out, turning a storage fault into an unmanageable live position. There is
   no state in this system in which a cancel is denied.
9. **Thread ownership** (arch §8.6; REQ-RISK-02 / REQ-EXEC-09): the halt store used
   by egress is constructed **on the event-loop thread egress dispatches from**,
   with a startup assertion pinning the owning thread identity — `SqliteStateStore`
   confinement is to the CONSTRUCTING thread (`sqlite_store.py:101-104` `[E]`).

**RED first.** (i) A timed-out submit latches; a second submit for the same market
is refused by name. (ii) An **acknowledged reject** does **not** latch. (iii) A
static test that no code path resubmits a create-order. (iv) A synthetic
`OrderRejected(reason="UNKNOWN")` on a latched market **triggers** the latch rather
than clearing it. (v) The ladder resolves an IOC ambiguity **without** consulting
open-orders. (vi) An unreadable latch store resolves to `HALT_NEW_EXPOSURE` **and a cancel
still dispatches** — both halves asserted in one test. (vi-b) The in-flight mark
is durable **before** the transport is called, asserted by a recording transport
that reads the store at dispatch time. (vi-c) A cache saying flat and a latch
saying in-flight resolves to in-flight after a restart. (vi-d) A response
classified AMBIGUOUS by E-3's table latches and is **never** retried. (vii) A latch call
from a foreign thread fails. (viii) The submit timeout is greater than 5 s.

---

### E-12 — `POST /v1/orders` and `_submit_order` · **[SEND — EXPOSURE-OPENING]**

> **First commit at which Breezy can open a position.** Gated on D2 funding, D3,
> D4, D5, `BREEZY_TRADING_OPERATOR_ID`, the new endpoint-scope variable of E-1, a
> **durable** session budget ledger (§6.4), a running Redis-backed cache (E-2) with E-4's staleness fence, and
> a real-money approval artifact — **none of which exist today**
> (`PREREQ:209-218` `[E]`).

**Goal.** Allowlist and permit scope each grow by **exactly one**. `_submit_order`
translates `SubmitOrder` → `CreateOrderRequest` → egress → `generate_order_submitted`
→ venue events. `_submit_order_list` continues to refuse.

| Field | Value | Cite |
|---|---|---|
| `marketSlug` | from `InstrumentId` via `symbology.py` | the only required field, `create-order:60-63` `[V]` |
| `type` | `ORDER_TYPE_LIMIT` **always** | F-4 forbids MARKET |
| `intent` / `outcomeSide` / `action` / `price.value` | **from `exec/direction.py`'s two-row total map** (E-7.3); `price.value` unmodified | `overview:114,141-158` `[V]`; N-9 `[V]` |
| `quantity` | pre-aligned to `minimumTradeQty`; decimals permitted | `create-order:73-79` `[V]`; OQ-5 |
| `tif` | IOC or FOK only | E-5 resting-TIF refusal |
| `participateDontInitiate` | **never true** | N-5 `[V]`; B-3 `[E]` |
| `manualOrderIndicator` | `MANUAL_ORDER_INDICATOR_AUTOMATIC`, required, explicit | `overview:230-237` `[V]`; chokepoint refuses `None` (`safety.py:674-675` `[V]`) |
| `synchronousExecution` | **false** | N-4 `[V]`; OQ-6 |
| price bounds | within **[0.01, 0.99]** before dispatch | `overview:162,164` `[V]` |

**Precision.** Every `Price`/`Quantity` pre-validated **before** construction:
Rust panics SIGABRT rather than raising (REQ-EXEC-06,
`TRADING_ENABLEMENT_PLAN.md:145` `[V]`).

**RED first.** (i) The exhaustive direction test of E-7.3 re-run against the
**serialised body**, asserting `price.value` is unmodified for both sides.
(ii) An off-tick or out-of-bounds price is refused before construction.
(iii) A submit while the latch is set is refused. (iv) A submit with no cached
account, a zero cap, or a non-USD balance is refused (E-5 regression over F-1,
F-3, F-5). (v) `order_notional_usd` passed to `consume` equals the value
recoverable from the **transmitted body bytes** (§4.5). (vi) The full path from
`Strategy.submit_order` to `generate_order_submitted` runs against a recording
transport with **zero** real network calls. (vii) The session ledger survives a
process restart with the spent budget still spent (§6.4).

**Completion.** **G2** met in the machinery; not yet demonstrated live (E-14).

---

### E-13 — Cancel · **[SEND]**

Allowlist and permit scope grow by **exactly one**: `POST /v1/order/{id}/cancel`
(`resources/orders.py:47` `[V]`). `_cancel_order` and `_cancel_all_orders`
implemented on the **non-decrementing** cancellation authority (BL-12);
`_modify_order` and `_batch_cancel_orders` continue to **refuse** — modify
semantics rest on a demonstrably drifted SDK snapshot alone (B-2 #7 `[E]`: six
order-endpoint doc pages and the entire private-WebSocket page were never
captured). Cancel is retried through `RetryManagerPool` — idempotent in effect,
unlike submit, and now unable to exhaust the permit. REQ-RISK-08's kill switch
gains teeth: read / status / cancel always permitted; submit / replace / increase
require the kill switch clear **and** D4 set **and** the endpoint on the permit's
operator-set scope.

---

### E-14 — Single-order live probe and enablement · **[SEND — real money]**

One order, **minimum tradable size**, at a price inside [0.01, 0.99] that will not
fill immediately, then a scoped cancel. Captures the fill payload shape (**never
observed** — B-2 #6 `[E]`, so E-3's fill mapper is still refusing per record until
this lands), commission parsing, `price_scale` / `fractional_quantity_scale`
decoding, and the naked-short question (OQ-10, unknowable read-only,
operator-gated). **Minimum tradable size is `minimumTradeQty`, which is `0.01` on
729/729 weather markets** — see OQ-5: revision 1's "conservative" whole-contract
fallback would have made this probe **100× larger** than necessary on the very
increment whose purpose is minimising first-send risk. Evidence digest-signed into
`docs/evidence/venue/polymarket_us/`. Tier-1 enablement follows as a separate
operator decision outside this plan.

---

## 8. The unknown-resolution track

Unknowns are never silently assumed away.

| ID | Unknown | Class | Resolved by | If it does not resolve |
|---|---|---|---|---|
| **OQ-1** | Does the POST body participate in the Ed25519 canonical string? (B-2 #1 `[E]`) | **live probe, scoped no-op** | E-9 | E-10..E-14 do not proceed; 100 % of submissions would 401 |
| **OQ-2** | Is `POST /v1/order/preview` non-mutating? (B-2 #2 `[E]`) | **operator-gated live probe** | E-10 | allowlist + permit-scope entries reverted; OQ-3 falls through to E-14 |
| **OQ-3** | Does the venue **enforce** the documented `outcomeSide`+`action` precedence? | **read-mostly**: preview echo | E-10 | E-12 proceeds only at minimum size with immediate position read-back |
| **OQ-4** | Do `Price(0.00)` / `Price(1.00)` survive fill validation? (`AUDIT:176-179` `[E]`) | **local RED** | E-6 | settle at the nearest representable tick and **report the residual as a named error**; never a silent clamp |
| **OQ-5** | Fractional quantities | **ALREADY ANSWERED ON DISK — closed** | — | — |
| **OQ-6** | Should `synchronousExecution` collapse submit ambiguity? (N-4 `[V]`) | **deferred, then live** | after E-14 | default `false`; it interacts with the 5 s stopgap and *lengthens* the unknown window |
| **OQ-7** | Field names / units on `GetAccountBalancesResponse` | **read-only** | E-4, from a captured authenticated GET | `_connect` fails closed; the client does not start |
| **OQ-8** | Is `/v1/portfolio/activities` the fill source, and its schema? | **read-only** | E-3/E-4 | the fill mapper refuses **per record** until E-14; the other two report types are unaffected (BL-16) |
| **OQ-9** | The egress/data split of the 20 req/s key-wide budget (B-4 `[E]`) | **measurement** | E-9/E-10; data path currently claims 15 rps (`transport.py:122` `[V]`) | egress bucket set to the smallest workable value; the data share is reserved. Starving the tape mid-position is a named failure mode, not an accepted cost |
| **OQ-10** | Naked-short acceptance (B-2 #4 `[E]`) | **unknowable read-only, operator-gated** | E-14 at the earliest | `allow_short=False` stands; nothing depends on it |
| **OQ-11** | Is `base_currency=USD` strictly safer than `None` given F-5? | **local test** | E-4 | `None` + the F-5 identity check ships; revisit if the venue reports multiple currencies |
| **OQ-12** | The exact market-scoping field name on `CancelAllOrdersParams` | **read-only** | E-8, from the SDK type + OpenAPI | E-9 does not run: an unscoped cancel-all could cancel the operator's manual orders on the same key |
| **OQ-13** | Modify / batch-cancel / private-WebSocket semantics (B-2 #7 `[E]`) | **DEFERRED — out of scope** | not in this plan | `_modify_order` and `_batch_cancel_orders` refuse permanently |
| **OQ-14** | **RE-OPENED (R2-BL-3).** Bodies of `calculate_reconciliation_price` / `create_inferred_reconciliation_trade_id` (Rust, unreadable) | **read-only, by behavioural probe** | **E-6** | Revision 2 deferred these on the grounds that the report path made them irrelevant. That is **inverted**: moving to the report path made the *trade-id* half MORE relevant, because dedup is by `TradeId` alone (N-16 `[V]`) and Breezy now fabricates one. Breezy's own deterministic id (E-6 item 3) does not depend on the Rust body, but a **collision** with a natively-inferred id would be silent, so E-6 probes the native id's shape for the same instrument and asserts the two are distinguishable. If unresolvable, the `SETTLE-` prefix stands as the collision guard and the residual is recorded |
| **OQ-15** | Whether any raw capture contains `MARKET_STATE_SETTLED` / `_CLOSED` | **read-only, archive scan** | E-6 | the two undocumented states are removed from `EXPIRED_MARKET_STATES` and `MARKET_STATE_TERMINATED` is added (§11 D-4) |
| **OQ-16** | **Does `GET /v1/markets/{slug}/settlement` EVER return 200 for a weather bucket?** Unresolved: **0/5 captures**, all `{"code":5,"message":"Settlement not found …"}` (N-15 `[V]`) | **read-only, observation over time** | opportunistically, from E-3's polling once a bucket resolves in production | the endpoint stays SECONDARY permanently, its 404 stays the expected response, and TIER_1 remains the only source. Nothing depends on it resolving; it is tracked so that a future 200 is noticed rather than assumed |
| **OQ-17** | Which field of the venue `PositionStatusReport` payload carries **average entry price**, needed by E-4's staleness fence | **read-only** | E-4, from a captured authenticated GET | the fence compares quantity **and** an explicitly-named absent field, and `_assert_reconciled` halts on absence rather than degrading to a quantity-only comparison |

**OQ-5 is CLOSED, and the review is right that it changes E-14.** Revision 1
weighed only two non-normative sources and adopted whole contracts as
"conservative". The **normative** OpenAPI on disk says `quantity: type: number,
format: double`, *"Supports decimal quantities on markets whose minimumTradeQty is
less than 1"* (`api-reference_orders_create-order_2026-08-25.md:73-79` `[V]`), and
`minimumTradeQty = 0.01` holds on 729/729 weather markets (`PREREQ:177-179` `[E]`).
`learn_trading_basics_fractional-shares:9,30` is a retail-education page and loses
to the API schema. **Consequence:** E-14's first live order is 100× smaller than
revision 1 would have made it — a "conservative" default that was conservative
about the wrong quantity.

**Operator-gated, not agent-decidable:** D2 funding, D3, D4, D5,
`BREEZY_TRADING_OPERATOR_ID`, the E-1 endpoint-scope variable, OQ-2's preview
permission, OQ-10, and the real-money approval artifact. All are **NO** today
except D1 (`PREREQ:209-218` `[E]`). No increment sets them; shipped code cannot
(`test_polymarket_us_permit_issuance.py:1324-1387` `[V]`).

---

## 9. Risk register

| # | Risk | Sev | Mitigation | The test that proves it |
|---|---|---|---|---|
| **R-0** | **The walk completes and there is no process to run any of it** (R2-BL-1) | **CRITICAL** | **E-2** builds the trading process before the components that need it; §1.0's container check is run explicitly, per artifact | E-2 RED (iii) + E-7 RED (ii): a `QuoteTick` reaches `on_quote_tick` in the node the entry point builds, and RED (ii-b) fails if `data_clients` is empty |
| **R-1** | The walk completes and the bot still cannot trade (BL-1) | **CRITICAL** | E-7 registers a source; §1's walk names what each increment adds | E-7 RED (ii): a real order reaches `_submit_order` offline |
| **R-2** | The registered strategy is denied 100 % of the time while looking healthy (BL-2) | **CRITICAL** | E-7 removes the MARKET arm and bans the config flag; only IOC LIMIT strategies are registrable | E-7 RED (v) + the no-`order_factory.market(` static test |
| **R-3** | A wrong-side fill — up to 49× the intended leg at a 0.02 limit (BL-3) | **CRITICAL** | `exec/direction.py` is total over `OrderSide`; the `1.00 − X` inversion is **not implemented** and is AST-banned | E-7 RED (iii)+(iv), and E-12 RED (i) against the serialised body |
| **R-4** | Settlement cannot execute; PnL never books (BL-4/BL-5) | **CRITICAL** | report path + the venue settlement endpoint | E-6 RED (i) `InvalidStateTrigger`; RED (ii) native path books zero |
| **R-5** | An exec file lands before the E0 rule, or N2 reports instead of stopping (A-1, BL-9) | **CRITICAL** | E-0 first; rule moved into `pytest_configure` | E-0 RED (iii): a child pytest never reaches collection |
| **R-6** | Five native fail-opens silently bypass every risk check | **CRITICAL** | E-5 denies before Nautilus; §0.4 F-table | E-5 RED (i): a 1000× order **passes** with Breezy's denial removed |
| **R-7** | A retry after an ambiguous submit creates a double position (B-1) | **CRITICAL** | latch, one-in-flight, **never resubmit**, plus the venue's pre-ack cancel to bound it | E-11 RED (iii): no code path resubmits |
| **R-8** | The operator's daily budget is reset every 15 min — ≈32×/day (BL-7) | **CRITICAL** | session ledger with carry-forward; durable before E-12 | E-1 RED (2); E-12 RED (vii) across a restart |
| **R-9** | cancel-only → exposure-opening with zero operator act (BL-8) | **CRITICAL** | operator-set endpoint scope hashed into the permit | E-1 RED (3); E-8 RED (iv) |
| **R-10** | One capability authorises any body (BL-10) | **CRITICAL** | one named `request_fingerprint(method, path, body_bytes)`; AST ban | E-1 RED (4): one-byte body mutation raises |
| **R-11** | Crash holding a position → restart with zero knowledge of exposure (BL-14) | **CRITICAL** | Redis-backed cache, `flush_on_start=False`; hard prerequisite of E-12 | E-4 RED (g) |
| **R-12** | `AccountId` unset → warning, no account, F-1 restored (BL-15) | **CRITICAL** | `_set_account_id` first; assert the account is in cache | E-4 RED (a)+(b) |
| **R-13** | A refusing fill mapper stops the trader entirely (BL-16) | **HIGH** | refuse per RECORD | E-3 RED (ii) |
| **R-14** | Reconciliation "SUCCEEDED" no longer implies matched (BL-6) | **HIGH** | Breezy-owned match assertion in `_assert_reconciled` | E-4 RED (f) asserts the halt |
| **R-15** | Nautilus fabricates `OrderRejected(UNKNOWN)` and the cache goes flat (BL-13) | **HIGH** | pin the retries/threshold; treat it as a latch TRIGGER | E-11 RED (iv) |
| **R-16** | Cancels burn the operator's budget; a retry storm disarms the kill switch (BL-12) | **HIGH** | separate non-decrementing cancellation authority | E-8 RED (vi) |
| **R-17** | A zero cap passes the presence check and leaves an instrument uncapped (BL-11 / F-3) | **HIGH** | four-part guard; unquoted instruments not registered | E-5 F-3 proof-by-construction |
| **R-18** | A non-USD balance reproduces F-1 with a valid account (F-5) | **HIGH** | currency identity at emission; `_connect` fails closed | E-4 RED (c) |
| **R-19** | An out-of-bounds price returns an orderID, never fills, and holds the bucket | **HIGH** | `PriceOutOfVenueBoundsError`, REDs at 0.005/0.995 | E-5 |
| **R-20** | A GTC limit rests and fills as maker — fee wrong in **sign** (B-3) | **HIGH** | refuse any resting TIF at the boundary | E-5 `RestingTimeInForceRefusedError` |
| **R-21** | E-9 closes OQ-1 falsely on an empty body | **HIGH** | non-empty **scoped** body | E-9 preconditions; OQ-12 gates the run |
| **R-22** | A 3 s client timeout manufactures ambiguity the venue would have rejected at 5 s | **HIGH** | timeout pinned above the stopgap | E-11 RED (viii) |
| **R-23** | A voided (`TERMINATED`) market books a 100 % loss on refunded capital, into an append-only archive (N-12) | **HIGH** | `TERMINATED` is a distinct terminal state routed to `VoidedMarketError`-halt, never priced 0/1 | E-6 RED (iv) |
| **R-24** | Egress starves the quote tape (B-4) | **HIGH** | reserved data share; `HALT_NEW_EXPOSURE` on exhaustion | E-8: egress cannot consume the reserved key |
| **R-25** | A barrier is weakened rather than narrowed (A-3) | **HIGH** | equality pins on all nine rule constants; every narrowing paired in-commit | `test_cage_rule_constants_are_pinned.py` |
| **R-26** | `issue_live_trading_permit` self-issued from any module (N-11a) | **HIGH** | B6a treatment + removal from `__all__` | E-1 RED (6) |
| **R-27** | The YES-denomination assumption of E-7.4 is wrong `[I]` | **HIGH** | pinned against a captured `(market, book)` pair; E-7 stops if it fails | E-7 RED (vi) |
| **R-28** | An exec test marked `allow_socket`/`live`/`venue_live`/`real_money` restores real pyo3 clients (A-4 #7) | **MEDIUM** | static ban | E-1 RED (9) |
| **R-29** | `_query_account` undefined → `AttributeError` swallowed (N-6) | **MEDIUM** | defined explicitly | E-4 RED (e) |
| **R-30** | `consume()` accepts a lying `Decimal` subclass at any magnitude (A-2) | **MEDIUM** | type-exactness mirroring `safety.py:676` | E-1 RED (1) |
| **R-31** | native `equity()` silently substituted once E-4 makes it non-zero (L-2, §4.3) | **MEDIUM** | named as a behaviour change; static ban in strategy/sizing | E-5 RED (iii) |
| **R-32** | **Every settlement poll re-applies the fill: flat → short 100 → short 200, +$70/cycle of phantom PnL into an append-only archive** (R2-BL-3) | **CRITICAL** | `(VenueOrderId, TradeId)` are pure functions of `(slug, settlementSetTime, settlementPx)`; dedup is by `TradeId` alone (N-16) | E-6 RED (ii-a): three emissions and a restart book one fill |
| **R-33** | **The settlement fill lands on `INSTR-EXTERNAL`: the long never closes and a phantom short appears** (R2-BL-5) | **CRITICAL** | `external_order_claims` on the registered strategy; `filter_unclaimed_external_orders=False` pinned | E-6 RED (ii-b): same `PositionId` as the entry |
| **R-34** | **A cancellation authority mints a capability for `POST /v1/orders` — D3 and D5 bypassed, nothing decremented, repeatable** (R2-BL-4) | **CRITICAL** | four distinct frozen types, `type(auth) is X`, disjoint endpoint frozensets, permit scope necessary but never sufficient | E-1 REDs (6b): refused at mint and again at dispatch |
| **R-35** | **Settlement prices are read from an endpoint that has never returned 200, so nothing ever settles** (R2-BL-2) | **CRITICAL** | primary is `stats.settlementPx` gated on TIER_1 + `settlementSetTime` + `closePx` absent; endpoint is secondary with 404 expected | E-6 RED (ii-c)/(ii-d) against the N-15 captures |
| **R-36** | A settlement never arrives from **any** source and the position silently looks unsettled forever | **HIGH** | `SettlementOverdueError` watchdog past `expiration_ns` | E-6 RED (ii-f) |
| **R-37** | `RetryManagerPool` is wired but never fires on the venue's own 429/503; ambiguity handling has no classifier (N-18) | **HIGH** | classification table as data in `exec/endpoints.py`; typed exceptions = the pool's `exc_types`, pinned equal | E-3 RED (ii-b); E-8's set-equality test |
| **R-38** | Redis dies mid-session; restart loads a **stale** cache that reconciles CLEAN and corrupts G3 | **HIGH** | monotonic session sequence; `_assert_reconciled` compares entry price and quantity; reconcile-or-halt; a kill-Redis drill | E-4 RED (h)+(i) |
| **R-39** | An unreadable latch store halts **cancellation**, leaving a live position unmanageable | **HIGH** | two-directional fail-closed: `HALT_NEW_EXPOSURE`, cancel always permitted | E-11 RED (vi) asserts both halves |
| **R-40** | A permit scoped to cancel-all authorises submission because the paths **nest** (`/v1/orders` prefixes `/v1/orders/open/cancel`) | **HIGH** | exact `(method, template)` pairs; `startswith`/`in`/regex banned in scope comparison | E-1 RED (6c) against the venue's real paths |
| **R-41** | The issuer barrier is written `<= 1` because `== 1` is unsatisfiable at E-1, and passes while dead | **HIGH** | `== 0` at E-1 with an empty declared allowlist, `== 1` at E-4 | E-1 and E-4 each prove the neighbouring counts fail |
| **R-42** | `cost_cap` derived at load from a stale price admits 10× the contracts at 0.05 | **HIGH** | the conversion is **deleted**; premium ceilings pass through unconverted, less a flat fee reserve | §4.2; E-5 AST scan banning cap × price |
| **R-43** | E-7.4's YES-denomination RED is GREEN under both hypotheses and proves nothing | **HIGH** | independent oracle `stats.lastPriceSample.longPx`, on a fixture materially off 0.50 (N-21) | E-7 RED (vi) |

---

## 10. Non-goals

1. **Short-side support.** `allow_short=False` stays (`risk.py:83` `[V]`). The bid
   side cannot support a stop-out — median top-of-book bid is 0.3 contracts — and
   `CashAccount.balance_impact` **credits** a SELL (`NT/accounting/accounts/cash.pyx:482-495`,
   H-6 `[E]`), so the native cash check is wrong **directionally** for a short
   binary. A real control, not a formality.
2. **Maker / post-only strategies — now enforced, not merely declared.** The maker
   coefficient is **−0.0125, a rebate**, while Breezy charges taker on both sides:
   at C=100, p=0.50 the venue **pays** $0.3125 and the model **charges** $1.50 —
   wrong by $1.8125 and wrong in **sign** (B-3 `[E]`). Revision 1 asserted this
   non-goal while enforcing it only against `post_only`, which does not stop a GTC
   limit resting. E-5 refuses **any resting time-in-force**, which makes
   `resting_ladder.py` structurally unregistrable rather than merely discouraged.
3. **`SandboxExecutionClient` / Nautilus paper mode.** Banned: it constructs
   `SimulatedExchange` directly with a hardcoded `MakerTakerFeeModel`
   (`NT/adapters/sandbox/execution.py:109-124` `[E]`) → 50× fee overstatement at
   p=0.98 with unbounded relative error `1/(1−p)`, plus `LatencyModel(0)`.
   Simultaneously too pessimistic on cost and too optimistic on fill (arch §9.1).
4. **Order modify.** `_modify_order` refuses permanently (B-2 #7 `[E]`).
   Cancel-and-resubmit is not offered either: it reopens B-1.
5. **Batch / order-list submission.** `_submit_order_list` and
   `_batch_cancel_orders` refuse; batched semantics unverified.
6. **`ExecAlgorithm`s, permanently.** `exec_algorithms=[]` stays empty at **all
   three** node-config sites, including the one E-2 creates. An `ExecAlgorithm`
   reaches `submit_order` in its own right (`node_config.py:213-217` `[V]`), so
   enabling one would open a second order source outside E-7's single registered
   strategy.
7. **The institutional DMA surface** (`insert-order`, `clordId`). The operator
   decision is retail (`POLYMARKET_US_BUILD_PLAN.md:18` `[E]`). Its idempotency key
   is exactly what would solve B-1 and it is out of reach — saying so is part of
   this plan, because a reviewer will ask.
8. **Kalshi portability.** Venue-specific by construction; the *seams* (report
   mappers, denial layer, direction map, settlement exit) are portable. Nothing is
   generalised speculatively (YAGNI; CLAUDE.md Engineering Priority 5).
9. **Deterministic client order IDs.** Deleted as a design, not deferred: the
   retail schema has no field to carry one (B-1 `[E]`; N-4 `[V]`), so
   `ClientOrderId` stays Nautilus-local and the venue cannot reject the duplicate.
10. **A Breezy-authored retry/backoff, state machine, or position ledger.**
    `RetryManagerPool` is wired (`NT/live/retry.py:242` `[V]`); the native state
    machine is obeyed, including N-10's missing `FILLED →` transition.
11. **Re-planning `DATA_CAPTURE_AND_RISK_PLAN.md`.** Its P0-P7 sequence is
    unchanged. Hard dependencies: **P5-fix** (`allow_short=False` correct before
    E-5) and **§2.3** (the unit).
12. **A fourth process, or a shared process framework.** E-2 is the third instance
    of an existing shape (settings loader + node-config builder + CLI + entry
    point), not a generalisation over three cases. No abstraction is extracted from
    them; three concrete builders that read clearly beat one parameterised builder
    whose read-only guarantees depend on its arguments (YAGNI, and the cage is
    easier to assert per site — §6.2).
13. **Trading inside the ingest or quote-tape process.** Both keep all four
    literals at their current values forever, pinned per site. The tape's value is
    that it keeps recording when trading halts.

---

## 11. Corrections this plan requires

Correction is part of the increment named, not a follow-up.

### 11.1 Documents

| Stale claim | Where | Refuted by | In |
|---|---|---|---|
| "Retries reuse the deterministic client order ID of §7.3" | `TRADING_SYSTEM_ARCHITECTURE.md:1375` `[V]`, and §7.3's "so a retry is a duplicate the venue rejects" `:1196` `[V]` | B-1 `[E]`; N-4 `[V]` | **E-11** |
| "no documented precedence for `intent` vs `outcomeSide`+`action`" | `SKILL.md:153,248,306`; `TRADING_ENABLEMENT_PLAN.md:90` `[E]` | `overview:114` `[V]` | **E-10** |
| `manualOrderIndicator` is "bool \| Rare" | `SKILL.md:151` `[E]` | required string enum, `overview:230-237` `[V]` | **E-12** |
| REQ-VENUE-04 G2 "order endpoints undocumented" | `TRADING_ENABLEMENT_PLAN.md:89` `[V]` | 11 endpoints + 2 OpenAPI schemas on disk `[E]` | **E-3** |
| REQ-VENUE-06 G4 "tick/minQty never observed" | `TRADING_ENABLEMENT_PLAN.md:91` `[V]` | 729/729 raw market objects `[E]` | **E-3** |
| drifted line refs for chokepoint / B6b / B3 | `TRADING_SYSTEM_ARCHITECTURE.md` §8.3-8.4 `[V]` | `safety.py:32`→`:626`; `readonly_guard.py:533`→`:550`; `transport.py:105-124`→`:129-148,325` `[E]` | **E-1** |
| §8.0 "reduces to effectively one enforced chain" | `TRADING_SYSTEM_ARCHITECTURE.md:1241-1251` `[V]` | true of the chain, but §5/§6 add per-file structural pairs and **three** chokepoints it did not contemplate | **E-8** |
| arch N9 (dry-run stub egress) | `TRADING_SYSTEM_ARCHITECTURE.md` §8.3 `[V]` | superseded by structure — retired **by name**, §6.2 | **E-1** |
| "fee_schedule_status is UNKNOWN" | `docs/evidence/roi_feasibility_2026-08-26.md:72-80` `[E]` | `parsing.py:477-489,1183-1195`. **Append-only regime — re-date, do NOT edit.** | **E-4** |

`GO_LIVE_PLAN.md` Phase F is **retired** by this document: on merge, `:227-236`
gains a pointer here and its retained value collapses to operator gates D1-D5.

### 11.2 Code defects this plan must correct (not merely work around)

| ID | Defect | Cite | In |
|---|---|---|---|
| **D-1** | `consume()` compares notionals with `!=` and does not type-check (A-2) | `safety.py:463` `[V]` | E-1 |
| **D-2** | `issue_live_trading_permit` has no caller barrier and is in the package `__all__` | `adapters/polymarket_us/__init__.py:107,191` `[V]` | E-1 |
| **D-3** | N2's rule is never consulted by `conftest.py` (BL-9) | `[V]` | E-0 |
| **D-4** | `EXPIRED_MARKET_STATES` names two states the venue's enum does not contain (`SETTLED`, `CLOSED`) and omits the real second terminal state (`TERMINATED`) | `parsing.py:212-214` vs `api-reference_websocket_markets_2026-08-25.md` `[V]` | E-6, gated on OQ-15 |
| **D-5** | The MARKET arm in the three weather strategies is one config flag from a 100 %-denial bot | `forecast_revision/strategy.py:371` and siblings `[V]` | E-7 |
| **D-6** | **Breezy has no trading process.** Two `TradingNodeConfig` builders exist, one for ingest (`data_clients={}`) and one for the tape (`exec_clients={}`), and `TradingNode(` appears nowhere in `src/` | `node_config.py:163,381`; `composition.py:310`; `pyproject.toml:256,260` `[V]` | **E-2** |
| **D-7** | The node-config cage barrier quantifies over **every** call site and asserts emptiness, so it cannot express "this site may carry exactly one client" — a third builder fails it as written | `test_runtime_node_config.py:289-305, 338-349` `[V]` | E-2, per §6.2's per-site value table |
| **D-8** | `RetryManagerPool` is wired to a transport that raises only on pyo3 transport failure, so it never fires on the venue's own 429/503 | `NT/live/retry.py:101,172`; `transport.py:328-340` `[V]` | E-3 (table), E-8 (raisers) |

**Explicitly NOT to be "fixed":** `risk.py:75-78`'s "short YES is spelled buy NO"
comment (§2) — correct in context; the fix is `exec/direction.py`, not an edit
there.

---

## 12. Sequencing against the active plan

- **E-5 requires `DATA_CAPTURE_AND_RISK_PLAN.md` P5-fix** (`allow_short=False`
  correctness). E-0..E-4 do not.
- **E-2 introduces a third deployable process** (`breezy-trade`) and with it a
  Redis dependency. Both are operations-visible on the day E-2 lands, before any
  order path exists — deliberately, so the infrastructure question is answered
  while nothing can trade. It changes no existing process: `breezy` and
  `breezy-quote-tape` are byte-unchanged and pinned so.
- **E-0..E-7 are independent of P0-P7** and can run in parallel with them.
- **E-8..E-14 require the operator gates** and are enablement events, not
  agent-schedulable work.
- **E-12 additionally requires infrastructure**: a running Redis for the durable
  cache (configured at **E-2**, fenced at **E-4**) and the durable session ledger
  (§6.4). Both are named prerequisites,
  not follow-ups.
- **E-0 changes every developer's test command** repo-wide from the moment it
  lands, and from BL-9 it *aborts* rather than reddens. A coordination cost paid
  once, deliberately, at the front.

---

## 13. How to review revision 3

Per LESSONS L-3 (`:152-155`), two questions — and the second is the one that found
BL-1, then R2-BL-1.

**Read §0.2 first.** It lists four claims this document made in its own voice that
were wrong. Two of them (C-1, C-2) survived a full adversarial round because they
were asserted confidently and were cheap to check but expensive to doubt. The
right posture toward the rest of this document is the one that caught them:
**check the claim whose consequence is largest, not the claim that is easiest to
check.**

1. **Is what is written here correct?** Start at §0.3 **N-14..N-21** and §0.2's
   correction table: newest, least reviewed, and every one of them changed a
   decision. Then §4's unit lines, §6.3.1's four authority types, and §7's REDs.
2. **What is NOT here, and would its absence stop the goal?** Named thin spots, so
   the hunt starts somewhere real. **The container question first** — for every
   artifact in §5, ask what has to be running for it to execute, and check §1.0
   names the increment that builds it. That question has now failed three rounds
   running, each time one layer further out, and §1.0 is the first time it is
   answered as a table rather than asserted in a sentence.
   - **E-11's one-in-flight invariant** is still `[I]` — the load-bearing
     substitute for a protocol guarantee that does not exist. If it is wrong, R-7
     is unmitigated even with the pre-ack cancel bounding it.
   - **E-7.4's YES-denomination assumption** is `[I]` and gates the direction
     map. It has a RED, but the RED is against a captured pair, not the live venue.
   - **The fill mapper is a per-record refusal, not an implementation, until E-14.**
     Whether position-endpoint reconciliation alone is sufficient in the interim is
     `[I]`.
   - **Nothing here covers the private WebSocket.** All order/fill state is polled;
     whether polling at the reserved rate keeps `inflight_check_threshold_ms`
     honest is unmeasured and interacts with OQ-9 and BL-13.
   - **`_disconnect` with working orders is unspecified.** Whether shutdown should
     cancel-all is a policy question this plan does not answer.
   - **The session ledger is process-local until E-12.** Between E-1 and E-12 a
     restart still resets the operator's budget; no exposure-opening endpoint is
     reachable in that window, which is why it is acceptable — but it is a stated
     residual, not a closed hole.
   - **Redis is a new single point of failure.** E-4's staleness fence covers
     mid-session loss and E-2 fails closed at startup, but the fence's entry-price
     comparison depends on OQ-17, an unread field. If that field does not exist on
     the venue's position payload the fence degrades to quantity-only, which is
     exactly what it was written to replace — so OQ-17 is load-bearing and is not
     yet answered.
   - **E-6's deterministic id assumes `settlementSetTime` is stable.** Both
     resolved captures carry one (N-15 `[V]`), but if the venue ever revises it for
     the same settlement the id changes and the fill re-applies — the R2-BL-3
     failure through a different door. `settlementPx` is in the id for the
     symmetric reason. Neither is observed across a venue correction.
   - **E-2's `QuoteTick` oracle proves delivery, not correctness.** It shows a
     quote reaches `on_quote_tick` in the composed node. It does not show the
     strategy's *decision* is right; nothing in this plan does, and nothing in it
     should.
   - **Four authority types is four chances to add a fifth carelessly.** §6.3.1's
     protection is that the four endpoint frozensets are disjoint and their union
     equals the transport allowlist. A fifth type added without extending that
     equality would be invisible — the assertion is the only thing standing
     between this design and R2-BL-4 recurring.
