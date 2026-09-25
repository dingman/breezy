# Plan: remove the one-trial-per-station-day construction bound (operator ruling 2026-09-14)

Status: Rev 3 — CONVERGED 2026-09-14 (round 2: security APPROVE; architect REVISE→resolved by R3-1/R3-2; prediction-market REVISE→APPROVE on the exact-variance statistic in R3-3, conditional on the validation slice). HEAD 9b9a670. Rev 1/2 text retained below; the Rev 3 dispositions at the end OVERRIDE §2's statistic, S0's hook, S4a's scope and S5's content wherever they differ.

# Plan Rev 2: remove the one-trial-per-station-day bound (ruling 2026-09-14)

**Tooling note:** `Grep`/`Glob` unavailable this session (`ENOENT ... 'rg'`); test-file lists come from codegraph blast radius, not a text scan. All three reviewers' load-bearing citations were **verified by reading**: A1 sites (`continuous_strategy.py:463-467`, `:553-581`), A2 rounding (`operator_controls.py:210-234`, `ROUND_UP`), S1 in-memory ledger (`operator_controls.py:260-265, 277-289`).

## §0 Review disposition (every item)
| Item | Disposition |
|---|---|
| A1 two missed latch call sites | **ADOPTED** — verified; both in S1 |
| A2 cent-safe floor | **ADOPTED** — `order_cost_usd` uses `ROUND_UP` (`:210-217, 234`), reviewer is right |
| A3 submit-rate is defense-in-depth | **ADOPTED** |
| A4 no WAIT queue / starvation | **ADOPTED** as named residual |
| A5 crux confirmation | **ADOPTED** (informational) |
| A6 increment split | **ADOPTED** — Increment A / B below |
| M1 coherence of weighting | **ADOPTED-WITH-CHANGE** — resolved by M2's combined draw: statistic is qty-weighted, one draw per station-day |
| M2 station-day trial unit + boundary re-validation | **ADOPTED** — **supersedes Rev 1 §2's "one filled order = one trial"** |
| M3 depth-capped sizing | **ADOPTED** |
| M4 per-rung edge pin | **ADOPTED** |
| M5 fee linearity | **ADOPTED** as evidence item, out of scope here |
| S1 ledger boot seed | **ADOPTED** — new slice S0, ships first |
| S2 permit session ceilings | **ADOPTED-WITH-CHANGE** — S0 seeds both ledger and `_PERMIT_BUDGETS`; no separate slice |
| S3 runtime-discovered slugs | **ADOPTED** as disclosed residual raising S0's priority |
| S4 shim fail-closed | **ADOPTED** (no change) |
| S5 clear_inflight ordering | **ADOPTED** — pinned in S1 RED |
| S6 redact qty from INFO line | **ADOPTED** |
| Rev 1's "defer cluster correction as a caveat" | **REJECTED-WITH-REASON** — M2: deferring under a BINDING prereg is not permitted; replaced by the station-day combined draw |
| Rev 1's `ScoredTrial` gains `qty` as the only schema change | **ADOPTED-WITH-CHANGE** — also needs a station-day aggregation layer before `StratumRow` |

## §1 L-1 null-hypothesis check — what installed Nautilus already provides
- **Per-order notional cap: NATIVE, already wired.** `RiskEngineConfig.max_notional_per_order: dict[str,int]` (`.venv/lib/python3.13/site-packages/nautilus_trader/risk/config.py:44`), keys parsed at `risk/engine.pyx:192-196`, read at `:675-679`, denial `NOTIONAL_EXCEEDS_MAX_PER_ORDER` at `:912-917`. Breezy builds it in `src/breezy/runtime/node_config.py:565-622`, installs at `:822`. Nothing to build — it becomes load-bearing the moment qty stops being 1.
- **Order-rate cap: NATIVE, currently defaulted.** `max_order_submit_rate` (`risk/config.py:42`) → `ORDER_SUBMIT_THROTTLER` with `output_drop=_deny_new_order` (`risk/engine.pyx:~140-158`). **A3: defense-in-depth only** — the account-wide intent latch already serializes to one order in flight, so the throttler can essentially never be the binding constraint. It is configured because a default is not a decision, not because it bounds anything.
- **Per-instrument exposure: NATIVE, already used.** `cache.positions_open(..., instrument.id, ..., PositionSide.LONG)` (`risk/engine.pyx:703-709`), and Breezy already calls native `self.portfolio.net_position(InstrumentId...)` at `continuous_strategy.py:495` as the AND-side of the absent-flat branch. `PositionId` per instrument follows from OmsType NETTING.
- **Residuals Nautilus does NOT cover:** (i) runtime-discovered rungs are absent from the cap map (`node_config.py:584-592`) — **S3, and the reason S0 is first**; (ii) all caps below `risk/engine.pyx:684-689` are inert until an `AccountState` is cached (pinned by `tests/contract/test_risk_engine_ordering_enforcement.py`); (iii) no native *day* dimension — `DailySpendLedger` stays (`operator_controls.py:256-258` says so explicitly).
- **Conclusion:** the latch **shrinks** to three jobs (idempotent fill→trial record, IN_FLIGHT marker, attempt counter). No new risk machinery.

## §2 Ruling artefact — `docs/evidence/RULING_multi_position_per_station_2026-09-14.md`
Amends `docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md`:
- **§13 line 210** ("construction bound is one position per station-day") → **struck**. Replaced: *the construction bound is one open position per **instrument**-day; a station-day may carry as many positions as it has current rungs, bounded only by the two operator caps.*
- **§16 line 276** (`q != 1` exclusion) → **struck**. Replaced: *qty is carried; `qty <= 0` stays a loud `malformed_input` refusal (`score_live_trials.py:364-376`); only `0 < qty < 1 lot` stays `partial_fill`. A fill smaller than requested because the book was thin is **accepted at its filled qty** (M3).*
- **§12 test 6** (line 197) → re-scoped to *duplicate fill on the same **instrument**-day*.
- **Trial unit (M2, binding):** *One trial unit is one **station-day**. The statistic operates on at most one draw per station-day; a station-day with ≥2 rung fills is combined into that one draw, qty-weighted. `I = Σ_sd q_sd·BE_sd(1−BE_sd)` and `S = Σ_sd q_sd(held_sd − BE_sd)/√I`, where for a combined station-day `q_sd = Σ qty_i`, `BE_sd` is the qty-weighted mean of the constituent `BE_i`, and `held_sd` is the qty-weighted realized hold fraction. PnL is `Σ_i ((1 if held_i else 0) − fill_px_i − fee_i)·qty_i`.* This makes looks and the SURVIVE gate **both** dollar-coherent (M1) and preserves one independent draw per station-day, so the mutual exclusivity of sibling rungs (M2) never enters the statistic.
- **Boundary artefact:** `deploy/families/gs_boundary_pm_us_crh_v2.json` (`boundary_inputs_sha256 = 471fd8a7…150e0c`, PREREG §16) is **re-validated, not silently reused** — slice S5. `I_max=40`, `n_max=160`, α=0.025, `look_step=10` are re-checked against the qty-weighted information scale before D0 continues; if `I_max` no longer bounds observed `I`, the family pauses arming rather than re-deriving a boundary mid-flight.
- **Duplicate/residual semantics:** family halt fires only on a second distinct `venue_order_id` filling an already-consumed **instrument**-day. Cross-rung fills at one station are normal operation, never residual. `compute_residual` inputs (`score_live_trials.py:449`) unchanged.
- **M4 pin:** a fill is admissible only for a rung whose **own** `p_hold_lower > break_even` was evaluated at decision time (`decision.py:298-305`); never inferred from a sibling rung.
- **M5:** `theta·C·p·(1−p)` is linear in qty so `pnl×qty` is model-exact; any venue fee component the model omits (`commissionSpreadPx`, `makerCommissionsBasisPoints`) is a reconciliation-evidence item, explicitly out of this plan.

## §3 Ordered slices

### Increment A — ships first (qty stays 1; multiple rungs per station-day)

**S0 — boot-seed the daily ledger and the permit session ceilings** *(S1 CRITICAL; must land before any multi-rung increment)*
- Files: `operator_controls.py:260-265, 277-289` (in-memory reset), `:290-300` (`spent_today_usd`), `:172-188` (`utc_day_for_ns`), `trial_day_latch.py:601-636` (`iter_fill_records`), `adapters/polymarket_us/safety.py` `_PERMIT_BUDGETS` (~`:658-722, 948-960`), `continuous_strategy.py:445-460` (the boot walk already reads the same records).
- RED: `test_a_relaunch_mid_day_does_not_re_grant_the_spent_budget`; `test_the_seed_sums_only_todays_utc_fills`; `test_a_corrupt_fill_index_fails_the_seed_closed_and_the_family_never_arms`; `test_the_seed_never_reads_an_operator_control_value`; `test_the_permit_session_ceiling_is_seeded_from_the_same_walk`.
- GREEN: one boot step summing `DurableFillRecord.cumulative_cost` for records whose `ts_event` falls in `utc_day_for_ns(now_ns)`, booked into the ledger before the strategy arms; same figure seeds the permit session budget. Fail **closed** (no arming) on an unreadable walk — the existing `_POSITION_FILL_WALK_UNREADABLE` path (`:452-457`) is the model.
- Risk: **HIGH** — a double-count would wrongly refuse the day. Idempotency is per `venue_order_id`, the same key `iter_fill_records` de-dupes on (`trial_day_latch.py:628-631`).

**S1 — re-key the latch from station-day to instrument-day** *(the bound itself)*
- Files: `trial_day_latch.py:361-378, 380-409, 411-451, 453-467, 640-683`; `continuous_strategy.py:728-735` (hunt guard), `:743-751` (inflight/attempt), `:909-923` (set_inflight/clear), **`:463-467` (`_run_never_arm_walk` per-instrument loop — A1)**, **`:553-581` (`_consume_trial_from_fill_record` — A1)**, `:1213-1215` (fill consume).
- RED: `test_two_current_rungs_at_one_station_day_both_reach_a_decision`; `test_a_second_fill_on_the_same_instrument_day_is_still_a_duplicate`; `test_the_inflight_key_is_per_instrument_day`; **`test_the_boot_walk_skips_only_the_filled_rung_not_the_whole_station_day`** (A1, site 1); **`test_the_fill_walk_consumes_per_instrument_day`** (A1, site 2); `test_a_fill_clears_the_inflight_marker_for_that_instrument_day` (S5 ordering: clear only after `consume_if_absent` returns True); `test_a_legacy_station_day_row_blocks_only_its_own_instrument`.
- GREEN: key `{prefix}{station}/{climate_day}/{instrument_id}` across trial, inflight and attempt keys; both A1 sites take the instrument; `clear_inflight` added on the `wrote` branch at `:1213-1215` (fixes the 09-13 MIA marker that stayed open because `_hunt_tick` returns at `:734` before HF-4's release).
- Read-compat shim: `is_consumed` also honours a legacy station-day row **iff** its `TrialDayRecord.instrument_id` (`:232`) matches the queried instrument — fail-closed direction (S4 confirms).
- Re-pin: `tests/unit/test_current_rung_hold_trial_day_latch.py` (`test_inflight_get_set_clear_is_keyed_station_day` → `..._instrument_day`; all `TrialDayAlreadyConsumed` cases), `test_continuous_rung_hold_strategy.py`, `test_continuous_rung_hold_fill_wiring.py`, `test_continuous_rung_hold_backtest_only.py`. **v2 (`strategy.py`, prefix `current_rung_hold/trial/`) is NOT re-keyed** — its PREREG is closed and byte-frozen.
- Risk: **HIGH** (durable-state semantics). A5 confirms re-keying is necessary *and sufficient*: `_hunt_tick` already fires per subscribed instrument and `instrument_rung_is_current` (`tick_eval.py:54-56`) can hold for adjacent rungs simultaneously; HF-4/R-9a evidence lookups are per slug, so rung B's re-arm is not refused by rung A's position.

**S3 — re-scope the duplicate-fill halt; state the submit-rate cap**
- Files: `trial_day_latch.py:471-513, 515-528`; `continuous_strategy.py:695-704, 1219-1246`; `node_config.py:615-622`.
- RED: `test_a_fill_on_a_second_rung_never_sets_the_family_halt`; `test_a_second_order_on_the_same_instrument_day_still_halts_the_family`; `test_the_submit_rate_cap_is_stated_not_defaulted` (in `tests/contract/test_native_order_cap_wiring.py`).
- GREEN: halt predicate becomes instrument-day-scoped (falls out of S1); `max_order_submit_rate` stated explicitly in `build_trade_risk_engine_config` — documented in-code as defense-in-depth per A3.

**S4a — station-day combined draw (scoring side of M2, qty=1 today, correct by construction for qty>1)**
- Files: `family_tally_v2.py:393-396` (`_stratum_row`), `:557-587` (`_assert_no_partial_or_multi_fill` call, `pooled_rows`, `total_pnl`), `settlement/current_rung_hold_v2.py:82-120` (`StratumRow`, `score`).
- RED: `test_two_rung_fills_on_one_station_day_are_one_draw`; `test_the_combined_draw_is_qty_weighted`; `test_information_is_qty_weighted`; `test_a_single_fill_station_day_is_byte_identical_to_today` (regression floor — proves the change is inert at qty=1).
- GREEN: an aggregation step mapping `ScoredTrial` rows → one `StratumRow` per `(station, climate_day)` with qty-weighted `entry_ask`/`fee`/`held`; `score()` gains a `qty` weight on `StratumRow`. `LOSS_STOP_PNL = -60` (`family_tally_v2.py:162`) stays a **dollar** stop and will be reached sooner with qty>1 — intended, stated in the ruling.
- Re-pin: `tests/unit/test_current_rung_hold_v2_score.py`, `test_current_rung_hold_v2_strata.py`, `test_current_rung_hold_v2_verdict.py`, `test_current_rung_hold_v2_truncation.py`, `test_family_tally_v2.py`.
- Risk: **HIGH** — touches the registered statistic. The qty=1 byte-identity test is the gate.

**S5 — boundary re-validation + ruling + manifest**
- Files: `deploy/families/gs_boundary_pm_us_crh_v2.json`, `scripts/analysis/crh_group_sequential_boundaries.py`, `deploy/families/pm_us_crh_cont.json:4-7`, §2's ruling file, `docs/core/LESSONS.md`.
- RED: `test_the_boundary_artefact_is_revalidated_against_the_qty_weighted_information_scale`; `test_the_family_refuses_to_arm_if_observed_I_can_exceed_I_max`.
- GREEN: re-run the boundary solver with the recorded inputs, assert `inputs_sha256` unchanged (α/spending/n_max/i_max/look_step are data-free, PREREG §16), and record the re-validation in the ruling. No boundary is re-derived mid-flight.

### Increment B — separate review gate (A6)

**S2 — depth-aware, cent-safe, log-redacted sizing** (interpretation (a))
- Files: `decision.py:290-293` (executability), `:306-312` (`quantity=config.order_quantity`), `config.py:198-201, 230, 253-256`, `continuous_strategy.py:836-852` (snapshot → decision), `:1280-1306` (`_maybe_submit`), `operator_controls.py:163-169, 220-234`.
- RED: `test_quantity_is_the_cap_divided_by_the_ask_floored_to_the_venue_lot`; **`test_the_derived_quantity_never_exceeds_the_position_cap_after_round_up`** (A2 property test over asks × caps, asserting `order_cost_usd(ask, qty) <= cap`); **`test_quantity_is_capped_by_executable_depth_at_the_limit`** (M3); `test_a_thin_book_fill_smaller_than_requested_is_accepted_not_excluded` (M3); `test_a_cap_smaller_than_one_lot_refuses_rather_than_rounds_up`; `test_quantity_is_never_assigned_a_literal_in_this_repo` (extend `tests/unit/test_operator_control_assignment_scan.py`); **`test_the_take_log_line_never_carries_a_derived_quantity`** (S6).
- GREEN: `qty = min(floor_cent_safe(cap / ask / lot) * lot, executable_size_at_limit)`, where `lot = instrument.size_increment` (venue `minimumTradeQty`, never a literal) and `executable_size_at_limit` comes from the cached Depth10 ask ladder already reachable via `strategy/depth10.py:31` `best_order`. Cent-safe floor: decrement the candidate qty while `order_cost_usd(ask, qty) > cap` (uses the ledger's own `ROUND_UP` function, so authorisation and sizing cannot disagree — the discipline `_round_cost_up_to_cent`'s docstring already states at `:213-215`). Replace `InvalidOrderQuantityError`'s `!= 1` clause (`config.py:253-256`) with positivity. **S6:** the `_maybe_submit` INFO line (`:1285-1291`) logs instrument, px and a `qty_present` token — never the derived qty, which with px would reconstruct the operator's per-position cap.
- Re-pin: `test_current_rung_hold_config.py::test_order_quantity_other_than_one_is_refused` → `test_order_quantity_is_derived_not_configured` (`test_order_quantity_zero_is_refused` stays), `tests/contract/test_current_rung_hold_wiring_contract.py`.

**S4b — carry qty through the scorer and store**
- Files: `trial_scorer.py:70-116, 119-138, 150-208` (pnl at `:187`), `score_live_trials.py:379-446` (`_admit_fill`), `:1166-1171`, `persistence/scored_trial_store.py` `SCORED_TRIAL_SCHEMA`, `runtime/paper_replay.py`, `scripts/analysis/current_rung_hold_paper_replay.py`, `whole_tape_paper_replay.py`.
- RED: `test_pnl_scales_with_qty`; `test_the_scored_trial_schema_carries_qty`; `test_held_matches_pnl_sign_under_qty_weighting`; `test_a_partial_fill_below_one_lot_is_still_excluded`; `test_a_thin_book_multi_contract_fill_is_scored_not_excluded`.
- GREEN: `pnl = ((1 if held else 0) - fill_px - fee) * qty` (fee stays per-contract, `trial_scorer.py:81-86`); `_admit_fill` drops the `qty != 1` branch, keeps `fill_below_ask` and `fee_unverified`; `_assert_no_partial_or_multi_fill` → `_assert_no_partial_fill`. `ScoredTrial.qty` is **trailing and additive**, the compat discipline of `TrialDayRecord.venue_order_id` (`trial_day_latch.py:235-242`); legacy rows read `qty=1`.

## §4 Risk envelope after the change
- **Worst-case daily exposure** = `min(the daily budget, Σ_i cost_i)` with every `cost_i ≤ the per-position cap`, enforced under one lock (`operator_controls.py:341-345` position, `:347-362` day). Formula unchanged; only the number of `i` grows. **Before S0 the real bound was 2× the daily budget across a mid-day relaunch** (`:260-265, 277-289`) — that is why S0 ships first.
- **Runaway guard replacement** (ordered by how binding each actually is): (1) **account-wide submit-intent latch** — `is_intent_open()` (`trial_day_latch.py:339-358`, checked `continuous_strategy.py:785-791`) permits one order in flight at a time across the whole account, so orders are strictly serialized however many rungs are eligible; (2) **`DailySpendLedger`** day ceiling, now restart-durable via S0; (3) **native per-order notional cap** (`risk/engine.pyx:912-917`) for declared slugs; (4) **native submit-rate throttler** — defense-in-depth (A3), effectively non-binding behind (1).
- **Fill-storm bound on one station:** with (1), at most one order is outstanding family-wide; per instrument-day at most one order is armed (IN_FLIGHT) and at most one fill is consumed, with the duplicate-fill halt still catching a second. Per station-day the bound is the number of simultaneously-current rungs (`tick_eval.py:54-56`), each ≤ per-position cap, all under the daily budget.
- **Residuals named, not closed:** **A4** — `is_intent_open()` WAIT has no queue, so whichever instrument ticks first wins and a low-quote-frequency station can be starved; that is an accepted residual, not fairness. **S3** — runtime-discovered rungs are outside the native cap and rely solely on the ledger, verified before the POST (`client.py:2912` vs `:2934`, reviewer-cited).
- **Untouched:** boot permit, NO-SEND egress firewall, `allow_short=False` (`risk.py:224`, `config.py:257-260`), account-presence halt (`trade_cli.py:414-419`), inflight-marker clear now correct (S1).

## §5 Backtest / tally parity
- `trial_scorer.score_trial` is the single pnl site (S4b touches it once); `score_trials` invariant `len(scored)+len(refused)==len(pairs)` (`:250-252`) holds.
- `family_tally_v2.build_family_tally_v2` gains the S4a station-day aggregation **before** `_stratum_row`/`build_stratum_v2`; `_ordered_for_looks` (`:414`) orders by the **earliest** fill in each combined station-day (fill-time sidecar, PREREG §16 line 270).
- `score_live_trials` state-DB reader already keys per `venue_order_id` — confirm no station-day collapse in `read_filled_trials_state_db`, since combination now happens at the tally, not the reader.
- Paper replay (`current_rung_hold_paper_replay.py`, `whole_tape_paper_replay.py`, `runtime/paper_replay.py`) constructs `FilledTrial` — add qty and re-run `test_current_rung_hold_study_replay_equivalence.py`.
- **Parity gate for the whole change:** at qty=1 with one rung per station-day, S4a+S4b must be byte-identical to today's tally output. That test is the merge condition.

## §6 Explicitly NOT changed
Nautilus (immutable; native config/extension only); `allow_short`; the two operator caps and the ban on assigning them (`operator_controls.py:119-126`); NO-SEND egress firewall and `scripts/ci/run_tests_no_egress.sh`; the boot permit and `OrderSubmissionPermit.issue` preconditions; the account-wide submit-intent latch (one order in flight); v2 and v1 (`strategy.py`, `settlement/current_rung_hold_v2.py`'s v2 semantics beyond the qty weight, `live_family_tally.py`) stay byte-frozen except S4a's weighted `score`, which carries a qty=1 identity test; the frozen archive table / `CORPUS_SHA256` pin; α, `n_max`, `i_max`, `look_step` and `boundary_inputs_sha256` (re-validated, never re-derived); `fill_below_ask` and `fee_unverified` exclusions; R-9a re-arm freshness (180 s/60 s); Nautilus `position_check_interval_secs` (stays off).

## §7 Operator-only questions (budget-shaped only)
1. With qty derived from the per-position cap, one order can spend the whole per-position cap instead of ~$0.30. **Is the current per-position value still the intended per-order spend**, or should it be lowered before the first Increment-B order? (Value stays operator-only; never read or restated by us.)
2. The daily budget is now reachable in a single afternoon across 4 stations × N rungs. **Confirm the daily budget value is the intended daily exposure ceiling** under multi-position operation.

Everything else — instrument-day uniqueness, station-day trial unit, qty-weighted statistic, sizing formula, submit-rate value, log redaction, slice order — is a build-side engineering call decided here.

CODEGRAPH_USED: 9 calls

## Rev 3 dispositions (2026-09-14, override the sections above where they differ)

**R3-1 (architect BLOCK, adopted) — S0 hook.** The seed lives in `PolymarketUSExecutionClient._connect()` (`exec/client.py:1122-1213`), immediately after `self._reconcile_submit_intent()` (`:1206`) and before `_refresh_startup_position_evidence()` (`:1213`). Same package as `DailySpendLedger` and `safety._PERMIT_BUDGETS`, `self._ledger` already in scope (`:1012`), fill-index reads via the mechanism `iter_fill_records` uses. No strategy→adapters injection; importlinter contracts unchanged. Client-connect-before-strategy-on_start is an existing invariant (the never-arm walk already depends on it). Security note carried: the fail-closed RED test must exercise a PER-INSTRUMENT corrupt fill index (`_read_fill_index` returning None for one instrument), not only a wholesale walk exception. Resolver-path and create-path writes share the `{FILL_KEY_PREFIX}{venue_order_id}` key (cumulative overwrite), so the seed cannot double-count; `cumulative_cost` is real dollars even when `feeReconciled` is false — the conservative direction.

**R3-2 (architect, adopted) — S4a scope in Increment A is qty≡1.** `ScoredTrial` gains `qty` only in S4b (Increment B). S4a's combined draw is implemented as a function of a qty parameter fixed at 1 (never a literal average), so S4b is additive. Merge gate = the single-fill byte-identity test AND the two-rung-same-station-day-at-qty=1 test.

**R3-3 (prediction-market BLOCK→APPROVE, adopted) — the registered statistic under multi-rung station-days.** §2's borrowed-Bernoulli combined draw is STRUCK. Model: for station-day sd with taken rungs i=1..k, `held_i` are mutually exclusive (rungs are non-overlapping by `RungBounds`/`_rung_index` construction); under H0 `P(held_i=1)=BE_i` and `Cov(held_i,held_j) = −BE_i·BE_j` (i≠j). Statistic:
`X_sd = Σ_i qty_i·(held_i − BE_i)`;
`Var_H0(X_sd) = Σ_i qty_i²·BE_i(1−BE_i) − 2·Σ_{i<j} qty_i·qty_j·BE_i·BE_j`;
`I = Σ_sd Var_H0(X_sd)`; `S = Σ_sd X_sd / √I`; `Var_H0(S) = 1` exactly (station-days independent). Reductions: k=1, qty=1 → byte-identical to `current_rung_hold_v2.score`; k=1, qty>1 → `qty²·BE(1−BE)`, matching PnL's dollar-variance scaling. **Admission gate, enforced at draw construction, never post-hoc:** `Σ_i BE_i ≤ 1` for the station-day, else the whole station-day is refused as `malformed_input` before I/S are touched.
**S5 is replaced by the validation slice:** (i) closed-form unit tests of the reductions; (ii) [SUPERSEDED by Amendment C below, 2026-09-24 — AUD-06a] a seeded Monte-Carlo under H0 with k∈{1,2,3} mutually exclusive rungs and mixed qty asserting sample Var(S) within tolerance of 1 AND the LD-OBF boundary's realised one-sided crossing rate ≤ α at n_max=160 (load-bearing: the boundary is asymptotically valid, finite-sample accrual shape changes with multi-rung days); (iii) `inputs_sha256` unchanged + the static I_max bound check. Re-validation suffices; a re-solve is required only if (ii) fails. Increment A ships only after (i)-(iii) are green.

## Amendment C (2026-09-24, AUD-06a) — item (ii) replaced: qty-envelope sweep, not a single re-run

**Source:** `docs/plans/backlog/AUDIT_2026-09-21/AUD-06a-r11-boundary-revalidation.md` (peer-reviewed to
100/100, READY). Clears R-11 (`PROGRESS.md`): item (ii)'s single mixed-qty point estimate measured a
~0.059 one-sided crossing rate against α=0.025 at k∈{1,2,3}, mixed qty∈{1,2,3}
(`tests/unit/test_multi_position_validation_2026_09_14.py:161-199`, strict `xfail`). This amendment
replaces item (ii) with a qty-envelope sweep so re-validation is a function of the qty distribution,
never a single unnamed point (the real Increment-B qty is `floor(cap/ask/lot)*lot`, a function of the
operator-reserved per-position cap this repo may never read — §5 there).

**New item (ii):** sweep the qty distribution over a dimensionless grid — never the cap itself — and
report, per cell, the realised one-sided crossing rate, its Clopper-Pearson upper bound, and the
realised information-accrual trajectory `t_k = I(n_k)/I_max` against the artefact's ASSUMED schedule
`t_k = n_k/n_max` (the mechanism the strict `xfail` already records: higher qty inflates a
station-day's variance, so `I` saturates faster than the artefact's schedule assumes, and the
realised-`t` boundary interpolation undershoots). Increment B's merge gate becomes "the sizing formula
provably cannot emit a qty outside the validated envelope, and the envelope is not stale" — not "the
boundary was re-validated once".

**Formulas reused verbatim** (unchanged from R3-3 above, generalised to mixed sides by
`docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §3): `X_sd = Σ_i qty_i·(held_i − BE_i)`;
`Var_H0(X_sd) = Σ_i qty_i²·q_i(1−q_i) − 2·Σ_{i<j} qty_i·qty_j·s_i·s_j·q_i·q_j` (`s_i=+1` YES, `s_i=-1`
NO, `q_i=BE_i` YES / `1-BE_i` NO); `I = Σ_sd Var_H0(X_sd)`; `S = Σ_sd X_sd/√I`. The station-day
admission gate `Σ_i q_i ≤ 1` is enforced at draw construction (rejection sampling), never post-hoc.
Implemented in `src/breezy/settlement/current_rung_hold_v2.py` (`StratumRow`, `combine_station_day`,
`score_combined`) — imported, never reimplemented, by
`scripts/analysis/aud06a_qty_envelope_sweep.py`.

**Sweep axes (dimensionless, seeded):** `q_max ∈ {1,2,3,4,5}`; qty dispersion — `all-equal` (every leg
at `qty=q_max`), `two-point` (half legs at `qty=1`, half at `qty=q_max`), `cap-shaped`
(`qty_i = clip(floor(R/ask_i), 1, q_max)`, `R ∈ {2,3,5,8,13,21}`, a dimensionless budget-to-ask ratio,
never a cap value); rungs per station-day `k ∈ {1,2,3}`; leg side composition
`side_mix ∈ {all-YES, all-NO, mixed}` (`mixed` undefined and SKIPPED at `k=1`). `ask_i`/`BE_i` are
drawn from the **observed live/tape ask distribution** — the 9 durable PM.us fills' posted price,
`docs/evidence/AUD13A_RECONCILIATION_EVIDENCE_2026-09-24.md` §1 (the same read-only source that
already confirms every real fill today is `qty=1` — no empirical qty>1 data exists, `config.py:255`).
Total grid: `5 q_max × 8 dispersion sub-cells × 8 admissible (k, side_mix) pairs = 320 cells`
(`(k=1, mixed)` excluded as inadmissible, not silently sampled as all-YES), at the REGISTERED 20000
replications/cell (`docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §6).

**Methodology, pinned:** 20000 reps/cell (registered figure, comparable to the qty≡1 mixed-side
study); Clopper-Pearson exact one-sided 95% upper bound (never normal-approximation, which
under-covers exactly where the safety decision is made); seeds `20260914` for reproduction cells,
`20260921_000 + cell_index` (disjoint) for the sweep; `Var(S) ∈ [0.95,1.05]` per look at 20000 reps.

**Mechanism verdict, machine-checkable, not eyeballed:** CONFIRMED requires (1) ≥24 contributing
cells, (2) Spearman `ρ ≥ 0.70` between `max_k|Δt_k|` and the realised crossing rate with a one-sided
permutation `p < 0.01` (10000 permutations), and (3) the qty≡1 control cell shows `max_k|Δt_k| ≤ 0.01`
and CP-upper ≤ 0.025. REFUTED if any cell with `max_k|Δt_k| ≤ 0.01` has a crossing-rate CP-lower bound
above the control's CP-upper bound. Anything else is INDETERMINATE. `ρ ≥ 0.70` / `p < 0.01` are
REASONED BUILD-SIDE DEFAULTS fixed before the sweep ran, NOT inherited from a registered study —
unlike the 20000 reps, the CP construction and the `Var(S)` tolerance, which ARE anchored to the
registered qty≡1 study.

**Output:** the largest `q_max` per `side_mix` whose every swept cell has CP-upper ≤ α=0.025,
published as `Q_MAX_VALIDATED` plus the artefact's `boundary_inputs_sha256` (unchanged) — `q_max=1`
(no qty above 1 validates) is an explicitly legitimate result. **Staleness trigger:** the artefact
records the `BE`-prior's sampled support (`min`/`p25`/`median`/`p75`/`max`/IQR); the envelope is STALE
— and `Q_MAX_VALIDATED` must not be relied on — when the live 14-day trailing median ask falls outside
the recorded `[p25,p75]`, or the live IQR drifts by more than +50%/−33% from the recorded IQR. The
check is fail-closed at the consumer (AUD-06b sizing refuses, never warns) and is evaluated at the
consumer's gate, never on a timer.

**Result, this run** (`docs/evidence/RULING_r11_qty_envelope_2026-09-25.md`, authoritative table):
**compute-budget-bounded — 33 of 320 cells run** (calibration `τ_cell=59.50s`, projected full-grid
5.29 wall-hours, over this session's 2-hour compute allowance; resumable via `--cells FROM:TO` against
the committed `docs/evidence/aud06a_sweep_cells.jsonl`). Mechanism verdict: **INDETERMINATE** — the
monotonicity condition is strongly satisfied (Spearman `ρ=0.8331`, permutation `p=0.0001` over 29
contributing cells) but the qty≡1 control anchor fails (`max_k|Δt_k|=0.365 > 0.01`) for a reason
unrelated to qty: the observed, realistically-cheap ask distribution (`median=0.22`) makes even the
`qty=1` control's per-draw variance depart substantially from the artefact's assumed 0.25-per-draw
schedule. **No envelope is published** (Amendment C: envelope publication is gated on a CONFIRMED
verdict); the raw partial table shows every run `q_max≥2` cell over `α=0.025` and every run `q_max=1`
cell (bar the structurally-infeasible `all_no,k=3`) under it, but that is reported as information, not
a ruling. **No re-solve of the boundary artefact** — R-11's remedy-B fallback triggers only on an
empty CONFIRMED-mechanism envelope, which did not occur; `boundary_inputs_sha256` is unchanged
(asserted by `test_the_boundary_inputs_sha256_is_unchanged`). The strict `xfail`
(`test_under_h0_the_ld_obf_boundary_crossing_rate_is_at_most_alpha`) is unchanged and stays strict, its
reason extended with a citation to this evidence.

**Increment A (final):** S0 (R3-1) → S1 (+A1 sites, inflight clear) → S3 → S4a (R3-2, R3-3 formula at qty≡1) → validation slice (i)-(iii) → ruling artefact + LESSONS entry. **Increment B:** S2 (depth-capped, cent-safe, log-redacted sizing) → S4b (qty through scorer/store) → re-run (ii) with qty>1.
