<!-- F1 FQ-PLAN draft (planner, 2026-10-04 ~21:40Z). DRAFT: not filed. CONFLICT/GAP register §R8-8 under peer review; errata E-25/E-26 are filed only after rulings. -->

# F1 FQ-PLAN: errata E-25/E-26 and the AUT-4 r12 and AUT-5 r8 deltas

## Summary

- **Erratum numbers.** E-15 to E-24 are already filed in `ARCH-ERRATA-rev9_2.md`: E-15 is the network field, E-16 is pair citation and root introduction, and the last one is E-24. These drafts use the next free numbers, **E-25** (RC-1) and **E-26** (RC-6). Wherever the FQ plan says "E-15", read E-25; "E-16" reads E-26. That covers the queue tokens of F7b, F11 and F13.
- **`fq_v1` count (my own).**

  | Plan | Lines | Occurrences | Disposition |
  |---|---|---|---|
  | AUT-5 r7 | 19 | 25 | 18 lines retargeted, 1 kept and flagged |
  | AUT-7 r5 | 28 | 38 | 26 lines retargeted, 2 kept and flagged |

  The review's 19 and 28 are line counts, and they match mine. Six more AUT-7 lines carry v1-only values without the string `fq_v1` (the v1 artefact sha and v1's d0). They are listed too.
- **Blockers for the peer loop.** Section 4 lists 12 CONFLICT, GAP and DEPENDENCY items with evidence. Two of them block F9 as currently written:
  - **CONFLICT-3:** ARCH ROOT_ADMIT refuses while any A1 `policy_halt` stands on the venue, so it is blocked by v1's own halt.
  - **CONFLICT-5:** AUT-5 stages S and L1 assume a v1 CHAMPION, which FQ-R13 makes TERMINAL, so the stages loop on each other.

---

## Section 1: Erratum A, paste-ready for `ARCH-ERRATA-rev9_2.md`

## E-25 (coordinator, 2026-10-04; from FQ loss-response r3 RC-1 as amended by FQ-R15, FQ-R20, FQ-R26; filed by F1 only, FQ-R19): e-process verdicts and the per-lineage e-LOND α schedule

**Numbering.** The FQ plan calls this "E-15". That number is taken by the network-namespace erratum, so this is E-25. Every FQ-plan reference to E-15, including F7b's Needs token, reads E-25.

**Finding.** Today only one kind of confirmatory test exists:
- **What ARCH C4 allows.** C4 (`snapshots/ARCH_rev9_2.md:288-301, :323-346`) and AUT-4 r11 (§3.1 `:469-472`, §3.5 `:560-572`) allow only a fixed-n, single-look FORWARD_SHADOW. Its α is the geometric FWER schedule α_k = α_total·2^−k_life.
- **What PREREG v2 needs instead.** It confirms on an anytime-valid calendar-day e-process and controls FDR with e-LOND, one stream per lineage (FQ r3 §6.3–§6.4).
- **What cannot express it.** Neither the `verdict/v1` key set (`src/breezy/persistence/autonomy/verdict.py:178-189`) nor the window-cap rule (`:340-346`) can express that.

**Rule.**
1. **New verdict fields.** All three are nullable additions to the `verdict/v1` exact set, and all are part of the identity body:
   - **`test_kind`** ∈ {`fixed_n`, `e_process`}.
     - On FORWARD_SHADOW it is never null.
     - On LIVE_SEQUENTIAL it is `e_process` only when the family PREREG registers an e-process. A family with an LD-OBF boundary keeps it null, and its semantics stay under `family_prereg_sha256`.
     - On every other kind it is null.
   - **`eta_ns`** (int, e_process only). The projected UTC ns at which n reaches the pinned power-0.8 sample size `n_e_power[k]`, at the lower take-rate bound. It is null when the nomination is infeasible or the test is fixed_n.
   - **`window_end`** (ISO date). FORWARD_SHADOW only, for both test kinds: the nominee's last forward climate day, inclusive, using AUT-4's `windows.py` arithmetic. It is null on every other kind.
2. **`n_min_eff` is not redefined.**
   - It is null on every `e_process` verdict and unchanged on `fixed_n`.
   - For e_process, `n_min` is the pre-registered earliest-look n from the F5 N record (FQ r3 §6.6). No PASS or FAIL is written below it.
3. **e-process outcomes (FORWARD_SHADOW, e_process).** The evaluator monitors every day:
   - **PASS:** min(e_a, e_b) ≥ 1/α_k, where e_a is the net-P&L e-process at the haircut ask and e_b is the BSS-on-takes e-value, and the calibration guard reports sufficient and not failing.
   - **FAIL:** the hedged CS has UB < 0 (KILL).
   - **UNDERPOWERED:** otherwise.
   - **INCONCLUSIVE(`window_end_no_crossing`):** the window ends with no crossing. This is final.
   - PASS and FAIL are final and never reopened. On LIVE_SEQUENTIAL e_process, WIN is PASS and KILL is FAIL; the detector map is unchanged.
4. **α schedule.** Each lineage root pins its schedule in the policy block: `alpha_schedule` ∈ {`halving_v1`, `elond_heavy_tailed_v1`}.
   - **`halving_v1`** is ARCH's α_total·2^−k_life, unchanged.
   - **`elond_heavy_tailed_v1`** gives α_k = α_total · γ_k · (R + 1), where:
     - k = `k_life` of this feasible nomination;
     - γ_t = g(t) / Σ_{s=1..T} g(s), with g(t) = 1/(t·ln²(t+1));
     - T = the pins ceiling `MAX_NOMINATIONS_PER_LINEAGE_LIFETIME` (`pins.py:38`, 4). This is the default. F5 may pin per-epoch budgets instead, and the design JSON pins exactly one;
     - R = the lineage's CHALLENGER→CHAMPION PROMOTE heads that took effect before the nomination row's `ts_ns` (the fold's `promotions` tally, `fold_tallies.py:61-62,87`).
   - **Why R is safe.** Every such PROMOTE needed an accepted FORWARD_SHADOW PASS (ARCH `:476`), so R ≤ the true discovery count. The α_t used is therefore ≤ e-LOND's α_t, and the e-LOND FDR bound still holds.
   - **Frozen at test start.** `alpha_k` is computed once, inside the nomination's `BEGIN IMMEDIATE` transaction, and written to the row. It is never recomputed, and FORWARD_SHADOW copies it.
   - **No pooling** across lineages. `alpha_spent` stays Σ row `alpha_k` (the fold is unchanged).
   - **Pairing rule.** The policy loader refuses `elond_heavy_tailed_v1` on a `fixed_n` lineage and `halving_v1` on an `e_process` lineage.
5. **Error-rate statement.** At R = 0, Σ_k α_k ≤ α_total. With R > 0 the bound is FDR ≤ α_total under arbitrary dependence, not FWER. ARCH's "Σα ≤ α_total per lineage" (`:334`) holds for `halving_v1` lineages only. That is the FWER-to-FDR substitution this programme adopts (FQ r3 §6.4).
6. **`nomination_feasible`.**
   - **`fixed_n`:** unchanged (`n_min_eff ≤ n_cap`).
   - **`e_process`:** true iff ⌊`take_rate_lower` · forward days from the nomination to `window_end` · `uptime_floor`⌋ ≥ `n_e_power[k]`. Here `n_e_power` is a pinned policy-block table (k = 1..K) of the smallest n at which F5's Monte Carlo gives power ≥ 0.8 at α_k, computed with R = 0 (the conservative choice). This is arithmetic on named block keys only (AUT-4 r11 K1).
   - **An infeasible nomination burns no K slot:** `alpha_k = 0`, `k_life` unchanged, `infeasible_nominations` +1, and the window slot is used. ARCH `:343-344` is unchanged.
7. **C5 row shape is unchanged.** All five nomination columns stay required (`registry_shape.py:41,73-74`). On an e_process row, `n_min_eff` holds the fixed-n value computed from the same pinned block (same meaning, disclosure only, never a gate). `n_cap` is unchanged.
8. **K_LIFETIME ≤ 4** stays a ceiling.
9. **Fixed-n-only rules.**
   - The single-look discipline (AUT-4 r11 §3.1 `:469-472`) and `test_nominee_single_look_never_reopened` apply to `fixed_n` only.
   - The window-cap rule (ARCH `:340-346`) applies to `fixed_n` only. `e_process` uses rule 6.

**Amends; the frozen text itself is not edited (CONFLICT-1).**
- ARCH C4 `:288-301` (schema), `:323-336` (α_k, Σα ≤ α_total), `:340-346` (window cap).
- AUT-4 r11 §3.1, §3.1a, §3.5, §3.7, §3.8 and §7.
- The AUT-5 r7 policy key `alpha_spending` (`:599`).

**Consumption.**
- **ARCH-0 owner:** three nullable keys in `verdict.py:178-189`, plus kind rules next to `_FORWARD_SHADOW_ONLY` (`:189`, `:264-270`).
- **AUT-4 r12:** F7b.
- **AUT-5 r8:** policy-block keys and the WP3 tests.
- **F5:** the design JSON pins γ, T, δ_h, `n_e_power`, `take_rate_lower` and the earliest-look n.

**Tests (all additive).**
- `test_c4_e_process_n_min_eff_null_with_eta_ns_window_end`
- `test_elond_alpha_matches_pinned_gamma_schedule` (FQ-R26)
- `test_alpha_frozen_at_test_start_per_lineage_no_pooling`
- `test_infeasible_nomination_burns_no_k_slot`
- `test_elond_schedule_refused_for_fixed_n_lineage`
- `test_elond_r_counts_only_effective_champion_promotes`
- `test_verdict_e_process_fields_null_on_other_kinds`

**Fail-closed reading.** Until a merged ARCH-0 change consumes E-25, the exact-set reader refuses any verdict carrying `test_kind`, and F7b cannot merge (it Needs E-25).

---

## Section 2: Erratum B, paste-ready

## E-26 (coordinator, 2026-10-04; from FQ loss-response r3 RC-6 as amended by FQ-R20; filed by F1 only, FQ-R19): two FQ model classes

**Numbering.** The FQ plan calls this "E-16". That number is taken (pair citation and root introduction), so this is E-26. The Needs of F11 and F13 read E-26.

**Finding.** Only two FQ model classes are admitted today:
- ARCH C3 (`:235-240`), AUT-3 r6 §3.1 (`:88-92`) and `pins.MODEL_CLASS_COMPONENTS = ("density_table", "rung_recalibration")` (`src/breezy/persistence/autonomy/pins.py:96`) admit exactly these two.
- So neither a new US-weather-source density (F13) nor an AUT-S/M1 survivor (F10/F11) can be minted.

**Rule.**
1. **Two new classes.**
   - Add `forecast_quantile_ladder:density_table_multisource` and `forecast_quantile_ladder:variant_spec`.
   - `MODEL_CLASS_COMPONENTS` becomes `("density_table", "rung_recalibration", "density_table_multisource", "variant_spec")`, append-only.
   - `ROOT_ARTEFACT_COMPONENT` stays `"density_table"` (`pins.py:91`; E-14 rule 2).
   - E-22(d) probing is unchanged: exactly one match.
2. **Single writer.** Both classes are written only by AUT-3's `c3_writer.write_candidate` (AUT-3 r6 §3.6 `:237`):
   - written into a fresh `derived/artefacts/<model_class>/<sha>/`;
   - with `lineage/v1` and every C3 invariant, including `ref_ts_lt_take_ts` and `no_sealed_holdout_rows_in_train`;
   - with one `refit_run/v1` per run.
3. **One mint slot.** ≤ 1 MINT per lineage per day across all four classes; ARCH `:323-325` is unchanged.
4. **`density_table_multisource`.**
   - It consumes external US weather sources only, never international and never venue prices (memory `prediction-from-weather-venues-for-cost`). It consumes no execution data (ARCH `:238-240`, unchanged).
   - `data_windows` carries one entry per source, each with its `content_sha256`.
   - It can be screened and forward-shadow-replayed at once. Promotion to CHAMPION additionally needs:
     - the F13 ingest actor live;
     - a G11-style live-loader acceptance with parity tests, in a separate reviewed WP.
5. **`variant_spec`.**
   - `params` is a closed-key object whose keys are a subset of the FQ manifest schema's keys at filing. Today those are the v1 manifest keys, `deploy/families/pm_us_crh_fq_v1.json:1-20`. Each value must pass the manifest validator. This is what "FQ-manifest-expressible only" means.
   - It never changes `taker_fee_coefficient` (θ is the estimand, ARCH `:704`), never changes `composition_kind`, and never adds a station outside the root's.
   - Anything else is a cross-family variant. Those go through new-family registration (a reviewed commit with its own manifest and allowlist path), never a MINT.
6. **ARCH §4.2 is unchanged.**
   - A child still equals its committed root on every key except the six allowlisted ones (ARCH `:803-806`; `byte_binding.manifest_equal_modulo_allowlist`, `byte_binding.py:124`).
   - So a `variant_spec` MINT whose `params` differ from the root on a non-allowlisted key may be screened, nominated and forward-shadow-replayed, but can never become CHAMPION as a child. Its promotion path is new-family registration followed by ROOT_ADMIT (CONFLICT-2).
7. **Forward freeze (FQ-R14).**
   - `variant_spec` `lineage.json` carries `spec_freeze_sha`, the committed SHA of the frozen M1/AUT-S survivor spec.
   - `leakage_assertions` gains `nomination_days_after_spec_freeze`, an additive assertion name.
   - Scan or screen days never count as nomination evidence.

**Consumption.**
- `pins.py:96`, reviewed by the ARCH-0 owner.
- AUT-3 r7: `c3_writer`, the §3.1 table, and the ordering rule at `:124` extended to four classes.
- F11, F13.
- AUT-4 OFFLINE_CHALLENGER screens all four classes; the NOT_DISTINCT rule is unchanged.

**Tests (additive).**
- `test_model_class_components_append_only_four`. Any existing exact-set pin on `MODEL_CLASS_COMPONENTS` is widened by exactly these two entries in one reviewed commit, never relaxed to a superset check.
- `test_c3_writer_only_writer_of_new_classes`
- `test_mint_ceiling_shared_across_four_classes`
- `test_multisource_consumes_no_execution_data`
- `test_variant_spec_params_subset_of_manifest_keys`
- `test_variant_spec_refuses_theta_kind_or_new_station`
- `test_variant_spec_child_with_non_allowlisted_diff_never_champion`
- `test_variant_spec_nomination_days_after_spec_freeze`

**Fail-closed reading.** Until E-26 is filed and consumed, `c3_writer` refuses both classes, and the replay probe finds no component, so it refuses (E-22d).

**Finding carried to F10.** M1 cells are (side, ask bin). The FQ manifest has no side or ask-bin key (`pm_us_crh_fq_v1.json:1-20`). So under rule 5 an M1 survivor is **not** `variant_spec`-expressible today. It reaches AUT-S only through either:
- a reviewed FQ manifest schema extension (the exact-set keys in `family_manifest.py`), which is a separate change and not part of E-26; or
- new-family registration.

---

## Section 3: AUT-4 r12 delta, paste-ready (round r12 over r11; ARCH Rev 9.2 + errata E-1..E-26)

**Header.**
- r12 consumes E-25 and E-26 and the FQ rulings FQ-R13..R33.
- r1..r11 are unchanged. Every r12 change is listed in §R12.
- **Type key:** ADD means new text or test. SCOPE means an existing test keeps its name and assertions, and only its fixture or parametrisation is narrowed.

### §R12-1 Work-package split (FQ-R19, FQ-R30): F7a is pinned STATS-ONLY

**WP1s, the stats-only part of the G36 move (queue F7a, Needs F1).**
- **Scope.** Move the five §3.3 `src/breezy/analysis/stats/` modules byte-identically, with the scripts kept as thin wrappers:
  - `sequential_looks.py` ← `family_tally_v2.py:625`, `aud07_live_rule_crossing_sim.py:158,210`;
  - `group_sequential_boundaries.py` ← `crh_group_sequential_boundaries.py:243`;
  - `scoring_core.py` ← `forecast_conditional_scoring.py:110,139,237,267,278,303,392,428`;
  - `market_baseline.py` ← `wp7b_market_as_forecaster.py:169,232,372,475,707`;
  - `drift_freshness.py`.
  - These are the statistics FqEvaluator needs (`scoring_core`, `market_baseline`). The other three move with them so the G36 byte-identity pin stays one set.
- **Stays in queue row 10 (WP1r):**
  - `analysis/autonomy/shadow_replay.py`, `subprocess_rss.py`, `import_blocker.py`, `scripts/ops/permit_line_check.py`;
  - the cut set W1–W5 and R-1;
  - all §3.9a/§3.9b gates, the `tests/fixtures/wp1/**` captures, and the §3.9b (7) supervisor runbook (r11 `:1282`).
- **Verify-first (read-only).** In a fresh process, record each moved module's runtime import closure.
  - A module whose closure contains any `breezy.runtime`, `breezy.strategy` or `…adapters…exec` module, or any of the ten §3.9b-pinned files, stays in row 10. Record which.
  - The rest move.
- **RED / GREEN.**
  - Scoped: `tests/unit/analysis/stats/test_moved_source_pinned.py::test_moved_functions_byte_identical` and `::test_script_wrappers_delegate`, parametrised over the stats set only. Row 10 appends the remaining move set to the same parameter list (additive).
  - Byte-unchanged and green: `test_aud07_live_rule_crossing_sim.py`, `test_family_tally_v2_look_loop_golden.py`, `test_nbp_shadow_parity_live.py`.
- **Gates.**
  - The full gate (`EXIT=0`) and `lint-imports` ("N kept, 0 broken").
  - `git diff --exit-code <base> HEAD -- <ten §3.9b paths>` is empty.
  - `git diff --name-only` ⊆ {the stats files, the five wrappers, `tests/unit/analysis/stats/**`}.
- **Activation.** Offline. No restart and no respawn, because no live-path file is touched.

**WP2 (queue F7a): as written in r11** (`:1286-1304`), and after WP1s. Its reliability-binning reuse reads `stats/scoring_core.py`.

**WP2b (NEW, queue F7b, Needs E-25, F4, F7a).** See §R12-3.

**Row 10 keeps:** WP1r, WP3–WP9. WP0 and WP7a for v2 run inside F5. r11's WP0/WP7a for `PREREG_FQ_v1` close with v1's tally only.

### §R12-2 Section-by-section changes

| r11 § (lines) | Change | Type |
|---|---|---|
| §0 header | r12; errata E-1..E-26; FQ-R13..R33 | ADD |
| §1 table (`:341-356`) | Rows added: e-process/CS (§R12-3, WP2b); e-LOND α schedule (E-25, WP2b plus `persistence/autonomy/elond.py`); `evidence_row/v1` (WP2b); parity continuation detector (§R12-5) | ADD |
| §2 reuse (`:364-390`) | Rows added. **e-process/CS:** nothing in the repo is anytime-valid; `PortfolioAnalyzer` (`analyzer.py:38`) and `roi_bound` are not; build. **e-LOND:** `hypothesis_ledger.alpha_remaining` (`:825`) is Bonferroni; build, persistence layer. **FqEvaluator stats:** reuse the moved `scoring_core` (Brier, reliability, cluster bootstrap) and `market_baseline` (ask comparator, look-ahead guard); PIT and Spiegelhalter Z are new and small | ADD |
| §3.1 single look (`:469-472`) | Prefixed "For `test_kind=fixed_n`:". New e_process paragraph: daily monitoring; terminal PASS/FAIL final; `INCONCLUSIVE(window_end_no_crossing)` | SCOPE + ADD |
| §3.1 "nothing to evaluate" (`:476`) | "four C4 fields" becomes "the nomination-row fields per E-25 (e_process: `k_life`, `alpha_k`, `n_cap`; `n_min_eff` null)" | SCOPE |
| §3.1 fail-closed (`:480-483`) | Add: any `evidence_row` that is untagged, has an unknown tag, a tag outside the consumer's accepted set, or `ref_ts ≥ take_ts` is ERROR plus CRITICAL | ADD |
| §3.1a table (`:529-541`) | Rows for `test_kind`, `eta_ns`, `window_end` per E-25. FS `n_min` for e_process is the earliest-look n. `n_min_eff` is null for e_process | ADD |
| §3.2 (`:490`) | The date-cluster sign-flip permutation statistic is the primary statistic for `fixed_n`. e_process uses the calendar-day Y_t (§R12-3) | SCOPE |
| §3.3 modules (`:504-521`) | New rows (§R12-3). r3 F7b's `fq_evaluator.py` resolves to r11's existing `evaluators/forecast_quantile_ladder.py` (DEDUP-1) | ADD |
| §3.5 nomination (`:560-572`) | e_process branch per E-25 rules 4, 6, 7. Engine inputs gain the lineage keys `test_kind`, `alpha_schedule`, `gamma_norm_T`, `n_e_power` (table), `take_rate_lower`, plus fold `promotions` for R | ADD |
| §3.5 window-end rules (`:576-579`) | Scoped to `fixed_n`; e_process rule added | SCOPE + ADD |
| §3.6 LIVE_SEQUENTIAL (`:587-594`) | For a family whose `family_prereg` registers an e-process: WIN is PASS, KILL is FAIL (`live.sequential` HALT RECOVERABLE_MODEL, unchanged), else UNDERPOWERED; accepts `source=live` only. v2's `family_prereg_sha256` is the F5 ruling. `PREREG_FQ_v1` (`:464`, `:1149`) stays for v1 until it is RETIRED | ADD |
| §3.7 look rule (`:610`) | Scoped to `fixed_n`. e_process predicates per E-25 rule 3; (c) is the calibration guard with a minimum sample that blocks on insufficient | SCOPE + ADD |
| §3.8 feasibility (`:620-628`) | Keys added: `test_kind`, `alpha_schedule`, `n_e_power`, `take_rate_lower`, `earliest_look_n`, per-nominee `eta_ns`. The `feasibility_consistency` e_process clause uses `eta_ns ≤ window_end` | ADD |
| §3.10 R-D (`:1161-1168`) | "α_k = α_total·2^−k_life" becomes "per lineage `alpha_schedule` (E-25)" | SCOPE |
| §3.10 detector map (`:1177`) | Add `parity.fq_v2_shadow_live` → DEMOTE (RECOVERABLE_MODEL) (§R12-5) | ADD |
| §3.11 (`:1183`) | `eval_completeness`: FORWARD_SHADOW expected set unchanged (one per open-window nominee, either `test_kind`) | none |
| §4 WP1/WP2 (`:1238-1304`) | Split per §R12-1 | SCOPE |
| §5 association/order (`:1352-1383`) | WP1s, then WP2 (F7a); WP2b (F7b); WP1r with Wave 1 tail (row 10). C4 → AUT-5: E-25 fields. C6: `FqEvaluator` registers into `src/breezy/analysis/plugins.py`, which F4 creates (FQ-R25) | ADD |
| §6.4 (`:1430-1442`) | Prerequisite rows added: 12 = E-25 filed (F1); 13 = F5 design JSON committed (γ, T, δ_h, `n_e_power`, `take_rate_lower`, earliest-look n, parity look/metric/threshold) | ADD |
| §7 store query (2) (`:1454`) | Becomes `select(.kind=="LIVE_SEQUENTIAL" and .test_kind!="e_process" and .outcome=="PASS" and .n < .metrics.n_max)` | SCOPE |
| §7 nomination accounting (`:1458`) | The halving formula applies to `halving_v1` lineages. elond lineages check `alpha_spent == Σ row alpha_k`, each `alpha_k == elond(k, R_at_row)` | SCOPE + ADD |
| §8 | Risks added: FDR is not FWER (E-25 rule 5); conservative R; Monte Carlo misspecification of `n_e_power`, mitigated by F5's exact-null and verbatim-loop MC (L-40, L-41) | ADD |
| §9 | Unchanged. Caps are never read, and `n_e_power` and the take rate are PREREG design values, not caps | none |

### §R12-3 WP2b: e-process, e-LOND, `evidence_row`, FqEvaluator (F7b)

**Modules.**
- `src/breezy/analysis/autonomy/eprocess.py` (FQ r3 §6.3):
  - Y_t = Σ(h−BE)/ΣBE per calendar day, with BE = ask + fee.
  - The ask floor and Y_max are pinned, and the CS range is normalised so the KILL side has a usable λ.
  - λ_t uses settled days only, and its denominator is fixed at decision time.
  - K_t = Π(1 + λ_s·Y_s), with λ ∈ [0, λ_max ≤ 0.5].
- `src/breezy/analysis/autonomy/confidence_sequence.py`:
  - the hedged CS; KILL only when UB < 0;
  - the BSS-on-takes CS with the ask as comparator;
  - min(e_a, e_b).
- **`src/breezy/persistence/autonomy/elond.py` (LAYER-1).** It is placed in the persistence layer, not in `analysis/autonomy/` as r3 F7b lists:
  - **Why:** `nomination.py` lives in the persistence layer (r11 `:516`), and the live path may not import `breezy.analysis` (r11 `:394`).
  - **Contents:** pure stdlib plus `Decimal`; `gamma(t, T)` and `alpha_k(k, R, schedule, alpha_total)`.
  - **Reuse:** analysis imports it and never redefines it.
  - **Review:** ARCH-0 owner, on the same basis as `nomination.py` and `sample_size.py`.
- **`src/breezy/analysis/autonomy/evidence_row.py`**, the RC-3 adapter as amended:
  - `EvidenceRow` is a frozen in-memory dataclass. `source` ∈ {`live`, `shadow`, `backtest`} is set by the loader from the store the row came from: the C2 label store is `live`, the node's C1 shadow Takes are `shadow`, and harness or `fs_replay` output is `backtest`.
  - **Single loader:** `load_evidence_rows(store_kind, …)` is the only constructor (AST-enforced).
  - `ref_ts < take_ts` is enforced at load.
  - C2 gains no column.
  - Accepted tags per consumer:

    | Consumer | Accepts |
    |---|---|
    | FqEvaluator e_process (FS and resume bar) | {shadow} |
    | `eval_live` LIVE_SEQUENTIAL | {live} |
    | `eval_offline` fixed_n FS lane | {backtest} (OPEN-1) |
    | parity detector | {live, shadow}, `subject = pm_us_crh_fq_v2` only |
    | AUT-S screen (F11) | {backtest}, reject-only |

- **`evaluators/forecast_quantile_ladder.py` (FqEvaluator, DEDUP-1)** computes:
  - BSS on takes and on all decisions;
  - per-rung-position PIT;
  - the reliability slope and Spiegelhalter Z, with a minimum sample that blocks on insufficient;
  - net P&L per calendar day.
  - It reuses `stats/scoring_core` and `stats/market_baseline`. It registers into `src/breezy/analysis/plugins.py`, serialised after F4.

**Tests, RED first.**
- The r3 F7b list, with `test_elond_equals_geometric_at_zero_discoveries` replaced by `test_elond_alpha_matches_pinned_gamma_schedule` (FQ-R26).
- Added:
  - `tests/unit/autonomy/test_elond.py::test_elond_schedule_refused_for_fixed_n_lineage`, `::test_elond_r_counts_only_effective_champion_promotes`. Verify-first: confirm via codegraph that fold `promotions` counts CHALLENGER→CHAMPION heads only; if it does not, use a filtered count.
  - `::test_elond_single_definition_in_persistence`
  - `tests/unit/autonomy/test_nomination.py::test_e_process_feasible_from_pinned_power_table`, `::test_e_process_row_n_min_eff_is_fixed_n_disclosure`
  - `tests/unit/autonomy/test_forward_shadow.py::test_e_process_fs_copies_row_columns_except_n_min_eff`, `::test_e_process_terminal_outcome_final`, `::test_e_process_window_end_no_crossing_inconclusive`
  - `tests/unit/autonomy/test_eval_live.py::test_live_sequential_e_process_win_pass_kill_fail`
  - `tests/contract/test_nomination_columns_contract.py::test_called_inside_begin_immediate_with_e_process_keys`
  - `tests/unit/autonomy/test_verdict_schema.py::test_verdict_e_process_fields_null_on_other_kinds`
  - `test_evidence_row_single_loader_contract`, `test_ref_ts_lt_take_ts_enforced_at_load`
  - per consumer: `test_fq_evaluator_refuses_untagged`, `…_unknown_tag`; `test_eval_live_refuses_untagged`, `…_unknown_tag`; `test_eval_offline_fs_refuses_untagged`, `…_unknown_tag`; `test_parity_gate_refuses_untagged`, `…_unknown_tag`; `test_shadow_rows_never_enter_live_sequential`; `test_backtest_rows_reject_only`
- **ARCH-0 file change.** `verdict.py:178-189` gains three keys.
  - Verify-first: list every merged test that pins the `verdict/v1` key set, and widen each by exactly these three keys in the same reviewed commit.
  - Verify that `$STATE/derived/verdicts/` is empty. If it is not, the identity change needs a ruling before merge (verdict ids would change).

**Gates.**
- The full gate, `lint-imports` with the "live path never imports analysis" contract kept, and the firewall and exec-import-pin guards.
- **Activation:** offline modules, no respawn.

### §R12-4 r11 tests: scoped (names and assertions byte-unchanged; fixtures use `test_kind=fixed_n`, `alpha_schedule=halving_v1`)

- `tests/unit/autonomy/test_forward_shadow.py`:
  - `::test_nominee_single_look_never_reopened`
  - `::test_window_cap_below_n_min_is_inconclusive_by_construction`
  - `::test_window_end_underpowered_final`
  - `::test_look_waits_for_n_ioc_min_inside_window`
  - `::test_window_end_before_n_ioc_min_is_fill_rate_underpowered_final`
  - `::test_look_time_independent_of_nominee_outcomes`
  - `::test_look_counts_signature_takes_no_nominee_input`
  - `::test_fs_reads_columns_never_recomputes`
- `tests/unit/autonomy/test_nomination.py::test_feasible_nomination_charges_alpha_k_life`, `::test_inputs_are_named_block_keys_only`
- `tests/contract/test_nomination_columns_contract.py::test_called_inside_begin_immediate_with_named_keys`
- `tests/unit/autonomy/test_permutation.py::test_b_max_covers_k_lifetime_over_three` (`halving_v1` only; WP2b's refusal test keeps elond off fixed_n, so the B cap is never reached)
- `tests/unit/autonomy/test_eval_live.py::test_n_min_is_first_look_n` (LD-OBF families)
- §7 store query (2) and the nomination-accounting check (§R12-2)

**Unchanged:** every other r11 test, including `test_infeasible_nomination_charges_no_alpha`, `test_infeasible_nomination_uses_window_slot`, `test_alpha_never_pooled_across_lineages`, `test_k_life_mismatch_is_error_k_exceeded` and `test_offline_successor_lands_before_predecessor_expiry`. **No test is weakened.**

### §R12-5 Parity continuation detector (FQ-R29)

- **Detector.** `parity.fq_v2_shadow_live`, kind DRIFT, produced by the existing `eval_live` producer id (no new pin id).
- **Inputs.** v2's own `source=live` fills paired with the same decisions' `source=shadow` predictions. v1 rows never enter.
- **Look rule.** One pre-registered look at n v2 live fills, with metric and threshold from the F5 design JSON (`test_design_json_pins_parity_look_metric_threshold`).
  - Before the look: UNDERPOWERED, which never acts.
  - At the look: PASS or FAIL.
  - FAIL declares DEMOTE (RECOVERABLE_MODEL). That is its only action.
- **Tests.** `tests/unit/autonomy/test_parity_gate.py::test_parity_gate_action_is_demote_only`, `::test_parity_gate_reads_v2_rows_only`, `::test_parity_single_preregistered_look`, `::test_parity_underpowered_never_acts`.

---

## Section 4: AUT-5 r8 delta, paste-ready (with the consequential AUT-7 r6 retarget table)

**Header.** r8 over r7. It consumes E-10..E-26, FQ-R13..R33, and the AUT-4 r12 delta. r1..r7 are unchanged.

### §R8-1 RC-7 ownership carve-out (FQ-R17)

- **Text added to §5 "Order and parallelism" (`:979`).** "`_compose_forecast_quantile_ladder` (`src/breezy/app/trade.py:676`) is carved out of AUT-5's exclusive ownership for one change: FQ r3 row F6, the composed veto.
  - It wraps the existing `submit_veto` from `_open_halt_latch_preamble` (`trade.py:709-714`).
  - It evaluates the family halt **and** the loss stop on every call, and returns the halt reason first.
  - The same callable reaches the strategy and the exec client.
  - F6 merges before row 7 (AUT-5a) starts, so a single writer holds at every instant. No other line of `app/trade.py` is carved out."
- **Note added to WP5 (`:888-898`).**
  - WP5 rebases over F6. WP5's `entry_veto` stays a separate required slot (ARCH G23). WP5 never alters the F6 composed `submit_veto`, nor the identity of the callable passed to the strategy and the exec client.
  - **Test (additive):** `tests/unit/test_registry_boot.py::test_wp5_preserves_fq_composed_veto_callable_identity`.
  - All F6 tests stay byte-unchanged and green at WP5's merge sha. That includes `test_composed_veto_evaluates_both_returns_halt_first` and `test_same_veto_callable_reaches_strategy_and_exec_client`.
- **CONFLICT-6** applies (§R8-8).

### §R8-2 F6 retirement trigger (FQ-R17, FQ-R28)

- **Owner.** The AUT-5a (row 7) owner, which is the coordinator. That owner also owns the re-calibration trigger.
- **Trigger.** The first accepted `live.drawdown` verdict that meets all of:
  - subject lineage = the sending FQ root (`pm_us_crh_fq_v2` after F9);
  - `schemas.drawdown_control_active(verdict)` is true (AD3, r7 `:752`);
  - **and** `day_status == EVALUATED`.
- **Why EVALUATED is required.** r7 `:752` makes `BELOW_MIN` count as active, so a zero-fill PASS on v2's new lineage would retire the bridge before any drawdown could trip (`test_drawdown_fail_requires_min_fills`). EVALUATED is a strict subset of "non-inert", so the rule stays inside FQ-R17 and errs in the safe direction.
- **Procedure.**
  - The retirement commit deletes `loss_stop_probe.py`, its wiring, and the producer unit.
  - Its evidence cites the verdict id.
  - Then a node respawn with the post-respawn checks.
- **Test.** `tests/unit/test_drawdown_producer.py::test_bridge_retirement_requires_evaluated_non_inert_pass` (ADD).

### §R8-3 RC-5: every `fq_v1` reference, retargeted to the v2 root `pm_us_crh_fq_v2`

**Naming hazard.** The retired CRH seed `pm_us_crh_v2` (`pins.py:107`) is a different family. Never shorten the new root to "v2" in code or tests.

**AUT-5 r7 (19 lines, 25 occurrences).**

| Line | Content | Disposition |
|---|---|---|
| 172 | BOOTSTRAP seed CHAMPION | **KEEP** (frozen ARCH `:472,:737`; merged `pins.py:103-108`). Add: "v1's standing A1 `policy_halt` mirrors as TERMINAL at the first pass (ARCH `:705`): HALTED, then RETIRED, lineage `terminal_frozen`. The FQ root `pm_us_crh_fq_v2` enters only by ROOT_ADMIT (§R8-4)." See CONFLICT-5 and CONFLICT-7 |
| 343 | E-5 restore predicates | RETARGET |
| 434 | ROLLBACK to root | RETARGET (CONFLICT-7) |
| 567 | drill clause: children `_r0001/_r0002`, root | RETARGET to `pm_us_crh_fq_v2_r0001/_r0002` |
| 589 | `lineage_roots` | RETARGET |
| 664, 665 | block `drill_clause` | RETARGET |
| 674 | `shadow_probe_clause.family_id` | RETARGET; runs only once v2 is CHAMPION on the shadow chain (§R8-4) |
| 685 | drill start gate | RETARGET |
| 689, 698, 699 | drill timeline | RETARGET |
| 702 | failed-close restore | RETARGET |
| 926 | WP9 `_LINEAGE_POLICY_ALLOWLIST` row | RETARGET: the row is replaced, so it is still one row (r7 `:794`) |
| 937 | L1 exit `registry_resolved family=…` | RETARGET; stage re-anchoring in §R8-4 |
| 963 | AUT-7 consumption | RETARGET |
| 987, 991 | live-proof node lines | RETARGET |
| 1026 | checklist (f) restored sha | RETARGET (`<v2 density sha, F8>`) |

Retargeted: 18 lines. Kept: 1 line.

**AUT-7 r5 (28 lines, 38 occurrences); consequential AUT-7 r6 edits.**

| Line | Disposition |
|---|---|
| 10 | **KEEP**: historical code evidence at `4b8347a6`. r6 adds v2 manifest evidence once F8 merges |
| 29 | **KEEP** (4 occurrences): verbatim quote of ARCH §10 (`:1255-1258`). Add a reading note (CONFLICT-7) |
| 35, 41, 43 | RETARGET; 41 and 43 paraphrase ARCH `:264` and `:607` (CONFLICT-7) |
| 66 | RETARGET to `deploy/families/pm_us_crh_fq_v2.json` with placeholders for the d0, sha and line numbers; r6 re-verifies them via codegraph after F8 |
| 225, 336, 339, 353, 354 | RETARGET; child id `pm_us_crh_fq_v2_r0001`; sha placeholder |
| 402, 404, 405, 406, 410, 418, 419, 425 | RETARGET (419: "the fq_v2 lineage") |
| 739, 744, 750, 752 | RETARGET; sha placeholder at 752 |
| 811, 825, 830, 831, 863 | RETARGET |

Retargeted: 26 lines. Kept: 2 lines.

**Values bound to v1 without the string `fq_v1`, also retargeted.**
- AUT-7 r5: sha `9c0b6d6e…` at `:66, :324, :339, :353, :354, :752, :804`, and the root d0 `2026-10-02` at `:66, :322`. That is six lines not counted above.
- AUT-5 r7: none. `:600` and `:602` are window anchors, not v1 values.

**Checklist scoping.** In r7 `:1027` (envelope invariants), "the diff of `_LIVE_ORDERS_ALLOWLIST` is empty" becomes "empty except the single reviewed RC-5 row for `pm_us_crh_fq_v2`, under `RULING_fq_v2_live_orders_<date>`". This is a scoping, ADD `test_live_orders_allowlist_diff_is_only_rc5_row`.

### §R8-4 F9: arming v2 through registry ROOT_ADMIT and RESUME

**The F9 commit (one reviewed commit, after the shadow resume bar passes; FQ-R23/R29).**
- v2 manifest `live_orders_ruling` set to the RC-5 ruling.
- One `_LIVE_ORDERS_ALLOWLIST` triple.
- A `pins.BOOTSTRAPPED_ROOT_MANIFEST_SHA256` row for v2 in the same commit (E-14 rule 7; `pins.py:100`).
- `_LINEAGE_POLICY_ALLOWLIST` row replaced.
- Policy revision:
  - `root_admit_enabled=true`;
  - `lineage_roots=["pm_us_crh_fq_v2"]`;
  - the E-25 lineage keys;
  - a `detector_map` row `parity.fq_v2_shadow_live → DEMOTE/RECOVERABLE_MODEL`.
- `ROOT_ADMIT_ENABLED_CEILING=True` (`pins.py:22`; the ARCH path at `:827-828`; r7 `:794`).

**The ROOT_ADMIT itself.**
- E-16(b) `(∅, CHAMPION)` with ACTIVATE, at the first 16:45Z pass ≥ `ROOT_ADMIT_COOLDOWN_H` after v1's TERMINAL row.
- It cites the `drift.fee_schedule` PASS (E-22b).

**Ordering rules.**
- **E-24.** v2 gets **no** registry row before the F9 commit. Its manifest sha binds at the row that introduces it, and F9 edits the manifest.
- **RESUME** of v2 follows r7 §3.3 unchanged, for recoverable causes only.
- **No v1 halt is cleared.**

**Tests (ADD).**
- `test_root_admit_v2_requires_parity_detector_mapped`
- `test_v2_never_in_registry_before_f9_commit`
- `test_root_admit_v2_cites_fee_pass`

**Blocking for F9 as written:** CONFLICT-3, CONFLICT-5, GAP-12 and DEP-9 (§R8-8).

### §R8-5 Parity continuation gate (FQ-R29)

- The producer, detector and look are in AUT-4 r12 §R12-5.
- The engine accepts a FAIL as **DEMOTE only**, through the AUT-5a engine. Demotion never requires a policy (`test_demotion_never_requires_policy_and_is_immediate`). The F6 option is dropped.
- **RESUME after a parity DEMOTE** needs the cause verdict to PASS again. With v2 HALTED there are no new live fills, so it stays HALTED until build-side recovery. That is the fail-closed outcome, stated as such.
- **Test.** `tests/unit/test_autonomy_engine.py::test_parity_fail_demotes_never_halts_or_widens` (ADD).

### §R8-6 F12: enabling PROMOTE (FQ-R21, FQ-R28)

- WP9's second commit already sets `pins.ENABLED_WIDENING_KINDS = WIDENING_KINDS` (`transitions.py:144-156`; the L2 flag).
- F12 adds PROMOTE, together with its SUPERSEDE and ACTIVATE partners, to `transitions._ADMISSION_IMPLEMENTED` (`transitions.py:168`, which ships empty), as the owner WP.
- F12 files `promote_enabled=true` only when:
  - `fixed_n` lineages meet r7's eta bound;
  - `e_process` lineages meet `eta_ns ≤ window_end`, `nomination_feasible`, and `eta ≤ KILL − forward_window_days`.
- Its tests are planned inside the F12 row.
- **WP3 scoping.** `test_promote_disabled_when_n_min_exceeds_window_cap` (r7 `:869`) is SCOPED to `fixed_n`. ADD `test_promote_disabled_when_e_process_nomination_infeasible`.

### §R8-7 Policy-block changes (WP3)

- **Additive keys.** A per-lineage `lineages.<root>` object holding `test_kind`, `alpha_schedule`, `gamma_norm_T`, `n_e_power`, `take_rate_lower`, `earliest_look_n`.
- `alpha_spending` (`:599`) is superseded by the per-lineage `alpha_schedule`.
- `test_policy_block_exact_set_keys` and `test_policy_block_not_looser_than_code_ceilings` widen by exactly these keys in the same reviewed commit.
- **Drawdown H0.** The fill rate was measured on v1. It is re-run on v2's lineage under the weekly AB3 re-run.

### §R8-8 CONFLICT, GAP and DEPENDENCY register (for the coordinator and the peer loop; nothing below is decided)

1. **CONFLICT-1 (frozen ARCH C4 `:323-346`, `:288-301`).** FWER and fixed-n only. Resolved by E-25. This is recorded, not open.
2. **CONFLICT-2 (frozen ARCH §4.2 `:803-806`).** A `variant_spec` child cannot differ from its root on a non-allowlisted key, and M1's (side, ask bin) is not an FQ manifest key (`pm_us_crh_fq_v1.json:1-20`).
   - E-26 does not amend §4.2.
   - Promotion goes through new-family registration. AUT-S/M1 needs a reviewed manifest schema extension first (F10).
3. **CONFLICT-3 (frozen ARCH `:479`; r7 `:365`). BLOCKS F9.**
   - ROOT_ADMIT refuses while any uncleared A1 `policy_halt` stands on **any family of the venue**.
   - v1's halt is set through the CLI (FQ-R13), and F9 clears no v1 halt.
   - **Proposed erratum (draft, needs a ruling plus security review):** "standing" excludes a `policy_halt` on a family the fold shows RETIRED with its lineage `terminal_frozen`, when the ROOT_ADMIT target's lineage differs. The reviewed allowlist triple and ruling stay the human act.
   - This narrows a safety guard, so it is not adopted here.
   - The alternative is a human CLI clear with an audit record after the registry shows v1 RETIRED. That contradicts F9's acceptance text.
4. **CONFLICT-4 (frozen ARCH `:827-828`; `pins.py:22`).** ROOT_ADMIT is inert until the ceiling is flipped. Resolved by the F9 commit through the path ARCH already sanctions (r7 `:794`). Recorded.
5. **CONFLICT-5 (r7 WP10 `:936-937`; ARCH `:472,:737`). BLOCKS row-7 activation and F9.**
   - Under FQ-R13, BOOTSTRAP seeds v1 CHAMPION and the A1 mirror immediately RETIREs it. Stage S then has no CHAMPION, so its ATTEST and shadow-probe criteria cannot be met, and L1's exit line naming v1 cannot appear.
   - The L1 cut-over (`BREEZY_FAMILY_SOURCE=registry`) would also stop v2's shadow run, which composes from env only in `registry_shadow` mode.
   - L2 needs L1's exit. ROOT_ADMIT needs L2's flag. So the stages loop on each other.
   - **Proposed:**
     - Hold stage S (`registry_shadow`, env family = v2 shadow) through F8 and the resume bar.
     - Re-anchor the S and L1 criteria to a venue with no sender until F9: every pass journaled, `REGISTRY_UNAVAILABLE` delivered.
     - Add stage **L1-R** = `ENABLED_WIDENING_KINDS {RESUME, ROOT_ADMIT, ACTIVATE}` in a reviewed commit with F9.
     - L1 then exits on ≥ 3 sessions of `registry_resolved family=pm_us_crh_fq_v2`.
   - Rejected alternative: seed v2 in BOOTSTRAP. That contradicts ARCH `:472` and the ruling that F9 arms through ROOT_ADMIT.
6. **CONFLICT-6 (frozen ARCH §5.1 `:1049-1051`).** "`app/trade.py` … belongs to AUT-5a alone." The RC-7 carve-out needs a one-line erratum or a coordinator reading that the rule is single-writer sequencing, which F6-before-row-7 preserves.
7. **CONFLICT-7 (frozen ARCH `:264, :472, :480, :607, :737, :1255-1258`).** These name `fq_v1` as the drill root and rollback target, so the RC-5 retarget is a reading of frozen text.
   - **Proposed one-line erratum:** "in C3, C5, §5.3 and the §10 AUT-7 text, `fq_v1` reads 'the venue's FQ root champion at drill time' (`pm_us_crh_fq_v2` after F9), except the BOOTSTRAP seed".
8. **DEDUP-1 / LAYER-1 (FQ r3 F7b file list).**
   - `fq_evaluator.py` duplicates r11's `evaluators/forecast_quantile_ladder.py`.
   - `elond.py` must live in `persistence/autonomy/`, because `nomination.py` cannot import the analysis layer (r11 `:394,:516`).
9. **DEP-9 (r7 `:818`, `test_l2_widening_requires_empty_placeholder_ledger`).**
   - Any enabled widening kind beyond {RESUME}, which includes L1-R's ROOT_ADMIT, requires the owner-placeholder ledger to be empty. That means the AUT-6, AUT-2, AUT-4 and AUT-7 placeholders (`:821-836`) must all be GREEN.
   - So F9's real Needs exceed {F8, 8, F6}. The test is a safety guard and is not weakened. Queue F9 as GATED on the ledger being empty.
10. **OPEN-1.** The `fs_replay` tag (`backtest`) means a fixed-n FS PASS on a replay would fall under the PREREG v2 rule that backtest rows may only reject.
    - FQ lineages are `e_process` by policy, so v2 is unaffected.
    - The peer loop decides whether non-FQ fixed-n lineages keep r11's replay-based FS.
11. **CONFLICT-11 (E-24, E-14 rule 7).** v2 must not be introduced into the registry before the F9 manifest edit. This is enforced by §R8-4. Recorded.
12. **GAP-12 (r7 `:180`; the bootstrap-only write drop-in for `derived/artefacts` roots, B3).**
    - ROOT_ADMIT needs v2's `artefact.json` and `roots/pm_us_crh_fq_v2.json` (E-14 rules 1 and 3), but only the bootstrap mode may write root copies.
    - **Proposed:** a one-time transient root-copy run in the E-6 pattern, restricted to ids in `BOOTSTRAPPED_ROOT_MANIFEST_SHA256`, before the ROOT_ADMIT pass. The alternative is a reviewed widening of the prelaunch drop-in.

**Files used.**
- `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/FQ-LOSS-RESPONSE_plan_r3.md`, `…_r2.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/ARCH-ERRATA-rev9_2.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/reviews/snapshots/ARCH_rev9_2.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-4-evaluation_plan_r11.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-5-promotion-demotion_plan_r7.md`
- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/AUT-7-rollback_plan_r5.md`
- `/home/jon/breezy/src/breezy/persistence/autonomy/{pins.py,transitions.py,verdict.py,registry_shape.py,validate.py,fold.py,fold_tallies.py}`
- `/home/jon/breezy/src/breezy/app/trade.py`
- `/home/jon/breezy/deploy/families/pm_us_crh_fq_v1.json`