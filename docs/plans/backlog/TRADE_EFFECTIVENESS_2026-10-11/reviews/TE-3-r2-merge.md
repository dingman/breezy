# TE-3 r2 review merge — coordinator rulings (binding on r3)

Scores: domain 88 RWC · governance 84 RWC · codex 98 READY. No BLOCKERs. Every finding below is accepted.

0. **The band-semantics correction (`CORRECTION_2026-10-11_band_semantics.md`) is binding.** The NO side was 3 fills / 1 win / +0.65. Only MDW 09-22 won; MIA 09-15 NO LOST.
   - Rewrite §0, §1, §2 (the fills table), §9 and Appendix A §1 to match.
   - The anomaly is gone: P(≥1 of 3 | p=0.12) = 0.3185 (recompute it). The 0.039744 statistic is withdrawn.
   - Re-run the Appendix B census. The 2 rungs that reached take are unchanged; only their outcomes differ, and the census is outcome-free.
   - The ruling then says: "no motivating anomaly survives the corrected scoring; the ledger verdict stands on its own".
1. **Domain S1/S2 — scope the Lane-E corroboration to δ = 0.04.**
   - State the feasible cells honestly: at central, p0=0.07 δ≥0.06; at high, several δ≥0.05 cells.
   - State that dismissing those cells rests on §4 prior grounds only.
2. **Domain S3 — fix the Appendix A corner text.**
   - The exact test misses the backstop by 1 day.
   - The corner needs every entry at ask 0.06 and the 95% upper rate.
   - The band-pooled p0 is mixed, so the corner is not reachable.
   - Note the flooring of n_avail (S4). Appendix C uses the unrounded λ (S5).
3. **Governance F1 — add Appendix A §8 "what this does NOT decide".**
   - It does not dispose of the NO-side class for RA-13 §6.6/B-1, does not kill the NO-side requirement, and does not fire R4.
   - Arming, halts, caps, NO-SEND, Nautilus, `allow_short` and PREREG are all untouched.
4. **Governance F2 — rewrite trigger 2.**
   - It is a desk action available now: propose a successor-ruling candidate class to the WA-3 class table.
   - Size it only via K-2a §5 (bound_K, n_K, shared α). Exclude the 5 shared cities from the holdout. No PM.us n, bound or α is reused.
5. **Governance F3 — name the T-trigger.** Lane-E feasibility expires for any freeze after 2026-10-17. Triggers 1, 3 and 4 lapse at 2027-01-25.
6. **Governance F4 — quote both α cases in Appendix A §3 and in trigger 3:**
   - 0.05/4: n 1486.
   - 0.025/4: n≈1743, MDE 0.0754 at 490 and 0.0815 at 420.
   - Recompute both.
7. **Governance F5.** Trigger 3 states the bound at feasible n: ≈0.088 at 308 and ≈0.123 at 156.
8. **Governance F6.** WP-4 requirement 2 mandates reuse of `replay_sufficiency.decision_window_ns`.
9. **Governance F7/F8/F9.**
   - F7: say "`recompute_mde` desk recompute; intake would return …", and cite the 0.04 bound to H-NO-SIDE §3.
   - F8: add a one-line erratum that H-NO-SIDE's ≈1487 is 1486.
   - F9: a WP-4 re-plan re-opens py F4–F10 and arch G7/G8 as review inputs.
