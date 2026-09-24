# AUD-05 — Round 1 review (prediction-market-reviewer, portfolio accounting/risk lens)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-05-live-family-tally-unit.md
SHA256: 7bd5f1ee6d9802a4a97b75668e52fe120fe694b9953e2e11c52566facc7356e1
Round: 1
Reviewer: prediction-market-reviewer (independent, blind)

## Claims verified

- D-A raise site: CONFIRMED verbatim at `settlement/current_rung_hold_v2.py:414-419`
  (`build_stratum_v2` raises `ValueError("build_stratum_v2() is side-blind and refuses any row
  with side != 'yes' until it is made side-aware (fix-first review of 87278dd, item 3)")`).
- D-B raise site: CONFIRMED at `family_tally_v2.py:666-671`
  (`ValueError(f"filled_takes={filled_takes} is less than len(rows)={len(rows)}: …")`).
- D-D `trial_id_prefix` collision: CONFIRMED — both `deploy/families/pm_us_crh_v4.json:4` and
  `deploy/families/pm_us_crh_cont.json:4` read `"trial_id_prefix": "continuous_rung_hold/trial/"`,
  byte-identical as claimed.
- `filter_rows_to_manifest_prefix` behaviour (drop + refuse on store-declared-single-family
  contamination): CONFIRMED at `family_tally_v2.py:531-563`, matches the plan's description exactly
  including the `FamilyStoreContaminationError` path D-D's step-1 RED test relies on.

## Defects

No MATERIAL defect found from the portfolio-accounting/risk lens. This item does not size, price,
or move money — it repairs a measurement pipeline — so most of my domain checklist (edge vs fees,
Kelly sanity, no-lookahead, settlement math) is not directly engaged. I checked it anyway for the
one item in my remit that does apply here:

**MINOR — D-B's guard-preserving fix is directionally sound but the two competing causes are not
pre-ranked.**
File: AUD-05 §3 D-B, §7 step 0(b).
Issue: the plan correctly refuses to guess between (i) MP-A multi-fill collapse and (ii) `^no`
instrument-id mismatch, and defers to step-0 evidence — appropriate discipline. However neither
candidate cause is checked against the `DurableFillRecord`/`leg_of` structure this reviewer just
verified elsewhere in this audit round (NO-leg fills live on a distinct `^no` instrument id, never a
SELL of YES), which would let an implementer pre-narrow the search before running step 0. Not a
defect in the plan's correctness, only in its efficiency.
Fix (optional, non-blocking): cross-reference `symbology.leg_of`/`LEG_NO` in step 0(b) as the first
thing to check for cause (ii).

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): 18 — all of G-04 covered, plus D-D which G-04 did not name;
  R-4 correctly deferred to BLOCKER-2 rather than silently resolved.
- Technical correctness and evidence grounding (20): 18 — both failure tracebacks and the prefix
  collision verified byte-for-byte against live source; this is unusually well-grounded evidence.
- Implementation specificity and feasibility (15): 11 — seams named; D-A's exact `StratumRow`
  field-level fix is left for the implementer to size (author-conceded).
- Acceptance criteria and validation quality (20): 17 — measurable, guard-preservation explicitly
  tested; AC #4's live half is honestly unschedulable given no fills since 09-15.
- Autonomous operation, failure handling, recovery (15): 11 — names the real defect (3 days silent
  failure) and ties it to alert delivery, but leaves the wiring choice open.
- Portfolio objective alignment, scope, dependencies (10): 5 — correctly scoped, contribution to ROI
  is honestly epistemic/indirect, not overstated.

**Total: 80/100**

## Required changes to reach 100

1. Pin one concrete D-A fix location (field-level) rather than "per-leg terminal-state handling".
2. Resolve the alert-wiring choice to one option instead of two.
3. (Optional) cross-reference `leg_of`/`LEG_NO` in step 0(b) to pre-narrow D-B's cause.

## Blockers

BLOCKER-1 and BLOCKER-2 are correctly named as strategy-lead/PREREG-authority rulings this plan
cannot and does not decide (re-issuing a REGISTERED family's `trial_id_prefix`; retiring
`pm_us_crh_cont`). These are genuine blockers, not scoring waivers — the plan is executable up to
them and correctly stops there.
