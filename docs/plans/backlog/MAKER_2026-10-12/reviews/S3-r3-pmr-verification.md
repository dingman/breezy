# S3 r3 verification + window-ruling review (prediction-market-reviewer, 2026-10-13)

Inputs read: S3 plan r3, reviews/S3-r2-final.md, RULING_MAKER-S3_loss_stop_window_2026-10-13.md (DRAFT), spec v0.3 s4, S5 plan r3 :19/:202/:221/:228/:235/:285, FQ engine (rows/draw/gate/engine/sim).

## PART 1 - R1..R5 disposition
| R | Status | r3 evidence |
|---|---|---|
| R1 kill anchor | RESOLVED | s1 table + s4.5: f_kill = 2x-rule POINT, f_pass = 2x 95% LB; UNDERDETERMINED = pass at point / fail at LB; test `test_verdict_kill_reads_stressed_point_and_pass_reads_stressed_lower_bound`; s8 row. Logic is coherent: failing at f_kill implies failing at f_pass (lower f = fewer ticks = harder G1). |
| R2 deff 1.5 | RESOLVED (with caveats N1, N5) | s4.4: z=x/sigma, carry in x units, crossing event {S<-c sqrt t} invariant under (sigma*sqrt1.5, c/sqrt1.5). I re-derived the algebra: correct. G1 (`repeated_crossing`, `fully_lost_fraction=c/(|z|sqrtT)`) is ratio-invariant: correct. Grid rounding caveat (smallest_grid_c, GRID_STEP 0.01) correctly handled by solving unit-variance and recording c_deff in float. |
| R3 stale text | RESOLVED | header v0.3; LD-OBF branch, NOT-APPLICABLE verdict, sub-0.70 cells removed; one B_FLOOR/B_CAP refusal test kept. |
| R4 theta 0.08 / look order | RESOLVED | s4.5 report cells; s4.1 "Look order" (climate-date order = settlement order up to same-date ties; true: all D+1 08:00 ET). |
| R5 FILL_ICC | RESOLVED | s4.1 `max(S2 ICC, 0.5/7)`; MakerMix refuses < 0.5/7. |

## Known-fact checks
- g1_unreachable on M-yes (not g3_floor): plan s3.1 is right (empty M-yes cell -> t_cross None -> g1_holds False -> select_alpha veto before G3). The framing "construction, not evidence" is correct. The all-NO world check is a characterisation test, fine.
- `exit_probability` floors at 0.10 (rows.py:280-283); engine.py:153 passes it to every sim; draw.py:243 applies it on the S4 row only. So WP3's `pool_exit_fraction=0.0` does NOT mean no exits: the binding S4 row charges, on 10% of legs, uniform-fraction x (KAPPA_FLOOR 0.02 + fee(b)) (half_spread None -> kappa floor). Mean shift ~0.0017/leg at b=0.70 (~0.004 sigma/tick): immaterial to c and strictly tightening, so NOT blocking, but the plan never discloses it and the maker is hold-to-settlement. Fix: one sentence + one test pinning "S4 charges the 10% floor exit cost; maker cells inherit it as a disclosed tightening", and print c with S4 excluded as context.
- Variance: plan s4.4 says maker legs have variance >= ~0.16. Wrong: per-leg BE(1-BE) at b=0.80, theta 0.0695 = 0.1532 (0.2039 at 0.70, 0.1808 at 0.75). Irrelevant to the 1e-12 VARIANCE_EPS argument; fix the number.
- Fee: plan says taker theta overstates BE by "~0.012-0.014". (0.0695+0.0125)*b(1-b) = 0.0172 / 0.0154 / 0.0131 at b = 0.70/0.75/0.80. Correct to 0.013-0.017. Direction (stricter null, cost basis consistent with S5's deterministic shadow fee) is fine.
- Two-leg exclusivity: correct. At most one of two distinct-rung NO legs loses; H1(-0.16) masses sum 0.70-0.89 < 1 for b in [0.70,0.80], so the categorical path holds and Bernoulli fallback share is 0 (tested). Station-day variance is below 2x leg variance (negative covariance); no problem.
- maker_be / leg PnL: `BE=b+theta*b*(1-b)`, win 1-BE, loss -BE, unresolved = LOSS: consistent with spec s6.5 and x_piece.
- G1 worst_feasible: min over len(legs)+1 outcomes crosses later than all_lose, so stricter: correct.

## New / residual issues
- N1 [BLOCKING, plan s1/s4.4/WP4 step 4] Which c is "the certified object"? The sweep solves a separate c per binding cell (k x b x f_pass/f_kill; c depends on tick count via max over t<=T of -S_t/sqrt t, and on the per-day z distribution). S5 freezes ONE (c, t_min, alpha). The plan records "alpha_star, t_min, c" singular and never says which cell. Frozen c from a cell with fewer ticks can fail G1/G3 in another. Fix (pin before binding run): frozen pair = the maximum c over binding cells at f_kill (or, equivalently, the cell nearest S2's realised (k,b,f-point)), AND the artifact re-evaluates G1/G3 for every binding cell at that frozen c (must still be sqrt_boundary / G3 >= 2.5*alpha). Add test `test_frozen_c_reevaluated_on_all_binding_cells`. Also state that alpha_star frozen is the one paired with that c.
- N2 [MEDIUM, s4.4 test (iii)] Crossing-indicator equality under an irrational 1/sqrt1.5 rescale is exact only up to fp ties; assert equality except where |S_t + c sqrt t|/sqrt t < 1e-9 (count such ties, expect ~0).
- N3 [LOW] S4-exit disclosure (above).
- N4 [LOW] Cross-doc: S5 G8 (:202) says "A1 reachability PASS"; S3 verdict vocabulary is REACHABLE/UNDERDETERMINED/UNREACHABLE. Align wording so G8 cannot be satisfied by UNDERDETERMINED. S5 :221 says `(c, t_min, alpha_floor)` -> should name `c_deff` per the ruling.
- N5 [LOW] The deff cancellation means "variance carries the 1.5 inflation" gives no extra protection by itself; plan already says so (s4.4 last paragraph). Keep that sentence in the artifact and in the PREREG, so no reader credits the stop with cluster robustness beyond S5-copula/S8/ICC rows.
- N6 [LOW] Open Q4 (k cells): default "all bind" is right; no change.

## Scores (1-10)
1 correctness vs acceptance criteria: 7 (R1/R2 correct; N1 leaves the acceptance object under-specified)
2 architecture fit with FQ engine at HEAD: 8 (FloorSpec, aliases, hash pins; M-pool equivalence verified in rows.apply_mix)
3 test coverage: 8 (good happy/failure/edge; add N1 and N2 tests)
4 risk mitigation: 8
5 scope minimality: 8 (WP2 cut, no knob for deff, no epoch code)
6 feasibility: 7 (open: N1; S2/window inputs not produced; run cost UNVERIFIED; S4 floor disclosure)
Overall: MEDIUM. All five r2 findings resolved; one new blocking pin (N1), a few one-line fixes. After N1 it would score HIGH without re-architecture.

## PART 2 - Window ruling (Option A)
Verdict: SOUND-WITH-CAVEATS. Option A is the right call; the draft's wording has one unit error and two under-specified obligations.

Why A is right: an absolute window that ends 2027-01-25 leaves a disarmed stop (the S5 table puts reads 83-412 days after an assumed 2026-11-23 start; Option B window ~64 days). A stop that disarms is worse than an uncertified tail. Ground 1 (engine not runnable for other freezes) is convenience, not merit; ground 2 carries the ruling. State that.

C1 [BLOCKING for ruling] Unit error. The engine's n_cal = inclusive_days(freeze, horizon) = 110 CALENDAR days (engine.py:231; gate.t_low_count = floor(n_days * lambda_sd * ...)). Ticks in that window = 110 * lambda_sd: with S5's own table (0.69-3.64 station-days/day) that is ~76-400 ticks, not 110. "110 ticking station-days", "counted from the first scored station-day" and PREREG field `certified_horizon_station_days: 110` are all wrong, and "83-412 days" vs "110" compares different units. Fix: window = 110 climate-days from the first scored climate day; field `certified_horizon_climate_days: 110` plus `certified_ticks_expected` (T_low at epoch 0 from the artifact) so the tail is defined in ticks too. Also say how epoch offsets {0,24,38,54} map (start-slip sensitivity), since the relative start is the first scored day.

C2 [(a) answered] "A false stop is the conservative direction": correct for capital (live and shadow: a stop only withdraws risk), WRONG as a blanket statement for the programme. S5 :19 makes an A1 stop a terminal artifact (`S5_A1_STOP`, no PROPOSAL). A tail false stop therefore destroys a possibly-good family's read: it is a power/attrition cost the day-60 power_projection does not model. I simulated the iid case (c solved on T0 ticks at t_min 10, false-stop rate over T1): T0=76->T1=284: alpha 0.10 -> 0.147, 0.20 -> 0.28, 0.30 -> 0.40; T0=76->T1=150: 0.124/0.243/0.355. Under S5/S8 dependence higher. So at alpha_floor 0.30 roughly 40% of null-true runs halt in a 412-day run. For a later LIVE family: capital-conservative, but a stop that kills a profitable family on noise forfeits ROI and the stop is the only loss control, so the false-stop rate must be known, not assumed benign. Required text: replace "conservative" with "capital-conservative; costs power"; have S3 print false-stop rate at the S5 planned cap horizon (see C3) and have S5's power projection discount by it; state that a tail STOP ends the experiment as STOP (not FAIL, not refutation), consistent with S5 :19.

C3 [(c) O-1/O-2 vs "zero planned revisions"] No real conflict: spec s6.3 zero revisions bind post-freeze; S3 runs pre-freeze; O-1 is a frozen field, not a revision. But O-2's "MAY add one sensitivity cell" is discretionary after pins are committed (S3 s2 item 4: post-result changes void) = forking-path risk, and circular (S3 binding precedes the PREREG freeze that fixes run length). Fix: make it mandatory and pinned now: one `horizon_sensitivity` report cell at the S5 calendar cap horizon (use the 412-day / cap figure from S5 s8, converted by lambda_sd), committed with the WP3 pins before the binding run. Report only; never binding.

C4 [(b) O-3] c_deff = c/sqrt(1.5) is the right algebra: S' = S/sqrt1.5 < -c' sqrt t <=> S < -(c' sqrt1.5) sqrt t <=> c' = c/sqrt1.5. The warning that unit c with inflated sigma is a different, LESS sensitive stop (threshold c*sqrt1.5 in x units) is correct. Caveats: needs N1 (which c); freeze the float at full precision, not the 0.01 grid; and S5's `test_a1_stop_uses_s3_parameters_and_deff_inflated_sigma` must assert the artifact key `c_deff` and an equivalence check, as it already plans. Since the rescale cancels, nothing is lost if S5 freezes (sigma, c) instead; allow the PREREG checker to accept either only if it verifies the pair equivalence.

C5 [(d) what S5 still cannot write] (i) the frozen c/t_min/alpha cell (N1); (ii) the window unit (C1); (iii) post-STOP semantics are partly in S5 :19 but not in the ruling: state STOP = terminal, no restart, resting orders cancelled (spec s3 cancel-on-stop), and that S5 treats it as neither FAIL nor refutation; (iv) the horizon_sensitivity value (C3); (v) O-4 is sound and writable (`ra13_review_note`, advisory-only after 2027-01-25 absent a dated R4 ruling), but add that the S5 read (>=300 positions, 359-412 days from 2026-11-23, i.e. after 2027-01-25) can only ever be advisory under the current RA-13 date; the PREREG should say so rather than imply a post-date read can promote.

Ruling O-5 verbatim string must change with C1 ("110-day label; certified_horizon_climate_days = 110").

## Summary of required edits
Plan: N1 pin (blocking), N2, N3 disclosure, number fixes (variance 0.153, fee 0.013-0.017), S5 G8 wording.
Ruling: C1 unit fix (blocking), C2 wording + false-stop disclosure, C3 mandatory pinned sensitivity cell, C5 post-STOP/advisory text.
