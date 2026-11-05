# P4/P5 r2 verification — prediction-market-reviewer

**VERDICT: APPROVE-WITH-CHANGES** (P4 r2 and P5 r2). Confidence 78.

**Recomputed from `maker_nobid_sharp/sharp/positions.csv`**
- Mean bid over the 17 stress-pass fills is 0.8647, so p0 = 0.8747, which rounds to 0.875. Over all 20 base fills it is 0.8785. The ruling must pin the exact figure, because 37/37 versus 36/37 sits on the threshold.
- There are 16 station-days with a fill (15 single, 1 double) over 23 data days (09-18 to 10-13).
- P(PASS), meaning at most 1 loss in 37, comes out as the plan states: 0.045 at p=0.875, 0.442 at 0.95, and 0.104 at 0.90. The stated power is correct.

**Your questions**

1. **Is p0 per-fill breakeven the right null for a station-day indicator?**
   - It is acceptable but not exact.
   - A station-day with 2 fills wins only if both win. Under per-fill breakeven its win probability is at most 0.875, so true breakeven is lower than 0.875 for those days. Size is therefore conservative, which is fine.
   - Only 1 of 16 in-sample days has 2 fills, so the effect is small.
   - The count statistic ignores loss size. A loss at a 0.89 bid costs 0.90 and a win pays 0.10. The "net > 0" clause is not redundant in principle, but with at most 1 loss in 37 it is almost always satisfied.
   - Keep it, and say it is a safety clause and not the inference.

2. **Is the 0.7 station-days/day rate right?**
   - It is 0.70 per data day (16 over 23) but 0.62 per calendar day (16 over 26).
   - That gives 53 days to 37 station-days at 0.70, and about 60 at 0.62.
   - It was also chosen in-sample and is subject to winner's-curse inflation. Expect the real rate to be lower.
   - The day-21 STOP at fewer than 8 station-days is sensible (expected about 13–15). The day-75 hard stop is OK.
   - Add this: if the rate is below 0.5/day at day 21, the plan will not reach 37 by day 75, so state that outcome as STOP and not as a FAIL.

3. **Evaluate PASS at exactly the first 37 complete station-days.** "At least 37" invites re-testing at n=38, 39 and so on, which inflates α. The early FAIL at the 2nd loss is fine. An unsettled fill should hold its station-day out of the count.

**P5 r2**

- The formula `m = p_LB − b − c` is dimensionally right, and removing `k` and the schedule is a correct simplification.
- It has a calibration problem. The P4 PASS gate is built so that the 95% bound sits near p0. A 36/37 outcome (the PASS floor) has a 90% Clopper–Pearson lower bound of about 0.90, so m is about +0.024 per contract. 37/37 gives a lower bound of about 0.94, so m is about +0.065.
- At 0.7 station-days/day, 36/37 gives about $0.5 per contract-month. N* = H/0.5 is large, so it will almost always exceed N_cap. The "tens of $/month" conclusion is therefore driven by the lower bound and not by the edge.
- Required change: report M with the point estimate (p̂) and with p_LB, and say that the decision uses p_LB for risk only. Otherwise P5 outputs "capacity binds" regardless of the result.
- Add a caution. D is volume at or below our bid, which is conditioned on adverse moves. A larger N also moves the realized adverse-selection rate, so m measured at qty 1 may not hold at N. The existing "re-read after 40 more fills" covers this.

**Other check**

- The exposure ceiling in step 5 (8 × $0.89 × 3 days ≈ $21) assumes harm-stop lag, but r2 FAILs at the 2nd loss through the same reading. The early FAIL is only as fast as the daily read, so it carries the same lag.