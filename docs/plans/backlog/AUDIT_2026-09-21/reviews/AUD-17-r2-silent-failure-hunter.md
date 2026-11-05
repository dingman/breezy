# AUD-17 review (round 2)

**Plan file sha256:** 3c6a9620311e66bcbebb7810d9345bfe24503b8fe74b709f984b3f067fc5aff4
**Round:** 2
**Reviewer:** silent-failure-hunter (independent, blind)

## Round-1 defect verification (my own R1 record: two MATERIAL findings)

1. **"Assertion 1 (per-position denial) underspecified relative to assertion 2 — the vacuous-pass
   shape"** — FIXED, and the fix uncovered a round-1 factual error the revision correctly
   corrected. I re-read `src/breezy/adapters/polymarket_us/operator_controls.py:118-126` and
   `exec/client.py:3480-3540` directly this session: the per-position ceiling is raised as a
   **plain `LiveTradingPermissionError`** (confirmed verbatim: *"raised ONLY by the daily-budget
   branch… The per-position ceiling and the clock-rewind branch stay plain
   `LiveTradingPermissionError`"*) — it has no dedicated subclass, so it genuinely cannot be
   pinned by exception type alone the way `DailyBudgetExhausted`/`SessionNotionalExhausted` can.
   §6 now uses three conjoined assertions instead — exact-type discrimination
   (`type(exc) is LiveTradingPermissionError`, confirmed this excludes the two named subclasses
   since `type() is` does not match subclasses), reason-equality against an **imported** constant
   (never a literal, so the assignment-scan's layer B stays unaffected), and a **differential**
   (the same order, same composition, same permit, admitted when only the per-position ceiling is
   raised) — which is the correct, structural answer to "denied for the right reason vs an
   unrelated upstream veto," since the differential is immune to *any* other veto changing
   behaviour by construction. **Genuinely and rigorously fixed** — not just accepted in prose.
2. **"No positive-control deliverable — all four assertions could pass vacuously"** — FIXED.
   §7 17b step 1 scopes `test_the_live_composition_admits_an_order_when_both_controls_are_
   generous` **first**, before any denial test, and §8 item 3 states explicitly a denial
   transcript without a green ADMIT first is not acceptance. §9 states the vacuity risk and its
   two closing guards (ADMIT + differential) directly, rather than leaving it implicit.
   **Genuinely fixed.**

## Claims verified this session (fresh read of the whole revised plan)

- `exec/client.py:3480-3540` — read verbatim: `submit_veto` at `:3484-3487`,
  `assert_live_order_submission_permitted` at `:3489-3495`, `except SessionNotionalExhausted`
  at `:3497`, exit-side branch `is_exit_side = order.side == OrderSide.SELL` at `:3520`, guard
  `if not is_exit_side:` at `:3522`, `authorize_order_cost` at `:3524-3528`, `except
  DailyBudgetExhausted` immediately after, bare `except LiveTradingPermissionError as exc:` at
  `:3531`. All of §2's three-cause table and §6's gate-ordering citation
  (`submit_veto → assert_live_order_submission_permitted → exit-side branch →
  authorize_order_cost → reconcile check → intent latch`) match the artefact exactly, in order.
- `operator_controls.py:118-126` — CONFIRMED verbatim, including the operator-ruling comment the
  plan quotes.
- `tests/unit/test_operator_reserved_controls.py:708` —
  `def test_the_mechanism_has_no_production_call_site_yet()` — CONFIRMED at the exact line the
  plan cites, appropriately scoped as a re-verification step (§7 17a step 3) rather than resolved
  inline, since resolving it requires reading the full test body against the AM-3 disposition —
  correctly deferred to the executing session, not a gap in the plan.

## Defects

No MATERIAL defect found this round. The composition-boundary test design (real manifest, real
dispatch, real exec-client factory, real ledger, real permit, unstubbed gate ordering, hand-built
synthetic order with the reason for that bound stated structurally rather than as a shortcut) is
sound, and the vacuity risk this review's lens specifically targets is closed by two independent,
structurally-justified mechanisms (ADMIT-first gating, and the per-position differential) rather
than one. The no-POST assertion on every denial case, run under the no-egress sandbox, is a
second independent guard against "denied" silently coming to mean "attempted."

**MINOR** — §7 17a step 2 ("determine layer B's exact tolerance for the imported-constant
assertion style… if the answer is no, assertion 3 [the differential] carries attribution alone")
correctly hedges the reason-equality sub-assertion, but the plan does not state what happens to
the *test's own pass/fail shape* if that fallback triggers — presumably it still passes on
type-discrimination + differential alone, which is sufficient per §9's stated redundancy, but
this should be one sentence rather than left to be inferred.

## Per-criterion points

| Criterion | Cap | Points |
|---|---|---|
| Fidelity to audit gap and completeness | 20 | 19 |
| Technical correctness and evidence grounding | 20 | 19 |
| Implementation specificity and feasibility | 15 | 14 |
| Acceptance criteria and validation quality | 20 | 19 |
| Autonomous operation, failure handling and recovery | 15 | 14 |
| Portfolio objective alignment, scope and dependencies | 10 | 10 |
| **Total** | **100** | **95** |

## Required changes to reach 100

1. State explicitly, in §7 17a step 2 or §9, that if the reason-equality fallback triggers, the
   test still passes on type-discrimination + differential alone (already true per the plan's own
   redundancy argument, but not stated as a pass/fail consequence).

## Blockers

None. R-12 (session order-count ceiling) remains correctly out of scope and unruled-on; no cap
value is read, assigned, or implied anywhere in the plan.

## Review record path
docs/plans/backlog/AUDIT_2026-09-21/reviews/AUD-17-r2-silent-failure-hunter.md
