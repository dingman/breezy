# RESTING BID HUNT — Rev 1 (2026-09-16)

**Operator ruling (verbatim, 2026-09-16):** *"I expect that the bot is autonomously hunting for
edges and places order bids for edge that is identified. if a confident edge is found, the bid
should be placed so if the position reaches that threshold, it's executed. Fully flesh out this
concept and modeling, from planning through backtesting to deployment to production."*

Scope: a **maker** entry seam — rest a bid where our edge is confident and let the market come to
us — as a successor family to taker-only `pm_us_crh_cont`. Operator input stays reserved for the
two caps; every constant below is build-side and PROVISIONAL until §2 measures it.
## §0 Measured facts (nothing here is assumed)

### §0.1 The live rule is a taker rule at the first executable snapshot

| Fact | Pin |
|---|---|
| Edge test is `p_bound − (ask + fee)`; fee = `θ·ask·(1−ask)` banker's-rounded to the cent | `strategy/current_rung_hold/decision.py:308-316` |
| `Take` carries `limit_price`, `p_hold_lower`, `break_even`, `rung`, `side`, `p_bound` | `decision.py:246-266` |
| `Refuse` carries `p_bound`/`break_even` only on `edge_below_break_even` | `decision.py:222-243` |
| Legal-cell rule (`width_code==2` never legal; `m_code==1` only with `width_code==0`) | `decision.py:291-302` |
| Decision window `[12:00, 17:00)` LST, exclusive end | `strategy.py:154-155`, gate at `continuous_strategy.py:1109` |
| Refusal code for outside-window | `strategy.py:159` (`_OUTSIDE_DECISION_WINDOW`) |
| Staleness bound 50 min; θ pin 0.06; executable ask band [0.05, 0.95]; min displayed size 1; `order_quantity == 1`; `allow_short = False`; `orders_enabled = False` default | `config.py:85, 226, 227-228, 229, 230, 231, 237` |
| Stations LAX/MDW/MIA/SFO | `config.py:224` |
| Fee coefficient read from `instrument.maker_fee` | `strategy.py:726`, `continuous_strategy.py:2214` |
| Observation poll cadence 300 s per station | `ingest/nws_observation_config.py:41` |

### §0.2 Every IOC assumption in the write path (the pins that must widen)

`unmappable_order_reason` (`adapters/polymarket_us/exec/submit_chain.py:287-328`) refuses
anything that is not exactly one taker shape:

`:294` not LIMIT · **`:296` not `TimeInForce.IOC` ← the TIF pin** · `:298` not BUY (a SELL
is a naked short) · `:305` qty ≠ 1 · `:307` price not strictly inside (0.00,1.00) ·
**`:309` `is_post_only` ← the post-only pin** · `:311` `is_reduce_only` ·
`:313` `display_qty` · **`:316` `expire_time is not None` ← the GTD pin** ·
`:319` `has_trigger_price`.

`build_order_body` (`submit_chain.py:331-358`) hardcodes `"tif": _TIF_IOC` (`:352`),
`"quantity": 1` (`:351`), `synchronousExecution: True` (`:356`), `maxBlockTime` (`:357`),
and emits **no `goodTillTime` key**. The body key set is frozen at `submit_chain.py:92`
(`ORDER_BODY_KEYS`).

The gated exit seam re-applies the **same** IOC pin to a closing SELL:
`_unmappable_exit_shape_reason` `submit_chain.py:414` (IOC), `:417` (SELL), `:431`
(`expire_time`). `exit_wiring.py:293` passes `reduce_only=False` (no such venue field).

### §0.3 There is no cancel path, and the firewall knows it

- `_cancel_order` **refuses** with a denial body: *"EXEC_SPINE R-4 has no order path, so no
  order of ours can be resting at the venue to cancel"* — `exec/client.py:3610-3624`.
- `_cancel_all_orders`/`_modify_order`/`_submit_order_list`/`_batch_cancel_orders` **raise**
  `NotImplementedError` — `client.py:3626-3636`, rationale `:3643`.
- Egress firewall E3 already classifies `cancel_order`, `_cancel_order`,
  `_cancel_all_orders`, `_batch_cancel_orders`, `_modify_order` as egress surfaces —
  `tests/unit/test_execution_egress_firewall_guard.py:213-227`.
- Write-verb cage `_WRITE_METHODS`/`_WRITE_ATTRS`/`_WRITE_FUNCTIONS` —
  `tests/unit/test_polymarket_us_readonly_guard.py:183-202`; exemption non-vacuity and
  *"the capture script is the only new venue write path"* at `:991-1055`.

### §0.4 What Nautilus already gives us (L-1 null hypothesis: it does)

`strategy/resting_ladder.py:113-393` — `BreezyRestingLadder` — already rests a GTC limit,
re-prices it and cancels it, **inside `BacktestEngine`**, using only native calls:

native GTC resting limit `:206-213`; re-price via `modify_order` `:253`; `cancel_order`
over a deterministic `cache.orders_open` sort `:261-278`; maker-fill detection via
`LiquiditySide.MAKER` `:284`; Depth10 size-0 pad skipped via `best_order` `:377-389`;
covered by `tests/integration/test_resting_ladder_backtest.py`.

**Conclusion: no new resting-order engine, order store, or timer framework may be built.**
The entire strategy-side capability exists natively; this plan's only new code is the
*decision* (where to rest), the *adapter mapping* (one TIF and one endpoint), and the
*safety state* (a resting intent + reconciliation).

### §0.5 Venue capability, from the captured SDK snapshot (contract, not confirmation)

`docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/types/orders.py`:

`TimeInForce` includes `..._GOOD_TILL_CANCEL` and `..._GOOD_TILL_DATE` (`:15-20`);
`CreateOrderParams` accepts `goodTillTime` (`:121`) and `participateDontInitiate` (`:120`,
the post-only analogue); **`CancelOrderParams` is `{marketSlug}` only (`:147-150`) — not
keyed by order id**, `CancelAllOrdersParams` takes `slugs` (`:153-156`);
`GetOpenOrdersParams`/`Response` (`:165-174`), `GetOrderResponse` (`:177-180`);
`Order` carries **both** `commissionsBasisPoints` and `makerCommissionsBasisPoints`
(`:91-92`) — the maker schedule is a *different number*, never observed;
`Execution` carries `aggressor: bool` (`:107`) and `commissionNotionalCollected` (`:108`);
private WS carries `SUBSCRIPTION_TYPE_ORDER` snapshot + update (`websocket/types.py:45-67`).

A snapshot is a *claim*. §4.1 discovers the real behaviour by preview + positive control.

### §0.6 Safety state, caps, evidence

- `SubmitIntent` singleton is `OPEN | RETIRED` only (`runtime/submit_intent.py:233-249`);
  `arm` refuses while OPEN (`:388-416`); `retire` (`:418-436`);
  `reconcile_at_startup` (`:438-474`). **No resting state exists.**
- Operator caps and the booking machinery already exist:
  `operator_max_daily_budget_usd` (`operator_controls.py:160`),
  `operator_max_position_cost_usd` (`:173`), `order_cost_usd` (`:230`),
  `SpendBooking` (`:248`), `DailySpendLedger` (`:263`), `authorize_order_cost` (`:347`),
  `release_booking` (`:456`), `true_up_booking` (`:476`), `DailyBudgetExhausted` (`:126`).
  **Booking → release/true-up is exactly reserve-then-settle. Reuse it; build nothing.**
- Decisions tape: `OfferTapeRecord` `offer_tape.py:82-225`, 16 strict legacy keys (`:59`),
  `decision_kind` and the exit fields (`:143-165`), byte cap (`:305`).
- Offline evidence reusable as-is: `exit_window_core.py:172-198` (`build_exit_timeline` over
  `Sequence[OrderBookDepth10]`, frames filtered `ts_init > filled_at_ns`), `entry_cost:298`,
  `hold_pnl:304`, `infer_preliminary_settlement:402`; `current_rung_hold_paper_replay.py`
  (BacktestEngine `:39`, window-coverage guard `:257`, live-store guard `:384`).
- **Trades are not captured.** No `SUBSCRIPTION_TYPE_TRADE` subscription exists anywhere in
  `src/` (grep clean). The fill proxy in §2 must therefore be depth-derived, not print-derived.

### §0.7 Today's evidence

- 09-16 MDW's current rung asked **0.99 all afternoon**; no bid ever crossed. A taker rule
  sees nothing all day. This is the motivating observation, and it is exactly one day.
- 09-15's four takes all lost; SFO lost a half-cent edge to a 300 s observation-latency race
  into a one-sided book. **Latency cuts both ways for a maker: the same 300 s that made us
  overpay as a taker is 300 s during which our resting bid is stale and pickable.**

## §1 Concept and model

### §1.1 Confident edge (unchanged definition, new use)

`p_bound` is the archive Wilson lower bound for the cell (`season`, `hour_lst`, `width_code`,
`m_code`) — the same number `decision.py` computes, over the same legal cells
(`decision.py:291-302`). "Confident" is *already* that lower bound; no new notion is added.

### §1.2 The resting price

For a leg, define `edge(p) = p_bound − (p + fee_maker(p))`, with `fee_maker` the maker
schedule (§4.6 — **unknown today**; §2 uses `fee_taker` as a conservative upper bound since
`θ=0.06` is what we have validated: `config.py:226`).

> **p\*** = the highest venue-tick price with `edge(p) ≥ m`, clamped to the executable band
> `[0.05, 0.95]` (`config.py:227-228`) and strictly inside (0,1) (`submit_chain.py:307`).

`m` = PROVISIONAL registered margin, **initial candidate 0.03 probability** — *not* the taker
rule's `> 0`: a maker needs a margin because §1.4 shows the fill is adversely selected. §2
calibrates `m`; §3 registers whatever §2 returns. One contract per order (`config.py:230`,
`submit_chain.py:305`). **Both legs** — YES on the current rung, NO wherever the NO edge
exists (its `p_bound` is `p_miss_lower`, carried as `Take.p_bound`, `decision.py:251-257`;
NO wire price still via `wire_price_for_leg`, `submit_chain.py:346`). Only inside
`[12:00,17:00)` LST (`strategy.py:154-155`).

### §1.3 Registered decision / re-price / cancel rules

**REST** when: inside window, cell legal, observation fresh (≤ 50 min, `config.py:85`), `θ`
matches the pin, no resting order live for this (station-day, leg), no in-flight submit, and
`p*` exists. Quantity 1.

**RE-PRICE** on every event that changes `p_bound` or the cell — new observation, running-max
change, rung change, hour_lst rollover. Recompute `p*`; if it differs from the live price,
`modify_order` (native, `resting_ladder.py:253`) where the venue supports modify, else
cancel-then-rest. **Never re-price upward past the best ask** — a bid that would cross is the
incumbent IOC family's job, not this one.

**CANCEL** immediately on: the observation killing the rung (running max moves out / `r_dead`);
staleness past the bound; window close; `p*` ceasing to exist (`edge(p) < m` everywhere); a
family halt; node stop (`on_stop`); a duplicate or unexpected open order. Cancel is
**fail-loud** — no confirmation within a PROVISIONAL 30 s escalates to cancel-all + durable
family halt (§4.8).

### §1.4 Adverse selection — the model that decides whether this is worth doing

L-7/L-9 is the binding prior: *public info has no offer side — a resting bid is picked off
exactly when the observation moves against it.* Formally, our bid at `p*` fills only when
someone is willing to sell at `p*`, and the reason matters:

- **Reason L (liquidity):** a seller crosses for non-informational reasons (inventory, exit,
  noise) ⇒ `E[settle|fill,L] ≈ p_bound`, so `E[pnl|fill,L] ≈ edge(p*) ≥ m > 0`.
- **Reason I (information):** the ask fell to `p*` because the *observation* moved against
  the rung and we have not seen it — we are stale by up to 300 s
  (`nws_observation_config.py:41`) ⇒ `E[settle|fill,I] ≪ p_bound`, `E[pnl|fill,I] < 0`,
  potentially `−p*`.

So `E[pnl | fill] = π_L·edge(p*) − π_I·|loss_I|`, where `π_I = P(I | fill)`.
**The whole viability question is `π_I`.**

**Estimator (this is what §2 computes, per station-day-cell):**
For each modelled fill at time `t`, classify it `I` if the *next* observation (or the
already-known ground truth of the day) moves the rung's `p_bound` down by more than a
PROVISIONAL 0.05 within a PROVISIONAL 600 s of `t`; else `L`. Then
`π̂_I = #I / (#I + #L)` with a Wilson interval, and
`Ê[pnl|fill]` from realised settlement, not from the classification.

**Data needed:** Depth10 frames (have: recorder tape, staged + parquet, ING-1 strand),
the per-station observation series (have: IEM/ASOS as used by the paper replay), the frozen
archive table (have), settlement truth (have: `infer_preliminary_settlement`
`exit_window_core.py:402`). **Not needed and not available:** trade prints (§0.6).

**Baseline to beat:** the IOC-take rule on the *same* station-days. The maker arm wins only
if `Ê[pnl|fill] > Ê[pnl|take]` **and** the fill count is materially higher (the 09-16 MDW
0.99 day is the motivating case: taker N=0, maker N=?).

## §2 Measurement BEFORE any venue write

No byte is sent to the venue in §2. Two arms, both offline.

### §2.1 Arm A — counterfactual study over existing tape

New script `scripts/analysis/resting_bid_counterfactual_study.py`, composing existing pieces
(`exit_window_core` `:172`/`:298`/`:304`/`:402`; `monitor_evidence`/`monitor_records` for the
row shape). For every station-day × cell where the IOC rule **would** or **did** arm:

1. Walk Depth10 frames in the window in `ts_init` order; maintain `p_bound`, cell and
   staleness from the observation series with the **real 300 s poll lag**, never hindsight.
2. Compute `p*` per §1.2 at each frame; emit a modelled REST/RE-PRICE/CANCEL trace.
3. **Fill proxy (conservative, depth-only):** the bid at `p*` fills iff the best ask is
   `≤ p*` for ≥ `k` consecutive frames (PROVISIONAL `k=3`) while it is live and un-cancelled —
   an ask at-or-below our bid means a crossing seller existed, and `k` frames avoids
   crediting a one-frame artefact. Report `k ∈ {1,2,3,5}`: the conclusion must survive `k=1`
   (most optimistic) *and* `k=5` (most pessimistic) or it is not a conclusion.
4. **Cancel race:** model cancel latency `λ` (PROVISIONAL 500 ms) plus the observation lag; a
   fill counts only if it precedes `t_kill + λ`, where `t_kill` is when we would *have
   learned* the rung died. Report fills landing inside the race window separately — those are
   the L-7/L-9 pick-offs made concrete.
5. Realised pnl at settlement per fill; `π̂_I` split per §1.4; compare to the IOC baseline
   over the identical day set.

**Pre-registered arming gates (written into this file before the study runs):**

| Gate | Threshold (PROVISIONAL) |
|---|---|
| G-R1 honest N | ≥ 150 modelled fills across ≥ 25 station-days, ≥ 3 stations |
| G-R2 profitability | `Ê[pnl \| fill] > 0` with a Wilson/bootstrap lower bound > 0 at α=0.05 |
| G-R3 adverse selection | `π̂_I` upper 95% bound leaves G-R2 intact |
| G-R4 dominance | maker `Ê[total pnl]` over the day set exceeds the IOC baseline's |
| G-R5 robustness | G-R2 holds at both `k=1` and `k=5`, and under `fee_maker = fee_taker` |
| G-R6 tape honesty | zero station-days admitted from a truncated/stranded ingest slice (ING-1); coverage asserted like `paper_replay:257`, never silently zero-filled |

**Any gate failing ⇒ §3 and §4 do not start.** A failed study is a complete answer to the ruling:
it says the edge is not restable *yet*, with numbers.

### §2.2 Arm B — paper replay with the real strategy

Extend `current_rung_hold_paper_replay.py`'s harness (not its file) with a
`resting` arm driving the **real** new strategy class under `BacktestEngine`, with:

Nautilus's native resting-order fill model (the surface
`tests/integration/test_resting_ladder_backtest.py` already exercises); a
`LiquiditySide.MAKER` assertion on the fill (`resting_ladder.py:284`) — an engine-reported
TAKER means the arm is mis-modelled and must fail, never be re-interpreted; and the
live-store (`paper_replay:384`) and window-coverage (`:257`) guards retained.

Arm B validates the *code path*, Arm A the *economics*. Disagreement on fill counts is a defect
to explain, never an average to take.

## §3 PREREG v5 — successor family `pm_us_crh_rest_v5`

**Class C** (a different selector ⇒ a new family, per `PREREG_v3…:5` and L-34). v3 is untouched
and keeps running; nothing about its code, D0, or tally changes.

| Field | Value |
|---|---|
| `family_id` | `pm_us_crh_rest_v5` |
| `trial_id_prefix` | `crh_rest_v5/trial/` |
| Selector | rest at `p*` (§1.2), margin `m` registered from §2 |
| D0 | first climate_day on which a rest order is armed |

**Trial definition.** A trial is a **rested bid that filled**: an order (a) accepted by the
venue as resting and (b) subsequently filled, whole or part, at our resting price. **A
cancelled bid is not a trial; a bid that never filled is not a trial.** A rest immediately
crossed on entry is **not** a v5 trial — it is a v3-shaped take, refused by §1.3's no-crossing
rule; one occurring anyway is a defect and a family halt (§4.8).

**First-executable-snapshot changes meaning.** v3 selects *the first snapshot where the edge is
positive*; v5 selects *the first snapshot where a price with `edge ≥ m` exists*, and the trial's
clock starts at the **fill**, not the decision. The decision snapshot is still recorded as the
`p_bound` provenance, but is no longer the entry price.

**Statistic — unchanged in form, `BE` re-anchored to the FILL price.**
`held_i | fill_i ~ Bern(BE_i)` with `BE_i = fill_price_i + fee_i(fill_price_i)`, where
`fill_price_i` is the executed price and `fee_i` the **maker** fee actually charged
(§4.6). `S_k = Σ(held_i − BE_i)/√Σ BE_i(1−BE_i)`, `I_k = Σ BE_i(1−BE_i)`,
`t_k = min(1, I_k/I_max)` — identical to `PREREG_v3…:40-44`.

**LD-OBF unchanged:** two one-sided α=0.025, `I_max=40`, `n_max=160`, looks every 10 filled
trials (`PREREG_v3…:44-50`). Efficacy/futility/truncation conditions carried over verbatim,
including the contract-unit halt.

**Shadow trials never feed a verdict** (carried from `PREREG_v3…:27`). §6's shadow stage and
§2's replay are characterisation only.

## §4 Execution seam increments, in dependency order

Every increment is RED-first. No increment starts before its predecessor is green **and**
its named pin widening has a test proving the pin still refuses everything else.

### §4.1 Discovery (read + preview only; no new write surface)

Route: the existing preview/shape-capture discovery path
(`scripts/venue/polymarket_us_shape_capture.py`, `polymarket_us_private_shape_probe.py`,
and the B4-exempt `polymarket_us_write_signing_probe.py`). Answer, from the venue, not the
snapshot:

1. Does a `GOOD_TILL_CANCEL`/`GOOD_TILL_DATE` LIMIT BUY preview accept, and is
   `goodTillTime` honoured — in what format?
2. Is `participateDontInitiate` (post-only) accepted, and does it reject-on-cross?
3. What does cancel actually take? `CancelOrderParams` is `{marketSlug}` only
   (`orders.py:147-150`) — **does cancelling a slug cancel one order or all of them?** The
   most important unknown: a slug-scoped cancel turns §4.5's one-resting-order invariant
   from a convenience into a requirement.
4. What does `GetOpenOrders` return for a resting order, and what is
   `makerCommissionsBasisPoints` on a resting/filled maker order (`orders.py:92`)?

**RED test:** a shape-contract test that pins the discovered preview/echo bytes, in the
style of `test_polymarket_us_readonly_guard.py:1041`
(`…capture_script_body_keys_equal_the_live_order_body_keys`).
**Discovery answers are recorded under `docs/evidence/venue/polymarket_us/` before §4.2.**

### §4.2 Adapter: a narrowly gated RESTING BUY shape

`submit_chain.py` gains `unmappable_resting_order_reason(order, instrument, authorization)`
mirroring the exit seam's structure (`:396-461`) — a **third** shape, never a relaxation of
the first two.

Widened *only* for an order carrying a `RestingAuthorization`:
`TimeInForce.GTD` (with `expire_time` = window end) or `GTC` per §4.1's answer, and
`is_post_only=True` iff §4.1 proves the venue has it. Everything else stays: LIMIT, BUY,
qty == 1, price strictly inside (0,1), no reduce-only, no display_qty, no trigger.

**RED tests (per-leg, L-44):** an untagged GTD BUY still refused byte-identically at
`submit_chain.py:296`; an untagged post-only BUY still refused at `:309`; a tagged resting
order whose leg/qty/price contradicts its authorization refused (mirroring `:445-460`);
`build_resting_order_body` emits `goodTillTime` / omits `synchronousExecution`+`maxBlockTime`
only if §4.1 says so. `ORDER_BODY_KEYS` (`:92`) gains a **separate** resting frozenset, never
a widened one.

### §4.3 The cancel write path — a genuinely new write surface

`_cancel_order` (`client.py:3610`) stops refusing and issues the venue cancel;
`_cancel_all_orders` (`:3632`) stops raising and issues cancel-all (needed by §4.8's kill).

Pin widenings, all **additive**: egress firewall rule **V2** — the cancel verbs remain E3
surfaces (`test_execution_egress_firewall_guard.py:213-227`) and the expected-module set at
`:710` gains the cancel path in the *same commit* (the mechanism working as designed, not a
bypass); readonly-guard cage (`test_polymarket_us_readonly_guard.py:183-202`) admits the
cancel endpoint's write verb for exactly the cancel module, with a `:991`-style non-vacuity
test proving removal trips the scan; `scripts/ci/run_tests_no_egress.sh` stays green — the
netns gate is what makes this additive rather than dangerous.

**RED tests:** a cancel with no resting order refuses; a cancel for a foreign order id
refuses; a cancel whose response does not confirm escalates per §4.8 (never a silent no-op —
`client.py:3643`'s stance).

### §4.4 Boot-time open-order reconciliation (SP-3 B1/B2 shape)

Before any arm, walk `GetOpenOrders` for the family's slugs and cross it with
`cache.orders_open` (`resting_ladder.py:262`):
both empty → proceed; ours, recognised, still valid → adopt it; **anything unexpected →
cancel-all + durable family halt** (§4.8). L-38: a stop that cannot fire is missing, so the
halt is written durably, never merely logged.

### §4.5 A RESTING state in the intent latch

`SubmitIntentState` (`submit_intent.py:68`) gains `RESTING`.
`SubmitIntent.__post_init__` (`:241-249`) gains its invariants; `arm` (`:388`) keeps
refusing while another intent is OPEN.

Invariants: **at most one resting order per (station-day, leg)** — a RESTING intent does not
block the sibling leg's resting order, and does block a second order on the same leg;
entries and exits stay mutually exclusive with any in-flight submit.
`reconcile_at_startup` (`:438`) extends so a RESTING singleton resolves via `GetOpenOrders`
+ fills, **not** the fill-record probe alone. **AMBIGUOUS for a resting order** is resolved
by GET open-orders *and* GET fills: still open → RESTING; filled → retire with a fill reason;
absent from both → retire as cancelled *only* on venue-confirmed absence, else stay latched
(fail closed, `:451`'s stance).

This retires L-36's assumption — recorded explicitly: the latch's docstring claim that
*nothing of ours can rest* becomes false at this increment and must be rewritten in the
same commit.

### §4.6 Maker fills and the maker fee

`Execution.aggressor` (`orders.py:107`) and `makerCommissionsBasisPoints` (`:92`) are the
evidence. Rules:
Fee is taken **at the fill price**, from the venue's reported `commissionNotionalCollected`
(`:108`) where present, never recomputed optimistically. If the maker schedule differs from
`θ=0.06` (`config.py:226`), the `fee_schedule_mismatch` admission refuse
(`PREREG_v3…:170`) applies to the maker θ as its own, *second* pinned coefficient — never an
edit of the taker one. **Until §4.1 measures it, §1/§2 use the taker fee as an upper bound:**
an unexpectedly lower maker fee only improves the edge; assuming one would not.

### §4.7 Operator caps — the reservation rule

Reuse `DailySpendLedger` unchanged (`operator_controls.py:263-490`):

> **At REST:** the order's cost (`order_cost_usd`, `:230`, cost-before-fee, rounded up to the
> cent, `:220`) is checked against the **per-order cap** and booked via
> `authorize_order_cost` (`:347`) as a *reservation*.
> **On CANCEL / expiry:** `release_booking` (`:456`) returns it — a cancelled bid consumes
> no budget.
> **On FILL:** `true_up_booking` (`:476`) makes the reservation permanent at the fill price;
> **this is the moment the daily budget is consumed.**

Consequence, stated plainly: a resting bid reserves against the per-order cap while it
rests, and spends against the daily budget only when it fills. Concurrent resting orders are
each individually capped, and their *reservations* jointly cannot exceed the daily budget —
which is what `authorize_order_cost`'s `_spent_usd + cost > daily_budget` check
(`:417-421`) already enforces. **No new operator control. No new env var.**

### §4.8 Kill

Durable family halt + cancel-all on: any unexpected open order at boot (§4.4); any cancel that
fails or does not confirm within the PROVISIONAL 30 s; any fill at a price other than our
resting price; a second resting order on a (station-day, leg); a resting order that took on
entry (§3). The halt is written durably, survives restart, and refuses re-arm until cleared
with evidence — the `entry_only_halt` (`config.py:234`) shape.

## §5 Safeguards and observability

- **Decisions tape:** `OfferTapeRecord.decision_kind` (`offer_tape.py:143`) gains `rest`,
  `reprice`, `cancel`, `rest_fill`; each row carries `p*`, `m`, `edge(p*)`, `p_bound`, the
  maker BE, staleness, cell, leg, and for `cancel` the **cancel reason code**. The 16 strict
  legacy keys (`:59`) are untouched — additive only, as with the exit fields (`:150-165`);
  byte cap (`:305`) unchanged.
- **Nightly series** (extending `position_monitor_nightly_report.py`'s pattern): rests,
  re-prices, cancels by reason, fills, time-at-rest distribution, and realised `π̂_I` vs §2's
  prediction. **A live `π̂_I` outside §2's interval is an alert, not a curiosity** — it is the
  model being wrong.
- **Alerts:** cancel failure; a resting order outliving the window; an open order the latch
  does not know; a maker fill reported TAKER; fill price ≠ resting price; reservation/ledger
  divergence.

## §6 Deployment

1. **Shadow.** Rest decisions computed and persisted to the tape; **no venue write**
   (`orders_enabled=False`, `config.py:237`; no resting authorization minted). Runs beside
   live v3. Exit criterion: ≥ 10 station-days where the shadow's modelled rests and cancels
   reconcile against the Depth10 tape with no unexplained divergence from §2.
2. **Positive control.** One 1-contract rest far from the touch, then cancel it — proving the
   rest *and* the cancel round-trip. **Automated, per the ruling that OP-1/OP-3 are the bot's
   job, never a UI step.** Success = venue-confirmed rest then venue-confirmed cancel, both
   ends in the tape.
3. **Enable per family registration.** `pm_us_crh_rest_v5` armed for one station, then
   widened. D0 is the first armed day.
4. **Rollback** = cancel-all + manifest flip to the prior registration. v3 is never modified,
   so rollback is a flip, not a revert.

## §7 Open questions

**Operator-budget questions: none.** The two caps (`operator_controls.py:131`, `:173`) are
sufficient: §4.7 expresses resting reservation entirely within the existing per-order cap and
daily budget, and every other constant (`m`, `k`, `λ`, the 30 s cancel deadline, the halt
rules, enablement, family registration) is build-side and either registered in §3 or
measured in §2.

Build-side unknowns, all resolved by §4.1 before any write, none needing the operator:
venue TIF acceptance and `goodTillTime` format; post-only availability;
**cancel granularity (slug-scoped vs order-scoped)**; the maker fee schedule.

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
