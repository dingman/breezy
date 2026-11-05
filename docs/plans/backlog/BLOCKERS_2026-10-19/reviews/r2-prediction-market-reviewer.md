# Review r2: BLOCKERS plan r2 - prediction-market-reviewer (domain math, READ-ONLY)
Verdict: APPROVE (with 3 minimal wording fixes below; no CRITICAL/HIGH; no invariant breach)

## Item 1 - my r1 findings
- E1/§8 unit (r1 B2 HIGH): APPLIED correctly (plan_r2.md:44-47), ruled before block 2, E1 text untouched.
- Gate-9 floor 10/mean(p_YES), 250 only if >= 0.04, ~333 at 0.03 (r1 B3): APPLIED (:69).
- Effective-n rejected outright, no parked option (r1 B3): APPLIED (:62-67).
- R4 == intake REGISTERED, HUNT-1:38 not a second test (r1 B4): APPLIED (:144-149); S2/S3 still run, cannot be cited as R4 (:154).
- B4+B5 merged into one ruling, UNDERPOWERED pre-declared (r1 B4/B5): APPLIED (:19-20).
- Design bid as mde_reference_ask, budget checked first, variance 0.25 admissible-but-loose: APPLIED (:98,125,247).
- Bound 0.08 "= table maximum" (my r1 claim, SPEC:142-147): WITHDRAWN by me. r2's correction is right: the 0.081 cell is b=0.85, a bid B_CAP 0.80 forbids; the max is +0.225 (SPEC:143). I had read the wrong row.
- Disputed: none. Rejections of Grok ("YES only if off-window", "B4 must not wait on B5", override=None) are reasoned and I accept all three; programme_alpha_override=0.025 only narrows 0.05 (ledger docstring: override may only narrow), so it is admissible.

## Item 2 - B5 pins at HEAD (hypothesis_ledger.py)
Verified: signature :873-899 has every kwarg listed; PROGRAMME_ALPHA 0.05 :177, MAX_HYPOTHESES 4 :181, POWER 0.80 :192, VARIANCE_BOUND 0.25 :196, EVIDENCED_FEE_THETA 0.0695 :204, MDE_MISMATCH_TOLERANCE 1e-4 :216, both LANDED flags False (:166,:174). Status test is `recomputed_mde > mde_plausibility_bound` (~:1125) so ask/slippage are recorded only.
Independent recompute: (z(0.99375)+z(0.80))*0.5/sqrt(200) = 0.118063; pinned 0.1181 is 3.7e-5 off, inside 1e-4, but see finding 2.
SPEC table recheck (SPEC:142-147): b=0.80 row EV +0.089 @0.90, +0.129 @0.94; fee 0.0111 = 0.0695*0.16. Units equal to MEAN_EXCESS_PER_TAKE minus slippage: correct.
Cell endorsement (required before the call):
- I ENDORSE b=0.80, w=0.90, net of 0.01 slippage = 0.079, pinned 0.08. Outcome-free (spec table only), the bid is the one the design places (B_CAP), and 0.90 is the spec's own mid-column.
- I do NOT endorse w=0.94 (0.119): it is a knife-edge 0.0009 above the MDE, equals P_MIN so it assumes zero adverse selection, which SPEC:49-52 names as the falsifier. Selecting it purely to REGISTER would be the gaming r2 risk 1 names.
- Both cells are chosen with the MDE known (disclosed); the pre-call commit plus this endorsement is the mitigation. Even w=0.92 (0.099) and w=0.93 (0.109) stay UNDERPOWERED, so the outcome is robust to any defensible rounding. Rounding 0.079 to 0.08 is immaterial.

## Item 3 - B2 convention r = min(r_lo_position, 1 - sqrt(1 - r_lo_station_day))
- Inversion: CORRECT for MAX_RUNGS=2. §8 (S5_...r3.md:282-283): station-days/day = 3.64*c*(1-(1-r)^2), so s = 1-(1-r)^2 gives r = 1 - sqrt(1-s). Positions/day = 7.28*c*r uses per-rung r, matching r_lo_position.
- Direction: 1-sqrt(1-s) <= s for s in [0,1], so the implied r never exceeds r_lo_station_day; min() of two non-negatives never exceeds either. E1 needs r*c >= 0.115 (:296) with S-1 below it, so a smaller r can only fire S-1 earlier or equal, never later, than either the plain station-day reading or the position reading alone. Correct. It cannot make a freeze that the plain rule would reject.
- Gap (minor): the formula is stated for MAX_RUNGS=2 only. At MAX_RUNGS=1 (:281) station-days = positions = 3.64*c*r, so the inversion is the identity (1-(1-r)^1 = r) and the convention must read r = min(r_lo_position, r_lo_station_day). State both cases so the freeze-day reader does not apply sqrt to k=1.
- Also state that c is applied after r (r*c vs 0.115), as in :296.

## Findings (numbered, minimal fixes)
1. plan_r2.md:47 - convention is MAX_RUNGS=2 only; add "MAX_RUNGS=1: r = min(r_lo_position, r_lo_station_day)".
2. plan_r2.md:97 - pin `mde_at_allocated_alpha` as the full-precision `recompute_mde(...)` value (0.118063...), not the 4-decimal 0.1181, to keep the 1e-4 tolerance (:216) from being the only margin.
3. plan_r2.md:90-102 - table omits `existing_records` (the scratchpad-copy read) and `disposition="NORMAL"` (default); list both so the pinned kwargs are the complete call.
4. plan_r2.md:101,113 - write "0.079 rounded to 0.08" in the pin cell itself, and record this review's endorsement of the b=0.80,w=0.90 cell in the ruling draft before Commit 1.
5. plan_r2.md:19,121-127 - simplicity: one pure function call does not need Grok AND python-reviewer AND a bespoke script; keep python-reviewer's independent re-derivation (:127) and let Grok run only the call, or run it from one agent, to avoid two dispatches for ~15 lines.
6. plan_r2.md:158 - UNVERIFIED RA-9 A-3 note is already correct: the ledger docstring says v2 refuses REGISTERED, and v3 is refused while the flags are False; no change, but on YES the constants row must also decide v1 vs v3 (already stated).
7. plan_r2.md:182 - 12-31 allowlist-expiry row is hygiene, not blocker work; acceptable as one calendar row, no further doc.

## Item 4 - simplicity
Three deliverables and one conditional code row is the minimum I can support. Only extra weight is finding 5. Review-disposition table is long but is the audit trail the pins rely on.

## Item 5 - invariants
No PREREG edit, no date moved (11-04..11-15, 2027-01-25 intact), no post-result gate change (all pins precede any block-2 number), no enablement or operator-reserved value assigned, no ledger write (copy read, sha before/after). One caution: the bound is chosen knowing the MDE; this is disclosed and, per the robustness note above, does not change the outcome.

## UNVERIFIED
- programme_budget_remaining on the live ledger (call records it).
- Whether the S5 design sets re_arm_gating (v3) - only matters on YES.
- Whether r_lo_position is per-rung under MAX_RUNGS=2 as §8 assumes (r4_delta:150-152 labels it "position" unit; I read it as per-rung trial).
