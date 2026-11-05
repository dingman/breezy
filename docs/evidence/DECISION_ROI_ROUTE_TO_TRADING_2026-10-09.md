# Decision: ROI ranking of routes back to live trading (2026-10-09)

**Decision owner:** the coordinator. The operator delegated it on 10-09: "you are the expert. you decide which pieces of work have the highest ROI impact."

**Constraint:** RULING_FQ-v2-NO-TRADE_2026-10-08 is in force. Orders are re-enabled only by trigger T1, T2 or T3. Re-enabling orders without a trigger is rejected: the last live family lost money, and no family has a demonstrated edge.

## Routes assessed (independent specialist reviews, 10-09)

### T2: a restricted-mix family (M-no)
- The loss stop has power. NP at α_eff is 0.4927 on 11-01 against the 0.30 bar.
- But G3 falls below the 2.5·α floor by 12-01 (M-no 0.2334 vs 0.25).
- No edge evidence exists.
- **Not pursued.** It fixes the binding stop gate, not the edge, and adds no information before the M1-v3 read.

### T3: F13 US sources
- The freeze is on or after ~10-21: the R5 rule requires 14 days of C1 data, and data started 10-06/07.
- Phase A gives an offline ACCEPT/STOP only.
- The market leg B1 is UNDERPOWERED (MDE 3.25 °F vs 0.5 °F), and confirming a 3¢ edge needs about 1,500 trades.
- **Not a 2026 trading route.** Freeze prep stays (builder profiling under way).

### Kalshi (evidence rate ×3–4)
- The admission floor is ≥381 TWC-era events per series, so the earliest payoff is mid-2027.
- The WA-2 Stage 0 doc says "Nothing in this document authorises a fetch now".
- Moving it earlier needs a new ruling and buys nothing before 2027.
- **Kept on the K-2a schedule.**

### T1: the M1-v3 read, on or after 2026-12-07
- This is the only scheduled re-open before 2027.
- The plan's own prior is P(WINNER) ≈ 0.
- A CONFIRM starts a new plan. It does not arm trading.
- Gap from a CONFIRM to live orders: about 1–2 weeks of build, or about 2–3 days if prepared.

## Ranking (plan of record)

1. **Finish in-flight work.** AMBIG-LATCH B activation proofs, SELF-CHECK-ORDERS-OFF activation (10-10), AUT-6 WP9, and ING-3.
2. **M1-v3 readiness, as optionality.**
   - Now (paper only, no screen contamination): draft the T2-sender ruling and the loss-floor MC design for a model-free NO≥0.90 family.
   - Code (strategy + composition kind, manifest kept unregistered, allowlist gate, exit/demotion rules) is scheduled to build after the forward window closes (11-28) and before the read (12-07), so a CONFIRM converts in about 2–3 days.
   - Never read window outcomes. Never edit `PREREG.json`.
3. **F13 freeze readiness:** make the draft build fast and mechanical by 10-21.
4. **Resume the AUTONOMY QUEUE (row 7a onward)** and the CF-12 typing work at the remaining capacity. Neither is a trading lever.

**Review:** this ranking is revisited at the 10-21 F13 freeze and at the 12-07 read.
