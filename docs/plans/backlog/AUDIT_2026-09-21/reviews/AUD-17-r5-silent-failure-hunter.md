# AUD-17 — Round 5 review (silent-failure-hunter, FINAL, reconciled)

**Plan file:** AUD-17-operator-caps-proven-through-the-v4-live-composition.md
**SHA256:** df21c342c630afa55a9b5fafdcd5aa5f9b48a5e0d33b56b8cf13bd7957bd4e9c (verified via `sha256sum`)
**Round:** 5 (final)
**Reviewer:** silent-failure-hunter (independent, blind)

## Verification of the reported change against source

Re-derived every citation the retargeted pin relies on, from `tests/unit/test_operator_control_assignment_scan.py`:

| Claim | Status |
|---|---|
| `SCAN_ROOTS = ("src", "scripts", "tests")` | CONFIRMED, exact line `:86` |
| `PERMITTED_CONTROL_ARGUMENT_CALLEES` | CONFIRMED, defined at `:126` |
| `_READER_CHAIN_CALLEES` | CONFIRMED, defined at `:138` |
| `find_control_assignments(path: str, source: str) -> list[Assignment]` — a **public** helper | CONFIRMED, exact line `:224` |
| A6 rule body: inside `find_control_assignments`, for an `ast.Call` node whose callee is outside `PERMITTED_CONTROL_ARGUMENT_CALLEES \| _READER_CHAIN_CALLEES`, if any argument `_mentions_control`, append an `Assignment(..., "A6", ...)` | CONFIRMED, exact lines `:285-295` |
| `_mentions_control` walks with `ast.walk` and matches an `ast.Name.id` against `CONTROL_CONSTANT_IDENTIFIERS` — reachable **inside** an f-string's `FormattedValue`, since `ast.walk` descends into it | CONFIRMED (re-derived structurally from `:157-167`, already verified in round 4) |
| `test_the_scan_does_not_fire_on_asserting_about_a_control_name` — plants `assert MAX_DAILY_BUDGET_USD_ENV_VAR in message` (a bare `Compare`, not a `Call`) and asserts `find_control_assignments(...) == []` | CONFIRMED, exact test body at `:469-479` (a pre-existing test, not new) |
| `test_the_scan_fires_on_every_planted_assignment_form` — parametrized non-vacuity check that the scan fires on each planted shape | CONFIRMED, exact location `:449-454` |

This is a materially significant finding in its own right: `find_control_assignments` is a **public, already-battle-tested helper**, and the repo **already contains a test** (`test_the_scan_does_not_fire_on_asserting_about_a_control_name`) proving the exact "bare comparison/containment, no call" shape the retargeted pin's branch (a) relies on is tolerated by layer A **today**, while A6's own `isinstance(node, ast.Call)` gate confirms structurally that wrapping the same identifier reference in a call to an unapproved callee (branch b) **would** trip it. The retargeted pin (§7 17a step 2a, per the plan's description) exercises both branches by feeding synthetic source strings directly to `find_control_assignments` — no monkeypatch, no edit to the scan module, nothing to revert — so the "capable of firing" demonstration required by §8 item 2a is now intrinsic to a single test run rather than staged. This closes both halves of the round-4 MATERIAL defect (wrong target — layer B, which structurally cannot drift for this style — corrected to layer A, which genuinely can under ordinary scan maintenance; and the previously-unspecified "how do you demonstrate firing without touching the scan" question, now answered by an existing public API with existing precedent).

I looked for a residual gap in the retargeting itself: is there any AST shape reachable in `tests/` that would let branch (a)'s "clean" rewrite (the bare comparison the per-position denial test's reason-equality assertion is meant to use) still race a *different* layer-A rule (A1-A5, A4) rather than A6? Reading `find_control_assignments`'s full body: A1/A5 fire only on `ast.Assign`/`AnnAssign`/`AugAssign` targets that are environment subscripts; A2/A3/A3b fire only on specific env-read/write call shapes; A4 fires only on `ast.Dict` literals with a control key. None of these are triggered by `assert <imported constant identifier> in <expression>` or an f-string embedding used purely for string construction/comparison — the only rule whose scope could plausibly reach a bare identifier reference is A6, which requires a `Call` node. No other rule presents a comparable risk.

## Reconciliation of previously-withheld points (round 4: 88/100)

| Criterion | R4 | Reason given | Disposition |
|---|---|---|---|
| Fidelity | 19/20 | "still correctly scoped as verification-only. Unaffected by the pin defect" | **(b) AWARDED — 20/20.** No defect is actually named here in any round — this is a description of the item's correct scope, not a shortfall. G-16 is closed as stated with the third denial cause folded in. |
| Technical correctness | 17/20 | "the round-4 addition (the precondition pin) is built on a technically inaccurate premise" [the layer-B mistargeting] | **(a) then closed.** The named defect is the layer-B/layer-A mistargeting — **CLOSED**, re-verified against source this session (table above). Award: 20/20. |
| Implementation specificity | 11/15 | **MATERIAL** — no legitimate, specified mechanism to demonstrate the pin "capable of firing" | **(a) then closed.** The retargeted design demonstrates firing intrinsically via `find_control_assignments`'s two branches, using a pre-existing, already-verified public helper and precedent test — no invented or unspecified technique required. Award: 15/15. |
| Acceptance | 17/20 | "item 2a specifically is not satisfiable as written" | **(a) then closed.** Directly downstream of the specificity fix — §8 item 2a's "capable of firing" requirement is now concretely satisfiable in one test run. Award: 20/20. |
| Autonomous operation | 14/15 | "Unaffected — neither-control-set, boundary-admit, no-cost-on-refusal and latch-not-cleared all remain pinned and are not implicated by the pin defect" | **(b) AWARDED — 15/15.** No defect named; the pin fix is confined to §7 17a step 2/2a's own self-check mechanism and does not touch the ten §7 17b tests or the caps' own enforcement proof. |
| Portfolio | 10/10 | (full) | Unchanged — 10/10. |

## Per-criterion points (final)

| Criterion | Cap | Points |
|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 |
| Technical correctness and evidence grounding | 20 | 20 |
| Implementation specificity and feasibility | 15 | 15 |
| Acceptance criteria and validation quality | 20 | 20 |
| Autonomous operation, failure handling, recovery | 15 | 15 |
| Portfolio objective alignment, scope, dependencies | 10 | 10 |
| **Total** | **100** | **100** |

## Required changes

None. The round-4 MATERIAL defect (pin mistargeted at a structurally-immune layer, with no specified non-scan-editing firing demonstration) is fully closed: retargeted at layer A's `find_control_assignments`/A6, exercised via synthetic sources against both branches, using a pre-existing public helper with pre-existing precedent tests as confirmation. No new defect found on this session's independent re-derivation.

## Blockers

None. No cap value is read or assigned; R-12 (the session order-count ceiling) remains open and explicitly out of scope, unaffected by this item — unchanged across all five rounds.
