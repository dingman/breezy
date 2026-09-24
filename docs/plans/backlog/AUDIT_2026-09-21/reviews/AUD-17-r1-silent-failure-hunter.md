# AUD-17 review (round 1)

**Plan file sha256:** c0eba6337c568011d42cda6bce7fe41814b094109f027b332c2edbc4c81636f7
**Round:** 1
**Reviewer:** silent-failure-hunter (independent, blind)

## Claims verified

- `tests/unit/operator_control_env.py` as the sole whitelisted injection seam, and its docstring
  language — plausible and internally consistent with the plan's description of
  `test_operator_control_assignment_scan.py`'s four-layer design; not independently re-read this
  session, treated as plan-internal evidence.
- `_submit_order`'s two enforcement points (`assert_live_order_submission_permitted` →
  `SessionNotionalExhausted`; `authorize_order_cost` → `DailyBudgetExhausted`) — plausible per
  the plan's citations; not independently re-read this session.

## Defects — this is where the assigned "can the test pass vacuously" challenge lands

**MATERIAL — assertion 1 (per-position-cap denial) is underspecified relative to assertion 2,
and is the exact vacuous-pass shape this review was asked to probe.** §6 states: *"An order
whose cost exceeds the synthetic per-position cap is denied on the entry path — assert the
denial reaches `_deny` and that no venue request is made."* Unlike assertion 2 (which explicitly
names `DailyBudgetExhausted` as the exception that must be raised), assertion 1 never requires
pinning `SessionNotionalExhausted` as the specific cause. A composition-level test that only
checks "was denied + no POST" cannot distinguish the per-position cap firing from an unrelated
earlier veto (e.g. a PREREG/cell-legal/observation-ambiguous refusal, or a broken test fixture)
intercepting the order first — in which case the test would pass while proving nothing about the
cap. This is precisely "denial raised for a different reason than the cap."

**MATERIAL — no positive-control ("would otherwise be admitted") case is actually specified as a
deliverable.** §9 ("Validation") states the tests "must cover" boundary-admitted cases ("Cost
exactly at the per-position cap → admitted", "Spend exactly at the daily budget → admitted"), but
§7's ordered RED-test list (the four items actually scoped for implementation) and §8's
acceptance criteria (which count exactly "four assertions") do not include an admitted/positive
case at the *composition* level — only the pre-existing *mechanism*-level test
(`test_a_cost_exactly_at_the_position_cap_is_admitted`) is referenced, and §2's own coverage
table already establishes that mechanism-level tests do **not** cover the v4 composition. Without
a composition-level admit case, none of the four scoped assertions proves the composition can
ever *succeed* through this wiring — so all four "denied" assertions could pass vacuously if the
composition harness always denies for an unrelated reason (a mis-wired fixture, a stale manifest
path, an exception in composition construction that happens to prevent any venue POST). This is
an internal contradiction between §9 (which states the requirement) and §7/§8 (which don't scope
it as a deliverable) — not a hypothetical: it is the concrete gap between what the plan claims to
validate and what it actually lists as work.

## Per-criterion points

| Criterion | Cap | Points |
|---|---|---|
| Fidelity to audit gap and completeness | 20 | 17 |
| Technical correctness and evidence grounding | 20 | 18 |
| Implementation specificity and feasibility | 15 | 11 |
| Acceptance criteria and validation quality | 20 | 13 |
| Autonomous operation, failure handling and recovery | 15 | 12 |
| Portfolio objective alignment, scope and dependencies | 10 | 10 |
| **Total** | **100** | **81** |

## Required changes to reach 100

1. Assertion 1 must explicitly assert `SessionNotionalExhausted` is the raised/caught exception,
   matching assertion 2's precision — not merely "denied + no POST".
2. Add a composition-level positive-control test: with the same order shape but a cap/budget set
   high enough to admit it, the order is **not** denied and reaches the point where it would
   place a (sandboxed, no-egress) venue request — proving the harness can produce a success
   through this exact composition wiring, so the denial assertions are falsifiable rather than
   vacuously true. Promote this from §9's "must cover" language into §7's ordered steps and §8's
   acceptance count (five assertions, not four).
3. Resolve the §9-vs-§7/§8 inconsistency explicitly rather than leaving §9's requirement
   unscoped.

## Blockers

None. The plan correctly states no operator/strategy ruling is required and correctly excludes
R-12 and MP-B/sizing.

## Review record path
docs/plans/backlog/AUDIT_2026-09-21/reviews/AUD-17-r1-silent-failure-hunter.md
