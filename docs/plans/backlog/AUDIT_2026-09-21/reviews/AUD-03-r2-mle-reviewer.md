# AUD-03 — Round 2 review (mle-reviewer, ML/production-engineering lens)

Plan: AUD-03-daily-decision-funnel-digest.md
sha256: 5073fc526077a53e31a43a91593de626ed2100bbdb7c3fec66b417275e4049f5
Round: 2
Reviewer: mle-reviewer (independent, blind)

## Round-1 disposition check (both accepted MATERIAL defects actually fixed?)

- **mle-reviewer round-1 MATERIAL** (offer-tape shared sidecar contamination
  — exit-decision rows would silently inflate the entry funnel once EXIT-1
  arms): re-verified directly against current source this round.
  `OfferTapeRecord.to_dict()` (`offer_tape.py:194-248`) — CONFIRMED present:
  `"source"` (`:210`), `"exit_rule"` (`:228`), `"decision"` (`:227`) are all
  real, serialized fields. §6.2's filter (`source in {"quote_tick", "depth",
  "no_side_shadow"}`, equivalently `exit_rule is None`) is present in the
  revised plan, applied "FIRST, before any stage is counted" per the text,
  and §7 step 3 specifies a concrete synthetic fixture (one
  `source="quote_tick"` row, one `source="position_monitor"`,
  `decision="exit_fired"` row) asserting the exit row is excluded from every
  stage. **Fix CONFIRMED, executable as specified** — this is a directly
  writable unit test against the stated field names, not a vague intention.
- **prediction-market-reviewer round-1 MATERIAL** (margin>0 tautology,
  `ask < break_even` vs the real rule): re-verified directly against current
  source this round. `decision.py:402-404` (`_finalize_take`) — CONFIRMED
  byte-exact to the plan's citation: `break_even = price + _fee(price,
  inputs.fee_coefficient); if not (p_bound > break_even): return
  Refuse("edge_below_break_even", ...)`. The revised §6.3 states the stage as
  `p_bound is not None and p_bound > break_even`, matching this exactly, and
  cites the field's presence in `OfferTapeRecord` (`p_bound`, confirmed at
  `offer_tape.py:212` in `to_dict`, serialized as `str(self.p_bound)` when
  set). §7 step 4 specifies a concrete synthetic fixture: one row with
  `ask < break_even` TRUE but `p_bound <= break_even` (must NOT count), one
  row with `p_bound > break_even` (must count). **Fix CONFIRMED, executable
  and non-vacuous** — this fixture is specifically constructed to distinguish
  the two comparisons, not merely re-run the all-zero 09-16/09-20 regression
  that was blind to the original bug.

## New-defect pass on the revision itself

- **`decision == "take"` for the "orders" stage (§6.3, final bullet):**
  verified against the actual write site, not merely the dataclass default.
  `continuous_strategy.py:1483/1486/1491` sets `offer_decision_label = "take"`
  on the Take branch and `"refuse"` on both Refuse branches (default and
  fallback), which is then passed as `decision=offer_decision_label` at
  `:1544`. This is exactly the literal string the plan's stage-6 rule keys
  on. CONFIRMED, not previously flagged by either round-1 reviewer, and holds
  up under direct verification.
- **Filter-order correctness:** §6.2's filter is applied before §6.3's stage
  computation in the plan's own ordering (filter is step 2, stages are step
  3), and §7 step 2 states both the filter and the corrected margin
  comparison are "part of the function's first correct implementation, not a
  later patch" — this closes the risk (present in a hypothetical
  partially-applied fix) of one correction landing without the other.
- **No new field-name or gate-order defect found** in the revised §3
  (schema list now explicitly includes `p_bound`, `source`, `exit_rule`) or
  §9 (failure-case coverage: missing-tape-file, partial-day, future EXIT-1
  arming — the last of these now explicitly ties back to the §7 step 3
  fixture rather than asserting it by construction alone).
- **Interaction with AUD-02's escalation requirement (§12, cross-plan):**
  AUD-03's own §12 already names the AUD-02 §6.4 digest-field requirement as
  a tracked, non-blocking addition; consistent with AUD-02's text (verified
  in this round's AUD-02 review) — no contradiction between the two revised
  plans.

No MATERIAL defect found in this revision. Both round-1 MATERIAL findings are
not just claimed-fixed in §13 but are independently confirmed fixed against
current source, and the specific mixed-fixture and margin-tautology tests are
concrete enough to write directly from the plan text without any further
design decision.

## Per-criterion points (out of the brief's rubric: 20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 20/20 — correctly reuses the
  now-corrected live-rule funnel definition; correctly declines the
  fault/wait/edge classification question as separate scope.
- Technical correctness and evidence grounding: 20/20 — every citation
  checked this round (offer_tape.py field list and serialization,
  decision.py:399-404, continuous_strategy.py's decision-label write site)
  is exact.
- Implementation specificity and feasibility: 15/15 — `funnel_for_day`'s
  business logic (filter + corrected margin stage + orders stage) is now
  fully and correctly specified from a single first implementation; no
  remaining design decision is left to the implementer.
- Acceptance criteria and validation quality: 20/20 — both round-1 defect
  classes now have a purpose-built synthetic-fixture RED test (mixed
  entry/exit rows; tautology-vs-real-rule margin comparison) in addition to
  the exact-reproduction regression guard against the 09-20 evidence table;
  none of the three tests are redundant with each other, and each targets a
  distinct failure mode.
- Autonomous operation, failure handling, recovery: 15/15 — fail-closed
  missing-file/partial-day handling is specific, distinguishes absence from
  zero, and is unaffected by (and now correctly paired with) both
  corrections.
- Portfolio alignment, scope, dependencies: 10/10 — correctly independent of
  AUD-01/AUD-02 for its own acceptance; the AUD-02 cross-reference is
  additive and non-blocking, consistently described in both plans.

**Total: 100/100.**

## Required changes to reach 100

None. Both round-1 MATERIAL defects are fixed, verified against current
source rather than trusted from §13's self-report, and the revision
introduces no new defect found by this lens.

## Blockers

None. This plan requires no operator or strategy-lead ruling; it is pure
read-only aggregation and delivery over an already-shipped schema and an
already-proven alert-egress path.
