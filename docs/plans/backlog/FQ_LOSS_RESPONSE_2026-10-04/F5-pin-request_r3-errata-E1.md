# F5 pin request r3, errata E-1 (2026-10-08): the residual outside mass in the all-YES overround shrink

**Defect.** The floor MC refused 89 of 1,502 seed-1 templates (5.9 %) with `ZERO_VARIANCE_REALISED`. All of them are all-YES overround days (Σ_NO q = 0, Σq > 1), with 2–4 legs.
- The r2 §4.2 YES-first shrink sets κ = (1 − Σ_NO)/Σ_YES. The masses then sum to 1, so the outcome outside every touched rung gets probability 0.
- The null then says x = 1 − ΣBE with zero variance, but in reality x = −ΣBE whenever the outcome falls outside the touched rungs.
- The null was degenerate, not the market. The S2 proportional shrink has the same degeneracy.

**Ruling (the domain reviewer's option (e), adopted by the coordinator).** This replaces r2 §4.2 for the case Σ_NO q = 0:

> When Σ_NO q = 0 and Σq > 1, the YES-first shrink reserves the residual mass m0 = Π_i(1 − q_i) for the outcome outside all touched rungs, with κ = (1 − m0)/Σ_YES q. The masses are κ·q for the YES legs and m0 for "other". Variance and drifts are computed over the k + 1 outcomes. Days with Σ_NO q > 0 are unchanged. A zero-variance day with x_rand ≠ 0 remains an invariant break (`ZERO_VARIANCE_REALISED`).

- **Why it is valid.** m0 is the independent-leg probability that no touched rung wins, so it uses only the day's own marginals and no new constant. L-41 holds: the joint is still the registered categorical with exact NO masses. Every YES drift is still ≤ 0, because κ < 1 whenever Σq > 1, so the Type-I conservativeness argument holds. S6 uses only feasible days and is unaffected.
- **S2 (proportional shrink).** In the same all-YES case, S2 scales the YES masses to 1 − m0.
- **Expected effect.** The outside draw adds a left tail (median |z| ≈ 4.3 on these days), which raises c. That can only push towards `unreachable_veto`.

**Open item for r4 (not blocking).** Mixed overround days (Σ_NO > 0, Σq > 1; 122 of 211 overround days in seed 1) also carry zero outside mass. They tick, because their σ > 0. The floor MC reports a sensitivity row S7 that reserves m0' = max(0, Π(1−q_i)) on those days as well, scaling the YES masses by κ' = (1 − Σ_NO − m0')/Σ_YES when that is ≥ 0, with the row skipped otherwise. The peer loop rules on whether S7 becomes binding.
