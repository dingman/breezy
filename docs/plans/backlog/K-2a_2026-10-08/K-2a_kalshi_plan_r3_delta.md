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

## R3-6 (prediction-market review of r3: three REVISE items + LOWs)
1. **GO starts the build, never arms a family.** WB-7 arms only after r2 §5's power check is re-run on GAP-6's measured S, best-ask distribution and θ_K and returns REGISTERED (n_K ≤ S·H_K within the {120, 180}-day horizon; n_K derived from bound_K, the lower 95% cluster-bootstrap limit of the net-of-θ_K SEARCH excess — never the PM.us-derived 385). Otherwise write `UNDERPOWERED_NOT_REGISTERED` and go to N-2. θ_K is sourced per §5 (series `fee_type`/`fee_multiplier` + the published schedule) before the power check; GAP-6 S6 runs after S5, so no bound is quoted at GO.
2. **FQ-R14.** WB-7's PREREG family is the GAP-6 tail band if S0 CONTINUE; otherwise a STRATEGY-SEARCH candidate frozen as a PREREG before any confirmatory-window data is read. A SEARCH PASS (including S0's own tail band, which is SEARCH-spent on the settled history it read) is a hypothesis source only, never confirmatory evidence. Confirmation uses only days ≥ max(2026-07-01, F_K); SEARCH ∩ confirmatory = ∅ with a test; α drawn from the shared programme totals per r2 §5.
3. **R3-4 is REPLACED by:** "Upper bound only: Kalshi lists 24 cities × HIGH/LOW against 5 × HIGH on PM.us, so the station-day count is at most ≈ 4.8× larger (HIGH-only listings). Edge, take rate and fills are unmeasured; the tail excess is a SEARCH-era observation; expected value is unproven and may be zero (cf. the PM.us 'prize ≈ $0 at qty 1' finding). The adapter is a cost incurred to find out, not a promised return. Build cap: WB-3 + WB-6 + WB-4 ≤ 10 working days and ≤ the r2 §7 WP count; overrun → N-S DEFER with a reason."
- LOW: a GAP-6 NO-GO also closes N-S (it does not run). "S × H" is pinned to H = 120 d and S counts climate-day clusters (shared cities add no independence), as GAP-6 §5 defines. WB-6 shadow acceptance = ≥ 7 days with zero `resting_query_unreadable`-class latches AND a quote-count floor per day (a zombie recorder shows zero latches).

## R3-7 (architect review of r3: items 1–8)
1. **All KILL passages rewritten.** r2 §0:24–25, §8:382 ("KILL → N-S START"), §8:384 ("(KILL recorded)"), Interpretation 4 (:464) and §0:40 ("K-2a never displaces PM.us work") each read "GAP-6 GO" in place of "KILL"; r2's DEFER rule (a deferral names its next review date) is kept. The GAP-6 S1 B-8 ruling scope explicitly includes the RA-13 §4/§5 + R3V §3.3 amendment (GAP-6 r3 R3-4/R3-6 do not mention it; this delta is the text).
2. **α ledger with PM.us still live (blocking, fixed).** Interpretation 4's "K-2b is KILL-gated" closure is gone, so: the both-ledger combined-budget test (r2 B2, :486) moves into the shared gate at WB-4 and runs on both venues' ledgers; WA-3 binds every later PM.us registration to `programme_alpha_override`. No Kalshi look is taken before that test is green.
3. **Order corrected to r2 §7 dependencies:** WB-0 → WB-3 → WB-6 → WB-4 (WA-3/WA-4 done) ‖ WB-1 → WB-5 → WB-7 → WB-7a → WB-7b. The 10-31 TWC = NWS CLI measurement (5185/5186 station-side-days, memory `both-venues-settle-on-nws`) RETIRES WB-1's reconciliation question; WB-1 reduces to citing that artefact. R3-3's order line is superseded by this one.
4. **WB-7 keeps its r2 meaning** (SEARCH comparator + power check, KC-1 NBP). The tail-band family enters through §5 class intake as a new KC-n with its own PREREG; it never replaces WB-7 and WB-7b stays distinct. The S0 settled-history window must be disjoint from the confirmatory holdout (B4) with a test.
5. **R3-2 inputs:** census S stands in only for "Σ admitted listing-persistence"; take-rate_K is measured in shadow (§5:248); θ_K is a WB-7 input (sourced per R3-6 item 1), not a WB-0 input.
6. LOW: WB-6 acceptance uses a read-path latch class (parse-REFUSE / schema-drift count) plus the quote-count floor; the `resting_query_unreadable` criterion moves to WB-8.
7. LOW: R3-4 (as replaced in R3-6) reads "119 PM.us markets listed incl. LOW (10-21 correction); recorder captures 84" instead of "5 × HIGH", and cites the tail-excess source as Card E / K1 SEARCH artefacts (`docs/evidence/STRAT_DESIGN_2026-10-31/`).
8. LOW: the §9 "KILL on 2027-01-25" risk row is struck; new risk row: "earlier start shortens the confirmatory window [max(07-01, F_K), F_H) — power re-check per R3-6 item 1 is mandatory".
