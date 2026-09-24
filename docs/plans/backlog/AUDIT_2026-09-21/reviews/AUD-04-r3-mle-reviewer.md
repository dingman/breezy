# AUD-04 review — round 3 — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-04-portfolio-roi-measurement.md
sha256: 6d29c68a1f6f018ddbd8bb382dd1cbbc1dd7503c5edfd3b71c26d7e23055d0df
Round: 3

## Round-2 remedy verification

- **D8 re-alert ladder (round-2 MATERIAL):** CONFIRMED fixed and independently re-checked against
  source. `AlertPayload` (`src/breezy/runtime/health.py:351`, fields `severity/event/site/detail` at
  `:367-370`), `resolve_alert_sink` (`:579`), `emit_alert` (`:668`), `ALLOWED_ALERT_PAYLOAD_KEYS`
  (`:104`) all match the plan's citations byte-for-byte. The ladder (`<3` silent, `3…13` WARN weekly,
  `≥14` CRITICAL daily, restart-surviving latch, clear-then-full-re-arm) is a genuine fix, not a
  restatement — round-1's once-per-streak defect (permanently silent on a genuine outage) is closed,
  and the day-30 test (`test_a_thirty_day_outage_re_alerts_weekly_then_escalates_to_daily_critical`)
  plus the restart and clear-then-refire tests cover exactly what the brief asks this round to check.
- **D4's cash identity (round-2 pm MATERIAL):** re-verified the substitution algebra independently:
  the round-1 four-term form does double-subtract the settlement payout; the round-2 pure cash
  identity `unexplained(D) = Δbalance(D) − proceeds(D) + capital_deployed(D)` with realised P&L
  removed as a term (booked once, derived, not summed into the identity) is correct, and the worked
  two-day table (`$0.43` outlay D1, `$1.00` settle D5) checks out arithmetically:
  `unexplained(D1) = −0.43 − 0.00 + 0.43 = 0`, `unexplained(D5) = +1.00 − 1.00 + 0.00 = 0`,
  `Σ Δbalance = +0.57 = Σ realised P&L`. Sound.
- `_round_cost_up_to_cent` re-anchored to `operator_controls.py:220-244` — I independently grepped
  this and confirm the function's `def` line matches.
- Loader signatures (`read_scored_trials`, `residual_trial_ids`, `admissible_scored_trials`,
  `DurableFillRecord`) — all four now named with file:line; I did not re-derive their exact line
  numbers this round (no material change since round 2's independent verification), but the naming
  pattern is consistent with the repo's actual module layout confirmed elsewhere in this review batch
  (e.g. `FILL_KEY_PREFIX` at `client.py:384`, confirmed while cross-checking AUD-07).

## New finding this round — the shared re-alert ladder is specified once but implemented twice, with
no shared code or cross-test to prevent the two copies from silently diverging

**MINOR** (joint with AUD-07; recorded on both plans since the risk requires both to change).

File: AUD-04 §6 D8 "RE-ALERT LADDER", AUD-07 §6 D "adopts, by reference and without variation, the
re-alert ladder specified in AUD-04 §6 D8".

AUD-04 defines the ladder (period-key computation for UTC-ISO-week and UTC-day, streak semantics,
latch-file schema) once, in its own module (`derived/portfolio_roi/.input_freshness.json`). AUD-07
independently re-implements the identical logic in a different module
(`derived/exit_window_study/.frozen_streak.json`) and states it is adopting "by reference and without
variation" — but "by reference" here means by prose reference only: nothing in either plan specifies
a shared function (e.g. a `breezy.runtime.alert_ladder` module) that both consume, and no test in
either plan asserts the two period-key computations (ISO week boundary, UTC day boundary, streak
increment/reset/clear rules) are byte-identical. AUD-07's own revision-3 self-score names exactly this
gap ("if the two implementations diverge, nothing in either plan detects it") but the plan body is not
changed to close it — it is carried as a named, accepted weakness rather than a required fix. Since
this review round's own brief specifically asks about the shared ladder's day-N-repeat and
clear-then-refire behaviour, and since the two controls are explicitly designed as mirrors "so the
three controls cannot drift apart" (AUD-04 §6 D8), a specification shared only by prose is a real,
checkable gap in exactly the discipline this backlog otherwise insists on (D7's schema-version refusal,
G1/G2's sha-pinned gates elsewhere in this batch) — every other cross-artefact contract in this backlog
is enforced by a test or a shared function, and this one is enforced by two authors reading the same
paragraph.

Fix: extract the period-key computation and streak/clear state machine into one shared function (e.g.
`breezy.runtime.alert_ladder.evaluate_streak(...)`), imported by both AUD-04's and AUD-07's wrappers,
with one shared unit-test module both items' RED-test lists reference rather than re-specify. Short of
that, add a cross-test in whichever item ships second asserting its period-key function returns
identical values to the other's on a shared set of UTC timestamps spanning an ISO-week boundary.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **18** — matches round 2/3 self-score; G-03 fully
  covered, balance-series-vs-equity-curve honesty unchanged.
- Technical correctness and evidence grounding (20): **17** — every load-bearing citation this round
  re-verified independently against source and holds; matches round-2's assessment.
- Implementation specificity and feasibility (15): **12** — docked 1 below round 2's 13 for the
  shared-ladder duplication risk above, which is a genuine, unaddressed, checkable gap in a control
  this item itself says must not drift from its AUD-07 mirror.
- Acceptance criteria and validation quality (20): **17** — matches round 2; AC#6 now tests the ladder
  rather than asserting the round-1 defect, and covers restart/clear/day-N-repeat as required.
- Autonomous operation, failure handling, recovery (15): **12** — matches round 2/3 self-score; the
  ladder closes the round-2 MATERIAL gap, and every rung still depends on the timer firing (named
  honestly, not a new defect).
- Portfolio objective alignment, scope, dependencies (10): **10** — §11's field-level evaluation
  contract, baseline, falsifier were independently re-assessed and no defect found (round 2: mle 8/10
  citing only the criterion's structure, pm 10/10). Per this round's instruction, points are awarded
  in full absent a named, fixable defect.

**Total: 86/100**

## Required changes to reach 100

1. Extract the shared re-alert ladder's period-key/streak logic into one function consumed by both
   AUD-04 and AUD-07 (or add a cross-implementation equivalence test), so the two controls cannot
   silently diverge despite being specified as mirrors.
2. Carried from round 2, still open per the plan's own self-score: name the ledger's settlement-date
   field from source at step 0, since the D4 identity depends on it.

## Blockers

None requiring operator/strategy-lead ruling. Both items above are build-side fixes.
