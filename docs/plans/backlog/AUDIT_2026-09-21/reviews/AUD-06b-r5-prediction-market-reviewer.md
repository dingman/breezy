# AUD-06b — Round 5 (FINAL) — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-06b-bounded-allocation-sizing.md
sha256: d3d26c2fba84fb0d812c7030b4770bf76ae1110d316e5c42b321c8b21a90dec0
Round: 5 (final)
Reviewer: prediction-market-reviewer (portfolio accounting / risk)

## MATERIAL defect from round 4 — re-verified fixed, with the exact command run myself

Ran, verbatim, `/usr/bin/grep -rn "qty=" src/breezy/strategy src/breezy/adapters/polymarket_us/exec
src/breezy/runtime` (excluding `__pycache__` binary matches). **Result: exactly 58 text matches
across 20 files** (the plan's "14 files" figure in the coordinator's summary undercounts;
independently confirmed 20 distinct files by `cut -d: -f1 | sort -u`, but this does not affect the
match-count claim, which I verified separately below).

**Line-by-line reconciliation, done programmatically, not by eye.** I extracted every `file:line`
pair from my own grep run and every `file:line` pair the plan's D6-R "line-by-line accounting"
paragraph claims (R1–R13 plus the "remaining matches" list), and diffed the two sets:

- Every one of my 58 actual matches is claimed by exactly one row in the plan's accounting.
- Every line the plan claims is present in my actual grep output.
- **Zero unmatched lines in either direction.** The enumeration is genuinely complete relative to its
  own cited command — the exact property round 4 found violated.

Spot-checked the two previously-missing sites and the one newly-surfaced class:
- `cli_settlement_print_lock/strategy.py:938-939` — CONFIRMED verbatim: `qty={signed_delta:+.1f}`
  co-emitted with `limit={limit_price}` and `edge={decision.edge:.3f}` in one log record (R7).
- `runtime/backtest_harness.py:845-846` — CONFIRMED verbatim: `qty={position.quantity}` co-emitted
  with `avg_px_close={position.avg_px_close}` (R8).
- `PositionMonitorSummary.to_dict` (`monitor_records.py:357-358`) — CONFIRMED verbatim: `"fill_px":
  str(self.fill_px)` and `"held_qty": str(self.held_qty)` in the same persisted mapping (R11), a
  genuinely new class the round-4 record did not name. Also independently found (not claimed by the
  plan under a separate label, but consistent with R11's stated scope) that `PositionMarkRecord.
  to_dict` (`:156-176`) carries `mark_vwap` (a price) alongside `held_qty` in the same persisted
  record — matches the plan's R11 disposition, which names `PositionMarkRecord` and covers it under
  the same fifth test.
- `running_extreme_lock/strategy.py:430-431` — CONFIRMED the qty+`edge` co-emission the widened
  forbidden-token list (`edge` added) is meant to catch (R9).

The fifth test (`test_no_evidence_artefact_writer_copies_the_duplicate_fill_records_qty_and_price_
together`) genuinely closes the round-4 MINOR (R2's enforcement claim was broader than its backing
tests); it is present in the plan body (§7 step 3), not only in §13, and its scope (evidence-writing
paths under `scripts/analysis/`, `scripts/venue/`, plus the two named persistence modules) matches
what R2/R11's dispositions require.

**This defect is closed. The enumeration is complete, checkable, and independently reproduced.**

## New check requested by the coordinator: does the `_REGISTERED_CONSTANT_QTY_SITES` allowlist stay safe once a dormant family's sizing stops being constant, and is that forced by a test?

**No, and this is a real, distinct gap — not the one round 4 found, but adjacent to it.** The
mechanism (§7 step 3) pins the **exact source text of the qty expression at the log/emission site**
(e.g. `signed_delta` at `running_extreme_lock/strategy.py:430`, `position.quantity` at
`backtest_harness.py:845`) and re-fires RED if that pinned text changes. I checked what this
mechanism can and cannot detect:

- **It catches:** someone editing the log line itself — adding a price token next to the pinned qty
  expression, renaming the qty variable at that call site, or otherwise changing what the emission
  statement interpolates. This is the majority of realistic edits and the mechanism is sound for it.
- **It does NOT catch:** a future change that makes the pinned qty expression's *value* cap-derived
  while leaving the *expression text at the emission site* unchanged. Concretely: if a later item
  extends sizing to `running_extreme_lock` by changing how `signed_delta` is *computed* earlier in
  the same function (e.g. deriving it from a per-position cap instead of the family's own
  position-delta logic), the log line `f"ORDER {contract.instrument_id} qty={signed_delta:+.1f} "` is
  syntactically unchanged, the pinned expression text `signed_delta` still matches, and the
  standing scan test stays GREEN — while the site now silently reconstructs an operator-reserved
  value through the log, exactly the failure class D6-R exists to prevent. The disposition text for
  R7/R9 ("its qty stays constant... the day anyone derives a cap-bearing qty here the test goes RED
  before the line ships") asserts a guarantee the expression-text pin does not actually provide,
  because the pin is syntactic, not semantic.
- This is genuinely out of THIS item's live diff — AUD-06b's own sizing code (S2/S4b) only touches
  `decision.py`, `config.py`, `continuous_strategy.py`, `operator_controls.py`, `trial_scorer.py` for
  the `pm_us_crh_v4`/continuous family, never `running_extreme_lock` or the other dormant families —
  so nothing in this item's own change re-derives `signed_delta`. The gap is in the *strength of the
  guarantee the standing guard claims to provide about the future*, not in this item's own live
  behaviour today.

**Defect: MINOR.** Fixable by a text-level change to the guard's own specification, not by an
operator ruling or another item's scope:
**Required change:** either (a) state explicitly, next to each `_REGISTERED_CONSTANT_QTY_SITES`
entry's "the test goes RED before the line ships" claim, that the guard is a **syntactic** pin over
the emission site only and does not extend to semantic changes in how the pinned expression is
computed upstream — so the claim is accurate rather than overstated — and add one companion rule:
any PR that adds sizing/allocation logic to one of the currently-dormant families named in R7/R9 must
remove that family's registry entries in the same change (a review-time rule, since a fully
mechanical version would require hashing each family's whole order-construction function, which is
disproportionate scope for this item); or (b) strengthen the pin to cover the enclosing function's
source (e.g. a content hash of the function that assigns the pinned variable, not just the log line),
closing the gap mechanically rather than by convention. Either is sufficient; (a) is the
proportionate one given this item's own scope never touches those families.

## Defects

1. **MINOR** (new this round): the `_REGISTERED_CONSTANT_QTY_SITES` allowlist's guarantee is
   overstated relative to what its syntactic expression-pin mechanism actually enforces. Required
   change stated above.

No MATERIAL defect remains — round 4's finding is fixed and independently reproduced.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **20** — the D6-R enumeration is now genuinely complete
  against its own cited method, independently re-verified line-by-line; the fifth test closes the
  evidence-writer gap; R11's newly surfaced persisted-record class is real and correctly handled.
- Technical correctness and evidence grounding (20): **19** — every one of the 58 matches is
  correctly accounted for and every disposition I spot-checked (R7, R8, R9, R11) is accurate against
  source. −1 for the MINOR defect: the allowlist's "the test goes RED before the line ships"
  guarantee is stated more strongly than the syntactic pin mechanism actually delivers.
- Implementation specificity and feasibility (15): **13** — the thirteen-row table, the five named
  tests, the pinned-expression registry and the falsifiable evidence requirement (a match with no
  R-row fails AC #5) are all concrete and independently checkable, which I did. Held below full marks
  because the offline sweep driver (step 7a) is still scoped but unwritten and depends on an AUD-06a
  entry point that does not exist yet (BLOCKER-A) — carried, unrelated to this round's fix.
- Acceptance criteria and validation quality (20): **20** — AC #5 now requires the grep output, its
  count and a per-match R-row mapping, with an unmapped match a failing criterion; I reproduced this
  requirement myself and it holds.
- Autonomous operation, failure handling, recovery (15): **12** — unchanged from round 4: every gate
  and clamp stays fail-closed; rollback genuinely cannot act on already-open positions, a venue
  property this plan correctly does not claim to fix.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11's field-level evaluation
  contract, fixed baselines, explicit "can REDUCE ROI" row and falsifier are unaffected by this
  round's change.

**Total: 94/100**

## Required changes to reach 100

1. Fix the MINOR defect: state the syntactic-only scope of the `_REGISTERED_CONSTANT_QTY_SITES` pin
   explicitly, and add the companion review-time rule (or the stronger function-hash mechanism) so a
   future item cannot silently make a "constant qty" site cap-derived while leaving the pinned
   expression text unchanged.

## Blockers (named separately, not scored as deductions)

- **BLOCKER-A** — AUD-06a's validated qty envelope and staleness predicate.
- **BLOCKER-B** — AUD-02's family-scoped edge estimate with a CI excluding 0.
- **BLOCKER-C** — operator ruling, R-12, on the permit's session order-count ceiling.
- **BLOCKER-D** — operator ruling on whether the current per-position cap is still the intended
  per-order spend once qty is derived from it.
