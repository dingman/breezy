# Review: BLOCKERS plan r1 — prediction-market-reviewer (domain math)
Verdict: REQUEST_CHANGES (no invariant breach; B2 and B5 each carry a domain defect; B3 and B4 need a one-line fix each)

## B1 — APPROVE
- [LOW] Section is a record, not work; fine. Risk (2) is the right caution. Add to "done": the E5 outcome (B5) will most likely be UNDERPOWERED (see B5), so state now that "done" may legitimately end at B4=NO / K-2.
- Over-engineering: none.

## B2 — REQUEST_CHANGES
Verified: `_stricter` = min(station-day, position) (maker_stage0_verdict.py:107-116), applied to base_rate/stress_rate at :215-216; `verdict_label` compares those to FILL_FLOOR (:269-278); `decide` uses them at :319. `r_lo` = `rates["stress_sd"].point` (:173-176), station-day. STAGE0_REPLAY_2026-10-16.md:79,81,131 agree (0.1364 SD vs 0.0814 position). Plan's claim "label=stricter, r_lo=station-day, no contradiction" is CORRECT.
- [HIGH] The plan stops one step short and so mis-closes the question. The real unit problem is downstream: S5 r3 §8 (S5_shadow_run_and_gates_plan_r3.md:284-296) uses a per-RUNG fill probability `r` (positions/day = 7.28·c·r; SD/day = 3.64·c·(1-(1-r)^2)), and E1 / `calendar_cap_date` feasibility is evaluated at `r_lo` (:296, "r_lo·c ≳ 0.115 at MAX_RUNGS=2 (positions bind)"). `r_lo` is a STATION-DAY rate. Feeding it as the per-position `r` overstates speed: the observed position rate is 0.0814 (k7/n86), and 1-(1-0.0814)^2 = 0.156 vs observed SD 0.1364 (implied r ≈ 0.071). At r=0.0814, k=2, days-to-300-positions = 300/(7.28*0.0814) ≈ 506 > cap; at r_lo=0.1364 the table reads ~300. A positions-bound feasibility gate must use `r_lo_position`, not `r_lo_station_day` (both exist per r4_delta:150-152).
- [MED] "No contradiction by design" should be recorded with this caveat; otherwise the NOTE certifies a unit that the freeze-day rule then misuses. Because E1 is frozen text I do NOT propose editing it (L-34); I propose the NOTE flags it and the freeze-day S-1 test is run at min(r_lo_position, implied-r from r_lo_station_day) by ruling BEFORE any result is seen (S2 block-2 not read until 11-04).
- Simpler alternative: fold the NOTE into the B4 ruling (one document instead of NOTE + ruling); the PROGRESS text fix stays. Over-engineering flag: Codex re-confirmation of six cited lines is not needed; I just did it (a reviewer pass suffices).

## B3 — APPROVE (decision), one edit
- Gate-9 arithmetic (SPEC:316-327 §6.9 "~12 expected losses at 300 positions", needs >=10): 12/300 = 0.04 mean model p_YES, so the pooled floor is 10/0.04 = 250 positions. It is NOT fixed: it is 10/mean(p_YES of FILLED episodes). Strata are 0.94-0.98+ p_NO (p_YES 0.02-0.06), so if the filled mean p_YES is 0.03 the floor is ~333 > 300. The plan's "about 250" is an upper-case optimistic figure. State it as 10/mean_p_YES, floor 250 only if mean p_YES >= 0.04.
- Rejecting the Kish/effective-n rule is RIGHT, for three reasons the plan understates: (1) realised design effect is computed from holdout outcomes (clustered fills), so a pre-11-08 rule that conditions the target on it is outcome-dependent unless it only fixes a formula, and SPEC §6.2/6.4 already bind 300 = 200 x 1.5 ceiling; (2) gate 9 counts raw pooled expected losses, not effective n, so the claimed ~20% saving is floored at ~250 (17%) and is zero if mean p_YES < 0.04; (3) it touches gate 2 semantics ("whichever binds", SPEC §6.4) which is a post-freeze-risk edit under L-34. Reject outright; do not park a named option with a deadline (a parked option is a pre-committed choice point visible after S2 results).
- [MED] SPEC §9.15 as quoted ("0.25 about 330", "0.3 -> 230-320") is a table of the same k=1/k=2 rows already in S5 §8; the v0.4 alignment is cosmetic and correct. But §9.15 also says "gate 2 needing 200 effective positions"; S5 §8 days are to 300 RAW positions. Align the unit in the same edit (still §9.15-only).
- Verify Doc A spec-sha pin (open Q5) before committing; plan already says so. Prefer: do not edit the spec at all until S2 evidence commit; the edit has no consumer before then. Simplest: write the corrected table in the B4 ruling and skip v0.4 (one fewer reviewed artefact).

## B4 — REQUEST_CHANGES (small)
- Open Q2 answer: HUNT-1:38 is a re-open trigger of the HUNT-1 ruling, bounded to the taker/off-window hunt. It does not define RA-13 R4. RA-13:53 defines R4 as "a new estimand that clears its power check at intake" and merely cites HUNT-1:38 as source. MAKER is not an hour-window hunt (it rests bids), so the literal "off-window hours" scoping is irrelevant to it; the operative test is the intake. Rule: the R4 criterion is "ledger intake returns REGISTERED"; HUNT-1's wording is not a second test. That resolves the judges' split without a debate.
- [HIGH] Therefore B4 is not independent of B5: R4 = REGISTERED. If B5 returns UNDERPOWERED_NOT_REGISTERED (likely, below), the ruling is mechanically NO. The plan treats B5 as "input, not a blocker" and pre-declares a YES branch that probably cannot occur. Merge B4+B5 into one ruling: "R4 requires REGISTERED; here is the dry-call result; therefore YES/NO." This removes one document and one calendar-row dependency.
- [MED] If NO: S2/S3 should still run (Q2 second half). They are already built, cost nothing, and give evidence for K-2 or a later T2; but state they cannot defer the KILL and cannot be cited as R4 (S5 r4_delta:53-58 already says so).
- [LOW] The pre-declared YES field list is over-specified for a branch that has no live path; keep only "counter + cap per L-38".
- Calendar rows are good; keep.

## B5 — REQUEST_CHANGES (answers open Q1)
Code facts verified: `register_hypothesis` pure (hypothesis_ledger.py:873); `recompute_mde` uses the module constant VARIANCE_BOUND only, "the ONLY admitted derivation" (:859-870; `mde_variance_bound` is checked at ~:1103 but NOT fed into the MDE); `mde_plausibility_bound` is a caller input compared at ~:1126 (`recomputed_mde > bound` -> UNDERPOWERED). My recompute with sigma=0.5: n=200: 0.1090 (a_v 0.0125), 0.1181, 0.1264; n=300: 0.089/0.096/0.103. Plan's figures are right.
- Q1 answer, outcome-free source for the bound: the SPEC §3 table (SPEC:142-147) of EV per contract at design win rate. Its maximum is EV +0.081 at w=0.94 (b=0.85), +0.041 at w=0.90; the break-even w* is 0.859. A "plausible effect size" is the best design-case EV, i.e. <= ~0.08 (and the realistic design point w=0.90 is ~0.04, the same 0.04 used for NO-SIDE, hypothesis_register.py:22-34). Pin bound = 0.08 (max of the table), stated before the call, per-contract dollars, no Stage-0 rate.
- Consequence (the important part): 0.08 < every MDE above (0.089-0.126), so the honest outcome is UNDERPOWERED_NOT_REGISTERED at both n=200 and n=300. Choosing bound >= 0.11 to pass would be exactly the gaming the plan's risk (1) names; the spec's own table cannot support it. Tell the plan: expect UNDERPOWERED, pre-declare it, and do not treat REGISTERED as the base case.
- Admissibility of MEAN_EXCESS_PER_TAKE with variance 0.25: ADMISSIBLE as a bound, VERY loose. The estimand for gate 3 is net expectancy per position (SPEC:311-313), and a per-contract net payoff on a binary contract has range <= 1, so Popoviciu gives var <= 0.25: valid. It is not a "win-rate" estimand; win rate (gate 1) is a point estimate only, not ledger-tested, so no mismatch. But real variance at w~0.9 is ~p(1-p)*range^2 ~ 0.09, so MDE is inflated ~1.7x; the ledger has no route to a tighter variance (justification param does not reach `recompute_mde`). Do not patch (plan agrees). Record that this makes MAKER structurally UNDERPOWERED at 200 station-days at ANY plausible effect, which is the actual finding for B4.
- Also: `mde_reference_ask` for a maker must be the design BID (cost basis), not an ask (`break_even` is ask-based, :850-857); record which value was passed and why. `existing_records` budget: MAX_HYPOTHESES=4 look-taking slots; check `programme_budget_remaining` BEFORE the call or the first outcome is a ProgrammeBudgetExhausted exception, not a status.
- Simpler alternative: the dry call is ~15 lines of arithmetic; run it as a scratchpad script and record the result in the merged B4 ruling. No separate E5_bound_pin and E5_dry_call notes: one dated file. Over-engineering flag: two notes + Codex dispatch for a deterministic pure function.

## B6 — APPROVE, one caution
- (a) LEAVE: sound; changing the sha-allowlisted drop-in is worse than the latent flag. Add one clause: note that the leaves-check/permit state must be re-read at any enablement ruling.
- (b) DEFER and document: correct. (c) none: correct.
- [LOW] Keep the three decisions as three PROGRESS lines; the extra "runbook note" is optional.

## Cross-cutting
- No invariant breach found: no gate, n, alpha, or date edited; no PREREG touched.
- Sequencing: do B5 (calc) BEFORE B4 and merge them; both before 2026-11-04. Nothing else depends on them.
- Missing blocker: the E1/S-1 unit issue in B2 (feasibility at the wrong unit) is the only decision that could change whether anything is frozen; it deserves a line in B4's ruling because the same ruling is the only outcome-free moment to fix the convention.
- Net: six sections with ~7 new documents is heavier than the mandate. Collapse to: (1) one ruling (B2 NOTE + B3 table + B4 + B5 result), (2) PROGRESS lines for B1/B6, (3) the PROGRESS row-2 text fix.

## Required edits
1. B2: add the E1/§8 unit finding (r_lo station-day used as per-position r) and require the freeze-day feasibility to name its unit before 11-04.
2. B3: state gate-9 floor as 10/mean(p_YES of filled) (250 only if >=0.04; ~333 at 0.03).
3. B3: reject the effective-n rule outright (outcome-dependent DE, raw gate 9, gate 2 semantics); drop the "named option with deadline".
4. B3: align "effective" vs "raw" positions wording within the §9.15-only diff, or skip v0.4 until after the S2 evidence commit.
5. B4: rule that R4 = ledger intake REGISTERED (RA-13:53); HUNT-1:38 is not a second test; MAKER is not an hour-window hunt.
6. B4: merge with B5; pre-declare that NO is the expected branch if E5 is UNDERPOWERED.
7. B4: state S2/S3 still run as evidence under NO.
8. B5: pin `mde_plausibility_bound` = 0.08 (max of SPEC:142-147 EV table), written before the call; pre-declare UNDERPOWERED as expected.
9. B5: record that variance 0.25 is a valid Popoviciu bound for expectancy but un-tightenable via the ledger; MEAN_EXCESS_PER_TAKE is admissible for gate 3 only.
10. B5: pass the design bid as `mde_reference_ask` and check `programme_budget_remaining` first.
11. Drop the separate E5_bound_pin and Codex dispatch; one dated evidence file.

## UNVERIFIED
- Whether Doc A pins the spec or verdict script by sha (open Q5); I did not find it in S2_RUN_PROCEDURE.
- The actual `programme_budget_remaining` on the live ledger and whether the S5 design sets `re_arm_gating` (v3 REGISTERED refusal, hypothesis_ledger.py:166).
- Mean p_YES of filled episodes (needed for the gate-9 floor); 0.04 is inferred from the spec's "~12 at 300".
- Exact line for the bound comparison (~:1126) and tolerance MDE_MISMATCH_TOLERANCE; I read the code in that region but did not execute it.
- Whether the E1 rule in S5 r3 §8 intends `r` as per-rung or station-day; the formulas imply per-rung, S2 r4_delta:150-152 exposes both units.
