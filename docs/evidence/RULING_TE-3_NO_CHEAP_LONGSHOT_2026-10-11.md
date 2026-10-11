# RULING TE-3: NO-side cheap-entry longshot (NO ask 0.06-0.12)
Date: 2026-10-11.
Verdict: UNDERPOWERED_NOT_REGISTERED (structurally infeasible on PM.us; a recompute_mde desk
recompute, intake would return this token). No PREREG is frozen. No tape outcome statistic was
computed. The only outcomes used are the 3 live NO fills, as premises (they power nothing). No tape after 2026-09-25 was read (RA-13 B-3). No M1-v3 outcome data was read.

1. Hypothesis. Buying NO at the Depth10 ask on an interior rung with NO ask in [0.06, 0.12] has
   positive net EV. It was prompted by 3 live NO fills, scored through the bot's inclusive band
   rule (bucket_facts_from_instrument_id): 1 win (MDW 09-22, +0.87), 2 losses (MIA 09-15 -0.09,
   MIA 09-21 -0.13), net +0.65. P(>=1 win of 3 | p=0.12) = 0.318528. No motivating anomaly
   survives the corrected scoring; the ledger verdict stands on its own. The fills are all the
   NO fills among 34 and are SEARCH data.
2. Delta. Disjoint from M1-v3 (NO ask >= 0.90). Samples are never pooled. The bot's NO rule
   (PREREG v3a, NO-1) is dead: cont/v4 halted (as of 2026-10-11), P_HOLD_UPPER unsafe on the NO side, AUD-01a
   no_side_calibration_gate_cleared=False. H-NO-SIDE-2026-09 already holds the no_side_hunting
   class as UNDERPOWERED_NOT_REGISTERED; this ruling cites that record and registers nothing new.
   Erratum: H-NO-SIDE quotes n ~1487; the recomputed figure is 1486.
3. Basis (R4, mechanical; MDE bound 0.04 per H-NO-SIDE section 3). Variance 0.25, power 0.80.
   - alpha 0.05/4 = 0.0125, z-sum 3.083024: n_raw 1485.16, n = 1486 station-days.
   - alpha 0.025/4 = 0.00625 (RA-13 programme FWER), z-sum 3.339327: n_raw 1742.36, n = 1743.
   PM.us has 5 stations: a 98-day window (2026-10-12..2027-01-17, backstop 2027-01-25 less an
   8-day truth lag) yields at most 490; 420 for a 2026-10-26 start. Ledger MDE at 490 = 0.0696
   (0.0754 at alpha 0.00625); at 420 = 0.0752 (0.0815). All exceed 0.04. The result holds at
   any rate.
4. Corroboration (Lane E, alpha 0.05, power 0.80, delta = 0.04 only). Preliminary census: 8
   interior rungs over 4 full tape days, lambda = 2.00/day, exact Poisson 95% [0.863, 3.941];
   the 9th rung is an open tail and excluded; 2 of the 8 reached take; 7 of 9 distinct rungs were only
   refused observation_ambiguous. n_avail (kappa 0.8, T 98, floored) = 67 / 156 / 308
   (low/central/high). Required exact-binomial n at delta 0.04 is 311 to 516 over p0 0.07-0.14.
   The test is infeasible at the central and low rates. At the high rate it fits only at p0 =
   0.07 under the normal approximation (n 292, verdict 2027-01-20); the exact test (n 311)
   misses the 2027-01-25 backstop by 1 day (2027-01-26). That corner needs every entry at ask
   0.06 and the 95% upper rate, so a band-pooled test (mixed p0) cannot reach it. This is
   corroboration, not a structural claim. At delta >= 0.05 some cells fit (central: p0 0.07,
   delta >= 0.06; high: several); excluding them rests on priors only (adverse fair-odds prior;
   SEARCH-picked band; observation_ambiguous refusals), not on a measurement.
5. Caveats. Four days; coverage holes at 09-17, 09-19, 09-23 and none after 09-23; sensitivity
   8/7 = 1.14/day. Same-day cross-station correlation shrinks effective n further. Floored
   n_avail, unrounded lambda.
6. Re-open triggers and next actions (formulas and census command: docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-3_plan_r3_1.md, Appendices B and C; Lane E = the offline forward-test lane outside the AUT-S K ledger, as M1-v3; R4 = the hypothesis_ledger recompute_mde rule): (1) PM.us station count lifts lambda*kappa*T to >= 1486
   (1743 at alpha 0.00625) before the backstop: re-run plan Appendix C; (2) desk action now: propose a
   successor-ruling candidate class to the WA-3 table, size via K-2a section 5 as amended by WA-3 P4'/WA-4 W15 (recompute_mde_k, Azuma; bound_K, n_K,
   shared alpha), exclude the 5 shared cities, reuse no PM.us n/bound/alpha (B-2); (3) bound
   raised by an outcome-free pre-freeze ruling: re-run recompute_mde, needs ~0.088 at n=308 (0.095 at alpha
   0.00625) or ~0.123 at n=156 (0.134); 0.0696/0.0754 at the 490 ceiling is necessary, not
   sufficient; (4) FQ-v2 trigger T2 or T3, as defined in RULING_FQ-v2-NO-TRADE_2026-10-08.md and RULING_R3-VIABILITY_NOT_VIABLE_2026-10-08.md section 3.2, fires (recorded by ruling on or before 2027-01-25) and requests it: re-plan WP-4. T1 (an M1-v3 CONFIRM) is irrelevant, because this sample is never pooled with M1-v3. Lane-E
   feasibility at delta 0.04 expires for any freeze after 2026-10-17 (the delta 0.06 central cells after
   2026-10-13 exact / 2026-10-23 normal); delta >= 0.05 cells are excluded on priors, not by expiry. Triggers 1, 3 and 4 lapse on 2027-01-25 (RA-13 backstop). Trigger 2 does not lapse.
7. Dormant WP-4 (the offline Lane-E tool defined in the plan, section 6) requirements: inputs refuse climate days after 2026-09-25; LST->UTC multi-day
   tape reusing replay_sufficiency.decision_window_ns; standalone no-lookahead check on the LST
   day end; scoring via bucket_facts_from_instrument_id. A re-plan re-opens python F4-F10 and
   arch G7/G8 as review inputs.
8. What this does NOT decide. It does not dispose of the NO-side class for RA-13 section
   6.6 / B-1. It does not kill the NO-side requirement. It does not fire R4. Arming, halts, caps,
   the NO-SEND firewall, Nautilus, allow_short and every PREREG are untouched.
   It does not assert the hypothesis is false and makes no edge claim: it records that the ledger test cannot be powered on PM.us. It does not rule on the Lane-E cells at delta >= 0.05 beyond section 4, and it does not claim those cells are infeasible. It does not alter M1-v3 (PREREG frozen, read-once on or after 2026-12-07), FQ-v2, or any operator cap or budget.

Reviews: docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/reviews/TE-3-final.md; final text read 2026-10-11 (prediction-market-reviewer, edits 1-5 applied verbatim).
