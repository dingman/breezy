# AUD-07 review — round 5 (delta) — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-07-exit-seam-arming-verification-path.md
sha256: d1d74b39caf8910d6be6473b28829489fd3ad239f2c998707bf1814d59599cc7
Round: 5 (delta review of the ruling application: RULING 3 + addendum A3; RULING_A1)

## Ruling application — verified faithful for the reclassifications

RULING 3 items 1-3 and addendum A3 are applied completely and correctly: PRECONDITION-1 (was
BLOCKER-1), DEP-2 (was BLOCKER-2, "operator-only hard gate" correctly struck since the positive
control is bot-automated per `OP_SEQ_BOT_POSITIVE_CONTROL_2026-09-04.md:7,118`, independently
confirmed present), DEP-3 (was BLOCKER-3, correctly downgraded to a registration-only sequencing
dependency). The authorisation chain (A3) is stated accurately: `pm_us_crh_exit_v4` is a new,
separately-manifested family, live-trading enablement stays operator-only. RULING_A1's "may not send
orders" consequence is applied honestly in the priority/timeline section (no date for arming, priority
stays P2 for the measurement loop, not softened into a false timeline). The DRAFT spec's existence
(`docs/specs/PREREG_v4_crh_exit_DRAFT_2026-09-16.md`) was independently re-verified: `Status:
DRAFT_NOT_REGISTERED (2026-09-16). D0 unpinned.` at `:3`, `d0_climate_day` **UNPINNED** at `:20`,
boundary re-run-and-pin instruction at `:116` — all exact, confirming step 7b correctly completes an
existing DRAFT rather than fabricating a second spec.

## A genuine, concrete defect found: the no-peeking check's date anchor is chronologically inverted

§6 E / §7 step 7b / AC #8b's new "checkable, not merely declared" mechanism requires every PREREG v4
provenance row's cited source date to be **strictly earlier than `corpus_first_fill_date`** — the
date field `§6 D` already defines as the exit corpus's earliest FILL. I checked this against the
plan's own facts: the plan states elsewhere (verified, both instances) that there have been **no fills
since 2026-09-15**, and the exit-window study has run "nightly since 09-17." `corpus_first_fill_date`
is therefore **≤ 2026-09-15** — a date that necessarily PRECEDES `POSITION_EXIT_EXECUTION_2026-09-16.md`
(2026-09-16), the very design document every inherited parameter cites as its provenance source.

**The check as specified would therefore FAIL on the real, live corpus** — the design doc (09-16)
*postdates* `corpus_first_fill_date` (≤09-15), which is exactly the condition the plan's own text
calls disqualifying: "a parameter whose cited source postdates the corpus could have been chosen with
the corpus in view." Applied literally, AC #8b would flag every inherited Rev-2 parameter as a
potential peek, even though RULING 3 item 2(a) explicitly blesses inheriting them with provenance.

**Why the anchor is the wrong date, and what it should be instead.** No-peeking is about whether the
design could have been informed by the *outcome data* it might tune toward — here, the R-THREAT/
R-DEAD verdicts the exit-window study computes for each held position, which can only exist AFTER a
position is filled and its subsequent price path is observed. `corpus_first_fill_date` marks when a
position was **opened**, not when its exit-signal **verdict** became computable or visible — those are
different events, and the fill date is *always* earlier than the verdict date by construction (a
verdict needs the fill first). Comparing the design date against the fill date therefore tests
nothing about peeking; it is a near-tautological failure for any corpus with fills before the design
doc, which is the normal, unremarkable case here. The chronology the plan's own text supports (design
doc 09-16, study reporting "nightly since 09-17") is consistent with genuine no-peeking — the design
predates the study's own reported readings — but the plan checks the wrong pair of dates to prove it.

This is not a trading-safety defect (nothing here touches order submission, cap values, or gates), but
it undermines the specific, newly-introduced claim this revision is proudest of ("checkable, not
merely declared"), and as literally specified would either produce a false failure or force silent
reinterpretation at implementation time — the exact "material design decision left to the implementer"
this review's brief tests for.

## Other coordinator questions, verified

- **N=5 readings kept strictly out of design:** YES. The attestation text is unambiguous — "no
  parameter, endpoint, boundary, window or firing threshold was chosen, tuned or justified against the
  N=5 exit corpus... The N=5 readings (R-DEAD 0/5, R-THREAT 1/5) are arming-gate reads, never design
  inputs." Correct and consistent with RULING 3's binding conditions.
- **"Corpus frozen" correctly reclassified as an arming-decision-only precondition:** YES, matches
  RULING 3 item 1 exactly, and both §4 and §12 state every measurement fix remains executable at N=5.
- **Priority/timeline honesty given the entry family may not send orders:** YES. The new "Priority
  honesty after the A1 ruling" section states plainly there is no date for the arming decision and
  explains why priority stays P2 rather than inflating urgency or silently keeping a stale timeline.

## Regression sweep

Checked AC numbering (`8`, `8b`, `9` — no collision), the BLOCKER→PRECONDITION/DEP renaming is applied
consistently everywhere the old names appeared (§4, §11, §12), and `exit_gate.py`'s empty-diff
invariant is restated, not weakened, everywhere arming is discussed. No other regression found.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **20** — both rulings applied completely; the DRAFT spec
  is correctly identified as already-existing rather than duplicated.
- Technical correctness and evidence grounding (20): **18** — every citation independently re-verified
  exact; 2 points withheld for the provenance-date check's inverted anchor (see required change).
- Implementation specificity and feasibility (15): **14** — 1 point withheld for the same defect: the
  anchor field named (`corpus_first_fill_date`) is the wrong field for what the check needs to prove.
- Acceptance criteria and validation quality (20): **18** — 2 points withheld because AC #8b, as
  specified, tests the wrong date relationship and would not reliably distinguish genuine no-peeking
  from peeking on this corpus.
- Autonomous operation, failure handling, recovery (15): **15** — unaffected by this revision.
- Portfolio objective alignment, scope, dependencies (10): **10** — unaffected; the priority-honesty
  addition strengthens rather than weakens this criterion.

**Total: 95/100**

## Remaining defect and required change

1. **MATERIAL (to this revision's new mechanism; not trading-safety-relevant).** §6 E / §7 step 7b /
   AC #8b's no-peeking check compares each provenance row's source date against `corpus_first_fill_date`
   (the exit corpus's earliest FILL date, ≤ 2026-09-15) — a date that necessarily precedes the design
   document (2026-09-16) by construction, making the stated check fail (or be meaningless) for the very
   parameters the ruling already blesses. **Required change:** redefine the check's anchor to the date
   the exit-window study first computed/reported an R-THREAT/R-DEAD reading for this corpus (e.g. a new
   or already-available `exit_window_study_first_report_date` field, consistent with the plan's own
   "nightly since 09-17" fact) rather than `corpus_first_fill_date`, and restate AC #8b and the RED test
   against the corrected field.

## Blockers / preconditions (not deductions)

- **PRECONDITION-1:** corpus growth and the arming decision depend on a future family trading —
  genuine, unavailable evidence, does not block this item's own fixes.
- **DEP-2:** PREREG v4 registration plus the bot-automated positive control, sequenced behind
  PRECONDITION-1 and registration — not an operator-only gate.
- **DEP-3:** registration-only sequencing behind AUD-06a's boundary conclusion.
- Live-trading enablement of `pm_us_crh_exit_v4` remains operator-only (addendum A3) — untouched by
  this item.
