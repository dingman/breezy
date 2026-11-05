# Independent audit — why Breezy runs in circles (2026-10-22)

Peers: prediction-market-reviewer (quant), trading-bot-architect (execution trace),
polymarket-us-discovery (live venue, 78 read-only GETs), Grok ×2 (meteorology;
process). Cross-challenge round: quant and execution re-tasked against each other's
claims; Grok devil's advocate argued for an edge. Codex not used. Read-only; no
orders. Raw peer reports: session scratchpad `1669e377-…/scratchpad/` (ephemeral).

## Verdict
Primary failure = **strategy edge**, compounded by **development process**. Data,
harness and execution are not the binding constraint. The market prices public NWS
data at least as well as Breezy; the only residual inefficiency is longshot
overround — a maker/microstructure play, unproven and small on this venue.

## Proven
1. Taker falsified live: 34 bot fills, 4 wins, −2.63 (−41% of cost); market-implied
   expected wins Σprice = 6.36 vs 4 observed. 31/34 cheap YES. Wins were luck.
   MIA 09-13 was a win (balance +0.29, `FU-3_capital_flow_attribution_2026-09-26.md:12`)
   despite the venue `realized` field showing 0.
2. End-to-end trace LAX 10-05 `lt97f` YES @0.64: decision→fill ≈120 ms
   (`logs/breezy-trade-20261004T165012Z.log` L1571–1589); p_hat 0.992; CLI 101 °F vs
   q50 92 °F; same heat event lost LAX 10-02..10-06. Failure is at the SIGNAL.
3. Maker-sharp 17/17 is a nomination: ≥6 arms on one 92 station-day tape
   (`MAKER_sharp_v1_leakage_audit_2026-10-21.md`); one-sided 95% LB 0.839 < breakeven
   0.865–0.888; `summary.json` says 17 fills but 20 episodes carry `filled_ns_base`;
   simulator has no placement latency (4 fills < 10 s after post, min 0.054 s);
   fills are BUYER-aggressor prints (`maker_stage0_fill_pass.py:_on_print`).
4. Venue 2026-10-22: 119 markets, 16 temperature ladders (PHL HIGH, NYC/MDW LOW not in
   registry); `feeCoefficient` 0.0695; Σ YES best asks 1.05–1.22; D0 ladder notional
   ≈ $0.4–2.6k/day; IOC proven; GTD rest/cancel/cancel-all proven only at $0.01 for
   540 s (B2 `maker_positive_control_20261022T075159Z.json`); maker rebate sign and
   fill behaviour unproven. Ceiling ≈ $10–65/month even with an edge.
5. Process: 2,568 commits since 08-22, 89% after the 09-02 no-edge memo; 978 plan
   files, 829 evidence files, 56 rulings, 111 worktrees; edge logic ≈0.3% of 187k src
   LOC; ~40 gates signal→order on `arm/integration`, built after Stage 0 said
   UNDERPOWERED.
6. Shadow produces no evidence: orders-off ⇒ `outside_permit_window` before pricing
   (`fq_funnel_2026-10-21.jsonl`: 832,479 refusals, 0 takes). Intended, but wasted.

## Hypotheses
- NBP vs venue price never scored (09-20 ruling scored NBS TXN).
- Maker fills may be adverse-selection sweeps (MIA 09-22 fill inside a 0.15→0.25 YES staircase).
- 9 sports DAY-order trades on the account (−5.40) are not Breezy's.
- Residual ≈$2.40 bot-DB vs venue gap = trades before 09-11.

## Shortest credible path (adopted as the backlog 2026-10-22)
1. Reconcile the maker replay + latency + adverse-selection test.
2. NBP vs venue mid paired Murphy resolution.
3. 2-hour GTD venue probe.
4. Live qty-1 maker test on one frozen rule, stop at 40 fills.
5. Scale decision only if 4 passes.
