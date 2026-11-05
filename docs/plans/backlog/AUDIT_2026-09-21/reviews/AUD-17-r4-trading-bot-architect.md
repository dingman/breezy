# AUD-17 round-4 review — trading-bot-architect

Plan: AUD-17-operator-caps-proven-through-the-v4-live-composition.md
SHA256: ddb769bc1a5ec850859dca6ef04bee13448578fb81ff71022bc901b1fcbf2850
Round: 4 (FINAL)
Reviewer: trading-bot-architect

## Claims verified against source (this session, read-only, before re-reading the plan's own quotations)

| Claim | Verdict |
|---|---|
| `operator_controls.py:120`, comment: "raised ONLY by the daily-budget branch…"; `class DailyBudgetExhausted(LiveTradingPermissionError):` at `:126`; the per-position branch `if cost > position_cap:` at `:386` raises a plain `LiveTradingPermissionError` | CONFIRMED — grepped directly, matches the plan's three-cause table exactly |
| `test_operator_control_assignment_scan.py`: `_mentions_control` at `:157`, `_control_aliases` at `:171`, `files_naming_a_control()` at `:347`, `test_only_the_definition_module_names_an_operator_reserved_control` at `:610` — the four helpers the round-3-added precondition pin (`test_layer_b_still_refuses_the_imported_constant_style_so_assertion_2_stays_dropped`) calls | CONFIRMED, all four present at the cited lines |
| `tests/unit/operator_control_env.py` described as the sole whitelisted injection seam, restoring in a `finally` | Not re-read line-for-line this session (no round-3/round-4 defect touches it); consistent with prior rounds' independent confirmation and with the assignment-scan module's own layered design, which I did inspect directly via the four helper citations above |

## Coherence check (the round-4 brief's specific ask: "the precondition pin using the scan's own helpers")

The pin is designed to call `files_naming_a_control()` and `_mentions_control`/`_control_aliases` **read-only**, asserting that the imported-constant reference form still counts as "naming a control" under layer B's current classification — never modifying, copying, or re-implementing the scan's logic. I confirmed all four are public module-level symbols at the cited lines, so the pin can import and call them without touching `test_operator_control_assignment_scan.py` itself, which is the hard boundary §5 sets ("never weaken `test_operator_control_assignment_scan.py`"). The design is sound: it fails exactly when layer B's tolerance changes (the premise), and does not fire on any change to *this* test file's own behaviour, which is precisely why an `xfail(strict=True)` variant was correctly rejected in §9 (a layer-B relaxation would manifest as the *scan's own* census changing, not as a failure inside the per-position test — an `xfail` on the per-position test would XPASS under both tolerances and never catch the drift).

## Defects

None MATERIAL, none MINOR found this round. This is the third consecutive round in which this reviewer type has found nothing to add; I treat that fact the way this backlog's own standing rule requires — not as evidence the plan is clean, but as a reason to look specifically for what a "no defect" verdict might be missing. I checked three things a rubber-stamp read would skip:

1. **Does the precondition pin's fallback trigger silently degrade the per-position test's attribution below what round 1's MATERIAL defect required?** No — §7 17a step 2 states explicitly that on fallback the test still runs on exact-type discrimination (`type(exc) is LiveTradingPermissionError`) plus the differential (the same order, same composition, denied at one ceiling and admitted at another), and the differential is independently sufficient to exclude every upstream veto by construction (`submit_veto`, `RECONCILE_NOT_RUN_REASON`, PREREG/cell-legality/observation-ambiguity) — none of those can produce a denial that disappears when exactly one control moves. Reason-equality (the dropped assertion) was always corroboration on top of that, never load-bearing alone.
2. **Is the ADMIT case genuinely required before any denial assertion counts, and is that enforced rather than merely stated?** Yes — §8 item 3 states "the ADMIT case must be green before any denial case is accepted as evidence," and §7 17b step 1 scopes it first in dependency order, ahead of every denial test.
3. **Does the synthetic-order bound quietly relax what the test proves about sizing?** No — §5 explicitly excludes sizing/order-construction (G-11/MP-B, blocked on R-11) and §6 states the caps enforce at the exec-client boundary downstream of and independent from sizing, so a hand-built order is the correct scope, not a shortcut; the plan is honest that what must be real is the wiring (shipped manifest, real composition dispatch, real ledger, real permit, real gate ordering), not the strategy's own decision to trade.

## Per-criterion scoring

| Criterion | Cap | Points | Rationale |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | G-16 closed as stated; the third denial cause (the permit-derived session-notional ceiling, which round 1 had conflated with the per-position cap) is folded in and now independently verified correct against source. |
| Technical correctness and evidence grounding | 20 | 20 | The three-cause exception table and all four scan-helper citations for the precondition pin verified directly from source this session, independent of the plan's own quotations, and all correct. |
| Implementation specificity and feasibility | 15 | 14 | Ten named tests plus the conditional precondition pin, each in dependency order; the layer-B fallback has a stated pass/fail consequence, a forbidden repair, and a named restoration trigger. Deducted 1: the two-permit-fixture construction and the exact synthetic-order shape remain the implementer's to build — a real cost, not a design gap, but not yet reduced to a literal fixture. |
| Acceptance criteria and validation quality | 20 | 19 | Nine items; ADMIT gates every denial; the differential is a required transcript element; the pin must be demonstrated capable of failing, not merely present. Deducted 1: on the no-fallback path acceptance is a recorded answer rather than an artefact, which is correct but asymmetric with the fallback path's stronger evidence bar. |
| Autonomous operation, failure handling and recovery | 15 | 14 | Neither-control-set, boundary-admit, no-cost-on-refusal and latch-not-cleared are all pinned; the no-POST assertion runs under the no-egress sandbox independently of the assertion logic. Deducted 1: this item detects a broken cap only at test time, never at run time — correct scope for a verification-only item, but the ceiling this criterion can reach for a test-only plan is inherently below what a runtime control item could earn. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | No cap value or magnitude read, assigned, or implied anywhere in the plan; R-12 and MP-B/R-11 are routed to their owning rulings rather than pre-empted; test-only scope makes rollback risk nil. |
| **Total** | **100** | **97** | |

## Required changes

None MATERIAL. The two points withheld on specificity reflect real remaining implementation cost (the two-permit fixture, the synthetic-order construction) that no additional plan prose would remove — they are execution-time work, not a design gap, and the plan correctly names both as costs rather than hiding them.

## Blockers

None. R-12 (session order-count ceiling) is open but explicitly out of scope and is not pre-empted by this item. No operator-reserved value is read, assigned, or implied.
