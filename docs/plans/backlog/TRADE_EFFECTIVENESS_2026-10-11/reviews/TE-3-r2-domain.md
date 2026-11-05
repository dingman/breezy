VERDICT: READY-WITH-CHANGES
SCORE: 88/100

All seven r1 merge rulings are implemented. The primary R4 basis holds. The corroboration prose misstates the Lane E feasibility grid, and the Appendix A text overstates the p0=0.07 corner.

I re-ran every Appendix C formula with `/home/jon/breezy/.venv/bin/python`, and I re-ran the Appendix B census. Everything matches the plan except the points in the table below.

| ID | Sev | Finding | Evidence | Required change |
|---|---|---|---|---|
| S1 | MED | §3 says the Lane E test is "infeasible at the central and low rates for every p0 and every δ ≤ 0.06". That is false. At p0=0.07, δ=0.06 the n_min is 138 (normal) and 155 (exact), and central n_avail is 156. The exact verdict date is 2027-01-24 (97 days, +8), which is inside the 2027-01-25 backstop. Appendix A restricts itself to δ=0.04, so the ruling text is not wrong on this point, but §3 and §0 are. | Plan §3 "Corroboration" (line 147), n_min table (lines 124-129) | Restrict the claim to δ=0.04. Or add "except p0=0.07, δ ≥ 0.06 (central) and several cells at the high rate". Or drop "every". |
| S2 | MED | The high-rate sentence "infeasible except in one corner" is false as written for δ>0.04. At n_avail 308, many cells have n_min ≤ 308, for example p0=0.07 at δ=0.05 or 0.06 and p0=0.10 at δ=0.05 (253/270). These are not the "p0=0.07, δ=0.04, normal" corner. | Plan lines 147-148; §0 line 13 | Qualify as "at δ=0.04", as Appendix A does. The grid is also feasible at δ ≥ 0.05, so the dismissal of those cells rests only on §4 prior grounds. Say so. |
| S3 | MED | The Appendix A and §0 claim that the high-rate p0=0.07 corner sits inside the backstop is arithmetically correct but overstated. (a) It holds only for the normal approximation. The exact n of 311 gives 2027-01-26, one day late. The plan does show this in the §3 date table, but the "knife-edge" wording hides that the exact test fails. (b) p0=0.07 applies only to entries at ask 0.06 exactly, and the rate λ was measured over the whole 0.06-0.12 band. A pooled band test has a mixed p0, so the corner is not reachable even at the high rate. (c) It needs the upper end of the Garwood CI plus the assumed κ=0.8. | Plan lines 12-13, 138-139, Appendix A item 4 | Add to Appendix A: "the exact test misses the backstop by 1 day; the corner needs every entry at ask 0.06 and the 95% upper rate". |
| S4 | LOW | n_avail is floored: 308.95 is quoted as 308 and 67.7 as 67. This is harmless and conservative, but it is not stated. | Plan line 101-103 | Optional: note the flooring or round. |
| S5 | LOW | The low-rate verdict date for n=464 reproduces as 2028-08-21 with the unrounded λ=0.8635, so the plan is right. This is only a note that rounding λ to 0.863 gives 08-22, so the Appendix C script should use the unrounded λ. | Plan line 141 | None. |

Reproduced and matching, no change needed:
- **Garwood interval:** [0.8635, 3.9408], and the 8/7 sensitivity [0.493, 2.252].
- **n_min tables:** the normal and exact n_min at α=0.05 and α=0.0125 match every cell.
- **Ledger constants:** z-sum 3.083024, n_raw 1485.162 which rounds to 1486, and the MDE values 0.0752 at 420, 0.0696 at 490, 0.1234 at 156 and 0.0878 at 308.
- **Bernoulli MDE:**
  - normal: 0.069 at n=156 and 0.048 at n=308
  - exact: 0.077 at n=156 and 0.052 at n=308
  - at the ceilings: 0.038/0.040 at 490 and 0.041/0.044 at 420
- **Windows:** the T=98 window is 2026-10-12 to 2027-01-17, which is backstop minus 8 days.
- **Ledger infeasibility:** 1486 at 5/day needs 298 days (297.2 rounded up).
- **Fee and p0 table:**
  - fee: half-even rounding gives 0.00 at asks 0.06 and 0.07 and 0.01 at 0.08 to 0.12
  - p0 values: 0.07, 0.08, 0.10, 0.12, 0.14
- **Binomial:** P(≥2 of 3 | 0.12) = 0.039744.
- **Verdict dates:** all other cells match, including 2029-05-05 and 2028-02-03.
- **Census:** I re-ran Appendix B and got the identical output.

Merge ruling checklist:
- **Ruling 1:** done (`UNDERPOWERED_NOT_REGISTERED`, n_raw 1485.16, 1486, H-NO-SIDE cited, no new registration).
- **Ruling 2:** done except for the S1 and S2 wording defects.
- **Ruling 3:** done.
- **Ruling 4:** done.
- **Ruling 5:** done.
- **Ruling 6:** done.
- **Ruling 7:** done.

Premises checked:
- **P1** (ledger arithmetic): CONFIRMED.
- **P2** (fee rounding and break-even table): CONFIRMED.
- **P3** (census counts): CONFIRMED by re-run. I did not re-check the "7 of 9 refused observation_ambiguous" figure.
- **P4** (p0=0.07 corner inside the backstop): PARTIALLY CONFIRMED. It is true only for the normal approximation (2027-01-20). The exact test is 1 day late (see S3).
- **P5** ("infeasible for every δ ≤ 0.06" at the central rate): WRONG at p0=0.07, δ=0.06 (see S1).