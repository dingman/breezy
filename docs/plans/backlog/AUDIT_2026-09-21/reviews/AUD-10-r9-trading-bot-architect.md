# AUD-10 — Review record (Round 9, delta on the in-place-edited final revision)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: a980ce3214ea2731b799e80373d69d7dcbfa01aea982b836dc69e2732ac63f0e
- Round: 9 · Reviewer: trading-bot-architect (promotion-gate/risk-architecture lens)
- Total: 100/100 (readiness/self-score text ignored per instruction)

## Round-8 MATERIAL defect (self-lifting PROVISIONAL tag) — genuinely fixed, more conservatively than required

§6b.3 now states the generator **never** lifts its own tag: the ruling's no-`INERT` condition is
"necessary, but not self-certifying." Every artefact emitted while PROVISIONAL — `criteria.json`,
`RATIONALE.md`, any `PROPOSAL` — carries `criteria_status: "PROVISIONAL"`, **explicitly including the
triggering run itself**. Lifting requires a **separate ruling artefact** under `docs/evidence/`, read
by pinned path **and** sha256, fail-closed on absent/unreadable/mismatched. This is stricter than the
ruling's literal "lifts automatically" wording, but does not contradict it — the ruling states a
*checkable condition*, not a mechanism, and the plan's added rationale (a run cannot self-certify its
own end-to-end exercise) is sound and consistent with this repo's fail-closed posture elsewhere
(`C-KILL`'s staleness handling). I confirmed the ruling citation (`:405-412`) is exact. **C20** gained
exactly the three REDs my defect required: (a) first-no-`INERT` run still tagged in its own artefact;
(b) lift only on exact pinned-sha256 match; (c) missing/tampered ⇒ PROVISIONAL, never a crash. This
closes the defect completely, not by rewording.

## Round-8 MINOR defect (halt-enforcement overclaim) — genuinely fixed

§9 now states the champion is RULED not to send but the halt is **UNENFORCED**, quoting
`RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`'s status line (`:3`) and §4 (`:273-278`) verbatim —
both re-confirmed exact against source. Reason (i) is re-grounded on the enforcement-independent fact
(zero decisions reach pricing, an accidental Gate 1/Gate 2 by-product, cited to `:276-277,337-343` —
both confirmed exact), and the bullet now states (i)/(ii)/(iii) are each independently sufficient.

## Third reviewer's fix (R-4's superseded literal) — verified in both cited locations

Both §6b.3's R-4 quotation and §12's KILL-clock bullet now carry "R-4's literal `pm_us_crh_cont.json`
naming is SUPERSEDED (RULING Q4 item 3, `:483-491`)... the count must follow `sending_family_id`
dynamically." I confirmed the ruling's `:483-491` reconciliation paragraph says exactly this. Ownership
text (AUD-05 exclusively, by id only) is unchanged in both places.

## No regression

**C19** and the "bolded property sentence... identical word for word in AUD-09 §6b.3" paragraph are
byte-unchanged from round 8 (confirmed by direct re-read). Swept all six diff hunks against the current
file: no unrelated text moved, no citation drift introduced, `C14`/`C-VALIDITY`/`C17(g)` framing
unchanged, ownership consistency (AUD-05/AUD-19, by id only) preserved everywhere it was verified in
round 8.

## Defects

None found in this revision.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | The PROVISIONAL-lifting gap is closed conservatively; both round-8 findings and the third reviewer's fix are all genuinely applied. |
| Technical correctness and evidence grounding | 20 | 20 | Every citation I re-checked this round (ruling `:405-412`, `RULING_A1:3,273-278,276-277,337-343`, `:483-491`) is exact. |
| Implementation specificity and feasibility | 15 | 15 | The lifting mechanism is now fully decided: pinned path, sha256 match, fail-closed fallback, no self-certification. |
| Acceptance criteria and validation quality | 20 | 20 | C20's three new REDs test exactly the boundary case my round-8 defect identified as untested. |
| Autonomous operation, failure handling, recovery | 15 | 15 | Unchanged; the halt/enforcement text is now accurate and the independent-sufficiency framing is explicit. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | No defect found here across any round. |
| **Total** | **100** | **100** | |

## Required changes to reach 100

None.

## Blockers (recorded, not scored)

- **Externally owned, by id:** AUD-05 (champion-scoped KILL clock), AUD-19 (`--family-manifest`).
- **Operator:** arming, live enablement, the two reserved caps — untouched.
- **Unenforced today, per `RULING_A1`:** the champion's "may not SEND orders" disposition has no live
  code enforcement until AUD-02b's CLI lands and is run — correctly stated as such in §9, not this
  item's gap.
