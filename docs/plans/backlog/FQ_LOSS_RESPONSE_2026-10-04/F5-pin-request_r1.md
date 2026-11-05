# F5 pin request r1: F7b guard thresholds, KILL constants, and the F6 loss-stop floor c (draft for peer review)

<!-- planner, 2026-10-08. DRAFT, not filed. Item 4 of HALT_POINT_2026-10-07 §4; it unblocks part of item 3 (F6b). Checked against HEAD 2590db5d. No operator-reserved control is named or assigned here: only the per-position cap and the daily budget are operator-reserved, and this request touches neither. -->

## 0. Summary
- `F5_prereg_v2_design.json` is frozen at `frozen_sha` 072ab026cdc790dd6e9a51d62d8164766b85fd82. It stays **byte-unchanged**. Nothing in this request edits any frozen PREREG, including M1-v3.
- The pins go into **new, additive amendment files**, frozen once each (§4):
  - **A1:** the KILL constants and the F6 loss-stop floor. A1 unblocks F6b.
  - **A2:** the F7b calibration-guard thresholds.
  Each file can merge independently.
- **Derivation status:**
  - KILL constants: DERIVED (copied from the MC).
  - Guard: mostly NEEDS-EVIDENCE; |Z| max is BLOCKED.
  - Floor c: BLOCKED on four rulings plus a new H0 MC.
  No number in this request is invented. Where no evidence exists, the request says so.

## 1. Lessons that bind this request
- **L-12:** widen exact-set barriers, never relax them. The checker's `REQUIRED_KEYS` and `_ALLOWED` are left as they are; the amendment gets its own exact key set.
- **L-34:** a pin set after evidence is seen is a second snapshot. Each pin must freeze before any evidence it governs exists (§4.4).
- **L-38:** a stop that cannot fire is MISSING. Floor c needs a positive control showing that the producer can reach FAIL.
- **L-39:** never name the reserved controls by their env-var names. Grep this file before the gate runs.
- **L-40 (with its amendment):** the variance of a mixed-side station-day is not the same-side ceiling. The floor MC must model the station-day bundle exactly.
- **L-41:** the MC null must be the registered H0 exactly: outcomes Bernoulli at BE, with selection independent of outcome.
- **L-3:** the plan must reach the goal state. §3 states exactly what F6b still lacks after this request.
- **L-10 / L-47:** every line cited below was read at HEAD. Peers should re-verify the lines rather than trust them.

## 2. (a)+(b) Values to pin: consumers, derivation rules, evidence

### 2.1 KILL constants (into A1, key `kill`). Status: all DERIVED
Rule: copy the constants unchanged from the MC that produced the frozen power table and Type-I record (`fq_mc_eprocess.py`, evidence `docs/evidence/f5/fq_resume_n_mc_seed20261006.json`, seed 20261006). Production already matches the MC; the pin only makes the match a pre-registered fact. Validity of KILL rests on the m=0 Ville argument (F7B-R22): false KILL ≤ α_kill/2 under E[Y_clipped] ≥ 0. The other grid points add conservatism only.

| Key (proposed) | Value | Production consumer | MC source |
|---|---|---|---|
| `kill_grid_points` | 5 | `src/breezy/analysis/autonomy/confidence_sequence.py:58`, used by `kill_grid` :74-79 | `scripts/analysis/fq_mc_eprocess.py:38`, :153-154 |
| `kill_grid_span` | "linspace[0, x_max]" (x_max = 4.0, already frozen) | `confidence_sequence.py:74-79` | `fq_mc_eprocess.py:154` |
| `kill_lambda_max` | 0.5 | `confidence_sequence.py:59`, :83 | `fq_mc_eprocess.py:26`, :166 |
| `kill_min_range` | 0.5 | `confidence_sequence.py:63`, :83 | `fq_mc_eprocess.py:166` |
| `kill_lambda_cap_rule` | "min(kill_lambda_max, 0.5/max(x_max−m, kill_min_range))" | `confidence_sequence.py:82-83` | `fq_mc_eprocess.py:166` |
| `kill_betting_rule` (addition, not in the F7B-R10 list) | "agrapa_minus_v1: lam=clip((m−mu)/(var+(m−mu)^2), 0, cap); prior_pseudo_days=1, prior_second_moment=0.25, var_floor=1e-6; settled days strictly before d" | `confidence_sequence.py:60-62`, :86-94 | `fq_mc_eprocess.py:41`, :44, :157-169 |
| `kill_hedge_theta` | 0.5 (implicit in the bar) | `kill_bar` `confidence_sequence.py:66-71` | `fq_mc_eprocess.py:188`, :201 |
| `kill_bar_rule` | "log(2/alpha_kill)"; KILL needs every grid capital ≥ bar, at n_cum ≥ earliest_look_n | `confidence_sequence.py:66-71`, :115-117; `evaluators/forecast_quantile_ladder.py:289-290` | `fq_mc_eprocess.py:201`, :213, :221 |

- **Naming hazard.** The frozen design's `theta` is the fee coefficient 0.0695 (`F5_prereg_v2_design.json:35`). The KILL hedge weight therefore **must** be keyed `kill_hedge_theta`, never `theta`.
- **Evidence notes.**
  - Under H1 at the pinned design (m_cap 2, x_max 4.0), the MC cells report `p_kill_by_n_max` = 0.0 (for example evidence :68 at δ_h 0.04).
  - At x_max 1.0 the same cell shows 0.9495 (:24). This is why x_max 4.0 is frozen.
  - The Type-I rows `p_kill_under_null_stream` (:3262 onward) run on streams whose clipped mean is negative. They are PASS-null evidence, not KILL-null evidence. KILL's level is analytic (F7B-R22), and `tests/unit/autonomy/test_confidence_sequence.py` carries the E[Y]=0 enumeration.
- **Already pinned in tests:** `test_confidence_sequence.py:42-44` checks the grid and the bar only. The cap, the min range and the bet rule are pinned only by the 1e-12 MC cross-check.

### 2.2 Calibration-guard thresholds (into A2, key `guard`; shape = `GuardThresholds`, `src/breezy/analysis/autonomy/eprocess.py:88-116`)
Validity note: the guard can only **remove** PASS days (`forecast_quantile_ladder.py:295`). Whatever its thresholds, the IUT level α_k (E-25 rule 3) is preserved. The thresholds therefore trade false-block rate against detecting miscalibration. That is a power question, not a Type-I question. Under the STARVED ruling, PASS is infeasible before KILL (2027-01-25), so pinning the guard has no practical effect before then.

| Key | Consumer | Derivation rule | Evidence / status |
|---|---|---|---|
| `bin_edges` | `forecast_quantile_ladder.py:149` (`_reliability_slope`), :363-366; fallback `_DEFAULT_BIN_EDGES` :84 = (0, `RELIABILITY_BUCKET_EDGES` `analysis/stats/scoring_core.py:31`, 1) | Reuse the existing native deciles (DRY; this is the fallback the evaluator already reports with). Accept only if, on the pre-2026-07-01 pool, the `p_model` of eligible takes fills ≥ 2 bins on ≥ 95 % of MC windows of size `n_guard_min`. Otherwise the slope is `INSUFFICIENT(slope_undefined)` by construction (`:156-157`). | **DERIVED-by-reuse, pending the bin-occupancy check.** No occupancy evidence exists. |
| `pooling` ∈ {pooled, per_side} | `forecast_quantile_ladder.py:187-194` | Proposed `per_side`. This is the restrictive direction, following the adjudicator precedent in RULING FQ-PREREG-v2 (α_par and stale_parity_h). NO-side hunting is a requirement, and L-40 shows the two sides behave differently. | **NEEDS-EVIDENCE.** No per-side calibration measurement of the v2 density exists. Code fact: a side with zero takes is skipped (`:191`), not refused. See Q3. |
| `n_guard_min` | `forecast_quantile_ladder.py:169` | The smallest n (per group, if `per_side`) at which (i) the calibrated-null false-block rate of the joint (\|Z\|, slope) rule ≤ α_guard, and (ii) Z's normal approximation holds: the MC null quantile of Z is within ±0.1 of Φ⁻¹ at α_guard/2. Floor: ≥ `earliest_look_n` = 20 (frozen), so the guard never binds earlier than the look rule. | **NEEDS-EVIDENCE.** No guard MC exists. |
| `spiegelhalter_abs_z_max` | `forecast_quantile_ladder.py:141-145`, :173 | Φ⁻¹(1 − α_guard/2), evaluated per settled day. Repeated daily evaluation only delays PASS, so no multiplicity correction is needed for validity. | **BLOCKED:** α_guard is pinned nowhere (not in E-25, F7B-R11 or the RULING). The MC reports false-block rates on a grid of standard quantiles {1.96, 2.576, 3.0}. That grid is an MC input, not a pin. |
| `slope_band` (low, high) | `forecast_quantile_ladder.py:175-179` | The central (α_guard/2, 1 − α_guard/2) quantiles of the slope's sampling distribution under a calibrated null at `n_guard_min`, with `bin_edges` fixed. | **NEEDS-EVIDENCE** (and α_guard). |
| `ci_rule` ∈ {point} | `_group_status` compares the **point** slope and point Z (`:173`, `:178`) | Pin `point`, which is what the code does. A CI rule would need a new `GuardThresholds` field and a code change. | **DERIVED from the code**, but see Q2: F7B-R11 and the F6 open items say "bin_edges plus the CI rule", and that wording is ambiguous. |

The guard MC (new script, sketched; it lives under `scripts/analysis/`) must:
- reuse the `fq_mc_livedata` pool, which is out-of-fold and before 2026-07-01, and never open the holdout;
- under the null, draw outcomes as Bernoulli(p_model) of the side bought (calibrated), per L-41;
- under the alternatives, use (i) slope miscalibration p → 0.5 + s·(p − 0.5) for s ∈ a stated grid, and (ii) a mean shift;
- include mixed-side days (L-40), and replay `_guard` from production verbatim, never a re-implementation;
- write `docs/evidence/f5/fq_guard_mc_seed<S>.json`, with the seed set by the coordinator before the run.

### 2.3 F6 loss-stop floor (into A1, key `loss_stop_floor`). Status: BLOCKED
Spec, verbatim: "Time-uniform −c·√t, with a stated horizon. The window starts at the arming-ruling timestamp. It is venue-level and never reads pre-epoch `family_id` (P15). It is never derived from either cap" (FQ-LOSS-RESPONSE r3 :263-267). Also: "calibrated by an H0 Monte-Carlo, derived from no cap, and names no cap variable" (r3 :597). No consumer exists yet: `src/breezy/analysis/fq_loss_stop.py` is NOT BUILT (F6 open items :6).

**Proposed derivation rule.**
- S_t = Σ_{i ≤ t} (h_i − BE_i), where:
  - per settled live FQ fill i after the epoch, normalised to qty 1 (P&L **per contract**, so c can never scale with either cap);
  - BE_i = fill_px + fee at the frozen θ (no haircut on real fills);
  - t = the count of settled fills.
- FAIL iff S_t < −c·√t for some t ∈ [t_min, t_horizon].
- c = the smallest value with P_H0(∃t ≤ t_horizon : S_t < −c·√t) ≤ α_floor, under an H0 MC with:
  - h ~ Bernoulli(BE) exactly (L-41);
  - the station-day bundle drawn with the exact mutual-exclusivity joint, including mixed-side days (L-40 and its amendment);
  - take counts drawn from the frozen pool's empirical per-day distribution.
- Report c ± its MC standard error, with ≥ 10,000 replicates and a coordinator-set seed.
- A −c√t boundary is not uniform over an infinite horizon (law of the iterated logarithm), so the horizon is load-bearing.

**Missing inputs. Each one is a peer ruling; none can be derived from evidence today.**

| Input | Why it is blocked |
|---|---|
| α_floor (false-stop level) | Stated nowhere. α_kill = 0.05 is a candidate only by analogy (Q5). |
| `t_unit` | Fills (the variance clock) or settled climate days. The spec does not say (Q6). |
| `pnl_unit` | Per-contract qty-1 is proposed, because dollar P&L would inherit the per-position cap (Q7). |
| `t_horizon` | The FQ v2 KILL date 2027-01-25, or "until retirement" (first accepted non-inert `live.drawdown` PASS). In fills it needs a take-rate **upper** bound, and only `take_rate_lower` is frozen (Q8). |
| `t_min` and past-horizon behaviour | The proposal is fail-closed: past the horizon the producer writes no PASS, so the probe reads UNKNOWN and vetoes (Q9). |
| `epoch_anchor` | The arming-ruling timestamp. FQ v2 has no arming ruling yet (F9 not done), and v1 has been halted since 10-06 (Q10). |

**Pre-registration integrity.** c is calibrated from the pre-2026-07-01 pool only, never from the live losses of 10-01..10-06, and pre-epoch fills never enter S_t. Pinning it now therefore peeks at nothing the floor will judge.

## 3. (c) What "F5 floor c" is, and what F6b needs
- **What it is.** "F5 floor c" is the constant c in the F6 FQ-BRIDGE interim stop: the producer writes `loss_stop/v1` verdict FAIL when post-epoch realised FQ P&L falls below −c·√t. The probe (`src/breezy/strategy/forecast_quantile_ladder/loss_stop_probe.py`) only reads that verdict, and has no c.
- **What F6b needs from this request.** All of the following, from the frozen A1 blob:
  1. c (numeric), with its MC evidence path and seed.
  2. `t_unit`, `pnl_unit`, `t_min`, `t_horizon` and the past-horizon rule.
  3. The `epoch_anchor` definition.
  4. A1's `frozen_sha`, so the producer test can pin its module constants equal to A1 (the pattern of `STALE_PARITY_H`, `loss_stop_probe.py:67-69`), and `test_floor_read_from_prereg_never_from_operator_controls` can hold.
- **Values F6b must match. They are fixed by F6 and NOT re-pinned here:**
  - `SCHEMA` `loss_stop/v1` (`loss_stop_probe.py:63`);
  - the digest `sha256(schema|verdict|as_of|c2_hwm|truth_sha)` (`:108-110`);
  - `MAX_AGE_H`=26 and `STALE_VETO_H`=36 (`:77-78`);
  - the parity paths;
  - `as_of` monotonicity;
  - directories created 0755 or 0700.
- **What stays blocked after A1.** The F4 labels (AUT-6 activation) and the v2 arming ruling (the epoch anchor). Until both exist, the probe stays UNKNOWN, which is fail-closed and correct.

## 4. (d) Amendment mechanics: the frozen file is never edited

### 4.1 Why a new file
`prereg_precommit_check.py` refuses any change to the frozen file:
- it requires canonical-JSON equality with the blob at `frozen_sha` (:323-326, :340-369);
- any key outside `_ALLOWED` is `UNKNOWN_KEY` (:111, :305);
- `test_eprocess.py:424-438` pins the frozen values.

Adding keys to the frozen file is therefore impossible, and widening `REQUIRED_KEYS` to fit them would be the relaxation L-12 forbids. The precedent is F13-phaseA-pin-proposals r3 §D(d): "Any amendment goes into a new … file with an amendment record."

### 4.2 Files
`docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F5_prereg_v2_amendment_A1.json` (and later `_A2.json`), with this exact key set:
- `frozen_sha`
- `amends`: {`path`: the design JSON path, `frozen_sha`: "072ab026…", `content_sha256`: sha256 of the parent's canonical body}
- `amendment_id`
- `kill` (A1)
- `loss_stop_floor` (A1)
- `guard` (A2)
- `provenance`: MC script git blob sha, evidence path, seed

Each amendment file is **additive only**: none of its keys may repeat or override a parent key.

### 4.3 Checker
Add an `--amendment <file>` mode to `scripts/analysis/prereg_precommit_check.py`. This is a code change, not a PREREG edit. The mode must:
- (i) re-run the unchanged parent check on `amends.path`, plus a `content_sha256` match;
- (ii) run `check_frozen_blob` on the amendment itself, with its own `frozen_sha` an ancestor of HEAD;
- (iii) enforce an exact key set per amendment id, with no overlap with the parent's keys;
- (iv) import the `kill` constants and compare them to `confidence_sequence` and `fq_mc_eprocess`, with no duplicated literals (same pattern as `PINNED_THETA` :45-48);
- (v) check that `guard` constructs `GuardThresholds` without error;
- (vi) refuse a second non-placeholder `frozen_sha` in the file's git history (one freeze only; F13 §D(b)).

The parent-mode behaviour and `tests/unit/test_prereg_precommit_check.py` stay byte-unchanged.

### 4.4 Order
1. Peer-review this request.
2. Rulings on Q1–Q10.
3. Run the MCs (floor first).
4. Draft A1 with `frozen_sha` "UNFROZEN".
5. One gated freeze commit, then stamp the sha.
6. Run the full gate (`scripts/ci/run_tests_no_egress.sh`) and read EXIT before pushing.

Timing constraints:
- A1 freezes before any v2 arming ruling.
- A2 freezes before the first forward-shadow source is registered (E-25 6b), so the guard never sees forward evidence (L-34).

## 5. (e) Acceptance tests (ADD; no existing test edited)
- `test_amendment_parent_is_frozen_f5_blob_and_content_sha_matches`
- `test_amendment_is_additive_no_parent_key_overridden`
- `test_amendment_exact_key_set` and `test_amendment_single_freeze_in_history`
- `test_prereg_precommit_check_amendment_mode_exits_0` (plus a planted-defect variant for each rule (i)–(vi))
- `test_kill_constants_equal_amendment_and_mc_module` (grid, λ max, min range, cap rule, bet rule, bar; MC imported in test code only)
- `test_kill_hedge_theta_key_distinct_from_fee_theta`
- `test_guard_from_amendment_constructs_guard_thresholds` (A2)
- `test_guard_only_removes_pass_days`: property test; PASS days with the guard ⊆ PASS days with no guard on the same evidence, for random thresholds
- **Floor MC acceptance:** the crossing rate at the pinned c and horizon ≤ α_floor + 3·SE under the exact H0; mixed-side and intraday-informed take-count null cases (L-40, L-41); a mutation test (a dollar-scaled P&L or a cap-derived c must fail)
- **Guard MC acceptance:** calibrated-null false-block rate reported per threshold grid point; bin-occupancy ≥ 2 bins on ≥ 95 % of windows
- **F6b side (owned by F6b, listed for completeness):**
  - `test_loss_floor_constants_equal_amendment_a1`
  - the existing plan names `test_floor_read_from_prereg_never_from_operator_controls` and `test_floor_time_uniform_from_arming_timestamp`
  - an L-38 positive control: a synthetic post-epoch losing stream below −c√t yields FAIL through the real writer and the real probe
- **Census:** grepping both amendment files and this document for the reserved env-var names returns 0 (L-39). The full gate stays green, including `test_operator_control_assignment_scan.py`.

## 6. (f) Open questions for the peer reviewers
1. **α_guard.** What level? Should it reuse α_par 0.10 (a demote-only analogue) or α_kill 0.05? Without it, |Z| max and the slope band cannot be derived.
2. **The "CI rule".** Does F7B-R11 mean point-in-band (what the code does) or CI-inside-band (needs a new field and a code change)?
3. **Pooling.** `per_side` or `pooled`? Under `per_side`, should an absent side (`:191`) be skipped (current code) or count as INSUFFICIENT?
4. **Should `kill_betting_rule` and `kill_min_range` be added?** They are beyond the F7B-R10 list, but they are load-bearing constants that only the cross-check pins today.
5. **α_floor.** What false-stop level for the bridge floor?
6. **`t_unit`.** Fills or settled days?
7. **`pnl_unit`.** Per-contract qty-1? Confirm that no normalisation by stake can leak a cap.
8. **`t_horizon`.** The FQ v2 KILL date or retirement? If it is in fills, which take-rate upper bound is used, given that only `take_rate_lower` is frozen?
9. **Past-horizon behaviour.** Fail-closed (UNKNOWN/veto), or a mandatory re-calibration with a named owner (FQ-R28: the coordinator)?
10. **`epoch_anchor`.** It requires a v2 arming ruling. Is any pre-v2 window (for example, v1 under the 10-01 ruling) in scope? The proposal is no, because v1 is halted.
11. **Split.** Is the A1 (KILL plus floor) / A2 (guard) split acceptable? A2 has no practical effect while the design is STARVED and the forward-source registry is empty.
12. **Out of scope, flagged.** The E-25 rule 6b forward-only source registration, `market_baseline`, and the per-rung PIT spec stay with their own owners.
