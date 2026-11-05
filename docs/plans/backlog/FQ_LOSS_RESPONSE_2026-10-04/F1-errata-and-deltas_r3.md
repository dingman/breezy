# F1 FQ-PLAN r3: errata E-25..E-28 and the AUT-4 r12 and AUT-5 r8 deltas

<!-- F1 FQ-PLAN r3 (planner, 2026-10-06). DRAFT: not filed. It folds in the binding round-1 rulings FQ-R34..R44 and the binding round-2 rulings FQ-R45..R55. Once the coordinator accepts it, E-25..E-28 are appended to ARCH-ERRATA-rev9_2.md. -->

## Summary

- **Erratum numbers.** E-1..E-24 are filed. This revision uses:
  - E-25 (RC-1, e-process and e-LOND);
  - E-26 (RC-6, two model classes);
  - E-27 (BOOTSTRAP_SEED, from FQ-R35, amended by FQ-R46, FQ-R47, FQ-R48 and FQ-R52);
  - E-28 (RC-7 carve-out, from FQ-R36, reworded by FQ-R50).
  - Read FQ-plan "E-15" as E-25 and "E-16" as E-26, including the queue tokens of F7b, F11 and F13.
- **How v2 is armed (FQ-R35, FQ-R48).** v2 is armed through the env and the RC-5 live-orders ruling, the same way v1 was armed on 10-01. The registry seeds v2 later. The order is fixed:
  - **F9-A → F9-B (verified) → {P-1, P-2, GAP-16 pins} → bootstrap → P-3.**
  - Stage S follows F9-B.
  - ROOT_ADMIT and RESUME are not on the F9 path. E-27 now says explicitly that it amends RC-5's wording (FQ-R52).
- **F9 Needs** are {F8, shadow resume-bar PASS, F6, RC-5 ruling}. The coordinator authors the RC-5 ruling under the standing grant (FQ-R54 M4).
- **Round-2 outcomes:**
  - CONFLICT-13 is RESOLVED with option (d). F3 is being rebuilt on it now (FQ-R45).
  - CONFLICT-14 is RESOLVED by FQ-R46. Rule 4 from r2 is deleted and replaced by a precondition rewrite plus a validate rule: "MINT under a RETIRED root is refused".
  - GAP-16 is RESOLVED by FQ-R47 (a pins entry).
  - DEP-17 is RESOLVED by FQ-R48 (the explicit sequence).
  - CONFLICT-7 is RESOLVED by FQ-R52 (the rule-2 readings).
- **Still OPEN.** Only these two remain, and §R8-8 says why:
  - the F5 numeric values;
  - the GAP-13 F5 ruling.
- **Citation check (r3).** I re-checked every new `file:line` against the working tree at `40397c1a`. The only commits since `4ba7f10c` are docs. I used codegraph (`projectPath=/home/jon/breezy`) and direct reads. The lines checked are:
  - `validate.py:524-557`, `:589-632`;
  - `validate_ii.py:208-219`, `:248-264`;
  - `pins.py:146-164`;
  - `test_autonomy_pins.py:97-105`, `:113-122`, `:148-158`, `:364-369`;
  - `runtime/settings.py:106`;
  - all ten FQ-R45 readers, plus one more direct reader that FQ-R45 did not list (`test_persistence_exit_gate.py:51`, `:55-64`);
  - `test_trade_supervisor_phase1_unit.py:37`, `:85`;
  - `clear_family_halt_cli.py:88` (path `src/breezy/strategy/current_rung_hold/`);
  - ARCH `:35`, `:68-69`, `:264`, `:372`, `:472`, `:480`, `:607`, `:1255-1258`;
  - FQ plan r3 `:71-75`;
  - two of the nine FQ-R46 fold assertions as spot checks (`test_registry_fold_effects.py:401`, `test_registry_fold_tallies.py:655`). The other seven are the architect's evidence and are carried as is.
  - Line citations into AUT-4 r11, AUT-5 r7 and AUT-7 r5 are carried from r1 and were not re-checked, because codegraph indexes code only.

---

## Section 1: Erratum A (paste-ready)

## E-25 (coordinator, 2026-10-04; FQ r3 RC-1 as amended by FQ-R15, FQ-R20, FQ-R26, FQ-R37, FQ-R38, FQ-R39, FQ-R55; filed by F1 only, FQ-R19): e-process verdicts and the per-lineage e-LOND α schedule

**Numbering.** The FQ plan's "E-15" is already used by the network-namespace erratum, so this one is E-25. Every FQ-plan reference to E-15, including F7b's Needs token, reads E-25.

**Finding.**
- ARCH C4 (`:288-301`, `:323-346`) and AUT-4 r11 (§3.1 `:469-472`, §3.5 `:560-572`) allow only a fixed-n, single-look FORWARD_SHADOW under a geometric FWER schedule.
- PREREG v2 confirms on an anytime-valid, calendar-day e-process and controls FDR with per-lineage e-LOND.
- Neither the `verdict/v1` key set (`src/breezy/persistence/autonomy/verdict.py:178-184`) nor the window-cap rule (ARCH `:340-346`) can express that.

**Rule.**

1. **New verdict fields.** These are three nullable additions to `verdict/v1` `_KEYS`, and all three are in the identity body.
   - **`test_kind`** ∈ {`fixed_n`, `e_process`}.
     - Never null on FORWARD_SHADOW.
     - On LIVE_SEQUENTIAL it is `e_process` only when the family PREREG registers an e-process. LD-OBF families keep it null; `family_prereg_sha256` governs them.
     - Null on every other kind.
   - **`eta_ns`** (int, `e_process` only). The projected UTC ns at which n reaches `n_e_power[k]`, at `take_rate_lower`. Null when the nomination is infeasible or the test is `fixed_n`.
   - **`window_end`** (ISO date, FORWARD_SHADOW only, either test kind). The last forward climate day, inclusive, by AUT-4 `windows.py` arithmetic.

2. **`n_min_eff` is not redefined.**
   - It is null on every `e_process` verdict.
   - For `e_process`, `n_min` is F5's pre-registered earliest-look n. No PASS or FAIL is written below it.

3. **The e-process (FORWARD_SHADOW and LIVE_SEQUENTIAL `e_process`).** The unit is the settled calendar day d.
   - **Null H0_a (per take).** E[h_i | G_τi] ≤ BE_i, where:
     - h_i ∈ {0, 1} is the qty-1 payout;
     - BE_i = haircut `ask_exec` + fee, with the existing minimum-ask floor on the ask kept unchanged (FQ-R55.2);
     - G_τi is the information at the decision instant.
   - **The per-take term, with the upside clipped (FQ-R55.2).**
     - X_i = min(h_i/BE_i − 1, `X_max`), where `X_max` is pinned in the F5 design JSON.
     - The downside is never clipped, so X_i ≥ −1 still holds.
     - Clipping only lowers X_i, so E[X_i | G_τi] ≤ 0 under H0_a still holds. Validity is kept and the upside tail is bounded.
   - **Voids and ties (FQ-R55.4).**
     - A voided take enters as X_i = 0 (and S_i = 0 below). It takes its slot and is never dropped.
     - Takes at one decision instant are ordered by G-measurable keys only: (station, rung id), lexicographic. No outcome-dependent or arrival-order key is used.
   - **The daily statistic uses a denominator pinned before the day (FQ-R39, FQ-R55.1).**
     - Y_d = (1/m_d) · Σ_{i ≤ min(N_d, m_d)} X_i, where N_d is the number of takes on day d.
     - **m_d = `m_cap`** for every day. `m_cap` is pinned in the F5 design JSON, **provisionally 2**. F5's joint power MC chooses between {2, 3}. m_d no longer depends on the listing count L_d.
     - Empty slots (N_d < m_d) contribute 0. A day with no takes has Y_d = 0, which gives a factor of 1.
     - Takes are counted in decision order (ties as above). Takes beyond m_d are excluded from Y_d and disclosed in the metric `eprocess_uncounted_takes`.
     - −1 ≤ Y_d ≤ `X_max`.
   - **e_a.** e_a,t = Π_{d ≤ t} (1 + λ_d·Y_d).
     - λ_d is fixed at the start of day d from settled days only (the betting rule is pinned).
     - λ_d ∈ [0, λ_max], with λ_max ≤ 0.5 (FQ-R15), so every factor is ≥ 0.5.
   - **e_b, a betting e-process built directly rather than derived from a CS (FQ-R39).**
     - S_i = (a_i − y_i)² − (p_i − y_i)², where a_i is the ask-implied probability of the side bought, p_i is the model's probability of that side, and y_i is the outcome.
     - The null is H0_b: E[S_i | G_τi] ≤ 0.
     - Z_d = (1/m_d)·Σ_{i ≤ min(N_d, m_d)} S_i ∈ [−1, 1], using the same m_d, the same tie order and the same void rule.
     - e_b,t = Π (1 + μ_d·Z_d), with μ_d predictable and in [0, μ_max ≤ 0.5].
     - The BSS-on-takes CS is still reported, as a diagnostic only.
   - **The two nulls are different (FQ-R55).**
     - H0_a (no net edge against the haircut ask) and H0_b (no Brier improvement against the ask) are distinct hypotheses. Neither implies the other.
     - PASS asserts **both** alternatives. It is an intersection–union test: it rejects H0_a ∪ H0_b only when each one is rejected at α_k.
   - **Outcomes.**
     - **PASS:** min(e_a, e_b) ≥ 1/α_k on some settled day with n ≥ `earliest_look_n`, **and** the calibration guard is sufficient and not failing.
       - Ville's inequality bounds P_H0a(sup e_a ≥ 1/α_k) ≤ α_k, and likewise for H0_b. So the IUT has level α_k.
     - **FAIL (KILL):** the hedged CS on Y_d (clipped X), at level 1 − **α_kill**, has UB < 0.
       - **KILL's null (FQ-R55).** It is E[Y_d | F_{d−}] ≥ 0 after the haircut and the clip: "the clipped, haircut daily mean is not negative". It is **not** "the model has no edge". A model with a small true edge that the haircut, the fee and the clip remove can be killed. That is accepted as capital protection.
       - **α_kill = 0.05**, pinned in the F5 design JSON. It is separate from α_k, is never charged to `alpha_spent`, and is not part of e-LOND. Rationale: KILL is a capital-protection decision, not a discovery claim.
       - **Compounding (FQ-R55).** Each re-nomination runs a new KILL test, so false-kill risk compounds across a lineage's tests. The lifetime cap bounds it. By the union bound, P(any false KILL across a lineage's FORWARD_SHADOW tests) ≤ K_LIFETIME·α_kill = 4·0.05 = 0.20. Infeasible nominations run no test, and `max_infeasible_nominations` caps them (rule 6). Each LIVE_SEQUENTIAL `e_process` tenure adds at most α_kill. F5 reports the realised bound.
     - **UNDERPOWERED:** otherwise.
     - **`INCONCLUSIVE(window_end_no_crossing)`:** the window ended without a crossing.
     - PASS, FAIL and INCONCLUSIVE are final and are never reopened.
     - On LIVE_SEQUENTIAL `e_process`, WIN is PASS and KILL is FAIL. The detector map is unchanged.
   - **Why a pinned denominator and not per-take factors (FQ-R39).**
     - The per-take product Π(1 + λ X_i) with a start-of-day λ is a test supermartingale only if each factor has conditional mean ≤ 1 given the earlier factors.
     - Takes on the same station-day settle together and are dependent. Mixed-side takes on one station-day are positively correlated (L-40 i).
     - The linear daily form is valid under any within-day dependence, and with a take count that depends on intraday information. Each term has conditional mean ≤ 0 at its own decision instant, the tower property applies, and the slot weights 1/m_cap are fixed before the day.
     - The cost is dilution on days with N_d < m_cap. F5's joint MC chooses `m_cap` ∈ {2, 3} to trade that dilution against P(N_d > m_cap).
   - **Mandatory MC cases (F5, L-40 and L-41).** Type-I error of PASS ≤ α_k is required in both exact-null cases:
     - (i) **Intraday-informed take count.** Takes fire when an intraday observation signal crosses a threshold, outcomes are correlated with that signal, and the true conditional edge is exactly 0.
     - (ii) **Mixed-side same-station-day takes** with positive covariance.
     - Both cases run at each candidate `m_cap` ∈ {2, 3}, with the pinned `X_max`.

4. **α schedule.** Each lineage root pins `alpha_schedule` ∈ {`halving_v1`, `elond_heavy_tailed_v1`} in the policy block.
   - **`halving_v1`** is ARCH's α_total·2^−k_life, unchanged.
   - **`elond_heavy_tailed_v1`** gives α_k = α_total·γ_k·(R + 1), where:
     - γ_t = g(t)/Σ_{s=1..T} g(s), with g(t) = 1/(t·ln²(t+1));
     - T = `MAX_NOMINATIONS_PER_LINEAGE_LIFETIME` (`pins.py:38`, which is 4), unless F5 pins per-epoch budgets. The design JSON pins exactly one of the two;
     - R = the lineage's effective CHALLENGER→CHAMPION PROMOTE count before the nomination row's `ts_ns`. That is the fold's `promotions` (`fold.py:397-398`; `fold_tallies.py:62`, `:87`). PROMOTE reaches CHAMPION only from CHALLENGER (`transitions.py:72`; FQ-R43 CONFIRMED).
   - **Why R is safe.** R ≤ the true discovery count, because each such PROMOTE needs an accepted FORWARD_SHADOW PASS (ARCH `:476`). If `promotions` is window-pruned (E-21), R only shrinks, which is conservative.
   - **Frozen at test start.** `alpha_k` is computed once, inside the nomination's `BEGIN IMMEDIATE`, and written to the row. FORWARD_SHADOW copies it.
   - **No pooling** across lineages. `alpha_spent` = Σ row `alpha_k`.
   - **Pairing rule.** The policy loader refuses `elond_heavy_tailed_v1` on a `fixed_n` lineage and `halving_v1` on an `e_process` lineage.

5. **Error-rate statement (FQ-R39).**
   - **What is controlled.** e-LOND controls FDR ≤ α_total **within each lineage's nomination sequence**, under arbitrary dependence among that lineage's e-values.
   - **The null.** A false discovery is a PASS when H0_k holds, where H0_k = H0_a ∪ H0_b for nominee k: no net edge against the **haircut ask** (on the clipped scale), or no Brier improvement against the **ask**.
   - **What PASS does not test.** PASS does **not** test superiority over the incumbent champion. That comparison is the non-confirmatory OFFLINE_CHALLENGER / NOT_DISTINCT screen.
   - **Across lineages, nothing is controlled.** With L lineages, this erratum does not bound the programme-wide false-discovery proportion.
   - **The FWER bound.** At R = 0, Σ_k α_k ≤ α_total. ARCH's "Σα ≤ α_total per lineage" (`:334`) holds for `halving_v1` lineages only. That is the FWER-to-FDR substitution this programme adopts.

6. **`nomination_feasible`.**
   - **`fixed_n`:** unchanged (`n_min_eff ≤ n_cap`).
   - **`e_process`:** true iff **both** of these hold:
     - (a) ⌊`take_rate_lower` · forward days to `window_end` · `uptime_floor`⌋ ≥ `n_e_power[k]`.
       - `n_e_power` is a pinned policy-block table of the smallest n with **joint** MC power ≥ 0.8 for the PASS rule min(e_a, e_b) ≥ 1/α_k, at R = 0, at the pinned `m_cap` and `X_max` (FQ-R55.3).
       - It is never derived from e_a power alone.
       - This is arithmetic on named block keys only (AUT-4 r11 K1);
     - (b) **(FQ-R38, GAP-13)** an F5 ruling registers a forward-only shadow evidence source for the nominee. While none exists, every `e_process` nomination of a non-champion is infeasible.
   - **An infeasible nomination burns no K slot:** `alpha_k = 0`, `k_life` unchanged, `infeasible_nominations` +1, and the window slot is used. ARCH `:343-344` is unchanged.
   - **Cap (FQ-R39).**
     - A nomination is refused, and no row is written, when the lineage's `infeasible_nominations` (`fold_tallies.py:59`, `:83`) is ≥ the policy key `max_infeasible_nominations`.
     - A new code ceiling owned by ARCH-0, `pins.MAX_INFEASIBLE_NOMINATIONS_PER_LINEAGE_LIFETIME = 4`, bounds that key.
     - Rationale: infeasible nominations spend no α. Without a cap, a lineage can consume forward windows indefinitely, and can shop for a feasible window as `window_end` and the table index move. The cap only restricts.

7. **C5 row shape is unchanged.** All five `NOMINATION_FIELDS` stay required on a nomination (`registry_shape.py:41`, `:73-75`).
   - On an `e_process` row, `n_min_eff` holds the `fixed_n` value computed from the same block. It is disclosure only and never a gate.

8. **Evidence provenance (FQ-R37).**
   - No verdict PASS may rest on `source=backtest` rows. The evaluator enforces this: a statistic whose only input is backtest yields at most UNDERPOWERED, or a screen rejection.
   - The policy loader refuses a `forecast_quantile_ladder` lineage with `test_kind=fixed_n`.
   - Non-FQ fixed-n replay FS is unchanged and moot, because `pins.LIVE_GATE_ROUTED_KINDS` = {`forecast_quantile_ladder`} (`pins.py:23`).

9. **K_LIFETIME ≤ 4** stays a ceiling.

10. **Fixed-n-only rules.**
    - The single-look discipline (AUT-4 r11 §3.1) and the window-cap rule (ARCH `:340-346`) apply to `fixed_n` only.
    - `e_process` uses rules 3 and 6.

**Amends (the frozen text itself is not edited).**
- ARCH C4 `:288-301`, `:323-336` and `:340-346`.
- AUT-4 r11 §3.1, §3.1a, §3.5, §3.7, §3.8 and §7.
- The AUT-5 r7 policy key `alpha_spending` (`:599`).

**Consumption.**
- **ARCH-0 owner:**
  - three keys in `verdict.py:178-184`;
  - kind rules beside `_FORWARD_SHADOW_ONLY` (`:189`, `:264-270`);
  - the new pins ceiling (rule 6);
  - `persistence/autonomy/elond.py`.
- AUT-4 r12: F7b (WP2b).
- AUT-5 r8: policy keys and WP3 tests.
- **F5 design JSON pins:**
  - γ or T, δ_h, `n_e_power` (joint), `take_rate_lower`, `uptime_floor`, `earliest_look_n`;
  - `m_cap` (provisional 2; final ∈ {2, 3}), `X_max`, λ_max, μ_max, the betting rules, α_kill;
  - the parity n_par, δ_par and α_par, plus the parity bootstrap seed and replicate count (§R12-5), and `STALE_PARITY_H` (§R8-1).

**Tests (all ADD).**
- `test_c4_e_process_n_min_eff_null_with_eta_ns_window_end`
- `test_elond_alpha_matches_pinned_gamma_schedule` (FQ-R26)
- `test_alpha_frozen_at_test_start_per_lineage_no_pooling`
- `test_infeasible_nomination_burns_no_k_slot`
- `test_infeasible_nominations_capped_per_lineage`
- `test_e_process_nomination_infeasible_without_forward_shadow_source`
- `test_elond_schedule_refused_for_fixed_n_lineage`
- `test_elond_r_counts_only_effective_champion_promotes`
- `test_verdict_e_process_fields_null_on_other_kinds`
- `test_eprocess_daily_denominator_fixed_before_first_decision`
- `test_eprocess_m_d_is_pinned_m_cap_independent_of_listing_count` (FQ-R55.1)
- `test_eprocess_uncounted_takes_disclosed_never_entered`
- `test_eprocess_upside_clipped_at_x_max_downside_never_clipped` (FQ-R55.2)
- `test_kill_cs_uses_clipped_haircut_y` (FQ-R55.2)
- `test_eprocess_same_instant_ties_ordered_by_station_then_rung_id` (FQ-R55.4)
- `test_eprocess_void_take_enters_as_zero_never_dropped` (FQ-R55.4)
- `test_eprocess_null_mc_intraday_dependent_take_count`
- `test_eprocess_null_mc_mixed_side_same_station_day`
- `test_n_e_power_is_joint_power_of_min_ea_eb` (FQ-R55.3; F5 design-JSON test)
- `test_e_b_is_betting_process_not_cs_derived`
- `test_alpha_kill_pinned_separately_never_charged`
- `test_backtest_only_input_never_yields_pass`
- `test_policy_loader_refuses_fq_lineage_fixed_n`

**Fail-closed reading.** Until a merged ARCH-0 change consumes E-25, the exact-set reader refuses any verdict carrying `test_kind`, and F7b cannot merge.

---

## Section 2: Erratum B (paste-ready)

## E-26 (coordinator, 2026-10-04; FQ r3 RC-6 as amended by FQ-R20, FQ-R40; filed by F1 only): two FQ model classes

**Numbering.** The FQ plan's "E-16" is already used, so this one is E-26. The Needs of F11 and F13 read E-26.

**Finding.** Only `density_table` and `rung_recalibration` are admitted (ARCH C3 `:235-240`; AUT-3 r6 §3.1; `pins.MODEL_CLASS_COMPONENTS`, `pins.py:96`).

**Rule.**

1. **Two new classes.**
   - Add `forecast_quantile_ladder:density_table_multisource` and `forecast_quantile_ladder:variant_spec`.
   - `MODEL_CLASS_COMPONENTS` becomes `("density_table", "rung_recalibration", "density_table_multisource", "variant_spec")`. It is append-only.
   - `ROOT_ARTEFACT_COMPONENT` stays `"density_table"` (`pins.py:91`).
   - E-22(d) probing still requires exactly one match.
2. **Single writer.** Only AUT-3 `c3_writer.write_candidate` writes either class:
   - into a fresh `derived/artefacts/<model_class>/<sha>/`;
   - with `lineage/v1` and every C3 invariant (`ref_ts_lt_take_ts`, `no_sealed_holdout_rows_in_train`);
   - with one `refit_run/v1` per run.
3. **One mint slot.** ≤ 1 MINT per lineage per day across all four classes (ARCH `:323-325`).
4. **`density_table_multisource`.**
   - Inputs: US weather sources only. Never international data, venue prices or execution data (ARCH `:238-240`).
   - `data_windows` has one entry per source, each with its `content_sha256`.
   - It may be screened and forward-shadow-replayed. Becoming CHAMPION also needs the F13 ingest actor live, and a separately reviewed G11-style live-loader acceptance with parity tests.
5. **`variant_spec` (FQ-R40).**
   - **The variation lives in the artefact only.** A `variant_spec` child's manifest equals its committed root on every key outside the ARCH §4.2 allowlist (ARCH `:803-806`; `byte_binding.CHILD_MANIFEST_ALLOWLIST`, `byte_binding.py:82-91`).
   - `params` is a closed-key artefact object. Its keys come from the set the FQ live loader reads from an artefact, bounded by that loader (ARCH `:806`).
   - It never changes `taker_fee_coefficient`, `composition_kind` or `stations`.
6. **Nomination refusal (FQ-R40).**
   - A nomination of a child whose manifest differs from its root outside the §4.2 allowlist is **refused at nomination**.
   - Variation that needs a manifest change goes through new-family registration, never through a MINT.
7. **Forward freeze (FQ-R14).**
   - `variant_spec` `lineage.json` carries `spec_freeze_sha`.
   - `leakage_assertions` gains `nomination_days_after_spec_freeze`.
   - Scan and screen days never count as nomination evidence.

**Consumption.**
- `pins.py:96`, by the ARCH-0 owner.
- AUT-3 r7: `c3_writer` and the §3.1 table.
- F11 and F13.
- The AUT-4 OFFLINE_CHALLENGER screens all four classes.

**Tests (all ADD unless marked).**
- `test_model_class_components_append_only_four`. Any existing exact-set pin is widened by exactly these two entries in the same commit (SCOPE: widened by exactly two, never turned into a superset check).
- `test_c3_writer_only_writer_of_new_classes`. This must be a call-site AST check (FQ-R43).
- `test_mint_ceiling_shared_across_four_classes`
- `test_multisource_consumes_no_execution_data`
- `test_variant_spec_params_are_artefact_only`
- `test_variant_spec_refuses_theta_kind_or_new_station`
- `test_variant_spec_nonallowlisted_diff_nomination_refused` (FQ-R40)
- `test_variant_spec_nomination_days_after_spec_freeze`

**Fail-closed reading.** Until E-26 is consumed, `c3_writer` refuses both classes, and the replay probe finds no component, so it refuses.

**Carried to F10.** M1 cells are (side, ask bin). The FQ manifest has no such key (`pm_us_crh_fq_v1.json:1-20`), and a child cannot vary it. An M1 survivor therefore needs either a reviewed FQ manifest-schema extension (outside E-26) or a new family (FQ-R40).

---

## Section 3: Erratum C (paste-ready)

## E-27 (coordinator, 2026-10-04; FQ-R35 as amended by FQ-R46, FQ-R47, FQ-R48, FQ-R52): BOOTSTRAP_SEED CHAMPION is the venue's sending FQ root

**Amends RC-5 (FQ-R52).** This erratum amends FQ r3 RC-5's "F9 arms v2 through registry ROOT_ADMIT/RESUME" (`FQ-LOSS-RESPONSE_plan_r3.md:74`). It now reads:
- v2 is armed by the env and the RC-5 live-orders ruling (F9-A, F9-B).
- v2 enters the registry as the `BOOTSTRAP_SEED` CHAMPION.
- Neither ROOT_ADMIT nor RESUME is on the F9 path.

**Rule.**

1. **The CHAMPION seed.** In ARCH `:472` and `:737-738`, the `pins.BOOTSTRAP_SEED` CHAMPION reads "the venue's sending FQ root at bootstrap".
   - For polymarket_us this is `pm_us_crh_fq_v2`.
   - `pm_us_crh_fq_v1` is seeded **RETIRED**, beside v4, cont and `pm_us_crh_v2`.
   - The pair BOOTSTRAP (∅, RETIRED) is allowed (`transitions.py:69`).
   - **Evidence that this is safe now:** no bootstrap has run, and `BOOTSTRAPPED_ROOT_MANIFEST_SHA256` is empty (`pins.py:99-100`; asserted by `test_empty_pins_at_arch0`, `test_autonomy_pins.py:104`).

2. **Other mentions of `fq_v1` (CONFLICT-7; FQ-R52).**
   - **Readings.** Where ARCH C3, C5, §5.3 or §10 names `fq_v1` as drill root, incumbent or rollback target (`:264`, `:480`, `:607`, `:1255`, `:1258`), it reads "the venue's FQ CHAMPION at drill time".
   - **The drill child.** `pm_us_crh_fq_v1_r0001` (`:1256`) reads `<champion>_r0001`. With v2 seeded, that is `pm_us_crh_fq_v2_r0001`.
   - **Historical, with no new reading.** These lines record the state at Rev 9.2 and are not re-read:
     - `:35` (G1, "currently `pm_us_crh_fq_v1`");
     - `:68-69` (G34, G35);
     - AUT-7 r5 `:29`, the ARCH §10 quote.

3. **Ordering (FQ-R48).**
   - The sequence is binding: **F9-A → F9-B (verified) → {P-1, P-2, GAP-16 pins} → bootstrap → P-3.**
   - P-1 also lands after F3 (FQ-R33).
   - The seed CHAMPION must hold its own `_LIVE_ORDERS_ALLOWLIST` triple at the P-1 commit.
   - E-24 holds: v2 has no registry row before F9-A.
   - Stage S follows F9-B. No session before F9-B ever counts toward L1.

4. **Seeded-retired lineages (FQ-R46; replaces r2 rule 4, which is deleted).**
   - **(a) The W15 clear precondition.** FQ-R34's precondition for clearing v1's standing halt reads: "the fold shows v1 RETIRED **and no family of v1's lineage is in any other state**".
     - The fold flag `terminal_frozen` is not part of the precondition.
     - The fold is unchanged. A BOOTSTRAP → RETIRED row sets no freeze, so every existing `terminal_frozen` assertion stays byte-unchanged.
   - **(b) The validate rule, owned by ARCH-0 and restrictive only: "a MINT is refused when every family of its lineage is RETIRED".** (FQ-R56; narrowed from r3's "lineage root is RETIRED". The broader rule conflicted with ARCH `:489`, under which a superseded root routinely ends RETIRED in a healthy lineage.)
     - It is added to `_CHECKS[Kind.MINT]` (`validate.py:526`) beside `ii.mint_rate` (`validate_ii.py:248-264`), as a new `validate_ii` check with a new `RuleII` member, refusing with `FAIL`.
     - The lineage's family states are read from `ctx.states`, which starts as the prior fold and is advanced by the earlier immediate rows in the batch (`validate.py:604`, `:623-624`). So a MINT that follows, in the same batch, a row that retires the lineage's last non-RETIRED family is also refused.
     - The check runs after `ii.mint_rate`, so the RED tests use the day's first MINT.
     - **SCOPE (FQ-R56):** `RULE_II_NAMES` (`tests/unit/test_registry_validate_ii.py:1254`, used by `test_every_rule_ii_name_is_unique_and_wired`) is widened by exactly the one new name, in the same commit.
     - **Why this is needed.** Y10 `terminal_frozen` (`validate_ii.py:208-219`) guards only →CHAMPION rows. MINT's checks today are `ii.mint_rate` alone (`validate.py:526`). So nothing currently stops a MINT in an all-RETIRED lineage. With this rule, (a) stays true once it holds.

**Unchanged.**
- ROOT_ADMIT (ARCH `:479`) stays the recovery path after a KILL or a TERMINAL event, including its U2 standing-halt rule.
- `ROOT_ADMIT_ENABLED_CEILING` stays `False` (`pins.py:22`).

**Consumption.**
- **ARCH-0 owner, as pins and validate commits:**
  - The `BOOTSTRAP_SEED` re-pin (P-1).
  - The `BOOTSTRAPPED_ROOT_MANIFEST_SHA256` rows (P-1).
  - **The GAP-16 pins entry (FQ-R47):** `pins.DEFAULT_RESTRICTIVE_CLASS` (`pins.py:148-164`; ARCH `:372` names this literal) gains `"parity.fq_v2_shadow_live": ("DEMOTE", "RECOVERABLE_MODEL")`. It lands at or before P-1.
  - The rule 4(b) MINT check in `validate.py` and `validate_ii.py`.
- AUT-5 r8: §R8-3 line 172; §R8-4.
- AUT-7 r6: the retargets (§R8-3).

**Tests.**
- **SCOPE (re-pin)** `tests/unit/test_autonomy_pins.py::test_literal_identity_pins` (`:113-122`). The exact-equality assertion on `pins.BOOTSTRAP_SEED` is kept. The expected literal becomes the E-27 seed (`pm_us_crh_fq_v2` CHAMPION; v1, v4, cont and `pm_us_crh_v2` RETIRED) in the P-1 commit.
- **SCOPE (re-pin)** `test_autonomy_pins.py::test_empty_pins_at_arch0` (`:97-105`). The `BOOTSTRAPPED_ROOT_MANIFEST_SHA256 == {}` assertion (`:104`) keeps exact equality, re-pinned to the exact five-row P-1 literal. The `MappingProxyType` check (`:105`) is byte-unchanged. `test_bootstrapped_root_manifests_unchanged` (`:359-361`) is byte-unchanged and then hashes those five files.
- **ADD (assertion)** to `test_default_restrictive_class_is_demote_or_halt_with_known_classes` (`test_autonomy_pins.py:148-158`): `assert table["parity.fq_v2_shadow_live"] == ("DEMOTE", "RECOVERABLE_MODEL")`. The existing assertions are byte-unchanged. The test pins no exact key set, so no widening is needed.
- ADD `test_bootstrap_seed_champion_has_live_orders_triple`
- ADD `test_policy_halt_mirror_on_seeded_retired_family_writes_no_row_and_no_freeze`
- ADD `test_mint_in_all_retired_lineage_refused` (FQ-R46, FQ-R56)
- ADD `test_mint_after_lineage_fully_retired_earlier_in_same_batch_refused` (FQ-R46, FQ-R56, the batch-aware read)
- ADD `test_mint_allowed_when_root_retired_but_lineage_has_live_family` (FQ-R56: a superseded root that is RETIRED does not block MINT in a healthy lineage)
- **Verify-first (FQ-R46, blocking).** List every existing test that writes a MINT in a lineage whose families are all, or all become, RETIRED. If any exists, STOP for a ruling. Its assertion is never edited to pass.
- **Dropped:** r2's `test_seeded_retired_lineage_is_terminal_frozen`. It was an r2 proposal that never merged, and its rule is rejected.

---

## Section 4: Erratum D (paste-ready)

## E-28 (coordinator, 2026-10-04; FQ-R36 as reworded by FQ-R50): RC-7 carve-out from AUT-5a's `app/trade.py` ownership

**Rule.**
- The ARCH §5.1 sentence "`app/trade.py` … belong[s] to AUT-5a alone" (`:1049-1051`) reads: "except that FQ r3 row F6 may change `_compose_forecast_quantile_ladder` (`app/trade.py:676`) once. **F6 merges before any row-7 WP that edits `app/trade.py` (WP5).**"
- **"Row 7 merged" means that row 7's last WP has merged.**
- Row-7 WPs that do not edit `app/trade.py` may merge before F6 (FQ-R48). Work after row 7 merges, such as F13, is outside AUT-5a's in-flight exclusivity and is unaffected.

---

## Section 5: AUT-4 r12 delta (paste-ready; round r12 over r11; ARCH Rev 9.2 + E-1..E-28)

**Header.**
- r12 consumes E-25 to E-28, FQ-R13..R33, FQ-R34..R44 and FQ-R45..R55.
- r1..r11 are unchanged.
- **Type key:**
  - ADD = new text, a new test, or a new assertion in an existing test whose existing assertions stay byte-unchanged.
  - SCOPE = an existing test keeps its name and its assertion form; only its fixture or parametrisation is narrowed, or an exact pin is re-pinned or widened by exactly the named items.

### §R12-1 Work-package split (FQ-R19, FQ-R30, FQ-R42, FQ-R51, FQ-R53): F7a is stats-only

**WP1s (queue F7a, Needs F1).**
- **Scope.** Move these five §3.3 modules byte-identically into `src/breezy/analysis/stats/`: `sequential_looks.py`, `group_sequential_boundaries.py`, `scoring_core.py`, `market_baseline.py`, `drift_freshness.py`.
- **Wrappers (FQ-R42).** The scripts become thin wrappers that **re-export every moved name**.
  - Verify-first: list the script importers with codegraph callers of each moved symbol under `scripts/` (`projectPath=/home/jon/breezy`).
  - `test_script_wrappers_delegate` checks every re-exported name by `is` identity (SCOPE: parametrised over the stats set plus the importers).
- **Verify-first (import closure).** In a fresh process, record each module's runtime import closure. A module that reaches `breezy.runtime`, `breezy.strategy`, `…adapters…exec` or any of the ten §3.9b files stays in row 10.
- **RED / GREEN.**
  - `test_moved_functions_byte_identical` and `test_script_wrappers_delegate` (SCOPE: stats set).
  - These stay byte-unchanged and green: `test_aud07_live_rule_crossing_sim.py`, `test_family_tally_v2_look_loop_golden.py`, `test_nbp_shadow_parity_live.py`.
- **Gates.**
  - The full gate passes (`EXIT=0`), and `lint-imports`, run from inside the tree, reports "N kept, 0 broken".
  - `git diff --exit-code <base> HEAD -- <ten §3.9b paths>` is empty.
  - `git diff --name-only` ⊆ {stats files, wrappers, `tests/unit/analysis/stats/**`}.
- **Activation proof (FQ-R51; replaces r2's next-firing-only proof).** There is no node restart or respawn.
  1. **Pre-flight (FQ-R53).** Run the H1 acceptance text (§R8-4, "Ops-step acceptance") for this step. It prints:
     - the resolved absolute paths of the `family_tally_v2` wrapper at both the base sha and the merge sha;
     - the frozen input snapshot directory and its content sha256;
     - the output paths;
     - the confirmation that `a8a66f41` is an ancestor of HEAD.
  2. **Frozen snapshot.** Copy the timer's inputs, read-only, to a snapshot directory outside the repo, and record their sha256.
     - Verify-first: run the base-sha wrapper twice on the snapshot. If the two outputs differ, the report is not deterministic. Then STOP for a ruling. Never mask fields to make the bytes match.
  3. **Hand run, before and after.** Run `family_tally_v2` once at the base sha and once at the merge sha on the same snapshot.
     - Each run is a `systemd-run --user --wait` unit with the deployed scorer memory-cap convention and `-p LimitNOFILE=524288`.
     - Only one heavy job runs at a time. Never run either while a nightly study is running.
  4. **Byte-compare** the two outputs. They must be equal.
  5. **Watch the next timer firing.** Record its exit code. It must be 0.
  6. **Read-back.** Record the snapshot sha, both output shas, the compare result and the timer exit code in the step's ops record.

**WP2 (F7a):** as in r11 (`:1286-1304`), after WP1s. Reliability binning reuses `analysis/brier_decomposition.py` (`bin_by_edges` `:106`, `murphy_decomposition` `:177`) and `stats/scoring_core.py` (FQ-R41).

**WP2b (F7b, Needs E-25, F4, F7a):** see §R12-3.

**Row 10 keeps:** WP1r and WP3–WP9.

### §R12-2 Section-by-section changes

| r11 § | Change | Type |
|---|---|---|
| §0 | r12; E-1..E-28; FQ-R13..R55 | ADD |
| §1 table | Rows: e-process (pinned m_d = `m_cap`, clipped X, e_a, e_b), α_kill CS, e-LOND, `evidence_row/v1` with `LoadedEvidence`, parity detector (§R12-5) | ADD |
| §2 reuse | **e-process/CS:** nothing anytime-valid in the repo; build. **e-LOND:** build in persistence. **Reliability:** reuse `brier_decomposition.py:106,:177` before writing new code (FQ-R41). **FqEvaluator stats:** `scoring_core`, `market_baseline` | ADD |
| §3.1 single look | Prefix "For `test_kind=fixed_n`:". New `e_process` paragraph per E-25 rule 3 | SCOPE + ADD |
| §3.1 "nothing to evaluate" | Nomination-row fields per E-25 | SCOPE |
| §3.1 fail-closed | Any `evidence_row` that is untagged, has an unknown or unaccepted tag, has `ref_ts ≥ take_ts`, is not `type(r) is EvidenceRow`, or did not arrive inside a `LoadedEvidence` is ERROR plus CRITICAL. A backtest-only PASS is impossible (E-25 rule 8) | ADD |
| §3.1a | `test_kind`, `eta_ns`, `window_end`; FS `n_min` = earliest-look n for `e_process` | ADD |
| §3.2 | The sign-flip permutation is primary for `fixed_n`; `e_process` uses clipped Y_d (E-25 rule 3) | SCOPE |
| §3.3 | New rows (§R12-3). r3's `fq_evaluator.py` resolves to r11 `evaluators/forecast_quantile_ladder.py` (DEDUP-1) | ADD |
| §3.5 nomination | `e_process` branch per E-25 rules 4, 6, 7. `nomination.py` imports `alpha_k` from `persistence/autonomy/elond.py`, the single definition (FQ-R41). Inputs gain `test_kind`, `alpha_schedule`, `gamma_norm_T`, `n_e_power`, `take_rate_lower`, `max_infeasible_nominations`, fold `promotions` and `infeasible_nominations` | ADD |
| §3.5 window-end | Scoped to `fixed_n`; `e_process` rule added | SCOPE + ADD |
| §3.6 LIVE_SEQUENTIAL | `e_process` family: WIN = PASS, KILL = FAIL; `source=live` only. `PREREG_FQ_v1` stays for v1's closing tally | ADD |
| §3.7 look rule | Scoped to `fixed_n`; `e_process` per E-25 rule 3 | SCOPE + ADD |
| §3.8 feasibility | Keys: `test_kind`, `alpha_schedule`, `n_e_power` (joint), `take_rate_lower`, `earliest_look_n`, `m_cap`, `x_max`, `eta_ns`. `feasibility_consistency`: `eta_ns ≤ window_end` | ADD |
| §3.10 R-D | α_k per lineage `alpha_schedule` | SCOPE |
| §3.10 detector map | `parity.fq_v2_shadow_live` → DEMOTE (RECOVERABLE_MODEL), in both the policy `detector_map` (P-3) and `pins.DEFAULT_RESTRICTIVE_CLASS` (E-27; FQ-R47) | ADD |
| §4 WP1/WP2 | Split per §R12-1 | SCOPE |
| §5 association | WP1s, then WP2 (F7a); WP2b (F7b); WP1r (row 10). **C6 (FQ-R41):** FqEvaluator **replaces** the `"forecast_quantile_ladder": RefusingPlugin()` entry at `analysis/autonomy/offline_plugins.py:18`. No `analysis/plugins.py` is created. F4 verify-first: confirm that no AUT-2 r7 WP needs a new plugin registry file | ADD |
| §6.4 prerequisites | Row 12 = E-25 filed. Row 13 = F5 design JSON with every E-25 consumption key, including the parity look date against the KILL date | ADD |
| §7 store query (2) | `… and .test_kind!="e_process" …` | SCOPE |
| §7 nomination accounting | Any Σα ≤ α_total check is scoped to `halving_v1` (FQ-R43). For elond: `alpha_spent == Σ row alpha_k`, and each `alpha_k == elond(k, R_at_row)` | SCOPE + ADD |
| §8 risks | FDR not FWER, per lineage only (E-25 rule 5). R is conservative. m_cap dilution. False-kill compounding ≤ K_LIFETIME·α_kill (E-25 rule 3). **Power record (FQ-R39, FQ-R55.3): PROVISIONAL AND OPTIMISTIC.** The r2 figures (with n ≤ 100 before 2027-01-25: ≈ 50% at ROI ≈ 50%, ≈ 80% at ROI ≈ 60–80%) are e_a-only and pre-clip. They are restated from F5's joint min(e_a, e_b) MC at the pinned `m_cap` and `X_max`. Until then, no feasibility or scheduling decision may rely on them | ADD |
| §9 | Unchanged. Caps are never read; `m_cap`, `X_max`, `n_e_power` and the take rate are PREREG design values | none |

### §R12-3 WP2b (F7b): e-process, e-LOND, `evidence_row`, FqEvaluator

**Modules.**

- **`analysis/autonomy/eprocess.py`.** Y_d and Z_d with m_d = `m_cap`, clipped X, ties ordered by (station, rung id) and voids as 0, then e_a and e_b, all exactly as in E-25 rule 3.
  - λ_d and μ_d are computed from settled days and frozen before the day's first decision.
  - It records `eprocess_uncounted_takes`.
- **`analysis/autonomy/confidence_sequence.py`.** The hedged CS on clipped Y_d at 1 − α_kill (KILL when UB < 0), and the diagnostic BSS CS.
- **`persistence/autonomy/elond.py` (LAYER-1, FQ-R41).**
  - Pure stdlib plus `Decimal`: `gamma(t, T)` and `alpha_k(k, R, schedule, alpha_total)`.
  - `nomination.py` imports it. Analysis re-imports it and never redefines it.
  - The ARCH-0 owner reviews it.
- **`analysis/autonomy/evidence_row.py` (FQ-R37, FQ-R54 M2).**
  - **Honesty statement (FQ-R54 M2).** The module-private token and the bans below are an **accident guard, not a security boundary**.
    - In-process Python code that wants to forge an `EvidenceRow` can always do so, for example through `gc`, `ctypes` or reading module globals.
    - The guard makes forgery impossible to do by accident and visible in review and in AST tests. Real provenance assurance comes from the store-kind-derived path, `ref_ts < take_ts` at load, and the reviewed consumer table below.
  - `load_evidence_rows(store_kind)` is the only constructor. It **derives the path from `store_kind`** through a closed mapping and takes no path argument:
    - C2 label store → `live`;
    - node C1 shadow Takes → `shadow`;
    - harness or `fs_replay` → `backtest`.
  - It returns a sealed **`LoadedEvidence`** container (FQ-R54 M2):
    - a final, frozen class whose constructor takes the same module-private token as an `InitVar`;
    - it holds an immutable tuple of rows plus the `store_kind`;
    - consumers accept only `type(x) is LoadedEvidence`, and never a bare sequence of rows.
  - `EvidenceRow` is a frozen dataclass and is **final** (FQ-R54 M2):
    - `__init_subclass__` raises `TypeError`, and it is decorated `typing.final`.
    - Its constructor takes a module-private token as an `InitVar` with no default, so `dataclasses.replace` raises.
  - `__copy__`, `__deepcopy__`, `__reduce__`, `__reduce_ex__` and `__setstate__` raise `TypeError`.
  - Every consumer checks `type(r) is EvidenceRow` for each row, and never uses `isinstance` (FQ-R54 M2).
  - **AST bans, in `src/`:**
    - `object.__setattr__` on an `EvidenceRow`;
    - any `object.__new__(EvidenceRow)` or `object.__new__(LoadedEvidence)`;
    - in `src/breezy/analysis/autonomy/**`, any call to `pickle.load`, `pickle.loads` or `pickle.Unpickler`, and any `__setstate__` definition (FQ-R54 M2).
  - `ref_ts < take_ts` is enforced at load. C2 gains no column.
  - Accepted tags per consumer:

    | Consumer | Accepts |
    |---|---|
    | FqEvaluator `e_process` (FS, resume bar) | {shadow}, from a registered forward-only source (E-25 rule 6b) |
    | `eval_live` LIVE_SEQUENTIAL | {live} |
    | `eval_offline` `fixed_n` FS | {backtest}; non-FQ only; can never yield PASS for FQ (E-25 rule 8) |
    | parity detector | {live, shadow}, `subject = pm_us_crh_fq_v2` only |
    | AUT-S screen (F11) | {backtest}, reject-only |

- **`evaluators/forecast_quantile_ladder.py` (FqEvaluator, DEDUP-1).**
  - It computes BSS on takes and on all decisions, per-rung PIT, the reliability slope via `murphy_decomposition`, Spiegelhalter Z with a blocking minimum sample, and net P&L per day.
  - It refuses PASS on backtest-only input.
  - It is registered by replacing `offline_plugins.py:18`.

**Tests, RED first (all ADD unless marked).**
- The r3 F7b list, with `test_elond_equals_geometric_at_zero_discoveries` replaced by `test_elond_alpha_matches_pinned_gamma_schedule` (FQ-R26).
- `tests/unit/autonomy/test_elond.py`:
  - `::test_elond_schedule_refused_for_fixed_n_lineage`
  - `::test_elond_r_counts_only_effective_champion_promotes`
  - `::test_elond_single_definition_in_persistence` (`is` identity, FQ-R41)
- `tests/unit/autonomy/test_nomination.py`:
  - `::test_e_process_feasible_from_pinned_power_table`
  - `::test_e_process_row_n_min_eff_is_fixed_n_disclosure`
  - `::test_infeasible_nominations_capped_per_lineage`
  - `::test_e_process_nomination_infeasible_without_forward_shadow_source`
- `tests/unit/autonomy/test_forward_shadow.py`:
  - `::test_e_process_fs_copies_row_columns_except_n_min_eff`
  - `::test_e_process_terminal_outcome_final`
  - `::test_e_process_window_end_no_crossing_inconclusive`
- `tests/unit/autonomy/test_eprocess.py`: every E-25 rule-3 test, including both null MC cases, the m_cap, clip, tie and void tests, and `test_kill_cs_uses_clipped_haircut_y`.
- `tests/unit/autonomy/test_eval_live.py::test_live_sequential_e_process_win_pass_kill_fail`
- `tests/contract/test_nomination_columns_contract.py::test_called_inside_begin_immediate_with_e_process_keys`
- `tests/unit/autonomy/test_verdict_schema.py::test_verdict_e_process_fields_null_on_other_kinds`
- `evidence_row` tests:
  - `test_evidence_row_single_loader_contract`
  - `test_load_evidence_rows_accepts_no_path_argument`
  - `test_evidence_row_cannot_be_forged_via_replace_or_pickle`
  - `test_evidence_row_copy_refused`
  - `test_evidence_row_object_setattr_banned_by_ast`
  - `test_evidence_row_is_final_subclass_refused` (FQ-R54 M2)
  - `test_evidence_row_object_new_path_refused_by_consumers_and_banned_by_ast` (FQ-R54 M2). An instance built through `object.__new__` is refused by every consumer's type and token check, and the AST ban flags the call site.
  - `test_consumers_require_exact_type_evidence_row` (FQ-R54 M2; a subclass or duck-typed row is refused)
  - `test_loader_returns_sealed_loaded_evidence_and_consumers_require_it` (FQ-R54 M2)
  - `test_no_pickle_load_or_setstate_in_analysis_autonomy_ast` (FQ-R54 M2)
  - `test_ref_ts_lt_take_ts_enforced_at_load`
  - `test_backtest_only_input_never_yields_pass`
  - `test_policy_loader_refuses_fq_lineage_fixed_n`
- Per consumer, the untagged and unknown-tag refusals: `test_fq_evaluator_refuses_untagged` and `…_unknown_tag`; likewise for `eval_live`, `eval_offline_fs` and `parity_gate`. Also `test_shadow_rows_never_enter_live_sequential`.

**Verify-firsts (blocking, FQ-R43).**
1. **Verdict-id golden fixtures.** The three new keys enter the identity body, so every verdict id changes. List every golden or fixture verdict id, and every test pinning the `verdict/v1` key set. In the same reviewed commit:
   - re-derive the ids from the spec, never from the code under test (SCOPE: re-pin);
   - widen the key-set pins by exactly three (SCOPE).
2. **`$STATE/derived/verdicts/` is empty.** If it is not, STOP for a ruling.
3. **Σα ≤ α_total checks.** Grep the tests and the code for any such check, and scope each one to `halving_v1`.
4. **R.** CONFIRMED (`fold.py:386-401`; `transitions.py:72`). Residual check: whether lineage `promotions` is window-pruned. If it is, record that R is conservative.
5. **`test_c3_writer_only_writer_of_new_classes`** is a call-site AST check (E-26).

**Gates.**
- The full gate.
- `lint-imports` with the "live path never imports analysis" contract kept.
- The firewall and exec-import-pin guards in the focused gate.
- **Activation:** offline, with no respawn.

### §R12-4 r11 tests: scoped (names and assertions byte-unchanged; fixtures use `test_kind=fixed_n`, `alpha_schedule=halving_v1`)

As in r1 §R12-4, all **SCOPE**:
- the eight `test_forward_shadow.py` tests;
- `test_feasible_nomination_charges_alpha_k_life` and `test_inputs_are_named_block_keys_only`;
- `test_called_inside_begin_immediate_with_named_keys`;
- `test_b_max_covers_k_lifetime_over_three`;
- `test_n_min_is_first_look_n`;
- §7 query (2) and the nomination-accounting check.

**Unchanged:** every other r11 test. **No test is weakened.**

### §R12-5 Parity continuation detector (FQ-R29, FQ-R35, FQ-R39, FQ-R55), built in WP2b

- **Detector.** `parity.fq_v2_shadow_live`, kind DRIFT, produced under the existing `eval_live` producer id.
- **Fill-conditioned null (FQ-R39).**
  - For each v2 `source=live` fill i, take the same decision's `source=shadow` record.
  - Live and shadow share the outcome, so the paired difference is execution-only: D_i = (shadow haircut `ask_exec` + shadow fee) − (fill_px + live fee).
  - Only filled decisions enter. Unfilled shadow decisions are excluded and reported as a fill-rate metric, which stays in `drift.fill_rate_slippage`'s domain.
  - The selection effect is reported, never gated.
  - Null (continue): E[D | filled] ≥ −δ_par.
- **Interval (FQ-R55).**
  - The mean D is **qty-weighted** over fills.
  - Its one-sided (1 − α_par) upper bound comes from a **day-clustered bootstrap**: settled climate days are resampled with replacement, and all of a day's fills move together. This respects within-day dependence.
  - The bootstrap **seed** and the replicate count are pinned in the F5 design JSON.
- **Single look, at n_par v2 live fills.**
  - FAIL when the upper bound is < −δ_par.
  - Before the look: UNDERPOWERED, which never acts.
  - F5 pins n_par, δ_par and α_par (`test_design_json_pins_parity_look_metric_threshold`).
- **Look date against the KILL date (FQ-R39).**
  - t_par = F9-B arm date + ⌈n_par / (`take_rate_lower`·`uptime_floor`)⌉ days.
  - F5 and the F9 evidence state t_par next to the KILL date (2027-01-25).
  - If t_par > KILL date − 14 d, F5 either lowers n_par (and recomputes the parity power) or records the gate as **infeasible before KILL**. In that case F9's acceptance states that continuation protection rests on F6 and `live.drawdown` alone.
- **Actuation (FQ-R35, FQ-R47).**
  - Before bootstrap: a FAIL makes the F6 composed veto refuse, and the refusal latches (§R8-1).
  - After bootstrap: a FAIL causes DEMOTE (RECOVERABLE_MODEL) through the AUT-5a engine.
    - The class comes from the P-3 policy `detector_map`, or, before P-3, from `pins.DEFAULT_RESTRICTIVE_CLASS` (GAP-16).
  - Both paths only restrict, so overlap after bootstrap is safe.
- **Tests (all ADD).**
  - `tests/unit/autonomy/test_parity_gate.py`:
    - `::test_parity_gate_action_is_demote_only`
    - `::test_parity_gate_reads_v2_rows_only`
    - `::test_parity_single_preregistered_look`
    - `::test_parity_underpowered_never_acts`
    - `::test_parity_null_is_fill_conditioned_execution_difference`
    - `::test_parity_unfilled_shadow_decisions_excluded_and_reported`
    - `::test_parity_interval_is_day_clustered_bootstrap_with_pinned_seed` (FQ-R55)
    - `::test_parity_mean_is_qty_weighted` (FQ-R55)
  - `tests/unit/autonomy/test_engine_restrictive_fallback.py::test_parity_fail_without_policy_demotes_via_default_restrictive_class` (FQ-R47)

---

## Section 6: AUT-5 r8 delta (paste-ready; with the consequential AUT-7 r6 retarget table)

**Header.** r8 over r7. It consumes E-10..E-28, FQ-R13..R55 and AUT-4 r12. r1..r7 are unchanged.

### §R8-1 RC-7 carve-out (FQ-R17, FQ-R36, FQ-R50, FQ-R54 M1, E-28)

**Text added to §5, "Order and parallelism" (`:979`).** "Per E-28, `_compose_forecast_quantile_ladder` (`src/breezy/app/trade.py:676`) is carved out of AUT-5a ownership for one change, F6.
- It wraps the `submit_veto` returned by `_open_halt_latch_preamble` (`trade.py:506`, called at `:709`).
- It is an add-only OR: it refuses wherever the old veto refused. It evaluates the family halt **first**, then the loss stop, then the parity verdict (FQ-R35).
- One callable object reaches both the strategy and the exec client.
- **F6 merges before any row-7 WP that edits `app/trade.py` (WP5).** 'Row 7 merged' means its last WP merged. Row-7 WPs that do not edit `app/trade.py` may merge before F6 (FQ-R48)."

**Parity staleness pin (FQ-R54 M1).**
- `STALE_PARITY_H` is a named module constant in the F6 probe module.
- Its value is taken from the F5 design JSON and pinned by `test_stale_parity_h_equals_design_json` (ADD).

**F6 tests (all ADD).**
- `test_composed_veto_is_or_add_only_refuses_wherever_old_refused`. A property test over the old veto's refusal domain.
- `test_composed_veto_is_single_object_shared`
- `test_composed_veto_evaluates_both_returns_halt_first`
- `test_same_veto_callable_reaches_strategy_and_exec_client`
- `test_loss_stop_input_missing_refuses_after_halt_branch`
- `test_loss_stop_input_stale_refuses_after_halt_branch`
- `test_loss_stop_input_raising_refuses_after_halt_branch`
- `test_stale_veto_fails_closed_with_alert_sink_down` (FQ-R36). `test_stale_veto_applies_even_when_alert_undelivered` (FQ-R31) is kept.
- `test_composed_veto_refuses_on_accepted_parity_fail`
- `test_composed_veto_refuses_when_parity_verdict_missing_or_stale_at_or_after_n_par`
- `test_composed_veto_ignores_parity_before_n_par`
- **FQ-R54 M1, in which each case refuses:**
  - `test_composed_veto_refuses_when_live_fill_count_unreadable`
  - `test_composed_veto_refuses_when_live_fill_count_read_raises`
  - `test_composed_veto_refuses_when_parity_verdict_older_than_stale_parity_h`
  - `test_composed_veto_refuses_on_parity_verdict_wrong_subject`
  - `test_composed_veto_refuses_on_parity_verdict_wrong_family`
  - `test_composed_veto_parity_fail_latches_later_underpowered_never_unrefuses`
  - `test_composed_veto_parity_fail_latches_older_pass_never_unrefuses`
- **Diff-scope guard:** `test_f6_trade_py_changes_only_compose_fq`. It compares an AST hash of every other top-level def in `app/trade.py` against the merge base. The gate also checks `git diff --name-only` ⊆ {`app/trade.py`, the probe module, F6 tests}.

**WP5 note (`:888-898`).**
- WP5 rebases over F6. `entry_veto` stays a separate slot (G23).
- ADD `tests/unit/test_registry_boot.py::test_wp5_preserves_fq_composed_veto_callable_identity`.
- Every F6 test stays byte-unchanged and green at WP5's merge sha.

### §R8-2 F6 retirement (FQ-R17, FQ-R28, FQ-R44, FQ-R53)

- **Owner.** The AUT-5a row owner, which is the coordinator.
- **Retirement needs all of the following:**
  - (a) N consecutive settled days of accepted `live.drawdown` PASS on the sending FQ root, each with `day_status == EVALUATED` and `drawdown_control_active` true (AD3, r7 `:752`);
  - (b) at least `bridge_retirement_min_fills` live fills over those days. Proposed: N = 5 and a minimum of 10 fills, aligned with `DRAWDOWN_INERT_ALERT_MIN_FILLS` (`pins.py:88`). These are design values, not caps;
  - (c) a fresh `live.drawdown` producer verdict;
  - (d) a reviewed commit, made by hand, that deletes `loss_stop_probe.py`, its wiring and its unit and cites the verdict ids. A respawn with the post-respawn checks follows it.
  - (e) **(FQ-R53)** the H1 pre-flight and read-back (§R8-4, "Ops-step acceptance"):
    - the pre-flight prints the resolved probe module path and sha, the unit path, the cited verdict ids and their resolved files, and the intended deletion set;
    - the read-back shows that the respawned node's composed veto no longer contains the loss-stop branch, while the family-halt and parity branches are still present.
- **Nothing auto-retires.**
- **Tests (all ADD):**
  - `tests/unit/test_drawdown_producer.py::test_bridge_retirement_requires_n_consecutive_evaluated_non_inert_pass_days`
  - `::test_bridge_retirement_requires_min_fills`
  - `::test_bridge_retirement_blocked_when_drawdown_producer_stale`
  - `::test_bridge_never_auto_retires` (AST)

### §R8-3 RC-5: every `fq_v1` reference retargeted to `pm_us_crh_fq_v2`

**Naming hazard.** `pm_us_crh_v2` (`pins.py:107`) is a different, retired CRH family. Never shorten the new root to "v2" in code or tests.

**The RC-5 live-orders ruling (FQ-R54 M4).**
- The coordinator authors `RULING_fq_v2_live_orders_<date>` under the operator's standing grant, in which only the two budget caps are operator decisions.
- It cites `RULING_operator_fq_live_real_orders_2026-10-01` as its authority.
- It is filed after the shadow resume-bar PASS and is peer-reviewed as RC-5 requires (`FQ-LOSS-RESPONSE_plan_r3.md:72`).
- It is not escalated to the operator.
- It assigns no value to either cap.

**AUT-5 r7 (19 lines, 25 occurrences).** As in r1, except line 172:

| Line | Disposition |
|---|---|
| 172 | **RETARGET under E-27:** "BOOTSTRAP seeds `pm_us_crh_fq_v2` CHAMPION and `pm_us_crh_fq_v1` RETIRED. v1's standing A1 `policy_halt` produces no registry row and no venue freeze (§R8-4 verify)." |
| 343, 434, 567, 589, 664, 665, 674, 685, 689, 698, 699, 702, 926, 937, 963, 987, 991, 1026 | RETARGET (as r1) |

Retargeted: 19 lines. Kept: 0.

**AUT-7 r5 (28 lines, 38 occurrences).**
- As in r1: 26 lines retargeted and 2 kept. `:10` is historical. `:29` is the ARCH §10 quote, read as historical per E-27 rule 2.
- The value-bound lines are retargeted: sha `9c0b6d6e…` at `:66, :324, :339, :353, :354, :752, :804`, and d0 `2026-10-02` at `:66, :322`.
- The drill child name reads `<champion>_r0001` (E-27 rule 2).

**Checklist scoping, r7 `:1027`.** The `_LIVE_ORDERS_ALLOWLIST` diff must be empty except for the single RC-5 row.
- ADD `test_live_orders_allowlist_diff_is_only_rc5_row`.

### §R8-4 F9: arming v2 by env and manifest ruling (FQ-R35, FQ-R48); the registry seeds it later (E-27)

**Needs:** {F8, shadow resume-bar PASS, F6, RC-5 ruling}. Row 8 and DEP-9 are not Needs.

**Binding sequence (FQ-R48):** F9-A → F9-B (verified) → {P-1, P-2, GAP-16 pins} → bootstrap → P-3. Each widening act is its own reviewed commit (security item 6).

| # | Act | Commit content | Activation |
|---|---|---|---|
| 1 | F9-A, live-orders enablement | The v2 manifest `live_orders_ruling` = the RC-5 ruling, plus one `_LIVE_ORDERS_ALLOWLIST` triple. These are the two inseparable halves of G4 | No send yet |
| 2 | F9-B, env arm | The env and unit sources switch the sending family (`BREEZY_SENDING_FAMILY_ID`, `runtime/settings.py:106`) from `pm_us_crh_fq_v1` to `pm_us_crh_fq_v2` (the v2 shadow run of F8 is a separate, non-sending composition), as v1 was armed on 10-01. Afterwards no env source names v1. **SCOPE (re-pin)** in this commit: `tests/unit/test_trade_supervisor_phase1_unit.py:37` `_EXPECTED_SENDING_FAMILY_ID` becomes `"pm_us_crh_fq_v2"`, and its assertions stay byte-unchanged | Node respawn plus the FQ-R22 checks. Supervisor restart in [01:00Z, 16:40Z) if the env lives in the symlinked unit. **"Verified"** means the read-back below is recorded before row 3 starts |
| 3a | P-1, pins before the first bootstrap (after F9-B and F3) | `BOOTSTRAP_SEED` per E-27. `BOOTSTRAPPED_ROOT_MANIFEST_SHA256` rows for v2 (the post-F9-A sha), v1 (the post-F3 sha), v4, cont and `pm_us_crh_v2`. **The mandatory fixture migration (FQ-R49)**, below | Inert until bootstrap |
| 3b | P-2 | The `_LINEAGE_POLICY_ALLOWLIST` row: `fq_v1` replaced by `pm_us_crh_fq_v2` (still one row) | Registry |
| 3c | GAP-16 pins | The `DEFAULT_RESTRICTIVE_CLASS` entry (E-27). It lands in the {P-1, P-2, GAP-16} stage, in the P-1 commit or a separate commit within that stage, never before F9-B and never after the bootstrap | Inert until bootstrap |
| 4 | Bootstrap | The row-7 genesis transaction from the P-1 seed. Stage S activates here | Registry |
| 5 | P-3 | Policy revision: `lineage_roots=["pm_us_crh_fq_v2"]`, the E-25 lineage keys and a `detector_map` parity row. `root_admit_enabled` stays false | Registry |
| — | (none) | `ROOT_ADMIT_ENABLED_CEILING` stays `False` (`pins.py:22`). Stage flags follow AUT-5 r7 WP9/WP10 unchanged. L2 stays gated by DEP-9 | — |

**Row-7 sequencing (FQ-R48).**
- Row-7 WP1–WP9 may merge now, because they are inert while the source is unset. WP5 still waits for F6 (E-28).
- Only WP10 (stage S, L1, L2) waits behind F8, F6, the resume bar and RC-5, and therefore behind F9-B and the bootstrap.
- **Record this delay in `docs/core/PROGRESS.md`** at the row-7 entry, in the same session that the r3 plan is accepted.

**L1 counting (FQ-R48; security M3).**
- An L1 session counts only if both of these hold:
  - its start is after the recorded F9-B read-back;
  - at session start, the registry's resolved family equals the env sender (`BREEZY_SENDING_FAMILY_ID`).
- On a mismatch the session is not counted and a CRITICAL is raised.
- ADD `tests/unit/test_autonomy_stage_policy.py::test_l1_session_counts_only_when_registry_resolved_family_equals_env_sender`
- ADD `::test_l1_sessions_before_f9b_never_count`
- Both tests are owned by WP10, which emits `registry_resolved` (not yet in `src/`).

**P-1 fixture migration (FQ-R49; mandatory, in the P-1 commit, SCOPE only).**
- **Verify-first (blocking).**
  - List every validate-path test that bootstraps `pm_us_crh_fq_v1` as CHAMPION. The architect counts 55 occurrences in 16 files. Re-count at the P-1 base and record the list.
  - Record `pytest --collect-only -q` node ids for those files, before the change.
  - Confirm that `deploy/families/pm_us_crh_fq_v2.json` exists at the post-F9-A sha.
  - Check whether `World`'s byte-replacement child derivation (`test_registry_replay.py:121-124`, which replaces the id and d0) applies to the v2 bytes. If v2's d0 or id shape breaks it, STOP for a ruling. Never loosen the replacement.
- **Change.**
  - The fixtures are migrated to a v2 root, which is option (a). The seed family, `INCUMBENT` (`test_registry_fold.py:57`) and every fixture constant become `pm_us_crh_fq_v2`.
  - Following FQ-R45's decoupling, `World.ROOT_SOURCE` becomes `tests/fixtures/registry_world/pm_us_crh_fq_v2.json`, a byte-exact copy of the post-F9-A deploy v2 file. It is copied into the temp repo as `deploy/families/pm_us_crh_fq_v2.json`.
  - The v1 fixture and its drift guard from CONFLICT-13 stay. v1 is now a RETIRED seed in the world.
- **What a change may touch.**
  - It changes fixtures and identifiers only, never the asserted relation.
  - An assertion that names `pm_us_crh_fq_v1` as a literal is rewritten to the fixture constant. The reviewer checks hunk by hunk that only identifiers change. **STOP (FQ-R56):** any hunk that changes anything other than an identifier, for example a refusal row index, a fold count or a tally, stops the commit for a ruling. Prefer fixtures that do not bootstrap v1 at all (`ii.bootstrap` only checks membership in the seed set, `validate_ii.py:196`), so no index shifts.
- **Guards.**
  - ADD `test_registry_world_v2_fixture_equals_deploy_v2`. It pins the fixture sha256 as a literal and compares the parsed fields to the deploy file.
  - The `--collect-only` node-id list after the change equals the list before it. No test is renamed, removed or skipped.

**v1's halt (FQ-R34 as amended by FQ-R46).**
- It is not cleared on the F9 path.
- It is cleared only under W15 (ARCH `:720-723`; U2 at `:479`), with the audited `breezy-clear-family-halt` (`src/breezy/strategy/current_rung_hold/clear_family_halt_cli.py:77`, prog `:88`), and only after:
  - **the fold shows v1 RETIRED and no family of v1's lineage is in any other state** (E-27 rule 4a);
  - no env source names v1;
  - the H1 pre-flight and read-back below.
- It is required only before any future polymarket_us ROOT_ADMIT.
- Verify-first (read-only): list every uncleared non-`fee_schedule_drift` `policy_halt` on polymarket_us.

**Verify: the RETIRED seed against the mirrored halt (FQ-R35).**
- No allowed pair leaves RETIRED, other than same-state HWM_RESET (`transitions.py:67-94`). HALT and DEMOTE start only from CHAMPION (`:83-84`). A TERMINAL class does not set the venue integrity freeze (`fold.py:441-444`).
- The halt mirror's owner (AUT-5a) must show that a `policy_halt:*` record on a family that folds RETIRED writes **no** row, raises no `engine_inconsistency`, and does not freeze the venue.
- ADD `test_policy_halt_mirror_on_seeded_retired_family_writes_no_row_and_no_freeze`.

**FQ-R45 readers after F3 (verify-first, carried into P-1's base).**
- Run every direct reader of `deploy/families/pm_us_crh_fq_v1.json` and record green:
  - `test_autonomy_pins.py:365`
  - `test_family_halt_cli_fq.py:155`
  - `test_nbp_shadow_parity_live.py:776`
  - `test_fq_s8_registration_artefacts.py:37`
  - `test_forecast_quantile_ladder_manifest_and_markers.py:23`
  - `test_ct08_supervisor_contract_surface.py:388`
  - `test_operator_caps_through_the_live_composition.py:338`
  - `test_trade_supervisor_phase1_unit.py:85`
  - the production readers `scripts/analysis/nbp_shadow_parity.py:115` and `scripts/analysis/family_tally_v2.py:1537`
- **Added in r3:** `tests/unit/test_persistence_exit_gate.py:51`. That test lists and parses every committed manifest (`:55-64`), and FQ-R45 omitted it.
- **Note for F8.** `test_persistence_exit_gate.py` cross-checks that every manifest under `deploy/families/` is enumerated. F8's new v2 manifest therefore needs exactly one added row, as a SCOPE widening by one, in F8's commit.

**Ops-step acceptance (FQ-R53, security H1).** The text below is the security reviewer's acceptance text as recorded in FQ-R53. It applies to every one of: F9-A, F9-B, P-1 with bootstrap, the W15 clear, the F7a activation (§R12-1) and the F6 retirement (§R8-2).

> "Before activation: run the CLI or step with `--dry-run` from a non-repo cwd, using absolute manifest and state paths. It must print the resolved manifest path and sha, the family id, and the intended write, and it must exit non-zero on any unresolved input. After activation: read back the effect (halt latch state, `family_halt_state` boot line, registry fold row, env source list) and record its output. A step that exits 0 without that evidence is not done. `a8a66f41` (cwd-independent manifest resolution) must be merged before any of these steps run." (security reviewer, round 2, verbatim)

- **Precondition, checked in every pre-flight:** `git merge-base --is-ancestor a8a66f41 HEAD` exits 0. If it does not, the step does not run.
- **Pre-flight form.** A read-only `set -euo pipefail` invocation, run from a cwd outside every worktree, using absolute interpreter and repo paths. Its output is stored in the step's ops record.
- **Read-back for each step:**

  | Step | Read-back |
  |---|---|
  | F9-A | The resolved manifest sha and `live_orders_ruling`, read through the production live-orders gate |
  | F9-B | The respawned node's sending family from its log file, and the permit line |
  | P-1 / bootstrap | The fold seed states and the five manifest shas |
  | W15 clear | The halt record cleared, plus its audit record |
  | F7a activation | As in §R12-1 |
  | F6 retirement | As in §R8-2(e) |

- **Tests (all ADD; SCOPE where marked).**
  - `test_v2_never_in_registry_before_f9a_commit`
  - `test_bootstrap_seed_champion_has_live_orders_triple`
  - `test_autonomy_pins.py` seed and manifest-sha pins (SCOPE: re-pin; E-27)
  - `test_no_env_source_names_v1_after_f9b`
  - `test_l1_session_counts_only_when_registry_resolved_family_equals_env_sender`, `test_l1_sessions_before_f9b_never_count`
  - `test_registry_world_v2_fixture_equals_deploy_v2`
  - `test_mint_in_all_retired_lineage_refused`, `test_mint_after_lineage_fully_retired_earlier_in_same_batch_refused`, `test_mint_allowed_when_root_retired_but_lineage_has_live_family` (E-27, FQ-R56)
  - r1's `test_root_admit_v2_requires_parity_detector_mapped` and `test_root_admit_v2_cites_fee_pass` stay **dropped**. They were r1 ADDs, never merged, and ROOT_ADMIT is not on the path.

### §R8-5 Parity continuation gate (FQ-R29, FQ-R35, FQ-R47)

- **Producer:** AUT-4 r12 §R12-5.
- **Before bootstrap:** the F6 composed veto refuses, and the refusal latches, in these cases:
  - an accepted FAIL;
  - a verdict that is missing, older than `STALE_PARITY_H`, or of the wrong subject or family, once v2 live fills ≥ n_par;
  - a fill count that is unreadable or raising.
- **After bootstrap:** the AUT-5a engine accepts a FAIL as **DEMOTE only** (`test_demotion_never_requires_policy_and_is_immediate`). The class comes from the P-3 `detector_map`, or before P-3 from `pins.DEFAULT_RESTRICTIVE_CLASS`.
- **RESUME after a parity DEMOTE** needs the cause verdict to PASS again. It cannot, because the look is single and final. So v2 stays HALTED until build-side recovery. This is fail-closed, and is stated as such.
- **Test (ADD):** `tests/unit/test_autonomy_engine.py::test_parity_fail_demotes_never_halts_or_widens`.

### §R8-6 F12: enabling PROMOTE (FQ-R21, FQ-R28, FQ-R38)

- **Ownership.**
  - WP1b (ARCH-0 seamA r5 `:909-917`) owns `transitions._ADMISSION_IMPLEMENTED` (`transitions.py:166-168`, which ships empty).
  - The L2 flag stays WP9's.
- **What F12 is.** F12 is the policy revision `promote_enabled=true` and its tests.
- **F12 is GATED on all of:**
  - GAP-13: an F5 ruling for a forward-only shadow source for non-champions (**OPEN**, §R8-8);
  - WP1b's PROMOTE admission;
  - the DEP-9 ledger being empty.
- **Filing condition.**
  - `fixed_n` lineages meet r7's eta bound.
  - `e_process` lineages meet `eta_ns ≤ window_end`, `nomination_feasible` (including E-25 rule 6b), and eta ≤ KILL − `forward_window_days`.
- **WP3 changes.**
  - `test_promote_disabled_when_n_min_exceeds_window_cap` (r7 `:869`): SCOPE to `fixed_n`.
  - ADD `test_promote_disabled_when_e_process_nomination_infeasible`.

### §R8-7 Policy-block changes (WP3)

- **The per-lineage `lineages.<root>` object holds:** `test_kind`, `alpha_schedule`, `gamma_norm_T`, `n_e_power`, `take_rate_lower`, `uptime_floor`, `earliest_look_n`, `m_cap`, `x_max`, `max_infeasible_nominations`, `bridge_retirement_consecutive_days`, `bridge_retirement_min_fills`.
- `alpha_spending` (`:599`) is superseded.
- `test_policy_block_exact_set_keys` and `test_policy_block_not_looser_than_code_ceilings` are SCOPE, widened by exactly these keys. `max_infeasible_nominations` is checked against the new pins ceiling.
- ADD `test_policy_loader_refuses_fq_lineage_fixed_n`.
- ADD `test_policy_m_cap_and_x_max_equal_f5_design_json`.
- Drawdown H0 is re-run on v2's lineage under the weekly AB3 re-run.

### §R8-8 CONFLICT, GAP and DEPENDENCY register

| # | Item | Status |
|---|---|---|
| 1 | CONFLICT-1: C4 FWER, fixed-n | RESOLVED by E-25 |
| 2 | CONFLICT-2: §4.2 against `variant_spec` | RESOLVED-by-ruling FQ-R40 (E-26 rules 5–6) |
| 3 | CONFLICT-3: U2 standing halt blocks ROOT_ADMIT | RESOLVED-by-ruling FQ-R34, with the precondition amended by FQ-R46 (E-27 rule 4a). Moot for F9 |
| 4 | CONFLICT-4: ROOT_ADMIT ceiling | RESOLVED, moot by FQ-R35. The ceiling stays `False` |
| 5 | CONFLICT-5: stage S/L1 loop | RESOLVED-by-ruling FQ-R35 and FQ-R48. Stage S follows F9-B and the bootstrap. L1 counts only sessions after F9-B with registry and env agreeing on the sender |
| 6 | CONFLICT-6: §5.1 `app/trade.py` ownership | RESOLVED-by-ruling FQ-R36 and FQ-R50 (E-28) |
| 7 | CONFLICT-7: frozen ARCH names `fq_v1` as drill root | **RESOLVED-by-ruling FQ-R52** (E-27 rule 2: readings, `<champion>_r0001`, historical lines) |
| 8 | DEDUP-1, LAYER-1, DEDUP-2 | RESOLVED-by-ruling FQ-R41 |
| 9 | DEP-9: owner-placeholder ledger | RESOLVED-by-ruling FQ-R35. It gates L2 only; the test is unweakened |
| 10 | OPEN-1: `fs_replay` backtest FS | RESOLVED-by-ruling FQ-R37 (E-25 rule 8) |
| 11 | CONFLICT-11: E-24 introduction order | RESOLVED (F9-A precedes P-1) |
| 12 | GAP-12: root-copy write | RESOLVED (dropped) by FQ-R35 |
| 13 | GAP-13: CHALLENGER accrues no shadow n | Structure RESOLVED-by-ruling FQ-R38 (F12 GATED; E-25 rule 6b). **The F5 ruling itself is OPEN** |
| 14 | CONFLICT-13: F3 terminal day against child fixtures | **RESOLVED-by-ruling FQ-R45**, option (d), with a sha-literal guard. F3 is being rebuilt with (d) now |
| 15 | CONFLICT-14: a RETIRED seed is not `terminal_frozen` | **RESOLVED-by-ruling FQ-R46.** The r2 freeze rule is rejected; the precondition is rewritten and a MINT-under-RETIRED-root validate rule is added (E-27 rule 4) |
| 16 | GAP-16: parity detector absent from the no-policy fallback | **RESOLVED-by-ruling FQ-R47** (pins entry in E-27 consumption, at or before P-1) |
| 17 | DEP-17: bootstrap ordering | **RESOLVED-by-ruling FQ-R48** (F9-A → F9-B → {P-1, P-2, GAP-16} → bootstrap → P-3) |
| 18 | FQ-R39 and FQ-R55 statistics | Structure RESOLVED in E-25 and §R12-5. **The numeric values are OPEN in F5** |
| 19 | P-1 test impact (architect HIGH) | **RESOLVED-by-ruling FQ-R49** (mandatory v2 fixture migration in P-1, SCOPE only) |
| 20 | Security H1, M1, M2, M3, M4 | **RESOLVED-by-ruling FQ-R53, FQ-R54, FQ-R48** |

**What is still OPEN, and why.** Nothing else is open.

- **F5 numeric values.** These are:
  - `m_cap` (provisional 2, final ∈ {2, 3});
  - `X_max`, λ_max, μ_max, γ or T, δ_h;
  - `n_e_power` (joint), `take_rate_lower`, `uptime_floor`, `earliest_look_n`;
  - n_par, δ_par, α_par, the parity bootstrap seed and replicate count;
  - `STALE_PARITY_H`;
  - the restated power record;
  - the t_par-against-KILL determination.
  - **Why open:** they are outputs of F5's pre-registered MC and design JSON, which come after F1 by construction. F1 fixes their structure, and F7b and F6 cannot merge until the design JSON pins them.
- **GAP-13 F5 ruling** (forward-only shadow source for non-champions).
  - **Why open:** it is an F5 deliverable. Until it exists, every non-champion `e_process` nomination is infeasible (E-25 rule 6b) and F12 stays GATED. That is fail-closed.

#### CONFLICT-13: F3's `terminal_climate_day` against the registry child fixtures (RESOLVED, FQ-R45, option (d))

**Evidence (unchanged from r2, in brief).**
- `World` reads the committed v1 manifest (`test_registry_replay.py:68`, `:115-116`) and derives a child with d0 2026-10-20 (`:121-124`).
- After F3, the inherited `terminal_climate_day` "2026-10-05" < d0 is refused at parse time (`family_manifest.py:406-411` → MANIFEST_INVALID, `byte_binding.py:217-218`). This happens before `manifest_equal_modulo_allowlist` (`byte_binding.py:124-144`).
- That refusal is correct production behaviour. Options (a) as F3's fix, (b) and (c) are rejected for the reasons in r2. (a) returns as the mandatory P-1 migration (FQ-R49).

**The accepted change (option (d); SCOPE, no test weakened).**
1. ADD `tests/fixtures/registry_world/pm_us_crh_fq_v1.json`: the byte-exact pre-F3 manifest from `git show <F3 merge-base>:deploy/families/pm_us_crh_fq_v1.json`.
2. SCOPE: `World.ROOT_SOURCE` (`test_registry_replay.py:68`) points at that fixture. It is still copied into the temp repo as `deploy/families/pm_us_crh_fq_v1.json`. Every test name, assertion and `root_file` path is unchanged.
3. ADD `test_registry_world_root_fixture_equals_deploy_v1_modulo_terminal_day`.
   - It pins the fixture's **sha256 as a literal** (FQ-R45).
   - It also parses both files and compares every `dataclasses.fields(FamilyManifest)` except `terminal_climate_day` and `manifest_sha256`.
   - It asserts that the fixture's terminal is `None` and the deploy file's is `"2026-10-05"`.
4. ADD `test_child_inheriting_root_terminal_before_its_d0_is_refused`. It uses the live post-F3 root bytes and the `replay_stubbed` resolve (`registry_resolver_world.py:157-175`), and expects MANIFEST_INVALID.

**Verify-firsts.**
- The 73 failures are exactly the `World` consumers.
- `test_autonomy_owner_placeholders.py` fails only transitively (`run_node_ids`, `:735`). Never edit the ledger to drop rows.
- No test pins the live v1 manifest sha. If one does, widen it by one reviewed row.
- `BOOTSTRAPPED_ROOT_MANIFEST_SHA256` is still empty (`pins.py:100`; `test_autonomy_pins.py:104`).
- **After F3, run every direct reader** listed in §R8-4 ("FQ-R45 readers"), including `test_persistence_exit_gate.py`.

---

## Changes from r2

| Ruling or item | Sections changed | Test changes |
|---|---|---|
| FQ-R45 (CONFLICT-13 (d)) | §R8-8 #14 RESOLVED; (d) guard pins the fixture sha literal; reader verify-first in §R8-4, with `test_persistence_exit_gate.py:51` added and an F8 note | guard strengthened (ADD sha literal) |
| FQ-R46 (CONFLICT-14) | E-27 rule 4 deleted and replaced (4a precondition, 4b MINT validate rule at `validate.py:526`); §R8-4 W15 precondition; §R8-8 #3, #15 | ADD `test_mint_under_retired_root_refused`, ADD batch variant; r2's `test_seeded_retired_lineage_is_terminal_frozen` dropped (never merged); fold tests untouched |
| FQ-R47 (GAP-16) | E-27 consumption (pins entry at `pins.py:148-164`; ARCH `:372`); §R12-2 §3.10; §R12-5 actuation; §R8-5; §R8-8 #16 | ADD exact-value assertion in `test_default_restrictive_class_is_demote_or_halt_with_known_classes`; ADD fallback engine test |
| FQ-R48 (sequence, DEP-17) | Summary; E-27 rule 3; §R8-4 sequence table, row-7 sequencing, PROGRESS note, L1 counting; E-28; §R8-8 #5, #17 | ADD sender-agreement and pre-F9-B L1 tests |
| FQ-R49 (P-1 impact) | §R8-4 mandatory fixture migration with verify-first; v2 world fixture | SCOPE (fixtures and identifiers); ADD `test_registry_world_v2_fixture_equals_deploy_v2`; collect-only parity |
| FQ-R50 (E-28 wording) | E-28; §R8-1 | none |
| FQ-R51 (activation proof) | §R12-1 rewritten (frozen snapshot, determinism verify-first, capped hand runs before and after, byte-compare, next firing) | none |
| FQ-R52 (E-27 text) | E-27 RC-5 amendment line; rule 2 (historical `:35`, `:68-69`; `<champion>_r0001` for `:1256`); §R8-3; §R8-8 #7 | none |
| FQ-R53 (H1) | §R8-4 "Ops-step acceptance" applied to six steps; §R12-1 and §R8-2(e) | none (ops) |
| FQ-R54 M1 | §R8-1 `STALE_PARITY_H` and seven veto tests; §R8-5 | ADD 7 + ADD `test_stale_parity_h_equals_design_json` |
| FQ-R54 M2 | §R12-3 honesty statement; final class; exact-type checks; `LoadedEvidence`; pickle and `__setstate__` AST ban; `object.__new__` test | ADD 5 |
| FQ-R54 M4 | §R8-3 RC-5 ruling authored by the coordinator, citing `RULING_operator_fq_live_real_orders_2026-10-01` | none |
| FQ-R55.1 (m_d) | E-25 rule 3: m_d = `m_cap` (provisional 2, F5 ∈ {2, 3}), L_d removed | ADD `test_eprocess_m_d_is_pinned_m_cap_independent_of_listing_count` |
| FQ-R55.2 (clip) | E-25 rule 3: X_max upside clip in e_a and KILL CS, downside unclipped, ask floor kept; §R8-7 `x_max` | ADD 2 + ADD policy pin test |
| FQ-R55.3 (joint power) | E-25 rule 6a; §R12-2 §8 power record marked PROVISIONAL AND OPTIMISTIC | ADD `test_n_e_power_is_joint_power_of_min_ea_eb` |
| FQ-R55.4 (ties, voids) | E-25 rule 3 | ADD 2 |
| FQ-R55 statements | H0_b ≠ H0_a (PASS asserts both); KILL null and compounding ≤ 0.20; parity day-clustered bootstrap, pinned seed, qty-weighted (§R12-5) | ADD 2 parity tests |
| New in r3 (found during citation check) | P-1 re-pin of `test_empty_pins_at_arch0` (`test_autonomy_pins.py:104`); F9-B re-pin of `test_trade_supervisor_phase1_unit.py:37`; `test_persistence_exit_gate.py` reader and F8 widening note | SCOPE (exact re-pins, exact equality kept) |

**No test is weakened.** Every change above is ADD, or SCOPE that keeps exact-equality assertions and re-pins or widens them by exactly the named items.

**Source documents:**
- r2 and its round-2 rulings: `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F1-errata-and-deltas_r2.md`
- r1 draft and FQ-R34..R44: `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F1-errata-and-deltas_draft.md`
- FQ plan r3 and RC-5 (`:71-75`): `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/FQ-LOSS-RESPONSE_plan_r3.md`
- Frozen ARCH: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/snapshots/ARCH_rev9_2.md` and `reviews/ARCH-ERRATA-rev9_2.md`
- WP1b ownership: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamA_plan_r5.md`
- Code anchors: `/home/jon/breezy/src/breezy/persistence/autonomy/validate.py`, `/home/jon/breezy/src/breezy/persistence/autonomy/validate_ii.py`, `/home/jon/breezy/src/breezy/persistence/autonomy/pins.py`, `/home/jon/breezy/tests/unit/test_autonomy_pins.py`, `/home/jon/breezy/tests/unit/test_registry_replay.py`, `/home/jon/breezy/tests/unit/test_persistence_exit_gate.py`, `/home/jon/breezy/tests/unit/test_trade_supervisor_phase1_unit.py`

---

**Coordinator notes (outside the paste-ready body):**
- **Pre-filing check.** I could not check `a8a66f41` from this read-only, no-shell session. Its ancestor check is built into every pre-flight, but confirm it once before filing.
- **H1 acceptance text.** I took it from FQ-R53 as written. If the security reviewer's original wording differs, substitute it word for word.
- **Two re-pins not named in the rulings.** Found in the citation check:
  - `test_empty_pins_at_arch0` at `test_autonomy_pins.py:104` belongs to P-1;
  - `test_trade_supervisor_phase1_unit.py:37` belongs to F9-B.
  - Without them, P-1 and F9-B would go red.
- **A reader FQ-R45 missed.** `test_persistence_exit_gate.py` reads every committed manifest, and FQ-R45's list omitted it.

---

## Convergence check (architect, 2026-10-06) and coordinator ruling FQ-R56

- **Verdict:** NOT-READY on four items, all fixed in place above.
  - **(a) HIGH.** Rule 4(b) is narrowed to "every family of the lineage is RETIRED". The ARCH `:489` superseded-root case is now allowed, with a new test.
  - **(b)** `RULE_II_NAMES` is widened by exactly one name.
  - **(c)** The P-1 migration has a STOP on any hunk that changes more than identifiers.
  - **(d)** F9-B's starting value is corrected to `pm_us_crh_fq_v1`.
  - **(e)** The GAP-16 pin's stage wording is aligned with E-27 rule 3.
- **Ruled genuine SCOPE:** the two re-pins r3 added (`test_autonomy_pins.py:104`, `test_trade_supervisor_phase1_unit.py:37`).
- **H1 text:** the security reviewer's round-2 text is substituted verbatim (§R8-4).
- **Status: READY TO FILE.** E-25..E-28 are appended to `ARCH-ERRATA-rev9_2.md`. They are consumed by their owning WPs, per each erratum's Consumption list.
