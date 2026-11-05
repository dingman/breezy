# AUD-15 round-8 delta review — trading-bot-architect

Plan: AUD-15-failing-study-units-fix-or-retire-and-alert.md
SHA256: 3b46e14d8e322887ad886f618d677f2c117b6c23e3d61beb3f7312bb52dc38b7
Round: 8 (delta, FINAL for this cluster)
Reviewer: trading-bot-architect (blind)

## Verified against source

`_CANDIDATE_UNITS` (`test_analysis_units_memory_capped.py:29-41`) and `_EXISTING_UNITS =
[name for name in _CANDIDATE_UNITS if (_DEPLOY_DIR / name).is_file()]` (`:43-45`) CONFIRMED exact
— this is the corrected citation for my own round-7 MINOR, now accurate. The three parametrized
tests the plan names as the falsifiable proof — `test_nightly_analysis_unit_has_a_memory_max
_ceiling` (`:102-110`), `..._memory_high_below_memory_max` (`:112-124`),
`..._cites_the_2026_09_11_k1_incident` (`:127-135`) — all confirmed at those lines (decorator-line
offset only). The ordering constraint (7d-bis's `_CANDIDATE_UNITS` entry only exercises once step
7a has written the unit file, because `_EXISTING_UNITS` filters on `is_file()`) is a correct,
independently-verifiable reading of the mechanism I confirmed in round 7.

## Round-7 required changes — both verified closed

1. **Mine (test-coverage decision).** §7 step 7d-bis now **decides** `breezy-asos-refresh.service`
   joins `_CANDIDATE_UNITS`, states why (it declares `MemoryHigh=512M`/`MemoryMax=1G` and nothing
   else pins them), orders it correctly behind 7a, and §8 item 14 makes the decision falsifiable —
   an entry present in the list but filtered out by `_EXISTING_UNITS` because the unit file wasn't
   written yet is explicitly named as **not** acceptance. This closes the gap completely, not
   partially: it answers the question I raised, rather than merely acknowledging it.
2. **Hunter's (silent-staling language).** §5/§6/§9's "ages silently"/"feeds an ever-older
   file"/"never raises the consumer's loud `SystemExit`" language is replaced throughout with the
   accurate shape (daily-rotating key ⇒ today's key missing ⇒ loud same-day `SystemExit`), and the
   13:30Z alert's value is re-grounded on lead time and unambiguous attribution rather than on a
   detection claim the corrected failure mode no longer supports. The provenance note
   (ruling §A1 predates the daily-rotation finding, strengthens rather than weakens the re-homing
   condition, ruling stands unedited) is accurate and appropriately scoped — it does not reopen or
   second-guess an ENDORSED ruling.

## The "not adopted" note — checked as instructed

My round-7 second MINOR (five non-pytest-enforced `docs/plans/*.md` narrative files still name the
retired units) was **not adopted**, with the reason: they are historical records of superseded
programmes, none is read by a test, rewriting them is outside this item's scope, and the live
inventory is `deploy/systemd/README.md`, which the plan does update. **This reason is acceptable**,
and on reflection my own round-7 deduction should not have been taken: I scored it "non-blocking"
and explicitly "not scored as material" in the same review, yet still withheld a fidelity point for
it without naming a required plan change — the same pattern this backlog's reconciliation rule
(applied earlier to AUD-13) exists to catch. Restoring it this round: the criterion is met as far
as this item's actual deliverable surface applies, and the stale-prose residual in unrelated
historical documents is correctly a note, not a defect.

## Defects

None found, MATERIAL or MINOR, in this revision's own new material. Both round-7 required changes
are genuinely and fully closed against source, not merely narrated as closed.

## Per-criterion scoring

| Criterion | Cap | Points | Rationale |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | Reconciled this round: the one prior deduction (doc-consistency MINOR) named no required change and is withdrawn per the "not adopted" reasoning being sound. |
| Technical correctness and evidence grounding | 20 | 20 | Every citation for both closed defects re-verified against source this session and correct, including the corrected `_CANDIDATE_UNITS`/`_EXISTING_UNITS` line ranges. |
| Implementation specificity and feasibility | 15 | 15 | The coverage decision is now fully specified: decided, ordered against step 7a, and proven exercised by named pytest node ids rather than merely present in a list. |
| Acceptance criteria and validation quality | 20 | 20 | Item 14's anti-vacuity clause (a filtered-out entry is not acceptance) closes the exact failure mode a less careful fix would have left open. |
| Autonomous operation, failure handling and recovery | 15 | 15 | Reconciled: my round-7 15/15→14/15 cell named no defect for the withheld point; the corrected failure-mode language (loud same-day `SystemExit` vs. silent staling) is, if anything, a strictly more accurate autonomous-detection story than round 7's. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unchanged. |
| **Total** | **100** | **100** | |

## Required changes

None.

## Blockers

None. Both fix-or-retire rulings remain RULED and peer-ENDORSED.
