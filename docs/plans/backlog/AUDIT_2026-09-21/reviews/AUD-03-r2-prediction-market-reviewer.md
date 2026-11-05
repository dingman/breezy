# AUD-03 review — round 2 — prediction-market-reviewer

Plan: AUD-03-daily-decision-funnel-digest.md
sha256: 5073fc526077a53e31a43a91593de626ed2100bbdb7c3fec66b417275e4049f5
Round: 2
Reviewer: prediction-market-reviewer (blind, independent)

## §13 review-history verification

- mle-reviewer round-1 MATERIAL (offer-tape shared sidecar, entry+exit contamination):
  CONFIRMED the concept is fixed — §6.2 now filters before counting any stage, and §7 step 3
  adds a mixed-fixture RED test. But see the NEW material finding below: the filter's own
  literal values are wrong, so the concept is right while the mechanism is broken.
- prediction-market-reviewer round-1 MATERIAL (margin>0 tautology `ask < break_even`):
  CONFIRMED FIXED. Re-verified directly against `decision.py:399-404`
  (`break_even = price + _fee(price, inputs.fee_coefficient); if not (p_bound > break_even):
  return Refuse("edge_below_break_even", ...)`) and `_finalize_take`'s call sites (:360-368,
  :442-449) confirming `p_bound` is `P_HOLD_LOWER.get(key)` for YES and
  `1 - P_HOLD_UPPER.get(key)` for NO. §6.3's redefinition
  (`p_bound is not None and p_bound > break_even`) is now the EXACT live rule, byte-for-byte.
  `offer_tape.py:117-120` confirms `p_bound`/`break_even` are real, persisted fields. This
  correction is technically sound and well-evidenced.

## Claims verified this round (fresh, whole-plan pass) — and one REFUTED

- `decision.py:402-404` margin-stage citation — CONFIRMED exact (see above).
- `offer_tape.py:82-155` field list (`station`, `hour_lst`, `reason`, `illegal_cell`, `ask`,
  `break_even`, `p_bound`, `side`, `decision`, `source`, `exit_rule`, `exit_decision`) —
  CONFIRMED all fields present as named.
- `HaltDetector`/`STRUCTURAL_HALT_REASONS` §3 claim that `observation_ambiguous`/
  `illegal_cell` are NOT members — CONFIRMED against `halt_detector.py`'s closed set.
- `position_monitor.py:174-195` — CONFIRMED: exit-decision rows are written with
  `trigger="exit"`, `source="position_monitor"`, `decision` in
  `{"exit_fired","exit_refused"}`.
- **REFUTED — §6.2's entry-hunt row filter, `source in {"quote_tick", "depth",
  "no_side_shadow"}`, uses a literal that the live code never writes to the `source` field.**
  Verified directly against `continuous_strategy.py`:
  - Line 264: `Source = Literal["quote", "depth"]` — the TYPE of `OfferTapeRecord.source`
    for entry-hunt rows is constrained to exactly `"quote"`/`"depth"`.
  - Line 295 (`_snapshot_from_quote`): `source="quote"` — the value actually written for
    every quote-triggered entry-hunt row, NOT `"quote_tick"`.
  - Line 1164: `source="depth"` for depth-triggered rows — this one matches the plan.
  - Line 1776: `source="no_side_shadow"` for NO-side shadow rows — this one matches too.
  - `"quote_tick"` IS a real literal in this module, but it is a value of a DIFFERENT,
    also-real field: `Trigger = Literal["quote_tick", "on_data", "depth"]` (line 263), used
    at `trigger="quote_tick"` (line 1146) — `trigger`, not `source`. The plan's §6.2 filter
    conflates the two closed-set fields: it allowlists a `trigger` value under the `source`
    key.
  - Consequence: implemented literally against real data, the filter
    `source in {"quote_tick","depth","no_side_shadow"}` matches `"depth"` and
    `"no_side_shadow"` rows but EXCLUDES every `"quote"`-sourced row — i.e. every YES-side
    row triggered by a live `QuoteTick`, which per `_hunt_tick`'s dispatch is the dominant
    trigger path (`_on_quote` → `_snapshot_from_quote` → `source="quote"`). This directly
    threatens §8's own headline acceptance bullet: "`funnel_for_day` reproduces
    `DECISION_FUNNEL_2026-09-20.md`'s exact 09-20 table (40,796 decisions...) from a fixture
    built from real tape rows" — a fixture built from REAL 09-20 rows carries `source="quote"`
    values (per the source cited above), and the specified filter would silently undercount
    stage 1 by excluding them, unless the implementer independently notices and fixes the
    typo (at which point the plan, not the implementer, should have specified it correctly).
  - The offer-tape module's OWN docstring (`offer_tape.py:145-146`, cited by the plan as
    verified) is itself imprecise here — it glosses the discriminator as "never
    `"quote_tick"/"depth"`" for entry rows, which reads as though `"quote_tick"` were a valid
    `source` value; it is not (it is a `trigger` value). The plan trusted this docstring's
    prose instead of the actual `source=` assignment call sites, and inherited the error.
- **RELATED, also REFUTED — §6.2's claimed equivalence, "(equivalently, `exit_rule is
  None`)".** Verified against `position_monitor.py:169-170`: `rule_value = outcome.rule.value
  if outcome.rule is not None else None` — an exit-decision row CAN carry `exit_rule=None`
  when the outcome never reached rule selection (confirmed by `offer_tape.py`'s own docstring:
  "`None` for every entry-hunt row... and for [a decision] that never even reached rule
  selection"). So `exit_rule is None` is NOT equivalent to "is an entry-hunt row" — some
  `position_monitor`-sourced rows (early-refused exits) would pass this alternative filter
  too, re-contaminating stage 1 in exactly the way the mle-reviewer's round-1 finding
  intended to close. The correct, available discriminator is `source != "position_monitor"`
  (or the corrected allowlist `source in {"quote", "depth", "no_side_shadow"}`), not
  `exit_rule is None`.

## Defects

- **MATERIAL — §6.2 (and §3's schema description it is grounded in): the entry-hunt row
  filter's `source` allowlist contains a wrong literal (`"quote_tick"` instead of `"quote"`)
  and its stated "equivalent" fallback (`exit_rule is None`) is not actually equivalent.**
  This is the single piece of business logic this plan owns (per its own §6.3 DRY framing:
  "it reports what the strategy already decided... never re-deriving a decision from
  scratch") and it is currently specified incorrectly at the literal-value level, in a way
  that would either (a) silently exclude the majority of entry-hunt rows from every funnel
  stage if implemented as the primary filter, or (b) silently re-admit some exit rows if an
  implementer instead relies on the plan's own claimed "equivalent" `exit_rule is None`
  check. Round 1 caught the CONCEPT (need a filter); this is a round-2 finding because it is
  a defect in the revision's own corrected text, at a level neither round-1 reviewer tested
  (the literal string values, checked against the actual `source=`/`trigger=` assignment
  call sites rather than the module docstring).
  - Required change: fix §6.2 to `source in {"quote", "depth", "no_side_shadow"}` (matching
    `continuous_strategy.py:295,1164,1776`), OR simplify to the single correct discriminator
    `source != "position_monitor"`; remove the false "(equivalently, `exit_rule is None`)"
    claim entirely, since it is not a safe substitute. Add a RED test asserting the filter
    against a real `source="quote"` row is INCLUDED (the current §7 step 3 mixed fixture
    tests exclusion of a `position_monitor` row but never asserts inclusion of a
    `"quote"`-sourced row, so it would not have caught this).
  - This also means §8's "byte-for-byte regression guard" against the real 09-20 tape cannot
    be trusted to pass as specified — the acceptance criterion itself is downstream of this
    defect, not merely the implementation.

## Per-criterion points

- Fidelity to audit gap and completeness: 17/20 — the funnel shape, delivery mechanism, and
  scope boundaries (no HaltDetector change, no schema change) are all correctly reasoned;
  deducted because the one piece of original logic this plan specifies is wrong at the value
  level, undermining "the digest reports what the strategy already decided" for the majority
  of real rows.
- Technical correctness and evidence grounding: 11/20 — every citation the plan makes is to
  a real file:line, but the load-bearing claim about what `source` actually contains is
  factually wrong (confirmed by direct read of the assignment sites), and the claimed
  filter-equivalence is also wrong; both are central to this plan's one piece of business
  logic, not peripheral details.
- Implementation specificity and feasibility: 8/15 — the aggregation function's stage
  definitions (rung resolved / cell legal / priced / margin>0 / orders) are all correctly
  and concretely specified against source; the row filter that gates entry into the funnel
  in the first place is not correctly specified and would need correction before an
  implementer could build it as written.
- Acceptance criteria and validation quality: 11/20 — the tautology-vs-real-rule margin test
  (§7 step 4) is a genuinely strong, well-targeted fixture; the mixed entry/exit fixture
  (§7 step 3) tests exclusion but never tests that a real `"quote"`-sourced row is included,
  so it would pass today while the filter silently drops most real entry-hunt rows — the
  regression guard against the real 09-20 table (§8) is not actually achievable with the
  filter as specified.
- Autonomous operation, failure handling, recovery: 13/15 — missing/rotated-file and
  partial-day handling are specific and fail-closed as designed; deducted slightly because a
  silently-wrong filter is exactly the "misleading zero-ish digest" failure mode §9 warns
  against for a different case (missing file) but does not itself guard against for this one
  (a systematically undercounted, not literally absent, funnel would not trip any of the
  named failure-case tests).
- Portfolio alignment, scope, dependencies: 10/10 — correctly independent of AUD-01/AUD-02;
  the AUD-02 §6.4 digest-field note is recorded without a hard dependency either direction
  (see AUD-02's own review for the ownership gap on that specific line, which is AUD-02's
  defect to fix, not double-counted here).

**Total: 70/100.**

## Required changes to reach 100

1. Fix §6.2's entry-hunt filter to the real `source` literals (`"quote"`, not `"quote_tick"`)
   or to `source != "position_monitor"`; drop the false `exit_rule is None` equivalence claim.
2. Add a RED test asserting a real `source="quote"` row is counted at stage 1 (inclusion, not
   just the existing exclusion test for a `position_monitor` row), so the corrected filter is
   pinned against both failure directions.
3. Re-verify the §8 byte-for-byte 09-20 reproduction bullet is actually achievable once the
   filter is corrected (it should be, since 09-16/09-20 predate EXIT-1 and carry no
   `position_monitor` rows regardless of the filter's correctness — but the acceptance
   criterion should not rely on that coincidence going forward).

## Blockers

None requiring operator/strategy-lead input or unavailable evidence — this is a plan-text
correction against code already in the repo, fully checkable and fixable without a ruling.
