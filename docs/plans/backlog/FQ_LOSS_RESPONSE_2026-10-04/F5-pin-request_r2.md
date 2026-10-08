# F5 pin request r2: KILL constants (A0), the F6 loss-stop floor (A1), and the F7b guard (A2)

<!-- planner, 2026-10-08. r2 of F5-pin-request_r1.md. It applies defect fixes M1–M11 and the coordinator rulings Q1–Q12 in F5-pin-request_r1-review-merge.md. Checked against HEAD 6acf4eee. No Monte Carlo was run for this document. Operator-reserved controls (the per-position cap and the daily budget) are neither named by their environment-variable names nor assigned. No frozen PREREG is edited. No checker or test is weakened. -->

## 0. Summary
- **The parent design stays byte-unchanged.** `F5_prereg_v2_design.json` is frozen at `072ab026cdc790dd6e9a51d62d8164766b85fd82`. M1-v3 and every other frozen PREREG are also untouched.
- **The pins go into three additive amendment files.** Each is frozen once and merges on its own (M5, Q11):

| File | Payload key | Status | Unblocks |
|---|---|---|---|
| `F5_prereg_v2_amendment_A0.json` | `kill` | **Freeze-ready now.** The exact body is in §3.1. | Makes KILL a pre-registered fact |
| `F5_prereg_v2_amendment_A1.json` | `loss_stop_floor` | BLOCKED on the floor MC and its M2 gate (§4) | F6b |
| `F5_prereg_v2_amendment_A2.json` | `guard` | BLOCKED on the guard MC (§5) | E-25 6b forward-source registration |

- **A sibling checker validates the amendments.** `scripts/analysis/prereg_amendment_check.py` reuses `validate_defects`, `check_frozen_blob` and `check_not_refrozen` by import (M1, M6). The parent checker and its tests stay byte-unchanged.
- **The floor is likely reachable only as a gross-loss tripwire (plain statement).** This applies in a YES-longshot regime with about 24 takes before 2027-01-25:
  - planning arithmetic, not evidence (§4.5), puts its power at the mirrored edge −0.16 near 0.3;
  - with high-priced NO legs it is reachable after one or two losses, but single unlucky days then dominate its false-stop rate;
  - the M2 gate decides;
  - if the gate fails, §4.5 gives the fail-closed alternative. No dead stop is ever frozen.

## 1. Binding lessons, and the facts verified for this request

### 1.1 Lessons (each header was re-read in `docs/core/LESSONS.md`)
| Lesson | Line | What it requires here |
|---|---|---|
| L-12 | :620 | Widen exact-set barriers, never relax them. `REQUIRED_KEYS`/`_ALLOWED` (`prereg_precommit_check.py:81-111`) are untouched; each amendment gets its own exact key set. |
| L-34 | :1296 | Each pin freezes before any evidence it governs exists (§6). |
| L-38 | :1354 | A stop that cannot fire is MISSING. Hence the M2 gate (§4.4) and the F6b positive control (§4.8). |
| L-39 | :1368 | The reserved controls are never named by their env-var names. This doc and every amendment must grep to 0 before the gate runs. |
| L-40 (+ 09-25 amendment) | :1382, :1396 | Use the exact mutual-exclusivity variance per station-day. On a mixed-side day the variance is `S − (q_y − q_n)²`, whose maximum is 1, not 1/4. Qty > 1 de-calibrates. |
| L-41 | :1405 | The MC null is the registered H0 verbatim. Any deviation is a separately labelled sensitivity row. |

### 1.2 Venue facts for M4, taken from code
`docs/core/LESSONS.md` has **no** lesson for either fact: grepping for BUY_SHORT, "short YES", "NO buy" and "NO holding" returns 0 hits. The authority is the code and its cited evidence.

**Fact 1: the venue represents a NO buy as SELL / BUY_SHORT on the YES slug.**
- `src/breezy/adapters/polymarket_us/leg_prices.py:14-18`: a NO-outcome order echoes `ORDER_INTENT_BUY_SHORT` and `ORDER_SIDE_SELL`. Evidence: `NO_SIDE_PREVIEW_20260914T170654Z.json`.
- `leg_prices.py:39-46`: the declared tables `VENUE_SIDE_FOR_LEG` and `VENUE_INTENT_FOR_LEG`.
- `src/breezy/adapters/polymarket_us/parsing.py:277-280`: the echo lands as `SELLER`, and the intent is deliberately not consulted.

**Fact 2: the venue nets a NO holding as short YES.**
- `src/breezy/persistence/autonomy/net_position.py:5-6, :18-23` gives the signs YES BUY +q, YES SELL −q, NO BUY −q, NO SELL +q. Any other leg/side raises `UnknownSide`.
- `src/breezy/analysis/labeling/fill_source.py:85-100`: the durable record stores a NO buy as `BUY` on the **NO-leg instrument**, and the sign comes from the leg.
- `src/breezy/analysis/labeling/label_run.py:271`: same convention.

**Fill ledger.** `DurableFillRecord` (`src/breezy/adapters/polymarket_us/exec/client.py:922-958`) stores values cumulative per venue order:
- `cumulative_qty`, `cumulative_cost` and `cumulative_fee`;
- `fee_reconciled: bool` (:956);
- a SELL record nets against the longs (a partial exit).

**C2 cash records.** `src/breezy/analysis/labeling/reconcile.py:642-754` (`cash_records`, `_exit_record` :681-694, `_entry_records` :697-754, `_lot_fraction` :620) already produces:
- settlement payouts;
- exit proceeds net of fee;
- YES/NO `netting_offset` records for paired quantity.

### 1.3 Amendment machinery, verified
**`check_not_refrozen`** (`scripts/analysis/multisource_blend_pin_guards.py:200-229`, PIN-R8b):
- It refuses a file whose git history holds more than one distinct (non-UNFROZEN stamp, body) state (`_freeze_content` :185-197, `_file_chain` :150-182).
- It refuses a shallow clone (:212-217).
- It raises `Refusal` from `scripts/analysis/multisource_blend_refusal` (:32). It does not return a `Defect`.
- `UNFROZEN` is defined at :42.

**`load_verified_prereg`** (`scripts/analysis/multisource_blend_skill.py:274-297`), the F13 loader, runs in this order:
1. refuse `frozen_sha == UNFROZEN` (:282-285);
2. `check_frozen_blob` (:286-288);
3. `check_not_refrozen` (:289);
4. required pins and value checks (:290-296).

It is hard-bound to F13's `REQUIRED_PINS` (:125-151), so it cannot be called for F5. r2 reuses its **pattern**, not the function (§2.4).

**Canonical JSON form.** There is exactly one form in use, written twice:
- `prereg_precommit_check._canonical` (:323-326): the body without `frozen_sha`, `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=True)`;
- byte-identically, `multisource_blend_skill._canonical` (:190-192), whose public digest is `content_digest` (:195-197).

r2 adds no third form (M7).

**`check_frozen_blob`** (`prereg_precommit_check.py:340-369`):
- requires a 40-hex sha (`"UNFROZEN"` fails `BAD_frozen_sha` at :343-344);
- requires the sha to be a commit that is an ancestor of HEAD (:351-356);
- requires canonical equality with `git show <sha>:<path>` (:367-368).

It works on any JSON object at any path, so it applies to amendments unchanged.

**`MAX_LAMBDA`** has three definitions:
- `prereg_precommit_check.py:73` = 0.5, the E-25 ceiling for `lambda_max`/`mu_max` (:208-209);
- `scripts/analysis/fq_mc_eprocess.py:26` = 0.5, used as the KILL cap in the MC (:166) and as `lam_max` in the MC's `kill_first_n` (:236);
- production's KILL cap is `KILL_MAX_LAMBDA` (`src/breezy/analysis/autonomy/confidence_sequence.py:59`), which is not in `__all__` (:46-56).

**Parent exports.** `__all__` (`prereg_precommit_check.py:60-68`) exports `Defect`, `check_frozen_blob`, `load_design`, `validate_defects` and `REQUIRED_KEYS`.

## 2. Amendment mechanics (shared by A0, A1 and A2)

### 2.1 Files and envelope
Path: `docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F5_prereg_v2_amendment_<A0|A1|A2>.json`.

The **envelope keys** are `frozen_sha`, `amendment_id`, `amends` and `provenance`. They are exempt from the overlap rule (M5).
- `amends` has exactly the keys `{path, frozen_sha}`, and they name the parent.
- **`amends.content_sha256` is dropped (M7).** The git blob at (`amends.path`, `amends.frozen_sha`) is immutable, and the checker re-proves that the working parent equals it through `check_frozen_blob`. A digest field would add a value that has to be computed and hand-carried, and a third copy of the canonical form.
- The per-file content-digest pin that M1 asks for is a **test** that uses the existing `content_digest` (§2.5). It is not an envelope field.

**Exact payload key per amendment:**

| `amendment_id` | Exact top-level key set |
|---|---|
| `F5_prereg_v2_A0_kill` | envelope ∪ {`kill`} |
| `F5_prereg_v2_A1_floor` | envelope ∪ {`loss_stop_floor`} |
| `F5_prereg_v2_A2_guard` | envelope ∪ {`guard`, `guard_basis`} |

**Additive rule.** Every non-envelope key, at the top level and nested one level down, must be disjoint from:
- the parent's keys;
- every key of every earlier-ordered amendment (A0 < A1 < A2).

This makes the fee/KILL naming hazard structural. The parent's `theta` (`F5_prereg_v2_design.json:35`) is the fee coefficient 0.0695, so no payload may define `theta`. `kill_hedge_theta` is dropped (M7). θ = 1/2 is implicit in `kill_bar_rule`, which is kept.

### 2.2 Sibling checker `scripts/analysis/prereg_amendment_check.py` (new; M6)
Usage: `prereg_amendment_check.py <amendment.json>`. Exit codes match the parent (`prereg_precommit_check.py:379-398`): 0 OK, 1 defects, 2 usage/load error.

It imports:
- `Defect`, `load_design`, `validate_defects` and `check_frozen_blob` from `scripts.analysis.prereg_precommit_check`;
- `check_not_refrozen` from `scripts.analysis.multisource_blend_pin_guards`;
- `Refusal` from `scripts.analysis.multisource_blend_refusal`.

A raised `Refusal` is converted to `Defect("REFROZEN" | "FREEZE_HISTORY_UNKNOWN", str(exc))`. Nothing is re-implemented (M1).

| Rule | Check |
|---|---|
| R1 parent | `load_design(amends.path)`; `validate_defects(parent) == []`; `check_frozen_blob(parent_path, parent) == []`; `check_not_refrozen(parent_path)` does not raise; `parent["frozen_sha"] == amends.frozen_sha`. |
| R2 envelope | Exact top-level key set for the `amendment_id` (§2.1); `amends` keys exactly {path, frozen_sha}. |
| R3 additive | The overlap rule of §2.1, with envelope keys exempt (M5). |
| R4 freeze | `check_frozen_blob(amendment_path, amendment) == []` (this also rejects UNFROZEN); `check_not_refrozen(amendment_path)` does not raise. |
| R5 payload | A0: §3.2. A1: §4.7. A2: §5.4. |

- With `--draft`, R4 is replaced by "`frozen_sha` == UNFROZEN". This is the pre-freeze readiness check. The tool never reports a draft as frozen: `--draft` exits 0 only for UNFROZEN files.
- `prereg_precommit_check.py` and `tests/unit/test_prereg_precommit_check.py` stay byte-unchanged. This is checked at review with `git diff --stat` on both paths.

### 2.3 Why `check_not_refrozen` is imported from an F13 module
- **Benefit:** it is the only PIN-R8b implementation (DRY).
- **Cost:** the F5 checker now depends on `multisource_blend_pin_guards`. Moving it to a shared module would edit F13 code, so that refactor is out of scope.
- **Mitigation:** the import is covered by the planted-defect tests in §2.5.

### 2.4 Consumer loader `load_verified_amendment(path, amendment_id)` (in the sibling module; M1)
It follows the `load_verified_prereg` pattern (`multisource_blend_skill.py:274-297`) step for step:
1. read the JSON, else `Refusal`;
2. refuse `frozen_sha == UNFROZEN`;
3. run R1–R5;
4. return the mapping.

Consumers:
- **Analysis scripts and tests** (the MCs and the pin tests) load amendments only through this function.
- **Production modules** never run git at runtime. They carry module constants that a test pins equal to the frozen amendment, loaded through this function. The precedent is `STALE_PARITY_H`, `loss_stop_probe.py:67-69`.

A pin test therefore stays RED until its amendment is frozen. That ordering is correct.

### 2.5 Shared tests (ADD only; `tests/unit/test_prereg_amendment_check.py`)
- `test_unfrozen_amendment_is_refused_by_loader`
- `test_amendment_exits_0_when_frozen_once` (temporary git repo fixture: freeze commit, then stamp commit)
- Planted-defect tests, one each:
  - parent body edited;
  - parent sha not an ancestor of HEAD;
  - parent re-frozen (two stamps);
  - amendment re-frozen;
  - edit after the stamp;
  - shallow clone;
  - unknown top-level key;
  - payload key equal to a parent key (`theta`);
  - payload key equal to an A0 key inside A1;
  - `amends` with an extra key.
- `test_envelope_keys_exempt_from_overlap`
- `test_<id>_content_digest_pinned`, PIN-R8(c)-style, one per file: `content_digest(amendment)` from `multisource_blend_skill.py:195-197` equals a literal recorded in the stamp commit's test.

## 3. A0: KILL constants (freeze-ready now)

### 3.1 Exact proposed body of `F5_prereg_v2_amendment_A0.json`
```json
{
  "frozen_sha": "UNFROZEN",
  "amendment_id": "F5_prereg_v2_A0_kill",
  "amends": {
    "path": "docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F5_prereg_v2_design.json",
    "frozen_sha": "072ab026cdc790dd6e9a51d62d8164766b85fd82"
  },
  "kill": {
    "kill_grid_points": 5,
    "kill_grid_span": "m_j = x_max * j / (kill_grid_points - 1) for j = 0..kill_grid_points-1 (numpy linspace(0, x_max, kill_grid_points)); x_max is the parent's",
    "kill_lambda_max": 0.5,
    "kill_min_range": 0.5,
    "kill_var_floor": 1e-06,
    "kill_prior_pseudo_days": 1,
    "kill_prior_second_moment": 0.25,
    "kill_lambda_cap_rule": "cap(m) = min(kill_lambda_max, 0.5 / max(x_max - m, kill_min_range))",
    "kill_betting_rule": "minus-side agrapa at day d and grid point m: n = d + kill_prior_pseudo_days; mu = sum_y / n; m2 = (sum_y2 + kill_prior_pseudo_days * kill_prior_second_moment) / n; var = max(m2 - mu^2, kill_var_floor); lam = clip((m - mu) / (var + (m - mu)^2), 0, cap(m)); sum_y and sum_y2 run over settled days strictly before d; log-capital increment = log1p(-lam * (y_d - m)); y_d is the clipped, haircut-BE Y_d on the parent's m_cap denominator",
    "kill_bar_rule": "bar = log(2 / alpha_kill) with the parent's alpha_kill (hedge weight 1/2); KILL iff every grid log-capital >= bar at a look with n_cum >= the parent's earliest_look_n; a same-day PASS and KILL is FAIL"
  },
  "provenance": {
    "production_module": "src/breezy/analysis/autonomy/confidence_sequence.py",
    "mc_module": "scripts/analysis/fq_mc_eprocess.py",
    "mc_evidence": "docs/evidence/f5/fq_resume_n_mc_seed20261006.json",
    "mc_seed": 20261006,
    "kill_power_report": {
      "path": "docs/evidence/f5/fq_kill_power_negative_edge_seed20261008.json",
      "seed": 20261008,
      "edges": [-0.04, -0.08, -0.16],
      "role": "reporting_only_changes_no_constant"
    }
  }
}
```
- The coordinator confirms seed 20261008 before the freeze commit. It follows the 20261006 convention, and it is a pre-registration of the M10 run, which happens after the freeze.
- No other value is open.

**Where each value comes from (verified):**

| Key | Production | MC |
|---|---|---|
| grid points 5 | `confidence_sequence.py:58`, `kill_grid` :74-79 | `fq_mc_eprocess.py:38`, `_kill_grid` :153-154 |
| λ max 0.5 | :59, `_lambda_cap` :82-83 | :26, used at :166 |
| min range 0.5 | `_MIN_RANGE` :63 | literal at :166 |
| var floor 1e-6 | `_VAR_FLOOR` :62 | literal at :164 |
| prior 1 / 0.25 | :60-61, `_bet_fraction` :86-94 | :41, :44, used at :161-163 |
| bar | `kill_bar` :66-71, `kill_crossed` :115-117, `kill_first_n` :120-135 | :201, :221 |
| same-day PASS + KILL = FAIL | `evaluators/forecast_quantile_ladder.py:296-298` | — |

**Two constants are inert at the pinned design** (stated so nobody reads them as load-bearing). They are pinned for rule identity, per Q4:
- `kill_min_range` changes nothing while it is ≤ 1, because the cap is then ≤ 0.5 anyway. Its job is to guard the division at m = x_max.
- `kill_var_floor` cannot bind in practice. For a constant stream the prior pseudo-day already keeps var ≥ 0.25/(d+1).

### 3.2 A0 payload rule (R5): compare by import, never by retyping (M7)
- `kill_grid_points == confidence_sequence.KILL_GRID_POINTS == fq_mc_eprocess.KILL_GRID_POINTS`
- `kill_lambda_max == confidence_sequence.KILL_MAX_LAMBDA == fq_mc_eprocess.MAX_LAMBDA`, and `<= prereg_precommit_check.MAX_LAMBDA` (the E-25 ceiling)
- `kill_prior_pseudo_days == confidence_sequence.PRIOR_PSEUDO_DAYS == fq_mc_eprocess.PRIOR_PSEUDO_DAYS`; the same for the second moment
- `kill_min_range == confidence_sequence._MIN_RANGE` and `kill_var_floor == confidence_sequence._VAR_FLOOR`
  - These are read-only imports of private names, a documented exception.
  - Promoting them to public would edit the KILL module. It stays byte-unchanged.
- The `*_rule` strings are compared to nothing in code. The freeze is what pins them, and the 1e-12 reference test (`tests/unit/autonomy/test_confidence_sequence.py:57-75`) pins behaviour.
- The checker contains no numeric literal for any KILL constant.

### 3.3 A0 tests (ADD)
- `test_kill_constants_equal_a0_production_and_mc` (imports only).
- `test_mc_kill_increment_literals_equal_production_constants`: an AST read of `fq_mc_eprocess._kill_increment` (:157-169). It extracts the 1e-6 and 0.5 literals and compares them to `_VAR_FLOOR`/`_MIN_RANGE`. Both sides are read from code; nothing is retyped.
- `test_a0_payload_keys_disjoint_from_parent` (this includes `theta`).
- `test_F5_prereg_v2_A0_kill_content_digest_pinned`.
- **Existing tests stay unchanged:** `test_kill_constants_are_the_mc_constants` (:41-47) and the reference-vector test (:57-75).

### 3.4 M10: KILL power at negative edges (reporting only, after the freeze)
New script `scripts/analysis/fq_kill_power_report.py`:
- **Design:** the frozen one (m_cap 2, x_max 4.0, α_kill 0.05, earliest_look_n 20), loaded through `load_verified_amendment` for A0.
- **Outcomes:** h ~ Bernoulli(clamp(BE + δ, 0, 1)) for δ ∈ {−0.04, −0.08, −0.16}.
  - The existing MC alternative `min(1, be + delta_h)` (`fq_mc_eprocess.py:113-114`) has **no lower clamp**. A negative δ below BE = δ would produce a negative probability.
  - The report script therefore clamps itself. The MC module is not edited, because its as-run state backs the frozen power table.
- **Engine:** KILL via the MC's `kill_first_n` (:226-241).
- **Reported values:** `p_kill_by_kill_date`, `p_kill_by_n_max` and the median n at KILL, per δ, with SE.
- **Anchor:** the existing row `clipped_mean_y −0.019 → p_kill_under_null_stream 0.0025` (`fq_resume_n_mc_seed20261006.json:3260-3262`) is the low-edge anchor that M10 calls unmeasured.
- **Output:** the A0 provenance path.
- It changes no constant, so it is not a re-pin (L-34).

## 4. A1: the F6 loss-stop floor

The spec, as quoted in r1 §2.3 (that source was not re-verified here): time-uniform −c·√t, with a stated horizon; venue-level; anchored at the arming ruling; never derived from either cap. The rulings applied:
- Q5: α_floor = 0.10, subject to the M2 gate;
- Q6: t = settled station-days, with standardised bundle increments;
- Q7: qty ≡ 1 per contract;
- Q8: horizon 2027-01-25, in days;
- Q9: past the horizon, fail-closed;
- Q10: the anchor is the v2 arming timestamp, with no pre-v2 window.

### 4.1 S_t, defined end to end (M9, M4, M11)
For each settled station-day d after the epoch anchor (FQ v2 family, venue-level, no pre-epoch `family_id`):

1. **Fills.** All `DurableFillRecord`s of the family's orders whose instrument settles on (station, climate_day d).
   - The leg comes from the instrument (`fill_source.leg_fill_of`, :85-100), never from the venue echo.
   - A NO buy is stored as BUY on the NO-leg instrument, and its price is the NO price. The wire price 1 − X (`leg_prices.py:56-60`) is never used.
   - The same-slug net is `net_signed_qty`. A same-rung YES+NO pair is flat, as the venue nets it (`net_position.py:5-6`).
2. **Net first.** Paired same-rung YES/NO quantity becomes the `netting_offset` the C2 ledger already forms (`reconcile.py:714-733`).
   - It is deterministic. It is excluded from the random bundle and reported in the artefact's diagnostic dollars.
   - Only the unpaired remainder enters step 3.
   - This keeps step 4's `combine_station_day` free of its same-rung opposite-side refusal (`settlement/current_rung_hold_v2.py:266-271`).
3. **Per-contract legs (qty ≡ 1).** For each (rung, leg) with an open BUY quantity, one leg is formed:
   - `BE = Σ(cumulative_cost + cumulative_fee) / Σ cumulative_qty` over that leg's BUY records. This is the **ledger** fee, so θ never enters (M9). It is also how the record's docstring says to average (`client.py:941-943`).
   - Multi-contract orders and partial fills are already cumulative per venue order (`client.py:931-937`). Summing records covers re-entries.
   - **Fail closed:** if any record has `fee_reconciled == False` or a missing fee, the producer refuses (§4.6, refusal channel).
4. **Bundle.** For the legs, `combine_station_day` (`settlement/current_rung_hold_v2.py:296`) gives the realised `x_d = Σ(h_i − BE_i)` and the exact `Var_H0` (`CombinedDraw` :193-221), with sides handled per L-40 and its amendment.
   - If it raises `StationDayAdmissionRefusal` for Σq > 1 (:182-190), the day is **not dropped**: that would silently discard real losses. Its variance comes from the M3 joint (§4.2), and x_d stays realised.
5. **Realised outcomes come from the venue.** `h_i` is the venue's settlement, read from the C2 cash records (`reconcile.cash_records` :642-678). It is never a Breezy-computed NWS truth.
6. **Exits (the c96c7f4 seam).** For a leg with exited fraction f (the complement of `_lot_fraction`, :620): `h_eff = (1 − f)·h + f·v`, where v is the per-contract net exit proceeds (`_exit_record` :681-694).
   - The variance stays the unexited Bernoulli value. That overstates σ, which is conservative for Type-I.
7. **Voids.** A voided leg contributes 0 to x_d and 0 to the variance. A day with every leg void, or with σ_d = 0, is not a clock tick.
8. **Clock.** `Z_d = x_d / σ_d`, `S_t = Σ_{d ≤ t} Z_d`, and t counts the ticks.
   - The null mean is **not** subtracted. Realised overround and fee bleed stay in S_t.
9. **Rule.** FAIL iff `S_t < −c·√t` for some t in [t_min, t_at_horizon]. t_at_horizon is the last tick whose climate day is ≤ 2027-01-25.
   - Past the horizon the producer writes no PASS and the probe vetoes (Q9). The coordinator owns recalibration.
10. **Restart (M11).**
    - A FAIL is terminal for its epoch: the producer keeps writing FAIL and never flips back.
    - A re-arm needs a new arming ruling. That ruling defines a new epoch anchor, and S_t restarts at 0 from it.
    - Producer re-runs and node restarts reset nothing, because S_t is recomputed statelessly from the ledger each run.

### 4.2 The H0 bundle joint, including overround (M3)
- **Joint.** On one station-day, the touched rungs carry the H0 masses `q_r = BE_r` (YES leg) or `1 − BE_r` (NO leg), per `_cell_probability` (:223-225). The outcome is R ~ Categorical(q_r over touched rungs, plus "other" with 1 − Σq). Then YES r wins iff R = r, and NO r wins iff R ≠ r.
- **Feasible (Σq ≤ 1).** The joint is exact, and its variance is `combine_station_day`'s formula (L-40).
- **Overround (Σq > 1).** No joint with exact marginals exists. The rule is a **YES-first shrink**:
  - NO masses are kept exact, so every NO leg's drift is 0;
  - YES masses are scaled by `κ = (1 − Σ_NO q) / Σ_YES q`, so every YES leg's win probability is ≤ its BE and its drift is ≤ 0.
- **Direction.** With every leg's drift ≤ 0, false crossings below the boundary are more likely during calibration. The calibrated c is therefore ≥ the c of any feasible zero-drift null, which makes it **conservative for Type-I**. Power and reach are then evaluated at that larger c, so the M2 gate is pessimistic. That is the safe direction.
- **Shared code.** σ_d for a shrunk day is the exact variance of x_d under the shrunk categorical, enumerated over k + 1 outcomes. One pure function computes it in production and in the MC (§6, step 2.2).
- **Rejected alternative.** Shrinking every mass proportionally raises the NO legs' win probability above BE. That is anti-conservative on mixed days, so it appears only as sensitivity row S2.
- **Refusal.** If `Σ_NO q > 1` alone (κ < 0), the template cannot be made feasible conservatively:
  - the MC **refuses to run** and reports such templates;
  - the producer refuses (fail closed).

### 4.3 MC specification for c (`scripts/analysis/fq_loss_floor_mc.py`; NOT run)
- **Pool.** The `fq_mc_livedata` pool: out-of-fold, before 2026-07-01, and the holdout never opened.
  - The live losses of 10-01..10-06 and every post-epoch fill are never read. Pinning therefore peeks at nothing the floor will judge.
- **Templates.** Station-day templates (rungs, sides, per-contract BE) of the pool's eligible FQ takes.
- **Mix scenarios.** M-pool (the empirical mix), M-yes (YES legs only) and M-no (NO legs only, which gives the heaviest single-day tails).
  - **c = the maximum over scenarios.** The pool's side mix need not match live FQ v2.
- **Ticks per replicate.** For each calendar day from the epoch start to 2027-01-25, draw the station-day count from the pool's empirical per-day distribution.
  - **Calibration uses the longest horizon:** epoch start = the A1 freeze date. A longer horizon gives more crossing chances and so a larger c, which is conservative.
- **H0 draws.** Draw per §4.2. The MC **imports** the production pure functions (bundle and crossing, §6 step 2.2) and replays them verbatim; it never re-implements them (L-40 amendment (ii)).
- **Solving for c.** Grid step 0.01. c is the smallest value with crossing rate ≤ α_floor = 0.10 across the scenarios.
  - Report c, its SE (bootstrap over replicates) and the crossing rate at c.
  - Acceptance: rate ≤ α_floor + 3·SE.
  - Replicates ≥ 10,000; seed set by the coordinator before the run.
- **t_min.** Chosen from the pre-stated grid {1, 2, 3, 5} to maximise G3 power (§4.4) subject to the α constraint. Ties go to the smallest t_min. It is pinned together with c.
- **Sensitivity rows** (labelled; never the H0 run, per L-41):
  - S1: independent Bernoulli(BE) per leg, with no exclusivity;
  - S2: proportional shrink;
  - S3: the share of false-stop mass from single-day crossings, per scenario.
- **Also reported:** the share of Σq > 1 templates, the mean κ, and the number of refused templates.
- **Output:** `docs/evidence/f5/fq_loss_floor_mc_seed<S>.json`, containing c, SE, t_min, per-scenario rates, the gate rows of §4.4, the script's git sha and the parent sha.
- **Run hygiene:**
  - one heavy job at a time;
  - the address-space cap (`breezy.analysis.memory_cap.apply_address_space_cap`);
  - a no-progress stall watch and a first subset benchmark;
  - a Monitor armed in the launch turn.

### 4.4 The M2 reachability and power gate (must pass before c freezes)
- **G1, structural reachability.** Deterministic, per mix scenario, using the median template:
  - the all-lose path (every leg h = 0, Z_d = −BE-weighted loss / σ_d) must cross −c√t at some t ≤ **T_low(e)**;
  - T_low(e) is the tick count by 2027-01-25 from epoch start e, at the lower take rate: the frozen `take_rate_lower` 0.25 (`F5_prereg_v2_design.json:14`, takes/day), converted to station-days by the pool's takes-per-station-day ratio;
  - e is evaluated on the grid {A1 freeze date, 2026-11-01, 2026-11-15, 2026-12-01};
  - also report the **minimum fully-lost fraction f\*** of station-days (with the rest at zero drift) needed for the expected S_t to cross by T_low(e). This is the "loss fraction needed at t_horizon" that M2 asks for.
- **G2, positive control (L-38).** Owned by F6b (§4.8): a synthetic post-epoch losing stream through the real producer and the real probe yields FAIL.
- **G3, power.** Per scenario and per e: P(FAIL by 2027-01-25)
  - at the mirrored edge δ = −δ_h = −0.16, where the frozen δ_h is 0.16 (`F5_prereg_v2_design.json:6`);
  - and at δ ∈ {−0.04, −0.08};
  - where the H1 leg win probability is lowered by |δ| (YES: q − |δ| floored at 0; NO: the win probability BE − |δ|), with the §4.2 shrink if needed;
  - target `POWER_TARGET` = 0.8 (`fq_mc_eprocess.py:35`), reused rather than invented.

**Gate outcomes (pre-stated):**

| Result | Action |
|---|---|
| G1 passes at e | Freeze allowed. A1 pins `reach_cutoff_epoch_start` = the latest e at which G1 passes on **every** scenario. If the eventual arming timestamp is later than that, the producer never writes PASS (fail closed). |
| G1 passes and G3 < 0.8 at −0.16 | Freeze allowed only with `power_class: "gross_loss_tripwire"` and the measured powers recorded in A1. F6b's docs must say the floor is not an edge detector. The edge stop remains KILL, whose power M10 measures. |
| G1 fails at α_floor 0.10 for every e | Do **not** freeze a √t c. Go to §4.5. |

### 4.5 How the floor looks in the real regime (planning arithmetic, not evidence), and the fail-closed alternative
**Planning arithmetic** (a Gaussian approximation; the MC replaces every number here):
- For a time-uniform √t boundary over about 25 looks at α 0.10, c is roughly 2.3–2.5.
- The worst single-day standardised increment for one leg:
  - YES at BE 0.3: −0.65;
  - YES at BE 0.5: −1.0;
  - NO at BE 0.92: −3.4.
- All-lose crossing needs t > (c/|z|)²:
  - YES 0.3: about 13 consecutive fully-lost station-days;
  - YES 0.5: about 6;
  - NO 0.92: 1.
- With about 24 takes by 2027-01-25 (the merge's figure; c√t ≈ 6.9 contracts against a maximum loss of about 7 on the fill clock), a YES-longshot book reaches the floor only under near-total loss.
- Power at δ = −0.16 is roughly 0.3, and at −0.04 it is about α.
- A NO-favourite book reaches the floor from a single loss, so its false-stop rate is carried by rare single days (sensitivity row S3).

**Plain statement:** in the YES-longshot regime, the √t floor is at best a gross-loss tripwire and may fail G1 for late epoch starts.

**Fail-closed alternative, in order. Never a dead stop:**
1. **If G1 fails at 0.10,** the MC also reports G1 and G3 on the pre-stated grid α_floor ∈ {0.20, 0.30}. The peer loop may rule a larger α_floor. For a veto-only stop that is the **safety direction**: more false halts, never less protection. It is a design choice made before any evidence, not a weakened checker.
2. **If G1 fails at every grid level, or the loop refuses,** A1 freezes `floor_mode: "unreachable_veto"` with `c: null`:
   - the producer never writes PASS, the probe reads UNKNOWN, and FQ v2 entries are vetoed;
   - this lasts until the bridge retires, which happens at the first accepted non-inert `live.drawdown` PASS (AUT-6);
   - this is an always-on veto that blocks trading, which is the opposite of a stop that cannot fire;
   - it is reported as a blocker to the goal state (L-3): the trading path then runs through AUT-6, not through F6.
3. **Considered and rejected:** a bounded-bet e-process on per-contract day P&L.
   - It is Ville-valid with no horizon, but it gains no reach for longshots: all-lose at BE 0.3 still needs about 16 days at log(1/0.1).
   - The spec also fixes the √t shape.

### 4.6 F6b inputs (M4): pinned here, or frozen before F6b is built
| Input | Status |
|---|---|
| NO-fill sign, leg source, netting | **Pinned in A1** (`inputs.sign_rule`): steps 1–2 of §4.1, `net_position._SIGNS` |
| Multi-contract and partial fills | **Pinned in A1:** step 3 of §4.1 (cumulative per venue order, summed per leg, qty ≡ 1) |
| BE and fee source | **Pinned in A1:** the ledger fee; `fee_reconciled == False` refuses |
| Exits, voids, overround | **Pinned in A1:** steps 4, 6 and 7 of §4.1; §4.2 |
| `truth_sha` feed | **Pinned in A1:** sha256 of the canonical JSON (the existing form, §1.3) of the sorted list of consumed C2 cash-record identities (`kind`, `fill_key`, `payout` as a string, `dated_at_ns`) |
| `c2_hwm` | Defined by F6 (digest `loss_stop_probe.py:108-110`); not re-pinned |
| **Refusal channel** | **Must freeze before F6b** (peer ruling). `loss_stop/v1` carries only PASS or FAIL (`loss_stop_probe.py:21-27`). A FAIL halts the family set-only, which is wrong for a data refusal. Staleness vetoes only after `STALE_VETO_H` = 36 h (:77-78), which leaves up to 36 h under the last PASS. **Proposal:** the producer atomically removes `latest.json`. The probe then reads a missing artefact as UNKNOWN (docstring :26-27), and UNKNOWN vetoes on the next probe (:290-291, interval 300 s at :80). This stays inside F6's fixed contract. |
| **Epoch-anchor runtime source** | **Must freeze before F6b** (peer ruling). Candidates: (a) the autonomy transition ledger row that records the v2 arming, if the arming is recorded as a transition (already validated by `persistence/autonomy/validate.py`); (b) a committed `armed_at` ruling JSON, loaded by `load_verified_amendment` in a pin test that fixes a producer constant. A1 pins only the **definition**: "the armed_at of the v2 arming ruling". It cannot pin the value, because A1 freezes before that ruling exists (L-34). |
| Fixed by F6, not re-pinned | `SCHEMA` (:63), the digest (:108-110), `MAX_AGE_H`/`STALE_VETO_H` (:77-78), the parity paths, `as_of` monotonicity, directory modes |

### 4.7 A1 draft shape (NOT freeze-ready) and its payload rule
```json
{
  "frozen_sha": "UNFROZEN",
  "amendment_id": "F5_prereg_v2_A1_floor",
  "amends": {"path": "docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F5_prereg_v2_design.json", "frozen_sha": "072ab026cdc790dd6e9a51d62d8164766b85fd82"},
  "loss_stop_floor": {
    "floor_mode": "PENDING_GATE (sqrt_boundary | unreachable_veto)",
    "power_class": "PENDING_GATE",
    "alpha_floor": 0.10,
    "t_unit": "settled_station_day",
    "pnl_unit": "per_contract_qty1",
    "increment_rule": "§4.1 steps 1-8 of F5-pin-request_r2",
    "bundle_null_rule": "categorical_yes_first_shrink_v1 (§4.2)",
    "boundary_rule": "FAIL iff S_t < -c*sqrt(t) for some t in [t_min, t_at_horizon]",
    "c": "PENDING_MC",
    "c_mc_se": "PENDING_MC",
    "t_min": "PENDING_MC",
    "t_horizon_climate_day": "2027-01-25",
    "reach_cutoff_epoch_start": "PENDING_MC",
    "past_horizon_rule": "fail_closed_no_pass; recalibration owner coordinator",
    "epoch_anchor_rule": "armed_at of the v2 arming ruling; no pre-v2 window",
    "restart_rule": "FAIL terminal within epoch; re-arm only by a new ruling and a new epoch; S_t restarts at 0",
    "inputs": {"sign_rule": "...", "fill_rule": "...", "fee_rule": "...", "exit_rule": "...", "void_rule": "...", "truth_sha_rule": "..."}
  },
  "provenance": {"mc_module": "scripts/analysis/fq_loss_floor_mc.py", "mc_evidence": "PENDING_MC", "mc_seed": "PENDING_COORDINATOR"}
}
```
R5 for A1:
- exact key set;
- `alpha_floor` in (0, 1);
- `floor_mode` ∈ {sqrt_boundary, unreachable_veto};
- `sqrt_boundary` ⇒ c is a finite number > 0 and `t_min` is an int ≥ 1;
- `unreachable_veto` ⇒ `c` is null;
- every `PENDING_*` string is refused;
- `t_horizon_climate_day` is an ISO date.

### 4.8 A1 and F6b tests (ADD)
- **Pure core** (§6, step 2.2):
  - `combine_station_day` reuse equals the L-40 same-side and mixed-side formulas;
  - the YES-first shrink gives every leg drift ≤ 0 and refuses when Σ_NO q > 1;
  - NO-leg BE is read from the NO instrument, never from the wire price;
  - same-rung YES/NO nets out as deterministic;
  - `fee_reconciled=False` refuses;
  - exit and void handling.
- **Floor MC acceptance:** the rate at the pinned (c, t_min) is ≤ α_floor + 3·SE in every scenario. Plus mutation tests: a dollar-scaled P&L, a cap-derived c, or a dropped overround day must each fail.
- **F6b** (owned by F6b):
  - `test_loss_floor_constants_equal_amendment_a1` (through `load_verified_amendment`);
  - `test_floor_read_from_prereg_never_from_operator_controls`;
  - `test_floor_time_uniform_from_arming_timestamp`;
  - the **L-38 positive control:** a synthetic post-epoch all-lose stream yields FAIL through the real writer and the real probe;
  - FAIL terminal within an epoch;
  - the refusal removes `latest.json` and leads to an UNKNOWN veto.

## 5. A2: the calibration guard

### 5.1 Rulings applied
- Q1: α_guard = 0.10, calibrated to the **ever-blocked** rate.
- Q2: the rule is point-in-band, as `_group_status` does (`evaluators/forecast_quantile_ladder.py:166-180`).
- Q3: pooling is `per_side` (`_POOLINGS` `eprocess.py:71`).
  - An absent side is skipped: the comprehension runs over present sides only (`forecast_quantile_ladder.py:189-192`).
  - **Stated consequence:** a side that is present with fewer than `n_guard_min` takes returns `INSUFFICIENT(n_guard_min)` (:169-170) and blocks PASS.
  - Because NO-side hunting is a requirement, a few early NO takes can therefore hold PASS until that side reaches `n_guard_min`. PASS is already infeasible before KILL under STARVED, so this costs nothing before 2027-01-25.
- The guard only removes PASS days (`pass_hit = cross and last_guard.status == GUARD_OK`, :295). It is evaluated every settled day (:292), and the IUT level α_k is unaffected.

### 5.2 Guard MC (`scripts/analysis/fq_guard_mc.py`; NOT run; M8)
- **Pool and holdout:** the same pool and the same holdout prohibition as §4.3. The seed is set by the coordinator.
- **Null.** Outcomes are calibrated to the model: the categorical with masses equal to the model's rung probabilities (P(NO wins) = 1 − p_rung).
  - This is always feasible, because the density sums to 1. It preserves exclusivity on mixed-side days (L-40, L-41).
- **Engine.** Replay `_guard`/`_group_status` verbatim, imported from the evaluator. Evaluate daily from the epoch to 2027-01-25 at the pool take rate, per side.
- **Metric (M8).** The **ever-FAIL** rate: P(any day yields `FAIL(spiegelhalter_z)` or `FAIL(reliability_slope)`, on either side). Calibrate it to ≤ α_guard = 0.10 (+ 3·SE). The time spent in INSUFFICIENT is reported separately.
- **Threshold family (one parameter a, solved by bisection):**
  - `spiegelhalter_abs_z_max = Φ⁻¹(1 − a/2)`;
  - `slope_band` = the null (a/2, 1 − a/2) quantiles of the per-side slope at `n_guard_min`.
- **`n_guard_min`:** the smallest value on the grid {20, 30, 40, 60, 80} that is ≥ the frozen `earliest_look_n` 20 and meets both conditions:
  - (i) **occupancy (M8):** ≥ 3 bins with ≥ 5 takes each, on ≥ 95 % of per-side windows. Two bins leave the slope zero residual degrees of freedom; 5 is the existing `min_cell_rows` floor, `multisource_blend_skill.py:169`;
  - (ii) Z's null quantile is within ±0.1 of Φ⁻¹ at a/2.
- **`bin_edges`:** reuse `_DEFAULT_BIN_EDGES` = (0, `RELIABILITY_BUCKET_EDGES`, 1) (`forecast_quantile_ladder.py:84`). If the deciles fail occupancy at every grid n, the pre-stated fallback is quintiles.
- **Power alternatives:**
  - slope miscalibration `p_true = 0.5 + s·(p_model − 0.5)`, with s ∈ {0.5, 0.7, 0.85, 1.2, 1.5}, where s > 1 means the model is under-confident;
  - a mean shift of ±0.05.
- **Positive control (M8):** on the pool's **real** out-of-fold windows, report P(OK).
  - The rung is known to be under-confident, so this may be near 0.
  - If it is, A2 still freezes the null-calibrated thresholds and records `real_pool_ok_rate`. The doc then states that PASS is unreachable until the density is recalibrated.
  - Thresholds are **never** tuned to real windows.
- **Output:** `docs/evidence/f5/fq_guard_mc_seed<S>.json`.

### 5.3 Timing and dependency
- A2 freezes before the first forward-shadow source is registered. `REGISTERED_FORWARD_SHADOW_SOURCES` is empty today (`forecast_quantile_ladder.py:89`).
- Per Q12, the 6b owner carries the guard that registration refuses while A2 is missing or UNFROZEN.

### 5.4 A2 payload (draft) and R5
- `guard` has exactly the five `GuardThresholds` fields (`eprocess.py:88-116`): `n_guard_min`, `spiegelhalter_abs_z_max`, `slope_band`, `bin_edges` and `pooling`, all `PENDING_MC` except `pooling: "per_side"`.
- `guard_basis` = {`alpha_guard`: 0.10, `ci_rule`: "point", `absent_side_rule`: "skip", `present_side_below_min_rule`: "blocks_pass", `real_pool_ok_rate`: PENDING_MC}.
- R5 for A2:
  - `GuardThresholds(**guard)` constructs without `EProcessRefused`;
  - `pooling == "per_side"`;
  - `bin_edges` equals the imported `(0.0, *RELIABILITY_BUCKET_EDGES, 1.0)` or the quintile fallback;
  - `PENDING_*` is refused.
- Tests:
  - `test_guard_from_amendment_constructs_guard_thresholds`;
  - `test_guard_only_removes_pass_days`: a property test over random thresholds; PASS days with the guard ⊆ PASS days without it;
  - the occupancy and ever-FAIL acceptance rows.

## 6. Implementation order (each phase merges on its own)

**Phase 0. Verify first. A STOP on failure; nothing is edited.**
1. `prereg_precommit_check.py <design.json>` exits 0 at HEAD.
2. `check_not_refrozen(design.json)` does not raise.
   - If it raises, STOP and report.
   - The parent is never edited, and A0 cannot proceed until the peer loop rules.

**Phase 1. A0 (now).**
1. tdd-guide writes RED tests (§2.5, §3.3).
2. Write the sibling checker and loader, then go GREEN.
3. Commit the A0 body (§3.1) with UNFROZEN; `--draft` exits 0.
4. Make the freeze commit, then the stamp commit (frozen_sha = the freeze commit). Add the content-digest literal test.
5. Run the full gate `scripts/ci/run_tests_no_egress.sh`, plus `lint-imports` from the tree root (the "N kept, 0 broken" line). Read EXIT, and only then push.
6. Run the M10 report after the freeze (§3.4) and commit it as evidence.

**Phase 2. A1.**
1. The peer loop rules on the two F6b inputs in §4.6: the refusal channel and the anchor source.
2. Build the F6b **pure core**, which has no I/O and no c: `src/breezy/analysis/fq_loss_stop_core.py`.
   - It holds leg normalisation, the netting split, `combine_station_day` reuse, the shrunk-null variance and the crossing function.
   - Do it TDD-first. Run `lint-imports` (analysis → settlement is an existing edge, used by `analysis/promotion_criteria.py`).
3. Write the floor MC script. TDD it on tiny seeds that import the core.
4. Have the coordinator set the seed, then run it (capped, watched).
5. Evaluate the M2 gate and branch per §4.4/§4.5.
6. Peer-review the evidence.
7. Freeze A1 **before any v2 arming ruling**.

**Phase 3. A2.**
1. Write and TDD the guard MC.
2. Run it.
3. Peer-review it.
4. Freeze A2 before the first 6b registration.

## 7. Testing strategy
- **Unit:**
  - the sibling checker rules R1–R5, with a planted defect for each;
  - the loader refuses UNFROZEN;
  - KILL import equality and the AST literal check;
  - the pure-core bundle, sign, fee, exit and void rules;
  - guard construction.
- **Integration:**
  - a temporary git repo freeze → stamp → re-freeze sequence through `check_not_refrozen`;
  - the F6b writer → probe positive control;
  - the guard property test.
- **MC acceptance:** the §4.8 and §5.2 rows, each with a seeded, recorded evidence file.
- **Census:** the reserved-name grep is 0 on this doc and all three amendments, and `test_operator_control_assignment_scan.py` stays green.
- **Regression:** the parent checker and its test are byte-unchanged; the full gate passes after every merge.

## 8. Risks and mitigations
- **The parent fails `check_not_refrozen` (its history is unknown).**
  - Mitigation: Phase 0 STOPs. The parent is never edited.
- **A shallow clone in CI refuses every amendment (:212-217).**
  - Mitigation: the gate runs in the full local tree. Document it in the checker usage text.
- **The floor's heavy NO tails.** A single unlucky high-price NO day trips the floor.
  - Mitigation: c is the maximum over mix scenarios; the single-day share is reported (S3); the peer loop sees it before the freeze.
- **The pool mix differs from the live FQ v2 mix.**
  - Mitigation: c is calibrated at the maximum over scenarios, and reachability is checked at the lower take rate.
- **The floor is unreachable or underpowered.**
  - Mitigation: the §4.4/§4.5 ladder. It ends in an always-on veto, never a dead stop.
- **The guard binds on a known under-confident density.**
  - Mitigation: report it as information; thresholds are never tuned to real data.
- **The F13 import coupling (§2.3).**
  - Mitigation: covered by the planted-defect tests.
- **Shared-tree hazards.**
  - Mitigation: a scratchpad per agent; `ruff format` on touched files only; never stash; never `uv sync`.

## 9. Success criteria
- [ ] A0 is frozen once; `prereg_amendment_check.py` A0 exits 0; the parent checker and its tests are byte-unchanged; the full gate is green and EXIT has been read.
- [ ] The M10 KILL power report exists, with δ clamped at 0, and no constant has changed.
- [ ] The floor MC evidence includes c ± SE, t_min, G1/G3 for every scenario and epoch start, and the share of Σq > 1 templates. A1 is frozen in `sqrt_boundary` or `unreachable_veto` mode, before arming.
- [ ] Both F6b inputs (the refusal channel and the anchor source) are ruled before F6b is built.
- [ ] The guard MC evidence includes the ever-FAIL calibration, occupancy, power and `real_pool_ok_rate`. A2 is frozen before any 6b registration.
- [ ] The census grep returns 0, and no operator-reserved control is named or assigned anywhere.

## 10. Residual questions for the peer loop
1. The F6b refusal channel: is the `latest.json` removal proposal in §4.6 acceptable?
2. The epoch-anchor runtime source: (a) the ledger row or (b) a ruling JSON?
3. If G1 fails at 0.10: which α_floor on the pre-stated grid, or `unreachable_veto`?
4. G3 below target at −0.16: is the labelled tripwire acceptable as a freeze (the §4.4 table proposes yes)?

## 11. r1 → r2 change log
| Defect | Fixed in |
|---|---|
| M1: rule (vi) rebuilt `check_not_refrozen`; no UNFROZEN-refusing loader; no digest test | §1.3, §2.2 (R1, R4 import `check_not_refrozen`), §2.4 (`load_verified_amendment` follows the `load_verified_prereg` pattern), §2.5 (PIN-R8(c)-style digest test per file) |
| M2: the floor may be unreachable (L-38) | §4.4 (G1 reach / f\*, G2 positive control, G3 power at −δ_h, outcomes table), §4.5 (plain regime read and the fail-closed ladder) |
| M3: the H0 joint is undefined when Σ BE > 1 | §4.2 (categorical joint, YES-first shrink, every leg's drift ≤ 0 ⇒ Type-I conservative; refusal when Σ_NO q > 1; S1/S2 sensitivity) |
| M4: F6b inputs unspecified | §1.2 (venue facts from code; LESSONS has none), §4.1 steps 1–5, §4.6 (pinned vs must-freeze-before-F6b table, `truth_sha` rule, refusal channel, anchor source) |
| M5: KILL coupled to the floor; rule (iii) hit the envelope | §0, §2.1 (three files A0/A1/A2; envelope keys exempt from overlap) |
| M6: `--amendment` edited the parent checker | §2.2 (sibling `prereg_amendment_check.py`; the parent stays byte-unchanged) |
| M7: `kill_lambda_max` duplicate; third canonical form; `kill_hedge_theta` with no consumer | §1.3, §2.1 (`content_sha256` dropped, the existing `content_digest` used in tests), §3.1 (`kill_hedge_theta` dropped, `kill_bar_rule` kept), §3.2 (import-only comparisons against `MAX_LAMBDA` and the KILL constants) |
| M8: per-day \|Z\| multiplicity; 2 bins too weak; under-confident rung | §5.2 (ever-FAIL calibration, ≥ 3 bins × ≥ 5 takes occupancy, positive control on real out-of-fold windows) |
| M9: wrong √t fill clock; S_t gaps | §4.1 (station-day clock with standardised bundle increments, ledger-fee BE, `fee_reconciled` fail-closed, exits, voids, partials, netting) |
| M10: KILL power at a negative edge unmeasured | §3.4 (post-freeze report at δ ∈ {−0.04, −0.08, −0.16} with a lower clamp the MC alternative lacks; reporting only) |
| M11: S_t restart unstated | §4.1 step 10 (FAIL terminal per epoch; re-arm only by a new ruling and a new epoch; stateless recomputation) |
| Q1–Q12 | Q1–Q3 §5.1; Q4 §3.1; Q5–Q10 §4 preamble and §4.1; Q11 §0/§2.1; Q12 §5.3 |
