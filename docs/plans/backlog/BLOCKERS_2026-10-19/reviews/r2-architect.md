# Review: BLOCKERS plan r2 (architect)

**Verdict: APPROVE.** r2 converges. All four findings below are LOW or MED, none blocks, and each can be fixed in the ruling text without another plan round.

## 1. My r1 findings: what happened to them
All nine of my required edits were applied:
- **B3:** spec v0.4 is dropped and the ≈250 floor is restated as 10/mean(p_YES).
- **B4:** it rules on RA-13:53's literal text, the R4 event is a REGISTERED record via `register_and_persist`, YES is void after 2027-01-24, the deadline is before 2026-11-04, there is no duplicate 01-25 row, and day-60 is cited by formula.
- **B5:** one call with k=1 and α=0.025.
- **Sequencing:** B5 runs before B4.
- **B1:** the PROGRESS line is the only completion criterion.

I accept both of Grok's rejected items. Under UNDERPOWERED, the HUNT-1:38 reading and the literal reading agree on NO. And B4 waiting on B5 costs nothing, because B5 uses no outcome. I dispute nothing.

## 2. B5 pins (checked against HEAD)
- **Signature and constants:** the kwarg names match `register_hypothesis` (`hypothesis_ledger.py:873-899`). The fixed constants match `:192-212`: POWER 0.80, VARIANCE_BOUND 0.25, θ 0.0695, leg share 0.20, MEAN_EXCESS_PER_TAKE, order_quantity 1.
- **α:** an override of 0.025 is a legal narrowing (`:957-964`). The split is 0.025/4/1 = 0.00625 (`:1114-1115`).
- **MDE:** (2.4977 + 0.8416)·0.5/√200 = 0.1181, which matches T4's 0.0964 at n=300.
- **Status logic:** status depends only on whether `recomputed_mde > mde_plausibility_bound` (`:1125`). The ask and slippage are recorded only (`:1139-1141`).
- **Schema:** with no strata and no horizon the record is schema v1, and the v2/v3 refusals at `:1159-1184` cannot fire.
- **Table cells:** `SPEC_pm_us_no_ladder_maker_2026-10-12.md:146` gives b=0.80 as +0.039 / +0.089 / +0.129. So w=0.90 nets 0.079 and w=0.94 nets 0.119, as the plan says. The plan's correction is right: 0.081 is the b=0.85 row, and the table maximum is 0.225.
- **Units:** they match. BE at `:851-856` is a + θa(1−a) + slip, which is the SPEC:140 EV less slippage.

**Endorsement (required): the w=0.90, b=0.80 cell, giving a bound of 0.08.**
- w=0.94 equals P_MIN, the lowest p_NO the model will bid at. Using it assumes perfect tail calibration and zero adverse selection, which is the spec's own named falsifier (SPEC:49-52). The spec also treats observed 0.85–0.91 as the realistic range (SPEC:149-154).
- Outcome-free cross-check: the spec's own E_MIN of 0.10, net of slippage, is 0.09. That is also below 0.1181. Every bound short of the zero-adverse-selection cell returns UNDERPOWERED, so the verdict does not depend on which cell is picked. Only the one optimistic cell flips it, by 0.0009.

## 3. B2 convention
- **The inversion is correct.** §8 (`S5_shadow_run_and_gates_plan_r3.md:282`) gives station-days/day = 3.64·c·(1−(1−r)²). Solving for r gives r = 1−√(1−s).
- **It is never less strict.** Taking min(·,·) gives a value ≤ each input, and E1 fires S-1 when r·c < 0.115. So S-1 can only fire at least as often, never less. Rung fills are positively correlated, so the independence the formula assumes makes 1−√(1−s) an underestimate of r, which is again the conservative direction.
- **It can only fire stricter against block 1 too.** Block-1 numbers are already visible, so a looser convention would be a post-result rescue. A stricter-only rule cannot be.
- **Caveat (finding 1):** the inversion only holds at MAX_RUNGS=2. At MAX_RUNGS=1, §8 says r = s, so the inverted form is over-strict there.

## 4 and 5. Simplicity and invariants
- **Simplicity:** one stray item (finding 2). Otherwise the plan is minimal: one ruling, PROGRESS lines, and one dry call with no new tool.
- **Invariants:** no breach found.
  - No PREREG edit and no date moves.
  - No change to enablement or the drop-in.
  - No operator-reserved values are assigned.
  - The E1 convention is ruled before any block-2 result, and its direction is stricter-only.
  - B5 reads a copy of the ledger, with the sha recorded before and after.

## Findings
1. **[MED]** `plan_r2.md:47`: the convention is stated without a MAX_RUNGS scope. **Fix:** "at MAX_RUNGS=2, r = min(r_lo_position, 1−√(1−r_lo_station_day)); at MAX_RUNGS=1, r = min(r_lo_position, r_lo_station_day), per §8:283."
2. **[LOW]** `plan_r2.md:5` and `:188`: Scope says there are "exactly three" deliverables, but B6(b) adds a `deploy/systemd/README.md` sentence. **Fix:** list it as part of deliverable 2, or drop it, since the PROGRESS line already records the paths.
3. **[LOW]** `plan_r2.md:126`: the list of outcome exceptions leaves out `DuplicateHypothesisIdError` (`:943-946`), which is raised before any power check if the id already exists in the ledger. **Fix:** add it to the step-7 list.
4. **[LOW]** `plan_r2.md:92`: "`pm_us_no_ladder_maker` (dry)" does not say whether "(dry)" is part of the string. **Fix:** pin the exact `hypothesis_class` string in the ruling's commit-1 pin table.

## UNVERIFIED
- I could not determine the denominator S2 uses for `r_lo_position` ("position/rung_trial", `S2_stage0_replay_plan_r4_delta.md:146`). If it is per placed rung under MAX_RUNGS=2, it is directly comparable with §8's r.
- RA-9 A-3 text against the v1 REGISTERED path. The code does not block a v1 REGISTERED record (only v2 and v3 are refused at `:1159-1184`). This matters only on YES, and the plan already lists it as unverified.
