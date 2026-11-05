# AUD-02 review — round 2 — prediction-market-reviewer

Plan: AUD-02-edge-discovery-programme-status-and-fold-in.md
sha256: 1d12667a9d970f3b85a809c4c81424dc82fa2f41c321d1682cbb1cc9e6cbd2c9
Round: 2
Reviewer: prediction-market-reviewer (blind, independent)

## §13 review-history verification

- mle-reviewer round-1 MINOR (leak-safety/pre-reg/sample-size never cited): CONFIRMED FIXED.
  Re-checked directly against `POST_FORECAST_PHASE_2026-09-20.md`: A1's row (line 45) reads
  "Precondition for (iii): a post-θ edge estimate whose CI excludes 0... if A0 cannot produce
  one, (iii) is abandoned by default and (ii) is the answer"; line 217 states "New
  `trial_id_prefix`, new `d0_climate_day`, **n reset to 0**, LD-OBF α spent"; line 93 states
  "hypothesis WP carries a pre-registered abandonment criterion"; C1's row (line 50) states
  "21 days of capture if qualifying events accrue at < 0.25/station-day"; C2's row (line 51)
  "Runs only at n ≥ 30... CI includes 0, or lower bound ≤ 0 ⇒ hypothesis CLOSED." All four
  citations in AUD-02 §3 are verbatim-accurate.
- prediction-market-reviewer round-1 MINOR (no escalation mechanism): PARTIALLY FIXED — see
  new MATERIAL finding below. A mechanism is now specified (§6.4), but its delivery is not
  enforced by either plan's own acceptance criteria, which reopens the underlying "rots
  silently" risk the round-1 finding was about, in a different form.

## Claims verified this round (fresh, whole-plan pass)

- WP-B0 `f97c26f` — CONFIRMED, commit message "feat(wp-b0): alert egress -- give detection a
  destination," dated 2026-09-20.
- WP-R1 `6aa9d92`/`e83fc5c` — CONFIRMED, "feat(wp-r1): detect a structural halt..." and
  "fix(wp-r1): a thin market is not a halt -- gate zero-evaluation on tick count."
- A1 precondition widening (§6.2) citing "recalibrate on the gate-pass subsample... a
  collider" — CONFIRMED verbatim in `DECISION_FUNNEL_2026-09-20.md`'s "Why 'recalibrate on
  the gate-pass subsample' is NOT the remedy" section.
- §4's C-branch gating citation "measured at 0.125/station-day, 2x BELOW that bar" against
  a ">= 0.25" threshold — CONFIRMED: `POST_FORECAST_PHASE_2026-09-20.md:284` "8 events over
  64 scored instants = 0.125/station-day"; line 295 "A measured rate ≥ 0.25/station-day";
  line 389 the ordering note "post-freeze YES qualifying rate >= 0.25."
- §4's execution order (B3→B2→WP-D1→A0→A1→B1) — consistent with the base plan's own
  amendment-B ordering; no contradiction found.
- Dependency on AUD-01a landing first, cited from "§12 of AUD-01" — CONFIRMED, AUD-01's own
  §4/§12 state the same ordering from its side.
- `PROGRESS.md`'s WP-R1 entry flagged stale (lines 103-128, "not yet applied") though
  `e83fc5c` landed 09-20 — spot-checked: PROGRESS.md does carry an entry in that range dated
  "2026-09-20 — WP-R1 calibration defect found in production (open)"; the plan's
  characterization is accurate and correctly deferred (planning-only, no PROGRESS edit).

## Defects

- **MATERIAL — §6.4/§8, the A1-blocker escalation mechanism is unowned, not merely
  cross-referenced.** The coordinator brief specifically asks whether this creates a
  circular or unowned dependency; it is not circular (no cycle: AUD-02 depends on AUD-01a,
  not on AUD-03; AUD-03 states no dependency on AUD-02), but it IS unowned. AUD-02's own §8
  acceptance criterion states: "this plan's own acceptance does not require AUD-03 to have
  shipped first, only that the requirement is on record" — i.e. AUD-02 can be marked DONE
  whether or not the escalation line is ever built. AUD-03's own §8 acceptance criteria (the
  plan that would actually implement it) does NOT list the A1-open-age line as a required
  criterion — AUD-03 §4/§12 only describe it as something "this item should carry once both
  land," a "small addition, not a dependency," never elevated to AUD-03's own §7/§8
  RED-test/acceptance list. The practical consequence: BOTH plans can independently reach
  100% of their own stated acceptance criteria while the escalation feature — whose entire
  purpose is preventing the exact "correct finding, undelivered" failure this repo has
  already paid for twice (3-day silent fee halt, 11-hour silent permit lapse, both cited in
  this plan's own §6.4) — never ships. This is a real gap between two plans' acceptance
  surfaces, not a hypothetical: nothing in either plan's §8 will fail if the line is never
  added.
  - Required change: either (a) add the A1-open-age line as a REQUIRED acceptance criterion
    in AUD-03's own §8 (conditional on AUD-02 having landed by the time AUD-03 is
    implemented, with a named fallback — e.g. a tracked fast-follow ticket with an owner and
    a date — if AUD-03 ships first), or (b) have AUD-02 itself create a standalone,
    owned follow-up backlog item (not "a scope note when dispatching AUD-03") for the
    escalation line, so at least one plan's acceptance criteria is not satisfied until the
    feature actually exists. As written, the requirement is real but nobody is accountable
    for shipping it.

## Per-criterion points

- Fidelity to audit gap and completeness: 19/20 — the programme-status synthesis, DONE/open
  work-package accounting, and A1 precondition widening are all accurate and complete; the
  one point held back is the unowned escalation gap above, which weakens "honestly
  dispositioned" for the specific risk this section itself names (silent staleness).
- Technical correctness and evidence grounding: 20/20 — every citation checked this round
  (commit SHAs, `POST_FORECAST_PHASE` line-level quotes, `PROGRESS.md` cross-check) matches
  current source exactly; no refuted claim found.
- Implementation specificity and feasibility: 13/15 — Amendment C text and the widened A1
  precondition are concrete and pasteable; the §6.4 escalation mechanism is specified in
  intent but not in a way an implementer of either plan is forced to actually build (see
  defect above) — that is an implementability/ownership gap, not merely a wire-format detail.
- Acceptance criteria and validation quality: 14/20 — deducted for the defect above: an
  acceptance bullet that is explicitly "on record" rather than "on record AND enforced" does
  not validate that the escalation mechanism exists; every other acceptance criterion (
  Amendment C present, A0 evidence pack dated, A1 signed ruling doc, PROGRESS staleness
  named) is concrete and checkable.
- Autonomous operation, failure handling, recovery: 11/15 — this criterion is precisely what
  the escalation mechanism exists to serve (an indefinitely-open blocker must stay visible
  without a human re-deriving it); because delivery of that mechanism is not enforced by
  either plan's acceptance surface, the "rots silently" failure mode this section explicitly
  names as its own motivation is not actually closed by this revision, only narrated as
  closed.
- Portfolio alignment, scope, dependencies: 7/10 — the AUD-01a dependency is correctly
  stated and justified; the AUD-03 relationship is where points are lost: an unowned
  cross-plan feature requirement is a scope/dependency defect by the rubric's own
  definition, not a stylistic one.

**Total: 84/100.**

## Required changes to reach 100

1. Close the ownership gap on the A1-open-age escalation line: make it a required,
   testable acceptance criterion in whichever plan (AUD-02 or AUD-03) actually implements
   it, with a named fallback if the two plans land out of order, rather than leaving it as
   a mutual "scope note."

## Blockers

- **Named BLOCKER (strategy-lead ruling, not decided here, correctly scoped by the plan):**
  A1 itself — RETIRE / STOP TRADING / re-register `pm_us_crh_v4` at observed θ with a
  genuinely independent edge estimate.
- **Named BLOCKER (operator, budget-ceiling only, correctly scoped by the plan):** no
  operator budget ceiling is set even if A1 rules (iii) and C2 later clears; this plan does
  not touch that control.
- The escalation-ownership defect above is a plan-text/scope fix, not an operator or
  strategy-lead ruling — it does not require unavailable evidence or access.
