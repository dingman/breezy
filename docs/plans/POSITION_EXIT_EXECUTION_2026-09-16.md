# Position exit execution — design plan — **Revision 2**, 2026-09-16

Design only; no implementation. Every citation was read in this tree (branch
`feat/data-capture-and-risk`, merge `9ea9ac5`); Nautilus citations in
`.venv/lib/python3.13/site-packages/nautilus_trader` (exact-pinned `nautilus-trader==1.231.0`,
`pyproject.toml:11`), each grep with a positive control (L-8).

**Authorising ruling (operator, 2026-09-16, verbatim):** "The operator expects that one[ce] losing
positions are identified that they get sold." It overrides the registered "IOC, hold to settlement"
action for the live family `pm_us_crh_cont` and unblocks INC-9 of
`docs/plans/INTRADAY_POSITION_MONITOR_2026-09-15.md` §5. Everything below the two budget caps is
build-side and decided here.
## Changelog — Revision 1 → Revision 2

| # | Change | Why |
|---|--------|-----|
| C1 | **§2 confirmatory endpoint reverted to the ENTRY thesis** (`would_have_held` at settlement, whether or not the position was exited). LD-OBF's `I_k = Σ BE_i(1−BE_i)` variance model is carried over UNCHANGED; realized pnl, avoided loss and premature-exit rate are **DESCRIPTIVE** report series, never the sequential endpoint | Rev 1 changed the outcome to `pnl > 0` while reusing v3's variance. Once a rule converts outcomes, `pnl > 0` is not `Bernoulli(BE_i)` under H0, so the boundary would have been spent against a null it no longer tests (review BLOCK 1) |
| C2 | **New §4 step 0** — the offline exit-window replay study (`scripts/analysis/current_rung_hold_exit_window_study.py`, stamp `20260916_initial`) with pre-registered per-rule arming criteria, and **step 0b**, the value-capturing positions read | No rule may arm on an assumed counterparty: the 09-15 diagnosis ruled "no exits (no counterparty; L-7/L-9)". The tape says whether an exit was *ever* fillable (review BLOCK 2) |
| C3 | **R-THREAT's registered firing condition is `recoverable_value > E[settlement | state]`**, estimator named (`p_hold_at` at the CURRENT cell), `p_hold_undefined` → never fire. R-DEAD keeps `> 0` (E≈0, measured) | `> 0` fires on positions the archive still expects to settle profitably — a registered premature exit (review HIGH 3) |
| C4 | **§5 rewritten onto named seams**: the durable family halt (`TrialDayLatch.is_family_halted`/`record_duplicate_fill`/`clear_family_halt` + `family_halt_submit_veto`) carries the AMBIGUOUS-exit kill; the response-side leg check extends `leg_prices.assert_echo_matches_leg`; rate limit and budget each get an owning increment and a RED test | Rev 1's safeguards were prose. A safeguard with no seam and no RED test is a wish (review CRITICAL 5, HIGH 6, MEDIUM 8/9) |
| C5 | **X3 resolved as fact, not preference**: `SELL_LONG`/`SELL_SHORT` are DOCUMENTED (Appendix A) and both carry the banned `SELL_` token, so the closing-order classifier lives in `leg_prices.py` (outside `exec/`) and X3 needs **no** widening. `docs/evidence/RULING_x3_sell_long_sell_short_2026-09-16.md` is an INC-E1 deliverable. **No new file under `exec/`** — requirement, not preference (E0 classifies by path) | Rev 1 treated the collision as hypothetical; it is documented (review HIGH 7) |
| C6 | Corrections: the live net-long guard is named the **binding** invariant and `ExitAuthorization` demoted to a convenience value object; partial IOC fills stated impossible (`quantity == ONE` pinned); the exit-fee coefficient gets an explicit verification step | Rev 1 called a strategy-constructed dataclass unforgeable, which is exactly the class of claim R-6a deleted (review LOW 10/11, item 4) |

---
## §0 Measured facts

**Decision layer (merged, shadow-only).** `monitor_decision.py:164-172`
`ThesisState{ALIVE,THREATENED,DEAD_BY_OBSERVATION,LOCKED_BY_OBSERVATION,UNKNOWN}` +
`Verdict{HOLD,REDUCE_RECOMMENDED,EXIT_RECOMMENDED,MISSING_STOP}`. THREATENED candidate =
`p_hold_at_entry - p_hold_at_t >= _P_HOLD_DROP_MARGIN` (`:149` `0.10`, `:431-432`), flipped by 3
consecutive candidates spanning >=10 min (`:150-151`, `:366-408`); DEAD confirms on 2 DISTINCT
observation instants spanning >=5 min (`:152-154`, `:306-325`), keyed on `observed_at_ns` (`:291-303`).
`_dead_verdict` (`:338-345`) is already executability-aware — `EXIT_RECOMMENDED` only when
`mark_source == "depth_walk"` AND `depth_sufficient` AND `book_staleness_ns <= 180 s` (`:157`), else
`MISSING_STOP` (L-38). Every threshold is flagged **PROVISIONAL/UNCALIBRATED** (`:148-158`, corpus = 1
clean day). `monitor_evidence.py:162-201` `walk_exit_vwap` walks the real executable side for the full
held qty (YES→bids, NO→`1 - ask_walk`), returning `(None, False)` rather than a partial or interpolated
price; `:309-317` `recoverable_value = mark_vwap*qty - exit_fee`; `:289-296` re-looks-up `p_hold_at`.
`continuous_strategy.py:359,454-460` the monitor is an injected `PositionMonitor | None`, default
`None`, every hook a no-op; `:874-875` it receives real Nautilus `Position` objects.

**The 2026-09-15 replay (4 live positions).** All four reach DEAD, but the last executable 1-lot exit
was 0.04/0.01/0.01/0.01 at 18:07Z/20:03Z/19:36Z/20:12Z while DEAD confirmed
19:40Z/20:10Z/23:05Z/20:20Z. **Sell-on-DEAD recovers ~0.** The economic window, if one exists, is
THREATENED — and whether it exists is a measurement (§4 step 0), not an assumption: the 09-15
diagnosis ruled **"no exits (no counterparty; L-7/L-9)"** for that day.

**Gates that currently forbid an exit.** `persistence/exit_gate.py:47`
`_EXIT_RULE_REGISTERED_FAMILIES = frozenset()` (empty), `:50-62` requiring BOTH code registration AND
`manifest.exit_rule` (L-22 unforgeable split); `family_manifest.py:83,123,196-200` `exit_rule` is the
sole optional key, declaration only; `exec/submit_chain.py:288-289` `"only a BUY is mappable (a SELL
is a naked short); refusing"`, `:295-296` qty must be 1, `:301-302` reduce-only unmappable,
`:337-348` `build_order_body` hardcodes `"action": _ORDER_ACTION_BUY`; `PREREG_v3_..._2026-09-10.md`
(BINDING) registers the action as IOC, hold to settlement with a `held == (pnl > 0)` tally guard.

**Gates already CLOSED (contra Rev 1's blocker (d) — this plan's largest finding).**
`REDUCE_ONLY_BYPASS_2026-09-02.md` §1 and §2 have **landed**: `backtest_order_guard.py:221-291`
refuses a SELL exceeding the net long "INCLUDING a `reduce_only` one" and `:322-345` counts EVERY
not-yet-closed SELL, reduce-only included. §6's `submit_order_list` class is **closed** —
`_working_sell_orders` reads `cache.orders(...)` not `orders_open(...)` (`:290-320`) plus the
approved-but-not-cached shim, pinned by `tests/unit/test_runtime_backtest_order_guard.py:504,587,643,651,704`.
The guard is **live and account-wide**: `install_live_order_guard` (`:407`) at `trade_cli.py:399`,
reading the shared `Portfolio`/`Cache` per instrument, so it binds across all four station strategies
(VERIFIED). The surviving `xfail(strict=True)` pair (`test_runtime_live_order_guard.py:321,346`) pins
a measured **Nautilus** defect (`OrderInitialized.reconciliation` hardcoded `False`), not a Breezy
gap. `exec/client.py:434-437` `_RECORD_SIGNS` already maps `SELL → -1`.

**Fill-accounting defects a SELL would hit (fixed with the mapping, INC-E2).** `exec/client.py:2007`
and `:3282` hardcode `order_side=OrderSide.BUY` in `generate_order_filled`; `:1924` and `:3232`
hardcode `order_side=LONG_ONLY_SIDE` ("BUY", `:429`) in the durable record. An exit fill would be
booked as a BUY — the position would *grow* in Nautilus and in the ledger.

**Nautilus null hypothesis (L-1) — tested, split verdict.** **REFUTED for `Strategy.close_position`:**
`trading/strategy.pyx:1351-1416` constructs `self.order_factory.market(...)` — a MarketOrder,
hardcoded, no limit variant (`:1418-1490` `close_all_positions` likewise); the invariant is IOC LIMIT
at an executable bid, never MARKET, and `submit_chain.py:284-285` refuses any non-LIMIT order, so with
Nautilus immutable this is unusable as-is. **CONFIRMED for everything else:** `model/orders/base.pyx:913`
`Order.closing_side(position.side)`; `trading/strategy.pyx:1416`'s attribution idiom
`submit_order(order, position_id=position.id)`; `cache.pyx:5412 position()` / `:5585 positions_open()`;
`exec/client.py:1007` `OmsType.NETTING`, so Nautilus builds and nets Positions. **The exit primitive is
therefore native-shaped, not new infrastructure:** `order_factory.limit(side=Order.closing_side(...),
TimeInForce.IOC, price=<executable bid>)` + `submit_order(order, position_id=position.id)` — the two
calls `continuous_strategy.py:2143,2151` already makes for entries, plus `position_id` and the closing
side; Breezy decides WHEN and authorises the adapter mapping, Nautilus owns order, position and netting.
`reduce_only` stays **False** (no such venue request field, Appendix A; REDUCE_ONLY_BYPASS §1 ruled the
flag means nothing to the guard), so `submit_chain.py:301-302` is byte-unchanged. **Partial fills cannot
occur:** `quantity == ONE` is pinned at `submit_chain.py:295-296` and the body literal `"quantity": 1`
at `:341`, so every exit order is all-or-nothing and the per-decision sizing needs no partial accounting.

---
## §1 Goal state and the two rules to register

**Goal state.** The live family, on a day it is holding, evaluates every position on the existing
shadow cadence; when a registered rule fires AND the exit is executable AND every §5 safeguard passes,
it submits exactly one 1-contract IOC LIMIT closing order per authorisation at a price the depth walk
proves fillable, booked as a reducing fill in Nautilus, the ledger and the durable record; every
decision — fired, refused, skipped — is persisted.

**R-THREAT (primary, acting rule).** On `state == THREATENED` with `verdict == REDUCE_RECOMMENDED`,
confirmed by the existing 3-candidate / >=10-min hysteresis (`monitor_decision.py:366-408`), exit 1
contract per authorisation while `mark_vwap` exists, `depth_sufficient`, `book_staleness_ns <= 180 s`,
**and `recoverable_value > E[settlement | state]`** — not `> 0`.
- **Estimator (registered, archive-only):** `E = p_hold · held_qty` for a YES holding,
  `E = (1 − p_hold) · held_qty` for a NO holding, with `p_hold` =
  `monitor_evidence.p_hold_at(station, season, hour_lst, width_code, m_code, leg)` re-looked-up at the
  **current** cell — the lookup `build_monitor_evidence` already performs (`:289-296`), so no new
  estimator is built. `recoverable_value` is already net of `exit_fee`, so the comparison is
  net-of-exit-cost on both sides.
- **`p_hold_undefined` → never fire** (`monitor_decision.py:426-429`): an exit without an estimate is
  a guess. Refusal with its own reason code.
- One contract per authorisation, never the whole position in one order: it matches the venue's
  1-contract mappability rule (`submit_chain.py:295-296`), keeps each order individually attributable,
  and makes partial de-risking the default.

**R-DEAD (backstop).** On confirmed `DEAD_BY_OBSERVATION` with `verdict == EXIT_RECOMMENDED`, same
executability preconditions, threshold **`recoverable_value > 0`** — `E[settlement | DEAD] ≈ 0` is the
measured content of DEAD, so no cell estimate is needed. Measured to recover ~0 today (§0); registered
anyway because it is the literal reading of the ruling, it fires when a thesis dies *before* liquidity
leaves, and an unregistered rule cannot be added later without re-opening the family (§2).
`MISSING_STOP` never authorises an order; it stays an alert (L-38).

**Sample-size truth, plainly.** At ~1 trial/day/station, R-THREAT accumulates firings at a rate that
leaves **the sign of its net benefit unknown for months**. Nothing here claims R-THREAT will help this
season; the rules are registered so the family's behaviour is honest and its record admissible.

**How the measurement reads (DESCRIPTIVE, per C1).** Extend
`scripts/analysis/position_monitor_nightly_report.py` (`:163-190` `AvoidedLossSummary` already computes
avoided loss in total-position dollars, units-corrected) with three per-rule series: (1) **intervened
vs control** — realized pnl where a rule fired vs settled pnl of same-cell-day positions where it did
not; (2) **avoided loss** — `recoverable_value_at_signal` minus realized settled pnl; (3)
**premature-exit rate** — share of firings whose position would have settled `held == True`. These are
report series, **never the sequential endpoint** (§2). Pre-stated reading: after >= 20 firings, a rule
whose intervened-minus-control is positive at a Wilson lower bound > 0 stays armed; a rule whose
premature-exit rate outweighs its avoided loss is DISARMED by amending the manifest's `exit_rule` value
(a registered, diffable amendment), never by silently moving a threshold. Until then the constants stay
**PROVISIONAL** and the family is explicitly a calibration family.

---
## §2 PREREG v4 — successor family

A change to the ACTION is a new family, not an amendment of `pm_us_crh_cont` (L-34): the registered
action was "IOC, hold to settlement", and selling mid-day changes what a trial *is*.

- **Family id:** `pm_us_crh_exit_v4`. **D0:** the first climate day the exit path is armed; registration
  (status `REGISTERED`, real `boundary_inputs_sha256`) committed **before the first affected fill**. `n`
  resets to 0; v3's `n` is never carried forward.
- **Trial id prefix:** a new prefix, so `family_tally_v2.py` and `settlement/family_barrier.py` separate
  v4 rows by prefix AND by `d0_climate_day` (`family_manifest.py:13-21`).
- **Manifest `exit_rule`:** `"crh_exit_v4:R_THREAT_PRIMARY+R_DEAD_BACKSTOP"` — names both registered
  rules, so disarming one is a visible diff. **`exit_gate.py:47`** gains exactly one member,
  `frozenset({"pm_us_crh_exit_v4"})`; `pm_us_crh_cont`, `pm_us_crh_v2`, `kalshi_crh_v1` keep holding to
  settlement.

**The confirmatory endpoint is the ENTRY thesis, unchanged (C1, resolving review BLOCK 1).**
- **v4 trial outcome, precisely:** `outcome_i = would_have_held_i` — did the settled CLI observation fall
  inside the rung the entry bought, **evaluated from settlement regardless of whether the position was
  exited**? For a never-exited position this is v3's `held` bit unchanged; for an exited one it is still
  computed from settlement data (the rung and the settled observation), which the exit does not alter.
  `BE_i` (break-even implied by the entry fill and fee) is likewise unchanged by an exit.
- **Consequence:** the per-trial null stays `Bernoulli(BE_i)`, so LD-OBF's information
  `I_k = Σ BE_i(1 − BE_i)` carries over **verbatim**, with one-sided α=0.025, `n_max=160`, `i_max=40`,
  `look_step=10`, looks every 10 filled trials, the `q != 1` exclusion, the provenance sidecar
  (`{"provenance":"live"}`), the empty-store rule, the fill-time look-ordering sidecar, the
  duplicate-fill family halt, and PREREG v3's NO-side amendment
  (`docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md`) per leg (L-44). Option (b) — deriving a new
  per-trial null variance for a pnl endpoint — is explicitly **rejected**: it needs a distributional
  model of exit prices we have no corpus to fit.
- **`held == (pnl > 0)` guard:** replaced for v4 only (BINDING still for v2/v3) by a **provenance**
  guard, since an exited row legitimately breaks the identity. Every v4 row declares
  `exit_reason ∈ {R_THREAT, R_DEAD, SETTLED}` plus a realized `pnl` with its exit fills; a row whose
  `exit_reason` contradicts its fill history refuses the tally, and `SETTLED` rows still assert the v3
  identity exactly as before.
- **Realized pnl is recorded, never spent on the boundary** — `pnl`, avoided loss and premature-exit rate
  are nightly-report series (§1); the sequential test never reads them.
- **Residual rule carried forward:** a GET-resolved fill stays fee-unreconciled **residual** and never
  grows `n`, including an exit leg resolved that way; a trial with an admissible entry and a
  resolver-recovered exit is scored residual, not dropped silently.
- **Boundary artefact:** the inputs manifest covers alpha/spending/n_max/i_max/look_step only and none
  change, so re-run `scripts/analysis/crh_group_sequential_boundaries.py` and pin the resulting
  `inputs_sha256` in the v4 manifest, so provenance is v4's own.

---
## §3 Execution-seam increments, in dependency order

Every increment is RED-first, runs `scripts/ci/run_tests_no_egress.sh` plus `lint-imports`, and lands
with its own evidence. **Nothing in E1–E3 can reach the venue: the gate stays closed until E4.**

**INC-E1 — capability types, registration, X3 ruling (no order path).**
- Files: `persistence/exit_gate.py` (add `pm_us_crh_exit_v4`), new
  `deploy/families/pm_us_crh_exit_v4.json` (status `DRAFT_NOT_REGISTERED` first), new
  `strategy/current_rung_hold/exit_authorization.py` — a frozen `ExitAuthorization`: `family_id`,
  `position_id`, `client_order_id`, `leg`, `attributed_net_long`, `working_sell_qty`, `quantity`,
  `limit_price`, `rule`, `expected_settlement_value`, `decided_at_ns`, `book_staleness_ns`.
  Construction validates `quantity <= attributed_net_long - working_sell_qty`, a price strictly inside
  (0,1), a present `position_id`, and the rule's own threshold.
- **Deliverable:** `docs/evidence/RULING_x3_sell_long_sell_short_2026-09-16.md` — states that
  `ORDER_INTENT_SELL_LONG`/`SELL_SHORT` are DOCUMENTED venue tokens (Appendix A) both carrying the
  X3-banned `SELL_` substring, that the closing-order classifier therefore lives in
  `adapters/polymarket_us/leg_prices.py` (outside `exec/`, where `BUY_SHORT` already lives), and that
  **X3's token set is consequently unchanged**. Shape follows
  `docs/evidence/RULING_x3_no_outcome_token_2026-09-14.md`.
- RED: the gate returns False for every other family, True for v4 only once the manifest declares
  `exit_rule`; `ExitAuthorization` refuses qty above net long, a unit-boundary price, a missing
  `position_id`, and an R-THREAT authorisation whose net proceeds `<= expected_settlement_value`.
- Layering: `exit_authorization` sits in `strategy/`, importing downward into `persistence/` only.

**INC-E2 — adapter mapping for an authorised exit, echo check, fee, fill-side correctness.**
- Files: `exec/submit_chain.py`, `exec/client.py`, `adapters/polymarket_us/leg_prices.py`.
  **No new file under `exec/`** (E0 classifies by path; the N2/E0 module table stays unchanged).
- `unmappable_order_reason` (`:277-318`) is **byte-unchanged** — a bare SELL remains a naked short. Add
  `unmappable_exit_order_reason(order, instrument, authorization)` and `build_exit_order_body(...)`
  **inside `submit_chain.py`**, reachable only with an `ExitAuthorization`. They re-apply every BUY-path
  rule (BinaryOption, slug, LIMIT, IOC, qty == 1, price strictly inside (0,1), no post-only, no
  reduce-only, no display_qty, no expire_time, no trigger) and add: the order's side must be the
  closing side for the authorised position; the authorisation's `position_id`/`client_order_id` must
  match the order; `family_declares_exit_rule(manifest)` must be True.
- **Response-side leg check (review HIGH 6).** `leg_prices.assert_echo_matches_leg` (`:99-118`) today
  accepts exactly two BUY echoes (`VENUE_SIDE_FOR_LEG`/`VENUE_INTENT_FOR_LEG`). Add a sibling **exit**
  table and `assert_exit_echo_matches_leg(leg, side, intent)` in the SAME module (outside `exec/`):
  YES+close → `(ORDER_SIDE_SELL, ORDER_INTENT_SELL_LONG)`, NO+close →
  `(ORDER_SIDE_SELL, ORDER_INTENT_SELL_SHORT)` — the pair Appendix A documents, refused in BOTH
  directions like the BUY table. Wire it into the exit-fill acceptance branch in `exec/client.py`. The
  literals are **pinned before enable** against the §4 step-1 capture; if the capture disagrees, the
  capture wins and the table is corrected, never widened to accept both.
- **Exit fee (review item 4).** Verify the coefficient `0.06 · p · (1 − p)` evaluated at the **exit**
  price against the entry-fee derivation, in this increment, with a test that one coefficient source
  feeds both `exit_fee` (`monitor_evidence.py:309-311`) and the entry path. A fee derived at the wrong
  price makes `recoverable_value` — and therefore R-THREAT's threshold — wrong.
- **Fill accounting.** `client.py:1924,3232` take the order's real side instead of `LONG_ONLY_SIDE`;
  `:2007,3282` pass the real `OrderSide` instead of the hardcoded `OrderSide.BUY`. `_RECORD_SIGNS`
  (`:434-437`) already handles `SELL`.
- **Budget (review MEDIUM 9).** The daily-budget debit is
  `adapters/polymarket_us/operator_controls.py:347`
  `authorize_order_cost(price_usd, quantity, now_ns)`, called from `exec/client.py:3119`.
  **Decision: the daily budget is GROSS entry spend, not net.** An exit never calls it and its proceeds
  never replenish entry headroom — a cap the day's sales could re-open is not a cap.
- RED: an authorised exit maps and emits a SELL-action body; an exit naming a different position
  refuses; a gate-refused family refuses; an exit fill is booked `SELL` in both the native event and the
  durable record and REDUCES Nautilus net position; the same body without an authorisation raises; an
  echo outside the exit table refuses; **an exit fill never decrements the daily counter AND never
  increases remaining entry headroom**.

**INC-E3 — strategy decision → order, halt, rate limit, persistence.**
- Files: `position_monitor.py` (emit an authorisation request, not only a summary),
  `continuous_strategy.py` (construct and submit), `trial_day_latch.py` (halt bucket), `offer_tape.py`
  / `monitor_store.py` (persist).
- Order: `order_factory.limit(instrument_id, order_side=Order.closing_side(position.side), quantity=1,
  price=<walk-proved executable bid>, time_in_force=IOC, reduce_only=False)` then
  `submit_order(order, position_id=position.id)` — the native shape from §0. Price = the best level
  `walk_exit_vwap` (`monitor_evidence.py:162-201`) proves fillable for qty 1; never a mark, never an
  interpolation, never a public-info price (L-7/L-9).
- **AMBIGUOUS/rejected-exit kill (review CRITICAL 5).** Add `record_ambiguous_exit` to
  `strategy/current_rung_hold/trial_day_latch.py` alongside `record_duplicate_fill` (`:761`), writing
  the **same durable family-halt state** that `is_family_halted` (`:816`) reads and that only
  `clear_family_halt` (`:845`) via `clear_family_halt_cli.py` can clear. It is therefore already
  enforced at three existing chokepoints with no new mechanism: `composition.py:190-221`
  `family_halt_submit_veto` (synchronous, pre-spend, zero money moved) and
  `continuous_strategy.py:561,975`.
- **Rate limit (review MEDIUM 8).** Exactly **one 1-contract exit order per `ExitAuthorization`**; a
  second authorisation for the same `position_id` inside the rule's confirmation span (>=10 min
  R-THREAT, >=5 min R-DEAD) refuses with its own reason code; plus a per-station-day cap.
- Persistence: one offer-tape row per exit decision (fired/refused, with reason) and the monitor summary
  row, written before any submit completes (`offer_tape.py:284-304` is already best-effort JSONL plus a
  bounded deque).
- RED: per leg (L-44) a YES and a NO exit; every §5 safeguard refuses with a distinct reason; a
  shadow-configured monitor (`position_monitor=None`, or a gate-refused family) submits **nothing**; the
  decision row is written even when the order is refused; **an AMBIGUOUS exit halts the family and the
  halt survives a process restart** (node dies and respawns mid-session, repeatedly — which
  `midday-relaunch` makes routine); a second exit for the same position inside the span refuses.

**INC-E4 — positive control, then enable** (§4). **INC-E5 — measurement:** the three §1 descriptive
series in `position_monitor_nightly_report.py`, keyed per rule.

**Pinned tests — additive only, named individually (L-12).**
1. `tests/unit/test_no_side_submit_chain_2026_09_14.py:181-191` — **unchanged**, plus a sibling test
   that the authorised-exit seam maps the same instrument, pinning the two paths apart.
2. `tests/unit/test_cage_rule_constants_are_pinned.py:497-570`
   `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` — **additive**:
   `submit_chain.unmappable_exit_order_reason`, `submit_chain.build_exit_order_body`, plus
   `leg_prices.assert_exit_echo_matches_leg` / a ledger-credit callee **only if** called from inside the
   exec order coroutine — each with its own justifying comment, recorded in `widened`.
3. `tests/unit/test_execution_egress_firewall_guard.py:739-765` (E0/N2 module table) — **unchanged**:
   no new file under `exec/`.
4. `tests/unit/test_execution_egress_firewall_guard.py:251-258` (X3 `BANNED_EXEC_DIRECTION_TOKENS`) —
   **unchanged**, per the INC-E1 ruling (C5).
5. `tests/unit/test_runtime_live_order_guard.py:321,346` (RED-4/RED-5 `xfail(strict=True)`) —
   **untouched**; they pin a Nautilus defect.
6. New RED tests for the halt and rate limit (INC-E3) and the echo table and budget (INC-E2).

---
## §4 Verification protocol — measurement before mapping, mapping before money

**Step 0 — offline exit-window replay study (retires "is there ever a counterparty?").**
`scripts/analysis/current_rung_hold_exit_window_study.py`, run stamp `20260916_initial`, over the
existing Depth10 tape plus IEM observations. Per position it reports the THREATENED and DEAD instants,
the executable 1-lot exit price at each instant, the instant the exit side emptied, and counterfactual
pnl for R-DEAD, R-THREAT and an R-BEST oracle against hold. This step exists because the 09-15
diagnosis ruled **"no exits (no counterparty; L-7/L-9)"** — the plan reconciles with that measurement
rather than assuming a counterparty. Both outcomes are acceptable results: a fillable window (arm per
below), or none (neither rule arms and the seam ships unarmed).
- **Pre-registered arming criteria, honest about N.** The usable losing-position corpus is N ≈ 4–6 (one
  clean day, four positions), so these are **feasibility gates**, not confirmatory tests, stated before
  the numbers are read:
  - **R-THREAT arms only if** it fires strictly before the exit side empties in **>= 3 of N** positions
    AND Σ counterfactual pnl(R-THREAT) >= Σ pnl(hold) on the same tape AND at least one firing had
    `recoverable_value > E[settlement | state]` (§1's real condition, not a proxy).
  - **R-DEAD arms only if** it fires before the exit side empties in **>= 1 of N** positions; otherwise
    it is registered but recorded as expected-inert (what §0 predicts).
  - **Either rule fails** if Σ counterfactual pnl < Σ pnl(hold), or if the R-BEST oracle is <= hold —
    the latter means no exit policy could have helped on this tape and no rule arms.
  - A gate passed on N ≈ 4–6 licenses **arming for measurement**, never a claim of edge.

**Step 0b — value-capturing positions read (retires the NO holding's sign and denomination).**
`scripts/venue/polymarket_us_positions_value_capture.py`, run against the four still-open 09-15
positions **before 12:00Z settlement**. Question retired: how a held NO position is signed and
denominated on `/v1/portfolio/positions` (`netPosition`, `qtyBought`/`qtySold`, `avgPx`,
`costPerShare`, `positionId`) — every positions response on this host has been `{"positions":{}}`, so
these VALUES have never been observed (Appendix A). Without it, "quantity <= attributed net long" is
arithmetic over an unverified sign for the NO leg. Commit as
`docs/evidence/venue/polymarket_us/POSITIONS_VALUE_<UTC>.json`, secrets stripped.

**Step 1 — preview capture (retires the request/echo shape).** Capture the preview response for a
closing order against (a) a held YES and (b) a held NO, at a price we would actually send; commit as
`docs/evidence/venue/polymarket_us/EXIT_PREVIEW_<UTC>.json`. Retirement evidence: per leg, the
`action`/`outcomeSide` pair, the `price.value` convention, the echoed `side`/`intent` (which pins
INC-E2's exit table), and that the venue reads the order as **reducing** rather than opening the
opposite side. If the preview cannot distinguish reducing from opening, this step is NOT retired and
step 3 stays blocked.

**Step 2 — declare the mapping** from the capture in a ruling doc; encode it in `build_exit_order_body`
plus the `leg_prices` exit table, with a test pinning the captured bytes.

**Step 3 — positive control: exactly one contract.** Arm the gate for a single station-day, exit one
1-contract position under the armed rule, and require: a create-order response classified
non-AMBIGUOUS, a durable record with `SELL`, Nautilus net position reduced by 1, nothing credited to
entry headroom (INC-E2), and a venue-side positions/activities GET independently confirming the
reduction. A GET timeout or 5xx during the control routes through the **existing** GET-based AMBIGUOUS
resolver (`exec/client.py` `_resolve_ambiguous_intents`), never a re-send. Any AMBIGUOUS outcome →
§5.4's kill.

**Step 4 — enable.** Only after step 3, and only for `pm_us_crh_exit_v4`.

---
## §5 Safeguards — each on a named seam

1. **Binding invariant: the live net-long guard.** `backtest_order_guard._refuse_naked_short`
   (`:221-291`), installed by `install_live_order_guard` (`:407`) at `trade_cli.py:399`, reads the
   shared `Portfolio`/`Cache` per instrument and therefore binds **account-wide across all four station
   strategies** (VERIFIED). Its `_working_sell_quantity` (`:322-345`) counts every not-yet-closed SELL,
   in-flight included, so two arms or two legs cannot double-sell. `ExitAuthorization` is a
   **convenience value object** that fails fast at the decision site — strategy-constructed, therefore
   NOT unforgeable, and never a substitute for this guard.
2. **Single account-wide exit intent latch.** The existing `SubmitIntentLatch`
   (`runtime/submit_intent.py:37,313`, L-36): one open intent account-wide, `arm` → POST → `retire` on
   one thread. The cross-arm race (an MDW exit while an SFO entry is in flight) is **VERIFIED closed**
   by this single latch — an exit competes for the same singleton instead of opening a parallel one.
3. **Per-position attribution.** An exit is authorised only against a Nautilus `Position` whose opening
   fill carries a Breezy `client_order_id` we minted (`submit_order(..., position_id=...)` ties them;
   `continuous_strategy.py:874-875` delivers the `Position`). An unattributable position is never
   exited — it is alerted.
4. **Kill on AMBIGUOUS or rejected exit — the durable family halt.** `record_ambiguous_exit` writes the
   same state `TrialDayLatch.is_family_halted` (`:816`) reads, cleared only by `clear_family_halt`
   (`:845`) via `clear_family_halt_cli.py`; enforced at `composition.py:190-221`
   `family_halt_submit_veto` (synchronous, pre-spend, zero money moved) and
   `continuous_strategy.py:561,975`. Durable, so it **survives the process death** `midday-relaunch`
   makes routine (RED test, INC-E3).
5. **Response-side leg check.** `leg_prices.assert_exit_echo_matches_leg` (INC-E2) refuses any echo that
   is not the exact documented pair for the leg, in both directions — the venue represents a NO buy as
   `side SELL`/`intent BUY_SHORT`, so an echo-blind exit path could attribute a report to the wrong leg.
6. **No exit outside the window or on a stale book.** The existing predicate
   (`monitor_decision.py:338-345`): `mark_source == "depth_walk"`, `depth_sufficient`,
   `book_staleness_ns <= 180 s`. Outside it the verdict is `MISSING_STOP` — an alert, never an order. No
   exit before the decision window opens or after the day's stop.
7. **Rate limit.** One order per `ExitAuthorization`; a second authorisation for the same position inside
   the rule's confirmation span refuses; per-station-day cap on exit orders.
8. **Budget.** Daily budget is GROSS entry spend: an exit never calls
   `operator_controls.authorize_order_cost` (`:347`, called at `exec/client.py:3119`) and never
   replenishes entry headroom.
9. **`allow_short=False` stays permanent** (`weather_common/risk.py:224` `RiskLimits.allow_short`,
   enforced at `:611-617`); the exit path never opens a position and never crosses zero.

---
## §6 What remains blocked, and why

- **Arming is blocked on §4 step 0.** If the exit-window study shows no fillable window, neither rule
  arms and the gate stays empty — the seam ships unarmed. That is the honest outcome the 09-15
  "no counterparty" measurement makes likely.
- **The NO-leg net-long arithmetic is blocked on step 0b** — those payload VALUES were never observed here.
- **Constants stay UNCALIBRATED.** `_P_HOLD_DROP_MARGIN`, the confirmation counts/spans and
  `_LOCKED_HOUR_LST` are PROVISIONAL on a 1-clean-day corpus (`monitor_decision.py:148-158`); none may
  be tuned off live firings without a registered amendment.
- **Multi-contract exits stay out of scope** — `submit_chain.py:295-296` unchanged here; a separate
  increment with its own mapping evidence. **`/v1/order/close-position` stays unused** — flatten-all, no
  price control, response never captured (Appendix A); it cannot express an IOC LIMIT at a proved bid.
- **RED-4/RED-5 stay `xfail(strict=True)`** — a Nautilus property defect, immutable, out of scope.
  **Kalshi is untouched** (`kalshi_crh_v1` not registered for exit); Polymarket.us first.

## §7 Open questions

**Operator BUDGET questions: none.** Exit proceeds are a credit and the daily budget is gross entry
spend (§5.8), so neither cap needs a new value, no new operator-reserved control is introduced, and the
§4 step-3 positive-control enablement is the one operator-only hard gate — which already exists.

## Appendix A — venue closing-order evidence (read-only sweep, 2026-09-16; coordinator hand-down)

| Fact | Status | Citation |
|---|---|---|
| `ORDER_INTENT_SELL_LONG` = sell YES contracts (close long YES); `ORDER_INTENT_SELL_SHORT` = sell NO contracts (close long NO) | DOCUMENTED | docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_orders_overview_2026-08-25.md:95-97; create-order_2026-08-25.md:179-185 |
| `outcomeSide`+`action` alias: YES+SELL→SELL_LONG, NO+SELL→SELL_SHORT (wins over `intent` if both present) | DOCUMENTED | overview_2026-08-25.md:114-121,137 |
| `price.value` is always the YES price; a NO close held at X is sent as 1.00−X | DOCUMENTED | overview_2026-08-25.md:141,158; src/breezy/adapters/polymarket_us/leg_prices.py:56-75 |
| Cash proceeds of a SELL_LONG fill = p | INFERRED only (never observed) | concepts_orders_2026-08-25.md:13-22 |
| `POST /v1/order/close-position` {marketSlug, manualOrderIndicator, synchronousExecution}: flatten-all, no price control, response never captured | DOCUMENTED shape / UNKNOWN behaviour | sdk_snapshot/polymarket_us_0.1.2/types/orders.py:186-191 |
| No `reduceOnly`/`positionId` request field exists | UNKNOWN / absent | repo-wide grep |
| Live body Breezy sends: 10 keys, no `intent`; only `ORDER_ACTION_BUY` ever constructed; X3 bans `_SHORT`, `BUY_SHORT`, `SELL_` tokens inside `exec/` | code-enforced | submit_chain.py:88-101,326-347; test_execution_egress_firewall_guard.py:252-257 |
| NO-buy echo: request NO+BUY @0.97 → response intent BUY_SHORT, side SELL, outcomeSide NO | live-observed 09-14 | docs/evidence/venue/polymarket_us/NO_SIDE_PREVIEW_20260914T170750Z.json; leg_prices.py:99-118 |
| Held-position payload: field names known (netPosition, qtyBought, qtySold, qtyAvailable, cost, avgPx, costPerShare, positionId…); VALUES never captured — every positions response on this host is `{"positions":{}}` | UNKNOWN sign/denomination for a NO holding | sdk_snapshot types/portfolio.py:21-34; exec/reports.py:337-380; exec/no_side_keys.py:45-49 |
| Preview: `POST /v1/order/preview` {"request": CreateOrderParams} → {"order": {state PENDING_NEW, id ""}}; product code never calls it; scripts/analysis/capture_no_side_preview.py (dry-run default, `--execute` to send) | DOCUMENTED + observed; "places no order" INFERRED from empty id | sdk resources/orders.py:68-74 |
| Live exec client has no close-position coroutine; `_close_position` sits in the widened (rejected) cage pin | code-enforced | tests/unit/test_cage_rule_constants_are_pinned.py:810-848 |

Top unknowns the §4 protocol must retire, in order: (1) how a held NO position is signed and priced on `/v1/portfolio/positions` (the positions endpoint has NEVER returned a non-empty body here — capture it while the four 09-15 positions are still open, before 12:00Z settlement); (2) whether `outcomeSide`+`action=ORDER_ACTION_SELL` is accepted on the intent-less 10-key body and what it echoes (preview both YES+SELL and NO+SELL); (3) proceeds/fee sign on a closing fill and whether a priced IOC SELL or `/close-position` is the venue's expected close.

### Appendix A.1 — §4 step 0b RETIRED (2026-09-16 ~03:40Z, value capture of the four open positions)
`scripts/venue/polymarket_us_positions_value_capture.py` → `PRIVATE_v1_portfolio_positions_open_positions_20260916.positions.json` (gitignored PRIVATE_ artefact; HTTP 200, 4 positions, redacted keys `eventId`, `id`).

| slug | outcome | netPosition | qtyAvailable | qtyBought / qtySold | avgPx | cost | cashValue | realized | expired |
|---|---|---|---|---|---|---|---|---|---|
| tc-temp-mdwhigh-2026-09-15-gte80lt81f | Yes | 1 | 1 | 1 / 0 | 0.1200 | 0.1200 | 0.0100 | 0 | False |
| tc-temp-mdwhigh-2026-09-15-gte82lt83f | Yes | 1 | 1 | 1 / 0 | 0.2500 | 0.2500 | 0.0100 | 0 | False |
| tc-temp-miahigh-2026-09-15-gte92lt93f | No | **−1** | **−1** | **0 / 1** | 0.0900 | 0.0900 | 0.0100 | 0 | False |
| tc-temp-sfohigh-2026-09-15-gte71lt72f | Yes | 1 | 1 | 1 / 0 | 0.4500 | 0.4500 | 0.0100 | 0 | False |

Findings that bind INC-E2/E3: (1) the venue nets a held NO as a **short of YES** (`netPosition −1`, `qtySold 1`), while Breezy/Nautilus holds it as a LONG on the `^no` leg instrument — the net-long guard reasons per Breezy instrument and stays correct, but any reconciliation of venue `netPosition` against Breezy positions must apply the leg sign (`marketMetadata.outcome`) before comparing; (2) `avgPx`/`cost` are **fee-inclusive** and denominated in the HELD leg (YES 0.12 = 0.11 + 0.01 fee; NO 0.09); (3) `cashValue` is the venue's mark (0.01 on all four = the settled-as-lost expectation); (4) the close of a NO must therefore be the order that brings `netPosition −1 → 0` — expected `SELL_SHORT` per the docs; the §4 step 1 preview capture decides.
