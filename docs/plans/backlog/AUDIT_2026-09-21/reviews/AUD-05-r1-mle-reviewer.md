# AUD-05 review — round 1 — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-05-live-family-tally-unit.md
sha256: 7bd5f1ee6d9802a4a97b75668e52fe120fe694b9953e2e11c52566facc7356e1
Round: 1

## Claims verified
- `build_stratum_v2` raises `ValueError` "is side-blind and refuses any row with side != 'yes'" at `current_rung_hold_v2.py:419-420` — CONFIRMED verbatim.
- `family_tally_v2.py:666-671` raises `ValueError(f"filled_takes={filled_takes} is less than len(rows)={len(rows)}...")` — CONFIRMED verbatim, and `filter_rows_to_manifest_prefix` at `:532-564` — CONFIRMED verbatim (raises `FamilyStoreContaminationError` when a single-family store admits a foreign-prefix row).
- `count_filled_takes` (`fill_time_count.py:139-159`) keys on `(family_prefix, station, climate_day)` — i.e. one entry per station-day — CONFIRMED by reading the function; this is a materially different unit than `len(rows)` (one row per scored fill), supporting the plan's category-error diagnosis for D-B cause (i).
- `pm_us_crh_v4.json` and `pm_us_crh_cont.json` share `"trial_id_prefix": "continuous_rung_hold/trial/"` byte-for-byte — CONFIRMED. `d0_climate_day` differs (2026-09-20 vs 2026-09-12), `terminal_climate_day` exists only on `pm_us_crh_cont` ("2026-09-19"), `taker_fee_coefficient` differs (0.0695 vs 0.06). Both manifests currently carry `"status": "REGISTERED"` — CONFIRMED, consistent with the plan treating BLOCKER-1 as live and urgent.
- **Central statistical-validity question (task-specified challenge): does fixing D-A risk changing the registered statistic?** Read `docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` in full. It is REGISTERED 2026-09-14 and its §2-3 give the *exact* mixed-side statistic (`s_i`, `q_i`, `BE_i` per leg, the NO break-even reflection `p_miss_lower = 1 - P_HOLD_UPPER`, and the exact `Var_H0` extension for mixed-sign draws). **Finding: fixing D-A does NOT risk changing the registered statistic — it is closing the gap between an already-registered statistic and a placeholder refusal that predates its registration.** The plan's own framing ("per-leg terminal-state handling (L-44)... exactly as the NO-side PREREG amendment registers it") is directionally correct but under-cites: it does not pin the exact amendment §3 formula/sign convention into the RED test spec, leaving an implementer to independently re-derive it from the amendment doc rather than having it handed down as a test oracle.

## Defects

**MINOR — D-A's fix specification under-cites the registered formula it must implement.**
File: AUD-05-live-family-tally-unit.md §6 "D-A → make `build_stratum_v2` side-aware", §7 step 1
Issue: The registered NO-side statistic (`PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md` §2-3) already specifies the exact per-leg `q_i`, `BE_i`, sign `s_i` and the mixed-draw variance formula. The plan cites the amendment only at the narrative level and leaves the exact fields to be ported to the implementer's discovery, which is also how the plan's own self-score docks 4 points on implementation specificity.
Fix: Quote the amendment's exact §3 formula (or the specific line range) directly in §6/§7 step 1's RED test description, and make `test_a_no_leg_row_is_scored_not_refused` assert against the amendment's own worked numeric example if one exists, not just "is scored."

No MATERIAL defect found beyond what the plan itself already surfaces as BLOCKER-1/BLOCKER-2 (correctly deferred to strategy-lead ruling, not decided in-plan).

## Per-criterion points
- Fidelity to gap and completeness: 18/20
- Technical correctness and evidence grounding: 16/20 (docked slightly below the author's 17 for the under-citation above — a genuine, checkable evidence-grounding gap on the item's single highest-risk claim)
- Implementation specificity and feasibility: 11/15
- Acceptance criteria and validation quality: 17/20
- Autonomous operation, failure handling, recovery: 11/15
- Portfolio objective alignment, scope, dependencies: 5/10

**Total: 78/100**

## Required changes to reach 100
1. Pin the exact registered NO-side formula into the D-A RED test spec (above).
2. Author-named: specify one alert-wiring choice for the three-day-silent-failure autonomy gap instead of leaving two options.
3. Author-named: establish the single D-B root cause before coding rather than fixing both hypothesized causes.

## Blockers
- **BLOCKER-1 (strategy-lead / PREREG authority):** resolving the `pm_us_crh_v4` / `pm_us_crh_cont` `trial_id_prefix` collision (D-D) is a REGISTERED-family identity change and cannot be decided by this plan or this review.
- **BLOCKER-2 (same authority):** whether `pm_us_crh_cont` is retired now that `terminal_climate_day` is set.
Both are correctly named as blockers in the plan itself (§12), not silently resolved.
