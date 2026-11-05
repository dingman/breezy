# [PLAN] TE-2 r2: Root-cause the FQ v1 0/25 result (delta over F0 and FQ_LOSS_TRIAGE)

Status: r2. It revises r1 under the binding coordinator rulings in `reviews/TE-2-r1-merge.md`. The coordinator saves it to `docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-2_plan_r2.md`.

The plan is read-only analysis. It produces one committed analysis script and its tests, plus evidence artefacts. It does not arm, halt, refit or edit strategy code.

## 0. What is already covered (do not redo) and the delta TE-2 owns

| Covered | Source |
|---|---|
| S0-1 LAX 10-05 `<97`, p̂ 0.992, ask 0.64: genuine, with no leak or input defect. The bot's own code recomputes it from the NBM 13Z cycle. | `FQ-LOSS-RESPONSE_plan_r3.md:87`; `FQ_LOSS_TRIAGE_2026-10-04.md:30-32` |
| S0-2 MIA p̂ 0.6368 comes from NBM's own tight spread. | plan r3 `:88` |
| Aggregate triage on n=14 with 1 win: Brier 0.075 vs market 0.048, mean p̂ 0.287 vs mean ask 0.142, NBM spread about 2 °F vs realised misses of 3–8 °F, and 2–3 exclusive rungs stacked per station-day. | triage `:9-23` |
| Fee, side, sizing, fee-θ drift and the latency race are ruled out. | triage `:25-28` |
| The M1 market scan found no model-free cell. Cheap YES (ask < 0.10) is a "reliable loser" filter input. | `M1_MARKET_SCAN_2026-10-04.md` |
| The 25-fill, −4.17 re-score, with 5 one-degree losses and zero slippage on 34/34. | `TRADE_EFFECTIVENESS_2026-10-11.md:12-27` (coordinator recipe, not a committed script) |

**The delta TE-2 owns:**
1. A per-fill classification of all 25 fills into one pre-declared taxonomy. The 10-05 and 10-06 settlements are new since the triage.
2. Exact variance tests at cluster level, with their power.
3. A split into fixable defect, model limitation and variance. The triage says "overconfident" but never separates location bias, spread and artefact extrapolation.
4. A committed, reproducible script. The audit re-score was hand-run.
5. A consumer for every finding, including INCONCLUSIVE.

**Expected outcome, stated up front:**
- There are about 14 station-days, in fewer clusters. At the audit's p̂ levels, T-WIN is expected to reject H0-M (model calibrated).
- The informative content is therefore the attribution: which defects, which limitation, which flags.
- VARIANCE is close to unreachable. INCONCLUSIVE is a live outcome and has its own consumer (§7).

## 1. Verified premises

Re-verified on 2026-10-11. Entries marked CHANGED differ from r1.

- **P1. FQ is D+1 only and prices YES off `p_lower`.**
  - `src/breezy/strategy/forecast_quantile_ladder/decision.py:216-218` and `:277-281` (`NotDPlus1`).
  - `:349` is `ev_net(p_lower, cost)` for YES; `:353-355` takes iff `net > forecast_margin(h)`.
  - `:331` sets `p_hat` as the mean of per-draw rung probabilities. p̂ depends only on the percentiles, the draws and the bought rung's bounds.
- **P2. The Take line carries no ask and no forecast vector** (`decision.py:200-212`).
  - It has no `client_order_id` either.
  - The ask is proxied by the fill's `cumulativeCost`. The audit measured slippage 0 on 34/34.
  - The decision-time ask is unauditable (audit "Gaps"). The report must say so.
- **P3. Logs live in `~/.local/share/breezy/logs/breezy-trade-202610*.log`** (CHANGED).
  - r1's repo-root `logs/` glob does not exist.
  - Files: 10-01 (3 boots), 10-02 (3), 10-03, 10-04, 10-05, 10-06 and later.
  - Reviewers counted 32 Takes, 32 OrderInitialized and 25 OrderFilled.
  - 7 Takes are IOC misses with no fill.
  - The 10-03 log is about 1.4 GB. The 10-04 log holds about 2.3 M `SHADOW_DECISION` lines. Streaming is required.
- **P4. The ladder partition is NOT recoverable from same-`now_ns` lines** (CHANGED, r1 was wrong).
  - A Take's `now_ns` matches only that rung's Take line plus its `already_latched` Refuse. Each rung is evaluated at its own `now_ns`, and the log is on-change.
  - Evidence: 10-04 log, `now_ns 1791132619727949700` (MIA 89_90) matches 2 lines and no other rung. Also `strategy.py:585-625`.
  - The partition is rebuilt as the union of `rung_id`s per (station, climate_day) across all logs, plus `instrument_facts.bucket_facts_from_instrument_id`. A station-day whose union cannot be shown complete is flagged `PARTITION_INCOMPLETE`.
  - p̂ reproduction needs only the bought rung's bounds. K7 and "central 80%" depend on the rebuilt partition.
- **P5. The fill → Take join is a three-hop chain** (CHANGED).
  - fill → OrderFilled → OrderInitialized by client id, then init → Take by instrument and time window.
  - `decision_link.py`: `read_log_events` (`:161`), `bridge_decision` (`:202`, joins on `fill.instrument_id` within `BRIDGE_TAKE_TO_INIT_MAX_S`), `bridge_report` (`:250`).
  - `bridge_decision` takes `epoch_class` and raises `BackfillRefused` unless the class is PRE_EPOCH (`:211-212`).
  - `fill_source.py:58` `read_durable_fills(db_path)` opens the store read-only and returns a `FillRead`. `FillRead.require_clean` is at `:49`.
- **P6. The FQ artefact is a validate-stage candidate** (manifest `pm_us_crh_fq_v1.json`, sha256 `9c0b6d6e…23a5`, stations LAX, MDW, MIA, SFO).
  - `NBP_S2_VALIDATE_RESULT_2026-09-30.md`:
    - G2.0 (n=11604) and G2.1 (n=4335) are the calibration baseline.
    - `month_10` mean residual is −0.20 °F, n=369, p=0.31, not significant (`:264-269`).
    - v5.0 parameters come from the 05-04..06-30 fit slice.
  - Consequence (CHANGED): LOC_ARTEFACT is reframed as "v5.0 May–June parameter extrapolation to October". The G2 results are the prior. TE-2 on about 12 clusters is weaker evidence than G2.1 and says so.
- **P7. Holdout (CHANGED, r1 was wrong).**
  - `RULING_holdout_freeze_and_forward_window_2026-10-03.md` C4.1 items 1, 2 and 4 freeze the holdout at [2026-07-01, 2026-10-02). Days on or after 10-02 are forward data, and changing that text is an ARCH change.
  - Every FQ climate day is 10-02..10-06, so none is a holdout day. No new ruling is filed.
  - `nbp_calibration.py:277` `DEFAULT_SPLITS` still lacks the end date. The code has not caught up, so the script must still never touch `open_holdout`.
- **P8. The SL-13p parity harness refuses October days** (`nbp_shadow_parity_pure.py:98-132`, `PostFreezeTapeRefusedError`). Recompute with production `evaluate` plus injected inputs (§5 S0-D).
- **P9. Which vector the strategy sees.**
  - `nbm_quantile_actor.py:210-218` keeps the nearest-valid-start (D+1) window per station and variable.
  - `available_at_ns = cycle_runtime_ns + measured_lag` (`:221-233`). The lag is measured at runtime.
  - The backfill store's availability comes from Last-Modified (`nbp_derived_store.py:142`). The two clocks differ, so the node log is the visibility source (P11).
  - The NBP TXN window length is UNVERIFIED (`NBP_TXN_WINDOW_AND_BBB_NOTE_2026-09-29.md:42-53`).
- **P10. Truth (CHANGED).**
  - `~/.local/share/breezy/derived/fq-truth/truth_cli_finals.csv` runs to 2026-10-10. `coverage.json` has top-level `coverage_gap_days == 1`: SFO has a gap on 2026-03-11 and 282 final days (`:4, 62-66`).
  - r1's "283 final days" and the "gap must be 0" STOP were wrong.
  - The coverage check is scoped to the settlement days only (§5 S0-F).
  - Truth is read through `settlement_source.NwsCliFinal` (`settlement_source.py:41`) plus `score_trial` (`trial_scorer.py:167`), the same path as TE-1.
  - `NwsClimateDay` (`domain/nws_climate_day.py:117`) is the record type.
  - The loader hard-clips at `climate_day <= 2026-10-06`. M1-v3's window starts 10-07; only the window field of the frozen PREREG may be consulted, never outcomes.
- **P11. Cycle and visibility source (CHANGED).**
  - `poll_ledger.jsonl` starts at the 10-06 01Z cycle, so it covers none of the take cycles.
  - The node logs carry `NBM_NBP_PUBLISHED cycle_ns=%d …` (`nbm_quantile_actor.py:546`, the FQ-S6 positive line). Its log timestamp is the visibility time.
  - The ledger sha check is N/A for 10-01..10-05.
  - `derived/nbp` stops at 09-29 and `derived/nbp5` at month 06. October vectors are re-fetched (§5 S0-D).
- **P12. Route-back policy.** `RULING_FQ-v2-NO-TRADE_2026-10-08.md:44-50`: T1 (M1-v3 CONFIRM, read ≥ 12-07), T2 (new family and prereg), T3 (a new US source, i.e. F13). The F13 freeze review is ≥ 10-21 (`PROGRESS.md:104`).
- **P13. Lessons (repo-local only, headers verified in `docs/core/LESSONS.md`).** L-1 (`:8`), L-2 (`:67`), L-18 (`:871`), L-40 (`:1384`), L-42 (`:1421`), L-52 (`:1610`), L-55 (`:1666`).
- **P14. Manifest scope field (NEW, A11).**
  - `terminal_climate_day` is a CLIMATE day and the bound is inclusive: `family_barrier.py:83-90`, `family_manifest.py:43-48`, `attribution.py:234`. The manifest says 2026-10-05.
  - The audit lists an FQ fill on SFO 10-06 (`gte81lt82`, CLI 80). That fill lies outside the family's registered scope.
  - Stage 0 confirms it. The fill is kept in the 25 and flagged K1b (§3). It is bookkeeping and a TE-1 and manifest bug row, not a cause of loss.

**Not verified; Stage 0 checks these:**
- The epoch class of the 25 fills.
- That S3 still serves the 10-01..10-05 cycles.
- That a second truth source exists.
- That venue-resolved outcomes are readable.
- The number of station-days and clusters (reviewer count is 14 station-days over 5 climate days).

## 2. Statistical design (frozen before Phase B)

**Units.**
- The station-day is the exact unit. Its rungs are mutually exclusive (L-40), so W_d ∈ {0,1} and P_d = min(1, Σ p̂_i over the bought rungs).
- P_d sums p̂ taken at different cycles and assumes marginal calibration. State this in the report.
- **Cluster (binding).** A cluster is a station-event: consecutive climate days at one station form one cluster. LAX 10-02..10-06 is one cluster. Phase A reports the cluster count.
- Climate-day clusters (n=5 days) are a descriptive sensitivity only.

**P_c under correlation.**
- Within a cluster, win events are positively dependent through shared forecast bias.
- The binding P_c is the conservative Fréchet bound P_c = max over the cluster's P_d. This makes the p-value larger (harder to reject).
- The independent value 1 − Π(1 − P_d) is reported as the optimistic bound.

**α allocation (overall ≤ 0.05 by Bonferroni across three families):**

| Family | Tests | α |
|---|---|---|
| Primary | T-WIN | 0.02 |
| Secondary, Holm via `nbp_calibration.holm_correction` (`:1670`) | T-LOC, T-SPREAD | 0.02 |
| Artefact | T-ART | 0.01 |

**Tests.** All are exact, standard-library, and conditional on take where noted. Poisson-binomial recursion is checked against brute force.

- **T-WIN (primary, one-sided lower tail, cluster level).**
  - H0-M: P(win_c) = P_c. With zero wins the p-value is Π(1 − P_c).
  - Companion H0-K uses the ask-implied probability net of θ·p·(1−p) fees. It is reported to say whether bad luck at the price paid is plausible.
  - The station-day-level result is a reported sensitivity.
- **T-LOC (Holm).** Exact sign test on cluster-mean signed (tmax − corrected median).
  - It is labelled "conditional on take" (adverse selection, `decision.py:349-355`).
  - Companions: the same on the raw NBM median, and the unfilled-Take contrast (the 7 IOC-missed Takes' signed errors, descriptive).
  - T-LOC alone never yields FIXABLE.
- **T-SPREAD (Holm).** Count of station-days with mid-PIT outside [0.05, 0.95].
  - The null is per station-day from the model's own discrete pmf: P(tail) = P(tmax pmf mass in the tails). The count is Poisson-binomial over station-days.
  - It is one-sided (too many tail misses). It is labelled "conditional on take".
  - Mean z² is reported as a descriptive value only.
- **T-ART (own α).** Exact paired sign test on d = |corrected error| − |raw error| per cluster, H1: corrected is worse.
  - Prior: G2.0/G2.1 and `month_10`.
  - A rejection means "v5.0 May–June parameters extrapolate badly to October", not "the day-length fit is wrong".
- **T-EDGE: exploratory, outside every family.**
  - It is the Poisson-binomial upper tail P(X ≥ 5) for edge_dist = 1 losses.
  - The count 5 was seen in the 10-11 audit, so it is post-hoc and confirmatory weight is zero.
- **Power gate (S0-I), outcome-blind.**
  - Computed at BOTH station-day level and cluster level (conservative P_c). The alternative is H1-K, the ask-implied probability.
  - **VARIANCE requires cluster-level power ≥ 0.8.** Below that, VARIANCE is excluded from the verdict space.

**Verdict, deterministic, evaluated in this precedence:**

1. **FIXABLE_DEFECT.**
   - Any fill carries K4 (venue-resolved ≠ CLI-slug outcome), OR any K1a that reproduces as a named code or data defect.
   - K3, K2, K1b, UNTESTABLE and CYCLE_AMBIGUOUS never produce FIXABLE.
   - The statistical label below is still reported alongside it.
2. **MODEL_LIMITATION.** No K1a or K4 present, and at least one of {T-LOC, T-SPREAD (Holm), T-ART} rejects. Sub-label: ARTEFACT (T-ART), SOURCE (T-LOC or T-SPREAD rejects and T-ART does not), or both.
3. **MODEL_MISCALIBRATED_UNATTRIBUTED.** T-WIN rejects, no secondary rejects, no K1a or K4.
4. **VARIANCE.** T-WIN, the Holm family and T-ART all fail to reject, and cluster power ≥ 0.8.
5. **INCONCLUSIVE.** Everything else, with the reason stated.

Mixed results are a ranked list with share of loss, never one label.

**Downgrade rule.** If the station-day-level decision differs from the cluster-level decision for any test, the verdict is the cluster-level one and the report states the range.

**Mandatory footer, pinned by a test, printed with every verdict.** The footer reads:
- "diagnostic, post-hoc, n = N station-days in C clusters, non-confirmatory"
- "This verdict is NOT permission to re-arm. Re-open routes are T1 (M1-v3 CONFIRM, read on or after 12-07), T2 (new family and prereg), T3 (new US source, F13), per RULING_FQ-v2-NO-TRADE_2026-10-08."
- "VARIANCE does not imply positive EV."

**Forbidden.**
- Counterfactual P&L such as "would have won with the 19Z cycle" as a finding (L-18). Cycle comparisons are descriptive only.
- Any hand arithmetic. All numbers come from the script.

## 3. Taxonomy (frozen in `TE2_PREDECLARATION.json`)

**Per-fill descriptors, computed and not judged:**
- `p_hat`, `p_lower`, `ask_proxy` (fill cost).
- `edge_dist_f`: integer °F distance from `tmax` to the nearest edge of the bought band, with the open `lt` and `gteLlt` bands handled explicitly.
- Mid-PIT of `tmax` under the corrected model CDF, and the signed standardised error z.
- Raw vs corrected median error, and the correction in °F.
- Cycle age at decision and the newest visible cycle at `now_ns` (from the log).
- Rungs bought on the same station-day, and `PARTITION_INCOMPLETE`.

**Primary partition (outcome classes, first match wins, order pinned by a test):**

| Class | Rule |
|---|---|
| BOUNDARY (K5) | `edge_dist_f == 1` and PIT in [0.05, 0.95] |
| TAIL (K6) | PIT outside [0.05, 0.95] |
| BAND_SELECTION (K7) | 2 or more rungs bought that station-day, tmax within the model's central 80% (PIT in [0.10, 0.90]), and tmax outside every bought band. Needs a complete partition; otherwise this class is UNTESTABLE for that station-day. |
| VARIANCE (K9) | Residual: body miss with `edge_dist_f >= 2` and none of the above |

Nothing is renumbered. The classes are K5, K6, K7, K9 and the flags are K1–K4. There is no K8.

TAIL attribution: LOCATION if T-LOC rejects, SPREAD if T-SPREAD rejects, otherwise unattributed.

**Orthogonal flags (multi-label, counted separately, never in the primary share):**

| Flag | Meaning |
|---|---|
| K1a INPUT_DEFECT | S0-D reproduction miss that survives root-cause, or `available_at > now_ns`, or `vector.climate_day != instrument climate day`. Can feed FIXABLE. |
| K1b SCOPE | Fill's climate day lies outside the manifest's `[d0, terminal_climate_day]` (SFO 10-06, P14). Bookkeeping only. |
| K2 STALE_CYCLE | The cycle in use (log `NBM_NBP_PUBLISHED`) is not the newest visible at `now_ns`, or its age exceeds a maximum pinned in the declaration from the 13Z/19Z/01Z cadence and the 16:50Z decision time. Descriptive. |
| K3 TRUTH_BASIS | The outcome flips when ASOS/METAR max replaces CLI tmax. **Descriptive only** and never routed as fixable: CLI is the settlement truth. |
| K4 VENUE_SEMANTICS | Venue-resolved outcome differs from the slug-parsed outcome (`lt`/`gteLlt H`, edge inclusivity). Uses the `reconcile.py` settlement leg. |
| LOC_ARTEFACT | The corrected median error is larger than the raw error. This per-fill flag fires about half the time by chance. Inference comes only from T-ART. |
| LOC_SOURCE | Raw NBM median error alone is beyond ±1 sd. |
| FLANK_CHEAP | Ask < 0.10, consistent with M1's reliable-loser cells. |
| CYCLE_AMBIGUOUS | Reconstruction cannot decide the cycle in use. |
| UNTESTABLE | The bulletin is unavailable or reissued, or the alternative-truth/venue source is absent. It is reported as UNTESTABLE and never counted as zero evidence. |

The integer-°C reachability check from r1 is dropped. FQ is a D+1 forecast with no °C observation input.

## 4. Stage 0 gates

All read-only. Any STOP is reported verbatim and halts the plan with no partial verdict.

**Pre-freeze, outcome-blind (Phase A):**

- **S0-A. Count-only reproduction** (CHANGED).
  - Use `read_durable_fills` plus `FillRead.require_clean`.
  - FQ fills must be 25 and every `instrumentId` must parse, with `n_undecodable == 0` (else `FillStoreCorruption`, STOP).
  - Record the epoch class. If POST_EPOCH, `bridge_decision` raises `BackfillRefused`, so STOP and re-plan the join on the C1 attribution path.
  - No wins and no P&L are computed before the freeze.
- **S0-B. Manifest scope.** Confirm P14: which fills have climate day > `terminal_climate_day`. They get K1b.
- **S0-C. Take attribution, 25/25 required** (CHANGED).
  - Use `read_log_events` over `~/.local/share/breezy/logs/breezy-trade-202610*.log`, then `bridge_decision` for each fill, then `bridge_report`.
  - A fill that does not attribute to exactly one Take is a named UNCLASSIFIED outcome, and the plan STOPs. There is no tolerance.
  - The 7 unfilled Takes form a separate census (their p̂ vs the fills'). They carry no P&L.
- **S0-D. Reproduction gate.**
  - **Pin to the deployed commit** at each boot, taken from the boot log and `git`, never HEAD. A change to bounds or calibration after 10-05 would otherwise cause a false STOP.
  - **Inputs (all named):**
    - the manifest `pm_us_crh_fq_v1.json`;
    - `ArtefactBoundsProvider` (`artefact_bounds.py`);
    - `load_live_calibration(<manifest path>, <sha>)`;
    - a fresh `QuantileLadderLatch`;
    - `cfg`, `fee_coefficient`, `slippage_floor_prob`, `latitude_deg`, `std_utc_offset_hours` as in `decision.py:221-241`;
    - conventions reused from `scripts/analysis/fq_evaluate_shim.py`;
    - `breezy.app` is never imported.
  - **Vector.** Rebuild with `ForecastQuantileState.push` (`forecast_state.py:245`) and `value_at` (`:310`), applying the actor's D+1 `_nearest_per_station_variable` filter.
  - **Cycle and visibility.** Take both from the node log `NBM_NBP_PUBLISHED cycle_ns=` lines (P11). The poll-ledger sha check is N/A for 10-01..10-05.
  - **Fetch.** One coordinator step, run outside 16:30–17:10Z (`launch_window_guard`, `capture_schedule.py:36-51`):
    `BREEZY_LIVE=1 BREEZY_USER_AGENT=<monitored> .venv/bin/python scripts/analysis/nbp_backfill.py --start 2026-10-01 --end 2026-10-05 --output-dir <scratch> --request-budget <2 × planned items> --apply --report-json <scratch>/report.json`
    - Run `--dry-run` first for the plan (`build_plan` is date-major over cycles 13, 19 and 1).
    - The backfill writes a parsed derived store carrying `raw_sha256`, not raw bulletins. Only the per-cycle `raw_sha256` and the small reconstructed-vector table are committed.
    - Tests never touch the network.
  - **Threshold and classes.**
    - Fewer than 23 of 25 p̂ matching the logged value to 1e-9: STOP.
    - A miss caused by an unavailable or reissued bulletin is UNTESTABLE.
    - A cycle-selection mismatch is CYCLE_AMBIGUOUS.
    - Only a miss that survives root cause as a code or data difference is K1a, with the delta recorded.
  - **Positive control.** A perturbed vector must produce a mismatch, which proves the gate can fail.
- **S0-E. Import and holdout guard** (CHANGED).
  - The AST pin is an allowlist of modules and names. It also forbids `ast.Attribute` and string access to `open_holdout` or any holdout path, and any path under an M1-v3 directory.
  - Mirror the scan shape of `test_nbp_shadow_parity_contract.py`.
  - `lint-imports` does not cover `scripts/` (`pyproject.toml:61-67`, `root_packages` is `breezy` and `nautilus_trader`). The AST pin plus `test_execution_egress_firewall_guard` (which scans `scripts/`, `:133`) are the enforcement.
- **S0-F. Truth quality, scoped** (CHANGED).
  - Check `coverage.json` only on the settlement days of the 14 station-days: `last_final_day >= 2026-10-06` and `catalog_disagreement == false`. The 2026-03-11 SFO gap is irrelevant.
  - Before the freeze, read ONLY record-status fields through `NwsCliFinal.record` (final, superseded, correction or flag state). Never read `tmax_f`. This is a disclosed pre-freeze read.
  - A flagged or superseded settlement day is `TRUTH_UNSETTLED`, with its exclusion count stated.
- **S0-G. Alternative sources.** Look for a METAR/ASOS series (`us_source_archive/metar-routine`, `asos-cache`; reuse the `settlement_alignment_study` loaders) and a venue-resolved outcome per instrument. If absent, K3/K4 are UNTESTABLE.
- **S0-H. Freeze.**
  - Phase A emits the per-fill outcome-blind table of p̂, ask proxy, cycle age, newest-visible flag, rung geometry, P_d, P_c and clusters.
  - `TE2_PREDECLARATION.json` holds the taxonomy, thresholds, tests, α allocation, verdict rules, footer text, consumer map, the cycle-age maximum, the P_c rule and the Phase A table sha256.
  - It does NOT store its own sha, or the sha of the commit that contains it.
  - **Enforcement (CHANGED).** Phase B refuses unless all of these hold:
    - (a) the blob sha256 of the script and core module equals values recorded in a separate `TE2_PINS.json`, whose own sha the coordinator records in the commit message;
    - (b) the predeclaration file is committed and its commit is an ancestor of HEAD (checked with `git merge-base --is-ancestor`);
    - (c) the result artefact is committed in a later commit than the predeclaration. Git records commits, not runs, so this ordering is the check.
  - Disclosed contamination: the audit and triage already showed the headline direction (0 wins, LAX heat bust, five 1-degree losses). The freeze constrains classification and thresholds, not the prior.
- **S0-I. Power gate** (§2). Outcome-blind, at both levels.

**Phase B (after the freeze):**
- Reproduce the audit: 25 fills, 0 wins, net −4.17 (cost + fee − payout, ±0.005), and 34 / 2 / −4.63. Mismatch is a STOP. Outcomes key on the INSTRUMENT climate day, not the order date (the audit's rejected seam result).
- Join truth through `NwsCliFinal` and `score_trial`, clipped to `<= 2026-10-06`.

## 5. Work packages

All work is native-first: no new infrastructure. Reuse what is cited above, plus `score_trial`, `holm_correction` and `combine_station_day` (`current_rung_hold_v2.py:296`, where the types fit; otherwise state why not). Statistics use the standard library only.

**Layout (each file under 400 lines; 800 is a hard stop):**
- `scripts/analysis/fq_v1_loss_taxonomy.py`: CLI with Phase A and Phase B modes.
- `scripts/analysis/fq_loss_taxonomy_core.py`: pure, no I/O. Descriptors, classifier, Poisson-binomial, tests, verdict, footer.
- `scripts/analysis/fq_loss_taxonomy_inputs.py`: I/O wrappers over the reused modules, the streaming reader and the ladder union.
- Tests in `tests/unit/test_fq_loss_taxonomy_core.py` and `…_inputs.py`.

**WP0. Stubs first, then RED tests (tdd-guide).** Stubs raise `NotImplementedError` so each test fails for the stated reason, not on `ImportError`.

| # | Test | Failure mode before implementation |
|---|---|---|
| 1 | `poisson_binomial_matches_bruteforce_enumeration` | wrong value |
| 2 | `zero_wins_pvalue_equals_product_of_complements` | wrong value |
| 3 | `station_day_collapses_exclusive_rungs_and_clamps_P_d_at_1` | P_d above 1 |
| 4 | `cluster_P_c_is_max_of_P_d_and_lax_is_one_cluster` | wrong cluster count |
| 5 | `classifier_first_match_order_is_pinned` (a fill matching BOUNDARY and TAIL conditions is TAIL; BOUNDARY precedes BAND_SELECTION) | wrong class |
| 6 | `edge_dist_counts_integer_f_incl_open_lt_and_gteLlt` | wrong distance |
| 7 | `pit_midpoint_for_integer_outcome_from_pmf` | wrong PIT |
| 8 | `t_spread_null_is_per_station_day_pmf_not_binomial_0_10` | wrong null |
| 9 | `verdict_variance_requires_cluster_power_0_8` | VARIANCE at 0.5 |
| 10 | `verdict_mismiscalibrated_unattributed_branch` | missing branch |
| 11 | `t_loc_alone_never_yields_fixable` | FIXABLE returned |
| 12 | `k3_never_yields_fixable` | FIXABLE returned |
| 13 | `footer_is_present_and_names_t1_t2_t3_not_permission_to_rearm` | footer missing |
| 14 | `holm_over_two_tests_only` (T-EDGE excluded) | wrong family |
| 15 | `truth_loader_clips_after_2026_10_06_and_never_holds_later_rows` | later row held |
| 16 | `ast_pin_allowlist_forbids_open_holdout_attribute_and_string_access` | bypass passes |
| 17 | `phase_b_refuses_without_pins_and_ancestor_commit_order` | runs anyway |
| 18 | `s0a_count_only_runs_without_any_outcome` | outcome read |
| 19 | `all_25_fills_attribute_or_stop_unclassified` | silent drop |
| 20 | `s0d_perturbed_vector_mismatches_and_is_classed_k1a` (positive control) | no mismatch |
| 21 | `unavailable_bulletin_is_untestable_not_k1a` and `cycle_mismatch_is_cycle_ambiguous` | wrong class |
| 22 | `streaming_reader_bounded_memory_and_take_split_across_prefilter_boundary_is_kept` | line lost or memory grows |
| 23 | `k1b_flags_fill_beyond_terminal_climate_day` | no flag |
| 24 | `alt_truth_unavailable_marks_untestable_not_zero` | counted as zero |
| 25 | `reproduces_audit_25_fills_zero_wins_minus_4_17` (Phase B; fixture written through the real writer path, `read_durable_fills` plus `require_clean`; L-42) | wrong total |

Per L-55, run the production default path once where a fake dependency is injected.

**WP1. Phase A (outcome-blind).**
- Implement the readers, the join, the partition union and the reconstruction. Run S0-A, B, C, D, G, I and emit the Phase A table.
- Streaming is a line-wise prefilter on `'kind': 'Take'` plus a keyed second pass on `now_ns`.
- The coordinator runs it under `systemd-run --user -p MemoryMax=4G -p LimitNOFILE=524288`, with `--basetemp` under `~/.cache` (not `/tmp`, tmpfs fills RAM). It runs one heavy job at a time.
- Interpreter: `/home/jon/breezy/.venv/bin/python`. No `uv`, no `pip`. In a worktree set `PYTHONPATH=<wt>/src`. No `git stash`.

**WP2. Freeze.**
- The coordinator commits `TE2_PINS.json` and `TE2_PREDECLARATION.json` (with the script and core blob shas in the pins file).
- The review checks that no Phase B quantity leaked in. Reviewers: prediction-market-reviewer (statistics and cluster rule), python-reviewer (code), and an adversarial Codex review. The reviewer is not the TE-1 or script author.

**WP3. Phase B and classification.**
- Run the Phase B reproduction, the truth join, the alternative sources, the classification, the tests and the verdict. Write JSON and a generated `.md`.
- Add a TE-1 ledger cross-check block, or print "TE-1 cross-check pending". Do not build a second scorer.

**WP4. Findings, consumers and delivery.** See §7.

**Outputs (committed):**
- `docs/evidence/te2/TE2_PINS.json` and `docs/evidence/te2/TE2_PREDECLARATION.json`.
- `docs/evidence/te2/fq_v1_loss_taxonomy_<date>.json` and generated `.md`, recording the script and pin shas.
- Per-cycle `raw_sha256` values and the small reconstructed-vector table.

## 6. Dependencies and gate

- **Hard.**
  - The node logs and the durable fill store.
  - S3 serving of the 10-01..10-05 cycles (if it does not, those fills are UNTESTABLE for S0-D, which can leave fewer than 23 matched and trigger the STOP).
  - `nbp_backfill`.
  - The `fq-truth` timers.
- **Soft.** The TE-1 ledger (cross-check only), a second truth series and a venue-resolved outcome source.
- **Sequencing.** WP0 → WP1 → WP2 (hard stage boundary) → WP3 → WP4.
- **Routing.** Grok, then Codex, then Claude tdd-guide for implementation. The coordinator runs `scripts/ci/run_tests_no_egress.sh` and reads the exit code before any push (read gate EXIT before pushing). Briefs restate the invariants: Nautilus immutable, `allow_short=False`, NO-SEND firewall, no operator caps, no live enablement.
- **Focused gate must include:**
  - the new AST-pin test and `test_execution_egress_firewall_guard`;
  - the exec-import pin and the citation map;
  - all `test_autonomy_*` tests;
  - `lint-imports`, run from the repo root, which must print "N kept, 0 broken".
  - `lint-imports` does not cover `scripts/`. Import `fill_source`, not `exec.client`, to avoid the x1 set-equality pin.

## 7. Consumers and delivery (each finding maps to exactly one)

The coordinator turns each into a row in `docs/core/PROGRESS.md`.

| Finding | Consumer |
|---|---|
| K1a | Bug row against the named module. Blocks any FQ re-open (T2). |
| K1b | TE-1 / manifest bug row: `terminal_climate_day` vs the D+1 take date. |
| K2 | Descriptive only. A feed-latency input to the F13 source review. |
| K3 | Descriptive only. If a route is wanted, the F13 US-source list. Never CF-2 or CF-7. |
| K4 | Venue-semantics row. Settlement alignment is fixed before any family trades this venue. |
| BOUNDARY (K5) | T2 input only. T-EDGE is exploratory. If it does not reject, close "no action: within model-expected near-misses". |
| TAIL (K6) with LOC_SOURCE or SPREAD | F13 / T3 input: a stratification or regime hypothesis for the F13 freeze review (≥ 10-21), validated forward only. The 25 days are forward data under C4.1 and may serve as a descriptive baseline, never as a tuning set. Any later validation uses days after 10-06 and never [07-01, 10-02). |
| TAIL (K6) with LOC_ARTEFACT (T-ART) | Calibration row against `nbp_calibration`: v5.0 May–June extrapolation to October, as input to the F13 blend design. |
| BAND_SELECTION (K7) | T2 take-rule input (rung stacking, minimum-ask filter, consistent with M1). |
| VARIANCE (K9) / VARIANCE verdict | Closed "no action" with the test, p-value and power, plus the T1–T3 footer. |
| MODEL_MISCALIBRATED_UNATTRIBUTED | F13 / T3 input: the model is miscalibrated in a way these data cannot attribute. The next evidence is T1 (12-07) or a forward screen. |
| INCONCLUSIVE | Two named routes: (1) a forward-only evidence plan defined by what the power calculation says is needed (days required for 0.8 power), handed to T2; (2) closed "no action" until T1 (12-07) if that number is infeasible. The report states which. |

**Delivery.**
- Target: the result artefact is committed by 2026-10-20, ahead of the F13 freeze review (≥ 10-21).
- If the S3 or fetch STOPs slip it, the report states the slip explicitly. F13 then proceeds on the K-flag descriptive table alone and TE-2 is cited as "pending".

## 8. Risks

1. **Overfit on a small sample.** Mitigated by the outcome-blind Phase A, the pinned freeze, exact tests, the conservative P_c and the α split.
2. **Selection bias.** T-LOC and T-SPREAD are conditional on take. Mitigated by labelling, the unfilled-Take contrast, and the rule that T-LOC alone cannot yield FIXABLE.
3. **Cycle retention or reissue.** Handled as UNTESTABLE or CYCLE_AMBIGUOUS, never silently skipped and never K1.
4. **Ask proxy.** The fill cost stands in for the decision-time ask (zero-slippage audit). State it in the report.
5. **Unverified TXN window.** Do not assert window alignment as a cause.
6. **Station dependence.** The cluster rule and downgrade rule cover it.
7. **Truth basis.** CLI is the settlement truth. The venue-side settlement was not cross-checked, so K4 may stay UNTESTABLE and is reported as such.
8. **Resources.** The 1.4 GB logs, memory caps, scratch directory and `~/.cache` basetemp as in WP1.
9. **Verdict misuse.** The footer test (#13) prevents VARIANCE from reading as permission to re-arm.

## 9. Non-goals

- No re-arm, no un-halt, no `BREEZY_ORDERS_ENABLED` change, no permit work. `RULING_FQ-v2-NO-TRADE` stays in force.
- No edits to `src/breezy/strategy/**`, `nbp_calibration`, the artefact or any manifest. A defect found becomes its own bug row.
- No refit, no new model, no `open_holdout`, no marker write.
- No change to PREREG semantics, F13 pins or `F13_prereg_blend_v1.json`.
- No M1-v3 outcome data, and no truth row after 2026-10-06 held or printed.
- No second scorer and no TE-1 build. No NO-side analysis (TE-3). No live network calls from tests.
- No new holdout ruling (the C4.1 text is not touched).

## 10. Acceptance (the goal state)

- [ ] All 25 fills carry a primary class and flags, or an explicit UNTESTABLE, TRUTH_UNSETTLED or UNCLASSIFIED-STOP reason.
- [ ] One verdict with tests, p-values, power (station-day and cluster level) and the mandatory footer. A ranked list when mixed.
- [ ] Every finding maps to one named consumer, including INCONCLUSIVE, with a delivery date or a stated slip.
- [ ] The result reproduces from the committed script. The artefact records the pins and the predeclaration commit, and the git ancestor check passes.
- [ ] The full gate passes with a read exit code, and no re-arm took place.

**Key paths for the implementer:**
- `/home/jon/breezy/src/breezy/strategy/forecast_quantile_ladder/decision.py`
- `/home/jon/breezy/src/breezy/analysis/labeling/fill_source.py`
- `/home/jon/breezy/src/breezy/analysis/labeling/decision_link.py`
- `/home/jon/breezy/src/breezy/analysis/labeling/settlement_source.py`
- `/home/jon/breezy/src/breezy/settlement/trial_scorer.py`
- `/home/jon/breezy/src/breezy/settlement/family_barrier.py`
- `/home/jon/breezy/src/breezy/analysis/nbp_calibration.py`
- `/home/jon/breezy/src/breezy/ingest/nbm_quantile_actor.py`
- `/home/jon/breezy/scripts/analysis/nbp_backfill.py`
- `/home/jon/breezy/scripts/analysis/fq_evaluate_shim.py`
- `/home/jon/breezy/deploy/families/pm_us_crh_fq_v1.json`
- `/home/jon/breezy/docs/evidence/TRADE_EFFECTIVENESS_2026-10-11.md`
- `/home/jon/breezy/docs/evidence/NBP_S2_VALIDATE_RESULT_2026-09-30.md`
- `/home/jon/breezy/docs/evidence/RULING_holdout_freeze_and_forward_window_2026-10-03.md`
- `/home/jon/.local/share/breezy/logs/breezy-trade-202610*.log`

## Changes from r1

| Finding | Disposition |
|---|---|
| merge: P4 | Adopted. P4 is WRONG. The partition is rebuilt from the union of `rung_id`s, and `PARTITION_INCOMPLETE` is defined (P4, §3, WP0 #5). |
| merge: codex F2 (memory entry) | Fixed. P13 cites only repo-local lessons with verified headers. |
| merge: holdout (arch A1) | Adopted. The S0-E ruling step is dropped, P7 is rewritten per C4.1, the AST pin is hardened and the WP4 wording is fixed (§7). |
| codex F1, python F1 (Take join) | Adopted. P5 and S0-C use the three-hop chain with `bridge_decision`, `read_log_events` and `bridge_report`. 25/25 is required, UNCLASSIFIED is a STOP and the log path is corrected. |
| python F2 (outcome blindness) | Adopted. S0-A is count-only, the P&L reproduction moves to Phase B, and the S0-F flag read is disclosed. |
| python F3, arch A10 (freeze enforcement) | Adopted. Blob-sha pins live in a separate `TE2_PINS.json`. A git ancestor check and a commit-order check replace "precedes the first run". The predeclaration holds no self-sha. |
| python F4, arch A3 (availability sources) | Adopted. The cycle and visibility come from the node log. `push` and `value_at` are used. The ledger check is N/A. CYCLE_AMBIGUOUS is its own class and not K1. |
| arch A5 (pin to deployed commit) | Adopted in S0-D. Unavailable or reissued bulletins are UNTESTABLE. |
| python F5 (fetch command) | Adopted. The exact `nbp_backfill` command, budget, window guard, and the parsed-store wording are in S0-D. |
| python F6 (`evaluate` inputs) | Adopted. Every input source is named in S0-D, reusing the `fq_evaluate_shim` conventions and not importing `breezy.app`. |
| python F7 (RED tests) | Adopted. Stubs come first with a failure mode per test (WP0). Perturbation positive control, streaming test and real-writer fixture added (#20, #22, #25). |
| python F8 (AST pin) | Adopted. Allowlist, plus Attribute and string-access bans (S0-E, #16). |
| python F9 (lint-imports scope) | Adopted. The gate section states that `lint-imports` omits `scripts/`. The AST pin and the egress guard are in the focused gate. |
| python F10, domain S11 (alpha, clamp) | Adopted. An explicit α allocation of 0.02/0.02/0.01, clamped P_d, and a marginal-calibration assumption stated. |
| python F11 (class-count wording) | Adopted. The wording is fixed and there is no K8. |
| arch A2 (S0-F STOP) | Adopted. The coverage check is scoped to the settlement days and P10 is corrected (SFO 282). |
| arch A4, domain S5, S6 (K3, K1/K2 ordering) | Adopted. The primary partition is BOUNDARY/TAIL/BAND_SELECTION/VARIANCE. K1–K4 are orthogonal flags. |
| arch A4 (K3 routing) | Adopted. K3 is descriptive and never fixable, and CF-2 and CF-7 are dropped from the consumers. |
| domain S5 (reachability) | Dropped. FQ has no °C observation input (§3). |
| arch A7 (reuse) | Adopted. Reuses `bridge_*`, `holm_correction`, `NwsCliFinal` plus `score_trial`, the ASOS loaders and the `reconcile.py` leg. `combine_station_day` is reused where the types fit. The hand-written join, truth loader and Holm test are dropped. |
| arch A8 (P6 baseline) | Adopted. G2.0/G2.1 and `month_10` are the baseline. LOC_ARTEFACT is reframed as v5.0 May–June extrapolation. |
| arch A6, A9 | Adopted. An INCONCLUSIVE consumer, the expected-reject statement and a delivery date of 10-20 with a stated slip are added (§0, §7). |
| arch A11 | Adopted. P14 shows that `terminal_climate_day` is an inclusive climate day, so the SFO 10-06 fill is flagged K1b. K1b is a bookkeeping bug row and not a FIXABLE input. |
| domain S1 (clusters) | Adopted. Station-event clusters are binding, LAX is one event, P_c is the Fréchet max, the T-LOC collapse and downgrade rule are pre-declared, and power is computed at cluster level. |
| domain S2 (conditional on take) | Adopted. T-LOC and T-SPREAD are labelled conditional on take, the unfilled-Take contrast is added, and T-LOC alone cannot yield FIXABLE. |
| domain S3 (LOC_ARTEFACT) | Adopted. Pre-declared paired exact test T-ART, with its own α. |
| domain S4 (T-SPREAD null) | Adopted. A per-station-day pmf Poisson-binomial null, one-sided. |
| domain S7 (T-EDGE) | Adopted. T-EDGE is exploratory and outside Holm. Holm covers T-LOC and T-SPREAD. K5 is descriptive, with a T2-input consumer. |
| domain S8 (power) | Adopted. VARIANCE requires cluster-level power ≥ 0.8 and "no positive EV" appears in the footer. |
| domain S9 | Adopted. MODEL_MISCALIBRATED_UNATTRIBUTED is added. |
| domain S10 (footer) | Adopted. Fixed footer naming T1–T3, pinned by test #13. |
| codex premise checks (P1–P3, P5–P12) | Confirmed. P3's log path is corrected. P4 is overruled by the merge ruling above. |