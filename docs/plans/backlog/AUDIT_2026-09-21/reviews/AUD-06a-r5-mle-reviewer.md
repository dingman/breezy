# AUD-06a review — round 5 (delta, FINAL) — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-06a-r11-boundary-revalidation.md
sha256: 1c55d80b276cdf7f6b16899b9edde4025ac3e436fcc10de66340b302533d9be3
Round: 5 (re-confirmation of the prior 100/100 against the new revision)

## Change verification

§5 gains one exclusion bullet naming `max_equity_fraction` explicitly and quoting AUD-06b §12's
disposition verbatim (a DECISION, "NOT adopted as a fourth clamp in this increment," with a stated
re-evaluation trigger tied to AUD-04's balance-semantics finding). Independently re-verified against
source before accepting the citation: `max_equity_fraction` is declared at
`src/breezy/strategy/weather_common/risk.py:186` (`max_equity_fraction: float = 0.08`) and applied as
the equity-notional clip at `:698-699` under the guard the plan describes (`order_notional >
limits.max_equity_fraction * equity`, inside the branch reached after `equity <= 0.0`/`equity is None`
refusals) — CONFIRMED exact. This was a round-4, pm-only finding (not mine); this item's own MATERIAL
defect from prior rounds was already closed and re-verified in my round-4 pass.

## Re-confirmation — no defect found

This is a single, small, additive change (one exclusion bullet, quoting rather than re-deciding
AUD-06b's disposition). It does not touch the grid, the compute budget, the resumability mechanism, the
`side_mix` axis, or any of the statistical machinery reviewed and confirmed defect-free across rounds
2-4. I re-read the full plan once more this round, per the coordinator's instruction to re-confirm rather
than assume, and found nothing new: the citation is exact, the disposition is correctly attributed to
AUD-06b (not re-decided here), and no scope, threshold, or acceptance criterion was altered.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **20** — the G-11 cross-reference gap (a reader having to
  infer where `max_equity_fraction` is dispositioned) is now closed by an explicit, source-verified
  mapping rather than left implicit.
- Technical correctness and evidence grounding (20): **20** — citation independently re-verified exact.
- Implementation specificity and feasibility (15): **15** — unaffected by this change.
- Acceptance criteria and validation quality (20): **20** — unaffected by this change.
- Autonomous operation, failure handling, recovery (15): **15** — unaffected by this change.
- Portfolio objective alignment, scope, dependencies (10): **10** — unaffected by this change.

**Total: 100/100**

## Remaining defects and required changes

None.

## Blockers

None requiring operator/strategy-lead ruling. Unchanged across all five rounds: this item is
deliberately constructed so no operator-reserved value enters the analysis.
