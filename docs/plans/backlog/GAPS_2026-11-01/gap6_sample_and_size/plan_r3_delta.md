# GAP-6 plan r3 — delta over r1 + r2 (ROI re-audit 2026-11-01: S0 first, end in an adapter go/no-go)

Applies on top of `plan_r1.md` + `plan_r2_delta.md` (incl. R2-6); where they differ this delta wins. Status: r3 — reviewer confirmation pending (architect + prediction-market).

## R3-1 Order and parallelism
- **S3 (S0 one look on settled history) is the first step of the whole backlog**, in parallel with GAP-1. It is the only remaining step that can find a positive edge without a forecast.
- **S4 (3-day capture pilot) starts immediately after S2 (build)**, not after the S3 verdict: it is calendar-bound and costs only disk. If S3 returns KILL the capture unit is stopped and the files kept (descriptive).
- S5 (14-day capture + census look) proceeds only if S3 ≠ KILL.

## R3-2 Cuts
- The "Size math — ILLUSTRATIVE ONLY" section is DELETED from the plan body. The take rate is unmeasured, so the table informs no decision; sizing lives in the SIZE-UNDER-CAPS backlog item.
- S6 (θ verification) is DEFERRED until S3 ≠ KILL and S5 PASS; a fee error cannot create an edge. D-3 defaults to the published fee schedule with a one-line verification at S6.

## R3-3 End state is a decision, not a census
S5 PASS (S × H ≥ n_req) → the plan's output is a **KALSHI-ADAPTER go** with the measured S, best-ask distribution and θ handed to that item's plan; S5 KILL or S3 KILL → **no-go**, Kalshi leaves the backlog and the parked branch stays parked. The census `.md` carries a final line `ADAPTER_DECISION: GO | NO-GO` written by the script from the frozen rule (L-75).

## R3-4 Operator decisions restated
D-2 (`s0` + `census` exception) gates S3 and is the first ruling needed. D-4 (size q) moves to SIZE-UNDER-CAPS. D-3 defaults as above. Everything else in r1/r2 is unchanged.

## R3-5 (prediction-market r3) no q anywhere in GAP-6
S6 drops the q grid and reports H1/H2/H3 only. D_gate is FIXED at 1 (the qty-1 proving stance) with the {1, 10, 100} depth grid reported; the r1 "D_gate = max(1, q)" clause (lines 10, 165) is struck. No q is read or proposed anywhere in GAP-6.
