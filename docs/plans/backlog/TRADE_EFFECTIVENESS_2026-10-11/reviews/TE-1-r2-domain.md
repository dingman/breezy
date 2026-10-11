VERDICT: READY-WITH-CHANGES
SCORE: 86/100

I reproduced the corrected targets independently. The reproduction script read the fill store and `truth_cli_finals.csv` read-only. It used `bucket_facts_from_instrument_id(...).contains()` with `^no` inversion and `pnl = payoff - cumulativeCost - cumulativeFee`. I did not call `score_trial` itself, so Stage 0 still has to exercise that path. Results: 34 fills, 4 wins, net −2.63, cost 6.36, fees 0.27. September is 9 fills and −0.46. October is 25 fills and −2.17, with wins on MIA 10-03 and MIA 10-05. NO side is 3 fills and +0.65. No fill in these 34 carries `correction_flag` true.

The September decomposition now closes. The 7 scored fills sum to −0.54. The 2 residual fills (SFO 09-11 −0.22, MIA 09-13 +0.30) sum to +0.08. Both residuals are the `feeReconciled=false` fills. So P18 holds, and r1 F3 is resolved because the "coincidence" never existed.

| ID | Sev | Finding | Evidence | Required change |
|---|---|---|---|---|
| N1 | HIGH | Live-proof 2 and the S0-5(ii) STOP encode wrong numbers. Run as written, the plan STOPs on correct behaviour. It expects −4.63 with 2 wins, FQ −4.17 and crh deltas of ±1.00. | r2 `:64,87,117-118,285-296` | Targets become 34 / 4 wins / −2.63, FQ −2.17, crh −0.46 (booked equals CLI-final), fees 0.27. Expect `n_settlement_disagree=0`, and the identity Σ DISAGREE = 0. |
| N2 | HIGH | P19 is false and must be deleted. Four other places depend on it: the "Changes" row for dom F3 (`:30`), R3's last bullet "−4.63 reproduces" (`:87`), the Risks bullet citing P19 (`:274`), and the non-goal "FQ 0/25" (`:309`). | as listed | Fix all four. The non-goal becomes "FQ 2/25". Reword the P1/P19 risk as hypothetical, since TE-1b is triggered only if S0-5 finds a real correction. |
| N3 | MED | S0-5 should become "legacy store agrees with the corrections-aware CLI final for all 9", with positive controls MIA 09-13 (tmax 92, YES wins) and MIA 09-15 NO (tmax 93, NO loses). | `:114-119` | Rewrite S0-5. Keep the DISAGREE/WARN machinery, but test it with a synthetic correction fixture, since live data has no disagreement. |
| N4 | MED | `test_recipe_fixture_reproduces` is built "from the audit recipe". The hand-rolled recipe is what produced the wrong rule. | `:210` | Derive expected values through `bucket_facts_from_instrument_id`, never a re-implemented band. Add upper-edge-inclusive fixtures for both YES and `^no`, and a single-token `ltB` fixture. State that `cli_final_check` uses `score_trial` and the same band function. |
| N5 | MED | The correction text says "`lt{B}` = tmax ≤ B−1". That is true only for the single-token `ltB` family. The two-token `gte{A}lt{B}` is `[A,B]` inclusive (`symbology.py:483-497`). Fixtures written from the correction's sentence would be wrong. | `symbology.py:495-497`; my run shows `gte91lt92` winning at tmax 92 | r3 should state both families explicitly. |
| N6 | MED | The fee-0 caveat on the residual fills is lost. MIA 09-13 is now a winner, so booking it at fee 0 flatters +0.30 by about 0.01–0.02. SFO is similar. The modelled delta stays Markdown-only (FU-3d), so a JSON reviewer cannot see it. | `:83`, `:295` | Say in proof 2 that totals are at the recorded fee, with `n_fee_unverified=2` and the Markdown disclosure delta cited. |
| N7 | LOW | `cli_final_check` is tautological for C2 rows unless it compares the booked `settlement_tmax_f` with a fresh corrections-aware read. The `UNPRICED` status trigger is undefined. | `:170,178` | State the comparison. Define the trigger for every status, and require null (not 0) `win`/`payout` for non-settled rows. |
| N8 | LOW | Proof 1 says `LAG_BACKLOG n=25`. The legacy fills also pre-date activation, so n is ambiguous. | `:286` | Define what n counts, or expect 34. |

Premises checked:
- Your r1 findings: F1 resolved by R3 (recorded fee plus `fee_unverified`). F2 is partly resolved (see N6). F3 resolved. F4 resolved by R1. F5 resolved by R6. F6 resolved (`SETTLED_NWS_IMPLIED` plus the NO-leg test). F7 resolved (S0-11 and the venue-positions disclosure). F8 resolved (S0-3 corrections-aware).
- P18: CONFIRMED. The two residual fills are the two fee-0 fills, with +0.08 = −0.22 + 0.30.
- P19: WRONG. The bot is right on both MIA cases.
- P10, R3 (the FQ unreconciled path), `fq_scorer.py:419-458`: CONFIRMED. `_realized` returns None when the fee is unreconciled, and UNATTRIBUTED is decided before FEE_UNRECONCILED.
- R1 and R6: sound. Legacy label rows (`LEGACY_SCORER_ID`) are excluded, which avoids the double count. The `GATED_ACCOUNTING_ONLY` trigger fires only on the 25 FQ fills.
- P1–P9, P13–P16 and P20–P22: not re-verified (outside my lens).

Relevant files:
- /home/jon/breezy/docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-1_plan_r2.md
- /home/jon/breezy/src/breezy/analysis/labeling/fq_scorer.py
- /home/jon/breezy/src/breezy/analysis/labeling/instrument_facts.py
- /home/jon/breezy/src/breezy/adapters/polymarket_us/symbology.py