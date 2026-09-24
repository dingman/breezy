# AUD-04 review — round 5 (delta, FINAL) — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-04-portfolio-roi-measurement.md
sha256: cf97bd4661a367b267a8bd2f077b171ea02b90f0152ed65fec69ceb0d568c711
Round: 5 (delta review of the round-4-named defect's fix)

## Fix verification: settled-through cutoff

§6 D4 now defines `SETTLED_THROUGH = D_now − max(7, observed p99 settlement_lag_days)`, with the `7`
floor read from `_SEVEN_DAYS_NS` at `trial_scorer.py:243` (independently re-confirmed) and the p99 from
step 0(f)'s measured distribution. The cumulative `Σ_D unexplained` pass/fail applies only to
`D ≤ SETTLED_THROUGH`; later days are computed, printed, labelled `PROVISIONAL_IN_FLIGHT`, and excluded
from the pass/fail determination, with their own tail sum printed separately as a non-gating figure.

**Coordinator question 1 — can a permanently unscored settlement sit in the provisional tail forever?**
NO, and the design is correct: `SETTLED_THROUGH` is a **fixed calendar-day cutoff relative to `D_now`**,
which advances every report run. A settlement's true credit day `D_credit` is a fixed historical date
(observed empirically via the balance parser, independent of whether it has been scored). As `D_now`
advances, `SETTLED_THROUGH` advances with it, so any fixed `D_credit` eventually crosses from the
provisional tail into the gated window and — if still unscored, contributing `proceeds(D_credit) = 0` —
produces a genuine, gating breach. This is not merely a design argument: I re-read §7 step 1's new test
`test_an_in_flight_settlement_inside_the_settled_through_window_does_not_fail_the_cumulative_check`
directly, and its **anti-suppression half is exactly this scenario** — the identical unscored-settlement
fixture placed at `D ≤ SETTLED_THROUGH` (i.e., aged past the cutoff) must still FAIL. This is the correct
test for the self-cleaning property, not a weaker one. **No residual gap on this question.**

**Coordinator question 2 — is a p99 over a handful of settlements an honest quantity, or should it be
max / a stated minimum-n rule?** This is a genuine, unaddressed gap. The live record has on the order of
six settled fills (confirmed elsewhere in this review batch — AUD-04 §8 AC#3's own header line: `n=<k>
settled fills over <d> days`). A 99th-percentile computed over `n≈6` observations is not a meaningfully
calibrated tail estimate: with so few samples, "p99" either collapses to the sample maximum (if the
percentile implementation clips to observed range) or, under linear-interpolation percentile methods
(the common default, e.g. NumPy's), can produce a value **below** the true maximum by interpolating
between the two highest observations — which would make the cutoff narrower than the worst lag actually
observed, silently reintroducing exactly the false-positive risk the cutoff exists to prevent. The plan
states the p99 is "read from the step-0(f) measured distribution (never a literal)" but nowhere states a
minimum sample size below which a percentile is not a meaningful statistic, nor does it fall back to
`max()` at small `n`. This is unaddressed by the round-5 revision and is a **new, concrete, fixable
defect introduced by (or rather, surfaced by) the fix itself** — the original round-4 defect (no cutoff
at all) is closed, but the cutoff's own statistical construction has a small-sample flaw.

## Fresh review — no other new defect found

I re-checked the worked two-day example, the `test_a_breach_explained_entirely_by_proxy_lag_is_classified_not_netted`
test, and AC #12's wording — all consistent with the fix as described, no drift from source citations.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **20** — unaffected by the cutoff fix or its residual gap.
- Technical correctness and evidence grounding (20): **19** — the cutoff's algebra and self-cleaning
  property are independently verified correct; 1 point withheld for the unaddressed small-`n` percentile
  construction (see required change below).
- Implementation specificity and feasibility (15): **15** — unaffected.
- Acceptance criteria and validation quality (20): **19** — AC #12 and its test correctly prove the
  cutoff and the self-cleaning property; 1 point withheld because no AC/test exercises the small-`n`
  case (e.g. a synthetic corpus with `n<20` lag observations), tied to the same defect above.
- Autonomous operation, failure handling, recovery (15): **15** — unaffected.
- Portfolio objective alignment, scope, dependencies (10): **10** — unaffected.

**Total: 98/100**

## Remaining defect and required change

1. **MINOR.** `SETTLED_THROUGH`'s `observed p99 settlement_lag_days` term has no stated minimum-sample
   rule. At the live record's current sample size (`n≈6`), a 99th percentile is not a well-calibrated
   tail estimate and, depending on the interpolation method, can understate the true observed maximum
   lag — which would narrow the cutoff below the worst lag actually seen, reintroducing the
   false-positive risk the cutoff exists to close. **Required change:** state a minimum-`n` rule in §6
   D4 (e.g. "when the step-0(f) sample has fewer than 20 settlement_lag_days observations, `SETTLED_THROUGH`
   uses `max(observed settlement_lag_days)` in place of `p99`, and the artefact header states which
   statistic was used and the observed `n`"), and add a RED test exercising the small-`n` fallback with
   a synthetic corpus below the stated threshold.

## Blockers

None requiring operator/strategy-lead ruling.
