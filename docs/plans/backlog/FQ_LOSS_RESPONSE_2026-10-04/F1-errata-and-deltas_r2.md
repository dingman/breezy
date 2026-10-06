# F1 FQ-PLAN r2: errata E-25..E-28 and the AUT-4 r12 and AUT-5 r8 deltas

<!-- F1 FQ-PLAN r2 (planner, 2026-10-06). DRAFT: not filed. It folds in the binding round-1 rulings FQ-R34..R44 and the new CONFLICT-13. It needs round-2 review (architect, security, stats) before E-25..E-28 are appended to ARCH-ERRATA-rev9_2.md. -->

## Summary

- **Erratum numbers.** E-1..E-24 are filed. This revision uses E-25 (RC-1, e-process and e-LOND), E-26 (RC-6, two model classes), **E-27** (BOOTSTRAP_SEED, from FQ-R35) and **E-28** (RC-7 carve-out, from FQ-R36). Read FQ-plan "E-15" as E-25 and "E-16" as E-26, including the queue tokens of F7b, F11 and F13.
- **How v2 is armed (FQ-R35).** v2 is armed the way v1 was armed on 10-01: through the env and a manifest ruling. ROOT_ADMIT is no longer on the F9 path.
  - The first bootstrap seeds `pm_us_crh_fq_v2` as CHAMPION and `pm_us_crh_fq_v1` as RETIRED.
  - As a result, CONFLICT-3, CONFLICT-4, CONFLICT-5, GAP-12 and DEP-9 no longer block F9.
- **F9 Needs** are now {F8, shadow resume-bar PASS, F6, RC-5 ruling}.
- **New items for round 2:**
  - **CONFLICT-13** (F3's terminal day against the child fixtures). Recommendation: option (d), with evidence in §R8-8.
  - **CONFLICT-14.** A RETIRED seed does not set `terminal_frozen`, so FQ-R34's clear precondition can never be met.
  - **DEP-17.** The bootstrap must come after F9-A.
  - **GAP-16.** The parity detector is absent from the no-policy fallback map.
- **Citation check.** Every `src/`, `tests/`, `deploy/` and `scripts/` citation was checked on disk at `4ba7f10c`. So were the ARCH lines quoted in the errata (`:472`, `:476-480`, `:699-706`, `:720-723`, `:737-738`, `:803-808`, `:1049-1051`) and ARCH-0 seamA r5 `:909-917`. Line citations into AUT-4 r11, AUT-5 r7 and AUT-7 r5 are carried from r1 unchanged and were not re-verified, because codegraph indexes code only.

---

## Section 1: Erratum A (paste-ready)

## E-25 (coordinator, 2026-10-04; FQ r3 RC-1 as amended by FQ-R15, FQ-R20, FQ-R26, FQ-R37, FQ-R38, FQ-R39; filed by F1 only, FQ-R19): e-process verdicts and the per-lineage e-LOND α schedule

**Numbering.** The FQ plan's "E-15" is taken by the network-namespace erratum, so this is E-25. Every FQ-plan reference to E-15, including F7b's Needs token, reads E-25.

**Finding.**
- ARCH C4 (`:288-301`, `:323-346`) and AUT-4 r11 (§3.1 `:469-472`, §3.5 `:560-572`) allow only a fixed-n, single-look FORWARD_SHADOW under a geometric FWER schedule.
- PREREG v2 confirms on an anytime-valid, calendar-day e-process and controls FDR with per-lineage e-LOND.
- Neither the `verdict/v1` key set (`src/breezy/persistence/autonomy/verdict.py:178-184`) nor the window-cap rule (ARCH `:340-346`) can express that.

**Rule.**

1. **New verdict fields.** These are three nullable additions to `verdict/v1` `_KEYS`, and all three are in the identity body.
   - **`test_kind`** ∈ {`fixed_n`, `e_process`}.
     - Never null on FORWARD_SHADOW.
     - On LIVE_SEQUENTIAL it is `e_process` only when the family PREREG registers an e-process. LD-OBF families keep it null, governed by `family_prereg_sha256`.
     - Null on every other kind.
   - **`eta_ns`** (int, `e_process` only). The projected UTC ns at which n reaches `n_e_power[k]`, at `take_rate_lower`. Null when the nomination is infeasible or the test is `fixed_n`.
   - **`window_end`** (ISO date, FORWARD_SHADOW only, either test kind). The last forward climate day, inclusive, by AUT-4 `windows.py` arithmetic.

2. **`n_min_eff` is not redefined.**
   - It is null on every `e_process` verdict.
   - For `e_process`, `n_min` is F5's pre-registered earliest-look n. No PASS or FAIL is written below it.

3. **The e-process (FORWARD_SHADOW and LIVE_SEQUENTIAL `e_process`).** The unit is the settled calendar day d.
   - **Null H0_a (per take).** E[h_i | G_τi] ≤ BE_i, where:
     - h_i ∈ {0, 1} is the qty-1 payout;
     - BE_i = haircut `ask_exec` + fee;
     - G_τi is the information at the decision instant.
   - **The daily statistic uses a denominator pinned before the day (FQ-R39).**
     - Y_d = (1/m_d) · Σ_{i ≤ m_d} (h_i/BE_i − 1).
     - m_d ≥ 1 is the number of counted take slots for day d. It is fixed before the day's first decision from pre-day facts only: m_d = min(`m_cap`, L_d), where L_d is the root's listed station-days at the pre-open snapshot and `m_cap` is pinned in the F5 design JSON.
     - Takes are counted in decision order. Takes past m_d are excluded from Y_d and disclosed in the metric `eprocess_uncounted_takes`.
     - Y_d ≥ −1.
   - **e_a.** e_a,t = Π_{d ≤ t} (1 + λ_d·Y_d).
     - λ_d is fixed at the start of day d from settled days only (the betting rule is pinned).
     - λ_d ∈ [0, λ_max], with λ_max ≤ 0.5 (FQ-R15), so every factor is ≥ 0.5.
   - **e_b, a betting e-process built directly, not derived from a CS (FQ-R39).**
     - S_i = (a_i − y_i)² − (p_i − y_i)², where a_i is the ask-implied probability of the side bought, p_i is the model's probability of that side, and y_i is the outcome.
     - The null is H0_b: E[S_i | G_τi] ≤ 0.
     - Z_d = (1/m_d)·Σ_{i ≤ m_d} S_i ∈ [−1, 1], using the same m_d.
     - e_b,t = Π (1 + μ_d·Z_d), with μ_d predictable and in [0, μ_max ≤ 0.5].
     - The BSS-on-takes CS is still reported, as a diagnostic only.
   - **Outcomes.**
     - **PASS:** min(e_a, e_b) ≥ 1/α_k on some settled day with n ≥ `earliest_look_n`, **and** the calibration guard is sufficient and not failing. Ville's inequality bounds P_H0a(sup e_a ≥ 1/α_k) ≤ α_k. Because PASS needs both, it is an intersection–union test of H0_a ∪ H0_b at α_k.
     - **FAIL (KILL):** the hedged CS on Y_d, at level 1 − **α_kill**, has UB < 0. Its estimand is the running mean of E[Y_d | F_{d−}].
     - **α_kill = 0.05**, pinned in the F5 design JSON. It is separate from α_k, is never charged to `alpha_spent`, and is not part of e-LOND. Rationale: KILL is a capital-protection decision, not a discovery claim. A 5% chance of killing a true-edge model is accepted.
     - **UNDERPOWERED:** otherwise.
     - **`INCONCLUSIVE(window_end_no_crossing)`:** the window ended with no crossing.
     - PASS, FAIL and INCONCLUSIVE are final and never reopened.
     - On LIVE_SEQUENTIAL `e_process`, WIN is PASS and KILL is FAIL. The detector map is unchanged.
   - **Why a pinned denominator and not per-take factors (FQ-R39 choice).**
     - The per-take product Π(1 + λ(h_i/BE_i − 1)) with a start-of-day λ is a test supermartingale only if each factor has conditional mean ≤ 1 given the realised earlier factors.
     - Takes on the same station-day settle together and are dependent. Mixed-side takes on one station-day (a YES on rung A and a NO on rung B; L-40 i, NO-side hunting) are positively correlated. So E[Π] picks up a λ²·Cov term that can exceed 1 under H0.
     - The linear daily form above is valid under any within-day dependence, and with a take count that depends on intraday information. Each term has conditional mean ≤ 0 at its own decision instant, the tower property applies, and slot weights 1/m_d are fixed before the day.
     - The cost is dilution: N_d/m_d < 1 on light days. F5's MC sets `m_cap` to trade that dilution against P(N_d > m_d).
   - **Mandatory MC cases (F5, L-40 and L-41).** Two exact-null cases are added. Type-I error of PASS ≤ α_k is required in both.
     - (i) **Intraday-informed take count.** Takes fire when an intraday observation signal crosses a threshold, outcomes are correlated with that signal, and the true conditional edge is exactly 0.
     - (ii) **Mixed-side same-station-day takes** with positive covariance.

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
   - **The null.** A false discovery is a PASS when H0_k holds, where H0_k = H0_a ∪ H0_b for nominee k: no net edge against the **haircut ask**, or no Brier improvement against the **ask**.
   - **What PASS does not test.** PASS does **not** test superiority over the incumbent champion. That comparison is the non-confirmatory OFFLINE_CHALLENGER / NOT_DISTINCT screen.
   - **Across lineages, nothing is controlled.** With L lineages, the programme-wide false-discovery proportion is unbounded by this erratum.
   - **The FWER bound.** At R = 0, Σ_k α_k ≤ α_total. ARCH's "Σα ≤ α_total per lineage" (`:334`) holds for `halving_v1` lineages only. That is the FWER-to-FDR substitution this programme adopts.

6. **`nomination_feasible`.**
   - **`fixed_n`:** unchanged (`n_min_eff ≤ n_cap`).
   - **`e_process`:** true iff **both** of these hold:
     - (a) ⌊`take_rate_lower` · forward days to `window_end` · `uptime_floor`⌋ ≥ `n_e_power[k]`. `n_e_power` is a pinned policy-block table of the smallest n with MC power ≥ 0.8 at α_k, computed at R = 0. This is arithmetic on named block keys only (AUT-4 r11 K1);
     - (b) **(FQ-R38, GAP-13)** a forward-only shadow evidence source is registered for the nominee by an F5 ruling. While none exists, every `e_process` nomination of a non-champion is infeasible.
   - **An infeasible nomination burns no K slot:** `alpha_k = 0`, `k_life` unchanged, `infeasible_nominations` +1, and the window slot is used. ARCH `:343-344` is unchanged.
   - **Cap (FQ-R39).**
     - A nomination is refused, and no row is written, when the lineage's `infeasible_nominations` (`fold_tallies.py:59`, `:83`) is ≥ the policy key `max_infeasible_nominations`.
     - That key is bounded by a new code ceiling, `pins.MAX_INFEASIBLE_NOMINATIONS_PER_LINEAGE_LIFETIME = 4`, owned by ARCH-0.
     - Rationale: infeasible nominations spend no α. Without a cap, a lineage can consume forward windows indefinitely, and can shop for a feasible window as `window_end` and the table index move. The cap is restrictive only.

7. **C5 row shape is unchanged.** All five `NOMINATION_FIELDS` stay required on a nomination (`registry_shape.py:41`, `:73-75`).
   - On an `e_process` row, `n_min_eff` holds the `fixed_n` value computed from the same block. It is disclosure only and never a gate.

8. **Evidence provenance (FQ-R37).**
   - No verdict PASS may rest on `source=backtest` rows. The evaluator enforces this: a statistic whose input is backtest-only yields at most UNDERPOWERED, or a screen rejection.
   - The policy loader refuses a `forecast_quantile_ladder` lineage with `test_kind=fixed_n`.
   - Non-FQ fixed-n replay FS is unchanged and moot, because `pins.LIVE_GATE_ROUTED_KINDS` = {`forecast_quantile_ladder`} (`pins.py:23`).

9. **K_LIFETIME ≤ 4** stays a ceiling.

10. **Fixed-n-only rules.**
    - The single-look discipline (AUT-4 r11 §3.1) and the window-cap rule (ARCH `:340-346`) apply to `fixed_n` only.
    - `e_process` uses rules 3 and 6.

**Amends; the frozen text itself is not edited.**
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
- **F5 design JSON pins:** γ or T, δ_h, `n_e_power`, `take_rate_lower`, `uptime_floor`, `earliest_look_n`, `m_cap`, λ_max, μ_max, the betting rules, α_kill, and the parity n_par, δ_par and α_par (§R12-5).

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
- `test_eprocess_uncounted_takes_disclosed_never_entered`
- `test_eprocess_null_mc_intraday_dependent_take_count`
- `test_eprocess_null_mc_mixed_side_same_station_day`
- `test_e_b_is_betting_process_not_cs_derived`
- `test_alpha_kill_pinned_separately_never_charged`
- `test_backtest_only_input_never_yields_pass`
- `test_policy_loader_refuses_fq_lineage_fixed_n`

**Fail-closed reading.** Until a merged ARCH-0 change consumes E-25, the exact-set reader refuses any verdict carrying `test_kind`, and F7b cannot merge.

---

## Section 2: Erratum B (paste-ready)

## E-26 (coordinator, 2026-10-04; FQ r3 RC-6 as amended by FQ-R20, FQ-R40; filed by F1 only): two FQ model classes

**Numbering.** The FQ plan's "E-16" is taken, so this is E-26. The Needs of F11 and F13 read E-26.

**Finding.** Only `density_table` and `rung_recalibration` are admitted (ARCH C3 `:235-240`; AUT-3 r6 §3.1; `pins.MODEL_CLASS_COMPONENTS`, `pins.py:96`).

**Rule.**

1. **Two new classes.**
   - Add `forecast_quantile_ladder:density_table_multisource` and `forecast_quantile_ladder:variant_spec`.
   - `MODEL_CLASS_COMPONENTS` becomes `("density_table", "rung_recalibration", "density_table_multisource", "variant_spec")`, append-only.
   - `ROOT_ARTEFACT_COMPONENT` stays `"density_table"` (`pins.py:91`).
   - E-22(d) probing still requires exactly one match.
2. **Single writer.** Both classes are written only by AUT-3 `c3_writer.write_candidate`:
   - into a fresh `derived/artefacts/<model_class>/<sha>/`;
   - with `lineage/v1` and every C3 invariant (`ref_ts_lt_take_ts`, `no_sealed_holdout_rows_in_train`);
   - with one `refit_run/v1` per run.
3. **One mint slot.** ≤ 1 MINT per lineage per day across all four classes (ARCH `:323-325`).
4. **`density_table_multisource`.**
   - Inputs: US weather sources only. Never international, never venue prices, never execution data (ARCH `:238-240`).
   - `data_windows` has one entry per source, each with its `content_sha256`.
   - It may be screened and forward-shadow-replayed. Becoming CHAMPION also needs the F13 ingest actor live, and a separately reviewed G11-style live-loader acceptance with parity tests.
5. **`variant_spec` (FQ-R40).**
   - **The variation lives in the artefact only.** A `variant_spec` child's manifest equals its committed root on every key outside the ARCH §4.2 allowlist (ARCH `:803-806`; `byte_binding.CHILD_MANIFEST_ALLOWLIST`, `byte_binding.py:82-91`).
   - `params` is a closed-key artefact object. Its keys come from the set the FQ live loader reads from an artefact, bounded by that loader (ARCH `:806`, "Recalibration forms live in the artefact, bounded by the loader (G11)").
   - It never changes `taker_fee_coefficient`, `composition_kind` or `stations`. All three are non-allowlisted manifest keys.
6. **Nomination refusal (FQ-R40).**
   - A nomination of a child whose manifest differs from its root outside the §4.2 allowlist is **refused at nomination**. It is not merely barred from CHAMPION later.
   - Variation that needs a manifest change goes through new-family registration (a reviewed commit with its own manifest and allowlist path), never through a MINT.
7. **Forward freeze (FQ-R14).**
   - `variant_spec` `lineage.json` carries `spec_freeze_sha`.
   - `leakage_assertions` gains `nomination_days_after_spec_freeze`.
   - Scan and screen days never count as nomination evidence.

**Consumption.**
- `pins.py:96`, by the ARCH-0 owner.
- AUT-3 r7: `c3_writer` and the §3.1 table.
- F11 and F13.
- The AUT-4 OFFLINE_CHALLENGER screens all four classes.

**Tests (all ADD).**
- `test_model_class_components_append_only_four`. Any existing exact-set pin is widened by exactly these two entries in the same commit (SCOPE: widened by exactly two, never turned into a superset check).
- `test_c3_writer_only_writer_of_new_classes`. This must be a **call-site AST check**: every `write_candidate` call site and every write into `derived/artefacts/<new class>/`, not a name-only check (FQ-R43).
- `test_mint_ceiling_shared_across_four_classes`
- `test_multisource_consumes_no_execution_data`
- `test_variant_spec_params_are_artefact_only`
- `test_variant_spec_refuses_theta_kind_or_new_station`
- `test_variant_spec_nonallowlisted_diff_nomination_refused` (FQ-R40)
- `test_variant_spec_nomination_days_after_spec_freeze`

**Fail-closed reading.** Until E-26 is consumed, `c3_writer` refuses both classes, and the replay probe finds no component, so it refuses.

**Carried to F10.** M1 cells are (side, ask bin). The FQ manifest has no such key (`pm_us_crh_fq_v1.json:1-20`), and they cannot vary in a child. An M1 survivor therefore needs either a reviewed FQ manifest-schema extension (outside E-26) or a new family (FQ-R40).

---

## Section 3: Erratum C (paste-ready)

## E-27 (coordinator, 2026-10-04; FQ-R35): BOOTSTRAP_SEED CHAMPION is the venue's sending FQ root

**Rule.**

1. **The CHAMPION seed.** In ARCH `:472` and `:737-738`, the `pins.BOOTSTRAP_SEED` CHAMPION reads "the venue's sending FQ root at bootstrap".
   - For polymarket_us this is `pm_us_crh_fq_v2`.
   - `pm_us_crh_fq_v1` is seeded **RETIRED**, next to v4, cont and `pm_us_crh_v2`.
   - The pair is allowed: BOOTSTRAP (∅, RETIRED) (`transitions.py:69`).
   - **Evidence that this is safe now:** no bootstrap has run, and `BOOTSTRAPPED_ROOT_MANIFEST_SHA256` is empty (`pins.py:99-100`).
2. **Other mentions of `fq_v1` (covers CONFLICT-7; round 2 to confirm).** Wherever ARCH C3, C5, §5.3 or §10 names `fq_v1` as drill root, incumbent or rollback target (`:264`, `:480`, `:607`, `:1255-1258`), it reads "the venue's FQ CHAMPION at drill time".
3. **Ordering.**
   - The reviewed pins commit that precedes the first bootstrap lands **after** F9-A (the v2 live-orders commit, §R8-4) and **after** F3 (FQ-R33).
   - The seed CHAMPION must hold its own `_LIVE_ORDERS_ALLOWLIST` triple at that commit.
   - E-24 holds: v2 has no registry row before F9-A.

**Unchanged.** ROOT_ADMIT (ARCH `:479`) stays the recovery path after a KILL or a TERMINAL event, including its U2 standing-halt rule. `ROOT_ADMIT_ENABLED_CEILING` stays `False` (`pins.py:22`).

**Tests.**
- `tests/unit/test_autonomy_pins.py` BOOTSTRAP_SEED pin: **SCOPE** (re-pin). The exact-equality assertion is kept, and the expected literal becomes the E-27 seed in the same reviewed commit.
- ADD `test_bootstrap_seed_champion_has_live_orders_triple`
- ADD `test_policy_halt_mirror_on_seeded_retired_family_writes_no_row_and_no_freeze`

---

## Section 4: Erratum D (paste-ready)

## E-28 (coordinator, 2026-10-04; FQ-R36): RC-7 carve-out from AUT-5a's `app/trade.py` ownership

**Rule.** The ARCH §5.1 sentence "`app/trade.py` … belong[s] to AUT-5a alone" (`:1049-1051`) reads: "except that FQ r3 row F6 may change `_compose_forecast_quantile_ladder` (`app/trade.py:676`) once, and F6 merges **before row 7 (AUT-5a) merges**."
- Work after row 7 merges, such as F13, is outside AUT-5a's in-flight exclusivity and is unaffected.

---

## Section 5: AUT-4 r12 delta (paste-ready; round r12 over r11; ARCH Rev 9.2 + E-1..E-28)

**Header.**
- r12 consumes E-25 to E-28, FQ-R13..R33 and FQ-R34..R44.
- r1..r11 are unchanged.
- **Type key:**
  - ADD = new text or test.
  - SCOPE = an existing test keeps its name and its assertion form. Only its fixture or parametrisation is narrowed, or an exact pin is re-pinned or widened by exactly the named items.

### §R12-1 Work-package split (FQ-R19, FQ-R30, FQ-R42): F7a is STATS-ONLY

**WP1s (queue F7a, Needs F1).**
- **Scope.** Move these five §3.3 modules byte-identically into `src/breezy/analysis/stats/`: `sequential_looks.py`, `group_sequential_boundaries.py`, `scoring_core.py`, `market_baseline.py`, `drift_freshness.py`. Sources as in r1.
- **Wrappers (FQ-R42).** The scripts become thin wrappers that **re-export every moved name**, so existing script importers keep working.
  - Verify-first: list the five script importers with codegraph callers of each moved symbol under `scripts/` (`projectPath=/home/jon/breezy`).
  - `test_script_wrappers_delegate` covers every re-exported name by `is` identity (SCOPE: parametrised over the stats set plus the five importers).
- **Verify-first (closure).** In a fresh process, record each module's runtime import closure.
  - A module that reaches `breezy.runtime`, `breezy.strategy`, `…adapters…exec` or any of the ten §3.9b files stays in row 10.
- **RED / GREEN.**
  - `test_moved_functions_byte_identical` and `test_script_wrappers_delegate` (SCOPE: stats set).
  - Byte-unchanged and green: `test_aud07_live_rule_crossing_sim.py`, `test_family_tally_v2_look_loop_golden.py`, `test_nbp_shadow_parity_live.py`.
- **Gates.**
  - The full gate (`EXIT=0`), and `lint-imports` run from the tree with "N kept, 0 broken".
  - `git diff --exit-code <base> HEAD -- <ten §3.9b paths>` is empty.
  - `git diff --name-only` ⊆ {stats files, wrappers, `tests/unit/analysis/stats/**`}.
- **Activation (FQ-R42).** No node restart or respawn.
  - The `family_tally_v2` timer runs the wrapper at its **next firing**. The coordinator watches that firing: the exit code, and a byte-compare of its report against the previous run when the inputs are unchanged.

**WP2 (F7a):** as in r11 (`:1286-1304`), after WP1s. Reliability binning reuses `analysis/brier_decomposition.py` (`bin_by_edges` `:106`, `murphy_decomposition` `:177`) and `stats/scoring_core.py` (FQ-R41).

**WP2b (F7b, Needs E-25, F4, F7a):** §R12-3.

**Row 10 keeps:** WP1r and WP3–WP9.

### §R12-2 Section-by-section changes

| r11 § | Change | Type |
|---|---|---|
| §0 | r12; E-1..E-28; FQ-R13..R44 | ADD |
| §1 table | Rows: e-process (pinned D_d, e_a, e_b), α_kill CS, e-LOND, `evidence_row/v1`, parity detector (§R12-5) | ADD |
| §2 reuse | **e-process/CS:** nothing anytime-valid in repo; build. **e-LOND:** build in persistence. **Reliability:** reuse `brier_decomposition.py:106,:177` before any new code (FQ-R41). **FqEvaluator stats:** `scoring_core`, `market_baseline` | ADD |
| §3.1 single look | Prefix "For `test_kind=fixed_n`:". New `e_process` paragraph per E-25 rule 3 | SCOPE + ADD |
| §3.1 "nothing to evaluate" | Nomination-row fields per E-25 | SCOPE |
| §3.1 fail-closed | Any `evidence_row` that is untagged, has an unknown or unaccepted tag, or has `ref_ts ≥ take_ts` is ERROR plus CRITICAL. A backtest-only PASS is impossible (E-25 rule 8) | ADD |
| §3.1a | `test_kind`, `eta_ns`, `window_end`; FS `n_min` = earliest-look n for `e_process` | ADD |
| §3.2 | The sign-flip permutation is primary for `fixed_n`; `e_process` uses Y_d (E-25 rule 3) | SCOPE |
| §3.3 | New rows (§R12-3). r3's `fq_evaluator.py` resolves to r11 `evaluators/forecast_quantile_ladder.py` (DEDUP-1) | ADD |
| §3.5 nomination | `e_process` branch per E-25 rules 4, 6, 7. `nomination.py` imports `alpha_k` from `persistence/autonomy/elond.py`, the single definition (FQ-R41). Inputs gain `test_kind`, `alpha_schedule`, `gamma_norm_T`, `n_e_power`, `take_rate_lower`, `max_infeasible_nominations`, fold `promotions` and `infeasible_nominations` | ADD |
| §3.5 window-end | Scoped to `fixed_n`; `e_process` rule added | SCOPE + ADD |
| §3.6 LIVE_SEQUENTIAL | `e_process` family: WIN = PASS, KILL = FAIL; `source=live` only. `PREREG_FQ_v1` stays for v1's closing tally | ADD |
| §3.7 look rule | Scoped to `fixed_n`; `e_process` per E-25 rule 3 | SCOPE + ADD |
| §3.8 feasibility | Keys: `test_kind`, `alpha_schedule`, `n_e_power`, `take_rate_lower`, `earliest_look_n`, `m_cap`, `eta_ns`. `feasibility_consistency`: `eta_ns ≤ window_end` | ADD |
| §3.10 R-D | α_k per lineage `alpha_schedule` | SCOPE |
| §3.10 detector map | `parity.fq_v2_shadow_live` → DEMOTE (RECOVERABLE_MODEL); see GAP-16 | ADD |
| §4 WP1/WP2 | Split per §R12-1 | SCOPE |
| §5 association | WP1s, then WP2 (F7a); WP2b (F7b); WP1r (row 10). **C6 (FQ-R41):** FqEvaluator **replaces** the `"forecast_quantile_ladder": RefusingPlugin()` entry in `analysis/autonomy/offline_plugins.py:18`. No `analysis/plugins.py` is created; FQ-R25 is superseded for FqEvaluator. F4 verify-first: confirm no AUT-2 r7 WP needs a new plugin registry file | ADD |
| §6.4 prerequisites | Row 12 = E-25 filed. Row 13 = F5 design JSON (all E-25 consumption keys, plus parity n_par, δ_par, α_par and the projected look date against the KILL date) | ADD |
| §7 store query (2) | `… and .test_kind!="e_process" …` | SCOPE |
| §7 nomination accounting | Any Σα ≤ α_total check is scoped to `halving_v1` (FQ-R43). elond: `alpha_spent == Σ row alpha_k`, each `alpha_k == elond(k, R_at_row)` | SCOPE + ADD |
| §8 risks | FDR not FWER, per-lineage only (E-25 rule 5); conservative R; dilution from pinned m_d; **power record (FQ-R39): with n ≤ 100 before 2027-01-25, power ≈ 50% at ROI ≈ 50%, ≈ 80% at ROI ≈ 60–80%** | ADD |
| §9 | Unchanged. Caps are never read; `m_cap`, `n_e_power` and the take rate are PREREG design values | none |

### §R12-3 WP2b (F7b): e-process, e-LOND, `evidence_row`, FqEvaluator

**Modules.**

- **`analysis/autonomy/eprocess.py`.** Y_d with the pinned m_d, e_a and e_b exactly as E-25 rule 3.
  - λ_d and μ_d are computed from settled days and frozen before the day's first decision.
  - It records `eprocess_uncounted_takes`.
- **`analysis/autonomy/confidence_sequence.py`.** The hedged CS on Y_d at 1 − α_kill (KILL when UB < 0), and the diagnostic BSS CS.
- **`persistence/autonomy/elond.py` (LAYER-1, FQ-R41).**
  - Pure stdlib plus `Decimal`: `gamma(t, T)` and `alpha_k(k, R, schedule, alpha_total)`.
  - `nomination.py` imports it. Analysis re-imports it and never redefines it.
  - Reviewed by the ARCH-0 owner.
- **`analysis/autonomy/evidence_row.py` (FQ-R37).**
  - `load_evidence_rows(store_kind)` is the only constructor. It **derives the path from `store_kind`** through a closed mapping and accepts no path argument:
    - C2 label store → `live`;
    - node C1 shadow Takes → `shadow`;
    - harness or `fs_replay` → `backtest`.
  - `EvidenceRow` is a frozen dataclass whose constructor takes a module-private token as an `InitVar` with no default. So `dataclasses.replace` raises, because an InitVar must be passed explicitly.
  - `__copy__`, `__deepcopy__`, `__reduce__` and `__reduce_ex__` raise `TypeError`.
  - `object.__setattr__` on an `EvidenceRow` is banned in `src/` by an AST test.
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
  - BSS on takes and on all decisions; per-rung PIT; reliability slope via `murphy_decomposition`; Spiegelhalter Z with a blocking minimum sample; net P&L per day.
  - It refuses PASS on backtest-only input.
  - It is registered by replacing `offline_plugins.py:18`.

**Tests, RED first (all ADD unless marked).**
- The r3 F7b list, with `test_elond_equals_geometric_at_zero_discoveries` replaced by `test_elond_alpha_matches_pinned_gamma_schedule` (FQ-R26).
- `tests/unit/autonomy/test_elond.py`:
  - `::test_elond_schedule_refused_for_fixed_n_lineage`
  - `::test_elond_r_counts_only_effective_champion_promotes`
  - `::test_elond_single_definition_in_persistence`. This asserts by `is` identity that the name `nomination.py` uses and the name analysis uses are the same object as `persistence.autonomy.elond.alpha_k` (FQ-R41).
- `tests/unit/autonomy/test_nomination.py`:
  - `::test_e_process_feasible_from_pinned_power_table`
  - `::test_e_process_row_n_min_eff_is_fixed_n_disclosure`
  - `::test_infeasible_nominations_capped_per_lineage`
  - `::test_e_process_nomination_infeasible_without_forward_shadow_source`
- `tests/unit/autonomy/test_forward_shadow.py`:
  - `::test_e_process_fs_copies_row_columns_except_n_min_eff`
  - `::test_e_process_terminal_outcome_final`
  - `::test_e_process_window_end_no_crossing_inconclusive`
- `tests/unit/autonomy/test_eprocess.py`: the E-25 rule-3 tests, including both null MC cases.
- `tests/unit/autonomy/test_eval_live.py::test_live_sequential_e_process_win_pass_kill_fail`
- `tests/contract/test_nomination_columns_contract.py::test_called_inside_begin_immediate_with_e_process_keys`
- `tests/unit/autonomy/test_verdict_schema.py::test_verdict_e_process_fields_null_on_other_kinds`
- `evidence_row` tests:
  - `test_evidence_row_single_loader_contract`
  - `test_load_evidence_rows_accepts_no_path_argument`
  - `test_evidence_row_cannot_be_forged_via_replace_or_pickle`
  - `test_evidence_row_copy_refused`
  - `test_evidence_row_object_setattr_banned_by_ast`
  - `test_ref_ts_lt_take_ts_enforced_at_load`
  - `test_backtest_only_input_never_yields_pass`
  - `test_policy_loader_refuses_fq_lineage_fixed_n`
- Per consumer, the untagged and unknown-tag refusals: `test_fq_evaluator_refuses_untagged` and `…_unknown_tag`; likewise for `eval_live`, `eval_offline_fs` and `parity_gate`. Also `test_shadow_rows_never_enter_live_sequential`.

**Verify-firsts (blocking, FQ-R43).**
1. **Verdict-id golden fixtures.** The three keys enter the identity body, so every verdict id changes. List every golden or fixture verdict id, and every test pinning the `verdict/v1` key set. In the same reviewed commit:
   - re-derive the ids from the spec, never from the code under test (SCOPE: re-pin);
   - widen the key-set pins by exactly three (SCOPE).
2. **`$STATE/derived/verdicts/` is empty.** If it is not, STOP for a ruling, because stored ids would change.
3. **Σα ≤ α_total checks.** Grep tests and code for any Σα ≤ α_total check, and scope each to `halving_v1`.
4. **R.** CONFIRMED (`fold.py:386-401`; `transitions.py:72`). Residual check: whether lineage `promotions` is window-pruned. If it is, record that R is conservative.
5. **`test_c3_writer_only_writer_of_new_classes`** is call-site AST (E-26).

**Gates.**
- The full gate, `lint-imports` with the "live path never imports analysis" contract kept, and the firewall and exec-import-pin guards in the focused gate.
- **Activation:** offline, no respawn.

### §R12-4 r11 tests: scoped (names and assertions byte-unchanged; fixtures use `test_kind=fixed_n`, `alpha_schedule=halving_v1`)

These are as r1 §R12-4, all **SCOPE**:
- the eight `test_forward_shadow.py` tests;
- `test_feasible_nomination_charges_alpha_k_life` and `test_inputs_are_named_block_keys_only`;
- `test_called_inside_begin_immediate_with_named_keys`;
- `test_b_max_covers_k_lifetime_over_three`;
- `test_n_min_is_first_look_n`;
- §7 query (2) and the nomination-accounting check.

**Unchanged:** every other r11 test. **No test is weakened.**

### §R12-5 Parity continuation detector (FQ-R29, FQ-R35, FQ-R39), built in WP2b

- **Detector.** `parity.fq_v2_shadow_live`, kind DRIFT, produced by the existing `eval_live` producer id.
- **Fill-conditioned null (FQ-R39).**
  - For each v2 `source=live` fill i, take the same decision's `source=shadow` record.
  - Live and shadow share the outcome, so the paired P&L difference is execution-only: D_i = (shadow haircut `ask_exec` + shadow fee) − (fill_px + live fee).
  - Only filled decisions enter. Unfilled shadow decisions are excluded and reported as a fill-rate metric, which stays in `drift.fill_rate_slippage`'s domain.
  - The selection effect (shadow P&L on the filled subset against all shadow decisions) is reported, never gated.
  - Null (continue): E[D_i | filled] ≥ −δ_par.
- **Single look, at n_par v2 live fills.**
  - FAIL when the one-sided (1 − α_par) upper bound of mean D is < −δ_par.
  - Before the look: UNDERPOWERED, which never acts.
  - n_par, δ_par and α_par are pinned by F5 (`test_design_json_pins_parity_look_metric_threshold`).
- **Look date against the KILL date (FQ-R39).**
  - The projected look date is t_par = F9-B arm date + ⌈n_par / (`take_rate_lower`·`uptime_floor`)⌉ days.
  - F5 and the F9 evidence state t_par next to the KILL date (2027-01-25).
  - If t_par > KILL date − 14 d, F5 either lowers n_par (with the parity power recomputed) or records the gate as **infeasible before KILL**. In that case F9's acceptance states that continuation protection rests on F6 and `live.drawdown` alone.
- **Actuation (FQ-R35).**
  - Before bootstrap: FAIL → the F6 composed veto refuses (§R8-1).
  - After bootstrap: FAIL → DEMOTE (RECOVERABLE_MODEL) through the AUT-5a engine.
  - Both are restrictive, so overlap after bootstrap is safe.
- **Tests (ADD).**
  - `tests/unit/autonomy/test_parity_gate.py`:
    - `::test_parity_gate_action_is_demote_only`
    - `::test_parity_gate_reads_v2_rows_only`
    - `::test_parity_single_preregistered_look`
    - `::test_parity_underpowered_never_acts`
    - `::test_parity_null_is_fill_conditioned_execution_difference`
    - `::test_parity_unfilled_shadow_decisions_excluded_and_reported`

---

## Section 6: AUT-5 r8 delta (paste-ready; with the consequential AUT-7 r6 retarget table)

**Header.** r8 over r7. It consumes E-10..E-28, FQ-R13..R44 and AUT-4 r12. r1..r7 are unchanged.

### §R8-1 RC-7 carve-out (FQ-R17, FQ-R36, E-28)

**Text added to §5, "Order and parallelism" (`:979`).** "Per E-28, `_compose_forecast_quantile_ladder` (`src/breezy/app/trade.py:676`) is carved out of AUT-5a ownership for one change, F6.
- It wraps the `submit_veto` returned by `_open_halt_latch_preamble` (`trade.py:506`, called at `:709`).
- It is an add-only OR: it refuses wherever the old veto refused. It evaluates the family halt **first**, then the loss stop, then the parity verdict (FQ-R35).
- One callable object reaches both the strategy and the exec client.
- F6 merges **before row 7 merges**."

**F6 tests (FQ-R36; all ADD):**
- `test_composed_veto_is_or_add_only_refuses_wherever_old_refused`. Property test over the old veto's refusal domain.
- `test_composed_veto_is_single_object_shared`
- `test_composed_veto_evaluates_both_returns_halt_first` (r3)
- `test_same_veto_callable_reaches_strategy_and_exec_client` (r3)
- `test_loss_stop_input_missing_refuses_after_halt_branch`
- `test_loss_stop_input_stale_refuses_after_halt_branch`
- `test_loss_stop_input_raising_refuses_after_halt_branch`
- `test_stale_veto_fails_closed_with_alert_sink_down` (FQ-R36). `test_stale_veto_applies_even_when_alert_undelivered` (FQ-R31) is kept.
- `test_composed_veto_refuses_on_accepted_parity_fail`
- `test_composed_veto_refuses_when_parity_verdict_missing_or_stale_at_or_after_n_par`
- `test_composed_veto_ignores_parity_before_n_par`
- **Diff-scope guard:** `test_f6_trade_py_changes_only_compose_fq`. This is an AST hash of every other top-level def in `app/trade.py` against the merge base, plus the gate `git diff --name-only` ⊆ {`app/trade.py`, the probe module, F6 tests}.

**WP5 note (`:888-898`).**
- WP5 rebases over F6. `entry_veto` stays a separate slot (G23).
- ADD `tests/unit/test_registry_boot.py::test_wp5_preserves_fq_composed_veto_callable_identity`.
- All F6 tests stay byte-unchanged and green at WP5's merge sha.

### §R8-2 F6 retirement (FQ-R17, FQ-R28, FQ-R44)

- **Owner.** The AUT-5a row owner, who is the coordinator.
- **Retirement needs all of the following:**
  - (a) N consecutive settled days of accepted `live.drawdown` PASS on the sending FQ root, each with `day_status == EVALUATED` and `drawdown_control_active` true (AD3, r7 `:752`);
  - (b) at least `bridge_retirement_min_fills` live fills over those days. N and the minimum fill count are policy-block keys. Proposed: N = 5, min fills = 10, aligned with `DRAWDOWN_INERT_ALERT_MIN_FILLS` (`pins.py:88`). These are design values, not caps;
  - (c) a fresh `live.drawdown` producer verdict;
  - (d) a reviewed commit made by hand that deletes `loss_stop_probe.py`, its wiring and its unit, citing the verdict ids, followed by a respawn with the post-respawn checks.
- **Nothing auto-retires.**
- **Tests (all ADD):**
  - `tests/unit/test_drawdown_producer.py::test_bridge_retirement_requires_n_consecutive_evaluated_non_inert_pass_days`
  - `::test_bridge_retirement_requires_min_fills`
  - `::test_bridge_retirement_blocked_when_drawdown_producer_stale`
  - `::test_bridge_never_auto_retires`. This is AST: no `src/` or unit path disarms or deletes the probe.

### §R8-3 RC-5: every `fq_v1` reference retargeted to `pm_us_crh_fq_v2`

**Naming hazard.** `pm_us_crh_v2` (`pins.py:107`) is a different, retired CRH family. Never shorten the new root to "v2" in code or tests.

**AUT-5 r7 (19 lines, 25 occurrences).** These are as in r1, except line 172:

| Line | Disposition |
|---|---|
| 172 | **RETARGET under E-27:** "BOOTSTRAP seeds `pm_us_crh_fq_v2` CHAMPION and `pm_us_crh_fq_v1` RETIRED. v1's standing A1 `policy_halt` produces no registry row and no venue freeze (§R8-4 verify)." |
| 343, 434, 567, 589, 664, 665, 674, 685, 689, 698, 699, 702, 926, 937, 963, 987, 991, 1026 | RETARGET (as r1) |

Retargeted: 19 lines. Kept: 0.

**AUT-7 r5 (28 lines, 38 occurrences).**
- As in r1: 26 lines retargeted and 2 kept (`:10` is historical; `:29` is the ARCH §10 quote, with a reading note citing E-27 rule 2).
- The six value-bound lines are retargeted (sha `9c0b6d6e…` at `:66, :324, :339, :353, :354, :752, :804`; d0 `2026-10-02` at `:66, :322`).

**Checklist scoping, r7 `:1027`.** The `_LIVE_ORDERS_ALLOWLIST` diff must be empty except the single RC-5 row.
- ADD `test_live_orders_allowlist_diff_is_only_rc5_row`.

### §R8-4 F9: arming v2 by env and manifest ruling (FQ-R35); the registry seeds it later (E-27)

**Needs:** {F8, shadow resume-bar PASS, F6, RC-5 ruling}. Row 8 and DEP-9 are no longer Needs.

**Each widening act is its own reviewed commit (security item 6).**

| Act | Commit content | Activation |
|---|---|---|
| F9-A, live-orders enablement | v2 manifest `live_orders_ruling` = the RC-5 ruling, plus one `_LIVE_ORDERS_ALLOWLIST` triple. These are the two inseparable halves of G4 | No send yet |
| F9-B, env arm | Env and unit sources switch the sending family from v2-shadow to v2, as v1 was armed on 10-01. Afterwards no env source names v1 | Node respawn plus FQ-R22 checks. Supervisor restart in [01:00Z, 16:40Z) if the env lives in the symlinked unit |
| P-1, pins before the first bootstrap (after F3 and F9-A) | `BOOTSTRAP_SEED` per E-27; `BOOTSTRAPPED_ROOT_MANIFEST_SHA256` rows for v2 (post-F9-A sha), v1 (post-F3 sha), v4, cont and `pm_us_crh_v2` | Row 7 bootstrap |
| P-2 | `_LINEAGE_POLICY_ALLOWLIST` row: `fq_v1` replaced by `pm_us_crh_fq_v2` (still one row) | Registry |
| P-3 | Policy revision: `lineage_roots=["pm_us_crh_fq_v2"]`, the E-25 lineage keys, a `detector_map` parity row; `root_admit_enabled` stays false | Registry |
| (none) | `ROOT_ADMIT_ENABLED_CEILING` stays `False` (`pins.py:22`). Stage flags follow AUT-5 r7 WP9/WP10 unchanged; L2 stays gated by DEP-9 | — |

**v1's halt (FQ-R34).**
- It is not cleared on the F9 path.
- It is cleared only under W15 (ARCH `:720-723`; U2 at `:479`), with the audited `breezy-clear-family-halt` (`clear_family_halt_cli.py:77`, prog `:88`), and only after:
  - the fold shows v1 RETIRED (see CONFLICT-14 for `terminal_frozen`);
  - no env source names v1.
- It is required only before any future polymarket_us ROOT_ADMIT.
- Verify-first (read-only): list every uncleared non-`fee_schedule_drift` `policy_halt` on polymarket_us.

**Verify: RETIRED seed against the mirrored halt (FQ-R35).**
- No allowed pair leaves RETIRED, other than same-state HWM_RESET (`transitions.py:67-94`). HALT and DEMOTE start only from CHAMPION (`:83-84`). A TERMINAL class does not set the venue integrity freeze (`fold.py:441-444`).
- The halt mirror is not yet implemented: `pins.HALT_REASON_CLASS_MAP` (`pins.py:134-144`) is the only artefact. Its owner (AUT-5a) must show that a `policy_halt:*` record on a family that folds RETIRED writes **no** row, raises no `engine_inconsistency`, and does not freeze the venue.
- ADD `test_policy_halt_mirror_on_seeded_retired_family_writes_no_row_and_no_freeze`.

**Tests (all ADD; SCOPE where marked).**
- `test_v2_never_in_registry_before_f9a_commit`
- `test_bootstrap_seed_champion_has_live_orders_triple`
- `test_autonomy_pins.py` seed pin (SCOPE: re-pin)
- `test_no_env_source_names_v1_after_f9b`
- r1's `test_root_admit_v2_requires_parity_detector_mapped` and `test_root_admit_v2_cites_fee_pass` are **dropped**. They were r1 ADDs and never merged, and ROOT_ADMIT is not on the path.

### §R8-5 Parity continuation gate (FQ-R29, FQ-R35)

- **Producer:** AUT-4 r12 §R12-5.
- **Before bootstrap:** the F6 composed veto refuses on an accepted FAIL, or on a missing or stale verdict once v2 live fills ≥ n_par.
- **After bootstrap:** the AUT-5a engine accepts a FAIL as **DEMOTE only** (`test_demotion_never_requires_policy_and_is_immediate`).
- **RESUME after a parity DEMOTE** needs the cause verdict to PASS again. It cannot, because the look is single and final. So v2 stays HALTED until build-side recovery. That is fail-closed, stated as such.
- **Test (ADD):** `tests/unit/test_autonomy_engine.py::test_parity_fail_demotes_never_halts_or_widens`.

### §R8-6 F12: enabling PROMOTE (FQ-R21, FQ-R28, FQ-R38)

- **Ownership.**
  - `transitions._ADMISSION_IMPLEMENTED` (`transitions.py:166-168`, which ships empty) is owned by **WP1b** (ARCH-0 seamA r5 `:909-917`). PROMOTE joins it in WP1b's commit that clears its `blocks_kinds` rows.
  - The L2 flag stays WP9's.
- **What F12 is.** F12 is the policy revision `promote_enabled=true` and its tests.
- **F12 is GATED on all of:**
  - GAP-13: an F5 ruling for a forward-only shadow source for non-champions;
  - WP1b's PROMOTE admission;
  - the DEP-9 ledger being empty.
- **Filing condition.** `fixed_n` lineages meet r7's eta bound. `e_process` lineages meet `eta_ns ≤ window_end`, `nomination_feasible` (including E-25 rule 6b), and eta ≤ KILL − `forward_window_days`.
- **WP3 changes.**
  - `test_promote_disabled_when_n_min_exceeds_window_cap` (r7 `:869`): SCOPE to `fixed_n`.
  - ADD `test_promote_disabled_when_e_process_nomination_infeasible`.

### §R8-7 Policy-block changes (WP3)

- **Per-lineage `lineages.<root>` object:** `test_kind`, `alpha_schedule`, `gamma_norm_T`, `n_e_power`, `take_rate_lower`, `uptime_floor`, `earliest_look_n`, `m_cap`, `max_infeasible_nominations`, `bridge_retirement_consecutive_days`, `bridge_retirement_min_fills`.
- `alpha_spending` (`:599`) is superseded.
- `test_policy_block_exact_set_keys` and `test_policy_block_not_looser_than_code_ceilings`: SCOPE, widened by exactly these keys. `max_infeasible_nominations` is checked against the new pins ceiling.
- ADD `test_policy_loader_refuses_fq_lineage_fixed_n`.
- Drawdown H0 is re-run on v2's lineage under the weekly AB3 re-run.

### §R8-8 CONFLICT, GAP and DEPENDENCY register

| # | Item | Status |
|---|---|---|
| 1 | CONFLICT-1: C4 FWER, fixed-n | RESOLVED by E-25 |
| 2 | CONFLICT-2: §4.2 against `variant_spec` | RESOLVED-by-ruling FQ-R40 (E-26 rules 5–6) |
| 3 | CONFLICT-3: U2 standing halt blocks ROOT_ADMIT | RESOLVED-by-ruling FQ-R34 (narrowing deleted; W15 CLI clear). Moot for F9 under FQ-R35. Residual: CONFLICT-14 |
| 4 | CONFLICT-4: ROOT_ADMIT ceiling | RESOLVED, moot by FQ-R35. The ceiling stays `False` |
| 5 | CONFLICT-5: stage S/L1 loop | RESOLVED-by-ruling FQ-R35 / E-27. Stage S has v2 CHAMPION seeded; L1 exits on ≥ 3 sessions of `registry_resolved family=pm_us_crh_fq_v2`; L1-R is rejected (it trips the DEP-9 ledger and ARCH-0 r5 `:916`) |
| 6 | CONFLICT-6: §5.1 `app/trade.py` ownership | RESOLVED-by-ruling FQ-R36 / E-28 |
| 7 | CONFLICT-7: frozen ARCH names `fq_v1` as drill root | PROPOSED as E-27 rule 2. **OPEN** until round 2 confirms (not separately ruled) |
| 8 | DEDUP-1, LAYER-1, DEDUP-2 | RESOLVED-by-ruling FQ-R41 (`offline_plugins.py:18`; `elond` in persistence; `brier_decomposition` reuse). FQ-R25 superseded for FqEvaluator |
| 9 | DEP-9: owner-placeholder ledger | RESOLVED-by-ruling FQ-R35. It gates L2 only, not F9; the test is unweakened |
| 10 | OPEN-1: `fs_replay` backtest FS | RESOLVED-by-ruling FQ-R37 (E-25 rule 8) |
| 11 | CONFLICT-11: E-24 introduction order | RESOLVED (§R8-4 F9-A then P-1) |
| 12 | GAP-12: root-copy write | RESOLVED (dropped) by FQ-R35. The bootstrap writes root copies |
| 13 | GAP-13: CHALLENGER accrues no shadow n | RESOLVED-by-ruling FQ-R38. F12 GATED; E-25 rule 6b. The F5 ruling itself is **OPEN** |
| 14 | **CONFLICT-13: F3 terminal day against child fixtures** | **OPEN**, recommendation below |
| 15 | **CONFLICT-14: a RETIRED seed is not `terminal_frozen`** | **OPEN**, recommendation below |
| 16 | **GAP-16: parity detector absent from the no-policy fallback** | **OPEN**, see below |
| 17 | **DEP-17: bootstrap after F9-A** | **OPEN** for coordinator acknowledgement |
| 18 | FQ-R39 statistics | RESOLVED in E-25 and §R12-5. Numeric values are **OPEN** in F5 |

#### CONFLICT-13: F3's `terminal_climate_day` against the registry child fixtures (OPEN; recommend (d))

**Evidence.**

1. **The fixture reads the live deploy manifest.**
   - `World` reads the committed `deploy/families/pm_us_crh_fq_v1.json` (`tests/unit/test_registry_replay.py:68`, `:115-116`).
   - It derives the child by byte replacement: the id, then d0 `"2026-10-02"` → `"2026-10-20"` (`:121-124`).
   - Every `test_registry_resolver*.py` and `test_registry_manifest_binding.py` builds on it (`tests/unit/registry_resolver_world.py:41`, `:202-203`; `test_registry_manifest_binding.py:39`).
   - `INCUMBENT = "pm_us_crh_fq_v1"` (`test_registry_fold.py:57`).
2. **Where the failure actually comes from.** After F3, the child inherits `"terminal_climate_day": "2026-10-05"`. The parser refuses terminal < d0 (`family_manifest.py:406-411`), which maps to MANIFEST_INVALID (`byte_binding.py:217-218`).
   - The refusal fires at **parse time**, before `manifest_equal_modulo_allowlist` (`byte_binding.py:124-144`, called at `:272`) is ever reached. The inherited value even equals the root's.
3. **The refusal is correct production behaviour.** A child minted at d0 2026-10-20 under a root closed on 2026-10-05 is an impossible world. Under E-27, v1 is seeded RETIRED and never mints.
4. **Prefixes already separate families.** FQ trial-id prefixes are family-unique: v1's is `forecast_quantile_ladder/trial/pm_us_crh_fq_v1/` (`pm_us_crh_fq_v1.json:4`), and ARCH V10 (`:807`) requires `f"{composition_kind}/trial/{child_id}/"`. `build_family_tally_v2` filters by prefix before the barrier (`family_tally_v2.py:818`, `:838`).
   - So v1's terminal bound only closes v1's own scope against late v1 rows. That is F3's purpose: `family_barrier.assert_family_only`, `family_barrier.py:85-91`.
5. **Precedent.** `terminal_climate_day` is the established manifest mechanism (`pm_us_crh_cont.json:18`; field at `family_manifest.py:250-253`). FQ-R13 binds terminality to "the v1 manifest's `terminal_climate_day` and the AUT-5 registry".

**The options.**

- **(a) Migrate the fixtures to a v2-shaped root.** Blocked: `deploy/families/pm_us_crh_fq_v2.json` does not exist until F8. That would make F3 (start-now, FQ-R30) depend on F8. Reject as F3's fix. Recommended later, as a fixture SCOPE once v2 exists, so the fixture models the E-27 seed.
- **(b) Move the cutoff into tally config.** This contradicts FQ-R13 (terminality belongs to the manifest), and it duplicates an existing manifest field into a second source of truth. Reject.
- **(c) Add `terminal_climate_day` to the §4.2 allowlist.** It does **not** fix the 73 failures, because the refusal is the parser's (evidence 2). The fixture would still need editing, and frozen §4.2 and `byte_binding.py:82-91` would change. It is also unsafe: a child could then drop its root's terminal and reopen a closed lineage's scope. A child's own closure belongs to the registry (FQ-R13), because its bound manifest is immutable (E-24). Reject. This would be a CONFLICT with frozen ARCH `:803-806`.
- **(d) Recommended. Decouple the registry fixture from the live deploy bytes.** A SCOPE change; no test is weakened.
  1. ADD `tests/fixtures/registry_world/pm_us_crh_fq_v1.json`, the byte-exact pre-F3 manifest from `git show <F3 merge-base>:deploy/families/pm_us_crh_fq_v1.json`.
  2. SCOPE: `World.ROOT_SOURCE` (`test_registry_replay.py:68`) points at that fixture. It is still copied into the temp repo as `deploy/families/pm_us_crh_fq_v1.json`, so every test name, assertion and `root_file` path is unchanged.
  3. ADD the drift guard `test_registry_world_root_fixture_equals_deploy_v1_modulo_terminal_day`. It parses both files and compares every `dataclasses.fields(FamilyManifest)` except `terminal_climate_day` and `manifest_sha256`. It asserts the fixture's terminal is `None` and the deploy file's is `"2026-10-05"`.
  4. ADD `test_child_inheriting_root_terminal_before_its_d0_is_refused`. It uses the live post-F3 root bytes and the `replay_stubbed` resolve (`registry_resolver_world.py:157-175`), and expects MANIFEST_INVALID. This pins the correct fail-closed behaviour.

**Verify-firsts.**
- The 73 failures are exactly the `World` consumers.
- `test_autonomy_owner_placeholders.py` fails only transitively: it runs ledger node ids via `run_node_ids` (`:735`). Never edit the ledger to drop rows.
- No test pins the live v1 manifest sha. If one does, widen it by one reviewed row (r3 F3).
- `BOOTSTRAPPED_ROOT_MANIFEST_SHA256` is still empty (FQ-R33 STOP rule; `pins.py:100`).

#### CONFLICT-14: FQ-R34's precondition cannot be met under E-27 (OPEN)

**Evidence.**
- `terminal_frozen` is set only by a TERMINAL-class HALT or DEMOTE, or by a RETIRE with MODEL_BUDGET_EXHAUSTED (`fold.py:357-360`, `:441-442`, `:446-447`).
- A BOOTSTRAP → RETIRED seed sets neither, so "fold shows v1 RETIRED and `terminal_frozen`" is never true.

**Recommendation.**
- An E-27 rule 4: "a BOOTSTRAP row to RETIRED freezes its lineage."
- It is a pure fold rule on row kind and state, and restrictive only. It also blocks ROOT_ADMIT and ROLLBACK into seeded-retired lineages (ARCH `:476`, `:478`, `:479`).
- Verify-first: list the fold tests that assert `terminal_frozen` false for v4, cont or `pm_us_crh_v2`. Any change there is a semantic erratum, never a relaxation.
- ADD `test_seeded_retired_lineage_is_terminal_frozen`.
- **Alternative:** amend FQ-R34's precondition to "RETIRED, seeded or TERMINAL". This is weaker, because it leaves the lineage MINT-eligible unless MINT checks root state.

#### GAP-16: parity detector absent from the no-policy fallback (OPEN)

**Evidence.**
- `pins.DEFAULT_RESTRICTIVE_CLASS` (`pins.py:148-162`) maps `parity.train_serve` to DEMOTE but has no `parity.fq_v2_shadow_live`.
- So between bootstrap and the P-3 policy revision, a parity FAIL has no registry actuation. The F6 veto still refuses (§R8-5).

**Options.**
- (i) Add `parity.fq_v2_shadow_live: (DEMOTE, RECOVERABLE_MODEL)` through an ARCH-0-owner pins commit.
- (ii) Land P-3 in the same session as bootstrap.

Recommend (i).

#### DEP-17 (OPEN)

E-27 makes the first bootstrap, and therefore row-7 stage S activation, wait for F9-A. Before that there is no sending FQ root to seed. Shadow v2 runs by env (F8) in the meantime.

---

## Changes from r1

| Ruling or item | Sections changed |
|---|---|
| FQ-R34 | §R8-8 #3 (narrowing deleted); §R8-4 (W15 CLI clear plus verify-first, off the F9 path) |
| FQ-R35 | New E-27; §R8-3 line 172; §R8-4 rewritten (F9-A/F9-B/P-1..P-3, separate commits, Needs); §R8-5 (F6 before bootstrap, DEMOTE after); §R8-1 F6 parity tests; §R8-8 #4, #5, #9, #12; RETIRED-seed mirror verify |
| FQ-R36 | New E-28; §R8-1 wording "before row 7 merges"; full F6 test list plus diff-scope guard |
| FQ-R37 | E-25 rule 8; §R12-3 `evidence_row` (path derived from store kind, token InitVar, copy/pickle/setattr bans, forgery tests); FQ fixed_n refusal; §R8-8 #10 |
| FQ-R38 | E-25 rule 6b; §R8-6 (F12 GATED; WP1b owns `_ADMISSION_IMPLEMENTED`); §R8-8 #13 |
| FQ-R39 | E-25 rule 3 (pinned m_d denominator chosen and justified, betting e_b, α_kill = 0.05, two MC cases), rule 5 (per-lineage FDR plus null), rule 6 (infeasible cap); §R12-5 (fill-conditioned parity, look date against KILL); §R12-2 §8 power record |
| FQ-R40 | E-26 rules 5–6 (artefact-only variation, nomination refusal); tests renamed or added |
| FQ-R41 | §R12-2 §3.5 and §5 (`elond` import, `is`-identity test; `offline_plugins.py:18` replacement; no `analysis/plugins.py`); `brier_decomposition` reuse |
| FQ-R42 | §R12-1 (wrapper re-exports, five importers, timer next-firing activation) |
| FQ-R43 | §R12-3 verify-firsts (verdict-id goldens, Σα scoping, R confirmed, verdicts dir, AST writer check); E-26 test wording |
| FQ-R44 | §R8-2 rewritten (N consecutive days, min fills, fresh producer, manual commit; four tests) |
| CONFLICT-13 (new) | §R8-8 analysis; recommends (d) |
| New findings | CONFLICT-14, GAP-16, DEP-17; E-27 rule 2 absorbs CONFLICT-7 (OPEN) |

The decisions round 2 needs to make:
- CONFLICT-13: option (d).
- CONFLICT-14: the fold freeze rule, or the weaker precondition change.
- GAP-16: the pins map entry.
- DEP-17: acknowledgement.
- The F5 values for `m_cap`, n_par, δ_par and α_par.
- Whether the parity look date falls before 2027-01-25.

**Source documents:**
- r1 draft and rulings: `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/F1-errata-and-deltas_draft.md`
- FQ-R13..R33: `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/FQ-LOSS-RESPONSE_plan_r3.md`
- Frozen ARCH: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/snapshots/ARCH_rev9_2.md`
- WP1b ownership: `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamA_plan_r5.md`
- The CONFLICT-13 fixture: `/home/jon/breezy/tests/unit/test_registry_replay.py`
---

## Peer-review round 2 rulings (coordinator, 2026-10-06 ~01:00Z; binding for r3)

**Reviews:**
- Architect: REQUEST_CHANGES. The blockers are CONFLICT-14 rule 4 and the P-1 test impact.
- Security: AMEND, 1 HIGH, no CRITICAL.
- Stats: SOUND-WITH-CAVEATS, with 4 required fixes.

- **FQ-R45, CONFLICT-13: option (d) ACCEPTED.**
  - The guard pins the fixture's sha256 as a literal, in addition to the parsed-field comparison.
  - **Verify-first:** after F3, run EVERY direct reader of `deploy/families/pm_us_crh_fq_v1.json`. That is `test_autonomy_pins.py:365`, `test_family_halt_cli_fq.py:155`, `test_nbp_shadow_parity_live.py:776`, `test_fq_s8_registration_artefacts.py:37`, `test_forecast_quantile_ladder_manifest_and_markers.py:23`, `test_ct08_supervisor_contract_surface.py:388`, `test_operator_caps_through_the_live_composition.py:338` and `test_trade_supervisor_phase1_unit.py:85`, plus the production readers `nbp_shadow_parity.py:115` and `family_tally_v2.py:1537`.
  - F3 is rebuilt on this basis now. It does not wait for r3.
- **FQ-R46, CONFLICT-14: E-27 rule 4 REJECTED.** Evidence (architect): it breaks 9 fold assertions (`test_registry_fold_effects.py:401,419,460,489,500,529,543,556`; `test_registry_fold_tallies.py:655`), and its benefits were overclaimed.
  - **Replacement, part 1:** FQ-R34's precondition reads "the fold shows v1 RETIRED and no family of v1's lineage is in any other state".
  - **Replacement, part 2:** a restrictive validate rule, owned by ARCH-0: "a MINT whose lineage root is RETIRED is refused". It needs a verify-first that no existing test mints under a RETIRED root. Test: `test_mint_under_retired_root_refused`.
  - Security preferred the freeze rule. The architect's evidence that it breaks existing assertions, and that MINT never checks `terminal_frozen`, decides it.
- **FQ-R47, GAP-16: option (i).**
  - The pins entry `parity.fq_v2_shadow_live: (DEMOTE, RECOVERABLE_MODEL)` is listed in E-27's consumption list (ARCH `:372` names the literal).
  - Add the exact-value assertion to `test_default_restrictive_class_is_demote_or_halt_with_known_classes`.
  - It lands at or before P-1.
- **FQ-R48, sequence and DEP-17.**
  - **Explicit order:** F9-A → F9-B (verified) → {P-1, P-2, GAP-16 pins} → bootstrap → P-3.
  - Stage S follows F9-B. Sessions before F9-B never count toward L1.
  - Add a test that the registry's resolved family matches the env sender before any L1 session counts (security M3).
  - Row-7 WP1–WP9 may merge, since they are inert while the source is unset. Only WP10 (stage S, L1, L2) waits behind F8, F6, the resume bar and RC-5. Record this delay in PROGRESS.
- **FQ-R49, P-1 test impact (architect HIGH).**
  - Verify-first: every validate-path test that bootstraps `pm_us_crh_fq_v1` as CHAMPION (55 occurrences in 16 files).
  - Option (a), migrating the fixtures to a v2 root, is MANDATORY in the P-1 commit. It is a SCOPE change, never an assertion change.
- **FQ-R50, E-28 wording:** "F6 merges before any row-7 WP that edits `app/trade.py` (WP5). 'Row 7 merged' means its last WP merged."
- **FQ-R51, the §R12-1 activation proof.**
  - Run one hand run of `family_tally_v2` on a frozen input snapshot, before and after the merge. Memory-capped, one heavy job at a time.
  - Byte-compare the two outputs, then watch the next timer firing's exit code.
- **FQ-R52, E-27 text.**
  - It states explicitly that it amends RC-5's "through registry ROOT_ADMIT".
  - Rule 2 treats ARCH `:35`, `:68-69` as historical (no new reading).
  - The drill child `pm_us_crh_fq_v1_r0001` (`:1256`) reads `<champion>_r0001`.
- **FQ-R53, security H1: every ops step needs a pre-flight and a read-back.**
  - Applies to F9-A, F9-B, P-1/bootstrap, the W15 clear, the F7a activation and the F6 retirement.
  - Add the security reviewer's acceptance text verbatim: a dry run from a non-repo cwd with absolute paths, which prints the resolved manifest path and sha, the family and the intended write, and exits non-zero on any unresolved input; then a read-back of the effect, recorded.
  - `a8a66f41` is merged before any of these steps runs.
- **FQ-R54, security M1, M2 and M4.**
  - **M1, parity veto tests.** Each case refuses:
    - an unreadable or raising fill count;
    - a stale age (`STALE_PARITY_H`, pinned);
    - a wrong subject or family.
    - A FAIL also latches: a later UNDERPOWERED or older PASS never un-refuses.
  - **M2, `evidence_row`.** r3 states that the token is an accident guard, not a security boundary. Add:
    - the class made final;
    - a `type(r) is EvidenceRow` check at consumers;
    - a sealed `LoadedEvidence` container returned by the loader and checked by consumers;
    - an AST ban on `pickle.load*` and `__setstate__` in `analysis/autonomy`;
    - an `object.__new__` path test.
  - **M4, the RC-5 live-orders ruling for v2.** The coordinator authors it under the operator's standing grant, where only the two budget caps are operator decisions. It cites the operator's 10-01 FQ live-real-orders ruling (`RULING_operator_fq_live_real_orders_2026-10-01`) as the authority. It is not escalated.
- **FQ-R55, statistics (all four required before filing).**
  1. **m_d.** m_d = `m_cap`, pinned in the F5 design JSON at 2 provisionally. F5's joint power MC chooses between {2, 3}, and m_d no longer tracks L_d.
  2. **Upside clip.** A pinned clip `X_max` applies to h/BE−1 in both e_a and the KILL CS. The downside is never clipped, and the ask floor is kept.
  3. **Joint power.** F5's MC reports joint power for min(e_a, e_b), and `n_e_power` comes from the joint test. The power record (FQ-R39) is re-stated after the MC; until then it is marked provisional and optimistic.
  4. **Ties and voids.**
     - Ties at one decision instant are ordered by G-measurable keys only (station, rung id).
     - A voided take enters as X = 0 and is never dropped.
  - Also state in r3:
    - H0_b ≠ H0_a, so PASS asserts both.
    - KILL's null is "E[Y] ≥ 0 after the haircut", not "no edge", and re-nominations compound the false-kill risk (bounded by the lifetime cap).
    - The parity interval uses a day-clustered bootstrap, with the seed pinned and fills qty-weighted.
