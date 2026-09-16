# RESTING BID HUNT — Rev 2 (2026-09-16)

**Operator ruling (verbatim, 2026-09-16):** *"I expect that the bot is autonomously hunting for edges and places order bids for
edge that is identified. if a confident edge is found, the bid should be placed so if the position reaches that threshold, it's
executed. Fully flesh out this concept and modeling, from planning through backtesting to deployment to production."*

Scope: a **maker** entry seam — rest a bid where our edge is confident and let the market come to us — as a successor family to
taker-only `pm_us_crh_cont`. Operator input stays reserved for the two caps; every constant below is build-side and PROVISIONAL
until §2 measures it.

## Changelog — Rev 1 → Rev 2 (three blind reviews merged)

| # | Verdict / source | Rev 1 defect | Rev 2 resolution |
|---|---|---|---|
| 1 | CRITICAL arch+sec | Rev 1 put a `RESTING` state in the ONE global `SubmitIntent` singleton — it cannot hold two legs | §4.4: resting intents move to a NEW durable keyed store, key `(station, climate_day, leg)`, same flock; singleton stays transient in-flight-POST serializer; `arm()` interaction rules + RED tests named |
| 2 | HIGH arch | two concurrent legs vs one-trial-per-station-day | §1.3 CANCEL trigger *sibling leg filled / station-day trial consumed*, durable under the flock **before** the sibling's fill is recorded |
| 3 | CRITICAL domain | fill proxy "ask ≤ p\* for k frames" models a CROSSED book, which §1.3/§3 call a defect | §2.1 subsection renamed **crossing-event proxy**; fill-eligible = the *transition* ask > p\* → ask ≤ p\*, one event, discounted by queue share `s`; sensitivity over `s∈{0.25,0.5,1.0}`; uncounted-fill caveat stated |
| 4 | HIGH domain | π_I estimator presented as *the* adverse-selection rate | §1.4 states it is a **lower bound**; G-R3 becomes a **precision** gate (Wilson half-width ≤ 0.08) |
| 5 | HIGH domain | G-R6 asserted a threshold with no count | §2.3 **measured now**: 27 supported station-days over **7 climate days** (09-03…09-11); consequences stated |
| 6 | HIGH arch+sec | Arm B unrunnable: `fees.py:187` raises `MakerRebateUnmodelledError` on post-only; Barrier F2 mandates that model | §4.1 maker-fee branch (Θ_maker **−0.0125**, second pinned coefficient) is a **prerequisite** of §2.2; Arm B otherwise scoped mechanics-only with fees stubbed, declared as such |
| 7 | CRITICAL domain | v5 statistic had no strata for a counterparty-triggered trial | §3.3 pre-declares time-to-fill and fill-cause (I/L) strata; primary = all fills, I-stratum + fast-fill as secondary **kill** criteria; registered before D0, never amended |
| 8 | HIGH sec | Rev 1 treated cancel as one verb; 09-04 proved only cancel-**ALL** | §4.6/§6.2: positive control exercises **both** verbs; "cancelled" retired only by a post-cancel GET open-orders read, never a bare 200, never the unverified private WS |
| 9 | MEDIUM arch | §4.4's open-orders read is barred by readonly-guard V2 with no increment | §4.3 is its own RED-first paired-barrier increment (V2 allowlist for `GET /v1/orders/open` + `GET /v1/order/{id}` + non-vacuity), sequenced **before the first rest**, fail-closed boot |
| 10 | MEDIUM sec | resting shape could be constructed before its safety state existed | §4.5 carries a **zero-call-sites** RED pin until §4.4 lands — the `write_transport.post_cancel_all` pattern |
| 11 | LOW | `resting_ladder.py` cited as production capability | §0.4 relabels it an **acceptance-harness proof**; §4.8 reworded to "a new call site to the existing `release_booking`/`true_up_booking` primitives" |
| 12 | Rev 1 factual error | Rev 1 §0.5 read `CancelOrderParams` as slug-keyed, "not keyed by order id" | Corrected from Appendix A: per-order cancel is **URL-id scoped** — `POST /v1/order/{id}/cancel`, body `{marketSlug}`, **no response body** |
| 13 | Rev 1 understated | Rev 1 treated TIF/post-only as undiscovered | Appendix A: the 09-04 probe **live-proved** GTC + `participateDontInitiate` resting, GET-enumerated, cancel-ALL'd (`CLOSED_YES_BOTH_VERBS`); only the per-order cancel verb remains unproven |

Security verdict stands: **§2 may proceed; §4's build order is as revised below.** Domain BLOCK on §3 and Arm B is addressed by
§3.3 and §4.1.

## §0 Measured facts (nothing here is assumed)

### §0.1 The live rule is a taker rule at the first executable snapshot

Edge `p_bound − (ask + fee)`, fee `θ·ask·(1−ask)` banker's-rounded to the cent (`current_rung_hold/decision.py:308-316`); `Take`
carries `limit_price`/`p_hold_lower`/`break_even`/ `rung`/`side`/`p_bound` (`:246-266`); legal-cell rule `:291-302`; window
`[12:00,17:00)` LST exclusive (`strategy.py:154-155`, refusal code `:159`, gate `continuous_strategy.py:1109`); staleness 50
min, θ 0.06, ask band [0.05,0.95], min displayed size 1, `order_quantity==1`, `allow_short=False`, `orders_enabled=False`,
`entry_only_halt=True` (`config.py:85, 226, 227-228, 229, 230, 231, 237, 234`); stations LAX/MDW/MIA/SFO (`:224`); θ read from
`instrument.maker_fee` — a *taker* number despite the name (`strategy.py:726`, `continuous_strategy.py:2214`); `p_bound` =
archive Wilson lower per cell, `n_min=90` (Appendix A); observation poll 300 s/station (`ingest/nws_observation_config.py:41`).

### §0.2 Every IOC assumption in the write path (the pins that must widen)

`unmappable_order_reason` (`adapters/polymarket_us/exec/submit_chain.py:287-328`): `:294` not LIMIT · **`:296` not
`TimeInForce.IOC` ← TIF pin** · `:298` not BUY (a SELL is a naked short) · `:305` qty ≠ 1 · `:307` price not strictly inside
(0.00,1.00) · **`:309` `is_post_only` ← post-only pin** · `:311` `is_reduce_only` · `:313` `display_qty` · **`:316` `expire_time
is not None` ← GTD pin** · `:319` `has_trigger_price`. `build_order_body` (`:331-358`) hardcodes `"tif": _TIF_IOC` (`:352`),
`"quantity": 1` (`:351`), `synchronousExecution` (`:356`), `maxBlockTime` (`:357`), emits no
`goodTillTime`/`participateDontInitiate`; key set frozen `:92`. The exit twin re-applies the same IOC pin (`:414` IOC, `:417`
SELL, `:431` `expire_time`; `exit_wiring.py:293` `reduce_only=False`).

### §0.3 No cancel call path exists, and the firewall knows it

`_cancel_order` **refuses** with a denial body — *"EXEC_SPINE R-4 has no order path…"* (`exec/client.py:3610-3624`);
`_cancel_all_orders`/`_modify_order`/`_submit_order_list`/ `_batch_cancel_orders` **raise** `NotImplementedError` (`:3626-3636`,
rationale `:3643`). **The cancel-all transport already ships, unused:** `write_transport.py:160` `post_cancel_all`,
`CANCEL_ALL_PATH=/v1/orders/open/cancel` (`:57`), `ORDERS_PATH` (`:58`) — **zero production call sites**, exactly the posture
§4.5's pin copies. Egress E3 classifies all five cancel/modify coroutines as egress surfaces
(`tests/unit/test_execution_egress_firewall_guard.py:213-227`, module set `:710`); write-verb cage
`_WRITE_METHODS`/`_WRITE_ATTRS`/`_WRITE_FUNCTIONS` (`tests/unit/test_polymarket_us_readonly_guard.py:183-202`, non-vacuity
`:991-1055`). **Readonly-guard V2 bans order-path literals outright**, so `GET /v1/orders/open` is barred today (Appendix A) —
§4.3.

### §0.4 What Nautilus already gives us (L-1 null hypothesis: it does)

`strategy/resting_ladder.py:113-393` (`BreezyRestingLadder`) rests a native GTC limit (`:206-213`), re-prices via `modify_order`
(`:253`), cancels over a deterministic `cache.orders_open` sort (`:261-278`), detects `LiquiditySide.MAKER` (`:284`), skips the
Depth10 size-0 pad via `best_order` (`:377-389`) — all under `BacktestEngine`. **It is an acceptance harness, not a production
strategy** (finding 11): sole consumer `tests/integration/test_resting_ladder_backtest.py`. Its value is evidentiary — Nautilus
natively supplies resting, re-pricing and cancellation, so **no resting-order engine, timer framework or order store may be
built.** New code = a decision, adapter shapes, a durable resting store, a cancel path.

### §0.5 Venue capability — LIVE-PROVEN vs SDK-claimed (Appendix A authoritative)

**Live-proven 2026-09-04** (`PRIVATE_write_sequence_probe_20260904T170856Z.json`, builder
`scripts/venue/polymarket_us_write_signing_probe.py:354-373`): a **GTC + `participateDontInitiate` BUY 1 @0.01 rested** (200),
**enumerated via `GET /v1/orders/open`** (200), **cancelled via `/v1/orders/open/cancel`** (200), postflight flat —
`CLOSED_YES_BOTH_VERBS`. Resting, post-only and read-back are *venue* facts; only the adapter lacks them. **Not proven:**
per-order cancel `POST /v1/order/{id}/cancel` — **URL-id scoped, body `{marketSlug}`, NO response body** (finding 12: corrects
Rev 1, which misread `CancelOrderParams` as slug-keyed). Cancel-all's `{canceledOrderIds}` is an **echo, not a confirmation**;
the private-WS ORDER channel is SDK-documented, never wire-verified; modify is cancel-replace → `REPLACED`; pure cancels are
never rate-limited.

### §0.6 Fees — the maker coefficient is a REBATE, and it blocks Arm B today

**Θ_taker = +0.06; Θ_maker = −0.0125 (a REBATE)** — `fees.py:63, 98`, `errors.py:307`, `backtest_order_guard.py:8, 213`,
`docs/evidence/ladder_ev_peer_review_2026-09-07.md:26`. `fees.py:187-196` **raises `MakerRebateUnmodelledError` on any post-only
order** — the model charges `+θ` where the venue pays `−0.0125`, so *"the fee would be wrong in SIGN. A posting strategy
backtested on it is negative by construction and unevaluable."* An incidental maker fill is priced but warned (`:198`).
**Barrier F2** (`tests/unit/test_polymarket_us_fee_guard.py:645-802`) mandates this model for every `BacktestEngine` venue. ⇒
**Arm B cannot run post-only until a correctly-signed maker branch exists** — §4.1, a prerequisite (finding 6). `Order` carries
both `commissionsBasisPoints` and `makerCommissionsBasisPoints` (`sdk_snapshot/.../types/orders.py:91-92`); `Execution` carries
`aggressor` (`:107`) and `commissionNotionalCollected` (`:108`).

### §0.7 Safety state, caps, evidence

- `SubmitIntent` is **one global record** at `CURRENT_INTENT_KEY="exec/polymarket_us/intent/current"`
  (`runtime/submit_intent.py:37`; record `:233-249`, `arm` `:388-416`, `retire` `:418`, `reconcile_at_startup` `:438`),
  `OPEN|RETIRED` only — **no accepted-and-working state**, so a resting order is an AMBIGUOUS shape forever and the account is
  serialized to one order. **Hence §4.4's separate keyed store, not a new state.** Keyed-store precedent:
  `trial_day_latch.station_day_admission` (`:1383-1420`) keys `(prefix, station, climate_day)` and takes **explicit** instrument
  ids because `StateStore` has **no key enumeration** (`:1405-1412`) — §4.4 needs an explicit index, never a scan.
- Caps/booking exist: `operator_controls.py:160`, `:173`, `order_cost_usd:230`, `SpendBooking:248`, `DailySpendLedger:263`,
  `authorize_order_cost:347` (budget check `:417-421`), `release_booking:456`, `true_up_booking:476`,
  `DailyBudgetExhausted:126`, cent round-up `:220`.
- Decisions tape `OfferTapeRecord` (`offer_tape.py:82-225`), 16 strict legacy keys (`:59`), `decision_kind:143`, exit fields
  `:150-165`, byte cap `:305`. Offline reuse: `exit_window_core.py:172-198`, `:298`, `:304`, `:402`;
  `current_rung_hold_paper_replay.py` (BacktestEngine `:39`, coverage guard `:257`, live-store guard `:384`).
- Replay settings (Appendix A): `prob_fill_on_limit=1.0` ("moot for taker-only"), `queue_position=False` — **real queue
  modelling needs `trade_execution=True`, which needs a trade tape**; `support_gtd_orders=True` UNVERIFIED; `latency_model=None`
  (known overstatement).

### §0.8 Prior art and today's evidence

**A resting bid here has already been argued dead once:** `docs/evidence/grok_no_edge_verdict_2026-09-02.md:25` — a bid on the
current rung is filled by profit-takers or an MM dumping inventory, "both adversely selected against a slower or equal
observer", and the rebate (`0.0125·0.3·0.7 ≈ $0.0026`) is wiped by one wrong-rung fill. §2 tests that verdict by measurement
instead of assuming past it. 09-16 MDW's rung asked **0.99 all afternoon**, no bid ever crossed — a taker rule sees nothing (one
day). 09-15's four takes all lost, SFO on a 300 s observation-latency race into a one-sided book: **the same 300 s is when our
bid is stale and pickable.**

## §1 Concept and model

### §1.1 Confident edge (unchanged definition, new use)

`p_bound` is the archive Wilson lower bound for the cell (`season`, `hour_lst`, `width_code`, `m_code`), `n_min = 90`, over the
same legal cells (`decision.py:291-302`). "Confident" *is* that bound.

### §1.2 The resting price

`edge(p) = p_bound − (p + fee(p))`. Because Θ_maker is a **rebate** (§0.6), a true maker fill has `fee < 0` and the edge is
*larger* than taker arithmetic implies — so **§1/§2 price the cost with the taker fee, a strict upper bound on maker cost, hence
conservative.** The rebate is never taken as credit until §4.1 pins a measured coefficient.

> **p\*** = the highest venue-tick price with `edge(p) ≥ m`, clamped to `[0.05, 0.95]`
> (`config.py:227-228`) and strictly inside (0,1) (`submit_chain.py:307`).

`m` = PROVISIONAL registered margin, initial candidate **0.03** — *not* the taker rule's `> 0`, because §1.4 shows the fill is
adversely selected; §2 calibrates it, §3 registers what §2 returns. One contract per order (`config.py:230`,
`submit_chain.py:305`). **Both legs** — YES on the current rung, NO where the NO edge exists (bound `p_miss_lower`, carried as
`Take.p_bound`, `decision.py:251-257`; NO wire price via `wire_price_for_leg`, `submit_chain.py:346`). Window only.

### §1.3 Registered decision / re-price / cancel rules

**REST** when: inside window, cell legal, observation fresh (≤ 50 min), θ matches its pin, no resting order live for this
`(station, climate_day, leg)`, no in-flight submit, and `p*` exists. Quantity 1.

**RE-PRICE** on any event changing `p_bound` or the cell (new observation, running-max change, rung change, hour_lst rollover):
recompute `p*`, and if it differs, **cancel-then-rest** — venue modify is cancel-replace → `REPLACED` (§0.5): no cheaper, harder
to reconcile. **Never re-price upward past the best ask**; a bid that would cross is the incumbent IOC family's job.

**CANCEL** immediately on: the observation killing the rung (running max out / `r_dead`); staleness past the bound; window
close; `p*` ceasing to exist; a family halt; node stop; a duplicate or unexpected open order; **and — finding 2 — the SIBLING
LEG FILLING or the station-day trial latch being consumed** (`trial_day_latch` admits one trial per station-day, so a fill on
either leg makes the other leg's bid ineligible). That cancel decision is written **durably, under the same flock, BEFORE the
sibling's fill is recorded**, so a crash between the two leaves the store saying *cancel required*, not *nothing pending* —
never best-effort, never in-memory only. Cancel is **fail-loud**: no *confirmed* cancellation (§4.6 — a GET read, not a 200)
within a PROVISIONAL 30 s escalates to cancel-all + durable family halt (§4.9).

### §1.4 Adverse selection — the estimator, and its direction of error

L-7/L-9 binds: *public info has no offer side — a resting bid is picked off exactly when the observation moves against it.* Our
bid at `p*` fills only when someone sells at `p*`: under **L (liquidity)** a non-informational seller (inventory, exit, noise)
gives `E[settle|fill,L] ≈ p_bound` so `E[pnl|fill,L] ≈ edge(p*) ≥ m > 0`; under **I (information)** the ask fell to `p*` because
the *observation* moved against the rung and we have not seen it — stale by up to 300 s — giving `E[settle|fill,I] ≪ p_bound`,
`E[pnl|fill,I] < 0`, potentially `−p*`. So `E[pnl|fill] = π_L·edge(p*) − π_I·|loss_I|`, and **the viability question is `π_I`.**

**Estimator.** A modelled fill at `t` is `I` if the next observation moves the rung's `p_bound` down by more than a PROVISIONAL
0.05 within a PROVISIONAL 600 s of `t`; else `L`. `π̂_I = #I/(#I+#L)`, Wilson interval; `Ê[pnl|fill]` from realised settlement,
never from the label.

**Finding 4 — this is a LOWER bound on adverse selection, not an estimate of it.** It misses (a) slow drift moving settlement
without a >0.05 `p_bound` step inside 600 s, (b) non-NWS information the counterparty holds (nowcasts, model runs, their own
flow), (c) cell coarseness — an unchanged `p_bound` can still contain a worsened day. True `π_I ≥ π̂_I`, so G-R3 is a
**precision** gate.

**Data:** Depth10 frames, the station observation series, the frozen archive table, settlement truth. **Absent:** trade prints
(§0.3 / §2.2). **Baseline to beat:** the IOC rule on the *same* station-days, on both `Ê[pnl|fill]` and total realised pnl.

## §2 Measurement BEFORE any venue write

No byte reaches the venue in §2.

### §2.1 Arm A — counterfactual study over existing tape

New `scripts/analysis/resting_bid_counterfactual_study.py`, composing `exit_window_core` (`:172`/`:298`/`:304`/`:402`) and
`monitor_evidence`/`monitor_records` for the row shape. For every station-day × cell where the IOC rule **would** or **did**
arm:

1. Walk Depth10 frames in window in `ts_init` order; maintain `p_bound`, cell and staleness from the observation series with the
   **real 300 s poll lag**, never hindsight. Compute `p*` per §1.2 at each frame; emit a modelled REST/RE-PRICE/CANCEL trace.
2. **Crossing-event fill proxy** *(finding 3 — renamed so it cannot read as validating a crossed rest, which §1.3 forbids and
   §3.2 calls a defect).* A fill-eligible **event** is the **transition** `ask > p*` → `ask ≤ p*` between consecutive frames
   while our bid is live and un-cancelled: **one** event, priced at `p*`. A book that merely *stays* crossed yields no further
   events — persistent crossing means our bid should not have been resting at all, and a fill per frame would manufacture volume
   out of a defect. Each event is discounted by a **queue-share `s ∈ [0,1]`** (Breezy is not first in queue; the venue exposes
   no queue position); report `s ∈ {0.25, 0.5, 1.0}` **and** frame-gap robustness (transition required to persist ≥1 frame, and
   separately ≥0). **Limitation:** true maker fills where the ask never prints `≤ p*` — a marketable sell walking *down through*
   resting bids, the textbook maker fill — are **uncounted**, unrecoverable from depth alone, until TRADE prints exist (§2.2).
   The proxy is therefore **biased-low in fill count and biased-adverse in fill mix**: it over-represents the crossing
   (informed) seller.
3. **Cancel race:** model cancel latency `λ` (PROVISIONAL 500 ms) plus observation lag; an event counts only if it precedes
   `t_kill + λ`, `t_kill` being when we would *have learned* the rung died. Report events inside the race window separately —
   the L-7/L-9 pick-offs, made concrete. Then realised pnl at settlement per fill; `π̂_I` split per §1.4; compare to the IOC
   baseline over the identical day set.

### §2.2 TRADE-print capture, and the re-run that closes the proxy gap

The recorder has a TRADE parser and publish path but **has never subscribed the channel** (Appendix A). **A separate capture
increment starts 2026-09-16/17: the recorder subscribes the market `TRADE` channel** (price, quantity, tradeTime, maker/taker
side+intent). Once ≥ `N` days of prints exist (PROVISIONAL `N = 20` station-days), **Arm A re-runs with print-based fills** — a
print at/below `p*` whose *maker* side matches our leg is a real maker fill, capturing the walker case §2.1 cannot. That re-run,
not the proxy, is the intended basis for the final `m` and §3's registration if the calendar allows; the proxy result is the
conservative interim.

**Print sizes are UNIT-UNRESOLVED until the first cross-check.** The venue wraps `trade.quantity` as `Amount{value, currency: "USD"}` -- its cash-quantity shape elsewhere -- while contract counts are bare numbers, so a captured `TradeTick.size` may be contracts or dollars. The adapter flags this as `parsing.TRADE_QUANTITY_UNIT == "UNRESOLVED"` and keeps the raw `quantity` object verbatim as bounded evidence; the Arm A re-run must not consume `TradeTick.size` until the first live print has been cross-checked against the REST fill quantity for the same trade and that constant is resolved.

### §2.3 Tape constraint, measured now (finding 5)

Counted 2026-09-16 over `~/.local/share/breezy/catalog/quote_tape/polymarket_us/live`, staged `order_book_depths` feather,
station-day keyed off the instrument slug: **27 supported station-days** (LAX 7, MDW 6, MIA 7, SFO 7) over **7 distinct climate
days**, 2026-09-03 … 2026-09-11 — 34 with NYC, which `config.py:224` does not support. **No depth staging after 2026-09-11 in
this catalog root.**

**What this means, before further build spend.** 27 clears G-R1's station-day count and ≥3-station spread, but they collapse
onto **7 climate days** — 7 independent weather draws, heavily clustered. Therefore: G-R1 is **amended** to require ≥ 25
station-days **across ≥ 12 distinct climate days**, which today's tape does **not** meet (7), so Arm A yields only a
*provisional* read; G-R2's bootstrap resamples **climate days**, not station-days, or it understates the interval by roughly
√(27/7); ING-1 stays binding (in-window **parquet** coverage < 30 min, staged feather is the complete source, Appendix A), so
§2.1 reads staged feather, asserts coverage like `paper_replay:257`, and **refuses** a truncated slice rather than zero-filling
it (L-23). The distinct-day count rises with the ongoing capture; §2.2's print re-run is what makes the answer decisive rather
than provisional.

### §2.4 Pre-registered arming gates

| Gate | Threshold (PROVISIONAL) |
|---|---|
| G-R1 honest N | ≥ 150 modelled fills, ≥ 25 station-days, **≥ 12 distinct climate days**, ≥ 3 stations (§2.3: 12 days not met today) |
| G-R2 profitability | `Ê[pnl\|fill] > 0` with a **climate-day-bootstrap** lower bound > 0 at α=0.05 |
| G-R3 adverse-selection **precision** | Wilson **half-width on `π̂_I` ≤ 0.08**, *and* G-R2 survives at `π_I` = the interval's upper end — π̂_I being a lower bound (§1.4), a wide interval is a fail, not a pass |
| G-R4 dominance | maker `Ê[total pnl]` over the day set exceeds the IOC baseline's |
| G-R5 robustness | G-R2 holds at every `s ∈ {0.25,0.5,1.0}`, both frame-gap conventions, and under `fee = fee_taker` |
| G-R6 tape honesty | zero station-days admitted from a truncated/stranded slice (ING-1); coverage asserted, never silently zero-filled |

**Any gate failing ⇒ §4.2 onward does not start** (§4.1 is independent — it is a correctness fix to the fee model and lands
regardless). A failed study is a complete answer to the ruling: the edge is not restable *yet*, with numbers — and it would be
the second time measurement said so (§0.8).

### §2.5 Arm B — paper replay, and why it is sequenced after §4.1

Arm B drives the real strategy under `BacktestEngine` with the native resting fill model
(`tests/integration/test_resting_ladder_backtest.py`'s surface), asserting `LiquiditySide.MAKER` on the fill
(`resting_ladder.py:284`) — an engine-reported TAKER means the arm is mis-modelled and must fail, never be re-interpreted —
keeping the live-store (`paper_replay:384`) and coverage (`:257`) guards.

**Finding 6.** Arm B is unrunnable today: `fees.py:187` raises `MakerRebateUnmodelledError` on any post-only order and mis-signs
incidental maker fills, and Barrier F2 mandates that model. The plan takes **(a) resequence** — §4.1's correctly-signed maker
branch is a **prerequisite** of Arm B. Only if (a) slips: **(b) mechanics-only Arm B**, fee assertions **stubbed and declared
fee-invalid in the output header**, producing order-lifecycle evidence (rest → reprice → cancel → fill) and **no pnl or edge
number at all**, never citable for G-R2/G-R4.

Arm B validates the *code path*, Arm A the *economics*; disagreement on fill counts is a defect to explain, never an average to
take. With `prob_fill_on_limit=1.0` and `queue_position=False` (§0.7), Arm B's fill count is an **upper bound** until a trade
tape enables `trade_execution=True`.

## §3 PREREG v5 — successor family `pm_us_crh_rest_v5`

### §3.1 Registry and class

**Class C** — a different selector ⇒ a new family (`PREREG_v3…:5`, L-34). v3 is untouched and keeps running; nothing about its
code, D0 or tally changes. `family_id = pm_us_crh_rest_v5`; `trial_id_prefix = crh_rest_v5/trial/`; selector = rest at `p*`
(§1.2) with margin `m` registered from §2; D0 = the first climate_day on which a rest order is armed.

### §3.2 Trial definition and statistic

A trial is a **rested bid that filled**: an order (a) accepted by the venue as resting and (b) subsequently filled, whole or
part, at our resting price. **A cancelled bid is not a trial; a bid that never filled is not a trial.** A rest immediately
crossed on entry is **not** a v5 trial — it is a v3-shaped take, refused by §1.3's no-crossing rule; one occurring anyway is a
defect and a family halt (§4.9). **First-executable-snapshot changes meaning:** v3 selects *the first snapshot where the edge is
positive*, v5 *the first snapshot where a price with `edge ≥ m` exists*, and the trial clock starts at the **fill** — the
decision snapshot is kept as `p_bound` provenance, not as entry price.

**Statistic — unchanged in form, `BE` re-anchored to the FILL price.** `held_i | fill_i ~ Bern(BE_i)`, `BE_i = fill_price_i +
fee_i(fill_price_i)`, `fee_i` the **maker** fee actually charged (§4.1/§4.7; a rebate makes `BE_i < fill_price_i`). `S_k =
Σ(held_i − BE_i)/√Σ BE_i(1−BE_i)`, `I_k = Σ BE_i(1−BE_i)`, `t_k = min(1, I_k/I_max)` — in form identical to `PREREG_v3…:40-44`.
LD-OBF unchanged (two one-sided α=0.025, `I_max=40`, `n_max=160`, looks every 10 filled trials, `:44-50`); efficacy/futility/
truncation and the contract-unit halt verbatim; shadow trials never feed a verdict (`:27`).

### §3.3 Pre-declared strata — the fill event IS the signal (finding 7)

v3's trial is *our* decision; v5's is **counterparty-triggered**, so the fill event carries information and a pooled statistic
can hide a lethal subpopulation. Mirroring v3's station/ask-band strata (`PREREG_v3…:161`), registered **before D0, never as an
amendment**:

| Stratum | Levels | Role |
|---|---|---|
| **Time-to-fill** | `fast` < 60 s, `mid` 60 s–15 min, `slow` > 15 min (rest → fill) | secondary **kill** |
| **Fill cause** | `I` vs `L` per §1.4's classifier, evaluated live from the next observation | secondary **kill** |
| Station · Fill-price band | LAX/MDW/MIA/SFO · v3's ask bands applied to the fill price | as v3 |

**Primary-statistic decision (registered):** the primary SURVIVE statistic is computed over **ALL fills**; the `I` and `fast`
strata are **pre-declared secondary KILL criteria** — either stratum's own `S_k` crossing its futility boundary at a scheduled
look KILLs the family even while the pooled statistic is favourable. A fast fill and an informed fill are the two observable
signatures of being picked off, and a pooled mean can stay positive while that subpopulation bleeds. **No stratum can produce a
SURVIVE** — strata kill only, keeping the α spend on the single pooled boundary.

## §4 Execution seam increments — revised build order (security BLOCK addressed)

Every increment is RED-first, lands its own named pin widening with a non-vacuity test, and waits for its predecessor to be
green. §4.1 is independent of §2 and lands first; §4.2 onward is gated on §2.4.

### §4.1 (prerequisite) A correctly-signed maker fee branch

`fees.py` gains a maker branch: **Θ_maker = −0.0125**, pinned as a **SECOND coefficient** under the existing
`fee_schedule_mismatch` admission refuse (`PREREG_v3…:170`); the taker coefficient (`config.py:226`) is **untouched**.
`MakerRebateUnmodelledError` (`fees.py:187`) stops firing only for an instrument carrying a *pinned* maker coefficient and keeps
firing for every other post-only order — Barrier F2's premise is re-stated, not weakened. **RED tests:** a post-only order on a
pinned instrument prices to a **negative** fee of the right magnitude; an unpinned post-only order still raises; an incidental
maker fill is signed the same way (`_MAKER_SIGN_WARNING` retired for pinned instruments only); a coefficient disagreeing with
the venue's echoed `makerCommissionsBasisPoints` is a `fee_schedule_mismatch` refuse, never a silent re-derivation; the taker
path stays byte-identical. **Unblocks** §2.5 and §3.2's `BE_i`.

### §4.2 Discovery — close the one remaining venue unknown

The 09-04 probe already closed TIF (GTC), post-only, resting acceptance, read-back and cancel-all (§0.5). Remaining, via preview
+ the existing write-signing-probe route: **per-order cancel `POST /v1/order/{id}/cancel`** — request shape, and what its
bodyless 200 does and does not assert; `goodTillTime`/`GOOD_TILL_TIME` spelling drift if GTD is chosen over GTC; live
`makerCommissionsBasisPoints` on a maker fill. Evidence lands under `docs/evidence/venue/polymarket_us/` before §4.3.
**Reconciled with Appendix A (finding 12):** Rev 1's "slug-scoped or order-scoped?" is answered — order-scoped URL,
`{marketSlug}` body — so the open question is no longer *granularity* but *confirmability*.

### §4.3 Open-order read-back — its own paired-barrier increment (finding 9)

Sequenced **before any rest exists** — nothing may rest that cannot be enumerated.

- Readonly-guard **V2** gains a narrow allowlist for `GET /v1/orders/open` and `GET /v1/order/{id}` — read verbs only, for
  exactly the new read module; V2's order-path literal ban otherwise stands. **Non-vacuity test** in the style of
  `test_polymarket_us_readonly_guard.py:991`: removing the entry trips the scan, and a second module with the same literals
  still trips it.
- Adapter gains the read and wires `generate_order_status_report(s)` (`client.py:2361/2410`, today returning `[]` — SP-3 B1/B2).
- **Fail-closed boot:** the never-arm walk (today balances + positions only, `endpoints.py:83-86`) extends to enumerate open
  orders and **refuses to arm anything — IOC entries and exits included — until every open order is enumerated and either
  adopted or cancelled.** An enumeration error is a refusal, never an assumed-empty book.
- **RED tests:** enumeration failure refuses arming; an unknown open order triggers §4.9; an adopted order reconciles into the
  §4.4 store; `generate_order_status_reports` no longer returns `[]` when an order rests.

### §4.4 A durable resting-intent store, SEPARATE from the in-flight singleton (finding 1)

**The Rev 1 design is withdrawn.** `SubmitIntent` is a single global record (§0.7); adding a `RESTING` state would either
clobber the record on a second `arm()` or serialize the whole account to one resting order. Instead: a **new durable keyed
store**, key **`(station, climate_day, leg)`**, bound to the **same flock** via `SubmitIntentLatch.shared_state_binding()`
(`submit_intent.py:496-514`) and keyed exactly as `station_day_admission` keys (`trial_day_latch.py:1383-1420`) with an
**explicit index**, because `StateStore` has no key enumeration (`:1405-1412`). Record: venue order id, client order id, resting
price, `p_bound`/`m` provenance, `armed_ns`, state ∈ `{PENDING_REST, RESTING, PENDING_CANCEL, CANCEL_CONFIRMED, FILLED}`, and
the `SpendBooking` handle (§4.8). The `SubmitIntent` singleton **keeps its exact current meaning** — a transient
one-POST-at-a-time serializer, armed before every POST (rest, cancel, entry, exit), retired with venue evidence, gaining **no**
new state; its docstring's claim that nothing of ours can rest is corrected in the same commit (L-36).

**`arm()` semantics while something rests — registered:**

| Situation | Rule |
|---|---|
| IOC **entry** on an instrument with a resting bid | **refused** (`resting_order_live`) — the rest *is* the entry |
| IOC **exit** on an instrument with a resting bid | **cancel first, cancel-CONFIRMED (§4.6), then arm** — never both live |
| Any order on a **different** station/instrument | proceeds; the store is per-key, not global |
| Two POSTs at once, anywhere | still impossible — the in-flight singleton serializes every POST |
| Second rest on the same `(station, climate_day, leg)` | refused, and §4.9 halts |

**RED tests:** `test_resting_store_holds_two_legs_of_one_station_day_concurrently`,
`test_an_ioc_entry_is_refused_while_a_bid_rests_on_that_instrument`,
`test_an_ioc_exit_cancels_the_rest_and_waits_for_confirmation_before_arming`,
`test_a_rest_on_one_station_does_not_block_a_rest_on_another`, `test_two_posts_cannot_be_in_flight_even_with_two_resting_legs`,
`test_a_second_rest_on_the_same_station_day_leg_is_refused_and_halts`, `test_the_resting_store_shares_the_submit_intent_flock`,
`test_a_crash_between_sibling_fill_and_cancel_write_leaves_cancel_required` (finding 2).

### §4.5 Adapter: gated RESTING shapes, with a zero-call-sites pin (finding 10)

`submit_chain.py` gains `unmappable_resting_order_reason(order, instrument, authorization)` — a **third** shape mirroring the
exit seam's structure (`:396-461`), never a relaxation of the first two. Widened only for an order carrying a
`RestingAuthorization`: `TimeInForce.GTC` (live-proven, §0.5) or GTD with `expire_time` = window end if §4.2 confirms the
spelling, and `is_post_only=True`. Everything else stays: LIMIT, BUY, qty == 1, price strictly inside (0,1), no reduce-only, no
display_qty, no trigger. `build_resting_order_body` emits `goodTillTime` and `participateDontInitiate`; `ORDER_BODY_KEYS`
(`:92`) gains a **separate** resting frozenset. **Zero-call-sites pin (finding 10):** until §4.4 is green, a RED test asserts
**no strategy module constructs a `RestingAuthorization`-tagged order and nothing calls `build_resting_order_body`** — exactly
the posture `write_transport.post_cancel_all` has held since it shipped (§0.3); removed in the commit that wires §4.6. **Other
RED tests (per-leg, L-44):** an untagged GTC/GTD BUY still refused byte-identically at `:296`; an untagged post-only BUY still
refused at `:309`; a tagged order whose leg/qty/price/position contradicts its authorization refused (mirroring `:445-460`).

### §4.6 Cancel write path — both verbs, and confirmation by READ (finding 8)

`_cancel_order` (`client.py:3610`) stops refusing and issues **per-order** cancel; `_cancel_all_orders` (`:3632`) stops raising
and calls the already-shipped `write_transport.post_cancel_all` (`:160`), needed by §4.9's kill. **Evidence bar, registered** —
the 09-04 probe proved **cancel-ALL only**, and per-order cancel is URL-id scoped and returns no body (§0.5):

> A cancel is **not** "cancelled" on a 200, and **not** on a private-WS `CANCELED` execution (that channel
> is never wire-verified). A resting record reaches `CANCEL_CONFIRMED` **only** after a post-cancel
> `GET /v1/orders/open` (§4.3) shows the order absent, or `GET /v1/order/{id}` shows a terminal
> `CANCELED`/`EXPIRED`. Cancel-all's `{canceledOrderIds}` is an echo, likewise insufficient.

Pin widenings, additive: egress firewall **V2** — cancel verbs remain E3 surfaces
(`test_execution_egress_firewall_guard.py:213-227`) and the expected-module set (`:710`) gains the cancel path in the same
commit; readonly-guard admits the cancel write verb for exactly the cancel module with a `:991`-style non-vacuity test;
`scripts/ci/run_tests_no_egress.sh` stays green. **RED tests:** a cancel with no resting record refuses; a bare 200 does **not**
advance the record past `PENDING_CANCEL`; a private-WS CANCELED alone does not either; absence in a post-cancel GET does; no
confirmation within 30 s escalates per §4.9; a foreign order id refuses.

### §4.7 Strategy wiring, and maker fill handling

Wire REST / RE-PRICE / CANCEL (§1.3) onto the native calls §0.4 proved, driving the §4.4 store. On fill, `Execution.aggressor`
(`orders.py:107`) and `commissionNotionalCollected` (`:108`) are the evidence: **the fee is taken at the FILL price from the
venue's reported number**, never recomputed optimistically, and reconciled against §4.1's pinned Θ_maker — a disagreement is a
`fee_schedule_mismatch` refuse, not a re-derivation. A fill reported TAKER on a post-only order, or at a price other than our
resting price, is §4.9.

### §4.8 Operator caps — the reservation rule

`DailySpendLedger` is **reused unchanged**; this increment adds **a new call site to the existing
`release_booking`/`true_up_booking` primitives** (finding 11), not a new ledger:

> **At REST:** cost (`order_cost_usd:230`, cost-before-fee, rounded up to the cent, `:220`) checked
> against the **per-order cap** and booked via `authorize_order_cost` (`:347`) as a *reservation*. **On
> CANCEL-CONFIRMED / expiry:** `release_booking` (`:456`) returns it — a cancelled bid consumes no
> budget. **On FILL:** `true_up_booking` (`:476`) makes it permanent at the fill price; **that is when
> the daily budget is consumed.**

Concurrent rests are each individually capped, and their joint *reservations* cannot exceed the daily budget —
`authorize_order_cost`'s `_spent_usd + cost > daily_budget` check (`:417-421`) already enforces exactly that. Appendix A's "no
cancel→release path" is closed by this call site. **No new operator control, no new env var.**

### §4.9 Kill

Durable family halt + cancel-all on: any unexpected open order at boot (§4.3); any cancel not *confirmed* within the PROVISIONAL
30 s (§4.6); any fill at a price other than our resting price; a fill reported TAKER on a post-only order; a second resting
order on one `(station, climate_day, leg)`; a rest that took on entry (§3.2); an enumeration failure. The halt is written
durably, survives restart, and refuses re-arm until cleared with evidence — the `entry_only_halt` (`config.py:234`) shape. L-38:
a stop that cannot fire is missing.

## §5 Safeguards and observability

- **Decisions tape:** `decision_kind` (`offer_tape.py:143`) gains `rest`, `reprice`, `cancel`, `cancel_confirmed`, `rest_fill`;
  each row carries `p*`, `m`, `edge(p*)`, `p_bound`, the maker BE, staleness, cell, leg, queue-share assumption, and for cancels
  the **reason code** (incl. `sibling_leg_filled`). The 16 strict legacy keys (`:59`) are untouched — additive only, as with the
  exit fields (`:150-165`); byte cap (`:305`) unchanged.
- **Nightly series** (extending `position_monitor_nightly_report.py`): rests, re-prices, cancels by reason, fills,
  **time-to-fill and fill-cause stratum counts (§3.3)**, time-at-rest distribution, and realised `π̂_I` vs §2's prediction. **A
  live `π̂_I` outside §2's interval is an alert** — π̂_I is a lower bound (§1.4), so exceedance is the expected direction of
  failure.
- **Alerts:** cancel unconfirmed at 30 s; a resting order outliving the window; an open order the store does not know; a maker
  fill reported TAKER; fill price ≠ resting price; reservation/ledger divergence; a stratum crossing its secondary kill
  boundary.

## §6 Deployment

1. **Shadow.** Rest decisions computed and persisted to the tape; **no venue write** (`orders_enabled=False`, `config.py:237`;
   no `RestingAuthorization` minted — §4.5's pin). Runs beside live v3. Exit criterion: ≥ 10 station-days where the shadow's
   modelled rests and cancels reconcile against the Depth10 tape with no unexplained divergence from §2.
2. **Positive control — both verbs (finding 8).** Re-run the 09-04 rest-and-cancel through the *adapter*: rest 1 contract far
   from the touch, enumerate via GET, cancel with the **per-order** verb, confirm absence via GET; then rest again and cancel
   with the **cancel-all** verb, confirm absence via GET. Both legs must pass; a bodyless 200 is not a pass. **Automated, per
   the ruling that OP-1/OP-3 are the bot's job, never a UI step.**
3. **Enable per family registration.** `pm_us_crh_rest_v5` armed for one station, then widened; D0 is the first armed day.
   **Rollback** = cancel-all (verb now live) + manifest flip to the prior registration; v3 is never modified, so rollback is a
   flip, not a revert.

## §7 Open questions

**Operator-budget questions: none.** The two caps (`operator_controls.py:131`, `:173`) suffice — §4.8 expresses resting
reservation entirely within the existing per-order cap and daily budget, and every other constant (`m`, `s`, `λ`, the 30 s
confirmation deadline, strata boundaries, halt rules, enablement, family registration) is build-side and either registered in §3
or measured in §2.

Build-side unknowns, each closed before its dependent increment, none needing the operator: per-order cancel request shape and
what its bodyless 200 asserts (§4.2, before §4.6); `goodTillTime`/ `GOOD_TILL_TIME` spelling if GTD is chosen over live-proven
GTC (§4.2); live `makerCommissionsBasisPoints` on a real maker fill (§4.2, reconciled in §4.7); whether §2.3's
distinct-climate-day count reaches 12 before the decision is needed — answered by §2.2's capture and the ongoing recorder, by
calendar, not by ruling.

## Appendix A — venue/adapter/data evidence sweep (read-only, 2026-09-16 ~19:45Z; coordinator hand-down)

## Venue (docs snapshots 2026-08-25 + SDK 0.1.2)
- TIF: DAY, GOOD_TILL_CANCEL, GOOD_TILL_DATE (`goodTillTime` RFC3339 → EXPIRED), IOC, FOK. Institutional insert-order lists GOOD_TILL_TIME (spelling drift).
- `maxBlockTime` only with synchronousExecution; adapter sends 5.
- Cancel one: `POST /v1/order/{id}/cancel` body {marketSlug}, NO response body. Cancel all: `POST /v1/orders/open/cancel` {slugs?} → {canceledOrderIds} (echo, not confirmation). Batch cancel/modify ≤20, atomic validation, unknown ids silently ignored. Modify = cancel-replace → REPLACED. Pure cancels never rate-limited.
- Open orders: `GET /v1/orders/open` (slugs[]), `GET /v1/order/{id}` — BARRED in adapter by readonly-guard V2 (order-path literal ban, no allowlist).
- States: PENDING_NEW, NEW (resting), PENDING_REPLACE, PENDING_CANCEL, PENDING_RISK, PARTIALLY_FILLED, FILLED, CANCELED, REPLACED, REJECTED, EXPIRED. Exec types incl. CANCELED, EXPIRED, DONE_FOR_DAY.
- Private WS `/v1/ws/private`: ORDER (snapshot + per-Execution updates, `aggressor`, `commissionNotionalCollected`), POSITION, ACCOUNT_BALANCE — SDK-documented, never wire-verified here.
- Market WS: MARKET_DATA, MARKET_DATA_LITE, TRADE (price, quantity, tradeTime, maker/taker side+intent); TRADE channel never subscribed by Breezy (capture increment dispatched 09-16).
- Post-only: `participateDontInitiate` on create and modify.
- FEES: Θ_taker +0.06; **Θ_maker −0.0125 (REBATE)**, applied at trade. Adapter `fees.py:57-118` refuses post-only and prices any maker fill at taker Θ with a UserWarning ("wrong in SIGN").
- LIVE-PROVEN 2026-09-04 (`PRIVATE_write_sequence_probe_20260904T170856Z.json`): GTC + participateDontInitiate BUY 1 @0.01 rested (200), enumerated via GET /v1/orders/open (200), cancelled via /v1/orders/open/cancel (200), postflight flat (200): CLOSED_YES_BOTH_VERBS. Builder scripts/venue/polymarket_us_write_signing_probe.py:354-373.

## Adapter today
- submit_chain.py:290-311 (+ exit twin :407-430): LIMIT, IOC only (:296-297), BUY, qty==1, price∈(0,1), post-only refused (:310-311). Body keys :92-105 lack goodTillTime/participateDontInitiate.
- write_transport.py:38-58: POST only; ORDERS_PATH, CANCEL_ALL_PATH + `post_cancel_all` shipped with ZERO call sites. No per-order cancel. client.py:3610-3633: `_cancel_order` denies, `_cancel_all_orders`/`_modify_order` NotImplementedError.
- Firewall: readonly-guard B4/V1–V3 (V2 order-path literal ban), egress-guard E0 (exec/ prefix), E3 (coroutine names classify), X2, X3, N1–N4.
- SubmitIntent latch (runtime/submit_intent.py): OPEN before POST, retired only with venue evidence; retirement vocabulary has NO accepted-and-working state → a resting order = AMBIGUOUS shape forever, account single-order.
- AMBIGUOUS is the residual (submit_chain.py:1167-1285); strict ZERO_FILL unreachable; GET-based resolver (client.py:1605).
- Boot never-arm walk reads only balances + positions (endpoints.py:83-86): no open-orders read possible under V2.
- OP-1/OP-3 rest-and-cancel: designed manual → ruled bot's job 09-04 → shipped as OP-SEQ S0–S6 probe; no resting path in the adapter (EXEC_SPINE_NEXT:180).

## Strategy / PREREG v3
- Trial = first FILLED legal snapshot, ask-side, IOC (PREREG v3:25-30); class C for a resting bid.
- BE = ask + θ·ask·(1−ask), θ 0.06 (decision.py:308-316, 391-413; config.py:226); edge = p_bound − BE; p_bound = archive Wilson lower per cell, n_min 90.
- Re-arm: 120 s floor, R-9a 180 s evidence ceiling, ≤3 attempts/station-day, no re-arm after fill.
- Only order construction: continuous_strategy.py:2235-2242 (limit, IOC, post_only False). reports.py:428 maps only IOC. paper_replay.py:131-142 assumes BUY-IOC-at-ask.

## Data for a backtest
- Depth10 tape: 10 levels/side with sizes, ts; per-station catalogs exist; ING-1 CRIT keeps in-window parquet coverage <30 min (staged feather frames are complete).
- Trade prints: parser + publish exist, channel never subscribed → no prints anywhere. Bid side usually empty → zero QuoteTicks on bid-empty markets.
- Studies: offer-gate scan = ask ≤ threshold existence (taker question); M_A prelock winner-ask; M_B archive edge + Depth10 join. None models a resting fill.
- Paper replay: BacktestEngine, L2_MBP, FillModel prob_fill_on_limit=1.0 ("moot for taker-only"), queue_position=False (needs trade_execution=True, needs a trade tape), support_gtd_orders=True UNVERIFIED, latency_model=None (known overstatement), taker-only fee model.
- "Would a bid at p have filled" logic: does not exist.

## Risk primitives
- Two caps re-read on every authorization; ledger is booking-based (SpendBooking, release/true-up) with no cancel→release path; trial-day latch ≤1 order/station-day is the binding cross-restart limit.
- Nautilus natively supports GTC/GTD limit, cancel/modify, cache.orders_open, generate_order_status_reports; adapter implements none (reports return []; SP-3 B1/B2 open).

## Five gaps
1. Latch needs an accepted-and-working state + order-id reconciler. 2. Read-back (open orders) and cancel are barred by design; paired-barrier changes with non-vacuity proofs; SP-3 B1/B2 must land. 3. No fill-probability evidence; trade capture must start; ask-touch overstates a resting fill. 4. Maker rebate unmodelled; BE/H0 are taker-shaped → new family/boundary; fee model needs a maker branch. 5. GTD/GTT spelling, cancel has no body (private WS confirms), batch echo not confirmation, SpendBooking has no cancel release, latency model absent; re-run the 09-04 rest-and-cancel as the positive control.
