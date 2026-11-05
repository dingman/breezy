# AUD-10 — Review record (Round 10, micro-delta, FINAL)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: 400aea7a33a1116849222aab4d38c18ad722a89814a674a06972982b9b1aa6fa (coordinator recorded 400aea7a…)
- Round: 10 (micro-delta) · Reviewer: architect (code-architect lens)
- Total: 100/100 · Readiness: READY

## Round-9 disposition, verified in place

| R9 defect | Claimed | Verified? |
|---|---|---|
| **10-10 (MINOR)** — the plan narrows a ruled instruction (the ruling says PROVISIONAL "lifts **automatically**"; the plan requires a separate sha256-pinned ruling artefact) without recording the departure, so a reader diffing plan against ruling cannot tell a considered refinement from drift | FIXED | **CONFIRMED at §6b.3**, inserted exactly where required — directly after *"a run cannot declare its own criteria end-to-end exercised on the strength of its own outcome."* and before the *"So **every artefact emitted while the criteria are PROVISIONAL** …"* consequence, so the paragraph now runs claim → reason → **recorded departure** → consequence without a seam. The text is verbatim as specified: *"**Recorded departure:** the ruling's word is *automatically* (`:405-406`); this plan is deliberately **stricter**, because a run may not self-certify. The stricter rule only ever keeps the tag on longer and never drops it earlier, so it cannot conflict with the ruling's binding requirement that every un-lifted verdict carry the tag (`:410-412`)."* **Both citations are exact** — I verified them at source in round 9: `:405-406` is *"PROVISIONAL lifts automatically the first time a promotion-proposal run completes…"* and `:410-412` is *"Until lifted, `PROPOSAL` and `NO_PROPOSAL` verdicts alike must carry the `PROVISIONAL` tag…"*. The clause therefore does three things correctly: it names the ruled word it departs from, it gives the reason, and it states the *soundness argument* (strictness can only extend tagging, never curtail it) rather than merely asserting compatibility — which is what makes the departure auditable rather than merely disclosed. This now matches the plan's own standard applied everywhere else it departs from a source (the withdrawn `:152-160` "mirror", R-4's supersession, the ruling's ±1 bootstrap range). |

## Regression check

Single in-place insertion; I re-read the whole paragraph (`:422-435`) and its neighbours. The
`criteria_status: "PROVISIONAL"` rule, the "triggering run's own artefact stays tagged" clause, the
pinned-path + sha256 lift, the fail-closed fallback, the "advisory to a human promotion commit" framing
and `C14`-unchanged are all present and unaltered. **C20** (including round 9's three REDs), the
`C-KILL` binding table, C15's seven refusal shapes, C17's seven arms, C18, and **§6b.4's property
sentence and C19's three-script set** are untouched — so the AUD-09 **B18** mirror and the normalised
anchor `ce5b6d1d…a26263` still hold. C1–C20 numbering and the §8 / §11 enumerations are unchanged.

## Defects found in revision 10

**None.** The fix introduces no new claim and no new cross-reference, and it does not alter the
behaviour C20 tests.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | 10a closes REG-1 across all six sites and the zero-strategy boot path; 10b binds all eight predicates to real artefacts, applies every ruled obligation in the ruling's own terms, and is explicit that naming owners produced no artefact — `PROPOSAL` stays unreachable and the plan says so where a reader looks for value (§11). |
| Technical correctness and evidence grounding | 20 | 20 | The round-9 deduction is discharged: the one place this plan is stricter than its authority now says so, with both ranges verified exact. Every other citation I have checked across rounds 3–9 stands (`score-live-trials-run.sh:47,115-129`; `structural_dead_stop.py:111-132,297-330,347-349`; `fill_time_count.py:101-118`; `family_manifest.py:185,220`; `current_rung_hold_v2.py:184,230,237,269-292,318-336`; `roi_bound.py:93,97,214-224`; `RULING_A1:3,273-278`; `PROGRESS.md:73` with its supersession). |
| Implementation specificity and feasibility | 15 | 15 | `C-KILL`'s binding (artefact, keys, reader, max-age, champion-scope identity, evaluation order, `evaluable`-before-`structural_dead`), the adapted R5 parameters pinned to shipped code, and `criteria_status` with its named lift mechanism and three failure modes leave nothing material to the implementer. |
| Acceptance criteria and validation quality | 20 | 20 | C1–C20 objective; C17's seven arms and C15's seven refusal shapes are complete and non-permissive; C20 pins the adapted-R5 parameters *and* the lifting boundary including the adversarial (tampered artefact) and self-certification cases; C19 mirrors AUD-09 B18 from this side. |
| Autonomous operation, failure handling, recovery | 15 | 15 | Fail-closed throughout: `INERT` is never a verdict and never permission, stale/absent/not-evaluable/wrong-family are four named outcomes with a stated precedence, the tag lift cannot silently fire or crash, content-hash idempotency, read-only on every input, and §9's halt case rests on three independently-sufficient grounds. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Zero-ROI honesty; correctness benefit named as correctness; a PROVISIONAL `PROPOSAL` is advisory to the human unit-file commit, never auto-promotion; AUD-05/AUD-19/AUD-02b/AUD-11/AUD-12 cited strictly by id with no schedule dependency; arming, the two reserved caps and NO-SEND untouched, with no code reading or proposing a cap value. |
| **Total** | **100** | **100** | |

## Required changes
None. This closes every defect I have raised against AUD-10 across rounds 3–9 (10-1 … 10-10, c1, c2).

## Blockers and dependencies (recorded separately; not scored)
- **AUD-05** (by id): champion-scoped KILL clock — `C-KILL` stays `INERT` until it lands; no plan change
  needed when it does.
- **AUD-19** (by id), gated on the replay-`trial_id` fix (AUD-19a): `--family-manifest` — `C-PAIRED`
  stays `INERT`.
- **Compound consequence, stated in-plan:** with both `INERT`, no run can emit `PROPOSAL`, and the
  adapted R5 criteria stay **PROVISIONAL** because the lifting condition is unreachable until those
  artefacts exist — a dependency, not a deduction, and §6b.3/§11/§12 say so plainly.
- **A future lifting ruling** under `docs/evidence/`, read by pinned path + sha256, is required before
  the criteria read as unqualified.
- **AUD-02b** (by id, via `RULING_A1`): the champion's halt is RULED but **UNENFORCED**; the plan's
  `NO_PROPOSAL` conclusion deliberately does not depend on it.
- **Operator:** arming, live-trading enablement, the two reserved caps — named, untouched.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._
