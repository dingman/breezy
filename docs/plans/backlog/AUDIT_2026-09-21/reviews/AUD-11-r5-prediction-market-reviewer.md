# AUD-11 — Round 5 (delta) — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-11-point-in-time-backtest-guard.md
SHA256: 4b6c4d03b734106ebef25147cf5a906a34cc986d2209a33a63085f3cc38ed603
Round: 5 (delta re-confirmation after in-place edit to close mle-reviewer's
round-4 MINOR)
Reviewer: prediction-market-reviewer (independent, blind)
Lens: settlement scenario construction, what was tradable at decision time,
point-in-time discipline for backtest/replay inputs.

## §13 review-history reconciliation

Round-4 MINOR (mle-reviewer, 99/100 — my own round-4 score was 100/100 and
found nothing): `assert_available_before_decision`'s exception-aggregation
semantics were unspecified. **Disposition: VERIFIED FIXED.** §6 item 1 now
states the guard scans every record in one pass and, on any violation,
raises a single `LookAheadRecordError` carrying `offending_records:
tuple[Data, ...]` (violating records, input order preserved) rather than
raising on the first hit. §6 item 2's call site paragraph now derives `N =
len(exc.offending_records)` explicitly and states the call site "does NOT
independently re-filter `records`." §7 step 2 adds a third RED fixture
(mixed violating/non-violating records; asserts `offending_records` contains
exactly the violating ones, input order preserved, and `len(offending_records)`
matches the violation count). §8's documenting-assertion bullet now also
requires `N` to be confirmed equal to `len(exc.offending_records)` for the
known tape (and, for this tape, equal to `len(records)`, since every record
is expected to violate). This is a complete, testable specification, not a
restated ambiguity.

## Checks performed this round (delta-scoped, per coordinator's brief)

1. **Does raising on the late records stop the default branch from still
   using those records for settlement-scenario construction?** No — and
   correctly so. Re-read §6 item 2 in full: `real_observed, real_records =
   _select_highest_revision_readings(records, stations=("NYC","MIA"),
   require_final=False, raise_on_missing=True)` is a SEPARATE call from
   `assert_available_before_decision(records, ...)` — the guard call is
   described explicitly as "a documenting/regression assertion, not a
   filter," and the call site "catches `LookAheadRecordError` ... rather
   than propagating." `real_observed`/`real_records` (used by
   `build_settlement_scenarios(real_observed_by_station=real_observed, ...)`
   at line ~1805 and the JSON output) are derived from `_select_highest_
   revision_readings`, not from the guard's return value or its exception —
   the guard has no data-flow connection to `real_observed_by_station` at
   all, it only observes and logs. This is unchanged by the round-5 edit
   (the edit only changed what the guard's exception carries and how N is
   computed from it) and is exactly the plan's own stated design: late
   records are excluded from `weather_data`/`BacktestEngine` (never fed to a
   decision) but remain the correct, sole source for post-hoc
   settlement-scenario construction. No regression introduced.
2. **Is the preliminary-only / `raise_on_missing` behaviour verified in
   round 4 untouched?** Confirmed untouched. §6 item 2's
   `_select_highest_revision_readings` signature, the `_load_real_
   observations`/`_settled_readings` thin-wrapper bodies, the
   `raise_on_missing=True`/`raise_on_missing=False` split, §7 step 4's
   missing-station RED fixtures, and §9's preliminary-only-print failure
   case are byte-identical to Revision 4 (diffed by re-reading each touched
   line number the coordinator named — §6 item 1, §6 item 2's call-site
   paragraph, §7 step 2, §8's documenting-assertion bullet, §13 — none of
   which overlap the selection-helper/missing-station text). The edit is
   scoped exactly as the coordinator described: aggregation semantics only.
3. Re-read the full `assert_available_before_decision` call-site paragraph
   (§6 item 2) and §8's corresponding bullet for internal consistency: both
   now consistently describe a single collect-then-raise pass, a call site
   that reads `N` off the exception object rather than re-scanning, and an
   acceptance criterion tying `N` to both `len(exc.offending_records)` and
   (for this specific tape) `len(records)`. No contradiction between the two
   sections.
4. Re-read §7 step 2's three fixtures for construction validity: fixture 1
   (single violator, raises), fixture 2 (exact equality, does not raise),
   fixture 3 (mixed set, `offending_records` exactly the violators in input
   order, `len` matches) — together these fully specify and test the
   aggregation contract described in §6 item 1; nothing is asserted in §6/§8
   that isn't independently testable from §7's fixtures.

No new defect, MATERIAL or MINOR, found in the edited sections or in their
interaction with the unedited sections.

## Per-criterion points (caps: 20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 20/20 — unchanged from round 4;
  the edit is a specificity fix, not a fidelity change, and does not touch
  the guard/settlement-scenario data-flow separation this criterion depends
  on.
- Technical correctness and evidence grounding: 20/20 — the collect-then-
  raise design is internally consistent, does not alter the guard's
  pure-function/no-I/O status, and does not create any new dependency
  between the guard's exception and `real_observed_by_station`'s
  construction (checked directly, see item 1 above).
- Implementation specificity and feasibility: 15/15 — the previously
  unspecified aggregation behaviour (mle-reviewer's round-4 MINOR) is now
  fully concrete: exact exception field name, exact ordering guarantee,
  exact call-site derivation rule (no re-filter).
- Acceptance criteria and validation quality: 20/20 — §7 step 2's new
  fixture and §8's N-equals-`len(offending_records)` (and, for this tape,
  N-equals-`len(records)`) criteria make the aggregation contract
  independently testable and falsifiable, closing the one gap that kept
  round 4's mle-reviewer score at 99/100.
- Autonomous operation, failure handling and recovery: 15/15 — unchanged;
  the guard remains a pure, in-memory, no-I/O scan; collecting all
  violations instead of raising on the first adds no new failure surface
  and does not change the guard's offline-only, non-runtime status.
- Portfolio alignment, scope, dependencies: 10/10 — unchanged.

**Total: 100/100.**

## Required changes to reach 100

None.

## Blockers

None. This item requires no operator or strategy-lead ruling — code/test
hygiene fix and a read-only survey, both within build authority. (Note per
the coordinator's instruction: the plan's own §13 "READY" note is not relied
on here — this score is derived independently from the sections re-read this
round.)
