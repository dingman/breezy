# AUD-04 — Round 2 review (prediction-market-reviewer, portfolio accounting/risk lens)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-04-portfolio-roi-measurement.md
SHA256: a6c079912ac3b359b1dbf49ecec87df9182118834529c774dcfc6080599b7b8d
Round: 2
Reviewer: prediction-market-reviewer (independent, blind)

## Round-1 defect disposition verification

All 6 round-1 findings from this lens (2 MINOR from me + shared items) are ACTUALLY fixed in the
plan body, not just claimed in §13:

- Two-leg YES+NO capital-deployed test: CONFIRMED added, §7 step 1
  `test_a_no_leg_and_a_yes_leg_fill_on_one_station_day_are_both_counted_in_capital_deployed`, with
  the leg-instrument grounding (`symbology.no_leg_instrument_id:277`, `leg_of:289`) restated
  accurately.
- n=6 power caveat: CONFIRMED, §7 step 3 pins the verbatim header line, §8 AC#3 requires it, a test
  (`test_the_report_header_states_the_sample_size_and_its_power_caveat`) asserts it.
- $0.05 tolerance → derived: CONFIRMED. Re-verified `_round_cost_up_to_cent` at
  `operator_controls.py:220-244` (plan cites `:213-215`; the function actually starts at `:220` —
  trivial line-number drift, the mechanism claimed — shared cent round-up used by both
  `order_cost_usd` and `true_up_booking` — is accurate) and `TOLERANCE_day = n_fills × $0.01` is a
  legitimate derivation from it, not an asserted constant.
- Balance-line parser anchor/regex: CONFIRMED pinned (`AccountState(` token, named-group regex,
  fixture from step 0(c), fail-closed `UNKNOWN`).
- Stale-input-growth detector (mle MATERIAL, I flagged related risk): CONFIRMED, D8
  `PORTFOLIO_ROI_INPUTS_FROZEN`, 3-consecutive-run latch through the delivering sink.
- Schema versioning (mle MATERIAL): CONFIRMED, D7, with an accurate correction of the "no
  precedent" claim — `station_observation.py:110,126,213,234,248` verified to carry exactly the
  declared-field / constructor-default / `to_dict` / `from_dict` / `pa.field(..., nullable=False)`
  idiom the plan says it copies.

No round-1 disposition is misrepresented.

## Fresh review of the full revision (new defects, round-2 lens)

**MINOR — D4's unexplained-flow identity is stated without a worked example, and its four terms
risk a double-count that the plan text alone cannot rule out.**
File: AUD-04 §6 D4.
Issue: `unexplained = Δbalance − (realised P&L settling that day) + (capital deployed that day) −
(proceeds that day)`. On this venue a position is realised by settlement crediting the account
directly (no separate "sell"); if "realised P&L settling that day" is `payout − cost − fee` and
"proceeds that day" is meant to include that same settlement payout, the identity double-subtracts
the payout unless "capital deployed"/"proceeds" are scoped to *same-day-opened* positions only and
"realised P&L" is scoped to *same-day-settled* positions with disjoint fill sets. The plan does not
state that scoping, and a station-day position frequently opens and settles on different dates (the
exit-window study's own multi-day hold times prove this). Without a numeric worked example (one buy
on day 1, one settlement payout on day 5, showing `unexplained == 0` across both days), an
implementer could wire this either way and both would compile and pass a test built from the same
ambiguous prose.
Failure: a sign or scoping error here makes every `UNEXPLAINED_CAPITAL_FLOW` line either
permanently silent (masking a real leak) or permanently noisy (training the operator to ignore it,
the exact WP-R1 false-page failure mode this backlog was opened to close).
Fix: add one worked two-day numeric example to §6 D4 (or the step-0 evidence doc) showing the
identity balances to `0` across an open day and a disjoint settlement day, and state explicitly
that "capital deployed"/"proceeds" are scoped to the SAME fills "realised P&L" is scoped to (i.e.
the three terms partition one set of ledger rows, never two overlapping sets).

**MINOR — loader reuse named by module, not by signature (self-conceded, verified still open).**
File: AUD-04 §7 step 2.
Issue: the scored-trial reader and residual reader are specified as "reuse the loader
`family_tally_v2.py` already imports" / "`residual_trial_ids`" without the function signature, so
the implementer still opens `family_tally_v2.py` to find the exact call shape. Genuinely minor
(confirmed by my own read of `family_tally_v2.py`, the loaders exist and are named accurately) but
it is a real specificity gap, not merely a self-critique for form's sake.
Fix: name the exact loader function signature(s) in §6/§7, e.g.
`family_tally_v2.load_scored_trials(store_dir: Path) -> tuple[ScoredTrial, ...]` (verify the real
name/signature and quote it).

No MATERIAL defect found. The partition invariant (I3), the leg-sum correctness, the fail-closed
`None`-not-`0` posture, the schema-version refusal, and the B0/B1 baseline separation from PREREG
are all sound and independently re-verified this round.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **20** — every element of G-03 covered; the
  balance-vs-equity-curve honesty is a transparent scope statement, not a completeness gap.
- Technical correctness and evidence grounding (20): **18** — Nautilus citations, the rounding
  derivation, and the schema-version precedent all independently re-confirmed against source this
  round. −2 for the D4 identity ambiguity above, which is a genuine correctness risk in an artefact
  whose entire job is catching unexplained money movement.
- Implementation specificity and feasibility (15): **13** — files, timer tick, lock discipline,
  parser anchor, schema policy all pinned. −2 for the unpinned loader signatures and the D4 term
  scoping.
- Acceptance criteria and validation quality (20): **19** — measurable, partition-enforced,
  schema-refusal tested, standing cross-check with AUD-07. −1 because no AC requires the D4 worked
  example / scoping statement to exist.
- Autonomous operation, failure handling, recovery (15): **15** — fail-closed on every input,
  frozen-input detector latched through a delivering sink, `Persistent=true` recovery, no silent
  zero. Fully met.
- Portfolio objective alignment, scope and dependencies (10): **10** — §11 is a complete field-level
  evaluation contract (named JSON fields, two registered baselines fixed before any number is read,
  an explicit falsifier, a stated dependency stage). The item's own ROI contribution is honestly
  "zero, it makes ROI observable" — that is the correct answer for this item's charter, not a
  shortfall. No operator ruling is needed to reach full marks here.

**Total: 95/100**

## Required changes to reach 100

1. Add a worked two-day numeric example to §6 D4 demonstrating the unexplained-flow identity
   balances to zero across an open-day/settlement-day pair, with the three terms' scoping stated
   explicitly (same fill set, never overlapping sets).
2. Name the scored-trial and residual-fill loader function signatures in §6/§7 rather than by
   module reference alone.

## Blockers

None. No operator-reserved value is read or assigned; the baseline choice (B0 headline) is
descriptive, not a PREREG endpoint, and is correctly kept as a build decision rather than escalated.
