# FQ-R8-2-UNDER-VETO plan r1 — peer-review merge

Date: 2026-10-08. Plan under review: `FQ-R8-2-UNDER-VETO_plan_r1.md`.
Reviewers, run blind to each other:

- **Architecture** (trading-bot-architect): SOUND-WITH-CAVEATS.
- **Domain/statistics** (prediction-market-reviewer): SOUND-WITH-CAVEATS. The domain reviewer read `cal025_full.json` only to confirm its figures and re-ran no MC.

**Disposition: r2 required.** Both reviewers endorse (b′) → (c′): an NP kill-screen first, then a single-shot A1b, with RULING_FQ-v2-NO-TRADE as the fallback. The reviews do not contradict each other. Every defect below goes into r2.

## Consolidated defects → r2 changes

| # | Sev | Source | Defect | r2 change |
|---|---|---|---|---|
| D-1 | HIGH | arch | Phase 1 is not mergeable now. Test 1 loads the frozen A1, which does not exist yet. | Split Phase 1. **1a** (now): docs steps 3–5, tests 2–4. **1b** (after the A1 freeze): test 1 and the F6b-cancelled row. |
| D-2 | HIGH | arch | A1b is not "ADD rules only". The checker's `_PAYLOADS`, `_AMENDMENT_FILENAME` and `_EARLIER` are closed maps. A2's `_EARLIER` must gain A1b, and A1b's child keys must differ from A1's. | Name the exact checker edits. Each closed-map edit widens by one reviewed row (L-12). Add a test that A1b keys are disjoint from A1 keys. Record the alternative (a pre-freeze A1 r4) as rejected, with the reason: A1 freezes as `unreachable_veto` on the evidence already run, and r4 would be a post-result redesign. |
| D-3 | HIGH | both | The terminal rule is keyed to ticks. If the realised rate is below `rate_cal`, t_K is never reached and L-38's "guaranteed to fire" is false. | Add a calendar backstop: the terminal veto fires at the earlier of t_K and the wall-clock date (≤ 2027-01-25 / max days armed). The **producer** enforces it, not a reviewer. Test it with an injected clock. |
| D-4 | HIGH | domain | D1 evaluates the NP bound at T_low, but candidates stop at t_K = 0.8·T_low. | Evaluate the bound at each candidate's t_K, or at the smallest t_K on the menu. |
| D-5 | MED | domain | D1 compares the bound to the bare G3 floor of 0.25. Group-sequential spending costs power. | Stage 0 passes only if the bound is ≥ 0.30, a pre-declared margin. Between 0.25 and 0.30 counts as FAIL → (c′). |
| D-6 | MED | domain | D1 is inconsistent: the 3b branch uses M-yes only, while `np_reach_cutoff_e` uses all mixes. | Define both on the same set: the minimum over the A1 r3 mixes. |
| D-7 | MED | domain | The rationale for using the H0 row is wrong. | Text: "H0 is one element of the composite null. An α-level rule for the composite null is α-level at H0, so the LR bound at H0 is valid." Remove "S4/S5 only lower power". |
| D-8 | MED | domain | Unit of analysis. Ticks within a day are correlated, and the rungs are mutually exclusive. | The LR and the look schedule use the daily Z_d units. Information fractions are Lan–DeMets null-known variance sums, not tick counts. Check Type-I at the realised counts. |
| D-9 | MED | domain | It is unconfirmed whether G3 is measured at T_low or at the realised N ≥ T_low. | Add a Stage 0 precondition: cite the line in the gate code that fixes the G3 horizon. If G3 is measured at N, evaluate the bound at N. |
| D-10 | MED | both | Winner's curse. Max-min selection over the menu also tolerates α ≤ α_floor + 3·SE, which allows a true α of about 0.109. | α is ≤ 0.10 as a point estimate, with a stated one-sided upper limit. The selected candidate is re-run on a **fresh seed** under the same gate. FAIL → (c′). |
| D-11 | MED | domain | The forced terminal veto has power 1 by construction. It would inflate G1/G3 if counted. | G1/G3 count only FAIL events strictly before t_K. Add a test that the forced veto is excluded. |
| D-12 | MED | both | The plan implies a PASS-able control. Under G-A, the design is a bounded pilot. Nothing after t_K is named. | State plainly: "FQ v2 under A1b is a bounded pilot of ≤ t_K ticks / ≤ calendar backstop. Loss is bounded by the exposure cap, not by the test." Name the post-t_K outcome: a terminal veto, with no bridge retirement by PASS. Any re-test is a new prereg. |
| D-13 | MED | arch | (c′) has no review or lapse date. | (c′) carries a review date, the earlier of 2027-01-25 and the next F5 epoch. |
| D-14 | MED | domain | "No loss control can be calibrated without v2 fills" is stated too broadly. | Scope the claim to the current AUT-5 pins (lineage-only fills, ≥30-fill minimum). List the fill-free alternatives — a conservative-rate drawdown, a bounded-exposure pilot (d1), shadow-tick rate pinning — each with the reason it was or wasn't chosen. |
| D-15 | LOW | arch | Under G-B, the row-7 L1 proof is a zero-fill proof. | State it. |
| D-16 | LOW | arch/domain | Menu size. Pocock K=4 is marginal (about 0.28) per the domain back-solve. | Drop menu item (iii). Drop K=4. The planning figures OBF K=2/3 ≈ 0.35–0.40 are labelled as Gaussian, not evidence. |
| D-17 | LOW | arch | The AUT-5a-owned test is in this plan. | Defer it to the row-7 WP. |
| D-18 | LOW | domain | The only evidence behind the plan is the 0.25 calibration run, and it is not recorded. | Add a one-line PROGRESS note: c ≈ 2.05, M-yes G3(−0.16) = 0.2104, seed 20261008, 10k replicates. |

## Ruling on the domain reviewer's "Stage −1: pin the mix"

The domain reviewer proposes deriving the live YES/NO mix from the frozen v2 design (`F5_prereg_v2_design.json` @072ab026) before Stage 0. If v2 is NO-heavy, M-yes may be infeasible and Phases 2/3a unnecessary.

**Accepted as a check, not as a lever.** The A1 r3 gate is min-over-mixes, and the M-yes failure is already known. Narrowing the mix set now is a post-result gate change unless the narrowing is **forced** by an artefact that predates the result. Ruling:

1. Stage −1 reads the frozen v2 design and the A1 r3 spec only. The tape and decision logs are corroboration and never a pin (the tape is not replay-sufficient).
2. M-yes may be dropped **only** if the frozen v2 design structurally excludes the YES-heavy mix, meaning a side or price rule makes it unreachable. A1b must cite that rule by file and sha.
3. Otherwise min-over-mixes stands unchanged, and Stage −1 records "no structural exclusion".
4. Either way, Stage −1's output is written down before Stage 0 runs.

## Agreements (no change)

- Freezing A1 as `unreachable_veto` is safe and mechanically well-defined. It proceeds independently of this plan.
- The deadlock core is right: with `unreachable_veto` there are no v2 fills, §R8-2(b) holds, and F-4 is inert.
- The NP bound is a valid necessary condition. It covers sequential rules, composite nulls, and mixture alternatives. It is not sufficient.
- F6b cancellation (replaced by a contract test), errata E-3 and the §R8-2(f) addendum stand.

## Next

The planner produces r2 applying D-1..D-18 and the Stage −1 ruling. Then a convergence check by both reviewers, scoped to the changed sections only.
