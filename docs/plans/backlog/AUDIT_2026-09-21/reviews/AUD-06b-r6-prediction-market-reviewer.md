# AUD-06b — Round 6 (delta) — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-06b-bounded-allocation-sizing.md
sha256: 6352149b3a62765fedd7babcfbea37152c22fb7dd6f470a6028d453a05ba0c66
Round: 6 (delta, final for this cluster)
Reviewer: prediction-market-reviewer (portfolio accounting / risk)

## What changed (per the supplied diff, verified against current source)

Two round-5 MINORs are addressed: (1) mle's file-count correction (14 → 20, now test-asserted), and
(2) my own finding that `_REGISTERED_CONSTANT_QTY_SITES` pinned the emission site's expression text
only, not the upstream semantics of what feeds it. I re-verified the second fix's three named sites
directly against source, since that is the fix I required.

## Content-hash pin verified at all three cited sites

- **R9 — `running_extreme_lock/strategy.py:430`.** `_maybe_submit` def at `:359`; its call
  `self._submit_delta(contract, risk_decision.clipped_quantity, decision)` is at `:408` — CONFIRMED
  exact (plan cites `:359-408`, one line short of the function's true end at `:409`, immaterial).
  `_submit_delta` def at `:410`, spanning to the `log.info` at `:430-432` — CONFIRMED (plan cites
  `:410-432`). The emission line `qty={signed_delta:+.1f} ... edge=...` at `:430` is exactly the site
  R9 registers.
- **R7 — `cli_settlement_print_lock/strategy.py:938`.** `_maybe_submit` def at `:761`; its call
  `self._submit_delta(contract, risk_decision.clipped_quantity, decision, quote)` is at `:837` —
  CONFIRMED exact. `_submit_delta` def at `:901`, spanning to the `log.info` at `:938-941` —
  CONFIRMED (plan cites `:901-941`).
- **R8 — `runtime/backtest_harness.py:845`.** `_refuse_open_positions` def at `:833`; `position` is
  drawn from `engine.cache.positions_open()` — CONFIRMED a native Nautilus cache read, with no
  Breezy-side assignment of `position.quantity` anywhere in this function. The "stated limit" (only
  `emitting_fn_sha256`, no `assigning_fn_sha256`) is honest: there is no single Breezy function that
  assigns this value, because it aggregates whichever strategy's order happened to fill, at whichever
  quantity that strategy's own (separately registered) site produced.

All three citations are exact. The RED test
(`test_a_registered_site_goes_red_when_its_upstream_assignment_changes`, mutating `_maybe_submit`'s
computation at `running_extreme_lock/strategy.py:408` while leaving `:430`'s emitted text
byte-identical, with a negative control) is coherent given the verified function boundaries: the
mutation site and the hashed function are the same function, so the test's premise holds.

## Judgment on the stated limit for Nautilus-owned/venue-reported quantities

**Honest and sufficient for the guarantee actually being claimed, not for a broader one.** The
guarantee this mechanism provides is: *a change to how a REGISTERED site's qty is computed will be
caught*, for every site where a Breezy function does the computing. Where the quantity is a native
Nautilus attribute (`position.quantity`, read generically across whichever strategy produced the
position) there is genuinely no single Breezy assignment site to hash — the actual protection for
*that* value's provenance lives at each contributing strategy's own registered emission site (R7/R9's
own two-hash pins), not at the aggregating diagnostic line in `backtest_harness.py`. I checked whether
a NEW, not-yet-registered strategy could introduce a cap-derived qty that reaches `:845` without
tripping any hash: the emission code at `:845` itself (`f"... qty={position.quantity} ..."`) is
generic and strategy-agnostic — it does not change when a new strategy is added — so R8's registered
entry continues to match regardless of which strategy's positions are open, and the general "new
co-emission anywhere in scope is RED unless registered" rule never has occasion to fire for this
specific line. The actual point of control for a new strategy's own qty derivation is that new
strategy's own emission site, which — being new — would not yet be in the registry and would
therefore be caught by the standing scan's default-deny rule at that new site. The design is
self-consistent: R8's stated limit does not create a gap, it correctly locates the control where it
actually belongs (at the producer, not at a generic downstream reader of Nautilus's own state).

## Regression sweep

- Re-confirmed the round-5 material fix (58 matches / 20 files, line-by-line reconciliation) is
  untouched by this diff except for the file-count correction itself, which now matches my own
  independent round-5 count of 20 distinct files exactly.
- Hash normalisation (comments and blank lines stripped, whitespace collapsed) is a reasonable
  engineering choice to avoid the pin firing on cosmetic edits — consistent with this repo's own
  WP-R1 false-page discipline (a guard that pages on noise gets ignored). I note this as a
  code-construction detail belonging to python-reviewer's charter, not scored here.
- No statistic, cap, or sizing formula is touched by this diff; the change is confined to the
  standing guard's own strength.

No new defect found.

## Defects

None MATERIAL, none MINOR remaining. Both round-5 findings (the file-count transcription error and
the syntactic-only registry pin) are closed with mechanisms I independently verified against source
at every cited site.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **20** — the enumeration is complete, its headline count is
  now correct and test-asserted, and the registry's guarantee now matches what it claims.
- Technical correctness and evidence grounding (20): **20** — every citation in this round's change
  (function boundaries, call sites, the Nautilus-attribute argument for R8's stated limit)
  independently re-verified exact against current source.
- Implementation specificity and feasibility (15): **15** — the two-hash registry entry, its
  normalisation rule, its RED test, and the honest stated-limit disposition for venue/Nautilus-owned
  quantities are all concretely specified and feasibility-checked at three real sites.
- Acceptance criteria and validation quality (20): **20** — AC #5 now asserts the file count and the
  registry's two-hash coverage mechanically; a match with no R-row, a stale file count, or a
  registry entry missing its hash are all failing criteria rather than review-time assumptions.
- Autonomous operation, failure handling, recovery (15): **15** — every gate and clamp remains
  fail-closed; the IOC submission path means no resting order needs cancellation on a gate lapse — a
  venue property already reconciled in prior rounds, not a text defect.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11's evaluation contract, fixed
  baselines, explicit "can REDUCE ROI" row and falsifier are unaffected by this round's change.

**Total: 100/100**

## Required changes

None.

## Blockers (named separately, not scored as deductions)

- **BLOCKER-A** — AUD-06a's validated qty envelope and staleness predicate; the offline sweep driver
  (step 7a) remains scoped but unwritten pending AUD-06a's entry point.
- **BLOCKER-B** — AUD-02's family-scoped edge estimate with a CI excluding 0.
- **BLOCKER-C** — operator ruling, R-12, on the permit's session order-count ceiling.
- **BLOCKER-D** — operator ruling on whether the current per-position cap is still the intended
  per-order spend once qty is derived from it.
