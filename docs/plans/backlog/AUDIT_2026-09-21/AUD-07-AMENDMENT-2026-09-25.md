# AUD-07 AMENDMENT 2026-09-25, Rev 2 (replaces Rev 1 in full)

**Status:** DRAFT amendment to `/home/jon/breezy/docs/plans/backlog/AUDIT_2026-09-21/AUD-07-exit-seam-arming-verification-path.md`. Nothing here arms, registers, enables or clears a halt. No operator-reserved control (max daily budget, max per position) is read, defaulted or touched. Any change to the statistic, the boundary artefact or the admitted population is a PREREG change: it needs a written, peer-reviewed ruling and is never made silently. Contradictions go to the peer loop, never to the operator.

**Headline:** Rev 2 adopts every requested change. There is one factual correction: `leg_of` never raises (details under disposition 7).

## Rev 2 dispositions

| # | Review item | Disposition |
|---|---|---|
| 1 | Branch V unreachable at `CP-upper ≤ α` | **Adopted.** §4 M2 sets a three-way gate per cell (δ = 3·SE_MC, anchored to the registered 09-14 gate α+3·SE = 0.02831), a rerun rule, and multiplicity handling. AC4 and DoD (ii) cite it. |
| 2 | Contradicts L-40 | **Adopted.** L-40 (`docs/core/LESSONS.md:1382`, header checked) says at `:1391` that "a multi-rung station-day never raises the information ceiling by itself", and at `:1394` "(`reference_table` interpolation or `boundary_for`), never a re-solve". New step M1a amends it through the lessons process (dedup first). M2 cites the amended text. |
| 3 | Don't re-implement the maths | **Adopted.** The streaming solver imports `_look_step` and `_one_sided_spend` from `src/breezy/persistence/gs_boundary_artefact.py:416,451`. Test 4 is split into 4a (exact, 1e-12) and 4b (reduced grid, 1e-3). |
| 4 | Sequencing | **Adopted.** Stage M runs in parallel with original steps 0–6 only. Steps 7 and 7b wait for M2. |
| 5 | Precondition | **Adopted.** AUD-06a merged (including caveat commit `21213d5`) and the full gate run after the merge (L-43, `:1424`); otherwise pin the import commit. |
| 6 | Refactor verification | **Adopted.** Golden output captured first, plus mutation evidence (L-33, `:1282`). Comparison is on objects. The tail moves into the extracted function; BCa stays in the caller; the disclosure line comes in a later commit. |
| 7 | Branch I details | **Adopted, with one correction.** `leg_of` → `leg_of_symbol` (`src/breezy/domain/instrument_leg.py:58-60`) is a pure suffix test that **never raises**. Anything without a `^no` suffix, malformed ids included, comes back `"yes"`. The exception that can actually fire is Nautilus `Symbol` validation inside `_leg_instrument_id` (`trial_day_latch.py:225-233`). Both points are handled in M3-I. The new reason is added to `LATCH_GATE_REFUSAL_REASONS` (`:203-205`). Only FILLED legs are counted. In-flight legs rely on the account-wide singleton `CURRENT_INTENT_KEY` (`src/breezy/runtime/submit_intent.py:37`), with a test. Fixtures go through the real writer (L-42, `:1410`). |
| NB | Ruling vs the 09-14 operator rulings; halt clear-condition; neutral sim inputs; compute unit; wider M0; recompute per-draw information; new test file | **All adopted** in §2.1, §3, §4, §5 and §8. The Rev 1 to-do "caveat RULING_r11 magnitudes" is dropped: done in `21213d5`, cited here. |

## 1. Original scope and what is still open

**Original scope (unchanged):** Rev 3 of `docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md`:
- **B/B2:** reconcile the step-0 drift and close the negative-median anomaly, row by row.
- **C1–C3:** bind the monitor report to a family, add the `UNBOUND` sentinel, and state the report's position universe against the ledger.
- **D:** `EXIT_CORPUS_FROZEN` on AUD-04's `alert_ladder`.
- Standing to-the-cent reconciliation with AUD-04 on `trial_id`.
- **A:** `pm_us_crh_exit_v4` package; stays `DRAFT_NOT_REGISTERED`, `exit_gate.py` byte-unchanged.
- **E/7b:** PREREG v4 DRAFT provenance plus the no-peeking attestation, anchored at `84d9042` (2026-09-16T03:36:32Z).
- **7c:** halt-state precondition for the positive control.

**Remaining:** all of it. Steps 0–9 and AC 1–9 are unstarted.

**Changed by AUD-06a:**
- DEP-3 (registration waits on AUD-06a) resolved as INDETERMINATE, so registration now waits on this amendment's DoD.
- Step 7 (minting shas) and step 7b (the boundary provenance row) wait on M2, because both touch `docs/specs/PREREG_v4_crh_exit_DRAFT_2026-09-16.md`.

**Framing corrections:**
- The mixed-side finding is 16/16 `mixed` q_max=1 cells over α. The "224/224" count is the q_max≥2 result, which belongs to AUD-06b. Its magnitudes are provisional per `21213d5`.
- Wilson drives only the `cell_dead` diagnostics.
- The sequential statistic is `S = ΣX_sd/√I` (`src/breezy/settlement/current_rung_hold_v2.py:348`), tested against LD-OBF boundaries solved at the realised `t_history` (`gs_boundary_artefact.py:183`).
- Looks happen every 10 station-day draws (`scripts/analysis/family_tally_v2.py:694-710`).

## 2. The mixed-side boundary question

### 2.1 The measurements do not replay the live rule (both claims confirmed by the prediction-market reviewer)

| | Live tally (`family_tally_v2.py:711-819`) | AUD-06a sweep (`aud06a_qty_envelope_sweep.py:429-454`) and strict-xfail harness (`test_multi_position_validation_2026_09_14.py:104-140`) |
|---|---|---|
| Boundary | Re-solved over the realised `t_history` | Interpolated from the 16-row regression-only `reference_table` |
| When I ≥ I_max | Terminal look: spends the remaining α, then `break` | No stop. `t` stays at 1 and later looks re-test at `b_eff(1)` |

So both the ~0.053 mixed-cell rates and the xfail's ~0.059 are unverified against the live rule.

**Per-draw information, recomputed with q = 1−BE for NO legs:**
- A mixed pair has `Var = S − (q_y − q_n)²` with `S = q_y + q_n ≤ 1`. The maximum is 1.0.
- The sweep sets fee=0, so BE = ask. Examples at observed asks:
  - YES 0.12 with NO 0.22 → q = (0.12, 0.78) → Var 0.464.
  - Equal asks a → Var = 4a(1−a); at a=0.22 that is 0.686.
- The ruling's own Δt gives the realised mean. For draws with mean information v per draw, the maximum of `t_real − n/160` is reached at the cap: `1 − 1/(4v)`. So:

| Cell | Recorded max\|Δt\| | Implied v (per draw) | Cap reached at | Extra looks at `b_eff(1)` |
|---|---|---|---|---|
| mixed, k=2 | 0.5 | 0.50 | draw 80 (look 8) | 8 |
| mixed, k=3 | 0.625 | 0.667 | draw 60 | 10 |
| all_yes, k=1 control | −0.365 (at n=160: 4v−1) | 0.159 | never; information below schedule, rate 0.0089 | 0 |

The variance itself is exact: `combine_station_day:337-344` is the true `Var_H0` under mutual exclusivity. Option (c) therefore has nothing to correct.

### 2.2 Options

| Option | Trade-offs | Disposition |
|---|---|---|
| (a) Partition: count one side only | Drops scored capital, which breaks the AUD-04 `trial_id` reconciliation. Choosing the side is a forking path and conditions on selection. Starves NO-side evidence. | Reject |
| (b) Simulation-calibrated critical values | Keeps every draw. But it is a PREREG change (new artefact and sha, a ruling), depends on a thin BE prior (n=9), and is compute-heavy. | Follow-up item, only if branch I |
| (c) Variance-corrected statistic | The variance is already exact. A "correction" would make Var_H0(S) ≠ 1. | Reject as framed |
| (d) Block mixed-side station-days by code | Cheap and reversible, one seam (`station_day_admission`, `trial_day_latch.py:1488`). Statistic unchanged. It restricts **which side** a station-day may add, not **how many** positions. | Containment, if branch I |

**Branch I does not conflict with the 09-14 operator rulings:**
- Multi-position per station is untouched: a station-day can still carry k rungs of one side.
- NO-hunting is untouched: all-NO days stay tradeable.
- Any conflict a reviewer raises goes to the peer loop, never to the operator.

**Recommendation:** M1, then the M2 gate. **V** → no statistic change. **I** → (d) plus a ruling, then (b) as a separately ruled item.

## 3. Current exposure: is any verdict at risk?

- **No LD-OBF verdict can have fired.** `pm_us_crh_v4` is HALTED (A1 (ii), sender-global), the durable census is 9 fills (at most 9 draws), and the first look is at 10 draws. The verdict is `CONTINUE` by construction.
- **The KILL clock is unaffected.** `structural_dead` (`family_tally_v2.py:685-707`) and LOSS_STOP never read the boundary.
- **Pending verification:** my Glob of `~/.local/share/breezy/derived` returned nothing, which may be tool blindness under dot-directories. M0 reads the artefacts with `/usr/bin/ls` and `/usr/bin/grep`, with a positive control.
- **M0 scope:** every REGISTERED family whose tally ran through `family_tally_v2` (the `breezy-family-tally@` wrapper) and ever held a NO leg — not only v4. The list is enumerated from `deploy/families/`, never assumed.

## 4. Build steps

**Preconditions:**
- AUD-06a merged, including `21213d5`, then the full `scripts/ci/run_tests_no_egress.sh` gate on the integration branch (L-43).
- Otherwise, pin the exact AUD-06a commit that `sample_station_day` is imported from, and record it in M2.

**Sequencing:**
- M0–M2 run in parallel with original steps 0–6.
- Original steps 7 and 7b start only after M2.
- Nothing is cited until it passes on the integration branch.

**M0: read-only exposure census.** `docs/evidence/AUD07_MIXED_SIDE_EXPOSURE_2026-09-__.md` records, for each family in scope:
- latest tally artefact: n draws, looks fired, verdict (verbatim lines);
- count of mixed-side station-days, via `stratum_row_from_scored_trial`;
- halt state.

**M1a: amend L-40** through the lessons skill, deduplicating against L-40, L-41 and L-43 first. Additive text:
- (i) The qty≡1 ceiling `S(1−S) ≤ 1/4` holds for **same-side days only**. A mixed YES+NO day has `Var = S − (q_y−q_n)²`, up to 1.0.
- (ii) Validation must replay the live look loop, **including the terminal stop at I ≥ I_max**.
- (iii) A streaming evaluation of `boundary_for`'s own recursion is allowed when proven equal to `boundary_for` (test 4a). That is not a re-solve of the artefact.

M1a lands before any M1 number is cited.

**M1b: refactor the live tally, verified by characterisation (L-33).**
1. **Before touching code, capture the golden** in `tests/unit/test_family_tally_v2_look_loop_golden.py`: `LookRecord`/verdict/`bca_line` **objects**, not report bytes. Scenarios:
   - I_max terminal on mixed-side rows;
   - LOSS_STOP;
   - forced truncation on-grid;
   - the off-grid truncation tail (`:784-819`);
   - structural KILL (`:706-708`);
   - a plain CONTINUE run.
   Rows go through `score_live_trials` writer fixtures where a store is read (L-42).
2. **Extract** `run_sequential_looks(combined_draws, *, artefact, boundary_fn, total_pnl, residual, cell_dead, structural_fired, registered, truncation) -> (looks, verdict, decided: bool)`. It includes the off-grid tail. `_roi_bound_line_v2`/`bca_line` stay in `build_family_tally_v2`, computed when `decided` is true. Production passes `artefact.boundary_for`.
3. **Mutation evidence** recorded in the commit message: remove `reached_i_max` → the golden goes red; remove the tail → red.
4. The disclosure line (DoD iv) lands in a **later** commit.

**M1c: harness.** New script `scripts/analysis/aud07_live_rule_crossing_sim.py`:
- **Reuses:** AUD-06a `sample_station_day` (with its NO-`held` fix), `combine_station_day`, `run_sequential_looks`.
- **Streaming `boundary_fn`:** a per-replicate object that imports `_look_step` and `_one_sided_spend` from `breezy.persistence.gs_boundary_artefact` and carries `(grid, dens, prev_t)`.
  - Non-terminal target: `spend(t) − spend(prev_t)`, the same subtraction `_iter_boundary_looks` does (`:513-526`).
  - Terminal target: `α − spend(prev_t)`, via a second `_look_step` from the **same prior state**.
  - Ties go through `_look_step`'s own `dt == 0` branch.
  - It asserts each call extends the previous history by exactly one element.
- **Neutral inputs (L-41):**
  - `total_pnl = residual = 0`, so LOSS_STOP never fires;
  - `cell_dead = False`, `structural_fired = False`, `truncation = None`;
  - counts **efficacy crossings only** (the `S ≥ b_eff` verdict literal, pinned by test);
  - reports mean(S_terminal) ≈ 0 and per-look Var(S) ∈ [0.95, 1.05].
- **Grid:** 16 mixed q=1 cells; matched all_yes/all_no q=1 cells in the same strata; the all_yes k=1 control.
- **Reps:** 20000 per cell at reduced `npts`. First measure τ_cell on one calibration cell and record the projected total.
- **Spot check:** one mixed cell at full `npts=2001` × 2000 reps, budget about 1 h.
- **Runtime:**
  - command: `systemd-run --user --unit=aud07-sim -p MemoryMax=6G -p MemorySwapMax=0 …`, a service so it survives SSH;
  - output: chunked `--cells FROM:TO` to JSONL, per-cell seeds;
  - timing: never overlapping the 15:20Z study or the nightly studies; one heavy job at a time, never touching the node.

**M2: decision artefact** `docs/evidence/RULING_aud07_mixed_side_ldobf_2026-09-__.md`. It is peer-reviewed by prediction-market-reviewer and architect, cites amended L-40 and `21213d5`, and puts both harnesses' rates side by side. The gate below is stated in advance and never re-read.

**Per-cell gate** (α = 0.025, SE_MC(α, 20k) = 0.001104, δ = 3·SE = 0.0033):

| Result | Condition |
|---|---|
| **I** | Clopper-Pearson lower bound at confidence 1 − 0.05/16 (Bonferroni over the 16 mixed cells) > α |
| **V** | CP-upper (one-sided 95%) ≤ α + δ = 0.0283. Same threshold as the registered `PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md:154` gate, and stricter than the 0.035 slack in the existing xfail. |
| **INDETERMINATE** | Anything else. Rerun that cell once at 80000 reps with fresh seeds (SE ≈ 0.00055, so a calibrated cell has CP-upper ≈ 0.026, which is reachable), then re-apply the gate. Still INDETERMINATE → counted as **I** (fail-closed; containment only costs trades). |

**Multiplicity across the 16 cells:**
- Branch **V** requires **every** mixed cell to be V. Requiring all 16 is conservative against a false V.
- Branch **I** fires if **any** cell is I. The Bonferroni correction keeps a spurious I near ≤ 5% family-wise when the true rate is exactly α.
- Disclosed tolerance: a true rate up to about α+δ can be classified V.

**M3-V (branch V):**
- New file `tests/unit/test_aud07_mixed_side_ldobf_live_rule.py` (tests 5, 7 and 9 below).
- In `test_multi_position_validation_2026_09_14.py`, **docstring only**: the static guard at `:224` covers same-side days. The strict xfail stays byte-unchanged.
- Tally line: `terminal at I_max below n_max: n=…`.
- Additive addendum on `RULING_r11_qty_envelope_2026-09-25.md`.
- Re-running AUD-06b's q≥2 cells is the coordinator's call, not AUD-07's.

**M3-I (branch I):**
- **Ruling first:** narrows the population registered in the v3 amendment; shows no conflict with the 09-14 rulings.
- **Add `MIXED_SIDE_STATION_DAY_REASON`** to `LATCH_GATE_REFUSAL_REASONS`.
- **Change `station_day_admission`:** for each existing **FILLED** record (`_FILLED_REASONS`), resolve its side. Refuse if any filled side ≠ `candidate_side`.
- **Side resolution:**
  - wrap `_leg_instrument_id(_bare_symbol(...))` and `leg_of` in `try/except ValueError` → `Refusal(STATION_DAY_ADMISSION_REASON)`, following the existing "unknown q refuses" rule;
  - because `leg_of` silently returns `"yes"` on anything without `^no`, cross-check the bare symbol with `base_symbol_of`/`assert_valid_slug`, and refuse on an invalid slug.
- **In-flight opposite legs** are covered by the account-wide singleton submit intent: `arm` is refused while an intent is OPEN.
- **Tally:** flags mixed days; a look over m > 0 mixed days marks `MIXED_SIDE_UNVALIDATED`.
- No manifest key is added (the key set is closed, `family_manifest.py:109,123`).
- Open item (b) with its own ruling.

**M4:** after each merge, run `scripts/ci/run_tests_no_egress.sh`, then `lint-imports`, with `PYTHONPATH` set in a worktree.

## 5. Tests

M1b is characterisation, not RED (L-33). Everything else is written RED-first.

1. `test_look_loop_golden_objects_are_unchanged_by_extraction`, plus the M1b mutation evidence.
2. `test_the_sim_stops_at_the_first_look_where_information_reaches_i_max`: fails against the AUD-06a loop.
3. `test_the_sim_terminal_look_spends_exactly_the_remaining_alpha`.
4. Streaming solver:
   - 4a. `test_streaming_boundary_at_npts_2001_equals_boundary_for_to_1e_12` on 50 random histories, including terminal looks and tied t.
   - 4b. `test_reduced_npts_streaming_boundary_is_within_1e_3_of_boundary_for`.
5. `test_a_mixed_side_qty1_station_day_can_carry_variance_above_one_quarter` (q_y = q_n = 0.5 → 1.0).
6. `test_the_sim_null_has_mean_s_near_zero_and_unit_var_s_on_mixed_days` (L-41).
7. `test_the_all_yes_qty1_control_passes_the_m2_gate_under_the_live_rule` (harness positive control).
8. `test_the_sim_counts_only_efficacy_crossings_and_loss_stop_never_fires`.
9. `test_the_tally_report_discloses_mixed_day_count_and_i_max_terminal_below_n_max` (later commit).

Branch I only (fixtures through the strategy's real fill/TRIAL writer, L-42):

10. `test_admission_refuses_a_no_candidate_when_a_filled_yes_leg_exists`, plus the mirror case.
11. `test_admission_still_admits_multi_rung_all_no_and_all_yes_days`.
12. `test_an_unparseable_or_invalid_slug_existing_record_refuses`.
13. `test_an_unfilled_opposite_record_does_not_block`.
14. `test_an_in_flight_opposite_leg_is_blocked_by_the_open_submit_intent_singleton`.
15. `test_the_new_reason_is_a_member_of_latch_gate_refusal_reasons`.
16. `test_a_look_over_a_mixed_day_marks_mixed_side_unvalidated`.

## 6. Acceptance criteria

1. M0 is published with verbatim lines for every in-scope family (expected: no look fired anywhere).
2. The golden and the mutation evidence are recorded. Tests 4a and 4b pass. The harness calls `run_sequential_looks`.
3. Every cell's rate and CP bounds are reported under **both** harnesses. None is omitted.
4. M2 applies the §4 gate exactly as written (δ, Bonferroni, 80k rerun, fail-closed), with peer sign-off.
5. The amended L-40 is merged, deduplicated, and cited by M2.
6. `inputs_sha256 = 471fd8a7…` is unchanged unless a ruling changes it.
7. Branch I: tests 10–16 green; the ruling record exists before the merge.
8. At merge: no order placed, no family registered, no halt cleared, `exit_gate.py` diff empty, strict xfail unchanged, no operator-reserved value touched.

## 7. Risks

- **The refactor changes live verdicts.** Mitigated by the object golden, mutation evidence, and the full gate after the merge. Rollback is a revert.
- **Reduced-grid error.** Mitigated by 4b plus the npts=2001 spot check. If the spot check disagrees with the reduced run, the whole grid is re-run at the full grid.
- **Normal-tail error at early looks** with few skewed draws. M1 reports rates per look.
- **Thin BE prior (n=9).** The verdict is conditional on the recorded support; AUD-06a's `envelope_is_stale` predicate is reused.
- **Shared-host compute.** Handled by the capped service unit, quiet windows, and resumable JSONL.
- **`leg_of` quietly returns "yes"** (branch I). Handled by the slug cross-check (test 12).

## 8. Definition of Done

AUD-07 is DONE only when all of these hold:

- **(i)** Original AC 1–9 are met. Steps 7 and 7b cite M2.
- **(ii)** Exactly one of:
  - **(V)** Every mixed q=1 cell passes the §4 M2 V-gate under the harness that runs the live rule. The statistic is valid for the admitted population, recorded as an addendum. No PREREG change.
  - **(I)** `station_day_admission` blocks mixed-side station-days by code, the tally flags historical mixed days, the population narrowing is recorded in a ruling, and item (b) is open.
- **(iii)** L-40 is amended.
- **(iv)** The disclosure line is live in the v4 tally.
- **(v)** Gate, `lint-imports` and test evidence are attached.
- **(vi)** A named clear-condition, **`C-AUD07-MIXED-SIDE`** ("DoD (ii) satisfied, citing the M2 ruling"), is added to the A1 ruling's halt-clear evidence checklist (AUD-02 clear → act → re-set). It is an evidence item, not a CLI check. No halt for a family that can open both sides clears without it.

## Confidence

| Claim | Confidence | Basis |
|---|---|---|
| Both harnesses diverge from the live rule | **HIGH** | Confirmed at file:line by the reviewer |
| Mixed days exceed 0.25 per draw; implied mean information 0.50 and 0.67 | **HIGH** | Algebra plus the ruling's recorded Δt |
| The live rule is calibrated on mixed days (branch V) | **MEDIUM (~65%)** | Unmeasured; M1 decides |
| The M2 gate makes V reachable and resists spurious I | **MEDIUM-HIGH** | Needs the 80k rerun for borderline cells; δ is a disclosed tolerance |
| No verdict at risk today | **HIGH** for the logic | M0 read still pending |
| `leg_of` never raises | **HIGH** | `instrument_leg.py:58-60` |
| Plan executable within budget | **MEDIUM** | Streaming τ_cell not yet measured |

Key files:
- `/home/jon/breezy/scripts/analysis/family_tally_v2.py`
- `/home/jon/breezy/src/breezy/persistence/gs_boundary_artefact.py`
- `/home/jon/breezy/src/breezy/settlement/current_rung_hold_v2.py`
- `/home/jon/breezy/src/breezy/strategy/current_rung_hold/trial_day_latch.py`
- `/home/jon/breezy/src/breezy/domain/instrument_leg.py`
- `/home/jon/breezy/src/breezy/runtime/submit_intent.py`
- `/home/jon/breezy/docs/core/LESSONS.md` (L-33, L-40–L-43)
- `/home/jon/breezy/tests/unit/test_multi_position_validation_2026_09_14.py`
- `/home/jon/breezy-a06a/scripts/analysis/aud06a_qty_envelope_sweep.py`
- `/home/jon/breezy-a06a/docs/evidence/RULING_r11_qty_envelope_2026-09-25.md`

## Rev 2.1 (coordinator, 2026-09-25) — binding corrections; amendment APPROVED

Round 2: architect APPROVE (with A/B wording fixes), prediction-market-reviewer APPROVE (gate power ≈1.0 against a 2× inflation; δ verified as the registered 09-14 gate; per-draw recompute exact). These override the text above where they conflict.

- **A. Rerun arithmetic (pinned before any number):** at 80k reps δ stays FIXED at 0.0033 (V threshold 0.0283); the 80k result REPLACES the 20k result for that cell (never pooled); the I test keeps the Bonferroni level 1 − 0.05/16; both Clopper-Pearson bounds are one-sided.
- **B. No unmerged imports:** the "otherwise pin the AUD-06a commit" fallback is DELETED. Stage M imports `sample_station_day` only from the integration branch after AUD-06a has merged and the full gate has passed there (L-43).
- **Compute projection** includes expected reruns (≈78% chance at least one cell needs 80k reps at 4× cost).
- **Test 12** includes a legacy `~no` symbol (tilde-breaks-catalog memory) and asserts it refuses if `assert_valid_slug` rejects `~`.
- **DoD (vi)** edits the endorsed A1 ruling as an ADDITIVE checklist row only; no existing text changes.
