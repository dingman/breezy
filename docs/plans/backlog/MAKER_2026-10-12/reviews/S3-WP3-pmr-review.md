# S3 WP3 prediction-market-reviewer review (91890035 + 8bcc9b31)

Verdict: REQUEST_CHANGES (no CRITICAL/HIGH; 4 MEDIUM, 4 LOW). Math core is sound; changes are test-gap and sizing-note fixes.
Scores: (1) 9  (2) 8  (3) 9  (4) 9  (5) 9  (6) 8  (7) 8  (8) 8  (9) 8  (10) 9  (11) 7.

## Findings
M1 maker.py:195-201 (_sweep), :247-250 (_binding), :176-185 (_pinned): CLI orchestration is untested. Nothing asserts the sweep runs
   with outer_resamples=0, that confirm/binding/report cells get OUTER 20x2000, that report cells are theta 0.08 at f_pass, or that
   the report list never enters the verdict. test_binding_run_pins_outer_resamples_and_replicates only checks constants. Failure: a
   refactor drops the outer SE from binding (or adds it to the sweep, reintroducing the 14,569 s run) and every test stays green.
   Fix: monkeypatch maker.run_cell/run_cell_final with a recorder and assert kwargs per mode; assert 12 pinned + 6 report cells.
M2 maker.py:195-201: the early-stop path writes {mode, seed, cells, early_stop, basis} with no "verdict": "UNREACHABLE" and no
   provenance (git_head, script sha). assemble_artifact(early_stop=) exists but needs an evaluation and is never reached from _sweep.
   Plan h3: "S3 issues UNREACHABLE". Fix: emit verdict + provenance in the sweep doc (frozen fields null) and test it.
M3 templates.py:117-123 / test_maker.py:168-179: spec 6.4 pins deff 1.5 = 1+7*ICC at 8 rung-trials per date. The template draws ONE
   fill trial per station-day (4 per date), so the realised count inflation is 1+3*0.0714 = 1.21 (the test's own analytic term is
   12*rho). The test pins only the arithmetic 1+7*ICC==1.5 and checks variance at rho=0.2, never at the pinned ICC. If S2's ICC is
   estimated on rung-trials, applying it per station-day understates clustering. Fix: state the unit of S2 fill_icc in the load_s2
   docstring; either map ICC to the station-day unit (deff 1.5 => rho_sd = 0.5/3) or record why not; add a test at ICC 0.5/7.
M4 benchmark note (S3_WP3_benchmark_2026-10-13.md): arithmetic checks (481*18=8658 s; 30*16=480 s; RSS 409+98*11=1.49 GiB). But
   (a) per-replicate slope and outer unit are extrapolated 50x and 200x from 100/200-replicate points and moved 2x between runs, so
   a binding cell is 480 s +/- ~2x; (b) the 2.4 h excludes borderline 50k re-runs (each re-run repeats the ~410 s outer SE plus 5x the
   base: ~760 s, up to 18x), the 84 re-check sims, the confirm step (6 x 481 s, 48 min) and the horizon cell; (c) "2x the projection per
   cell group" is ambiguous. Worst-case sweep+confirm+binding+re-runs is ~5-6.5 h, so the stated 5 h RuntimeMaxSec is not safe in one
   unit. Fix: total each stage, give RuntimeMaxSec per stage (sweep, confirm, binding), or one unit at >= 8 h; require a 1,000-replicate
   calibration point in WP4 step 0 before setting the cap; add a watch per every-background-job-needs-a-watch.
L1 inputs.py:157-203 load_s2: no check f_pass <= f_kill (and k1 pair). A swapped pair silently reverses KILL/PASS roles. Add refusal.
L2 inputs.py:249-270: unknown_share = UNKNOWN/len(four-station non-PRE_TRADE rows); delta (g) says "all non-PRE_TRADE rows". The test
   pins 8/49. The four-station denominator is the stricter refusal, so fail-closed, but it departs from the plan text; reconcile in
   the plan or code. Also validate that the IQR contains the median (select_frozen_cell would raise only after all kill cells ran).
L3 test_maker_verdict: no test for a bracket where one cell is unsolved and the other solved (code picks the solved cell; the unsolved
   one is a failed kill cell so the verdict is UNREACHABLE; correct but unpinned). maker_config_keep_probability test checks p_cal only,
   not p_gate; cell test never asserts p_keep_gate == 1.0 or tick_share == 1.0.
L4 test_maker_s4_row_applies_exit_floor calls advance_prepared with a self-computed floor; it does not prove the engine passes
   exit_probability(pool_exit_fraction) into S4 (engine.py:150). Acceptable as CHARACTERISATION; note it.

## Per-item judgement
1. maker_be, win 1-BE/loss -BE, exclusive legs (len(xs)==3 and min==one_lost), H1 fallback share 0 (prepared.h1 all non-None, cell
   share dict {0.0}) are correct. Rung count 6 and H1 -0.16 give 2*(0.285+0.16)=0.89 <1 at b=0.70, so no fallback. Tests would catch
   independent-outcome, duplicate-rung and BE-formula regressions.
2. Fill/listing/bid-bearing means are 4-8 sigma tests; refusals covered (ICC>=1 bound untested, trivial). See M3 for deff unit.
3. lambda_sd=days/dates, r_sd*lambda_sd=legs/dates, p_keep 1, tick share 1 are correct; partly tautological tests (see L3).
4. O-4 implemented as written (nearest cell, bracket => larger c, solved-only, refuse b outside range, recheck of G1/G3/H0 at frozen
   (c,t_min,alpha) on every cell at both f, frozen_c_deff=c/sqrt(1.5) top level). Recheck is epoch 0 only (n_cal=110), which matches
   O-1; later epochs are not rechecked. Recheck G3/H0 have no borderline re-run (single 10k draw, 3 SE slack on H0): acceptable.
5. horizon_sensitivity: re-simulates to L_cap, crossing-rate only, raises if cuts < L_cap, report-only; test shows rate rises with L_cap.
6. Fail-closed and consistent with delta (a)3: pass@f_pass + fail@f_kill => UNREACHABLE (the delta text is self-contradictory there
   and the code takes the stricter reading; REACHABLE additionally needs pass@f_kill). Unsolved bracket cells skipped; none =>
   frozen None => every cell fails => UNREACHABLE. Non-sqrt_boundary (incl. freeze_blocked, floor_mode None) => failed, not rechecked.
   Borderline rule |G3-2.5a*|<2SE => one 50k re-run seed 20261013, final, never re-checked: matches plan.
7. Sound. Outer SE only widens c_se (apply_outer_se replaces c_se with the larger total), so dropping it in the sweep can only reduce
   vetoes; a spurious non-veto merely blocks the early stop, and the six f=0.5 cells re-run WITH the outer SE at 10k gate the stop.
   Assumes veto monotone in f (f=0.5 is the max fill). freeze_blocked never counts (tested both sides). See M1/M2.
8. Outage days excluded from the denominator, thresholds 0.91 / 0.20 strict; recorder-outage and AMBIGUOUS-as-listed tested. See L2.
9. Test would fail if the floor were 0 (approx 0.10 assertion plus charged fraction 0.10-0.30 around the expected 0.19).
10. O-6 string matches the ruling text segment-for-segment; `frozen cell = 2, 0.75, 0.31` renders from k, b, f_kill; certified
   horizon 110 and epoch-0 T_low tested on a real cell. Test builds the expected string from the same literal (not read from the ruling).
11. See M4.

## Required to flip to APPROVE
M1, M2, M4 (note text) and a decision on M3. L-items optional.
