# PREREG v4 — current_rung_hold with registered EXIT (Polymarket.us) — successor family (DRAFT, NOT REGISTERED)

**Status: DRAFT_NOT_REGISTERED (2026-09-16). D0 unpinned.**

A **CLASS (C) new family**: v3 registered the action "IOC, hold to settlement"; `pm_us_crh_exit_v4` sells a held position mid-day under a registered rule. Per **L-34** a change to the registered ACTION is a new family, not an amendment — `n` resets to 0, v3's `n` is never carried forward, and registration (`status → REGISTERED` with a real `boundary_inputs_sha256`) must land **before the first affected fill**. The ENTRY selector, the confirmatory statistic and every sequential parameter are UNCHANGED from v3: this family differs from `pm_us_crh_cont` in exactly one respect — what it does with a position it already holds. `allow_short` stays `False`; Nautilus is untouched; v1/v2/v3 code paths byte-identical.

Companion plan `docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md` (Rev 2). v3 source `docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md` (cited "v3 §n:lines"); NO-side amendment `docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md`.

---

## 1. Family Registry — **NEW**

| Property | Value |
|---|---|
| `family_id` | `pm_us_crh_exit_v4` |
| `venue` | `polymarket_us` |
| `trial_id_prefix` | `current_rung_hold_exit/trial/` — new prefix; separates v4 rows from `pm_us_crh_cont`'s by prefix AND `d0_climate_day`, the two discriminants of `persistence/family_manifest.py:13-21` |
| `stations` | LAX, MDW, MIA, SFO (UNCHANGED, v3 §1:14-21) |
| `status` | **DRAFT_NOT_REGISTERED** |
| `d0_climate_day` | **UNPINNED** — first climate day the exit path is armed; pinned at registration, never retroactive |
| `exit_rule` (manifest) | `"crh_exit_v4:R_THREAT_PRIMARY+R_DEAD_BACKSTOP"` |
| `boundary_artefact_path` | `deploy/families/gs_boundary_pm_us_crh_v2.json` (reused verbatim, §8) |
| Code registration | `persistence/exit_gate.py:47` `_EXIT_RULE_REGISTERED_FAMILIES` gains exactly this member; BOTH manifest declaration AND code frozenset are required (`:50-62`, L-22 unforgeable split) |

**Registration trigger.** `status → REGISTERED` + real `boundary_inputs_sha256` + D0 pinned, committed before the first fill that could be exited under §3b. A fill taken earlier belongs to `pm_us_crh_cont` and is scored under v3.

## 2. Selection Population — **UNCHANGED FROM v3** (§2:23-34)

Trigger, covariates (not H0 conditioning, L-18) and strata (pooled / station / ask-band, no venue stratum) byte-identical; the NO-side amendment's admission gates (amendment §4) carry forward per leg (L-44). **The exit rule never changes which trials enter the population** — it acts only after a fill.

## 3. Decision Rule (ENTRY) — **UNCHANGED FROM v3** (§3:36-52)

`held_i | ask_i ~ Bern(BE_i)`, `BE_i = entry_ask_i + fee_i`; fill-conditional; interior `m=1` illegal. Sequential monitoring verbatim: `S_k`, `I_k = Σ BE_i(1−BE_i)`, `t_k = min(1, I_k/I_max)`, `I_max = 40`, looks every 10 filled trials (`n_k = 10..160`), LD-OBF two one-sided α=0.025, efficacy/futility/truncation, terminal Wilson endpoints. The amendment's mixed-side variance (amendment §3) carries forward unchanged.

## 3b. Decision Rule (EXIT) — **NEW — the whole of v4's novelty**

Both rules are registered here, before the first affected fill; an unregistered rule may never be added to an armed family.

**Common preconditions (both rules), all required:** family code-registered AND declaring `exit_rule` (`exit_gate.py:50-62`); the position attributable to a Breezy-minted `client_order_id` via its Nautilus `position_id`; the book executable — `mark_source == "depth_walk"` AND `depth_sufficient` AND `book_staleness_ns <= _BOOK_STALE_NS` (`monitor_decision.py:338-345`, `:157`); the evaluation inside the decision window and before the day's stop; `quantity (1) <= attributed net long − working sell quantity`.

**R-THREAT (primary).** Fires on `state == THREATENED`, `verdict == REDUCE_RECOMMENDED`, confirmed by the registered hysteresis (`monitor_decision.py:366-408`), **and only if net proceeds at the walk-proved executable bid exceed `E[settlement | state]`**:
- Proceeds `recoverable_value = mark_vwap · held_qty − exit_fee` (`monitor_evidence.py:309-317`), with `mark_vwap` from `walk_exit_vwap`'s full-quantity walk of the executable side (`:162-201`; YES→bids, NO→`1 − ask_walk`) — never a mark, never an interpolation, never a public-info price (L-7/L-9).
- Estimator `E = p_hold · held_qty` (YES holding) / `E = (1 − p_hold) · held_qty` (NO holding), with `p_hold = monitor_evidence.p_hold_at(station, season, hour_lst, width_code, m_code, leg)` re-looked-up at the CURRENT cell — the lookup `build_monitor_evidence` already performs (`:289-296`). Archive-only, no new estimator. Both sides net of exit fee.
- **`p_hold_undefined` → NEVER fires** (`monitor_decision.py:426-429`): an exit without an estimate is a guess; refused with its own reason code.

**R-DEAD (backstop).** Fires on confirmed `DEAD_BY_OBSERVATION`, `verdict == EXIT_RECOMMENDED`, and `recoverable_value > 0` — `E[settlement | DEAD] ≈ 0` is the measured content of DEAD, so no cell estimate is needed. Measured on the 2026-09-15 tape to recover ≈0 (the exit side emptied before DEAD confirmed); registered because it is the literal reading of the operator ruling and is the rule that fires when a thesis dies *before* liquidity leaves. **`MISSING_STOP` never authorises an order** — alert only (L-38).

**Order shape (both rules).** `quantity = 1`; **IOC LIMIT at the proven bid**; `reduce_only = False` (no such venue field); **never MARKET** — which is also why Nautilus's native `Strategy.close_position` is unusable (it constructs a MarketOrder, `trading/strategy.pyx:1351-1416`). Submitted as `submit_order(order, position_id=position.id)`, so Nautilus owns attribution and netting. **Exactly one order per authorisation**; a second authorisation for the same `position_id` inside the rule's confirmation span refuses; a per-station-day cap bounds a flapping book. One contract per authorisation matches the venue's 1-contract mappability rule (`exec/submit_chain.py:295-296`), so partial fills cannot occur.

**PROVISIONAL constants — all UNCALIBRATED on a 1-clean-day corpus; source lines in `src/breezy/strategy/current_rung_hold/monitor_decision.py`:** `_P_HOLD_DROP_MARGIN = 0.10` (`:149`); `_THREATENED_CONFIRMATIONS = 3` (`:150`); `_THREATENED_MIN_SPAN_NS = 10 min` (`:151`); `_DEAD_CONFIRMATIONS = 2` distinct observation instants (`:152`); `_DEAD_MIN_CONFIRM_SPAN_NS = 5 min` (`:154`); `_LOCKED_HOUR_LST = 18` (`:155`); `_BOOK_STALE_NS = 180 s` (`:157`). Each is **PROVISIONAL** and class-C (§7): none may be tuned off live firings without a registered amendment.

## 4. AMBIGUOUS-Resolution Gate — **UNCHANGED FROM v3** (§4:54-72), extended to the exit leg

The bounded GET resolver, its durable pre-write and its fail-closed rules (GET failure, 5xx, malformed, PENDING, not-found, retry exhaustion are never terminal evidence) apply verbatim to an exit order. A GET timeout or 5xx during an exit routes through this resolver, never a re-send.

## 4a. Resolution H (L-32 / R-7 §5 ruling) — **UNCHANGED FROM v3** (§4a:74-78)

`classify_create_order_outcome` stays byte-unchanged; a GET is new evidence, never a reclassification.

## 5. Residual Classification & Contract-Unit Halt — **UNCHANGED FROM v3** (§5:80-104), plus one v4 rule

Three mutually exclusive first-match-wins buckets (`duplicate_fill`, `q≠1`, `fee_unreconciled`), `total_pnl = scored_pnl − residual` in contract-units, the `total_pnl ≤ −60` halt, the re-arm floor and the attempt counter are carried over verbatim. **v4 addition:** a GET-resolved **exit** leg is `fee_unreconciled` residual and never grows `n` — the same treatment v3 gives a resolver-recovered entry fill; a trial with an admissible entry and a resolver-recovered exit is scored residual, never dropped.

## 5b. Exit Kill Rule — **NEW, TWO layers (corrected in review, finding B, 2026-09-16)**

An exit order whose outcome is **AMBIGUOUS or rejected** is covered by two distinct, durable layers —
corrected from the original single-mechanism statement above, which described only the venue-side
reject/deny path and missed that a POST exception or a `KIND_AMBIGUOUS` classification raises **no
order event at all** (`on_order_denied`/`on_order_rejected` are Strategy-hook overrides on an event
that, for this failure mode, is never delivered).

**Layer 1 — immediate, account-wide, no exit-specific code.** The existing `SubmitIntentLatch`
(`runtime/submit_intent.py:37,313`) is `arm()`-ed BEFORE the create-order POST, identically for an
entry and an exit. An AMBIGUOUS send therefore leaves the account-wide intent OPEN on disk the instant
it happens; every subsequent order of EITHER kind — entry or exit, this process or one restarted over
the same store — is refused (`submit_chain.OPEN_INTENT_WAIT_REASON`) until an operator retires the
intent with venue evidence via the durable-intent CLI. This is the SAME cover an AMBIGUOUS entry
already had.

**Layer 2 — durable family halt, checked on the strategy's own next tick.** `exit_wiring.
check_exit_intent_for_ambiguous_send`, injected into the position monitor and invoked at the top of
every evaluation once a prior exit has fired for that position, reads the account-wide intent
read-only (`TrialDayLatch.current_open_submit_intent()`, a pass-through to `SubmitIntentLatch.
current_open()` — never a venue poll). Once it can prove, by intent fingerprint, that THIS exit's own
intent is still the one OPEN and has sat open longer than a healthy round trip ever would (30s, above
the venue's own 5s `maxBlockTime`), it calls `record_ambiguous_exit` — the same durable state
`TrialDayLatch.is_family_halted` (`strategy/current_rung_hold/trial_day_latch.py:816`) reads, cleared
**only** by `clear_family_halt` (`:845`) via the operator CLI `clear_family_halt_cli.py`, and enforced
at the same chokepoints: `composition.py:190-221` `family_halt_submit_veto` (synchronous, pre-spend,
zero money moved) and `continuous_strategy.py:561,975`. A genuine venue-side reject/deny still sets the
SAME state directly, via `on_order_denied`/`on_order_rejected`, with no dependence on layer 2's tick
cadence.

Both layers are durable and survive the mid-session process death and relaunch that is routine on this
host: layer 1 needs no restart-specific code (the singleton is read fresh from the shared store on
every process); layer 2 re-evaluates from durable state on the strategy's very next tick after
restart, never from in-memory bookkeeping. A with-id AMBIGUOUS exit resolves through the SAME
GET-based resolver an entry does (`exec/client.py::_resolve_ambiguous_intents`); resolving it is a
NORMAL closure of the OPEN intent and does not bypass either layer above. **No automatic clearing of
the family halt, of any kind.**

## 6. Safety Pins — **UNCHANGED FROM v3** (§6:106-128), plus four exit safeguards on existing seams

SAFETY-C1's authoritative pre-spend `is_latched()` re-check, the guard-pin equalities and the never-arm startup gate carry over verbatim. v4 adds:
1. **Binding naked-short invariant:** `backtest_order_guard._refuse_naked_short` (`:221-291`), installed live by `install_live_order_guard` (`:407`) at `runtime/trade_cli.py:399`, reading the shared `Portfolio`/`Cache` per instrument — account-wide across all four station strategies. `_working_sell_quantity` (`:322-345`) counts every not-yet-closed SELL, in-flight included, so two arms or legs cannot double-sell. This, not any strategy-constructed object, is the invariant.
2. **One account-wide intent latch:** the existing `SubmitIntentLatch` (`runtime/submit_intent.py:37,313`, L-36) — an exit competes for the same singleton as an entry, so a cross-station exit/entry race is structurally impossible.
3. **Response-side leg check:** an exit echo table in `adapters/polymarket_us/leg_prices.py` (outside `exec/`, beside the BUY table at `:99-118`) refuses any echo that is not the exact documented pair for the leg, in both directions.
4. **Fill sign:** an exit fill is booked `SELL` in the native event and the durable record (`_RECORD_SIGNS`, `exec/client.py:434-437`), reducing the position rather than growing it.

## 7. Operator Controls & Class-C Scope — **UNCHANGED FROM v3** (§7:130-139)

Exactly two budget caps in `operator.env`, never valued in code. **v4 introduces no operator control and asks for no new value.** The daily budget is **GROSS entry spend**: an exit never calls `operator_controls.authorize_order_cost` (`adapters/polymarket_us/operator_controls.py:347`, called at `exec/client.py:3119`) and its proceeds never replenish entry headroom — a cap the day's sales could re-open is not a cap. **Class-C in v4 = any constant of the exit rules** (every §3b PROVISIONAL constant, the confirmation-span rate limit, the per-station-day cap, and the two firing thresholds): changing one is a registered amendment or a new family, never a tuning. **Build-side** = the order shape, the seams, the echo table, the halt plumbing, the persistence, the report.

## 8. Boundary Artefact — **UNCHANGED FROM v3** (§8:141-148)

The inputs manifest covers α / spending function / `n_max` / `I_max` / look schedule only and none change, so `gs_boundary_pm_us_crh_v2.json` is reused verbatim (`inputs_sha256 = 471fd8a7…c150e0c`). Re-run `scripts/analysis/crh_group_sequential_boundaries.py` at registration and pin the resulting `inputs_sha256` in the v4 manifest so provenance is v4's own.

## 9. Structural-Dead Test — **UNCHANGED FROM v3** (§9:150-154)

Window `[12:00, 17:00)` LST, 30 min afternoon-covered threshold, ≥15 covered listed station-days.

## 10. Frozen from v3 — **UNCHANGED** (§10:156-170), with ONE substitution

Everything in v3 §10 stays frozen: `n_max=160`, `I_max=40`, per-row `BE_i`, the sequential monitor, the LD-OBF solver, Wilson terminal endpoints, fixed strata, no venue stratum, the D0 climate-day discriminant, Kalshi's separation, `fee_schedule_mismatch` as a per-tick Refuse. **One item is replaced, for v4 only:**

- **v3's `held == (pnl > 0)` tally guard → an `exit_reason` provenance guard.** An exited row legitimately breaks that identity. Every v4 row declares `exit_reason ∈ {R_THREAT, R_DEAD, SETTLED}` plus a realized `pnl` with its exit fills; a row whose `exit_reason` contradicts its fill history **refuses the tally**. `SETTLED` rows still assert the v3 identity. The v3 guard remains BINDING for `pm_us_crh_v2` and `pm_us_crh_cont`.

**The confirmatory outcome is the ENTRY thesis, not realized pnl.** `outcome_i = would_have_held_i`: did the settled CLI observation fall inside the rung the entry bought — **evaluated from settlement regardless of whether the position was exited**? For a never-exited position this is v3's `held` bit unchanged; for an exited one it is still computed from settlement data, which the exit cannot alter. `BE_i` is likewise unchanged by an exit. Consequence: the per-trial null stays `Bernoulli(BE_i)` and `I_k = Σ BE_i(1−BE_i)`, α, the look schedule and `n_max` carry over verbatim. Deriving a new per-trial null variance for a pnl endpoint is **explicitly rejected** — it needs a distributional model of exit prices for which no corpus exists.

## 10b. Descriptive Series (never the sequential endpoint) — **NEW**

Recorded per rule and reported nightly by `scripts/analysis/position_monitor_nightly_report.py` (`AvoidedLossSummary`, `:163-190`, already in total-position dollars, units-corrected): (1) **intervened vs control** — realized pnl where a rule fired vs settled pnl of same-cell-day positions where it did not; (2) **avoided loss** — `recoverable_value_at_signal` minus realized settled pnl; (3) **premature-exit rate** — share of firings whose position would have settled `held == True`. **The sequential test never reads them.** Pre-stated reading: after ≥20 firings, a rule whose intervened-minus-control is positive at a Wilson lower bound > 0 stays armed; a rule whose premature-exit rate outweighs its avoided loss is DISARMED by amending the manifest's `exit_rule` value — registered and diffable, never a silent threshold move. **Sample-size truth:** at ~1 trial/day/station the sign of R-THREAT's net benefit stays unknown for months; nothing here claims it will be shown to help this season.

## 11. Arming Gates — **NEW**

**Step 0 — offline exit-window replay study.** `scripts/analysis/current_rung_hold_exit_window_study.py`, stamp `20260916_initial`, over existing Depth10 tape + IEM observations; per position: the THREATENED and DEAD instants, the executable 1-lot exit price at each, the instant the exit side emptied, and counterfactual pnl for R-DEAD, R-THREAT and an R-BEST oracle against hold. Required because the 2026-09-15 no-trade diagnosis ruled **"no exits (no counterparty; L-7/L-9)"** — no rule arms on an assumed counterparty. Usable losing-position corpus **N ≈ 4–6** (one clean day, four positions), so these are **feasibility gates, not confirmatory tests**, registered before the numbers are read:
- **R-THREAT arms only if** it fires strictly before the exit side empties in **≥3 of N** positions AND Σ counterfactual pnl(R-THREAT) ≥ Σ pnl(hold) on the same tape AND ≥1 firing satisfied `recoverable_value > E[settlement | state]` (§3b's real condition, not a proxy).
- **R-DEAD arms only if** it fires before the exit side empties in **≥1 of N** positions; otherwise it is registered but recorded as expected-inert (what §3b predicts).
- **Either rule fails** if Σ counterfactual pnl < Σ pnl(hold), or if the R-BEST oracle is ≤ hold — the latter means no exit policy could have helped on this tape and **no rule arms**.
- A gate passed on N ≈ 4–6 licenses **arming for measurement**, never a claim of edge.

**Step 0b — RETIRED 2026-09-16 ~03:40Z** (plan Appendix A.1): the held NO is `netPosition −1 / qtySold 1 / qtyAvailable −1`, `avgPx 0.0900` NO-denominated and fee-inclusive; YES holdings `netPosition 1`, `avgPx` = fill + fee; `cashValue 0.01` on all four. The venue nets a NO as a short of YES; Breezy holds it as a LONG on the `^no` instrument, so the net-long guard reasons per Breezy instrument and any venue reconciliation applies the leg sign first. Original text: **value-capturing positions read.** `scripts/venue/polymarket_us_positions_value_capture.py` against still-open positions before settlement. Retires: how a held NO position is signed and denominated on `/v1/portfolio/positions` (`netPosition`, `qtyBought`/`qtySold`, `avgPx`, `costPerShare`, `positionId`) — every positions response on this host has been `{"positions":{}}`, so these VALUES have never been observed. Until retired, "quantity ≤ attributed net long" is arithmetic over an unverified NO-leg sign.

**Step 1 — RETIRED 2026-09-16 03:19Z** (plan Appendix A.2; no order created, state PENDING_NEW, id ""): YES + `ORDER_ACTION_SELL` → echo `ORDER_SIDE_SELL` / `ORDER_INTENT_SELL_LONG`; NO + `ORDER_ACTION_SELL` at wire 0.99 → echo **`ORDER_SIDE_BUY`** / `ORDER_INTENT_SELL_SHORT`. §6.3's exit echo table is pinned to these pairs (checked as a (side, intent) PAIR). Whether the venue books the fill as REDUCING is retired only by step 3's positive control (the preview cannot show it). Original text: **preview capture.** Closing-order preview for a held YES and a held NO; retires the `action`/`outcomeSide` pair, the `price.value` convention, the echoed `side`/`intent` (pinning §6.3's table), and that the venue reads the order as REDUCING rather than opening the opposite side. If reducing cannot be distinguished from opening, this step is NOT retired and step 3 stays blocked.

**Step 2 — declare the mapping** from the capture in a ruling doc; encode it with a test pinning the captured bytes.

**Step 3 — positive control, exactly one contract.** One station-day, one 1-contract exit under the armed rule; requires a non-AMBIGUOUS create-order classification, a durable `SELL` record, Nautilus net position reduced by 1, nothing credited to entry headroom, and an independent venue-side GET confirming the reduction. Any AMBIGUOUS outcome → §5b kill.

**Step 4 — registration and enable.** `status → REGISTERED`, D0 pinned, `exit_gate.py` member added — then armed, and only for `pm_us_crh_exit_v4`.

## 12. Acceptance Criteria (RED→GREEN before registration) — **NEW**

1. The exit gate is False for every other family and True for v4 only once the manifest declares `exit_rule`; a manifest-only or code-only declaration gates False.
2. An authorised exit maps to a venue body, while a bare SELL still refuses with v3's exact message (`exec/submit_chain.py:288-289` byte-unchanged); an exit fill is booked `SELL` in both the native event and the durable record and REDUCES the Nautilus net position.
3. Per leg (L-44): a YES exit and a NO exit, each with its own echo-table assertion.
4. R-THREAT refuses when `recoverable_value ≤ E[settlement | state]`, and refuses on `p_hold_undefined`.
5. An AMBIGUOUS or rejected exit halts the family and **the halt survives a process restart**.
6. A second exit for the same position inside the confirmation span refuses; the per-station-day cap refuses beyond its bound.
7. An exit fill never decrements the daily budget counter and never increases remaining entry headroom.
8. A shadow-configured monitor, or a gate-refused family, submits nothing; every exit decision — fired or refused — is persisted (offer-tape row + monitor summary) even when the order is refused.
9. The v4 tally refuses a row whose `exit_reason` contradicts its fill history; `SETTLED` rows still assert `held == (pnl > 0)`.

## 13. Contested & Unverified — v3 §13:206-220 carried forward in full, plus v4 items

- Whether a fillable exit window exists at all — the 09-15 tape shows the exit side emptied before DEAD confirmed, and the no-trade diagnosis ruled no counterparty. §11 step 0 decides it.
- Venue closing-order semantics: request shape, echo, proceeds/fee sign, and whether a priced IOC SELL is read as reducing. UNKNOWN until §11 steps 1–3.
- ~~NO-holding sign and denomination on the positions endpoint (§11 step 0b).~~ RETIRED 2026-09-16 (plan Appendix A.1).
- Every PROVISIONAL constant in §3b (1-day corpus), and whether R-THREAT's benefit has a positive sign at any attainable `n` this season.

## 14. Reference — **UNCHANGED FROM v3** (§14:222-233), plus

`strategy/current_rung_hold/monitor_decision.py` (states, verdicts, hysteresis, PROVISIONAL constants); `monitor_evidence.py` (`walk_exit_vwap`, `recoverable_value`, `p_hold_at`); `persistence/exit_gate.py`; `persistence/family_manifest.py`; `docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md` (Rev 2); `docs/plans/REDUCE_ONLY_BYPASS_2026-09-02.md` (§1/§2 landed; the guard is the binding invariant). Lessons: L-1, L-7/L-9, L-12, L-18, L-22, L-34, L-36, L-38, L-44.

## 15. Changelog (v3 → v4)

- **NEW family** `pm_us_crh_exit_v4`, new trial prefix, `n` resets to 0, D0 unpinned (§1).
- **NEW §3b** R-THREAT + R-DEAD registered: rule, thresholds, confirmation, sizing, order shape, rate limits, and every PROVISIONAL constant with its source line. **NEW §5b** exit kill rule. **NEW §10b** descriptive series. **NEW §11** arming gates. **NEW §12** acceptance criteria.
- **§10 substitution:** `held == (pnl > 0)` → `exit_reason` provenance guard, v4 only; the confirmatory outcome stays the ENTRY thesis (`would_have_held`), so `BE_i`, `I_k`, α, looks and `n_max` are unchanged.
- **§7 clarified:** class-C = any exit-rule constant; daily budget is gross entry spend; no new operator value.
- **UNCHANGED:** §2, §3, §4, §4a, §5 (buckets and halt), §6 (v3 pins), §7 (the two caps), §8, §9, §10 (all but the one substitution), §13 (v3 items), §14.

## 16. Registration record — **EMPTY (not registered)**

No registration has occurred. `deploy/families/pm_us_crh_exit_v4.json` carries `status: "DRAFT_NOT_REGISTERED"` and the all-zero `boundary_inputs_sha256` placeholder, which `load_family_manifest` refuses unless a caller explicitly passes `allow_draft=True`. Registration requires §11 steps 0–3 retired, this section filled with the D0 and commit sha, and the `exit_gate.py` member added in the same change.
