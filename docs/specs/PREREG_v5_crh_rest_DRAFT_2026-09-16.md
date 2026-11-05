# PREREG v5 — current_rung_hold with a RESTING BID entry (Polymarket.us) — successor family (DRAFT, NOT REGISTERED)

**Status: DRAFT_NOT_REGISTERED (2026-09-16). D0 unpinned. n = 0.**

A **CLASS (C) new family**: v3 registered the action "IOC take at the first executable snapshot"; `pm_us_crh_rest_v5` **rests a bid** at the price where the archive edge is confident and lets the counterparty come to it. Per **L-34** a change to the registered ACTION is a new family, not an amendment — `n` resets to 0, v3's `n` is never carried forward, and registration (`status → REGISTERED` with a real `boundary_inputs_sha256`) must land **before the first rested order that could fill**. The ENTRY THESIS, the confirmatory statistic and every sequential parameter are UNCHANGED from v3: this family differs from `pm_us_crh_cont` in exactly one respect — *how* the position is acquired. `allow_short` stays `False`; Nautilus is untouched; v1/v2/v3/v4 code paths byte-identical.

Companion plan `docs/plans/RESTING_BID_HUNT_2026-09-16.md` (Rev 2), cited "plan §n". v3 source `docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md` (cited "v3 §n:lines"); NO-side amendment `docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md`; sibling exit family `docs/specs/PREREG_v4_crh_exit_DRAFT_2026-09-16.md`.

---

## 1. Family Registry — **NEW**

| Property | Value |
|---|---|
| `family_id` | `pm_us_crh_rest_v5` |
| `venue` | `polymarket_us` |
| `trial_id_prefix` | `crh_rest_v5/trial/` — new prefix; separates v5 rows from `pm_us_crh_cont`'s and `pm_us_crh_exit_v4`'s by prefix AND `d0_climate_day`, the two discriminants of `persistence/family_manifest.py:13-21` |
| `stations` | LAX, MDW, MIA, SFO (UNCHANGED, v3 §1:14-21) |
| `status` | **DRAFT_NOT_REGISTERED** |
| `d0_climate_day` | **UNPINNED** — the first climate day a resting order is armed; pinned at registration, never retroactive |
| `boundary_artefact_path` | `deploy/families/gs_boundary_pm_us_crh_v2.json` (reused verbatim, §8) |
| Kalshi sibling | never pooled; own PREREG, own D0 (v3 §10:156-170) |

**Registration trigger.** `status → REGISTERED` + real `boundary_inputs_sha256` + D0 pinned, committed **before the first rested order that could fill**. A rest submitted earlier is a defect, not a trial (§5b). An IOC take on the same day belongs to `pm_us_crh_cont` and is scored under v3; the two families never pool.

## 2. Selection Population — **UNCHANGED FROM v3** (§2:23-34), with the RESTING action added

Trigger, covariates (not H0 conditioning, L-18), the legal-cell rule (`decision.py:291-302`) and the strata base (pooled / station / ask-band, no venue stratum) are byte-identical; the NO-side amendment's admission gates carry forward per leg (L-44). **The entry thesis is unchanged** — `p_bound` is the same archive Wilson lower bound per cell, `n_min = 90`, and the same cells are legal. What v5 adds is the **action**: instead of lifting the ask when `edge > 0`, the family **posts a bid at `p*`** (§3b) and takes the fill if one arrives. Selection therefore widens from *snapshots where the ask is already cheap enough* to *snapshots where a price exists at which we would be willing to buy* — a strictly larger population, which is exactly why this is class C and not an amendment.

## 3. Decision Rule (ENTRY THESIS) — **UNCHANGED FROM v3** (§3:36-52)

`held_i | · ~ Bern(BE_i)`; fill-conditional (filled orders only); interior `m=1` illegal. Sequential monitoring verbatim: `S_k = Σ(held_i − BE_i)/√Σ BE_i(1−BE_i)`, `I_k = Σ BE_i(1−BE_i)`, `t_k = min(1, I_k/I_max)`, `I_max = 40`, looks every 10 filled trials (`n_k = 10..160`), LD-OBF two one-sided α=0.025, efficacy/futility/truncation, terminal Wilson endpoints never sequentialized. The amendment's mixed-side variance carries forward unchanged. **Only the anchor of `BE_i` moves** — see §3b.

## 3b. Decision Rule (RESTING ENTRY) — **NEW — the whole of v5's novelty**

Registered here in full, before the first rest; an unregistered rule may never be added to an armed family.

**The resting price.** `edge_maker(p) = p_bound − (p + fee_maker(p))`.

> **p\*** = the **highest venue tick** with `edge_maker(p) ≥ m`, **strictly below the best ask**, clamped to the executable band `[0.05, 0.95]` (`config.py:227-228`) and strictly inside (0.00, 1.00) (`exec/submit_chain.py:307`).

A price at or above the best ask would cross and is refused: crossing is the v3 action, not v5's, and a rest that crosses on entry is a defect (§5b). `m` is **PROVISIONAL, initial candidate 0.03 probability** (source: plan §1.2; calibrated by plan §2 Arm A, registered at §11 step 6 — it is not registered by this draft).

**Order shape.** `quantity = 1` (`config.py:230`; one-contract mappability, `submit_chain.py:305`), LIMIT, BUY, **post-only iff the venue's `participateDontInitiate` is confirmed to reject-on-cross** (§11 step 4; live-proven to be *accepted* 2026-09-04, but its reject-on-cross semantics are not); **GTD to the decision-window end if the `goodTillTime` spelling is retired (§13), otherwise GTC with an unconditional cancel-at-close**. `allow_short` stays `False`; a NO rest buys the NO leg instrument, never a short of YES.

**Eligibility to rest.** Inside the decision window `[12:00, 17:00)` LST (`strategy.py:154-155`); cell legal; observation fresh (≤ 50 min, `config.py:85`); `θ` matches its pin; **no resting order live for this `(station, climate_day, leg)`**; no in-flight submit; `p*` exists.

**Re-price.** On **every** event that changes `p_bound` or the cell — a new observation, a running-max change, a rung change, an `hour_lst` rollover. Recompute `p*`; if it differs from the live resting price, **cancel-then-rest** (venue modify is cancel-replace → `REPLACED`, so it is neither cheaper nor easier to reconcile). **Never re-price upward past the best ask.**

**CANCEL triggers — the complete registered list.** Any one of: (1) the observation kills the rung (running max moves out / `r_dead`); (2) observation staleness exceeds the 50-min bound; (3) the decision window closes; (4) `p*` ceases to exist (`edge_maker(p) < m` at every tick); (5) a family halt; (6) node stop (`on_stop`); (7) a duplicate or unexpected open order; (8) **the SIBLING LEG FILLS, or the station-day trial latch is consumed** — `trial_day_latch` admits one trial per station-day, so a fill on either leg makes the other leg's bid ineligible. Trigger (8) is written **durably, under the same flock, BEFORE the sibling's fill is recorded**, so a crash between the two leaves the store reading *cancel required* rather than *nothing pending*; it is never best-effort and never in-memory only.

**Cancel latency assumption.** A cancel is modelled as taking **λ = 500 ms PROVISIONAL** (source: plan §2.1) from decision to venue effect, on top of the observation-poll lag of **300 s** (`ingest/nws_observation_config.py:41`). A fill inside `[t_kill, t_kill + λ]` is a modelled pick-off, not a surprise — it is counted and reported, never excluded. A cancel that is not **confirmed** (§4) within **30 s PROVISIONAL** (source: plan §1.3) escalates to §5b.

**Exclusivity — one resting order per `(station, climate_day, leg)`, durable.** Held in the resting-intent store (§6), keyed on that triple, bound to the same flock as the submit-intent singleton. A second rest on the same key is refused **and halts the family** (§5b). The two legs of one station-day may rest concurrently; different stations are independent; the transient submit-intent singleton still serializes every POST account-wide.

**Trial definition (registered).** A trial is a **RESTED bid that FILLED**: an order (a) accepted by the venue as resting and (b) subsequently filled, whole or part, at our resting price.
- **A cancelled rest is never a trial. An expired rest is never a trial. An unfilled rest is never a trial.** They are recorded on the decisions tape and counted in the descriptive series (§10b), and they never enter `n`, `S_k` or `I_k`.
- **A rest that is immediately crossed on entry is not a trial — it is a defect** and a durable family halt (§5b). It is a v3-shaped take taken under a v5 registration, which would silently pool two families.
- **`n` counts fills, not rests.** This is the material difference from v3, where `n` counted armed takes: a v5 look schedule advances only when a counterparty acts.

**Break-even — `BE_i` re-anchored to the FILL price.** `BE_i = fill_price_i + fee_maker(fill_price_i)`, where `fill_price_i` is the executed price (equal to `p*` for a clean maker fill) and `fee_maker` the fee **actually charged and reported by the venue** (`Execution.commissionNotionalCollected`). This replaces v3's `BE_i = entry_ask_i + fee_i`; the functional form of the statistic is untouched.

**The maker coefficient is documented, NOT wire-observed.** `Θ_maker = −0.0125` — a **REBATE** — is a documentation fact only (`adapters/polymarket_us/fees.py:63, 98`; `errors.py:307`; `backtest_order_guard.py:8, 213`; `docs/evidence/ladder_ev_peer_review_2026-09-07.md:26`). **Breezy has never observed a maker fill on this venue.** Therefore, until a real maker fill retires it (§11 step 4, §13):
- **`fee_maker` is priced at the TAKER coefficient `θ = 0.06`** (`config.py:226`) everywhere a number is needed — `p*`, `m`, every gate in §11, and `BE_i`. A rebate would make the true edge *larger* and `BE_i` *smaller*, so the taker value is a **strict conservative upper bound on cost**. The rebate is never taken as credit.
- A pinned maker coefficient (§11 step 4) that disagrees with the venue's echoed `makerCommissionsBasisPoints` is a `fee_schedule_mismatch` per-tick admission refuse (v3 §10:170), never a silent re-derivation.
- `fees.py:187` currently **raises `MakerRebateUnmodelledError` on any post-only order** because the model charges `+θ` where the venue documents `−0.0125`; Barrier F2 mandates that model under `BacktestEngine`. No backtest of this family may run post-only until §11 step 4 lands.

**Confirmatory statistic — UNCHANGED.** The outcome is still the ENTRY THESIS (`would_have_held`). `S_k`, `I_k`, `t_k`, `I_max = 40`, `n_max = 160`, look schedule every 10 **filled** trials, LD-OBF two one-sided α = 0.025, efficacy/futility/truncation, contract-unit halt — all verbatim from v3 §3:36-52. **Only `BE_i`'s anchor changed.**

**Pre-declared strata.** Station and ask-band (on the **fill price**) exactly as v3 (v3 §10:161). **NEW, because a v5 trial is counterparty-triggered and the fill event itself carries information:**

| Stratum | Levels | Role |
|---|---|---|
| **Time-to-fill** | `fast` < 60 s · `mid` 60 s–15 min · `slow` > 15 min, rest → fill | secondary **KILL only** |
| **Fill cause** | `I` (informed) vs `L` (liquidity), per the classifier below | secondary **KILL only** |
| Station · fill-price band | LAX/MDW/MIA/SFO · v3's ask bands read on the fill price | as v3 |

**Fill-cause classifier (registered).** A fill at `t` is `I` if the next observation moves the rung's `p_bound` down by more than **0.05 PROVISIONAL** within **600 s PROVISIONAL** of `t` (source: plan §1.4); else `L`. **This is a LOWER bound on adverse selection, not an estimate of it** — it misses slow drift, non-NWS information held by the counterparty, and cell coarseness. Reported with a Wilson interval; the true `π_I ≥ π̂_I`.

**Primary-statistic decision (registered, before D0).** The **primary SURVIVE statistic is computed over ALL fills**. The `I` stratum and the `fast` time-to-fill stratum are **pre-declared secondary KILL criteria**: either stratum's own `S_k` crossing its futility boundary at a scheduled look **KILLs the family**, even while the pooled statistic is favourable. **No stratum can ever produce a SURVIVE** — strata kill only, so the α spend stays on the single pooled efficacy boundary and no multiplicity correction is owed. Time-to-fill bands and the `I/L` classifier are registered here and may not be moved after D0 without a new family.

## 4. AMBIGUOUS-Resolution Gate — **UNCHANGED FROM v3** (§4:54-72), re-scoped for a resting order

The bounded GET resolver, its durable pre-write and its fail-closed rules (a GET failure, 5xx, malformed body, PENDING state, not-found, or retry exhaustion is never terminal evidence) apply verbatim.

**What changes is which outcomes are ambiguous at all.** v3's residual AMBIGUOUS shape exists because a synchronous IOC returns `{id, executions}` with no terminal state, so an empty `executions` is indistinguishable from a timeout. A **resting** order has a different truth:

- **ACCEPTED-AND-WORKING IS NOT AMBIGUOUS** once the resting-intent store (§6) and the `GET /v1/orders/open` read-back exist. An order that the venue reports as open is `RESTING`, a known state with a durable record — not an unresolved intent. This retires, for this family only, the v3 posture that a non-filling submit leaves the account latched.
- **A CANCEL IS CONFIRMED ONLY BY A READ.** Per-order cancel is URL-id scoped and **returns no response body**; cancel-all's `{canceledOrderIds}` is an **echo, not a confirmation**; the private-WS ORDER channel is SDK-documented but **never wire-verified** (§13). A resting record therefore reaches `CANCEL_CONFIRMED` **only** after a post-cancel `GET /v1/orders/open` shows the order absent, or `GET /v1/order/{id}` shows a terminal `CANCELED`/`EXPIRED`. **A 200 is never a cancellation.**
- A fill arriving after `CANCEL_CONFIRMED` is not an ambiguity to resolve — it is a contradiction between the venue and our read, and it halts the family (§5b).

## 4a. Resolution H (L-32 / R-7 §5 ruling) — **UNCHANGED FROM v3** (§4a:74-78)

`classify_create_order_outcome` stays byte-unchanged; a GET is new evidence, never a reclassification.

## 5. Residual Classification & Contract-Unit Halt — **UNCHANGED FROM v3** (§5:80-104)

The three mutually exclusive first-match-wins buckets (`duplicate_fill`, `q≠1`, `fee_unreconciled`), `total_pnl = scored_pnl − residual` in contract-units, the `total_pnl ≤ −60` halt, the re-arm floor and the attempt counter are carried over verbatim. A GET-resolved (rather than create-path) fill remains `fee_unreconciled` residual and never grows `n`.

## 5b. Resting Kill Rules — **NEW**

Each of the following is a **durable family halt plus cancel-all**, written to the durable store, surviving process restart, and refusing to re-arm until cleared with venue evidence (the `entry_only_halt` shape, `config.py:234`; L-38 — a stop that cannot fire is missing):

1. **Any unknown open order at boot** — an open order the resting store does not recognise (§6 fail-closed boot).
2. **Cancel failure, or no `CANCEL_CONFIRMED` within 30 s PROVISIONAL** (plan §1.3) of the cancel decision.
3. **An immediately-crossed rest** — a rest that takes on entry (it is a v3 action inside a v5 registration).
4. **A fill after `CANCEL_CONFIRMED`** — the venue and our read-back contradict each other.
5. A **second resting order** on one `(station, climate_day, leg)`.
6. A fill **reported TAKER on a post-only order**, or at a **price other than our resting price**.
7. An **open-order enumeration failure** at boot (never an assumed-empty book).

The contract-unit halt (§5) is unchanged and independent of these.

## 6. Safety Pins — **UNCHANGED FROM v3** (§6:106-128), plus four v5 pins

v3's pre-arm race check (SAFETY-C1), the `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` equality pin, the await-exemption pin and the never-arm startup gate carry over verbatim. Added:

- **P1 — zero-call-sites pin.** Until the resting-intent store lands, a RED test asserts **no strategy module constructs a `RestingAuthorization`-tagged order and nothing calls `build_resting_order_body`** — the posture `write_transport.post_cancel_all` (`:160`) has held since it shipped. The pin is removed only in the commit that wires the resting path.
- **P2 — keyed resting store, SEPARATE from the submit-intent singleton.** `SubmitIntent` is ONE global record (`runtime/submit_intent.py:37`, `:233-249`) and may **not** gain a `RESTING` state: a second `arm()` would clobber it or serialize the account to one resting order. The resting store is keyed `(station, climate_day, leg)`, bound to the same flock via `shared_state_binding()` (`:496-514`), keyed as `station_day_admission` keys (`trial_day_latch.py:1383-1420`) with an **explicit index** because `StateStore` has no key enumeration (`:1405-1412`). The singleton keeps its exact current meaning: a transient one-POST-at-a-time serializer.
- **P3 — fail-closed boot.** The never-arm walk enumerates open orders and **refuses to arm anything — IOC entries and exits included — until every open order is enumerated and either adopted or cancelled.**
- **P4 — caps at rest vs at fill.** Reserve against the **per-order cap at REST** (`authorize_order_cost`, `operator_controls.py:347`); **release on `CANCEL_CONFIRMED` or expiry** (`release_booking`, `:456`) — a cancelled bid consumes no budget; **consume the daily budget at FILL** (`true_up_booking`, `:476`) at the fill price. Joint reservations cannot exceed the daily budget, already enforced at `:417-421`.

## 7. Operator Controls — **UNCHANGED FROM v3** (§7:130-139)

Exactly two budget caps: the daily budget cap and the per-position (per-order spend) cap, both in `operator.env`, memory/shell-only. **No new operator value is introduced by this family** — §6 P4 expresses resting reservation entirely inside the existing two. Enablement flags, PREREG status, session ceilings and operator id remain build-side derived or constant. The −60 contract-unit halt is never configurable.

## 8. Boundary Artefact — **UNCHANGED FROM v3** (§8:141-148)

Same solver, same inputs (two one-sided α=0.025, LD-OBF spending of `t`, look schedule `n_k = 10..160` step 10, `I_max = 40`), same `inputs_sha256` discipline; `deploy/families/gs_boundary_pm_us_crh_v2.json` reused verbatim.

## 9. Structural-Dead Test — **UNCHANGED FROM v3** (§9:150-154)

## 10. Frozen from v3 — **UNCHANGED** (§10:156-170), with ONE substitution

Everything frozen in v3 §10 stays frozen. **The single substitution:** `BE_i = entry_ask_i + fee_i` → `BE_i = fill_price_i + fee_maker(fill_price_i)` (§3b), which is a change of anchor, not of form — `S_k`, `I_k`, α, the look schedule and `n_max` are unchanged. `v1 byte-identical` still holds; v3 and v4 paths are untouched.

## 10b. Descriptive Series (never the sequential endpoint) — **NEW**

Recorded per station-day and reported nightly: rests placed, re-prices, cancels by trigger (the eight of §3b), unfilled-rest count, time-at-rest distribution, time-to-fill and fill-cause stratum counts, and realised `π̂_I` against the plan §2 prediction. **The sequential test never reads them.** Pre-stated reading: a live `π̂_I` outside the study's interval is an alert — π̂_I is a lower bound, so exceedance is the expected direction of failure. **Sample-size truth:** `n` grows only when a counterparty sells to us; at an unknown fill rate the time to `n = 10` is unknown and nothing here claims it is attainable this season.

## 11. Arming Gates — **NEW**

**Step 1 — Arm A, the offline depth proxy** (plan §2.1). Counterfactual study over existing Depth10 tape + IEM observations; fill-eligible event = the **transition** `ask > p*` → `ask ≤ p*`, one event, discounted by queue share `s` (**PROVISIONAL, reported over `s ∈ {0.25, 0.5, 1.0}`**, source plan §2.1), with the cancel race modelled at `λ` and the observation lag at 300 s. Gates, **verbatim from plan §2.4**:

| Gate | Threshold (PROVISIONAL, source plan §2.4) |
|---|---|
| G-R1 honest N | ≥ 150 modelled fills, ≥ 25 station-days, **≥ 12 distinct climate days**, ≥ 3 stations — **NOT MET TODAY: 7 distinct climate days** (27 supported station-days, LAX 7 / MDW 6 / MIA 7 / SFO 7, 2026-09-03…09-11; counted 2026-09-16) |
| G-R2 profitability | `Ê[pnl\|fill] > 0` with a **climate-day-bootstrap** lower bound > 0 at α=0.05 |
| G-R3 adverse-selection precision | Wilson **half-width on `π̂_I` ≤ 0.08**, *and* G-R2 survives at `π_I` = the interval's upper end — π̂_I being a lower bound, a wide interval is a fail, not a pass |
| G-R4 dominance | maker `Ê[total pnl]` over the day set exceeds the IOC baseline's on the same days |
| G-R5 robustness | G-R2 holds at every `s ∈ {0.25,0.5,1.0}`, both frame-gap conventions, and under `fee = fee_taker` |
| G-R6 tape honesty | zero station-days admitted from a truncated/stranded slice (ING-1); coverage asserted, never silently zero-filled |

**Step 2 — TRADE-print re-run.** The recorder subscribes the market `TRADE` channel (capture increment starting 2026-09-16/17; the channel has never been subscribed). Once **≥ 20 station-days PROVISIONAL** (source plan §2.2) of prints exist, Arm A is re-run with print-based fills — a print at or below `p*` whose *maker* side matches our leg is a real maker fill, capturing the case the depth proxy structurally cannot (a marketable sell walking *down through* resting bids). **The print `quantity` unit is UNRESOLVED (§13)** and must be cross-checked against `Depth10` sizes and `minimumTradeQty` before any count derived from it is read. The print-based re-run, not the depth proxy, is the intended basis for the registered `m`.

**Step 3 — maker-fee branch.** `fees.py` gains a correctly-signed maker branch with `Θ_maker` pinned as a **SECOND** coefficient under `fee_schedule_mismatch`; the taker coefficient is untouched and `MakerRebateUnmodelledError` keeps firing for every unpinned post-only order. Prerequisite for any `BacktestEngine` arm (Barrier F2).

**Step 4 — venue discovery.** Retire, by preview and the existing write-signing-probe route: the **per-order cancel** request shape and what its bodyless 200 does and does not assert; the **`goodTillTime` vs `GOOD_TILL_TIME` spelling** if GTD is chosen over live-proven GTC; `participateDontInitiate`'s reject-on-cross semantics; and the live `makerCommissionsBasisPoints` on a real maker fill. Evidence lands under `docs/evidence/venue/polymarket_us/`.

**Step 5 — shadow.** Rest decisions computed and **persisted to the decisions tape with no venue write** (`orders_enabled=False`, `config.py:237`; no `RestingAuthorization` minted — §6 P1). Runs beside live v3. Exit criterion: ≥ 10 station-days on which the shadow's modelled rests and cancels reconcile against the Depth10 tape with no unexplained divergence from step 1.

**Step 6 — positive control, automated, 1 lot, BOTH cancel verbs.** Through the *adapter*, not a probe script: rest one contract far from the touch, enumerate it via `GET /v1/orders/open`, cancel with the **per-order** verb, confirm absence via GET; then rest again and cancel with the **cancel-all** verb, confirm absence via GET. **Both legs must pass; a bodyless 200 is not a pass.** Automated — the operator is never asked to click (2026-09-04 ruling: the positive control is the bot's job).

**Step 7 — registration.** `status → REGISTERED`, D0 pinned, §16 filled, `m` and every constant promoted from PROVISIONAL to registered in the same commit.

**Step 8 — enable.** One station first, then widened. **Rollback** = cancel-all + manifest flip to the prior registration; v3/v4 are never modified, so rollback is a flip, not a revert.

## 12. Acceptance Criteria (RED→GREEN before registration) — **NEW**

1. A resting order maps to a venue body **only** when it carries a `RestingAuthorization`; an untagged GTC/GTD BUY still refuses byte-identically at `submit_chain.py:296`, and an untagged post-only BUY at `:309`.
2. The resting store holds **two legs of one station-day concurrently**; a second rest on the same `(station, climate_day, leg)` refuses and halts; a rest on one station does not block a rest on another; two POSTs can never be in flight even with two resting legs.
3. An IOC **entry** on an instrument with a live resting bid refuses; an IOC **exit** cancels the rest and waits for `CANCEL_CONFIRMED` before arming.
4. A crash between a sibling fill and the cancel write leaves the store reading *cancel required* (§3b trigger 8).
5. A bare 200 does **not** advance a record past `PENDING_CANCEL`; a private-WS `CANCELED` alone does not either; absence in a post-cancel GET does.
6. Boot refuses to arm when enumeration fails; an unknown open order halts; an adopted order reconciles into the store.
7. Per leg (L-44): a YES rest and a NO rest, each with its own body and echo assertion.
8. A cancelled rest **releases** its booking and never decrements the daily budget; a fill trues up at the fill price.
9. An immediately-crossed rest halts the family; a fill after `CANCEL_CONFIRMED` halts the family.
10. Every rest, re-price, cancel and fill is persisted to the decisions tape even when the order is refused; the v5 tally refuses a row whose cancel reason contradicts its fill history.

## 13. Contested & Unverified — v3 §13:206-220 carried forward in full, plus v5 items

- **The private WS ORDER channel is UNVERIFIED on the wire.** SDK-documented (snapshot + per-`Execution` updates, `aggressor`, `commissionNotionalCollected`); Breezy has never received one. No cancel, fill or state transition may be believed on its evidence alone (§4).
- **`goodTillTime` vs `GOOD_TILL_TIME` spelling drift** between the SDK types and the institutional insert-order documentation. Unretired until §11 step 4; GTC + cancel-at-close is the fallback precisely because it is live-proven.
- **Per-order cancel is bodyless.** `POST /v1/order/{id}/cancel` returns no response body, and cancel-all returns an echo. Confirmability, not granularity, is the open question.
- **The quantity unit is UNRESOLVED** — `Depth10` sizes, the venue's `minimumTradeQty` (1 → 0.01 at 2026-06-14) and the TRADE print's `quantity` have never been cross-checked against one another. Every §11 step-2 count derived from prints is provisional until they are.
- **`Θ_maker = −0.0125` is documented, never observed.** Until a real maker fill retires it, the taker coefficient is used as the conservative bound (§3b).
- Whether a resting bid on this surface is filled by anything other than an adversely-selected counterparty. The 2026-09-02 verdict (`docs/evidence/grok_no_edge_verdict_2026-09-02.md:25`) argues it is not; §11 step 1 decides it by measurement.
- Every PROVISIONAL constant in §3b and §11, and whether `n` reaches any look at an attainable fill rate.

## 14. Reference — **UNCHANGED FROM v3** (§14:222-233), plus

`docs/plans/RESTING_BID_HUNT_2026-09-16.md` (Rev 2, incl. Appendix A venue sweep); `adapters/polymarket_us/exec/submit_chain.py` (shape pins); `write_transport.py` (`post_cancel_all`, paths); `runtime/submit_intent.py`; `strategy/current_rung_hold/trial_day_latch.py`; `adapters/polymarket_us/fees.py` + `tests/unit/test_polymarket_us_fee_guard.py` (Barrier F2); `strategy/resting_ladder.py` + `tests/integration/test_resting_ladder_backtest.py` (native resting/cancel capability, an acceptance harness, not a production strategy). Lessons: L-1, L-7/L-9, L-12, L-18, L-22, L-23, L-34, L-36, L-38, L-44.

## 15. Changelog (v3 → v5)

- **NEW family** `pm_us_crh_rest_v5`, new trial prefix, `n` resets to 0, D0 unpinned (§1).
- **NEW §3b:** the resting rule registered in full — `p*`, margin `m`, order shape, eligibility, re-price, the eight cancel triggers, the cancel-latency assumption, one-rest-per-`(station, climate_day, leg)`, the trial definition (a filled rest only), `BE_i` re-anchored to the fill price, the documented-not-observed maker rebate, and the pre-declared time-to-fill and fill-cause strata with I/fast as KILL-only.
- **NEW §5b** resting kill rules. **NEW §10b** descriptive series. **NEW §11** arming gates (G-R1…G-R6 verbatim from plan §2.4, steps 1–8). **NEW §12** acceptance criteria.
- **§4 re-scoped:** accepted-and-working is NOT ambiguous once the resting store and GET read-back exist; a cancel is confirmed only by a post-cancel GET.
- **§6 + four pins:** zero-call-sites; keyed store separate from the submit-intent singleton; fail-closed boot; reserve-at-rest / release-on-cancel / daily-budget-at-fill.
- **§10 substitution:** `BE_i` anchor only. The confirmatory outcome stays the ENTRY THESIS, so `S_k`, `I_k`, α, looks, `I_max` and `n_max` are unchanged.
- **UNCHANGED:** §2 (population base), §3 (statistic), §4a, §5 (buckets and halt), §6 (v3 pins), §7 (the two caps), §8, §9, §10 (all but the one substitution), §13 (v3 items), §14.

## 16. Registration record — **EMPTY (not registered)**

No registration has occurred. `n = 0`. D0 is unpinned. `deploy/families/pm_us_crh_rest_v5.json` does not exist; when written it carries `status: "DRAFT_NOT_REGISTERED"` and the all-zero `boundary_inputs_sha256` placeholder, which `load_family_manifest` refuses unless a caller explicitly passes `allow_draft=True`. Registration requires §11 steps 1–6 retired, every PROVISIONAL constant in §3b promoted to a registered value, and this section filled with the D0 and commit sha — in the same change, before the first rested order that could fill.
