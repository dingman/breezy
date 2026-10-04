# FQ loss response plan r1 (planner draft, 2026-10-04; under peer review)

Operator directive 2026-10-04: continually optimize toward identifying and executing winning trades. Diagnosis: see the coordinator synthesis and the scratchpad `loss-triage/`.

# Implementation plan: FQ loss response (W1 measure, W2 repair, W3 winner search)

## Overview
FQ (`pm_us_crh_fq_v1`) is losing, and nothing in the system can see the losses or stop them. Settled n=11, ROI −39%, and model Brier is worse than market Brier on its own picks. The plan runs in three stages:
- **W1** builds an honest scorecard and the missing settlement and telemetry feeds.
- **W2** repairs FQ behind a pre-registered resume bar, a stopping boundary and an automatic halt that only ever sets.
- **W3** adds a reject-only search loop so the system keeps looking for strategies that win.

Every slice can be merged on its own. FQ stays HALTED until the W2 resume bar passes.

## Ground truth checked in the graph (premises the briefs must carry)
- **Settlement truth has no timer.** `deploy/systemd/` holds 18 timers and none of them runs `scripts/analysis/settlement_truth_dataset.py`. That explains why truth stops at 09-28. It is a missing feed, not a defect in the parser.
- **portfolio_roi drops FQ silently.** `scripts/analysis/portfolio_roi_report.py:3615-3665` skips families on DRAFT or on a scan exception and only logs it. `deploy/families/pm_us_crh_fq_v1.json` is `REGISTERED`, so the skip must come from the scan-exception path. The likely cause is `not_applicable_boundary.json` meeting a reader that requires a boundary. The first step proves this cause before anything is fixed (L-32).
- **FQ never registers positions with the monitor.** `PositionMonitor` (`src/breezy/strategy/current_rung_hold/position_monitor.py:201`) registers positions only through `on_position_opened` and `_on_depth`. Its builders all sit in CRH composition, and `src/breezy/strategy/forecast_quantile_ladder/composition.py` has no monitor wiring. That accounts for "1 of 20".
- **A NO-side code path already exists in FQ.** `decision.evaluate(side=...)`, `ev_net_no`, `OPPOSITE_SIDE_LATCHED`, and `strategy.py:390` (which latches `"no"`) are all present. "No NO-side evaluation" is therefore a wiring or subscription gap, not a missing feature. Per L-11, it must be confirmed with the FQ decision-funnel counts by side before anything is built.
- **Pieces that already exist and get reused:**
  - `src/breezy/analysis/hypothesis_ledger.py` and `scripts/analysis/hypothesis_register.py` (PROGRAMME_ALPHA / MAX_HYPOTHESES / K_variants α-split).
  - `src/breezy/runtime/backtest_harness.py`.
  - `src/breezy/persistence/gs_boundary_artefact.py` and `scripts/analysis/crh_group_sequential_boundaries.py` (LD-OBF).
  - `src/breezy/settlement/trial_scorer.py`.
  - `src/breezy/settlement/roi_bound.py`.
  - The `set_family_halted` / `TrialDayLatch.record_policy_halt` / `set_family_halt_cli.py` halt path.
  - `scripts/analysis/nbp_market_comparison.py`, which already has a look-ahead assert and the leg-side model probability.
- **Prior evidence that bears on W2's chances.** Memory "Forecast edge CLOSED on PM.us rungs (09-20)" found the market's resolution is 1.98× the forecast's, and recalibration could not help. The plan therefore treats the W2 resume bar as likely to fail and does not let W2 block W3.

## Binding lessons applied
| Lesson | Where it bites |
|---|---|
| L-1 / L-11 | Native-first. The NO side and the halt mechanism already exist, so reuse them. |
| L-21 | The comparator is the market ask, never climatology. |
| L-38 | The FQ tally SKIP is a missing stop. The fix is a counter that can actually increment. |
| L-40 | The trial unit is the station-day, with the exact variance for mutually exclusive rungs. |
| L-41 | The screening null must reproduce H0 exactly, because quote noise plus selection manufactures edge. |
| L-42 / L-55 | Store-reading tests write through the real writer and run the production default once. |
| L-43 | Run the full gate after every merge. |
| L-12 | Widen exact-set barriers, never relax them (this includes the exec import pin). |
| Memory | `scripts/ci/run_tests_no_egress.sh`, `lint-imports` from the tree root, and an explicit interpreter path (never `uv sync`). |

## Definition of "winning" (precise, pre-registered, used by W2 and W3)
A strategy variant *h* is **winning** when all three conditions hold on its capped live trial.
1. **P&L (primary, sequential).**
   - Let X_sd be net realised P&L per independent station-day: the sum over all of the variant's fills on that station-day, after the venue fee θ·p·(1−p), with the cent rounding and the actual fill price.
   - H0: E[X_sd] ≤ 0. H1: E[X_sd] ≥ δ_h, the MDE pre-registered for *h*.
   - The test is a one-sided Lan-DeMets O'Brien-Fleming group-sequential test on the standardised mean. The variance is the exact mutual-exclusivity variance per L-40, so stacked rungs are one trial, not several.
   - Looks happen every k station-days, with α_h = PROGRAMME_ALPHA / MAX_HYPOTHESES / K_h (the existing `hypothesis_register` split).
   - **WIN** means the upper boundary is crossed. **KILL** means the futility (lower) boundary is crossed, or the P&L floor in W2-4 is hit.
2. **Skill (co-primary, non-sequential at the final look).** On the same decisions, BSS = 1 − Brier_model / Brier_ask, and its station-day block-bootstrap 95% lower bound must be > 0.
3. **Calibration (guard).** The reliability slope's 95% CI contains 1, and the Spiegelhalter Z test is not rejected at 0.05. A guard failure blocks promotion even when (1) crosses.

Shadow and backtest results never count toward (1); this is PREREG v2's ruling, carried forward. They can only reject.

---

## W1: Measure honestly (first; everything else reads its outputs)

### Acceptance criteria
- `settlement_truth.csv` covers 09-29 → D-1, refreshed daily by a timer. The scorecard shows the coverage gap explicitly, never as a silent zero.
- A daily `fq_scorecard` artefact covers every FQ Take, Refuse and NotExecutable decision, traded or shadow, with a settled truth label. It reports:
  - Brier_model vs Brier_ask, as a paired difference with a block-bootstrap CI;
  - a reliability table over p_hat bins [0,.05,.1,.2,.3,.5,.7,1];
  - P&L per independent station-day;
  - fees;
  - n per stratum (side, station, rung position).
- `portfolio_roi` includes FQ. A golden test fails if any REGISTERED family is skipped without that skip appearing in the report's own skipped field.
- The position monitor registers 100% of FQ positions from the exec store at boot and on every fill. Test: 20 positions written through the real writer yield 20 registered.
- Every FQ decision log line carries `q10,q50,q90,model_version,vector_issued_ts_ns,obs_ts_ns,decision_ts_ns`.
- LAX finding: a written verdict, either LEAK, INPUT_DEFECT (with the exact field) or GENUINE, with evidence. If it is a defect, a RED test reproduces it.

### Files
| # | File | New/Exists | Change |
|---|---|---|---|
| 1a | `deploy/systemd/breezy-settlement-truth-refresh.{service,timer}` | NEW | Runs `settlement_truth_dataset.py` daily after the NWS CLI release. Sets `RuntimeMaxSec`, a memory cap and an alert on failure through `alerts.env`. |
| 1b | `scripts/analysis/settlement_truth_dataset.py` | EXISTS | Add an incremental `--since` mode, append-only and idempotent. Single writer (L-50). |
| 1c | `src/breezy/analysis/fq_scorecard.py` | NEW | Pure core: join decisions × truth × fills; Brier, reliability, station-day P&L, fees. No I/O. Designed to be imported by AUT-4 so the logic is not duplicated. |
| 1d | `scripts/analysis/fq_scorecard_daily.py` | NEW | I/O shell that reads the decision JSONL, the exec state DB and truth, and writes `derived/fq-scorecard/YYYY-MM-DD.{json,md}`. |
| 1e | `deploy/systemd/breezy-fq-scorecard.{service,timer}` | NEW | Runs after 1a. |
| 1f | `scripts/analysis/portfolio_roi_report.py` | EXISTS | Fix the cause found in step 0. Accept `not_applicable_boundary` for P&L-only families, and surface every skip in the schema (`skipped_families`). |
| 1g | `src/breezy/strategy/forecast_quantile_ladder/composition.py` | EXISTS | Wire `PositionMonitor` through the existing `install_position_monitor` seam. |
| 1h | `src/breezy/strategy/current_rung_hold/position_monitor.py` | EXISTS | Add a `seed_from_exec_store(positions)` registration path, called at `on_start` from `Cache.positions_open()`. This is native Nautilus; a parallel store is not allowed. |
| 1i | `src/breezy/strategy/forecast_quantile_ladder/decision.py` (`decision_log_fields`) + `strategy.py` (`_shadow_log_line`) | EXISTS | Add the forecast-vector fields as additive keys. Update the `_EXECUTION_DRIFT_ALLOWED_KEYS` analogue if the decision-log schema is pinned. |
| 1j | `scripts/analysis/fq_lax_input_audit.py` | NEW, read-only | For the LAX 10-05 take, assert `vector_issued_ts < take.ts` and `obs.ts < take.ts`. Check the vector's `climate_day`, the station mapping, and the rung bound direction (does "<97" map to the lower tail?). |

### Tests
- `test_settlement_truth_since_mode_is_idempotent`
- `test_settlement_truth_refuses_overlap_rewrite`
- `test_scorecard_brier_pair_matches_hand_fixture`
- `test_scorecard_reliability_bins_cover_all_decisions`
- `test_scorecard_station_day_pnl_nets_stacked_rungs` (L-40)
- `test_scorecard_reports_truth_coverage_gap_not_zero`
- `test_scorecard_excludes_decisions_with_vector_ts_after_decision_ts` (look-ahead guard)
- `test_portfolio_roi_includes_registered_fq_family`
- `test_portfolio_roi_surfaces_every_skipped_family`
- `test_fq_monitor_registers_all_exec_store_positions_at_boot` (fixture written through the real exec writer, per L-42)
- `test_fq_monitor_production_default_seeds_from_cache` (L-55)
- `test_decision_log_fields_carry_forecast_vector_on_take_and_refuse`
- `test_fq_rung_lower_tail_probability_matches_cdf` (the RED candidate for LAX)

### Order and parallel groups (disjoint files)
- **Step 0** (read-only, parallel): run 1j (LAX audit) and the portfolio_roi skip root-cause read. Both go to Codex or Grok, read-only.
- **G1-A** {1a, 1b}
- **G1-B** {1c, 1d, 1e}
- **G1-C** {1f}
- **G1-D** {1g, 1h}
- **G1-E** {1i}

G1-B depends on G1-A's data, but not on its code. Build it against fixtures, run it once A is live.

The smallest first is **1a**, the timer. The data unblocks everything else.

### Live path and restarts
- 1g, 1h and 1i load in the trade node. They are **live-path**: merge outside 16:30–17:10Z, then respawn the node. FQ is halted, so a respawn is low-risk.
- None of them touches the supervisor, so **no supervisor restart**.
- 1a–1f are timer jobs only.

### Trade-offs
- **Scorecard as a new core module vs. waiting for AUT-4.** Chosen: the new pure module, which AUT-4 then imports. Waiting leaves a −39% family unmeasured for weeks. A pure module avoids building a duplicate evaluator.
- **Monitor fed from the exec store vs. event-only.** The event-only path is exactly what missed 19 of 20. `Cache.positions_open()` is the native source of truth.
- **Brier over all decisions vs. only Takes.** Chosen: both, stratified. Take-only Brier measures winner's-curse selection. All-decision Brier measures model skill. Both numbers are needed to tell the two apart.

---

## W2: Repair FQ before any resume

### Acceptance criteria
- **`PREREG_FQ_v1` (R-B)** is filed and frozen at a commit SHA. It pins:
  - the variant set K;
  - α_h;
  - δ_h;
  - the LD-OBF boundary artefact (a real `gs_boundary` file, replacing `not_applicable`);
  - the P&L floor rule;
  - the calibration-failure rule;
  - N_shadow, the number of station-days for the resume bar. It comes from a power calculation for a BSS MDE of 0.05 at 80% power, with a provisional floor of ≥100 independent station-days.
- **Automatic halt job.** It calls only `set_family_halted`; no clear path is reachable, which a test proves by import-graph analysis. It fires when either rule holds:
  - (a) the cumulative station-day P&L lower bound crosses the pre-registered floor;
  - (b) the calibration guard fails on ≥ the pre-registered n.
- **Probability includes forecast-error variance.** On the out-of-sample holdout, PIT coverage of the 80% interval lies in [0.75, 0.85], and the `p_lower` coverage test passes. These are the G2.0–G2.3 gates, re-run.
- **Market-disagreement ceiling.** A Take is refused with `disagreement_ceiling` when (p_hat − ask) exceeds the pre-registered ceiling. The ceiling is an execution-cost filter only. The ask never enters p_hat.
- **One position per station-day** (default), or netting. A second Take on a station-day is refused with `station_day_occupied`. This is chosen over netting; see the trade-offs.
- **NO side.** The decision funnel shows NO-side evaluations per station at a rate within 10% of the YES rate in shadow mode. NO buys are BUYs of the NO instrument, and `allow_short` stays False.
- **Resume bar.** Over N_shadow independent station-days, a frozen model (SHA pinned) gets a BSS-vs-ask block-bootstrap lower bound > 0 on shadow decisions, from the W1 scorecard. The resume is a capped live trial under the R-B boundary only. Enablement goes through the existing permit and halt-clear procedure, and the caps are untouched.

### Files
| # | File | New/Exists | Change |
|---|---|---|---|
| 2a | `docs/specs/PREREG_FQ_v1_2026-10-XX.md` | NEW | The R-B document. Variants, α split, δ, N_shadow power calculation, floor rule, calibration rule, definition of winning. |
| 2b | `deploy/families/artefacts/gs_boundary_pm_us_crh_fq_v1.json` + `deploy/families/pm_us_crh_fq_v1.json` | NEW + EXISTS | Generated by `crh_group_sequential_boundaries.py`, then the sha is pinned in the manifest. |
| 2c | `scripts/analysis/crh_group_sequential_boundaries.py`, `src/breezy/persistence/gs_boundary_artefact.py` | EXISTS | Parametrise the statistic from Wilson win-rate to the station-day mean P&L with L-40 variance. Additive mode; the CRH mode stays byte-identical. |
| 2d | `scripts/analysis/family_tally_v2.py`, `scripts/analysis/score_live_trials.py` | EXISTS | Remove the FQ SKIP by routing FQ through the new boundary (L-38). |
| 2e | `src/breezy/analysis/fq_auto_halt.py` | NEW | Pure rule: scorecard plus tally go in, `HALT(reason)` or `NO_ACTION` comes out. |
| 2f | `scripts/analysis/fq_auto_halt_job.py` + `deploy/systemd/breezy-fq-auto-halt.{service,timer}` | NEW | Calls the existing `set_family_halt_cli` entry. Never imports `clear_family_halt_cli`. Alerts through `alerts.env`. |
| 2g | `src/breezy/analysis/nbp_calibration.py` | EXISTS | Build a predictive distribution with forecast-error variance: inflate the EMOS spread with the out-of-sample residual variance per lead and station. Then derive `p_lower` from a station-day block bootstrap over holdout residuals plus parameter draws. Emits a new artefact version. |
| 2h | `src/breezy/strategy/forecast_quantile_ladder/artefact_bounds.py` / `bounds.py` | EXISTS | Consume the new draw set. The `BoundsProvider` signature is unchanged. |
| 2i | `src/breezy/strategy/ladder_ev/config.py` (margin, lines 153-162) + `forecast_quantile_ladder/decision.py` | EXISTS | Add a `disagreement_ceiling` config and refusal. Add `STATION_DAY_OCCUPIED` and its refusal, inserted after the existing scoring refusals, as the check-order docstring requires. |
| 2j | `src/breezy/strategy/forecast_quantile_ladder/latch.py` / `persistent_latch.py` | EXISTS | Add a station-day key (the existing latch is per station, day and rung). |
| 2k | `src/breezy/strategy/forecast_quantile_ladder/strategy.py` / `composition.py` | EXISTS | NO-side subscription and evaluation fix. Scope is set by the step-0 funnel count. |

### Tests
- `test_prereg_fq_v1_boundary_artefact_sha_matches_manifest`
- `test_gs_boundary_station_day_pnl_mode_reproduces_h0_size_by_simulation` (L-41: the null includes quote noise plus selection)
- `test_crh_boundary_mode_byte_identical`
- `test_family_tally_v2_scores_fq` and `test_score_live_trials_fq_not_skipped`
- `test_fq_auto_halt_sets_on_pnl_floor`
- `test_fq_auto_halt_sets_on_calibration_failure`
- `test_fq_auto_halt_never_imports_clear_path`
- `test_fq_auto_halt_unknown_input_alerts_not_halts`, which mirrors the fee-drift UNKNOWN rule
- `test_predictive_pit_coverage_on_holdout`
- `test_p_lower_includes_forecast_error_variance` (p_lower must widen against a parameter-only fixture)
- `test_disagreement_ceiling_refuses_and_is_never_latched`
- `test_ask_never_enters_p_hat` (a property test: p_hat is invariant to ask)
- `test_second_take_same_station_day_refused_station_day_occupied`
- `test_evaluate_check_order_*`, the existing pin, extended
- `test_no_side_evaluated_for_every_subscribed_rung`
- `test_no_take_is_buy_of_no_instrument_allow_short_false`
- Firewall guards and the exec import pin, run in every focused gate

### Order and parallel groups
- **G2-A** {2a, 2b, 2c, 2d}. This is the stats and stop path, and the smallest first item is the **2a document**. It needs W1-1a truth and W1-1c for P&L.
- **G2-B** {2e, 2f}. It depends on W1-1c's scorecard schema and the 2a rules. It can be built with the floor rule alone before 2b exists.
- **G2-C** {2g, 2h}. Offline re-calibration plus a G2.0–G2.3 re-validation, run as a capped systemd job (`RuntimeMaxSec`, memory cap, stall watch).
- **G2-D** {2i, 2j}. Decision rules. It conflicts with G2-E on `strategy.py`, so G2-D owns decision.py, latch.py and config.py, and G2-E owns strategy.py and composition.py.
- **G2-E** {2k}.

G2-A ∥ G2-C ∥ G2-D ∥ G2-E. G2-B runs after G2-A's rules are frozen.

### Live path and restarts
- 2h, 2i, 2j and 2k are **live-path**: merge outside 16:30–17:10Z, then respawn the node.
- 2f is a timer only.
- 2b is a manifest change. If the supervisor reads manifests once at load, **2b needs a supervisor restart** in the 01:00–16:40Z window. Verify this in `trade_supervisor_core.py`.
- No other item touches the supervisor.

### Trade-offs
- **Forecast-error variance:**
  - (i) Inflate the spread with held-out residual variance. **Chosen.** It is simple, auditable, and US weather data only.
  - (ii) Isotonic recalibration. Rejected: it needs more n than exists, and the 09-20 finding says recalibration did not help.
  - (iii) Shrink toward the market. **Rejected:** it uses the venue price as a predictor, which violates "venues for cost only".
- **Ceiling vs. a larger margin.** A larger margin still selects for the largest disagreements. A ceiling cuts directly at the winner's-curse tail where the model loses (mean p_hat .287 vs ask .142).
- **One per station-day vs. netting.** Netting needs a joint-outcome P&L model and new sizing logic. One per station-day is a key change in an existing latch and matches the L-40 trial unit. Netting is deferred under YAGNI.
- **A new boundary statistic vs. reusing Wilson win-rate.** FQ asks range widely, so a win rate is not a sufficient statistic for P&L. Mean station-day P&L is.

---

## W3: Winner search loop (AUT-S)

### Acceptance criteria
- **Hypothesis register.** Every candidate is registered before it is screened, with a frozen SHA, K, α_h, δ_h and N. Reused from `hypothesis_ledger` / `hypothesis_register`.
- **Candidate generator.** It emits variants from a declared grammar:
  - family: FQ, CRH v4, NO-side and others;
  - side;
  - ceiling and margin;
  - lead and hour window;
  - station subset.

  It has a hard cap on K per cycle, and each variant consumes α.
- **Screen 1, native `BacktestNode`/`BacktestEngine`.** It replays the captured `ParquetDataCatalog` with Nautilus's native `FillModel` and fee model, plus a `PortfolioAnalyzer.register_statistic` for station-day P&L and BSS.
  - It is **reject-only**: a PASS only advances the candidate, and its numbers never reach a verdict.
  - It asserts `ref.ts < take.ts`, with windows scoped by date and hour.
  - It only accepts replay-sufficient tape days (the "quote tape is not replay-sufficient" memory).
- **Screen 2, shadow-in-node.** The variant runs in shadow mode in the node for N_shadow station-days. The W1 scorecard must show a BSS lower bound > 0 and pass the calibration guard.
- **Promotion** happens only through a capped live trial under that variant's LD-OBF boundary (the definition of winning above). KILL and demotion are automatic through AUT-5a and the W2 halt job.
- **Autonomy queue re-sequenced:**
  1. R-B `PREREG_FQ_v1` (W2-A)
  2. AUT-2 P&L labels
  3. AUT-5a demotion stop
  4. AUT-1 remainder
  5. AUT-4
  6. AUT-S
  7. AUT-3

  The AUT-3 gate changes to "AUT-S screen PASS".

### Files
| # | File | New/Exists | Change |
|---|---|---|---|
| 3a | `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-S-winner-search_plan_r1.md` | NEW | Plan doc (input for the peer review). |
| 3b | `docs/core/PROGRESS.md` (AUTONOMY QUEUE), `AUT-3-retraining_plan_r6.md` successor `r7`, `README.md` | EXISTS / NEW r7 | Re-sequence the queue and change the gate. |
| 3c | `src/breezy/analysis/hypothesis_ledger.py`, `scripts/analysis/hypothesis_register.py` | EXISTS | Add a variant-grammar registration and per-cycle α accounting. |
| 3d | `src/breezy/analysis/candidate_generator.py` | NEW | Pure function: grammar → frozen variant specs, capped at K. |
| 3e | `src/breezy/runtime/backtest_harness.py` | EXISTS | Run each variant through `BacktestNode` and register the station-day P&L and BSS statistics. Reject-only output schema. |
| 3f | `src/breezy/analysis/screen_statistics.py` | NEW | `PortfolioStatistic` subclasses: the native extension point, not a parallel analyser. |
| 3g | `scripts/analysis/aut_s_screen.py` + `deploy/systemd/breezy-aut-s-screen.{service,timer}` | NEW | Nightly, capped, one heavy job at a time, with a stall watch. |
| 3h | `src/breezy/strategy/forecast_quantile_ladder/plugin.py` / `composition.py` | EXISTS | Shadow-variant instantiation keyed by the variant spec. Shadow lines are tagged so they can never feed a live verdict. |

### Tests
- `test_unregistered_variant_cannot_be_screened`
- `test_alpha_spent_per_variant_sums_to_programme_alpha`
- `test_candidate_generator_respects_k_cap_and_is_deterministic`
- `test_backtest_screen_is_reject_only_schema` (no "WIN" token reachable)
- `test_backtest_screen_rejects_lookahead_vector`
- `test_backtest_screen_refuses_non_replay_sufficient_day`
- `test_screen_null_reproduces_h0_size` (L-41)
- `test_register_statistic_station_day_pnl_matches_scorecard`, a parity check against W1-1c
- `test_shadow_variant_lines_never_enter_live_tally`

### Order and parallel groups
- **G3-A** {3a, 3b}. Docs only. This is the smallest first item, and it can run right now, in parallel with W1.
- **G3-B** {3c, 3d}
- **G3-C** {3e, 3f, 3g}. Needs W1-1c for parity.
- **G3-D** {3h}. This is live-path and touches `composition.py`, so it must be serialised after W1-G1-D and W2-G2-E.

### Live path and restarts
- Only 3h is live-path: merge outside 16:30–17:10Z, then respawn the node.
- 3g is a timer only.
- No supervisor restart.

### Trade-offs
- **Native `BacktestNode` vs. the custom replay scripts.** Native is chosen because the rules require it, and `FillModel` plus the fee model already exist. Its weakness is known: replay cannot measure slippage. So the screen is reject-only, and live trials are the only promotion path.
- **Open search vs. a grammar with a K cap.** An open search spends α without bound and manufactures edge through selection (L-41). The grammar with a cap keeps the family-wise error controlled.
- **Is AUT-3 retraining a prerequisite?** No. Retraining without an accepted screen just repeats the 09-20 dead end. Gating it on an AUT-S PASS means compute is spent only where a candidate has survived rejection.

---

## Cross-workstream risk register
| Risk | Severity | Mitigation |
|---|---|---|
| The LAX p̂ 0.992 is a systematic rung-direction or input defect that also affected earlier trades | HIGH | Step-0 audit first. If it is a defect, the W1 scorecard excludes affected decisions **and reports the count**. The RED test lands before any W2 work. |
| The W2 resume bar never passes (prior evidence: forecast edge closed on PM.us) | HIGH (likely) | FQ stays halted. W3 is never blocked by W2. A failed bar is recorded as a hypothesis-ledger disposition, not left as a silent hold. |
| The halt job gains a clear path through a refactor | HIGH | Import-graph test plus code review. A SET-only CLI entry. |
| Two writers to `settlement_truth.csv` | MED | One timer is the only writer. The `--since` append mode refuses to rewrite rows (L-50). |
| Live-path merges trip the exec import pin or the firewall | MED | Firewall guards in every focused gate. Widen, never relax (L-12). |
| Agents run `ruff format` on whole directories, or stash, or run `uv sync` | MED | Briefs say: format only your own files, run `git status` before committing, use the explicit interpreter, never stash. |
| Concurrent slices on `composition.py` / `strategy.py` | MED | Groups are serialised as noted. Full gate after every merge (L-43). |
| Re-calibration job memory blow-up | MED | systemd `MemoryMax`, `RuntimeMaxSec`, and a stall watch. |
| A shadow result leaks into a live verdict | HIGH | Tagged lines, plus `test_shadow_variant_lines_never_enter_live_tally`. |

## Global sequencing (smallest first)
1. Step 0, read-only and parallel: the LAX audit, the portfolio_roi skip root cause, and the FQ NO-side funnel count.
2. In parallel: W1-1a (truth timer), W3-G3-A (docs and re-sequence), W2-2a (PREREG_FQ_v1 draft).
3. In parallel: W1-G1-B, W1-G1-C, W1-G1-D, W1-G1-E (live-path, outside 16:30–17:10Z, then node respawn).
4. In parallel: W2-G2-A, W2-G2-C, W2-G2-D, W2-G2-E. Then W2-G2-B, the auto-halt, which is the first automatic P&L stop.
5. W3-G3-B, then G3-C, then G3-D. AUT-2 labels and AUT-5a demotion are pulled forward in the queue.
6. The FQ resume decision, by the bar alone, as a capped live trial under the R-B boundary.

## Success criteria
- [ ] Truth is current to D-1 daily, with the coverage gap reported.
- [ ] The FQ scorecard runs daily, and FQ appears in `portfolio_roi` and `family_tally_v2`.
- [ ] The monitor sees 100% of FQ positions.
- [ ] The LAX verdict is written, with a RED→GREEN test if it is a defect.
- [ ] `PREREG_FQ_v1` is frozen, the boundary artefact is pinned, and the auto-halt is live with SET-only behaviour proven.
- [ ] The FQ repairs are merged behind the halt. The resume happens only through the bar.
- [ ] AUT-S has screened at least one registered cycle, with reject-only output and α accounted.
- [ ] Every merge passes the gate: `scripts/ci/run_tests_no_egress.sh` with EXIT=0 read, and `lint-imports` reporting "N kept, 0 broken".

## Key paths
- `/home/jon/breezy/src/breezy/strategy/forecast_quantile_ladder/{decision,strategy,composition,latch,bounds,artefact_bounds}.py`
- `/home/jon/breezy/src/breezy/strategy/ladder_ev/config.py`
- `/home/jon/breezy/src/breezy/strategy/current_rung_hold/{position_monitor,set_family_halt_cli,fee_drift_probe}.py`
- `/home/jon/breezy/scripts/analysis/{settlement_truth_dataset,portfolio_roi_report,family_tally_v2,score_live_trials,crh_group_sequential_boundaries,hypothesis_register,nbp_market_comparison}.py`
- `/home/jon/breezy/src/breezy/{analysis/hypothesis_ledger,analysis/nbp_calibration,runtime/backtest_harness,persistence/gs_boundary_artefact}.py`
- `/home/jon/breezy/deploy/families/pm_us_crh_fq_v1.json`
- `/home/jon/breezy/deploy/systemd/`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/`

---

## Round-1 peer review resolution (coordinator, 2026-10-04; domain, ARCH and SEC all REQUEST_CHANGES; binding on r2)
- **FQ-R1, no parallel machinery.** The scorecard is built as an early slice of AUT-2: `analysis/labeling/fq_scorer.py`, `ForecastQuantileLadderScorer` on C2 `label/v1`. Evaluation is built as an early slice of AUT-4: `FqEvaluator`, which reuses `forecast_conditional_scoring.py`. Reports are thin readers over C2. `portfolio_roi` follows AUT-2's gating rule (`test_gated_unlabelled_fq_publishes_no_roi_figure`).
- **FQ-R2, queue order.** The AUTONOMY queue's Needs column is kept intact. AUT-1a WP5 stage 3 finishes first. True prerequisites go in as new rows with explicit Needs: R-B, the truth fetch, the interim stop bridge and the FQ v2 repair.
- **FQ-R3, interim stop.**
  - It is an in-node probe modelled on fee-drift (`app/trade.py:461-473`). It reads a pinned, fresh scorecard artefact, and checks sha, schema, an `as_of` age bound and the truth-coverage field.
  - It acts through an entry-only veto. FQ has no exit path, so nothing is stranded.
  - It sets only. A test at the attribute and call level forbids any reference to a clear method.
  - Stale or missing input (UNKNOWN_STALE) sends a repeated CRITICAL alert, and beyond a pre-registered bound it vetoes entries (fail-closed, per L-38).
  - Label it a TEMPORARY BRIDGE. It retires when AUT-5a's `entry_veto` and drawdown producer land.
  - Halt clearing stays human-only. No timer or agent may clear a halt.
- **FQ-R4, the repaired strategy is a new family.** It is registered as `pm_us_crh_fq_v2`, and v1 gets `terminal_climate_day`. Pre-repair and post-repair rows never share an α sequence. The latch and trial_id grammar stay unchanged, and occupancy is a separate read.
- **FQ-R5, P&L and truth sources.**
  - Realised P&L comes from venue settlement events in the exec store, reconciled per station against official truth.
  - The truth FETCH is a separate unit: public GET to `mesonet.agron.iastate.edu` only, with no venue credential, only `alerts.env`, `MemoryMax`, `RuntimeMaxSec` and `OnFailure=`.
  - It is the single writer of the cache. The dataset script stays offline.
  - The plan does not claim sandbox containment for user units.
- **FQ-R6, shadow at the executable ask as primary evidence.**
  - What counts: shadow decisions at the observed executable ask, a depth-checked qty-1 taker, net of fee.
  - What it decides: SCREENING and the RESUME decision. Live real-order trials then validate fill realism and execution.
  - This needs a written PREREG v2 amendment, filed as a ruling under `docs/evidence/` through the peer loop. It supersedes "shadow never feeds a verdict" for screening and resume only.
  - Every line carries a mandatory `source` field: shadow, backtest or live. Every reader fails closed when the field is absent.
- **FQ-R7, statistics for a standing loop.**
  - Use anytime-valid e-processes: a betting confidence sequence on per-fill martingale differences, with BE_i = ask + fee.
  - Combine them with online FDR control across hypotheses (e-LOND or alpha-investing), replacing the fixed Bonferroni split.
  - Screening spends no α. α is charged per nomination.
  - The L-40 amendment (i)/(ii) applies.
  - Bootstrap by calendar day.
  - N is computed from holdout residuals, never chosen arbitrarily.
  - The resume bar has three conditions, all required: shadow net P&L lower bound > 0 at the executable ask, BSS on TAKES (not only on all decisions), and the calibration guard.
  - Repairs tuned on the 5 losing station-days are data-dependent and need a fresh sample.
- **FQ-R8, diagnose before repairing.** Step 0 adds a check of the MIA p̂ = 0.6368, repeated across 3 days and rungs: is the predictive spread collapsed, or is p produced by integer-quantile geometry? A LEAK or INPUT_DEFECT verdict blocks W2. The ceiling idea is dropped unless it is model-intrinsic and registered as an α-spending variant. Report per-rung-position PIT.
- **FQ-R9, new measurement.** W1 gains a model-free market calibration scan: ask bin against realised outcome, by side, across all rungs, from the tape plus truth. It tests longshot bias and cheap NO.
- **FQ-R10, the search loop includes new weather information.** It admits new US weather sources, through a scheduled AUT-3 refit. The search grammar adds execution mode, horizon and observation conditioning. The AUT-3 gate is not weakened: a screen PASS feeds AUT-4 nomination, never retraining directly. The plan ends in a standing loop with no fixed horizon: AUT-S generation → AUT-4 nomination → capped live trial → AUT-5 promotion/demotion.
- **FQ-R11, dropped items.** Drop 1g/1h (the position-monitor seed, which is infeasible and redundant) and 1i (the decision-log fields, which contradict AUT-1 r12). The NO-side work adds leg-sign reconciliation tests through the real writer. One rung per station-day is recorded as a RISK LIMIT, using max-net-edge at one snapshot, not as a repair.
- **FQ-R12, corrections and requirements.**
  - The supervisor reads no manifests. The node loads them at boot, so a manifest change needs a node respawn.
  - The harness is `backtest()`/`BacktestEngine`, not `BacktestNode`.
  - The screen states which days are usable: replay-sufficient tape is scarce. Rejection is conservative, rejecting only when the upper bound is below 0. Add a SPA or reality-check multiplicity control.
  - Every new timer names its install, `daemon-reload` and enable owner.
  - Each node respawn is followed by a `--status` check of the halt.
