# AUD-03 — Round 1 review (mle-reviewer, ML/production-engineering lens)

Plan: AUD-03-daily-decision-funnel-digest.md
sha256: 4e2b1bce1167be650e4c005c8041b2102c0bd0a5c52beac2a97dd93f7cd4dd1e
Round: 1
Reviewer: mle-reviewer (independent, blind)

## Claims verified against source

- `HaltDetector` (`halt_detector.py:264-421`), `STRUCTURAL_HALT_REASONS`
  (`:138-154`) = `{fee_schedule_mismatch, shorts_disabled,
  instrument_unresolved, settlement_halt, no_side_first_order_pending}` —
  CONFIRMED exact; `observation_ambiguous`/`illegal_cell` are NOT members —
  CONFIRMED.
- `zero_evaluation_halt` fix `e83fc5c` — CONFIRMED in `git log`; matches the
  plan's "already CLOSED" claim.
- `docs/core/PROGRESS.md:103-128` — read directly: CONFIRMED still says
  "Fix (not yet applied)" though `e83fc5c` landed same day. The plan's
  "PROGRESS.md is stale" claim (§3, §12) is independently verified true,
  not merely asserted.
- **Offer-tape schema** (`offer_tape.py`, `OfferTapeRecord`) — read the
  full dataclass and `to_dict()`. Every field the plan cites (`station`,
  `hour_lst`, `reason`, `illegal_cell`, `ask`, `break_even`, `side`,
  `decision`) is CONFIRMED present, by exact name, and `decision` really is
  a first-class field (`decision: str = "refuse"`), not something the plan
  invented — this is a load-bearing, precisely-grounded claim.
- `resolve_alert_sink` (`runtime/health.py:579-610`) — CONFIRMED: unset env
  returns `LoggingAlertSink()`, configured returns a `TeeAlertSink`
  (log-first, webhook second) — matches the plan's delivery-mechanism
  claim exactly, including the "log branch first" ordering the plan does
  not even need to restate but which supports its "already-proven" claim.
- `evaluate_decision` returns `Refuse("illegal_cell")` and
  `Refuse("observation_ambiguous")` as the literal `reason` strings
  (`decision.py:342-344,350-351`) — CONFIRMED, so the plan's funnel-stage
  definitions keyed on the `reason` string (§6.2) are grounded in what the
  tape actually writes, not a re-derivation.

## Defect found (schema/label contamination — production-monitoring lens)

**MATERIAL** — The offer-tape JSONL is NOT exclusively an entry-hunt log.
`OfferTapeRecord`'s own docstring (verified, read verbatim) states the
`decision` field's INC-E3 extension adds `"exit_fired"`/`"exit_refused"`
values "for the intra-day position monitor's own exit-decision rows -- a
DIFFERENT source (`"position_monitor"`, never `"quote_tick"`/`"depth"`),
additive and never read by the entry-hunt's own consumers." The file the
digest reads (`offer_tape_<date>.jsonl`) is the SAME sidecar for both row
families, distinguished only by the `source` field (`quote_tick`/`depth`/
`no_side_shadow` vs `position_monitor`).

AUD-03 §6.2 defines funnel stage 1 ("decisions emitted") as every row in
the file, and does not filter on `source`. This is a real train/serve-
style contamination risk for the digest itself: once EXIT-1 (position-
monitor exits) is armed — it is currently "BUILT, UNARMED" per gap G-12,
not hypothetical, and AUD-01a's own §6.5 explicitly anticipates this class
of future-state change — every exit-decision row (`fired`/`refused`) would
be counted into the entry funnel's denominator ("decisions emitted") even
though it is a structurally different event (governed by `exit_rule`/
`exit_decision`, not the entry `reason` taxonomy), silently inflating stage
1 and skewing every downstream percentage in the digest without changing
what actually happened on the entry side. Today (EXIT-1 unarmed, per
PROGRESS.md) this does not corrupt current output, so the RED-test fixture
pinned against the 09-20 data (§7 step 1) would still pass — which is
exactly the failure shape this reviewer's brief warns about ("compute a
digest whose counts are reconcilable with the offline funnel study"): the
reconciliation holds today and silently breaks the day EXIT-1 arms, with
no test in §7 that would catch it.

Required change: `funnel_for_day` (§6.2/§7 step 1) must filter rows to
`source in {"quote_tick", "depth", "no_side_shadow"}` (or equivalently
`exit_rule is None`) before computing any stage count, and §7 should add a
RED test with a synthetic fixture mixing an entry-hunt row and a
`position_monitor` exit row, asserting the exit row is excluded from every
funnel stage. This is a small, scoped addition — it does not change the
plan's architecture, dependency set, or delivery mechanism.

## Other observations (not defects)

- §9's "missing/rotated tape file" fail-closed handling (named, non-
  CRITICAL diagnostic distinguishing absence from zero) directly answers
  this review's "what happens on a day the node never ran" challenge, and
  is well-specified: a missing file produces a named diagnostic, not a
  misleading zero-funnel digest. This is a correct, specific answer to a
  question production digests routinely get wrong (absence vs. zero).
- The exact-reproduction regression test against
  `DECISION_FUNNEL_2026-09-20.md`'s published six-stage table (§8) is a
  strong, concrete backstop for schema drift and stage-definition drift —
  provided the source-filtering fix above is folded in before that fixture
  is built, so the fixture itself is built from entry-hunt rows only (as
  the plan already intends in spirit, just not stated in the filter logic).
- Persisted-schema stability: the plan correctly treats the tape schema as
  an external contract it must not duplicate/re-derive (§6.2, "reuses no
  strategy import... cannot silently diverge from or duplicate the live
  decision logic") — this is the right DRY posture for a monitoring
  consumer of a production decision log.

## Per-criterion points

- Fidelity to audit gap and completeness: 19/20 — matches the plan's own
  self-score; correctly reuses the evidence doc's funnel definition rather
  than inventing a new one.
- Technical correctness and evidence grounding: 17/20 (down from the
  plan's self-scored 19) — every citation checked is exact, but the
  `source`-field filtering gap is a genuine grounding miss: the plan reads
  and quotes-adjacent fields from the same dataclass without noticing the
  field that would contaminate its own funnel once a sibling feature
  (EXIT-1) arms.
- Implementation specificity and feasibility: 15/20 (down from 17) — the
  script/unit shape is concrete and well-modelled on a sibling unit; the
  missing `source` filter is a small but real correctness gap in the one
  piece of business logic (`funnel_for_day`) this plan actually specifies.
- Acceptance criteria and validation quality: 16/20 (down from 18) — the
  exact-reproduction regression test is strong, but does not (yet) guard
  against the exit-row contamination case, which is exactly the kind of
  silent-divergence scenario a monitoring digest's test suite should pin.
- Autonomous operation, failure handling, recovery: 14/15 — unaffected;
  fail-closed missing-file handling is specific and well-reasoned.
- Portfolio alignment, scope, dependencies: 9/10 — correctly independent
  of AUD-01/AUD-02; correctly scoped away from `HaltDetector` semantics.

**Total: 90/100.**

## Required changes to reach 100

1. Add a `source`-based filter (or equivalent `exit_rule is None` guard) to
   `funnel_for_day` before any stage is counted, and a RED test with a
   mixed entry+exit-row fixture proving the exit row is excluded (§6.2,
   §7 step 1/3).
2. Once (1) lands, confirm the 09-20 exact-reproduction fixture (§8) is
   built only from entry-hunt-shaped rows (it should already be, since
   EXIT-1 was unarmed that day, but the filter should be explicit in code,
   not implicit in the data).

## Blockers

None. This plan requires no operator or strategy-lead ruling; the MATERIAL
defect above is a scoped implementation fix within the plan's own stated
boundaries (§5 "in scope"), not a design decision requiring a ruling.
