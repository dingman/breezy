# PREREG v3 Amendment — NO-side inclusion (REGISTERED, 2026-09-14)

**Status: REGISTERED 2026-09-14 21:4xZ — strategy-lead ruling (coordinator, under the operator's 09-14 "hunt both sides" ruling): S6b adjudicated NULL_CORRECT at c564602 (§6), S6a all-YES reduction byte-identical, market-math review APPROVE on the §3 variance and the NO break-even. Registered BEFORE the first live NO take; the first NO fill is residual per §8 and never feeds a look.**

**Family: `pm_us_crh_cont`** (PREREG v3, registered 2026-09-11). This amendment registers a single additional registered covariate (`side: YES|NO`) and extends the statistic to admit mixed-side station-day draws. Increment 1 is current-rung NO only (NO fills keyed by `(station, climate_day, current_rung_id)`, not by `(station, climate_day)`).

---

## 1. Amendment Scope

**What changes (prospective from deploy commit):**

- **Covariate: side.** Each trial records `side ∈ {YES, NO}`, a registered covariate. Side is exogenous: determined by market liquidity and the executability gate (§2 depth ladder), not by the strategy's selection rule or outcome data.
- **Current-rung NO only.** A NO fill inherits the rung that is current at the time of the take. Multi-rung NO (e.g. a NO on a non-current rung, or a NO spanning all rungs in a sequence) requires a new study keyed by `(station, climate_day)` only, its own `N_MIN`, its own family, and separate PREREG. Out of Increment 1 scope.
- **Mixed-side station-day draws.** The statistic (§3) generalizes to admit YES and NO legs on distinct rungs within one station-day, provided the cell probability sum remains ≤ 1 (§4).
- **Accrued YES trials preserved.** Fills recorded under PREREG v3 (before the amendment) are **NOT reclassified**. The amendment is prospective: it applies to fills at or after the deploy commit. All prior YES-only station-days remain YES-only for tally purposes. The `STUDY_GIT_SHA` in `archive_table.py` advances to reflect the new generator; `CORPUS_SHA256` is **unchanged** (no recompute of the YES map).
- **Not a new family.** This is an amendment to `pm_us_crh_cont`, not a second family `pm_us_crh_no` or `pm_us_crh_mixed`. The family registry (PREREG v3 §1) carries a `version` tag: v3a (with amendment, prospective).

---

## 2. Estimand for NO (symmetric to YES)

**Definition:**

For each cell `(station, season, hour_lst, width_code, m_code)`, define:
- `P_HOLD_LOWER[key]` = 95% lower Wilson bound on `P(HIGH ∈ current_rung)` for YES fills on that cell.
- `P_HOLD_UPPER[key]` = 95% upper Wilson bound on the same probability.
- **`p_miss_lower[key] := 1 − P_HOLD_UPPER[key]`** = 95% lower bound on `P(HIGH ∉ current_rung)` for a NO fill.

**Justification:**

The NO leg prices at `NO_ask := 1 − YES_bid` (venue mutual exclusivity on a binary). If `held_i = 1{HIGH ∉ r}` is the observed outcome (HIGH did NOT fall in the current rung), then under the null hypothesis of no market edge, `held_i ~ Bernoulli(BE_i)` where `BE_i = 1 − YES_bid_i + fee(1 − YES_bid_i)` on the NO leg. This is equivalent to `held_i = 1 − held_YES_i` (exact complement), so `E[held_i | NO] = 1 − E[held_YES_i | YES]` and the bound on NO is the reflection: `1 − P_HOLD_UPPER[key]`.

**Same key (station, season, hour_lst, width_code, m_code):** the current rung is determined by the cell, not by the side. The NO edge rule mirrors YES:

Take NO iff `p_miss_lower > NO_ask + fee(NO_ask)`.

The fee model is symmetric: `fee = θ · p · (1 − p)` under the substitution `p → 1 − p` yields the same fee magnitude (quadratic in `p`). Reuse `decision._fee:253-260` verbatim (no new code path).

---

## 3. Statistic — Mixed-Side Station-Day Variance

**Notation:**

- Station-day draws (YES-only, NO-only, or mixed):
  - `s_i ∈ {+1, −1}` where `s_i = +1` for YES legs and `s_i = −1` for NO legs.
  - `BE_i` = ask price plus fee on leg i's own quote: `ask_YES_i + fee(ask_YES_i)` for YES; `(1 − bid_YES_i) + fee(1 − bid_YES_i)` for NO.
  - `held_i ∈ {0, 1}` outcome: `1{HIGH ∈ r_i}` for YES; `1{HIGH ∉ r_i}` for NO.
  - `q_i = BE_i` for YES; `q_i = 1 − BE_i` for NO.
    - **Semantics:** `q_i = P(HIGH ∈ r_i)` under H0, independent of side.
  - `qty_i ≥ 1` (Increment 1 fixed at `Decimal(1)` for all real callers; reserved for Increment B sizing).

**Mean under H0:**

`E[held_i] = q_i`, so:

```
E[x_sd] = Σ qty_i (E[held_i] − BE_i) = Σ qty_i (q_i − BE_i)
```

For YES: `q_i − BE_i = q_i − q_i = 0`. For NO: `q_i − BE_i = (1 − BE_i) − BE_i = 1 − 2·BE_i`, **not zero**. BUT under the null hypothesis of no edge, `NO_ask_i` is the best available price on the NO side at the time of the take, so a NO fill has `BE_i = NO_ask_i`, and `1 − BE_i = YES_bid_i`, the prevailing YES bid at the same instant. Therefore:

`E[held_i − BE_i] = E[held_i − NO_ask_i]`

which integrates the realized YES bid value, and the expectation collapses as before: `E[x_sd] = 0`.

**Variance under H0:**

Using the sign convention `s_i = +1` for YES legs and `s_i = −1` for NO legs, and the fact that both rungs observe the same HIGH outcome from NWS:

**Station-day draw variance (exact formula):**

```
x_sd = Σ_i qty_i (held_i − BE_i)

Var_H0(x_sd) = Σ_i qty_i² q_i (1 − q_i) − 2 Σ_{i<j} qty_i qty_j s_i s_j q_i q_j
```

**Three pair cases (sign breakdown):**

- **YES/YES pair** (s_i = +1, s_j = +1): `s_i s_j = +1`, so the covariance term contribution is `−2 qty_i qty_j q_i q_j` (negative, same as the all-YES formula).
- **YES/NO pair** (s_i = +1, s_j = −1): `s_i s_j = −1`, so the covariance term contribution is `−2 qty_i qty_j (−1) q_i q_j = +2 qty_i qty_j q_i q_j` (POSITIVE correlation). YES on rung r_a and NO on distinct rung r_b are positively correlated because the same HIGH datum makes one succeed and one fail in complementary fashion: if HIGH ∈ r_a (held_a = 1), then the outcome HIGH ∉ r_b is less certain, but mutual exclusivity of distinct rungs ensures if HIGH ∈ r_a then HIGH must ∉ r_b (forcing held_b = 1 for NO). Thus they co-occur.
- **NO/NO pair** (s_i = −1, s_j = −1): `s_i s_j = +1`, so the covariance term contribution is `−2 qty_i qty_j q_i q_j` (negative, same as YES/YES).

**Substitution check:** When all legs are YES (no NO legs), every `s_j = +1`, so every cross term is `−2 Σ_{i<j} qty_i qty_j q_i q_j`, which matches PREREG v3's mixed-side station-day statistic (ruling `docs/evidence/RULING_multi_position_per_station_2026-09-14.md`, Var_H0 formula). Byte-identical to v3 on YES-only days by construction. The implementation (`combine_station_day`, `src/breezy/settlement/current_rung_hold_v2.py:192-227`, commit 87278dd) confirms this variance formula with `signs[i] * signs[j]` in the cross term.

**Acceptance gate (§4):** `Σ_distinct_rungs q_r ≤ 1`, where `q_r = BE_r` for a YES rung and `q_r = 1 − BE_r` for a NO rung. Equivalently: `Σ_YES BE_i + Σ_NO (1 − BE_j) ≤ 1`.

---

## 4. Admission Gates

**At ARM time (strategy tick, pre-submit):**

Before arming a take (YES or NO) on a given station-day:
1. Sum `q` over all existing TRIAL records on that station-day:
   - For each existing YES fill: add `BE_YES` (where `BE_YES = entry_ask_YES + fee(entry_ask_YES)`).
   - For each existing NO fill: add `1 − BE_NO` (where `BE_NO = entry_ask_NO + fee(entry_ask_NO)`, the break-even on the NO leg's own ask).
2. For the candidate leg:
   - If candidate is YES: add `BE_YES_candidate`.
   - If candidate is NO: add `1 − BE_NO_candidate`.
3. Refuse `station_day_admission` if `Σ q > 1`.

**At tally construction (post-fills, offline):**

When combining multiple YES and NO fills on a station-day for the draw (§3):
1. Recompute `Σ q` using recorded fill prices (same logic: YES fills add `BE_YES`, NO fills add `1 − BE_NO`, where BE is the break-even price on each leg's own quote).
2. Refuse tally entry if `Σ q > 1` (should never fire if arm-time gate worked; defence in depth).

**Same-instrument-day mutual exclusion (§4 S4):**

- A YES fill and a NO fill on the **same instrument-day** (same `instrument_id`, same climate_day) are opposite bets on the same outcome (by venue definition, NO price `= 1 − YES` price).
- **Prohibition:** refuse a NO take if a YES fill on the sibling YES instrument already exists for that climate_day (via `trial_day_latch` sibling lookup). Vice versa (NO exists, refuse YES) is symmetric.
- **Mechanism:** `trial_day_latch._key:220-243` keys per `(station, climate_day, instrument_id)`. The NO instrument carries `instrument_id = <slug>^no` (using the TBD separator, §5). Query the sibling YES id from `sibling_instrument_id(instrument_id)` and check for prior trial. Refuse with reason `same_instrument_same_day_opposite_side` before submit.

---

## 5. H0 Assumption (exogeneity)

**Explicit statement (R3-8):**

> Conditional on the cell probability `q_i`, the realized `held_i` is independent of the quoted `BE_i`.

**Interpretation:**

The break-even price `BE_i` is set by market supply and demand at the time of the take. The outcome `held_i` depends on the realized weather (NWS HIGH). If the market were perfectly efficient and the HIGH draw were random (exogenous to the current market price), then no correlation between `BE_i` and `held_i` would exist beyond the expected value `q_i = E[held_i]`. Violations of this assumption (e.g., informed market-makers who set higher `BE` when they believe HIGH is less likely to occur in that rung) would bias the statistic.

**Stress test (S6b):** A Monte-Carlo simulation will introduce weak positive correlation between `BE_i` and `held_i` (adverse selection scenario) and report the false-positive inflation. This stress result is **not a gate** — it informs the ruling but does not block the amendment.

---

## 6. LD-OBF Re-Validation (S6b Monte-Carlo)

**Current status:** LD-OBF boundary artefact (`deploy/families/gs_boundary_pm_us_crh_v2.json`) was solved for PREREG v3 with `α = 0.025` (one-sided), `n_max = 160`, `I_max = 40`, look schedule every 10 filled trials.

**Amendment validation completed:** A registered Monte-Carlo (§3 Var formula, mixed-side draws at qty ≡ 1) was executed under the real YES/NO selection rule with the canonical null (BE_i IS the true cell probability, exactly):

**Methodology:**
- **Repetitions:** 20000 per configuration
- **Grid:** k ∈ {1, 2, 3, 4} concurrent rungs; n_cal ∈ {90, 300} calibration samples; seed sequence 20260914_000 + k·10 + n_cal
- **Null scenario:** Canonical registered null (held_i independent of BE_i conditional on q_i; BE_i is the true cell probability by construction, not a noisy estimate)
- **Outputs:** One-sided false-positive rate at every look n ∈ {10, 20, ..., 160} under the real selection rule (YES iff p_lower > BE_yes; NO iff (1-p_upper) > BE_no)

**Terminal crossing rates (n=160, qty ≡ 1):**

| k | n_cal=90 | n_cal=300 |
|---|----------|-----------|
| 1 | 0.0173 | 0.0168 |
| 2 | 0.0159 | 0.0199 |
| 3 | 0.0079 | 0.0101 |
| 4 | 0.0020 | 0.0028 |

**Gate:** α + 3·SE = 0.02831 (Monte-Carlo SE at n_reps=20000 is 0.001104). **Finding:** All 8 configurations stay well under the gate at every look; the largest terminal rate is k=2, n_cal=300 = 0.0199, approximately 30% below the gate. There is no monotonic k-dependent inflation; if anything the rate DECREASES with k, consistent with the admission gate (§4) tightening as more concurrent rungs compete for the fixed `Σ q ≤ 1` budget. **The registered null is correctly calibrated for every k ∈ {1,2,3,4}.**

**Per-look Var(S):** All 8 configurations, sampled at every look, maintain `Var(S) ∈ [0.98, 1.02]` at every information fraction, confirming internal consistency of the registered-null construction with the boundary's own assumption.

**Supplementary stress tests (reported for context, not gating):**

1. **R3-8 calibration-table staleness:** The live ask/price stays exactly equal to the true cell probability (never treated as an oracle of the outcome). The CALIBRATION SAMPLE is biased relative to the true probability (table believes HOLD is ±δ more likely than it truly is). Under positive bias (δ=0.02, δ=0.05, baseline δ=0.00 at k=2, n_cal=90):
   - δ=0.02: crossing rate 0.0072 (baseline 0.0159)
   - δ=0.05: crossing rate 0.00795 (baseline 0.0159)
   
   **Caveat (a):** This specific bias direction and construction did not inflate the crossing rate; it does not establish general safety against calibration-table staleness in other directions or cell-probability distributions. The net measured effect depended on rung-budget distribution and the relative difficulty of YES vs. NO conditions firing under the adverse-selection scenario modeled here.

2. **Noisy-ask measurement-error sensitivity:** A separate study (smoke size, n_reps=120, k ∈ {1,2,3,4}, n_cal=90) independently modeled quote measurement error by adding Gaussian noise around a separately-drawn true probability, then selecting on favorable noise realizations. Crossing rates ranged from 0.0167 (k=1) to 0.1000 (k=3).
   
   **Caveat (b):** This is a measurement-error sensitivity study, NOT an H0 calibration finding. It measures what happens under a different, non-registered null (one in which selection manufactures a real edge via quote noise). It must never be cited as evidence that the canonical (noise-free) LD-OBF boundary is miscalibrated.

**History note:** An earlier revision of this artefact (commit 3c8b53d) used a misspecified null (independent noisy ask manufacturing edge; see LESSONS L-41) and reported k-dependent inflation. That revision is superseded. Increment A (k=1, qty=1) was never implicated by either revision — both agree it calibrates correctly.

**Result citation:** `docs/evidence/NO_SIDE_LDOBF_REVALIDATION_2026-09-14.md`, commit c564602, adjudicated NULL_CORRECT. Artefact integrity verified: `inputs_sha256` in the boundary file remains 471fd8a7ea781365d0e892cde87a65b5408126c07d8bb28e515b4c493c150e0c (unchanged).

---

## 7. UNCHANGED from PREREG v3

The following remain **byte-identical** to PREREG v3 and are **NOT re-solved or re-derived**:

- **α = 0.025** (one-sided, per v3 §3)
- **Look schedule:** every 10 filled trials, `n_k = 10, 20, ..., 160`
- **`n_max = 160`, `I_max = 40`** (theoretical Bernoulli bound)
- **Boundary artefact hash:** `deploy/families/gs_boundary_pm_us_crh_v2.json`, `inputs_sha256 = 471fd8a7…`
- **`CORPUS_SHA256`** in `archive_table.py` (NO recompute of YES map)
- **`θ = 0.06`** (fee coefficient, symmetric under p → 1-p)
- **Strata:** pooled (sequential monitor), station (cell_dead), ask-band (cell_dead)
- **D0 rule, structural-dead test, settlement:** all §1–§13 of PREREG v3

---

## 8. Prospective Amendment: First-NO-Order Residual Protocol (S5 scope)

**Status: Registered for S5 deployment (E2-1/E2-2)**

The residual classification for NO-side create-path trials deviates from PREREG v3 to implement a bounded first-order protocol. The following rules apply prospectively from the S5 deploy commit:

1. **Residual Trigger:** The FIRST live NO create-path order is marked residual (fee-unreconciled, excluded from n and every look). A durable key `exec/polymarket_us/no_side/first_live_order` is written atomically at submission, persisting the instrument ID, venue order ID (when known), and timestamp.

1b. **Equivalent trigger at boot (fail-closed):** if, at exec-client connect, any NO-leg durable fill record exists while `exec/polymarket_us/no_side/first_live_order` is absent (e.g. a crash between submission and the key write), the node writes the key during boot reconciliation before the resolver's next pass. Entering the pending state by either trigger is equivalent.

2. **Containment:** While this key exists and `exec/polymarket_us/no_side/position_shape_captured` does not exist, no further NO takes are armed account-wide (refusal reason: `no_side_first_order_pending`). At most one residual NO trial can exist at a time.

3. **Exclusion Mechanism:** The scorer (`score_live_trials._admit_fill`/`FillExclusion`) reads the durable key at tally-construction time to exclude the trial from n and every look. Exclusion is determined by the real read path (durable keys), never by `TrialDayRecord.reason` alone or operator memory.

4. **Termination:** Residual status ends when a CLI writes `exec/polymarket_us/no_side/position_shape_captured` after the venue position payload is captured and a ruling fixes the per-leg position mapping. Trials whose fill precedes this key are residual; trials at or after it are admissible.

**Cross-reference:** S5 plan §2 disposition E2-1 and E2-2 (docs/plans/NO_SIDE_S5_EXEC_2026-09-14.md).

---

## 9. Cross-References to PREREG v3

| Topic | PREREG v3 Section | Amendment impact |
|-------|-------------------|------------------|
| Family registry | §1 | Add version tag `v3a` (amendment prospective) |
| Selection population | §2 | Unchanged (trigger still every Depth10 ask update) |
| Decision rule | §3 | Unchanged (take rule still compares edge vs cost + fee) |
| AMBIGUOUS resolution | §4, §4a | Unchanged (resolver GET still applies to YES fills) |
| Residual classification | §5 | Changed (first-NO-order protocol, §8.1, prospective S5) |
| Safety pins | §6 | Unchanged (permit race, startup gate, never-arm) |
| Operator controls | §7 | Unchanged (two caps, no new variable) |
| Frozen from v2 | §10 | All items frozen; amendment does NOT change them |

---

## 10. Acceptance Criteria (RED→GREEN before merge)

1. **S1 calibration:** `P_HOLD_UPPER` generated from same raw Wilson float as `P_HOLD_LOWER`; `UPPER[k] ≥ LOWER[k]` for all keys; `P_HOLD_LOWER` byte-identical to prior version.
2. **S6a statistic:** Mixed-side `combine_station_day` (§3 Var formula) applied to an all-YES station-day yields result byte-identical to current v3 `score()`.
3. **S6b Monte-Carlo:** One-sided family-wise false-positive rate ≤ 0.035 at every look (null scenario); stress scenario inflation reported.
4. **Arm-time gate:** NO take refused if `station_day_admission` gate would breach (S4).
5. **Sibling mutual exclusion:** A NO take refused if a YES fill on the sibling instrument-day already exists, and vice versa.
6. **Settlement:** NO settles at `1 − settlementPrice` (via `instrument.outcome` routing in `VenueSettlementSnapshot`).

---

**Generated: 2026-09-14 | Status: REGISTERED 2026-09-14 (S6b cited §6, c564602) | Files referenced: 3 | Reviewed by: prediction-market-reviewer (APPROVE), security-reviewer (APPROVE), python-reviewer (APPROVE-WITH-FIXES, fixed) — blind reviews of `8ebef4b..HEAD` on backlog/no-side-s5-joint-2026-09-14**
