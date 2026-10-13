# S5 plan r4: DELTA against `S5_shadow_run_and_gates_plan_r3.md` (HEAD `4fb736f6`, 2026-10-13) — r4 delta, rev 2 after round-2

**Status: r4 = r3 + this delta; READY (rev 2: round-2 items folded).**

r3 and `docs/plans/backlog/MAKER_2026-10-12/reviews/S5-r2-final.md` stay in force. This delta replaces only the anchors named below.
Sources:
- `docs/evidence/RULING_MAKER-S3_loss_stop_window_2026-10-13.md` (FINAL, `35e0289d`, O-1..O-6);
- `docs/plans/backlog/MAKER_2026-10-12/reviews/S3-r3-pmr-verification.md`;
- `docs/plans/backlog/MAKER_2026-10-12/reviews/S3-r4-pmr-final.md`;
- `docs/plans/backlog/MAKER_2026-10-12/S3_loss_floor_reachability_plan_r4_delta.md`.

## (a) Frozen stop form (:221, :28 E2, :228; ruling O-3)
- **r3 said:** `a1_stop` = "`(c, t_min, α_floor)` … σ inflated by √1.5".
- **r4 says:** `a1_stop` = `(c_deff, t_min, α_floor)`, read only from the S3 artifact's **top-level** `frozen_c_deff`, `frozen_t_min` and `frozen_alpha_star`. σ is inflated by √1.5.
  - The per-cell `cells[*].c_deff` is never read.
  - Full float precision. The unit-variance `c` with the inflated σ is forbidden.
  - `test_a1_stop_uses_s3_parameters_and_deff_inflated_sigma` asserts the value equals `frozen_c_deff`, and that crossings match (σ, c) on a seeded path set.
  - :28 E2 becomes "pins the frozen cell and `(frozen_c_deff, t_min, α_floor)`".

## (b) Certified horizon inside `a1_stop` (:221, :228, R-13; ruling O-1)
- `a1_stop` gains `certified_horizon_climate_days: 110` and `certified_ticks: <T_low of the S3 frozen cell>`, inside `a1_stop` only.
- The R-13 checker accepts exactly these two extra keys there and still refuses any other stop key.
- Tests: `test_a1_stop_accepts_certified_horizon_fields_inside_a1_stop` and `test_certified_horizon_as_top_level_stop_key_refuses`.
- The stop stays ARMED all run. Past climate date 110 its false-stop rate is uncertified.

## (c) False-stop disclosure (:226, :220; ruling O-1/O-2; PMR round 2)
- `Disclosures` gains `a1_tail_false_stop`: the S3 `horizon_sensitivity` per-row rates at `calendar_cap_date`, with sha, plus "capital-conservative; costs power".
- The day-60 `power_projection` discounts by **`worst_binding_row_rate`**, the maximum over the H0, S4, S5-bind and S8 rows. It never uses the H0 row alone, because H0 is optimistic against S4/S5-bind.

## (d) New WP0a — cap pin, written BEFORE the S3 binding run (:218, §8 :296; ruling O-2)
- **What.** WP0a commits `docs/evidence/maker/S5_CAP_PIN_<date>.json`: `holdout_start_date`, `calendar_cap_date`, `L_cap = inclusive days between them`, the input shas and the §8 rule text.
- **Inputs.** Only S2's `r_lo` and the WP0 coverage factor. The coverage factor is a tooling measurement and needs no S3 output.
- **Exemption.** WP0a is **EXEMPT from E2 and S-1**. Without the exemption the dependency is circular: S3's binding run needs the pin, and S5 cannot otherwise start before S3 REACHABLE. Nothing else in S5 moves ahead of E2.
- **Freeze check.** The PREREG checker asserts `inclusive_days(holdout_start_date, calendar_cap_date)` == the S3 artifact's `horizon_sensitivity.L_cap`. A start slip shifts both dates 1:1. Test: `test_cap_length_must_match_s3_horizon_sensitivity`.
- **Clamp edge case.** If a start slip hits the 2027-11-30 ceiling (:296), L_cap shortens.
  - The remedy is a new WP0a pin plus an S3 `horizon_sensitivity` re-run with the same seeds. The re-run REPLACES the old cell for the PREREG, and both cells stay in the record with their pin shas.
  - This is consistent with O-2 (no cell chosen after results), because the pin changed, not the results.

## (e) G8 vocabulary (:202, :28; PMR N4)
- **r3 said:** "A1 reachability PASS".
- **r4 says:** "S3 artefact sha with verdict **REACHABLE**". UNDERDETERMINED and UNREACHABLE make G8 false, and E2 requires REACHABLE.
- Test: `test_g8_false_when_s3_verdict_is_underdetermined`.

## (f) Post-STOP semantics (:19, :243; ruling O-1)
An A1 STOP:
- is **terminal** for this PREREG, with no restart; a new run is a new PREREG;
- sets the family halt row;
- cancels resting orders (spec §3 cancel-on-stop; none exist in shadow);
- writes `S5_A1_STOP_<date>.md`.

It is **neither FAIL nor a refutation**, and yields no PROPOSAL.

## (g) RA-13 advisory-only (:226 `ra13_review_note`, :298; ruling O-5)
`ra13_review_note` states:
- the RA-13 review date is 2027-01-25;
- unless a separate dated R4 ruling lands before it, the programme KILL backstop stands;
- the ≥ 300-position read lands after 2027-01-25 under every S5 start assumption, so the S5 report is **ADVISORY-ONLY** absent that R4 ruling;
- S2/S3 artifacts are inputs to R4, never a substitute for it.
