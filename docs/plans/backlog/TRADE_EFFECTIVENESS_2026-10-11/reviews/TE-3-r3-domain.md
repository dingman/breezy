VERDICT: READY, SCORE: 93/100

No BLOCKER or HIGH finding remains. I re-ran every number in `TE-3_plan_r3.md` from Appendix C, using the unrounded λ and scipy, and re-scored the fills. The `bucket_facts_from_instrument_id` function and `truth_cli_finals.csv` were read-only inputs, and no M1-v3 data was touched.

| ID | Sev | Finding | Evidence | Required change |
|---|---|---|---|---|
| R3-1 | MED | Appendix A §6 and the §8 closing line overstate the Lane-E expiry. §8 scopes 2026-10-17 to "the δ = 0.04 corner", but Appendix A §6 says "Lane-E feasibility expires for any freeze after 2026-10-17" with no scope. The δ ≥ 0.05 high-rate cells stay feasible well past that date. For example, p0 = 0.07 at δ = 0.05 needs exact n = 204, which is 65 days, so its expiry is about 2026-11-14. The expiry for the δ = 0.06 central cells (2026-10-13 and 2026-10-23) is also missing from the ruling text. | Plan lines 228 and 314-315 | Say "the δ = 0.04 corner (normal-approximation cell) expires after 2026-10-17". Optionally list the cell expiries, or state that δ ≥ 0.05 cells expire later. |
| R3-2 | LOW | The verdict-date table shows "not reachable" for 155 at the low rate. The computed date is 2027-06-01, which is past the backstop. The other infeasible cells show their dates. | Plan line 158 | Show 2027-06-01 (past the backstop) for consistency. |
| R3-3 | LOW | The Appendix B command does not reproduce the "7 of 9 refused `observation_ambiguous`" count or the 12-16 LST hours. STOP 5 requires every number to be reproducible. I re-ran a variant and the counts hold. | Plan lines 79-82 and 327-346 | Add the reason and `hour_lst` tallies to the command, or mark those two as separately checked. |
| R3-4 | LOW | "7 of 9 distinct rungs refused" counts the rungs that were only refused. 8 of 9 had an ambiguity refusal, because MIA 09-21 was also refused before its take. | Plan line 81 | Reword the line. |

**Premises checked:**
- **P-fills: CONFIRMED.** The CLI tmax values are MIA 09-15 = 93, MDW 09-22 = 64 and MIA 09-21 = 88. The inclusive intervals are [92,93], [62,63] and [88,89]. The results are NO loses (−0.09), NO wins (+0.87) and NO loses (−0.13). The net is +0.65, so 3 fills / 1 win.
  - I did not re-open the execution sqlite file. The three instrument ids I scored are the ones named in the plan's table.
- **P(≥1 of 3 | 0.12) = 0.318528: CONFIRMED.** The 0.039744 figure is correctly withdrawn.
- **Ledger z-sums: CONFIRMED.** They are 3.083024 and 3.339327. n_raw is 1485.162 and 1742.360, giving n = 1486 and 1743. The MDE values at n = 156, 308, 420 and 490 match the plan at both α. At n = 1486 the MDE is 0.039989 (α 0.0125).
- **Garwood interval: CONFIRMED.** λ = 2.00 gives [0.8635, 3.9408]. The 8/7 sensitivity gives [0.493, 2.252].
- **n_avail: CONFIRMED.** Flooring gives 67 / 156 / 308 at T = 98 and 58 / 134 / 264 at T = 84. The ceilings are 490 and 420. The 98-day window is correct.
- **Required-n table: CONFIRMED.** All normal and exact cells match at α = 0.05, and the α = 0.0125 δ = 0.04 values also match (436/476, 582/613, 672/705, 758/787).
- **Feasible-cell list: CONFIRMED.** The corner at n = 292 is feasible under the normal approximation, with a verdict date of 2027-01-20. The exact n = 311 gives 2027-01-26, which is 1 day late.
- **Verdict dates: CONFIRMED.** All of them reproduce, including 2029-05-05 and 2028-02-03 for n = 1486, and 298 days at 5 per day.
- **Freeze expiries: CONFIRMED** as arithmetic: 2026-10-17 for n = 292, 2026-10-13 for n = 155 and 2026-10-23 for n = 138. n = 311 needs 99 days, so it is never feasible. The scoping problem is R3-1.
- **Fee and break-even: CONFIRMED.** Fees are 0.00 at asks 0.06-0.07 and 0.01 at 0.08-0.12. The p0 values are 0.07, 0.08, 0.10, 0.12 and 0.14.
- **Census: CONFIRMED.** There are 9 rungs, 8 interior on 8 distinct station-days. The per-day counts are 3/1/2/2. Hours run 12-16, 2 rungs reached take, and MIA 09-21 shows both a refusal and a take.
- **Appendix A accuracy:** the text is accurate and not overstated, apart from R3-1 and R3-4. The corner, the flooring, the priors-only dismissal and the §8 "does NOT decide" section are all properly hedged.

Files: `/home/jon/breezy/docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-3_plan_r3.md`