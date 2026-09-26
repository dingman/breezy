# AUD-07 M1c: per-depth eps_k switch (plan r1, 2026-09-26; PR-1..PR-4 UNDER PEER RULING)

## Trigger
Segment A (code-S 0369e12) CAL passed: cal_check `f_per_cell={0: 0.191, 15: 0.2115, 46: 0.2075}`. The glue then stopped on f > 0.10, citing EXEC-REV2 §5 :309: "If f > 10%: switch to a per-depth `eps_k` table in the pin, using the same validation rule per depth. A new pin requires a CAL-c re-run." The gate itself is coordinator glue (`~/.local/share/breezy/aud07_m1c/seg/seg_A_cal_then_20k.sh:106-115`, `F_GATE_MAX`). Note that the glue cites "amendment §5"; the correct reference is EXEC-REV2 §5.

## Facts
- **The census has no per-depth data.** It pools |Δb| across depths (`aud07_m1c_census.py:154-192`), so the switch needs a code change, a new sha S′, and a full CAL rerun (CAL-a, CAL-b, census, CAL-c).
- **EPS=0.6948 comes from same-side cells.** The census max is 0.2316 (cells 17 and 45), with 0.14–0.23 across same-side cells 16–46. Mixed cells 0–15 stay ≤0.0275, and control cell 48 is 0.0325.
- **One value recurs, which suggests a schedule-determined point.** 0.16852808884208237 appears in cells 21, 25, 29, 33, 37 and 41. That points to the terminal look or the t-cap point, not look-1 small-t. This is an inference.
- **f is performance-only.** The global pin is valid and conservative, so no gated statistic is at risk.

## Design, if the switch proceeds
- **Census.** Add per-depth max and p99.9 (eff/fut), a terminal bucket, and `derive_eps_pin` → `eps_by_depth`, `census_max_by_depth`, `eps_terminal`. Keep scalar `eps = max(eps_k)` for disclosure. Refuse ragged vectors.
- **Sim.** `EpsPin` gains optional `eps_by_depth` and `eps_terminal`. `load_eps_pin` applies floor + 3× per depth, and a legacy scalar pin still loads. `_needs_refine` uses the eps of each look's depth. The audit abort becomes per-depth. `M1cCellResult` gets a defaulted `eps_by_depth`.
- **Tests (RED first).**
  - Per-depth census and terminal bucket.
  - `derive eps_k = max(0.02, 3·max_k)`.
  - Test 28 extended.
  - `_needs_refine` flips only at the right depth.
  - Terminal looks use `eps_terminal`.
  - The per-depth audit fires.
  - Tests 17 and 21 rerun under eps_k.
  - Tests 1–16, 4a/4b and the M1b golden stay byte-unchanged.

## Run plan
1. Rename `runs/0369e1218a85/` to `.superseded-<utc>`; never delete it. It is M2 disclosure evidence.
2. Snapshot S′.
3. Smoke run: cells 0/16, 20 reps.
4. Diagnostic: per-depth census on cell 21 at ~20 reps (~1 min) to identify the depth that produces 0.1685.
5. Arm the seg-A glue at S′ for 09-27 02:10Z, with MemoryMax=6G and CUTOFF 08:40Z.

Wall-time estimate: CAL rerun ~6h, then 20k ~10–11h.

## For peer ruling
- **PR-1.** Index by look ordinal k, pooled across cells and across eff/fut, plus a separate `eps_terminal` bucket. Reason: the sim can stop early at i_max, but the census marks `is_terminal` only at N_MAX, so a per-depth table without a terminal bucket misses early terminal boundaries.
- **PR-2.** DT_MIN under eps_k: proposal is `min_k eps_k`, the tightest value (fail-closed).
- **PR-3.** If f is still >10% after eps_k, there is no pre-registered fallback. Proposal: pre-register NOW, before seeing any number, that the eps_k pin is terminal and 20k proceeds at whatever f results. The cost is compute only. Glue sets `F_GATE_MAX=1.0` under that ruling.
- **PR-4.** Alternative: override the gate and run 20k on the existing global pin.
  - Needs no code and no CAL rerun.
  - Costs ~121 CPU-h (~23h wall) at f≈0.21, vs ~6h CAL + ~11h 20k for eps_k if it reaches f≤5%.
  - The pre-registered text says "switch", so this alternative needs an amendment ruling.
  - The planner recommends following the switch.

## Schedule
- **Today:** no heavy AUD-07 work in 09:35–14:00Z (AUD-09b C2 window). Rulings, then TDD of S′.
- **Optional seg C:** 14:05–14:50Z CAL-b prefill, if S′ is merged.
- **09-27 A (02:10–08:40Z):** CAL rerun.
- **Then:** 20k.

## Risks
- HIGH: eps_k may not lower f if the large Δb sits at terminal or t-cap depth. Step 4 is the check.
- HIGH: missing the terminal bucket silently breaks premise P.
- MED: the CAL rerun wall time is ~2.5× the original plan.
