# PLAN Rev 5 (FINAL): Forecast-Conditioned Ladder Edge Family (`pm_us_crh_fc_v1`)

Scope: DESIGN ONLY, read-only against `/home/jon/breezy`
(branch `feat/data-capture-and-risk`). Rewrites Rev 4 per
`REV5_DISPOSITIONS.md` (coordinator round-4 merge: architect NOT-CONVERGED
0.86 on §7 locals, Grok CONVERGED-WITH-EDITS 0.86, prediction-market
CONVERGED-WITH-EDITS 0.83, mle CONVERGED-WITH-EDITS 0.72; all remaining
items local, every one required). §§1-13 of Rev 4 stand except where an
item below names them. This is the intended FINAL revision.

CODEGRAPH_USED: 4 calls this session, all against live source, targeted at
the citations round-4 review flagged unreconciled: (1) `order_enablement.
py` `OrderSubmissionPermit.issue` (`:177-242`) + `composition.py`
`phase1_family_permits` (`:247-281`) + `settings.py` `load_trade_settings`
(`:790-859`) + the mutual-exclusion contract test, full source; (2)
`ladder_ev/density_table.py` full module + `current_rung_hold_v2.py`
`StratumV2.cell_dead`/`build_stratum_v2` + `trial_day_latch.py`
`_attempt_key`/`station_day_admission` + `depth_adapter.py` full module +
`decision.py` `_is_legal_cell` + `backtest_harness.py` `run_backtest`; (3)
`current_rung_hold_v2.py` `CombinedDraw`/`_cell_probability`/
`combine_station_day`/`score_combined` + `continuous_strategy.py`
`_submission_armed` (base, `:658-672`) + `continuous_backtest_only.py`
`ContinuousRungHoldBacktestStrategy._submission_armed` (the ACTUAL
override, a separate module -- Rev 4's `continuous_strategy.py:668-671`
citation was the base docstring naming this override, not its body,
corrected below); (4) `leg_prices.py` full module + `current_rung_hold/
decision.py` `DecisionInputs`, confirming `NO_ask = 1 - bid` is computed
inside `evaluate_decision`, never by the caller. Context-only:
`reviews/grok4.md`, `REV4_DISPOSITIONS.md`, `REV5_DISPOSITIONS.md`,
`seams/result_C.md`, `FORECAST_EDGE_FAMILY_Rev4_2026-09-18.md`.

**HARD INVARIANTS (restated, obeyed throughout, unchanged since Rev 4):**
Nautilus Trader is immutable -- extend only through native extension
points. `allow_short` stays `False` everywhere; a NO take is `OrderSide.
BUY` on the `^no` leg instrument, **never** `SELL_SHORT`. Never weaken,
delete, or bypass a safety/settlement/contract test -- the mutual-exclusion
contract test (`tests/contract/test_rung_hold_families_mutual_exclusion_
contract.py`, VERIFIED this session, full source read) is AMENDED to a
three-family invariant and must still refuse any two families sending
simultaneously; it is a stricter test, not a weaker one (R5-2). Exactly two
operator caps (max daily budget, max per position) are named, never
valued, never a third knob. Never touch live-trading enablement or the
NO-SEND execution-egress firewall. New family, own `family_id`/`trial_id_
prefix`/`d0_climate_day`, n resets to 0, before first fill. L-9 and L-21
both bind, including inside §13's loop. Stage 0 precedes any ingest/
strategy code. The plan must reach the goal state: §7.13's integration
test is the concrete, buildable proof; §13's promotion rule is the
concrete, buildable proof the loop only ever produces a disciplined new
revision.

---

## 0. Evidence classes (unchanged from Rev 4) and Rev 5 disposition

| Class | Meaning |
|---|---|
| VERIFIED file:line (this session) | Read via `codegraph_explore` this pass |
| VERIFIED (Rev 3/4, cross-checked) | Read in a prior session, corroborated by an independent reviewer, unchanged this session |
| INFERRED | Reasoned from verified facts, not itself measured; flagged inline; every §13 constant carries "set by the 0b power table before PREREG v6 registration" |
| UNVERIFIED | Named in a source doc, not re-checked this session; re-probe before the dependent stage |

### 0.1 Rev 5 disposition table

| Item | § | Item | § |
|---|---|---|---|
| R5-1 NO-leg pricing = inverted bid-ladder walk, `depth_adapter.py` EXTEND | §7.6, §7.10 | R5-2 permit displacement (coordinator decision), 3-family exclusion | §0.2, §7.8, §8, §9, §12, §13.3 |
| R5-3 window gate: one statement, family reads `cfg` inside `exclusion_filter` | §7.2, §7.7 | R5-4 same-rung YES+NO arm-time refusal | §7.3, §7.8 |
| R5-5 density key shape: one shape, closed outcome alphabet | §2, §7.1, §7.2, §7.5, §13.1a | R5-6 scorer gates by side (split Wilson gates) | §7.6, §7.11, §9 |
| R5-7 promotion estimator + paired comparison | §13.3 | R5-8 rollback/promotion vs KILL clocks; `boundary_inputs_sha256` blocking | §13.3, §9 |
| R5-9 §7.13 fixture: correct backtest override citation, name `allow_open_positions`/`allow_idle_strategies` | §7.13 | R5-10(a-i) small edits | §7.8, §7.9, §2, §7.1, §7.5, §10, §1.3, throughout |
| R5-11 carried SATISFIED (Rev 4 round): A1,A3(d),A4,A6,C1-C4, R4-B lexical, §13 framing/leakage/walk-forward/ledger/what-cannot-be-learned/INFERRED constants, §9/§11/§12 integration | throughout | Rev 3 carried: A1(NO reuse)/A2/A3/A4/A5/A6/A7/A8, B1-B8 (Route B), C1-C4 | §1,§2,§4,§5,§7 |
| Rev 2 carried (D, unchanged since Rev 2) | climate-day fixtures, NBS/GFS baseline, single 0a gate, coarsening ladder, MAE-by-lead, tape completeness, `_DATA_TYPE_FACTORIES` regression, `ForecastState.value_at` mirror, frozen table, namespace, lint-imports, security items, L-16 test, secondary endpoint + 15-day clock + Var(S) | | |

### 0.2 RULING artefact (filed under `docs/evidence/` before Stage 0; ≤25 lines per brief)

> ## RULING: Forecast-conditioned family authorized, self-learning required, standing KILL verdicts superseded (2026-09-18)
> **Operator (verbatim):** "Accurate forecasting is exactly what I want the
> trading bot strategy to be using. Using all available data, identify the
> edge and execute trades where edge is identified to increase the
> portfolio level ROI."
> **Second operator requirement (verbatim), sanctioned by §13:** "the
> trading bot must have self-learning functionality. As it trades, as it
> ingests more data, it learns, and improves the forecasting trading."
> **Supersedes:** `PROGRESS.md:30` ("forecast family KILLED... Do not
> design a new family"); `grok_forecast_family_verdict_2026-09-02.md:11,
> 38,40`.
> **Does NOT supersede:** L-9, L-21, Stage-0-before-build, the two-
> operator-caps rule, PREREG discipline, any safety invariant, or the
> champion/challenger discipline §13 imposes on the second requirement.
> **New family, own D0.** `pm_us_crh_cont`/`archive_table.py` stay byte-
> unmodified -- a structural guarantee (Route B, §7), not a behaviour-
> preserving promise resting on a golden-replay test.
> **Permit-displacement consequence (R5-2, coordinator decision).** Arming
> `pm_us_crh_fc_v1` (Stage 4) DISPLACES `pm_us_crh_cont` as the single
> sending family; `pm_us_crh_cont` continues unarmed (shadow, offer-tape
> only) -- see §7.8/§9 for the honest statement of what that does to its
> own clocks. "Armed together" is deleted everywhere.
> **Licenses Stage 0 measurement only.** Stage 1+ requires Stage 0b PASS;
> live enablement additionally requires the §4.5 pre-Stage-4 gates; §13
> additionally requires the champion to be PREREG-registered before any
> challenger may ever be promoted.

---

### 0.3 Coordinator hand edits after the final review round (BINDING — override the body wherever they conflict)

Final round (architect CONVERGED-WITH-EDITS 0.79; Grok CONVERGED-WITH-EDITS 0.88; both verified against live source). The implementer applies these as written; where §2/§7/§9/§13 text conflicts, THIS section wins.

| # | Edit | Evidence |
|---|---|---|
| E1 | **One window gate, inside `exclusion_filter`.** The comparison at `ladder_ev/decision.py:104` reads `cfg.window_start_hour_lst`/`cfg.window_end_hour_lst` (defaults 12/17; existing tests unchanged); `exclusion_filter` is EXTEND for that line; the family keeps NO second window gate. Delete §7.7's "not edited / own universe gate" sentence. | `decision.py:17-18,104` |
| E2 | **NO-leg EV formula and ladder order.** A NO row is a LONG BUY of the NO leg: `edge_after_costs(model_p=1 − p_upper, ask_p=NO_ask, bid_p=None, intent_long_yes=True, cost=total_prob)` — `intent_long_yes` names the leg being bought; NEVER `intent_long_yes=(side=="yes")` (False is a short-YES edge and returns None without `bid_p`, `risk.py:732-751`). `bid_levels_from_book` inverts YES bids to NO asks (`1 − bid`, size = bid size) and THEN sorts ascending (best NO ask first); never the raw-bid ascending sort. Consumer: `unified_cost` takes a `DepthAwareTradeCost` (`scoring.py:40-42`) via `weather_common.costs.depth_aware_trade_cost_prob` → `walk_ask_ladder` (`ladder.py:135-182`, best-first). Drop "exactly CRH's convention": CRH's NO is top-of-book only (`decision.py:422-431`); the ladder walk is a ladder_ev extension. The `1 − bid` arithmetic lives in `strategy/ladder_ev/`, outside the X3 AST ban scoped to `adapters/polymarket_us/exec/` (`leg_prices.py:3-7`); `wire_price_for_leg` is submit-only and is never called for EV. | `decision.py:422-431`; `leg_prices.py:56-75`; `depth_adapter.py:18-41`; `risk.py:732-751`; `scoring.py:40-53`; `ladder.py:135-182` |
| E3 | **Third-family settings surface (all sites).** `rung_hold_family = current or continuous or forecast` at `settings.py:814`, and the consumers at `:815` (live observations), `:834-847` (`BREEZY_ORDERS_ENABLED` → `SettingsError` at `:835` today), `:848` (catalog root); `SettingsLike` (`order_enablement.py:~125-146`, `isinstance` gate `:192`) gains the forecast flag; `issue()` gate `:224-231` widened; `load_trade_settings` exclusivity `:823-833` becomes "refuse any two of three". `app/trade.py`: do not early-return when both legacy flags are off (`:175-182`); `phase1_family_permits` returns a 3-tuple and `:206-211` unpacks three; a forecast composition branch beside `:215/:225`; `test_current_rung_hold_composition.py:808` updated. Contract test `tests/contract/test_rung_hold_families_mutual_exclusion_contract.py` AMENDED to three pairs (stricter, never weakened), security-reviewer sign-off. | `settings.py:814-848`; `order_enablement.py:125-146,192,224-231`; `composition.py:247-281`; `trade.py:175-225` |
| E4 | **Displacement semantics (replaces every "CRH keeps scanning / clock ticks" sentence).** Exclusivity is enforced on the PERMIT and, today, also on COMPOSITION (`trade.py:225` only builds CRH when its flag is on). Decision: when `pm_us_crh_fc_v1` is the sending family, `pm_us_crh_cont` is NOT composed; its trial is CLOSED at displacement with terminal state SUPERSEDED-BY-RULING (S_k, n, clocks frozen and written by the scorer; `docs/evidence/RULING_forecast_edge_family_2026-09-18.md`). No displacement-shadow path is built (YAGNI); `phase0_shadow` is not extended. §9's 15-day clock row for CRH is deleted. | PREREG v3 `:27` (shadow never feeds a verdict); memory: covered = recorder capture |
| E5 | **Pre-Stage-4 Wilson gates by side.** `build_stratum_v2` raises on ANY `side != "yes"` (`current_rung_hold_v2.py:418-423`), so a NO-only subset also raises. EXTEND (or a sibling helper) for a HOMOGENEOUS `side="no"` subset (held/entry_ask already per-leg); the raise stays for mixed rows; never relabel NO rows as "yes". Stage 4 refused if either side's cell is dead. | `current_rung_hold_v2.py:385-437` |
| E6 | **Same-rung arm-time refusal = REUSE BY IMPORT.** `refuse_if_sibling_leg_traded` → `Refusal(SIBLING_LEG_TRADED_REASON)` (`trial_day_latch.py:166-172, ~1400-1410`) already refuses a same-rung opposite-side second take at arm time; `Refusal.__post_init__` (`:216-221`) validates against the closed `LATCH_GATE_REFUSAL_REASONS` (`:202-204`). Delete the proposed new `same_rung_opposite_side` reason; the counted reason is `sibling_leg_traded`. §7.3's "only fires post-fill" sentence is withdrawn. | `trial_day_latch.py:166-221` |
| E7 | **§7.13 fixture.** File name `tests/integration/test_forecast_ladder_family_backtest.py` (the existing `test_forecast_edge_backtest.py` exercises the unrelated `ForecastHighEdgeBuyer` and its fixture spine — `run_backtest`, `as_backtest_data`, `SyntheticBinaryTape`, `make_climate_day`, `settlement_prices` — is REUSED, the file is not). Pass `allow_open_positions=True` only if the hold-to-settlement double take actually leaves a position open after `settlement_prices`. Confirm before Stage 3.9 that `SyntheticBinaryTape` can emit a ONE-SIDED book for the `no_bid_side` assertion; if not, extend the fixture. The family's backtest subclass must not import `continuous_backtest_only` (one-importer AST pin `:41-45`). | `tests/integration/test_forecast_edge_backtest.py`; `backtest_harness.py:958` |
| E8 | **Citation nits.** `density_table.py` `__all__` at `:32`; §9 "fallback to last-good" must say "mints a new revision" (as §13.3 does); `family_manifest.py:175-184` `UnpinnedBoundaryArtefactError` is VERIFIED (class `:101`), drop the RE-VERIFY flag; the permit class/mint is `order_enablement.py:156/:177-242`, never `safety.py`. | — |

Reach-the-goal after E1–E8 (both final reviewers): the family can take the thesis trades (NO on the current rung's `^no` leg, YES on the forecast-implied rung) through permit/latch/submit, can be judged on station-day units with side-homogeneous Wilson gates and `score_combined`, and leaves `pm_us_crh_cont`'s files byte-unmodified. No hard invariant is touched.

---

## 1. Goal, non-goals, the LADDER estimand (unchanged from Rev 4 except 1.3)

**Goal.** A forecast-conditioned probability for every legal rung on a
station's ladder, both sides, gated by a fee-inclusive break-even test,
screened per §4 before any code beyond Stage 0. Under Route B (§7) this is
met by composing a second, independent decision core (`ladder_ev`,
extended) rather than hooking the live family's decision core. A build-
time, pre-registered learning loop (§13) improves the forecast-
conditioning over time, strictly through new, disciplined revisions --
never a live inline refit.

**Non-goals.** No edit to `pm_us_crh_cont`'s `continuous_strategy.py`,
`tick_eval.py`, `decision.py` (the CRH one), or `archive_table.py`. No
backtest-ROI claim. No sizing change beyond `order_quantity=1`. No NO-SEND
touch. No operator-value assignment, including inside §13. No online/
in-node model mutation (§13.2).

**1.1 Why current-rung-only cannot trade the thesis, without editing CRH.**
The 09-15 miss (archive 0.36/0.59/0.30 vs market 0.11/0.24/0.09,
`LOSING_DAY_…md:15`) is harvested by NO on the current rung and/or YES on
the forecast-implied higher rung. `ladder_ev/decision.py`'s
`exclusion_filter` (`decision.py:60-111`) already evaluates one candidate
rung at a time, independent of which rung contains `running_max`; X1 hard-
refuses a rung entirely below the running max (`decision.py:64-69`,
`running_max.lower_f > inputs.rung_upper`). The family's per-rung scan
(§7.2) calls this once per listed rung, per side -- but round-3 review
proved the reuse-as-is `exclusion_filter` X8 still structurally refuses the
YES-above candidate; §7.4 is the fix (SATISFIED per round-4 review).

**1.2 NO submit path (traced Rev 3, unchanged since; §7.10 below refines
how EV is computed, never how the order is submitted).**
`NO_SIDE_SHADOW_ONLY = False` (`continuous_strategy.py:161`).
`_evaluate_no_side_shadow` builds a NO `Decision` via `sibling_instrument_
id` (`symbology.py:318-325`: `no_leg_instrument_id` at `:277-286` builds a
plain composite id, not a Nautilus short position), calls `station_day_
admission` and appends an offer-tape row, then `self._maybe_submit(no_iid,
no_decision)`; `_maybe_submit` calls `order_factory.limit(OrderSide.BUY,
...)` on the NO-leg instrument id. **Consequence, if confirmed:** a live NO
order is `OrderSide.BUY` on `sibling_instrument_id(yes_id)` -- this family
reuses the pattern for ORDER SUBMISSION, never invents a new order path,
never constructs `SELL`/`SELL_SHORT`. **RE-VERIFY the exact `_maybe_submit`
line range before Stage 3 build** (carried UNVERIFIED-this-session per
Rev 3/4; three prior reviewers corroborated the same call shape).

**1.3 `R(t)` is a physical refuse, not a table key (R5-5 wording fix).** A
candidate rung's `r_relation` to `running_max` is one of `below` (whole
interval beneath -- physically dead, hard refuse before any density-table
lookup, COUNTER reason `rung_physically_dead`), `contains` (spans
`running_max`, today's "current rung"), or `above` (entirely above --
forecast-implied). `r_relation` is DERIVED at scan time from the settled/
candidate rung's position relative to `running_max`; it is never a table
KEY component (§7.5 corrects this precisely) and never enters the fee/
break-even test directly -- it selects which side-aware legality rule
applies (§7.4) and which outcome symbol a settled record maps to (§7.5).

**1.4 Exit posture.** Hold-to-settlement default; intraday exit stays
UNARMED for this family unless a later ruling arms it; PREREG states this.

**1.5 Portfolio ROI.** Fixed `order_quantity=1`, `trial_count × mean_
realized_edge` (mean of `held_i − BE_i` over filled Takes, both sides,
every rung, scored per §7.11's `combine_station_day`/`score_combined`
unit) -- never annualized. The two operator caps bound worst-case
exposure; §13 introduces no third.

**1.6 Non-goal: Kalshi.** Settles on The Weather Company, not the NWS CLI
this estimand is built against; out of scope.

**1.7 Fee/break-even (unchanged, reused verbatim from `ladder_ev`/CRH).**
`Fee = θ·C·p·(1−p)`, `θ=0.06`, `ROUND_HALF_EVEN` (`decision.py:315` in
`_fee`). `REFUSAL_REASONS` is a 10-member closed set jointly owned with
`trial_day_latch`/`weather_common.risk.COUNTED_REFUSAL_REASONS`; new
family reasons (`rung_physically_dead`, `forecast_unavailable`,
`forecast_stale`, `no_bid_side` -- R5-1) are `RefusalCounter.record`
COUNTER reasons (free-form string), never additions to the closed
`Refuse.reason` frozenset. Executable: `0.05<price<0.95`, size≥1.

---

## 2. Null hypothesis vs Nautilus and the repo's own prior art

**Nautilus (unchanged):** forecast row / HTTP fetch / calibration fit /
strategy composition / live actor composition all REUSE PATTERN, new class,
exactly as Rev 4 §2 stated. Nightly build-time refit (§13): REUSE PATTERN
(`breezy-mb-daily.*`-shaped systemd timer+service); no online-learning
extension point exists in Nautilus, confirmed by omission (§13.2).

**Repo prior art (`ladder_ev`), per-component, corrected this revision
(R5-1, R5-5, R5-10f resolve the three items round-4 review flagged
PARTIAL/leftover):**

| Component | File:line | Verdict | Why |
|---|---|---|---|
| `LadderEvConfig` | `config.py:42-184` | EXTEND | `mode='forecast'` (§7.7); `window_start_hour_lst`/`window_end_hour_lst` (§7.7); `allow_short` stays `False` (`:159-162`), immutable |
| `exclusion_filter`/`ExclusionInputs` | `decision.py:23-111` | EXTEND (single statement, R5-10f resolves the Rev 4 §7.1-vs-§2 ambiguity) | `ExclusionInputs` gains `side: Literal["yes","no"]`; the family's own call site substitutes a side-aware legality policy for X8 (§7.4); the family's universe gate reads `cfg.window_start_hour_lst`/`window_end_hour_lst` in place of the module's `_ENTRY_WINDOW_*` constants (R5-3) -- `exclusion_filter`'s BODY is otherwise byte-unmodified (X1-X7,X9-X11, executable gates) |
| `density_table.py` | `RUNG_IDS:54` `DensityKey:58` `DensityCell:73-81` `_wilson_lower:86-94` `partition_check:126-132`, ALL VERIFIED this session, full module read | EXTEND | Existing `RUNG_IDS=("lt","i0","i1","i2","i3","gte")` and `DensityKey=(station,season,hour_lst,width_code,m_code)` are CRH's 6-rung shape and are NOT reused for this mode -- `mode='forecast'` gets its OWN outer key `(station,season,hour_lst,forecast_bucket)` and its OWN closed outcome alphabet, replacing `RUNG_IDS` for this mode only (§7.5, R5-5). `DensityCell` (VERIFIED: `p_hat`,`p_lower`,`n_cell`,`k_r` only, no `p_upper`) gains `p_upper`; a NEW `_wilson_upper` function is written (only `_wilson_lower` exists, VERIFIED `:86-94`, returns `0.0` at `total=0` -- `p_lower`/`p_upper` must be `None` below `n_min_cell`, never this degenerate zero, R5-10d) |
| `scoring.py` (`ev_net`/`OpportunityRow`/`rank_rows`/`unified_cost`/`margin`) | `:23-107` | EXTEND | `OpportunityRow` gains `side`; a NO-aware EV path calls `edge_after_costs` directly (§7.6, R5-1 rewrite: NO cost is an inverted-bid-ladder walk of the YES book, not a `^no`-book ask walk); `rank_rows`/`margin`/`unified_cost`'s ranking arithmetic REUSE-AS-IS once side-tagged rows feed it |
| `depth_adapter.py` (`depth_levels_from_book`) | `:18-41`, VERIFIED this session, full module read | **EXTEND (corrected from Rev 4's REUSE-AS-IS -- R5-1, CRITICAL)** | Existing function walks `.asks()`/`.asks` only, fail-closed (`NoExecutableDepthError`, no top-of-book fallback) -- this module gains a NEW sibling function, `bid_levels_from_book`, mirroring the same fail-closed shape over `.bids()`/`.bids`, because the NO leg has no independently quotable order-book depth on this venue (§7.6) |
| On-disk 6-rung freeze | `density_table.py:34,51` `ON_DISK_BUILD_RAN=False` | NOT RUN, build fresh | Unaffected by the key reshape; still built from injected records, never a placeholder |
| `ladder_ev/strategy.py`, `composition.py` | -- | DO NOT EXIST | §7 is their first concrete build spec |
| CRH `is_legal_cell` (`_is_legal_cell`) | `current_rung_hold/decision.py:291-305`, VERIFIED this session | REUSE-AS-IS, physical-shape helper only | `(width_code==0 and m_code==0) or width_code==1`; §7.4 routes YES/NO legality through a family-private policy that calls this as ONE input, never the only gate |
| CRH `TrialDayLatch`/`station_day_admission` | `trial_day_latch.py:1413-1480`, VERIFIED this session, full body | REUSE BY IMPORT | Neither symbol imports `continuous_strategy.py`; safe to import from a sibling Strategy |
| CRH `sibling_instrument_id`/`no_leg_instrument_id` | `symbology.py:277-286,318-325` | REUSE-AS-IS | Pure functions |
| CRH submit shape (`_maybe_submit` pattern) | cited, re-verify per §1.2 | REUSE PATTERN, own call site | `order_factory.limit(BUY, IOC, qty=1)` on the RESOLVED instrument id, `wire_price_for_leg` applied to the wire value only (§7.10) |
| CRH `offer_tape.py`/`trial_scorer.py`/`ScoredTrial` | cited | REUSE BY IMPORT | Own `family_id`/`trial_id_prefix` keeps rows disjoint |
| `current_rung_hold_v2.CombinedDraw`/`_cell_probability`/`combine_station_day`/`score_combined` | `:196-227,298-345,348-364`, VERIFIED this session, full bodies | REUSE BY IMPORT | `score()` (`:150-169`) raises `ValueError` on any `side != "yes"` row -- unusable here; `combine_station_day`/`score_combined` are the converged mixed-side path (§7.11) |
| `current_rung_hold_v2.build_stratum_v2`/`StratumV2.cell_dead` | VERIFIED this session, full body | REUSE BY IMPORT, ALSO the pre-Stage-4 per-side gate | `build_stratum_v2` itself RAISES `ValueError` on any `side != "yes"` row (VERIFIED) -- §7.6/R5-6 runs it TWICE, once per side, on YES-only and NO-only would-take subsets, never on a mixed set |
| `leg_prices.wire_price_for_leg`/`instrument_price_for_leg` | `:56-96`, VERIFIED this session, full module read | REUSE-AS-IS | Pure `1 − x` translation of the ORDER WIRE price only (venue always prices the long/YES side on the wire); unrelated to EV/cost computation, which never calls this module (R5-1 draws this boundary explicitly, §7.6/§7.10) |
| `FamilyManifest`/`load_family_manifest` | `family_manifest.py:1-213` (Rev 3 session, cross-checked; NOT re-read this session -- carried, RE-VERIFY before build) | REUSE-AS-IS for registration; EXTEND-BY-ANALOGY for §13's registry | Exact-set key validation, `DRAFT_NOT_REGISTERED`/`REGISTERED` gate, content-hash pattern; §13.3's registry mirrors the shape as a DISTINCT schema |

Nothing above requires a new Nautilus extension point. Genuinely NEW code:
`ForecastState`/`ForecastPoint` (§7.9), `bid_levels_from_book` (§7.6),
`forecast_strategy.py`/`forecast_composition.py` (§7), and (§13) new
sibling systemd units plus two new append-only schemas.

---

## 3. Data (unchanged from Rev 4)

**3.1 Sources.** Live primary: NBM NBS(+NBH) text/NOMADS, native TXN
12Z-06Z next. `api.weather.gov` is DROPPED (`SETTLEMENT_HOSTS`,
`probe_transport.py:107`). Fallback: IEM `/api/1/mos.json?model=NBS` or
NONE (refuse `forecast_unavailable`). Archive primary: IEM `mos.py?model=
NBS|GFS` CSV, NBS 2018-11→, GFS 2003-12→, 1 req/s. Coordinator probe scope
today is KMIA-only; the 4-station 2021→now overlap is a Stage 0a
DELIVERABLE. Excluded: Open-Meteo, NAM MOS (EOL ~2026-10-14), HRRR/ECMWF.

**3.2 Vintage rule.** `available_at_ns = cycle_runtime_ns + measured_
publication_lag_ns` (§4.1), never `ts_init`. Serves both the live decision
path and every §13.1 nightly refit.

**3.3 Valid-period mapping**, frozen before the fit: `(icao, runtime,
ftime) → climate_day`, MIA bleed, SFO/LAX PST miss, v5 split, DST.

**3.4 Station mapping.** `sites.toml` ICAO (KMIA/KSFO/KMDW/KLAX; KNYC
excluded), same four `pm_us_crh_cont` trades.

**3.5 Storage schema** (tall, nullable, strict Arrow): `ForecastPoint:
station, model("NBM_NBS"|"GFS_MOS"), variable("TXN"), cycle_runtime_ns,
valid_start_ns, valid_end_ns, value_f: float|None (-99/999 -> None),
available_at_ns`.

**3.6 Backfill and durable cache.** IEM `mos.py` CSV backfill script,
`(icao,runtime,ftime)` join key, 1 req/s named pacer, process-then-discard
per station-year. The IEM 1-min corpus for historical `R(t)` reconstruction
(§4.3) lands in a durable content-addressed cache mirroring `settlement_
alignment_cache.py` (sha256-keyed, coverage manifest, off-`/tmp`,
`~/.local/share/breezy/archive/`) before any 0b fit runs -- Stage 0a
deliverable. §13.1(a) reads this SAME cache; the loop adds no second one.

---

## 4. Stage 0 (no ingest/strategy code) -- load-bearing

**4.0** ONE gate: PASS iff NBS reachable with row counts for all four
stations 2021→now; GFS optional. RED test `test_reachability_probe_
reports_row_counts_not_http_status`.

**4.1 PIT lag, two-lag sensitivity.** Poll live NOMADS first-availability
vs cycle runtime, ≥100 cycles/station, stratified by cycle hour, bootstrap
CI on p95 per stratum. Pre-2026 archive rows: `lag_era = max(observed
strata) + 6h`. A cell/hour/window whose PASS/FAIL flips under both lags is
INSUFFICIENT-DATA, never a PASS. IEM `mos.py` has no publish time.

**4.2 Climate-day mapping**, frozen before the fit: 3 fixtures (MIA bleed,
SFO/LAX PST miss, DST) before 0b runs.

**4.3 Fit corpus.** IEM NBS ⨝ CLI truth, 2021-01-01..2024-12-31 fit, 2025
held out. `R(t)` source = IEM 1-min/5-min ASOS archive (§3.6, L-13 cadence
applies). NBS is the p_fc model, GFS is baseline/drift-comparison only.
§13.1(b) reuses this exact fit/holdout split shape, rolled forward.

**4.4 Trial unit.** ONE trial per station-day per family -- the first
filled take, never per-hour rows (per-hour rows are descriptive strata
only); CIs are cluster-robust block bootstrap by station-day. Hour rule:
report per LST hour 9-16; two PRE-REGISTERED windows, 09-12 and 12-17;
STOP only if NO hour in EITHER window clears the mid-book gate (≥20
station-days, ≥50% positive margin, median≥0.03). Margin schedule: the
live decision uses `margin(h, n_cell, cfg)` (`scoring.py:56-62`, `m0=0.02`
at `h0=6h`, `m24=0.06` at 24h, `None` below `n_min_cell`) -- the flat
`median≥0.03` screen is the Stage-0 measurement gate only. The key and
coarsening themselves are defined ONCE, jointly, in §7.5 (R5-5) -- this
section states the trial unit only, to avoid two competing key
definitions in one plan.

**4.5 L-21 statistic, PRE-STAGE-4 gates, INSUFFICIENT-DATA.** Among
would-take rows, station-day units, both sides: `StratumRow(side="yes"|
"no")` per would-take fill (every rung, both sides), folded through
`combine_station_day()` into one `CombinedDraw` per station-day (`x`,
`variance`, `n_constituents`), scored with `score_combined()` -- never
`score()` (raises on any `side != "yes"`).

**Reinstated PRE-STAGE-4 gates:** (1) `score_combined`'s cluster-robust
Wilson-UPPER-of-realized < mean(BE_i), n≥150 (n≥60 only if claimed p≥0.9,
realized≤0.75) → KILL, over `CombinedDraw`s. (2) `build_stratum_v2` on the
YES-only and NO-only would-take SUBSETS separately (R5-6): Stage 4 is
refused if EITHER side's `cell_dead` is True (Wilson-UPPER of that side's
hit rate < that side's mean(BE_i), n≥60). (3) 150 station-days, real
forecast source, zero honest takes → operational KILL. (4) Table-valid
calibration kill, pre-declared thresholds below. **These accumulate through
shadow plus the secondary offer-tape endpoint (§9) and gate Stage 4 ONLY --
never Stage 1, never Stage-3-start.**

**Pre-declared calibration thresholds.** Fit 2021-2024, 2025 held out:
`Brier_fc ≤ Brier_clim − δ` (INFERRED `δ=0.01` -- set by the 0b power table
before PREREG v6 registration); reliability `|observed − predicted| ≤ ε`
(INFERRED `ε=0.05`, same disposition) per bucket on the SAME holdout. The
2026 tape only TESTS against these pre-declared numbers.

**INSUFFICIENT-DATA.** Any cell/hour/window never reaching n≥20 station-
days is reported INSUFFICIENT-DATA -- extend shadow, never STOP or a
calibration verdict.

**4.6-4.10 unchanged:** MAE/RMSE-by-lead; tape completeness (incomplete
days excluded, never zero-margin); liftability (qty=1 L0-fillable fraction
from Depth10, cycle-age vs margin); staleness rule from §4.1's measured
lag; 0b reports expected takes per station-day, both sides, all rungs --
also §13.5's basis for the first-promotion-horizon estimate.

**4.11 Scripts/RED tests.** `forecast_conditional_model_study.py` (≤800
lines), `forecast_tape_screen.py` (≤400 lines). Deterministic-given-same-
inputs; train-window-leak refuses; every bucket/hour reported even on
fail; STOP/INSUFFICIENT-DATA exit 0, never raise; station-day unit never
double-counts; Wilson-UPPER-not-lower is the pre-Stage-4 refutation tail;
two-lag flip forces INSUFFICIENT-DATA. Runtime: process-then-discard per
station-year; 16G nightly cap; one heavy job at a time; one-shot wake.

---

## 5. Stage 1 ingest (only on 0b PASS) -- security pinned

| Module | Purpose | Precedent |
|---|---|---|
| `domain/forecast_point.py` | `ForecastPoint` `Data`+`register_arrow` | `station_observation.py` |
| `ingest/nbm_forecast_data_type.py` | factory, empty metadata | `iem_observations.py:36-45` |
| `ingest/nbm_forecast_transport.py` | `NbmForecastTransport(HttpTransport)` | `ingest/http.py:522-546` |
| `ingest/iem_mos_fallback_transport.py` | IEM `mos.json` fallback | same pattern, distinct `allowed_hosts` |
| `ingest/nbm_forecast_actor.py` | per-cycle timer Actor | `ingest/nws_observation_actor.py:109` |
| `ladder_ev/forecast_catalog.py` | writer+reader (§7.9) | `station_catalog_path`, tilde-guard posture |
| `ladder_ev/forecast_composition.py` | `build_live_forecast_actors(...)` | `observation_composition.py:93-157` |
| Backfill | §3.6's durable cache | `iem_asos_1min.py` pattern |

**Security items (unchanged from Rev 4):** dedicated transports, never
`ProbeTransport`, never `SETTLEMENT_HOSTS` (`allowed_hosts={"nomads.ncep.
noaa.gov"}`/`{"mesonet.agron.iastate.edu"}`); own `RequestBudget`, zero-
shared-state test; named IEM pacer, ≥1s RED test; measured `max_body_
bytes` (0a payload measurement, RE-VERIFY before build); parser raise-on-
drift RED test; `find_execution_egress_modules()` RED test; disjoint
catalog root (§7.9); systemd service+timer pair (INFERRED shape, RE-VERIFY
before build); durable-cache `coverage.json` manifest with a partial-write
RED test. `L-16` timer-swallow test, backfill process-then-discard test,
correctness RED tests (round-trip, PIT guard, sentinel parse, v5/DST
fixtures, staleness-never-silent) unchanged from Rev 4.

---

## 6. Stage 2 calibration module (unchanged)

Frozen generated table (§7.5 output) in `archive_table.py` posture, frozen
at PREREG registration with `CORPUS_SHA256`+`STUDY_GIT_SHA`; Stage 2
promotes the 0b artefact UNCHANGED; nightly job computes only the §4.5
drift/calibration monitor, never a live inline refit -- a refit is a new
family revision (§13.3's general form). Tests: table-generation
determinism; drift-monitor unit test with a synthetic value above/below
the pre-declared thresholds.

---

## 7. Stage 3 new family -- architecture, then the build

### 7.0 Route A vs Route B (unchanged, converged since Rev 3)

Route B (`ladder_ev` core + CRH infra by import) is adopted: zero edits to
`continuous_strategy.py`/`tick_eval.py`/`decision.py`/`archive_table.py`;
near-zero blast radius against the live family's decision path; reuses the
peer-reviewed 6-rung-adjacent machinery directly. §7.1-§7.9 below is the
honest accounting of Route B's own internals that round-3/4 review forced.

### 7.1 Module/class layout (extends `ladder_ev/`)

```
src/breezy/strategy/ladder_ev/
  config.py               EXTEND: mode='forecast'; window_start_hour_lst/
                           window_end_hour_lst; forecast_staleness_bound_ns;
                           publication_lag_ns
  density_table.py        EXTEND (mode-scoped, R5-5): a distinct forecast-
                           mode DensityKey/outcome-alphabet/DensityCell.p_upper
                           /_wilson_upper, never touching the existing
                           6-rung RUNG_IDS/DensityKey CRH's own mode uses
  decision.py              EXTEND: ExclusionInputs.side; the family's own
                           universe gate reads cfg.window_*; X8 is REPLACED
                           at the family's own call site (§7.4) -- X1-X7,
                           X9-X11, executable gates REUSE-AS-IS
  scoring.py               EXTEND: OpportunityRow.side; a NO-aware EV path
                           via edge_after_costs (§7.6); rank_rows/margin/
                           unified_cost REUSE-AS-IS
  depth_adapter.py         EXTEND: new bid_levels_from_book (§7.6, R5-1);
                           depth_levels_from_book REUSE-AS-IS
  forecast_state.py        NEW: ForecastState.value_at(now_ns)
  forecast_catalog.py      NEW: ForecastPoint catalog writer+reader (§7.9)
  forecast_strategy.py     NEW: ForecastLadderStrategy(Strategy) -- owns
                           on_start/on_data/the per-rung, per-side scan;
                           the side-aware legality wrapper; imports (never
                           subclasses) TrialDayLatch, station_day_admission,
                           sibling_instrument_id, no_leg_instrument_id,
                           OfferTapeRecord, StratumRow/combine_station_day/
                           score_combined/build_stratum_v2
  forecast_composition.py  NEW: build_forecast_ladder_strategies(...)
```

`lint-imports` proof (required): `ladder_ev.*` continues to never import
`current_rung_hold.continuous_strategy` -- only `current_rung_hold.
decision.is_legal_cell`, `current_rung_hold.trial_day_latch.*`,
`adapters.polymarket_us.symbology.*`, `adapters.polymarket_us.leg_prices.
wire_price_for_leg` (§7.10). `ingest.*forecast*` never imports `runtime`/
`strategy`.

### 7.2 Per-rung, per-side scan (`on_scan`)

For every listed instrument in the FORECAST ENTRY universe (4 stations,
climate day D and D+1, all listed legal rungs), for each `side ∈
{yes, no}`:

1. Compute `r_relation` from `running_max` vs the rung's own bounds
   (§1.3). If `below`: record `rung_physically_dead`, skip -- never a
   density-table lookup, either side.
2. Else compute `forecast_bucket` from the candidate rung vs `Forecast
   State.value_at(now_ns)`'s latest visible TXN. If none visible: record
   `forecast_unavailable`, skip.
3. Look up the mode-scoped density cell at `(station, season, hour_lst,
   forecast_bucket)`, select the outcome symbol matching `r_relation`
   (§7.5). `p_lower`/`p_upper` come from the SAME cell record; both `None`
   below `n_min_cell` -- record `forecast_stale` or a table-sparsity
   COUNTER reason and skip, never guess.
4. Run the side-aware legality policy (§7.4) in place of X8; run the rest
   of `exclusion_filter`'s gates REUSE-AS-IS. The universe/window gate
   reads `cfg.window_start_hour_lst`/`window_end_hour_lst` (R5-3) -- there
   is exactly ONE window gate for this family, never a second.
5. For a YES row: depth-walk `depth_levels_from_book` (asks, REUSE-AS-IS);
   `C` via `scoring.unified_cost`. For a NO row: depth-walk the NEW `bid_
   levels_from_book` on the SAME YES book (§7.6, R5-1) -- fail-closed,
   COUNTER reason `no_bid_side` on an empty bid side.
6. If eligible and `ev_net > margin(h, n_cell, cfg)`: this (rung, side) is
   a candidate row, ranked via `rank_rows` (§7.3).

### 7.3 Take cap vs trial unit (unchanged from Rev 4, SATISFIED round 4)

Two counters, never conflated: **TRIAL UNIT** (scoring, §4.4/§4.5) is one
station-day draw, first filled take, both sides pooled into one
`CombinedDraw`. **TAKE CAP** (arm-time, live) is at most one YES rung AND
one NO rung per station-day, jointly admitted by `station_day_admission`'s
Σq≤1 gate. `max_per_city_day=1` (`config.py:143`) is DEGRADED mode's own
YES-only cap and is never read here; `rank_rows`'s city-day de-dup
(`scoring.py:97-105`) is likewise a DEGRADED-mode convenience this family
does not rely on -- `ForecastLadderStrategy` calls `rank_rows` separately
per side and gates the actual submit through `station_day_admission`
jointly across both takes before either is armed (§7.10). A SAME-RUNG
YES+NO double take is additionally refused at ARM TIME (R5-4, new): the
take-cap policy checks whether the OTHER side already holds a filled trial
on the SAME rung for this station-day (mirroring CRH's own `_SameRung
OppositeSidesRefusal`, `current_rung_hold_v2.py:304-307`, which today only
fires post-fill inside `combine_station_day`) and refuses the SECOND take
with a new COUNTER reason `same_rung_opposite_side`, with a RED test --
defence in depth over `combine_station_day`'s own post-fill refusal, never
a replacement for it.

### 7.4 Side-aware legality policy replaces X8 (unchanged from Rev 4, SATISFIED round 4)

`exclusion_filter`'s X8 (`decision.py:91-93`) delegates to `is_legal_cell`,
which admits interiors only at `m_code==0`; a forecast-implied interior
above `running_max` has `m_code<0` by construction and dies here
unconditionally. **Policy (family's own call site, `is_legal_cell` itself
untouched):** YES legal iff interior-or-open-upper (physical shape, via
`is_legal_cell` as a helper) AND `r_relation ∈ {contains, above}`. NO legal
iff `r_relation ∈ {contains, above}` on the candidate's `^no` leg; a rung
already below `running_max` is a certain NO winner and is refused
`rung_physically_dead` for NO too (L-9: a certain outcome is not an edge).
`ExclusionInputs` gains `side`. X1's physical fact is YES-directional as
written; the `r_relation=below` refuse in §7.2 step 1 subsumes X1's role
for both sides before `exclusion_filter` is even called -- no second X1
variant needed. §7.13's control run (unmodified `is_legal_cell`-only
legality) is the load-bearing proof this fix matters.

### 7.5 Density table: one shape, closed outcome alphabet, `p_upper`/NO bound (R5-5)

**One shape everywhere.** `ForecastDensityTable[(station, season,
hour_lst, forecast_bucket)][outcome]` -- the OUTER key is the 4-tuple; the
INNER dict is the closed outcome alphabet. This is a MODE-SCOPED type
(`ForecastDensityKey`/`ForecastDensityTable` in `density_table.py`,
distinct names from CRH's existing `DensityKey`/`RUNG_IDS`, R5-5/R5-10
correcting round-4's "replace `RUNG_IDS` for this mode" wording -- the
existing 6-rung `RUNG_IDS`/`DensityKey`/`build_density_table` stay byte-
unmodified for CRH's own mode; this family's builder is a SEPARATE
function over the SAME `DensityCell`/`_wilson_lower` shapes, extended with
`p_upper`/`_wilson_upper`).

**Closed outcome alphabet.** Outcomes are settled-rung positions RELATIVE
to `R(t)`'s rung at settlement, clamped to a fixed alphabet: `{below,
contains, above1, above2, above3+}` -- `below`/`contains` mirror `r_
relation`; `above1..above3+` bucket the settled distance in rungs above
`R(t)` (3+ pooled for sparsity). `build_forecast_density_table` raises on
any symbol outside this alphabet -- one `ForecastDensityRecord` per
(station, climate_day, hour_lst, forecast_bucket), whose outcome is the
SETTLED rung's alphabet symbol relative to `R(t)` AT THAT HOUR (never one
record per candidate rung per hour, which would be n-inflation). The
partition check (`partition_check`-shaped: Σp=1 within `1e-9`) runs per
OUTER key, summed over whichever alphabet symbols were actually observed
at that key. `r_relation` of a CANDIDATE rung at scan time (§7.2) selects
which alphabet symbol(s) its own EV lookup uses -- `contains`/`below` map
1:1; `above` maps to whichever of `above1..above3+` the candidate's own
rung-distance from `running_max` falls into.

**`p_upper`/NO bound.** `DensityCell` (this mode's own instances) gains
`p_upper` -- the SAME Wilson interval computed once per cell (mirrors
`archive_table.py`'s cached-interval pattern); `_wilson_upper` is a NEW
function (only `_wilson_lower` exists today, VERIFIED `:86-94`). YES uses
`p_lower`; NO uses `1 − p_upper` (mirrors CRH's own `p_miss_lower = 1 -
P_HOLD_UPPER` convention, `decision.py`'s `DecisionInputs` docstring,
VERIFIED this session at the NO-inversion note). `1 − p_lower` for a NO
candidate is FORBIDDEN -- anti-conservative, understates the true miss
probability using the wrong tail. Below `n_min_cell=90`: `p_lower`/
`p_upper` are BOTH `None` (never `_wilson_lower(0,0)=0.0`); a candidate
whose cell is `None` records a table-sparsity COUNTER reason and is
skipped, never armed on a fabricated `p=0`/`p=1`.

### 7.6 Side-aware scoring, NO-leg pricing = inverted bid-ladder walk (R5-1, R5-6)

`ev_net` (`scoring.py:45-53`) hardcodes `intent_long_yes=True`;
`OpportunityRow` (`:23-38`) has no `side` field today. `OpportunityRow`
gains `side: Literal["yes","no"]`. The family's own scan calls `edge_
after_costs` directly (already accepts an `intent_long_yes` flag) with
`intent_long_yes=(side=="yes")`, rather than routing through the
unmodified `ev_net()` -- `ev_net()` stays DEGRADED-mode's own YES-only
convenience function, untouched.

- **YES row:** `ev_net = p_lower − C`, `C` = `scoring.unified_cost` on the
  YES-leg book's ASKS (`depth_levels_from_book`, unchanged).
- **NO row (R5-1, CRITICAL correction from Rev 4):** there is NO
  independently listed/quotable `^no` order book on this venue -- the
  venue prices the long (YES) side only, and Breezy never subscribes
  depth on a distinct NO instrument. `ev_net_no = (1 − p_upper) − C_no`,
  where `C_no` is `scoring.unified_cost` computed on the INVERTED YES-book
  BID ladder: walk `bid_levels_from_book(book)` (§7.2 step 5, §2), price
  each level as `1 − bid_price`, size = that level's displayed bid size --
  exactly CRH's own live convention (`NO_ask = 1 − bid`, sized on
  `bid_size`, computed inside `evaluate_decision`, never by the caller;
  `current_rung_hold/decision.py`'s `DecisionInputs` docstring, VERIFIED
  this session). This is the ONLY inversion in the cost path; `leg_prices.
  wire_price_for_leg` is NEVER called here -- it translates the ORDER WIRE
  price at SUBMISSION time (§7.10), a distinct concern from EV/cost
  computation, and this plan draws that boundary explicitly so a future
  reader does not conflate "the NO leg has its own book" (false) with "the
  NO leg has its own wire-price convention for submission" (true, §7.10).
  A one-sided book (empty bid side) is common on this venue (memory:
  "Weather market bid side is empty" / QuoteTicks cannot show an empty
  bid, use Depth10) -- `bid_levels_from_book` fails closed, COUNTER reason
  `no_bid_side`, a named §9/§10 live-feasibility risk for the NO leg.
- `rank_rows`'s ranking arithmetic (`_sort_key`/`_roi`, `scoring.py:76-96`)
  is REUSE-AS-IS once fed side-tagged rows.
- **Pre-Stage-4 side-split gates (R5-6).** `build_stratum_v2` RAISES on any
  `side != "yes"` row (VERIFIED this session) -- the pre-Stage-4 Wilson
  gates therefore run it TWICE, once on the YES-only would-take subset and
  once on the NO-only would-take subset (each independently `cell_dead`-
  checked, `current_rung_hold_v2.py:385-437`); Stage 4 is refused if
  EITHER side's cell is dead. `score_combined` (mixed-side) remains the
  sequential PREREG statistic (§7.11, §9) -- the two mechanisms serve
  different questions and neither substitutes for the other. Drop any
  hand-written `S` formula; cite `score_combined` (`:348-364`) directly.

### 7.7 Config: window fields, three mode branches (unchanged from Rev 4)

**Window (R5-3, restated once, no other section repeats it).** `_ENTRY_
WINDOW_START_HOUR=12`/`_END_HOUR=17` (`decision.py:17-18`, used at `:104`)
become `LadderEvConfig` fields `window_start_hour_lst`/`window_end_hour_
lst`, defaulting to the SAME `(12,17)`. `exclusion_filter` itself is not
edited for the window; this family's own universe gate in `forecast_
strategy.py` reads the config fields directly, satisfying the §4.4/§7.13
requirement that a 10 LST fixture be reachable without the standing 12-17
constant blocking it.

**Three mode branches.** `LadderEvConfig.__post_init__` (`config.py:
158-184`) has three branches touching `mode`: (1) `'full'` stays a hard
refusal, `mode='forecast'` never routes through it. (2) `if self.mode !=
"degraded": raise ValueError` widens to `if self.mode not in ("degraded",
"forecast"): raise ValueError`. (3) `raw_corpus_pin` still pins the SAME
RAW archive corpus bytes regardless of mode; `mode='forecast'` construction
ADDITIONALLY validates a second pin, `forecast_corpus_pin`, against a new
`FORECAST_CORPUS_SHA256` constant (the RAW forecast+CLI join corpus §4.3's
fit ran against) -- the existing check is never weakened or bypassed, a
second additive check runs alongside it.

### 7.8 Live contention -- per-shared-key namespacing, permit displacement (R5-2, R5-4, R5-10a)

Route B's live contention is account-level, not family-namespaced, in
four places (extends Rev 4's three-row table to the permit-exclusivity
consequence R5-2 makes explicit):

| Shared resource | Where | Namespacing today | This family's posture |
|---|---|---|---|
| Attempt counter | `ATTEMPT_COUNTER_KEY_PREFIX` (`trial_day_latch.py:319`), a MODULE CONSTANT | NOT namespaced by family | REQUIRED (R5-10a): BOTH `record_attempt` (9 callers) AND `_attempt_key` (`:1130-1136`, VERIFIED this session: `base = f"{ATTEMPT_COUNTER_KEY_PREFIX}{station}/{climate_day}"`, hardcodes the module constant) are EXTENDED to accept a `prefix` parameter -- Rev 4 extended only `record_attempt`; `_attempt_key` closes over the same constant internally and must take the parameter too, or the extension is a no-op. Default-preserving: `pm_us_crh_cont`'s call sites pass no prefix and are unaffected, proven by the existing test suite staying green |
| In-flight marker | `TrialDayLatch.consume_if_absent`, `_key`'s `key_prefix` param (`:365-399`) | Already namespaced by design | This family passes `forecast_ladder_edge/trial/`; REUSE-AS-IS |
| Day-budget exhaustion | `is_day_budget_exhausted(utc_day)` (`:1006`) | Shared BY DESIGN -- the two operator caps are account-wide | Stated honestly: both Strategies in one node share ONE daily budget ceiling |
| Order-submission permit -- EXCLUSIVE, not merely shared (R5-2) | `OrderSubmissionPermit` (`order_enablement.py:156`, `.issue()` `:177-242`, VERIFIED this session, full body) gated by `rung_hold_family = settings.current_rung_hold is True or settings.continuous_rung_hold is True` (`:224-226`, VERIFIED exact) | ONE permit object per node; `phase1_family_permits` (`composition.py:247-281`, VERIFIED this session, full body) routes it to exactly ONE of the two existing families and refuses both together outside `phase0_shadow`; `load_trade_settings` (`settings.py:790-859`, VERIFIED, exclusivity check at `:823-833` exact) refuses the pair at load time | **EXTENDED to three families (R5-2, coordinator decision), never merely "shared":** a new `BreezyTradeSettings.forecast_ladder_edge: bool` field + env var; `OrderSubmissionPermit.issue()`'s gate widens to `rung_hold_family = current_rung_hold or continuous_rung_hold or forecast_ladder_edge`; `phase1_family_permits` gains a third bool parameter and a third return slot, returning the permit to WHICHEVER SINGLE family is on and `(None,None,None)` if none is; `load_trade_settings`'s exclusivity check widens to refuse ANY two of the three together -- the existing `phase0_shadow` escape hatch is NOT extended to the forecast family (it remains scoped to the legacy `current_rung_hold`+`continuous_rung_hold` pairing only; the forecast family has no dual-family shadow mode). The mutual-exclusion contract test (`tests/contract/test_rung_hold_families_mutual_exclusion_contract.py`, VERIFIED this session, full source) is AMENDED with new cases: all three pairs refused, each family alone boots, the `phase0_shadow` pair-only case is unchanged -- a STRICTER test, never weakened, security-reviewer sign-off required (§11) |
| OPEN submit intent | Account-wide | Shared by design | Identical first-order protocol CRH already uses |

**Permit-displacement consequence, stated honestly (R5-2).** Arming `pm_us
_crh_fc_v1` sets `forecast_ladder_edge=True`, the operator flow's ONLY
active flag. `pm_us_crh_cont` keeps constructing/SCANNING (offer-tape rows
written) in shadow, but `_submission_armed()` (`continuous_strategy.py:
658-672`) returns `False` and `_maybe_submit` no-ops. **INFERRED (from
PREREG v3's discipline -- LD-OBF looks only on filled Takes, shadow trials
never feed a verdict, lesson `prereg-v3-sequential-ruling-2026-09-04`):**
its LD-OBF `S_k`/`n_k` clock PAUSES (no fills possible), but its 15-day
0-fill structural KILL clock (§9, gated on scan-live not arming) CONTINUES
to accrue -- displacement risks tripping that clock as an accepted
consequence of this decision. **RE-VERIFY against PREREG v3's literal text
before Stage 4 arming**; this risk is named, not resolved, here.

**Live-contention test (unchanged shape from Rev 4, now asserting the
three-way exclusivity too):** a fixture with all applicable strategies
against the SAME `StateStore`/permit/day-budget instance; assert (i) an
attempt recorded under one family's own prefix is invisible to another's
re-arm gate; (ii) day-budget exhaustion set by either is observed by both;
(iii) `permit=None` disarms `_maybe_submit` identically; (iv) `phase1_
family_permits` never returns a non-`None` permit to more than one of the
three slots, for any input (property test over all 8 boolean combos, R5-2).

**Same-rung arm-time refusal (R5-4).** See §7.3 -- `same_rung_opposite_
side` is a new COUNTER reason checked at arm time, defence in depth over
`combine_station_day`'s post-fill `_SameRungOppositeSidesRefusal`.

### 7.9 `ForecastPoint` catalog writer/reader (R5-10b)

Named Stage 1 deliverable (`ladder_ev/forecast_catalog.py`, §5):
**Partitioning:** by `(station, climate_day)`. `station_catalog_path
(base, venue, city)` (`catalog.py:341-388`) itself takes exactly TWO
components (`venue`, `city`) and does not accept a `climate_day` -- this
module therefore writes its OWN partition-path helper for `(station,
climate_day)`, distinct from `station_catalog_path`, rather than
misapplying that helper's two-component signature (R5-10b names this
precisely so the build does not silently drop the `climate_day` axis).
**Composite id separator:** `^`/`:` per the tilde-guard memory -- a bare
`~` breaks every catalog read with a SQL `ParserError`; ids are built
exclusively through the shared separator helper. **Read-back RED test:** a
row written and read back is byte-identical on every field, including any
`~`-bearing station/model string -- a precondition for `ForecastState.
value_at` (§7.2 step 2) ever being trustworthy, since a silently corrupted
read would present as `forecast_unavailable` at best or a wrong `forecast_
bucket` at worst. Catalog root disjoint from CRH's and `pm_us_crh_cont`'s
own roots (security item 7, §5).

### 7.10 YES and NO take construction

- **YES take:** the candidate rung's own listed instrument id --
  `order_factory.limit(OrderSide.BUY, time_in_force=IOC, price=tick_ceil
  (p_worst), quantity=1)`, `self.submit_order(order)`.
- **NO take:** `sibling_instrument_id(candidate_rung_instrument_id)`
  (`symbology.py:318-325`, REUSE-AS-IS) -- the SAME `order_factory.limit
  (OrderSide.BUY, IOC, qty=1)` call, on the `^no` leg id, with the SUBMIT
  price translated through `leg_prices.wire_price_for_leg("no", instrument
  _price)` (VERIFIED this session: `1 − instrument_price`, the venue
  always prices the long side on the wire) -- **this is the SUBMISSION-
  TIME wire translation only, unrelated to the EV/cost computation of
  §7.6, which never calls `wire_price_for_leg`** (R5-1 draws this boundary
  explicitly: the NO leg has no own order book to walk for EV, but it IS a
  real, order-placeable instrument on the venue, and the SUBMIT price for
  it is computed by this existing, unchanged translation). Never `OrderSide
  .SELL`/`SELL_SHORT`.
- Before either submit: `station_day_admission(...)` (REUSE-AS-IS) gates
  Σq≤1 jointly across both takes; the arm-time `same_rung_opposite_side`
  refusal (§7.3/§7.8, R5-4) runs first.
- `TrialDayLatch.consume_if_absent(...)` keyed on `(station, climate_day,
  key_instrument_id)`, this family's OWN `trial_id_prefix`.
- Both submit paths obtain the SAME `OrderSubmissionPermit` (§7.8) and
  check `_submission_armed`'s equivalent predicate before `submit_order`.

### 7.11 Scorer integration (unchanged mechanism from Rev 4, R5-6 adds the side-split gate at §7.6/§9)

Every would-take fill becomes one `StratumRow(side="yes"|"no", entry_ask=
..., fee=..., held=..., rung=<base slug>)`; `_MixedDayMissingRungKeyRefusal`
requires `rung` on every row once a NO row exists -- this family's rows
always carry it. All of a station-day's rows fold through `combine_
station_day()` into one `CombinedDraw`; `score_combined()` produces the
`ScoreState` used for BOTH the Stage-0b screen (§4.5) and the live PREREG
statistic (§9). `score()` is NEVER called by this family. This is the
single mixed-side scorer entry point cited throughout §4.5, §9, §12; §7.6
names the SEPARATE per-side `build_stratum_v2` gate, which answers a
different (pre-Stage-4 per-side health) question and never substitutes for
`score_combined`.

### 7.12 Manifest

| Property | Value |
|---|---|
| `family_id` | `pm_us_crh_fc_v1` |
| `trial_id_prefix` | `forecast_ladder_edge/trial/` (attempt prefix: `forecast_ladder_edge/attempts/`, §7.8) |
| Stations | LAX, MDW, MIA, SFO |
| `d0_climate_day` | Set at registration, never retroactive |
| Decision core | `ladder_ev` (extended, `mode='forecast'`) -- NOT `ContinuousRungHoldStrategy` |
| Order/infra | CRH's `TrialDayLatch`/`station_day_admission`/`sibling_instrument_id`/`wire_price_for_leg`/offer-tape/`OrderSubmissionPermit` BY IMPORT (§7.8 names the shared-state contention AND the permit-exclusivity extension honestly) |
| NO submit | `OrderSide.BUY` on `^no` leg; EV/cost from the inverted YES-book bid ladder (§7.6/R5-1), never a `^no`-book ask walk |
| Both sides | Every legal rung, both sides, side-aware legality (§7.4), forecast-mode density table (§7.5) |
| Window | Config field, own pre-registered window (§7.7) |
| PREREG | `combine_station_day`/`score_combined` (mixed-side statistic, §7.11); PLUS the per-side `build_stratum_v2` pre-Stage-4 gate (§7.6/R5-6); own 15-day KILL clock (§9); secondary offer-tape endpoint doubles as §13's shadow-scoring source; hold-to-settlement, exit UNARMED |
| Shadow | ≥30 covered station-days, `permit=None`, before any enablement conversation |
| Arming | Stage 4 DISPLACES `pm_us_crh_cont` as the sending family (§7.8/R5-2) -- never "armed together" |
| Learning loop | Trades the frozen champion artefact only (§13); this manifest's `family_id` is the CHAMPION's; a promotion mints a NEW manifest, never edits this one |

### 7.13 The reach-the-goal integration test (RED first, R5-9 corrects the citation)

`test_forecast_ladder_produces_no_and_yes_takes_and_crh_stays_byte_
identical` -- written RED before `forecast_strategy.py`/`forecast_
composition.py`/`forecast_catalog.py` exist. Setup: a recorded/synthetic
station-day fixture, NBM MaxT far above `R(t)` at 10 LST (inside this
family's own configured window, §7.7), `ForecastPoint` rows written
through §7.9's catalog writer and read back through its reader, a
`RunningMax` fixture, ONE synthetic one-sided book (empty bid on at least
one candidate) to exercise `no_bid_side` (§7.6); both strategies wired via
`run_backtest`/`backtest` (`runtime/backtest_harness.py:958-1024`,
VERIFIED this session, full body: `allow_rejected_orders`/`allow_open_
positions`/`allow_idle_strategies` are three SEPARATE flags, never one
`strict` switch) against the SAME tape/catalog, sharing ONE `StateStore`/
`OrderSubmissionPermit`. `ForecastLadderStrategy` never holds a real
permit here; the predicate-identity restatement of "backtest subclass
never holds a permit" (R5-9) is: the family's OWN backtest harness class
overrides `_submission_armed()` to read a private flag, mirroring the
ACTUAL pattern -- `ContinuousRungHoldBacktestStrategy._submission_armed`
(`current_rung_hold/continuous_backtest_only.py:154-155`, VERIFIED, full
module: `return self._backtest_submit_enabled`), overriding the BASE
`ContinuousRungHoldStrategy._submission_armed` (`continuous_strategy.py:
658-672`, VERIFIED: `return self._order_submission_permit is not None`;
its docstring at `:668-670` names this override -- Rev 4's `continuous_
strategy.py:668-671` citation was that docstring reference, not the
override body, which lives in the separate `continuous_backtest_only.py`
module; corrected here). `run_backtest(..., allow_open_positions=True,
allow_idle_strategies=True)` covers the hold-to-settlement double take and
the CRH-absent control run. Asserts:

(i) `ForecastLadderStrategy` emits exactly one NO take -- legal under
§7.4's policy despite `r_relation=contains` -- priced via the inverted-bid
walk (§7.6), submitted `OrderSide.BUY` on `sibling_instrument_id` through
the shared permit/latch/submit path, `wire_price_for_leg("no", ...)`
applied only at submission;

(ii) it also emits exactly one YES take on the forecast-implied `r_
relation=above` rung -- legal under §7.4, which unmodified `is_legal_cell`
alone would refuse as `illegal_cell` (a control run using unmodified
legality FAILS this assertion, proving the fix is load-bearing) --
`station_day_admission`'s Σq gate satisfied jointly with (i);

(iii) a THIRD candidate rung with an empty bid side records `no_bid_side`
and is never armed (R5-1's fail-closed proof);

(iv) both real fills score as one `CombinedDraw` via `combine_station_
day`; a direct call to `score()` on the same two rows RAISES `ValueError`;
a direct call to `build_stratum_v2` on the mixed pair ALSO raises (R5-6);
`build_stratum_v2` on the YES-only subset and the NO-only subset each
succeed independently;

(v) `ContinuousRungHoldStrategy`'s Decision stream over the IDENTICAL
tape/catalog is byte-identical to a control run with `ForecastLadderStr
ategy` absent -- proving the shared `StateStore`/`TrialDayLatch`/permit
namespacing and the additive `_DATA_TYPE_FACTORIES` entry introduce zero
behaviour change;

(vi) the §7.8 live-contention assertions (attempt-counter isolation,
shared day-budget, shared permit predicate, three-way permit exclusivity)
run as part of this SAME fixture.

This is the plan's concrete proof it reaches the stated goal state.

---

## 8. Stage 4 arming

Existing manifest gate (`deploy/families/*.json`, `status: DRAFT` until
registration, `FamilyManifest`/`load_family_manifest` REUSE-AS-IS row).
Positive control: reused rest-and-cancel pattern (venue-level).
**Operator-only:** enablement, the two named budget caps (name-only).
**Build-side:** everything else, including all pre-Stage-4 gates (§4.5
mixed-side AND §7.6's per-side `build_stratum_v2` gates) passing.
**Arming this family DISPLACES `pm_us_crh_cont` as the sending family
(R5-2)** -- the enablement flow sets exactly one of the three settings
flags (§7.8); this is stated here as the Stage-4 consequence, not merely
a §7.8 implementation detail. §13 introduces no additional operator-only
step (§13.3).

---

## 9. Kill gates and stop rules (pre-declared)

| Stage | Kill condition | Number |
|---|---|---|
| 0a | NBS unreachable, any station (GFS optional) | go/no-go |
| 0b cheap screen | 0.25-0.75 bucket fails at EVERY reported hour in BOTH windows | ≥20 station-days, ≥50% margin>0, median≥0.03 |
| 0b | Two-lag PIT sensitivity flips PASS/FAIL for a cell | INSUFFICIENT-DATA |
| 0b | Any cell/hour/window under n≥20 station-days | INSUFFICIENT-DATA, extend shadow |
| Pre-Stage-4 | Mixed-side Wilson UPPER < mean(BE_i), n≥150 (n≥60 if p≥0.9, realized≤0.75), via `score_combined` over `CombinedDraw`s | §4.5(1) |
| Pre-Stage-4 (R5-6) | EITHER side's `build_stratum_v2(side-only subset).cell_dead` | §4.5(2) |
| Pre-Stage-4 | 150 station-days, real source, 0 honest takes | §4.5(3) |
| Pre-Stage-4 | Table-valid calibration kill, pre-declared 2025-holdout thresholds | §4.5(4) |
| 3 | `total_pnl ≤ −60` | −60 |
| 3 | LD-OBF `S_k ≤ b_k^fut` (via `score_combined`), or either side's `cell_dead` at n≥60 | pending Var(S) check |
| 3 structural | 15-day 0-fill KILL clock -- starts once the ladder-scan AND the NO-take path are BOTH live; **runs while displaced too (§7.8's honest consequence)** | own counter, tested to increment |
| 4 | Positive control fails | binary |
| Any | `duplicate_fill` fires | family halt, operator-visible clear only |
| §13 | No challenger clears promotion in `T` days (INFERRED `T=90`) | ledger status line only, never a threshold relaxation (§13.6) |
| §13 | CHAMPION breaches Stage 2 drift/calibration monitor | REJECTED, fallback to shadow-only on last-good artefact (§13.3) |
| §13 (R5-8) | A §9 KILL is tripped or PENDING at the next scheduled look | promotion REFUSED this cycle, re-checked next cycle, never overridden |

**Secondary endpoint:** shadow-scored offer-tape rows (this family's OWN
tape) PRE-REGISTERED as the LEARNING statistic, scored nightly vs CLI
finals, NEVER feeding `S_k`; §13's challenger shadow-scoring reads the
SAME tape. Sizing (deferred): bounded by the two operator caps, unchanged
by any promotion.

---

## 10. Risks and open questions

| Risk | Resolution |
|---|---|
| `ladder_ev`'s reshape is itself untested code in a PARKED package | New unit tests land alongside; existing `tests/strategy/ladder_ev/*` prove no DEGRADED-mode regression |
| Two/three Strategies sharing one `StateStore`/permit could collide on a key-collision bug | §7.13's integration test is the direct proof; §7.8's live-contention assertions run inside it |
| 4-station 2021→now IEM overlap is currently KMIA-only | §4.0 extends before 0b runs |
| NBM TXN window ≠ climate day at every station | §4.2's frozen map + fixtures must pass RED before the fit |
| v5 cycle change may shift TXN semantics silently | §4.3/§4.6's pre/post-v5 split is the measurement |
| Forecast may already be priced in (L-7) | §4.8 cycle-age-vs-margin is the direct test |
| Table sparsity at rare cells | §7.5 coarsening + `n_min_cell=90` refuse-not-guess (both `p_lower`/`p_upper` `None`) |
| Is `gs_boundary_pm_us_crh_v2.json` valid for this family's Var(S) | Run the consistency check before PREREG registration; §13.3's `boundary_inputs_sha256` makes this a BLOCKING promotion step, not a by-product (R5-8) |
| §3.6's durable IEM-1min cache does not yet exist | Named Stage 0a deliverable, blocking 0b's fit |
| **NO-leg pricing risk (R5-1, new):** the YES book's bid side is frequently empty on this venue (memory: bid side is empty), so a meaningful fraction of NO candidates will hit `no_bid_side` and never be evaluated | Named, counted refusal reason; §7.13's fixture exercises it directly; §4.10's trial-frequency estimate must report the NO-side `no_bid_side` rate alongside its takes-per-day estimate, not just the aggregate |
| **§7.8 permit displacement risk (R5-2, new):** displacing `pm_us_crh_cont`'s permit risks tripping its own 15-day structural KILL purely from the hand-off, independent of edge | Stated in §7.8/§8/§9; RE-VERIFY against PREREG v3's literal clock-trigger text before Stage 4 arming -- this plan flags the risk, it does not resolve PREREG v3's own wording |
| **Pre-existing `tests/integration/test_forecast_edge_backtest.py` (discovered this session via blast-radius on `run_backtest`, NOT read this session)** | A test file with this exact name already exists in the tree. Before Stage 3 build starts, its contents must be read and reconciled with §7.13 -- either it is an existing fixture this plan's test should extend/rename into, or it is unrelated prior work that must not silently collide with the family_id/module names this plan introduces. Named here as an explicit Stage-3 precondition, not assumed away |
| `OrderSubmissionPermit`'s exact mint call site is now resolved (`order_enablement.py:177-242`, VERIFIED this session, full body) | No longer open -- `safety.py:552-608` was Rev 3's stale citation; closed (R5-10g) |
| A promoted challenger's first revision inherits an unmeasured trial-frequency | Its own §4.10-equivalent output, produced once the champion accrues tape, replaces any sibling-family analogy before promotion math is trusted |

---

## 11. Build order

| Stage | Depends on | Effort | Reviewer |
|---|---|---|---|
| 0a reachability + durable cache (§3.6) | RULING filed | S | none (measurement) |
| 0b fit + cheap screen + two-lag sensitivity (§4.1-4.3, §7.5) | 0a PASS | M | prediction-market-reviewer |
| Pre-Stage-4 gates computed (§4.5-4.10, incl. §7.6's per-side gate) | 0b PASS or INSUFFICIENT-DATA extends shadow | M | prediction-market-reviewer + mle |
| 3.0 `ladder_ev` extension (mode='forecast', density/legality/scoring/depth reshape, §7.1-§7.7) | 0b PASS | M | python-reviewer |
| Live-contention + 3-family permit exclusivity wiring/test (§7.8) | 3.0 merged | S | python-reviewer + security-reviewer (permit/intent sharing AND the widened exclusivity contract test) |
| 1 ingest, incl. `forecast_catalog.py` (§5, §7.9) | 3.0 merged | M | python-reviewer + security-reviewer |
| 2 calibration module | Stage 1 schema fixed | S | prediction-market-reviewer + python-reviewer |
| 3 `forecast_strategy.py`/`forecast_composition.py` + PREREG (§7.10-§7.12) | Stage 2 table frozen | M-L | prediction-market-reviewer + python-reviewer |
| 3.9 §7.13 integration test (incl. §7.8 live-contention, `no_bid_side`, pre-existing test-file reconciliation) | 3 merged | S | python-reviewer, sign-off mandatory (reach-the-goal proof) |
| 4 arming (displaces `pm_us_crh_cont`) | Stage 3 green, PREREG registered | S | prediction-market-reviewer |
| 5 shadow, ≥30 station-days | Stage 4 | elapsed time | ongoing, no reviewer gate |
| 5+ learning-loop artefact registry + ledger schema (§13.3-§13.4) | Stage 4 (champion registered) | M | python-reviewer |
| 5+ nightly refit jobs + systemd units (§13.2, §13.4) | learning-loop schema merged | M | python-reviewer + security-reviewer (egress-scope per job) |
| 5+ shadow-scoring + promotion-rule engine, incl. §13.3's paired estimator and KILL-clock refusal (R5-7/R5-8) | nightly jobs green | M | prediction-market-reviewer + python-reviewer |
| 5+ promotion RED tests (leakage, determinism, promotion-rule, rollback-as-new-revision, R5-8's KILL-pending refusal) | promotion engine merged | S | python-reviewer, sign-off mandatory |

`lint-imports` green is a completion criterion of every row, including
the learning-loop rows, not a stage of its own.

---

## 12. Self-review vs the 18 binding constraints (`seams/result_C.md`)

| # | Constraint | Satisfied how |
|---|---|---|
| 1 | L-9 lock is dead | Reused gates plus §7.4's side-aware policy evaluate every rung continuously in-window; a certain-outcome rung is refused `rung_physically_dead` on BOTH sides |
| 2 | Edge is calibration vs the book | §4.5's kills discriminate, gate Stage 4 only, scored via `combine_station_day`/`score_combined` PLUS §7.6's per-side `build_stratum_v2` gate (R5-6) |
| 3 | Ingest is Gate 0 | §5 is Stage 1, gated behind §4 AND §4.5; §13's nightly jobs are Stage 5+, gated behind a REGISTERED champion |
| 4 | K1-before-build | §4.0-4.10 mirror K1, station-day units, two-lag sensitivity; §13.4's walk-forward guard applies the same discipline to every nightly refit |
| 5 | L-21: no refit after a miss | §4.5 kill, gates Stage 4 only; §13's promotion rule is pre-declared before any challenger sees a miss, scored on a holdout the fit never touched -- a refit is always a NEW revision |
| 6 | Post-peak cheap book is a lost lottery | §7.2's reused Xc/X3 rules encode this, unaffected by the reshape |
| 7 | L-7 public info has no offer | §4.8; §13.5 states the loop cannot learn venue reaction or counterfactual fills |
| 8 | L-8 coverage = row counts | §4.0 RED test; §3.1 scoped as KMIA-only, not a 4-station fact |
| 9 | Forward-only prices | §1 non-goals; §4 screens tape, never historical ROI; §13.2's backtest reuse is walk-forward evaluation of a candidate artefact |
| 10 | New family + own D0 | §7.12; a promoted challenger mints a NEW `family_id`/D0/`trial_id_prefix` (§13.3), never an in-place edit |
| 11 | LD-OBF, Wilson terminals | §7.12/§9, `combine_station_day`/`score_combined`, pending Var(S); §7.6's per-side gate is a SEPARATE, additional pre-Stage-4 check |
| 12 | 15-day KILL, tickable counter | §9, gated on ladder-scan+NO-path live; §7.8 states honestly that displacement leaves this clock running against `pm_us_crh_cont` too |
| 13 | Two operator caps | §1.5/§8, no third knob; §13.3 states explicitly the loop introduces none |
| 14 | Stage-0 before code | §4 precedes §5-8; §4.5 additionally blocks Stage 4; §13.6 extends this to Stage-5-before-any-relaxation |
| 15 | Hard safety floor | §0.2 RULING; no new order path (§1.2/§7.10); the mutual-exclusion contract test is AMENDED, never weakened (R5-2); §13's nightly jobs get the same egress-scope review as any new ingest module |
| 16 | Standing verdicts KILLED | §0.2 RULING supersedes, scoped; §13's second operator requirement is scoped by the SAME ruling |
| 17 | L-13/L-16/L-35 | §4.3 (L-13, §3.6's cache); §5 (L-16 test); §13.1(b) reuses `fit_error_model`'s cadence discipline; L-35's Depth10-not-QuoteTick posture now ALSO backs the NO-leg's inverted bid walk (§7.6, R5-1) |
| 18 | 09-15 diagnosis | §1.1's rationale; §7.6's corrected NO-leg pricing (R5-1) is the mechanism that actually harvests the miss, not a `^no`-book fiction; §13.1(c) addresses the same miss on a pre-registered, holdout-fit basis |

**RE-VERIFY BEFORE STAGE 3 BUILD:** §1.2's `_maybe_submit` exact line
range; §5 item 4 (measured `max_body_bytes`) and item 8 (systemd unit
directives); the pre-declared `δ`/`ε` calibration constants (INFERRED
pending the 2025-holdout 0b output); `family_manifest.py:175-184`'s exact
`UnpinnedBoundaryArtefactError` shape (carried from Rev 3, NOT re-read
this session -- corroborated but due a direct re-read); the contents of
the pre-existing `tests/integration/test_forecast_edge_backtest.py`
(§10); PREREG v3's literal clock-trigger wording for the §7.8 displacement
consequence.

---

## 13. Self-learning loop (Stage 5+)

Operator requirement (verbatim, §0.2): "the trading bot must have self-
learning functionality. As it trades, as it ingests more data, it learns,
and improves the forecasting trading." Sanctioned shape: CHAMPION/
CHALLENGER with a PRE-REGISTERED UPDATE POLICY. The champion (this
family's manifest, §7.12) trades on a frozen artefact for its entire life;
nightly build-time jobs fit challengers from growing data; challengers are
shadow-scored, never armed; promotion happens only under pre-declared
rules and always mints a NEW family revision -- `S_k` is never
contaminated (L-21) and nothing is refit after seeing a miss.

### 13.0 Framing (unchanged from Rev 4)

The loop never touches a live decision inline. Everything that "learns" is
a scheduled, out-of-process batch job that writes a new frozen artefact;
the live Strategy only ever reads the CURRENT champion artefact, exactly
as `ladder_ev`'s on-disk 6-rung freeze is read today (build-then-freeze,
never build-then-mutate). A "refit" is never an edit to a registered
family's inputs; it is a new `family_id`/D0/`trial_id_prefix`, n reset to
0, exactly like `pm_us_crh_fc_v1`'s own registration.

### 13.1 What is learned

| # | Component | Data source | Cadence | Leakage rule |
|---|---|---|---|---|
| a | Forecast-conditioned density table `(station,season,hour_lst,forecast_bucket)` with the closed outcome alphabet (§7.5, R5-5) | §3.6's durable cache | Nightly batch refit as station-days SETTLE | Only rows with `available_at_ns ≤ decision time` (§3.2); only SETTLED station-days |
| b | Forecast-error calibration by station×season×lead | `ForecastPoint` rows + CLI finals | Nightly | Reuses `fit_error_model`'s `train_end_exclusive` guard verbatim; post-v5 sample-weight bucket reuses §4.3/§4.6's split fixture |
| c | Market-conditioned recalibration (reliability/isotonic vs contemporaneous ask vs settled outcome) | This family's OWN offer tape (§9 secondary endpoint) joined to CLI finals | Nightly, walk-forward | Same fit-window/holdout split shape as §4.5, rolled forward; pre-registered as a named component with its own promotion rule (§13.3), never a hand patch inserted after a loss |
| d | Execution learning: liftability/fill-rate/slippage by hour×ask-bucket×station, including the `no_bid_side` empty-bid-side RATE by hour (R5-1 extends this row) | Depth10 (`depth_adapter.py`, both `depth_levels_from_book` and the NEW `bid_levels_from_book`) + fills | Nightly | Retrospective measurement only; gated on SETTLED station-day, never scored mid-day |
| e | Window/hour policy learning | `window_start_hour_lst`/`window_end_hour_lst` (§7.7) | Nightly, same batch | Same holdout discipline as (c); gated through the SAME promotion rule (§13.3), never applied in place |

### 13.2 Nautilus null hypothesis vs BUILD (unchanged from Rev 4)

Recurring in-node timer work: REUSE PATTERN (Actor timers, fetch/backfill
only, never fitting). Historical replay for a candidate artefact: REUSE
(`ParquetDataCatalog` + `run_backtest`/`backtest`, the SAME harness §7.13
already wires). Online/incremental in-Strategy model update: **NONE
EXISTS** -- confirmed by omission, BUILD out-of-process nightly. Scheduled
batch jobs: BUILD, established pattern (`deploy/systemd/breezy-mb-daily.
timer`/`.service` shape: `OnCalendar`, `Type=oneshot`, `MemoryHigh=12G`/
`MemoryMax=16G`, `Slice=breezy-studies.slice`, `TimeoutStartSec=3600`).
Frozen-artefact + provenance pinning: BUILD, REUSE PATTERN (`archive_
table.py`'s `CORPUS_SHA256`/`STUDY_GIT_SHA`; `family_manifest.py`'s
frozen dataclass/exact-set validation/content hash/status gate). Append-
only scored-outcome record: BUILD, REUSE PATTERN (`ScoredTrial`/
`OfferTapeRecord.to_dict`/`from_dict`, explicit-field serialization,
`dataclasses.asdict` banned repo-wide). Refusal/skip bookkeeping:
`RefusalCounter.record`/`.count` REUSE-AS-IS. Nothing above is a new
Nautilus extension point.

### 13.3 Champion/challenger protocol (R5-2, R5-7, R5-8 corrections)

**Artefact registry** (new schema, mirrors `FamilyManifest`'s shape but is
a DISTINCT schema -- its exact-set key validation would reject any bolted-
on field): `artefact_id` (e.g. `pm_us_crh_fc_v1/density_table/2026-10-15T
0300Z`), `component` (enum `{density_table, error_calibration, market_
recalibration, execution_policy, window_policy}`, §13.1 a-e), `sha256`
(64-hex content hash), `git_sha`, `corpus_span` (`fit_start, fit_end,
holdout_start, holdout_end`), `fit_date`, `parent_revision` (or `None`),
`status` (`{CHAMPION, CHALLENGER, REJECTED, RETIRED}`), `promoted_at`/
`rejected_reason` (nullable), and `boundary_inputs_sha256` (R5-8, NEW
required field -- see below).

**Shadow scoring.** ≥K challengers (K INFERRED=3, small enough for the
nightly memory cap) are scored concurrently on the SAME offer-tape rows
§9's secondary endpoint already produces (own tape per `family_id`).
Challengers never see live order flow: they replay the frozen tape through
their own candidate table using the SAME side-aware `scoring.py` functions
this family's live decision uses (§7.6), against settled CLI finals for
Brier/ECE.

**Pre-declared promotion rule (ALL must hold; R5-7 corrects the estimator
and pairing, R5-8 adds the KILL-pending refusal and the boundary-artefact
gate):**
1. `Brier_challenger ≤ Brier_champion − δ_promote` on settled station-days
   AND `ECE_challenger ≤ ECE_champion` in the mid-probability bucket
   (`δ_promote` INFERRED, same disposition as §4.5's `δ`).
2. **Realized-edge comparison, PAIRED (R5-7, corrects Rev 4's unpaired
   compare):** on the SAME post-`fit_date` station-days both champion and
   challenger scored, estimator `edge_hat = Σx/Σqty`, `SE = sqrt(I)/Σqty`
   over `CombinedDraw`s (`x`, `variance` from `combine_station_day`), CI =
   `edge_hat ± z·SE`, PLUS a station-day block bootstrap. Compare CI-LOWER
   vs CI-LOWER (never challenger CI-lower vs champion POINT estimate); the
   challenger's CI-lower must exceed 0 AND not be worse than the
   champion's own CI-lower on the SAME paired days. Brier-on-all-days can
   never rescue a would-take set that dropped a disagreement day (e.g.
   09-15's, L-7 note).
3. Minimum `N_promote` station-days scored since the challenger's
   `fit_date` (INFERRED `N_promote=150`, mirrors §4.5's own gate; a
   DIFFERENT counter than the champion's PREREG `S_k`).
4. No more than one promotion per family per `M` days (INFERRED `M=30`).
5. **(R5-8, NEW) KILL-pending refusal:** promotion is REFUSED outright if
   any §9 KILL condition of the CHAMPION is tripped OR pending evaluation
   at the next scheduled LD-OBF look -- a promotion never resets a tripped
   clock, and a challenger cannot rescue a champion mid-look. Re-checked
   the following scheduled cycle; never overridden by the promotion engine
   itself.
6. **(R5-8, NEW) Boundary-artefact gate:** promotion additionally requires
   a real `boundary_inputs_sha256` -- the Var(S) boundary artefact
   generated and consistency-checked against the challenger's own corpus
   -- or `load_family_manifest`-shaped validation raises `UnpinnedBoundary
   ArtefactError` (mirrors `family_manifest.py:175-184`, carried citation,
   RE-VERIFY per §12). This is a BLOCKING promotion step, not a by-product
   computed after the fact.

Any failure → NOT PROMOTED, logged to the ledger with the specific failing
criterion named.

**Demotion/rollback (R5-8, corrects Rev 4's S13-1 finding).** A CHAMPION
that breaches Stage 2's drift/calibration monitor is never repaired in
place: it is marked `REJECTED`; the family falls back to shadow-only
(`permit=None`) on the LAST artefact that passed drift. **Any artefact
change -- INCLUDING this rollback to last-good -- MINTS A NEW REVISION**
(new `family_id`/D0/`trial_id_prefix`, `S_k`/`I_k`/`t_k` restart at 0); an
in-place swap of the decision function under a running `S_k` is FORBIDDEN
(L-34 class C) -- the only in-place action a running `S_k` ever permits is
`permit=None` halt. A fresh challenger cycle is required before anything
re-arms.

**Promotion → new revision.** A promoted challenger mints a new `family_
id` (e.g. `pm_us_crh_fc_v2`), its own `trial_id_prefix`/attempt-counter
prefix (§7.8's per-shared-key namespacing, extended to the new revision,
not a new mechanism), `d0_climate_day` = the next climate day after the
promotion decision -- never retroactive -- `status: DRAFT_NOT_REGISTERED`
until registration, `S_k`/`I_k`/`t_k` restart at 0 with its own boundary
artefact, the 15-day and structural KILL clocks restart, and the secondary
offer-tape endpoint's own `family_id` column carries the new revision id
so nightly scoring never pools two revisions.

**Stays constant across revisions:** fee model (`θ=0.06`, `ROUND_HALF_
EVEN`); executable band `0.05<price<0.95`; window (unless (e) itself was
promoted); the two operator caps, name-only, never valued.

**Operator-only: nothing new.** Promotion is 100% build-side, decided by
the pre-declared rule engine above.

### 13.4 Anti-overfitting and integrity (unchanged from Rev 4)

Walk-forward evaluation only, `train_end_exclusive`-shaped guard on every
fit function in (a)-(c). No in-node learning: the live Strategy reads the
frozen generated table module at construction time only; a `lint-imports`
rule forbids `strategy.*` from importing any nightly fit module directly.
Refit jobs memory-capped, one at a time, off-peak: new sibling systemd
unit, `MemoryHigh=12G`/`MemoryMax=16G`, `Slice=breezy-studies.slice`,
`Type=oneshot`, `TimeoutStartSec=3600`, staggered `OnCalendar` off the
existing nightly hours; `breezy-trade-supervisor.service` stays uncapped,
lightweight, never shares a Slice with the learning jobs. Every artefact
reproducible from pinned inputs (`corpus_sha256`/`study_git_sha`, same
build-script family as the registry's own fields). Learning ledger: new
append-only store, one row per challenger cycle (`artefact_id`,
`component`, metrics, promotion decision, failing criterion, `decided_by=
"rule_engine"`), `OfferTapeRecord`-shaped explicit serialization,
`dataclasses.asdict` banned. RED tests: leakage; determinism; promotion
rule (a Brier-winning, edge-CI-failing challenger is NOT promoted, ledger
names the criterion); rollback-as-new-revision (§13.3, R5-8: asserts the
rollback path MINTS a revision rather than re-arming the same `family_id`
under the same `S_k`); KILL-pending refusal (R5-8: a promotion attempt
while a §9 KILL is pending is refused, re-attempted next cycle); the
`lint-imports` rule itself.

### 13.5 Bounded reach (unchanged from Rev 4)

| Metric | Rate | Basis |
|---|---|---|
| Station-days/day/family | 4 | Structural |
| Forecast cycles/day (NBM NBS) | ~4 (00/06/12/18Z) | INFERRED from §4.1's stratification |
| Fills/day at the champion's own projected trial frequency | UNMEASURED until §4.10's output | Any sibling-family figure is INFERRED-by-analogy only |
| First-promotion horizon | best-case ≈ `N_promote / 4` calendar days if every station trades daily | INFERRED; runs in PARALLEL with the champion's own PREREG `n≥150` gate |

**What the loop cannot learn:** venue reaction to Breezy's own orders
(execution-policy learning is scored only on OBSERVED Depth10/fills);
counterfactual fills (a rung never taken has no realized outcome -- only
the archive/forecast probability exists for it, a strictly weaker signal,
L-21's discipline applied to the loop's own self-evaluation).

### 13.6 Kill/stop rules for the loop itself (unchanged from Rev 4)

A challenger that beats the champion on Brier/ECE but fails the realized-
edge CI criterion is NOT promoted -- both required. If no challenger beats
the champion in `T` days (INFERRED `T=90`), the nightly job emits ONE
ledger status line and takes no other action -- never forces a change,
lowers a threshold, or retries with relaxed criteria. Relaxing a promotion
criterion to force a result is itself an estimand change requiring the
same peer-reviewed revision process as any other family change.

### 13.7 Constraint disposition

Folded into §12's table rather than duplicated -- §12's rows 5, 9-18 each
name their §13 counterpart and how it is satisfied.

**RE-VERIFY BEFORE BUILD:** `K` (concurrent challengers), `δ_promote`,
`N_promote`, `M` (promotion cadence floor), `T` (no-improvement report
window) are all INFERRED placeholders, each set by the 0b power table
before PREREG v6 registration, none a measured or operator-set value,
none settled until a Stage-5 measurement or explicit ruling fixes it. This
section assigns no operator value anywhere and introduces no third
operator-controlled knob.
