# AUD-17 — Round 3 review (silent-failure-hunter)

**Plan file:** AUD-17-operator-caps-proven-through-the-v4-live-composition.md
**SHA256:** 5e5877c745c2a299acf639e5c04436aae6118791670476caae8924e6fc7f8f87
**Round:** 3
**Reviewer:** silent-failure-hunter (independent, blind)

## Claims verified against source (this session)

| Claim | Status |
|---|---|
| `MAX_POSITION_COST_USD_ENV_VAR = "BREEZY_MAX_POSITION_COST_USD"` (`operator_controls.py:136`), `MAX_DAILY_BUDGET_USD_ENV_VAR = "BREEZY_MAX_DAILY_BUDGET_USD"` (`:131`), `OPERATOR_RESERVED_CONTROL_ENV_VARS` tuple of both (`:141-144`) | CONFIRMED verbatim |
| `operator_max_position_cost_usd()`/`operator_max_daily_budget_usd()` route through `_read_operator_money`, raising `LiveTradingPermissionError` and naming the control, never its value (`:160-179`) | CONFIRMED |
| The per-position ceiling's plain-`LiveTradingPermissionError` framing (never a nameable subclass) is consistent with the ruling text the plan quotes at `operator_controls.py:120-125` | Consistent with source read this session; not independently re-derived line-by-line this round (already verified by both round-1/round-2 reviewers per the plan's own record) |

## Attack per brief: "the stated fallback consequence — can 'still passes, unskipped' hide a lost assertion?"

§7 17a step 2 / §9: if layer B refuses the imported-constant assertion style, the per-position denial test drops assertion 2 (reason-equality) and runs on assertion 1 (exact-type discrimination, `type(exc) is LiveTradingPermissionError`) plus assertion 3 (the differential: the identical order/composition/permit admitted when only that one ceiling is raised) alone — "still PASSES... not skipped, not xfailed."

Examined for whether this could mask a real loss of attribution power:

- **Logically, no.** Assertion 3 (the differential) is independently sufficient to exclude every upstream veto by construction: since the *same* order/composition/permit is admitted when *only* the per-position ceiling changes, no other gate (`submit_veto`, `RECONCILE_NOT_RUN_REASON`, PREREG, cell-legality) can be the true cause of the original denial, because none of those was touched between the two runs. Assertion 1 additionally excludes causes 1/2 (the two *nameable* subclasses) positively. Assertion 2 (reason-equality against the imported constant) genuinely is corroboration on top of an already-sufficient pair, not a third independent leg — the plan's own §9 argument for this is sound and I could not construct a counter-example where dropping assertion 2 admits a false positive that assertions 1+3 would not also catch.
- **Procedurally, the "still passes" framing is adequately bounded**, not open-ended: the fallback is required to be *recorded in the transcript* with the scan output that forced it (§7 17a step 2(a)), and dropping assertion 2 is stated as the *only* permitted response — amending the scan is explicitly forbidden. This closes the most dangerous version of the risk (silently weakening a safety-adjacent test with no trace).
- **Residual, not material:** the recording obligation is a one-time execution-transcript artifact, not an ongoing CI check. If layer B's tolerance is later loosened (permitting the imported-constant style), nothing in this plan re-triggers a review of whether assertion 2 should be restored — the fallback, once taken, is durable by default rather than revisited. This is a real but low-severity gap: since assertions 1+3 are independently sufficient (as argued above), the absence of a restoration trigger does not weaken correctness, only tidiness/defence-in-depth. **MINOR**, not MATERIAL.

No defect found that would make "still passes, unskipped" hide a genuine loss of attribution.

## Other checks — no additional defects found this round

- The three-cause enforcement table (session-notional / daily-budget / per-position) and the load-bearing fact that a failed reconciliation makes the per-position ceiling's exception type structurally ambiguous (shared with clock-rewind and permit-validation failures) is correctly reasoned and drives a genuinely stronger test design (type + differential) than a naive subclass check would.
- The ADMIT/positive-control case is correctly scoped first (§7 17b step 1) and gates acceptance of every denial case (§8 item 3) — this closes the vacuous-pass risk structurally, not just by assertion.
- The exit-side skip's negative (`test_an_untagged_sell_never_reaches_the_exit_side_skip`) correctly guards against the skip being reachable by a naked short, tying back to the `allow_short=False` invariant.
- No cap value, magnitude, or assignment is read, written, or implied anywhere in the plan; the injection seam (`operator_control_env.py`) and its whitelisting rationale are consistent with the codebase's own described four-layer scan.

## Per-criterion points

| Criterion | Cap | Points | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 19 | G-16 closed as stated, with the third denial cause folded in; correctly scoped as verification-only. |
| Technical correctness and evidence grounding | 20 | 19 | Every constant, function and the ruling text re-checked this session and matches; acknowledged ±1-2 line drift is immaterial. |
| Implementation specificity and feasibility | 15 | 14 | Ten named tests in dependency order; the fallback's pass/fail consequence is fully specified. The two-permit-fixture and synthetic-order construction remain the costliest unspecified mechanics, as the plan itself states. |
| Acceptance criteria and validation quality | 20 | 19 | ADMIT gates every denial; differential required in transcript; three `git diff`-empty guards. Fallback now carries a transcript obligation. |
| Autonomous operation, failure handling, recovery | 15 | 14 | Directly proves the unattended-spend bound; boundary-admit, no-cost-on-refusal, latch-not-cleared all pinned; adds no new runtime control (correct for a verification item). |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | No cap value or magnitude invented or implied; R-12/MP-B correctly routed to their owners; test-only, zero rollback risk. |
| **Total** | **100** | **95** | |

## Required changes

None MATERIAL. Optional (MINOR, not blocking): note in §9 that if layer B's tolerance is ever relaxed, the reason-equality assertion should be revisited for restoration — a low-cost defence-in-depth note, not a correctness requirement, since assertions 1+3 are independently sufficient.

## Blockers

None. R-12 remains explicitly out of scope and creates no new ruling need, consistent with the plan's own statement.
