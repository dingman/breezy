# AUD-06a — Round 2 review (prediction-market-reviewer, portfolio accounting/risk lens)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-06a-r11-boundary-revalidation.md
SHA256: 97617646201ee5796c0772c29babd37e49b415888fa7357c520fbc0a6716446d
Round: 2
Reviewer: prediction-market-reviewer (independent, blind)

## Round-1 defect disposition verification

- CI method/replication count unspecified (my MINOR): CONFIRMED fixed. §6 "Methodology, pinned" now
  states 20000 reps (grounded — the REGISTERED qty≡1 study's own replication count, not invented),
  Clopper-Pearson exact one-sided 95% upper bound, with the stated consequence (a cell needs
  observed rate ≲0.0232 to enter the envelope).
- No re-validation trigger for `BE`-drift (my MINOR): CONFIRMED fixed and hardened beyond what I
  asked for. §6 "Staleness trigger" records the `BE` prior's `[min,p25,median,p75,max,IQR]` and two
  dimensionless expiry conditions, and — the strengthening — makes the check **fail-closed at the
  consumer** (AUD-06b refuses on a stale envelope) rather than a WARN, which is stronger than what I
  recommended.
- `Var(S)` tolerance unpinned: CONFIRMED fixed, `[0.95,1.05]`, grounded in the registered study's
  observed `[0.98,1.02]` at the same replication count.
- `q_max ≥ 2` threshold asserted without justification: CONFIRMED removed rather than justified —
  the correct disposition, since no threshold can be justified before the sweep runs.

**Independently re-verified the item's central round-1 pivot (mle's MATERIAL finding, which this
plan now rests on):** the xfail reason at `tests/unit/test_multi_position_validation_2026_09_14.py:
161-179` does verbatim record the mechanism the plan now quotes — "higher qty pushes a station-day's
variance up to 9x a single Bernoulli term, so I saturates far faster than the artefact's
n_k/n_max=0.25-per-draw schedule assumes, and the realised-t boundary interpolation undershoots" —
and the surrounding test (`:179-199`) confirms the recorded figures (0.0592/0.058 vs a ~0.011-0.013
qty≡1 control) verbatim. The plan's withdrawal of the "raise the first look's n" remedy is
well-reasoned and consistent with this recorded mechanism (an earlier/later first look relocates,
rather than removes, the undershoot).

## Fresh review of the full revision (new defects)

**MINOR — the "empirical-shaped" qty dispersion class (one of three sweep axes) is named but not
defined, and it is the axis most likely to determine whether the envelope reflects the real live
order-size distribution rather than a synthetic one.**
File: AUD-06a §6 "Sweep axes".
Issue: `q_max`, dispersion (all-equal, two-point, empirical-shaped), and `k` are the three swept
axes. "All-equal" and "two-point" are fully specified by their names; "empirical-shaped" is not — it
presumably means "drawn from the historical realised qty distribution once qty>1 exists," but no
such distribution exists yet (today `order_quantity≡1`), so the plan does not say what "empirical"
means in the absence of empirical data. This is exactly the kind of ambiguity the amendment's own
history note warns is how a misspecified null gets published.
Fix: state explicitly what "empirical-shaped" draws from today (e.g., a synthetic distribution
shaped like AUD-06b's cap-derived `qty = floor(cap/ask/lot)` formula evaluated over the observed ask
distribution, WITHOUT reading the actual cap value) or drop the axis until real qty data exists.

**MINOR — the mechanism-confirmation criterion is monotonicity across cells, but the plan does not
state a minimum number of cells or a statistical test for "monotone increasing," leaving the
CONFIRM/REFUTE call itself judgment-based on a plot rather than machine-checkable.**
File: AUD-06a §6 "How it is tested, not assumed", §7 step 4, §8 AC#3.
Issue: "the mechanism is CONFIRMED if the crossing rate is monotone increasing in `max_k |Δt_k|`
across cells" is a strong, testable claim in principle, but with no minimum cell count, no
tolerance for near-ties, and no statistic (e.g., Spearman rank correlation with a stated threshold),
two implementers could read the same sweep table and reach opposite CONFIRM/REFUTE verdicts. Given
AC#3 requires this verdict to gate whether an envelope is published at all, it should be as
mechanically checkable as the crossing-rate threshold itself.
Fix: pin a concrete statistic (e.g., Spearman ρ > some stated value, or "no cell with near-zero
`Δt_k` exceeds the qty≡1 control's crossing rate by more than its Clopper-Pearson CI width") in
Amendment C's own text.

No MATERIAL defect. The item touches no capital, sizes nothing, and reads no operator-reserved
value; its central analytical claim (the recorded mechanism) is correctly left open until step 4
runs rather than assumed, and the two remedies (envelope; re-solve) are both mechanism-consistent
and correctly ranked.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **18** — squarely addresses R-11/G-11's blocker and tests
  the codebase's own recorded mechanism rather than an invented one. −2 because G-11 also names
  `max_equity_fraction` being unused, correctly deferred to AUD-06b but genuinely outside this
  item's coverage.
- Technical correctness and evidence grounding (20): **18** — registered H0 formulas, the xfail
  mechanism quote, and the amendment's methodology are all independently re-verified verbatim this
  round. −2 for the two open specification gaps above (empirical-shaped dispersion; monotonicity
  statistic), both of which bear directly on whether the published envelope is trustworthy.
- Implementation specificity and feasibility (15): **13** — replications, CI construction, seeds,
  `Var(S)` tolerance, and staleness thresholds are all pinned in Amendment C's own text. −2 for the
  same two gaps (dispersion class definition; monotonicity statistic).
- Acceptance criteria and validation quality (20): **19** — reproduce-first gate, an honest
  stop-and-report refutation branch, no pre-asserted threshold, `q_max=1` an explicit legitimate
  outcome. −1 because AC#3's CONFIRM/REFUTE call is not yet machine-checkable.
- Autonomous operation, failure handling, recovery (15): **14** — correctly forbids a timer; the
  staleness predicate is fail-closed at the consumer, stronger than a WARN. −1 because this item
  ships the predicate but cannot itself enforce AUD-06b actually evaluates it (named honestly in
  §12, not a defect of THIS item beyond the interface risk).
- Portfolio objective alignment, scope, dependencies (10): **10** — §11's three-row plausible-vs-
  demonstrated table explicitly declines the ROI claim, states a numeric baseline, a falsifier and
  the dependency stage; correctly independent of AUD-02. No operator ruling is needed and none is
  sought, so full marks apply here.

**Total: 92/100**

## Required changes to reach 100

1. Define what the "empirical-shaped" qty dispersion class draws from, given no real qty>1 data
   exists yet (or drop the axis).
2. Pin a concrete, machine-checkable statistic for the mechanism CONFIRM/REFUTE monotonicity
   criterion in Amendment C's own text.

## Blockers

None. Fully actionable offline; no operator-reserved value is read, restated, defaulted, or
assigned anywhere in this item, as both round-1 review and this round's independent re-check
confirm.
