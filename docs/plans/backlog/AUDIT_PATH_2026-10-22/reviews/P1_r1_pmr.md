# P1 r1 review — prediction-market-reviewer

**VERDICT: REQUEST-CHANGES.** The latency run is worth doing but should be much smaller. The adverse-selection test (G4) is the weakest part and should go.

I read the simulator at `/home/jon/breezy-maker-design/scripts/analysis/maker_stage0_fill_pass.py:222-242` and `:284-311`. I did not open the driver or the output files, so the plan's 17/20 and 8-fill claims are taken on trust.

**Required changes**

1. **Say what the latency model is and isn't.** Ignoring prints with `ts <= t0+L` (`:225`) is conservative on one side. The real queue ahead of us would be eaten by those prints, and the override keeps `ep.r` and `ep.g` too high, so we need more volume to fill. The plan's own risk 1 names the other side. New orders that arrive in (t0, t0+L] land ahead of us, and the t0 snapshot ignores them. The 2× stress factor (`:298`) covers that growth only loosely. The model also ignores the book moving during L. `_refusal` (`:272-282`) is checked only at t0, so an order that would be marketable or stale at t0+L is still treated as resting. Add a sentence saying the model is "conservative on consumption, unmodelled on queue growth and book drift". Don't call it realistic.
2. **Drop G4, the adverse-selection test.** It cannot give a meaningful PASS and it is biased toward FAIL. (a) Power: about 15 fills clustered into about 11 day sums, with a one-sided sign-flip at 0.05, has almost no power. The plan already says this in risk 3. The only informative outcome is a FAIL. (b) Mechanical bias: a fill is a BUYER-aggressor print at or through our level (`:225-233`), so YES mid is pushed up by construction. The unfilled rungs are conditioned on no such sweep, so they don't have this push. Δ is therefore biased adverse against the fills, and the test can reject for reasons unrelated to adverse selection. (c) Undefined controls: unfilled rungs have no `t_f`, and "same instants" is not defined. (d) Already observed: 17 of 17 fills won at settlement, and settlement is the real adverse-selection outcome. A 10-minute mid change is a weaker proxy than that. If any version is kept, it should be descriptive only (fills and mean Δ in cents) and never a gate.
3. **Make G2 and G3 honest or cut them.** With every in-sample fill a win, both gates are close to tautological. Ignoring prints can only remove or delay fills, so `mean_x > 0` holds whenever fills are at least 1. G3 can only trip if a delayed episode ends and re-posts into a different, losing rung. Fold G3 into a single check: "no new fill appears that wasn't in the L=0 set". G1 is the only gate with real discrimination. Keep it, and add the number of survivors out of 17 and out of the 4 fills under 10 s.
4. **Reduce the arms.** Control is not gated and P4 has dropped it, so `control_l1` and `control_l5` are pure cost. Run `sharp`, `sharp_l1` and `sharp_l5` only. Keep the G0 check at L=0 for sharp (17 fills, `sum_x` 1.96). It guards your driver edit. The control G0 can be dropped, or kept cheaply only if the run is already budgeted.
5. **Fix "any FAIL ends the maker programme".** The test is in-sample on the tape that selected sharp, and the plan says a PASS never claims an edge. A FAIL from G1 means the fills depend on sub-second queue-position luck, and that is a legitimate stop. A FAIL from a noisy G4 should not end the programme, so G4 should not gate at all.
6. **Reconcile step.** Steps 1 and 5 are one script, but the 17 vs 20 reconcile is already explained in the plan by `arm_stats` and `PositionFold`. A one-off `jq` or pandas check is enough. Don't ship `maker_p1_audit.py` and its test file.

**What a PASS or FAIL really tells us**

- A PASS says only that the in-sample fills aren't a sub-second feed-skew artefact. The 0.054 s fill already hints at one.
- A FAIL on G1 is a real warning.
- Neither result estimates edge, because the selection tape is the evaluation tape.
- P4 (live, up to 40 fills) is the only informative test. P1 should be a short pre-flight (about half a day, sharp only, one gate), not a day-long gated programme.

**Cut list**

- G4 and the whole adverse-selection pipeline: Depth10 reads, matched controls, sign-flip, and its test file.
- The control latency arms.
- The standalone audit script.
- The "wrap up" evidence note. Update the PROGRESS row only.

**Medium**

- State the seed and flip count for any retained descriptive statistic.
- `Arm.latency_ns` in the arm table must be covered by the arm-table pins.
- The effort estimate is fine, but it falls to about 4–5 h after the cuts.

**Confidence: 80.**