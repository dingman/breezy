# Adversarial review record — DTC pre-registration, revision 1

- **Artifact reviewed:** `docs/evidence/decision_time_clearance_prereg_2026-08-27.md`, revision 1 (910 lines)
- **Date:** 2026-08-27
- **Requested by:** §11 of the artifact, which states that a bare APPROVE constitutes a *failed* review
- **Verdict:** **BLOCK** — 6 CRITICAL, 9 HIGH, 10 MEDIUM, 3 LOW
- **Disposition:** all ten blocking items discharged in revision 2, §15, as pre-declared amendments `[D1]`-`[D10]`. Re-review pending, scoped by the reviewer's own instruction to those ten items rather than the whole document.

Nothing had been computed at the time of review, and nothing has been computed
since. This record exists so that what was pre-registered, and what was found
wrong with it, are both fixed in the record before any statistic exists to
argue about.

## The single mechanism behind the findings

§5.3 correctly replaced the parent's ladder `θ = rounded_metar_max − margin`
with an independent climatological ladder, because the parent's construction
*is* the hindsight the study exists to remove. But four rules were transcribed
from the parent as constants and predicates **without their generating
mechanisms**, and those mechanisms depended on the old ladder. The document
reproduced, inside itself, the inherited-reasoning defect it was written to
avoid.

## Verified independently before acceptance

Every code and line citation below was checked against the source by the
coordinator before the review was acted on. All four spot-checks confirmed the
reviewer verbatim:

| claim | location | verified |
|---|---|---|
| `hit` is one-sided, not an agreement predicate | `settlement_alignment_study.py:313-315` | yes |
| `bucket_for_margin` labels the **margin**, not a measured clearance | `settlement_alignment_study.py:200-207` | yes |
| `fetch_text_cached` does `mkdir` + `client.get` on cache miss | `settlement_alignment_study.py:343-353` | yes |
| parent declares a **per-city** determination with the 2-of-5 rule layered above it | `asymmetric_gate_prereg_2026-08-26.md:842-860` | yes |

## CRITICAL

- **C1 — the mandated agreement predicate does not measure agreement under the
  new ladder.** `hit = label.tmax_f >= threshold` coincides with settlement
  agreement only because `θ` is built from the METAR max itself. Under §5.3's
  independent ladder it measures `P(CLI tmax ≥ θ)` ≈ 0.5, so F2 would fire
  everywhere and the study would return a **false NO-GO carrying §9.1's
  terminating language**. → `[D1]`
- **C2 — F3 cannot fire.** 13 integer strikes per city-day, at most 2 excluded
  by a ±1.0 °F admission rule ⇒ `RET ≈ 11/13 ≈ 0.846` arithmetically, always.
  The 0.25 constant was transcribed from a 12.97% collapse caused by
  *whole-city-day* exclusion — a different mechanism. → `[D4]`
- **C3 — P2's conservatism is algebraically inverted for half the boundary
  population.** `K_hat_2 = |(M_obs + R̂) − θ|` moves the estimate *away* from the
  strike whenever `θ < M_obs`. Since `R̂` is the p90, this is systematic on ~90%
  of days, and raising the quantile makes it worse. → `[D2]`
- **C4 — every interval treats 13 correlated strikes per city-day as
  independent.** Effective `n` inflated ~13×, intervals ~3.6× too narrow, and
  the harm falls in the **permissive** direction on F2's lower bound. → `[D3]`
- **C5 — the transcribed anchors are 0.5 °F misaligned.** The
  0.7800–0.8334 figures label the margin-0 bucket `[0, 0.5]`, not the `[0,1)`
  stratum §5.4 defines; the wider stratum's rate is necessarily higher. §2's
  premise for inverting the brief's question therefore rests on a stratum that
  **has never been measured**. → `[D5]`, discharged as prerequisite P1
- **C6 — "no network fetch at all" is contradicted by the code the document
  mandates reusing.** A cache miss creates the directory and issues an HTTP GET,
  which would silently mix a 2026-08-27 snapshot into a 2026-08-25 study. → `[D6]`

## HIGH

- **H1** — F2 diluted to near-unfailable by the ±6 °F ladder; binds on the
  pooled admitted set where strikes 3–7 °F from the max agree trivially. → `[D4]`
- **H2** — §9.1's "regardless of any hindsight-stratified statistic any tape
  could produce" claims more than the computation can support; §3.2 already
  established the forecast-estimator class is untestable here. → `[D7]`
- **H3** — F4 pairs a **p90** statistic with a **central-tendency** rationale,
  and its pooling basis is unpinned on the criterion that terminates the
  programme. → `[D7]`
- **H4** — `R̂` marked "available at T" though leave-one-year-out includes
  **future** years; §5.3 states this honestly for the ladder, §6.3 does not for
  the identical construction. → `[D8]`
- **H5** — purity test B is unpassable as specified: garbling all post-T
  observations destroys the `R̂` fit the test holds constant, so the test halts
  the study by construction and would be silently rescoped. → `[D8]`
- **H6** — the parent's `[R3]` **per-city determination** was dropped, keeping
  only the programme rule. A city leaking at 0.45 alongside three clean cities
  would draw no adverse verdict, making §8.4's MDW paragraph exactly the theatre
  `[R3]` abolished. **More permissive than the parent.** → `[D9]`
- **H7** — §5.3's "favourable to the proxy" bias direction is asserted, not
  derived, and is probably inverted; a better-centred ladder *enlarges* the
  boundary population. The sentence is load-bearing: it is the reason a failure
  would be read as real rather than as artifact. → `[D10]`
- **H8** — `R̂` refit under LAG = 45 unspecified, confounding information loss
  with estimator mis-specification. → `[D8]`
- **H9** — P0 under-specified: no manifest **re-verification** at run start (the
  realistic failure is corruption, not absence), and the fourth script — the one
  that owns the fetch helpers — was left aimed at a non-existent directory. → `[D6]`

## MEDIUM and LOW

M1 (LAG = 45 cannot fire a criterion), M2 (Holm step-down unimplementable as
written; F4 outside multiplicity control), M3 (F2/F3 failure has no declared
programme consequence — **the rescue channel**), M4 (COR incidence *is*
measurable; §12.1 overstates), M5 (§12.3 threshold left blank), M6 (parent's
absolute sample floors dropped without note), M7 (`M_final` comparison basis
unpinned), M8 (retained city-day fraction identically 1), M9 (quantile estimator
unpinned), M10 (stale archive path); L1 (precision floor non-binding by two
orders of magnitude), L2 (`DecisionSnapshot` unguarded on `T`), L3 (import
contract misses the shortest leak path).

M3 was promoted into the blocking set as part of `[D10]`: with F3 inert and F2
diluted, the most likely non-terminating outcome was a marginal F2 result routing
to a pre-authorised sweep of the admission cut-off — the accumulated-near-miss
channel §11 Q6 exists to close. The remainder are folded in §15.1.

## What the review found sound

The inversion of the brief's question is legitimate **in form** (its premise is
corrected by `[D5]`, not its logic); the `[R8]` non-transfer argument in §6.4 is
correct and correctly scoped; the ladder substitution itself is mandatory and
right; the primary-cell pinning in §8.1–§8.2 is a genuinely closed selection
surface; §9.2's scoping and §8.3's pre-declared prediction are real anti-rescue
devices; §12.2's venue-ladder under-estimate argument is the document at its
best and is retained unchanged.

## The risk this changed

The brief anticipated a study that might **rescue** a strategy that should die.
The review found the opposite exposure: as specified, revision 1 was more likely
to **over-kill** — terminating on F4's mismatched statistic or on a `LEAK`
inflated by C3's laundering defect, then attaching §9.1's over-broad language to
that result. A wrong terminating verdict on a strategy that may well deserve to
die is still a wrong verdict, and it would enter this programme as settled fact.

## Coordinator's own contribution to the defects

`[D5]` traces to the coordinator: the "STRUCTURALLY UNREACHABLE" figures were
relayed as `[0,1)` stratum rates when they are margin-0 bucket rates, and that
error was carried into the brief that produced revision 1. `[D2]`'s framing
premise was likewise supplied by the coordinator and correctly inverted by the
author before review.
