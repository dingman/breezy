# CORRECTION (binding on every TE plan revision from r3 / TE-1 r2 review onward)

The audit's hand re-score treated `gte{A}lt{B}f` as half-open [A,B). The settlement-grade rule is INCLUSIVE [A,B] (`THRESHOLD_SEMANTICS_2026-08-25.md` §4.2; `symbology.slug_closed_interval`; `bucket_facts_from_instrument_id`). `lt{B}` = tmax ≤ B−1; `gte{A}` = tmax ≥ A. The bot's scorer is correct.

Corrected facts (`docs/evidence/TRADE_EFFECTIVENESS_2026-10-11.md`, re-scored with the inclusive rule):
- Total 34 fills, **4 wins, net −2.63**, cost 6.36, fees 0.27.
- Sep 9/2/−0.46. The official 09-30 artifact agrees FILL BY FILL. TE-1 r2 P19's two "disagreements" (MIA 09-13 YES won +0.30; MIA 09-15 NO lost −0.09) are the bot being RIGHT. There is no coincidental cancellation.
- Oct FQ **25 fills / 2 wins / −2.17**. Wins: 10-03 MIA `gte86lt87` (tmax 87, +0.88) and 10-05 MIA `gte89lt90` (tmax 90, +0.50).
- NO side **3 fills / 1 win / +0.65**. Only MDW 09-22 won. MIA 09-15 NO lost (tmax 93 ∈ [92,93]). YES side 31 fills / 3 wins.
- The "five 1 °F losses" list is WITHDRAWN. It was computed with the wrong rule. Any edge-distance figure must be recomputed by the plan's own script through `bucket_facts_from_instrument_id`.

Consequences:
- **TE-1:** live-proof targets become 4 wins / −2.63 / FQ −2.17 / crh −0.46. P19 and the S0-5 (ii) STOP collapse. S0-5 becomes "confirm the legacy store agrees with the corrections-aware CLI final for all 9" (positive control: MIA 09-13 and MIA 09-15 upper-edge cases).
- **TE-2:** 2/25, not 0/25. Every "0 wins" / "five 1 °F" premise is restated. T-WIN's zero-win formula Π(1−P_c) generalises to the exact Poisson-binomial lower tail P(W ≤ 2). The edge_dist and BOUNDARY definitions must use the inclusive interval. Test fixtures must include the upper-edge-inclusive case.
- **TE-3:** the motivating anomaly is gone. 1/3 NO wins at p≈0.12 gives P(≥1 of 3) ≈ 0.32, which is unremarkable. The ruling's §1 must state this. The verdict (UNDERPOWERED_NOT_REGISTERED on the ledger basis) is unchanged and needs no anomaly.
