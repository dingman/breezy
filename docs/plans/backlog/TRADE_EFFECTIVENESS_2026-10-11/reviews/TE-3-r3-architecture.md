**VERDICT: READY. SCORE: 93/100**

My r2 findings F1–F9 are all fixed. No BLOCKER or HIGH finding remains. Two MED wording defects remain in the ruling text. Neither changes the verdict, but they should be fixed when WP-2 saves the ruling.

| ID | Sev | Finding | Evidence file:line | Required change |
|---|---|---|---|---|
| G1 | MED | Appendix A §6 says "Lane-E feasibility expires for any freeze after 2026-10-17" with no scope. That date only applies to the δ = 0.04 corner (n 292 at λ_high). The ruling itself admits δ ≥ 0.05 cells at the high rate (§4), and some of those stay feasible much longer: p0 0.14, δ 0.08, exact n 145 at 3.153/day needs 46 days, so a freeze is feasible until about 12-02. The plan body (§8:228) is scoped correctly; the ruling text is not. | TE-3_r3:228 vs :314-315 and :302-304 | Change it to "Lane-E feasibility at δ = 0.04 expires for any freeze after 2026-10-17". Optionally add that the δ ≥ 0.05 cells are excluded on priors, not by expiry. |
| G2 | MED | Trigger 2 says to size the new class "only via K-2a §5 (bound_K, n_K, shared α)". The n_K formula at K-2a §5 is the normal fixed-σ form. WA-3 P4′ superseded it: Kalshi uses `recompute_mde_k` (Azuma–Hoeffding) and forbids fixed-σ normal critical values (WA-4 W15/W15a). My own F2 wording caused this. | K-2a r2:247; WA-3:244-251, :297; WA-4:417-476; TE-3_r3:224, :309-311 | Write "K-2a §5 as amended by WA-3 P4′ / WA-4 W15 (`recompute_mde_k`, Azuma; bound_K from the SEARCH cluster bootstrap; shared α totals)". |
| G3 | LOW | Trigger 3 says "outcome-free evidence". The precedent re-open route requires "outcome-free **pre-freeze** evidence" (RA-13 §1, citing RA-9 A-9). Under B-3, any post-freeze count spends CONFIRM days. | RA-13:18, :89-92; TE-3_r3:225, :311-312 | Add "pre-freeze". |
| G4 | LOW | Trigger 4 says "fires". Under R3V, a T-trigger counts only once a ruling records its evidence before the horizon; opening a plan does not count. | R3V:46-47; TE-3_r3:226 | Write "fires (recorded by ruling before 2027-01-25)". |
| G5 | LOW | WA-3 is a converged draft that will only be issued with the K-2b N-S START ruling, so a "successor ruling" to it is really an amendment to the draft before issue. Under the WA-3 F1 amendment, a new class also must not reserve Kalshi α before WB-7b. | WA-3:3, :147-150, :299 | Optionally add "(WA-3 binds as procedure pending issue; no Kalshi α reserved before WB-7b)". |

**My r2 findings:**
- **F1 (Appendix A §8 "does NOT decide"): RESOLVED.** It keeps the NO-side class open for RA-13 §6.6/B-1, does not kill the requirement, does not fire R4, and lists the untouched invariants. This matches RA-13 §5 and R3V §4.
- **F2 (trigger 2): RESOLVED**, apart from the sizing-reference drift in G2.
- **F3 (named T-trigger, expiries, lapse dates): RESOLVED.** I recomputed the dates by hand from the Appendix C formulas: 10-17, 10-13 and 10-23 are correct. G1 is about scope only.
- **F4 (both α cases): RESOLVED.** Both are quoted in §0, §3, §8 rows 1 and 3, and Appendix A §3 and §6.
- **F5–F9: RESOLVED.**

**Consistency with the binding rulings:**
- **RA-13:** consistent. It keeps the 2027-01-25 backstop firm under B-5, the B-3 firewall, and B-2 (no PM.us n, bound or α reused for Kalshi). It does not dispose of anything under B-1.
- **H-NO-SIDE:** consistent. The bound 0.04 is at H-NO-SIDE:85. The erratum (its ≈1487 is really 1486) is correct: (3.08302/0.08)² = 1485.16.
- **R3V:** consistent. The routes are R4 and FQ-v2 T1–T3, and K-2a is desk-only.
- **K-2a / WA-3:** MAX_HYPOTHESES_K = 3 and the L-12 successor-ruling rule match. Shared cities are excluded from the Kalshi holdout by default (K-2a:186; WA-3:98). The α totals are shared (K-2a:230).

**Premises checked:**
- P1 Ledger constants at `hypothesis_ledger.py` :177, :181, :192, :196; `recompute_mde` at :859; UNDERPOWERED branch ending at :1148: CONFIRMED.
- P2 `no_side_calibration_gate_cleared = False` at `config.py:247`; refusal at `decision.py:484-485`: CONFIRMED.
- P3 `decision_window_ns` at `replay_sufficiency.py:207`: CONFIRMED.
- P4 RA-13 :5 (FWER 0.025), B-1, B-2, B-3 and B-5: CONFIRMED.
- P5 R3V §3.2 T1–T3 and §3.3 K-2a desk-only: CONFIRMED.
- P6 WA-3 class table is full (KC-1..KC-3) and n_K uses the Azuma form: CONFIRMED. K-2a §5's normal-form n_K is superseded (G2).
- P7 H-NO-SIDE bound 0.04 (:85) and ≈1487 (:99), so the erratum is valid: CONFIRMED.

I did not read any M1-v3 outcome data.

Files reviewed:
- /home/jon/breezy/docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-3_plan_r3.md
- /home/jon/breezy/docs/plans/backlog/K-2a_2026-10-08/WA-3_ruling_draft.md
- /home/jon/breezy/docs/plans/backlog/K-2a_2026-10-08/WA-4_ledger_interface_spec.md
- /home/jon/breezy/docs/plans/backlog/K-2a_2026-10-08/K-2a_kalshi_plan_r2.md
- /home/jon/breezy/docs/evidence/RULING_RA-13_programme_kill_2026-09-27.md
- /home/jon/breezy/docs/evidence/RULING_R3-VIABILITY_NOT_VIABLE_2026-10-08.md
- /home/jon/breezy/docs/evidence/RULING_H-NO-SIDE-2026-09_horizon_2026-09-25.md