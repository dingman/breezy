# P5 plan r1 — scale decision (2026-10-22; author trading-bot-architect)


**Goal:** Decide whether to raise quantity, using measured P4 inputs.

**Inputs, all measured in P4**
- fills/day `f`
- net per contract `m`, after actual commission
- win rate with its Clopper–Pearson lower bound
- the venue's depth and queue at our posted prices
- notional/day at qty 1

**Computation**
- Projected $/month at qty N ≈ `f × 30 × N × m_LB × k`.
  - `m_LB` is the lower-bound net per contract: the 95% lower bound on win rate converted to net, not the point estimate.
  - `k` is a depth factor in (0,1]. Take `k = min(1, queued-ahead-adjusted fill share)`, measured as our fills as a share of the tape trades at our price.
- Capacity check: N × (fills/day) must stay under 20% of the observed D0 ladder notional of about $0.4–2.6k/day. Above that, our own size moves the price.
- If `k` falls by more than half when N rises, treat the extra size as not scalable.

**Hurdle (the operator sets it; it is the operator's budget call)**
- The operator names the minimum $/month, the maximum daily budget and the maximum per position.
- I do not set any of these. P5 only reports whether the projection clears the number the operator gives.

**Step-up schedule**
- qty 1 → 3 → 10, each step needing a re-check.
- Each step runs until at least 40 more fills.
- Advance only if, at the new qty:
  - win rate stays at least 95%;
  - net per contract is within 0.01 of the earlier step;
  - `k` has not collapsed.
- A 3rd loss at any qty halts and drops back to qty 1.
- Each step needs the operator to raise the per-position cap.

**Capacity limit**
- Σ YES asks are 1.05–1.22, and D0 ladder notional is ≈$0.4–2.6k/day.
- The audit ceiling is ≈$10–65/month even with an edge.
- If the projection at the capacity limit comes out at tens of $/month, PM.us caps the result. The next question is then Kalshi (24 cities), which is out of scope for this plan.

**What we do NOT do**
- No scale build and no new venue work.
- No scaling by assumption.
- No raising of caps by the plan itself.

Files this plan names: `/home/jon/breezy-arm-int/src/breezy/strategy/no_ladder_maker/params.py` and `composition.py` (family id and tag), the strategy file (daily counter and sharp-subset log), the new `scripts/analysis/maker_control_tally.py`, and the ruling file named in step 5. The `trade.py` call site where `params=` gets passed is unconfirmed. Codegraph has no index for `/home/jon/breezy-arm-int`, so I used grep and read. I did not run any test or gate.