# P2 r2 verification — prediction-market-reviewer

**VERDICT: APPROVE-WITH-CHANGES.** All six r1 changes are addressed. I did not re-verify code paths, so this is a read of the r2 text only. I found no new CRITICAL issue and one HIGH.

**r1 changes**
1. Three-way outcome: done (lines 66–72).
2. Realized taker P&L: done. It uses the production `evaluate` rule, the fee formula, and a YES-first primary with NO reported separately.
3. Ask set primary and mid report-only with a bid floor: done.
4. D−1 instant: done. It is the instant FQ actually traded.
5. Dual clustering, taking the wider CI, plus minimum samples: done.
6. One gating instant, with (b) dropped: done.

**Your coordinator choices**
- **PASS on D_res(ask) OR YES P&L:** acceptable. Both are one-sided looks at the same hypothesis. The extra false-pass probability only leans toward keeping the code, which is the safe direction. Delete decisions need the AND on FAIL, and the plan has that.
- **FAIL requires both upper bounds < 0:** sound and conservative.
- **Minimum samples:** reasonable.

**Issues**

1. **HIGH: the D_res(ask) FAIL leg is structurally biased toward FAIL.**
   - The ask carries a roughly 29% mean overround and is not a calibrated probability. Under 10 equal-width bins, RES is computed from bin means. WP-7b measured the ask's RES at 2× the forecast's, but that came from the market quoting tail rungs near certainty.
   - D_res(ask) < 0 is therefore the expected result even when the forecast has real taker edge. For FAIL, the P&L leg is the one that matters.
   - Fix: state in the plan that a FAIL is decided by the P&L upper bound, and that the D_res leg is corroborating only. Alternatively, make FAIL require YES P&L UB < 0 with at least N takes, plus D_res UB < 0.

2. **MEDIUM: P&L is evaluated at qty 1 at the L0 ask.** It ignores depth, so it is optimistic. That leans toward PASS, which is the safe direction. Note it in the evidence.

3. **MEDIUM: INCONCLUSIVE is the likely outcome.**
   - The 30-takes-over-30-clusters floor, the MIA dropout risk (line 88) and about 40–60 clusters in total make an inconclusive result probable.
   - That is honest, but it means P2 probably cannot justify deletion.
   - Say explicitly that INCONCLUSIVE leaves deletion to the operator's separate decision, so nobody reads it as a mandate.

4. **MEDIUM: the live-parity control needs a defined failure action.** The log was produced under live conditions, and the script reproduces it at an exactly specified decision time. A failure currently means STOP, which is right. Add a note that a mismatch likely indicates a calibration or `available_at` discrepancy and not a reason to widen the tolerance.

5. **LOW: the "wider of two CIs" rule is correct but doubles bootstrap cost.** At B=2000 this is negligible.

**Confidence: 78.**