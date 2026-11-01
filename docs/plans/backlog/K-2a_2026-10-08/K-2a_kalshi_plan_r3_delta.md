# K-2a/K-2b plan r3 — delta over r2 (ROI re-audit 2026-11-01: backlog item KALSHI-ADAPTER)

Applies on top of `K-2a_kalshi_plan_r2.md`; where they differ this delta wins. Status: r3 — peer review pending (architect + prediction-market-reviewer).

## R3-1 Gate replaced: GAP-6 GO, not "programme KILL"
r2 §0 "K-2b starts only on programme KILL [A1]" and §7 "K-2b (gated: KILL, then N-S START)" are REPLACED by: **K-2b starts when GAP-6 writes `ADAPTER_DECISION: GO`** (`docs/plans/backlog/GAPS_2026-11-01/gap6_sample_and_size/plan_r3_delta.md` R3-3: S0 ≠ KILL and census PASS S × H ≥ n_req). The PM.us programme state is irrelevant to the gate: the operator's single objective is portfolio ROI, and the P4 maker has 0 fills since 10-24, so waiting for its day-21 STOP buys nothing. Node N-S (§8) still runs, within 7 days of GO, and may only DEFER with a stated reason. A GAP-6 NO-GO leaves K-2b unstarted and the parked branch parked (§6 unchanged).
- Reason this is a ruling change: r2 cited RA-13 §4/§5 and R3V §3.3. This delta IS the proposed amendment; the B-8 peer loop that GAP-6 S1 already requires co-signs it in the same ruling (one ruling, not two).

## R3-2 Inputs handed from GAP-6 (new WB-0 precondition)
WB-0 reads the GAP-6 census artefact: measured S (eligible station-days/day), the pre-observation best-NO-ask distribution per station × side, θ (from S6) and the strike_type mix. These replace r2 §5's placeholder power inputs; §5 arithmetic re-runs on the measured values before WB-5.

## R3-3 Order inside K-2b (ROI-first)
WB-3 (barriers/egress pins) → WB-6 (read path: depth + instruments, shadow) → WB-4 (ledger) → WB-7 (one family, qty 1, PREREG from the GAP-6 tail band if S0 CONTINUE, else from the first STRATEGY-SEARCH PASS on Kalshi) → the rest of r2 §7 unchanged. WB-6 shadow must run ≥ 7 days with zero `resting_query_unreadable`-class latches before WB-7 (lesson 10-28). Live enablement on Kalshi is operator-only, as on PM.us.

## R3-4 ROI mechanism
Kalshi is the only station-day multiplier (24 cities × HIGH/LOW vs 5 × HIGH) and the only venue with fee-free tail excess measured. Without it, every PM.us family tops out at tens of dollars per month at qty 1. The adapter is a precondition for SIZE-UNDER-CAPS to have anything to size.

## R3-5 Unchanged
All r2 invariants, the null-hypothesis section (§2: no native Kalshi adapter in Nautilus 1.231.0, so the adapter is a native extension mirroring the PM.us exec seam with permit, ledger and NO-SEND intact), WA-1/WA-2 desk work, and §10 operator-only items.
