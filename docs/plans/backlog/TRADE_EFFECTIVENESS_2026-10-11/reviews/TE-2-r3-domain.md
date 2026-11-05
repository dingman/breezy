VERDICT: READY, SCORE: 88/100

No BLOCKER or HIGH finding remains. The MED items below can be folded into `TE2_PREDECLARATION.json` and WP0 without another plan round.

**R2-1..R2-7 status**

| R2 | Status | Basis |
|---|---|---|
| R2-1 | Resolved | Test #11 covers BOUNDARY against BAND_SELECTION, #12 covers BOUNDARY against TAIL, #14 applies K7 per fill, and the classes apply to losing fills only. |
| R2-2 | Resolved | The leave-one-out, the P_c clamp, the "< 1e-12" print rule and the §0 statement on where the information gain lies are all present. |
| R2-3 | Mostly resolved | Ties are dropped, T-LOC is two-sided, and minimum attainable p with NOT-TESTABLE is added. Residual items are M1 and M2 below. |
| R2-4 | Resolved | The cluster T-SPREAD uses max-q (Fréchet), and attribution is stated as not identified. A detail remains in M5. |
| R2-5 | Resolved | |
| R2-6 | Resolved | |
| R2-7 | Partly | See M4. |

| ID | Sev | Finding | Evidence | Required change |
|---|---|---|---|---|
| M1 | MED | The S0-I "tie-free n" cannot be computed outcome-blind, because ties are `tmax == median` and Phase A has no `tmax_f`. The NOT-TESTABLE labels are therefore frozen on the cluster count alone. After ties are dropped in Phase B, n can fall below that count (for example, 7 to 6 for T-ART). A test labelled TESTABLE would then be untestable, and it would feed the VARIANCE rule's "TESTABLE secondary" clause. | plan §2 S0-I, rule 4 | Re-evaluate testability in Phase B on n after drops, by a rule declared in advance. Remove "tie-free" from S0-I. Add a test. |
| M2 | MED | The T-LOC null is muddled. Dropping zeros and using p = 0.5 "on the pmf's mid-rank convention" are two different nulls. For a skewed integer pmf, P(above \| not tied) is not 0.5, and a cluster-mean sign is not symmetric either. At 7 of 7 same sign with q around 0.6, the false-reject rate is about twice nominal. | §2 T-LOC | Pick one. Either use the per-day pmf-based null at the day level and collapse to clusters conservatively, or state that 0.5 is approximate and that T-LOC is "indicative, anticonservative-possible". Pin the choice in the predeclaration. |
| M3 | MED | It is unspecified whether a NOT-TESTABLE member stays in the Holm family. At 6 clusters T-LOC is NOT-TESTABLE (minimum p 0.031). If it stays in, T-SPREAD faces the step-1 threshold 0.01 instead of 0.02. `holm_correction` (`nbp_calibration.py:1670-1689`) uses k = len(p_values). Test #32 does not say. | §2, S0-I, #32 | Declare it: either drop NOT-TESTABLE members before Holm, or keep them with p = 1. State which, and apply the same rule in the 6-cluster sensitivity. |
| M4 | MED | Power is computed with the conservative max-P_c, which is a lower bound on cluster win probability. That bound is conservative for p-values but overstates power under H1-K, because W is stochastically smaller. The 0.8 VARIANCE gate can then pass wrongly. Separately, T-SPREAD is practically always TESTABLE (minimum p = Π q_c), so the "at least one TESTABLE secondary" clause is nearly vacuous, and T-SPREAD's power is unreported. | §2 power, rule 4 | Take power as the minimum over {max-P_c, independent-union P_c}. Report T-SPREAD power, or label VARIANCE "weak" when secondary power is unknown. |
| M5 | MED | The pmf behind T-SPREAD q and the mid-PIT is ambiguous when one station-day has fills at several cycles. These are different pmfs and different fills. It is not stated whether the day's q is the max over fills or over cycles, or whether A_c is per fill or per day. | §2 T-SPREAD, §3 | Pin it: pmf per fill's decision cycle, day-level q as the max over the day's fills, A_c as any fill in the cluster. |
| M6 | MED | The §0 expectation (lines 31-32, "T-WIN likely driven by one cluster") is stale r2 zero-win logic. With w_obs = 2 of 7 clusters, P(W ≤ 2) rejects only if the cluster P_c values are mostly ≳ 0.8. For example, LAX at 1 and the other six at 0.5 gives about 0.11. INCONCLUSIVE from non-rejection is the more likely outcome. Dropping LAX as a loss cluster can only raise the p-value (P(W≤2) ≤ P(W′≤2)). | §0 | Restate the expectation. State that w_obs is recomputed on the remaining clusters when the dropped cluster is a win cluster. State that the leave-one-out is not part of the α budget and can only block VARIANCE or label "single-cluster-driven". |
| M7 | LOW | The verdict "VARIANCE" and the class K9 "VARIANCE" share a name. There is no explicit test that SIBLING_WON precedes BOUNDARY (#13 covers only the losers-only rule). | §3, WP0 | Rename K9 to BODY_MISS. Extend #11 or #13 to pin the SIBLING_WON-first order. |

**Specific checks**
- **SIBLING_WON:** it is coherent and exclusive with BAND_SELECTION ("all lost"). Its consumer row is acceptable.
- **T-WIN as P(W ≤ w_obs):** correct. The cluster max-P_c lower bound is conservative for p. Minimum attainable p = P(W=0) is correct.
- **Verdict precedence at 7 and 6 clusters:** at 6 clusters T-ART and T-LOC become NOT-TESTABLE, so rule 3 gets the "secondaries NOT-TESTABLE" qualifier and rule 4 rests on T-SPREAD alone. Apart from M3 and M4 this is coherent.
- **Two-sided T-LOC:** the choice is justified. Its minimum p of 0.0156 can never pass Holm step 1 (0.01). It can reject only at step 2, after T-SPREAD rejects, and the plan should say so in the predeclaration.

**Premises checked**
- P5, `decision_link.py:213-214` `BackfillRefused`: CONFIRMED.
- P4/P5, `instrument_facts.py:72` `bucket_facts_from_instrument_id`: CONFIRMED.
- P8/P9, `nbp_calibration.py:273` `DEFAULT_SPLITS`: CONFIRMED.
- P2/§2, `nbp_calibration.py:1670` `holm_correction`: CONFIRMED. Thresholds are α/(k−rank).
- Not re-verified (r2-verified cites and the git-log claims in P7): P1, P3, P6, P7, P10–P16.