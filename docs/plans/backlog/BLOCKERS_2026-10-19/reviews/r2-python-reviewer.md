# r2 python-reviewer (focus: item 2, B5 pin table) -- READ-ONLY

Verdict: APPROVE (item 2 scope; items 1,3-5 not reviewed here). 2 nits, neither blocks.

## Verified at HEAD (src/breezy/analysis/hypothesis_ledger.py)
- register_hypothesis (:873): required keyword-only: hypothesis_id, hypothesis_class, registered_at (str), k_variants (int), freeze_commit (str), existing_records (Sequence[HypothesisRecord]). existing_records is NOT in the pin table: the run step must pass read_hypothesis_ledger(copy).
- NORMAL path requires non-None (else MissingRegistrationInputError): min_station_days, max_single_day_leg_share_cap, mde_at_allocated_alpha, mde_plausibility_bound, power_is_primary_only, mde_reference_ask, mde_fee_theta, mde_slippage_allowance, mde_variance_bound, station_day_statistic, order_quantity, look_policy. The pin table lists all 12. mde_variance_bound_justification is optional (None ok at 0.25).
- Types ok: int k_variants=1, min_station_days=200, order_quantity=1; floats elsewhere; bool power_is_primary_only=True; programme_alpha_override 0.025 passes the int/float, bool-excluded, (0, 0.05] guard (:PROGRAMME_ALPHA=0.05).
- Pinned constants match: max_single_day_leg_share_cap 0.20 (==MAX_SINGLE_DAY_LEG_SHARE), mde_fee_theta 0.0695 (EVIDENCED_FEE_THETA :204), variance 0.25 (VARIANCE_BOUND :196), statistic "MEAN_EXCESS_PER_TAKE" and look_policy "SINGLE_LOOK" accepted (checks :1060-1090 region; no refusal fires). k_variants 1 <= ceiling.
- Not passing re_arm_gating/horizon_days/variant_stratum_filters => schema v1; the v3 refusals (HORIZON_TOLLING_LANDED :166, PATH_B_SOURCE_GATE_LANDED :174, both False) sit AFTER the power check, so UNDERPOWERED is returned before them. Correct.
- MDE_MISMATCH_TOLERANCE = 1e-4 (:216). Confirmed. Compare is abs(recomputed - stated) > tol (:1119).
- Names exist: read_hypothesis_ledger(path: Path) (:1369), programme_budget_remaining(records) (:811), recompute_mde(*, per_variant_alpha, n_station_days) (:859).
- Hand-check MDE: alpha_v = 0.025/4/1 = 0.00625; z(0.99375) = 2.49771; z(0.80) = 0.84162; sum 3.33933; x sqrt(0.25)=0.5 -> 1.669665; / sqrt(200)=14.1421 -> 0.118063. Executed recompute_mde: 0.11806302799. Stating 0.1181 gives |diff| 3.7e-6 << 1e-4. OK.
- Ordering inside register_hypothesis: recompute (:1116) happens after the budget check; DuplicateHypothesisIdError and budget raise first. Live ledger has 4 records, all zero-look, programme_budget_remaining = 4 (executed read-only on the real file); ids H-ARCHIVE-RECAL-2026-09, H-FORECAST-TAKER-RUNG-SCREEN-2026-09-20, H-NO-SIDE-2026-09, H-OFFWINDOW-T4-2026-09. H-MAKER-NO-2026-10 is not a duplicate. Budget will not refuse.
- Ledger path: ~/.local/share/breezy/derived/hypothesis/hypothesis_ledger.jsonl EXISTS (3012 B, mode 0600, mtime Sep 28 18:22). ledger_path(default_derived_root()) (scripts/analysis/hypothesis_triage.py:146-154) resolves to Path.home()/.local/share/breezy/derived/hypothesis/hypothesis_ledger.jsonl UNLESS the derived-root env override (_DERIVED_ROOT_ENV_VAR) is set; hardcoding the path matches the default and avoids env drift. Good.
- Predicted outcome: 0.11806 > 0.08 -> UNDERPOWERED_NOT_REGISTERED, is_zero_look=True, allocated_alpha 0.0. Matches plan.

## Findings
1. plan_r2.md B5 "Run" step 4: cites read_hypothesis_ledger at `:1372-1395`; actual is `:1369-1392`. Fix: correct the line range (or cite the symbol only).
2. plan_r2.md B5 pin table: `hypothesis_register.py:235-239` etc. are unqualified; the file is scripts/analysis/hypothesis_register.py, not src/. Fix: prefix the path once so Grok does not search src/ (the plan also forbids importing it, so nobody should need it).
3. B5 pin table omits `existing_records`. Fix: add a row "existing_records | read_hypothesis_ledger(scratchpad copy) | step 4" so the kwarg set is complete and the call is one-shot.

## Cell endorsement (item 2)
I endorse the b=0.80, w=0.90 cell net of 0.01 slippage (0.089 - 0.01 = 0.079 -> 0.08). It sits on the design bid (B_CAP 0.80), uses a calibration (0.90) below P_MIN's 0.94 that the spec's adverse-selection falsifier makes the honest prior, and is chosen outcome-free. The w=0.94 cell (0.119) assumes perfect tail calibration and zero adverse selection, and only barely clears MDE (by ~0.0009, within a rounding choice), so it is the motivated reading. Caveat to keep in the ruling: any bound in [0.079, 0.118) gives the same UNDERPOWERED status, so the result is insensitive to rounding 0.079 vs 0.08.

Unit check: breakeven formula (:851-856) is a + theta*a*(1-a) + slippage, consistent with the plan's EV-per-contract description; theta check 0.0111/(0.16) = 0.0694 ~ 0.0695 OK (arithmetic only, SPEC file not re-read).
