# S3 plan r4: DELTA against `S3_loss_floor_reachability_plan_r3.md` (HEAD `4fb736f6`, 2026-10-13) — r4 delta, rev 2 after round-2

**Status: r4 = r3 + this delta; READY (rev 2: round-2 items folded).** Rev 2 folds round-2 items from `docs/plans/backlog/MAKER_2026-10-12/reviews/S3-r4-pmr-final.md` (N-1..N-6) and the architect round-2 review.

r3, `docs/plans/backlog/MAKER_2026-10-12/reviews/S3-r2-final.md` and the r1 dispositions stay in force. This delta replaces only the anchors named below.
Sources:
- `docs/plans/backlog/MAKER_2026-10-12/reviews/S3-r3-pmr-verification.md` (N1–N6, C1–C5);
- `docs/plans/backlog/MAKER_2026-10-12/reviews/S3-r4-pmr-final.md`;
- architect rounds 1–2;
- `docs/evidence/RULING_MAKER-S3_loss_stop_window_2026-10-13.md` (**FINAL**, `35e0289d`; O-1..O-6 binding).

## Verified at 4fb736f6 (codegraph + line reads; `35e0289d` is docs-only on top)
- **Exit floor.** `exit_probability` = `max(_P_EXIT_FLOOR, pool_exit_fraction)` (`scripts/analysis/fq_loss_floor_mc_rows.py:280-283`), with `_P_EXIT_FLOOR = 0.10` (`:53`) and `KAPPA_FLOOR = 0.02` (`:52`). It is passed to every sim (`fq_loss_floor_mc_engine.py:153`) and applied on the S4 row only (`fq_loss_floor_mc_draw.py:241-247`).
- **Window arithmetic.** `n_cal = inclusive_days(freeze, horizon)` (`engine.py:231`). `t_low_count = ⌊n_days·λ_sd·p_keep·tick_share⌋` (`fq_loss_floor_mc_gate.py:136-142`). `inclusive_days` returns 0 when end < start (`gate.py:145-148`). `DEFAULT_FREEZE`/`HORIZON` (`gate.py:57-58`). `epoch_grid` depends on the freeze only (`gate.py:151-153`).
- **Clamp.** `_criticals(sim, n_days, t_min)` (`engine.py:111`) takes `end = cuts[min(n_days, len(cuts)) - 1]` (`:117`). It **clamps to the simulated length**. `crossing_rate(critical, c)` is at `fq_loss_floor_mc_solve.py:48`.
- **Hard-coded binding sites (three).**
  - `outer.py:45` `_BINDING`;
  - `report.py:80` `_BINDING`;
  - `fq_loss_floor_mc_e2.py:195`: `finish_e2` → `sensitivity_c(binding=(("H0","none"),("S4","none"),("S5","bind")), …)`.
- **np_bound coupling.** `fq_loss_floor_np_bound.py` imports `MIXES, _partition, _seed, prepare_mix_groups` (`:36-40`), `ticking_share` (`:52`) and `simulate_family` (`:57`). It raises on `MIXES != _MIXSET` (`:94`, `:147-148`).
- **S1 census.** `src/breezy/analysis/maker_tape_census.py`: one row per (station, climate_day). `REASONS` (`:126-134`) = PRE_TRADE_CAPTURE, NEVER_LISTED, AMBIGUOUS_NO_CLEAN_INSTANCE, TRADE_PARSE_FAILURE, LOW_COVERAGE, LONG_HOLE, COVERED. `first_seen_ns: int | None` (`:448`).
- **Maker rebate.** `MakerRebateUnmodelledError` is at `src/breezy/adapters/polymarket_us/errors.py:305` (maker coefficient −0.0125, `:308`).
- `tests/unit/test_runtime_import_isolation.py` exists.
- **WP0 is committed:** `c4447c4b` on `backlog/maker-s3-2026-10-13` (worktree `.claude/worktrees/maker-s3`).
  - Its base is `5b82b3de`, not the delta anchor `4fb736f6`. The difference is docs-only (LESSONS archive), so the pins are unaffected.
  - WP0 pins `engine._CAL`, `report._BINDING` and `outer._BINDING` (`test_fq_module_constants_are_unchanged`).

## (a) Frozen cell and per-cell re-check (§1, §4.4, §4.5, WP4 step 4; ruling O-4; PMR N1, N-2, N-6)
- **r3 said:** the artifact records "`alpha_star`, `t_min`, `c`" (singular). No cell is named.
- **r4 says** (rule pinned in WP3 code before the binding run):
  1. **Frozen cell.** Use the binding cell at `f_kill` nearest S2's realised (k, b).
     - b = median of S2's realised fill-bid histogram (S2 output 4). If b lies outside [0.70, 0.80], the **binding run is REFUSED** (spec B_FLOOR/B_CAP), never extrapolated.
     - k = the admitted MAX_RUNGS. If the admission ruling has not landed, both k values count as bracketing.
     - If b is between grid points or at a midpoint, or k is undetermined, freeze the **larger c** of the bracketing cells.
     - Larger c is the LESS protective choice (it fires later). Protection is enforced by the re-check in step 2 (O-4).
     - The frozen c is **solved at the `f_kill` tick count**; the artifact says so. Real ticks above that point raise the false-stop rate exactly as the tail does (N-6).
     - The frozen `alpha_star` and `t_min` are the ones solved with that c.
  2. **Re-check.** At the frozen (c, t_min, α*), every binding cell is re-checked at both `f_kill` and `f_pass`, with the same seeds, using `crossing_rate` on that cell's criticals. It records:
     - G1 (`repeated_crossing`, margin, `fully_lost_fraction`);
     - G3(−0.16) ≥ 2.5·α*;
     - **the cell's own H0 crossing rate per binding row** (H0, S4, S5-bind, S8), which must be ≤ α* + 3·binomial SE at 10,000 replicates (N-2).
  3. **Verdict (amends §1 / §4.5).** A cell "passes" only if its own solve is `sqrt_boundary` **and** all three checks hold at the frozen c.
     - REACHABLE: every binding cell passes at `f_pass`.
     - UNDERDETERMINED: every binding cell passes at `f_kill`, and some cell fails at `f_pass`.
     - UNREACHABLE: some binding cell fails at `f_kill`.
     - **Disclosure (artifact + §4.5):** the verdict deliberately couples to b cells S2 never realised. A larger frozen c can fail G1 on such a cell, and that yields UNREACHABLE.
  4. **Artifact keys.**
     - Top-level scalars: `frozen_cell = {k, b, f_kill}`, `frozen_c`, `frozen_c_deff`, `frozen_t_min`, `frozen_alpha_star`.
     - Per cell, under `cells[*]`: `c`, `c_deff`, `certified_ticks`, `frozen_c_g1_holds`, `frozen_c_g3_by_delta`, `frozen_c_h0_rate_by_row`, `frozen_c_pass`.
     - S5 reads **only** the top-level `frozen_c_deff`.
- **Tests (WP3):**
  - `test_frozen_c_reevaluates_g1_g3_on_every_binding_cell`. Two cells with different tick counts. The c comes from the nearest cell, and the larger c is taken on bracketing. The other cell records G1, G3 **and** H0 rates, and a failing re-check flips the verdict.
  - `test_binding_mode_refuses_realised_bid_outside_floor_cap`.

## (b) Window unit: 110 inclusive climate dates (§2 item 3, §3 step 3, §4.3, WP4 step 4; ruling O-1/O-6)
- **r3 said:**
  - "a relative 110 days" / "110-day label";
  - "Under the absolute date the window is ~0 days".
- **r4 says:**
  - Everywhere: **"110 inclusive climate dates"**, counted from the S5 PREREG `holdout_start_date`. Ticks are an output, never the window unit.
  - §2.3 becomes: "The window ruling is FINAL (`35e0289d`). Under the absolute alternative the window is ~64 climate dates from the S5 assumed 2026-11-23 start and ~0 from a post-PASS live start. Either way the stop would expire on 2027-01-25."
  - The artifact records:
    - `certified_horizon_climate_days = 110`;
    - `certified_ticks = T_low` (epoch 0) per cell and for the frozen cell;
    - the O-6 string verbatim: "window = FQ v2 window 2026-10-08..2027-01-25 used as a 110-climate-date label; certified_horizon_climate_days = 110; certified_ticks = <T_low of the frozen cell>; frozen cell = <k, b, f_kill>; frozen_c_deff = <value>; see RULING_MAKER-S3_loss_stop_window_2026-10-13".
- **Test:** `test_artifact_records_window_label_and_certified_horizon`. It checks the exact O-6 string, `certified_horizon_climate_days == inclusive_days(DEFAULT_FREEZE, HORIZON) == 110`, and `certified_ticks == t_low_count(...)` per cell.

## (c) Mandatory `horizon_sensitivity` cell (WP3 pins, WP4 step 3, §2, §7; ruling O-1/O-2; PMR N-1, N-5)
- **r3 said:** "refuses any other freeze/horizon". Test: `test_other_freeze_or_horizon_is_refused`.
- **r4 says:** exactly one extra horizon is pinned in WP3 code before the binding run.
  - The freeze stays 2026-10-08. Any other freeze is refused.
  - L_cap = `inclusive_days(holdout_start_date, calendar_cap_date)` from the S5 cap pin (S5 r4 delta WP0a).
  - **Re-simulation, not re-scoring (N-1).** Calling `_criticals` with `n_days = L_cap` on the 110-date sim would clamp silently (`engine.py:117`) and report the 110-date rate. So the frozen cell is **re-simulated** with `simulate_family(n_days = L_cap, …)`, using the same seeds, data and binding rows.
  - A dedicated crossing-rate-only path scores it: `_criticals(sim, L_cap, frozen_t_min)` → `crossing_rate(·, frozen_c)` per binding row.
    - There are **no epoch gates, no G1/G3, no solve.** Epochs past the horizon would get `inclusive_days` = 0 (`gate.py:145-148`).
    - The path asserts `len(cuts) >= L_cap` on every replicate.
  - It records:
    - `L_cap` and both S5 dates;
    - `false_stop_rate_by_row` at the frozen (c, t_min);
    - `worst_binding_row_rate`;
    - `certified_ticks_at_cap`;
    - the sentence "capital-conservative; costs power; a tail STOP is terminal STOP, not FAIL, not refutation".
  - It is report-only and never enters the verdict.
  - **Re-run rule (N-5).** A pre-freeze re-run is allowed only when the S5 cap pin changes (e.g. the 2027-11-30 clamp shortens L_cap). It uses the same seeds and stays report-only. The new cell REPLACES the old one for S5, and both are kept in the record with their pin shas. A re-run is never driven by results.
  - **§2 binding entry item 5 (new):** the S5 cap pin is committed. Binding mode refuses without `--s5-cap-pin PATH`.
  - **§7 new row:** "S5 cap pin | S5 r4 delta WP0a | not produced".
- **Tests:**
  - `test_other_freeze_or_horizon_is_refused` is replaced by `test_other_freeze_is_refused`.
  - New: `test_horizon_sensitivity_cell_is_report_only_and_pinned`.
  - New: `test_horizon_sensitivity_resimulates_to_l_cap`. It asserts `len(cuts) >= L_cap`, and that the rate at L_cap is ≥ the rate at 110 on a seeded case with L_cap > 110.
  - New: `test_binding_mode_refuses_missing_s5_cap_pin`.

## (d) Single frozen form; tie tolerance (§4.4; ruling O-3; PMR N2/N5)
- **r3 said:** "the PREREG may freeze either form". Test (iii) expected agreement "on every path".
- **r4 says:**
  - The frozen object is **(σ·√1.5, `frozen_c_deff`)**, with `c_deff = c/√1.5` at full float precision. The unit c with an inflated σ is forbidden.
  - Test (iii): indicators agree on every path except fp ties, where |S_t + c√t|/√t < 1e-9. The test counts ties (expects 0) and asserts every disagreement is a tie.
  - Keep the §4.4 "clustered-null risk" sentence in the artifact.

## (e) L-33 classification (WP0, WP1)
- **WP0 — DONE** (`c4447c4b`, base `5b82b3de`).
  - Five tests GREEN, including `test_fq_floor_document_hash_is_stable_across_identical_runs`.
  - Hashes: A `3d7e1554…`, B `3b02cc46…`. `fq_before.json` `f811908e…`.
  - The r4 completion criteria are met: (i) per-assertion `MUTATION_RED_EVIDENCE` in the WP0 return; (ii) hash stability across two runs.
  - The WP1 brief copies the mutation block into the WP1 evidence note.
- **WP1 CHARACTERISATION** (mutation evidence, no RED). The only RED available would be ImportError/TypeError (L-33).
  - `test_run_floor_default_and_explicit_fq_spec_hash_equal`
  - `test_persist_none_leaves_rng_stream_unchanged`
  - `test_fq_spec_document_has_no_floor_spec_key`
  - `test_m_pool_equals_m_no_on_all_no_templates` (existing `apply_mix`, `rows.py:249-256`)
- All other WP1 tests are CHANGE.

## (f) WP1: FQ-default rule, three binding sites, missing tests
- **FQ defaults.** Every new `FloorSpec` field and the `simulate_family(persist=…)` parameter default to the FQ value. `MIXES`, `PATH_FAMILIES`, `_partition`, `_seed`, `prepare_mix_groups`, `ticking_share` and `simulate_family` keep their names and FQ behaviour, because np_bound imports them and enforces MIXES drift. np_bound is not modified.
- **Three binding sites read `spec.binding`:**
  - `outer.binding_c` (`outer.py:87`, replacing the use of `_BINDING` at `:111`);
  - `report` binding checks (`:128`, `:175`, `:188`);
  - **`finish_e2`'s `sensitivity_c(binding=…)` at `fq_loss_floor_mc_e2.py:195`** (added to WP1 scope).
- **FQ constants stay.** `outer._BINDING`, `report._BINDING` and `engine._CAL` **stay as the FQ default values** (`FQ_SPEC` reads them). WP0 pins them, and that pin is never edited (L-12).
- **New CHANGE tests:**
  - `test_maker_binding_c_takes_max_over_s8`. At all three sites S8 enters the max: `binding_c`, the report binding role, and `finish_e2`'s `sensitivity_c`.
  - `test_persist_factor_redrawn_every_L_days`. The factor is shared within a block and redrawn across blocks. At `rho_p = 0` the critical distribution matches `persist=None` within 3 MC SE (distributional; factors use their own child stream).

## (g) WP3/WP4 inputs: S2 NO-GO, freeze_blocked, listing rate
- **New tests:** `test_binding_mode_refuses_s2_no_go` and `test_freeze_blocked_cell_is_unreachable`.
- **Listing rate.** S3 WP4 derives it; there is no S1 change before S1's 2026-10-14 run.
  - Binding mode takes `--s1-census PATH` (the S1 `censused_days.jsonl`, sha recorded) and computes `listing_rate_4stn` over LAX/MDW/MIA/SFO.
  - Rows with `reason == PRE_TRADE_CAPTURE` are excluded entirely.
  - **UNKNOWN** = NEVER_LISTED on a climate day where **no** station has `first_seen_ns` set. That is a recorder outage. It is excluded from the denominator and never counted as unlisted.
  - **UNLISTED** = NEVER_LISTED on a climate day where ≥ 1 sibling station has `first_seen_ns` set.
  - **LISTED** = every other reason. AMBIGUOUS_NO_CLEAN_INSTANCE counts as listed because a LIVE/CORRUPT instance exists.
  - `listing_rate_4stn` = LISTED / (LISTED + UNLISTED). `unknown_share` = UNKNOWN / (all non-PRE_TRADE rows).
  - **Refuse** if `listing_rate_4stn < 0.91` or `unknown_share > 0.20`. Otherwise the model keeps the pin 0.91 (conservative when measured is higher).
  - Tests: `test_binding_mode_refuses_listing_rate_below_pin` and `test_listing_rate_counts_recorder_outage_as_unknown`.
- §2 item 1 gains "S1 census jsonl (sha)". The §7 row "Listing 0.91" now reads "derived by S3 WP4 from S1 census jsonl".

## (h) Sweep EARLY STOP (WP4 step 2, §2 STOPs, §1)
- **r3 said:** "Context only."
- **r4 says (pinned in WP3):**
  1. **Trigger.** Every sweep cell (f ∈ {0.1..0.5} × b × k, β = 1, p₂ = 0.5) is `unreachable_veto`.
  2. **Confirm.** The six f = 0.5 cells are re-run once at 10,000 replicates with SEED and the pinned outer SE. All six must again be **`unreachable_veto`**. A `freeze_blocked` cell anywhere (sweep or confirm) **never** counts toward the early stop. It routes to a builder-defect fix, and the early stop is not taken.
  3. **Then** S3 issues UNREACHABLE — not registrable without waiting for S2.
     - The artifact carries `early_stop = "sweep_all_veto"` and `early_stop_basis = {f_max: 0.5, beta: 1.0, replicates: 10000}`.
     - STOP 2 consequences apply (no S4/S5, spec §8 row, PROGRESS line).
  4. **Reopen.** The early stop is terminal. It reopens only by a new dated ruling, and only if S2's **2×-rule point** exceeds 0.50. The 2×-rule point is the stressed fill rate `r_lo` defined at `docs/plans/backlog/MAKER_2026-10-12/S5_shadow_run_and_gates_plan_r3.md:27` (E1: 2 × (size ahead + 1), denominator = all covered bid-bearing station-days).
  - New STOP 5 `sweep_all_veto`. Test: `test_sweep_all_veto_triggers_early_stop_after_confirm_rerun`, which includes the freeze_blocked-blocks-early-stop case.

## (i) Text and number fixes
| Anchor | r3 said | r4 says | Why |
|---|---|---|---|
| §4.4 tick rule | "variance ≥ ~0.16" | per-leg BE(1−BE) ≈ 0.204 / 0.181 / 0.153 at b = 0.70 / 0.75 / 0.80; all ≫ `VARIANCE_EPS` | PMR |
| §4.1 BE and θ | "~0.012–0.014" | "0.013–0.017" ((0.0695 + 0.0125)·b(1−b)) | PMR |
| §4.1 / §5 | `errors.py:305` | `src/breezy/adapters/polymarket_us/errors.py:305` | precision |
| §4.1 new bullet "S4 exit floor" | (absent) | `exit_probability` floors at 0.10 even with `pool_exit_fraction = 0.0` (`rows.py:280-283`). The binding S4 row charges 10% of legs a uniform fraction of 0.02 + fee(b) (`draw.py:241-247`): ≈0.0017/leg, ≈0.004 σ/tick. It is a disclosed tightening. Test: `test_maker_s4_row_applies_exit_floor` (CHARACTERISATION; mutation: floor → 0) | PMR N3 |
| §5 table | No / Not usable / N/A | `PortfolioAnalyzer` (`nautilus_trader/analysis/analyzer.py:38`) **NATIVE EXISTS, DECLINED BECAUSE** it is descriptive-only. `infer_maker_rebate_rate` (`adapters/polymarket/fee_model.py:132`) **NATIVE EXISTS, DECLINED BECAUSE** rebates are refused by policy. Sequential loss-stop reach/power Monte Carlo: **GENUINE GAP (FQ tooling reused)**. Search: case-insensitive `grep -rE "sequential test\|sprt\|crossing\|monte ?carlo\|bootstrap\|false.?stop\|sqrt.?boundary"` over `.venv/lib/python3.13/site-packages/nautilus_trader/**/*.py` gives only unrelated hits (`live/reconciliation.py:627` position zero-crossings; `adapters/hyperliquid/data.py:444` cache bootstrap). Positive control: the same search for `drawdown` finds `TearsheetDrawdownChart` (`analysis/config.py:70`). Fill simulation: N/A (S2) | L-1 |
| §2 item 3 | "~0 days" | the ruling's 64 / ~0 statement, see (b) | ruling §2 |
| header, §11 | `reviews/S3-r2-final.md` | `docs/plans/backlog/MAKER_2026-10-12/reviews/S3-r2-final.md` | path hygiene |
| WP0 / WP4 runs | `systemd-run … MemoryMax, RuntimeMaxSec` | add `-p LimitNOFILE=524288`; run "outside the nightly-study window, the only heavy job" | host lessons |
| §6 focused gate | list | add `tests/unit/test_runtime_import_isolation.py`; in a worktree export `BREEZY_PYTHON=/home/jon/breezy/.venv/bin/python` for `scripts/ci/run_tests_no_egress.sh` | contract tests |

## (j) WP4 real-artifact check (new step 3a; L-24, L-42) and S5 coupling
- **Step 3a.** Before the binding run, binding mode runs once in `--inputs-only` mode against the **actual** inputs, not fixtures:
  - the S2 artifact;
  - the actual S1 `censused_days.jsonl`;
  - the actual committed S5 cap pin.
- That run prints every derived input with its sha: `listing_rate_4stn`, `unknown_share`, realised b median, `L_cap`, `r_lo`, and the S2 verdict. Its stdout goes in the artifact. Any refusal stops WP4.
- §8 guard row "Frozen stop ≠ certified stop" gains: "S5 freezes `frozen_c_deff` with σ·√1.5; `a1_stop` carries `certified_horizon_climate_days` and `certified_ticks` (`docs/plans/backlog/MAKER_2026-10-12/S5_shadow_run_and_gates_plan_r4_delta.md`)".

## (k) Consolidated test lists (names only)
**WP1** (`tests/unit/test_fq_loss_floor_mc_spec_pins.py`):
- CHANGE:
  - `test_run_floor_maker_spec_all_no_world_is_not_vetoed_by_empty_cells`
  - `test_floor_spec_rejects_noncanonical_mixes_and_missing_m_pool`
  - `test_floor_spec_rejects_duplicate_binding_row_labels_and_binding_outside_cal`
  - `test_persist_full_correlation_shares_station_factor_within_block`
  - `test_persist_factor_redrawn_every_L_days`
  - `test_persist_and_rho_together_are_refused`
  - `test_g1_all_lose_path_is_infeasible_for_exclusive_no_legs`
  - `test_maker_spec_g1_uses_worst_feasible_and_reports_all_lose`
  - `test_maker_binding_c_takes_max_over_s8`
- CHARACTERISATION:
  - `test_run_floor_default_and_explicit_fq_spec_hash_equal`
  - `test_persist_none_leaves_rng_stream_unchanged`
  - `test_fq_spec_document_has_no_floor_spec_key`
  - `test_m_pool_equals_m_no_on_all_no_templates`

**WP3** (`tests/unit/test_fq_loss_floor_mc_maker.py`):
- Path model:
  - `test_maker_be_is_bid_plus_theta_fee`
  - `test_maker_leg_pnl_win_is_one_minus_be_and_loss_is_minus_be`
  - `test_two_maker_legs_cannot_both_lose`
  - `test_h1_bernoulli_fallback_share_is_zero_on_maker_cells`
  - `test_maker_s4_row_applies_exit_floor` (CHARACTERISATION)
- Templates:
  - `test_template_listing_bid_bearing_and_fill_rates_match_parameters`
  - `test_template_fill_overdispersion_matches_pinned_design_effect`
  - `test_maker_templates_are_all_no_side`
  - `test_templates_refuse_bid_outside_b_floor_b_cap`
  - `test_fill_icc_below_ceiling_floor_is_refused`
- Rates:
  - `test_lambda_sd_equals_template_mean_station_days_per_date`
  - `test_r_sd_times_lambda_sd_equals_template_fills_per_date`
  - `test_maker_config_keep_probability_is_one`
  - `test_maker_tick_share_is_one`
- Pins and inputs:
  - `test_maker_config_pins_rho_hat_half_and_fq_window`
  - `test_other_freeze_is_refused`
  - `test_binding_run_pins_outer_resamples_and_replicates`
  - `test_binding_mode_refuses_missing_s2_field`
  - `test_binding_mode_refuses_s2_no_go`
  - `test_binding_mode_refuses_realised_bid_outside_floor_cap`
  - `test_binding_mode_refuses_listing_rate_below_pin`
  - `test_listing_rate_counts_recorder_outage_as_unknown`
  - `test_binding_mode_refuses_missing_s5_cap_pin`
- Horizon:
  - `test_horizon_sensitivity_cell_is_report_only_and_pinned`
  - `test_horizon_sensitivity_resimulates_to_l_cap`
- Deff:
  - `test_deff_variance_inflation_cancels_in_certified_stop` (tie-tolerant)
  - `test_artifact_records_c_and_c_deff`
- Window and frozen cell:
  - `test_artifact_records_window_label_and_certified_horizon`
  - `test_frozen_c_reevaluates_g1_g3_on_every_binding_cell`
- Verdict:
  - `test_verdict_reachable_underdetermined_unreachable`
  - `test_verdict_kill_reads_stressed_point_and_pass_reads_stressed_lower_bound`
  - `test_freeze_blocked_cell_is_unreachable`
  - `test_theta_008_cell_is_report_only`
  - `test_borderline_g3_triggers_one_pinned_rerun`
  - `test_sweep_all_veto_triggers_early_stop_after_confirm_rerun`

## Verdict
r4 = r3 + this delta (rev 2); READY. Round-2 items N-1..N-6 and the architect round-2 items are folded in (a), (c), (f), (g), (h), (i), (j).

## (k) S2 interface update (rev 3, 2026-10-14; from S2 r4 delta §(n), §(r); binding on the WP4 brief)
1. **Verdict allowlist.** WP4 binding mode admits `s3_inputs.json` `verdict` only by exact-string allowlist {"NOT-KILLED", "NOT-KILLED-UNSCREENED"}; `UNDERPOWERED-WAIT`, any `NO-GO (…)`, `STOP-S4-NO-BID-BEARING-DAYS`, missing or unknown → refuse. Test `test_binding_mode_refuses_any_label_outside_allowlist` supersedes `test_binding_mode_refuses_s2_no_go` (widen, never delete).
2. **k.** S2 emits only `max_rungs_hypothesis` (no `k` key). WP4 takes k from the MAX_RUNGS admission ruling if one exists, else brackets {2, 1} using the `_k1` keys for k = 1.
3. **f.** `f_kill` = `r_lo` (= `r_lo_station_day`, minimum over unit hypotheses), `f_pass` = `r_lo_lcb_cluster_boot`; for k = 1 `f_kill` = `r_lo_k1`, `f_pass` = `r_lo_k1_lcb_cluster_boot`. Any `r_lo*` key `null` → REFUSE (not 0).
4. **ICC.** WP4 reads only `fill_icc_rung_trial` (k = 1: `fill_icc_rung_trial_k1`). `null` → refuse. A value below `FILL_ICC` (0.5/7) is floored to `FILL_ICC` with the floor disclosed in the artifact; a value ≥ 3/7 maps to a station-day ICC ≥ 1 and `MakerMix` raises `MakerRefusal` — WP4 records `icc_out_of_range` and refuses the binding run (never clips). `fill_icc_station_day` is report-only.
5. **b.** `b` is the lower on-tick median of stressed-rule fills; outside [0.70, 0.80] or null → refuse (ruling O-4 unchanged).
6. **Provenance.** The artifact pins the S2 `s3_inputs.json` sha256, its `code_sha`, and the amendment FINAL sha it was produced under.
