# AUD-11 — round 5 review (mle-reviewer, delta review)

Plan file: docs/plans/backlog/AUDIT_2026-09-21/AUD-11-point-in-time-backtest-guard.md
SHA256: 4b6c4d03b734106ebef25147cf5a906a34cc986d2209a33a63085f3cc38ed603 (verified via sha256sum — matches coordinator's reported value)
Round: 5
Reviewer: mle-reviewer (independent, blind to other reviewers)

## My round-4 MINOR defect — verified genuinely closed and testable

Round-4 finding: `assert_available_before_decision`'s exception-aggregation
semantics were unspecified, even though the call site's "N record(s)
excluded" log message implied N was derivable from the raised exception.

Re-read the touched sections in full against the new revision:

- **§6 item 1** (lines 259-266): now states explicitly the guard "scans
  every record in `records` in one pass and, if any violate, raises a
  single `LookAheadRecordError` carrying `offending_records:
  tuple[Data, ...]` (every violating record, input order preserved) rather
  than raising on the first" — this is a complete, unambiguous spec: one
  pass, one exception, full violator set, order-preserving.
- **§6 item 2's call-site paragraph** (lines 361-365): the log line now
  reads "...where `N = len(exc.offending_records)` (the guard's own
  aggregated count per §6 item 1 — the call site does NOT independently
  re-filter `records`)" — closes exactly the ambiguity I raised: the two
  candidate designs (guard aggregates vs. call site re-filters) are no
  longer both live; only the first is specified, and the second is
  explicitly ruled out in the same sentence.
- **§7 step 2** (lines 403-407): adds a third RED fixture — "mixing several
  violating and non-violating records; assert the raised exception's
  `offending_records` contains exactly the violating records (input order
  preserved) and `len(offending_records)` matches the violation count —
  proving the guard's aggregation semantics ..., not just first-raise."
  This is directly testable and specifically distinguishes aggregate-raise
  from fail-fast-on-first, which is the exact ambiguity that existed.
- **§8's documenting-assertion bullet** (lines 473-482): adds "The logged
  count N is confirmed to equal `len(exc.offending_records)` (the guard's
  own aggregate, per §6 item 1 — never a call-site re-filter) and, for this
  tape, to equal `len(records)` (every record is expected to violate)." The
  added `len(records)` cross-check is a genuine strengthening (not merely
  restating the spec) — for the known 2026-08-30 tape every NYC/MIA record
  is expected to violate the boundary, so N should equal the full input
  count; this is a real, falsifiable prediction the implementation run must
  satisfy, not a tautology.
- **§13**: Round 4 entry accurately records my defect and its disposition
  ("§6 item 1 now states the guard aggregates every violation into one
  `LookAheadRecordError` carrying `offending_records`, §6 item 2's call
  site now derives N as `len(exc.offending_records)`... §7 step 2 adds an
  aggregation fixture, and §8 now requires N to be confirmed equal to
  `len(exc.offending_records)`") — matches the actual diff, not overstated.

**Disposition: CONFIRMED FIXED.** The defect is closed by a concrete,
testable specification with a dedicated RED fixture, not by prose alone.

## Fresh check for anything new introduced by the edit

- The edit does not touch the "late records excluded from the decision
  feed, used only for settlement-scenario construction" rule (§3, §6 item
  2's restamp-deletion paragraph, lines 325-341) — re-read in context,
  unchanged and still internally consistent: `records`/`real_records` still
  flow only into `_select_highest_revision_readings` → `real_observed` →
  `build_settlement_scenarios`, never into `weather_data`. The aggregation
  fix is orthogonal to this rule (the guard call remains a
  documenting/regression assertion over `records`, not a filter that
  produces a different `weather_data`).
- The "collect-all" design does not weaken the RED test 2 case (§7 step 3,
  unchanged) — a single violating fixture still raises, since one-or-more
  violators trigger the exception under the new spec exactly as under a
  fail-fast spec.
- The equality-boundary case (§7 step 2's first two fixtures, unchanged)
  is unaffected: an exactly-equal `ts_init` is still not a violation, so it
  never enters `offending_records`.
- No change to `_select_highest_revision_readings`, `_load_real_observations`,
  `_settled_readings`, `_run_live_capture`, or the missing-station-contract
  fixtures from round 4 — spot-checked those regions are byte-identical to
  the round-4 revision I already verified against source.
- No new citation was introduced by this edit that requires fresh source
  verification (the change is internal to the guard's own contract, not a
  new claim about `codebase` behaviour).
- No LESSONS.md violation, no operator-cap value assigned, no Nautilus
  touch, no scope change, no acceptance criterion softened.

No new defects found.

## Per-criterion points (caps 20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 20/20 — unchanged from round 4;
  the edit is a specificity fix, not a scope change.
- Technical correctness and evidence grounding: 20/20 — unchanged; the
  chosen aggregation design (collect-all, single raise) is internally
  consistent with the guard remaining a pure function and does not
  contradict any other section.
- Implementation specificity and feasibility: 15/15 — the sole outstanding
  MINOR from round 4 is now fully specified (guard collects and exposes
  `offending_records`; call site derives N from it; re-filtering is
  explicitly ruled out) — no material design decision left to the
  implementer on this point.
- Acceptance criteria and validation quality: 20/20 — the new aggregation
  fixture (§7 step 2) and the N-equals-`len(offending_records)` /
  N-equals-`len(records)` criteria (§8) make the chosen semantics
  independently testable and falsifiable, not merely asserted in prose.
- Autonomous operation, failure handling, recovery: 15/15 — unchanged; the
  aggregation choice adds no new failure surface (still a pure, in-memory,
  offline-only scan).
- Portfolio objective alignment, scope, dependencies: 10/10 — unchanged.

**Total: 100/100.**

## Defects

None. Zero material defects remain from my lens; the round-4 MINOR is
closed with a concrete, testable specification.

## Blockers

None. Note: §13's "Readiness status: READY" is the plan author's own
self-assessment and was disregarded per the coordinator's instruction —
this review's own score (100/100, no material defects, rubric fully met)
is what supports readiness from this reviewer's lens.
