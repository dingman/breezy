# P5 plan r2 — scale decision (2026-10-22; supersedes r1)


**Goal:** Compute one projection from the P4 results and compare it with the operator's hurdle.

**Inputs from P4**
- `f`: station-days with a fill, per day.
- `p_LB`: 90% one-sided Clopper–Pearson lower bound on the station-day win rate.
- `b`: mean bid.
- `c`: flat $0.01 cost, rebate excluded.
- `D`: median per-rung volume traded at or below our bid, per day, from the book and trade logs at our prices.
- `H`: the operator's minimum $/month. The operator owns it, along with the caps.

**Formula (computed once)**
- Net per contract: `m = p_LB − b − c`.
- Capacity: `N_cap = floor(0.2 × D)`. This is per-rung depth at our prices, not ladder notional.
- Projection: `M(N) = f × 30 × N × m`. There is no separate depth factor `k`, because the depth limit sits only in `N_cap`.
- Required size: `N* = H / (f × 30 × m)`.

**Decision**
- If `m ≤ 0`: stop. The edge does not survive the bound.
- If `N* ≤ N_cap`: ask the operator to set the per-position cap that allows `N*`. This is one step with no schedule. Re-read the artefact after 40 more fills.
- If `N* > N_cap`: PM.us capacity binds. `M(N_cap)` is likely tens of $/month. The next question is Kalshi (24 cities), which is out of scope here.

**We do NOT**
- No step-up schedule.
- No double-counted `k`.
- No cap changes by the plan.
---

## r2.1 coordinator amendment (per `reviews/P4P5_r2_pmr.md`) — STATUS: READY

- Report M(N) twice: at the point estimate p̂ and at p_LB. The decision uses p_LB **for risk only**. Otherwise a PASS at the floor (36/37 ⇒ p_LB ≈ 0.90, m ≈ +0.024) always reads as "capacity binds".
- m measured at qty 1 may not hold at N, because D is conditioned on adverse moves. Re-read after 40 more fills at the new N, and drop back to qty 1 if m_hat ≤ 0.
