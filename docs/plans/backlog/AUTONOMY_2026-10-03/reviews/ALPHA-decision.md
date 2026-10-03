# Coordinator decision: α indexing, mint limit and the forward-window cap (2026-10-03)

**Conflict.** AUT-4 r2 uses a lifetime α index (as directed in AUT-4-r1-merged E1). ARCH Rev 5 §4.2 tests the k-th
MINT *per window* at α_total·2^−k. The reviewers flagged both:
- A per-window reset gives unbounded family-wise α across windows.
- An unbounded lifetime k makes deep candidates impossible to compute or power, and breaks C4's `alpha_spent` cross-check.

**Decision (binding on ARCH Rev 7, AUT-3 and AUT-4; settled by peer review, not by the operator):**
1. **Two separate counters.**
   - `k_life`: the lifetime α index per lineage. It counts every evaluated MINT and **never resets**. Candidate k is tested at α_total·2^−k_life, so Σα ≤ α_total for the whole life of the lineage.
   - `mints_in_window`: the rate limiter. At most K_max MINTs per forward window (ARCH W7 mint limit). AUT-3 records `NO_CHANGE(k_max_reached)`, which counts toward its live-proof streak.
2. **Effective horizon.** `K_LIFETIME_EFFECTIVE` is a pins.py ceiling (proposed value 6). A candidate with k_life > K_LIFETIME_EFFECTIVE is evaluated **nominally**: it is descriptive, it never produces a promotable PASS, and its α is still charged. Bootstrap or permutation B is capped, with an exact or analytic tail used beyond the cap.
3. **Window cap feasibility.** Every FORWARD_SHADOW verdict records `n_min_eff` and `n_cap = stations·window_days·uptime_floor`. If n_min_eff > n_cap, the verdict is `INCONCLUSIVE(window_cap_below_n_min)` **by construction**. Under today's σ and X this applies to every candidate (n_min 403–605 > n_cap ≤ 480), which agrees with `promote_enabled=false` (AUT-5 feasibility ETA 2027-05-06 > KILL). The verdicts still flow, so the machinery is exercised, but no promotable path is claimed. Evidence class: machinery proven, edge unproven.
4. C4 records `k_life`, `alpha_k`, `mints_in_window`, `n_min_eff` and `n_cap`. The registry cross-check uses `k_life`.

## Amendment 2026-10-03, later the same day: ARCH Rev 6 rule adopted as canonical (supersedes the detail above)
ARCH Rev 6 refines this decision and its rule now binds:
- α is charged **per AUT-4 stage-1 nomination**, not per mint. `k_life` counts nominations and **never resets**, so Σα ≤ α_total per lineage.
- At most **1 nomination per forward window**, and **K_LIFETIME = 4** nominations per lineage, which replaces the proposed 6.
- MINTs are rate-limited separately to **1 per lineage per day** across both model classes. A mint that is not nominated spends no α.
  AUT-3 therefore does not need `NO_CHANGE(k_max_reached)`, because K_max limits nominations, not mints. AUT-3 records `MINT_REFUSED_CEILING`
  only when the 1-per-day mint ceiling refuses.
- Items 3 and 4 above (the window-cap INCONCLUSIVE rule and the C4 fields) are unchanged, with `k_life` meaning the nomination index.
