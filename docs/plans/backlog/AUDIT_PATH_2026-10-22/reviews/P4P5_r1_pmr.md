# P4/P5 r1 review — prediction-market-reviewer

**VERDICT: REQUEST-CHANGES** (P4). P5 is APPROVE-WITH-CHANGES once P4 is fixed.

**Evidence.** I used `positions.csv` and `summary.json` in `maker_nobid_full/` and `maker_nobid_sharp/` under `~/.local/share/breezy/derived/replay/design/`, plus `params.py` in `/home/jon/breezy-arm-int/src/breezy/strategy/no_ladder_maker/`.

**Required changes**

1. **The 40-fill PASS is unreachable inside the 45-day STOP.**
   - Control filled 8 times (8 wins). Its tradable days run 09-30 to 10-13, about 13 days with data, because `abstain_unlisted` drops the late-listed days. That is about 0.6 fills/day.
   - So 40 fills take about 65 days, and only about 27 fills arrive by day 45.
   - Day 21 gives about 13 expected fills against the "fewer than 10 fills" STOP. That fires roughly 20% of the time even if the rate holds, and more often since 8 fills is a noisy estimate.
   - The 5-bids/day cap makes it worse. Control posts 7–9 rungs on busy days. The sharp rule with a cap (`sharp_cap84`) lost about 30% of its fills (12 against 17).
   - Sharp gets 17 fills in about 24 days, about 0.7/day. That is 57 days to 40 fills, so it also fails at 45 days.
   - Either design leaves the test as written with a very high chance of ending in a STOP. Control is also the weaker rule on fill rate.

2. **The PASS gate tests a 95% win rate, not an edge, and has little power.**
   - Control's breakeven win rate at a bid of about 0.77 is about 0.78–0.81. At 38/40 the net is about +0.17 per contract, so the "+$0.02 net" clause never binds. It is decoration.
   - 38/40 rejects breakeven (p=0.80) with probability under 1%, which is good. But a true win rate of 0.90 (net about +0.10 per contract, clearly profitable) passes only about 22% of the time. A true 0.93 passes about half the time.
   - The gate therefore cannot separate "profitable" from "breakeven". It separates "at least 95%" from the rest.
   - Replace it with a one-sided test against the breakeven win rate. For example, 25 fills with at most 1 loss rejects p=0.80 at about 3%. Set the horizon from the real fill rate, about 60 or more days for control.

3. **The 3-loss STOP is a loss bound, not an inference rule.**
   - Three losses in 40 is a win rate of 92.5%. At a loss of about −0.77 against a win of +0.23, that is still positive net.
   - Say that the STOP is a harm bound and not evidence of no edge. Don't let a STOP read as FAIL.

4. **The sharp-subset logging is invalid and should be cut.**
   - The two rules have disjoint bid ranges: control bids 0.70–0.80, sharp bids 0.75–0.89, and most sharp fills sit at 0.81–0.89.
   - A control order can never be a sharp order. The same rung rests at 0.80 under control and at 0.89 under sharp.
   - A fill at 0.80 occurs under different market moves than a fill at 0.89, so conditioning on it is selection bias. Sharp's breakeven of about 0.90 is also different.
   - `sharp_would_pick` shows what sharp would decide. It gives no information about sharp's fills or P&L. Drop step 3, or run sharp as the live test, which is the rule that was actually nominated.

5. **Commission needs to be one consistent treatment.**
   - `harm_stop.py` costs each fill at the max of the venue fee and θ=0.0695, rounded to the cent with a 0.01 floor. At qty 1 that is a flat $0.01 per fill.
   - The tally script uses the actual commission. State which of the two is authoritative for the net gate.
   - Report the net both with and without the rebate. A rebate is unproven, and the plan should not let a rebate create a PASS.

6. **Clustering is ignored.**
   - Control's `n_eff` is 6.0 for 8 fills, and sharp's is 13.5 for 17. The fills are correlated within a station-day and across stations (same weather regime). Examples are LAX on 10-06 and LAX plus MDW on 10-02.
   - A binomial analysis over fills overstates the evidence. Count independent station-days, or use Clopper–Pearson on days.

**P5**

- `f×30×N×m_LB×k` double-discounts. Measured fills/day already includes queue position, so applying `k` on top counts the queue twice.
- The capacity rule is vacuous. At N=10 and 0.6 fills/day the notional is about $5/day, against the $400–2,600/day base, which is about 1%. The real limit is per-rung depth.
- The projection comes to about $30/month at N=10 (0.6×30×10×0.17). The plan's own ceiling is about $10–65/month.
- The step-up schedule (1→3→10, 40 fills each) would take about 200 days. The "net within 0.01" rule is far below the sampling noise of 40 fills.
- Simplify to: one formula computed once from P4 results, compared with the operator's number. Delete the step-up schedule.

**Simplifications**

- Drop the sharp-subset log, the `max_simultaneous=5` change to the frozen constants, and the P5 schedule.
- Prefer to run sharp live instead of control. It has a higher fill rate and is the rule the audit nominated.

Confidence: 80. The fill-rate figures come from 8 and 17 fills, so they are rough, but the direction is robust.