# AUD-02 — Round 1 review (mle-reviewer, ML/production-engineering lens)

Plan: AUD-02-edge-discovery-programme-status-and-fold-in.md
sha256: 4009b3215d532993e77504ddc7f76e85fb1b277359d07a0af39285b1e6452f5d
Round: 1
Reviewer: mle-reviewer (independent, blind)

## Claims verified against source / git

- WP-B0 (`f97c26f`) and WP-R1 (`6aa9d92`, `e83fc5c`) commit SHAs exist —
  CONFIRMED via `git log --oneline`.
- `docs/core/PROGRESS.md:103-128`'s "2026-09-20 — WP-R1 calibration defect
  found in production (open)" entry, with "Fix (not yet applied)" — read
  directly: CONFIRMED still present verbatim, even though `e83fc5c` (same
  day) already lands the fix described. The plan's "PROGRESS.md is stale
  on this point" claim is CONFIRMED, not asserted on faith.
- AUD-02's calibration-defect fold-in (§3, §6.2) rests on AUD-01's finding
  (233/240 cells, mean +0.094 overstatement, "UNSALVAGEABLE" domain-
  reviewer verdict) — I independently re-verified the underlying source
  facts AUD-01 itself cites (`P_HOLD_UPPER` table shape, `build_hold_cases`
  population) as part of the AUD-01 review; they hold, so this plan's
  inherited claim is grounded, not merely asserted.
- The plan does not itself propose any code change (§6, §10) — verified:
  every proposed change is a documentation amendment to
  `POST_FORECAST_PHASE_2026-09-20.md`.

## Claims not independently re-verified (named, not concealed)

- The plan defers entirely to `POST_FORECAST_PHASE_2026-09-20.md`'s
  existing (peer-reviewed) acceptance criteria for A0/A1/B1-B3/C0-C2/WP-D1/
  Q1/T1 (§7 step 2: "each already fully specified with acceptance criteria
  in the existing plan; no re-design needed here"). This reviewer's brief
  asks specifically whether the evaluation protocol for any candidate edge
  is leak-safe and pre-registered with sample-size rules. **I did not open
  `POST_FORECAST_PHASE_2026-09-20.md` in full** (out of the three plans
  in scope for this round) to independently confirm A0/A1 actually carry a
  leak-safe, pre-registered, sample-size-ruled protocol — AUD-02 asserts
  that document already covers it (having been through its own peer
  review) but does not restate or re-verify it here. This is a genuine,
  named verification gap on my part, not a defect I am asserting exists in
  the base plan.

## Defects

**MINOR** — AUD-02 widens A1's precondition (§6.2) correctly and precisely
(citing "the domain reviewer has ruled a collider"), but does not restate
or cross-check that the base plan's own A0/A1 acceptance criteria actually
require pre-registration / a fixed sample-size rule / leak-safety before
any new edge estimate can pass. Since AUD-02's whole job is exactly this
kind of fold-in, a one-line confirmation ("A0/A1's existing acceptance
criteria already require X, verified at `POST_FORECAST_PHASE
§<section>`") would close this gap outright rather than leaving it as an
inherited, unstated assumption. Classed MINOR rather than MATERIAL because
the base plan was independently peer-reviewed (security + architecture)
before AUD-02 was written, and AUD-02 explicitly says it is not
re-litigating that content (§12 assumption, stated plainly).

**MINOR** — §11 states the evaluation is "whether A1 actually runs and
produces a signed ruling within a bounded time (operator/strategy-lead
cadence, not specified here)" — there is no owner or SLA named for A1
itself beyond "strategy lead," which the plan correctly flags as an
operator/strategy-lead decision it cannot make (§12), so this is not a gap
this plan can close; noted as inherent, not a defect to fix.

No MATERIAL defect found from this lens: the plan makes no new pricing,
data-contract, or serving claim of its own; it is a governance/fold-in
document whose only executable content (Amendment C text) is fully
specified and grounded in verified commits and verified source facts.

## Per-criterion points

- Fidelity to audit gap and completeness: 17/20 — matches plan's own
  self-score; correctly scoped as fold-in/status, not new architecture.
- Technical correctness and evidence grounding: 18/20 — WP-B0/WP-R1 DONE
  status and PROGRESS.md staleness both independently re-verified by this
  reviewer (not merely trusted); calibration-defect fold-in grounded in
  source facts this reviewer separately confirmed via AUD-01.
- Implementation specificity and feasibility: 13/15 — Amendment C text is
  concrete and pasteable; appropriate ceiling for a documentation item.
- Acceptance criteria and validation quality: 14/20 — concrete for the
  documentation deliverable; the plan's own acceptance criteria do not
  independently verify that A0/A1's inherited evaluation protocol is
  leak-safe/pre-registered, leaving that property assumed rather than
  demonstrated within this plan's own artefact.
- Autonomous operation, failure handling, recovery: 13/15 — correctly
  treats "A1 never rules" as an acceptable indefinite fail-closed state.
- Portfolio alignment, scope, dependencies: 10/10 — explicit, justified
  dependency on AUD-01a; correctly refuses to reopen the closed hunt.

**Total: 85/100.**

## Required changes to reach 100

1. Add one paragraph to §6 or §8 explicitly citing the specific
   `POST_FORECAST_PHASE_2026-09-20.md` section(s) that already impose
   pre-registration, a fixed sample-size/stopping rule, and leak-safety
   (as-of/point-in-time joins) on A0/A1's edge estimate — turning an
   inherited assumption into a checked citation, consistent with this
   plan's own standard elsewhere (every other claim in the plan is
   file:line or commit-SHA grounded).

## Blockers

- **BLOCKER (strategy-lead ruling, not this plan's to resolve):** A1 itself
  — named correctly in the plan's own §12, not waived here.
- **BLOCKER (operator, budget ceiling):** named correctly in §12, not
  touched by this plan, correctly not requested prematurely.
- **Reviewer-side scope limit (not a plan blocker):** confirming the
  leak-safety/pre-registration content of `POST_FORECAST_PHASE_2026-09-20.md`
  itself is outside this round's three-plan scope; the required change
  above asks the plan to make that citation explicit rather than asking me
  to re-review a fourth document.
