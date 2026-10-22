# P1 r2 verification — prediction-market-reviewer

**VERDICT: APPROVE-WITH-CHANGES.** All six r1 changes are addressed. Three small fixes remain.

**r1 changes 1–6**
1. Done. The latency wording (plan lines 14–17) matches the simulator. `_on_print` returns at `maker_stage0_fill_pass.py:225` before `r` and `g` are touched, and the refusal check runs only at attempt time (`:290`). The plan states the unmodelled queue growth and book drift.
2. Done. G4 is now a descriptive markout with no p-value. The mechanical bias, where a sweep print pushes YES mid up at the fill, is still there. Add one line saying the markout is biased adverse by construction, and don't compare it to X as if it measured selection. "Same-station" and "the filled rung's own Depth10" are defined well enough for a descriptive number.
3. Done. G2 and G3 are folded into G1. The "any fill at L=1 s not in the L=0 set" check is in step 5 but is not a gate. That is acceptable, because a new fill in the latency arm is mostly an anomaly signal.
4. Done. The arms are sharp-only.
5. Done. The FAIL/STOP asymmetry is fixed: G0 failure is a STOP, and only G1 ends the programme.
6. Done. The audit script and its test file are cut.

**Required fixes**
- **G1's "no settlement loser" clause is vacuous but harmless.** All 17 in-sample fills won, and latency can only remove fills or add a different fill. Keep it, but define the loser test as `win == False` on any base or stress fill at L=1 s, using the same truth join as `arm_stats`. A fill with `win is None` (no truth row) should be counted and reported, not silently treated as a non-loser.
- **G1 should compare the right counts.** State that `sharp_l1` must reach at least 10 stress-pass fills out of 17. Also name the survivors among the 4 sub-10 s fills. If all 4 die, 13 remain, which passes. That is fine, but write it down.
- **Pin the G0 pass criterion to the committed-HEAD artifact.** Specify that G0 compares the `sharp` arm's fills at the `(rung, day)` level against the old `positions.csv`, not just the count and `sum_x`. Equal counts can hide a different set. Also record `code_sha` in the new `summary.json` so the provenance is closed.

**Over-engineering check.** Nothing material remains. The `systemd-run` and stall-watch steps are proportionate to a 2 h job. The evidence note and the PROGRESS row are the minimum record.

**Confidence: 85.**