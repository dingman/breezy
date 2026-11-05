# F5 pin request r3, errata E-2 (2026-10-08): the calibration rate (D5 amendment). Found AFTER the first full run; the outcome is unchanged

**Finding (domain peer review of `fq_loss_floor_mc_seed20261008.json`, first run at code 8e6482ee).**
- r3 §4.5 D5 calibrated c at `rate_cal = max(λ_pool, take_rate_lower)`. λ_pool is the take rate of the pool's synthetic model view at `DEFAULT_PI_FAV`, and it was 5.794 takes/day. That is about 23× the frozen `take_rate_lower` of 0.25. It is not a bound on the live FQ v2 rate.
- Calibrating at 5.794 sizes c over about 600 ticks for a stop that will see about 26. It gave c = 12.32, which makes the √t boundary unreachable by construction. That contradicts r3 §4.7: a frozen stop that cannot fire is not an option.
- The first run's recorded cause ("all-lose never crosses; G3 = 0 everywhere") is therefore an artefact.

**Ruling (coordinator, adopting the peer's E2 text).**

> D5-E2. `rate_cal` = `take_rate_lower` (0.25 takes/day), identical to `rate_gate`, whenever λ_pool > `take_rate_lower`. The max() rule applies only when λ_pool < `take_rate_lower`. The max(λ_pool, 0.25) calibration is reported as a NON-BINDING sensitivity row.

**Forking-path disclosure.** This rule was changed after one result had been seen. It is admissible only because it cannot change the freeze outcome. The peer reran seed 20261008 at 10,000 replicates with calibration at 0.25:
- c ≈ 2.05, which matches the r2/r3 planning estimate of 2.3–2.5;
- G1 passes at α 0.10 in every cell;
- G3(−0.16) is 0.579 for M-pool, 0.434 for M-no and **0.210 for M-yes**, below the floor 2.5 × 0.10 = 0.25, and below the floor at α 0.20 and 0.30 as well;
- under r3 §4.6 (no escalation on G3), the outcome is **`unreachable_veto`**, the same as the first run.

The errata only corrects the recorded cause, which is now: the G3 power floor fails in the M-yes mix. It also fills the c, power and S6 fields that the evidence reports.

**Housekeeping.**
- The `p_keep` cap warning is reworded "within bisection tolerance" when |raw − 1| ≤ the bisection tolerance; the shortfall of 0.248 against 0.25 is within tolerance.
- The binding evidence file is the E-2 rerun. The first run is kept as `…_seed20261008_run1_pre_E2.json` for the audit trail.
