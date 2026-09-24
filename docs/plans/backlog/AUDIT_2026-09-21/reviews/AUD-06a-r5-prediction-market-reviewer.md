# AUD-06a — Round 5 (FINAL) — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-06a-r11-boundary-revalidation.md
sha256: 1c55d80b276cdf7f6b16899b9edde4025ac3e436fcc10de66340b302533d9be3
Round: 5 (final)
Reviewer: prediction-market-reviewer (portfolio accounting / risk)

## Claim verified: §5 now names `max_equity_fraction` explicitly and cites AUD-06b's disposition

Read from source before checking the plan's claims: `max_equity_fraction` is declared at
`src/breezy/strategy/weather_common/risk.py:186` (`max_equity_fraction: float = 0.08`) and applied
as the equity-notional clip at `:698-699` (`if order_notional > limits.max_equity_fraction * equity:
clipped = (limits.max_equity_fraction * equity) / max(contract.contract_size, 1e-9)`), under the
`signed_qty_delta > 0` guard read one line above — CONFIRMED, both citations exact.

§5's new bullet is present in the plan body (not only §13): it names `max_equity_fraction`
specifically, cites both source lines, notes that §2's `weather_common/equity.py` attribution
follows G-11's own wording while the field actually lives in `risk.py` (an honest correction rather
than a propagated error), and quotes AUD-06b §12's disposition verbatim — a **DECISION**, "NOT
adopted as a fourth clamp in this increment" because its denominator is the UNVERIFIED
`currentBalance` semantics (T-4 §4), with the named re-evaluation trigger tied to AUD-04's
balance-semantics finding. The bullet states explicitly that this item "neither adopts, re-litigates
nor re-decides that disposition; it is recorded here only so a reader checking G-11 element by
element reads the mapping instead of inferring it."

This closes exactly the gap named in round 4: the mapping is now explicit rather than left to
inference from the generic "no sizing code" exclusion, and no new scope, capability or value is
introduced — it is a pure cross-reference. I verified AUD-06b §12 does in fact carry the DECISION
text as quoted (re-confirmed in my own AUD-06b round-4 review this cluster).

## Re-check of the rest of the plan (no regression)

The 320-cell grid enumeration, the step-4a calibration (`τ_cell`, the 6-wall-hour chunking gate),
and the explicit "reasoned, not inherited" threshold-provenance statement — all verified in my prior
round's review — are untouched by this revision's diff. No regression found. This was the only
change (per §13's own disposition and confirmed by reading the full document).

## Defects

None MATERIAL, none MINOR remaining. The single carried defect (an implicit rather than explicit
scope mapping for `max_equity_fraction`) is closed with a precise, source-grounded cross-reference
that adds no new scope and re-decides nothing.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **20** — R-11/G-11's `Var(S)` blocker is fully addressed
  against the codebase's own recorded mechanism, and G-11's `max_equity_fraction` element is now
  explicitly mapped to its actual owner and disposition rather than left to inference. Both named
  elements of the source finding are accounted for by this plan, even though only one is delivered
  by it — the other is correctly and now explicitly deferred.
- Technical correctness and evidence grounding (20): **20** — every formula, line reference and sign
  argument re-verified this round and in prior rounds; the new citations (`risk.py:186`, `:698-699`)
  are exact.
- Implementation specificity and feasibility (15): **15** — reps, CI, seeds, tolerance, dispersion
  classes, `side_mix` axis, verdict statistic, cell ordering, chunk interface, resume protocol and
  memory contract remain fully pinned; the scope-mapping addition is precise and non-speculative.
- Acceptance criteria and validation quality (20): **20** — reproduce-first gate, the three-outcome
  verdict, the measured-budget criterion and the threshold-provenance criterion are all intact and
  unaffected by this round's change.
- Autonomous operation, failure handling, recovery (15): **15** — correctly forbids a standing timer;
  the staleness predicate is fail-closed at its one real consumer, independently verified in AUD-06b.
- Portfolio objective alignment, scope, dependencies (10): **10** — §11's enabling chain, numeric
  baseline and falsifier are concrete; no operator-reserved value enters the analysis anywhere in
  this plan.

**Total: 100/100**

## Required changes

None.

## Blockers

None. No operator or strategy-lead ruling is required for this item's own scope.
