# RULING — BLOCKERS R4 scope and E5 intake (2026-10-19)

- **Type:** coordinator ruling.
- **Source plan:** `docs/plans/backlog/BLOCKERS_2026-10-19/plan_r2.md` (r2.1 READY; peer reviews in `docs/plans/backlog/BLOCKERS_2026-10-19/reviews/`).
- **Status:** DRAFT (Commit 1 of 2). §B5 Result, §B4 and Peer verdicts are placeholders until Commit 2.
- **Arms nothing. Sets no operator control.**

Short names used below: `SPEC` = `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md`; `S5r3` = `docs/plans/backlog/MAKER_2026-10-12/S5_shadow_run_and_gates_plan_r3.md`; `S2r4d` = `docs/plans/backlog/MAKER_2026-10-12/S2_stage0_replay_plan_r4_delta.md`; `S2r3` = `docs/plans/backlog/MAKER_2026-10-12/S2_second_look_plan_r3.md`; `verdict.py` = `scripts/analysis/maker_stage0_verdict.py`; `ledger.py` = `src/breezy/analysis/hypothesis_ledger.py`; `RA-13` = `docs/evidence/RULING_RA-13_programme_kill_2026-09-27.md`; `HUNT-1` = `docs/evidence/RULING_HUNT-1_all_hours_hunting_2026-09-26.md`; `DocA` = `docs/evidence/RULING_MAKER-S2_second_look_SEARCH_declaration_2026-10-16.md`.

**Invariants, restated.**
- Nautilus Trader is immutable. Nothing in this ruling modifies, patches, forks, bypasses or reimplements it.
- No code, no spec and no plan is edited. No PREREG is edited and no pre-registered date moves (including 2026-11-04..11-15 and 2027-01-25).
- Operator-reserved controls are referred to only as "the per-position cap" and "the daily budget". No value is assigned to either.
- No live enablement change. No ledger edit. Nothing is armed.

---

## §B2 — S2 label unit and the E1/§8 unit convention (DRAFT, peer verdicts pending)

**Scope.** Mechanism only. This section carries no block-1 or block-2 number as a scenario.

**Label unit (verified).**
- `_stricter` (the lower of the station-day and position units; empty unit on a non-empty denominator is a refusal) is defined at `verdict.py:107-116` and applied to base and stress rates at `verdict.py:215-216`.
- `verdict_label` compares `base` and `stress` with `FILL_FLOOR` (0.10) at `verdict.py:269-278`. `decide` calls it at `verdict.py:319`.
- `r_lo` is the stressed station-day point: `verdict.py:173-176`; `S2r4d:151` (`r_lo` = `r_lo_station_day`, S3 `f_kill`); `S2r4d:152` (stressed point, each unit, min over hypotheses).
- Pre-registered support for the stricter unit: `S2r4d:290` (r3 PMR §5 path 7, "stricter unit"); `SPEC:134-136` ("the gates use the stricter").
- The label and `r_lo` are different quantities by design.

**Byte-identity.** `scripts/analysis/maker_stage0_verdict.py` at `2380042f` is byte-identical to HEAD: `git diff 2380042f HEAD -- scripts/analysis/maker_stage0_verdict.py | wc -l` = 0.

**E1/§8 unit convention (convention ruling; E1 text is frozen and not edited).**
- `S5r3:282`: at MAX_RUNGS = 2, positions/day = 7.28·c·r, so `r` is a per-rung quantity. `S5r3:283`: at MAX_RUNGS = 1, positions/day = station-days/day = 3.64·c·r.
- `S5r3:296`: E1 feasibility reads `r_lo · c` ≳ 0.115 at MAX_RUNGS = 2 and ≳ 0.23 at MAX_RUNGS = 1. Both `r_lo_station_day` and `r_lo_position` exist (`S2r4d:151-152`), so the unit must be fixed.
- Convention, fixed before any block-2 result. The freeze-day S-1 test uses:
  - at MAX_RUNGS = 2: `r = min(r_lo_position, 1 − √(1 − r_lo_station_day))`;
  - at MAX_RUNGS = 1: `r = min(r_lo_position, r_lo_station_day)`;
  - `c` multiplies `r` afterwards (`r · c` against 0.115, `S5r3:296`).
- Justification. The k = 2 form inverts the §8 station-day formula (`S5r3:282`: station-days/day = 3.64·c·(1 − (1 − r)²), so `s = 1 − (1 − r)²` gives `r = 1 − √(1 − s)`). Since `1 − √(1 − s) ≤ s` for `s` in [0, 1], and `min` can only lower `r`, the rule can only fire S-1 earlier or at the same time, never later.

**Citation corrections (verified by opening the lines).**
- `S2r3:36,38` is cited in the plan for the label unit but does not contain it: those lines are census-invocation and registry-narrowing text. They are replaced by `S2r4d:290` and `SPEC:134-136`.
- The stale rows are `S2r3:415-417` (timeline rows for 10-18..10-24, already past). `S2r3` stays unedited because it is frozen input.
- `DocA` pins only its own sha (`DocA:5`), the tail csv (`DocA:73`) and `trade_quantity_unit.json` (`DocA:70`). Code is frozen through `CODE_SHA` (`DocA:64`).
- The S2 run pins the spec sha256 (`scripts/analysis/maker_stage0_pins.py:86,332`).

**Do not build.** No label change, no station-day-only label, no edit to `verdict.py`, `DocA` or the trigger.

---

## §B3 — S5 read target 300/200 is the pole (DRAFT)

**Decision.** 300/200 is kept. The effective-n (Kish) rule is REJECTED outright. It is not parked as an option.
- Position target 300: `SPEC:252-253` ("read target of 300 positions (200 × the 1.5 design-effect ceiling) and 200 station-days"); `S5r3:219` ("holdout positions ≥ 300 (200 × deff ceiling 1.5)").
- Effective-n gate 2, 200: `SPEC:262` (§6.4, "Gate 2 uses the realised effective n on the holdout") and `SPEC:310` ("Realised effective n ≥ 200 positions and ≥ 200 station-days"), stated separately.

**Reasons.**
1. The ledger refuses any look policy other than a single look: `ledger.py:1071-1075` (`InvalidLookPolicyError`; `SINGLE_LOOK` is the only admitted design).
2. The realised design effect depends on outcomes (clustered fills), so an effective-n target is post-outcome.
3. Choosing n after the block-1 split is visible is the post-result pattern.

**Gate-9 floor (optional sentence, stated as the plan states it).** The adverse-selection floor is 10/mean(p_YES of filled episodes). It is ≈250 only if mean p_YES ≥ 0.04, and ≈333 at 0.03. Source of the floor: `S5r3:174` (pooled m = Σ p_YES,i; m < 10 → UNSCREENED) and `S5r3:44` (S-5b).

**§9.15 is superseded by S5r3 §8.** Values copied verbatim: 412 / 165 / 83 days at MAX_RUNGS = 2, c = 1 (`S5r3:289,291,292`). `c` is unmeasured, so these are upper bounds on speed. The §8 table row at `S5r3:313` maps R6 "r_lo ≳ 0.2" (§9.15) to §8.

**No spec edit.** The S2 run pins the spec sha256 (`scripts/analysis/maker_stage0_pins.py:86,332`). The S5 PREREG names spec v0.3 (`S5r3:217`).

**Do not build.** No S5 redesign, no sequential or LD-OBF looks, no 300/200 change, no station-day-only gate, no effective-n target rule, no spec revision.

---

## §B5 — E5 intake pins (FINAL in this commit; frozen before the call)

**Ledger facts (verified).**
- `register_hypothesis` is `ledger.py:873-899`. It is pure. The status is decided by `recomputed_mde > mde_plausibility_bound` (`ledger.py:1116-1125`). The MDE is `recompute_mde` (`ledger.py:859`). Ask and slippage are recorded only (`ledger.py:1139-1141`).
- Tolerance `MDE_MISMATCH_TOLERANCE` = 1e-4 (`ledger.py:216`), compared at `ledger.py:1119`.
- `ledger.py:177` `PROGRAMME_ALPHA` = 0.05 (older default); `ledger.py:181` `MAX_HYPOTHESES` = 4. The override is checked at `ledger.py:957-964`; the split is `ledger.py:1114-1115`.
- With no strata and no horizon the record is schema v1. The v2 refusal is at `ledger.py:1159-1165`; the v3 refusals are at `ledger.py:1166-1184`, and both `HORIZON_TOLLING_LANDED` (`ledger.py:166`) and `PATH_B_SOURCE_GATE_LANDED` (`ledger.py:174`) are False.
- `read_hypothesis_ledger` is `ledger.py:1369-1392`. `programme_budget_remaining` is `ledger.py:811`. `DuplicateHypothesisIdError` is raised at `ledger.py:943-946`.
- `hypothesis_register.py` (`scripts/analysis/`) is not imported by the call. `freeze_commit` format is not validated there (`scripts/analysis/hypothesis_register.py:235-239`, cited only).

**Pin table (copied verbatim from `plan_r2.md` §B5).**

| kwarg | value | source |
|---|---|---|
| `hypothesis_id` / `hypothesis_class` | exact strings `"H-MAKER-NO-2026-10"` / `"pm_us_no_ladder_maker"` | SPEC §1; not a duplicate of the 4 live ids (python r2) |
| `existing_records` / `disposition` | `read_hypothesis_ledger(<scratchpad copy>)` / default `"NORMAL"` | run step 4 |
| `registered_at` / `freeze_commit` | call date / HEAD 40-hex sha at the call (not format-validated, `scripts/analysis/hypothesis_register.py:235-239` — cite only, never import) | — |
| `k_variants` | 1 | one design; `MAX_RUNGS` is not a variant (precedents `hypothesis_register.py:154,183,214`) |
| `programme_alpha_override` | 0.025, one value | RA-13 binds programme FWER at 0.025 (`RULING_RA-13:5`) and the spec nests α in RA-13. The ledger's `PROGRAMME_ALPHA` 0.05 (`:177`) is the older default. |
| `min_station_days` | 200 | `SPEC:252-253` design value |
| `mde_at_allocated_alpha` | `recompute_mde(per_variant_alpha=0.025/4/1, n_station_days=200)` = the full-precision returned value (0.118063…; python r2 ran it: 0.11806302799), never a rounded literal (tolerance 1e-4, `:1119`, `:216`) | `:859` |
| `mde_reference_ask` | 0.80, the design bid | Break-even is ask-based (`:851-856`); a maker's cost basis is its bid. For every rung with p_NO ≥ P_MIN 0.94, `p_no − E_MIN − fee` ≥ 0.829, so `b_max` = B_CAP 0.80 (`SPEC:72,83`). |
| `mde_slippage_allowance` | 0.01 | The spec names none. Programme convention is the AUD-12a retained placeholder (`RULING_RA-13:13`; precedents `hypothesis_register.py:169,202,229`). |
| `mde_variance_bound` | 0.25 | `VARIANCE_BOUND` (`:196`), Popoviciu; no justification needed |
| `mde_plausibility_bound` | **0.08** (= b 0.80 / w 0.90 cell 0.089 − 0.01 slippage = 0.079, rounded) | cell ENDORSED by architect, PMR and python-reviewer in `reviews/r2-*.md`; any bound in [0.079, 0.118) gives the same status |
| fixed constants | `power_is_primary_only=True`, `mde_fee_theta=0.0695`, `max_single_day_leg_share_cap=0.20`, `station_day_statistic="MEAN_EXCESS_PER_TAKE"`, `order_quantity=1`, `look_policy="SINGLE_LOOK"` | `:196-212,1000-1018` |
| not passed | `re_arm_gating`, `horizon_days`, `variant_stratum_filters` (schema v1) | — |

**OPEN before the call: hypothesis id citation defect.** `SPEC §1` names the hypothesis `H-MAKER-NO` (`SPEC:24`; also the v0.1 row, `SPEC:333`). The string `-2026-10` does not appear in the SPEC (grep at this commit). The pin is kept verbatim as the plan states it. This ruling does not silently change it. The peers must rule on the id, and the call does not run until the pin table is re-committed with that decision.

**Bound unit check (verified).**
- The `SPEC:138-147` column is "EV per contract" = `w − (b + θ·b·(1−b))` (`SPEC:139-140`). The fee column implies θ ≈ 0.0694 (`SPEC:146`), which matches `EVIDENCED_FEE_THETA` 0.0695 (`ledger.py:204`).
- `MEAN_EXCESS_PER_TAKE` is the mean of `W − BE`, with `BE = a + θa(1−a) + slippage` (`ledger.py:851-856`). The units are equivalent.

**Correction to the premise.** 0.08 is NOT the table maximum. The maximum is +0.225 (b = 0.70, w = 0.94; `SPEC:138-147`, row 0.70). The +0.081 cell is the b = 0.85 row (`SPEC:138-147`), a bid the design never places (B_CAP 0.80, `SPEC:72`).

**Derivation of the pinned bound.** Design-bid row b = 0.80 at w = 0.90: +0.089 (`SPEC:146`). Net of 0.01 slippage that is 0.079, rounded to 0.08 at the precision of past bounds (`hypothesis_register.py:22-34`).

**Disclosed alternative.** The w = 0.94 cell nets 0.119 (`SPEC:146`, +0.129 less 0.01), which exceeds the MDE 0.1181 by 0.0009 and would REGISTER. It is not the plausibility value. w = 0.94 equals P_MIN (`SPEC:72`), the lowest model p_NO for any bid, so it assumes perfect tail calibration and zero adverse selection. The spec names adverse selection as the falsifier (`SPEC:49-52`), states the hostile priors (`SPEC:41-47`), and reads observed 0.85 as its case (`SPEC:149-154`). The cell choice is made with the MDE known, as in every precedent, and is disclosed here.

**Peer endorsements of the cell (quoted; required before the call).**
- Architect, `reviews/r2-architect.md` §2 (line 24): "**Endorsement (required): the w=0.90, b=0.80 cell, giving a bound of 0.08.**"
- PMR, `reviews/r2-prediction-market-reviewer.md` Item 2, "Cell endorsement" (line 19): "I ENDORSE b=0.80, w=0.90, net of 0.01 slippage = 0.079, pinned 0.08."
- Python-reviewer, `reviews/r2-python-reviewer.md` "Cell endorsement (item 2)" (line 24): "I endorse the b=0.80, w=0.90 cell net of 0.01 slippage (0.089 - 0.01 = 0.079 -> 0.08)."

**Sensitivity (L-56).** `recomputed_mde > bound` decides the status. Every bound in [0.079, 0.118) is below the recomputed 0.1181 and gives the same status. Only a bound at or above the recomputed value would change it.

**Pre-declared expected outcome.** `UNDERPOWERED_NOT_REGISTERED`; `is_zero_look=True`; `allocated_alpha=0.0`; `per_variant_alpha=0.0`; `schema_version=1`; programme budget remaining 4.

**Procedure pinned (executed in the B5 call, not here).**
1. Run `~/.claude/bin/grok-check.sh` before any dispatch.
2. Ledger source: `~/.local/share/breezy/derived/hypothesis/hypothesis_ledger.jsonl` (hardcoded, never via `default_derived_root()`). Copy it to the executing agent's scratchpad. Record its sha256 before and after.
3. Read the COPY with `read_hypothesis_ledger`; record `programme_budget_remaining(records)` first.
4. Exactly ONE call to `register_hypothesis` with the pins above.
5. The script imports only from `breezy.analysis.hypothesis_ledger`. It never imports `hypothesis_register.py` or `write_hypothesis_ledger`.
6. Six named exceptions are recorded outcomes, not bugs: `DuplicateHypothesisIdError`, `MissingRegistrationInputError`, `MdeMismatchError`, `ProgrammeBudgetExhaustedError`, `HorizonTollingNotLandedError`, `PathBSourceGateNotLandedError`.
7. python-reviewer re-derives the arithmetic: z(0.99375) ≈ 2.4977, (2.4977 + 0.8416) · 0.5 / √200 ≈ 0.1181.

---

## §B5 — Result

Filled at Commit 2.

---

## §B4 — RA-13 KILL vs MAKER (R4 scope)

Filled at Commit 2 after the §B5 result.

---

## Peer verdicts

Filled at Commit 2.

---

## What this ruling does NOT decide

- No PREREG, pre-registered date, spec, code, live-enablement or budget/position-cap change. No ledger edit.
- The drop-in `fq-v1-halt-orders-off.conf` (`docs/core/PROGRESS.md:29`) is untouched.
- Activation remains the manual trio (`docs/core/PROGRESS.md:83`). No auto-arm path is created.
