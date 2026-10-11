**VERDICT: READY-WITH-CHANGES (not READY). SCORE: 82/100**

M1–M7 and merge items 3–9 are all present in r3.1. Two items are implemented wrongly: T-SPREAD's cluster q is anti-conservative, and the T-LOC collapse is unproven. Details are in the table and the checks below. I did not read any outcome data.

| ID | Sev | Finding | Evidence | Required change |
|---|---|---|---|---|
| C1 | HIGH | T-SPREAD uses q_c = max q_d and calls it "a Fréchet lower bound, so the upper-tail test is conservative". The direction is wrong. A lower bound on P(A_c=1) makes X stochastically smaller under the assumed null. That makes P(X ≥ x) too small, which is anti-conservative. T-WIN's max-P_c is correct because T-WIN is a lower-tail test. Across independent days the max understates the null tail probability. | plan l.156 vs l.125 | Use the union upper bound q = min(1, Σ q_f) per cluster, or the independent union 1 − Π(1 − q). Fix the comment and test #17. Recompute the T-SPREAD min-p and H1-S power. |
| C2 | HIGH | The T-LOC collapse is asserted, not shown. The sign of a cluster-mean error over days with different pmfs and magnitudes is not a Bernoulli bounded by [min π_d, max π_d]. Days with unequal pmf shapes can push the sign probability outside that interval. "Larger p is conservative" holds only if that bound holds. It is monotone for the observed direction, but the premise is unproven. | plan l.149 | Either define the cluster statistic as a sign vote with an exact bound, or label T-LOC "indicative, not validated conservative". In the second case it cannot feed MODEL_LIMITATION alone. |
| C3 | MED | S0-I computes min attainable p only against the uniform 0.5 reference. With π around 0.6, 7 same-sign gives about 0.028 and is NOT-TESTABLE. The plan does not say that testability uses the max-of-two-vectors rule. | l.165, l.171 | Pin testability to the same π^min/π^max rule. |
| C4 | LOW | Post-tie re-evaluation can shrink Holm k after outcomes are seen. A member that cannot reject never affects validity, so this is acceptable, but the predeclaration should say so. | l.173 | One sentence. |

**Checks that passed**
- Holm α/k: NOT-TESTABLE members are dropped first, k shrinks, and the TESTABLE-CONDITIONAL status is correct. The 6-cluster reference values are consistent, and test #32 pins them.
- Post-tie re-evaluation: present, and a downgraded test cannot feed VARIANCE (test #50).
- T-LOC π_d null: a single per-day pmf null, as M2 required.
- Power as the min over the two P_c bounds: the direction is correct. The independent union lowers power, so it is the binding one. T-SPREAD power under H1-S (doubled q, capped at 1) is reported.
- Per-fill T-SPREAD pmf, with q_d as the max over the day's fills and A_c as any fill in the cluster: pinned. C1 applies to the cross-day step only.
- §0 expectation and LOO outside α: correct. Dropping a win cluster recomputes w_obs.
- BODY_MISS rename: the stale K9 "VARIANCE" label is gone and SIBLING_WON-first is pinned in #13.

Fix C1 and C2 and the plan is READY.